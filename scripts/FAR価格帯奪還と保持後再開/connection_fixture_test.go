// work92手製API人工由来SHA256: 98e4fdb71d226e2b04f9ce5643d7b8cff570343efaec285a1af72e8f8dbae2ac
// 89派生元: scripts/FAR背景維持と押戻し再開/connection_test.go
// 89派生元SHA256: dde08dd9fa2f6409b1948311143782dea92b784b641fc4b2695febe523a76958
package far92

import (
	"fmt"
	"testing"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// connection89Fixture は元Source前史と指標を手製で与える非0の金融API人工です。
//
// 引数: t(*testing.T)、side(int)、hasEvent(bool)は検査器・鏡像・初回履歴有無です。
// 返り値: *replayRuntime/GridDecision/TechnicalViewは全8会計と同じ当時入力です。
func connection89Fixture(t *testing.T, side int, hasEvent bool) (*replayRuntime, GridDecision, TechnicalView) {
	t.Helper()
	session, err := sessionClock("2026-11-02_Day")
	if err != nil {
		t.Fatal(err)
	}
	at := session.Start + 1800
	inputs := event89Sequence(true)
	shift := at - inputs[len(inputs)-1].At
	tracker := NewEventTracker()
	for _, original := range inputs {
		in := original
		if side < 0 {
			in = event89Mirror(in)
		}
		in.At += shift
		in.EpochStart = session.Start
		in.Technical.Bar3End += shift
		in.Technical.Bar15End += shift
		in.Quote.Time += shift
		event89Feed(t, tracker, in)
	}
	events, err := tracker.Snapshot(at)
	if err != nil {
		t.Fatal(err)
	}
	if !hasEvent {
		for i := range events.Directions {
			events.Directions[i].Event = nil
			events.Directions[i].EventValid = false
		}
	}
	last := inputs[len(inputs)-1]
	if side < 0 {
		last = event89Mirror(last)
	}
	tech := last.Technical
	tech.Bar3End += shift
	tech.Bar15End += shift
	q := Quote{Time: at - 1, Index: 0, Line: 20, Last: 1010, Bid: 1000, Ask: 1010, Valid: true}
	if side < 0 {
		q.Last, q.Bid, q.Ask = 2000-q.Last, 2000-q.Ask, 2000-q.Bid
	}
	previous := inputs[len(inputs)-2]
	if side < 0 {
		previous = event89Mirror(previous)
	}
	chart := ChartView{Technical: tech, PreviousClose3: previous.Technical.Close3, PreviousEMA8_3: tech.EMA8_3, PreviousBar3End: at - 180, Previous3Known: true}
	evaluation, err := EvaluateEntry(at, q, chart, events)
	if err != nil {
		t.Fatal(err)
	}
	raw := entry89Source(q.Time)
	// 元pool順位は反対側/適格側/適格側の後続ID。供給順位の圧縮を確認します。
	for i := range raw.Lots {
		raw.Lots[i].Reference.Side = side * raw.Lots[i].Reference.Side
		raw.Lots[i].NativeParentInitialKnown = true
		raw.Lots[i].NativeParentInitialReason = "手製親初回50"
		raw.Lots[i].NativeParentOriginalDesiredApplicable = true
		raw.Lots[i].NativeParentOriginalDesiredReason = "手製未取得"
		raw.Lots[i].NativeSmallInitialReason = "P164対象外"
	}
	third := raw.Lots[1]
	third.Reference.ID = "同側後続"
	third.Reference.InternalID = "同側後続内部"
	third.Reference.At = q.Time - 1
	third.Reference.Quantity = 3
	raw.Lots = append(raw.Lots, third)
	r := &replayRuntime{session: session, books: map[string]*Book{}, last: q, result: &ReplayResult{Session: session.ID, Books: map[string]BookResult{}, GridDecisions: []GridDecision{}, EntryBindings: []EntryOrderBinding{}, EntryObservations: []EventRecord{}, ProfitContexts: []ProfitContext{}}}
	initialTech := tech
	initialTech.Bar3End -= 180
	initialTech.Bar15End -= 180
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			_, _, e := modeParts(mode)
			if e != nil {
				t.Fatal(e)
			}
			b, e := NewSourceBook(session.ID, "S", 100)
			if e != nil {
				t.Fatal(e)
			}
			if e = b.SetFillDelay(float64(delay)); e != nil {
				t.Fatal(e)
			}
			if e = b.OnQuote(q, ReferenceFrame{}, initialTech, nil); e != nil {
				t.Fatal(e)
			}
			r.books[bookKey(mode, delay)] = b
		}
	}
	// 固定C0の採否は意図的にfalse。全新政策はこの採否を新gateへ使いません。
	c0 := Decision{}
	c0.Base.At = at
	c0.Base.Quote = q
	c0.Base.Technical = tech
	grid := GridDecision{At: at, Window: "D164_15", ClockAllowed: true, C0: c0, Source: raw, SourceLine: q.Line, StructureAnchor: structureAnchorAt(at, chart), Entry: evaluation, Events: events, Policies: map[string]PolicySupply{}}
	return r, grid, tech
}

// connection89Current は実Indexと源Indexを区別した同原行の抜粋入力です。
//
// 引数: q(Quote)、value(float64)は当原行と変化を検出する人工値です。
// 返り値: *CurrentEvidenceはWindows mapも持つがprofit保存は選択値だけです。
func connection89Current(q Quote, value float64) *CurrentEvidence {
	c := &CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: q.Time, SourceIndex: q.Index + 7, SourceLine: q.Line, Last: q.Last, Bid: q.Bid, Ask: q.Ask}}
	c.Buy = far81.CurrentSupport{OFIKnown: true, OFI30: value, OwnAt: q.Time, Windows: map[string]far81.CurrentSupportWindow{"人工": {Value: value}}}
	c.Sell = c.Buy
	c.Night = far81.CurrentStructure{Time: q.Time, Index: c.SourceIndex, PriceEvent: int64(value)}
	c.Short = far87.CurrentShort{Time: q.Time, Mid: q.Bid + (q.Ask-q.Bid)/2, Five: far87.CurrentShortWindow{Reason: fmt.Sprint(value)}}
	return c
}
