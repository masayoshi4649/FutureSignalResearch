// 人工は市場へ接続せず、独立原板監査へ渡す固定価格列を生成します。
package main

import (
	"compress/gzip"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	far83 "github.com/masayoshi4649/SessionTradeExecuter/research83"
)

// save は既存成果物を上書きせずJSONを新規保存します。
//
// 引数: path(string)は保存先、value(any)はJSON互換値です。
// 返り値: errorは生成・保存の失敗です。
func save(path string, value any) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.Write(data)
	return err
}

// scenario は固定価格列から8会計を作り、手計算の端点を検査します。
//
// 引数: root/name(string)は新規人工根と場面、side(int)は方向です。
// 返り値: errorは手計算との不一致又は保存異常です。
func scenario(root, name string, side int) error {
	session := "2026-09-21_Day"
	folder := filepath.Join(root, fmt.Sprintf("%s_%d", name, side))
	if err := os.MkdirAll(folder, 0755); err != nil {
		return err
	}
	start := float64(time.Date(2026, 9, 21, 9, 15, 0, 0, time.FixedZone("JST", 9*3600)).Unix())
	bids, distance, anchorPrice := []float64{9990, 9990, 10020, 10020, 10120, 10100, 10100}, 20.0, 9900.123456789
	if name == "小利確" {
		bids = []float64{9990, 9990, 10020, 10020, 10040, 10000, 10000}
	}
	if name == "構造先行" {
		bids, distance, anchorPrice = []float64{9990, 9990, 9980, 9980, 10020, 10020, 10000, 10000}, 30, 9985
	}
	if name == "取得時否定" {
		anchorPrice = 9995
	}
	if side < 0 {
		anchorPrice = 20000 - anchorPrice
	}
	anchor := far83.StructureAnchor{Known: true, Price: anchorPrice, At: start, BarEnd: start, Reason: "人工確定EMA"}
	tech := far83.TechnicalView{ExitKnown: true, EMA8_3: anchorPrice, Close3: anchorPrice, Bar3End: start, ATRKnown: true, ATR3: distance}
	if name == "構造未知" {
		anchor = far83.StructureAnchor{Reason: "人工未知"}
		tech.ExitKnown, tech.EMA8_3 = false, 0
	}
	books := map[string]*far83.Book{}
	for _, mode := range far83.Modes {
		for delay := 0; delay <= 1; delay++ {
			b, err := far83.NewBook(session, mode, 100)
			if err != nil {
				return err
			}
			if err = b.SetFillDelay(float64(delay)); err != nil {
				return err
			}
			books[fmt.Sprintf("%s_D%d", mode, delay)] = b
		}
	}
	file, err := os.OpenFile(filepath.Join(folder, "book.jsonl.gz"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	z := gzip.NewWriter(file)
	encoder := json.NewEncoder(z)
	var lastQuote far83.Quote
	for index, bid := range bids {
		ask := bid + 10
		if side < 0 {
			bid, ask = 20000-ask, 20000-bid
		}
		at := start + float64(index*2)
		row := map[string]any{"Symbol": "人工限月", "CurrentPriceTime": time.Unix(int64(at), 0).In(time.FixedZone("JST", 9*3600)).Format(time.RFC3339), "CurrentPrice": (bid + ask) / 2}
		for level := 1; level <= 10; level++ {
			row[fmt.Sprintf("Buy%d", level)] = map[string]any{"Price": bid - float64(level-1)*10, "Qty": 10}
			row[fmt.Sprintf("Sell%d", level)] = map[string]any{"Price": ask + float64(level-1)*10, "Qty": 10}
		}
		if err = encoder.Encode(row); err != nil {
			return err
		}
		q := far83.Quote{Time: at, Index: int64(index), Line: int64(index + 1), Last: (bid + ask) / 2, Bid: bid, Ask: ask, Valid: true}
		lastQuote = q
		for _, b := range books {
			if err = b.OnQuote(q, far83.ReferenceFrame{}, tech); err != nil {
				return err
			}
			if index == 0 {
				entry := ask
				if side < 0 {
					entry = bid
				}
				frame := far83.ReferenceFrame{Lots: []far83.ReferenceLot{{ID: "人工候補", InternalID: "人工候補", Side: side, Quantity: 100, Entry: entry, At: start, Kind: "順行", Owner: "B1", Method: "D164_15"}}}
				if err = b.OnGrid(start, q, frame, tech, anchor); err != nil {
					return err
				}
			}
		}
	}
	// ----------------------------------------
	// 後続の予定枠は未公開のまま判定不能を記録し、価格を補完しません。
	for index := 1; index < 25; index++ {
		at := start + float64(index*900)
		for _, b := range books {
			if err = b.OnGrid(at, lastQuote, far83.ReferenceFrame{}, tech, far83.StructureAnchor{Reason: "人工後続は未公開"}); err != nil {
				return err
			}
		}
	}
	if err = z.Close(); err != nil {
		return err
	}
	if err = file.Close(); err != nil {
		return err
	}
	results := map[string]far83.BookResult{}
	for key, b := range books {
		r := b.Result()
		results[key] = r
		expected := 87800.0
		if key[2:4] == "G1" {
			expected = 27800
		}
		if name == "小利確" {
			expected = -12200
			if key[2:4] == "G1" {
				expected = 2800
			}
		}
		if name == "構造先行" {
			expected = -12200
			if key[2:4] == "G1" {
				expected = 2800
			}
			if key[:2] == "S1" {
				expected = -32200
			}
		}
		if name == "取得時否定" && key[:2] == "S1" {
			expected = 7800
		}
		if r.Unresolved || r.Metrics.NetPnLYen != expected {
			return fmt.Errorf("人工端点差 %s/%s 期待%.0f 保存%.0f", name, key, expected, r.Metrics.NetPnLYen)
		}
	}
	grid := map[string]any{"at": start, "entry_policy": "B1", "structure_anchor": anchor, "decision": map[string]any{"technical": tech}}
	return save(filepath.Join(folder, session+".json"), map[string]any{"session": session, "books": results, "grid_decisions": []any{grid}})
}

// main は5場面の鏡像だけを生成し、正式市場入力を受け付けません。
//
// 引数: CLIのout(string)は存在しない作業出力です。
// 返り値: ありません。失敗時は終了1です。
func main() {
	out := flag.String("out", "", "新規人工出力")
	flag.Parse()
	if *out == "" {
		fmt.Fprintln(os.Stderr, "outが必要です")
		os.Exit(2)
	}
	if _, err := os.Stat(*out); !os.IsNotExist(err) {
		fmt.Fprintln(os.Stderr, "新規出力のみです")
		os.Exit(2)
	}
	for _, name := range []string{"大順行", "小利確", "構造先行", "取得時否定", "構造未知"} {
		for _, side := range []int{1, -1} {
			if err := scenario(*out, name, side); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
		}
	}
	fmt.Println("10人工場面・80会計の手計算端点が一致")
}
