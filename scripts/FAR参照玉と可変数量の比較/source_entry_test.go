package far87

import (
	"encoding/json"
	"reflect"
	"testing"

	far84 "github.com/masayoshi4649/SessionTradeExecuter/research84"
	far86 "github.com/masayoshi4649/SessionTradeExecuter/research86"
)

// stripSource87は宣言済みの87追加欄だけを落とし旧金融全値を保ちます。
//
// 引数: out(map[string]any)は新旧BookResultのJSON値です。
// 返り値: ありません。値・数量・配列順を変えず新欄だけ除外します。
func stripSource87(out map[string]any) {
	delete(out, "source_policy")
	delete(out, "source_effects")
	for _, name := range []string{"orders", "pending_entries", "lots", "positions", "closed"} {
		for _, v := range out[name].([]any) {
			r := v.(map[string]any)
			delete(r, "source_entry")
			delete(r, "real_entry_stage")
		}
	}
	for _, v := range out["decisions"].([]any) {
		d := v.(map[string]any)
		delete(d, "source_context")
		for _, c := range d["candidates"].([]any) {
			delete(c.(map[string]any), "source_check")
		}
	}
}

// projectSource87は旧86全文への比較投影を作ります。
//
// 引数: value(any)は新旧保存会計です。
// 返り値: map[string]anyは87新欄以外を全て保持した値です。
func projectSource87(value any) map[string]any {
	data, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	var out map[string]any
	if err = json.Unmarshal(data, &out); err != nil {
		panic(err)
	}
	stripSource87(out)
	return out
}

// snapshot87は現在量・初期量・親初回を区別したSource人工を作ります。
//
// 引数: q(Quote)、side/quantity(int)、id(string)は当原行と参照所有です。
// 返り値: ReadSnapshotは生存一玉の人工値です。Source自然発生の証明ではありません。
func snapshot87(q Quote, side, quantity int, id string) ReadSnapshot {
	parent := 50
	desired := 32
	r := ReferenceLot{ID: id, InternalID: "内部_" + id, Parent: "親", SourceID: "源_" + id, Method: "NK225_D164_15", Owner: "core", Kind: "source_add", Side: side, Quantity: quantity, Entry: 10005, At: q.Time - 10}
	row := ReadLot{Reference: r, ReferenceInitialQuantity: 100, NativeParentInitialMicro: &parent, NativeParentOriginalDesired: &desired}
	return ReadSnapshot{Method: r.Method, At: q.Time, SourceIndex: 70 + q.Index, Started: true, Lots: []ReadLot{row}, Closes: []ReferenceClose{}}
}

// c087は最終C0と同原行の品質bindingを持つ金融境界人工を作ります。
//
// 引数: q(Quote)、at(float64)、side(int)、allowed/unknown(bool)、tech(TechnicalView)は当時値です。
// 返り値: Decisionは方向行より最終判定を優先する人工です。
func c087(q Quote, at float64, side int, allowed, unknown bool, tech TechnicalView) Decision {
	c := Decision{Policy: "C0", Allowed: allowed, Side: side, Role: "順行", RequiredUnknown: unknown, Reason: "人工の最終C0"}
	c.Base.At = at
	c.Base.Quote = q
	c.Base.Technical = tech
	c.Base.Evidence = current86(q, side, 0, 0, true, true)
	return c
}

// openSource87は指定量を次正常原行で取得します。
//
// 引数: t(*testing.T)、policy(string)、side/quantity(int)は会計政策と参照現在量です。
// 返り値: *Bookは非0実所有、ReadSnapshotは要求時出典です。
func openSource87(t *testing.T, policy string, side, quantity int) (*Book, ReadSnapshot) {
	t.Helper()
	b, err := NewSourceBook("人工87", policy, 100)
	need85(t, err)
	q := quote85(1, 10000, 10010)
	tech := TechnicalView{ATRKnown: true, ATR3: 100}
	need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
	s := snapshot87(q, side, quantity, "参照玉")
	need85(t, b.OnSourceGrid(q.Time, q, s, c087(q, q.Time, side, true, false, tech), tech, StructureAnchor{}))
	need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, tech))
	if b.Result().Metrics.OpenQuantity != quantity {
		t.Fatal("可変量の実所有がない")
	}
	return b, s
}

// TestSource87Constructorsは専用API・内部政策・保護off・混用拒否を確認します。
//
// 引数: t(*testing.T)は人工検査です。
// 返り値: ありません。100以外・不正政策・旧API混用を検出します。
func TestSource87Constructors(t *testing.T) {
	for _, policy := range []string{"S", "SC"} {
		b, err := NewSourceBook("人工87", policy, 100)
		need85(t, err)
		if b.Result().Mode != "S0G1" || b.Result().HoldEnabled || b.Result().ConfirmEnabled || b.SetConfirmEnabled(true) == nil {
			t.Fatal("Source金融の保護契約が不整合")
		}
		if b.OnGrid(1000, quote85(1, 10000, 10010), ReferenceFrame{}, TechnicalView{}, StructureAnchor{}, HoldAnchor{}, CurrentEvidence{}) == nil {
			t.Fatal("Sourceで旧OnGridを使用")
		}
	}
	for _, policy := range []string{"", "C0", "s"} {
		if _, err := NewSourceBook("人工87", policy, 100); err == nil {
			t.Fatal("不正政策を受理")
		}
	}
	if _, err := NewSourceBook("人工87", "S", 1); err == nil {
		t.Fatal("capを変更")
	}
	b, err := NewBook("人工87", "S0G1", 100, false)
	need85(t, err)
	if b.OnSourceGrid(1000, quote85(1, 10000, 10010), ReadSnapshot{}, Decision{}, TechnicalView{}, StructureAnchor{}) == nil {
		t.Fatal("旧会計でSourceAPIを使用")
	}
}

// TestSource87SAndFinalSCはSの未知C0非使用とSCの最終判定だけによる選別を検査します。
//
// 引数: t(*testing.T)は買売鏡像・古いC0・競合の人工です。
// 返り値: ありません。Sへの隠れC0gate又は方向行単独採用を検出します。
func TestSource87SAndFinalSC(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, policy := range []string{"S", "SC"} {
			q := quote85(1, 10000, 10010)
			b, err := NewSourceBook("人工87", policy, 100)
			need85(t, err)
			need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
			s := snapshot87(q, side, 20, "参照玉")
			s.Lots[0].NativeParentInitialMicro = nil
			c := c087(q, q.Time, side, false, true, TechnicalView{})
			c.Directions = []far84.Direction{{Allowed: true}}
			if policy == "S" {
				c.Base.At--
			}
			need85(t, b.OnSourceGrid(q.Time, q, s, c, TechnicalView{}, StructureAnchor{}))
			r := b.Result()
			if policy == "S" {
				if len(r.Orders) != 1 || r.Orders[0].Quantity != 20 || r.Orders[0].HoldAnchor.Known || r.Orders[0].HoldAnchor.Reason != sourceHoldUnusedReason || r.Decisions[0].SourceContext.RequiredUnknown {
					t.Fatal("SにC0又は親初回未知gateを課した", r)
				}
			} else if len(r.Orders) != 0 || r.Decisions[0].Action != "判定不能" || !r.Decisions[0].SourceContext.RequiredUnknown {
				t.Fatal("SC最終不許可を方向行で突破", r)
			}
		}
	}
	q := quote85(1, 10000, 10010)
	b, err := NewSourceBook("人工87", "SC", 100)
	need85(t, err)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	c := c087(q, q.Time, 1, true, false, TechnicalView{})
	c.Base.At--
	if b.OnSourceGrid(q.Time, q, snapshot87(q, 1, 20, "参照玉"), c, TechnicalView{}, StructureAnchor{}) == nil {
		t.Fatal("SCへ古い最終C0を流用")
	}
}

// TestSource87SortedPoolAndImmutableは全poolの安定順位と要求時出典の値保存を検査します。
//
// 引数: t(*testing.T)はClosing・SC不許可・同時計別IDの人工です。
// 返り値: ありません。poolの消失・順序・親量pointer共有を検出します。
func TestSource87SortedPoolAndImmutable(t *testing.T) {
	b, err := NewSourceBook("人工87", "SC", 100)
	need85(t, err)
	q := quote85(1, 10000, 10010)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	s := snapshot87(q, 1, 17, "b")
	a := cloneSourceLot(s.Lots[0])
	a.Reference.ID = "a"
	a.Reference.Side = -1
	c := cloneSourceLot(s.Lots[0])
	c.Reference.ID = "c"
	c.Reference.Closing = true
	s.Lots = []ReadLot{c, s.Lots[0], a}
	need85(t, b.OnSourceGrid(q.Time, q, s, c087(q, q.Time, 1, true, false, TechnicalView{}), TechnicalView{}, StructureAnchor{}))
	*s.Lots[1].NativeParentInitialMicro = 999
	s.Lots[1].Reference.Quantity = 99
	r := b.Result()
	d := r.Decisions[0]
	if len(d.Candidates) != 3 || d.Candidates[0].ReferenceID != "a" || d.Candidates[1].ReferenceID != "b" || d.Candidates[2].ReferenceID != "c" || r.Orders[0].Quantity != 17 || r.Orders[0].SourceEntry.Rank != 2 || *r.Orders[0].SourceEntry.ReadLot.NativeParentInitialMicro != 50 {
		t.Fatal("全pool順位又は出典複写が不整合", r)
	}
	if r.Orders[0].RealEntryStage != "初参加要求" || r.Orders[0].Role != "source_add" || r.Orders[0].SourceEntry.C0Role != "順行" {
		t.Fatal("選定参照Kindと技法role又は実段階を混同")
	}
	need85(t, b.OnQuote(quote85(2, 10000, 10010), ReferenceFrame{}, TechnicalView{}))
	r = b.Result()
	if r.Lots[0].RealEntryStage != "実初参加" || r.Lots[0].SourceEntry.ReferenceKind != "source_add" {
		t.Fatal("source_addを元初回へ呼替え")
	}
}

// TestSource87VariableG1は32枚G1の整数計画と896円の手計算を検査します。
//
// 引数: t(*testing.T)は買売鏡像の人工です。
// 返り値: ありません。100枚への補正・費用・G1式変更を検出します。
func TestSource87VariableG1(t *testing.T) {
	for _, side := range []int{1, -1} {
		b, snapshot := openSource87(t, "S", side, 32)
		for _, step := range []struct {
			index int64
			gain  float64
		}{{3, 20}, {4, 20}, {5, 0}, {6, 0}} {
			need85(t, b.OnQuote(gain85(step.index, side, step.gain), ReferenceFrame{}, TechnicalView{}))
		}
		r := b.Result()
		if r.Unresolved || r.Orders[1].Quantity != 24 || r.Orders[2].Quantity != 8 || r.Metrics.NetPnLYen != 896 || r.Metrics.EntryQuantity != 32 || r.Closed[0].SourceEntry.RequestedQuantity != 32 || r.Closed[0].RealEntryStage != "実初参加" {
			t.Fatal("32枚G1手計算と不一致", side, r)
		}
		last := gain85(6, side, 0)
		snapshot.At = last.Time
		snapshot.SourceIndex = 76
		need85(t, b.OnSourceGrid(1015, last, snapshot, Decision{}, TechnicalView{}, StructureAnchor{}))
		if len(b.Result().Orders) != 3 || !b.Result().Decisions[1].Candidates[0].SourceCheck.Seen {
			t.Fatal("G1利益退出後の同参照IDへ再参加")
		}
	}
}

// TestSource87TimerAndSeenはtimerがfillせず元要求時刻を保持し、取消後もIDを消費することを検査します。
//
// 引数: t(*testing.T)は未約定取消・遅いForce通知の人工です。
// 返り値: ありません。旧q.Timeへの要求巻戻し又は同参照再参加を検出します。
func TestSource87TimerAndSeen(t *testing.T) {
	b, err := NewSourceBook("人工87", "S", 100)
	need85(t, err)
	q := quote85(1, 10000, 10010)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	s := snapshot87(q, 1, 32, "参照玉")
	need85(t, b.OnSourceGrid(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	c := ReferenceClose{ID: "取消部分", ReferenceID: "参照玉", Before: 32, Quantity: 10, Reason: "人工部分"}
	need85(t, b.OnReference(1005, q, []ReferenceClose{c}))
	r := b.Result()
	e := r.SourceEffects[0]
	if r.Metrics.EntryQuantity != 0 || e.At != 1005 || e.QuoteTime != 1000 || e.Cancelled != 10 || e.PendingBefore != 32 || r.Orders[0].Remaining != 22 || b.last.Time != 1000 {
		t.Fatal("timerでfill又は要求時計を巻戻した", r)
	}
	q = quote85(2, 10000, 10010)
	q.Time = 1006
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	if b.Result().Lots[0].InitialQuantity != 22 || b.Result().Lots[0].SourceEntry.RequestedQuantity != 32 {
		t.Fatal("取消後実取得と要求時出典を混同")
	}
	need85(t, b.OnReference(1010, q, []ReferenceClose{{ID: "全残", ReferenceID: "参照玉", Before: 22, Quantity: 22, Reason: "人工全残"}}))
	r = b.Result()
	if r.Orders[1].RequestTime != 1010 || r.Orders[1].RequestLine != q.Line || r.SourceEffects[1].ExitRequested != 22 {
		t.Fatal("timer要求が実時刻を保持しない", r)
	}
	if b.OnReference(1010, q, []ReferenceClose{c}) == nil {
		t.Fatal("通知ID重複を受理")
	}
	q = quote85(3, 10000, 10010)
	q.Time = 1011
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	s.At = q.Time
	s.SourceIndex++
	need85(t, b.OnSourceGrid(1015, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	r = b.Result()
	if len(r.Orders) != 2 || r.Decisions[1].Candidates[0].SourceCheck.Seen != true {
		t.Fatal("同じ参照IDへ再参加")
	}
	// ----------------------------------------
	b, err = NewSourceBook("人工87", "S", 100)
	need85(t, err)
	q = quote85(1, 10000, 10010)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	s = snapshot87(q, 1, 1, "一枚")
	need85(t, b.OnSourceGrid(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	need85(t, b.OnReference(1001, q, []ReferenceClose{{ID: "全取消", ReferenceID: "一枚", Before: 1, Quantity: 1}}))
	s.At = q.Time
	need85(t, b.OnSourceGrid(1002, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	if len(b.Result().Orders) != 1 || b.Result().Orders[0].RealEntryStage != "初参加要求" || len(b.Result().Lots) != 0 {
		t.Fatal("取消を実参加へ昇格又はseenを解除")
	}
}

// TestSource87CloseRoundingAndPriorityは0丸め・末尾全残・G1予約控除・無所有通知を検査します。
//
// 引数: t(*testing.T)は部分返済と連続Source通知の人工です。
// 返り値: ありません。通知効果の欠落・予約二重化・全残丸め残しを検出します。
func TestSource87CloseRoundingAndPriority(t *testing.T) {
	b, _ := openSource87(t, "S", 1, 32)
	need85(t, b.OnQuote(gain85(3, 1, 20), ReferenceFrame{}, TechnicalView{}))
	if b.Result().Metrics.ReservedExitQuantity != 24 {
		t.Fatal("G1予約がない")
	}
	q := gain85(4, 1, 20)
	closes := []ReferenceClose{{ID: "小比率", ReferenceID: "参照玉", Before: 32, Quantity: 1}, {ID: "末尾", ReferenceID: "参照玉", Before: 31, Quantity: 31}, {ID: "無所有", ReferenceID: "他", Before: 20, Quantity: 20}}
	need85(t, b.OnQuote(q, ReferenceFrame{Closes: closes}, TechnicalView{}))
	r := b.Result()
	if len(r.SourceEffects) != 3 || r.SourceEffects[0].UnreservedBefore != 8 || r.SourceEffects[0].ExitRequested != 0 || r.SourceEffects[1].ExitRequested != 8 || r.SourceEffects[1].OrdersAfterCount != r.SourceEffects[1].OrdersBeforeCount+1 || r.SourceEffects[2].ExitRequested != 0 || r.Orders[2].Reason != "参照返済:" {
		t.Fatal("Source通知作用と順序が不整合", r)
	}
	if r.Metrics.ReservedExitQuantity != 8 || r.Metrics.OpenQuantity != 8 {
		t.Fatal("G1予約と二重計上")
	}
}

// TestSource87PoolCorruptionは0補正・未来・重複・Source価格と実建値の混同を拒否します。
//
// 引数: t(*testing.T)はpoolの破損人工です。
// 返り値: ありません。不正源を新規として受理すれば失敗します。
func TestSource87PoolCorruption(t *testing.T) {
	for _, change := range []func(*ReadSnapshot){func(s *ReadSnapshot) { s.Lots[0].Reference.Quantity = 0 }, func(s *ReadSnapshot) { s.Lots[0].Reference.Quantity = 101 }, func(s *ReadSnapshot) { s.At++ }, func(s *ReadSnapshot) { s.Lots = append(s.Lots, s.Lots[0]) }, func(s *ReadSnapshot) { s.Lots[0].ReferenceInitialQuantity = 1 }} {
		b, err := NewSourceBook("人工87", "S", 100)
		need85(t, err)
		q := quote85(1, 10000, 10010)
		need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
		s := snapshot87(q, 1, 32, "参照玉")
		change(&s)
		if b.OnSourceGrid(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}) == nil {
			t.Fatal("不正poolを受理")
		}
	}
}

// TestSource87LegacyFullProjectionは旧APIの非0会計を86と全文比較します。
//
// 引数: t(*testing.T)は買売×遅延の旧回帰人工です。
// 返り値: ありません。旧費用・G1・所有・入力APIの変更を検出します。
func TestSource87LegacyFullProjection(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delay := range []float64{0, 1} {
			b, err := NewBook("旧回帰", "S0G1", 100, false)
			need85(t, err)
			old, err := far86.NewBook("旧回帰", "S0G1", 100, false)
			need85(t, err)
			need85(t, b.SetFillDelay(delay))
			need85(t, old.SetFillDelay(delay))
			q := quote85(1, 10000, 10010)
			c := evidence85(q, side)
			a, err := BuildHoldAnchor(q.Time, q, c, side)
			need85(t, err)
			oa, err := far86.BuildHoldAnchor(q.Time, q, c, side)
			need85(t, err)
			tech := TechnicalView{ATRKnown: true, ATR3: 100}
			f := candidate85(q.Time, side, q)
			need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
			need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
			need85(t, b.OnGrid(q.Time, q, f, tech, StructureAnchor{}, a, c))
			need85(t, old.OnGrid(q.Time, q, f, tech, StructureAnchor{}, oa, c))
			for _, step := range []struct {
				index int64
				gain  float64
			}{{2, -10}, {3, 20}, {4, 20}, {5, 0}, {6, 0}} {
				q = gain85(step.index, side, step.gain)
				need85(t, b.OnQuote(q, ReferenceFrame{}, tech))
				need85(t, old.OnQuote(q, ReferenceFrame{}, tech))
			}
			if !reflect.DeepEqual(projectSource87(b.Result()), projectSource87(old.Result())) {
				t.Fatal("旧86全文が不同値", side, delay)
			}
		}
	}
}

// TestSource87QuantityExtremesは1〜100の量を補正せず保持し、G1整数端点を確認します。
//
// 引数: t(*testing.T)は買売×量の人工です。
// 返り値: ありません。1枚を0へ、可変量を100へ変える場合に失敗します。
func TestSource87QuantityExtremes(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, quantity := range []int{1, 10, 20, 32, 100} {
			b, _ := openSource87(t, "S", side, quantity)
			need85(t, b.OnQuote(gain85(3, side, 20), ReferenceFrame{}, TechnicalView{}))
			r := b.Result()
			target := (222*quantity + 1 + 299) / 300
			if target > quantity {
				target = quantity
			}
			if r.Metrics.EntryQuantity != quantity || r.Orders[1].Quantity != target || r.Lots[0].Floor < 0 {
				t.Fatal("可変量又はG1切上げが不整合", quantity, r)
			}
			need85(t, b.OnQuote(gain85(4, side, 20), ReferenceFrame{}, TechnicalView{}))
			if quantity == 1 && b.Result().Unresolved {
				t.Fatal("1枚利確で架空残玉")
			}
		}
	}
}

// TestSource87OccupancyAndQualityは残り枠があっても同時一建玉と品質の優先を維持します。
//
// 引数: t(*testing.T)は保有/新規待機/Last不正の人工です。
// 返り値: ありません。保有中追加・未知を待ちに補完する場合に失敗します。
func TestSource87OccupancyAndQuality(t *testing.T) {
	b, _ := openSource87(t, "S", 1, 10)
	q := quote85(2, 10000, 10010)
	s := snapshot87(q, 1, 20, "別玉")
	need85(t, b.OnSourceGrid(1005, q, s, Decision{RequiredUnknown: true}, TechnicalView{}, StructureAnchor{}))
	r := b.Result()
	if len(r.Orders) != 1 || r.Decisions[1].Action != "保有継続" || r.Decisions[1].Candidates[0].SourceCheck.Eligible || r.Decisions[1].SourceContext.SeenAfterCount != 1 {
		t.Fatal("空き90枚を保有中追加へ利用", r)
	}
	b, err := NewSourceBook("人工87", "S", 100)
	need85(t, err)
	q = quote85(1, 10000, 10010)
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	s = snapshot87(q, 1, 10, "先行")
	need85(t, b.OnSourceGrid(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	s = snapshot87(q, 1, 20, "後続")
	need85(t, b.OnSourceGrid(1001, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	if b.Result().Decisions[1].Action != "処理中" || len(b.Result().Orders) != 1 {
		t.Fatal("新規待機中の追加を許可")
	}
	b, err = NewSourceBook("人工87", "S", 100)
	need85(t, err)
	q = quote85(1, 10000, 10010)
	q.Valid = false
	q.Last = 0
	need85(t, b.OnQuote(q, ReferenceFrame{}, TechnicalView{}))
	s = snapshot87(q, 1, 20, "候補")
	need85(t, b.OnSourceGrid(q.Time, q, s, Decision{}, TechnicalView{}, StructureAnchor{}))
	if b.Result().Decisions[0].Action != "判定不能" || len(b.Result().Orders) != 0 {
		t.Fatal("Last不正を正常候補へ補完")
	}
}

// TestSource87MultipleCloseAndForceは同原行先行通知と後段G1、実Force後通知0作用を分けます。
//
// 引数: t(*testing.T)は2通知の比率と境界の人工です。
// 返り値: ありません。先行予約の重複やSource通知の欠落を検出します。
func TestSource87MultipleCloseAndForce(t *testing.T) {
	b, _ := openSource87(t, "S", 1, 32)
	q := gain85(3, 1, 20)
	cs := []ReferenceClose{{ID: "前半", ReferenceID: "参照玉", Before: 32, Quantity: 16}, {ID: "全残", ReferenceID: "参照玉", Before: 16, Quantity: 16}}
	need85(t, b.OnQuote(q, ReferenceFrame{Closes: cs}, TechnicalView{}))
	r := b.Result()
	if len(r.Orders) != 3 || r.Orders[1].Quantity != 16 || r.Orders[2].Quantity != 16 || r.Metrics.HarvestOrders != 0 || r.SourceEffects[0].OrdersBeforeCount != 1 || r.SourceEffects[0].OrdersAfterCount != 2 || r.SourceEffects[1].OrdersBeforeCount != 2 || r.SourceEffects[1].OrdersAfterCount != 3 {
		t.Fatal("Source2通知とG1優先が不整合", r)
	}
	b, _ = openSource87(t, "S", 1, 32)
	q = quote85(2, 10000, 10010)
	need85(t, b.Force(1010, q, "境界実Force"))
	need85(t, b.OnReference(1010, q, []ReferenceClose{{ID: "SourceForce", ReferenceID: "参照玉", Before: 32, Quantity: 32}}))
	r = b.Result()
	if len(r.Orders) != 2 || r.Orders[1].RequestTime != 1010 || len(r.SourceEffects) != 1 || r.SourceEffects[0].UnreservedBefore != 0 || r.SourceEffects[0].ExitRequested != 0 || r.SourceEffects[0].OrdersBeforeCount != r.SourceEffects[0].OrdersAfterCount {
		t.Fatal("実Force後SourceForceを二重返済", r)
	}
	if b.OnReference(1011, quote85(3, 10000, 10010), nil) == nil {
		t.Fatal("timerへ別のqを偽装")
	}
	if b.OnReference(1011, q, []ReferenceClose{{ID: "異常上限", ReferenceID: "参照玉", Before: 101, Quantity: 1}}) == nil {
		t.Fatal("Source元玉100上限の不整合を受理")
	}
}
