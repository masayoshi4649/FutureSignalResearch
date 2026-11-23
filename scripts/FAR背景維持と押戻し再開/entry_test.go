package far88

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"

	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// entry88Fixture は非0の再開と旧ChartPairを結んだ人工を作ります。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: 時刻(float64)、Quote、ChartView、EventSnapshotは当時の正常値です。
func entry88Fixture(t *testing.T) (float64, far87.Quote, far87.ChartView, EventSnapshot) {
	t.Helper()
	tracker := NewEventTracker()
	inputs := event88Sequence(true)
	event88Feed(t, tracker, inputs...)
	last := inputs[len(inputs)-1]
	q := last.Quote
	q.Bid, q.Ask, q.Last = 1000, 1010, 1010
	chart := far87.ChartView{Technical: last.Technical, PreviousClose3: inputs[len(inputs)-2].Technical.Close3,
		PreviousEMA8_3: 1000, PreviousBar3End: last.Technical.Bar3End - 180, Previous3Known: true}
	view, err := tracker.Snapshot(last.At)
	if err != nil {
		t.Fatal(err)
	}
	return last.At, q, chart, view
}

// entry88Source は元初回/親量を現在量から分けた参照全poolを作ります。
//
// 引数: at(float64)はSource観測時計です。
// 返り値: ReadSnapshotは買売の参照と現在量を含む人工です。
func entry88Source(at float64) far87.ReadSnapshot {
	parent := 50
	rows := []far87.ReadLot{}
	for i, side := range []int{-1, 1} {
		id := []string{"売参照", "買参照"}[i]
		rows = append(rows, far87.ReadLot{Reference: far87.ReferenceLot{ID: id, InternalID: id + "内部", Parent: "元親", SourceID: "元源", Method: "NK225_D164_15", Owner: "元所有", Kind: "source_add", Side: side, Quantity: 7 + i, Entry: 1000, At: at - float64(20-i)},
			ReferenceInitialQuantity: 32, NativeParentInitialMicro: &parent})
	}
	return far87.ReadSnapshot{Method: "NK225_D164_15", At: at, SourceIndex: 5, Started: true, Lots: rows, Closes: []far87.ReferenceClose{}}
}

// TestEntry88CurrentAndSequence は静的資格と順序資格及び3分整列非要件を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。旧C0を使わず複合資格を計算します。
func TestEntry88CurrentAndSequence(t *testing.T) {
	at, q, chart, events := entry88Fixture(t)
	before, _ := json.Marshal(struct {
		Chart  far87.ChartView
		Events EventSnapshot
	}{chart, events})
	evaluation, err := EvaluateEntry(at, q, chart, events)
	if err != nil {
		t.Fatal(err)
	}
	buy := evaluation.Directions[0]
	if !buy.E0Allowed || !buy.E1Allowed || buy.RequiredUnknown || buy.EventRequiredUnknown || buy.PlacementATR == nil || *buy.PlacementATR != .5 || evaluation.Directions[1].E0Allowed {
		t.Fatal("複合資格又は売買区分が不正", evaluation)
	}
	if chart.Technical.EMA8_3 >= chart.Technical.EMA21_3 {
		t.Fatal("3分整列を外した反証になっていません")
	}
	events.Directions[0].Event, events.Directions[0].EventValid = nil, false
	currentOnly, err := EvaluateEntry(at, q, chart, events)
	if err != nil || !currentOnly.Directions[0].E0Allowed || currentOnly.Directions[0].E1Allowed {
		t.Fatal("現在状態から順序を補完しました", currentOnly, err)
	}
	_, _, _, originalEvents := entry88Fixture(t)
	after, _ := json.Marshal(struct {
		Chart  far87.ChartView
		Events EventSnapshot
	}{chart, originalEvents})
	if string(before) != string(after) {
		t.Fatal("元入力が変化しました")
	}
}

// TestEntry88KnownFailureAndUnknown はATR0/端点/急変と未知を分離します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。全閾値の等号を固定します。
func TestEntry88KnownFailureAndUnknown(t *testing.T) {
	for _, tc := range []struct {
		name    string
		unknown bool
		allowed bool
	}{
		{"ATR0", false, false}, {"取得0", false, true}, {"取得1", false, true}, {"取得超", false, false},
		{"Spike", false, false}, {"Spike等号", false, true}, {"RSI横ばい", false, false},
		{"pair未知", true, false}, {"ATR未知", true, false}, {"背景未知", true, false},
		{"旧足", true, false}, {"気配未知", true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			at, q, chart, events := entry88Fixture(t)
			switch tc.name {
			case "ATR0":
				chart.Technical.ATR3 = 0
			case "取得0":
				q.Ask, q.Bid = 1000, 990
			case "取得1":
				q.Ask, q.Bid = 1020, 1010
			case "取得超":
				q.Ask, q.Bid = 1030, 1020
			case "Spike":
				chart.Technical.TR3, chart.Technical.RSI3, chart.Technical.PreviousRSI3 = 41, 70, 49
			case "Spike等号":
				chart.Technical.TR3, chart.Technical.RSI3, chart.Technical.PreviousRSI3 = 40, 70, 49
			case "RSI横ばい":
				chart.Technical.RSI3 = chart.Technical.PreviousRSI3
			case "pair未知":
				chart.Previous3Known = false
			case "ATR未知":
				chart.Technical.ATRKnown = false
			case "背景未知":
				chart.Technical.TrendKnown = false
			case "旧足":
				at += 181
				q.Time = at - 1
				events.At = at
			case "気配未知":
				q.Valid = false
			}
			evaluation, err := EvaluateEntry(at, q, chart, events)
			if err != nil {
				t.Fatal(err)
			}
			d := evaluation.Directions[0]
			if d.RequiredUnknown != tc.unknown || d.E0Allowed != tc.allowed || d.E1Allowed && !d.E0Allowed {
				t.Fatal("未知/不成立/包含が不正", tc, d)
			}
		})
	}
}

// TestEntry88FilterRanksAndFirstParticipation は部分列/元量/親量と金融seenの分担を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。外filter自身は占有やseenを作りません。
func TestEntry88FilterRanksAndFirstParticipation(t *testing.T) {
	at, q, chart, events := entry88Fixture(t)
	evaluation, err := EvaluateEntry(at, q, chart, events)
	if err != nil {
		t.Fatal(err)
	}
	raw := entry88Source(q.Time)
	before, _ := json.Marshal(raw)
	for _, policy := range []string{"S", "E0", "E1"} {
		out, checks, err := FilterEntry(policy, raw, evaluation)
		if err != nil {
			t.Fatal(err)
		}
		want := 1
		if policy == "S" {
			want = 2
		}
		if len(out.Lots) != want || len(checks) != 2 || checks[1].RawRank != 2 || out.At != raw.At || out.SourceIndex != raw.SourceIndex || out.Method != raw.Method {
			t.Fatal("全pool又は出典が変化しました", policy, out, checks)
		}
		if policy != "S" && (checks[0].SuppliedRank != nil || *checks[1].SuppliedRank != 1 || out.Lots[0].Reference.Quantity != 8 || out.Lots[0].ReferenceInitialQuantity != 32 || *out.Lots[0].NativeParentInitialMicro != 50) {
			t.Fatal("原順位/供給順位又は現在量/初期量を混同しました", checks, out)
		}
		*out.Lots[0].NativeParentInitialMicro = 999
		out.Lots[0].Reference.Quantity = 1
	}
	after, _ := json.Marshal(raw)
	if string(before) != string(after) {
		t.Fatal("供給poolから元Sourceを変更しました")
	}
}

// TestEntry88EventBeforeSourceAndExpiry は生成前eventと期限を明示します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。生成後/前/同時を損益で選びません。
func TestEntry88EventBeforeSourceAndExpiry(t *testing.T) {
	at, q, chart, events := entry88Fixture(t)
	for _, offset := range []float64{-1, 0, 1} {
		raw := entry88Source(at + 2)
		raw.At, raw.Lots[1].Reference.At = at+2, at+offset
		events.At = at + 2
		evaluation, err := EvaluateEntry(at+2, q, chart, events)
		if err != nil {
			t.Fatal(err)
		}
		out, checks, err := FilterEntry("E1", raw, evaluation)
		if err != nil || len(out.Lots) != 1 || checks[1].EventBeforeSource == nil || *checks[1].EventBeforeSource != (offset > 0) {
			t.Fatal("event/Source順を誤りました", offset, out, checks, err)
		}
	}
	tracker := NewEventTracker()
	event88Feed(t, tracker, event88Sequence(true)...)
	expired, _ := tracker.Snapshot(at + 900)
	q.Time = at + 899
	chart.Technical.Bar3End, chart.Technical.Bar15End = at+900, at+900
	chart.PreviousBar3End = at + 720
	evaluation, err := EvaluateEntry(at+900, q, chart, expired)
	if err != nil || !evaluation.Directions[0].E0Allowed || evaluation.Directions[0].E1Allowed {
		t.Fatal("期限を現在資格で若返らせました", evaluation, err)
	}
}

// TestEntry88MirrorAndInputErrors は売買鏡像と保存値破損を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。NaN/未来/重複/schema矛盾はerrorです。
func TestEntry88MirrorAndInputErrors(t *testing.T) {
	at, q, chart, events := entry88Fixture(t)
	buy, err := EvaluateEntry(at, q, chart, events)
	if err != nil {
		t.Fatal(err)
	}
	tracker := NewEventTracker()
	inputs := event88Sequence(true)
	for _, in := range inputs {
		event88Feed(t, tracker, event88Mirror(in))
	}
	mirrorInput := event88Mirror(inputs[len(inputs)-1])
	mirrorChart := far87.ChartView{Technical: mirrorInput.Technical, PreviousClose3: 2000 - chart.PreviousClose3,
		PreviousEMA8_3: 2000 - chart.PreviousEMA8_3, PreviousBar3End: chart.PreviousBar3End, Previous3Known: true}
	mirrorEvents, _ := tracker.Snapshot(at)
	sell, err := EvaluateEntry(at, mirrorInput.Quote, mirrorChart, mirrorEvents)
	if err != nil || buy.Directions[0].E0Allowed != sell.Directions[1].E0Allowed || buy.Directions[0].E1Allowed != sell.Directions[1].E1Allowed ||
		!reflect.DeepEqual(buy.Directions[0].Checks, sell.Directions[1].Checks) || *buy.Directions[0].PlacementATR != *sell.Directions[1].PlacementATR {
		t.Fatal("売買で閾値が異なります", buy, sell, err)
	}
	for _, name := range []string{"NaN", "future", "pair", "duplicate", "eventflag", "eventfuture"} {
		at, q, chart, events := entry88Fixture(t)
		switch name {
		case "NaN":
			chart.Technical.Histogram3 = math.NaN()
		case "future":
			chart.Technical.Bar3End = at + 1
		case "pair":
			chart.PreviousBar3End--
		case "duplicate":
			events.Directions[1].Side = 1
		case "eventflag":
			events.Directions[0].EventValid = false
		case "eventfuture":
			events.Directions[0].Event.Confirmation.PublishedAt = at + 1
		}
		if _, err := EvaluateEntry(at, q, chart, events); err == nil {
			t.Fatal("破損を受理しました", name)
		}
	}
}

// TestEntry88LockedAndCrossedQuotes はValidとの矛盾でも正常気配へ補完しません。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。買売ともlocked/crossedを未知として拒否します。
func TestEntry88LockedAndCrossedQuotes(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, crossed := range []bool{false, true} {
			at, q, chart, events := entry88Fixture(t)
			if side == -1 {
				tracker := NewEventTracker()
				inputs := event88Sequence(true)
				for _, in := range inputs {
					event88Feed(t, tracker, event88Mirror(in))
				}
				last := event88Mirror(inputs[len(inputs)-1])
				q = last.Quote
				chart = far87.ChartView{Technical: last.Technical, PreviousClose3: 2000 - chart.PreviousClose3,
					PreviousEMA8_3: 2000 - chart.PreviousEMA8_3, PreviousBar3End: chart.PreviousBar3End, Previous3Known: true}
				events, _ = tracker.Snapshot(at)
			}
			q.Bid, q.Ask, q.Valid = 1000, 1000, true
			if crossed {
				q.Bid = 1010
			}
			result, err := EvaluateEntry(at, q, chart, events)
			if err != nil {
				t.Fatal(err)
			}
			for _, direction := range result.Directions {
				if direction.E0Allowed || direction.E1Allowed || direction.CurrentKnown || !direction.RequiredUnknown || direction.Checks[3].Known || direction.Checks[3].Passed {
					t.Fatal("locked/crossedの矛盾Validを正常気配としました", side, crossed, direction)
				}
			}
		}
	}
}

// TestEntry88ChartFreshnessBoundaries は3分180秒/15分900秒の既知性境界を確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。等号は既知、超過は必要値未知です。
func TestEntry88ChartFreshnessBoundaries(t *testing.T) {
	for _, tc := range []struct {
		age3, age15 float64
		known       bool
	}{{180, 900, true}, {181, 900, false}, {180, 901, false}} {
		at, q, chart, events := entry88Fixture(t)
		chart.Technical.Bar3End, chart.Technical.Bar15End = at-tc.age3, at-tc.age15
		chart.PreviousBar3End = chart.Technical.Bar3End - 180
		result, err := EvaluateEntry(at, q, chart, events)
		if err != nil {
			t.Fatal(err)
		}
		d := result.Directions[0]
		if d.Checks[1].Known != tc.known || d.Checks[1].Passed != tc.known || d.CurrentKnown != tc.known || d.RequiredUnknown == tc.known || d.E0Allowed != tc.known || d.E1Allowed != tc.known {
			t.Fatal("足鮮度の等号/未知を誤りました", tc, d)
		}
	}
}
