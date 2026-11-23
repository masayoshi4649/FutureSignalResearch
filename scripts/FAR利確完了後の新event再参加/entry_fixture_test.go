// 91派生元: scripts/FAR利益床と収穫配分の比較/entry_fixture_test.go
// 91派生元SHA256: ed4c9addc23fc2d14dbb49a78bb9426996dc1b40a4558250c91735a19331e662
// 89人工helperは固定88の公開API用合成入力から派生。実市場入力は読みません。
package far91

import (
	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
	"testing"
)

const event91Epoch = 100000.0

// event91View は方向整列を強制しない正常な公開指標人工を作ります。
//
// 引数: end/close/hist/previousHist/rsi/previousRSI(float64)は当時値です。
// 返り値: TechnicalViewは3分EMA配列だけ買いと逆の正常値です。
func event91View(end, close, hist, previousHist, rsi, previousRSI float64) far87.TechnicalView {
	return far87.TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true,
		EMA8_3: 1000, EMA21_3: 1005, EMA8_15: 1000, EMA21_15: 990, RSI3: rsi, PreviousRSI3: previousRSI,
		Histogram3: hist, PreviousHistogram3: previousHist, Close3: close, TR3: 10, ATR3: 20, PreviousATR3: 20, Bar3End: end, Bar15End: end}
}

// event91Input は公開時計と直前原行を分けたイベント入力を作ります。
//
// 引数: ordinal(int64)、v(TechnicalView)は処理順と公開足です。
// 返り値: EventInputは当時rawを先取りしない人工です。
func event91Input(ordinal int64, v far87.TechnicalView) EventInput {
	return EventInput{Ordinal: ordinal, At: v.Bar3End, Origin: "three_timer", Window: "D164_15", EpochStart: event91Epoch,
		Quote: far87.Quote{Time: v.Bar3End - 1, Index: ordinal, Line: ordinal + 1, Last: v.Close3, Bid: 1000, Ask: 1010, Valid: true}, Technical: v}
}

// event91Sequence は推進/押し/回復/確認の別足又は同足人工を返します。
//
// 引数: delayed(bool)は勢い確認を次足へ分ける指定です。
// 返り値: []EventInputは未来を含まない時間順入力です。
func event91Sequence(delayed bool) []EventInput {
	inputs := []EventInput{
		event91Input(1, event91View(event91Epoch+180, 1010, 1, 0, 51, 50)),
		event91Input(2, event91View(event91Epoch+360, 995, 0, 1, 50, 51)),
	}
	if delayed {
		inputs = append(inputs,
			event91Input(3, event91View(event91Epoch+540, 1005, -1, 0, 49, 50)),
			event91Input(4, event91View(event91Epoch+720, 1010, 0, -1, 50, 49)))
	} else {
		inputs = append(inputs, event91Input(3, event91View(event91Epoch+540, 1010, 1, 0, 51, 50)))
	}
	return inputs
}

// event91Feed は入力列を追跡器へ渡し、保存recordだけを返します。
//
// 引数: t(*testing.T)、tracker(*EventTracker)、inputs([]EventInput)は人工です。
// 返り値: []EventRecordはnilでない観測で、失敗時はテストを停止します。
func event91Feed(t *testing.T, tracker *EventTracker, inputs ...EventInput) []EventRecord {
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

// event91Mirror は価格/RSI/勢いを鏡像にした同時計入力を作ります。
//
// 引数: in(EventInput)は買い人工です。
// 返り値: EventInputは売り側の同式を検査する人工です。
func event91Mirror(in EventInput) EventInput {
	v := &in.Technical
	v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = 2000-v.EMA8_3, 2000-v.EMA21_3, 2000-v.EMA8_15, 2000-v.EMA21_15
	v.Close3, v.RSI3, v.PreviousRSI3 = 2000-v.Close3, 100-v.RSI3, 100-v.PreviousRSI3
	v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
	q := &in.Quote
	q.Last, q.Bid, q.Ask = 2000-q.Last, 2000-q.Ask, 2000-q.Bid
	return in
}

// entry91Source は元初回/親量を現在量から分けた参照全poolを作ります。
//
// 引数: at(float64)はSource観測時計です。
// 返り値: ReadSnapshotは買売の参照と現在量を含む人工です。
func entry91Source(at float64) far87.ReadSnapshot {
	parent := 50
	rows := []far87.ReadLot{}
	for i, side := range []int{-1, 1} {
		id := []string{"売参照", "買参照"}[i]
		rows = append(rows, far87.ReadLot{Reference: far87.ReferenceLot{ID: id, InternalID: id + "内部", Parent: "元親", SourceID: "元源", Method: "NK225_D164_15", Owner: "元所有", Kind: "source_add", Side: side, Quantity: 7 + i, Entry: 1000, At: at - float64(20-i)},
			ReferenceInitialQuantity: 32, NativeParentInitialMicro: &parent})
	}
	return far87.ReadSnapshot{Method: "NK225_D164_15", At: at, SourceIndex: 5, Started: true, Lots: rows, Closes: []far87.ReferenceClose{}}
}
