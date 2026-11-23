package lighttape97

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// TestSelectedGzipBoundaries は圧縮形式と固定許可集合の失敗境界を人工で検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。Native本文/Raw/CSVを読まず一時人工だけを使います。
func TestSelectedGzipBoundaries(t *testing.T) {
	folder := t.TempDir()
	path := filepath.Join(folder, "native.json.gz")
	for _, body := range []string{`{"session":"人工"}`, `{"session":"人工"}{}`, `not-json`} {
		file, err := os.Create(path)
		if err != nil {
			t.Fatal(err)
		}
		writer := gzip.NewWriter(file)
		if _, err = writer.Write([]byte(body)); err != nil {
			t.Fatal(err)
		}
		if err = writer.Close(); err != nil {
			t.Fatal(err)
		}
		file.Close()
		result, err := readGzipNative(path)
		if body == `{"session":"人工"}` {
			if err != nil || result.Session != "人工" {
				t.Fatal("gzip正常人工", err)
			}
		} else if err == nil {
			t.Fatal("余分/不正gzipを採用")
		}
	}
	if err := os.WriteFile(path, []byte(`{}`), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := readGzipNative(path); err == nil {
		t.Fatal("非gzipを採用")
	}
	if _, err := SelectedCatalog(path); err == nil {
		t.Fatal("改変完了記録を採用")
	}
}

// TestSelectedFirstTwo は追加許可された正式96の2gzipを旧入力へ結びます。
//
// 引数: t(*testing.T)、環境変数SELECTED97_EXPORT(string)は明示した証拠dirです。
// 返り値: ありません。既存Scalar入力だけを使いRaw再走査/H/他52場本文読取は行いません。
func TestSelectedFirstTwo(t *testing.T) {
	export := os.Getenv("SELECTED97_EXPORT")
	if export == "" {
		t.Skip("正式2gzipの読取は明示人工接続だけ")
	}
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	completion := filepath.Join(root, "study", "00096_5分枠の順行反転と現在数量", "完了記録.json")
	catalog, err := SelectedCatalog(completion)
	if err != nil {
		t.Fatal(err)
	}
	for _, label := range []string{"Day", "Night"} {
		skeleton := filepath.Join(root, "work", "97再生軽量化案", "実2場", label+"入力.json.gz")
		file, err := os.Open(skeleton)
		if err != nil {
			t.Fatal(err)
		}
		reader, err := gzip.NewReader(file)
		if err != nil {
			t.Fatal(err)
		}
		var input ProductionInput
		if err = json.NewDecoder(reader).Decode(&input); err != nil {
			t.Fatal(err)
		}
		reader.Close()
		file.Close()
		original, oldBase, err := BuildProduction(input)
		if err != nil {
			t.Fatal(err)
		}
		previousPath := input.NativePath
		input.NativePath = filepath.Join(filepath.Dir(completion), "成果物", input.Session.ID+".json.gz")
		input.NativeSHA = catalog[input.Session.ID]
		input.Evidence = map[string]string{input.NativePath: input.NativeSHA, completion: SelectedCompletionSHA256}
		selected, selectedBase, err := BuildSelectedProduction(input, completion)
		if err != nil {
			t.Fatal(err)
		}
		x, _ := json.Marshal(original.Events)
		y, _ := json.Marshal(selected.Events)
		if !bytes.Equal(x, y) || original.Session != selected.Session {
			t.Fatal("許可境界以外の入力値が変化")
		}
		books, err := Replay(selected)
		if err != nil {
			t.Fatal(err)
		}
		for _, baseline := range []actual.ReplayResult{oldBase, selectedBase} {
			if err = CompareEight(books, baseline); err != nil {
				t.Fatal(err)
			}
		}
		if err = os.MkdirAll(export, 0755); err != nil {
			t.Fatal(err)
		}
		proof := map[string]any{"成功": true, "session": input.Session.ID, "旧/新wrapperの入力Event全文同値": true, "Scope/Provenance": "許可範囲とgzip出典だけが相違", "旧2場/P0正式96への全文一致": 8, "除外": []string{}, "Raw/CSV再走査": 0, "他52場本文/H市場": 0, "completion_SHA256": SelectedCompletionSHA256, "旧Native": previousPath, "正式Native": input.NativePath, "正式Native_gzip_SHA256": input.NativeSHA}
		body, err := json.MarshalIndent(proof, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(export, label+"新経路の照合.json"), append(body, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
}
