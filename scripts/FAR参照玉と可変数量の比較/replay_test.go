// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/replay_test.go
// 87派生元SHA256: 6cab483141988199914fd2f6d6fc259d1175dc44a71a79cc0c28f916e970ef59

// 86派生元: scripts/保持帯の返済側固定否定/replay_test.go
// 86派生元SHA256: 8d626786119727595e974878e7e0ba7d7d35bba82e0f64bdccc2c4b5452348f9

// 85派生元: scripts/現在の価格応答と数量確認/replay_test.go
// 85派生元SHA256: 667beba24b2916bc900e0216f338c4dd0ebf27d527dde53b9aca2f589546fa8f

// 84派生元: scripts/構造否定と利益配分/replay_test.go
// 84派生元SHA256: 0b7f31c6da084fa11c78107035e2ebb774d65ecff3699fd7b459a2c2aeab876b

package far87

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
)

// input87Stamp は市場と無関係な人工Unix時計を保存形式へ写します。
//
// 引数: at(float64)は人工Unix秒です。
// 返り値: stringはRFC3339Nano時計です。
func input87Stamp(at float64) string {
	return time.Unix(0, int64(math.Round(at*1e9))).UTC().Format(time.RFC3339Nano)
}

// input87Raw は原板の形だけを持つ人工JSON行を作ります。
//
// 引数: at/last(float64)は人工時計/Last、code(string)は限月IDです。
// 返り値: map[string]anyは毎回独立した行で、実市場データではありません。
func input87Raw(at, last float64, code string) map[string]any {
	row := map[string]any{"Symbol": code, "CurrentPriceTime": input87Stamp(at), "CurrentPrice": last}
	bid := 10 * math.Floor((last-1e-9)/10)
	ask := 10 * math.Ceil((last+1e-9)/10)
	for i := 1; i <= 10; i++ {
		row[fmt.Sprintf("Buy%d", i)] = map[string]float64{"Price": bid - float64(i-1)*10, "Qty": 10}
		row[fmt.Sprintf("Sell%d", i)] = map[string]float64{"Price": ask + float64(i-1)*10, "Qty": 10}
	}
	return row
}

// input87Pin は人工ファイルの全byteを固定情報へまとめます。
//
// 引数: t(*testing.T)は検査、root/name(string)は人工一時領域と相対名です。
// 返り値: InputFileはサイズとSHA256を持つ人工指紋です。
func input87Pin(t *testing.T, root, name string) InputFile {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(data)
	return InputFile{Path: filepath.ToSlash(name), SHA256: hex.EncodeToString(digest[:]), Size: int64(len(data))}
}

// input87Gzip は人工行だけを新しい一時gzipへ保存します。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([]map[string]any)は人工行です。
// 返り値: InputFileは新しい人工gzipの指紋です。
func input87Gzip(t *testing.T, root, name string, rows []map[string]any) InputFile {
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
	return input87Pin(t, root, name)
}

// input87CSV は確定足の形だけを持つ人工CSVを作ります。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([][]string)は人工足です。
// 返り値: InputFileは人工CSVの指紋です。
func input87CSV(t *testing.T, root, name string, rows [][]string) InputFile {
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
	return input87Pin(t, root, name)
}

// input87Fixture は二市場・6入力の自己完結した人工場を作ります。
//
// 引数: t(*testing.T)は検査、id(string)は場ID、times([]float64)は人工原行時計です。
// 返り値: stringは一時領域、InputSessionは全6人工指紋です。
func input87Fixture(t *testing.T, id string, times []float64) (string, InputSession) {
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
			rows = append(rows, input87Raw(at, price, code))
		}
		input.Files[ref+"_book"] = input87Gzip(t, root, ref+".jsonl.gz", rows)
		for _, interval := range []int{60, 300} {
			name := fmt.Sprintf("%s_%d.csv", ref, interval)
			input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)] = input87CSV(t, root, name, nil)
		}
	}
	return root, input
}

// TestInput87PhysicalSequence は欠測・後退・同値行と物理行番号を混ぜないことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。実市場ファイルは開きません。
func TestInput87PhysicalSequence(t *testing.T) {
	session, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	root := t.TempDir()
	missing := input87Raw(session.Start, 1000, "NK")
	delete(missing, "CurrentPriceTime")
	unknown := input87Raw(session.Start+2, 1000, "NK")
	unknown["CurrentPrice"] = nil
	crossed := input87Raw(session.Start+3, 1000, "NK")
	crossed["Sell1"] = map[string]float64{"Price": 980, "Qty": 10}
	rows := []map[string]any{input87Raw(session.Start-1, 1000, "NK"), missing, input87Raw(session.Start+1, 1000, "NK"), input87Raw(session.Start+1, 1000, "NK"), unknown, input87Raw(session.Start+1, 999, "NK"), crossed, input87Raw(session.End, 1000, "NK")}
	file := input87Gzip(t, root, "人工.jsonl.gz", rows)
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

// TestInput87CandlesAndClock は足の公開時計と訂正版の内部時計を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。足は一時領域の架空値だけです。
func TestInput87CandlesAndClock(t *testing.T) {
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
	file := input87CSV(t, root, "人工.csv", [][]string{{input87Stamp(day.Start - 60), "1000", "1002", "999", "1001", "true"}, {input87Stamp(day.Start), "1000", "1002", "999", "1001", "true"}, {input87Stamp(day.Start + 60), "1000", "1002", "999", "1001", "false"}})
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

// TestReplay87UsesPreviousSnapshot は当時の直前原行だけで定時判断することを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。同時計の大きな価格変化を定時へ先取りしません。
func TestReplay87UsesPreviousSnapshot(t *testing.T) {
	session, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	grids, e := far80.ScheduledTimes(session.ID)
	if e != nil {
		t.Fatal(e)
	}
	root, input := input87Fixture(t, session.ID, []float64{session.Start + 1, grids[0] - 1, grids[0], grids[0] + 1, session.End - 1})
	rows := []map[string]any{input87Raw(session.Start+1, 1000, input.Contract), input87Raw(grids[0]-1, 1001, input.Contract), input87Raw(grids[0], 5000, input.Contract), input87Raw(grids[0]+1, 5000, input.Contract), input87Raw(session.End-1, 5000, input.Contract)}
	input.Files["NK225_book"] = input87Gzip(t, root, "NK差替.jsonl.gz", rows)
	result, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	if len(result.Books) != 4 || len(result.GridDecisions) != 25 {
		t.Fatal("政策/遅延又は全定時が欠落", len(result.Books), len(result.GridDecisions))
	}
	for _, grid := range result.GridDecisions[:1] {
		d := grid.C0.Base
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
			if !ok || book.Mode != "S0G1" || book.FillDelaySeconds != float64(delay) || len(book.Decisions) != 25 {
				t.Fatal("保存会計キー/時計が違います", mode, delay)
			}
		}
	}
}

// TestReplay87UnknownLastSeparatesIndices は不良Lastの実連番と源連番を区別します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。交差板でも正常Lastは技法へ入り、不良Lastは源へ入りません。
func TestReplay87UnknownLastSeparatesIndices(t *testing.T) {
	session, e := sessionClock("2026-11-02_Day")
	if e != nil {
		t.Fatal(e)
	}
	grids, _ := far80.ScheduledTimes(session.ID)
	root, input := input87Fixture(t, session.ID, []float64{session.Start + 1, session.Start + 2, grids[0] - 1, grids[0] + 1, grids[1] - 1, grids[1] + 1})
	bad := input87Raw(session.Start+2, 1000, input.Contract)
	bad["CurrentPrice"] = nil
	crossed := input87Raw(grids[0]-1, 1001, input.Contract)
	crossed["Buy1"] = map[string]float64{"Price": 1002, "Qty": 10}
	crossed["Sell1"] = map[string]float64{"Price": 1001, "Qty": 10}
	badGrid := input87Raw(grids[1]-1, 1000, input.Contract)
	delete(badGrid, "CurrentPrice")
	input.Files["NK225_book"] = input87Gzip(t, root, "NK未知.jsonl.gz", []map[string]any{input87Raw(session.Start+1, 1000, input.Contract), bad, crossed, input87Raw(grids[0]+1, 1001, input.Contract), badGrid, input87Raw(grids[1]+1, 1000, input.Contract)})
	result, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	if result.Quality["NK225"].BadLast != 2 {
		t.Fatal("不良Lastを数えていません")
	}
	first := result.GridDecisions[0].C0.Base
	if first.Quote.Index != 2 || first.Evidence.SourceIndex != 1 || first.Quote.Valid || first.Technical.Close3 != 1001 {
		t.Fatalf("SourceIndex/実Index又はLast/BBOを混同:%+v", first)
	}
	second := result.GridDecisions[1].C0.Base
	if second.Quote.Index != 4 || second.Quote.Line != 5 || second.Quote.Valid || second.Evidence.SourceLine != 4 || second.Allowed {
		t.Fatalf("不良Lastを源観測として再利用:%+v", second)
	}
	if second.Technical.TrendKnown || second.Technical.ATRKnown || second.Technical.ReversalKnown {
		t.Fatal("不良Last後に指標を既知で補完")
	}
}

// TestReplay87QuietAndEOF は米国境界と終端後候補停止を全枠へ残します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。架空の新規/返済約定を作りません。
func TestReplay87QuietAndEOF(t *testing.T) {
	session, e := sessionClock("2026-11-02_Night")
	if e != nil {
		t.Fatal(e)
	}
	times := []float64{session.Start + 1, session.USOpen - 901, session.USOpen - 900, session.USOpen + 899, session.USOpen + 900, session.End - 1}
	root, input := input87Fixture(t, session.ID, times)
	result, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	if len(result.GridDecisions) != 49 {
		t.Fatal("夜間49枠×固定B1入口が欠落")
	}
	pre, post := 0, 0
	for _, grid := range result.GridDecisions {
		if grid.At == session.USOpen-900 {
			pre++
			if grid.Window != "静観" || grid.ClockAllowed || grid.BlockReason == "" {
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
	if pre != 1 || post != 1 {
		t.Fatal("境界定時が二重又は欠落", pre, post)
	}
	root, input = input87Fixture(t, "2026-11-03_Day", []float64{session.End + 3*3600})
	day, e := Replay(root, input, far80.NewTechnicalBank())
	if e != nil {
		t.Fatal(e)
	}
	for _, grid := range day.GridDecisions {
		if grid.ClockAllowed || grid.BlockReason != "原板終端後の定時" {
			t.Fatal("終端後を当時原行で補完", grid)
		}
	}
	for _, book := range day.Books {
		if book.Unresolved || len(book.Trades) != 0 || book.Metrics.EntryQuantity != 0 {
			t.Fatal("終端後の架空約定", book.Mode)
		}
	}
}

// input87MultiFixture は複数場の種引継ぎだけを検査する密な人工台帳を作ります。
//
// 引数: t(*testing.T)は検査器、mirror(bool)は価格・両気配を反転するかです。
// 返り値: InputManifestは3場の人工固定台帳です。
func input87MultiFixture(t *testing.T, mirror bool) InputManifest {
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
				rows = append(rows, input87Raw(at, price, contract))
			}
			file := input87Gzip(t, dir, reference+".jsonl.gz", rows)
			file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
			input.Files[reference+"_book"] = file
			for _, interval := range []int{60, 300} {
				file = input87CSV(t, dir, fmt.Sprintf("%s_%d.csv", reference, interval), nil)
				file.Path = filepath.ToSlash(filepath.Join(id, file.Path))
				input.Files[fmt.Sprintf("%s_candle_%d", reference, interval)] = file
			}
		}
		manifest.Sessions = append(manifest.Sessions, input)
	}
	return manifest
}

// TestReplay87SeedsAndParallel は逐次と種複写並列の全成果物が同値であることを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。同限月carryと限月切替resetを含みます。
func TestReplay87SeedsAndParallel(t *testing.T) {
	manifest := input87MultiFixture(t, false)
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

// TestReplay87MirrorSnapshots は価格反転で指標・時計・入力品質が対称なことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。売買資格の単独人工はEntry担当の検査へ分けます。
func TestReplay87MirrorSnapshots(t *testing.T) {
	positive, negative := input87MultiFixture(t, false), input87MultiFixture(t, true)
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
		if math.Abs(x.C0.Base.Quote.Last+y.C0.Base.Quote.Last-10000) > 1e-8 {
			t.Fatal("鏡像Lastが違います")
		}
		p, q := x.C0.Base.Technical, y.C0.Base.Technical
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
		pairLeft, pairRight := x.C0.Base.ChartPair, y.C0.Base.ChartPair
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
