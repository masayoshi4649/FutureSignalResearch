// Package minishortexit は現在の短秒進行と数量を使う保有専用純式です。
package minishortexit

import (
	"fmt"
	"math"

	x5 "github.com/masayoshi4649/SessionTradeExecuter/minix5"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

type TechnicalGateInput = x5.TechnicalGateInput
type HeldDecision = x5.HeldDecision
type TechnicalGateCheck = x5.TechnicalGateCheck

// ShortEvidence は公称窓と実両端・速度を保存し、未知の方向値をnullにします。
type ShortEvidence struct {
	Known       bool                     `json:"known"`
	Window      far82.CurrentShortWindow `json:"window"`
	SignedSpeed *float64                 `json:"signed_speed"`
}

// Evidence は純式の現在出典を保存し、私有所有や起動を捏造しません。
type Evidence struct {
	SceneID        string                  `json:"scene_id"`
	Contract       string                  `json:"contract"`
	Current        x5.CurrentQuoteEvidence `json:"current"`
	PriceAge       *float64                `json:"price_age"`
	ShortTime      float64                 `json:"short_time"`
	ShortMid       float64                 `json:"short_mid"`
	Five           ShortEvidence           `json:"five"`
	Fifteen        ShortEvidence           `json:"fifteen"`
	Quantity       x5.QuantityEvidence     `json:"quantity"`
	SignedQuantity *float64                `json:"signed_quantity"`
}

// Assessment は政策ごとの必要checkだけと全現在根拠を返します。
type Assessment struct {
	Decision HeldDecision         `json:"decision"`
	Checks   []TechnicalGateCheck `json:"checks"`
	Evidence Evidence             `json:"evidence"`
}

// number は入力と共有しない既知の数値を作ります。
//
// 引数: v(float64)は有限な数値です。
// 返り値: *float64は独立した値です。
func number(v float64) *float64 { return &v }

// shortWindow は元窓の単位と両端を検査し、使用可能な方向速度を作ります。
//
// 引数: w(CurrentShortWindow)、c(CurrentEvidence)、h(float64)、side(int)、currentKnown(bool)です。
// 返り値: ShortEvidence/errorは当時の窓か、既知窓の単位/時計破損です。
func shortWindow(w far82.CurrentShortWindow, c far82.CurrentEvidence, h float64, side int, currentKnown bool) (ShortEvidence, error) {
	e := ShortEvidence{Window: w}
	if w.Known {
		s := c.Short
		valid := s.Time == c.Time && s.Mid > 0 && s.Mid == c.Bid+(c.Ask-c.Bid)/2 &&
			w.Elapsed >= h && w.Elapsed == s.Time-w.Endpoint && w.Endpoint <= s.Time-h &&
			w.Delay == w.Elapsed-h && w.Delay >= 0 && w.Delay <= 15 &&
			math.Abs(w.Speed-w.Move/w.Elapsed) <= 1e-12*math.Max(1, math.Abs(w.Speed))
		if !valid {
			return e, fmt.Errorf("既知の%.0f秒窓の単位/両端が不整合です", h)
		}
		e.Known = currentKnown
		if e.Known {
			e.SignedSpeed = number(float64(side) * w.Speed)
		}
	}
	return e, nil
}

// check は未知を不成立や0と区別する一条件を作ります。
//
// 引数: id/reason(string)、known/passed(bool)は条件と既知性です。
// 返り値: TechnicalGateCheckは未知ならPassed=falseの値です。
func check(id string, known, passed bool, reason string) TechnicalGateCheck {
	return TechnicalGateCheck{ID: id, Known: known, Passed: known && passed, Reason: reason}
}

// AssessShortExit はS5Q/S515Qを計算し、旧X5の採否・金融状態を使用しません。
//
// 引数: input(TechnicalGateInput)、side(int)は公開contextと実保有方向、policy(string)はS5Q/S515Qです。
// 返り値: Assessment/errorは個別根拠/純判断、又は公開値の破損です。
func AssessShortExit(input TechnicalGateInput, side int, policy string) (Assessment, error) {
	if policy != "S5Q" && policy != "S515Q" {
		return Assessment{}, fmt.Errorf("短秒退出政策が不正です")
	}
	base, err := x5.AssessHeldTechnicalExit(input, side)
	if err != nil {
		return Assessment{}, err
	}
	if len(base.Checks) != 5 || base.Checks[0].ID != "X5.現在価格時計" {
		return Assessment{}, fmt.Errorf("固定X5の公開品質型が変わりました")
	}
	currentKnown := base.Checks[0].Known && base.Checks[0].Passed
	five, err := shortWindow(input.Current.Short.Five, input.Current, 5, side, currentKnown)
	if err != nil {
		return Assessment{}, err
	}
	fifteen, err := shortWindow(input.Current.Short.Fifteen, input.Current, 15, side, currentKnown)
	if err != nil {
		return Assessment{}, err
	}
	q := base.Evidence
	e := Evidence{SceneID: q.SceneID, Contract: q.Contract, Current: q.Current, PriceAge: q.PriceAge,
		ShortTime: input.Current.Short.Time, ShortMid: input.Current.Short.Mid, Five: five, Fifteen: fifteen, Quantity: q.Quantity, SignedQuantity: q.SignedQuantity}
	checks := []TechnicalGateCheck{
		check("S.現在価格時計", currentKnown, true, "正常なCurrentの価格時計15秒以内。金融最新Quoteへの外部bindは別責務"),
		check("S.5秒速度", five.Known, five.Known && *five.SignedSpeed < 0, "実両端が既知の保有方向付き5秒窓pt/秒がstrict負"),
	}
	if policy == "S515Q" {
		checks = append(checks, check("S.15秒速度", fifteen.Known, fifteen.Known && *fifteen.SignedSpeed < 0, "実両端が既知の保有方向付き15秒窓pt/秒がstrict負"))
	}
	checks = append(checks, check("S.現在量", q.Quantity.Known, q.Quantity.Known && *q.SignedQuantity < 0, "同Current出典の保有方向付きDay OFI30又はNight E08四量差がstrict負"))
	known, passed := true, true
	for _, c := range checks {
		known = known && c.Known
		if c.Known && !c.Passed {
			passed = false
		}
	}
	if !passed {
		known = true
	}
	allowed := known && passed
	d := HeldDecision{Policy: policy, SnapshotID: input.SnapshotID, At: input.At, Side: side, Known: known, Allowed: allowed, Role: "短秒複合失効", Reason: "短秒進行と現在量が保有方向へ反対"}
	if !known {
		d.Role, d.Reason = "判定不能", "既知の否定条件はなく必要な短秒又は現在量が未知"
	} else if !allowed {
		d.Role, d.Reason = "追加退出なし", "公開済みの必要条件が不成立"
	}
	return Assessment{Decision: d, Checks: checks, Evidence: e}, nil
}
