package actorport97

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash"
	"reflect"
	"strings"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

// RunResult は全field結果と全原行現在値の順次指紋を分けます。
type RunResult struct {
	Books         map[string]json.RawMessage `json:"books"`
	StateSHA256   map[string]string          `json:"state_sha256"`
	GateCallbacks map[string]int             `json:"gate_callbacks"`
}

// Configurations は入口2×出口指定×費用2×遅延2を列挙します。
//
// 引数: exits([]string)は空又はH0の明示集合です。
// 返り値: []Configは独立金融を作るための値だけです。
func Configurations(exits []string) []Config {
	out := []Config{}
	for _, gate := range []string{"", "AB"} {
		for _, exit := range exits {
			for _, slip := range []float64{0, 5} {
				for _, delay := range []int{0, 1} {
					out = append(out, Config{Gate: gate, Harvest: exit, Slip: slip, Delay: delay})
				}
			}
		}
	}
	return out
}

// RunArtificial は人工だけのTapeからfactoryへ同順の公開入力を配送します。
//
// 引数: input(tape.Tape)、factory(Factory)、configs([]Config)は停止入力と金融生成口です。
// 返り値: RunResult/errorは全金融結果と全原行指紋です。市場Tapeを拒否します。
func RunArtificial(input tape.Tape, factory Factory, configs []Config) (RunResult, error) {
	if !strings.HasPrefix(input.Scope, "固定96Go型人工") || len(input.Provenance) != 0 {
		return RunResult{}, fmt.Errorf("この接続器は手製API人工専用です")
	}
	return Run(input, factory, configs)
}

// Run はファイルを読まず指定されたTapeを同じ順で各factoryへ配送します。
//
// 引数: input(tape.Tape)、factory(Factory)、configs([]Config)は明示された不変入力と金融生成口です。
// 返り値: RunResult/errorは全金融結果と全原行指紋です。市場の運転許可は呼出元CLIで別に固定します。
func Run(input tape.Tape, factory Factory, configs []Config) (RunResult, error) {
	out := RunResult{Books: map[string]json.RawMessage{}, StateSHA256: map[string]string{}, GateCallbacks: map[string]int{}}
	if input.Version != 1 || !reflect.DeepEqual(input.Capabilities, tape.Capabilities()) {
		return out, fmt.Errorf("Tapeの版又は対応範囲が不明です")
	}
	before, err := json.Marshal(input)
	if err != nil {
		return out, err
	}
	actors, chains := []Actor{}, []hash.Hash{}
	for _, cfg := range configs {
		a, err := factory.New(input.Session, cfg)
		if err != nil {
			return out, err
		}
		actors, chains = append(actors, a), append(chains, sha256.New())
		state, err := a.Snapshot()
		if err != nil {
			return out, err
		}
		chains[len(chains)-1].Write(state)
	}
	last := map[string]int64{}
	previous := 0.0
	for i, event := range input.Events {
		if event.Ordinal != i+1 || event.At < previous {
			return out, fmt.Errorf("イベント順序不正")
		}
		previous = event.At
		switch event.Kind {
		case "quote", "force":
			batches, err := tape.RestoreBatches(event, last)
			if err != nil {
				return out, err
			}
			batchBefore, err := json.Marshal(batches)
			if err != nil {
				return out, err
			}
			for _, actor := range actors {
				if event.Kind == "quote" {
					if event.Quote == nil || event.At != event.Quote.Time {
						return out, fmt.Errorf("当原行時計不正")
					}
					err = actor.Step(event.Quote.Observation(), event.Quote.SourceLine, batches)
				} else {
					err = actor.Force(event.At, batches)
				}
				if err != nil {
					return out, err
				}
				after, err := json.Marshal(batches)
				if err != nil {
					return out, err
				}
				if !bytes.Equal(batchBefore, after) {
					return out, fmt.Errorf("共用Source通知の書換え")
				}
			}
		case "grid":
			if event.Quote != nil || event.Context == nil || event.Context.At != event.At || len(event.Methods)+len(event.NonEmpty) != 0 {
				return out, fmt.Errorf("gridのclock/文脈/Source混入")
			}
			for _, actor := range actors {
				if err := actor.Grid(event.At, event.Context); err != nil {
					return out, err
				}
			}
		default:
			return out, fmt.Errorf("不明なイベント")
		}
		for j, actor := range actors {
			state, err := actor.Snapshot()
			if err != nil {
				return out, err
			}
			chains[j].Write(state)
		}
	}
	for i, actor := range actors {
		key, result, err := actor.Finish()
		if err != nil {
			return out, err
		}
		if _, exists := out.Books[key]; exists {
			return out, fmt.Errorf("同keyの金融重複")
		}
		chains[i].Write(result)
		out.Books[key], out.StateSHA256[key], out.GateCallbacks[key] = result, hex.EncodeToString(chains[i].Sum(nil)), actor.Callbacks()
	}
	after, err := json.Marshal(input)
	if err != nil {
		return out, err
	}
	if !bytes.Equal(before, after) {
		return out, fmt.Errorf("Tape入力を書換え")
	}
	return out, nil
}
