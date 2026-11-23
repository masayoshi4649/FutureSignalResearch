package far85

import (
	"fmt"
	"math"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

const (
	HoldKind          = "E08保持帯返済側1tick"
	HoldRuleVersion   = 1
	HoldTick          = 10.0
	HoldExitReason    = "保持帯返済側1tick否定"
	holdUnknownReason = "当時のC0候補がないため保持帯線は未使用"
	holdKnownReason   = "新規要求時点のfreshなE08同方向保持帯の返済側1tick否定"
)

// HoldAnchor は要求時に選択した保持帯の出典と、返済側1tickの固定停止価格です。
// HoldBid/Askは候補出生値、HoldTime/Index/Eventは後続確認時の値です。
// FeatureIndex/QuoteIndex/SourceLineは別の番号として保存します。
type HoldAnchor struct {
	Known        bool    `json:"known"`
	Kind         string  `json:"kind"`
	RuleVersion  int     `json:"rule_version"`
	At           float64 `json:"at"`
	Side         int     `json:"side"`
	QuoteTime    float64 `json:"quote_time"`
	QuoteIndex   int64   `json:"quote_index"`
	SourceLine   int64   `json:"source_line"`
	FeatureIndex int64   `json:"feature_index"`
	PriceEvent   int64   `json:"price_event"`
	HoldID       int     `json:"hold_id"`
	HoldSide     int     `json:"hold_side"`
	HoldBid      float64 `json:"hold_bid"`
	HoldAsk      float64 `json:"hold_ask"`
	HoldTime     float64 `json:"hold_time"`
	HoldIndex    int64   `json:"hold_index"`
	HoldEvent    int64   `json:"hold_event"`
	Tick         float64 `json:"tick"`
	StopPrice    float64 `json:"stop_price"`
	Reason       string  `json:"reason"`
}

// holdGrid は指数価格を丸めず、10pt格子の有限正値か検査します。
//
// 引数: price(float64)は保持帯又は返済側気配の価格です。
// 返り値: boolは有限正値で余りが厳密に0なら真です。
func holdGrid(price float64) bool {
	return actualFinite(price) && price > 0 && math.Mod(price, HoldTick) == 0
}

// holdBarrierValid は旧82と同じ当時までの既知点の整合を確認します。
//
// 引数: point(far81.CurrentBarrier)、current(CurrentEvidence)は回復点と当時の出典です。
// 返り値: boolは未知点又は未来・不正価格を含まない点なら真です。
func holdBarrierValid(point far81.CurrentBarrier, current CurrentEvidence) bool {
	return !point.Known || (actualFinite(point.Price) && actualFinite(point.Time) && point.Price > 0 && point.Time <= current.Time && point.Index >= 0 && point.Index <= current.SourceIndex && point.Event >= 0 && point.Event <= current.Night.PriceEvent)
}

// holdBarrierFresh は旧82の60秒・32更新の包含境界を保ちます。
//
// 引数: point(far81.CurrentBarrier)、at(float64)、event/index(int64)は当時点です。
// 返り値: boolは当時までの新鮮な既知点なら真です。
func holdBarrierFresh(point far81.CurrentBarrier, at float64, event, index int64) bool {
	return point.Known && actualFinite(point.Price) && actualFinite(point.Time) && actualFinite(at) && point.Price > 0 && point.Index >= 0 && point.Index <= index && point.Event >= 0 && point.Event <= event && point.Time <= at && at-point.Time <= 60 && event-point.Event <= 32
}

// BuildHoldAnchor はC0の当時freshな保持帯を検査し、方向別の固定停止価格を構成します。
//
// 引数: at(float64)は15分要求時計、q(Quote)は直前気配、current(CurrentEvidence)は同原行の特徴、side(int)は供給候補の±1又は不供給0です。
// 返り値: HoldAnchorは固定出典又は通常未知、errorは候補ありの未知・未来・別原行・方向・格子等の不整合です。
func BuildHoldAnchor(at float64, q Quote, current CurrentEvidence, side int) (HoldAnchor, error) {
	unknown := HoldAnchor{Kind: HoldKind, RuleVersion: HoldRuleVersion, Tick: HoldTick, Reason: holdUnknownReason}
	if !actualFinite(at) {
		return HoldAnchor{}, fmt.Errorf("保持帯の要求時計が有限ではありません")
	}
	if side == 0 {
		return unknown, nil
	}
	if side != 1 && side != -1 {
		return HoldAnchor{}, fmt.Errorf("保持帯の候補方向が不正")
	}
	if !actualFinite(at) || !actualNormal(q) || !actualFinite(q.Last) || q.Last <= 0 || q.Index < 0 || q.Line <= 0 || q.Time > at || at-q.Time > 15 || !holdGrid(q.Bid) || !holdGrid(q.Ask) {
		return HoldAnchor{}, fmt.Errorf("保持帯の要求気配・当時性・10pt格子が不正")
	}
	// ----------------------------------------
	// 現在特徴は同じ物理原行へ結び、特徴連番と気配連番は別に保持します。
	if current.Reference != "NK225" || !actualFinite(current.Time) || !actualFinite(current.Received) || current.Time != q.Time || current.Received < current.Time || current.Received > at || current.SourceLine != q.Line || current.SourceIndex < 0 || current.Last != q.Last || current.Bid != q.Bid || current.Ask != q.Ask {
		return HoldAnchor{}, fmt.Errorf("保持帯の特徴と要求気配が同じ物理原行ではありません")
	}
	n := current.Night
	h, opposite := n.Buy, n.Sell
	liquidation := q.Bid
	if side < 0 {
		h, opposite = n.Sell, n.Buy
		liquidation = q.Ask
	}
	known := n.Available && n.Known && !n.Invalid && n.Window == "E08" && n.Band.Known && n.Time == current.Time && n.Index == current.SourceIndex && n.PriceEvent >= 0 && n.Band.Index == current.SourceIndex && n.Band.StartIndex >= 0 && n.Band.StartIndex <= n.Band.Index && actualFinite(n.Band.Time) && actualFinite(n.Band.StartTime) && actualFinite(n.Time) && actualFinite(h.Time) && n.Band.Time == current.Time && n.Band.StartTime <= n.Band.Time && h.Time <= current.Time && h.Index >= 0 && h.Index <= current.SourceIndex && h.Event >= 0 && h.Event <= n.PriceEvent && holdBarrierValid(h.Barrier, current) && holdBarrierValid(h.Support, current) && holdBarrierValid(opposite.Support, current)
	s := float64(side)
	band := known && h.Active && h.Side == side && h.ID > 0 && !h.Pressured && holdGrid(h.Bid) && holdGrid(h.Ask) && h.Ask > h.Bid && at >= h.Time && at-h.Time <= 60 && n.PriceEvent-h.Event <= 32 && s*(q.Bid-h.Bid) >= 0 && s*(q.Ask-h.Ask) >= 0
	barrierFresh := holdBarrierFresh(h.Barrier, at, n.PriceEvent, current.SourceIndex)
	passed := !barrierFresh || s*(liquidation-h.Barrier.Price) >= 10
	oppositePressure := opposite.Active && opposite.QuantitySupport && holdBarrierFresh(opposite.Support, at, n.PriceEvent, current.SourceIndex) && actualFinite(opposite.Time) && at >= opposite.Time && at-opposite.Time <= 60 && opposite.Index >= 0 && opposite.Index <= current.SourceIndex && opposite.Event >= 0 && opposite.Event <= n.PriceEvent && n.PriceEvent-opposite.Event <= 32
	if !band || !passed || oppositePressure {
		return HoldAnchor{}, fmt.Errorf("供給候補のC0保持帯・反対圧力が既知成立していません")
	}
	// ----------------------------------------
	// 確認時刻の気配へ価格を移さず、保存された候補出生価格から線を構成します。
	stop := h.Bid - HoldTick
	if side < 0 {
		stop = h.Ask + HoldTick
	}
	if !holdGrid(stop) {
		return HoldAnchor{}, fmt.Errorf("保持帯の固定停止価格が有限正の10pt格子ではありません")
	}
	return HoldAnchor{Known: true, Kind: HoldKind, RuleVersion: HoldRuleVersion, At: at, Side: side, QuoteTime: q.Time, QuoteIndex: q.Index, SourceLine: q.Line,
		FeatureIndex: current.SourceIndex, PriceEvent: n.PriceEvent, HoldID: h.ID, HoldSide: h.Side, HoldBid: h.Bid, HoldAsk: h.Ask, HoldTime: h.Time, HoldIndex: h.Index, HoldEvent: h.Event, Tick: HoldTick, StopPrice: stop, Reason: holdKnownReason}, nil
}

// normalizeHoldAnchor は要求時入力から再構成した全出典値と型内の値を厳密比較します。
//
// 引数: at(float64)、q(Quote)、current(CurrentEvidence)、side(int)、anchor(HoldAnchor)は当時入力と呼出側の固定線です。
// 返り値: HoldAnchorは検査済みの値、errorは未知偽装・出典・停止式の不整合です。
func normalizeHoldAnchor(at float64, q Quote, current CurrentEvidence, side int, anchor HoldAnchor) (HoldAnchor, error) {
	expected, err := BuildHoldAnchor(at, q, current, side)
	if err != nil {
		return HoldAnchor{}, err
	}
	if anchor != expected {
		return HoldAnchor{}, fmt.Errorf("保持帯anchorが要求時の出典・方向・停止式と不整合")
	}
	return anchor, nil
}

// activateHold は実取得価格へ固定価格線の単位だけを写し、対照では活性化しません。
//
// 引数: p(*ActualLot)は新しい実所有、q(Quote)は正常な実新規約定原行です。
// 返り値: ありません。価格線Pは移動させず、初回hitは全fill後の残玉段階で記録します。
func (b *Book) activateHold(p *ActualLot, q Quote) {
	if p.HoldAnchor.Known {
		b.metrics.HoldKnownEntries++
	} else {
		b.metrics.HoldUnknownEntries++
	}
	if !b.holdEnabled || !p.HoldAnchor.Known {
		return
	}
	floor := float64(p.Side) * (p.HoldAnchor.StopPrice - p.EntryPrice)
	p.HoldActive = true
	p.HoldFloor = actualPointer(floor)
	p.HoldActivatedAt = actualPointer(q.Time)
	p.HoldEntryBreached = float64(p.Side)*(actualMark(q, p.Side)-p.HoldAnchor.StopPrice) <= 0
	b.metrics.HoldActivatedLots++
	if p.HoldEntryBreached {
		b.metrics.HoldEntryBreachedLots++
	}
}

// applyHoldFloor は旧非緩和床を別に保存してから保持帯床を重ねます。
//
// 引数: p(*ActualLot)、q(Quote)、gain(float64)は全fill後の正常残玉と現在幅です。
// 返り値: boolは保持帯床が旧床より厳密に高く、理由の優先拘束となる場合に真です。
func (b *Book) applyHoldFloor(p *ActualLot, q Quote, gain float64) bool {
	p.holdBaseFloor = p.Floor
	if !p.HoldActive {
		return false
	}
	binding := *p.HoldFloor > p.holdBaseFloor
	p.Floor = math.Max(p.Floor, *p.HoldFloor)
	if gain <= *p.HoldFloor && p.HoldFirstHitAt == nil {
		p.HoldFirstHitAt = actualPointer(q.Time)
		p.HoldFirstHitIndex = q.Index
		p.HoldFirstHitLine = q.Line
		b.metrics.HoldHitLots++
	}
	return binding
}

// validateHoldQuote は保持帯有効の実保有・待機新規がある時だけ将来気配の格子を確認します。
//
// 引数: q(Quote)は実原行です。
// 返り値: errorは保持帯比較に使用する正常BBOの格子不整合、正常又は非該当ならnilです。
func (b *Book) validateHoldQuote(q Quote) error {
	if !b.holdEnabled || !actualNormal(q) {
		return nil
	}
	relevant := false
	for _, p := range b.lots {
		relevant = relevant || p.Quantity > 0 && p.HoldActive
	}
	for _, o := range b.orders {
		relevant = relevant || o.Kind == "entry" && o.Remaining > 0 && o.HoldAnchor.Known
	}
	if relevant && (!holdGrid(q.Bid) || !holdGrid(q.Ask)) {
		return fmt.Errorf("保持帯の正常保有気配が10pt格子と不整合")
	}
	return nil
}
