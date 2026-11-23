package actorport97

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	harvest "github.com/masayoshi4649/SessionTradeExecuter/miniharvest"
)

// TestFactoriesArtificial は停止した6人工で全原行と最終JSONを検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Hは人工だけで実行し、空設定は旧96全文へ比較します。
func TestFactoriesArtificial(t *testing.T) {
	paths, err := filepath.Glob(filepath.Join("..", "..", "work", "96結合人工", "初回", "方向*.json"))
	if err != nil || len(paths) != 6 {
		t.Fatal("固定6人工が必要", err, len(paths))
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
			old, err := RunArtificial(input, Fixed96{}, Configurations([]string{""}))
			if err != nil {
				t.Fatal(err)
			}
			current, err := RunArtificial(input, Harvest97{}, Configurations([]string{"", "H0"}))
			if err != nil {
				t.Fatal(err)
			}
			again, err := RunArtificial(input, Harvest97{}, Configurations([]string{"", "H0"}))
			if err != nil {
				t.Fatal(err)
			}
			firstJSON, _ := json.Marshal(current)
			secondJSON, _ := json.Marshal(again)
			if !bytes.Equal(firstJSON, secondJSON) {
				t.Fatal("同人工の二運転が非決定的")
			}
			if len(old.Books) != 8 || len(current.Books) != 16 {
				t.Fatal("金融件数")
			}
			harvestOrders, callbacks := 0, 0
			for key, result := range old.Books {
				expected, err := json.Marshal(fixture.Actors[key])
				if err != nil {
					t.Fatal(err)
				}
				if !bytes.Equal(result, expected) {
					t.Fatalf("旧96本体と元Go人工が相違 %s", key)
				}
				if !bytes.Equal(result, current.Books[key]) || old.StateSHA256[key] != current.StateSHA256[key] {
					t.Fatalf("空97の全原行/最終全文差 %s", key)
				}
				if old.GateCallbacks[key] != current.GateCallbacks[key] {
					t.Fatal("空97の現在候補評価回数差")
				}
				callbacks += current.GateCallbacks[key]
			}
			for key, result := range current.Books {
				if !strings.HasPrefix(key, "H0_") {
					continue
				}
				var typed harvest.ActualResult
				if err := json.Unmarshal(result, &typed); err != nil {
					t.Fatal(err)
				}
				for _, order := range typed.Orders {
					if order.Reason == "初回費用後残玉正益の全量確定" {
						harvestOrders++
					}
				}
				if typed.Config.HarvestPolicy != "H0" {
					t.Fatal("H設定が失われた")
				}
			}
			if callbacks == 0 || (!strings.Contains(path, "容量取消未知") && harvestOrders == 0) {
				t.Fatal("AB純評価/H要求が非0でなければ接続を証明しない", callbacks, harvestOrders)
			}
			if out := os.Getenv("ACTOR97_EXPORT"); out != "" {
				if err := os.MkdirAll(out, 0755); err != nil {
					t.Fatal(err)
				}
				proof := map[string]any{"scope": "停止96Go型手製人工。H市場損益/自然Source/Raw Chart形成/旧96実市場共有は未計測", "fixture": path, "旧96": old, "新97": current, "旧96/空97全文一致": 8, "全原行snapshot指紋一致": true, "H0保護要求": harvestOrders}
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

// TestNamedBoundaryPreservesAllFields は名前付き型間の無変形を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Source/Quoteを含む全fieldが同じJSONであることを検査します。
func TestNamedBoundaryPreservesAllFields(t *testing.T) {
	paths, _ := filepath.Glob(filepath.Join("..", "..", "work", "96結合人工", "初回", "方向*.json"))
	f, err := tape.LoadFixture(paths[0])
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, step := range f.Steps {
		a, _ := json.Marshal(step.Batches)
		b, _ := json.Marshal(ConvertBatches(step.Batches))
		if !bytes.Equal(a, b) {
			t.Fatal("全配送型変換のfield差")
		}
		for _, batch := range step.Batches {
			for _, signal := range batch.Delta.Signals {
				if signal.Signal.Action != "new" {
					continue
				}
				var source harvest.SourceIdentity
				for _, actor := range f.Actors {
					if len(actor.EntryOpportunities) > 0 {
						body, _ := json.Marshal(actor.EntryOpportunities[0].Source)
						if err := json.Unmarshal(body, &source); err != nil {
							t.Fatal(err)
						}
						break
					}
				}
				candidate := harvest.EntryCandidate{Ordinal: 7, At: f.Grids[0], Side: signal.Signal.Side, Source: source, Quote: signal.Quote, Available: 9, Quantity: 3}
				x, _ := json.Marshal(candidate)
				y, _ := json.Marshal(ConvertCandidate(candidate))
				if !bytes.Equal(x, y) {
					t.Fatal("候補変換のfield差")
				}
				d := actual.GateDecision{Policy: "AB", SnapshotID: "人工snapshot", Known: true, Allowed: true, Role: "順行", Reason: "人工理由"}
				x, _ = json.Marshal(d)
				y, _ = json.Marshal(harvest.GateDecision(d))
				if !bytes.Equal(x, y) {
					t.Fatal("返答型変換のfield差")
				}
				count++
			}
		}
	}
	if count == 0 {
		t.Fatal("非空通知を検査していない")
	}
}

// TestMarketTapeRejected は現段階で市場Hを実行できない境界を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。実2場Tapeを読むことなく人工のscopeを壊して拒否を確認します。
func TestMarketTapeRejected(t *testing.T) {
	paths, _ := filepath.Glob(filepath.Join("..", "..", "work", "96結合人工", "初回", "方向*.json"))
	f, err := tape.LoadFixture(paths[0])
	if err != nil {
		t.Fatal(err)
	}
	input, err := tape.FixtureTape(f)
	if err != nil {
		t.Fatal(err)
	}
	input.Provenance = map[string]string{"固定96市場入力": "人工の拒否用"}
	if _, err := RunArtificial(input, Harvest97{}, Configurations([]string{"H0"})); err == nil {
		t.Fatal("市場Hの境界が無い")
	}
	if _, err := (Fixed96{}).New(input.Session, Config{Harvest: "H0"}); err == nil {
		t.Fatal("旧96にHを代入")
	}
}
