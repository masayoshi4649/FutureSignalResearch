// 由来97停止金融: scripts/FAR初回利益確定/actual_test.go
// 由来SHA256: 01272cb9dce6ff5c267ac9d3c68e63fc22db6ebacca6232f23f389a6822fe710
// 由来: scripts/FAR5分枠の順行反転と数量/actual_test.go
// 由来SHA256: d74976eb9fe12d5fa8a9ca2b995739cf0634328237664f47608622ca8be55066
// 由来: scripts/FAR連続出生と個別利益追尾/actual_test.go
// 由来SHA256: 32e6426376d87a2edc7a52e85bab775170066c091414c91178a1edd13fd5bb6e
package minirisk98

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

type fixtureStep94 struct {
	Observation Observation   `json:"observation"`
	SourceLine  int64         `json:"source_line"`
	Batches     []NativeBatch `json:"batches"`
}
type fixtureTimer94 struct {
	At      float64       `json:"at"`
	Batches []NativeBatch `json:"batches"`
}
type fixture94 struct {
	Session Session                 `json:"session"`
	Scope   string                  `json:"scope"`
	Steps   []fixtureStep94         `json:"steps"`
	Timers  []fixtureTimer94        `json:"timers"`
	Actors  map[string]ActualResult `json:"actors"`
}
type fixtureSource94 struct {
	orders     map[string]native.Signal
	pending    []native.Signal
	quantity   map[string]int
	reserved   map[string]int
	entry      map[string]float64
	entryQuote map[string]QuoteStamp
	side       map[string]int
	last       QuoteStamp
}

// newFixtureSource94 はSource戦略を動かさない手製API通知の器具です。
//
// 引数: ありません。
// 返り値: *fixtureSource94は予約/所有だけを持ち、FAR自然生成を主張しません。
func newFixtureSource94() *fixtureSource94 {
	return &fixtureSource94{orders: map[string]native.Signal{}, pending: []native.Signal{}, quantity: map[string]int{}, reserved: map[string]int{}, entry: map[string]float64{}, entryQuote: map[string]QuoteStamp{}, side: map[string]int{}, last: QuoteStamp{Index: -1}}
}

// session94 は原板を開かない人工の正しい場時計です。
//
// 引数: ありません。
// 返り値: Sessionは2026-09-21 DayのJST時計です。
func session94() Session {
	z := time.FixedZone("JST", 9*3600)
	start := float64(time.Date(2026, 9, 21, 8, 45, 0, 0, z).Unix())
	end := start + 7*3600
	return Session{ID: "2026-09-21_Day", Kind: "Day", Start: start, ForceClose: end - 600, End: end, ExtraAt: start + 13500}
}

// configs94 は固定12口座を市場なしで列挙します。
//
// 引数: ありません。
// 返り値: []ActorConfigは3Policy×2費用×2遅延です。
func configs94() []ActorConfig {
	out := []ActorConfig{}
	for _, p := range []string{"S0", "P0", "P1"} {
		for _, s := range []float64{0, 5} {
			for _, d := range []int{0, 1} {
				out = append(out, legacyConfig95(p, s, d))
			}
		}
	}
	return out
}

// observation94 は鏡像の原行と手製公開ATRを作ります。
//
// 引数: session(Session)、side(int)、index(int64)、seconds/move/atr(float64)は人工条件です。
// 返り値: Observationは原板生成でないAPI人工入力です。
func observation94(session Session, side int, index int64, seconds, move, atr float64) Observation {
	bid, ask := 1000+move, 1010+move
	if side < 0 {
		bid, ask = 2000-ask, 2000-bid
	}
	at := session.Start + 1800 + seconds
	o := Observation{Reference: "NK225", Time: at, Received: at, Index: index, Last: (bid + ask) / 2, Bid: bid, Ask: ask, QuoteOK: true, ATR: atr}
	o.E01.ATR = atr
	if atr > 0 {
		o.E01.ATRNominal = session.Start + 1500
		o.E01.ATRAvailable = session.Start + 1560
	}
	return o
}

// birth94 は元kind等を型付きMarshalした手製mini出生です。
//
// 引数: id(string)、side/quantity(int)は出典IDと方向/枚数です。
// 返り値: native.Signalは時刻がstep時に固定される人工newです。
func birth94(id string, side, quantity int) native.Signal {
	e := sourceEvidence{Kind: "initial", Parent: "親-" + id, SourceID: "元-" + id, Method: "NK225_D164_15", QuantityMicro: quantity * 10}
	raw, _ := json.Marshal(e)
	return native.Signal{ID: id, Action: "new", Owner: "episode", Side: side, Quantity: quantity, Reason: "人工出生", Evidence: raw}
}

// close94 はSourceの実在HoldIDにだけ向けた手製返済です。
//
// 引数: id/birth(string)、side/quantity(int)は通知と元所有です。
// 返り値: native.SignalはSource所有の反対側への返済です。
func close94(id, birth string, side, quantity int) native.Signal {
	return native.Signal{ID: id, Action: "close", Owner: "episode", Side: -side, Quantity: quantity, Reason: "人工Source返済", Targets: []strategy.LotTarget{{ID: "玉-" + birth, Quantity: quantity}}}
}

// step は手製Source通知の後原行fillだけをpublic Go型で表します。
//
// 引数: t(*testing.T)、o(Observation)、line(int64)、news([]native.Signal)、cancels([]string)は人工原行です。
// 返り値: NativeBatchはFAR戦略生成ではない全量/所有接続の人工です。
func (s *fixtureSource94) step(t *testing.T, o Observation, line int64, news []native.Signal, cancels []string) NativeBatch {
	t.Helper()
	q := quoteActual(o, line)
	d := native.StepResult{At: o.Time, Origin: "quote", SourceLine: line, Signals: []native.SignalRecord{}, Fills: []native.FillRecord{}, Cancellations: []native.Cancellation{}, Closes: []native.CloseNotice{}}
	left := []native.Signal{}
	for _, sig := range s.pending {
		if !normalActual(q) || q.Index <= sig.SourceIndex || q.Time < sig.Time {
			left = append(left, sig)
			continue
		}
		price := q.Bid
		if sig.Side > 0 {
			price = q.Ask
		}
		f := native.Fill{SignalID: sig.ID, ExecutionID: "約定-" + sig.ID, Quantity: sig.Quantity, Price: price, Time: q.Time, Fee: 0}
		fr := native.FillRecord{Fill: f, Action: sig.Action, Side: sig.Side, Quote: q, FeeYen: float64(sig.Quantity) * 38.5, SlippageYen: float64(sig.Quantity) * 500, Allocations: []native.CloseAllocation{}}
		if sig.Action == "new" {
			h := "玉-" + sig.ID
			fr.Fill.HoldID = h
			s.quantity[h] = sig.Quantity
			s.entry[h] = price
			s.entryQuote[h] = q
			s.side[h] = sig.Side
		} else {
			fr.Fill.Closed = valueCopy(sig.Targets)
			for _, target := range sig.Targets {
				if target.Quantity > s.quantity[target.ID] || target.Quantity > s.reserved[target.ID] {
					t.Fatal("人工Source過剰返済")
				}
				gross := float64(s.side[target.ID]) * (price - s.entry[target.ID]) * float64(target.Quantity) * 100
				s.quantity[target.ID] -= target.Quantity
				s.reserved[target.ID] -= target.Quantity
				fr.GrossYen += gross
				pieceFee, pieceSlip := float64(target.Quantity)*38.5, float64(target.Quantity)*500
				fr.Allocations = append(fr.Allocations, native.CloseAllocation{HoldID: target.ID, Quantity: target.Quantity, EntryPrice: s.entry[target.ID], EntryQuote: s.entryQuote[target.ID], ExitPrice: price, ExitQuote: q, GrossYen: gross, EntryFeeYen: pieceFee, ExitFeeYen: pieceFee, EntrySlippageYen: pieceSlip, ExitSlippageYen: pieceSlip, NetYen: gross - 2*pieceFee - 2*pieceSlip})
			}
		}
		fr.NetContributionYen = fr.GrossYen - fr.FeeYen - fr.SlippageYen
		d.Fills = append(d.Fills, fr)
	}
	s.pending = left
	for _, sig := range news {
		sig.Time, sig.SourceIndex = o.Time, o.Index
		if _, exists := s.orders[sig.ID]; exists {
			t.Fatal("人工Source ID重複")
		}
		s.orders[sig.ID] = sig
		if sig.Action == "close" {
			for _, target := range sig.Targets {
				before := s.quantity[target.ID] - s.reserved[target.ID]
				if target.Quantity > before {
					t.Fatal("人工Source Before不足")
				}
				d.Closes = append(d.Closes, native.CloseNotice{ID: sig.ID + "|" + target.ID, ReferenceID: target.ID, Before: before, Quantity: target.Quantity, Reason: sig.Reason})
				s.reserved[target.ID] += target.Quantity
			}
		}
		d.Signals = append(d.Signals, native.SignalRecord{Signal: sig, Origin: "quote", At: o.Time, Quote: q})
		s.pending = append(s.pending, sig)
	}
	for _, id := range cancels {
		found := false
		left = []native.Signal{}
		for _, sig := range s.pending {
			if sig.ID == id {
				found = true
				d.Cancellations = append(d.Cancellations, native.Cancellation{SignalID: id, At: o.Time, Quote: q, Reason: "人工即取消"})
			} else {
				left = append(left, sig)
			}
		}
		if !found {
			t.Fatal("人工取消が未予約")
		}
		s.pending = left
	}
	s.last = q
	return NativeBatch{Method: "D164_15", Delta: d}
}

// newActors94 は同じSourceへ別会計12本を用意します。
//
// 引数: t(*testing.T)、s(Session)は試験器と場です。
// 返り値: map[string]*ActualBookは独立した12口座です。
func newActors94(t *testing.T, s Session) map[string]*ActualBook {
	t.Helper()
	out := map[string]*ActualBook{}
	for _, cfg := range configs94() {
		b, err := NewActualBook(s, cfg)
		if err != nil {
			t.Fatal(err)
		}
		out[b.result.Key] = b
	}
	return out
}

// feed94 は同じimmutable batchを全Actorへ渡します。
//
// 引数: t(*testing.T)、actors(map[string]*ActualBook)、o(Observation)、batch(NativeBatch)は人工です。
// 返り値: fixtureStep94はGo型そのもののexport値です。
func feed94(t *testing.T, actors map[string]*ActualBook, o Observation, batch NativeBatch) fixtureStep94 {
	t.Helper()
	before, _ := json.Marshal(batch)
	for key, b := range actors {
		if err := b.OnNativeStep(o, batch.Delta.SourceLine, []NativeBatch{batch}); err != nil {
			t.Fatalf("%s:index%d:%v", key, o.Index, err)
		}
	}
	after, _ := json.Marshal(batch)
	if !reflect.DeepEqual(before, after) {
		t.Fatal("ActorがSource batchを変更")
	}
	return fixtureStep94{Observation: o, SourceLine: batch.Delta.SourceLine, Batches: []NativeBatch{batch}}
}

// finish94 は全Actorの終了残と費用会計を検査します。
//
// 引数: t(*testing.T)、actors(map[string]*ActualBook)は独立会計です。
// 返り値: map[string]ActualResultは型Marshal可能な完結結果です。
func finish94(t *testing.T, actors map[string]*ActualBook) map[string]ActualResult {
	t.Helper()
	out := map[string]ActualResult{}
	for key, b := range actors {
		r, err := b.Finish()
		if err != nil {
			t.Fatalf("%s:%v", key, err)
		}
		if !r.Complete || !r.Finished || r.Totals.NetYen != r.Totals.ClosedNetYen {
			t.Fatal("終了会計", key, r.Totals)
		}
		out[key] = r
	}
	return out
}

// wave94 はSource部分返済と2ATR到達、D1の待機を手計算します。
//
// 引数: t(*testing.T)、side(int)、unknownATR(bool)は試験器・鏡像・幅後取得です。
// 返り値: fixture94はATR/Sourceを手製と明示した実Go型結果です。
func wave94(t *testing.T, side int, unknownATR bool) fixture94 {
	t.Helper()
	session := session94()
	actors := newActors94(t, session)
	source := newFixtureSource94()
	out := fixture94{Session: session, Scope: "API人工。Source戦略生成なし、ATRは手製公開値。原板/凍結足由来ATRの証明ではない。", Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}}
	seconds := []float64{0, .5, 1, 1, 2, 2, 3, 3, 4}
	moves := []float64{0, 0, 0, 0, 30, 80, 40, 20, 0}
	for i := range seconds {
		atr := 20.0
		if unknownATR && i < 6 {
			atr = 0
		}
		o := observation94(session, side, int64(i), seconds[i], moves[i], atr)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("A", side, 5))
		}
		if i == 3 {
			news = append(news, close94("部分A", "A", side, 2))
		}
		if i == 7 {
			news = append(news, close94("全残A", "A", side, 3))
		}
		batch := source.step(t, o, int64(i+20), news, nil)
		out.Steps = append(out.Steps, feed94(t, actors, o, batch))
	}
	out.Actors = finish94(t, actors)
	for key, r := range out.Actors {
		want := 615.0
		if r.Config.SlipPts == 5 {
			want = -4385
		}
		if r.Config.Policy != "S0" && r.Config.DelaySeconds == 0 {
			want = 6615
			if r.Config.SlipPts == 5 {
				want = 1615
			}
		}
		if r.Totals.NetYen != want {
			t.Fatalf("%s:手計算額 got%g want%g", key, r.Totals.NetYen, want)
		}
		p := r.Positions[0]
		if p.Marks.FirstUnitPositive == nil || p.Marks.FirstUnitPositive.Phase != PhasePreFill || p.Marks.FirstUnitPositive.Quantity != 5 || p.ATR == nil || p.ATR.Width != 40 || p.ATR.AfterEntry != unknownATR {
			t.Fatal("初回MTM/幅出典", key, p)
		}
		if r.Config.Policy != "S0" && (p.FirstFloorHit == nil || p.Activation == nil || *p.FloorGain != 30) {
			t.Fatal("床/起動/等号", key, p)
		}
	}
	return out
}

// capCancel94 は2側20枚・D1容量差・即取消・Sourceclose前の未取得取消を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: fixture94は手製Source通知の全Actor結果です。
func capCancel94(t *testing.T) fixture94 {
	t.Helper()
	session := session94()
	actors := newActors94(t, session)
	source := newFixtureSource94()
	out := fixture94{Session: session, Scope: "API人工。Source strategyなし、ATRは公開値の手製。", Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}}
	times := []float64{0, 1, 2, 2.5, 3, 3.5, 4, 4.5}
	for i, sec := range times {
		o := observation94(session, 1, int64(i), sec, 0, 20)
		news := []native.Signal{}
		cancel := []string{}
		switch i {
		case 0:
			news = []native.Signal{birth94("買A", 1, 10), birth94("売B", -1, 10)}
		case 2:
			news = []native.Signal{close94("買A全残", "買A", 1, 10)}
		case 3:
			news = []native.Signal{birth94("買次", 1, 6), birth94("即取消", 1, 4)}
			cancel = []string{"即取消"}
		case 4:
			news = []native.Signal{close94("売B部分", "売B", -1, 5), close94("買次全残", "買次", 1, 6)}
		case 5:
			news = []native.Signal{close94("売B全残", "売B", -1, 5)}
		}
		batch := source.step(t, o, int64(i+50), news, cancel)
		out.Steps = append(out.Steps, feed94(t, actors, o, batch))
		if i == 1 {
			for _, b := range actors {
				r := b.Snapshot()
				if r.Totals.OpenBuy != 10 || r.Totals.OpenSell != 10 {
					t.Fatal("両側20", r.Key, r.Totals)
				}
			}
		}
	}
	out.Actors = finish94(t, actors)
	for key, r := range out.Actors {
		want := 26
		if r.Config.DelaySeconds == 1 {
			want = 20
			if r.Metrics.CapRejectedEntries != 1 {
				t.Fatal("D1容量差", key, r.Metrics)
			}
		}
		if r.Totals.EntryQuantity != want || r.Metrics.NativeCancels != 1 {
			t.Fatal("出生量/即取消", key, r.Totals, r.Metrics)
		}
		for _, o := range r.Orders {
			if o.Source.SignalID == "即取消" {
				t.Fatal("同原行取消を復活", key)
			}
		}
	}
	return out
}

// TestActualWaveMirror は12口座の鏡像と半円/Source部分/利益返しを検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestActualWaveMirror(t *testing.T) {
	buy, sell := wave94(t, 1, false), wave94(t, -1, true)
	for key, b := range buy.Actors {
		s := sell.Actors[key]
		if b.Totals != s.Totals {
			t.Fatal("売買対称で金額差", key, b.Totals, s.Totals)
		}
	}
}

// TestActualCapAndCancelledBirth はP/U合算と同じ口座の2側/予約上限を検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestActualCapAndCancelledBirth(t *testing.T) { _ = capCancel94(t) }

// TestExportActualFixtures は明示環境がある時だけGo型Marshalを新規保存します。
//
// 引数: MINIGRID_LEGACY_EXPORT_DIR(string環境変数)は未作成の保存先です。
// 返り値: ありません。通常試験ではskip、市場やSource戦略は実行しません。
func TestExportActualFixtures(t *testing.T) {
	dir := os.Getenv("MINIGRID_LEGACY_EXPORT_DIR")
	if dir == "" {
		t.Skip("人工exportは明示環境指定時だけ")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("出力は未作成フォルダのみ")
	}
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	for _, item := range []struct {
		name    string
		side    int
		unknown bool
	}{{"買い", 1, false}, {"売り", -1, true}} {
		v := wave94(t, item.side, item.unknown)
		data, err := json.MarshalIndent(v, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(dir, item.name+".json"), append(data, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	v := capCancel94(t)
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(dir, "両側と取消.json"), append(data, '\n'), 0644); err != nil {
		t.Fatal(err)
	}
}

// TestActualFinishAndCopies はEOF残と既読値の非遡及を検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestActualFinishAndCopies(t *testing.T) {
	s := session94()
	b, err := NewActualBook(s, legacyConfig95("P0", 0, 0))
	if err != nil {
		t.Fatal(err)
	}
	src := newFixtureSource94()
	o := observation94(s, 1, 0, 0, 0, 20)
	d := src.step(t, o, 20, []native.Signal{birth94("A", 1, 1)}, nil)
	if err = b.OnNativeStep(o, 20, []NativeBatch{d}); err != nil {
		t.Fatal(err)
	}
	if _, err = b.Finish(); err == nil {
		t.Fatal("未取得予約を成功化")
	}
	o = observation94(s, 1, 1, 1, 0, 20)
	d = src.step(t, o, 21, nil, nil)
	if err = b.OnNativeStep(o, 21, []NativeBatch{d}); err != nil {
		t.Fatal(err)
	}
	if _, err = b.Finish(); err == nil {
		t.Fatal("保有を成功化")
	}
	r := b.Snapshot()
	r.Positions[0].Quantity = 999
	r.Positions[0].ATR.Width = 999
	if b.Snapshot().Positions[0].Quantity != 1 || b.Snapshot().Positions[0].ATR.Width != 40 {
		t.Fatal("既読pointerを遡及")
	}
}

// TestPublishedATRCorruptions は公開値の非正/未来と未知を区別します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestPublishedATRCorruptions(t *testing.T) {
	s := session94()
	for _, bad := range []func(*Observation){func(o *Observation) { o.ATR = -1; o.E01.ATR = -1 }, func(o *Observation) { o.E01.ATRAvailable = o.Time + 1 }, func(o *Observation) { o.E01.ATRNominal = o.Time + 1 }, func(o *Observation) { o.E01.ATRAvailable = o.E01.ATRNominal - 1 }} {
		b, _ := NewActualBook(s, legacyConfig95("P0", 0, 0))
		src := newFixtureSource94()
		o := observation94(s, 1, 0, 0, 0, 20)
		bad(&o)
		d := src.step(t, o, 20, nil, nil)
		if b.OnNativeStep(o, 20, []NativeBatch{d}) == nil {
			t.Fatal("公開ATR破損を受理")
		}
	}
}

// TestPendingSourceCloseAndTimer は遅延new取消とtimer無評価を狭く反証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。元戦略を再生しません。
func TestPendingSourceCloseAndTimer(t *testing.T) {
	s := session94()
	b, _ := NewActualBook(s, legacyConfig95("S0", 0, 1))
	src := newFixtureSource94()
	for i, sec := range []float64{0, .1, .2} {
		o := observation94(s, 1, int64(i), sec, 0, 20)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("未取得", 1, 1))
		}
		if i == 1 {
			news = append(news, close94("早期close", "未取得", 1, 1))
		}
		d := src.step(t, o, int64(i+20), news, nil)
		if err := b.OnNativeStep(o, int64(i+20), []NativeBatch{d}); err != nil {
			t.Fatal(err)
		}
	}
	r, err := b.Finish()
	if err != nil || len(r.Fills) != 0 || r.Orders[0].Status != "cancelled" || r.Metrics.CancelledEntries != 1 {
		t.Fatal("遅延newを源close後に取得", r, err)
	}

	b, _ = NewActualBook(s, legacyConfig95("P1", 5, 0))
	src = newFixtureSource94()
	for i := int64(0); i < 2; i++ {
		o := observation94(s, 1, i, float64(i), 0, 20)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("timer玉", 1, 1))
		}
		d := src.step(t, o, i+20, news, nil)
		if err := b.OnNativeStep(o, i+20, []NativeBatch{d}); err != nil {
			t.Fatal(err)
		}
	}
	before := b.Snapshot()
	sig := close94("timer返済", "timer玉", 1, 1)
	sig.Time, sig.SourceIndex = s.ForceClose, src.last.Index
	src.orders[sig.ID] = sig
	src.pending = append(src.pending, sig)
	src.reserved["玉-timer玉"] = 1
	delta := native.StepResult{At: s.ForceClose, Origin: "timer", SourceLine: src.last.SourceLine,
		Signals: []native.SignalRecord{{Signal: sig, Origin: "timer", At: s.ForceClose, Quote: src.last}},
		Closes:  []native.CloseNotice{{ID: sig.ID + "|玉-timer玉", ReferenceID: "玉-timer玉", Before: 1, Quantity: 1, Reason: sig.Reason}}}
	if err := b.OnNativeForce(s.ForceClose, []NativeBatch{{Method: "D164_15", Delta: delta}}); err != nil {
		t.Fatal(err)
	}
	after := b.Snapshot()
	if len(after.Fills) != len(before.Fills) || after.Account.Count != before.Account.Count || after.Positions[0].Marks.Last.Quote != before.Positions[0].Marks.Last.Quote {
		t.Fatal("timerで古い価格を再評価/約定")
	}
	o := observation94(s, 1, 2, 0, 40, 20)
	o.Time, o.Received = s.ForceClose, s.ForceClose
	d := src.step(t, o, 22, nil, nil)
	if err := b.OnNativeStep(o, 22, []NativeBatch{d}); err != nil {
		t.Fatal(err)
	}
	if r, err := b.Finish(); err != nil || r.Totals.NetYen != 1923 || r.Metrics.ProtectionExitRequests != 0 || r.Positions[0].Activation.Phase != PhasePreFill {
		t.Fatal("同時計Source予約済みの初正益/完結", r, err)
	}
}

// TestClippedEntryCeil はD1で3枚だけ受理したSource10枚の返済配分を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。ceilをfloorへ置換するとこの試験は失敗します。
func TestClippedEntryCeil(t *testing.T) {
	s := session94()
	b, _ := NewActualBook(s, legacyConfig95("S0", 0, 1))
	src := newFixtureSource94()
	for i, sec := range []float64{0, 1, 2, 2.5, 3, 3.5, 4, 4.5, 5} {
		o := observation94(s, 1, int64(i), sec, 0, 20)
		news := []native.Signal{}
		switch i {
		case 0:
			news = append(news, birth94("旧7枚", 1, 7))
		case 2:
			news = append(news, close94("旧返済", "旧7枚", 1, 7))
		case 3:
			news = append(news, birth94("次10枚", 1, 10))
		case 5:
			news = append(news, close94("次部分1", "次10枚", 1, 1))
		case 6:
			news = append(news, close94("次全残9", "次10枚", 1, 9))
		}
		d := src.step(t, o, int64(i+20), news, nil)
		if err := b.OnNativeStep(o, int64(i+20), []NativeBatch{d}); err != nil {
			t.Fatal(err)
		}
	}
	r, err := b.Finish()
	if err != nil || r.Metrics.CapClippedEntries != 1 || r.Totals.EntryQuantity != 10 {
		t.Fatal(r.Metrics, r.Totals, err)
	}
	found := false
	for _, e := range r.SourceEvents {
		if e.SignalID == "次部分1" && e.Kind == "close_notice" {
			found = true
			if e.Before != 10 || e.Quantity != 1 || e.ActualFreeBefore != 3 || e.ActualExitRequested != 1 {
				t.Fatal("ceil(3/10)が1でない", e)
			}
		}
	}
	if !found {
		t.Fatal("ceil作用記録なし")
	}
}
