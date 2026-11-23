// 87派生元: work/87接続試作/source_test.go
// 87派生元SHA256: 19f0375ee5ba70640b9cd736180cc0ee0d092fd967e6e1ee52041b2f0ccd7276

// 読取試作の派生元: scripts/FAR後期15分移植/source_test.go
// 派生元SHA256: 3a115bae631aac086eaf454008016047753310994d21962d690b58496163a2be
// package名だけを変え、参照仮想運転の本文は変更しません。

package far87

import (
	"errors"
	"fmt"
	"math"
	"reflect"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// fakeReferenceBook は公開会計契約だけを持つ架空の所有・通知列です。
type fakeReferenceBook struct {
	lots       []strategy.SelectedLot
	scripts    map[int64][]strategy.Signal
	cancelAt   map[int64][]string
	cancels    []string
	orders     map[string]strategy.Signal
	fills      []strategy.Fill
	rejected   []string
	observed   []int64
	lastIndex  int64
	forceCount int
	forced     bool
	badFlags   bool
	failAt     int64
}

// newFakeReference は市場を読まない人工参照を作ります。
//
// 引数: lots([]strategy.SelectedLot)は初期所有です。返り値: *Referenceと*fakeReferenceBookです。
func newFakeReference(lots []strategy.SelectedLot) (*Reference, *fakeReferenceBook) {
	b := &fakeReferenceBook{lots: append([]strategy.SelectedLot(nil), lots...), scripts: map[int64][]strategy.Signal{},
		cancelAt: map[int64][]string{}, orders: map[string]strategy.Signal{}, lastIndex: -1, failAt: -1}
	r := &Reference{book: b, method: "NK225_P164_06", deadline: 10000, seen: map[string]bool{}, lastIndex: -1,
		frame: ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}}
	r.refresh()
	return r, b
}

// referenceTestLot は出典を区別できる架空の参照玉を作ります。
//
// 引数: id(string)は所有ID、quantity(int)は残量です。返り値: strategy.SelectedLotです。
func referenceTestLot(id string, quantity int) strategy.SelectedLot {
	return strategy.SelectedLot{ID: "内部_" + id, HoldID: id, EntryID: "入口_" + id, Parent: "親A", SourceID: "源A",
		Owner: "core", Kind: "initial", Side: 1, Quantity: quantity, InitialQuantity: quantity, Entry: 100, At: 99}
}

// referenceTestObservation は同秒でも原行を区別できる架空気配を作ります。
//
// 引数: index(int64)は原行、at(float64)は時計、normal(bool)は正常板かです。返り値: strategy.Observationです。
func referenceTestObservation(index int64, at float64, normal bool) strategy.Observation {
	o := strategy.Observation{Reference: "NK225", Index: index, Time: at, Received: at, Last: 105, Bid: 100, Ask: 110, QuoteOK: normal}
	if !normal {
		o.Ask = 90
	}
	return o
}

// referenceTestSignal は指定原行で作る架空の新規又は所有返済を作ります。
//
// 引数: id/action(string)、quantity(int)、index(int64)、target(string)は通知と対象です。返り値: strategy.Signalです。
func referenceTestSignal(id, action string, quantity int, index int64, target string) strategy.Signal {
	s := strategy.Signal{ID: id, Owner: "core", Action: action, Side: 1, Quantity: quantity, Time: 100, SourceIndex: index, Reason: "架空_" + id}
	if action == "close" {
		s.Side = -1
		s.Targets = []strategy.LotTarget{{ID: target, Quantity: quantity}}
	}
	return s
}

// referenceLots は架空所有をコピーします。
//
// 引数: なし。返り値: []strategy.SelectedLotです。
func (b *fakeReferenceBook) referenceLots() []strategy.SelectedLot {
	return append([]strategy.SelectedLot(nil), b.lots...)
}

// ObserveWithFreshness は指定原行の架空通知だけを発行します。
//
// 引数: o(strategy.Observation)、allow/fresh(bool)は公開会計契約です。返り値: []strategy.Signalとerrorです。
func (b *fakeReferenceBook) ObserveWithFreshness(o strategy.Observation, allow, fresh bool) ([]strategy.Signal, error) {
	b.badFlags = b.badFlags || !allow || !fresh
	b.lastIndex = o.Index
	b.observed = append(b.observed, o.Index)
	if o.Index == b.failAt {
		return nil, errors.New("架空の元会計失敗")
	}
	b.cancels = append([]string(nil), b.cancelAt[o.Index]...)
	var out []strategy.Signal
	for _, s := range b.scripts[o.Index] {
		if b.forced && s.Action == "new" {
			continue
		}
		b.orders[s.ID] = s
		out = append(out, s)
	}
	return out, nil
}

// OnFill は費用0の架空約定を所有へ反映し、原対象の一致を検査します。
//
// 引数: f(strategy.Fill)は約定です。返り値: errorは所有又は価格の不整合です。
func (b *fakeReferenceBook) OnFill(f strategy.Fill) error {
	s, ok := b.orders[f.SignalID]
	if !ok || f.Fee != 0 || f.Quantity != s.Quantity || f.Price <= 0 {
		return errors.New("架空約定の契約違反")
	}
	if s.Action == "new" {
		lot := referenceTestLot(f.HoldID, f.Quantity)
		lot.ID, lot.EntryID, lot.Entry, lot.At, lot.Side = f.ExecutionID, f.SignalID, f.Price, f.Time, s.Side
		b.lots = append(b.lots, lot)
	} else {
		if !reflect.DeepEqual(f.Closed, s.Targets) {
			return errors.New("返済所有IDの不一致")
		}
		for _, target := range f.Closed {
			found := false
			for i := range b.lots {
				if b.lots[i].HoldID == target.ID && b.lots[i].Quantity >= target.Quantity {
					b.lots[i].Quantity -= target.Quantity
					found = true
					break
				}
			}
			if !found {
				return errors.New("架空返済に管理外玉又は残量超過")
			}
		}
	}
	b.fills = append(b.fills, f)
	return nil
}

// OnOrderDone は架空の予約を解放します。
//
// 引数: id(string)は注文IDです。返り値: errorは未知注文の場合です。
func (b *fakeReferenceBook) OnOrderDone(id string) error {
	if _, ok := b.orders[id]; !ok {
		return errors.New("架空終了の未知注文")
	}
	delete(b.orders, id)
	var kept []string
	for _, target := range b.cancels {
		if target != id {
			kept = append(kept, target)
		}
	}
	b.cancels = kept
	return nil
}

// OnOrderRejected は指定新規だけを架空取消します。
//
// 引数: id(string)は注文IDです。返り値: errorは未知注文又は返済取消の場合です。
func (b *fakeReferenceBook) OnOrderRejected(id string) error {
	if s, ok := b.orders[id]; !ok || s.Action != "new" {
		return errors.New("架空取消の対象違反")
	}
	b.rejected = append(b.rejected, id)
	return b.OnOrderDone(id)
}

// SelectedCancellationIDs は現在の架空取消対象をコピーします。
//
// 引数: なし。返り値: []stringは新規取消の対象IDです。
func (b *fakeReferenceBook) SelectedCancellationIDs() []string {
	return append([]string(nil), b.cancels...)
}

// Flatten は既存予約を控除した全残量を架空返済通知にします。
//
// 引数: at(float64)は時計、reason(string)は理由です。返り値: []strategy.Signalです。
func (b *fakeReferenceBook) Flatten(at float64, reason string) []strategy.Signal {
	b.forced = true
	reserved := map[string]int{}
	for _, s := range b.orders {
		if s.Action == "close" {
			for _, target := range s.Targets {
				reserved[target.ID] += target.Quantity
			}
		}
	}
	var out []strategy.Signal
	for _, lot := range b.lots {
		quantity := lot.Quantity - reserved[lot.HoldID]
		if quantity <= 0 {
			continue
		}
		b.forceCount++
		s := referenceTestSignal(fmt.Sprintf("強制%d", b.forceCount), "close", quantity, b.lastIndex, lot.HoldID)
		s.Time, s.Reason = at, reason
		b.orders[s.ID] = s
		out = append(out, s)
	}
	return out
}

// TestReferenceConstructor は実純戦略の三手法・数量尺度を外部通信なしで検査します。
//
// 引数: t(*testing.T)は検査です。返り値: なし。市場・設定ファイルは読みません。
func TestReferenceConstructor(t *testing.T) {
	for _, method := range []string{"NK225_D164_15", "P164_06", "NK225_U165_03"} {
		kind := "Night"
		if method == "NK225_D164_15" {
			kind = "Day"
		}
		session := strategy.Session{ID: "人工_" + kind, Kind: kind, Start: 1000, ForceClose: 47000, End: 48000, USOpen: 20000, ExtraAt: 21800}
		r, err := NewReference(method, session, 100)
		if err != nil {
			t.Fatal(err)
		}
		p := r.book.(*strategyReferenceBook).Portfolio
		if p.Config.Product != "NK225micro" || p.Config.PointValue != 10 || p.Config.Cap != 100 || p.Config.CoreQuantity != 50 || p.Config.ExtraMaxQuantity != 50 {
			t.Fatal("参照側のmicro100尺度が変化しました")
		}
		if p.Selected.Shadow.Config.Product != "NK225mini" || p.Selected.Shadow.Config.Cap != 10 {
			t.Fatal("原Sourceの固定mini10尺度が変化しました")
		}
		if len(r.Frame().Lots) != 0 || len(r.Frame().Closes) != 0 {
			t.Fatal("入力前に架空所有が生成されました")
		}
		at := session.Start + 1
		if method == "NK225_U165_03" {
			at = session.USOpen + 900
		}
		features, err := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, p.Config.Parameters.Features)
		if err != nil {
			t.Fatal(err)
		}
		features.EnableResearch()
		o, err := features.OnBoard(strategy.Board{Reference: "NK225", Time: at, Received: at, Last: 105, Bid: 100, Ask: 110, BidQuantity: 100, AskQuantity: 100})
		if err != nil {
			t.Fatal(err)
		}
		if frame, err := r.Step(o); err != nil || len(frame.Lots) != 0 {
			t.Fatal("特徴未準備の人工原行を元三手法へ接続できません", method, frame, err)
		}
	}
	s := strategy.Session{ID: "人工_Day", Kind: "Day", Start: 1, ForceClose: 100, End: 101}
	for _, method := range []string{"D07", "TOPIX_D164_15", "P164_06"} {
		if _, err := NewReference(method, s, 100); err == nil {
			t.Fatal("対象外手法又は時間帯を受理しました", method)
		}
	}
	if _, err := NewReference("D164_15", s, 0); err == nil {
		t.Fatal("上限0を受理しました")
	}
	s.ForceClose = math.NaN()
	if _, err := NewReference("D164_15", s, 100); err == nil {
		t.Fatal("非有限の終了時計を受理しました")
	}
}

// TestReferenceNextNormalRowAndImmediateNotice は後原行約定と当行通知を分けて検査します。
//
// 引数: t(*testing.T)。返り値: なし。同秒後行・交差板・スナップショット非汚染も確認します。
func TestReferenceNextNormalRowAndImmediateNotice(t *testing.T) {
	r, b := newFakeReference(nil)
	b.scripts[0] = []strategy.Signal{referenceTestSignal("初回", "new", 10, 0, "")}
	b.scripts[2] = []strategy.Signal{referenceTestSignal("部分", "close", 6, 2, "初回-玉")}
	b.scripts[4] = []strategy.Signal{referenceTestSignal("残全", "close", 4, 4, "初回-玉")}
	for i := int64(0); i <= 5; i++ {
		frame, err := r.Step(referenceTestObservation(i, 100, i != 1 && i != 3))
		if err != nil {
			t.Fatal(err)
		}
		if i < 2 && len(frame.Lots) != 0 {
			t.Fatal("同原行又は交差板で新規約定しました")
		}
		if i == 2 {
			if len(frame.Lots) != 1 || frame.Lots[0].Quantity != 10 || !frame.Lots[0].Closing || frame.Lots[0].ID != "初回-玉" || len(frame.Closes) != 1 || frame.Closes[0].Before != 10 {
				t.Fatal("新返済を仮想約定まで遅延又は残量を先取りしました", frame)
			}
			frame.Lots[0].Quantity, frame.Closes[0].Before = 999, 999
			if r.Frame().Lots[0].Quantity != 10 || r.Frame().Closes[0].Before != 10 {
				t.Fatal("呼出し元から参照会計が汚染されました")
			}
		}
		if i == 3 && (len(frame.Closes) != 0 || frame.Lots[0].Quantity != 10 || !frame.Lots[0].Closing) {
			t.Fatal("前行通知を再発行又は非正常板で返済しました")
		}
		if i == 4 && (frame.Lots[0].Quantity != 4 || frame.Closes[0].Before != 4 || frame.Closes[0].Quantity != 4) {
			t.Fatal("部分約定後の残全通知が不正です", frame)
		}
		if i == 5 && (len(frame.Lots) != 0 || len(frame.Closes) != 0) {
			t.Fatal("数量0の玉又は過去通知が残りました")
		}
	}
	if len(b.fills) != 3 || b.fills[0].Price != 110 || b.fills[1].Price != 100 || b.badFlags || len(b.observed) != 6 {
		t.Fatal("約定BBO・費用0・全原行Source継続が不正です", b.fills)
	}
}

// TestReferenceMultipleReservations は同原行と前行未約定の通知量を順に控除します。
//
// 引数: t(*testing.T)。返り値: なし。最後の全残通知が未通知残量と一致することを確認します。
func TestReferenceMultipleReservations(t *testing.T) {
	r, b := newFakeReference([]strategy.SelectedLot{referenceTestLot("玉", 10), referenceTestLot("終了済", 0)})
	b.scripts[0] = []strategy.Signal{referenceTestSignal("一", "close", 3, 0, "玉"), referenceTestSignal("二", "close", 2, 0, "玉")}
	b.scripts[1] = []strategy.Signal{referenceTestSignal("三", "close", 5, 1, "玉")}
	f, err := r.Step(referenceTestObservation(0, 100, false))
	if err != nil || len(f.Closes) != 2 || f.Closes[0].Before != 10 || f.Closes[1].Before != 7 || len(f.Lots) != 1 {
		t.Fatal("同原行の返済通知順が不正です", f, err)
	}
	f, err = r.Step(referenceTestObservation(1, 100, false))
	if err != nil || len(f.Closes) != 1 || f.Closes[0].Before != 5 || f.Closes[0].Quantity != 5 || f.Lots[0].Quantity != 10 || !f.Lots[0].Closing {
		t.Fatal("前行未約定予約を控除した最後全残でありません", f, err)
	}
	f, err = r.Step(referenceTestObservation(2, 100, true))
	if err != nil || len(f.Lots) != 0 || len(b.fills) != 3 {
		t.Fatal("同一玉の連続返済予約が全量約定しません", f, err)
	}
}

// TestReferenceSelectedCancellation は指定新規だけを取り消し返済予約を維持します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestReferenceSelectedCancellation(t *testing.T) {
	r, b := newFakeReference([]strategy.SelectedLot{referenceTestLot("玉", 10)})
	b.scripts[0] = []strategy.Signal{referenceTestSignal("取消新規", "new", 2, 0, ""), referenceTestSignal("維持返済", "close", 3, 0, "玉")}
	b.cancelAt[1] = []string{"取消新規"}
	for i := int64(0); i < 3; i++ {
		if _, err := r.Step(referenceTestObservation(i, 100, i == 2)); err != nil {
			t.Fatal(err)
		}
	}
	if !reflect.DeepEqual(b.rejected, []string{"取消新規"}) || len(b.fills) != 1 || b.fills[0].SignalID != "維持返済" || r.Frame().Lots[0].Quantity != 7 {
		t.Fatal("個別新規取消が返済又は所有を変えました")
	}
}

// TestReferenceForceKeepsPendingClose は境界取消と、予約を控除した全残通知を検査します。
//
// 引数: t(*testing.T)。返り値: なし。Force後も次正常原行まで所有を保持します。
func TestReferenceForceKeepsPendingClose(t *testing.T) {
	r, b := newFakeReference([]strategy.SelectedLot{referenceTestLot("玉", 10)})
	b.scripts[0] = []strategy.Signal{referenceTestSignal("終了新規", "new", 2, 0, ""), referenceTestSignal("既予約", "close", 4, 0, "玉")}
	if _, err := r.Step(referenceTestObservation(0, 100, true)); err != nil {
		t.Fatal(err)
	}
	if err := r.Force(100, "米国前境界"); err != nil {
		t.Fatal(err)
	}
	f := r.Frame()
	if len(f.Closes) != 1 || f.Closes[0].Before != 6 || f.Closes[0].Quantity != 6 || f.Lots[0].Quantity != 10 || !f.Lots[0].Closing || !reflect.DeepEqual(b.rejected, []string{"終了新規"}) {
		t.Fatal("強制返済が既予約又は未通知残量を無視しました", f)
	}
	if err := r.Force(100, "米国前境界"); err != nil || len(r.Frame().Closes) != 0 {
		t.Fatal("強制の繰返しで同じ通知を増やしました", err)
	}
	if _, err := r.Step(referenceTestObservation(1, 100, false)); err != nil || len(r.Frame().Lots) != 1 {
		t.Fatal("強制直後の交差板で所有を消しました", err)
	}
	if _, err := r.Step(referenceTestObservation(2, 100, true)); err != nil || len(r.Frame().Lots) != 0 || len(b.fills) != 2 {
		t.Fatal("次正常原行で既予約と強制を約定しません", err)
	}
}

// TestReferenceDeadlineCancelsBeforeFill は終了時計と同原行の新規fillを拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestReferenceDeadlineCancelsBeforeFill(t *testing.T) {
	r, b := newFakeReference(nil)
	r.deadline = 100
	s := referenceTestSignal("期限新規", "new", 2, 0, "")
	s.Time = 99
	b.scripts[0] = []strategy.Signal{s}
	if _, err := r.Step(referenceTestObservation(0, 99, true)); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Step(referenceTestObservation(1, 100, true)); err != nil {
		t.Fatal(err)
	}
	if len(b.fills) != 0 || !reflect.DeepEqual(b.rejected, []string{"期限新規"}) {
		t.Fatal("終了境界で先に新規fillしました")
	}
}

// TestReferenceRejectsOrderAndClockCorruption は所有不整合・時計逆行と失敗後再試行を拒否します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestReferenceRejectsOrderAndClockCorruption(t *testing.T) {
	r, b := newFakeReference(nil)
	if _, err := r.Step(referenceTestObservation(0, 100, true)); err != nil {
		t.Fatal(err)
	}
	for _, o := range []strategy.Observation{referenceTestObservation(0, 100, true), referenceTestObservation(1, 99, true), referenceTestObservation(1, math.NaN(), true), {Reference: "TOPIX", Index: 1, Time: 100}} {
		if _, err := r.Step(o); err == nil {
			t.Fatal("重複・逆行・非有限・別市場を受理しました")
		}
	}
	if len(b.observed) != 1 {
		t.Fatal("拒否した観測で元会計を進めました")
	}
	if err := r.Force(99, "過去"); err == nil {
		t.Fatal("過去の強制時計を受理しました")
	}
	b.scripts[1] = []strategy.Signal{referenceTestSignal("管理外返済", "close", 1, 1, "管理外玉")}
	if _, err := r.Step(referenceTestObservation(1, 100, true)); err == nil {
		t.Fatal("管理外玉の返済通知を受理しました")
	}
	count := len(b.observed)
	if _, err := r.Step(referenceTestObservation(2, 100, true)); err == nil || len(b.observed) != count {
		t.Fatal("部分失敗した参照会計を再試行しました")
	}
}

// TestReferenceRejectsCloseCancellation は取消APIが返済を返した場合に停止します。
//
// 引数: t(*testing.T)。返り値: なし。
func TestReferenceRejectsCloseCancellation(t *testing.T) {
	r, b := newFakeReference([]strategy.SelectedLot{referenceTestLot("玉", 5)})
	b.scripts[0] = []strategy.Signal{referenceTestSignal("返済", "close", 2, 0, "玉")}
	b.cancelAt[0] = []string{"返済"}
	if _, err := r.Step(referenceTestObservation(0, 100, false)); err == nil || len(b.rejected) != 0 {
		t.Fatal("返済取消の契約違反を通しました")
	}
}
