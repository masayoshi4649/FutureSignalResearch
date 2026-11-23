package riskport98

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
)

// TestNoRiskFullBaselineBoundaries は旧H0八会計だけへ除外0比較する境界を検査します。
//
// 引数: t(*testing.T)は試験器。
// 返り値: ありません。旧P0への偽装・欠落・半円差・未知tagの追加を拒否します。
func TestNoRiskFullBaselineBoundaries(t *testing.T) {
	input := fixtureTape(t, filepath.Join("..", "..", "work", "98初期ATR追尾案", "人工", "停止版", "方向1_幅と次板悪化.json"))
	result, _, err := ReplayRisk(input, false)
	if err != nil {
		t.Fatal(err)
	}
	records := []port.GateAssessmentRecord{}
	old, err := port.RunProduction(input, port.CapturedHarvest{Records: &records}, port.Configurations([]string{"H0"}))
	if err != nil {
		t.Fatal(err)
	}
	keys, err := CompareEmptyRisk97(result.Books, old.Books)
	if err != nil || len(keys) != 8 {
		t.Fatal("正常旧H0全JSON比較", err)
	}
	key := keys[0]
	missing := clone(old.Books)
	delete(missing, key)
	if _, err = CompareEmptyRisk97(result.Books, missing); err == nil {
		t.Fatal("旧基準欠落を許可")
	}
	fakeP0 := clone(result.Books)
	fakeP0[strings.TrimPrefix(key, "H0_")] = fakeP0[key]
	delete(fakeP0, key)
	if _, err = CompareEmptyRisk97(fakeP0, old.Books); err == nil {
		t.Fatal("P0偽装を許可")
	}
	for _, mode := range []string{"半円", "新tag"} {
		changed := clone(old.Books)
		var row map[string]any
		if err = json.Unmarshal(changed[key], &row); err != nil {
			t.Fatal(err)
		}
		if mode == "半円" {
			totals := row["totals"].(map[string]any)
			totals["net_yen"] = totals["net_yen"].(float64) + .5
		} else {
			row["余分な実績欄"] = true
		}
		changed[key], err = json.Marshal(row)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = CompareEmptyRisk97(result.Books, changed); err == nil {
			t.Fatal("全field差を許可", mode)
		}
	}
}

// TestCanonicalMergeAndStage はログの公開順と旧stage集合guardを狭く確認します。
//
// 引数: t(*testing.T)は試験器。
// 返り値: ありません。金融/市場を運転せず2時計×3keyの並びと集合を確認します。
func TestCanonicalMergeAndStage(t *testing.T) {
	keys := []string{"H0_AB", "R05_H0_AB", "R10_H0_AB"}
	records := []GateAssessmentRecord{}
	for _, key := range keys {
		for _, at := range []float64{10, 20} {
			r := GateAssessmentRecord{Key: key, Ordinal: 1}
			r.Candidate.At = at
			records = append(records, r)
		}
	}
	if err := CanonicalGateRecords(keys, records); err != nil {
		t.Fatal(err)
	}
	for i, r := range records {
		want := 10.0
		if i >= 3 {
			want = 20
		}
		if r.Candidate.At != want || r.Key != keys[i%3] {
			t.Fatal("同時計24順位merge", records)
		}
	}
	if CanonicalGateRecords(append(keys, keys[0]), records) == nil {
		t.Fatal("順位重複を許可")
	}
	if CanonicalGateRecords(keys[:2], records) == nil {
		t.Fatal("順位なしログを許可")
	}
	sha := strings.Repeat("a", 64)
	index := TapeIndex{Version: 1, Stage: "first2", Entries: []TapeEntry{{Session: "2026-09-21_Day", Path: "人工Day", SHA256: sha}, {Session: "2026-09-21_Night", Path: "人工Night", SHA256: sha}}}
	if err := port.ValidateIndex(index, "first2", nil); err != nil {
		t.Fatal(err)
	}
	index.Entries[1].Session = index.Entries[0].Session
	if port.ValidateIndex(index, "first2", nil) == nil {
		t.Fatal("stage重複を許可")
	}
	if RunBatch(BatchArguments{}) == nil {
		t.Fatal("必須CLI不足を許可")
	}
}
