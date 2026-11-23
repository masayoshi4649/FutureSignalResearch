package far90

import (
	"fmt"
	"math"
)

const PullbackKind = "押戻し確定終値固定床"
const PullbackRuleVersion = 1
const PullbackTick = 10.0

// PullbackAnchor は要求時に固定する最新押しCloseと元eventの公開出典です。
// 金融Bookへ追加tagを持ち込まず、共有sidecarと金融境界で使います。
type PullbackAnchor struct {
	Known           bool        `json:"known"`
	Kind            string      `json:"kind"`
	RuleVersion     int         `json:"rule_version"`
	At              float64     `json:"at"`
	ReferenceID     string      `json:"reference_id"`
	Side            int         `json:"side"`
	Event           ResumeEvent `json:"event"`
	PullbackOrdinal int64       `json:"pullback_ordinal"`
	PullbackOrigin  string      `json:"pullback_origin"`
	PullbackQuote   Quote       `json:"pullback_quote"`
	Close           float64     `json:"close"`
	Tick            float64     `json:"tick"`
	Price           float64     `json:"price"`
	Reason          string      `json:"reason"`
}

// PullbackLevel は定時/ref候補ごとのanchorを全会計へ重複せず保存します。
type PullbackLevel struct {
	At           float64        `json:"at"`
	ReferenceID  string         `json:"reference_id"`
	RawRank      int            `json:"raw_rank"`
	SuppliedRank int            `json:"supplied_rank"`
	Anchor       PullbackAnchor `json:"anchor"`
}

// pullbackFinite は検査に用いる価格と時計の有限性を確認します。
//
// 引数: values(...float64)は価格/時計です。
// 返り値: boolは全値が有限なら真です。
func pullbackFinite(values ...float64) bool {
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return false
		}
	}
	return true
}

// BuildPullbackAnchor は公開済みpRecordを元eventへ結び、逆側10ptの価格線を固定します。
//
// 引数: at(float64)、reference(ReferenceLot)、event(ResumeEvent)、record(EventRecord)は要求時計/候補/元event/公開済みpです。
// 返り値: PullbackAnchorは値型の固定線、errorは既知E1出典の欠落・未来・数値/順序不整合です。
func BuildPullbackAnchor(at float64, reference ReferenceLot, event ResumeEvent, record EventRecord) (PullbackAnchor, error) {
	bad := func(reason string) (PullbackAnchor, error) {
		return PullbackAnchor{}, fmt.Errorf("押戻し固定床の出典不整合:%s", reason)
	}
	if !pullbackFinite(at, event.EpochStart) || at <= 0 || reference.ID == "" || (reference.Side != 1 && reference.Side != -1) ||
		event.ID == "" || event.Side != reference.Side || event.EpochStart <= 0 || event.EpochStart >= at ||
		(event.Window != "D164_15" && event.Window != "P164_06" && event.Window != "U165_03") {
		return bad("要求時計/候補/event")
	}
	points := []EventPoint{event.Impulse, event.Pullback, event.Recovery, event.Confirmation}
	for _, point := range points {
		if point.ObservationID <= 0 || !pullbackFinite(point.BarEnd, point.PublishedAt) ||
			point.BarEnd <= event.EpochStart || point.BarEnd > point.PublishedAt || point.PublishedAt > at {
			return bad("event点の公開時計")
		}
	}
	i, p, r, k := points[0], points[1], points[2], points[3]
	if !(i.BarEnd < p.BarEnd && p.BarEnd < r.BarEnd && r.BarEnd <= k.BarEnd &&
		i.PublishedAt <= p.PublishedAt && p.PublishedAt <= r.PublishedAt && r.PublishedAt <= k.PublishedAt &&
		i.ObservationID < p.ObservationID && p.ObservationID < r.ObservationID && r.ObservationID <= k.ObservationID) ||
		(r.BarEnd == k.BarEnd) != (r == k) || at-k.BarEnd >= 900 {
		return bad("i<p<r<=k又は再開期限")
	}
	in, tech := record.Input, record.Input.Technical
	if record.ID != p.ObservationID || in.Ordinal <= 0 || in.AfterEOF || in.Window != event.Window || in.EpochStart != event.EpochStart ||
		in.At != p.PublishedAt || tech.Bar3End != p.BarEnd || !pullbackFinite(tech.Close3, in.At, in.Quote.Time, in.Quote.Last, in.Quote.Bid, in.Quote.Ask) || tech.Close3 <= 0 ||
		in.Quote.Time <= 0 || in.Quote.Time > in.At || in.Quote.Index < 0 || in.Quote.Line <= 0 || in.Quote.Last <= 0 ||
		(in.Origin != "quote" && in.Origin != "three_timer" && in.Origin != "core_timer") {
		return bad("pRecordと公開pointの結合")
	}
	price := tech.Close3 - float64(reference.Side)*PullbackTick
	if !pullbackFinite(price) || price <= 0 {
		return bad("価格線が正の有限値でない")
	}
	// ----------------------------------------
	// BBOの品質や価格格子を新たに入口条件へ加えず、固定offsetだけを使います。
	return PullbackAnchor{Known: true, Kind: PullbackKind, RuleVersion: PullbackRuleVersion, At: at, ReferenceID: reference.ID, Side: reference.Side,
		Event: event, PullbackOrdinal: in.Ordinal, PullbackOrigin: in.Origin, PullbackQuote: in.Quote,
		Close: tech.Close3, Tick: PullbackTick, Price: price, Reason: PullbackExitReason}, nil
}

// indexEventRecord は公開append直後の値型Recordを場内IDへ一度だけ登録します。
//
// 引数: record(EventRecord)は今回公開した疎な観測です。
// 返り値: errorは欠番・重複・ordinal後退です。元数値器や金融を呼びません。
func (r *replayRuntime) indexEventRecord(record EventRecord) error {
	if r.eventIndex == nil {
		r.eventIndex = map[int64]EventRecord{}
	}
	if record.ID != int64(len(r.eventIndex)+1) || record.Input.Ordinal <= 0 {
		return fmt.Errorf("公開event索引のID欠番又は重複")
	}
	if previous, ok := r.eventIndex[record.ID-1]; ok && previous.Input.Ordinal >= record.Input.Ordinal {
		return fmt.Errorf("公開event索引のordinal後退")
	}
	r.eventIndex[record.ID] = record
	return nil
}

// pullbackCandidates はE1実供給の各候補へ同定時のp価格を固定して一度保存します。
//
// 引数: grid(GridDecision)、supplied(ReadSnapshot)、pool([]PoolEvaluation)は旧E1 filterの値です。
// 返り値: map[string]PullbackAnchorとerrorは候補別固定値又は既知出典の欠落です。
func (r *replayRuntime) pullbackCandidates(grid GridDecision, supplied ReadSnapshot, pool []PoolEvaluation) (map[string]PullbackAnchor, error) {
	anchors := map[string]PullbackAnchor{}
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
			direction == nil || !direction.E1Allowed || !direction.EventValid || direction.Event == nil || evaluation.EventID != direction.Event.ID {
			return nil, fmt.Errorf("E1実供給候補と当時eventが不整合")
		}
		if _, duplicate := anchors[ref.ID]; duplicate {
			return nil, fmt.Errorf("固定床の候補参照ID重複")
		}
		var previousOrdinal int64
		var previousID int64
		for _, point := range []EventPoint{direction.Event.Impulse, direction.Event.Pullback, direction.Event.Recovery, direction.Event.Confirmation} {
			published, ok := r.eventIndex[point.ObservationID]
			if !ok || published.Input.Ordinal > r.ordinal || published.Input.At != point.PublishedAt || published.Input.Technical.Bar3End != point.BarEnd ||
				published.Input.Window != direction.Event.Window || published.Input.EpochStart != direction.Event.EpochStart || published.Input.AfterEOF ||
				published.Input.Ordinal < previousOrdinal || (point.ObservationID != previousID && published.Input.Ordinal == previousOrdinal) {
				return nil, fmt.Errorf("E1全pointの公開索引とordinalが不整合")
			}
			previousOrdinal, previousID = published.Input.Ordinal, point.ObservationID
		}
		record, ok := r.eventIndex[direction.Event.Pullback.ObservationID]
		if !ok {
			return nil, fmt.Errorf("既知E1の押戻し観測が公開索引にない")
		}
		anchor, err := BuildPullbackAnchor(grid.At, ref, *direction.Event, record)
		if err != nil {
			return nil, err
		}
		anchors[ref.ID] = anchor
		r.result.PullbackLevels = append(r.result.PullbackLevels, PullbackLevel{At: grid.At, ReferenceID: ref.ID, RawRank: evaluation.RawRank, SuppliedRank: rank + 1, Anchor: anchor})
	}
	return anchors, nil
}
