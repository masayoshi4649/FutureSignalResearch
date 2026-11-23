// 91接続人工派生元: scripts/FAR押戻し確定終値の固定床/export_test.go
// 91派生元SHA256: 2b290956aa5318df48a6966c2f6349dabbc2267a3c27bc5f089b67dd0b8b8947
// 90派生元: scripts/FAR利益床と収穫配分の比較/export_test.go
// 90派生元SHA256: 18e9a11f3c44a3584109ca01384f9dddb2eddc2cfbc96befc1fe501eee5c92a3
package far91

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
)

// export91JSON は非有限値と上書きを拒否して合成人工を保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・新規先・保存値です。
// 返り値: ありません。実市場や固定旧結果は読みません。
func export91JSON(t *testing.T, path string, value any) {
	t.Helper()
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(append(b, '\n')); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
}

// TestExport91Natural は自然Source合成3場と独立旧89を新規出力します。
//
// 引数: t(*testing.T)、環境変数FAR91_NATURAL_EXPORTは専用保存先です。
// 返り値: ありません。E1非0の証明は実指標手製Sourceへ分けます。
func TestExport91Natural(t *testing.T) {
	out := os.Getenv("FAR91_NATURAL_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if err := os.Mkdir(out, 0700); err != nil {
		t.Fatal(err)
	}
	manifest := input91MultiFixture(t, false)
	oldRoot := manifest.Root
	inputRoot := filepath.Join(out, "入力")
	if err := os.Mkdir(inputRoot, 0700); err != nil {
		t.Fatal(err)
	}
	for _, input := range manifest.Sessions {
		for _, f := range input.Files {
			p := filepath.Join(inputRoot, filepath.FromSlash(f.Path))
			if err := os.MkdirAll(filepath.Dir(p), 0700); err != nil {
				t.Fatal(err)
			}
			b, err := os.ReadFile(filepath.Join(oldRoot, filepath.FromSlash(f.Path)))
			if err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(p, b, 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	for name := range manifest.StrategySHA256 {
		b, err := os.ReadFile(filepath.Join(oldRoot, name))
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(inputRoot, name), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	manifest.Root, manifest.StrategyRoot = inputRoot, inputRoot
	export91JSON(t, filepath.Join(out, "manifest.json"), manifest)
	seeds, err := far80.PrepareTechnicalSeeds(manifest)
	if err != nil {
		t.Fatal(err)
	}
	for _, input := range manifest.Sessions {
		dir := filepath.Join(out, input.ID)
		if err = os.Mkdir(dir, 0700); err != nil {
			t.Fatal(err)
		}
		seed, oldSeed := seeds[input.ID], seeds[input.ID]
		got, err := Replay(inputRoot, input, &seed)
		if err != nil {
			t.Fatal(err)
		}
		old, err := far89.Replay(inputRoot, input, &oldSeed)
		if err != nil {
			t.Fatal(err)
		}
		compare91Legacy89(t, got, old)
		export91JSON(t, filepath.Join(dir, "91.json"), got)
		export91JSON(t, filepath.Join(dir, "89.json"), old)
		session, err := sessionClock(input.ID)
		if err != nil {
			t.Fatal(err)
		}
		boards, _, err := readBoards(filepath.Join(inputRoot, filepath.FromSlash(input.Files["NK225_book"].Path)), "NK225", session)
		if err != nil {
			t.Fatal(err)
		}
		rows := []any{}
		featureIndex := int64(-1)
		for i, row := range boards {
			if row.Board.Last > 0 {
				featureIndex++
			}
			q := Quote{Time: row.Board.Time, Index: int64(i), Line: row.Line, Last: row.Board.Last, Bid: row.Board.Bid, Ask: row.Board.Ask, Valid: row.Board.Last > 0 && row.Board.Bid > 0 && row.Board.Ask > row.Board.Bid}
			rows = append(rows, map[string]any{"quote": q, "accepted": true, "clock_missing": false, "feature_index": featureIndex})
		}
		export91JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export91JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "合成原板・実Features/TechnicalBank・自然Source・独立far89.ReplayとのG1/共有E1射影同値", "input": input, "seed_view": got.SeedView, "注意": "E1だけを残した宣言射影以外は同値。実E1機会/再参加非0は別人工であり、市場性能の証明ではない。"})
	}
}

// TestExport91Indicator は実指標/原板整合/手製Sourceの初参加/再参加の4会計非0を保存します。
//
// 引数: t(*testing.T)、環境変数FAR91_INDICATOR_EXPORTは専用保存先です。
// 返り値: ありません。旧89対照は固定金融API2会計に限定します。
func TestExport91Indicator(t *testing.T) {
	out := os.Getenv("FAR91_INDICATOR_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if err := os.Mkdir(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		for _, repeat := range []bool{false, true} {
			kind := "初参加"
			if repeat {
				kind = "再参加"
			}
			dir := filepath.Join(out, fmt.Sprintf("実指標_%s_%+d", kind, side))
			if err := os.Mkdir(dir, 0700); err != nil {
				t.Fatal(err)
			}
			r, quotes, seed := runIndicator91Case(t, side, repeat)
			old := indicator91G1Baseline(t, r, quotes, side)
			rows := []any{}
			boards := []map[string]any{}
			for _, q := range quotes {
				rows = append(rows, map[string]any{"quote": q, "accepted": true, "clock_missing": false, "feature_index": q.Index})
				row := map[string]any{"Symbol": "人工限月", "CurrentPriceTime": input91Stamp(q.Time), "CurrentPrice": q.Last}
				for n := 1; n <= 10; n++ {
					row[fmt.Sprintf("Buy%d", n)] = map[string]float64{"Price": q.Bid - float64(n-1)*10, "Qty": 100}
					row[fmt.Sprintf("Sell%d", n)] = map[string]float64{"Price": q.Ask + float64(n-1)*10, "Qty": 100}
				}
				boards = append(boards, row)
			}
			bookFile := input91Gzip(t, dir, "NK225.jsonl.gz", boards)
			r.result.Quality["NK225"] = RawQuality{Lines: int64(len(quotes)), Accepted: int64(len(quotes)), Contracts: []string{"人工限月"}}
			export91JSON(t, filepath.Join(dir, "91.json"), r.result)
			export91JSON(t, filepath.Join(dir, "89.json"), map[string]any{"session": r.session.ID, "books": old})
			export91JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
			export91JSON(t, filepath.Join(dir, "manifest.json"), InputManifest{Root: dir, Sessions: []InputSession{{ID: r.session.ID, Contract: "人工限月", Files: map[string]InputFile{"NK225_book": bookFile}}}})
			export91JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "実固定TechnicalBank・合成8時間種/当場原板・手製Source・4会計非0", "旧89E1G1対照": "固定89金融へ同じ2入口供給を旧時計で渡したAPI限定対照。far89.ReplayへのSource注入ではない。", "未計測": "元FAR自然Source/SourceEquivalenceは0空のまま。旧対照の未測定sharedは補完しない。", "Current": "当時特徴未供給のためnil。原板足/旗の出典を検証する。", "seed_view": seed, "非0会計数": 4, "実参加機会数": len(r.result.EntryOpportunities), "再参加人工": repeat})
		}
	}
}
