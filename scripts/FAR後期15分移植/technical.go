package far80

import (
	"fmt"
	"math"
)

type exponentialMean struct {
	period int
	count  int
	sum    float64
	value  float64
	known  bool
}

// update は初期SMAと、その後のEMAを一つ進めます。
//
// 引数: value(float64)は新しい有限観測です。
// 返り値: ありません。期間本数に達するまでknownを立てません。
func (e *exponentialMean) update(value float64) {
	if !e.known {
		e.count++
		e.sum += value
		if e.count == e.period {
			e.value, e.known = e.sum/float64(e.period), true
		}
		return
	}
	e.value += 2 / float64(e.period+1) * (value - e.value)
}

type wilderMean struct {
	period int
	count  int
	sum    float64
	value  float64
	known  bool
}

// update は初期SMAと、その後のWilder平均を一つ進めます。
//
// 引数: value(float64)は新しい有限観測です。
// 返り値: ありません。未知値を0へ補完しません。
func (w *wilderMean) update(value float64) {
	if !w.known {
		w.count++
		w.sum += value
		if w.count == w.period {
			w.value, w.known = w.sum/float64(w.period), true
		}
		return
	}
	w.value = (w.value*float64(w.period-1) + value) / float64(w.period)
}

type technicalSeries struct {
	ema8, ema21, ema12, ema26, signal exponentialMean
	gain, loss, atr                   wilderMean
	previousClose                     float64
	previousCloseKnown                bool
	close, rsi, previousRSI           float64
	histogram, previousHistogram      float64
	tr, previousATR                   float64
	rsiKnown, previousRSIKnown        bool
	histKnown, previousHistKnown      bool
	previousATRKnown                  bool
	end                               float64
	published                         bool
}

// reset は欠足又は不良に続く数値履歴を未知へ戻します。
//
// 引数: ありません。
// 返り値: ありません。期間と計算法だけを初期化します。
func (s *technicalSeries) reset() {
	*s = technicalSeries{
		ema8: exponentialMean{period: 8}, ema21: exponentialMean{period: 21},
		ema12: exponentialMean{period: 12}, ema26: exponentialMean{period: 26},
		signal: exponentialMean{period: 9}, gain: wilderMean{period: 14},
		loss: wilderMean{period: 14}, atr: wilderMean{period: 14},
	}
}

// closeBar は公開された一つの正常OHLCから指標を更新します。
//
// 引数: high/low/close/end(float64)は確定足の高値・安値・終値・終端です。
// 返り値: ありません。前値は今回更新前の既知性とともに保存します。
func (s *technicalSeries) closeBar(high, low, close, end float64) {
	s.previousRSI, s.previousRSIKnown = s.rsi, s.rsiKnown
	s.previousHistogram, s.previousHistKnown = s.histogram, s.histKnown
	s.previousATR, s.previousATRKnown = s.atr.value, s.atr.known
	s.tr = high - low
	if s.previousCloseKnown {
		s.tr = math.Max(s.tr, math.Max(math.Abs(high-s.previousClose), math.Abs(low-s.previousClose)))
		change := close - s.previousClose
		s.gain.update(math.Max(change, 0))
		s.loss.update(math.Max(-change, 0))
	}
	s.atr.update(s.tr)
	s.ema8.update(close)
	s.ema21.update(close)
	s.ema12.update(close)
	s.ema26.update(close)
	if s.gain.known && s.loss.known {
		s.rsiKnown = true
		switch {
		case s.gain.value == 0 && s.loss.value == 0:
			s.rsi = 50
		case s.loss.value == 0:
			s.rsi = 100
		default:
			s.rsi = 100 - 100/(1+s.gain.value/s.loss.value)
		}
	}
	if s.ema12.known && s.ema26.known {
		macd := s.ema12.value - s.ema26.value
		s.signal.update(macd)
		if s.signal.known {
			s.histogram, s.histKnown = macd-s.signal.value, true
		}
	}
	s.previousClose, s.previousCloseKnown = close, true
	s.close, s.end, s.published = close, end, true
}

type formingBar struct {
	start, width, open, high, low, close float64
	count                                int
	bad                                  bool
}

// add は半開区間の当場形成足へ当時Lastを加えます。
//
// 引数: value(float64)は正常で正のLastです。
// 返り値: ありません。不良を挟んだ足のbadは解消しません。
func (b *formingBar) add(value float64) {
	if b.count == 0 {
		b.open, b.high, b.low = value, value, value
	} else {
		b.high, b.low = math.Max(b.high, value), math.Min(b.low, value)
	}
	b.close = value
	b.count++
}

// advance は終端以下の形成足を確定し、空足の数値履歴を破棄します。
//
// 引数: at(float64)は現在時計、series(*technicalSeries)は同尺度の数値履歴です。
// 返り値: ありません。連続空足は補完せず、対象区間へ時計だけを進めます。
func (b *formingBar) advance(at float64, series *technicalSeries) {
	end := b.start + b.width
	if end > at {
		return
	}
	if b.count == 0 || b.bad {
		series.reset()
		series.end, series.published = end, true
	} else {
		series.closeBar(b.high, b.low, b.close, end)
	}
	*b = formingBar{start: end, width: b.width}
	if b.start+b.width <= at {
		// ----------------------------------------
		// 当場の欠足が複数ある場合も、価格を創作せず一括で未知にします。
		steps := math.Floor((at - b.start) / b.width)
		b.start += steps * b.width
		series.reset()
		series.end, series.published = b.start, true
	}
}

// TechnicalBank は当場の形成足と同限月で持ち越す数値履歴を管理します。
// BeginSessionは形成足と公開maskだけを更新し、場外の足を生成しません。
type TechnicalBank struct {
	three, fifteen    formingBar
	series3, series15 technicalSeries
	frontier, start   float64
	started           bool
	beginError        error
}

// NewTechnicalBank は未知の3分・15分技法器を作ります。
//
// 引数: ありません。
// 返り値: *TechnicalBankは市場や外部ファイルへ接続しない技法器です。
func NewTechnicalBank() *TechnicalBank {
	bank := &TechnicalBank{}
	bank.series3.reset()
	bank.series15.reset()
	return bank
}

// BeginSession は当場の足区切りを設定し、同限月の数値種を保ちます。
//
// 引数: start(float64)は場開始の有限Unix秒です。
// 返り値: ありません。不正な開始は後続Observe/Advanceでerrorにします。
func (b *TechnicalBank) BeginSession(start float64) {
	b.three, b.fifteen = formingBar{start: start, width: 180}, formingBar{start: start, width: 900}
	b.series3.published, b.series15.published = false, false
	b.started, b.frontier, b.start, b.beginError = true, start, start, nil
	if !finiteTechnical(start) {
		b.beginError = fmt.Errorf("場開始時計が非有限です")
	}
}

// Advance は現在時計以下の足終端を価格更新より先に処理します。
//
// 引数: at(float64)は有限で後退しないUnix秒です。
// 返り値: errorは未開始・不正時計・時計後退です。正常時はnilです。
func (b *TechnicalBank) Advance(at float64) error {
	if !b.started {
		return fmt.Errorf("技法器の場が未開始です")
	}
	if b.beginError != nil {
		return b.beginError
	}
	if !finiteTechnical(at) || at < b.frontier || at < b.start {
		return fmt.Errorf("技法器の時計が非有限又は後退しています")
	}
	b.three.advance(at, &b.series3)
	b.fifteen.advance(at, &b.series15)
	b.frontier = at
	return nil
}

// Observe は当行時計まで確定してから、Lastを次の半開区間へ加えます。
//
// 引数: q(Quote)は当時値で、技法用ValidはLast利用可否です。BBO正常性とは独立です。
// 返り値: errorは時計の異常です。不良価格は数値を未知へ戻しnilを返します。
func (b *TechnicalBank) Observe(q Quote) error {
	if err := b.Advance(q.Time); err != nil {
		return err
	}
	if !q.Valid || !finiteTechnical(q.Last) || q.Last <= 0 {
		b.three.bad, b.fifteen.bad = true, true
		end3, end15 := b.series3.end, b.series15.end
		published3, published15 := b.series3.published, b.series15.published
		b.series3.reset()
		b.series15.reset()
		b.series3.end, b.series15.end = end3, end15
		b.series3.published, b.series15.published = published3, published15
		return nil
	}
	b.three.add(q.Last)
	b.fifteen.add(q.Last)
	return nil
}

// View は確定足だけから、既知性を添えた現在の複合判断を返します。
//
// 引数: ありません。
// 返り値: TechnicalViewは呼出側から技法器を変更できない値コピーです。
func (b *TechnicalBank) View() TechnicalView {
	a, z := b.series3, b.series15
	v := TechnicalView{}
	if a.published {
		v.Bar3End, v.Close3, v.TR3 = a.end, a.close, a.tr
		v.EMA8_3, v.EMA21_3 = a.ema8.value, a.ema21.value
		v.RSI3, v.PreviousRSI3 = a.rsi, a.previousRSI
		v.Histogram3, v.PreviousHistogram3 = a.histogram, a.previousHistogram
		v.ATR3, v.PreviousATR3 = a.atr.value, a.previousATR
		v.ReversalKnown = a.ema8.known && a.rsiKnown && a.previousRSIKnown && a.histKnown && a.previousHistKnown
		v.ExitKnown = a.ema8.known && a.histKnown && a.previousHistKnown
		v.SpikeKnown = a.rsiKnown && a.previousRSIKnown && a.previousATRKnown
		v.ATRKnown = a.atr.known
	}
	if z.published {
		v.Bar15End, v.EMA8_15, v.EMA21_15 = z.end, z.ema8.value, z.ema21.value
	}
	v.TrendKnown = a.published && z.published && a.ema8.known && a.ema21.known && z.ema8.known && z.ema21.known
	return v
}

// finiteTechnical は指標・時計の有限性を確認します。
//
// 引数: value(float64)は検査する数値です。
// 返り値: boolはNaNと正負無限大でない場合に真です。
func finiteTechnical(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}

// Entry は順行又は反転の既知成立を確認し、同時スパイクだけを拒否します。
//
// 引数: side(int)は買い1又は売り-1です。
// 返り値: allowed(bool)は採用可否、role/reason(string)は役割と判断理由です。
func (v TechnicalView) Entry(side int) (allowed bool, role string, reason string) {
	if side != 1 && side != -1 {
		return false, "待機", "売買方向が不正"
	}
	if !v.SpikeKnown {
		return false, "待機", "同時スパイクの必要値が未知"
	}
	if v.TR3 > 2*v.PreviousATR3 && math.Abs(v.RSI3-v.PreviousRSI3) > 15 {
		return false, "待機", "TRとRSI変化の同時スパイク"
	}
	direction := float64(side)
	if v.TrendKnown && direction*(v.EMA8_3-v.EMA21_3) > 0 && direction*(v.EMA8_15-v.EMA21_15) > 0 {
		return true, "順行", "3分と15分のEMA方向一致"
	}
	if v.ReversalKnown && direction*(v.RSI3-50) > 0 && direction*(v.PreviousRSI3-50) <= 0 &&
		direction*(v.Histogram3-v.PreviousHistogram3) > 0 && direction*(v.Close3-v.EMA8_3) > 0 {
		return true, "反転", "3分RSI交差と勢い及び終値の確認"
	}
	if !v.TrendKnown || !v.ReversalKnown {
		return false, "待機", "成立しない条件又は必要値の未知"
	}
	return false, "待機", "順行と反転の条件不一致"
}

// Failed は現在の3分足が保有方向と逆の価格・勢いを同時に示すか判定します。
//
// 引数: side(int)は保有方向の買い1又は売り-1です。
// 返り値: boolは既知の終値がEMA8反対側かつヒストグラム差も反対なら真です。
func (v TechnicalView) Failed(side int) bool {
	if (side != 1 && side != -1) || !v.ExitKnown {
		return false
	}
	direction := float64(side)
	return direction*(v.Close3-v.EMA8_3) < 0 && direction*(v.Histogram3-v.PreviousHistogram3) < 0
}
