// 由来: scripts/FAR背景と勢いと数量の再生/factory.go
// 由来SHA256: 2e57b4244da5d8b2b3f08789ce6f7050f14ce108aaba9db63b2e9f1426bda77c
package grossport100

import (
	"encoding/json"
	"fmt"

	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	entry "github.com/masayoshi4649/SessionTradeExecuter/minigrossguard100"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

type GateAssessmentRecord = port.GateAssessmentRecord

// ProtectionFactory は本名E3S固定でP0/H0/HGの保護だけを切り替えます。
type ProtectionFactory struct{ Records *[]GateAssessmentRecord }

// Configurations はP0/H0/HGの3保護と費用・遅延を列挙します。
//
// 引数: ありません。
// 返り値: []port.ConfigはE3S固定の12独立設定です。Riskへ別の意味を入れません。
func Configurations() []port.Config {
	out := []port.Config{}
	for _, harvest := range []string{"", "H0", "HG"} {
		for _, cost := range []float64{0, 5} {
			for _, delay := range []int{0, 1} {
				out = append(out, port.Config{Gate: "E3S", Harvest: harvest, Slip: cost, Delay: delay})
			}
		}
	}
	return out
}

// New は当場の新12口座の一つを生成します。
//
// 引数: session(native.Session)、cfg(port.Config)は旧時計の場と明示設定です。
// 返り値: port.Actor/errorは新金融wrapper又は設定差です。
func (f ProtectionFactory) New(session native.Session, cfg port.Config) (port.Actor, error) {
	if f.Records == nil || cfg.Gate != "E3S" || (cfg.Harvest != "" && cfg.Harvest != "H0" && cfg.Harvest != "HG") {
		return nil, fmt.Errorf("100factoryはE3Sと空/H0/HGだけです")
	}
	b, err := entry.NewActualBook(session, entry.ActorConfig{Policy: "P0", EntryTiming: "B5Q", USOpen: session.USOpen, HarvestPolicy: cfg.Harvest, GatePolicy: cfg.Gate, SlipPts: cfg.Slip, DelaySeconds: cfg.Delay})
	if err != nil {
		return nil, err
	}
	return &entryActor{book: b, key: b.Snapshot().Key, gate: cfg.Gate, records: f.Records}, nil
}

type entryActor struct {
	book      *entry.ActualBook
	key, gate string
	callbacks int
	records   *[]GateAssessmentRecord
}

// ConvertBatches は公開NativeBatchの名前付き配列を全field対応します。
//
// 引数: batches([]actual.NativeBatch)は元順序の公開通知です。
// 返り値: []entry.NativeBatchは同じDeltaです。nilと空配列の区別も維持します。
func ConvertBatches(batches []actual.NativeBatch) []entry.NativeBatch {
	if batches == nil {
		return nil
	}
	out := make([]entry.NativeBatch, len(batches))
	for i, b := range batches {
		out[i] = entry.NativeBatch{Method: b.Method, Delta: b.Delta}
	}
	return out
}

// ConvertCandidate は金融候補全fieldを保存・純式の共通型へ対応します。
//
// 引数: c(entry.EntryCandidate)は旧適格性と現余力を満たした候補です。
// 返り値: actual.EntryCandidateはSource/方向/量/時計/原行を変えない値です。
func ConvertCandidate(c entry.EntryCandidate) actual.EntryCandidate {
	s := c.Source
	return actual.EntryCandidate{Ordinal: c.Ordinal, At: c.At, Side: c.Side, Quote: c.Quote, Available: c.Available, Quantity: c.Quantity,
		Source: actual.SourceIdentity{Method: s.Method, SignalID: s.SignalID, Kind: s.Kind, Parent: s.Parent, SourceID: s.SourceID, QuantityMicro: s.QuantityMicro, BirthQuantity: s.BirthQuantity, BirthTime: s.BirthTime, BirthQuote: s.BirthQuote}}
}

// Step は当原行Scalarと元Source通知を新金融へ渡します。
//
// 引数: o(native.Observation)、line(int64)、b([]actual.NativeBatch)は公開値です。
// 返り値: errorは入力又は金融の不整合です。元Source判断は実行しません。
func (a *entryActor) Step(o native.Observation, line int64, b []actual.NativeBatch) error {
	return a.book.OnNativeStep(o, line, ConvertBatches(b))
}

// Force は元timer通知だけを同じ時計で新金融へ渡します。
//
// 引数: at(float64)、b([]actual.NativeBatch)は公開時計と通知です。
// 返り値: errorは金融の不整合です。気配を更新・再時刻化しません。
func (a *entryActor) Force(at float64, b []actual.NativeBatch) error {
	return a.book.OnNativeForce(at, ConvertBatches(b))
}

// Grid は当候補を停止E3Sで再評価し、本名の全checkを保存します。
//
// 引数: at(float64)、input(*actual.TechnicalGateInput)は当枠の公開文脈です。
// 返り値: errorは文脈・純式・金融の不整合です。旧採否を転記しません。
func (a *entryActor) Grid(at float64, input *actual.TechnicalGateInput) error {
	if input == nil || input.At != at {
		return fmt.Errorf("100当定時の技法文脈が欠落")
	}
	var callback entry.EntryGate
	if a.gate != "" {
		callback = func(c entry.EntryCandidate) (entry.GateDecision, error) {
			a.callbacks++
			v, err := entry.AssessEntryTechnical(*input, c, a.gate)
			if err != nil {
				return entry.GateDecision{}, err
			}
			current := ConvertCandidate(c)
			*a.records = append(*a.records, GateAssessmentRecord{Key: a.key, Ordinal: c.Ordinal, Source: current.Source, Candidate: current, Assessment: v})
			d := v.Decision
			return entry.GateDecision{Policy: d.Policy, SnapshotID: d.SnapshotID, Known: d.Known, Allowed: d.Allowed, Role: d.Role, Reason: d.Reason}, nil
		}
	}
	return a.book.OnEntryGridWithGate(at, callback)
}

// Snapshot は人工全時点対照用の金融全JSONを返します。
//
// 引数: ありません。
// 返り値: json.RawMessage/errorは現在全fieldです。productionでは原行ごとに呼びません。
func (a *entryActor) Snapshot() (json.RawMessage, error) { return json.Marshal(a.book.Snapshot()) }

// Finish は新金融を完結させ全結果を返します。
//
// 引数: ありません。
// 返り値: string/json.RawMessage/errorはKeyと最終全JSON又は未完です。
func (a *entryActor) Finish() (string, json.RawMessage, error) {
	r, err := a.book.Finish()
	if err != nil {
		return "", nil, err
	}
	body, err := json.Marshal(r)
	return r.Key, body, err
}

// Callbacks は実金融が要求した現在純式の回数を返します。
//
// 引数: ありません。
// 返り値: intは実callback数です。候補なしを仮想的に追加しません。
func (a *entryActor) Callbacks() int { return a.callbacks }
