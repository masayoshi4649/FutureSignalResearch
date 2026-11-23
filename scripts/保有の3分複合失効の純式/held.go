package minix5

import (
	"fmt"
	"math"
	"reflect"
)

// validateHeldInput は固定96の共通検査へ、EntryCandidate不要の公開入力境界を接続します。
//
// 引数: in(TechnicalGateInput)は公開snapshot、side(int)は実保有方向±1です。
// 返り値: errorは未来/非有限/型で表現可能な出典矛盾です。金融所有は調べません。
func validateHeldInput(in TechnicalGateInput, side int) error {
	if !gateFiniteValue(reflect.ValueOf(in)) {
		return fmt.Errorf("保有技法入力に非有限値があります")
	}
	if (side != 1 && side != -1) || in.SnapshotID == "" || in.At <= 0 || in.Chart.At != in.At ||
		(in.Kind != "Day" && in.Kind != "Night") || in.Chart.Scene.ID == "" ||
		in.Chart.Scene.Contract == "" || in.Chart.Scene.Start <= 0 {
		return fmt.Errorf("保有方向/場/判断時計が不正です")
	}
	c := in.Current
	if c.Reference != "" && c.Reference != "NK225" || c.Time < 0 || c.Time > in.At ||
		c.Received < 0 || c.Received > in.At || c.SourceLine < 0 ||
		c.Time > 0 && (c.SourceIndex < 0 || c.SourceLine <= 0) || c.Last < 0 || c.Bid < 0 || c.Ask < 0 {
		return fmt.Errorf("現在原行の市場/時計/出典/価格が不正です")
	}
	for _, support := range []struct{ own, peer float64 }{{c.Buy.OwnAt, c.Buy.PeerAt}, {c.Sell.OwnAt, c.Sell.PeerAt}} {
		if support.own < 0 || support.peer < 0 || support.own > c.Time || support.peer > c.Time {
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

// numberPointer は入力を参照しない有限な値copyを作ります。
//
// 引数: value(float64)は記録する既知値です。
// 返り値: *float64は独立値。派生演算の非有限は呼出側で検査します。
func numberPointer(value float64) *float64 { return &value }

// AssessHeldTechnicalExit はX5の現在状態を判定し、金融active/freeを捏造しません。
//
// 引数: input(TechnicalGateInput)は固定96公開型、side(int)は実保有方向±1です。
// 返り値: HeldAssessment/errorは個別品質/三条件/出典と最終純判断、又は破損入力です。
func AssessHeldTechnicalExit(input TechnicalGateInput, side int) (HeldAssessment, error) {
	if err := validateHeldInput(input, side); err != nil {
		return HeldAssessment{}, err
	}
	c, chart, at, s := input.Current, input.Chart, input.At, float64(side)
	t := chart.Chart.Technical
	currentKnown := c.Reference == "NK225" && c.Time > 0 && c.SourceIndex >= 0 && c.SourceLine > 0 &&
		c.Last > 0 && c.Bid > 0 && c.Ask > c.Bid && at-c.Time <= 15
	threeKnown := chart.Three.DataKnown && t.Bar3End > 0 && at-t.Bar3End < 180
	roleKnown := threeKnown && t.ExitKnown
	evidence := HeldEvidence{SceneID: chart.Scene.ID, Contract: chart.Scene.Contract,
		Current: CurrentQuoteEvidence{c.Reference, c.Time, c.Received, c.SourceIndex, c.SourceLine, c.Last, c.Bid, c.Ask},
		Three:   chart.Three, Quantity: QuantityEvidence{Kind: input.Kind}}
	if c.Time > 0 {
		evidence.PriceAge = numberPointer(at - c.Time)
	}
	if t.Bar3End > 0 {
		evidence.ThreeAge = numberPointer(at - t.Bar3End)
	}
	if roleKnown {
		evidence.SignedCloseEMA = numberPointer(s * (t.Close3 - t.EMA8_3))
		evidence.SignedHistogramDelta = numberPointer(s * (t.Histogram3 - t.PreviousHistogram3))
	}
	quantityKnown, quantity := false, 0.0
	if input.Kind == "Day" {
		v := c.Buy
		if side == -1 {
			v = c.Sell
		}
		evidence.Quantity.Time, evidence.Quantity.Index, evidence.Quantity.OwnAt = c.Time, c.SourceIndex, v.OwnAt
		quantityKnown = currentKnown && v.OFIKnown && v.OwnAt == c.Time
		quantity = v.OFI30
	} else {
		n, v := c.Night, c.Night.Band
		evidence.Quantity.Time, evidence.Quantity.Index = v.Time, v.Index
		quantityKnown = currentKnown && n.Available && n.Window == "E08" && v.QuantityKnown && v.Time == c.Time && v.Index == c.SourceIndex
		if quantityKnown {
			quantity = v.BidRefill + v.AskDeplete - v.AskRefill - v.BidDeplete
			evidence.Quantity.BidRefill, evidence.Quantity.AskRefill = numberPointer(v.BidRefill), numberPointer(v.AskRefill)
			evidence.Quantity.BidDeplete, evidence.Quantity.AskDeplete = numberPointer(v.BidDeplete), numberPointer(v.AskDeplete)
		}
	}
	evidence.Quantity.Known = quantityKnown
	if quantityKnown {
		evidence.Quantity.Value, evidence.SignedQuantity = numberPointer(quantity), numberPointer(s*quantity)
	}
	if !gateFiniteValue(reflect.ValueOf(evidence)) || math.IsInf(quantity, 0) || math.IsNaN(quantity) {
		return HeldAssessment{}, fmt.Errorf("保有技法の派生差分が非有限です")
	}
	checks := []TechnicalGateCheck{
		gateCheck("X5.現在価格時計", currentKnown, true, "Currentの正常BBO/Last正・価格時計15秒以内。金融最新Quoteとの外部bindは別責務"),
		gateCheck("X5.公開3分", threeKnown, true, "当場の既知確定3分・公開済み・足齢180秒未満"),
		gateCheck("X5.P", roleKnown, roleKnown && *evidence.SignedCloseEMA < 0, "保有方向付きClose3-同足EMA8_3がstrict負・等号は不成立"),
		gateCheck("X5.M", roleKnown, roleKnown && *evidence.SignedHistogramDelta < 0, "保有方向付き3分hist増分がstrict負・水準0交差は不要"),
		gateCheck("X5.Q", quantityKnown, quantityKnown && *evidence.SignedQuantity < 0, "同Current出典のDay OFI30又はNight E08差が保有方向へstrict負・約定量ではない"),
	}
	state := gateAnd(checks)
	decision := HeldDecision{Policy: "X5", SnapshotID: input.SnapshotID, At: at, Side: side,
		Known: state.known, Allowed: state.passed, Role: "複合失効", Reason: "価格・勢い・現在量の反対状態が成立"}
	if !state.known {
		decision.Role, decision.Reason = "判定不能", "既知の否定条件はなく必要な公開値が未知"
	} else if !state.passed {
		decision.Role, decision.Reason = "追加退出なし", "公開済みの必要条件が不成立"
	}
	return HeldAssessment{Decision: decision, Checks: checks, Evidence: evidence}, nil
}
