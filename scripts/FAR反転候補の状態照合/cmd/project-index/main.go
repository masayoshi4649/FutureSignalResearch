package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
)

const sourceSHA = "37261350b06e5abe86622d7ec3d05b7bfaea3c11372be7817d62102b0a505676"

type row struct {
	Session  string  `json:"session"`
	Order    string  `json:"entry_order_id"`
	Snapshot string  `json:"snapshot_id"`
	At       float64 `json:"at"`
	States   string  `json:"check_states"`
}
type projection struct {
	CheckOrder []string          `json:"チェック順"`
	Rows       []row             `json:"入口索引"`
	Inputs     map[string]string `json:"入力SHA256"`
}

// extract は元指紋を検査し、損益・u群・check本文を型に取り込まず索引化します。
//
// 引数: source/out(string)は既存派生JSONと新規出力先です。
// 返り値: errorは元指紋/302一意/54入力/出力の不整合です。
func extract(source, out string) error {
	raw, err := os.ReadFile(source)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(raw)
	if hex.EncodeToString(sum[:]) != sourceSHA {
		return fmt.Errorf("固定した元索引SHAと違います")
	}
	var p projection
	if err = json.Unmarshal(raw, &p); err != nil {
		return err
	}
	if len(p.Rows) != 302 || len(p.CheckOrder) != 20 {
		return fmt.Errorf("302入口/20状態欄が必要です")
	}
	seen := map[string]bool{}
	sessions := map[string]bool{}
	for _, r := range p.Rows {
		key := r.Session + "/" + r.Order
		if seen[key] || r.Order == "" || r.Snapshot == "" || r.At <= 0 || len(r.States) != 20 {
			return fmt.Errorf("ID/時刻/状態欄が不整合です")
		}
		seen[key] = true
		sessions[r.Session] = true
		for _, c := range r.States {
			if c != '+' && c != '-' && c != '?' {
				return fmt.Errorf("未知の状態文字です")
			}
		}
	}
	native := map[string]string{}
	for path, h := range p.Inputs {
		path = strings.ReplaceAll(path, "\\", "/")
		if strings.HasPrefix(path, "work/97実行/正式54場/") && strings.HasSuffix(path, ".json") {
			session := strings.TrimSuffix(strings.TrimPrefix(path, "work/97実行/正式54場/"), ".json")
			if session == "完了" {
				continue
			}
			if !sessions[session] || len(h) != 64 {
				return fmt.Errorf("対象外の本文SHAです")
			}
			native[path] = h
		}
	}
	if len(native) != 54 || len(sessions) != 54 {
		return fmt.Errorf("54場の本文SHAが必要です")
	}
	p.Inputs = native
	encoded, err := json.Marshal(p)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(out, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err = f.Write(append(encoded, '\n')); err != nil {
		return err
	}
	fmt.Println("302入口・20文字状態・54本文SHAを射影、Native/金融は読取0")
	return nil
}

// main は明示した派生JSONだけから最小の再現用索引を作ります。
//
// 引数: --source/--out(string)は元と新規保存先です。
// 返り値: ありません。失敗は終了1です。
func main() {
	source := flag.String("source", "", "元372613版のJSON")
	out := flag.String("out", "", "新規の再現用入口索引")
	flag.Parse()
	if *source == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "--source と --out が必要です")
		os.Exit(2)
	}
	if err := extract(*source, *out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
