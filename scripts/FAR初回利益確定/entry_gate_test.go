// 由来: scripts/FAR5分枠の順行反転と数量/entry_gate_test.go
// 由来SHA256: 3cb58b0dc8d5722fa0b157b1ec5b9ea591900a2515cee5b46013aebc78abcfca
package miniharvest

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"testing"

	old "github.com/masayoshi4649/SessionTradeExecuter/minigrid"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// gateFixture96 は旧Go型の手製Source通知で技法判定前の状態だけを用意します。
//
// 引数: t(*testing.T)、side(int)、state(string)、policy(string)は試験器・鏡像・状態・政策です。
// 返り値: *ActualBook/float64は未判定口座と最初の割当枠です。
func gateFixture96(t *testing.T, side int, state, policy string) (*ActualBook, float64) {
	t.Helper()
	s := session94()
	grid := s.Start + 1800
	if state == "quiet" {
		grid = s.Start + 300
	}
	b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: policy})
	if err != nil {
		t.Fatal(err)
	}
	src := newFixtureSource94()
	index := int64(0)
	feed := func(at float64, news []native.Signal, cancelled []string, bad bool) {
		o := observation95(s, side, index, at, 0, 20)
		o.QuoteOK = !bad
		delta := src.step(t, o, index+20, news, cancelled)
		if err := b.OnNativeStep(o, index+20, []NativeBatch{delta}); err != nil {
			t.Fatal(err)
		}
		index++
	}
	var cancelled []string
	if state == "cancelled" {
		cancelled = []string{"技法A"}
	}
	feed(grid-1, []native.Signal{birth94("技法A", side, 5)}, cancelled, state == "pending")
	if state != "pending" && state != "cancelled" {
		feed(grid-.9, nil, nil, false)
	}
	if state == "closing" || state == "closed" {
		quantity := 2
		if state == "closed" {
			quantity = 5
		}
		feed(grid-.8, []native.Signal{close94("技法源返済", "技法A", side, quantity)}, nil, false)
		if state == "closed" {
			feed(grid-.7, nil, nil, false)
		}
	}
	if state == "bad_quote" {
		feed(grid-.1, nil, nil, true)
	}
	return b, grid
}

// TestGate96MirrorAndConsumption は許可/拒否/未知を符号対称に一枠だけ消費します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。許可でも金融量/Sourceを変えません。
func TestGate96MirrorAndConsumption(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, policy := range []string{"A", "B", "AB"} {
			for _, kind := range []string{"allow", "deny", "unknown"} {
				t.Run(fmt.Sprintf("%d_%s_%s", side, policy, kind), func(t *testing.T) {
					b, grid := gateFixture96(t, side, "filled", policy)
					calls := 0
					gate := func(c EntryCandidate) (GateDecision, error) {
						calls++
						if c.Ordinal != 1 || c.At != grid || c.Side != side || c.Quantity != 5 || c.Available != 10 || c.Source.SignalID != "技法A" {
							t.Fatal("候補の公開値/旧min", c)
						}
						return GateDecision{Policy: policy, SnapshotID: "共通公開文脈", Known: kind != "unknown", Allowed: kind == "allow", Role: "技法役割", Reason: kind}, nil
					}
					before := b.Snapshot()
					if err := b.OnEntryGridWithGate(grid, gate); err != nil {
						t.Fatal(err)
					}
					r := b.Snapshot()
					p := r.EntryOpportunities[0]
					if calls != 1 || !p.Consumed || p.Gate == nil || p.Gate.Policy != policy || p.RequiredUnknown != (kind == "unknown") ||
						(p.Status == "accepted") != (kind == "allow") || r.Account.Count != before.Account.Count || len(r.Fills) != len(before.Fills) {
						t.Fatal("一枠判定/既知未知/金融に副作用", p)
					}
					if kind == "allow" {
						if p.Requested != 5 || r.Orders[0].Quantity != 5 || r.Orders[0].Side != side || r.Key != policy+"_B5Q_P0_C0_D0" {
							t.Fatal("採否が旧注文を変更", r.Orders)
						}
					} else if len(r.Orders) != 0 || p.Requested != 0 {
						t.Fatal("拒否/未知で実注文")
					}
					if err := b.OnEntryGridWithGate(grid+300, gate); err != nil || calls != 1 || b.result.GridTraces[1].CandidateCount != 0 {
						t.Fatal("同出生を再判定", err)
					}
				})
			}
		}
	}
}

// TestGate96PriorFinancialFilters はquiet/源状態/正常気配が技法判定より先であることを確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。不適格候補のcallbackは0回です。
func TestGate96PriorFinancialFilters(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, state := range []string{"quiet", "pending", "cancelled", "closing", "closed", "bad_quote"} {
			t.Run(fmt.Sprintf("%d_%s", side, state), func(t *testing.T) {
				b, grid := gateFixture96(t, side, state, "A")
				calls := 0
				gate := func(c EntryCandidate) (GateDecision, error) {
					calls++
					return GateDecision{}, fmt.Errorf("不適格候補へ到達")
				}
				if err := b.OnEntryGridWithGate(grid, gate); err != nil {
					t.Fatal(err)
				}
				p := b.Snapshot().EntryOpportunities[0]
				if calls != 0 || p.Gate != nil || !p.Consumed || p.Status != "expired" || p.RequiredUnknown != (state == "bad_quote") {
					t.Fatal("既存検査順", p)
				}
			})
		}
	}
}

// TestGate96Copies はcallback候補と保存判定の値複写を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。callbackの局所編集を金融へ書き戻しません。
func TestGate96Copies(t *testing.T) {
	b, grid := gateFixture96(t, 1, "filled", "A")
	source := b.Snapshot().EntryOpportunities[0].Source
	answer := GateDecision{Policy: "A", SnapshotID: "元snapshot", Known: true, Allowed: true, Role: "元役割", Reason: "許可"}
	gate := func(c EntryCandidate) (GateDecision, error) {
		c.Side, c.Quantity, c.Available = -1, 999, 999
		c.Source.BirthQuantity, c.Source.BirthQuote.Ask, c.Quote.Ask = 999, 1, 1
		return answer, nil
	}
	if err := b.OnEntryGridWithGate(grid, gate); err != nil {
		t.Fatal(err)
	}
	answer.SnapshotID, answer.Role = "後の書換", "後の役割"
	p := b.Snapshot().EntryOpportunities[0]
	if p.Side != 1 || p.Requested != 5 || !reflect.DeepEqual(p.Source, source) || p.Gate.SnapshotID != "元snapshot" || p.Gate.Role != "元役割" {
		t.Fatal("callback入力/返答のalias", p)
	}
	r := b.Snapshot()
	r.EntryOpportunities[0].Gate.SnapshotID = "Snapshotからの書換"
	if b.Snapshot().EntryOpportunities[0].Gate.SnapshotID != "元snapshot" {
		t.Fatal("Snapshot値copyのalias")
	}
}

// TestGate96Capacity は予約/実保有の既存capを先に計算し、技法へ量を決めさせません。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。空き0はcallbackなし、空き2は旧min2を保持します。
func TestGate96Capacity(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, first := range []int{8, 10} {
			t.Run(fmt.Sprintf("%d_%d", side, first), func(t *testing.T) {
				s := session94()
				g := s.Start + 2400
				b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "A"})
				if err != nil {
					t.Fatal(err)
				}
				src := newFixtureSource94()
				index := int64(0)
				feed := func(at float64, news []native.Signal) {
					o := observation95(s, side, index, at, 0, 20)
					d := src.step(t, o, index+20, news, nil)
					if err := b.OnNativeStep(o, index+20, []NativeBatch{d}); err != nil {
						t.Fatal(err)
					}
					index++
				}
				calls, got := 0, 0
				gate := func(c EntryCandidate) (GateDecision, error) {
					calls++
					got = c.Quantity
					return GateDecision{Policy: "A", SnapshotID: "容量文脈", Known: true, Allowed: true}, nil
				}
				feed(g-302, []native.Signal{birth94("先行容量", side, first)})
				feed(g-301, nil)
				if err := b.OnEntryGridWithGate(g-300, gate); err != nil {
					t.Fatal(err)
				}
				feed(g-299, nil)
				feed(g-1, []native.Signal{birth94("後続容量", side, 5)})
				feed(g-.9, nil)
				if err := b.OnEntryGridWithGate(g, gate); err != nil {
					t.Fatal(err)
				}
				p := b.Snapshot().EntryOpportunities[1]
				if first == 10 {
					if calls != 1 || p.Gate != nil || p.Requested != 0 || p.Reason != "片側上限に空きなし" {
						t.Fatal("空き0で技法判定", p)
					}
				} else if calls != 2 || got != 2 || p.Requested != 2 || p.Available != 2 || p.Source.BirthQuantity != 5 || p.Gate == nil || b.result.Metrics.CapClippedEntries != 1 {
					t.Fatal("技法がmin/capを変更", p)
				}
			})
		}
	}
}

// TestGate96MixedUnknown は同枠の未知と許可を分け、新規行動の優先を維持します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。未知を待機へ隠さず、許可を未知へ上書きしません。
func TestGate96MixedUnknown(t *testing.T) {
	s := session94()
	g := s.Start + 1800
	b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "AB"})
	if err != nil {
		t.Fatal(err)
	}
	src := newFixtureSource94()
	for i, at := range []float64{g - 1, g - .9} {
		o := observation95(s, 1, int64(i), at, 0, 20)
		var news []native.Signal
		if i == 0 {
			news = []native.Signal{birth94("未知候補", 1, 2), birth94("許可候補", 1, 3)}
		}
		d := src.step(t, o, int64(i+20), news, nil)
		if err := b.OnNativeStep(o, int64(i+20), []NativeBatch{d}); err != nil {
			t.Fatal(err)
		}
	}
	if err := b.OnEntryGridWithGate(g, func(c EntryCandidate) (GateDecision, error) {
		return GateDecision{Policy: "AB", SnapshotID: "同枠共通", Known: c.Ordinal == 2, Allowed: c.Ordinal == 2}, nil
	}); err != nil {
		t.Fatal(err)
	}
	r := b.Snapshot()
	if r.GridTraces[0].Action != "新規" || r.GridTraces[0].UnknownCount != 1 || r.GridTraces[0].AcceptedCount != 1 || r.GridTraces[0].AcceptedQty != 3 {
		t.Fatal("未知と許可の優先/分母", r.GridTraces)
	}
}

// TestGate96InvalidContract はnil政策対応と返答の破損を拒否します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。異常を通常未知に吸収しません。
func TestGate96InvalidContract(t *testing.T) {
	for _, kind := range []string{"empty_with_gate", "policy_without_gate", "policy", "snapshot", "unknown_allowed", "callback_error"} {
		t.Run(kind, func(t *testing.T) {
			policy := "A"
			if kind == "empty_with_gate" {
				policy = ""
			}
			b, grid := gateFixture96(t, 1, "filled", policy)
			gate := EntryGate(func(c EntryCandidate) (GateDecision, error) {
				d := GateDecision{Policy: "A", SnapshotID: "文脈", Known: true, Allowed: true}
				switch kind {
				case "policy":
					d.Policy = "B"
				case "snapshot":
					d.SnapshotID = ""
				case "unknown_allowed":
					d.Known = false
				case "callback_error":
					return d, fmt.Errorf("人工例外")
				}
				return d, nil
			})
			if kind == "policy_without_gate" {
				gate = nil
			}
			if err := b.OnEntryGridWithGate(grid, gate); err == nil || b.failure == nil || len(b.result.Orders) != 0 {
				t.Fatal("判定契約破損を受理")
			}
		})
	}
	for _, cfg := range []ActorConfig{{Policy: "P0", EntryTiming: "N", GatePolicy: "A"}, {Policy: "P0", EntryTiming: "B5", GatePolicy: "B"},
		{Policy: "P1", EntryTiming: "B5Q", GatePolicy: "AB"}, {Policy: "P0", EntryTiming: "B5Q", GatePolicy: "G0"}} {
		if _, err := NewActualBook(session94(), cfg); err == nil {
			t.Fatal("未定義構成を受理", cfg)
		}
	}
	b, grid := gateFixture96(t, 1, "filled", "A")
	valid := EntryCandidate{Ordinal: 1, At: grid, Side: 1, Source: b.result.EntryOpportunities[0].Source, Quote: b.last, Available: 10, Quantity: 5}
	for _, kind := range []string{"side", "nan", "future_quote", "nongrid", "quantity"} {
		c := valid
		switch kind {
		case "side":
			c.Side = 0
		case "nan":
			c.At = math.NaN()
		case "future_quote":
			c.Quote.Time = c.At + 1
		case "nongrid":
			c.At++
		case "quantity":
			c.Quantity = 11
		}
		calls := 0
		if _, err := evaluateEntryGate("A", func(EntryCandidate) (GateDecision, error) { calls++; return GateDecision{}, nil }, c); err == nil || calls != 0 {
			t.Fatal("候補破損がcallbackへ到達", kind)
		}
	}
}

// TestGate96G0Full95 は追加omitemptyが空のG0を旧95全金融本文へ逐次比較します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。N/B5/B5Q・買売・C0/C5・D0/D1を含みます。
func TestGate96G0Full95(t *testing.T) {
	for _, side := range []int{-1, 1} {
		fixture := captureWave95(t, side)
		for _, timing := range []string{"N", "B5", "B5Q"} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					b, err := NewActualBook(fixture.Session, ActorConfig{Policy: "P0", EntryTiming: timing, SlipPts: slip, DelaySeconds: delay, USOpen: fixture.Session.USOpen})
					if err != nil {
						t.Fatal(err)
					}
					prior, err := old.NewActualBook(fixture.Session, old.ActorConfig{Policy: "P0", EntryTiming: timing, SlipPts: slip, DelaySeconds: delay, USOpen: fixture.Session.USOpen})
					if err != nil {
						t.Fatal(err)
					}
					compare := func() {
						x, _ := json.Marshal(b.Snapshot())
						y, _ := json.Marshal(prior.Snapshot())
						if !bytes.Equal(x, y) {
							t.Fatal("G0旧95全本文差", b.result.Key, side)
						}
					}
					for _, event := range fixture.Events {
						if event.Kind == "grid" {
							err = b.OnEntryGrid(fixture.Grids[event.Index])
							if err == nil {
								err = prior.OnEntryGrid(fixture.Grids[event.Index])
							}
						} else {
							step := fixture.Steps[event.Index]
							oldBatches := make([]old.NativeBatch, len(step.Batches))
							for i, batch := range step.Batches {
								oldBatches[i] = old.NativeBatch{Method: batch.Method, Delta: batch.Delta}
							}
							err = b.OnNativeStep(step.Observation, step.SourceLine, step.Batches)
							if err == nil {
								err = prior.OnNativeStep(step.Observation, step.SourceLine, oldBatches)
							}
						}
						if err != nil {
							t.Fatal(err)
						}
						compare()
					}
					if _, err = b.Finish(); err != nil {
						t.Fatal(err)
					}
					if _, err = prior.Finish(); err != nil {
						t.Fatal(err)
					}
					compare()
				}
			}
		}
	}
}
