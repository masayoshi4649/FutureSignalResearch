// 由来: scripts/FAR背景と勢いと数量の再生/replay.go
// 由来SHA256: fc20573ad874233bcdef7e8eef572d36a5c11ff7ecf56237c6c96ab6a03cbd1f
package grossport100

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	e3 "github.com/masayoshi4649/SessionTradeExecuter/minie3"
)

// Keys は実factory順と同じ12口座名を返します。
//
// 引数: ありません。
// 返り値: []stringはP0空/H0/HG→費用→遅延順です。
func Keys() []string {
	out := []string{}
	for _, c := range Configurations() {
		prefix := "E3S_"
		if c.Harvest != "" {
			prefix = c.Harvest + "_" + prefix
		}
		out = append(out, fmt.Sprintf("%sB5Q_P0_C%.0f_D%d", prefix, c.Slip, c.Delay))
	}
	return out
}

// ReplayProtection は同じ不変Tapeを独立12口座へ一巡で配送します。
//
// 引数: input(tape.Tape)、artificial(bool)は固定入力と人工全時点観測の指定です。
// 返り値: port.RunResult/[]GateAssessmentRecord/errorは最終12口座と現在全checkです。
// productionは停止97.RunProductionを直接再用し、全原行Bookの複写連鎖を省きます。
func ReplayProtection(input tape.Tape, artificial bool) (port.RunResult, []GateAssessmentRecord, error) {
	if artificial && (!strings.HasPrefix(input.Scope, "固定100Go型人工") || len(input.Provenance) != 0) {
		return port.RunResult{}, nil, fmt.Errorf("人工専用観測に市場Tapeを渡せません")
	}
	records := []GateAssessmentRecord{}
	factory := ProtectionFactory{Records: &records}
	var out port.RunResult
	var err error
	if artificial {
		out, err = port.Run(input, factory, Configurations())
	} else {
		out, err = port.RunProduction(input, factory, Configurations())
	}
	if err != nil {
		return out, nil, err
	}
	if len(out.Books) != 12 {
		return out, nil, fmt.Errorf("100は12会計が必要")
	}
	if err = ValidateGateRecords(input, out, records); err != nil {
		return out, nil, err
	}
	return out, records, nil
}

// ValidateGateRecords は12key・現在候補・本名・全checksの保存集合を検査します。
//
// 引数: input(tape.Tape)、result(port.RunResult)、records([]GateAssessmentRecord)は同運転です。
// 返り値: errorは欠落/重複/順序/政策偽装です。保存採否は再利用しません。
func ValidateGateRecords(input tape.Tape, result port.RunResult, records []GateAssessmentRecord) error {
	rank := map[string]int{}
	for i, key := range Keys() {
		rank[key] = i
	}
	if len(result.Books) != len(rank) || len(result.GateCallbacks) != len(rank) {
		return fmt.Errorf("100結果の12集合不足")
	}
	for key := range result.Books {
		if _, ok := rank[key]; !ok {
			return fmt.Errorf("100候補外Key")
		}
	}
	for key := range result.GateCallbacks {
		if _, ok := rank[key]; !ok {
			return fmt.Errorf("100callback候補外Key")
		}
	}
	contexts := map[float64]string{}
	frames := map[float64]actual.TechnicalGateInput{}
	for _, e := range input.Events {
		if e.Kind == "grid" {
			if e.Context == nil || e.Context.At != e.At || contexts[e.At] != "" {
				return fmt.Errorf("grid文脈欠落/重複")
			}
			contexts[e.At] = e.Context.SnapshotID
			frames[e.At] = *e.Context
		}
	}
	seen, counts := map[string]bool{}, map[string]int{}
	previousAt, previousRank, previousOrdinal := -1.0, -1, -1
	for _, r := range records {
		policy := "E3S"
		n, ok := rank[r.Key]
		if !ok || policy == "" || r.Ordinal <= 0 || r.Ordinal != r.Candidate.Ordinal || !reflect.DeepEqual(r.Source, r.Candidate.Source) || r.Assessment.Decision.Policy != policy || contexts[r.Candidate.At] != r.Assessment.Decision.SnapshotID {
			return fmt.Errorf("99現在候補/政策/公開枠の結合差")
		}
		checkCount := 9
		if len(r.Assessment.Checks) != checkCount {
			return fmt.Errorf("E3Sの全checkが欠落")
		}
		current, err := e3.AssessTechnicalGate(frames[r.Candidate.At], r.Candidate, "E3S")
		if err != nil || !reflect.DeepEqual(current, r.Assessment) {
			return fmt.Errorf("本名E3Sの現在候補/全9checkと保存値が不一致")
		}
		id := fmt.Sprintf("%s\x00%d\x00%.17g", r.Key, r.Ordinal, r.Candidate.At)
		if seen[id] {
			return fmt.Errorf("純式callback重複")
		}
		seen[id] = true
		counts[r.Key]++
		at := r.Candidate.At
		if at < previousAt || at == previousAt && (n < previousRank || n == previousRank && r.Ordinal <= previousOrdinal) {
			return fmt.Errorf("純式保存順が時計/12Key/ordinalでない")
		}
		previousAt, previousRank, previousOrdinal = at, n, r.Ordinal
	}
	for _, key := range Keys() {
		if result.GateCallbacks[key] != counts[key] {
			return fmt.Errorf("12callback集合の欠落")
		}
	}
	return nil
}

// canonical は全JSON値を保持したまま表記順だけを揃えます。
//
// 引数: raw(json.RawMessage)は全口座JSONです。
// 返り値: []byte/errorは正規化したJSON又は不正JSONです。
func canonical(raw json.RawMessage) ([]byte, error) {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, err
	}
	return json.Marshal(v)
}
