package far88

import (
	"fmt"
	"math"

	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// EventInput は独立eventBankの公開値と処理順を保存する入力です。
// Quoteは公開直前又は当原行で、物理Lineと実Indexを保持します。
type EventInput struct {
	Ordinal    int64               `json:"ordinal"`
	At         float64             `json:"at"`
	Origin     string              `json:"origin"`
	Window     string              `json:"window"`
	EpochStart float64             `json:"epoch_start"`
	AfterEOF   bool                `json:"after_eof"`
	Quote      far87.Quote         `json:"quote"`
	Technical  far87.TechnicalView `json:"technical"`
}

// EventRecord は確定足又は失効の入力だけを一度保存します。
type EventRecord struct {
	ID    int64      `json:"id"`
	Kind  string     `json:"kind"`
	Input EventInput `json:"input"`
}

// EventPoint は値の全文を複写せず観測IDと公開時計を参照します。
type EventPoint struct {
	ObservationID int64   `json:"observation_id"`
	BarEnd        float64 `json:"bar_end"`
	PublishedAt   float64 `json:"published_at"`
}

// ResumeEvent は異なる推進/押し/回復と、その後の最初の勢い確認です。
type ResumeEvent struct {
	ID           string     `json:"id"`
	Side         int        `json:"side"`
	Window       string     `json:"window"`
	EpochStart   float64    `json:"epoch_start"`
	Impulse      EventPoint `json:"impulse"`
	Pullback     EventPoint `json:"pullback"`
	Recovery     EventPoint `json:"recovery"`
	Confirmation EventPoint `json:"confirmation"`
}

// EventDirectionState は方向別の順序と未知理由を値で保存します。
type EventDirectionState struct {
	Side            int          `json:"side"`
	Stage           string       `json:"stage"`
	Reason          string       `json:"reason"`
	RequiredUnknown bool         `json:"required_unknown"`
	Impulse         *EventPoint  `json:"impulse"`
	Pullback        *EventPoint  `json:"pullback"`
	Recovery        *EventPoint  `json:"recovery"`
	Confirmation    *EventPoint  `json:"confirmation"`
	Event           *ResumeEvent `json:"event"`
	EventValid      bool         `json:"event_valid"`
}

// EventSnapshot は定時の方向別状態です。市場や金融の所有は含みません。
type EventSnapshot struct {
	At         float64               `json:"at"`
	Window     string                `json:"window"`
	EpochStart float64               `json:"epoch_start"`
	Directions []EventDirectionState `json:"directions"`
}

// EventTracker は公開された隣接3分足だけで時間順を追います。
type EventTracker struct {
	lastInput   EventInput
	haveInput   bool
	records     int64
	states      [2]EventDirectionState
	lastBar     far87.TechnicalView
	haveBar     bool
	lastUnknown bool
	eof         bool
}

// NewEventTracker は場間状態を持ち越さない空の追跡器を作ります。
//
// 引数: ありません。
// 返り値: *EventTrackerは外部市場や金融へ接続しない状態器です。
func NewEventTracker() *EventTracker {
	t := &EventTracker{}
	t.clear("当場の確定足を未観測", true)
	return t
}

// clear は全方向の履歴を失効させ、既知不成立と未知を区別します。
//
// 引数: reason(string)は理由、unknown(bool)は必要値未知です。
// 返り値: ありません。数値器とSourceの状態は変更しません。
func (t *EventTracker) clear(reason string, unknown bool) {
	for i, side := range []int{1, -1} {
		t.states[i] = EventDirectionState{Side: side, Stage: "背景待ち", Reason: reason, RequiredUnknown: unknown}
	}
}

// eventActive は研究対象のSource時間窓を識別します。
//
// 引数: window(string)はRuntimeの窓IDです。
// 返り値: boolは固定三手法の時間窓なら真です。
func eventActive(window string) bool {
	return window == "D164_15" || window == "P164_06" || window == "U165_03"
}

// eventTechnicalKnown は順序判定に必要な公開既知旗と値を検査します。
//
// 引数: v(TechnicalView)は固定数値器の現在公開値です。
// 返り値: boolは推進/価格/勢い/急変を既知として評価できる場合に真です。
func eventTechnicalKnown(v far87.TechnicalView) bool {
	return v.TrendKnown && v.ReversalKnown && v.SpikeKnown &&
		v.Close3 > 0 && v.EMA8_3 > 0 && v.EMA21_3 > 0 && v.EMA8_15 > 0 && v.EMA21_15 > 0 &&
		v.PreviousATR3 >= 0 && v.TR3 >= 0 && v.RSI3 >= 0 && v.RSI3 <= 100 && v.PreviousRSI3 >= 0 && v.PreviousRSI3 <= 100
}

// eventFiniteTechnical は保存される全公開数値の有限性を確認します。
//
// 引数: v(TechnicalView)は既知/未知を含む公開値です。
// 返り値: boolはJSONへ有限数値だけを保存できる場合に真です。
func eventFiniteTechnical(v far87.TechnicalView) bool {
	return entryFinite(v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15, v.RSI3, v.PreviousRSI3,
		v.Histogram3, v.PreviousHistogram3, v.Close3, v.TR3, v.ATR3, v.PreviousATR3, v.Bar3End, v.Bar15End)
}

// eventPoint は観測IDと足終端から独立した点を作ります。
//
// 引数: id(int64)、in(EventInput)は保存した観測です。
// 返り値: *EventPointは当時の公開時計を保持します。
func eventPoint(id int64, in EventInput) *EventPoint {
	return &EventPoint{ObservationID: id, BarEnd: in.Technical.Bar3End, PublishedAt: in.At}
}

// cloneEventState は返却値のpointerを内部状態から分離します。
//
// 引数: s(EventDirectionState)は内部状態です。
// 返り値: EventDirectionStateは呼出側が変更しても内部へ影響しません。
func cloneEventState(s EventDirectionState) EventDirectionState {
	for _, p := range []**EventPoint{&s.Impulse, &s.Pullback, &s.Recovery, &s.Confirmation} {
		if *p != nil {
			v := **p
			*p = &v
		}
	}
	if s.Event != nil {
		v := *s.Event
		s.Event = &v
	}
	return s
}

// step は正常な隣接確定足を方向別の4段階へ適用します。
//
// 引数: s(*EventDirectionState)、in(EventInput)、id(int64)は方向と公開観測です。
// 返り値: ありません。勢い確認後の同方向足でeventを若返らせません。
func (t *EventTracker) step(s *EventDirectionState, in EventInput, id int64) {
	v, side := in.Technical, float64(s.Side)
	point := eventPoint(id, in)
	background := side*(v.EMA8_15-v.EMA21_15) > 0
	price := side*(v.Close3-v.EMA8_3) > 0
	momentum := side*(v.Histogram3-v.PreviousHistogram3) > 0 && side*(v.RSI3-v.PreviousRSI3) > 0
	spike := v.TR3 > 2*v.PreviousATR3 && math.Abs(v.RSI3-v.PreviousRSI3) > 15
	if !background {
		*s = EventDirectionState{Side: s.Side, Stage: "背景待ち", Reason: "15分背景が同方向を支持しない"}
		return
	}
	s.RequiredUnknown = false
	if s.Event != nil && !price {
		impulse := s.Event.Confirmation
		*s = EventDirectionState{Side: s.Side, Stage: "押し", Reason: "再開後の再押しで旧event失効", Impulse: &impulse, Pullback: point}
		return
	}
	switch s.Stage {
	case "背景待ち":
		if price && momentum {
			s.Stage, s.Reason, s.Impulse = "推進", "背景内の価格と勢いの推進を観測", point
		} else {
			s.Reason = "背景支持下の推進を待つ"
		}
	case "推進":
		if !price {
			s.Stage, s.Reason, s.Pullback = "押し", "平均逆側への押しを観測", point
		}
	case "押し":
		if !price {
			s.Pullback, s.Reason = point, "押しの最新確定足を更新"
			return
		}
		s.Recovery, s.Stage, s.Reason = point, "価格回復", "価格回復後の勢い確認を待つ"
		fallthrough
	case "価格回復":
		if !price {
			s.Stage, s.Reason, s.Pullback, s.Recovery = "押し", "再押しで価格回復を破棄", point, nil
			return
		}
		if momentum && !spike {
			s.Confirmation, s.Stage, s.Reason = point, "再開", "価格回復後の勢いと非急変を確認"
			s.Event = &ResumeEvent{ID: fmt.Sprintf("E%06d_S%d", id, s.Side), Side: s.Side, Window: in.Window, EpochStart: in.EpochStart,
				Impulse: *s.Impulse, Pullback: *s.Pullback, Recovery: *s.Recovery, Confirmation: *point}
			s.EventValid = true
		}
	case "再開":
		s.Reason = "同じ再開eventを維持"
	}
}

// Observe は全公開操作を受け、閉じ足又は失効に必要な入力だけを返します。
//
// 引数: in(EventInput)は全呼出で増えるordinalと当時公開値です。
// 返り値: *EventRecordは保存対象、nilは重複、errorは未来/非有限/順序矛盾です。
func (t *EventTracker) Observe(in EventInput) (*EventRecord, error) {
	if !entryFinite(in.At, in.EpochStart, in.Quote.Time, in.Quote.Last, in.Quote.Bid, in.Quote.Ask) || !eventFiniteTechnical(in.Technical) ||
		in.At <= 0 || in.EpochStart < 0 || in.EpochStart > in.At || in.Quote.Time > in.At || in.Ordinal <= 0 ||
		(in.Origin != "three_timer" && in.Origin != "core_timer" && in.Origin != "quote") {
		return nil, fmt.Errorf("event入力の時計・公開元・数値が不正です")
	}
	if t.haveInput && (in.Ordinal <= t.lastInput.Ordinal || in.At < t.lastInput.At) {
		return nil, fmt.Errorf("event入力のordinal又は時計が後退しています")
	}
	v := in.Technical
	if err := validatePublishedTechnical(in.At, v); err != nil {
		return nil, err
	}
	epochChanged := !t.haveInput || in.Window != t.lastInput.Window || in.EpochStart != t.lastInput.EpochStart
	barChanged := !t.haveInput || v.Bar3End != t.lastInput.Technical.Bar3End
	unknown := !eventTechnicalKnown(v) || v.Bar3End <= 0 || v.Bar15End <= 0 || in.At-v.Bar3End > 180 || in.At-v.Bar15End > 900
	badLast := in.Origin == "quote" && in.Quote.Last <= 0
	expired := false
	for i := range t.states {
		if event := t.states[i].Event; event != nil && in.At-event.Confirmation.BarEnd >= 900 {
			side := t.states[i].Side
			t.states[i] = EventDirectionState{Side: side, Stage: "背景待ち", Reason: "再開確認から900秒以上で失効"}
			expired = true
		}
	}
	kind, reset := "", false
	switch {
	case in.AfterEOF:
		if !t.eof || barChanged || epochChanged {
			kind = "EOF"
		}
		t.clear("原板終端後のため失効", false)
		reset = true
	case !eventActive(in.Window):
		if epochChanged || barChanged {
			kind = "窓停止"
		}
		t.clear("静観又は場末のため失効", false)
		reset = true
	case epochChanged:
		kind = "窓開始"
		t.clear("Source時間窓を開始", unknown)
		reset = true
	case badLast:
		kind = "Last不良"
		t.clear("Last不良で必要値を失効", true)
		reset = true
	case unknown:
		if !t.lastUnknown || barChanged {
			kind = "必要値未知"
		}
		t.clear("確定足の必要値又は鮮度が未知", true)
		reset = true
	case expired:
		kind = "期限失効"
	}
	if barChanged && kind == "" {
		kind = "確定3分"
	}
	if kind == "" {
		t.lastInput, t.haveInput, t.lastUnknown, t.eof = in, true, unknown, in.AfterEOF
		return nil, nil
	}
	t.records++
	record := &EventRecord{ID: t.records, Kind: kind, Input: in}
	if barChanged && v.Bar3End > 0 && !in.AfterEOF && eventActive(in.Window) && !unknown && !badLast {
		continuous := epochChanged || !t.haveBar || v.Bar3End-t.lastBar.Bar3End == 180 &&
			t.lastBar.Histogram3 == v.PreviousHistogram3 && t.lastBar.RSI3 == v.PreviousRSI3
		if !continuous {
			t.clear("確定3分の欠足又は前値結合が不成立", true)
		}
		if v.Bar3End > in.EpochStart {
			for i := range t.states {
				t.step(&t.states[i], in, record.ID)
			}
		}
	}
	if reset && !(epochChanged && !unknown && !badLast && eventActive(in.Window) && !in.AfterEOF && v.Bar3End > in.EpochStart) {
		t.haveBar = false
	} else if barChanged && v.Bar3End > 0 {
		t.lastBar, t.haveBar = v, true
	}
	t.lastInput, t.haveInput, t.lastUnknown, t.eof = in, true, unknown, in.AfterEOF
	return record, nil
}

// Snapshot は当時状態の独立コピーとevent期限を返します。
//
// 引数: at(float64)は最後にObserveした時計以上の公開判断時刻です。
// 返り値: EventSnapshotは状態を消費せず、errorは非有限又は時計後退です。
func (t *EventTracker) Snapshot(at float64) (EventSnapshot, error) {
	if !entryFinite(at) || at <= 0 || t.haveInput && at < t.lastInput.At {
		return EventSnapshot{}, fmt.Errorf("event snapshot時計が不正です")
	}
	v := EventSnapshot{At: at, Window: t.lastInput.Window, EpochStart: t.lastInput.EpochStart, Directions: []EventDirectionState{}}
	for _, state := range t.states {
		s := cloneEventState(state)
		s.EventValid = s.Event != nil && !s.RequiredUnknown && eventActive(v.Window) && s.Event.Window == v.Window && s.Event.EpochStart == v.EpochStart &&
			s.Event.Confirmation.PublishedAt <= at && s.Event.Confirmation.BarEnd <= at && at-s.Event.Confirmation.BarEnd < 900
		if s.Event != nil && !s.EventValid {
			s.Reason = "再開eventの期限又は窓が不成立"
		}
		v.Directions = append(v.Directions, s)
	}
	return v, nil
}
