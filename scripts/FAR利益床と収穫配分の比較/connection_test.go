// 89派生元: scripts/FAR背景維持と押戻し再開/connection_test.go
// 89派生元SHA256: dde08dd9fa2f6409b1948311143782dea92b784b641fc4b2695febe523a76958
package far89

import (
	"encoding/json"
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
			_, guard, e := modeParts(mode)
			if e != nil {
				t.Fatal(e)
			}
			b, e := NewSourceGuardBook(session.ID, "S", guard, 100)
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

// runConnection89 は源部分予約と正益、後の全返済までを全8会計へ共有します。
//
// 引数: t(*testing.T)、side(int)、hasEvent(bool)は人工の方向と初回順序資格です。
// 返り値: *replayRuntimeは非0実約定と原行別利益観測を持つ手製API人工です。
func runConnection89(t *testing.T, side int, hasEvent bool) *replayRuntime {
	t.Helper()
	r, grid, tech := connection89Fixture(t, side, hasEvent)
	if err := r.supplyEntryGrid(grid, tech); err != nil {
		t.Fatal(err)
	}
	if len(r.result.EntryBindings) != (map[bool]int{true: 8, false: 4}[hasEvent]) {
		t.Fatal("新規binding数が不正")
	}
	shared := r.result.GridDecisions[0]
	if len(shared.Source.Lots) != 3 || len(shared.Policies["E0"].SuppliedIDs) != 2 {
		t.Fatal("全pool又は部分列が欠落")
	}
	for _, binding := range r.result.EntryBindings {
		if binding.Policy != "S" && (binding.RawRank != 2 || binding.SuppliedRank != 1 || binding.RequestedQuantity != 8) {
			t.Fatal("元/供給順位又は量の混同", binding)
		}
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			b := r.books[bookKey(mode, delay)].Result()
			policy, guard, e := modeParts(mode)
			if e != nil {
				t.Fatal(e)
			}
			want := policy != "E1" || hasEvent
			if (len(b.Orders) > 0) != want || b.SourcePolicy != "S" || b.Mode != "S0"+guard {
				t.Fatal("外政策が旧金融を変えた", mode)
			}
		}
	}
	q := r.last
	var first *CurrentEvidence
	for _, after := range []float64{.5, 1, 2, 3, 4, 5, 6} {
		q.Time, q.Index, q.Line = grid.At+after, q.Index+1, q.Line+1
		move := 0.0
		if after >= 2 && after <= 4 {
			move = float64(side) * 40
		}
		q.Last, q.Bid, q.Ask = grid.C0.Base.Quote.Last+move, grid.C0.Base.Quote.Bid+move, grid.C0.Base.Quote.Ask+move
		frame := ReferenceFrame{Closes: []ReferenceClose{}}
		if after == 2 {
			frame.Closes = append(frame.Closes, ReferenceClose{ID: "手製部分", ReferenceID: grid.Source.Lots[1].Reference.ID, Before: 8, Quantity: 3, Reason: "手製部分"})
		}
		c := connection89Current(q, after)
		if after == 2 {
			first = c
		}
		if err := r.deliverQuote(q, frame, tech, c); err != nil {
			t.Fatal(err)
		}
		if after == .5 {
			if r.books["E0G1_D0"].Result().Metrics.OpenQuantity != 8 || r.books["E0G1_D1"].Result().Metrics.OpenQuantity != 0 {
				t.Fatal("D0/D1の最初の後原行を混同")
			}
		}
	}
	// 保存値を未来の入力変更から独立させ、将来片を旗原行の確定へ混入させません。
	first.Night.PriceEvent = 9999
	first.Buy.OFI30 = 9999
	first.Buy.Windows["人工"] = far81.CurrentSupportWindow{Value: 9999}
	if err := r.flushProfitContexts(); err != nil {
		t.Fatal(err)
	}
	if len(r.profitBuffer) != 0 || len(r.result.ProfitContexts) != 1 {
		t.Fatal("利益buffer破棄又は共有旗原行の集約が不正")
	}
	ctx := r.result.ProfitContexts[0]
	if ctx.Current == nil || ctx.Current.Night.PriceEvent != 2 || ctx.Current.Buy.OFI30 != 2 || ctx.Quote.Time != grid.At+2 {
		t.Fatal("旗snapshotへ未来が混入", ctx)
	}
	wantTriggers := 16
	if !hasEvent {
		wantTriggers = 8
	}
	if len(ctx.TriggeredBy) != wantTriggers {
		t.Fatal("残玉/全玉旗の件数混同", ctx.TriggeredBy)
	}
	for _, trigger := range ctx.TriggeredBy {
		if trigger.RemainingAfterFill != 8 || trigger.ClosedNetAfterFill != 0 {
			t.Fatal("旗へ後の確定益が遡及", trigger)
		}
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(mode, delay)
			b := r.books[key].Result()
			if b.Unresolved {
				t.Fatal("人工が未完結", key)
			}
			r.result.Books[key] = b
		}
	}
	return r
}

// TestConnection89PoliciesAndProfit は八金融の非0入口・順位・遅延・源先行予約を確認します。
//
// 引数: t(*testing.T)は売買鏡像とE1待機の人工です。
// 返り値: ありません。Sourceと指標は手製前史であり自然発生の証明ではありません。
func TestConnection89PoliciesAndProfit(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, event := range []bool{true, false} {
			runConnection89(t, side, event)
		}
	}
}

// TestConnection89UnknownClockAndBindings は政策未知を金融へ書き戻さずclock停止を守ります。
//
// 引数: t(*testing.T)は未知・clock・凍結の人工です。
// 返り値: ありません。受理しない候補のsupplied_rankはnullとなります。
func TestConnection89UnknownClockAndBindings(t *testing.T) {
	r, g, tech := connection89Fixture(t, 1, true)
	g.ClockAllowed = false
	if err := r.supplyEntryGrid(g, tech); err != nil {
		t.Fatal(err)
	}
	for _, p := range r.result.GridDecisions[0].Policies {
		if len(p.SuppliedIDs) != 0 {
			t.Fatal("clock停止で供給")
		}
		for _, c := range p.Pool {
			if c.SuppliedRank != nil {
				t.Fatal("未供給に供給順位")
			}
		}
	}
	r, g, tech = connection89Fixture(t, 1, true)
	tech.ATRKnown = false
	chart := ChartView{Technical: tech, Previous3Known: true, PreviousClose3: 1005, PreviousEMA8_3: 1000, PreviousBar3End: tech.Bar3End - 180}
	evaluation, err := EvaluateEntry(g.At, r.last, chart, g.Events)
	if err != nil {
		t.Fatal(err)
	}
	g.Entry = evaluation
	g.C0.Base.Technical = tech
	if err := r.supplyEntryGrid(g, tech); err != nil {
		t.Fatal(err)
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			if len(r.books[bookKey(mode, delay)].Result().Orders) != 0 {
				t.Fatal("未知の外政策を金融へ供給")
			}
		}
	}
	if !r.result.GridDecisions[0].Policies["E0"].Pool[1].RequiredUnknown {
		t.Fatal("外未知を通常待機へ消去")
	}

	r, g, tech = connection89Fixture(t, 1, true)
	if err := r.supplyEntryGrid(g, tech); err != nil {
		t.Fatal(err)
	}
	before, _ := json.Marshal(r.result.EntryBindings)
	g.Entry.Directions[0].Event.Confirmation.BarEnd += 1
	*g.Source.Lots[1].NativeParentInitialMicro = 999
	after, _ := json.Marshal(r.result.EntryBindings)
	if string(before) != string(after) || r.result.GridDecisions[0].Entry.Directions[0].Event.Confirmation.BarEnd == g.Entry.Directions[0].Event.Confirmation.BarEnd || *r.books["E0G1_D0"].Result().Orders[0].SourceEntry.ReadLot.NativeParentInitialMicro != 50 {
		t.Fatal("要求時凍結値を後で変更")
	}
}

// TestConnection89MissingProfitRow は未計測旗を診断成功にしないことを確認します。
//
// 引数: t(*testing.T)は欠番の反証です。
// 返り値: ありません。必要bufferを破棄した後の旗収集はerrorとなります。
func TestConnection89MissingProfitRow(t *testing.T) {
	r := runConnection89(t, 1, true)
	r.profitSeen = map[string]bool{}
	if err := r.flushProfitContexts(); err == nil {
		t.Fatal("旗原行欠番を成功化")
	}
}

// TestConnection89PostfillFlagAndSameSecond は旗原行の全fill後状態を同秒後原行と区別します。
//
// 引数: t(*testing.T)は買売鏡像・両遅延の手計算人工です。
// 返り値: ありません。Source部分3の534円と残5を旗へ結び、後の356円は除外します。
func TestConnection89PostfillFlagAndSameSecond(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, grid, tech := connection89Fixture(t, side, true)
		if err := r.supplyEntryGrid(grid, tech); err != nil {
			t.Fatal(err)
		}
		q := r.last
		steps := []struct {
			after, move, value float64
			partial            bool
		}{
			{.5, 0, .5, false}, {1, 0, 1, false},
			{1, 20, 1, true}, {2, 40, 2, false}, {2, 40, 99, false},
		}
		for _, step := range steps {
			q.Time, q.Index, q.Line = grid.At+step.after, q.Index+1, q.Line+1
			move := float64(side) * step.move
			q.Last, q.Bid, q.Ask = grid.C0.Base.Quote.Last+move, grid.C0.Base.Quote.Bid+move, grid.C0.Base.Quote.Ask+move
			frame := ReferenceFrame{Closes: []ReferenceClose{}}
			if step.partial {
				frame.Closes = append(frame.Closes, ReferenceClose{ID: "旗前部分", ReferenceID: grid.Source.Lots[1].Reference.ID, Before: 8, Quantity: 3, Reason: "人工部分"})
			}
			if err := r.deliverQuote(q, frame, tech, connection89Current(q, step.value)); err != nil {
				t.Fatal(err)
			}
		}
		if err := r.flushProfitContexts(); err != nil {
			t.Fatal(err)
		}
		if len(r.result.ProfitContexts) != 1 {
			t.Fatal("旗原行共有の誤り", r.result.ProfitContexts)
		}
		context := r.result.ProfitContexts[0]
		if context.Quote.Line != q.Line-1 || context.Current.Night.PriceEvent != 2 || len(context.TriggeredBy) != 16 {
			t.Fatal("同秒将来原行が遡及", context)
		}
		for _, trigger := range context.TriggeredBy {
			if trigger.RemainingAfterFill != 5 || trigger.ClosedNetAfterFill != 534 {
				t.Fatal("全fill後の旗状態が違う", trigger)
			}
		}
		for _, key := range []string{"E0G1_D0", "E1G1_D0"} {
			b := r.books[key].Result()
			if b.Metrics.OpenQuantity != 3 || len(b.Closed) != 2 {
				t.Fatal("同秒後原行の実fill未確認", key, b.Metrics)
			}
		}
	}
}

// TestConnection89RejectedSeenAndOccupied は外filterの見送りを金融seenと混同しません。
//
// 引数: t(*testing.T)は15分後の再開成立と実占有中の人工です。
// 返り値: ありません。見送ったE1は同じ元IDへ初参加でき、保有中は追加しません。
func TestConnection89RejectedSeenAndOccupied(t *testing.T) {
	r, grid, tech := connection89Fixture(t, 1, false)
	if err := r.supplyEntryGrid(grid, tech); err != nil {
		t.Fatal(err)
	}
	q := r.last
	for _, after := range []float64{.5, 1} {
		q.Time, q.Index, q.Line = grid.At+after, q.Index+1, q.Line+1
		if err := r.deliverQuote(q, ReferenceFrame{}, tech, connection89Current(q, after)); err != nil {
			t.Fatal(err)
		}
	}
	if err := r.flushProfitContexts(); err != nil {
		t.Fatal(err)
	}
	newAt := grid.At + 900
	q.Time, q.Index, q.Line = newAt-1, q.Index+1, q.Line+1
	if err := r.deliverQuote(q, ReferenceFrame{}, tech, connection89Current(q, 99)); err != nil {
		t.Fatal(err)
	}
	inputs := event89Sequence(true)
	shift := newAt - inputs[len(inputs)-1].At
	tracker := NewEventTracker()
	for _, in := range inputs {
		in.At += shift
		in.Quote.Time += shift
		in.EpochStart = r.session.Start
		in.Technical.Bar3End += shift
		in.Technical.Bar15End += shift
		event89Feed(t, tracker, in)
	}
	events, err := tracker.Snapshot(newAt)
	if err != nil {
		t.Fatal(err)
	}
	newTech := inputs[len(inputs)-1].Technical
	newTech.Bar3End += shift
	newTech.Bar15End += shift
	chart := ChartView{Technical: newTech, Previous3Known: true, PreviousBar3End: newAt - 180, PreviousClose3: inputs[len(inputs)-2].Technical.Close3, PreviousEMA8_3: newTech.EMA8_3}
	evaluation, err := EvaluateEntry(newAt, q, chart, events)
	if err != nil {
		t.Fatal(err)
	}
	grid.At, grid.Source.At, grid.Source.SourceIndex = newAt, q.Time, q.Index+7
	grid.C0.Base.At, grid.C0.Base.Quote, grid.C0.Base.Technical = newAt, q, newTech
	grid.Entry, grid.Events, grid.StructureAnchor = evaluation, events, structureAnchorAt(newAt, chart)
	if err = r.supplyEntryGrid(grid, newTech); err != nil {
		t.Fatal(err)
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book := r.books[bookKey(mode, delay)].Result()
			d := book.Decisions[len(book.Decisions)-1]
			policy, _, err := modeParts(mode)
			if err != nil {
				t.Fatal(err)
			}
			if policy == "E1" {
				if d.Action != "新規要求" || d.SourceContext.SeenBeforeCount != 0 || d.SourceContext.SeenAfterCount != 1 || d.SourceContext.SelectedID != grid.Source.Lots[1].Reference.ID {
					t.Fatal("見送りをseenへ消費", d)
				}
			} else if d.Action != "保有継続" || !d.SourceContext.Occupied || d.SourceContext.SeenBeforeCount != 1 || d.SourceContext.SeenAfterCount != 1 {
				t.Fatal("占有中の追加又はseen変更", mode, d)
			}
		}
	}
	if len(r.result.EntryBindings) != 8 {
		t.Fatal("時間順の受理binding数", r.result.EntryBindings)
	}
}
