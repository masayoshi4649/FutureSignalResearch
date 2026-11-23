package far80

import (
	"fmt"
	"strings"
	"time"
	_ "time/tzdata"
)

// ScheduledTimes は初回を飛ばした場内の15分判断時計を作ります。
//
// 引数: sessionID(string)はYYYY-MM-DD_Day又はYYYY-MM-DD_Nightです。
// 返り値: []float64は時系列のUnix秒、errorは不正な場IDです。
func ScheduledTimes(sessionID string) ([]float64, error) {
	parts := strings.Split(sessionID, "_")
	if len(parts) != 2 || (parts[1] != "Day" && parts[1] != "Night") {
		return nil, fmt.Errorf("場IDの形式が不正です: %s", sessionID)
	}
	zone, err := time.LoadLocation("Asia/Tokyo")
	if err != nil {
		return nil, fmt.Errorf("日本時計の読込: %w", err)
	}
	day, err := time.ParseInLocation("2006-01-02", parts[0], zone)
	if err != nil || day.Format("2006-01-02") != parts[0] {
		return nil, fmt.Errorf("場IDの日付が不正です: %s", sessionID)
	}
	start := day.Add(9*time.Hour + 15*time.Minute)
	end := day.Add(15*time.Hour + 15*time.Minute)
	if parts[1] == "Night" {
		start = day.Add(17*time.Hour + 30*time.Minute)
		end = day.AddDate(0, 0, 1).Add(5*time.Hour + 30*time.Minute)
	}
	values := make([]float64, 0, 49)
	for at := start; !at.After(end); at = at.Add(15 * time.Minute) {
		values = append(values, float64(at.Unix()))
	}
	return values, nil
}

// USOpen は同日ニューヨーク09:30を自動DSTでUnix時計へ写します。
//
// 引数: day(string)はナイトの開始日YYYY-MM-DDです。
// 返り値: float64は米国開始Unix秒、errorは不正日付又は時計設定です。
func USOpen(day string) (float64, error) {
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		return 0, fmt.Errorf("米国時計の読込: %w", err)
	}
	date, err := time.ParseInLocation("2006-01-02", day, zone)
	if err != nil || date.Format("2006-01-02") != day {
		return 0, fmt.Errorf("米国開始の日付が不正です: %s", day)
	}
	at := time.Date(date.Year(), date.Month(), date.Day(), 9, 30, 0, 0, zone)
	return float64(at.Unix()), nil
}

// WindowMethod は場種と米国開始相対時計から参照する手法を返します。
//
// 引数: at/usOpen(float64)は現在/米国開始Unix秒、kind(string)はDay又はNightです。
// 返り値: stringはD164_15/P164_06/静観/U165_03、errorは非有限時計又は不正場種です。
func WindowMethod(at, usOpen float64, kind string) (string, error) {
	if !finiteTechnical(at) || !finiteTechnical(usOpen) {
		return "", fmt.Errorf("時間枠の時計が非有限です")
	}
	switch kind {
	case "Day":
		return "D164_15", nil
	case "Night":
		if at < usOpen-900 {
			return "P164_06", nil
		}
		if at < usOpen+900 {
			return "静観", nil
		}
		return "U165_03", nil
	default:
		return "", fmt.Errorf("場種が不正です: %s", kind)
	}
}
