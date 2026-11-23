package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	model "github.com/masayoshi4649/SessionTradeExecuter/miniprotect"
)

// writeNew は既存の研究結果を上書きせずJSONを保存します。
//
// 引数: path(string)、value(any)は新規保存先と内容。
// 返り値: errorは直列化/保存失敗です。
func writeNew(path string, value any) error {
	body, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	body = append(body, '\n')
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	if _, err = file.Write(body); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

// run は固定54場の先頭指定だけを再生し、Shadow全文比較と終了指紋を保存します。
//
// 引数: なし。返り値: errorは引数・入力・会計・Shadow差・保存の異常です。
func run() error {
	manifestPath := flag.String("manifest", "", "固定80の入力台帳")
	baseline := flag.String("baseline", "", "固定93の圧縮Nativeフォルダ")
	proof := flag.String("baseline-proof", "", "固定93完了記録")
	out := flag.String("out", "", "未作成結果フォルダ")
	limit := flag.Int("limit", 54, "54場からの先頭接続数1〜54")
	flag.Parse()
	if *manifestPath == "" || *baseline == "" || *proof == "" || *out == "" || *limit < 1 || *limit > 54 {
		return fmt.Errorf("台帳/93基準/完了正本/新規先/件数を明示してください")
	}
	body, err := os.ReadFile(*manifestPath)
	if err != nil {
		return err
	}
	hash := sha256.Sum256(body)
	if hex.EncodeToString(hash[:]) != "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42" {
		return fmt.Errorf("固定80台帳の指紋差")
	}
	var manifest model.InputManifest
	if err = json.Unmarshal(body, &manifest); err != nil {
		return err
	}
	if err = model.ValidateManifest(manifest); err != nil {
		return err
	}
	selected := []model.InputSession{}
	for _, input := range manifest.Sessions {
		day := strings.Split(input.ID, "_")[0]
		if day >= "2026-09-21" && day <= "2026-10-27" {
			selected = append(selected, input)
		}
	}
	if len(selected) != 54 {
		return fmt.Errorf("固定54場がない")
	}
	selected = selected[:*limit]
	if _, err = os.Stat(*out); !os.IsNotExist(err) {
		return fmt.Errorf("結果先は未作成フォルダだけ")
	}
	if err = os.MkdirAll(*out, 0755); err != nil {
		return err
	}
	started := time.Now().Format(time.RFC3339Nano)
	hashes := map[string]string{}
	for i, input := range selected {
		value, err := model.Replay(manifest.Root, input, *baseline, *proof)
		if err != nil {
			_ = writeNew(filepath.Join(*out, "不完了.json"), map[string]any{"session": input.ID, "error": err.Error(), "result": value})
			return err
		}
		name := input.ID + ".json"
		path := filepath.Join(*out, name)
		if err = writeNew(path, value); err != nil {
			return err
		}
		saved, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		digest := sha256.Sum256(saved)
		hashes[name] = hex.EncodeToString(digest[:])
		fmt.Printf("%d/%d %s Shadow93全文一致・12Actor終了\n", i+1, len(selected), input.ID)
	}
	if err = model.ValidateManifest(manifest); err != nil {
		return err
	}
	after, err := os.ReadFile(*manifestPath)
	if err != nil {
		return err
	}
	if sha256.Sum256(after) != hash {
		return fmt.Errorf("台帳が実行中に変化")
	}
	return writeNew(filepath.Join(*out, "完了.json"), map[string]any{
		"試行": 94, "開始": started, "終了": time.Now().Format(time.RFC3339Nano), "場数": len(selected), "Actor数": 12,
		"台帳SHA256": hex.EncodeToString(hash[:]), "結果SHA256": hashes, "Shadow93全文一致": true,
		"元FAR全面同値": false, "新5分": false, "新全玉利益追尾": true, "外側Entry条件追加": false,
	})
}

// main は実口座通信を持たない再生CLIを終了コード付きで実行します。
//
// 引数: なし。返り値: なし。
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
