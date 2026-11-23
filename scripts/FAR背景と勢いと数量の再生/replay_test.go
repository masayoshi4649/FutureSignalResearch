package entryport99

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
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	entry "github.com/masayoshi4649/SessionTradeExecuter/minientry99"
	prior98 "github.com/masayoshi4649/SessionTradeExecuter/riskport98"
)

// clone は人工のpointer/slice/mapを独立に複写します。
//
// 引数: value(T)は公開型です。
// 返り値: TはJSONで全値を保持した独立値です。
func clone[T any](value T) T {
	body, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	var out T
	if err = json.Unmarshal(body, &out); err != nil {
		panic(err)
	}
	return out
}

// root99 は手製入力だけを参照するrepositoryルートを返します。
//
// 引数: ありません。
// 返り値: stringは当試験の2段上です。市場を探索しません。
func root99() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Dir(filepath.Dir(filepath.Dir(file)))
}

// fixture99 は停止98の人工Tape値だけを読み込みます。
//
// 引数: t(*testing.T)、name(string)は試験器と停止人工名です。
// 返り値: tape.Tapeは同eventsの人工入力です。市場98成果物は読みません。
func fixture99(t *testing.T, name string) tape.Tape {
	t.Helper()
	path := filepath.Join(root99(), "work", "98再生接続案", "人工", "停止版", name)
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var input struct {
		Tape tape.Tape `json:"tape"`
	}
	if err = json.Unmarshal(body, &input); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(input.Tape.Scope, "固定98Go型人工") || len(input.Tape.Provenance) != 0 {
		t.Fatal("手製Tape以外を読めません")
	}
	input.Tape.Scope = "固定99Go型人工。停止98の手製Source/ATR/Chart文脈を再用し、新金融/純E3への配送だけを確認。元Source/チャート形成/市場は未検査。"
	return input.Tape
}

// boundaryInput99 は少数API境界だけの技法値を手製で変更します。
//
// 引数: input(tape.Tape)、mode(string)は独立した人工入力と未知/否定/スパイクです。
// 返り値: tape.Tapeは同じScalar/Source/時計を保持する境界人工です。
func boundaryInput99(input tape.Tape, mode string) tape.Tape {
	input = clone(input)
	for i := range input.Events {
		e := &input.Events[i]
		if e.Kind != "grid" {
			continue
		}
		v := &e.Context.Chart.Chart.Technical
		side := 1
		if e.Context.Current.Buy.OFI30 < 0 {
			side = -1
		}
		switch mode {
		case "必要未知":
			v.ExitKnown = false
			v.SpikeKnown = false
		case "既知否定優先":
			v.ExitKnown = false
			v.SpikeKnown = false
			v.EMA8_3 = v.EMA21_3 - float64(side)*10
		case "同時スパイク":
			v.TR3 = 41
			v.ATR3 = 20
			v.PreviousATR3 = 20
			if side > 0 {
				v.RSI3, v.PreviousRSI3 = 90, 74
			} else {
				v.RSI3, v.PreviousRSI3 = 10, 26
			}
		default:
			panic("人工境界名が不正")
		}
		e.Context.Recent3[len(e.Context.Recent3)-1].Chart = e.Context.Chart.Chart
	}
	input.Scope += " 追加API境界=" + mode + "。価格/Source/費用は変更0。"
	return input
}

// equal99 は全JSON値の比較を行います。
//
// 引数: t(*testing.T)、a/b(any)、label(string)は試験器・値・説明です。
// 返り値: ありません。省略fieldや余分fieldも差として拒否します。
func equal99(t *testing.T, a, b any, label string) {
	t.Helper()
	x, err := json.Marshal(a)
	if err != nil {
		t.Fatal(err)
	}
	y, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(x, y) {
		t.Fatal(label, "全JSON不一致")
	}
}

// runCase99 は同じ人工Tapeの全時点/productionと旧空Gateを照合します。
//
// 引数: t(*testing.T)、input(tape.Tape)、name(string)は試験器・手製入力・保存名です。
// 返り値: int/intは実新規のある口座数と新純式callback数です。
func runCase99(t *testing.T, input tape.Tape, name string) (int, int) {
	t.Helper()
	before, _ := json.Marshal(input)
	observed, _, err := ReplayEntry(input, true)
	if err != nil {
		t.Fatal(err)
	}
	production, records, err := ReplayEntry(input, false)
	if err != nil {
		t.Fatal(err)
	}
	equal99(t, observed.Books, production.Books, "全時点器とproduction最終12")
	equal99(t, observed.GateCallbacks, production.GateCallbacks, "production callback数")
	if len(production.StateSHA256) != 0 {
		t.Fatal("productionに全原行Snapshot連鎖")
	}
	baselineRecords := []port.GateAssessmentRecord{}
	configs := []port.Config{}
	for _, c := range Configurations() {
		if c.Gate == "" {
			configs = append(configs, c)
		}
	}
	baseline, err := port.Run(input, prior98.RiskFactory{Policy: "", Records: &baselineRecords}, configs)
	if err != nil {
		t.Fatal(err)
	}
	matched, err := CompareEmptyGate98(production.Books, baseline.Books)
	if err != nil || len(matched) != 4 {
		t.Fatal("旧空Gate四対照", err)
	}
	for _, record := range records {
		d := record.Assessment.Decision
		switch {
		case strings.Contains(name, "API必要未知"):
			if d.Known || d.Allowed {
				t.Fatal("人工の必要未知を採用した", d)
			}
		case strings.Contains(name, "API既知否定優先"):
			if !d.Known || d.Allowed {
				t.Fatal("人工の既知否定を優先しない", d)
			}
		case strings.Contains(name, "API同時スパイク"):
			if !d.Known || d.Allowed != (d.Policy == "E3") {
				t.Fatal("E3Sだけのスパイク拒否を維持しない", d)
			}
		}
	}
	for _, key := range matched {
		equal99(t, observed.Books[key], baseline.Books[key], "空Gate旧98最終")
		if observed.StateSHA256[key] != baseline.StateSHA256[key] {
			t.Fatal("空Gate旧98全時点指紋差", key)
		}
	}
	contexts := []any{}
	forces, nonzero := 0, 0
	for _, e := range input.Events {
		if e.Kind == "force" {
			forces++
		}
		if e.Kind == "grid" {
			contexts = append(contexts, *e.Context)
		}
	}
	if forces != 1 {
		t.Fatal("明示Source Forceが必要")
	}
	for key, body := range production.Books {
		var b entry.ActualResult
		if err = json.Unmarshal(body, &b); err != nil {
			t.Fatal(err)
		}
		if !b.Complete || !b.Finished || b.Config.RiskPolicy != "" || b.Config.HarvestPolicy != "H0" || b.Totals.OpenBuy != 0 || b.Totals.OpenSell != 0 || b.Totals.PendingBuy != 0 || b.Totals.PendingSell != 0 {
			t.Fatal("12口座の設定/完結", key)
		}
		if len(b.Positions) > 0 {
			nonzero++
		}
		if strings.Contains(key, "E3S_") {
			if b.Config.GatePolicy != "E3S" {
				t.Fatal("名偽装")
			}
		} else if strings.Contains(key, "E3_") {
			if b.Config.GatePolicy != "E3" {
				t.Fatal("名偽装")
			}
		} else if b.Config.GatePolicy != "" {
			t.Fatal("G0名偽装")
		}
	}
	after, _ := json.Marshal(input)
	if !bytes.Equal(before, after) {
		t.Fatal("Tape書換え")
	}
	if out := os.Getenv("ENTRY99_EXPORT"); out != "" {
		if err = os.MkdirAll(out, 0755); err != nil {
			t.Fatal(err)
		}
		proof := map[string]any{"scope": input.Scope, "tape": input, "output": map[string]any{"trial": 99, "version": 1, "session": input.Session.ID, "books": production.Books, "chart_grids": contexts, "gate_assessments": records, "source_reexecuted": false, "charts_recomputed": false, "empty_gate_98_match": map[string]any{"all": true, "books": 4, "keys": matched, "excluded": []string{}, "scope": "同じ人工Tapeの旧98公開API四会計。正式市場基準ではない。"}, "actual_run_complete": true}, "baseline98_api": map[string]any{"books": baseline.Books, "scope": "手製API限定。正式98Nativeを補完しない。"}, "empty_gate_all_snapshots_equal": true, "production_full_books_equal": true, "callbacks": production.GateCallbacks}
		body, err := json.MarshalIndent(proof, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(out, name), append(body, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	return nonzero, len(records)
}

// TestEntryTapeProduction99 は停止人工14と少数境界6を本名12口座へ接続します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。元Scalar/Source/時計を変えず金融/純式/Force/旧対照を検証します。
func TestEntryTapeProduction99(t *testing.T) {
	scenes, nonzero, callbacks := 0, 0, 0
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"幅と次板悪化", "非緩和", "未知後既知", "Source部分", "Source全予約", "利益移行", "risk要求後正益"} {
			name := fmt.Sprintf("方向%d_%s.json", side, mode)
			n, c := runCase99(t, fixture99(t, name), name)
			scenes++
			nonzero += n
			callbacks += c
		}
	}
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"必要未知", "既知否定優先", "同時スパイク"} {
			input := fixture99(t, fmt.Sprintf("方向%d_幅と次板悪化.json", side))
			n, c := runCase99(t, boundaryInput99(input, mode), fmt.Sprintf("方向%d_API%s.json", side, mode))
			scenes++
			nonzero += n
			callbacks += c
		}
	}
	if scenes != 20 || callbacks != 160 || nonzero == 0 {
		t.Fatal("人工接続の必要経路不足", scenes, nonzero, callbacks)
	}
	t.Logf("人工=%d/口座=%d/非0=%d/全時点空Gate=%d/全純式=%d/Force=%d", scenes, scenes*12, nonzero, scenes*4, callbacks, scenes)
}

// TestEntryRecordBoundary99 は本名・集合・時計・全checkの破損を拒否します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。新政策を旧ABで受理させません。
func TestEntryRecordBoundary99(t *testing.T) {
	input := fixture99(t, "方向1_幅と次板悪化.json")
	out, records, err := ReplayEntry(input, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 8 {
		t.Fatal("E3/E3S八候補")
	}
	for _, mode := range []string{"重複", "旧名", "時刻", "ordinal", "check欠落", "callback欠落", "callback候補外"} {
		broken := clone(records)
		result := clone(out)
		switch mode {
		case "重複":
			broken = append(broken, broken[0])
		case "旧名":
			broken[0].Assessment.Decision.Policy = "AB"
		case "時刻":
			broken[0].Candidate.At++
		case "ordinal":
			broken[0].Candidate.Ordinal++
		case "check欠落":
			broken[0].Assessment.Checks = broken[0].Assessment.Checks[:1]
		case "callback欠落":
			result.GateCallbacks[broken[0].Key]++
		case "callback候補外":
			delete(result.GateCallbacks, "H0_B5Q_P0_C0_D0")
			result.GateCallbacks["旧AB偽装"] = 0
		}
		if ValidateGateRecords(input, result, broken) == nil {
			t.Fatal("純式保存破損未拒否", mode)
		}
	}
}

// TestEmptyGateAndMarketBoundary99 は正式98のmetadata結合と未固定99条件を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。旧四対照は人工、実98は完了metadataだけ読みNativeを開きません。
func TestEmptyGateAndMarketBoundary99(t *testing.T) {
	if Fixed98CompletionSHA256 != "2ee9417d0cd1f8bef107712789d26e3f72c0f95a933e60b31bb3f11784ca0dfe" {
		t.Fatal("正式98完了SHA結合差")
	}
	proof98 := filepath.Join(root99(), "study", "00098_実建値からの利益前ATR追尾", "完了記録.json")
	catalog, err := Selected98Catalog(proof98)
	if err != nil || len(catalog) != 54 {
		t.Fatal("正式98許可metadata", err)
	}
	temp := t.TempDir()
	fakeProof := filepath.Join(temp, "不正98.json")
	if err = os.WriteFile(fakeProof, []byte("{}"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err = Selected98Catalog(fakeProof); err == nil {
		t.Fatal("98異指紋を許可")
	}
	if RunBatch(BatchArguments{}) == nil {
		t.Fatal("必須引数なしを許可")
	}
	indexPath := filepath.Join(temp, "index.json")
	idx := TapeIndex{Version: 1, Stage: "first2", Entries: []TapeEntry{{Session: "2026-09-21_Day", Path: "開くことが禁止のTapeDay", SHA256: strings.Repeat("a", 64)}, {Session: "2026-09-21_Night", Path: "開くことが禁止のTapeNight", SHA256: strings.Repeat("a", 64)}}}
	indexBody, _ := json.Marshal(idx)
	if err = os.WriteFile(indexPath, indexBody, 0644); err != nil {
		t.Fatal(err)
	}
	conditionPath := filepath.Join(temp, "未固定99条件.json")
	conditionBody, _ := json.Marshal(map[string]any{"試行": 99, "固定98完了SHA256": Fixed98CompletionSHA256, "固定97完了SHA256": "0d7111c41c4c25140be69fe8b06d0118496ddd6de3bc9ac7467ec2f01f6aef79", "固定96完了SHA256": "33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483", "市場損益を開く前の固定": false, "コードSHA256": map[string]string{}})
	if err = os.WriteFile(conditionPath, conditionBody, 0644); err != nil {
		t.Fatal(err)
	}
	args := BatchArguments{Index: indexPath, Condition: conditionPath, Proof98: proof98, Proof97: filepath.Join(root99(), "study", "00097_初回費用後利益の全量確定", "完了記録.json"), Proof96: filepath.Join(root99(), "study", "00096_5分枠の順行反転と現在数量", "完了記録.json"), Out: filepath.Join(temp, "生成禁止"), Stage: "first2", Workers: 1}
	if err = RunBatch(args); err == nil || !strings.Contains(err.Error(), "固定99条件") {
		t.Fatal("未固定99条件の前でTapeに進んだ", err)
	}
	if _, err = os.Stat(args.Out); !os.IsNotExist(err) {
		t.Fatal("未固定99条件で出力を作成")
	}
	for _, w := range []int{0, 9} {
		args.Workers = w
		if RunBatch(args) == nil {
			t.Fatal("worker範囲外")
		}
	}
	input := fixture99(t, "方向1_幅と次板悪化.json")
	current, _, err := ReplayEntry(input, false)
	if err != nil {
		t.Fatal(err)
	}
	previous := map[string]json.RawMessage{}
	for _, key := range Keys() {
		if strings.HasPrefix(key, "H0_B5Q_") {
			previous[key] = current.Books[key]
		}
	}
	keys, err := CompareEmptyGate98(current.Books, previous)
	if err != nil || len(keys) != 4 {
		t.Fatal("四比較のAPI正常", err)
	}
	for _, mode := range []string{"基準欠落", "半円", "新tag", "旧AB偽装"} {
		before := clone(previous)
		next := clone(current.Books)
		key := keys[0]
		switch mode {
		case "基準欠落":
			delete(before, key)
		case "半円", "新tag":
			var row map[string]any
			_ = json.Unmarshal(before[key], &row)
			if mode == "半円" {
				v := row["totals"].(map[string]any)
				v["net_yen"] = v["net_yen"].(float64) + .5
			} else {
				row["余分な成功"] = true
			}
			before[key], _ = json.Marshal(row)
		case "旧AB偽装":
			next["H0_AB_B5Q_P0_C0_D0"] = next[key]
			delete(next, key)
		}
		if _, err = CompareEmptyGate98(next, before); err == nil {
			t.Fatal("旧対照の全field破損を許可", mode)
		}
	}
}

// TestIndexScope99 は固定再用するstage集合検査の境界を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。人工文字列の集合だけを使い、Native/原板を開きません。
func TestIndexScope99(t *testing.T) {
	sha := strings.Repeat("a", 64)
	index := TapeIndex{Version: 1, Stage: "first2", Entries: []TapeEntry{{Session: "2026-09-21_Day", Path: "人工Day", SHA256: sha}, {Session: "2026-09-21_Night", Path: "人工Night", SHA256: sha}}}
	if err := port.ValidateIndex(index, "first2", nil); err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"重複", "追加", "不足", "stage", "SHA"} {
		b := clone(index)
		switch mode {
		case "重複":
			b.Entries[1].Session = b.Entries[0].Session
		case "追加":
			b.Entries = append(b.Entries, b.Entries[0])
		case "不足":
			b.Entries = b.Entries[:1]
		case "stage":
			b.Stage = "full54"
		case "SHA":
			b.Entries[0].SHA256 = "未固定"
		}
		if port.ValidateIndex(b, "first2", nil) == nil {
			t.Fatal("stage破損を許可", mode)
		}
	}
	full := TapeIndex{Version: 1, Stage: "full54", Entries: []TapeEntry{}}
	allowed := map[string]string{}
	for i := 0; i < 54; i++ {
		id := fmt.Sprintf("人工許可%02d", i)
		allowed[id] = sha
		full.Entries = append(full.Entries, TapeEntry{Session: id, Path: "人工のみ", SHA256: sha})
	}
	if err := port.ValidateIndex(full, "full54", allowed); err != nil {
		t.Fatal(err)
	}
	full.Entries[0].Session = "対象外"
	if port.ValidateIndex(full, "full54", allowed) == nil {
		t.Fatal("対象外を許可")
	}
}
