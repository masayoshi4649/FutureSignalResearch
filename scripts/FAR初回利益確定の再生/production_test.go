package actorport97

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

// TestProductionObserverSameArtificial は重い観測を外した配送と純評価保存を6人工で照合します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。最終全Book/現在候補評価回数はRunへ、空97の純評価は旧人工へ結びます。
func TestProductionObserverSameArtificial(t *testing.T) {
	paths, err := filepath.Glob(filepath.Join("..", "..", "work", "96結合人工", "初回", "方向*.json"))
	if err != nil || len(paths) != 6 {
		t.Fatal("固定6人工が必要", err)
	}
	for _, path := range paths {
		t.Run(filepath.Base(path), func(t *testing.T) {
			fixture, err := tape.LoadFixture(path)
			if err != nil {
				t.Fatal(err)
			}
			input, err := tape.FixtureTape(fixture)
			if err != nil {
				t.Fatal(err)
			}
			expected, err := RunArtificial(input, Harvest97{}, Configurations([]string{"", "H0"}))
			if err != nil {
				t.Fatal(err)
			}
			records := []GateAssessmentRecord{}
			got, err := RunProduction(input, CapturedHarvest{Records: &records}, Configurations([]string{"", "H0"}))
			if err != nil {
				t.Fatal(err)
			}
			x, _ := json.Marshal(expected.Books)
			y, _ := json.Marshal(got.Books)
			if !bytes.Equal(x, y) {
				t.Fatal("最終全Book差")
			}
			x, _ = json.Marshal(expected.GateCallbacks)
			y, _ = json.Marshal(got.GateCallbacks)
			if !bytes.Equal(x, y) {
				t.Fatal("現在候補評価回数差")
			}
			if len(got.StateSHA256) != 0 || len(records) == 0 {
				t.Fatal("未計測と純評価保存の境界")
			}
			counts := map[string]int{}
			for _, r := range records {
				if r.Assessment.Decision.Policy != "AB" || !strings.Contains(r.Key, "AB_") {
					t.Fatal("観測のpolicy/key差")
				}
				counts[r.Key]++
			}
			for key, count := range got.GateCallbacks {
				if count != counts[key] {
					t.Fatal("純評価の欠落/重複")
				}
			}
			if out := os.Getenv("PRODUCTION97_EXPORT"); out != "" {
				if err := os.MkdirAll(out, 0755); err != nil {
					t.Fatal(err)
				}
				contexts := []any{}
				for _, e := range input.Events {
					if e.Kind == "grid" {
						contexts = append(contexts, e.Context)
					}
				}
				proof := map[string]any{"scope": "停止96Go型手製Source/技法/ATRの人工。自然Source/Raw Chart形成/正式市場対照は未計測", "tape": input, "output": map[string]any{"session": input.Session.ID, "books": got.Books, "chart_grids": contexts, "gate_assessments": records, "source_reexecuted": false, "charts_recomputed": false, "P0_96_match": map[string]any{"all": true, "books": 8, "scope": "手製API人工の旧96全文限定。正式市場8会計の証明ではない"}}, "callback_counts": got.GateCallbacks, "Run最終全Book同値": true}
				body, err := json.MarshalIndent(proof, "", "  ")
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(out, filepath.Base(path)), append(body, '\n'), 0644); err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}
