package far82

import (
	"fmt"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// 固定81の入力・約定・実所有会計を型同一のまま再用します。
type Quote = far81.Quote
type Trade = far81.Trade
type TechnicalView = far81.TechnicalView
type ReferenceLot = far81.ReferenceLot
type ReferenceClose = far81.ReferenceClose
type ReferenceFrame = far81.ReferenceFrame
type InputManifest = far81.InputManifest
type InputSession = far81.InputSession
type InputFile = far81.InputFile
type RawQuality = far81.RawQuality
type Book = far81.Book
type BookResult = far81.BookResult

// Modes はチャート主軸の入口二案と、固定済みG1保護だけです。
var Modes = []string{"B0G1", "B1G1"}

// NewBook は82の入口IDを確認し、固定81のG1実会計を作ります。
//
// 引数: sessionID/mode(string)は場とB0G1又はB1G1、cap(int)は片側上限です。
// 返り値: *Bookは既存G1会計、errorは未知ID又は会計引数の不正です。
func NewBook(sessionID, mode string, cap int) (*Book, error) {
	if mode != "B0G1" && mode != "B1G1" {
		return nil, fmt.Errorf("未知の82政策です:%s", mode)
	}
	return far81.NewBook(sessionID, mode, cap)
}
