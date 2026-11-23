// 由来: scripts/FAR5分枠の順行反転と数量/entry_grid_test.go
// 由来SHA256: 508885abd7f6747c9dbbcc48967fb40589336e4ad655c71d110ceb6fa7b28ed2
package miniharvest

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	old "github.com/masayoshi4649/SessionTradeExecuter/miniprotect"
)

type fixtureEvent95 struct {
	Kind  string `json:"kind"`
	Index int    `json:"index"`
}
type fixture95 struct {
	Session Session                     `json:"session"`
	Scope   string                      `json:"scope"`
	Steps   []fixtureStep94             `json:"steps"`
	Timers  []fixtureTimer94            `json:"timers"`
	Grids   []float64                   `json:"grids"`
	Events  []fixtureEvent95            `json:"events"`
	Actors  map[string]ActualResult     `json:"actors"`
	LegacyN map[string]old.ActualResult `json:"legacy_n"`
}

// observation95 は人工の絶対時計と公開済みATRを作ります。
//
// 引数: s(Session)、side(int)、index(int64)、at/move/atr(float64)は人工値です。
// 返り値: ObservationはSource/ATR自然生成を主張しないAPI入力です。
func observation95(s Session, side int, index int64, at, move, atr float64) Observation {
	o := observation94(s, side, index, 0, move, atr)
	o.Time, o.Received = at, at
	if atr > 0 {
		o.E01.ATRNominal, o.E01.ATRAvailable = at-100, at-50
	}
	return o
}

// actors95 は共通P0の三時計・両費用・両遅延を独立に作ります。
//
// 引数: t(*testing.T)、s(Session)は人工器と場です。
// 返り値: map[string]*ActualBookは固定12口座です。
func actors95(t *testing.T, s Session) map[string]*ActualBook {
	t.Helper()
	out := map[string]*ActualBook{}
	for _, timing := range []string{"N", "B5", "B5Q"} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				b, err := NewActualBook(s, ActorConfig{Policy: "P0", SlipPts: slip, DelaySeconds: delay, EntryTiming: timing, USOpen: s.USOpen})
				if err != nil {
					t.Fatal(err)
				}
				out[b.result.Key] = b
			}
		}
	}
	return out
}

// captureWave95 は5分枠・保護・Source部分返済を実Go型で接続します。
//
// 引数: t(*testing.T)、side(int)は試験器と鏡像です。
// 返り値: fixture95は全12口座と独立94のN対照です。
func captureWave95(t *testing.T, side int) fixture95 {
	t.Helper()
	s := session94()
	actors := actors95(t, s)
	legacy := map[string]*old.ActualBook{}
	for key, b := range actors {
		if b.result.Config.EntryTiming == "N" {
			prior, err := old.NewActualBook(s, old.ActorConfig{Policy: "P0", SlipPts: b.result.Config.SlipPts, DelaySeconds: b.result.Config.DelaySeconds})
			if err != nil {
				t.Fatal(err)
			}
			legacy[key] = prior
		}
	}
	out := fixture95{Session: s, Scope: "Go型API人工。Source戦略/原板/実5分ATR源は未計測。手製公開通知を12口座へ同時配送し、Nだけ別運転94へ全値比較。", Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}, Grids: []float64{}, Events: []fixtureEvent95{}}
	src := newFixtureSource94()
	grid := s.Start + 1800
	times := []float64{grid - 1, grid - 1, grid, grid + 1, grid + 2, grid + 3, grid + 4, grid + 4.1, grid + 5, grid + 6}
	moves := []float64{0, 0, 0, 0, 30, 80, 40, 20, 20, 0}
	for i, at := range times {
		if i == 2 {
			for _, b := range actors {
				before := b.Snapshot()
				if err := b.OnEntryGrid(grid); err != nil {
					t.Fatal(err)
				}
				after := b.Snapshot()
				if !reflect.DeepEqual(before.Account, after.Account) || len(before.Fills) != len(after.Fills) || len(before.Positions) != len(after.Positions) {
					t.Fatal("gridが金融評価/約定を更新")
				}
				if b.result.Config.EntryTiming != "N" && (after.Orders[0].RequestTime != grid || after.Orders[0].RequestQuote.Time != grid-1 || after.Orders[0].Quantity != 5) {
					t.Fatal("実時計と出典時計の混同")
				}
			}
			out.Events = append(out.Events, fixtureEvent95{Kind: "grid", Index: len(out.Grids)})
			out.Grids = append(out.Grids, grid)
		}
		o := observation95(s, side, int64(i), at, moves[i], 20)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("枠A", side, 5))
		}
		if i == 4 {
			news = append(news, close94("枠部分", "枠A", side, 2))
		}
		if i == 8 {
			news = append(news, close94("枠全残", "枠A", side, 3))
		}
		batch := src.step(t, o, int64(i+20), news, nil)
		before, _ := json.Marshal(batch)
		for key, b := range actors {
			if err := b.OnNativeStep(o, int64(i+20), []NativeBatch{batch}); err != nil {
				t.Fatal(key, err)
			}
			if prior := legacy[key]; prior != nil {
				if err := prior.OnNativeStep(o, int64(i+20), []old.NativeBatch{{Method: batch.Method, Delta: batch.Delta}}); err != nil {
					t.Fatal(err)
				}
				if !reflect.DeepEqual(oldProjection95(b.Snapshot()), oldProjection95(prior.Snapshot())) {
					t.Fatal("N人工の各原行全文差", key, i)
				}
			}
		}
		after, _ := json.Marshal(batch)
		if !reflect.DeepEqual(before, after) {
			t.Fatal("Source入力変更")
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "quote", Index: len(out.Steps)})
		out.Steps = append(out.Steps, fixtureStep94{Observation: o, SourceLine: int64(i + 20), Batches: []NativeBatch{batch}})
	}
	out.Actors = map[string]ActualResult{}
	out.LegacyN = map[string]old.ActualResult{}
	for key, b := range actors {
		r, err := b.Finish()
		if err != nil {
			t.Fatal(key, err)
		}
		want := 16615.0
		if r.Config.SlipPts == 5 {
			want = 11615
		}
		if r.Totals.NetYen != want || r.Totals.EntryQuantity != 5 || r.Metrics.ProtectionExitRequests != 1 {
			t.Fatal("5分手計算", key, r.Totals, r.Metrics)
		}
		out.Actors[key] = r
		if prior := legacy[key]; prior != nil {
			oldResult, err := prior.Finish()
			if err != nil || !reflect.DeepEqual(oldProjection95(r), oldProjection95(oldResult)) {
				t.Fatal("N最終全文差", key, err)
			}
			out.LegacyN[key] = oldResult
		}
	}
	return out
}

// TestGrid95CaptureMirror はslot後の実約定と94共通保護を鏡像で確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestGrid95CaptureMirror(t *testing.T) {
	a, b := captureWave95(t, 1), captureWave95(t, -1)
	for key, row := range a.Actors {
		if row.Totals != b.Actors[key].Totals {
			t.Fatal("5分売買鏡像", key)
		}
	}
}

// TestGrid95SourceStates は割当枠のSource状態と正常未知を区別します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。採否後の復活は一度も許しません。
func TestGrid95SourceStates(t *testing.T) {
	for _, kind := range []string{"pending", "cancelled", "closing", "partial_done", "closed", "bad_quote"} {
		t.Run(kind, func(t *testing.T) {
			s := session94()
			grid := s.Start + 1800
			b, err := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5"})
			if err != nil {
				t.Fatal(err)
			}
			src := newFixtureSource94()
			index := int64(0)
			feed := func(at float64, news []native.Signal, cancel []string, bad bool) {
				o := observation95(s, 1, index, at, 0, 20)
				o.QuoteOK = !bad
				d := src.step(t, o, index+20, news, cancel)
				if err := b.OnNativeStep(o, index+20, []NativeBatch{d}); err != nil {
					t.Fatal(err)
				}
				index++
			}
			cancel := []string{}
			if kind == "cancelled" {
				cancel = []string{"状態A"}
			}
			birth := birth94("状態A", 1, 5)
			if kind == "partial_done" {
				var evidence sourceEvidence
				_ = json.Unmarshal(birth.Evidence, &evidence)
				evidence.Kind, evidence.Parent = "source_add", "実未参加の元親"
				birth.Evidence, _ = json.Marshal(evidence)
			}
			feed(grid-1, []native.Signal{birth}, cancel, kind == "pending")
			if kind != "pending" && kind != "cancelled" {
				feed(grid-.9, nil, nil, false)
			}
			if kind == "closing" || kind == "partial_done" || kind == "closed" {
				q := 2
				if kind == "closed" {
					q = 5
				}
				feed(grid-.8, []native.Signal{close94("状態部分", "状態A", 1, q)}, nil, false)
				if kind != "closing" {
					feed(grid-.7, nil, nil, false)
				}
			}
			if kind == "bad_quote" {
				feed(grid-.1, nil, nil, true)
			}
			before := b.Snapshot()
			if err = b.OnEntryGrid(grid); err != nil {
				t.Fatal(err)
			}
			r := b.Snapshot()
			if before.Account.Count != r.Account.Count || len(before.Fills) != len(r.Fills) {
				t.Fatal("gridが過去原行で約定/評価")
			}
			p := r.EntryOpportunities[0]
			if !p.Consumed || p.EvaluatedAt == nil || *p.EvaluatedAt != grid {
				t.Fatal("一枠消費", p)
			}
			if kind == "partial_done" {
				if p.Requested != 3 || p.Status != "accepted" || *p.SourceQuantity != 3 || *p.SourceReserved != 0 {
					t.Fatal("出生5/現在3のmin", p)
				}
			} else if p.Requested != 0 || p.Status != "expired" {
				t.Fatal("状態による失効", p)
			}
			if p.RequiredUnknown != (kind == "bad_quote") {
				t.Fatal("未取得と未知を混同", p)
			}
			if kind == "bad_quote" && r.GridTraces[0].Action != "判定不能" {
				t.Fatal("最新badBBOを過去正常で埋めた")
			}
			// grid後に新しい正常行や枠が来ても同じ出生は再供給しません。
			feed(grid+1, nil, nil, false)
			if kind == "partial_done" && (len(b.result.Positions) != 1 || b.result.Positions[0].Source.Kind != "source_add") {
				t.Fatal("元追加の実初参加を排除/改名")
			}
			if err = b.OnEntryGrid(grid + 300); err != nil {
				t.Fatal(err)
			}
			if b.result.GridTraces[1].CandidateCount != 0 {
				t.Fatal("同じ出生を後枠へ復活")
			}
		})
	}
}

// TestGrid95QuietAndClock はstrict次枠とquiet半開区間・米国DSTを確認します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestGrid95QuietAndClock(t *testing.T) {
	s := session94()
	for _, v := range []struct{ birth, want float64 }{{s.Start + 1799, s.Start + 1800}, {s.Start + 1800, s.Start + 2100}} {
		if assignedGrid(v.birth) != v.want {
			t.Fatal("strict次5分", v)
		}
	}
	for _, delta := range []float64{1500, 1800} {
		for _, timing := range []string{"B5", "B5Q"} {
			b, _ := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: timing})
			src := newFixtureSource94()
			grid := s.Start + delta
			for i := int64(0); i < 2; i++ {
				o := observation95(s, 1, i, grid-1, 0, 20)
				news := []native.Signal{}
				if i == 0 {
					news = append(news, birth94("静観A", 1, 1))
				}
				d := src.step(t, o, i+20, news, nil)
				if err := b.OnNativeStep(o, i+20, []NativeBatch{d}); err != nil {
					t.Fatal(err)
				}
			}
			if err := b.OnEntryGrid(grid); err != nil {
				t.Fatal(err)
			}
			want := timing == "B5" || delta == 1800
			if (b.result.EntryOpportunities[0].Requested > 0) != want {
				t.Fatal("quiet端", timing, delta)
			}
		}
	}
	for _, date := range []string{"2026-10-30", "2026-11-02"} {
		us, err := native.USOpen(date)
		if err != nil {
			t.Fatal(err)
		}
		jst := time.Unix(int64(us), 0).In(time.FixedZone("JST", 9*3600))
		wantHour := 22
		if date == "2026-11-02" {
			wantHour = 23
		}
		if jst.Hour() != wantHour || jst.Minute() != 30 {
			t.Fatal("米国DST時計", jst)
		}
		ns := s
		ns.Kind = "Night"
		ns.ID = date + "_Night"
		ns.Start = float64(time.Date(jst.Year(), jst.Month(), jst.Day(), 17, 0, 0, 0, jst.Location()).Unix())
		ns.End = ns.Start + 13*3600
		ns.ForceClose = ns.End - 600
		b, err := NewActualBook(ns, ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: us})
		if err != nil {
			t.Fatal(err)
		}
		for _, x := range []struct {
			at   float64
			want bool
		}{{us - 300, false}, {us, true}, {us + 1500, true}, {us + 1800, false}} {
			q, _, u := b.gridQuiet(x.at)
			if q != x.want || u == nil || *u != x.want {
				t.Fatal("USquiet半開", x)
			}
		}
		if _, err = NewActualBook(ns, ActorConfig{Policy: "P0", EntryTiming: "B5"}); err == nil {
			t.Fatal("B NightUS未知を許可")
		}
		n, err := NewActualBook(ns, ActorConfig{Policy: "P0", EntryTiming: "N"})
		if err != nil {
			t.Fatal(err)
		}
		if err = n.OnEntryGrid(math.Ceil((us+1800)/300) * 300); err != nil {
			t.Fatal(err)
		}
		if n.result.GridTraces[0].USClockKnown || n.result.GridTraces[0].USQuiet != nil || n.result.GridTraces[0].Action == "判定不能" {
			t.Fatal("N不使用US未知を採否へ混入")
		}
	}
}

// capWave95 はSource上限内の新出生とActor遅延中の予約容量差を作ります。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: fixture95は同枠順序・両側10・0/clip消費を含む12口座です。
func capWave95(t *testing.T) fixture95 {
	t.Helper()
	s := session94()
	actors := actors95(t, s)
	src := newFixtureSource94()
	out := fixture95{Session: s, Scope: "Go型API人工。Source戦略/ATR源は未計測。Source現所有は買売各10以下。ActualD1の旧返済待ち中だけ容量差を作る。", Steps: []fixtureStep94{}, Timers: []fixtureTimer94{}, Grids: []float64{}, Events: []fixtureEvent95{}, LegacyN: map[string]old.ActualResult{}}
	index := int64(0)
	grid1, grid2 := s.Start+1800, s.Start+2100
	feed := func(at float64, news []native.Signal) {
		o := observation95(s, 1, index, at, 0, 20)
		batch := src.step(t, o, index+20, news, nil)
		before, _ := json.Marshal(batch)
		for key, b := range actors {
			if err := b.OnNativeStep(o, index+20, []NativeBatch{batch}); err != nil {
				t.Fatal(key, err)
			}
		}
		after, _ := json.Marshal(batch)
		if !reflect.DeepEqual(before, after) {
			t.Fatal("Sourceを変更")
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "quote", Index: len(out.Steps)})
		out.Steps = append(out.Steps, fixtureStep94{Observation: o, SourceLine: index + 20, Batches: []NativeBatch{batch}})
		index++
	}
	grid := func(at float64) {
		for _, b := range actors {
			if err := b.OnEntryGrid(at); err != nil {
				t.Fatal(err)
			}
		}
		out.Events = append(out.Events, fixtureEvent95{Kind: "grid", Index: len(out.Grids)})
		out.Grids = append(out.Grids, at)
	}
	feed(grid1-2, []native.Signal{birth94("旧7", 1, 7)})
	feed(grid1-1, nil)
	grid(grid1)
	feed(grid1+1, nil)
	feed(grid2-.5, []native.Signal{close94("旧7返済", "旧7", 1, 7)})
	feed(grid2-.4, []native.Signal{birth94("順一6", 1, 6), birth94("順二4", 1, 4), birth94("反対10", -1, 10)})
	feed(grid2-.3, nil)
	grid(grid2)
	for _, b := range actors {
		r := b.Snapshot()
		if r.Config.EntryTiming != "N" && r.Config.DelaySeconds == 1 {
			if r.EntryOpportunities[1].Requested != 3 || r.EntryOpportunities[2].Requested != 0 || r.EntryOpportunities[3].Requested != 10 {
				t.Fatal("同枠登録順/反対側独立上限", r.Key, r.EntryOpportunities)
			}
			g := r.GridTraces[1]
			if g.OpenBuy != 7 || g.PendingBuy != 3 || g.PendingSell != 10 || g.Action != "新規" {
				t.Fatal("返済予約を空きにした", r.Key, g)
			}
		}
	}
	feed(grid2+1, nil)
	feed(grid2+2, []native.Signal{close94("順一全残", "順一6", 1, 6), close94("順二全残", "順二4", 1, 4), close94("反対全残", "反対10", -1, 10)})
	feed(grid2+3, nil)
	out.Actors = map[string]ActualResult{}
	for key, b := range actors {
		r, err := b.Finish()
		if err != nil {
			t.Fatal(key, err)
		}
		want := 27
		if r.Config.DelaySeconds == 1 {
			want = 20
		}
		// 気配不変でも新規/返済側の10pt spreadを両側とも実価格で負担します。
		unitCost := 1000.0 + 77 + 2*r.Config.SlipPts*100
		if r.Totals.EntryQuantity != want || r.Totals.NetYen != -float64(want)*unitCost {
			t.Fatal("容量別の費用検算", key, r.Totals)
		}
		if r.Config.DelaySeconds == 1 && (r.Metrics.CapClippedEntries != 1 || r.Metrics.CapRejectedEntries != 1) {
			t.Fatal("clip/0の分母", key, r.Metrics)
		}
		out.Actors[key] = r
	}
	return out
}

// TestGrid95StableCapacity は出生順・予約中容量・売買独立の上限を検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func TestGrid95StableCapacity(t *testing.T) { _ = capWave95(t) }

// TestGrid95PendingClose はslot後の源closeが未取得Actualだけを取消すことを検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。同原行に取得できたD0は通常の返済へ進みます。
func TestGrid95PendingClose(t *testing.T) {
	for _, delay := range []int{0, 1} {
		s := session94()
		grid := s.Start + 1800
		b, _ := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5", DelaySeconds: delay})
		src := newFixtureSource94()
		for i, at := range []float64{grid - 1, grid - 1, grid + .1, grid + 1.1} {
			if i == 2 {
				if err := b.OnEntryGrid(grid); err != nil {
					t.Fatal(err)
				}
			}
			o := observation95(s, 1, int64(i), at, 0, 20)
			news := []native.Signal{}
			if i == 0 {
				news = append(news, birth94("待機A", 1, 1))
			}
			if i == 2 {
				news = append(news, close94("早い源close", "待機A", 1, 1))
			}
			d := src.step(t, o, int64(i+20), news, nil)
			if err := b.OnNativeStep(o, int64(i+20), []NativeBatch{d}); err != nil {
				t.Fatal(err)
			}
		}
		r, err := b.Finish()
		if err != nil {
			t.Fatal(err)
		}
		if delay == 1 {
			if len(r.Fills) != 0 || r.Metrics.CancelledEntries != 1 || r.Orders[0].Status != "cancelled" {
				t.Fatal("Sourceclose後にActualを遅れて取得", r)
			}
		} else if len(r.Fills) != 2 || r.Totals.NetYen != -1077 {
			t.Fatal("D0のfill→Source通知順序", r)
		}
	}
}

// TestGrid95MixedUnknown は既知拒否と必要未知の混在を待機へ落とさないことを検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。最新badBBOを古い正常気配で埋めません。
func TestGrid95MixedUnknown(t *testing.T) {
	s := session94()
	g := s.Start + 1800
	b, _ := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5"})
	src := newFixtureSource94()
	for i, at := range []float64{g - 2, g - 1, g - .5} {
		o := observation95(s, 1, int64(i), at, 0, 20)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("取得済未知", 1, 1))
		}
		if i == 2 {
			o.QuoteOK = false
			news = append(news, birth94("未取得拒否", 1, 1))
		}
		d := src.step(t, o, int64(i+20), news, nil)
		if err := b.OnNativeStep(o, int64(i+20), []NativeBatch{d}); err != nil {
			t.Fatal(err)
		}
	}
	if err := b.OnEntryGrid(g); err != nil {
		t.Fatal(err)
	}
	r := b.Snapshot()
	if r.GridTraces[0].Action != "判定不能" || r.GridTraces[0].UnknownCount != 1 || r.GridTraces[0].ExpiredCount != 2 {
		t.Fatal("known拒否混在を未知0にした", r.GridTraces)
	}
	if r.EntryOpportunities[0].SourceQuantity == nil || r.EntryOpportunities[1].SourceQuantity != nil {
		t.Fatal("未知/未取得を0へ補完")
	}
}

// TestGrid95ForceEOFAndValidation はForce優先・EOF失効・時計破損拒否を検証します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。EOFから架空の枠/約定は作りません。
func TestGrid95ForceEOFAndValidation(t *testing.T) {
	s := session94()
	b, _ := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5"})
	src := newFixtureSource94()
	at := s.ForceClose
	for i := int64(0); i < 2; i++ {
		o := observation95(s, 1, i, at-1, 0, 20)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("Force候補", 1, 1))
		}
		d := src.step(t, o, i+20, news, nil)
		if err := b.OnNativeStep(o, i+20, []NativeBatch{d}); err != nil {
			t.Fatal(err)
		}
	}
	sig := close94("Force返済", "Force候補", 1, 1)
	sig.Time, sig.SourceIndex = at, src.last.Index
	src.orders[sig.ID] = sig
	src.pending = append(src.pending, sig)
	src.reserved["玉-Force候補"] = 1
	d := native.StepResult{At: at, Origin: "timer", SourceLine: src.last.SourceLine, Signals: []native.SignalRecord{{Signal: sig, Origin: "timer", At: at, Quote: src.last}}, Closes: []native.CloseNotice{{ID: sig.ID + "|玉-Force候補", ReferenceID: "玉-Force候補", Before: 1, Quantity: 1, Reason: sig.Reason}}}
	if err := b.OnNativeForce(at, []NativeBatch{{Method: "D164_15", Delta: d}}); err != nil {
		t.Fatal(err)
	}
	if err := b.OnEntryGrid(at); err != nil {
		t.Fatal(err)
	}
	if b.result.EntryOpportunities[0].Reason != "元手法Force境界以降" || len(b.result.Orders) != 0 {
		t.Fatal("Force同枠の実新規", b.result.EntryOpportunities)
	}
	o := observation95(s, 1, 2, at, 0, 20)
	batch := src.step(t, o, 22, nil, nil)
	if err := b.OnNativeStep(o, 22, []NativeBatch{batch}); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Finish(); err != nil {
		t.Fatal(err)
	}
	// Sourceまで完結したが割当枠がまだ来ない出生だけをEOF失効します。
	b, _ = NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5"})
	src = newFixtureSource94()
	g := s.Start + 1800
	for i := int64(0); i < 4; i++ {
		o = observation95(s, 1, i, g-1+float64(i)/10, 0, 20)
		news := []native.Signal{}
		if i == 0 {
			news = append(news, birth94("EOF候補", 1, 1))
		}
		if i == 2 {
			news = append(news, close94("EOF全残", "EOF候補", 1, 1))
		}
		batch = src.step(t, o, i+20, news, nil)
		if err := b.OnNativeStep(o, i+20, []NativeBatch{batch}); err != nil {
			t.Fatal(err)
		}
	}
	r, err := b.Finish()
	if err != nil || len(r.Fills) != 0 || len(r.GridTraces) != 0 || r.GridMetrics.EOFExpired != 1 {
		t.Fatal("EOF機会を架空約定", r, err)
	}
	for _, badAt := range []float64{s.End, s.Start + 1, math.NaN(), math.Inf(1)} {
		x, _ := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5"})
		if x.OnEntryGrid(badAt) == nil {
			t.Fatal("不正grid時計", badAt)
		}
	}
	x, _ := NewActualBook(s, ActorConfig{Policy: "P0", EntryTiming: "B5"})
	if err = x.OnEntryGrid(g); err != nil {
		t.Fatal(err)
	}
	if x.OnEntryGrid(g) == nil {
		t.Fatal("同枠二重配送")
	}
	if _, err = NewActualBook(s, ActorConfig{Policy: "P1", EntryTiming: "B5"}); err == nil {
		t.Fatal("Bへ別保護政策を混入")
	}
}

// TestExportGrid95Fixtures は明示環境だけで実Go型の鏡像2場を新規保存します。
//
// 引数: MINIGRID_EXPORT_DIR(string環境変数)は未作成出力先です。
// 返り値: ありません。通常試験はskipします。
func TestExportGrid95Fixtures(t *testing.T) {
	dir := os.Getenv("MINIGRID_EXPORT_DIR")
	if dir == "" {
		t.Skip("95人工exportは明示環境のみ")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("新規出力先のみ")
	}
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	for _, v := range []struct {
		name string
		side int
	}{{"買い", 1}, {"売り", -1}} {
		row := captureWave95(t, v.side)
		data, err := json.MarshalIndent(row, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(dir, v.name+".json"), append(data, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	row := capWave95(t)
	data, err := json.MarshalIndent(row, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(dir, "容量と両側.json"), append(data, '\n'), 0644); err != nil {
		t.Fatal(err)
	}
}

// legacyConfig95 は旧金融人工の3条件を診断Nへ明示して移します。
//
// 引数: policy(string)、slip(float64)、delay(int)は旧94の設定です。
// 返り値: ActorConfigは旧API互換の連続新規条件です。
func legacyConfig95(policy string, slip float64, delay int) ActorConfig {
	return ActorConfig{Policy: policy, SlipPts: slip, DelaySeconds: delay, EntryTiming: "N"}
}

// oldProjection95 は宣言した5追加項目だけを除いて旧結果へ比較します。
//
// 引数: value(any)はGo型の結果です。
// 返り値: map[string]anyは旧94の全JSON比較用の射影です。
func oldProjection95(value any) map[string]any {
	data, _ := json.Marshal(value)
	var out map[string]any
	_ = json.Unmarshal(data, &out)
	delete(out, "entry_opportunities")
	delete(out, "grid_traces")
	delete(out, "grid_metrics")
	cfg := out["config"].(map[string]any)
	delete(cfg, "entry_timing")
	delete(cfg, "us_open")
	return out
}

// TestNative95EveryRowFull94 は各原行のN全金融を旧94へ比較します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。Source/ATRは手製で、市場・原板を使用しません。
func TestNative95EveryRowFull94(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				s := session94()
				b, err := NewActualBook(s, legacyConfig95("P0", slip, delay))
				if err != nil {
					t.Fatal(err)
				}
				prior, err := old.NewActualBook(s, old.ActorConfig{Policy: "P0", SlipPts: slip, DelaySeconds: delay})
				if err != nil {
					t.Fatal(err)
				}
				src := newFixtureSource94()
				if err = b.OnEntryGrid(s.Start + 1800); err != nil {
					t.Fatal(err)
				}
				for i, sec := range []float64{0, .5, 1, 2, 3, 4, 5} {
					o := observation94(s, side, int64(i), sec, []float64{0, 0, 0, 30, 0, 0, 0}[i], 20)
					news := []native.Signal{}
					if i == 0 {
						news = append(news, birth94("旧同値", side, 5))
					}
					if i == 5 {
						news = append(news, close94("旧全残", "旧同値", side, 5))
					}
					batch := src.step(t, o, int64(i+20), news, nil)
					if err = b.OnNativeStep(o, int64(i+20), []NativeBatch{batch}); err != nil {
						t.Fatal(err)
					}
					if err = prior.OnNativeStep(o, int64(i+20), []old.NativeBatch{{Method: batch.Method, Delta: batch.Delta}}); err != nil {
						t.Fatal(err)
					}
					if !reflect.DeepEqual(oldProjection95(b.Snapshot()), oldProjection95(prior.Snapshot())) {
						t.Fatalf("Nの旧全field差:side%d C%g D%d row%d", side, slip, delay, i)
					}
				}
				if err = b.OnNativeForce(s.ForceClose, nil); err != nil {
					t.Fatal(err)
				}
				if err = prior.OnNativeForce(s.ForceClose, nil); err != nil {
					t.Fatal(err)
				}
				if err = b.OnEntryGrid(s.ForceClose); err != nil {
					t.Fatal(err)
				}
				br, be := b.Finish()
				pr, pe := prior.Finish()
				if be != nil || pe != nil || !reflect.DeepEqual(oldProjection95(br), oldProjection95(pr)) {
					t.Fatal("Force/Finishの旧全文差", be, pe)
				}
			}
		}
	}
}
