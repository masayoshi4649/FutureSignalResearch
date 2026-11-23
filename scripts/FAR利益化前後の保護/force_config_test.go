package minigrossguard100

import (
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	"testing"
)

// Test100ForceCancelsUnfilled は利益観測の無い実新規予約をSource Forceで取消します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Source取得済みでも実未取得ならHG/利益flag/架空約定を作りません。
func Test100ForceCancelsUnfilled(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, exit := range []string{"", "H0", "HG"} {
			for _, cost := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					s := session()
					grid := s.Start + 1800
					s.ForceClose = grid + .5
					b, e := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", HarvestPolicy: exit, SlipPts: cost, DelaySeconds: delay})
					if e != nil {
						t.Fatal(e)
					}
					src := newSource()
					index := int64(0)
					feed := func(at float64, newBirth bool) {
						o := observation(at, 0, side, index, false)
						q := stamp(o, index+20)
						var batch NativeBatch
						if newBirth {
							batch = src.step(q, []native.Signal{birth("Force未取得", side, 5)})
						} else {
							batch = src.step(q, nil)
						}
						if e := b.OnNativeStep(o, index+20, []NativeBatch{batch}); e != nil {
							t.Fatal(e)
						}
						index++
					}
					feed(grid-1, true)
					feed(grid-.9, false)
					if e = b.OnEntryGridWithGate(grid, entryGate100); e != nil {
						t.Fatal(e)
					}
					before := b.Snapshot()
					if len(before.Orders) != 1 || before.Orders[0].Status != "pending" || len(before.Positions) != 0 {
						t.Fatal("実未取得の準備")
					}
					if e = b.OnNativeForce(s.ForceClose, []NativeBatch{NativeBatch(src.force(s.ForceClose))}); e != nil {
						t.Fatal(e)
					}
					after := b.Snapshot()
					if len(after.Positions) != 0 || len(after.Fills) != 0 || after.Orders[0].Status != "cancelled" || after.Account.Count != before.Account.Count {
						t.Fatal("Force取消/偽評価")
					}
					feed(s.ForceClose, false)
					feed(s.ForceClose+1, false)
					final, e := b.Finish()
					if e != nil {
						t.Fatal(e)
					}
					if !final.Complete || final.Metrics.CancelledEntries != 1 || final.Metrics.GrossGuardExitRequests != 0 || final.Metrics.ProtectionActivatedPositions != 0 || final.Totals.EntryQuantity != 0 || final.Totals.NetYen != 0 {
						t.Fatal("未取得のflag/費用偽装", final)
					}
				}
			}
		}
	}
}

// Test100PolicyAndSnapshot は入口固定と新optional欄の不変・深い複写を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。HG名をH0へ置き換えず、Snapshot経由の書換えを許しません。
func Test100PolicyAndSnapshot(t *testing.T) {
	s := session()
	base := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", HarvestPolicy: "HG"}
	for _, kind := range []string{"Gate空", "E3", "AB", "risk", "P1", "B5", "未知出口", "費用", "遅延"} {
		cfg := base
		switch kind {
		case "Gate空":
			cfg.GatePolicy = ""
		case "E3":
			cfg.GatePolicy = "E3"
		case "AB":
			cfg.GatePolicy = "AB"
		case "risk":
			cfg.RiskPolicy = "R05"
		case "P1":
			cfg.Policy = "P1"
		case "B5":
			cfg.EntryTiming = "B5"
		case "未知出口":
			cfg.HarvestPolicy = "H1"
		case "費用":
			cfg.SlipPts = 1
		case "遅延":
			cfg.DelaySeconds = 2
		}
		if _, e := NewActualBook(s, cfg); e == nil {
			t.Fatal("候補外設定を許可", kind)
		}
	}
	fixture, _ := wave100(t, 1, "HG予約後正益")
	key := "HG_E3S_B5Q_P0_C5_D1"
	p := fixture.Actors[key].Positions[0]
	if p.GrossGuard == nil || p.GrossGuard.ProfitTransition == nil || p.GrossGuard.FirstHit == nil {
		t.Fatal("必要出典なし")
	}
	copy := valueCopy(fixture.Actors[key])
	copy.Positions[0].GrossGuard.Activation.GainPoints = 123456
	copy.Orders[1].GrossGuardPoint.GainPoints = 123456
	if fixture.Actors[key].Positions[0].GrossGuard.Activation.GainPoints == 123456 || fixture.Actors[key].Orders[1].GrossGuardPoint.GainPoints == 123456 {
		t.Fatal("HG出典の浅い複写")
	}
}
