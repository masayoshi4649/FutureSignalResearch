package far80

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// seedsTestSession は一つの一時根へ自己完結した人工場を追加します。
//
// 引数: tは*testing.T、rootとidとcontractはstring、denseとunknownはboolです。
// 返り値: InputSessionは6個の人工gzip/CSV指紋です。本物入力を読みません。
func seedsTestSession(t *testing.T, root, id, contract string, dense, unknown bool) InputSession {
	t.Helper()
	session, err := sessionClock(id)
	if err != nil {
		t.Fatal(err)
	}
	input := InputSession{ID: id, Contract: contract, Files: map[string]InputFile{}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		code := contract
		if ref == "TOPIX" {
			code = "TP" + strings.TrimPrefix(contract, "NK")
		}
		times := []float64{session.Start, session.Start + 179, session.Start + 180, session.Start + 899}
		if dense {
			times = nil
			for at := session.Start; at < session.End; at += 60 {
				times = append(times, at)
			}
			times = append(times, session.End-1)
		}
		rows := make([]map[string]any, 0, len(times)+3)
		for i, at := range times {
			price := 1000 + .03*float64(i) + 5*math.Sin(float64(i)/7)
			if ref == "TOPIX" {
				at += .25
				price = 4000 + float64(i)/100
			}
			row := replayTestRaw(at, price, code)
			if unknown && i == 2 && ref == "NK225" {
				row["CurrentPrice"] = nil
			}
			if dense && i == 3 && ref == "NK225" {
				row["Buy1"] = map[string]float64{"Price": price + 2, "Qty": 10}
			}
			rows = append(rows, row)
			if i == 1 {
				rows = append(rows, replayTestRaw(at, price+1, code))
			}
		}
		name := id + "_" + ref + ".jsonl.gz"
		input.Files[ref+"_book"] = replayTestGzip(t, root, name, rows)
		for _, interval := range []int{60, 300} {
			name := fmt.Sprintf("%s_%s_%d.csv", id, ref, interval)
			input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)] = replayTestCSV(t, root, name, nil)
		}
	}
	return input
}

// seedsTestManifest は公開worker検査用の人工固定台帳を作ります。
//
// 引数: tは*testing.T、rootはstringの一時根、inputsは[]InputSessionです。
// 返り値: InputManifestは人工純コード指紋も持つ台帳です。
func seedsTestManifest(t *testing.T, root string, inputs []InputSession) InputManifest {
	t.Helper()
	name := "人工純コード.txt"
	if err := os.WriteFile(filepath.Join(root, name), []byte("人工の指紋検査専用。実アプリではない"), 0600); err != nil {
		t.Fatal(err)
	}
	pin := replayTestPin(t, root, name)
	return InputManifest{Root: root, Sessions: inputs, StrategyRoot: root, StrategySHA256: map[string]string{name: pin.SHA256}}
}

// seedsTestEqual は型と全非公開数値を含めて人工値を比較します。
//
// 引数: tは*testing.T、nameはstring、actualとexpectedはanyの値です。
// 返り値: なし。JSONが隠す非公開Bankも比較します。
func seedsTestEqual(t *testing.T, name string, actual, expected any) {
	t.Helper()
	if !reflect.DeepEqual(actual, expected) {
		t.Fatalf("人工seed不一致:%s", name)
	}
}

// seedsTestSequential は限月切替だけをリセットする逐次Replayの独立対照です。
//
// 引数: tは*testing.T、mはInputManifest、delayはfloat64です。
// 返り値: map[string]ReplayResultとmap[string]TechnicalBankは全場結果と開始前の逐次種です。
func seedsTestSequential(t *testing.T, m InputManifest, delay float64) (map[string]ReplayResult, map[string]TechnicalBank) {
	t.Helper()
	bank := NewTechnicalBank()
	contract := ""
	results := map[string]ReplayResult{}
	before := map[string]TechnicalBank{}
	for _, input := range m.Sessions {
		if input.Contract != contract {
			bank = NewTechnicalBank()
			contract = input.Contract
		}
		before[input.ID] = *bank
		result, err := Replay(m.Root, input, bank, delay)
		if err != nil {
			t.Fatal(err)
		}
		results[input.ID] = result
	}
	return results, before
}

// ----------------------------------------

// TestSeedsSequentialAndEightWorkers は逐次と事前種と8workerの全文一致を確認します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。同限月carry・契約切替・0/1秒を人工3場で通します。
func TestSeedsSequentialAndEightWorkers(t *testing.T) {
	root := t.TempDir()
	inputs := []InputSession{
		seedsTestSession(t, root, "2026-11-06_Day", "NK202612", true, false),
		seedsTestSession(t, root, "2026-11-06_Night", "NK202612", true, true),
		seedsTestSession(t, root, "2026-11-09_Day", "NK202703", true, false),
	}
	m := seedsTestManifest(t, root, inputs)
	seeds, err := PrepareTechnicalSeeds(m)
	if err != nil {
		t.Fatal(err)
	}
	if len(seeds) != 3 {
		t.Fatal("人工3場の種が不足")
	}
	warm := seeds[inputs[1].ID]
	if !warm.series3.ema21.known || !warm.series15.ema21.known || !warm.series3.atr.known {
		t.Fatal("同限月carry検査が未知のまま空疎")
	}
	seedsTestEqual(t, "契約切替は完全初期化", seeds[inputs[2].ID], *NewTechnicalBank())
	original := map[string]TechnicalBank{}
	for id, seed := range seeds {
		original[id] = seed
		if seed.beginError != nil {
			t.Fatal("正常種に可変errorが存在")
		}
	}
	expected := map[float64]map[string]ReplayResult{}
	for _, delay := range []float64{0, 1} {
		sequential, before := seedsTestSequential(t, m, delay)
		expected[delay] = sequential
		for _, input := range inputs {
			seedsTestEqual(t, "開始前全Bank:"+input.ID, seeds[input.ID], before[input.ID])
			copy := seeds[input.ID]
			got, err := Replay(root, input, &copy, delay)
			if err != nil {
				t.Fatal(err)
			}
			seedsTestEqual(t, fmt.Sprintf("全出力:%s/delay%.0f", input.ID, delay), got, sequential[input.ID])
		}
	}
	seedsTestEqual(t, "二遅延の逐次技法種が同値", original, seeds)
	changed := seeds[inputs[1].ID]
	changed.series3.ema8.value += 777
	changed.three.count++
	seedsTestEqual(t, "種の値コピーは元mapへ波及しない", seeds, original)
	out := filepath.Join(root, "8worker出力")
	var progress bytes.Buffer
	if err = RunBatch(m, out, 8, &progress); err != nil {
		t.Fatal(err)
	}
	if strings.Count(progress.String(), "未解決") != 18 {
		t.Fatal("人工6jobの3案進捗が不足")
	}
	for _, delay := range []float64{0, 1} {
		label := "主66場"
		if delay == 1 {
			label = "追加1秒66場"
		}
		for _, input := range inputs {
			data, err := os.ReadFile(filepath.Join(out, label, input.ID+".json"))
			if err != nil {
				t.Fatal(err)
			}
			want, err := json.Marshal(expected[delay][input.ID])
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(data, want) {
				t.Fatalf("8worker JSONが逐次とbyte不一致:%s/%s", label, input.ID)
			}
		}
	}
	for _, input := range inputs {
		for _, file := range input.Files {
			if _, err = verifyInput(root, file); err != nil {
				t.Fatal("人工が原入力を変更")
			}
		}
	}
	t.Log("人工3場×2遅延: 逐次全Bank/全ReplayResult/8worker全JSON一致、同限月carry・契約切替・不明Lastを確認")
}

// TestSeedsUnknownLastAndEOFTimers は欠Lastと早いEOFでも後続種を省略しないことを確認します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。場末まで価格を創作せずtimerだけを進めます。
func TestSeedsUnknownLastAndEOFTimers(t *testing.T) {
	root := t.TempDir()
	inputs := []InputSession{
		seedsTestSession(t, root, "2026-11-06_Day", "NK202612", false, true),
		seedsTestSession(t, root, "2026-11-06_Night", "NK202612", false, true),
		seedsTestSession(t, root, "2026-11-09_Day", "NK202612", false, false),
	}
	m := seedsTestManifest(t, root, inputs)
	seeds, err := PrepareTechnicalSeeds(m)
	if err != nil {
		t.Fatal(err)
	}
	for _, delay := range []float64{0, 1} {
		results, before := seedsTestSequential(t, m, delay)
		for _, input := range inputs {
			seedsTestEqual(t, "不明Last/EOFの全開始前Bank", seeds[input.ID], before[input.ID])
			copy := seeds[input.ID]
			got, err := Replay(root, input, &copy, delay)
			if err != nil {
				t.Fatal(err)
			}
			seedsTestEqual(t, "不明Last/EOFの全結果", got, results[input.ID])
			expected := 25
			if strings.HasSuffix(input.ID, "Night") {
				expected = 49
			}
			for _, mode := range []string{"F0", "P1", "T1"} {
				if len(got.Books[mode].Decisions) != expected {
					t.Fatal("EOF後の全timer定時が不足")
				}
			}
		}
	}
	for _, input := range inputs[1:] {
		seed := seeds[input.ID]
		prev := inputs[0]
		if input.ID == inputs[2].ID {
			prev = inputs[1]
		}
		clock, _ := sessionClock(prev.ID)
		if seed.frontier != clock.ForceClose || seed.View().TrendKnown || seed.View().ATRKnown {
			t.Fatal("EOF後の技法未知又は最終force時計が一致しない")
		}
	}
}

// TestSeedsBatchRejectsErrors は指紋不正と並列数不正を成功としないことを確認します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。失敗jobのJSONを保存せず、既存出力は変更しません。
func TestSeedsBatchRejectsErrors(t *testing.T) {
	root := t.TempDir()
	input := seedsTestSession(t, root, "2026-11-06_Day", "NK202612", false, false)
	m := seedsTestManifest(t, root, []InputSession{input})
	for _, workers := range []int{0, 17} {
		if err := RunBatch(m, filepath.Join(root, fmt.Sprintf("不正%d", workers)), workers, io.Discard); err == nil {
			t.Fatal("不正並列数を受理")
		}
	}
	file := input.Files["TOPIX_book"]
	file.SHA256 = strings.Repeat("0", 64)
	input.Files["TOPIX_book"] = file
	m.Sessions = []InputSession{input}
	out := filepath.Join(root, "失敗出力")
	if err := RunBatch(m, out, 8, io.Discard); err == nil {
		t.Fatal("Replayの異常を並列成功へ変換")
	}
	for _, label := range []string{"主66場", "追加1秒66場"} {
		if _, err := os.Stat(filepath.Join(out, label, input.ID+".json")); !os.IsNotExist(err) {
			t.Fatal("失敗jobの結果JSONを成功保存")
		}
	}
	if err := RunBatch(m, out, 8, io.Discard); err == nil {
		t.Fatal("既存出力へ再起動した")
	}
	input.Files["NK225_book"] = file
	m.Sessions = []InputSession{input}
	if _, err := PrepareTechnicalSeeds(m); err == nil {
		t.Fatal("事前種でNK指紋の差を無視")
	}
}
