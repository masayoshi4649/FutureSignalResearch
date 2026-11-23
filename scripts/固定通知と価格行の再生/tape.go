package lighttape97

import (
	"bytes"
	"encoding/json"
	"fmt"
	"reflect"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// ScalarQuote は固定96P0金融が読む当原行とATR5の11値だけです。
type ScalarQuote struct {
	Time         float64 `json:"time"`
	Received     float64 `json:"received"`
	Index        int64   `json:"index"`
	SourceLine   int64   `json:"source_line"`
	Last         float64 `json:"last"`
	Bid          float64 `json:"bid"`
	Ask          float64 `json:"ask"`
	QuoteOK      bool    `json:"quote_ok"`
	ATR          float64 `json:"atr"`
	ATRAvailable float64 `json:"atr_available"`
	ATRNominal   float64 `json:"atr_nominal"`
}

// ProjectQuote は固定96への当時Observationから参照欄だけを抜きます。
//
// 引数: o(actual.Observation)、line(int64)は元入力と物理行です。
// 返り値: ScalarQuoteは未来や不足値を補わない値複写です。
func ProjectQuote(o actual.Observation, line int64) (ScalarQuote, error) {
	if o.Reference != "NK225" || o.ATR != o.E01.ATR {
		return ScalarQuote{}, fmt.Errorf("Scalarの市場/ATR二重欄が不整合です")
	}
	return ScalarQuote{o.Time, o.Received, o.Index, line, o.Last, o.Bid, o.Ask, o.QuoteOK, o.ATR, o.E01.ATRAvailable, o.E01.ATRNominal}, nil
}

// Observation は金融専用の最小値へ戻し、未計算特徴を既知にしません。
//
// 引数: ありません。
// 返り値: actual.Observationは固定96P0の金融に限った再生入力です。
func (q ScalarQuote) Observation() actual.Observation {
	o := actual.Observation{Reference: "NK225", Time: q.Time, Received: q.Received, Index: q.Index, Last: q.Last, Bid: q.Bid, Ask: q.Ask, QuoteOK: q.QuoteOK, ATR: q.ATR}
	o.E01.ATR, o.E01.ATRAvailable, o.E01.ATRNominal = q.ATR, q.ATRAvailable, q.ATRNominal
	return o
}

// stamp は元特徴連番と物理行を金融の公開Quote型へ結びます。
//
// 引数: ありません。
// 返り値: native.QuoteStampは当原行の値です。
func (q ScalarQuote) stamp() native.QuoteStamp {
	return native.QuoteStamp{Time: q.Time, Index: q.Index, SourceLine: q.SourceLine, Last: q.Last, Bid: q.Bid, Ask: q.Ask, QuoteOK: q.QuoteOK}
}

// TapeEvent は元呼出順をordinalで保持し、gridに架空Quoteを足しません。
type TapeEvent struct {
	Ordinal  int                        `json:"ordinal"`
	Kind     string                     `json:"kind"`
	At       float64                    `json:"at"`
	Quote    *ScalarQuote               `json:"quote,omitempty"`
	Methods  []string                   `json:"methods,omitempty"`
	NonEmpty []actual.NativeBatch       `json:"non_empty,omitempty"`
	Context  *actual.TechnicalGateInput `json:"context,omitempty"`
}

// Tape は固定したSource通知/金融入力/96入口の公開文脈にだけ対応します。
type Tape struct {
	Version      int               `json:"version"`
	Scope        string            `json:"scope"`
	Session      actual.Session    `json:"session"`
	Capabilities []string          `json:"capabilities"`
	Events       []TapeEvent       `json:"events"`
	Provenance   map[string]string `json:"provenance,omitempty"`
}

// Capabilities は本prototypeの参照可能欄を版付きで限定します。
//
// 引数: ありません。
// 返り値: []stringはSource公開通知/固定96P0金融/固定AB入口の対応範囲です。
func Capabilities() []string {
	return []string{"source93.public_notifications.v1", "actual96.P0.scalar11.v1", "entry96.AB.gate3ba3c2c8.v1"}
}

// CompressBatches は空通知を捨ててもactive methodsの位置を残します。
//
// 引数: batches([]actual.NativeBatch)は元の全手法の配送順です。
// 返り値: methods([]string)/nonEmpty([]actual.NativeBatch)は順序と非空通知の値複写です。
func CompressBatches(batches []actual.NativeBatch) ([]string, []actual.NativeBatch, error) {
	methods := []string{}
	nonEmpty := []actual.NativeBatch{}
	for _, b := range batches {
		methods = append(methods, b.Method)
		if len(b.Delta.Signals)+len(b.Delta.Fills)+len(b.Delta.Cancellations) > 0 {
			v, err := copyValue(b)
			if err != nil {
				return nil, nil, err
			}
			nonEmpty = append(nonEmpty, v)
		}
	}
	return methods, nonEmpty, nil
}

// RestoreBatches は空batchを元の手法順へ復元します。
//
// 引数: event(TapeEvent)、last(map[string]int64)は元配送と各手法の直前SourceLineです。
// 返り値: []actual.NativeBatch/errorは全手法通知又は重複/未結合です。
func RestoreBatches(event TapeEvent, last map[string]int64) ([]actual.NativeBatch, error) {
	origin := "quote"
	if event.Kind == "force" {
		origin = "timer"
	}
	stored := map[string]actual.NativeBatch{}
	for _, b := range event.NonEmpty {
		if _, ok := stored[b.Method]; ok {
			return nil, fmt.Errorf("非空手法重複")
		}
		stored[b.Method] = b
	}
	seen := map[string]bool{}
	out := []actual.NativeBatch{}
	for _, m := range event.Methods {
		if seen[m] {
			return nil, fmt.Errorf("全手法順に重複")
		}
		seen[m] = true
		line := last[m]
		if event.Kind == "quote" {
			if event.Quote == nil {
				return nil, fmt.Errorf("quote本体欠落")
			}
			line = event.Quote.SourceLine
			last[m] = line
		}
		b, ok := stored[m]
		if !ok {
			b = actual.NativeBatch{Method: m, Delta: empty(event.At, origin, line)}
		}
		if b.Delta.At != event.At || b.Delta.Origin != origin || b.Delta.SourceLine != line {
			return nil, fmt.Errorf("非空通知の時計/位相/物理行が不一致")
		}
		out = append(out, b)
	}
	for m := range stored {
		if !seen[m] {
			return nil, fmt.Errorf("非空通知の手法が生成順へ未結合")
		}
	}
	return out, nil
}

// actorConfigs は元96のG0/ABだけを元key/IDで作り、出口はP0のままです。
//
// 引数: session(actual.Session)は当場時計です。
// 返り値: []actual.ActorConfigは八口座。Hや新条件を含みません。
func actorConfigs(session actual.Session) []actual.ActorConfig {
	out := []actual.ActorConfig{}
	for _, p := range []string{"", "AB"} {
		for _, c := range []float64{0, 5} {
			for _, d := range []int{0, 1} {
				out = append(out, actual.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen, GatePolicy: p, SlipPts: c, DelaySeconds: d})
			}
		}
	}
	return out
}

// Replay は保存Source通知を固定96へ配送し、入口だけを各金融の現在余力で再評価します。
//
// 引数: tape(Tape)は固定公開入力です。
// 返り値: map[string]actual.ActualResult/errorは同P0八口座の再現。新しい出口損益は計算しません。
func Replay(tape Tape) (map[string]actual.ActualResult, error) {
	if tape.Version != 1 || tape.Scope == "" || !reflect.DeepEqual(tape.Capabilities, Capabilities()) {
		return nil, fmt.Errorf("Tape版不明")
	}
	actors := []*actual.ActualBook{}
	policies := []string{}
	for _, cfg := range actorConfigs(tape.Session) {
		b, err := actual.NewActualBook(tape.Session, cfg)
		if err != nil {
			return nil, err
		}
		actors = append(actors, b)
		policies = append(policies, cfg.GatePolicy)
	}
	last := map[string]int64{}
	previous := 0.0
	for i, e := range tape.Events {
		if e.Ordinal != i+1 || e.At < previous {
			return nil, fmt.Errorf("Tapeの呼出順が不正")
		}
		previous = e.At
		switch e.Kind {
		case "quote", "force":
			batches, err := RestoreBatches(e, last)
			if err != nil {
				return nil, err
			}
			before, _ := json.Marshal(batches)
			for _, actor := range actors {
				if e.Kind == "quote" {
					if e.Quote == nil || e.Quote.Time != e.At {
						return nil, fmt.Errorf("Quote時計不整合")
					}
					err = actor.OnNativeStep(e.Quote.Observation(), e.Quote.SourceLine, batches)
				} else {
					err = actor.OnNativeForce(e.At, batches)
				}
				if err != nil {
					return nil, err
				}
			}
			after, _ := json.Marshal(batches)
			if !bytes.Equal(before, after) {
				return nil, fmt.Errorf("金融が共用通知を書換え")
			}
		case "grid":
			if e.Quote != nil || e.Context == nil || e.Context.At != e.At || len(e.NonEmpty)+len(e.Methods) != 0 {
				return nil, fmt.Errorf("gridへ架空気配/Source配送を混入")
			}
			for i, actor := range actors {
				var gate actual.EntryGate
				if policies[i] != "" {
					policy := policies[i]
					gate = func(c actual.EntryCandidate) (actual.GateDecision, error) {
						a, err := actual.AssessTechnicalGate(*e.Context, c, policy)
						return a.Decision, err
					}
				}
				if err := actor.OnEntryGridWithGate(e.At, gate); err != nil {
					return nil, err
				}
			}
		default:
			return nil, fmt.Errorf("Tape種別不明")
		}
	}
	out := map[string]actual.ActualResult{}
	for _, actor := range actors {
		r, err := actor.Finish()
		if err != nil {
			return nil, err
		}
		out[r.Key] = r
	}
	return out, nil
}
