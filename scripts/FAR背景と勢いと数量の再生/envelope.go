package entryport99

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strings"

	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	prior98 "github.com/masayoshi4649/SessionTradeExecuter/riskport98"
)

// Fixed98CompletionSHA256 は正式98完了を固定し、異なる入力や未固定99条件を拒否します。
const Fixed98CompletionSHA256 = "2ee9417d0cd1f8bef107712789d26e3f72c0f95a933e60b31bb3f11784ca0dfe"

// Envelope は99新入口の結果と固定98入力の由来を分けます。
type Envelope struct {
	Trial             int                          `json:"trial"`
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
	Input97Provenance map[string]any               `json:"input97_provenance"`
	Input98Provenance map[string]any               `json:"input98_provenance"`
	TapeProvenance    map[string]any               `json:"tape_provenance"`
	SourceReexecuted  bool                         `json:"source_reexecuted"`
	ChartsRecomputed  bool                         `json:"charts_recomputed"`
	EmptyGate98Match  map[string]any               `json:"empty_gate_98_match"`
	ActualRunComplete bool                         `json:"actual_run_complete"`
}

// validSHA は未設定又は不正な固定指紋を拒否するための純検査です。
//
// 引数: value(string)はSHA256候補です。
// 返り値: boolは小文字十六進64桁かどうかです。
func validSHA(value string) bool { return regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(value) }

// Selected98Catalog は固定完了98の正式Native54場だけを宣言から選びます。
//
// 引数: proof(string)は正式98完了記録です。
// 返り値: map[string]string/errorは場ID/gzipSHA又は未固定/完了不明です。市場本文は読みません。
func Selected98Catalog(proof string) (map[string]string, error) {
	if !validSHA(Fixed98CompletionSHA256) {
		return nil, fmt.Errorf("正式98完了SHAが未固定のため99市場運転は禁止です")
	}
	got, err := tape.Digest(proof)
	if err != nil {
		return nil, err
	}
	if got != Fixed98CompletionSHA256 {
		return nil, fmt.Errorf("固定98完了SHA差")
	}
	body, err := os.ReadFile(proof)
	if err != nil {
		return nil, err
	}
	var v struct {
		Trial    int               `json:"試行"`
		Complete bool              `json:"比較保存完了"`
		Scenes   int               `json:"場数"`
		Files    map[string]string `json:"自己を除く正式指紋"`
	}
	if err = json.Unmarshal(body, &v); err != nil {
		return nil, err
	}
	if v.Trial != 98 || !v.Complete || v.Scenes != 54 {
		return nil, fmt.Errorf("正式98の54場完了が不明")
	}
	pattern := regexp.MustCompile(`^成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz$`)
	out := map[string]string{}
	for name, sha := range v.Files {
		m := pattern.FindStringSubmatch(strings.ReplaceAll(name, "\\", "/"))
		if m == nil {
			continue
		}
		if _, ok := out[m[1]]; ok || !validSHA(sha) {
			return nil, fmt.Errorf("98Nativeの重複又はSHA不正")
		}
		out[m[1]] = sha
	}
	if len(out) != 54 {
		return nil, fmt.Errorf("98の許可54集合不足")
	}
	return out, nil
}

// ReadPrior98 は固定98の正式gzip一場だけを全値読取します。
//
// 引数: proof/session(string)は固定完了と許可場IDです。
// 返り値: prior98.Envelope/string/string/errorは旧保存・絶対path・SHA又は不整合です。
func ReadPrior98(proof, session string) (prior98.Envelope, string, string, error) {
	var out prior98.Envelope
	catalog, err := Selected98Catalog(proof)
	if err != nil {
		return out, "", "", err
	}
	expected, ok := catalog[session]
	if !ok {
		return out, "", "", fmt.Errorf("98許可集合にない場")
	}
	path, err := filepath.Abs(filepath.Join(filepath.Dir(proof), "成果物", session+".json.gz"))
	if err != nil {
		return out, "", "", err
	}
	got, err := tape.Digest(path)
	if err != nil {
		return out, "", "", err
	}
	if got != expected {
		return out, "", "", fmt.Errorf("98Native gzipSHA差")
	}
	f, err := os.Open(path)
	if err != nil {
		return out, "", "", err
	}
	defer f.Close()
	r, err := gzip.NewReader(f)
	if err != nil {
		return out, "", "", err
	}
	defer r.Close()
	d := json.NewDecoder(r)
	if err = d.Decode(&out); err != nil {
		return out, "", "", err
	}
	var extra any
	if err = d.Decode(&extra); err != io.EOF {
		return out, "", "", fmt.Errorf("98gzipの余分又は不正JSON")
	}
	if out.Version != 1 || out.Session != session || len(out.Books) != 24 || !out.ActualRunComplete || out.SourceReexecuted || out.ChartsRecomputed {
		return out, "", "", fmt.Errorf("旧98の24/完了/再実行範囲が不明")
	}
	return out, path, got, nil
}

// CompareEmptyGate98 は新12の空Gate四会計を固定98H0/G0へ除外0比較します。
//
// 引数: current/previous(map[string]json.RawMessage)は新12と実在旧基準です。
// 返り値: []string/errorは一致した四Key又は全field差です。疑似基準は補完しません。
func CompareEmptyGate98(current, previous map[string]json.RawMessage) ([]string, error) {
	if len(current) != 12 {
		return nil, fmt.Errorf("99は12会計が必要")
	}
	matched := []string{}
	for _, key := range Keys() {
		value, exists := current[key]
		if !exists {
			return nil, fmt.Errorf("99Key不足")
		}
		if strings.HasPrefix(key, "H0_E3_") || strings.HasPrefix(key, "H0_E3S_") {
			continue
		}
		old, ok := previous[key]
		if !ok {
			return nil, fmt.Errorf("空Gateの固定98H0基準Keyがない:%s", key)
		}
		a, err := canonical(value)
		if err != nil {
			return nil, err
		}
		b, err := canonical(old)
		if err != nil {
			return nil, err
		}
		if !bytes.Equal(a, b) {
			return nil, fmt.Errorf("空Gate旧98H0全文差:%s", key)
		}
		matched = append(matched, key)
	}
	if len(matched) != 4 {
		return nil, fmt.Errorf("空Gate四比較不足")
	}
	sort.Strings(matched)
	return matched, nil
}

// BuildEnvelope は固定98の由来と空Gate対照を保ち新12口座を運転します。
//
// 引数: input(tape.Tape)、proof98/proof97/proof96/tapePath/tapeSHA(string)は固定保存入力です。
// 返り値: Envelope/errorは新運転と四対照又は不整合です。未固定98は必ず拒否します。
func BuildEnvelope(input tape.Tape, proof98, proof97, proof96, tapePath, tapeSHA string) (Envelope, error) {
	var out Envelope
	base, path, sha, err := ReadPrior98(proof98, input.Session.ID)
	if err != nil {
		return out, err
	}
	if got, e := tape.Digest(proof97); e != nil || got != prior98.Fixed97CompletionSHA256 {
		return out, fmt.Errorf("固定97完了SHA差")
	}
	if got, e := tape.Digest(proof96); e != nil || got != tape.SelectedCompletionSHA256 {
		return out, fmt.Errorf("固定96完了SHA差")
	}
	var savedSession json.RawMessage
	for _, key := range Keys() {
		if strings.HasPrefix(key, "H0_B5Q_") {
			var r struct {
				Session json.RawMessage `json:"session"`
			}
			if err = json.Unmarshal(base.Books[key], &r); err != nil {
				return out, err
			}
			savedSession = r.Session
			break
		}
	}
	currentSession, _ := json.Marshal(input.Session)
	a, e := canonical(currentSession)
	if e != nil {
		return out, e
	}
	b, e := canonical(savedSession)
	if e != nil {
		return out, e
	}
	if !bytes.Equal(a, b) {
		return out, fmt.Errorf("固定98とTapeの場時計差")
	}
	if oldSHA, ok := base.TapeProvenance["sha256"].(string); !ok || oldSHA != tapeSHA {
		return out, fmt.Errorf("固定98で使ったTapeとSHA差")
	}
	contexts := []actual.TechnicalGateInput{}
	for _, event := range input.Events {
		if event.Kind == "grid" && event.Context != nil {
			contexts = append(contexts, *event.Context)
		}
	}
	if !reflect.DeepEqual(contexts, base.ChartGrids) {
		return out, fmt.Errorf("固定98とChartGrids全文差")
	}
	result, records, err := ReplayEntry(input, false)
	if err != nil {
		return out, err
	}
	matched, err := CompareEmptyGate98(result.Books, base.Books)
	if err != nil {
		return out, err
	}
	for _, body := range result.Books {
		var f struct {
			Complete bool   `json:"complete"`
			Finished bool   `json:"finished"`
			Failure  string `json:"failure"`
		}
		if err = json.Unmarshal(body, &f); err != nil {
			return out, err
		}
		if !f.Complete || !f.Finished || f.Failure != "" {
			return out, fmt.Errorf("新99金融が未完")
		}
	}
	out = Envelope{Trial: 99, Version: 1, Session: base.Session, Contract: base.Contract, Books: result.Books, ChartGrids: base.ChartGrids, GateAssessments: records, Shadows: base.Shadows, FeatureConfig: base.FeatureConfig, SourceRows: base.SourceRows, ChartEnd: base.ChartEnd, Quality: base.Quality, Input96Provenance: base.Input96Provenance, Input97Provenance: base.Input97Provenance,
		Input98Provenance: map[string]any{"native_path": path, "native_gzip_sha256": sha, "completion_sha256": Fixed98CompletionSHA256, "old_empty_risk_97_match": base.EmptyRisk97Match, "old_actual_run_complete": base.ActualRunComplete, "scope": "旧98保存の入力由来と旧対照。新99の成功や新Source/指標形成を表さない。"},
		TapeProvenance:    map[string]any{"path": tapePath, "sha256": tapeSHA, "capabilities": input.Capabilities, "scope": input.Scope, "source_input_provenance": "完成Tapeと固定96/97/98構築証拠へ参照。新Source/助走判断再実行0。"},
		EmptyGate98Match:  map[string]any{"all": true, "books": 4, "keys": matched, "excluded": []string{}, "scope": "新99の空Gate/G0・H0四会計を正式98の空Risk/G0/H0へ全field比較。E3の採否や旧ABを対照に転用しない。"}, ActualRunComplete: true}
	return out, nil
}
