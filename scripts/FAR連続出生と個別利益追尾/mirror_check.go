package miniprotect

import (
	"fmt"
	"reflect"

	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

type mirrorKey struct {
	Action, Signal, Hold string
	Side                 int
	Time, Price          float64
	Index, Line          int64
}
type mirrorAmount struct {
	Quantity int
	Gross    float64
}

// checkMirrors はD0無保護の全約定をSourceの所有別に結び、金額相殺の一致を拒みます。
//
// 引数: actors(map[string]ActualResult)、shadows(map[string]native.Ledger)は終了した保存値。
// 返り値: errorは新規/返済原行・方向・量・価格・所有・費用の不一致です。
func checkMirrors(actors map[string]ActualResult, shadows map[string]native.Ledger) error {
	want := map[mirrorKey]mirrorAmount{}
	sourceHolds := map[string]native.HoldLedger{}
	gross, qty := 0.0, 0
	for _, book := range shadows {
		gross += book.Totals.GrossYen
		qty += book.Totals.EntryQuantity
		for _, h := range book.Holds {
			sourceHolds[h.HoldID] = h
		}
		for _, f := range book.Fills {
			if f.Action == "new" {
				key := mirrorKey{f.Action, f.Fill.SignalID, f.Fill.HoldID, f.Side, f.Quote.Time, f.Fill.Price, f.Quote.Index, f.Quote.SourceLine}
				value := want[key]
				value.Quantity += f.Fill.Quantity
				want[key] = value
			} else {
				for _, a := range f.Allocations {
					key := mirrorKey{f.Action, f.Fill.SignalID, a.HoldID, f.Side, f.Quote.Time, f.Fill.Price, f.Quote.Index, f.Quote.SourceLine}
					value := want[key]
					value.Quantity += a.Quantity
					value.Gross += a.GrossYen
					want[key] = value
				}
			}
		}
	}
	for _, cost := range []int{0, 5} {
		actor, ok := actors[fmt.Sprintf("S0_C%d_D0", cost)]
		if !ok {
			return fmt.Errorf("D0無保護対照が欠落")
		}
		got := map[mirrorKey]mirrorAmount{}
		seenHolds := map[string]bool{}
		for _, p := range actor.Positions {
			h, ok := sourceHolds[p.SourceHoldID]
			if !ok || seenHolds[p.SourceHoldID] || p.Source.SignalID != h.EntryID || p.Source.Parent != h.Parent || p.Source.SourceID != h.SourceID || p.Source.Kind != h.Kind || p.InitialQuantity != h.InitialQuantity || p.Side != h.Side || p.EntryPrice != h.EntryPrice || p.Quantity != 0 {
				return fmt.Errorf("D0のSource所有対応差: %s", p.SourceHoldID)
			}
			seenHolds[p.SourceHoldID] = true
		}
		if len(seenHolds) != len(sourceHolds) {
			return fmt.Errorf("D0新規所有集合が不一致")
		}
		for _, f := range actor.Fills {
			signal := f.Source.SignalID
			if f.Action == "close" {
				signal = f.NativeCloseSignalID
			}
			if signal == "" {
				return fmt.Errorf("D0の元Signal対応が空")
			}
			key := mirrorKey{f.Action, signal, f.SourceHoldID, f.Side, f.Quote.Time, f.Price, f.Quote.Index, f.Quote.SourceLine}
			value := got[key]
			value.Quantity += f.Quantity
			value.Gross += f.GrossYen
			got[key] = value
			if f.FeeYen != float64(f.Quantity)*38.5 || f.SlipYen != float64(f.Quantity*cost*100) {
				return fmt.Errorf("D0の片道費用差")
			}
		}
		if !reflect.DeepEqual(got, want) {
			return fmt.Errorf("D0全FillのSource所有/原行/量/価格が不一致: C%d", cost)
		}
		if actor.Totals.GrossYen != gross || actor.Totals.EntryQuantity != qty || actor.Totals.CloseQuantity != qty || actor.Totals.NetYen != gross-float64(qty)*(77+float64(200*cost)) {
			return fmt.Errorf("D0総額と費用の差: C%d", cost)
		}
	}
	return nil
}
