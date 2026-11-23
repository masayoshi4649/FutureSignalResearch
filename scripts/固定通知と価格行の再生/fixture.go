package lighttape97

import (
	"encoding/json"
	"fmt"
	"os"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// Fixture は固定96Go型人工だけの入力で、自然Sourceの証明へ使いません。
type Fixture struct {
	Session actual.Session `json:"session"`
	Scope   string         `json:"scope"`
	Steps   []struct {
		Observation actual.Observation   `json:"observation"`
		SourceLine  int64                `json:"source_line"`
		Batches     []actual.NativeBatch `json:"batches"`
	} `json:"steps"`
	Timers []struct {
		At      float64              `json:"at"`
		Batches []actual.NativeBatch `json:"batches"`
	} `json:"timers"`
	Grids  []float64 `json:"grids"`
	Events []struct {
		Kind  string `json:"kind"`
		Index int    `json:"index"`
	} `json:"events"`
	Actors     map[string]actual.ActualResult `json:"actors"`
	ChartGrids []actual.TechnicalGateInput    `json:"chart_grids"`
}

// LoadFixture は明示されたGo型人工を読むだけです。
//
// 引数: path(string)は許可された人工JSONです。
// 返り値: Fixture/errorは入力又は読取/型不整合です。
func LoadFixture(path string) (Fixture, error) {
	var f Fixture
	body, err := os.ReadFile(path)
	if err != nil {
		return f, err
	}
	err = json.Unmarshal(body, &f)
	return f, err
}

// FixtureTape は元イベント列を保ち、Ledgerの公開3列から通知を再構成します。
//
// 引数: f(Fixture)はGo型人工です。
// 返り値: Tape/errorは圧縮した呼出Tape又はSource通知の相違です。Source/Featuresを運転しません。
func FixtureTape(f Fixture) (Tape, error) {
	ledgers := map[string]native.Ledger{}
	routes := []CancelRoute{}
	collect := func(batches []actual.NativeBatch) {
		for _, b := range batches {
			l, ok := ledgers[b.Method]
			if !ok {
				l = native.Ledger{Method: "NK225_" + b.Method, Session: f.Session, Signals: []native.SignalRecord{}, Fills: []native.FillRecord{}, Cancellations: []native.Cancellation{}}
			}
			l.Signals = append(l.Signals, b.Delta.Signals...)
			l.Fills = append(l.Fills, b.Delta.Fills...)
			l.Cancellations = append(l.Cancellations, b.Delta.Cancellations...)
			ledgers[b.Method] = l
			for _, c := range b.Delta.Cancellations {
				routes = append(routes, CancelRoute{b.Method, c.SignalID, b.Delta.Origin, c.At, b.Delta.SourceLine})
			}
		}
	}
	for _, e := range f.Events {
		switch e.Kind {
		case "quote":
			if e.Index < 0 || e.Index >= len(f.Steps) {
				return Tape{}, fmt.Errorf("人工quote索引")
			}
			collect(f.Steps[e.Index].Batches)
		case "force":
			if e.Index < 0 || e.Index >= len(f.Timers) {
				return Tape{}, fmt.Errorf("人工force索引")
			}
			collect(f.Timers[e.Index].Batches)
		case "grid":
		default:
			return Tape{}, fmt.Errorf("人工イベント種別")
		}
	}
	index, err := NewSourceIndex(ledgers, routes)
	if err != nil {
		return Tape{}, err
	}
	t := Tape{Version: 1, Scope: "固定96Go型人工の保存Source通知とP0再現。自然Source/実原板形成は未検査", Session: f.Session, Capabilities: Capabilities(), Events: []TapeEvent{}}
	for i, e := range f.Events {
		entry := TapeEvent{Ordinal: i + 1, Kind: e.Kind}
		var original []actual.NativeBatch
		var q native.QuoteStamp
		if e.Kind == "grid" {
			if e.Index < 0 || e.Index >= len(f.Grids) || e.Index >= len(f.ChartGrids) {
				return Tape{}, fmt.Errorf("人工grid索引")
			}
			context, err := copyValue(f.ChartGrids[e.Index])
			if err != nil {
				return Tape{}, err
			}
			entry.At, entry.Context = f.Grids[e.Index], &context
			t.Events = append(t.Events, entry)
			continue
		}
		if e.Kind == "quote" {
			s := f.Steps[e.Index]
			scalar, err := ProjectQuote(s.Observation, s.SourceLine)
			if err != nil {
				return Tape{}, err
			}
			entry.At, entry.Quote = scalar.Time, &scalar
			q = scalar.stamp()
			original = s.Batches
		} else {
			s := f.Timers[e.Index]
			entry.At = s.At
			original = s.Batches
		}
		methods := []string{}
		for _, b := range original {
			methods = append(methods, b.Method)
		}
		origin := "quote"
		if e.Kind == "force" {
			origin = "timer"
		}
		reconstructed, err := index.Take(entry.At, origin, q, methods)
		if err != nil {
			return Tape{}, err
		}
		// ----------------------------------------
		// 元の全通知値と派生Beforeを、元Go型batchと厳密比較します。
		left, _ := json.Marshal(reconstructed)
		right, _ := json.Marshal(original)
		if string(left) != string(right) {
			return Tape{}, fmt.Errorf("Ledgerからの公開通知再構成が不一致: event%d", i+1)
		}
		entry.Methods, entry.NonEmpty, err = CompressBatches(reconstructed)
		if err != nil {
			return Tape{}, err
		}
		t.Events = append(t.Events, entry)
	}
	if err = index.Finish(); err != nil {
		return Tape{}, err
	}
	return t, nil
}
