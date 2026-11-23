// 由来99固定金融: scripts/FAR背景と勢いと数量の入口/entry_gate.go
// 由来SHA256: 8511f2f9451625352e140be3c136754da3501eab6321745470e6ac3402947701
// 由来98固定金融: scripts/FAR利益前ATR追尾/entry_gate.go
// 由来SHA256: dda3e2532a486af88bdf3674a959d6e08b0a4e4106e83c3c658a0d1a3d08d7e6
// 由来97停止金融: scripts/FAR初回利益確定/entry_gate.go
// 由来SHA256: 2a0d1d672c249f609953370d3295ecae7cc51c8264932785acf65e011db62fd4
// 由来: scripts/FAR5分枠の順行反転と数量/entry_gate.go
// 由来SHA256: 45019f080133d8087b4969e5bdee173f358994ec1ecd22dcf8fa33ee8d71c4c6
package minigrossguard100

import (
	"fmt"
	"math"
)

// EntryCandidate は既存金融の適格性と量計算を終えた一出生の値copyです。
// 技法側はSource/方向/要求枚数を書き戻せません。
type EntryCandidate struct {
	Ordinal   int            `json:"ordinal"`
	At        float64        `json:"at"`
	Side      int            `json:"side"`
	Source    SourceIdentity `json:"source"`
	Quote     QuoteStamp     `json:"quote"`
	Available int            `json:"available"`
	Quantity  int            `json:"quantity"`
}

// GateDecision は技法の公開snapshotと既知/採否だけを金融へ渡します。
// 保護幅・注文量・Source更新のfieldは持ちません。
type GateDecision struct {
	Policy     string `json:"policy"`
	SnapshotID string `json:"snapshot_id"`
	Known      bool   `json:"known"`
	Allowed    bool   `json:"allowed"`
	Role       string `json:"role"`
	Reason     string `json:"reason"`
}

// EntryGate は公開済み技法snapshotだけで候補を判定するcallbackです。
//
// 引数: EntryCandidateは金融が作る深い値copyです。
// 返り値: GateDecision/errorは技法の採否又は不整合です。
type EntryGate func(EntryCandidate) (GateDecision, error)

// evaluateEntryGate は金融から独立した型境界を検査して判定を凍結します。
//
// 引数: policy(string)はE3S、gate(EntryGate)は必須、candidate(EntryCandidate)は既存適格値です。
// 返り値: GateDecision/errorは値copyの判定又は入力/返答契約の不整合です。
func evaluateEntryGate(policy string, gate EntryGate, candidate EntryCandidate) (GateDecision, error) {
	if policy != "E3S" || gate == nil {
		return GateDecision{}, fmt.Errorf("技法callback又は政策名が不正です")
	}
	if candidate.Ordinal <= 0 || !finiteActual(candidate.At) || candidate.At <= 0 || math.Mod(candidate.At, 300) != 0 ||
		(candidate.Side != 1 && candidate.Side != -1) || candidate.Source.SignalID == "" ||
		candidate.Source.BirthQuantity <= 0 || !finiteActual(candidate.Source.BirthTime) || candidate.Source.BirthTime > candidate.At ||
		candidate.Available <= 0 || candidate.Available > 10 || candidate.Quantity <= 0 ||
		candidate.Quantity > candidate.Available || candidate.Quantity > candidate.Source.BirthQuantity ||
		!normalActual(candidate.Quote) || candidate.Quote.Time > candidate.At || candidate.Quote.Index < 0 || candidate.Quote.SourceLine <= 0 {
		return GateDecision{}, fmt.Errorf("技法callback候補の時計/方向/数量/公開気配が不正です")
	}
	decision, err := gate(valueCopy(candidate))
	if err != nil {
		return GateDecision{}, fmt.Errorf("技法callback: %w", err)
	}
	if decision.Policy != policy || decision.SnapshotID == "" || decision.Allowed && !decision.Known {
		return GateDecision{}, fmt.Errorf("技法callbackの政策/snapshot/既知採否が不整合です")
	}
	return valueCopy(decision), nil
}
