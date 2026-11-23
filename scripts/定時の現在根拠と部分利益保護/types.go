package far81

import (
	"fmt"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// 固定済み80の入力・時計・証券約定型だけを再用し、80のファイルを変更しません。
type Quote = far80.Quote
type Trade = far80.Trade
type TechnicalView = far80.TechnicalView
type ReferenceLot = far80.ReferenceLot
type ReferenceClose = far80.ReferenceClose
type ReferenceFrame = far80.ReferenceFrame
type InputManifest = far80.InputManifest
type InputSession = far80.InputSession
type InputFile = far80.InputFile
type RawQuality = far80.RawQuality

// Modes は事前に固定する入口二案と出口二案の全組合せです。
var Modes = []string{"B0G0", "B0G1", "B1G0", "B1G1"}

// splitMode は新研究の入口と保護を分離し、未知のIDを拒否します。
//
// 引数: mode(string)はB0/B1とG0/G1を連結したIDです。
// 返り値: entry/guard(string)は両政策、errorは未知IDです。
func splitMode(mode string) (entry, guard string, err error) {
	for _, known := range Modes {
		if mode == known {
			return mode[:2], mode[2:], nil
		}
	}
	return "", "", fmt.Errorf("未知の81政策です:%s", mode)
}
