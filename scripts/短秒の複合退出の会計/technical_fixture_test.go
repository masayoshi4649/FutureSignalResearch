// 由来: work/101保有失効の金融案/technical_fixture_test.go
// 由来SHA256: bfa321fb033e89f494a17d5d6bd4cdc3b5f80fa3377e4e7f46e8fb294d11ccdf
// 由来100固定金融: scripts/FAR利益化前後の保護/technical_fixture_test.go
// 由来SHA256: 26de95b271e41f30ccad89d8f0f308c7f35fab35ddde2000873e659f0a7bf06d
// 人工fixture由来99: scripts/FAR背景と勢いと数量の入口/technical_fixture_test.go
// 由来SHA256: fa83dd7b63fadf220712872499c1900ad87d884d267634f4e07d3e11def7e3bf
// 手製技法fixture由来: work/99純技法案/fixture_test.go
// 由来SHA256: c12a2b02f3597d75201e6dd2de44c6d5be3a66829a934dea96218632a214f672
// 人工fixtureだけを固定96 test（SHA3bf1b7d81c10989937f1096c8564185b621305032e39e3a1716938a1e9782e2a）から派生。
package minishortfinance

import (
	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	fixed96 "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
	"math"
)

type TechnicalGateInput = fixed96.TechnicalGateInput

// technicalFixture99 は実市場を読まず、公開出典付きの順行又は反転候補を作ります。
//
// 引数: side(int)は±1、role(string)はA又はBです。
// 返り値: TechnicalGateInput/fixed96.EntryCandidateは値型の人工入力です。
func technicalFixture99(side int, role string) (TechnicalGateInput, fixed96.EntryCandidate) {
	const at = 36000.0
	scene := chartwarmup96.Scene{ID: "人工場", Contract: "人工限月", Start: 18000}
	snapshots := make([]chartwarmup96.Snapshot, 3)
	for i := range snapshots {
		end := at - float64(2-i)*180
		close := 1000 + float64(i)*10
		em8 := 990 + float64(i)*10
		if i == 0 && role == "B" {
			em8 = 1000
		}
		v := far80.TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true,
			EMA8_3: em8, EMA21_3: em8 - 10, EMA8_15: 1010, EMA21_15: 1000,
			RSI3: 80 + float64(i), PreviousRSI3: 79 + float64(i), Histogram3: 2, PreviousHistogram3: 1,
			Close3: close, TR3: 20, ATR3: 20, PreviousATR3: 20, Bar3End: end, Bar15End: math.Floor(end/900) * 900}
		if role == "B" {
			v.EMA8_15, v.EMA21_15 = 990, 1000
		}
		evidence := func(barEnd float64) chartwarmup96.BarEvidence {
			return chartwarmup96.BarEvidence{BarEnd: barEnd, AvailableAt: barEnd, ObservedClock: at + 100,
				Rows: 1, DataKnown: true, HasLastSource: true,
				LastSource: chartwarmup96.SourceStamp{Time: barEnd - 1, Index: 9000 + int64(i), Line: 10000 + int64(i), Last: close, Valid: true}}
		}
		snapshots[i] = chartwarmup96.Snapshot{Scene: scene, At: end, HasObservedClock: true, ObservedClock: at + 100,
			HasLastInput: true, LastInput: chartwarmup96.SourceStamp{Time: end - 1, Index: 9000 + int64(i), Line: 10000 + int64(i), Last: close, Valid: true},
			Chart: far82.ChartView{Technical: v, PreviousClose3: close - 10, PreviousEMA8_3: em8 - 10, PreviousBar3End: end - 180, Previous3Known: true},
			Three: evidence(end), Fifteen: evidence(v.Bar15End)}
	}
	q := fixed96.QuoteStamp{Time: at - 1, Index: 12, SourceLine: 10050, Last: 1015, Bid: 1010, Ask: 1020, QuoteOK: true}
	current := far82.CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: q.Time,
		SourceIndex: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask,
		Buy: far81.CurrentSupport{OFIKnown: true, OFI30: 1, OwnAt: q.Time,
			Windows: map[string]far81.CurrentSupportWindow{"人工": {Known: true, CurrentAt: q.Time, EndpointAt: q.Time - 5}}},
		Sell: far81.CurrentSupport{OFIKnown: true, OFI30: 1, OwnAt: q.Time},
		Night: far81.CurrentStructure{Available: true, Window: "E08", Time: q.Time, Index: q.Index,
			Band: far81.CurrentBandWindow{QuantityKnown: true, Time: q.Time, Index: q.Index, StartTime: q.Time - 5,
				BidRefill: 10, AskDeplete: 3, AskRefill: 2, BidDeplete: 1}}}}
	in := TechnicalGateInput{SnapshotID: "人工場-G0001", At: at, Kind: "Day", Chart: snapshots[2], Recent3: snapshots, Current: current}
	candidate := fixed96.EntryCandidate{Ordinal: 1, At: at, Side: 1, Quote: q, Available: 10, Quantity: 2,
		Source: fixed96.SourceIdentity{SignalID: "人工出生", BirthQuantity: 2, BirthTime: at - 100, Method: "D164_15"}}
	if side == -1 {
		mirrorSnapshot := func(p *chartwarmup96.Snapshot) {
			v := &p.Chart.Technical
			v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = 4000-v.EMA8_3, 4000-v.EMA21_3, 4000-v.EMA8_15, 4000-v.EMA21_15
			v.Close3, v.RSI3, v.PreviousRSI3 = 4000-v.Close3, 100-v.RSI3, 100-v.PreviousRSI3
			v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
			p.Chart.PreviousClose3, p.Chart.PreviousEMA8_3 = 4000-p.Chart.PreviousClose3, 4000-p.Chart.PreviousEMA8_3
			p.LastInput.Last, p.Three.LastSource.Last, p.Fifteen.LastSource.Last = 4000-p.LastInput.Last, 4000-p.Three.LastSource.Last, 4000-p.Fifteen.LastSource.Last
		}
		for i := range in.Recent3 {
			mirrorSnapshot(&in.Recent3[i])
		}
		in.Chart = in.Recent3[2]
		candidate.Side, candidate.Quote.Last = -1, 4000-q.Last
		candidate.Quote.Bid, candidate.Quote.Ask = 4000-q.Ask, 4000-q.Bid
		in.Current.Last, in.Current.Bid, in.Current.Ask = candidate.Quote.Last, candidate.Quote.Bid, candidate.Quote.Ask
		in.Current.Buy.OFI30, in.Current.Sell.OFI30 = -1, -1
		v := &in.Current.Night.Band
		v.BidRefill, v.AskRefill, v.BidDeplete, v.AskDeplete = v.AskRefill, v.BidRefill, v.AskDeplete, v.BidDeplete
	}
	return in, candidate
}
