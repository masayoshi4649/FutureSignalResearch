// batch は同じ因果的な種から独立場を並列計算する研究CLIです。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// main は固定台帳を読み、主と追加1秒を別の成果物へ再生します。
//
// 引数: CLIのmanifest/outはstring、workersはintです。
// 返り値: なし。失敗時はコード1で終了し、途中結果を成功としません。
func main() {
	manifest := flag.String("manifest", "", "固定入力台帳JSON")
	out := flag.String("out", "", "新規出力根")
	workers := flag.Int("workers", 8, "並列数1..16")
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
	if e = far80.RunBatch(m, *out, *workers, os.Stdout); e != nil {
		fail(e)
	}
}

// fail は並列再生の異常を表示して終了します。
//
// 引数: errはerrorの原因です。
// 返り値: なし。終了コード1で終了します。
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
