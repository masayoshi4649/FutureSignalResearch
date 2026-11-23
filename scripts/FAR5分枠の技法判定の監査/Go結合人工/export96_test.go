package minichart

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

type pureCase96 struct {
	Input      TechnicalGateInput  `json:"input"`
	Candidate  EntryCandidate      `json:"candidate"`
	Policy     string              `json:"policy"`
	Assessment TechnicalAssessment `json:"assessment"`
}

type combinedFixture96 struct {
	Session         Session                 `json:"session"`
	Scope           string                  `json:"scope"`
	Steps           []fixtureStep94         `json:"steps"`
	Timers          []fixtureTimer94        `json:"timers"`
	Grids           []float64               `json:"grids"`
	Events          []fixtureEvent95        `json:"events"`
	Actors          map[string]ActualResult `json:"actors"`
	ChartGrids      []TechnicalGateInput    `json:"chart_grids"`
	GateAssessments []GateAssessmentRecord  `json:"gate_assessments"`
}

// gateContextForExport96 は停止済み純技法人工を実候補の場時計/価格へ平行移動します。
//
// 引数: side(int)、role(string)、session(Session)、at(float64)、q(QuoteStamp)、id(string)、unknown(bool)は人工条件です。
// 返り値: TechnicalGateInputは人工公開値で、実ChartBank/原板からの生成は主張しません。
func gateContextForExport96(side int, role string, session Session, at float64, q QuoteStamp, id string, unknown bool) TechnicalGateInput {
	in, original := technicalFixture96(side, role)
	offset := q.Last - original.Quote.Last
	lastEnd := session.Start + 180*math.Floor((at-session.Start)/180)
	for i := range in.Recent3 {
		p := &in.Recent3[i]
		end := lastEnd - float64(2-i)*180
		fifteen := math.Floor(end/900) * 900
		p.Scene.ID, p.Scene.Contract, p.Scene.Start = session.ID, "人工限月", session.Start
		p.At, p.ObservedClock = end, at
		p.LastInput.Time = end - 1
		p.LastInput.Last += offset
		p.Three.BarEnd, p.Three.AvailableAt, p.Three.ObservedClock = end, end, at
		p.Three.LastSource.Time = end - 1
		p.Three.LastSource.Last += offset
		p.Fifteen.BarEnd, p.Fifteen.AvailableAt, p.Fifteen.ObservedClock = fifteen, fifteen, at
		p.Fifteen.LastSource.Time = fifteen - 1
		p.Fifteen.LastSource.Last += offset
		v := &p.Chart.Technical
		v.Bar3End, v.Bar15End = end, fifteen
		v.Close3, v.EMA8_3, v.EMA21_3 = v.Close3+offset, v.EMA8_3+offset, v.EMA21_3+offset
		v.EMA8_15, v.EMA21_15 = v.EMA8_15+offset, v.EMA21_15+offset
		p.Chart.PreviousClose3 += offset
		p.Chart.PreviousEMA8_3 += offset
		p.Chart.PreviousBar3End = end - 180
	}
	in.SnapshotID, in.At, in.Kind = id, at, session.Kind
	in.Chart = in.Recent3[2]
	in.Chart.At = at
	c := &in.Current
	c.Reference, c.Time, c.Received = "NK225", q.Time, q.Time
	c.SourceIndex, c.SourceLine, c.Last, c.Bid, c.Ask = q.Index, q.SourceLine, q.Last, q.Bid, q.Ask
	c.Buy.OwnAt, c.Sell.OwnAt = q.Time, q.Time
	for key, w := range c.Buy.Windows {
		w.CurrentAt, w.EndpointAt = q.Time, q.Time-5
		c.Buy.Windows[key] = w
	}
	c.Night.Time, c.Night.Index = q.Time, q.Index
	c.Night.Band.Time, c.Night.Band.Index, c.Night.Band.StartTime = q.Time, q.Index, q.Time-5
	if unknown {
		c.Buy.OFIKnown, c.Sell.OFIKnown = false, false
	}
	return in
}

// combinedActors96 はRootの正式16config/keyをそのまま再用します。
//
// 引数: t(*testing.T)、s(Session)は試験器と場です。
// 返り値: map/[]stringは独立16口座とRoot順のkeyです。
func combinedActors96(t *testing.T, s Session) (map[string]*ActualBook, []string) {
	t.Helper()
	actors, keys := map[string]*ActualBook{}, []string{}
	for _, cfg := range allConfigs(s) {
		b, err := NewActualBook(s, cfg)
		if err != nil || b.result.Key != configKey(cfg) || actors[configKey(cfg)] != nil {
			t.Fatal("Root16構成/key", err)
		}
		actors[b.result.Key] = b
		keys = append(keys, b.result.Key)
	}
	if len(keys) != 16 {
		t.Fatal("16Actor集合")
	}
	return actors, keys
}

// captureCombined96 は手製Source/ATR/公開技法を同じ原行時計へ16口座同時に流します。
//
// 引数: t(*testing.T)、side(int)、role(string)、capacity(bool)は試験器と人工種です。
// 返り値: combinedFixture96/[]pureCase96は金融Go型と実callback全field列です。
func captureCombined96(t *testing.T, side int, role string, capacity bool) (combinedFixture96, []pureCase96) {
	t.Helper()
	s := session94()
	actors, keys := combinedActors96(t, s)
	src := newFixtureSource94()
	out := combinedFixture96{Session: s,
		Scope: "Go型API結合人工。Source/ATR/公開技法/Currentは手製。実ChartBank形成・原板・自然Shadow・旧95正本の全面同値は未計測。G0旧95全文回帰は別の固定金融人工証拠。",
		Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}, Grids: []float64{}, Events: []fixtureEvent95{},
		Actors: map[string]ActualResult{}, ChartGrids: []TechnicalGateInput{}, GateAssessments: []GateAssessmentRecord{}}
	pure := []pureCase96{}
	index := int64(0)
	var last QuoteStamp
	feed := func(at, move float64, news []native.Signal, cancellations []string) {
		o := observation95(s, side, index, at, move, 20)
		line := index + 10050
		batch := src.step(t, o, line, news, cancellations)
		before, _ := json.Marshal(batch)
		for _, key := range keys {
			if err := actors[key].OnNativeStep(o, line, []NativeBatch{batch}); err != nil {
				t.Fatal(key, err)
			}
		}
		after, _ := json.Marshal(batch)
		if !reflect.DeepEqual(before, after) {
			t.Fatal("金融が共有Sourceを書換え")
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "quote", Index: len(out.Steps)})
		out.Steps = append(out.Steps, fixtureStep94{Observation: o, SourceLine: line, Batches: []NativeBatch{batch}})
		last = quoteActual(o, line)
		index++
	}
	grid := func(at float64, unknown bool) {
		context := gateContextForExport96(side, role, s, at, last, fmt.Sprintf("%s-G%04d", s.ID, len(out.ChartGrids)+1), unknown)
		out.ChartGrids = append(out.ChartGrids, valueCopy(context))
		for _, key := range keys {
			b := actors[key]
			var gate EntryGate
			if policy := b.result.Config.GatePolicy; policy != "" {
				gate = func(c EntryCandidate) (GateDecision, error) {
					assessment, err := AssessTechnicalGate(context, c, policy)
					if err != nil {
						return GateDecision{}, err
					}
					out.GateAssessments = append(out.GateAssessments, GateAssessmentRecord{Key: key, Ordinal: c.Ordinal, Source: valueCopy(c.Source), Assessment: valueCopy(assessment)})
					pure = append(pure, pureCase96{Input: valueCopy(context), Candidate: valueCopy(c), Policy: policy, Assessment: valueCopy(assessment)})
					return assessment.Decision, nil
				}
			}
			before := b.Snapshot()
			if err := b.OnEntryGridWithGate(at, gate); err != nil {
				t.Fatal(key, err)
			}
			after := b.Snapshot()
			if !reflect.DeepEqual(before.Account, after.Account) || len(before.Fills) != len(after.Fills) {
				t.Fatal("gridがMTM/約定を実行")
			}
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "grid", Index: len(out.Grids)})
		out.Grids = append(out.Grids, at)
	}
	if !capacity {
		g := s.Start + 1800
		feed(g-1, 0, []native.Signal{birth94("結合出生", side, 5)}, nil)
		feed(g-1, 0, nil, nil)
		grid(g, false)
		for i, move := range []float64{0, 0, 30, 80, 40, 20, 20, 0} {
			at := g + float64(i)
			if i == 5 {
				at -= .9
			}
			var news []native.Signal
			if i == 2 {
				news = []native.Signal{close94("結合部分", "結合出生", side, 2)}
			}
			if i == 6 {
				news = []native.Signal{close94("結合全残", "結合出生", side, 3)}
			}
			feed(at, move, news, nil)
		}
		grid(g+300, false)
	} else {
		g := s.Start + 2700
		feed(g-302, 0, []native.Signal{birth94("先行8", side, 8)}, nil)
		feed(g-301, 0, nil, nil)
		grid(g-300, false)
		feed(g-299, 0, nil, nil)
		feed(g-1, 0, []native.Signal{birth94("後続5", side, 5), birth94("取消1", side, 1)}, []string{"取消1"})
		feed(g-.9, 0, nil, nil)
		grid(g, false)
		feed(g+.1, 0, []native.Signal{close94("先行全8", "先行8", side, 8), close94("後続全5", "後続5", side, 5)}, nil)
		feed(g+1.1, 0, nil, nil)
		feed(g+299, 0, []native.Signal{birth94("必要未知3", side, 3)}, nil)
		feed(g+299.1, 0, nil, nil)
		grid(g+300, true)
		feed(g+300.1, 0, []native.Signal{close94("未知源全3", "必要未知3", side, 3)}, nil)
		feed(g+301.1, 0, nil, nil)
		grid(g+600, false)
	}
	nonzero := 0
	for _, key := range keys {
		r, err := actors[key].Finish()
		if err != nil || !r.Complete || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 {
			t.Fatal(key, "人工未完", err)
		}
		if r.Totals.EntryQuantity > 0 {
			nonzero++
		}
		if !capacity {
			accepted := r.Config.GatePolicy == "" || r.Config.GatePolicy == role || r.Config.GatePolicy == "AB"
			want := 0.0
			if accepted {
				want = 16615 - r.Config.SlipPts*1000
			}
			if r.Totals.NetYen != want || (r.Totals.EntryQuantity > 0) != accepted {
				t.Fatal(key, "鏡像の手計算", r.Totals, want)
			}
		} else {
			p := r.EntryOpportunities[1]
			if r.Config.GatePolicy != "B" && (p.Requested != 2 || p.Available != 2) {
				t.Fatal(key, "旧min/cap2", p)
			}
			if r.EntryOpportunities[2].Gate != nil || r.EntryOpportunities[2].Status != "expired" || r.Metrics.NativeCancels != 1 {
				t.Fatal("Source取消を技法へ流した")
			}
			if r.Config.GatePolicy == "A" || r.Config.GatePolicy == "AB" {
				p = r.EntryOpportunities[3]
				if p.Gate == nil || !p.RequiredUnknown || !p.Consumed || p.Status != "expired" {
					t.Fatal("必要未知を後枠へ延期", p)
				}
			}
		}
		out.Actors[key] = r
	}
	if nonzero != 12 {
		t.Fatal("非0口座の想定12", nonzero)
	}
	return out, pure
}

// TestExportCombined96 は停止済み純技法と16金融の非0結合人工をGo型のまま出力します。
//
// 引数: t(*testing.T)、環境FAR96_COMBINED_OUTは存在しない出力フォルダです。
// 返り値: ありません。原板/市場/旧正本の擬似指紋は作りません。
func TestExportCombined96(t *testing.T) {
	root := os.Getenv("FAR96_COMBINED_OUT")
	if root == "" {
		t.Skip("FAR96_COMBINED_OUTの明示時だけGo型人工を出力")
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("新規出力先だけ", err)
	}
	if err := os.MkdirAll(root, 0755); err != nil {
		t.Fatal(err)
	}
	pure := []pureCase96{}
	for _, side := range []int{1, -1} {
		for _, role := range []string{"A", "B", "容量取消未知"} {
			model := role
			if role == "容量取消未知" {
				model = "A"
			}
			fixture, cases := captureCombined96(t, side, model, role == "容量取消未知")
			pure = append(pure, cases...)
			body, err := json.MarshalIndent(fixture, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			name := fmt.Sprintf("方向%d_%s.json", side, role)
			if err := os.WriteFile(filepath.Join(root, name), append(body, '\n'), 0644); err != nil {
				t.Fatal(err)
			}
		}
	}
	body, err := json.MarshalIndent(struct {
		Scope string       `json:"scope"`
		Cases []pureCase96 `json:"cases"`
	}{"同じ人工callbackの純全field比較列。金融/価格/Source自然生成の証明とは分ける。", pure}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "純技法列.json"), append(body, '\n'), 0644); err != nil {
		t.Fatal(err)
	}
}
