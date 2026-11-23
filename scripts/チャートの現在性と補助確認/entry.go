package far82

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// ChartView は現確定足と、同じ計算器で連続確認した直前3分足を分けます。
type ChartView struct {
	Technical       TechnicalView
	PreviousClose3  float64
	PreviousEMA8_3  float64
	PreviousBar3End float64
	Previous3Known  bool
}

// ChartPair は保存用の直前3分足で、現Technicalとの重複を避けます。
type ChartPair struct {
	PreviousClose3  float64 `json:"previous_close3"`
	PreviousEMA8_3  float64 `json:"previous_ema8_3"`
	PreviousBar3End float64 `json:"previous_bar3_end"`
	Previous3Known  bool    `json:"previous3_known"`
}

// CurrentShortWindow は元FARの実経過秒によるpt/秒を保存します。
type CurrentShortWindow struct {
	Known    bool    `json:"known"`
	Move     float64 `json:"move"`
	Speed    float64 `json:"speed"`
	Elapsed  float64 `json:"elapsed"`
	Endpoint float64 `json:"endpoint"`
	Delay    float64 `json:"delay"`
	Reason   string  `json:"reason"`
}

// CurrentShort は窓別換算bp幅と別の、自己気配中央の短秒速度です。
type CurrentShort struct {
	Five    CurrentShortWindow `json:"five"`
	Fifteen CurrentShortWindow `json:"fifteen"`
	Time    float64            `json:"time"`
	Mid     float64            `json:"mid"`
}

// CurrentEvidence は81固定の現在構造に、独立した短秒速度を加えます。
type CurrentEvidence struct {
	far81.CurrentEvidence
	Short CurrentShort `json:"short"`
}

// AuxiliaryValue は補助値を未知・反対・中立・支持へ分け、未知に数値を置きません。
type AuxiliaryValue struct {
	Known  bool     `json:"known"`
	State  string   `json:"state"`
	Value  *float64 `json:"value,omitempty"`
	Reason string   `json:"reason"`
}

// AuxiliaryState は片側における補助の観測と、追加確認の発動を保存します。
type AuxiliaryState struct {
	Five             AuxiliaryValue `json:"five"`
	Fifteen          AuxiliaryValue `json:"fifteen"`
	OFI              AuxiliaryValue `json:"ofi"`
	SlowdownKnown    bool           `json:"slowdown_known"`
	Slowdown         bool           `json:"slowdown"`
	StructureKnown   bool           `json:"structure_known"`
	StructureSupport bool           `json:"structure_support"`
	PressureClear    bool           `json:"pressure_clear"`
}

// EntryDirection は81と共通の判定項目に、必須未知と補助状態を加えます。
type EntryDirection struct {
	far81.EntryDirection
	RequiredUnknown bool           `json:"required_unknown"`
	Auxiliary       AuxiliaryState `json:"auxiliary"`
}

// EntryDecision は同一時点の入力と、2方向の複合判断を保持します。
type EntryDecision struct {
	At              float64          `json:"at"`
	Policy          string           `json:"policy"`
	Allowed         bool             `json:"allowed"`
	Side            int              `json:"side"`
	Role            string           `json:"role"`
	Reason          string           `json:"reason"`
	RequiredUnknown bool             `json:"required_unknown"`
	Quote           Quote            `json:"quote"`
	Technical       TechnicalView    `json:"technical"`
	ChartPair       ChartPair        `json:"chart_pair"`
	Evidence        CurrentEvidence  `json:"evidence"`
	Directions      []EntryDirection `json:"directions"`
}

// copyShortWindow は元の速度・両端時計・未知理由を値で複写します。
//
// 引数: w(strategy.SelectedDay164ShortWindow)は元の公開窓です。
// 返り値: CurrentShortWindowはpt/秒と計算元metadataです。
func copyShortWindow(w strategy.SelectedDay164ShortWindow) CurrentShortWindow {
	return CurrentShortWindow{w.Known, w.Move, w.Speed, w.Elapsed, w.Endpoint, w.Delay, w.Reason}
}

// ExtractCurrent は81の構造抽出を固定再用し、DayShortだけを追加します。
//
// 引数: o(strategy.Observation)は最後の実特徴、rawLine(int64)は物理原行です。
// 返り値: CurrentEvidenceは保有Sourceに依存しない当時入力です。
func ExtractCurrent(o strategy.Observation, rawLine int64) CurrentEvidence {
	s := o.Selected.DayShort
	return CurrentEvidence{CurrentEvidence: far81.ExtractCurrent(o, rawLine), Short: CurrentShort{Five: copyShortWindow(s.Five), Fifteen: copyShortWindow(s.Fifteen), Time: s.Time, Mid: s.Mid}}
}

// finiteEntry は必要な数値が全て有限かを検査します。
//
// 引数: values(...float64)は評価に使う数値です。
// 返り値: boolはNaNと無限大が一つもなければ真です。
func finiteEntry(values ...float64) bool {
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return false
		}
	}
	return true
}

// cloneCurrent は81から継承した窓mapを入力側と分離します。
//
// 引数: c(CurrentEvidence)は評価前の現在入力です。
// 返り値: CurrentEvidenceは方向別mapの独立複写です。
func cloneCurrent(c CurrentEvidence) CurrentEvidence {
	for _, support := range []*far81.CurrentSupport{&c.Buy, &c.Sell} {
		if support.Windows != nil {
			windows := map[string]far81.CurrentSupportWindow{}
			for key, value := range support.Windows {
				windows[key] = value
			}
			support.Windows = windows
		}
	}
	return c
}

// auxiliaryValue は個別に既知の符号だけを状態へ写します。
//
// 引数: known(bool)、value(float64)、reason(string)は観測の利用可能性です。
// 返り値: AuxiliaryValueは未知を0又は反対へ変換しない状態です。
func auxiliaryValue(known bool, value float64, reason string) AuxiliaryValue {
	v := AuxiliaryValue{State: "未知", Reason: reason}
	if !known || !finiteEntry(value) {
		return v
	}
	v.Known, v.Value = true, &value
	v.State = "中立"
	if value > 0 {
		v.State = "支持"
	} else if value < 0 {
		v.State = "反対"
	}
	return v
}

// shortValue は元Short窓の単位と当時の両端を確認して方向別速度へ写します。
//
// 引数: w(CurrentShortWindow)、short(CurrentShort)、c(CurrentEvidence)、horizon/side(float64)です。
// 返り値: AuxiliaryValueは既知のpt/秒又は理由付き未知です。
func shortValue(w CurrentShortWindow, short CurrentShort, c CurrentEvidence, horizon, side float64) AuxiliaryValue {
	reason := w.Reason
	known := w.Known && finiteEntry(w.Move, w.Speed, w.Elapsed, w.Endpoint, w.Delay, short.Time, short.Mid) && short.Time == c.Time && short.Mid > 0 && short.Mid == c.Bid+(c.Ask-c.Bid)/2 && w.Elapsed >= horizon && w.Elapsed == short.Time-w.Endpoint && w.Endpoint <= short.Time-horizon && w.Delay == w.Elapsed-horizon && w.Delay >= 0 && w.Delay <= 15
	if known {
		known = math.Abs(w.Speed-w.Move/w.Elapsed) <= 1e-12*math.Max(1, math.Abs(w.Speed))
	}
	if w.Known && !known {
		reason = "元短秒の単位・有限性・両端時計が不整合"
	}
	return auxiliaryValue(known, side*w.Speed, reason)
}

// freshBarrier は同価格回復点が当時の60秒・32更新以内かを検査します。
//
// 引数: b(far81.CurrentBarrier)、at(float64)、event/index(int64)は現在の源番号です。
// 返り値: boolは未来を含まない新鮮な既知点なら真です。
func freshBarrier(b far81.CurrentBarrier, at float64, event, index int64) bool {
	return b.Known && finiteEntry(b.Price, b.Time, at) && b.Price > 0 && b.Index >= 0 && b.Index <= index && b.Event >= 0 && b.Event <= event && at >= b.Time && at-b.Time <= 60 && event-b.Event <= 32
}

// validBarrier は既知回復点に未来や不正価格がないかを検査します。
//
// 引数: b(far81.CurrentBarrier)、c(CurrentEvidence)は回復点と当時入力です。
// 返り値: boolは未知点又は当時までの正常点なら真です。
func validBarrier(b far81.CurrentBarrier, c CurrentEvidence) bool {
	return !b.Known || (finiteEntry(b.Price, b.Time) && b.Price > 0 && b.Time <= c.Time && b.Index >= 0 && b.Index <= c.SourceIndex && b.Event >= 0 && b.Event <= c.Night.PriceEvent)
}

// structureState は81と同じ現在帯・同価格数量支持・反対圧力を分けます。
//
// 引数: at(float64)、q(Quote)、c(CurrentEvidence)、side(int)は片側の当時入力です。
// 返り値: known/band/quantity/pressureClear(bool)は構造の既知性と各成立です。
func structureState(at float64, q Quote, c CurrentEvidence, side int) (known, band, quantity, pressureClear bool) {
	n := c.Night
	hold, opposite := n.Buy, n.Sell
	liquidation := q.Bid
	if side < 0 {
		hold, opposite = n.Sell, n.Buy
		liquidation = q.Ask
	}
	s := float64(side)
	known = n.Available && n.Known && !n.Invalid && n.Window == "E08" && n.Band.Known && n.Time == c.Time && n.Index == c.SourceIndex && n.PriceEvent >= 0 && n.Band.Index == c.SourceIndex && n.Band.StartIndex >= 0 && n.Band.StartIndex <= n.Band.Index && finiteEntry(n.Band.Time, n.Band.StartTime, n.Time, hold.Bid, hold.Ask, hold.Time) && n.Band.Time == c.Time && n.Band.StartTime <= n.Band.Time && hold.Time <= c.Time && hold.Index >= 0 && hold.Index <= c.SourceIndex && hold.Event >= 0 && hold.Event <= n.PriceEvent && validBarrier(hold.Barrier, c) && validBarrier(hold.Support, c) && validBarrier(opposite.Support, c)
	band = known && hold.Active && hold.Side == side && !hold.Pressured && hold.Bid > 0 && hold.Ask > hold.Bid && at >= hold.Time && at-hold.Time <= 60 && n.PriceEvent-hold.Event <= 32 && s*(q.Bid-hold.Bid) >= 0 && s*(q.Ask-hold.Ask) >= 0
	quantity = known && hold.QuantitySupport && freshBarrier(hold.Support, at, n.PriceEvent, c.SourceIndex)
	barrierFresh := freshBarrier(hold.Barrier, at, n.PriceEvent, c.SourceIndex)
	passed := !barrierFresh || s*(liquidation-hold.Barrier.Price) >= 10
	oppositePressure := opposite.Active && opposite.QuantitySupport && freshBarrier(opposite.Support, at, n.PriceEvent, c.SourceIndex) && finiteEntry(opposite.Time) && at >= opposite.Time && at-opposite.Time <= 60 && opposite.Index >= 0 && opposite.Index <= c.SourceIndex && opposite.Event >= 0 && opposite.Event <= n.PriceEvent && n.PriceEvent-opposite.Event <= 32
	pressureClear = known && passed && !oppositePressure
	return
}

// evaluateDirection は背景・現在・取得位置・補助の役割を片側で評価します。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、c(CurrentEvidence)、policy(string)、side(int)です。
// 返り値: EntryDirectionは未知と既知の不成立を別記した判定です。
func evaluateDirection(at float64, q Quote, chart ChartView, c CurrentEvidence, policy string, side int) EntryDirection {
	d := EntryDirection{EntryDirection: far81.EntryDirection{Side: side, Role: "待機", Checks: []far81.EntryCheck{}}}
	add := func(group, id string, known, passed bool, reason string) bool {
		d.Checks = append(d.Checks, far81.EntryCheck{ID: id, Group: group, Known: known, Passed: known && passed, Reason: reason})
		return known && passed
	}
	mandatory := func(id string, known, passed bool, reason string) bool {
		if !known {
			d.RequiredUnknown = true
		}
		return add("共通", id, known, passed, reason)
	}
	t, s := chart.Technical, float64(side)
	support, entry := c.Buy, q.Ask
	if side < 0 {
		support, entry = c.Sell, q.Bid
	}
	d.EntryPrice = entry
	valid := mandatory("政策", true, policy == "B0" || policy == "B1", "B0は反対拒否、B1は既知失速時の追加支持")
	valid = mandatory("参照市場", true, c.Reference == "NK225", "当時特徴はNK225ラージ") && valid
	quoteKnown := finiteEntry(at, q.Time, q.Last, q.Bid, q.Ask, c.Time, c.Received, c.Last, c.Bid, c.Ask)
	valid = mandatory("自己現在", quoteKnown, q.Valid && q.Index >= 0 && q.Last > 0 && q.Bid > 0 && q.Ask > q.Bid && q.Time <= at && at-q.Time <= 15 && c.Time == q.Time && c.Received >= c.Time && c.Received <= at && c.SourceLine > 0 && c.SourceLine == q.Line && c.SourceIndex >= 0 && c.Last == q.Last && c.Bid == q.Bid && c.Ask == q.Ask, "同物理行・正常気配・自己15秒以内") && valid
	current3 := finiteEntry(t.Bar3End, at) && t.Bar3End > 0 && t.Bar3End <= at && at-t.Bar3End <= 180
	valid = mandatory("確定3分時計", current3, current3, "現3分足は公開済み180秒以内") && valid
	pairKnown := chart.Previous3Known && finiteEntry(chart.PreviousClose3, chart.PreviousEMA8_3, chart.PreviousBar3End) && chart.PreviousClose3 > 0 && chart.PreviousEMA8_3 > 0 && chart.PreviousBar3End > 0 && t.Bar3End-chart.PreviousBar3End == 180
	valid = mandatory("直前3分結合", pairKnown, pairKnown, "同計算器の連続180秒の直前Close/EMA、hist/RSI結合") && valid
	progressKnown := t.ExitKnown && finiteEntry(t.Close3, t.EMA8_3, t.Histogram3, t.PreviousHistogram3) && t.Close3 > 0 && t.EMA8_3 > 0
	valid = mandatory("現在の勢い", progressKnown, s*(t.Histogram3-t.PreviousHistogram3) > 0, "3分MACDhist増分は実方向へstrict正") && valid
	valid = mandatory("終値回復", progressKnown, s*(t.Close3-t.EMA8_3) > 0, "現確定終値が現EMA8の方向側") && valid
	placementKnown := t.ATRKnown && finiteEntry(entry, t.EMA8_3, t.ATR3) && t.EMA8_3 > 0 && t.ATR3 > 0
	if placementKnown {
		d.PlacementPoints = s * (entry - t.EMA8_3)
		ratio := d.PlacementPoints / t.ATR3
		d.PlacementATR = &ratio
	}
	valid = mandatory("取得位置", placementKnown, d.PlacementPoints >= 0 && d.PlacementPoints <= t.ATR3, "新規側BBOはEMA8方向側0..1ATR") && valid
	spikeKnown := t.SpikeKnown && finiteEntry(t.TR3, t.PreviousATR3, t.RSI3, t.PreviousRSI3) && t.TR3 >= 0 && t.PreviousATR3 >= 0 && t.RSI3 >= 0 && t.RSI3 <= 100 && t.PreviousRSI3 >= 0 && t.PreviousRSI3 <= 100
	spike := t.TR3 > 2*t.PreviousATR3 && math.Abs(t.RSI3-t.PreviousRSI3) > 15
	valid = mandatory("同時スパイク", spikeKnown, !spike, "TRが前ATR2倍超かつRSI差15超を拒否") && valid

	// ----------------------------------------
	// 補助未知は必須チャートと分け、既知の反対だけを拒否へ使います。
	a := &d.Auxiliary
	a.Five = shortValue(c.Short.Five, c.Short, c, 5, s)
	a.Fifteen = shortValue(c.Short.Fifteen, c.Short, c, 15, s)
	ofiKnown := support.OFIKnown && finiteEntry(support.OFI30, support.OwnAt) && support.OwnAt == c.Time
	ofiReason := support.OFIReason
	if support.OFIKnown && !ofiKnown {
		ofiReason = "元OFIの有限性・現在時計が不整合"
	}
	a.OFI = auxiliaryValue(ofiKnown, s*support.OFI30, ofiReason)
	opposition := false
	for _, value := range []struct {
		id string
		v  AuxiliaryValue
	}{{"5秒補助", a.Five}, {"15秒補助", a.Fifteen}, {"OFI補助", a.OFI}} {
		add("補助状態", value.id, value.v.Known, value.v.State != "反対", value.v.State+":"+value.v.Reason)
		if value.v.Known && value.v.State == "反対" {
			opposition = true
		}
	}
	valid = add("補助集約", "既知反対なし", true, !opposition, "各個別既知の反対だけ拒否、未知状態は別保存") && valid
	a.SlowdownKnown = a.Five.Known && a.Fifteen.Known
	if a.SlowdownKnown {
		a.Slowdown = *a.Fifteen.Value > 0 && *a.Five.Value <= .5*(*a.Fifteen.Value)
	}
	structureKnown, band, quantity, pressureClear := structureState(at, q, c, side)
	a.StructureKnown, a.StructureSupport, a.PressureClear = structureKnown, band && quantity, pressureClear
	add("補助状態", "既知失速", a.SlowdownKnown, a.Slowdown, "pt/秒で両窓既知・v15>0・v5<=0.5v15")
	if policy == "B1" && a.SlowdownKnown && a.Slowdown {
		positive := a.OFI.State == "支持" || a.StructureSupport
		confirmationKnown := positive || (a.OFI.Known && structureKnown)
		if !confirmationKnown {
			d.RequiredUnknown = true
		}
		valid = add("失速時確認", "追加支持", confirmationKnown, positive, "失速時だけ既知OFI正又は新鮮帯と数量支持") && valid
	}

	// ----------------------------------------
	// 背景一致を順行、実際の平均回復と現在構造を転換初動に使います。
	trendKnown := t.TrendKnown && finiteEntry(t.EMA8_3, t.EMA21_3, t.EMA8_15, t.EMA21_15, t.Bar15End) && t.EMA8_3 > 0 && t.EMA21_3 > 0 && t.EMA8_15 > 0 && t.EMA21_15 > 0 && t.Bar15End > 0 && t.Bar15End <= at && at-t.Bar15End <= 900
	trend := trendKnown && s*(t.EMA8_3-t.EMA21_3) > 0 && s*(t.EMA8_15-t.EMA21_15) > 0
	add("順行枝", "複数尺度方向", trendKnown, trend, "3/15分EMA方向一致、15分は公開済み900秒以内")
	rsiKnown := spikeKnown && pairKnown
	rsiImproved := rsiKnown && s*(t.RSI3-t.PreviousRSI3) > 0
	recrossKnown := pairKnown && progressKnown
	recross := recrossKnown && s*(chart.PreviousClose3-chart.PreviousEMA8_3) <= 0 && s*(t.Close3-t.EMA8_3) > 0
	add("転換初動枝", "RSI増分", rsiKnown, rsiImproved, "RSI50交差を待たず実方向の増分を確認")
	add("転換初動枝", "直前平均からの回復", recrossKnown, recross, "直前Closeと直前EMA8は同足、現在の平均回復へ結ぶ")
	add("転換初動枝", "現在価格帯", structureKnown, band, "81と同じ60秒/32更新以内の両気配維持")
	add("転換初動枝", "同価格数量支持", structureKnown, quantity, "同価格回復点の現在鮮度を確認")
	add("転換初動枝", "反対圧力", structureKnown, pressureClear, "fresh反対帯は10pt通過、反対数量支持なし")
	initial := rsiImproved && recross && band && quantity && pressureClear
	initialUnknown := (!rsiKnown || !recrossKnown) || (rsiImproved && recross && !structureKnown)
	if valid && (trend || initial) {
		d.Allowed, d.RequiredUnknown, d.Role = true, false, "順行"
		if !trend {
			d.Role = "転換初動"
		}
		d.Reason = d.Role + "の現在根拠成立"
		return d
	}
	if !trend && !initial && (!trendKnown || initialUnknown) {
		d.RequiredUnknown = true
	}
	if d.RequiredUnknown {
		d.Role = "判定不能"
	}
	reasons := []string{}
	for _, check := range d.Checks {
		if !check.Known {
			reasons = append(reasons, check.ID+"未知")
		} else if !check.Passed {
			reasons = append(reasons, check.ID+"不成立")
		}
	}
	d.Reason = strings.Join(reasons, "／")
	return d
}

// resolveEntry は両方向の独立判定を一つの売買・待機へまとめます。
//
// 引数: d(*EntryDecision)は2方向を保持した判定です。
// 返り値: ありません。競合時は方向を消し、必須未知を区別します。
func resolveEntry(d *EntryDecision) {
	count := 0
	for _, direction := range d.Directions {
		if direction.Allowed {
			count++
			d.Side, d.Role, d.Reason = direction.Side, direction.Role, direction.Reason
		}
		d.RequiredUnknown = d.RequiredUnknown || direction.RequiredUnknown
	}
	if count == 1 {
		d.Allowed, d.RequiredUnknown = true, false
	} else if count > 1 {
		d.Side, d.Role, d.Reason, d.RequiredUnknown = 0, "競合待機", "両方向の現在根拠が競合", false
	} else {
		if d.RequiredUnknown {
			d.Role = "判定不能"
		}
		if len(d.Directions) == 2 {
			d.Reason = "買:" + d.Directions[0].Reason + "／売:" + d.Directions[1].Reason
		}
	}
}

// Decide は同時点の公開足と現在特徴から両方向の直接新規判断を作ります。
//
// 引数: at(float64)、q(Quote)、chart(ChartView)、c(CurrentEvidence)、policy(string)です。
// 返り値: EntryDecisionは未来の約定や参照保有へ依存しない判断です。
func Decide(at float64, q Quote, chart ChartView, c CurrentEvidence, policy string) EntryDecision {
	d := EntryDecision{At: at, Policy: policy, Role: "待機", Reason: "現在の新規根拠なし", Quote: q, Technical: chart.Technical, ChartPair: ChartPair{chart.PreviousClose3, chart.PreviousEMA8_3, chart.PreviousBar3End, chart.Previous3Known}, Evidence: cloneCurrent(c), Directions: []EntryDirection{}}
	for _, side := range []int{1, -1} {
		d.Directions = append(d.Directions, evaluateDirection(at, q, chart, d.Evidence, policy, side))
	}
	resolveEntry(&d)
	return d
}

// Candidate は許可した定時判断をG1会計へ渡す最大1候補へ写します。
//
// 引数: sessionID/window(string)は場と時間枠、quantity(int)は固定枚数です。
// 返り値: ReferenceFrameは当時新規BBOの1候補又は空値です。
func (d EntryDecision) Candidate(sessionID, window string, quantity int) ReferenceFrame {
	f := ReferenceFrame{Lots: []ReferenceLot{}, Closes: []ReferenceClose{}}
	if !d.Allowed || (d.Side != 1 && d.Side != -1) || (d.Policy != "B0" && d.Policy != "B1") || sessionID == "" || window == "" || window == "静観" || quantity <= 0 || !finiteEntry(d.At, d.Quote.Time, d.Quote.Last, d.Quote.Bid, d.Quote.Ask) || !d.Quote.Valid || d.Quote.Index < 0 || d.Quote.Line <= 0 || d.Quote.Last <= 0 || d.Quote.Time > d.At || d.At-d.Quote.Time > 15 || d.Quote.Bid <= 0 || d.Quote.Ask <= d.Quote.Bid {
		return f
	}
	entry := d.Quote.Ask
	if d.Side < 0 {
		entry = d.Quote.Bid
	}
	id := fmt.Sprintf("%s_%s_%s_%+d", sessionID, d.Policy, strconv.FormatFloat(d.At, 'f', 9, 64), d.Side)
	f.Lots = append(f.Lots, ReferenceLot{ID: id, InternalID: id, Parent: id, SourceID: id, Method: window, Owner: d.Policy, Kind: d.Role, Side: d.Side, Quantity: quantity, Entry: entry, At: d.At})
	return f
}
