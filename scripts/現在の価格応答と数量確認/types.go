package far84

import (
	"fmt"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
	far83 "github.com/masayoshi4649/SessionTradeExecuter/research83"
)

// 固定83/82の型を同一のまま再用し、金融実装を複写しません。
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
type StructureAnchor = far83.StructureAnchor
type Book = far83.Book
type BookResult = far83.BookResult

// Modes は外側の入口識別だけで、全Bookの内部政策はS0G1です。
var Modes = []string{"A0G1", "C0G1", "C1G1"}

// NewBook は外側の入口IDを確認し、固定83のS0G1実会計を生成します。
//
// 引数: sessionID/mode(string)は場と外側入口政策、cap(int)は片側上限です。
// 返り値: *Bookは内部modeがS0G1の固定会計、errorは未知入口又は会計引数の不正です。
func NewBook(sessionID, mode string, cap int) (*Book, error) {
	for _, known := range Modes {
		if mode == known {
			return far83.NewBook(sessionID, "S0G1", cap)
		}
	}
	return nil, fmt.Errorf("未知の84外側政策です:%s", mode)
}

// NewChartBank は固定82の前足結合器を、固定80の数値種へ接続します。
//
// 引数: base(*far80.TechnicalBank)は当場前の指標種です。
// 返り値: *ChartBankは固定82と同じ確定足・前足追跡器です。
func NewChartBank(base *far80.TechnicalBank) *ChartBank { return far82.NewChartBank(base) }

// ExtractCurrent は固定82と同じ短秒・OFI・価格構造の当時snapshotを作ります。
//
// 引数: observation(strategy.Observation)は当時の元特徴、line(int64)は物理原行です。
// 返り値: CurrentEvidenceは旧B1と追加入口へ共有する現在情報です。
func ExtractCurrent(observation strategy.Observation, line int64) CurrentEvidence {
	return far82.ExtractCurrent(observation, line)
}
