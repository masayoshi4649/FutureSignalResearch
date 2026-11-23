package far80

import (
	"math"
	"testing"
)

// actualTestQuote は価格本文を読まない人工気配を作ります。
//
// 引数: indexはint64の原行、bidとaskはfloat64の気配です。
// 返り値: Quoteは原行と同じ価格秒を持つ正常気配です。
func actualTestQuote(index int64, bid, ask float64) Quote {
	return Quote{Time: float64(index), Index: index, Line: index, Last: (bid + ask) / 2, Bid: bid, Ask: ask, Valid: true}
}

// actualTestSource は人工の生きた参照玉を作ります。
//
// 引数: idはstring、sideとquantityはintです。
// 返り値: ReferenceFrameは一つの参照玉を含みます。
func actualTestSource(id string, side, quantity int) ReferenceFrame {
	return ReferenceFrame{Lots: []ReferenceLot{{ID: id, Side: side, Quantity: quantity, Entry: 1000, At: 0, Method: "人工", Kind: "順行"}}}
}

// actualTestNeed は人工のAPI呼出しが成功したことを検査します。
//
// 引数: tは*testing.T、errはerrorです。
// 返り値: なし。不成功なら当該テストを停止します。
func actualTestNeed(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

// actualTestOpen は定時要求と次正常原行の実新規を人工接続します。
//
// 引数: tは*testing.T、modeはstring、sideとquantityはintです。
// 返り値: *Bookは実所有済みの人工会計です。
func actualTestOpen(t *testing.T, mode string, side, quantity int) *Book {
	t.Helper()
	b, err := NewBook("人工場", mode, 100)
	actualTestNeed(t, err)
	q := actualTestQuote(1, 1000, 1005)
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(1, q, actualTestSource("R1", side, quantity), TechnicalView{ATRKnown: true, ATR3: 23}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(2, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	return b
}

// ----------------------------------------

// TestActualCostFloor は初回正と不足余裕の即要求、次行費用を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。主費用・部分配分・Viewer費用が異なれば失敗します。
func TestActualCostFloor(t *testing.T) {
	b := actualTestOpen(t, "P1", 1, 100)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1025, 1030), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if len(r.Orders) != 2 || r.Positions[0].ReservedExit != 100 || r.Positions[0].D != 25 || !r.Positions[0].Flag || r.Positions[0].Floor != 20 || *r.Orders[1].Floor != 20 {
		t.Fatalf("初回正の即要求:%+v", r)
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1020, 1025), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Unresolved || len(r.Closed) != 1 || r.Closed[0].PnL5 != 2800 || r.Metrics.CashYen != 2800 || r.Metrics.NetPnLYen != 2800 || r.Metrics.TotalCostYen != 12200 || r.Metrics.CommissionYen != 2200 || r.Metrics.SlippageYen != 10000 {
		t.Fatalf("費用又は数量:%+v", r)
	}
	if len(r.Trades) != 2 || r.Trades[0].FeeYen != 6100 || r.Trades[1].FeeYen != 6100 || r.Metrics.ClosedLots != 1 || r.Metrics.WinningLots != 1 {
		t.Fatal("Viewer費用又は完結玉集計")
	}
}

// TestActualFlagLoss は同値赤字と飛越・要求後悪化を区別します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。利益旗を最終黒字として扱えば失敗します。
func TestActualFlagLoss(t *testing.T) {
	b := actualTestOpen(t, "P1", 1, 1)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1020, 1025), ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1005, 1010), ReferenceFrame{}, TechnicalView{}))
	c := b.Result().Closed[0]
	if !c.Flag || !c.NominalFlat || c.PnL5 != -122 || b.Result().Metrics.FlagAfterLossPieces != 1 {
		t.Fatal("名目同値を費用後黒字にした")
	}
	b = actualTestOpen(t, "P1", 1, 1)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1035, 1040), ReferenceFrame{}, TechnicalView{}))
	if b.Result().Positions[0].ReservedExit != 0 {
		t.Fatal("余裕のある旗で即返済した")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1020, 1025), ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(5, 1010, 1015), ReferenceFrame{}, TechnicalView{}))
	c = b.Result().Closed[0]
	if !c.FloorJump || !c.CostLoss || c.PnL5 != -72 || *c.RequestToFillAdverseYen != 100 {
		t.Fatalf("飛越と要求後悪化:%+v", c)
	}
}

// TestActualReservation は不正BBOでの連続参照通知と予約重複を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。未予約数量だけへ比率を適用します。
func TestActualReservation(t *testing.T) {
	b := actualTestOpen(t, "F0", 1, 100)
	for i, c := range []ReferenceClose{{ID: "C1", ReferenceID: "R1", Before: 100, Quantity: 30}, {ID: "C2", ReferenceID: "R1", Before: 70, Quantity: 35}, {ID: "C3", ReferenceID: "R1", Before: 35, Quantity: 35}} {
		q := actualTestQuote(int64(i+3), 1000, 1005)
		q.Valid = false
		actualTestNeed(t, b.OnQuote(q, ReferenceFrame{Closes: []ReferenceClose{c}}, TechnicalView{}))
	}
	r := b.Result()
	if len(r.Orders) != 4 || r.Positions[0].ReservedExit != 100 || r.Metrics.EquityYen != nil || r.Metrics.FloatingYen != nil {
		t.Fatal("不正気配通知又は未知評価")
	}
	if r.Orders[1].Quantity != 30 || r.Orders[2].Quantity != 35 || r.Orders[3].Quantity != 35 {
		t.Fatal("未予約残量比率を誤った")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(6, 1010, 1015), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Metrics.ExitQuantity != 100 || r.Unresolved || len(r.Closed) != 3 {
		t.Fatal("参照通知の全量予約")
	}
	b = actualTestOpen(t, "P1", 1, 100)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1025, 1030), ReferenceFrame{Closes: []ReferenceClose{{ID: "C", ReferenceID: "R1", Before: 100, Quantity: 20}}}, TechnicalView{}))
	r = b.Result()
	if len(r.Orders) != 3 || r.Orders[1].Quantity != 20 || r.Orders[2].Quantity != 80 || r.Positions[0].ReservedExit != 100 {
		t.Fatal("参照返済と独自保護の二重予約")
	}
}

// TestActualPendingAndCap は新規待機の余力拘束と参照減少を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。返済待ちを先取り余力へ使えば失敗します。
func TestActualPendingAndCap(t *testing.T) {
	b, err := NewBook("人工場", "F0", 100)
	actualTestNeed(t, err)
	q := actualTestQuote(1, 1000, 1005)
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	ref := actualTestSource("R1", 1, 100)
	ref.Lots = append(ref.Lots, actualTestSource("R2", 1, 100).Lots...)
	actualTestNeed(t, b.OnGrid(1, q, ref, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(2, q, ref, TechnicalView{}))
	if len(b.Result().Orders) != 1 || b.Result().Metrics.PendingEntryQuantity != 100 {
		t.Fatal("新規待機を片側上限から除外した")
	}
	bad := actualTestQuote(2, 1000, 1005)
	bad.Valid = false
	actualTestNeed(t, b.OnQuote(bad, ReferenceFrame{Closes: []ReferenceClose{{ID: "C1", ReferenceID: "R1", Before: 100, Quantity: 25}}}, TechnicalView{}))
	if b.Result().PendingEntries[0].Remaining != 75 {
		t.Fatal("未約定新規の参照部分減少")
	}
	bad = actualTestQuote(3, 1000, 1005)
	bad.Valid = false
	actualTestNeed(t, b.OnQuote(bad, ReferenceFrame{Closes: []ReferenceClose{{ID: "C2", ReferenceID: "R1", Before: 75, Quantity: 75}}}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(4, actualTestQuote(4, 1000, 1005), actualTestSource("R1", 1, 100), TechnicalView{}))
	if len(b.Result().Trades) != 0 || len(b.Result().Orders) != 1 {
		t.Fatal("取消済み参照IDを再入場した")
	}
	b = actualTestOpen(t, "F0", 1, 100)
	actualTestNeed(t, b.Force(3, actualTestQuote(2, 1000, 1005), "境界"))
	actualTestNeed(t, b.OnGrid(3, actualTestQuote(2, 1000, 1005), actualTestSource("R2", 1, 100), TechnicalView{}))
	if len(b.Result().Orders) != 2 {
		t.Fatal("返済予約を新規余力として先取りした")
	}
}

// TestActualNoCancelAndForce は返済受付後の反発と場末未解消を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。返済取消・同原行の架空返済は許しません。
func TestActualNoCancelAndForce(t *testing.T) {
	b := actualTestOpen(t, "P1", 1, 1)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1020, 1025), ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1100, 1105), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if r.Orders[1].Status != "filled" || *r.Orders[1].FillTime != 4 || r.Orders[1].CancelledQuantity != 0 {
		t.Fatal("反発で受理済み返済を取消した")
	}
	b = actualTestOpen(t, "F0", 1, 10)
	actualTestNeed(t, b.Force(3, actualTestQuote(2, 1000, 1005), "場末"))
	r = b.Result()
	if !r.Unresolved || r.Metrics.ExitQuantity != 0 || len(r.Trades) != 1 || r.Positions[0].ReservedExit != 10 {
		t.Fatal("場末で架空に約定した")
	}
	actualTestNeed(t, b.Force(4, actualTestQuote(2, 1000, 1005), "再通知"))
	if len(b.Result().Orders) != 2 {
		t.Fatal("強制通知で二重返済した")
	}
}

// TestActualProtectionAndFailure は共通125ptと新確定足だけの失敗退出を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。F0へ追加保護を混入させません。
func TestActualProtectionAndFailure(t *testing.T) {
	b := actualTestOpen(t, "F0", 1, 1)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1025, 1030), ReferenceFrame{}, TechnicalView{}))
	if !b.Result().Positions[0].Flag || len(b.Result().Orders) != 1 {
		t.Fatal("F0旗又は追加保護混入")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 880, 885), ReferenceFrame{}, TechnicalView{}))
	if len(b.Result().Orders) != 2 || b.Result().Orders[1].Reason != "共通125pt保護" {
		t.Fatal("125pt等号で保護しない")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(5, 875, 880), ReferenceFrame{}, TechnicalView{}))
	if b.Result().Metrics.WorstFloatingYen != -1422 || b.Result().Metrics.MaxDrawdownYen != 1500 {
		t.Fatal("返済約定直前の最大含み損又はDDを失った")
	}
	b = actualTestOpen(t, "P1", 1, 1)
	v := TechnicalView{ExitKnown: true, Bar3End: 180, Close3: 90, EMA8_3: 100, Histogram3: -2, PreviousHistogram3: -1}
	bad := actualTestQuote(3, 1000, 1005)
	bad.Valid = false
	actualTestNeed(t, b.OnQuote(bad, ReferenceFrame{}, v))
	if len(b.Result().Orders) != 2 || b.Result().Orders[1].Reason != "確定3分技法失敗" {
		t.Fatal("不正BBOで確定足の失敗通知を失った")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1000, 1005), ReferenceFrame{}, v))
	if b.Result().Unresolved || len(b.Result().Closed) != 1 {
		t.Fatal("技法失敗を余分な一行遅延した")
	}
}

// TestActualT1AndStrictThreshold は未知入口の保留と費用後0の等号を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。未知技法又は費用後0を正益へ補完しません。
func TestActualT1AndStrictThreshold(t *testing.T) {
	b, err := NewBook("人工場", "T1", 100)
	actualTestNeed(t, err)
	q := actualTestQuote(1, 1000, 1005)
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(1, q, actualTestSource("R1", 1, 1), TechnicalView{}))
	if len(b.Result().Orders) != 0 {
		t.Fatal("T1の未知入力で実新規した")
	}
	v := TechnicalView{TrendKnown: true, SpikeKnown: true, EMA8_3: 1020, EMA21_3: 1010, EMA8_15: 1020, EMA21_15: 1010}
	actualTestNeed(t, b.OnGrid(2, q, actualTestSource("R1", 1, 1), v))
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1017.2, 1022.2), ReferenceFrame{}, TechnicalView{}))
	if b.Result().Positions[0].Flag {
		t.Fatal("十進の費用後0で利益旗を起動した")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(5, 1017.3, 1022.3), ReferenceFrame{}, TechnicalView{}))
	if !b.Result().Positions[0].Flag || len(b.Result().Orders) != 2 {
		t.Fatal("費用後strict正の即保護")
	}
	b, err = NewBook("人工場", "F0", 100)
	actualTestNeed(t, err)
	q = actualTestQuote(1, 1000, 1005)
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(1, q, actualTestSource("R1", 1, 100), TechnicalView{}))
	actualTestNeed(t, b.Force(1, q, "場末"))
	actualTestNeed(t, b.OnQuote(actualTestQuote(2, 1000, 1005), ReferenceFrame{}, TechnicalView{}))
	if len(b.Result().Trades) != 0 || b.Result().Orders[0].CancelledQuantity != 100 || b.Result().Unresolved {
		t.Fatal("Forceで未約定新規を取消していない")
	}
}

// TestActualReflection は買い売りの費用と保護を同じ人工経路で反射します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。符号反転で純回収が違えば失敗します。
func TestActualReflection(t *testing.T) {
	results := make([]BookResult, 0, 2)
	for _, side := range []int{1, -1} {
		b, err := NewBook("人工場", "P1", 100)
		actualTestNeed(t, err)
		events := []Quote{actualTestQuote(1, 1000, 1005), actualTestQuote(2, 1000, 1005), actualTestQuote(3, 1035, 1040), actualTestQuote(4, 1020, 1025), actualTestQuote(5, 1010, 1015)}
		for i, q := range events {
			if side < 0 {
				q.Last = 3000 - q.Last
				q.Bid, q.Ask = 3000-q.Ask, 3000-q.Bid
			}
			actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			if i == 0 {
				actualTestNeed(t, b.OnGrid(q.Time, q, actualTestSource("R1", side, 3), TechnicalView{ATRKnown: true, ATR3: 23}))
			}
		}
		results = append(results, b.Result())
	}
	a, z := results[0], results[1]
	if a.Metrics.NetPnLYen != z.Metrics.NetPnLYen || a.Metrics.TotalCostYen != z.Metrics.TotalCostYen || a.Metrics.MaxDrawdownYen != z.Metrics.MaxDrawdownYen || a.Closed[0].FloorJump != z.Closed[0].FloorJump {
		t.Fatal("実会計の売買鏡像")
	}
}

// TestActualDelayFreshnessAndCopies は時刻境界・遅延と保存値の非共有を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。未知を0補完又は保存値を内部へ共有すれば失敗します。
func TestActualDelayFreshnessAndCopies(t *testing.T) {
	b, err := NewBook("人工場", "P1", 100)
	actualTestNeed(t, err)
	actualTestNeed(t, b.SetFillDelay(1))
	q := actualTestQuote(1, 1000, 1005)
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(1, q, actualTestSource("R1", 1, 1), TechnicalView{}))
	q = actualTestQuote(2, 1000, 1005)
	q.Time = 1
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	if len(b.Result().Trades) != 0 {
		t.Fatal("1秒感応を同時計で約定した")
	}
	q = actualTestQuote(3, 1000, 1005)
	q.Time = 2
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if r.Positions[0].D != 125 || r.Positions[0].EntryATR != nil {
		t.Fatal("未知ATRを0へ補完した")
	}
	r.Positions[0].D = 1
	r.Orders[0].Source.ID = "改変"
	*r.Metrics.EquityYen = 999
	if b.Result().Positions[0].D != 125 || b.Result().Orders[0].Source.ID != "R1" || *b.Result().Metrics.EquityYen == 999 {
		t.Fatal("Resultから内部状態を改変した")
	}
	actualTestNeed(t, b.OnGrid(18, q, actualTestSource("R2", 1, 1), TechnicalView{}))
	if b.Result().Decisions[1].Action != "判定不能" {
		t.Fatal("16秒古い気配で実新規した")
	}
	if b.SetFillDelay(0) == nil || b.OnGrid(math.NaN(), q, ReferenceFrame{}, TechnicalView{}) == nil {
		t.Fatal("不正又は事後変更を許した")
	}
	for _, atr := range []float64{0, 200} {
		x, err := NewBook("人工場", "P1", 100)
		actualTestNeed(t, err)
		q := actualTestQuote(1, 1000, 1005)
		actualTestNeed(t, x.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		actualTestNeed(t, x.OnGrid(1, q, actualTestSource("R1", 1, 1), TechnicalView{ATRKnown: true, ATR3: atr}))
		want := 15.0
		if atr > 125 {
			want = 125
		}
		if x.Result().Orders[0].D != want || x.Result().Orders[0].ATR == nil {
			t.Fatal("既知ATR0又は上限の区別")
		}
	}
}

// TestActualIndependentCash は部分返済の数量と現金をViewer約定片だけから別算します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。部分費用・同約定0/5/10感応・全完結玉を照合します。
func TestActualIndependentCash(t *testing.T) {
	b := actualTestOpen(t, "F0", 1, 100)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1020, 1025), ReferenceFrame{Closes: []ReferenceClose{{ID: "C1", ReferenceID: "R1", Before: 100, Quantity: 30}}}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1030, 1035), ReferenceFrame{Closes: []ReferenceClose{{ID: "C2", ReferenceID: "R1", Before: 70, Quantity: 35}}}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(5, 990, 995), ReferenceFrame{Closes: []ReferenceClose{{ID: "C3", ReferenceID: "R1", Before: 35, Quantity: 35}}}, TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(6, 1005, 1010), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	quantity, entries, exits := 0, 0, 0
	cash, gross, fees := 0.0, 0.0, 0.0
	entryPrice := 0.0
	for _, tr := range r.Trades {
		fees += tr.FeeYen
		cash -= tr.FeeYen
		if tr.Type == "LongN" {
			quantity += tr.Quantity
			entries += tr.Quantity
			entryPrice = tr.Price
		} else if tr.Type == "LongR" {
			quantity -= tr.Quantity
			exits += tr.Quantity
			g := (tr.Price - entryPrice) * 10 * float64(tr.Quantity)
			gross += g
			cash += g
		} else {
			t.Fatal("想定外の約定種別")
		}
		if tr.FeeYen != 61*float64(tr.Quantity) {
			t.Fatal("約定片の費用が枚数に比例しない")
		}
	}
	if quantity != 0 || entries != 100 || exits != 100 || cash != -9950 || cash != r.Metrics.CashYen || fees != 12200 || gross != 2250 {
		t.Fatalf("独立数量現金:%+v", r.Metrics)
	}
	var p0, p5, p10 float64
	for _, c := range r.Closed {
		p0 += c.PnL0
		p5 += c.PnL5
		p10 += c.PnL10
		if c.Commission != 22*float64(c.Quantity) || c.Slippage != 100*float64(c.Quantity) {
			t.Fatal("部分返済の往復費用按分")
		}
	}
	if p0 != 50 || p5 != -9950 || p10 != -19950 || p5 != cash || p0-p5 != 10000 || p5-p10 != 10000 {
		t.Fatal("同約定の費用感応")
	}
	if len(r.Lots) != 1 || r.Lots[0].Quantity != 0 || r.Lots[0].ClosedQuantity != 100 || r.Lots[0].NetPnL != cash || r.Lots[0].FlagMark == nil || len(r.Positions) != 0 || r.Metrics.ClosedLots != 1 || r.Metrics.LosingLots != 1 || r.Metrics.MinEquityYen != -17200 || r.Metrics.MaxDrawdownYen != 28000 || r.Metrics.WorstFloatingYen != -19040 {
		t.Fatalf("全完結玉又は実経路:%+v", r)
	}
}

// TestActualFillRowAndPending は新規約定直後の共通保護と返済待ちの凍結を検査します。
//
// 引数: tは*testing.Tです。
// 返り値: なし。余分な原行遅延、二重予約、返済取消を防ぎます。
func TestActualFillRowAndPending(t *testing.T) {
	b, err := NewBook("人工場", "P1", 100)
	actualTestNeed(t, err)
	q := actualTestQuote(1, 1000, 1005)
	actualTestNeed(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	actualTestNeed(t, b.OnGrid(1, q, actualTestSource("R1", 1, 10), TechnicalView{}))
	actualTestNeed(t, b.OnQuote(actualTestQuote(2, 1000, 1200), ReferenceFrame{}, TechnicalView{}))
	r := b.Result()
	if len(r.Orders) != 2 || r.Orders[1].RequestIndex != 2 || r.Positions[0].ReservedExit != 10 || r.Positions[0].Flag {
		t.Fatal("entryfill当行の共通保護又は不可能な正益旗")
	}
	b = actualTestOpen(t, "P1", 1, 10)
	actualTestNeed(t, b.OnQuote(actualTestQuote(3, 1020, 1025), ReferenceFrame{Closes: []ReferenceClose{{ID: "C", ReferenceID: "R1", Before: 10, Quantity: 10}}}, TechnicalView{}))
	r = b.Result()
	if len(r.Orders) != 2 || !r.Positions[0].Flag || r.Positions[0].ReservedExit != 10 || r.Positions[0].Floor != -125 {
		t.Fatal("参照全返済待ちの二重予約又は保護状態変更")
	}
	actualTestNeed(t, b.OnQuote(actualTestQuote(4, 1005, 1010), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Unresolved || r.Orders[1].CancelledQuantity != 0 || r.Closed[0].PnL5 != -1220 || r.Closed[0].FlagMark == nil {
		t.Fatal("受理後の取消又は利益旗根拠喪失")
	}
}
