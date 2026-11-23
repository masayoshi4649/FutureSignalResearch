package far91

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"testing"

	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
)

// gain91 は原行番号と時刻を分けた売買鏡像の人工を作ります。
//
// 引数: index(int64)、at(float64)、side(int)、gain(float64)は採用番号・時計・方向・実想定方向幅です。
// 返り値: Quoteは正常な10ptスプレッドです。
func gain91(index int64, at float64, side int, gain float64) Quote {
	q := gain85(index, side, gain)
	q.Time = at
	return q
}

// opportunity91 は金融境界のためだけの公開済みE1出典を合成します。
//
// 引数: at(float64)、q(Quote)、ref(ReferenceLot)、serial(int)は定時・直前原行・候補・異なるevent番号です。
// 返り値: EntryOpportunityは手製の全公開点です。元指標又はE1生成の証明ではありません。
func opportunity91(at float64, q Quote, ref ReferenceLot, serial int) EntryOpportunity {
	point := func(n int64, delta float64) EventPoint {
		return EventPoint{ObservationID: int64(serial)*10 + n, BarEnd: at - delta, PublishedAt: at - delta}
	}
	e := ResumeEvent{ID: fmt.Sprintf("人工event%d", serial), Side: ref.Side, Window: "D164_15", EpochStart: at - 900,
		Impulse: point(1, 720), Pullback: point(2, 540), Recovery: point(3, 360), Confirmation: point(4, 180)}
	pubs := []OpportunityPublication{}
	for i, p := range []EventPoint{e.Impulse, e.Pullback, e.Recovery, e.Confirmation} {
		pubs = append(pubs, OpportunityPublication{ObservationID: p.ObservationID, Ordinal: int64(serial*100 + i + 1), At: p.PublishedAt, BarEnd: p.BarEnd, Origin: "three_timer",
			Quote: Quote{Time: p.PublishedAt, Index: 0, Line: 100, Last: 10005, Bid: 10000, Ask: 10010, Valid: true}})
	}
	return EntryOpportunity{Known: true, Kind: OpportunityKind, RuleVersion: OpportunityRuleVersion, At: at, ReferenceID: ref.ID, Side: ref.Side,
		OpportunityID: OpportunityKey{Session: "人工91", ReferenceID: ref.ID, EventID: e.ID}, Event: e, Publications: pubs, Reason: OpportunityReason}
}

// grid91 は手製Source現在玉の同一候補へ現在eventを渡します。
//
// 引数: t(*testing.T)、b(*Book)、s(ReadSnapshot)、q(Quote)、serial(int)は金融と新しい公開機会です。
// 返り値: EntryOpportunityは要求した固定機会です。
func grid91(t *testing.T, b *Book, s ReadSnapshot, q Quote, serial int) EntryOpportunity {
	t.Helper()
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{ATRKnown: true, ATR3: 100}))
	s.At, s.SourceIndex = q.Time, s.SourceIndex+q.Index
	o := opportunity91(q.Time, q, s.Lots[0].Reference, serial)
	need85(t, b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{ATRKnown: true, ATR3: 100}, StructureAnchor{}, map[string]EntryOpportunity{s.Lots[0].Reference.ID: o}))
	return o
}

// open91 は次適格原行で初参加するR1を作ります。
//
// 引数: t(*testing.T)、side/quantity(int)、delay(float64)は方向・元現在量・価格時計遅延です。
// 返り値: *BookとReadSnapshotは実初参加の金融と元候補です。
func open91(t *testing.T, side, quantity int, delay float64) (*Book, ReadSnapshot) {
	t.Helper()
	b, err := NewReentrySourceBook("人工91", "S", 100)
	need85(t, err)
	need85(t, b.SetFillDelay(delay))
	q := quote85(1, 10000, 10010)
	s := snapshot87(q, side, quantity, "参照玉")
	grid91(t, b, s, q, 1)
	need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, TechnicalView{ATRKnown: true, ATR3: 100}))
	if b.Result().Metrics.OpenQuantity != quantity {
		t.Fatal("初参加の実所有がない")
	}
	return b, s
}

// profit91 はG1の自然な部分収穫と建値返済だけで全返済を作ります。
//
// 引数: t(*testing.T)、b(*Book)、side/quantity(int)、index(int64)、at(float64)は金融と次原行です。
// 返り値: float64は手計算した当該玉の費用後円です。Source参照は閉じません。
func profit91(t *testing.T, b *Book, side, quantity int, index int64, at float64) float64 {
	t.Helper()
	harvest := int(math.Ceil(float64(222*quantity+1) / 400))
	for i, gain := range []float64{30, 30, 0, 0} {
		need85(t, b.OnQuote(gain91(index+int64(i), at+float64(i), side, gain), ReferenceFrame{}, TechnicalView{}))
	}
	expected := float64(300*harvest - 122*quantity)
	if expected <= 0 || b.lastActual["参照玉"].NetPnL != expected || len(b.lots) != 0 {
		t.Fatal("G1利確完了の手計算差", quantity, expected, b.Result())
	}
	return expected
}

// TestReentry91Constructors は旧金融schemaと専用APIの混用禁止を確認します。
//
// 引数: t(*testing.T)はconstructorの検査器です。
// 返り値: ありません。R0の初期JSONは固定89へ投影せず比較します。
func TestReentry91Constructors(t *testing.T) {
	for _, args := range []struct {
		session, policy string
		cap             int
	}{{"", "S", 100}, {"人工91", "SC", 100}, {"人工91", "", 100}, {"人工91", "S", 99}} {
		if _, err := NewReentrySourceBook(args.session, args.policy, args.cap); err == nil {
			t.Fatal("不正なR1constructorを受理")
		}
	}
	b, err := NewReentrySourceBook("人工91", "S", 100)
	need85(t, err)
	q := quote85(1, 10000, 10010)
	if b.mode != "S0G1" || b.guard != "G1" || b.stop != "S0" || b.holdEnabled || b.confirmEnabled || b.SetConfirmEnabled(true) == nil || b.OnSourceGrid(q.Time, q, ReadSnapshot{}, Decision{}, TechnicalView{}, StructureAnchor{}) == nil {
		t.Fatal("R1内部又は旧API混用が違う")
	}
	r0, err := NewSourceBook("人工91", "S", 100)
	need85(t, err)
	if r0.OnSourceGridWithReentry(q.Time, q, ReadSnapshot{}, Decision{}, TechnicalView{}, StructureAnchor{}, nil) == nil || len(r0.LastReentryAssessments()) != 0 {
		t.Fatal("R0へR1APIを混用")
	}
	old, err := far89.NewSourceBook("人工91", "S", 100)
	need85(t, err)
	a, _ := json.Marshal(r0.Result())
	c, _ := json.Marshal(old.Result())
	if !bytes.Equal(a, c) {
		t.Fatal("R0初期全JSON差")
	}
}

// TestReentry91ThreeActualGenerations は全数量・買売・両遅延で同参照3世代と予算初期化を確認します。
//
// 引数: t(*testing.T)は400条件の非0金融検査器です。
// 返り値: ありません。全履歴/新玉G1/IDと費用後総額を手計算へ結びます。
func TestReentry91ThreeActualGenerations(t *testing.T) {
	for quantity := 1; quantity <= 100; quantity++ {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				b, s := open91(t, side, quantity, delay)
				expected := profit91(t, b, side, quantity, 3, 1002)
				for generation := 2; generation <= 3; generation++ {
					at := float64(1000 + 900*(generation-1))
					index := int64(10 * (generation - 1))
					q := gain91(index, at, side, -10)
					grid91(t, b, s, q, generation)
					a := b.LastReentryAssessments()[0]
					if !a.Selected || !a.Consumed || a.Role != "利確後再参加" || a.AcceptedSerial != generation || a.PreviousActual == nil || a.PreviousActual.NetPnL != expected || a.PreviousActual.Completion == nil || a.SourceSeen != true {
						t.Fatal("受理時の再参加履歴と役割が違う", a)
					}
					need85(t, b.OnQuote(gain91(index+1, at+1, side, -10), ReferenceFrame{}, TechnicalView{}))
					p := b.lots["参照玉"]
					if p.RealEntryStage != "利確後再参加" || p.Role != "source_add" || p.NetPnL != 0 || p.Flag || p.WholeFlag || p.HarvestOrderID != "" || p.CashFloorActive || p.HarvestFilled != 0 || p.Floor != -100 || len(b.allByPosition) != generation {
						t.Fatal("過去の予算/旗を新玉へ継承又は履歴消失", p)
					}
					profit91(t, b, side, quantity, index+2, at+2)
				}
				r := b.Result()
				if r.Unresolved || len(r.Lots) != 3 || r.Metrics.ClosedLots != 3 || r.Metrics.NetPnLYen != 3*expected || r.Metrics.TotalCostYen != float64(3*122*quantity) || len(b.seen) != 1 || len(b.opportunitySeen) != 3 {
					t.Fatal("3世代全量/費用/永久seenの手計算差", quantity, side, delay, r)
				}
				for i, p := range r.Lots {
					if p.ID != fmt.Sprintf("人工91_S0G1_P%06d", i+1) || p.NetPnL != expected || p.Quantity != 0 || p.SourceEntry.ReadLot.Reference.ID != "参照玉" {
						t.Fatal("全履歴又は単調IDを喪失")
					}
				}
			}
		}
	}
}

// TestReentry91CancellationA は実取得0の取消を実参加にせず同event消費を維持します。
//
// 引数: t(*testing.T)は買売・両遅延の取消A境界です。
// 返り値: ありません。別eventは最後の実玉を基準に再検討し、IDを飛ばして採番します。
func TestReentry91CancellationA(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, s := open91(t, side, 8, delay)
			profit91(t, b, side, 8, 3, 1002)
			q := gain91(10, 1900, side, -10)
			o := grid91(t, b, s, q, 2)
			need85(t, b.Force(1900.25, q, "人工取消"))
			if len(b.allByPosition) != 1 || b.entrySerial != 2 || b.lastActual["参照玉"].ID != "人工91_S0G1_P000001" {
				t.Fatal("0取得取消を新しい実参加へ補完")
			}
			q = gain91(11, 1915, side, -10)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			s.At = q.Time
			o.At = q.Time
			need85(t, b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]EntryOpportunity{"参照玉": o}))
			if b.LastReentryAssessments()[0].Selected || !b.LastReentryAssessments()[0].OpportunitySeen {
				t.Fatal("取消eventを解放した")
			}
			q = gain91(20, 2800, side, -10)
			grid91(t, b, s, q, 3)
			if a := b.LastReentryAssessments()[0]; !a.Selected || a.AcceptedSerial != 3 || a.PreviousActual.PositionID != "人工91_S0G1_P000001" || a.PositionID != "人工91_S0G1_P000003" {
				t.Fatal("取消後別eventの資格又はserialが違う", a)
			}
			need85(t, b.OnQuote(gain91(21, 2801, side, -10), ReferenceFrame{}, TechnicalView{}))
			if len(b.allByPosition) != 2 || b.lots["参照玉"].ID != "人工91_S0G1_P000003" {
				t.Fatal("取消世代を実玉へ混ぜた")
			}
			fresh, err := NewReentrySourceBook("人工91", "S", 100)
			need85(t, err)
			need85(t, fresh.SetFillDelay(delay))
			q = quote85(1, 10000, 10010)
			s0 := snapshot87(q, side, 8, "参照玉")
			grid91(t, fresh, s0, q, 1)
			need85(t, fresh.Force(1000.25, q, "初回取消"))
			grid91(t, fresh, s0, gain91(10, 1900, side, -10), 2)
			if a := fresh.LastReentryAssessments()[0]; a.Selected || a.PreviousActual != nil || len(fresh.allByPosition) != 0 {
				t.Fatal("初回取消だけで利確資格を作った")
			}
		}
	}
}

// TestReentry91LatestLossAndZero は最新実参加の損失/同値を昔の勝ちへ置き換えません。
//
// 引数: t(*testing.T)は売買鏡像の最新実績検査です。
// 返り値: ありません。部分益/正益旗だけの未完了も再参加させません。
func TestReentry91LatestLossAndZero(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, gain := range []float64{-20, 12.2} {
			b, s := open91(t, side, 8, 0)
			profit91(t, b, side, 8, 3, 1002)
			q := gain91(10, 1900, side, -10)
			grid91(t, b, s, q, 2)
			need85(t, b.OnQuote(gain91(11, 1901, side, -10), ReferenceFrame{}, TechnicalView{}))
			need85(t, b.Force(1901.25, b.last, "人工撤退"))
			need85(t, b.OnQuote(gain91(12, 1902, side, gain), ReferenceFrame{}, TechnicalView{}))
			q = gain91(20, 2800, side, -10)
			grid91(t, b, s, q, 3)
			a := b.LastReentryAssessments()[0]
			if a.Selected || a.PreviousActual.PositionID != "人工91_S0G1_P000002" || a.PreviousActual.NetPnL > 0 || b.entrySerial != 2 {
				t.Fatal("最新非正を昔の利確へfallback", a)
			}
		}
		b, s := open91(t, side, 8, 0)
		need85(t, b.OnQuote(gain91(3, 1002, side, 30), ReferenceFrame{}, TechnicalView{}))
		grid91(t, b, s, gain91(4, 1003, side, 30), 2)
		a := b.LastReentryAssessments()[0]
		if a.Selected || a.PreviousActual.Completion != nil || b.decisions[len(b.decisions)-1].Action != "保有継続" || b.entrySerial != 1 {
			t.Fatal("部分収穫/旗だけで再参加")
		}
	}
}

// TestReentry91SameClock はp/r/kの公開順を同時計の両Index/Lineで確認します。
//
// 引数: t(*testing.T)は同原行・後原行・片方だけ後・stale timerの反証です。
// 返り値: ありません。i又はBarEndまで返済後にする追加gateは作りません。
func TestReentry91SameClock(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, tc := range []struct {
			name         string
			index, line  int64
			stale, allow bool
		}{{"同原行", 0, 0, false, false}, {"後原行", 1, 1, false, true}, {"Indexだけ後", 1, 0, false, false}, {"Lineだけ後", 0, 1, false, false}, {"stale", 1, 1, true, false}} {
			b, s := open91(t, side, 8, 0)
			profit91(t, b, side, 8, 3, 1002)
			done := b.flatStamps["人工91_S0G1_P000001"]
			q := gain91(10, 1015, side, -10)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			s.At = q.Time
			o := opportunity91(q.Time, q, s.Lots[0].Reference, 2)
			o.Event.Pullback.PublishedAt, o.Event.Recovery.PublishedAt, o.Event.Confirmation.PublishedAt = done.At, done.At, done.At
			for i := 1; i < len(o.Publications); i++ {
				o.Publications[i].At, o.Publications[i].Quote.Time = done.At, done.At
				o.Publications[i].Quote.Index, o.Publications[i].Quote.Line = done.QuoteIndex+tc.index, done.QuoteLine+tc.line
				if tc.stale {
					o.Publications[i].Quote.Time--
				}
			}
			need85(t, b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]EntryOpportunity{"参照玉": o}))
			a := b.LastReentryAssessments()[0]
			if a.Selected != tc.allow || len(a.Chronology) != 3 {
				t.Fatal("同時計の公開順を誤分類", tc.name, a)
			}
			if tc.allow && !(o.Event.Impulse.PublishedAt < done.At && o.Event.Pullback.BarEnd < done.At) {
				t.Fatal("i/BarEnd返済後限定の反証が機能していない")
			}
		}
	}
}

// TestReentry91FreshPriority は供給順位を維持してfreshだけ先に選びます。
//
// 引数: t(*testing.T)は同枠競合・同event別ref・再参加占有の人工です。
// 返り値: ありません。表示/保有/見送りではopportunityを消費しません。
func TestReentry91FreshPriority(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, s := open91(t, side, 8, 0)
		profit91(t, b, side, 8, 3, 1002)
		q := gain91(10, 1900, side, -10)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		fresh := s.Lots[0]
		fresh.Reference.ID, fresh.Reference.InternalID, fresh.Reference.SourceID, fresh.Reference.At = "新候補", "新内部", "新源", 1890
		s.Lots, s.At = append(s.Lots, fresh), q.Time
		oldOp, freshOp := opportunity91(q.Time, q, s.Lots[0].Reference, 2), opportunity91(q.Time, q, fresh.Reference, 2)
		need85(t, b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]EntryOpportunity{"参照玉": oldOp, "新候補": freshOp}))
		a := b.LastReentryAssessments()
		if len(a) != 2 || a[0].Selected || !a[0].Eligible || a[0].SelectionRank != 2 || !a[1].Selected || a[1].Role != "初参加" || a[1].SuppliedRank != 2 || a[1].SelectionRank != 1 || b.orders[len(b.orders)-1].SourceEntry.Rank != 2 || b.opportunitySeen[oldOp.OpportunityID] {
			t.Fatal("fresh優先/供給rank/非消費が違う", a)
		}
		need85(t, b.OnQuote(gain91(11, 1901, side, -10), ReferenceFrame{}, TechnicalView{}))
		q = gain91(12, 1915, side, -10)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		s.At = q.Time
		oldOp.At, freshOp.At = q.Time, q.Time
		need85(t, b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]EntryOpportunity{"参照玉": oldOp, "新候補": freshOp}))
		if b.LastReentryAssessments()[0].Selected || b.opportunitySeen[oldOp.OpportunityID] || b.decisions[len(b.decisions)-1].Action != "保有継続" {
			t.Fatal("保有中の候補表示で機会消費又は強制新規")
		}
		if b.seen["新候補"] != true || len(b.opportunitySeen) != 2 {
			t.Fatal("同eventを別refへ全会計共通消費した")
		}
	}
}

// TestReentry91SourceCurrentOnly はSource通知を現在世代だけへ適用します。
//
// 引数: t(*testing.T)は買売・両遅延・0丸め・部分/全量の人工です。
// 返り値: ありません。過去flatへの再作用と新玉への過去利益流入を拒否します。
func TestReentry91SourceCurrentOnly(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, s := open91(t, side, 8, delay)
			profit91(t, b, side, 8, 3, 1002)
			old := b.Result().Lots[0]
			q := gain91(10, 1900, side, -10)
			grid91(t, b, s, q, 2)
			need85(t, b.OnQuote(gain91(11, 1901, side, -10), ReferenceFrame{}, TechnicalView{}))
			closes := []ReferenceClose{{ID: "丸め0", ReferenceID: "参照玉", Before: 100, Quantity: 1}, {ID: "部分3", ReferenceID: "参照玉", Before: 8, Quantity: 3}}
			need85(t, b.OnQuote(gain91(12, 1902, side, 10), ReferenceFrame{Closes: closes}, TechnicalView{}))
			need85(t, b.OnQuote(gain91(13, 1903, side, 10), ReferenceFrame{}, TechnicalView{}))
			need85(t, b.OnReference(1903.25, b.last, []ReferenceClose{{ID: "全残5", ReferenceID: "参照玉", Before: 5, Quantity: 5}}))
			need85(t, b.OnQuote(gain91(14, 1905, side, 20), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			if r.Unresolved || len(r.Lots) != 2 || r.Lots[0].NetPnL != old.NetPnL || r.Lots[0].ClosedQuantity != old.ClosedQuantity || r.Lots[1].NetPnL != 324 || r.Metrics.NetPnLYen != 848 || !r.Lots[1].Flag || r.Lots[1].Quantity != 0 || b.sourceEffects[0].ExitRequested != 0 || b.sourceEffects[1].ExitRequested != 3 || b.sourceEffects[2].ExitRequested != 5 {
				t.Fatal("Sourceが過去世代へ作用又は予算を継承", r)
			}
			for _, c := range r.Closed {
				if c.PositionID == r.Lots[1].ID && c.RealEntryStage != "利確後再参加" {
					t.Fatal("返済片の実役割又は世代を混同")
				}
			}
			if b.OnReference(1906, b.last, closes[:1]) == nil {
				t.Fatal("再参加世代でSource通知IDを解放した")
			}
		}
	}
}

// TestReentry91AssessmentCopy は外側の資格出典を金融へ書き戻せないことを確認します。
//
// 引数: t(*testing.T)はgetterの深い値コピー検査器です。
// 返り値: ありません。前回純額・完了stamp・公開順の後変更を遮断します。
func TestReentry91AssessmentCopy(t *testing.T) {
	b, s := open91(t, 1, 8, 0)
	profit91(t, b, 1, 8, 3, 1002)
	grid91(t, b, s, gain91(10, 1900, 1, -10), 2)
	a := b.LastReentryAssessments()
	a[0].PreviousActual.NetPnL = 999999
	a[0].PreviousActual.Completion.At = 999999
	a[0].Chronology[0].After = false
	c := b.LastReentryAssessments()[0]
	if c.PreviousActual.NetPnL != 524 || c.PreviousActual.Completion.At == 999999 || !c.Chronology[0].After {
		t.Fatal("外sidecarの後変更が金融へ逆流")
	}
}

// TestReentry91OpportunityCorruption は既知機会の破損を資格不成立へ隠さず拒否します。
//
// 引数: t(*testing.T)は両方向・公開出典・map一意性の反証器です。
// 返り値: ありません。error前にseen/採番/定時を消費しません。
func TestReentry91OpportunityCorruption(t *testing.T) {
	mutations := []struct {
		name string
		edit func(*EntryOpportunity)
	}{
		{"未知", func(o *EntryOpportunity) { o.Known = false }},
		{"種類", func(o *EntryOpportunity) { o.Kind = "別方式" }},
		{"版", func(o *EntryOpportunity) { o.RuleVersion++ }},
		{"理由", func(o *EntryOpportunity) { o.Reason = "変更" }},
		{"要求at", func(o *EntryOpportunity) { o.At++ }},
		{"参照ID", func(o *EntryOpportunity) { o.ReferenceID = "別玉" }},
		{"側", func(o *EntryOpportunity) { o.Side = -o.Side }},
		{"場", func(o *EntryOpportunity) { o.OpportunityID.Session = "別場" }},
		{"機会ref", func(o *EntryOpportunity) { o.OpportunityID.ReferenceID = "別ref" }},
		{"機会event", func(o *EntryOpportunity) { o.OpportunityID.EventID = "別event" }},
		{"event側", func(o *EntryOpportunity) { o.Event.Side = -o.Event.Side }},
		{"別窓", func(o *EntryOpportunity) { o.Event.Window = "P164_06" }},
		{"epoch", func(o *EntryOpportunity) { o.Event.EpochStart = o.At + 1 }},
		{"p未来", func(o *EntryOpportunity) { o.Event.Pullback.PublishedAt = o.At + 1 }},
		{"p有限", func(o *EntryOpportunity) { o.Event.Pullback.BarEnd = math.NaN() }},
		{"p順序", func(o *EntryOpportunity) { o.Event.Pullback = o.Event.Impulse }},
		{"k期限", func(o *EntryOpportunity) { o.Event.Confirmation.BarEnd = o.At - 900 }},
		{"公開欠落", func(o *EntryOpportunity) { o.Publications = o.Publications[:3] }},
		{"公開余剰", func(o *EntryOpportunity) { o.Publications = append(o.Publications, o.Publications[3]) }},
		{"公開ID", func(o *EntryOpportunity) { o.Publications[1].ObservationID++ }},
		{"公開Ordinal", func(o *EntryOpportunity) { o.Publications[1].Ordinal = o.Publications[0].Ordinal }},
		{"公開At", func(o *EntryOpportunity) { o.Publications[1].At++ }},
		{"公開足", func(o *EntryOpportunity) { o.Publications[1].BarEnd++ }},
		{"origin", func(o *EntryOpportunity) { o.Publications[1].Origin = "未公開" }},
		{"未来Index", func(o *EntryOpportunity) { o.Publications[1].Quote.Index = 2 }},
		{"未来Line", func(o *EntryOpportunity) { o.Publications[1].Quote.Line = 102 }},
		{"未来原行", func(o *EntryOpportunity) { o.Publications[1].Quote.Time = o.At + 1 }},
		{"Last未知", func(o *EntryOpportunity) { o.Publications[1].Quote.Last = 0 }},
		{"BBO非有限", func(o *EntryOpportunity) { o.Publications[1].Quote.Bid = math.Inf(1) }},
	}
	for _, side := range []int{1, -1} {
		for _, m := range mutations {
			t.Run(fmt.Sprintf("%s_%d", m.name, side), func(t *testing.T) {
				b, err := NewReentrySourceBook("人工91", "S", 100)
				need85(t, err)
				q := quote85(1, 10000, 10010)
				need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
				s := snapshot87(q, side, 8, "参照玉")
				o := opportunity91(q.Time, q, s.Lots[0].Reference, 1)
				m.edit(&o)
				if b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]EntryOpportunity{"参照玉": o}) == nil || len(b.orders) != 0 || len(b.seen) != 0 || b.haveGrid || b.entrySerial != 0 {
					t.Fatal("破損機会を受理又はerror前に状態消費")
				}
			})
		}
		q := quote85(1, 10000, 10010)
		s := snapshot87(q, side, 8, "参照玉")
		o := opportunity91(q.Time, q, s.Lots[0].Reference, 1)
		for _, opportunities := range []map[string]EntryOpportunity{nil, {"別玉": o}, {"参照玉": o, "別玉": o}} {
			b, err := NewReentrySourceBook("人工91", "S", 100)
			need85(t, err)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			if b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, opportunities) == nil {
				t.Fatal("mapの参照集合不一致を受理")
			}
		}
		b, err := NewReentrySourceBook("人工91", "S", 100)
		need85(t, err)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		o.Publications[1].Quote.Valid = false
		o.Publications[1].Quote.Ask = o.Publications[1].Quote.Bid - 10
		need85(t, b.OnSourceGridWithReentry(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}, map[string]EntryOpportunity{"参照玉": o}))
		if !b.LastReentryAssessments()[0].Selected {
			t.Fatal("過去のBBO不正を新E1 gateにした")
		}
	}
}

// TestReentry91SourceBeforeAndPending は再参加前の通知と現在pendingの比率を分けます。
//
// 引数: t(*testing.T)は買売・両遅延で取消後実量を確認する人工です。
// 返り値: ありません。過去通知の再適用と要求量/実量の混同を防ぎます。
func TestReentry91SourceBeforeAndPending(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, s := open91(t, side, 8, delay)
			profit91(t, b, side, 8, 3, 1002)
			c := ReferenceClose{ID: "再参加前1", ReferenceID: "参照玉", Before: 8, Quantity: 1}
			need85(t, b.OnReference(1006, b.last, []ReferenceClose{c}))
			if e := b.sourceEffects[0]; e.ExitRequested != 0 || e.Cancelled != 0 || e.UnreservedBefore != 0 {
				t.Fatal("過去flatへSource再作用")
			}
			s.Lots[0].Reference.Quantity = 7
			q := gain91(10, 1900, side, -10)
			grid91(t, b, s, q, 2)
			need85(t, b.OnReference(1900.25, q, []ReferenceClose{{ID: "現在pending2", ReferenceID: "参照玉", Before: 7, Quantity: 2}}))
			if b.sourceEffects[1].PendingBefore != 7 || b.sourceEffects[1].Cancelled != 2 || b.sourceEffects[1].ExitRequested != 0 {
				t.Fatal("現在pendingだけの比率取消が違う")
			}
			need85(t, b.OnQuote(gain91(11, 1901, side, -10), ReferenceFrame{}, TechnicalView{}))
			p := b.lots["参照玉"]
			if p.InitialQuantity != 5 || p.SourceEntry.RequestedQuantity != 7 || p.NetPnL != 0 || p.Flag || p.HarvestFilled != 0 || b.allByPosition["人工91_S0G1_P000001"].NetPnL != 524 {
				t.Fatal("通知前史/旧利益を新玉へ逆適用又は要求量を補正")
			}
			if b.OnReference(1902, b.last, []ReferenceClose{c}) == nil {
				t.Fatal("再参加で過去通知IDを解放")
			}
		}
	}
}

// TestReentry91OffEveryQuantity は量1..100・売買・両遅延の対照全文を固定89へ直接比較します。
//
// 引数: t(*testing.T)は旧JSONの全field/順序/数値を比較する人工です。
// 返り値: ありません。Source部分比率・正益/G1・Force後もJSONラベルを置換しません。
func TestReentry91OffEveryQuantity(t *testing.T) {
	for quantity := 1; quantity <= 100; quantity++ {
		for _, side := range []int{1, -1} {
			for _, delay := range []float64{0, 1} {
				b, err := NewSourceBook("人工91対照", "S", 100)
				need85(t, err)
				old, err := far89.NewSourceBook("人工91対照", "S", 100)
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
