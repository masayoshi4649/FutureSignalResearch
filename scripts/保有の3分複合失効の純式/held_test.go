package minix5

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	chartwarmup96 "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// fixtureX5 はSource/指標を運転せず、出典付きの公開人工入力を作ります。
//
// 引数: side(int)は±1、kind(string)はDay/Nightです。
// 返り値: TechnicalGateInputは保有方向に三反対が成立する手製値です。
func fixtureX5(side int, kind string) TechnicalGateInput {
	const at = 36000.0
	qtime := at - 1
	t := far80.TechnicalView{TrendKnown: true, ReversalKnown: true, ExitKnown: true, SpikeKnown: true, ATRKnown: true,
		Bar3End: at, Bar15End: at, Close3: 990, EMA8_3: 1000, EMA21_3: 990, EMA8_15: 1010, EMA21_15: 1000,
		Histogram3: 1, PreviousHistogram3: 2, RSI3: 90, PreviousRSI3: 89, TR3: 20, ATR3: 20, PreviousATR3: 20}
	evidence := chartwarmup96.BarEvidence{BarEnd: at, AvailableAt: at, ObservedClock: at + 300,
		Rows: 1, DataKnown: true, HasLastSource: true,
		LastSource: chartwarmup96.SourceStamp{Time: at - 1, Index: 9000, Line: 10000, Last: 990, Valid: true}}
	chart := chartwarmup96.Snapshot{Scene: chartwarmup96.Scene{ID: "人工場", Contract: "人工限月", Start: 18000}, At: at,
		HasObservedClock: true, ObservedClock: at + 300, HasLastInput: true, LastInput: evidence.LastSource,
		Three: evidence, Fifteen: evidence,
		Chart: far82.ChartView{Technical: t, Previous3Known: true, PreviousBar3End: at - 180, PreviousClose3: 995, PreviousEMA8_3: 1000}}
	current := far82.CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: qtime, Received: qtime,
		SourceIndex: 12, SourceLine: 10050, Last: 1005, Bid: 1000, Ask: 1010,
		Buy: far81.CurrentSupport{OFIKnown: true, OFI30: -5, OwnAt: qtime,
			Windows: map[string]far81.CurrentSupportWindow{"未使用": {Known: true, CurrentAt: qtime, EndpointAt: qtime - 5}}},
		Sell: far81.CurrentSupport{OFIKnown: true, OFI30: -5, OwnAt: qtime},
		Night: far81.CurrentStructure{Available: true, Window: "E08", Time: qtime, Index: 12,
			Band: far81.CurrentBandWindow{QuantityKnown: true, Time: qtime, Index: 12, StartTime: qtime - 5,
				BidRefill: 1, AskDeplete: 1, AskRefill: 4, BidDeplete: 3}}}}
	in := TechnicalGateInput{SnapshotID: "人工場-G0001", At: at, Kind: kind, Chart: chart, Recent3: []chartwarmup96.Snapshot{chart}, Current: current}
	if side == -1 {
		for _, c := range []*chartwarmup96.Snapshot{&in.Chart, &in.Recent3[0]} {
			v := &c.Chart.Technical
			v.Close3, v.EMA8_3, v.EMA21_3 = 4000-v.Close3, 4000-v.EMA8_3, 4000-v.EMA21_3
			v.EMA8_15, v.EMA21_15 = 4000-v.EMA8_15, 4000-v.EMA21_15
			v.Histogram3, v.PreviousHistogram3 = -v.Histogram3, -v.PreviousHistogram3
			v.RSI3, v.PreviousRSI3 = 100-v.RSI3, 100-v.PreviousRSI3
			c.Chart.PreviousClose3, c.Chart.PreviousEMA8_3 = 4000-c.Chart.PreviousClose3, 4000-c.Chart.PreviousEMA8_3
			c.LastInput.Last, c.Three.LastSource.Last, c.Fifteen.LastSource.Last = 4000-c.LastInput.Last, 4000-c.Three.LastSource.Last, 4000-c.Fifteen.LastSource.Last
		}
		in.Current.Last, in.Current.Bid, in.Current.Ask = 4000-current.Last, 4000-current.Ask, 4000-current.Bid
		in.Current.Buy.OFI30, in.Current.Sell.OFI30 = 5, 5
		v := &in.Current.Night.Band
		v.BidRefill, v.AskRefill, v.BidDeplete, v.AskDeplete = v.AskRefill, v.BidRefill, v.AskDeplete, v.BidDeplete
	}
	return in
}

// assessX5 は正常人工の純判定と入力不変を同時に検査します。
//
// 引数: t(*testing.T)、in(TechnicalGateInput)、side(int)は人工入力です。
// 返り値: HeldAssessmentは想定外errorのない値copyです。
func assessX5(t *testing.T, in TechnicalGateInput, side int) HeldAssessment {
	t.Helper()
	before, err := json.Marshal(in)
	if err != nil {
		t.Fatal(err)
	}
	got, err := AssessHeldTechnicalExit(in, side)
	if err != nil {
		t.Fatal(err)
	}
	after, err := json.Marshal(in)
	if err != nil || string(before) != string(after) {
		t.Fatal("入力を変更", err)
	}
	return got
}

// TestX5MirrorAndEvidence は買売/日夜の三反対と出典・nullの意味を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestX5MirrorAndEvidence(t *testing.T) {
	for _, kind := range []string{"Day", "Night"} {
		for _, side := range []int{1, -1} {
			in := fixtureX5(side, kind)
			got := assessX5(t, in, side)
			if !got.Decision.Known || !got.Decision.Allowed || got.Decision.Side != side || got.Decision.Policy != "X5" ||
				got.Decision.SnapshotID != in.SnapshotID || len(got.Checks) != 5 ||
				*got.Evidence.SignedCloseEMA != -10 || *got.Evidence.SignedHistogramDelta != -1 || *got.Evidence.SignedQuantity != -5 {
				t.Fatal(got)
			}
			if got.Evidence.Current.SourceIndex == got.Evidence.Three.LastSource.Index || got.Evidence.Current.SourceLine != in.Current.SourceLine {
				t.Fatal("Features連番とbank連番を混同", got.Evidence)
			}
			if kind == "Day" && got.Evidence.Quantity.BidRefill != nil || kind == "Night" && got.Evidence.Quantity.BidRefill == nil {
				t.Fatal("使用しない量値を補完", got.Evidence)
			}
		}
	}
}

// TestX5StrictAndUnknown は等号と既知否定優先/必要未知を少数の境界で検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestX5StrictAndUnknown(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, tc := range []struct {
			name           string
			mutate         func(*TechnicalGateInput)
			known, allowed bool
		}{
			{"価格等号", func(p *TechnicalGateInput) { p.Chart.Chart.Technical.Close3 = p.Chart.Chart.Technical.EMA8_3 }, true, false},
			{"勢い等号", func(p *TechnicalGateInput) {
				p.Chart.Chart.Technical.Histogram3 = p.Chart.Chart.Technical.PreviousHistogram3
			}, true, false},
			{"量等号", func(p *TechnicalGateInput) { p.Current.Buy.OFI30 = 0; p.Current.Sell.OFI30 = 0 }, true, false},
			{"量未知", func(p *TechnicalGateInput) { p.Current.Buy.OFIKnown = false; p.Current.Sell.OFIKnown = false }, false, false},
			{"既知中立と量未知", func(p *TechnicalGateInput) {
				p.Chart.Chart.Technical.Close3 = p.Chart.Chart.Technical.EMA8_3
				p.Current.Buy.OFIKnown = false
				p.Current.Sell.OFIKnown = false
			}, true, false},
			{"技法未知", func(p *TechnicalGateInput) { p.Chart.Chart.Technical.ExitKnown = false }, false, false},
			{"不良BBO", func(p *TechnicalGateInput) { p.Current.Ask = p.Current.Bid }, false, false},
			{"Currentなし", func(p *TechnicalGateInput) { p.Current = far82.CurrentEvidence{} }, false, false},
		} {
			t.Run(tc.name, func(t *testing.T) {
				in := fixtureX5(side, "Day")
				tc.mutate(&in)
				got := assessX5(t, in, side)
				if got.Decision.Known != tc.known || got.Decision.Allowed != tc.allowed {
					t.Fatal(got)
				}
				if !got.Checks[4].Known && (got.Evidence.SignedQuantity != nil || got.Evidence.Quantity.Value != nil) {
					t.Fatal("未知を0へ補完")
				}
			})
		}
	}
}

// TestX5FreshnessAndUnusedBackground は既存15/180境界と未使用15分の非gateを確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestX5FreshnessAndUnusedBackground(t *testing.T) {
	for _, age := range []float64{15, 15.001} {
		in := fixtureX5(1, "Day")
		in.At += age - 1
		in.Chart.At = in.At
		got := assessX5(t, in, 1)
		if got.Decision.Allowed != (age == 15) || got.Decision.Known != (age == 15) {
			t.Fatal("価格鮮度", age, got)
		}
	}
	for _, age := range []float64{179.999, 180} {
		in := fixtureX5(1, "Day")
		in.At += age
		in.Chart.At = in.At
		in.Current.Time, in.Current.Received = in.At-1, in.At-1
		in.Current.Buy.OwnAt, in.Current.Sell.OwnAt = in.Current.Time, in.Current.Time
		got := assessX5(t, in, 1)
		if got.Decision.Allowed != (age < 180) || got.Decision.Known != (age < 180) {
			t.Fatal("3分鮮度", age, got)
		}
	}
	for _, unknown := range []bool{false, true} {
		in := fixtureX5(1, "Night")
		in.Recent3 = nil
		v := &in.Chart.Chart.Technical
		v.TrendKnown, v.SpikeKnown, v.ReversalKnown = false, false, false
		if unknown {
			v.Bar15End, v.EMA8_15, v.EMA21_15 = 0, 0, 0
			in.Chart.Fifteen = chartwarmup96.BarEvidence{}
		} else {
			v.Bar15End -= 900
			in.Chart.Fifteen.BarEnd, in.Chart.Fifteen.AvailableAt = v.Bar15End, v.Bar15End
			in.Chart.Fifteen.LastSource.Time = v.Bar15End - 1
		}
		got := assessX5(t, in, 1)
		if !got.Decision.Known || !got.Decision.Allowed || in.Chart.ObservedClock <= in.At {
			t.Fatal("未使用背景又はdrain上限をgateへ混入", got)
		}
	}
}

// TestX5QuantitySources は同Currentの量出典とstrict等号/未知を独立に確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestX5QuantitySources(t *testing.T) {
	for _, side := range []int{1, -1} {
		in := fixtureX5(side, "Day")
		in.Current.Buy.OwnAt--
		in.Current.Sell.OwnAt--
		if got := assessX5(t, in, side); got.Decision.Known || got.Checks[4].Known {
			t.Fatal("過去OwnAtを現在量へ補完", got)
		}
		for _, tc := range []struct {
			name   string
			mutate func(*TechnicalGateInput)
			known  bool
		}{
			{"別窓", func(p *TechnicalGateInput) { p.Current.Night.Window = "E07" }, false},
			{"古い数量時計", func(p *TechnicalGateInput) { p.Current.Night.Band.Time-- }, false},
			{"古い数量連番", func(p *TechnicalGateInput) { p.Current.Night.Band.Index-- }, false},
			{"数量未知", func(p *TechnicalGateInput) { p.Current.Night.Band.QuantityKnown = false }, false},
			{"数量等号", func(p *TechnicalGateInput) {
				p.Current.Night.Band.BidRefill = 1
				p.Current.Night.Band.AskDeplete = 1
				p.Current.Night.Band.AskRefill = 1
				p.Current.Night.Band.BidDeplete = 1
			}, true},
		} {
			t.Run(tc.name, func(t *testing.T) {
				in := fixtureX5(side, "Night")
				tc.mutate(&in)
				got := assessX5(t, in, side)
				if got.Decision.Known != tc.known || got.Decision.Allowed {
					t.Fatal(got)
				}
			})
		}
	}
	invalid := fixtureX5(1, "Night")
	invalid.Current.Night.Band.Index++
	if _, err := AssessHeldTechnicalExit(invalid, 1); err == nil {
		t.Fatal("未来数量連番を通過")
	}
}

// TestX5MalformedUnused は使用しない値も含め未来/非有限/出典破損を拒否します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestX5MalformedUnused(t *testing.T) {
	for _, tc := range []struct {
		name   string
		mutate func(*TechnicalGateInput)
	}{
		{"未使用RSI非有限", func(p *TechnicalGateInput) { p.Chart.Chart.Technical.RSI3 = math.NaN() }},
		{"未使用15分未来", func(p *TechnicalGateInput) { p.Chart.Fifteen.AvailableAt = p.At + 1 }},
		{"未使用窓未来", func(p *TechnicalGateInput) {
			p.Current.Buy.Windows["未使用"] = far81.CurrentSupportWindow{CurrentAt: p.Current.Time + 1}
		}},
		{"未使用窓非有限", func(p *TechnicalGateInput) {
			p.Current.Buy.Windows["未使用"] = far81.CurrentSupportWindow{Value: math.Inf(1)}
		}},
		{"未使用短秒未来", func(p *TechnicalGateInput) { p.Current.Short.Five.Endpoint = p.Current.Time + 1 }},
		{"未使用E08負数量", func(p *TechnicalGateInput) { p.Current.Night.Band.BidRefill = -1 }},
		{"3分未来", func(p *TechnicalGateInput) { p.Chart.Three.AvailableAt = p.At + 1 }},
		{"Recent3別場", func(p *TechnicalGateInput) { p.Recent3[0].Scene.ID = "別場" }},
		{"Recent3未来", func(p *TechnicalGateInput) { p.Recent3[0].At = p.At + 1 }},
		{"現在未来", func(p *TechnicalGateInput) { p.Current.Time = p.At + 1 }},
		{"原行欠落", func(p *TechnicalGateInput) { p.Current.SourceLine = 0 }},
		{"別市場", func(p *TechnicalGateInput) { p.Current.Reference = "TOPIX" }},
		{"hist差overflow", func(p *TechnicalGateInput) {
			p.Chart.Chart.Technical.Histogram3 = math.MaxFloat64
			p.Chart.Chart.Technical.PreviousHistogram3 = -math.MaxFloat64
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			in := fixtureX5(1, "Day")
			tc.mutate(&in)
			if _, err := AssessHeldTechnicalExit(in, 1); err == nil {
				t.Fatal("破損を通過")
			}
		})
	}
	if _, err := AssessHeldTechnicalExit(fixtureX5(1, "Day"), 0); err == nil {
		t.Fatal("不正side")
	}
	var typed TechnicalGateInput
	if err := json.Unmarshal([]byte(`{"current":{"time":"壊れた型"}}`), &typed); err == nil {
		t.Fatal("型破損JSONを通過")
	}
}

// TestX5DeepValueAndFailed は深いmap不変・出力独立と固定80の二式を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestX5DeepValueAndFailed(t *testing.T) {
	in := fixtureX5(1, "Day")
	before, _ := json.Marshal(in)
	got := assessX5(t, in, 1)
	got.Evidence.Three.LastSource.Last = 123
	*got.Evidence.SignedCloseEMA = 999
	got.Checks[0].Reason = "出力のみ変更"
	after, _ := json.Marshal(in)
	if string(before) != string(after) || !reflect.DeepEqual(in.Current.Buy.Windows, fixtureX5(1, "Day").Current.Buy.Windows) {
		t.Fatal("入力又はmapを変更")
	}
	for _, side := range []int{1, -1} {
		for _, price := range []float64{-1, 0, 1} {
			for _, delta := range []float64{-1, 0, 1} {
				in := fixtureX5(side, "Day")
				v := &in.Chart.Chart.Technical
				v.Close3 = v.EMA8_3 + float64(side)*price
				v.Histogram3 = v.PreviousHistogram3 + float64(side)*delta
				got := assessX5(t, in, side)
				if !got.Decision.Known || got.Decision.Allowed != v.Failed(side) {
					t.Fatal("固定80二式との差", side, price, delta)
				}
			}
		}
	}
}

// TestExportX5Fixture は明示環境変数時だけ、実Go型marshalの再用人工を新規保存します。
//
// 引数: t(*testing.T)、環境変数X5_FIXTURE_OUT(string)は未使用のJSONパスです。
// 返り値: ありません。未指定はskipで、Source/金融/市場運転は行いません。
func TestExportX5Fixture(t *testing.T) {
	path := os.Getenv("X5_FIXTURE_OUT")
	if path == "" {
		t.Skip("明示した新規出力先だけ")
	}
	type row struct {
		Name       string             `json:"name"`
		Input      TechnicalGateInput `json:"input"`
		Side       int                `json:"side"`
		Assessment *HeldAssessment    `json:"assessment"`
		Error      string             `json:"error"`
	}
	rows := []row{}
	for _, kind := range []string{"Day", "Night"} {
		for _, side := range []int{1, -1} {
			in := fixtureX5(side, kind)
			rows = append(rows, row{Name: fmt.Sprintf("%s_side%+d_三反対", kind, side), Input: in, Side: side})
		}
	}
	for _, name := range []string{"価格等号", "量未知", "空Current", "15分未知", "FutureCurrent", "BadSide"} {
		in := fixtureX5(1, "Day")
		side := 1
		switch name {
		case "価格等号":
			in.Chart.Chart.Technical.Close3 = in.Chart.Chart.Technical.EMA8_3
		case "量未知":
			in.Current.Buy.OFIKnown = false
		case "空Current":
			in.Current = far82.CurrentEvidence{}
		case "15分未知":
			in.Recent3 = nil
			in.Chart.Chart.Technical.TrendKnown = false
			in.Chart.Chart.Technical.Bar15End = 0
			in.Chart.Fifteen = chartwarmup96.BarEvidence{}
		case "FutureCurrent":
			in.Current.Time = in.At + 1
		case "BadSide":
			side = 0
		}
		rows = append(rows, row{Name: name, Input: in, Side: side})
	}
	for i := range rows {
		got, err := AssessHeldTechnicalExit(rows[i].Input, rows[i].Side)
		if err != nil {
			rows[i].Error = err.Error()
		} else {
			rows[i].Assessment = &got
		}
	}
	value := map[string]any{"scope": "手製の保有純判定だけ・Source/金融/市場0", "cases": rows,
		"固定96品質源SHA256": "3ba3c2c8d5b67635b9f2edab076ec9cce9785fea090e8ba87191a65142985fbf",
		"仕様候補SHA256":    "50dd28465bec51eb59e7d05e892cb3383bca99964cabe5e0f3b7caa9c0f771a1"}
	body, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = file.Write(append(body, '\n')); err != nil {
		file.Close()
		t.Fatal(err)
	}
	if err = file.Close(); err != nil {
		t.Fatal(err)
	}
}
