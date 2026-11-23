// package minie3 は固定96の純採否checkを選択し、E3/E3Sだけを返します。
package minie3

import (
	"fmt"

	fixed96 "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// 固定純評価本文は複写せず、このSHAの公開AssessTechnicalGateを再用します。
const FixedTechnicalGateSHA256 = "3ba3c2c8d5b67635b9f2edab076ec9cce9785fea090e8ba87191a65142985fbf"

type TechnicalGateInput = fixed96.TechnicalGateInput
type EntryCandidate = fixed96.EntryCandidate
type TechnicalAssessment = fixed96.TechnicalAssessment

var e3Checks = [...]string{
	"共通.現在価格時計",
	"共通.確定3分",
	"共通.確定15分",
	"共通.EMA背景既知",
	"共通.MACD増分",
	"共通.現在量支持",
	"A.3分EMA方向",
	"A.15分EMA方向",
}

// AssessTechnicalGate は既存の時間/既知/方向/量checkだけをE3として評価します。
//
// 引数: input(TechnicalGateInput)、candidate(EntryCandidate)、policy(string)は公開済み値とE3/E3Sです。
// 返り値: TechnicalAssessment/errorは使用した全checkとDecision、又は固定入力検査の不整合です。
// CloseEMA/ATR距離/Close進行を条件にせず、E3Sだけ旧同時スパイク拒否を追加します。
// 金融/Source/方向/数量/価格を変更せず、新規指標や新しい数値閾値を計算しません。
func AssessTechnicalGate(input TechnicalGateInput, candidate EntryCandidate, policy string) (TechnicalAssessment, error) {
	if policy != "E3" && policy != "E3S" {
		return TechnicalAssessment{}, fmt.Errorf("純技法の政策はE3/E3Sだけです")
	}
	base, err := fixed96.AssessTechnicalGate(input, candidate, "A")
	if err != nil {
		return TechnicalAssessment{}, err
	}
	byID := make(map[string]fixed96.TechnicalGateCheck, len(base.Checks))
	for _, item := range base.Checks {
		if _, exists := byID[item.ID]; exists {
			return TechnicalAssessment{}, fmt.Errorf("固定check IDが重複しています: %s", item.ID)
		}
		byID[item.ID] = item
	}
	selected := make([]fixed96.TechnicalGateCheck, 0, 9)
	for _, id := range e3Checks {
		item, exists := byID[id]
		if !exists {
			return TechnicalAssessment{}, fmt.Errorf("固定checkがありません: %s", id)
		}
		selected = append(selected, item)
	}
	if policy == "E3S" {
		item, exists := byID["共通.同時スパイク警戒"]
		if !exists {
			return TechnicalAssessment{}, fmt.Errorf("固定スパイクcheckがありません")
		}
		selected = append(selected, item)
	}
	// ----------------------------------------
	// 未知があっても既知否定を優先し、必要未知だけなら判定不能にします。
	allKnown, refused := true, false
	for _, item := range selected {
		allKnown = allKnown && item.Known
		refused = refused || item.Known && !item.Passed
	}
	decision := fixed96.GateDecision{Policy: policy, SnapshotID: input.SnapshotID, Known: allKnown || refused, Allowed: allKnown && !refused}
	switch {
	case decision.Allowed:
		decision.Role, decision.Reason = "順行", "公開済み複合テクニカルが成立"
	case decision.Known:
		decision.Role, decision.Reason = "待機", "公開済みの必要条件が不成立"
	default:
		decision.Role, decision.Reason = "判定不能", "既知の否定条件はなく採否に必要な値が未知"
	}
	return TechnicalAssessment{Decision: decision, Checks: selected}, nil
}
