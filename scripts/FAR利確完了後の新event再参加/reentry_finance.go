package far91

import (
	"encoding/json"
	"fmt"
	"math"
)

// ReentryCompletion は実全返済の原行と当時までの実確定額を保持します。
type ReentryCompletion struct {
	PositionID      string  `json:"position_id"`
	EntryOrderID    string  `json:"entry_order_id"`
	At              float64 `json:"at"`
	QuoteIndex      int64   `json:"quote_index"`
	QuoteLine       int64   `json:"quote_line"`
	InitialQuantity int     `json:"initial_quantity"`
	ClosedQuantity  int     `json:"closed_quantity"`
	NetPnL          float64 `json:"net_pnl"`
}

// ReentryPrevious は直近実参加を以前の勝ちへ置き換えず観測する小型出典です。
type ReentryPrevious struct {
	PositionID      string             `json:"position_id"`
	EntryOrderID    string             `json:"entry_order_id"`
	OpportunityID   OpportunityKey     `json:"opportunity_id"`
	InitialQuantity int                `json:"initial_quantity"`
	Quantity        int                `json:"quantity"`
	ReservedExit    int                `json:"reserved_exit"`
	ClosedQuantity  int                `json:"closed_quantity"`
	NetPnL          float64            `json:"net_pnl"`
	PendingEntry    int                `json:"pending_entry"`
	PendingExit     int                `json:"pending_exit"`
	Completion      *ReentryCompletion `json:"completion"`
}

// ReentryChronology は公開pointが前回実全返済より後かを既知性と分けます。
type ReentryChronology struct {
	Point  string `json:"point"`
	Known  bool   `json:"known"`
	After  bool   `json:"after"`
	Reason string `json:"reason"`
}

// ReentryAssessment は受理時の実役割と履歴資格を金融外sidecarへ固定します。
type ReentryAssessment struct {
	At              float64             `json:"at"`
	ReferenceID     string              `json:"reference_id"`
	Side            int                 `json:"side"`
	OpportunityID   OpportunityKey      `json:"opportunity_id"`
	Role            string              `json:"role"`
	SuppliedRank    int                 `json:"supplied_rank"`
	RoleRank        int                 `json:"role_rank"`
	SelectionRank   int                 `json:"selection_rank"`
	SourceSeen      bool                `json:"source_seen"`
	OpportunitySeen bool                `json:"opportunity_seen"`
	PreviousActual  *ReentryPrevious    `json:"previous_actual"`
	Chronology      []ReentryChronology `json:"chronology"`
	Known           bool                `json:"known"`
	RequiredUnknown bool                `json:"required_unknown"`
	Eligible        bool                `json:"eligible"`
	Selected        bool                `json:"selected"`
	Consumed        bool                `json:"consumed"`
	Reason          string              `json:"reason"`
	EntryOrderID    string              `json:"entry_order_id"`
	PositionID      string              `json:"position_id"`
	AcceptedSerial  int                 `json:"accepted_serial"`
}

// NewReentrySourceBook は金融schemaを変えず利確後再参加だけを私有状態で有効化します。
//
// 引数: sessionID/policy(string)は場と固定S、cap(int)は100micro上限です。
// 返り値: *Bookは内部S0G1の独立会計、errorは不正な場・政策・上限です。
func NewReentrySourceBook(sessionID, policy string, cap int) (*Book, error) {
	if policy != "S" {
		return nil, fmt.Errorf("再参加は旧S参照入口・G1だけを使います")
	}
	b, err := NewSourceBook(sessionID, policy, cap)
	if err != nil {
		return nil, err
	}
	b.reentryEnabled = true
	b.allByPosition = map[string]*ActualLot{}
	b.lastActual = map[string]*ActualLot{}
	b.flatStamps = map[string]ReentryCompletion{}
	b.opportunitySeen = map[OpportunityKey]bool{}
	b.entryOpportunity = map[string]OpportunityKey{}
	return b, nil
}

// LastReentryAssessments は最新成功定時の資格snapshotを独立複写します。
//
// 引数: なし。
// 返り値: []ReentryAssessmentは金融へ書き戻せない値です。R0では空配列です。
func (b *Book) LastReentryAssessments() []ReentryAssessment {
	data, err := json.Marshal(append([]ReentryAssessment{}, b.lastAssessments...))
	if err != nil {
		panic("再参加資格の保存値が不正:" + err.Error())
	}
	var copied []ReentryAssessment
	if err = json.Unmarshal(data, &copied); err != nil {
		panic("再参加資格の複写に失敗:" + err.Error())
	}
	return copied
}

// captureReentryCompletions は全fill後・Source通知前に実全返済だけを記録します。
//
// 引数: q(Quote)は今回の正常約定原行です。
// 返り値: errorは所有・Closed確定額の不整合です。pending0資格の時計と混ぜません。
func (b *Book) captureReentryCompletions(q Quote) error {
	for ref, p := range b.lots {
		if p.Quantity > 0 {
			continue
		}
		if p.Quantity < 0 || p.InitialQuantity <= 0 || p.ClosedQuantity != p.InitialQuantity || p.ReservedExit != 0 || b.allByPosition[p.ID] != p {
			return fmt.Errorf("実全返済の所有又は量が不整合")
		}
		quantity, net, lastLine, lastAt := 0, 0.0, int64(0), 0.0
		entryID := ""
		for _, o := range b.orders {
			if o.PositionID == p.ID && o.Kind == "entry" {
				if entryID != "" {
					return fmt.Errorf("同じ実玉へ複数の新規要求")
				}
				entryID = o.ID
			}
		}
		for _, c := range b.closed {
			if c.PositionID == p.ID {
				quantity += c.Quantity
				net += c.PnL5
				lastLine, lastAt = c.ExitLine, c.ExitTime
			}
		}
		if entryID == "" || quantity != p.InitialQuantity || net != p.NetPnL || !actualFinite(net) || lastLine != q.Line || lastAt != q.Time {
			return fmt.Errorf("実全返済が当原行の確定片と一致しない")
		}
		if _, duplicate := b.flatStamps[p.ID]; duplicate {
			return fmt.Errorf("実全返済stampの上書き")
		}
		b.flatStamps[p.ID] = ReentryCompletion{PositionID: p.ID, EntryOrderID: entryID, At: q.Time, QuoteIndex: q.Index, QuoteLine: q.Line, InitialQuantity: p.InitialQuantity, ClosedQuantity: quantity, NetPnL: net}
		delete(b.lots, ref)
	}
	return nil
}

// validateEntryOpportunity は現在E1の公開済み全点を候補と原行へ厳密に結びます。
//
// 引数: at(float64)、q(Quote)、ref(ReferenceLot)、o(EntryOpportunity)は当時定時と公開出典です。
// 返り値: map[int64]OpportunityPublicationは一意公開索引、errorは欠落・未来・式/順序不整合です。
func (b *Book) validateEntryOpportunity(at float64, q Quote, ref ReferenceLot, o EntryOpportunity) (map[int64]OpportunityPublication, error) {
	e := o.Event
	key := OpportunityKey{Session: b.session, ReferenceID: ref.ID, EventID: e.ID}
	if !o.Known || o.Kind != OpportunityKind || o.RuleVersion != OpportunityRuleVersion || o.Reason != OpportunityReason ||
		o.At != at || o.ReferenceID != ref.ID || o.Side != ref.Side || e.Side != ref.Side || o.OpportunityID != key || e.ID == "" ||
		!actualFinite(at) || !actualFinite(e.EpochStart) || at <= 0 || e.EpochStart <= 0 || e.EpochStart >= at ||
		ref.Method != "NK225_"+e.Window || (e.Window != "D164_15" && e.Window != "P164_06" && e.Window != "U165_03") {
		return nil, fmt.Errorf("再参加機会の候補・種類・場・方向又は時計が不整合")
	}
	points := []EventPoint{e.Impulse, e.Pullback, e.Recovery, e.Confirmation}
	for n, p := range points {
		if p.ObservationID <= 0 || !actualFinite(p.BarEnd) || !actualFinite(p.PublishedAt) || p.BarEnd <= e.EpochStart || p.BarEnd > p.PublishedAt || p.PublishedAt > at ||
			n > 0 && (p.BarEnd < points[n-1].BarEnd || p.PublishedAt < points[n-1].PublishedAt || p.ObservationID < points[n-1].ObservationID) {
			return nil, fmt.Errorf("現在E1のevent公開点が未来又は逆順")
		}
	}
	if !(e.Impulse.BarEnd < e.Pullback.BarEnd && e.Pullback.BarEnd < e.Recovery.BarEnd && e.Recovery.BarEnd <= e.Confirmation.BarEnd) ||
		!(e.Impulse.ObservationID < e.Pullback.ObservationID && e.Pullback.ObservationID < e.Recovery.ObservationID && e.Recovery.ObservationID <= e.Confirmation.ObservationID) ||
		(e.Recovery.BarEnd == e.Confirmation.BarEnd) != (e.Recovery == e.Confirmation) || at-e.Confirmation.BarEnd >= 900 {
		return nil, fmt.Errorf("現在E1のi<p<r<=k又は期限が不整合")
	}
	publications := map[int64]OpportunityPublication{}
	lastOrdinal := int64(0)
	for _, p := range points {
		if _, exists := publications[p.ObservationID]; exists {
			continue
		}
		n := len(publications)
		if n >= len(o.Publications) {
			return nil, fmt.Errorf("現在E1の公開Recordが欠落")
		}
		pub := o.Publications[n]
		pq := pub.Quote
		if pub.ObservationID != p.ObservationID || pub.At != p.PublishedAt || pub.BarEnd != p.BarEnd || pub.Ordinal <= lastOrdinal ||
			(pub.Origin != "quote" && pub.Origin != "three_timer" && pub.Origin != "core_timer") ||
			!actualFinite(pq.Time) || !actualFinite(pq.Last) || !actualFinite(pq.Bid) || !actualFinite(pq.Ask) || pq.Time <= 0 || pq.Time > pub.At || pq.Last <= 0 ||
			pq.Index < 0 || pq.Line <= 0 || pq.Time > q.Time || pq.Index > q.Index || pq.Line > q.Line {
			return nil, fmt.Errorf("現在E1の公開Recordと原行出典が不整合")
		}
		publications[p.ObservationID] = pub
		lastOrdinal = pub.Ordinal
	}
	if len(publications) != len(o.Publications) {
		return nil, fmt.Errorf("現在E1の公開Recordに重複又は余剰")
	}
	return publications, nil
}

// reentryAfter は時刻同値の公開を実原行の両番号で判定します。
//
// 引数: name(string)、pub(OpportunityPublication)、done(ReentryCompletion)は点名・公開・前回実全返済です。
// 返り値: ReentryChronologyは後/前と、同時計での未証明を分けます。
func reentryAfter(name string, pub OpportunityPublication, done ReentryCompletion) ReentryChronology {
	r := ReentryChronology{Point: name, Known: true}
	if pub.At > done.At {
		r.After, r.Reason = true, "実全返済より後の公開時計"
		return r
	}
	if pub.At < done.At {
		r.Reason = "実全返済より前の公開時計"
		return r
	}
	q := pub.Quote
	if q.Time == done.At && q.Index > done.QuoteIndex && q.Line > done.QuoteLine {
		r.After, r.Reason = true, "同時計の別原行で両番号が実全返済より後"
	} else if q.Time == done.At && q.Index == done.QuoteIndex && q.Line == done.QuoteLine {
		r.Reason = "同原行は公開が金融fillより先"
	} else if q.Time <= done.At && q.Index <= done.QuoteIndex && q.Line <= done.QuoteLine {
		r.Reason = "同時計の公開原行が実全返済より前"
	} else {
		r.Known, r.Reason = false, "同時計の公開原行の前後を両番号で証明できない"
	}
	return r
}

// reentryHistory は金融自身の最新実参加・確定純額と新p/r/kを検査します。
//
// 引数: ref(ReferenceLot)、o(EntryOpportunity)、pubs(map[int64]OpportunityPublication)、a(*ReentryAssessment)は候補と出典です。
// 返り値: boolは履歴資格成立です。現在価格・占有の検査は呼出側で共通化します。
func (b *Book) reentryHistory(ref ReferenceLot, o EntryOpportunity, pubs map[int64]OpportunityPublication, a *ReentryAssessment) (bool, error) {
	if !a.SourceSeen {
		a.Reason = "未参加のfresh参照"
		return true, nil
	}
	p := b.lastActual[ref.ID]
	if p == nil {
		a.Reason = "受理履歴だけで実取得した参加がない"
		return false, nil
	}
	if p.ReferenceID != ref.ID || p.Side != ref.Side || p.Method != ref.Method || b.allByPosition[p.ID] != p {
		return false, fmt.Errorf("直近実参加の参照所有が不整合")
	}
	previous := &ReentryPrevious{PositionID: p.ID, OpportunityID: b.entryOpportunity[p.ID], InitialQuantity: p.InitialQuantity,
		Quantity: p.Quantity, ReservedExit: p.ReservedExit, ClosedQuantity: p.ClosedQuantity, NetPnL: p.NetPnL}
	for _, order := range b.orders {
		if order.PositionID != p.ID {
			continue
		}
		if order.Kind == "entry" {
			previous.EntryOrderID = order.ID
			previous.PendingEntry += order.Remaining
		} else {
			previous.PendingExit += order.Remaining
		}
	}
	if done, exists := b.flatStamps[p.ID]; exists {
		copied := done
		previous.Completion = &copied
	}
	a.PreviousActual = previous
	if p.InitialQuantity <= 0 || p.Quantity != 0 || p.ClosedQuantity != p.InitialQuantity || p.ReservedExit != 0 || previous.PendingEntry != 0 || previous.PendingExit != 0 || previous.Completion == nil {
		a.Reason = "直近実参加の全返済又は未約定残0が未完了"
		return false, nil
	}
	if p.NetPnL <= 0 {
		a.Reason = "直近実参加の費用後実確定額がstrict正でない"
		return false, nil
	}
	if a.OpportunitySeen || previous.OpportunityID.EventID == o.Event.ID {
		a.Reason = "同じ再開eventは取消後も再利用しない"
		return false, nil
	}
	for _, item := range []struct {
		name  string
		point EventPoint
	}{{"p", o.Event.Pullback}, {"r", o.Event.Recovery}, {"k", o.Event.Confirmation}} {
		c := reentryAfter(item.name, pubs[item.point.ObservationID], *previous.Completion)
		a.Chronology = append(a.Chronology, c)
	}
	for _, c := range a.Chronology {
		if !c.Known {
			a.Known, a.RequiredUnknown, a.Reason = false, true, "新p/r/kの公開前後が未知"
			return false, nil
		}
		if !c.After {
			a.Reason = "p/r/kの全点が前回実全返済より後でない"
			return false, nil
		}
	}
	a.Reason = "直近利確完了後の別eventを確認"
	return true, nil
}

// OnSourceGridWithReentry はfresh優先の後だけ利確完了後の別eventへ再参加します。
//
// 引数: at/q/snapshot/c0/tech/anchorは旧6入力、opportunities(map[string]EntryOpportunity)は旧E1供給候補の現在出典です。
// 返り値: errorは会計混用・当時入力・出典又は所有の不整合です。金融Bookへ新tagを加えません。
func (b *Book) OnSourceGridWithReentry(at float64, q Quote, snapshot ReadSnapshot, c0 Decision, tech TechnicalView, anchor StructureAnchor, opportunities map[string]EntryOpportunity) error {
	if !b.reentryEnabled || b.sourcePolicy != "S" || b.mode != "S0G1" || b.stop != "S0" || b.guard != "G1" || b.holdEnabled || b.confirmEnabled {
		return fmt.Errorf("再参加専用のS/G1会計が必要です")
	}
	if !actualFinite(at) || !actualFinite(q.Time) || b.haveGrid && at <= b.lastGrid {
		return fmt.Errorf("再参加定時時計は有限の昇順が必要です")
	}
	anchor, err := normalizeAnchor(at, tech, anchor)
	if err != nil {
		return err
	}
	pool, err := sourcePool(at, snapshot)
	if err != nil {
		return err
	}
	if len(opportunities) != len(pool) {
		return fmt.Errorf("E1供給候補と機会ID集合が不一致")
	}
	indices := map[string]map[int64]OpportunityPublication{}
	for _, row := range pool {
		o, exists := opportunities[row.Reference.ID]
		if !exists {
			return fmt.Errorf("E1供給候補の現在機会が欠落")
		}
		index, err := b.validateEntryOpportunity(at, q, row.Reference, o)
		if err != nil {
			return err
		}
		indices[row.Reference.ID] = index
	}
	occupied := b.occupied()
	quality := actualNormal(q) && actualFinite(q.Last) && q.Last > 0 && q.Time <= at && at-q.Time <= 15 && b.haveQuote && q.Index == b.last.Index && q.Time == b.last.Time && q.Line == b.last.Line && q.Bid == b.last.Bid && q.Ask == b.last.Ask && q.Last == b.last.Last && snapshot.Started && snapshot.At == q.Time
	assessments := make([]ReentryAssessment, len(pool))
	candidates := make([]GridCandidate, len(pool))
	roleRanks := map[string]int{}
	priority := []int{}
	for _, seen := range []bool{false, true} {
		for i, row := range pool {
			if b.seen[row.Reference.ID] == seen {
				priority = append(priority, i)
			}
		}
	}
	for i, row := range pool {
		r, o := row.Reference, opportunities[row.Reference.ID]
		role, stage := "初参加", "初参加候補"
		if b.seen[r.ID] {
			role, stage = "利確後再参加", "利確後再参加候補"
		}
		roleRanks[role]++
		a := ReentryAssessment{At: at, ReferenceID: r.ID, Side: r.Side, OpportunityID: o.OpportunityID, Role: role, SuppliedRank: i + 1, RoleRank: roleRanks[role],
			SourceSeen: b.seen[r.ID], OpportunitySeen: b.opportunitySeen[o.OpportunityID], Known: true, Chronology: []ReentryChronology{}}
		history, err := b.reentryHistory(r, o, indices[r.ID], &a)
		if err != nil {
			return err
		}
		check := &SourceCheck{Rank: i + 1, Seen: a.SourceSeen, C0Passed: c0.Allowed && c0.Side == r.Side, RealEntryStage: stage}
		switch {
		case r.Closing:
			a.Reason = "参照返済予約あり"
		case occupied:
			a.Reason = "実保有又は注文で占有"
		case !quality:
			a.Known, a.RequiredUnknown, a.Reason = false, true, "Source又は気配品質が未知"
		case !history:
		default:
			a.Eligible, check.Eligible = true, true
		}
		assessments[i] = a
		candidates[i] = GridCandidate{ReferenceID: r.ID, SourceQuantity: r.Quantity, Side: r.Side, Role: r.Kind, SourceCheck: check}
	}
	context := &SourceContext{Policy: "S", Method: snapshot.Method, SnapshotAt: snapshot.At, SnapshotIndex: snapshot.SourceIndex, Started: snapshot.Started, Occupied: occupied, SeenBeforeCount: len(b.seen)}
	d := ActualDecision{At: at, QuoteTime: q.Time, QuoteIndex: q.Index, Action: "待ち", Reason: "有効な参照玉なし", Candidates: candidates, SourceContext: context}
	if occupied {
		d.Action, d.Reason = "処理中", "既存注文の約定待ち"
		for _, p := range b.lots {
			if p.Quantity > 0 {
				d.Action, d.Reason = "保有継続", "同時一建玉を維持"
				break
			}
		}
	}
	for rank, i := range priority {
		a := &assessments[i]
		a.SelectionRank = rank + 1
		if !a.Eligible {
			continue
		}
		if context.SelectedID != "" {
			a.Reason = "同枠の優先候補を採用済み"
			continue
		}
		r := pool[i].Reference
		quantity := min(b.cap-b.used(r.Side), r.Quantity)
		if quantity <= 0 {
			a.Eligible, a.Reason = false, "片側空き数量なし"
			continue
		}
		distance := 125.0
		var atr *float64
		if tech.ATRKnown && actualFinite(tech.ATR3) && tech.ATR3 >= 0 {
			atr = actualPointer(tech.ATR3)
			distance = math.Min(125, math.Max(15, math.Ceil(tech.ATR3/5)*5))
		}
		binding := &SourceBinding{Policy: "S", ReadLot: cloneSourceLot(pool[i]), SnapshotMethod: snapshot.Method, SnapshotAt: snapshot.At, SnapshotIndex: snapshot.SourceIndex, SnapshotStarted: snapshot.Started,
			Rank: i + 1, RequestedQuantity: quantity, ReferenceKind: r.Kind, C0Used: false, C0Allowed: c0.Allowed, C0RequiredUnknown: c0.RequiredUnknown, C0Side: c0.Side, C0Role: c0.Role, C0Reason: c0.Reason}
		stage, reason := "初参加要求", "FAR参照の初参加要求"
		if a.Role == "利確後再参加" {
			stage, reason = "利確後再参加要求", "FAR参照の利確後再参加要求"
		}
		b.entrySerial++
		positionID := fmt.Sprintf("%s_%s_P%06d", b.session, b.mode, b.entrySerial)
		o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "entry", ReferenceID: r.ID, PositionID: positionID, Side: r.Side, Quantity: quantity, Remaining: quantity,
			RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: reason, Status: "pending", Source: r, Role: r.Kind, ATR: atr, D: distance, StructureAnchor: anchor,
			HoldAnchor: HoldAnchor{Kind: HoldKind, RuleVersion: HoldRuleVersion, Tick: HoldTick, Reason: sourceHoldUnusedReason}, SourceEntry: binding, RealEntryStage: stage}
		b.orders = append(b.orders, o)
		b.seen[r.ID], b.opportunitySeen[a.OpportunityID] = true, true
		b.entryOpportunity[positionID] = a.OpportunityID
		a.Selected, a.Consumed, a.EntryOrderID, a.PositionID, a.AcceptedSerial = true, true, o.ID, positionID, b.entrySerial
		a.Reason = "E1現在機会で" + a.Role + "要求"
		context.SelectedID = r.ID
		d.Candidates[i].RequestedQuantity = quantity
		d.Action, d.Reason = "新規要求", a.Reason
	}
	for i, a := range assessments {
		check := d.Candidates[i].SourceCheck
		check.Selected, check.Eligible, check.RequiredUnknown, check.Reason = a.Selected, a.Eligible, a.RequiredUnknown, a.Reason
		d.Candidates[i].Reason = a.Reason
		context.RequiredUnknown = context.RequiredUnknown || a.RequiredUnknown
	}
	if d.Action == "待ち" && context.RequiredUnknown {
		d.Action, d.Reason = "判定不能", "再参加の必要出典が未知"
	}
	context.SeenAfterCount = len(b.seen)
	b.haveGrid, b.lastGrid = true, at
	b.decisions = append(b.decisions, d)
	b.lastAssessments = assessments
	// ----------------------------------------
	// 呼出側のpointer/sliceから資格snapshotを書き換えられないよう独立複写します。
	b.lastAssessments = b.LastReentryAssessments()
	return nil
}
