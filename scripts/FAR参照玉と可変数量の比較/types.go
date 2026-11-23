// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/types.go
// 87派生元SHA256: 10d5eae5278c904d9278874f6a4001b30f0ffe1e3bb46af5c9cd8a357a2f1881

// 86派生元: scripts/保持帯の返済側固定否定/types.go
// 86派生元SHA256: 74d85c01df2fcfec3bac26612fd57be18f3c2e7bffe15bb0db61608303b86029

package far87

import (
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
	far84 "github.com/masayoshi4649/SessionTradeExecuter/research84"
)

// 固定84/83の公開型を同一のまま再用します。金融Bookは87の金融担当が定義します。
type Quote = far84.Quote
type Trade = far84.Trade
type TechnicalView = far84.TechnicalView
type InputManifest = far84.InputManifest
type InputSession = far84.InputSession
type InputFile = far84.InputFile
type RawQuality = far84.RawQuality
type ChartBank = far84.ChartBank
type ChartView = far84.ChartView
type CurrentEvidence = far84.CurrentEvidence
type CurrentShort = far82.CurrentShort
type CurrentShortWindow = far82.CurrentShortWindow
type EntryDecision = far84.EntryDecision
type StructureAnchor = far84.StructureAnchor
type PolicySnapshot = far84.PolicySnapshot
type PolicyDirection = far84.PolicyDirection
type Decision = far84.Decision

// Modes はSourceのS/SCだけを分ける外キーで、内部金融modeはS0G1です。
var Modes = []string{"R0G1", "R1G1"}

// NewChartBank は固定84と同じ公開足・前足の追跡器を生成します。
//
// 引数: base(*far80.TechnicalBank)は当場前の指標種です。
// 返り値: *ChartBankは旧83/84と同じ追跡器です。
func NewChartBank(base *far80.TechnicalBank) *ChartBank { return far84.NewChartBank(base) }

// ExtractCurrent は固定84の同じ源特徴snapshot抽出だけを呼びます。
//
// 引数: observation(strategy.Observation)は当時特徴、line(int64)は物理原行です。
// 返り値: CurrentEvidenceは純C0入口と当時保持帯へ共有する情報です。
func ExtractCurrent(observation strategy.Observation, line int64) CurrentEvidence {
	return far84.ExtractCurrent(observation, line)
}

// Decide は固定84のC0純入口を無変更で呼びます。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、current(CurrentEvidence)は当時入力です。
// 返り値: Decisionは旧B1全snapshotを含む固定C0判定、errorは固定84の入力不整合です。
func Decide(at float64, q Quote, chart ChartView, current CurrentEvidence) (Decision, error) {
	return far84.Decide(at, q, chart, current, "C0")
}
