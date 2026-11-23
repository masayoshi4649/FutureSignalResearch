package far80

import (
	"math"
	"reflect"
	"testing"
)

// closeEnoughTechnical は人工の独立算術期待値へ有限誤差内で照合します。
//
// 引数: t(*testing.T)は検査、actual/expected(float64)は実値/期待値です。
// 返り値: ありません。不一致又は非有限値でテストを失敗させます。
func closeEnoughTechnical(t *testing.T, actual, expected float64) {
	t.Helper()
	if !finiteTechnical(actual) || math.Abs(actual-expected) > 1e-9 {
		t.Fatalf("数値が不一致: 実値=%v 期待=%v", actual, expected)
	}
}

// fakeTechnicalQuote は市場と無関係な正常な当時気配を作ります。
//
// 引数: at/last(float64)は人工時計/Lastです。
// 返り値: Quoteは呼出ごとに独立した値です。
func fakeTechnicalQuote(at, last float64) Quote {
	return Quote{Time: at, Line: int64(at + 1), Index: int64(at + 1), Last: last, Bid: last - 1, Ask: last + 1, Valid: true}
}

// warmTechnical は人工の連続足を技法器へ供給します。
//
// 引数: t(*testing.T)は検査、bank(*TechnicalBank)は開始済み器、count(int)は3分足数です。
// 返り値: float64は最後に閉じた足の終端です。市場・元ソースを読みません。
func warmTechnical(t *testing.T, bank *TechnicalBank, count int) float64 {
	t.Helper()
	for i := 0; i < count; i++ {
		price := 1000 + float64(i)*0.25 + 8*math.Sin(float64(i)/7)
		if err := bank.Observe(fakeTechnicalQuote(float64(i)*180, price)); err != nil {
			t.Fatal(err)
		}
	}
	at := float64(count) * 180
	if err := bank.Advance(at); err != nil {
		t.Fatal(err)
	}
	return at
}

// TestTechnicalInitialValues はEMA種・RSI・MACD前値・TR/ATRを独立算術で確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。人工値だけを使用します。
func TestTechnicalInitialValues(t *testing.T) {
	var series technicalSeries
	series.reset()
	for i := 1; i <= 35; i++ {
		value := float64(i)
		series.closeBar(value, value, value, value*180)
		if i == 7 && series.ema8.known {
			t.Fatal("EMA8が準備前に既知")
		}
		if i == 8 {
			closeEnoughTechnical(t, series.ema8.value, 4.5)
		}
		if i == 9 {
			closeEnoughTechnical(t, series.ema8.value, 5.5)
		}
		if i == 14 && series.rsiKnown {
			t.Fatal("14差分の前にRSIが既知")
		}
		if i == 15 {
			closeEnoughTechnical(t, series.rsi, 100)
			if series.previousRSIKnown {
				t.Fatal("最初のRSIに前値を補完")
			}
		}
		if i == 21 {
			closeEnoughTechnical(t, series.ema21.value, 11)
		}
		if i == 33 && series.histKnown {
			t.Fatal("MACD signal9の準備前にヒストグラムが既知")
		}
		if i == 34 && (!series.histKnown || series.previousHistKnown) {
			t.Fatal("最初のヒストグラムのmaskが不正")
		}
	}
	if !series.previousHistKnown {
		t.Fatal("35足目でもヒストグラム前値が未知")
	}
	closeEnoughTechnical(t, series.histogram, 0)
	// ----------------------------------------
	// 横ばい・下落と、Wilder初期平均からの一歩を手計算します。
	for _, value := range []float64{0, -1} {
		series.reset()
		for i := 0; i <= 14; i++ {
			price := 100 + float64(i)*value
			series.closeBar(price, price, price, float64(i+1)*180)
		}
		want := 0.0
		if value == 0 {
			want = 50
		}
		closeEnoughTechnical(t, series.rsi, want)
	}
	series.reset()
	for i := 1; i <= 15; i++ {
		value := float64(i)
		series.closeBar(value, value, value, float64(i)*180)
	}
	series.closeBar(14, 14, 14, 16*180)
	closeEnoughTechnical(t, series.rsi, 100-100.0/14)
	series.reset()
	for i := 0; i < 14; i++ {
		series.closeBar(101, 99, 100, float64(i+1)*180)
	}
	closeEnoughTechnical(t, series.atr.value, 2)
	series.closeBar(106, 104, 105, 15*180)
	closeEnoughTechnical(t, series.tr, 6)
	closeEnoughTechnical(t, series.previousATR, 2)
	closeEnoughTechnical(t, series.atr.value, 32.0/14)
}

// TestTechnicalHalfOpen は終端の先行確定とtick境界・入力不変を確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。未来のtickで過去の終値を変えません。
func TestTechnicalHalfOpen(t *testing.T) {
	bank := NewTechnicalBank()
	bank.BeginSession(0)
	for _, q := range []Quote{fakeTechnicalQuote(0, 100), fakeTechnicalQuote(179, 110)} {
		if q.Time == 0 {
			// Lastチャートは交差BBOでもLast利用可ならその価格を使います。
			q.Bid, q.Ask = 105, 95
		}
		before := q
		if err := bank.Observe(q); err != nil {
			t.Fatal(err)
		}
		if q != before {
			t.Fatal("元気配が変更された")
		}
	}
	if bank.View().Bar3End != 0 {
		t.Fatal("足終端前に公開")
	}
	if err := bank.Advance(180); err != nil {
		t.Fatal(err)
	}
	before := bank.View()
	closeEnoughTechnical(t, before.Close3, 110)
	closeEnoughTechnical(t, before.TR3, 10)
	if err := bank.Observe(fakeTechnicalQuote(180, 90)); err != nil {
		t.Fatal(err)
	}
	if bank.View() != before || bank.three.open != 90 {
		t.Fatal("終端tickが前足又は不正openへ混入")
	}
	if err := bank.Advance(360); err != nil {
		t.Fatal(err)
	}
	closeEnoughTechnical(t, bank.View().Close3, 90)
	closeEnoughTechnical(t, bank.View().TR3, 20)
	if before.Close3 != 110 {
		t.Fatal("公開済みViewが後続観測で変更")
	}
	if err := bank.Advance(900); err != nil {
		t.Fatal(err)
	}
	if bank.View().ATRKnown || bank.View().Bar3End != 900 || bank.View().Bar15End != 900 {
		t.Fatal("当場空足の未知又は15分境界が不正")
	}
	closeEnoughTechnical(t, bank.series15.close, 90)
	closeEnoughTechnical(t, bank.series15.tr, 20)
}

// TestTechnicalUnknownAndCarry は欠足・不良resetと場外非補完の数値carryを確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。市場を読みません。
func TestTechnicalUnknownAndCarry(t *testing.T) {
	bank := NewTechnicalBank()
	bank.BeginSession(0)
	at := warmTechnical(t, bank, 110)
	if v := bank.View(); !v.TrendKnown || !v.ReversalKnown || !v.SpikeKnown || !v.ATRKnown || !v.ExitKnown {
		t.Fatal("十分な人工履歴で未準備")
	}
	count := bank.series3.ema8.count
	value := bank.series3.ema8.value
	bank.BeginSession(at + 100000)
	if bank.View() != (TechnicalView{}) || bank.series3.ema8.count != count || bank.series3.ema8.value != value {
		t.Fatal("場外で架空足又は数値種の破棄")
	}
	if err := bank.Observe(fakeTechnicalQuote(at+100000, 1100)); err != nil {
		t.Fatal(err)
	}
	if err := bank.Advance(at + 100180); err != nil {
		t.Fatal(err)
	}
	if !bank.View().ATRKnown || !bank.View().ExitKnown || bank.View().TrendKnown {
		t.Fatal("新場3分だけの公開maskが不正")
	}
	bad := fakeTechnicalQuote(at+100181, 1101)
	bad.Valid = false
	if err := bank.Observe(bad); err != nil {
		t.Fatal(err)
	}
	if v := bank.View(); v.TrendKnown || v.ReversalKnown || v.ExitKnown || v.SpikeKnown || v.ATRKnown {
		t.Fatal("Last利用不可を未知へ戻していない")
	}
	if err := bank.Observe(fakeTechnicalQuote(at+100182, 1102)); err != nil {
		t.Fatal(err)
	}
	if err := bank.Advance(at + 100360); err != nil {
		t.Fatal(err)
	}
	if bank.View().ATRKnown || bank.series3.ema8.count != 0 {
		t.Fatal("不良を挟んだ形成足を有効へ戻した")
	}
	for _, last := range []float64{0, -1, math.NaN(), math.Inf(1)} {
		q := fakeTechnicalQuote(at+100361, last)
		if err := bank.Observe(q); err != nil || bank.View().ATRKnown {
			t.Fatal("不正Lastを0補完せず未知にする必要")
		}
	}
}

// TestTechnicalClockRejection は時計異常を状態変更前に拒否します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。
func TestTechnicalClockRejection(t *testing.T) {
	bank := NewTechnicalBank()
	if bank.Advance(0) == nil {
		t.Fatal("未開始を受理")
	}
	bank.BeginSession(math.NaN())
	if bank.Observe(fakeTechnicalQuote(0, 100)) == nil {
		t.Fatal("不正な場開始を受理")
	}
	bank.BeginSession(100)
	if err := bank.Observe(fakeTechnicalQuote(101, 100)); err != nil {
		t.Fatal(err)
	}
	before := bank.View()
	for _, at := range []float64{99, 100, math.NaN(), math.Inf(-1)} {
		if bank.Advance(at) == nil || bank.View() != before {
			t.Fatal("不正時計の受理又は入力状態変更")
		}
	}
}

// reflectTechnicalView は人工価格を定数から反射し売買鏡像を作ります。
//
// 引数: v(TechnicalView)は人工技法値です。
// 返り値: TechnicalViewはRSIを100との差、MACDを符号反転した値です。
func reflectTechnicalView(v TechnicalView) TechnicalView {
	v.EMA8_3, v.EMA21_3 = 2000-v.EMA8_3, 2000-v.EMA21_3
	v.EMA8_15, v.EMA21_15 = 2000-v.EMA8_15, 2000-v.EMA21_15
	v.Close3 = 2000 - v.Close3
	v.RSI3, v.PreviousRSI3 = 100-v.RSI3, 100-v.PreviousRSI3
	v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
	return v
}

// TestTechnicalEntryAndFailed は資格のstrict境界・OR・鏡像・未知を確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。高RSI持続単独では拒否しません。
func TestTechnicalEntryAndFailed(t *testing.T) {
	trend := TechnicalView{TrendKnown: true, SpikeKnown: true, EMA8_3: 102, EMA21_3: 100,
		EMA8_15: 104, EMA21_15: 100, RSI3: 90, PreviousRSI3: 90, TR3: 4, PreviousATR3: 2}
	if ok, role, _ := trend.Entry(1); !ok || role != "順行" {
		t.Fatal("既知の順行又は高RSI持続を誤拒否")
	}
	reversal := TechnicalView{ReversalKnown: true, SpikeKnown: true, EMA8_3: 100, Close3: 101,
		RSI3: 51, PreviousRSI3: 50, Histogram3: 1, PreviousHistogram3: 0, TR3: 2, PreviousATR3: 2}
	if ok, role, _ := reversal.Entry(1); !ok || role != "反転" {
		t.Fatal("順行と独立した反転を拒否")
	}
	for _, original := range []TechnicalView{trend, reversal} {
		mirror := reflectTechnicalView(original)
		a, ar, ax := original.Entry(1)
		b, br, bx := mirror.Entry(-1)
		if a != b || ar != br || ax != bx {
			t.Fatal("売買反射で資格又は役割が変わる")
		}
	}
	for _, mutate := range []func(*TechnicalView){
		func(v *TechnicalView) { v.RSI3 = 50 },
		func(v *TechnicalView) { v.PreviousRSI3 = 51 },
		func(v *TechnicalView) { v.Histogram3 = 0 },
		func(v *TechnicalView) { v.Close3 = 100 },
		func(v *TechnicalView) { v.SpikeKnown = false },
		func(v *TechnicalView) { v.ReversalKnown = false },
	} {
		v := reversal
		mutate(&v)
		if ok, _, _ := v.Entry(1); ok {
			t.Fatal("反転の等号又は未知を受理")
		}
	}
	v := trend
	v.RSI3, v.PreviousRSI3, v.TR3 = 70, 55, 4.1
	if ok, _, _ := v.Entry(1); !ok {
		t.Fatal("RSI差15の等号をスパイク拒否")
	}
	v.RSI3 = 70.1
	if ok, _, _ := v.Entry(1); ok {
		t.Fatal("TRとRSIの同時スパイクを受理")
	}
	v.TR3 = 4
	if ok, _, _ := v.Entry(1); !ok {
		t.Fatal("TR2倍の等号をスパイク拒否")
	}
	v = reversal
	v.ExitKnown, v.Close3, v.Histogram3 = true, 99, -1
	if !v.Failed(1) || !reflectTechnicalView(v).Failed(-1) {
		t.Fatal("終値と勢いの同時失敗又は鏡像が不正")
	}
	for _, mutate := range []func(*TechnicalView){
		func(v *TechnicalView) { v.ExitKnown = false },
		func(v *TechnicalView) { v.Close3 = v.EMA8_3 },
		func(v *TechnicalView) { v.Histogram3 = v.PreviousHistogram3 },
	} {
		x := v
		mutate(&x)
		if x.Failed(1) {
			t.Fatal("未知又は等号で技法失敗")
		}
	}
	if ok, _, _ := trend.Entry(0); ok || v.Failed(0) {
		t.Fatal("無効なsideを受理")
	}
}

// TestTechnicalWholeMirror はOHLC形成から全指標の鏡像を確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。ATR/TRは反射せず、数値の符号だけを対称にします。
func TestTechnicalWholeMirror(t *testing.T) {
	a, b := NewTechnicalBank(), NewTechnicalBank()
	a.BeginSession(0)
	b.BeginSession(0)
	for i := 0; i < 120; i++ {
		price := 1000 + float64(i)/4 + 8*math.Sin(float64(i)/7)
		q := fakeTechnicalQuote(float64(i)*180, price)
		mirror := q
		mirror.Last, mirror.Bid, mirror.Ask = 2000-q.Last, 2000-q.Ask, 2000-q.Bid
		if err := a.Observe(q); err != nil {
			t.Fatal(err)
		}
		if err := b.Observe(mirror); err != nil {
			t.Fatal(err)
		}
	}
	if err := a.Advance(120 * 180); err != nil {
		t.Fatal(err)
	}
	if err := b.Advance(120 * 180); err != nil {
		t.Fatal(err)
	}
	x, y := reflectTechnicalView(a.View()), b.View()
	actual, expected := reflect.ValueOf(y), reflect.ValueOf(x)
	for i := 0; i < actual.NumField(); i++ {
		if actual.Field(i).Kind() == reflect.Float64 {
			closeEnoughTechnical(t, actual.Field(i).Float(), expected.Field(i).Float())
		} else if actual.Field(i).Bool() != expected.Field(i).Bool() {
			t.Fatal("反射後の既知maskが不一致")
		}
	}
}
