package minichart

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
)

// Baseline95Match はG0四口座と旧95の同じB5Q全フィールドを照合した記録です。
type Baseline95Match struct {
	Path        string          `json:"path"`
	SHA256      string          `json:"sha256"`
	ProofSHA256 string          `json:"proof_sha256"`
	Keys        map[string]bool `json:"keys"`
	All         bool            `json:"all"`
}

// compareBaseline95 は除外フィールドなしで旧95の四口座全文へ比較します。
//
// 引数: folder/proof/session(string)は旧正本と対象、books(map)は新16口座です。
// 返り値: Baseline95Match/errorは指紋・配列順を含む一致又は不一致です。
func compareBaseline95(folder, proof, session string, books map[string]ActualResult) (Baseline95Match, error) {
	out := Baseline95Match{Keys: map[string]bool{}}
	proofBody, err := os.ReadFile(proof)
	if err != nil {
		return out, err
	}
	proofHash := sha256.Sum256(proofBody)
	out.ProofSHA256 = hex.EncodeToString(proofHash[:])
	if out.ProofSHA256 != "b7df0d9f793fca1ee9fbb489e045b927f8cf4b46e0e81a6c199920f128e4d943" {
		return out, fmt.Errorf("固定95完了指紋差")
	}
	var fixed struct {
		Files map[string]string `json:"自己を除く正式指紋"`
	}
	if err = json.Unmarshal(proofBody, &fixed); err != nil {
		return out, err
	}
	name := session + ".json.gz"
	out.Path = filepath.Join(folder, name)
	body, err := os.ReadFile(out.Path)
	if err != nil {
		return out, err
	}
	hash := sha256.Sum256(body)
	out.SHA256 = hex.EncodeToString(hash[:])
	if fixed.Files["成果物/"+name] != out.SHA256 {
		return out, fmt.Errorf("固定95圧縮指紋差")
	}
	stream, err := gzip.NewReader(bytes.NewReader(body))
	if err != nil {
		return out, err
	}
	defer stream.Close()
	var previous struct {
		Session string                     `json:"session"`
		Books   map[string]json.RawMessage `json:"books"`
	}
	if err = json.NewDecoder(stream).Decode(&previous); err != nil {
		return out, err
	}
	if previous.Session != session {
		return out, fmt.Errorf("固定95対象場差")
	}
	for _, slip := range []int{0, 5} {
		for _, delay := range []int{0, 1} {
			key := fmt.Sprintf("B5Q_P0_C%d_D%d", slip, delay)
			book, ok := books[key]
			if !ok {
				return out, fmt.Errorf("G0口座欠落")
			}
			current, err := json.Marshal(book)
			if err != nil {
				return out, err
			}
			old, ok := previous.Books[key]
			if !ok {
				return out, fmt.Errorf("固定95口座欠落")
			}
			var left, right any
			ld, rd := json.NewDecoder(bytes.NewReader(current)), json.NewDecoder(bytes.NewReader(old))
			ld.UseNumber()
			rd.UseNumber()
			if err = ld.Decode(&left); err != nil {
				return out, err
			}
			if err = rd.Decode(&right); err != nil {
				return out, err
			}
			out.Keys[key] = reflect.DeepEqual(left, right)
			if !out.Keys[key] {
				return out, fmt.Errorf("G0対95全文差: %s %s", session, key)
			}
		}
	}
	out.All = true
	return out, nil
}
