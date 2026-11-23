package main

import (
	"flag"
	"fmt"
	"os"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
)

// main は固定indexと条件が明示された場合だけ新97金融を実行します。
//
// 引数: CLI --run/--index/--condition/--proof96/--out/--workers/--stageです。
// 返り値: ありません。未指定/不整合/未完は非0で終了します。
func main() {
	run := flag.Bool("run", false, "固定条件後の金融運転")
	index := flag.String("index", "", "Tape index JSON")
	condition := flag.String("condition", "", "固定97条件JSON")
	proof := flag.String("proof96", "", "固定96完了記録")
	out := flag.String("out", "", "新規結果dir")
	stage := flag.String("stage", "", "first2又はfull54")
	workers := flag.Int("workers", 8, "並列数1..16")
	flag.Parse()
	if !*run {
		fmt.Fprintln(os.Stderr, "固定条件後の明示--runが必要です")
		os.Exit(1)
	}
	if err := port.RunBatch(port.BatchArguments{Index: *index, Condition: *condition, Proof96: *proof, Out: *out, Stage: *stage, Workers: *workers}); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
