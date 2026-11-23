package main

import (
	"compress/gzip"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

// main は先頭2場の明示された入力だけで旧96P0の再現を確認します。
//
// 引数: --input/--out(string)はScalar構築入力と新規保存dirです。
// 返り値: ありません。不整合は非0、Source/Features/新出口を運転しません。
func main() {
	input := flag.String("input", "", "Scalar構築JSON.gz")
	out := flag.String("out", "", "新規結果dir")
	flag.Parse()
	if err := run(*input, *out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// run は公開通知再構成と8Book全文一致を保存し、未完Tapeを成功へしません。
//
// 引数: input/out(string)は許可されたファイルと新規保存dirです。
// 返り値: errorは指紋/Source/金融/保存の不整合です。
func run(input, out string) error {
	if input == "" || out == "" {
		return fmt.Errorf("入出力を明示")
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		return fmt.Errorf("出力先は新規")
	}
	before, err := tape.Digest(input)
	if err != nil {
		return err
	}
	f, err := os.Open(input)
	if err != nil {
		return err
	}
	g, err := gzip.NewReader(f)
	if err != nil {
		f.Close()
		return err
	}
	var in tape.ProductionInput
	err = json.NewDecoder(g).Decode(&in)
	g.Close()
	f.Close()
	if err != nil {
		return err
	}
	for p, v := range in.Evidence {
		got, err := tape.Digest(p)
		if err != nil {
			return err
		}
		if got != v {
			return fmt.Errorf("構築元指紋差:%s", p)
		}
	}
	started := time.Now()
	cached, base, err := tape.BuildProduction(in)
	if err != nil {
		return err
	}
	books, err := tape.Replay(cached)
	if err != nil {
		return err
	}
	if err = tape.CompareEight(books, base); err != nil {
		return err
	}
	after, err := tape.Digest(input)
	if err != nil {
		return err
	}
	if before != after {
		return fmt.Errorf("入力前後変化")
	}
	for p, v := range in.Evidence {
		got, err := tape.Digest(p)
		if err != nil {
			return err
		}
		if got != v {
			return fmt.Errorf("構築元の前後指紋差")
		}
	}
	if err = os.MkdirAll(out, 0755); err != nil {
		return err
	}
	path := filepath.Join(out, "tape.json.gz")
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	w := gzip.NewWriter(file)
	err = json.NewEncoder(w).Encode(cached)
	if closeErr := w.Close(); err == nil {
		err = closeErr
	}
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	sha, err := tape.Digest(path)
	if err != nil {
		return err
	}
	stats := map[string]int{}
	for _, e := range cached.Events {
		stats[e.Kind]++
		stats["non_empty_batches"] += len(e.NonEmpty)
		stats["all_batches"] += len(e.Methods)
	}
	proof := map[string]any{"成功": true, "session": in.Session.ID, "固定96全文一致Book": 8, "除外": []string{}, "Source判断/Features再実行": 0, "H/新条件損益計算": 0, "イベント": stats, "構築元SHA256": in.Evidence, "入力SHA256前": before, "入力SHA256後": after, "tape_SHA256": sha, "検査秒": time.Since(started).Seconds(), "scope": "固定先頭2場内の一場。同条件P0の再現だけ。新しい収益性/速度優位は未検証"}
	body, err := json.MarshalIndent(proof, "", "  ")
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(out, "証拠.json"), append(body, '\n'), 0644); err != nil {
		return err
	}
	fmt.Println(string(body))
	return nil
}
