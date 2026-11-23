// 由来97停止金融: scripts/FAR初回利益確定/force_boundary_test.go
// 由来SHA256: f1f1b36c1082c97364add8218418a0ea2e8e881878217c70afc70ba0fda9c1f6
// 境界人工は停止H0/旧96の公開APIだけを呼び、金融本文を複写しません。
package minirisk98_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"testing"
	"time"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	old "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	h "github.com/masayoshi4649/SessionTradeExecuter/minirisk98"
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
// 返り値: h.NativeBatchは手製Sourceの公開型。戦略計算ではありません。
func (x *source) step(q native.QuoteStamp, news []native.Signal) h.NativeBatch {
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
	return h.NativeBatch{Method: "D164_15", Delta: d}
}

// force は同時計でもfill/原行更新せず、new取消→残所有closeだけを作ります。
//
// 引数: at(float64)はSource timer時計。
// 返り値: h.NativeBatchは取消/返済要求のみの人工Force。
func (x *source) force(at float64) h.NativeBatch {
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
	return h.NativeBatch{Method: "D164_15", Delta: d}
}

type pair struct {
	book  *h.ActualBook
	prior *old.ActualBook
	cfg   h.ActorConfig
}

// books は空/H0の16口座と空設定の旧96対照8口座を作ります。
//
// 引数: t(*testing.T)、s(native.Session)は試験器と場。
// 返り値: []pairは同じ通知だけを受ける独立会計。
func books(t *testing.T, s native.Session) []pair {
	t.Helper()
	out := []pair{}
	for _, gate := range []string{"", "AB"} {
		for _, harvest := range []string{"", "H0"} {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					cfg := h.ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: gate, HarvestPolicy: harvest, SlipPts: slip, DelaySeconds: delay}
					b, err := h.NewActualBook(s, cfg)
					if err != nil {
						t.Fatal(err)
					}
					one := pair{book: b, cfg: cfg}
					if harvest == "" {
						one.prior, err = old.NewActualBook(s, old.ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: gate, SlipPts: slip, DelaySeconds: delay})
						if err != nil {
							t.Fatal(err)
						}
					}
					out = append(out, one)
				}
			}
		}
	}
	return out
}

// compare は空Harvestの全JSONを旧96へ除外0で確認します。
//
// 引数: t(*testing.T)、one(pair)、label(string)は対象と位相。
// 返り値: ありません。
func compare(t *testing.T, one pair, label string) {
	t.Helper()
	if one.prior == nil {
		return
	}
	a, _ := json.Marshal(one.book.Snapshot())
	b, _ := json.Marshal(one.prior.Snapshot())
	if !bytes.Equal(a, b) {
		t.Fatal("空Harvestの96全文差", label, one.cfg)
	}
}

// runBoundary は同時計Forceの狭い三系列だけを実行します。
//
// 引数: t(*testing.T)、side(int)、mode(string)は鏡像と境界。
// 返り値: ありません。実市場・原板・FAR生成を一切呼びません。
func runBoundary(t *testing.T, side int, mode string) {
	t.Helper()
	s := session()
	grid := s.Start + 1800
	all := books(t, s)
	src := newSource()
	idx := int64(0)
	feed := func(at, move float64, bad bool, news ...native.Signal) {
		o := observation(at, move, side, idx, bad)
		batch := src.step(stamp(o, idx+20), news)
		before, _ := json.Marshal(batch)
		for _, one := range all {
			if err := one.book.OnNativeStep(o, idx+20, []h.NativeBatch{batch}); err != nil {
				t.Fatal(mode, one.cfg, err)
			}
			if one.prior != nil {
				if err := one.prior.OnNativeStep(o, idx+20, []old.NativeBatch{{Method: batch.Method, Delta: batch.Delta}}); err != nil {
					t.Fatal(err)
				}
			}
			compare(t, one, "quote")
		}
		after, _ := json.Marshal(batch)
		if !bytes.Equal(before, after) {
			t.Fatal("入力Source変更")
		}
		idx++
	}
	quantity := 5
	if mode == "両側cap" {
		quantity = 10
	}
	news := []native.Signal{birth("主", side, quantity)}
	if mode == "両側cap" {
		news = append(news, birth("反対", -side, 10))
	}
	feed(grid-1, 0, false, news...)
	feed(grid-.9, 0, false)
	for _, one := range all {
		var gate h.EntryGate
		var oldGate old.EntryGate
		if one.cfg.GatePolicy != "" {
			gate = func(h.EntryCandidate) (h.GateDecision, error) {
				return h.GateDecision{Policy: "AB", SnapshotID: "境界人工", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
			}
			oldGate = func(old.EntryCandidate) (old.GateDecision, error) {
				return old.GateDecision{Policy: "AB", SnapshotID: "境界人工", Known: true, Allowed: true, Role: "順行", Reason: "人工許可"}, nil
			}
		}
		if err := one.book.OnEntryGridWithGate(grid, gate); err != nil {
			t.Fatal(err)
		}
		if one.prior != nil {
			if err := one.prior.OnEntryGridWithGate(grid, oldGate); err != nil {
				t.Fatal(err)
			}
		}
		compare(t, one, "grid")
	}
	forceAt := grid
	if mode != "未取得取消" {
		feed(grid, 0, false)
		feed(grid+1, 0, false)
		if mode == "部分と取消" {
			feed(grid+1, 0, false, closeSignal("部分", "玉-主", side, 2))
			feed(grid+2, 30, false, birth("取消出生", side, 5))
		} else {
			feed(grid+2, 30, false)
		}
		forceAt = grid + 2
	}
	batch := src.force(forceAt)
	input, _ := json.Marshal(batch)
	for _, one := range all {
		before := one.book.Snapshot()
		if mode != "未取得取消" && one.cfg.HarvestPolicy == "H0" {
			p := before.Positions[0]
			if !p.ProtectionActive || p.Activation == nil || p.Reserved != p.Quantity {
				t.Fatal("H予約状態不足", mode, one.cfg, p)
			}
			if mode == "両側cap" && (before.Totals.OpenBuy != 10 || before.Totals.OpenSell != 10) {
				t.Fatal("両側10未達")
			}
		}
		if err := one.book.OnNativeForce(forceAt, []h.NativeBatch{batch}); err != nil {
			t.Fatal(mode, one.cfg, err)
		}
		if one.prior != nil {
			if err := one.prior.OnNativeForce(forceAt, []old.NativeBatch{{Method: batch.Method, Delta: batch.Delta}}); err != nil {
				t.Fatal(err)
			}
		}
		after := one.book.Snapshot()
		compare(t, one, "同時計Force")
		if len(after.Fills) != len(before.Fills) || after.Account.Count != before.Account.Count || after.Metrics.Rows != before.Metrics.Rows {
			t.Fatal("Forceがfill/MTM/rawを生成")
		}
		for i, p := range after.Positions {
			a, _ := json.Marshal(p.Marks)
			b, _ := json.Marshal(before.Positions[i].Marks)
			if !bytes.Equal(a, b) {
				t.Fatal("Forceが正益点を再評価")
			}
		}
		if mode == "未取得取消" {
			if len(after.Positions) != 0 || after.Orders[0].Status != "cancelled" || after.Orders[0].CancelTime == nil || *after.Orders[0].CancelTime != forceAt {
				t.Fatal("Actual new取消", one.cfg, after.Orders)
			}
		}
		if one.cfg.HarvestPolicy == "H0" && mode != "未取得取消" {
			requested := 0
			for _, e := range after.SourceEvents[len(before.SourceEvents):] {
				if e.Kind == "close_notice" {
					if e.HoldID == "玉-主" && (e.ActualFreeBefore != 0 || e.ActualExitRequested != 0) {
						t.Fatal("H予約へ重複返済", e)
					}
					requested += e.ActualExitRequested
				}
			}
			want := 0
			if mode == "両側cap" {
				want = 10
			}
			if requested != want {
				t.Fatal("未予約反対側のForce配分", requested, want)
			}
			if mode == "部分と取消" && after.Metrics.NativeCancels != 1 {
				t.Fatal("Source new取消欠落")
			}
		}
	}
	afterInput, _ := json.Marshal(batch)
	if !bytes.Equal(input, afterInput) {
		t.Fatal("Force入力を変更")
	}
	// ----------------------------------------
	// 異常BBOはfill不可。正常な別物理行が同じ時計でもD1は+1秒まで待ちます。
	feed(forceAt, 30, true)
	for _, one := range all {
		r := one.book.Snapshot()
		if mode != "未取得取消" && r.Totals.CloseQuantity > map[bool]int{true: 2, false: 0}[mode == "部分と取消"] {
			t.Fatal("異常BBOでfill")
		}
	}
	feed(forceAt, 30, false)
	for _, one := range all {
		if one.cfg.DelaySeconds == 0 && mode != "未取得取消" {
			r := one.book.Snapshot()
			if r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 {
				t.Fatal("D0が同時計の後続正常原行で返済されない")
			}
		}
		if one.cfg.DelaySeconds == 1 && mode != "未取得取消" {
			for _, o := range one.book.Snapshot().Orders {
				if o.Kind == "exit" && o.RequestTime == forceAt && o.Status != "pending" {
					t.Fatal("同時計D1 fill")
				}
			}
		}
	}
	feed(forceAt+1, 30, false)
	for _, one := range all {
		r, err := one.book.Finish()
		if err != nil {
			t.Fatal(mode, one.cfg, err)
		}
		if one.prior != nil {
			if _, err := one.prior.Finish(); err != nil {
				t.Fatal(err)
			}
		}
		compare(t, one, "Finish")
		if !r.Complete || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 {
			t.Fatal("終了残", r.Totals)
		}
		for _, o := range r.Orders {
			if o.Status == "pending" {
				t.Fatal("終了注文予約")
			}
		}
		if mode == "未取得取消" && (len(r.Fills) != 0 || r.Totals.EntryQuantity != 0 || r.Totals.NetYen != 0) {
			t.Fatal("取消後の架空取得")
		}
		if mode == "両側cap" && r.Totals.EntryQuantity != 20 {
			t.Fatal("両側cap量")
		}
	}
	t.Logf("境界確認: 系列=%s 売買符号=%d 新口座=%d H0口座=8 旧96全文対照=8 終了残=0", mode, side, len(all))
}

// TestForce97Boundaries は三つの公開API境界を鏡像で検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。6系列×16口座、空48旧96全文比較を含みます。
func TestForce97Boundaries(t *testing.T) {
	for _, mode := range []string{"両側cap", "部分と取消", "未取得取消"} {
		for _, side := range []int{-1, 1} {
			t.Run(fmt.Sprintf("%s_%d", mode, side), func(t *testing.T) { runBoundary(t, side, mode) })
		}
	}
}
