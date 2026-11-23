package minichart

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
// 引数: policy(string)はA/B/AB、gate(EntryGate)は必須、candidate(EntryCandidate)は既存適格値です。
// 返り値: GateDecision/errorは値copyの判定又は入力/返答契約の不整合です。
func evaluateEntryGate(policy string, gate EntryGate, candidate EntryCandidate) (GateDecision, error) {
	if (policy != "A" && policy != "B" && policy != "AB") || gate == nil {
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
