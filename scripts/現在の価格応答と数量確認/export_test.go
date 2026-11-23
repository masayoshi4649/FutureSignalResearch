package far84

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	far83 "github.com/masayoshi4649/SessionTradeExecuter/research83"
)

type artificialObservation struct {
	Quote     Quote         `json:"quote"`
	Technical TechnicalView `json:"technical"`
}

// writeArtificialJSON は新規の人工JSONだけを保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・新規先・人工値です。
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

// TestExportArtificialSnapshots は明示された新規work先へ非0人工接続を保存します。
//
// 引数: t(*testing.T)、環境変数FAR84_ARTIFICIAL_OUT(string)は検査器と明示出力根です。
// 返り値: ありません。変数未指定ではskipし、市場入力や損益再生を行いません。
func TestExportArtificialSnapshots(t *testing.T) {
	out := os.Getenv("FAR84_ARTIFICIAL_OUT")
	if out == "" {
		t.Skip("人工保存先が明示されていません")
	}
	if !filepath.IsAbs(out) {
		t.Fatal("人工保存先には絶対パスが必要です")
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatal("人工保存根は新規である必要があります")
	}
	if err := os.MkdirAll(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		for _, scene := range []string{"正常", "数量不成立", "構造未知"} {
			runtime, at := input84Runtime(t, side)
			if scene == "構造未知" {
				runtime.current.Night.Known = false
			} else if scene == "数量不成立" {
				if side > 0 {
					runtime.current.Night.Buy.QuantitySupport = false
				} else {
					runtime.current.Night.Sell.QuantitySupport = false
				}
			}
			before := runtime.last
			if err := runtime.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			grid := runtime.result.GridDecisions[0]
			legacy := far83.ReplayResult{Session: runtime.session.ID, Quality: runtime.result.Quality,
				Books: map[string]far83.BookResult{}, GridDecisions: []far83.GridDecision{{At: grid.At, Window: grid.Window,
					EntryPolicy: grid.EntryPolicy, Decision: grid.Decision, ClockAllowed: grid.ClockAllowed,
					BlockReason: grid.BlockReason, CandidateAccepted: grid.CandidateAccepted, StructureAnchor: grid.StructureAnchor}}}
			previous := map[int]*far83.Book{}
			for delay := 0; delay <= 1; delay++ {
				book, err := far83.NewBook(runtime.session.ID, "S0G1", 100)
				if err != nil {
					t.Fatal(err)
				}
				if err = book.SetFillDelay(float64(delay)); err != nil {
					t.Fatal(err)
				}
				if err = book.OnQuote(before, ReferenceFrame{}, grid.Decision.Technical); err != nil {
					t.Fatal(err)
				}
				if err = book.OnGrid(at, before, grid.Decision.Candidate(runtime.session.ID, grid.Window, 100), grid.Decision.Technical, grid.StructureAnchor); err != nil {
					t.Fatal(err)
				}
				previous[delay] = book
			}
			observations := []artificialObservation{{before, grid.Decision.Technical}}
			q := before
			for _, step := range []struct{ after, move float64 }{{.5, 0}, {1, 0}, {2, 40}, {3, 40}, {4, 0}, {5, 0}} {
				q.Time, q.Index, q.Line = at+step.after, q.Index+1, q.Line+1
				q.Last, q.Bid, q.Ask = before.Last+float64(side)*step.move, before.Bid+float64(side)*step.move, before.Ask+float64(side)*step.move
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
				result := book.Result()
				legacy.Books[fmt.Sprintf("S0G1_D%d", delay)] = result
				actual := runtime.result.Books[bookKey("A0G1", delay)]
				if result.Metrics.EntryQuantity != 100 || result.Unresolved || !reflect.DeepEqual(result, actual) {
					t.Fatal("別運転した旧83人工との非0全文同値がありません", side, scene, delay)
				}
			}
			dir := filepath.Join(out, fmt.Sprintf("%s_%+d", scene, side))
			if err := os.Mkdir(dir, 0700); err != nil {
				t.Fatal(err)
			}
			writeArtificialJSON(t, filepath.Join(dir, "84.json"), runtime.result)
			writeArtificialJSON(t, filepath.Join(dir, "83.json"), legacy)
			writeArtificialJSON(t, filepath.Join(dir, "人工観測.json"), observations)
		}
	}
	writeArtificialJSON(t, filepath.Join(out, "説明.json"), map[string]any{"種類": "Goの明示人工保存接続", "場面": 6,
		"金融": "固定far83.S0G1を別運転したA0人工の全文同値", "市場読取": 0, "市場新損益再生": 0,
		"限定": "チャート種と現在E08は手製の人工。源特徴・指標の原板からの生成を実証せず、実市場成績又は全66場基準同値の証明ではない。"})
}
