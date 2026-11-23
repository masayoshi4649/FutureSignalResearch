package far92

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far89 "github.com/masayoshi4649/SessionTradeExecuter/research89"
)

// saveArtificial92 は明示出力へ人工証拠を新規保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・出力・値です。
// 返り値: ありません。既存ファイルは拒否します。
func saveArtificial92(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(append(data, '\n')); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
}

// copyArtificial92 は一時人工入力だけを明示出力へ複写します。
//
// 引数: t(*testing.T)、src/dst(string)は人工入力と新規保存先です。
// 返り値: ありません。
func copyArtificial92(t *testing.T, src, dst string) {
	t.Helper()
	err := filepath.WalkDir(src, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, e := filepath.Rel(src, path)
		if e != nil {
			return e
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0755)
		}
		data, e := os.ReadFile(path)
		if e != nil {
			return e
		}
		f, e := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
		if e != nil {
			return e
		}
		_, e = f.Write(data)
		closeErr := f.Close()
		if e != nil {
			return e
		}
		return closeErr
	})
	if err != nil {
		t.Fatal(err)
	}
}

// TestExport92Fixtures は明示環境変数があるときだけ人工を保存します。
//
// 引数: t(*testing.T)は検査器、WORK92_EXPORT環境変数(string)は新規出力根です。
// 返り値: ありません。市場入力は開かず全入力を合成します。
func TestExport92Fixtures(t *testing.T) {
	out := os.Getenv("WORK92_EXPORT")
	if out == "" {
		t.Skip("WORK92_EXPORT未指定")
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatal("人工出力根は未使用が必要", err)
	}
	if err := os.MkdirAll(out, 0755); err != nil {
		t.Fatal(err)
	}
	// ----------------------------------------
	// 自然Source合成は元driver/実数値器の全scope、H0実取得0を明示します。
	m := input89MultiFixture(t, false)
	seeds, err := far80.PrepareTechnicalSeeds(m)
	if err != nil {
		t.Fatal(err)
	}
	for _, input := range m.Sessions {
		seed := seeds[input.ID]
		copy := seed
		got, e := Replay(m.Root, input, &copy)
		if e != nil {
			t.Fatal(e)
		}
		copy = seed
		old, e := far89.Replay(m.Root, input, &copy)
		if e != nil {
			t.Fatal(e)
		}
		compareControl92(t, got, old)
		dir := filepath.Join(out, "自然Source", input.ID)
		saveArtificial92(t, filepath.Join(dir, "92.json"), got)
		saveArtificial92(t, filepath.Join(dir, "89.json"), old)
		saveArtificial92(t, filepath.Join(out, "自然Source", "再生", input.ID+".json"), got)
		saveArtificial92(t, filepath.Join(dir, "人工観測.json"), map[string]any{"合成入力": true, "Source生成": "固定FARを合成入力で運転、別80driverと全frame同値", "市場": 0, "新実運用損益": 0, "H0実玉数": len(got.Books["H0G1_D0"].Lots), "SourceEq": got.SourceEquivalence})
	}
	inputRoot := filepath.Join(out, "自然Source", "人工入力")
	copyArtificial92(t, m.Root, inputRoot)
	m.Root, m.StrategyRoot = inputRoot, inputRoot
	saveArtificial92(t, filepath.Join(out, "自然Source", "入力台帳.json"), m)
	// ----------------------------------------
	// 金融API限定。価格と旧E1出典は手製であり、旧trace全面同値を主張しません。
	for _, side := range []int{1, -1} {
		for _, oldEvent := range []bool{true, false} {
			r := runConnection92(t, side, oldEvent)
			dir := filepath.Join(out, "API非0", fmt.Sprintf("方向%d_旧E1%v", side, oldEvent))
			for i := range r.result.ProfitContexts {
				r.result.ProfitContexts[i].CurrentAvailable = false
				r.result.ProfitContexts[i].Current = nil
			}
			grid := r.result.GridDecisions[0]
			q := grid.C0.Base.Quote
			quotes := []Quote{q}
			for _, offset := range []float64{.5, 1, 2, 3, 4, 5} {
				q.Time = grid.At + offset
				q.Index++
				q.Line++
				move := 0.0
				if offset >= 2 {
					move = float64(side) * 40
				}
				q.Bid = grid.C0.Base.Quote.Bid + move
				q.Ask = grid.C0.Base.Quote.Ask + move
				q.Last = q.Bid
				quotes = append(quotes, q)
			}
			saveArtificial92(t, filepath.Join(dir, "92.json"), r.result)
			saveArtificial92(t, filepath.Join(dir, "raw_quotes.json"), quotes)
			saveArtificial92(t, filepath.Join(dir, "人工観測.json"), map[string]any{"市場": 0, "金融": "固定89公開API、全H0を各原行で独立旧89 Bookへ全文照合", "限定": "手製Source/E1/価格/ATR。旧entry_observationsと旧Sequenceの全面整合/実指標/元Source生成/全予定時計の証明ではない", "SourceEq": "0/空のまま、補完なし", "PriceCounts": r.result.PriceCounts})
		}
	}
	// ----------------------------------------
	// 実指標/合成raw/手製Sourceは価格原板までの非0統合、SourceEqは0/空です。
	for _, side := range []int{1, -1} {
		r, raw, seed := runIndicator89(t, side)
		baseline := indicator89G1Baseline(t, r, raw, side)
		old := far89.ReplayResult{Session: r.result.Session, Quality: r.result.Quality, ReferenceCounts: r.result.ReferenceCounts, Books: map[string]far89.BookResult{}, GridDecisions: r.result.GridDecisions, SourceEvents: r.result.SourceEvents, EntryObservations: r.result.EntryObservations, EntryBindings: []EntryOrderBinding{}, TechnicalEquivalence: r.result.TechnicalEquivalence, SeedView: r.result.SeedView, ProfitContexts: []ProfitContext{}, InputEnd: r.result.InputEnd}
		for delay := 0; delay <= 1; delay++ {
			old.Books[bookKey("E1G1", delay)] = baseline[bookKey("E1", delay)]
		}
		for _, b := range r.result.EntryBindings {
			b.BookKey = bookKey("E1G1", b.DelaySeconds)
			old.EntryBindings = append(old.EntryBindings, b)
		}
		dir := filepath.Join(out, "実指標非0", fmt.Sprintf("方向%d", side))
		saveArtificial92(t, filepath.Join(dir, "92.json"), r.result)
		saveArtificial92(t, filepath.Join(dir, "89.json"), old)
		saveArtificial92(t, filepath.Join(dir, "raw_quotes.json"), raw)
		saveArtificial92(t, filepath.Join(dir, "seed_view.json"), seed)
		saveArtificial92(t, filepath.Join(dir, "人工観測.json"), map[string]any{"市場": 0, "原板": "全当場rawは5秒合成、前史8時間も合成", "指標": "固定TechnicalBankと独立eventBankを全原行/旧core呼出で同値", "Source": "手製当時参照、元生成/80全面同値は未計測", "SourceEq": "0/空を維持", "control": "旧89.Book API、共有旧E1供給と全raw/旧timerを別運転して全文一致", "新金融": "fixed89直接import、4Book実8枚/正益/G1/完結"})
	}
	// ----------------------------------------
	// 純trackerの全Record/各時点snapshot/counterを独立Pythonへ渡します。
	for _, side := range []int{1, -1} {
		for _, kind := range []string{"完成", "継承", "H否定後押し", "H保持再attempt", "p更新", "同値"} {
			f := newPriceFixture(side)
			f.complete(t)
			switch kind {
			case "継承":
				f.add(t, 94, 95)
			case "H否定後押し":
				f.add(t, 95, 94)
				f.add(t, 94, 94)
			case "H保持再attempt":
				f.add(t, 95, 94)
				f.add(t, 101, 100)
				f.add(t, 99, 98)
				f.add(t, 102, 99)
			case "p更新":
				f.add(t, 110, 110)
				f.add(t, 112, 111)
			case "同値":
				f.add(t, 111, 105)
				f.add(t, 111, 105)
			}
			tracker := NewPriceTracker()
			snapshots := []PriceSnapshot{}
			counts := []PriceCounts{}
			for _, record := range f.records {
				if err := tracker.Feed(record); err != nil {
					t.Fatal(err)
				}
				s, e := tracker.Snapshot(record.Input.At)
				if e != nil {
					t.Fatal(e)
				}
				snapshots = append(snapshots, s)
				counts = append(counts, tracker.Counts())
			}
			saveArtificial92(t, filepath.Join(out, "tracker", fmt.Sprintf("方向%d_%s.json", side, kind)), map[string]any{"records": f.records, "snapshots": snapshots, "counts": counts})
		}
	}
}
