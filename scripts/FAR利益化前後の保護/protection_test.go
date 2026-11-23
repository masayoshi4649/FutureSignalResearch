package minigrossguard100

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	e3 "github.com/masayoshi4649/SessionTradeExecuter/minie3"
	prior "github.com/masayoshi4649/SessionTradeExecuter/minientry99"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

type testStep100 struct {
	Observation Observation   `json:"observation"`
	SourceLine  int64         `json:"source_line"`
	Batches     []NativeBatch `json:"batches"`
}
type testTimer100 struct {
	At      float64       `json:"at"`
	Batches []NativeBatch `json:"batches"`
}
type testEvent100 struct {
	Kind  string `json:"kind"`
	Index int    `json:"index"`
}
type testFixture100 struct {
	Session         Session                       `json:"session"`
	Scope           string                        `json:"scope"`
	Steps           []testStep100                 `json:"steps"`
	Timers          []testTimer100                `json:"timers"`
	Grids           []float64                     `json:"grids"`
	Events          []testEvent100                `json:"events"`
	Actors          map[string]ActualResult       `json:"actors"`
	Baseline99H0    map[string]prior.ActualResult `json:"baseline99_h0"`
	ChartGrids      []TechnicalGateInput          `json:"chart_grids"`
	GateAssessments []testAssessment100           `json:"gate_assessments"`
}

type testAssessment100 struct {
	Key        string                 `json:"key"`
	Ordinal    int                    `json:"ordinal"`
	Source     SourceIdentity         `json:"source"`
	Candidate  EntryCandidate         `json:"candidate"`
	Assessment e3.TechnicalAssessment `json:"assessment"`
}

// equal100 は全JSONを除外なしで比較します。
//
// 引数: t(*testing.T)、a/b(any)、label(string)は試験器・比較値・説明です。
// 返り値: ありません。H0の追加omitempty欄が現れた場合も差になります。
func equal100(t *testing.T, a, b any, label string) {
	t.Helper()
	x, e := json.Marshal(a)
	if e != nil {
		t.Fatal(e)
	}
	y, e := json.Marshal(b)
	if e != nil {
		t.Fatal(e)
	}
	if !bytes.Equal(x, y) {
		t.Fatal(label, "全JSON差")
	}
}

// priorBatches100 は元通知を別module型へ全field対応します。
//
// 引数: input([]NativeBatch)は元の公開順です。
// 返り値: []prior.NativeBatchは同じDeltaです。nilも維持します。
func priorBatches100(input []NativeBatch) []prior.NativeBatch {
	if input == nil {
		return nil
	}
	out := make([]prior.NativeBatch, len(input))
	for i, v := range input {
		out[i] = prior.NativeBatch{Method: v.Method, Delta: v.Delta}
	}
	return out
}

// entryGate100 は手製の公開技法を本来のE3S純式へ結びます。
//
// 引数: c(EntryCandidate)は金融の旧適格性と数量計算を終えた現在候補です。
// 返り値: GateDecision/errorは停止純式の判断又は出典不整合です。
func entryGate100(c EntryCandidate) (GateDecision, error) {
	a, e := AssessEntryTechnical(context100(c, "正常"), c, "E3S")
	d := a.Decision
	return GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, e
}

// priorGate100 は旧99にも同じ全field現在候補と純E3Sを渡します。
//
// 引数: c(prior.EntryCandidate)は旧99の現在候補です。
// 返り値: prior.GateDecision/errorは同じ公開純式の結果です。
func priorGate100(c prior.EntryCandidate) (prior.GateDecision, error) {
	s := c.Source
	v := EntryCandidate{Ordinal: c.Ordinal, At: c.At, Side: c.Side, Quote: c.Quote, Available: c.Available, Quantity: c.Quantity, Source: SourceIdentity{Method: s.Method, SignalID: s.SignalID, Kind: s.Kind, Parent: s.Parent, SourceID: s.SourceID, QuantityMicro: s.QuantityMicro, BirthQuantity: s.BirthQuantity, BirthTime: s.BirthTime, BirthQuote: s.BirthQuote}}
	d, e := entryGate100(v)
	return prior.GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, e
}

// wave100 は手製Source/ATR/技法だけを同じ12口座と旧H0四へ渡します。
//
// 引数: t(*testing.T)、side(int)、mode(string)は試験器・鏡像・事前境界です。
// 返り値: testFixture100/intは全公開入力/最終12と旧4、全時点JSON比較数です。
func wave100(t *testing.T, side int, mode string) (testFixture100, int) {
	t.Helper()
	s := session()
	grid := s.Start + 1800
	out := testFixture100{Session: s, Scope: "未採番100の手製Source/ATR/Chart snapshotを公開E3Sへ結ぶAPI人工。元Source戦略/CSV/原板/技法形成/市場成績ではない。", Steps: []testStep100{}, Timers: []testTimer100{}, Grids: []float64{}, Events: []testEvent100{}, Actors: map[string]ActualResult{}, Baseline99H0: map[string]prior.ActualResult{}}
	actors := map[string]*ActualBook{}
	keys := []string{}
	old := map[string]*prior.ActualBook{}
	for _, exit := range []string{"", "H0", "HG"} {
		for _, cost := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", HarvestPolicy: exit, SlipPts: cost, DelaySeconds: delay}
				b, e := NewActualBook(s, cfg)
				if e != nil {
					t.Fatal(e)
				}
				actors[b.Snapshot().Key] = b
				keys = append(keys, b.Snapshot().Key)
				if exit == "H0" {
					p, e := prior.NewActualBook(s, prior.ActorConfig{Policy: "P0", EntryTiming: "B5Q", GatePolicy: "E3S", HarvestPolicy: "H0", SlipPts: cost, DelaySeconds: delay})
					if e != nil {
						t.Fatal(e)
					}
					old[b.Snapshot().Key] = p
				}
			}
		}
	}
	comparisons := 0
	compare := func() {
		for key, b := range old {
			equal100(t, actors[key].Snapshot(), b.Snapshot(), mode+"/旧99H0")
			comparisons++
		}
	}
	compare()
	src := newSource()
	index := int64(0)
	feed := func(at, move float64, bad bool, signals ...native.Signal) {
		o := observation(at, move, side, index, bad)
		q := stamp(o, index+20)
		batch := src.step(q, signals)
		before, _ := json.Marshal(batch)
		for _, b := range actors {
			if e := b.OnNativeStep(o, index+20, []NativeBatch{batch}); e != nil {
				t.Fatal(mode, b.Snapshot().Key, e)
			}
		}
		for _, b := range old {
			if e := b.OnNativeStep(o, index+20, priorBatches100([]NativeBatch{batch})); e != nil {
				t.Fatal(e)
			}
		}
		after, _ := json.Marshal(batch)
		if !bytes.Equal(before, after) {
			t.Fatal("共用Source通知の変更")
		}
		out.Events = append(out.Events, testEvent100{Kind: "quote", Index: len(out.Steps)})
		out.Steps = append(out.Steps, testStep100{Observation: o, SourceLine: index + 20, Batches: []NativeBatch{batch}})
		index++
		compare()
	}
	feed(grid-1, 0, false, birth("保護出生", side, 5))
	feed(grid-.9, 0, false)
	for _, key := range keys {
		b := actors[key]
		callback := func(c EntryCandidate) (GateDecision, error) {
			input := context100(c, "正常")
			if len(out.ChartGrids) == 0 {
				out.ChartGrids = append(out.ChartGrids, input)
			} else {
				equal100(t, input, out.ChartGrids[0], "共有現在技法文脈")
			}
			assessment, e := AssessEntryTechnical(input, c, "E3S")
			if e != nil {
				return GateDecision{}, e
			}
			out.GateAssessments = append(out.GateAssessments, testAssessment100{Key: key, Ordinal: c.Ordinal, Source: c.Source, Candidate: c, Assessment: assessment})
			d := assessment.Decision
			return GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, nil
		}
		if e := b.OnEntryGridWithGate(grid, callback); e != nil {
			t.Fatal(e)
		}
	}
	for _, b := range old {
		if e := b.OnEntryGridWithGate(grid, priorGate100); e != nil {
			t.Fatal(e)
		}
	}
	out.Grids = append(out.Grids, grid)
	out.Events = append(out.Events, testEvent100{Kind: "grid", Index: 0})
	compare()
	feed(grid, 0, false)
	feed(grid+1, 0, false)
	for _, b := range actors {
		p := b.Snapshot().Positions[0]
		if p.GrossGuard != nil || p.ProtectionActive || p.PeakGain != -10 || !p.HasMark || p.FloorGain != nil {
			t.Fatal("取得時に架空peak0/ガード/利益flagを作成", p)
		}
	}
	activateGross := func() {
		feed(grid+2, 10.5, true)
		for _, b := range actors {
			if b.Snapshot().Positions[0].GrossGuard != nil {
				t.Fatal("異常BBOでガード起動")
			}
		}
		feed(grid+2, 10.5, false)
		for _, b := range actors {
			r := b.Snapshot()
			p := r.Positions[0]
			if r.Config.HarvestPolicy == "HG" {
				if p.GrossGuard == nil || p.GrossGuard.Activation.GainPoints != .5 || p.GrossGuard.Activation.UnitNet > 0 || p.GrossGuard.FirstHit != nil || p.ProtectionActive || p.Activation != nil || p.FloorGain != nil {
					t.Fatal("利益前の実観測/旧flagの分離", r.Key, p)
				}
			} else if p.GrossGuard != nil {
				t.Fatal("他出口にHG欄")
			}
		}
	}
	switch mode {
	case "順行なし":
		feed(grid+2, 10, false)
		feed(grid+3, 0, false)
		for _, b := range actors {
			p := b.Snapshot().Positions[0]
			if p.GrossGuard != nil || p.ProtectionActive {
				t.Fatal("正の進行なしで起動")
			}
		}
	case "費用前順行から戻る":
		activateGross()
		feed(grid+3, 10, true)
		for _, b := range actors {
			if g := b.Snapshot().Positions[0].GrossGuard; g != nil && g.FirstHit != nil {
				t.Fatal("異常BBOでfirst_hit")
			}
		}
		feed(grid+3, 10, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "HG" {
				p := r.Positions[0]
				if p.GrossGuard.FirstHit == nil || p.GrossGuard.FirstHit.GainPoints != 0 || p.ProtectionActive || r.Metrics.GrossGuardExitRequests != 1 || r.Metrics.ProtectionExitRequests != 0 || r.Metrics.SourceExitRequests != 0 {
					t.Fatal("HG等号/独立要求", r.Key, p, r.Metrics)
				}
				last := r.Orders[len(r.Orders)-1]
				if last.GrossGuardPoint == nil || last.ProtectionPoint != nil || last.Reason != GrossGuardExitReason || len(r.Fills) != 1 {
					t.Fatal("HG要求出典/同原行fill")
				}
			}
		}
		feed(grid+3, 5, false)
		feed(grid+4, 0, false)
	case "利益後へ移行":
		activateGross()
		feed(grid+3, 30, false)
		for _, b := range actors {
			r := b.Snapshot()
			p := r.Positions[0]
			if !p.ProtectionActive || p.Activation == nil || p.Activation.UnitNet <= 0 {
				t.Fatal("strictu正益の起動")
			}
			if r.Config.HarvestPolicy == "HG" {
				if p.GrossGuard.ProfitTransition == nil || r.Metrics.GrossGuardExitRequests != 0 || r.Metrics.ProtectionExitRequests != 1 || p.FloorGain == nil || *p.FloorGain < 20 {
					t.Fatal("HG後の旧H0床", r.Key, p, r.Metrics)
				}
			}
		}
		feed(grid+3, 20, false)
		feed(grid+4, 10, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "HG" {
				p := r.Positions[0]
				if !p.ProtectionActive || p.FloorGain == nil || *p.FloorGain < 20 || r.Metrics.GrossGuardExitRequests != 0 {
					t.Fatal("利益後に名目0へ戻った")
				}
			}
		}
	case "HG予約後正益":
		activateGross()
		feed(grid+3, 10, false)
		feed(grid+3, 30, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "HG" {
				p := r.Positions[0]
				if !p.ProtectionActive || p.GrossGuard.ProfitTransition == nil || r.Metrics.ProtectionExitRequests != 0 || r.Metrics.GrossGuardExitRequests != 1 {
					t.Fatal("予約後移行/二重要求", r.Key, p, r.Metrics)
				}
				if r.Orders[len(r.Orders)-1].Reason != GrossGuardExitReason || r.Orders[len(r.Orders)-1].GrossGuardPoint == nil {
					t.Fatal("移行で受理済HGの理由を変更")
				}
			}
		}
		feed(grid+4, 10, false)
	case "HG予約のForce":
		activateGross()
		feed(grid+3, 10, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "HG" {
				if r.Metrics.GrossGuardExitRequests != 1 || r.Positions[0].Reserved != 5 || r.Orders[len(r.Orders)-1].Status != "pending" {
					t.Fatal("Force前HG予約")
				}
			}
		}
	case "Source部分先行", "Source全予約":
		activateGross()
		quantity := 3
		if mode == "Source全予約" {
			quantity = 5
		}
		feed(grid+3, 10, false, closeSignal("元返済", "玉-保護出生", side, quantity))
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "HG" {
				p := r.Positions[0]
				want := 1
				if quantity == 5 {
					want = 0
				}
				if r.Metrics.SourceExitRequests != 1 || r.Metrics.GrossGuardExitRequests != want || r.Metrics.ProtectionExitRequests != 0 || p.Reserved != 5 {
					t.Fatal("Source優先とHG未予約残", r.Key, p, r.Metrics)
				}
				for _, o := range r.Orders {
					if o.GrossGuardPoint != nil && o.Quantity != 5-quantity {
						t.Fatal("HGがSource予約を飛越した")
					}
				}
			}
		}
		feed(grid+3, 5, false)
		feed(grid+4, 0, false)
	case "費用後正益が先":
		feed(grid+2, 30, false)
		for _, b := range actors {
			r := b.Snapshot()
			p := r.Positions[0]
			if !p.ProtectionActive || p.GrossGuard != nil {
				t.Fatal("u正益を利益前ガードへ偽装")
			}
		}
		feed(grid+3, 0, false)
	case "P0非緩和追尾":
		activateGross()
		feed(grid+3, 30, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "" {
				p := r.Positions[0]
				if !p.ProtectionActive || p.FloorGain == nil || *p.FloorGain != 0 || r.Metrics.ProtectionExitRequests != 0 {
					t.Fatal("P0へH0即時全返済を混入")
				}
			}
		}
		feed(grid+4, 60, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "" {
				p := r.Positions[0]
				if p.PeakGain != 50 || p.ATR == nil || p.ATR.Width != 40 || *p.FloorGain != 10 {
					t.Fatal("旧固定2ATR追尾", p)
				}
			}
		}
		feed(grid+5, 40, false)
		for _, b := range actors {
			r := b.Snapshot()
			if r.Config.HarvestPolicy == "" && *r.Positions[0].FloorGain != 10 {
				t.Fatal("P0の床を緩めた")
			}
		}
		feed(grid+6, 20, false)
		feed(grid+6, 10, false)
		feed(grid+7, 0, false)
	case "10pt費用窓":
		feed(grid+2, 20, false)
		for _, b := range actors {
			r := b.Snapshot()
			p := r.Positions[0]
			if r.Config.HarvestPolicy != "HG" {
				continue
			}
			if r.Config.SlipPts == 0 {
				if p.GrossGuard != nil || !p.ProtectionActive {
					t.Fatal("C0の10ptは既に費用後正益")
				}
			} else {
				if p.GrossGuard == nil || p.GrossGuard.Activation.GainPoints != 10 || p.GrossGuard.Activation.UnitNet != -77 || p.ProtectionActive {
					t.Fatal("C5の10pt利益前窓")
				}
			}
		}
		feed(grid+3, 10, false)
		feed(grid+4, 0, false)
	default:
		t.Fatal("未定義波形")
	}
	force := NativeBatch(src.force(s.ForceClose))
	for _, b := range actors {
		before := b.Snapshot()
		if e := b.OnNativeForce(s.ForceClose, []NativeBatch{force}); e != nil {
			t.Fatal(e)
		}
		after := b.Snapshot()
		if len(before.Fills) != len(after.Fills) || before.Account.Count != after.Account.Count {
			t.Fatal("Forceで偽fill/MTM")
		}
	}
	for _, b := range old {
		if e := b.OnNativeForce(s.ForceClose, priorBatches100([]NativeBatch{force})); e != nil {
			t.Fatal(e)
		}
	}
	out.Events = append(out.Events, testEvent100{Kind: "force", Index: 0})
	out.Timers = append(out.Timers, testTimer100{At: s.ForceClose, Batches: []NativeBatch{force}})
	compare()
	feed(s.ForceClose, 0, false)
	feed(s.ForceClose+1, 0, false)
	for key, b := range actors {
		r, e := b.Finish()
		if e != nil {
			t.Fatal(mode, key, e)
		}
		if !r.Complete || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 {
			t.Fatal("最終0")
		}
		out.Actors[key] = r
		counts := map[string]int{"Source": 0, "H": 0, "HG": 0}
		for _, o := range r.Orders {
			if o.Kind != "exit" {
				continue
			}
			switch {
			case o.GrossGuardPoint != nil:
				counts["HG"]++
				if o.ProtectionPoint != nil || o.Reason != GrossGuardExitReason {
					t.Fatal("HG分類")
				}
			case o.ProtectionPoint != nil:
				counts["H"]++
			default:
				counts["Source"]++
			}
		}
		if counts["HG"] != r.Metrics.GrossGuardExitRequests || counts["H"] != r.Metrics.ProtectionExitRequests || counts["Source"] != r.Metrics.SourceExitRequests {
			t.Fatal("三原因の排他的counter")
		}
	}
	for key, b := range old {
		r, e := b.Finish()
		if e != nil {
			t.Fatal(e)
		}
		equal100(t, out.Actors[key], r, mode+"/H0最終")
		comparisons++
		out.Baseline99H0[key] = r
	}
	return out, comparisons
}

// Test100CostWindow は10pt刻みの同一価格でもC0/C5の起動段階が異なることを検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。価格条件の最適化ではなく、指定費用77/1077円の固定算術です。
func Test100CostWindow(t *testing.T) {
	for _, side := range []int{-1, 1} {
		wave100(t, side, "10pt費用窓")
	}
}

// Test100ProtectModes は九波形を買売対称の同じ十二口座へ接続します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。全入口は実純E3S、HG状態/既存H0/旧P0を分離します。
func Test100ProtectModes(t *testing.T) {
	total, comparisons := 0, 0
	mirrors := map[string]map[int]any{}
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"順行なし", "費用前順行から戻る", "利益後へ移行", "HG予約後正益", "HG予約のForce", "Source部分先行", "Source全予約", "費用後正益が先", "P0非緩和追尾"} {
			f, n := wave100(t, side, mode)
			comparisons += n
			total += len(f.Actors)
			for key, r := range f.Actors {
				pair := mirrors[mode+"/"+key]
				if pair == nil {
					pair = map[int]any{}
					mirrors[mode+"/"+key] = pair
				}
				pair[side] = struct {
					Totals  ActualTotals
					Metrics ActorMetrics
					Grids   EntryGridMetrics
				}{r.Totals, r.Metrics, r.GridMetrics}
			}
			if dir := os.Getenv("PROTECT100_EXPORT"); dir != "" {
				if e := os.MkdirAll(dir, 0755); e != nil {
					t.Fatal(e)
				}
				body, e := json.MarshalIndent(f, "", "  ")
				if e != nil {
					t.Fatal(e)
				}
				if e = os.WriteFile(filepath.Join(dir, fmt.Sprintf("方向%d_%s.json", side, mode)), append(body, '\n'), 0644); e != nil {
					t.Fatal(e)
				}
			}
		}
	}
	for name, pair := range mirrors {
		equal100(t, pair[1], pair[-1], name+"/経済counter鏡像")
	}
	if total != 216 || comparisons == 0 {
		t.Fatal("人工経路不足")
	}
	t.Logf("人工18場面/%d口座/H0全時点JSON=%d/経済鏡像=%d", total, comparisons, len(mirrors))
}
