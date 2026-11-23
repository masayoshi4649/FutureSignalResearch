package minie3

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

type saved302Entry struct {
	Session      string  `json:"session"`
	EntryOrderID string  `json:"entry_order_id"`
	SnapshotID   string  `json:"snapshot_id"`
	Group        string  `json:"group"`
	At           float64 `json:"at"`
	CheckStates  string  `json:"check_states"`
}

type saved302Source struct {
	CheckOrder []string          `json:"チェック順"`
	Entries    []saved302Entry   `json:"入口索引"`
	Inputs     map[string]string `json:"入力SHA256"`
}

type saved302Opportunity struct {
	Ordinal        int            `json:"ordinal"`
	At             float64        `json:"evaluated_at"`
	Side           int            `json:"side"`
	Source         SourceIdentity `json:"source"`
	Quote          QuoteStamp     `json:"quote"`
	Available      int            `json:"available"`
	SourceQuantity int            `json:"source_quantity"`
	EntryOrderID   string         `json:"entry_order_id"`
	Requested      int            `json:"requested"`
}

type saved302Scene struct {
	ChartGrids []TechnicalGateInput `json:"chart_grids"`
	Books      map[string]struct {
		Opportunities []saved302Opportunity `json:"entry_opportunities"`
	} `json:"books"`
}

// Test99Saved302 は既使用保存Contextと主入口候補だけへ純式を適用します。
//
// 引数: t(*testing.T)。明示環境MINIE3_VERIFY_302=1のときだけ保存54Nativeを読みます。
// 返り値: ありません。損益/退出後/Raw/Source/金融を計算せず、未知を含む全604判断を照合します。
func Test99Saved302(t *testing.T) {
	if os.Getenv("MINIE3_VERIFY_302") != "1" {
		t.Skip("既使用302の保存純式照合は明示実行だけ")
	}
	root := repo99()
	sourcePath := filepath.Join(root, "work", "98入口状態の比較", "結果.json")
	body, err := os.ReadFile(sourcePath)
	if err != nil || hash99(body) != "37261350b06e5abe86622d7ec3d05b7bfaea3c11372be7817d62102b0a505676" {
		t.Fatal("固定302記述の指紋差", err)
	}
	var expected saved302Source
	if err := json.Unmarshal(body, &expected); err != nil || len(expected.Entries) != 302 || len(expected.CheckOrder) != 20 {
		t.Fatal("302索引のschema", err)
	}
	inputs := map[string]string{sourcePath: hash99(body)}
	indices := map[string]int{}
	for i, name := range expected.CheckOrder {
		indices[name] = i
	}
	scenes := map[string]saved302Scene{}
	byID := map[string]map[string]saved302Opportunity{}
	frames := map[string]map[float64]TechnicalGateInput{}
	for _, row := range expected.Entries {
		if _, exists := scenes[row.Session]; exists {
			continue
		}
		rel := filepath.Join("work", "97実行", "正式54場", row.Session+".json")
		path := filepath.Join(root, rel)
		raw, err := os.ReadFile(path)
		if err != nil || hash99(raw) != expected.Inputs[rel] {
			t.Fatal("固定Nativeの差", row.Session, err)
		}
		inputs[path] = hash99(raw)
		var scene saved302Scene
		if err := json.Unmarshal(raw, &scene); err != nil {
			t.Fatal(err)
		}
		scenes[row.Session] = scene
		byID[row.Session] = map[string]saved302Opportunity{}
		for _, opportunity := range scene.Books["H0_B5Q_P0_C0_D0"].Opportunities {
			if opportunity.EntryOrderID != "" {
				byID[row.Session][opportunity.EntryOrderID] = opportunity
			}
		}
		frames[row.Session] = map[float64]TechnicalGateInput{}
		for _, frame := range scene.ChartGrids {
			frames[row.Session][frame.At] = frame
		}
	}
	if len(scenes) != 54 {
		t.Fatal("固定54場だけを要求")
	}
	counts := map[string]map[string]map[string]int{}
	for _, policy := range []string{"E3", "E3S"} {
		counts[policy] = map[string]map[string]int{}
		for _, group := range []string{"No-u", "u正益"} {
			counts[policy][group] = map[string]int{"成立": 0, "既知拒否": 0, "未知": 0}
		}
	}
	seen := map[string]bool{}
	for _, row := range expected.Entries {
		if seen[row.EntryOrderID] {
			t.Fatal("入口重複")
		}
		seen[row.EntryOrderID] = true
		op, exists := byID[row.Session][row.EntryOrderID]
		if !exists || op.At != row.At {
			t.Fatal("実受理候補がありません", row.EntryOrderID)
		}
		in := frames[row.Session][row.At]
		if in.SnapshotID != row.SnapshotID {
			t.Fatal("要求時の公開Context差")
		}
		quantity := min(op.Source.BirthQuantity, op.SourceQuantity, op.Available)
		if quantity != op.Requested {
			t.Fatal("元の実受理量差")
		}
		candidate := EntryCandidate{Ordinal: op.Ordinal, At: op.At, Side: op.Side, Source: op.Source, Quote: op.Quote, Available: op.Available, Quantity: quantity}
		before, _ := json.Marshal([]any{in, candidate})
		for _, policy := range []string{"E3", "E3S"} {
			got := assess99(t, in, candidate, policy)
			unknown, refused := false, false
			for _, check := range got.Checks {
				index, exists := indices[check.ID]
				if !exists {
					t.Fatal("比較元にないcheck", check.ID)
				}
				state := row.CheckStates[index]
				if check.Known != (state != '?') || check.Passed != (state == '+') {
					t.Fatal("固定Python記述のcheckと差", row.EntryOrderID, check)
				}
				unknown = unknown || state == '?'
				refused = refused || state == '-'
			}
			if got.Decision.Known != (refused || !unknown) || got.Decision.Allowed != (!refused && !unknown) || got.Decision.Policy != policy || got.Decision.SnapshotID != row.SnapshotID {
				t.Fatal("302の三値Decision差", row.EntryOrderID, got.Decision)
			}
			label := "未知"
			if got.Decision.Allowed {
				label = "成立"
			} else if got.Decision.Known {
				label = "既知拒否"
			}
			counts[policy][row.Group][label]++
		}
		after, _ := json.Marshal([]any{in, candidate})
		if string(before) != string(after) {
			t.Fatal("302の入力を変更")
		}
	}
	if !reflect.DeepEqual(counts["E3"], map[string]map[string]int{"No-u": {"成立": 0, "既知拒否": 45, "未知": 4}, "u正益": {"成立": 28, "既知拒否": 208, "未知": 17}}) {
		t.Fatal("前段E3表と差", counts)
	}
	if counts["E3S"]["No-u"]["成立"] != 0 || counts["E3S"]["u正益"]["成立"] != 28 {
		t.Fatal("旧spike別枝と差", counts)
	}
	for path, before := range inputs {
		after, err := os.ReadFile(path)
		if err != nil || hash99(after) != before {
			t.Fatal("入力前後の差", path, err)
		}
	}
	if output := os.Getenv("MINIE3_PROOF_DIR"); output != "" {
		if err := os.Mkdir(output, 0755); err != nil {
			t.Fatal("新規証拠先だけ", err)
		}
		proof := map[string]any{"成功": true, "場数": 54, "入口数": 302, "純評価数": 604, "No-u": 49, "u正益": 253, "結果": counts, "入力前後一致": true, "入力SHA256": inputs, "固定96純SHA256": FixedTechnicalGateSHA256, "金融/Source/Raw/新日/収支再生": 0, "限定": "既知54場の保存Context純式照合。新戦略成績や予測精度ではない。"}
		raw, _ := json.MarshalIndent(proof, "", "  ")
		if err := os.WriteFile(filepath.Join(output, "照合.json"), append(raw, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("302入口・604純評価: %+v", counts)
}
