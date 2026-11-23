package minishortfinance

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	bank "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	old100 "github.com/masayoshi4649/SessionTradeExecuter/minigrossguard100"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	short "github.com/masayoshi4649/SessionTradeExecuter/minishortexit"
	x5 "github.com/masayoshi4649/SessionTradeExecuter/minix5"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

type shortCall struct {
	Kind        string                    `json:"kind"`
	At          float64                   `json:"at"`
	Observation *Observation              `json:"observation"`
	Line        int64                     `json:"line"`
	Batches     []NativeBatch             `json:"batches"`
	Input       *short.TechnicalGateInput `json:"input"`
	Candidates  []ShortHeldCandidate      `json:"candidates"`
	Assessments []ShortAssessment         `json:"assessments"`
}
type shortHarness struct {
	t                   *testing.T
	book                *ActualBook
	old                 *old100.ActualBook
	source              *source
	side                int
	index               int64
	callbacks, compares int
	calls               []shortCall
	gate                ShortExitGate
}

// newShortHarness は停止Source器具だけでS又はP0対照を作ります。
//
// 引数: t(*testing.T)、side(int)、slip(float64)、delay(int)、policy(ExitPolicy)、control(bool)です。
// 返り値: *shortHarnessは手製Sourceの公開API人工です。自然FARの生成はしません。
func newShortHarness(t *testing.T, side int, slip float64, delay int, policy ExitPolicy, control bool) *shortHarness {
	t.Helper()
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", SlipPts: slip, DelaySeconds: delay, ExitPolicy: policy}
	var b *ActualBook
	var err error
	if policy == "" {
		b, err = NewActualBook(session(), cfg)
	} else {
		b, err = NewShortExitBook(session(), cfg, "人工限月")
	}
	if err != nil {
		t.Fatal(err)
	}
	h := &shortHarness{t: t, book: b, source: newSource(), side: side, index: -1, calls: []shortCall{}}
	if control {
		h.old, err = old100.NewActualBook(session(), old100.ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", SlipPts: slip, DelaySeconds: delay})
		if err != nil {
			t.Fatal(err)
		}
	}
	h.compare()
	return h
}

// compare は旧100P0へ初期/全呼出/最終の全文bytesを除外0で比較します。
//
// 引数: ありません。
// 返り値: ありません。私有限月や追加S記録は空Exitへ出しません。
func (h *shortHarness) compare() {
	if h.old == nil {
		return
	}
	a, _ := json.Marshal(h.book.Snapshot())
	b, _ := json.Marshal(h.old.Snapshot())
	if string(a) != string(b) {
		h.t.Fatalf("空Exit旧100全文差\n新=%s\n旧=%s", a, b)
	}
	h.compares++
}

// shortInputFixture は実Raw値だけを原行出典とし、速度/現在量を手製で付けます。
//
// 引数: o(Observation)、line(int64)、side(int)、state(string)は人工原行と境界選択です。
// 返り値: short.TechnicalGateInputは完全な公開型です。架空の実保有/新規候補は作りません。
func shortInputFixture(o Observation, line int64, side int, state string) short.TechnicalGateInput {
	at, s := o.Time, float64(side)
	end, quarter := float64(int64(o.Time)/180*180), float64(int64(o.Time)/900*900)
	t := far80.TechnicalView{ExitKnown: true, Bar3End: end, Bar15End: quarter, EMA8_3: 1000, Close3: 1000 + s*10, Histogram3: s, PreviousHistogram3: 0}
	evidence := func(end float64) bank.BarEvidence {
		return bank.BarEvidence{BarEnd: end, AvailableAt: end, ObservedClock: at + 100, Rows: 1, DataKnown: true, HasLastSource: true, LastSource: bank.SourceStamp{Time: end - 1, Index: 90000, Line: 1, Last: t.Close3, Valid: true}}
	}
	q := far82.CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: o.Time, Received: o.Received, SourceIndex: o.Index, SourceLine: line, Last: o.Last, Bid: o.Bid, Ask: o.Ask,
		Buy: far81.CurrentSupport{OFIKnown: true, OFI30: -s, OwnAt: o.Time}, Sell: far81.CurrentSupport{OFIKnown: true, OFI30: -s, OwnAt: o.Time}}}
	q.Short = far82.CurrentShort{Time: o.Time, Mid: o.Bid + (o.Ask-o.Bid)/2, Five: far82.CurrentShortWindow{Known: true, Move: -10 * s, Speed: -2 * s, Elapsed: 5, Endpoint: o.Time - 5, Reason: "手製5秒"}, Fifteen: far82.CurrentShortWindow{Known: true, Move: -15 * s, Speed: -s, Elapsed: 15, Endpoint: o.Time - 15, Reason: "手製15秒"}}
	switch state {
	case "順":
		q.Short.Five.Move, q.Short.Five.Speed = 10*s, 2*s
	case "15未知":
		q.Short.Fifteen.Known = false
	case "15順":
		q.Short.Fifteen.Move, q.Short.Fifteen.Speed = 15*s, s
	case "量未知":
		q.Buy.OFIKnown, q.Sell.OFIKnown = false, false
	}
	return short.TechnicalGateInput{SnapshotID: fmt.Sprintf("%s-Q%d", session().ID, o.Index), At: at, Kind: "Day", Current: q, Recent3: nil, Chart: bank.Snapshot{Scene: bank.Scene{ID: session().ID, Contract: "人工限月", Start: session().Start}, At: at, HasObservedClock: true, ObservedClock: at + 100, Three: evidence(end), Fifteen: evidence(quarter), Chart: far82.ChartView{Technical: t}}}
}

// step はSource→旧全Step→短秒callbackの順を新公開APIで検査します。
//
// 引数: at/move(float64)、news([]native.Signal)、state(string)は手製原行/通知/純境界です。
// 返り値: ありません。Input/Sourceの深い不変も確認します。
func (h *shortHarness) step(at, move float64, news []native.Signal, state string) {
	h.index++
	o := observation(at, move, h.side, h.index, false)
	line := h.index + 20
	news = valueCopy(news)
	method := "D164_15"
	if h.book.result.Session.Kind == "Night" {
		method = "P164_06"
		for i := range news {
			if news[i].Action == "new" {
				var e map[string]any
				json.Unmarshal(news[i].Evidence, &e)
				e["method"] = "NK225_" + method
				news[i].Evidence, _ = json.Marshal(e)
			}
		}
	}
	batch := h.source.step(stamp(o, line), news)
	batch.Method = method
	batches := []NativeBatch{batch}
	call := shortCall{Kind: "quote", At: at, Observation: &o, Line: line, Batches: valueCopy(batches), Candidates: []ShortHeldCandidate{}, Assessments: []ShortAssessment{}}
	var input *short.TechnicalGateInput
	var gate ShortExitGate
	if isShortPolicy(h.book.result.Config.ExitPolicy) {
		in := shortInputFixture(o, line, h.side, state)
		in.Kind = h.book.result.Session.Kind
		in.Chart.Scene.ID = h.book.result.Session.ID
		in.Chart.Scene.Start = h.book.result.Session.Start
		in.SnapshotID = fmt.Sprintf("%s-Q%d", in.Chart.Scene.ID, o.Index)
		if in.Kind == "Night" {
			in.Current.Night = far81.CurrentStructure{Available: true, Window: "E08", Time: o.Time, Index: o.Index, Band: far81.CurrentBandWindow{QuantityKnown: state != "量未知", Time: o.Time, Index: o.Index}}
			if h.side == 1 {
				in.Current.Night.Band.AskRefill = 1
			} else {
				in.Current.Night.Band.BidRefill = 1
			}
		}
		input = &in
		call.Input = &in
		gate = func(c ShortHeldCandidate, in short.TechnicalGateInput) (ShortAssessment, error) {
			h.callbacks++
			call.Candidates = append(call.Candidates, valueCopy(c))
			var a ShortAssessment
			var err error
			if h.gate != nil {
				a, err = h.gate(c, in)
			} else {
				a, err = short.AssessShortExit(in, c.Side, string(c.Policy))
			}
			if err == nil {
				call.Assessments = append(call.Assessments, valueCopy(a))
			}
			return a, err
		}
	}
	before, _ := json.Marshal(struct {
		B []NativeBatch
		I *short.TechnicalGateInput
	}{batches, input})
	if err := h.book.OnNativeStepWithShortExit(o, line, batches, input, gate); err != nil {
		h.t.Fatal(err)
	}
	after, _ := json.Marshal(struct {
		B []NativeBatch
		I *short.TechnicalGateInput
	}{batches, input})
	if string(before) != string(after) {
		h.t.Fatal("Source/Inputを書換え")
	}
	if h.old != nil {
		if err := h.old.OnNativeStep(o, line, legacyBatch(batches)); err != nil {
			h.t.Fatal(err)
		}
	}
	h.calls = append(h.calls, call)
	h.compare()
}

// grid は新規だけを処理し、Sを追加評価しないことを確認します。
//
// 引数: at(float64)は人工5分時計です。
// 返り値: ありません。
func (h *shortHarness) grid(at float64) {
	n := h.callbacks
	if err := h.book.OnEntryGridWithGate(at, allowHeldEntry); err != nil {
		h.t.Fatal(err)
	}
	if h.callbacks != n {
		h.t.Fatal("gridでS評価")
	}
	if h.old != nil {
		if err := h.old.OnEntryGridWithGate(at, func(c old100.EntryCandidate) (old100.GateDecision, error) {
			return old100.GateDecision{Policy: "E3S", SnapshotID: "人工入口", Known: true, Allowed: true, Role: "順行", Reason: "金融接続の入口stub"}, nil
		}); err != nil {
			h.t.Fatal(err)
		}
	}
	h.calls = append(h.calls, shortCall{Kind: "grid", At: at})
	h.compare()
}

// force は同時計でもSource予約だけを渡し、短秒評価を増やしません。
//
// 引数: at(float64)は人工Source timer時計です。
// 返り値: ありません。
func (h *shortHarness) force(at float64) {
	batch := h.source.force(at)
	if h.book.result.Session.Kind == "Night" {
		batch.Method = "P164_06"
	}
	batch.Delta.SourceLine = h.source.last.SourceLine
	batches := []NativeBatch{batch}
	n := h.callbacks
	if err := h.book.OnNativeForce(at, batches); err != nil {
		h.t.Fatal(err)
	}
	if h.callbacks != n {
		h.t.Fatal("ForceでS評価")
	}
	if h.old != nil {
		if err := h.old.OnNativeForce(at, legacyBatch(batches)); err != nil {
			h.t.Fatal(err)
		}
	}
	h.calls = append(h.calls, shortCall{Kind: "force", At: at, Batches: valueCopy(batches)})
	h.compare()
}

// finish は残玉/予約/pendingを架空約定なしで0へ結びます。
//
// 引数: ありません。
// 返り値: ActualResultは完結値です。
func (h *shortHarness) finish() ActualResult {
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

// setupShort は5分新規8枚を取得し、まだ追加退出しない初回利益化を作ります。
//
// 引数: t(*testing.T)、side(int)、slip(float64)、delay(int)、policy(ExitPolicy)、control(bool)です。
// 返り値: *shortHarness/float64は器具と取得後の次秒です。
func setupShort(t *testing.T, side int, slip float64, delay int, policy ExitPolicy, control bool) (*shortHarness, float64) {
	h := newShortHarness(t, side, slip, delay, policy, control)
	g := session().Start + 1800
	h.step(g-3, 0, []native.Signal{birth("A", side, 8)}, "順")
	h.step(g-2, 0, nil, "順")
	h.grid(g)
	h.step(g+0.5, 0, nil, "順")
	h.step(g+1, 0, nil, "順")
	if h.callbacks != 0 {
		t.Fatal("起動前callback")
	}
	h.step(g+2, 30, nil, "順")
	return h, g + 3
}

// runShortWave は買売/費用/遅延の16非0接続に使う固定の手製波です。
//
// 引数: t(*testing.T)、side(int)、slip(float64)、delay(int)、policy(ExitPolicy)です。
// 返り値: *shortHarness/ActualResultは実純式の要求/Fillを含む完結器具です。
func runShortWave(t *testing.T, side int, slip float64, delay int, policy ExitPolicy) (*shortHarness, ActualResult) {
	h, at := setupShort(t, side, slip, delay, policy, false)
	h.step(at, 30, []native.Signal{closeSignal("部分", "玉-A", side, 3)}, "反")
	r := h.book.Snapshot()
	if r.Metrics.ShortExitRequests != 1 || r.Metrics.SourceExitRequests != 1 || r.Positions[0].Reserved != 8 {
		t.Fatal("先行Source3→S5予約", r.Metrics)
	}
	o := r.Orders[len(r.Orders)-1]
	if o.ShortExitPoint == nil || o.ShortExitPoint.Candidate.Reserved != 3 || o.Quantity != 5 || o.RequestTime != at || o.ProtectionPoint != nil || o.HeldExitPoint != nil || o.GrossGuardPoint != nil || o.InitialRiskPoint != nil {
		t.Fatal("専用出典/量/時刻差", o)
	}
	if len(r.Fills) != 1 {
		t.Fatal("要求原行即fill")
	}
	if h.book.available(side) != 2 || h.book.available(-side) != 10 {
		t.Fatal("S予約を片側10余力へ即解放")
	}
	h.step(at, -10, nil, "反")
	if delay == 1 && h.book.Snapshot().Metrics.ShortExitFills != 0 {
		t.Fatal("D1同時計fill")
	}
	h.step(at+1, -10, nil, "反")
	h.force(at + 1)
	h.step(at+2, -10, nil, "反")
	final := h.finish()
	if final.Metrics.ShortExitFills != 1 || final.Metrics.ProtectionExitRequests != 0 || final.Totals.OpenBuy+final.Totals.OpenSell != 0 || final.Totals.NetYen >= 0 {
		t.Fatal("後続悪化の実赤字/所有0", final.Metrics, final.Totals)
	}
	for _, f := range final.Fills {
		if f.OrderID == o.ID && (f.Quote.Index <= o.RequestQuote.Index || f.Quote.Time < at+float64(delay)) {
			t.Fatal("strict後原行/D1差")
		}
	}
	return h, final
}

// TestShortFinanceMirror は実純式S2政策×4感度×売買の16口座を通します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。現在3分が順方向でも短秒の別役割で成立させます。
func TestShortFinanceMirror(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, policy := range []ExitPolicy{ExitS5Q, ExitS515Q} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					t.Run(fmt.Sprintf("%d/%s/C%.0f/D%d", side, policy, slip, delay), func(t *testing.T) { runShortWave(t, side, slip, delay, policy) })
				}
			}
		}
	}
}

// TestShortFinanceEmptyP0 は新Stepの空Exitで旧100全時点の全文を除外0にします。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestShortFinanceEmptyP0(t *testing.T) {
	total := 0
	for _, side := range []int{1, -1} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				h, at := setupShort(t, side, slip, delay, "", true)
				h.step(at, 30, []native.Signal{closeSignal("部分", "玉-A", side, 3)}, "反")
				h.step(at, 20, nil, "反")
				h.force(at)
				h.step(at+1, 10, nil, "反")
				h.finish()
				total += h.compares
			}
		}
	}
	t.Logf("空Exit旧100全JSON比較=%d、8会計、除外0", total)
}

// TestShortFinancePoliciesUnknown は15秒未知/正と現在量未知の政策差を接続します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestShortFinancePoliciesUnknown(t *testing.T) {
	for _, state := range []string{"15未知", "15順", "量未知"} {
		for _, policy := range []ExitPolicy{ExitS5Q, ExitS515Q} {
			h, at := setupShort(t, 1, 5, 1, policy, false)
			h.step(at, 30, nil, state)
			want := 0
			if policy == ExitS5Q && state != "量未知" {
				want = 1
			}
			if h.book.Snapshot().Metrics.ShortExitRequests != want {
				t.Fatal(state, policy, "政策差")
			}
			h.force(at)
			h.step(at+1, 30, nil, "順")
			h.finish()
		}
	}
}

// TestShortFinanceReservationAndNonpositive はSource/P0全予約と過去起動履歴を区別します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestShortFinanceReservationAndNonpositive(t *testing.T) {
	for _, cause := range []string{"Source全残", "P0床"} {
		h, at := setupShort(t, 1, 0, 0, ExitS5Q, false)
		n := h.callbacks
		move := 30.0
		var signals []native.Signal
		if cause == "Source全残" {
			signals = []native.Signal{closeSignal("全残", "玉-A", 1, 8)}
		} else {
			move = 0
		}
		h.step(at, move, signals, "反")
		if h.callbacks != n || h.book.Snapshot().Metrics.ShortExitRequests != 0 {
			t.Fatal("全予約の二重S")
		}
		h.force(at)
		h.step(at+1, move, nil, "反")
		h.finish()
	}
	h, at := setupShort(t, 1, 5, 0, ExitS5Q, false)
	h.step(at, 20, nil, "反")
	r := h.book.Snapshot()
	if r.Positions[0].Marks.Last.UnitNet >= 0 || r.Metrics.ShortExitRequests != 1 {
		t.Fatal("既起動・現在u非正を対象外へした")
	}
	h.force(at)
	h.step(at+1, 20, nil, "反")
	h.finish()
}

// stubShort は純採否と分離した金融境界用の整合返却型を作ります。
//
// 引数: c(ShortHeldCandidate)、in(short.TechnicalGateInput)、known/allowed(bool)は実候補/手製採否です。
// 返り値: ShortAssessmentは金融型契約だけのstubで、純式成立の証明ではありません。
func stubShort(c ShortHeldCandidate, in short.TechnicalGateInput, known, allowed bool) ShortAssessment {
	zero, neg := -0.0, -1.0
	ids := []string{"S.現在価格時計", "S.5秒速度"}
	if c.Policy == ExitS515Q {
		ids = append(ids, "S.15秒速度")
	}
	ids = append(ids, "S.現在量")
	checks := []short.TechnicalGateCheck{}
	for _, id := range ids {
		checks = append(checks, short.TechnicalGateCheck{ID: id, Known: true, Passed: true, Reason: "金融stub"})
	}
	current := in.Current
	a := ShortAssessment{Decision: short.HeldDecision{Policy: string(c.Policy), SnapshotID: c.SnapshotID, At: c.At, Side: c.Side, Known: known, Allowed: allowed, Role: "金融stub", Reason: "金融の三値境界"}, Checks: checks, Evidence: short.Evidence{SceneID: c.SessionID, Contract: c.Contract, Current: contextCurrent(current), PriceAge: &zero, ShortTime: current.Short.Time, ShortMid: current.Short.Mid,
		Five: short.ShortEvidence{Known: true, Window: current.Short.Five, SignedSpeed: &neg}, Fifteen: short.ShortEvidence{Known: true, Window: current.Short.Fifteen, SignedSpeed: &neg}, Quantity: quantityStub(c, &neg), SignedQuantity: &neg}}
	if !known {
		i := len(a.Checks) - 1
		a.Checks[i].Known = false
		a.Checks[i].Passed = false
		a.Evidence.Quantity.Known = false
		a.Evidence.Quantity.Value = nil
		a.Evidence.SignedQuantity = nil
	} else if !allowed {
		a.Checks[1].Passed = false
		a.Evidence.Five.SignedSpeed = &zero
	}
	return a
}

// contextCurrent はCurrentの実物理行を公開evidence型へ全field対応します。
//
// 引数: c(far82.CurrentEvidence)は同原行です。
// 返り値: x5.CurrentQuoteEvidenceは値だけの出典です。
func contextCurrent(c far82.CurrentEvidence) x5.CurrentQuoteEvidence {
	return x5.CurrentQuoteEvidence{Reference: c.Reference, Time: c.Time, Received: c.Received, SourceIndex: c.SourceIndex, SourceLine: c.SourceLine, Last: c.Last, Bid: c.Bid, Ask: c.Ask}
}

// quantityStub は金融境界だけの同Current量型を作ります。
//
// 引数: c(ShortHeldCandidate)、value(*float64)は実出典とstub数値です。
// 返り値: x5.QuantityEvidenceは手製の量証拠です。
func quantityStub(c ShortHeldCandidate, value *float64) x5.QuantityEvidence {
	return x5.QuantityEvidence{Kind: c.Kind, Known: true, Time: c.Quote.Time, Index: c.Quote.Index, OwnAt: c.Quote.Time, Value: value}
}

// TestShortFinanceStubAndCopies は金融三値とcallbackの深い分離・再入拒否を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。実純式の採否とstubを別試験にします。
func TestShortFinanceStubAndCopies(t *testing.T) {
	for _, state := range []struct{ known, allowed bool }{{false, false}, {true, false}, {true, true}} {
		h, at := setupShort(t, 1, 0, 0, ExitS5Q, false)
		var returned ShortAssessment
		initial := h.book.Snapshot().Positions[0].Activation.GainPoints
		h.gate = func(c ShortHeldCandidate, in short.TechnicalGateInput) (ShortAssessment, error) {
			returned = stubShort(c, in, state.known, state.allowed)
			c.Activation.GainPoints = 999
			c.Source.Kind = "変更"
			in.Current.Buy.Windows = map[string]far81.CurrentSupportWindow{"改変": {Known: true}}
			if err := h.book.OnNativeForce(c.At, nil); err == nil {
				t.Fatal("再入を許可")
			}
			return returned, nil
		}
		h.step(at, 30, nil, "反")
		want := 0
		if state.allowed {
			want = 1
		}
		r := h.book.Snapshot()
		if r.Metrics.ShortExitRequests != want || r.Positions[0].Activation.GainPoints != initial {
			t.Fatal("stub/私有値差")
		}
		returned.Checks[0].Reason = "後変更"
		if returned.Evidence.SignedQuantity != nil {
			*returned.Evidence.SignedQuantity = 999
		}
		last := h.book.Snapshot().ShortExitEvents[len(r.ShortExitEvents)-1]
		if last.Positions[0].Assessment.Checks[0].Reason == "後変更" {
			t.Fatal("返却alias")
		}
		h.force(at)
		h.step(at+1, 30, nil, "順")
		h.finish()
	}
}

// TestShortFinanceBindingRejects は専用入口/限月/同原行/返却型の破損を拒否します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。失敗口座を成功へ再使用しません。
func TestShortFinanceBindingRejects(t *testing.T) {
	for _, name := range []string{"旧Step", "欠落callback", "別限月", "Current連番", "別物理行", "別snapshot", "別side", "返却窓", "三値破損"} {
		t.Run(name, func(t *testing.T) {
			h, at := setupShort(t, 1, 0, 0, ExitS5Q, false)
			o := observation(at, 30, 1, h.index+1, false)
			line := h.index + 21
			input := shortInputFixture(o, line, 1, "反")
			gate := func(c ShortHeldCandidate, in short.TechnicalGateInput) (ShortAssessment, error) {
				a := stubShort(c, in, true, true)
				switch name {
				case "別snapshot":
					a.Decision.SnapshotID = "別"
				case "別side":
					a.Decision.Side = -c.Side
				case "返却窓":
					a.Evidence.Five.Window.Endpoint--
				case "三値破損":
					a.Checks[0].Known = false
				}
				return a, nil
			}
			var err error
			switch name {
			case "旧Step":
				err = h.book.OnNativeStep(o, line, nil)
			case "欠落callback":
				err = h.book.OnNativeStepWithShortExit(o, line, nil, &input, nil)
			default:
				if name == "別限月" {
					input.Chart.Scene.Contract = "別限月"
				}
				if name == "Current連番" {
					input.Current.SourceIndex++
				}
				if name == "別物理行" {
					input.Current.SourceLine++
				}
				err = h.book.OnNativeStepWithShortExit(o, line, nil, &input, gate)
			}
			if err == nil {
				t.Fatal("破損が成功")
			}
			if _, err = h.book.Finish(); err == nil {
				t.Fatal("失敗を成功へ再使用")
			}
		})
	}
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", ExitPolicy: ExitS5Q}
	if _, err := NewActualBook(session(), cfg); err == nil {
		t.Fatal("S限月constructor欠落")
	}
	cfg.HarvestPolicy = "H0"
	if _, err := NewShortExitBook(session(), cfg, "人工限月"); err == nil {
		t.Fatal("S/H混合")
	}
}

// TestShortFinanceNightQuiet はUSquietでも保有だけの連続判断を止めないことを確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。Night Source生存と時計は手製API条件です。
func TestShortFinanceNightQuiet(t *testing.T) {
	scene := session()
	scene.Kind = "Night"
	scene.ID = "2026-09-21_Night"
	cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", ExitPolicy: ExitS515Q, USOpen: scene.Start + 3600}
	b, err := NewShortExitBook(scene, cfg, "人工限月")
	if err != nil {
		t.Fatal(err)
	}
	h := &shortHarness{t: t, book: b, source: newSource(), side: 1, index: -1, calls: []shortCall{}}
	g := scene.Start + 1800
	h.step(g-3, 0, []native.Signal{birth("A", 1, 8)}, "順")
	h.step(g-2, 0, nil, "順")
	h.grid(g)
	h.step(g+1, 0, nil, "順")
	h.step(g+2, 30, nil, "順")
	h.step(cfg.USOpen, 30, nil, "反")
	h.grid(cfg.USOpen)
	r := h.book.Snapshot()
	if r.Metrics.ShortExitRequests != 1 || !r.GridTraces[len(r.GridTraces)-1].Quiet {
		t.Fatal("quietが保有退出を止めた")
	}
	h.force(cfg.USOpen)
	h.step(cfg.USOpen+1, 30, nil, "順")
	h.finish()
}

// TestShortFinanceFirstActivationAndPendingCancel は同原行初回起動とD1未取得取消を区別します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。空保有の全raw traceやcallbackは保存しません。
func TestShortFinanceFirstActivationAndPendingCancel(t *testing.T) {
	h := newShortHarness(t, 1, 0, 0, ExitS5Q, false)
	g := session().Start + 1800
	h.step(g-3, 0, []native.Signal{birth("A", 1, 8)}, "反")
	h.step(g-2, 0, nil, "反")
	h.grid(g)
	if len(h.book.Snapshot().ShortExitEvents) != 0 || h.callbacks != 0 {
		t.Fatal("0保有の全raw trace/callback")
	}
	h.step(g+1, 0, nil, "反")
	h.step(g+2, 30, nil, "反")
	r := h.book.Snapshot()
	if r.Metrics.ShortExitRequests != 1 || r.Positions[0].Activation.Quote.Index != h.index || h.callbacks != 1 || len(r.Fills) != 1 {
		t.Fatal("旧Step初回起動の後に同原行でS要求していない")
	}
	h.force(g + 2)
	h.step(g+3, 30, nil, "反")
	h.finish()
	h = newShortHarness(t, 1, 0, 1, ExitS515Q, false)
	h.step(g-3, 0, []native.Signal{birth("A", 1, 8)}, "反")
	h.step(g-2, 0, nil, "反")
	h.grid(g)
	h.step(g+0.5, 30, []native.Signal{closeSignal("全残", "玉-A", 1, 8)}, "反")
	r = h.book.Snapshot()
	if r.Metrics.CancelledEntries != 1 || r.Metrics.EntryFills != 0 || h.callbacks != 0 || len(r.ShortExitEvents) != 0 {
		t.Fatal("D1未取得のSource取消差")
	}
	h.step(g+1, 30, nil, "反")
	h.finish()
}

// TestExportShortFinance は実Marshalを明示env時だけ新規rootへ出します。
//
// 引数: t(*testing.T)、環境変数SHORT_FINANCE_EXPORT(string)は未使用rootです。
// 返り値: ありません。手製Input/Sourceと実candidate/assessmentを保存し、市場証明にしません。
func TestExportShortFinance(t *testing.T) {
	root := os.Getenv("SHORT_FINANCE_EXPORT")
	if root == "" {
		t.Skip("明示exportのみ")
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("使用済みroot")
	}
	if err := os.MkdirAll(root, 0755); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		for _, policy := range []ExitPolicy{ExitS5Q, ExitS515Q} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					h, r := runShortWave(t, side, slip, delay, policy)
					v := struct {
						Scope string       `json:"scope"`
						Side  int          `json:"side"`
						Calls []shortCall  `json:"calls"`
						Book  ActualResult `json:"book"`
					}{"手製Source/短秒/量の公開API人工、自然生成・市場未検査", side, h.calls, r}
					body, err := json.MarshalIndent(v, "", "  ")
					if err != nil {
						t.Fatal(err)
					}
					path := filepath.Join(root, fmt.Sprintf("方向%d_%s_C%.0f_D%d.json", side, policy, slip, delay))
					f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
					if err != nil {
						t.Fatal(err)
					}
					_, e := f.Write(body)
					ce := f.Close()
					if e != nil || ce != nil {
						t.Fatal(e, ce)
					}
				}
			}
		}
	}
}
