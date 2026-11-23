// Package chartwarmup は固定80/82の数値器を所有なしで再用する独立チャートです。
package chartwarmup

import (
	"fmt"
	"math"
	"reflect"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

type Quote = far80.Quote

// Scene は足の起点と数値種を継承する限月を明示します。
type Scene struct {
	ID       string  `json:"id"`
	Contract string  `json:"contract"`
	Start    float64 `json:"start"`
}

// SourceStamp は呼出側の価格時計と原行識別であり、実受信時刻ではありません。
type SourceStamp struct {
	Time  float64 `json:"time"`
	Index int64   `json:"index"`
	Line  int64   `json:"line"`
	Last  float64 `json:"last"`
	Valid bool    `json:"valid"`
}

// BarEvidence は値の既知性と別に、完成足の論理公開・入力由来を記録します。
type BarEvidence struct {
	BarEnd        float64     `json:"bar_end"`
	AvailableAt   float64     `json:"available_at"`
	ObservedClock float64     `json:"observed_clock"`
	Rows          int         `json:"rows"`
	DataKnown     bool        `json:"data_known"`
	HasLastSource bool        `json:"has_last_source"`
	LastSource    SourceStamp `json:"last_source"`
	Reason        string      `json:"reason"`
}

// Snapshot は公開APIの値だけを出し、OHLCや未公開EMA履歴を補いません。
type Snapshot struct {
	Scene              Scene           `json:"scene"`
	At                 float64         `json:"at"`
	HasObservedClock   bool            `json:"has_observed_clock"`
	ObservedClock      float64         `json:"observed_clock"`
	HasLastInput       bool            `json:"has_last_input"`
	LastInput          SourceStamp     `json:"last_input"`
	InvalidatedAt      float64         `json:"invalidated_at"`
	Chart              far82.ChartView `json:"chart"`
	Three              BarEvidence     `json:"three"`
	Fifteen            BarEvidence     `json:"fifteen"`
	CarriedNumericSeed bool            `json:"carried_numeric_seed"`
	Sealed             bool            `json:"sealed"`
}

// Publication は3分timerによる値更新と3/15分の更新有無を一度だけ保存します。
type Publication struct {
	At       float64  `json:"at"`
	Three    bool     `json:"three"`
	Fifteen  bool     `json:"fifteen"`
	Snapshot Snapshot `json:"snapshot"`
}

// Batch は独立した値sliceで、呼出側が書換えてもbankに作用しません。
type Batch struct {
	Publications []Publication `json:"publications"`
	Grids        []Snapshot    `json:"grids"`
	After        Snapshot      `json:"after"`
}

// Seed の数値器は値copyで、error等の参照値はnilであることを検査します。
// 公開mask/形成足はNew時に必ず初期化します。
// 私有fieldなので外から未sealedの有効種を組み立てることはできません。
type Seed struct {
	numeric  far80.TechnicalBank
	contract string
	start    float64
	observed float64
	sealed   bool
}

type formingSource struct {
	rows int
	bad  bool
	last SourceStamp
}

// Bank は同一限月の数値種と当場の出典だけを持ち、金融所有を持ちません。
type Bank struct {
	scene       Scene
	numeric     *far80.TechnicalBank
	chart       *far82.ChartBank
	nextThree   float64
	nextFifteen float64
	form3       formingSource
	form15      formingSource
	view        Snapshot
	haveRaw     bool
	lastRaw     Quote
	haveGrid    bool
	lastGrid    float64
	sealed      bool
}

// finite はJSONへ保存できる有限数を確認します。
//
// 引数: values(...float64)は時計又は価格です。
// 返り値: boolは全値が有限なら真です。
func finite(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// referenceFree は固定数値器の値copyに共有する可変参照がないことを確認します。
//
// 引数: v(reflect.Value)は固定数値器又は検査対象の値です。
// 返り値: boolはscalar/struct/固定配列とnil参照だけなら真です。
func referenceFree(v reflect.Value) bool {
	switch v.Kind() {
	case reflect.Struct:
		for i := 0; i < v.NumField(); i++ {
			if !referenceFree(v.Field(i)) {
				return false
			}
		}
		return true
	case reflect.Array:
		for i := 0; i < v.Len(); i++ {
			if !referenceFree(v.Index(i)) {
				return false
			}
		}
		return true
	case reflect.Interface, reflect.Pointer, reflect.Slice, reflect.Map, reflect.Chan, reflect.Func:
		return v.IsNil()
	case reflect.Bool, reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
		reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64,
		reflect.Float32, reflect.Float64, reflect.String:
		return true
	}
	return false
}

// New は同限月のsealed種だけを継承し、当場の形成/公開/前3分を初期化します。
//
// 引数: scene(Scene)は起点と限月、seed(*Seed)は任意の前場sealed値です。
// 返り値: *Bank/errorは独立bank又は未sealed/時計後退/不正入力です。
func New(scene Scene, seed *Seed) (*Bank, error) {
	if scene.ID == "" || scene.Contract == "" || !finite(scene.Start) || scene.Start <= 0 {
		return nil, fmt.Errorf("Scene識別/開始が不正です")
	}
	numeric := far80.NewTechnicalBank()
	carried := false
	if seed != nil {
		if !seed.sealed || seed.contract == "" || !finite(seed.start, seed.observed) || scene.Start <= seed.start || scene.Start < seed.observed {
			return nil, fmt.Errorf("Seed未sealed又はSceneが種の時計より過去です")
		}
		if !referenceFree(reflect.ValueOf(seed.numeric)) {
			return nil, fmt.Errorf("Seed数値器に共有参照があります")
		}
		if scene.Contract == seed.contract {
			copy := seed.numeric
			numeric = &copy
			carried = true
		}
	}
	if !referenceFree(reflect.ValueOf(*numeric)) {
		return nil, fmt.Errorf("固定数値器に共有参照があります")
	}
	chart := far82.NewChartBank(numeric)
	chart.BeginSession(scene.Start)
	b := &Bank{scene: scene, numeric: numeric, chart: chart, nextThree: scene.Start + 180, nextFifteen: scene.Start + 900}
	b.view = Snapshot{Scene: scene, At: scene.Start, Chart: chart.View(), CarriedNumericSeed: carried}
	return b, nil
}

// validateClock は原入力を進める前に全clock/grid条件を確認します。
//
// 引数: at(float64)は明示observed時計、grids([]float64)は今回までの判断時点です。
// 返り値: errorは未来grid/後退/重複/同秒raw後grid等です。失敗時は状態不変です。
func (b *Bank) validateClock(at float64, grids []float64) error {
	if b == nil || b.sealed {
		return fmt.Errorf("bank未初期化又はsealedです")
	}
	if !finite(at) || at < b.scene.Start || b.view.HasObservedClock && at < b.view.ObservedClock {
		return fmt.Errorf("observed時計が不正又は後退です")
	}
	previous := b.lastGrid
	for i, g := range grids {
		if !finite(g) || g < b.scene.Start || g > at || g < b.view.At || b.haveRaw && g <= b.lastRaw.Time ||
			(b.haveGrid || i > 0) && g <= previous {
			return fmt.Errorf("gridが未来/後退/重複又は同秒raw後です")
		}
		previous = g
	}
	return nil
}

// evidence はOHLCを再計算せず、その足へ入ったSourceだけを公開時計に結びます。
//
// 引数: form(formingSource)、end/observed(float64)は当足の入力と公開証跡です。
// 返り値: BarEvidenceは値のKnownと区別した出典です。
func evidence(form formingSource, end, observed float64) BarEvidence {
	reason := "公開済み形成足の入力出典"
	if form.rows == 0 {
		reason = "空足・価格の横ばい補完なし"
	} else if form.bad {
		reason = "形成足に不良Last・数値履歴は未知"
	}
	return BarEvidence{BarEnd: end, AvailableAt: end, ObservedClock: observed, Rows: form.rows,
		DataKnown: form.rows > 0 && !form.bad, HasLastSource: form.rows > 0, LastSource: form.last, Reason: reason}
}

// publish はobserved上限以下の次3分timerだけを固定数値器へ渡します。
//
// 引数: at(float64)は次timer、observed(float64)は今回進行を許した入力価格時計です。
// 返り値: Publication/errorは値と出典、又は時計/固定器の不整合です。
func (b *Bank) publish(at, observed float64) (Publication, error) {
	if at != b.nextThree || at > observed {
		return Publication{}, fmt.Errorf("未来又は順番の違うtimer公開です")
	}
	before := b.chart.View().Technical
	if err := b.chart.Advance(at); err != nil {
		return Publication{}, err
	}
	after := b.chart.View().Technical
	changed3, changed15 := after.Bar3End != before.Bar3End, after.Bar15End != before.Bar15End
	if !changed3 || after.Bar3End != at {
		return Publication{}, fmt.Errorf("固定3分公開とtimerが結合しません")
	}
	b.view.Three = evidence(b.form3, at, observed)
	b.form3 = formingSource{}
	if at == b.nextFifteen {
		if !changed15 || after.Bar15End != at {
			return Publication{}, fmt.Errorf("固定15分公開とtimerが結合しません")
		}
		b.view.Fifteen = evidence(b.form15, at, observed)
		b.form15 = formingSource{}
		b.nextFifteen += 900
	} else if changed15 {
		return Publication{}, fmt.Errorf("15分が予定外に公開されています")
	}
	b.nextThree += 180
	b.view.At, b.view.Chart, b.view.InvalidatedAt = at, b.chart.View(), 0
	return Publication{At: at, Three: changed3, Fifteen: changed15, Snapshot: b.view}, nil
}

// advance は3分timerと明示gridをmergeし、同時計timerをgridより先に公開します。
//
// 引数: at(float64)、grids([]float64)は検査済みobserved時計と判断時点です。
// 返り値: Batch/errorは公開/判断snapshot、又は固定数値器の不整合です。
func (b *Bank) advance(at float64, grids []float64) (Batch, error) {
	result := Batch{Publications: []Publication{}, Grids: []Snapshot{}}
	b.view.HasObservedClock, b.view.ObservedClock = true, at
	for _, g := range grids {
		for b.nextThree <= g {
			p, err := b.publish(b.nextThree, at)
			if err != nil {
				return result, err
			}
			result.Publications = append(result.Publications, p)
		}
		b.view.At = g
		result.Grids = append(result.Grids, b.view)
		b.lastGrid, b.haveGrid = g, true
	}
	for b.nextThree <= at {
		p, err := b.publish(b.nextThree, at)
		if err != nil {
			return result, err
		}
		result.Publications = append(result.Publications, p)
	}
	b.view.At = at
	result.After = b.view
	return result, nil
}

// AdvanceObserved は明示された入力価格時計まで進め、価格を形成足へ足しません。
//
// 引数: observedClock(float64)、grids([]float64)は他市場/Last0等の観測済み時計と判断時点です。
// 返り値: Batch/errorは論理timer公開とgrid。実受信可能時刻を証明しません。
func (b *Bank) AdvanceObserved(observedClock float64, grids []float64) (Batch, error) {
	if err := b.validateClock(observedClock, grids); err != nil {
		return Batch{}, err
	}
	return b.advance(observedClock, grids)
}

// Step はtimer→grid→同時刻rawの順で公開し、Nativeへ何も通知しません。
//
// 引数: q(Quote)は当場NK入力。ValidはLast可用性でBBO品質とは独立、grids([]float64)は判断時点です。
// 返り値: Batch/errorは公開結果又は不正な価格時計/原行です。
func (b *Bank) Step(q Quote, grids []float64) (Batch, error) {
	if err := b.validateClock(q.Time, grids); err != nil {
		return Batch{}, err
	}
	if !finite(q.Time, q.Last, q.Bid, q.Ask) || q.Index < 0 || q.Line <= 0 || b.haveRaw && (q.Index <= b.lastRaw.Index || q.Line <= b.lastRaw.Line || q.Time < b.lastRaw.Time) {
		return Batch{}, fmt.Errorf("Quoteの有限性/原行順が不正です")
	}
	result, err := b.advance(q.Time, grids)
	if err != nil {
		return result, err
	}
	if err = b.chart.Observe(q); err != nil {
		return result, err
	}
	s := SourceStamp{q.Time, q.Index, q.Line, q.Last, q.Valid && q.Last > 0}
	for _, form := range []*formingSource{&b.form3, &b.form15} {
		form.rows++
		form.last = s
		form.bad = form.bad || !s.Valid
	}
	b.view.HasLastInput, b.view.LastInput, b.view.Chart = true, s, b.chart.View()
	if !s.Valid {
		b.view.InvalidatedAt = q.Time
	}
	b.haveRaw, b.lastRaw = true, q
	result.After = b.view
	return result, nil
}

// Snapshot は参照を共有しない値型の現在snapshotを返します。
//
// 引数: ありません。
// 返り値: Snapshotは公開API値と出典だけです。
func (b *Bank) Snapshot() Snapshot {
	if b == nil {
		return Snapshot{}
	}
	return b.view
}

// Seal は観測済み時計を越えて足を締めず、数値種だけを値で確定します。
//
// 引数: ありません。名目場末時計を受け取らず、Advanceを呼びません。
// 返り値: Seed/Snapshot/errorは次場用の数値種、現snapshot、又は重複sealです。
func (b *Bank) Seal() (Seed, Snapshot, error) {
	if b == nil || b.sealed {
		return Seed{}, Snapshot{}, fmt.Errorf("bank未初期化又はseal済みです")
	}
	if !referenceFree(reflect.ValueOf(*b.numeric)) {
		return Seed{}, Snapshot{}, fmt.Errorf("固定数値器に共有参照があります")
	}
	b.sealed, b.view.Sealed = true, true
	return Seed{numeric: *b.numeric, contract: b.scene.Contract, start: b.scene.Start, observed: b.view.ObservedClock, sealed: true}, b.view, nil
}
