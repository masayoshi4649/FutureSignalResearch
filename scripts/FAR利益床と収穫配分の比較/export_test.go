package far89

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far88 "github.com/masayoshi4649/SessionTradeExecuter/research88"
)

// export89JSON は非有限値と上書きを拒否して合成人工を保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・新規先・保存値です。
// 返り値: ありません。実市場や固定旧結果は読みません。
func export89JSON(t *testing.T, path string, value any) {
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

// TestExport89Natural は自然Source合成3場と独立旧88を新規出力します。
//
// 引数: t(*testing.T)、環境変数FAR89_NATURAL_EXPORTは専用保存先です。
// 返り値: ありません。E0/E1非0の証明は実指標手製Sourceへ分けます。
func TestExport89Natural(t *testing.T) {
	out := os.Getenv("FAR89_NATURAL_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if err := os.Mkdir(out, 0700); err != nil {
		t.Fatal(err)
	}
	manifest := input89MultiFixture(t, false)
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
	export89JSON(t, filepath.Join(out, "manifest.json"), manifest)
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
		old, err := far88.Replay(inputRoot, input, &oldSeed)
		if err != nil {
			t.Fatal(err)
		}
		compare89Legacy88(t, got, old)
		export89JSON(t, filepath.Join(dir, "89.json"), got)
		export89JSON(t, filepath.Join(dir, "88.json"), old)
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
		export89JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export89JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "合成原板・実Features/TechnicalBank・自然Source・独立far88.ReplayとのG1/全shared同値", "input": input, "seed_view": got.SeedView, "注意": "S政策を外した宣言射影以外は同値。自然E0/E1非0は別人工であり、市場性能の証明ではない。"})
	}
}

// TestExport89Indicator は実指標/原板整合/手製Sourceの8会計非0を保存します。
//
// 引数: t(*testing.T)、環境変数FAR89_INDICATOR_EXPORTは専用保存先です。
// 返り値: ありません。旧88対照は固定金融API4会計に限定します。
func TestExport89Indicator(t *testing.T) {
	out := os.Getenv("FAR89_INDICATOR_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if err := os.Mkdir(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		dir := filepath.Join(out, fmt.Sprintf("実指標_%+d", side))
		if err := os.Mkdir(dir, 0700); err != nil {
			t.Fatal(err)
		}
		r, quotes, seed := runIndicator89(t, side)
		old := indicator89G1Baseline(t, r, quotes, side)
		rows := []any{}
		boards := []map[string]any{}
		for _, q := range quotes {
			rows = append(rows, map[string]any{"quote": q, "accepted": true, "clock_missing": false, "feature_index": q.Index})
			row := map[string]any{"Symbol": "人工限月", "CurrentPriceTime": input89Stamp(q.Time), "CurrentPrice": q.Last}
			for n := 1; n <= 10; n++ {
				row[fmt.Sprintf("Buy%d", n)] = map[string]float64{"Price": q.Bid - float64(n-1)*10, "Qty": 100}
				row[fmt.Sprintf("Sell%d", n)] = map[string]float64{"Price": q.Ask + float64(n-1)*10, "Qty": 100}
			}
			boards = append(boards, row)
		}
		bookFile := input89Gzip(t, dir, "NK225.jsonl.gz", boards)
		r.result.Quality["NK225"] = RawQuality{Lines: int64(len(quotes)), Accepted: int64(len(quotes)), Contracts: []string{"人工限月"}}
		export89JSON(t, filepath.Join(dir, "89.json"), r.result)
		export89JSON(t, filepath.Join(dir, "88.json"), map[string]any{"session": r.session.ID, "books": old})
		export89JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export89JSON(t, filepath.Join(dir, "manifest.json"), InputManifest{Root: dir, Sessions: []InputSession{{ID: r.session.ID, Contract: "人工限月", Files: map[string]InputFile{"NK225_book": bookFile}}}})
		export89JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "実固定TechnicalBank・合成8時間種/当場原板・手製Source・8会計非0", "旧88G1対照": "88で使う固定87金融へ同じ4入口供給を旧時計で渡したAPI限定対照。far88.ReplayへのSource注入ではない。", "未計測": "元FAR自然Source/SourceEquivalenceは0空のまま。旧対照の未測定sharedは補完しない。", "Current": "当時特徴未供給のためnil。原板足/旗の出典を検証する。", "seed_view": seed, "非0会計数": 8})
	}
}

// TestExport89API はCurrent非nullとSource部分予約の手製API人工を保存します。
//
// 引数: t(*testing.T)、環境変数FAR89_API_EXPORTは専用保存先です。
// 返り値: ありません。手製指標/前史を原板整合として扱いません。
func TestExport89API(t *testing.T) {
	out := os.Getenv("FAR89_API_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if err := os.Mkdir(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		dir := filepath.Join(out, fmt.Sprintf("API_%+d", side))
		if err := os.Mkdir(dir, 0700); err != nil {
			t.Fatal(err)
		}
		r := runConnection89(t, side, true)
		grid := r.result.GridDecisions[0]
		q := grid.C0.Base.Quote
		rows := []any{map[string]any{"quote": q, "accepted": true, "clock_missing": false}}
		for _, after := range []float64{.5, 1, 2, 3, 4, 5, 6} {
			q.Time, q.Index, q.Line = grid.At+after, q.Index+1, q.Line+1
			move := 0.0
			if after >= 2 && after <= 4 {
				move = float64(side) * 40
			}
			q.Last, q.Bid, q.Ask = grid.C0.Base.Quote.Last+move, grid.C0.Base.Quote.Bid+move, grid.C0.Base.Quote.Ask+move
			rows = append(rows, map[string]any{"quote": q, "accepted": true, "clock_missing": false})
			if after == 2 {
				r.result.SourceEvents = append(r.result.SourceEvents, SourceEvent{At: q.Time, Origin: "quote", Quote: q, Method: grid.Source.Method, SourceAt: q.Time, SourceIndex: q.Index + 7, SourceLine: q.Line, Closes: []ReferenceClose{{ID: "手製部分", ReferenceID: grid.Source.Lots[1].Reference.ID, Before: 8, Quantity: 3, Reason: "手製部分"}}})
			}
		}
		r.result.InputEnd = &MergedEnd{Time: q.Time, Reference: "NK225", SourceLine: q.Line}
		export89JSON(t, filepath.Join(dir, "89.json"), r.result)
		export89JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export89JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "手製指標/Source/前史の8金融APIとCurrent抜粋の値複写", "注意": "Source同値/原板足/全clockは未計測。正式市場又は自然Sourceへ合算しない。", "非0会計数": 8})
	}
}
