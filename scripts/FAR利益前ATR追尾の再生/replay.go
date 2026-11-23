package riskport98

import (
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"strings"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

// ReplayRisk は同じ不変Tapeを独立した三群×八会計へ配送します。
//
// 引数: input(tape.Tape)、artificial(bool)は固定入力と全時点観測の人工指定です。
// 返り値: port.RunResult/[]GateAssessmentRecord/errorは24全結果と現在の純判定です。
// 本番は旧RunProductionを直接再用し、全原行Book Snapshot連鎖を作りません。
func ReplayRisk(input tape.Tape, artificial bool) (port.RunResult, []GateAssessmentRecord, error) {
	out := port.RunResult{Books: map[string]json.RawMessage{}, StateSHA256: map[string]string{}, GateCallbacks: map[string]int{}}
	records := []GateAssessmentRecord{}
	order := []string{}
	if artificial && (!strings.HasPrefix(input.Scope, "固定98Go型人工") || len(input.Provenance) != 0) {
		return out, nil, fmt.Errorf("人工モードに市場Tapeを渡せません")
	}
	for _, policy := range []string{"", "R05", "R10"} {
		factory := RiskFactory{Policy: policy, Records: &records, Order: &order}
		var group port.RunResult
		var err error
		if artificial {
			group, err = port.Run(input, factory, port.Configurations([]string{"H0"}))
		} else {
			group, err = port.RunProduction(input, factory, port.Configurations([]string{"H0"}))
		}
		if err != nil {
			return out, nil, err
		}
		for key, value := range group.Books {
			if _, exists := out.Books[key]; exists {
				return out, nil, fmt.Errorf("24会計のkey重複")
			}
			out.Books[key] = value
			out.GateCallbacks[key] = group.GateCallbacks[key]
			if artificial {
				out.StateSHA256[key] = group.StateSHA256[key]
			}
		}
	}
	if len(out.Books) != 24 {
		return out, nil, fmt.Errorf("98は24会計が必要")
	}
	if err := CanonicalGateRecords(order, records); err != nil {
		return out, nil, err
	}
	if err := ValidateGateRecords(input, out, records); err != nil {
		return out, nil, err
	}
	return out, records, nil
}

// CanonicalGateRecords は独立三配送のログだけを同時計24順へ並べます。
//
// 引数: order([]string)、records([]GateAssessmentRecord)は実factory生成順と純判定です。
// 返り値: errorはkey集合の不整合です。金融採否/値は変更せず、at→24key順位→ordinalだけで整列します。
func CanonicalGateRecords(order []string, records []GateAssessmentRecord) error {
	rank := map[string]int{}
	for i, key := range order {
		if _, exists := rank[key]; exists {
			return fmt.Errorf("factory key順位が重複")
		}
		rank[key] = i
	}
	for _, r := range records {
		if _, exists := rank[r.Key]; !exists {
			return fmt.Errorf("factory順位のない純判定")
		}
	}
	sort.SliceStable(records, func(i, j int) bool {
		a, b := records[i], records[j]
		if a.Candidate.At != b.Candidate.At {
			return a.Candidate.At < b.Candidate.At
		}
		if rank[a.Key] != rank[b.Key] {
			return rank[a.Key] < rank[b.Key]
		}
		return a.Ordinal < b.Ordinal
	})
	return nil
}

// ValidateGateRecords は現在候補/Key/ordinal/atとcallback集合の欠落・重複を検査します。
//
// 引数: input(tape.Tape)、result(port.RunResult)、records([]GateAssessmentRecord)は当運転です。
// 返り値: errorは保存判定の結合不整合です。採否を別戦略から転記しません。
func ValidateGateRecords(input tape.Tape, result port.RunResult, records []GateAssessmentRecord) error {
	contexts := map[float64]string{}
	for _, e := range input.Events {
		if e.Kind == "grid" {
			if e.Context == nil {
				return fmt.Errorf("grid文脈欠落")
			}
			if _, exists := contexts[e.At]; exists {
				return fmt.Errorf("grid時計重複")
			}
			contexts[e.At] = e.Context.SnapshotID
		}
	}
	seen, counts := map[string]bool{}, map[string]int{}
	for _, r := range records {
		if _, ok := result.Books[r.Key]; !ok || !strings.Contains(r.Key, "AB_") || r.Ordinal != r.Candidate.Ordinal || r.Ordinal <= 0 || !reflect.DeepEqual(r.Source, r.Candidate.Source) || r.Assessment.Decision.Policy != "AB" || contexts[r.Candidate.At] != r.Assessment.Decision.SnapshotID {
			return fmt.Errorf("現在候補の純判定結合が不一致")
		}
		key := fmt.Sprintf("%s\x00%d\x00%.17g", r.Key, r.Ordinal, r.Candidate.At)
		if seen[key] {
			return fmt.Errorf("現在候補の純判定重複")
		}
		seen[key] = true
		counts[r.Key]++
	}
	for key, count := range result.GateCallbacks {
		if counts[key] != count {
			return fmt.Errorf("純判定のcallback集合が欠落")
		}
	}
	return nil
}
