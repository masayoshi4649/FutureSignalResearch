// 由来: work/101保有失効の金融案/source_fixture_test.go
// 由来SHA256: 6bbbe0453de24ff2f4148a1896d88df8f49773143a591876002c02422fd3de2a
// 由来100固定金融: scripts/FAR利益化前後の保護/source_fixture_test.go
// 由来SHA256: 658b386ff7c0571c2e4454464599cd1f3774baf3f93c11099f126e14bb1596a1
// 手製Source器具由来99: scripts/FAR背景と勢いと数量の入口/source_fixture_test.go
// 由来SHA256: 7a58320ccbf8f94839080705d9d6d908f79dfa4adbe20c4e001f5535bed0f7fd
// 手製Source器具由来: scripts/FAR利益前ATR追尾/force_boundary_test.go
// 由来SHA256: 484ff14932f5cac66bc8b7abb838361f9c2fe4eba9c214d6ade5530dca18d941
package minishortfinance

import (
	"encoding/json"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	"sort"
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
