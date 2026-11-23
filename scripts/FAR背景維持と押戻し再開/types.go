// Package far88 は元Source背景へ現在状態と押戻し再開履歴を加える独立入口比較です。
package far88

import (
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// 公開金融/Source/指標は固定87そのものをimportし、本文を複写しません。
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
type Decision = far87.Decision
type StructureAnchor = far87.StructureAnchor
type Reference = far87.Reference
type ReferenceFrame = far87.ReferenceFrame
type ReferenceLot = far87.ReferenceLot
type ReferenceClose = far87.ReferenceClose
type ReadSnapshot = far87.ReadSnapshot
type ReadLot = far87.ReadLot
type Book = far87.Book
type BookResult = far87.BookResult

var Modes = []string{"S", "E0", "E1"}

// NewChartBank は固定87の同じ公開足/前足追跡器を生成します。
//
// 引数: base(*far80.TechnicalBank)は独立の当場前指標種です。
// 返り値: *ChartBankは固定87の実体で、金融又はSourceを作りません。
func NewChartBank(base *far80.TechnicalBank) *ChartBank { return far87.NewChartBank(base) }

// NewReference は固定87の全原行Sourceと読取metadataだけを再用します。
//
// 引数: method(string)、session(strategy.Session)、cap(int)は旧Source引数です。
// 返り値: *Referenceは固定87、errorは元Sourceの入力不正です。
func NewReference(method string, session strategy.Session, cap int) (*Reference, error) {
	return far87.NewReference(method, session, cap)
}

// ExtractCurrent は固定87のC0用当原行特徴を同じ出典で抽出します。
//
// 引数: observation(strategy.Observation)、line(int64)は当時特徴と物理行です。
// 返り値: CurrentEvidenceは固定87の保存型です。
func ExtractCurrent(observation strategy.Observation, line int64) CurrentEvidence {
	return far87.ExtractCurrent(observation, line)
}

// Decide は旧actual bankだけで固定87C0を無変更で評価します。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、current(CurrentEvidence)は旧時点入力です。
// 返り値: Decisionは固定87C0、errorは旧判定の入力不整合です。
func Decide(at float64, q Quote, chart ChartView, current CurrentEvidence) (Decision, error) {
	return far87.Decide(at, q, chart, current)
}
