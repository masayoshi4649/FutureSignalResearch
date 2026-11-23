package main

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"

	fixed "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

const account = "H0_B5Q_P0_C0_D0"

type pin struct {
	Path    string `json:"path"`
	SHA     string `json:"sha256"`
	Session string `json:"session,omitempty"`
}
type plan struct {
	Root   string `json:"root"`
	Native []pin  `json:"対象Native"`
	Code   []pin  `json:"使用コード"`
	Index  pin    `json:"固定302索引"`
}

// 以下は損益・marks・u群・退出値を持たない専用の読取型です。
type indexRow struct {
	Session  string  `json:"session"`
	Order    string  `json:"entry_order_id"`
	Snapshot string  `json:"snapshot_id"`
	At       float64 `json:"at"`
	States   string  `json:"check_states"`
}
type indexData struct {
	Rows       []indexRow        `json:"入口索引"`
	CheckOrder []string          `json:"チェック順"`
	Inputs     map[string]string `json:"入力SHA256"`
}
type opportunity struct {
	Ordinal        int                  `json:"ordinal"`
	At             float64              `json:"evaluated_at"`
	Side           int                  `json:"side"`
	Source         fixed.SourceIdentity `json:"source"`
	Quote          fixed.QuoteStamp     `json:"quote"`
	Available      int                  `json:"available"`
	SourceQuantity int                  `json:"source_quantity"`
	Order          string               `json:"entry_order_id"`
	Requested      int                  `json:"requested"`
}
type position struct {
	ID      string               `json:"id"`
	Order   string               `json:"entry_order_id"`
	Source  fixed.SourceIdentity `json:"source"`
	Hold    string               `json:"source_hold_id"`
	Side    int                  `json:"side"`
	Initial int                  `json:"initial_quantity"`
}
type book struct {
	Opportunities []json.RawMessage `json:"entry_opportunities"`
	Positions     []position        `json:"positions"`
}
type storedGate struct {
	Source     fixed.SourceIdentity      `json:"source"`
	Candidate  fixed.EntryCandidate      `json:"candidate"`
	Assessment fixed.TechnicalAssessment `json:"assessment"`
}
type scene struct {
	Session  string                     `json:"session"`
	Complete bool                       `json:"actual_run_complete"`
	Charts   []json.RawMessage          `json:"chart_grids"`
	Books    map[string]json.RawMessage `json:"books"`
	Gates    []json.RawMessage          `json:"gate_assessments"`
}

// digest は保存byteのSHA256を返します。
//
// 引数: data([]byte)は保存入力です。
// 返り値: stringは小文字の指紋です。
func digest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

// readPinned は計画に固定したファイルだけを読みます。
//
// 引数: root(string)、p(pin)は許可範囲と指紋です。
// 返り値: []byte/errorは保存byte又は指紋差です。
func readPinned(root string, p pin) ([]byte, error) {
	if !filepath.IsLocal(p.Path) {
		return nil, fmt.Errorf("計画の相対pathが不正です")
	}
	raw, err := os.ReadFile(filepath.Join(root, p.Path))
	if err != nil {
		return nil, err
	}
	if digest(raw) != p.SHA {
		return nil, fmt.Errorf("計画指紋の差: %s", p.Path)
	}
	return raw, nil
}

// require は破損や欠落を成功へ補完しません。
//
// 引数: ok(bool)、message(string)は成立要件です。
// 返り値: errorは不成立時だけ非nilです。
func require(ok bool, message string) error {
	if !ok {
		return fmt.Errorf("%s", message)
	}
	return nil
}

// clockInput は当時のcheckを説明する入力だけを抜きます。
//
// 引数: in(fixed.TechnicalGateInput)、c(fixed.EntryCandidate)は要求時の公開値です。
// 返り値: map[string]anyは時計・価格・勢い・必要量の値です。損益や退出はありません。
func clockInput(in fixed.TechnicalGateInput, c fixed.EntryCandidate) map[string]any {
	t := in.Chart.Chart.Technical
	s := float64(c.Side)
	e := c.Quote.Ask
	if c.Side < 0 {
		e = c.Quote.Bid
	}
	recent := []map[string]any{}
	for _, p := range in.Recent3 {
		x := p.Chart.Technical
		recent = append(recent, map[string]any{"scene": p.Scene, "at": p.At, "three": p.Three, "close": x.Close3, "ema8": x.EMA8_3, "rsi": x.RSI3, "trend_known": x.TrendKnown, "exit_known": x.ExitKnown, "spike_known": x.SpikeKnown, "reversal_known": x.ReversalKnown})
	}
	var distance any
	if t.ATR3 > 0 {
		distance = s * (e - t.EMA8_3) / t.ATR3
	}
	quantity := map[string]any{}
	if in.Kind == "Day" {
		v := in.Current.Buy
		if c.Side < 0 {
			v = in.Current.Sell
		}
		quantity = map[string]any{"kind": "OFI30", "known": v.OFIKnown, "reason": v.OFIReason, "own_at": v.OwnAt, "raw": v.OFI30, "signed": s * v.OFI30}
	} else {
		n := in.Current.Night
		v := n.Band
		quantity = map[string]any{"kind": "E08同価格4成分差", "available": n.Available, "window": n.Window, "known": v.QuantityKnown, "time": v.Time, "index": v.Index, "bid_refill": v.BidRefill, "ask_deplete": v.AskDeplete, "ask_refill": v.AskRefill, "bid_deplete": v.BidDeplete, "signed": s * (v.BidRefill + v.AskDeplete - v.AskRefill - v.BidDeplete)}
	}
	return map[string]any{
		"snapshot_id": in.SnapshotID, "at": in.At, "kind": in.Kind, "candidate": c,
		"quote_age_seconds": in.At - c.Quote.Time, "scene": in.Chart.Scene, "three": in.Chart.Three, "fifteen": in.Chart.Fifteen,
		"bar3_age_seconds": in.At - t.Bar3End, "bar15_age_seconds": in.At - t.Bar15End,
		"technical":      map[string]any{"trend_known": t.TrendKnown, "exit_known": t.ExitKnown, "spike_known": t.SpikeKnown, "ema8_3": t.EMA8_3, "ema21_3": t.EMA21_3, "ema8_15": t.EMA8_15, "ema21_15": t.EMA21_15, "close3": t.Close3, "histogram3": t.Histogram3, "previous_histogram3": t.PreviousHistogram3, "signed_histogram_delta": s * (t.Histogram3 - t.PreviousHistogram3), "rsi3": t.RSI3, "previous_rsi3": t.PreviousRSI3, "tr3": t.TR3, "atr3": t.ATR3, "previous_atr3": t.PreviousATR3, "entry_distance_atr": distance},
		"current_source": map[string]any{"time": in.Current.Time, "received": in.Current.Received, "source_index": in.Current.SourceIndex, "source_line": in.Current.SourceLine, "last": in.Current.Last, "bid": in.Current.Bid, "ask": in.Current.Ask},
		"quantity":       quantity, "recent3": recent,
	}
}

// run は固定54場の主実入口だけへ本名Bの純式を適用します。
//
// 引数: planPath/out(string)は事前固定計画と新規出力先です。
// 返り値: errorは対象/出典/保存査定との不一致です。
func run(planPath, out string) error {
	planRaw, err := os.ReadFile(planPath)
	if err != nil {
		return err
	}
	var p plan
	if err = json.Unmarshal(planRaw, &p); err != nil {
		return err
	}
	if err = require(len(p.Native) == 54, "54場だけが必要です"); err != nil {
		return err
	}
	allPins := append(append([]pin{}, p.Code...), p.Index)
	allPins = append(allPins, p.Native...)
	for _, file := range allPins {
		if _, err = readPinned(p.Root, file); err != nil {
			return err
		}
	}
	raw, err := readPinned(p.Root, p.Index)
	if err != nil {
		return err
	}
	var idx indexData
	if err = json.Unmarshal(raw, &idx); err != nil {
		return err
	}
	if err = require(len(idx.Rows) == 302 && len(idx.CheckOrder) == 20, "302入口/20check索引が必要です"); err != nil {
		return err
	}
	expected := map[string]indexRow{}
	oldSHA := map[string]string{}
	for path, h := range idx.Inputs {
		oldSHA[strings.ReplaceAll(path, "\\", "/")] = h
	}
	for _, row := range idx.Rows {
		key := row.Session + "/" + row.Order
		if _, yes := expected[key]; yes {
			return fmt.Errorf("固定索引の入口重複")
		}
		expected[key] = row
	}
	seen := map[string]bool{}
	sourceSeen := map[string]bool{}
	sessions := map[string]bool{}
	counters := map[string]int{"成立": 0, "既知不成立": 0, "必要未知": 0}
	shape, background, quantity, bindings := 0, 0, 0, 0
	cases := []map[string]any{}
	mother := []map[string]any{}
	for _, file := range p.Native {
		if sessions[file.Session] {
			return fmt.Errorf("場が重複しています")
		}
		sessions[file.Session] = true
		zipped, err := readPinned(p.Root, file)
		if err != nil {
			return err
		}
		reader, err := gzip.NewReader(bytes.NewReader(zipped))
		if err != nil {
			return err
		}
		body, err := io.ReadAll(reader)
		if err != nil {
			return err
		}
		if err = reader.Close(); err != nil {
			return err
		}
		if digest(body) != oldSHA["work/97実行/正式54場/"+file.Session+".json"] {
			return fmt.Errorf("正式gzipと既存302参照Native本文指紋が不一致: %s", file.Session)
		}
		var sc scene
		if err = json.Unmarshal(body, &sc); err != nil {
			return err
		}
		if err = require(sc.Session == file.Session && sc.Complete, "場名/完了の差"); err != nil {
			return err
		}
		bookRaw, ok := sc.Books[account]
		if !ok {
			return fmt.Errorf("主口座がありません")
		}
		var b book
		if err = json.Unmarshal(bookRaw, &b); err != nil {
			return err
		}
		frames := map[float64]fixed.TechnicalGateInput{}
		needed := map[float64]bool{}
		for _, row := range idx.Rows {
			if row.Session == sc.Session {
				needed[row.At] = true
			}
		}
		for _, frameRaw := range sc.Charts {
			var header struct {
				At float64 `json:"at"`
			}
			if err = json.Unmarshal(frameRaw, &header); err != nil {
				return err
			}
			if !needed[header.At] {
				continue
			}
			var frame fixed.TechnicalGateInput
			if err = json.Unmarshal(frameRaw, &frame); err != nil {
				return err
			}
			if _, yes := frames[frame.At]; yes {
				return fmt.Errorf("同時計のChart重複")
			}
			frames[frame.At] = frame
		}
		ops := map[string]opportunity{}
		for _, opRaw := range b.Opportunities {
			var header struct {
				Order string `json:"entry_order_id"`
			}
			if err = json.Unmarshal(opRaw, &header); err != nil {
				return err
			}
			if _, yes := expected[sc.Session+"/"+header.Order]; !yes {
				continue
			}
			var op opportunity
			if err = json.Unmarshal(opRaw, &op); err != nil {
				return err
			}
			if _, yes := ops[op.Order]; yes {
				return fmt.Errorf("同注文機会が重複")
			}
			ops[op.Order] = op
		}
		for _, pos := range b.Positions {
			key := sc.Session + "/" + pos.Order
			row, ok := expected[key]
			if !ok || seen[key] {
				return fmt.Errorf("母集合外又は重複の実入口: %s", key)
			}
			seen[key] = true
			op, ok := ops[pos.Order]
			if !ok {
				return fmt.Errorf("実入口の出生機会がない")
			}
			in, ok := frames[op.At]
			if !ok {
				return fmt.Errorf("要求時Contextなし")
			}
			n := min(op.Source.BirthQuantity, op.SourceQuantity, op.Available)
			if err = require(pos.Initial > 0 && pos.Initial == n && n == op.Requested && pos.Side == op.Side && pos.Source == op.Source && row.At == op.At && row.Snapshot == in.SnapshotID, "初期取得/候補/索引差"); err != nil {
				return err
			}
			identity := sc.Session + "/" + pos.Source.Method + "/" + pos.Source.SignalID + "/" + pos.Hold
			if sourceSeen[identity] {
				return fmt.Errorf("同Sourceを水増し")
			}
			sourceSeen[identity] = true
			c := fixed.EntryCandidate{Ordinal: op.Ordinal, At: op.At, Side: op.Side, Source: op.Source, Quote: op.Quote, Available: op.Available, Quantity: n}
			before, _ := json.Marshal([]any{in, c})
			ab, err := fixed.AssessTechnicalGate(in, c, "AB")
			if err != nil {
				return err
			}
			if len(ab.Checks) != len(idx.CheckOrder) || len(row.States) != len(ab.Checks) {
				return fmt.Errorf("check数差")
			}
			for i, ch := range ab.Checks {
				state := row.States[i]
				if ch.ID != idx.CheckOrder[i] || ch.Known != (state != '?') || ch.Passed != (state == '+') {
					return fmt.Errorf("固定302check差: %s/%s", key, ch.ID)
				}
			}
			matched := 0
			for _, storedRaw := range sc.Gates {
				var header struct {
					Source struct {
						Signal string `json:"signal_id"`
					} `json:"source"`
					Candidate struct {
						At   float64 `json:"at"`
						Side int     `json:"side"`
					} `json:"candidate"`
				}
				if err = json.Unmarshal(storedRaw, &header); err != nil {
					return err
				}
				if header.Source.Signal != pos.Source.SignalID || header.Candidate.At != in.At || header.Candidate.Side != c.Side {
					continue
				}
				var stored storedGate
				if err = json.Unmarshal(storedRaw, &stored); err != nil {
					return err
				}
				got, err := fixed.AssessTechnicalGate(in, stored.Candidate, "AB")
				if err != nil {
					return err
				}
				if !reflect.DeepEqual(got, stored.Assessment) || !reflect.DeepEqual(ab, stored.Assessment) {
					return fmt.Errorf("固定保存AB査定と差")
				}
				matched++
			}
			if matched != 8 {
				return fmt.Errorf("保存AB対応数が8ではありません: %s %d", key, matched)
			}
			bindings += matched
			assessment, err := fixed.AssessTechnicalGate(in, c, "B")
			if err != nil {
				return err
			}
			if assessment.Decision.Policy != "B" {
				return fmt.Errorf("本名Bではありません")
			}
			after, _ := json.Marshal([]any{in, c})
			if !bytes.Equal(before, after) {
				return fmt.Errorf("純入力の副作用")
			}
			checks := map[string]fixed.TechnicalGateCheck{}
			for _, ch := range assessment.Checks {
				checks[ch.ID] = ch
			}
			shapeOK := true
			for _, ch := range assessment.Checks {
				if strings.HasPrefix(ch.ID, "B.") && ch.ID != "B.15分EMA逆背景" {
					shapeOK = shapeOK && ch.Known && ch.Passed
				}
			}
			label := "必要未知"
			if assessment.Decision.Known {
				label = "既知不成立"
				if assessment.Decision.Allowed {
					label = "成立"
				}
			}
			counters[label]++
			if shapeOK {
				shape++
				if ch := checks["B.15分EMA逆背景"]; ch.Known && ch.Passed {
					background++
					if ch := checks["共通.現在量支持"]; ch.Known && ch.Passed {
						quantity++
						failed, unknown := []string{}, []string{}
						for _, ch := range assessment.Checks {
							if !ch.Known {
								unknown = append(unknown, ch.ID)
							} else if !ch.Passed {
								failed = append(failed, ch.ID)
							}
						}
						cases = append(cases, map[string]any{"session": sc.Session, "entry_order_id": pos.Order, "position_id": pos.ID, "source_hold_id": pos.Hold, "assessment": assessment, "既知不成立check": failed, "必要未知check": unknown, "当時入力": clockInput(in, c)})
					}
				}
			}
			mother = append(mother, map[string]any{"session": sc.Session, "entry_order_id": pos.Order, "source_signal_id": pos.Source.SignalID, "source_hold_id": pos.Hold, "snapshot_id": in.SnapshotID})
		}
	}
	if err = require(len(seen) == 302 && len(expected) == 302 && len(sourceSeen) == 302 && len(sessions) == 54 && shape == 16 && background == 7 && quantity == 2 && bindings == 2416, "母集合/既存交差/保存査定との合計差"); err != nil {
		return err
	}
	for _, file := range allPins {
		if _, err = readPinned(p.Root, file); err != nil {
			return err
		}
	}
	sort.Slice(mother, func(i, j int) bool { return fmt.Sprint(mother[i]) < fmt.Sprint(mother[j]) })
	motherBytes, _ := json.Marshal(mother)
	result := map[string]any{"成功": true, "計画SHA256": digest(planRaw), "場数": 54, "一意実入口数": 302, "一意Source出生数": len(sourceSeen), "母集合射影SHA256": digest(motherBytes), "本名政策": "B", "B純評価数": 302, "固定AB純照合数": 302, "保存AB査定照合数": bindings, "B最終": counters, "必要条件交差": map[string]int{"固定3足形状": shape, "上位逆背景も成立": background, "現在量支持も成立": quantity}, "対象2件": cases, "入力前後不変": true, "計画固定入力": allPins, "禁止項目のデコード": map[string]int{"損益": 0, "u勝敗ラベル": 0, "marks": 0, "退出価格": 0}, "市場再売買/Raw/Source再実行/新日": 0, "限界": "302は既存主口座の固定標本。2件の否定内容は新B閾値の有効性や新戦略成績ではない。"}
	encoded, err := json.MarshalIndent(result, "", "  ")
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
	fmt.Printf("成功: 54場/302入口/保存AB%d・形状%d/逆背景%d/量支持%d、入力前後不変\n", bindings, shape, background, quantity)
	return nil
}

// main は計画を必須にし、保存Pure Bの診断だけを実行します。
//
// 引数: --plan/--out(string)は固定計画と既存上書禁止の結果です。
// 返り値: ありません。異常は終了1です。
func main() {
	planPath := flag.String("plan", "", "事前固定した計画JSON")
	out := flag.String("out", "", "新規の結果JSON")
	flag.Parse()
	if *planPath == "" || *out == "" {
		fmt.Fprintln(os.Stderr, "--plan と --out が必要です")
		os.Exit(2)
	}
	if err := run(*planPath, *out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
