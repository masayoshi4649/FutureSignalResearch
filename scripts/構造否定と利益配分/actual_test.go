package far83

import (
	"math"
	"testing"
)

// bookTestNeed は人工呼出しの異常をその場で報告します。
//
// 引数: tは*testing.T、errはerrorです。
// 返り値: なし。異常なら当該テストを停止します。
func bookTestNeed(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

// bookTestQuote は入力市場を開かない正常な人工気配を作ります。
//
// 引数: indexはint64、bid/askはfloat64です。
// 返り値: Quoteは同じ番号の原行と価格秒を持ちます。
func bookTestQuote(index int64, bid, ask float64) Quote {
	return Quote{Time: float64(index), Index: index, Line: index, Last: (bid + ask) / 2, Bid: bid, Ask: ask, Valid: true}
}

// bookTestCandidate は外部選別済みの100枚候補を人工作成します。
//
// 引数: idはstring、sideはintの±1です。
// 返り値: ReferenceFrameは一件の定時候補です。
func bookTestCandidate(id string, side int) ReferenceFrame {
	return ReferenceFrame{Lots: []ReferenceLot{{ID: id, Side: side, Quantity: 100, Entry: 1000, At: 0, Method: "人工の現在根拠", Kind: "順行"}}}
}

// bookTestOpen は定時新規要求を次原行で100枚約定させます。
//
// 引数: tは*testing.T、modeはstring、sideはint、atrはfloat64、knownはbool、delayはfloat64です。
// 返り値: *Bookは一建玉を実所有した会計です。
func bookTestOpen(t *testing.T, mode string, side int, atr float64, known bool, delay float64) *Book {
	t.Helper()
	b, err := NewBook("人工場", mode, 100)
	bookTestNeed(t, err)
	bookTestNeed(t, b.SetFillDelay(delay))
	q := bookTestQuote(1, 1000, 1005)
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("R1", side), TechnicalView{ATRKnown: known, ATR3: atr}, StructureAnchor{}))
	bookTestNeed(t, b.OnQuote(bookTestQuote(2, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	if b.Result().Metrics.OpenQuantity != 100 {
		t.Fatal("100枚の人工建玉を作れなかった")
	}
	return b
}

// bookTestGain は実方向幅を指定して鏡像の返済気配を作ります。
//
// 引数: indexはint64、sideはint、gainはfloat64の順行幅です。
// 返り値: Quoteは買い建値1005・売り建値1000を基準とする気配です。
func bookTestGain(index int64, side int, gain float64) Quote {
	if side == 1 {
		return bookTestQuote(index, 1005+gain, 1010+gain)
	}
	return bookTestQuote(index, 995-gain, 1000-gain)
}

// bookTestCash はViewer約定だけから数量・現金・費用を独立に再計算します。
//
// 引数: tは*testing.T、rはBookResultの完結済み結果です。
// 返り値: なし。会計本体の損益関数やClosedを使わず照合します。
func bookTestCash(t *testing.T, r BookResult) {
	t.Helper()
	type own struct {
		side, quantity int
		entry          float64
	}
	positions := map[string]*own{}
	cash, gross, cost := 0.0, 0.0, 0.0
	entryQ, exitQ := 0, 0
	for _, trade := range r.Trades {
		if trade.Quantity <= 0 || trade.FeeYen != 61*float64(trade.Quantity) {
			t.Fatal("約定片の数量又は費用が不正")
		}
		cash -= trade.FeeYen
		cost += trade.FeeYen
		side := 1
		if trade.Type == "ShortN" || trade.Type == "ShortR" {
			side = -1
		}
		if trade.Type == "LongN" || trade.Type == "ShortN" {
			if positions[trade.PositionID] != nil {
				t.Fatal("所有IDが新規で重複")
			}
			positions[trade.PositionID] = &own{side: side, quantity: trade.Quantity, entry: trade.Price}
			entryQ += trade.Quantity
		} else {
			p := positions[trade.PositionID]
			if p == nil || p.side != side || p.quantity < trade.Quantity {
				t.Fatal("返済の所有又は枚数が不正")
			}
			value := float64(side*trade.Quantity*10) * (trade.Price - p.entry)
			gross += value
			cash += value
			p.quantity -= trade.Quantity
			exitQ += trade.Quantity
		}
	}
	for _, p := range positions {
		if p.quantity != 0 {
			t.Fatal("独立約定台帳に未返済がある")
		}
	}
	if cash != r.Metrics.CashYen || cash != r.Metrics.NetPnLYen || gross != r.Metrics.GrossPnLYen || cost != r.Metrics.TotalCostYen || entryQ != r.Metrics.EntryQuantity || exitQ != r.Metrics.ExitQuantity {
		t.Fatalf("独立現金照合:%g/%g/%g != %+v", cash, gross, cost, r.Metrics)
	}
	if r.Metrics.CommissionYen != float64((entryQ+exitQ)*11) || r.Metrics.SlippageYen != float64((entryQ+exitQ)*50) {
		t.Fatal("独立費用内訳が不一致")
	}
}

// ----------------------------------------

// anchor83Open は入口要求時の価格線を保存し、次原行で100枚を実所有します。
//
// 引数: t(*testing.T)、mode(string)、side(int)、distance(float64)、known(bool)は人工条件です。
// 返り値: *Bookは要求時EMAを独立に保存した会計です。
func anchor83Open(t *testing.T, mode string, side int, distance float64, known bool) *Book {
	t.Helper()
	b, err := NewBook("人工場", mode, 100)
	bookTestNeed(t, err)
	q := bookTestQuote(1, 1000, 1005)
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	entry := 1005.0
	if side < 0 {
		entry = 1000
	}
	price := entry - float64(side)*distance
	tech := TechnicalView{ATRKnown: true, ATR3: 100, ExitKnown: true, EMA8_3: price, Bar3End: 1}
	anchor := StructureAnchor{Known: known, Price: price, At: 1, BarEnd: 1, Reason: "人工公開EMA"}
	bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("R1", side), tech, anchor))
	anchor.Price = 999999
	bookTestNeed(t, b.OnQuote(bookTestQuote(2, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	return b
}

// TestBook83ModesAndOccupancy は4政策・同時一建玉・100枚固定を検査します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。未知政策・競合・待機中の新規を受理すれば失敗します。
func TestBook83ModesAndOccupancy(t *testing.T) {
	for _, mode := range Modes {
		b, err := NewBook("人工", mode, 100)
		bookTestNeed(t, err)
		q := bookTestQuote(1, 1000, 1005)
		bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		bad := bookTestCandidate("A", 1)
		bad.Lots = append(bad.Lots, bookTestCandidate("B", -1).Lots...)
		if b.OnGrid(1, q, bad, TechnicalView{}, StructureAnchor{}) == nil {
			t.Fatal("競合二候補を選択した")
		}
		bad = bookTestCandidate("A", 1)
		bad.Lots[0].Quantity = 99
		if b.OnGrid(1, q, bad, TechnicalView{}, StructureAnchor{}) == nil {
			t.Fatal("100枚以外を受理")
		}
		bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("A", 1), TechnicalView{}, StructureAnchor{}))
		bookTestNeed(t, b.OnGrid(1.5, q, bookTestCandidate("B", -1), TechnicalView{}, StructureAnchor{}))
		if len(b.Result().Orders) != 1 || b.Result().Decisions[1].Action != "処理中" {
			t.Fatal("新規待機中に反対方向を予約")
		}
		bookTestNeed(t, b.OnQuote(bookTestQuote(2, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
		bookTestNeed(t, b.OnGrid(2, bookTestQuote(2, 1000, 1005), bookTestCandidate("C", -1), TechnicalView{}, StructureAnchor{}))
		if len(b.Result().Orders) != 1 || b.Result().Decisions[2].Action != "保有継続" {
			t.Fatal("実所有中に再入場")
		}
	}
	for _, bad := range []string{"B0G1", "S0G0", "S2G1", "S0G3"} {
		if _, err := NewBook("人工", bad, 100); err == nil {
			t.Fatal("未知政策受理", bad)
		}
	}
	if _, err := NewBook("人工", "S0G1", 99); err == nil {
		t.Fatal("100以外の上限を受理")
	}
}

// TestBook83ProfitAllocation は同じ順行列の75/25と全量追尾の配分差を検査します。
//
// 引数: t(*testing.T)は買い・売り鏡像の検査です。
// 返り値: ありません。未確定予算・早期全返済・G2部分返済は失敗です。
func TestBook83ProfitAllocation(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, mode := range Modes {
			b := bookTestOpen(t, mode, side, 23, true, 0)
			bookTestNeed(t, b.OnQuote(bookTestGain(3, side, 20), ReferenceFrame{}, TechnicalView{}))
			p := b.Result().Positions[0]
			if !p.Flag || p.Floor != 0 || p.FlagFloor == nil || *p.FlagFloor != 0 || p.CashFloorActive {
				t.Fatal("利益初回の建値床又は未確定予算が不正", mode)
			}
			if b.guard == "G1" && (p.HarvestTarget != 75 || p.ReservedExit != 75 || p.NetPnL != 0) {
				t.Fatal("G1初回75枚計画", mode)
			}
			if b.guard == "G2" && (p.HarvestTarget != 0 || p.ReservedExit != 0 || p.HarvestOrderID != "") {
				t.Fatal("G2が部分返済", mode)
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(4, side, 20), ReferenceFrame{}, TechnicalView{}))
			p = b.Result().Positions[0]
			if b.guard == "G1" && (p.Quantity != 25 || p.NetPnL != 5850 || !p.CashFloorActive) {
				t.Fatal("G1実確定後の予算", mode)
			}
			if b.guard == "G2" && (p.Quantity != 100 || p.NetPnL != 0 || p.CashFloorActive) {
				t.Fatal("G2全量が残らない", mode)
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(5, side, 70), ReferenceFrame{}, TechnicalView{}))
			if b.Result().Positions[0].Floor != 45 {
				t.Fatal("ATR追尾の非緩和", mode)
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(6, side, 45), ReferenceFrame{}, TechnicalView{}))
			bookTestNeed(t, b.OnQuote(bookTestGain(7, side, 40), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			want := 12800.0
			if b.guard == "G2" {
				want = 27800
				if r.Metrics.HarvestOrders != 0 || r.Metrics.CashFloorActivatedLots != 0 || r.Metrics.FundingFailureLots != 0 {
					t.Fatal("G2に部分予算集計", mode)
				}
			}
			if r.Unresolved || r.Metrics.NetPnLYen != want || r.Metrics.TotalCostYen != 12200 || r.Metrics.ProtectionMissingQuantity != 0 {
				t.Fatal("配分の会計又は保護不足", mode, r.Metrics)
			}
			bookTestCash(t, r)
		}
	}
}

// TestBook83BreakevenCostLoss は最低建値が費用後黒字保証ではないことを検査します。
//
// 引数: t(*testing.T)は鏡像の回復・建値返済です。
// 返り値: ありません。G2の費用負けを隠したりG1利確を先取りすれば失敗です。
func TestBook83BreakevenCostLoss(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, mode := range Modes {
			b := bookTestOpen(t, mode, side, 23, true, 0)
			for _, row := range []struct {
				i    int64
				gain float64
			}{{3, 20}, {4, 20}, {5, 0}, {6, 0}} {
				bookTestNeed(t, b.OnQuote(bookTestGain(row.i, side, row.gain), ReferenceFrame{}, TechnicalView{}))
			}
			r := b.Result()
			want := 2800.0
			if b.guard == "G2" {
				want = -12200
				if !r.Lots[0].Flag || r.Lots[0].Floor != 0 || len(r.Closed) != 1 || !r.Closed[0].NominalFlat {
					t.Fatal("G2の建値返済と費用負け", mode)
				}
			}
			if r.Unresolved || r.Metrics.NetPnLYen != want {
				t.Fatal("建値時の配分純額", mode, r.Metrics)
			}
			bookTestCash(t, r)
		}
	}
}

// TestBook83FixedStructure は新規時EMAの固定・等号到達・同原行要求を検査します。
//
// 引数: t(*testing.T)は全政策と買い売り鏡像です。
// 返り値: ありません。後のEMAへの移動・S0活性・要求遅延があれば失敗です。
func TestBook83FixedStructure(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, mode := range Modes {
			b := anchor83Open(t, mode, side, 20, true)
			p := b.Result().Positions[0]
			price := p.EntryPrice - float64(side)*20
			if p.StructureAnchor.Price != price || p.StructureAnchor.At != 1 || p.StructureAnchor.BarEnd != 1 {
				t.Fatal("要求時価格線の値コピー", mode)
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(3, side, 10), ReferenceFrame{}, TechnicalView{EMA8_3: 99999}))
			bookTestNeed(t, b.OnQuote(bookTestGain(4, side, -20), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			p = r.Positions[0]
			if b.stop == "S0" {
				if p.StructureActive || p.StructureFloor != nil || p.StructureActivatedAt != nil || p.StructureFirstHitIndex != -1 || p.ReservedExit != 0 {
					t.Fatal("S0が構造を活性", mode)
				}
				bookTestNeed(t, b.Force(4, bookTestGain(4, side, -20), "人工期限"))
			} else {
				if !p.StructureActive || *p.StructureFloor != -20 || *p.StructureActivatedAt != 2 || p.StructureEntryBreached || p.StructureFirstHitIndex != 4 || *p.StructureFirstHitAt != 4 || p.ReservedExit != 100 {
					t.Fatal("構造活性又は等号要求", mode, p)
				}
				o := r.Orders[len(r.Orders)-1]
				if o.Reason != "固定EMA構造否定" || o.RequestIndex != 4 || o.RequestTime != 4 || o.StructureAnchor != p.StructureAnchor || *o.StructureFloor != -20 || r.Metrics.StructureExitOrders != 1 {
					t.Fatal("同原行の構造返済metadata", mode)
				}
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(5, side, -25), ReferenceFrame{}, TechnicalView{}))
			r = b.Result()
			if r.Unresolved || r.Metrics.NetPnLYen != -37200 || r.Closed[0].StructureAnchor.Price != price || r.Metrics.StructureKnownEntries != 1 {
				t.Fatal("構造返済会計", mode, r.Metrics)
			}
			bookTestCash(t, r)
		}
	}
}

// TestBook83UnknownAndInvalidAnchor は未知を補完せず、既知の未来・別足を拒否します。
//
// 引数: t(*testing.T)は未知対照と不正条件の検査です。
// 返り値: ありません。不正既知線受理又は未知線の活性は失敗です。
func TestBook83UnknownAndInvalidAnchor(t *testing.T) {
	for _, mode := range Modes {
		b := anchor83Open(t, mode, 1, 20, false)
		p := b.Result().Positions[0]
		if p.StructureAnchor.Known || p.StructureAnchor.Price != 0 || p.StructureAnchor.At != 0 || p.StructureActive || p.StructureFloor != nil || p.StructureFirstHitIndex != -1 || b.Result().Metrics.StructureUnknownEntries != 1 {
			t.Fatal("未知構造を創作", mode)
		}
	}
	tech := TechnicalView{ExitKnown: true, EMA8_3: 985, Bar3End: 1}
	good := StructureAnchor{Known: true, Price: 985, At: 1, BarEnd: 1}
	for _, bad := range []StructureAnchor{{true, math.NaN(), 1, 1, "NaN"}, {true, 0, 1, 1, "0価格"}, {true, 985, 2, 1, "未来要求"}, {true, 985, 1, 2, "未来足"}, {true, 985, 1, -180, "古足"}, {true, 986, 1, 1, "別EMA"}} {
		if _, err := normalizeAnchor(1, tech, bad); err == nil {
			t.Fatal("既知不正構造を受理", bad.Reason)
		}
	}
	if _, err := normalizeAnchor(1, TechnicalView{}, good); err == nil {
		t.Fatal("未知の足を既知アンカーに結合")
	}
	unknown, err := normalizeAnchor(1, tech, StructureAnchor{Price: math.NaN(), At: math.Inf(1), Reason: "人工未観測"})
	bookTestNeed(t, err)
	if unknown.Known || unknown.Price != 0 || unknown.At != 0 || unknown.BarEnd != 0 || unknown.Reason != "人工未観測" {
		t.Fatal("未知の非有限値を保存又は観測化")
	}
}

// TestBook83AlreadyBreachedEntry は実約定が線の反対側でも新規を隠さず即返済します。
//
// 引数: t(*testing.T)は両方向と両利益配分の検査です。
// 返り値: ありません。同原行架空約定・入口取消・線の移動は失敗です。
func TestBook83AlreadyBreachedEntry(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, mode := range []string{"S1G1", "S1G2"} {
			b, err := NewBook("人工", mode, 100)
			bookTestNeed(t, err)
			q := bookTestQuote(1, 1000, 1005)
			bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			anchorPrice := 985.0
			if side < 0 {
				anchorPrice = 1020
			}
			tech := TechnicalView{ExitKnown: true, EMA8_3: anchorPrice, Bar3End: 1, ATRKnown: true, ATR3: 100}
			bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("R", side), tech, StructureAnchor{Known: true, Price: anchorPrice, At: 1, BarEnd: 1}))
			fill := bookTestQuote(2, 975, 980)
			if side < 0 {
				fill = bookTestQuote(2, 1025, 1030)
			}
			bookTestNeed(t, b.OnQuote(fill, ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			p := r.Positions[0]
			if len(r.Trades) != 1 || p.Quantity != 100 || p.ReservedExit != 100 || !p.StructureEntryBreached || *p.StructureFloor != 5 || p.StructureAnchor.Price != anchorPrice || p.StructureFirstHitIndex != 2 || r.Metrics.StructureEntryBreachedLots != 1 {
				t.Fatal("既に割れた実約定の保存", mode, p)
			}
			fill.Index, fill.Line, fill.Time = 3, 3, 3
			bookTestNeed(t, b.OnQuote(fill, ReferenceFrame{}, TechnicalView{}))
			r = b.Result()
			if r.Unresolved || r.Metrics.NetPnLYen != -17200 || len(r.Trades) != 2 || r.Closed[0].StructureFirstHitIndex != 2 {
				t.Fatal("即否定の次原行返済", mode, r.Metrics)
			}
			bookTestCash(t, r)
		}
	}
}

// TestBook83StrictProfitAndPending は費用後0等号・遅延・EOFで未確定益を使いません。
//
// 引数: t(*testing.T)は全政策の境界検査です。
// 返り値: ありません。0等号の正益化・EOFの架空返済・G2部分予約は失敗です。
func TestBook83StrictProfitAndPending(t *testing.T) {
	for _, mode := range Modes {
		b := bookTestOpen(t, mode, 1, 23, true, 0)
		bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 12.2), ReferenceFrame{}, TechnicalView{}))
		if b.Result().Positions[0].Flag {
			t.Fatal("費用後0を正益化", mode)
		}
		bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, 15), ReferenceFrame{}, TechnicalView{}))
		r := b.Result()
		if !r.Unresolved || !r.Positions[0].Flag || r.Positions[0].Floor != 0 || r.Metrics.CashYen != -6100 || r.Metrics.NetPnLYen != 0 || r.Positions[0].CashFloorActive {
			t.Fatal("正益起動とEOF未約定", mode, r.Metrics)
		}
		if b.guard == "G2" && (len(r.Orders) != 1 || r.Positions[0].ReservedExit != 0) {
			t.Fatal("G2が利確予約", mode)
		}
	}
	b := bookTestOpen(t, "S1G2", 1, 23, true, 1)
	bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, 0), ReferenceFrame{}, TechnicalView{}))
	q := bookTestGain(5, 1, 0)
	q.Time = 4
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	if b.Result().Metrics.OpenQuantity != 100 {
		t.Fatal("1秒追加を同価格秒で約定")
	}
	q = bookTestGain(6, 1, -5)
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	if b.Result().Unresolved || b.Result().Metrics.NetPnLYen != -17200 {
		t.Fatal("次適格原行で返済しない")
	}
	bookTestCash(t, b.Result())
}

// TestBook83ReservationAndInvalidQuote は部分予約を取り消さず、不良気配で約定しません。
//
// 引数: t(*testing.T)はG1の悪化・期限・不良BBOの検査です。
// 返り値: ありません。数量の二重返済・取消・未約定予算は失敗です。
func TestBook83ReservationAndInvalidQuote(t *testing.T) {
	b := bookTestOpen(t, "S1G1", 1, 23, true, 0)
	bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	bookTestNeed(t, b.Force(3, bookTestGain(3, 1, 20), "人工場末"))
	r := b.Result()
	if len(r.Orders) != 3 || r.Positions[0].ReservedExit != 100 || r.Positions[0].CashFloorActive {
		t.Fatal("部分予約後の未予約量だけ返済できない")
	}
	q := bookTestGain(4, 1, 20)
	q.Valid = false
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	if b.Result().Metrics.OpenQuantity != 100 || len(b.Result().Trades) != 1 {
		t.Fatal("不良BBOで約定")
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(5, 1, 10), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Unresolved || r.Metrics.NetPnLYen != -2200 || r.Metrics.ExitQuantity != 100 || r.Metrics.TotalCostYen != 12200 {
		t.Fatal("予約量の悪化・費用", r.Metrics)
	}
	for _, order := range r.Orders {
		if order.CancelledQuantity != 0 {
			t.Fatal("受理返済を取り消した")
		}
	}
	bookTestCash(t, r)
}

// TestBook83AdverseHarvest はG1の約定悪化で実確定予算だけを再計算します。
//
// 引数: t(*testing.T)は両方向と両停止政策の検査です。
// 返り値: ありません。未確定予算や不足残玉の放置は失敗です。
func TestBook83AdverseHarvest(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, mode := range []string{"S0G1", "S1G1"} {
			b := bookTestOpen(t, mode, side, 23, true, 0)
			bookTestNeed(t, b.OnQuote(bookTestGain(3, side, 20), ReferenceFrame{}, TechnicalView{}))
			bookTestNeed(t, b.OnQuote(bookTestGain(4, side, 10), ReferenceFrame{}, TechnicalView{}))
			p := b.Result().Positions[0]
			if p.NetPnL != -1650 || p.Quantity != 25 || p.CashFloor == nil || *p.CashFloor != 30 || p.Floor != 30 || p.ReservedExit != 25 || !p.FundingFailed {
				t.Fatal("不足した確定予算で残玉を放置", mode, p)
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(5, side, 10), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			if r.Unresolved || r.Metrics.NetPnLYen != -2200 || r.Metrics.WholeFlagAfterLossLots != 1 || r.Metrics.FundingFailureLots != 1 || r.Metrics.ProtectionMissingQuantity != 0 {
				t.Fatal("実行悪化を黒字に変えた", mode, r.Metrics)
			}
			bookTestCash(t, r)
		}
	}
	for _, row := range []struct {
		quantity      int
		closed, floor float64
	}{{25, 5850, 0}, {25, -1650, 30}, {100, 22200, 5}} {
		floor, err := actualCashFloor(row.closed, row.quantity)
		bookTestNeed(t, err)
		if floor != row.floor {
			t.Fatal("5pt刻み確定床の算術", row, floor)
		}
	}
}

// TestBook83StructureAndTechPriority は確定技法返済と構造到達の同時発生を区別します。
//
// 引数: t(*testing.T)は両方向・両配分の同原行検査です。
// 返り値: ありません。先に予約した全量を構造到達で二重返済すれば失敗します。
func TestBook83StructureAndTechPriority(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, mode := range []string{"S1G1", "S1G2"} {
			b := anchor83Open(t, mode, side, 20, true)
			tech := TechnicalView{ExitKnown: true, Bar3End: 3, Close3: 900, EMA8_3: 1000, Histogram3: -1, PreviousHistogram3: 0}
			if side < 0 {
				tech.Close3, tech.Histogram3 = 1100, 1
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(3, side, -20), ReferenceFrame{}, tech))
			r := b.Result()
			if len(r.Orders) != 2 || r.Orders[1].Reason != "確定3分技法失敗" || r.Positions[0].ReservedExit != 100 || r.Metrics.StructureHitLots != 1 || r.Metrics.StructureExitOrders != 0 {
				t.Fatal("技法・構造同時の数量又は理由", mode, r.Metrics)
			}
			bookTestNeed(t, b.OnQuote(bookTestGain(4, side, -20), ReferenceFrame{}, TechnicalView{}))
			bookTestCash(t, b.Result())
		}
	}
	anchor := StructureAnchor{Known: true, Price: 985, At: 200, BarEnd: 20}
	tech := TechnicalView{ExitKnown: true, EMA8_3: 985, Bar3End: 20}
	if _, err := normalizeAnchor(200, tech, anchor); err != nil {
		t.Fatal("公開後180秒の等号を拒否", err)
	}
	anchor.At = 200.1
	if _, err := normalizeAnchor(200.1, tech, anchor); err == nil {
		t.Fatal("公開後180秒超を受理")
	}
}
