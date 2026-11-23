package far81

import (
	"fmt"
	"reflect"
	"sort"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// GridDecision は定時の当時入力と、入口政策二案の独立判定を保存します。
// CandidateAcceptedは時計を満たした候補frame生成で、Bookの実採用ではありません。
// 実注文の正本は各BookのDecisions/Ordersです。全snapshotはDecision内に一度だけ置きます。
type GridDecision struct {
	At                float64       `json:"at"`
	Window            string        `json:"window"`
	EntryPolicy       string        `json:"entry_policy"`
	Decision          EntryDecision `json:"decision"`
	ClockAllowed      bool          `json:"clock_allowed"`
	BlockReason       string        `json:"block_reason"`
	CandidateAccepted bool          `json:"candidate_accepted"`
}

// ReplayResult は一場の共有入力と四政策・二遅延の実所有を分けた成果物です。
type ReplayResult struct {
	Session       string                `json:"session"`
	Quality       map[string]RawQuality `json:"quality"`
	Books         map[string]BookResult `json:"books"`
	GridDecisions []GridDecision        `json:"grid_decisions"`
}

type replayRuntime struct {
	session   strategy.Session
	bank      *far80.TechnicalBank
	books     map[string]*Book
	last      Quote
	current   CurrentEvidence
	forceDone bool
	grids     map[float64]bool
	result    *ReplayResult
}

// bookKey は四政策と追加価格時計遅延を一意な保存キーへ写します。
//
// 引数: mode(string)はB0G0等、delay(int)は0又は1です。
// 返り値: stringはB0G0_D0等のキーです。
func bookKey(mode string, delay int) string { return fmt.Sprintf("%s_D%d", mode, delay) }

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

// advanceTimer は当原行より先に境界返済と定時判断を処理します。
//
// 引数: at(float64)はtimer時計、afterEOF(bool)は全原板終端後かです。
// 返り値: errorは技法時計・判定・所有会計の不整合です。
func (r *replayRuntime) advanceTimer(at float64, afterEOF bool) error {
	if e := r.bank.Advance(at); e != nil {
		return e
	}
	if at == r.session.ForceClose || (r.session.Kind == "Night" && at == r.session.USOpen-900) {
		reason := "場末10分前"
		if at != r.session.ForceClose {
			reason = "米国前枠終了"
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				if e := r.books[bookKey(mode, delay)].Force(at, r.last, reason); e != nil {
					return e
				}
			}
		}
		if at == r.session.ForceClose {
			r.forceDone = true
		}
	}
	if !r.grids[at] {
		return nil
	}
	window, e := far80.WindowMethod(at, r.session.USOpen, r.session.Kind)
	if e != nil {
		return e
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
	// ----------------------------------------
	// 入口は保護・遅延に依存させず、当時snapshotから各政策一度だけ判定します。
	technical := r.bank.View()
	for _, policy := range []string{"B0", "B1"} {
		decision := Decide(at, r.last, technical, r.current, policy)
		frame := ReferenceFrame{}
		if allowed {
			frame = decision.Candidate(r.session.ID, window, 100)
		}
		if len(frame.Lots) > 1 || len(frame.Closes) > 0 {
			return fmt.Errorf("定時候補は最大一玉で、源返済通知を含めません")
		}
		r.result.GridDecisions = append(r.result.GridDecisions, GridDecision{At: at, Window: window, EntryPolicy: policy, Decision: decision, ClockAllowed: allowed, BlockReason: block, CandidateAccepted: len(frame.Lots) > 0})
		for _, guard := range []string{"G0", "G1"} {
			for delay := 0; delay <= 1; delay++ {
				if e := r.books[bookKey(policy+guard, delay)].OnGrid(at, r.last, frame, technical); e != nil {
					return e
				}
			}
		}
	}
	return nil
}

// observeQuote は技法Lastと実BBOを分離して、全政策の連続保護を進めます。
//
// 引数: q(Quote)は実原行、current(*CurrentEvidence)は当行の源特徴で不良Last時はnilです。
// 返り値: errorは技法時計又は実会計不整合です。
func (r *replayRuntime) observeQuote(q Quote, current *CurrentEvidence) error {
	chart := q
	chart.Valid = q.Last > 0
	if e := r.bank.Observe(chart); e != nil {
		return e
	}
	if current != nil {
		r.current = *current
	}
	technical := r.bank.View()
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			if e := r.books[bookKey(mode, delay)].OnQuote(q, ReferenceFrame{}, technical); e != nil {
				return e
			}
		}
	}
	r.last = q
	return nil
}

// Replay は一場の特徴を一度だけ作り、四入口保護政策と二遅延を独立に再生します。
//
// 引数: root(string)は固定入力根、input(InputSession)は場、bank(*far80.TechnicalBank)は当場前の種です。
// 返り値: ReplayResultは8会計と共有定時snapshot、errorは入力又は状態不整合です。
func Replay(root string, input InputSession, bank *far80.TechnicalBank) (ReplayResult, error) {
	result := ReplayResult{Session: input.ID, Quality: map[string]RawQuality{}, Books: map[string]BookResult{}, GridDecisions: []GridDecision{}}
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
	books := map[string]*Book{}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book, err := NewBook(input.ID, mode, 100)
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
	bank.BeginSession(session.Start)
	runtime := replayRuntime{session: session, bank: bank, books: books, last: Quote{Index: -1}, grids: grids, result: &result}
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
				if e = runtime.observeQuote(q, nil); e != nil {
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
		if e = runtime.observeQuote(q, &current); e != nil {
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
