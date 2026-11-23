// 由来: work/101保有失効の金融案/held_exit_test.go
// 由来SHA256: 3820d20aa0685fa1581c91b01f00e80efb6c9808fff86eb967420d8eaff7ed9e
package minishortfinance

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"testing"

	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	old100 "github.com/masayoshi4649/SessionTradeExecuter/minigrossguard100"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	x5 "github.com/masayoshi4649/SessionTradeExecuter/minix5"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

type heldCall struct {
	Kind        string           `json:"kind"`
	At          float64          `json:"at"`
	Observation *Observation     `json:"observation"`
	Line        int64            `json:"line"`
	Batches     []NativeBatch    `json:"batches"`
	SnapshotID  string           `json:"snapshot_id"`
	Candidates  []HeldCandidate  `json:"candidates"`
	Assessments []HeldAssessment `json:"assessments"`
}

type heldHarness struct {
	t        *testing.T
	book     *ActualBook
	old      *old100.ActualBook
	source   *source
	side     int
	index    int64
	calls    []heldCall
	compares int
	method   string
}

// newHeldHarness はFARを運転せず、手製Source通知と任意の旧100対照を作ります。
//
// 引数: t(*testing.T)、side(int)、cfg(ActorConfig)、control(bool)は人工条件です。
// 返り値: *heldHarnessは公開APIだけを運転する器具です。
func newHeldHarness(t *testing.T, side int, cfg ActorConfig, control bool) *heldHarness {
	t.Helper()
	b, err := NewActualBook(session(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	h := &heldHarness{t: t, book: b, source: newSource(), side: side, index: -1, calls: []heldCall{}, method: "D164_15"}
	if control {
		body, _ := json.Marshal(cfg)
		var oldCfg old100.ActorConfig
		if err = json.Unmarshal(body, &oldCfg); err != nil {
			t.Fatal(err)
		}
		h.old, err = old100.NewActualBook(session(), oldCfg)
		if err != nil {
			t.Fatal(err)
		}
	}
	h.compare()
	return h
}

// compare は空Exitの旧100全JSONを各呼出後に除外0で比較します。
//
// 引数: ありません。
// 返り値: ありません。片側のラベルやnil/空を正規化しません。
func (h *heldHarness) compare() {
	if h.old == nil {
		return
	}
	a, _ := json.Marshal(h.book.Snapshot())
	b, _ := json.Marshal(h.old.Snapshot())
	if string(a) != string(b) {
		h.t.Fatalf("旧100全文差\n新=%s\n旧=%s", a, b)
	}
	h.compares++
}

// legacyBatch は通知の名前付き外型だけを明示変換します。
//
// 引数: values([]NativeBatch)は同じ公開型Deltaです。
// 返り値: []old100.NativeBatchは順序とnil/空を保ちます。
func legacyBatch(values []NativeBatch) []old100.NativeBatch {
	if values == nil {
		return nil
	}
	out := make([]old100.NativeBatch, len(values))
	for i, v := range values {
		out[i] = old100.NativeBatch{Method: v.Method, Delta: v.Delta}
	}
	return out
}

// step は一原行の実Source器具通知を新旧へ配送します。
//
// 引数: at/move(float64)、news([]native.Signal)は手製原行と公開通知です。
// 返り値: ありません。実データや指標を生成しません。
func (h *heldHarness) step(at, move float64, news []native.Signal) {
	h.index++
	o := observation(at, move, h.side, h.index, false)
	line := h.index + 20
	news = valueCopy(news)
	if h.method != "D164_15" {
		for i := range news {
			if news[i].Action == "new" {
				var e map[string]any
				json.Unmarshal(news[i].Evidence, &e)
				e["method"] = "NK225_" + h.method
				news[i].Evidence, _ = json.Marshal(e)
			}
		}
	}
	batch := h.source.step(stamp(o, line), news)
	batch.Method = h.method
	batches := []NativeBatch{batch}
	if err := h.book.OnNativeStep(o, line, batches); err != nil {
		h.t.Fatal(err)
	}
	if h.old != nil {
		if err := h.old.OnNativeStep(o, line, legacyBatch(batches)); err != nil {
			h.t.Fatal(err)
		}
	}
	copy := o
	h.calls = append(h.calls, heldCall{Kind: "quote", At: at, Observation: &copy, Line: line, Batches: valueCopy(batches)})
	h.compare()
}

// allowHeldEntry は新規の金融API検査だけに使う同じE3S人工返答です。
//
// 引数: c(EntryCandidate)は実際の新規適格候補です。
// 返り値: GateDecision/errorは人工の既知成立です。新規純技法の実証ではありません。
func allowHeldEntry(c EntryCandidate) (GateDecision, error) {
	return GateDecision{Policy: "E3S", SnapshotID: "人工入口", Known: true, Allowed: true, Role: "順行", Reason: "金融接続の入口stub"}, nil
}

// contextHeld は実HeldCandidateのQuoteへ手製の既知三反対snapshotを結びます。
//
// 引数: c(HeldCandidate)は金融の実値copyです。
// 返り値: x5.TechnicalGateInputは純接続人工だけの文脈です。EntryCandidateは作りません。
func contextHeld(c HeldCandidate) x5.TechnicalGateInput {
	at := c.At
	end := float64(int64(at) / 180 * 180)
	fifteen := float64(int64(at) / 900 * 900)
	s := float64(c.Side)
	t := far80.TechnicalView{ExitKnown: true, Bar3End: end, Bar15End: fifteen, EMA8_3: 1500, Close3: 1500 - s*10, Histogram3: -s, PreviousHistogram3: 0}
	evidence := func(end float64) chartwarmup96.BarEvidence {
		return chartwarmup96.BarEvidence{BarEnd: end, AvailableAt: end, ObservedClock: at + 100, Rows: 1, DataKnown: true, HasLastSource: true, LastSource: chartwarmup96.SourceStamp{Time: end - 1, Index: 90000, Line: 1, Last: t.Close3, Valid: true}}
	}
	q := c.Quote
	current := far82.CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: c.QuoteReceived, SourceIndex: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask,
		Buy: far81.CurrentSupport{OFIKnown: true, OFI30: -s, OwnAt: q.Time}, Sell: far81.CurrentSupport{OFIKnown: true, OFI30: -s, OwnAt: q.Time}}}
	if c.Kind == "Night" {
		current.Night = far81.CurrentStructure{Available: true, Window: "E08", Time: q.Time, Index: q.Index, Band: far81.CurrentBandWindow{QuantityKnown: true, Time: q.Time, Index: q.Index}}
		if c.Side > 0 {
			current.Night.Band.AskRefill = 1
		} else {
			current.Night.Band.BidRefill = 1
		}
	}
	return x5.TechnicalGateInput{SnapshotID: c.SnapshotID, At: at, Kind: c.Kind, Chart: chartwarmup96.Snapshot{Scene: chartwarmup96.Scene{ID: c.SessionID, Contract: "人工限月", Start: session().Start}, At: at, HasObservedClock: true, ObservedClock: at + 100, Chart: far82.ChartView{Technical: t}, Three: evidence(end), Fifteen: evidence(fifteen)}, Current: current}
}

// pureHeld は停止X5の実公開関数へ実保有copyを渡します。
//
// 引数: c(HeldCandidate)は金融が作った実保有候補です。
// 返り値: HeldAssessment/errorは純式そのものの結果です。
func pureHeld(c HeldCandidate) (HeldAssessment, error) {
	return x5.AssessHeldTechnicalExit(contextHeld(c), c.Side)
}

// grid は旧entry又は新held→entryの時計だけを進め、Quoteを再投入しません。
//
// 引数: at(float64)、gate(HeldExitGate)は観測枠と任意の保有判定です。
// 返り値: ありません。
func (h *heldHarness) grid(at float64, gate HeldExitGate) {
	snapshot := ""
	call := heldCall{Kind: "grid", At: at, Candidates: []HeldCandidate{}, Assessments: []HeldAssessment{}}
	var wrapped HeldExitGate
	if h.book.result.Config.ExitPolicy != "" {
		snapshot = fmt.Sprintf("%s-G%.0f", session().ID, at)
		wrapped = func(c HeldCandidate) (HeldAssessment, error) {
			got, err := gate(c)
			if err == nil {
				call.Candidates = append(call.Candidates, valueCopy(c))
				call.Assessments = append(call.Assessments, valueCopy(got))
			}
			return got, err
		}
	}
	call.SnapshotID = snapshot
	if err := h.book.OnEntryGridWithHeldExit(at, snapshot, allowHeldEntry, wrapped); err != nil {
		h.t.Fatal(err)
	}
	if h.old != nil {
		if err := h.old.OnEntryGridWithGate(at, func(c old100.EntryCandidate) (old100.GateDecision, error) {
			return old100.GateDecision{Policy: "E3S", SnapshotID: "人工入口", Known: true, Allowed: true, Role: "順行", Reason: "金融接続の入口stub"}, nil
		}); err != nil {
			h.t.Fatal(err)
		}
	}
	h.calls = append(h.calls, call)
	h.compare()
}

// force は同時計でもSource予約だけを進めます。
//
// 引数: at(float64)はSource timer時計です。
// 返り値: ありません。SourceLineは最後の公開物理行を明示します。
func (h *heldHarness) force(at float64) {
	b := h.source.force(at)
	b.Method = h.method
	b.Delta.SourceLine = h.source.last.SourceLine
	batches := []NativeBatch{b}
	if err := h.book.OnNativeForce(at, batches); err != nil {
		h.t.Fatal(err)
	}
	if h.old != nil {
		if err := h.old.OnNativeForce(at, legacyBatch(batches)); err != nil {
			h.t.Fatal(err)
		}
	}
	h.calls = append(h.calls, heldCall{Kind: "force", At: at, Batches: valueCopy(batches)})
	h.compare()
}

// finish は全所有/予約/Source終了を新旧公開APIで確認します。
//
// 引数: ありません。
// 返り値: ActualResultは完結した新口座です。
func (h *heldHarness) finish() ActualResult {
	r, err := h.book.Finish()
	if err != nil {
		h.t.Fatal(err)
	}
	if h.old != nil {
		if _, err = h.old.Finish(); err != nil {
			h.t.Fatal(err)
		}
	}
	h.compare()
	return r
}

// setupHeld は最初の実8枚を取得し、費用後u正益を原行で起動します。
//
// 引数: t(*testing.T)、side(int)、slip(float64)、delay(int)、exit(string)、control(bool)です。
// 返り値: *heldHarness/float64は器具と次5分枠です。
func setupHeld(t *testing.T, side int, slip float64, delay int, exit string, control bool) (*heldHarness, float64) {
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", SlipPts: slip, DelaySeconds: delay, ExitPolicy: ExitPolicy(exit)}
	h := newHeldHarness(t, side, cfg, control)
	g := session().Start + 1800
	h.step(g-3, 0, []native.Signal{birth("A", side, 8)})
	h.step(g-2, 0, nil)
	h.grid(g, pureHeld)
	h.step(g+0.5, 0, nil)
	h.step(g+1, 0, nil)
	h.step(g+2, 30, nil)
	return h, g + 300
}

// TestHeldEmptyFull100 は空Exitの全時点/最終を旧100P0へ除外0対照します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestHeldEmptyFull100(t *testing.T) {
	comparisons := 0
	for _, side := range []int{1, -1} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				h, g := setupHeld(t, side, slip, delay, "", true)
				h.step(g-1, 30, []native.Signal{closeSignal("部分", "玉-A", side, 3)})
				h.grid(g, nil)
				h.step(g+1, 20, nil)
				h.force(g + 1)
				h.step(g+2, 10, nil)
				h.finish()
				comparisons += h.compares
			}
		}
	}
	t.Logf("旧100P0全時点/最終の全文比較=%d、8会計、除外0", comparisons)
	for _, harvest := range []string{"H0", "HG"} {
		cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", SlipPts: 5, DelaySeconds: 1, HarvestPolicy: harvest}
		h := newHeldHarness(t, 1, cfg, true)
		g := session().Start + 1800
		h.step(g-3, 0, []native.Signal{birth("A", 1, 2)})
		h.step(g-2, 0, nil)
		h.grid(g, nil)
		h.step(g+1, 0, nil)
		move := 30.0
		if harvest == "HG" {
			move = 20
		}
		h.step(g+2, move, nil)
		h.step(g+3, 10, nil)
		h.step(g+4, 0, nil)
		h.force(g + 5)
		h.step(g+6, 0, nil)
		h.finish()
		t.Logf("空Exitの旧100%s全文比較=%d、除外0", harvest, h.compares)
	}
}

// stubHeld は純式の効果と分離した金融型契約だけの人工返答です。
//
// 引数: c(HeldCandidate)、known/allowed(bool)は金融からの実値と人工採否です。
// 返り値: HeldAssessmentは手製の整合型。純X5の正しさを証明しません。
func stubHeld(c HeldCandidate, known, allowed bool) HeldAssessment {
	ctx := contextHeld(c)
	q := ctx.Current
	neg, zero := -1.0, 0.0
	checks := []x5.TechnicalGateCheck{}
	for _, id := range []string{"X5.現在価格時計", "X5.公開3分", "X5.P", "X5.M", "X5.Q"} {
		checks = append(checks, x5.TechnicalGateCheck{ID: id, Known: true, Passed: true, Reason: "金融stub"})
	}
	a := HeldAssessment{Decision: x5.HeldDecision{Policy: "X5", SnapshotID: c.SnapshotID, At: c.At, Side: c.Side, Known: known, Allowed: allowed, Role: "金融stub", Reason: "金融契約の人工採否"}, Checks: checks,
		Evidence: x5.HeldEvidence{SceneID: c.SessionID, Contract: "人工限月", Current: x5.CurrentQuoteEvidence{Reference: "NK225", Time: q.Time, Received: q.Received, SourceIndex: q.SourceIndex, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask}, Three: ctx.Chart.Three,
			Quantity: x5.QuantityEvidence{Kind: c.Kind, Known: true, Time: q.Time, Index: q.SourceIndex, OwnAt: q.Time, Value: &neg}, SignedCloseEMA: &neg, SignedHistogramDelta: &neg, SignedQuantity: &neg}}
	if !known {
		a.Checks[4].Known = false
		a.Checks[4].Passed = false
		a.Evidence.Quantity.Known = false
		a.Evidence.Quantity.Value = nil
		a.Evidence.SignedQuantity = nil
	} else if !allowed {
		a.Checks[2].Passed = false
		a.Evidence.SignedCloseEMA = &zero
	}
	return a
}

// TestHeldStubContract は未知/不成立と返却pointerの後変更を金融規約だけで確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestHeldStubContract(t *testing.T) {
	for _, state := range []struct{ known, allowed bool }{{false, false}, {true, false}, {true, true}} {
		h, g := setupHeld(t, 1, 0, 0, "X5", false)
		h.step(g-1, 30, nil)
		var returned HeldAssessment
		h.grid(g, func(c HeldCandidate) (HeldAssessment, error) {
			returned = stubHeld(c, state.known, state.allowed)
			return returned, nil
		})
		r := h.book.Snapshot()
		expected := 0
		if state.allowed {
			expected = 1
		}
		if r.Metrics.HeldExitRequests != expected {
			t.Fatal(r)
		}
		returned.Checks[0].Reason = "返却後変更"
		if returned.Evidence.SignedCloseEMA != nil {
			*returned.Evidence.SignedCloseEMA = 999
		}
		row := h.book.Snapshot().HeldExitGrids[1].Positions[0]
		if row.Assessment.Checks[0].Reason != "金融stub" {
			t.Fatal("返却値がprivateへalias")
		}
		if state.allowed && *h.book.Snapshot().Orders[1].HeldExitPoint.Assessment.Evidence.SignedCloseEMA != -1 {
			t.Fatal("order point alias")
		}
		h.force(g)
		h.step(g+1, 30, nil)
		h.finish()
	}
}

// TestHeldPendingSourceCancellation は未取得D1がForceで取消されれば保有callbackを作らないと確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestHeldPendingSourceCancellation(t *testing.T) {
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", DelaySeconds: 1, ExitPolicy: "X5"}
	h := newHeldHarness(t, 1, cfg, false)
	g := session().Start + 1800
	h.step(g-3, 0, []native.Signal{birth("A", 1, 8)})
	h.step(g-2, 0, nil)
	h.grid(g, pureHeld)
	h.force(g + 0.5)
	h.step(g+1, 30, nil)
	calls := 0
	h.step(g+299, 30, nil)
	h.grid(g+300, func(c HeldCandidate) (HeldAssessment, error) { calls++; return pureHeld(c) })
	r := h.finish()
	if calls != 0 || r.Metrics.CancelledEntries != 1 || r.Metrics.EntryFills != 0 || r.Metrics.HeldExitRequests != 0 {
		t.Fatal(r)
	}
}

// TestHeldPureNextFill は純接続・半円・両遅延・要求後悪化とMTM非更新を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestHeldPureNextFill(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				h, g := setupHeld(t, side, slip, delay, "X5", false)
				move := 30.0
				if slip == 5 {
					move = 20
				} // C5は現在u<=0だが過去起動済み・床0より上。
				h.step(g-1, move, nil)
				before := h.book.Snapshot()
				h.grid(g, pureHeld)
				after := h.book.Snapshot()
				if after.Metrics.HeldExitRequests != 1 || after.Metrics.SourceExitRequests != 0 || after.Metrics.ProtectionExitRequests != 0 || after.Positions[0].Reserved != 8 || len(after.Fills) != len(before.Fills) || after.Account.Count != before.Account.Count {
					t.Fatal(after)
				}
				order := after.Orders[len(after.Orders)-1]
				if order.RequestTime != g || order.RequestQuote.Time != g-1 || order.HeldExitPoint == nil || order.ProtectionPoint != nil || order.GrossGuardPoint != nil || order.InitialRiskPoint != nil {
					t.Fatal(order)
				}
				h.step(g, 0, nil)
				if delay == 1 && h.book.Snapshot().Metrics.HeldExitFills != 0 {
					t.Fatal("D1早期fill")
				}
				h.step(g+1, 0, nil)
				h.force(g + 2)
				h.step(g+3, 0, nil)
				r := h.finish()
				if r.Metrics.HeldExitFills != 1 || r.Totals.NetYen >= 0 || r.Totals.OpenBuy+r.Totals.OpenSell != 0 || r.Metrics.ProtectionExitRequests != 0 {
					t.Fatal(r)
				}
			}
		}
	}
}

// TestHeldSourcePriority は全/部分予約とForce同時計で二重返済を拒否します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestHeldSourcePriority(t *testing.T) {
	for _, full := range []bool{false, true} {
		h, g := setupHeld(t, 1, 0, 1, "X5", false)
		h.step(g-0.5, 30, nil)
		if full {
			h.force(g)
		} else {
			h.step(g-0.25, 30, []native.Signal{closeSignal("部分", "玉-A", 1, 3)})
		}
		calls := 0
		h.grid(g, func(c HeldCandidate) (HeldAssessment, error) { calls++; return pureHeld(c) })
		r := h.book.Snapshot()
		want := 1
		qty := 5
		if full {
			want = 0
			qty = 0
		}
		if calls != want || r.Metrics.HeldExitRequests != want {
			t.Fatal(r, calls)
		}
		if !full && r.Orders[len(r.Orders)-1].Quantity != qty {
			t.Fatal(r.Orders)
		}
		h.force(g)
		h.step(g+1, 30, nil)
		h.step(g+2, 30, nil)
		r = h.finish()
		if r.Metrics.HeldExitFills != want || r.Totals.CloseQuantity != 8 {
			t.Fatal(r)
		}
	}
}

// TestHeldBeforeActivationAndBindings は起動前と誤接続/返却破損を区別します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestHeldBeforeActivationAndBindings(t *testing.T) {
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", ExitPolicy: "X5"}
	h := newHeldHarness(t, 1, cfg, false)
	g := session().Start + 1800
	h.step(g-3, 0, []native.Signal{birth("A", 1, 8)})
	h.step(g-2, 0, nil)
	h.grid(g, pureHeld)
	h.step(g+1, 0, nil)
	h.step(g+299, 0, nil)
	calls := 0
	h.grid(g+300, func(c HeldCandidate) (HeldAssessment, error) { calls++; return pureHeld(c) })
	if calls != 0 || h.book.Snapshot().Metrics.HeldExitRequests != 0 {
		t.Fatal("利益前にcallback")
	}
	h.force(g + 300)
	h.step(g+301, 0, nil)
	h.finish()
	for _, harvest := range []string{"H0", "HG"} {
		bad := cfg
		bad.HarvestPolicy = harvest
		if _, err := NewActualBook(session(), bad); err == nil {
			t.Fatal("未検証のH/X5併用")
		}
	}
	bad, _ := NewActualBook(session(), cfg)
	if err := bad.OnEntryGridWithGate(g, allowHeldEntry); err == nil {
		t.Fatal("X5が旧APIで黙ってoff")
	}
	for _, field := range []string{"Policy", "Snapshot", "At", "Side", "Index", "Line", "Received", "AND", "NaN"} {
		t.Run(field, func(t *testing.T) {
			h, g := setupHeld(t, 1, 0, 0, "X5", false)
			h.step(g-1, 30, nil)
			err := h.book.OnEntryGridWithHeldExit(g, "指定snapshot", allowHeldEntry, func(c HeldCandidate) (HeldAssessment, error) {
				a, e := pureHeld(c)
				if e != nil {
					return a, e
				}
				switch field {
				case "Policy":
					a.Decision.Policy = "A"
				case "Snapshot":
					a.Decision.SnapshotID = "別snapshot"
				case "At":
					a.Decision.At++
				case "Side":
					a.Decision.Side = -a.Decision.Side
				case "Index":
					a.Evidence.Current.SourceIndex++
				case "Line":
					a.Evidence.Current.SourceLine++
				case "Received":
					a.Evidence.Current.Received--
				case "AND":
					a.Checks[2].Passed = false
				case "NaN":
					a.Evidence.Current.Bid = math.NaN()
				}
				return a, nil
			})
			if err == nil || h.book.Snapshot().Failure == "" {
				t.Fatal("返却破損を通過")
			}
		})
	}
}

// TestHeldQuietAndCopies はquietが保有exitを止めずprivate値が変更されないことを確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。NightのUS時計とSource生存は手製API条件で、自然生成を主張しません。
func TestHeldQuietAndCopies(t *testing.T) {
	scene := session()
	scene.ID = "2026-09-21_Night"
	scene.Kind = "Night"
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", ExitPolicy: "X5", USOpen: scene.Start + 3600}
	b, err := NewActualBook(scene, cfg)
	if err != nil {
		t.Fatal(err)
	}
	h := &heldHarness{t: t, book: b, source: newSource(), side: 1, index: -1, calls: []heldCall{}, method: "P164_06"}
	entry := scene.Start + 1800
	h.step(entry-3, 0, []native.Signal{birth("A", 1, 8)})
	h.step(entry-2, 0, nil)
	h.grid(entry, pureHeld)
	h.step(entry+1, 0, nil)
	h.step(entry+2, 30, nil)
	g := cfg.USOpen
	h.step(g-1, 30, nil)
	original := h.book.Snapshot().Positions[0].Activation.GainPoints
	calls := 0
	h.grid(g, func(c HeldCandidate) (HeldAssessment, error) {
		calls++
		a, err := pureHeld(c)
		c.Activation.GainPoints = 999
		c.Source.Kind = "改変"
		c.Quote.Bid = 1
		if err2 := h.book.OnNativeForce(g, nil); err2 == nil {
			t.Fatal("callback金融再入")
		}
		return a, err
	})
	r := h.book.Snapshot()
	if calls != 1 || r.Metrics.HeldExitRequests != 1 || r.Positions[0].Activation.GainPoints != original || !r.GridTraces[len(r.GridTraces)-1].Quiet || !r.HeldExitGrids[len(r.HeldExitGrids)-1].Quiet {
		t.Fatal(r)
	}
	h.step(g, 30, nil)
	h.force(g)
	h.step(g+1, 30, nil)
	h.finish()
}

// TestHeldReservationDoesNotFreeCap はX5予約を同じ枠の余力へ足さないことを確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。Source片側現在量も10以内の器具です。
func TestHeldReservationDoesNotFreeCap(t *testing.T) {
	h, g := setupHeld(t, 1, 0, 1, "X5", false)
	h.step(g-0.5, 30, []native.Signal{closeSignal("部分", "玉-A", 1, 6)})
	h.step(g-0.4, 30, []native.Signal{birth("B", 1, 8), birth("C", -1, 10)})
	h.step(g-0.3, 30, nil)
	h.grid(g, pureHeld)
	r := h.book.Snapshot()
	if r.Positions[0].Quantity != 8 || r.Positions[0].Reserved != 8 || r.Orders[len(r.Orders)-3].HeldExitPoint == nil {
		t.Fatal(r)
	}
	last := r.GridTraces[len(r.GridTraces)-1]
	if last.AcceptedQty != 12 || last.PendingBuy != 2 || last.PendingSell != 10 || last.OpenBuy != 8 {
		t.Fatal("返済予約を余力へ即解放", last)
	}
	h.step(g+0.5, 30, nil)
	h.step(g+1, 30, nil)
	h.force(g + 2)
	h.step(g+3, 30, nil)
	r = h.finish()
	if r.Totals.OpenBuy+r.Totals.OpenSell+r.Totals.PendingBuy+r.Totals.PendingSell != 0 {
		t.Fatal(r.Totals)
	}
}

// TestExportHeldFinance は実Go型の8口座×鏡像2場を明示時だけ新規保存します。
//
// 引数: t(*testing.T)、環境変数HELD_FIXTURE_OUT(string)は未使用JSONパスです。
// 返り値: ありません。市場/Source戦略/チャート数値器の実運転は行いません。
func TestExportHeldFinance(t *testing.T) {
	path := os.Getenv("HELD_FIXTURE_OUT")
	if path == "" {
		t.Skip("明示した新規出力だけ")
	}
	type scene struct {
		Side  int                     `json:"side"`
		Books map[string]ActualResult `json:"books"`
		Calls map[string][]heldCall   `json:"calls"`
		Scope string                  `json:"scope"`
	}
	scenes := []scene{}
	for _, side := range []int{1, -1} {
		s := scene{Side: side, Books: map[string]ActualResult{}, Calls: map[string][]heldCall{}, Scope: "手製Source通知/ATR/技法・実Go API。元FAR/原板の再現ではない"}
		for _, exit := range []string{"", "X5"} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					h, g := setupHeld(t, side, slip, delay, exit, false)
					h.step(g-0.5, 30, []native.Signal{closeSignal("部分", "玉-A", side, 3)})
					h.grid(g, pureHeld)
					h.step(g, 0, nil)
					h.step(g+1, 0, nil)
					h.force(g + 2)
					h.step(g+3, 0, nil)
					r := h.finish()
					s.Books[r.Key] = r
					s.Calls[r.Key] = h.calls
				}
			}
		}
		scenes = append(scenes, s)
	}
	body, err := json.MarshalIndent(map[string]any{"scope": "保有exit金融APIの手製非0人工のみ", "scenes": scenes, "純X5停止SHA256": "f57be6c9f32cac86cbfb34cffd931d8a76250144c2d2f544b55f8f1dc9f7b62b"}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(append(body, '\n')); err != nil {
		f.Close()
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
}
