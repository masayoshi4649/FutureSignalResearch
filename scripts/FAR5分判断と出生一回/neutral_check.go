package minigrid

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// protect94ProofSHA は全件検査を含め比較保存した94の正式指紋です。
// 95の市場実行前に固定し、別の基準へ黙って差替えません。
const protect94ProofSHA = "ccbc365b647c8225f5ef238f707778e9fbff01c5decba721c2843cb3f1972f80"

// NeutralMatch はN4口座の全既存金融fieldを固定94へ照合した出典です。
type NeutralMatch struct {
	BaselinePath        string          `json:"baseline_path"`
	BaselineSHA256      string          `json:"baseline_sha256"`
	BaselineProofSHA256 string          `json:"baseline_proof_sha256"`
	Books               map[string]bool `json:"books"`
	All                 bool            `json:"all"`
}

// normalizeNeutral は事前列挙した新診断fieldだけを除き、旧金融本文へ戻します。
//
// 引数: body([]byte)は95のN口座JSONです。
// 返り値: []byte/errorは残る全fieldの正規化本文、又は型の異常です。
func normalizeNeutral(body []byte) ([]byte, error) {
	var value map[string]any
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	for _, field := range []string{"entry_opportunities", "grid_traces", "grid_metrics"} {
		delete(value, field)
	}
	cfg, ok := value["config"].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("N比較のConfig型が不正")
	}
	delete(cfg, "entry_timing")
	delete(cfg, "us_open")
	return json.Marshal(value)
}

// compareNeutral は94保存指紋とN4口座の全既存金融fieldを比較します。
//
// 引数: folder/proofPath/session(string)、books(map[string]ActualResult)は固定94と今回口座です。
// 返り値: NeutralMatch/errorは全一致の出典、又は不一致です。
func compareNeutral(folder, proofPath, session string, books map[string]ActualResult) (NeutralMatch, error) {
	out := NeutralMatch{Books: map[string]bool{}}
	if len(protect94ProofSHA) != 64 {
		return out, fmt.Errorf("94比較保存の指紋が未固定です")
	}
	proofBody, err := os.ReadFile(proofPath)
	if err != nil {
		return out, err
	}
	digest := sha256.Sum256(proofBody)
	out.BaselineProofSHA256 = hex.EncodeToString(digest[:])
	if out.BaselineProofSHA256 != protect94ProofSHA {
		return out, fmt.Errorf("固定94完了記録の指紋差")
	}
	var proof struct {
		Trial int               `json:"試行"`
		Files map[string]string `json:"自己を除く正式指紋"`
	}
	if err = json.Unmarshal(proofBody, &proof); err != nil || proof.Trial != 94 {
		return out, fmt.Errorf("94完了記録の型/試行差:%v", err)
	}
	out.BaselinePath = filepath.Join(folder, session+".json.gz")
	body, err := os.ReadFile(out.BaselinePath)
	if err != nil {
		return out, err
	}
	digest = sha256.Sum256(body)
	out.BaselineSHA256 = hex.EncodeToString(digest[:])
	expected := proof.Files["成果物/"+session+".json.gz"]
	if expected == "" {
		expected = proof.Files["成果物\\"+session+".json.gz"]
	}
	if expected != out.BaselineSHA256 {
		return out, fmt.Errorf("94保存Nativeの指紋差")
	}
	stream, err := gzip.NewReader(bytes.NewReader(body))
	if err != nil {
		return out, err
	}
	defer stream.Close()
	var old struct {
		Session string                     `json:"session"`
		Books   map[string]json.RawMessage `json:"books"`
	}
	if err = json.NewDecoder(stream).Decode(&old); err != nil {
		return out, err
	}
	if old.Session != session {
		return out, fmt.Errorf("94場名差")
	}
	for _, cost := range []int{0, 5} {
		for _, delay := range []int{0, 1} {
			key := fmt.Sprintf("P0_C%d_D%d", cost, delay)
			current, ok := books[key]
			if !ok || len(old.Books[key]) == 0 {
				return out, fmt.Errorf("N対照の欠落:%s", key)
			}
			if current.Config.EntryTiming != "N" {
				return out, fmt.Errorf("N比較へ別時計が混入")
			}
			left, err := json.Marshal(current)
			if err != nil {
				return out, err
			}
			left, err = normalizeNeutral(left)
			if err != nil {
				return out, err
			}
			right, err := normalizeNeutral(old.Books[key])
			if err != nil {
				return out, err
			}
			out.Books[key] = bytes.Equal(left, right)
			if !out.Books[key] {
				return out, fmt.Errorf("Nと94の全既存金融fieldが不一致:%s", key)
			}
		}
	}
	out.All = len(out.Books) == 4
	return out, nil
}
