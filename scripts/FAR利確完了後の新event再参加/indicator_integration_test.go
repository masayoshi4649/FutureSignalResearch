// 91接続人工派生元: scripts/FAR押戻し確定終値の再参加機会/indicator_integration_test.go
// 91派生元SHA256: 6298ca34bd36a7679e8724e4bda7569d013a53b6fdfcbc9b50a192854f1d1cd4
// 90派生元: scripts/FAR利益床と収穫配分の比較/indicator_integration_test.go
// 90派生元SHA256: 547af5ee0697f5d9b52e98bccee58dd49cfe97490f4773259dc819c7def5d978
// 89派生元: scripts/FAR背景維持と押戻し再開/indicator_integration_test.go
// 89派生元SHA256: b4ed0ceb731f5c83156cf6ecaca5a414efb2101a4499c2d1ea46ae96a5113b34
package far91

import (
	"math"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
)

// indicator91Price は実市場を参照しない合成終値と足内往復を作ります。
//
// 引数: close(float64)、sample(int)、side(int)は終値・足内0..35・売買鏡像です。
// 返り値: float64は終端の終値へ戻る合成Lastです。
func indicator91Price(close float64, sample, side int) float64 {
	price := close + 10*math.Round(4*math.Sin(2*math.Pi*float64(sample)/35))
	if side < 0 {
		price = 40000 - price
	}
	return price
}

// indicator91Quote は合成Lastから鏡像の正常な10pt格子気配を作ります。
//
// 引数: at/longPrice(float64)、index/line(int64)、side(int)は時計・買い側Last・出典・方向です。
// 返り値: QuoteはLastの値と正常BBOを持つ人工です。
func indicator91Quote(at, longPrice float64, index, line int64, side int) Quote {
	bid := 10 * math.Floor(longPrice/10)
	q := Quote{Time: at, Index: index, Line: line, Last: longPrice, Bid: bid, Ask: bid + 10, Valid: true}
	if side < 0 {
		q.Last, q.Bid, q.Ask = 40000-q.Last, 40000-q.Ask, 40000-q.Bid
	}
	return q
}

// indicator91Seed は合成8時間だけを公開数値器へ与えて指標種を準備します。
//
// 引数: t(*testing.T)、start(float64)、side(int)は検査器・当場開始・鏡像です。
// 返り値: *TechnicalBankとfloat64は独立した実指標種と買い側前Closeです。
func indicator91Seed(t *testing.T, start float64, side int) (*far80.TechnicalBank, float64) {
	t.Helper()
	bank := far80.NewTechnicalBank()
	warmStart := start - 8*3600
	bank.BeginSession(warmStart)
	last := 0.0
	for bar := 0; bar < 160; bar++ {
		close := 10000 + 5*float64(bar) + []float64{0, 20, 10, -10}[bar%4]
		for sample := 0; sample < 36; sample++ {
			at := warmStart + float64(bar*180+sample*5+4)
			price := indicator91Price(close, sample, 1)
			q := indicator91Quote(at, price, int64(bar*36+sample), int64(bar*36+sample+1), side)
			if err := bank.Observe(q); err != nil {
				t.Fatal(err)
			}
		}
		last = close
	}
	if err := bank.Advance(start); err != nil {
		t.Fatal(err)
	}
	if v := bank.View(); !v.TrendKnown || !v.ReversalKnown || !v.SpikeKnown || !v.ATRKnown {
		t.Fatal("合成前史が固定指標器を準備していません", v)
	}
	return bank, last
}

// indicator91Grid は実公開足だけから外資格を計算し、手製Sourceだけを供給します。
//
// 引数: t(*testing.T)、r(*replayRuntime)、at(float64)、side(int)、supply(bool)は人工接続です。
// 返り値: ありません。元FAR生成やSource旧80同値を作りません。
func indicator91Grid(t *testing.T, r *replayRuntime, at float64, side int, supply bool) {
	t.Helper()
	chart := r.bank.View()
	c0, err := Decide(at, r.last, chart, CurrentEvidence{})
	if err != nil {
		t.Fatal(err)
	}
	events, err := r.tracker.Snapshot(at)
	if err != nil {
		t.Fatal(err)
	}
	evaluation, err := EvaluateEntry(at, r.last, chart, events)
	if err != nil {
		t.Fatal(err)
	}
	source := emptySnapshot()
	if supply {
		source = entry91Source(r.last.Time)
		source.Lots = source.Lots[1:2]
		source.Lots[0].Reference.Side = side
		source.Lots[0].Reference.Kind = "initial"
		source.Lots[0].Reference.Entry = r.last.Last
		source.Lots[0].NativeParentInitialKnown = true
		source.Lots[0].NativeParentInitialReason = "手製親初回50・元FAR生成は未検証"
		source.Lots[0].NativeParentOriginalDesiredApplicable = true
		source.Lots[0].NativeParentOriginalDesiredReason = "手製Sourceのため未取得"
		source.Lots[0].NativeSmallInitialReason = "D164はP164小量規則の対象外"
		for _, before := range r.result.GridDecisions {
			if len(before.Source.Lots) > 0 {
				source.Lots[0] = before.Source.Lots[0]
				break
			}
		}
	}
	allowed, block := !r.forceDone && r.result.InputEnd != nil && at <= r.result.InputEnd.Time, ""
	if !allowed {
		block = "合成原板終端又は場末後"
	}
	grid := GridDecision{At: at, Window: "D164_15", ClockAllowed: allowed, BlockReason: block, C0: c0,
		Source: source, SourceLine: r.last.Line, StructureAnchor: structureAnchorAt(at, chart), Entry: evaluation, Events: events, Policies: map[string]PolicySupply{}}
	if err := r.supplyEntryGrid(grid, chart.Technical); err != nil {
		t.Fatal(err)
	}
}

// indicator91Clock は合成人工だけの独立公開と旧actual呼出を配送します。
//
// 引数: t(*testing.T)、r(*replayRuntime)、clock(replayClock)、side(int)、entryAt(float64)は人工時計です。
// 返り値: ありません。Source生成/Step/Forceを偽装せず、金融Forceだけを旧時点で呼びます。
func indicator91Clock(t *testing.T, r *replayRuntime, clock replayClock, side int, entryAt, reentryAt float64) {
	t.Helper()
	afterEOF := r.result.InputEnd == nil || clock.At > r.result.InputEnd.Time
	if clock.Three {
		if err := r.advanceEvent(clock.At, "three_timer", afterEOF); err != nil {
			t.Fatal(err)
		}
	}
	if !clock.Core {
		return
	}
	if err := r.advanceEvent(clock.At, "core_timer", afterEOF); err != nil {
		t.Fatal(err)
	}
	if err := r.bank.Advance(clock.At); err != nil {
		t.Fatal(err)
	}
	if err := r.compareTechnical("core_timer", clock.At); err != nil {
		t.Fatal(err)
	}
	if clock.At == r.session.ForceClose {
		for _, book := range r.books {
			if err := book.Force(clock.At, r.last, "場末10分前"); err != nil {
				t.Fatal(err)
			}
		}
		r.forceDone = true
	}
	if r.grids[clock.At] {
		indicator91Grid(t, r, clock.At, side, clock.At == entryAt || reentryAt > 0 && clock.At == reentryAt)
	}
	if err := r.flushProfitContexts(); err != nil {
		t.Fatal(err)
	}
}

// runIndicator91 は初参加だけの固定指標人工を返します。
//
// 引数: t(*testing.T)、side(int)は検査器と鏡像です。
// 返り値: *replayRuntime/[]Quote/TechnicalViewは当時出典つき人工です。
func runIndicator91(t *testing.T, side int) (*replayRuntime, []Quote, TechnicalView) {
	return runIndicator91Case(t, side, false)
}

// runIndicator91 は実固定指標/合成原板/手製SourceのE1非0経路を作ります。
//
// 引数: t(*testing.T)、side(int)は検査器と売買鏡像です。
// 返り値: Runtime・当場全Quote・種TechnicalViewはexport可能な人工です。
func runIndicator91Case(t *testing.T, side int, repeat bool) (*replayRuntime, []Quote, TechnicalView) {
	t.Helper()
	session, err := sessionClock("2026-11-02_Day")
	if err != nil {
		t.Fatal(err)
	}
	bank, previous := indicator91Seed(t, session.Start, side)
	seed := bank.View()
	eventSeed := *bank
	actual, event := NewChartBank(bank), NewChartBank(&eventSeed)
	actual.BeginSession(session.Start)
	event.BeginSession(session.Start)
	entryAt := session.Start + 1800
	reentryAt, endAt := 0.0, entryAt+29
	if repeat {
		reentryAt = entryAt + 900
		endAt = reentryAt + 29
	}
	closes := []float64{previous + 10, previous + 20, previous + 10, previous + 30, previous + 40,
		previous - 40, previous + 20, previous + 50, previous + 60, previous + 70}
	if repeat {
		closes = append(closes, previous+80, previous+110, previous+20, previous+120, previous+140)
	}
	raw := []Quote{}
	for at := session.Start + 4; at <= endAt; at += 5 {
		offset := at - session.Start
		bar, sample := int(offset/180), int(math.Mod(offset, 180)/5)
		price := closes[len(closes)-1]
		if bar < len(closes) {
			price = indicator91Price(closes[bar], sample, 1)
		}
		if at >= entryAt+9 && at < entryAt+19 || repeat && at >= reentryAt+9 && at < reentryAt+19 {
			price += 40
		}
		raw = append(raw, indicator91Quote(at, price, int64(len(raw)), int64(len(raw)+1), side))
	}
	r := &replayRuntime{session: session, bank: actual, eventBank: event, tracker: NewEventTracker(), last: Quote{Index: -1}, books: map[string]*Book{},
		result: &ReplayResult{EntryOpportunities: []EntryOpportunityLevel{}, Session: session.ID, SeedView: seed, InputEnd: &MergedEnd{Time: raw[len(raw)-1].Time, Reference: "NK225", SourceLine: raw[len(raw)-1].Line},
			Quality: map[string]RawQuality{}, Books: map[string]BookResult{}, ReferenceCounts: map[string]int{}, GridDecisions: []GridDecision{}, SourceEvents: []SourceEvent{}, EntryObservations: []EventRecord{}, EntryBindings: []EntryOrderBinding{}, ProfitContexts: []ProfitContext{}}}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			var book *Book
			var e error
			if mode == "R0" {
				book, e = NewSourceBook(session.ID, "S", 100)
			} else {
				book, e = NewReentrySourceBook(session.ID, "S", 100)
			}
			if e != nil {
				t.Fatal(e)
			}
			if e = book.SetFillDelay(float64(delay)); e != nil {
				t.Fatal(e)
			}
			r.books[bookKey(mode, delay)] = book
		}
	}
	times, grids, err := replayTimers(session)
	if err != nil {
		t.Fatal(err)
	}
	r.grids = grids
	clocks, cursor := mergedClocks(session, times), 0
	for _, q := range raw {
		for cursor < len(clocks) && clocks[cursor].At <= q.Time {
			indicator91Clock(t, r, clocks[cursor], side, entryAt, reentryAt)
			cursor++
		}
		chart := q
		chart.Valid = q.Last > 0
		if err := r.bank.Observe(chart); err != nil {
			t.Fatal(err)
		}
		if err := r.eventBank.Observe(chart); err != nil {
			t.Fatal(err)
		}
		if err := r.recordEvent(q.Time, "quote", false, q); err != nil {
			t.Fatal(err)
		}
		if err := r.compareTechnical("quote", q.Time); err != nil {
			t.Fatal(err)
		}
		if err := r.deliverQuote(q, ReferenceFrame{}, r.bank.View().Technical, nil); err != nil {
			t.Fatal(err)
		}
	}
	for cursor < len(clocks) {
		indicator91Clock(t, r, clocks[cursor], side, entryAt, reentryAt)
		cursor++
	}
	if err := r.flushProfitContexts(); err != nil {
		t.Fatal(err)
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(mode, delay)
			r.result.Books[key] = r.books[key].Result()
		}
	}
	return r, raw, seed
}

// indicator91G1Baseline は独立した旧金融へ同じ非0供給/原行/旧時計を渡します。
//
// 引数: t(*testing.T)、r(*replayRuntime)、raw([]Quote)、side(int)は実指標人工です。
// 返り値: map[string]far89.BookResultは88が使う旧89G1金融の2会計です。
func indicator91G1Baseline(t *testing.T, r *replayRuntime, raw []Quote, side int) map[string]far89.BookResult {
	t.Helper()
	seed, _ := indicator91Seed(t, r.session.Start, side)
	bank := NewChartBank(seed)
	bank.BeginSession(r.session.Start)
	books := map[string]*far89.Book{}
	for _, policy := range EntryPolicies {
		for delay := 0; delay <= 1; delay++ {
			book, err := far89.NewSourceBook(r.session.ID, "S", 100)
			if err != nil {
				t.Fatal(err)
			}
			if err = book.SetFillDelay(float64(delay)); err != nil {
				t.Fatal(err)
			}
			books[bookKey(policy, delay)] = book
		}
	}
	grids := map[float64]GridDecision{}
	for _, g := range r.result.GridDecisions {
		grids[g.At] = g
	}
	times, _, err := replayTimers(r.session)
	if err != nil {
		t.Fatal(err)
	}
	cursor, last := 0, (Quote{Index: -1})
	advance := func(at float64) {
		if err := bank.Advance(at); err != nil {
			t.Fatal(err)
		}
		if at == r.session.ForceClose {
			for _, book := range books {
				if err := book.Force(at, last, "場末10分前"); err != nil {
					t.Fatal(err)
				}
			}
		}
		if grid, ok := grids[at]; ok {
			for _, policy := range EntryPolicies {
				source := grid.Source
				source.Lots = []ReadLot{}
				if grid.ClockAllowed {
					for _, id := range grid.Policies[policy].SuppliedIDs {
						for _, row := range grid.Source.Lots {
							if row.Reference.ID == id {
								source.Lots = append(source.Lots, row)
							}
						}
					}
				}
				for delay := 0; delay <= 1; delay++ {
					if err := books[bookKey(policy, delay)].OnSourceGrid(at, last, source, grid.C0, bank.View().Technical, grid.StructureAnchor); err != nil {
						t.Fatal(err)
					}
				}
			}
		}
	}
	for _, q := range raw {
		for cursor < len(times) && times[cursor] <= q.Time {
			advance(times[cursor])
			cursor++
		}
		chart := q
		chart.Valid = q.Last > 0
		if err := bank.Observe(chart); err != nil {
			t.Fatal(err)
		}
		for _, book := range books {
			if err := book.OnQuote(q, ReferenceFrame{}, bank.View().Technical, nil); err != nil {
				t.Fatal(err)
			}
		}
		last = q
	}
	for cursor < len(times) {
		advance(times[cursor])
		cursor++
	}
	out := map[string]far89.BookResult{}
	for _, policy := range EntryPolicies {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(policy, delay)
			out[bookKey("E1G1", delay)] = books[key].Result()
			equal91JSON(t, "実指標非0R0旧89金融全文", r.result.Books[bookKey("R0", delay)], out[bookKey("E1G1", delay)])
		}
	}
	return out
}

// TestIndicator91RealBankAndSyntheticRaw は実数値器からE1供給/約定/G1を非0接続します。
//
// 引数: t(*testing.T)は完全合成買売系列の検査器です。
// 返り値: ありません。元FAR自然発生と市場性能を証明しません。
func TestIndicator91RealBankAndSyntheticRaw(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, raw, seed := runIndicator91(t, side)
		indicator91G1Baseline(t, r, raw, side)
		if len(raw) == 0 || !seed.TrendKnown || len(r.result.EntryBindings) != 4 {
			t.Fatal("実指標から全政策への供給が非0ではありません", side, len(raw), r.result.EntryBindings)
		}
		for i, q := range raw {
			if q.Index != int64(i) || q.Line != int64(i+1) || q.Time != r.session.Start+4+5*float64(i) {
				t.Fatal("当場rawの物理行/実Index/5秒時計が不連続です", i, q)
			}
		}
		if seed.Bar3End != r.session.Start || seed.Bar15End != r.session.Start || r.result.InputEnd.SourceLine != int64(len(raw)) {
			t.Fatal("合成前史の終端又は当場EOFが不整合です")
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				book := r.result.Books[bookKey(mode, delay)]
				if book.Metrics.EntryQuantity != 8 || book.Metrics.ProfitFlags == 0 || book.Unresolved {
					t.Fatal("実数値器の入口/約定/保護が貫通しません", side, mode, delay, book.Metrics)
				}
				if book.Metrics.HarvestOrders == 0 {
					t.Fatal("G1収穫未接続", mode)
				}
				if book.Mode != "S0G1" {
					t.Fatal("共通G1modeが不整合", mode)
				}
			}
		}
		for _, b := range r.result.EntryBindings {
			if b.Policy == "E1" {
				e := b.CurrentQualification.Event
				if e == nil || !(e.Impulse.BarEnd < e.Pullback.BarEnd && e.Pullback.BarEnd < e.Recovery.BarEnd && e.Recovery.BarEnd <= e.Confirmation.BarEnd) {
					t.Fatal("実公開足の時系列出典が不成立", b)
				}
				if e.Impulse.BarEnd != r.session.Start+900 || e.Pullback.BarEnd != r.session.Start+1080 || e.Recovery.BarEnd != r.session.Start+1260 ||
					e.Confirmation.BarEnd != e.Recovery.BarEnd || b.PoolEvaluation.EventBeforeSource == nil || !*b.PoolEvaluation.EventBeforeSource {
					t.Fatal("実3分足の推進/押し/回復点又はSource成立前eventが異なります", b)
				}
				t.Log("実指標の再開", side, e, "取得ATR比", *b.CurrentQualification.PlacementATR)
			}
		}
		for _, grid := range r.result.GridDecisions {
			if grid.At == r.session.Start+1800 && grid.C0.Allowed {
				t.Fatal("C0拒否時のE1非0を検証できていません")
			}
		}
		if r.result.SourceEquivalence.StepFrames != 0 || r.result.SourceEquivalence.CurrentSHA256 != "" {
			t.Fatal("手製Sourceを元Source同値証明へ偽装しました")
		}
	}
}

// TestIndicator91RealBankReentry は同じ手製Sourceが残る2回目の公開再開を実指標から接続します。
//
// 引数: t(*testing.T)は完全合成の買売鏡像検査器です。
// 返り値: ありません。Source自然生成や市場性能を証明せず、R0の旧金融全文とR1全履歴を確認します。
func TestIndicator91RealBankReentry(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, raw, _ := runIndicator91Case(t, side, true)
		indicator91G1Baseline(t, r, raw, side)
		if len(r.result.EntryOpportunities) != 2 {
			t.Fatal("同参照の別event機会が2回ではない", side, r.result.EntryOpportunities)
		}
		for delay := 0; delay <= 1; delay++ {
			control := r.result.Books[bookKey("R0", delay)]
			book := r.result.Books[bookKey("R1", delay)]
			if len(control.Lots) != 1 || len(book.Lots) != 2 || book.Metrics.EntryQuantity != 16 || book.Unresolved {
				t.Fatal("実再参加の全履歴又は量が不整合", side, delay, control.Metrics, book.Metrics, book.Decisions)
			}
			assessment := r.result.EntryOpportunities[1].Assessments[bookKey("R1", delay)]
			if !assessment.Selected || !assessment.Consumed || assessment.Role != "利確後再参加" || assessment.PreviousActual == nil || assessment.PreviousActual.Completion == nil || assessment.PreviousActual.NetPnL <= 0 || assessment.AcceptedSerial != 2 {
				t.Fatal("利確完了後の新機会の受理出典が不整合", assessment)
			}
			for _, relation := range assessment.Chronology {
				if !relation.Known || !relation.After {
					t.Fatal("新p/r/k公開が実返済後でない", relation)
				}
			}
			if book.Lots[0].ID == book.Lots[1].ID || book.Lots[0].ReferenceID != book.Lots[1].ReferenceID || book.Lots[1].RealEntryStage != "利確後再参加" {
				t.Fatal("同参照の実世代ID又は役割が不整合", book.Lots)
			}
		}
	}
}
