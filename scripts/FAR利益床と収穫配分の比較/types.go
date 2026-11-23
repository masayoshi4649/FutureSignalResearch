// Package far89 は固定88入口で共通利益床とG1/G2収穫配分を比較します。
package far89

import (
	"fmt"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
	far88 "github.com/masayoshi4649/SessionTradeExecuter/research88"
)

// 公開入力/Sourceは固定87、純入口と順序状態は固定88の同一型を再用します。
type Quote = far87.Quote
type Trade = far87.Trade
type TechnicalView = far87.TechnicalView
type InputManifest = far87.InputManifest
type InputSession = far87.InputSession
type InputFile = far87.InputFile
type RawQuality = far87.RawQuality
type ChartBank = far87.ChartBank
type ChartView = far87.ChartView
type CurrentEvidence = far87.CurrentEvidence
type CurrentShort = far87.CurrentShort
type CurrentShortWindow = far87.CurrentShortWindow
type Decision = far87.Decision
type StructureAnchor = far87.StructureAnchor
type Reference = far87.Reference
type ReferenceFrame = far87.ReferenceFrame
type ReferenceLot = far87.ReferenceLot
type ReferenceClose = far87.ReferenceClose
type ReadSnapshot = far87.ReadSnapshot
type ReadLot = far87.ReadLot

type QualificationCheck = far88.QualificationCheck
type EntryDirectionEvaluation = far88.EntryDirectionEvaluation
type EntryEvaluation = far88.EntryEvaluation
type PoolEvaluation = far88.PoolEvaluation
type EventInput = far88.EventInput
type EventRecord = far88.EventRecord
type EventPoint = far88.EventPoint
type ResumeEvent = far88.ResumeEvent
type EventDirectionState = far88.EventDirectionState
type EventSnapshot = far88.EventSnapshot
type EventTracker = far88.EventTracker
type PolicySupply = far88.PolicySupply
type EntryOrderBinding = far88.EntryOrderBinding
type TechnicalEquivalence = far88.TechnicalEquivalence
type ProfitSupport = far88.ProfitSupport
type ProfitCurrent = far88.ProfitCurrent
type ProfitTrigger = far88.ProfitTrigger
type ProfitContext = far88.ProfitContext
type GridDecision = far88.GridDecision
type SourceEvent = far88.SourceEvent
type MergedEnd = far88.MergedEnd

// Modesは外入口とguardの会計名、EntryPoliciesは一度だけ評価する入口です。
var Modes = []string{"E0G1", "E0G2", "E1G1", "E1G2"}
var EntryPolicies = []string{"E0", "E1"}

// modeParts は固定した外会計名を入口と共通guardへ分離します。
//
// 引数: mode(string)はE0G1/E0G2/E1G1/E1G2です。
// 返り値: policy/guard(string)とerrorは分離値又は未知名の拒否です。
func modeParts(mode string) (string, string, error) {
	switch mode {
	case "E0G1", "E0G2", "E1G1", "E1G2":
		return mode[:2], mode[2:], nil
	default:
		return "", "", fmt.Errorf("外会計名が不正です:%s", mode)
	}
}

// NewChartBank は固定87と同一の数値種/直前足追跡器を返します。
//
// 引数: base(*far80.TechnicalBank)は当場前の独立種です。
// 返り値: *ChartBankは元の公開型で、計算法は複写しません。
func NewChartBank(base *far80.TechnicalBank) *ChartBank { return far87.NewChartBank(base) }

// NewReference は元FAR全原行運転とmetadataを固定87から再用します。
//
// 引数: method(string)、session(strategy.Session)、cap(int)は元Source引数です。
// 返り値: *Referenceとerrorは固定87の参照器又は入力不正です。
func NewReference(method string, session strategy.Session, cap int) (*Reference, error) {
	return far87.NewReference(method, session, cap)
}

// ExtractCurrent は固定87の当原行特徴抜粋を同じ物理出典で返します。
//
// 引数: observation(strategy.Observation)、line(int64)は当時特徴と物理行です。
// 返り値: CurrentEvidenceは固定87そのものです。
func ExtractCurrent(observation strategy.Observation, line int64) CurrentEvidence {
	return far87.ExtractCurrent(observation, line)
}

// Decide は旧actual bankのC0診断を固定87から返します。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、current(CurrentEvidence)は当時値です。
// 返り値: Decisionとerrorは固定C0又は入力不整合です。入口資格へ混ぜません。
func Decide(at float64, q Quote, chart ChartView, current CurrentEvidence) (Decision, error) {
	return far87.Decide(at, q, chart, current)
}

// NewEventTracker は固定88の公開順序器をそのまま生成します。
//
// 引数: ありません。
// 返り値: *EventTrackerは別実体の固定88順序器です。
func NewEventTracker() *EventTracker { return far88.NewEventTracker() }

// EvaluateEntry は固定88の現在資格と順序資格を直接呼びます。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、events(EventSnapshot)は当時値です。
// 返り値: EntryEvaluationとerrorは固定88の純判断又は不整合です。
func EvaluateEntry(at float64, q Quote, chart ChartView, events EventSnapshot) (EntryEvaluation, error) {
	return far88.EvaluateEntry(at, q, chart, events)
}

// FilterEntry は固定88の全raw順位と入口ID部分列を直接呼びます。
//
// 引数: policy(string)、raw(ReadSnapshot)、evaluation(EntryEvaluation)はE0/E1の入力です。
// 返り値: ReadSnapshot/[]PoolEvaluation/errorは固定88の独立供給値又は不整合です。
func FilterEntry(policy string, raw ReadSnapshot, evaluation EntryEvaluation) (ReadSnapshot, []PoolEvaluation, error) {
	return far88.FilterEntry(policy, raw, evaluation)
}
