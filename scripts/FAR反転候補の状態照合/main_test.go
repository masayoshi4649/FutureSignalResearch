package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// TestExcludedFields99 は禁止した損益・u群・退出欄を型へ取り込まないことを確認します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。人工JSONだけを読みます。
func TestExcludedFields99(t *testing.T) {
	var x indexData
	raw := []byte(`{"入口索引":[{"session":"人工","entry_order_id":"E1","at":300,"group":{"数値へ解釈しない":true},"net_yen":{"不正型":true}}],"母数":{"No-u":{"不正型":true}}}`)
	if err := json.Unmarshal(raw, &x); err != nil || len(x.Rows) != 1 || x.Rows[0].Order != "E1" {
		t.Fatal(err)
	}
	var sc scene
	raw = []byte(`{"session":"人工","actual_run_complete":true,"books":{"H0_B5Q_P0_C0_D0":{"positions":[{"id":"P1","entry_order_id":"E1","initial_quantity":1,"marks":{"first_unit_positive":"読まない"},"realized_net":{"不正型":true},"closed_quote":{"price":"読まない"}}]},"対象外口座":"本体をデコードしない"},"chart_grids":[],"gate_assessments":[]}`)
	if err := json.Unmarshal(raw, &sc); err != nil {
		t.Fatal(err)
	}
	var b book
	if err := json.Unmarshal(sc.Books[account], &b); err != nil || len(b.Positions) != 1 || b.Positions[0].Initial != 1 {
		t.Fatal(err)
	}
	body, err := json.Marshal(b.Positions[0])
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err = json.Unmarshal(body, &fields); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"marks", "realized_net", "closed_quote", "entry_price"} {
		if _, yes := fields[key]; yes {
			t.Fatal("禁止fieldを保持", key)
		}
	}
}

// TestInputPins99 は計画と異なるbyteや範囲外pathを拒否します。
//
// 引数: t(*testing.T)は一時人工ファイルだけを作ります。
// 返り値: ありません。市場入力はありません。
func TestInputPins99(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "人工.json")
	if err := os.WriteFile(path, []byte(`{"value":1}`), 0600); err != nil {
		t.Fatal(err)
	}
	p := pin{Path: "人工.json", SHA: digest([]byte(`{"value":1}`))}
	if _, err := readPinned(root, p); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"value":2}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readPinned(root, p); err == nil {
		t.Fatal("破損を検出しない")
	}
	if _, err := readPinned(root, pin{Path: "../対象外.json"}); err == nil {
		t.Fatal("範囲外pathを拒否しない")
	}
}
