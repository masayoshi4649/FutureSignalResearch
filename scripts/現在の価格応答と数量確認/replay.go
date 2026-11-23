// 84派生元: scripts/構造否定と利益配分/replay.go
// 84派生元SHA256: 0b0a4dd7aeb959214764b7ae4055510e35469251258eded8ee43fe4f7ef28558

package far84

// 83派生元: scripts/チャートの現在性と補助確認/replay.go
// 83派生元SHA256: 3b6ae6adb77602246c4c21a191c0118d88ed559958eb4f6af335cf315a18b811

// 派生元: scripts/定時の現在根拠と部分利益保護/replay.go
// 派生元SHA256: bd73fa2276e2f566f6561b4d70c8053208fa4f6a2111c09d158da40c9ea1d924
// 元ファイルは固定のまま編集しません。

import (
	"fmt"
	"math"
	"reflect"
	"sort"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// PolicyDirection は旧方向全snapshotを重複せず、追加入口の採否と必須チェックだけを保存します。
type PolicyDirection struct {
	Side            int                `json:"side"`
	Allowed         bool               `json:"allowed"`
	Role            string             `json:"role"`
	Reason          string             `json:"reason"`
	RequiredUnknown bool               `json:"required_unknown"`
	AddedChecks     []far81.EntryCheck `json:"added_checks"`
}

// PolicySnapshot は一入口の最終採否と候補供給を分け、旧全snapshotは含めません。
type PolicySnapshot struct {
	Allowed           bool              `json:"allowed"`
	Side              int               `json:"side"`
	Role              string            `json:"role"`
	Reason            string            `json:"reason"`
	RequiredUnknown   bool              `json:"required_unknown"`
	Directions        []PolicyDirection `json:"directions"`
	CandidateAccepted bool              `json:"candidate_accepted"`
}

// policySnapshot は純判定から旧全snapshotを除いた保存値を作ります。
//
// 引数: decision(Decision)は純入口、accepted(bool)は時計も通した候補供給です。
// 返り値: PolicySnapshotは旧方向全checksを重複しない独立した保存値です。
func policySnapshot(decision Decision, accepted bool) PolicySnapshot {
	value := PolicySnapshot{Allowed: decision.Allowed, Side: decision.Side, Role: decision.Role, Reason: decision.Reason,
		RequiredUnknown: decision.RequiredUnknown, CandidateAccepted: accepted, Directions: []PolicyDirection{}}
	for _, direction := range decision.Directions {
		value.Directions = append(value.Directions, PolicyDirection{Side: direction.Base.Side, Allowed: direction.Allowed,
			Role: direction.Role, Reason: direction.Reason, RequiredUnknown: direction.RequiredUnknown,
			AddedChecks: append([]far81.EntryCheck{}, direction.Added...)})
	}
	return value
}

// GridDecision は旧B1の当時入力一つと、三入口の採否と、要求時点の構造線を保存します。
// CandidateAcceptedは時計を満たした候補frame生成で、Bookの実採用ではありません。
// 実注文の正本は各BookのDecisions/Ordersです。全snapshotはDecision内に一度だけ置きます。
type GridDecision struct {
	At                float64                   `json:"at"`
	Window            string                    `json:"window"`
	EntryPolicy       string                    `json:"entry_policy"`
	Decision          EntryDecision             `json:"decision"`
	ClockAllowed      bool                      `json:"clock_allowed"`
	BlockReason       string                    `json:"block_reason"`
	CandidateAccepted bool                      `json:"candidate_accepted"`
	StructureAnchor   StructureAnchor           `json:"structure_anchor"`
	Policies          map[string]PolicySnapshot `json:"policies"`
}

// ReplayResult は一場の共有入力と三入口・同じS0G1出口・二遅延の実所有を分けた成果物です。
type ReplayResult struct {
	Session       string                `json:"session"`
	Quality       map[string]RawQuality `json:"quality"`
	Books         map[string]BookResult `json:"books"`
	GridDecisions []GridDecision        `json:"grid_decisions"`
}

type replayRuntime struct {
	session   strategy.Session
	bank      *ChartBank
	books     map[string]*Book
	last      Quote
	current   CurrentEvidence
	forceDone bool
	grids     map[float64]bool
	result    *ReplayResult
}

// bookKey は外側の三入口政策と追加価格時計遅延を一意な保存キーへ写します。
//
// 引数: mode(string)はA0G1/C0G1/C1G1、delay(int)は0又は1です。
// 返り値: stringはA0G1_D0等の外側キーです。
func bookKey(mode string, delay int) string { return fmt.Sprintf("%s_D%d", mode, delay) }

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
	// 旧B1全snapshotを一度だけ保存し、三入口の追加ANDを同じ固定出口へ渡します。
	chart := r.bank.View()
	decision := far82.Decide(at, r.last, chart, r.current, "B1")
	anchor := structureAnchorAt(at, chart)
	frames := map[string]ReferenceFrame{}
	policies := map[string]PolicySnapshot{}
	for _, policy := range []string{"A0", "C0", "C1"} {
		refined, err := Refine(decision, policy)
		if err != nil {
			return fmt.Errorf("%s:%w", policy, err)
		}
		frame := ReferenceFrame{}
		if allowed {
			frame = refined.Candidate(r.session.ID, window, 100)
		}
		if len(frame.Lots) > 1 || len(frame.Closes) > 0 {
			return fmt.Errorf("定時候補は最大一玉で、源返済通知を含めません")
		}
		frames[policy] = frame
		policies[policy] = policySnapshot(refined, len(frame.Lots) > 0)
	}
	r.result.GridDecisions = append(r.result.GridDecisions, GridDecision{At: at, Window: window, EntryPolicy: "B1", Decision: decision, ClockAllowed: allowed, BlockReason: block, CandidateAccepted: policies["A0"].CandidateAccepted, StructureAnchor: anchor, Policies: policies})
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			if e := r.books[bookKey(mode, delay)].OnGrid(at, r.last, frames[mode[:2]], chart.Technical, anchor); e != nil {
				return e
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
	technical := r.bank.View().Technical
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

// Replay は一場の特徴を一度だけ作り、三入口・同じS0G1出口・二遅延を独立に再生します。
//
// 引数: root(string)は固定入力根、input(InputSession)は場、bank(*far80.TechnicalBank)は当場前の種です。
// 返り値: ReplayResultは6会計と共有定時snapshot、errorは入力又は状態不整合です。
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
	chartBank := NewChartBank(bank)
	chartBank.BeginSession(session.Start)
	runtime := replayRuntime{session: session, bank: chartBank, books: books, last: Quote{Index: -1}, grids: grids, result: &result}
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
