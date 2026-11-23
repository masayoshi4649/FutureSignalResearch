package far82

import (
	"math"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// chart82Warm は市場に接続せず、70本目の終端直前まで人工Lastを供給します。
//
// 引数: t(*testing.T)は検査器、start(float64)は人工場開始です。
// 返り値: *ChartBankは既知指標と連続する確定足、float64は最後の人工Lastです。
func chart82Warm(t *testing.T, start float64) (*ChartBank, float64) {
	t.Helper()
	bank := NewChartBank(far80.NewTechnicalBank())
	bank.BeginSession(start)
	last := 0.0
	for i := 0; i < 70*6; i++ {
		last = 1000 + float64(i)*.1 + math.Sin(float64(i)*.7)*20
		if err := bank.Observe(Quote{Time: start + float64(i)*30 + 1, Last: last, Valid: true}); err != nil {
			t.Fatal(err)
		}
	}
	return bank, last
}

// TestChart82PreviousPair は前Closeと前EMAが同じ確定足へ結び付くことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。終端同時計の新価格は確定済み終値へ混入しません。
func TestChart82PreviousPair(t *testing.T) {
	start := 1_000_000.0
	bank, last := chart82Warm(t, start)
	before := bank.View()
	end := start + 70*180
	if err := bank.Advance(end); err != nil {
		t.Fatal(err)
	}
	after := bank.View()
	if !after.Previous3Known || after.PreviousBar3End != before.Technical.Bar3End ||
		after.PreviousClose3 != before.Technical.Close3 || after.PreviousEMA8_3 != before.Technical.EMA8_3 ||
		after.Technical.Bar3End != end || after.Technical.Close3 != last ||
		after.Technical.PreviousRSI3 != before.Technical.RSI3 ||
		after.Technical.PreviousHistogram3 != before.Technical.Histogram3 {
		t.Fatal("直前180秒足の結合が異なります", before, after)
	}
	if err := bank.Observe(Quote{Time: end, Last: 999999, Valid: true}); err != nil {
		t.Fatal(err)
	}
	if bank.View() != after {
		t.Fatal("終端同時計の形成価格が確定足へ混入")
	}
	copy := bank.View()
	copy.PreviousClose3 = -1
	if bank.View().PreviousClose3 == -1 {
		t.Fatal("返したsnapshotが追跡器を変更")
	}
}

// TestChart82UnknownGapAndBad は空足・不良Last・未準備を未知に保つことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。欠損を前値で埋めません。
func TestChart82UnknownGapAndBad(t *testing.T) {
	start := 1_000_000.0
	bank := NewChartBank(far80.NewTechnicalBank())
	bank.BeginSession(start)
	if err := bank.Observe(Quote{Time: start + 1, Last: 1000, Valid: true}); err != nil {
		t.Fatal(err)
	}
	if err := bank.Advance(start + 180); err != nil {
		t.Fatal(err)
	}
	if bank.View().Previous3Known {
		t.Fatal("最初の確定足へ架空の前足を作成")
	}
	bank, _ = chart82Warm(t, start)
	if !bank.View().Previous3Known {
		t.Fatal("人工準備に失敗")
	}
	end := start + 70*180
	if err := bank.Observe(Quote{Time: end - 1, Last: 0, Valid: false}); err != nil {
		t.Fatal(err)
	}
	if bank.View().Previous3Known {
		t.Fatal("不良Last後も前足を既知にしました")
	}
	if err := bank.Advance(end); err != nil {
		t.Fatal(err)
	}
	if bank.View().Previous3Known || bank.View().Technical.ExitKnown {
		t.Fatal("不良を含む形成足の指標を再利用")
	}
	bank, _ = chart82Warm(t, start)
	if err := bank.Advance(end + 3*180); err != nil {
		t.Fatal(err)
	}
	if bank.View().Previous3Known || bank.View().Technical.ExitKnown {
		t.Fatal("複数空足を連続前足へ変換")
	}
}

// TestChart82NewSessionResetsPair は同限月の数値種と前足の場内公開を区別します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。場を跨いだEMA値を前3分足として使いません。
func TestChart82NewSessionResetsPair(t *testing.T) {
	start := 1_000_000.0
	bank, _ := chart82Warm(t, start)
	newStart := start + 24*3600
	bank.BeginSession(newStart)
	if bank.View().Previous3Known || bank.View().Technical.ExitKnown {
		t.Fatal("新場で前足公開maskを継承")
	}
	for _, at := range []float64{newStart + 1, newStart + 181} {
		if err := bank.Observe(Quote{Time: at, Last: 1100, Valid: true}); err != nil {
			t.Fatal(err)
		}
	}
	if bank.View().Previous3Known || !bank.View().Technical.ExitKnown {
		t.Fatal("数値種継承と初回前足未知を区別していません")
	}
	if err := bank.Observe(Quote{Time: newStart + 361, Last: 1110, Valid: true}); err != nil {
		t.Fatal(err)
	}
	if !bank.View().Previous3Known || bank.View().PreviousBar3End != newStart+180 {
		t.Fatal("同場の連続確定足を再開できません", bank.View())
	}
}

// TestChart82ClockAndBinding は時刻異常と前後指標の異なる結合を拒否します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。固定数値器へ反する前足の既知性を作りません。
func TestChart82ClockAndBinding(t *testing.T) {
	bank := NewChartBank(nil)
	if bank.Advance(1) == nil || bank.Observe(Quote{Time: 1}) == nil {
		t.Fatal("nil数値種を受理")
	}
	bank = NewChartBank(far80.NewTechnicalBank())
	if bank.Advance(1) == nil {
		t.Fatal("未開始時計を受理")
	}
	bank.BeginSession(1000)
	for _, at := range []float64{999, math.NaN(), math.Inf(1)} {
		if bank.Advance(at) == nil {
			t.Fatal("異常時計を受理", at)
		}
	}
	before := TechnicalView{Bar3End: 1000, Close3: 1000, EMA8_3: 999, Histogram3: 1, RSI3: 51, ExitKnown: true, SpikeKnown: true}
	after := TechnicalView{Bar3End: 1180, PreviousHistogram3: 1, PreviousRSI3: 51, ExitKnown: true, SpikeKnown: true}
	bank.capture(before, after)
	if !bank.View().Previous3Known {
		t.Fatal("正常な人工前足結合を受理しません")
	}
	for _, field := range []string{"hist", "rsi", "gap", "nan"} {
		bad := after
		switch field {
		case "hist":
			bad.PreviousHistogram3 = 2
		case "rsi":
			bad.PreviousRSI3 = 52
		case "gap":
			bad.Bar3End += 180
		case "nan":
			bad.PreviousRSI3 = math.NaN()
		}
		bank.capture(before, bad)
		if bank.View().Previous3Known {
			t.Fatal("異なる前足の指標を同じ足へ結合", field)
		}
	}
}
