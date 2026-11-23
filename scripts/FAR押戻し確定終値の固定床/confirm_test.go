// 90派生元: scripts/FAR利益床と収穫配分の比較/confirm_test.go
// 90派生元SHA256: 51637806e5957940ac7430d834b18a85bfbd33265649d5f87b6710ad40ccdca0
// 固定89は変更せず、G1対照全文と押戻し確定終値の固定床を別会計で比較します。

// 89派生元: scripts/FAR参照玉と可変数量の比較/confirm_test.go
// 89派生元SHA256: 73b9136393debdbe0db46300bcd56dd5e096b706ca5e10d7b207794b5976a278
// 固定87は変更せず、G1旧全文とG2既存分岐を別会計で比較します。

// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/confirm_test.go
// 87派生元SHA256: bb17a04eac48153fa4295f2433881b37215a1a353464266f1899bbc017a5c771

package far90

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"

	far85 "github.com/masayoshi4649/SessionTradeExecuter/research85"
)

// current86 は原行出典と実秒単位が整合する手製短秒値を作ります。
//
// 引数: q(Quote)、side(int)、v5/v15(float64)、k5/k15(bool)は当原行・方向・速度・既知性です。
// 返り値: CurrentEvidenceは金融境界用人工です。源チャート・短秒履歴を再現したとの意味ではありません。
func current86(q Quote, side int, v5, v15 float64, k5, k15 bool) CurrentEvidence {
	c := evidence85(q, side)
	c.SourceIndex = 70 + q.Index
	c.Short = CurrentShort{Time: q.Time, Mid: q.Bid + (q.Ask-q.Bid)/2,
		Five:    CurrentShortWindow{Known: k5, Move: v5 * 5, Speed: v5, Elapsed: 5, Endpoint: q.Time - 5, Reason: "既知"},
		Fifteen: CurrentShortWindow{Known: k15, Move: v15 * 15, Speed: v15, Elapsed: 15, Endpoint: q.Time - 15, Reason: "既知"}}
	if !k5 {
		c.Short.Five = CurrentShortWindow{Reason: "過去端不足"}
	}
	if !k15 {
		c.Short.Fifteen = CurrentShortWindow{Reason: "窓内欠測又は価格時計空白"}
	}
	return c
}

// openConfirm86 は固定帯を要求し、次正常原行で非0所有を作ります。
//
// 引数: t(*testing.T)、side(int)、enabled(bool)、atr/delay(float64)は人工条件です。
// 返り値: *Bookは複合確認だけの新会計、HoldAnchorは不変の要求時出典です。
func openConfirm86(t *testing.T, side int, enabled bool, atr, delay float64) (*Book, HoldAnchor) {
	t.Helper()
	b, err := NewBook("人工86", "S0G1", 100, false)
	need85(t, err)
	need85(t, b.SetConfirmEnabled(enabled))
	need85(t, b.SetFillDelay(delay))
	q := quote85(1, 10000, 10010)
	c := evidence85(q, side)
	a, err := BuildHoldAnchor(q.Time, q, c, side)
	need85(t, err)
	tech := TechnicalView{ATRKnown: true, ATR3: atr}
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech, nil))
	need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, StructureAnchor{}, a, c))
	q = quote85(2, 10000, 10010)
	c = current86(q, side, 0, 0, true, true)
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
	if b.Result().Metrics.OpenQuantity != 100 {
		t.Fatal("人工非0所有がありません")
	}
	return b, a
}

// projectConfirm86 は宣言したconfirm追加欄だけを除き85全金融を比較可能にします。
//
// 引数: value(any)は新旧BookResultです。
// 返り値: map[string]anyは旧全値・順序・hold欄を保つJSON投影です。
func projectConfirm86(value any) map[string]any {
	raw, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	var out map[string]any
	if err = json.Unmarshal(raw, &out); err != nil {
		panic(err)
	}
	stripSource87(out)
	delete(out, "confirm_enabled")
	for _, field := range []string{"orders", "pending_entries", "lots", "positions", "closed"} {
		for _, item := range out[field].([]any) {
			row := item.(map[string]any)
			for _, name := range []string{"confirm_counts", "confirm_first_price_breach", "confirm_first_unknown", "confirm_first_confirmed", "confirm_evidence", "confirm_request_evidence"} {
				delete(row, name)
			}
		}
	}
	for _, name := range []string{"confirm_counts", "confirm_confirmed_lots", "confirm_exit_orders", "confirm_exit_obligations", "confirm_missing_quantity"} {
		delete(out["metrics"].(map[string]any), name)
	}
	return out
}

// assertCounts86 は全玉と会計の確認5群が正常原行数へ一致することを検査します。
//
// 引数: t(*testing.T)、result(BookResult)は人工検査と保存会計です。
// 返り値: ありません。群・玉・全体・要求の不足があれば失敗します。
func assertCounts86(t *testing.T, result BookResult) {
	t.Helper()
	total := ConfirmCounts{}
	for _, lot := range result.Lots {
		c := lot.ConfirmCounts
		if c.NormalQuotes != c.PriceNotBreachedShortKnown+c.PriceNotBreachedShortUnknown+c.PriceBreachedShortUnknown+c.PriceBreachedNotOpposed+c.Confirmed {
			t.Fatal("5群の和が正常原行数と不一致", c)
		}
		total.NormalQuotes += c.NormalQuotes
		total.PriceNotBreachedShortKnown += c.PriceNotBreachedShortKnown
		total.PriceNotBreachedShortUnknown += c.PriceNotBreachedShortUnknown
		total.PriceBreachedShortUnknown += c.PriceBreachedShortUnknown
		total.PriceBreachedNotOpposed += c.PriceBreachedNotOpposed
		total.Confirmed += c.Confirmed
	}
	if total != result.Metrics.ConfirmCounts || result.Metrics.ConfirmMissingQuantity != 0 || result.Metrics.ProtectionMissingQuantity != 0 {
		t.Fatal("玉と会計の群又は全返済義務が不整合", result.Metrics)
	}
}

// TestConfirm86API は旧0引数互換・設定時点・併用禁止・引数数を検査します。
//
// 引数: t(*testing.T)は市場なしの人工検査です。
// 返り値: ありません。稼働後変更・併用・J1特徴省略を認めれば失敗します。
func TestConfirm86API(t *testing.T) {
	b, err := NewBook("人工86", "S0G1", 100, true)
	need85(t, err)
	if b.SetConfirmEnabled(true) == nil || b.confirmEnabled {
		t.Fatal("旧固定床との併用を受理")
	}
	b, err = NewBook("人工86", "S0G1", 100, false)
	need85(t, err)
	need85(t, b.SetConfirmEnabled(true))
	q := quote85(1, 10000, 10010)
	if b.OnQuote(q, ReferenceFrame{}, TechnicalView{}) == nil {
		t.Fatal("J1で特徴引数を省略")
	}
	if b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, nil, nil) == nil {
		t.Fatal("特徴2引数を受理")
	}
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, nil))
	if b.SetConfirmEnabled(false) == nil || !b.confirmEnabled {
		t.Fatal("最初のQuote後に変更")
	}
	b, err = NewBook("人工86", "S0G1", 100, false)
	need85(t, err)
	a, err := BuildHoldAnchor(q.Time, q, CurrentEvidence{}, 0)
	need85(t, err)
	need85(t, b.OnGrid(q.Time, q, ReferenceFrame{}, TechnicalView{}, StructureAnchor{}, a, CurrentEvidence{}))
	if b.SetConfirmEnabled(true) == nil {
		t.Fatal("最初のGrid後に変更")
	}
}

// TestConfirm86ConditionAndMirror は価格AND・厳密速度符号・未知・売買鏡像を確認します。
//
// 引数: t(*testing.T)は手製原行・短秒の人工検査です。
// 返り値: ありません。片側・0速度・片窓未知を確認へ昇格すれば失敗します。
func TestConfirm86ConditionAndMirror(t *testing.T) {
	cases := []struct {
		name                         string
		v5, v15                      float64
		k5, k15, oneQuote, confirmed bool
	}{
		{"両反対", -1, -2, true, true, false, true},
		{"短期0", 0, -1, true, true, false, false},
		{"中期0", -1, 0, true, true, false, false},
		{"短期支持", 1, -1, true, true, false, false},
		{"中期支持", -1, 1, true, true, false, false},
		{"短期未知", -1, -1, false, true, false, false},
		{"中期未知", -1, -1, true, false, false, false},
		{"両未知", -1, -1, false, false, false, false},
		{"片側だけ", -1, -1, true, true, true, false},
	}
	for _, test := range cases {
		for _, side := range []int{1, -1} {
			b, _ := openConfirm86(t, side, true, 100, 0)
			q := gain85(3, side, -20)
			if test.oneQuote {
				if side > 0 {
					q.Ask += 10
				} else {
					q.Bid -= 10
				}
			}
			c := current86(q, side, test.v5*float64(side), test.v15*float64(side), test.k5, test.k15)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
			r := b.Result()
			assertCounts86(t, r)
			if r.HoldEnabled || r.Lots[0].HoldActive || r.Lots[0].HoldFloor != nil || r.Lots[0].Floor != -100 || r.Metrics.HoldHitLots != 0 {
				t.Fatal("保持帯床を活性化又は旧ATR床を変更", test.name, side, r)
			}
			if test.confirmed {
				if len(r.Orders) != 2 || r.Orders[1].Reason != ConfirmExitReason || r.Orders[1].ConfirmEvidence == nil || r.Orders[1].Quantity != 100 || r.Lots[0].ConfirmFirstConfirmed == nil {
					t.Fatal("両条件成立の同原行要求がない", test.name, side, r)
				}
				next := gain85(4, side, -20)
				cc := current86(next, side, 0, 0, true, true)
				need85(t, b.OnQuote(next, ReferenceFrame{}, TechnicalView{}, &cc))
				r = b.Result()
				if r.Unresolved || r.Metrics.NetPnLYen != -32200 || r.Closed[0].ConfirmRequestEvidence == nil || r.Closed[0].ConfirmFirstConfirmed.SourceLine != q.Line {
					t.Fatal("次原行実約定・費用又は確認継承が不整合", test.name, side, r)
				}
			} else if len(r.Orders) != 1 || r.Lots[0].ConfirmFirstConfirmed != nil || r.Metrics.ConfirmExitOrders != 0 {
				t.Fatal("非成立を退出へ昇格", test.name, side, r)
			}
		}
	}
}

// TestConfirm86SourceReject は同原行・有限性・既知窓の時計と単位の矛盾を拒否します。
//
// 引数: t(*testing.T)は金融出典の破損人工です。
// 返り値: ありません。既知不整合を真の未知として受理すれば失敗します。
func TestConfirm86SourceReject(t *testing.T) {
	mutations := []struct {
		name   string
		change func(*CurrentEvidence)
	}{
		{"別参照", func(c *CurrentEvidence) { c.Reference = "TOPIX" }},
		{"別原行", func(c *CurrentEvidence) { c.SourceLine++ }},
		{"負特徴番号", func(c *CurrentEvidence) { c.SourceIndex = -1 }},
		{"別時計", func(c *CurrentEvidence) { c.Time++ }},
		{"未来受領", func(c *CurrentEvidence) { c.Received++ }},
		{"過去受領", func(c *CurrentEvidence) { c.Received-- }},
		{"別Bid", func(c *CurrentEvidence) { c.Bid -= 10 }},
		{"別Ask", func(c *CurrentEvidence) { c.Ask += 10 }},
		{"別Last", func(c *CurrentEvidence) { c.Last++ }},
		{"短秒時刻", func(c *CurrentEvidence) { c.Short.Time-- }},
		{"短秒中央", func(c *CurrentEvidence) { c.Short.Mid++ }},
		{"速度単位", func(c *CurrentEvidence) { c.Short.Five.Speed *= 5 }},
		{"経過不整合", func(c *CurrentEvidence) { c.Short.Five.Elapsed++ }},
		{"未来端点", func(c *CurrentEvidence) { c.Short.Five.Endpoint = c.Time }},
		{"遅延不整合", func(c *CurrentEvidence) { c.Short.Fifteen.Delay++ }},
		{"許容外端点", func(c *CurrentEvidence) {
			c.Short.Five.Endpoint = c.Time - 21
			c.Short.Five.Elapsed = 21
			c.Short.Five.Delay = 16
			c.Short.Five.Move = c.Short.Five.Speed * 21
		}},
		{"既知NaN", func(c *CurrentEvidence) { c.Short.Five.Move = math.NaN() }},
		{"ゼロ幅へ極小負速度", func(c *CurrentEvidence) { c.Short.Five.Move = 0; c.Short.Five.Speed = -1e-100 }},
		{"未知非有限", func(c *CurrentEvidence) { c.Short.Fifteen.Known = false; c.Short.Fifteen.Speed = math.Inf(1) }},
	}
	for _, mutation := range mutations {
		b, _ := openConfirm86(t, 1, true, 100, 0)
		q := gain85(3, 1, -20)
		c := current86(q, 1, -1, -1, true, true)
		mutation.change(&c)
		if b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c) == nil {
			t.Fatal("破損を受理", mutation.name)
		}
	}
	b, _ := openConfirm86(t, 1, true, 100, 0)
	if b.OnQuote(gain85(3, 1, -20), ReferenceFrame{}, TechnicalView{}, nil) == nil {
		t.Fatal("正常残玉のnil特徴を受理")
	}
}

// TestConfirm86LegacyPriority は旧ATR・125・確定3分の予約理由を上書きしないことを検査します。
//
// 引数: t(*testing.T)は旧保護と複合確認が同時成立する人工です。
// 返り値: ありません。旧予約を二重化・上書きすれば失敗します。
func TestConfirm86LegacyPriority(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, test := range []struct {
			atr, gain float64
			reason    string
		}{{15, -20, "正益前ATR損失追尾"}, {125, -130, "共通125pt保護"}} {
			b, _ := openConfirm86(t, side, true, test.atr, 0)
			q := gain85(3, side, test.gain)
			c := current86(q, side, -float64(side), -float64(side), true, true)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
			r := b.Result()
			if len(r.Orders) != 2 || r.Orders[1].Reason != test.reason || r.Orders[1].ConfirmEvidence != nil || r.Metrics.ConfirmExitOrders != 0 || r.Metrics.ConfirmExitObligations != 1 || r.Lots[0].ConfirmFirstConfirmed == nil {
				t.Fatal("旧保護の優先・理由又は確認観測を破損", side, test.reason, r)
			}
			assertCounts86(t, r)
		}
		b, _ := openConfirm86(t, side, true, 100, 0)
		q := gain85(3, side, -20)
		c := current86(q, side, -float64(side), -float64(side), true, true)
		tech := TechnicalView{ExitKnown: true, EMA8_3: 10000, Close3: 10000 - float64(side), Histogram3: -float64(side), PreviousHistogram3: 0, Bar3End: q.Time}
		need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
		r := b.Result()
		if len(r.Orders) != 2 || r.Orders[1].Reason != "確定3分技法失敗" || r.Metrics.ConfirmExitOrders != 0 || r.Lots[0].ConfirmFirstConfirmed == nil {
			t.Fatal("確定3分失敗を新確認で上書き", side, r)
		}
	}
}

// TestConfirm86PartialAndSnapshot はG1の即時部分利確・床と先行片の時点保存を維持します。
//
// 引数: t(*testing.T)は部分fill悪化と同原行の確認人工です。
// 返り値: ありません。部分利確の遅延・将来確認の遡及・G1予約消去を検出します。
func TestConfirm86PartialAndSnapshot(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, _ := openConfirm86(t, side, true, 100, 0)
		q := gain85(3, side, 20)
		c := current86(q, side, float64(side), float64(side), true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r := b.Result()
		if len(r.Orders) != 2 || r.Orders[1].Quantity != 75 || !r.Lots[0].Flag || r.Lots[0].Floor < 0 || r.Orders[1].Reason != "正益起動の部分利確" {
			t.Fatal("正益即時起動・75枚計画・最低建値を変更", r)
		}
		q = gain85(4, side, -20)
		c = current86(q, side, -float64(side), -float64(side), true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r = b.Result()
		if len(r.Closed) != 1 || r.Closed[0].ConfirmFirstConfirmed != nil || r.Lots[0].ConfirmFirstConfirmed.SourceLine != q.Line || !r.Lots[0].FundingFailed || r.Lots[0].Floor < 0 || r.Orders[2].Reason != "G1確定益予算・ATR追尾" || r.Metrics.ConfirmExitOrders != 0 {
			t.Fatal("先行片遡及・部分fill悪化・旧G1優先が破損", r)
		}
		q = gain85(5, side, -20)
		c = current86(q, side, 0, 0, true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r = b.Result()
		if r.Unresolved || r.Closed[1].ConfirmFirstConfirmed.SourceLine != 104 || r.Closed[1].ConfirmRequestEvidence != nil || r.Metrics.NetPnLYen != -32200 {
			t.Fatal("後続片の当時確認・旧注文証拠が不整合", r)
		}
		assertCounts86(t, r)
	}
}

// TestConfirm86G1ThenAdditional は同原行のG1利確を残して複合確認が未予約25枚だけを要求します。
//
// 引数: t(*testing.T)は帯より有利な実取得と、正益・複合否定同時成立の人工です。
// 返り値: ありません。旧G1より先に新退出を置けば失敗します。
func TestConfirm86G1ThenAdditional(t *testing.T) {
	b, err := NewBook("人工86", "S0G1", 100, false)
	need85(t, err)
	need85(t, b.SetConfirmEnabled(true))
	q := quote85(1, 10000, 10010)
	c := evidence85(q, 1)
	a, err := BuildHoldAnchor(q.Time, q, c, 1)
	need85(t, err)
	tech := TechnicalView{ATRKnown: true, ATR3: 100}
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech, nil))
	need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, 1, q), tech, StructureAnchor{}, a, c))
	q = quote85(2, 9950, 9960)
	c = current86(q, 1, 0, 0, false, false)
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
	q = quote85(3, 9980, 9990)
	c = current86(q, 1, -1, -1, true, true)
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
	r := b.Result()
	if len(r.Orders) != 3 || r.Orders[1].Reason != "正益起動の部分利確" || r.Orders[1].Quantity != 75 || r.Orders[1].ConfirmEvidence != nil || r.Orders[2].Reason != ConfirmExitReason || r.Orders[2].Quantity != 25 || r.Orders[2].ConfirmEvidence == nil || r.Lots[0].Floor != 0 {
		t.Fatal("旧G1計画後に未予約残量だけ追加する順序が破損", r)
	}
	q = quote85(4, 9980, 9990)
	c = current86(q, 1, 0, 0, true, true)
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
	r = b.Result()
	if r.Unresolved || r.Metrics.NetPnLYen != 7800 || r.Closed[0].ConfirmRequestEvidence != nil || r.Closed[1].ConfirmRequestEvidence == nil {
		t.Fatal("手計算7800円又は片別注文証拠が不整合", r)
	}
	assertCounts86(t, r)
}

// TestConfirm86ReservedAndFinalFill は既予約残玉の観測と最終fillのみの非遡及を分けます。
//
// 引数: t(*testing.T)は同秒別行・1秒遅延と全量予約の人工です。
// 返り値: ありません。予約済み二重退出又は最終fill後の架空観測を検出します。
func TestConfirm86ReservedAndFinalFill(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, _ := openConfirm86(t, side, true, 100, 1)
		last := quote85(2, 10000, 10010)
		need85(t, b.Force(last.Time, last, "人工の全返済予約"))
		q := gain85(3, side, -20)
		q.Time = last.Time
		c := current86(q, side, -float64(side), -float64(side), true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r := b.Result()
		if len(r.Orders) != 2 || r.Metrics.ConfirmExitOrders != 0 || r.Metrics.ConfirmExitObligations != 1 || r.Lots[0].ConfirmFirstConfirmed.SourceLine != 103 || r.Metrics.ReservedExitQuantity != 100 {
			t.Fatal("全量予約の観測・同秒次行又は遅延を破損", r)
		}
		q = gain85(4, side, -20)
		q.Time = last.Time + 1
		c = current86(q, side, 0, 0, true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r = b.Result()
		if r.Unresolved || r.Closed[0].ConfirmFirstConfirmed.SourceLine != 103 || r.Closed[0].ConfirmRequestEvidence != nil {
			t.Fatal("予約済み注文の確認継承を破損", r)
		}
		b, _ = openConfirm86(t, side, true, 100, 0)
		need85(t, b.Force(last.Time, last, "人工の全返済予約"))
		q = gain85(3, side, -20)
		c = current86(q, side, -float64(side), -float64(side), true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r = b.Result()
		if r.Unresolved || r.Metrics.ConfirmCounts.NormalQuotes != 1 || r.Lots[0].ConfirmFirstConfirmed != nil || r.Closed[0].ConfirmFirstConfirmed != nil {
			t.Fatal("最終fillの後から確認を作った", r)
		}
		assertCounts86(t, r)
	}
}

// TestConfirm86FirstUnknownAndImmutable は未知を保持し、初回証拠を後続入力やResultから変更しません。
//
// 引数: t(*testing.T)は未知→回復→確認と値複写の人工です。
// 返り値: ありません。未知の昇格・将来値の遡及・外部共有を検出します。
func TestConfirm86FirstUnknownAndImmutable(t *testing.T) {
	b, _ := openConfirm86(t, 1, true, 100, 0)
	q := gain85(3, 1, -20)
	c := current86(q, 1, -1, -1, false, true)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
	q = gain85(4, 1, -10)
	c = current86(q, 1, 0, 0, true, true)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
	if b.Result().Lots[0].Floor != -100 || len(b.Result().Orders) != 1 {
		t.Fatal("未確認で保持帯床を活性化")
	}
	q = gain85(5, 1, -20)
	c = current86(q, 1, -1, -1, true, true)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
	c.Short.Five.Speed = 99
	r := b.Result()
	if r.Lots[0].ConfirmFirstPriceBreach.SourceLine != 103 || r.Lots[0].ConfirmFirstUnknown.SourceLine != 103 || r.Lots[0].ConfirmFirstConfirmed.SourceLine != 105 || r.Orders[1].ConfirmEvidence.Short.Five.Speed != -1 {
		t.Fatal("初回証拠の保持又は入力の値複写を破損", r)
	}
	r.Orders[1].ConfirmEvidence.Short.Five.Speed = 77
	if b.Result().Orders[1].ConfirmEvidence.Short.Five.Speed != -1 {
		t.Fatal("Resultの変更が内部へ伝播")
	}
	assertCounts86(t, b.Result())
}

// TestConfirm86QuoteGridAndUnknownProtection は待機/保有/最終fillの格子と未知時の旧保護を確認します。
//
// 引数: t(*testing.T)は正常非格子・不良気配・短秒未知の人工です。
// 返り値: ありません。黙った丸め・nilの補完・未知による旧損切り停止を検出します。
func TestConfirm86QuoteGridAndUnknownProtection(t *testing.T) {
	for _, final := range []bool{false, true} {
		b, _ := openConfirm86(t, 1, true, 100, 0)
		last := quote85(2, 10000, 10010)
		if final {
			need85(t, b.Force(last.Time, last, "人工全返済"))
		}
		q := gain85(3, 1, -20)
		q.Bid++
		c := current86(q, 1, -1, -1, true, true)
		if b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c) == nil {
			t.Fatal("保有又は最終fillの正常非格子を受理", final)
		}
	}
	b, _ := openConfirm86(t, 1, true, 15, 0)
	q := gain85(3, 1, -20)
	c := current86(q, 1, 0, 0, false, false)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
	r := b.Result()
	if r.Orders[1].Reason != "正益前ATR損失追尾" || r.Metrics.ConfirmExitOrders != 0 || r.Lots[0].ConfirmFirstUnknown == nil {
		t.Fatal("短秒未知で従来保護を停止", r)
	}
	b, _ = openConfirm86(t, 1, true, 100, 0)
	q = gain85(3, 1, -20)
	q.Valid = false
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, nil))
	if b.Result().Metrics.ConfirmCounts.NormalQuotes != 1 {
		t.Fatal("非正常原行を確認へ混入")
	}
	for _, enabled := range []bool{false, true} {
		b, err := NewBook("人工86", "S0G1", 100, false)
		need85(t, err)
		need85(t, b.SetConfirmEnabled(enabled))
		q = quote85(1, 10000, 10010)
		c = evidence85(q, 1)
		a, err := BuildHoldAnchor(q.Time, q, c, 1)
		need85(t, err)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, nil))
		need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, 1, q), TechnicalView{}, StructureAnchor{}, a, c))
		q = quote85(2, 10001, 10010)
		c = current86(q, 1, 0, 0, true, true)
		err = b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c)
		if enabled && (err == nil || b.Result().Metrics.EntryQuantity != 0) {
			t.Fatal("新規待機の非格子をfill前に拒否していない")
		}
		if !enabled && (err != nil || b.Result().Metrics.EntryQuantity != 100) {
			t.Fatal("J0の旧将来気配処理を変更")
		}
	}
}

// TestConfirm86EndpointAndProfitBoundary は既知端点15秒包含と利益のstrict正を検査します。
//
// 引数: t(*testing.T)は5/15秒端点・10ptと20ptの費用後境界の人工です。
// 返り値: ありません。許容端点の拒否・費用前起動・利益保護の遅延を検出します。
func TestConfirm86EndpointAndProfitBoundary(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, _ := openConfirm86(t, side, true, 100, 0)
		q := gain85(3, side, -20)
		c := current86(q, side, -float64(side), -float64(side), true, true)
		for _, item := range []struct {
			window  *CurrentShortWindow
			horizon float64
		}{{&c.Short.Five, 5}, {&c.Short.Fifteen, 15}} {
			item.window.Delay = 15
			item.window.Elapsed = item.horizon + 15
			item.window.Endpoint = q.Time - item.window.Elapsed
			item.window.Move = item.window.Speed * item.window.Elapsed
		}
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		if b.Result().Metrics.ConfirmExitOrders != 1 {
			t.Fatal("15秒端点の包含境界を拒否", side)
		}
		b, _ = openConfirm86(t, side, true, 100, 0)
		q = gain85(3, side, 10)
		c = current86(q, side, 0, 0, true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		if b.Result().Lots[0].Flag || len(b.Result().Orders) != 1 {
			t.Fatal("費用後−22円/枚の10ptで利益起動", side)
		}
		q = gain85(4, side, 20)
		c = current86(q, side, 0, 0, true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}, &c))
		r := b.Result()
		if !r.Lots[0].Flag || r.Lots[0].Floor < 0 || len(r.Orders) != 2 || r.Orders[1].Quantity != 75 {
			t.Fatal("費用後＋78円/枚の20ptの即時G1起動を変更", side, r)
		}
	}
}

// TestConfirm86EntryAlreadyConfirmed は既に両気配否定した実fillを残して同原行に返済要求します。
//
// 引数: t(*testing.T)は買売鏡像の新規ギャップ人工です。
// 返り値: ありません。新規消去・同原行の架空返済・旧hold活性化を検出します。
func TestConfirm86EntryAlreadyConfirmed(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, err := NewBook("人工86", "S0G1", 100, false)
		need85(t, err)
		need85(t, b.SetConfirmEnabled(true))
		q := quote85(1, 10000, 10010)
		c := evidence85(q, side)
		a, err := BuildHoldAnchor(q.Time, q, c, side)
		need85(t, err)
		tech := TechnicalView{ATRKnown: true, ATR3: 100}
		need85(t, b.OnQuote(q, ReferenceFrame{}, tech, nil))
		need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, StructureAnchor{}, a, c))
		q = quote85(2, 9980, 9990)
		if side < 0 {
			q = quote85(2, 10020, 10030)
		}
		c = current86(q, side, -float64(side), -float64(side), true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
		r := b.Result()
		if r.Metrics.EntryQuantity != 100 || r.Metrics.ExitQuantity != 0 || r.Lots[0].ConfirmFirstConfirmed.SourceLine != r.Lots[0].EntryLine || len(r.Orders) != 2 || r.Orders[1].RequestLine != q.Line || r.Lots[0].HoldActive {
			t.Fatal("新規fillと同原行確認要求の順序が不整合", side, r)
		}
		q.Index++
		q.Line++
		q.Time++
		c = current86(q, side, 0, 0, true, true)
		need85(t, b.OnQuote(q, ReferenceFrame{}, tech, &c))
		r = b.Result()
		if r.Unresolved || r.Metrics.NetPnLYen != -22200 || r.Closed[0].ExitLine == r.Lots[0].EntryLine {
			t.Fatal("次原行の実返済・手計算−22200円が不整合", side, r)
		}
		assertCounts86(t, r)
	}
}

// TestConfirm86DisabledFullProjection は新観測offの非0全会計を固定85H0と全文比較します。
//
// 引数: t(*testing.T)は買売×両遅延×利益/損失の独立対照です。
// 返り値: ありません。価格・費用・所有・旧hold欄・旧全値の相違を検出します。
func TestConfirm86DisabledFullProjection(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			for _, profit := range []bool{false, true} {
				b, err := NewBook("人工86", "S0G1", 100, false)
				need85(t, err)
				old, err := far85.NewBook("人工86", "S0G1", 100, false)
				need85(t, err)
				need85(t, b.SetConfirmEnabled(false))
				need85(t, b.SetFillDelay(delay))
				need85(t, old.SetFillDelay(delay))
				q := quote85(1, 10000, 10010)
				c := evidence85(q, side)
				a, err := BuildHoldAnchor(q.Time, q, c, side)
				need85(t, err)
				oa, err := far85.BuildHoldAnchor(q.Time, q, c, side)
				need85(t, err)
				tech := TechnicalView{ATRKnown: true, ATR3: 100}
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
				need85(t, b.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, StructureAnchor{}, a, c))
				need85(t, old.OnGrid(q.Time, q, candidate85(q.Time, side, q), tech, StructureAnchor{}, oa, c))
				gains := []float64{-10, -110, -110, -110}
				if profit {
					gains = []float64{-10, 20, 20, 0, -10}
				}
				for i, gain := range gains {
					q = gain85(int64(i+2), side, gain)
					need85(t, b.OnQuote(q, ReferenceFrame{}, tech, nil))
					need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
				}
				r := b.Result()
				if r.Unresolved || r.Metrics.EntryQuantity != 100 || r.Metrics.ConfirmCounts != (ConfirmCounts{}) || r.ConfirmEnabled || r.Lots[0].ConfirmFirstPriceBreach != nil || !reflect.DeepEqual(projectConfirm86(r), projectConfirm86(old.Result())) {
					t.Fatal("J0旧85H0非0全文不同値", side, delay, profit, r)
				}
			}
		}
	}
}
