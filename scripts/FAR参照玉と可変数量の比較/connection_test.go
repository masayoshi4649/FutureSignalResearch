package far87

import (
	"math"
	"reflect"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// row87 は手製接続人工で現在特徴の物理行と時計をqへ更新します。
//
// 引数: q(Quote)、previous(CurrentEvidence)は当行と前源観測です。
// 返り値: CurrentEvidenceは源Indexだけを一つ進め、実Indexと区別した値です。
func row87(q Quote, previous CurrentEvidence) CurrentEvidence {
	c := previous
	c.Time, c.Received, c.SourceLine, c.SourceIndex = q.Time, q.Time, q.Line, previous.SourceIndex+1
	c.Last, c.Bid, c.Ask = q.Last, q.Bid, q.Ask
	c.Short = CurrentShort{Time: q.Time, Mid: q.Bid + (q.Ask-q.Bid)/2, Five: CurrentShortWindow{Reason: "手製過去端不足"}, Fifteen: CurrentShortWindow{Reason: "手製過去端不足"}}
	return c
}

// observe87 は手製当原行を二つの架空Sourceと実四会計へ一度だけ渡します。
//
// 引数: t(*testing.T)、r(*replayRuntime)、q(Quote)は検査器・人工Runtime・実当行です。
// 返り値: ありません。Last0では源Stepを作りません。
func observe87(t *testing.T, r *replayRuntime, q Quote) {
	t.Helper()
	if q.Last <= 0 {
		if err := r.observeQuote(q, nil, nil); err != nil {
			t.Fatal(err)
		}
		return
	}
	c := row87(q, r.current)
	o := referenceTestObservation(c.SourceIndex, q.Time, q.Valid)
	o.Last, o.Bid, o.Ask = q.Last, q.Bid, q.Ask
	if err := r.observeQuote(q, &c, &o); err != nil {
		t.Fatal(err)
	}
}

// fixtureReference はSource接続人工の架空参照driverへ型付きmetadataだけを添えます。
// 固定FAR自然発生の証明ではなく、全原行driver互換は別Replay人工で検査します。
type fixtureReference struct {
	*Reference
	fake *fakeReferenceBook
}

// ReadMetadata は架空Sourceの元Kind・量・親初回を区別したsnapshotを作ります。
//
// 引数: なし。
// 返り値: ReadSnapshotは人工参照の現在値で、元親量は現在量から逆算しません。
func (r *fixtureReference) ReadMetadata() (ReadSnapshot, error) {
	f := r.Frame()
	s := ReadSnapshot{Method: r.method, At: r.lastTime, SourceIndex: r.lastIndex, Started: r.started, Lots: []ReadLot{}, Closes: append([]ReferenceClose{}, f.Closes...)}
	for _, ref := range f.Lots {
		initial := 0
		for _, l := range r.fake.lots {
			if l.HoldID == ref.ID {
				initial = l.InitialQuantity
			}
		}
		s.Lots = append(s.Lots, ReadLot{Reference: ref, ReferenceInitialQuantity: initial, NativeParentInitialMicro: integerPointer(50), NativeParentOriginalDesired: integerPointer(32), NativeParentInitialKnown: true, NativeParentInitialReason: "人工の元親初回50", NativeParentOriginalDesiredApplicable: true, NativeParentOriginalDesiredKnown: true, NativeParentOriginalDesiredReason: "人工の初回希望32", NativeSmallInitialReason: "P164小量初回は対象外"})
	}
	return s, nil
}

// newRuntime87 は独立した二つの架空SourceとS/SC四会計を構成します。
//
// 引数: t(*testing.T)、session(strategy.Session)、bank(*ChartBank)、q(Quote)、current(CurrentEvidence)、at(float64)、quantity(int)は手製指標種・当時入力・参照量です。
// 返り値: *replayRuntimeは人工で、親初回50・参照初期32・現在量を分離します。
func newRuntime87(t *testing.T, session strategy.Session, bank *ChartBank, q Quote, current CurrentEvidence, at float64, quantity int) *replayRuntime {
	t.Helper()
	lot := referenceTestLot("参照追加", quantity)
	lot.InitialQuantity = 32
	lot.Kind = "source_add"
	lot.At = q.Time - 10
	lot.Entry = q.Last
	lot.Side = current.Night.Buy.Side
	if lot.Side != 1 && lot.Side != -1 {
		lot.Side = current.Night.Sell.Side
	}
	makeRef := func() *fixtureReference {
		ref, fake := newFakeReference([]strategy.SelectedLot{lot})
		ref.method = "NK225_D164_15"
		ref.deadline = session.ForceClose
		ref.started = true
		ref.lastTime = q.Time
		ref.lastIndex = current.SourceIndex
		ref.refresh()
		return &fixtureReference{Reference: ref, fake: fake}
	}
	ref, legacy := makeRef(), makeRef()
	runtime := &replayRuntime{session: session, bank: bank, books: map[string]*Book{}, last: Quote{Index: -1}, grids: map[float64]bool{at: true}, result: &ReplayResult{Session: session.ID, Books: map[string]BookResult{}, ReferenceCounts: map[string]int{}, GridDecisions: []GridDecision{}, SourceEvents: []SourceEvent{}}, refs: map[string]replayReference{"D164_15": ref}, legacyRefs: map[string]replayLegacyReference{"D164_15": legacy}, sourceLines: map[string]int64{"D164_15": q.Line}}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book, err := NewSourceBook(session.ID, sourcePolicy(mode), 100)
			if err != nil {
				t.Fatal(err)
			}
			if err = book.SetFillDelay(float64(delay)); err != nil {
				t.Fatal(err)
			}
			runtime.books[bookKey(mode, delay)] = book
		}
	}
	if err := runtime.observeQuote(q, &current, nil); err != nil {
		t.Fatal(err)
	}
	return runtime
}

// input87Runtime は人工確定足とfresh帯で固定C0を満たす4会計を作ります。
//
// 引数: t(*testing.T)は検査器、side(int)は±1の鏡像方向です。
// 返り値: *replayRuntimeは人工会計、float64は次の定時です。
func input87Runtime(t *testing.T, side int) (*replayRuntime, float64) {
	t.Helper()
	session, err := sessionClock("2026-11-02_Day")
	if err != nil {
		t.Fatal(err)
	}
	at := session.Start + 5.5*3600
	bank := NewChartBank(far80.NewTechnicalBank())
	bank.BeginSession(session.Start)
	wave := []float64{0, 20, -20, 20, -20, 0}
	price := 0.0
	index := 0
	for clock := session.Start + 1; clock < at; clock += 30 {
		price = 1000 + float64(index)*.1 + float64(index*index)*.00005 + wave[index%6]
		if side < 0 {
			price = 10000 - price
		}
		if err := bank.Observe(Quote{Time: clock, Last: price, Valid: true}); err != nil {
			t.Fatal(err)
		}
		index++
	}
	q := Quote{Time: at - 1, Index: 0, Line: 20, Last: price, Bid: 10 * math.Floor((price-1e-9)/10), Ask: 10 * math.Ceil((price+1e-9)/10), Valid: true}
	evidence := CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: q.Time,
		SourceIndex: 7, SourceLine: q.Line, Last: q.Last, Bid: q.Bid, Ask: q.Ask,
		Buy:  far81.CurrentSupport{Windows: map[string]far81.CurrentSupportWindow{"人工": {Value: 1}}},
		Sell: far81.CurrentSupport{Windows: map[string]far81.CurrentSupportWindow{"人工": {Value: 1}}}}}
	evidence.Short = CurrentShort{Time: q.Time, Mid: q.Bid + (q.Ask-q.Bid)/2}
	evidence.Night = far81.CurrentStructure{Available: true, Known: true, Window: "E08", Time: q.Time, Index: evidence.SourceIndex,
		PriceEvent: 100, Band: far81.CurrentBandWindow{Known: true, QuantityKnown: true, StartIndex: 1, Index: evidence.SourceIndex,
			StartTime: q.Time - 10, Time: q.Time, Elapsed: 10, Events: 8, QuantityEvents: 8}}
	liquidation := q.Bid
	if side < 0 {
		liquidation = q.Ask
	}
	hold := far81.CurrentPriceBand{Active: true, QuantitySupport: true, ID: 4, Side: side, Bid: q.Bid - float64(side)*10, Ask: q.Ask - float64(side)*10,
		Time: q.Time - 1, Index: 6, Event: 99,
		Support: far81.CurrentBarrier{Known: true, Price: liquidation - float64(side)*10, Time: q.Time - 2, Index: 5, Event: 98},
		Barrier: far81.CurrentBarrier{Known: true, Price: liquidation - float64(side)*20, Time: q.Time - 3, Index: 4, Event: 97}}
	if side > 0 {
		evidence.Night.Buy = hold
	} else {
		evidence.Night.Sell = hold
	}
	runtime := newRuntime87(t, session, bank, q, evidence, at, 17)
	return runtime, at
}

// TestRuntimeSourceC0AndQuantity は同じpoolをS/SCへ渡し、Sの隠れC0条件を禁止します。
//
// 引数: t(*testing.T)は買売・C0成立/不成立の人工です。
// 返り値: ありません。元追加17枚を実初参加し、参照初期32/親初回50を保ちます。
func TestRuntimeSourceC0AndQuantity(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, allowC0 := range []bool{true, false} {
			r, at := input87Runtime(t, side)
			if !allowC0 {
				r.current.Night.Known = false
			}
			before, _ := r.refs["D164_15"].ReadMetadata()
			if err := r.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			grid := r.result.GridDecisions[0]
			if grid.C0.Allowed != allowC0 || len(grid.Source.Lots) != 1 || len(grid.Source.Closes) != 0 {
				t.Fatal("共有C0又は全参照poolが不一致", side, allowC0, grid)
			}
			for _, mode := range Modes {
				for delay := 0; delay <= 1; delay++ {
					book := r.books[bookKey(mode, delay)].Result()
					want := mode == "R0G1" || allowC0
					if (len(book.Orders) == 1) != want {
						t.Fatal("Sへの隠れC0条件又はSC未適用", mode, allowC0, book.Decisions)
					}
					if want {
						o := book.Orders[0]
						if o.Quantity != 17 || o.Source.Kind != "source_add" || o.SourceEntry == nil || o.HoldAnchor.Known || o.HoldActive || o.SourceEntry.ReadLot.ReferenceInitialQuantity != 32 || *o.SourceEntry.ReadLot.NativeParentInitialMicro != 50 {
							t.Fatal("要求量・元段階・元親初回の混同", o)
						}
					}
				}
			}
			q := r.last
			for _, after := range []float64{.5, 1} {
				q.Time, q.Index, q.Line = at+after, q.Index+1, q.Line+1
				observe87(t, r, q)
			}
			for _, mode := range Modes {
				for delay := 0; delay <= 1; delay++ {
					book := r.books[bookKey(mode, delay)].Result()
					want := mode == "R0G1" || allowC0
					if want && (book.Metrics.OpenQuantity != 17 || len(book.Lots) != 1 || book.Lots[0].RealEntryStage != "実初参加") {
						t.Fatal("元追加の実初参加又は変数量を保存しません", book)
					}
				}
			}
			after, _ := r.refs["D164_15"].ReadMetadata()
			if !reflect.DeepEqual(before.Lots, after.Lots) {
				t.Fatal("実G1状態がSourceへ逆流しました")
			}
		}
	}
}

// close87 は二つの架空Sourceへ同じ全返済通知を当原行で発行させます。
//
// 引数: r(*replayRuntime)、at(float64)、side/quantity(int)は人工当行と通知数量です。
// 返り値: ありません。Sourceは各自の別台帳で進みます。
func close87(r *replayRuntime, at float64, side, quantity int) {
	index := r.current.SourceIndex + 1
	s := referenceTestSignal("接続返済", "close", quantity, index, "参照追加")
	s.Time = at
	s.Side = -side
	r.refs["D164_15"].(*fixtureReference).fake.scripts[index] = []strategy.Signal{s}
	r.legacyRefs["D164_15"].(*fixtureReference).fake.scripts[index] = []strategy.Signal{s}
}

// TestRuntimeSourceCloseFillOrder はSource通知が実fill後に適用されることを確認します。
//
// 引数: t(*testing.T)は買売と新規待機中/保有後の二時点です。
// 返り値: ありません。Source全返済で17枚の完結純額−3774円を鏡像確認します。
func TestRuntimeSourceCloseFillOrder(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, pending := range []bool{false, true} {
			r, at := input87Runtime(t, side)
			if err := r.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			q := r.last
			for _, after := range []float64{.5, 1, 2, 3, 4} {
				q.Time, q.Index, q.Line = at+after, q.Index+1, q.Line+1
				if pending && after == .5 || !pending && after == 2 {
					close87(r, q.Time, side, 17)
				}
				observe87(t, r, q)
			}
			if len(r.result.SourceEvents) != 1 || r.result.SourceEvents[0].Origin != "quote" || r.result.SourceEquivalence.CurrentSHA256 != r.result.SourceEquivalence.LegacySHA256 {
				t.Fatal("Source通知の重複又は互換差", r.result.SourceEvents)
			}
			for _, mode := range Modes {
				for delay := 0; delay <= 1; delay++ {
					b := r.books[bookKey(mode, delay)].Result()
					want := 17
					if pending && delay == 1 {
						want = 0
					}
					if b.Metrics.OpenQuantity != 0 || b.Metrics.EntryQuantity != want || b.Metrics.ExitQuantity != want || b.Metrics.NetPnLYen != float64(-222*want) || len(b.SourceEffects) != 1 {
						t.Fatal("Source通知とfillの同原行順序・量・費用が不一致", side, pending, mode, delay, b)
					}
				}
			}
		}
	}
}

// TestRuntimeTimerReferenceNoFill は実Forceを優先し参照Force通知を失わず受領します。
//
// 引数: t(*testing.T)は鏡像二方向です。
// 返り値: ありません。timerで約定・源時計の書換えをせず、D1は次1秒を待ちます。
func TestRuntimeTimerReferenceNoFill(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, at := input87Runtime(t, side)
		if err := r.advanceTimer(at, false); err != nil {
			t.Fatal(err)
		}
		q := r.last
		for _, after := range []float64{.5, 1} {
			q.Time, q.Index, q.Line = at+after, q.Index+1, q.Line+1
			observe87(t, r, q)
		}
		last := r.last
		if err := r.advanceTimer(r.session.ForceClose, false); err != nil {
			t.Fatal(err)
		}
		if len(r.result.SourceEvents) != 1 || r.result.SourceEvents[0].At != r.session.ForceClose || r.result.SourceEvents[0].SourceAt != last.Time || r.last != last {
			t.Fatal("timer通知又は源時計を改変しました", r.result.SourceEvents)
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				b := r.books[bookKey(mode, delay)].Result()
				if b.Metrics.OpenQuantity != 17 || b.Metrics.ExitQuantity != 0 || len(b.SourceEffects) != 1 || b.SourceEffects[0].ExitRequested != 0 || b.SourceEffects[0].At != r.session.ForceClose {
					t.Fatal("timerがfill又は重複返済しました", b)
				}
			}
		}
		for _, after := range []float64{0, 1} {
			q.Time, q.Index, q.Line = r.session.ForceClose+after, q.Index+1, q.Line+1
			observe87(t, r, q)
		}
		for _, b := range r.books {
			v := b.Result()
			if v.Metrics.OpenQuantity != 0 || v.Metrics.NetPnLYen != -3774 {
				t.Fatal("場末返済が正常原行で完結しません", v)
			}
		}
	}
}
