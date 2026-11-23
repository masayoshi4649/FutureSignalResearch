package far92

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"
)

type priceFixture struct {
	tracker   *PriceTracker
	records   []EventRecord
	side      int
	epoch     float64
	hist, rsi float64
}

// newPriceFixture は対称な公開値人工を開始します。
//
// 引数: side(int)は買売符号です。
// 返り値: *priceFixtureは市場を参照しない人工器具です。
func newPriceFixture(side int) *priceFixture {
	return &priceFixture{tracker: NewPriceTracker(), side: side, epoch: 100000, rsi: 50}
}

// add は一つの新しい確定足を人工器へ与えます。
//
// 引数: t(*testing.T)、x/ema(float64)は方向座標の加算値と平均です。
// 返り値: PriceDirectionは当方向snapshotです。
func (f *priceFixture) add(t *testing.T, x, ema float64) PriceDirection {
	t.Helper()
	n := len(f.records) + 1
	at := f.epoch + 180*float64(n)
	side := float64(f.side)
	v := TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true, EMA8_3: 1000 + side*ema, EMA21_3: 1000 + side*ema, EMA8_15: 1000 + side, EMA21_15: 1000, Close3: 1000 + side*x, Histogram3: f.hist + side, PreviousHistogram3: f.hist, RSI3: f.rsi + side, PreviousRSI3: f.rsi, TR3: 10, ATR3: 20, PreviousATR3: 20, Bar3End: at, Bar15End: at}
	r := EventRecord{ID: int64(n), Kind: "確定3分", Input: EventInput{Ordinal: int64(n), At: at, Origin: "three_timer", Window: "D164_15", EpochStart: f.epoch, Technical: v, Quote: Quote{Time: at - 1, Index: int64(n), Line: int64(n + 20), Last: v.Close3, Bid: v.Close3 - 5, Ask: v.Close3 + 5, Valid: true}}}
	f.hist, f.rsi = v.Histogram3, v.RSI3
	f.records = append(f.records, r)
	if err := f.tracker.Feed(r); err != nil {
		t.Fatal(err)
	}
	return f.state(t, at)
}

// state は人工の指定方向を取得します。
//
// 引数: t(*testing.T)、at(float64)は検査器と観測時計です。
// 返り値: PriceDirectionは値コピーです。
func (f *priceFixture) state(t *testing.T, at float64) PriceDirection {
	t.Helper()
	s, e := f.tracker.Snapshot(at)
	if e != nil {
		t.Fatal(e)
	}
	for _, d := range s.Directions {
		if d.Side == f.side {
			return d
		}
	}
	t.Fatal("方向が欠落")
	return PriceDirection{}
}

// complete はH95とP110の人工完成まで進めます。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: PriceDirectionは完成状態です。
func (f *priceFixture) complete(t *testing.T) PriceDirection {
	for _, p := range [][2]float64{{95, 94}, {90, 91}, {100, 99}, {110, 100}, {105, 103}} {
		f.add(t, p[0], p[1])
	}
	return f.add(t, 111, 104)
}

// TestPriceFirstPointsAndMirror は点の最初性と同値更新を検証します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPriceFirstPointsAndMirror(t *testing.T) {
	for _, side := range []int{1, -1} {
		f := newPriceFixture(side)
		for _, p := range [][2]float64{{95, 94}, {90, 91}, {100, 99}, {110, 100}, {105, 103}, {106, 103}, {104, 103}, {104, 103}, {110, 103}} {
			d := f.add(t, p[0], p[1])
			if d.Resume != nil {
				t.Fatal("P未越過で完成")
			}
		}
		d := f.add(t, 111, 104)
		if !d.TriggerValid || d.Reclaim.ObservationID != 3 || d.Peak.Point.ObservationID != 4 || d.Hold.ObservationID != 7 || d.Resume.ObservationID != 10 || d.High.Point.ObservationID != 1 {
			t.Fatalf("点不正 %+v", d)
		}
		before := *d.Resume
		f.add(t, 112, 105)
		after := f.state(t, f.records[len(f.records)-1].Input.At)
		if *after.Resume != before {
			t.Fatal("続伸でvが若返った")
		}
		c := f.tracker.Counts()
		if c.FreshImpulses != 1 || c.Episodes != 1 || c.Reclaims != 1 || c.PeakUpdates != 1 || c.Holds != 1 || c.HoldUpdates != 1 || c.Resumes != 1 {
			t.Fatal(c)
		}
	}
}

// TestPriceRolloverAndBrokenV は競合の優先順と隠し復活禁止を検証します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPriceRolloverAndBrokenV(t *testing.T) {
	for _, side := range []int{1, -1} {
		f := newPriceFixture(side)
		v := *f.complete(t).Resume
		d := f.add(t, 94, 95)
		if d.ImpulseOrigin != "completed_v" || *d.Impulse != v || d.Pullback.ObservationID != 7 || d.High.Point.ObservationID != 6 || d.Resume != nil {
			t.Fatal(d)
		}
		g := newPriceFixture(side)
		g.complete(t)
		d = g.add(t, 95, 94)
		if d.Resume != nil || d.Reclaim != nil {
			t.Fatal("H等号でvを保持")
		}
		d = g.add(t, 94, 94)
		if d.ImpulseOrigin != "fresh" || d.Impulse.ObservationID != 1 || d.Pullback.ObservationID != 8 {
			t.Fatal("破棄vを復活", d)
		}
		if d.High.Point.ObservationID != 6 {
			t.Fatal("更新pのHが区間全体最大でない", d)
		}
	}
}

// TestPriceTTLAndOldKRecord は旧k失効とv寿命を分離します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPriceTTLAndOldKRecord(t *testing.T) {
	f := newPriceFixture(1)
	d := f.complete(t)
	end := d.Resume.BarEnd
	before := f.tracker.Counts()
	if f.state(t, end+899.999).TriggerValid != true || f.state(t, end+900).TriggerValid || f.state(t, end+900).Resume == nil || !reflect.DeepEqual(before, f.tracker.Counts()) {
		t.Fatal("純view又は期限等号不正")
	}
	r := f.records[len(f.records)-1]
	r.ID++
	r.Input.Ordinal++
	r.Input.At += 1
	r.Kind = "期限失効"
	if err := f.tracker.Feed(r); err != nil {
		t.Fatal(err)
	}
	after := f.state(t, r.Input.At)
	if *after.Resume != *d.Resume || f.tracker.Counts().Bars != 6 {
		t.Fatal("旧k同足でstepした")
	}
	for _, p := range [][2]float64{{112, 105}, {113, 106}, {114, 107}, {115, 108}, {116, 109}} {
		f.addRecordAfterDuplicate(t, p[0], p[1])
	}
	after = f.state(t, end+900)
	if after.TriggerValid || after.Stage != "完成" || *after.Resume != *d.Resume || f.tracker.Counts().ExpiredTriggers != 1 {
		t.Fatal(after, f.tracker.Counts())
	}
	after = f.addRecordAfterDuplicate(t, 100, 101)
	if after.ImpulseOrigin != "completed_v" {
		t.Fatal("期限でvの継承が消えた")
	}
}

// addRecordAfterDuplicate は同足Record後の新足人工を作ります。
//
// 引数: t(*testing.T)、x/ema(float64)は新足の方向値です。
// 返り値: PriceDirectionは更新状態です。
func (f *priceFixture) addRecordAfterDuplicate(t *testing.T, x, ema float64) PriceDirection {
	t.Helper()
	r := f.records[len(f.records)-1]
	id := f.tracker.lastID + 1
	at := f.tracker.last.Technical.Bar3End + 180
	r.ID = id
	r.Input.Ordinal = id
	r.Input.At = at
	r.Input.Technical.Bar3End = at
	r.Input.Technical.Bar15End = at
	r.Input.Technical.PreviousHistogram3 = f.hist
	r.Input.Technical.PreviousRSI3 = f.rsi
	r.Input.Technical.Histogram3 = f.hist + float64(f.side)
	r.Input.Technical.RSI3 = f.rsi + float64(f.side)
	r.Input.Technical.Close3 = 1000 + float64(f.side)*x
	r.Input.Technical.EMA8_3 = 1000 + float64(f.side)*ema
	r.Input.Quote.Time = at - 1
	r.Input.Quote.Index = id
	r.Input.Quote.Line = id + 20
	r.Input.Quote.Last = r.Input.Technical.Close3
	f.hist, f.rsi = r.Input.Technical.Histogram3, r.Input.Technical.RSI3
	f.records = append(f.records, r)
	if err := f.tracker.Feed(r); err != nil {
		t.Fatal(err)
	}
	return f.state(t, at)
}

// TestPricePUpdateUnknownAndCopy は更新破棄、未知、保存不変を検証します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。
func TestPricePUpdateUnknownAndCopy(t *testing.T) {
	f := newPriceFixture(1)
	f.complete(t)
	snap, _ := f.tracker.Snapshot(f.tracker.last.At)
	encoded, _ := json.Marshal(snap)
	f.add(t, 100, 100)
	if after, _ := json.Marshal(snap); string(after) != string(encoded) {
		t.Fatal("既読snapshot変化")
	}
	snap.Directions[0].Impulse.ObservationID = 999
	if f.state(t, f.tracker.last.At).Impulse.ObservationID == 999 {
		t.Fatal("getter共有")
	}
	r := f.records[len(f.records)-1]
	r.ID = f.tracker.lastID + 1
	r.Input.Ordinal = r.ID
	r.Input.At++
	r.Input.Origin = "quote"
	r.Input.Quote.Last = 0
	if err := f.tracker.Feed(r); err != nil {
		t.Fatal(err)
	}
	if d := f.state(t, r.Input.At); d.Known || d.Impulse != nil || !d.RequiredUnknown {
		t.Fatal(d)
	}
	r.ID++
	r.Input.Ordinal++
	r.Input.At++
	r.Input.Technical.Close3 = math.NaN()
	if f.tracker.Feed(r) == nil {
		t.Fatal("非有限を受理")
	}
}
