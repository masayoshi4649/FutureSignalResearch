// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/confirm.go
// 87派生元SHA256: 388ec3ce27286c00994a5d98b4cb63b122bf30863edd7b131a1dce7ddc0652a6

package far87

import "fmt"

const (
	ConfirmRuleVersion            = 1
	ConfirmExitReason             = "保持帯両気配1tick・短秒反対確認"
	confirmPriceNotBreachedReason = "保持帯両気配1tick否定は未成立"
	confirmShortUnknownReason     = "保持帯両気配1tick成立・短秒未知"
	confirmNotOpposedReason       = "保持帯両気配1tick成立・短秒の両反対は不成立"
)

// ConfirmCounts は全fill後の正常残玉原行を、価格否定と短秒既知性の5群へ分けます。
// PriceNotBreachedは両気配否定条件の不成立であり、片側も維持されたとの意味ではありません。
type ConfirmCounts struct {
	NormalQuotes                 int `json:"normal_quotes"`
	PriceNotBreachedShortKnown   int `json:"price_not_breached_short_known"`
	PriceNotBreachedShortUnknown int `json:"price_not_breached_short_unknown"`
	PriceBreachedShortUnknown    int `json:"price_breached_short_unknown"`
	PriceBreachedNotOpposed      int `json:"price_breached_not_opposed"`
	Confirmed                    int `json:"confirmed"`
}

// ConfirmEvidence は要求時凍結帯に対する当原行の両気配・短秒確認を値保存します。
// FeatureIndexとQuoteIndexは別の番号で、Shortの端点時計を原板物理行番号と偽って保存しません。
type ConfirmEvidence struct {
	RuleVersion   int          `json:"rule_version"`
	At            float64      `json:"at"`
	QuoteIndex    int64        `json:"quote_index"`
	SourceLine    int64        `json:"source_line"`
	FeatureIndex  int64        `json:"feature_index"`
	SourceTime    float64      `json:"source_time"`
	Received      float64      `json:"received"`
	Last          float64      `json:"last"`
	Bid           float64      `json:"bid"`
	Ask           float64      `json:"ask"`
	Short         CurrentShort `json:"short"`
	PriceBreached bool         `json:"price_breached"`
	ShortKnown    bool         `json:"short_known"`
	Opposed       bool         `json:"opposed"`
	Confirmed     bool         `json:"confirmed"`
	Reason        string       `json:"reason"`
}

// SetConfirmEnabled は最初のQuote/Gridより前に複合確認だけを有効・無効へ設定します。
//
// 引数: enabled(bool)は複合退出確認の有効化です。
// 返り値: errorは稼働後の変更又は旧保持帯床との併用です。失敗時は設定を変えません。
func (b *Book) SetConfirmEnabled(enabled bool) error {
	if enabled && b.sourcePolicy != "" {
		return fmt.Errorf("Source会計へ複合確認を追加できません")
	}
	if b.haveQuote || b.haveGrid {
		return fmt.Errorf("複合確認の有効化は最初の気配・定時より前だけ可能です")
	}
	if enabled && b.holdEnabled {
		return fmt.Errorf("複合確認と保持帯固定床は併用できません")
	}
	b.confirmEnabled = enabled
	return nil
}

// validateConfirmQuote は複合確認の正常実保有・既知新規待機で将来BBOの格子を検査します。
//
// 引数: q(Quote)はfill前の当原行です。
// 返り値: errorは保持帯比較に用いる正常気配が10pt格子と不整合の場合、その他はnilです。
func (b *Book) validateConfirmQuote(q Quote) error {
	if !b.confirmEnabled || !actualNormal(q) {
		return nil
	}
	relevant := false
	for _, p := range b.lots {
		relevant = relevant || p.Quantity > 0 && p.HoldAnchor.Known
	}
	for _, o := range b.orders {
		relevant = relevant || o.Kind == "entry" && o.Remaining > 0 && o.HoldAnchor.Known
	}
	if relevant && (!holdGrid(q.Bid) || !holdGrid(q.Ask)) {
		return fmt.Errorf("複合確認の正常保有・新規待機気配が10pt格子と不整合")
	}
	return nil
}

// confirmShortValid は真の未知と既知窓の単位・端点の不整合を区別します。
//
// 引数: w(CurrentShortWindow)、short(CurrentShort)、horizon(float64)は元窓と5又は15秒の尺度です。
// 返り値: errorは非有限値又はKnown=trueの時計・速度矛盾です。正常なKnown=falseはnilです。
func confirmShortValid(w CurrentShortWindow, short CurrentShort, horizon float64) error {
	for _, x := range []float64{w.Move, w.Speed, w.Elapsed, w.Endpoint, w.Delay} {
		if !actualFinite(x) {
			return fmt.Errorf("複合確認の短秒値が有限ではありません")
		}
	}
	if !w.Known {
		return nil
	}
	valid := w.Elapsed >= horizon && w.Elapsed == short.Time-w.Endpoint && w.Endpoint <= short.Time-horizon && w.Delay == w.Elapsed-horizon && w.Delay >= 0 && w.Delay <= 15
	if valid {
		valid = w.Speed == w.Move/w.Elapsed
	}
	if !valid {
		return fmt.Errorf("既知の複合確認短秒が単位・有限性・両端時計と不整合")
	}
	return nil
}

// confirmationEvidence は正常残玉に対し同原行出典と要求時固定帯から一つの確認値を作ります。
//
// 引数: p(*ActualLot)、q(Quote)、current(*CurrentEvidence)は実所有・当原行・当原行特徴です。
// 返り値: ConfirmEvidenceは価格と短秒の結合、errorは接続欠落・出典矛盾・既知窓不整合です。
func confirmationEvidence(p *ActualLot, q Quote, current *CurrentEvidence) (ConfirmEvidence, error) {
	if current == nil {
		return ConfirmEvidence{}, fmt.Errorf("正常残玉の当原行特徴がありません")
	}
	if !actualNormal(q) || !actualFinite(q.Last) || q.Last <= 0 || q.Index < 0 || q.Line <= 0 || !holdGrid(q.Bid) || !holdGrid(q.Ask) {
		return ConfirmEvidence{}, fmt.Errorf("複合確認の当原行気配・格子が不正")
	}
	c := current
	if c.Reference != "NK225" || !actualFinite(c.Time) || !actualFinite(c.Received) || c.Time != q.Time || c.Received != q.Time || c.SourceLine != q.Line || c.SourceIndex < 0 || c.Last != q.Last || c.Bid != q.Bid || c.Ask != q.Ask {
		return ConfirmEvidence{}, fmt.Errorf("複合確認の特徴と気配が同じ物理原行ではありません")
	}
	short := c.Short
	if !actualFinite(short.Time) || !actualFinite(short.Mid) || short.Time != q.Time || short.Mid <= 0 || short.Mid != q.Bid+(q.Ask-q.Bid)/2 {
		return ConfirmEvidence{}, fmt.Errorf("複合確認の短秒時計・中央価格と当原行が不整合")
	}
	if err := confirmShortValid(short.Five, short, 5); err != nil {
		return ConfirmEvidence{}, err
	}
	if err := confirmShortValid(short.Fifteen, short, 15); err != nil {
		return ConfirmEvidence{}, err
	}
	anchor := p.HoldAnchor
	if !anchor.Known || (p.Side != 1 && p.Side != -1) || anchor.Side != p.Side || !holdGrid(anchor.HoldBid) || !holdGrid(anchor.HoldAsk) || anchor.HoldBid >= anchor.HoldAsk || anchor.Tick != HoldTick {
		return ConfirmEvidence{}, fmt.Errorf("複合確認の要求時凍結帯・方向が不整合")
	}
	// ----------------------------------------
	// 保持帯線をFloorへ入れず、両気配の否定と両短秒の反対を一つの条件にします。
	s := float64(p.Side)
	price := s*(q.Bid-anchor.HoldBid) <= -HoldTick && s*(q.Ask-anchor.HoldAsk) <= -HoldTick
	known := short.Five.Known && short.Fifteen.Known
	opposed := known && s*short.Five.Speed < 0 && s*short.Fifteen.Speed < 0
	confirmed := price && opposed
	reason := confirmPriceNotBreachedReason
	if price {
		switch {
		case !known:
			reason = confirmShortUnknownReason
		case !opposed:
			reason = confirmNotOpposedReason
		default:
			reason = ConfirmExitReason
		}
	}
	return ConfirmEvidence{RuleVersion: ConfirmRuleVersion, At: q.Time, QuoteIndex: q.Index, SourceLine: q.Line, FeatureIndex: c.SourceIndex, SourceTime: c.Time, Received: c.Received,
		Last: q.Last, Bid: q.Bid, Ask: q.Ask, Short: short, PriceBreached: price, ShortKnown: known, Opposed: opposed, Confirmed: confirmed, Reason: reason}, nil
}

// count は一つの正常残玉原行を相互排他的な5群のちょうど一つへ加えます。
//
// 引数: evidence(ConfirmEvidence)は当原行の検査済み確認です。
// 返り値: ありません。NormalQuotesと5群合計を同時に増やします。
func (c *ConfirmCounts) count(evidence ConfirmEvidence) {
	c.NormalQuotes++
	switch {
	case !evidence.PriceBreached && evidence.ShortKnown:
		c.PriceNotBreachedShortKnown++
	case !evidence.PriceBreached:
		c.PriceNotBreachedShortUnknown++
	case !evidence.ShortKnown:
		c.PriceBreachedShortUnknown++
	case !evidence.Opposed:
		c.PriceBreachedNotOpposed++
	default:
		c.Confirmed++
	}
}

// observeConfirmation は旧保護とG1部分利確の後で確認を観測し未予約残量だけを要求します。
//
// 引数: p(*ActualLot)、q(Quote)、current(*CurrentEvidence)は全fill後の正常残玉と当原行特徴です。
// 返り値: errorは出典又は既知短秒の不整合です。確定証拠と先行片を後から書き換えません。
func (b *Book) observeConfirmation(p *ActualLot, q Quote, current *CurrentEvidence) error {
	evidence, err := confirmationEvidence(p, q, current)
	if err != nil {
		return err
	}
	p.ConfirmCounts.count(evidence)
	b.metrics.ConfirmCounts.count(evidence)
	if evidence.PriceBreached && p.ConfirmFirstPriceBreach == nil {
		copy := evidence
		p.ConfirmFirstPriceBreach = &copy
	}
	if evidence.PriceBreached && !evidence.ShortKnown && p.ConfirmFirstUnknown == nil {
		copy := evidence
		p.ConfirmFirstUnknown = &copy
	}
	if !evidence.Confirmed {
		return nil
	}
	if p.ConfirmFirstConfirmed == nil {
		copy := evidence
		p.ConfirmFirstConfirmed = &copy
		b.metrics.ConfirmConfirmedLots++
	}
	b.metrics.ConfirmExitObligations++
	before := len(b.orders)
	b.requestExit(p, p.Quantity-p.ReservedExit, q.Time, q, ConfirmExitReason)
	if len(b.orders) > before {
		copy := evidence
		b.orders[len(b.orders)-1].ConfirmEvidence = &copy
	}
	if missing := p.Quantity - p.ReservedExit; missing > 0 {
		b.metrics.ConfirmMissingQuantity += missing
	}
	return nil
}
