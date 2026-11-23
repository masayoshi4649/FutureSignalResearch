package main

import (
	"flag"
	"fmt"
	build "github.com/masayoshi4649/SessionTradeExecuter/continuous101"
	"os"
)

// main は明示されたRoot実行だけを新規出力へ配送します。
//
// 引数: CLI flagsは固定閉鎖/許可54/旧Tape/元入力/停止/stageです。
// 返り値: ありません。未指定又は検査失敗は終了1です。
func main() {
	var a build.Arguments
	run := flag.Bool("run", false, "Rootの別許可後にだけ実行")
	flag.StringVar(&a.Root, "root", "", "repo絶対根")
	flag.StringVar(&a.Proof, "proof100", "", "固定100完了")
	flag.StringVar(&a.Allowed, "allowed", "", "許可54metadata")
	flag.StringVar(&a.Manifest, "manifest", "", "固定80入力台帳")
	flag.StringVar(&a.Index, "index", "", "固定100のstage Tape台帳")
	flag.StringVar(&a.Out, "out", "", "新規出力dir")
	flag.StringVar(&a.Stage, "stage", "first2", "first2又はfull54")
	flag.StringVar(&a.Stop, "stop", "", "所有停止証拠")
	flag.StringVar(&a.First2, "first2", "", "full54前の同版成功")
	flag.IntVar(&a.MaxNKRows, "max-nk-rows", 1000000, "場単位positiveNK行の資源上限")
	flag.Uint64Var(&a.MaxHeapMiB, "max-heap-mib", 4096, "Go heap標本の資源上限MiB（OS RSS保証ではない）")
	flag.Parse()
	if !*run {
		fmt.Fprintln(os.Stderr, "--runとRootの別実行許可が必要")
		os.Exit(1)
	}
	if e := build.RunFirst(a); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
