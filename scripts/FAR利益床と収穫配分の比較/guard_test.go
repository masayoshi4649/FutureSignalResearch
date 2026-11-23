package far89

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// emptyAllocation89 はG2の収穫/cash欄が旧型の空値を保つことを全階層で確認します。
//
// 引数: t(*testing.T)、value(any)は検査器とJSON保存値です。
// 返り値: ありません。cash_yen等の実会計額は空欄検査の対象外です。
func emptyAllocation89(t *testing.T, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	need85(t, err)
	var root any
	need85(t, json.Unmarshal(data, &root))
	var visit func(any)
	visit = func(value any) {
		switch v := value.(type) {
		case map[string]any:
			for key, item := range v {
				if strings.HasPrefix(key, "harvest") || strings.HasPrefix(key, "cash_floor") || strings.HasPrefix(key, "funding_fail") {
					if item != nil && item != false && item != "" && item != float64(0) {
						t.Fatalf("G2へ収穫/cash欄が混入:%s=%v", key, item)
					}
				}
				visit(item)
			}
		case []any:
			for _, item := range v {
				visit(item)
			}
		}
	}
	visit(root)
}

// equalG189 はG1の全保存byteを別の固定87会計と直接照合します。
//
// 引数: t(*testing.T)、got(BookResult)、old(far87.BookResult)は同入力の両会計です。
// 返り値: ありません。投影・ラベル置換・配列整列は行いません。
func equalG189(t *testing.T, got BookResult, old far87.BookResult) {
	t.Helper()
	a, e := json.Marshal(got)
	need85(t, e)
	b, e := json.Marshal(old)
	need85(t, e)
	if !bytes.Equal(a, b) {
		t.Fatal("G1旧87全文byte差")
	}
}

// openGuard89 は量と遅延を補正せず要求し、両遅延で次の原行取得を作ります。
//
// 引数: t(*testing.T)、guard(string)、side/quantity(int)、delay(float64)は人工条件です。
// 返り値: *BookとReadSnapshotは非0実玉と要求時Source出典です。
func openGuard89(t *testing.T, guard string, side, quantity int, delay float64) (*Book, ReadSnapshot) {
	t.Helper()
	b, e := NewSourceGuardBook("人工89", "S", guard, 100)
	need85(t, e)
	need85(t, b.SetFillDelay(delay))
	q := quote85(1, 10000, 10010)
	tech := TechnicalView{ATRKnown: true, ATR3: 100}
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
	snapshot := snapshot87(q, side, quantity, "参照玉")
	need85(t, b.OnSourceGrid(q.Time, q, snapshot, Decision{}, tech, StructureAnchor{}))
	need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, tech))
	if b.Result().Metrics.OpenQuantity != quantity {
		t.Fatal("量又はD0/D1取得が違う")
	}
	return b, snapshot
}

// TestGuard89Constructors はG1旧互換・G2内部名・不正政策を検査します。
//
// 引数: t(*testing.T)は新constructorの人工です。
// 返り値: ありません。Source API混用と保護の再有効化も拒否します。
func TestGuard89Constructors(t *testing.T) {
	for _, guard := range []string{"G1", "G2"} {
		b, e := NewSourceGuardBook("人工89", "S", guard, 100)
		need85(t, e)
		r := b.Result()
		if r.Mode != "S0"+guard || r.SourcePolicy != "S" || r.HoldEnabled || r.ConfirmEnabled || b.SetConfirmEnabled(true) == nil {
			t.Fatal("内部政策又は非活性保護が違う", r)
		}
		if b.OnGrid(1000, quote85(1, 10000, 10010), ReferenceFrame{}, TechnicalView{}, StructureAnchor{}, HoldAnchor{}, CurrentEvidence{}) == nil {
			t.Fatal("Source/旧直接API混用")
		}
	}
	for _, args := range []struct {
		session, policy, guard string
		cap                    int
	}{{"", "S", "G2", 100}, {"人工", "S", "G0", 100}, {"人工", "不正", "G2", 100}, {"人工", "S", "G2", 99}, {"人工", "S", "", 100}} {
		if _, e := NewSourceGuardBook(args.session, args.policy, args.guard, args.cap); e == nil {
			t.Fatal("不正constructorを受理", args)
		}
	}
	a, e := NewSourceBook("人工89", "S", 100)
	need85(t, e)
	b, e := far87.NewSourceBook("人工89", "S", 100)
	need85(t, e)
	equalG189(t, a.Result(), b.Result())
}

// TestGuard89AllVariableQuantities は1..100枚・売買・両遅延で旧G1全文とG2を検査します。
//
// 引数: t(*testing.T)は合成原行だけを使う人工検査器です。
// 返り値: ありません。G2の最低床・非緩和ATR・費用・全量完結を手計算へ結びます。
func TestGuard89AllVariableQuantities(t *testing.T) {
	for quantity := 1; quantity <= 100; quantity++ {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				g1, snapshot := openGuard89(t, "G1", side, quantity, delay)
				g2, _ := openGuard89(t, "G2", side, quantity, delay)
				old, e := far87.NewSourceBook("人工89", "S", 100)
				need85(t, e)
				need85(t, old.SetFillDelay(delay))
				tech := TechnicalView{ATRKnown: true, ATR3: 100}
				q := quote85(1, 10000, 10010)
				need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
				need85(t, old.OnSourceGrid(q.Time, q, snapshot, Decision{}, tech, StructureAnchor{}))
				need85(t, old.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, tech))
				equalG189(t, g1.Result(), old.Result())
				floor := -125.0
				for i, gain := range []float64{10, 20, 20, 180, 90, 80, 80} {
					q = gain85(int64(i+3), side, gain)
					need85(t, g1.OnQuote(q, ReferenceFrame{}, tech))
					need85(t, g2.OnQuote(q, ReferenceFrame{}, tech))
					need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
					equalG189(t, g1.Result(), old.Result())
					r := g2.Result()
					p := r.Lots[0]
					if p.Floor < floor {
						t.Fatal("G2床を緩和", quantity, side, delay)
					}
					floor = p.Floor
					if i == 0 && (p.Flag || p.WholeFlag || len(r.Orders) != 1) {
						t.Fatal("+10ptを費用後正益へ補完")
					}
					if i == 1 && (!p.Flag || !p.WholeFlag || p.Floor < 0 || len(r.Orders) != 1 || p.Quantity != quantity) {
						t.Fatal("G2の即建値保護又は全量継続が違う", r)
					}
					emptyAllocation89(t, r)
				}
				r := g2.Result()
				if r.Unresolved || r.Metrics.NetPnLYen != 678*float64(quantity) || r.Metrics.EntryQuantity != quantity || r.Metrics.TotalCostYen != 122*float64(quantity) || len(r.Orders) != 2 || r.Orders[1].Reason != "G2全量建値床・ATR追尾" || r.Orders[1].Quantity != quantity {
					t.Fatal("G2全量ATRの人工手計算差", quantity, side, delay, r)
				}
				for _, trade := range r.Trades {
					if trade.MethodID != "S0G2" {
						t.Fatal("G2表示名偽装", trade)
					}
				}
				last := q
				snapshot.At = last.Time
				snapshot.SourceIndex++
				need85(t, g2.OnSourceGrid(1015, last, snapshot, Decision{}, tech, StructureAnchor{}))
				if len(g2.Result().Orders) != 2 || !g2.Result().Decisions[1].Candidates[0].SourceCheck.Seen {
					t.Fatal("G2利益退出後のseen再利用")
				}
			}
		}
	}
}

// TestGuard89StrictPositive は費用控除後の等号とstrict正の原行を区別します。
//
// 引数: t(*testing.T)は小数価格も持つ人工です。
// 返り値: ありません。12.2ptの純益0では起動せず、わずかな正益では床0を起動します。
func TestGuard89StrictPositive(t *testing.T) {
	for _, guard := range []string{"G1", "G2"} {
		for _, side := range []int{1, -1} {
			b, _ := openGuard89(t, guard, side, 2, 0)
			need85(t, b.OnQuote(gain85(3, side, 12.2), ReferenceFrame{}, TechnicalView{}))
			if b.Result().Lots[0].Flag {
				t.Fatal("費用後0を正益とした", guard, side)
			}
			need85(t, b.OnQuote(gain85(4, side, 12.2001), ReferenceFrame{}, TechnicalView{}))
			p := b.Result().Lots[0]
			if !p.Flag || p.FlagIndex != 4 || p.Floor < 0 {
				t.Fatal("strict正益の最低床が遅延", guard, side, p)
			}
			if guard == "G2" {
				emptyAllocation89(t, b.Result())
			}
		}
	}
}

// TestGuard89SourcePriorityZeroAndFlagClosed はSource先行予約・0丸め・旗後残0を確認します。
//
// 引数: t(*testing.T)は売買・両遅延・両guardの人工です。
// 返り値: ありません。全Source返済済の原行でも初回旗を削除しません。
func TestGuard89SourcePriorityZeroAndFlagClosed(t *testing.T) {
	for _, guard := range []string{"G1", "G2"} {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				b, _ := openGuard89(t, guard, side, 3, delay)
				q := gain85(3, side, 10)
				closes := []ReferenceClose{{ID: "0丸め", ReferenceID: "参照玉", Before: 100, Quantity: 1}, {ID: "全残", ReferenceID: "参照玉", Before: 99, Quantity: 99}}
				need85(t, b.OnQuote(q, ReferenceFrame{Closes: closes}, TechnicalView{}))
				r := b.Result()
				if len(r.SourceEffects) != 2 || r.SourceEffects[0].ExitRequested != 0 || r.SourceEffects[1].ExitRequested != 3 || r.Metrics.HarvestOrders != 0 || r.Metrics.ReservedExitQuantity != 3 {
					t.Fatal("Source丸め/全残/先行予約が違う", guard, side, delay, r)
				}
				need85(t, b.OnQuote(gain85(4, side, 20), ReferenceFrame{}, TechnicalView{}))
				r = b.Result()
				p := r.Lots[0]
				if r.Unresolved || p.Quantity != 0 || !p.Flag || !p.WholeFlag || p.FlagIndex != 4 || p.WholeFlagIndex != 4 || r.Metrics.NetPnLYen != 234 || r.Metrics.HarvestOrders != 0 {
					t.Fatal("同原行最終fill/旗後0残の喪失", guard, side, delay, r)
				}
				if guard == "G2" {
					emptyAllocation89(t, r)
				}
			}
		}
	}
}

// TestGuard89TimerCancelAndRatio は取消後取得/整数比率/Force無fillとseenを共通検査します。
//
// 引数: t(*testing.T)は両guard・売買・両遅延の人工です。
// 返り値: ありません。出典要求32・実取得22を保持し、全残へ比率を写します。
func TestGuard89TimerCancelAndRatio(t *testing.T) {
	for _, guard := range []string{"G1", "G2"} {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				b, e := NewSourceGuardBook("人工89", "S", guard, 100)
				need85(t, e)
				need85(t, b.SetFillDelay(delay))
				q := quote85(1, 10000, 10010)
				tech := TechnicalView{ATRKnown: true, ATR3: 100}
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				snapshot := snapshot87(q, side, 32, "参照玉")
				need85(t, b.OnSourceGrid(q.Time, q, snapshot, Decision{}, tech, StructureAnchor{}))
				need85(t, b.OnReference(1000.25, q, []ReferenceClose{{ID: "部分取消", ReferenceID: "参照玉", Before: 32, Quantity: 10}}))
				if b.Result().Metrics.EntryQuantity != 0 || b.Result().Orders[0].Remaining != 22 || b.last != q {
					t.Fatal("timerで架空取得又はlast更新")
				}
				q = quote85(2, 10000, 10010)
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				if b.Result().Lots[0].InitialQuantity != 22 || b.Result().Lots[0].SourceEntry.RequestedQuantity != 32 {
					t.Fatal("要求量と取消後取得を混同")
				}
				need85(t, b.OnReference(1001.25, q, []ReferenceClose{{ID: "部分返済", ReferenceID: "参照玉", Before: 22, Quantity: 5}}))
				if b.Result().SourceEffects[1].ExitRequested != 5 || b.Result().Orders[1].RequestTime != 1001.25 {
					t.Fatal("timer比率と要求時計が違う")
				}
				q = quote85(3, 10000, 10010)
				q.Time = 1002.5
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				if b.Result().Metrics.OpenQuantity != 17 {
					t.Fatal("次適格板の部分fillが違う")
				}
				need85(t, b.Force(1003, q, "人工Force"))
				need85(t, b.OnReference(1003, q, []ReferenceClose{{ID: "源Force", ReferenceID: "参照玉", Before: 17, Quantity: 17}}))
				if b.Result().SourceEffects[2].ExitRequested != 0 || b.Result().Metrics.OpenQuantity != 17 {
					t.Fatal("実Forceの予約を源Forceで二重化又はtimer約定")
				}
				q = quote85(4, 10000, 10010)
				q.Time = 1004
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				if b.Result().Unresolved || b.Result().Metrics.NetPnLYen != -4884 {
					t.Fatal("22枚平値往復費用の差", guard, side, delay, b.Result())
				}
				snapshot.At = q.Time
				snapshot.SourceIndex++
				need85(t, b.OnSourceGrid(1015, q, snapshot, Decision{}, tech, StructureAnchor{}))
				if !b.Result().Decisions[1].Candidates[0].SourceCheck.Seen || len(b.Result().Orders) != 3 {
					t.Fatal("取消後のseenが変化")
				}
			}
		}
	}
}

// TestGuard89FixedLossAndTechnical はG2でも125/ATR/確定3分失敗を維持します。
//
// 引数: t(*testing.T)は損失と技法失敗の鏡像人工です。
// 返り値: ありません。G2を保護なし又は利確だけの会計にしません。
func TestGuard89FixedLossAndTechnical(t *testing.T) {
	for _, guard := range []string{"G1", "G2"} {
		for _, side := range []int{1, -1} {
			b, _ := openGuard89(t, guard, side, 10, 0)
			need85(t, b.OnQuote(gain85(3, side, -130), ReferenceFrame{}, TechnicalView{}))
			if len(b.Result().Orders) != 2 || b.Result().Orders[1].Quantity != 10 {
				t.Fatal("大幅逆行の保護が消失")
			}
			need85(t, b.OnQuote(gain85(4, side, -140), ReferenceFrame{}, TechnicalView{}))
			if b.Result().Unresolved || b.Result().Metrics.NetPnLYen != -15220 {
				t.Fatal("損失約定/費用の差")
			}
			b, _ = openGuard89(t, guard, side, 10, 0)
			tech := TechnicalView{ExitKnown: true, Bar3End: 1002, Close3: 10000 - float64(side)*10, EMA8_3: 10000, Histogram3: -float64(side), PreviousHistogram3: 0}
			need85(t, b.OnQuote(gain85(3, side, 20), ReferenceFrame{}, tech))
			r := b.Result()
			if r.Orders[1].Reason != "確定3分技法失敗" || r.Orders[1].Quantity != 10 || r.Metrics.HarvestOrders != 0 {
				t.Fatal("全返済の後に収穫を二重予約", guard, side, r)
			}
			if guard == "G2" {
				emptyAllocation89(t, r)
			}
		}
	}
}
