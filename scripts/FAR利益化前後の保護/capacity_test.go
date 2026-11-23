package minigrossguard100

import (
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	"testing"
)

// Test100CapacityBothSides は片側10の予約込み上限と反対側余力を公開APIで確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Source器具は手製通知のみで、FAR戦略/価格入力は読みません。
func Test100CapacityBothSides(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, exit := range []string{"", "H0", "HG"} {
			policy := "E3S"
			for _, cost := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					s := session()
					grid := s.Start + 1800
					b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: exit, GatePolicy: policy, SlipPts: cost, DelaySeconds: delay})
					if err != nil {
						t.Fatal(err)
					}
					x := newSource()
					index := int64(0)
					feed := func(at float64, signals ...native.Signal) {
						o := observation(at, 0, side, index, false)
						q := stamp(o, index+20)
						batch := x.step(q, signals)
						if err := b.OnNativeStep(o, index+20, []NativeBatch{batch}); err != nil {
							t.Fatal(err)
						}
						index++
					}
					callGrid := func(at float64) {
						var callback EntryGate
						if policy != "" {
							callback = func(c EntryCandidate) (GateDecision, error) {
								a, err := AssessEntryTechnical(context100(c, "正常"), c, policy)
								d := a.Decision
								return GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, err
							}
						}
						if err := b.OnEntryGridWithGate(at, callback); err != nil {
							t.Fatal(err)
						}
					}
					feed(grid-1, birth("同側先行", side, 8), birth("反対先行", -side, 10))
					feed(grid - .9)
					callGrid(grid)
					if b.available(side) != 2 || b.available(-side) != 0 {
						t.Fatal("新規予約だけで余力を二重使用")
					}
					feed(grid)
					feed(grid + 1)
					feed(grid+299, birth("同側追加", side, 5), birth("反対超過", -side, 1))
					feed(grid + 299.1)
					callGrid(grid + 300)
					r := b.Snapshot()
					if r.EntryOpportunities[2].Requested != 2 || r.EntryOpportunities[3].Requested != 0 || b.available(side) != 0 || b.available(-side) != 0 {
						t.Fatal("min又は両側上限", r.EntryOpportunities)
					}
					feed(grid + 300)
					feed(grid + 301)
					feed(grid+302, closeSignal("Source部分", "玉-同側先行", side, 3))
					if b.available(side) != 0 {
						t.Fatal("返済予約を所有から先引きして余力を増やした")
					}
					feed(grid + 303)
					before := b.Snapshot()
					if err := b.OnNativeForce(s.ForceClose, []NativeBatch{x.force(s.ForceClose)}); err != nil {
						t.Fatal(err)
					}
					if len(before.Fills) != len(b.Snapshot().Fills) {
						t.Fatal("Force同時fill")
					}
					feed(s.ForceClose)
					feed(s.ForceClose + 1)
					final, err := b.Finish()
					if err != nil {
						t.Fatal(err)
					}
					if !final.Complete || final.Totals.EntryQuantity != 20 || final.Totals.CloseQuantity != 20 || final.Totals.OpenBuy != 0 || final.Totals.OpenSell != 0 || final.Metrics.CapClippedEntries != 1 || final.Metrics.CapRejectedEntries != 1 {
						t.Fatal("容量/最終所有", final.Totals, final.Metrics)
					}
				}
			}
		}
	}
}
