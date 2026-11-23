package far87

import (
	"reflect"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far84 "github.com/masayoshi4649/SessionTradeExecuter/research84"
	far86 "github.com/masayoshi4649/SessionTradeExecuter/research86"
)

// TestReplayC0AndSourceFullPool はSourceを全行運転しても固定C0入力を変えません。
//
// 引数: t(*testing.T)は同じ人工原板を新旧へ渡す検査器です。
// 返り値: ありません。C0全Decisionと全Source互換の件数・順次指紋を確認します。
func TestReplayC0AndSourceFullPool(t *testing.T) {
	manifest := input87MultiFixture(t, false)
	a, b := far80.NewTechnicalBank(), far80.NewTechnicalBank()
	input := manifest.Sessions[0]
	current, err := Replay(manifest.Root, input, a)
	if err != nil {
		t.Fatal(err)
	}
	previous, err := far86.Replay(manifest.Root, input, b)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(current.Quality, previous.Quality) || len(current.GridDecisions) != len(previous.GridDecisions) {
		t.Fatal("Source追加で品質・定時を変更")
	}
	for i, grid := range current.GridDecisions {
		old := previous.GridDecisions[i]
		expected, err := far84.Refine(old.Decision, "C0")
		if err != nil {
			t.Fatal(err)
		}
		if grid.At != old.At || grid.Window != old.Window || grid.ClockAllowed != old.ClockAllowed || grid.BlockReason != old.BlockReason || grid.StructureAnchor != old.StructureAnchor || !reflect.DeepEqual(grid.C0, expected) {
			t.Fatal("Source追加でC0全判断を変更", i)
		}
	}
	eq := current.SourceEquivalence
	count := 0
	for _, n := range current.ReferenceCounts {
		count += n
	}
	if eq.StepFrames != count || count == 0 || eq.GridFrames != len(current.GridDecisions) || eq.ForceFrames == 0 || eq.CurrentSHA256 != eq.LegacySHA256 || eq.Mismatches != 0 {
		t.Fatal("固定80の全Source比較が欠落", eq, current.ReferenceCounts)
	}
}
