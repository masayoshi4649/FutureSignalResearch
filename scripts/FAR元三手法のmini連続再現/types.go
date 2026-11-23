// Package mininative は元三手法の連続通知を同じ商品会計へ約定します。
// 残玉を別の新規建玉へ再取得せず、元判断の費用は0、外費用は別台帳です。
package mininative

import "github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"

type Observation = strategy.Observation
type Session = strategy.Session
type Signal = strategy.Signal
type Fill = strategy.Fill

// ProductConfig は新miniと固定micro対照の規格と外費用を区別します。
type ProductConfig struct {
	Product          string  `json:"product"`
	CoreQuantity     int     `json:"core_quantity"`
	ExtraMaxQuantity int     `json:"extra_max_quantity"`
	Cap              int     `json:"cap"`
	PointValue       float64 `json:"point_value"`
	LargeTick        float64 `json:"large_tick"`
	FeeYenPerSide    float64 `json:"fee_yen_per_side"`
	SlippagePoints   float64 `json:"slippage_points"`
}

// MiniConfig は親の指定したmini10枚と税込片道費用を返します。
//
// 引数: ありません。
// 返り値: ProductConfigはmini5+5/上限10/点価100/片道38.5円/滑り5ptです。
func MiniConfig() ProductConfig {
	return ProductConfig{"NK225mini", 5, 5, 10, 100, 10, 38.5, 5}
}

// MicroControlConfig は固定87Sourceと同じmicro100枚の対照を返します。
//
// 引数: ありません。
// 返り値: ProductConfigはmicro50+50/上限100/点価10/片道11円/滑り5ptです。
func MicroControlConfig() ProductConfig {
	return ProductConfig{"NK225micro", 50, 50, 100, 10, 10, 11, 5}
}

// QuoteStamp は元特徴連番と物理行を分け、約定したBBOを保持します。
type QuoteStamp struct {
	Time       float64 `json:"time"`
	Index      int64   `json:"index"`
	SourceLine int64   `json:"source_line"`
	Last       float64 `json:"last"`
	Bid        float64 `json:"bid"`
	Ask        float64 `json:"ask"`
	QuoteOK    bool    `json:"quote_ok"`
}

// CloseNotice は旧Referenceの返済要求と同じ所有ID/予約前残量です。
type CloseNotice struct {
	ID          string `json:"id"`
	ReferenceID string `json:"reference_id"`
	Before      int    `json:"before"`
	Quantity    int    `json:"quantity"`
	Reason      string `json:"reason"`
}

// SignalRecord は元の全Signalと要求時計/当時気配を値保存します。
type SignalRecord struct {
	Signal Signal     `json:"signal"`
	Origin string     `json:"origin"`
	At     float64    `json:"at"`
	Quote  QuoteStamp `json:"quote"`
}

// CloseAllocation は同じHoldIDの返済片と往復外費用を記録します。
type CloseAllocation struct {
	HoldID           string     `json:"hold_id"`
	Quantity         int        `json:"quantity"`
	EntryPrice       float64    `json:"entry_price"`
	ExitPrice        float64    `json:"exit_price"`
	EntryQuote       QuoteStamp `json:"entry_quote"`
	ExitQuote        QuoteStamp `json:"exit_quote"`
	GrossYen         float64    `json:"gross_yen"`
	EntryFeeYen      float64    `json:"entry_fee_yen"`
	ExitFeeYen       float64    `json:"exit_fee_yen"`
	EntrySlippageYen float64    `json:"entry_slippage_yen"`
	ExitSlippageYen  float64    `json:"exit_slippage_yen"`
	NetYen           float64    `json:"net_yen"`
}

// FillRecord は全実Fillを費用0の元会計通知と外費用に分けます。
// NetContributionYenは新規時に片道費用だけ控除し、返済時に粗益と返済費用を反映します。
type FillRecord struct {
	Fill               Fill              `json:"fill"`
	Action             string            `json:"action"`
	Side               int               `json:"side"`
	Quote              QuoteStamp        `json:"quote"`
	GrossYen           float64           `json:"gross_yen"`
	FeeYen             float64           `json:"fee_yen"`
	SlippageYen        float64           `json:"slippage_yen"`
	NetContributionYen float64           `json:"net_contribution_yen"`
	Allocations        []CloseAllocation `json:"allocations"`
}

// Cancellation は実約定しなかった新規予約の終了通知です。
type Cancellation struct {
	SignalID string     `json:"signal_id"`
	At       float64    `json:"at"`
	Quote    QuoteStamp `json:"quote"`
	Reason   string     `json:"reason"`
}

// HoldLedger は取得された一つのHoldIDの履歴と現在残量です。
type HoldLedger struct {
	HoldID          string     `json:"hold_id"`
	InternalID      string     `json:"internal_id"`
	EntryID         string     `json:"entry_id"`
	Parent          string     `json:"parent"`
	SourceID        string     `json:"source_id"`
	Kind            string     `json:"kind"`
	Side            int        `json:"side"`
	InitialQuantity int        `json:"initial_quantity"`
	Quantity        int        `json:"quantity"`
	ClosedQuantity  int        `json:"closed_quantity"`
	EntryPrice      float64    `json:"entry_price"`
	EntryQuote      QuoteStamp `json:"entry_quote"`
	GrossYen        float64    `json:"gross_yen"`
	ClosedNetYen    float64    `json:"closed_net_yen"`
}

// LedgerTotals は実Fillだけから算出した総額です。
// 元FARとの比較はGrossYen、今回の費用後評価はNetYenを使います。
type LedgerTotals struct {
	EntryQuantity       int     `json:"entry_quantity"`
	CloseQuantity       int     `json:"close_quantity"`
	OpenBuyQuantity     int     `json:"open_buy_quantity"`
	OpenSellQuantity    int     `json:"open_sell_quantity"`
	PendingBuyQuantity  int     `json:"pending_buy_quantity"`
	PendingSellQuantity int     `json:"pending_sell_quantity"`
	GrossYen            float64 `json:"gross_yen"`
	FeeYen              float64 `json:"fee_yen"`
	SlippageYen         float64 `json:"slippage_yen"`
	GrossMinusFeeYen    float64 `json:"gross_minus_fee_yen"`
	NetYen              float64 `json:"net_yen"`
	ClosedNetYen        float64 `json:"closed_net_yen"`
	OpenEntryCostsYen   float64 `json:"open_entry_costs_yen"`
}

// StepResult は今回の要求/約定/取消だけを返し、先行原行へ書き戻しません。
type StepResult struct {
	At            float64        `json:"at"`
	Origin        string         `json:"origin"`
	SourceLine    int64          `json:"source_line"`
	Signals       []SignalRecord `json:"signals"`
	Fills         []FillRecord   `json:"fills"`
	Cancellations []Cancellation `json:"cancellations"`
	Closes        []CloseNotice  `json:"closes"`
}

// Ledger は連続運転の全履歴と終了残を保存する外台帳です。
// Sourceの仮想判断へこの台帳の費用後額を戻しません。
type Ledger struct {
	Method        string         `json:"method"`
	Session       Session        `json:"session"`
	Config        ProductConfig  `json:"config"`
	Signals       []SignalRecord `json:"signals"`
	Fills         []FillRecord   `json:"fills"`
	Cancellations []Cancellation `json:"cancellations"`
	Holds         []HoldLedger   `json:"holds"`
	Pending       []Signal       `json:"pending"`
	Totals        LedgerTotals   `json:"totals"`
	Forced        bool           `json:"forced"`
	ForcedAt      float64        `json:"forced_at"`
	Finished      bool           `json:"finished"`
	Complete      bool           `json:"complete"`
	Failure       string         `json:"failure"`
}
