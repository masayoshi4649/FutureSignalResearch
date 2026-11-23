// 88派生元: scripts/FAR参照玉と可変数量の比較/source_equivalence.go
// 88派生元SHA256: a3b079682ae47b72b4a59f29eaedfa1f3d50ab612b921c6bde107014033d6199

package far88

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash"
	"reflect"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// SourceEquivalence は固定80driverとmetadata投影の全pool一致を小型保存します。
type SourceEquivalence struct {
	StepFrames    int    `json:"step_frames"`
	ForceFrames   int    `json:"force_frames"`
	GridFrames    int    `json:"grid_frames"`
	CurrentSHA256 string `json:"current_sha256"`
	LegacySHA256  string `json:"legacy_sha256"`
	Mismatches    int    `json:"mismatches"`
}

type frameHashes struct {
	current hash.Hash
	legacy  hash.Hash
}

// replayLegacyReference は別インスタンスの固定80参照driverだけを受けます。
type replayLegacyReference interface {
	Step(strategy.Observation) (ReferenceFrame, error)
	Force(float64, string) error
	Frame() ReferenceFrame
}

// projectedFrame はmetadataの全参照玉を元順序のまま旧Frameへ戻します。
//
// 引数: snapshot(ReadSnapshot)は読取済みの全poolです。
// 返り値: ReferenceFrameは全玉と当回Closesで、数量・IDを選別しません。
func projectedFrame(snapshot ReadSnapshot) ReferenceFrame {
	frame := ReferenceFrame{Lots: []ReferenceLot{}, Closes: append([]ReferenceClose{}, snapshot.Closes...)}
	for _, lot := range snapshot.Lots {
		frame.Lots = append(frame.Lots, lot.Reference)
	}
	return frame
}

// compareSource は各Step/Force/定時の全Frameを固定80と比較し順次指紋へ加えます。
//
// 引数: phase/method(string)、at(float64)、snapshot(ReadSnapshot)、current/legacy(ReferenceFrame)は同じ公開入力の両参照です。
// 返り値: errorはmetadataの玉脱落又は元driverとの全pool不一致です。独立売買実装の証明とはしません。
func (r *replayRuntime) compareSource(phase, method string, at float64, snapshot ReadSnapshot, current, legacy ReferenceFrame) error {
	projected := projectedFrame(snapshot)
	if !reflect.DeepEqual(projected, current) || !reflect.DeepEqual(projected, legacy) {
		r.result.SourceEquivalence.Mismatches++
		return fmt.Errorf("Source全poolのmetadata/固定80互換差:%s %s", phase, method)
	}
	if r.frameHashes == nil {
		r.frameHashes = &frameHashes{current: sha256.New(), legacy: sha256.New()}
	}
	for i, frame := range []ReferenceFrame{projected, legacy} {
		value := struct {
			Phase       string         `json:"phase"`
			Method      string         `json:"method"`
			At          float64        `json:"at"`
			SourceIndex int64          `json:"source_index"`
			Frame       ReferenceFrame `json:"frame"`
		}{phase, method, at, snapshot.SourceIndex, frame}
		var err error
		if i == 0 {
			err = json.NewEncoder(r.frameHashes.current).Encode(value)
		} else {
			err = json.NewEncoder(r.frameHashes.legacy).Encode(value)
		}
		if err != nil {
			return err
		}
	}
	switch phase {
	case "step":
		r.result.SourceEquivalence.StepFrames++
	case "force":
		r.result.SourceEquivalence.ForceFrames++
	case "grid":
		r.result.SourceEquivalence.GridFrames++
	default:
		return fmt.Errorf("Source互換比較の段階が不正")
	}
	r.result.SourceEquivalence.CurrentSHA256 = hex.EncodeToString(r.frameHashes.current.Sum(nil))
	r.result.SourceEquivalence.LegacySHA256 = hex.EncodeToString(r.frameHashes.legacy.Sum(nil))
	return nil
}
