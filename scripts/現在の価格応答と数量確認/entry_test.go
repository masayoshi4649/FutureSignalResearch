// 84派生元: work/84入口試作/entry_test.go
// 84派生元SHA256: fbe9f20679f85f596d5dee430573e589ba2cae261e209b3b953bc1bf79c6cebf

package far84

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

type input struct {
	at       float64
	q        far82.Quote
	chart    far82.ChartView
	evidence far82.CurrentEvidence
}

// TestSchemaFingerprint は旧公開型の再帰指紋を記録します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。固定した指紋との照合はRefineが行います。
func TestSchemaFingerprint(t *testing.T) {
	if got := OldSchemaSHA256(); got != acceptedSchemaSHA256 {
		t.Fatalf("旧保存型が変わりました:%s", got)
	}
}

// fixture は未知の短秒/OFIでもチャート順行とfresh帯が成立する当時入力を作ります。
//
// 引数: ありません。
// 返り値: inputは市場や損益を使わない買い方向の人工入力です。
func fixture() input {
	x := input{at: 1000, q: far82.Quote{Time: 999, Index: 50, Line: 42, Last: 1005, Bid: 1000, Ask: 1010, Valid: true}}
	x.chart = far82.ChartView{Technical: far82.TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true, EMA8_3: 1000, EMA21_3: 990, EMA8_15: 1000, EMA21_15: 990, RSI3: 55, PreviousRSI3: 54, Histogram3: 1, PreviousHistogram3: .9, Close3: 1005, TR3: 5, ATR3: 30, PreviousATR3: 30, Bar3End: 990, Bar15End: 990}, PreviousClose3: 995, PreviousEMA8_3: 1000, PreviousBar3End: 810, Previous3Known: true}
	c := far81.CurrentEvidence{Reference: "NK225", Time: 999, Received: 999, SourceIndex: 40, SourceLine: 42, Last: 1005, Bid: 1000, Ask: 1010}
	c.Buy.Windows = map[string]far81.CurrentSupportWindow{"人工": {Known: true, Value: 1}}
	c.Night = far81.CurrentStructure{Available: true, Known: true, Window: "E08", Time: 999, Index: 40, PriceEvent: 100, Band: far81.CurrentBandWindow{Known: true, QuantityKnown: true, StartIndex: 30, Index: 40, StartTime: 980, Time: 999, Elapsed: 19, Events: 8, QuantityEvents: 8}}
	c.Night.Buy = far81.CurrentPriceBand{Active: true, QuantitySupport: true, ID: 4, Side: 1, Bid: 995, Ask: 1005, Time: 998, Index: 39, Event: 99, Support: far81.CurrentBarrier{Known: true, Price: 995, Time: 997, Index: 38, Event: 98}, Barrier: far81.CurrentBarrier{Known: true, Price: 980, Time: 995, Index: 37, Event: 97}}
	x.evidence = far82.CurrentEvidence{CurrentEvidence: c}
	return x
}

// mirror は価格を反射して買売を入れ替え、実方向の同じ人工を作ります。
//
// 引数: x(input)は買いの当時入力です。
// 返り値: inputは独立した売りの当時入力です。
func mirror(x input) input {
	const pivot = 2000.0
	x.q.Last, x.q.Bid, x.q.Ask = pivot-x.q.Last, pivot-x.q.Ask, pivot-x.q.Bid
	v := &x.chart.Technical
	v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = pivot-v.EMA8_3, pivot-v.EMA21_3, pivot-v.EMA8_15, pivot-v.EMA21_15
	v.Close3 = pivot - v.Close3
	v.RSI3, v.PreviousRSI3 = 100-v.RSI3, 100-v.PreviousRSI3
	v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
	x.chart.PreviousClose3, x.chart.PreviousEMA8_3 = pivot-x.chart.PreviousClose3, pivot-x.chart.PreviousEMA8_3
	c := &x.evidence
	c.Last, c.Bid, c.Ask = pivot-c.Last, pivot-c.Ask, pivot-c.Bid
	c.Buy, c.Sell = c.Sell, c.Buy
	for _, support := range []*far81.CurrentSupport{&c.Buy, &c.Sell} {
		support.Own5, support.Own15, support.Own120, support.Own300, support.Peer120, support.OFI30 = -support.Own5, -support.Own15, -support.Own120, -support.Own300, -support.Peer120, -support.OFI30
	}
	if c.Short.Mid > 0 {
		c.Short.Mid = pivot - c.Short.Mid
	}
	for _, window := range []*far82.CurrentShortWindow{&c.Short.Five, &c.Short.Fifteen} {
		window.Move, window.Speed = -window.Move, -window.Speed
	}
	n := &c.Night
	n.Buy, n.Sell = n.Sell, n.Buy
	n.ConfirmedSide, n.RetestSide = -n.ConfirmedSide, -n.RetestSide
	for _, hold := range []*far81.CurrentPriceBand{&n.Buy, &n.Sell} {
		hold.Side = -hold.Side
		hold.Bid, hold.Ask = pivot-hold.Ask, pivot-hold.Bid
		if hold.Support.Known {
			hold.Support.Price = pivot - hold.Support.Price
		}
		if hold.Barrier.Known {
			hold.Barrier.Price = pivot - hold.Barrier.Price
		}
	}
	return x
}

// oldDecision は固定82B1の純判定だけを呼び出します。
//
// 引数: x(input)は人工当時入力です。
// 返り値: far82.EntryDecisionは市場を読まない旧判定です。
func oldDecision(x input) far82.EntryDecision {
	return far82.Decide(x.at, x.q, x.chart, x.evidence, "B1")
}

// TestFreshStructureAndMirror は構造の境界と未知を買売鏡像で確かめます。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。旧方向包含と初動保存も確認します。
func TestFreshStructureAndMirror(t *testing.T) {
	cases := []struct {
		name             string
		mutate           func(*input)
		old, c0, c1, unk bool
	}{
		{"正常", func(*input) {}, true, true, true, false},
		{"数量だけ不成立", func(x *input) { x.evidence.Night.Buy.QuantitySupport = false }, true, true, false, false},
		{"帯60秒境界", func(x *input) { x.evidence.Night.Buy.Time = 940 }, true, true, true, false},
		{"帯60秒超", func(x *input) { x.evidence.Night.Buy.Time = 939.99 }, true, false, false, false},
		{"帯32更新境界", func(x *input) { x.evidence.Night.Buy.Event = 68 }, true, true, true, false},
		{"帯33更新", func(x *input) { x.evidence.Night.Buy.Event = 67 }, true, false, false, false},
		{"価格帯未維持", func(x *input) { x.evidence.Night.Buy.Bid, x.evidence.Night.Buy.Ask = 1005, 1015 }, true, false, false, false},
		{"反対圧力未解消", func(x *input) { x.evidence.Night.Buy.Barrier.Price = 1000 }, true, false, false, false},
		{"反対点10pt境界", func(x *input) { x.evidence.Night.Buy.Barrier.Price = 990 }, true, true, true, false},
		{"数量回復60秒境界", func(x *input) { x.evidence.Night.Buy.Support.Time = 940 }, true, true, true, false},
		{"数量回復古い", func(x *input) { x.evidence.Night.Buy.Support.Time = 939.99 }, true, true, false, false},
		{"構造未知", func(x *input) { x.evidence.Night.Known = false }, true, false, false, true},
		{"未来帯", func(x *input) { x.evidence.Night.Buy.Time = 1001 }, true, false, false, true},
		{"未来数量点", func(x *input) { x.evidence.Night.Buy.Support.Time = 1001 }, true, false, false, true},
		{"非有限構造", func(x *input) { x.evidence.Night.Buy.Time = math.NaN() }, true, false, false, true},
		{"非有限チャート", func(x *input) { x.chart.Technical.Close3 = math.NaN() }, false, false, false, true},
		{"初動", func(x *input) { x.chart.Technical.EMA8_15, x.chart.Technical.EMA21_15 = 980, 1000 }, true, true, true, false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			x := fixture()
			test.mutate(&x)
			for _, pair := range []struct {
				x    input
				side int
			}{{x, 1}, {mirror(x), -1}} {
				old := oldDecision(pair.x)
				if old.Allowed != test.old {
					t.Fatalf("旧判定の前提差:%+v", old)
				}
				for _, policy := range []string{"C0", "C1"} {
					got, err := Decide(pair.x.at, pair.x.q, pair.x.chart, pair.x.evidence, policy)
					if err != nil {
						t.Fatal(err)
					}
					want := test.c0
					if policy == "C1" {
						want = test.c1
					}
					if got.Allowed != want || got.RequiredUnknown != test.unk || (want && got.Side != pair.side) {
						t.Fatalf("%s 採否/未知/方向差:%+v", policy, got)
					}
					for i, direction := range got.Directions {
						if direction.Allowed && !old.Directions[i].Allowed {
							t.Fatal("旧不許可の方向を復活させました")
						}
					}
					if test.name == "初動" && got.Role != "転換初動" {
						t.Fatal("初動を失いました")
					}
				}
			}
		})
	}
}

// TestConditionalSchema は失速時だけ現れる旧追加支持チェックを確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。optionalの欠落/余剰も拒否します。
func TestConditionalSchema(t *testing.T) {
	x := fixture()
	x.evidence.Short = far82.CurrentShort{Time: 999, Mid: 1005, Five: far82.CurrentShortWindow{Known: true, Move: .5, Speed: .1, Elapsed: 5, Endpoint: 994}, Fifteen: far82.CurrentShortWindow{Known: true, Move: 6, Speed: .4, Elapsed: 15, Endpoint: 984}}
	base := oldDecision(x)
	if len(base.Directions[0].Checks) != 21 {
		t.Fatal("失速時のschemaが違います")
	}
	for _, policy := range []string{"C0", "C1"} {
		got, err := Refine(base, policy)
		if err != nil || !got.Allowed {
			t.Fatalf("有効失速確認を失いました:%v", err)
		}
	}
	base.Directions[0].Checks = append(base.Directions[0].Checks[:14], base.Directions[0].Checks[15:]...)
	if _, err := Refine(base, "C0"); err == nil {
		t.Fatal("失速時追加支持の欠落を受理しました")
	}
}

// TestSchemaAndLogicalDamage は欠落・重複・順序・真偽の保存破損を拒否します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。各破損は独立した旧判定に加えます。
func TestSchemaAndLogicalDamage(t *testing.T) {
	cases := []struct {
		name string
		edit func(*far82.EntryDecision)
	}{
		{"欠落", func(d *far82.EntryDecision) { d.Directions[0].Checks = d.Directions[0].Checks[:19] }},
		{"余剰", func(d *far82.EntryDecision) {
			d.Directions[0].Checks = append(d.Directions[0].Checks, d.Directions[0].Checks[0])
		}},
		{"重複", func(d *far82.EntryDecision) { d.Directions[0].Checks[18] = d.Directions[0].Checks[17] }},
		{"順序", func(d *far82.EntryDecision) {
			d.Directions[0].Checks[17], d.Directions[0].Checks[18] = d.Directions[0].Checks[18], d.Directions[0].Checks[17]
		}},
		{"group変更", func(d *far82.EntryDecision) { d.Directions[0].Checks[17].Group = "別枝" }},
		{"未知成立", func(d *far82.EntryDecision) { d.Directions[0].Checks[17].Known = false }},
		{"補助結合破損", func(d *far82.EntryDecision) { d.Directions[0].Auxiliary.StructureSupport = false }},
		{"方向採否破損", func(d *far82.EntryDecision) { d.Directions[0].Allowed = false }},
		{"最終方向破損", func(d *far82.EntryDecision) { d.Side = -1 }},
		{"方向順序", func(d *far82.EntryDecision) { d.Directions[0], d.Directions[1] = d.Directions[1], d.Directions[0] }},
		{"旧政策違い", func(d *far82.EntryDecision) { d.Policy = "B0" }},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			base := oldDecision(fixture())
			test.edit(&base)
			if _, err := Refine(base, "C0"); err == nil {
				t.Fatal("保存破損を受理しました")
			}
		})
	}
	if _, err := Refine(oldDecision(fixture()), "未知"); err == nil {
		t.Fatal("未知政策を受理しました")
	}
}

// TestInputUnchanged は実行時と返却値編集時に元判定が変わらないことを確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。slice/map/ポインターの分離を実際に編集して確認します。
func TestInputUnchanged(t *testing.T) {
	x := fixture()
	x.evidence.Buy.OFIKnown, x.evidence.Buy.OFI30, x.evidence.Buy.OwnAt = true, 1, 999
	base := oldDecision(x)
	before, _ := json.Marshal(base)
	got, err := Refine(base, "C1")
	if err != nil {
		t.Fatal(err)
	}
	got.Base.Directions[0].Checks[0].Reason = "返却編集"
	got.Base.Evidence.Buy.Windows["人工"] = far81.CurrentSupportWindow{Value: 999}
	*got.Base.Directions[0].PlacementATR = 999
	*got.Base.Directions[0].Auxiliary.OFI.Value = 999
	got.Directions[0].Added[0].Passed = false
	after, _ := json.Marshal(base)
	if !reflect.DeepEqual(before, after) {
		t.Fatal("元の公開判定を変更しました")
	}
	if x.evidence.Buy.Windows["人工"].Value != 1 {
		t.Fatal("元の当時入力を変更しました")
	}
}

// TestOriginalConflictIsNotResolvedByFiltering は旧競合から片側を新規へ復活させません。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。構造チェックが片側だけ残る人工競合を使います。
func TestOriginalConflictIsNotResolvedByFiltering(t *testing.T) {
	base := oldDecision(fixture())
	sell := oldDecision(mirror(fixture())).Directions[1]
	sell.Checks[17].Passed, sell.Auxiliary.StructureSupport = false, false
	base.Directions[1] = sell
	base.Allowed, base.Side, base.Role, base.Reason, base.RequiredUnknown = false, 0, "競合待機", "両方向の現在根拠が競合", false
	got, err := Refine(base, "C0")
	if err != nil {
		t.Fatal(err)
	}
	if !got.Directions[0].Allowed || got.Directions[1].Allowed || got.Allowed || got.Side != 0 || got.Role != "競合待機" {
		t.Fatalf("旧競合を新規へ変えました:%+v", got)
	}
}
