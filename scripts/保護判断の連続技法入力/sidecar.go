// Package continuous101 は人工の公開入力だけから所有なしの連続技法を保存します。
package continuous101

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"reflect"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	oldtape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	chart "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

type Row struct {
	Board        strategy.Board `json:"board"`
	PhysicalLine int64          `json:"physical_line"`
}
type CandleEvent struct {
	Reference string          `json:"reference"`
	Interval  int             `json:"interval"`
	Candle    strategy.Candle `json:"candle"`
	At        float64         `json:"at"`
}
type Request struct {
	Session strategy.Session `json:"session"`
	Scene   warm.Scene       `json:"scene"`
	Rows    []Row            `json:"rows"`
	Candles []CandleEvent    `json:"candles"`
	Grids   []float64        `json:"grids"`
}
type Identity struct {
	Market        string  `json:"market"`
	Time          float64 `json:"time"`
	PhysicalLine  int64   `json:"physical_line"`
	AllIndex      int64   `json:"market_all_index"`
	FeaturesIndex *int64  `json:"features_index"`
	MergeOrdinal  int     `json:"merge_ordinal"`
}

// Payload はSnapshotの変化が少ない公開値で、私有Seedの復元には使いません。
type Payload struct {
	Scene   warm.Scene       `json:"scene"`
	Chart   far82.ChartView  `json:"chart"`
	Three   warm.BarEvidence `json:"three"`
	Fifteen warm.BarEvidence `json:"fifteen"`
	Carried bool             `json:"carried_numeric_seed"`
}
type State struct {
	PayloadSHA  string           `json:"payload_sha256"`
	At          float64          `json:"at"`
	HasObserved bool             `json:"has_observed_clock"`
	Observed    float64          `json:"observed_clock"`
	HasLast     bool             `json:"has_last_input"`
	Last        warm.SourceStamp `json:"last_input"`
	Invalidated float64          `json:"invalidated_at"`
	Sealed      bool             `json:"sealed"`
}
type RawContext struct {
	Ordinal  int                   `json:"positive_nk_ordinal"`
	Identity Identity              `json:"identity"`
	Scalar   oldtape.ScalarQuote   `json:"scalar"`
	Current  far82.CurrentEvidence `json:"current"`
	Chart    State                 `json:"chart_state"`
	Recent3  []State               `json:"recent3_refs"`
}
type Trace struct {
	Kind     string    `json:"kind"`
	At       float64   `json:"at"`
	Identity *Identity `json:"identity,omitempty"`
	Chart    State     `json:"chart_state"`
}
type Record struct {
	TapeOrdinal int         `json:"tape_ordinal,omitempty"`
	Kind        string      `json:"kind"`
	Row         *RawContext `json:"row,omitempty"`
	Control     *Trace      `json:"control,omitempty"`
}

// copyCurrent は旧JSON経路の空窓nil化を保ち、非空の可変窓mapを独立複写します。
//
// 引数: c(far82.CurrentEvidence)は固定81/82公開値です。
// 返り値: far82.CurrentEvidenceはomitempty空窓をnilへ揃えた独立公開値です。
func copyCurrent(c far82.CurrentEvidence) far82.CurrentEvidence {
	for _, p := range []*far81.CurrentSupport{&c.Buy, &c.Sell} {
		if len(p.Windows) == 0 {
			p.Windows = nil
			continue
		}
		if p.Windows != nil {
			m := make(map[string]far81.CurrentSupportWindow, len(p.Windows))
			for k, v := range p.Windows {
				m[k] = v
			}
			p.Windows = m
		}
	}
	return c
}

type Sink func(Record) error
type Binding struct {
	TapeOrdinal    int    `json:"tape_ordinal"`
	Kind           string `json:"kind"`
	SidecarOrdinal int    `json:"sidecar_ordinal"`
}
type LegacyMatch struct {
	LegacySHA string    `json:"legacy_tape_canonical_sha256"`
	Bindings  []Binding `json:"bindings"`
	Quotes    int       `json:"quotes"`
	Grids     int       `json:"grids"`
	Events    int       `json:"events"`
}
type Sidecar struct {
	Version              int                        `json:"version"`
	Scope                string                     `json:"scope"`
	Session              strategy.Session           `json:"session"`
	SourceReexecuted     bool                       `json:"source_reexecuted"`
	FinancialExecuted    bool                       `json:"financial_executed"`
	FeaturesRecomputed   bool                       `json:"features_recomputed"`
	ChartsRecomputed     bool                       `json:"charts_recomputed"`
	FeatureConfig        json.RawMessage            `json:"feature_config"`
	Streamed             bool                       `json:"streamed"`
	RowCount             int                        `json:"row_count"`
	TraceCount           int                        `json:"trace_count"`
	Payloads             map[string]Payload         `json:"chart_payloads"`
	Rows                 []RawContext               `json:"rows"`
	Grids                []chart.TechnicalGateInput `json:"grids"`
	Trace                []Trace                    `json:"trace"`
	Ending               State                      `json:"ending"`
	LegacyEndingCompared bool                       `json:"legacy_ending_compared"`
	SkippedGrids         []float64                  `json:"skipped_grids"`
	LegacySHA            string                     `json:"legacy_tape_canonical_sha256,omitempty"`
	Provenance           map[string]string          `json:"provenance,omitempty"`
	Bindings             []Binding                  `json:"legacy_bindings,omitempty"`
}

// copyValue は公開JSON値のmap/slice共有を切ります。
//
// 引数: v(T)は公開値です。
// 返り値: T/errorは独立複写、又は非有限値等のJSON不正です。
func copyValue[T any](v T) (T, error) {
	var out T
	raw, e := json.Marshal(v)
	if e != nil {
		return out, e
	}
	e = json.Unmarshal(raw, &out)
	return out, e
}

// pack は公開Snapshotを辞書と当時stateへ無損失で分けます。
//
// 引数: s(warm.Snapshot)、dict(map[string]Payload)は当時値と保存辞書です。
// 返り値: State/errorは内容SHA参照、又は公開値不正です。
func pack(s warm.Snapshot, dict map[string]Payload) (State, error) {
	p := Payload{s.Scene, s.Chart, s.Three, s.Fifteen, s.CarriedNumericSeed}
	raw, e := json.Marshal(p)
	if e != nil {
		return State{}, e
	}
	sum := sha256.Sum256(raw)
	key := hex.EncodeToString(sum[:])
	dict[key] = p
	return State{key, s.At, s.HasObservedClock, s.ObservedClock, s.HasLastInput, s.LastInput, s.InvalidatedAt, s.Sealed}, nil
}

// Materialize は辞書の指紋を検査し公開Snapshot全文を復元します。
//
// 引数: out(Sidecar)、s(State)は辞書と原行状態です。
// 返り値: warm.Snapshot/errorは無損失復元値、又は欠落/辞書改変です。
func Materialize(out Sidecar, s State) (warm.Snapshot, error) {
	p, ok := out.Payloads[s.PayloadSHA]
	if !ok {
		return warm.Snapshot{}, fmt.Errorf("辞書参照欠落")
	}
	raw, e := json.Marshal(p)
	if e != nil {
		return warm.Snapshot{}, e
	}
	sum := sha256.Sum256(raw)
	if hex.EncodeToString(sum[:]) != s.PayloadSHA {
		return warm.Snapshot{}, fmt.Errorf("辞書指紋不一致")
	}
	return warm.Snapshot{Scene: p.Scene, At: s.At, HasObservedClock: s.HasObserved, ObservedClock: s.Observed, HasLastInput: s.HasLast, LastInput: s.Last, InvalidatedAt: s.Invalidated, Chart: p.Chart, Three: p.Three, Fifteen: p.Fifteen, CarriedNumericSeed: p.Carried, Sealed: s.Sealed}, nil
}

// BindLegacy は旧TapeのScalarと全Gridを検査し対応ordinalだけを返します。
//
// 引数: value(Sidecar)、t(oldtape.Tape)は新入力と固定旧入力です。
// 返り値: LegacyMatch/errorは小型の対応証拠、又は不足/改変です。入力全文を複写せずSourceも実行しません。
func BindLegacy(value Sidecar, t oldtape.Tape) (LegacyMatch, error) {
	if value.Session != t.Session || t.Version != 1 {
		return LegacyMatch{}, fmt.Errorf("旧場/版不一致")
	}
	out := LegacyMatch{Bindings: []Binding{}}
	ri, gi := 0, 0
	prior := 0.0
	for i, ev := range t.Events {
		if ev.Ordinal != i+1 || ev.At < prior {
			return LegacyMatch{}, fmt.Errorf("旧ordinal/時計逆行")
		}
		prior = ev.At
		if ev.Kind == "quote" {
			if ev.Quote == nil || ev.Quote.Time != ev.At || ri >= len(value.Rows) || !reflect.DeepEqual(*ev.Quote, value.Rows[ri].Scalar) {
				return LegacyMatch{}, fmt.Errorf("旧Scalar11不一致")
			}
			out.Bindings = append(out.Bindings, Binding{ev.Ordinal, "quote", ri + 1})
			ri++
		} else if ev.Kind == "grid" {
			if ev.Quote != nil || len(ev.Methods)+len(ev.NonEmpty) != 0 || ev.Context == nil || ev.At != ev.Context.At || gi >= len(value.Grids) || !reflect.DeepEqual(*ev.Context, value.Grids[gi]) {
				return LegacyMatch{}, fmt.Errorf("旧5分Input不一致")
			}
			out.Bindings = append(out.Bindings, Binding{ev.Ordinal, "grid", gi + 1})
			gi++
		} else if ev.Kind != "force" {
			return LegacyMatch{}, fmt.Errorf("旧種別不正")
		}
	}
	if ri != len(value.Rows) || gi != len(value.Grids) {
		return LegacyMatch{}, fmt.Errorf("旧原行/枠の不足")
	}
	raw, e := json.Marshal(t)
	if e != nil {
		return LegacyMatch{}, e
	}
	sum := sha256.Sum256(raw)
	out.LegacySHA = hex.EncodeToString(sum[:])
	out.Quotes, out.Grids, out.Events = ri, gi, len(t.Events)
	return out, nil
}
