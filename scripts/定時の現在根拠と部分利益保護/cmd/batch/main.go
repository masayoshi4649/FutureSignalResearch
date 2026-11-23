// batch は定時の現在根拠と部分利益保護を研究するオフラインCLIです。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// main は固定台帳の各場を独立workerへ渡し、四政策・二遅延を保存します。
//
// 引数: CLIのmanifest/outはstring、workersはintです。
// 返り値: なし。既存出力を上書きせず、異常時は非0で終了します。
func main() {
	manifest := flag.String("manifest", "", "固定入力台帳JSON")
	out := flag.String("out", "", "新規出力根")
	workers := flag.Int("workers", 16, "並列数1..16")
	flag.Parse()
	if *manifest == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "manifestとoutが必要です")
		os.Exit(2)
	}
	raw, e := os.ReadFile(*manifest)
	if e != nil {
		fail(e)
	}
	var inputs far81.InputManifest
	if e = json.Unmarshal(raw, &inputs); e != nil {
		fail(e)
	}
	if e = far81.RunBatch(inputs, *out, *workers, os.Stdout); e != nil {
		fail(e)
	}
}

// fail は入力又は再生異常を明示し、CLIを終了します。
//
// 引数: err(error)は原因です。
// 返り値: なし。終了コード1で終了します。
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
