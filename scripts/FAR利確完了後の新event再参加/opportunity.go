package far91

import (
	"fmt"
	"math"
)

const OpportunityKind = "E1順行再開機会"
const OpportunityRuleVersion = 1
const OpportunityReason = "現在E1の公開event出典を固定"

// OpportunityKey は実参加serialを含めず、元参照ごとのeventを識別します。
type OpportunityKey struct {
	Session     string `json:"session"`
	ReferenceID string `json:"reference_id"`
	EventID     string `json:"event_id"`
}

// OpportunityPublication は元Recordを一度だけ参照する公開時計と原行の値コピーです。
type OpportunityPublication struct {
	ObservationID int64   `json:"observation_id"`
	Ordinal       int64   `json:"ordinal"`
	At            float64 `json:"at"`
	BarEnd        float64 `json:"bar_end"`
	Origin        string  `json:"origin"`
	Quote         Quote   `json:"quote"`
}

// EntryOpportunity は現在E1の当時出典だけで、前回の実損益や完了を含みません。
type EntryOpportunity struct {
	Known         bool                     `json:"known"`
	Kind          string                   `json:"kind"`
	RuleVersion   int                      `json:"rule_version"`
	At            float64                  `json:"at"`
	ReferenceID   string                   `json:"reference_id"`
	Side          int                      `json:"side"`
	OpportunityID OpportunityKey           `json:"opportunity_id"`
	Event         ResumeEvent              `json:"event"`
	Publications  []OpportunityPublication `json:"publications"`
	Reason        string                   `json:"reason"`
}

// EntryOpportunityLevel は候補のeventを一度だけ保持し、遅延別金融判断を結びます。
type EntryOpportunityLevel struct {
	At           float64                      `json:"at"`
	ReferenceID  string                       `json:"reference_id"`
	RawRank      int                          `json:"raw_rank"`
	SuppliedRank int                          `json:"supplied_rank"`
	Opportunity  EntryOpportunity             `json:"opportunity"`
	Assessments  map[string]ReentryAssessment `json:"assessments"`
}

// opportunityFinite は保存する時計と価格の有限性を確認します。
//
// 引数: values(...float64)は公開値です。
// 返り値: boolは全値が有限なら真です。
func opportunityFinite(values ...float64) bool {
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return false
		}
	}
	return true
}

// BuildEntryOpportunity は現在のE1資格と公開済み全pointを候補の機会へ固定します。
//
// 引数: session(string)、at(float64)、q(Quote)、reference(ReferenceLot)、direction(EntryDirectionEvaluation)、records(map[int64]EventRecord)は当時の場/要求/原行/候補/現在E1/公開索引です。
// 返り値: EntryOpportunityは値型の出典、errorは既知E1なのに出典が欠落・未来・不整合の場合です。
func BuildEntryOpportunity(session string, at float64, q Quote, reference ReferenceLot, direction EntryDirectionEvaluation, records map[int64]EventRecord) (EntryOpportunity, error) {
	bad := func(reason string) (EntryOpportunity, error) {
		return EntryOpportunity{}, fmt.Errorf("E1機会の出典不整合:%s", reason)
	}
	if session == "" || !opportunityFinite(at, q.Time, q.Last, q.Bid, q.Ask) || at <= 0 || q.Time <= 0 || q.Time > at || at-q.Time > 15 || q.Index < 0 || q.Line <= 0 ||
		!q.Valid || q.Last <= 0 || q.Bid <= 0 || q.Ask <= q.Bid ||
		reference.ID == "" || (reference.Side != 1 && reference.Side != -1) || direction.Side != reference.Side ||
		!direction.CurrentKnown || !direction.CurrentAllowed || direction.RequiredUnknown || direction.EventRequiredUnknown || !direction.E1Allowed || !direction.EventValid || direction.Event == nil {
		return bad("現在のE1/候補/原行")
	}
	event := *direction.Event
	if event.ID == "" || event.Side != reference.Side || !opportunityFinite(event.EpochStart) || event.EpochStart <= 0 || event.EpochStart >= at ||
		(event.Window != "D164_15" && event.Window != "P164_06" && event.Window != "U165_03") {
		return bad("eventの側/窓/epoch")
	}
	points := []EventPoint{event.Impulse, event.Pullback, event.Recovery, event.Confirmation}
	for _, point := range points {
		if point.ObservationID <= 0 || !opportunityFinite(point.BarEnd, point.PublishedAt) || point.BarEnd <= event.EpochStart || point.BarEnd > point.PublishedAt || point.PublishedAt > at {
			return bad("eventの公開点")
		}
	}
	i, p, r, k := points[0], points[1], points[2], points[3]
	if !(i.BarEnd < p.BarEnd && p.BarEnd < r.BarEnd && r.BarEnd <= k.BarEnd &&
		i.PublishedAt <= p.PublishedAt && p.PublishedAt <= r.PublishedAt && r.PublishedAt <= k.PublishedAt &&
		i.ObservationID < p.ObservationID && p.ObservationID < r.ObservationID && r.ObservationID <= k.ObservationID) ||
		(r.BarEnd == k.BarEnd) != (r == k) || at-k.BarEnd >= 900 {
		return bad("i<p<r<=k又は既存期限")
	}
	publications := []OpportunityPublication{}
	var previousOrdinal, previousID int64
	for _, point := range points {
		if point.ObservationID == previousID {
			continue
		}
		record, ok := records[point.ObservationID]
		if !ok {
			return bad("公開Record欠落")
		}
		in := record.Input
		if record.ID != point.ObservationID || in.Ordinal <= previousOrdinal || in.AfterEOF || in.Window != event.Window || in.EpochStart != event.EpochStart ||
			in.At != point.PublishedAt || in.Technical.Bar3End != point.BarEnd || !opportunityFinite(in.Technical.Close3) || in.Technical.Close3 <= 0 ||
			!opportunityFinite(in.Quote.Time, in.Quote.Last, in.Quote.Bid, in.Quote.Ask) || in.Quote.Time <= 0 || in.Quote.Time > in.At || in.Quote.Time > q.Time ||
			in.Quote.Index < 0 || in.Quote.Index > q.Index || in.Quote.Line <= 0 || in.Quote.Line > q.Line || in.Quote.Last <= 0 ||
			(in.Origin != "quote" && in.Origin != "three_timer" && in.Origin != "core_timer") {
			return bad("公開Recordの時計/ordinal/元原行")
		}
		publications = append(publications, OpportunityPublication{ObservationID: record.ID, Ordinal: in.Ordinal, At: in.At, BarEnd: in.Technical.Bar3End, Origin: in.Origin, Quote: in.Quote})
		previousOrdinal, previousID = in.Ordinal, point.ObservationID
	}
	return EntryOpportunity{Known: true, Kind: OpportunityKind, RuleVersion: OpportunityRuleVersion, At: at, ReferenceID: reference.ID, Side: reference.Side,
		OpportunityID: OpportunityKey{Session: session, ReferenceID: reference.ID, EventID: event.ID}, Event: event, Publications: publications, Reason: OpportunityReason}, nil
}

// indexEventRecord は公開append直後のRecordを場内IDへ一度だけ値コピーします。
//
// 引数: record(EventRecord)は今回の疎な公開観測です。
// 返り値: errorは欠番・重複・ordinal後退です。数値器や金融は呼びません。
func (r *replayRuntime) indexEventRecord(record EventRecord) error {
	if r.eventIndex == nil {
		r.eventIndex = map[int64]EventRecord{}
	}
	if record.ID != int64(len(r.eventIndex)+1) || record.Input.Ordinal <= 0 {
		return fmt.Errorf("機会の公開索引IDが欠番又は重複")
	}
	if previous, ok := r.eventIndex[record.ID-1]; ok && previous.Input.Ordinal >= record.Input.Ordinal {
		return fmt.Errorf("機会の公開索引ordinal後退")
	}
	r.eventIndex[record.ID] = record
	return nil
}

// opportunityCandidates はE1実供給の出典を全会計共通で一度だけ固定します。
//
// 引数: grid(GridDecision)、supplied(ReadSnapshot)、pool([]PoolEvaluation)は当時E1の純部分列です。
// 返り値: map[string]EntryOpportunity/[]EntryOpportunityLevel/errorは金融入力と共有候補又は出典不整合です。
func (r *replayRuntime) opportunityCandidates(grid GridDecision, supplied ReadSnapshot, pool []PoolEvaluation) (map[string]EntryOpportunity, []EntryOpportunityLevel, error) {
	opportunities := map[string]EntryOpportunity{}
	levels := []EntryOpportunityLevel{}
	for rank, row := range supplied.Lots {
		ref := row.Reference
		var evaluation *PoolEvaluation
		for n := range pool {
			if pool[n].ReferenceID == ref.ID {
				evaluation = &pool[n]
				break
			}
		}
		var direction *EntryDirectionEvaluation
		for n := range grid.Entry.Directions {
			if grid.Entry.Directions[n].Side == ref.Side {
				direction = &grid.Entry.Directions[n]
				break
			}
		}
		if !grid.ClockAllowed || evaluation == nil || !evaluation.Allowed || evaluation.SuppliedRank == nil || *evaluation.SuppliedRank != rank+1 ||
			direction == nil || direction.Event == nil || evaluation.EventID != direction.Event.ID {
			return nil, nil, fmt.Errorf("E1実供給候補の機会出典が不整合")
		}
		if _, duplicate := opportunities[ref.ID]; duplicate {
			return nil, nil, fmt.Errorf("機会の参照ID重複")
		}
		opportunity, err := BuildEntryOpportunity(r.session.ID, grid.At, r.last, ref, *direction, r.eventIndex)
		if err != nil {
			return nil, nil, err
		}
		for _, publication := range opportunity.Publications {
			if publication.Ordinal > r.ordinal {
				return nil, nil, fmt.Errorf("公開索引へ未来のordinalが混入")
			}
		}
		opportunities[ref.ID] = opportunity
		levels = append(levels, EntryOpportunityLevel{At: grid.At, ReferenceID: ref.ID, RawRank: evaluation.RawRank, SuppliedRank: rank + 1, Opportunity: opportunity, Assessments: map[string]ReentryAssessment{}})
	}
	return opportunities, levels, nil
}
