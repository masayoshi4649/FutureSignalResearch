package continuous101

import (
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"sort"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	oldtape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	chart "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// finite は公開入力の有限性を検査します。
//
// 引数: values(...float64)は時計又は価格です。
// 返り値: boolはすべて有限ならtrueです。
func finite(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// prepare は市場内順序を検査し固定96と同じstable mergeを作ります。
//
// 引数: req(Request)は明示公開型です。
// 返り値: []Row/errorはTOPIX同時計先行の独立slice、又は入力不正です。
func prepare(req Request) ([]Row, error) {
	if !finite(req.Session.Start, req.Session.End, req.Scene.Start) || req.Session.ID != req.Scene.ID || req.Session.Start != req.Scene.Start || req.Scene.Contract == "" || req.Session.Start <= 0 || req.Session.End <= req.Session.Start || (req.Session.Kind != "Day" && req.Session.Kind != "Night") {
		return nil, fmt.Errorf("場/限月/開始時計不正")
	}
	rows := []Row{}
	for _, ref := range []string{"TOPIX", "NK225"} {
		last, line := req.Session.Start, int64(0)
		for _, r := range req.Rows {
			if r.Board.Reference != ref {
				continue
			}
			b := r.Board
			if !finite(b.Time, b.Received, b.Last, b.Bid, b.Ask) || b.Time < last || b.Time < req.Session.Start || b.Time >= req.Session.End || b.Received != b.Time || r.PhysicalLine <= line {
				return nil, fmt.Errorf("市場内時計/物理行/Received不正")
			}
			last, line = b.Time, r.PhysicalLine
			rows = append(rows, r)
		}
	}
	if len(rows) != len(req.Rows) || len(rows) == 0 {
		return nil, fmt.Errorf("市場/空原行不正")
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].Board.Time < rows[j].Board.Time })
	prior := req.Session.Start - 1
	for _, g := range req.Grids {
		if !finite(g) || g < req.Session.Start || g >= req.Session.End || g <= prior {
			return nil, fmt.Errorf("Grid時計不正")
		}
		prior = g
	}
	return rows, nil
}

// Build はFeaturesと独立bankだけを連続運転します。
//
// 引数: req(Request)、seed(*warm.Seed)は当場公開型と前場の数値種です。
// 返り値: Sidecar/*warm.Seed/errorは共有入力/次種/不正です。Source/金融は呼びません。
func Build(req Request, seed *warm.Seed) (Sidecar, *warm.Seed, error) {
	return build(req, seed, nil)
}

// BuildToSink は全原行をRAMへ保持せず同じ処理を逐次出力します。
//
// 引数: req(Request)、seed(*warm.Seed)、sink(Sink)は公開入力/数値種/出力関数です。
// 返り値: Sidecar/*warm.Seed/errorは辞書/全Grid/終値を持つheader、次種、又は処理不正です。
func BuildToSink(req Request, seed *warm.Seed, sink Sink) (Sidecar, *warm.Seed, error) {
	if sink == nil {
		return Sidecar{}, nil, fmt.Errorf("sink必須")
	}
	return build(req, seed, sink)
}

// build は人工materializeと実streamの共通配送loopです。
//
// 引数: req(Request)、seed(*warm.Seed)、sink(Sink又はnil)は入力と保存方式です。
// 返り値: Sidecar/*warm.Seed/errorは公開保存/次種/不正です。sink有りではRows/Traceを貯めません。
func build(req Request, seed *warm.Seed, sink Sink) (Sidecar, *warm.Seed, error) {
	out := Sidecar{Version: 1, Scope: "公開FeaturesとBankの共有入力・Source/金融運転なし", Session: req.Session, FeaturesRecomputed: true, ChartsRecomputed: true, Payloads: map[string]Payload{}, Rows: []RawContext{}, Grids: []chart.TechnicalGateInput{}, Trace: []Trace{}, SkippedGrids: []float64{}}
	if sink != nil {
		out.Streamed = true
		out.Rows = nil
		out.Trace = nil
	}
	emitTrace := func(tr Trace, positiveNK bool) error {
		out.TraceCount++
		if sink == nil {
			out.Trace = append(out.Trace, tr)
			return nil
		}
		if positiveNK {
			return nil
		}
		return sink(Record{Kind: "control", Control: &tr})
	}
	rows, e := prepare(req)
	if e != nil {
		return out, nil, e
	}
	bank, e := warm.New(req.Scene, seed)
	if e != nil {
		return out, nil, e
	}
	method := "D164_15"
	if req.Session.Kind == "Night" {
		method = "P164_06"
	}
	params, e := strategy.ParametersForMethod("NK225", req.Session.Kind, method)
	if e != nil {
		return out, nil, e
	}
	if params.Features.ATRPeriod != 12 || params.Features.ATRMinBars != 3 || params.Features.CandleDelay != 60 {
		return out, nil, fmt.Errorf("固定特徴設定差")
	}
	if req.Session.Kind == "Night" {
		other, er := strategy.ParametersForMethod("NK225", "Night", "U165_03")
		if er != nil || !reflect.DeepEqual(params.Features, other.Features) {
			return out, nil, fmt.Errorf("P/U特徴設定差")
		}
	}
	out.FeatureConfig, e = json.Marshal(params.Features)
	if e != nil {
		return out, nil, e
	}
	f, e := strategy.NewFeatures(req.Session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		return out, nil, e
	}
	f.EnableResearch()
	candles := append([]CandleEvent{}, req.Candles...)
	for _, c := range candles {
		if (c.Reference != "NK225" && c.Reference != "TOPIX") || (c.Interval != 60 && c.Interval != 300) || !c.Candle.Closed || c.At != c.Candle.Time+float64(c.Interval)+params.Features.CandleDelay || !finite(c.At, c.Candle.Time, c.Candle.Open, c.Candle.High, c.Candle.Low, c.Candle.Close) || c.Candle.Time < req.Session.Start || c.Candle.Time >= req.Session.End {
			return out, nil, fmt.Errorf("CSV公開型/時計不正")
		}
	}
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })
	history := []warm.Snapshot{}
	historyRefs := []State{}
	current := far82.CurrentEvidence{}
	gi, ci := 0, 0
	all := map[string]int64{}
	features := map[string]int64{}
	// ----------------------------------------
	// 公表/旧Gridは同時計rawを入れる前の公開値だけを持つ。
	for merge, r := range rows {
		grids := []float64{}
		for gi < len(req.Grids) && req.Grids[gi] <= r.Board.Time {
			grids = append(grids, req.Grids[gi])
			gi++
		}
		batch, err := bank.AdvanceObserved(r.Board.Time, grids)
		if err != nil {
			return out, nil, err
		}
		pi := 0
		appendPub := func(p warm.Publication) error {
			history = append(history, p.Snapshot)
			if len(history) > 3 {
				history = history[len(history)-3:]
			}
			s, er := pack(p.Snapshot, out.Payloads)
			if er == nil {
				historyRefs = append(historyRefs, s)
				if len(historyRefs) > 3 {
					historyRefs = historyRefs[len(historyRefs)-3:]
				}
				er = emitTrace(Trace{Kind: "publication", At: p.At, Chart: s}, false)
			}
			return er
		}
		for _, g := range batch.Grids {
			for pi < len(batch.Publications) && batch.Publications[pi].At <= g.At {
				if err = appendPub(batch.Publications[pi]); err != nil {
					return out, nil, err
				}
				pi++
			}
			c := copyCurrent(current)
			h := append([]warm.Snapshot{}, history...)
			out.Grids = append(out.Grids, chart.TechnicalGateInput{SnapshotID: fmt.Sprintf("%s-G%04d", req.Scene.ID, len(out.Grids)+1), At: g.At, Kind: req.Session.Kind, Chart: g, Recent3: h, Current: c})
			s, er := pack(g, out.Payloads)
			if er != nil {
				return out, nil, er
			}
			if er = emitTrace(Trace{Kind: "grid", At: g.At, Chart: s}, false); er != nil {
				return out, nil, er
			}
		}
		for pi < len(batch.Publications) {
			if err = appendPub(batch.Publications[pi]); err != nil {
				return out, nil, err
			}
			pi++
		}
		id := Identity{Market: r.Board.Reference, Time: r.Board.Time, PhysicalLine: r.PhysicalLine, AllIndex: all[r.Board.Reference], MergeOrdinal: merge + 1}
		all[r.Board.Reference]++
		if r.Board.Reference == "NK225" {
			b, er := bank.Step(warm.Quote{Time: r.Board.Time, Index: id.AllIndex, Line: r.PhysicalLine, Last: r.Board.Last, Bid: r.Board.Bid, Ask: r.Board.Ask, Valid: r.Board.Last > 0}, nil)
			if er != nil {
				return out, nil, er
			}
			if len(b.Publications)+len(b.Grids) != 0 {
				return out, nil, fmt.Errorf("同時計再公表")
			}
		}
		for ci < len(candles) && candles[ci].At <= r.Board.Time {
			c := candles[ci]
			if _, err = f.AddCandles(c.Reference, c.Interval, []strategy.Candle{c.Candle}, c.At); err != nil {
				return out, nil, err
			}
			ci++
		}
		if r.Board.Last > 0 {
			o, er := f.OnBoard(r.Board)
			if er != nil {
				return out, nil, er
			}
			expected := features[r.Board.Reference]
			if o.Index != expected {
				return out, nil, fmt.Errorf("FeaturesIndex不整合")
			}
			features[r.Board.Reference]++
			id.FeaturesIndex = &expected
			if r.Board.Reference == "NK225" {
				current = far82.ExtractCurrent(o, r.PhysicalLine)
				q, er := oldtape.ProjectQuote(o, r.PhysicalLine)
				if er != nil {
					return out, nil, er
				}
				c := copyCurrent(current)
				h := append([]State{}, historyRefs...)
				s, er := pack(bank.Snapshot(), out.Payloads)
				if er != nil {
					return out, nil, er
				}
				out.RowCount++
				row := RawContext{out.RowCount, id, q, c, s, h}
				if sink == nil {
					out.Rows = append(out.Rows, row)
				} else if er = sink(Record{Kind: "row", Row: &row}); er != nil {
					return out, nil, er
				}
			}
		}
		s, er := pack(bank.Snapshot(), out.Payloads)
		if er != nil {
			return out, nil, er
		}
		if er = emitTrace(Trace{Kind: "raw", At: r.Board.Time, Identity: &id, Chart: s}, r.Board.Reference == "NK225" && r.Board.Last > 0); er != nil {
			return out, nil, er
		}
	}
	// ----------------------------------------
	// EOF以後を公開せず、数値種だけを場間へ渡す。
	out.SkippedGrids = append(out.SkippedGrids, req.Grids[gi:]...)
	next, end, e := bank.Seal()
	if e != nil {
		return out, nil, e
	}
	out.Ending, e = pack(end, out.Payloads)
	if e != nil {
		return out, nil, e
	}
	return out, &next, nil
}
