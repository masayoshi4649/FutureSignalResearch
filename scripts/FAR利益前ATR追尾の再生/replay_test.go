package riskport98

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	risk "github.com/masayoshi4649/SessionTradeExecuter/minirisk98"
)

// clone は人工だけのpointer/sliceを分けます。
//
// 引数: v(T)は公開型。
// 返り値: TはJSONで独立した値。
func clone[T any](v T) T {
	body, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	var out T
	if err = json.Unmarshal(body, &out); err != nil {
		panic(err)
	}
	return out
}

// fixtureTape は停止金融人工のSourceと固定96手製技法を結びます。
//
// 引数: t(*testing.T)、path(string)は試験器と明示人工パス。
// 返り値: tape.TapeはSource/ATR/技法が手製で自然形成を主張しない入力。
func fixtureTape(t *testing.T, path string) tape.Tape {
	t.Helper()
	f, err := tape.LoadFixture(path)
	if err != nil {
		t.Fatal(err)
	}
	side := 1
	if strings.Contains(filepath.Base(path), "方向-1_") {
		side = -1
	}
	role := "A"
	if strings.Contains(path, "利益移行") {
		role = "B"
	}
	base, err := tape.LoadFixture(filepath.Join("..", "..", "work", "96結合人工", "初回", fmt.Sprintf("方向%d_%s.json", side, role)))
	if err != nil {
		t.Fatal(err)
	}
	input := clone(base.ChartGrids[0])
	latest := f.Steps[1]
	input.Current.Time, input.Current.Received = latest.Observation.Time, latest.Observation.Received
	input.Current.SourceIndex, input.Current.SourceLine = latest.Observation.Index, latest.SourceLine
	input.Current.Last, input.Current.Bid, input.Current.Ask = latest.Observation.Last, latest.Observation.Bid, latest.Observation.Ask
	input.Current.Buy.OwnAt, input.Current.Sell.OwnAt = latest.Observation.Time, latest.Observation.Time
	f.ChartGrids = []actual.TechnicalGateInput{input}
	out := tape.Tape{Version: 1, Session: f.Session, Capabilities: tape.Capabilities(), Events: []tape.TapeEvent{}, Scope: "固定98Go型人工。停止金融の公開NativeBatchを直接保存し、手製ATR/固定96手製A/B文脈へ結合。Ledger再構成/自然Source/指標形成/市場は未計測。"}
	for i, e := range f.Events {
		entry := tape.TapeEvent{Ordinal: i + 1, Kind: e.Kind}
		var batches []actual.NativeBatch
		switch e.Kind {
		case "quote":
			s := f.Steps[e.Index]
			q, err := tape.ProjectQuote(s.Observation, s.SourceLine)
			if err != nil {
				t.Fatal(err)
			}
			entry.At, entry.Quote = q.Time, &q
			batches = s.Batches
		case "force":
			s := f.Timers[e.Index]
			entry.At = s.At
			batches = s.Batches
		case "grid":
			context := clone(f.ChartGrids[e.Index])
			entry.At, entry.Context = f.Grids[e.Index], &context
		default:
			t.Fatal(e.Kind)
		}
		if e.Kind != "grid" {
			entry.Methods, entry.NonEmpty, err = tape.CompressBatches(batches)
			if err != nil {
				t.Fatal(err)
			}
		}
		out.Events = append(out.Events, entry)
	}
	return out
}

// TestRiskTapeProduction は14手製Tapeの24会計と空8の旧97全時点を確認します。
//
// 引数: t(*testing.T)は試験器。
// 返り値: ありません。全原行観測は人工だけで、production結果/callbackを全文比較します。
func TestRiskTapeProduction(t *testing.T) {
	paths, err := filepath.Glob(filepath.Join("..", "..", "work", "98初期ATR追尾案", "人工", "停止版", "方向*.json"))
	if err != nil || len(paths) != 14 {
		t.Fatal("停止14人工が必要", err, len(paths))
	}
	for _, path := range paths {
		t.Run(filepath.Base(path), func(t *testing.T) {
			input := fixtureTape(t, path)
			oldRecords := []port.GateAssessmentRecord{}
			old, err := port.Run(input, port.CapturedHarvest{Records: &oldRecords}, port.Configurations([]string{"H0"}))
			if err != nil {
				t.Fatal(err)
			}
			observed, _, err := ReplayRisk(input, true)
			if err != nil {
				t.Fatal(err)
			}
			actualRun, records, err := ReplayRisk(input, false)
			if err != nil {
				t.Fatal(err)
			}
			for key, expected := range old.Books {
				if !bytes.Equal(expected, observed.Books[key]) || old.StateSHA256[key] != observed.StateSHA256[key] {
					t.Fatal("空riskの旧97全時点/最終差", key)
				}
				if old.GateCallbacks[key] != observed.GateCallbacks[key] {
					t.Fatal("空riskの現在候補回数差", key)
				}
			}
			x, _ := json.Marshal(observed.Books)
			y, _ := json.Marshal(actualRun.Books)
			if !bytes.Equal(x, y) {
				t.Fatal("productionと全時点観測の最終全Book差")
			}
			x, _ = json.Marshal(observed.GateCallbacks)
			y, _ = json.Marshal(actualRun.GateCallbacks)
			if !bytes.Equal(x, y) || len(actualRun.StateSHA256) != 0 {
				t.Fatal("productionの観測scope差")
			}
			requests, forceCount := 0, 0
			contexts := []actual.TechnicalGateInput{}
			for _, e := range input.Events {
				if e.Kind == "force" {
					forceCount++
				}
				if e.Kind == "grid" {
					contexts = append(contexts, *e.Context)
				}
			}
			if forceCount != 1 {
				t.Fatal("明示Forceが必要")
			}
			for key, body := range actualRun.Books {
				var r risk.ActualResult
				if err := json.Unmarshal(body, &r); err != nil {
					t.Fatal(err)
				}
				if !r.Complete || r.Totals.OpenBuy != 0 || r.Totals.OpenSell != 0 {
					t.Fatal("未完", key)
				}
				requests += r.Metrics.InitialRiskExitRequests
			}
			if strings.Contains(path, "幅と次板悪化") && requests == 0 {
				t.Fatal("risk非0の入口がない")
			}
			if dir := os.Getenv("RISKTAPE98_EXPORT"); dir != "" {
				if err := os.MkdirAll(dir, 0755); err != nil {
					t.Fatal(err)
				}
				proof := map[string]any{"scope": input.Scope, "tape": input, "output": map[string]any{"version": 1, "session": input.Session.ID, "books": actualRun.Books, "chart_grids": contexts, "gate_assessments": records, "source_reexecuted": false, "charts_recomputed": false, "empty_risk_97_match": map[string]any{"all": true, "books": 8, "scope": "同じ手製Tapeを旧97H0公開APIへ運転した限定比較。正式市場対照ではない。"}}, "baseline97_api": map[string]any{"books": old.Books, "scope": "手製API限定"}, "empty_risk_all_snapshots_equal": true, "production_full_books_equal": true, "initial_risk_requests": requests, "callbacks": actualRun.GateCallbacks}
				body, err := json.MarshalIndent(proof, "", "  ")
				if err != nil {
					t.Fatal(err)
				}
				if err = os.WriteFile(filepath.Join(dir, filepath.Base(path)), append(body, '\n'), 0644); err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}

// TestRiskGateRecordBoundaries は24ログ集合とnamed型の全fieldを確認します。
//
// 引数: t(*testing.T)は試験器。
// 返り値: ありません。保存採否を転記せず候補/全checkを保持します。
func TestRiskGateRecordBoundaries(t *testing.T) {
	input := fixtureTape(t, filepath.Join("..", "..", "work", "98初期ATR追尾案", "人工", "停止版", "方向1_幅と次板悪化.json"))
	out, records, err := ReplayRisk(input, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 12 {
		t.Fatal("24会計のAB12候補", len(records))
	}
	broken := append(append([]GateAssessmentRecord{}, records...), records[0])
	if ValidateGateRecords(input, out, broken) == nil {
		t.Fatal("重複ログを通した")
	}
	broken = clone(records)
	broken[0].Candidate.Ordinal++
	if ValidateGateRecords(input, out, broken) == nil {
		t.Fatal("候補ordinal破損を通した")
	}
	broken = clone(records)
	broken[0].Candidate.At++
	if ValidateGateRecords(input, out, broken) == nil {
		t.Fatal("候補時計破損を通した")
	}
	for _, e := range input.Events {
		a, _ := json.Marshal(e.NonEmpty)
		b, _ := json.Marshal(ConvertBatches(e.NonEmpty))
		if len(e.NonEmpty) > 0 && !bytes.Equal(a, b) {
			t.Fatal("batch型変換差")
		}
	}
	var candidate risk.EntryCandidate
	body, _ := json.Marshal(records[0].Candidate)
	if err = json.Unmarshal(body, &candidate); err != nil {
		t.Fatal(err)
	}
	converted, _ := json.Marshal(ConvertCandidate(candidate))
	if !bytes.Equal(body, converted) {
		t.Fatal("候補全field変換差")
	}
}
