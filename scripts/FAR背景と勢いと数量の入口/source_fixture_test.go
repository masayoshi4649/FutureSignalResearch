// 手製Source器具由来: scripts/FAR利益前ATR追尾/force_boundary_test.go
// 由来SHA256: 484ff14932f5cac66bc8b7abb838361f9c2fe4eba9c214d6ade5530dca18d941
package minientry99

import (
	"encoding/json"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	"sort"
	"testing"
	"time"
)

type source struct {
	pending             []native.Signal
	qty, reserved, side map[string]int
	entry               map[string]float64
	entryQuote          map[string]native.QuoteStamp
	last                native.QuoteStamp
}

// newSource はFARを実行しない手製の公開通知器具を作ります。
//
// 引数: なし。
// 返り値: *sourceはSource予約/所有だけを持つ人工です。
func newSource() *source {
	return &source{qty: map[string]int{}, reserved: map[string]int{}, side: map[string]int{}, entry: map[string]float64{}, entryQuote: map[string]native.QuoteStamp{}}
}

// session は時計だけを持つ人工Dayを返します。
//
// 引数: なし。
// 返り値: native.Sessionは実原板へ接続しない場です。
func session() native.Session {
	start := float64(time.Date(2026, 9, 21, 8, 45, 0, 0, time.FixedZone("JST", 32400)).Unix())
	return native.Session{ID: "2026-09-21_Day", Kind: "Day", Start: start, End: start + 25200, ForceClose: start + 24600, ExtraAt: start + 13500}
}

// observation は符号反転した有限気配と手製ATRを作ります。
//
// 引数: at/move(float64)、side(int)、index(int64)、bad(bool)は人工原行。
// 返り値: native.Observationはscalarだけの入力です。
func observation(at, move float64, side int, index int64, bad bool) native.Observation {
	bid, ask := 1000+move, 1010+move
	if side < 0 {
		bid, ask = 2000-ask, 2000-bid
	}
	o := native.Observation{Reference: "NK225", Time: at, Received: at, Index: index, Last: (bid + ask) / 2, Bid: bid, Ask: ask, QuoteOK: !bad, ATR: 20}
	if bad {
		o.Bid, o.Ask = 0, 0
	}
	o.E01.ATR, o.E01.ATRAvailable, o.E01.ATRNominal = 20, at-50, at-100
	return o
}

// stamp はNative Features番号と物理行を分けて複写します。
//
// 引数: o(native.Observation)、line(int64)は人工当原行。
// 返り値: native.QuoteStampは元時計のままの値です。
func stamp(o native.Observation, line int64) native.QuoteStamp {
	return native.QuoteStamp{Time: o.Time, Index: o.Index, SourceLine: line, Last: o.Last, Bid: o.Bid, Ask: o.Ask, QuoteOK: o.QuoteOK}
}

// birth は型付きEvidenceを持つmini出生を作ります。
//
// 引数: id(string)、side/quantity(int)は元ID/方向/量。
// 返り値: native.Signalは後原行約定を待つ人工new。
func birth(id string, side, quantity int) native.Signal {
	e, _ := json.Marshal(map[string]any{"kind": "initial", "parent": "親-" + id, "source_id": "元-" + id, "method": "NK225_D164_15", "quantity_micro": quantity * 10})
	return native.Signal{ID: id, Action: "new", Owner: "episode", Side: side, Quantity: quantity, Evidence: e, Reason: "人工出生"}
}

// closeSignal は実在するSource所有を部分返済します。
//
// 引数: id/hold(string)、side/quantity(int)は通知と元所有。
// 返り値: native.SignalはSource closeです。
func closeSignal(id, hold string, side, quantity int) native.Signal {
	return native.Signal{ID: id, Action: "close", Owner: "episode", Side: -side, Quantity: quantity, Reason: "人工Source返済", Targets: []strategy.LotTarget{{ID: hold, Quantity: quantity}}}
}

// appendSignal は要求時の未通知残へCloseNoticeを結びます。
//
// 引数: d(*native.StepResult)、s(native.Signal)、at(float64)、q(native.QuoteStamp)は配送位相。
// 返り値: ありません。入力に未来fillを加えません。
func (x *source) appendSignal(d *native.StepResult, s native.Signal, at float64, q native.QuoteStamp) {
	s.Time, s.SourceIndex = at, q.Index
	if s.Action == "close" {
		for _, target := range s.Targets {
			before := x.qty[target.ID] - x.reserved[target.ID]
			if target.Quantity > before {
				panic("人工予約超過")
			}
			d.Closes = append(d.Closes, native.CloseNotice{ID: s.ID + "|" + target.ID, ReferenceID: target.ID, Before: before, Quantity: target.Quantity, Reason: s.Reason})
			x.reserved[target.ID] += target.Quantity
		}
	}
	d.Signals = append(d.Signals, native.SignalRecord{Signal: s, At: at, Origin: d.Origin, Quote: q})
	x.pending = append(x.pending, s)
}

// step は先行Source要求を次正常原行でだけfillし、その後に新Signalを受け付けます。
//
// 引数: q(native.QuoteStamp)、news([]native.Signal)は当行と新通知。
// 返り値: NativeBatchは手製Sourceの公開型。戦略計算ではありません。
func (x *source) step(q native.QuoteStamp, news []native.Signal) NativeBatch {
	d := native.StepResult{At: q.Time, Origin: "quote", SourceLine: q.SourceLine, Signals: []native.SignalRecord{}, Fills: []native.FillRecord{}, Cancellations: []native.Cancellation{}, Closes: []native.CloseNotice{}}
	left := []native.Signal{}
	for _, s := range x.pending {
		if !q.QuoteOK || q.Bid <= 0 || q.Ask <= q.Bid || q.Index <= s.SourceIndex || q.Time < s.Time {
			left = append(left, s)
			continue
		}
		price := q.Bid
		if s.Side > 0 {
			price = q.Ask
		}
		f := native.FillRecord{Fill: native.Fill{SignalID: s.ID, ExecutionID: "約定-" + s.ID, Quantity: s.Quantity, Price: price, Time: q.Time, Fee: 0}, Action: s.Action, Side: s.Side, Quote: q, FeeYen: float64(s.Quantity) * 38.5, SlippageYen: float64(s.Quantity) * 500, Allocations: []native.CloseAllocation{}}
		if s.Action == "new" {
			id := "玉-" + s.ID
			f.Fill.HoldID = id
			x.qty[id], x.side[id], x.entry[id], x.entryQuote[id] = s.Quantity, s.Side, price, q
		} else {
			f.Fill.Closed = append([]strategy.LotTarget{}, s.Targets...)
			for _, target := range s.Targets {
				if target.Quantity > x.qty[target.ID] || target.Quantity > x.reserved[target.ID] {
					panic("人工fill超過")
				}
				x.qty[target.ID] -= target.Quantity
				x.reserved[target.ID] -= target.Quantity
				gross := float64(x.side[target.ID]) * (price - x.entry[target.ID]) * float64(target.Quantity) * 100
				fee, slip := float64(target.Quantity)*38.5, float64(target.Quantity)*500
				f.GrossYen += gross
				f.Allocations = append(f.Allocations, native.CloseAllocation{HoldID: target.ID, Quantity: target.Quantity, EntryPrice: x.entry[target.ID], EntryQuote: x.entryQuote[target.ID], ExitPrice: price, ExitQuote: q, GrossYen: gross, EntryFeeYen: fee, ExitFeeYen: fee, EntrySlippageYen: slip, ExitSlippageYen: slip, NetYen: gross - 2*fee - 2*slip})
			}
		}
		f.NetContributionYen = f.GrossYen - f.FeeYen - f.SlippageYen
		d.Fills = append(d.Fills, f)
	}
	x.pending = left
	for _, s := range news {
		x.appendSignal(&d, s, q.Time, q)
	}
	x.last = q
	return NativeBatch{Method: "D164_15", Delta: d}
}

// force は同時計でもfill/原行更新せず、new取消→残所有closeだけを作ります。
//
// 引数: at(float64)はSource timer時計。
// 返り値: NativeBatchは取消/返済要求のみの人工Force。
func (x *source) force(at float64) NativeBatch {
	d := native.StepResult{At: at, Origin: "timer", Signals: []native.SignalRecord{}, Fills: []native.FillRecord{}, Cancellations: []native.Cancellation{}, Closes: []native.CloseNotice{}}
	left := []native.Signal{}
	for _, s := range x.pending {
		if s.Action == "new" {
			d.Cancellations = append(d.Cancellations, native.Cancellation{SignalID: s.ID, At: at, Quote: x.last, Reason: "人工Force取消"})
		} else {
			left = append(left, s)
		}
	}
	x.pending = left
	ids := []string{}
	for id := range x.qty {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		free := x.qty[id] - x.reserved[id]
		if free > 0 {
			x.appendSignal(&d, closeSignal("Force-"+id, id, x.side[id], free), at, x.last)
		}
	}
	return NativeBatch{Method: "D164_15", Delta: d}
}

// Test99CapacityBothSides は片側10の予約込み上限と反対側余力を公開APIで確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Source器具は手製通知のみで、FAR戦略/価格入力は読みません。
func Test99CapacityBothSides(t *testing.T) {
	for _, side := range []int{-1, 1} {
		for _, policy := range []string{"", "E3", "E3S"} {
			for _, cost := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					s := session()
					grid := s.Start + 1800
					b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", GatePolicy: policy, SlipPts: cost, DelaySeconds: delay})
					if err != nil {
						t.Fatal(err)
					}
					x := newSource()
					index := int64(0)
					feed := func(at float64, signals ...native.Signal) {
						o := observation(at, 0, side, index, false)
						q := stamp(o, index+20)
						batch := x.step(q, signals)
						if err := b.OnNativeStep(o, index+20, []NativeBatch{batch}); err != nil {
							t.Fatal(err)
						}
						index++
					}
					callGrid := func(at float64) {
						var callback EntryGate
						if policy != "" {
							callback = func(c EntryCandidate) (GateDecision, error) {
								a, err := AssessEntryTechnical(context99(c, "正常"), c, policy)
								d := a.Decision
								return GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, err
							}
						}
						if err := b.OnEntryGridWithGate(at, callback); err != nil {
							t.Fatal(err)
						}
					}
					feed(grid-1, birth("同側先行", side, 8), birth("反対先行", -side, 10))
					feed(grid - .9)
					callGrid(grid)
					if b.available(side) != 2 || b.available(-side) != 0 {
						t.Fatal("新規予約だけで余力を二重使用")
					}
					feed(grid)
					feed(grid + 1)
					feed(grid+299, birth("同側追加", side, 5), birth("反対超過", -side, 1))
					feed(grid + 299.1)
					callGrid(grid + 300)
					r := b.Snapshot()
					if r.EntryOpportunities[2].Requested != 2 || r.EntryOpportunities[3].Requested != 0 || b.available(side) != 0 || b.available(-side) != 0 {
						t.Fatal("min又は両側上限", r.EntryOpportunities)
					}
					feed(grid + 300)
					feed(grid + 301)
					feed(grid+302, closeSignal("Source部分", "玉-同側先行", side, 3))
					if b.available(side) != 0 {
						t.Fatal("返済予約を所有から先引きして余力を増やした")
					}
					feed(grid + 303)
					before := b.Snapshot()
					if err := b.OnNativeForce(s.ForceClose, []NativeBatch{x.force(s.ForceClose)}); err != nil {
						t.Fatal(err)
					}
					if len(before.Fills) != len(b.Snapshot().Fills) {
						t.Fatal("Force同時fill")
					}
					feed(s.ForceClose)
					feed(s.ForceClose + 1)
					final, err := b.Finish()
					if err != nil {
						t.Fatal(err)
					}
					if !final.Complete || final.Totals.EntryQuantity != 20 || final.Totals.CloseQuantity != 20 || final.Totals.OpenBuy != 0 || final.Totals.OpenSell != 0 || final.Metrics.CapClippedEntries != 1 || final.Metrics.CapRejectedEntries != 1 {
						t.Fatal("容量/最終所有", final.Totals, final.Metrics)
					}
				}
			}
		}
	}
}
