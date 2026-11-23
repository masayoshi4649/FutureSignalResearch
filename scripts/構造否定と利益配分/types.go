package far83

import (
	"fmt"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// 固定82の入力・指標・入口型を同じ型のまま再利用します。
type Quote = far82.Quote
type Trade = far82.Trade
type TechnicalView = far82.TechnicalView
type ReferenceLot = far82.ReferenceLot
type ReferenceClose = far82.ReferenceClose
type ReferenceFrame = far82.ReferenceFrame
type InputManifest = far82.InputManifest
type InputSession = far82.InputSession
type InputFile = far82.InputFile
type RawQuality = far82.RawQuality
type ChartBank = far82.ChartBank
type ChartView = far82.ChartView
type CurrentEvidence = far82.CurrentEvidence
type EntryDecision = far82.EntryDecision

// Modes は損失否定二案と利益配分二案を全て組み合わせます。
var Modes = []string{"S0G1", "S1G1", "S0G2", "S1G2"}

// splitMode は損失否定と利益配分を分離し、未定義の組合せを拒否します。
//
// 引数: mode(string)はS0/S1とG1/G2を結合した政策IDです。
// 返り値: stop/guard(string)は両対照、errorは未知IDです。
func splitMode(mode string) (stop, guard string, err error) {
	for _, known := range Modes {
		if mode == known {
			return mode[:2], mode[2:], nil
		}
	}
	return "", "", fmt.Errorf("未知の83政策です:%s", mode)
}

// NewChartBank は固定82の前足結合器を、固定80の数値種へ接続します。
//
// 引数: base(*far80.TechnicalBank)は当場開始前の指標種です。
// 返り値: *ChartBankは固定82と同じ確定足・前足追跡器です。
func NewChartBank(base *far80.TechnicalBank) *ChartBank { return far82.NewChartBank(base) }

// ExtractCurrent は固定82と同じ短秒・OFI・価格構造の当時snapshotを作ります。
//
// 引数: observation(strategy.Observation)は当時の元特徴、line(int64)は物理原行です。
// 返り値: CurrentEvidenceは固定82入口へ渡す現在情報です。
func ExtractCurrent(observation strategy.Observation, line int64) CurrentEvidence {
	return far82.ExtractCurrent(observation, line)
}

// Decide は固定82のB1だけを呼び、出口対照による入口の変化を防ぎます。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、current(CurrentEvidence)は当時入力です。
// 返り値: EntryDecisionは固定82B1と数式も閾値も同じ判定です。
func Decide(at float64, q Quote, chart ChartView, current CurrentEvidence) EntryDecision {
	return far82.Decide(at, q, chart, current, "B1")
}
