package far80

import (
	"math"
	"testing"
	"time"
)

// tokyoArtificial は人工の日本時刻をUnix秒へ写します。
//
// 引数: t(*testing.T)は検査、value(string)はYYYY-MM-DD HH:MMです。
// 返り値: float64は人工のUnix秒です。取引日カレンダーを読みません。
func tokyoArtificial(t *testing.T, value string) float64 {
	t.Helper()
	zone, err := time.LoadLocation("Asia/Tokyo")
	if err != nil {
		t.Fatal(err)
	}
	at, err := time.ParseInLocation("2006-01-02 15:04", value, zone)
	if err != nil {
		t.Fatal(err)
	}
	return float64(at.Unix())
}

// TestScheduleGrid は初回skip・端点・夜の日付越えを確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。人工日付だけを使用します。
func TestScheduleGrid(t *testing.T) {
	for _, example := range []struct {
		id, first, last string
		count           int
	}{
		{"2026-11-06_Day", "2026-11-06 09:15", "2026-11-06 15:15", 25},
		{"2026-11-06_Night", "2026-11-06 17:30", "2026-11-07 05:30", 49},
		{"2026-12-31_Night", "2026-12-31 17:30", "2027-01-01 05:30", 49},
	} {
		values, err := ScheduledTimes(example.id)
		if err != nil {
			t.Fatal(err)
		}
		if len(values) != example.count || values[0] != tokyoArtificial(t, example.first) || values[len(values)-1] != tokyoArtificial(t, example.last) {
			t.Fatalf("定時の数又は端点が不正: %s", example.id)
		}
		for i := 1; i < len(values); i++ {
			if values[i]-values[i-1] != 900 {
				t.Fatal("15分でない判断時計")
			}
		}
		// ----------------------------------------
		// 返り値の配列を変えても、次の呼出へ共有されません。
		values[0] = -1
		again, err := ScheduledTimes(example.id)
		if err != nil || again[0] != tokyoArtificial(t, example.first) {
			t.Fatal("定時配列が呼出間で共有")
		}
	}
	for _, invalid := range []string{"", "2026-02-30_Day", "2026-1-01_Day", "2026-11-06_day", "2026-11-06_Day_extra"} {
		if _, err := ScheduledTimes(invalid); err == nil {
			t.Fatalf("不正な場IDを受理: %s", invalid)
		}
	}
}

// TestScheduleDST はNY09:30のDST移行前後を固定の日本時計へ照合します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。ネットワーク時計や実市場へ接続しません。
func TestScheduleDST(t *testing.T) {
	for _, example := range []struct{ day, expected string }{
		{"2026-03-06", "2026-03-06 23:30"},
		{"2026-03-09", "2026-03-09 22:30"},
		{"2026-10-30", "2026-10-30 22:30"},
		{"2026-11-02", "2026-11-02 23:30"},
	} {
		at, err := USOpen(example.day)
		if err != nil || at != tokyoArtificial(t, example.expected) {
			t.Fatalf("DST時計が不一致: %s %v %v", example.day, at, err)
		}
	}
	for _, invalid := range []string{"", "2026-02-30", "2026-1-01", "2026-11-06_Night"} {
		if _, err := USOpen(invalid); err == nil {
			t.Fatal("不正な米国開始日を受理")
		}
	}
}

// TestScheduleWindow は静観区間の等号と場種を確認します。
//
// 引数: t(*testing.T)はGoの検査器です。
// 返り値: ありません。開始15分前から静観し、15分後の等号で後枠へ移ります。
func TestScheduleWindow(t *testing.T) {
	for _, example := range []struct {
		at       float64
		kind, id string
	}{
		{99, "Day", "D164_15"}, {99, "Night", "P164_06"},
		{100, "Night", "静観"}, {1899.999, "Night", "静観"}, {1900, "Night", "U165_03"},
	} {
		id, err := WindowMethod(example.at, 1000, example.kind)
		if err != nil || id != example.id {
			t.Fatalf("時間枠が不一致: %+v %s %v", example, id, err)
		}
	}
	if _, err := WindowMethod(1000, 1000, "不明"); err == nil {
		t.Fatal("不正な場種を受理")
	}
	if _, err := WindowMethod(math.NaN(), 1000, "Day"); err == nil {
		t.Fatal("非有限時計を受理")
	}
	if _, err := WindowMethod(1000, math.Inf(1), "Night"); err == nil {
		t.Fatal("非有限米国開始を受理")
	}
}
