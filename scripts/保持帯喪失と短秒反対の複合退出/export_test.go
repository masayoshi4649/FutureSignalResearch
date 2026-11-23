package far86

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far85 "github.com/masayoshi4649/SessionTradeExecuter/research85"
)

type artificialObservation struct {
	Quote     Quote            `json:"quote"`
	Technical TechnicalView    `json:"technical"`
	Current   *CurrentEvidence `json:"current"`
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

// TestExportArtificialSnapshots は買売7状態の4会計と旧85H0別運転を明示workへ保存します。
//
// 引数: t(*testing.T)、環境変数FAR86_ARTIFICIAL_OUT(string)は検査器と新規絶対出力根です。
// 返り値: ありません。未指定はskip。市場・実注文には接続しません。
func TestExportArtificialSnapshots(t *testing.T) {
	exportArtificialSnapshots(t, "FAR86_ARTIFICIAL_OUT", false)
}

// exportArtificialSnapshots はAPI境界人工と全原行付き人工を明示して保存します。
//
// 引数: t(*testing.T)、env(string)は明示保存先の環境変数名、rawCompatible(bool)は全原行の整合版です。
// 返り値: ありません。源と異なる手製速度を持つAPI人工は原板整合版へ混ぜません。
func exportArtificialSnapshots(t *testing.T, env string, rawCompatible bool) {
	out := os.Getenv(env)
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
	scenes := []string{"正益保護", "両気配反対", "短秒未知", "片窓中立", "片気配のみ", "取得時既否定", "候補不供給"}
	if rawCompatible {
		scenes = []string{"正益保護", "両気配反対", "取得時既否定", "候補不供給"}
	}
	for _, side := range []int{1, -1} {
		for _, scene := range scenes {
			runtime, at := input86Runtime(t, side)
			source := &strategy.SelectedDay164Features{}
			rawQuotes := []rawArtificialQuote{}
			if rawCompatible {
				rawQuotes = prepareRawRuntime(t, runtime, source)
			}
			if scene == "候補不供給" {
				runtime.current.Night.Known = false
			}
			before, beforeTech, beforeCurrent := runtime.last, runtime.bank.View().Technical, runtime.current
			if err := runtime.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			grid := runtime.result.GridDecisions[0]
			legacy := far85.ReplayResult{Session: runtime.session.ID, Quality: runtime.result.Quality, Books: map[string]far85.BookResult{}}
			x, err := json.Marshal(runtime.result.GridDecisions)
			if err != nil {
				t.Fatal(err)
			}
			if err = json.Unmarshal(x, &legacy.GridDecisions); err != nil {
				t.Fatal(err)
			}
			c0, err := Decide(at, before, runtime.bank.View(), beforeCurrent)
			if err != nil {
				t.Fatal(err)
			}
			previous := map[int]*far85.Book{}
			for delay := 0; delay <= 1; delay++ {
				book, err := far85.NewBook(runtime.session.ID, "S0G1", 100, false)
				if err != nil {
					t.Fatal(err)
				}
				if err = book.SetFillDelay(float64(delay)); err != nil {
					t.Fatal(err)
				}
				if err = book.OnQuote(before, ReferenceFrame{}, beforeTech); err != nil {
					t.Fatal(err)
				}
				var hold far85.HoldAnchor
				x, err := json.Marshal(grid.HoldAnchor)
				if err != nil {
					t.Fatal(err)
				}
				if err = json.Unmarshal(x, &hold); err != nil {
					t.Fatal(err)
				}
				if err = book.OnGrid(at, before, c0.Candidate(runtime.session.ID, grid.Window, 100), grid.Decision.Technical, grid.StructureAnchor, hold, beforeCurrent); err != nil {
					t.Fatal(err)
				}
				previous[delay] = book
			}
			if !rawCompatible {
				for clock := before.Time - 30; clock <= before.Time; clock += 5 {
					q := before
					q.Time = clock
					input86SourceRow(q, source)
				}
			}
			moves := []float64{0, 0, 40, 40, 0, 0}
			if scene == "両気配反対" || scene == "短秒未知" || scene == "片窓中立" {
				moves = []float64{0, 0, -20, -20, -60, -60}
			}
			if scene == "取得時既否定" {
				moves = []float64{-40, -40, -40, -40, 40, 40}
			}
			if scene == "片気配のみ" {
				moves = []float64{0, 0, -20, -20, -20, -20}
			}
			observations := []artificialObservation{{before, beforeTech, &beforeCurrent}}
			q := before
			observe := func(q Quote) {
				row := input86SourceRow(q, source)
				if rawCompatible {
					row.SourceIndex = q.Index - 1
					rawQuotes = append(rawQuotes, rawArtificialQuote{Quote: q, Accepted: true, FeatureExpected: row.SourceIndex})
				}
				if scene == "短秒未知" {
					row.Short.Five.Known = false
					row.Short.Five.Reason = "人工の通常短秒未知"
				}
				if scene == "片窓中立" && row.Short.Five.Known {
					row.Short.Five.Move = 0
					row.Short.Five.Speed = 0
				}
				if err := runtime.observeQuote(q, row); err != nil {
					t.Fatal(err)
				}
				technical := runtime.bank.View().Technical
				observations = append(observations, artificialObservation{q, technical, row})
				for _, book := range previous {
					if err := book.OnQuote(q, ReferenceFrame{}, technical); err != nil {
						t.Fatal(err)
					}
				}
			}
			for i, after := range []float64{.5, 1, 2, 3, 4, 5} {
				q.Time, q.Index, q.Line = at+after, q.Index+1, q.Line+1
				q.Last, q.Bid, q.Ask = before.Last+float64(side)*moves[i], before.Bid+float64(side)*moves[i], before.Ask+float64(side)*moves[i]
				if scene == "片気配のみ" {
					if side > 0 {
						q.Ask = before.Ask
					} else {
						q.Bid = before.Bid
					}
				}
				observe(q)
			}
			if err := runtime.advanceTimer(runtime.session.ForceClose, false); err != nil {
				t.Fatal(err)
			}
			for _, book := range previous {
				if err := book.Force(runtime.session.ForceClose, q, "場末10分前"); err != nil {
					t.Fatal(err)
				}
			}
			for _, clock := range []float64{runtime.session.ForceClose, runtime.session.ForceClose + 1} {
				q.Time, q.Index, q.Line = clock, q.Index+1, q.Line+1
				observe(q)
			}
			for _, mode := range Modes {
				for delay := 0; delay <= 1; delay++ {
					runtime.result.Books[bookKey(mode, delay)] = runtime.books[bookKey(mode, delay)].Result()
				}
			}
			for delay, book := range previous {
				expected := book.Result()
				legacy.Books[fmt.Sprintf("H0G1_D%d", delay)] = expected
				actual := runtime.result.Books[bookKey("J0G1", delay)]
				assertOld85Book(t, actual, expected)
				quantity := 100
				if scene == "候補不供給" {
					quantity = 0
				}
				confirmed := runtime.result.Books[bookKey("J1G1", delay)]
				if actual.Unresolved || confirmed.Unresolved || actual.Metrics.EntryQuantity != quantity || confirmed.Metrics.EntryQuantity != quantity || confirmed.Metrics.ExitQuantity != quantity {
					t.Fatal("人工の実新規量又は完結に差", scene, side, delay)
				}
				hand := map[string][2]float64{"正益保護": {200, 200}, "両気配反対": {-82200, -42200}, "短秒未知": {-82200, -82200}, "片窓中立": {-82200, -82200}, "取得時既否定": {57800, -22200}, "候補不供給": {0, 0}}
				if pnl, ok := hand[scene]; ok && (actual.Metrics.NetPnLYen != pnl[0] || confirmed.Metrics.NetPnLYen != pnl[1]) {
					t.Fatal("両遅延・鏡像の手計算金額と不一致", scene, side, delay, actual.Metrics.NetPnLYen, confirmed.Metrics.NetPnLYen)
				}
			}
			dir := filepath.Join(out, fmt.Sprintf("%s_%+d", scene, side))
			if err := os.Mkdir(dir, 0700); err != nil {
				t.Fatal(err)
			}
			writeArtificialJSON(t, filepath.Join(dir, "86.json"), runtime.result)
			writeArtificialJSON(t, filepath.Join(dir, "85.json"), legacy)
			writeArtificialJSON(t, filepath.Join(dir, "人工観測.json"), observations)
			if rawCompatible {
				writeArtificialJSON(t, filepath.Join(dir, "raw_quotes.json"), rawQuotes)
			}
		}
	}
	writeArtificialJSON(t, filepath.Join(out, "説明.json"), map[string]any{"種類": "86の買売・4会計の手製保存接続", "場面": len(scenes) * 2, "原板全行付き": rawCompatible, "市場読取": 0, "市場新損益再生": 0,
		"旧基準": "固定85H0のBookを別運転し、J0のconfirm_追加以外の全field/値/順序を照合",
		"限定":  "入口ChartBank種とE08は手製。短秒は源SelectedDay164Features経由で、短秒未知/片窓中立は明示人工。実市場の証明ではない。"})
}
