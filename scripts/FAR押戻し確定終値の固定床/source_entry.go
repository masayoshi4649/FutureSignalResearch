// 90派生元: scripts/FAR利益床と収穫配分の比較/source_entry.go
// 90派生元SHA256: bf4478f979d85986d2208762371fecf78523cd93f0e6cb4aa6af7041c8ed1cd4
// 固定89は変更せず、G1対照全文と押戻し確定終値の固定床を別会計で比較します。

// 89派生元: scripts/FAR参照玉と可変数量の比較/source_entry.go
// 89派生元SHA256: b9a6fd1a2e9939f8a7f42bf5f57231aaeeaeff6e42f8dda66fe5218acda8f9d0
// 固定87は変更せず、G1旧全文とG2既存分岐を別会計で比較します。

package far90

import (
	"fmt"
	"math"
	"sort"
)

const sourceHoldUnusedReason = "FAR参照入口のためC0保持帯線は未使用"
const PullbackExitReason = "押戻し確定終値固定否定"

// SourceBindingは受理した要求時の参照量とC0利用の有無を不変の値で保存します。
// 参照Kindと親初回量を実側段階又は現在量から再構成しません。
type SourceBinding struct {
	Policy            string  `json:"policy"`
	ReadLot           ReadLot `json:"read_lot"`
	SnapshotMethod    string  `json:"snapshot_method"`
	SnapshotAt        float64 `json:"snapshot_at"`
	SnapshotIndex     int64   `json:"snapshot_index"`
	SnapshotStarted   bool    `json:"snapshot_started"`
	Rank              int     `json:"rank"`
	RequestedQuantity int     `json:"requested_quantity"`
	ReferenceKind     string  `json:"reference_kind"`
	C0Used            bool    `json:"c0_used"`
	C0Allowed         bool    `json:"c0_allowed"`
	C0RequiredUnknown bool    `json:"c0_required_unknown"`
	C0Side            int     `json:"c0_side"`
	C0Role            string  `json:"c0_role"`
	C0Reason          string  `json:"c0_reason"`
}

// SourceContextは定時の元snapshotと実会計の占有・採用を結びます。
type SourceContext struct {
	Policy          string  `json:"policy"`
	Method          string  `json:"method"`
	SnapshotAt      float64 `json:"snapshot_at"`
	SnapshotIndex   int64   `json:"snapshot_index"`
	Started         bool    `json:"started"`
	Occupied        bool    `json:"occupied"`
	SeenBeforeCount int     `json:"seen_before_count"`
	SeenAfterCount  int     `json:"seen_after_count"`
	SelectedID      string  `json:"selected_id"`
	RequiredUnknown bool    `json:"required_unknown"`
	C0Used          bool    `json:"c0_used"`
}

// SourceCheckは元poolの全候補を、配列順・seen・C0最終許可と採用へ分けます。
type SourceCheck struct {
	Rank            int    `json:"rank"`
	Seen            bool   `json:"seen"`
	Eligible        bool   `json:"eligible"`
	C0Passed        bool   `json:"c0_passed"`
	RequiredUnknown bool   `json:"required_unknown"`
	Selected        bool   `json:"selected"`
	RealEntryStage  string `json:"real_entry_stage"`
	Reason          string `json:"reason"`
}

// SourceEffectは通知の元比率と実側への作用を0丸めも含め一度だけ保存します。
type SourceEffect struct {
	ID                string  `json:"id"`
	ReferenceID       string  `json:"reference_id"`
	At                float64 `json:"at"`
	QuoteTime         float64 `json:"quote_time"`
	QuoteIndex        int64   `json:"quote_index"`
	QuoteLine         int64   `json:"quote_line"`
	Origin            string  `json:"origin"`
	Before            int     `json:"before"`
	Quantity          int     `json:"quantity"`
	Reason            string  `json:"reason"`
	PendingBefore     int     `json:"pending_before"`
	Cancelled         int     `json:"cancelled"`
	UnreservedBefore  int     `json:"unreserved_before"`
	ExitRequested     int     `json:"exit_requested"`
	UnreservedAfter   int     `json:"unreserved_after"`
	ExitOrderID       string  `json:"exit_order_id"`
	OrdersBeforeCount int     `json:"orders_before_count"`
	OrdersAfterCount  int     `json:"orders_after_count"`
}

// NewSourceBookはSource参照量入口だけを有効にし、旧保持帯床と複合確認を無効にします。
//
// 引数: sessionID/policy(string)は場とS/SC、cap(int)は100です。
// 返り値: *Bookは独立S0G1会計、errorは政策又は上限の不正です。
func NewSourceBook(sessionID, policy string, cap int) (*Book, error) {
	if policy != "S" && policy != "SC" {
		return nil, fmt.Errorf("Source政策はS又はSCが必要です")
	}
	b, err := NewBook(sessionID, "S0G1", cap, false)
	if err != nil {
		return nil, err
	}
	b.sourcePolicy = policy
	return b, nil
}

// NewSourceGuardBook は元Source可変量入口のままG1又は保護付き全量G2を選びます。
//
// 引数: sessionID/policy/guard(string)は場・旧S/SC政策・G1/G2、cap(int)は100です。
// 返り値: *Bookは独立S0G1/S0G2会計、errorは政策・guard・上限不正です。
func NewSourceGuardBook(sessionID, policy, guard string, cap int) (*Book, error) {
	if guard == "G1" {
		return NewSourceBook(sessionID, policy, cap)
	}
	if guard != "G2" || (policy != "S" && policy != "SC") {
		return nil, fmt.Errorf("Source政策はS又はSC、利益配分はG1又はG2が必要です")
	}
	b, err := NewBook(sessionID, "S0G2", cap, false)
	if err != nil {
		return nil, err
	}
	b.sourcePolicy = policy
	return b, nil
}

// NewPullbackSourceBook は旧G1のSource入口へ押戻し確定終値の固定床だけを加えます。
//
// 引数: sessionID/policy(string)は場と固定S政策、cap(int)は旧100上限です。
// 返り値: *Bookは内部S2G1の独立会計、errorは場・政策・上限の不正です。
func NewPullbackSourceBook(sessionID, policy string, cap int) (*Book, error) {
	if policy != "S" {
		return nil, fmt.Errorf("押戻し床は旧S参照入口・G1だけを使います")
	}
	b, err := NewSourceBook(sessionID, policy, cap)
	if err != nil {
		return nil, err
	}
	b.mode, b.stop = "S2G1", "S2"
	return b, nil
}

// normalizePullback は候補別の凍結出典を検査し、S2だけの汎用固定価格線へ写します。
//
// 引数: at(float64)、reference(ReferenceLot)、a(PullbackAnchor)は要求時計・選定候補・当時公開出典です。
// 返り値: StructureAnchorはEMAと区別したS2価格線、errorは欠落・未来・異側・式又は因果順の不整合です。
func normalizePullback(at float64, reference ReferenceLot, a PullbackAnchor) (StructureAnchor, error) {
	e := a.Event
	points := []EventPoint{e.Impulse, e.Pullback, e.Recovery, e.Confirmation}
	if !a.Known || a.Kind != PullbackKind || a.RuleVersion != PullbackRuleVersion ||
		a.At != at || a.ReferenceID != reference.ID || a.Side != reference.Side ||
		(a.Side != 1 && a.Side != -1) || a.Side != e.Side || e.ID == "" ||
		!actualFinite(at) || at <= 0 || !actualFinite(a.Close) || a.Close <= 0 ||
		!actualFinite(a.Price) || a.Price <= 0 || a.Tick != PullbackTick ||
		a.Price != a.Close-float64(a.Side)*PullbackTick || a.Reason != PullbackExitReason ||
		!actualFinite(e.EpochStart) || e.EpochStart <= 0 || e.EpochStart > at ||
		reference.Method != "NK225_"+e.Window ||
		(e.Window != "D164_15" && e.Window != "P164_06" && e.Window != "U165_03") ||
		a.PullbackOrdinal <= 0 ||
		(a.PullbackOrigin != "three_timer" && a.PullbackOrigin != "core_timer" && a.PullbackOrigin != "quote") {
		return StructureAnchor{}, fmt.Errorf("S2候補の既知出典・方向・時計又は固定価格式が不整合")
	}
	for i, p := range points {
		if p.ObservationID <= 0 || !actualFinite(p.BarEnd) || !actualFinite(p.PublishedAt) ||
			p.BarEnd <= e.EpochStart || p.BarEnd > p.PublishedAt || p.PublishedAt > at ||
			i > 0 && (p.BarEnd < points[i-1].BarEnd || p.PublishedAt < points[i-1].PublishedAt || p.ObservationID < points[i-1].ObservationID) {
			return StructureAnchor{}, fmt.Errorf("S2イベントの公開順・epoch又は未来参照が不整合")
		}
	}
	if !(e.Impulse.BarEnd < e.Pullback.BarEnd && e.Pullback.BarEnd < e.Recovery.BarEnd && e.Recovery.BarEnd <= e.Confirmation.BarEnd) ||
		!(e.Impulse.ObservationID < e.Pullback.ObservationID && e.Pullback.ObservationID < e.Recovery.ObservationID && e.Recovery.ObservationID <= e.Confirmation.ObservationID) ||
		e.Recovery.BarEnd == e.Confirmation.BarEnd && e.Recovery != e.Confirmation ||
		at-e.Confirmation.BarEnd >= 900 {
		return StructureAnchor{}, fmt.Errorf("S2イベントのi<p<r<=k又は既存期限が不整合")
	}
	q := a.PullbackQuote
	if !actualFinite(q.Time) || q.Time <= 0 || q.Time > e.Pullback.PublishedAt || q.Index < 0 || q.Line < 0 ||
		!actualFinite(q.Last) || q.Last <= 0 || !actualFinite(q.Bid) || !actualFinite(q.Ask) {
		return StructureAnchor{}, fmt.Errorf("S2押し足公開原行の時計・番号又は有限価格が不整合")
	}
	return StructureAnchor{Known: true, Price: a.Price, At: at, BarEnd: e.Pullback.BarEnd, Reason: PullbackExitReason}, nil
}

// cloneSourceLotは親量のpointerを外部Sourceと共有しない読取値にします。
//
// 引数: value(ReadLot)は要求時のadapter出力です。
// 返り値: ReadLotは同じ数値・既知性の独立複写です。
func cloneSourceLot(value ReadLot) ReadLot {
	if value.NativeParentInitialMicro != nil {
		n := *value.NativeParentInitialMicro
		value.NativeParentInitialMicro = &n
	}
	if value.NativeParentOriginalDesired != nil {
		n := *value.NativeParentOriginalDesired
		value.NativeParentOriginalDesired = &n
	}
	if value.NativeSmallInitialEligible != nil {
		n := *value.NativeSmallInitialEligible
		value.NativeSmallInitialEligible = &n
	}
	return value
}

// sourcePoolは現在参照玉だけを検査し、元At/IDの順で独立複写します。
//
// 引数: at(float64)、snapshot(ReadSnapshot)は定時と当時Sourceです。
// 返り値: []ReadLotは安定順の全候補、errorは未来・重複・量・所有の矛盾です。
func sourcePool(at float64, snapshot ReadSnapshot) ([]ReadLot, error) {
	if !actualFinite(snapshot.At) || snapshot.At > at || len(snapshot.Closes) != 0 {
		return nil, fmt.Errorf("定時Sourceの時計又は未配送Closeが不正")
	}
	if snapshot.Started && snapshot.SourceIndex < 0 || !snapshot.Started && len(snapshot.Lots) > 0 {
		return nil, fmt.Errorf("Sourceの開始状態と原行番号・所有が不整合")
	}
	if len(snapshot.Lots) > 0 && snapshot.Method != "NK225_D164_15" && snapshot.Method != "NK225_P164_06" && snapshot.Method != "NK225_U165_03" {
		return nil, fmt.Errorf("Source現在玉は固定三手法が必要です")
	}
	pool := make([]ReadLot, 0, len(snapshot.Lots))
	ids := map[string]bool{}
	for _, row := range snapshot.Lots {
		r := row.Reference
		if r.ID == "" || r.InternalID == "" || r.Parent == "" || r.SourceID == "" || r.Owner == "" || r.Kind == "" || ids[r.ID] || r.Method != snapshot.Method || (r.Side != 1 && r.Side != -1) || r.Quantity < 1 || r.Quantity > 100 || row.ReferenceInitialQuantity < r.Quantity || !actualFinite(r.At) || r.At > snapshot.At || !actualFinite(r.Entry) || r.Entry <= 0 {
			return nil, fmt.Errorf("Source参照玉のID・出典・現在量又は時計が不正")
		}
		if row.NativeParentInitialMicro != nil && *row.NativeParentInitialMicro <= 0 || row.NativeParentOriginalDesired != nil && *row.NativeParentOriginalDesired <= 0 {
			return nil, fmt.Errorf("既知のSource親初回量が不正")
		}
		ids[r.ID] = true
		pool = append(pool, cloneSourceLot(row))
	}
	sort.SliceStable(pool, func(i, j int) bool {
		if pool[i].Reference.At != pool[j].Reference.At {
			return pool[i].Reference.At < pool[j].Reference.At
		}
		return pool[i].Reference.ID < pool[j].Reference.ID
	})
	return pool, nil
}

// OnSourceGridは元現在玉を一枠一ID・変数量で選び、SCだけ最終C0を必要とします。
//
// 引数: at(float64)、q(Quote)、snapshot(ReadSnapshot)、c0(Decision)、tech(TechnicalView)、anchor(StructureAnchor)は当時入力です。
// 返り値: errorは時計・Source写像・EMAの不整合です。SにC0保持帯又はC0未知を課しません。
func (b *Book) OnSourceGrid(at float64, q Quote, snapshot ReadSnapshot, c0 Decision, tech TechnicalView, anchor StructureAnchor) error {
	if b.stop == "S2" {
		return fmt.Errorf("S2は候補別の押戻し出典を伴う専用Source入口が必要です")
	}
	return b.onSourceGrid(at, q, snapshot, c0, tech, anchor, nil)
}

// OnSourceGridWithPullback は入口gateを増やさず候補別の押し足価格線を受理時に凍結します。
//
// 引数: at/q/snapshot/c0/tech/anchorは旧Sourceの6引数、anchors(map[string]PullbackAnchor)は供給候補IDごとの当時出典です。
// 返り値: errorはS2以外の混用・出典の不足又は不整合です。未知をATRへの無言fallbackにしません。
func (b *Book) OnSourceGridWithPullback(at float64, q Quote, snapshot ReadSnapshot, c0 Decision, tech TechnicalView, anchor StructureAnchor, anchors map[string]PullbackAnchor) error {
	if b.stop != "S2" || b.mode != "S2G1" || b.guard != "G1" || b.sourcePolicy != "S" {
		return fmt.Errorf("押戻し専用入口はS2G1・S会計だけで使います")
	}
	return b.onSourceGrid(at, q, snapshot, c0, tech, anchor, anchors)
}

// onSourceGrid は旧Sourceの選択順を保ち、S2だけで選定前に価格出典を結びます。
//
// 引数: 旧6入力とanchors(map[string]PullbackAnchor)は同じ定時の供給候補です。
// 返り値: errorは旧時計・Source品質又はS2候補の不変条件違反です。
func (b *Book) onSourceGrid(at float64, q Quote, snapshot ReadSnapshot, c0 Decision, tech TechnicalView, anchor StructureAnchor, anchors map[string]PullbackAnchor) error {
	if (b.sourcePolicy != "S" && b.sourcePolicy != "SC") || b.holdEnabled || b.confirmEnabled {
		return fmt.Errorf("Source専用の無保持帯・無複合確認会計が必要です")
	}
	if !actualFinite(at) || !actualFinite(q.Time) || b.haveGrid && at <= b.lastGrid {
		return fmt.Errorf("Source定時時計は有限の昇順が必要です")
	}
	if b.sourcePolicy == "SC" {
		if c0.Base.At != at || c0.Base.Quote != q || c0.Base.Technical != tech {
			return fmt.Errorf("SCのC0時計・気配・技法が当時入力と不整合")
		}
		c := c0.Base.Evidence
		if c0.Allowed && (c.Time != q.Time || c.SourceLine != q.Line || c.Last != q.Last || c.Bid != q.Bid || c.Ask != q.Ask) {
			return fmt.Errorf("SCの最終許可が別原行のC0特徴に基づいています")
		}
	}
	anchor, err := normalizeAnchor(at, tech, anchor)
	if err != nil {
		return err
	}
	pool, err := sourcePool(at, snapshot)
	if err != nil {
		return err
	}
	var fixed map[string]StructureAnchor
	if b.stop == "S2" {
		if len(anchors) != len(pool) {
			return fmt.Errorf("S2供給候補と押戻し出典のID集合が不一致")
		}
		fixed = make(map[string]StructureAnchor, len(pool))
		for _, row := range pool {
			a, ok := anchors[row.Reference.ID]
			if !ok {
				return fmt.Errorf("S2供給候補の押戻し出典が欠落")
			}
			if a.PullbackQuote.Time > q.Time || a.PullbackQuote.Index > q.Index || a.PullbackQuote.Line > q.Line {
				return fmt.Errorf("S2押し足の公開原行が要求の直前原行より未来です")
			}
			price, err := normalizePullback(at, row.Reference, a)
			if err != nil {
				return err
			}
			fixed[row.Reference.ID] = price
		}
	}
	b.haveGrid = true
	b.lastGrid = at
	occupied := b.occupied()
	context := &SourceContext{Policy: b.sourcePolicy, Method: snapshot.Method, SnapshotAt: snapshot.At, SnapshotIndex: snapshot.SourceIndex, Started: snapshot.Started, Occupied: occupied, SeenBeforeCount: len(b.seen), C0Used: b.sourcePolicy == "SC"}
	d := ActualDecision{At: at, QuoteTime: q.Time, QuoteIndex: q.Index, Action: "待ち", Reason: "有効な参照玉なし", Candidates: []GridCandidate{}, SourceContext: context}
	quality := actualNormal(q) && actualFinite(q.Last) && q.Last > 0 && q.Time <= at && at-q.Time <= 15 && b.haveQuote && q.Index == b.last.Index && q.Time == b.last.Time && q.Line == b.last.Line && q.Bid == b.last.Bid && q.Ask == b.last.Ask && q.Last == b.last.Last && snapshot.Started && snapshot.At == q.Time
	if occupied {
		d.Action, d.Reason = "処理中", "既存注文の約定待ち"
		for _, p := range b.lots {
			if p.Quantity > 0 {
				d.Action, d.Reason = "保有継続", "同時一建玉を維持"
				break
			}
		}
	} else if len(pool) > 0 && !quality {
		d.Action, d.Reason = "判定不能", "直前Source・正常気配の当時性が不成立"
		context.RequiredUnknown = true
	}
	for i, row := range pool {
		r := row.Reference
		seen := b.seen[r.ID]
		passed := c0.Allowed && c0.Side == r.Side
		check := &SourceCheck{Rank: i + 1, Seen: seen, C0Passed: passed, RealEntryStage: "初参加候補"}
		candidate := GridCandidate{ReferenceID: r.ID, SourceQuantity: r.Quantity, Side: r.Side, Role: r.Kind, SourceCheck: check}
		switch {
		case r.Closing:
			candidate.Reason = "参照返済予約あり"
		case seen:
			candidate.Reason = "同じ参照HoldIDへ再参加しない"
		case occupied:
			candidate.Reason = "実保有又は注文で占有"
		case !quality:
			candidate.Reason = "Source又は気配品質が未知"
			check.RequiredUnknown = true
		case b.sourcePolicy == "SC" && !passed:
			check.RequiredUnknown = c0.RequiredUnknown
			candidate.Reason = "同方向の最終C0許可なし"
		default:
			check.Eligible = true
			if context.SelectedID != "" {
				candidate.Reason = "同枠の先行参照玉を採用済み"
				break
			}
			quantity := b.cap - b.used(r.Side)
			if quantity > r.Quantity {
				quantity = r.Quantity
			}
			if quantity <= 0 {
				candidate.Reason = "片側空き数量なし"
				break
			}
			distance := 125.0
			var atr *float64
			if tech.ATRKnown && actualFinite(tech.ATR3) && tech.ATR3 >= 0 {
				atr = actualPointer(tech.ATR3)
				distance = math.Min(125, math.Max(15, math.Ceil(tech.ATR3/5)*5))
			}
			binding := &SourceBinding{Policy: b.sourcePolicy, ReadLot: cloneSourceLot(row), SnapshotMethod: snapshot.Method, SnapshotAt: snapshot.At, SnapshotIndex: snapshot.SourceIndex, SnapshotStarted: snapshot.Started, Rank: i + 1, RequestedQuantity: quantity, ReferenceKind: r.Kind, C0Used: b.sourcePolicy == "SC", C0Allowed: c0.Allowed, C0RequiredUnknown: c0.RequiredUnknown, C0Side: c0.Side, C0Role: c0.Role, C0Reason: c0.Reason}
			hold := HoldAnchor{Kind: HoldKind, RuleVersion: HoldRuleVersion, Tick: HoldTick, Reason: sourceHoldUnusedReason}
			orderAnchor := anchor
			if b.stop == "S2" {
				orderAnchor = fixed[r.ID]
			}
			o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "entry", ReferenceID: r.ID, PositionID: fmt.Sprintf("%s_%s_P%06d", b.session, b.mode, len(b.seen)+1), Side: r.Side, Quantity: quantity, Remaining: quantity, RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: "FAR参照の初参加要求", Status: "pending", Source: r, Role: r.Kind, ATR: atr, D: distance, StructureAnchor: orderAnchor, HoldAnchor: hold, SourceEntry: binding, RealEntryStage: "初参加要求"}
			b.orders = append(b.orders, o)
			b.seen[r.ID] = true
			check.Selected = true
			candidate.RequestedQuantity = quantity
			candidate.Reason = "参照現在量以内の初参加要求"
			context.SelectedID = r.ID
			d.Action, d.Reason = "新規要求", "15分定時の参照玉を変数量で初参加"
		}
		check.Reason = candidate.Reason
		context.RequiredUnknown = context.RequiredUnknown || check.RequiredUnknown
		d.Candidates = append(d.Candidates, candidate)
	}
	if d.Action == "待ち" && context.RequiredUnknown {
		d.Action, d.Reason = "判定不能", "必要な最終C0許可が未知"
	}
	context.SeenAfterCount = len(b.seen)
	b.decisions = append(b.decisions, d)
	return nil
}

// applyCloseAtは通知時刻を保ち、旧比率を未約定新規と実未予約残量へ一度だけ適用します。
//
// 引数: c(ReferenceClose)、at(float64)、q(Quote)、origin(string)は通知・要求時計・最新気配・quote/timerです。
// 返り値: errorは不正通知又はID重複です。Source会計では0作用も台帳へ残します。
func (b *Book) applyCloseAt(c ReferenceClose, at float64, q Quote, origin string) error {
	if c.ID == "" || c.ReferenceID == "" || c.Before <= 0 || c.Quantity <= 0 || c.Quantity > c.Before {
		return fmt.Errorf("参照返済通知が不正")
	}
	if b.sourcePolicy != "" && c.Before > 100 {
		return fmt.Errorf("Source通知の元玉残量が100micro上限を超えています")
	}
	if b.closeSeen[c.ID] {
		return fmt.Errorf("参照返済通知IDの重複:%s", c.ID)
	}
	if !actualFinite(at) || !actualFinite(q.Time) || q.Time > at || origin != "quote" && origin != "timer" {
		return fmt.Errorf("参照通知の要求時計又は出典が不正")
	}
	b.closeSeen[c.ID] = true
	effect := SourceEffect{ID: c.ID, ReferenceID: c.ReferenceID, At: at, QuoteTime: q.Time, QuoteIndex: q.Index, QuoteLine: q.Line, Origin: origin, Before: c.Before, Quantity: c.Quantity, Reason: c.Reason, OrdersBeforeCount: len(b.orders)}
	for _, o := range b.orders {
		if o.Kind == "entry" && o.ReferenceID == c.ReferenceID && o.Remaining > 0 {
			effect.PendingBefore += o.Remaining
			n := o.Remaining
			if c.Quantity < c.Before {
				n = n * c.Quantity / c.Before
			}
			b.cancelEntry(o, n)
			effect.Cancelled += n
		}
	}
	if p := b.lots[c.ReferenceID]; p != nil {
		effect.UnreservedBefore = p.Quantity - p.ReservedExit
		if effect.UnreservedBefore > 0 {
			n := effect.UnreservedBefore
			if c.Quantity < c.Before {
				n = n * c.Quantity / c.Before
			}
			before := len(b.orders)
			b.requestExit(p, n, at, q, "参照返済:"+c.Reason)
			if len(b.orders) > before {
				effect.ExitRequested = b.orders[len(b.orders)-1].Quantity
				effect.ExitOrderID = b.orders[len(b.orders)-1].ID
			}
		}
		effect.UnreservedAfter = p.Quantity - p.ReservedExit
	}
	effect.OrdersAfterCount = len(b.orders)
	if b.sourcePolicy != "" {
		b.sourceEffects = append(b.sourceEffects, effect)
	}
	return nil
}

// OnReferenceはtimerのSource通知だけを配送し、fill・last・通常観測を進めません。
//
// 引数: at(float64)、last(Quote)、closes([]ReferenceClose)はtimer時計・最後の実原行・当回通知です。
// 返り値: errorはSource会計以外・時計・古い気配の偽装・重複通知です。
func (b *Book) OnReference(at float64, last Quote, closes []ReferenceClose) error {
	if b.sourcePolicy == "" || !actualFinite(at) || !actualFinite(last.Time) || last.Time > at {
		return fmt.Errorf("timer参照配送の会計又は時計が不正")
	}
	if b.haveQuote && last != b.last {
		return fmt.Errorf("timer参照配送の気配が実lastと不一致")
	}
	for _, c := range closes {
		if err := b.applyCloseAt(c, at, last, "timer"); err != nil {
			return err
		}
	}
	return nil
}
