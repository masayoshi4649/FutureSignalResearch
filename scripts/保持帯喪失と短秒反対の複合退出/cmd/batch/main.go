// 86派生元: scripts/保持帯の返済側固定否定/cmd/batch/main.go
// 86派生元SHA256: f30ea9ef91c933b606e076b63943a87f5e7452ea154ff13bb6ae0ec5520fd8e4

// 85派生元: scripts/現在の価格応答と数量確認/cmd/batch/main.go
// 85派生元SHA256: bf3d8907260807f22fa93eaeb1592497292625790653b187ea8c650946338ff8

// 84派生元: scripts/構造否定と利益配分/cmd/batch/main.go
// 84派生元SHA256: 49c23f893d548195428c91dd9d2328d2a15c3882d29b98812fd7a957dc32855b

// batch は保持帯喪失と短秒反対の複合退出を研究するオフラインCLIです。
package main

// 83派生元: scripts/チャートの現在性と補助確認/cmd/batch/main.go
// 83派生元SHA256: d50ad9101dba8c8368ae9be410ac054a7b55520677d3bf7defd19a0297eb1369

// 派生元: scripts/構造否定と利益配分/cmd/batch/main.go
// 派生元SHA256: 71c25e125c2e503fd9676ceec43440afb7af61c7871ba2153f0ccf75d80db903

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	far86 "github.com/masayoshi4649/SessionTradeExecuter/research86"
)

// main は固定台帳の各場を独立workerへ渡し、同じC0入口・複合退出off/on・二遅延を保存します。
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
	var inputs far86.InputManifest
	if e = json.Unmarshal(raw, &inputs); e != nil {
		fail(e)
	}
	if e = far86.RunBatch(inputs, *out, *workers, os.Stdout); e != nil {
		fail(e)
	}
}

// fail は入力又は再生異常を明示し、CLIを終了します。
//
// 引数: err(error)は原因です。
// 返り値: なし。終了コード1で終了します。
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
