// 89派生元: scripts/FAR参照玉と可変数量の比較/actual_test.go
// 89派生元SHA256: f0633c7e2a8717cea4b5021fc2c80dc0198bdb5d8399286f7d7d7de99037a5c8
// 固定87は変更せず、G1旧全文とG2既存分岐を別会計で比較します。

// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/actual_test.go
// 87派生元SHA256: e1b49e26b1ebd92b724d35e1fae384592fd741dcabaa42f0e222fdd68fd21818

// 86派生元: scripts/保持帯の返済側固定否定/actual_test.go
// 86派生元SHA256: a9c57d62fd0e83b2d8720c25fd64b406214887ddb6ea2922cbf6f1c70202f57b

package far89

import (
	"encoding/json"
	"math"
	"reflect"
	"strings"
	"testing"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far83 "github.com/masayoshi4649/SessionTradeExecuter/research83"
)

// need85 は金融人工の異常を当該テストへ報告します。
//
// 引数: t(*testing.T)、err(error)は検査器と呼出結果です。
// 返り値: ありません。異常ならテストを停止します。
func need85(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

// quote85 は10pt格子の正常BBOと別々のIndex/Lineを人工作成します。
//
// 引数: index(int64)、bid/ask(float64)は原行番号と気配です。
// 返り値: Quoteは価格時計1000+index−1、物理行100+indexを持ちます。
func quote85(index int64, bid, ask float64) Quote {
	return Quote{Time: 999 + float64(index), Index: index, Line: 100 + index, Last: bid, Bid: bid, Ask: ask, Valid: true}
}

// evidence85 はsource IndexとQuote Indexを意図的に分けたfresh E08を作ります。
//
// 引数: q(Quote)、side(int)は要求時の人工気配と方向です。
// 返り値: CurrentEvidenceは保持帯と特徴の出典を手製で与えた人工です。
func evidence85(q Quote, side int) CurrentEvidence {
	c := CurrentEvidence{}
	c.Reference, c.Time, c.Received, c.SourceLine, c.SourceIndex = "NK225", q.Time, q.Time, q.Line, 70
	c.Last, c.Bid, c.Ask = q.Last, q.Bid, q.Ask
	c.Night.Available, c.Night.Known, c.Night.Window, c.Night.Time, c.Night.Index, c.Night.PriceEvent = true, true, "E08", q.Time, 70, 30
	c.Night.Band.Known, c.Night.Band.Time, c.Night.Band.StartTime, c.Night.Band.Index, c.Night.Band.StartIndex = true, q.Time, q.Time-5, 70, 60
	hold := far81.CurrentPriceBand{Active: true, ID: 7, Side: side, Bid: q.Bid, Ask: q.Ask, Time: q.Time - 10, Index: 60, Event: 20}
	if side > 0 {
		c.Night.Buy = hold
	} else {
		c.Night.Sell = hold
	}
	return c
}

// candidate85 はIDと100枚を持つB1互換の供給候補を作ります。
//
// 引数: at(float64)、side(int)、q(Quote)は要求時計と人工方向・気配です。
// 返り値: ReferenceFrameは一件の新規候補です。
func candidate85(at float64, side int, q Quote) ReferenceFrame {
	price := q.Ask
	if side < 0 {
		price = q.Bid
	}
	id := "人工_B1_候補"
	return ReferenceFrame{Lots: []ReferenceLot{{ID: id, InternalID: id, Parent: id, SourceID: id, Method: "D164_15", Owner: "B1", Kind: "順行", Side: side, Quantity: 100, Entry: price, At: at}}, Closes: []ReferenceClose{}}
}

// gain85 は買い建値10010・売り建値10000から対称な返済気配を作ります。
//
// 引数: index(int64)、side(int)、gain(float64)は原行・方向・方向幅です。
// 返り値: Quoteはスプレッド10ptの人工です。
func gain85(index int64, side int, gain float64) Quote {
	if side > 0 {
		return quote85(index, 10010+gain, 10020+gain)
	}
	return quote85(index, 9990-gain, 10000-gain)
}

// open85 は要求時の出典を固定し、次正常原行で100枚を実所有します。
//
// 引数: t(*testing.T)、side(int)、enabled(bool)、atr/delay(float64)は人工条件です。
// 返り値: *Bookは一玉を持つ金融、HoldAnchorは凍結した要求線です。
func open85(t *testing.T, side int, enabled bool, atr, delay float64) (*Book, HoldAnchor) {
	t.Helper()
	b, e := NewBook("人工場", "S0G1", 100, enabled)
	need85(t, e)
	need85(t, b.SetFillDelay(delay))
	q := quote85(1, 10000, 10010)
	c := evidence85(q, side)
	anchor, e := BuildHoldAnchor(q.Time, q, c, side)
	need85(t, e)
	tech := TechnicalView{ATRKnown: true, ATR3: atr}
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
	need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, StructureAnchor{}, anchor, c))
	need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, tech))
	if b.Result().Metrics.OpenQuantity != 100 {
		t.Fatal("非0実所有を作れません")
	}
	return b, anchor
}

// project85 は宣言した新hold欄だけを除いた旧全BookのJSON投影を作ります。
//
// 引数: value(any)は新旧のBookResultです。
// 返り値: map[string]anyは価格・数量・配列順・旧全値を変えない投影です。
func project85(value any) map[string]any {
	raw, e := json.Marshal(value)
	if e != nil {
		panic(e)
	}
	var out map[string]any
	if e = json.Unmarshal(raw, &out); e != nil {
		panic(e)
	}
	stripSource87(out)
	delete(out, "hold_enabled")
	delete(out, "confirm_enabled")
	for _, container := range []string{"orders", "pending_entries", "lots", "positions", "closed"} {
		for _, item := range out[container].([]any) {
			row := item.(map[string]any)
			for _, field := range []string{"hold_anchor", "hold_active", "hold_floor", "hold_activated_at", "hold_entry_breached", "hold_first_hit_at", "hold_first_hit_index", "hold_first_hit_line"} {
				delete(row, field)
			}
			for _, field := range []string{"confirm_counts", "confirm_first_price_breach", "confirm_first_unknown", "confirm_first_confirmed", "confirm_evidence", "confirm_request_evidence"} {
				delete(row, field)
			}
		}
	}
	metrics := out["metrics"].(map[string]any)
	for _, field := range []string{"hold_known_entries", "hold_unknown_entries", "hold_activated_lots", "hold_entry_breached_lots", "hold_hit_lots", "hold_exit_orders"} {
		delete(metrics, field)
	}
	for _, field := range []string{"confirm_counts", "confirm_confirmed_lots", "confirm_exit_orders", "confirm_exit_obligations", "confirm_missing_quantity"} {
		delete(metrics, field)
	}
	return out
}

// TestHold85SourceAndReject は同出典と格子・未知・未来・方向の境界を確認します。
//
// 引数: t(*testing.T)は市場なしの人工検査です。
// 返り値: ありません。不正候補又は偽anchorを受理すれば失敗します。
func TestHold85SourceAndReject(t *testing.T) {
	for _, side := range []int{1, -1} {
		q := quote85(1, 10000, 10010)
		c := evidence85(q, side)
		a, e := BuildHoldAnchor(q.Time, q, c, side)
		need85(t, e)
		if !a.Known || a.QuoteIndex == a.FeatureIndex || a.SourceLine != q.Line || a.HoldID != 7 || a.StopPrice != map[int]float64{1: 9990, -1: 10020}[side] {
			t.Fatal("出典又は方向式", a)
		}
		get := func(c *CurrentEvidence) *far81.CurrentPriceBand {
			if side > 0 {
				return &c.Night.Buy
			}
			return &c.Night.Sell
		}
		mutations := []struct {
			name   string
			change func(*CurrentEvidence)
		}{
			{"別原行", func(x *CurrentEvidence) { x.SourceLine++ }},
			{"特徴番号", func(x *CurrentEvidence) { x.Night.Index++ }},
			{"窓番号", func(x *CurrentEvidence) { x.Night.Band.Index++ }},
			{"特徴時計", func(x *CurrentEvidence) { x.Time++ }},
			{"未来受領", func(x *CurrentEvidence) { x.Received++ }},
			{"無効E08", func(x *CurrentEvidence) { x.Night.Invalid = true }},
			{"未知E08", func(x *CurrentEvidence) { x.Night.Known = false }},
			{"別窓", func(x *CurrentEvidence) { x.Night.Window = "T15" }},
			{"hold方向", func(x *CurrentEvidence) { get(x).Side = -side }},
			{"holdID0", func(x *CurrentEvidence) { get(x).ID = 0 }},
			{"hold未来", func(x *CurrentEvidence) { get(x).Time = q.Time + 1 }},
			{"hold非格子", func(x *CurrentEvidence) { get(x).Bid++ }},
			{"holdNaN", func(x *CurrentEvidence) { get(x).Ask = math.NaN() }},
			{"hold圧力", func(x *CurrentEvidence) { get(x).Pressured = true }},
			{"hold未来event", func(x *CurrentEvidence) { get(x).Event = x.Night.PriceEvent + 1 }},
			{"hold未来index", func(x *CurrentEvidence) { get(x).Index = x.SourceIndex + 1 }},
		}
		for _, test := range mutations {
			bad := c
			test.change(&bad)
			if _, e = BuildHoldAnchor(q.Time, q, bad, side); e == nil {
				t.Fatal(test.name, side)
			}
		}
		badQ := q
		badQ.Bid++
		if _, e = BuildHoldAnchor(q.Time, badQ, c, side); e == nil {
			t.Fatal("気配の格子不正を受理")
		}
		boundary := c
		h := get(&boundary)
		h.Time = q.Time - 60
		h.Event = 0
		boundary.Night.PriceEvent = 32
		if _, e = BuildHoldAnchor(q.Time, q, boundary, side); e != nil {
			t.Fatal("60秒32更新の包含", e)
		}
		h.Time = q.Time - 60.01
		if _, e = BuildHoldAnchor(q.Time, q, boundary, side); e == nil {
			t.Fatal("60秒超を受理")
		}
		h.Time = q.Time
		boundary.Night.PriceEvent = 33
		if _, e = BuildHoldAnchor(q.Time, q, boundary, side); e == nil {
			t.Fatal("32更新超を受理")
		}
		for _, enabled := range []bool{false, true} {
			b, e := NewBook("人工", "S0G1", 100, enabled)
			need85(t, e)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			unknown, e := BuildHoldAnchor(q.Time, q, c, 0)
			need85(t, e)
			if e = b.OnGrid(q.Time, q, candidate85(q.Time, side, q), TechnicalView{}, StructureAnchor{}, unknown, c); e == nil {
				t.Fatal("候補あり未知を受理")
			}
			bad := a
			bad.StopPrice += 10
			if e = b.OnGrid(q.Time, q, candidate85(q.Time, side, q), TechnicalView{}, StructureAnchor{}, bad, c); e == nil {
				t.Fatal("固定停止式の改変を受理")
			}
			need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), TechnicalView{}, StructureAnchor{}, a, c))
		}
	}
	unknown, e := BuildHoldAnchor(1000, Quote{}, CurrentEvidence{}, 0)
	need85(t, e)
	if unknown.Known || unknown.At != 0 || unknown.StopPrice != 0 || unknown.Reason != holdUnknownReason {
		t.Fatal("未知への価格創作", unknown)
	}
}

// TestHold85EqualityAndInclusive は等号維持・1tick到達・次板約定を売買鏡像で検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。等号誤切り・当原行約定・方向非対称なら失敗します。
func TestHold85EqualityAndInclusive(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, a := open85(t, side, true, 100, 0)
		r := b.Result()
		p := r.Lots[0]
		if len(r.Orders) != 1 || p.HoldEntryBreached || p.HoldFirstHitAt != nil || !p.HoldActive || *p.HoldFloor != -20 {
			t.Fatal("等号維持を切った", r)
		}
		a.StopPrice = 1
		need85(t, b.OnQuote(gain85(3, side, -20), ReferenceFrame{}, TechnicalView{}))
		r = b.Result()
		p = r.Lots[0]
		if len(r.Trades) != 1 || len(r.Orders) != 2 || r.Orders[1].Reason != HoldExitReason || p.HoldFirstHitLine != 103 || p.HoldFirstHitIndex != 3 || r.Metrics.HoldExitOrders != 1 {
			t.Fatal("1tick到達又は次行制約", r)
		}
		need85(t, b.OnQuote(gain85(4, side, -30), ReferenceFrame{}, TechnicalView{}))
		r = b.Result()
		if r.Unresolved || r.Metrics.NetPnLYen != -42200 || r.Metrics.HoldHitLots != 1 || r.Closed[0].HoldFirstHitLine != 103 || r.Closed[0].HoldAnchor.StopPrice == 1 {
			t.Fatal("価格線での架空約定又は出典共有", r)
		}
	}
}

// TestHold85FillAlreadyBroken は遅延fillが否定側なら同原行要求・次原行返済することを検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。新規fillを消したり同原行に架空返済したら失敗します。
func TestHold85FillAlreadyBroken(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, e := NewBook("人工", "S0G1", 100, true)
			need85(t, e)
			need85(t, b.SetFillDelay(delay))
			q := quote85(1, 10000, 10010)
			c := evidence85(q, side)
			a, e := BuildHoldAnchor(q.Time, q, c, side)
			need85(t, e)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), TechnicalView{}, StructureAnchor{}, a, c))
			next := quote85(2, 9990, 10000)
			if side < 0 {
				next = quote85(2, 10010, 10020)
			}
			need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			p := r.Lots[0]
			if len(r.Trades) != 1 || len(r.Orders) != 2 || r.Orders[1].RequestLine != next.Line || p.HoldFirstHitLine != next.Line || !p.HoldEntryBreached || r.Metrics.HoldEntryBreachedLots != 1 {
				t.Fatal("実fill否定の順序", r)
			}
			next.Index++
			next.Line++
			next.Time++
			need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
			if b.Result().Unresolved || b.Result().Orders[1].FillLine <= b.Result().Orders[1].RequestLine {
				t.Fatal("次原行返済ではない")
			}
		}
	}
}

// TestHold85OldFloorTieAndPriority はATR床との同値・旧床優先と非緩和を検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。旧床を保持帯由来と誤認すれば失敗します。
func TestHold85OldFloorTieAndPriority(t *testing.T) {
	for _, distance := range []float64{15, 20} {
		for _, side := range []int{1, -1} {
			b, _ := open85(t, side, true, distance, 0)
			need85(t, b.OnQuote(gain85(3, side, -20), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			if len(r.Orders) != 2 || r.Orders[1].Reason != "正益前ATR損失追尾" || r.Metrics.HoldExitOrders != 0 || r.Metrics.HoldHitLots != 1 {
				t.Fatal("旧ATR床の優先を破った", r)
			}
		}
	}
}

// TestHold85PartialSnapshot は部分fill後のhitを先行片へ遡及しないことを検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。G1の確定R・残量床又は時点snapshotが破れれば失敗します。
func TestHold85PartialSnapshot(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, _ := open85(t, side, true, 100, 0)
		need85(t, b.OnQuote(gain85(3, side, 20), ReferenceFrame{}, TechnicalView{}))
		if b.Result().Orders[1].Quantity != 75 || b.Result().Lots[0].Floor < 0 {
			t.Fatal("G1の即時75枚計画又は最低建値床を変更")
		}
		need85(t, b.OnQuote(gain85(4, side, -20), ReferenceFrame{}, TechnicalView{}))
		r := b.Result()
		if len(r.Closed) != 1 || r.Closed[0].HoldFirstHitAt != nil || r.Lots[0].HoldFirstHitLine != 104 || !r.Lots[0].FundingFailed || r.Lots[0].Floor < 0 || len(r.Orders) != 3 || r.Orders[2].Reason != "G1確定益予算・ATR追尾" {
			t.Fatal("先行部分片へ将来hitを遡及又はG1優先破損", r)
		}
		need85(t, b.OnQuote(gain85(5, side, -20), ReferenceFrame{}, TechnicalView{}))
		r = b.Result()
		if r.Unresolved || len(r.Closed) != 2 || r.Closed[1].HoldFirstHitLine != 104 || r.Metrics.HoldHitLots != 1 || r.Metrics.HoldExitOrders != 0 {
			t.Fatal("後続片の当時hit又は予約が破損", r)
		}
	}
}

// TestHold85FinalFillHitIsNotBackdated は既予約全返済fillだけの接触を後段hitへ遡及しません。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。実残量0の後からhitを作れば失敗します。
func TestHold85FinalFillHitIsNotBackdated(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, _ := open85(t, side, true, 100, 0)
		for _, step := range []struct {
			index int64
			gain  float64
		}{{3, 20}, {4, 20}, {5, 0}, {6, -20}} {
			need85(t, b.OnQuote(gain85(step.index, side, step.gain), ReferenceFrame{}, TechnicalView{}))
		}
		r := b.Result()
		if r.Unresolved || r.Metrics.HoldHitLots != 0 || r.Lots[0].HoldFirstHitAt != nil || r.Closed[len(r.Closed)-1].HoldFirstHitAt != nil {
			t.Fatal("最終全返済fillの後からhitを遡及した", r)
		}
	}
}

// TestHold85OppositeQuoteOnlyAndExpiry は単線の限界と要求線の固定を検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。反対側だけの変化や期限で停止線を動かせば失敗します。
func TestHold85OppositeQuoteOnlyAndExpiry(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, e := NewBook("人工", "S0G1", 100, true)
		need85(t, e)
		q := quote85(1, 10000, 10020)
		c := evidence85(q, side)
		a, e := BuildHoldAnchor(q.Time, q, c, side)
		need85(t, e)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), TechnicalView{}, StructureAnchor{}, a, c))
		need85(t, b.OnQuote(quote85(2, 10000, 10020), ReferenceFrame{}, TechnicalView{}))
		next := quote85(3, 10000, 10010)
		if side < 0 {
			next = quote85(3, 10010, 10020)
		}
		next.Time = q.Time + 100
		need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
		r := b.Result()
		if len(r.Orders) != 1 || r.Lots[0].HoldFirstHitAt != nil || r.Lots[0].HoldAnchor != a {
			t.Fatal("両気配ORやhold失効を単線へ混入", r)
		}
	}
}

// TestHold85DisabledFullProjection は非0の売買・二遅延を旧83へ全文同値にします。
//
// 引数: t(*testing.T)は独立旧Bookを並べて動かす人工です。
// 返り値: ありません。宣言外の旧数値・キー・配列差を許可しません。
func TestHold85DisabledFullProjection(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, e := NewBook("人工", "S0G1", 100, false)
			need85(t, e)
			old, e := far83.NewBook("人工", "S0G1", 100)
			need85(t, e)
			need85(t, b.SetFillDelay(delay))
			need85(t, old.SetFillDelay(delay))
			q := quote85(1, 10000, 10010)
			c := evidence85(q, side)
			a, e := BuildHoldAnchor(q.Time, q, c, side)
			need85(t, e)
			tech := TechnicalView{ATRKnown: true, ATR3: 100}
			frame := candidate85(q.Time, side, q)
			need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
			need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
			need85(t, b.OnGrid(q.Time, q, frame, tech, StructureAnchor{}, a, c))
			need85(t, old.OnGrid(q.Time, q, frame, tech, StructureAnchor{}))
			quotes := []Quote{quote85(2, 10000, 10010), gain85(3, side, 20), gain85(4, side, 20), gain85(5, side, 0), gain85(6, side, -10)}
			for _, next := range quotes {
				need85(t, b.OnQuote(next, ReferenceFrame{}, tech))
				need85(t, old.OnQuote(next, ReferenceFrame{}, tech))
			}
			r := b.Result()
			before := old.Result()
			if r.Metrics.EntryQuantity != 100 || r.Unresolved || r.Metrics.HoldActivatedLots != 0 || r.Metrics.HoldKnownEntries != 1 || !reflect.DeepEqual(project85(r), project85(before)) {
				t.Fatalf("H0旧非0全文が不同値 side%d delay%g", side, delay)
			}
		}
	}
}

// TestHold85StrictProfitAndNormalQuality はstrict正益と有効保有中の格子品質を検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。0円で旗を立てる、非格子を黙って丸める場合に失敗します。
func TestHold85StrictProfitAndNormalQuality(t *testing.T) {
	b, _ := open85(t, 1, true, 100, 0)
	p := b.lots["人工_B1_候補"]
	if b.observe(p, gain85(3, 1, 12.2)); p.Flag {
		t.Fatal("費用後0で旗を立てた")
	}
	if b.observe(p, gain85(4, 1, 12.3)); !p.Flag {
		t.Fatal("費用後strict正で旗を立てない")
	}
	q := quote85(3, 10001, 10010)
	if e := b.OnQuote(q, ReferenceFrame{}, TechnicalView{}); e == nil || !strings.Contains(e.Error(), "10pt格子") {
		t.Fatal("非格子の正常保有気配を受理", e)
	}
}

// TestHold85SameClockAndDelay は同秒の物理行と追加価格時計遅延を別に検査します。
//
// 引数: t(*testing.T)は市場なしの人工検査です。
// 返り値: ありません。同原行fill又は1秒前の架空fillを許すと失敗します。
func TestHold85SameClockAndDelay(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, e := NewBook("人工", "S0G1", 100, true)
			need85(t, e)
			need85(t, b.SetFillDelay(delay))
			q := quote85(1, 10000, 10010)
			c := evidence85(q, side)
			a, e := BuildHoldAnchor(q.Time, q, c, side)
			need85(t, e)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), TechnicalView{}, StructureAnchor{}, a, c))
			next := quote85(2, 9990, 10000)
			if side < 0 {
				next = quote85(2, 10010, 10020)
			}
			next.Time = q.Time
			need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
			if delay == 1 {
				if len(b.Result().Trades) != 0 {
					t.Fatal("追加1秒前に新規を約定")
				}
				next.Index++
				next.Line++
				next.Time++
				need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
			}
			request := b.Result().Orders[1]
			if request.RequestLine != next.Line || len(b.Result().Trades) != 1 {
				t.Fatal("新規原行で返済要求し、同原行では未約定とする")
			}
			next.Index++
			next.Line++
			need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
			if delay == 1 {
				if len(b.Result().Trades) != 1 {
					t.Fatal("返済要求から追加1秒前に約定")
				}
				next.Index++
				next.Line++
				next.Time++
				need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}))
			}
			if b.Result().Unresolved || len(b.Result().Trades) != 2 {
				t.Fatal("後続の適格原行で全返済しない")
			}
		}
	}
}

// TestHold85PressureAndUnknown はC0の反対圧力と候補無しの通常未知を検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。反対圧力を通す、数量をC0へ追加する、通常未知を創作する場合に失敗します。
func TestHold85PressureAndUnknown(t *testing.T) {
	for _, side := range []int{1, -1} {
		q := quote85(1, 10000, 10010)
		c := evidence85(q, side)
		point := far81.CurrentBarrier{Known: true, Price: q.Bid, Time: q.Time, Index: c.SourceIndex, Event: c.Night.PriceEvent}
		if side < 0 {
			point.Price = q.Ask
		}
		h := &c.Night.Buy
		opposite := &c.Night.Sell
		if side < 0 {
			h, opposite = opposite, h
		}
		h.Barrier = point
		if _, e := BuildHoldAnchor(q.Time, q, c, side); e == nil {
			t.Fatal("fresh反対障害の未通過を許可")
		}
		h.Barrier.Price -= float64(side) * 10
		if _, e := BuildHoldAnchor(q.Time, q, c, side); e != nil {
			t.Fatal("10ptちょうど通過又は数量支持なしC0を拒否", e)
		}
		*opposite = far81.CurrentPriceBand{Active: true, QuantitySupport: true, Time: q.Time, Index: c.SourceIndex, Event: c.Night.PriceEvent, Support: point}
		if _, e := BuildHoldAnchor(q.Time, q, c, side); e == nil {
			t.Fatal("fresh反対数量帯を許可")
		}
		opposite.Support.Time = q.Time - 61
		if _, e := BuildHoldAnchor(q.Time, q, c, side); e != nil {
			t.Fatal("鮮度外の反対数量点をfresh扱い", e)
		}
	}
	q := quote85(1, 10000, 10010)
	unknown, e := BuildHoldAnchor(q.Time, q, CurrentEvidence{}, 0)
	need85(t, e)
	for _, enabled := range []bool{false, true} {
		b, e := NewBook("人工", "S0G1", 100, enabled)
		need85(t, e)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		need85(t, b.OnGrid(q.Time, q, ReferenceFrame{}, TechnicalView{}, StructureAnchor{}, unknown, CurrentEvidence{}))
		if len(b.Result().Orders) != 0 || b.Result().Decisions[0].Action != "待ち" || b.Result().HoldEnabled != enabled {
			t.Fatal("通常未知の枠を新規又は別設定へ変更")
		}
	}
	for _, mode := range []string{"S1G1", "S1G2", "H0G1", "H1G1"} {
		if _, e := NewBook("人工", mode, 100, true); e == nil {
			t.Fatal("内部金融modeはS0G1又はS0G2だけ", mode)
		}
	}
	if _, e := NewBook("人工", "S0G1", 99, false); e == nil {
		t.Fatal("100枚以外を許可")
	}
}

// TestHold85EMAAndBirthPrice はEMA追跡を保持帯へ偽装せず、出生価格と確認時計を分けます。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。EMA同値検査を迂回する、保持帯価格を確認時BBOへ変更すると失敗します。
func TestHold85EMAAndBirthPrice(t *testing.T) {
	for _, side := range []int{1, -1} {
		q := quote85(1, 10000, 10010)
		c := evidence85(q, side)
		h := &c.Night.Buy
		if side < 0 {
			h = &c.Night.Sell
		}
		h.Bid -= float64(side) * 20
		h.Ask -= float64(side) * 20
		a, e := BuildHoldAnchor(q.Time, q, c, side)
		need85(t, e)
		b, e := NewBook("人工", "S0G1", 100, true)
		need85(t, e)
		tech := TechnicalView{ExitKnown: true, EMA8_3: 9955.25, Bar3End: q.Time, ATRKnown: true, ATR3: 100}
		need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
		fake := StructureAnchor{Known: true, Price: a.StopPrice, At: q.Time, BarEnd: q.Time}
		if e = b.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, fake, a, c); e == nil {
			t.Fatal("保持帯価格を確定EMAと偽って受理")
		}
		ema := StructureAnchor{Known: true, Price: tech.EMA8_3, At: q.Time, BarEnd: q.Time}
		need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, ema, a, c))
		need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, tech))
		r := b.Result()
		p := r.Lots[0]
		if p.StructureActive || p.StructureFloor != nil || p.StructureAnchor.Price != tech.EMA8_3 || p.HoldAnchor != a || p.HoldAnchor.HoldBid == q.Bid {
			t.Fatal("EMA追跡と保持帯出生値を混合", p)
		}
	}
	if _, e := BuildHoldAnchor(math.NaN(), Quote{}, CurrentEvidence{}, 0); e == nil {
		t.Fatal("不供給でも非有限の要求時計を受理")
	}
}
