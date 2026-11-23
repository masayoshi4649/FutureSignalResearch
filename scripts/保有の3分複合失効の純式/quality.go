// 由来: scripts/FAR5分枠の順行反転と数量/technical_gate.go
// 由来SHA256: 3ba3c2c8d5b67635b9f2edab076ec9cce9785fea090e8ba87191a65142985fbf
// 公開入口APIは呼ばず、共通品質と三値論理の6関数本文だけを同体で派生します。
package minix5

import (
	"fmt"
	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	"math"
	"reflect"
)

type gateTruth struct {
	known  bool
	passed bool
}

// gateFiniteValue はmapを含めて非有限値だけを拒否し、入力を書き換えません。
//
// 引数: v(reflect.Value)は公開入力の一部です。
// 返り値: boolは全float値がJSONに保存可能なら真です。
func gateFiniteValue(v reflect.Value) bool {
	switch v.Kind() {
	case reflect.Float32, reflect.Float64:
		return !math.IsNaN(v.Float()) && !math.IsInf(v.Float(), 0)
	case reflect.Struct:
		for i := 0; i < v.NumField(); i++ {
			if !gateFiniteValue(v.Field(i)) {
				return false
			}
		}
	case reflect.Slice, reflect.Array:
		for i := 0; i < v.Len(); i++ {
			if !gateFiniteValue(v.Index(i)) {
				return false
			}
		}
	case reflect.Map:
		iter := v.MapRange()
		for iter.Next() {
			if !gateFiniteValue(iter.Value()) {
				return false
			}
		}
	case reflect.Interface, reflect.Pointer:
		if !v.IsNil() {
			return gateFiniteValue(v.Elem())
		}
	}
	return true
}

// gateAnd は既知不成立を先に確定する三値ANDを計算します。
//
// 引数: checks([]TechnicalGateCheck)は一つの役割の必要条件です。
// 返り値: gateTruthは成立/既知不成立/必要未知です。
func gateAnd(checks []TechnicalGateCheck) gateTruth {
	known := true
	for _, c := range checks {
		if c.Known && !c.Passed {
			return gateTruth{true, false}
		}
		known = known && c.Known
	}
	return gateTruth{known, known}
}

// gateCheck は未知のPassedを常に偽にして保存します。
//
// 引数: id/reason(string)、known/passed(bool)は一条件の根拠です。
// 返り値: TechnicalGateCheckは独立した値です。
func gateCheck(id string, known, passed bool, reason string) TechnicalGateCheck {
	return TechnicalGateCheck{id, known, known && passed, reason}
}

// validateGateTechnical は既知性を数値から推測せず、破損値だけを拒否します。
//
// 引数: t(far80.TechnicalView)は固定数値器の公開値です。
// 返り値: errorは負値/既知価格/RSI範囲の不整合です。
func validateGateTechnical(t far80.TechnicalView) error {
	if t.Bar3End < 0 || t.Bar15End < 0 || t.Close3 < 0 || t.TR3 < 0 || t.ATR3 < 0 || t.PreviousATR3 < 0 ||
		t.EMA8_3 < 0 || t.EMA21_3 < 0 || t.EMA8_15 < 0 || t.EMA21_15 < 0 ||
		t.RSI3 < 0 || t.RSI3 > 100 || t.PreviousRSI3 < 0 || t.PreviousRSI3 > 100 {
		return fmt.Errorf("指標の価格/値幅/RSI範囲が不正です")
	}
	if t.TrendKnown && (t.EMA8_3 <= 0 || t.EMA21_3 <= 0 || t.EMA8_15 <= 0 || t.EMA21_15 <= 0) ||
		(t.ExitKnown || t.ReversalKnown) && (t.EMA8_3 <= 0 || t.Close3 <= 0) ||
		t.SpikeKnown && t.Close3 <= 0 {
		return fmt.Errorf("既知指標の正価格が不正です")
	}
	return nil
}

// validateGateSnapshot は論理公開時計と未来原行を検査します。
//
// 引数: s(chartwarmup96.Snapshot)、at(float64)は公開値と今回の判断時刻です。
// 返り値: errorは将来/出典破損です。助走不足や空足はerrorにしません。
func validateGateSnapshot(s chartwarmup96.Snapshot, at float64) error {
	if s.At < 0 || s.At > at || s.InvalidatedAt < 0 || s.InvalidatedAt > at ||
		s.Scene.Start < 0 || s.Scene.Start > s.At || s.Chart.Technical.Bar3End > s.At || s.Chart.Technical.Bar15End > s.At {
		return fmt.Errorf("チャートの判断/場/足時計が未来又は不正です")
	}
	if s.HasObservedClock && s.ObservedClock < s.At || s.ObservedClock < 0 {
		return fmt.Errorf("チャート観測上限が公開時計より過去です")
	}
	if err := validateGateTechnical(s.Chart.Technical); err != nil {
		return err
	}
	if s.HasLastInput && (s.LastInput.Time <= 0 || s.LastInput.Time > s.At || s.LastInput.Index < 0 || s.LastInput.Line <= 0 ||
		s.LastInput.Valid && s.LastInput.Last <= 0) {
		return fmt.Errorf("チャート最終入力の原行/時計が不正です")
	}
	for i, e := range []chartwarmup96.BarEvidence{s.Three, s.Fifteen} {
		width := 180.0
		if i == 1 {
			width = 900
		}
		if e.BarEnd < 0 || e.AvailableAt < 0 || e.BarEnd > s.At || e.AvailableAt > s.At ||
			e.BarEnd > e.AvailableAt || e.Rows < 0 || e.DataKnown && (e.BarEnd <= 0 || e.Rows == 0 || !e.HasLastSource) {
			return fmt.Errorf("足の論理公開/入力数が未来又は不整合です")
		}
		if e.BarEnd > 0 && (!s.HasObservedClock || e.ObservedClock < e.AvailableAt) || e.Rows > 0 != e.HasLastSource {
			return fmt.Errorf("足の観測上限/原行有無が不整合です")
		}
		if e.HasLastSource && (e.LastSource.Time < math.Max(s.Scene.Start, e.BarEnd-width) || e.LastSource.Time >= e.BarEnd || e.LastSource.Index < 0 || e.LastSource.Line <= 0 ||
			e.DataKnown && (!e.LastSource.Valid || e.LastSource.Last <= 0)) {
			return fmt.Errorf("足の最終原行が半開足/既知性と不整合です")
		}
	}
	if s.Three.BarEnd != s.Chart.Technical.Bar3End || s.Fifteen.BarEnd != s.Chart.Technical.Bar15End {
		return fmt.Errorf("足出典と指標の終端が不一致です")
	}
	if s.Chart.PreviousBar3End < 0 || s.Chart.PreviousBar3End > s.At ||
		s.Chart.Previous3Known && (s.Chart.PreviousClose3 <= 0 || s.Chart.PreviousEMA8_3 <= 0 || s.Chart.Technical.Bar3End-s.Chart.PreviousBar3End != 180) {
		return fmt.Errorf("直前3分の公開値が不整合です")
	}
	return nil
}

// validateGateCurrentTimes は利用対象外も含む出典の未来化を拒否します。
//
// 引数: in(TechnicalGateInput)は現在特徴と判断時計です。
// 返り値: errorは未来出典又は既知数量の負値です。
func validateGateCurrentTimes(in TechnicalGateInput) error {
	c := in.Current
	for _, windows := range []map[string]far81.CurrentSupportWindow{c.Buy.Windows, c.Sell.Windows} {
		for _, w := range windows {
			if w.CurrentAt < 0 || w.EndpointAt < 0 || w.CurrentAt > c.Time || w.EndpointAt > c.Time {
				return fmt.Errorf("量支持窓が未来です")
			}
		}
	}
	n := c.Night
	if n.Time < 0 || n.Time > c.Time || n.Band.Time < 0 || n.Band.Time > c.Time || n.Band.StartTime < 0 || n.Band.StartTime > c.Time {
		return fmt.Errorf("夜間E08の出典時計が未来です")
	}
	if n.Index > c.SourceIndex || n.Band.Index > c.SourceIndex || n.Band.StartIndex > c.SourceIndex {
		return fmt.Errorf("夜間E08の出典連番が未来です")
	}
	for _, hold := range []far81.CurrentPriceBand{n.Buy, n.Sell} {
		if hold.Time < 0 || hold.Time > c.Time || hold.Barrier.Time < 0 || hold.Barrier.Time > c.Time || hold.Support.Time < 0 || hold.Support.Time > c.Time ||
			hold.Index > c.SourceIndex || hold.Barrier.Index > c.SourceIndex || hold.Support.Index > c.SourceIndex || hold.PressureIndex > c.SourceIndex {
			return fmt.Errorf("夜間保持帯の出典時計が未来です")
		}
	}
	if c.Short.Time < 0 || c.Short.Time > c.Time || c.Short.Five.Endpoint < 0 || c.Short.Five.Endpoint > c.Time ||
		c.Short.Fifteen.Endpoint < 0 || c.Short.Fifteen.Endpoint > c.Time {
		return fmt.Errorf("短秒出典が未来です")
	}
	for _, quantity := range []float64{n.Band.BidRefill, n.Band.AskRefill, n.Band.BidDeplete, n.Band.AskDeplete,
		n.Band.CommonBidUp, n.Band.CommonAskUp, n.Band.CommonBidDown, n.Band.CommonAskDown} {
		if quantity < 0 {
			return fmt.Errorf("夜間の数量変化が負です")
		}
	}
	return nil
}
