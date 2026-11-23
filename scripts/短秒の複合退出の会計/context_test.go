// 由来: work/101保有失効の金融案/context_test.go
// 由来SHA256: 6ce679d341e4303405c1d3933aee287a14eb7fb232151c82c5d6ba94052ead39
// 由来100固定金融: scripts/FAR利益化前後の保護/context_test.go
// 由来SHA256: 5e8934bf99bf32d96219f4d4e0afee57009f2922811f572239e3194fa1740fda
// 手製現在技法文脈由来99: scripts/FAR背景と勢いと数量の入口/connection_test.go
// 由来SHA256: d02c095e59afda12085a9494c22d6959641725a1a5c9bcc73f2d2284349db7e9
package minishortfinance

import (
	"fmt"
	e3 "github.com/masayoshi4649/SessionTradeExecuter/minie3"
	"math"
)

// context100 は当候補の公開時計と原行を手製技法snapshotへ結びます。
//
// 引数: c(EntryCandidate)、mode(string)は金融が作る現在候補と境界名です。
// 返り値: e3.TechnicalGateInputは当枠公開値です。Source/方向/量を変更しません。
func context100(c EntryCandidate, mode string) e3.TechnicalGateInput {
	in, _ := technicalFixture99(c.Side, "A")
	in.At, in.SnapshotID = c.At, fmt.Sprintf("人工場-G%.0f", c.At)
	in.Chart.Scene.ID = "人工場"
	in.Chart.Scene.Start = c.At - 18000
	for i := range in.Recent3 {
		v := &in.Recent3[i]
		end := math.Floor(c.At/180)*180 - float64(2-i)*180
		v.Scene = in.Chart.Scene
		v.At, v.ObservedClock = end, c.At
		v.Chart.Technical.Bar3End, v.Chart.Technical.Bar15End = end, math.Floor(end/900)*900
		v.Chart.PreviousBar3End = end - 180
		v.LastInput.Time = end - 1
		v.Three.BarEnd, v.Three.AvailableAt, v.Three.ObservedClock, v.Three.LastSource.Time = end, end, c.At, end-1
		v.Fifteen.BarEnd, v.Fifteen.AvailableAt, v.Fifteen.ObservedClock, v.Fifteen.LastSource.Time = math.Floor(end/900)*900, math.Floor(end/900)*900, c.At, math.Floor(end/900)*900-1
	}
	in.Chart = in.Recent3[2]
	in.Chart.At = c.At
	in.Current.Time, in.Current.Received = c.Quote.Time, c.Quote.Time
	in.Current.SourceIndex, in.Current.SourceLine = c.Quote.Index, c.Quote.SourceLine
	in.Current.Last, in.Current.Bid, in.Current.Ask = c.Quote.Last, c.Quote.Bid, c.Quote.Ask
	in.Current.Buy.OwnAt, in.Current.Sell.OwnAt = c.Quote.Time, c.Quote.Time
	for k, v := range in.Current.Buy.Windows {
		v.CurrentAt, v.EndpointAt = c.Quote.Time, c.Quote.Time-5
		in.Current.Buy.Windows[k] = v
	}
	in.Current.Night.Time, in.Current.Night.Index = c.Quote.Time, c.Quote.Index
	in.Current.Night.Band.Time, in.Current.Night.Band.Index, in.Current.Night.Band.StartTime = c.Quote.Time, c.Quote.Index, c.Quote.Time-5
	switch mode {
	case "未知":
		in.Chart.Chart.Technical.Histogram3 = 0
		in.Chart.Chart.Technical.ExitKnown = false
		in.Chart.Chart.Technical.SpikeKnown = false
	case "否定", "否定優先":
		v := &in.Chart.Chart.Technical
		v.EMA8_3 = v.EMA21_3 - float64(c.Side)*10
		if mode == "否定優先" {
			v.ExitKnown = false
			v.SpikeKnown = false
		}
	case "スパイク":
		v := &in.Chart.Chart.Technical
		v.TR3 = 41
		v.ATR3 = 20
		v.PreviousATR3 = 20
		if c.Side > 0 {
			v.RSI3, v.PreviousRSI3 = 90, 74
		} else {
			v.RSI3, v.PreviousRSI3 = 10, 26
		}
	}
	in.Recent3[2].Chart = in.Chart.Chart
	return in
}
