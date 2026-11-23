package far92

import (
	"encoding/json"
	"fmt"
)

// PricePoolEvaluation は元・基礎・最終供給の順位と既知性を分けます。
type PricePoolEvaluation struct {
	ReferenceID      string `json:"reference_id"`
	Side             int    `json:"side"`
	RawRank          int    `json:"raw_rank"`
	BaseSuppliedRank *int   `json:"base_supplied_rank"`
	SuppliedRank     *int   `json:"supplied_rank"`
	BaseAllowed      bool   `json:"base_allowed"`
	OldE0Allowed     bool   `json:"old_e0_allowed"`
	OldE1Allowed     bool   `json:"old_e1_allowed"`
	Known            bool   `json:"known"`
	Allowed          bool   `json:"allowed"`
	RequiredUnknown  bool   `json:"required_unknown"`
	Reason           string `json:"reason"`
}

// PriceSupply は外政策ごとの全poolと最終供給IDです。
type PriceSupply struct {
	Policy      string                `json:"policy"`
	BasePolicy  string                `json:"base_policy"`
	SuppliedIDs []string              `json:"supplied_ids"`
	Pool        []PricePoolEvaluation `json:"pool"`
}

// PriceDecision は旧gridを書き換えない追加定時記録です。
type PriceDecision struct {
	At       float64                `json:"at"`
	Snapshot PriceSnapshot          `json:"snapshot"`
	Policies map[string]PriceSupply `json:"policies"`
}

// PriceEntryBinding は全四会計の受理と独立価格根拠を結びます。
type PriceEntryBinding struct {
	BookKey              string                   `json:"book_key"`
	Policy               string                   `json:"policy"`
	BasePolicy           string                   `json:"base_policy"`
	DelaySeconds         int                      `json:"delay_seconds"`
	EntryOrderID         string                   `json:"entry_order_id"`
	PositionID           string                   `json:"position_id"`
	ReferenceID          string                   `json:"reference_id"`
	At                   float64                  `json:"at"`
	RequestedQuantity    int                      `json:"requested_quantity"`
	RawRank              int                      `json:"raw_rank"`
	BaseSuppliedRank     int                      `json:"base_supplied_rank"`
	SuppliedRank         int                      `json:"supplied_rank"`
	SourceMethod         string                   `json:"source_method"`
	SourceAt             float64                  `json:"source_at"`
	SourceIndex          int64                    `json:"source_index"`
	PoolEvaluation       PricePoolEvaluation      `json:"pool_evaluation"`
	CurrentQualification EntryDirectionEvaluation `json:"current_qualification"`
	PriceQualification   PriceDirection           `json:"price_qualification"`
}

// validatePriceSnapshot は金融へ供給する直前の公開時刻と構造を検査します。
//
// 引数: snapshot(PriceSnapshot)は独立器の当時値です。
// 返り値: errorは未来点・非有限値・期限旗や点順の不整合です。
func validatePriceSnapshot(snapshot PriceSnapshot) error {
	if !priceFinite(snapshot.At, snapshot.EpochStart) || snapshot.At <= 0 || snapshot.EpochStart < 0 || snapshot.EpochStart > snapshot.At || len(snapshot.Directions) != 2 {
		return fmt.Errorf("独立価格snapshot時計が不正です")
	}
	seen := map[int]bool{}
	for _, d := range snapshot.Directions {
		if (d.Side != 1 && d.Side != -1) || seen[d.Side] || d.Known == d.RequiredUnknown {
			return fmt.Errorf("独立価格snapshot方向が不正です")
		}
		seen[d.Side] = true
		for _, p := range []*EventPoint{d.Impulse, d.Pullback, d.Reclaim, d.Hold, d.Resume} {
			if p != nil && (p.ObservationID <= 0 || !priceFinite(p.BarEnd, p.PublishedAt) || p.BarEnd <= snapshot.EpochStart || p.BarEnd > p.PublishedAt || p.PublishedAt > snapshot.At) {
				return fmt.Errorf("独立価格snapshotの点が未来又は別窓です")
			}
		}
		for _, l := range []*PriceLevel{d.High, d.Low, d.Peak} {
			if l != nil && (!priceFinite(l.Close, l.Point.BarEnd, l.Point.PublishedAt) || l.Close <= 0 || l.Point.ObservationID <= 0 || l.Point.BarEnd <= snapshot.EpochStart || l.Point.BarEnd > l.Point.PublishedAt || l.Point.PublishedAt > snapshot.At) {
				return fmt.Errorf("独立価格snapshotの価格出典が不正です")
			}
		}
		if d.Resume == nil {
			if d.ExpiresAt != nil || d.TriggerValid {
				return fmt.Errorf("vなしの期限旗です")
			}
			continue
		}
		if d.Impulse == nil || d.Pullback == nil || d.Reclaim == nil || d.Peak == nil || d.Hold == nil || d.High == nil || d.Low == nil || !(d.Impulse.BarEnd < d.Pullback.BarEnd && d.Pullback.BarEnd < d.Reclaim.BarEnd && d.Reclaim.BarEnd <= d.Peak.Point.BarEnd && d.Peak.Point.BarEnd < d.Hold.BarEnd && d.Hold.BarEnd < d.Resume.BarEnd) || d.ExpiresAt == nil || !priceFinite(*d.ExpiresAt) || *d.ExpiresAt != d.Resume.BarEnd+900 {
			return fmt.Errorf("独立価格snapshotの完成順序又は期限が不正です")
		}
		expected := d.Known && priceActive(snapshot.Window) && snapshot.At >= d.Resume.PublishedAt && snapshot.At >= d.Resume.BarEnd && snapshot.At < *d.ExpiresAt
		if d.TriggerValid != expected {
			return fmt.Errorf("独立価格snapshotの期限判定が不整合です")
		}
	}
	return nil
}

// FilterPriceEntry はH0旧E1、H1現在E0と独立価格triggerの全poolを評価します。
//
// 引数: policy(string)はH0/H1、grid(GridDecision)は旧当時値、snapshot(PriceSnapshot)は独立公開値です。
// 返り値: ReadSnapshot/PriceSupply/errorは独立供給コピー、全候補記録又は矛盾です。
func FilterPriceEntry(policy string, grid GridDecision, snapshot PriceSnapshot) (ReadSnapshot, PriceSupply, error) {
	base := "E1"
	if policy == "H1" {
		base = "E0"
	} else if policy != "H0" {
		return ReadSnapshot{}, PriceSupply{}, fmt.Errorf("独立価格政策が不正です")
	}
	out, oldPool, err := FilterEntry(base, grid.Source, grid.Entry)
	supply := PriceSupply{Policy: policy, BasePolicy: base, SuppliedIDs: []string{}, Pool: []PricePoolEvaluation{}}
	if err != nil {
		return out, supply, err
	}
	if err = validatePriceSnapshot(snapshot); err != nil {
		return out, supply, err
	}
	if snapshot.At != grid.At || len(snapshot.Directions) != 2 {
		return out, supply, fmt.Errorf("独立価格の当定時出典が不整合です")
	}
	directions := map[int]PriceDirection{}
	current := map[int]EntryDirectionEvaluation{}
	for _, d := range snapshot.Directions {
		if (d.Side != 1 && d.Side != -1) || directions[d.Side].Side != 0 || d.Known == d.RequiredUnknown {
			return out, supply, fmt.Errorf("独立価格の方向/既知性が不正です")
		}
		directions[d.Side] = d
	}
	for _, d := range grid.Entry.Directions {
		current[d.Side] = d
	}
	byID := map[string]ReadLot{}
	for _, r := range out.Lots {
		byID[r.Reference.ID] = r
	}
	out.Lots = []ReadLot{}
	for _, p := range oldPool {
		d, now := directions[p.Side], current[p.Side]
		check := PricePoolEvaluation{ReferenceID: p.ReferenceID, Side: p.Side, RawRank: p.RawRank, BaseSuppliedRank: p.SuppliedRank, BaseAllowed: p.Allowed, OldE0Allowed: now.E0Allowed, OldE1Allowed: now.E1Allowed, Known: p.Known, Allowed: p.Allowed, RequiredUnknown: p.RequiredUnknown, Reason: p.Reason}
		if policy == "H1" {
			check.Known = p.Known && d.Known
			check.RequiredUnknown = !check.Known
			bbo := grid.Entry.QuoteTime <= grid.At && grid.C0.Base.Quote.Valid && grid.C0.Base.Quote.Bid > 0 && grid.C0.Base.Quote.Ask > grid.C0.Base.Quote.Bid
			above := d.High != nil && bbo && float64(p.Side)*grid.C0.Base.Quote.Bid > float64(p.Side)*d.High.Close && float64(p.Side)*grid.C0.Base.Quote.Ask > float64(p.Side)*d.High.Close
			check.Allowed = p.Allowed && d.Known && d.TriggerValid && above
			check.Reason = "独立価格trigger又は現在価格帯が不成立"
			if check.RequiredUnknown {
				check.Reason = "現在資格又は独立価格の必要値が未知"
			} else if !p.Allowed {
				check.Reason = "現在E0資格が既知不成立"
			} else if check.Allowed {
				check.Reason = "現在E0と独立価格triggerと両気配維持が成立"
			}
		}
		if check.Allowed && grid.ClockAllowed {
			row, ok := byID[p.ReferenceID]
			if !ok {
				return out, supply, fmt.Errorf("許可候補が基礎供給に存在しません")
			}
			out.Lots = append(out.Lots, row)
			rank := len(out.Lots)
			check.SuppliedRank = &rank
			supply.SuppliedIDs = append(supply.SuppliedIDs, p.ReferenceID)
		}
		supply.Pool = append(supply.Pool, check)
	}
	return out, supply, nil
}

// bindPriceEntry は旧金融の受理後に新外bindingを不変コピーします。
//
// 引数: key/mode(string)、delay(int)、grid(GridDecision)、price(PriceDecision)は会計と当定時です。
// 返り値: errorは受理・候補・順位・根拠の不整合です。
func (r *replayRuntime) bindPriceEntry(key, mode string, delay int, grid GridDecision, price PriceDecision) error {
	book := r.books[key].Result()
	if len(book.Decisions) == 0 {
		return fmt.Errorf("金融判断がありません")
	}
	last := book.Decisions[len(book.Decisions)-1]
	if last.At != grid.At {
		return fmt.Errorf("金融時計が当定時と不一致です")
	}
	if last.Action != "新規要求" {
		return nil
	}
	policy := mode[:2]
	supply := price.Policies[policy]
	var order *ActualOrder
	for i := range book.Orders {
		o := &book.Orders[i]
		if o.Kind == "entry" && o.RequestTime == grid.At {
			if order != nil {
				return fmt.Errorf("一枠に複数の新規があります")
			}
			order = o
		}
	}
	if order == nil || !grid.ClockAllowed {
		return fmt.Errorf("新規に対応する供給がありません")
	}
	var pool *PricePoolEvaluation
	for i := range supply.Pool {
		p := &supply.Pool[i]
		if p.ReferenceID == order.ReferenceID {
			pool = p
		}
	}
	if pool == nil || !pool.Allowed || pool.SuppliedRank == nil || pool.BaseSuppliedRank == nil || order.SourceEntry == nil || order.SourceEntry.Rank != *pool.SuppliedRank {
		return fmt.Errorf("新価格bindingの供給順位が不一致です")
	}
	var now EntryDirectionEvaluation
	var state PriceDirection
	for _, d := range grid.Entry.Directions {
		if d.Side == order.Side {
			now = d
		}
	}
	for _, d := range price.Snapshot.Directions {
		if d.Side == order.Side {
			state = d
		}
	}
	if now.Side == 0 || state.Side == 0 || policy == "H0" && !now.E1Allowed || policy == "H1" && (!now.E0Allowed || !state.TriggerValid) {
		return fmt.Errorf("新価格bindingの根拠が不成立です")
	}
	b := PriceEntryBinding{BookKey: key, Policy: policy, BasePolicy: supply.BasePolicy, DelaySeconds: delay, EntryOrderID: order.ID, PositionID: order.PositionID, ReferenceID: order.ReferenceID, At: grid.At, RequestedQuantity: order.Quantity, RawRank: pool.RawRank, BaseSuppliedRank: *pool.BaseSuppliedRank, SuppliedRank: *pool.SuppliedRank, SourceMethod: grid.Source.Method, SourceAt: grid.Source.At, SourceIndex: grid.Source.SourceIndex, PoolEvaluation: *pool, CurrentQualification: now, PriceQualification: state}
	encoded, err := json.Marshal(b)
	if err != nil {
		return err
	}
	var frozen PriceEntryBinding
	if err = json.Unmarshal(encoded, &frozen); err != nil {
		return err
	}
	for _, old := range r.result.PriceBindings {
		if old.BookKey == key && old.EntryOrderID == order.ID {
			return fmt.Errorf("新価格bindingが重複しています")
		}
	}
	r.result.PriceBindings = append(r.result.PriceBindings, frozen)
	return nil
}
