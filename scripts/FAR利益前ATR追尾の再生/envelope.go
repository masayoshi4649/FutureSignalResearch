package riskport98

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

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

const Fixed97CompletionSHA256 = "0d7111c41c4c25140be69fe8b06d0118496ddd6de3bc9ac7467ec2f01f6aef79"

// Envelope は固定入力の出典と新24口座の運転証拠を分けます。
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
	Input97Provenance map[string]any               `json:"input97_provenance"`
	TapeProvenance    map[string]any               `json:"tape_provenance"`
	SourceReexecuted  bool                         `json:"source_reexecuted"`
	ChartsRecomputed  bool                         `json:"charts_recomputed"`
	EmptyRisk97Match  map[string]any               `json:"empty_risk_97_match"`
	ActualRunComplete bool                         `json:"actual_run_complete"`
}

// Selected97Catalog は完成97の正式Native54場だけを宣言から選びます。
//
// 引数: proof(string)は固定97完了記録です。
// 返り値: map[string]string/errorは場ID/gzipSHA又は指紋・集合の不整合です。Native本文は読みません。
func Selected97Catalog(proof string) (map[string]string, error) {
	sha, err := tape.Digest(proof)
	if err != nil {
		return nil, err
	}
	if sha != Fixed97CompletionSHA256 {
		return nil, fmt.Errorf("固定97完了SHAが不一致")
	}
	body, err := os.ReadFile(proof)
	if err != nil {
		return nil, err
	}
	var value struct {
		Trial    int               `json:"試行"`
		Complete bool              `json:"比較保存完了"`
		Scenes   int               `json:"場数"`
		Files    map[string]string `json:"自己を除く正式指紋"`
	}
	if err = json.Unmarshal(body, &value); err != nil {
		return nil, err
	}
	if value.Trial != 97 || !value.Complete || value.Scenes != 54 {
		return nil, fmt.Errorf("正式97の54場完了が不明")
	}
	pattern := regexp.MustCompile(`^成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz$`)
	out := map[string]string{}
	for name, sha := range value.Files {
		matched := pattern.FindStringSubmatch(strings.ReplaceAll(name, "\\", "/"))
		if matched == nil {
			continue
		}
		if _, ok := out[matched[1]]; ok || len(sha) != 64 {
			return nil, fmt.Errorf("97Nativeの重複/指紋不正")
		}
		out[matched[1]] = sha
	}
	if len(out) != 54 {
		return nil, fmt.Errorf("正式97の54場許可集合が不足")
	}
	return out, nil
}

// ReadPrior97 は許可済み圧縮正本を一場だけ読みます。
//
// 引数: proof/session(string)は固定97完了と場IDです。
// 返り値: port.Envelope/string/string/errorは旧保存値と絶対path/SHA又は不整合です。
func ReadPrior97(proof, session string) (port.Envelope, string, string, error) {
	var value port.Envelope
	catalog, err := Selected97Catalog(proof)
	if err != nil {
		return value, "", "", err
	}
	expected, ok := catalog[session]
	if !ok {
		return value, "", "", fmt.Errorf("97許可集合に無い場")
	}
	path, err := filepath.Abs(filepath.Join(filepath.Dir(proof), "成果物", session+".json.gz"))
	if err != nil {
		return value, "", "", err
	}
	sha, err := tape.Digest(path)
	if err != nil {
		return value, "", "", err
	}
	if sha != expected {
		return value, "", "", fmt.Errorf("正式97Native gzipSHA差")
	}
	file, err := os.Open(path)
	if err != nil {
		return value, "", "", err
	}
	defer file.Close()
	reader, err := gzip.NewReader(file)
	if err != nil {
		return value, "", "", err
	}
	defer reader.Close()
	decoder := json.NewDecoder(reader)
	if err = decoder.Decode(&value); err != nil {
		return value, "", "", err
	}
	var extra any
	if err = decoder.Decode(&extra); err != io.EOF {
		return value, "", "", fmt.Errorf("正式97gzipに余分又は不正なJSON")
	}
	if value.Session != session || value.Version != 1 || len(value.Books) != 16 || !value.ActualRunComplete || value.SourceReexecuted || value.ChartsRecomputed {
		return value, "", "", fmt.Errorf("旧97envelopeのscope/完了が不明")
	}
	return value, path, sha, nil
}

// canonical は全JSON値を保持したまま表記順だけを揃えます。
//
// 引数: raw(json.RawMessage)は一口座の全JSONです。
// 返り値: []byte/errorはキー順/数値表記を正規化した全値又は不正JSONです。
func canonical(raw json.RawMessage) ([]byte, error) {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	return json.Marshal(value)
}

// CompareEmptyRisk97 は新24のうち空Risk八会計を正式97H0へ全field比較します。
//
// 引数: current/previous(map[string]json.RawMessage)は新24と旧保存H0/P0です。
// 返り値: []string/errorは一致したH0八key又は除外0の不一致です。旧P0へ対応させません。
func CompareEmptyRisk97(current, previous map[string]json.RawMessage) ([]string, error) {
	if len(current) != 24 {
		return nil, fmt.Errorf("新98は24会計が必要")
	}
	matched := []string{}
	for key, value := range current {
		if strings.HasPrefix(key, "R05_") || strings.HasPrefix(key, "R10_") {
			continue
		}
		if !strings.HasPrefix(key, "H0_") {
			return nil, fmt.Errorf("空riskを旧P0へ偽装してはいけません")
		}
		old, ok := previous[key]
		if !ok {
			return nil, fmt.Errorf("旧97H0基準keyがありません: %s", key)
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
			return nil, fmt.Errorf("空Riskの旧97H0全文差: %s", key)
		}
		matched = append(matched, key)
	}
	if len(matched) != 8 {
		return nil, fmt.Errorf("空Risk八会計の比較が不足")
	}
	sort.Strings(matched)
	return matched, nil
}

// BuildEnvelope は固定97H0の出典と対照を保ち、新24口座を運転します。
//
// 引数: input(tape.Tape)、proof97/proof96/tapePath/tapeSHA(string)は固定保存入力と証拠です。
// 返り値: Envelope/errorは新運転と空Risk八全文比較又は不整合です。
func BuildEnvelope(input tape.Tape, proof97, proof96, tapePath, tapeSHA string) (Envelope, error) {
	var out Envelope
	base, path, sha, err := ReadPrior97(proof97, input.Session.ID)
	if err != nil {
		return out, err
	}
	if got, err := tape.Digest(proof96); err != nil || got != tape.SelectedCompletionSHA256 {
		return out, fmt.Errorf("固定96完了SHAが不一致")
	}
	var savedSession map[string]any
	for key, book := range base.Books {
		if strings.HasPrefix(key, "H0_") {
			var row struct {
				Session json.RawMessage `json:"session"`
			}
			if err = json.Unmarshal(book, &row); err != nil {
				return out, err
			}
			if err = json.Unmarshal(row.Session, &savedSession); err != nil {
				return out, err
			}
			break
		}
	}
	currentSession, _ := json.Marshal(input.Session)
	previousSession, _ := json.Marshal(savedSession)
	a, _ := canonical(currentSession)
	b, _ := canonical(previousSession)
	if !bytes.Equal(a, b) {
		return out, fmt.Errorf("固定97とTapeの場時計が異なります")
	}
	if priorSHA, ok := base.Input96Provenance["tape_sha256"].(string); !ok || priorSHA != tapeSHA {
		return out, fmt.Errorf("固定97で使ったTapeと指紋が異なります")
	}
	contexts := []actual.TechnicalGateInput{}
	for _, e := range input.Events {
		if e.Kind == "grid" && e.Context != nil {
			contexts = append(contexts, *e.Context)
		}
	}
	if !reflect.DeepEqual(contexts, base.ChartGrids) {
		return out, fmt.Errorf("旧保存97のChartGrids全値が不一致")
	}
	result, records, err := ReplayRisk(input, false)
	if err != nil {
		return out, err
	}
	matched, err := CompareEmptyRisk97(result.Books, base.Books)
	if err != nil {
		return out, err
	}
	for _, value := range result.Books {
		var flags struct {
			Complete bool   `json:"complete"`
			Finished bool   `json:"finished"`
			Failure  string `json:"failure"`
		}
		if err = json.Unmarshal(value, &flags); err != nil {
			return out, err
		}
		if !flags.Complete || !flags.Finished || flags.Failure != "" {
			return out, fmt.Errorf("新98金融が未完")
		}
	}
	out = Envelope{Version: 1, Session: base.Session, Contract: base.Contract, Books: result.Books, ChartGrids: base.ChartGrids, GateAssessments: records, Shadows: base.Shadows, FeatureConfig: base.FeatureConfig, SourceRows: base.SourceRows, ChartEnd: base.ChartEnd, Quality: base.Quality, Input96Provenance: base.Input96Provenance, Input97Provenance: map[string]any{"native_path": path, "native_gzip_sha256": sha, "completion_sha256": Fixed97CompletionSHA256, "old_P0_96_match": base.P096Match, "old_actual_run_complete": base.ActualRunComplete, "scope": "旧97保存の出典/対照。新98の成功や新Source生成を示す欄ではない。"}, TapeProvenance: map[string]any{"path": tapePath, "sha256": tapeSHA, "capabilities": input.Capabilities, "scope": input.Scope, "source_input_provenance": "完成Tape.provenanceと固定構築証拠を参照。新Source/助走判断再実行0。"}, EmptyRisk97Match: map[string]any{"all": true, "books": 8, "keys": matched, "excluded": []string{}, "scope": "新98のRisk空/H0八会計を正式97H0と全field比較。旧P0ではない。"}, ActualRunComplete: true}
	return out, nil
}
