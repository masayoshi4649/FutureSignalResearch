package minichart

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"

	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// technicalFixture96 は実市場を読まず、公開出典付きの順行又は反転候補を作ります。
//
// 引数: side(int)は±1、role(string)はA又はBです。
// 返り値: TechnicalGateInput/EntryCandidateは値型の人工入力です。
func technicalFixture96(side int, role string) (TechnicalGateInput, EntryCandidate) {
	const at = 36000.0
	scene := chartwarmup96.Scene{ID: "人工場", Contract: "人工限月", Start: 18000}
	snapshots := make([]chartwarmup96.Snapshot, 3)
	for i := range snapshots {
		end := at - float64(2-i)*180
		close := 1000 + float64(i)*10
		em8 := 990 + float64(i)*10
		if i == 0 && role == "B" {
			em8 = 1000
		}
		v := far80.TechnicalView{TrendKnown: true, ReversalKnown: true, SpikeKnown: true, ExitKnown: true, ATRKnown: true,
			EMA8_3: em8, EMA21_3: em8 - 10, EMA8_15: 1010, EMA21_15: 1000,
			RSI3: 80 + float64(i), PreviousRSI3: 79 + float64(i), Histogram3: 2, PreviousHistogram3: 1,
			Close3: close, TR3: 20, ATR3: 20, PreviousATR3: 20, Bar3End: end, Bar15End: math.Floor(end/900) * 900}
		if role == "B" {
			v.EMA8_15, v.EMA21_15 = 990, 1000
		}
		evidence := func(barEnd float64) chartwarmup96.BarEvidence {
			return chartwarmup96.BarEvidence{BarEnd: barEnd, AvailableAt: barEnd, ObservedClock: at + 100,
				Rows: 1, DataKnown: true, HasLastSource: true,
				LastSource: chartwarmup96.SourceStamp{Time: barEnd - 1, Index: 9000 + int64(i), Line: 10000 + int64(i), Last: close, Valid: true}}
		}
		snapshots[i] = chartwarmup96.Snapshot{Scene: scene, At: end, HasObservedClock: true, ObservedClock: at + 100,
			HasLastInput: true, LastInput: chartwarmup96.SourceStamp{Time: end - 1, Index: 9000 + int64(i), Line: 10000 + int64(i), Last: close, Valid: true},
			Chart: far82.ChartView{Technical: v, PreviousClose3: close - 10, PreviousEMA8_3: em8 - 10, PreviousBar3End: end - 180, Previous3Known: true},
			Three: evidence(end), Fifteen: evidence(v.Bar15End)}
	}
	q := QuoteStamp{Time: at - 1, Index: 12, SourceLine: 10050, Last: 1015, Bid: 1010, Ask: 1020, QuoteOK: true}
	current := far82.CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: q.Time,
		SourceIndex: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask,
		Buy: far81.CurrentSupport{OFIKnown: true, OFI30: 1, OwnAt: q.Time,
			Windows: map[string]far81.CurrentSupportWindow{"人工": {Known: true, CurrentAt: q.Time, EndpointAt: q.Time - 5}}},
		Sell: far81.CurrentSupport{OFIKnown: true, OFI30: 1, OwnAt: q.Time},
		Night: far81.CurrentStructure{Available: true, Window: "E08", Time: q.Time, Index: q.Index,
			Band: far81.CurrentBandWindow{QuantityKnown: true, Time: q.Time, Index: q.Index, StartTime: q.Time - 5,
				BidRefill: 10, AskDeplete: 3, AskRefill: 2, BidDeplete: 1}}}}
	in := TechnicalGateInput{SnapshotID: "人工場-G0001", At: at, Kind: "Day", Chart: snapshots[2], Recent3: snapshots, Current: current}
	candidate := EntryCandidate{Ordinal: 1, At: at, Side: 1, Quote: q, Available: 10, Quantity: 2,
		Source: SourceIdentity{SignalID: "人工出生", BirthQuantity: 2, BirthTime: at - 100, Method: "D164_15"}}
	if side == -1 {
		mirrorSnapshot := func(p *chartwarmup96.Snapshot) {
			v := &p.Chart.Technical
			v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15 = 4000-v.EMA8_3, 4000-v.EMA21_3, 4000-v.EMA8_15, 4000-v.EMA21_15
			v.Close3, v.RSI3, v.PreviousRSI3 = 4000-v.Close3, 100-v.RSI3, 100-v.PreviousRSI3
			v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
			p.Chart.PreviousClose3, p.Chart.PreviousEMA8_3 = 4000-p.Chart.PreviousClose3, 4000-p.Chart.PreviousEMA8_3
			p.LastInput.Last, p.Three.LastSource.Last, p.Fifteen.LastSource.Last = 4000-p.LastInput.Last, 4000-p.Three.LastSource.Last, 4000-p.Fifteen.LastSource.Last
		}
		for i := range in.Recent3 {
			mirrorSnapshot(&in.Recent3[i])
		}
		in.Chart = in.Recent3[2]
		candidate.Side, candidate.Quote.Last = -1, 4000-q.Last
		candidate.Quote.Bid, candidate.Quote.Ask = 4000-q.Ask, 4000-q.Bid
		in.Current.Last, in.Current.Bid, in.Current.Ask = candidate.Quote.Last, candidate.Quote.Bid, candidate.Quote.Ask
		in.Current.Buy.OFI30, in.Current.Sell.OFI30 = -1, -1
		v := &in.Current.Night.Band
		v.BidRefill, v.AskRefill, v.BidDeplete, v.AskDeplete = v.AskRefill, v.BidRefill, v.AskDeplete, v.BidDeplete
	}
	return in, candidate
}

// assessGate96 は人工の想定外エラーを直ちに報告します。
//
// 引数: t(*testing.T)、in(TechnicalGateInput)、c(EntryCandidate)、policy(string)です。
// 返り値: TechnicalAssessmentは実装が返した保存値です。
func assessGate96(t *testing.T, in TechnicalGateInput, c EntryCandidate, policy string) TechnicalAssessment {
	t.Helper()
	got, err := AssessTechnicalGate(in, c, policy)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

// TestTechnical96MirrorRoles は買売鏡像、A/Bの分離とABのORを検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96MirrorRoles(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, role := range []string{"A", "B"} {
			in, c := technicalFixture96(side, role)
			for _, policy := range []string{"A", "B", "AB"} {
				got := assessGate96(t, in, c, policy)
				allowed := policy == role || policy == "AB"
				if !got.Decision.Known || got.Decision.Allowed != allowed || got.Decision.SnapshotID != in.SnapshotID || got.Decision.Policy != policy {
					t.Fatalf("side=%d role=%s policy=%s: %+v", side, role, policy, got.Decision)
				}
				if allowed && ((role == "A" && got.Decision.Role != "順行") || (role == "B" && got.Decision.Role != "反転")) {
					t.Fatal(got.Decision)
				}
			}
		}
	}
}

// TestTechnical96SpikeStrict は高RSI持続と同時スパイクのstrict境界を検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96SpikeStrict(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, test := range []struct {
			name      string
			tr, delta float64
			allowed   bool
		}{
			{"高RSI持続", 50, 1, true}, {"同時急変", 41, 16, false}, {"TR等号", 40, 16, true}, {"RSI等号", 41, 15, true},
		} {
			t.Run(test.name, func(t *testing.T) {
				in, c := technicalFixture96(side, "A")
				in.Chart.Chart.Technical.TR3 = test.tr
				in.Chart.Chart.Technical.RSI3, in.Chart.Chart.Technical.PreviousRSI3 = 90, 90-test.delta
				if side == -1 {
					in.Chart.Chart.Technical.RSI3, in.Chart.Chart.Technical.PreviousRSI3 = 10, 10+test.delta
				}
				in.Recent3[2].Chart.Technical = in.Chart.Chart.Technical
				got := assessGate96(t, in, c, "A")
				if !got.Decision.Known || got.Decision.Allowed != test.allowed {
					t.Fatal(got.Decision)
				}
			})
		}
	}
}

// TestTechnical96Volume はDayのOFIとNightの4量差を未知/反対/支持へ分けます。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96Volume(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, kind := range []string{"Day", "Night"} {
			for _, state := range []string{"支持", "未知", "反対", "中立", "別時計", "未対応"} {
				in, c := technicalFixture96(side, "A")
				in.Kind = kind
				if kind == "Day" {
					v := &in.Current.Buy
					if side == -1 {
						v = &in.Current.Sell
					}
					switch state {
					case "未知":
						v.OFIKnown = false
					case "反対":
						v.OFI30 = -float64(side)
					case "中立":
						v.OFI30 = 0
					case "別時計":
						v.OwnAt--
					case "未対応":
						v.OFIKnown = false
						v.M, v.T = 100, 100
					}
				} else {
					v := &in.Current.Night.Band
					switch state {
					case "未知":
						v.QuantityKnown = false
					case "反対":
						v.BidRefill, v.AskRefill, v.BidDeplete, v.AskDeplete = v.AskRefill, v.BidRefill, v.AskDeplete, v.BidDeplete
					case "中立":
						v.BidRefill, v.AskRefill, v.BidDeplete, v.AskDeplete = 0, 0, 0, 0
					case "別時計":
						v.Time--
					case "未対応":
						in.Current.Night.Window = "E09"
					}
				}
				got := assessGate96(t, in, c, "A")
				known := state == "支持" || state == "反対" || state == "中立"
				if got.Decision.Known != known || got.Decision.Allowed != (state == "支持") {
					t.Fatalf("%d %s %s: %+v", side, kind, state, got.Decision)
				}
			}
		}
	}
}

// TestTechnical96UnknownAndAge は未知値0と時間境界を通常の不成立から分けます。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96UnknownAndAge(t *testing.T) {
	for _, name := range []string{"EMA背景", "MACD", "ATR", "ATR0", "前RSI", "空足", "3分齢", "15分齢", "価格15秒", "価格15秒超", "取得位置0", "取得位置ATR", "取得位置ATR超"} {
		t.Run(name, func(t *testing.T) {
			in, c := technicalFixture96(1, "A")
			known, allowed := false, false
			switch name {
			case "EMA背景":
				in.Chart.Chart.Technical.TrendKnown = false
			case "MACD":
				in.Chart.Chart.Technical.ExitKnown = false
			case "ATR":
				in.Chart.Chart.Technical.ATRKnown = false
			case "ATR0":
				in.Chart.Chart.Technical.ATR3 = 0
			case "前RSI":
				in.Chart.Chart.Technical.SpikeKnown = false
			case "空足":
				in.Chart.Three.DataKnown = false
			case "3分齢":
				in.At += 180
				c.At = in.At
				in.Chart.At = in.At
			case "15分齢":
				in.At += 900
				c.At = in.At
				in.Chart.At = in.At
			case "価格15秒", "価格15秒超":
				delta := 15.0
				if name == "価格15秒超" {
					delta = 15.001
				}
				c.Quote.Time, in.Current.Time, in.Current.Received = in.At-delta, in.At-delta, in.At-delta
				in.Current.Buy.OwnAt, in.Current.Sell.OwnAt = in.Current.Time, in.Current.Time
				in.Current.Buy.Windows = nil
				in.Current.Night = far81.CurrentStructure{}
				known, allowed = delta == 15, delta == 15
			case "取得位置0":
				c.Quote.Ask = 1010
				c.Quote.Bid = 1000
				known, allowed = true, true
			case "取得位置ATR":
				c.Quote.Ask = 1030
				c.Quote.Bid = 1020
				known, allowed = true, true
			case "取得位置ATR超":
				c.Quote.Ask = 1030.01
				c.Quote.Bid = 1020
				known, allowed = true, false
			}
			in.Current.Bid, in.Current.Ask = c.Quote.Bid, c.Quote.Ask
			in.Chart.ObservedClock = in.At + 100
			in.Recent3[2].Chart.Technical = in.Chart.Chart.Technical
			got := assessGate96(t, in, c, "A")
			if got.Decision.Known != known || got.Decision.Allowed != allowed {
				t.Fatal(got.Decision)
			}
		})
	}
}

// TestTechnical96FixedLine は過去aのEMA線、固定3本窓、c足維持を検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96FixedLine(t *testing.T) {
	for _, test := range []struct {
		name           string
		known, allowed bool
	}{
		{"固定L成立", true, true}, {"後EMAなら成立するが固定L拒否", true, false}, {"3足不足", false, false},
		{"別足間隔", false, false}, {"空a", false, false}, {"b同値", true, false}, {"c再進行なし", true, false}, {"cRSI失速", true, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			in, c := technicalFixture96(1, "B")
			switch test.name {
			case "後EMAなら成立するが固定L拒否":
				in.Recent3[0].Chart.Technical.EMA8_3 = 1015
			case "3足不足":
				in.Recent3 = in.Recent3[1:]
			case "別足間隔":
				in.Recent3[0].At -= 180
				in.Recent3[0].Three.BarEnd -= 180
				in.Recent3[0].Three.AvailableAt -= 180
				in.Recent3[0].Three.LastSource.Time -= 180
				in.Recent3[0].Chart.Technical.Bar3End -= 180
				in.Recent3[0].Chart.PreviousBar3End -= 180
				in.Recent3[0].LastInput.Time -= 180
			case "空a":
				in.Recent3[0].Three.DataKnown = false
			case "b同値":
				in.Recent3[1].Chart.Technical.Close3 = 1000
			case "c再進行なし":
				in.Recent3[1].Chart.Technical.Close3 = 1020
			case "cRSI失速":
				in.Recent3[1].Chart.Technical.RSI3 = 83
			}
			got := assessGate96(t, in, c, "B")
			if got.Decision.Known != test.known || got.Decision.Allowed != test.allowed {
				t.Fatal(got.Decision)
			}
		})
	}
}

// TestTechnical96PublicationAndCorruption は未来・非有限・原行取り違えを拒否します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96PublicationAndCorruption(t *testing.T) {
	corruptions := map[string]func(*TechnicalGateInput, *EntryCandidate){
		"未来Available": func(i *TechnicalGateInput, _ *EntryCandidate) { i.Chart.Three.AvailableAt = i.At + 1 },
		"未来Source":    func(i *TechnicalGateInput, _ *EntryCandidate) { i.Chart.Three.LastSource.Time = i.At + 1 },
		"未来Current":   func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.Received = i.At + 1 },
		"未来出生":        func(i *TechnicalGateInput, c *EntryCandidate) { c.Source.BirthTime = i.At + 1 },
		"未来OFI":       func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.Buy.OwnAt = i.At + 1 },
		"未来窓": func(i *TechnicalGateInput, _ *EntryCandidate) {
			i.Current.Buy.Windows["未来"] = far81.CurrentSupportWindow{EndpointAt: i.At + 1}
		},
		"未来Night":         func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.Night.Band.Index = i.Current.SourceIndex + 1 },
		"非有限":             func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.Sell.M = math.NaN() },
		"負ATR":            func(i *TechnicalGateInput, _ *EntryCandidate) { i.Chart.Chart.Technical.ATR3 = -1 },
		"負数量":             func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.Night.Band.AskRefill = -1 },
		"原行違い":            func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.SourceLine++ },
		"FeaturesIndex違い": func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.SourceIndex++ },
		"価格違い":            func(i *TechnicalGateInput, _ *EntryCandidate) { i.Current.Ask++ },
		"別場":              func(i *TechnicalGateInput, _ *EntryCandidate) { i.Recent3[0].Scene.ID = "他場" },
		"4本窓":             func(i *TechnicalGateInput, _ *EntryCandidate) { i.Recent3 = append(i.Recent3, i.Chart) },
		"c取り違え":           func(i *TechnicalGateInput, _ *EntryCandidate) { i.Recent3[2].Chart.Technical.Close3++ },
		"不正Kind":          func(i *TechnicalGateInput, _ *EntryCandidate) { i.Kind = "日中" },
	}
	for name, mutate := range corruptions {
		t.Run(name, func(t *testing.T) {
			in, c := technicalFixture96(1, "B")
			mutate(&in, &c)
			if _, err := AssessTechnicalGate(in, c, "AB"); err == nil {
				t.Fatal("破損を受理")
			}
		})
	}
	in, c := technicalFixture96(1, "A")
	if got := assessGate96(t, in, c, "A"); !got.Decision.Allowed {
		t.Fatal("未来ObservedClockを値の未来公開と混同")
	}
	if in.Chart.LastInput.Index == c.Quote.Index {
		t.Fatal("人工は連番差を持つ必要あり")
	}
	if _, err := AssessTechnicalGate(in, c, "G0"); err == nil {
		t.Fatal("不正政策を受理")
	}
}

// TestTechnical96ThreeValuedAndNoMutation は三値論理と入力map/slice不変を検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestTechnical96ThreeValuedAndNoMutation(t *testing.T) {
	in, c := technicalFixture96(1, "A")
	in.Current.Buy.OFIKnown = false
	got := assessGate96(t, in, c, "AB")
	if got.Decision.Known || got.Decision.Allowed {
		t.Fatal(got.Decision)
	}
	in.Chart.Chart.Technical.Histogram3 = 0
	in.Recent3[2].Chart.Technical.Histogram3 = 0
	got = assessGate96(t, in, c, "AB")
	if !got.Decision.Known || got.Decision.Allowed {
		t.Fatal("既知否定AND未知は既知拒否", got.Decision)
	}
	in, c = technicalFixture96(1, "A")
	in.Recent3 = nil
	before, _ := json.Marshal(in)
	got = assessGate96(t, in, c, "AB")
	if !got.Decision.Known || !got.Decision.Allowed || got.Decision.Role != "順行" {
		t.Fatal("A成立OR B未知は成立", got.Decision)
	}
	after, _ := json.Marshal(in)
	if !reflect.DeepEqual(before, after) {
		t.Fatal("入力を書換え")
	}
	got.Checks[0].Reason = "出力変更"
	again := assessGate96(t, in, c, "AB")
	if again.Checks[0].Reason == "出力変更" {
		t.Fatal("返却sliceを共有")
	}
}

// TestTechnical96InvalidatedCurrent は不良Last後に残る過去公開足を現在成立へ戻しません。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。通常の未知化を出典破損errorへ変換しないことも確認します。
func TestTechnical96InvalidatedCurrent(t *testing.T) {
	in, c := technicalFixture96(1, "B")
	in.Chart.Chart.Technical = far80.TechnicalView{Bar3End: in.Chart.Three.BarEnd, Bar15End: in.Chart.Fifteen.BarEnd}
	in.Chart.Chart.Previous3Known = false
	in.Chart.InvalidatedAt = in.At - .5
	in.Chart.LastInput = chartwarmup96.SourceStamp{Time: in.At - .5, Index: 9900, Line: 11000, Last: 0, Valid: false}
	for _, policy := range []string{"A", "B", "AB"} {
		got := assessGate96(t, in, c, policy)
		if got.Decision.Known || got.Decision.Allowed {
			t.Fatalf("%s: %+v", policy, got.Decision)
		}
	}
}
