package minishortfinance

import (
	"encoding/json"
	"fmt"

	short "github.com/masayoshi4649/SessionTradeExecuter/minishortexit"
	x5 "github.com/masayoshi4649/SessionTradeExecuter/minix5"
)

type ExitPolicy string

const (
	ExitS5Q         ExitPolicy = "S5Q"
	ExitS515Q       ExitPolicy = "S515Q"
	ShortExitReason            = "利益起動後の短秒進行・現在量の複合失効"
)

type ShortAssessment = short.Assessment

// ShortHeldCandidate は当原行の全旧処理後に金融が確認した実保有です。
type ShortHeldCandidate struct {
	Policy        ExitPolicy     `json:"policy"`
	SessionID     string         `json:"session_id"`
	Kind          string         `json:"kind"`
	Contract      string         `json:"contract"`
	PositionID    string         `json:"position_id"`
	Source        SourceIdentity `json:"source"`
	SourceHoldID  string         `json:"source_hold_id"`
	Side          int            `json:"side"`
	At            float64        `json:"at"`
	SnapshotID    string         `json:"snapshot_id"`
	Quote         QuoteStamp     `json:"quote"`
	QuoteReceived float64        `json:"quote_received"`
	Quantity      int            `json:"quantity"`
	Reserved      int            `json:"reserved"`
	Activation    MTMPoint       `json:"activation"`
}

// ShortExitGate は実保有と当原行の深い値copyを受ける保有専用callbackです。
//
// 引数: ShortHeldCandidate、short.TechnicalGateInputは私有pointerを含まない公開値です。
// 返り値: ShortAssessment/errorは停止純式の出力又は出典不整合です。
type ShortExitGate func(ShortHeldCandidate, short.TechnicalGateInput) (ShortAssessment, error)

type ShortExitPoint struct {
	Candidate  ShortHeldCandidate `json:"candidate"`
	Assessment ShortAssessment    `json:"assessment"`
}
type ShortExitPositionTrace struct {
	PositionID string              `json:"position_id"`
	Quantity   int                 `json:"quantity"`
	Reserved   int                 `json:"reserved"`
	Free       int                 `json:"free"`
	Status     string              `json:"status"`
	Reason     string              `json:"reason"`
	Candidate  *ShortHeldCandidate `json:"candidate"`
	Assessment *ShortAssessment    `json:"assessment"`
	Requested  int                 `json:"requested"`
	OrderID    string              `json:"order_id"`
}
type ShortExitEventTrace struct {
	At         float64                  `json:"at"`
	SnapshotID string                   `json:"snapshot_id"`
	Quote      QuoteStamp               `json:"quote"`
	Positions  []ShortExitPositionTrace `json:"positions"`
}

// isShortPolicy はS専用の2政策だけを識別します。
//
// 引数: policy(ExitPolicy)は明示設定です。
// 返り値: boolはS5Q/S515Qなら真です。Harvest/Riskは調べません。
func isShortPolicy(policy ExitPolicy) bool { return policy == ExitS5Q || policy == ExitS515Q }

// NewShortExitBook は外部正本から渡された期待限月を私有固定します。
//
// 引数: session(Session)、cfg(ActorConfig)、expectedContract(string)は場/政策/期待限月です。
// 返り値: *ActualBook/errorはS専用の口座です。同じcallback内の自己申告同士ではbindしません。
func NewShortExitBook(session Session, cfg ActorConfig, expectedContract string) (*ActualBook, error) {
	if !isShortPolicy(cfg.ExitPolicy) {
		return nil, fmt.Errorf("S専用constructorの政策はS5Q/S515Qだけです")
	}
	return newActualBook(session, cfg, expectedContract)
}

// bindShortInput は元原行と最新Current/場/限月を値で結びます。
//
// 引数: in(short.TechnicalGateInput)、o(Observation)、line(int64)は同一原行です。
// 返り値: short.TechnicalGateInput/errorはcallback用の深い独立copyです。数値の純採否は停止純式側です。
func (b *ActualBook) bindShortInput(in short.TechnicalGateInput, o Observation, line int64) (short.TechnicalGateInput, error) {
	body, err := json.Marshal(in)
	if err != nil {
		return in, fmt.Errorf("短秒Inputの有限な型が不正: %w", err)
	}
	if in.SnapshotID == "" || in.At != o.Time || in.Chart.At != o.Time || in.Kind != b.result.Session.Kind || in.Chart.Scene.ID != b.result.Session.ID || in.Chart.Scene.Start != b.result.Session.Start || in.Chart.Scene.Contract != b.shortContract || b.shortContract == "" {
		return in, fmt.Errorf("短秒Inputの場/期待限月/At/snapshot差")
	}
	c := in.Current
	if c.Reference != "NK225" || c.Time != o.Time || c.Received != o.Received || c.SourceIndex != o.Index || c.SourceLine != line || c.Last != o.Last || c.Bid != o.Bid || c.Ask != o.Ask {
		return in, fmt.Errorf("短秒Inputと原行のTime/Received/Features連番/物理行/BBO差")
	}
	var copy short.TechnicalGateInput
	err = json.Unmarshal(body, &copy)
	return copy, err
}

// OnNativeStepWithShortExit は旧Stepの全処理を先に完了してからS保有査定を加えます。
//
// 引数: o(Observation)、sourceLine(int64)、batches([]NativeBatch)、input(*short.TechnicalGateInput)、gate(ShortExitGate)です。
// 返り値: errorは時計/Source/純判定/金融の不整合です。空Exitならinput/gate=nilで旧100経路そのものです。
func (b *ActualBook) OnNativeStepWithShortExit(o Observation, sourceLine int64, batches []NativeBatch, input *short.TechnicalGateInput, gate ShortExitGate) error {
	if err := b.ready(); err != nil {
		return err
	}
	if !isShortPolicy(b.result.Config.ExitPolicy) {
		if b.result.Config.ExitPolicy != "" || input != nil || gate != nil {
			return b.stop(fmt.Errorf("短秒専用Stepとexit設定/入力が不整合です"))
		}
		return b.onNativeStep(o, sourceLine, batches)
	}
	if input == nil || gate == nil {
		return b.stop(fmt.Errorf("S政策は当原行Inputと実保有callbackが必須です"))
	}
	copy, err := b.bindShortInput(*input, o, sourceLine)
	if err != nil {
		return b.stop(err)
	}
	if err = b.onNativeStep(o, sourceLine, batches); err != nil {
		return err
	}
	if err = b.evaluateShortExit(copy, gate); err != nil {
		return b.stop(err)
	}
	return nil
}

// bindShortAssessment は返却された全公開出典と政策/check集合を検査します。
//
// 引数: c(ShortHeldCandidate)、in(short.TechnicalGateInput)、value(ShortAssessment)は同一callbackです。
// 返り値: ShortAssessment/errorは独立copy又は返却破損です。純式の再実装はしません。
func bindShortAssessment(c ShortHeldCandidate, in short.TechnicalGateInput, value ShortAssessment) (ShortAssessment, error) {
	body, err := json.Marshal(value)
	if err != nil {
		return value, fmt.Errorf("短秒callback返却が非有限/不正: %w", err)
	}
	var out ShortAssessment
	if err = json.Unmarshal(body, &out); err != nil {
		return out, err
	}
	d, e, q := out.Decision, out.Evidence, c.Quote
	if d.Policy != string(c.Policy) || d.At != c.At || d.Side != c.Side || d.SnapshotID != c.SnapshotID || d.Allowed && !d.Known || d.Role == "" || d.Reason == "" || e.SceneID != c.SessionID || e.Contract != c.Contract || e.Quantity.Kind != c.Kind {
		return out, fmt.Errorf("短秒callbackの政策/場/期待限月/実side差")
	}
	want := x5.CurrentQuoteEvidence{Reference: "NK225", Time: q.Time, Received: c.QuoteReceived, SourceIndex: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask}
	if e.Current != want || e.PriceAge == nil || *e.PriceAge != c.At-q.Time || e.ShortTime != in.Current.Short.Time || e.ShortMid != in.Current.Short.Mid || e.Five.Window != in.Current.Short.Five || e.Fifteen.Window != in.Current.Short.Fifteen {
		return out, fmt.Errorf("短秒callbackの現在原行/窓/両端差")
	}
	ids := []string{"S.現在価格時計", "S.5秒速度"}
	if c.Policy == ExitS515Q {
		ids = append(ids, "S.15秒速度")
	}
	ids = append(ids, "S.現在量")
	if len(out.Checks) != len(ids) {
		return out, fmt.Errorf("短秒全check集合差")
	}
	known, passed := true, true
	for i, v := range out.Checks {
		if v.ID != ids[i] || v.Reason == "" || v.Passed && !v.Known {
			return out, fmt.Errorf("短秒check名/既知性差")
		}
		known = known && v.Known
		if v.Known && !v.Passed {
			passed = false
		}
	}
	if !passed {
		known = true
	}
	if d.Known != known || d.Allowed != (known && passed) {
		return out, fmt.Errorf("短秒三値AND差")
	}
	if e.Quantity.Known && (e.Quantity.Time != q.Time || e.Quantity.Index != q.Index || c.Kind == "Day" && e.Quantity.OwnAt != q.Time) {
		return out, fmt.Errorf("短秒数量の同Current差")
	}
	if d.Allowed && (!normalActual(q) || e.Five.SignedSpeed == nil || *e.Five.SignedSpeed >= 0 || !e.Five.Known || e.SignedQuantity == nil || *e.SignedQuantity >= 0 || !e.Quantity.Known || c.Policy == ExitS515Q && (!e.Fifteen.Known || e.Fifteen.SignedSpeed == nil || *e.Fifteen.SignedSpeed >= 0)) {
		return out, fmt.Errorf("成立した短秒判定の必要値不足")
	}
	return out, nil
}

// evaluateShortExit は旧Step完了後の起動済み実未予約量だけを査定します。
//
// 引数: in(short.TechnicalGateInput)、gate(ShortExitGate)は当原行の公開値とcallbackです。
// 返り値: errorは私有所有/返却/予約の破損です。0保有の空traceは保存しません。
func (b *ActualBook) evaluateShortExit(in short.TechnicalGateInput, gate ShortExitGate) error {
	if err := b.checkActual(); err != nil {
		return err
	}
	trace := ShortExitEventTrace{At: in.At, SnapshotID: in.SnapshotID, Quote: b.last, Positions: []ShortExitPositionTrace{}}
	for i := range b.result.Positions {
		p := &b.result.Positions[i]
		if p.Quantity == 0 {
			continue
		}
		t := ShortExitPositionTrace{PositionID: p.ID, Quantity: p.Quantity, Reserved: p.Reserved, Free: p.Quantity - p.Reserved, Status: "対象外", Reason: "P0利益起動前"}
		if p.ProtectionActive {
			if p.Activation == nil || p.Activation.UnitNet <= 0 || !finiteActual(p.Activation.UnitNet, p.Activation.GainPoints, p.Activation.Quote.Time) || p.Activation.Quote.Time > b.last.Time || p.Activation.Quote.Index > b.last.Index {
				return fmt.Errorf("短秒退出の私有利益起動証拠が不正")
			}
			if t.Free == 0 {
				t.Reason = "先行Source/P0/短秒が全量予約済み"
			} else if !normalActual(b.last) {
				t.Status, t.Reason = "判定不能", "金融の最新QuoteOK/BBOが不良"
			} else {
				c := ShortHeldCandidate{Policy: b.result.Config.ExitPolicy, SessionID: b.result.Session.ID, Kind: b.result.Session.Kind, Contract: b.shortContract, PositionID: p.ID, Source: p.Source, SourceHoldID: p.SourceHoldID, Side: p.Side, At: in.At, SnapshotID: in.SnapshotID, Quote: b.last, QuoteReceived: b.lastReceived, Quantity: p.Quantity, Reserved: p.Reserved, Activation: *p.Activation}
				copy := valueCopy(c)
				t.Candidate = &copy
				b.heldCallbackActive = true
				assessment, err := func() (ShortAssessment, error) {
					defer func() { b.heldCallbackActive = false }()
					return gate(valueCopy(c), valueCopy(in))
				}()
				if err != nil {
					return fmt.Errorf("短秒callback: %w", err)
				}
				p = &b.result.Positions[b.positions[c.PositionID]]
				if p.ID != c.PositionID || p.Side != c.Side || p.SourceHoldID != c.SourceHoldID || !p.ProtectionActive || p.Quantity != c.Quantity || p.Reserved != c.Reserved || p.Source != c.Source || p.Activation == nil || *p.Activation != c.Activation || b.last != c.Quote || b.lastReceived != c.QuoteReceived {
					return fmt.Errorf("短秒callback中の私有状態変化")
				}
				assessment, err = bindShortAssessment(c, in, assessment)
				if err != nil {
					return err
				}
				t.Assessment = &assessment
				t.Status, t.Reason = "不成立", assessment.Decision.Reason
				if !assessment.Decision.Known {
					t.Status = "判定不能"
				} else if assessment.Decision.Allowed {
					point := &ShortExitPoint{Candidate: c, Assessment: assessment}
					id, err := b.requestExitTagged(p, t.Free, in.At, b.last, ShortExitReason, "", "", nil, nil, nil, point)
					if err != nil {
						return err
					}
					t.Status, t.Reason, t.Requested, t.OrderID = "返済要求", ShortExitReason, t.Free, id
				}
			}
		}
		trace.Positions = append(trace.Positions, valueCopy(t))
	}
	if len(trace.Positions) > 0 {
		b.result.ShortExitEvents = append(b.result.ShortExitEvents, trace)
	}
	return b.checkActual()
}
