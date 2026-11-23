package minichart

import (
	"fmt"
	"math"
	"sort"
)

// clockEvent は元Sourceのtimerと金融評価を伴わない新規gridを分けます。
type clockEvent struct {
	At   float64
	Grid bool
}

// scheduledEvents は元Force時計を保ち、開始含む/終了含まない5分格子を結びます。
//
// 引数: session(Session)は開始/終了/Forceと米国開始です。
// 返り値: []clockEvent/errorは同時刻Source先行の予定、又は時計不整合です。
func scheduledEvents(session Session) ([]clockEvent, error) {
	if !finiteActual(session.Start, session.End, session.ForceClose, session.USOpen) || session.Start >= session.ForceClose || session.ForceClose > session.End {
		return nil, fmt.Errorf("95予定時計が不正です")
	}
	events := []clockEvent{{At: session.ForceClose}}
	if session.Kind == "Night" {
		if session.USOpen-900 <= session.Start || session.USOpen+900 >= session.ForceClose {
			return nil, fmt.Errorf("95米国時計が場内にありません")
		}
		events = append(events, clockEvent{At: session.USOpen - 900}, clockEvent{At: session.USOpen + 900})
	} else if session.Kind != "Day" {
		return nil, fmt.Errorf("95場種が不正です")
	}
	for at := 300 * math.Ceil(session.Start/300); at < session.End; at += 300 {
		events = append(events, clockEvent{At: at, Grid: true})
	}
	sort.SliceStable(events, func(i, j int) bool {
		if events[i].At != events[j].At {
			return events[i].At < events[j].At
		}
		return !events[i].Grid && events[j].Grid
	})
	return events, nil
}
