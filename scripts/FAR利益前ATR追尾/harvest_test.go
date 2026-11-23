// 由来97停止金融: scripts/FAR初回利益確定/harvest_test.go
// 由来SHA256: 30fe724c57b396512951050e9008529c3597333baeb9835b50ad21b957027c0a
package minirisk98

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	prior96 "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// TestHarvest97EmptyFull96 は空Harvestを旧96の全金融JSONへ除外0で比較します。
//
// 引数: t(*testing.T)は人工の試験器です。
// 返り値: ありません。N/B5/B5Q、Gate空/AB、鏡像、C0/C5、D0/D1を含みます。
func TestHarvest97EmptyFull96(t *testing.T) {
	for _, side := range []int{-1, 1} {
		fixture := captureWave95(t, side)
		for _, timing := range []string{"N", "B5", "B5Q"} {
			gates := []string{""}
			if timing == "B5Q" {
				gates = append(gates, "AB")
			}
			for _, gate := range gates {
				for _, slip := range []float64{0, 5} {
					for _, delay := range []int{0, 1} {
						cfg := ActorConfig{Policy: "P0", EntryTiming: timing, GatePolicy: gate, SlipPts: slip, DelaySeconds: delay, USOpen: fixture.Session.USOpen}
						b, err := NewActualBook(fixture.Session, cfg)
						if err != nil {
							t.Fatal(err)
						}
						old, err := prior96.NewActualBook(fixture.Session, prior96.ActorConfig{Policy: cfg.Policy, EntryTiming: timing, GatePolicy: gate, SlipPts: slip, DelaySeconds: delay, USOpen: cfg.USOpen})
						if err != nil {
							t.Fatal(err)
						}
						compare := func() {
							x, _ := json.Marshal(b.Snapshot())
							y, _ := json.Marshal(old.Snapshot())
							if !bytes.Equal(x, y) {
								t.Fatalf("空Harvestの旧96全文差 side=%d %s", side, b.result.Key)
							}
							if bytes.Contains(x, []byte("harvest_policy")) {
								t.Fatal("空設定がJSONへ出現")
							}
						}
						compare()
						for _, e := range fixture.Events {
							if e.Kind == "grid" {
								var callback EntryGate
								var oldCallback prior96.EntryGate
								if gate != "" {
									callback = func(c EntryCandidate) (GateDecision, error) {
										return GateDecision{Policy: gate, SnapshotID: "人工共通", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
									}
									oldCallback = func(c prior96.EntryCandidate) (prior96.GateDecision, error) {
										return prior96.GateDecision{Policy: gate, SnapshotID: "人工共通", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
									}
								}
								err = b.OnEntryGridWithGate(fixture.Grids[e.Index], callback)
								if err == nil {
									err = old.OnEntryGridWithGate(fixture.Grids[e.Index], oldCallback)
								}
							} else {
								step := fixture.Steps[e.Index]
								batches := make([]prior96.NativeBatch, len(step.Batches))
								for i, batch := range step.Batches {
									batches[i] = prior96.NativeBatch{Method: batch.Method, Delta: batch.Delta}
								}
								err = b.OnNativeStep(step.Observation, step.SourceLine, step.Batches)
								if err == nil {
									err = old.OnNativeStep(step.Observation, step.SourceLine, batches)
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
						if _, err = old.Finish(); err != nil {
							t.Fatal(err)
						}
						compare()
					}
				}
			}
		}
	}
}

type fixtureHarvest97 struct {
	Session Session                 `json:"session"`
	Scope   string                  `json:"scope"`
	Steps   []fixtureStep94         `json:"steps"`
	Timers  []fixtureTimer94        `json:"timers"`
	Grids   []float64               `json:"grids"`
	Events  []fixtureEvent95        `json:"events"`
	Actors  map[string]ActualResult `json:"actors"`
}

// harvestWave97 は同じ手製Sourceを16口座へ配送するAPI人工です。
//
// 引数: t(*testing.T)、side(int)、mode(string)は試験器・鏡像・境界系列です。
// 返り値: fixtureHarvest97は金融結果と全公開入力。FAR自然生成の証拠ではありません。
func harvestWave97(t *testing.T, side int, mode string) fixtureHarvest97 {
	t.Helper()
	s := session94()
	grid := s.Start + 1800
	out := fixtureHarvest97{Session: s, Scope: "手製Source/公開ATRによるAPI人工。原板・FAR自然生成・市場損益ではない。", Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}, Grids: []float64{}, Events: []fixtureEvent95{}, Actors: map[string]ActualResult{}}
	actors := map[string]*ActualBook{}
	for _, gate := range []string{"", "AB"} {
		for _, harvest := range []string{"", "H0"} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: gate, HarvestPolicy: harvest, SlipPts: slip, DelaySeconds: delay})
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
	feed := func(at, move float64, signals ...native.Signal) {
		o := observation95(s, side, index, at, move, 20)
		if mode == "ATR未知" {
			o.ATR, o.E01.ATR, o.E01.ATRAvailable, o.E01.ATRNominal = 0, 0, 0, 0
		}
		batch := src.step(t, o, index+20, signals, nil)
		before, _ := json.Marshal(batch)
		for _, b := range actors {
			if err := b.OnNativeStep(o, index+20, []NativeBatch{batch}); err != nil {
				t.Fatal(b.result.Key, at-grid, err)
			}
			if b.available(1) < 0 || b.available(-1) < 0 {
				t.Fatal("片側上限超過")
			}
		}
		after, _ := json.Marshal(batch)
		if !bytes.Equal(before, after) {
			t.Fatal("Source入力変更")
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "quote", Index: len(out.Steps)})
		out.Steps = append(out.Steps, fixtureStep94{Observation: o, SourceLine: index + 20, Batches: []NativeBatch{batch}})
		index++
	}
	quantity := 5
	if mode == "両側上限" {
		quantity = 10
	}
	news := []native.Signal{birth94("H出生", side, quantity)}
	if mode == "両側上限" {
		news = append(news, birth94("反対出生", -side, quantity))
	}
	feed(grid-1, 0, news...)
	feed(grid-.9, 0)
	for _, b := range actors {
		var gate EntryGate
		if b.result.Config.GatePolicy != "" {
			gate = func(c EntryCandidate) (GateDecision, error) {
				return GateDecision{Policy: "AB", SnapshotID: "人工枠", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
			}
		}
		if err := b.OnEntryGridWithGate(grid, gate); err != nil {
			t.Fatal(err)
		}
	}
	out.Events = append(out.Events, fixtureEvent95{Kind: "grid", Index: 0})
	out.Grids = append(out.Grids, grid)
	feed(grid, 0)
	feed(grid+1, 0)
	switch mode {
	case "部分予約先行":
		feed(grid+1, 0, close94("先行部分", "H出生", side, 2))
		feed(grid+2, 30)
		feed(grid+3, 30)
		feed(grid+4, 30, close94("源全残", "H出生", side, 3))
		feed(grid+5, 30)
	case "全予約先行":
		feed(grid+1, 0, close94("先行全残", "H出生", side, 5))
		feed(grid+2, 30)
		feed(grid+3, 30)
	case "同原行Source部分":
		feed(grid+2, 30, close94("同原行部分", "H出生", side, 2))
		feed(grid+3, 30)
		feed(grid+4, 30, close94("源全残", "H出生", side, 3))
		feed(grid+5, 30)
	case "同原行Source全量":
		feed(grid+2, 30, close94("同原行全残", "H出生", side, 5))
		feed(grid+3, 30)
	case "残玉uだけ正益":
		feed(grid+1.5, -30, close94("源損失部分", "H出生", side, 4))
		feed(grid+2, -30)
		feed(grid+2.5, -30)
		feed(grid+3, 30)
		feed(grid+4, 30)
		feed(grid+5, 30, close94("源全残", "H出生", side, 1))
		feed(grid+6, 30)
	case "次気配悪化":
		feed(grid+2, 30)
		feed(grid+2, -10)
		feed(grid+3, -10)
		feed(grid+4, -10, close94("源全残", "H出生", side, 5))
		feed(grid+5, -10)
	case "両側上限":
		feed(grid+2, 30)
		for _, b := range actors {
			if b.available(side) != 0 || b.available(-side) != 0 {
				t.Fatal("予約だけで上限が解放された")
			}
		}
		feed(grid+3, 30)
		feed(grid+4, 30, close94("源全残", "H出生", side, 10), close94("反対源全残", "反対出生", -side, 10))
		feed(grid+5, 30)
	default:
		feed(grid+2, 20)
		for _, b := range actors {
			if b.result.Config.HarvestPolicy == "H0" {
				p := b.result.Positions[0]
				if (p.Activation != nil) != (b.result.Config.SlipPts == 0) {
					t.Fatal("滑りを含む初回strict起動", b.result.Key, p.Activation)
				}
			}
		}
		feed(grid+3, 30)
		feed(grid+3, 30)
		feed(grid+4, 30)
		feed(grid+5, 30, close94("源全残", "H出生", side, 5))
		feed(grid+6, 30)
	}
	for key, b := range actors {
		r, err := b.Finish()
		if err != nil {
			t.Fatal(key, err)
		}
		if !r.Complete || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 {
			t.Fatal("最終所有/予約", key, r.Totals)
		}
		out.Actors[key] = r
	}
	return out
}

// TestHarvest97MirrorCostsDelays は費用閾値・同原行禁止・後続時刻と手計算純額を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestHarvest97MirrorCostsDelays(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"通常", "ATR未知"} {
			fixture := harvestWave97(t, side, mode)
			for key, r := range fixture.Actors {
				if r.Config.HarvestPolicy != "H0" {
					continue
				}
				p := r.Positions[0]
				want, timeAt, gain := 9615.0, fixture.Session.Start+1802, 10.0
				if r.Config.SlipPts == 5 {
					want, timeAt, gain = 4615, fixture.Session.Start+1803, 20
				}
				if r.Totals.NetYen != want || p.Activation == nil || p.Activation.Quote.Time != timeAt || p.Activation.GainPoints != gain || p.FloorGain == nil || *p.FloorGain < gain || p.FirstFloorHit == nil {
					t.Fatal("初回正益床/手計算", key, r.Totals, p)
				}
				if mode == "ATR未知" && p.ATR != nil {
					t.Fatal("未知ATRを補完")
				}
				found := 0
				for _, o := range r.Orders {
					if o.Reason != HarvestFirstPositiveReason {
						continue
					}
					found++
					if o.Quantity != 5 || o.ProtectionPoint == nil || o.ProtectionPoint.Phase != PhaseAfterSource || o.RequestTime != timeAt || o.Status != "filled" {
						t.Fatal("全量確定要求", key, o)
					}
					for _, f := range r.Fills {
						if f.OrderID == o.ID {
							if f.Quote.Index <= o.RequestQuote.Index || f.Quote.Time < o.RequestTime+float64(r.Config.DelaySeconds) {
								t.Fatal("同原行/遅延違反", key, f)
							}
						}
					}
				}
				if found != 1 || r.Metrics.ProtectionExitRequests != 1 {
					t.Fatal("H0要求回数", key, found)
				}
			}
		}
	}
}

// TestHarvest97SourcePriority は先行予約・同原行Source・残0旗と二重返済を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestHarvest97SourcePriority(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"部分予約先行", "全予約先行", "同原行Source部分", "同原行Source全量", "残玉uだけ正益"} {
			fixture := harvestWave97(t, side, mode)
			for key, r := range fixture.Actors {
				if r.Config.HarvestPolicy != "H0" {
					continue
				}
				p := r.Positions[0]
				if p.Activation == nil || p.FirstFloorHit == nil || p.ClosedQuantity != 5 {
					t.Fatal("起動/床/終了", key, p)
				}
				want := 3
				if mode == "全予約先行" || mode == "同原行Source全量" {
					want = 0
				}
				if mode == "残玉uだけ正益" {
					want = 1
					if p.Activation.WholeNet >= 0 || p.Activation.UnitNet <= 0 {
						t.Fatal("uとWの分離", key, p.Activation)
					}
				}
				total, source := 0, 0
				for _, o := range r.Orders {
					if o.Kind != "exit" {
						continue
					}
					if o.Reason == HarvestFirstPositiveReason {
						total += o.Quantity
						if o.ProtectionPoint.Phase != PhaseAfterSource {
							t.Fatal("preで要求")
						}
					} else {
						source += o.Quantity
					}
				}
				if total != want || total+source != 5 {
					t.Fatal("Source予約との重複", key, total, source)
				}
				if mode == "全予約先行" && (p.Marks.FirstUnitPositive == nil || p.Marks.FirstUnitPositive.Phase != PhasePreFill || p.Marks.FirstUnitPositive.Reserved != 5) {
					t.Fatal("全fill前の正益旗", key, p.Marks)
				}
			}
		}
	}
}

// TestHarvest97AdverseAndCap は正益要求後の実赤字と予約込み両側10を残します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestHarvest97AdverseAndCap(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for key, r := range harvestWave97(t, side, "次気配悪化").Actors {
			if r.Config.HarvestPolicy != "H0" {
				continue
			}
			want := -10385.0
			if r.Config.SlipPts == 5 {
				want = -15385
			}
			if r.Totals.NetYen != want || r.Positions[0].Marks.FirstUnitPositive == nil {
				t.Fatal("次気配悪化の実額", key, r.Totals)
			}
		}
		for key, r := range harvestWave97(t, side, "両側上限").Actors {
			if r.Totals.EntryQuantity != 20 {
				t.Fatal("両側最大20", key, r.Totals)
			}
		}
	}
}

// TestHarvest97UnitOnlyPredicate はWだけ正益又はu同値0の単元状態で未起動を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。公開Source生成ではない状態単元反証です。
func TestHarvest97UnitOnlyPredicate(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, slip := range []float64{0, 5} {
			b, err := NewActualBook(session94(), ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", SlipPts: slip})
			if err != nil {
				t.Fatal(err)
			}
			o := observation94(session94(), 1, 0, 0, 0, 0)
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
			b.result.Positions = append(b.result.Positions, ActualPosition{ID: "単元状態", Side: side, InitialQuantity: 1, Quantity: 1, EntryPrice: entry, RealizedNet: 1000})
			if err = b.markPositions(o, quoteActual(o, 1), PhaseAfterSource, true); err != nil {
				t.Fatal(err)
			}
			p := b.result.Positions[0]
			if p.Marks.Last.UnitNet != 0 || p.Marks.Last.WholeNet <= 0 || p.ProtectionActive || p.Activation != nil || len(b.result.Orders) != 0 {
				t.Fatal("W又はu=0で起動", side, slip, p)
			}
		}
	}
}

// TestHarvest97Config はH0専用の許可範囲を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestHarvest97Config(t *testing.T) {
	for _, c := range []ActorConfig{{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H1"}, {Policy: "P0", EntryTiming: "N", HarvestPolicy: "H0"}, {Policy: "P0", EntryTiming: "B5", HarvestPolicy: "H0"}, {Policy: "P1", EntryTiming: "B5Q", HarvestPolicy: "H0"}, {Policy: "P0", EntryTiming: "B5Q", GatePolicy: "A", HarvestPolicy: "H0"}, {Policy: "P0", EntryTiming: "B5Q", GatePolicy: "B", HarvestPolicy: "H0"}} {
		if _, err := NewActualBook(session94(), c); err == nil {
			t.Fatal("H0の未定義組を受理", c)
		}
	}
}

// TestExportHarvest97 は明示環境時だけ実型marshalの小型人工を新規保存します。
//
// 引数: t(*testing.T)は試験器、環境MINIHARVEST_EXPORT_DIRは新規保存先です。
// 返り値: ありません。市場価格やFAR自然生成を含めません。
func TestExportHarvest97(t *testing.T) {
	dir := os.Getenv("MINIHARVEST_EXPORT_DIR")
	if dir == "" {
		t.Skip("人工exportは明示指定時だけ")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("人工出力先は未作成だけ")
	}
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	for _, s := range []struct {
		side int
		mode string
	}{{1, "通常"}, {-1, "通常"}, {1, "同原行Source部分"}, {-1, "次気配悪化"}} {
		v := harvestWave97(t, s.side, s.mode)
		data, err := json.MarshalIndent(v, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(dir, fmt.Sprintf("%d_%s.json", s.side, s.mode))
		if err = os.WriteFile(path, append(data, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
}
