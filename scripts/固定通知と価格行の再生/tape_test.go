package lighttape97

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestFixed96GoFixtures は元の全Observationから抜いたTapeで8Bookを除外0比較します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。固定Go型人工だけで、H・新市場損益は実行しません。
func TestFixed96GoFixtures(t *testing.T) {
	paths, err := filepath.Glob(filepath.Join("..", "..", "work", "96結合人工", "初回", "*_*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 6 {
		t.Fatalf("固定Go人工6sceneが必要: %d", len(paths))
	}
	for _, path := range paths {
		t.Run(filepath.Base(path), func(t *testing.T) {
			f, err := LoadFixture(path)
			if err != nil {
				t.Fatal(err)
			}
			tape, err := FixtureTape(f)
			if err != nil {
				t.Fatal(err)
			}
			before, _ := json.Marshal(tape)
			books, err := Replay(tape)
			if err != nil {
				t.Fatal(err)
			}
			after, _ := json.Marshal(tape)
			if string(before) != string(after) {
				t.Fatal("再生が共有Tapeを更新")
			}
			if len(books) != 8 {
				t.Fatal("G0/AB×4の八口座が必要")
			}
			for key, b := range books {
				if !(strings.HasPrefix(key, "B5Q_") || strings.HasPrefix(key, "AB_")) {
					t.Fatal("新政策を混入")
				}
				want, ok := f.Actors[key]
				if !ok {
					t.Fatal("元96の対象bookなし")
				}
				x, _ := json.Marshal(b)
				y, _ := json.Marshal(want)
				if string(x) != string(y) {
					t.Fatalf("元96全Book相違: %s", key)
				}
			}
			// ----------------------------------------
			// 同Tapeの二回目でもSource/金融のprivate状態を共有しません。
			again, err := Replay(tape)
			if err != nil {
				t.Fatal(err)
			}
			x, _ := json.Marshal(books)
			y, _ := json.Marshal(again)
			if string(x) != string(y) {
				t.Fatal("同Tapeの独立再生が相違")
			}
			if folder := os.Getenv("TAPE97_EXPORT"); folder != "" {
				if err = os.MkdirAll(folder, 0755); err != nil {
					t.Fatal(err)
				}
				out := filepath.Join(folder, filepath.Base(path))
				if err = os.WriteFile(out, before, 0644); err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}

// TestTapeRejectsUnsupportedInput は未計算の特徴を版なしで流用しません。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。互換外のcapabilityは金融を開始する前に拒否します。
func TestTapeRejectsUnsupportedInput(t *testing.T) {
	for _, caps := range [][]string{nil, {"将来の未計算特徴"}, {"source93.public_notifications.v1"}} {
		if _, err := Replay(Tape{Version: 1, Scope: "人工", Capabilities: caps}); err == nil {
			t.Fatal("未対応の入力契約を受理")
		}
	}
}
