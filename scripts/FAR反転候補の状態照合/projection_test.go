package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestPortableIndex99 は正式な小型索引をGo型へ読み、302件の一意性だけを検査します。
//
// 引数: t(*testing.T)は計画/索引の構文確認です。
// 返り値: ありません。Native・Raw・純査定・金融は実行しません。
func TestPortableIndex99(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "docs", "議論", "検討資料", "反転Bの2候補", "再現用計画.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var p plan
	if err = json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	if len(p.Native) != 54 || p.Root != root {
		t.Fatal("計画の場数/絶対root")
	}
	for _, code := range p.Code {
		if !strings.HasPrefix(code.Path, "scripts/") {
			t.Fatal("元workコードへの依存", code.Path)
		}
		if _, err = readPinned(root, code); err != nil {
			t.Fatal(err)
		}
	}
	raw, err = readPinned(root, p.Index)
	if err != nil {
		t.Fatal(err)
	}
	var idx indexData
	if err = json.Unmarshal(raw, &idx); err != nil {
		t.Fatal(err)
	}
	if len(idx.Rows) != 302 || len(idx.CheckOrder) != 20 || len(idx.Inputs) != 54 {
		t.Fatal("小型索引の要素数")
	}
	seen := map[string]bool{}
	sessions := map[string]bool{}
	for _, row := range idx.Rows {
		key := row.Session + "/" + row.Order
		if seen[key] || row.Order == "" || row.Snapshot == "" || row.At <= 0 || len(row.States) != 20 {
			t.Fatal("ID/時刻/状態の差")
		}
		seen[key] = true
		sessions[row.Session] = true
		for _, state := range row.States {
			if state != '+' && state != '-' && state != '?' {
				t.Fatal("状態文字の差")
			}
		}
	}
	for _, file := range p.Native {
		if !sessions[file.Session] {
			t.Fatal("索引に場がない")
		}
		if len(idx.Inputs["work/97実行/正式54場/"+file.Session+".json"]) != 64 {
			t.Fatal("元本文SHAがない")
		}
	}
	if len(sessions) != 54 {
		t.Fatal("場が不足")
	}
}
