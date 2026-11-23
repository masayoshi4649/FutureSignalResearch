package far87

import "testing"

// TestSourceWholePoolEquivalence はmetadata投影が候補を落とすと同値判定を止めます。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。2玉・元追加・返済通知を丸ごと比較し、旧新同時の変更も指紋へ反映します。
func TestSourceWholePoolEquivalence(t *testing.T) {
	a := ReferenceLot{ID: "A", Quantity: 17, Kind: "initial", Side: 1, At: 100, Entry: 1000}
	b := ReferenceLot{ID: "B", Quantity: 12, Kind: "source_add", Side: 1, At: 101, Entry: 1010}
	close := ReferenceClose{ID: "C", ReferenceID: "A", Before: 17, Quantity: 5, Reason: "Source部分返済"}
	snapshot := ReadSnapshot{Method: "NK225_D164_15", At: 102, SourceIndex: 7, Started: true, Lots: []ReadLot{{Reference: a}, {Reference: b}}, Closes: []ReferenceClose{close}}
	frame := projectedFrame(snapshot)
	r := &replayRuntime{result: &ReplayResult{}}
	for _, phase := range []string{"step", "force", "grid"} {
		if err := r.compareSource(phase, "D164_15", 103, snapshot, frame, frame); err != nil {
			t.Fatal(err)
		}
	}
	eq := r.result.SourceEquivalence
	if eq.StepFrames != 1 || eq.ForceFrames != 1 || eq.GridFrames != 1 || eq.Mismatches != 0 || len(eq.CurrentSHA256) != 64 || eq.CurrentSHA256 != eq.LegacySHA256 {
		t.Fatal("全pool指紋・件数不一致", eq)
	}
	for _, kind := range []string{"metadata玉脱落", "旧玉減量", "順序変更", "返済通知脱落"} {
		bad := snapshot
		bad.Lots = append([]ReadLot{}, snapshot.Lots...)
		old := ReferenceFrame{Lots: append([]ReferenceLot{}, frame.Lots...), Closes: append([]ReferenceClose{}, frame.Closes...)}
		switch kind {
		case "metadata玉脱落":
			bad.Lots = bad.Lots[:1]
		case "旧玉減量":
			old.Lots[0].Quantity--
		case "順序変更":
			old.Lots[0], old.Lots[1] = old.Lots[1], old.Lots[0]
		case "返済通知脱落":
			old.Closes = []ReferenceClose{}
		}
		x := &replayRuntime{result: &ReplayResult{}}
		if err := x.compareSource("step", "D164_15", 103, bad, frame, old); err == nil || x.result.SourceEquivalence.Mismatches != 1 {
			t.Fatal("Source全pool破損を通過", kind, err)
		}
	}
	changed := snapshot
	changed.Lots = append([]ReadLot{}, snapshot.Lots...)
	changed.Lots[0].Reference.Quantity--
	x := &replayRuntime{result: &ReplayResult{}}
	newFrame := projectedFrame(changed)
	for _, phase := range []string{"step", "force", "grid"} {
		if err := x.compareSource(phase, "D164_15", 103, changed, newFrame, newFrame); err != nil {
			t.Fatal(err)
		}
	}
	if x.result.SourceEquivalence.CurrentSHA256 == eq.CurrentSHA256 {
		t.Fatal("Source数量変更が順次指紋へ反映されません")
	}
}
