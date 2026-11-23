package miniprotect

import (
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	"testing"
)

// mirrorFixture は所有IDと物理行を持つ単純な手計算対照を作ります。
//
// 引数: なし。返り値: Actor2会計とSource1会計。市場資料は読みません。
func mirrorFixture() (map[string]ActualResult, map[string]native.Ledger) {
	entry := QuoteStamp{Time: 2, Index: 1, SourceLine: 2, Last: 10000, Bid: 9990, Ask: 10000, QuoteOK: true}
	exit := QuoteStamp{Time: 4, Index: 3, SourceLine: 4, Last: 10020, Bid: 10020, Ask: 10030, QuoteOK: true}
	n := native.Ledger{Holds: []native.HoldLedger{{HoldID: "H", EntryID: "N", Parent: "parent", SourceID: "source", Kind: "initial", Side: 1, InitialQuantity: 1}}, Fills: []native.FillRecord{}}
	n.Holds[0].EntryPrice = 10000
	n.Fills = append(n.Fills, native.FillRecord{Action: "new", Side: 1, Quote: entry, Fill: native.Fill{SignalID: "N", HoldID: "H", Quantity: 1, Price: 10000}})
	n.Fills = append(n.Fills, native.FillRecord{Action: "close", Side: -1, Quote: exit, Fill: native.Fill{SignalID: "R", Quantity: 1, Price: 10020}, Allocations: []native.CloseAllocation{{HoldID: "H", Quantity: 1, GrossYen: 2000}}})
	n.Totals.EntryQuantity = 1
	n.Totals.GrossYen = 2000
	books := map[string]ActualResult{}
	for _, cost := range []int{0, 5} {
		cfg := ActorConfig{Policy: "S0", SlipPts: float64(cost), DelaySeconds: 0}
		identity := SourceIdentity{SignalID: "N", Parent: "parent", SourceID: "source", Kind: "initial"}
		b := ActualResult{Positions: []ActualPosition{{ID: "P", Source: identity, SourceHoldID: "H", Side: 1, InitialQuantity: 1, EntryPrice: 10000}}, Fills: []ActualFill{}}
		b.Fills = append(b.Fills, ActualFill{Action: "new", Side: 1, Quantity: 1, Price: 10000, Quote: entry, Source: identity, SourceHoldID: "H", FeeYen: 38.5, SlipYen: float64(cost * 100)})
		b.Fills = append(b.Fills, ActualFill{Action: "close", Side: -1, Quantity: 1, Price: 10020, Quote: exit, Source: identity, SourceHoldID: "H", NativeCloseSignalID: "R", GrossYen: 2000, FeeYen: 38.5, SlipYen: float64(cost * 100)})
		b.Totals = ActualTotals{EntryQuantity: 1, CloseQuantity: 1, GrossYen: 2000, NetYen: 2000 - 77 - float64(200*cost)}
		books[configKey(cfg)] = b
	}
	return books, map[string]native.Ledger{"D164_15": n}
}

// TestMirrorRejectsIdentityMismatch は総額同値でも物理行・所有の違いを検出します。
//
// 引数: t(*testing.T)はテスト実行器。返り値: なし。
func TestMirrorRejectsIdentityMismatch(t *testing.T) {
	books, shadow := mirrorFixture()
	if err := checkMirrors(books, shadow); err != nil {
		t.Fatal(err)
	}
	mutations := []func(*ActualResult){
		func(b *ActualResult) { b.Fills[1].Quote.SourceLine++ },
		func(b *ActualResult) { b.Fills[1].NativeCloseSignalID = "他の返済" },
		func(b *ActualResult) { b.Positions[0].SourceHoldID = "他の所有" },
		func(b *ActualResult) { b.Fills[0].FeeYen = 39 },
	}
	for _, mutate := range mutations {
		books, shadow = mirrorFixture()
		b := books["S0_C0_D0"]
		mutate(&b)
		books["S0_C0_D0"] = b
		if checkMirrors(books, shadow) == nil {
			t.Fatal("総額だけでSource差を通過")
		}
	}
}
