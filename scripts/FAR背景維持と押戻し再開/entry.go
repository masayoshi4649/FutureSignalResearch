package far88

import (
	"fmt"
	"math"
	"sort"

	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// QualificationCheck は未知と既知不成立を分けた複合資格の一項目です。
type QualificationCheck struct {
	ID     string `json:"id"`
	Known  bool   `json:"known"`
	Passed bool   `json:"passed"`
	Reason string `json:"reason"`
}

// EntryDirectionEvaluation は共通現在資格と順序eventの資格を分けます。
type EntryDirectionEvaluation struct {
	Side                 int                  `json:"side"`
	CurrentKnown         bool                 `json:"current_known"`
	CurrentAllowed       bool                 `json:"current_allowed"`
	E0Allowed            bool                 `json:"e0_allowed"`
	E1Allowed            bool                 `json:"e1_allowed"`
	RequiredUnknown      bool                 `json:"required_unknown"`
	EventRequiredUnknown bool                 `json:"event_required_unknown"`
	Reason               string               `json:"reason"`
	PlacementATR         *float64             `json:"placement_atr"`
	Checks               []QualificationCheck `json:"checks"`
	Event                *ResumeEvent         `json:"event"`
	EventValid           bool                 `json:"event_valid"`
}

// EntryEvaluation は同一の15分要求時計に対する二方向の純評価です。
type EntryEvaluation struct {
	At         float64                    `json:"at"`
	QuoteTime  float64                    `json:"quote_time"`
	QuoteIndex int64                      `json:"quote_index"`
	SourceLine int64                      `json:"source_line"`
	Directions []EntryDirectionEvaluation `json:"directions"`
}

// PoolEvaluation は原poolと供給poolの順位及び入口理由を結びます。
// 注文受理/占有/seenの判定は固定87金融だけが行います。
type PoolEvaluation struct {
	ReferenceID         string `json:"reference_id"`
	Side                int    `json:"side"`
	RawRank             int    `json:"raw_rank"`
	SuppliedRank        *int   `json:"supplied_rank"`
	Known               bool   `json:"known"`
	Allowed             bool   `json:"allowed"`
	RequiredUnknown     bool   `json:"required_unknown"`
	Reason              string `json:"reason"`
	EventID             string `json:"event_id"`
	EventBeforeSource   *bool  `json:"event_before_source"`
	EventSourceRelation string `json:"event_source_relation"`
}

// entryFinite は保存又は計算する数値が全て有限かを確認します。
//
// 引数: values(...float64)は時計・価格・指標です。
// 返り値: boolはNaN/無限大がなければ真です。
func entryFinite(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// qualification は既知と判定を分離した固定理由のcheckを作ります。
//
// 引数: id(string)、known/passed(bool)は項目と評価です。
// 返り値: QualificationCheckは未知の場合に成立を示しません。
func qualification(id string, known, passed bool) QualificationCheck {
	reason := "既知不成立"
	if !known {
		reason = "必要値未知"
	} else if passed {
		reason = "既知成立"
	}
	return QualificationCheck{ID: id, Known: known, Passed: known && passed, Reason: reason}
}

// validatePublishedTechnical は公開された既知値の品質を確認します。
//
// 引数: at(float64)、v(TechnicalView)は公開時計と指標です。
// 返り値: errorは未来/非有限又は既知値の単位矛盾、正常ならnilです。
func validatePublishedTechnical(at float64, v far87.TechnicalView) error {
	if !eventFiniteTechnical(v) || v.Bar3End < 0 || v.Bar15End < 0 || v.Bar3End > at || v.Bar15End > at {
		return fmt.Errorf("公開指標の時計又は数値が不正です")
	}
	if v.TrendKnown && (v.EMA8_3 <= 0 || v.EMA21_3 <= 0 || v.EMA8_15 <= 0 || v.EMA21_15 <= 0 || v.Bar3End <= 0 || v.Bar15End <= 0) ||
		(v.ExitKnown || v.ReversalKnown) && (v.Close3 <= 0 || v.EMA8_3 <= 0 || v.Bar3End <= 0) ||
		(v.ReversalKnown || v.SpikeKnown) && (v.RSI3 < 0 || v.RSI3 > 100 || v.PreviousRSI3 < 0 || v.PreviousRSI3 > 100) ||
		v.SpikeKnown && (v.PreviousATR3 < 0 || v.TR3 < 0) || v.ATRKnown && v.ATR3 < 0 {
		return fmt.Errorf("既知の公開指標の価格・RSI・値幅が不正です")
	}
	return nil
}

// validateResumeEvent はi<p<r<=kと出典/窓/公開時計を検査します。
//
// 引数: at(float64)、event(*ResumeEvent)、side(int)は要求と記録eventです。
// 返り値: errorは順序又は未来の不整合、nil eventは正常な未観測です。
func validateResumeEvent(at float64, event *ResumeEvent, side int) error {
	if event == nil {
		return nil
	}
	if event.ID == "" || event.Side != side || !eventActive(event.Window) || !entryFinite(event.EpochStart) || event.EpochStart < 0 {
		return fmt.Errorf("再開eventの方向又は窓が不正です")
	}
	points := []EventPoint{event.Impulse, event.Pullback, event.Recovery, event.Confirmation}
	for _, p := range points {
		if p.ObservationID <= 0 || !entryFinite(p.BarEnd, p.PublishedAt) || p.BarEnd <= event.EpochStart || p.BarEnd > p.PublishedAt || p.PublishedAt > at {
			return fmt.Errorf("再開eventの公開点に未来又は欠落があります")
		}
	}
	i, p, r, k := points[0], points[1], points[2], points[3]
	if !(i.BarEnd < p.BarEnd && p.BarEnd < r.BarEnd && r.BarEnd <= k.BarEnd) ||
		!(i.ObservationID < p.ObservationID && p.ObservationID < r.ObservationID && r.ObservationID <= k.ObservationID) ||
		!(i.PublishedAt <= p.PublishedAt && p.PublishedAt <= r.PublishedAt && r.PublishedAt <= k.PublishedAt) ||
		(r.BarEnd == k.BarEnd) != (r.ObservationID == k.ObservationID) {
		return fmt.Errorf("再開eventのi<p<r<=kが不成立です")
	}
	return nil
}

// EvaluateEntry は旧actualの現在資格と独立eventの順序資格を純計算します。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、events(EventSnapshot)は当時の値です。
// 返り値: EntryEvaluationは買売の同式、errorは保存入力の矛盾です。
func EvaluateEntry(at float64, q far87.Quote, chart far87.ChartView, events EventSnapshot) (EntryEvaluation, error) {
	result := EntryEvaluation{At: at, QuoteTime: q.Time, QuoteIndex: q.Index, SourceLine: q.Line, Directions: []EntryDirectionEvaluation{}}
	if !entryFinite(at, q.Time, q.Last, q.Bid, q.Ask, chart.PreviousClose3, chart.PreviousEMA8_3, chart.PreviousBar3End) || at <= 0 || q.Time > at || q.Time < 0 || chart.PreviousBar3End < 0 || chart.PreviousBar3End > at ||
		events.At != at || !entryFinite(events.EpochStart) || events.EpochStart > at || events.EpochStart < 0 || len(events.Directions) != 2 {
		return result, fmt.Errorf("入口の公開時計・気配・event集合が不正です")
	}
	v := chart.Technical
	if err := validatePublishedTechnical(at, v); err != nil {
		return result, err
	}
	if chart.Previous3Known && (chart.PreviousBar3End <= 0 || chart.PreviousClose3 <= 0 || chart.PreviousEMA8_3 <= 0 || v.Bar3End-chart.PreviousBar3End != 180) {
		return result, fmt.Errorf("既知の旧ChartPairが直前180秒足へ結合しません")
	}
	states := map[int]EventDirectionState{}
	for _, state := range events.Directions {
		if (state.Side != 1 && state.Side != -1) || states[state.Side].Side != 0 {
			return result, fmt.Errorf("event方向の欠落又は重複があります")
		}
		if err := validateResumeEvent(at, state.Event, state.Side); err != nil {
			return result, err
		}
		valid := state.Event != nil && !state.RequiredUnknown && eventActive(events.Window) && state.Event.Window == events.Window && state.Event.EpochStart == events.EpochStart &&
			at-state.Event.Confirmation.BarEnd < 900
		if state.EventValid != valid {
			return result, fmt.Errorf("event有効旗と期限・窓が不整合です")
		}
		states[state.Side] = state
	}
	// ----------------------------------------
	// 方向だけを符号反転し、気配の取得側と全checkを同じ式で計算します。
	for _, side := range []int{1, -1} {
		s, state := float64(side), states[side]
		known := v.TrendKnown && v.ReversalKnown && v.SpikeKnown && v.ATRKnown
		clock := v.Bar3End > 0 && v.Bar15End > 0 && at-v.Bar3End <= 180 && at-v.Bar15End <= 900
		pair := chart.Previous3Known
		quoteKnown := q.Valid && q.Last > 0 && q.Bid > 0 && q.Ask > q.Bid && q.Time > 0 && at-q.Time <= 15 && q.Index >= 0 && q.Line > 0
		current := EntryDirectionEvaluation{Side: side, CurrentKnown: true, CurrentAllowed: true, EventRequiredUnknown: state.RequiredUnknown,
			Event: cloneEventState(state).Event, EventValid: state.EventValid, Checks: []QualificationCheck{}}
		entry := q.Ask
		if side == -1 {
			entry = q.Bid
		}
		placementKnown := v.ATRKnown && quoteKnown && v.EMA8_3 > 0
		placementPassed := false
		if placementKnown && v.ATR3 > 0 {
			x := s * (entry - v.EMA8_3) / v.ATR3
			if !entryFinite(x) {
				return result, fmt.Errorf("取得ATR比が非有限です")
			}
			current.PlacementATR = &x
			placementPassed = x >= 0 && x <= 1
		}
		current.Checks = []QualificationCheck{
			qualification("必要指標既知", known, known),
			qualification("確定足時計", clock, clock),
			qualification("旧直前3分結合", pair, pair),
			qualification("当時新規気配", quoteKnown, quoteKnown),
			qualification("15分背景", v.TrendKnown, s*(v.EMA8_15-v.EMA21_15) > 0),
			qualification("3分価格側", v.ReversalKnown, s*(v.Close3-v.EMA8_3) > 0),
			qualification("MACD増分", v.ReversalKnown, s*(v.Histogram3-v.PreviousHistogram3) > 0),
			qualification("RSI増分", v.ReversalKnown, s*(v.RSI3-v.PreviousRSI3) > 0),
			qualification("同時スパイクなし", v.SpikeKnown, !(v.TR3 > 2*v.PreviousATR3 && math.Abs(v.RSI3-v.PreviousRSI3) > 15)),
			qualification("取得0から1ATR", placementKnown, placementPassed),
		}
		for _, check := range current.Checks {
			current.CurrentKnown = current.CurrentKnown && check.Known
			current.CurrentAllowed = current.CurrentAllowed && check.Passed
		}
		current.RequiredUnknown = !current.CurrentKnown
		current.E0Allowed = current.CurrentAllowed
		current.E1Allowed = current.CurrentAllowed && state.EventValid
		current.Reason = "現在資格が既知不成立"
		if current.RequiredUnknown {
			current.Reason = "現在資格の必要値が未知"
		} else if current.CurrentAllowed {
			current.Reason = "現在の複合資格が成立"
		}
		result.Directions = append(result.Directions, current)
	}
	return result, nil
}

// cloneEntryReadLot は供給poolのpointerを元Sourceから分離します。
//
// 引数: row(ReadLot)は固定87の出典です。
// 返り値: ReadLotは親量や小量資格を推測せず値複写します。
func cloneEntryReadLot(row far87.ReadLot) far87.ReadLot {
	if row.NativeParentInitialMicro != nil {
		v := *row.NativeParentInitialMicro
		row.NativeParentInitialMicro = &v
	}
	if row.NativeParentOriginalDesired != nil {
		v := *row.NativeParentOriginalDesired
		row.NativeParentOriginalDesired = &v
	}
	if row.NativeSmallInitialEligible != nil {
		v := *row.NativeSmallInitialEligible
		row.NativeSmallInitialEligible = &v
	}
	return row
}

// FilterEntry は全原poolを記録し、外policyの資格だけで部分列を供給します。
//
// 引数: policy(string)はS/E0/E1、raw(ReadSnapshot)、evaluation(EntryEvaluation)は当時値です。
// 返り値: ReadSnapshotは独立供給pool、[]PoolEvaluationは全原順位、errorは入力不整合です。
func FilterEntry(policy string, raw far87.ReadSnapshot, evaluation EntryEvaluation) (far87.ReadSnapshot, []PoolEvaluation, error) {
	out := raw
	out.Lots, out.Closes = []far87.ReadLot{}, append([]far87.ReferenceClose{}, raw.Closes...)
	checks := []PoolEvaluation{}
	if policy != "S" && policy != "E0" && policy != "E1" || !entryFinite(evaluation.At, raw.At) || evaluation.At <= 0 || raw.At > evaluation.At || len(raw.Closes) != 0 ||
		raw.Started && raw.SourceIndex < 0 || !raw.Started && len(raw.Lots) > 0 {
		return out, checks, fmt.Errorf("入口policy又はSource時刻/通知が不正です")
	}
	directions := map[int]EntryDirectionEvaluation{}
	for _, direction := range evaluation.Directions {
		if direction.Side != 1 && direction.Side != -1 || directions[direction.Side].Side != 0 {
			return out, checks, fmt.Errorf("入口評価の方向が欠落又は重複しています")
		}
		if direction.RequiredUnknown == direction.CurrentKnown || direction.E0Allowed != direction.CurrentAllowed || direction.CurrentAllowed && !direction.CurrentKnown ||
			direction.E1Allowed != (direction.CurrentAllowed && direction.EventValid) || direction.EventValid && (direction.Event == nil || direction.EventRequiredUnknown) ||
			direction.PlacementATR != nil && !entryFinite(*direction.PlacementATR) {
			return out, checks, fmt.Errorf("入口評価の既知性・政策包含が不整合です")
		}
		directions[direction.Side] = direction
	}
	if len(directions) != 2 {
		return out, checks, fmt.Errorf("入口評価は二方向が必要です")
	}
	pool := append([]far87.ReadLot{}, raw.Lots...)
	sort.SliceStable(pool, func(i, j int) bool {
		if pool[i].Reference.At != pool[j].Reference.At {
			return pool[i].Reference.At < pool[j].Reference.At
		}
		return pool[i].Reference.ID < pool[j].Reference.ID
	})
	ids := map[string]bool{}
	for i, row := range pool {
		r := row.Reference
		if r.ID == "" || ids[r.ID] || (r.Side != 1 && r.Side != -1) || !entryFinite(r.At, r.Entry) || r.At > raw.At || r.Entry <= 0 || r.Quantity < 1 || r.Quantity > 100 || row.ReferenceInitialQuantity < r.Quantity || r.Method != raw.Method {
			return out, checks, fmt.Errorf("原poolのID/方向/量/出典が不正です")
		}
		ids[r.ID] = true
		d := directions[r.Side]
		check := PoolEvaluation{ReferenceID: r.ID, Side: r.Side, RawRank: i + 1, Known: d.CurrentKnown, Allowed: d.E0Allowed,
			RequiredUnknown: d.RequiredUnknown, Reason: d.Reason, EventSourceRelation: "再開eventなし"}
		if policy == "S" {
			check.Known, check.Allowed, check.RequiredUnknown, check.Reason = true, true, false, "元参照を無filterで供給"
		} else if policy == "E1" {
			check.Known = d.CurrentKnown && !d.EventRequiredUnknown
			check.RequiredUnknown = !check.Known
			check.Allowed = d.E1Allowed
			if !check.Known {
				check.Reason = "現在資格又は順序履歴の必要値が未知"
			} else if !d.CurrentAllowed {
				check.Reason = "現在資格が既知不成立"
			} else if !d.EventValid {
				check.Reason = "有効な順行再開eventがない"
			} else {
				check.Reason = "現在資格と順行再開eventが成立"
			}
		}
		if d.Event != nil {
			check.EventID = d.Event.ID
			before := d.Event.Confirmation.BarEnd < r.At
			check.EventBeforeSource = &before
			check.EventSourceRelation = "同時"
			if before {
				check.EventSourceRelation = "eventがSource生成前"
			} else if d.Event.Confirmation.BarEnd > r.At {
				check.EventSourceRelation = "eventがSource生成後"
			}
		}
		if check.Allowed {
			out.Lots = append(out.Lots, cloneEntryReadLot(row))
			rank := len(out.Lots)
			check.SuppliedRank = &rank
		}
		checks = append(checks, check)
	}
	return out, checks, nil
}
