package miniprotect

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

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
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
	Session       string                   `json:"session"`
	Contract      string                   `json:"contract"`
	Quality       map[string]RawQuality    `json:"quality"`
	FeatureConfig json.RawMessage          `json:"feature_config"`
	SourceRows    map[string]int           `json:"source_rows"`
	Shadows       map[string]native.Ledger `json:"shadows"`
	Books         map[string]ActualResult  `json:"books"`
	ShadowMatch   ShadowMatch              `json:"shadow_match"`
}

// allConfigs は損益前に定義した3政策×2費用×2遅延だけを列挙します。
//
// 引数: なし。返り値: []ActorConfigは固定12口座です。
func allConfigs() []ActorConfig {
	out := []ActorConfig{}
	for _, policy := range []string{"S0", "P0", "P1"} {
		for _, slip := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				out = append(out, ActorConfig{Policy: policy, SlipPts: slip, DelaySeconds: delay})
			}
		}
	}
	return out
}

// configKey は異なる政策・費用・遅延を混同しない口座名を作ります。
//
// 引数: cfg(ActorConfig)は固定設定。返り値: stringは保存キーです。
func configKey(cfg ActorConfig) string {
	return fmt.Sprintf("%s_C%.0f_D%d", cfg.Policy, cfg.SlipPts, cfg.DelaySeconds)
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

// Replay は93のShadow入力時計を維持し、独立12Actorを同原行で一度ずつ進めます。
//
// 引数: root(string)、input(InputSession)は固定原入力、baseline/proof(string)は93正本です。
// 返り値: ReplayResult/errorは全保存口座とShadow一致、又は未完了の理由です。
func Replay(root string, input InputSession, baseline, proof string) (ReplayResult, error) {
	out := ReplayResult{Session: input.ID, Contract: input.Contract, Quality: map[string]RawQuality{}, SourceRows: map[string]int{}, Shadows: map[string]native.Ledger{}, Books: map[string]ActualResult{}}
	session, err := sessionClock(input.ID)
	if err != nil {
		return out, err
	}
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
	actorKeys := []string{}
	for _, cfg := range allConfigs() {
		actor, err := NewActualBook(session, cfg)
		if err != nil {
			return out, err
		}
		key := configKey(cfg)
		actors[key] = actor
		actorKeys = append(actorKeys, key)
	}
	timers := []float64{session.ForceClose}
	if session.Kind == "Night" {
		timers = append(timers, session.USOpen-900, session.USOpen+900)
	}
	sort.Float64s(timers)
	ti, ci := 0, 0
	// ----------------------------------------
	// Sourceは一度だけ更新し、Actorの損益・保護から切り離す。
	for _, row := range boards {
		for ti < len(timers) && timers[ti] <= row.Board.Time {
			at := timers[ti]
			ti++
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
	for ti < len(timers) {
		at := timers[ti]
		ti++
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
	if err = checkMirrors(out.Books, out.Shadows); err != nil {
		return out, err
	}
	out.ShadowMatch, err = compareShadow(baseline, proof, input.ID, out.Shadows)
	if err != nil {
		return out, err
	}
	return out, nil
}
