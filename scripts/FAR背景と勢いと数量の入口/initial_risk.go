// 由来98固定金融: scripts/FAR利益前ATR追尾/initial_risk.go
// 由来SHA256: 4a12b60afb7f67d05b29626cab24f6efbeda959dffb37898da2e31431da7dd59
package minientry99

import (
	"fmt"
	"math"
)

const InitialRiskExitReason = "利益前の固定初期幅追尾"

// InitialRiskPoint は利益前床の初到達とその時の床/PeakをHから分離します。
type InitialRiskPoint struct {
	Mark      MTMPoint `json:"mark"`
	PeakGain  float64  `json:"peak_gain"`
	FloorGain float64  `json:"floor_gain"`
}

// InitialRiskState は初回実取得の幅と利益前だけの非緩和床です。
// 初期床-Widthは規定値で、HasMark=falseのPeak0は観測値として使いません。
type InitialRiskState struct {
	Policy           string            `json:"policy"`
	Multiplier       float64           `json:"multiplier"`
	Width            float64           `json:"width"`
	ATRKnown         bool              `json:"atr_known"`
	ATRValue         float64           `json:"atr_value"`
	ATRAvailable     float64           `json:"atr_available"`
	ATRNominal       float64           `json:"atr_nominal"`
	EntryQuote       QuoteStamp        `json:"entry_quote"`
	PeakGain         float64           `json:"peak_gain"`
	HasMark          bool              `json:"has_mark"`
	PeakUpdated      *MTMPoint         `json:"peak_updated"`
	FloorGain        float64           `json:"floor_gain"`
	FloorUpdated     *InitialRiskPoint `json:"floor_updated"`
	FirstHit         *InitialRiskPoint `json:"first_hit"`
	ProfitTransition *MTMPoint         `json:"profit_transition"`
}

// lockInitialRisk は最初実取得時のATR又は未知125ptを一度だけ固定します。
//
// 引数: p(*ActualPosition)、o(Observation)、q(QuoteStamp)は新実玉と取得原行です。
// 返り値: errorは政策/幅/出典の不整合です。後でATRが既知になっても再固定しません。
func (b *ActualBook) lockInitialRisk(p *ActualPosition, o Observation, q QuoteStamp) error {
	policy := b.result.Config.RiskPolicy
	if policy == "" {
		return nil
	}
	if p.InitialRisk != nil {
		return fmt.Errorf("初期riskの幅を二度固定しようとしました")
	}
	multiplier := 1.0
	if policy == "R05" {
		multiplier = 0.5
	} else if policy != "R10" {
		return fmt.Errorf("初期risk政策が不正です")
	}
	if err := validateATR(o); err != nil {
		return err
	}
	width := 125.0
	if o.ATR > 0 {
		width = math.Max(20, math.Min(125, multiplier*o.ATR))
	}
	if !finiteActual(width) || width < 20 || width > 125 {
		return fmt.Errorf("初期risk幅が不正です")
	}
	p.InitialRisk = &InitialRiskState{Policy: policy, Multiplier: multiplier, Width: width, ATRKnown: o.ATR > 0, ATRValue: o.ATR, ATRAvailable: o.E01.ATRAvailable, ATRNominal: o.E01.ATRNominal, EntryQuote: q, FloorGain: -width}
	return nil
}

// observeInitialRisk は正常MTM二phaseで利益前床を観測し、Source後の未予約分だけ要求します。
//
// 引数: p(*ActualPosition)、point(MTMPoint)、issue(bool)は実残玉/当行評価/追加要求可否です。
// 返り値: errorはrisk状態/金融要求の不整合です。利益後は旧Hへ移り戻りません。
func (b *ActualBook) observeInitialRisk(p *ActualPosition, point MTMPoint, issue bool) error {
	if b.result.Config.RiskPolicy == "" {
		return nil
	}
	risk := p.InitialRisk
	if risk == nil || risk.Policy != b.result.Config.RiskPolicy || risk.Width < 20 || risk.Width > 125 {
		return fmt.Errorf("初期riskの取得時固定がありません")
	}
	if p.ProtectionActive {
		if risk.ProfitTransition == nil {
			copy := point
			risk.ProfitTransition = &copy
		}
		return nil
	}
	if risk.ProfitTransition != nil {
		return fmt.Errorf("利益移行後に初期riskへ戻りました")
	}
	if !risk.HasMark || point.GainPoints > risk.PeakGain {
		risk.PeakGain = point.GainPoints
		copy := point
		risk.PeakUpdated = &copy
	}
	risk.HasMark = true
	floor := math.Max(-risk.Width, math.Max(risk.PeakGain-risk.Width, risk.FloorGain))
	if !finiteActual(floor) {
		return fmt.Errorf("初期risk床が非有限です")
	}
	if floor > risk.FloorGain {
		risk.FloorGain = floor
		copy := InitialRiskPoint{Mark: point, PeakGain: risk.PeakGain, FloorGain: floor}
		risk.FloorUpdated = &copy
	}
	if point.GainPoints <= floor {
		copy := InitialRiskPoint{Mark: point, PeakGain: risk.PeakGain, FloorGain: floor}
		if risk.FirstHit == nil {
			risk.FirstHit = &copy
		}
		if issue && p.Quantity > p.Reserved {
			if point.Phase != PhaseAfterSource {
				return fmt.Errorf("初期risk要求がSource後ではありません")
			}
			trigger := InitialRiskPoint{Mark: point, PeakGain: risk.PeakGain, FloorGain: floor}
			if _, err := b.requestExit(p, p.Quantity-p.Reserved, point.Quote.Time, point.Quote, InitialRiskExitReason, "", "", nil, &trigger); err != nil {
				return err
			}
		}
	}
	return nil
}
