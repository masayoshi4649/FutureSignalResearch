// 由来99固定金融: scripts/FAR背景と勢いと数量の入口/actual.go
// 由来SHA256: 37e63e3c61031a11125ca4b932920e246bf56277b6b2833114fc50a186150ffc
// 由来98固定金融: scripts/FAR利益前ATR追尾/actual.go
// 由来SHA256: 37c6d5cd2ee007bb5435ad43a6627662d91f77fa9a925ccde6e29bff0ee331c5
// 由来97停止金融: scripts/FAR初回利益確定/actual.go
// 由来SHA256: 292cd4f054a03121a220cb3c6db96d11610e0eb8f123f31839a3a295030d11f6
// 由来: scripts/FAR5分枠の順行反転と数量/actual.go
// 由来SHA256: aa7e5dace4bf6667aea7e9a10dbbb0d956b77f63bc52886740a05d2fa56d24d2
// 由来: scripts/FAR連続出生と個別利益追尾/actual.go
// 由来SHA256: 653360ffea807e865c50adc44bd54c2298d9fb519e4ccec264fcf106b5fb8fe7
package minigrossguard100

import (
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"strings"

	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

const (
	PhasePreFill               = "pre_fill"
	PhaseAfterSource           = "after_source"
	EntryFloorReason           = "最低建値床と固定2ATR追尾"
	FeeFloorReason             = "費用回収床と固定2ATR追尾"
	HarvestFirstPositiveReason = "初回費用後残玉正益の全量確定"
)

type sourceEvidence struct {
	Kind          string `json:"kind"`
	Parent        string `json:"parent"`
	SourceID      string `json:"source_id"`
	Method        string `json:"method"`
	QuantityMicro int    `json:"quantity_micro"`
}

type sourceOrder struct {
	signal   native.Signal
	identity SourceIdentity
	state    string
	hold     string
}

type sourceHold struct {
	orderKey string
	side     int
	quantity int
	reserved int
}

// ActualBook は独立した実所有と出典registryを持ち、Shadowへ更新を返しません。
type ActualBook struct {
	result              ActualResult
	orders              map[string]int
	positions           map[string]int
	entryBySource       map[string]string
	positionByHold      map[string]string
	sourceOrders        map[string]*sourceOrder
	sourceHolds         map[string]*sourceHold
	sourceExecutions    map[string]bool
	notices             map[string]bool
	last                QuoteStamp
	haveQuote           bool
	lastEventAt         float64
	cash                float64
	failure             error
	opportunityBySource map[string]int
	lastGridAt          float64
	haveGrid            bool
}

// finiteActual は金額・価格・時計の有限性を確認します。
//
// 引数: values(...float64)は検査値です。
// 返り値: boolはNaN/無限大がない場合に真です。
func finiteActual(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// valueCopy は保存可能な独立値を複写します。
//
// 引数: value(T)は入力確認済みの公開型又は実結果です。
// 返り値: Tはslice/pointerも分離した値です。内部保存不変条件違反はpanicです。
func valueCopy[T any](value T) T {
	var copy T
	data, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	if err = json.Unmarshal(data, &copy); err != nil {
		panic(err)
	}
	return copy
}

// sourceKey は文字列を分割せず手法と元IDの二要素を結びます。
//
// 引数: method/id(string)は明示された出典です。
// 返り値: stringは衝突しない内部索引です。
func sourceKey(method, id string) string { return method + "\x00" + id }

// canonicalMethod は対象の短縮名だけを明示的に受け付けます。
//
// 引数: method(string)、kind(string)は元手法と場種です。
// 返り値: string/errorは正式手法名又は不整合です。
func canonicalMethod(method, kind string) (string, error) {
	short := strings.TrimPrefix(method, "NK225_")
	if kind == "Day" && short == "D164_15" || kind == "Night" && (short == "P164_06" || short == "U165_03") {
		return "NK225_" + short, nil
	}
	return "", fmt.Errorf("Source手法と場種が不整合です:%s", method)
}

// NewActualBook は固定mini商品条件の独立口座を作ります。
//
// 引数: session(Session)、cfg(ActorConfig)は場とPolicy/費用/遅延です。
// 返り値: *ActualBook/errorは空口座又は不正な設定です。
func NewActualBook(session Session, cfg ActorConfig) (*ActualBook, error) {
	if session.ID == "" || (session.Kind != "Day" && session.Kind != "Night") || !finiteActual(session.Start, session.End, session.ForceClose) || session.Start >= session.ForceClose || session.ForceClose > session.End {
		return nil, fmt.Errorf("Actor場時計が不正です")
	}
	if cfg.Policy != "S0" && cfg.Policy != "P0" && cfg.Policy != "P1" || cfg.SlipPts != 0 && cfg.SlipPts != 5 || cfg.DelaySeconds != 0 && cfg.DelaySeconds != 1 {
		return nil, fmt.Errorf("Actorの12設定以外は受け付けません")
	}
	if cfg.EntryTiming == "" {
		cfg.EntryTiming = "N"
	}
	if cfg.EntryTiming != "N" && cfg.EntryTiming != "B5" && cfg.EntryTiming != "B5Q" || cfg.EntryTiming != "N" && cfg.Policy != "P0" {
		return nil, fmt.Errorf("新規時計又は共通P0政策が不正です")
	}
	if cfg.GatePolicy != "E3S" || cfg.EntryTiming != "B5Q" || cfg.Policy != "P0" || cfg.RiskPolicy != "" ||
		(cfg.HarvestPolicy != "" && cfg.HarvestPolicy != "H0" && cfg.HarvestPolicy != "HG") {
		return nil, fmt.Errorf("100金融案はE3S/B5Q/P0/risk空と出口P0(空)/H0/HGだけを受け付けます")
	}
	if !finiteActual(cfg.USOpen) || cfg.USOpen < 0 || session.Kind == "Night" && (cfg.USOpen > 0 && (cfg.USOpen <= session.Start || cfg.USOpen >= session.End) || cfg.EntryTiming != "N" && cfg.USOpen == 0) {
		return nil, fmt.Errorf("米国開始時計が不正又は必要未知です")
	}
	r := &ActualBook{orders: map[string]int{}, positions: map[string]int{}, entryBySource: map[string]string{}, positionByHold: map[string]string{}, sourceOrders: map[string]*sourceOrder{}, sourceHolds: map[string]*sourceHold{}, sourceExecutions: map[string]bool{}, notices: map[string]bool{}, last: QuoteStamp{Index: -1}}
	r.result = ActualResult{Session: session, Key: fmt.Sprintf("%s_C%.0f_D%d", cfg.Policy, cfg.SlipPts, cfg.DelaySeconds), Config: cfg, Orders: []ActualOrder{}, Fills: []ActualFill{}, Positions: []ActualPosition{}, SourceEvents: []SourceEventTrace{}, StreamScope: "固定93と同じLast>0のSource受理行。Last0未供給数は共有qualityを参照。"}
	if cfg.EntryTiming != "N" {
		r.result.Key = cfg.EntryTiming + "_" + r.result.Key
	}
	if cfg.GatePolicy != "" {
		r.result.Key = cfg.GatePolicy + "_" + r.result.Key
	}
	if cfg.HarvestPolicy != "" {
		r.result.Key = cfg.HarvestPolicy + "_" + r.result.Key
	}
	if cfg.RiskPolicy != "" {
		r.result.Key = cfg.RiskPolicy + "_" + r.result.Key
	}
	r.opportunityBySource = map[string]int{}
	r.result.EntryOpportunities = []EntryOpportunityTrace{}
	r.result.GridTraces = []EntryGridTrace{}
	return r, nil
}

// ready は失敗後やFinish後の再利用を拒否します。
//
// 引数: ありません。
// 返り値: errorは継続できない状態です。
func (b *ActualBook) ready() error {
	if b == nil {
		return fmt.Errorf("Actorが未初期化です")
	}
	if b.failure != nil {
		return b.failure
	}
	if b.result.Finished {
		return fmt.Errorf("ActorはFinish済みです")
	}
	return nil
}

// stop は部分更新の失敗を以後の成功へ読み替えません。
//
// 引数: err(error)は失敗です。
// 返り値: errorは同じ失敗です。
func (b *ActualBook) stop(err error) error {
	b.failure = err
	b.result.Failure = err.Error()
	return err
}

// quoteActual は当原行を値だけで保存します。
//
// 引数: o(Observation)、line(int64)は当時特徴と物理行です。
// 返り値: QuoteStampはSource Indexをraw連番と混ぜない抜粋です。
func quoteActual(o Observation, line int64) QuoteStamp {
	return QuoteStamp{Time: o.Time, Index: o.Index, SourceLine: line, Last: o.Last, Bid: o.Bid, Ask: o.Ask, QuoteOK: o.QuoteOK}
}

// normalActual は現在の実約定・評価に使うBBO条件です。
//
// 引数: q(QuoteStamp)は当原行です。
// 返り値: boolは正常な有限の正Bid<Askです。
func normalActual(q QuoteStamp) bool {
	return q.QuoteOK && finiteActual(q.Bid, q.Ask) && q.Bid > 0 && q.Ask > q.Bid
}

// validateATR はnativeの公開5分ATR出典を検査します。
//
// 引数: o(Observation)は現在までの公開特徴です。
// 返り値: errorは非有限・負・未来又は時計の不整合です。0は正常な暖機未知です。
func validateATR(o Observation) error {
	a, v, n := o.ATR, o.E01.ATRAvailable, o.E01.ATRNominal
	if !finiteActual(a, v, n, o.E01.ATR) || a < 0 || v < 0 || n < 0 || v > o.Time || n > o.Time || o.E01.ATR != a {
		return fmt.Errorf("公開native ATR又は時計が不正です")
	}
	if a > 0 && (v <= 0 || n <= 0 || v < n) {
		return fmt.Errorf("既知ATRの公開/名目時計が不正です")
	}
	return nil
}

// available は返済予約を空きへ数えずP/U全体の片側余力を返します。
//
// 引数: side(int)は新規の買売符号です。
// 返り値: intは0〜10の実余力です。
func (b *ActualBook) available(side int) int {
	n := 10
	for _, p := range b.result.Positions {
		if p.Side == side {
			n -= p.Quantity
		}
	}
	for _, o := range b.result.Orders {
		if o.Kind == "entry" && o.Side == side && o.Status == "pending" {
			n -= o.Quantity
		}
	}
	return n
}

// checkActual は実残/予約/上限の不変条件を確認します。
//
// 引数: ありません。
// 返り値: errorは過剰予約、所有不整合、上限超過です。
func (b *ActualBook) checkActual() error {
	reserved := map[string]int{}
	for _, o := range b.result.Orders {
		if o.Kind == "exit" && o.Status == "pending" {
			reserved[o.PositionID] += o.Quantity
		}
	}
	for _, p := range b.result.Positions {
		if p.Quantity < 0 || p.Reserved < 0 || p.Reserved > p.Quantity || reserved[p.ID] != p.Reserved || p.Quantity+p.ClosedQuantity != p.InitialQuantity {
			return fmt.Errorf("Actual所有/予約が不整合です:%s", p.ID)
		}
	}
	if b.available(1) < 0 || b.available(-1) < 0 {
		return fmt.Errorf("P/U合算の片側10枚上限を超過しています")
	}
	return nil
}

// cancelEntry はActual未取得newだけを終了します。
//
// 引数: source(string)、at(float64)、reason(string)は明示出典と要求時刻です。
// 返り値: intは取消枚数です。過去の取得済み玉へ作用しません。
func (b *ActualBook) cancelEntry(source string, at float64, reason string) int {
	id, ok := b.entryBySource[source]
	if !ok || id == "" {
		return 0
	}
	i := b.orders[id]
	o := &b.result.Orders[i]
	if o.Status != "pending" {
		return 0
	}
	o.Status, o.CancelReason = "cancelled", reason
	stamp := at
	o.CancelTime = &stamp
	b.result.Metrics.CancelledEntries++
	return o.Quantity
}

// parseIdentity は元Evidenceの必要fieldを型付きで読むだけです。
//
// 引数: method(string)、r(native.SignalRecord)は元new通知です。
// 返り値: SourceIdentity/errorは元段階と出生量又は出典不整合です。
func parseIdentity(method string, r native.SignalRecord) (SourceIdentity, error) {
	var e sourceEvidence
	if err := json.Unmarshal(r.Signal.Evidence, &e); err != nil {
		return SourceIdentity{}, fmt.Errorf("Source Evidence型:%w", err)
	}
	if e.Kind == "" || e.Parent == "" || e.SourceID == "" || e.Method != method || e.QuantityMicro <= 0 {
		return SourceIdentity{}, fmt.Errorf("Source Evidenceの元段階/量/手法が不正です")
	}
	return SourceIdentity{Method: method, SignalID: r.Signal.ID, Kind: e.Kind, Parent: e.Parent, SourceID: e.SourceID, QuantityMicro: e.QuantityMicro, BirthQuantity: r.Signal.Quantity, BirthTime: r.At, BirthQuote: r.Quote}, nil
}

// prepareBatches は元newの出典と取消・Source実Fillを受付けます。
//
// 引数: at(float64)、q(QuoteStamp)、batches([]NativeBatch)、timer(bool)は一配送です。
// 返り値: []NativeBatch/errorは正式手法名で凍結した通知又は不整合です。
func (b *ActualBook) prepareBatches(at float64, q QuoteStamp, batches []NativeBatch, timer bool) ([]NativeBatch, error) {
	// Deltaは読取専用。正規化するMethodを持つ外側struct配列だけを分離します。
	copy := append([]NativeBatch(nil), batches...)
	seenMethods := map[string]bool{}
	fillIDs := map[string]bool{}
	cancelIDs := map[string]bool{}
	for i := range copy {
		batch := &copy[i]
		method, err := canonicalMethod(batch.Method, b.result.Session.Kind)
		if err != nil {
			return nil, err
		}
		batch.Method = method
		if seenMethods[method] {
			return nil, fmt.Errorf("同原行にSource手法が重複しています")
		}
		seenMethods[method] = true
		if batch.Delta.At != at || (!timer && (batch.Delta.Origin != "quote" || batch.Delta.SourceLine != q.SourceLine)) || (timer && (batch.Delta.Origin != "timer" || len(batch.Delta.Fills) != 0)) {
			return nil, fmt.Errorf("NativeBatchの時計/位相が不正です")
		}
		for _, f := range batch.Delta.Fills {
			fillIDs[sourceKey(method, f.Fill.SignalID)] = true
		}
		for _, c := range batch.Delta.Cancellations {
			key := sourceKey(method, c.SignalID)
			if cancelIDs[key] {
				return nil, fmt.Errorf("Native取消が重複しています")
			}
			cancelIDs[key] = true
		}
	}
	for id := range cancelIDs {
		if fillIDs[id] {
			return nil, fmt.Errorf("同じSource Signalにfill/取消が併存しています")
		}
	}
	// ----------------------------------------
	// 同原行取消のnewも出生出典だけ先に登録し、Actual受理は最後の専用位相へ残します。
	for _, batch := range copy {
		for _, r := range batch.Delta.Signals {
			s := r.Signal
			if s.ID == "" || (s.Side != 1 && s.Side != -1) || s.Quantity < 1 || s.Quantity > 10 || r.At != at || s.Time != at || s.SourceIndex != r.Quote.Index || !finiteActual(s.Time, s.Risk, s.Boundary) {
				return nil, fmt.Errorf("Native Signalの時計/量/方向が不正です")
			}
			if !timer && r.Quote != q {
				return nil, fmt.Errorf("Native Signalが当原行に結合しません")
			}
			if r.Origin != batch.Delta.Origin {
				return nil, fmt.Errorf("Native Signalの起源とbatchが不一致です")
			}
			if timer && (r.Origin != "timer" || s.Action != "close" || r.Quote.Time > at) {
				return nil, fmt.Errorf("timerに新規又は未来気配があります")
			}
			if s.Action == "new" {
				key := sourceKey(batch.Method, s.ID)
				if _, ok := b.sourceOrders[key]; ok {
					return nil, fmt.Errorf("Source新規通知の再配送です")
				}
				identity, err := parseIdentity(batch.Method, r)
				if err != nil {
					return nil, err
				}
				b.sourceOrders[key] = &sourceOrder{signal: valueCopy(s), identity: identity, state: "pending"}
				b.result.Metrics.NativeNewSignals++
			} else if s.Action != "close" {
				return nil, fmt.Errorf("未知のNative Signal種別です")
			}
		}
	}
	for _, batch := range copy {
		for _, c := range batch.Delta.Cancellations {
			key := sourceKey(batch.Method, c.SignalID)
			s, ok := b.sourceOrders[key]
			if !ok || s.signal.Action != "new" || s.state != "pending" || c.At != at {
				return nil, fmt.Errorf("Source取消が未取得newへ結合しません")
			}
			if !timer && c.Quote != q || timer && c.Quote.Time > at {
				return nil, fmt.Errorf("Native取消の原行又は時計が不正です")
			}
			s.state = "cancelled"
			cancelled := b.cancelEntry(key, at, "元Sourceの未取得new取消")
			b.result.SourceEvents = append(b.result.SourceEvents, SourceEventTrace{At: at, Phase: "before_fill", Method: batch.Method, Kind: "cancel", SignalID: c.SignalID, Quote: c.Quote, Side: s.signal.Side, Quantity: s.signal.Quantity, ActualNewCancelled: cancelled, Reason: c.Reason})
			b.result.Metrics.NativeCancels++
		}
	}
	for _, batch := range copy {
		for _, f := range batch.Delta.Fills {
			key := sourceKey(batch.Method, f.Fill.SignalID)
			s, ok := b.sourceOrders[key]
			if !ok || s.state != "pending" || f.Quote != q || f.Fill.Time != q.Time || f.Fill.Quantity != s.signal.Quantity || f.Action != s.signal.Action || f.Side != s.signal.Side || f.Fill.Fee != 0 {
				return nil, fmt.Errorf("Source Fillと先行Signalが不一致です")
			}
			if !normalActual(q) || q.Index <= s.signal.SourceIndex || q.Time < s.signal.Time || f.Fill.Price != (map[bool]float64{true: q.Ask, false: q.Bid}[s.signal.Side > 0]) {
				return nil, fmt.Errorf("Source Fillの約定適格/価格が不正です")
			}
			execKey := sourceKey(batch.Method, f.Fill.ExecutionID)
			if f.Fill.ExecutionID == "" || b.sourceExecutions[execKey] {
				return nil, fmt.Errorf("Source ExecutionIDが空又は重複しています")
			}
			b.sourceExecutions[execKey] = true
			kind := "close_fill"
			if s.signal.Action == "new" {
				kind = "new_fill"
				hk := sourceKey(batch.Method, f.Fill.HoldID)
				if f.Fill.HoldID == "" || b.sourceHolds[hk] != nil || len(f.Fill.Closed) != 0 {
					return nil, fmt.Errorf("Source新規HoldIDが不正です")
				}
				s.hold = f.Fill.HoldID
				b.sourceHolds[hk] = &sourceHold{orderKey: key, side: s.signal.Side, quantity: f.Fill.Quantity}
				b.result.Metrics.NativeNewFills++
			} else {
				if !reflect.DeepEqual(f.Fill.Closed, s.signal.Targets) {
					return nil, fmt.Errorf("Source close Fillの所有内訳が不一致です")
				}
				for _, t := range f.Fill.Closed {
					h := b.sourceHolds[sourceKey(batch.Method, t.ID)]
					if h == nil || t.Quantity <= 0 || h.quantity < t.Quantity || h.reserved < t.Quantity {
						return nil, fmt.Errorf("Source実返済が所有/予約を超過しています")
					}
					h.quantity -= t.Quantity
					h.reserved -= t.Quantity
				}
				b.result.Metrics.NativeCloseFills++
			}
			s.state = "filled"
			b.result.SourceEvents = append(b.result.SourceEvents, SourceEventTrace{At: at, Phase: "native_fill", Method: batch.Method, Kind: kind, SignalID: s.signal.ID, ExecutionID: f.Fill.ExecutionID, HoldID: f.Fill.HoldID, Quote: q, Side: f.Side, Quantity: f.Fill.Quantity})
		}
	}
	b.result.Metrics.NativeBatches += len(copy)
	return copy, nil
}

// newID は一口座内で取消も含めた単調な実注文IDを返します。
//
// 引数: ありません。
// 返り値: stringは次の実注文IDです。
func (b *ActualBook) newID() string {
	return fmt.Sprintf("%s-%s-O%06d", b.result.Session.ID, b.result.Key, len(b.result.Orders)+1)
}

// acceptEntries は元出生量を空きへminし、一度だけActual newを受理します。
//
// 引数: at(float64)、batches([]NativeBatch)は当原行の元通知です。
// 返り値: errorは出生出典の不整合です。
func (b *ActualBook) acceptEntries(at float64, batches []NativeBatch) error {
	if b.result.Config.EntryTiming != "N" {
		return b.scheduleEntries(at, batches)
	}
	for batchIndex, batch := range batches {
		for signalIndex, r := range batch.Delta.Signals {
			if r.Signal.Action != "new" {
				continue
			}
			key := sourceKey(batch.Method, r.Signal.ID)
			s := b.sourceOrders[key]
			if _, exists := b.entryBySource[key]; exists {
				return fmt.Errorf("Actual出生が再配送されました")
			}
			free := b.available(s.signal.Side)
			quantity := min(s.signal.Quantity, free)
			reason := "元Source出生量を受理"
			if s.state == "cancelled" {
				quantity = 0
				reason = "Native取消済みの出生は復活しない"
			} else if quantity == 0 {
				reason = "片側上限に空きなし"
				b.result.Metrics.CapRejectedEntries++
			} else if quantity < s.signal.Quantity {
				reason = "片側上限で出生量を制限"
				b.result.Metrics.CapClippedEntries++
			}
			id := ""
			if quantity > 0 {
				id = b.newID()
				positionID := fmt.Sprintf("%s-%s-P%06d", b.result.Session.ID, b.result.Key, len(b.result.Orders)+1)
				o := ActualOrder{ID: id, Kind: "entry", Side: s.signal.Side, Quantity: quantity, PositionID: positionID, Source: s.identity, RequestTime: at, RequestQuote: r.Quote, Reason: s.signal.Reason, Status: "pending"}
				b.orders[id] = len(b.result.Orders)
				b.result.Orders = append(b.result.Orders, o)
				b.result.Metrics.EntryRequests++
				b.result.Metrics.EntryAcceptedQuantity += quantity
			}
			// 空き0/取消も消費済みとして残し、後の原行で復活させません。
			b.entryBySource[key] = id
			b.result.SourceEvents = append(b.result.SourceEvents, SourceEventTrace{At: at, Phase: "native_new", Method: batch.Method, Kind: "new_signal", SignalID: s.signal.ID, Quote: r.Quote, Side: s.signal.Side, Quantity: s.signal.Quantity, ActualAccepted: quantity, Available: free, OrderID: id, Reason: reason})
			if err := b.recordNativeOpportunity(s, batchIndex, signalIndex, at, quantity, free, id, reason); err != nil {
				return err
			}
		}
	}
	return b.checkActual()
}

// requestExit は実未予約残だけを新しい返済注文へ予約します。
//
// 引数: p(*ActualPosition)、quantity(int)、at(float64)、q(QuoteStamp)、reason/nativeSignal/notice(string)、point(*MTMPoint)、initial(...*InitialRiskPoint)は要求と出典です。
// 返り値: string/errorは実注文ID又は過剰予約です。
func (b *ActualBook) requestExit(p *ActualPosition, quantity int, at float64, q QuoteStamp, reason, nativeSignal, notice string, point *MTMPoint, initial ...*InitialRiskPoint) (string, error) {
	return b.requestExitTagged(p, quantity, at, q, reason, nativeSignal, notice, point, nil, initial...)
}

// requestExitTagged はSource/H/HGの出典を排他的に保存する共通予約口です。
//
// 引数: p(*ActualPosition)、quantity(int)、at(float64)、q(QuoteStamp)、reason/nativeSignal/notice(string)、point/gross(*MTMPoint)、initial(...*InitialRiskPoint)は要求と出典です。
// 返り値: string/errorは実注文ID又は出典/数量の不整合です。H0でgross=nilなら旧経路のままです。
func (b *ActualBook) requestExitTagged(p *ActualPosition, quantity int, at float64, q QuoteStamp, reason, nativeSignal, notice string, point, gross *MTMPoint, initial ...*InitialRiskPoint) (string, error) {
	if gross != nil && (b.result.Config.HarvestPolicy != "HG" || p.GrossGuard == nil || point != nil || len(initial) != 0 || reason != GrossGuardExitReason || nativeSignal != "" || notice != "" || gross.Phase != PhaseAfterSource || gross.Quote != q || gross.GainPoints > 0 || gross.UnitNet > 0) {
		return "", fmt.Errorf("利益前ガード要求の独立出典が不正です")
	}
	if quantity <= 0 || quantity > p.Quantity-p.Reserved {
		return "", fmt.Errorf("Actual返済が未予約残を超過しています")
	}
	if len(initial) > 1 || len(initial) == 1 && (initial[0] == nil || b.result.Config.RiskPolicy == "" || point != nil || reason != InitialRiskExitReason) {
		return "", fmt.Errorf("初期risk返済の独立出典が不正です")
	}
	id := b.newID()
	o := ActualOrder{ID: id, Kind: "exit", Side: -p.Side, Quantity: quantity, PositionID: p.ID, Source: p.Source, SourceHoldID: p.SourceHoldID, NativeCloseSignalID: nativeSignal, NativeCloseNoticeID: notice, RequestTime: at, RequestQuote: q, Reason: reason, Status: "pending", ProtectionPoint: point}
	if len(initial) == 1 {
		o.InitialRiskPoint = initial[0]
	}
	if gross != nil {
		copy := *gross
		o.GrossGuardPoint = &copy
	}
	b.orders[id] = len(b.result.Orders)
	b.result.Orders = append(b.result.Orders, o)
	p.Reserved += quantity
	if o.GrossGuardPoint != nil {
		b.result.Metrics.GrossGuardExitRequests++
	} else if o.InitialRiskPoint != nil {
		b.result.Metrics.InitialRiskExitRequests++
	} else if point == nil {
		b.result.Metrics.SourceExitRequests++
	} else {
		b.result.Metrics.ProtectionExitRequests++
	}
	return id, nil
}

// sourceCloses はSource Beforeを独立確認してActual freeへceil配分します。
//
// 引数: at(float64)、batches([]NativeBatch)は同位相の元返済通知です。
// 返り値: errorは通知/所有/順序/比率の不整合です。
func (b *ActualBook) sourceCloses(at float64, batches []NativeBatch) error {
	for _, batch := range batches {
		noticeIndex := 0
		for _, record := range batch.Delta.Signals {
			s := record.Signal
			if s.Action != "close" {
				continue
			}
			key := sourceKey(batch.Method, s.ID)
			if _, ok := b.sourceOrders[key]; ok {
				return fmt.Errorf("Source close Signalが再配送されました")
			}
			total := 0
			targets := map[string]bool{}
			for _, target := range s.Targets {
				if noticeIndex >= len(batch.Delta.Closes) {
					return fmt.Errorf("Source close通知が不足しています")
				}
				n := batch.Delta.Closes[noticeIndex]
				noticeIndex++
				hk := sourceKey(batch.Method, target.ID)
				h := b.sourceHolds[hk]
				if h == nil || targets[hk] || target.Quantity <= 0 || h.side != -s.Side {
					return fmt.Errorf("Source close対象の所有/方向が不正です")
				}
				targets[hk] = true
				before := h.quantity - h.reserved
				if before <= 0 || target.Quantity > before || n.ID != s.ID+"|"+target.ID || n.ReferenceID != target.ID || n.Before != before || n.Quantity != target.Quantity || n.Reason != s.Reason {
					return fmt.Errorf("Source close Before/Targetsが不一致です")
				}
				nk := sourceKey(batch.Method, n.ID)
				if b.notices[nk] {
					return fmt.Errorf("Source noticeが再配送されました")
				}
				b.notices[nk] = true
				pending := 0
				if id := b.entryBySource[h.orderKey]; id != "" {
					o := b.result.Orders[b.orders[id]]
					if o.Status == "pending" {
						pending = o.Quantity
					}
				}
				cancelled := b.cancelEntry(h.orderKey, at, "Source close前のActual未取得new全取消")
				free, requested, orderID := 0, 0, ""
				if pid := b.positionByHold[hk]; pid != "" {
					p := &b.result.Positions[b.positions[pid]]
					free = p.Quantity - p.Reserved
					if target.Quantity == before {
						requested = free
					} else {
						requested = (free*target.Quantity + before - 1) / before
					}
					if requested > 0 {
						var err error
						orderID, err = b.requestExit(p, requested, at, record.Quote, s.Reason, s.ID, n.ID, nil)
						if err != nil {
							return err
						}
					}
				}
				h.reserved += target.Quantity
				total += target.Quantity
				b.result.Metrics.NativeCloseNotices++
				b.result.SourceEvents = append(b.result.SourceEvents, SourceEventTrace{At: at, Phase: "source_close", Method: batch.Method, Kind: "close_notice", SignalID: s.ID, HoldID: target.ID, NoticeID: n.ID, Quote: record.Quote, Side: s.Side, Quantity: target.Quantity, Before: before, ActualPendingBefore: pending, ActualNewCancelled: cancelled, ActualFreeBefore: free, ActualExitRequested: requested, ActualFreeAfter: free - requested, OrderID: orderID, Reason: s.Reason})
			}
			if total != s.Quantity {
				return fmt.Errorf("Source返済総量とTargetsが不一致です")
			}
			b.sourceOrders[key] = &sourceOrder{signal: valueCopy(s), state: "pending"}
		}
		if noticeIndex != len(batch.Delta.Closes) {
			return fmt.Errorf("Signalへ結合しないSource close通知があります")
		}
	}
	return b.checkActual()
}

// lockATR は取得時又は初回既知のnative幅を一度だけ固定します。
//
// 引数: p(*ActualPosition)、o(Observation)、q(QuoteStamp)は実玉と公開原行です。
// 返り値: errorは導出幅の非有限です。暖機0は最低床を妨げません。
func (b *ActualBook) lockATR(p *ActualPosition, o Observation, q QuoteStamp) error {
	if p.ATR != nil || o.ATR == 0 {
		return nil
	}
	width := 5 * math.Ceil(2*o.ATR/5)
	if !finiteActual(width) || width <= 0 {
		return fmt.Errorf("固定2ATR幅が不正です")
	}
	p.ATR = &ATRLock{Value: o.ATR, Available: o.E01.ATRAvailable, Nominal: o.E01.ATRNominal, AgeSeconds: q.Time - o.E01.ATRAvailable, Width: width, Quote: q, AfterEntry: q.Index > p.EntryQuote.Index}
	return nil
}

// fillOrders は以前の実予約を適格な当気配で全量約定します。
//
// 引数: o(Observation)、q(QuoteStamp)は現在原行です。
// 返り値: errorは所有/Source結合又は金額の不整合です。
func (b *ActualBook) fillOrders(o Observation, q QuoteStamp) error {
	if !normalActual(q) {
		return nil
	}
	limit := len(b.result.Orders)
	for i := 0; i < limit; i++ {
		order := &b.result.Orders[i]
		if order.Status != "pending" || q.Index <= order.RequestQuote.Index || q.Time < order.RequestTime+float64(b.result.Config.DelaySeconds) {
			continue
		}
		price := q.Bid
		if order.Side > 0 {
			price = q.Ask
		}
		qty := float64(order.Quantity)
		fee, slip := qty*38.5, qty*b.result.Config.SlipPts*100
		f := ActualFill{ID: order.ID + "-F", OrderID: order.ID, PositionID: order.PositionID, Side: order.Side, Quantity: order.Quantity, Price: price, Quote: q, Source: order.Source, SourceHoldID: order.SourceHoldID, NativeCloseSignalID: order.NativeCloseSignalID, NativeCloseNoticeID: order.NativeCloseNoticeID, Reason: order.Reason, FeeYen: fee, SlipYen: slip, Allocations: []ActualAllocation{}}
		if order.Kind == "entry" {
			key := sourceKey(order.Source.Method, order.Source.SignalID)
			s := b.sourceOrders[key]
			if s == nil || s.state != "filled" || s.hold == "" {
				return fmt.Errorf("Actual取得時にSource実在Holdが未公開です")
			}
			hk := sourceKey(order.Source.Method, s.hold)
			if b.positionByHold[hk] != "" {
				return fmt.Errorf("同じSource出生へActual再参加しています")
			}
			order.SourceHoldID = s.hold
			f.SourceHoldID = s.hold
			f.Action = "new"
			p := ActualPosition{ID: order.PositionID, EntryOrderID: order.ID, Source: order.Source, SourceHoldID: s.hold, Side: order.Side, InitialQuantity: order.Quantity, Quantity: order.Quantity, EntryPrice: price, EntryQuote: q}
			if err := b.lockATR(&p, o, q); err != nil {
				return err
			}
			if err := b.lockInitialRisk(&p, o, q); err != nil {
				return err
			}
			if p.ATR == nil {
				b.result.Metrics.ATRDeferredPositions++
			}
			b.positions[p.ID] = len(b.result.Positions)
			b.positionByHold[hk] = p.ID
			b.result.Positions = append(b.result.Positions, p)
			b.result.Metrics.EntryFills++
		} else {
			pi, ok := b.positions[order.PositionID]
			if !ok {
				return fmt.Errorf("実返済に所有Positionがありません")
			}
			p := &b.result.Positions[pi]
			if order.Quantity > p.Quantity || order.Quantity > p.Reserved || order.Side != -p.Side {
				return fmt.Errorf("実返済量が所有/予約を超過しています")
			}
			gross := float64(p.Side) * (price - p.EntryPrice) * qty * 100
			net := gross - 2*fee - 2*slip
			if !finiteActual(gross, net) {
				return fmt.Errorf("実返済金額が非有限です")
			}
			f.Action, f.GrossYen = "close", gross
			f.Allocations = append(f.Allocations, ActualAllocation{PositionID: p.ID, SourceHoldID: p.SourceHoldID, Quantity: order.Quantity, EntryPrice: p.EntryPrice, EntryQuote: p.EntryQuote, ExitPrice: price, ExitQuote: q, GrossYen: gross, EntryFeeYen: fee, ExitFeeYen: fee, EntrySlipYen: slip, ExitSlipYen: slip, NetYen: net})
			p.Quantity -= order.Quantity
			p.Reserved -= order.Quantity
			p.ClosedQuantity += order.Quantity
			p.GrossYen += gross
			p.RealizedNet += net
			if p.Quantity == 0 {
				stamp := q
				p.ClosedQuote = &stamp
			}
			b.result.Metrics.ExitFills++
			if order.GrossGuardPoint != nil {
				b.result.Metrics.GrossGuardExitFills++
			} else if order.ProtectionPoint != nil {
				b.result.Metrics.ProtectionExitFills++
			}
		}
		f.NetContributionYen = f.GrossYen - fee - slip
		b.cash += f.NetContributionYen
		order.Status, order.FillID = "filled", f.ID
		b.result.Fills = append(b.result.Fills, f)
	}
	return b.checkActual()
}

// updateMarks は実残玉のu/W初回と返し/極値を同じ原行で記録します。
//
// 引数: marks(*PositionMarks)、point(MTMPoint)は保存先と当時評価です。
// 返り値: なし。必要な少数点だけを値保存します。
func updateMarks(marks *PositionMarks, point MTMPoint) {
	copy := point
	if marks.First == nil {
		marks.First = &copy
	}
	if marks.Last == nil {
		last := point
		marks.Last = &last
	} else {
		*marks.Last = point
	}
	if marks.UnitMax == nil || point.UnitNet > marks.UnitMax.UnitNet {
		marks.UnitMax = &copy
	}
	if marks.UnitMin == nil || point.UnitNet < marks.UnitMin.UnitNet {
		marks.UnitMin = &copy
	}
	if marks.WholeMax == nil || point.WholeNet > marks.WholeMax.WholeNet {
		marks.WholeMax = &copy
	}
	if marks.WholeMin == nil || point.WholeNet < marks.WholeMin.WholeNet {
		marks.WholeMin = &copy
	}
	if marks.FirstUnitPositive == nil && point.UnitNet > 0 {
		marks.FirstUnitPositive = &copy
	}
	if marks.FirstWholePositive == nil && point.WholeNet > 0 {
		marks.FirstWholePositive = &copy
	}
	if marks.FirstUnitPositive != nil && point.UnitNet <= 0 && marks.FirstUnitNonPositiveAfter == nil {
		marks.FirstUnitNonPositiveAfter = &copy
	}
	if marks.FirstUnitPositive != nil && point.UnitNet < 0 && marks.FirstUnitNegativeAfter == nil {
		marks.FirstUnitNegativeAfter = &copy
	}
	if marks.FirstWholePositive != nil && point.WholeNet <= 0 && marks.FirstWholeNonPositiveAfter == nil {
		marks.FirstWholeNonPositiveAfter = &copy
	}
	if marks.FirstWholePositive != nil && point.WholeNet < 0 && marks.FirstWholeNegativeAfter == nil {
		marks.FirstWholeNegativeAfter = &copy
	}
}

// markPositions はfill前/Source受付後の評価と非緩和床を処理します。
//
// 引数: o(Observation)、q(QuoteStamp)、phase(string)、issue(bool)は当原行と新要求可否です。
// 返り値: errorは金額/幅/所有不整合です。新要求はafter_sourceだけです。
func (b *ActualBook) markPositions(o Observation, q QuoteStamp, phase string, issue bool) error {
	for i := range b.result.Positions {
		p := &b.result.Positions[i]
		if p.Quantity == 0 {
			continue
		}
		mark := q.Bid
		if p.Side < 0 {
			mark = q.Ask
		}
		gain := float64(p.Side) * (mark - p.EntryPrice)
		unit := gain*100 - (77 + 2*b.result.Config.SlipPts*100)
		whole := p.RealizedNet + float64(p.Quantity)*unit
		if !finiteActual(gain, unit, whole) {
			return fmt.Errorf("実保有MTMが非有限です")
		}
		point := MTMPoint{Quote: q, Phase: phase, Quantity: p.Quantity, Reserved: p.Reserved, MarkPrice: mark, GainPoints: gain, UnitNet: unit, RealizedNet: p.RealizedNet, WholeNet: whole}
		updateMarks(&p.Marks, point)
		if !p.HasMark || gain > p.PeakGain {
			p.PeakGain = gain
		}
		p.HasMark = true
		if err := b.lockATR(p, o, q); err != nil {
			return err
		}
		if b.result.Config.Policy == "S0" {
			continue
		}
		if !p.ProtectionActive && unit > 0 {
			p.ProtectionActive = true
			copy := point
			p.Activation = &copy
		}
		if err := b.observeInitialRisk(p, point, issue); err != nil {
			return err
		}
		if err := b.observeGrossGuard(p, point, issue); err != nil {
			return err
		}
		if !p.ProtectionActive {
			continue
		}
		minimum := 0.0
		if b.result.Config.HarvestPolicy == "H0" || b.result.Config.HarvestPolicy == "HG" {
			if p.Activation == nil || !finiteActual(p.Activation.GainPoints) || p.Activation.UnitNet <= 0 {
				return fmt.Errorf("H0の初回費用後残玉正益の起動証拠が不正です")
			}
			minimum = math.Max(0, p.Activation.GainPoints)
		}
		if b.result.Config.Policy == "P1" {
			minimum = 5 * math.Ceil((77+2*b.result.Config.SlipPts*100)/100/5)
		}
		floor := minimum
		if p.ATR != nil {
			floor = math.Max(floor, p.PeakGain-p.ATR.Width)
		}
		if p.FloorGain != nil {
			floor = math.Max(floor, *p.FloorGain)
		}
		if p.FloorGain == nil || floor > *p.FloorGain {
			value := floor
			p.FloorGain = &value
			copy := point
			p.FloorUpdated = &copy
		}
		if gain <= floor {
			if p.FirstFloorHit == nil {
				copy := point
				p.FirstFloorHit = &copy
			}
			if issue && p.Quantity > p.Reserved {
				reason := EntryFloorReason
				if b.result.Config.Policy == "P1" {
					reason = FeeFloorReason
				}
				if b.result.Config.HarvestPolicy == "H0" || b.result.Config.HarvestPolicy == "HG" {
					reason = HarvestFirstPositiveReason
				}
				copy := point
				if _, err := b.requestExit(p, p.Quantity-p.Reserved, q.Time, q, reason, "", "", &copy); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

// markAccount はP/U全体の清算評価とpeak/DDを一口座で測定します。
//
// 引数: q(QuoteStamp)、phase(string)は評価時点です。
// 返り値: errorは時点会計の金額不整合です。
func (b *ActualBook) markAccount(q QuoteStamp, phase string) error {
	equity, whole := b.cash, 0.0
	buy, sell := 0, 0
	for _, p := range b.result.Positions {
		whole += p.RealizedNet
		if p.Quantity == 0 {
			continue
		}
		mark := q.Bid
		if p.Side < 0 {
			mark = q.Ask
		}
		gain := float64(p.Side) * (mark - p.EntryPrice)
		qty := float64(p.Quantity)
		equity += qty * (gain*100 - 38.5 - b.result.Config.SlipPts*100)
		whole += qty * (gain*100 - 77 - 2*b.result.Config.SlipPts*100)
		if p.Side > 0 {
			buy += p.Quantity
		} else {
			sell += p.Quantity
		}
	}
	if !finiteActual(equity, whole) || math.Abs(equity-whole) > 1e-7 {
		return fmt.Errorf("口座の現金寄与と全Hold評価が不一致です")
	}
	p := AccountPoint{Quote: q, Phase: phase, Equity: equity, CashNet: b.cash, OpenBuy: buy, OpenSell: sell}
	m := &b.result.Account
	if m.First == nil {
		copy := p
		m.First = &copy
	}
	if m.Last != nil {
		m.MaxGapSeconds = math.Max(m.MaxGapSeconds, q.Time-m.Last.Quote.Time)
	}
	if m.Peak == nil || equity > m.Peak.Equity {
		copy := p
		m.Peak = &copy
	}
	if m.Max == nil || equity > m.Max.Equity {
		copy := p
		m.Max = &copy
	}
	if m.Min == nil || equity < m.Min.Equity {
		copy := p
		m.Min = &copy
	}
	dd := m.Peak.Equity - equity
	if dd > m.MaxDrawdown {
		m.MaxDrawdown = dd
		peak := *m.Peak
		trough := p
		m.DrawdownPeak = &peak
		m.DrawdownTrough = &trough
	}
	if m.Last == nil {
		copy := p
		m.Last = &copy
	} else {
		*m.Last = p
	}
	m.Count++
	return nil
}

// OnNativeStep は同じSource原行にある全手法を一度だけ進めます。
//
// 引数: o(Observation)、sourceLine(int64)、batches([]NativeBatch)は当原行と公開通知です。
// 返り値: errorは時計・Source結合・実会計の不整合です。
func (b *ActualBook) OnNativeStep(o Observation, sourceLine int64, batches []NativeBatch) error {
	if err := b.ready(); err != nil {
		return err
	}
	if o.Reference != "NK225" || !finiteActual(o.Time, o.Received, o.Last, o.Bid, o.Ask) || o.Last <= 0 || o.Time <= 0 || o.Index < 0 || sourceLine <= 0 || o.Time < b.lastEventAt || b.haveQuote && (o.Index <= b.last.Index || o.Time < b.last.Time) {
		return b.stop(fmt.Errorf("Actual当原行の市場/時計/出典が不正です"))
	}
	if err := validateATR(o); err != nil {
		return b.stop(err)
	}
	q := quoteActual(o, sourceLine)
	prepared, err := b.prepareBatches(o.Time, q, batches, false)
	if err != nil {
		return b.stop(err)
	}
	b.result.Metrics.Rows++
	if normalActual(q) {
		if err = b.markPositions(o, q, PhasePreFill, false); err != nil {
			return b.stop(err)
		}
		if err = b.markAccount(q, PhasePreFill); err != nil {
			return b.stop(err)
		}
	} else {
		b.result.Metrics.BadQuoteRows++
	}
	if err = b.fillOrders(o, q); err != nil {
		return b.stop(err)
	}
	if err = b.sourceCloses(o.Time, prepared); err != nil {
		return b.stop(err)
	}
	if err = b.acceptEntries(o.Time, prepared); err != nil {
		return b.stop(err)
	}
	if normalActual(q) {
		if err = b.markPositions(o, q, PhaseAfterSource, true); err != nil {
			return b.stop(err)
		}
		if err = b.markAccount(q, PhaseAfterSource); err != nil {
			return b.stop(err)
		}
	}
	b.last, b.haveQuote, b.lastEventAt = q, true, o.Time
	if err = b.checkActual(); err != nil {
		return b.stop(err)
	}
	return nil
}

// OnNativeForce は元timerの取消/closeだけを一度配送し、古い気配で評価しません。
//
// 引数: at(float64)、batches([]NativeBatch)は元Forceの公開通知です。
// 返り値: errorは時計又は元通知の不整合です。
func (b *ActualBook) OnNativeForce(at float64, batches []NativeBatch) error {
	if err := b.ready(); err != nil {
		return err
	}
	if !finiteActual(at) || at <= 0 || at < b.lastEventAt {
		return b.stop(fmt.Errorf("Actual timer時計が不正です"))
	}
	prepared, err := b.prepareBatches(at, b.last, batches, true)
	if err != nil {
		return b.stop(err)
	}
	if err = b.sourceCloses(at, prepared); err != nil {
		return b.stop(err)
	}
	b.result.Metrics.TimerCalls++
	b.lastEventAt = at
	if err = b.checkActual(); err != nil {
		return b.stop(err)
	}
	return nil
}

// Snapshot は実Fillから総額と旗の分母を算出して独立複写します。
//
// 引数: ありません。
// 返り値: ActualResultは政策固有の現在/最終結果です。
func (b *ActualBook) Snapshot() ActualResult {
	if b == nil {
		return ActualResult{Failure: "Actor未初期化"}
	}
	r := valueCopy(b.result)
	for _, f := range r.Fills {
		if f.Action == "new" {
			r.Totals.EntryQuantity += f.Quantity
		} else {
			r.Totals.CloseQuantity += f.Quantity
		}
		r.Totals.GrossYen += f.GrossYen
		r.Totals.FeeYen += f.FeeYen
		r.Totals.SlipYen += f.SlipYen
		r.Totals.NetYen += f.NetContributionYen
	}
	for _, p := range r.Positions {
		if p.Side > 0 {
			r.Totals.OpenBuy += p.Quantity
		} else {
			r.Totals.OpenSell += p.Quantity
		}
		r.Totals.ClosedNetYen += p.RealizedNet
		r.Totals.OpenEntryCostsYen += float64(p.Quantity) * (38.5 + r.Config.SlipPts*100)
		if p.Marks.FirstUnitPositive != nil {
			r.Metrics.UnitPositivePositions++
		}
		if p.Marks.FirstWholePositive != nil {
			r.Metrics.WholePositivePositions++
		}
		if p.ProtectionActive {
			r.Metrics.ProtectionActivatedPositions++
		}
		if p.Quantity == 0 && p.RealizedNet < 0 {
			if p.ProtectionActive {
				r.Metrics.ActivatedClosedNegative++
			}
			if p.Marks.FirstUnitPositive != nil {
				r.Metrics.UnitPositiveClosedNegative++
			}
			if p.Marks.FirstWholePositive != nil {
				r.Metrics.WholePositiveClosedNegative++
			}
		}
	}
	pending := 0
	for _, o := range r.Orders {
		if o.Status == "pending" {
			pending++
			if o.Kind == "entry" {
				if o.Side > 0 {
					r.Totals.PendingBuy += o.Quantity
				} else {
					r.Totals.PendingSell += o.Quantity
				}
			}
		}
	}
	r.Totals.GrossMinusFeeYen = r.Totals.GrossYen - r.Totals.FeeYen
	r.Complete = r.Failure == "" && pending == 0 && r.Totals.OpenBuy == 0 && r.Totals.OpenSell == 0
	return r
}

// Finish はActorと配送済みSourceの終了残を架空約定で補いません。
//
// 引数: ありません。
// 返り値: ActualResult/errorは独立結果と未完了の理由です。
func (b *ActualBook) Finish() (ActualResult, error) {
	if err := b.ready(); err != nil {
		return b.Snapshot(), err
	}
	if err := b.checkActual(); err != nil {
		return b.Snapshot(), b.stop(err)
	}
	r := b.Snapshot()
	if !r.Complete {
		return r, fmt.Errorf("Actual終了残又は未約定があります")
	}
	for _, s := range b.sourceOrders {
		if s.state == "pending" {
			return r, fmt.Errorf("Sourceの未完了注文があります")
		}
	}
	for _, h := range b.sourceHolds {
		if h.quantity != 0 || h.reserved != 0 {
			return r, fmt.Errorf("Sourceの所有/予約が未完了です")
		}
	}
	b.expireOpportunitiesEOF()
	b.result.Finished = true
	return b.Snapshot(), nil
}
