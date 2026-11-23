package actorport97

import (
	"bytes"
	"encoding/json"
	"fmt"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	"reflect"
)

// RunProduction は停止Runと同じ順で配送し、全原行BookのJSON観測だけを省きます。
//
// 引数: input(tape.Tape)、factory(Factory)、configs([]Config)は明示した入力と金融生成口です。
// 返り値: RunResult/errorは最終全Bookと現在Gate呼出数です。StateSHA256は未計測の空mapです。
// 非空通知の全Actor前後不変と全Tape前後不変は保持し、収益/速度優位は主張しません。
func RunProduction(input tape.Tape, factory Factory, configs []Config) (RunResult, error) {
	out := RunResult{Books: map[string]json.RawMessage{}, StateSHA256: map[string]string{}, GateCallbacks: map[string]int{}}
	if input.Version != 1 || !reflect.DeepEqual(input.Capabilities, tape.Capabilities()) {
		return out, fmt.Errorf("Tapeの版又は対応範囲が不明です")
	}
	before, err := json.Marshal(input)
	if err != nil {
		return out, err
	}
	actors := []Actor{}
	for _, cfg := range configs {
		a, err := factory.New(input.Session, cfg)
		if err != nil {
			return out, err
		}
		actors = append(actors, a)
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
			var batchBefore []byte
			if len(event.NonEmpty) > 0 {
				batchBefore, err = json.Marshal(batches)
				if err != nil {
					return out, err
				}
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

			}
			if len(event.NonEmpty) > 0 {
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

	}
	for _, actor := range actors {
		key, result, err := actor.Finish()
		if err != nil {
			return out, err
		}
		if _, exists := out.Books[key]; exists {
			return out, fmt.Errorf("同keyの金融重複")
		}
		out.Books[key], out.GateCallbacks[key] = result, actor.Callbacks()
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
