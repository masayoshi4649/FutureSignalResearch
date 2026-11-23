// replay は固定原板を読むオフライン研究CLIです。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// main は入力台帳の順に再生し、各場終了時に結果を個別保存します。
//
// 引数: コマンド引数のmanifest/out/limit/delayです。
// 返り値: なし。異常は非0終了し、既存出力を上書きしません。
func main() {
	manifest := flag.String("manifest", "", "固定入力台帳JSON")
	out := flag.String("out", "", "新規出力先")
	limit := flag.Int("limit", 0, "先頭接続確認場数、0は全場")
	delay := flag.Float64("delay", 0, "判断後の追加価格時計遅延秒")
	flag.Parse()
	if *manifest == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "manifestとoutが必要です")
		os.Exit(2)
	}
	raw, e := os.ReadFile(*manifest)
	if e != nil {
		fail(e)
	}
	var m far80.InputManifest
	if e = json.Unmarshal(raw, &m); e != nil {
		fail(e)
	}
	if e = far80.ValidateManifest(m); e != nil {
		fail(e)
	}
	if _, e = os.Stat(*out); !os.IsNotExist(e) {
		fail(fmt.Errorf("出力先は新規である必要があります: %s", *out))
	}
	if e = os.MkdirAll(*out, 0755); e != nil {
		fail(e)
	}
	bank := far80.NewTechnicalBank()
	contract := ""
	for i, s := range m.Sessions {
		if *limit > 0 && i >= *limit {
			break
		}
		if s.Contract != contract {
			bank = far80.NewTechnicalBank()
			contract = s.Contract
		}
		r, err := far80.Replay(m.Root, s, bank, *delay)
		if err != nil {
			fail(fmt.Errorf("%s: %w", s.ID, err))
		}
		data, err := json.Marshal(r)
		if err != nil {
			fail(err)
		}
		if err = os.WriteFile(filepath.Join(*out, s.ID+".json"), data, 0644); err != nil {
			fail(err)
		}
		fmt.Printf("%s", s.ID)
		for _, mode := range []string{"F0", "P1", "T1"} {
			b := r.Books[mode]
			fmt.Printf(" %s=%.0f円 新規%d枚 未解決%v", mode, b.Metrics.NetPnLYen, b.Metrics.EntryQuantity, b.Unresolved)
		}
		fmt.Println()
	}
}

// fail は研究CLIの異常を明示し処理を終了します。
//
// 引数: errはerrorの原因です。
// 返り値: なし。終了コード1で終了します。
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
