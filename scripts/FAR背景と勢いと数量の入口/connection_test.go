package minientry99

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	e3 "github.com/masayoshi4649/SessionTradeExecuter/minie3"
	old98 "github.com/masayoshi4649/SessionTradeExecuter/minirisk98"
)

type fixtureStep99 struct {
	Observation Observation   `json:"observation"`
	SourceLine  int64         `json:"source_line"`
	Batches     []NativeBatch `json:"batches"`
}
type fixtureTimer99 struct {
	At      float64       `json:"at"`
	Batches []NativeBatch `json:"batches"`
}
type fixtureEvent99 struct {
	Kind  string `json:"kind"`
	Index int    `json:"index"`
}
type fixture99 struct {
	Session Session          `json:"session"`
	Scope   string           `json:"scope"`
	Steps   []fixtureStep99  `json:"steps"`
	Timers  []fixtureTimer99 `json:"timers"`
	Grids   []float64        `json:"grids"`
	Events  []fixtureEvent99 `json:"events"`
}

// root99 は人工と由来コードを固定配置で参照します。
//
// 引数: ありません。
// 返り値: stringはrepositoryルートです。原板を列挙しません。
func root99() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Dir(filepath.Dir(filepath.Dir(file)))
}

// fixtures99 は停止済み14手製Source通知だけを読みます。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: map[string]fixture99は実Go型入力です。旧結果金額を期待値へ転記しません。
func fixtures99(t *testing.T) map[string]fixture99 {
	t.Helper()
	out := map[string]fixture99{}
	for _, side := range []int{-1, 1} {
		for _, mode := range []string{"幅と次板悪化", "非緩和", "未知後既知", "Source部分", "Source全予約", "利益移行", "risk要求後正益"} {
			name := fmt.Sprintf("方向%d_%s.json", side, mode)
			body, err := os.ReadFile(filepath.Join(root99(), "work", "98初期ATR追尾案", "人工", "停止版", name))
			if err != nil {
				t.Fatal(err)
			}
			var value fixture99
			if err = json.Unmarshal(body, &value); err != nil {
				t.Fatal(err)
			}
			out[name] = value
		}
	}
	return out
}

// oldBatches99 は別moduleの型へ全公開fieldを明示対応します。
//
// 引数: input([]NativeBatch)は当行公開通知です。
// 返り値: []old98.NativeBatchは同じDelta値です。nilと空列も区別して維持します。
func oldBatches99(input []NativeBatch) []old98.NativeBatch {
	if input == nil {
		return nil
	}
	out := make([]old98.NativeBatch, len(input))
	for i, batch := range input {
		out[i] = old98.NativeBatch{Method: batch.Method, Delta: batch.Delta}
	}
	return out
}

// equalJSON99 は新旧口座を除外0で全値比較します。
//
// 引数: t(*testing.T)、a/b(any)、label(string)は試験器・比較値・説明です。
// 返り値: ありません。byte差はJSON全field差として失敗します。
func equalJSON99(t *testing.T, a, b any, label string) {
	t.Helper()
	x, err := json.Marshal(a)
	if err != nil {
		t.Fatal(err)
	}
	y, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(x, y) {
		t.Fatalf("%s: 全JSON差\n%s\n%s", label, x, y)
	}
}

// Test99EmptyGateFull98 は空Gate四会計を固定98へ全時点・Force後・最終で比較します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。14場面×4費用遅延、人工Source以外は読取りません。
func Test99EmptyGateFull98(t *testing.T) {
	comparisons, series := 0, 0
	for name, f := range fixtures99(t) {
		for _, cost := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				cfg := ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", SlipPts: cost, DelaySeconds: delay}
				b, err := NewActualBook(f.Session, cfg)
				if err != nil {
					t.Fatal(err)
				}
				old, err := old98.NewActualBook(f.Session, old98.ActorConfig{Policy: cfg.Policy, EntryTiming: cfg.EntryTiming, HarvestPolicy: cfg.HarvestPolicy, SlipPts: cost, DelaySeconds: delay})
				if err != nil {
					t.Fatal(err)
				}
				equalJSON99(t, b.Snapshot(), old.Snapshot(), name+"/作成")
				comparisons++
				for _, event := range f.Events {
					switch event.Kind {
					case "quote":
						s := f.Steps[event.Index]
						before, _ := json.Marshal(s.Batches)
						if err = b.OnNativeStep(s.Observation, s.SourceLine, s.Batches); err != nil {
							t.Fatal(err)
						}
						if err = old.OnNativeStep(s.Observation, s.SourceLine, oldBatches99(s.Batches)); err != nil {
							t.Fatal(err)
						}
						after, _ := json.Marshal(s.Batches)
						if !bytes.Equal(before, after) {
							t.Fatal("共通通知変更")
						}
					case "grid":
						if err = b.OnEntryGridWithGate(f.Grids[event.Index], nil); err != nil {
							t.Fatal(err)
						}
						if err = old.OnEntryGridWithGate(f.Grids[event.Index], nil); err != nil {
							t.Fatal(err)
						}
					case "force":
						s := f.Timers[event.Index]
						if err = b.OnNativeForce(s.At, s.Batches); err != nil {
							t.Fatal(err)
						}
						if err = old.OnNativeForce(s.At, oldBatches99(s.Batches)); err != nil {
							t.Fatal(err)
						}
					default:
						t.Fatal("未知人工イベント")
					}
					equalJSON99(t, b.Snapshot(), old.Snapshot(), name+"/"+event.Kind)
					comparisons++
				}
				r, err := b.Finish()
				if err != nil {
					t.Fatal(err)
				}
				prior, err := old.Finish()
				if err != nil {
					t.Fatal(err)
				}
				equalJSON99(t, r, prior, name+"/最終")
				comparisons++
				series++
				if !r.Complete || r.Config.RiskPolicy != "" || r.Key != fmt.Sprintf("H0_B5Q_P0_C%.0f_D%d", cost, delay) {
					t.Fatal("空Gateの旧ID/条件")
				}
			}
		}
	}
	t.Logf("空Gate旧98除外0: %d系列/%d全時点JSON", series, comparisons)
}

// context99 は当候補の公開時計と原行を手製技法snapshotへ結びます。
//
// 引数: c(EntryCandidate)、mode(string)は金融が作る現在候補と境界名です。
// 返り値: e3.TechnicalGateInputは当枠公開値です。Source/方向/量を変更しません。
func context99(c EntryCandidate, mode string) e3.TechnicalGateInput {
	in, _ := technicalFixture99(c.Side, "A")
	in.At, in.SnapshotID = c.At, fmt.Sprintf("人工場-G%.0f", c.At)
	in.Chart.Scene.ID = "人工場"
	in.Chart.Scene.Start = c.At - 18000
	for i := range in.Recent3 {
		v := &in.Recent3[i]
		end := math.Floor(c.At/180)*180 - float64(2-i)*180
		v.Scene = in.Chart.Scene
		v.At, v.ObservedClock = end, c.At
		v.Chart.Technical.Bar3End, v.Chart.Technical.Bar15End = end, math.Floor(end/900)*900
		v.Chart.PreviousBar3End = end - 180
		v.LastInput.Time = end - 1
		v.Three.BarEnd, v.Three.AvailableAt, v.Three.ObservedClock, v.Three.LastSource.Time = end, end, c.At, end-1
		v.Fifteen.BarEnd, v.Fifteen.AvailableAt, v.Fifteen.ObservedClock, v.Fifteen.LastSource.Time = math.Floor(end/900)*900, math.Floor(end/900)*900, c.At, math.Floor(end/900)*900-1
	}
	in.Chart = in.Recent3[2]
	in.Chart.At = c.At
	in.Current.Time, in.Current.Received = c.Quote.Time, c.Quote.Time
	in.Current.SourceIndex, in.Current.SourceLine = c.Quote.Index, c.Quote.SourceLine
	in.Current.Last, in.Current.Bid, in.Current.Ask = c.Quote.Last, c.Quote.Bid, c.Quote.Ask
	in.Current.Buy.OwnAt, in.Current.Sell.OwnAt = c.Quote.Time, c.Quote.Time
	for k, v := range in.Current.Buy.Windows {
		v.CurrentAt, v.EndpointAt = c.Quote.Time, c.Quote.Time-5
		in.Current.Buy.Windows[k] = v
	}
	in.Current.Night.Time, in.Current.Night.Index = c.Quote.Time, c.Quote.Index
	in.Current.Night.Band.Time, in.Current.Night.Band.Index, in.Current.Night.Band.StartTime = c.Quote.Time, c.Quote.Index, c.Quote.Time-5
	switch mode {
	case "未知":
		in.Chart.Chart.Technical.Histogram3 = 0
		in.Chart.Chart.Technical.ExitKnown = false
		in.Chart.Chart.Technical.SpikeKnown = false
	case "否定", "否定優先":
		v := &in.Chart.Chart.Technical
		v.EMA8_3 = v.EMA21_3 - float64(c.Side)*10
		if mode == "否定優先" {
			v.ExitKnown = false
			v.SpikeKnown = false
		}
	case "スパイク":
		v := &in.Chart.Chart.Technical
		v.TR3 = 41
		v.ATR3 = 20
		v.PreviousATR3 = 20
		if c.Side > 0 {
			v.RSI3, v.PreviousRSI3 = 90, 74
		} else {
			v.RSI3, v.PreviousRSI3 = 10, 26
		}
	}
	in.Recent3[2].Chart = in.Chart.Chart
	return in
}

// Test99PureGateAndProtection は純式を実出生一回枠と金融へ非0接続します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。買売/C0C5/D0D1、未知/否定/Source予約/Force/H0を確認します。
func Test99PureGateAndProtection(t *testing.T) {
	total, unknown, refused, active, sourceRequests, forceCalls := 0, 0, 0, 0, 0, 0
	mirrors := map[string]map[int]any{}
	for name, f := range fixtures99(t) {
		for _, mode := range []string{"正常", "未知", "否定", "否定優先", "スパイク"} {
			for _, policy := range []string{"E3", "E3S"} {
				for _, cost := range []float64{0, 5} {
					for _, delay := range []int{0, 1} {
						b, err := NewActualBook(f.Session, ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0", GatePolicy: policy, SlipPts: cost, DelaySeconds: delay})
						if err != nil {
							t.Fatal(err)
						}
						calls := 0
						for _, event := range f.Events {
							switch event.Kind {
							case "quote":
								s := f.Steps[event.Index]
								err = b.OnNativeStep(s.Observation, s.SourceLine, s.Batches)
							case "force":
								s := f.Timers[event.Index]
								before := b.Snapshot()
								err = b.OnNativeForce(s.At, s.Batches)
								after := b.Snapshot()
								forceCalls++
								if len(before.Fills) != len(after.Fills) || before.Account.Count != after.Account.Count {
									t.Fatal("Forceで偽fill/MTM")
								}
							case "grid":
								err = b.OnEntryGridWithGate(f.Grids[event.Index], func(c EntryCandidate) (GateDecision, error) {
									calls++
									input := context99(c, mode)
									before, _ := json.Marshal([]any{c, input})
									got, e := AssessEntryTechnical(input, c, policy)
									if e != nil {
										return GateDecision{}, e
									}
									after, _ := json.Marshal([]any{c, input})
									if !bytes.Equal(before, after) {
										t.Fatal("純callback入力変更")
									}
									d := got.Decision
									if mode == "未知" && (d.Known || d.Allowed) {
										t.Fatal("必要未知の採用", d)
									}
									if (mode == "否定" || mode == "否定優先") && (!d.Known || d.Allowed) {
										t.Fatal("既知否定優先", d)
									}
									if mode == "正常" && (!d.Known || !d.Allowed) {
										t.Fatal("正常純式が非採用", d)
									}
									if !d.Known {
										unknown++
									}
									if d.Known && !d.Allowed {
										refused++
									}
									return GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, nil
								})
							}
							if err != nil {
								t.Fatal(name, mode, policy, cost, delay, err)
							}
						}
						r, e := b.Finish()
						if e != nil {
							t.Fatal(e)
						}
						if calls != 1 || !r.Complete || r.Config.RiskPolicy != "" || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 || r.Totals.PendingBuy != 0 || r.Totals.PendingSell != 0 {
							t.Fatal("一回枠/最終0", r.Key, calls)
						}
						if r.Config.GatePolicy != policy || r.Key != fmt.Sprintf("H0_%s_B5Q_P0_C%.0f_D%d", policy, cost, delay) {
							t.Fatal("名前偽装")
						}
						if mode == "正常" || mode == "スパイク" && policy == "E3" {
							if len(r.Positions) != 1 {
								t.Fatal("実金融非0にならない")
							}
						}
						if mode == "未知" || mode == "否定" || mode == "否定優先" || mode == "スパイク" && policy == "E3S" {
							if len(r.Positions) != 0 {
								t.Fatal("拒否後の実新規")
							}
						}
						for _, p := range r.Positions {
							if p.ProtectionActive {
								active++
								if p.Activation == nil || p.Activation.UnitNet <= 0 || p.FloorGain == nil || *p.FloorGain < math.Max(0, p.Activation.GainPoints) {
									t.Fatal("H0利益保護変更")
								}
							}
							if p.InitialRisk != nil {
								t.Fatal("99に初期risk")
							}
							if p.Reserved != 0 || p.Quantity != 0 {
								t.Fatal("予約残")
							}
						}
						sourceRequests += r.Metrics.SourceExitRequests
						mirrorKey := fmt.Sprintf("%s/%s/%s/C%.0f/D%d", strings.TrimPrefix(strings.TrimPrefix(name, "方向-1_"), "方向1_"), mode, policy, cost, delay)
						if mirrors[mirrorKey] == nil {
							mirrors[mirrorKey] = map[int]any{}
						}
						side := f.Steps[0].Batches[0].Delta.Signals[0].Signal.Side
						mirrors[mirrorKey][side] = struct {
							Totals  ActualTotals
							Metrics ActorMetrics
							Grids   EntryGridMetrics
						}{r.Totals, r.Metrics, r.GridMetrics}
						total++
					}
				}
			}
		}
	}
	if total != 560 || unknown == 0 || refused == 0 || active == 0 || sourceRequests == 0 || forceCalls != total {
		t.Fatal("必要経路を通っていない", total, unknown, refused, active, sourceRequests, forceCalls)
	}
	for key, pair := range mirrors {
		if len(pair) != 2 {
			t.Fatal("鏡像欠落", key)
		}
		equalJSON99(t, pair[1], pair[-1], "経済/全counter鏡像:"+key)
	}
	t.Logf("人工口座=%d 必要未知=%d 既知否定=%d H0起動=%d Source要求=%d Force=%d", total, unknown, refused, active, sourceRequests, forceCalls)
}

// Test99ConfigurationBoundary は候補外の金融設定とcallback偽装を拒否します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Gate名を旧A/ABへ置換して受理させません。
func Test99ConfigurationBoundary(t *testing.T) {
	f := fixtures99(t)["方向1_利益移行.json"]
	base := ActorConfig{Policy: "P0", EntryTiming: "B5Q", HarvestPolicy: "H0"}
	for _, policy := range []string{"G0", "A", "B", "AB", "E3x"} {
		cfg := base
		cfg.GatePolicy = policy
		if _, err := NewActualBook(f.Session, cfg); err == nil {
			t.Fatal("不正gate受理", policy)
		}
	}
	for _, field := range []string{"risk", "harvest", "timing", "base"} {
		cfg := base
		switch field {
		case "risk":
			cfg.RiskPolicy = "R05"
		case "harvest":
			cfg.HarvestPolicy = ""
		case "timing":
			cfg.EntryTiming = "B5"
		case "base":
			cfg.Policy = "P1"
		}
		if _, err := NewActualBook(f.Session, cfg); err == nil {
			t.Fatal("条件外受理", field)
		}
	}
	input, c := technicalFixture99(1, "A")
	candidate := EntryCandidate{Ordinal: c.Ordinal, At: c.At, Side: c.Side, Quote: c.Quote, Available: c.Available, Quantity: c.Quantity, Source: SourceIdentity{Method: c.Source.Method, SignalID: c.Source.SignalID, BirthQuantity: c.Source.BirthQuantity, BirthTime: c.Source.BirthTime}}
	for _, kind := range []string{"旧名", "未知採用", "snapshot欠落", "nil"} {
		callback := EntryGate(func(c EntryCandidate) (GateDecision, error) {
			d := GateDecision{Policy: "E3", SnapshotID: input.SnapshotID, Known: true, Allowed: true}
			switch kind {
			case "旧名":
				d.Policy = "AB"
			case "未知採用":
				d.Known = false
			case "snapshot欠落":
				d.SnapshotID = ""
			}
			return d, nil
		})
		if kind == "nil" {
			callback = nil
		}
		if _, err := evaluateEntryGate("E3", callback, candidate); err == nil {
			t.Fatal("callback境界未拒否", kind)
		}
	}
}
