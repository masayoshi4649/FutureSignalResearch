// 90派生元: scripts/FAR利益床と収穫配分の比較/replay_test.go
// 90派生元SHA256: e9092ee599bbdf104a385d4e8b2770e21171958b8d12cad4860a488cfaff39e0
// 89派生元: scripts/FAR背景維持と押戻し再開/replay_test.go
// 89派生元SHA256: ab7949bc72858364b250b1a4c957cb1523c0f6e033caf5bc426350dc542d524e
// 88人工入力helper派生元SHA256: b24c2f846c6789cf97530bdc38ce31b87132e831b723ee90c0957fe998c9c8ce
package far90

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// input90Stamp は市場と無関係な人工Unix時計を保存形式へ写します。
//
// 引数: at(float64)は人工Unix秒です。
// 返り値: stringはRFC3339Nano時計です。
func input90Stamp(at float64) string {
	return time.Unix(0, int64(math.Round(at*1e9))).UTC().Format(time.RFC3339Nano)
}

// input90Raw は原板の形だけを持つ人工JSON行を作ります。
//
// 引数: at/last(float64)は人工時計/Last、code(string)は限月IDです。
// 返り値: map[string]anyは毎回独立した行で、実市場データではありません。
func input90Raw(at, last float64, code string) map[string]any {
	row := map[string]any{"Symbol": code, "CurrentPriceTime": input90Stamp(at), "CurrentPrice": last}
	bid := 10 * math.Floor((last-1e-9)/10)
	ask := 10 * math.Ceil((last+1e-9)/10)
	for i := 1; i <= 10; i++ {
		row[fmt.Sprintf("Buy%d", i)] = map[string]float64{"Price": bid - float64(i-1)*10, "Qty": 10}
		row[fmt.Sprintf("Sell%d", i)] = map[string]float64{"Price": ask + float64(i-1)*10, "Qty": 10}
	}
	return row
}

// input90Pin は人工ファイルの全byteを固定情報へまとめます。
//
// 引数: t(*testing.T)は検査、root/name(string)は人工一時領域と相対名です。
// 返り値: InputFileはサイズとSHA256を持つ人工指紋です。
func input90Pin(t *testing.T, root, name string) InputFile {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(data)
	return InputFile{Path: filepath.ToSlash(name), SHA256: hex.EncodeToString(digest[:]), Size: int64(len(data))}
}

// input90Gzip は人工行だけを新しい一時gzipへ保存します。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([]map[string]any)は人工行です。
// 返り値: InputFileは新しい人工gzipの指紋です。
func input90Gzip(t *testing.T, root, name string, rows []map[string]any) InputFile {
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
	return input90Pin(t, root, name)
}

// input90CSV は確定足の形だけを持つ人工CSVを作ります。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([][]string)は人工足です。
// 返り値: InputFileは人工CSVの指紋です。
func input90CSV(t *testing.T, root, name string, rows [][]string) InputFile {
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
	return input90Pin(t, root, name)
}

// input90Fixture は二市場・6入力の自己完結した人工場を作ります。
//
// 引数: t(*testing.T)は検査、id(string)は場ID、times([]float64)は人工原行時計です。
// 返り値: stringは一時領域、InputSessionは全6人工指紋です。
func input90Fixture(t *testing.T, id string, times []float64) (string, InputSession) {
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
			rows = append(rows, input90Raw(at, price, code))
		}
		input.Files[ref+"_book"] = input90Gzip(t, root, ref+".jsonl.gz", rows)
		for _, interval := range []int{60, 300} {
			name := fmt.Sprintf("%s_%d.csv", ref, interval)
			input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)] = input90CSV(t, root, name, nil)
		}
	}
	return root, input
}

// input90MultiFixture は複数場の種引継ぎだけを検査する密な人工台帳を作ります。
//
// 引数: t(*testing.T)は検査器、mirror(bool)は価格・両気配を反転するかです。
// 返り値: InputManifestは3場の人工固定台帳です。
func input90MultiFixture(t *testing.T, mirror bool) InputManifest {
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
				rows = append(rows, input90Raw(at, price, contract))
			}
			file := input90Gzip(t, dir, reference+".jsonl.gz", rows)
			file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
			input.Files[reference+"_book"] = file
			for _, interval := range []int{60, 300} {
				file = input90CSV(t, dir, fmt.Sprintf("%s_%d.csv", reference, interval), nil)
				file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
				input.Files[fmt.Sprintf("%s_candle_%d", reference, interval)] = file
			}
		}
		manifest.Sessions = append(manifest.Sessions, input)
	}
	return manifest
}

// equal90JSON は型名が異なる新旧の全保存fieldをbyteで比較します。
//
// 引数: t(*testing.T)、label(string)、actual/expected(any)は検査器・位置・新旧値です。
// 返り値: ありません。JSON型/field/値のどれかが異なれば停止します。
func equal90JSON(t *testing.T, label string, actual, expected any) {
	t.Helper()
	a, err := json.Marshal(actual)
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(expected)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(a, b) {
		t.Fatal("新旧全文JSON差", label)
	}
}

// profit90P0 は旧E1G1とP0の利益原行だけを同じ外名へ投影します。
//
// 引数: rows([]ProfitContext)、current(bool)は対象共有行と新側です。
// 返り値: map[int64]ProfitContextは同一原行でラベル以外を保持します。
func profit90P0(rows []ProfitContext, current bool) map[int64]ProfitContext {
	out := map[int64]ProfitContext{}
	for _, row := range rows {
		copy := row
		copy.ID = ""
		copy.TriggeredBy = []ProfitTrigger{}
		for _, trigger := range row.TriggeredBy {
			prefix := "E1G1_D"
			if current {
				prefix = "P0_D"
			}
			if !strings.HasPrefix(trigger.BookKey, prefix) {
				continue
			}
			if current {
				trigger.BookKey = strings.Replace(trigger.BookKey, "P0_D", "E1G1_D", 1)
			}
			copy.TriggeredBy = append(copy.TriggeredBy, trigger)
		}
		if len(copy.TriggeredBy) > 0 {
			out[row.Quote.Index] = copy
		}
	}
	return out
}

// compare90Legacy89 は旧89E1/G1の全金融と共有E1射影を比較します。
//
// 引数: t(*testing.T)、got(ReplayResult)、old(far89.ReplayResult)は新旧独立運転です。
// 返り値: ありません。新p sidecar以外の差は宣言した外policy射影に限ります。
func compare90Legacy89(t *testing.T, got ReplayResult, old far89.ReplayResult) {
	t.Helper()
	equal90JSON(t, "Source全frame", got.SourceEquivalence, old.SourceEquivalence)
	equal90JSON(t, "Source通知", got.SourceEvents, old.SourceEvents)
	equal90JSON(t, "Source観測数", got.ReferenceCounts, old.ReferenceCounts)
	equal90JSON(t, "原板品質", got.Quality, old.Quality)
	equal90JSON(t, "Technical全旧call", got.TechnicalEquivalence, old.TechnicalEquivalence)
	equal90JSON(t, "種", got.SeedView, old.SeedView)
	equal90JSON(t, "統合終端", got.InputEnd, old.InputEnd)
	equal90JSON(t, "全event入力", got.EntryObservations, old.EntryObservations)
	if len(got.GridDecisions) != len(old.GridDecisions) {
		t.Fatal("全定時数差")
	}
	for i, g := range got.GridDecisions {
		before := old.GridDecisions[i]
		before.Policies = map[string]PolicySupply{"E1": before.Policies["E1"]}
		equal90JSON(t, "旧全共有E1", g, before)
	}
	for delay := 0; delay <= 1; delay++ {
		equal90JSON(t, "P0旧Book全文", got.Books[bookKey("P0", delay)], old.Books[bookKey("E1G1", delay)])
	}
	bindings := []EntryOrderBinding{}
	for _, b := range got.EntryBindings {
		if strings.HasPrefix(b.BookKey, "P0_D") {
			b.BookKey = strings.Replace(b.BookKey, "P0_D", "E1G1_D", 1)
			bindings = append(bindings, b)
		}
	}
	previous := []EntryOrderBinding{}
	for _, b := range old.EntryBindings {
		if strings.HasPrefix(b.BookKey, "E1G1_D") {
			previous = append(previous, b)
		}
	}
	equal90JSON(t, "P0受理外binding", bindings, previous)
	equal90JSON(t, "P0利益原行", profit90P0(got.ProfitContexts, true), profit90P0(old.ProfitContexts, false))
}

// TestReplay90Legacy89P0FullAndEntry は自然Source合成3場の旧88同値を確認します。
//
// 引数: t(*testing.T)は同限月carry/限月resetを含む検査器です。
// 返り値: ありません。自然E1の非0は別の実指標手製Source人工で確認します。
func TestReplay90Legacy89P0FullAndEntry(t *testing.T) {
	manifest := input90MultiFixture(t, false)
	seeds, err := far80.PrepareTechnicalSeeds(manifest)
	if err != nil {
		t.Fatal(err)
	}
	for _, input := range manifest.Sessions {
		seed, oldSeed := seeds[input.ID], seeds[input.ID]
		got, err := Replay(manifest.Root, input, &seed)
		if err != nil {
			t.Fatal(err)
		}
		old, err := far89.Replay(manifest.Root, input, &oldSeed)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(seed, oldSeed) {
			t.Fatal("種carry差")
		}
		compare90Legacy89(t, got, old)
		if got.SourceEquivalence.StepFrames == 0 || got.TechnicalEquivalence.QuoteCalls == 0 {
			t.Fatal("同値計測欠落")
		}
	}
}

// TestReplay90GapLast0AndMergedEnd はLast0/疎入力/TOPIX終端で旧入口を変えません。
//
// 引数: t(*testing.T)は人工入力品質の検査器です。
// 返り値: ありません。欠足を補完せず同原行失効を保持します。
func TestReplay90GapLast0AndMergedEnd(t *testing.T) {
	session, _ := sessionClock("2026-11-02_Day")
	root, input := input90Fixture(t, session.ID, []float64{session.Start + 1, session.Start + 180, session.Start + 900, session.End - 1})
	input.Files["NK225_book"] = input90Gzip(t, root, "NKgap.gz", []map[string]any{input90Raw(session.Start+1, 1000, input.Contract), input90Raw(session.Start+180, 0, input.Contract), input90Raw(session.Start+901, 1001, input.Contract)})
	got, err := Replay(root, input, far80.NewTechnicalBank())
	if err != nil {
		t.Fatal(err)
	}
	old, err := far89.Replay(root, input, far80.NewTechnicalBank())
	if err != nil {
		t.Fatal(err)
	}
	compare90Legacy89(t, got, old)
	if got.InputEnd == nil || got.InputEnd.Reference != "TOPIX" {
		t.Fatal("TOPIX統合終端欠落")
	}
}

// TestBatch90SequentialParallel は全場種準備後の逐次/16worker保存を比較します。
//
// 引数: t(*testing.T)は完全合成3場の検査器です。
// 返り値: ありません。会計/全共有値/順序をJSON byte同値へ結びます。
func TestBatch90SequentialParallel(t *testing.T) {
	manifest := input90MultiFixture(t, false)
	root := t.TempDir()
	a, b := filepath.Join(root, "逐次"), filepath.Join(root, "並列")
	if err := RunBatch(manifest, a, 1, nil); err != nil {
		t.Fatal(err)
	}
	if err := RunBatch(manifest, b, 16, nil); err != nil {
		t.Fatal(err)
	}
	for _, input := range manifest.Sessions {
		x, err := os.ReadFile(filepath.Join(a, input.ID+".json"))
		if err != nil {
			t.Fatal(err)
		}
		y, err := os.ReadFile(filepath.Join(b, input.ID+".json"))
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(x, y) {
			t.Fatal("逐次並列の全JSON差", input.ID)
		}
	}
}
