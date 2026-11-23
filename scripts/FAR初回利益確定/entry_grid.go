// 由来: scripts/FAR5分枠の順行反転と数量/entry_grid.go
// 由来SHA256: 059ded903da7a615026852169571740a9b01598a5c18e97a319192f07a6ce9b1
package miniharvest

import (
	"fmt"
	"math"
	"strings"
)

// assignedGrid は出生後の最初のstrict5分格子を計算します。
//
// 引数: birth(float64)は元Signalの出生時計です。
// 返り値: float64は出生と同時刻を含まない割当枠です。
func assignedGrid(birth float64) float64 { return 300 * (math.Floor(birth/300) + 1) }

// appendOpportunity は出典を不変複写し、一出生を一つだけ登録します。
//
// 引数: s(*sourceOrder)、batchIndex/signalIndex(int)は元通知と同原行内順です。
// 返り値: int/errorは保存索引又は重複です。
func (b *ActualBook) appendOpportunity(s *sourceOrder, batchIndex, signalIndex int) (int, error) {
	key := sourceKey(s.identity.Method, s.signal.ID)
	if _, exists := b.opportunityBySource[key]; exists {
		return 0, fmt.Errorf("出生機会が重複しています")
	}
	i := len(b.result.EntryOpportunities)
	b.result.EntryOpportunities = append(b.result.EntryOpportunities, EntryOpportunityTrace{
		Ordinal: i + 1, Source: valueCopy(s.identity), Side: s.signal.Side,
		BatchIndex: batchIndex, SignalIndex: signalIndex, AssignedAt: assignedGrid(s.signal.Time), Status: "scheduled"})
	b.opportunityBySource[key] = i
	b.result.GridMetrics.Births++
	return i, nil
}

// recordNativeOpportunity はNの旧金融へ介入せず受理結果だけを記録します。
//
// 引数: s(*sourceOrder)、batchIndex/signalIndex(int)、at(float64)、quantity/free(int)、id/reason(string)は旧受理の結果です。
// 返り値: errorは診断の重複だけです。
func (b *ActualBook) recordNativeOpportunity(s *sourceOrder, batchIndex, signalIndex int, at float64, quantity, free int, id, reason string) error {
	i, err := b.appendOpportunity(s, batchIndex, signalIndex)
	if err != nil {
		return err
	}
	p := &b.result.EntryOpportunities[i]
	p.Consumed, p.EvaluatedAt, p.Available, p.Requested, p.EntryOrderID = true, &at, free, quantity, id
	p.Status, p.Reason, p.SourceState = "expired", reason, s.state
	q, age := s.identity.BirthQuote, 0.0
	p.Quote, p.QuoteAgeSeconds = &q, &age
	if quantity > 0 {
		p.Status = "accepted"
		b.result.GridMetrics.Accepted++
	} else {
		b.result.GridMetrics.Expired++
	}
	return nil
}

// scheduleEntries は全Source出生を保持し、Actual新規だけを割当枠へ送ります。
//
// 引数: at(float64)、batches([]NativeBatch)は当原行の公開通知です。
// 返り値: errorは重複又は実所有の不整合です。
func (b *ActualBook) scheduleEntries(at float64, batches []NativeBatch) error {
	for batchIndex, batch := range batches {
		for signalIndex, record := range batch.Delta.Signals {
			if record.Signal.Action != "new" {
				continue
			}
			key := sourceKey(batch.Method, record.Signal.ID)
			s := b.sourceOrders[key]
			if _, exists := b.entryBySource[key]; exists {
				return fmt.Errorf("消費済み実出生が再配送されました")
			}
			if _, err := b.appendOpportunity(s, batchIndex, signalIndex); err != nil {
				return err
			}
			b.result.SourceEvents = append(b.result.SourceEvents, SourceEventTrace{At: at, Phase: "native_new", Method: batch.Method,
				Kind: "new_signal", SignalID: s.signal.ID, Quote: record.Quote, Side: s.signal.Side,
				Quantity: s.signal.Quantity, Available: b.available(s.signal.Side), Reason: "出生を最初の次5分枠へ割当"})
		}
	}
	return b.checkActual()
}

// gridQuiet は開始30分と米国開始30分を半開区間で診断します。
//
// 引数: at(float64)は現在枠です。
// 返り値: bool/string/*boolはquiet・理由・米国区間内（時計未知ならnil）です。
func (b *ActualBook) gridQuiet(at float64) (bool, string, *bool) {
	quiet, reason := false, ""
	if at >= b.result.Session.Start && at < b.result.Session.Start+1800 {
		quiet, reason = true, "セッション開始30分"
	}
	var usQuiet *bool
	if b.result.Session.Kind == "Night" && b.result.Config.USOpen > 0 {
		inside := at >= b.result.Config.USOpen && at < b.result.Config.USOpen+1800
		usQuiet = &inside
		if inside {
			quiet, reason = true, "米国開始30分"
		}
	}
	return quiet, reason, usQuiet
}

// entryDeadline は元手法のForce上限だけを取得し、新しい停止時刻を作りません。
//
// 引数: method(string)は正式Source手法名です。
// 返り値: float64はstrict前に供給すべき境界です。
func (b *ActualBook) entryDeadline(method string) float64 {
	deadline := b.result.Session.ForceClose
	if strings.TrimPrefix(method, "NK225_") == "P164_06" {
		deadline = math.Min(deadline, b.result.Config.USOpen-900)
	}
	return deadline
}

// evaluateOpportunity は当枠の既知Source状態と最後の原行だけで一度判定します。
//
// 引数: i(int)、at(float64)、quiet(bool)、trace(*EntryGridTrace)、gate(EntryGate)は機会索引・枠・quiet・集計先・任意の技法判定です。
// 返り値: errorは出典破損です。正常な未取得/未知/quietは失効として保存します。
func (b *ActualBook) evaluateOpportunity(i int, at float64, quiet bool, trace *EntryGridTrace, gate EntryGate) error {
	p := &b.result.EntryOpportunities[i]
	key := sourceKey(p.Source.Method, p.Source.SignalID)
	s := b.sourceOrders[key]
	if s == nil || s.signal.Action != "new" || s.identity != p.Source || s.signal.Side != p.Side {
		return fmt.Errorf("割当機会の元出生が不整合です")
	}
	p.Consumed, p.EvaluatedAt, p.Status, p.SourceState = true, &at, "expired", s.state
	p.Available = b.available(p.Side)
	if b.haveQuote {
		q, age := b.last, at-b.last.Time
		p.Quote, p.QuoteAgeSeconds = &q, &age
	}
	var hold *sourceHold
	if s.hold != "" {
		hold = b.sourceHolds[sourceKey(p.Source.Method, s.hold)]
		if hold == nil || hold.orderKey != key || hold.side != p.Side || hold.quantity < 0 || hold.reserved < 0 || hold.reserved > hold.quantity {
			return fmt.Errorf("割当枠のSource実在所有が不整合です")
		}
		q, r := hold.quantity, hold.reserved
		p.SourceHoldID, p.SourceQuantity, p.SourceReserved = s.hold, &q, &r
	}
	switch {
	case p.AssignedAt != at:
		p.Reason = "割当枠を通過・後の枠へ復活しない"
	case at >= b.entryDeadline(p.Source.Method):
		p.Reason = "元手法Force境界以降"
	case quiet && b.result.Config.EntryTiming == "B5Q":
		p.Reason = "割当枠が開始30分見送り"
	case s.state == "cancelled":
		p.Reason = "Native取消済みの出生"
	case s.state == "pending":
		p.Reason = "割当枠でSource未取得"
	case s.state != "filled" || hold == nil:
		return fmt.Errorf("取得済みSourceのHold出典が欠落しています")
	case hold.quantity == 0:
		p.Reason = "割当枠でSource完結済み"
	case hold.reserved > 0:
		p.Reason = "割当枠でSource返済予約あり"
	case !trace.QuoteKnown:
		p.RequiredUnknown, p.Reason = true, "割当枠の最新原行の正常気配が必要未知"
	case p.Available == 0:
		p.Reason = "片側上限に空きなし"
		b.result.Metrics.CapRejectedEntries++
	default:
		quantity := min(s.signal.Quantity, hold.quantity, p.Available)
		if quantity <= 0 {
			return fmt.Errorf("取得済み候補の要求量が非正です")
		}
		if gate != nil {
			decision, err := evaluateEntryGate(b.result.Config.GatePolicy, gate, EntryCandidate{
				Ordinal: p.Ordinal, At: at, Side: p.Side, Source: s.identity, Quote: b.last,
				Available: p.Available, Quantity: quantity})
			if err != nil {
				return err
			}
			p.Gate = &decision
			if !decision.Known || !decision.Allowed {
				p.RequiredUnknown, p.Reason = !decision.Known, decision.Reason
				break
			}
		}
		p.Requested, p.EntryOrderID, p.Status = quantity, b.newID(), "accepted"
		p.Reason = "出生量・Source現在残量・片側余力のminを一度受理"
		if p.Available < min(s.signal.Quantity, hold.quantity) {
			b.result.Metrics.CapClippedEntries++
		}
		positionID := fmt.Sprintf("%s-%s-P%06d", b.result.Session.ID, b.result.Key, len(b.result.Orders)+1)
		order := ActualOrder{ID: p.EntryOrderID, Kind: "entry", Side: p.Side, Quantity: quantity, PositionID: positionID,
			Source: s.identity, SourceHoldID: s.hold, RequestTime: at, RequestQuote: b.last, Reason: s.signal.Reason, Status: "pending"}
		b.orders[order.ID] = len(b.result.Orders)
		b.result.Orders = append(b.result.Orders, order)
		b.result.Metrics.EntryRequests++
		b.result.Metrics.EntryAcceptedQuantity += quantity
		trace.AcceptedCount++
		trace.AcceptedQty += quantity
		b.result.GridMetrics.Accepted++
	}
	b.entryBySource[key] = p.EntryOrderID
	if p.Status != "accepted" {
		trace.ExpiredCount++
		b.result.GridMetrics.Expired++
	}
	if p.RequiredUnknown {
		trace.UnknownCount++
		b.result.GridMetrics.RequiredUnknown++
	}
	return nil
}

// OnEntryGrid は5分枠の新規受付だけを進め、原行を再投入しません。
//
// 引数: at(float64)はセッション内の増加する5分格子時計です。
// 返り値: errorは時計/所有破損です。MTM・ATR・Fillは変更しません。
func (b *ActualBook) OnEntryGrid(at float64) error {
	return b.OnEntryGridWithGate(at, nil)
}

// OnEntryGridWithGate は旧5分受付の適格候補だけへ値copyの技法判定を一度渡します。
//
// 引数: at(float64)は枠時計、gate(EntryGate)はA/B/ABで必須、空G0ではnilです。
// 返り値: errorは時計/金融所有/判定契約の不整合です。判定で数量やSourceを変更しません。
func (b *ActualBook) OnEntryGridWithGate(at float64, gate EntryGate) error {
	if err := b.ready(); err != nil {
		return err
	}
	if b.result.Config.GatePolicy == "" && gate != nil || b.result.Config.GatePolicy != "" && gate == nil {
		return b.stop(fmt.Errorf("空G0はnil、A/B/ABは技法callbackが必須です"))
	}
	if !finiteActual(at) || at <= 0 || math.Mod(at, 300) != 0 || at < b.result.Session.Start || at >= b.result.Session.End || at < b.lastEventAt || b.haveGrid && at <= b.lastGridAt {
		return b.stop(fmt.Errorf("新規5分枠の時計が不正です"))
	}
	if b.haveQuote && (!finiteActual(b.last.Time, b.last.Last, b.last.Bid, b.last.Ask) || b.last.Time > at || b.last.Index < 0 || b.last.SourceLine <= 0) {
		return b.stop(fmt.Errorf("新規枠の最後の原行出典が不正です"))
	}
	quiet, reason, usQuiet := b.gridQuiet(at)
	t := EntryGridTrace{At: at, Timing: b.result.Config.EntryTiming, Quiet: quiet, QuietApplied: quiet && b.result.Config.EntryTiming == "B5Q",
		QuietReason: reason, USQuiet: usQuiet, USClockKnown: b.result.Session.Kind == "Day" || b.result.Config.USOpen > 0, Ordinals: []int{}}
	if b.haveQuote {
		q, age := b.last, at-b.last.Time
		t.Quote, t.QuoteAgeSeconds, t.QuoteKnown = &q, &age, normalActual(q)
	}
	if b.result.Config.EntryTiming != "N" {
		for i := range b.result.EntryOpportunities {
			p := b.result.EntryOpportunities[i]
			if p.Consumed || p.AssignedAt > at {
				continue
			}
			t.CandidateCount++
			t.Ordinals = append(t.Ordinals, p.Ordinal)
			if err := b.evaluateOpportunity(i, at, quiet, &t, gate); err != nil {
				return b.stop(err)
			}
		}
	}
	for _, p := range b.result.Positions {
		if p.Side > 0 {
			t.OpenBuy += p.Quantity
		} else {
			t.OpenSell += p.Quantity
		}
	}
	for _, o := range b.result.Orders {
		if o.Kind == "entry" && o.Status == "pending" {
			if o.Side > 0 {
				t.PendingBuy += o.Quantity
			} else {
				t.PendingSell += o.Quantity
			}
		}
	}
	switch {
	case t.AcceptedCount > 0:
		t.Action, t.Reason = "新規", "当5分枠で実新規要求を受理"
		b.result.GridMetrics.NewGrids++
	case t.OpenBuy+t.OpenSell > 0:
		t.Action, t.Reason = "保有", "実保有の継続"
		b.result.GridMetrics.HoldingGrids++
	case t.UnknownCount > 0:
		t.Action, t.Reason = "判定不能", "候補の必須情報が未知"
		b.result.GridMetrics.UnknownGrids++
	default:
		t.Action, t.Reason = "待機", "当枠に受理できる候補なし"
		if t.PendingBuy+t.PendingSell > 0 {
			t.Reason = "実新規約定待ち"
		}
		b.result.GridMetrics.WaitingGrids++
	}
	b.result.GridMetrics.GridCalls++
	if quiet {
		b.result.GridMetrics.QuietGrids++
	}
	if !t.USClockKnown {
		b.result.GridMetrics.UnknownUSGrids++
	}
	b.result.GridTraces = append(b.result.GridTraces, t)
	b.haveGrid, b.lastGridAt, b.lastEventAt = true, at, at
	return b.checkActual()
}

// expireOpportunitiesEOF は金融完結後に残る出生機会だけを失効させます。
//
// 引数: ありません。
// 返り値: ありません。実注文/所有を変更せず、架空の枠や約定を作りません。
func (b *ActualBook) expireOpportunitiesEOF() {
	for i := range b.result.EntryOpportunities {
		p := &b.result.EntryOpportunities[i]
		if p.Consumed {
			continue
		}
		at := b.lastEventAt
		p.Consumed, p.EvaluatedAt, p.Status, p.Reason = true, &at, "expired", "EOFで未消費出生機会を失効"
		key := sourceKey(p.Source.Method, p.Source.SignalID)
		if s := b.sourceOrders[key]; s != nil {
			p.SourceState, p.SourceHoldID = s.state, s.hold
			if h := b.sourceHolds[sourceKey(p.Source.Method, s.hold)]; h != nil {
				q, r := h.quantity, h.reserved
				p.SourceQuantity, p.SourceReserved = &q, &r
			}
		}
		if b.haveQuote {
			q, age := b.last, at-b.last.Time
			p.Quote, p.QuoteAgeSeconds = &q, &age
		}
		p.Available = b.available(p.Side)
		b.entryBySource[key] = ""
		b.result.GridMetrics.Expired++
		b.result.GridMetrics.EOFExpired++
	}
}
