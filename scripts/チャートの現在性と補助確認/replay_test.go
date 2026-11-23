package far82

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// input82Stamp は市場と無関係な人工Unix時計を保存形式へ写します。
//
// 引数: at(float64)は人工Unix秒です。
// 返り値: stringはRFC3339Nano時計です。
func input82Stamp(at float64) string {
	return time.Unix(0, int64(math.Round(at*1e9))).UTC().Format(time.RFC3339Nano)
}

// input82Raw は原板の形だけを持つ人工JSON行を作ります。
//
// 引数: at/last(float64)は人工時計/Last、code(string)は限月IDです。
// 返り値: map[string]anyは毎回独立した行で、実市場データではありません。
func input82Raw(at, last float64, code string) map[string]any {
	row := map[string]any{"Symbol": code, "CurrentPriceTime": input82Stamp(at), "CurrentPrice": last}
	for i := 1; i <= 10; i++ {
		row[fmt.Sprintf("Buy%d", i)] = map[string]float64{"Price": last - float64(i), "Qty": 10}
		row[fmt.Sprintf("Sell%d", i)] = map[string]float64{"Price": last + float64(i), "Qty": 10}
	}
	return row
}

// input82Pin は人工ファイルの全byteを固定情報へまとめます。
//
// 引数: t(*testing.T)は検査、root/name(string)は人工一時領域と相対名です。
// 返り値: InputFileはサイズとSHA256を持つ人工指紋です。
func input82Pin(t *testing.T, root, name string) InputFile {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(data)
	return InputFile{Path: filepath.ToSlash(name), SHA256: hex.EncodeToString(digest[:]), Size: int64(len(data))}
}

// input82Gzip は人工行だけを新しい一時gzipへ保存します。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([]map[string]any)は人工行です。
// 返り値: InputFileは新しい人工gzipの指紋です。
func input82Gzip(t *testing.T, root, name string, rows []map[string]any) InputFile {
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
	return input82Pin(t, root, name)
}

// input82CSV は確定足の形だけを持つ人工CSVを作ります。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([][]string)は人工足です。
// 返り値: InputFileは人工CSVの指紋です。
func input82CSV(t *testing.T, root, name string, rows [][]string) InputFile {
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
	return input82Pin(t, root, name)
}

// input82Fixture は二市場・6入力の自己完結した人工場を作ります。
//
// 引数: t(*testing.T)は検査、id(string)は場ID、times([]float64)は人工原行時計です。
// 返り値: stringは一時領域、InputSessionは全6人工指紋です。
func input82Fixture(t *testing.T, id string, times []float64) (string, InputSession) {
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
			rows = append(rows, input82Raw(at, price, code))
		}
		input.Files[ref+"_book"] = input82Gzip(t, root, ref+".jsonl.gz", rows)
		for _, interval := range []int{60, 300} {
			name := fmt.Sprintf("%s_%d.csv", ref, interval)
			input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)] = input82CSV(t, root, name, nil)
		}
	}
	return root, input
}

// TestInput82PhysicalSequence は欠測・後退・同値行と物理行番号を混ぜないことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。実市場ファイルは開きません。
func TestInput82PhysicalSequence(t *testing.T) {
	session, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	root := t.TempDir()
	missing := input82Raw(session.Start, 1000, "NK")
	delete(missing, "CurrentPriceTime")
	unknown := input82Raw(session.Start+2, 1000, "NK")
	unknown["CurrentPrice"] = nil
	crossed := input82Raw(session.Start+3, 1000, "NK")
	crossed["Sell1"] = map[string]float64{"Price": 998, "Qty": 10}
	rows := []map[string]any{input82Raw(session.Start-1, 1000, "NK"), missing, input82Raw(session.Start+1, 1000, "NK"), input82Raw(session.Start+1, 1000, "NK"), unknown, input82Raw(session.Start+1, 999, "NK"), crossed, input82Raw(session.End, 1000, "NK")}
	file := input82Gzip(t, root, "人工.jsonl.gz", rows)
	path, e := verifyInput(root, file)
	if e != nil {
		t.Fatal(e)
	}
	parsed, q, e := readBoards(path, "NK225", session)
	if e != nil {
		t.Fatal(e)
	}
	if q.Lines != 8 || q.ClockMissing != 1 || q.Outside != 2 || q.Backward != 1 || q.BadLast != 1 || q.BadQuote != 1 || q.Accepted != 4 {
		t.Fatalf("品質の分類が異なります:%+v", q)
	}
	got := []int64{}
	for _, row := range parsed {
		got = append(got, row.Line)
	}
	if !reflect.DeepEqual(got, []int64{3, 4, 5, 7}) {
		t.Fatal("物理行又は同値行が失われました", got)
	}
	wrong := file
	wrong.SHA256 = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
	if _, e = verifyInput(root, wrong); e == nil {
		t.Fatal("不正SHAを受理")
	}
	wrong = file
	wrong.Size++
	if _, e = verifyInput(root, wrong); e == nil {
		t.Fatal("不正サイズを受理")
	}
}

// TestInput82CandlesAndClock は足の公開時計と訂正版の内部時計を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。足は一時領域の架空値だけです。
func TestInput82CandlesAndClock(t *testing.T) {
	day, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	if day.USOpen != 0 || day.NightCoreStart != 0 || day.ExtraAt != day.Start+13500 || day.ForceClose != day.End-600 {
		t.Fatal("Day訂正時計が違います", day)
	}
	for _, id := range []string{"2026-10-30_Night", "2026-11-02_Night"} {
		night, e := sessionClock(id)
		if e != nil {
			t.Fatal(e)
		}
		us, e := far80.USOpen(id[:10])
		if e != nil {
			t.Fatal(e)
		}
		if night.USOpen != us || night.ExtraAt != us+1800 || night.NightCoreStart != 0 || night.ForceClose != night.End-600 {
			t.Fatal("Night訂正時計が違います", night)
		}
	}
	root := t.TempDir()
	file := input82CSV(t, root, "人工.csv", [][]string{{input82Stamp(day.Start - 60), "1000", "1002", "999", "1001", "true"}, {input82Stamp(day.Start), "1000", "1002", "999", "1001", "true"}, {input82Stamp(day.Start + 60), "1000", "1002", "999", "1001", "false"}})
	path, e := verifyInput(root, file)
	if e != nil {
		t.Fatal(e)
	}
	events, e := readCandles(path, "NK225", 60, 60, day)
	if e != nil {
		t.Fatal(e)
	}
	if len(events) != 1 || events[0].Candle.Time != day.Start || events[0].At != day.Start+120 {
		t.Fatal("足終端と公開遅延が混ざりました", events)
	}
}

// TestReplay82UsesPreviousSnapshot は当時の直前原行だけで定時判断することを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。同時計の大きな価格変化を定時へ先取りしません。
func TestReplay82UsesPreviousSnapshot(t *testing.T) {
	session, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	grids, e := far80.ScheduledTimes(session.ID)
	if e != nil {
		t.Fatal(e)
	}
	root, input := input82Fixture(t, session.ID, []float64{session.Start + 1, grids[0] - 1, grids[0], grids[0] + 1, session.End - 1})
	rows := []map[string]any{input82Raw(session.Start+1, 1000, input.Contract), input82Raw(grids[0]-1, 1001, input.Contract), input82Raw(grids[0], 5000, input.Contract), input82Raw(grids[0]+1, 5000, input.Contract), input82Raw(session.End-1, 5000, input.Contract)}
	input.Files["NK225_book"] = input82Gzip(t, root, "NK差替.jsonl.gz", rows)
	result, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	if len(result.Books) != 4 || len(result.GridDecisions) != 50 {
		t.Fatal("政策/遅延又は全定時が欠落", len(result.Books), len(result.GridDecisions))
	}
	for _, grid := range result.GridDecisions[:2] {
		d := grid.Decision
		if grid.At != grids[0] || d.Quote.Line != 2 || d.Quote.Time != grids[0]-1 || d.Quote.Last != 1001 || d.Evidence.SourceLine != 2 || d.Evidence.Last != 1001 {
			t.Fatalf("当時snapshot不一致:%+v", grid)
		}
		if d.Technical.Close3 != 1001 || d.Technical.Bar3End != grids[0] {
			t.Fatal("確定終端と当時計の原行を混同しました", d.Technical)
		}
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book, ok := result.Books[bookKey(mode, delay)]
			if !ok || book.Mode != mode || book.FillDelaySeconds != float64(delay) || len(book.Decisions) != 25 {
				t.Fatal("保存会計キー/時計が違います", mode, delay)
			}
		}
	}
}

// TestReplay82UnknownLastSeparatesIndices は不良Lastの実連番と源連番を区別します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。交差板でも正常Lastは技法へ入り、不良Lastは源へ入りません。
func TestReplay82UnknownLastSeparatesIndices(t *testing.T) {
	session, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	grids, _ := far80.ScheduledTimes(session.ID)
	root, input := input82Fixture(t, session.ID, []float64{session.Start + 1, session.Start + 2, grids[0] - 1, grids[0] + 1, grids[1] - 1, grids[1] + 1})
	bad := input82Raw(session.Start+2, 1000, input.Contract)
	bad["CurrentPrice"] = nil
	crossed := input82Raw(grids[0]-1, 1001, input.Contract)
	crossed["Buy1"] = map[string]float64{"Price": 1002, "Qty": 10}
	crossed["Sell1"] = map[string]float64{"Price": 1001, "Qty": 10}
	badGrid := input82Raw(grids[1]-1, 1000, input.Contract)
	delete(badGrid, "CurrentPrice")
	input.Files["NK225_book"] = input82Gzip(t, root, "NK未知.jsonl.gz", []map[string]any{input82Raw(session.Start+1, 1000, input.Contract), bad, crossed, input82Raw(grids[0]+1, 1001, input.Contract), badGrid, input82Raw(grids[1]+1, 1000, input.Contract)})
	result, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	if result.Quality["NK225"].BadLast != 2 {
		t.Fatal("不良Lastを数えていません")
	}
	first := result.GridDecisions[0].Decision
	if first.Quote.Index != 2 || first.Evidence.SourceIndex != 1 || first.Quote.Valid || first.Technical.Close3 != 1001 {
		t.Fatalf("SourceIndex/実Index又はLast/BBOを混同:%+v", first)
	}
	second := result.GridDecisions[2].Decision
	if second.Quote.Index != 4 || second.Quote.Line != 5 || second.Quote.Valid || second.Evidence.SourceLine != 4 || second.Allowed {
		t.Fatalf("不良Lastを源観測として再利用:%+v", second)
	}
	if second.Technical.TrendKnown || second.Technical.ATRKnown || second.Technical.ReversalKnown {
		t.Fatal("不良Last後に指標を既知で補完")
	}
}

// TestReplay82QuietAndEOF は米国境界と終端後候補停止を全枠へ残します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。架空の新規/返済約定を作りません。
func TestReplay82QuietAndEOF(t *testing.T) {
	session, e := sessionClock("2026-11-02_Night")
	if e != nil {
		t.Fatal(e)
	}
	times := []float64{session.Start + 1, session.USOpen - 901, session.USOpen - 900, session.USOpen + 899, session.USOpen + 900, session.End - 1}
	root, input := input82Fixture(t, session.ID, times)
	result, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	if len(result.GridDecisions) != 98 {
		t.Fatal("夜間49枠×2政策が欠落")
	}
	pre, post := 0, 0
	for _, grid := range result.GridDecisions {
		if grid.At == session.USOpen-900 {
			pre++
			if grid.Window != "静観" || grid.ClockAllowed || grid.CandidateAccepted || grid.BlockReason == "" {
				t.Fatal("静観境界が先取りされています", grid)
			}
		}
		if grid.At == session.USOpen+900 {
			post++
			if grid.Window != "U165_03" || !grid.ClockAllowed {
				t.Fatal("米国後等号が開始されません", grid)
			}
		}
	}
	if pre != 2 || post != 2 {
		t.Fatal("境界定時が二重又は欠落", pre, post)
	}
	root, input = input82Fixture(t, "2026-11-03_Day", []float64{session.End + 3*3600})
	day, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	for _, grid := range day.GridDecisions {
		if grid.CandidateAccepted || grid.ClockAllowed || grid.BlockReason != "原板終端後の定時" {
			t.Fatal("終端後を当時原行で補完", grid)
		}
	}
	for _, book := range day.Books {
		if book.Unresolved || len(book.Trades) != 0 || book.Metrics.EntryQuantity != 0 {
			t.Fatal("終端後の架空約定", book.Mode)
		}
	}
}

// input82MultiFixture は複数場の種引継ぎだけを検査する密な人工台帳を作ります。
//
// 引数: t(*testing.T)は検査器、mirror(bool)は価格・両気配を反転するかです。
// 返り値: InputManifestは3場の人工固定台帳です。
func input82MultiFixture(t *testing.T, mirror bool) InputManifest {
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
			for index, at := 0, session.Start+1; at < session.End; index, at = index+1, at+60 {
				price := 1000 + float64(index)/10 + float64(index%7)
				if reference == "TOPIX" {
					price = 4000 + float64(index)/10 + float64(index%7)
				}
				if mirror {
					price = 10000 - price
				}
				rows = append(rows, input82Raw(at, price, contract))
			}
			file := input82Gzip(t, dir, reference+".jsonl.gz", rows)
			file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
			input.Files[reference+"_book"] = file
			for _, interval := range []int{60, 300} {
				file = input82CSV(t, dir, fmt.Sprintf("%s_%d.csv", reference, interval), nil)
				file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
				input.Files[fmt.Sprintf("%s_candle_%d", reference, interval)] = file
			}
		}
		manifest.Sessions = append(manifest.Sessions, input)
	}
	return manifest
}

// TestReplay82SeedsAndParallel は逐次と種複写並列の全成果物が同値であることを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。同限月carryと限月切替resetを含みます。
func TestReplay82SeedsAndParallel(t *testing.T) {
	manifest := input82MultiFixture(t, false)
	seeds, e := far80.PrepareTechnicalSeeds(manifest)
	if e != nil {
		t.Fatal(e)
	}
	bank := far80.NewTechnicalBank()
	contract := ""
	sequential := map[string][]byte{}
	for _, input := range manifest.Sessions {
		if input.Contract != contract {
			bank = far80.NewTechnicalBank()
			contract = input.Contract
		}
		if !reflect.DeepEqual(*bank, seeds[input.ID]) {
			t.Fatal("開始前種が逐次と違います", input.ID)
		}
		result, e := Replay(manifest.Root, input, bank)
		if e != nil {
			t.Fatal(e)
		}
		copy := seeds[input.ID]
		isolated, e := Replay(manifest.Root, input, &copy)
		if e != nil {
			t.Fatal(e)
		}
		if !reflect.DeepEqual(result, isolated) {
			t.Fatal("種コピー再生が逐次と違います", input.ID)
		}
		data, e := json.Marshal(result)
		if e != nil {
			t.Fatal(e)
		}
		sequential[input.ID] = data
	}
	if reflect.DeepEqual(seeds[manifest.Sessions[1].ID], *far80.NewTechnicalBank()) {
		t.Fatal("同限月の既知種が継承されません")
	}
	if !reflect.DeepEqual(seeds[manifest.Sessions[2].ID], *far80.NewTechnicalBank()) {
		t.Fatal("限月切替で完全resetされません")
	}
	out := filepath.Join(t.TempDir(), "並列")
	var log bytes.Buffer
	if e = RunBatch(manifest, out, 8, &log); e != nil {
		t.Fatal(e)
	}
	for _, input := range manifest.Sessions {
		data, e := os.ReadFile(filepath.Join(out, input.ID+".json"))
		if e != nil {
			t.Fatal(e)
		}
		if !bytes.Equal(data, sequential[input.ID]) {
			t.Fatal("並列保存JSONが逐次と違います", input.ID)
		}
	}
	if e = RunBatch(manifest, out, 8, nil); e == nil {
		t.Fatal("既存結果を上書き")
	}
	for _, workers := range []int{0, 17} {
		if e = RunBatch(manifest, filepath.Join(t.TempDir(), "不正"), workers, nil); e == nil {
			t.Fatal("不正workerを受理", workers)
		}
	}
}

// TestReplay82MirrorSnapshots は価格反転で指標・時計・入力品質が対称なことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。売買資格の単独人工はEntry担当の検査へ分けます。
func TestReplay82MirrorSnapshots(t *testing.T) {
	positive, negative := input82MultiFixture(t, false), input82MultiFixture(t, true)
	a, b := far80.NewTechnicalBank(), far80.NewTechnicalBank()
	left, e := Replay(positive.Root, positive.Sessions[0], a)
	if e != nil {
		t.Fatal(e)
	}
	right, e := Replay(negative.Root, negative.Sessions[0], b)
	if e != nil {
		t.Fatal(e)
	}
	if len(left.GridDecisions) != len(right.GridDecisions) || !reflect.DeepEqual(left.Quality, right.Quality) {
		t.Fatal("鏡像の時計又は品質が非対称")
	}
	checked := 0
	for i, x := range left.GridDecisions {
		y := right.GridDecisions[i]
		if x.At != y.At || x.Window != y.Window || x.ClockAllowed != y.ClockAllowed {
			t.Fatal("鏡像で時計が変化")
		}
		if math.Abs(x.Decision.Quote.Last+y.Decision.Quote.Last-10000) > 1e-8 {
			t.Fatal("鏡像Lastが違います")
		}
		p, q := x.Decision.Technical, y.Decision.Technical
		if p.ATRKnown != q.ATRKnown || p.TrendKnown != q.TrendKnown {
			t.Fatal("鏡像で既知性が変化")
		}
		if p.ATRKnown {
			checked++
			if math.Abs(p.ATR3-q.ATR3) > 1e-8 {
				t.Fatal("鏡像でATRが変化")
			}
		}
		if p.TrendKnown {
			if math.Abs(p.EMA8_3+q.EMA8_3-10000) > 1e-8 || math.Abs(p.EMA21_15+q.EMA21_15-10000) > 1e-8 {
				t.Fatal("鏡像EMAが違います")
			}
		}
		if p.ReversalKnown {
			if math.Abs(p.RSI3+q.RSI3-100) > 1e-8 || math.Abs(p.Histogram3+q.Histogram3) > 1e-8 {
				t.Fatal("鏡像の勢いが非対称")
			}
		}
		pairLeft, pairRight := x.Decision.ChartPair, y.Decision.ChartPair
		if pairLeft.Previous3Known != pairRight.Previous3Known || pairLeft.PreviousBar3End != pairRight.PreviousBar3End {
			t.Fatal("前足の既知性又は公開時計が非対称")
		}
		if pairLeft.Previous3Known && (math.Abs(pairLeft.PreviousClose3+pairRight.PreviousClose3-10000) > 1e-8 ||
			math.Abs(pairLeft.PreviousEMA8_3+pairRight.PreviousEMA8_3-10000) > 1e-8) {
			t.Fatal("鏡像の前Close又は前EMAが非対称")
		}
	}
	if checked == 0 {
		t.Fatal("鏡像人工で既知ATRに到達していません")
	}
}

// input82Runtime は人工確定足で現在の進行・取得位置を満たす4会計を作ります。
//
// 引数: t(*testing.T)は検査器、side(int)は±1の鏡像方向です。
// 返り値: *replayRuntimeは人工会計、float64は次の定時です。
func input82Runtime(t *testing.T, side int) (*replayRuntime, float64) {
	t.Helper()
	session, err := sessionClock("2026-11-02_Day")
	if err != nil {
		t.Fatal(err)
	}
	at := session.Start + 5.5*3600
	bank := NewChartBank(far80.NewTechnicalBank())
	bank.BeginSession(session.Start)
	wave := []float64{0, 5, -5, 5, -5, 0}
	price := 0.0
	index := 0
	for clock := session.Start + 1; clock < at; clock += 30 {
		price = 1000 + float64(index)*.1 + float64(index*index)*.00005 + wave[index%6]
		if side < 0 {
			price = 10000 - price
		}
		if err := bank.Observe(Quote{Time: clock, Last: price, Valid: true}); err != nil {
			t.Fatal(err)
		}
		index++
	}
	q := Quote{Time: at - 1, Index: 0, Line: 20, Last: price, Bid: price - 1, Ask: price + 1, Valid: true}
	evidence := CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: q.Time,
		SourceIndex: 7, SourceLine: q.Line, Last: q.Last, Bid: q.Bid, Ask: q.Ask,
		Buy:  far81.CurrentSupport{Windows: map[string]far81.CurrentSupportWindow{"人工": {Value: 1}}},
		Sell: far81.CurrentSupport{Windows: map[string]far81.CurrentSupportWindow{"人工": {Value: 1}}}}}
	runtime := &replayRuntime{session: session, bank: bank, books: map[string]*Book{}, last: Quote{Index: -1},
		grids: map[float64]bool{at: true}, result: &ReplayResult{Session: session.ID, Books: map[string]BookResult{}}}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book, err := NewBook(session.ID, mode, 100)
			if err != nil {
				t.Fatal(err)
			}
			if err = book.SetFillDelay(float64(delay)); err != nil {
				t.Fatal(err)
			}
			runtime.books[bookKey(mode, delay)] = book
		}
	}
	if err = runtime.observeQuote(q, &evidence); err != nil {
		t.Fatal(err)
	}
	return runtime, at
}

// TestReplay82CandidateSharingAndDelay は入口候補を両遅延へ同値供給することを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。買売とも実新規・場末返済が非0であることを要求します。
func TestReplay82CandidateSharingAndDelay(t *testing.T) {
	for _, side := range []int{1, -1} {
		runtime, at := input82Runtime(t, side)
		if err := runtime.advanceTimer(at, false); err != nil {
			t.Fatal(err)
		}
		if len(runtime.result.GridDecisions) != 2 {
			t.Fatal("入口二案が保存されません")
		}
		for _, grid := range runtime.result.GridDecisions {
			if !grid.CandidateAccepted || !grid.Decision.Allowed || grid.Decision.Side != side {
				t.Fatal("人工のチャート主軸候補が成立しません", side, grid)
			}
		}
		for _, mode := range Modes {
			zero := runtime.books[bookKey(mode, 0)].Result()
			one := runtime.books[bookKey(mode, 1)].Result()
			if len(zero.Orders) != 1 || len(one.Orders) != 1 || zero.Orders[0].Kind != "entry" ||
				zero.Orders[0].Quantity != 100 || zero.Orders[0].RequestTime != at ||
				zero.Orders[0].ReferenceID != one.Orders[0].ReferenceID {
				t.Fatal("遅延ごとに候補を変更", side, mode, zero.Orders, one.Orders)
			}
		}
		original := runtime.result.GridDecisions[1].Decision.Evidence
		runtime.result.GridDecisions[0].Decision.Evidence.Buy.Windows["人工"] = far81.CurrentSupportWindow{Value: 999}
		if original.Buy.Windows["人工"].Value == 999 {
			t.Fatal("政策間で元mapを共有")
		}
		q := runtime.last
		q.Time, q.Index, q.Line = at+.5, q.Index+1, q.Line+1
		if err := runtime.observeQuote(q, nil); err != nil {
			t.Fatal(err)
		}
		for _, mode := range Modes {
			zero := runtime.books[bookKey(mode, 0)].Result()
			one := runtime.books[bookKey(mode, 1)].Result()
			if zero.Metrics.EntryQuantity != 100 || one.Metrics.EntryQuantity != 0 || one.Metrics.PendingEntryQuantity != 100 {
				t.Fatal("遅延間で実所有を共有", mode, side, zero.Metrics, one.Metrics)
			}
		}
		q.Time, q.Index, q.Line = at+1, q.Index+1, q.Line+1
		if err := runtime.observeQuote(q, nil); err != nil {
			t.Fatal(err)
		}
		for _, mode := range Modes {
			book := runtime.books[bookKey(mode, 1)].Result()
			if book.Metrics.EntryQuantity != 100 || book.Trades[0].SourceLine != 22 {
				t.Fatal("1秒後の最初正常原行に約定しません", mode, side, book)
			}
		}
		if err := runtime.advanceTimer(runtime.session.ForceClose, false); err != nil {
			t.Fatal(err)
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				book := runtime.books[bookKey(mode, delay)].Result()
				if book.Metrics.OpenQuantity != 100 || book.Metrics.ReservedExitQuantity != 100 {
					t.Fatal("場末要求の前後所有が異なります", side, mode, delay, book.Metrics)
				}
			}
		}
		for _, clock := range []float64{runtime.session.ForceClose, runtime.session.ForceClose + 1} {
			q.Time, q.Index, q.Line = clock, q.Index+1, q.Line+1
			if err := runtime.observeQuote(q, nil); err != nil {
				t.Fatal(err)
			}
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				book := runtime.books[bookKey(mode, delay)].Result()
				if book.Unresolved || book.Metrics.OpenQuantity != 0 || book.Metrics.ExitQuantity != 100 || len(book.Trades) != 2 {
					t.Fatal("人工新規が全量返済されません", side, mode, delay, book.Metrics)
				}
			}
		}
	}
}
