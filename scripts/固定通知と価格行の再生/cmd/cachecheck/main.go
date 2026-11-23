package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

// main は完成cacheと元96だけで逐次/二並列の再現を照合します。
//
// 引数: --tape/--sha/--baseline/--out(string)は完成cache/SHA/元保存/新規証拠です。
// 返り値: ありません。Raw/CSVやSource戦略へ接続せず、不一致なら非0です。
func main() {
	path := flag.String("tape", "", "完成Tape.gz")
	sha := flag.String("sha", "", "完成SHA256")
	base := flag.String("baseline", "", "元96JSON")
	out := flag.String("out", "", "新規証拠JSON")
	flag.Parse()
	if *path == "" || *sha == "" || *base == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "全path/SHAを明示")
		os.Exit(1)
	}
	if _, err := os.Stat(*out); !os.IsNotExist(err) {
		fmt.Fprintln(os.Stderr, "出力先は新規")
		os.Exit(1)
	}
	r, err := tape.VerifyCache(*path, *sha, *base)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	body, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		panic(err)
	}
	if err = os.WriteFile(*out, append(body, '\n'), 0644); err != nil {
		panic(err)
	}
	fmt.Println(string(body))
}
