package lighttape97

import (
	"encoding/json"
	"testing"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// testSignal は公開JSONのTargets型を利用し、Source戦略を呼ばず人工通知を作ります。
//
// 引数: t(*testing.T)、id/action(string)、quantity(int)、at(float64)、index(int64)、targets(string)です。
// 返り値: native.Signalは公開APIの人工値です。
func testSignal(t *testing.T, id, action string, quantity int, at float64, index int64, targets string) native.Signal {
	t.Helper()
	var s native.Signal
	if targets == "" {
		targets = "[]"
	}
	if err := json.Unmarshal([]byte(`{"targets":`+targets+`}`), &s); err != nil {
		t.Fatal(err)
	}
	s.ID, s.Action, s.Quantity, s.Time, s.SourceIndex, s.Reason = id, action, quantity, at, index, "人工通知"
	s.Side = 1
	if action == "close" {
		s.Side = -1
	}
	s.Evidence = json.RawMessage(`{"kind":"初回","parent":"人工親","source_id":"人工元","quantity_micro":30,"method":"NK225_D164_15"}`)
	return s
}

// qStamp は有限の人工Source行を作ります。
//
// 引数: at(float64)、index(int64)は価格時計と特徴連番です。
// 返り値: native.QuoteStampは正常BBOと物理行を持ちます。
func qStamp(at float64, index int64) native.QuoteStamp {
	return native.QuoteStamp{Time: at, Index: index, SourceLine: index + 10, Last: 50005, Bid: 50000, Ask: 50010, QuoteOK: true}
}

// TestCloseBeforeFromReservations は先行予約と当行SourceFill後の未通知量を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。CloseNoticeを最後の残量から逆算しません。
func TestCloseBeforeFromReservations(t *testing.T) {
	const method = "D164_15"
	at := 100000.0
	q0, q1, q2, q3 := qStamp(at, 0), qStamp(at+1, 1), qStamp(at+2, 2), qStamp(at+3, 3)
	a := testSignal(t, "a", "new", 5, at, 0, "")
	b := testSignal(t, "b", "new", 4, at, 0, "")
	c1 := testSignal(t, "c1", "close", 3, at+2, 2, `[{"id":"A","quantity":2},{"id":"B","quantity":1}]`)
	c2 := testSignal(t, "c2", "close", 1, at+3, 3, `[{"id":"A","quantity":1}]`)
	c3 := testSignal(t, "c3", "close", 1, at+3, 3, `[{"id":"A","quantity":1}]`)
	ledger := native.Ledger{Method: "NK225_" + method, Signals: []native.SignalRecord{{Signal: a, Origin: "quote", At: at, Quote: q0}, {Signal: b, Origin: "quote", At: at, Quote: q0}, {Signal: c1, Origin: "quote", At: at + 2, Quote: q2}, {Signal: c2, Origin: "quote", At: at + 3, Quote: q3}, {Signal: c3, Origin: "quote", At: at + 3, Quote: q3}},
		Fills: []native.FillRecord{{Fill: native.Fill{SignalID: "a", HoldID: "A", Quantity: 5}, Action: "new", Side: 1, Quote: q1}, {Fill: native.Fill{SignalID: "b", HoldID: "B", Quantity: 4}, Action: "new", Side: 1, Quote: q1}, {Fill: native.Fill{SignalID: "c1", Closed: c1.Targets, Quantity: 3}, Action: "close", Side: -1, Quote: q3}}}
	s, err := NewSourceIndex(map[string]native.Ledger{method: ledger}, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, q := range []native.QuoteStamp{q0, q1} {
		if _, err = s.Take(q.Time, "quote", q, []string{method}); err != nil {
			t.Fatal(err)
		}
	}
	one, err := s.Take(q2.Time, "quote", q2, []string{method})
	if err != nil {
		t.Fatal(err)
	}
	if len(one[0].Delta.Closes) != 2 || one[0].Delta.Closes[0].Before != 5 || one[0].Delta.Closes[1].Before != 4 {
		t.Fatal("複数Target Before")
	}
	two, err := s.Take(q3.Time, "quote", q3, []string{method})
	if err != nil {
		t.Fatal(err)
	}
	if len(two[0].Delta.Closes) != 2 || two[0].Delta.Closes[0].Before != 3 || two[0].Delta.Closes[1].Before != 2 {
		t.Fatal("SourceFill→先行close予約を反映しない")
	}
	if err = s.Finish(); err != nil {
		t.Fatal(err)
	}
}

// TestCancellationOriginRequired はLedgerだけでは曖昧な同時計Force取消を拒否します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。明示の元配送Originがある時だけ再構成します。
func TestCancellationOriginRequired(t *testing.T) {
	const method = "P164_06"
	q := qStamp(100000, 0)
	sig := testSignal(t, "n", "new", 2, q.Time, 0, "")
	sig.Evidence = json.RawMessage(`{"kind":"初回","parent":"人工親","source_id":"人工元","quantity_micro":20,"method":"NK225_P164_06"}`)
	l := native.Ledger{Method: "NK225_" + method, Signals: []native.SignalRecord{{Signal: sig, Origin: "quote", At: q.Time, Quote: q}}, Cancellations: []native.Cancellation{{SignalID: "n", At: q.Time, Quote: q, Reason: "同時計Force"}}}
	if _, err := NewSourceIndex(map[string]native.Ledger{method: l}, nil); err == nil {
		t.Fatal("不足Originを勝手にquoteへ分類")
	}
	s, err := NewSourceIndex(map[string]native.Ledger{method: l}, []CancelRoute{{method, "n", "timer", q.Time, q.SourceLine}})
	if err != nil {
		t.Fatal(err)
	}
	first, err := s.Take(q.Time, "quote", q, []string{method})
	if err != nil {
		t.Fatal(err)
	}
	force, err := s.Take(q.Time, "timer", native.QuoteStamp{}, []string{method})
	if err != nil {
		t.Fatal(err)
	}
	if len(first[0].Delta.Cancellations) != 0 || len(force[0].Delta.Cancellations) != 1 || force[0].Delta.SourceLine != q.SourceLine {
		t.Fatal("Forceの位相又は直前行が相違")
	}
	if err = s.Finish(); err != nil {
		t.Fatal(err)
	}
}

// TestEmptyMethodsAreObservable はP空batchを省くと元の出生位置/計数が変わる反例です。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Source出生のbatch_indexを選択順位へ変えません。
func TestEmptyMethodsAreObservable(t *testing.T) {
	session := actual.Session{ID: "人工Night", Kind: "Night", Start: 100000, ForceClose: 143200, End: 143800, USOpen: 120000}
	q := qStamp(121801, 0)
	sig := testSignal(t, "u", "new", 3, q.Time, q.Index, "")
	sig.Evidence = json.RawMessage(`{"kind":"初回","parent":"人工親","source_id":"人工元","quantity_micro":30,"method":"NK225_U165_03"}`)
	original := []actual.NativeBatch{{Method: "P164_06", Delta: empty(q.Time, "quote", q.SourceLine)}, {Method: "U165_03", Delta: empty(q.Time, "quote", q.SourceLine)}}
	original[1].Delta.Signals = append(original[1].Delta.Signals, native.SignalRecord{Signal: sig, Origin: "quote", At: q.Time, Quote: q})
	methods, nonempty, err := CompressBatches(original)
	if err != nil {
		t.Fatal(err)
	}
	if len(methods) != 2 || len(nonempty) != 1 {
		t.Fatal("空手法圧縮の形")
	}
	scalar := ScalarQuote{Time: q.Time, Received: q.Time, Index: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask, QuoteOK: true}
	full, err := RestoreBatches(TapeEvent{Kind: "quote", At: q.Time, Quote: &scalar, Methods: methods, NonEmpty: nonempty}, map[string]int64{})
	if err != nil {
		t.Fatal(err)
	}
	good, err := actual.NewActualBook(session, actual.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen})
	if err != nil {
		t.Fatal(err)
	}
	bad, err := actual.NewActualBook(session, actual.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen})
	if err != nil {
		t.Fatal(err)
	}
	if err = good.OnNativeStep(scalar.Observation(), q.SourceLine, full); err != nil {
		t.Fatal(err)
	}
	if err = bad.OnNativeStep(scalar.Observation(), q.SourceLine, nonempty); err != nil {
		t.Fatal(err)
	}
	a, b := good.Snapshot(), bad.Snapshot()
	if a.Metrics.NativeBatches != 2 || b.Metrics.NativeBatches != 1 || a.EntryOpportunities[0].BatchIndex != 1 || b.EntryOpportunities[0].BatchIndex != 0 {
		t.Fatal("空batch省略の反例が成立しない")
	}
}
