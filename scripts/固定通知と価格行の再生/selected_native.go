package lighttape97

import (
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// SelectedCompletionSHA256 は既使用54場を固定した正式96完了記録です。
const SelectedCompletionSHA256 = "33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483"

// SelectedCatalog は完成記録のうちNative許可集合だけを返します。
//
// 引数: completion(string)は固定96完了記録の明示パスです。
// 返り値: map[string]string/errorは場IDとgzipSHA256又は完了/集合の不整合です。
func SelectedCatalog(completion string) (map[string]string, error) {
	digest, err := Digest(completion)
	if err != nil {
		return nil, err
	}
	if digest != SelectedCompletionSHA256 {
		return nil, fmt.Errorf("固定96完了記録のSHA差")
	}
	body, err := os.ReadFile(completion)
	if err != nil {
		return nil, err
	}
	var record struct {
		Complete bool              `json:"比較保存完了"`
		Scenes   int               `json:"場数"`
		Files    map[string]string `json:"自己を除く正式指紋"`
	}
	if err = json.Unmarshal(body, &record); err != nil {
		return nil, err
	}
	if !record.Complete || record.Scenes != 54 {
		return nil, fmt.Errorf("96の54場完了が不明")
	}
	pattern := regexp.MustCompile(`^成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz$`)
	out := map[string]string{}
	for path, sha := range record.Files {
		matched := pattern.FindStringSubmatch(strings.ReplaceAll(path, "\\", "/"))
		if matched == nil {
			continue
		}
		if len(sha) != 64 {
			return nil, fmt.Errorf("Nativeの指紋長不正")
		}
		if _, exists := out[matched[1]]; exists {
			return nil, fmt.Errorf("Native許可集合が重複")
		}
		out[matched[1]] = sha
	}
	if len(out) != 54 {
		return nil, fmt.Errorf("固定Native許可集合は54場が必要")
	}
	return out, nil
}

// ValidateSelectedNative は許可集合・正本配置・gzip指紋を束縛します。
//
// 引数: completion/session/path/sha(string)は固定完了記録と要求された場/圧縮Nativeです。
// 返り値: errorは対象外/別配置/指紋差です。54場の本文をまとめて読むことはありません。
func ValidateSelectedNative(completion, session, path, sha string) error {
	catalog, err := SelectedCatalog(completion)
	if err != nil {
		return err
	}
	expected, known := catalog[session]
	if !known || sha != expected {
		return fmt.Errorf("対象外場又はNative指紋の不一致")
	}
	actualPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	requiredPath, err := filepath.Abs(filepath.Join(filepath.Dir(completion), "成果物", session+".json.gz"))
	if err != nil {
		return err
	}
	if filepath.Clean(actualPath) != filepath.Clean(requiredPath) {
		return fmt.Errorf("固定96正式Native配置と異なります")
	}
	digest, err := Digest(path)
	if err != nil {
		return err
	}
	if digest != expected {
		return fmt.Errorf("固定96 gzipのSHA差")
	}
	return nil
}

// ReadSelectedBaseline は新wrapperの旧比較元を公開します。
//
// 引数: completion/session/path/sha(string)は固定記録と場/圧縮Native/期待指紋です。
// 返り値: actual.ReplayResult/errorは保存96の全値又は出典不整合です。Source判断は再運転しません。
func ReadSelectedBaseline(completion, session, path, sha string) (actual.ReplayResult, error) {
	if err := ValidateSelectedNative(completion, session, path, sha); err != nil {
		return actual.ReplayResult{}, err
	}
	return readGzipNative(path)
}

// readGzipNative は新しい経路で圧縮正本を厳密に一つだけ読みます。
//
// 引数: path(string)は検証済みのgzip Nativeパスです。
// 返り値: actual.ReplayResult/errorは旧計算へ渡す全値又は形式不整合です。
func readGzipNative(path string) (actual.ReplayResult, error) {
	var value actual.ReplayResult
	file, err := os.Open(path)
	if err != nil {
		return value, err
	}
	defer file.Close()
	stream, err := gzip.NewReader(file)
	if err != nil {
		return value, err
	}
	defer stream.Close()
	decoder := json.NewDecoder(stream)
	if err = decoder.Decode(&value); err != nil {
		return value, err
	}
	var extra any
	if err = decoder.Decode(&extra); err != io.EOF {
		return value, fmt.Errorf("gzip Nativeに余分又は不正なJSONがあります: %v", err)
	}
	return value, nil
}
