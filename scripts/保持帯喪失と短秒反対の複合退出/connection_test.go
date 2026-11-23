// 86派生元: scripts/保持帯の返済側固定否定/connection_test.go
// 86派生元SHA256: 5bdaa14a157672aa2da21e4d173453f27ac7057b8c4203a362869d749efa5518

package far86

import "testing"

// TestC0PhysicalSourceAndHoldBinding は実連番と源連番を分け、同秒別原行を混ぜません。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。買売で保持帯の要求出典と非候補未知を確認します。
func TestC0PhysicalSourceAndHoldBinding(t *testing.T) {
	for _, side := range []int{1, -1} {
		runtime, at := input86Runtime(t, side)
		if err := runtime.advanceTimer(at, false); err != nil {
			t.Fatal(err)
		}
		grid := runtime.result.GridDecisions[0]
		anchor := grid.HoldAnchor
		if !anchor.Known || anchor.QuoteIndex != 0 || anchor.FeatureIndex != 7 || anchor.SourceLine != 20 || anchor.Side != side || anchor.HoldID != 4 {
			t.Fatal("実連番と源連番又は物理出典が混ざりました", anchor)
		}
		other, at := input86Runtime(t, side)
		other.current.SourceLine++
		if err := other.advanceTimer(at, false); err != nil {
			t.Fatal(err)
		}
		grid = other.result.GridDecisions[0]
		if grid.CandidateAccepted || grid.HoldAnchor.Known || grid.Policies["C0"].CandidateAccepted {
			t.Fatal("同秒の別原行を保持帯へ結びました")
		}
	}
}

// TestHoldBindingFailureBeforeOrders は旧C0が通る型内出典破損を発注前に拒否します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。不正Hold IDは旧入口改変ではなく接続の整合性違反として止めます。
func TestHoldBindingFailureBeforeOrders(t *testing.T) {
	for _, side := range []int{1, -1} {
		runtime, at := input86Runtime(t, side)
		if side > 0 {
			runtime.current.Night.Buy.ID = 0
		} else {
			runtime.current.Night.Sell.ID = 0
		}
		if err := runtime.bank.Advance(at); err != nil {
			t.Fatal(err)
		}
		old, err := Decide(at, runtime.last, runtime.bank.View(), runtime.current)
		if err != nil || !old.Allowed {
			t.Fatal("人工の旧C0不変という前提を失いました", err)
		}
		if err = runtime.advanceTimer(at, false); err == nil {
			t.Fatal("出典の不正な候補を受理しました")
		}
		for _, book := range runtime.books {
			if len(book.Result().Orders) != 0 {
				t.Fatal("保持帯検査失敗後に実注文がありました")
			}
		}
	}
}

// TestNoClockCandidateNormalizesHoldUnknown は純C0成立でも時計で不供給なら保持帯を未知にします。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。公開snapshotと候補供給・保持帯knownを分けて確認します。
func TestNoClockCandidateNormalizesHoldUnknown(t *testing.T) {
	runtime, at := input86Runtime(t, 1)
	runtime.forceDone = true
	if err := runtime.advanceTimer(at, false); err != nil {
		t.Fatal(err)
	}
	grid := runtime.result.GridDecisions[0]
	unknown, err := BuildHoldAnchor(at, runtime.last, runtime.current, 0)
	if err != nil {
		t.Fatal(err)
	}
	if !grid.Policies["C0"].Allowed || grid.CandidateAccepted || grid.ClockAllowed || grid.HoldAnchor != unknown {
		t.Fatal("時計で不供給の既知構造を保持帯knownへ混ぜました", grid)
	}
}
