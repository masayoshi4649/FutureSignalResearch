// 由来: scripts/FAR背景と勢いと数量の再生/envelope.go
// 由来SHA256: f3665da4d243e36e2896d0ef79c7b0f89d4c73b07645756067cd48fa1e862969
package grossport100

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

	prior99 "github.com/masayoshi4649/SessionTradeExecuter/entryport99"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	prior98 "github.com/masayoshi4649/SessionTradeExecuter/riskport98"
)

// Fixed99CompletionSHA256 は正式99完了の版を固定します。
const Fixed99CompletionSHA256 = "8c2a30e1073126038e2a6a9c370f945ac258164877be6a250afb1c683fbbf5c8"

// Fixed100FinancialStopSHA256 は停止金融へ結合するまで市場CLIを拒否します。
const Fixed100FinancialStopSHA256 = "717db3c18a154c4b016611ffebf0d37b8db35e67217372a57cdc9f07899f103c"

// Envelope は100新保護の結果と固定99入力の由来を分けます。
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
	Input99Provenance map[string]any               `json:"input99_provenance"`
	TapeProvenance    map[string]any               `json:"tape_provenance"`
	SourceReexecuted  bool                         `json:"source_reexecuted"`
	ChartsRecomputed  bool                         `json:"charts_recomputed"`
	H099Match         map[string]any               `json:"h0_99_match"`
	ActualRunComplete bool                         `json:"actual_run_complete"`
}

// validSHA は未設定又は不正な固定指紋を拒否するための純検査です。
//
// 引数: value(string)はSHA256候補です。
// 返り値: boolは小文字十六進64桁かどうかです。
func validSHA(value string) bool { return regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(value) }

// Selected99Catalog は固定完了99の正式Native54場だけを宣言から選びます。
//
// 引数: proof(string)は正式99完了記録です。
// 返り値: map[string]string/errorは場ID/gzipSHA又は未固定/完了不明です。市場本文は読みません。
func Selected99Catalog(proof string) (map[string]string, error) {
	if !validSHA(Fixed99CompletionSHA256) {
		return nil, fmt.Errorf("正式99完了SHAが未固定のため100市場運転は禁止です")
	}
	got, err := tape.Digest(proof)
	if err != nil {
		return nil, err
	}
	if got != Fixed99CompletionSHA256 {
		return nil, fmt.Errorf("固定99完了SHA差")
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
	if v.Trial != 99 || !v.Complete || v.Scenes != 54 {
		return nil, fmt.Errorf("正式99の54場完了が不明")
	}
	pattern := regexp.MustCompile(`^成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz$`)
	out := map[string]string{}
	for name, sha := range v.Files {
		m := pattern.FindStringSubmatch(strings.ReplaceAll(name, "\\", "/"))
		if m == nil {
			continue
		}
		if _, ok := out[m[1]]; ok || !validSHA(sha) {
			return nil, fmt.Errorf("99Nativeの重複又はSHA不正")
		}
		out[m[1]] = sha
	}
	if len(out) != 54 {
		return nil, fmt.Errorf("99の許可54集合不足")
	}
	return out, nil
}

// ReadPrior99 は固定99の正式gzip一場だけを全値読取します。
//
// 引数: proof/session(string)は固定完了と許可場IDです。
// 返り値: prior99.Envelope/string/string/errorは旧保存・絶対path・SHA又は不整合です。
func ReadPrior99(proof, session string) (prior99.Envelope, string, string, error) {
	var out prior99.Envelope
	catalog, err := Selected99Catalog(proof)
	if err != nil {
		return out, "", "", err
	}
	expected, ok := catalog[session]
	if !ok {
		return out, "", "", fmt.Errorf("99許可集合にない場")
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
		return out, "", "", fmt.Errorf("99Native gzipSHA差")
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
		return out, "", "", fmt.Errorf("99gzipの余分又は不正JSON")
	}
	if out.Trial != 99 || out.Version != 1 || out.Session != session || len(out.Books) != 12 || !out.ActualRunComplete || out.SourceReexecuted || out.ChartsRecomputed {
		return out, "", "", fmt.Errorf("旧99の12/完了/再実行範囲が不明")
	}
	return out, path, got, nil
}

// CompareH099 は新12のH0/E3S四会計を固定99E3S/H0へ除外0比較します。
//
// 引数: current/previous(map[string]json.RawMessage)は新12と実在旧基準です。
// 返り値: []string/errorは一致した四Key又は全field差です。疑似基準は補完しません。
func CompareH099(current, previous map[string]json.RawMessage) ([]string, error) {
	if len(current) != 12 {
		return nil, fmt.Errorf("100は12会計が必要")
	}
	matched := []string{}
	for _, key := range Keys() {
		value, exists := current[key]
		if !exists {
			return nil, fmt.Errorf("100Key不足")
		}
		if !strings.HasPrefix(key, "H0_") {
			continue
		}
		old, ok := previous[key]
		if !ok {
			return nil, fmt.Errorf("H0の固定99E3S基準Keyがない:%s", key)
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
			return nil, fmt.Errorf("H0旧99E3S全文差:%s", key)
		}
		matched = append(matched, key)
	}
	if len(matched) != 4 {
		return nil, fmt.Errorf("H0四比較不足")
	}
	sort.Strings(matched)
	return matched, nil
}

// BuildEnvelope は固定99の由来とH0対照を保ち新12口座を運転します。
//
// 引数: input(tape.Tape)、proof99/proof98/proof97/proof96/tapePath/tapeSHA(string)は固定保存入力です。
// 返り値: Envelope/errorは新運転と四対照又は不整合です。呼出元CLIは未固定100を拒否します。
func BuildEnvelope(input tape.Tape, proof99, proof98, proof97, proof96, tapePath, tapeSHA string) (Envelope, error) {
	var out Envelope
	base, path, sha, err := ReadPrior99(proof99, input.Session.ID)
	if err != nil {
		return out, err
	}
	if got, e := tape.Digest(proof98); e != nil || got != prior99.Fixed98CompletionSHA256 {
		return out, fmt.Errorf("固定98完了SHA差")
	}
	if got, e := tape.Digest(proof97); e != nil || got != prior98.Fixed97CompletionSHA256 {
		return out, fmt.Errorf("固定97完了SHA差")
	}
	if got, e := tape.Digest(proof96); e != nil || got != tape.SelectedCompletionSHA256 {
		return out, fmt.Errorf("固定96完了SHA差")
	}
	var savedSession json.RawMessage
	for _, key := range Keys() {
		if strings.HasPrefix(key, "H0_E3S_") {
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
		return out, fmt.Errorf("固定99とTapeの場時計差")
	}
	if oldSHA, ok := base.TapeProvenance["sha256"].(string); !ok || oldSHA != tapeSHA {
		return out, fmt.Errorf("固定99で使ったTapeとSHA差")
	}
	contexts := []actual.TechnicalGateInput{}
	for _, event := range input.Events {
		if event.Kind == "grid" && event.Context != nil {
			contexts = append(contexts, *event.Context)
		}
	}
	if !reflect.DeepEqual(contexts, base.ChartGrids) {
		return out, fmt.Errorf("固定99とChartGrids全文差")
	}
	result, records, err := ReplayProtection(input, false)
	if err != nil {
		return out, err
	}
	matched, err := CompareH099(result.Books, base.Books)
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
			return out, fmt.Errorf("新100金融が未完")
		}
	}
	out = Envelope{Trial: 100, Version: 1, Session: base.Session, Contract: base.Contract, Books: result.Books, ChartGrids: base.ChartGrids, GateAssessments: records, Shadows: base.Shadows, FeatureConfig: base.FeatureConfig, SourceRows: base.SourceRows, ChartEnd: base.ChartEnd, Quality: base.Quality, Input96Provenance: base.Input96Provenance, Input97Provenance: base.Input97Provenance,
		Input98Provenance: base.Input98Provenance,
		Input99Provenance: map[string]any{"native_path": path, "native_gzip_sha256": sha, "completion_sha256": Fixed99CompletionSHA256, "old_empty_gate_98_match": base.EmptyGate98Match, "old_actual_run_complete": base.ActualRunComplete, "scope": "旧99の保存由来と空Gate対98の過去対照。新100の成功やH0対照を表さない。"},
		TapeProvenance:    map[string]any{"path": tapePath, "sha256": tapeSHA, "capabilities": input.Capabilities, "scope": input.Scope, "source_input_provenance": "完成Tapeと固定96/97/98/99構築証拠へ参照。新Source/助走判断再実行0。"},
		H099Match:         map[string]any{"all": true, "books": 4, "keys": matched, "excluded": []string{}, "scope": "新100のH0/E3S四会計を正式99E3S/H0へ全field比較。旧99のG0/E3や旧依存対照を新成功へ転用しない。"}, ActualRunComplete: true}

	return out, nil
}
