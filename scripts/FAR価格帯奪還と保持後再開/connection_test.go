package far92

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
)

// compareControl92 は旧89金融と共有の全値を人工で比較します。
//
// 引数: t(*testing.T)、got(ReplayResult)、old(far89.ReplayResult)は同じ合成入力です。
// 返り値: ありません。
func compareControl92(t *testing.T, got ReplayResult, old far89.ReplayResult) {
	t.Helper()
	for _, pair := range []struct {
		name string
		a, b any
	}{{"quality", got.Quality, old.Quality}, {"references", got.ReferenceCounts, old.ReferenceCounts}, {"grid", got.GridDecisions, old.GridDecisions}, {"source", got.SourceEvents, old.SourceEvents}, {"sourceEq", got.SourceEquivalence, old.SourceEquivalence}, {"trace", got.EntryObservations, old.EntryObservations}, {"technical", got.TechnicalEquivalence, old.TechnicalEquivalence}, {"seed", got.SeedView, old.SeedView}, {"end", got.InputEnd, old.InputEnd}} {
		equal89JSON(t, pair.name, pair.a, pair.b)
	}
	for delay := 0; delay <= 1; delay++ {
		equal89JSON(t, "control", got.Books[bookKey("H0G1", delay)], old.Books[bookKey("E1G1", delay)])
	}
	bindings := []EntryOrderBinding{}
	for _, b := range old.EntryBindings {
		if b.Policy == "E1" && b.BookKey == bookKey("E1G1", b.DelaySeconds) {
			b.BookKey = bookKey("H0G1", b.DelaySeconds)
			bindings = append(bindings, b)
		}
	}
	equal89JSON(t, "control受理binding", got.EntryBindings, bindings)
	if len(got.PriceDecisions) != len(got.GridDecisions) || got.PriceCounts.Records != len(got.EntryObservations) {
		t.Fatal("新観測分母が一致しません")
	}
}

// TestReplay92ControlFullArtificial は自然Source合成3場の旧全文を検査します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。実市場は読みません。
func TestReplay92ControlFullArtificial(t *testing.T) {
	for _, mirror := range []bool{false, true} {
		m := input89MultiFixture(t, mirror)
		seeds, err := far80.PrepareTechnicalSeeds(m)
		if err != nil {
			t.Fatal(err)
		}
		for _, input := range m.Sessions {
			seed := seeds[input.ID]
			copy := seed
			got, err := Replay(m.Root, input, &copy)
			if err != nil {
				t.Fatal(err)
			}
			copy = seed
			old, err := far89.Replay(m.Root, input, &copy)
			if err != nil {
				t.Fatal(err)
			}
			compareControl92(t, got, old)
		}
	}
}

// TestBatch92SequentialParallel は人工場の並列独立性と上書拒否を検査します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestBatch92SequentialParallel(t *testing.T) {
	m := input89MultiFixture(t, false)
	a := filepath.Join(t.TempDir(), "逐次")
	b := filepath.Join(t.TempDir(), "並列")
	if err := RunBatch(m, a, 1, nil); err != nil {
		t.Fatal(err)
	}
	if err := RunBatch(m, b, 2, nil); err != nil {
		t.Fatal(err)
	}
	for _, s := range m.Sessions {
		x, _ := os.ReadFile(filepath.Join(a, s.ID+".json"))
		y, _ := os.ReadFile(filepath.Join(b, s.ID+".json"))
		if !bytes.Equal(x, y) {
			t.Fatal("並列差", s.ID)
		}
	}
	if RunBatch(m, a, 1, nil) == nil {
		t.Fatal("既存出力を上書")
	}
}

// runConnection92 は手製価格と旧API人工を全4会計の実約定へ接続します。
//
// 引数: t(*testing.T)、side(int)、oldEvent(bool)は方向と旧E1資格です。
// 返り値: *replayRuntimeは新v成立と旧金融の完結を持つ人工です。
func runConnection92(t *testing.T, side int, oldEvent bool) *replayRuntime {
	t.Helper()
	r, grid, tech := connection89Fixture(t, side, oldEvent)
	f := newPriceFixture(side)
	f.epoch = grid.At - 7*180
	for _, p := range [][2]float64{{-15, -16}, {-20, -19}, {-10, -11}, {0, -10}, {-5, -7}, {5, -6}} {
		f.add(t, p[0], p[1])
	}
	r.priceTracker = f.tracker
	r.result.EntryObservations = f.records
	r.result.PriceDecisions = []PriceDecision{}
	r.result.PriceBindings = []PriceEntryBinding{}
	r.result.PriceCounts = f.tracker.Counts()
	r.result.SourceEvents = []SourceEvent{}
	controls := map[int]*far89.Book{}
	supplied, _, err := FilterEntry("E1", grid.Source, grid.Entry)
	if err != nil {
		t.Fatal(err)
	}
	initial := tech
	initial.Bar3End -= 180
	initial.Bar15End -= 180
	for delay := 0; delay <= 1; delay++ {
		b, e := far89.NewSourceBook(r.session.ID, "S", 100)
		if e != nil {
			t.Fatal(e)
		}
		if e = b.SetFillDelay(float64(delay)); e != nil {
			t.Fatal(e)
		}
		if e = b.OnQuote(r.last, ReferenceFrame{}, initial, nil); e != nil {
			t.Fatal(e)
		}
		if e = b.OnSourceGrid(grid.At, r.last, supplied, grid.C0, tech, grid.StructureAnchor); e != nil {
			t.Fatal(e)
		}
		controls[delay] = b
	}
	if err := r.supplyEntryGrid(grid, tech); err != nil {
		t.Fatal(err)
	}
	for delay, b := range controls {
		equal89JSON(t, "非0受理時H0旧全文", r.books[bookKey("H0G1", delay)].Result(), b.Result())
	}
	for _, offset := range []float64{.5, 1, 2, 3, 4, 5} {
		q := r.last
		q.Time = grid.At + offset
		q.Index++
		q.Line++
		move := 0.0
		if offset >= 2 {
			move = float64(side) * 40
		}
		q.Bid = grid.C0.Base.Quote.Bid + move
		q.Ask = grid.C0.Base.Quote.Ask + move
		q.Last = q.Bid
		frame := ReferenceFrame{Closes: []ReferenceClose{}}
		if offset == 2 {
			frame.Closes = []ReferenceClose{{ID: "部分通知", ReferenceID: grid.Source.Lots[1].Reference.ID, Before: 8, Quantity: 3, Reason: "人工部分"}}
		}
		if offset == 4 {
			frame.Closes = []ReferenceClose{{ID: "全部通知", ReferenceID: grid.Source.Lots[1].Reference.ID, Before: 5, Quantity: 5, Reason: "人工全部"}}
		}
		if len(frame.Closes) > 0 {
			r.recordSourceEvent(q.Time, "quote", q, ReadSnapshot{Method: grid.Source.Method, At: q.Time, SourceIndex: q.Index, Started: true, Closes: frame.Closes}, q.Line)
		}
		if err := r.deliverQuote(q, frame, tech, connection89Current(q, offset)); err != nil {
			t.Fatal(err)
		}
		for delay, b := range controls {
			if err := b.OnQuote(q, frame, tech, connection89Current(q, offset)); err != nil {
				t.Fatal(err)
			}
			equal89JSON(t, "非0各原行H0旧全文", r.books[bookKey("H0G1", delay)].Result(), b.Result())
		}
	}
	if err := r.flushProfitContexts(); err != nil {
		t.Fatal(err)
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(mode, delay)
			b := r.books[key].Result()
			r.result.Books[key] = b
			want := mode == "H1G1" || oldEvent
			if want && (len(b.Lots) != 1 || b.Lots[0].InitialQuantity != 8 || b.Unresolved || !b.Lots[0].Flag) {
				t.Fatal("非0完結/正益が未確認", key, b.Metrics)
			}
			if !want && len(b.Lots) != 0 {
				t.Fatal("旧E1 falseでcontrolが参加")
			}
		}
	}
	return r
}

// TestConnection92NewTriggerNonzero は旧E1不成立でも新vを使えることを検証します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestConnection92NewTriggerNonzero(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, old := range []bool{false, true} {
			r := runConnection92(t, side, old)
			want := 2
			if old {
				want = 4
			}
			if len(r.result.PriceBindings) != want {
				t.Fatal("新binding数", len(r.result.PriceBindings))
			}
			if len(r.result.EntryBindings) != (want - 2) {
				t.Fatal("旧bindingへH1が混入")
			}
			for _, b := range r.result.PriceBindings {
				if b.Policy == "H1" && (b.BasePolicy != "E0" || !b.PriceQualification.TriggerValid || b.CurrentQualification.E1Allowed != old) {
					t.Fatal(b)
				}
			}
		}
	}
}

// TestPriceFilterUnknownWaitAndRank はH0診断非gateと最終順位分離を検査します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPriceFilterUnknownWaitAndRank(t *testing.T) {
	r, grid, tech := connection89Fixture(t, 1, true)
	_ = tech
	s, err := NewPriceTracker().Snapshot(grid.At)
	if err != nil {
		t.Fatal(err)
	}
	_, h0, e := FilterPriceEntry("H0", grid, s)
	if e != nil || len(h0.SuppliedIDs) != 2 {
		t.Fatal("H0を未知でgate", e)
	}
	_, h1, e := FilterPriceEntry("H1", grid, s)
	if e != nil || len(h1.SuppliedIDs) != 0 || !h1.Pool[1].RequiredUnknown {
		t.Fatal("H1未知補完", e)
	}
	grid.ClockAllowed = false
	if err := r.supplyEntryGrid(grid, tech); err != nil {
		t.Fatal(err)
	}
	if len(r.result.PriceBindings) != 0 {
		t.Fatal("時計不可で新規")
	}
	for _, b := range r.books {
		if len(b.Result().Orders) != 0 {
			t.Fatal("金融へ候補を供給")
		}
	}
}

// TestPriceFilterCurrentBBO は確定足と現在気配の維持を分離します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPriceFilterCurrentBBO(t *testing.T) {
	for _, side := range []int{1, -1} {
		r := runConnection92(t, side, true)
		grid := r.result.GridDecisions[0]
		s := r.result.PriceDecisions[0].Snapshot
		for i := range s.Directions {
			if s.Directions[i].Side == side {
				h := s.Directions[i].High.Close
				grid.C0.Base.Quote.Bid = h
				grid.C0.Base.Quote.Ask = h + 10
				if side < 0 {
					grid.C0.Base.Quote.Ask = h
					grid.C0.Base.Quote.Bid = h - 10
				}
			}
		}
		_, p, e := FilterPriceEntry("H1", grid, s)
		if e != nil || len(p.SuppliedIDs) != 0 {
			t.Fatal("H同値気配を許可", e)
		}
	}
}

// TestConnection92CopyAndPermanentSeen は診断値の非共有と旧seenを確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestConnection92CopyAndPermanentSeen(t *testing.T) {
	r := runConnection92(t, 1, true)
	before, _ := json.Marshal(r.result.PriceBindings)
	s, _ := r.priceTracker.Snapshot(r.last.Time)
	s.Directions[0].Impulse.ObservationID = 999
	after, _ := json.Marshal(r.result.PriceBindings)
	if !bytes.Equal(before, after) {
		t.Fatal("既読binding変化")
	}
	for _, b := range r.books {
		x := b.Result()
		if x.Decisions[0].SourceContext.SeenAfterCount != 1 || x.SourcePolicy != "S" || x.Mode != "S0G1" {
			t.Fatal(x.Mode)
		}
	}
	if reflect.DeepEqual(r.result.PriceBindings[0].PoolEvaluation, PricePoolEvaluation{}) {
		t.Fatal(fmt.Sprint("根拠なし"))
	}
}

// TestPriceSnapshotCorruptions は偽の公開点と旗を供給前に拒否します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPriceSnapshotCorruptions(t *testing.T) {
	r := runConnection92(t, 1, true)
	grid := r.result.GridDecisions[0]
	original := r.result.PriceDecisions[0].Snapshot
	mutations := []func(*PriceSnapshot){
		func(s *PriceSnapshot) { s.Directions[0].Resume.PublishedAt = s.At + 1 },
		func(s *PriceSnapshot) { s.Directions[0].Resume.BarEnd = s.At + 1 },
		func(s *PriceSnapshot) { s.Directions[0].High.Close = math.Inf(1) },
		func(s *PriceSnapshot) { s.Directions[0].Hold = s.Directions[0].Resume },
		func(s *PriceSnapshot) { s.Directions[0].TriggerValid = false },
		func(s *PriceSnapshot) { s.Directions[0].ExpiresAt = nil },
		func(s *PriceSnapshot) { s.Directions[0].Side = -1 },
		func(s *PriceSnapshot) { s.Directions[0].Known = false },
	}
	for i, mutate := range mutations {
		data, _ := json.Marshal(original)
		var s PriceSnapshot
		if err := json.Unmarshal(data, &s); err != nil {
			t.Fatal(err)
		}
		mutate(&s)
		if _, _, err := FilterPriceEntry("H1", grid, s); err == nil {
			t.Fatal("破損受理", i)
		}
	}
}
