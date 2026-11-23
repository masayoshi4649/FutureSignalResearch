package far92

import (
	"encoding/json"
	"fmt"
	"math"
)

// PriceLevel は既存公開点と正の元Closeを結びます。
type PriceLevel struct {
	Point EventPoint `json:"point"`
	Close float64    `json:"close"`
}

// PriceDirection は独立価格構造の方向別保存値です。
type PriceDirection struct {
	Side            int         `json:"side"`
	Known           bool        `json:"known"`
	RequiredUnknown bool        `json:"required_unknown"`
	Stage           string      `json:"stage"`
	Reason          string      `json:"reason"`
	Impulse         *EventPoint `json:"impulse"`
	Pullback        *EventPoint `json:"pullback"`
	ImpulseOrigin   string      `json:"impulse_origin"`
	High            *PriceLevel `json:"high"`
	Low             *PriceLevel `json:"low"`
	Reclaim         *EventPoint `json:"reclaim"`
	Peak            *PriceLevel `json:"peak"`
	Hold            *EventPoint `json:"hold"`
	Resume          *EventPoint `json:"resume"`
	TriggerValid    bool        `json:"trigger_valid"`
	ExpiresAt       *float64    `json:"expires_at"`
}

// PriceSnapshot は定時の独立状態を旧eventと分けて保存します。
type PriceSnapshot struct {
	At         float64          `json:"at"`
	Window     string           `json:"window"`
	EpochStart float64          `json:"epoch_start"`
	Directions []PriceDirection `json:"directions"`
}

// PriceCounts は定時前に消えた構造も含む小型分母です。
type PriceCounts struct {
	Records           int            `json:"records"`
	Bars              int            `json:"bars"`
	FreshImpulses     int            `json:"fresh_impulses"`
	InheritedImpulses int            `json:"inherited_impulses"`
	Episodes          int            `json:"episodes"`
	Reclaims          int            `json:"reclaims"`
	PeakUpdates       int            `json:"peak_updates"`
	Holds             int            `json:"holds"`
	HoldUpdates       int            `json:"hold_updates"`
	Resumes           int            `json:"resumes"`
	AttemptResets     int            `json:"attempt_resets"`
	ExpiredTriggers   int            `json:"expired_triggers"`
	Resets            map[string]int `json:"resets"`
}

type priceState struct {
	value     PriceDirection
	history   []PriceLevel
	holdClose float64
	expired   bool
}

// PriceTracker は旧Recordの公開入力だけから独立i/pと価格vを発見します。
type PriceTracker struct {
	states    [2]priceState
	last      EventInput
	haveInput bool
	lastID    int64
	lastBar   TechnicalView
	haveBar   bool
	counts    PriceCounts
}

// NewPriceTracker は未知の独立器を生成します。
//
// 引数: ありません。
// 返り値: *PriceTrackerは外部金融と状態を共有しない実体です。
func NewPriceTracker() *PriceTracker {
	t := &PriceTracker{counts: PriceCounts{Resets: map[string]int{}}}
	t.clear("公開入力なし", true)
	return t
}

// clear は全方向と全履歴を失効させます。
//
// 引数: reason(string)は失効理由、unknown(bool)は必要未知です。
// 返り値: ありません。
func (t *PriceTracker) clear(reason string, unknown bool) {
	for i, side := range []int{1, -1} {
		t.states[i] = priceState{value: PriceDirection{Side: side, Known: !unknown, RequiredUnknown: unknown, Stage: "背景待ち", Reason: reason}}
	}
}

// priceFinite は公開値の有限性を検査します。
//
// 引数: values(...float64)は検査値です。
// 返り値: boolはすべて有限なら真です。
func priceFinite(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// priceKnown は固定88と同じ順序用の既知条件です。
//
// 引数: v(TechnicalView)は公開指標です。
// 返り値: boolは必要値と値域が既知なら真です。
func priceKnown(v TechnicalView) bool {
	return v.TrendKnown && v.ReversalKnown && v.SpikeKnown && v.Close3 > 0 && v.EMA8_3 > 0 && v.EMA21_3 > 0 && v.EMA8_15 > 0 && v.EMA21_15 > 0 && v.PreviousATR3 >= 0 && v.TR3 >= 0 && v.RSI3 >= 0 && v.RSI3 <= 100 && v.PreviousRSI3 >= 0 && v.PreviousRSI3 <= 100
}

// priceActive は元Sourceの有効窓だけを認めます。
//
// 引数: window(string)は窓名です。
// 返り値: boolは旧三窓なら真です。
func priceActive(window string) bool {
	return window == "D164_15" || window == "P164_06" || window == "U165_03"
}

// Feed は疎な旧Recordを一度ずつ読み、旧k期限を状態へ使いません。
//
// 引数: record(EventRecord)は旧Observeが返した公開入力です。
// 返り値: errorは公開時計、非有限値、重複/欠落Recordの矛盾です。
func (t *PriceTracker) Feed(record EventRecord) error {
	in, v := record.Input, record.Input.Technical
	if record.ID != t.lastID+1 || in.Ordinal <= 0 || t.haveInput && (in.Ordinal <= t.last.Ordinal || in.At < t.last.At) || !priceFinite(in.At, in.EpochStart, in.Quote.Time, in.Quote.Last, in.Quote.Bid, in.Quote.Ask, v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15, v.RSI3, v.PreviousRSI3, v.Histogram3, v.PreviousHistogram3, v.Close3, v.TR3, v.ATR3, v.PreviousATR3, v.Bar3End, v.Bar15End) || in.At <= 0 || in.EpochStart < 0 || in.EpochStart > in.At || in.Quote.Time > in.At || v.Bar3End > in.At || v.Bar15End > in.At || v.Bar3End < 0 || v.Bar15End < 0 || (in.Origin != "quote" && in.Origin != "three_timer" && in.Origin != "core_timer") {
		return fmt.Errorf("独立価格の公開入力/Record順が不正です")
	}
	epoch := !t.haveInput || in.Window != t.last.Window || in.EpochStart != t.last.EpochStart
	bar := !t.haveInput || v.Bar3End != t.last.Technical.Bar3End
	unknown := !priceKnown(v) || v.Bar3End <= 0 || v.Bar15End <= 0 || in.At-v.Bar3End > 180 || in.At-v.Bar15End > 900
	bad := in.Origin == "quote" && in.Quote.Last <= 0
	t.counts.Records++
	if bar && v.Bar3End > 0 {
		t.counts.Bars++
	}
	reason, u, reset := "", false, false
	switch {
	case in.AfterEOF:
		reason = "原板終端後のため失効"
		reset = true
	case !priceActive(in.Window):
		reason = "静観又は場末のため失効"
		reset = true
	case epoch:
		reason = "Source時間窓を開始"
		u = unknown
		reset = true
	case bad:
		reason = "Last不良で必要値を失効"
		u = true
		reset = true
	case unknown:
		reason = "確定足の必要値又は鮮度が未知"
		u = true
		reset = true
	}
	if reset {
		t.clear(reason, u)
		t.counts.Resets[reason]++
	}

	canStep := bar && !in.AfterEOF && priceActive(in.Window) && !unknown && !bad
	gap := false
	if canStep {
		continuous := epoch || !t.haveBar || v.Bar3End-t.lastBar.Bar3End == 180 && t.lastBar.Histogram3 == v.PreviousHistogram3 && t.lastBar.RSI3 == v.PreviousRSI3
		if !continuous {
			t.clear("確定3分の欠足又は前値結合が不成立", true)
			t.counts.Resets["確定3分の欠足又は前値結合が不成立"]++
			gap = true
		}
	}
	if !reset && !gap {
		for i := range t.states {
			s := &t.states[i]
			background := float64(s.value.Side)*(v.EMA8_15-v.EMA21_15) > 0
			if background && s.value.Resume != nil && !s.expired && in.At-s.value.Resume.BarEnd >= 900 {
				s.expired = true
				t.counts.ExpiredTriggers++
			}
		}
	}
	if canStep && v.Bar3End > in.EpochStart {
		for i := range t.states {
			t.step(&t.states[i], record)
		}
	}

	if reset && !(epoch && !unknown && !bad && priceActive(in.Window) && !in.AfterEOF && v.Bar3End > in.EpochStart) {
		t.haveBar = false
	} else if bar && v.Bar3End > 0 {
		t.lastBar = v
		t.haveBar = true
	}
	t.last, t.haveInput, t.lastID = in, true, record.ID
	return nil
}

// step は単一の新しい確定足をRootの優先順で適用します。
//
// 引数: s(*priceState)は方向状態、record(EventRecord)は当足です。
// 返り値: ありません。履歴は当時公開Closeのみです。
func (t *PriceTracker) step(s *priceState, record EventRecord) {
	v := record.Input.Technical
	side := float64(s.value.Side)
	point := EventPoint{ObservationID: record.ID, BarEnd: v.Bar3End, PublishedAt: record.Input.At}
	level := PriceLevel{Point: point, Close: v.Close3}
	price := side*(v.Close3-v.EMA8_3) > 0
	if side*(v.EMA8_15-v.EMA21_15) <= 0 {
		*s = priceState{value: PriceDirection{Side: s.value.Side, Known: true, Stage: "背景待ち", Reason: "15分背景が同方向を支持しない"}}
		return
	}
	s.value.Known, s.value.RequiredUnknown = true, false
	if s.value.Impulse == nil {
		if price && side*(v.Histogram3-v.PreviousHistogram3) > 0 && side*(v.RSI3-v.PreviousRSI3) > 0 {
			s.value.Impulse = &point
			s.value.ImpulseOrigin = "fresh"
			s.value.Stage = "推進"
			s.value.Reason = "背景内の価格と勢いの推進を観測"
			s.history = []PriceLevel{level}
			t.counts.FreshImpulses++
		} else {
			s.value.Reason = "背景支持下の推進を待つ"
		}
		return
	}
	if s.value.Resume != nil && !price {
		next := *s.value.Resume
		history := []PriceLevel{}
		for _, row := range s.history {
			if row.Point.BarEnd >= next.BarEnd {
				history = append(history, row)
			}
		}
		*s = priceState{value: PriceDirection{Side: s.value.Side, Known: true, Impulse: &next, ImpulseOrigin: "completed_v", Stage: "推進", Reason: "自身vを次iへ継承して新押しを開始"}, history: history}
		t.counts.InheritedImpulses++
	}
	if !price {
		var high *PriceLevel
		for _, row := range s.history {
			if high == nil || side*row.Close > side*high.Close {
				copy := row
				high = &copy
			}
		}
		s.value.Pullback = &point
		s.value.High = high
		s.value.Low = &level
		s.value.Reclaim = nil
		s.value.Peak = nil
		s.value.Hold = nil
		s.value.Resume = nil
		s.expired = false
		s.value.Stage = "押し"
		s.value.Reason = "平均側でない最新押しを更新"
		t.counts.Episodes++
		s.history = append(s.history, level)
		return
	}
	defer func() { s.history = append(s.history, level) }()
	if s.value.Pullback == nil {
		return
	}
	if s.value.High == nil || side*s.value.High.Close <= side*s.value.Low.Close {
		s.value.Reason = "押し前終値基準が押し終値以下"
		return
	}
	x, h := side*v.Close3, side*s.value.High.Close
	if x <= h {
		if s.value.Reclaim != nil || s.value.Resume != nil {
			t.counts.AttemptResets++
		}
		s.value.Reclaim = nil
		s.value.Peak = nil
		s.value.Hold = nil
		s.value.Resume = nil
		s.expired = false
		s.value.Stage = "押し"
		s.value.Reason = "押し前終値基準以下で価格attemptを破棄"
		return
	}
	if s.value.Resume != nil {
		return
	}
	if s.value.Reclaim == nil {
		s.value.Reclaim = &point
		s.value.Peak = &level
		s.value.Stage = "奪還後"
		s.value.Reason = "押し前終値基準を初めて奪還"
		t.counts.Reclaims++
		return
	}
	p := side * s.value.Peak.Close
	if s.value.Hold == nil {
		if x > p {
			s.value.Peak = &level
			s.value.Reason = "保持前の方向側最高終値を更新"
			t.counts.PeakUpdates++
		} else if x < p {
			s.value.Hold = &point
			s.holdClose = v.Close3
			s.value.Stage = "保持後"
			s.value.Reason = "突破後の調整を観測"
			t.counts.Holds++
		}
		return
	}
	if x > p {
		s.value.Resume = &point
		s.expired = false
		s.value.Stage = "完成"
		s.value.Reason = "固定最高終値を越え価格再開を確認"
		t.counts.Resumes++
		return
	}
	if x < side*s.holdClose {
		s.value.Hold = &point
		s.holdClose = v.Close3
		s.value.Reason = "保持中の方向側最低終値を更新"
		t.counts.HoldUpdates++
	}
}

// Snapshot は当時状態を深い値複写で返します。
//
// 引数: at(float64)は最後の公開以後の観測時刻です。
// 返り値: PriceSnapshot/errorは期限を再評価した純view又は時計不正です。
func (t *PriceTracker) Snapshot(at float64) (PriceSnapshot, error) {
	if !priceFinite(at) || at <= 0 || t.haveInput && at < t.last.At {
		return PriceSnapshot{}, fmt.Errorf("独立価格snapshot時計が不正です")
	}
	out := PriceSnapshot{At: at, Window: t.last.Window, EpochStart: t.last.EpochStart, Directions: []PriceDirection{}}
	for _, state := range t.states {
		d := state.value
		if d.Resume != nil {
			end := d.Resume.BarEnd + 900
			d.ExpiresAt = &end
			d.TriggerValid = d.Known && priceActive(out.Window) && at >= d.Resume.PublishedAt && at >= d.Resume.BarEnd && at < end
		}
		out.Directions = append(out.Directions, d)
	}
	data, err := json.Marshal(out)
	if err != nil {
		return out, err
	}
	var copied PriceSnapshot
	err = json.Unmarshal(data, &copied)
	return copied, err
}

// Counts はcounterのmapを共有せず返します。
//
// 引数: ありません。
// 返り値: PriceCountsは保存用の独立値です。
func (t *PriceTracker) Counts() PriceCounts {
	out := t.counts
	out.Resets = map[string]int{}
	for k, v := range t.counts.Resets {
		out.Resets[k] = v
	}
	return out
}
