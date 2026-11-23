// 順序の参照元: scripts/FAR参照玉と可変数量の比較/source.go
// 元会計を変更せず、同じ通知→次正常後原行Fill→OnOrderDoneを商品別に運転します。
package mininative

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// nativeBook は元Portfolioの公開更新と公開Selected.Lots読取だけを接続します。
type nativeBook interface {
	ObserveWithFreshness(Observation, bool, bool) ([]Signal, error)
	OnFill(Fill) error
	OnOrderDone(string) error
	OnOrderRejected(string) error
	SelectedCancellationIDs() []string
	Flatten(float64, string) []Signal
	lots() []strategy.SelectedLot
}

type portfolioBook struct{ *strategy.Portfolio }

// lots は現在の公開所有を読み、元の並びを維持します。
//
// 引数: ありません。
// 返り値: []strategy.SelectedLotは公開所有の独立した配列です。
func (p *portfolioBook) lots() []strategy.SelectedLot {
	return append([]strategy.SelectedLot{}, p.Selected.Lots...)
}

// Adapter は一つの元手法の商品会計と外費用台帳です。
// 別の実Bookや残玉poolへ元状態を再取得しません。
type Adapter struct {
	book      nativeBook
	ledger    Ledger
	deadline  float64
	pending   []Signal
	seen      map[string]bool
	holdIndex map[string]int
	last      QuoteStamp
	started   bool
	failure   error
}

// finite は有限値だけを外台帳へ保存するための確認です。
//
// 引数: values(...float64)は時計・価格・費用です。
// 返り値: boolは全値がNaN/無限大以外なら真です。
func finite(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// clone は有限性等を検査済みの保存値を独立複写します。
//
// 引数: value(T)は本adapterが保持する保存可能な型です。
// 返り値: Tは独立値です。検査済み保存不変条件の内部違反はpanicです。
func clone[T any](value T) T {
	var out T
	raw, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	if err = json.Unmarshal(raw, &out); err != nil {
		panic(err)
	}
	return out
}

// NewAdapter は元の三手法を指定商品で新規に連続運転します。
//
// 引数: method(string)、session(strategy.Session)、config(ProductConfig)は手法・時計・商品規格です。
// 返り値: *Adapter/errorはHTTP等を使わない元Portfolio又は設定不整合です。
func NewAdapter(method string, session strategy.Session, config ProductConfig) (*Adapter, error) {
	short := strings.TrimPrefix(method, "NK225_")
	if short != "D164_15" && short != "P164_06" && short != "U165_03" {
		return nil, errors.New("対象は元の選定三手法だけです")
	}
	if config != MiniConfig() && config != MicroControlConfig() {
		return nil, errors.New("商品規格・枚数・外費用が固定mini又はmicro対照と一致しません")
	}
	if !finite(session.Start, session.ForceClose, session.End, session.USOpen, session.ExtraAt, session.NightCoreStart) || session.Start < 0 || session.Start >= session.ForceClose || session.ForceClose > session.End || short == "P164_06" && session.USOpen-900 <= session.Start {
		return nil, errors.New("セッション又は米国前終了時計が不正です")
	}
	params, err := strategy.ParametersForMethod("NK225", session.Kind, short)
	if err != nil {
		return nil, err
	}
	p, err := strategy.New(strategy.Config{Namespace: "80参照-" + short, Reference: "NK225", Product: config.Product, CoreQuantity: config.CoreQuantity, ExtraMaxQuantity: config.ExtraMaxQuantity,
		Cap: config.Cap, LargeTick: config.LargeTick, PointValue: config.PointValue, Parameters: params}, session)
	if err != nil {
		return nil, err
	}
	deadline := session.ForceClose
	if short == "P164_06" {
		deadline = math.Min(deadline, session.USOpen-900)
	}
	r := &Adapter{book: &portfolioBook{p}, deadline: deadline, seen: map[string]bool{}, holdIndex: map[string]int{}, pending: []Signal{}, last: QuoteStamp{Index: -1},
		ledger: Ledger{Method: "NK225_" + short, Session: session, Config: config, Signals: []SignalRecord{}, Fills: []FillRecord{}, Cancellations: []Cancellation{}, Holds: []HoldLedger{}, Pending: []Signal{}}}
	return r, nil
}

// ready は初期化・失敗後再利用・Finish後再利用を拒否します。
//
// 引数: ありません。
// 返り値: errorは継続不能な状態、正常ならnilです。
func (r *Adapter) ready() error {
	if r == nil || r.book == nil {
		return errors.New("adapterが未初期化です")
	}
	if r.failure != nil {
		return r.failure
	}
	if r.ledger.Finished {
		return errors.New("Finish済みのadapterは再利用できません")
	}
	return nil
}

// stop は元会計更新後の失敗を保持し、部分更新の再試行を禁止します。
//
// 引数: err(error)は失敗です。
// 返り値: errorは同じ失敗です。
func (r *Adapter) stop(err error) error { r.failure = err; r.ledger.Failure = err.Error(); return err }

// stamp は原行由来の気配と源特徴連番を値保存します。
//
// 引数: o(Observation)、line(int64)は当行と原板物理行です。
// 返り値: QuoteStampは当行の抜粋です。
func stamp(o Observation, line int64) QuoteStamp {
	return QuoteStamp{o.Time, o.Index, line, o.Last, o.Bid, o.Ask, o.QuoteOK}
}

// normal は有限な正Bid<Askだけを実Fillへ使います。
//
// 引数: o(Observation)は元の当時特徴です。
// 返り値: boolは異常BBOでない場合だけ真です。
func normal(o Observation) bool {
	return o.QuoteOK && finite(o.Bid, o.Ask) && o.Bid > 0 && o.Ask > o.Bid
}

// result は今回だけの保存先を空配列で作ります。
//
// 引数: at(float64)、origin(string)、line(int64)は処理の出典です。
// 返り値: StepResultは不変出力の初期値です。
func result(at float64, origin string, line int64) StepResult {
	return StepResult{At: at, Origin: origin, SourceLine: line, Signals: []SignalRecord{}, Fills: []FillRecord{}, Cancellations: []Cancellation{}, Closes: []CloseNotice{}}
}

// reservations は未約定返済を所有HoldIDごとに集計します。
//
// 引数: ありません。
// 返り値: map[string]intは未返済所有から別途控除する予約量です。
func (r *Adapter) reservations() map[string]int {
	out := map[string]int{}
	for _, s := range r.pending {
		if s.Action == "close" {
			for _, t := range s.Targets {
				out[t.ID] += t.Quantity
			}
		}
	}
	return out
}

// checkOwnership は公開所有と独立台帳・予約込み片側上限を照合します。
//
// 引数: ありません。
// 返り値: errorは所有/予約/上限の不整合です。
func (r *Adapter) checkOwnership() error {
	owned := map[string]strategy.SelectedLot{}
	for _, l := range r.book.lots() {
		if l.HoldID == "" || l.Quantity < 0 || (l.Side != 1 && l.Side != -1) || !finite(l.Entry, l.At) || l.Entry <= 0 {
			return errors.New("公開所有のID・量・価格が不正です")
		}
		if _, ok := owned[l.HoldID]; ok {
			return errors.New("公開HoldIDが重複しています")
		}
		owned[l.HoldID] = l
	}
	bySide := map[int]int{1: 0, -1: 0}
	for id, i := range r.holdIndex {
		h := r.ledger.Holds[i]
		l, ok := owned[id]
		if !ok || l.Quantity != h.Quantity || l.Side != h.Side || l.Entry != h.EntryPrice {
			return errors.New("外台帳と公開所有が一致しません")
		}
		delete(owned, id)
		bySide[h.Side] += h.Quantity
	}
	for _, l := range owned {
		if l.Quantity != 0 {
			return errors.New("外台帳にない元所有が存在します")
		}
	}
	for _, s := range r.pending {
		if s.Action == "new" {
			bySide[s.Side] += s.Quantity
		}
	}
	for _, s := range []int{1, -1} {
		if bySide[s] > r.ledger.Config.Cap {
			return errors.New("新規予約込みの片側上限を超過しています")
		}
	}
	for id, q := range r.reservations() {
		i, ok := r.holdIndex[id]
		if !ok || q > r.ledger.Holds[i].Quantity {
			return errors.New("返済予約が所有残量を超過しています")
		}
	}
	return nil
}

// cancel は選定政策又は境界が指定した未約定新規を終了通知します。
//
// 引数: ids([]string)、at(float64)、q(QuoteStamp)、reason(string)、out(*StepResult)は取消と出典です。
// 返り値: errorは未知ID/返済取消/元会計失敗です。
func (r *Adapter) cancel(ids []string, at float64, q QuoteStamp, reason string, out *StepResult) error {
	wanted := map[string]bool{}
	for _, id := range ids {
		if id == "" || wanted[id] {
			return errors.New("取消IDが空又は重複しています")
		}
		wanted[id] = true
	}
	for _, s := range r.pending {
		if wanted[s.ID] && s.Action != "new" {
			return errors.New("返済予約は取消対象にできません")
		}
	}
	kept := []Signal{}
	for _, s := range r.pending {
		if !wanted[s.ID] {
			kept = append(kept, s)
			continue
		}
		if err := r.book.OnOrderRejected(s.ID); err != nil {
			return err
		}
		c := Cancellation{s.ID, at, q, reason}
		r.ledger.Cancellations = append(r.ledger.Cancellations, c)
		out.Cancellations = append(out.Cancellations, c)
		delete(wanted, s.ID)
	}
	if len(wanted) != 0 {
		return errors.New("指定取消が未約定新規にありません")
	}
	r.pending = kept
	return nil
}

// cancelAll は既存返済を残して全未約定新規だけを取り消します。
//
// 引数: at(float64)、q(QuoteStamp)、out(*StepResult)は境界と出典です。
// 返り値: errorは元会計の取消不整合です。
func (r *Adapter) cancelAll(at float64, q QuoteStamp, out *StepResult) error {
	ids := []string{}
	for _, s := range r.pending {
		if s.Action == "new" {
			ids = append(ids, s.ID)
		}
	}
	return r.cancel(ids, at, q, "時間境界の新規取消", out)
}

// accept は全Signalを元順序で保存し、所有別の返済予約を検査します。
//
// 引数: signals([]Signal)、at(float64)、q(QuoteStamp)、out(*StepResult)は今回の元通知です。
// 返り値: errorはID・時計・上限・返済所有の不整合です。
func (r *Adapter) accept(signals []Signal, at float64, q QuoteStamp, out *StepResult) error {
	reserved := r.reservations()
	for _, s := range signals {
		if s.ID == "" || r.seen[s.ID] || s.Quantity <= 0 || (s.Side != 1 && s.Side != -1) || (s.Action != "new" && s.Action != "close") || !finite(s.Time, s.Risk, s.Boundary) || s.Time != at || s.SourceIndex != q.Index || len(s.Evidence) > 0 && !json.Valid(s.Evidence) {
			return errors.New("元SignalのID・量・時計・出典が不正です")
		}
		if s.Action == "new" {
			if r.ledger.Forced || len(s.Targets) != 0 {
				return errors.New("終了後新規又は新規への返済対象があります")
			}
		} else {
			total := 0
			targets := map[string]bool{}
			for _, t := range s.Targets {
				i, ok := r.holdIndex[t.ID]
				if !ok || targets[t.ID] || t.Quantity <= 0 {
					return errors.New("返済所有IDが不正です")
				}
				targets[t.ID] = true
				h := r.ledger.Holds[i]
				before := h.Quantity - reserved[t.ID]
				if t.Quantity > before || s.Side != -h.Side {
					return errors.New("返済量又は返済方向が所有と不一致です")
				}
				out.Closes = append(out.Closes, CloseNotice{s.ID + "|" + t.ID, t.ID, before, t.Quantity, s.Reason})
				reserved[t.ID] += t.Quantity
				total += t.Quantity
			}
			if total != s.Quantity {
				return errors.New("返済Signal総量と所有内訳が不一致です")
			}
		}
		record := SignalRecord{clone(s), out.Origin, at, q}
		r.pending = append(r.pending, clone(s))
		r.seen[s.ID] = true
		r.ledger.Signals = append(r.ledger.Signals, record)
		out.Signals = append(out.Signals, clone(record))
		if err := r.checkOwnership(); err != nil {
			return err
		}
	}
	return nil
}

// fill は一つの以前のSignalを当正常BBOで実約定し、費用0で元へ通知します。
//
// 引数: s(Signal)、q(QuoteStamp)は先行注文と当原行です。
// 返り値: FillRecord/errorは約定・所有配賦・外費用又は不整合です。
func (r *Adapter) fill(s Signal, q QuoteStamp) (FillRecord, error) {
	price := q.Bid
	if s.Side > 0 {
		price = q.Ask
	}
	f := Fill{SignalID: s.ID, ExecutionID: s.ID + "-参照約定", Quantity: s.Quantity, Price: price, Time: q.Time, HoldID: s.ID + "-玉", Fee: 0}
	record := FillRecord{Fill: f, Action: s.Action, Side: s.Side, Quote: q, FeeYen: float64(s.Quantity) * r.ledger.Config.FeeYenPerSide, SlippageYen: float64(s.Quantity) * r.ledger.Config.SlippagePoints * r.ledger.Config.PointValue, Allocations: []CloseAllocation{}}
	if s.Action == "close" {
		record.Fill.HoldID = ""
		record.Fill.Closed = clone(s.Targets)
		for _, target := range s.Targets {
			i, ok := r.holdIndex[target.ID]
			if !ok {
				return record, errors.New("実返済先に所有がありません")
			}
			h := r.ledger.Holds[i]
			if target.Quantity > h.Quantity {
				return record, errors.New("実返済量が所有を超過しています")
			}
			qty := float64(target.Quantity)
			gross := float64(h.Side) * (price - h.EntryPrice) * qty * r.ledger.Config.PointValue
			fee, slip := qty*r.ledger.Config.FeeYenPerSide, qty*r.ledger.Config.SlippagePoints*r.ledger.Config.PointValue
			a := CloseAllocation{target.ID, target.Quantity, h.EntryPrice, price, h.EntryQuote, q, gross, fee, fee, slip, slip, gross - 2*fee - 2*slip}
			if !finite(a.GrossYen, a.NetYen) {
				return record, errors.New("外損益が非有限です")
			}
			record.GrossYen += gross
			record.Allocations = append(record.Allocations, a)
		}
	}
	record.NetContributionYen = record.GrossYen - record.FeeYen - record.SlippageYen
	if err := r.book.OnFill(record.Fill); err != nil {
		return record, err
	}
	// ----------------------------------------
	// 元会計の実約定を一度だけ写し、費用を元の判断へ返しません。
	if s.Action == "new" {
		if _, ok := r.holdIndex[record.Fill.HoldID]; ok {
			return record, errors.New("実HoldIDが重複しています")
		}
		var lot *strategy.SelectedLot
		for _, v := range r.book.lots() {
			if v.HoldID == record.Fill.HoldID {
				copy := v
				lot = &copy
			}
		}
		if lot == nil || lot.Quantity != s.Quantity || lot.Entry != price || lot.Side != s.Side {
			return record, errors.New("元新規Fillと公開所有が結合しません")
		}
		r.holdIndex[lot.HoldID] = len(r.ledger.Holds)
		r.ledger.Holds = append(r.ledger.Holds, HoldLedger{HoldID: lot.HoldID, InternalID: lot.ID, EntryID: lot.EntryID, Parent: lot.Parent, SourceID: lot.SourceID, Kind: lot.Kind, Side: lot.Side,
			InitialQuantity: s.Quantity, Quantity: s.Quantity, EntryPrice: price, EntryQuote: q})
	} else {
		for _, a := range record.Allocations {
			h := &r.ledger.Holds[r.holdIndex[a.HoldID]]
			h.Quantity -= a.Quantity
			h.ClosedQuantity += a.Quantity
			h.GrossYen += a.GrossYen
			h.ClosedNetYen += a.NetYen
		}
	}
	r.ledger.Fills = append(r.ledger.Fills, clone(record))
	if err := r.book.OnOrderDone(s.ID); err != nil {
		return record, err
	}
	return record, nil
}

// fillPending は次正常後原行だけで以前の全予約を約定します。
//
// 引数: o(Observation)、q(QuoteStamp)、out(*StepResult)は当行と出力先です。
// 返り値: errorは元約定又は所有照合の不一致です。
func (r *Adapter) fillPending(o Observation, q QuoteStamp, out *StepResult) error {
	if !normal(o) {
		return nil
	}
	previous := r.pending
	r.pending = []Signal{}
	for i, s := range previous {
		if o.Index <= s.SourceIndex || o.Time < s.Time {
			r.pending = append(r.pending, s)
			continue
		}
		f, err := r.fill(s, q)
		if err != nil {
			r.pending = append(r.pending, previous[i:]...)
			return err
		}
		out.Fills = append(out.Fills, clone(f))
	}
	return r.checkOwnership()
}

// Step は取消→以前のFill→元全原行Observe→今回Signal→選定取消の順を維持します。
//
// 引数: o(strategy.Observation)、sourceLine(int64)は既知特徴と原板物理行です。
// 返り値: StepResult/errorは今回の全通知・実Fill・取消又は不整合です。
// 異常BBOでも元判断を省かず、約定だけを次の正常原行まで待ちます。
func (r *Adapter) Step(o strategy.Observation, sourceLine int64) (StepResult, error) {
	out := result(o.Time, "quote", sourceLine)
	if err := r.ready(); err != nil {
		return out, err
	}
	if o.Reference != "NK225" || !finite(o.Time, o.Received, o.Last, o.Bid, o.Ask) || o.Time < 0 || o.Index < 0 || sourceLine <= 0 || r.started && (o.Time < r.last.Time || o.Index <= r.last.Index) || r.ledger.Forced && o.Time < r.ledger.ForcedAt {
		return out, errors.New("原行の市場・時計・価格・連番・物理行が不正です")
	}
	q := stamp(o, sourceLine)
	if r.ledger.Forced || o.Time >= r.deadline {
		if err := r.cancelAll(o.Time, q, &out); err != nil {
			return out, r.stop(err)
		}
		if !r.ledger.Forced {
			r.ledger.Forced, r.ledger.ForcedAt = true, r.deadline
		}
	}
	if err := r.cancel(r.book.SelectedCancellationIDs(), o.Time, q, "元選定政策の新規取消", &out); err != nil {
		return out, r.stop(err)
	}
	if err := r.fillPending(o, q, &out); err != nil {
		return out, r.stop(err)
	}
	signals, err := r.book.ObserveWithFreshness(o, true, true)
	if err != nil {
		return out, r.stop(err)
	}
	if err = r.accept(signals, o.Time, q, &out); err != nil {
		return out, r.stop(err)
	}
	if err = r.cancel(r.book.SelectedCancellationIDs(), o.Time, q, "元選定政策の新規取消", &out); err != nil {
		return out, r.stop(err)
	}
	r.started, r.last = true, q
	if err = r.checkOwnership(); err != nil {
		return out, r.stop(err)
	}
	return clone(out), nil
}

// Force は境界の新規を取り消し、元Flattenの返済予約を保存します。
//
// 引数: at(float64)は強制返済要求時計です。
// 返り値: StepResult/errorは当時の要求だけです。古い気配での即時Fillは行いません。
func (r *Adapter) Force(at float64) (StepResult, error) {
	out := result(at, "timer", 0)
	if err := r.ready(); err != nil {
		return out, err
	}
	if !finite(at) || at < 0 || r.started && at < r.last.Time || r.ledger.Forced && at < r.ledger.ForcedAt {
		return out, errors.New("Force時計が不正です")
	}
	out.SourceLine = r.last.SourceLine
	r.ledger.Forced, r.ledger.ForcedAt = true, at
	if err := r.cancelAll(at, r.last, &out); err != nil {
		return out, r.stop(err)
	}
	if err := r.accept(r.book.Flatten(at, "時間境界の全返済"), at, r.last, &out); err != nil {
		return out, r.stop(err)
	}
	if err := r.checkOwnership(); err != nil {
		return out, r.stop(err)
	}
	return clone(out), nil
}

// Snapshot は外台帳の累積と未完了残を独立複写します。
//
// 引数: ありません。
// 返り値: Ledgerは全実Fillのgross/外費用/数量と現在予約です。
func (r *Adapter) Snapshot() Ledger {
	if r == nil {
		return Ledger{Failure: "未初期化"}
	}
	out := clone(r.ledger)
	out.Pending = clone(r.pending)
	for _, f := range out.Fills {
		if f.Action == "new" {
			out.Totals.EntryQuantity += f.Fill.Quantity
		} else {
			out.Totals.CloseQuantity += f.Fill.Quantity
		}
		out.Totals.GrossYen += f.GrossYen
		out.Totals.FeeYen += f.FeeYen
		out.Totals.SlippageYen += f.SlippageYen
		out.Totals.NetYen += f.NetContributionYen
	}
	for _, h := range out.Holds {
		if h.Side > 0 {
			out.Totals.OpenBuyQuantity += h.Quantity
		} else {
			out.Totals.OpenSellQuantity += h.Quantity
		}
		out.Totals.ClosedNetYen += h.ClosedNetYen
		out.Totals.OpenEntryCostsYen += float64(h.Quantity) * (out.Config.FeeYenPerSide + out.Config.SlippagePoints*out.Config.PointValue)
	}
	for _, s := range out.Pending {
		if s.Action == "new" {
			if s.Side > 0 {
				out.Totals.PendingBuyQuantity += s.Quantity
			} else {
				out.Totals.PendingSellQuantity += s.Quantity
			}
		}
	}
	out.Complete = out.Failure == "" && len(out.Pending) == 0 && out.Totals.OpenBuyQuantity == 0 && out.Totals.OpenSellQuantity == 0
	out.Totals.GrossMinusFeeYen = out.Totals.GrossYen - out.Totals.FeeYen
	return out
}

// Finish は終了時残を成功に補完せず、残玉又は予約があればerrorを返します。
//
// 引数: ありません。
// 返り値: Ledger/errorは最終台帳と終了残の有無です。架空の終値約定を作りません。
func (r *Adapter) Finish() (Ledger, error) {
	if err := r.ready(); err != nil {
		return r.Snapshot(), err
	}
	if err := r.checkOwnership(); err != nil {
		return r.Snapshot(), r.stop(err)
	}
	out := r.Snapshot()
	if !out.Complete {
		return out, fmt.Errorf("終了未完了:買残%d・売残%d・未約定%d", out.Totals.OpenBuyQuantity, out.Totals.OpenSellQuantity, len(out.Pending))
	}
	r.ledger.Finished = true
	return r.Snapshot(), nil
}
