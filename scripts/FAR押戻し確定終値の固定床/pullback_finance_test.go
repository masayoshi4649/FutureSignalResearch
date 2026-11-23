package far90

import (
	"bytes"
	"encoding/json"
	"math"
	"testing"

	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
)

// anchorFinance90 は180秒より古いpを持つ公開済み価格線を合成します。
//
// 引数: t(*testing.T)、at(float64)、reference(ReferenceLot)、price(float64)は検査器・要求時計・候補・固定線です。
// 返り値: PullbackAnchorは手製のイベントと公開記録をBuilderへ渡した値です。原板生成の証明ではありません。
func anchorFinance90(t *testing.T, at float64, reference ReferenceLot, price float64) PullbackAnchor {
	t.Helper()
	point := func(id int64, delta float64) EventPoint {
		return EventPoint{ObservationID: id, BarEnd: at - delta, PublishedAt: at - delta}
	}
	e := ResumeEvent{ID: "人工再開", Side: reference.Side, Window: "D164_15", EpochStart: at - 900,
		Impulse: point(1, 720), Pullback: point(2, 540), Recovery: point(3, 360), Confirmation: point(4, 180)}
	close := price + float64(reference.Side)*10
	record := EventRecord{ID: e.Pullback.ObservationID, Kind: "確定3分", Input: EventInput{Ordinal: 2, At: e.Pullback.PublishedAt, Origin: "three_timer", Window: e.Window, EpochStart: e.EpochStart,
		Quote:     Quote{Time: e.Pullback.PublishedAt, Index: 0, Line: 100, Last: close, Bid: close - 5, Ask: close + 5, Valid: true},
		Technical: TechnicalView{ExitKnown: true, Bar3End: e.Pullback.BarEnd, Close3: close}}}
	a, err := BuildPullbackAnchor(at, reference, e, record)
	need85(t, err)
	return a
}

// sourceRequest90 は一つの候補へS2の要求を作り、要求前の出典も返します。
//
// 引数: t(*testing.T)、side/quantity(int)、delay/atr/floor(float64)は方向・量・遅延・旧ATR・実想定建値からの固定床です。
// 返り値: *Book、ReadSnapshot、PullbackAnchorは未約定要求と凍結出典です。
func sourceRequest90(t *testing.T, side, quantity int, delay, atr, floor float64) (*Book, ReadSnapshot, PullbackAnchor) {
	t.Helper()
	b, err := NewPullbackSourceBook("人工90", "S", 100)
	need85(t, err)
	need85(t, b.SetFillDelay(delay))
	q := quote85(1, 10000, 10010)
	tech := TechnicalView{ATRKnown: true, ATR3: atr}
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
	s := snapshot87(q, side, quantity, "参照玉")
	entry := actualMark(q, -side)
	a := anchorFinance90(t, q.Time, s.Lots[0].Reference, entry+float64(side)*floor)
	need85(t, b.OnSourceGridWithPullback(q.Time, q, s, Decision{}, tech, StructureAnchor{}, map[string]PullbackAnchor{"参照玉": a}))
	return b, s, a
}

// sourceOpen90 は次適格原行で実所有したS2人工を返します。
//
// 引数: t(*testing.T)、side/quantity(int)、delay/atr/floor(float64)はsourceRequest90と同じ条件です。
// 返り値: *Book、ReadSnapshot、PullbackAnchorは非0所有と要求時出典です。
func sourceOpen90(t *testing.T, side, quantity int, delay, atr, floor float64) (*Book, ReadSnapshot, PullbackAnchor) {
	t.Helper()
	b, s, a := sourceRequest90(t, side, quantity, delay, atr, floor)
	need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, TechnicalView{ATRKnown: true, ATR3: atr}))
	if b.Result().Metrics.OpenQuantity != quantity {
		t.Fatal("S2実新規量が違う")
	}
	return b, s, a
}

// TestPullback90Constructors は専用APIの混用と内部ラベル・旧保存schemaを検査します。
//
// 引数: t(*testing.T)はconstructor人工の検査器です。
// 返り値: ありません。旧金融保存tagは増やさずS2だけ専用入口を要求します。
func TestPullback90Constructors(t *testing.T) {
	for _, args := range []struct {
		session, policy string
		cap             int
	}{{"", "S", 100}, {"人工", "SC", 100}, {"人工", "", 100}, {"人工", "S", 99}} {
		if _, err := NewPullbackSourceBook(args.session, args.policy, args.cap); err == nil {
			t.Fatal("不正S2constructorを受理", args)
		}
	}
	b, err := NewPullbackSourceBook("人工90", "S", 100)
	need85(t, err)
	if b.mode != "S2G1" || b.stop != "S2" || b.guard != "G1" || b.sourcePolicy != "S" || b.holdEnabled || b.confirmEnabled || b.SetConfirmEnabled(true) == nil {
		t.Fatal("S2内部条件が違う")
	}
	q := quote85(1, 10000, 10010)
	if b.OnSourceGrid(q.Time, q, ReadSnapshot{}, Decision{}, TechnicalView{}, StructureAnchor{}) == nil {
		t.Fatal("S2へ旧入口を混用")
	}
	old, err := NewSourceBook("人工90", "S", 100)
	need85(t, err)
	if old.OnSourceGridWithPullback(q.Time, q, ReadSnapshot{}, Decision{}, TechnicalView{}, StructureAnchor{}, nil) == nil {
		t.Fatal("対照へS2入口を混用")
	}
	baseline, err := far89.NewSourceBook("人工90", "S", 100)
	need85(t, err)
	a, err := json.Marshal(old.Result())
	need85(t, err)
	c, err := json.Marshal(baseline.Result())
	need85(t, err)
	if !bytes.Equal(a, c) {
		t.Fatal("対照初期全文が旧89と不一致")
	}
}

// TestPullback90OffEveryQuantity は量1..100・売買・両遅延の対照全文を固定89へ直接比較します。
//
// 引数: t(*testing.T)は旧JSONの全field/順序/数値を比較する人工です。
// 返り値: ありません。Source部分比率・正益/G1・Force後もJSONラベルを置換しません。
func TestPullback90OffEveryQuantity(t *testing.T) {
	for quantity := 1; quantity <= 100; quantity++ {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				b, err := NewSourceBook("人工90対照", "S", 100)
				need85(t, err)
				old, err := far89.NewSourceBook("人工90対照", "S", 100)
				need85(t, err)
				need85(t, b.SetFillDelay(delay))
				need85(t, old.SetFillDelay(delay))
				check := func() {
					a, e := json.Marshal(b.Result())
					need85(t, e)
					c, e := json.Marshal(old.Result())
					need85(t, e)
					if !bytes.Equal(a, c) {
						t.Fatal("対照の旧89全文byte差", quantity, side, delay)
					}
				}
				tech := TechnicalView{ATRKnown: true, ATR3: 100}
				q := quote85(1, 10000, 10010)
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
				s := snapshot87(q, side, quantity, "参照玉")
				need85(t, b.OnSourceGrid(q.Time, q, s, Decision{}, tech, StructureAnchor{}))
				need85(t, old.OnSourceGrid(q.Time, q, s, Decision{}, tech, StructureAnchor{}))
				check()
				for i, gain := range []float64{-10, 10, 20, 40, 10, 0} {
					q = gain85(int64(i+2), side, gain)
					frame := ReferenceFrame{}
					if i == 1 {
						frame.Closes = []ReferenceClose{{ID: "源部分", ReferenceID: "参照玉", Before: 100, Quantity: 5}}
					}
					need85(t, b.OnQuote(q, frame, tech))
					need85(t, old.OnQuote(q, frame, tech))
					check()
				}
				need85(t, b.Force(q.Time+0.25, q, "人工Force"))
				need85(t, old.Force(q.Time+0.25, q, "人工Force"))
				check()
				q = gain85(10, side, -20)
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
				check()
			}
		}
	}
}

// TestPullback90Validator は古いpの許可と欠落・未来・異側・式破損の拒否を検査します。
//
// 引数: t(*testing.T)は候補別mapと金融境界の反証検査器です。
// 返り値: ありません。error時は注文・seen・定時を消費しません。
func TestPullback90Validator(t *testing.T) {
	mutations := []struct {
		name string
		edit func(*PullbackAnchor)
	}{
		{"未知", func(a *PullbackAnchor) { a.Known = false }},
		{"種類", func(a *PullbackAnchor) { a.Kind = "EMA" }},
		{"版", func(a *PullbackAnchor) { a.RuleVersion++ }},
		{"要求時計", func(a *PullbackAnchor) { a.At++ }},
		{"参照ID", func(a *PullbackAnchor) { a.ReferenceID = "別玉" }},
		{"側", func(a *PullbackAnchor) { a.Side = -a.Side }},
		{"Event側", func(a *PullbackAnchor) { a.Event.Side = -a.Event.Side }},
		{"EventID", func(a *PullbackAnchor) { a.Event.ID = "" }},
		{"別窓", func(a *PullbackAnchor) { a.Event.Window = "P164_06" }},
		{"epoch未来", func(a *PullbackAnchor) { a.Event.EpochStart = a.At + 1 }},
		{"p未来", func(a *PullbackAnchor) { a.Event.Pullback.PublishedAt = a.At + 1 }},
		{"p公開前", func(a *PullbackAnchor) { a.Event.Pullback.PublishedAt = a.Event.Pullback.BarEnd - 1 }},
		{"p順序", func(a *PullbackAnchor) { a.Event.Pullback.BarEnd = a.Event.Impulse.BarEnd }},
		{"p観測順序", func(a *PullbackAnchor) { a.Event.Pullback.ObservationID = a.Event.Recovery.ObservationID }},
		{"k期限等号", func(a *PullbackAnchor) { a.Event.Confirmation.BarEnd = a.At - 900 }},
		{"r=k点不一致", func(a *PullbackAnchor) { a.Event.Confirmation.BarEnd = a.Event.Recovery.BarEnd }},
		{"ordinal", func(a *PullbackAnchor) { a.PullbackOrdinal = 0 }},
		{"origin", func(a *PullbackAnchor) { a.PullbackOrigin = "未来足" }},
		{"元原行未来Index", func(a *PullbackAnchor) { a.PullbackQuote.Index = 200 }},
		{"元原行未来Line", func(a *PullbackAnchor) { a.PullbackQuote.Line = 200 }},
		{"元原行未来時計", func(a *PullbackAnchor) { a.PullbackQuote.Time = a.At + 1 }},
		{"元Last未知", func(a *PullbackAnchor) { a.PullbackQuote.Last = 0 }},
		{"元BBO非有限", func(a *PullbackAnchor) { a.PullbackQuote.Bid = math.NaN() }},
		{"Close非有限", func(a *PullbackAnchor) { a.Close = math.Inf(1) }},
		{"Close式破損", func(a *PullbackAnchor) { a.Close++ }},
		{"固定線式破損", func(a *PullbackAnchor) { a.Price++ }},
		{"offset", func(a *PullbackAnchor) { a.Tick = 5 }},
		{"理由", func(a *PullbackAnchor) { a.Reason = "固定EMA構造否定" }},
	}
	for _, side := range []int{1, -1} {
		for _, m := range mutations {
			t.Run(m.name+string(rune(side+50)), func(t *testing.T) {
				b, err := NewPullbackSourceBook("人工90", "S", 100)
				need85(t, err)
				q := quote85(1, 10000, 10010)
				need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
				s := snapshot87(q, side, 8, "参照玉")
				a := anchorFinance90(t, q.Time, s.Lots[0].Reference, 9950)
				m.edit(&a)
				if b.OnSourceGridWithPullback(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]PullbackAnchor{"参照玉": a}) == nil || len(b.orders) != 0 || len(b.seen) != 0 || b.haveGrid {
					t.Fatal("破損出典の受理又はerror前の状態消費")
				}
			})
		}
		b, _, a := sourceRequest90(t, side, 8, 0, 100, -50.25)
		if a.At-a.Event.Pullback.BarEnd <= 180 || b.orders[0].StructureAnchor.Price != a.Price {
			t.Fatal("古いp又は非10pt格子を追加gateで除外")
		}
		q := quote85(1, 10000, 10010)
		s := snapshot87(q, side, 8, "参照玉")
		for _, anchors := range []map[string]PullbackAnchor{nil, {"別玉": a}, {"参照玉": a, "別玉": a}} {
			fresh, err := NewPullbackSourceBook("人工90", "S", 100)
			need85(t, err)
			need85(t, fresh.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			if fresh.OnSourceGridWithPullback(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, anchors) == nil {
				t.Fatal("mapのID集合不整合を受理")
			}
		}
	}
}

// TestPullback90VariableLoss は量1..100・売買・両遅延の固定床と次板悪化を手計算へ結びます。
//
// 引数: t(*testing.T)は古いp・要求固定価格・floorの検査器です。
// 返り値: ありません。到達等号を使い、返済価格を固定線へ捏造しません。
func TestPullback90VariableLoss(t *testing.T) {
	for quantity := 1; quantity <= 100; quantity++ {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				b, _, a := sourceOpen90(t, side, quantity, delay, 100, -50)
				need85(t, b.OnQuote(gain85(3, side, -49), ReferenceFrame{}, TechnicalView{}))
				if len(b.orders) != 1 || b.lots["参照玉"].Floor != -50 || b.lots["参照玉"].structureBaseFloor != -100 {
					t.Fatal("非到達・独立旧床が違う")
				}
				need85(t, b.OnQuote(gain85(4, side, -50), ReferenceFrame{}, TechnicalView{}))
				if len(b.orders) != 2 || b.orders[1].Reason != PullbackExitReason || b.orders[1].Remaining != quantity || b.orders[1].RequestIndex != 4 {
					t.Fatal("等号又は2行目以降のS2理由を誤判定")
				}
				need85(t, b.OnQuote(gain85(5, side, -60), ReferenceFrame{}, TechnicalView{}))
				r := b.Result()
				p, c := r.Lots[0], r.Closed[0]
				if r.Unresolved || r.Metrics.NetPnLYen != -722*float64(quantity) || r.Metrics.TotalCostYen != 122*float64(quantity) || r.Metrics.StructureExitOrders != 1 || r.Metrics.StructureHitLots != 1 || p.StructureEntryBreached || p.StructureAnchor.Price != a.Price || c.StructureAnchor != p.StructureAnchor || c.StructureFirstHitIndex != 4 || c.RequestToFillAdverseYen == nil || *c.RequestToFillAdverseYen != 100*float64(quantity) {
					t.Fatal("固定床の次板損失・費用又は不変継承が違う", quantity, side, delay, r)
				}
			}
		}
	}
}

// TestPullback90OldFloorPriority はATR同値・厳しい旧床・G1最低床を守ります。
//
// 引数: t(*testing.T)は売買鏡像の理由優先人工です。
// 返り値: ありません。S2到達とS2が支配した注文を区別します。
func TestPullback90OldFloorPriority(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, tc := range []struct {
			atr, gain float64
			reason    string
		}{{15, -50, "正益前ATR損失追尾"}, {50, -50, "正益前ATR損失追尾"}, {100, -50, PullbackExitReason}, {125, -130, "共通125pt保護"}} {
			b, _, _ := sourceOpen90(t, side, 8, 0, tc.atr, -50)
			need85(t, b.OnQuote(gain85(3, side, tc.gain), ReferenceFrame{}, TechnicalView{}))
			if b.orders[1].Reason != tc.reason || b.metrics.StructureHitLots != 1 {
				t.Fatal("旧床理由の優先が違う", side, tc, b.Result())
			}
		}
		b, _, _ := sourceOpen90(t, side, 100, 0, 100, -50)
		need85(t, b.OnQuote(gain85(3, side, 12.2), ReferenceFrame{}, TechnicalView{}))
		if b.lots["参照玉"].Flag {
			t.Fatal("費用後等号で利益起動")
		}
		need85(t, b.OnQuote(gain85(4, side, 20), ReferenceFrame{}, TechnicalView{}))
		if !b.lots["参照玉"].Flag || b.lots["参照玉"].Floor < 0 || b.orders[1].Quantity != 75 || !b.orders[1].Harvest {
			t.Fatal("G1即起動・75枚部分収穫が変化")
		}
		need85(t, b.OnQuote(gain85(5, side, 20), ReferenceFrame{}, TechnicalView{}))
		p := b.lots["参照玉"]
		if p.Quantity != 25 || p.NetPnL != 5850 || !p.CashFloorActive || p.structureBaseFloor != 0 {
			t.Fatal("部分収穫・旧床の私有追跡が違う", p)
		}
		need85(t, b.OnQuote(gain85(6, side, 0), ReferenceFrame{}, TechnicalView{}))
		if b.orders[2].Reason != "G1確定益予算・ATR追尾" || b.orders[2].Quantity != 25 || b.metrics.StructureExitOrders != 0 {
			t.Fatal("利益床をS2で緩和又は理由を偽装")
		}
	}
}

// TestPullback90EntryBreached は要求時否定を新規gateへせず実取得後に返済を要求します。
//
// 引数: t(*testing.T)は売買・両遅延・不適格板の人工です。
// 返り値: ありません。要求/取得/返済要求/実fillを同一価格へ混同しません。
func TestPullback90EntryBreached(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, _, a := sourceOpen90(t, side, 8, delay, 100, -5)
			p := b.lots["参照玉"]
			if len(b.orders) != 2 || !p.StructureEntryBreached || p.StructureFirstHitIndex != 2 || b.orders[1].RequestIndex != 2 || b.orders[1].Reason != PullbackExitReason || p.StructureAnchor.Price != a.Price {
				t.Fatal("要求時既否定を入口拒否又は同原行fillへ改変")
			}
			q := gain85(3, side, -20)
			q.Time = 1001.5
			if delay == 0 {
				q.Valid = false
			}
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			if b.Result().Metrics.OpenQuantity != 8 {
				t.Fatal("非正常又は1秒未経過で架空返済")
			}
			q = gain85(4, side, -20)
			q.Time = 1002
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			if b.Result().Unresolved || b.Result().Metrics.NetPnLYen != -2576 || b.Result().Metrics.StructureEntryBreachedLots != 1 {
				t.Fatal("取得時否定の返済手計算が違う", b.Result())
			}
		}
	}
}

// TestPullback90SourceAndTechnicalPriority は先行Source・技法失敗と新床の予約競合を確認します。
//
// 引数: t(*testing.T)は買売・両遅延の合成通知です。
// 返り値: ありません。既予約を二重計上せず、先行返済片へ後のhitを遡及しません。
func TestPullback90SourceAndTechnicalPriority(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, _, _ := sourceOpen90(t, side, 8, delay, 100, -50)
			c := ReferenceClose{ID: "源部分", ReferenceID: "参照玉", Before: 8, Quantity: 3}
			need85(t, b.OnQuote(gain85(3, side, -20), ReferenceFrame{Closes: []ReferenceClose{c}}, TechnicalView{}))
			need85(t, b.OnQuote(gain85(4, side, -50), ReferenceFrame{}, TechnicalView{}))
			if len(b.closed) != 1 || b.closed[0].Quantity != 3 || b.closed[0].StructureFirstHitAt != nil || b.orders[2].Quantity != 5 || b.orders[2].Reason != PullbackExitReason || b.lots["参照玉"].StructureFirstHitIndex != 4 {
				t.Fatal("全fill後の初回hit又は未来hitの遡及", b.Result())
			}
			need85(t, b.OnQuote(gain85(5, side, -60), ReferenceFrame{}, TechnicalView{}))
			if b.Result().Unresolved || b.Result().Metrics.NetPnLYen != -5476 || b.closed[1].StructureFirstHitIndex != 4 {
				t.Fatal("Source先行部分＋S2残玉の手計算差", b.Result())
			}
			b, _, _ = sourceOpen90(t, side, 8, delay, 100, -50)
			tech := TechnicalView{ExitKnown: true, Bar3End: 1002, Close3: 10000 - float64(side)*10, EMA8_3: 10000, Histogram3: -float64(side), PreviousHistogram3: 0}
			need85(t, b.OnQuote(gain85(3, side, -50), ReferenceFrame{Closes: []ReferenceClose{c}}, tech))
			if len(b.orders) != 3 || b.orders[1].Quantity != 3 || b.orders[1].Reason != "参照返済:" || b.orders[2].Quantity != 5 || b.orders[2].Reason != "確定3分技法失敗" || b.metrics.StructureExitOrders != 0 || b.Result().Metrics.ReservedExitQuantity != 8 {
				t.Fatal("Source→3分→S2の先行予約順が違う", b.Result())
			}
		}
	}
}

// TestPullback90FinalFillFlag は最終Source返済fillだけで利益が立つ0残量も保存します。
//
// 引数: t(*testing.T)は売買・両遅延の最終fill人工です。
// 返り値: ありません。正常残玉の無い原行へS2hit又はG1収穫を創作しません。
func TestPullback90FinalFillFlag(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, _, _ := sourceOpen90(t, side, 3, delay, 100, -50)
			closes := []ReferenceClose{{ID: "丸め0", ReferenceID: "参照玉", Before: 100, Quantity: 1}, {ID: "全残", ReferenceID: "参照玉", Before: 99, Quantity: 99}}
			need85(t, b.OnQuote(gain85(3, side, 10), ReferenceFrame{Closes: closes}, TechnicalView{}))
			need85(t, b.OnQuote(gain85(4, side, 20), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			p := r.Lots[0]
			if r.Unresolved || !p.Flag || !p.WholeFlag || p.Quantity != 0 || p.FlagIndex != 4 || r.Metrics.HarvestOrders != 0 || r.Metrics.StructureHitLots != 0 || r.SourceEffects[0].ExitRequested != 0 || r.Metrics.NetPnLYen != 234 {
				t.Fatal("0丸め・旗後0残・最終fillの手計算差", r)
			}
			b, _, _ = sourceOpen90(t, side, 3, delay, 100, -50)
			need85(t, b.OnQuote(gain85(3, side, -20), ReferenceFrame{Closes: []ReferenceClose{{ID: "全残", ReferenceID: "参照玉", Before: 3, Quantity: 3}}}, TechnicalView{}))
			need85(t, b.OnQuote(gain85(4, side, -60), ReferenceFrame{}, TechnicalView{}))
			if b.Result().Metrics.StructureHitLots != 0 || b.closed[0].StructureFirstHitAt != nil || b.Result().Unresolved {
				t.Fatal("最終fillだけの接触を正常残玉hitへ補完")
			}
		}
	}
}

// TestPullback90CancelTimerAndImmutable は取消・0丸め・Source比率・timer無fillと価格の不変性を確認します。
//
// 引数: t(*testing.T)は売買・両遅延のSource人工です。
// 返り値: ありません。外mapの変更・取消後量・seenを価格線又は新規へ逆流させません。
func TestPullback90CancelTimerAndImmutable(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, snapshot, a := sourceRequest90(t, side, 32, delay, 100, -50)
			q := quote85(1, 10000, 10010)
			need85(t, b.OnReference(1000.25, q, []ReferenceClose{{ID: "部分取消", ReferenceID: "参照玉", Before: 32, Quantity: 10}}))
			if b.orders[0].Remaining != 22 || b.last != q || b.Result().Metrics.EntryQuantity != 0 {
				t.Fatal("timerの架空fill又は取消比率")
			}
			a.Price += float64(side) * 100
			need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, TechnicalView{}))
			p := b.lots["参照玉"]
			if p.InitialQuantity != 22 || p.SourceEntry.RequestedQuantity != 32 || *p.StructureFloor != -50 {
				t.Fatal("取消後取得・要求量又は外出典変化からの上書き")
			}
			need85(t, b.OnReference(1001.25, b.last, []ReferenceClose{{ID: "丸め0", ReferenceID: "参照玉", Before: 100, Quantity: 1}, {ID: "部分返済", ReferenceID: "参照玉", Before: 22, Quantity: 5}}))
			if b.sourceEffects[1].ExitRequested != 0 || b.sourceEffects[2].ExitRequested != 5 {
				t.Fatal("0丸め又は未予約比率")
			}
			q = quote85(3, 10000, 10010)
			q.Time = 1002.5
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			need85(t, b.Force(1003, q, "人工Force"))
			need85(t, b.OnReference(1003, q, []ReferenceClose{{ID: "源Force", ReferenceID: "参照玉", Before: 17, Quantity: 17}}))
			if b.sourceEffects[3].ExitRequested != 0 || b.Result().Metrics.OpenQuantity != 17 {
				t.Fatal("実Force→源Forceの二重返済又はtimer fill")
			}
			q = quote85(4, 10000, 10010)
			q.Time = 1004
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			if b.Result().Unresolved || b.Result().Metrics.NetPnLYen != -4884 {
				t.Fatal("22枚往復費用の手計算差")
			}
			snapshot.At, snapshot.SourceIndex = q.Time, snapshot.SourceIndex+1
			freshAnchor := anchorFinance90(t, 1015, snapshot.Lots[0].Reference, p.StructureAnchor.Price)
			need85(t, b.OnSourceGridWithPullback(1015, q, snapshot, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]PullbackAnchor{"参照玉": freshAnchor}))
			if len(b.orders) != 3 || !b.decisions[1].Candidates[0].SourceCheck.Seen || b.decisions[1].SourceContext.SelectedID != "" {
				t.Fatal("取消・完結後に同参照IDへ再参加")
			}
			b, snapshot, a = sourceRequest90(t, side, 32, delay, 100, -50)
			q = quote85(1, 10000, 10010)
			need85(t, b.OnReference(1000.25, q, []ReferenceClose{{ID: "全取消", ReferenceID: "参照玉", Before: 32, Quantity: 32}}))
			freshAnchor = anchorFinance90(t, 1015, snapshot.Lots[0].Reference, a.Price)
			need85(t, b.OnSourceGridWithPullback(1015, q, snapshot, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]PullbackAnchor{"参照玉": freshAnchor}))
			if b.Result().Unresolved || len(b.lots) != 0 || len(b.orders) != 1 || b.orders[0].CancelledQuantity != 32 || !b.decisions[1].Candidates[0].SourceCheck.Seen {
				t.Fatal("全取消を実参加へ補完又はseenを解除")
			}
		}
	}
}
