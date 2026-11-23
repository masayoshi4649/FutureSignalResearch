package continuous101

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	oldtape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// request は市場履歴を用いない公開型人工を作ります。
//
// 引数: side(int)、seconds(int)は鏡像と人工長です。
// 返り値: Requestは5秒原行と公開CSVを持つ手製入力です。
func request(side, seconds int) Request {
	start := 1800000000.0
	s := strategy.Session{ID: "人工Day", Kind: "Day", Start: start, End: start + 20000, ForceClose: start + 19400}
	r := Request{Session: s, Scene: warm.Scene{ID: s.ID, Contract: "人工限月", Start: start}, Rows: []Row{}, Candles: []CandleEvent{}, Grids: []float64{start + 300, start + 600, start + 900}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		for i := 0; i <= seconds; i += 5 {
			base := 40000.0
			if ref == "TOPIX" {
				base = 2800
			}
			price := base + float64(side*(i/5)%7)*5
			b := strategy.Board{Reference: ref, Time: start + float64(i), Received: start + float64(i), Last: price, Bid: price - 5, Ask: price + 5, BidQuantity: 50 + float64(i%17), AskQuantity: 60}
			for j := 0; j < 10; j++ {
				b.BidLevels[j] = strategy.ResearchLevel{Price: b.Bid - float64(j)*10, Quantity: b.BidQuantity}
				b.AskLevels[j] = strategy.ResearchLevel{Price: b.Ask + float64(j)*10, Quantity: b.AskQuantity}
			}
			r.Rows = append(r.Rows, Row{b, int64(i/5 + 10)})
		}
	}
	for _, ref := range []string{"TOPIX", "NK225"} {
		for _, width := range []int{60, 300} {
			for t := 0; t < seconds; t += width {
				at := start + float64(t)
				c := strategy.Candle{Time: at, Open: 40000, High: 40030, Low: 39990, Close: 40010, Closed: true}
				r.Candles = append(r.Candles, CandleEvent{ref, width, c, at + float64(width) + 60})
			}
		}
	}
	return r
}

// legacy は人工出力を旧公開Tapeの型へ対応させます。
//
// 引数: value(Sidecar)は人工の期待値です。
// 返り値: oldtape.Tapeは型接続用で、旧市場一致の証拠ではありません。
func legacy(value Sidecar) oldtape.Tape {
	t := oldtape.Tape{Version: 1, Scope: "手製旧入力型・実Source未測定", Session: value.Session, Capabilities: oldtape.Capabilities(), Events: []oldtape.TapeEvent{}}
	for _, g := range value.Grids {
		c := g
		t.Events = append(t.Events, oldtape.TapeEvent{Kind: "grid", At: g.At, Context: &c})
	}
	for _, r := range value.Rows {
		q := r.Scalar
		t.Events = append(t.Events, oldtape.TapeEvent{Kind: "quote", At: q.Time, Quote: &q})
	}
	sort.SliceStable(t.Events, func(i, j int) bool {
		return t.Events[i].At < t.Events[j].At || t.Events[i].At == t.Events[j].At && t.Events[i].Kind == "grid" && t.Events[j].Kind != "grid"
	})
	if len(t.Events) > 0 {
		t.Events = append(t.Events, oldtape.TapeEvent{Kind: "force", At: t.Events[len(t.Events)-1].At + 100, Methods: []string{"D164_15"}})
	}
	for i := range t.Events {
		t.Events[i].Ordinal = i + 1
	}
	return t
}

// TestClockCurrentAndDictionary は公開経路と同秒公表を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。失敗はt.Fatalへ渡します。
func TestClockCurrentAndDictionary(t *testing.T) {
	for _, side := range []int{1, -1} {
		req := request(side, 965)
		out, _, e := Build(req, nil)
		if e != nil {
			t.Fatal(e)
		}
		if len(out.Grids) != 3 || len(out.Rows) != 194 || out.SourceReexecuted || out.FinancialExecuted {
			t.Fatal("scope/count")
		}
		s := req.Session.Start
		g := out.Grids[2]
		if g.Chart.Three.BarEnd != s+900 || g.Chart.Fifteen.BarEnd != s+900 || g.Current.Time != s+895 || g.Chart.Three.LastSource.Time != s+895 {
			t.Fatal("同秒raw先取り")
		}
		for _, r := range out.Rows {
			if r.Identity.Time > s && r.Current.Buy.PeerAt >= r.Current.Time {
				t.Fatal("同秒peer")
			}
			if r.Current.SourceLine != r.Identity.PhysicalLine || r.Current.SourceIndex != *r.Identity.FeaturesIndex || r.Current.Short.Time != r.Current.Time {
				t.Fatal("Current出典")
			}
		}
		phase := []string{}
		for _, tr := range out.Trace {
			if tr.At == s+900 {
				phase = append(phase, tr.Kind)
			}
		}
		if !reflect.DeepEqual(phase, []string{"publication", "grid", "raw", "raw"}) {
			t.Fatal(phase)
		}
		for _, tr := range out.Trace {
			restored, e := Materialize(out, tr.Chart)
			if e != nil {
				t.Fatal(e)
			}
			state, e := pack(restored, map[string]Payload{})
			if e != nil || state != tr.Chart {
				t.Fatal("snapshot復元")
			}
		}
		old := legacy(out)
		before, _ := json.Marshal(old)
		match, e := BindLegacy(out, old)
		if e != nil || match.Quotes != len(out.Rows) || match.Grids != 3 || match.Events != len(old.Events) {
			t.Fatal("旧型接続", e)
		}
		after, _ := json.Marshal(old)
		if string(before) != string(after) {
			t.Fatal("旧入力改変")
		}
		// ----------------------------------------
		// 全公開型を再ロードしてもCurrent/Chartの値を落とさない。
		raw, e := json.Marshal(out)
		if e != nil {
			t.Fatal(e)
		}
		var again Sidecar
		if e = json.Unmarshal(raw, &again); e != nil || !reflect.DeepEqual(out, again) {
			t.Fatal("JSON全値")
		}
	}
}

// TestLastZeroAndIndexNamespaces は不正Lastの失効と異なる連番を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。
func TestLastZeroAndIndexNamespaces(t *testing.T) {
	req := request(1, 965)
	s := req.Session.Start
	for i := range req.Rows {
		r := &req.Rows[i]
		if r.Board.Reference == "NK225" && r.Board.Time == s+305 {
			r.Board.Last = 0
		}
		if r.Board.Reference == "NK225" && r.Board.Time == s+315 {
			r.Board.Ask = r.Board.Bid
		}
	}
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	zero := 0
	for _, tr := range out.Trace {
		if tr.Kind == "raw" && tr.Identity.Market == "NK225" && tr.At == s+305 {
			zero++
			if tr.Identity.FeaturesIndex != nil || tr.Chart.Invalidated != s+305 {
				t.Fatal("Last0失効")
			}
		}
	}
	if zero != 1 || len(out.Rows) != 193 {
		t.Fatal("Last0除外")
	}
	for _, r := range out.Rows {
		if r.Scalar.Time > s+305 && r.Identity.AllIndex != *r.Identity.FeaturesIndex+1 {
			t.Fatal("連番混同")
		}
		if r.Scalar.Time == s+315 && (r.Scalar.QuoteOK || r.Current.Buy.OwnKnown) {
			t.Fatal("badBBOを既知化")
		}
	}
	badBar, goodBar := false, false
	for _, tr := range out.Trace {
		if tr.Kind == "publication" {
			p, er := Materialize(out, tr.Chart)
			if er != nil {
				t.Fatal(er)
			}
			if tr.At == s+360 {
				badBar = !p.Three.DataKnown
			}
			if tr.At == s+540 {
				goodBar = p.Three.DataKnown
			}
		}
	}
	if !badBar || !goodBar {
		t.Fatal("Last0後の足可用復帰")
	}
	if out.Grids[2].Current.SourceIndex == out.Grids[2].Chart.LastInput.Index {
		t.Fatal("別名前空間が同値へ改変")
	}
}

// TestIndependentPublicFeatures はCurrentとATRを別の公開Features運転へ結びます。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。Source/Actualは作りません。
func TestIndependentPublicFeatures(t *testing.T) {
	req := request(1, 980)
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	p, _ := strategy.ParametersForMethod("NK225", "Day", "D164_15")
	f, _ := strategy.NewFeatures(req.Session, map[string]float64{"NK225": 10, "TOPIX": .5}, p.Features)
	f.EnableResearch()
	rows, _ := prepare(req)
	candles := append([]CandleEvent{}, req.Candles...)
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })
	ci, ri := 0, 0
	for _, row := range rows {
		for ci < len(candles) && candles[ci].At <= row.Board.Time {
			c := candles[ci]
			if _, e = f.AddCandles(c.Reference, c.Interval, []strategy.Candle{c.Candle}, c.At); e != nil {
				t.Fatal(e)
			}
			ci++
		}
		o, e := f.OnBoard(row.Board)
		if e != nil {
			t.Fatal(e)
		}
		if o.Reference == "NK225" {
			if !reflect.DeepEqual(far82.ExtractCurrent(o, row.PhysicalLine), out.Rows[ri].Current) {
				t.Fatal("Current全値")
			}
			if o.E01.ATR != out.Rows[ri].Scalar.ATR || o.E01.ATRAvailable != out.Rows[ri].Scalar.ATRAvailable {
				t.Fatal("ATR公開")
			}
			ri++
		}
	}
	for _, r := range out.Rows {
		if r.Scalar.Time < req.Session.Start+960 && r.Scalar.ATR != 0 {
			t.Fatal("未公表ATR")
		}
	}
	if out.Rows[len(out.Rows)-1].Scalar.ATR <= 0 {
		t.Fatal("ATR公表不足")
	}
}

// TestSeedRollGapAndSeal は数値種と公開maskを別に扱います。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。
func TestSeedRollGapAndSeal(t *testing.T) {
	a := request(1, 7250)
	a.Grids = nil
	out, seed, e := Build(a, nil)
	if e != nil {
		t.Fatal(e)
	}
	end, _ := Materialize(out, out.Ending)
	if end.Three.BarEnd > a.Session.Start+7250 || end.Three.BarEnd == a.Session.Start+7380 {
		t.Fatal("Seal先締め")
	}
	b := request(-1, 400)
	delta := 8000.0
	oldStart := b.Session.Start
	b.Session.ID = "人工次場"
	b.Scene.ID = b.Session.ID
	b.Session.Start += delta
	b.Session.End += delta
	b.Scene.Start += delta
	b.Session.ForceClose += delta
	for i := range b.Rows {
		b.Rows[i].Board.Time += delta
		b.Rows[i].Board.Received += delta
	}
	for i := range b.Candles {
		b.Candles[i].At += delta
		b.Candles[i].Candle.Time += delta
	}
	b.Grids = []float64{oldStart + delta + 300}
	carried, _, e := Build(b, seed)
	if e != nil {
		t.Fatal(e)
	}
	if !carried.Grids[0].Chart.CarriedNumericSeed || carried.Rows[0].Current.SourceIndex != 0 || carried.Rows[0].Chart.HasLast == false {
		t.Fatal("継承/初期化")
	}
	before, _ := json.Marshal(carried)
	again, _, e := Build(b, seed)
	if e != nil {
		t.Fatal(e)
	}
	after, _ := json.Marshal(again)
	if string(before) != string(after) {
		t.Fatal("Seed共有改変")
	}
	b.Scene.Contract = "別限月"
	rolled, _, e := Build(b, seed)
	if e != nil || rolled.Grids[0].Chart.CarriedNumericSeed {
		t.Fatal("roll", e)
	}
	bad := b
	bad.Scene.Start = a.Session.Start + 100
	bad.Session.Start = bad.Scene.Start
	if _, _, e = Build(bad, seed); e == nil {
		t.Fatal("未来種")
	}
	gap := request(1, 600)
	gap.Rows = []Row{gap.Rows[0], gap.Rows[120]}
	gap.Grids = []float64{gap.Session.Start + 300, gap.Session.Start + 900}
	g, _, e := Build(gap, nil)
	if e != nil {
		t.Fatal(e)
	}
	if len(g.Grids) != 1 || len(g.SkippedGrids) != 1 {
		t.Fatal("EOF grid創作")
	}
}

// TestCloneAndCorruptions は入力共有と少数破損を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。
func TestCloneAndCorruptions(t *testing.T) {
	req := request(1, 965)
	before, _ := json.Marshal(req)
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	after, _ := json.Marshal(req)
	if string(before) != string(after) {
		t.Fatal("入力改変")
	}
	old := legacy(out)
	cases := []func(*oldtape.Tape){func(x *oldtape.Tape) { x.Events[0].Ordinal = 5 }, func(x *oldtape.Tape) { x.Events[0].Quote.Index++ }, func(x *oldtape.Tape) {
		for i := range x.Events {
			if x.Events[i].Kind == "grid" {
				x.Events[i].Context.Current.Short.Five.Speed++
				break
			}
		}
	}, func(x *oldtape.Tape) { x.Events = x.Events[:len(x.Events)-2] }}
	for i, mutate := range cases {
		x, _ := copyValue(old)
		mutate(&x)
		if _, e = BindLegacy(out, x); e == nil {
			t.Fatal("破損受理", i)
		}
	}
	first := out.Rows[0].Current.Buy.Windows
	second := out.Rows[1].Current.Buy.Windows
	first["手製変更"] = first["own5"]
	if _, ok := second["手製変更"]; ok {
		t.Fatal("Current map共有")
	}
	if _, ok := out.Grids[0].Current.Buy.Windows["手製変更"]; ok {
		t.Fatal("Grid map共有")
	}
	state := out.Rows[0].Chart
	p := out.Payloads[state.PayloadSHA]
	p.Chart.Technical.Close3++
	out.Payloads[state.PayloadSHA] = p
	if _, e = Materialize(out, state); e == nil {
		t.Fatal("辞書破損受理")
	}
}

// TestMetadataAndNewOutput は市場読取前の拒否と機械派生を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。実入力は読みません。
func TestMetadataAndNewOutput(t *testing.T) {
	source, e := os.ReadFile("../../scripts/FAR5分枠の順行反転と数量/input.go")
	if e != nil {
		t.Fatal(e)
	}
	derived, e := os.ReadFile("input.go")
	if e != nil {
		t.Fatal(e)
	}
	expected := string(source)
	if string(derived) != replacePackage(expected) {
		t.Fatal("reader本文差")
	}
	dir := t.TempDir()
	a := Arguments{Root: dir, Proof: filepath.Join(dir, "存在しない完了"), Allowed: "未読", Manifest: "未読", Index: "未読", Out: filepath.Join(dir, "新規"), Stage: "first2", Stop: "未読"}
	if RunFirst(a) == nil {
		t.Fatal("未固定受理")
	}
	if _, e = os.Stat(a.Out); !os.IsNotExist(e) {
		t.Fatal("guard前出力")
	}
	a.Out = dir
	if RunFirst(a) == nil {
		t.Fatal("既存出力")
	}
}

// TestTapeSourceRelativeBaseAndPreflight は台帳基準のpathと出力前Source検査を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。tempバイト列だけを読み、市場Tape/Raw/Nativeを読みません。
func TestTapeSourceRelativeBaseAndPreflight(t *testing.T) {
	dir := t.TempDir()
	indexDir := filepath.Join(dir, "study", "人工台帳")
	sourceDir := filepath.Join(dir, "work", "人工Tape")
	if e := os.MkdirAll(indexDir, 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.MkdirAll(sourceDir, 0700); e != nil {
		t.Fatal(e)
	}
	index := filepath.Join(indexDir, "index.json")
	source := filepath.Join(sourceDir, "tape.json.gz")
	if e := os.WriteFile(source, []byte("市場でないmetadata検査専用バイト列"), 0600); e != nil {
		t.Fatal(e)
	}
	h, e := digest(source)
	if e != nil {
		t.Fatal(e)
	}
	relative, e := filepath.Rel(indexDir, source)
	if e != nil {
		t.Fatal(e)
	}
	entry := TapeEntry{Session: "人工場", Path: relative, SHA: h}
	got, e := ResolveTapeSource(index, entry)
	if e != nil || got.Path != source {
		t.Fatal("台帳基準relative", e, got.Path)
	}
	absolute, e := ResolveTapeSource(index, TapeEntry{Session: "人工場", Path: source, SHA: h})
	if e != nil || absolute != got {
		t.Fatal("absolute", e)
	}
	if filepath.Clean(filepath.Join(dir, relative)) == source {
		t.Fatal("旧repo基準誤りを識別できない器具")
	}
	cases := []TapeEntry{{Session: "欠落", Path: "missing/tape.json.gz", SHA: h}, {Session: "指紋違い", Path: relative, SHA: "0000000000000000000000000000000000000000000000000000000000000000"}, {Session: "dir", Path: sourceDir, SHA: h}, {Session: "空path", SHA: h}}
	for _, bad := range cases {
		if _, e = ResolveTapeSource(index, bad); e == nil {
			t.Fatal("Source破損受理", bad.Session)
		}
	}
	if entry.Path != relative {
		t.Fatal("metadata入力改変")
	}
	out := filepath.Join(dir, "未作成出力")
	if _, e = os.Stat(out); !os.IsNotExist(e) {
		t.Fatal("Source検査が出力を作成")
	}
}

// fillPublic は公開型のすべての値欄を非ゼロ人工で埋めます。
//
// 引数: v(reflect.Value)は書換え可能な公開値です。
// 返り値: ありません。市場値や既知性の正当性の証拠には使いません。
func fillPublic(v reflect.Value) {
	switch v.Kind() {
	case reflect.Struct:
		for i := 0; i < v.NumField(); i++ {
			fillPublic(v.Field(i))
		}
	case reflect.String:
		v.SetString("人工型全欄")
	case reflect.Bool:
		v.SetBool(true)
	case reflect.Float64:
		v.SetFloat(123.25)
	case reflect.Int, reflect.Int64:
		v.SetInt(7)
	}
}

// TestAllPublicSnapshotFields は非ゼロ公開型全文を保存/復元します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。手製公開型であり市場公表の証明ではありません。
func TestAllPublicSnapshotFields(t *testing.T) {
	var s warm.Snapshot
	fillPublic(reflect.ValueOf(&s).Elem())
	out := Sidecar{Payloads: map[string]Payload{}}
	state, e := pack(s, out.Payloads)
	if e != nil {
		t.Fatal(e)
	}
	got, e := Materialize(out, state)
	if e != nil || !reflect.DeepEqual(s, got) {
		t.Fatal("全公開field復元", e)
	}
}

// TestSameClockPhysicalRows は同Timeの二原行を別連番のまま扱います。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。Gridへ同Timeのどちらの価格も先取りしません。
func TestSameClockPhysicalRows(t *testing.T) {
	req := request(1, 305)
	s := req.Session.Start
	next := []Row{}
	for _, r := range req.Rows {
		if r.Board.Reference == "NK225" && r.Board.Time > s+300 {
			r.PhysicalLine++
		}
		next = append(next, r)
		if r.Board.Reference == "NK225" && r.Board.Time == s+300 {
			extra := r
			extra.PhysicalLine++
			extra.Board.Last += 20
			extra.Board.Bid += 20
			extra.Board.Ask += 20
			next = append(next, extra)
		}
	}
	req.Rows = next
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	same := []RawContext{}
	for _, r := range out.Rows {
		if r.Scalar.Time == s+300 {
			same = append(same, r)
		}
	}
	if len(same) != 2 || same[0].Scalar.Index+1 != same[1].Scalar.Index || same[0].Scalar.SourceLine+1 != same[1].Scalar.SourceLine || out.Grids[0].Current.Time != s+295 {
		t.Fatal("同秒別原行")
	}
	if _, e = BindLegacy(out, legacy(out)); e != nil {
		t.Fatal(e)
	}
}

// TestDrainClockIsNotPublication は将来側のdrain上限を公表時計と分けます。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。未投入rawの価格をGridへ入れません。
func TestDrainClockIsNotPublication(t *testing.T) {
	req := request(1, 315)
	s := req.Session.Start
	kept := []Row{}
	for _, r := range req.Rows {
		if r.Board.Time == s+300 || r.Board.Time == s+305 {
			continue
		}
		kept = append(kept, r)
	}
	req.Rows = kept
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	g := out.Grids[0]
	if g.At != s+300 || g.Chart.At != s+300 || g.Chart.ObservedClock != s+310 || g.Current.Time != s+295 || g.Chart.LastInput.Time != s+295 {
		t.Fatal("drain/公表混同")
	}
}

// TestNightCurrentIncludesShort はNightでも元FeaturesのShort/E08を省略しません。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。Short成立や退出利益の証明ではありません。
func TestNightCurrentIncludesShort(t *testing.T) {
	req := request(-1, 965)
	req.Session.Kind = "Night"
	req.Session.ID = "人工Night"
	req.Scene.ID = req.Session.ID
	req.Session.USOpen = req.Session.Start + 3600
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	observed := 0
	for _, r := range out.Rows {
		if r.Current.Short.Time != r.Scalar.Time || r.Current.Night.Index != r.Scalar.Index {
			t.Fatal("Night当行出典")
		}
		if r.Current.Night.Band.Known {
			observed++
			if r.Current.Night.Band.Line != r.Scalar.Index || r.Current.Night.Band.Line == r.Scalar.SourceLine {
				t.Fatal("E08 Line名前空間")
			}
		}
	}
	if observed == 0 {
		t.Fatal("人工E08未生成")
	}
}

// TestCurrentCloneMatchesOldJSON はnil/空/非空mapを旧JSON経路の全型へ揃えます。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。値の除外や新しい採否条件を加えません。
func TestCurrentCloneMatchesOldJSON(t *testing.T) {
	for _, mode := range []string{"nil", "empty", "nonempty"} {
		c := far82.CurrentEvidence{}
		if mode != "nil" {
			c.Buy.Windows = map[string]far81.CurrentSupportWindow{}
			c.Sell.Windows = map[string]far81.CurrentSupportWindow{}
		}
		if mode == "nonempty" {
			c.Buy.Windows["own5"] = far81.CurrentSupportWindow{Known: true, CurrentAt: 300, EndpointAt: 295, Elapsed: 5, Value: 2}
			c.Sell.Windows["own5"] = c.Buy.Windows["own5"]
		}
		before, _ := json.Marshal(c)
		expected, e := copyValue(c)
		if e != nil {
			t.Fatal(e)
		}
		actual := copyCurrent(c)
		after, _ := json.Marshal(actual)
		if !reflect.DeepEqual(expected, actual) || string(before) != string(after) {
			t.Fatal("旧Current全型/Marshal差", mode)
		}
		if mode == "nonempty" {
			actual.Buy.Windows["追加"] = actual.Buy.Windows["own5"]
			if _, ok := c.Buy.Windows["追加"]; ok {
				t.Fatal("map共有")
			}
		} else if actual.Buy.Windows != nil || actual.Sell.Windows != nil {
			t.Fatal("空窓nil化")
		}
	}
	req := request(1, 305)
	for i := range req.Rows {
		if req.Rows[i].Board.Reference == "NK225" && req.Rows[i].Board.Time == req.Session.Start+295 {
			req.Rows[i].Board.Bid = req.Rows[i].Board.Ask
		}
	}
	out, _, e := Build(req, nil)
	if e != nil {
		t.Fatal(e)
	}
	g := out.Grids[0]
	expected, e := copyValue(g)
	if e != nil || !reflect.DeepEqual(expected, g) || g.Current.Buy.Windows != nil || g.Current.Sell.Windows != nil {
		t.Fatal("badBBO→Grid旧型互換", e)
	}
	if _, e = BindLegacy(out, legacy(out)); e != nil {
		t.Fatal(e)
	}
}

// TestAllowedMetadata は閉鎖metadataの54と不正stage集合を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。Native/Raw/CSV本文は読みません。
func TestAllowedMetadata(t *testing.T) {
	root, _ := filepath.Abs("../..")
	expected, _, e := Catalog(root, filepath.Join(root, filepath.FromSlash(Study100), "完了記録.json"))
	if e != nil {
		t.Fatal(e)
	}
	ids, e := Select(expected, expected, "first2")
	if e != nil || !reflect.DeepEqual(ids, []string{"2026-09-21_Day", "2026-09-21_Night"}) {
		t.Fatal("first2", e)
	}
	if ids, e = Select(expected, expected, "full54"); e != nil || len(ids) != 54 {
		t.Fatal("54", e)
	}
	bad, _ := copyValue(expected)
	bad.Entries = bad.Entries[:53]
	if _, e = Select(bad, expected, "first2"); e == nil {
		t.Fatal("53受理")
	}
	bad, _ = copyValue(expected)
	bad.Entries[1] = bad.Entries[0]
	if _, e = Select(bad, expected, "full54"); e == nil {
		t.Fatal("重複受理")
	}
	if _, e = Select(expected, expected, "未許可"); e == nil {
		t.Fatal("stage受理")
	}
}

// replacePackage は派生許可差をpackage1箇所だけへ限定します。
//
// 引数: s(string)は元reader全文です。
// 返り値: stringはpackage置換だけの派生本文です。
func replacePackage(s string) string {
	for i := 0; i+len("package minichart") <= len(s); i++ {
		if s[i:i+len("package minichart")] == "package minichart" {
			return s[:i] + "package continuous101" + s[i+len("package minichart"):]
		}
	}
	return s
}

// TestExportArtificial は明示env時だけ人工の公開型を新規保存します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。市場やSourceは読みません。
func TestExportArtificial(t *testing.T) {
	dir := os.Getenv("CONTINUOUS101_ARTIFICIAL")
	if dir == "" {
		t.Skip("人工export未指定")
	}
	if e := os.Mkdir(dir, 0700); e != nil {
		t.Fatal(e)
	}
	for _, side := range []int{1, -1} {
		req := request(side, 965)
		out, _, e := Build(req, nil)
		if e != nil {
			t.Fatal(e)
		}
		old := legacy(out)
		match, e := BindLegacy(out, old)
		if e != nil {
			t.Fatal(e)
		}
		var buffer bytes.Buffer
		header, _, streamMatch, stats, e := WriteStream(req, nil, old, &buffer, Budget{0, 10000})
		if e != nil {
			t.Fatal(e)
		}
		records, e := decodeRecords(buffer.Bytes())
		if e != nil {
			t.Fatal(e)
		}
		value := map[string]any{"scope": "手製公開型・実Raw/Source/金融未測定", "request": req, "output": out, "legacy_artificial": old, "legacy_match": match, "stream_header": header, "stream_records": records, "stream_match": streamMatch, "stream_stats": stats}
		if e = saveNew(filepath.Join(dir, fmtName(side)), value, false); e != nil {
			t.Fatal(e)
		}
	}
}

// decodeRecords は人工のJSONLを公開Record型へ戻します。
//
// 引数: raw([]byte)は人工の逐次出力です。
// 返り値: []Record/errorは全record又はJSON不正です。
func decodeRecords(raw []byte) ([]Record, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	out := []Record{}
	for {
		var r Record
		e := dec.Decode(&r)
		if e == io.EOF {
			return out, nil
		}
		if e != nil {
			return nil, e
		}
		out = append(out, r)
	}
}

// TestStreamingMatchesMaterialized は同loopのstreamと人工Buildを全値比較します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。資源上限は売買条件ではありません。
func TestStreamingMatchesMaterialized(t *testing.T) {
	for _, side := range []int{1, -1} {
		req := request(side, 965)
		s := req.Session.Start
		for i := range req.Rows {
			if req.Rows[i].Board.Reference == "NK225" && req.Rows[i].Board.Time == s+305 {
				req.Rows[i].Board.Last = 0
			}
		}
		full, _, e := Build(req, nil)
		if e != nil {
			t.Fatal(e)
		}
		old := legacy(full)
		var buffer bytes.Buffer
		header, _, match, stats, e := WriteStream(req, nil, old, &buffer, Budget{0, 10000})
		if e != nil {
			t.Fatal(e)
		}
		if !header.Streamed || len(header.Rows)+len(header.Trace) != 0 || stats.Rows != len(full.Rows) || stats.Records != len(full.Trace) || match.Quotes != len(full.Rows) {
			t.Fatal("stream保持/件数")
		}
		records, e := decodeRecords(buffer.Bytes())
		if e != nil {
			t.Fatal(e)
		}
		reassembled := header
		reassembled.Streamed = false
		reassembled.LegacySHA = ""
		reassembled.Bindings = nil
		reassembled.Rows = []RawContext{}
		reassembled.Trace = []Trace{}
		for _, r := range records {
			if r.Kind == "row" {
				if r.Row == nil || r.TapeOrdinal <= 0 {
					t.Fatal("raw結合")
				}
				x := *r.Row
				reassembled.Rows = append(reassembled.Rows, x)
				id := x.Identity
				reassembled.Trace = append(reassembled.Trace, Trace{Kind: "raw", At: x.Scalar.Time, Identity: &id, Chart: x.Chart})
				for _, ref := range x.Recent3 {
					if _, e = Materialize(header, ref); e != nil {
						t.Fatal("Recent3参照", e)
					}
				}
			} else {
				reassembled.Trace = append(reassembled.Trace, *r.Control)
			}
		}
		if !reflect.DeepEqual(full, reassembled) {
			t.Fatal("stream全公開値差")
		}
		if _, _, _, _, e = WriteStream(req, nil, old, io.Discard, Budget{0, 1}); e == nil {
			t.Fatal("資源上限無視")
		}
	}
}

// fmtName は人工鏡像名を返します。
//
// 引数: side(int)は買売符号です。
// 返り値: stringは新規人工ファイル名です。
func fmtName(side int) string {
	if side == 1 {
		return "買い.json"
	}
	return "売り.json"
}
