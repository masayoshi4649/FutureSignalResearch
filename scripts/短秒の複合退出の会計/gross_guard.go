// 由来: work/101保有失効の金融案/gross_guard.go
// 由来SHA256: be6ec8ecefc2ca77986a3ea3847cac3a88f2612bb25302c278e9c04e41635a9f
// 由来100固定金融: scripts/FAR利益化前後の保護/gross_guard.go
// 由来SHA256: 7bf0c3ad074ed009f26711b01315157a24303a74cb843a02c2f8cb5f792a23e3
package minishortfinance

import "fmt"

const GrossGuardExitReason = "費用前順行を観測した名目建値ガード"

// GrossGuardState は費用後利益flagを前倒しせず、利益前の実観測を分離します。
// Activationはgain>0かつu<=0の初回、FirstHitはその後の正常gain<=0、ProfitTransitionは旧H0の起動です。
type GrossGuardState struct {
	Activation       MTMPoint  `json:"activation"`
	FirstHit         *MTMPoint `json:"first_hit"`
	ProfitTransition *MTMPoint `json:"profit_transition"`
}

// observeGrossGuard はHGだけで費用前進行の名目床0を観測します。
//
// 引数: p(*ActualPosition)、point(MTMPoint)、issue(bool)は実残玉・正常当原行・Source後要求可否です。
// 返り値: errorは出典又は予約の不整合です。旧H0起動後はガードへ戻らず受理済み注文を保持します。
func (b *ActualBook) observeGrossGuard(p *ActualPosition, point MTMPoint, issue bool) error {
	if b.result.Config.HarvestPolicy != "HG" {
		return nil
	}
	if point.Quantity <= 0 || point.Quantity != p.Quantity || !normalActual(point.Quote) {
		return fmt.Errorf("利益前ガードの正常実残観測が不正です")
	}
	if p.ProtectionActive {
		if p.GrossGuard != nil && p.GrossGuard.ProfitTransition == nil {
			if p.Activation == nil || point.UnitNet <= 0 {
				return fmt.Errorf("HGからH0への初回利益移行が不整合です")
			}
			copy := point
			p.GrossGuard.ProfitTransition = &copy
		}
		return nil
	}
	if p.GrossGuard == nil {
		if point.GainPoints <= 0 {
			return nil
		}
		if point.UnitNet > 0 {
			return fmt.Errorf("費用後正益を利益前ガードへ渡しました")
		}
		p.GrossGuard = &GrossGuardState{Activation: point}
	}
	if p.GrossGuard.ProfitTransition != nil {
		return fmt.Errorf("HGの利益後に利益前ガードへ戻りました")
	}
	if point.GainPoints <= 0 {
		if p.GrossGuard.FirstHit == nil {
			copy := point
			p.GrossGuard.FirstHit = &copy
		}
		if issue && p.Quantity > p.Reserved {
			if point.Phase != PhaseAfterSource {
				return fmt.Errorf("HG要求はSource後だけです")
			}
			if _, err := b.requestExitTagged(p, p.Quantity-p.Reserved, point.Quote.Time, point.Quote, GrossGuardExitReason, "", "", nil, &point, nil, nil); err != nil {
				return err
			}
		}
	}
	return nil
}
