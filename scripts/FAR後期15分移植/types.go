package far80

// Quote は実売買模型で利用するNK225ラージの当時気配です。
// Indexは時計採用NK原行の連番、Lineは原JSONLの行番号です。
// Last不正もIndexを進め、元特徴器のSourceIndexとは分離し、未来へ補完しません。
// ValidはBookでは正常BBO、TechnicalBankへ渡す独立複写ではLastの可用性を表します。
type Quote struct {
	Time  float64 `json:"time"`
	Index int64   `json:"index"`
	Line  int64   `json:"line"`
	Last  float64 `json:"last"`
	Bid   float64 `json:"bid"`
	Ask   float64 `json:"ask"`
	Valid bool    `json:"valid"`
}

// ReferenceLot は元三手法を仮想運転した時点で生きている玉です。
// IDは参照側HoldIDで、内部政策IDや別参照会計の損益を実損益へ混ぜません。
type ReferenceLot struct {
	ID         string  `json:"id"`
	InternalID string  `json:"internal_id"`
	Parent     string  `json:"parent"`
	SourceID   string  `json:"source_id"`
	Method     string  `json:"method"`
	Owner      string  `json:"owner"`
	Kind       string  `json:"kind"`
	Side       int     `json:"side"`
	Quantity   int     `json:"quantity"`
	Entry      float64 `json:"entry"`
	At         float64 `json:"at"`
	Closing    bool    `json:"closing"`
}

// ReferenceClose は当行に元手法が発した参照玉への返済通知です。
// Beforeは先行する未約定返済予約と同原行の先行通知を引いた参照未通知残量です。
// 実側は未予約残量へQuantity/Beforeを掛け、末尾全残通知では未予約全量を返します。
type ReferenceClose struct {
	ID          string `json:"id"`
	ReferenceID string `json:"reference_id"`
	Before      int    `json:"before"`
	Quantity    int    `json:"quantity"`
	Reason      string `json:"reason"`
}

// ReferenceFrame は全原行を進めた参照会計の現在状態です。
type ReferenceFrame struct {
	Lots   []ReferenceLot   `json:"lots"`
	Closes []ReferenceClose `json:"closes"`
}

// TechnicalView は確定足だけから作った複合判断の現在値です。
// Knownの区別を保ち、不足した数値の0を観測として採用しません。
type TechnicalView struct {
	TrendKnown         bool    `json:"trend_known"`
	ReversalKnown      bool    `json:"reversal_known"`
	SpikeKnown         bool    `json:"spike_known"`
	ExitKnown          bool    `json:"exit_known"`
	ATRKnown           bool    `json:"atr_known"`
	EMA8_3             float64 `json:"ema8_3"`
	EMA21_3            float64 `json:"ema21_3"`
	EMA8_15            float64 `json:"ema8_15"`
	EMA21_15           float64 `json:"ema21_15"`
	RSI3               float64 `json:"rsi3"`
	PreviousRSI3       float64 `json:"previous_rsi3"`
	Histogram3         float64 `json:"histogram3"`
	PreviousHistogram3 float64 `json:"previous_histogram3"`
	Close3             float64 `json:"close3"`
	TR3                float64 `json:"tr3"`
	ATR3               float64 `json:"atr3"`
	PreviousATR3       float64 `json:"previous_atr3"`
	Bar3End            float64 `json:"bar3_end"`
	Bar15End           float64 `json:"bar15_end"`
}

// Trade はViewer互換の実所有に対する一つの約定片です。
// FeeYenは手数料と主想定滑りの合計で、参照仮想約定ではありません。
type Trade struct {
	ID         string  `json:"id"`
	Timestamp  string  `json:"timestamp"`
	Type       string  `json:"type"`
	PositionID string  `json:"position_id"`
	Price      float64 `json:"price"`
	Quantity   int     `json:"qty"`
	FeeYen     float64 `json:"fee_yen"`
	MethodID   string  `json:"method_id"`
	SourceLine int64   `json:"source_line"`
	Reason     string  `json:"reason"`
}
