package far82

import (
	"fmt"
	"math"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// ChartBank は固定80の数値器に、同じ確定3分足へ結ぶ直前足の追跡を加えます。
// 数値器の場間種は保ち、追跡値は場頭で必ず未知へ戻します。
type ChartBank struct {
	base *far80.TechnicalBank
	view ChartView
}

// NewChartBank は既存の数値種を包み、前足の公開関係を未知から始めます。
//
// 引数: base(*far80.TechnicalBank)は当場前の独立種です。
// 返り値: *ChartBankは前足をまだ保存していない追跡器です。
func NewChartBank(base *far80.TechnicalBank) *ChartBank {
	return &ChartBank{base: base}
}

// BeginSession は数値種を保ったまま当場の足と追跡情報を開始します。
//
// 引数: start(float64)は当場の開始Unix秒です。
// 返り値: ありません。不正時計は固定数値器の後続操作でerrorになります。
func (b *ChartBank) BeginSession(start float64) {
	b.view = ChartView{}
	if b.base != nil {
		b.base.BeginSession(start)
		b.view.Technical = b.base.View()
	}
}

// chartFinite は前後の数値・時計が全て有限であることを確認します。
//
// 引数: values(...float64)は既知性へ結ぶ数値です。
// 返り値: boolはNaNと無限大が一つもない場合に真です。
func chartFinite(values ...float64) bool {
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return false
		}
	}
	return true
}

// capture は処理前後の公開値を結び、直前180秒足だけを有効にします。
//
// 引数: before/after(TechnicalView)は固定数値器の同操作前後の値です。
// 返り値: ありません。更新前の値を現在のEMAで再解釈しません。
func (b *ChartBank) capture(before, after TechnicalView) {
	if after.Bar3End != before.Bar3End {
		b.view.PreviousClose3 = before.Close3
		b.view.PreviousEMA8_3 = before.EMA8_3
		b.view.PreviousBar3End = before.Bar3End
		b.view.Previous3Known = before.ExitKnown && before.SpikeKnown && after.ExitKnown && after.SpikeKnown &&
			before.Bar3End > 0 && after.Bar3End-before.Bar3End == 180 &&
			before.Histogram3 == after.PreviousHistogram3 && before.RSI3 == after.PreviousRSI3 &&
			chartFinite(before.Bar3End, after.Bar3End, before.Close3, before.EMA8_3,
				before.Histogram3, before.RSI3, after.PreviousHistogram3, after.PreviousRSI3)
	}
	if !after.ExitKnown || !after.SpikeKnown || after.Bar3End == 0 {
		b.view.Previous3Known = false
	}
	b.view.Technical = after
}

// Advance は当時時計までの確定公開を進め、直前足と現在足を結合します。
//
// 引数: at(float64)は現在のUnix秒です。
// 返り値: errorはnil種又は固定数値器の時計異常です。
func (b *ChartBank) Advance(at float64) error {
	if b.base == nil {
		return fmt.Errorf("数値種がnilです")
	}
	before := b.base.View()
	if err := b.base.Advance(at); err != nil {
		return err
	}
	b.capture(before, b.base.View())
	return nil
}

// Observe は当行を次の形成足へ追加し、確定足の前後関係を保存します。
//
// 引数: q(Quote)はLast利用可否をValidに持つ当時の原観測です。
// 返り値: errorはnil種又は時計異常です。不良Lastの後は前足を既知にしません。
func (b *ChartBank) Observe(q Quote) error {
	if b.base == nil {
		return fmt.Errorf("数値種がnilです")
	}
	before := b.base.View()
	if err := b.base.Observe(q); err != nil {
		return err
	}
	b.capture(before, b.base.View())
	return nil
}

// View は確定公開済みの現在値と直前3分足を値コピーで返します。
//
// 引数: ありません。
// 返り値: ChartViewは数値器を変更できない保存用snapshotです。
func (b *ChartBank) View() ChartView { return b.view }
