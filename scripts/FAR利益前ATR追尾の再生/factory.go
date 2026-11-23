package riskport98

import (
	"encoding/json"
	"fmt"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
	risk "github.com/masayoshi4649/SessionTradeExecuter/minirisk98"
)

type GateAssessmentRecord = port.GateAssessmentRecord

// RiskFactory は固定H0の金融へrisk政策だけを独立に設定します。
type RiskFactory struct {
	Policy  string
	Records *[]GateAssessmentRecord
	Order   *[]string
}

// New は旧97のConfigを偽装せず新しい98口座を生成します。
//
// 引数: session(native.Session)、cfg(port.Config)は明示したH0/入口/費用/遅延です。
// 返り値: port.Actor/errorは新金融wrapper又は設定不整合です。
func (f RiskFactory) New(session native.Session, cfg port.Config) (port.Actor, error) {
	if f.Records == nil || cfg.Harvest != "H0" || (cfg.Gate != "" && cfg.Gate != "AB") || (f.Policy != "" && f.Policy != "R05" && f.Policy != "R10") {
		return nil, fmt.Errorf("98factoryは固定H0/技法空AB/risk空R05R10だけです")
	}
	b, err := risk.NewActualBook(session, risk.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen, HarvestPolicy: "H0", RiskPolicy: f.Policy, GatePolicy: cfg.Gate, SlipPts: cfg.Slip, DelaySeconds: cfg.Delay})
	if err != nil {
		return nil, err
	}
	key := b.Snapshot().Key
	if f.Order != nil {
		*f.Order = append(*f.Order, key)
	}
	return &riskActor{book: b, key: key, gate: cfg.Gate, records: f.Records}, nil
}

type riskActor struct {
	book      *risk.ActualBook
	key, gate string
	callbacks int
	records   *[]GateAssessmentRecord
}

// ConvertBatches は名前付き外配列だけを全field明示変換します。
//
// 引数: batches([]actual.NativeBatch)は空通知も含む元順序です。
// 返り値: []risk.NativeBatchは同じnative.StepResultを持つ独立した外配列です。
func ConvertBatches(batches []actual.NativeBatch) []risk.NativeBatch {
	out := make([]risk.NativeBatch, len(batches))
	for i, b := range batches {
		out[i] = risk.NativeBatch{Method: b.Method, Delta: b.Delta}
	}
	return out
}

// ConvertCandidate は現在98候補を固定96純技法へ全field渡します。
//
// 引数: c(risk.EntryCandidate)は当時の実余力/要求量を持つ候補です。
// 返り値: actual.EntryCandidateはSourceIdentityを明示変換した同値です。
func ConvertCandidate(c risk.EntryCandidate) actual.EntryCandidate {
	return actual.EntryCandidate{Ordinal: c.Ordinal, At: c.At, Side: c.Side, Source: actual.SourceIdentity(c.Source), Quote: c.Quote, Available: c.Available, Quantity: c.Quantity}
}

// Step は当原行ScalarとSource通知を98へ渡します。
//
// 引数: o(native.Observation)、line(int64)、b([]actual.NativeBatch)は公開原行と通知です。
// 返り値: errorは金融契約の不整合です。
func (a *riskActor) Step(o native.Observation, line int64, b []actual.NativeBatch) error {
	return a.book.OnNativeStep(o, line, ConvertBatches(b))
}

// Force は元timer通知を98へ渡します。
//
// 引数: at(float64)、b([]actual.NativeBatch)は元時計と通知です。
// 返り値: errorは金融契約の不整合です。
func (a *riskActor) Force(at float64, b []actual.NativeBatch) error {
	return a.book.OnNativeForce(at, ConvertBatches(b))
}

// Grid は各98の現在候補を固定96純式へ一度評価し全checkを保存します。
//
// 引数: at(float64)、input(*actual.TechnicalGateInput)は当時の保存済み公開文脈です。
// 返り値: errorは時計/純式/金融契約の不整合です。旧採否は転記しません。
func (a *riskActor) Grid(at float64, input *actual.TechnicalGateInput) error {
	if input == nil || input.At != at {
		return fmt.Errorf("当定時の技法文脈が欠落")
	}
	var callback risk.EntryGate
	if a.gate != "" {
		callback = func(candidate risk.EntryCandidate) (risk.GateDecision, error) {
			a.callbacks++
			current := ConvertCandidate(candidate)
			v, err := actual.AssessTechnicalGate(*input, current, a.gate)
			if err != nil {
				return risk.GateDecision{}, err
			}
			*a.records = append(*a.records, GateAssessmentRecord{Key: a.key, Ordinal: current.Ordinal, Source: current.Source, Candidate: current, Assessment: v})
			return risk.GateDecision(v.Decision), nil
		}
	}
	return a.book.OnEntryGridWithGate(at, callback)
}

// Snapshot は人工の全時点検査用に98全JSONを返します。
//
// 引数: ありません。
// 返り値: json.RawMessage/errorは全field現在値です。
func (a *riskActor) Snapshot() (json.RawMessage, error) { return json.Marshal(a.book.Snapshot()) }

// Finish は98を完結させ全JSONを返します。
//
// 引数: ありません。
// 返り値: string/json.RawMessage/errorはkeyと全field又は未完です。
func (a *riskActor) Finish() (string, json.RawMessage, error) {
	r, err := a.book.Finish()
	if err != nil {
		return "", nil, err
	}
	body, err := json.Marshal(r)
	return r.Key, body, err
}

// Callbacks はこの金融から実際に要求された純技法評価数を返します。
//
// 引数: ありません。
// 返り値: intは実呼出数です。
func (a *riskActor) Callbacks() int { return a.callbacks }
