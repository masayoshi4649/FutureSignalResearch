package far88

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far87 "github.com/masayoshi4649/SessionTradeExecuter/research87"
)

// export88JSON は人工証拠を既存上書きなしで保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・新規保存先・人工値です。
// 返り値: ありません。保存済み証拠の上書きと非有限値は失敗となります。
func export88JSON(t *testing.T, path string, value any) {
	t.Helper()
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
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

// export88IndicatorBaseline は別の旧87Bookと旧actual時計からS全値を照合します。
//
// 引数: t(*testing.T)、r(*replayRuntime)、raw([]Quote)、side(int)は合成数値器の入力です。
// 返り値: *far87.ReplayResultは旧金融Sの独立API対照です。Source自然運転ではありません。
func export88IndicatorBaseline(t *testing.T, r *replayRuntime, raw []Quote, side int) *far87.ReplayResult {
	t.Helper()
	seed, _ := indicator88Seed(t, r.session.Start, side)
	bank := NewChartBank(seed)
	bank.BeginSession(r.session.Start)
	books := map[string]*Book{}
	for delay := 0; delay <= 1; delay++ {
		b, e := far87.NewSourceBook(r.session.ID, "S", 100)
		if e != nil {
			t.Fatal(e)
		}
		if e = b.SetFillDelay(float64(delay)); e != nil {
			t.Fatal(e)
		}
		books[fmt.Sprintf("R0G1_D%d", delay)] = b
	}
	baseline := &far87.ReplayResult{Session: r.session.ID, Books: map[string]BookResult{}, Quality: r.result.Quality, ReferenceCounts: map[string]int{}, SourceEvents: []far87.SourceEvent{}}
	grids := map[float64]GridDecision{}
	for _, g := range r.result.GridDecisions {
		grids[g.At] = g
		baseline.GridDecisions = append(baseline.GridDecisions, far87.GridDecision{At: g.At, Window: g.Window, ClockAllowed: g.ClockAllowed, BlockReason: g.BlockReason, C0: g.C0, Source: g.Source, SourceLine: g.SourceLine, StructureAnchor: g.StructureAnchor})
	}
	times, _, e := replayTimers(r.session)
	if e != nil {
		t.Fatal(e)
	}
	cursor := 0
	last := Quote{Index: -1}
	advance := func(at float64) {
		if e := bank.Advance(at); e != nil {
			t.Fatal(e)
		}
		if at == r.session.ForceClose {
			for _, b := range books {
				if e := b.Force(at, last, "場末10分前"); e != nil {
					t.Fatal(e)
				}
			}
		}
		if g, ok := grids[at]; ok {
			source := g.Source
			if !g.ClockAllowed {
				source.Lots = []ReadLot{}
				source.Closes = []ReferenceClose{}
			}
			for _, b := range books {
				if e := b.OnSourceGrid(at, last, source, g.C0, bank.View().Technical, g.StructureAnchor); e != nil {
					t.Fatal(e)
				}
			}
		}
	}
	for _, q := range raw {
		for cursor < len(times) && times[cursor] <= q.Time {
			advance(times[cursor])
			cursor++
		}
		chart := q
		chart.Valid = q.Last > 0
		if e := bank.Observe(chart); e != nil {
			t.Fatal(e)
		}
		for _, b := range books {
			if e := b.OnQuote(q, ReferenceFrame{}, bank.View().Technical, nil); e != nil {
				t.Fatal(e)
			}
		}
		last = q
	}
	for cursor < len(times) {
		advance(times[cursor])
		cursor++
	}
	for delay := 0; delay <= 1; delay++ {
		key := fmt.Sprintf("R0G1_D%d", delay)
		baseline.Books[key] = books[key].Result()
		if !reflect.DeepEqual(baseline.Books[key], r.result.Books[bookKey("S", delay)]) {
			t.Fatal("実指標人工の独立旧S全文差", delay)
		}
	}
	return baseline
}

// TestExport88Indicator は実指標・原板整合の非0E1を別範囲の人工として保存します。
//
// 引数: t(*testing.T)、環境変数FAR88_INDICATOR_EXPORTは新規先です。
// 返り値: ありません。Source生成だけが手製であり元FAR同値0を成功へ補完しません。
func TestExport88Indicator(t *testing.T) {
	out := os.Getenv("FAR88_INDICATOR_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if e := os.Mkdir(out, 0700); e != nil {
		t.Fatal(e)
	}
	for _, side := range []int{1, -1} {
		dir := filepath.Join(out, fmt.Sprintf("実指標_%+d", side))
		if e := os.Mkdir(dir, 0700); e != nil {
			t.Fatal(e)
		}
		r, quotes, seed := runIndicator88(t, side)
		rows := []any{}
		boardRows := []map[string]any{}
		for _, q := range quotes {
			rows = append(rows, map[string]any{"quote": q, "accepted": true, "clock_missing": false, "feature_index": q.Index})
			row := map[string]any{"Symbol": "人工限月", "CurrentPriceTime": input88Stamp(q.Time), "CurrentPrice": q.Last}
			for n := 1; n <= 10; n++ {
				row[fmt.Sprintf("Buy%d", n)] = map[string]float64{"Price": q.Bid - float64(n-1)*10, "Qty": 100}
				row[fmt.Sprintf("Sell%d", n)] = map[string]float64{"Price": q.Ask + float64(n-1)*10, "Qty": 100}
			}
			boardRows = append(boardRows, row)
		}
		bookFile := input88Gzip(t, dir, "NK225.jsonl.gz", boardRows)
		r.result.Quality["NK225"] = RawQuality{Lines: int64(len(quotes)), Accepted: int64(len(quotes)), Contracts: []string{"人工限月"}}
		baseline := export88IndicatorBaseline(t, r, quotes, side)
		export88JSON(t, filepath.Join(dir, "88.json"), r.result)
		export88JSON(t, filepath.Join(dir, "87.json"), baseline)
		export88JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export88JSON(t, filepath.Join(dir, "manifest.json"), InputManifest{Root: dir, Sessions: []InputSession{{ID: r.session.ID, Contract: "人工限月", Files: map[string]InputFile{"NK225_book": bookFile}}}})
		export88JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "実固定TechnicalBank＋合成8時間種＋合成当場原板＋手製参照玉", "注意": "元FAR自然Source生成/固定80同値は未計測、source_equivalenceは0/空のまま。市場性能ではありません。Current抜粋はnilであり技法/旗原行だけを検証します。", "seed_view": seed, "非0会計数": 6, "元Source生成を再実装": false, "独立旧87S全文同値": true})
	}
}

// TestExport88Natural は合成原板から自然に進む元Sourceと独立旧87を輸出します。
//
// 引数: t(*testing.T)は検査器、環境変数FAR88_NATURAL_EXPORTは空の新規保存先です。
// 返り値: ありません。実市場は読まず、E0/E1の非0証明とは区別します。
func TestExport88Natural(t *testing.T) {
	out := os.Getenv("FAR88_NATURAL_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if err := os.Mkdir(out, 0700); err != nil {
		t.Fatal(err)
	}
	manifest := input88MultiFixture(t, false)
	oldRoot := manifest.Root
	inputRoot := filepath.Join(out, "入力")
	if err := os.Mkdir(inputRoot, 0700); err != nil {
		t.Fatal(err)
	}
	for _, input := range manifest.Sessions {
		for _, f := range input.Files {
			dest := filepath.Join(inputRoot, filepath.FromSlash(f.Path))
			if err := os.MkdirAll(filepath.Dir(dest), 0700); err != nil {
				t.Fatal(err)
			}
			b, err := os.ReadFile(filepath.Join(oldRoot, filepath.FromSlash(f.Path)))
			if err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(dest, b, 0600); err != nil {
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
	export88JSON(t, filepath.Join(out, "manifest.json"), manifest)
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
		got, err := Replay(manifest.Root, input, &seed)
		if err != nil {
			t.Fatal(err)
		}
		old, err := far87.Replay(manifest.Root, input, &oldSeed)
		if err != nil {
			t.Fatal(err)
		}
		export88JSON(t, filepath.Join(dir, "88.json"), got)
		export88JSON(t, filepath.Join(dir, "87.json"), old)
		session, err := sessionClock(input.ID)
		if err != nil {
			t.Fatal(err)
		}
		boards, _, err := readBoards(filepath.Join(manifest.Root, filepath.FromSlash(input.Files["NK225_book"].Path)), "NK225", session)
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
		export88JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export88JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "合成原板・実Features/TechnicalBank/元Source自然運転・独立旧87比較", "注意": "実市場成績ではありません。E0/E1非0と再開イベントの非0原板証明は別人工です。入力Qty10を変更する再materializeはしません。", "input": input, "seed_view": got.SeedView, "S枚数": got.Books["S_D0"].Metrics.EntryQuantity, "E0枚数": got.Books["E0_D0"].Metrics.EntryQuantity, "E1枚数": got.Books["E1_D0"].Metrics.EntryQuantity})
		t.Log(fmt.Sprint(input.ID), "保存済")
	}
}

// TestExport88API はCurrent抜粋も非nullとなる手製金融API人工を保存します。
//
// 引数: t(*testing.T)、環境変数FAR88_API_EXPORTは新規保存先です。
// 返り値: ありません。手製指標のため原板Close/TRの成功証拠とはしません。
func TestExport88API(t *testing.T) {
	out := os.Getenv("FAR88_API_EXPORT")
	if out == "" {
		t.Skip("明示された人工保存先がありません")
	}
	if e := os.Mkdir(out, 0700); e != nil {
		t.Fatal(e)
	}
	for _, side := range []int{1, -1} {
		dir := filepath.Join(out, fmt.Sprintf("API_%+d", side))
		if e := os.Mkdir(dir, 0700); e != nil {
			t.Fatal(e)
		}
		r := runConnection88(t, side, true)
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
		export88JSON(t, filepath.Join(dir, "88.json"), r.result)
		export88JSON(t, filepath.Join(dir, "raw_quotes.json"), rows)
		export88JSON(t, filepath.Join(dir, "人工観測.json"), map[string]any{"範囲": "Source/指標/時計前史は手製の金融API接続。Current非null値複写/外binding/全trigger/将来片除外の人工", "注意": "Source全frame/hash・Technical全履歴・原板CloseTRは未計測。正常原板と呼ばず、全場正式監査の成功証拠に合算しません。", "Current支持Windows": "保存対象外・入力map変更で保存が変わらない検査済み", "非0会計": 6, "利益原行": len(r.result.ProfitContexts)})
	}
}
