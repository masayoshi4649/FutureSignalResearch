package grossport100

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	prior99 "github.com/masayoshi4649/SessionTradeExecuter/entryport99"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	finance "github.com/masayoshi4649/SessionTradeExecuter/minigrossguard100"
)

// repository100 はこの人工コードの2階層上を返します。
//
// 引数: ありません。
// 返り値: stringは固定人工の所在だけに使うrootです。
func repository100() string {
	_, p, _, _ := runtime.Caller(0)
	return filepath.Dir(filepath.Dir(filepath.Dir(p)))
}

// clone100 は人工のslice/map/pointerを独立に複写します。
//
// 引数: v(T)はJSON型です。
// 返り値: Tは元と共有しない同値です。
func clone100[T any](v T) T {
	b, e := json.Marshal(v)
	if e != nil {
		panic(e)
	}
	var out T
	if e = json.Unmarshal(b, &out); e != nil {
		panic(e)
	}
	return out
}

// fixture100 は停止98の手製Tapeだけを明示名で読みます。
//
// 引数: t(*testing.T)、side(int)、mode(string)は鏡像/人工名です。
// 返り値: tape.TapeはSource/ATR/Chart手製の接続人工です。市場本文は読みません。
func fixture100(t *testing.T, side int, mode string) tape.Tape {
	t.Helper()
	name := "Source部分"
	if mode == "HG戻り" {
		name = "幅と次板悪化"
	}
	p := filepath.Join(repository100(), "work", "98再生接続案", "人工", "停止版", fmt.Sprintf("方向%d_%s.json", side, name))
	body, e := os.ReadFile(p)
	if e != nil {
		t.Fatal(e)
	}
	var x struct {
		Tape tape.Tape `json:"tape"`
	}
	if e = json.Unmarshal(body, &x); e != nil {
		t.Fatal(e)
	}
	if !strings.HasPrefix(x.Tape.Scope, "固定98Go型人工") || len(x.Tape.Provenance) != 0 {
		t.Fatal("手製入力だけ")
	}
	x.Tape.Scope = "固定100Go型人工。旧停止98の手製Source/Chart/ATRを再用する公開API接続。市場/Source生成/チャート形成は未検証。"
	if mode == "HG戻り" {
		entry := x.Tape.Events[0].Quote.Ask
		if side < 0 {
			entry = x.Tape.Events[0].Quote.Bid
		}
		gains := []float64{10, 0, -10, 30, 0}
		for j, g := range gains {
			ev := &x.Tape.Events[j+5]
			if ev.Kind != "quote" || len(ev.NonEmpty) != 0 {
				t.Fatal("源通知を変更しない人工行が必要")
			}
			price := entry + float64(side)*g
			if side > 0 {
				ev.Quote.Bid, ev.Quote.Ask = price, price+10
			} else {
				ev.Quote.Bid, ev.Quote.Ask = price-10, price
			}
			ev.Quote.Last = (ev.Quote.Bid + ev.Quote.Ask) / 2
		}
		x.Tape.Scope += " HG粗順行/戻り人工のScalarだけ変更。新規/ForceのSource約定原行は変更0。"
	}
	// Force出典は元人工の直前Source物理行を厳密に保持する。
	var line int64
	var last actual.QuoteStamp
	for _, ev := range x.Tape.Events {
		if ev.Kind == "quote" {
			line = ev.Quote.SourceLine
			q := ev.Quote
			last = actual.QuoteStamp{Time: q.Time, Index: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask, QuoteOK: q.QuoteOK}
		}
		if ev.Kind == "force" {
			for _, b := range ev.NonEmpty {
				if b.Delta.SourceLine != line {
					t.Fatal("Forceの直前原行出典差")
				}
				for _, record := range b.Delta.Signals {
					if record.Quote != last {
						t.Fatal("Force保存気配と直前Scalarの全文差")
					}
				}
			}
		}
	}
	return x.Tape
}

// TestRuntime100 は少数の鏡像人工で新12と旧99H0四の全時点を比較します。
//
// 引数: t(*testing.T)は試験器です。GROSSPORT100_EXPORT_DIRが明示された時だけ新規保存します。
// 返り値: ありません。Native/Raw/新日/金融市場運転は行いません。
func TestRuntime100(t *testing.T) {
	output := os.Getenv("GROSSPORT100_EXPORT_DIR")
	if output != "" {
		if e := os.Mkdir(output, 0755); e != nil {
			t.Fatal("新規出力だけ", e)
		}
	}
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"HG戻り", "Source部分"} {
			input := fixture100(t, side, mode)
			before, _ := json.Marshal(input)
			observed, _, e := ReplayProtection(input, true)
			if e != nil {
				t.Fatal(e)
			}
			production, records, e := ReplayProtection(input, false)
			if e != nil {
				t.Fatal(e)
			}
			a, _ := json.Marshal(observed.Books)
			b, _ := json.Marshal(production.Books)
			if !bytes.Equal(a, b) || len(production.StateSHA256) != 0 {
				t.Fatal("全時点とproductionの全12差")
			}
			legacyRecords := []port.GateAssessmentRecord{}
			configs := []port.Config{}
			for _, cfg := range Configurations() {
				if cfg.Harvest == "H0" {
					configs = append(configs, cfg)
				}
			}
			old, e := port.Run(input, prior99.EntryFactory{Records: &legacyRecords}, configs)
			if e != nil {
				t.Fatal(e)
			}
			matched, e := CompareH099(production.Books, old.Books)
			if e != nil || len(matched) != 4 {
				t.Fatal("旧99H0四の全値", e)
			}
			for _, key := range matched {
				if observed.StateSHA256[key] != old.StateSHA256[key] {
					t.Fatal("H0旧99全時点差")
				}
			}
			guards := 0
			for key, body := range production.Books {
				var r finance.ActualResult
				if e = json.Unmarshal(body, &r); e != nil {
					t.Fatal(e)
				}
				if r.Key != key || !r.Complete || !r.Finished || r.Failure != "" || r.Config.GatePolicy != "E3S" || r.Config.RiskPolicy != "" || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 || len(r.Positions) == 0 {
					t.Fatal("本名12の非0完結差", key)
				}
				if r.Config.HarvestPolicy == "HG" {
					for _, p := range r.Positions {
						if p.GrossGuard != nil {
							guards++
						}
					}
				}
			}
			if mode == "HG戻り" && guards != 2 {
				t.Fatal("HG費用5/両遅延だけで利益前ガードを観測", guards)
			}
			after, _ := json.Marshal(input)
			if !bytes.Equal(before, after) {
				t.Fatal("Tape入力副作用")
			}
			if output != "" {
				contexts := []actual.TechnicalGateInput{}
				for _, ev := range input.Events {
					if ev.Kind == "grid" {
						contexts = append(contexts, *ev.Context)
					}
				}
				value := map[string]any{"scope": input.Scope, "tape": input, "output": map[string]any{"trial": 100, "version": 1, "session": input.Session.ID, "books": production.Books, "chart_grids": contexts, "gate_assessments": records, "source_reexecuted": false, "charts_recomputed": false, "actual_run_complete": true, "h0_99_match": map[string]any{"all": true, "books": 4, "keys": matched, "excluded": []string{}, "scope": "手製Tape同一入力の旧99公開API四。正式市場99基準ではない。"}}, "baseline99_api": map[string]any{"books": old.Books, "scope": "旧99公開API人工・正式Nativeは未読"}, "all_snapshot_h0_equal": true, "production_books_equal": true}
				body, _ := json.MarshalIndent(value, "", "  ")
				path := filepath.Join(output, fmt.Sprintf("方向%d_%s.json", side, mode))
				if e = os.WriteFile(path, append(body, '\n'), 0644); e != nil {
					t.Fatal(e)
				}
			}
			t.Logf("方向%d/%s 新12非0・旧H0四/全時点・Force出典・入力不変", side, mode)
		}
	}
}

// TestConversionAndGuards100 は本名順序/全field/配列と未固定CLIの早期拒否を検査します。
//
// 引数: t(*testing.T)は人工だけを使う試験器です。
// 返り値: ありません。存在しないTape/index/Proofを開く前の拒否を要求します。
func TestConversionAndGuards100(t *testing.T) {
	keys := Keys()
	if len(keys) != 12 || keys[0] != "E3S_B5Q_P0_C0_D0" || keys[4] != "H0_E3S_B5Q_P0_C0_D0" || keys[8] != "HG_E3S_B5Q_P0_C0_D0" {
		t.Fatal("canonical12順")
	}
	if ConvertBatches(nil) != nil || ConvertBatches([]actual.NativeBatch{}) == nil {
		t.Fatal("nilと空配列")
	}
	v := fixture100(t, 1, "HG戻り")
	for _, ev := range v.Events {
		a, _ := json.Marshal(ev.NonEmpty)
		b, _ := json.Marshal(ConvertBatches(ev.NonEmpty))
		if !bytes.Equal(a, b) {
			t.Fatal("Source全field変換")
		}
	}
	left, _ := canonical(json.RawMessage(`{"values":null}`))
	right, _ := canonical(json.RawMessage(`{"values":[]}`))
	if bytes.Equal(left, right) {
		t.Fatal("nil/空を同一化")
	}
	temp := t.TempDir()
	condition := filepath.Join(temp, "未固定100.json")
	if e := os.WriteFile(condition, []byte(`{"試行":100,"市場損益を開く前の固定":false}`), 0600); e != nil {
		t.Fatal(e)
	}
	err := RunBatch(BatchArguments{Index: "開くことが禁止のindex", Condition: condition, Proof99: "開くことが禁止の99", Proof98: "開くことが禁止の98", Proof97: "開くことが禁止の97", Proof96: "開くことが禁止の96", Out: filepath.Join(temp, "出力"), Stage: "first2", Workers: 1})
	if err == nil || !strings.Contains(err.Error(), "固定100条件") {
		t.Fatal("Tape/Proofを開く前に未固定条件を拒否しない", err)
	}
	if _, e := os.Stat(filepath.Join(temp, "出力")); !os.IsNotExist(e) {
		t.Fatal("拒否時に出力した")
	}
	validHeader := map[string]any{"試行": 100, "市場損益を開く前の固定": true, "固定99完了SHA256": Fixed99CompletionSHA256, "固定98完了SHA256": prior99.Fixed98CompletionSHA256, "固定97完了SHA256": "0d7111c41c4c25140be69fe8b06d0118496ddd6de3bc9ac7467ec2f01f6aef79", "固定96完了SHA256": tape.SelectedCompletionSHA256, "金融停止SHA256": strings.Repeat("0", 64), "全12Key": Keys(), "コードSHA256": map[string]string{"開くことが禁止のcode": strings.Repeat("a", 64)}}
	encoded, _ := json.Marshal(validHeader)
	if writeErr := os.WriteFile(condition, encoded, 0600); writeErr != nil {
		t.Fatal(writeErr)
	}
	err = RunBatch(BatchArguments{Index: "禁止index", Condition: condition, Proof99: "禁止99", Proof98: "禁止98", Proof97: "禁止97", Proof96: "禁止96", Out: filepath.Join(temp, "出力"), Stage: "first2", Workers: 1})
	if err == nil || !strings.Contains(err.Error(), "金融停止SHA") {
		t.Fatal("金融停止差をTape前に拒否しない", err)
	}
	result, _, e := ReplayProtection(v, false)
	if e != nil {
		t.Fatal(e)
	}
	prior := map[string]json.RawMessage{}
	for _, k := range Keys() {
		if strings.HasPrefix(k, "H0_") {
			prior[k] = result.Books[k]
		}
	}
	if _, e = CompareH099(result.Books, prior); e != nil {
		t.Fatal(e)
	}
	k := "H0_E3S_B5Q_P0_C0_D0"
	var broken map[string]any
	if e = json.Unmarshal(prior[k], &broken); e != nil {
		t.Fatal(e)
	}
	broken["余分なfield"] = true
	prior[k], _ = json.Marshal(broken)
	if _, e = CompareH099(result.Books, prior); e == nil {
		t.Fatal("全field差を見逃し")
	}
	_, records, e := ReplayProtection(v, false)
	if e != nil || len(records) != 12 {
		t.Fatal("E3S全12の現在候補", e)
	}
	for _, mode := range []string{"旧名", "check改名", "ordinal", "重複"} {
		broken := clone100(records)
		switch mode {
		case "旧名":
			broken[0].Assessment.Decision.Policy = "AB"
		case "check改名":
			broken[0].Assessment.Checks[0].ID = "架空check"
		case "ordinal":
			broken[0].Candidate.Ordinal++
		case "重複":
			broken = append(broken, broken[0])
		}
		if ValidateGateRecords(v, result, broken) == nil {
			t.Fatal("保存現在check破損を拒否しない", mode)
		}
	}
}
