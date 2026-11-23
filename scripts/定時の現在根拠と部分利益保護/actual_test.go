package far81

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
	bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("R1", side), TechnicalView{ATRKnown: known, ATR3: atr}))
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

// TestBook81ModesAndOccupancy は候補を再選別せず一建玉だけを受け付けることを検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。方向跨ぎ・待機中の新規・不正候補を受理すれば失敗します。
func TestBook81ModesAndOccupancy(t *testing.T) {
	for _, mode := range Modes {
		b, err := NewBook("人工", mode, 100)
		bookTestNeed(t, err)
		q := bookTestQuote(1, 1000, 1005)
		bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		bad := bookTestCandidate("A", 1)
		bad.Lots = append(bad.Lots, bookTestCandidate("B", -1).Lots...)
		if b.OnGrid(1, q, bad, TechnicalView{}) == nil {
			t.Fatal("競合二候補をID順で選択した")
		}
		bad = bookTestCandidate("A", 1)
		bad.Lots[0].Quantity = 99
		if b.OnGrid(1, q, bad, TechnicalView{}) == nil {
			t.Fatal("100枚以外の定時候補を受理した")
		}
		bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("A", 1), TechnicalView{}))
		bookTestNeed(t, b.OnGrid(1.5, q, bookTestCandidate("B", -1), TechnicalView{}))
		if len(b.Result().Orders) != 1 || b.Result().Decisions[1].Action != "処理中" {
			t.Fatal("新規待機中に反対方向を予約した")
		}
		bookTestNeed(t, b.OnQuote(bookTestQuote(2, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
		bookTestNeed(t, b.OnGrid(2, bookTestQuote(2, 1000, 1005), bookTestCandidate("C", -1), TechnicalView{}))
		if len(b.Result().Orders) != 1 || b.Result().Decisions[2].Action != "保有継続" {
			t.Fatal("実保有中に反対方向を予約した")
		}
	}
	if _, err := NewBook("人工", "P1", 100); err == nil {
		t.Fatal("81で旧政策を受理した")
	}
	if _, err := NewBook("人工", "B0G0", 99); err == nil {
		t.Fatal("研究対照の上限100以外を受理した")
	}
}

// TestBook81G0ProfitAndLossTrail は両政策の正益前ATRとG0の20pt床を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。ATRを緩めたり正益前の損失追尾を止めれば失敗します。
func TestBook81G0ProfitAndLossTrail(t *testing.T) {
	for _, guard := range []string{"G0", "G1"} {
		b := bookTestOpen(t, "B0"+guard, 1, 23, true, 0)
		if b.Result().Positions[0].Floor != -25 {
			t.Fatal("入口ATRから初期停止線を置かなかった")
		}
		bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 10), ReferenceFrame{}, TechnicalView{}))
		if p := b.Result().Positions[0]; p.Flag || p.Floor != -15 {
			t.Fatal("正益前の最高幅から損失停止線を追尾しなかった")
		}
		bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, -15), ReferenceFrame{}, TechnicalView{}))
		if b.Result().Positions[0].ReservedExit != 100 {
			t.Fatal("正益前ATRの等号で返済しなかった")
		}
		bookTestNeed(t, b.OnQuote(bookTestGain(5, 1, -15), ReferenceFrame{}, TechnicalView{}))
		r := b.Result()
		if r.Unresolved || r.Metrics.NetPnLYen != -27200 || r.Lots[0].Flag || r.Metrics.ProtectionMissingQuantity != 0 {
			t.Fatal("正益前損失の費用又は所有が不正")
		}
		bookTestCash(t, r)
	}
	b := bookTestOpen(t, "B1G0", 1, 23, true, 0)
	bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	if p := b.Result().Positions[0]; !p.Flag || p.Floor != 20 || p.ReservedExit != 100 || p.HarvestOrderID != "" {
		t.Fatal("G0の初回20pt全返済が不正")
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, 20), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if r.Metrics.NetPnLYen != 7800 || r.Metrics.TotalCostYen != 12200 || r.Metrics.WholeProfitFlags != 1 || !r.Lots[0].WholeFlag {
		t.Fatal("G0の費用又は全玉正益が不正")
	}
	bookTestCash(t, r)
}

// TestBook81HarvestAndRunner は75枚の確定後だけ残25枚へcash床を有効化します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。予定利益の先取り、全量早期返済、停止線緩和があれば失敗します。
func TestBook81HarvestAndRunner(t *testing.T) {
	b := bookTestOpen(t, "B0G1", 1, 23, true, 0)
	bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	p := r.Positions[0]
	if p.HarvestTarget != 75 || p.HarvestNeeded != 75 || !p.HarvestFeasible || p.ReservedExit != 75 || p.CashFloorActive || p.NetPnL != 0 || p.Floor != 0 {
		t.Fatalf("利確待ちで予算を先取り:%+v", p)
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, 20), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	p = r.Positions[0]
	if p.Quantity != 25 || p.NetPnL != 5850 || p.HarvestFilled != 75 || p.HarvestDoneAt == nil || !p.CashFloorActive || p.CashFloor == nil || *p.CashFloor != 0 || p.Floor != 0 || p.ReservedExit != 0 || p.FundingFailed {
		t.Fatalf("確定益の残玉保護が不正:%+v", p)
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(5, 1, 70), ReferenceFrame{}, TechnicalView{}))
	if p = b.Result().Positions[0]; p.Floor != 45 || p.ReservedExit != 0 {
		t.Fatal("有利進行からATR床を上げなかった")
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(6, 1, 45), ReferenceFrame{}, TechnicalView{}))
	if b.Result().Positions[0].ReservedExit != 25 {
		t.Fatal("上げた床で残25枚を返済予約しなかった")
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(7, 1, 40), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Unresolved || r.Metrics.CashYen != 12800 || r.Metrics.NetPnLYen != 12800 || r.Metrics.GrossPnLYen != 25000 || r.Metrics.TotalCostYen != 12200 || r.Metrics.CommissionYen != 2200 || r.Metrics.SlippageYen != 10000 {
		t.Fatalf("75/25の現金又は費用:%+v", r.Metrics)
	}
	if len(r.Trades) != 3 || r.Trades[1].Quantity != 75 || r.Trades[2].Quantity != 25 || r.Metrics.HarvestOrders != 1 || r.Metrics.HarvestFilledQuantity != 75 || r.Metrics.CashFloorActivatedLots != 1 || r.Metrics.WholeFlagAfterLossLots != 0 {
		t.Fatal("利確と残玉の履歴が不正")
	}
	if r.Closed[0].PnL0+r.Closed[1].PnL0 != 22800 || r.Closed[0].PnL10+r.Closed[1].PnL10 != 2800 {
		t.Fatal("同約定0/10pt費用感応が不正")
	}
	bookTestCash(t, r)
}

// TestBook81AdverseHarvest は利確要求後の悪化を確定予算不足として扱います。
//
// 引数: tは*testing.Tです。
// 返り値: なし。未約定75枚の予定5850円を使えば失敗します。
func TestBook81AdverseHarvest(t *testing.T) {
	b := bookTestOpen(t, "B0G1", 1, 23, true, 0)
	bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, 10), ReferenceFrame{}, TechnicalView{}))
	p := b.Result().Positions[0]
	if p.NetPnL != -1650 || p.Quantity != 25 || p.CashFloor == nil || *p.CashFloor != 30 || p.Floor != 30 || p.ReservedExit != 25 || !p.FundingFailed || b.Result().Metrics.FundingFailureLots != 1 {
		t.Fatalf("不足時に残玉を放置:%+v", p)
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(5, 1, 10), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if r.Unresolved || r.Metrics.NetPnLYen != -2200 || r.Metrics.WholeFlagAfterLossLots != 1 || !r.Lots[0].WholeFlag || r.Metrics.ProtectionMissingQuantity != 0 {
		t.Fatal("全玉正益後の実行悪化を黒字とした")
	}
	bookTestCash(t, r)
}

// TestBook81DelayAndForce は利確待ちと残玉強制予約を二重にしません。
//
// 引数: tは*testing.Tです。
// 返り値: なし。待機中にcash床を有効化したり既受理返済を取消せば失敗します。
func TestBook81DelayAndForce(t *testing.T) {
	b := bookTestOpen(t, "B0G1", 1, 23, true, 1)
	bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	q := bookTestGain(4, 1, 20)
	q.Time = 3.5
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	p := b.Result().Positions[0]
	if p.Quantity != 100 || p.NetPnL != 0 || p.HarvestFilled != 0 || p.CashFloorActive || p.ReservedExit != 75 || p.Floor != 0 {
		t.Fatal("1秒未満で約定又は予定益を確定した")
	}
	bookTestNeed(t, b.Force(3.6, q, "人工境界"))
	if b.Result().Positions[0].ReservedExit != 100 {
		t.Fatal("利確予約を残して未予約25枚を返さなかった")
	}
	q = bookTestGain(5, 1, 20)
	q.Time = 4
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	if p = b.Result().Positions[0]; p.Quantity != 25 || p.ReservedExit != 25 || !p.CashFloorActive {
		t.Fatal("別時計の返済を早く約定させた")
	}
	q = bookTestGain(6, 1, 20)
	q.Time = 4.6
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if r.Unresolved || r.Metrics.NetPnLYen != 7800 || len(r.Orders) != 3 {
		t.Fatal("1秒と境界の独立注文が不正")
	}
	for _, o := range r.Orders {
		if o.Kind == "exit" && o.CancelledQuantity != 0 {
			t.Fatal("受理返済を取消した")
		}
	}
	bookTestCash(t, r)
}

// TestBook81HarvestArithmetic は切上げ、予算不足、1枚、strict等号を別算と比較します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。予定数量又は5pt刻み床が式と異なれば失敗します。
func TestBook81HarvestArithmetic(t *testing.T) {
	for _, row := range []struct {
		q, needed, close int
		u, r             float64
		feasible         bool
	}{{100, 75, 75, 78, 0, true}, {10, 8, 8, 78, 0, true}, {1, 1, 1, 78, 0, true}, {1, 2, 1, .5, 0, false}, {100, 408, 100, 78, -100000, false}} {
		n, qty, ok, err := actualHarvestPlan(row.q, row.u, row.r)
		bookTestNeed(t, err)
		if n != row.needed || qty != row.close || ok != row.feasible {
			t.Fatalf("数量式:%+v -> %d/%d/%v", row, n, qty, ok)
		}
	}
	for _, row := range []struct {
		r, floor float64
		q        int
	}{{5850, 0, 25}, {-1650, 30, 25}, {0, 25, 100}, {22201, 0, 100}, {22200, 5, 100}} {
		floor, err := actualCashFloor(row.r, row.q)
		bookTestNeed(t, err)
		if floor != row.floor {
			t.Fatalf("cash床:%+v -> %g", row, floor)
		}
	}
	if _, _, _, err := actualHarvestPlan(100, 0, 0); err == nil {
		t.Fatal("単価益0で部分利確計画を出した")
	}
	if _, err := actualCashFloor(math.NaN(), 100); err == nil {
		t.Fatal("不明確定益を予算0へ補完した")
	}
	for _, mode := range []string{"B0G0", "B0G1"} {
		b := bookTestOpen(t, mode, 1, 23, true, 0)
		bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 12.2), ReferenceFrame{}, TechnicalView{}))
		if b.Result().Positions[0].Flag || b.Result().Positions[0].WholeFlag || len(b.Result().Orders) != 1 {
			t.Fatal("十進費用後0をstrict正とした")
		}
	}
}

// TestBook81ReferenceCompatibility は不正気配でも既知の比例返済を受理します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。30/35/35の予約又は完結費用が異なれば失敗します。
func TestBook81ReferenceCompatibility(t *testing.T) {
	b := bookTestOpen(t, "B0G1", 1, 23, true, 0)
	for i, c := range []ReferenceClose{{ID: "C1", ReferenceID: "R1", Before: 100, Quantity: 30}, {ID: "C2", ReferenceID: "R1", Before: 70, Quantity: 35}, {ID: "C3", ReferenceID: "R1", Before: 35, Quantity: 35}} {
		q := bookTestGain(int64(i+3), 1, 20)
		q.Valid = false
		bookTestNeed(t, b.OnQuote(q, ReferenceFrame{Closes: []ReferenceClose{c}}, TechnicalView{}))
	}
	r := b.Result()
	if r.Positions[0].ReservedExit != 100 || r.Metrics.EquityYen != nil || r.Metrics.UnpricedExposureQuotes != 3 {
		t.Fatal("不正BBOで予約を止めた又は未知を0にした")
	}
	bookTestNeed(t, b.OnQuote(bookTestGain(6, 1, 20), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Unresolved || r.Metrics.NetPnLYen != 7800 || len(r.Closed) != 3 || r.Metrics.HarvestOrders != 0 || !r.Lots[0].WholeFlag {
		t.Fatal("参照互換の完結又は全玉旗が不正")
	}
	bookTestCash(t, r)
}

// TestBook81ATRKnownAndFailure は既知0・未知と確定足失敗を混同しません。
//
// 引数: tは*testing.Tです。
// 返り値: なし。追尾幅又は未確定の技法失敗を誤れば失敗します。
func TestBook81ATRKnownAndFailure(t *testing.T) {
	if p := bookTestOpen(t, "B0G1", 1, 0, true, 0).Result().Positions[0]; p.D != 15 || p.EntryATR == nil || *p.EntryATR != 0 {
		t.Fatal("既知ATR0の15ptを未知へ変えた")
	}
	if p := bookTestOpen(t, "B0G1", 1, 0, false, 0).Result().Positions[0]; p.D != 125 || p.EntryATR != nil {
		t.Fatal("未知ATRを0として使った")
	}
	for _, guard := range []string{"G0", "G1"} {
		b := bookTestOpen(t, "B1"+guard, 1, 100, true, 0)
		bad := TechnicalView{ExitKnown: true, Bar3End: 3, Close3: 999, EMA8_3: 1000, Histogram3: -2, PreviousHistogram3: -1}
		bookTestNeed(t, b.OnQuote(bookTestGain(3, 1, 20), ReferenceFrame{}, bad))
		if p := b.Result().Positions[0]; p.ReservedExit != 100 || p.HarvestOrderID != "" {
			t.Fatal("共通の技法失敗より部分利確を優先した")
		}
		bookTestNeed(t, b.OnQuote(bookTestGain(4, 1, 20), ReferenceFrame{}, bad))
		if b.Result().Unresolved {
			t.Fatal("技法失敗の後原行返済が完了しない")
		}
	}
}

// TestBook81MirrorAndCopy は売買鏡像と保存値の非共有を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。政策の方向条件又は返り値が内部を変更すれば失敗します。
func TestBook81MirrorAndCopy(t *testing.T) {
	nets := []float64{}
	for _, side := range []int{1, -1} {
		b := bookTestOpen(t, "B0G1", side, 23, true, 0)
		for i, gain := range []float64{20, 20, 70, 45, 40} {
			bookTestNeed(t, b.OnQuote(bookTestGain(int64(i+3), side, gain), ReferenceFrame{}, TechnicalView{}))
		}
		r := b.Result()
		nets = append(nets, r.Metrics.NetPnLYen)
		if r.Unresolved || r.Metrics.HarvestFilledQuantity != 75 || r.Lots[0].Floor != 45 || r.Metrics.ProtectionMissingQuantity != 0 {
			t.Fatal("売買鏡像の予約又は床が不正")
		}
		bookTestCash(t, r)
		r.Lots[0].Floor = -999
		*r.Lots[0].CashFloor = 999
		r.Orders[1].Quantity = 1
		if again := b.Result(); again.Lots[0].Floor != 45 || *again.Lots[0].CashFloor != 0 || again.Orders[1].Quantity != 75 {
			t.Fatal("保存値が内部会計を共有した")
		}
	}
	if nets[0] != 12800 || nets[1] != nets[0] {
		t.Fatalf("方向鏡像の損益:%v", nets)
	}
}

// TestBook81ReservedIdentity は取消済み新規IDと全返済予約の占有を維持します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。取消IDの復活又は返済待ち中の新規を許せば失敗します。
func TestBook81ReservedIdentity(t *testing.T) {
	b, err := NewBook("人工", "B0G1", 100)
	bookTestNeed(t, err)
	q := bookTestQuote(1, 1000, 1005)
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("A", 1), TechnicalView{}))
	bookTestNeed(t, b.Force(1.1, q, "人工の未約定取消"))
	bookTestNeed(t, b.OnGrid(1.2, q, bookTestCandidate("A", 1), TechnicalView{}))
	if r := b.Result(); len(r.Orders) != 1 || r.Orders[0].CancelledQuantity != 100 || r.Decisions[1].Candidates[0].Reason != "同じ定時候補IDへ再入場しない" {
		t.Fatal("取消済み新規の候補IDを復活させた")
	}
	b = bookTestOpen(t, "B0G1", 1, 23, true, 0)
	bookTestNeed(t, b.Force(2, bookTestQuote(2, 1000, 1005), "人工全返済"))
	bookTestNeed(t, b.OnGrid(2.5, bookTestQuote(2, 1000, 1005), bookTestCandidate("B", -1), TechnicalView{}))
	if r := b.Result(); len(r.Orders) != 2 || r.Decisions[1].Action != "保有継続" {
		t.Fatal("返済予約を空き枠として先取りした")
	}
}

// TestBook81EntryStopAndUnknown は新規fill直後の危険と不正気配での予約維持を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。約定前保有を捏造したり不正板を約定に使えば失敗します。
func TestBook81EntryStopAndUnknown(t *testing.T) {
	b, err := NewBook("人工", "B0G1", 100)
	bookTestNeed(t, err)
	q := bookTestQuote(1, 1000, 1005)
	bookTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	bookTestNeed(t, b.OnGrid(1, q, bookTestCandidate("A", 1), TechnicalView{ATRKnown: true, ATR3: 15}))
	bad := bookTestQuote(2, 1000, 1000)
	bookTestNeed(t, b.OnQuote(bad, ReferenceFrame{}, TechnicalView{}))
	if b.Result().Metrics.EntryQuantity != 0 {
		t.Fatal("交差又は同値板で約定した")
	}
	bookTestNeed(t, b.OnQuote(bookTestQuote(3, 1000, 1130), ReferenceFrame{}, TechnicalView{}))
	if p := b.Result().Positions[0]; p.EntryPrice != 1130 || p.ReservedExit != 100 || p.Flag {
		t.Fatal("fill直後の125pt逆行を同じ原行で要求しなかった")
	}
	bad = bookTestQuote(4, 1000, 1000)
	bookTestNeed(t, b.OnQuote(bad, ReferenceFrame{}, TechnicalView{}))
	if r := b.Result(); r.Metrics.ExitQuantity != 0 || r.Positions[0].ReservedExit != 100 || r.Metrics.EquityYen != nil {
		t.Fatal("不正板で返済又は予約解放した")
	}
	bookTestNeed(t, b.OnQuote(bookTestQuote(5, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if r.Unresolved || r.Metrics.NetPnLYen != -142200 || r.Metrics.ProtectionMissingQuantity != 0 {
		t.Fatal("次正常板での危険返済が不正")
	}
	bookTestCash(t, r)
}
