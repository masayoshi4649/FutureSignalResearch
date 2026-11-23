package far80

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"sort"
	"strconv"
	"time"
)

const actualFee = 61.0

// ActualLot は参照玉とは独立した実所有と保護の記録です。
type ActualLot struct {
	ID              string   `json:"id"`
	ReferenceID     string   `json:"reference_id"`
	Method          string   `json:"method"`
	Owner           string   `json:"owner"`
	SourceID        string   `json:"source_id"`
	Parent          string   `json:"parent"`
	Role            string   `json:"role"`
	Side            int      `json:"side"`
	Quantity        int      `json:"quantity"`
	InitialQuantity int      `json:"initial_quantity"`
	ReservedExit    int      `json:"reserved_exit"`
	EntryPrice      float64  `json:"entry_price"`
	EntryTime       float64  `json:"entry_time"`
	EntryIndex      int64    `json:"entry_index"`
	EntryLine       int64    `json:"entry_line"`
	EntryATR        *float64 `json:"entry_atr"`
	D               float64  `json:"d"`
	BestGain        float64  `json:"best_gain"`
	WorstGain       float64  `json:"worst_gain"`
	Floor           float64  `json:"floor"`
	Flag            bool     `json:"flag"`
	FlagTime        *float64 `json:"flag_time"`
	FlagIndex       int64    `json:"flag_index"`
	FlagMark        *float64 `json:"flag_mark"`
	FlagNetPerUnit  *float64 `json:"flag_net_per_unit"`
	FlagFloor       *float64 `json:"flag_floor"`
	RequestTime     *float64 `json:"request_time"`
	RequestMark     *float64 `json:"request_mark"`
	RequestFloor    *float64 `json:"request_floor"`
	NetPnL          float64  `json:"net_pnl"`
	ClosedQuantity  int      `json:"closed_quantity"`
}

// ActualOrder は一度要求した数量と約定・取消数量を分ける注文記録です。
type ActualOrder struct {
	ID                string       `json:"id"`
	Kind              string       `json:"kind"`
	ReferenceID       string       `json:"reference_id"`
	PositionID        string       `json:"position_id"`
	Side              int          `json:"side"`
	Quantity          int          `json:"quantity"`
	Remaining         int          `json:"remaining"`
	FilledQuantity    int          `json:"filled_quantity"`
	CancelledQuantity int          `json:"cancelled_quantity"`
	RequestTime       float64      `json:"request_time"`
	RequestIndex      int64        `json:"request_index"`
	RequestLine       int64        `json:"request_line"`
	FillTime          *float64     `json:"fill_time"`
	FillPrice         *float64     `json:"fill_price"`
	FillLine          int64        `json:"fill_line"`
	Reason            string       `json:"reason"`
	Status            string       `json:"status"`
	Mark              *float64     `json:"mark"`
	Gain              *float64     `json:"gain"`
	Floor             *float64     `json:"floor"`
	NetPerUnit        *float64     `json:"net_per_unit"`
	Flagged           bool         `json:"flagged"`
	Source            ReferenceLot `json:"source"`
	Role              string       `json:"role"`
	ATR               *float64     `json:"atr"`
	D                 float64      `json:"d"`
}

// GridCandidate は定時に参照玉を見た結果で、実新規との違いを残します。
type GridCandidate struct {
	ReferenceID       string `json:"reference_id"`
	SourceQuantity    int    `json:"source_quantity"`
	RequestedQuantity int    `json:"requested_quantity"`
	Side              int    `json:"side"`
	Role              string `json:"role"`
	Reason            string `json:"reason"`
}

// ActualDecision は全定時の分類と候補別の不採用理由です。
type ActualDecision struct {
	At         float64         `json:"at"`
	QuoteTime  float64         `json:"quote_time"`
	QuoteIndex int64           `json:"quote_index"`
	Action     string          `json:"action"`
	Reason     string          `json:"reason"`
	Candidates []GridCandidate `json:"candidates"`
}

// ClosedLot は返済約定片単位の厳密な費用と保護診断です。
type ClosedLot struct {
	PositionID              string   `json:"position_id"`
	ReferenceID             string   `json:"reference_id"`
	Side                    int      `json:"side"`
	Quantity                int      `json:"quantity"`
	EntryPrice              float64  `json:"entry_price"`
	ExitPrice               float64  `json:"exit_price"`
	EntryTime               float64  `json:"entry_time"`
	ExitTime                float64  `json:"exit_time"`
	ExitLine                int64    `json:"exit_line"`
	Reason                  string   `json:"reason"`
	GrossPnL                float64  `json:"gross_pnl"`
	Commission              float64  `json:"commission"`
	Slippage                float64  `json:"slippage"`
	PnL0                    float64  `json:"pnl0"`
	PnL5                    float64  `json:"pnl5"`
	PnL10                   float64  `json:"pnl10"`
	Flag                    bool     `json:"flag"`
	FlagTime                *float64 `json:"flag_time"`
	FlagMark                *float64 `json:"flag_mark"`
	FlagFloor               *float64 `json:"flag_floor"`
	FlagNetPerUnit          *float64 `json:"flag_net_per_unit"`
	RequestTime             float64  `json:"request_time"`
	RequestMark             *float64 `json:"request_mark"`
	RequestFloor            *float64 `json:"request_floor"`
	RequestNetPerUnit       *float64 `json:"request_net_per_unit"`
	RequestToFillAdverseYen *float64 `json:"request_to_fill_adverse_yen"`
	FloorJump               bool     `json:"floor_jump"`
	CostLoss                bool     `json:"cost_loss"`
	NominalFlat             bool     `json:"nominal_flat"`
}

// BookMetrics は実会計だけの観測集計です。未観測の現在評価額はnilです。
type BookMetrics struct {
	CashYen                      float64  `json:"cash_yen"`
	NetPnLYen                    float64  `json:"net_pnl_yen"`
	GrossPnLYen                  float64  `json:"gross_pnl_yen"`
	CommissionYen                float64  `json:"commission_yen"`
	SlippageYen                  float64  `json:"slippage_yen"`
	TotalCostYen                 float64  `json:"total_cost_yen"`
	EquityYen                    *float64 `json:"equity_yen"`
	FloatingYen                  *float64 `json:"floating_yen"`
	EquityPeakYen                float64  `json:"equity_peak_yen"`
	MinEquityYen                 float64  `json:"min_equity_yen"`
	MaxDrawdownYen               float64  `json:"max_drawdown_yen"`
	WorstFloatingYen             float64  `json:"worst_floating_yen"`
	EntryQuantity                int      `json:"entry_quantity"`
	ExitQuantity                 int      `json:"exit_quantity"`
	OpenQuantity                 int      `json:"open_quantity"`
	PendingEntryQuantity         int      `json:"pending_entry_quantity"`
	ReservedExitQuantity         int      `json:"reserved_exit_quantity"`
	ClosedPieces                 int      `json:"closed_pieces"`
	WinningPieces                int      `json:"winning_pieces"`
	LosingPieces                 int      `json:"losing_pieces"`
	FlatPieces                   int      `json:"flat_pieces"`
	ClosedLots                   int      `json:"closed_lots"`
	WinningLots                  int      `json:"winning_lots"`
	LosingLots                   int      `json:"losing_lots"`
	FlatLots                     int      `json:"flat_lots"`
	ProfitFlags                  int      `json:"profit_flags"`
	FlagAfterLossPieces          int      `json:"flag_after_loss_pieces"`
	RequestBeforeFloorViolations int      `json:"request_before_floor_violations"`
	MarkKnown                    bool     `json:"mark_known"`
	UnpricedExposureQuotes       int      `json:"unpriced_exposure_quotes"`
}

// BookResult は巨大な原行軌跡を含まない実所有の最小保存結果です。
type BookResult struct {
	Session          string           `json:"session"`
	Mode             string           `json:"mode"`
	SideCap          int              `json:"side_cap"`
	FillDelaySeconds float64          `json:"fill_delay_seconds"`
	Trades           []Trade          `json:"trades"`
	Orders           []ActualOrder    `json:"orders"`
	Decisions        []ActualDecision `json:"decisions"`
	Closed           []ClosedLot      `json:"closed"`
	Positions        []ActualLot      `json:"positions"`
	Lots             []ActualLot      `json:"lots"`
	PendingEntries   []ActualOrder    `json:"pending_entries"`
	QuantityBySide   map[int]int      `json:"quantity_by_side"`
	Metrics          BookMetrics      `json:"metrics"`
	Unresolved       bool             `json:"unresolved"`
	Warnings         []string         `json:"warnings"`
}

// Book は参照玉のIDと実所有を分離し、次正常原行約定を管理します。
type Book struct {
	session, mode  string
	cap            int
	delay          float64
	seen           map[string]bool
	lots           map[string]*ActualLot
	orders         []*ActualOrder
	trades         []Trade
	decisions      []ActualDecision
	closed         []ClosedLot
	last           Quote
	haveQuote      bool
	lastGrid       float64
	haveGrid       bool
	lastBar3       float64
	lastNormalTime float64
	haveNormal     bool
	closeSeen      map[string]bool
	metrics        BookMetrics
	warnings       []string
}

// ----------------------------------------

// NewBook は実会計を初期化し、政策と片側上限を検査します。
//
// 引数: sessionIDとmodeはstring、capはintで片側1..100枚です。
// 返り値: *Bookは独立実会計、errorは不正条件です。
func NewBook(sessionID, mode string, cap int) (*Book, error) {
	if sessionID == "" || (mode != "F0" && mode != "P1" && mode != "T1") || cap < 1 || cap > 100 {
		return nil, fmt.Errorf("場・政策又は片側上限が不正")
	}
	return &Book{session: sessionID, mode: mode, cap: cap, seen: map[string]bool{}, lots: map[string]*ActualLot{}, closeSeen: map[string]bool{}}, nil
}

// SetFillDelay は発注前に限り価格時計の約定遅延を指定します。
//
// 引数: secondsはfloat64で0以上の有限秒です。
// 返り値: errorは不正又は発注後の設定変更です。
func (b *Book) SetFillDelay(seconds float64) error {
	if !actualFinite(seconds) || seconds < 0 || len(b.orders) != 0 {
		return fmt.Errorf("約定遅延は発注前に有限非負で固定")
	}
	b.delay = seconds
	return nil
}

// ----------------------------------------

// actualFinite は真の有限実数を判定します。
//
// 引数: xはfloat64の値です。
// 返り値: boolはNaN又は無限大でなければ真です。
func actualFinite(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }

// actualNormal は実約定に利用できる当時の正常BBOを判定します。
//
// 引数: qはQuoteです。
// 返り値: boolは有限正bid<askかつ元Validが真の場合です。
func actualNormal(q Quote) bool {
	return q.Valid && actualFinite(q.Time) && actualFinite(q.Bid) && actualFinite(q.Ask) && q.Bid > 0 && q.Bid < q.Ask
}

// actualPointer は保存用の独立した数値ポインタを作ります。
//
// 引数: xはfloat64の保存値です。
// 返り値: *float64は入力変数と独立した値です。
func actualPointer(x float64) *float64 { return &x }

// actualMark は実方向の返済側気配を返します。
//
// 引数: qはQuote、sideはintの±1です。
// 返り値: float64は買いのbid又は売りのaskです。
func actualMark(q Quote, side int) float64 {
	if side == 1 {
		return q.Bid
	}
	return q.Ask
}

// actualGrossPerUnit は十進表示の価格差を1枚の実方向粗利益へ写します。
//
// 引数: sideはint、markとentryはfloat64の有限価格です。
// 返り値: float64は円粗利益です。整数価格は高速経路、端数は十進有理数で計算します。
func actualGrossPerUnit(side int, mark, entry float64) float64 {
	if mark == math.Trunc(mark) && entry == math.Trunc(entry) {
		return float64(side) * (mark - entry) * 10
	}
	a, _ := new(big.Rat).SetString(strconv.FormatFloat(mark, 'f', -1, 64))
	e, _ := new(big.Rat).SetString(strconv.FormatFloat(entry, 'f', -1, 64))
	v := new(big.Rat).Sub(a, e)
	v.Mul(v, big.NewRat(int64(side)*10, 1))
	out, _ := v.Float64()
	return out
}

// orderedLots は参照ID順で実所有を列挙します。
//
// 引数: なし。
// 返り値: []*ActualLotは数量0の完結玉も含む決定的順です。
func (b *Book) orderedLots() []*ActualLot {
	keys := make([]string, 0, len(b.lots))
	for id := range b.lots {
		keys = append(keys, id)
	}
	sort.Strings(keys)
	out := make([]*ActualLot, 0, len(keys))
	for _, id := range keys {
		out = append(out, b.lots[id])
	}
	return out
}

// used は返済予約を控除せず、実所有と新規待機を片側余力へ算入します。
//
// 引数: sideはintの実方向です。
// 返り値: intは当該方向の消費枚数です。
func (b *Book) used(side int) int {
	n := 0
	for _, p := range b.lots {
		if p.Side == side {
			n += p.Quantity
		}
	}
	for _, o := range b.orders {
		if o.Kind == "entry" && o.Side == side {
			n += o.Remaining
		}
	}
	return n
}

// warn は品質注意を重複させずに保存します。
//
// 引数: textはstringの注意理由です。
// 返り値: なし。
func (b *Book) warn(text string) {
	for _, s := range b.warnings {
		if s == text {
			return
		}
	}
	b.warnings = append(b.warnings, text)
}

// ----------------------------------------

// observe は利益の初回strict正と実保有中の有利・不利幅を測ります。
//
// 引数: pは*ActualLot、qは正常なQuoteです。
// 返り値: float64は現在の実方向幅ptです。
func (b *Book) observe(p *ActualLot, q Quote) float64 {
	m := actualMark(q, p.Side)
	gross := actualGrossPerUnit(p.Side, m, p.EntryPrice)
	gain := gross / 10
	p.BestGain = math.Max(p.BestGain, gain)
	p.WorstGain = math.Min(p.WorstGain, gain)
	if !p.Flag && gross-122 > 0 {
		p.Flag = true
		p.FlagTime = actualPointer(q.Time)
		p.FlagIndex = q.Index
		p.FlagMark = actualPointer(m)
		p.FlagNetPerUnit = actualPointer(gross - 122)
		p.FlagFloor = actualPointer(p.Floor)
		b.metrics.ProfitFlags++
	}
	return gain
}

// requestExit は未予約残量だけを返済要求し、既存注文を変更しません。
//
// 引数: pは*ActualLot、quantityはint、atはfloat64、qはQuote、reasonはstringです。
// 返り値: なし。現在気配不明なら価格根拠をnilで残します。
func (b *Book) requestExit(p *ActualLot, quantity int, at float64, q Quote, reason string) {
	available := p.Quantity - p.ReservedExit
	if quantity > available {
		quantity = available
	}
	if quantity <= 0 {
		return
	}
	o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "exit", ReferenceID: p.ReferenceID, PositionID: p.ID, Side: p.Side, Quantity: quantity, Remaining: quantity, RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: reason, Status: "pending", Flagged: p.Flag, Floor: actualPointer(p.Floor)}
	if actualNormal(q) && q.Time <= at {
		m := actualMark(q, p.Side)
		gross := actualGrossPerUnit(p.Side, m, p.EntryPrice)
		g := gross / 10
		o.Mark = actualPointer(m)
		o.Gain = actualPointer(g)
		o.NetPerUnit = actualPointer(gross - 122)
	}
	if p.RequestTime == nil {
		p.RequestTime = actualPointer(at)
		p.RequestMark = o.Mark
		p.RequestFloor = actualPointer(p.Floor)
	}
	p.ReservedExit += quantity
	b.orders = append(b.orders, o)
}

// cancelEntry は未約定新規だけを減らし、参照IDの再入場禁止を維持します。
//
// 引数: oは*ActualOrder、quantityはintの取消枚数です。
// 返り値: なし。返済注文は取消しません。
func (b *Book) cancelEntry(o *ActualOrder, quantity int) {
	if o.Kind != "entry" || o.Remaining == 0 {
		return
	}
	if quantity > o.Remaining {
		quantity = o.Remaining
	}
	if quantity <= 0 {
		return
	}
	o.Remaining -= quantity
	o.CancelledQuantity += quantity
	if o.Remaining == 0 {
		o.Status = "cancelled"
	}
}

// applyClose は参照の未通知残量比率を実未予約数量へ適用します。
//
// 引数: cはReferenceClose、qは通知を受けたQuoteです。
// 返り値: errorは不正数量又は重複通知です。
func (b *Book) applyClose(c ReferenceClose, q Quote) error {
	if c.ID == "" || c.ReferenceID == "" || c.Before <= 0 || c.Quantity <= 0 || c.Quantity > c.Before {
		return fmt.Errorf("参照返済通知が不正")
	}
	if b.closeSeen[c.ID] {
		return fmt.Errorf("参照返済通知IDの重複:%s", c.ID)
	}
	b.closeSeen[c.ID] = true
	for _, o := range b.orders {
		if o.Kind == "entry" && o.ReferenceID == c.ReferenceID && o.Remaining > 0 {
			n := o.Remaining
			if c.Quantity < c.Before {
				n = n * c.Quantity / c.Before
			}
			b.cancelEntry(o, n)
		}
	}
	if p := b.lots[c.ReferenceID]; p != nil && p.Quantity > p.ReservedExit {
		n := p.Quantity - p.ReservedExit
		if c.Quantity < c.Before {
			n = n * c.Quantity / c.Before
		}
		b.requestExit(p, n, q.Time, q, "参照返済:"+c.Reason)
	}
	return nil
}

// ----------------------------------------

// fill は前原行以前の待機注文だけを現在正常気配で全量約定します。
//
// 引数: qは正常なQuoteです。
// 返り値: errorは数量予約の内部不整合です。
func (b *Book) fill(q Quote) error {
	for _, o := range b.orders {
		if o.Remaining <= 0 || q.Index <= o.RequestIndex || q.Time < o.RequestTime+b.delay {
			continue
		}
		n := o.Remaining
		price := actualMark(q, -o.Side)
		typ := "LongN"
		if o.Side < 0 {
			typ = "ShortN"
		}
		if o.Kind == "entry" {
			if b.lots[o.ReferenceID] != nil {
				return fmt.Errorf("参照IDを再新規した")
			}
			p := &ActualLot{ID: o.PositionID, ReferenceID: o.ReferenceID, Method: o.Source.Method, Owner: o.Source.Owner, SourceID: o.Source.SourceID, Parent: o.Source.Parent, Role: o.Role, Side: o.Side, Quantity: n, InitialQuantity: n, EntryPrice: price, EntryTime: q.Time, EntryIndex: q.Index, EntryLine: q.Line, EntryATR: o.ATR, D: o.D, Floor: -125}
			b.lots[o.ReferenceID] = p
			b.metrics.EntryQuantity += n
			b.metrics.CashYen -= actualFee * float64(n)
		} else {
			p := b.lots[o.ReferenceID]
			if p == nil || n > p.Quantity || n > p.ReservedExit {
				return fmt.Errorf("返済予約数量の不整合")
			}
			b.observe(p, q)
			price = actualMark(q, o.Side)
			typ = "LongR"
			if o.Side < 0 {
				typ = "ShortR"
			}
			gross := actualGrossPerUnit(p.Side, price, p.EntryPrice) * float64(n)
			net := gross - 122*float64(n)
			closed := ClosedLot{PositionID: p.ID, ReferenceID: p.ReferenceID, Side: p.Side, Quantity: n, EntryPrice: p.EntryPrice, ExitPrice: price, EntryTime: p.EntryTime, ExitTime: q.Time, ExitLine: q.Line, Reason: o.Reason, GrossPnL: gross, Commission: 22 * float64(n), Slippage: 100 * float64(n), PnL0: gross - 22*float64(n), PnL5: net, PnL10: gross - 222*float64(n), Flag: p.Flag, FlagTime: p.FlagTime, FlagMark: p.FlagMark, FlagFloor: p.FlagFloor, FlagNetPerUnit: p.FlagNetPerUnit, RequestTime: o.RequestTime, RequestMark: o.Mark, RequestFloor: o.Floor, RequestNetPerUnit: o.NetPerUnit, CostLoss: gross > 0 && net < 0, NominalFlat: price == p.EntryPrice}
			if o.Mark != nil {
				adverse := actualGrossPerUnit(p.Side, *o.Mark, price) * float64(n)
				closed.RequestToFillAdverseYen = actualPointer(adverse)
			}
			if o.Gain != nil && o.Floor != nil {
				closed.FloorJump = *o.Gain < *o.Floor
			}
			b.closed = append(b.closed, closed)
			p.Quantity -= n
			p.ReservedExit -= n
			p.ClosedQuantity += n
			p.NetPnL += net
			b.metrics.ExitQuantity += n
			b.metrics.GrossPnLYen += gross
			b.metrics.NetPnLYen += net
			b.metrics.CashYen += gross - actualFee*float64(n)
			b.metrics.ClosedPieces++
			if net > 0 {
				b.metrics.WinningPieces++
			} else if net < 0 {
				b.metrics.LosingPieces++
			} else {
				b.metrics.FlatPieces++
			}
			if p.Flag && net < 0 {
				b.metrics.FlagAfterLossPieces++
			}
		}
		b.metrics.CommissionYen += 11 * float64(n)
		b.metrics.SlippageYen += 50 * float64(n)
		b.metrics.TotalCostYen += actualFee * float64(n)
		o.Remaining = 0
		o.FilledQuantity += n
		o.Status = "filled"
		o.FillTime = actualPointer(q.Time)
		o.FillPrice = actualPointer(price)
		o.FillLine = q.Line
		seconds, fraction := math.Modf(q.Time)
		stamp := time.Unix(int64(seconds), int64(math.Round(fraction*1e9))).In(time.FixedZone("日本標準時", 9*3600)).Format(time.RFC3339Nano)
		b.trades = append(b.trades, Trade{ID: fmt.Sprintf("%s_%s_T%06d", b.session, b.mode, len(b.trades)+1), Timestamp: stamp, Type: typ, PositionID: o.PositionID, Price: price, Quantity: n, FeeYen: actualFee * float64(n), MethodID: b.mode, SourceLine: q.Line, Reason: o.Reason})
	}
	return nil
}

// mark は実所有の費用後評価額と観測された最大DDを更新します。
//
// 引数: qはQuoteで、無効時の現在評価は未知にします。
// 返り値: なし。未観測区間の最低値を0で補いません。
func (b *Book) mark(q Quote) {
	b.metrics.MarkKnown = actualNormal(q)
	b.metrics.EquityYen = nil
	b.metrics.FloatingYen = nil
	if !actualNormal(q) {
		for _, p := range b.lots {
			if p.Quantity > 0 {
				b.metrics.UnpricedExposureQuotes++
				break
			}
		}
		return
	}
	floating := 0.0
	entryCost := 0.0
	for _, p := range b.lots {
		if p.Quantity > 0 {
			floating += (actualGrossPerUnit(p.Side, actualMark(q, p.Side), p.EntryPrice) - 122) * float64(p.Quantity)
			entryCost += 61 * float64(p.Quantity)
		}
	}
	equity := b.metrics.CashYen + floating + entryCost
	b.metrics.FloatingYen = actualPointer(floating)
	b.metrics.EquityYen = actualPointer(equity)
	b.metrics.WorstFloatingYen = math.Min(b.metrics.WorstFloatingYen, floating)
	b.metrics.EquityPeakYen = math.Max(b.metrics.EquityPeakYen, equity)
	b.metrics.MinEquityYen = math.Min(b.metrics.MinEquityYen, equity)
	b.metrics.MaxDrawdownYen = math.Max(b.metrics.MaxDrawdownYen, b.metrics.EquityPeakYen-equity)
}

// ----------------------------------------

// OnQuote は次原行約定・参照通知・連続保護を順番どおり処理します。
//
// 引数: qはQuote、refはReferenceFrame、techはTechnicalViewです。
// 返り値: errorは時計・通知・数量の不正です。不正BBOも通知を受領します。
func (b *Book) OnQuote(q Quote, ref ReferenceFrame, tech TechnicalView) error {
	if !actualFinite(q.Time) || q.Index < 0 || q.Line < 0 || (b.haveQuote && (q.Index <= b.last.Index || q.Time < b.last.Time)) {
		return fmt.Errorf("実気配の時計又は原行順が不正")
	}
	if actualNormal(q) && b.haveNormal && q.Time-b.lastNormalTime > 300 {
		for _, p := range b.lots {
			if p.Quantity > 0 {
				b.warn("実所有中の正常BBO間隔300秒超")
				break
			}
		}
	}
	b.last = q
	b.haveQuote = true
	if actualNormal(q) {
		b.lastNormalTime = q.Time
		b.haveNormal = true
		b.mark(q)
		if err := b.fill(q); err != nil {
			return err
		}
	}
	for _, c := range ref.Closes {
		if err := b.applyClose(c, q); err != nil {
			return err
		}
	}
	newBar := actualFinite(tech.Bar3End) && tech.Bar3End > b.lastBar3
	for _, p := range b.orderedLots() {
		if p.Quantity <= 0 {
			continue
		}
		if actualNormal(q) {
			gain := b.observe(p, q)
			if b.mode != "F0" && p.Flag && p.Quantity > p.ReservedExit {
				p.Floor = math.Max(p.Floor, math.Max(20, p.BestGain-p.D))
				if p.FlagIndex == q.Index {
					p.FlagFloor = actualPointer(p.Floor)
				}
			}
			if gain <= -125 {
				b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, "共通125pt保護")
			} else if b.mode != "F0" && p.Flag && gain <= p.Floor {
				b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, "費用床・ATR追尾")
			}
		}
		if b.mode != "F0" && newBar && tech.Failed(p.Side) {
			b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, "確定3分技法失敗")
		}
	}
	if newBar {
		b.lastBar3 = tech.Bar3End
	}
	b.mark(q)
	return nil
}

// OnGrid は直前既知気配を用い、15分呼出し時だけ実新規を予約します。
//
// 引数: atはfloat64の予定時計、qは直前Quote、refはReferenceFrame、techはTechnicalViewです。
// 返り値: errorは時計・参照玉の不正です。鮮度不足は判定不能として保存します。
func (b *Book) OnGrid(at float64, q Quote, ref ReferenceFrame, tech TechnicalView) error {
	if !actualFinite(at) || !actualFinite(q.Time) || (b.haveGrid && at <= b.lastGrid) {
		return fmt.Errorf("定時時計は有限の昇順が必要")
	}
	b.haveGrid = true
	b.lastGrid = at
	d := ActualDecision{At: at, QuoteTime: q.Time, QuoteIndex: q.Index, Action: "待ち", Reason: "有効な新規候補なし", Candidates: []GridCandidate{}}
	if !actualNormal(q) || q.Time > at || at-q.Time > 15 || !b.haveQuote || q.Index != b.last.Index || q.Time != b.last.Time || q.Line != b.last.Line || q.Bid != b.last.Bid || q.Ask != b.last.Ask {
		d.Action = "判定不能"
		d.Reason = "直前正常気配の鮮度又は当時性が不成立"
		b.decisions = append(b.decisions, d)
		return nil
	}
	items := append([]ReferenceLot(nil), ref.Lots...)
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].At != items[j].At {
			return items[i].At < items[j].At
		}
		return items[i].ID < items[j].ID
	})
	frameIDs := map[string]bool{}
	for _, src := range items {
		if src.ID == "" || frameIDs[src.ID] || (src.Side != 1 && src.Side != -1) || src.Quantity <= 0 || !actualFinite(src.At) || src.At > at || !actualFinite(src.Entry) {
			return fmt.Errorf("参照実玉のID・方向・数量が不正")
		}
		frameIDs[src.ID] = true
		c := GridCandidate{ReferenceID: src.ID, SourceQuantity: src.Quantity, Side: src.Side, Role: src.Kind}
		switch {
		case src.Closing:
			c.Reason = "参照返済中"
		case b.seen[src.ID]:
			c.Reason = "同じ参照IDへ再入場しない"
		default:
			allowed := true
			role := src.Kind
			reason := "FAR参照有効玉"
			if b.mode == "T1" {
				allowed, role, reason = tech.Entry(src.Side)
			}
			c.Role = role
			c.Reason = reason
			if allowed {
				n := b.cap - b.used(src.Side)
				if n > src.Quantity {
					n = src.Quantity
				}
				if n <= 0 {
					c.Reason = "片側余力なし"
				} else {
					distance := 125.0
					var atr *float64
					if tech.ATRKnown && actualFinite(tech.ATR3) && tech.ATR3 >= 0 {
						atr = actualPointer(tech.ATR3)
						distance = math.Min(125, math.Max(15, math.Ceil(tech.ATR3/5)*5))
					}
					o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "entry", ReferenceID: src.ID, PositionID: fmt.Sprintf("%s_%s_P%06d", b.session, b.mode, len(b.seen)+1), Side: src.Side, Quantity: n, Remaining: n, RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: reason, Status: "pending", Source: src, Role: role, ATR: atr, D: distance}
					b.orders = append(b.orders, o)
					b.seen[src.ID] = true
					c.RequestedQuantity = n
					d.Action = "新規要求"
					d.Reason = "15分定時の参照玉を実新規"
				}
			}
		}
		d.Candidates = append(d.Candidates, c)
	}
	if d.Action == "待ち" {
		for _, p := range b.lots {
			if p.Quantity > 0 {
				d.Action = "保有継続"
				d.Reason = "実建玉を保有"
				break
			}
		}
		for _, o := range b.orders {
			if o.Remaining > 0 {
				d.Action = "処理中"
				d.Reason = "既存注文の約定待ち"
				break
			}
		}
	}
	b.decisions = append(b.decisions, d)
	return nil
}

// Force は未約定新規を取消し、既存実玉の未予約分だけ返済要求します。
//
// 引数: atはfloat64の要求時計、qはQuote、reasonはstringの場末又は境界理由です。
// 返り値: errorは不正時計です。同じ行で架空約定しません。
func (b *Book) Force(at float64, q Quote, reason string) error {
	if !actualFinite(at) || !actualFinite(q.Time) || q.Time > at || reason == "" {
		return fmt.Errorf("強制返済の時計又は理由が不正")
	}
	for _, o := range b.orders {
		if o.Kind == "entry" {
			b.cancelEntry(o, o.Remaining)
		}
	}
	for _, p := range b.orderedLots() {
		b.requestExit(p, p.Quantity-p.ReservedExit, at, q, reason)
	}
	return nil
}

// Result は内部状態を共有しない保存用の実会計結果を返します。
//
// 引数: なし。
// 返り値: BookResultは約定・注文・定時・完結・残状態と観測集計です。
func (b *Book) Result() BookResult {
	r := BookResult{Session: b.session, Mode: b.mode, SideCap: b.cap, FillDelaySeconds: b.delay, Trades: append([]Trade{}, b.trades...), Decisions: append([]ActualDecision{}, b.decisions...), Closed: append([]ClosedLot{}, b.closed...), Positions: []ActualLot{}, Lots: []ActualLot{}, Orders: []ActualOrder{}, PendingEntries: []ActualOrder{}, QuantityBySide: map[int]int{-1: 0, 1: 0}, Metrics: b.metrics, Warnings: append([]string{}, b.warnings...)}
	for _, p := range b.orderedLots() {
		r.Lots = append(r.Lots, *p)
		if p.Quantity > 0 {
			r.Positions = append(r.Positions, *p)
			r.QuantityBySide[p.Side] += p.Quantity
			r.Metrics.OpenQuantity += p.Quantity
			r.Metrics.ReservedExitQuantity += p.ReservedExit
		} else if p.ClosedQuantity > 0 {
			r.Metrics.ClosedLots++
			if p.NetPnL > 0 {
				r.Metrics.WinningLots++
			} else if p.NetPnL < 0 {
				r.Metrics.LosingLots++
			} else {
				r.Metrics.FlatLots++
			}
		}
	}
	for _, o := range b.orders {
		r.Orders = append(r.Orders, *o)
		if o.Remaining > 0 {
			r.Unresolved = true
			if o.Kind == "entry" {
				r.PendingEntries = append(r.PendingEntries, *o)
				r.Metrics.PendingEntryQuantity += o.Remaining
			}
		}
	}
	if len(r.Positions) > 0 {
		r.Unresolved = true
	}
	if r.Unresolved {
		r.Warnings = append(r.Warnings, "実建玉又は注文が未解消")
	}
	encoded, err := json.Marshal(r)
	if err != nil {
		panic("実会計の保存値が不正:" + err.Error())
	}
	var copied BookResult
	if err = json.Unmarshal(encoded, &copied); err != nil {
		panic("実会計の複写に失敗:" + err.Error())
	}
	return copied
}
