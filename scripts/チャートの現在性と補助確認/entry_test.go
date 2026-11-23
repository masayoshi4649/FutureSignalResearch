package far82

import (
	"encoding/json"
	"math"
	"reflect"
	"strings"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// entry82Fixture は補助が全て未知でも成立するチャート順行を作ります。
//
// 引数: ありません。
// 返り値: at(float64)、q(Quote)、chart(ChartView)、c(CurrentEvidence)は人工当時入力です。
func entry82Fixture() (float64, Quote, ChartView, CurrentEvidence) {
	at := 1000.0
	q := Quote{Time: 999, Index: 50, Line: 42, Last: 1005, Bid: 1000, Ask: 1010, Valid: true}
	v := TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true, EMA8_3: 1000, EMA21_3: 990, EMA8_15: 1000, EMA21_15: 990, RSI3: 55, PreviousRSI3: 54, Histogram3: 1, PreviousHistogram3: .9, Close3: 1005, TR3: 5, ATR3: 30, PreviousATR3: 30, Bar3End: 990, Bar15End: 990}
	chart := ChartView{Technical: v, PreviousClose3: 995, PreviousEMA8_3: 1000, PreviousBar3End: 810, Previous3Known: true}
	c := CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: 999, Received: 999, SourceIndex: 40, SourceLine: 42, Last: q.Last, Bid: q.Bid, Ask: q.Ask}}
	c.Buy.OFIReason, c.Sell.OFIReason = "未観測", "未観測"
	c.Short.Five.Reason, c.Short.Fifteen.Reason = "未観測", "未観測"
	return at, q, chart, c
}

// entry82Band は81と同じ現在構造の人工帯を付加します。
//
// 引数: c(CurrentEvidence)は買いの当時入力です。
// 返り値: CurrentEvidenceは新鮮な同方向帯・量支持・反対圧力解消を持ちます。
func entry82Band(c CurrentEvidence) CurrentEvidence {
	c.Night = far81.CurrentStructure{Available: true, Known: true, Window: "E08", Time: c.Time, Index: c.SourceIndex, PriceEvent: 100, Band: far81.CurrentBandWindow{Known: true, QuantityKnown: true, StartIndex: 30, Index: c.SourceIndex, StartTime: c.Time - 19, Time: c.Time, Elapsed: 19, Events: 8, QuantityEvents: 8}}
	c.Night.Buy = far81.CurrentPriceBand{Active: true, QuantitySupport: true, ID: 4, Side: 1, Bid: 995, Ask: 1005, Time: c.Time - 1, Index: c.SourceIndex - 1, Event: 99, Support: far81.CurrentBarrier{Known: true, Price: 995, Time: c.Time - 2, Index: c.SourceIndex - 2, Event: 98}, Barrier: far81.CurrentBarrier{Known: true, Price: 980, Time: c.Time - 4, Index: c.SourceIndex - 3, Event: 97}}
	return c
}

// entry82Speeds は実際のMove/Elapsedと整合する5/15秒速度を作ります。
//
// 引数: c(CurrentEvidence)、five/fifteen(float64)は人工のpt/秒です。
// 返り値: CurrentEvidenceは元APIと同じ単位と時計の既知窓です。
func entry82Speeds(c CurrentEvidence, five, fifteen float64) CurrentEvidence {
	c.Short = CurrentShort{Time: c.Time, Mid: c.Bid + (c.Ask-c.Bid)/2,
		Five:    CurrentShortWindow{Known: true, Move: five * 5, Speed: five, Elapsed: 5, Endpoint: c.Time - 5, Reason: "既知"},
		Fifteen: CurrentShortWindow{Known: true, Move: fifteen * 15, Speed: fifteen, Elapsed: 15, Endpoint: c.Time - 15, Reason: "既知"}}
	return c
}

// mirrorEntry82 は全価格を反射し、買売の符号だけを反転します。
//
// 引数: q(Quote)、chart(ChartView)、c(CurrentEvidence)は買いの人工入力です。
// 返り値: Quote/ChartView/CurrentEvidenceは売りへ反射した独立値です。
func mirrorEntry82(q Quote, chart ChartView, c CurrentEvidence) (Quote, ChartView, CurrentEvidence) {
	const pivot = 2000.0
	q.Last, q.Bid, q.Ask = pivot-q.Last, pivot-q.Ask, pivot-q.Bid
	v := &chart.Technical
	v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = pivot-v.EMA8_3, pivot-v.EMA21_3, pivot-v.EMA8_15, pivot-v.EMA21_15
	v.Close3 = pivot - v.Close3
	v.RSI3, v.PreviousRSI3 = 100-v.RSI3, 100-v.PreviousRSI3
	v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
	chart.PreviousClose3, chart.PreviousEMA8_3 = pivot-chart.PreviousClose3, pivot-chart.PreviousEMA8_3
	c = cloneCurrent(c)
	c.Last, c.Bid, c.Ask = pivot-c.Last, pivot-c.Ask, pivot-c.Bid
	c.Buy, c.Sell = c.Sell, c.Buy
	for _, support := range []*far81.CurrentSupport{&c.Buy, &c.Sell} {
		support.Own5, support.Own15, support.Own120, support.Own300, support.Peer120, support.OFI30 = -support.Own5, -support.Own15, -support.Own120, -support.Own300, -support.Peer120, -support.OFI30
	}
	if c.Short.Mid > 0 {
		c.Short.Mid = pivot - c.Short.Mid
	}
	for _, window := range []*CurrentShortWindow{&c.Short.Five, &c.Short.Fifteen} {
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
	return q, chart, c
}

// checkEntry82Mirror は両政策の採否・役割・位置が売買対称かを確認します。
//
// 引数: t(*testing.T)、at(float64)、q(Quote)、chart(ChartView)、c(CurrentEvidence)です。
// 返り値: ありません。補助状態も実方向の同じ数値であることを確かめます。
func checkEntry82Mirror(t *testing.T, at float64, q Quote, chart ChartView, c CurrentEvidence) {
	t.Helper()
	mq, mv, mc := mirrorEntry82(q, chart, c)
	for _, policy := range []string{"B0", "B1"} {
		a, b := Decide(at, q, chart, c, policy), Decide(at, mq, mv, mc, policy)
		if a.Allowed != b.Allowed || a.Role != b.Role || a.Side != -b.Side || a.RequiredUnknown != b.RequiredUnknown || !reflect.DeepEqual(a.Directions[0].Auxiliary, b.Directions[1].Auxiliary) || a.Directions[0].PlacementPoints != b.Directions[1].PlacementPoints {
			t.Fatalf("売買非対称 %s 買=%+v 売=%+v", policy, a, b)
		}
	}
}

// TestEntry82CoreTrendAndInitial は未知補助でも順行を通し、初動は実際の回復で分けます。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。元参照保有・M/T・相手全既知に依存しないことを確認します。
func TestEntry82CoreTrendAndInitial(t *testing.T) {
	at, q, chart, c := entry82Fixture()
	for _, policy := range []string{"B0", "B1"} {
		d := Decide(at, q, chart, c, policy)
		if !d.Allowed || d.Side != 1 || d.Role != "順行" || d.RequiredUnknown || d.Directions[0].Auxiliary.Five.Known || d.Directions[0].Auxiliary.OFI.State != "未知" {
			t.Fatalf("未知補助を必須化:%+v", d)
		}
		if _, err := json.Marshal(d); err != nil {
			t.Fatal(err)
		}
	}
	checkEntry82Mirror(t, at, q, chart, c)
	// ----------------------------------------
	// 上位未準備とRSI50未交差でも、同足の平均回復と現在帯があれば初動です。
	chart.Technical.TrendKnown = false
	chart.Technical.RSI3, chart.Technical.PreviousRSI3 = 47, 45
	c = entry82Band(c)
	for _, policy := range []string{"B0", "B1"} {
		d := Decide(at, q, chart, c, policy)
		if !d.Allowed || d.Role != "転換初動" || d.RequiredUnknown {
			t.Fatalf("実際の早期回復を失った:%+v", d)
		}
	}
	checkEntry82Mirror(t, at, q, chart, c)
	chart.PreviousClose3 = 1005
	for _, policy := range []string{"B0", "B1"} {
		if Decide(at, q, chart, c, policy).Allowed {
			t.Fatal("直前足で既に平均の方向側なのに初動回復とした")
		}
	}
	chart.PreviousEMA8_3 = 1010
	if !Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("直前EMAを現在EMAへ置換した")
	}
}

// TestEntry82RequiredInput は主軸・当時性・時計の不備を各々拒否します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。補助の未知許可を必須チャートの未知へ流用しません。
func TestEntry82RequiredInput(t *testing.T) {
	cases := []struct {
		name   string
		change func(*float64, *Quote, *ChartView, *CurrentEvidence)
	}{
		{"未来3分", func(a *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.Bar3End = *a + 1 }},
		{"古い3分", func(a *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) {
			v.Technical.Bar3End = *a - 180.01
			v.PreviousBar3End = v.Technical.Bar3End - 180
		}},
		{"前足未知", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Previous3Known = false }},
		{"前足非連続", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.PreviousBar3End-- }},
		{"前EMA非有限", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.PreviousEMA8_3 = math.NaN() }},
		{"進行未知", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.ExitKnown = false }},
		{"hist増分同値", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) {
			v.Technical.Histogram3 = v.Technical.PreviousHistogram3
		}},
		{"hist非有限", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.Histogram3 = math.Inf(1) }},
		{"終値平均同値", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.Close3 = v.Technical.EMA8_3 }},
		{"終値反対", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) {
			v.Technical.Close3 = v.Technical.EMA8_3 - 1
		}},
		{"ATR未知", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.ATRKnown = false }},
		{"ATR零", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.ATR3 = 0 }},
		{"遠い取得", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.ATR3 = 9.99 }},
		{"平均反対取得", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.EMA8_3 = 1010.01 }},
		{"スパイク未知", func(_ *float64, _ *Quote, v *ChartView, _ *CurrentEvidence) { v.Technical.SpikeKnown = false }},
		{"別市場", func(_ *float64, _ *Quote, _ *ChartView, c *CurrentEvidence) { c.Reference = "TOPIX" }},
		{"源原行不一致", func(_ *float64, _ *Quote, _ *ChartView, c *CurrentEvidence) { c.SourceLine++ }},
		{"源Index不正", func(_ *float64, _ *Quote, _ *ChartView, c *CurrentEvidence) { c.SourceIndex = -1 }},
		{"実Index不正", func(_ *float64, q *Quote, _ *ChartView, _ *CurrentEvidence) { q.Index = -1 }},
		{"未来受信", func(a *float64, _ *Quote, _ *ChartView, c *CurrentEvidence) { c.Received = *a + 1 }},
		{"古い自己", func(a *float64, q *Quote, _ *ChartView, c *CurrentEvidence) {
			q.Time = *a - 15.01
			c.Time, c.Received = q.Time, q.Time
		}},
		{"未来自己", func(a *float64, q *Quote, _ *ChartView, c *CurrentEvidence) {
			q.Time = *a + 1
			c.Time, c.Received = q.Time, q.Time
		}},
		{"交差気配", func(_ *float64, q *Quote, _ *ChartView, c *CurrentEvidence) { q.Ask = q.Bid; c.Ask = q.Ask }},
		{"元気配不一致", func(_ *float64, _ *Quote, _ *ChartView, c *CurrentEvidence) { c.Last++ }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			for _, policy := range []string{"B0", "B1"} {
				at, q, chart, c := entry82Fixture()
				tc.change(&at, &q, &chart, &c)
				if Decide(at, q, chart, c, policy).Allowed {
					t.Fatalf("%sを採用:%s", tc.name, policy)
				}
			}
		})
	}
	// ----------------------------------------
	// 15分時計の未知は順行に使わず、初動が別途成立した場合だけ許可します。
	for _, end := range []float64{1001, 99.99} {
		at, q, chart, c := entry82Fixture()
		chart.Technical.Bar15End = end
		if Decide(at, q, chart, c, "B0").Allowed {
			t.Fatal("未来又は900秒より古い15分足で順行を認めた")
		}
	}
	at, q, chart, c := entry82Fixture()
	q.Time, c.Time, c.Received = at-15, at-15, at-15
	chart.Technical.Bar3End, chart.PreviousBar3End, chart.Technical.Bar15End = at-180, at-360, at-900
	if !Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("自己15秒・3分180秒・15分900秒の等号を拒否")
	}
}

// TestEntry82AuxiliaryStates は補助の個別既知と反対だけの拒否を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。未知を観測0や反対にせず、M/Tを確率として使いません。
func TestEntry82AuxiliaryStates(t *testing.T) {
	at, q, chart, c := entry82Fixture()
	c.Buy.OwnKnown, c.Buy.PeerKnown, c.Buy.Known = false, false, false
	c.Buy.OFI30, c.Buy.M, c.Buy.T = -100, -100, -100
	for _, policy := range []string{"B0", "B1"} {
		if d := Decide(at, q, chart, c, policy); !d.Allowed || d.Directions[0].Auxiliary.OFI.Value != nil {
			t.Fatal("未知OFIの保管値又はM/Tを資格へ使った")
		}
	}
	// ----------------------------------------
	// 既知の0は中立、方向反対は窓単位で拒否します。
	c = entry82Speeds(c, 0, 0)
	c.Buy.OFIKnown, c.Buy.OwnAt, c.Buy.OFI30 = true, c.Time, 0
	for _, policy := range []string{"B0", "B1"} {
		d := Decide(at, q, chart, c, policy)
		if !d.Allowed || d.Directions[0].Auxiliary.Five.State != "中立" || d.Directions[0].Auxiliary.OFI.State != "中立" || d.Directions[0].Auxiliary.Slowdown {
			t.Fatal("既知0を未知又は失速へ入れた")
		}
	}
	for _, field := range []string{"5秒", "15秒", "OFI"} {
		other := entry82Speeds(c, 1, 1)
		switch field {
		case "5秒":
			other = entry82Speeds(other, -1, 1)
		case "15秒":
			other = entry82Speeds(other, 1, -1)
		case "OFI":
			other.Buy.OFI30 = -.01
		}
		for _, policy := range []string{"B0", "B1"} {
			if Decide(at, q, chart, other, policy).Allowed {
				t.Fatalf("既知反対%sを採用", field)
			}
		}
		checkEntry82Mirror(t, at, q, chart, other)
	}
}

// TestEntry82SlowdownConfirmation は0.5等号の時だけB1の追加支持を要求します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。未知失速の創作と、全枠への支持必須化を防ぎます。
func TestEntry82SlowdownConfirmation(t *testing.T) {
	at, q, chart, c := entry82Fixture()
	c = entry82Speeds(c, .5, 1)
	a, b := Decide(at, q, chart, c, "B0"), Decide(at, q, chart, c, "B1")
	if !a.Allowed || b.Allowed || !b.RequiredUnknown || !b.Directions[0].Auxiliary.Slowdown {
		t.Fatal("既知失速と支持未知の分岐が不正")
	}
	checkEntry82Mirror(t, at, q, chart, c)
	// ----------------------------------------
	// 個別に実測の正OFI又は帯量支持があれば追加支持が成立します。
	c.Buy.OFIKnown, c.Buy.OwnAt, c.Buy.OFI30 = true, c.Time, .01
	if !Decide(at, q, chart, c, "B1").Allowed {
		t.Fatal("自己・相手全未知を個別OFIへ混ぜた")
	}
	c.Buy.OFIKnown = false
	c = entry82Band(c)
	if !Decide(at, q, chart, c, "B1").Allowed {
		t.Fatal("新鮮な帯量支持を使えない")
	}
	checkEntry82Mirror(t, at, q, chart, c)
	c.Night.Buy.QuantitySupport = false
	c.Buy.OFIKnown, c.Buy.OwnAt, c.Buy.OFI30 = true, c.Time, 0
	b = Decide(at, q, chart, c, "B1")
	if b.Allowed || b.Directions[0].RequiredUnknown {
		t.Fatal("両確認が既知の不成立を未知とした")
	}
	for _, speeds := range [][2]float64{{.5000001, 1}, {1, 1}, {0, 0}} {
		other := entry82Speeds(c, speeds[0], speeds[1])
		if d := Decide(at, q, chart, other, "B1"); !d.Allowed || d.Directions[0].Auxiliary.Slowdown {
			t.Fatalf("非失速まで支持を必須化:%+v", speeds)
		}
	}
	c.Short.Five.Known = false
	if d := Decide(at, q, chart, c, "B1"); !d.Allowed || d.Directions[0].Auxiliary.SlowdownKnown || d.Directions[0].Auxiliary.Slowdown {
		t.Fatal("未知の短秒から失速を作った")
	}
}

// TestEntry82ShortMetadata は速度とbp幅の違い、未来・空白の無効化を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。壊れた補助を未知へ分け、チャート順行を自動棄却しません。
func TestEntry82ShortMetadata(t *testing.T) {
	cases := []struct {
		name   string
		change func(*CurrentEvidence)
	}{
		{"bp幅を速度へ代用", func(c *CurrentEvidence) { c.Short.Five.Speed *= 5 }},
		{"未来端点", func(c *CurrentEvidence) { c.Short.Five.Endpoint = c.Time + 1 }},
		{"窓時計不一致", func(c *CurrentEvidence) { c.Short.Time-- }},
		{"Mid不一致", func(c *CurrentEvidence) { c.Short.Mid++ }},
		{"経過秒不一致", func(c *CurrentEvidence) { c.Short.Five.Elapsed++ }},
		{"空白超過", func(c *CurrentEvidence) {
			c.Short.Five.Elapsed = 21
			c.Short.Five.Endpoint = c.Time - 21
			c.Short.Five.Delay = 16
			c.Short.Five.Move = 21
		}},
		{"非有限速度", func(c *CurrentEvidence) { c.Short.Five.Speed = math.NaN() }},
		{"OFI未来時計", func(c *CurrentEvidence) { c.Buy.OFIKnown = true; c.Buy.OwnAt = c.Time + 1; c.Buy.OFI30 = -1 }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			at, q, chart, c := entry82Fixture()
			c = entry82Speeds(c, 1, 1)
			tc.change(&c)
			d := Decide(at, q, chart, c, "B1")
			if !d.Allowed {
				t.Fatal("補助不整合を硬いチャート資格へした")
			}
			if tc.name == "OFI未来時計" {
				if d.Directions[0].Auxiliary.OFI.Known || d.Directions[0].Auxiliary.OFI.Value != nil {
					t.Fatal("OFI未来値を観測反対へした")
				}
			} else if d.Directions[0].Auxiliary.Five.Known || d.Directions[0].Auxiliary.Five.Value != nil {
				t.Fatal("不整合速度を既知の0又は反対へ変換")
			}
		})
	}
}

// TestEntry82InitialBandBoundaries は初動の帯と量回復点を別々に失効させます。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。60秒/32更新の等号と10pt通過の境界を確認します。
func TestEntry82InitialBandBoundaries(t *testing.T) {
	cases := []struct {
		name   string
		change func(*CurrentEvidence)
	}{
		{"帯未来", func(c *CurrentEvidence) { c.Night.Buy.Time = 1001 }},
		{"帯古い", func(c *CurrentEvidence) { c.Night.Buy.Time = 939.99 }},
		{"帯33更新", func(c *CurrentEvidence) { c.Night.Buy.Event = 67 }},
		{"量未来", func(c *CurrentEvidence) { c.Night.Buy.Support.Time = 1001 }},
		{"量古い", func(c *CurrentEvidence) { c.Night.Buy.Support.Time = 939.99 }},
		{"量33更新", func(c *CurrentEvidence) { c.Night.Buy.Support.Event = 67 }},
		{"量未来Index", func(c *CurrentEvidence) { c.Night.Buy.Support.Index = 41 }},
		{"量旗なし", func(c *CurrentEvidence) { c.Night.Buy.QuantitySupport = false }},
		{"価格帯未準備", func(c *CurrentEvidence) { c.Night.Known = false }},
		{"返済側10pt未通過", func(c *CurrentEvidence) { c.Night.Buy.Barrier.Price = 990.01 }},
		{"反対量が残る", func(c *CurrentEvidence) {
			c.Night.Sell = far81.CurrentPriceBand{Active: true, QuantitySupport: true, Side: -1, Time: 998, Index: 39, Event: 99, Support: far81.CurrentBarrier{Known: true, Price: 1010, Time: 997, Index: 38, Event: 98}}
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			at, q, chart, c := entry82Fixture()
			chart.Technical.TrendKnown = false
			c = entry82Band(c)
			tc.change(&c)
			for _, policy := range []string{"B0", "B1"} {
				if Decide(at, q, chart, c, policy).Allowed {
					t.Fatal("古い・未来・不成立の初動構造を採用")
				}
			}
		})
	}
	at, q, chart, c := entry82Fixture()
	chart.Technical.TrendKnown = false
	c = entry82Band(c)
	c.Night.Buy.Time, c.Night.Buy.Event = 940, 68
	c.Night.Buy.Support.Time, c.Night.Buy.Support.Event = 940, 68
	c.Night.Buy.Barrier.Price = 990
	if !Decide(at, q, chart, c, "B1").Allowed {
		t.Fatal("60秒/32更新又は返済側10ptの等号を拒否")
	}
	checkEntry82Mirror(t, at, q, chart, c)
}

// TestEntry82SpikeBoundaries は高RSI持続と同時急変を区別します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。二つのstrict境界と1ATR取得の等号を保ちます。
func TestEntry82SpikeBoundaries(t *testing.T) {
	at, q, chart, c := entry82Fixture()
	chart.Technical.TR3, chart.Technical.RSI3, chart.Technical.PreviousRSI3 = 61, 80, 64
	if Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("同時急変を採用")
	}
	chart.Technical.TR3 = 60
	if !Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("TR2倍の等号を急変扱い")
	}
	chart.Technical.TR3, chart.Technical.PreviousRSI3 = 61, 65
	if !Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("RSI差15の等号を急変扱い")
	}
	chart.Technical.RSI3, chart.Technical.PreviousRSI3 = 90, 89
	chart.Technical.ATR3 = 10
	if !Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("高RSI持続又は取得1ATR等号を拒否")
	}
	chart.Technical.EMA8_3, chart.Technical.Close3 = 1010, 1015
	if !Decide(at, q, chart, c, "B0").Allowed {
		t.Fatal("平均価格取得0ATR等号を拒否")
	}
	checkEntry82Mirror(t, at, q, chart, c)
}

// TestEntry82CandidateAndSnapshot は候補形式・競合・保存mapの独立性を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。将来約定でなく当時BBOを最大1候補として渡します。
func TestEntry82CandidateAndSnapshot(t *testing.T) {
	at, q, chart, c := entry82Fixture()
	c.Buy.Windows = map[string]far81.CurrentSupportWindow{"own5": {Known: true, Value: 1}}
	d := Decide(at, q, chart, c, "B0")
	c.Buy.Windows["own5"] = far81.CurrentSupportWindow{Value: 999}
	if d.Evidence.Buy.Windows["own5"].Value != 1 {
		t.Fatal("保存snapshotが入力mapの後変更へ追随")
	}
	f := d.Candidate("人工_Day", "D164_15", 100)
	if len(f.Lots) != 1 || len(f.Closes) != 0 || f.Lots[0].Entry != q.Ask || f.Lots[0].Quantity != 100 || f.Lots[0].At != at || !strings.Contains(f.Lots[0].ID, "B0") || !reflect.DeepEqual(f, d.Candidate("人工_Day", "D164_15", 100)) {
		t.Fatal("候補の当時値・数量・一意性が不正")
	}
	for _, bad := range []struct {
		session, window string
		quantity        int
	}{{"", "D164_15", 100}, {"人工_Day", "静観", 100}, {"人工_Day", "", 100}, {"人工_Day", "D164_15", 0}} {
		if len(d.Candidate(bad.session, bad.window, bad.quantity).Lots) > 0 {
			t.Fatal("不正引数の候補を作った")
		}
	}
	d.At += 900
	if len(d.Candidate("人工_Day", "D164_15", 100).Lots) > 0 || Decide(at, q, chart, c, "不正政策").Allowed {
		t.Fatal("古い又は不正政策の候補を作った")
	}
	conflict := EntryDecision{Role: "待機", Directions: []EntryDirection{
		{EntryDirection: far81.EntryDirection{Side: 1, Allowed: true, Role: "順行"}},
		{EntryDirection: far81.EntryDirection{Side: -1, Allowed: true, Role: "転換初動"}}}}
	resolveEntry(&conflict)
	if conflict.Allowed || conflict.Side != 0 || conflict.Role != "競合待機" {
		t.Fatal("人工競合から一方を恣意的に選んだ")
	}
}

// TestEntry82PureFeatureShortConnection は元Featuresから実経過秒速度を抽出します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。市場・実アプリ・APIは開かず、窓別bp幅との違いを確認します。
func TestEntry82PureFeatureShortConnection(t *testing.T) {
	session := strategy.Session{ID: "人工_Day", Kind: "Day", Start: 1000, ForceClose: 20000, End: 20600, ExtraAt: 14500}
	params := strategy.DefaultParameters("NK225", "Day")
	features, err := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if err != nil {
		t.Fatal(err)
	}
	features.EnableResearch()
	var o strategy.Observation
	for i := 0; i < 40; i++ {
		bid := 1000 + float64(i)
		o, err = features.OnBoard(strategy.Board{Reference: "NK225", Time: 1001 + float64(i), Received: 1001 + float64(i), Last: bid + 5, Bid: bid, Ask: bid + 10, BidQuantity: 10, AskQuantity: 10})
		if err != nil {
			t.Fatal(err)
		}
	}
	c := ExtractCurrent(o, 99)
	if !c.Short.Five.Known || !c.Short.Fifteen.Known || c.Short.Five.Speed != 1 || c.Short.Fifteen.Speed != 1 || c.Short.Five.Move != 5 || c.Short.Fifteen.Move != 15 || c.Short.Five.Speed == c.Buy.Own5 || c.SourceLine != 99 || c.SourceIndex != o.Index {
		t.Fatalf("元Shortの単位又は源番号が不正:%+v", c.Short)
	}
	_, _, chart, _ := entry82Fixture()
	chart.Technical.EMA8_3, chart.Technical.EMA21_3, chart.Technical.Close3 = 1039, 1029, 1044
	chart.Technical.Bar3End, chart.PreviousBar3End = 1030, 850
	q := Quote{Time: o.Time, Index: 400, Line: 99, Last: o.Last, Bid: o.Bid, Ask: o.Ask, Valid: o.QuoteOK}
	d := Decide(1041, q, chart, c, "B1")
	if !d.Allowed || !d.Directions[0].Auxiliary.Five.Known || d.Directions[0].Auxiliary.Five.Value == nil || *d.Directions[0].Auxiliary.Five.Value != 1 {
		t.Fatalf("公開特徴の速度を接続できない:%+v", d)
	}
	if _, err := json.Marshal(d); err != nil {
		t.Fatal(err)
	}
}
