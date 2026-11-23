// 88人工入力helper派生元SHA256: b24c2f846c6789cf97530bdc38ce31b87132e831b723ee90c0957fe998c9c8ce
package far88

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

// input88Stamp は市場と無関係な人工Unix時計を保存形式へ写します。
//
// 引数: at(float64)は人工Unix秒です。
// 返り値: stringはRFC3339Nano時計です。
func input88Stamp(at float64) string {
	return time.Unix(0, int64(math.Round(at*1e9))).UTC().Format(time.RFC3339Nano)
}

// input88Raw は原板の形だけを持つ人工JSON行を作ります。
//
// 引数: at/last(float64)は人工時計/Last、code(string)は限月IDです。
// 返り値: map[string]anyは毎回独立した行で、実市場データではありません。
func input88Raw(at, last float64, code string) map[string]any {
	row := map[string]any{"Symbol": code, "CurrentPriceTime": input88Stamp(at), "CurrentPrice": last}
	bid := 10 * math.Floor((last-1e-9)/10)
	ask := 10 * math.Ceil((last+1e-9)/10)
	for i := 1; i <= 10; i++ {
		row[fmt.Sprintf("Buy%d", i)] = map[string]float64{"Price": bid - float64(i-1)*10, "Qty": 10}
		row[fmt.Sprintf("Sell%d", i)] = map[string]float64{"Price": ask + float64(i-1)*10, "Qty": 10}
	}
	return row
}

// input88Pin は人工ファイルの全byteを固定情報へまとめます。
//
// 引数: t(*testing.T)は検査、root/name(string)は人工一時領域と相対名です。
// 返り値: InputFileはサイズとSHA256を持つ人工指紋です。
func input88Pin(t *testing.T, root, name string) InputFile {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(data)
	return InputFile{Path: filepath.ToSlash(name), SHA256: hex.EncodeToString(digest[:]), Size: int64(len(data))}
}

// input88Gzip は人工行だけを新しい一時gzipへ保存します。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([]map[string]any)は人工行です。
// 返り値: InputFileは新しい人工gzipの指紋です。
func input88Gzip(t *testing.T, root, name string, rows []map[string]any) InputFile {
	t.Helper()
	f, err := os.Create(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	z := gzip.NewWriter(f)
	encoder := json.NewEncoder(z)
	for _, row := range rows {
		if err := encoder.Encode(row); err != nil {
			t.Fatal(err)
		}
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return input88Pin(t, root, name)
}

// input88CSV は確定足の形だけを持つ人工CSVを作ります。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([][]string)は人工足です。
// 返り値: InputFileは人工CSVの指紋です。
func input88CSV(t *testing.T, root, name string, rows [][]string) InputFile {
	t.Helper()
	f, err := os.Create(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	w := csv.NewWriter(f)
	if err := w.Write([]string{"time", "open", "high", "low", "close", "closed"}); err != nil {
		t.Fatal(err)
	}
	for _, row := range rows {
		if err := w.Write(row); err != nil {
			t.Fatal(err)
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return input88Pin(t, root, name)
}

// input88Fixture は二市場・6入力の自己完結した人工場を作ります。
//
// 引数: t(*testing.T)は検査、id(string)は場ID、times([]float64)は人工原行時計です。
// 返り値: stringは一時領域、InputSessionは全6人工指紋です。
func input88Fixture(t *testing.T, id string, times []float64) (string, InputSession) {
	t.Helper()
	root := t.TempDir()
	input := InputSession{ID: id, Contract: "NK202612", Files: map[string]InputFile{}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		code, price := "NK202612", 1000.0
		if ref == "TOPIX" {
			code, price = "TP202612", 4000
		}
		rows := []map[string]any{}
		for _, at := range times {
			rows = append(rows, input88Raw(at, price, code))
		}
		input.Files[ref+"_book"] = input88Gzip(t, root, ref+".jsonl.gz", rows)
		for _, interval := range []int{60, 300} {
			name := fmt.Sprintf("%s_%d.csv", ref, interval)
			input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)] = input88CSV(t, root, name, nil)
		}
	}
	return root, input
}

// input88MultiFixture は複数場の種引継ぎだけを検査する密な人工台帳を作ります。
//
// 引数: t(*testing.T)は検査器、mirror(bool)は価格・両気配を反転するかです。
// 返り値: InputManifestは3場の人工固定台帳です。
func input88MultiFixture(t *testing.T, mirror bool) InputManifest {
	t.Helper()
	root := t.TempDir()
	manifest := InputManifest{Root: root, StrategyRoot: root, StrategySHA256: map[string]string{}}
	source := filepath.Join(root, "人工純戦略.go")
	if e := os.WriteFile(source, []byte("実行しない人工指紋"), 0600); e != nil {
		t.Fatal(e)
	}
	digest := sha256.Sum256([]byte("実行しない人工指紋"))
	manifest.StrategySHA256["人工純戦略.go"] = hex.EncodeToString(digest[:])
	for scene, id := range []string{"2026-11-02_Day", "2026-11-02_Night", "2026-11-03_Day"} {
		session, e := sessionClock(id)
		if e != nil {
			t.Fatal(e)
		}
		contract := "NK202612"
		if scene == 2 {
			contract = "NK202703"
		}
		input := InputSession{ID: id, Contract: contract, Files: map[string]InputFile{}}
		dir := filepath.Join(root, id)
		if e = os.Mkdir(dir, 0700); e != nil {
			t.Fatal(e)
		}
		for _, reference := range []string{"TOPIX", "NK225"} {
			rows := []map[string]any{}
			for index, at := 0, session.Start+4; at < session.End; index, at = index+1, at+5 {
				wave := []float64{40, 30, 20, 10, 0, -10, -20, -30, -20, -10, 0, 10, 20, 30, 40, 50, 40, 30, 20, 10}
				price := 1000 + float64(index)/10 + wave[(index+15)%len(wave)]
				if reference == "TOPIX" {
					price = 4000 + float64(index)/10 + wave[(index+15)%len(wave)]
				}
				if mirror {
					price = 10000 - price
				}
				rows = append(rows, input88Raw(at, price, contract))
			}
			file := input88Gzip(t, dir, reference+".jsonl.gz", rows)
			file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
			input.Files[reference+"_book"] = file
			for _, interval := range []int{60, 300} {
				file = input88CSV(t, dir, fmt.Sprintf("%s_%d.csv", reference, interval), nil)
				file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
				input.Files[fmt.Sprintf("%s_candle_%d", reference, interval)] = file
			}
		}
		manifest.Sessions = append(manifest.Sessions, input)
	}
	return manifest
}

// TestReplay88LegacySFullAndSeed は旧87S/C0/全Source指紋と独立指標の同値を確認します。
//
// 引数: t(*testing.T)は3人工場/同限月carry/限月resetを使う検査器です。
// 返り値: ありません。市場原板又は実損益を新しく読みません。
func TestReplay88LegacySFullAndSeed(t *testing.T) {
	manifest := input88MultiFixture(t, false)
	seeds, err := far80.PrepareTechnicalSeeds(manifest)
	if err != nil {
		t.Fatal(err)
	}
	nonzero := 0
	for _, input := range manifest.Sessions {
		seed, oldSeed := seeds[input.ID], seeds[input.ID]
		got, err := Replay(manifest.Root, input, &seed)
		if err != nil {
			t.Fatal(input.ID, err)
		}
		old, err := far87.Replay(manifest.Root, input, &oldSeed)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(seed, oldSeed) || !reflect.DeepEqual(got.SourceEquivalence, SourceEquivalence(old.SourceEquivalence)) || !reflect.DeepEqual(got.ReferenceCounts, old.ReferenceCounts) {
			t.Fatal("旧seed/Source全frameが変更", input.ID)
		}
		for delay := 0; delay <= 1; delay++ {
			if !reflect.DeepEqual(got.Books[bookKey("S", delay)], old.Books[fmt.Sprintf("R0G1_D%d", delay)]) {
				t.Fatal("旧S金融全文差", input.ID, delay)
			}
			nonzero += got.Books[bookKey("S", delay)].Metrics.EntryQuantity
		}
		if len(got.GridDecisions) != len(old.GridDecisions) {
			t.Fatal("旧定時数変更")
		}
		for i, g := range got.GridDecisions {
			o := old.GridDecisions[i]
			if g.At != o.At || g.Window != o.Window || g.ClockAllowed != o.ClockAllowed || g.BlockReason != o.BlockReason || g.StructureAnchor != o.StructureAnchor || !reflect.DeepEqual(g.C0, o.C0) || !reflect.DeepEqual(g.Source, o.Source) || g.SourceLine != o.SourceLine {
				t.Fatal("旧C0/Source全値差", input.ID, i)
			}
		}
		a, _ := json.Marshal(got.SourceEvents)
		b, _ := json.Marshal(old.SourceEvents)
		if !bytes.Equal(a, b) {
			t.Fatal("Source通知列の変更")
		}
		eq := got.TechnicalEquivalence
		if eq.Mismatches != 0 || eq.ActualSHA256 != eq.EventSHA256 || eq.CoreCalls == 0 || eq.QuoteCalls == 0 {
			t.Fatal("独立Technical全呼出同値が欠落", eq)
		}
		for _, o := range got.EntryObservations {
			if o.Input.AfterEOF != (got.InputEnd == nil || o.Input.At > got.InputEnd.Time) {
				t.Fatal("EOFが統合終端へ未結合")
			}
		}
		t.Log(input.ID, "S実枚数", got.Books["S_D0"].Metrics.EntryQuantity, "E0/E1", got.Books["E0_D0"].Metrics.EntryQuantity, got.Books["E1_D0"].Metrics.EntryQuantity, "疎観測", len(got.EntryObservations), "旗原行", len(got.ProfitContexts))
	}
	if nonzero == 0 {
		t.Fatal("旧S非0約定がない人工")
	}
}

// TestReplay88GapLast0AndMergedEnd は疎原行/Last0/終端TOPIXと空列を旧時点へ結びます。
//
// 引数: t(*testing.T)は入力品質人工の検査器です。
// 返り値: ありません。入力指紋以外の実ファイルは開きません。
func TestReplay88GapLast0AndMergedEnd(t *testing.T) {
	session, _ := sessionClock("2026-11-02_Day")
	root, input := input88Fixture(t, session.ID, []float64{session.Start + 1, session.Start + 180, session.Start + 900, session.End - 1})
	rows := []map[string]any{input88Raw(session.Start+1, 1000, input.Contract), input88Raw(session.Start+180, 0, input.Contract), input88Raw(session.Start+901, 1001, input.Contract)}
	input.Files["NK225_book"] = input88Gzip(t, root, "NKgap.gz", rows)
	seed, oldSeed := far80.NewTechnicalBank(), far80.NewTechnicalBank()
	got, err := Replay(root, input, seed)
	if err != nil {
		t.Fatal(err)
	}
	old, err := far87.Replay(root, input, oldSeed)
	if err != nil {
		t.Fatal(err)
	}
	if got.InputEnd == nil || got.InputEnd.Reference != "TOPIX" || got.InputEnd.Time != session.End-1 {
		t.Fatal("TOPIX終端が落ちた", got.InputEnd)
	}
	if !reflect.DeepEqual(got.Books["S_D0"], old.Books["R0G1_D0"]) {
		t.Fatal("疎原行でSが変更")
	}
	found := false
	for _, e := range got.EntryObservations {
		if e.Input.Origin == "quote" && e.Input.Quote.Last == 0 {
			found = true
		}
	}
	if !found {
		t.Fatal("Last0失効の保存不足")
	}
}

// TestRunBatch88ParallelAndFailures は逐次/並列の保存全値と失敗境界を確認します。
//
// 引数: t(*testing.T)は3場人工と専用出力根です。
// 返り値: ありません。非0失敗は成功JSONとして保存せず、既存根は拒否します。
func TestRunBatch88ParallelAndFailures(t *testing.T) {
	manifest := input88MultiFixture(t, false)
	out := t.TempDir()
	sequential, parallel := filepath.Join(out, "逐次"), filepath.Join(out, "並列")
	if e := RunBatch(manifest, sequential, 1, nil); e != nil {
		t.Fatal(e)
	}
	if e := RunBatch(manifest, parallel, 3, nil); e != nil {
		t.Fatal(e)
	}
	for _, s := range manifest.Sessions {
		a, e := os.ReadFile(filepath.Join(sequential, s.ID+".json"))
		if e != nil {
			t.Fatal(e)
		}
		b, e := os.ReadFile(filepath.Join(parallel, s.ID+".json"))
		if e != nil {
			t.Fatal(e)
		}
		if !bytes.Equal(a, b) {
			t.Fatal("逐次並列の保存全値差", s.ID)
		}
	}
	if e := RunBatch(manifest, sequential, 1, nil); e == nil {
		t.Fatal("既存根の上書きを許可")
	}
	if e := RunBatch(manifest, filepath.Join(out, "不正並列"), 0, nil); e == nil {
		t.Fatal("並列0を成功化")
	}
	s := manifest.Sessions[0]
	f := s.Files["NK225_book"]
	f.SHA256 = fmt.Sprintf("%064d", 0)
	s.Files["NK225_book"] = f
	manifest.Sessions = manifest.Sessions[:1]
	failed := filepath.Join(out, "指紋不正")
	if e := RunBatch(manifest, failed, 1, nil); e == nil {
		t.Fatal("指紋不正を成功化")
	}
	if _, e := os.Stat(filepath.Join(failed, s.ID+".json")); !os.IsNotExist(e) {
		t.Fatal("失敗場を成功JSONに保存")
	}
}
