package mininative

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// fakeBook は元判断を捏造せず、約定/所有接続だけを手計算する器具です。
type fakeBook struct {
	script     map[int64][]Signal
	cancelAt   map[int64][]string
	owned      []strategy.SelectedLot
	orders     map[string]Signal
	done       map[string]bool
	cancels    []string
	observed   []int64
	fills      []Fill
	rejected   []string
	lastIndex  int64
	forced     bool
	forceCount int
}

// lots は人工所有を値コピーします。
//
// 引数: ありません。
// 返り値: []strategy.SelectedLotは人工の現在所有です。
func (b *fakeBook) lots() []strategy.SelectedLot { return append([]strategy.SelectedLot{}, b.owned...) }

// ObserveWithFreshness は人工の発行原行を元APIと同じ契約で進めます。
//
// 引数: o(Observation)、allow/fresh(bool)は当行と旧接続旗です。
// 返り値: []Signal/errorは今回の人工要求だけです。
func (b *fakeBook) ObserveWithFreshness(o Observation, allow, fresh bool) ([]Signal, error) {
	if !allow || !fresh {
		return nil, fmt.Errorf("元全原行判断を変更しました")
	}
	b.observed = append(b.observed, o.Index)
	b.lastIndex = o.Index
	b.cancels = append([]string{}, b.cancelAt[o.Index]...)
	out := []Signal{}
	for _, s := range b.script[o.Index] {
		if b.forced && s.Action == "new" {
			continue
		}
		s.Time, s.SourceIndex = o.Time, o.Index
		s.Evidence = json.RawMessage(`{"人工":true}`)
		b.orders[s.ID] = s
		out = append(out, s)
	}
	return out, nil
}

// OnFill は費用0・実BBOの約定を人工の同じHoldIDへ反映します。
//
// 引数: f(Fill)は当行の実約定です。
// 返り値: errorは注文/所有/費用の不整合です。
func (b *fakeBook) OnFill(f Fill) error {
	s, ok := b.orders[f.SignalID]
	if !ok || b.done[s.ID] || f.Fee != 0 {
		return fmt.Errorf("人工Fill契約違反")
	}
	if s.Action == "new" {
		b.owned = append(b.owned, strategy.SelectedLot{ID: f.ExecutionID, HoldID: f.HoldID, EntryID: s.ID, Parent: "親", SourceID: "元源", Kind: "source_add", Owner: s.Owner, Side: s.Side, Quantity: f.Quantity, InitialQuantity: f.Quantity, Entry: f.Price, At: f.Time})
	} else {
		if !reflect.DeepEqual(f.Closed, s.Targets) {
			return fmt.Errorf("返済所有を変更しました")
		}
		for _, target := range f.Closed {
			found := false
			for i := range b.owned {
				l := &b.owned[i]
				if l.HoldID == target.ID {
					if target.Quantity > l.Quantity {
						return fmt.Errorf("過剰返済")
					}
					l.Quantity -= target.Quantity
					l.Realized += float64(l.Side) * (f.Price - l.Entry) * float64(target.Quantity) * 100
					found = true
				}
			}
			if !found {
				return fmt.Errorf("未知所有")
			}
		}
	}
	b.fills = append(b.fills, clone(f))
	return nil
}

// OnOrderDone は全量約定又は取消後の注文終了を記録します。
//
// 引数: id(string)は元Signal IDです。
// 返り値: errorは二重又は未知ID終了です。
func (b *fakeBook) OnOrderDone(id string) error {
	if _, ok := b.orders[id]; !ok || b.done[id] {
		return fmt.Errorf("未知又は二重終了")
	}
	b.done[id] = true
	kept := []string{}
	for _, v := range b.cancels {
		if v != id {
			kept = append(kept, v)
		}
	}
	b.cancels = kept
	return nil
}

// OnOrderRejected は取消を実約定に数えず注文を終了します。
//
// 引数: id(string)は元新規IDです。
// 返り値: errorは元終了の失敗です。
func (b *fakeBook) OnOrderRejected(id string) error {
	b.rejected = append(b.rejected, id)
	return b.OnOrderDone(id)
}

// SelectedCancellationIDs は未処理の人工取消を返します。
//
// 引数: ありません。
// 返り値: []stringは現在の取消要求です。
func (b *fakeBook) SelectedCancellationIDs() []string { return append([]string{}, b.cancels...) }

// Flatten は既存予約を引いた現在所有だけの返済を発行します。
//
// 引数: at(float64)、reason(string)は境界時計と理由です。
// 返り値: []Signalは新しい未予約分だけです。
func (b *fakeBook) Flatten(at float64, reason string) []Signal {
	b.forced = true
	b.forceCount++
	reserved := map[string]int{}
	for id, s := range b.orders {
		if !b.done[id] && s.Action == "close" {
			for _, v := range s.Targets {
				reserved[v.ID] += v.Quantity
			}
		}
	}
	out := []Signal{}
	for _, l := range b.owned {
		qty := l.Quantity - reserved[l.HoldID]
		if qty <= 0 {
			continue
		}
		s := Signal{ID: fmt.Sprintf("強制%d-%s", b.forceCount, l.HoldID), Owner: "core", Action: "close", Side: -l.Side, Quantity: qty, Time: at, SourceIndex: b.lastIndex, Reason: reason, Targets: []strategy.LotTarget{{ID: l.HoldID, Quantity: qty}}}
		b.orders[s.ID] = s
		out = append(out, s)
	}
	return out
}

// artificial は元公開constructor後に約定接続だけを人工bookへ差し替えます。
//
// 引数: t(*testing.T)、config(ProductConfig)は試験器と商品規格です。
// 返り値: *Adapter/*fakeBookは新しい空会計です。元信号の自然発生の証明ではありません。
func artificial(t *testing.T, config ProductConfig) (*Adapter, *fakeBook) {
	t.Helper()
	r, err := NewAdapter("D164_15", Session{ID: "人工_Day", Kind: "Day", Start: 1000, ForceClose: 20000, End: 20600}, config)
	if err != nil {
		t.Fatal(err)
	}
	b := &fakeBook{script: map[int64][]Signal{}, cancelAt: map[int64][]string{}, orders: map[string]Signal{}, done: map[string]bool{}, lastIndex: -1}
	r.book = b
	return r, b
}

// observation は売買を価格2000に対して鏡像にした原行です。
//
// 引数: side(int)、index(int64)、move(float64)、good(bool)は人工条件です。
// 返り値: Observationは一つの受理原行です。
func observation(side int, index int64, move float64, good bool) Observation {
	bid, ask := 1000+move, 1010+move
	if side < 0 {
		bid, ask = 2000-ask, 2000-bid
	}
	if !good {
		ask = bid - 1
	}
	o := Observation{Reference: "NK225", Time: 1100 + float64(index), Received: 1100 + float64(index), Index: index, Last: (bid + ask) / 2, Bid: bid, Ask: ask, QuoteOK: good}
	// 夜間特徴の既知状態は空のまま、公開APIの当原行出典だけを結びます。
	o.Selected.NightAvailable, o.Selected.NightTime, o.Selected.NightIndex = true, o.Time, o.Index
	return o
}

// newSignal は元段階を変えない人工の新規通知です。
//
// 引数: id(string)、side/qty(int)は通知ID・方向・枚数です。
// 返り値: Signalは時刻がObserve時に固定される人工要求です。
func newSignal(id string, side, qty int) Signal {
	return Signal{ID: id, Owner: "core", Action: "new", Side: side, Quantity: qty, Reason: "人工新規"}
}

// closeSignal は同じ所有HoldIDの一部返済通知です。
//
// 引数: id/hold(string)、side/qty(int)は通知と所有です。
// 返り値: Signalは返済側を所有方向の逆へ固定します。
func closeSignal(id, hold string, side, qty int) Signal {
	return Signal{ID: id, Owner: "core", Action: "close", Side: -side, Quantity: qty, Reason: "人工部分返済", Targets: []strategy.LotTarget{{ID: hold, Quantity: qty}}}
}

// step は人工原行を物理行へ結び正常終了を要求します。
//
// 引数: t(*testing.T)、r(*Adapter)、o(Observation)は試験器と当行です。
// 返り値: StepResultは今回の新通知だけです。
func step(t *testing.T, r *Adapter, o Observation) StepResult {
	t.Helper()
	v, err := r.Step(o, o.Index+20)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

// TestConstructorPublicBranches は純Portfolio正常branchを三手法×両商品で実行します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。空の人工特徴で新規を捏造しません。
func TestConstructorPublicBranches(t *testing.T) {
	for _, method := range []string{"D164_15", "P164_06", "U165_03"} {
		for _, config := range []ProductConfig{MiniConfig(), MicroControlConfig()} {
			kind := "Night"
			if method == "D164_15" {
				kind = "Day"
			}
			s := Session{ID: "人工_" + kind, Kind: kind, Start: 1000, USOpen: 6000, ExtraAt: 7800, ForceClose: 20000, End: 20600}
			r, err := NewAdapter(method, s, config)
			if err != nil {
				t.Fatal(err)
			}
			p := r.book.(*portfolioBook).Portfolio
			if p.Config.Product != config.Product || p.Config.Cap != config.Cap || p.Config.CoreQuantity != config.CoreQuantity || p.Selected.Shadow.Config.Product != "NK225mini" || p.Selected.Shadow.Config.Cap != 10 {
				t.Fatal("商品又は元尺度を変更")
			}
			if method == "P164_06" && r.deadline != s.USOpen-900 || method != "P164_06" && r.deadline != s.ForceClose {
				t.Fatal("米国前/場末時計を変更")
			}
			for i := int64(0); i < 3; i++ {
				step(t, r, observation(1, i, 0, i != 1))
			}
			if p.LastIndex != 2 {
				t.Fatal("異常BBOで元Observeを省略")
			}
			if _, err = r.Force(1110); err != nil {
				t.Fatal(err)
			}
			v, err := r.Finish()
			if err != nil || !v.Complete || !v.Finished || len(v.Fills) != 0 {
				t.Fatal(v, err)
			}
		}
	}
	bad := MiniConfig()
	bad.Cap = 11
	if _, err := NewAdapter("D164_15", Session{}, bad); err == nil {
		t.Fatal("規格破損")
	}
}

// TestMiniPartialAndMirror は元通知を次正常板で約定し同じHoldIDを部分返済します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestMiniPartialAndMirror(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, b := artificial(t, MiniConfig())
		b.script[0] = []Signal{newSignal("入口", side, 10)}
		b.script[2] = []Signal{closeSignal("部分", "入口-玉", side, 3)}
		b.script[4] = []Signal{closeSignal("残り", "入口-玉", side, 7)}
		if out := step(t, r, observation(side, 0, 0, true)); len(out.Fills) != 0 || len(out.Signals) != 1 {
			t.Fatal(out)
		}
		if out := step(t, r, observation(side, 1, 0, false)); len(out.Fills) != 0 {
			t.Fatal("異常BBOで新規Fill")
		}
		out := step(t, r, observation(side, 2, 0, true))
		if len(out.Fills) != 1 || out.Closes[0].Before != 10 || out.Closes[0].Quantity != 3 {
			t.Fatal(out)
		}
		if out := step(t, r, observation(side, 3, 20, false)); len(out.Fills) != 0 {
			t.Fatal("異常BBOで返済Fill")
		}
		out = step(t, r, observation(side, 4, 40, true))
		if len(out.Fills) != 1 || out.Closes[0].Before != 7 {
			t.Fatal(out)
		}
		partial := r.Snapshot()
		if partial.Totals.ClosedNetYen != 5769 || partial.Totals.OpenEntryCostsYen != 3769.5 || partial.Totals.NetYen != 1999.5 || partial.Totals.NetYen != partial.Totals.ClosedNetYen-partial.Totals.OpenEntryCostsYen {
			t.Fatal("部分返済の新規費用配賦が不一致", partial)
		}
		step(t, r, observation(side, 5, 50, true))
		v, err := r.Finish()
		if err != nil {
			t.Fatal(err)
		}
		if v.Totals.GrossYen != 37000 || v.Totals.FeeYen != 770 || v.Totals.SlippageYen != 10000 || v.Totals.GrossMinusFeeYen != 36230 || v.Totals.NetYen != 26230 || v.Totals.ClosedNetYen != 26230 || v.Holds[0].Quantity != 0 || len(v.Holds) != 1 || v.Holds[0].Kind != "source_add" {
			t.Fatal(v)
		}
		if len(b.observed) != 6 || len(b.fills) != 3 {
			t.Fatal("元全行/全Fillを省略")
		}
		for _, f := range b.fills {
			if f.Fee != 0 {
				t.Fatal("外費用を元判断へ混入")
			}
		}
		if v.Fills[1].Allocations[0].HoldID != v.Fills[2].Allocations[0].HoldID {
			t.Fatal("別新規へ再取得")
		}
		if _, err = r.Step(observation(side, 6, 60, true), 30); err == nil {
			t.Fatal("終了後再利用")
		}
	}
}

// TestRoundTripCostUnits はmini77/1000とmicro22/100の往復費用を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestRoundTripCostUnits(t *testing.T) {
	for _, cfg := range []ProductConfig{MiniConfig(), MicroControlConfig()} {
		r, b := artificial(t, cfg)
		b.script[0] = []Signal{newSignal("入口", 1, 1)}
		b.script[1] = []Signal{closeSignal("返済", "入口-玉", 1, 1)}
		step(t, r, observation(1, 0, 0, true))
		step(t, r, observation(1, 1, 0, true))
		step(t, r, observation(1, 2, 40, true))
		v, err := r.Finish()
		if err != nil {
			t.Fatal(err)
		}
		if v.Totals.FeeYen != 2*cfg.FeeYenPerSide || v.Totals.SlippageYen != 10*cfg.PointValue || v.Fills[0].Fill.Price != 1010 || v.Fills[1].Fill.Price != 1040 {
			t.Fatal("費用を価格へ二重計上", v)
		}
		if cfg.Product == "NK225mini" && (v.Totals.FeeYen != 77 || v.Totals.SlippageYen != 1000 || v.Totals.NetYen != 1923) {
			t.Fatal(v)
		}
	}
}

// TestBothSidesCapReservations は両方向各10枚と新規予約込み上限を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestBothSidesCapReservations(t *testing.T) {
	r, b := artificial(t, MiniConfig())
	b.script[0] = []Signal{newSignal("買", 1, 10), newSignal("売", -1, 10)}
	step(t, r, observation(1, 0, 0, true))
	v := r.Snapshot()
	if v.Totals.PendingBuyQuantity != 10 || v.Totals.PendingSellQuantity != 10 {
		t.Fatal(v)
	}
	step(t, r, observation(1, 1, 0, true))
	v = r.Snapshot()
	if v.Totals.OpenBuyQuantity != 10 || v.Totals.OpenSellQuantity != 10 {
		t.Fatal(v)
	}
	if _, err := r.Force(1102); err != nil {
		t.Fatal(err)
	}
	step(t, r, observation(1, 2, 0, true))
	if _, err := r.Finish(); err != nil {
		t.Fatal(err)
	}
	for _, pending := range []bool{true, false} {
		r, b = artificial(t, MiniConfig())
		b.script[0] = []Signal{newSignal("満", 1, 10)}
		if pending {
			b.script[0] = append(b.script[0], newSignal("超", 1, 1))
		} else {
			b.script[1] = []Signal{closeSignal("予約返済", "満-玉", 1, 10), newSignal("超", 1, 1)}
		}
		_, err := r.Step(observation(1, 0, 0, true), 20)
		if !pending {
			if err != nil {
				t.Fatal(err)
			}
			_, err = r.Step(observation(1, 1, 0, true), 21)
		}
		if err == nil {
			t.Fatal("予約又は実保有の上限超過")
		}
	}
}

// TestCancellationAndForceOrder は取消をFillより先に行い既返済予約を重複しません。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestCancellationAndForceOrder(t *testing.T) {
	r, b := artificial(t, MiniConfig())
	b.script[0] = []Signal{newSignal("取消", 1, 10)}
	b.cancelAt[0] = []string{"取消"}
	out := step(t, r, observation(1, 0, 0, true))
	if len(out.Cancellations) != 1 || len(r.Snapshot().Pending) != 0 {
		t.Fatal(out)
	}
	step(t, r, observation(1, 1, 0, true))
	if len(b.fills) != 0 {
		t.Fatal("取消後Fill")
	}
	if _, err := r.Finish(); err != nil {
		t.Fatal(err)
	}
	r, b = artificial(t, MiniConfig())
	b.script[0] = []Signal{newSignal("入口", 1, 4)}
	b.script[1] = []Signal{closeSignal("先行部分", "入口-玉", 1, 2)}
	step(t, r, observation(1, 0, 0, true))
	step(t, r, observation(1, 1, 0, true))
	before := len(b.fills)
	out, err := r.Force(1101)
	if err != nil || len(out.Closes) != 1 || out.Closes[0].Before != 2 || out.Closes[0].Quantity != 2 || len(b.fills) != before {
		t.Fatal("Forceの予約/即時Fill", out, err)
	}
	if out, err = r.Force(1101); err != nil || len(out.Signals) != 0 {
		t.Fatal("二重Force", out, err)
	}
	step(t, r, observation(1, 2, 40, true))
	if _, err = r.Finish(); err != nil {
		t.Fatal(err)
	}
	r, b = artificial(t, MiniConfig())
	b.script[0] = []Signal{newSignal("境界前", 1, 1)}
	step(t, r, observation(1, 0, 0, true))
	r.deadline = 1101
	out = step(t, r, observation(1, 1, 0, true))
	if len(out.Fills) != 0 || len(out.Cancellations) != 1 {
		t.Fatal("境界で先に新規Fill", out)
	}
}

// TestFinishUnresolvedAndCopies は不足原行を補わず未完了を返し出力の不変性を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestFinishUnresolvedAndCopies(t *testing.T) {
	r, b := artificial(t, MiniConfig())
	b.script[0] = []Signal{newSignal("入口", 1, 1)}
	first := step(t, r, observation(1, 0, 0, true))
	before, _ := json.Marshal(first)
	if v, err := r.Finish(); err == nil || v.Complete || len(v.Pending) != 1 {
		t.Fatal("予約残を成功化")
	}
	step(t, r, observation(1, 1, 0, true))
	if v, err := r.Finish(); err == nil || v.Complete || v.Totals.OpenBuyQuantity != 1 {
		t.Fatal("保有残を成功化")
	}
	v := r.Snapshot()
	v.Signals[0].Signal.Targets = []strategy.LotTarget{{ID: "改変", Quantity: 9}}
	v.Holds[0].Quantity = 999
	if r.Snapshot().Holds[0].Quantity != 1 {
		t.Fatal("既読の所有を遡及")
	}
	after, _ := json.Marshal(first)
	if !bytes.Equal(before, after) {
		t.Fatal("旧Step出力を遡及")
	}
	if _, err := r.Force(1102); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Finish(); err == nil {
		t.Fatal("返済未Fillを成功化")
	}
	step(t, r, observation(1, 2, 40, true))
	end, err := r.Finish()
	if err != nil || !end.Complete || !end.Finished || end.Totals.OpenEntryCostsYen != 0 {
		t.Fatal(end, err)
	}
}

// TestInputAndOwnershipCorruptions は未来でなく同秒後原行を許し破損を拒否します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestInputAndOwnershipCorruptions(t *testing.T) {
	for _, c := range []struct {
		name   string
		mutate func(*Observation, *int64)
	}{
		{"Index逆行", func(o *Observation, _ *int64) { o.Index = -1 }}, {"物理行なし", func(_ *Observation, line *int64) { *line = 0 }},
		{"時計非有限", func(o *Observation, _ *int64) { o.Time = math.NaN() }}, {"気配非有限", func(o *Observation, _ *int64) { o.Bid = math.Inf(1) }},
	} {
		t.Run(c.name, func(t *testing.T) {
			r, _ := artificial(t, MiniConfig())
			o, line := observation(1, 0, 0, true), int64(20)
			c.mutate(&o, &line)
			if _, err := r.Step(o, line); err == nil {
				t.Fatal("入力破損を受理")
			}
		})
	}
	r, b := artificial(t, MiniConfig())
	b.script[0] = []Signal{newSignal("入口", 1, 1)}
	step(t, r, observation(1, 0, 0, true))
	o := observation(1, 1, 0, true)
	o.Time, o.Received = 1100, 1100
	step(t, r, o)
	if len(r.Snapshot().Fills) != 1 {
		t.Fatal("同秒後原行を拒否")
	}
	b.script[2] = []Signal{closeSignal("誤所有", "他人の玉", 1, 1)}
	if _, err := r.Step(observation(1, 2, 0, true), 22); err == nil {
		t.Fatal("他人所有の返済を受理")
	}
	if _, err := r.Finish(); err == nil {
		t.Fatal("失敗後を成功化")
	}
}

// TestForceSameTimeAndBadBBO はtimerが即時約定せず同秒後原行の正常板を使う点を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Pの米国前終了後も返済だけを継続します。
func TestForceSameTimeAndBadBBO(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, badNext := range []bool{false, true} {
			r, b := artificial(t, MiniConfig())
			// 公開constructorのP本体へ人工通知接続だけを差し替えます。
			p, err := NewAdapter("P164_06", Session{ID: "人工_Night", Kind: "Night", Start: 1000, USOpen: 6000, ForceClose: 20000, End: 20600}, MiniConfig())
			if err != nil {
				t.Fatal(err)
			}
			r = p
			r.book = b
			b.script[0] = []Signal{newSignal("入口", side, 1)}
			step(t, r, observation(side, 0, 0, true))
			step(t, r, observation(side, 1, 0, true))
			out, err := r.Force(5100)
			if err != nil || len(out.Fills) != 0 || len(out.Signals) != 1 {
				t.Fatal(out, err)
			}
			o := observation(side, 2, 40, !badNext)
			o.Time, o.Received = 5100, 5100
			o.Selected.NightTime = 5100
			out = step(t, r, o)
			if badNext {
				if len(out.Fills) != 0 || len(out.Signals) != 0 {
					t.Fatal("P終了後の異常板約定又は新規", out)
				}
				o = observation(side, 3, 40, true)
				o.Time, o.Received = 5100, 5100
				o.Selected.NightTime = 5100
				out = step(t, r, o)
			}
			if len(out.Fills) != 1 || out.Fills[0].Fill.Time != 5100 || len(out.Signals) != 0 {
				t.Fatal("同秒後原行の返済", out)
			}
			v, err := r.Finish()
			if err != nil || v.Totals.NetYen != 1923 {
				t.Fatal(v, err)
			}
		}
	}
}
