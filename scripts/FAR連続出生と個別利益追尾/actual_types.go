// Package miniprotect は固定93Shadowとは独立したmini実口座です。
// Sourceを再生成せず、公開通知と原行だけを受け取ります。
package miniprotect

import native "github.com/masayoshi4649/SessionTradeExecuter/mininative"

type Observation = native.Observation
type Session = native.Session
type QuoteStamp = native.QuoteStamp

// ActorConfig は利益床/費用仮定/価格時計遅延の独立した12組を指定します。
type ActorConfig struct {
	Policy       string  `json:"policy"`
	SlipPts      float64 `json:"slip_pts"`
	DelaySeconds int     `json:"delay_seconds"`
}

// NativeBatch は同原行のP/Uを一度に配送し、商品合算の上限を維持します。
type NativeBatch struct {
	Method string            `json:"method"`
	Delta  native.StepResult `json:"delta"`
}

// SourceIdentity は出生量と元の技法上の段階をActualの役割から分けます。
type SourceIdentity struct {
	Method        string     `json:"method"`
	SignalID      string     `json:"signal_id"`
	Kind          string     `json:"kind"`
	Parent        string     `json:"parent"`
	SourceID      string     `json:"source_id"`
	QuantityMicro int        `json:"quantity_micro"`
	BirthQuantity int        `json:"birth_quantity"`
	BirthTime     float64    `json:"birth_time"`
	BirthQuote    QuoteStamp `json:"birth_quote"`
}

// ATRLock は実取得時又は初回既知の公開幅を一度だけ固定した証拠です。
type ATRLock struct {
	Value      float64    `json:"value"`
	Available  float64    `json:"available"`
	Nominal    float64    `json:"nominal"`
	AgeSeconds float64    `json:"age_seconds"`
	Width      float64    `json:"width"`
	Quote      QuoteStamp `json:"quote"`
	AfterEntry bool       `json:"after_entry"`
}

// MTMPoint は実残玉の単価uと全Hold清算Wを同時に保存します。
type MTMPoint struct {
	Quote       QuoteStamp `json:"quote"`
	Phase       string     `json:"phase"`
	Quantity    int        `json:"quantity"`
	Reserved    int        `json:"reserved"`
	MarkPrice   float64    `json:"mark_price"`
	GainPoints  float64    `json:"gain_points"`
	UnitNet     float64    `json:"unit_net"`
	RealizedNet float64    `json:"realized_net"`
	WholeNet    float64    `json:"whole_net"`
}

// PositionMarks は少数の初回/返し/極値だけを残し、毎原行を複製しません。
type PositionMarks struct {
	First                      *MTMPoint `json:"first"`
	Last                       *MTMPoint `json:"last"`
	FirstUnitPositive          *MTMPoint `json:"first_unit_positive"`
	FirstWholePositive         *MTMPoint `json:"first_whole_positive"`
	FirstUnitNonPositiveAfter  *MTMPoint `json:"first_unit_nonpositive_after"`
	FirstUnitNegativeAfter     *MTMPoint `json:"first_unit_negative_after"`
	FirstWholeNonPositiveAfter *MTMPoint `json:"first_whole_nonpositive_after"`
	FirstWholeNegativeAfter    *MTMPoint `json:"first_whole_negative_after"`
	UnitMax                    *MTMPoint `json:"unit_max"`
	UnitMin                    *MTMPoint `json:"unit_min"`
	WholeMax                   *MTMPoint `json:"whole_max"`
	WholeMin                   *MTMPoint `json:"whole_min"`
}

// ActualPosition は一つの実新規約定を永久履歴と現在残量へ分けて保持します。
type ActualPosition struct {
	ID               string         `json:"id"`
	EntryOrderID     string         `json:"entry_order_id"`
	Source           SourceIdentity `json:"source"`
	SourceHoldID     string         `json:"source_hold_id"`
	Side             int            `json:"side"`
	InitialQuantity  int            `json:"initial_quantity"`
	Quantity         int            `json:"quantity"`
	Reserved         int            `json:"reserved"`
	ClosedQuantity   int            `json:"closed_quantity"`
	EntryPrice       float64        `json:"entry_price"`
	EntryQuote       QuoteStamp     `json:"entry_quote"`
	ClosedQuote      *QuoteStamp    `json:"closed_quote"`
	GrossYen         float64        `json:"gross_yen"`
	RealizedNet      float64        `json:"realized_net"`
	PeakGain         float64        `json:"peak_gain"`
	HasMark          bool           `json:"has_mark"`
	ProtectionActive bool           `json:"protection_active"`
	Activation       *MTMPoint      `json:"activation"`
	FloorGain        *float64       `json:"floor_gain"`
	FloorUpdated     *MTMPoint      `json:"floor_updated"`
	FirstFloorHit    *MTMPoint      `json:"first_floor_hit"`
	ATR              *ATRLock       `json:"atr"`
	Marks            PositionMarks  `json:"marks"`
}

// ActualOrder は要求時計と最終状態を保持し、同原行fillを許しません。
type ActualOrder struct {
	ID                  string         `json:"id"`
	Kind                string         `json:"kind"`
	Side                int            `json:"side"`
	Quantity            int            `json:"quantity"`
	PositionID          string         `json:"position_id"`
	Source              SourceIdentity `json:"source"`
	SourceHoldID        string         `json:"source_hold_id"`
	NativeCloseSignalID string         `json:"native_close_signal_id"`
	NativeCloseNoticeID string         `json:"native_close_notice_id"`
	RequestTime         float64        `json:"request_time"`
	RequestQuote        QuoteStamp     `json:"request_quote"`
	Reason              string         `json:"reason"`
	Status              string         `json:"status"`
	FillID              string         `json:"fill_id"`
	CancelTime          *float64       `json:"cancel_time"`
	CancelReason        string         `json:"cancel_reason"`
	ProtectionPoint     *MTMPoint      `json:"protection_point"`
}

// ActualAllocation は返済片ごとの所有/原行/実現費用を固定します。
type ActualAllocation struct {
	PositionID   string     `json:"position_id"`
	SourceHoldID string     `json:"source_hold_id"`
	Quantity     int        `json:"quantity"`
	EntryPrice   float64    `json:"entry_price"`
	EntryQuote   QuoteStamp `json:"entry_quote"`
	ExitPrice    float64    `json:"exit_price"`
	ExitQuote    QuoteStamp `json:"exit_quote"`
	GrossYen     float64    `json:"gross_yen"`
	EntryFeeYen  float64    `json:"entry_fee_yen"`
	ExitFeeYen   float64    `json:"exit_fee_yen"`
	EntrySlipYen float64    `json:"entry_slip_yen"`
	ExitSlipYen  float64    `json:"exit_slip_yen"`
	NetYen       float64    `json:"net_yen"`
}

// ActualFill は元Sourceへの再通知を行わない実口座だけの約定です。
type ActualFill struct {
	ID                  string             `json:"id"`
	OrderID             string             `json:"order_id"`
	PositionID          string             `json:"position_id"`
	Action              string             `json:"action"`
	Side                int                `json:"side"`
	Quantity            int                `json:"quantity"`
	Price               float64            `json:"price"`
	Quote               QuoteStamp         `json:"quote"`
	Source              SourceIdentity     `json:"source"`
	SourceHoldID        string             `json:"source_hold_id"`
	NativeCloseSignalID string             `json:"native_close_signal_id"`
	NativeCloseNoticeID string             `json:"native_close_notice_id"`
	Reason              string             `json:"reason"`
	FeeYen              float64            `json:"fee_yen"`
	SlipYen             float64            `json:"slip_yen"`
	GrossYen            float64            `json:"gross_yen"`
	NetContributionYen  float64            `json:"net_contribution_yen"`
	Allocations         []ActualAllocation `json:"allocations"`
}

// SourceEventTrace は全配送とActorへの作用を小さな台帳で証明します。
type SourceEventTrace struct {
	At                  float64    `json:"at"`
	Phase               string     `json:"phase"`
	Method              string     `json:"method"`
	Kind                string     `json:"kind"`
	SignalID            string     `json:"signal_id"`
	ExecutionID         string     `json:"execution_id"`
	HoldID              string     `json:"hold_id"`
	NoticeID            string     `json:"notice_id"`
	Quote               QuoteStamp `json:"quote"`
	Side                int        `json:"side"`
	Quantity            int        `json:"quantity"`
	Before              int        `json:"before"`
	ActualPendingBefore int        `json:"actual_pending_before"`
	ActualNewCancelled  int        `json:"actual_new_cancelled"`
	ActualFreeBefore    int        `json:"actual_free_before"`
	ActualExitRequested int        `json:"actual_exit_requested"`
	ActualFreeAfter     int        `json:"actual_free_after"`
	ActualAccepted      int        `json:"actual_accepted"`
	Available           int        `json:"available"`
	OrderID             string     `json:"order_id"`
	Reason              string     `json:"reason"`
}

// AccountPoint はP/Uを合算した一口座の清算評価です。
type AccountPoint struct {
	Quote    QuoteStamp `json:"quote"`
	Phase    string     `json:"phase"`
	Equity   float64    `json:"equity"`
	CashNet  float64    `json:"cash_net"`
	OpenBuy  int        `json:"open_buy"`
	OpenSell int        `json:"open_sell"`
}

// AccountMarks は口座の最大DDと極値・評価間隔を原行へ結びます。
type AccountMarks struct {
	First          *AccountPoint `json:"first"`
	Last           *AccountPoint `json:"last"`
	Peak           *AccountPoint `json:"peak"`
	Max            *AccountPoint `json:"max"`
	Min            *AccountPoint `json:"min"`
	MaxDrawdown    float64       `json:"max_drawdown"`
	DrawdownPeak   *AccountPoint `json:"drawdown_peak"`
	DrawdownTrough *AccountPoint `json:"drawdown_trough"`
	Count          int           `json:"count"`
	MaxGapSeconds  float64       `json:"max_gap_seconds"`
}

// ActorMetrics は政策固有の受付/保護/利益観測の分母です。
type ActorMetrics struct {
	Rows                         int `json:"rows"`
	BadQuoteRows                 int `json:"bad_quote_rows"`
	TimerCalls                   int `json:"timer_calls"`
	NativeBatches                int `json:"native_batches"`
	NativeNewSignals             int `json:"native_new_signals"`
	NativeNewFills               int `json:"native_new_fills"`
	NativeCloseNotices           int `json:"native_close_notices"`
	NativeCloseFills             int `json:"native_close_fills"`
	NativeCancels                int `json:"native_cancels"`
	EntryRequests                int `json:"entry_requests"`
	EntryAcceptedQuantity        int `json:"entry_accepted_quantity"`
	CapClippedEntries            int `json:"cap_clipped_entries"`
	CapRejectedEntries           int `json:"cap_rejected_entries"`
	CancelledEntries             int `json:"cancelled_entries"`
	SourceExitRequests           int `json:"source_exit_requests"`
	ProtectionExitRequests       int `json:"protection_exit_requests"`
	EntryFills                   int `json:"entry_fills"`
	ExitFills                    int `json:"exit_fills"`
	ProtectionExitFills          int `json:"protection_exit_fills"`
	UnitPositivePositions        int `json:"unit_positive_positions"`
	WholePositivePositions       int `json:"whole_positive_positions"`
	ProtectionActivatedPositions int `json:"protection_activated_positions"`
	ActivatedClosedNegative      int `json:"activated_closed_negative"`
	UnitPositiveClosedNegative   int `json:"unit_positive_closed_negative"`
	WholePositiveClosedNegative  int `json:"whole_positive_closed_negative"`
	ATRDeferredPositions         int `json:"atr_deferred_positions"`
}

// ActualTotals は外費用を二条件に分離し、未決済を費用0へ補いません。
type ActualTotals struct {
	EntryQuantity     int     `json:"entry_quantity"`
	CloseQuantity     int     `json:"close_quantity"`
	OpenBuy           int     `json:"open_buy"`
	OpenSell          int     `json:"open_sell"`
	PendingBuy        int     `json:"pending_buy"`
	PendingSell       int     `json:"pending_sell"`
	GrossYen          float64 `json:"gross_yen"`
	FeeYen            float64 `json:"fee_yen"`
	SlipYen           float64 `json:"slip_yen"`
	GrossMinusFeeYen  float64 `json:"gross_minus_fee_yen"`
	NetYen            float64 `json:"net_yen"`
	ClosedNetYen      float64 `json:"closed_net_yen"`
	OpenEntryCostsYen float64 `json:"open_entry_costs_yen"`
}

// ActualResult は一つの独立Actorの実正本です。
type ActualResult struct {
	Session      Session            `json:"session"`
	Key          string             `json:"key"`
	Config       ActorConfig        `json:"config"`
	Orders       []ActualOrder      `json:"orders"`
	Fills        []ActualFill       `json:"fills"`
	Positions    []ActualPosition   `json:"positions"`
	SourceEvents []SourceEventTrace `json:"source_events"`
	Metrics      ActorMetrics       `json:"metrics"`
	Totals       ActualTotals       `json:"totals"`
	Account      AccountMarks       `json:"account"`
	Finished     bool               `json:"finished"`
	Complete     bool               `json:"complete"`
	Failure      string             `json:"failure"`
	StreamScope  string             `json:"stream_scope"`
}
