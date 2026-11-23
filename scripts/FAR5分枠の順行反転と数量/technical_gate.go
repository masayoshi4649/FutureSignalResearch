package minichart

import (
	"fmt"
	"math"
	"reflect"

	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// TechnicalGateInput は当枠の公開チャートと現在原行だけを金融外から受け取ります。
// ObservedClockは公開をdrainした上限であり、値の利用時計AvailableAtとは異なります。
type TechnicalGateInput struct {
	SnapshotID string                   `json:"snapshot_id"`
	At         float64                  `json:"at"`
	Kind       string                   `json:"kind"`
	Chart      chartwarmup96.Snapshot   `json:"chart"`
	Recent3    []chartwarmup96.Snapshot `json:"recent3"`
	Current    far82.CurrentEvidence    `json:"current"`
}

// TechnicalGateCheck は未知を不成立や0支持へ置換しない個別の採否です。
type TechnicalGateCheck struct {
	ID     string `json:"id"`
	Known  bool   `json:"known"`
	Passed bool   `json:"passed"`
	Reason string `json:"reason"`
}

// TechnicalAssessment は金融へ渡す最終判断と、その根拠を分けて保存します。
type TechnicalAssessment struct {
	Decision GateDecision         `json:"decision"`
	Checks   []TechnicalGateCheck `json:"checks"`
}

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

// validateTechnicalGate は同原行の現在値と公開snapshotの破損を拒否します。
//
// 引数: in(TechnicalGateInput)、c(EntryCandidate)、policy(string)は純判断入力です。
// 返り値: errorは型/未来/同原行/有限性の不整合です。
func validateTechnicalGate(in TechnicalGateInput, c EntryCandidate, policy string) error {
	if !gateFiniteValue(reflect.ValueOf(in)) || !gateFiniteValue(reflect.ValueOf(c)) {
		return fmt.Errorf("技法入力に非有限値があります")
	}
	if policy != "A" && policy != "B" && policy != "AB" {
		return fmt.Errorf("技法政策が不正です")
	}
	if in.SnapshotID == "" || in.At <= 0 || in.At != c.At || in.Chart.At != in.At ||
		(in.Kind != "Day" && in.Kind != "Night") || (c.Side != 1 && c.Side != -1) ||
		in.Chart.Scene.ID == "" || in.Chart.Scene.Contract == "" || in.Chart.Scene.Start <= 0 ||
		c.Source.BirthTime < 0 || c.Source.BirthTime > in.At || c.Source.BirthQuote.Time < 0 || c.Source.BirthQuote.Time > in.At ||
		c.Quote.Time <= 0 || c.Quote.Time > in.At || c.Quote.Index < 0 || c.Quote.SourceLine <= 0 ||
		!c.Quote.QuoteOK || c.Quote.Last <= 0 || c.Quote.Bid <= 0 || c.Quote.Ask <= c.Quote.Bid {
		return fmt.Errorf("技法の政策/場/候補/判断時計が不正です")
	}
	current := in.Current
	if current.Time != c.Quote.Time || current.SourceIndex != c.Quote.Index || current.SourceLine != c.Quote.SourceLine ||
		current.Last != c.Quote.Last || current.Bid != c.Quote.Bid || current.Ask != c.Quote.Ask ||
		current.Received < 0 || current.Received > in.At {
		return fmt.Errorf("現在特徴と候補の同物理行/時計/価格が不一致です")
	}
	for _, support := range []struct{ own, peer float64 }{{current.Buy.OwnAt, current.Buy.PeerAt}, {current.Sell.OwnAt, current.Sell.PeerAt}} {
		if support.own < 0 || support.peer < 0 || support.own > current.Time || support.peer > current.Time {
			return fmt.Errorf("現在量支持の源時計が未来です")
		}
	}
	if err := validateGateSnapshot(in.Chart, in.At); err != nil {
		return err
	}
	if len(in.Recent3) > 3 {
		return fmt.Errorf("直近公開足は最大3本です")
	}
	for i, s := range in.Recent3 {
		if err := validateGateSnapshot(s, in.At); err != nil {
			return fmt.Errorf("直近足%d: %w", i, err)
		}
		if s.Scene != in.Chart.Scene || s.At != s.Three.BarEnd || i > 0 && s.At <= in.Recent3[i-1].At {
			return fmt.Errorf("直近足の場/公開順が不一致です")
		}
	}
	return validateGateCurrentTimes(in)
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

// AssessTechnicalGate は現在の順行A/反転B/和集合ABだけを純粋に判定します。
//
// 引数: input(TechnicalGateInput)、candidate(EntryCandidate)、policy(string)は公開値・固定方向・政策です。
// 返り値: TechnicalAssessment/errorは採否と全根拠、又は未来/破損入力です。
func AssessTechnicalGate(input TechnicalGateInput, candidate EntryCandidate, policy string) (TechnicalAssessment, error) {
	if err := validateTechnicalGate(input, candidate, policy); err != nil {
		return TechnicalAssessment{}, err
	}
	s, at, chart := float64(candidate.Side), input.At, input.Chart
	t := chart.Chart.Technical
	e := candidate.Quote.Ask
	if candidate.Side == -1 {
		e = candidate.Quote.Bid
	}
	three := chart.Three.DataKnown && t.Bar3End > 0 && at-t.Bar3End < 180
	fifteen := chart.Fifteen.DataKnown && t.Bar15End > 0 && at-t.Bar15End < 900
	common := []TechnicalGateCheck{
		gateCheck("共通.現在価格時計", at-candidate.Quote.Time <= 15, true, "候補とCurrentの同原行を検査済み・価格時計は15秒以内"),
		gateCheck("共通.確定3分", three, true, "当場の既知確定足・終端以下で足齢180秒未満"),
		gateCheck("共通.確定15分", fifteen, true, "当場の既知確定足・終端以下で足齢900秒未満"),
		gateCheck("共通.EMA背景既知", three && fifteen && t.TrendKnown, true, "固定APIのTrendKnownを使用・EMA15単独の既知性は推測しない"),
		gateCheck("共通.MACD増分", three && t.ExitKnown, s*(t.Histogram3-t.PreviousHistogram3) > 0, "3分ヒストグラム増分が候補方向へstrict正"),
		gateCheck("共通.終値とEMA8", three && t.ExitKnown, s*(t.Close3-t.EMA8_3) > 0, "確定終値は現在EMA8の候補方向側"),
		gateCheck("共通.取得位置ATR", three && t.ExitKnown && t.ATRKnown && t.ATR3 > 0,
			s*(e-t.EMA8_3) >= 0 && s*(e-t.EMA8_3) <= t.ATR3, "取得側気配の符号付きEMA8距離が0以上1ATR以下・等号許容"),
		gateCheck("共通.同時スパイク警戒", three && t.SpikeKnown,
			!(t.TR3 > 2*t.PreviousATR3 && math.Abs(t.RSI3-t.PreviousRSI3) > 15), "TR>前ATRの2倍 AND RSI変化絶対値>15のみ拒否・RSI水準単独では拒否しない"),
	}
	volumeKnown, volumePassed, volumeReason := false, false, "量支持は未知"
	if input.Kind == "Day" {
		v := input.Current.Buy
		if candidate.Side == -1 {
			v = input.Current.Sell
		}
		volumeKnown = v.OFIKnown && v.OwnAt == input.Current.Time
		volumePassed = s*v.OFI30 > 0
		volumeReason = "当原行OwnAtの既知OFI30に候補方向を掛けstrict正・約定出来高ではない"
	} else {
		n, v := input.Current.Night, input.Current.Night.Band
		volumeKnown = n.Available && n.Window == "E08" && v.QuantityKnown && v.Time == input.Current.Time && v.Index == input.Current.SourceIndex
		volumePassed = s*(v.BidRefill+v.AskDeplete-v.AskRefill-v.BidDeplete) > 0
		volumeReason = "同時刻/同FeaturesIndexのE08数量変化4成分の符号差・約定出来高ではない"
	}
	common = append(common, gateCheck("共通.現在量支持", volumeKnown, volumePassed, volumeReason))
	a := []TechnicalGateCheck{
		gateCheck("A.3分EMA方向", three && t.TrendKnown, s*(t.EMA8_3-t.EMA21_3) > 0, "EMA8とEMA21の差が候補方向へstrict正"),
		gateCheck("A.15分EMA方向", fifteen && t.TrendKnown, s*(t.EMA8_15-t.EMA21_15) > 0, "上位EMA背景も候補方向へstrict正"),
		gateCheck("A.確定終値進行", three && chart.Chart.Previous3Known, s*(t.Close3-chart.Chart.PreviousClose3) > 0, "連続する直前3分確定終値より候補方向へ進む"),
	}
	b := []TechnicalGateCheck{
		gateCheck("B.15分EMA逆背景", fifteen && t.TrendKnown, s*(t.EMA8_15-t.EMA21_15) < 0, "候補方向は上位EMA8/21のstrict逆・Source方向は変更しない"),
	}
	windowKnown := len(input.Recent3) == 3 && t.ExitKnown && t.SpikeKnown
	if windowKnown {
		for i, p := range input.Recent3 {
			windowKnown = windowKnown && p.Three.DataKnown && p.Three.BarEnd == p.At
			if i > 0 {
				windowKnown = windowKnown && p.At-input.Recent3[i-1].At == 180
			}
		}
		a, b, c := input.Recent3[0].Chart.Technical, input.Recent3[1].Chart.Technical, input.Recent3[2].Chart.Technical
		windowKnown = windowKnown && (a.TrendKnown || a.ExitKnown || a.ReversalKnown) &&
			(b.SpikeKnown || b.ReversalKnown) && (c.SpikeKnown || c.ReversalKnown)
		windowKnown = windowKnown && input.Recent3[2].At == t.Bar3End
		if windowKnown && (c.Close3 != t.Close3 || c.EMA8_3 != t.EMA8_3 || c.RSI3 != t.RSI3) {
			return TechnicalAssessment{}, fmt.Errorf("直近公開c足と現在確定値が不一致です")
		}
	}
	b = append(b, gateCheck("B.固定3足窓", windowKnown, true, "同場の最新a/b/cだけ・各足終端差180秒・空足/欠足/助走不足を補完しない"))
	var aClose, bClose, cClose, bRSI, cRSI, level float64
	if windowKnown {
		aClose, bClose, cClose = input.Recent3[0].Chart.Technical.Close3, input.Recent3[1].Chart.Technical.Close3, input.Recent3[2].Chart.Technical.Close3
		bRSI, cRSI, level = input.Recent3[1].Chart.Technical.RSI3, input.Recent3[2].Chart.Technical.RSI3, input.Recent3[0].Chart.Technical.EMA8_3
	}
	b = append(b,
		gateCheck("B.a足は固定線反対側", windowKnown, s*(aClose-level) <= 0, "L=a時点EMA8固定・a終値は反対側又は同値"),
		gateCheck("B.b足で固定線奪還", windowKnown, s*(bClose-level) > 0, "b確定終値が固定Lの候補方向側へstrict移行"),
		gateCheck("B.c足で固定線維持", windowKnown, s*(cClose-level) > 0, "別の後足cでも固定L方向側を維持・後のEMAで線を更新しない"),
		gateCheck("B.c足で価格再進行", windowKnown, s*(cClose-bClose) > 0, "c終値がb終値から候補方向へstrict進行"),
		gateCheck("B.c足でRSI再進行", windowKnown, s*(cRSI-bRSI) > 0, "cのRSIがbから候補方向へstrict進行"),
		gateCheck("B.現在取得側も固定線方向", windowKnown, s*(e-level) > 0, "取得側気配も固定Lの候補方向側・Side反転なし"),
	)
	allA, allB := append(append([]TechnicalGateCheck{}, common...), a...), append(append([]TechnicalGateCheck{}, common...), b...)
	stateA, stateB := gateAnd(allA), gateAnd(allB)
	result := TechnicalAssessment{Decision: GateDecision{Policy: policy, SnapshotID: input.SnapshotID}, Checks: allA}
	selected := stateA
	role := "順行"
	if policy == "B" {
		selected, result.Checks, role = stateB, allB, "反転"
	}
	if policy == "AB" {
		result.Checks = append(append(append([]TechnicalGateCheck{}, common...), a...), b...)
		switch {
		case stateA.known && stateA.passed:
			selected, role = stateA, "順行"
		case stateB.known && stateB.passed:
			selected, role = stateB, "反転"
		case stateA.known && stateB.known:
			selected = gateTruth{true, false}
		default:
			selected = gateTruth{}
		}
	}
	result.Decision.Known, result.Decision.Allowed = selected.known, selected.passed
	result.Decision.Role, result.Decision.Reason = role, "公開済み複合テクニカルが成立"
	if !selected.known {
		result.Decision.Role, result.Decision.Reason = "判定不能", "既知の否定条件はなく採否に必要な値が未知"
	}
	if selected.known && !selected.passed {
		result.Decision.Role, result.Decision.Reason = "待機", "公開済みの必要条件が不成立"
	}
	return result, nil
}
