package far85

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	far84 "github.com/masayoshi4649/SessionTradeExecuter/research84"
)

type artificialObservation struct {
	Quote     Quote         `json:"quote"`
	Technical TechnicalView `json:"technical"`
}

// writeArtificialJSON は明示した新規人工ファイルだけを保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・保存先・人工値です。
// 返り値: ありません。既存ファイルの上書きは拒否します。
func writeArtificialJSON(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(data); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
}

// TestExportArtificialSnapshots は買売6状態の4会計と旧84C0別運転を明示workへ保存します。
//
// 引数: t(*testing.T)、環境変数FAR85_ARTIFICIAL_OUT(string)は検査器と新規絶対出力根です。
// 返り値: ありません。未指定はskip。市場・実注文には接続しません。
func TestExportArtificialSnapshots(t *testing.T) {
	out := os.Getenv("FAR85_ARTIFICIAL_OUT")
	if out == "" {
		t.Skip("人工保存根が明示されていません")
	}
	if !filepath.IsAbs(out) {
		t.Fatal("人工保存先は絶対パスが必要です")
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatal("人工保存根は新規である必要があります")
	}
	if err := os.MkdirAll(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		for _, scene := range []string{"正益保護", "保持帯先行", "帯を遠く保存", "取得時既否定", "Qなし", "候補不供給"} {
			expectedPnL := map[string][2]float64{"正益保護": {200, 200}, "保持帯先行": {-82200, -42200},
				"帯を遠く保存": {-82200, -82200}, "取得時既否定": {57800, -22200}, "Qなし": {200, 200}, "候補不供給": {0, 0}}[scene]
			runtime, at := input85Runtime(t, side)
			if scene == "候補不供給" {
				runtime.current.Night.Known = false
			}
			hold := &runtime.current.Night.Buy
			if side < 0 {
				hold = &runtime.current.Night.Sell
			}
			if scene == "Qなし" {
				hold.QuantitySupport = false
			}
			if scene == "帯を遠く保存" {
				hold.Bid -= float64(side) * 30
				hold.Ask -= float64(side) * 30
			}
			before, beforeTech := runtime.last, runtime.bank.View().Technical
			if err := runtime.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			grid := runtime.result.GridDecisions[0]
			legacy := far84.ReplayResult{Session: runtime.session.ID, Quality: runtime.result.Quality, Books: map[string]far84.BookResult{}}
			legacyPolicies := map[string]far84.PolicySnapshot{}
			for _, policy := range []string{"A0", "C0", "C1"} {
				decision, err := far84.Refine(grid.Decision, policy)
				if err != nil {
					t.Fatal(err)
				}
				legacyPolicies[policy] = policySnapshot(decision, len(decision.Candidate(runtime.session.ID, grid.Window, 100).Lots) > 0)
			}
			legacy.GridDecisions = []far84.GridDecision{{At: grid.At, Window: grid.Window, EntryPolicy: "B1", Decision: grid.Decision,
				ClockAllowed: grid.ClockAllowed, BlockReason: grid.BlockReason, CandidateAccepted: legacyPolicies["A0"].CandidateAccepted,
				StructureAnchor: grid.StructureAnchor, Policies: legacyPolicies}}
			if !reflect.DeepEqual(grid.Policies["C0"], legacyPolicies["C0"]) {
				t.Fatal("人工の旧C0snapshot差")
			}
			c0, err := far84.Refine(grid.Decision, "C0")
			if err != nil {
				t.Fatal(err)
			}
			previous := map[int]*far84.Book{}
			for delay := 0; delay <= 1; delay++ {
				book, err := far84.NewBook(runtime.session.ID, "C0G1", 100)
				if err != nil {
					t.Fatal(err)
				}
				if err = book.SetFillDelay(float64(delay)); err != nil {
					t.Fatal(err)
				}
				if err = book.OnQuote(before, ReferenceFrame{}, beforeTech); err != nil {
					t.Fatal(err)
				}
				if err = book.OnGrid(at, before, c0.Candidate(runtime.session.ID, grid.Window, 100), grid.Decision.Technical, grid.StructureAnchor); err != nil {
					t.Fatal(err)
				}
				previous[delay] = book
			}
			moves := []float64{0, 0, 40, 40, 0, 0}
			if scene == "保持帯先行" || scene == "帯を遠く保存" {
				moves = []float64{0, 0, -20, -20, -60, -60}
			} else if scene == "取得時既否定" {
				moves = []float64{-40, -40, -40, -40, 40, 40}
			}
			observations := []artificialObservation{{before, beforeTech}}
			q := before
			for i, after := range []float64{.5, 1, 2, 3, 4, 5} {
				q.Time, q.Index, q.Line = at+after, q.Index+1, q.Line+1
				q.Last, q.Bid, q.Ask = before.Last+float64(side)*moves[i], before.Bid+float64(side)*moves[i], before.Ask+float64(side)*moves[i]
				if err := runtime.observeQuote(q, nil); err != nil {
					t.Fatal(err)
				}
				technical := runtime.bank.View().Technical
				observations = append(observations, artificialObservation{q, technical})
				for _, book := range previous {
					if err := book.OnQuote(q, ReferenceFrame{}, technical); err != nil {
						t.Fatal(err)
					}
				}
			}
			if err := runtime.advanceTimer(runtime.session.ForceClose, false); err != nil {
				t.Fatal(err)
			}
			for _, book := range previous {
				if err := book.Force(runtime.session.ForceClose, q, "場末10分前"); err != nil {
					t.Fatal(err)
				}
			}
			for _, at := range []float64{runtime.session.ForceClose, runtime.session.ForceClose + 1} {
				q.Time, q.Index, q.Line = at, q.Index+1, q.Line+1
				if err := runtime.observeQuote(q, nil); err != nil {
					t.Fatal(err)
				}
				technical := runtime.bank.View().Technical
				observations = append(observations, artificialObservation{q, technical})
				for _, book := range previous {
					if err := book.OnQuote(q, ReferenceFrame{}, technical); err != nil {
						t.Fatal(err)
					}
				}
			}
			for _, mode := range Modes {
				for delay := 0; delay <= 1; delay++ {
					runtime.result.Books[bookKey(mode, delay)] = runtime.books[bookKey(mode, delay)].Result()
				}
			}
			for delay, book := range previous {
				expected := book.Result()
				legacy.Books[fmt.Sprintf("C0G1_D%d", delay)] = expected
				actual := runtime.result.Books[bookKey("H0G1", delay)]
				assertOld84Book(t, actual, expected)
				quantity := 100
				if scene == "候補不供給" {
					quantity = 0
				}
				if actual.Metrics.EntryQuantity != quantity || actual.Unresolved {
					t.Fatal("人工の実新規量又は完結に差")
				}
				h1 := runtime.result.Books[bookKey("H1G1", delay)]
				if h1.Unresolved || h1.Metrics.EntryQuantity != quantity || h1.Metrics.ExitQuantity != quantity {
					t.Fatal("保持帯onの人工が完結しません")
				}
				if actual.Metrics.NetPnLYen != expectedPnL[0] || h1.Metrics.NetPnLYen != expectedPnL[1] {
					t.Fatal("買売・両遅延の手計算金額と不一致", scene, side, delay, actual.Metrics.NetPnLYen, h1.Metrics.NetPnLYen)
				}
				if scene == "保持帯先行" && h1.Metrics.HoldExitOrders != 1 {
					t.Fatal("保持帯先行人工が保持帯で返済していません")
				}
				if scene == "取得時既否定" && h1.Metrics.HoldEntryBreachedLots != 1 {
					t.Fatal("取得時否定が記録されません")
				}
			}
			dir := filepath.Join(out, fmt.Sprintf("%s_%+d", scene, side))
			if err := os.Mkdir(dir, 0700); err != nil {
				t.Fatal(err)
			}
			writeArtificialJSON(t, filepath.Join(dir, "85.json"), runtime.result)
			writeArtificialJSON(t, filepath.Join(dir, "84.json"), legacy)
			writeArtificialJSON(t, filepath.Join(dir, "人工観測.json"), observations)
		}
	}
	writeArtificialJSON(t, filepath.Join(out, "説明.json"), map[string]any{"種類": "85の買売6状態・4会計の手製保存接続", "場面": 12, "市場読取": 0, "市場新損益再生": 0,
		"旧基準": "固定84C0のBookを別運転し、H0のhold_追加以外の全field/値/順序を照合",
		"手計算": "正益時30ptの56枚利確と残44枚−10ptで200円。保持帯先行は100枚−30ptで−42200円、旧は−70ptで−82200円。取得時否定はH1−10ptで−22200円、旧は全量70ptで57800円。往復122円/枚。買売と両遅延は同額。",
		"限定":  "当時のChartBank種とE08は手製。実市場又は原板からの源特徴/指標の独立検査ではない。"})
}
