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

	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// writeNew は結果を既存ファイルへ上書きせず保存します。
//
// 引数: path(string)は新しい保存先、value(any)はJSON化する値です。
// 返り値: errorは既存成果物又は書込の失敗、正常ならnilです。
func writeNew(path string, value any) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	output, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	if _, err = output.Write(data); err != nil {
		output.Close()
		return err
	}
	return output.Close()
}

// run は固定台帳の既知54場だけを選び、各結果と指紋を保存します。
//
// 引数: なし。返り値: errorは引数・固定入力・会計・保存の不整合です。
func run() error {
	manifestPath := flag.String("manifest", "", "固定80台帳")
	out := flag.String("out", "", "新しい結果フォルダ")
	limit := flag.Int("limit", 54, "54場からの先頭試験数。1〜54")
	flag.Parse()
	if *manifestPath == "" || *out == "" || *limit < 1 || *limit > 54 {
		return fmt.Errorf("台帳・保存先・1〜54の件数が必要です")
	}
	body, err := os.ReadFile(*manifestPath)
	if err != nil {
		return err
	}
	var manifest native.InputManifest
	if err = json.Unmarshal(body, &manifest); err != nil {
		return err
	}
	if err = native.ValidateManifest(manifest); err != nil {
		return err
	}
	selected := []native.InputSession{}
	for _, input := range manifest.Sessions {
		day := strings.Split(input.ID, "_")[0]
		if day >= "2026-09-21" && day <= "2026-10-27" {
			selected = append(selected, input)
		}
	}
	if len(selected) != 54 {
		return fmt.Errorf("元54場が揃っていません: %d", len(selected))
	}
	selected = selected[:*limit]
	if _, err = os.Stat(*out); !os.IsNotExist(err) {
		return fmt.Errorf("保存先は未作成フォルダが必要です: %s", *out)
	}
	if err = os.MkdirAll(*out, 0755); err != nil {
		return err
	}
	manifestHash := sha256.Sum256(body)
	resultHashes := map[string]string{}
	started := time.Now().Format(time.RFC3339Nano)
	for index, input := range selected {
		result, err := native.Replay(manifest.Root, input)
		if err != nil {
			_ = writeNew(filepath.Join(*out, "不完了.json"), map[string]any{"session": input.ID, "error": err.Error(), "result": result})
			return err
		}
		name := input.ID + ".json"
		path := filepath.Join(*out, name)
		if err = writeNew(path, result); err != nil {
			return err
		}
		saved, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		digest := sha256.Sum256(saved)
		resultHashes[name] = hex.EncodeToString(digest[:])
		fmt.Printf("%d/%d %s 完了\n", index+1, len(selected), input.ID)
	}
	if err = native.ValidateManifest(manifest); err != nil {
		return err
	}
	after, err := os.ReadFile(*manifestPath)
	if err != nil {
		return err
	}
	afterHash := sha256.Sum256(after)
	if afterHash != manifestHash {
		return fmt.Errorf("固定台帳が実行中に変わりました")
	}
	return writeNew(filepath.Join(*out, "完了.json"), map[string]any{
		"開始": started, "終了": time.Now().Format(time.RFC3339Nano), "場数": len(selected), "台帳SHA256": hex.EncodeToString(manifestHash[:]), "結果SHA256": resultHashes,
		"対象": "2026-09-21〜10-27の既知54場の先頭選択", "新5分": false, "新利益追尾": false, "外テクニカル": false,
	})
}

// main は成功時0、失敗時1で元手法再現を終了します。
//
// 引数: なし。返り値: なし。
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
