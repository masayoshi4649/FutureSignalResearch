package actorport97

import (
	"bytes"
	"encoding/json"
	"fmt"
	"path/filepath"
	"reflect"
	"sort"
	"strings"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// Envelope は保存96入力の出典と新金融の実運転を別の欄へ保持します。
type Envelope struct {
	Version           int                          `json:"version"`
	Session           string                       `json:"session"`
	Contract          string                       `json:"contract"`
	Books             map[string]json.RawMessage   `json:"books"`
	ChartGrids        []actual.TechnicalGateInput  `json:"chart_grids"`
	GateAssessments   []GateAssessmentRecord       `json:"gate_assessments"`
	Shadows           json.RawMessage              `json:"shadows"`
	FeatureConfig     json.RawMessage              `json:"feature_config"`
	SourceRows        map[string]int               `json:"source_rows"`
	ChartEnd          json.RawMessage              `json:"chart_end"`
	Quality           map[string]actual.RawQuality `json:"quality"`
	Input96Provenance map[string]any               `json:"input96_provenance"`
	SourceReexecuted  bool                         `json:"source_reexecuted"`
	ChartsRecomputed  bool                         `json:"charts_recomputed"`
	P096Match         map[string]any               `json:"P0_96_match"`
	ActualRunComplete bool                         `json:"actual_run_complete"`
}

// BuildEnvelope は固定圧縮正本から新97金融の16口座だけを運転します。
//
// 引数: input(tape.Tape)、baseline/completion/tapePath/tapeSHA(string)は明示した固定保存物です。
// 返り値: Envelope/errorは新結果と旧入力の出典。市場の実行はCLIの--run/条件指紋で別に固定します。
func BuildEnvelope(input tape.Tape, baseline, completion, tapePath, tapeSHA string) (Envelope, error) {
	var out Envelope
	path, err := filepath.Abs(baseline)
	if err != nil {
		return out, err
	}
	expected, exists := input.Provenance[path]
	if !exists {
		return out, fmt.Errorf("Tapeに固定96正本の出典がありません")
	}
	base, err := tape.ReadSelectedBaseline(completion, input.Session.ID, path, expected)
	if err != nil {
		return out, err
	}
	if input.Session != base.Books["B5Q_P0_C0_D0"].Session {
		return out, fmt.Errorf("Tapeと基準96の場時計が相違")
	}
	contexts := []actual.TechnicalGateInput{}
	for _, event := range input.Events {
		if event.Kind == "grid" && event.Context != nil {
			contexts = append(contexts, *event.Context)
		}
	}
	if !reflect.DeepEqual(contexts, base.ChartGrids) {
		return out, fmt.Errorf("保存96ChartGridsが全値で不一致")
	}
	records := []GateAssessmentRecord{}
	result, err := RunProduction(input, CapturedHarvest{Records: &records}, Configurations([]string{"", "H0"}))
	if err != nil {
		return out, err
	}
	if len(result.Books) != 16 {
		return out, fmt.Errorf("新金融は16会計が必要")
	}
	matched, complete := []string{}, true
	for key, value := range result.Books {
		var flags struct {
			Finished bool   `json:"finished"`
			Complete bool   `json:"complete"`
			Failure  string `json:"failure"`
		}
		if err = json.Unmarshal(value, &flags); err != nil {
			return out, err
		}
		complete = complete && flags.Finished && flags.Complete && flags.Failure == ""
		if strings.HasPrefix(key, "H0_") {
			continue
		}
		previous, exists := base.Books[key]
		if !exists {
			return out, fmt.Errorf("空97基準keyが旧96にありません")
		}
		expected, err := json.Marshal(previous)
		if err != nil {
			return out, err
		}
		if !bytes.Equal(expected, value) {
			return out, fmt.Errorf("空97と旧96の全文差: %s", key)
		}
		matched = append(matched, key)
	}
	if !complete || len(matched) != 8 {
		return out, fmt.Errorf("新金融の未完又は旧全文比較の不足")
	}
	sort.Strings(matched)
	shadows, err := json.Marshal(base.Shadows)
	if err != nil {
		return out, err
	}
	end, err := json.Marshal(base.ChartEnd)
	if err != nil {
		return out, err
	}
	out = Envelope{Version: 1, Session: base.Session, Contract: base.Contract, Books: result.Books, ChartGrids: base.ChartGrids, GateAssessments: records, Shadows: shadows, FeatureConfig: base.FeatureConfig, SourceRows: base.SourceRows, ChartEnd: end, Quality: base.Quality, Input96Provenance: map[string]any{"native_path": path, "native_gzip_sha256": expected, "completion_sha256": tape.SelectedCompletionSHA256, "old_shadow_match": base.ShadowMatch, "old_baseline95_match": base.NeutralMatch, "old_quality_scope": "保存96のloader採用/品質。97でSource又は助走を再運転した品質証明ではない", "tape_path": tapePath, "tape_sha256": tapeSHA, "input_scope": input.Scope}, P096Match: map[string]any{"all": true, "books": 8, "keys": matched, "excluded": []string{}, "scope": "同じ保存入力を空97で新規運転し、固定96G0/ABの全fieldと全文一致"}, ActualRunComplete: true}
	return out, nil
}
