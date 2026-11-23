package minigrid

import (
	"testing"
	"time"
)

// TestScheduledClocks は全予定枠・端点とForce/grid同時刻の順を確認します。
//
// 引数: t(*testing.T)はGo試験器です。
// 返り値: なし。不整合は試験失敗です。
func TestScheduledClocks(t *testing.T) {
	stamp := func(value string) float64 {
		at, err := time.Parse(time.RFC3339, value)
		if err != nil {
			t.Fatal(err)
		}
		return float64(at.Unix())
	}
	cases := []struct {
		kind, start, end, force, us string
		slots                       int
	}{
		{"Day", "2026-09-21T08:45:00+09:00", "2026-09-21T15:45:00+09:00", "2026-09-21T15:35:00+09:00", "", 84},
		{"Night", "2026-09-21T17:00:00+09:00", "2026-09-22T06:00:00+09:00", "2026-09-22T05:50:00+09:00", "2026-09-21T22:30:00+09:00", 156},
		{"Night", "2026-11-02T17:00:00+09:00", "2026-11-03T06:00:00+09:00", "2026-11-03T05:50:00+09:00", "2026-11-02T23:30:00+09:00", 156},
	}
	for _, tc := range cases {
		session := Session{ID: "時計人工", Kind: tc.kind, Start: stamp(tc.start), End: stamp(tc.end), ForceClose: stamp(tc.force)}
		if tc.us != "" {
			session.USOpen = stamp(tc.us)
		}
		events, err := scheduledEvents(session)
		if err != nil {
			t.Fatal(err)
		}
		grid, forces, previous := 0, 0, session.Start-1
		for i, event := range events {
			if event.At < previous {
				t.Fatal("予定が逆行")
			}
			if i > 0 && event.At == events[i-1].At && !event.Grid {
				t.Fatal("同時刻のForceがgridより後")
			}
			previous = event.At
			if event.Grid {
				grid++
				if event.At < session.Start || event.At >= session.End || int64(event.At)%300 != 0 {
					t.Fatal("grid端点不整合")
				}
			} else {
				forces++
			}
		}
		wantForce := 1
		if tc.kind == "Night" {
			wantForce = 3
		}
		if grid != tc.slots || forces != wantForce {
			t.Fatalf("枠数 %s grid=%d source=%d", tc.kind, grid, forces)
		}
	}
}
