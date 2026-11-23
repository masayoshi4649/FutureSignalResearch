// 91派生元: scripts/FAR利益床と収穫配分の比較/source_entry.go
// 91派生元SHA256: bf4478f979d85986d2208762371fecf78523cd93f0e6cb4aa6af7041c8ed1cd4
// 固定89は変更せず、G1対照全文と利確完了後の別event再参加を比較します。

// 89派生元: scripts/FAR参照玉と可変数量の比較/source_entry.go
// 89派生元SHA256: b9a6fd1a2e9939f8a7f42bf5f57231aaeeaeff6e42f8dda66fe5218acda8f9d0
// 固定87は変更せず、G1旧全文とG2既存分岐を別会計で比較します。

package far91

import (
	"fmt"
	"math"
	"sort"
)

const sourceHoldUnusedReason = "FAR参照入口のためC0保持帯線は未使用"

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
	if b.reentryEnabled {
		return fmt.Errorf("再参加会計は現在E1出典を伴う専用Source入口が必要です")
	}
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
			o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "entry", ReferenceID: r.ID, PositionID: fmt.Sprintf("%s_%s_P%06d", b.session, b.mode, len(b.seen)+1), Side: r.Side, Quantity: quantity, Remaining: quantity, RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: "FAR参照の初参加要求", Status: "pending", Source: r, Role: r.Kind, ATR: atr, D: distance, StructureAnchor: anchor, HoldAnchor: hold, SourceEntry: binding, RealEntryStage: "初参加要求"}
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
