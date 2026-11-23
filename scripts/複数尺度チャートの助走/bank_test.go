package chartwarmup

import (
	"fmt"
	"math"
	"reflect"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

const sceneStart = 100000.0

// makeBank は市場へ接続しない人工bankを初期化します。
//
// 引数: t(*testing.T)、start(float64)、contract(string)、seed(*Seed)です。
// 返り値: *Bankは独立した試験対象です。
func makeBank(t *testing.T, start float64, contract string, seed *Seed) *Bank {
	t.Helper()
	b, err := New(Scene{ID: "人工場", Contract: contract, Start: start}, seed)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// quote は有限の人工Lastと原行を作ります。
//
// 引数: at/price(float64)、index(int64)です。
// 返り値: QuoteのValidはLast可用性を表します。
func quote(at, price float64, index int64) Quote {
	return Quote{Time: at, Last: price, Bid: price - 5, Ask: price + 5, Index: index, Line: index + 1, Valid: true}
}

// mustStep は正常入力の失敗を直ちに検出します。
//
// 引数: t(*testing.T)、b(*Bank)、q(Quote)、grids(...float64)です。
// 返り値: Batchは当操作の公開値です。
func mustStep(t *testing.T, b *Bank, q Quote, grids ...float64) Batch {
	t.Helper()
	got, err := b.Step(q, grids)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

// warm は実データを使わず、各3分足へ2原行を与えて助走します。
//
// 引数: t(*testing.T)、b(*Bank)、n(int)、mirror(bool)です。
// 返り値: ありません。15分足も同じ公開timerから生成します。
func warm(t *testing.T, b *Bank, n int, mirror bool) {
	t.Helper()
	for i := 0; i < n; i++ {
		p := 10000 + float64(i)*2 + 20*math.Sin(float64(i)*0.7)
		p2 := p + 7*math.Cos(float64(i)*0.3)
		if mirror {
			p, p2 = 40000-p, 40000-p2
		}
		base := b.scene.Start + float64(i)*180
		mustStep(t, b, quote(base+10, p, int64(i*2)))
		mustStep(t, b, quote(base+170, p2, int64(i*2+1)))
		if _, err := b.AdvanceObserved(base+180, nil); err != nil {
			t.Fatal(err)
		}
	}
}

// TestWarmupAndFixedAPI は助走不足と固定80/82の全公開値同値を検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。独自の指標式を期待値に使いません。
func TestWarmupAndFixedAPI(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	base := far80.NewTechnicalBank()
	chart := far82.NewChartBank(base)
	chart.BeginSession(sceneStart)
	for i := 0; i < 110; i++ {
		p := 10000 + float64(i)*2 + 20*math.Sin(float64(i)*0.7)
		for j, off := range []float64{10, 170} {
			price := p
			if j == 1 {
				price += 7 * math.Cos(float64(i)*0.3)
			}
			q := quote(sceneStart+float64(i)*180+off, price, int64(i*2+j))
			mustStep(t, b, q)
			if err := chart.Observe(q); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(b.Snapshot().Chart, chart.View()) {
				t.Fatalf("原行%dで固定器の値が相違", q.Line)
			}
		}
		at := sceneStart + float64(i+1)*180
		if _, err := b.AdvanceObserved(at, nil); err != nil {
			t.Fatal(err)
		}
		if err := chart.Advance(at); err != nil {
			t.Fatal(err)
		}
		v := b.Snapshot()
		if !reflect.DeepEqual(v.Chart, chart.View()) {
			t.Fatalf("足%dで固定器の値が相違", i)
		}
		if i == 0 && (v.Chart.Technical.ATRKnown || v.Chart.Technical.TrendKnown || v.Chart.Previous3Known) {
			t.Fatal("助走不足を既知にした")
		}
	}
	v := b.Snapshot()
	if !v.Chart.Technical.TrendKnown || !v.Chart.Technical.ATRKnown || !v.Chart.Previous3Known {
		t.Fatal("十分な人工助走が公開されない")
	}
	if v.Three.Rows != 2 || v.Fifteen.Rows != 10 || !v.Three.DataKnown || !v.Fifteen.DataKnown {
		t.Fatal("足の出典数が相違")
	}
}

// TestTimerGridRaw は同時計の当原行が足・gridへ混入しないことを確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTimerGridRaw(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	mustStep(t, b, quote(sceneStart+10, 100, 0))
	mustStep(t, b, quote(sceneStart+179, 110, 1))
	got := mustStep(t, b, quote(sceneStart+180, 999, 2), sceneStart+180)
	if len(got.Publications) != 1 || len(got.Grids) != 1 {
		t.Fatal("timer/grid数が相違")
	}
	g := got.Grids[0]
	if g.Chart.Technical.Close3 != 110 || g.Three.LastSource.Index != 1 || g.LastInput.Index != 1 || g.At != sceneStart+180 {
		t.Fatal("gridが同原行を先取り")
	}
	if g.Three.AvailableAt != sceneStart+180 || g.Three.BarEnd != sceneStart+180 || g.Three.ObservedClock != sceneStart+180 {
		t.Fatal("公開出典が相違")
	}
	if got.After.LastInput.Index != 2 || got.After.Chart.Technical.Close3 != 110 {
		t.Fatal("rawの形成足への追加が相違")
	}
	got2, err := b.AdvanceObserved(sceneStart+360, []float64{sceneStart + 360})
	if err != nil {
		t.Fatal(err)
	}
	if got2.Grids[0].Chart.Technical.Close3 != 999 || got2.Grids[0].Three.LastSource.Index != 2 {
		t.Fatal("次足へ当行が入らない")
	}
}

// TestFifteenTimerRaw は15分の最終出典も同時計rawより前に固定します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。3分と15分を別の出典として検査します。
func TestFifteenTimerRaw(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	for i := 0; i < 5; i++ {
		mustStep(t, b, quote(sceneStart+float64(i)*180+10, 100+float64(i)*10, int64(i)))
	}
	got := mustStep(t, b, quote(sceneStart+900, 9999, 5), sceneStart+900)
	if len(got.Publications) != 1 || !got.Publications[0].Fifteen || !got.Publications[0].Three {
		t.Fatal("同時計3/15分timerの更新が相違")
	}
	g := got.Grids[0]
	if g.Fifteen.BarEnd != sceneStart+900 || g.Fifteen.AvailableAt != sceneStart+900 || g.Fifteen.Rows != 5 || !g.Fifteen.DataKnown || g.Fifteen.LastSource.Index != 4 {
		t.Fatal("15分出典が同時計rawを含む")
	}
	if g.Three.Rows != 1 || g.Three.LastSource.Index != 4 || g.Chart.Technical.Close3 != 140 || g.LastInput.Index != 4 || got.After.LastInput.Index != 5 {
		t.Fatal("3分/15分/grid/rawの各出典が混同")
	}
}

// TestInterleavedGrids は遅れて受け取ったclockを過去gridの価格へ混ぜません。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。observed_clockは今回drainを許した上限です。
func TestInterleavedGrids(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	mustStep(t, b, quote(sceneStart+10, 100, 0))
	got := mustStep(t, b, quote(sceneStart+600, 900, 1), sceneStart+300, sceneStart+540)
	if len(got.Publications) != 3 || len(got.Grids) != 2 {
		t.Fatal("timerをgrid別にmergeしない")
	}
	if got.Grids[0].Chart.Technical.Bar3End != sceneStart+180 || got.Grids[0].Chart.Technical.Close3 != 100 {
		t.Fatal("後のtimerを早いgridへ混入")
	}
	if got.Grids[0].ObservedClock != sceneStart+600 || got.Grids[0].At != sceneStart+300 {
		t.Fatal("判断clockと観測上限を混同")
	}
	if got.Grids[1].Three.DataKnown || got.Grids[1].Three.Rows != 0 || got.Grids[1].Three.HasLastSource {
		t.Fatal("欠足を横ばいで補完")
	}
}

// TestSealAndSameContract は未完足を締めず数値助走だけを次場へ渡します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。場外横ばい・前場公開maskの継承を拒否します。
func TestSealAndSameContract(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	warm(t, b, 110, false)
	completed := b.Snapshot()
	cleanSeed, _, err := b.Seal()
	if err != nil {
		t.Fatal(err)
	}
	clean := makeBank(t, sceneStart+30000, "202612", &cleanSeed)
	b2 := makeBank(t, sceneStart, "202612", nil)
	warm(t, b2, 110, false)
	mustStep(t, b2, quote(sceneStart+110*180+17, 99999, 220))
	before := b2.Snapshot()
	seed, sealed, err := b2.Seal()
	if err != nil {
		t.Fatal(err)
	}
	if sealed.Chart != before.Chart || sealed.Three != before.Three || sealed.Fifteen != before.Fifteen || sealed.At != before.At {
		t.Fatal("Sealが形成足を先締め")
	}
	if sealed.Chart.Technical.Bar3End != completed.Chart.Technical.Bar3End {
		t.Fatal("未完足が種へ公開")
	}
	next := makeBank(t, sceneStart+30000, "202612", &seed)
	v := next.Snapshot()
	if !v.CarriedNumericSeed || v.HasObservedClock || v.HasLastInput || v.Chart.Previous3Known || v.Chart.Technical.TrendKnown || v.Chart.Technical.Bar3End != 0 || v.Three.BarEnd != 0 || v.Fifteen.BarEnd != 0 {
		t.Fatal("前場のmask/追跡/出典が残る")
	}
	for _, x := range []*Bank{clean, next} {
		mustStep(t, x, quote(x.scene.Start+1, 10500, 0))
		if _, err := x.AdvanceObserved(x.scene.Start+180, nil); err != nil {
			t.Fatal(err)
		}
	}
	if !reflect.DeepEqual(next.Snapshot().Chart, clean.Snapshot().Chart) {
		t.Fatal("前場未完価格が次場へ混入")
	}
	if !next.Snapshot().Chart.Technical.ATRKnown || next.Snapshot().Chart.Previous3Known {
		t.Fatal("数値種又は前足resetが相違")
	}
	if _, err := next.AdvanceObserved(next.scene.Start+900, nil); err != nil {
		t.Fatal(err)
	}
	if next.Snapshot().Chart.Technical.TrendKnown {
		t.Fatal("場内の欠足を無視")
	}
}

// TestRollAndIndependentSuccessors はroll初期化と同種2後継の参照非共有を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestRollAndIndependentSuccessors(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	warm(t, b, 110, false)
	seed, _, err := b.Seal()
	if err != nil {
		t.Fatal(err)
	}
	a := makeBank(t, sceneStart+30000, "202612", &seed)
	other := makeBank(t, sceneStart+30000, "202612", &seed)
	otherBefore := other.Snapshot()
	mustStep(t, a, quote(a.scene.Start+10, 15000, 0))
	if _, err := a.AdvanceObserved(a.scene.Start+180, nil); err != nil {
		t.Fatal(err)
	}
	if other.Snapshot() != otherBefore {
		t.Fatal("同種の後継が共有状態を更新")
	}
	control := makeBank(t, sceneStart+30000, "202612", &seed)
	for _, x := range []*Bank{other, control} {
		mustStep(t, x, quote(x.scene.Start+10, 12000, 0))
		if _, err := x.AdvanceObserved(x.scene.Start+180, nil); err != nil {
			t.Fatal(err)
		}
	}
	if other.Snapshot() != control.Snapshot() {
		t.Fatal("数値器が浅い共有copy")
	}
	roll := makeBank(t, sceneStart+30000, "202703", &seed)
	fresh := makeBank(t, sceneStart+30000, "202703", nil)
	for _, x := range []*Bank{roll, fresh} {
		mustStep(t, x, quote(x.scene.Start+10, 12000, 0))
		if _, err := x.AdvanceObserved(x.scene.Start+180, nil); err != nil {
			t.Fatal(err)
		}
	}
	if roll.Snapshot() != fresh.Snapshot() || roll.Snapshot().CarriedNumericSeed || roll.Snapshot().Chart.Technical.ATRKnown {
		t.Fatal("限月交代で数値種が残る")
	}
}

// TestCopiesAndReferenceGuard は返却値の変更とnil以外の参照持越しを隔離します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestCopiesAndReferenceGuard(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	mustStep(t, b, quote(sceneStart+10, 100, 0))
	got, err := b.AdvanceObserved(sceneStart+180, []float64{sceneStart + 180})
	if err != nil {
		t.Fatal(err)
	}
	before := b.Snapshot()
	got.Grids[0].Chart.Technical.Close3 = 9999
	got.Publications[0].Snapshot.Three.LastSource.Last = 9999
	got.After.Scene.Contract = "別限月"
	if b.Snapshot() != before {
		t.Fatal("返却slice/valueの変更が作用")
	}
	if !referenceFree(reflect.ValueOf(*b.numeric)) || !referenceFree(reflect.ValueOf(struct{ Err error }{})) {
		t.Fatal("nil errorを共有参照と誤判定")
	}
	for _, v := range []any{struct{ Err error }{fmt.Errorf("人工error")}, []int{1}, map[string]int{"x": 1}, &struct{ N int }{1}} {
		if referenceFree(reflect.ValueOf(v)) {
			t.Fatalf("可変参照%Tを許可", v)
		}
	}
}

// TestBadLastAndBBOSeparation はLast品質とBBO品質を同一視しません。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。Last不良は同終端timerの後に履歴を未知へします。
func TestBadLastAndBBOSeparation(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	warm(t, b, 110, false)
	q := quote(sceneStart+110*180+10, 10500, 220)
	q.Bid, q.Ask = 10600, 10400
	mustStep(t, b, q)
	if !b.Snapshot().Chart.Technical.ATRKnown {
		t.Fatal("BBO異常だけで技法を未知化")
	}
	q = quote(sceneStart+111*180, 0, 221)
	q.Valid = false
	got := mustStep(t, b, q, sceneStart+111*180)
	if !got.Grids[0].Chart.Technical.ATRKnown || got.After.Chart.Technical.ATRKnown || got.After.Chart.Previous3Known || got.After.InvalidatedAt != q.Time {
		t.Fatal("同終端Last不良の公開順が相違")
	}
	mustStep(t, b, quote(q.Time, 10510, 222))
	if b.Snapshot().Chart.Technical.ATRKnown {
		t.Fatal("同秒後行で履歴が復活")
	}
	got2, err := b.AdvanceObserved(sceneStart+112*180, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got2.After.Three.DataKnown || got2.After.Three.Rows != 2 || got2.After.InvalidatedAt != 0 {
		t.Fatal("不良形成足/一時印の仕様が相違")
	}
}

// TestMirror は買売鏡像で公開値の方向・値幅を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。売買判断は実装せず、指標の鏡像だけを検査します。
func TestMirror(t *testing.T) {
	a := makeBank(t, sceneStart, "202612", nil)
	z := makeBank(t, sceneStart, "202612", nil)
	warm(t, a, 110, false)
	warm(t, z, 110, true)
	x, y := a.Snapshot().Chart, z.Snapshot().Chart
	if x.Technical.TrendKnown != y.Technical.TrendKnown || x.Technical.ReversalKnown != y.Technical.ReversalKnown || x.Previous3Known != y.Previous3Known {
		t.Fatal("鏡像の既知性が相違")
	}
	for name, pair := range map[string][2]float64{
		"EMA8_3": {x.Technical.EMA8_3 + y.Technical.EMA8_3, 40000}, "EMA21_3": {x.Technical.EMA21_3 + y.Technical.EMA21_3, 40000},
		"EMA8_15": {x.Technical.EMA8_15 + y.Technical.EMA8_15, 40000}, "EMA21_15": {x.Technical.EMA21_15 + y.Technical.EMA21_15, 40000},
		"Close": {x.Technical.Close3 + y.Technical.Close3, 40000}, "RSI": {x.Technical.RSI3 + y.Technical.RSI3, 100},
		"Hist": {x.Technical.Histogram3 + y.Technical.Histogram3, 0}, "TR": {x.Technical.TR3, y.Technical.TR3}, "ATR": {x.Technical.ATR3, y.Technical.ATR3},
		"前Close": {x.PreviousClose3 + y.PreviousClose3, 40000}, "前EMA8": {x.PreviousEMA8_3 + y.PreviousEMA8_3, 40000},
	} {
		if math.Abs(pair[0]-pair[1]) > 1e-8 {
			t.Fatalf("%s鏡像: %.12f != %.12f", name, pair[0], pair[1])
		}
	}
}

// TestInvalidClockAndSource は不正入力拒否時の状態不変を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestInvalidClockAndSource(t *testing.T) {
	b := makeBank(t, sceneStart, "202612", nil)
	mustStep(t, b, quote(sceneStart+10, 100, 0))
	cases := []struct {
		name  string
		q     Quote
		grids []float64
	}{
		{"未来grid", quote(sceneStart+20, 101, 1), []float64{sceneStart + 21}},
		{"raw後同秒grid", quote(sceneStart+20, 101, 1), []float64{sceneStart + 10}},
		{"重複grid", quote(sceneStart+20, 101, 1), []float64{sceneStart + 15, sceneStart + 15}},
		{"grid後退", quote(sceneStart+20, 101, 1), []float64{sceneStart + 19, sceneStart + 18}},
		{"時計後退", quote(sceneStart+9, 101, 1), nil},
		{"Index重複", quote(sceneStart+20, 101, 0), nil},
		{"Line後退", Quote{Time: sceneStart + 20, Last: 101, Index: 1, Line: 1, Valid: true}, nil},
		{"NaN", quote(sceneStart+20, math.NaN(), 1), nil},
		{"無限clock", quote(math.Inf(1), 101, 1), nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			before := b.Snapshot()
			if _, err := b.Step(c.q, c.grids); err == nil {
				t.Fatal("不正入力を許可")
			}
			if b.Snapshot() != before {
				t.Fatal("拒否時に状態を更新")
			}
		})
	}
	if _, err := b.publish(sceneStart+180, sceneStart+179); err == nil {
		t.Fatal("observedを越えて公開")
	}
}

// TestSeedAndSceneValidation はsealed/開始時計/限月境界の不正を拒否します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestSeedAndSceneValidation(t *testing.T) {
	for _, s := range []Scene{{}, {ID: "x", Contract: "c", Start: math.NaN()}, {ID: "x", Contract: "c", Start: 0}} {
		if _, err := New(s, nil); err == nil {
			t.Fatal("不正Sceneを許可")
		}
	}
	if _, err := New(Scene{"次", "c", sceneStart + 1}, &Seed{}); err == nil {
		t.Fatal("未sealed種を許可")
	}
	b := makeBank(t, sceneStart, "c", nil)
	mustStep(t, b, quote(sceneStart+200, 100, 0))
	seed, _, err := b.Seal()
	if err != nil {
		t.Fatal(err)
	}
	for _, at := range []float64{sceneStart, sceneStart + 199} {
		if _, err := New(Scene{"次", "別限月", at}, &seed); err == nil {
			t.Fatal("種より過去のSceneをrollで許可")
		}
	}
	if _, err := New(Scene{"次", "c", sceneStart + 200}, &seed); err != nil {
		t.Fatal("observedと同時計の次場開始を不正扱い", err)
	}
	if _, _, err := b.Seal(); err == nil {
		t.Fatal("二重Sealを許可")
	}
	if _, err := b.AdvanceObserved(sceneStart+201, nil); err == nil {
		t.Fatal("sealed後に更新")
	}
	if _, err := b.Step(quote(sceneStart+201, 100, 1), nil); err == nil {
		t.Fatal("sealed後にraw追加")
	}
}

// TestEmptySceneAndLongGap は無入力Sealと休場gapを価格なしで扱います。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestEmptySceneAndLongGap(t *testing.T) {
	b := makeBank(t, sceneStart, "c", nil)
	seed, s, err := b.Seal()
	if err != nil {
		t.Fatal(err)
	}
	if s.HasObservedClock || s.Three.BarEnd != 0 || s.Chart.Technical.Bar3End != 0 {
		t.Fatal("無入力場の足を合成")
	}
	next := makeBank(t, sceneStart+3*86400, "c", &seed)
	if next.Snapshot().Chart.Technical.Bar3End != 0 {
		t.Fatal("休場中の足を合成")
	}
	mustStep(t, next, quote(next.scene.Start+1, 100, 0))
	got, err := next.AdvanceObserved(next.scene.Start+900, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Publications) != 5 || !got.Publications[0].Snapshot.Three.DataKnown {
		t.Fatal("当場の最初の入力を失った")
	}
	for _, p := range got.Publications[1:] {
		if p.Snapshot.Three.DataKnown || p.Snapshot.Three.Rows != 0 {
			t.Fatal("場内欠足を補完")
		}
	}
	if got.After.Chart.Technical.TrendKnown || got.After.Chart.Technical.ATRKnown {
		t.Fatal("欠足でも助走既知")
	}
}
