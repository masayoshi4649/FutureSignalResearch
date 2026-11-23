package minichart

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// ShadowMatch は正本93のmini全文と当場Shadowの同一性を保存します。
type ShadowMatch struct {
	BaselinePath        string          `json:"baseline_path"`
	BaselineSHA256      string          `json:"baseline_sha256"`
	BaselineProofSHA256 string          `json:"baseline_proof_sha256"`
	Methods             map[string]bool `json:"methods"`
	All                 bool            `json:"all"`
}

// ReplayResult は全Actorと、一度だけ運転した共通Shadowを保存します。
type ReplayResult struct {
	Session         string                   `json:"session"`
	Contract        string                   `json:"contract"`
	Quality         map[string]RawQuality    `json:"quality"`
	FeatureConfig   json.RawMessage          `json:"feature_config"`
	SourceRows      map[string]int           `json:"source_rows"`
	Shadows         map[string]native.Ledger `json:"shadows"`
	Books           map[string]ActualResult  `json:"books"`
	ShadowMatch     ShadowMatch              `json:"shadow_match"`
	NeutralMatch    Baseline95Match          `json:"baseline95_match"`
	ChartGrids      []TechnicalGateInput     `json:"chart_grids"`
	GateAssessments []GateAssessmentRecord   `json:"gate_assessments"`
	ChartEnd        warm.Snapshot            `json:"chart_end"`
}

// allConfigs は共通B5Q/P0の四技法政策×二費用×二遅延を作ります。
//
// 引数: session(Session)は場と既知米国時計です。
// 返り値: []ActorConfigは固定16口座です。
func allConfigs(session Session) []ActorConfig {
	out := []ActorConfig{}
	for _, gate := range []string{"", "A", "B", "AB"} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				out = append(out, ActorConfig{Policy: "P0", SlipPts: slip, DelaySeconds: delay, EntryTiming: "B5Q", USOpen: session.USOpen, GatePolicy: gate})
			}
		}
	}
	return out
}

// configKey はNの旧金融IDを保ち、B系だけ接頭辞を付けます。
//
// 引数: cfg(ActorConfig)は入口/費用/遅延です。
// 返り値: stringは口座の保存名です。
func configKey(cfg ActorConfig) string {
	key := fmt.Sprintf("%s_C%.0f_D%d", cfg.Policy, cfg.SlipPts, cfg.DelaySeconds)
	if cfg.EntryTiming != "" && cfg.EntryTiming != "N" {
		key = cfg.EntryTiming + "_" + key
	}
	if cfg.GatePolicy != "" {
		key = cfg.GatePolicy + "_" + key
	}
	return key
}

// captureActors は失敗位置の所有・予約を残し、途中状態を消さず診断へ渡します。
//
// 引数: out(*ReplayResult)、actors(map[string]*ActualBook)は保存先と実口座です。
// 返り値: なし。金融を更新せずSnapshotだけを読む。
func captureActors(out *ReplayResult, actors map[string]*ActualBook) {
	for key, actor := range actors {
		out.Books[key] = actor.Snapshot()
	}
}

// compareShadow は93の圧縮正本を指紋確認し、RawMessageを正規化して全文比較します。
//
// 引数: folder/proof(string)は93成果物と完了正本、session(string)、ledgers(map)は今回のShadow。
// 返り値: ShadowMatch/errorは全文一致の結果又は不一致です。
func compareShadow(folder, proof, session string, ledgers map[string]native.Ledger) (ShadowMatch, error) {
	check := ShadowMatch{Methods: map[string]bool{}}
	proofBody, err := os.ReadFile(proof)
	if err != nil {
		return check, err
	}
	proofSHA := sha256.Sum256(proofBody)
	check.BaselineProofSHA256 = hex.EncodeToString(proofSHA[:])
	if check.BaselineProofSHA256 != "e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37" {
		return check, fmt.Errorf("固定93の完了正本が変更されています")
	}
	var fixed struct {
		Files map[string]string `json:"自己を除く正式指紋"`
	}
	if err = json.Unmarshal(proofBody, &fixed); err != nil {
		return check, err
	}
	path := filepath.Join(folder, session+".json.gz")
	body, err := os.ReadFile(path)
	if err != nil {
		return check, err
	}
	digest := sha256.Sum256(body)
	check.BaselinePath = path
	check.BaselineSHA256 = hex.EncodeToString(digest[:])
	expected := fixed.Files["成果物\\"+session+".json.gz"]
	if expected == "" {
		expected = fixed.Files["成果物/"+session+".json.gz"]
	}
	if expected != check.BaselineSHA256 {
		return check, fmt.Errorf("固定93 Nativeの指紋差: %s", session)
	}
	stream, err := gzip.NewReader(bytes.NewReader(body))
	if err != nil {
		return check, err
	}
	defer stream.Close()
	var old native.ReplayResult
	if err = json.NewDecoder(stream).Decode(&old); err != nil {
		return check, err
	}
	if old.Session != session {
		return check, fmt.Errorf("固定93の場名差")
	}
	for method, actual := range ledgers {
		expected, ok := old.Books["mini_"+method]
		if !ok {
			return check, fmt.Errorf("固定93の手法欠落: %s", method)
		}
		left, err := json.Marshal(actual)
		if err != nil {
			return check, err
		}
		right, err := json.Marshal(expected)
		if err != nil {
			return check, err
		}
		check.Methods[method] = bytes.Equal(left, right)
		if !check.Methods[method] {
			return check, fmt.Errorf("93 Shadow全文不一致: %s %s", session, method)
		}
	}
	check.All = len(check.Methods) == len(ledgers) && len(ledgers) > 0
	return check, nil
}

// Replay は93のShadow入力時計を維持し、共通保護と枠時点採否の16Actorを同原行で一度ずつ進めます。
//
// 引数: root(string)、input(InputSession)は固定原入力、baseline/proof(string)は93正本です。
// protectBaseline/protectProof(string)は固定95、seed(*warm.Seed)は今回の場直前の数値種です。
// 返り値: ReplayResult/errorは全保存口座とShadow一致、又は未完了の理由です。
func Replay(root string, input InputSession, baseline, proof, protectBaseline, protectProof string, seed *warm.Seed) (ReplayResult, error) {
	out := ReplayResult{Session: input.ID, Contract: input.Contract, Quality: map[string]RawQuality{}, SourceRows: map[string]int{}, Shadows: map[string]native.Ledger{}, Books: map[string]ActualResult{}}
	session, err := sessionClock(input.ID)
	if err != nil {
		return out, err
	}
	chart, err := warm.New(warm.Scene{ID: input.ID, Contract: input.Contract, Start: session.Start}, seed)
	if err != nil {
		return out, err
	}
	history := []warm.Snapshot{}
	current := far82.CurrentEvidence{}
	nkIndex := int64(0)
	method := "D164_15"
	if session.Kind == "Night" {
		method = "P164_06"
	}
	params, err := strategy.ParametersForMethod("NK225", session.Kind, method)
	if err != nil {
		return out, err
	}
	if session.Kind == "Night" {
		other, err := strategy.ParametersForMethod("NK225", session.Kind, "U165_03")
		if err != nil {
			return out, err
		}
		if !reflect.DeepEqual(params.Features, other.Features) {
			return out, fmt.Errorf("二夜の特徴条件差")
		}
	}
	if params.Features.ATRPeriod != 12 || params.Features.ATRMinBars != 3 || params.Features.CandleDelay != 60 {
		return out, fmt.Errorf("固定native ATR条件が変わりました")
	}
	out.FeatureConfig, err = json.Marshal(params.Features)
	if err != nil {
		return out, err
	}
	features, err := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if err != nil {
		return out, err
	}
	features.EnableResearch()
	boards := []replayBoard{}
	candles := []candleEvent{}
	for _, ref := range []string{"TOPIX", "NK225"} {
		path, err := verifyInput(root, input.Files[ref+"_book"])
		if err != nil {
			return out, err
		}
		rows, quality, err := readBoards(path, ref, session)
		if err != nil {
			return out, err
		}
		if len(quality.Contracts) != 1 || ref == "NK225" && quality.Contracts[0] != input.Contract {
			return out, fmt.Errorf("限月不一致: %s", ref)
		}
		out.Quality[ref] = quality
		boards = append(boards, rows...)
		for _, interval := range []int{60, 300} {
			path, err = verifyInput(root, input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)])
			if err != nil {
				return out, err
			}
			rows, err := readCandles(path, ref, interval, params.Features.CandleDelay, session)
			if err != nil {
				return out, err
			}
			candles = append(candles, rows...)
		}
	}
	sort.SliceStable(boards, func(i, j int) bool { return boards[i].Board.Time < boards[j].Board.Time })
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })
	ref, err := native.NewAdapter(method, session, native.MiniConfig())
	if err != nil {
		return out, err
	}
	refs := map[string]*native.Adapter{method: ref}
	methods := []string{method}
	actors := map[string]*ActualBook{}
	actorPolicies := map[string]string{}
	actorKeys := []string{}
	for _, cfg := range allConfigs(session) {
		actor, err := NewActualBook(session, cfg)
		if err != nil {
			return out, err
		}
		key := configKey(cfg)
		actors[key] = actor
		actorPolicies[key] = cfg.GatePolicy
		actorKeys = append(actorKeys, key)
	}
	clocks, err := scheduledEvents(session)
	if err != nil {
		return out, err
	}
	ti, ci := 0, 0
	// ----------------------------------------
	// Sourceは一度だけ更新し、Actorの損益・保護から切り離す。
	for _, row := range boards {
		gridTimes := []float64{}
		for next := ti; next < len(clocks) && clocks[next].At <= row.Board.Time; next++ {
			if clocks[next].Grid {
				gridTimes = append(gridTimes, clocks[next].At)
			}
		}
		chartBatch, chartErr := chart.AdvanceObserved(row.Board.Time, gridTimes)
		if chartErr != nil {
			return out, chartErr
		}
		pi, gi := 0, 0
		for ti < len(clocks) && clocks[ti].At <= row.Board.Time {
			event := clocks[ti]
			at := event.At
			ti++
			if event.Grid {
				for pi < len(chartBatch.Publications) && chartBatch.Publications[pi].At <= at {
					history = appendChartHistory(history, chartBatch.Publications[pi].Snapshot)
					pi++
				}
				if gi >= len(chartBatch.Grids) || chartBatch.Grids[gi].At != at {
					return out, fmt.Errorf("チャート判断時計が枠と不一致")
				}
				context := TechnicalGateInput{SnapshotID: fmt.Sprintf("%s-G%04d", input.ID, len(out.ChartGrids)+1),
					At: at, Kind: session.Kind, Chart: chartBatch.Grids[gi], Recent3: append([]warm.Snapshot{}, history...), Current: valueCopy(current)}
				gi++
				out.ChartGrids = append(out.ChartGrids, context)
				for _, key := range actorKeys {
					policy := actorPolicies[key]
					var gate EntryGate
					if policy != "" {
						gate = func(candidate EntryCandidate) (GateDecision, error) {
							assessment, e := AssessTechnicalGate(context, candidate, policy)
							if e != nil {
								return GateDecision{}, e
							}
							out.GateAssessments = append(out.GateAssessments, GateAssessmentRecord{Key: key, Ordinal: candidate.Ordinal, Source: candidate.Source, Assessment: assessment})
							return assessment.Decision, nil
						}
					}
					if err = actors[key].OnEntryGridWithGate(at, gate); err != nil {
						captureActors(&out, actors)
						return out, fmt.Errorf("%s grid: %w", key, err)
					}
				}
				continue
			}
			if session.Kind == "Night" && at == session.USOpen+900 {
				before := refs["P164_06"].Snapshot()
				if !before.Forced || !before.Complete {
					return out, fmt.Errorf("Pの所有照合未完了")
				}
				ref, err := native.NewAdapter("U165_03", session, native.MiniConfig())
				if err != nil {
					return out, err
				}
				refs["U165_03"] = ref
				methods = append(methods, "U165_03")
			} else {
				batches := []NativeBatch{}
				for _, m := range methods {
					delta, err := refs[m].Force(at)
					if err != nil {
						return out, err
					}
					batches = append(batches, NativeBatch{Method: m, Delta: delta})
				}
				for _, key := range actorKeys {
					if err = actors[key].OnNativeForce(at, batches); err != nil {
						captureActors(&out, actors)
						return out, fmt.Errorf("%s timer: %w", key, err)
					}
				}
			}
		}
		if gi != len(chartBatch.Grids) {
			return out, fmt.Errorf("未使用のチャート枠があります")
		}
		for pi < len(chartBatch.Publications) {
			history = appendChartHistory(history, chartBatch.Publications[pi].Snapshot)
			pi++
		}
		if row.Board.Reference == "NK225" {
			q := warm.Quote{Time: row.Board.Time, Index: nkIndex, Line: row.Line, Last: row.Board.Last, Bid: row.Board.Bid, Ask: row.Board.Ask, Valid: row.Board.Last > 0}
			nkIndex++
			added, e := chart.Step(q, nil)
			if e != nil {
				return out, e
			}
			if len(added.Publications)+len(added.Grids) != 0 {
				return out, fmt.Errorf("同時計原行で先公開を再生成しました")
			}
		}
		for ci < len(candles) && candles[ci].At <= row.Board.Time {
			c := candles[ci]
			ci++
			if _, err = features.AddCandles(c.Reference, c.Interval, []strategy.Candle{c.Candle}, c.At); err != nil {
				return out, err
			}
		}
		if row.Board.Last <= 0 {
			continue
		}
		observation, err := features.OnBoard(row.Board)
		if err != nil {
			return out, err
		}
		if observation.Reference != "NK225" {
			continue
		}
		current = far82.ExtractCurrent(observation, row.Line)
		batches := []NativeBatch{}
		nonempty := false
		for _, m := range methods {
			delta, err := refs[m].Step(observation, row.Line)
			if err != nil {
				return out, err
			}
			out.SourceRows[m]++
			if len(delta.Signals)+len(delta.Fills)+len(delta.Cancellations) > 0 {
				nonempty = true
			}
			batches = append(batches, NativeBatch{Method: m, Delta: delta})
		}
		var before []byte
		if nonempty {
			before, _ = json.Marshal(batches)
		}
		for _, key := range actorKeys {
			if err = actors[key].OnNativeStep(observation, row.Line, batches); err != nil {
				captureActors(&out, actors)
				return out, fmt.Errorf("%s quote: %w", key, err)
			}
		}
		if nonempty {
			after, _ := json.Marshal(batches)
			if !bytes.Equal(before, after) {
				return out, fmt.Errorf("Actorが共用Source通知を書き換えました")
			}
		}
	}
	// ----------------------------------------
	// EOFに架空の市場行を足さない。timer通知のみ進め、未返済は失敗へ残す。
	_, out.ChartEnd, err = chart.Seal()
	if err != nil {
		return out, err
	}
	for ti < len(clocks) {
		event := clocks[ti]
		ti++
		if event.Grid {
			continue
		}
		at := event.At
		if session.Kind == "Night" && at == session.USOpen+900 {
			continue
		}
		batches := []NativeBatch{}
		for _, m := range methods {
			delta, err := refs[m].Force(at)
			if err != nil {
				return out, err
			}
			batches = append(batches, NativeBatch{Method: m, Delta: delta})
		}
		for _, key := range actorKeys {
			if err = actors[key].OnNativeForce(at, batches); err != nil {
				captureActors(&out, actors)
				return out, err
			}
		}
	}
	for _, m := range methods {
		ledger, err := refs[m].Finish()
		out.Shadows[m] = ledger
		if err != nil {
			return out, err
		}
		if out.SourceRows[m] <= 0 {
			return out, fmt.Errorf("Source窓に既知行がない: %s", m)
		}
	}
	need := 1
	if session.Kind == "Night" {
		need = 2
	}
	if len(out.Shadows) != need {
		return out, fmt.Errorf("Source窓が欠落")
	}
	for _, key := range actorKeys {
		result, err := actors[key].Finish()
		out.Books[key] = result
		if err != nil {
			return out, fmt.Errorf("%s finish: %w", key, err)
		}
	}
	out.NeutralMatch, err = compareBaseline95(protectBaseline, protectProof, input.ID, out.Books)
	if err != nil {
		return out, err
	}
	out.ShadowMatch, err = compareShadow(baseline, proof, input.ID, out.Shadows)
	if err != nil {
		return out, err
	}
	return out, nil
}
