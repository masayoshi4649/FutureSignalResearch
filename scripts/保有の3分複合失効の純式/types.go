// Package minix5 は保有専用X5の公開状態判定だけを提供します。
package minix5

import (
	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	legacy96 "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// TechnicalGateInput は固定96と同じ公開入力型で、Source/指標を生成しません。
type TechnicalGateInput = legacy96.TechnicalGateInput

// TechnicalGateCheck は固定96と同じ4欄の値を保有側の名前付き型で保存します。
type TechnicalGateCheck struct {
	ID     string `json:"id"`
	Known  bool   `json:"known"`
	Passed bool   `json:"passed"`
	Reason string `json:"reason"`
}

// HeldDecision は純技法の成立であり、金融の起動済み/未予約量を保証しません。
type HeldDecision struct {
	Policy     string  `json:"policy"`
	SnapshotID string  `json:"snapshot_id"`
	At         float64 `json:"at"`
	Side       int     `json:"side"`
	Known      bool    `json:"known"`
	Allowed    bool    `json:"allowed"`
	Role       string  `json:"role"`
	Reason     string  `json:"reason"`
}

// CurrentQuoteEvidence はCurrentの出典を保存し、未提供のQuoteOKを作りません。
type CurrentQuoteEvidence struct {
	Reference   string  `json:"reference"`
	Time        float64 `json:"time"`
	Received    float64 `json:"received"`
	SourceIndex int64   `json:"source_index"`
	SourceLine  int64   `json:"source_line"`
	Last        float64 `json:"last"`
	Bid         float64 `json:"bid"`
	Ask         float64 `json:"ask"`
}

// QuantityEvidence はDay OFI又はNight四成分の出典と元定義を区別します。
type QuantityEvidence struct {
	Kind       string   `json:"kind"`
	Known      bool     `json:"known"`
	Time       float64  `json:"time"`
	Index      int64    `json:"index"`
	OwnAt      float64  `json:"own_at"`
	Value      *float64 `json:"value"`
	BidRefill  *float64 `json:"bid_refill"`
	AskRefill  *float64 `json:"ask_refill"`
	BidDeplete *float64 `json:"bid_deplete"`
	AskDeplete *float64 `json:"ask_deplete"`
}

// HeldEvidence は使用値と公開時計を凍結し、未知の式値はnullにします。
type HeldEvidence struct {
	SceneID              string                    `json:"scene_id"`
	Contract             string                    `json:"contract"`
	Current              CurrentQuoteEvidence      `json:"current"`
	PriceAge             *float64                  `json:"price_age"`
	ThreeAge             *float64                  `json:"three_age"`
	Three                chartwarmup96.BarEvidence `json:"three"`
	Quantity             QuantityEvidence          `json:"quantity"`
	SignedCloseEMA       *float64                  `json:"signed_close_ema"`
	SignedHistogramDelta *float64                  `json:"signed_histogram_delta"`
	SignedQuantity       *float64                  `json:"signed_quantity"`
}

// HeldAssessment は個別品質/三反対と純判断を返す値型です。
type HeldAssessment struct {
	Decision HeldDecision         `json:"decision"`
	Checks   []TechnicalGateCheck `json:"checks"`
	Evidence HeldEvidence         `json:"evidence"`
}
