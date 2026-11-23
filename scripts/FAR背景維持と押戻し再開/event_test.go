package far88

import (
	"math"
	"reflect"
	"testing"

	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

const event88Epoch = 100000.0

// event88View は方向整列を強制しない正常な公開指標人工を作ります。
//
// 引数: end/close/hist/previousHist/rsi/previousRSI(float64)は当時値です。
// 返り値: TechnicalViewは3分EMA配列だけ買いと逆の正常値です。
func event88View(end, close, hist, previousHist, rsi, previousRSI float64) far87.TechnicalView {
	return far87.TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true,
		EMA8_3: 1000, EMA21_3: 1005, EMA8_15: 1000, EMA21_15: 990, RSI3: rsi, PreviousRSI3: previousRSI,
		Histogram3: hist, PreviousHistogram3: previousHist, Close3: close, TR3: 10, ATR3: 20, PreviousATR3: 20, Bar3End: end, Bar15End: end}
}

// event88Input は公開時計と直前原行を分けたイベント入力を作ります。
//
// 引数: ordinal(int64)、v(TechnicalView)は処理順と公開足です。
// 返り値: EventInputは当時rawを先取りしない人工です。
func event88Input(ordinal int64, v far87.TechnicalView) EventInput {
	return EventInput{Ordinal: ordinal, At: v.Bar3End, Origin: "three_timer", Window: "D164_15", EpochStart: event88Epoch,
		Quote: far87.Quote{Time: v.Bar3End - 1, Index: ordinal, Line: ordinal + 1, Last: v.Close3, Bid: 1000, Ask: 1010, Valid: true}, Technical: v}
}

// event88Sequence は推進/押し/回復/確認の別足又は同足人工を返します。
//
// 引数: delayed(bool)は勢い確認を次足へ分ける指定です。
// 返り値: []EventInputは未来を含まない時間順入力です。
func event88Sequence(delayed bool) []EventInput {
	inputs := []EventInput{
		event88Input(1, event88View(event88Epoch+180, 1010, 1, 0, 51, 50)),
		event88Input(2, event88View(event88Epoch+360, 995, 0, 1, 50, 51)),
	}
	if delayed {
		inputs = append(inputs,
			event88Input(3, event88View(event88Epoch+540, 1005, -1, 0, 49, 50)),
			event88Input(4, event88View(event88Epoch+720, 1010, 0, -1, 50, 49)))
	} else {
		inputs = append(inputs, event88Input(3, event88View(event88Epoch+540, 1010, 1, 0, 51, 50)))
	}
	return inputs
}

// event88Feed は入力列を追跡器へ渡し、保存recordだけを返します。
//
// 引数: t(*testing.T)、tracker(*EventTracker)、inputs([]EventInput)は人工です。
// 返り値: []EventRecordはnilでない観測で、失敗時はテストを停止します。
func event88Feed(t *testing.T, tracker *EventTracker, inputs ...EventInput) []EventRecord {
	t.Helper()
	records := []EventRecord{}
	for _, in := range inputs {
		r, err := tracker.Observe(in)
		if err != nil {
			t.Fatal(err)
		}
		if r != nil {
			records = append(records, *r)
		}
	}
	return records
}

// event88Mirror は価格/RSI/勢いを鏡像にした同時計入力を作ります。
//
// 引数: in(EventInput)は買い人工です。
// 返り値: EventInputは売り側の同式を検査する人工です。
func event88Mirror(in EventInput) EventInput {
	v := &in.Technical
	v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = 2000-v.EMA8_3, 2000-v.EMA21_3, 2000-v.EMA8_15, 2000-v.EMA21_15
	v.Close3, v.RSI3, v.PreviousRSI3 = 2000-v.Close3, 100-v.RSI3, 100-v.PreviousRSI3
	v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
	q := &in.Quote
	q.Last, q.Bid, q.Ask = 2000-q.Last, 2000-q.Ask, 2000-q.Bid
	return in
}

// TestEvent88SequenceAndDelayedConfirmation は異なるi/p/rと同足又は後足kを確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。静的状態だけから履歴を補完しません。
func TestEvent88SequenceAndDelayedConfirmation(t *testing.T) {
	for _, delayed := range []bool{false, true} {
		tracker := NewEventTracker()
		inputs := event88Sequence(delayed)
		for i, in := range inputs {
			event88Feed(t, tracker, in)
			view, err := tracker.Snapshot(in.At)
			if err != nil {
				t.Fatal(err)
			}
			got := view.Directions[0]
			if i < len(inputs)-1 && got.EventValid || i == len(inputs)-1 && !got.EventValid {
				t.Fatalf("確認前の先取り又は確認後欠落: delayed=%v i=%d %+v", delayed, i, got)
			}
		}
		e := tracker.states[0].Event
		if e.Impulse.BarEnd >= e.Pullback.BarEnd || e.Pullback.BarEnd >= e.Recovery.BarEnd ||
			delayed && e.Recovery.BarEnd >= e.Confirmation.BarEnd || !delayed && e.Recovery != e.Confirmation {
			t.Fatal("i<p<r<=kの出典が不正", e)
		}
	}
	tracker := NewEventTracker()
	last := event88Sequence(false)[2]
	event88Feed(t, tracker, last)
	if tracker.states[0].Event != nil || tracker.states[0].Stage != "推進" {
		t.Fatal("最終形だけで押し履歴を作りました")
	}
}

// TestEvent88NoRenewalAndExpiry は900秒等号と若返り禁止を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Snapshotのpointerも内部から分離します。
func TestEvent88NoRenewalAndExpiry(t *testing.T) {
	tracker := NewEventTracker()
	inputs := event88Sequence(false)
	event88Feed(t, tracker, inputs...)
	original := *tracker.states[0].Event
	last := inputs[len(inputs)-1]
	for n := 1; n <= 4; n++ {
		in := event88Input(int64(n+3), event88View(last.At+float64(n)*180, 1010, float64(n+1), float64(n), float64(51+n), float64(50+n)))
		event88Feed(t, tracker, in)
		if !reflect.DeepEqual(original, *tracker.states[0].Event) {
			t.Fatal("継続足でeventを若返らせました")
		}
	}
	before, _ := tracker.Snapshot(original.Confirmation.BarEnd + 899)
	at, _ := tracker.Snapshot(original.Confirmation.BarEnd + 900)
	if !before.Directions[0].EventValid || at.Directions[0].EventValid {
		t.Fatal("900秒strict境界を破りました")
	}
	before.Directions[0].Event.ID = "外部破損"
	before.Directions[0].Impulse.BarEnd = 0
	if tracker.states[0].Event.ID == "外部破損" || tracker.states[0].Impulse.BarEnd == 0 {
		t.Fatal("Snapshotが内部pointerを共有しました")
	}
	deadline := event88Input(8, event88View(last.At+900, 1010, 6, 5, 56, 55))
	r := event88Feed(t, tracker, deadline)
	if len(r) != 1 || r[0].Kind != "期限失効" || tracker.states[0].Event != nil {
		t.Fatal("期限失効が記録されません", r)
	}
}

// TestEvent88RepullAndRecoveryReset は確認待ちと確認後の再押しを区別します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。再押し後は新eventを作ります。
func TestEvent88RepullAndRecoveryReset(t *testing.T) {
	tracker := NewEventTracker()
	inputs := event88Sequence(true)
	event88Feed(t, tracker, inputs[:3]...)
	repull := event88Input(4, event88View(event88Epoch+720, 990, -2, -1, 48, 49))
	event88Feed(t, tracker, repull)
	if tracker.states[0].Stage != "押し" || tracker.states[0].Recovery != nil || tracker.states[0].Event != nil {
		t.Fatal("確認待ちの再押しで回復を破棄しません")
	}
	recover := event88Input(5, event88View(event88Epoch+900, 1010, -1, -2, 49, 48))
	event88Feed(t, tracker, recover)
	old := *tracker.states[0].Event
	repull = event88Input(6, event88View(event88Epoch+1080, 990, -2, -1, 48, 49))
	event88Feed(t, tracker, repull)
	if tracker.states[0].Event != nil || *tracker.states[0].Impulse != old.Confirmation {
		t.Fatal("確認後再押しの起点が旧kではありません")
	}
	recover = event88Input(7, event88View(event88Epoch+1260, 1010, -1, -2, 49, 48))
	event88Feed(t, tracker, recover)
	if tracker.states[0].Event == nil || tracker.states[0].Event.ID == old.ID {
		t.Fatal("新しい再開を区別しません")
	}
}

// TestEvent88Invalidations は同終端Last0/背景/窓/EOF/欠足の失効を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。未知を支持へ補完しません。
func TestEvent88Invalidations(t *testing.T) {
	for _, kind := range []string{"Last0", "未知", "背景逆", "背景0", "窓", "静観", "EOF", "欠足"} {
		t.Run(kind, func(t *testing.T) {
			tracker := NewEventTracker()
			inputs := event88Sequence(false)
			event88Feed(t, tracker, inputs...)
			in := event88Input(4, event88View(event88Epoch+720, 1010, 2, 1, 52, 51))
			switch kind {
			case "Last0":
				in = inputs[2]
				in.Ordinal, in.At, in.Origin = 4, in.At+1, "quote"
				in.Quote.Time, in.Quote.Last = in.At, 0
				in.Technical.ReversalKnown = false
			case "未知":
				in.Technical.SpikeKnown = false
			case "背景逆":
				in.Technical.EMA8_15 = 980
			case "背景0":
				in.Technical.EMA8_15 = in.Technical.EMA21_15
			case "窓":
				in.Window, in.EpochStart = "U165_03", in.At
			case "静観":
				in.Window, in.EpochStart = "静観", in.At
			case "EOF":
				in.AfterEOF = true
			case "欠足":
				in.At, in.Technical.Bar3End, in.Technical.Bar15End = in.At+180, in.At+180, in.At+180
			}
			r := event88Feed(t, tracker, in)
			view, err := tracker.Snapshot(in.At)
			if err != nil || len(r) != 1 || view.Directions[0].EventValid || view.Directions[0].Event != nil {
				t.Fatal("失効漏れ", kind, r, view, err)
			}
		})
	}
}

// TestEvent88SparseTraceAndMirror は重複nil、Last0全行、鏡像の状態を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。入力値も不変です。
func TestEvent88SparseTraceAndMirror(t *testing.T) {
	buy, sell := NewEventTracker(), NewEventTracker()
	for _, in := range event88Sequence(true) {
		before := in
		event88Feed(t, buy, in)
		event88Feed(t, sell, event88Mirror(in))
		if in != before {
			t.Fatal("元入力を変更しました")
		}
	}
	a, b := buy.states[0].Event, sell.states[1].Event
	if a == nil || b == nil || a.Impulse != b.Impulse || a.Pullback != b.Pullback || a.Recovery != b.Recovery || a.Confirmation != b.Confirmation {
		t.Fatal("売買鏡像の出典が変化しました", a, b)
	}
	duplicate := event88Sequence(true)[3]
	duplicate.Ordinal, duplicate.Origin = 5, "core_timer"
	r, err := buy.Observe(duplicate)
	if err != nil || r != nil {
		t.Fatal("同BarEndの重複eventを作りました", r, err)
	}
	for n := int64(6); n <= 7; n++ {
		bad := duplicate
		bad.Ordinal, bad.At, bad.Origin = n, duplicate.At+float64(n), "quote"
		bad.Quote.Time, bad.Quote.Last = bad.At, 0
		bad.Technical.ReversalKnown = false
		r, err := buy.Observe(bad)
		if err != nil || r == nil || r.Kind != "Last不良" {
			t.Fatal("Last0失効入力を省略しました", r, err)
		}
	}
}

// TestEvent88RejectsCorruptInput は未来/NaN/順序/値幅矛盾を拒否します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。error後に入力順を消費しません。
func TestEvent88RejectsCorruptInput(t *testing.T) {
	for _, kind := range []string{"未来足", "未来quote", "NaN", "負ATR", "RSI", "ordinal", "時計"} {
		t.Run(kind, func(t *testing.T) {
			tracker := NewEventTracker()
			first := event88Sequence(false)[0]
			event88Feed(t, tracker, first)
			in := event88Sequence(false)[1]
			switch kind {
			case "未来足":
				in.Technical.Bar3End = in.At + 1
			case "未来quote":
				in.Quote.Time = in.At + 1
			case "NaN":
				in.Technical.Histogram3 = math.NaN()
			case "負ATR":
				in.Technical.ATR3 = -1
			case "RSI":
				in.Technical.RSI3 = 101
			case "ordinal":
				in.Ordinal = first.Ordinal
			case "時計":
				in.At = first.At - 1
			}
			if _, err := tracker.Observe(in); err == nil {
				t.Fatal("不正入力を受理しました", kind)
			}
			if tracker.lastInput != first {
				t.Fatal("拒否入力で状態を変更しました")
			}
		})
	}
}

// TestEvent88RecoveryWaitAndBadBBO は回復待ちの逆勢い/急変と不良BBOを区別します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。価格回復後の勢い確認を遅れて受け入れます。
func TestEvent88RecoveryWaitAndBadBBO(t *testing.T) {
	tracker := NewEventTracker()
	event88Feed(t, tracker, event88Sequence(true)[:3]...)
	weak := event88Input(4, event88View(event88Epoch+720, 1007, -2, -1, 48, 49))
	weak.Quote.Bid, weak.Quote.Ask, weak.Quote.Valid = 1020, 1010, false
	event88Feed(t, tracker, weak)
	if tracker.states[0].Stage != "価格回復" || tracker.states[0].Recovery.BarEnd != event88Epoch+540 || tracker.states[0].RequiredUnknown {
		t.Fatal("既知の逆勢い又はbadBBOを未知失効としました", tracker.states[0])
	}
	spike := event88Input(5, event88View(event88Epoch+900, 1010, -1, -2, 70, 48))
	spike.Technical.TR3 = 41
	event88Feed(t, tracker, spike)
	if tracker.states[0].Stage != "価格回復" || tracker.states[0].Event != nil {
		t.Fatal("急変中に確認又は回復破棄しました")
	}
	confirm := event88Input(6, event88View(event88Epoch+1080, 1010, 0, -1, 71, 70))
	event88Feed(t, tracker, confirm)
	if tracker.states[0].Event == nil || tracker.states[0].Event.Recovery.BarEnd != event88Epoch+540 || tracker.states[0].Event.Confirmation.BarEnd != event88Epoch+1080 {
		t.Fatal("価格回復点を保った遅い確認がありません")
	}
	old := *tracker.states[0].Event
	weak = event88Input(7, event88View(event88Epoch+1260, 1010, -1, 0, 70, 71))
	event88Feed(t, tracker, weak)
	if !reflect.DeepEqual(old, *tracker.states[0].Event) {
		t.Fatal("確認後の既知逆勢いでeventを更新しました")
	}
}

// TestEvent88EpochBoundaryAndZeroPull は窓開始端と平均同値の押しを検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。前窓の閉じ足を新窓の起点にしません。
func TestEvent88EpochBoundaryAndZeroPull(t *testing.T) {
	tracker := NewEventTracker()
	first := event88Sequence(false)[0]
	first.Window, first.EpochStart = "U165_03", first.At
	event88Feed(t, tracker, first)
	if tracker.states[0].Impulse != nil {
		t.Fatal("epoch開始端の旧窓足を起点にしました")
	}
	impulse := event88Input(2, event88View(first.At+180, 1010, 2, 1, 52, 51))
	impulse.Window, impulse.EpochStart = first.Window, first.EpochStart
	pull := event88Input(3, event88View(first.At+360, 1000, 1, 2, 51, 52))
	pull.Window, pull.EpochStart = first.Window, first.EpochStart
	recover := event88Input(4, event88View(first.At+540, 1010, 2, 1, 52, 51))
	recover.Window, recover.EpochStart = first.Window, first.EpochStart
	event88Feed(t, tracker, impulse, pull, recover)
	if tracker.states[0].Event == nil || tracker.states[0].Event.Impulse.BarEnd != impulse.At || tracker.states[0].Event.Pullback.BarEnd != pull.At {
		t.Fatal("新窓だけの順序又は平均同値の押しが成立しません")
	}
}
