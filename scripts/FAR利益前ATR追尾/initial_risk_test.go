package minirisk98

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"testing"

	prior "github.com/masayoshi4649/SessionTradeExecuter/miniharvest"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// TestRisk98EmptyFull97 は空risk八会計を旧97H0へ全呼出時点で全文比較します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。買売×費用×遅延×Gate空/ABの16系列、通常と次板悪化を含みます。
func TestRisk98EmptyFull97(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"通常", "次気配悪化"} {
			fixture := harvestWave97(t, side, mode)
			for _, gate := range []string{"", "AB"} {
				for _, slip := range []float64{0, 5} {
					for _, delay := range []int{0, 1} {
						cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", GatePolicy: gate, SlipPts: slip, DelaySeconds: delay}
						b, err := NewActualBook(fixture.Session, cfg)
						if err != nil {
							t.Fatal(err)
						}
						old, err := prior.NewActualBook(fixture.Session, prior.ActorConfig{Policy: cfg.Policy, EntryTiming: cfg.EntryTiming, HarvestPolicy: cfg.HarvestPolicy, GatePolicy: gate, SlipPts: slip, DelaySeconds: delay})
						if err != nil {
							t.Fatal(err)
						}
						compare := func() {
							x, _ := json.Marshal(b.Snapshot())
							y, _ := json.Marshal(old.Snapshot())
							if !bytes.Equal(x, y) {
								t.Fatal("空riskの旧97全field差", side, mode, cfg)
							}
							if bytes.Contains(x, []byte("risk_policy")) || bytes.Contains(x, []byte("initial_risk")) {
								t.Fatal("空設定の新tag出現")
							}
						}
						compare()
						for _, e := range fixture.Events {
							if e.Kind == "grid" {
								var callback EntryGate
								var oldCallback prior.EntryGate
								if gate != "" {
									callback = func(c EntryCandidate) (GateDecision, error) {
										return GateDecision{Policy: gate, SnapshotID: "人工枠", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
									}
									oldCallback = func(c prior.EntryCandidate) (prior.GateDecision, error) {
										return prior.GateDecision{Policy: gate, SnapshotID: "人工枠", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
									}
								}
								err = b.OnEntryGridWithGate(fixture.Grids[e.Index], callback)
								if err == nil {
									err = old.OnEntryGridWithGate(fixture.Grids[e.Index], oldCallback)
								}
							} else if e.Kind == "quote" {
								step := fixture.Steps[e.Index]
								batches := make([]prior.NativeBatch, len(step.Batches))
								for i, batch := range step.Batches {
									batches[i] = prior.NativeBatch{Method: batch.Method, Delta: batch.Delta}
								}
								err = b.OnNativeStep(step.Observation, step.SourceLine, step.Batches)
								if err == nil {
									err = old.OnNativeStep(step.Observation, step.SourceLine, batches)
								}
							} else {
								t.Fatal("未対応人工イベント", e.Kind)
							}
							if err != nil {
								t.Fatal(err)
							}
							compare()
						}
						r, err := b.Finish()
						if err != nil {
							t.Fatal(err)
						}
						previous, err := old.Finish()
						if err != nil {
							t.Fatal(err)
						}
						x, _ := json.Marshal(r)
						y, _ := json.Marshal(previous)
						if !bytes.Equal(x, y) {
							t.Fatal("空riskの最終旧97差")
						}
					}
				}
			}
		}
	}
}

// riskWave98 は同じ手製Sourceをrisk空/R05/R10の24口座へ渡します。
//
// 引数: t(*testing.T)、side(int)、mode(string)は試験器/鏡像/事前固定の境界波形です。
// 返り値: fixtureHarvest97は全入力と新金融結果です。自然Source/ATR/市場結果ではありません。
func riskWave98(t *testing.T, side int, mode string) fixtureHarvest97 {
	t.Helper()
	s := session94()
	grid := s.Start + 1800
	out := fixtureHarvest97{Session: s, Scope: "手製Source/ATR/常時許可AB callbackのAPI人工。価格データ/自然Source/純技法の有効性は未検査。", Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}, Grids: []float64{}, Events: []fixtureEvent95{}, Actors: map[string]ActualResult{}}
	actors := map[string]*ActualBook{}
	for _, risk := range []string{"", "R05", "R10"} {
		for _, gate := range []string{"", "AB"} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", RiskPolicy: risk, GatePolicy: gate, SlipPts: slip, DelaySeconds: delay})
					if err != nil {
						t.Fatal(err)
					}
					actors[b.result.Key] = b
				}
			}
		}
	}
	src := newFixtureSource94()
	index := int64(0)
	feed := func(at, move, atr float64, signals ...native.Signal) {
		o := observation95(s, side, index, at, move, atr)
		batch := src.step(t, o, index+20, signals, nil)
		before, _ := json.Marshal(batch)
		for _, b := range actors {
			if err := b.OnNativeStep(o, index+20, []NativeBatch{batch}); err != nil {
				t.Fatal(mode, b.result.Key, err)
			}
			if b.available(1) < 0 || b.available(-1) < 0 {
				t.Fatal("予約込みcap超過")
			}
			for _, p := range b.result.Positions {
				if p.Quantity > 0 && p.Reserved > 0 && b.available(p.Side) == 10 {
					t.Fatal("返済予約だけで片側余力を解放")
				}
			}
		}
		after, _ := json.Marshal(batch)
		if !bytes.Equal(before, after) {
			t.Fatal("共通Source通知の書換え")
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "quote", Index: len(out.Steps)})
		out.Steps = append(out.Steps, fixtureStep94{Observation: o, SourceLine: index + 20, Batches: []NativeBatch{batch}})
		index++
	}
	atr := 100.0
	if mode == "非緩和" || mode == "Source部分" || mode == "Source全予約" || mode == "利益移行" || mode == "risk要求後正益" {
		atr = 20
	}
	if mode == "未知後既知" {
		atr = 0
	}
	feed(grid-1, 0, atr, birth94("risk出生", side, 5))
	feed(grid-.9, 0, atr)
	for _, b := range actors {
		var callback EntryGate
		if b.result.Config.GatePolicy != "" {
			callback = func(c EntryCandidate) (GateDecision, error) {
				return GateDecision{Policy: "AB", SnapshotID: "人工枠", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
			}
		}
		if err := b.OnEntryGridWithGate(grid, callback); err != nil {
			t.Fatal(err)
		}
	}
	out.Events = append(out.Events, fixtureEvent95{Kind: "grid", Index: 0})
	out.Grids = append(out.Grids, grid)
	feed(grid, 0, atr)
	feed(grid+1, 0, atr)
	for _, b := range actors {
		if b.result.Config.RiskPolicy != "" {
			r := b.result.Positions[0].InitialRisk
			if r == nil || !r.HasMark || r.PeakGain != -10 || r.FloorGain != -r.Width {
				t.Fatal("初期0を観測した扱い又は初期床", b.result.Key, r)
			}
		}
	}
	switch mode {
	case "幅と次板悪化":
		feed(grid+2, -40, atr)
		feed(grid+2, -50, atr)
		feed(grid+3, -50, atr)
		feed(grid+4, -90, atr)
		feed(grid+4, -110, atr)
		feed(grid+5, -110, atr)
	case "非緩和":
		feed(grid+2, 10, atr)
		feed(grid+3, 20, atr)
		feed(grid+4, 15, atr)
		feed(grid+5, 0, atr)
		feed(grid+5, -5, atr)
		feed(grid+6, -5, atr)
	case "未知後既知":
		feed(grid+2, 0, 20)
		feed(grid+3, -115, 20)
		feed(grid+3, -125, 20)
		feed(grid+4, -125, 20)
	case "Source部分":
		feed(grid+2, -10, atr, close94("源部分", "risk出生", side, 2))
		feed(grid+3, -20, atr)
	case "Source全予約":
		feed(grid+1.5, 0, atr, close94("源全予約", "risk出生", side, 5))
		feed(grid+2, -10, atr)
		feed(grid+2.5, -20, atr)
		feed(grid+3, -20, atr)
	case "利益移行":
		feed(grid+2, 30, atr)
		feed(grid+2, -10, atr)
		feed(grid+3, -10, atr)
	case "risk要求後正益":
		feed(grid+2, -10, atr)
		feed(grid+3, 40, atr)
	default:
		t.Fatal("未定義risk人工", mode)
	}
	forceBatches := []NativeBatch{}
	remaining := src.quantity["玉-risk出生"] - src.reserved["玉-risk出生"]
	if remaining > 0 {
		signal := close94("riskForce", "risk出生", side, remaining)
		signal.Time, signal.SourceIndex = s.ForceClose, src.last.Index
		src.orders[signal.ID] = signal
		src.pending = append(src.pending, signal)
		src.reserved["玉-risk出生"] += remaining
		delta := native.StepResult{At: s.ForceClose, Origin: "timer", SourceLine: src.last.SourceLine, Signals: []native.SignalRecord{{Signal: signal, Origin: "timer", At: s.ForceClose, Quote: src.last}}, Closes: []native.CloseNotice{{ID: signal.ID + "|玉-risk出生", ReferenceID: "玉-risk出生", Before: remaining, Quantity: remaining, Reason: signal.Reason}}}
		forceBatches = append(forceBatches, NativeBatch{Method: "D164_15", Delta: delta})
	}
	for _, b := range actors {
		before := b.Snapshot()
		if err := b.OnNativeForce(s.ForceClose, forceBatches); err != nil {
			t.Fatal(err)
		}
		after := b.Snapshot()
		if len(before.Fills) != len(after.Fills) || before.Account.Count != after.Account.Count {
			t.Fatal("Forceで原行fill/MTMを作った")
		}
	}
	out.Events = append(out.Events, fixtureEvent95{Kind: "force", Index: 0})
	out.Timers = append(out.Timers, fixtureTimer94{At: s.ForceClose, Batches: forceBatches})
	feed(s.ForceClose, -125, atr)
	feed(s.ForceClose+1, -125, atr)
	for key, b := range actors {
		r, err := b.Finish()
		if err != nil {
			t.Fatal(err)
		}
		if !r.Complete || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 {
			t.Fatal("最終所有/予約", key)
		}
		out.Actors[key] = r
	}
	return out
}

// TestRisk98WidthClampFallback は幅の最小/最大/非丸め/未知固定を純状態で検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。ATRは手製公開値でSource指標の再計算ではありません。
func TestRisk98WidthClampFallback(t *testing.T) {
	for _, policy := range []string{"R05", "R10"} {
		for _, atr := range []float64{0, 1, 20, 41, 250, 1000} {
			b, err := NewActualBook(session94(), ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", RiskPolicy: policy})
			if err != nil {
				t.Fatal(err)
			}
			o := observation94(session94(), 1, 0, 0, 0, atr)
			q := quoteActual(o, 20)
			p := ActualPosition{EntryQuote: q}
			if err = b.lockInitialRisk(&p, o, q); err != nil {
				t.Fatal(err)
			}
			m := 1.0
			if policy == "R05" {
				m = .5
			}
			want := 125.0
			if atr > 0 {
				want = math.Max(20, math.Min(125, m*atr))
			}
			if p.InitialRisk.Width != want || p.InitialRisk.ATRKnown != (atr > 0) || p.InitialRisk.HasMark || p.InitialRisk.PeakUpdated != nil || p.InitialRisk.FloorGain != -want {
				t.Fatal("幅/未知/架空peak", policy, atr, p.InitialRisk)
			}
			if err = b.lockInitialRisk(&p, o, q); err == nil {
				t.Fatal("二度の幅固定")
			}
		}
	}
}

// TestRisk98MirrorsAndSource は損失側要求/利益移行/Source優先/費用/遅延を人工で確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。期待損益は実fillの買売価格と指定費用から別算術で確認します。
func TestRisk98MirrorsAndSource(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"幅と次板悪化", "非緩和", "未知後既知", "Source部分", "Source全予約", "利益移行", "risk要求後正益"} {
			t.Run(fmt.Sprintf("%d_%s", side, mode), func(t *testing.T) {
				fixture := riskWave98(t, side, mode)
				for key, r := range fixture.Actors {
					if r.Config.RiskPolicy == "" {
						continue
					}
					p := r.Positions[0]
					risk := p.InitialRisk
					if risk == nil {
						t.Fatal("risk証拠不足")
					}
					qty, requests := 0, 0
					for _, order := range r.Orders {
						if order.Reason != InitialRiskExitReason {
							continue
						}
						qty += order.Quantity
						requests++
						if order.ProtectionPoint != nil || order.InitialRiskPoint == nil || order.InitialRiskPoint.Mark.Phase != PhaseAfterSource || order.InitialRiskPoint.Mark.UnitNet > 0 {
							t.Fatal("要求のphase/利益前条件", key, order)
						}
						for _, fill := range r.Fills {
							if fill.OrderID == order.ID {
								if fill.Quote.Index <= order.RequestQuote.Index || fill.Quote.Time < order.RequestTime+float64(r.Config.DelaySeconds) {
									t.Fatal("同原行/遅延fill", key)
								}
								want := float64(p.Side)*(fill.Price-p.EntryPrice)*float64(fill.Quantity)*100 - float64(fill.Quantity)*(77+2*r.Config.SlipPts*100)
								if fill.Allocations[0].NetYen != want {
									t.Fatal("独立の半円/滑り算術", key, fill)
								}
							}
						}
					}
					if r.Metrics.InitialRiskExitRequests != requests {
						t.Fatal("risk要求counterの分離", key, requests, r.Metrics)
					}
					switch mode {
					case "幅と次板悪化":
						if qty != 5 || risk.FirstHit == nil || risk.ProfitTransition != nil || p.ProtectionActive || p.FirstFloorHit != nil || p.FloorGain != nil {
							t.Fatal("利益前だけの追尾", key, qty, risk)
						}
					case "未知後既知":
						if risk.ATRKnown || risk.Width != 125 || p.ATR == nil || risk.ATRValue != 0 || qty != 5 {
							t.Fatal("未知幅を書換え", key, risk, p.ATR)
						}
					case "非緩和":
						if r.Config.SlipPts == 5 {
							if risk.PeakGain != 10 || risk.FloorGain != -10 || qty != 5 || risk.ProfitTransition != nil {
								t.Fatal("床の非緩和", key, risk, qty)
							}
						} else if risk.ProfitTransition == nil || qty != 0 {
							t.Fatal("正益H移行", key)
						}
					case "Source部分":
						if qty != 3 || risk.FirstHit == nil {
							t.Fatal("Source部分の先行予約", key, qty)
						}
					case "Source全予約":
						if qty != 0 || risk.FirstHit == nil || risk.FirstHit.Mark.Reserved != 5 {
							t.Fatal("Source全予約の床観測と要求分離", key, qty, risk)
						}
					case "利益移行":
						if risk.ProfitTransition == nil || p.Activation == nil || qty != 0 || risk.FirstHit != nil || p.FirstFloorHit == nil {
							t.Fatal("Hとriskの分離", key, risk, p.Activation)
						}
					case "risk要求後正益":
						if qty != 5 || risk.FirstHit == nil || risk.ProfitTransition == nil || p.Activation == nil || p.Activation.Phase != PhasePreFill || r.Metrics.ProtectionExitRequests != 0 {
							t.Fatal("既受理risk要求の継続と利益移行", key, risk, p.Activation, r.Metrics)
						}
					}
				}
				if dir := os.Getenv("RISK98_EXPORT"); dir != "" {
					if err := os.MkdirAll(dir, 0755); err != nil {
						t.Fatal(err)
					}
					body, err := json.MarshalIndent(fixture, "", "  ")
					if err != nil {
						t.Fatal(err)
					}
					if err = os.WriteFile(filepath.Join(dir, fmt.Sprintf("方向%d_%s.json", side, mode)), append(body, '\n'), 0644); err != nil {
						t.Fatal(err)
					}
				}
			})
		}
	}
}

// TestRisk98Configuration は未定義の政策/組合せを受理しない境界を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestRisk98Configuration(t *testing.T) {
	for _, cfg := range []ActorConfig{{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", RiskPolicy: "R00"}, {Policy: "P0", EntryTiming: "B5Q", RiskPolicy: "R05"}, {Policy: "P0", EntryTiming: "N", HarvestPolicy: "H0", RiskPolicy: "R05"}, {Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", GatePolicy: "A", RiskPolicy: "R10"}, {Policy: "P1", EntryTiming: "B5Q", HarvestPolicy: "H0", RiskPolicy: "R10"}} {
		if _, err := NewActualBook(session94(), cfg); err == nil {
			t.Fatal("未定義組合せ", cfg)
		}
	}
}

// TestRisk98StrictZeroAndLatchedProfit はu同値0と利益移行後の逆行を単元状態で確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。人工MTMでriskの再起動やH床への混入を拒否します。
func TestRisk98StrictZeroAndLatchedProfit(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, slip := range []float64{0, 5} {
			b, err := NewActualBook(session94(), ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", RiskPolicy: "R05", SlipPts: slip})
			if err != nil {
				t.Fatal(err)
			}
			o := observation94(session94(), side, 0, 0, 0, 0)
			entry, mark := .23, 1.0
			if slip == 5 {
				mark = 11
			}
			if side < 0 {
				entry, mark = mark, .23
			}
			o.Bid, o.Ask = mark, mark+.01
			if side < 0 {
				o.Bid, o.Ask = mark-.01, mark
			}
			o.Last = (o.Bid + o.Ask) / 2
			q := quoteActual(o, 20)
			p := ActualPosition{ID: "単元risk", Side: side, InitialQuantity: 1, Quantity: 1, EntryPrice: entry, EntryQuote: q}
			if err = b.lockInitialRisk(&p, o, q); err != nil {
				t.Fatal(err)
			}
			b.result.Positions = append(b.result.Positions, p)
			if err = b.markPositions(o, q, PhaseAfterSource, false); err != nil {
				t.Fatal(err)
			}
			p = b.result.Positions[0]
			if p.Marks.Last.UnitNet != 0 || p.ProtectionActive || p.InitialRisk.ProfitTransition != nil {
				t.Fatal("u同値0で利益移行", side, slip, p)
			}
			o.Index++
			o.Time++
			o.Received = o.Time
			o.Bid += float64(side) * .01
			o.Ask += float64(side) * .01
			o.Last = (o.Bid + o.Ask) / 2
			q = quoteActual(o, 21)
			if err = b.markPositions(o, q, PhaseAfterSource, false); err != nil {
				t.Fatal(err)
			}
			p = b.result.Positions[0]
			if !p.ProtectionActive || p.InitialRisk.ProfitTransition == nil || p.Activation == nil || p.Activation.UnitNet <= 0 {
				t.Fatal("strict正益移行", side, slip, p)
			}
			before, _ := json.Marshal(p.InitialRisk)
			o.Index++
			o.Time++
			o.Received = o.Time
			o.Bid -= float64(side) * .1
			o.Ask -= float64(side) * .1
			o.Last = (o.Bid + o.Ask) / 2
			q = quoteActual(o, 22)
			if err = b.markPositions(o, q, PhaseAfterSource, false); err != nil {
				t.Fatal(err)
			}
			after, _ := json.Marshal(b.result.Positions[0].InitialRisk)
			if !bytes.Equal(before, after) || b.result.Positions[0].InitialRisk.FirstHit != nil {
				t.Fatal("利益後にrisk観測へ戻る")
			}
		}
	}
}
