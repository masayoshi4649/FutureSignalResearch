// 由来: work/101保有失効の金融案/held_exit.go
// 由来SHA256: 6dd1f079c7b704bc167579376a29ddc949fef7833d32b52b62af83431706b5ad
package minishortfinance

import (
	"encoding/json"
	"fmt"

	minix5 "github.com/masayoshi4649/SessionTradeExecuter/minix5"
)

const HeldExitReason = "利益起動後の5分価格・勢い・数量の複合失効"

// HeldAssessment は停止したX5純式と型同一の公開値です。
type HeldAssessment = minix5.HeldAssessment

// HeldCandidate は金融私有所有を確認した実保有の値copyです。
type HeldCandidate struct {
	SessionID     string         `json:"session_id"`
	Kind          string         `json:"kind"`
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

// HeldExitGate は実保有の値copyから純技法の公開判定を返します。
//
// 引数: HeldCandidateは実positionと最新Quoteの値copyです。
// 返り値: HeldAssessment/errorは純判定又は出典/公開値の不整合です。
type HeldExitGate func(HeldCandidate) (HeldAssessment, error)

// HeldExitPoint はSource/H/HGと排他的なgrid返済要求の証拠です。
type HeldExitPoint struct {
	Candidate  HeldCandidate  `json:"candidate"`
	Assessment HeldAssessment `json:"assessment"`
}

// HeldExitTrace は実保有ごとの対象外/未知/不成立/要求を区別します。
type HeldExitTrace struct {
	PositionID string          `json:"position_id"`
	Quantity   int             `json:"quantity"`
	Reserved   int             `json:"reserved"`
	Free       int             `json:"free"`
	Status     string          `json:"status"`
	Reason     string          `json:"reason"`
	Candidate  *HeldCandidate  `json:"candidate"`
	Assessment *HeldAssessment `json:"assessment"`
	Requested  int             `json:"requested"`
	OrderID    string          `json:"order_id"`
}

// HeldExitGridTrace はquietと金融保有退出の時計を混同しない一枠の記録です。
type HeldExitGridTrace struct {
	At         float64         `json:"at"`
	SnapshotID string          `json:"snapshot_id"`
	Quiet      bool            `json:"quiet"`
	Quote      *QuoteStamp     `json:"quote"`
	Positions  []HeldExitTrace `json:"positions"`
}

// bindHeldAssessment は返却型の有限性と最新金融Quote/時計/純判定構造を結びます。
//
// 引数: candidate(HeldCandidate)、assessment(HeldAssessment)、sessionID/kind(string)は実所有と純判定です。
// 返り値: HeldAssessment/errorは深い値copy又は出典/既知性の不整合です。純数学は再計算しません。
func bindHeldAssessment(candidate HeldCandidate, assessment HeldAssessment, sessionID, kind string) (HeldAssessment, error) {
	body, err := json.Marshal(assessment)
	if err != nil {
		return HeldAssessment{}, fmt.Errorf("保有callbackの有限な保存型が不正です: %w", err)
	}
	var copy HeldAssessment
	if err = json.Unmarshal(body, &copy); err != nil {
		return HeldAssessment{}, err
	}
	d, e, q := copy.Decision, copy.Evidence, candidate.Quote
	if d.Policy != "X5" || d.SnapshotID != candidate.SnapshotID || d.At != candidate.At || d.Side != candidate.Side ||
		d.Allowed && !d.Known || d.Role == "" || d.Reason == "" || e.SceneID != sessionID || e.Contract == "" || e.Quantity.Kind != kind {
		return HeldAssessment{}, fmt.Errorf("保有callbackの政策/snapshot/場/時計/sideが不一致です")
	}
	expected := minix5.CurrentQuoteEvidence{Reference: "NK225", Time: q.Time, Received: candidate.QuoteReceived,
		SourceIndex: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask}
	if e.Current != expected || e.Three.BarEnd < 0 || e.Three.BarEnd > candidate.At || e.Three.AvailableAt < 0 || e.Three.AvailableAt > candidate.At {
		return HeldAssessment{}, fmt.Errorf("保有callbackのCurrent/Features連番/物理行/公開時計が不一致です")
	}
	ids := []string{"X5.現在価格時計", "X5.公開3分", "X5.P", "X5.M", "X5.Q"}
	if len(copy.Checks) != len(ids) {
		return HeldAssessment{}, fmt.Errorf("保有callbackの全check集合が不正です")
	}
	known, passed := true, true
	for i, check := range copy.Checks {
		if check.ID != ids[i] || check.Reason == "" || check.Passed && !check.Known {
			return HeldAssessment{}, fmt.Errorf("保有callbackのcheck名/既知性が不正です")
		}
		known = known && check.Known
		if check.Known && !check.Passed {
			passed = false
		}
	}
	if !passed {
		known = true
	}
	if d.Known != known || d.Allowed != (known && passed) {
		return HeldAssessment{}, fmt.Errorf("保有callbackの三値ANDが不整合です")
	}
	if e.Quantity.Known && (e.Quantity.Time != q.Time || e.Quantity.Index != q.Index || kind == "Day" && e.Quantity.OwnAt != q.Time) {
		return HeldAssessment{}, fmt.Errorf("保有callbackの量が同Current出典ではありません")
	}
	if d.Allowed && (!normalActual(q) || candidate.At-q.Time > 15 || !e.Quantity.Known ||
		e.SignedCloseEMA == nil || e.SignedHistogramDelta == nil || e.SignedQuantity == nil) {
		return HeldAssessment{}, fmt.Errorf("成立した保有callbackの必要品質/式値が不足しています")
	}
	return copy, nil
}

// evaluateHeldExitGrid はSource後・entry前に正残/起動済み/未予約だけを調べます。
//
// 引数: at(float64)、snapshotID(string)、gate(HeldExitGate)は観測済みの枠と純判断です。
// 返り値: errorは所有/起動/callback出典不整合です。fill/MTM/ATR/Sourceは更新しません。
func (b *ActualBook) evaluateHeldExitGrid(at float64, snapshotID string, gate HeldExitGate) error {
	if err := b.checkActual(); err != nil {
		return err
	}
	quiet, _, _ := b.gridQuiet(at)
	grid := HeldExitGridTrace{At: at, SnapshotID: snapshotID, Quiet: quiet, Positions: []HeldExitTrace{}}
	if b.haveQuote {
		q := b.last
		grid.Quote = &q
	}
	for i := range b.result.Positions {
		p := &b.result.Positions[i]
		if p.Quantity == 0 {
			continue
		}
		trace := HeldExitTrace{PositionID: p.ID, Quantity: p.Quantity, Reserved: p.Reserved, Free: p.Quantity - p.Reserved,
			Status: "対象外", Reason: "P0利益起動前"}
		if p.ProtectionActive {
			if p.Activation == nil || !finiteActual(p.Activation.UnitNet, p.Activation.GainPoints, p.Activation.Quote.Time) ||
				p.Activation.UnitNet <= 0 || p.Activation.Quote.Time > at || !b.haveQuote || p.Activation.Quote.Index > b.last.Index {
				return fmt.Errorf("保有exitの私有利益起動証拠が不正です")
			}
			if trace.Free == 0 {
				trace.Reason = "先行Source/保護が全量予約済み"
			} else if !normalActual(b.last) {
				trace.Status, trace.Reason = "判定不能", "金融の最新QuoteOK/BBOが不良"
			} else {
				candidate := HeldCandidate{SessionID: b.result.Session.ID, Kind: b.result.Session.Kind, PositionID: p.ID, Source: p.Source,
					SourceHoldID: p.SourceHoldID, Side: p.Side, At: at, SnapshotID: snapshotID, Quote: b.last,
					QuoteReceived: b.lastReceived, Quantity: p.Quantity, Reserved: p.Reserved, Activation: *p.Activation}
				copy := valueCopy(candidate)
				trace.Candidate = &copy
				b.heldCallbackActive = true
				assessment, err := func() (HeldAssessment, error) {
					defer func() { b.heldCallbackActive = false }()
					return gate(valueCopy(candidate))
				}()
				if err != nil {
					return fmt.Errorf("保有callback: %w", err)
				}
				p = &b.result.Positions[b.positions[candidate.PositionID]]
				if p.ID != candidate.PositionID || p.Side != candidate.Side || p.SourceHoldID != candidate.SourceHoldID || !p.ProtectionActive ||
					p.Quantity != candidate.Quantity || p.Reserved != candidate.Reserved || p.Source != candidate.Source ||
					p.Activation == nil || *p.Activation != candidate.Activation || b.last != candidate.Quote || b.lastReceived != candidate.QuoteReceived {
					return fmt.Errorf("保有callback中に私有状態が変化しました")
				}
				assessment, err = bindHeldAssessment(candidate, assessment, b.result.Session.ID, b.result.Session.Kind)
				if err != nil {
					return err
				}
				trace.Assessment = &assessment
				trace.Status, trace.Reason = "不成立", assessment.Decision.Reason
				if !assessment.Decision.Known {
					trace.Status = "判定不能"
				} else if assessment.Decision.Allowed {
					point := &HeldExitPoint{Candidate: candidate, Assessment: assessment}
					id, err := b.requestExitTagged(p, trace.Free, at, b.last, HeldExitReason, "", "", nil, nil, point, nil)
					if err != nil {
						return err
					}
					trace.Status, trace.Reason, trace.Requested, trace.OrderID = "返済要求", HeldExitReason, trace.Free, id
				}
			}
		}
		grid.Positions = append(grid.Positions, valueCopy(trace))
	}
	b.result.HeldExitGrids = append(b.result.HeldExitGrids, grid)
	return b.checkActual()
}
