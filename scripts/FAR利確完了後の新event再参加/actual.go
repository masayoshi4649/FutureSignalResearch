// 91派生元: scripts/FAR利益床と収穫配分の比較/actual.go
// 91派生元SHA256: e9e754c3ea8071b0337d1746ff511f16ea2cd58f1c45f8340f3bba274c8994ff
// 固定89は変更せず、G1対照全文と利確完了後の別event再参加を比較します。

// 89派生元: scripts/FAR参照玉と可変数量の比較/actual.go
// 89派生元SHA256: f70d370bc1f8681f3f6e32edc9f7be578386d18e47ad0a46b32509948c3443c3
// 固定87は変更せず、G1旧全文とG2既存分岐を別会計で比較します。

// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/actual.go
// 87派生元SHA256: bb965e820d5534c1f73d2dc87eeec4bd4b062022ecc2aefb6386ed089834a9e8

// 86派生元: scripts/保持帯の返済側固定否定/actual.go
// 86派生元SHA256: 4c6c19ad8d01722d27793550f0a422eb8d397c2cab0f56dafe384349f6e0aef0

package far91

// 86金融は85の全保護を保ち、その後に床と独立した両気配・短秒確認退出を追加します。
// 複合確認offの旧全文を対照とし、要求時保持帯は確認onでも固定床へ活性化しません。

// 派生元: scripts/定時の現在根拠と部分利益保護/actual.go
// 派生元SHA256: d5c851661c411577993259fdeb12f3f27bcb3ff4e8aef9a71c40369c6c21d83a
// 固定元は変更せず、構造否定と利益配分だけを追加します。

// 85派生元: scripts/構造否定と利益配分/actual.go
// 85派生元SHA256: e2937726cc93cda363cecc22b93902a008d2a60ece3ef9132d3fc423f3400c36
// 既存S0G1金融は維持し、保持帯の出典と固定否定だけを追加します。

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
	ID                      string           `json:"id"`
	ReferenceID             string           `json:"reference_id"`
	Method                  string           `json:"method"`
	Owner                   string           `json:"owner"`
	SourceID                string           `json:"source_id"`
	Parent                  string           `json:"parent"`
	Role                    string           `json:"role"`
	Side                    int              `json:"side"`
	Quantity                int              `json:"quantity"`
	InitialQuantity         int              `json:"initial_quantity"`
	ReservedExit            int              `json:"reserved_exit"`
	EntryPrice              float64          `json:"entry_price"`
	EntryTime               float64          `json:"entry_time"`
	EntryIndex              int64            `json:"entry_index"`
	EntryLine               int64            `json:"entry_line"`
	EntryATR                *float64         `json:"entry_atr"`
	D                       float64          `json:"d"`
	BestGain                float64          `json:"best_gain"`
	WorstGain               float64          `json:"worst_gain"`
	Floor                   float64          `json:"floor"`
	Flag                    bool             `json:"flag"`
	FlagTime                *float64         `json:"flag_time"`
	FlagIndex               int64            `json:"flag_index"`
	FlagMark                *float64         `json:"flag_mark"`
	FlagNetPerUnit          *float64         `json:"flag_net_per_unit"`
	FlagFloor               *float64         `json:"flag_floor"`
	RequestTime             *float64         `json:"request_time"`
	RequestMark             *float64         `json:"request_mark"`
	RequestFloor            *float64         `json:"request_floor"`
	NetPnL                  float64          `json:"net_pnl"`
	ClosedQuantity          int              `json:"closed_quantity"`
	WholeFlag               bool             `json:"whole_flag"`
	WholeFlagTime           *float64         `json:"whole_flag_time"`
	WholeFlagIndex          int64            `json:"whole_flag_index"`
	WholeFlagLine           int64            `json:"whole_flag_line"`
	WholeBestNet            float64          `json:"whole_best_net"`
	WholeWorstNet           float64          `json:"whole_worst_net"`
	HarvestOrderID          string           `json:"harvest_order_id"`
	HarvestTarget           int              `json:"harvest_target"`
	HarvestFilled           int              `json:"harvest_filled"`
	HarvestNeeded           int              `json:"harvest_needed"`
	HarvestFeasible         bool             `json:"harvest_feasible"`
	HarvestAt               *float64         `json:"harvest_at"`
	HarvestDoneAt           *float64         `json:"harvest_done_at"`
	CashFloorActive         bool             `json:"cash_floor_active"`
	CashFloor               *float64         `json:"cash_floor"`
	CashFloorAt             *float64         `json:"cash_floor_at"`
	FundingFailed           bool             `json:"funding_failed"`
	StructureAnchor         StructureAnchor  `json:"structure_anchor"`
	StructureActive         bool             `json:"structure_active"`
	StructureFloor          *float64         `json:"structure_floor"`
	StructureActivatedAt    *float64         `json:"structure_activated_at"`
	StructureEntryBreached  bool             `json:"structure_entry_breached"`
	StructureFirstHitAt     *float64         `json:"structure_first_hit_at"`
	StructureFirstHitIndex  int64            `json:"structure_first_hit_index"`
	HoldAnchor              HoldAnchor       `json:"hold_anchor"`
	HoldActive              bool             `json:"hold_active"`
	HoldFloor               *float64         `json:"hold_floor"`
	HoldActivatedAt         *float64         `json:"hold_activated_at"`
	HoldEntryBreached       bool             `json:"hold_entry_breached"`
	HoldFirstHitAt          *float64         `json:"hold_first_hit_at"`
	HoldFirstHitIndex       int64            `json:"hold_first_hit_index"`
	HoldFirstHitLine        int64            `json:"hold_first_hit_line"`
	ConfirmCounts           ConfirmCounts    `json:"confirm_counts"`
	ConfirmFirstPriceBreach *ConfirmEvidence `json:"confirm_first_price_breach"`
	ConfirmFirstUnknown     *ConfirmEvidence `json:"confirm_first_unknown"`
	ConfirmFirstConfirmed   *ConfirmEvidence `json:"confirm_first_confirmed"`
	SourceEntry             *SourceBinding   `json:"source_entry"`
	RealEntryStage          string           `json:"real_entry_stage"`
	holdBaseFloor           float64
}

// ActualOrder は一度要求した数量と約定・取消数量を分ける注文記録です。
type ActualOrder struct {
	ID                string           `json:"id"`
	Kind              string           `json:"kind"`
	ReferenceID       string           `json:"reference_id"`
	PositionID        string           `json:"position_id"`
	Side              int              `json:"side"`
	Quantity          int              `json:"quantity"`
	Remaining         int              `json:"remaining"`
	FilledQuantity    int              `json:"filled_quantity"`
	CancelledQuantity int              `json:"cancelled_quantity"`
	RequestTime       float64          `json:"request_time"`
	RequestIndex      int64            `json:"request_index"`
	RequestLine       int64            `json:"request_line"`
	FillTime          *float64         `json:"fill_time"`
	FillPrice         *float64         `json:"fill_price"`
	FillLine          int64            `json:"fill_line"`
	Reason            string           `json:"reason"`
	Status            string           `json:"status"`
	Mark              *float64         `json:"mark"`
	Gain              *float64         `json:"gain"`
	Floor             *float64         `json:"floor"`
	NetPerUnit        *float64         `json:"net_per_unit"`
	Flagged           bool             `json:"flagged"`
	Source            ReferenceLot     `json:"source"`
	Role              string           `json:"role"`
	ATR               *float64         `json:"atr"`
	D                 float64          `json:"d"`
	Harvest           bool             `json:"harvest"`
	WholeNet          *float64         `json:"whole_net"`
	ClosedNet         *float64         `json:"closed_net"`
	HarvestNeeded     int              `json:"harvest_needed"`
	HarvestFeasible   bool             `json:"harvest_feasible"`
	StructureAnchor   StructureAnchor  `json:"structure_anchor"`
	StructureActive   bool             `json:"structure_active"`
	StructureFloor    *float64         `json:"structure_floor"`
	HoldAnchor        HoldAnchor       `json:"hold_anchor"`
	HoldActive        bool             `json:"hold_active"`
	HoldFloor         *float64         `json:"hold_floor"`
	ConfirmEvidence   *ConfirmEvidence `json:"confirm_evidence"`
	SourceEntry       *SourceBinding   `json:"source_entry"`
	RealEntryStage    string           `json:"real_entry_stage"`
}

// GridCandidate は定時に参照玉を見た結果で、実新規との違いを残します。
type GridCandidate struct {
	ReferenceID       string       `json:"reference_id"`
	SourceQuantity    int          `json:"source_quantity"`
	RequestedQuantity int          `json:"requested_quantity"`
	Side              int          `json:"side"`
	Role              string       `json:"role"`
	Reason            string       `json:"reason"`
	SourceCheck       *SourceCheck `json:"source_check"`
}

// ActualDecision は全定時の分類と候補別の不採用理由です。
type ActualDecision struct {
	At            float64         `json:"at"`
	QuoteTime     float64         `json:"quote_time"`
	QuoteIndex    int64           `json:"quote_index"`
	Action        string          `json:"action"`
	Reason        string          `json:"reason"`
	Candidates    []GridCandidate `json:"candidates"`
	SourceContext *SourceContext  `json:"source_context"`
}

// ClosedLot は返済約定片単位の厳密な費用と保護診断です。
type ClosedLot struct {
	PositionID              string           `json:"position_id"`
	ReferenceID             string           `json:"reference_id"`
	Side                    int              `json:"side"`
	Quantity                int              `json:"quantity"`
	EntryPrice              float64          `json:"entry_price"`
	ExitPrice               float64          `json:"exit_price"`
	EntryTime               float64          `json:"entry_time"`
	ExitTime                float64          `json:"exit_time"`
	ExitLine                int64            `json:"exit_line"`
	Reason                  string           `json:"reason"`
	GrossPnL                float64          `json:"gross_pnl"`
	Commission              float64          `json:"commission"`
	Slippage                float64          `json:"slippage"`
	PnL0                    float64          `json:"pnl0"`
	PnL5                    float64          `json:"pnl5"`
	PnL10                   float64          `json:"pnl10"`
	Flag                    bool             `json:"flag"`
	FlagTime                *float64         `json:"flag_time"`
	FlagMark                *float64         `json:"flag_mark"`
	FlagFloor               *float64         `json:"flag_floor"`
	FlagNetPerUnit          *float64         `json:"flag_net_per_unit"`
	RequestTime             float64          `json:"request_time"`
	RequestMark             *float64         `json:"request_mark"`
	RequestFloor            *float64         `json:"request_floor"`
	RequestNetPerUnit       *float64         `json:"request_net_per_unit"`
	RequestToFillAdverseYen *float64         `json:"request_to_fill_adverse_yen"`
	FloorJump               bool             `json:"floor_jump"`
	CostLoss                bool             `json:"cost_loss"`
	NominalFlat             bool             `json:"nominal_flat"`
	WholeFlag               bool             `json:"whole_flag"`
	WholeFlagTime           *float64         `json:"whole_flag_time"`
	WholeNetBeforeFill      float64          `json:"whole_net_before_fill"`
	ClosedNetAfterFill      float64          `json:"closed_net_after_fill"`
	Harvest                 bool             `json:"harvest"`
	CashFloorActive         bool             `json:"cash_floor_active"`
	StructureAnchor         StructureAnchor  `json:"structure_anchor"`
	StructureActive         bool             `json:"structure_active"`
	StructureFloor          *float64         `json:"structure_floor"`
	StructureActivatedAt    *float64         `json:"structure_activated_at"`
	StructureEntryBreached  bool             `json:"structure_entry_breached"`
	StructureFirstHitAt     *float64         `json:"structure_first_hit_at"`
	StructureFirstHitIndex  int64            `json:"structure_first_hit_index"`
	HoldAnchor              HoldAnchor       `json:"hold_anchor"`
	HoldActive              bool             `json:"hold_active"`
	HoldFloor               *float64         `json:"hold_floor"`
	HoldActivatedAt         *float64         `json:"hold_activated_at"`
	HoldEntryBreached       bool             `json:"hold_entry_breached"`
	HoldFirstHitAt          *float64         `json:"hold_first_hit_at"`
	HoldFirstHitIndex       int64            `json:"hold_first_hit_index"`
	HoldFirstHitLine        int64            `json:"hold_first_hit_line"`
	ConfirmRequestEvidence  *ConfirmEvidence `json:"confirm_request_evidence"`
	ConfirmFirstPriceBreach *ConfirmEvidence `json:"confirm_first_price_breach"`
	ConfirmFirstUnknown     *ConfirmEvidence `json:"confirm_first_unknown"`
	ConfirmFirstConfirmed   *ConfirmEvidence `json:"confirm_first_confirmed"`
	SourceEntry             *SourceBinding   `json:"source_entry"`
	RealEntryStage          string           `json:"real_entry_stage"`
}

// BookMetrics は実会計だけの観測集計です。未観測の現在評価額はnilです。
type BookMetrics struct {
	CashYen                      float64       `json:"cash_yen"`
	NetPnLYen                    float64       `json:"net_pnl_yen"`
	GrossPnLYen                  float64       `json:"gross_pnl_yen"`
	CommissionYen                float64       `json:"commission_yen"`
	SlippageYen                  float64       `json:"slippage_yen"`
	TotalCostYen                 float64       `json:"total_cost_yen"`
	EquityYen                    *float64      `json:"equity_yen"`
	FloatingYen                  *float64      `json:"floating_yen"`
	EquityPeakYen                float64       `json:"equity_peak_yen"`
	MinEquityYen                 float64       `json:"min_equity_yen"`
	MaxDrawdownYen               float64       `json:"max_drawdown_yen"`
	WorstFloatingYen             float64       `json:"worst_floating_yen"`
	EntryQuantity                int           `json:"entry_quantity"`
	ExitQuantity                 int           `json:"exit_quantity"`
	OpenQuantity                 int           `json:"open_quantity"`
	PendingEntryQuantity         int           `json:"pending_entry_quantity"`
	ReservedExitQuantity         int           `json:"reserved_exit_quantity"`
	ClosedPieces                 int           `json:"closed_pieces"`
	WinningPieces                int           `json:"winning_pieces"`
	LosingPieces                 int           `json:"losing_pieces"`
	FlatPieces                   int           `json:"flat_pieces"`
	ClosedLots                   int           `json:"closed_lots"`
	WinningLots                  int           `json:"winning_lots"`
	LosingLots                   int           `json:"losing_lots"`
	FlatLots                     int           `json:"flat_lots"`
	ProfitFlags                  int           `json:"profit_flags"`
	FlagAfterLossPieces          int           `json:"flag_after_loss_pieces"`
	RequestBeforeFloorViolations int           `json:"request_before_floor_violations"`
	MarkKnown                    bool          `json:"mark_known"`
	UnpricedExposureQuotes       int           `json:"unpriced_exposure_quotes"`
	WholeProfitFlags             int           `json:"whole_profit_flags"`
	WholeFlagAfterLossLots       int           `json:"whole_flag_after_loss_lots"`
	HarvestOrders                int           `json:"harvest_orders"`
	HarvestQuantity              int           `json:"harvest_quantity"`
	HarvestFilledQuantity        int           `json:"harvest_filled_quantity"`
	HarvestDoneLots              int           `json:"harvest_done_lots"`
	CashFloorActivatedLots       int           `json:"cash_floor_activated_lots"`
	FundingFailureLots           int           `json:"funding_failure_lots"`
	ProtectionObligations        int           `json:"protection_obligations"`
	ProtectionMissingQuantity    int           `json:"protection_missing_quantity"`
	StructureKnownEntries        int           `json:"structure_known_entries"`
	StructureUnknownEntries      int           `json:"structure_unknown_entries"`
	StructureActivatedLots       int           `json:"structure_activated_lots"`
	StructureEntryBreachedLots   int           `json:"structure_entry_breached_lots"`
	StructureHitLots             int           `json:"structure_hit_lots"`
	StructureExitOrders          int           `json:"structure_exit_orders"`
	HoldKnownEntries             int           `json:"hold_known_entries"`
	HoldUnknownEntries           int           `json:"hold_unknown_entries"`
	HoldActivatedLots            int           `json:"hold_activated_lots"`
	HoldEntryBreachedLots        int           `json:"hold_entry_breached_lots"`
	HoldHitLots                  int           `json:"hold_hit_lots"`
	HoldExitOrders               int           `json:"hold_exit_orders"`
	ConfirmCounts                ConfirmCounts `json:"confirm_counts"`
	ConfirmConfirmedLots         int           `json:"confirm_confirmed_lots"`
	ConfirmExitOrders            int           `json:"confirm_exit_orders"`
	ConfirmExitObligations       int           `json:"confirm_exit_obligations"`
	ConfirmMissingQuantity       int           `json:"confirm_missing_quantity"`
}

// BookResult は巨大な原行軌跡を含まない実所有の最小保存結果です。
type BookResult struct {
	HoldEnabled      bool             `json:"hold_enabled"`
	ConfirmEnabled   bool             `json:"confirm_enabled"`
	SourcePolicy     string           `json:"source_policy"`
	SourceEffects    []SourceEffect   `json:"source_effects"`
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
	session, mode    string
	guard            string
	stop             string
	holdEnabled      bool
	confirmEnabled   bool
	sourcePolicy     string
	sourceEffects    []SourceEffect
	cap              int
	delay            float64
	seen             map[string]bool
	lots             map[string]*ActualLot
	orders           []*ActualOrder
	trades           []Trade
	decisions        []ActualDecision
	closed           []ClosedLot
	last             Quote
	haveQuote        bool
	lastGrid         float64
	haveGrid         bool
	lastBar3         float64
	lastNormalTime   float64
	haveNormal       bool
	closeSeen        map[string]bool
	metrics          BookMetrics
	warnings         []string
	reentryEnabled   bool
	allByPosition    map[string]*ActualLot
	lastActual       map[string]*ActualLot
	flatStamps       map[string]ReentryCompletion
	opportunitySeen  map[OpportunityKey]bool
	entryOpportunity map[string]OpportunityKey
	entrySerial      int
	lastAssessments  []ReentryAssessment
}

// ----------------------------------------

// NewBook は実会計を初期化し、政策と片側上限を検査します。
//
// 引数: sessionID/modeはstring、capはintの100枚、holdEnabledはboolの保持帯有効化です。
// 返り値: *Bookは独立実会計、errorは不正条件です。
func NewBook(sessionID, mode string, cap int, holdEnabled bool) (*Book, error) {
	if sessionID == "" || (mode != "S0G1" && mode != "S0G2") || cap != 100 {
		return nil, fmt.Errorf("場・政策又は片側上限が不正")
	}
	guard := "G1"
	if mode == "S0G2" {
		guard = "G2"
	}
	return &Book{session: sessionID, mode: mode, stop: "S0", guard: guard, cap: cap, holdEnabled: holdEnabled, seen: map[string]bool{}, lots: map[string]*ActualLot{}, closeSeen: map[string]bool{}}, nil
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

// normalizeAnchor は要求時の公開EMAを検査し、未知の数値を創作しません。
//
// 引数: at(float64)は要求時計、tech(TechnicalView)は当時公開足、anchor(StructureAnchor)は固定候補線です。
// 返り値: StructureAnchorは検査済み値、errorは既知とされた線の当時性・数値の不整合です。
func normalizeAnchor(at float64, tech TechnicalView, anchor StructureAnchor) (StructureAnchor, error) {
	if !anchor.Known {
		anchor.Price, anchor.At, anchor.BarEnd = 0, 0, 0
		if anchor.Reason == "" {
			anchor.Reason = "入口EMA価格線は未観測"
		}
		return anchor, nil
	}
	if !actualFinite(anchor.Price) || !actualFinite(anchor.At) || !actualFinite(anchor.BarEnd) ||
		anchor.Price <= 0 || anchor.At != at || anchor.BarEnd <= 0 || anchor.BarEnd > at || at-anchor.BarEnd > 180 ||
		!tech.ExitKnown || !actualFinite(tech.EMA8_3) || !actualFinite(tech.Bar3End) ||
		anchor.Price != tech.EMA8_3 || anchor.BarEnd != tech.Bar3End {
		return StructureAnchor{}, fmt.Errorf("既知の構造線が要求時の確定EMAと不整合")
	}
	return anchor, nil
}

// activateStructure は実新規約定に要求時の価格線を結び、単位だけを実建値へ変換します。
//
// 引数: p(*ActualLot)は新しい実所有、q(Quote)はその正常約定気配です。
// 返り値: ありません。価格線は滑りや後のEMAで移動しません。
func (b *Book) activateStructure(p *ActualLot, q Quote) {
	if p.StructureAnchor.Known {
		b.metrics.StructureKnownEntries++
	} else {
		b.metrics.StructureUnknownEntries++
	}
	if b.stop != "S1" || !p.StructureAnchor.Known {
		return
	}
	floor := float64(p.Side) * (p.StructureAnchor.Price - p.EntryPrice)
	p.StructureActive = true
	p.StructureFloor = actualPointer(floor)
	p.StructureActivatedAt = actualPointer(q.Time)
	p.Floor = math.Max(p.Floor, floor)
	b.metrics.StructureActivatedLots++
	gain := actualGrossPerUnit(p.Side, actualMark(q, p.Side), p.EntryPrice) / 10
	if gain <= floor {
		p.StructureEntryBreached = true
		b.metrics.StructureEntryBreachedLots++
	}
}

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

// actualDecimal は有限な十進表示値を有理数へ写します。
//
// 引数: valueはfloat64の計画損益です。
// 返り値: *big.Ratは正確な表示値、errorは非有限値又は変換異常です。
func actualDecimal(value float64) (*big.Rat, error) {
	if !actualFinite(value) {
		return nil, fmt.Errorf("損益計画は有限値が必要")
	}
	r, ok := new(big.Rat).SetString(strconv.FormatFloat(value, 'f', -1, 64))
	if !ok {
		return nil, fmt.Errorf("十進損益の変換に失敗")
	}
	return r, nil
}

// actualCeil は有理数を正の無限大方向へ整数化します。
//
// 引数: valueは*big.Ratです。
// 返り値: *big.Intは負値を含む数学上の切上げ整数です。
func actualCeil(value *big.Rat) *big.Int {
	q, r := new(big.Int), new(big.Int)
	q.QuoRem(value.Num(), value.Denom(), r)
	if r.Sign() > 0 {
		q.Add(q, big.NewInt(1))
	}
	return q
}

// actualHarvestPlan は現在価格で必要な部分利確量だけを計画します。
//
// 引数: quantityはintの実残量、unitNet/closedNetはfloat64の現在単価益と実確定額です。
// 返り値: needed/closeQuantityはint、feasibleはbool、errorは不正な計画入力です。
// 未約定の計画利益を実確定額へ足さず、必要量が残量を超えれば全返済とします。
func actualHarvestPlan(quantity int, unitNet, closedNet float64) (needed, closeQuantity int, feasible bool, err error) {
	if quantity <= 0 || quantity > 100 || !actualFinite(unitNet) || unitNet <= 0 || !actualFinite(closedNet) {
		return 0, 0, false, fmt.Errorf("部分利確計画の残量又は損益が不正")
	}
	u, err := actualDecimal(unitNet)
	if err != nil {
		return 0, 0, false, err
	}
	r, err := actualDecimal(closedNet)
	if err != nil {
		return 0, 0, false, err
	}
	numerator := new(big.Rat).Sub(big.NewRat(int64(222*quantity+1), 1), r)
	denominator := new(big.Rat).Add(u, big.NewRat(222, 1))
	raw := actualCeil(new(big.Rat).Quo(numerator, denominator))
	if !raw.IsInt64() {
		return 0, 0, false, fmt.Errorf("部分利確必要量の有限範囲を超えた")
	}
	needed = int(raw.Int64())
	closeQuantity = max(1, min(quantity, needed))
	whole := new(big.Rat).Add(r, new(big.Rat).Mul(u, big.NewRat(int64(quantity), 1)))
	feasible = needed <= quantity && whole.Cmp(big.NewRat(1, 1)) >= 0
	return needed, closeQuantity, feasible, nil
}

// actualCashFloor は実確定益だけから残玉の5pt刻み停止幅を計算します。
//
// 引数: closedNetはfloat64の実確定額、quantityはintの実残量です。
// 返り値: float64は建値以上の必要幅、errorは不正な量又は有限範囲です。
func actualCashFloor(closedNet float64, quantity int) (float64, error) {
	if quantity <= 0 || quantity > 100 {
		return 0, fmt.Errorf("cash床の残量が不正")
	}
	r, err := actualDecimal(closedNet)
	if err != nil {
		return 0, err
	}
	numerator := new(big.Rat).Sub(big.NewRat(int64(222*quantity+1), 1), r)
	if numerator.Sign() <= 0 {
		return 0, nil
	}
	steps := actualCeil(new(big.Rat).Quo(numerator, big.NewRat(int64(50*quantity), 1)))
	if !steps.IsInt64() {
		return 0, fmt.Errorf("cash床の有限範囲を超えた")
	}
	floor := float64(steps.Int64()) * 5
	if !actualFinite(floor) {
		return 0, fmt.Errorf("cash床が非有限")
	}
	return floor, nil
}

// orderedLots は参照ID順で実所有を列挙します。
//
// 引数: なし。
// 返り値: []*ActualLotは数量0の完結玉も含む決定的順です。
func (b *Book) orderedLots() []*ActualLot {
	lots := b.lots
	if b.reentryEnabled {
		lots = b.allByPosition
	}
	keys := make([]string, 0, len(lots))
	for id := range lots {
		keys = append(keys, id)
	}
	sort.Strings(keys)
	out := make([]*ActualLot, 0, len(keys))
	for _, id := range keys {
		out = append(out, lots[id])
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

// occupied は方向を跨いだ同時一建玉と未約定新規の占有を判定します。
//
// 引数: なし。
// 返り値: boolは実玉又は未約定新規が存在する場合にtrueです。
func (b *Book) occupied() bool {
	for _, p := range b.lots {
		if p.Quantity > 0 {
			return true
		}
	}
	for _, o := range b.orders {
		if o.Kind == "entry" && o.Remaining > 0 {
			return true
		}
	}
	return false
}

// wholeNet は実確定部分と残玉の費用後現在額を結合します。
//
// 引数: pは*ActualLot、qは正常なQuoteです。
// 返り値: float64は実確定部分の往復費用と残玉の往復費用を各一回だけ含む額です。
func wholeNet(p *ActualLot, q Quote) float64 {
	unit := actualGrossPerUnit(p.Side, actualMark(q, p.Side), p.EntryPrice) - 122
	return p.NetPnL + unit*float64(p.Quantity)
}

// observeWhole は当行全fill後の全玉正益と最高・最低額を記録します。
//
// 引数: qは正常なQuoteです。
// 返り値: なし。初回正益を後の原行へずらさず、完結時の正益も観測します。
func (b *Book) observeWhole(q Quote) {
	for _, p := range b.orderedLots() {
		value := wholeNet(p, q)
		p.WholeBestNet = math.Max(p.WholeBestNet, value)
		p.WholeWorstNet = math.Min(p.WholeWorstNet, value)
		if !p.WholeFlag && value > 0 {
			p.WholeFlag = true
			p.WholeFlagTime = actualPointer(q.Time)
			p.WholeFlagIndex = q.Index
			p.WholeFlagLine = q.Line
			b.metrics.WholeProfitFlags++
		}
		for i := len(b.closed) - 1; i >= 0; i-- {
			c := &b.closed[i]
			if c.ExitLine < q.Line {
				break
			}
			if c.PositionID == p.ID && c.ExitLine == q.Line {
				c.WholeFlag, c.WholeFlagTime = p.WholeFlag, p.WholeFlagTime
			}
		}
	}
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
	o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "exit", ReferenceID: p.ReferenceID, PositionID: p.ID, Side: p.Side, Quantity: quantity, Remaining: quantity, RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: reason, Status: "pending", Flagged: p.Flag, Floor: actualPointer(p.Floor), StructureAnchor: p.StructureAnchor, StructureActive: p.StructureActive, StructureFloor: p.StructureFloor, HoldAnchor: p.HoldAnchor, HoldActive: p.HoldActive, HoldFloor: p.HoldFloor, SourceEntry: p.SourceEntry, RealEntryStage: p.RealEntryStage}
	if actualNormal(q) && q.Time <= at {
		m := actualMark(q, p.Side)
		gross := actualGrossPerUnit(p.Side, m, p.EntryPrice)
		g := gross / 10
		o.Mark = actualPointer(m)
		o.Gain = actualPointer(g)
		o.NetPerUnit = actualPointer(gross - 122)
		o.WholeNet = actualPointer(wholeNet(p, q))
		o.ClosedNet = actualPointer(p.NetPnL)
	}
	if p.RequestTime == nil {
		p.RequestTime = actualPointer(at)
		p.RequestMark = o.Mark
		p.RequestFloor = actualPointer(p.Floor)
	}
	p.ReservedExit += quantity
	b.orders = append(b.orders, o)
	if reason == HoldExitReason {
		b.metrics.HoldExitOrders++
	}
	if reason == ConfirmExitReason {
		b.metrics.ConfirmExitOrders++
	}
	if reason == "固定EMA構造否定" {
		b.metrics.StructureExitOrders++
	}
}

// requestHarvest は数量計画を返済予約へ写し、実確定益を増やしません。
//
// 引数: pは*ActualLot、qは正常Quote、needed/quantityはint、feasibleはboolです。
// 返り値: なし。既に一度計画した建玉への追加の初回利確は出しません。
func (b *Book) requestHarvest(p *ActualLot, q Quote, needed, quantity int, feasible bool) {
	if p.HarvestOrderID != "" || p.ReservedExit != 0 || quantity <= 0 {
		return
	}
	reason := "正益起動の部分利確"
	if quantity >= p.Quantity {
		reason = "残玉を分割できないため全利確"
	}
	if !feasible {
		reason = "必要利確量不足の全返済"
	}
	before := len(b.orders)
	b.requestExit(p, quantity, q.Time, q, reason)
	if len(b.orders) == before {
		return
	}
	o := b.orders[len(b.orders)-1]
	o.Harvest, o.HarvestNeeded, o.HarvestFeasible = true, needed, feasible
	p.HarvestOrderID = o.ID
	p.HarvestTarget, p.HarvestNeeded, p.HarvestFeasible = o.Quantity, needed, feasible
	p.HarvestAt = actualPointer(q.Time)
	b.metrics.HarvestOrders++
	b.metrics.HarvestQuantity += o.Quantity
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
	return b.applyCloseAt(c, q.Time, q, "quote")
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
			if b.reentryEnabled && b.allByPosition[o.PositionID] != nil {
				return fmt.Errorf("再参加の実玉IDを再利用した")
			}
			p := &ActualLot{ID: o.PositionID, ReferenceID: o.ReferenceID, Method: o.Source.Method, Owner: o.Source.Owner, SourceID: o.Source.SourceID, Parent: o.Source.Parent, Role: o.Role, Side: o.Side, Quantity: n, InitialQuantity: n, EntryPrice: price, EntryTime: q.Time, EntryIndex: q.Index, EntryLine: q.Line, EntryATR: o.ATR, D: o.D, Floor: -125, StructureAnchor: o.StructureAnchor, StructureFirstHitIndex: -1, HoldAnchor: o.HoldAnchor, HoldFirstHitIndex: -1, holdBaseFloor: -125}
			p.SourceEntry = o.SourceEntry
			if o.SourceEntry != nil {
				p.RealEntryStage = "実初参加"
				if b.reentryEnabled && o.RealEntryStage == "利確後再参加要求" {
					p.RealEntryStage = "利確後再参加"
				}
			}
			b.activateStructure(p, q)
			b.activateHold(p, q)
			b.lots[o.ReferenceID] = p
			if b.reentryEnabled {
				b.allByPosition[p.ID] = p
				b.lastActual[p.ReferenceID] = p
			}
			b.metrics.EntryQuantity += n
			b.metrics.CashYen -= actualFee * float64(n)
		} else {
			p := b.lots[o.ReferenceID]
			if b.reentryEnabled {
				p = b.allByPosition[o.PositionID]
				if p == nil || p.ReferenceID != o.ReferenceID || b.lots[o.ReferenceID] != p {
					return fmt.Errorf("再参加返済が現在世代と一致しない")
				}
			}
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
			closed := ClosedLot{PositionID: p.ID, ReferenceID: p.ReferenceID, Side: p.Side, Quantity: n, EntryPrice: p.EntryPrice, ExitPrice: price, EntryTime: p.EntryTime, ExitTime: q.Time, ExitLine: q.Line, Reason: o.Reason, GrossPnL: gross, Commission: 22 * float64(n), Slippage: 100 * float64(n), PnL0: gross - 22*float64(n), PnL5: net, PnL10: gross - 222*float64(n), Flag: p.Flag, FlagTime: p.FlagTime, FlagMark: p.FlagMark, FlagFloor: p.FlagFloor, FlagNetPerUnit: p.FlagNetPerUnit, RequestTime: o.RequestTime, RequestMark: o.Mark, RequestFloor: o.Floor, RequestNetPerUnit: o.NetPerUnit, CostLoss: gross > 0 && net < 0, NominalFlat: price == p.EntryPrice, WholeFlag: p.WholeFlag, WholeFlagTime: p.WholeFlagTime, WholeNetBeforeFill: wholeNet(p, q), ClosedNetAfterFill: p.NetPnL + net, Harvest: o.Harvest, CashFloorActive: p.CashFloorActive}
			closed.StructureAnchor, closed.StructureActive, closed.StructureFloor = p.StructureAnchor, p.StructureActive, p.StructureFloor
			closed.StructureActivatedAt, closed.StructureEntryBreached = p.StructureActivatedAt, p.StructureEntryBreached
			closed.StructureFirstHitAt, closed.StructureFirstHitIndex = p.StructureFirstHitAt, p.StructureFirstHitIndex
			closed.HoldAnchor, closed.HoldActive, closed.HoldFloor = p.HoldAnchor, p.HoldActive, p.HoldFloor
			closed.HoldActivatedAt, closed.HoldEntryBreached = p.HoldActivatedAt, p.HoldEntryBreached
			closed.HoldFirstHitAt, closed.HoldFirstHitIndex, closed.HoldFirstHitLine = p.HoldFirstHitAt, p.HoldFirstHitIndex, p.HoldFirstHitLine
			closed.ConfirmRequestEvidence = o.ConfirmEvidence
			closed.ConfirmFirstPriceBreach, closed.ConfirmFirstUnknown, closed.ConfirmFirstConfirmed = p.ConfirmFirstPriceBreach, p.ConfirmFirstUnknown, p.ConfirmFirstConfirmed
			closed.SourceEntry, closed.RealEntryStage = p.SourceEntry, p.RealEntryStage
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
			if o.Harvest {
				p.HarvestFilled += n
				b.metrics.HarvestFilledQuantity += n
			}
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
		if o.Harvest {
			p := b.lots[o.ReferenceID]
			if b.reentryEnabled {
				p = b.allByPosition[o.PositionID]
			}
			if p == nil || p.HarvestOrderID != o.ID || p.HarvestFilled != p.HarvestTarget {
				return fmt.Errorf("部分利確の完了数量が不一致")
			}
			if p.HarvestDoneAt == nil {
				p.HarvestDoneAt = actualPointer(q.Time)
				b.metrics.HarvestDoneLots++
				if p.NetPnL-222*float64(p.Quantity) < 1 {
					p.FundingFailed = true
					b.metrics.FundingFailureLots++
				}
			}
		}
		seconds, fraction := math.Modf(q.Time)
		stamp := time.Unix(int64(seconds), int64(math.Round(fraction*1e9))).In(time.FixedZone("日本標準時", 9*3600)).Format(time.RFC3339Nano)
		b.trades = append(b.trades, Trade{ID: fmt.Sprintf("%s_%s_T%06d", b.session, b.mode, len(b.trades)+1), Timestamp: stamp, Type: typ, PositionID: o.PositionID, Price: price, Quantity: n, FeeYen: actualFee * float64(n), MethodID: b.mode, SourceLine: q.Line, Reason: o.Reason})
	}
	if b.reentryEnabled {
		return b.captureReentryCompletions(q)
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
// 引数: qはQuote、refはReferenceFrame、techはTechnicalView、currentは当原行の*CurrentEvidenceの0又は1引数です。
// 返り値: errorは時計・通知・数量・複合確認出典の不正です。確認有効時はnil明示を含む1引数が必要です。
func (b *Book) OnQuote(q Quote, ref ReferenceFrame, tech TechnicalView, current ...*CurrentEvidence) error {
	if len(current) > 1 || (b.confirmEnabled && len(current) != 1) {
		return fmt.Errorf("当原行特徴は0又は1引数、複合確認有効時は1引数が必要です")
	}
	if err := b.validateHoldQuote(q); err != nil {
		return err
	}
	if err := b.validateConfirmQuote(q); err != nil {
		return err
	}
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
		if newBar && tech.Failed(p.Side) {
			b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, "確定3分技法失敗")
		}
		if actualNormal(q) {
			gain := b.observe(p, q)
			p.Floor = math.Max(p.holdBaseFloor, math.Max(-125, p.BestGain-p.D))
			if p.StructureActive {
				p.Floor = math.Max(p.Floor, *p.StructureFloor)
				if gain <= *p.StructureFloor && p.StructureFirstHitAt == nil {
					p.StructureFirstHitAt = actualPointer(q.Time)
					p.StructureFirstHitIndex = q.Index
					b.metrics.StructureHitLots++
				}
			}
			if p.Flag {
				p.Floor = math.Max(p.Floor, 0)
				if b.guard == "G1" {
					if p.HarvestDoneAt != nil {
						cash, err := actualCashFloor(p.NetPnL, p.Quantity)
						if err != nil {
							return err
						}
						p.CashFloor = actualPointer(cash)
						p.Floor = math.Max(p.Floor, cash)
						if !p.CashFloorActive {
							p.CashFloorActive = true
							p.CashFloorAt = actualPointer(q.Time)
							b.metrics.CashFloorActivatedLots++
						}
					}
				}
			}
			holdBinding := b.applyHoldFloor(p, q, gain)
			if p.Flag && p.FlagIndex == q.Index {
				p.FlagFloor = actualPointer(p.Floor)
			}
			needsAll := gain <= p.Floor || gain <= -125
			if gain <= -125 {
				b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, "共通125pt保護")
			} else if gain <= p.Floor {
				reason := "正益前ATR損失追尾"
				if holdBinding {
					reason = HoldExitReason
				} else if p.StructureActive && *p.StructureFloor >= p.Floor && gain <= *p.StructureFloor {
					reason = "固定EMA構造否定"
				} else if p.Flag && b.guard == "G2" {
					reason = "G2全量建値床・ATR追尾"
				} else if p.Flag && p.CashFloorActive {
					reason = "G1確定益予算・ATR追尾"
				} else if p.Flag {
					reason = "G1建値床・ATR追尾"
				}
				b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, reason)
			}
			if needsAll {
				b.metrics.ProtectionObligations++
				if missing := p.Quantity - p.ReservedExit; missing > 0 {
					b.metrics.RequestBeforeFloorViolations++
					b.metrics.ProtectionMissingQuantity += missing
				}
			}
			if b.guard == "G1" && p.Flag && p.HarvestOrderID == "" && p.ReservedExit == 0 {
				unit := actualGrossPerUnit(p.Side, actualMark(q, p.Side), p.EntryPrice) - 122
				if unit > 0 {
					needed, quantity, feasible, err := actualHarvestPlan(p.Quantity, unit, p.NetPnL)
					if err != nil {
						return err
					}
					b.requestHarvest(p, q, needed, quantity, feasible)
				}
			}
			if b.confirmEnabled {
				if err := b.observeConfirmation(p, q, current[0]); err != nil {
					return err
				}
			}
		}
	}
	if newBar {
		b.lastBar3 = tech.Bar3End
	}
	if actualNormal(q) {
		b.observeWhole(q)
	}
	b.mark(q)
	return nil
}

// OnGrid は外部で選別済みの一候補を15分呼出し時だけ実新規にします。
//
// 引数: at(float64)、q(Quote)、ref(ReferenceFrame)、tech(TechnicalView)、anchor(StructureAnchor)、hold(HoldAnchor)、current(CurrentEvidence)は要求時入力です。
// 返り値: errorは時計・参照玉の不正です。鮮度不足は判定不能として保存します。
func (b *Book) OnGrid(at float64, q Quote, ref ReferenceFrame, tech TechnicalView, anchor StructureAnchor, hold HoldAnchor, current CurrentEvidence) error {
	if b.sourcePolicy != "" {
		return fmt.Errorf("Source会計はOnSourceGridを使用してください")
	}
	if !actualFinite(at) || !actualFinite(q.Time) || (b.haveGrid && at <= b.lastGrid) {
		return fmt.Errorf("定時時計は有限の昇順が必要")
	}
	anchor, err := normalizeAnchor(at, tech, anchor)
	if err != nil {
		return err
	}
	if len(ref.Lots) > 1 {
		return fmt.Errorf("定時候補は外部で一つに絞る必要があります")
	}
	for _, src := range ref.Lots {
		if src.ID == "" || (src.Side != 1 && src.Side != -1) || src.Quantity != 100 || !actualFinite(src.At) || src.At > at || !actualFinite(src.Entry) {
			return fmt.Errorf("定時候補のID・方向・100枚・当時性が不正")
		}
	}
	side := 0
	if len(ref.Lots) == 1 {
		side = ref.Lots[0].Side
	}
	hold, err = normalizeHoldAnchor(at, q, current, side, hold)
	if err != nil {
		return err
	}
	b.haveGrid = true
	b.lastGrid = at
	d := ActualDecision{At: at, QuoteTime: q.Time, QuoteIndex: q.Index, Action: "待ち", Reason: "有効な新規候補なし", Candidates: []GridCandidate{}}
	if b.occupied() {
		d.Action, d.Reason = "処理中", "既存新規注文の約定待ち"
		for _, p := range b.lots {
			if p.Quantity > 0 {
				d.Action, d.Reason = "保有継続", "方向を跨いだ同時一建玉を維持"
				break
			}
		}
		for _, src := range ref.Lots {
			d.Candidates = append(d.Candidates, GridCandidate{ReferenceID: src.ID, SourceQuantity: src.Quantity, Side: src.Side, Role: src.Kind, Reason: "実保有又は新規待機で占有"})
		}
		b.decisions = append(b.decisions, d)
		return nil
	}
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
		if frameIDs[src.ID] {
			return fmt.Errorf("参照実玉のID・方向・数量が不正")
		}
		frameIDs[src.ID] = true
		c := GridCandidate{ReferenceID: src.ID, SourceQuantity: src.Quantity, Side: src.Side, Role: src.Kind}
		switch {
		case src.Closing:
			c.Reason = "参照返済中"
		case b.seen[src.ID]:
			c.Reason = "同じ定時候補IDへ再入場しない"
		default:
			role := src.Kind
			reason := "定時の現在根拠"
			c.Role = role
			c.Reason = reason
			{
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
					o := &ActualOrder{ID: fmt.Sprintf("%s_%s_O%06d", b.session, b.mode, len(b.orders)+1), Kind: "entry", ReferenceID: src.ID, PositionID: fmt.Sprintf("%s_%s_P%06d", b.session, b.mode, len(b.seen)+1), Side: src.Side, Quantity: n, Remaining: n, RequestTime: at, RequestIndex: q.Index, RequestLine: q.Line, Reason: reason, Status: "pending", Source: src, Role: role, ATR: atr, D: distance, StructureAnchor: anchor, HoldAnchor: hold}
					b.orders = append(b.orders, o)
					b.seen[src.ID] = true
					c.RequestedQuantity = n
					d.Action = "新規要求"
					d.Reason = "15分定時の外部選別済み候補を100枚で実新規"
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
	r := BookResult{HoldEnabled: b.holdEnabled, ConfirmEnabled: b.confirmEnabled, SourcePolicy: b.sourcePolicy, SourceEffects: append([]SourceEffect{}, b.sourceEffects...), Session: b.session, Mode: b.mode, SideCap: b.cap, FillDelaySeconds: b.delay, Trades: append([]Trade{}, b.trades...), Decisions: append([]ActualDecision{}, b.decisions...), Closed: append([]ClosedLot{}, b.closed...), Positions: []ActualLot{}, Lots: []ActualLot{}, Orders: []ActualOrder{}, PendingEntries: []ActualOrder{}, QuantityBySide: map[int]int{-1: 0, 1: 0}, Metrics: b.metrics, Warnings: append([]string{}, b.warnings...)}
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
			if p.WholeFlag && p.NetPnL < 0 {
				r.Metrics.WholeFlagAfterLossLots++
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
