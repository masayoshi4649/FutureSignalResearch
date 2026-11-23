package mininative

import (
	"fmt"
	"reflect"
	"sort"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// ReplayResult は一場の元連続判断のminiとmicro対照を保存します。
type ReplayResult struct {
	Session    string                `json:"session"`
	Quality    map[string]RawQuality `json:"quality"`
	SourceRows map[string]int        `json:"source_rows"`
	Books      map[string]Ledger     `json:"books"`
}

// Replay は固定54場のうち一場を、元の連続判断と次正常気配で再生します。
//
// 引数: root(string)は原データ根、input(InputSession)は指紋付きの場です。
// 返り値: ReplayResultは商品別の実配分と外費用台帳、errorは入力又は会計の不整合です。
func Replay(root string, input InputSession) (ReplayResult, error) {
	result := ReplayResult{Session: input.ID, Quality: map[string]RawQuality{}, SourceRows: map[string]int{}, Books: map[string]Ledger{}}
	session, err := sessionClock(input.ID)
	if err != nil {
		return result, err
	}
	method := "D164_15"
	if session.Kind == "Night" {
		method = "P164_06"
	}
	params, err := strategy.ParametersForMethod("NK225", session.Kind, method)
	if err != nil {
		return result, err
	}
	if session.Kind == "Night" {
		after, err := strategy.ParametersForMethod("NK225", "Night", "U165_03")
		if err != nil {
			return result, err
		}
		if !reflect.DeepEqual(params.Features, after.Features) {
			return result, fmt.Errorf("二夜手法の特徴条件が不一致です")
		}
	}
	features, err := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if err != nil {
		return result, err
	}
	features.EnableResearch()
	boards := []replayBoard{}
	candles := []candleEvent{}
	for _, ref := range []string{"TOPIX", "NK225"} {
		path, err := verifyInput(root, input.Files[ref+"_book"])
		if err != nil {
			return result, err
		}
		rows, quality, err := readBoards(path, ref, session)
		if err != nil {
			return result, err
		}
		if len(quality.Contracts) != 1 || (ref == "NK225" && quality.Contracts[0] != input.Contract) {
			return result, fmt.Errorf("限月不明又は不一致です: %s", ref)
		}
		result.Quality[ref] = quality
		boards = append(boards, rows...)
		for _, interval := range []int{60, 300} {
			path, err = verifyInput(root, input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)])
			if err != nil {
				return result, err
			}
			rows, err := readCandles(path, ref, interval, params.Features.CandleDelay, session)
			if err != nil {
				return result, err
			}
			candles = append(candles, rows...)
		}
	}
	sort.SliceStable(boards, func(i, j int) bool { return boards[i].Board.Time < boards[j].Board.Time })
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })

	// ----------------------------------------
	// 元Selected会計へ直接約定を返し、残玉poolからの遅い新規取得を作らない。
	adapters := map[string]*Adapter{}
	order := []string{}
	for _, product := range []string{"micro", "mini"} {
		config := MicroControlConfig()
		if product == "mini" {
			config = MiniConfig()
		}
		adapter, err := NewAdapter(method, session, config)
		if err != nil {
			return result, err
		}
		key := product + "_" + method
		adapters[key] = adapter
		order = append(order, key)
	}
	timers := []float64{session.ForceClose}
	if session.Kind == "Night" {
		timers = append(timers, session.USOpen-900, session.USOpen+900)
	}
	sort.Float64s(timers)
	timerIndex, candleIndex := 0, 0
	for _, row := range boards {
		for timerIndex < len(timers) && timers[timerIndex] <= row.Board.Time {
			at := timers[timerIndex]
			timerIndex++
			if session.Kind == "Night" && at == session.USOpen+900 {
				for _, product := range []string{"micro", "mini"} {
					before := adapters[product+"_P164_06"].Snapshot()
					if !before.Forced || !before.Complete {
						return result, fmt.Errorf("米国前の所有・予約の照合が未完了です: %s", product)
					}
					config := MicroControlConfig()
					if product == "mini" {
						config = MiniConfig()
					}
					adapter, err := NewAdapter("U165_03", session, config)
					if err != nil {
						return result, err
					}
					key := product + "_U165_03"
					adapters[key] = adapter
					order = append(order, key)
				}
			} else {
				for _, key := range order {
					if _, err = adapters[key].Force(at); err != nil {
						return result, fmt.Errorf("%s: %w", key, err)
					}
				}
			}
		}
		for candleIndex < len(candles) && candles[candleIndex].At <= row.Board.Time {
			candle := candles[candleIndex]
			candleIndex++
			if _, err = features.AddCandles(candle.Reference, candle.Interval, []strategy.Candle{candle.Candle}, candle.At); err != nil {
				return result, err
			}
		}
		if row.Board.Last <= 0 {
			continue
		}
		observation, err := features.OnBoard(row.Board)
		if err != nil {
			return result, err
		}
		if observation.Reference != "NK225" {
			continue
		}
		for _, key := range order {
			if _, err = adapters[key].Step(observation, row.Line); err != nil {
				return result, fmt.Errorf("%s: %w", key, err)
			}
			result.SourceRows[key]++
		}
	}

	// ----------------------------------------
	// 実在しない末尾気配で約定を補わず、未返済や未約定は不完了にする。
	for timerIndex < len(timers) {
		at := timers[timerIndex]
		timerIndex++
		if session.Kind == "Night" && at == session.USOpen+900 {
			continue
		}
		for _, key := range order {
			if _, err = adapters[key].Force(at); err != nil {
				return result, fmt.Errorf("%s: %w", key, err)
			}
		}
	}
	for _, key := range order {
		ledger, err := adapters[key].Finish()
		result.Books[key] = ledger
		if err != nil {
			return result, fmt.Errorf("%s: %w", key, err)
		}
	}
	expected := 2
	if session.Kind == "Night" {
		expected = 4
	}
	if len(result.Books) != expected {
		return result, fmt.Errorf("対象の手法窓が欠落しています: %d/%d", len(result.Books), expected)
	}
	for _, key := range order {
		if result.SourceRows[key] == 0 {
			return result, fmt.Errorf("対象の手法窓に既知原行がありません: %s", key)
		}
	}
	return result, nil
}
