package far80

import (
	"errors"
	"fmt"
	"math"
	"strings"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// referenceBook は純戦略の公開会計APIと、所有・予約の読取を接続します。
// 人工検査では同じ契約の架空会計を使い、市場・HTTP・設定を開きません。
type referenceBook interface {
	ObserveWithFreshness(strategy.Observation, bool, bool) ([]strategy.Signal, error)
	OnFill(strategy.Fill) error
	OnOrderDone(string) error
	OnOrderRejected(string) error
	SelectedCancellationIDs() []string
	Flatten(float64, string) []strategy.Signal
	referenceLots() []strategy.SelectedLot
}

// strategyReferenceBook は元Portfolioを変更せず所有読取だけを追加します。
type strategyReferenceBook struct {
	*strategy.Portfolio
}

// referenceLots は元選定会計の実約定片を読取用に複写します。
//
// 引数: なし。返り値: []strategy.SelectedLotは元の順序を保つ所有玉です。
func (b *strategyReferenceBook) referenceLots() []strategy.SelectedLot {
	return append([]strategy.SelectedLot(nil), b.Selected.Lots...)
}

// Reference は元三手法を費用0・次正常原行で進める参照会計です。
// 実80会計の利益や数量を元Sourceへ戻さず、返済通知を当行で公開します。
type Reference struct {
	book      referenceBook
	method    string
	deadline  float64
	pending   []strategy.Signal
	seen      map[string]bool
	frame     ReferenceFrame
	lastTime  float64
	lastIndex int64
	started   bool
	forced    bool
	forcedAt  float64
	failure   error
}

// NewReference は固定三手法のmicro参照会計を外部通信なしで作ります。
//
// 引数: method(string)は短縮又はNK225付きID、session(strategy.Session)は当場時計、cap(int)は片方向上限です。
// 返り値: *Referenceとerror。点価10円・費用0、元Sourceのmini10枚尺度は純戦略側に維持します。
func NewReference(method string, session strategy.Session, cap int) (*Reference, error) {
	short := strings.TrimPrefix(method, "NK225_")
	if short != "D164_15" && short != "P164_06" && short != "U165_03" {
		return nil, errors.New("参照会計は指定された日経三手法だけを扱います")
	}
	if cap <= 0 {
		return nil, errors.New("参照会計の片方向上限は正の整数が必要です")
	}
	if !referenceFinite(session.Start) || !referenceFinite(session.ForceClose) || !referenceFinite(session.End) ||
		(short == "P164_06" && (!referenceFinite(session.USOpen) || session.USOpen-900 <= session.Start)) {
		return nil, errors.New("参照会計の場時計又は米国前終了時計が不正です")
	}
	params, err := strategy.ParametersForMethod("NK225", session.Kind, short)
	if err != nil {
		return nil, err
	}
	p, err := strategy.New(strategy.Config{
		Namespace: "80参照-" + short, Reference: "NK225", Product: "NK225micro",
		CoreQuantity: min(50, cap), ExtraMaxQuantity: min(50, cap), Cap: cap,
		LargeTick: 10, PointValue: 10, Parameters: params,
	}, session)
	if err != nil {
		return nil, err
	}
	deadline := session.ForceClose
	if short == "P164_06" {
		deadline = math.Min(deadline, session.USOpen-900)
	}
	return &Reference{book: &strategyReferenceBook{p}, method: "NK225_" + short,
		deadline: deadline, seen: map[string]bool{}, lastIndex: -1,
		frame: ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}}, nil
}

// referenceFinite は参照時計・価格の有限性を判定します。
//
// 引数: value(float64)は数値です。返り値: boolはNaN・無限大でなければtrueです。
func referenceFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}

// referenceNormal は約定に使える正常な返済側・新規側BBOを判定します。
//
// 引数: o(strategy.Observation)は当時観測です。返り値: boolは元QuoteOKと有限正bid<askを満たすかです。
func referenceNormal(o strategy.Observation) bool {
	return o.QuoteOK && referenceFinite(o.Bid) && referenceFinite(o.Ask) && o.Bid > 0 && o.Ask > o.Bid
}

// check は参照会計の初期化と、既に失敗した経路の再利用禁止を検査します。
//
// 引数: なし。返り値: errorは未初期化又は継続不能の理由、正常ならnilです。
func (r *Reference) check() error {
	if r == nil || r.book == nil {
		return errors.New("参照会計が初期化されていません")
	}
	return r.failure
}

// stop は純会計を更新した後の失敗を保持し、部分更新のまま再試行させません。
//
// 引数: err(error)は失敗です。返り値: errorは同じ失敗で、後続操作も拒否します。
func (r *Reference) stop(err error) error {
	r.failure = err
	return err
}

// cancelEntries は指定された未約定新規だけを取消完了として純会計へ通知します。
//
// 引数: ids([]string)は元の取消対象です。返り値: errorは未知ID又は返済取消の契約違反です。
func (r *Reference) cancelEntries(ids []string) error {
	wanted := map[string]bool{}
	for _, id := range ids {
		wanted[id] = true
	}
	for _, s := range r.pending {
		if wanted[s.ID] && s.Action != "new" {
			return errors.New("参照の取消対象に返済注文があります")
		}
	}
	kept := make([]strategy.Signal, 0, len(r.pending))
	for _, s := range r.pending {
		if !wanted[s.ID] {
			kept = append(kept, s)
			continue
		}
		if err := r.book.OnOrderRejected(s.ID); err != nil {
			return err
		}
		delete(wanted, s.ID)
	}
	if len(wanted) != 0 {
		return errors.New("参照の取消対象が未約定新規予約にありません")
	}
	r.pending = kept
	return nil
}

// cancelAllEntries は境界以後の新規約定を防ぎ、既存返済予約は保持します。
//
// 引数: なし。返り値: errorは純会計への注文終了通知の失敗です。
func (r *Reference) cancelAllEntries() error {
	var ids []string
	for _, s := range r.pending {
		if s.Action == "new" {
			ids = append(ids, s.ID)
		}
	}
	return r.cancelEntries(ids)
}

// fillPending は前原行までの予約を、現在の正常後原行だけで全量仮想約定します。
//
// 引数: o(strategy.Observation)は当行です。返り値: errorは所有・約定・注文終了の不整合です。
func (r *Reference) fillPending(o strategy.Observation) error {
	if !referenceNormal(o) {
		return nil
	}
	kept := make([]strategy.Signal, 0, len(r.pending))
	for _, s := range r.pending {
		if o.Index <= s.SourceIndex || o.Time < s.Time {
			kept = append(kept, s)
			continue
		}
		price := o.Bid
		if s.Side > 0 {
			price = o.Ask
		}
		f := strategy.Fill{SignalID: s.ID, ExecutionID: s.ID + "-参照約定", Quantity: s.Quantity,
			Price: price, Time: o.Time, HoldID: s.ID + "-玉", Fee: 0}
		if s.Action == "close" {
			f.HoldID = ""
			f.Closed = append([]strategy.LotTarget(nil), s.Targets...)
		}
		if err := r.book.OnFill(f); err != nil {
			return err
		}
		if err := r.book.OnOrderDone(s.ID); err != nil {
			return err
		}
	}
	r.pending = kept
	return nil
}

// closeReservations は既に通知した未約定返済量を参照HoldIDごとに集計します。
//
// 引数: なし。返り値: map[string]intは通知済みで未約定の返済予約量です。
func (r *Reference) closeReservations() map[string]int {
	reserved := map[string]int{}
	for _, s := range r.pending {
		if s.Action == "close" {
			for _, target := range s.Targets {
				reserved[target.ID] += target.Quantity
			}
		}
	}
	return reserved
}

// accept は元の新通知を予約し、返済は仮想約定を待たず当行へ公開します。
//
// 引数: signals([]strategy.Signal)は元の発行順です。返り値: errorはID・所有・予約数量の契約違反です。
func (r *Reference) accept(signals []strategy.Signal) error {
	lots := map[string]int{}
	for _, lot := range r.book.referenceLots() {
		if lot.Quantity > 0 {
			if lot.HoldID == "" || lots[lot.HoldID] != 0 {
				return errors.New("参照所有玉のHoldIDが空又は重複しています")
			}
			lots[lot.HoldID] = lot.Quantity
		}
	}
	reserved := r.closeReservations()
	for _, s := range signals {
		if s.ID == "" || r.seen[s.ID] || s.Quantity <= 0 || (s.Side != 1 && s.Side != -1) || (s.Action != "new" && s.Action != "close") {
			return errors.New("参照通知のID・方向・数量・種別が不正です")
		}
		if s.Action == "close" {
			total := 0
			for _, target := range s.Targets {
				before := lots[target.ID] - reserved[target.ID]
				if target.ID == "" || target.Quantity <= 0 || target.Quantity > before {
					return errors.New("参照返済通知が所有の未通知残量を超えています")
				}
				r.frame.Closes = append(r.frame.Closes, ReferenceClose{ID: s.ID + "|" + target.ID,
					ReferenceID: target.ID, Before: before, Quantity: target.Quantity, Reason: s.Reason})
				reserved[target.ID] += target.Quantity
				total += target.Quantity
			}
			if total != s.Quantity {
				return errors.New("参照返済通知と対象内訳の数量が一致しません")
			}
		} else if len(s.Targets) != 0 || r.forced {
			return errors.New("参照新規通知の対象又は強制終了状態が不正です")
		}
		s.Targets = append([]strategy.LotTarget(nil), s.Targets...)
		r.pending = append(r.pending, s)
		r.seen[s.ID] = true
	}
	return nil
}

// refresh は現在約定残量を元順序で写し、返済予約のある玉にClosingを付けます。
//
// 引数: なし。返り値: なし。Quantityは予約を控除せず、実参照約定残量を保持します。
func (r *Reference) refresh() {
	reserved := r.closeReservations()
	r.frame.Lots = []ReferenceLot{}
	for _, lot := range r.book.referenceLots() {
		if lot.Quantity <= 0 {
			continue
		}
		r.frame.Lots = append(r.frame.Lots, ReferenceLot{ID: lot.HoldID, InternalID: lot.ID,
			Parent: lot.Parent, SourceID: lot.SourceID, Method: r.method, Owner: lot.Owner, Kind: lot.Kind,
			Side: lot.Side, Quantity: lot.Quantity, Entry: lot.Entry, At: lot.At, Closing: reserved[lot.HoldID] > 0})
	}
}

// Step は当行以前の約定、元全行判断、新返済通知の順に参照会計を進めます。
//
// 引数: o(strategy.Observation)は全NK225原行の当時特徴です。返り値: ReferenceFrameとerrorです。
// 非正常BBOでもObserveを省かず、返済通知は当行、約定は次正常後原行と分離します。
func (r *Reference) Step(o strategy.Observation) (ReferenceFrame, error) {
	if err := r.check(); err != nil {
		return ReferenceFrame{}, err
	}
	if o.Reference != "NK225" || !referenceFinite(o.Time) || o.Index < 0 ||
		(r.started && (o.Time < r.lastTime || o.Index <= r.lastIndex)) || (r.forced && o.Time < r.forcedAt) {
		return ReferenceFrame{}, errors.New("参照観測の市場・価格時計・原行順が不正です")
	}
	r.frame.Closes = []ReferenceClose{}
	// ----------------------------------------
	// 終了時計で新規を先に取り消し、返済の次正常約定は継続します。
	if r.forced || o.Time >= r.deadline {
		if err := r.cancelAllEntries(); err != nil {
			return ReferenceFrame{}, r.stop(err)
		}
		if !r.forced {
			r.forced, r.forcedAt = true, r.deadline
		}
	}
	if err := r.cancelEntries(r.book.SelectedCancellationIDs()); err != nil {
		return ReferenceFrame{}, r.stop(err)
	}
	if err := r.fillPending(o); err != nil {
		return ReferenceFrame{}, r.stop(err)
	}
	// ----------------------------------------
	// Sourceは全行で元の新規判断を継続し、実80側の定時gateを持ち込みません。
	signals, err := r.book.ObserveWithFreshness(o, true, true)
	if err != nil {
		return ReferenceFrame{}, r.stop(err)
	}
	if err = r.accept(signals); err != nil {
		return ReferenceFrame{}, r.stop(err)
	}
	if err = r.cancelEntries(r.book.SelectedCancellationIDs()); err != nil {
		return ReferenceFrame{}, r.stop(err)
	}
	r.started, r.lastTime, r.lastIndex = true, o.Time, o.Index
	r.refresh()
	return r.Frame(), nil
}

// Force は境界の参照新規を取消し、所有玉の返済通知を直ちに公開します。
//
// 引数: at(float64)は要求時計、reason(string)は理由です。返り値: errorは時計又は所有の不整合です。
// 呼出し後のFrame.Closesは今回の新通知だけです。呼出し元は次のStepより前にその通知を処理します。
func (r *Reference) Force(at float64, reason string) error {
	if err := r.check(); err != nil {
		return err
	}
	if !referenceFinite(at) || strings.TrimSpace(reason) == "" || (r.started && at < r.lastTime) || (r.forced && at < r.forcedAt) {
		return errors.New("参照強制返済の時計又は理由が不正です")
	}
	r.frame.Closes = []ReferenceClose{}
	r.forced, r.forcedAt = true, at
	if err := r.cancelAllEntries(); err != nil {
		return r.stop(err)
	}
	if err := r.accept(r.book.Flatten(at, reason)); err != nil {
		return r.stop(fmt.Errorf("参照強制返済: %w", err))
	}
	r.refresh()
	return nil
}

// Frame は現在の参照玉と、直近Step又はForceの返済通知を複写します。
//
// 引数: なし。返り値: ReferenceFrameは呼出し元が変更しても参照会計を汚染しないスナップショットです。
func (r *Reference) Frame() ReferenceFrame {
	if r == nil {
		return ReferenceFrame{}
	}
	return ReferenceFrame{Lots: append([]ReferenceLot{}, r.frame.Lots...), Closes: append([]ReferenceClose{}, r.frame.Closes...)}
}
