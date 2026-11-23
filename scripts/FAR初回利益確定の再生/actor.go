// Package actorport97 は停止済みTapeと金融の名前付き型だけを接続します。
package actorport97

import (
	"encoding/json"
	"fmt"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	harvest "github.com/masayoshi4649/SessionTradeExecuter/miniharvest"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// Actor は同じ公開入力を受ける金融APIの小さい共通境界です。
type Actor interface {
	Step(native.Observation, int64, []actual.NativeBatch) error
	Force(float64, []actual.NativeBatch) error
	Grid(float64, *actual.TechnicalGateInput) error
	Snapshot() (json.RawMessage, error)
	Finish() (string, json.RawMessage, error)
	Callbacks() int
}

// Config は金融の選択を入口から分離します。
type Config struct {
	Gate    string
	Harvest string
	Slip    float64
	Delay   int
}

// Factory は同一Session/費用/入口から実口座を生成します。
type Factory interface {
	New(native.Session, Config) (Actor, error)
}

// Fixed96 は旧96金融の対照を生成します。
type Fixed96 struct{}

// New は旧96を新しい口座として生成します。
//
// 引数: session(native.Session)、cfg(Config)は明示した時計と政策です。
// 返り値: Actor/errorは旧口座又は未対応の出口設定です。
func (Fixed96) New(session native.Session, cfg Config) (Actor, error) {
	if cfg.Harvest != "" {
		return nil, fmt.Errorf("旧96へ新しい出口は渡せません")
	}
	b, err := actual.NewActualBook(session, actual.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen, GatePolicy: cfg.Gate, SlipPts: cfg.Slip, DelaySeconds: cfg.Delay})
	return &oldActor{book: b, gate: cfg.Gate}, err
}

// Harvest97 は新金融の空設定/H0を生成します。
type Harvest97 struct{}

// New は旧入力APIと同形の97口座を生成します。
//
// 引数: session(native.Session)、cfg(Config)は明示した時計と政策です。
// 返り値: Actor/errorは新口座又は不正な設定です。
func (Harvest97) New(session native.Session, cfg Config) (Actor, error) {
	b, err := harvest.NewActualBook(session, harvest.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen, GatePolicy: cfg.Gate, HarvestPolicy: cfg.Harvest, SlipPts: cfg.Slip, DelaySeconds: cfg.Delay})
	return &newActor{book: b, gate: cfg.Gate}, err
}

type oldActor struct {
	book      *actual.ActualBook
	gate      string
	callbacks int
}
type newActor struct {
	book      *harvest.ActualBook
	gate      string
	callbacks int
}

// ConvertBatches はSource通知を列順・全fieldを保ったまま明示変換します。
//
// 引数: batches([]actual.NativeBatch)は空通知も含む全配送です。
// 返り値: []harvest.NativeBatchは同じnative.StepResultを持つ新しい配列です。
func ConvertBatches(batches []actual.NativeBatch) []harvest.NativeBatch {
	out := make([]harvest.NativeBatch, len(batches))
	for i, b := range batches {
		out[i] = harvest.NativeBatch{Method: b.Method, Delta: b.Delta}
	}
	return out
}

// ConvertCandidate は現在口座が計算した候補を固定96純判定の型へ結びます。
//
// 引数: c(harvest.EntryCandidate)は97の現在余力/要求枚数を持つ候補です。
// 返り値: actual.EntryCandidateはSourceIdentityを含む全fieldの明示変換です。
func ConvertCandidate(c harvest.EntryCandidate) actual.EntryCandidate {
	return actual.EntryCandidate{Ordinal: c.Ordinal, At: c.At, Side: c.Side, Source: actual.SourceIdentity(c.Source), Quote: c.Quote, Available: c.Available, Quantity: c.Quantity}
}

// Step は旧金融へ当原行を渡します。
//
// 引数: o(native.Observation)、line(int64)、b([]actual.NativeBatch)は原行と公開通知です。
// 返り値: errorは金融契約の不整合です。
func (a *oldActor) Step(o native.Observation, line int64, b []actual.NativeBatch) error {
	return a.book.OnNativeStep(o, line, b)
}

// Step は97金融へ同じ原行を渡します。
//
// 引数: o(native.Observation)、line(int64)、b([]actual.NativeBatch)は原行と公開通知です。
// 返り値: errorは金融契約の不整合です。
func (a *newActor) Step(o native.Observation, line int64, b []actual.NativeBatch) error {
	return a.book.OnNativeStep(o, line, ConvertBatches(b))
}

// Force は旧金融へ元のtimer通知を渡します。
//
// 引数: at(float64)、b([]actual.NativeBatch)はForce時計と通知です。
// 返り値: errorは金融契約の不整合です。
func (a *oldActor) Force(at float64, b []actual.NativeBatch) error {
	return a.book.OnNativeForce(at, b)
}

// Force は97金融へ元のtimer通知を渡します。
//
// 引数: at(float64)、b([]actual.NativeBatch)はForce時計と通知です。
// 返り値: errorは金融契約の不整合です。
func (a *newActor) Force(at float64, b []actual.NativeBatch) error {
	return a.book.OnNativeForce(at, ConvertBatches(b))
}

// Grid は現在の旧候補を固定96純式へ評価させます。
//
// 引数: at(float64)、input(*actual.TechnicalGateInput)は保存公開時計と全文文脈です。
// 返り値: errorは欠落又は金融/技法契約の不整合です。
func (a *oldActor) Grid(at float64, input *actual.TechnicalGateInput) error {
	if input == nil || input.At != at {
		return fmt.Errorf("定時公開文脈の欠落")
	}
	var gate actual.EntryGate
	if a.gate != "" {
		gate = func(c actual.EntryCandidate) (actual.GateDecision, error) {
			a.callbacks++
			v, err := actual.AssessTechnicalGate(*input, c, a.gate)
			return v.Decision, err
		}
	}
	return a.book.OnEntryGridWithGate(at, gate)
}

// Grid は現在の97候補を型変換し固定96純式で再評価します。
//
// 引数: at(float64)、input(*actual.TechnicalGateInput)は保存公開時計と全文文脈です。
// 返り値: errorは欠落又は金融/技法契約の不整合です。旧採否は入力しません。
func (a *newActor) Grid(at float64, input *actual.TechnicalGateInput) error {
	if input == nil || input.At != at {
		return fmt.Errorf("定時公開文脈の欠落")
	}
	var gate harvest.EntryGate
	if a.gate != "" {
		gate = func(c harvest.EntryCandidate) (harvest.GateDecision, error) {
			a.callbacks++
			v, err := actual.AssessTechnicalGate(*input, ConvertCandidate(c), a.gate)
			return harvest.GateDecision(v.Decision), err
		}
	}
	return a.book.OnEntryGridWithGate(at, gate)
}

// Snapshot は旧金融の全JSONを返します。
//
// 引数: ありません。
// 返り値: json.RawMessage/errorは全fieldの現在値です。
func (a *oldActor) Snapshot() (json.RawMessage, error) { return json.Marshal(a.book.Snapshot()) }

// Snapshot は97金融の全JSONを返します。
//
// 引数: ありません。
// 返り値: json.RawMessage/errorは全fieldの現在値です。
func (a *newActor) Snapshot() (json.RawMessage, error) { return json.Marshal(a.book.Snapshot()) }

// Finish は旧金融をEOFで完結させます。
//
// 引数: ありません。
// 返り値: string/json.RawMessage/errorはkeyと全field又は未完です。
func (a *oldActor) Finish() (string, json.RawMessage, error) {
	r, err := a.book.Finish()
	if err != nil {
		return "", nil, err
	}
	b, err := json.Marshal(r)
	return r.Key, b, err
}

// Finish は97金融をEOFで完結させます。
//
// 引数: ありません。
// 返り値: string/json.RawMessage/errorはkeyと全field又は未完です。
func (a *newActor) Finish() (string, json.RawMessage, error) {
	r, err := a.book.Finish()
	if err != nil {
		return "", nil, err
	}
	b, err := json.Marshal(r)
	return r.Key, b, err
}

// Callbacks は旧金融から実際に要求された技法評価回数を返します。
//
// 引数: ありません。
// 返り値: intは実呼出数です。
func (a *oldActor) Callbacks() int { return a.callbacks }

// Callbacks は97金融から実際に要求された技法評価回数を返します。
//
// 引数: ありません。
// 返り値: intは実呼出数です。
func (a *newActor) Callbacks() int { return a.callbacks }
