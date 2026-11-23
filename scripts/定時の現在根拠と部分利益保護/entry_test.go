package far81

import (
	"encoding/json"
	"math"
	"reflect"
	"strings"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// entryFixture は市場を開かない買い順行の人工当時入力を作ります。
//
// 引数: ありません。
// 返り値: at(float64)、q(Quote)、t(TechnicalView)、c(CurrentEvidence)は独立入力です。
func entryFixture() (float64, Quote, TechnicalView, CurrentEvidence) {
	at := 1000.0
	q := Quote{Time: 999, Index: 50, Line: 42, Last: 1005, Bid: 1000, Ask: 1010, Valid: true}
	t := TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true, EMA8_3: 1000, EMA21_3: 990, EMA8_15: 1000, EMA21_15: 990, RSI3: 55, PreviousRSI3: 54, Histogram3: 1, PreviousHistogram3: .9, Close3: 1005, TR3: 5, ATR3: 30, PreviousATR3: 30, Bar3End: 990, Bar15End: 990}
	s := CurrentSupport{Known: true, OwnKnown: true, PeerKnown: true, OFIKnown: true, Own5: 1, Own15: 2, Own120: 3, Own300: 4, Peer120: 1, OFI30: .01, M: .4, T: .5, OwnAt: 999, PeerAt: 998, Windows: map[string]CurrentSupportWindow{"own5": {Known: true, CurrentAt: 999, EndpointAt: 994, Elapsed: 5, Value: 1}}}
	c := CurrentEvidence{Reference: "NK225", Time: 999, Received: 999, SourceIndex: 40, SourceLine: 42, Last: 1005, Bid: 1000, Ask: 1010, Buy: s, Sell: s}
	c.Sell.M, c.Sell.T = 0, 0
	return at, q, t, c
}

// initialEntryFixture は50中心線前の転換初動を人工的に作ります。
//
// 引数: ありません。
// 返り値: at(float64)、q(Quote)、t(TechnicalView)、c(CurrentEvidence)は初動入力です。
func initialEntryFixture() (float64, Quote, TechnicalView, CurrentEvidence) {
	at, q, t, c := entryFixture()
	t.TrendKnown = false
	t.EMA21_3 = 1010
	t.RSI3, t.PreviousRSI3 = 47, 45
	c.Buy.M = 0
	c.Night = CurrentStructure{Available: true, Known: true, Window: "E08", Time: 999, Index: 40, PriceEvent: 100, Band: CurrentBandWindow{Known: true, QuantityKnown: true, StartIndex: 30, Index: 40, StartTime: 980, Time: 999, Elapsed: 19, Events: 8, QuantityEvents: 8, BidMove: 20, AskMove: 20, UpFraction: .75, GrossPriceMove: 80}}
	c.Night.Buy = CurrentPriceBand{Active: true, QuantitySupport: true, ID: 4, Side: 1, Bid: 995, Ask: 1005, Time: 998, Index: 39, Event: 99, Support: CurrentBarrier{true, 995, 997, 38, 98}, Barrier: CurrentBarrier{true, 980, 995, 37, 97}}
	return at, q, t, c
}

// mirrorEntry は価格反射と符号反転を同じ人工入力へ適用します。
//
// 引数: q(Quote)、v(TechnicalView)、c(CurrentEvidence)は元入力です。
// 返り値: Quote/TechnicalView/CurrentEvidenceは買売を反転した独立値です。
func mirrorEntry(q Quote, v TechnicalView, c CurrentEvidence) (Quote, TechnicalView, CurrentEvidence) {
	const pivot = 2000.0
	q.Last, q.Bid, q.Ask = pivot-q.Last, pivot-q.Ask, pivot-q.Bid
	v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = pivot-v.EMA8_3, pivot-v.EMA21_3, pivot-v.EMA8_15, pivot-v.EMA21_15
	v.Close3 = pivot - v.Close3
	v.RSI3, v.PreviousRSI3 = 100-v.RSI3, 100-v.PreviousRSI3
	v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
	c = cloneCurrent(c)
	c.Last, c.Bid, c.Ask = pivot-c.Last, pivot-c.Ask, pivot-c.Bid
	c.Buy, c.Sell = c.Sell, c.Buy
	for _, s := range []*CurrentSupport{&c.Buy, &c.Sell} {
		s.Own5, s.Own15, s.Own120, s.Own300, s.Peer120, s.OFI30 = -s.Own5, -s.Own15, -s.Own120, -s.Own300, -s.Peer120, -s.OFI30
	}
	n := &c.Night
	n.Buy, n.Sell = n.Sell, n.Buy
	n.ConfirmedSide, n.RetestSide = -n.ConfirmedSide, -n.RetestSide
	for _, h := range []*CurrentPriceBand{&n.Buy, &n.Sell} {
		h.Side = -h.Side
		h.Bid, h.Ask = pivot-h.Ask, pivot-h.Bid
		if h.Support.Known {
			h.Support.Price = pivot - h.Support.Price
		}
		if h.Barrier.Known {
			h.Barrier.Price = pivot - h.Barrier.Price
		}
	}
	n.Band.BidMove, n.Band.AskMove, n.Band.MidMove = -n.Band.AskMove, -n.Band.BidMove, -n.Band.MidMove
	n.Band.UpFraction = 1 - n.Band.UpFraction
	return q, v, c
}

// TestEntryDirectTrendAndInitial は参照保有なしの二入口と早期転換を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。条件・役割・当時新規BBOを検証します。
func TestEntryDirectTrendAndInitial(t *testing.T) {
	at, q, v, c := entryFixture()
	for _, policy := range []string{"B0", "B1"} {
		d := Decide(at, q, v, c, policy)
		if !d.Allowed || d.Side != 1 || d.Role != "順行" || len(d.Directions) != 2 {
			t.Fatalf("%s順行不成立:%+v", policy, d)
		}
		if _, e := json.Marshal(d); e != nil {
			t.Fatal(e)
		}
	}
	// ----------------------------------------
	// 15分EMA未準備とRSI50未交差でも、B1の初動枝は現在構造で判定します。
	at, q, v, c = initialEntryFixture()
	old := Decide(at, q, v, c, "B0")
	early := Decide(at, q, v, c, "B1")
	if old.Allowed || !early.Allowed || early.Role != "転換初動" || early.Side != 1 {
		t.Fatalf("初動の区別が不正 old=%+v early=%+v", old, early)
	}
	for _, policy := range []string{"B0", "B1"} {
		mq, mv, mc := mirrorEntry(q, v, c)
		a, b := Decide(at, q, v, c, policy), Decide(at, mq, mv, mc, policy)
		if a.Allowed != b.Allowed || a.Role != b.Role || a.Side != -b.Side || a.Directions[0].Allowed != b.Directions[1].Allowed {
			t.Fatalf("初動の売買非対称:%s", policy)
		}
	}
	// ----------------------------------------
	// B0の中心線交差は旧技法と同じ条件を保ちます。
	v.RSI3, v.PreviousRSI3 = 51, 49
	c.Buy.M = .4
	d := Decide(at, q, v, c, "B0")
	if !d.Allowed || d.Role != "反転" {
		t.Fatalf("50交差が失われた:%+v", d)
	}
}

// TestEntryCurrentUnknownAndClock は未知・自己時計・相手strict過去の境界を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。源Indexと実Indexの相違は許し、物理原行相違は拒否します。
func TestEntryCurrentUnknownAndClock(t *testing.T) {
	cases := []struct {
		name   string
		change func(*float64, *Quote, *TechnicalView, *CurrentEvidence)
	}{
		{"相手未知", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.PeerKnown = false }},
		{"別参照市場", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Reference = "TOPIX" }},
		{"OFI未知", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.OFIKnown = false }},
		{"自己未知", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.OwnKnown = false }},
		{"相手同時計", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.PeerAt = c.Time }},
		{"相手古い", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.PeerAt = 984.99 }},
		{"物理行違い", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.SourceLine++ }},
		{"源時刻違い", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Time-- }},
		{"将来受信", func(a *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Received = *a + 1 }},
		{"気配違い", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Bid-- }},
		{"不正実Index", func(_ *float64, q *Quote, _ *TechnicalView, _ *CurrentEvidence) { q.Index = -1 }},
		{"交差板", func(_ *float64, q *Quote, _ *TechnicalView, _ *CurrentEvidence) { q.Ask = q.Bid }},
		{"将来気配", func(a *float64, q *Quote, _ *TechnicalView, _ *CurrentEvidence) { q.Time = *a + 1 }},
		{"数量方向不一致", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.OFI30 = 0 }},
		{"自己短期逆方向", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.Own5 = -1 }},
		{"非有限支持", func(_ *float64, _ *Quote, _ *TechnicalView, c *CurrentEvidence) { c.Buy.M = math.NaN() }},
		{"スパイク未知", func(_ *float64, _ *Quote, v *TechnicalView, _ *CurrentEvidence) { v.SpikeKnown = false }},
		{"未来3分足", func(a *float64, _ *Quote, v *TechnicalView, _ *CurrentEvidence) { v.Bar3End = *a + 1 }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			for _, p := range []string{"B0", "B1"} {
				at, q, v, c := entryFixture()
				tc.change(&at, &q, &v, &c)
				if d := Decide(at, q, v, c, p); d.Allowed {
					t.Fatalf("%s不正を採用:%s", tc.name, p)
				}
			}
		})
	}
	at, q, v, c := entryFixture()
	c.Buy.PeerAt = 985
	if !Decide(at, q, v, c, "B0").Allowed {
		t.Fatal("相手15秒等号を拒否")
	}
	q.Time, c.Time, c.Received, c.Buy.OwnAt, c.Buy.PeerAt = 985, 985, 985, 985, 984
	if Decide(at, q, v, c, "B0").Allowed {
		t.Fatal("相手が定時から16秒古い値を自己鮮度に便乗")
	}
	c.Buy.PeerAt = 984
	q.Time, c.Time, c.Received, c.Buy.OwnAt = 985, 985, 985, 985
	at = 999
	if !Decide(at, q, v, c, "B0").Allowed {
		t.Fatal("自己14秒・相手15秒を拒否")
	}
}

// TestEntrySpikeAndPlacement は同時急変のstrict境界と1ATR配置を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。単独の高RSIを除外せず、独自配置の上下端を保ちます。
func TestEntrySpikeAndPlacement(t *testing.T) {
	at, q, v, c := entryFixture()
	v.TR3 = 61
	v.RSI3, v.PreviousRSI3 = 80, 64
	for _, p := range []string{"B0", "B1"} {
		if Decide(at, q, v, c, p).Allowed {
			t.Fatalf("同時急変を採用:%s", p)
		}
	}
	v.TR3 = 60
	if !Decide(at, q, v, c, "B1").Allowed {
		t.Fatal("TR2倍等号を急変に数えた")
	}
	v.TR3 = 61
	v.PreviousRSI3 = 65
	if !Decide(at, q, v, c, "B0").Allowed {
		t.Fatal("RSI差15等号を急変に数えた")
	}
	v.RSI3, v.PreviousRSI3 = 90, 89
	if !Decide(at, q, v, c, "B0").Allowed {
		t.Fatal("高RSI持続だけを拒否")
	}
	for _, test := range []struct {
		ema float64
		ok  bool
	}{{1010, true}, {980, true}, {979.99, false}, {1010.01, false}} {
		v.EMA8_3 = test.ema
		v.EMA21_3 = test.ema - 10
		d := Decide(at, q, v, c, "B1")
		if d.Allowed != test.ok {
			t.Fatalf("位置境界EMA=%v got%v", test.ema, d.Allowed)
		}
	}
	v.EMA8_3 = 1000
	v.ATR3 = 0
	if Decide(at, q, v, c, "B1").Allowed {
		t.Fatal("既知ATR0へ1ATRを適用")
	}
}

// TestEntryInitialStructureBoundaries は現在帯と数量回復点を別々に失効させます。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。生成時の量支持旗だけで古い又は未来の回復点を採用しません。
func TestEntryInitialStructureBoundaries(t *testing.T) {
	cases := []struct {
		name   string
		change func(*CurrentEvidence)
	}{
		{"帯未知", func(c *CurrentEvidence) { c.Night.Known = false }},
		{"帯不正", func(c *CurrentEvidence) { c.Night.Invalid = true }},
		{"帯後退", func(c *CurrentEvidence) { c.Night.Buy.Time = 939.99 }},
		{"帯更新過多", func(c *CurrentEvidence) { c.Night.Buy.Event = 67 }},
		{"回復点古い", func(c *CurrentEvidence) { c.Night.Buy.Support.Time = 939.99 }},
		{"回復点更新過多", func(c *CurrentEvidence) { c.Night.Buy.Support.Event = 67 }},
		{"未来回復点", func(c *CurrentEvidence) { c.Night.Buy.Support.Time = 1001 }},
		{"未来Barrier", func(c *CurrentEvidence) { c.Night.Buy.Barrier.Time = 1001 }},
		{"未来源Index", func(c *CurrentEvidence) { c.Night.Buy.Support.Index = 41 }},
		{"未来価格Event", func(c *CurrentEvidence) { c.Night.Buy.Support.Event = 101 }},
		{"価格帯当時行違い", func(c *CurrentEvidence) { c.Night.Index-- }},
		{"窓当時行違い", func(c *CurrentEvidence) { c.Night.Band.Index-- }},
		{"窓時計違い", func(c *CurrentEvidence) { c.Night.Band.Time-- }},
		{"押戻り中", func(c *CurrentEvidence) { c.Night.Buy.Pressured = true }},
		{"量支持なし", func(c *CurrentEvidence) { c.Night.Buy.QuantitySupport = false }},
		{"回復点未知", func(c *CurrentEvidence) { c.Night.Buy.Support.Known = false }},
		{"反対障害未通過", func(c *CurrentEvidence) { c.Night.Buy.Barrier.Price = 995 }},
		{"確認帯維持不足", func(c *CurrentEvidence) { c.Night.Buy.Bid = 1001 }},
		{"反対帯支持", func(c *CurrentEvidence) {
			c.Night.Sell = CurrentPriceBand{Active: true, QuantitySupport: true, Side: -1, Time: 998, Index: 39, Event: 99, Support: CurrentBarrier{true, 1010, 997, 38, 98}}
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			at, q, v, c := initialEntryFixture()
			tc.change(&c)
			if Decide(at, q, v, c, "B1").Allowed {
				t.Fatal("不成立の初動を採用")
			}
		})
	}
	at, q, v, c := initialEntryFixture()
	c.Night.Buy.Time = 940
	c.Night.Buy.Event = 68
	c.Night.Buy.Support.Time = 940
	c.Night.Buy.Support.Event = 68
	c.Night.Buy.Barrier.Price = 990
	if !Decide(at, q, v, c, "B1").Allowed {
		t.Fatal("60秒/32更新/反対10ptの等号を拒否")
	}
	c.Night.Buy.Barrier.Time = 939.99
	c.Night.Buy.Barrier.Price = 1100
	if !Decide(at, q, v, c, "B1").Allowed {
		t.Fatal("古いBarrierを現在の反対供給帯にした")
	}
}

// TestEntryExtractionAndSnapshot は公開型の抽出と元map非共有を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。観測・保存判断の数値を後の呼出しで書き換えません。
func TestEntryExtractionAndSnapshot(t *testing.T) {
	o := strategy.Observation{Reference: "NK225", Time: 999, Received: 999, Index: 40, Last: 1005, Bid: 1000, Ask: 1010, QuoteOK: true}
	o.Selected.DayBuy = strategy.SelectedDay164Support{Known: true, Own5: 1, Own15: 2, Own120: 3, Own300: 4, Peer120: 1, OFI30: .01, M: .4, T: .5, OwnAt: 999, PeerAt: 998, Components: &strategy.SelectedDay164Components{OwnKnown: true, PeerKnown: true, OFIKnown: true, Windows: map[string]strategy.SelectedDay164Window{"own5": {Known: true, Value: 1}}}}
	o.Selected.NightAvailable = true
	o.Selected.NightTime = 999
	o.Selected.NightIndex = 40
	o.Selected.Night.Known = true
	o.Selected.Night.Window = "E08"
	o.Selected.Night.PriceEvent = 100
	o.Selected.Night.Buy.Active = true
	o.Selected.Night.Buy.Side = 1
	c := ExtractCurrent(o, 42)
	if c.SourceIndex != 40 || c.SourceLine != 42 || c.Night.Index != 40 || !c.Night.Buy.Active || c.Buy.M != .4 {
		t.Fatal("公開入力の抽出不一致")
	}
	o.Selected.DayBuy.Components.Windows["own5"] = strategy.SelectedDay164Window{Known: false, Value: 100}
	if !c.Buy.Windows["own5"].Known || c.Buy.Windows["own5"].Value != 1 {
		t.Fatal("元mapを共有")
	}
	at, q, v, _ := entryFixture()
	d := Decide(at, q, v, c, "B0")
	before, _ := json.Marshal(d)
	c.Buy.Windows["own5"] = CurrentSupportWindow{Known: false, Value: 200}
	after, _ := json.Marshal(d)
	if string(before) != string(after) {
		t.Fatal("保存判断が呼出し元により変化")
	}
	if !d.Allowed || q.Index == c.SourceIndex {
		t.Fatal("源Indexと実Indexを同一視")
	}
}

// TestEntryCandidateAndMirrors は当時BBO候補・一意ID・売買の符号対称を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。窓・枚数・待機の不正値から新規候補を作りません。
func TestEntryCandidateAndMirrors(t *testing.T) {
	at, q, v, c := entryFixture()
	d := Decide(at, q, v, c, "B0")
	f := d.Candidate("人工_Day", "D164_15", 100)
	if len(f.Lots) != 1 || len(f.Closes) != 0 {
		t.Fatal("候補件数不正")
	}
	p := f.Lots[0]
	if p.Entry != q.Ask || p.At != at || p.Quantity != 100 || p.Method != "D164_15" || p.Kind != "順行" || p.Closing || !strings.Contains(p.ID, "B0") || !strings.Contains(p.ID, "+1") {
		t.Fatalf("候補の当時入力不正:%+v", p)
	}
	if !reflect.DeepEqual(f, d.Candidate("人工_Day", "D164_15", 100)) {
		t.Fatal("同条件候補IDが非決定的")
	}
	d.At += 900
	if d.Candidate("人工_Day", "D164_15", 100).Lots != nil && len(d.Candidate("人工_Day", "D164_15", 100).Lots) != 0 {
		t.Fatal("古い気配で候補を作った")
	}
	for _, args := range []struct {
		session, window string
		q               int
	}{{"", "D164_15", 100}, {"人工_Day", "静観", 100}, {"人工_Day", "", 100}, {"人工_Day", "D164_15", 0}} {
		if len(Decide(at, q, v, c, "B0").Candidate(args.session, args.window, args.q).Lots) != 0 {
			t.Fatal("不正候補を作った")
		}
	}
	for _, policy := range []string{"B0", "B1"} {
		mq, mv, mc := mirrorEntry(q, v, c)
		buy, sell := Decide(at, q, v, c, policy), Decide(at, mq, mv, mc, policy)
		if !buy.Allowed || !sell.Allowed || sell.Side != -1 || buy.Role != sell.Role || buy.Directions[0].PlacementPoints != sell.Directions[1].PlacementPoints {
			t.Fatalf("順行非対称:%s", policy)
		}
		sf := sell.Candidate("人工_Day", "D164_15", 100)
		if len(sf.Lots) != 1 || sf.Lots[0].Entry != mq.Bid {
			t.Fatal("売り新規の想定価格はBid")
		}
	}
	if Decide(at, q, v, c, "B2").Allowed {
		t.Fatal("未知政策を採用")
	}
	v.Bar15End = at + 1
	for _, policy := range []string{"B0", "B1"} {
		if Decide(at, q, v, c, policy).Allowed {
			t.Fatal("未来15分足の順行を採用")
		}
	}
}

// TestEntryConflict は矛盾した人工両側入力でも一方向を恣意的に選ばないことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。競合は待機と空候補へ変換します。
func TestEntryConflict(t *testing.T) {
	at, q, v, c := entryFixture()
	v.EMA8_3 = 1005
	v.EMA21_3 = 995
	v.RSI3, v.PreviousRSI3 = 45, 46
	v.Histogram3, v.PreviousHistogram3 = 0, 1
	v.Close3 = 1000
	c.Sell = c.Buy
	c.Sell.Own5, c.Sell.Own15, c.Sell.Own120, c.Sell.Own300, c.Sell.Peer120, c.Sell.OFI30 = -1, -2, -3, -4, -1, -.01
	c.Night = CurrentStructure{Available: true, Known: true, Window: "E08", Time: 999, Index: 40, PriceEvent: 100, Band: CurrentBandWindow{Known: true, Index: 40, StartIndex: 30, Time: 999, StartTime: 980}}
	c.Night.Sell = CurrentPriceBand{Active: true, QuantitySupport: true, Side: -1, ID: 4, Bid: 1005, Ask: 1015, Time: 998, Index: 39, Event: 99, Support: CurrentBarrier{true, 1015, 997, 38, 98}, Barrier: CurrentBarrier{true, 1030, 995, 37, 97}}
	d := Decide(at, q, v, c, "B1")
	if !d.Directions[0].Allowed || !d.Directions[1].Allowed || d.Allowed || d.Side != 0 || d.Role != "競合待機" || len(d.Candidate("人工_Day", "D164_15", 100).Lots) != 0 {
		t.Fatalf("競合を採用:%+v", d)
	}
}

// TestEntryPureFeaturesConnection は元の公開特徴器を人工一原行だけで接続します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。実市場・実アプリ・APIへ接続せず未準備を拒否します。
func TestEntryPureFeaturesConnection(t *testing.T) {
	session := strategy.Session{ID: "人工_Day", Kind: "Day", Start: 1000, ForceClose: 20000, End: 20600, ExtraAt: 14500}
	params := strategy.DefaultParameters("NK225", "Day")
	f, e := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		t.Fatal(e)
	}
	f.EnableResearch()
	o, e := f.OnBoard(strategy.Board{Reference: "NK225", Time: 1001, Received: 1001, Last: 1005, Bid: 1000, Ask: 1010, BidQuantity: 10, AskQuantity: 10})
	if e != nil {
		t.Fatal(e)
	}
	c := ExtractCurrent(o, 7)
	q := Quote{Time: o.Time, Index: 9, Line: 7, Last: o.Last, Bid: o.Bid, Ask: o.Ask, Valid: o.QuoteOK}
	_, _, v, _ := entryFixture()
	if c.SourceIndex != 0 || c.SourceLine != 7 || !c.Night.Available || c.Night.Known || c.Buy.Known {
		t.Fatal("未準備の公開特徴を別の値へ変換")
	}
	for _, p := range []string{"B0", "B1"} {
		d := Decide(1002, q, v, c, p)
		if d.Allowed {
			t.Fatal("一原行で準備済とした")
		}
		if _, e = json.Marshal(d); e != nil {
			t.Fatal(e)
		}
	}
}
