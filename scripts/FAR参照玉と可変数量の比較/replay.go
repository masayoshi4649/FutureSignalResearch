// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/replay.go
// 87派生元SHA256: 47244d36af7bc4db13848fca7abcb8c156c1dc5c29ed16cd816e97ab0b1ae09e

package far87

import (
	"fmt"
	"math"
	"reflect"
	"sort"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// GridDecision は前原行までのC0全判断とactiveな参照全poolを一度だけ保存します。
// Source.Closesは空で、返済通知はSourceEventsに一度記録します。
type GridDecision struct {
	At              float64         `json:"at"`
	Window          string          `json:"window"`
	ClockAllowed    bool            `json:"clock_allowed"`
	BlockReason     string          `json:"block_reason"`
	C0              Decision        `json:"c0"`
	Source          ReadSnapshot    `json:"source"`
	SourceLine      int64           `json:"source_line"`
	StructureAnchor StructureAnchor `json:"structure_anchor"`
}

// SourceEvent はSourceの新返済通知をtimer/quoteの出典と共に一度だけ保存します。
type SourceEvent struct {
	At          float64          `json:"at"`
	Origin      string           `json:"origin"`
	Quote       Quote            `json:"quote"`
	Method      string           `json:"method"`
	SourceAt    float64          `json:"source_at"`
	SourceIndex int64            `json:"source_index"`
	SourceLine  int64            `json:"source_line"`
	Closes      []ReferenceClose `json:"closes"`
}

// ReplayResult は共有参照・定時・返済イベントと4独立実会計を保存します。
type ReplayResult struct {
	Session           string                `json:"session"`
	Quality           map[string]RawQuality `json:"quality"`
	ReferenceCounts   map[string]int        `json:"reference_counts"`
	Books             map[string]BookResult `json:"books"`
	GridDecisions     []GridDecision        `json:"grid_decisions"`
	SourceEvents      []SourceEvent         `json:"source_events"`
	SourceEquivalence SourceEquivalence     `json:"source_equivalence"`
}

// replayReference は固定Source運転と追加読取だけの境界です。
type replayReference interface {
	Step(strategy.Observation) (ReferenceFrame, error)
	Force(float64, string) error
	Frame() ReferenceFrame
	ReadMetadata() (ReadSnapshot, error)
}

type replayRuntime struct {
	session     strategy.Session
	bank        *ChartBank
	books       map[string]*Book
	last        Quote
	current     CurrentEvidence
	forceDone   bool
	grids       map[float64]bool
	result      *ReplayResult
	refs        map[string]replayReference
	sourceLines map[string]int64
	legacyRefs  map[string]replayLegacyReference
	frameHashes *frameHashes
}

var referenceOrder = []string{"D164_15", "P164_06", "U165_03"}

// bookKey はS/SCの外側ラベルと約定遅延を保存キーへ写します。
//
// 引数: mode(string)、delay(int)はR0G1/R1G1と0/1です。
// 返り値: stringは一意な会計キーです。
func bookKey(mode string, delay int) string { return fmt.Sprintf("%s_D%d", mode, delay) }

// sourcePolicy は固定された外側ラベルからSource入口政策を返します。
//
// 引数: mode(string)はR0G1又はR1G1です。
// 返り値: stringはS又はSCで、不正外キーは空文字です。
func sourcePolicy(mode string) string {
	if mode == "R0G1" {
		return "S"
	}
	if mode == "R1G1" {
		return "SC"
	}
	return ""
}

// emptySnapshot は未作成・供給停止の空poolを統一します。
//
// 引数: なし。
// 返り値: ReadSnapshotは架空のSource原行を持たない空値です。
func emptySnapshot() ReadSnapshot {
	return ReadSnapshot{SourceIndex: -1, Lots: []ReadLot{}, Closes: []ReferenceClose{}}
}

// structureAnchorAt は当時の確定3分EMA8だけを要求時点で固定します。
//
// 引数: at(float64)は判断時計、chart(ChartView)は確定公開された指標です。
// 返り値: StructureAnchorは当時EMA価格又は理由付き未知で、将来足を使いません。
func structureAnchorAt(at float64, chart ChartView) StructureAnchor {
	t := chart.Technical
	a := StructureAnchor{Reason: "当時確定3分EMA8が未知"}
	if t.ExitKnown && !math.IsNaN(at) && !math.IsInf(at, 0) &&
		!math.IsNaN(t.EMA8_3) && !math.IsInf(t.EMA8_3, 0) && t.EMA8_3 > 0 &&
		!math.IsNaN(t.Bar3End) && !math.IsInf(t.Bar3End, 0) && t.Bar3End > 0 &&
		t.Bar3End <= at && at-t.Bar3End <= 180 {
		a.Known, a.Price, a.At, a.BarEnd, a.Reason = true, t.EMA8_3, at, t.Bar3End, "新規要求時点の確定3分EMA8"
	}
	return a
}

// replayTimers は定時と強制返済境界を重複なしの時間順へまとめます。
//
// 引数: session(strategy.Session)は固定内部時計です。
// 返り値: []float64は全timer、map[float64]boolは新規判断定時、errorは場ID不正です。
func replayTimers(session strategy.Session) ([]float64, map[float64]bool, error) {
	grids, e := far80.ScheduledTimes(session.ID)
	if e != nil {
		return nil, nil, e
	}
	set := map[float64]bool{}
	times := append([]float64{}, grids...)
	for _, at := range grids {
		set[at] = true
	}
	times = append(times, session.ForceClose)
	if session.Kind == "Night" {
		times = append(times, session.USOpen-900, session.USOpen+900)
	}
	sort.Float64s(times)
	unique := times[:0]
	for _, at := range times {
		if len(unique) == 0 || unique[len(unique)-1] != at {
			unique = append(unique, at)
		}
	}
	return unique, set, nil
}

// recordSourceEvent は新返済がある時だけ、共有イベントを一度保存します。
//
// 引数: at(float64)、origin(string)、q(Quote)、snapshot(ReadSnapshot)、sourceLine(int64)はイベント出典です。
// 返り値: ありません。現在源snapshotの時計をtimer時計へ変更しません。
func (r *replayRuntime) recordSourceEvent(at float64, origin string, q Quote, snapshot ReadSnapshot, sourceLine int64) {
	if len(snapshot.Closes) == 0 {
		return
	}
	r.result.SourceEvents = append(r.result.SourceEvents, SourceEvent{At: at, Origin: origin, Quote: q, Method: snapshot.Method, SourceAt: snapshot.At, SourceIndex: snapshot.SourceIndex, SourceLine: sourceLine, Closes: append([]ReferenceClose{}, snapshot.Closes...)})
}

// sourceFrame は当原行でSourceを進めるか、Last不良なら直近現在量だけを読みます。
//
// 引数: q(Quote)、observation(*strategy.Observation)は実当行と正常Last時の元特徴です。
// 返り値: ReferenceFrameは全Sourceの現在量と当回だけのCloses、errorは参照不整合です。
func (r *replayRuntime) sourceFrame(q Quote, observation *strategy.Observation) (ReferenceFrame, error) {
	frame := ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}
	for _, name := range referenceOrder {
		ref := r.refs[name]
		if ref == nil {
			continue
		}
		part := ref.Frame()
		if observation != nil {
			var err error
			part, err = ref.Step(*observation)
			if err != nil {
				return frame, err
			}
			r.sourceLines[name] = q.Line
			snapshot, err := ref.ReadMetadata()
			if err != nil {
				return frame, err
			}
			legacy := r.legacyRefs[name]
			if legacy == nil {
				return frame, fmt.Errorf("固定80Sourceが未準備")
			}
			old, err := legacy.Step(*observation)
			if err != nil {
				return frame, err
			}
			if err = r.compareSource("step", name, q.Time, snapshot, part, old); err != nil {
				return frame, err
			}
			if snapshot.At != observation.Time || snapshot.SourceIndex != observation.Index {
				return frame, fmt.Errorf("Source読取が当原行と不一致")
			}
			r.recordSourceEvent(q.Time, "quote", q, snapshot, q.Line)
			frame.Closes = append(frame.Closes, part.Closes...)
			r.result.ReferenceCounts[name]++
		}
		frame.Lots = append(frame.Lots, part.Lots...)
	}
	return frame, nil
}

// advanceTimer は当原行より前に境界通知と参照poolの定時取得を処理します。
//
// 引数: at(float64)、afterEOF(bool)は公開時計と終端後の区別です。
// 返り値: errorは参照・読取・金融接続の不整合です。
func (r *replayRuntime) advanceTimer(at float64, afterEOF bool) error {
	if err := r.bank.Advance(at); err != nil {
		return err
	}
	if at == r.session.ForceClose || (r.session.Kind == "Night" && at == r.session.USOpen-900) {
		reason := "場末10分前"
		if at != r.session.ForceClose {
			reason = "米国前枠終了"
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				if err := r.books[bookKey(mode, delay)].Force(at, r.last, reason); err != nil {
					return err
				}
			}
		}
		for _, name := range referenceOrder {
			ref := r.refs[name]
			if ref == nil {
				continue
			}
			if err := ref.Force(at, reason); err != nil {
				return err
			}
			legacy := r.legacyRefs[name]
			if legacy == nil {
				return fmt.Errorf("固定80Sourceが未準備")
			}
			if err := legacy.Force(at, reason); err != nil {
				return err
			}
			snapshot, err := ref.ReadMetadata()
			if err != nil {
				return err
			}
			if err = r.compareSource("force", name, at, snapshot, ref.Frame(), legacy.Frame()); err != nil {
				return err
			}
			r.recordSourceEvent(at, "timer", r.last, snapshot, r.sourceLines[name])
			if len(snapshot.Closes) > 0 {
				for _, mode := range Modes {
					for delay := 0; delay <= 1; delay++ {
						if err = r.books[bookKey(mode, delay)].OnReference(at, r.last, snapshot.Closes); err != nil {
							return err
						}
					}
				}
			}
		}
		if at == r.session.ForceClose {
			r.forceDone = true
		}
	}
	if r.session.Kind == "Night" && at == r.session.USOpen+900 {
		if r.refs["U165_03"] != nil {
			return fmt.Errorf("U165参照を二重に生成")
		}
		next, err := NewReference("U165_03", r.session, 100)
		if err != nil {
			return err
		}
		r.refs["U165_03"] = next
		old, err := far80.NewReference("U165_03", r.session, 100)
		if err != nil {
			return err
		}
		r.legacyRefs["U165_03"] = old
	}
	if !r.grids[at] {
		return nil
	}
	window, err := far80.WindowMethod(at, r.session.USOpen, r.session.Kind)
	if err != nil {
		return err
	}
	allowed, block := true, ""
	switch {
	case r.forceDone:
		allowed, block = false, "場末返済要求後"
	case window == "静観":
		allowed, block = false, "米国開始前後の静観"
	case afterEOF:
		allowed, block = false, "原板終端後の定時"
	}
	chart := r.bank.View()
	c0, err := Decide(at, r.last, chart, r.current)
	if err != nil {
		return err
	}
	snapshot := emptySnapshot()
	if ref := r.refs[window]; ref != nil {
		snapshot, err = ref.ReadMetadata()
		if err != nil {
			return err
		}
	}
	currentFrame, oldFrame := ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}, ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}
	if ref := r.refs[window]; ref != nil {
		currentFrame = ref.Frame()
		legacy := r.legacyRefs[window]
		if legacy == nil {
			return fmt.Errorf("固定80Sourceが未準備")
		}
		oldFrame = legacy.Frame()
	}
	if err = r.compareSource("grid", window, at, snapshot, currentFrame, oldFrame); err != nil {
		return err
	}
	snapshot.Closes = []ReferenceClose{}
	anchor := structureAnchorAt(at, chart)
	r.result.GridDecisions = append(r.result.GridDecisions, GridDecision{At: at, Window: window, ClockAllowed: allowed, BlockReason: block, C0: c0, Source: snapshot, SourceLine: r.sourceLines[window], StructureAnchor: anchor})
	supplied := snapshot
	if !allowed {
		supplied.Lots = []ReadLot{}
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			if err = r.books[bookKey(mode, delay)].OnSourceGrid(at, r.last, supplied, c0, chart.Technical, anchor); err != nil {
				return err
			}
		}
	}
	return nil
}

// observeQuote はSourceと実G1を当原行の順で進め、元Sourceへ実損益を返しません。
//
// 引数: q(Quote)、current(*CurrentEvidence)、observation(*strategy.Observation)は当原行で、Last不良時の源二値はnilです。
// 返り値: errorは足時計・源特徴・金融接続の不整合です。
func (r *replayRuntime) observeQuote(q Quote, current *CurrentEvidence, observation *strategy.Observation) error {
	chart := q
	chart.Valid = q.Last > 0
	if err := r.bank.Observe(chart); err != nil {
		return err
	}
	if current != nil {
		r.current = *current
	}
	frame, err := r.sourceFrame(q, observation)
	if err != nil {
		return err
	}
	technical := r.bank.View().Technical
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			if err = r.books[bookKey(mode, delay)].OnQuote(q, frame, technical, current); err != nil {
				return err
			}
		}
	}
	r.last = q
	return nil
}

// Replay は一場の特徴を一度だけ作り、全行Source・S/SC・二遅延を独立再生します。
//
// 引数: root(string)は固定入力根、input(InputSession)は場、bank(*far80.TechnicalBank)は当場前の種です。
// 返り値: ReplayResultは4会計と共有定時snapshot、errorは入力又は状態不整合です。
func Replay(root string, input InputSession, bank *far80.TechnicalBank) (ReplayResult, error) {
	result := ReplayResult{Session: input.ID, Quality: map[string]RawQuality{}, Books: map[string]BookResult{}, GridDecisions: []GridDecision{}, ReferenceCounts: map[string]int{}, SourceEvents: []SourceEvent{}}
	if bank == nil {
		return result, fmt.Errorf("技法種がnilです")
	}
	session, e := sessionClock(input.ID)
	if e != nil {
		return result, e
	}
	method := "D164_15"
	if session.Kind == "Night" {
		method = "P164_06"
	}
	params, e := strategy.ParametersForMethod("NK225", session.Kind, method)
	if e != nil {
		return result, e
	}
	if session.Kind == "Night" {
		u, err := strategy.ParametersForMethod("NK225", "Night", "U165_03")
		if err != nil {
			return result, err
		}
		if !reflect.DeepEqual(params.Features, u.Features) {
			return result, fmt.Errorf("二夜手法の特徴条件が異なります")
		}
	}
	features, e := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		return result, e
	}
	features.EnableResearch()
	boards, candles := []replayBoard{}, []candleEvent{}
	for _, reference := range []string{"TOPIX", "NK225"} {
		path, err := verifyInput(root, input.Files[reference+"_book"])
		if err != nil {
			return result, err
		}
		rows, quality, err := readBoards(path, reference, session)
		if err != nil {
			return result, err
		}
		if len(quality.Contracts) != 1 {
			return result, fmt.Errorf("限月混在又は不明:%s %v", reference, quality.Contracts)
		}
		if reference == "NK225" && quality.Contracts[0] != input.Contract {
			return result, fmt.Errorf("NK限月不一致")
		}
		result.Quality[reference] = quality
		boards = append(boards, rows...)
		for _, interval := range []int{60, 300} {
			path, err = verifyInput(root, input.Files[fmt.Sprintf("%s_candle_%d", reference, interval)])
			if err != nil {
				return result, err
			}
			events, err := readCandles(path, reference, interval, params.Features.CandleDelay, session)
			if err != nil {
				return result, err
			}
			candles = append(candles, events...)
		}
	}
	sort.SliceStable(boards, func(i, j int) bool { return boards[i].Board.Time < boards[j].Board.Time })
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })
	first, e := NewReference(method, session, 100)
	if e != nil {
		return result, e
	}
	refs := map[string]replayReference{method: first}
	legacy, err := far80.NewReference(method, session, 100)
	if err != nil {
		return result, err
	}
	legacyRefs := map[string]replayLegacyReference{method: legacy}
	books := map[string]*Book{}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book, err := NewSourceBook(input.ID, sourcePolicy(mode), 100)
			if err != nil {
				return result, err
			}
			if err = book.SetFillDelay(float64(delay)); err != nil {
				return result, err
			}
			books[bookKey(mode, delay)] = book
		}
	}
	times, grids, e := replayTimers(session)
	if e != nil {
		return result, e
	}
	chartBank := NewChartBank(bank)
	chartBank.BeginSession(session.Start)
	runtime := replayRuntime{session: session, bank: chartBank, books: books, last: Quote{Index: -1}, grids: grids, result: &result, refs: refs, sourceLines: map[string]int64{}, legacyRefs: legacyRefs}
	timerIndex, candleIndex := 0, 0
	actualIndex := int64(-1)
	// ----------------------------------------
	// 同時計の当原行を先取りせず、公開timer→足CSV→源特徴→実保護の順に進めます。
	for _, row := range boards {
		for timerIndex < len(times) && times[timerIndex] <= row.Board.Time {
			at := times[timerIndex]
			timerIndex++
			if e = runtime.advanceTimer(at, false); e != nil {
				return result, e
			}
		}
		for candleIndex < len(candles) && candles[candleIndex].At <= row.Board.Time {
			event := candles[candleIndex]
			candleIndex++
			if _, e = features.AddCandles(event.Reference, event.Interval, []strategy.Candle{event.Candle}, event.At); e != nil {
				return result, e
			}
		}
		if row.Board.Last <= 0 {
			if row.Board.Reference == "NK225" {
				actualIndex++
				q := Quote{Time: row.Board.Time, Index: actualIndex, Line: row.Line, Last: row.Board.Last, Bid: row.Board.Bid, Ask: row.Board.Ask, Valid: false}
				if e = runtime.observeQuote(q, nil, nil); e != nil {
					return result, e
				}
			}
			continue
		}
		observation, err := features.OnBoard(row.Board)
		if err != nil {
			return result, err
		}
		if observation.Reference != "NK225" {
			continue
		}
		actualIndex++
		q := Quote{Time: observation.Time, Index: actualIndex, Line: row.Line, Last: observation.Last, Bid: observation.Bid, Ask: observation.Ask, Valid: observation.QuoteOK && observation.Last > 0}
		current := ExtractCurrent(observation, row.Line)
		if e = runtime.observeQuote(q, &current, &observation); e != nil {
			return result, e
		}
	}
	// ----------------------------------------
	// 終端後の時計も記録し、約定価格や未観測の返済を補完しません。
	for timerIndex < len(times) {
		at := times[timerIndex]
		timerIndex++
		if e = runtime.advanceTimer(at, true); e != nil {
			return result, e
		}
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(mode, delay)
			result.Books[key] = books[key].Result()
		}
	}
	return result, nil
}
