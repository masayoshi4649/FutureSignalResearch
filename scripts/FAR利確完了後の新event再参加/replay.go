// 91派生元: scripts/FAR利益床と収穫配分の比較/replay.go
// 91派生元SHA256: e63d70728b57859b9dbddce9965a5d9237183d2ad9d386ed5dac801dd0f324a0
// 89派生元: scripts/FAR背景維持と押戻し再開/replay.go
// 89派生元SHA256: 875d9b63766beb6a0db12b40f132358b6f43408f274b86b3a0678d3c2bd9cd44

// 88派生元: scripts/FAR参照玉と可変数量の比較/replay.go
// 88派生元SHA256: b3c1a54ca1ea357bb92186997e9a535ec06536b186eaae0926eb7be210ce80c8
// Sourceと純入口は固定87/88を再用し、金融は固定89からの再参加最小派生へ接続します。

// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/replay.go
// 87派生元SHA256: 47244d36af7bc4db13848fca7abcb8c156c1dc5c29ed16cd816e97ab0b1ae09e

package far91

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash"
	"math"
	"reflect"
	"sort"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

type technicalHashes struct{ actual, event hash.Hash }

type replayClock struct {
	At          float64
	Three, Core bool
}

// mergedClocks は追加3分公開と旧core時計を同時計でも順序付きでまとめます。
//
// 引数: session(strategy.Session)、core([]float64)は旧場と旧時計列です。
// 返り値: []replayClockは3分公開を先に処理できる昇順の合成時計です。
func mergedClocks(session strategy.Session, core []float64) []replayClock {
	rows := map[float64]replayClock{}
	for _, at := range core {
		rows[at] = replayClock{At: at, Core: true}
	}
	for at := session.Start + 180; at <= session.End; at += 180 {
		row := rows[at]
		row.At, row.Three = at, true
		rows[at] = row
	}
	out := make([]replayClock, 0, len(rows))
	for _, row := range rows {
		out = append(out, row)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].At < out[j].At })
	return out
}

// eventEpoch は独立履歴だけにSource時間窓の有効範囲を与えます。
//
// 引数: at(float64)は公開時刻です。
// 返り値: window(string)/epoch(float64)は窓名と開始時計です。
func (r *replayRuntime) eventEpoch(at float64) (string, float64) {
	if at >= r.session.ForceClose {
		return "場末", r.session.ForceClose
	}
	if r.session.Kind == "Day" {
		return "D164_15", r.session.Start
	}
	if at < r.session.USOpen-900 {
		return "P164_06", r.session.Start
	}
	if at < r.session.USOpen+900 {
		return "静観", r.session.USOpen - 900
	}
	return "U165_03", r.session.USOpen + 900
}

// recordEvent は全呼出ordinalを進め、新足又は失効入力だけを疎に保存します。
//
// 引数: at(float64)、origin(string)、afterEOF(bool)、q(Quote)は独立公開入力です。
// 返り値: errorは履歴の時計・数値矛盾です。金融とSourceを呼びません。
func (r *replayRuntime) recordEvent(at float64, origin string, afterEOF bool, q Quote) error {
	expectedEOF := r.result.InputEnd == nil || at > r.result.InputEnd.Time
	if afterEOF != expectedEOF {
		return fmt.Errorf("独立eventのEOF状態が統合原板終端と不一致")
	}
	r.ordinal++
	window, epoch := r.eventEpoch(at)
	record, err := r.tracker.Observe(EventInput{Ordinal: r.ordinal, At: at, Origin: origin, Window: window, EpochStart: epoch, AfterEOF: afterEOF, Quote: q, Technical: r.eventBank.View().Technical})
	if err != nil {
		return err
	}
	if record != nil {
		r.result.EntryObservations = append(r.result.EntryObservations, *record)
		if err := r.indexEventRecord(*record); err != nil {
			return err
		}
	}
	return nil
}

// advanceEvent は独立eventBankだけを公開時計へ進めます。
//
// 引数: at(float64)、origin(string)、afterEOF(bool)は公開段階です。
// 返り値: errorは指標又はeventの入力不正です。
func (r *replayRuntime) advanceEvent(at float64, origin string, afterEOF bool) error {
	if err := r.eventBank.Advance(at); err != nil {
		return err
	}
	return r.recordEvent(at, origin, afterEOF, r.last)
}

// processClock は同時計の3分公開を旧coretimerより先に実行します。
//
// 引数: clock(replayClock)、afterEOF(bool)は合成時計と終端後の区別です。
// 返り値: errorは独立公開又は旧金融接続の不整合です。
func (r *replayRuntime) processClock(clock replayClock, afterEOF bool) error {
	if clock.Three {
		if err := r.advanceEvent(clock.At, "three_timer", afterEOF); err != nil {
			return err
		}
	}
	if clock.Core {
		if err := r.advanceTimer(clock.At, afterEOF); err != nil {
			return err
		}
		if err := r.flushProfitContexts(); err != nil {
			return err
		}
	}
	return nil
}

// hashTechnical は全既知旗と全数値を固定little-endian配列へ写して指紋化します。
//
// 引数: h(hash.Hash)、phase(string)、at(float64)、v(TechnicalView)は旧呼出直後値です。
// 返り値: なし。JSONのraw毎巨大文字列を作らず全fieldを同じ順で保存します。
func hashTechnical(h hash.Hash, phase string, at float64, v TechnicalView) {
	var data [1 + 8 + 5 + 14*8]byte
	if phase == "quote" {
		data[0] = 1
	}
	binary.LittleEndian.PutUint64(data[1:9], math.Float64bits(at))
	for i, b := range []bool{v.TrendKnown, v.ReversalKnown, v.SpikeKnown, v.ExitKnown, v.ATRKnown} {
		if b {
			data[9+i] = 1
		}
	}
	for i, n := range []float64{v.EMA8_3, v.EMA21_3, v.EMA8_15, v.EMA21_15, v.RSI3, v.PreviousRSI3, v.Histogram3, v.PreviousHistogram3, v.Close3, v.TR3, v.ATR3, v.PreviousATR3, v.Bar3End, v.Bar15End} {
		binary.LittleEndian.PutUint64(data[14+i*8:22+i*8], math.Float64bits(n))
	}
	_, _ = h.Write(data[:])
}

// compareTechnical は旧actual呼出後の全Technicalを独立数値器へ照合します。
//
// 引数: phase(string)、at(float64)は旧core/raw段階と時計です。
// 返り値: errorは未知残値を含めた一つでもある差です。ChartPairは同値対象外です。
func (r *replayRuntime) compareTechnical(phase string, at float64) error {
	actual, event := r.bank.View().Technical, r.eventBank.View().Technical
	if !reflect.DeepEqual(actual, event) {
		r.result.TechnicalEquivalence.Mismatches++
		return fmt.Errorf("旧actual/独立event Technical差:%s %.9f", phase, at)
	}
	if r.techHashes == nil {
		r.techHashes = &technicalHashes{actual: sha256.New(), event: sha256.New()}
	}
	hashTechnical(r.techHashes.actual, phase, at, actual)
	hashTechnical(r.techHashes.event, phase, at, event)
	if phase == "quote" {
		r.result.TechnicalEquivalence.QuoteCalls++
	} else {
		r.result.TechnicalEquivalence.CoreCalls++
	}
	r.result.TechnicalEquivalence.ActualSHA256 = hex.EncodeToString(r.techHashes.actual.Sum(nil))
	r.result.TechnicalEquivalence.EventSHA256 = hex.EncodeToString(r.techHashes.event.Sum(nil))
	return nil
}

// bindEntry は旧金融が受理した新規だけへ外政策と元/供給順位を凍結します。
//
// 引数: key/mode(string)、delay(int)、grid(GridDecision)は会計と当時共有判断です。
// 返り値: errorは要求ID・供給pool・方向資格・金融rankの不一致です。
func (r *replayRuntime) bindEntry(key, mode string, delay int, grid GridDecision) error {
	policy, _, err := modeParts(mode)
	if err != nil {
		return err
	}
	book := r.books[key].Result()
	if len(book.Decisions) == 0 {
		return fmt.Errorf("定時金融判断がない")
	}
	last := book.Decisions[len(book.Decisions)-1]
	if last.At != grid.At {
		return fmt.Errorf("定時金融判断の時計が不一致")
	}
	if last.Action != "新規要求" {
		return nil
	}
	selected := last.SourceContext.SelectedID
	var order *ActualOrder
	for i := range book.Orders {
		o := &book.Orders[i]
		if o.Kind == "entry" && o.RequestTime == grid.At && o.ReferenceID == selected {
			if order != nil {
				return fmt.Errorf("同枠に複数新規")
			}
			order = o
		}
	}
	if order == nil || !grid.ClockAllowed {
		return fmt.Errorf("金融新規に当時の外供給がない")
	}
	var pool *PoolEvaluation
	for i := range grid.Policies[policy].Pool {
		p := &grid.Policies[policy].Pool[i]
		if p.ReferenceID == selected {
			pool = p
			break
		}
	}
	if pool == nil || !pool.Allowed || pool.SuppliedRank == nil || order.SourceEntry == nil || order.SourceEntry.Rank != *pool.SuppliedRank {
		return fmt.Errorf("受理新規の元/供給順位が不一致")
	}
	var direction *EntryDirectionEvaluation
	for i := range grid.Entry.Directions {
		d := &grid.Entry.Directions[i]
		if d.Side == order.Side {
			direction = d
			break
		}
	}
	if direction == nil || policy == "E0" && !direction.E0Allowed || policy == "E1" && !direction.E1Allowed {
		return fmt.Errorf("受理新規の外方向資格が不成立")
	}
	binding := EntryOrderBinding{BookKey: key, Policy: policy, DelaySeconds: delay, EntryOrderID: order.ID, PositionID: order.PositionID, ReferenceID: selected, At: grid.At, RequestedQuantity: order.Quantity, RawRank: pool.RawRank, SuppliedRank: *pool.SuppliedRank, SourceMethod: grid.Source.Method, SourceAt: grid.Source.At, SourceIndex: grid.Source.SourceIndex, PoolEvaluation: *pool, CurrentQualification: *direction}
	encoded, err := json.Marshal(binding)
	if err != nil {
		return err
	}
	var frozen EntryOrderBinding
	if err = json.Unmarshal(encoded, &frozen); err != nil {
		return err
	}
	for _, b := range r.result.EntryBindings {
		if b.BookKey == key && b.EntryOrderID == order.ID {
			return fmt.Errorf("外新規binding重複")
		}
	}
	r.result.EntryBindings = append(r.result.EntryBindings, frozen)
	return nil
}

// profitSupport は元支持のうち将来の観測に必要なスカラーだけを複写します。
//
// 引数: s(far81.CurrentSupport)は当原行の元支持です。
// 返り値: ProfitSupportはWindows mapを共有しない抜粋です。
func profitSupport(s far81.CurrentSupport) ProfitSupport {
	return ProfitSupport{Known: s.Known, Reason: s.Reason, OFIKnown: s.OFIKnown, OFI30: s.OFI30, OFIReason: s.OFIReason, M: s.M, T: s.T, Opp: s.Opp, OwnAt: s.OwnAt}
}

// bufferProfitContext は正常原行の値型抜粋を直前core以後だけ一時保持します。
//
// 引数: q(Quote)、technical(TechnicalView)、current(*CurrentEvidence)は当原行値です。
// 返り値: errorは別原行の元特徴又は実Index重複です。売買側へ値を返しません。
func (r *replayRuntime) bufferProfitContext(q Quote, technical TechnicalView, current *CurrentEvidence) error {
	if !q.Valid || q.Last <= 0 {
		return nil
	}
	if r.profitBuffer == nil {
		r.profitBuffer = map[int64]ProfitContext{}
	}
	if _, duplicate := r.profitBuffer[q.Index]; duplicate {
		return fmt.Errorf("利益観測bufferの実Index重複")
	}
	row := ProfitContext{Quote: q, Technical: technical, CurrentAvailable: current != nil, TriggeredBy: []ProfitTrigger{}}
	if current != nil {
		c := *current
		if c.Time != q.Time || c.SourceLine != q.Line || c.Last != q.Last || c.Bid != q.Bid || c.Ask != q.Ask {
			return fmt.Errorf("利益観測のCurrentが別原行")
		}
		row.Current = &ProfitCurrent{Reference: c.Reference, Time: c.Time, Received: c.Received, SourceIndex: c.SourceIndex, SourceLine: c.SourceLine, Short: c.Short, Night: c.Night, Buy: profitSupport(c.Buy), Sell: profitSupport(c.Sell)}
	}
	r.profitBuffer[q.Index] = row
	return nil
}

// flushProfitContexts はcore/EOFの読取結果から初回旗原行だけを凍結します。
//
// 引数: なし。4 Book.Resultの新flagを当原行bufferへ結びます。
// 返り値: errorは欠番・別時計・全玉旗の別物理行・未来片です。金融状態は変えません。
func (r *replayRuntime) flushProfitContexts() error {
	if r.profitSeen == nil {
		r.profitSeen = map[string]bool{}
	}
	selected := map[int64]*ProfitContext{}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(mode, delay)
			book := r.books[key].Result()
			for _, lot := range book.Lots {
				for _, kind := range []string{"residual", "whole"} {
					flag, index, at := lot.Flag, lot.FlagIndex, lot.FlagTime
					if kind == "whole" {
						flag, index, at = lot.WholeFlag, lot.WholeFlagIndex, lot.WholeFlagTime
					}
					identity := key + "|" + lot.ID + "|" + kind
					if !flag || r.profitSeen[identity] {
						continue
					}
					source, ok := r.profitBuffer[index]
					if !ok || at == nil || *at != source.Quote.Time || kind == "whole" && lot.WholeFlagLine != source.Quote.Line {
						return fmt.Errorf("初回利益旗の原行buffer欠番又は時計差:%s", identity)
					}
					context := selected[index]
					if context == nil {
						copy := source
						copy.TriggeredBy = []ProfitTrigger{}
						context = &copy
						selected[index] = context
					}
					remaining, net := lot.InitialQuantity, 0.0
					for _, piece := range book.Closed {
						if piece.PositionID == lot.ID && piece.ExitLine <= source.Quote.Line {
							if piece.ExitTime > source.Quote.Time {
								return fmt.Errorf("利益旗の計算へ未来の返済片が混入")
							}
							remaining -= piece.Quantity
							net += piece.PnL5
						}
					}
					if remaining < 0 {
						return fmt.Errorf("利益旗原行の残量が負")
					}
					context.TriggeredBy = append(context.TriggeredBy, ProfitTrigger{BookKey: key, PositionID: lot.ID, ReferenceID: lot.ReferenceID, FlagKind: kind, RemainingAfterFill: remaining, ClosedNetAfterFill: net})
					r.profitSeen[identity] = true
				}
			}
		}
	}
	indices := make([]int64, 0, len(selected))
	for index := range selected {
		indices = append(indices, index)
	}
	sort.Slice(indices, func(i, j int) bool { return indices[i] < indices[j] })
	for _, index := range indices {
		row := *selected[index]
		row.ID = fmt.Sprintf("P%06d", len(r.result.ProfitContexts)+1)
		r.result.ProfitContexts = append(r.result.ProfitContexts, row)
	}
	r.profitBuffer = map[int64]ProfitContext{}
	return nil
}

// ReplayResult は共有参照・定時・返済イベントと4独立実会計を保存します。
type ReplayResult struct {
	EntryOpportunities   []EntryOpportunityLevel `json:"entry_opportunities"`
	Session              string                  `json:"session"`
	Quality              map[string]RawQuality   `json:"quality"`
	ReferenceCounts      map[string]int          `json:"reference_counts"`
	Books                map[string]BookResult   `json:"books"`
	GridDecisions        []GridDecision          `json:"grid_decisions"`
	SourceEvents         []SourceEvent           `json:"source_events"`
	SourceEquivalence    SourceEquivalence       `json:"source_equivalence"`
	EntryObservations    []EventRecord           `json:"entry_observations"`
	EntryBindings        []EntryOrderBinding     `json:"entry_bindings"`
	TechnicalEquivalence TechnicalEquivalence    `json:"technical_equivalence"`
	SeedView             TechnicalView           `json:"seed_view"`
	ProfitContexts       []ProfitContext         `json:"profit_contexts"`
	InputEnd             *MergedEnd              `json:"input_end"`
}

// replayReference は固定Source運転と追加読取だけの境界です。
type replayReference interface {
	Step(strategy.Observation) (ReferenceFrame, error)
	Force(float64, string) error
	Frame() ReferenceFrame
	ReadMetadata() (ReadSnapshot, error)
}

type replayRuntime struct {
	eventIndex   map[int64]EventRecord
	session      strategy.Session
	bank         *ChartBank
	books        map[string]*Book
	last         Quote
	current      CurrentEvidence
	forceDone    bool
	grids        map[float64]bool
	result       *ReplayResult
	refs         map[string]replayReference
	sourceLines  map[string]int64
	legacyRefs   map[string]replayLegacyReference
	frameHashes  *frameHashes
	eventBank    *ChartBank
	tracker      *EventTracker
	ordinal      int64
	techHashes   *technicalHashes
	profitBuffer map[int64]ProfitContext
	profitSeen   map[string]bool
}

var referenceOrder = []string{"D164_15", "P164_06", "U165_03"}

// bookKey はR0/R1の外側ラベルと約定遅延を保存キーへ写します。
//
// 引数: mode(string)、delay(int)はR0/R1と0/1です。
// 返り値: stringは一意な会計キーです。
func bookKey(mode string, delay int) string { return fmt.Sprintf("%s_D%d", mode, delay) }

// emptySnapshot は未作成・供給停止の空poolを統一します。
//
// 引数: なし。
// 返り値: ReadSnapshotは架空のSource原行を持たない空値です。
func emptySnapshot() ReadSnapshot {
	return ReadSnapshot{SourceIndex: -1, Lots: []ReadLot{}, Closes: []ReferenceClose{}}
}

// structureAnchorAt は当時の確定3分EMA8だけを要求時点で固定します。
//
// 引数: at(float64)は判断時計、chart(ChartView)は確定公開された指標です。
// 返り値: StructureAnchorは当時EMA価格又は理由付き未知で、将来足を使いません。
func structureAnchorAt(at float64, chart ChartView) StructureAnchor {
	t := chart.Technical
	a := StructureAnchor{Reason: "当時確定3分EMA8が未知"}
	if t.ExitKnown && !math.IsNaN(at) && !math.IsInf(at, 0) &&
		!math.IsNaN(t.EMA8_3) && !math.IsInf(t.EMA8_3, 0) && t.EMA8_3 > 0 &&
		!math.IsNaN(t.Bar3End) && !math.IsInf(t.Bar3End, 0) && t.Bar3End > 0 &&
		t.Bar3End <= at && at-t.Bar3End <= 180 {
		a.Known, a.Price, a.At, a.BarEnd, a.Reason = true, t.EMA8_3, at, t.Bar3End, "新規要求時点の確定3分EMA8"
	}
	return a
}

// replayTimers は定時と強制返済境界を重複なしの時間順へまとめます。
//
// 引数: session(strategy.Session)は固定内部時計です。
// 返り値: []float64は全timer、map[float64]boolは新規判断定時、errorは場ID不正です。
func replayTimers(session strategy.Session) ([]float64, map[float64]bool, error) {
	grids, e := far80.ScheduledTimes(session.ID)
	if e != nil {
		return nil, nil, e
	}
	set := map[float64]bool{}
	times := append([]float64{}, grids...)
	for _, at := range grids {
		set[at] = true
	}
	times = append(times, session.ForceClose)
	if session.Kind == "Night" {
		times = append(times, session.USOpen-900, session.USOpen+900)
	}
	sort.Float64s(times)
	unique := times[:0]
	for _, at := range times {
		if len(unique) == 0 || unique[len(unique)-1] != at {
			unique = append(unique, at)
		}
	}
	return unique, set, nil
}

// recordSourceEvent は新返済がある時だけ、共有イベントを一度保存します。
//
// 引数: at(float64)、origin(string)、q(Quote)、snapshot(ReadSnapshot)、sourceLine(int64)はイベント出典です。
// 返り値: ありません。現在源snapshotの時計をtimer時計へ変更しません。
func (r *replayRuntime) recordSourceEvent(at float64, origin string, q Quote, snapshot ReadSnapshot, sourceLine int64) {
	if len(snapshot.Closes) == 0 {
		return
	}
	r.result.SourceEvents = append(r.result.SourceEvents, SourceEvent{At: at, Origin: origin, Quote: q, Method: snapshot.Method, SourceAt: snapshot.At, SourceIndex: snapshot.SourceIndex, SourceLine: sourceLine, Closes: append([]ReferenceClose{}, snapshot.Closes...)})
}

// sourceFrame は当原行でSourceを進めるか、Last不良なら直近現在量だけを読みます。
//
// 引数: q(Quote)、observation(*strategy.Observation)は実当行と正常Last時の元特徴です。
// 返り値: ReferenceFrameは全Sourceの現在量と当回だけのCloses、errorは参照不整合です。
func (r *replayRuntime) sourceFrame(q Quote, observation *strategy.Observation) (ReferenceFrame, error) {
	frame := ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}
	for _, name := range referenceOrder {
		ref := r.refs[name]
		if ref == nil {
			continue
		}
		part := ref.Frame()
		if observation != nil {
			var err error
			part, err = ref.Step(*observation)
			if err != nil {
				return frame, err
			}
			r.sourceLines[name] = q.Line
			snapshot, err := ref.ReadMetadata()
			if err != nil {
				return frame, err
			}
			legacy := r.legacyRefs[name]
			if legacy == nil {
				return frame, fmt.Errorf("固定80Sourceが未準備")
			}
			old, err := legacy.Step(*observation)
			if err != nil {
				return frame, err
			}
			if err = r.compareSource("step", name, q.Time, snapshot, part, old); err != nil {
				return frame, err
			}
			if snapshot.At != observation.Time || snapshot.SourceIndex != observation.Index {
				return frame, fmt.Errorf("Source読取が当原行と不一致")
			}
			r.recordSourceEvent(q.Time, "quote", q, snapshot, q.Line)
			frame.Closes = append(frame.Closes, part.Closes...)
			r.result.ReferenceCounts[name]++
		}
		frame.Lots = append(frame.Lots, part.Lots...)
	}
	return frame, nil
}

// advanceTimer は当原行より前に境界通知と参照poolの定時取得を処理します。
//
// 引数: at(float64)、afterEOF(bool)は公開時計と終端後の区別です。
// 返り値: errorは参照・読取・金融接続の不整合です。
func (r *replayRuntime) advanceTimer(at float64, afterEOF bool) error {
	if err := r.advanceEvent(at, "core_timer", afterEOF); err != nil {
		return err
	}
	if err := r.bank.Advance(at); err != nil {
		return err
	}
	if err := r.compareTechnical("core_timer", at); err != nil {
		return err
	}
	if at == r.session.ForceClose || (r.session.Kind == "Night" && at == r.session.USOpen-900) {
		reason := "場末10分前"
		if at != r.session.ForceClose {
			reason = "米国前枠終了"
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				if err := r.books[bookKey(mode, delay)].Force(at, r.last, reason); err != nil {
					return err
				}
			}
		}
		for _, name := range referenceOrder {
			ref := r.refs[name]
			if ref == nil {
				continue
			}
			if err := ref.Force(at, reason); err != nil {
				return err
			}
			legacy := r.legacyRefs[name]
			if legacy == nil {
				return fmt.Errorf("固定80Sourceが未準備")
			}
			if err := legacy.Force(at, reason); err != nil {
				return err
			}
			snapshot, err := ref.ReadMetadata()
			if err != nil {
				return err
			}
			if err = r.compareSource("force", name, at, snapshot, ref.Frame(), legacy.Frame()); err != nil {
				return err
			}
			r.recordSourceEvent(at, "timer", r.last, snapshot, r.sourceLines[name])
			if len(snapshot.Closes) > 0 {
				for _, mode := range Modes {
					for delay := 0; delay <= 1; delay++ {
						if err = r.books[bookKey(mode, delay)].OnReference(at, r.last, snapshot.Closes); err != nil {
							return err
						}
					}
				}
			}
		}
		if at == r.session.ForceClose {
			r.forceDone = true
		}
	}
	if r.session.Kind == "Night" && at == r.session.USOpen+900 {
		if r.refs["U165_03"] != nil {
			return fmt.Errorf("U165参照を二重に生成")
		}
		next, err := NewReference("U165_03", r.session, 100)
		if err != nil {
			return err
		}
		r.refs["U165_03"] = next
		old, err := far80.NewReference("U165_03", r.session, 100)
		if err != nil {
			return err
		}
		r.legacyRefs["U165_03"] = old
	}
	if !r.grids[at] {
		return nil
	}
	window, err := far80.WindowMethod(at, r.session.USOpen, r.session.Kind)
	if err != nil {
		return err
	}
	allowed, block := true, ""
	switch {
	case r.forceDone:
		allowed, block = false, "場末返済要求後"
	case window == "静観":
		allowed, block = false, "米国開始前後の静観"
	case afterEOF:
		allowed, block = false, "原板終端後の定時"
	}
	chart := r.bank.View()
	c0, err := Decide(at, r.last, chart, r.current)
	if err != nil {
		return err
	}
	snapshot := emptySnapshot()
	if ref := r.refs[window]; ref != nil {
		snapshot, err = ref.ReadMetadata()
		if err != nil {
			return err
		}
	}
	currentFrame, oldFrame := ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}, ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}
	if ref := r.refs[window]; ref != nil {
		currentFrame = ref.Frame()
		legacy := r.legacyRefs[window]
		if legacy == nil {
			return fmt.Errorf("固定80Sourceが未準備")
		}
		oldFrame = legacy.Frame()
	}
	if err = r.compareSource("grid", window, at, snapshot, currentFrame, oldFrame); err != nil {
		return err
	}
	snapshot.Closes = []ReferenceClose{}
	anchor := structureAnchorAt(at, chart)
	events, err := r.tracker.Snapshot(at)
	if err != nil {
		return err
	}
	evaluation, err := EvaluateEntry(at, r.last, chart, events)
	if err != nil {
		return err
	}
	grid := GridDecision{At: at, Window: window, ClockAllowed: allowed, BlockReason: block, C0: c0, Source: snapshot, SourceLine: r.sourceLines[window], StructureAnchor: anchor, Entry: evaluation, Events: events, Policies: map[string]PolicySupply{}}
	return r.supplyEntryGrid(grid, chart.Technical)
}

// observeQuote はSourceと実G1を当原行の順で進め、元Sourceへ実損益を返しません。
//
// 引数: q(Quote)、current(*CurrentEvidence)、observation(*strategy.Observation)は当原行で、Last不良時の源二値はnilです。
// 返り値: errorは足時計・源特徴・金融接続の不整合です。
func (r *replayRuntime) observeQuote(q Quote, current *CurrentEvidence, observation *strategy.Observation) error {
	chart := q
	chart.Valid = q.Last > 0
	if err := r.bank.Observe(chart); err != nil {
		return err
	}
	if err := r.eventBank.Observe(chart); err != nil {
		return err
	}
	if err := r.recordEvent(q.Time, "quote", false, q); err != nil {
		return err
	}
	if err := r.compareTechnical("quote", q.Time); err != nil {
		return err
	}
	if current != nil {
		r.current = *current
	}
	frame, err := r.sourceFrame(q, observation)
	if err != nil {
		return err
	}
	technical := r.bank.View().Technical
	return r.deliverQuote(q, frame, technical, current)
}

// Replay は旧Source/金融を保ち、E1と利確後再参加R0/R1の四会計と独立再開履歴を保存します。
//
// 引数: root(string)は固定入力根、input(InputSession)は場、bank(*far80.TechnicalBank)は当場前の種です。
// 返り値: ReplayResultは4会計と共有/疎な観測、errorは旧同値又は接続の不整合です。
func Replay(root string, input InputSession, bank *far80.TechnicalBank) (ReplayResult, error) {
	result := ReplayResult{EntryOpportunities: []EntryOpportunityLevel{}, EntryObservations: []EventRecord{}, EntryBindings: []EntryOrderBinding{}, ProfitContexts: []ProfitContext{}, Session: input.ID, Quality: map[string]RawQuality{}, Books: map[string]BookResult{}, GridDecisions: []GridDecision{}, ReferenceCounts: map[string]int{}, SourceEvents: []SourceEvent{}}
	if bank == nil {
		return result, fmt.Errorf("技法種がnilです")
	}
	session, e := sessionClock(input.ID)
	if e != nil {
		return result, e
	}
	method := "D164_15"
	if session.Kind == "Night" {
		method = "P164_06"
	}
	params, e := strategy.ParametersForMethod("NK225", session.Kind, method)
	if e != nil {
		return result, e
	}
	if session.Kind == "Night" {
		u, err := strategy.ParametersForMethod("NK225", "Night", "U165_03")
		if err != nil {
			return result, err
		}
		if !reflect.DeepEqual(params.Features, u.Features) {
			return result, fmt.Errorf("二夜手法の特徴条件が異なります")
		}
	}
	features, e := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		return result, e
	}
	features.EnableResearch()
	boards, candles := []replayBoard{}, []candleEvent{}
	for _, reference := range []string{"TOPIX", "NK225"} {
		path, err := verifyInput(root, input.Files[reference+"_book"])
		if err != nil {
			return result, err
		}
		rows, quality, err := readBoards(path, reference, session)
		if err != nil {
			return result, err
		}
		if len(quality.Contracts) != 1 {
			return result, fmt.Errorf("限月混在又は不明:%s %v", reference, quality.Contracts)
		}
		if reference == "NK225" && quality.Contracts[0] != input.Contract {
			return result, fmt.Errorf("NK限月不一致")
		}
		result.Quality[reference] = quality
		boards = append(boards, rows...)
		for _, interval := range []int{60, 300} {
			path, err = verifyInput(root, input.Files[fmt.Sprintf("%s_candle_%d", reference, interval)])
			if err != nil {
				return result, err
			}
			events, err := readCandles(path, reference, interval, params.Features.CandleDelay, session)
			if err != nil {
				return result, err
			}
			candles = append(candles, events...)
		}
	}
	sort.SliceStable(boards, func(i, j int) bool { return boards[i].Board.Time < boards[j].Board.Time })
	if len(boards) > 0 {
		last := boards[len(boards)-1]
		result.InputEnd = &MergedEnd{Time: last.Board.Time, Reference: last.Board.Reference, SourceLine: last.Line}
	}
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })
	first, e := NewReference(method, session, 100)
	if e != nil {
		return result, e
	}
	refs := map[string]replayReference{method: first}
	legacy, err := far80.NewReference(method, session, 100)
	if err != nil {
		return result, err
	}
	legacyRefs := map[string]replayLegacyReference{method: legacy}
	books := map[string]*Book{}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			var book *Book
			var err error
			if mode == "R0" {
				book, err = NewSourceBook(input.ID, "S", 100)
			} else {
				book, err = NewReentrySourceBook(input.ID, "S", 100)
			}
			if err != nil {
				return result, err
			}
			if err = book.SetFillDelay(float64(delay)); err != nil {
				return result, err
			}
			books[bookKey(mode, delay)] = book
		}
	}
	times, grids, e := replayTimers(session)
	if e != nil {
		return result, e
	}
	result.SeedView = bank.View()
	eventSeed := *bank
	chartBank := NewChartBank(bank)
	eventBank := NewChartBank(&eventSeed)
	chartBank.BeginSession(session.Start)
	eventBank.BeginSession(session.Start)
	runtime := replayRuntime{session: session, bank: chartBank, books: books, last: Quote{Index: -1}, grids: grids, result: &result, refs: refs, sourceLines: map[string]int64{}, legacyRefs: legacyRefs, eventBank: eventBank, tracker: NewEventTracker()}
	clocks := mergedClocks(session, times)
	timerIndex, candleIndex := 0, 0
	actualIndex := int64(-1)
	// ----------------------------------------
	// 同時計の当原行を先取りせず、公開timer→足CSV→源特徴→実保護の順に進めます。
	for _, row := range boards {
		for timerIndex < len(clocks) && clocks[timerIndex].At <= row.Board.Time {
			clock := clocks[timerIndex]
			timerIndex++
			if e = runtime.processClock(clock, false); e != nil {
				return result, e
			}
		}
		for candleIndex < len(candles) && candles[candleIndex].At <= row.Board.Time {
			event := candles[candleIndex]
			candleIndex++
			if _, e = features.AddCandles(event.Reference, event.Interval, []strategy.Candle{event.Candle}, event.At); e != nil {
				return result, e
			}
		}
		if row.Board.Last <= 0 {
			if row.Board.Reference == "NK225" {
				actualIndex++
				q := Quote{Time: row.Board.Time, Index: actualIndex, Line: row.Line, Last: row.Board.Last, Bid: row.Board.Bid, Ask: row.Board.Ask, Valid: false}
				if e = runtime.observeQuote(q, nil, nil); e != nil {
					return result, e
				}
			}
			continue
		}
		observation, err := features.OnBoard(row.Board)
		if err != nil {
			return result, err
		}
		if observation.Reference != "NK225" {
			continue
		}
		actualIndex++
		q := Quote{Time: observation.Time, Index: actualIndex, Line: row.Line, Last: observation.Last, Bid: observation.Bid, Ask: observation.Ask, Valid: observation.QuoteOK && observation.Last > 0}
		current := ExtractCurrent(observation, row.Line)
		if e = runtime.observeQuote(q, &current, &observation); e != nil {
			return result, e
		}
	}
	// ----------------------------------------
	// 終端後の時計も記録し、約定価格や未観測の返済を補完しません。
	for timerIndex < len(clocks) {
		clock := clocks[timerIndex]
		timerIndex++
		if e = runtime.processClock(clock, true); e != nil {
			return result, e
		}
	}
	if e = runtime.flushProfitContexts(); e != nil {
		return result, e
	}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			key := bookKey(mode, delay)
			result.Books[key] = books[key].Result()
		}
	}
	return result, nil
}

// supplyEntryGrid は純資格の部分列を固定金融へ渡し、要求時外bindingを保存します。
//
// 引数: grid(GridDecision)、technical(TechnicalView)は旧actualで確定した当時値です。
// 返り値: errorはfilter又は固定金融の入力不整合です。資格は金融へ逆流しません。
func (r *replayRuntime) supplyEntryGrid(grid GridDecision, technical TechnicalView) error {
	if grid.Policies == nil {
		grid.Policies = map[string]PolicySupply{}
	}
	for _, policy := range EntryPolicies {
		supplied, pool, err := FilterEntry(policy, grid.Source, grid.Entry)
		if err != nil {
			return err
		}
		ids := []string{}
		if !grid.ClockAllowed {
			supplied.Lots = []ReadLot{}
			for i := range pool {
				pool[i].SuppliedRank = nil
			}
		}
		for _, row := range supplied.Lots {
			ids = append(ids, row.Reference.ID)
		}
		grid.Policies[policy] = PolicySupply{Policy: policy, SuppliedIDs: ids, Pool: pool}
		opportunities, levels, err := r.opportunityCandidates(grid, supplied, pool)
		if err != nil {
			return err
		}
		levelIndexes := map[string]int{}
		for index, level := range levels {
			levelIndexes[level.ReferenceID] = index
		}
		for _, mode := range Modes {
			for delay := 0; delay <= 1; delay++ {
				key := bookKey(mode, delay)
				if mode == "R0" {
					err = r.books[key].OnSourceGrid(grid.At, r.last, supplied, grid.C0, technical, grid.StructureAnchor)
				} else {
					err = r.books[key].OnSourceGridWithReentry(grid.At, r.last, supplied, grid.C0, technical, grid.StructureAnchor, opportunities)
				}
				if err != nil {
					return err
				}
				if mode == "R1" {
					assessments := r.books[key].LastReentryAssessments()
					if len(assessments) != len(levels) {
						return fmt.Errorf("再参加assessmentの候補数が不一致")
					}
					seen := map[string]bool{}
					for _, assessment := range assessments {
						index, ok := levelIndexes[assessment.ReferenceID]
						if !ok || seen[assessment.ReferenceID] || assessment.At != grid.At || assessment.OpportunityID != levels[index].Opportunity.OpportunityID || assessment.SuppliedRank != levels[index].SuppliedRank {
							return fmt.Errorf("再参加assessmentと当時機会が不整合")
						}
						seen[assessment.ReferenceID] = true
						levels[index].Assessments[key] = assessment
					}
				}
				if err = r.bindEntry(key, mode, delay, grid); err != nil {
					return err
				}
			}
		}
		encodedLevels, err := json.Marshal(levels)
		if err != nil {
			return err
		}
		var frozenLevels []EntryOpportunityLevel
		if err = json.Unmarshal(encodedLevels, &frozenLevels); err != nil {
			return err
		}
		r.result.EntryOpportunities = append(r.result.EntryOpportunities, frozenLevels...)
	}
	encoded, err := json.Marshal(grid)
	if err != nil {
		return err
	}
	var frozen GridDecision
	if err = json.Unmarshal(encoded, &frozen); err != nil {
		return err
	}
	r.result.GridDecisions = append(r.result.GridDecisions, frozen)
	return nil
}

// deliverQuote は同じSource通知と当原行を四金融へ渡し、観測だけを後に保持します。
//
// 引数: q(Quote)、frame(ReferenceFrame)、technical(TechnicalView)、current(*CurrentEvidence)は共有当時入力です。
// 返り値: errorは固定金融又は診断出典の不正です。fill→Source→旧G1は固定87内部で実行します。
func (r *replayRuntime) deliverQuote(q Quote, frame ReferenceFrame, technical TechnicalView, current *CurrentEvidence) error {
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			if err := r.books[bookKey(mode, delay)].OnQuote(q, frame, technical, current); err != nil {
				return err
			}
		}
	}
	if err := r.bufferProfitContext(q, technical, current); err != nil {
		return err
	}
	r.last = q
	return nil
}
