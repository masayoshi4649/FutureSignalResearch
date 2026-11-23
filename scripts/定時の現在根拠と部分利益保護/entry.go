package far81

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// CurrentSupportWindow は支持窓の元単位・過去端・未知理由を保存します。
type CurrentSupportWindow struct {
	Known           bool    `json:"known"`
	Reason          string  `json:"reason"`
	CurrentAt       float64 `json:"current_at"`
	EndpointAt      float64 `json:"endpoint_at"`
	Elapsed         float64 `json:"elapsed"`
	Delay           float64 `json:"delay"`
	RawReturn       float64 `json:"raw_return"`
	Value           float64 `json:"value"`
	IntermediateBad int64   `json:"intermediate_bad"`
}

// CurrentSupport は方向ごとの現在支持と、その既知性を保存します。
// M/Tは元の未校正支持であり、確率ではありません。
type CurrentSupport struct {
	Known      bool                            `json:"known"`
	Reason     string                          `json:"reason"`
	OwnKnown   bool                            `json:"own_known"`
	PeerKnown  bool                            `json:"peer_known"`
	OFIKnown   bool                            `json:"ofi_known"`
	OwnReason  string                          `json:"own_reason"`
	PeerReason string                          `json:"peer_reason"`
	OFIReason  string                          `json:"ofi_reason"`
	Own5       float64                         `json:"own5"`
	Own15      float64                         `json:"own15"`
	Own120     float64                         `json:"own120"`
	Own300     float64                         `json:"own300"`
	Peer120    float64                         `json:"peer120"`
	OFI30      float64                         `json:"ofi30"`
	M          float64                         `json:"m"`
	T          float64                         `json:"t"`
	Opp        float64                         `json:"opp"`
	OwnAt      float64                         `json:"own_at"`
	PeerAt     float64                         `json:"peer_at"`
	Windows    map[string]CurrentSupportWindow `json:"windows,omitempty"`
}

// CurrentBarrier は同価格数量回復の元観測を表し、実約定の出来高ではありません。
type CurrentBarrier struct {
	Known bool    `json:"known"`
	Price float64 `json:"price"`
	Time  float64 `json:"time"`
	Index int64   `json:"index"`
	Event int64   `json:"event"`
}

// CurrentPriceBand は証券建玉と独立した、現在の価格帯維持状態です。
type CurrentPriceBand struct {
	Active          bool           `json:"active"`
	QuantitySupport bool           `json:"quantity_support"`
	SupplyPassed    bool           `json:"supply_passed"`
	Pressured       bool           `json:"pressured"`
	ID              int            `json:"id"`
	Side            int            `json:"side"`
	Bid             float64        `json:"bid"`
	Ask             float64        `json:"ask"`
	Time            float64        `json:"time"`
	Index           int64          `json:"index"`
	Event           int64          `json:"event"`
	PressureEvent   int64          `json:"pressure_event"`
	PressureIndex   int64          `json:"pressure_index"`
	Barrier         CurrentBarrier `json:"barrier"`
	Support         CurrentBarrier `json:"support"`
}

// CurrentBandWindow は現在E08窓の価格・数量変化を元単位のまま保存します。
// Lineは元Features内のIndex代理であり、CurrentEvidence.SourceLineの物理原行とは別です。
type CurrentBandWindow struct {
	Known             bool    `json:"known"`
	QuantityKnown     bool    `json:"quantity_known"`
	StartIndex        int64   `json:"start_index"`
	Index             int64   `json:"index"`
	StartLine         int64   `json:"start_line"`
	Line              int64   `json:"line"`
	StartTime         float64 `json:"start_time"`
	Time              float64 `json:"time"`
	Elapsed           float64 `json:"elapsed"`
	Events            int     `json:"events"`
	QuantityEvents    int     `json:"quantity_events"`
	BadQuantity       int     `json:"bad_quantity"`
	CommonDepthEvents int     `json:"common_depth_events"`
	BidMove           float64 `json:"bid_move"`
	AskMove           float64 `json:"ask_move"`
	MidMove           float64 `json:"mid_move"`
	Spread            float64 `json:"spread"`
	SpreadChange      float64 `json:"spread_change"`
	UpFraction        float64 `json:"up_fraction"`
	GrossPriceMove    float64 `json:"gross_price_move"`
	BidOnlyUp         float64 `json:"bid_only_up"`
	AskOnlyDown       float64 `json:"ask_only_down"`
	AskOnlyUp         float64 `json:"ask_only_up"`
	BidOnlyDown       float64 `json:"bid_only_down"`
	BidRefill         float64 `json:"bid_refill"`
	AskRefill         float64 `json:"ask_refill"`
	BidDeplete        float64 `json:"bid_deplete"`
	AskDeplete        float64 `json:"ask_deplete"`
	CommonBidUp       float64 `json:"common_bid_up"`
	CommonAskUp       float64 `json:"common_ask_up"`
	CommonBidDown     float64 `json:"common_bid_down"`
	CommonAskDown     float64 `json:"common_ask_down"`
}

// CurrentStructure は全原行で進んだ価格帯であり、参照Portfolioの所有ではありません。
type CurrentStructure struct {
	Available     bool              `json:"available"`
	Known         bool              `json:"known"`
	Invalid       bool              `json:"invalid"`
	Window        string            `json:"window"`
	Time          float64           `json:"time"`
	Index         int64             `json:"index"`
	PriceEvent    int64             `json:"price_event"`
	ConfirmedSide int               `json:"confirmed_side"`
	RetestSide    int               `json:"retest_side"`
	RetestID      int               `json:"retest_id"`
	RetestHoldID  int               `json:"retest_hold_id"`
	Band          CurrentBandWindow `json:"band"`
	Buy           CurrentPriceBand  `json:"buy"`
	Sell          CurrentPriceBand  `json:"sell"`
}

// CurrentEvidence は元特徴器の連番と物理原行を分ける再利用可能な現在入力です。
type CurrentEvidence struct {
	Reference   string           `json:"reference"`
	Time        float64          `json:"time"`
	Received    float64          `json:"received"`
	SourceIndex int64            `json:"source_index"`
	SourceLine  int64            `json:"source_line"`
	Last        float64          `json:"last"`
	Bid         float64          `json:"bid"`
	Ask         float64          `json:"ask"`
	Buy         CurrentSupport   `json:"buy"`
	Sell        CurrentSupport   `json:"sell"`
	Night       CurrentStructure `json:"night"`
}

// EntryCheck は既知性と条件不一致を分けた、一つの評価項目です。
type EntryCheck struct {
	ID     string `json:"id"`
	Group  string `json:"group"`
	Known  bool   `json:"known"`
	Passed bool   `json:"passed"`
	Reason string `json:"reason"`
}

// EntryDirection は片側の理由・想定取得値・複合判断を保存します。
type EntryDirection struct {
	Side            int          `json:"side"`
	Allowed         bool         `json:"allowed"`
	Role            string       `json:"role"`
	Reason          string       `json:"reason"`
	EntryPrice      float64      `json:"entry_price"`
	PlacementPoints float64      `json:"placement_points"`
	PlacementATR    *float64     `json:"placement_atr"`
	Checks          []EntryCheck `json:"checks"`
}

// EntryDecision は定時に使った全入力と両方向の評価を保持します。
type EntryDecision struct {
	At         float64          `json:"at"`
	Policy     string           `json:"policy"`
	Allowed    bool             `json:"allowed"`
	Side       int              `json:"side"`
	Role       string           `json:"role"`
	Reason     string           `json:"reason"`
	Quote      Quote            `json:"quote"`
	Technical  TechnicalView    `json:"technical"`
	Evidence   CurrentEvidence  `json:"evidence"`
	Directions []EntryDirection `json:"directions"`
}

// copyCurrentSupport は元の方向支持を未知理由・窓metadataとともに独立複写します。
//
// 引数: s(strategy.SelectedDay164Support)は現在支持です。
// 返り値: CurrentSupportは元mapへの可変参照を持たない値です。
func copyCurrentSupport(s strategy.SelectedDay164Support) CurrentSupport {
	o := CurrentSupport{Known: s.Known, Reason: s.Reason, Own5: s.Own5, Own15: s.Own15, Own120: s.Own120, Own300: s.Own300, Peer120: s.Peer120, OFI30: s.OFI30, M: s.M, T: s.T, Opp: s.Opp, OwnAt: s.OwnAt, PeerAt: s.PeerAt}
	if c := s.Components; c != nil {
		o.OwnKnown, o.PeerKnown, o.OFIKnown = c.OwnKnown, c.PeerKnown, c.OFIKnown
		o.OwnReason, o.PeerReason, o.OFIReason = c.OwnReason, c.PeerReason, c.OFIReason
		if c.Windows != nil {
			o.Windows = map[string]CurrentSupportWindow{}
			for k, v := range c.Windows {
				o.Windows[k] = CurrentSupportWindow{v.Known, v.Reason, v.CurrentAt, v.EndpointAt, v.Elapsed, v.Delay, v.RawReturn, v.Value, v.IntermediateBad}
			}
		}
	}
	return o
}

// ExtractCurrent は公開fieldから、保有参照を必要としない現在入力を作ります。
//
// 引数: o(strategy.Observation)は最後の元特徴、rawLine(int64)はその物理原行です。
// 返り値: CurrentEvidenceは価格帯の時点情報を含む独立した入力です。
func ExtractCurrent(o strategy.Observation, rawLine int64) CurrentEvidence {
	c := CurrentEvidence{Reference: o.Reference, Time: o.Time, Received: o.Received, SourceIndex: o.Index, SourceLine: rawLine, Last: o.Last, Bid: o.Bid, Ask: o.Ask, Buy: copyCurrentSupport(o.Selected.DayBuy), Sell: copyCurrentSupport(o.Selected.DaySell)}
	n := o.Selected.Night
	b := n.Band
	c.Night = CurrentStructure{Available: o.Selected.NightAvailable, Known: n.Known, Invalid: n.Invalid, Window: n.Window, Time: o.Selected.NightTime, Index: o.Selected.NightIndex, PriceEvent: n.PriceEvent, ConfirmedSide: n.ConfirmedSide, RetestSide: n.RetestSide, RetestID: n.RetestID, RetestHoldID: n.RetestHoldID, Band: CurrentBandWindow{Known: b.Known, QuantityKnown: b.QuantityKnown, StartIndex: b.StartIndex, Index: b.Index, StartLine: b.StartLine, Line: b.Line, StartTime: b.StartTime, Time: b.Time, Elapsed: b.Elapsed, Events: b.Events, QuantityEvents: b.QuantityEvents, BadQuantity: b.BadQuantity, CommonDepthEvents: b.CommonDepthEvents, BidMove: b.BidMove, AskMove: b.AskMove, MidMove: b.MidMove, Spread: b.Spread, SpreadChange: b.SpreadChange, UpFraction: b.UpFraction, GrossPriceMove: b.GrossPriceMove, BidOnlyUp: b.BidOnlyUp, AskOnlyDown: b.AskOnlyDown, AskOnlyUp: b.AskOnlyUp, BidOnlyDown: b.BidOnlyDown, BidRefill: b.BidRefill, AskRefill: b.AskRefill, BidDeplete: b.BidDeplete, AskDeplete: b.AskDeplete, CommonBidUp: b.CommonBidUp, CommonAskUp: b.CommonAskUp, CommonBidDown: b.CommonBidDown, CommonAskDown: b.CommonAskDown}}
	// ----------------------------------------
	// 価格帯のHoldは証券建玉と無関係で、源Index/Eventをそのまま区別して保存します。
	for _, side := range []int{1, -1} {
		h := n.Buy
		if side < 0 {
			h = n.Sell
		}
		p := CurrentPriceBand{Active: h.Active, QuantitySupport: h.QuantitySupport, SupplyPassed: h.SupplyPassed, Pressured: h.Pressured, ID: h.ID, Side: h.Side, Bid: h.Bid, Ask: h.Ask, Time: h.Time, Index: h.Index, Event: h.Event, PressureEvent: h.PressureEvent, PressureIndex: h.PressureIndex, Barrier: CurrentBarrier{h.Barrier.Known, h.Barrier.Price, h.Barrier.Time, h.Barrier.Index, h.Barrier.Event}, Support: CurrentBarrier{h.Support.Known, h.Support.Price, h.Support.Time, h.Support.Index, h.Support.Event}}
		if side > 0 {
			c.Night.Buy = p
		} else {
			c.Night.Sell = p
		}
	}
	return c
}

// finiteEntry は入口に使う数値の有限性をまとめて検査します。
//
// 引数: values(...float64)は必要な観測数値です。
// 返り値: boolは全て有限なら真です。
func finiteEntry(values ...float64) bool {
	for _, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// cloneCurrent は保持した窓mapを入力側から分離します。
//
// 引数: c(CurrentEvidence)は現在入力です。
// 返り値: CurrentEvidenceは窓mapの独立複写です。
func cloneCurrent(c CurrentEvidence) CurrentEvidence {
	for _, side := range []int{1, -1} {
		s := &c.Buy
		if side < 0 {
			s = &c.Sell
		}
		if s.Windows != nil {
			m := map[string]CurrentSupportWindow{}
			for k, v := range s.Windows {
				m[k] = v
			}
			s.Windows = m
		}
	}
	return c
}

// freshBarrier は元の数量回復点が当時の時計・更新数でまだ有効かを検査します。
//
// 引数: b(CurrentBarrier)、at(float64)、event/index(int64)は現在の源番号です。
// 返り値: boolは既知の正価格で未来がなく60秒/32更新以内なら真です。
func freshBarrier(b CurrentBarrier, at float64, event, index int64) bool {
	return b.Known && finiteEntry(b.Price, b.Time, at) && b.Price > 0 && b.Index >= 0 && b.Index <= index && b.Event >= 0 && b.Event <= event && at >= b.Time && at-b.Time <= 60 && event-b.Event <= 32
}

// validBarrier は既知の回復点に未来や壊れた値が混じっていないか検査します。
//
// 引数: b(CurrentBarrier)、c(CurrentEvidence)は回復点と当時観測です。
// 返り値: boolは未観測又は当時までの有限正価格なら真です。
func validBarrier(b CurrentBarrier, c CurrentEvidence) bool {
	return !b.Known || (finiteEntry(b.Price, b.Time) && b.Price > 0 && b.Time <= c.Time && b.Index >= 0 && b.Index <= c.SourceIndex && b.Event >= 0 && b.Event <= c.Night.PriceEvent)
}

// evaluateDirection は一つの方向を他方向と同じ符号式で評価します。
//
// 引数: at(float64)、q(Quote)、t(TechnicalView)、c(CurrentEvidence)、policy(string)、side(int)です。
// 返り値: EntryDirectionは未知を条件不一致と分けた評価です。
func evaluateDirection(at float64, q Quote, t TechnicalView, c CurrentEvidence, policy string, side int) EntryDirection {
	d := EntryDirection{Side: side, Role: "待機", Checks: []EntryCheck{}}
	add := func(id string, known, passed bool, reason string) bool {
		group := "共通"
		if id == "順行枝" {
			group = "順行枝"
		}
		if id == "転換勢い" || id == "現在価格帯" || id == "同価格数量支持" || id == "反対圧力" {
			group = "転換初動枝"
		}
		d.Checks = append(d.Checks, EntryCheck{ID: id, Group: group, Known: known, Passed: known && passed, Reason: reason})
		return known && passed
	}
	s := float64(side)
	support := c.Buy
	d.EntryPrice = q.Ask
	if side < 0 {
		support = c.Sell
		d.EntryPrice = q.Bid
	}
	d.PlacementPoints = s * (d.EntryPrice - t.EMA8_3)
	if t.ATRKnown && finiteEntry(t.ATR3) && t.ATR3 > 0 {
		v := d.PlacementPoints / t.ATR3
		d.PlacementATR = &v
	}
	valid := add("政策", true, policy == "B0" || policy == "B1", "入口政策はB0/B1")
	valid = add("参照市場", true, c.Reference == "NK225", "当時特徴はNK225ラージ") && valid
	valid = add("自己現在", finiteEntry(at, q.Time, q.Last, q.Bid, q.Ask, c.Time, c.Received, c.Last, c.Bid, c.Ask), q.Valid && q.Index >= 0 && q.Last > 0 && q.Bid > 0 && q.Ask > q.Bid && q.Time <= at && at-q.Time <= 15 && c.Time == q.Time && c.Received >= c.Time && c.Received <= at && c.SourceLine > 0 && c.SourceLine == q.Line && c.SourceIndex >= 0 && c.Last == q.Last && c.Bid == q.Bid && c.Ask == q.Ask, "同物理行の正常気配と15秒以内の当時入力") && valid
	known := support.Known && support.OwnKnown && support.PeerKnown && support.OFIKnown && finiteEntry(support.Own5, support.Own15, support.Own120, support.Own300, support.Peer120, support.OFI30, support.M, support.T, support.Opp, support.OwnAt, support.PeerAt)
	valid = add("支持既知", known, known, "自己4窓・相手・OFIの全既知性") && valid
	valid = add("支持時計", known, support.OwnAt == c.Time && support.PeerAt < c.Time && support.PeerAt <= at && at-support.PeerAt <= 15, "相手はstrict過去かつ定時から15秒以内") && valid
	valid = add("現在支持", known, s*support.Own5 > 0 && s*support.Own15 > 0 && s*support.Peer120 >= 0 && s*support.OFI30 > 0, "自己5/15秒・相手120秒・OFI30秒の方向") && valid
	valid = add("確定3分時計", finiteEntry(t.Bar3End) && t.Bar3End > 0, t.Bar3End <= at, "必要な3分足の終端が定時までに公開済み") && valid
	spikeKnown := t.SpikeKnown && finiteEntry(t.TR3, t.PreviousATR3, t.RSI3, t.PreviousRSI3) && t.TR3 >= 0 && t.PreviousATR3 >= 0 && t.RSI3 >= 0 && t.RSI3 <= 100 && t.PreviousRSI3 >= 0 && t.PreviousRSI3 <= 100
	spike := t.TR3 > 2*t.PreviousATR3 && math.Abs(t.RSI3-t.PreviousRSI3) > 15
	valid = add("同時スパイク", spikeKnown, !spike, "TRが前ATR2倍超かつRSI差15超を拒否") && valid
	// ----------------------------------------
	// B0は既存の確定足入口、B1は取得位置と転換初動の別経路を持ちます。
	if policy == "B0" {
		checked := t
		checked.TrendKnown = t.TrendKnown && finiteEntry(t.EMA8_3, t.EMA21_3, t.EMA8_15, t.EMA21_15, t.Bar15End) && t.Bar15End > 0 && t.Bar15End <= at
		checked.ReversalKnown = t.ReversalKnown && finiteEntry(t.RSI3, t.PreviousRSI3, t.Histogram3, t.PreviousHistogram3, t.Close3, t.EMA8_3)
		allowed, role, reason := checked.Entry(side)
		techKnown := checked.TrendKnown || checked.ReversalKnown
		valid = add("既存確定足", techKnown, allowed, reason) && valid
		valid = add("中期短期支持", known, support.M > 0 && support.T > 0, "未校正M/Tともstrict正") && valid
		if valid {
			d.Allowed, d.Role = true, role
		}
	} else if policy == "B1" {
		placementKnown := t.ATRKnown && finiteEntry(t.ATR3, t.EMA8_3, d.PlacementPoints) && t.ATR3 > 0
		valid = add("取得位置", placementKnown, d.PlacementPoints >= 0 && d.PlacementPoints <= t.ATR3, "想定取得BBOはEMA8実方向側の1ATR以内") && valid
		trendKnown := t.TrendKnown && finiteEntry(t.EMA8_3, t.EMA21_3, t.EMA8_15, t.EMA21_15, t.Bar15End) && t.Bar15End > 0 && t.Bar15End <= at
		trend := trendKnown && s*(t.EMA8_3-t.EMA21_3) > 0 && s*(t.EMA8_15-t.EMA21_15) > 0 && support.M > 0
		add("順行枝", trendKnown, trend, "3/15分EMA方向一致とM支持")
		turnKnown := t.ReversalKnown && finiteEntry(t.RSI3, t.PreviousRSI3, t.Histogram3, t.PreviousHistogram3, t.Close3, t.EMA8_3)
		turn := turnKnown && s*(t.RSI3-t.PreviousRSI3) > 0 && s*(t.Histogram3-t.PreviousHistogram3) > 0 && s*(t.Close3-t.EMA8_3) > 0
		add("転換勢い", turnKnown, turn, "RSI差・MACDhist差・終値回復。50交差待ちなし")
		n := c.Night
		hold, opposite := n.Buy, n.Sell
		if side < 0 {
			hold, opposite = n.Sell, n.Buy
		}
		structureKnown := n.Available && n.Known && !n.Invalid && n.Window == "E08" && n.Band.Known && n.Time == c.Time && n.Index == c.SourceIndex && n.PriceEvent >= 0 && n.Band.Index == c.SourceIndex && n.Band.StartIndex >= 0 && n.Band.StartIndex <= n.Band.Index && finiteEntry(n.Band.Time, n.Band.StartTime) && n.Band.Time == c.Time && n.Band.StartTime <= n.Band.Time && finiteEntry(hold.Bid, hold.Ask, hold.Time, n.Time) && hold.Time <= c.Time && hold.Index >= 0 && hold.Index <= c.SourceIndex && hold.Event >= 0 && hold.Event <= n.PriceEvent && validBarrier(hold.Barrier, c) && validBarrier(hold.Support, c) && validBarrier(opposite.Support, c)
		band := structureKnown && hold.Active && hold.Side == side && !hold.Pressured && hold.Bid > 0 && hold.Ask > hold.Bid && at >= hold.Time && at-hold.Time <= 60 && n.PriceEvent-hold.Event <= 32 && s*(q.Bid-hold.Bid) >= 0 && s*(q.Ask-hold.Ask) >= 0
		add("現在価格帯", structureKnown, band, "現在E08帯を60秒/32更新以内で両気配維持")
		quantity := hold.QuantitySupport && freshBarrier(hold.Support, at, n.PriceEvent, c.SourceIndex)
		add("同価格数量支持", structureKnown, quantity, "生成時の旗だけでなく回復点の現在鮮度を確認")
		liquidation := q.Bid
		if side < 0 {
			liquidation = q.Ask
		}
		barrierFresh := freshBarrier(hold.Barrier, at, n.PriceEvent, c.SourceIndex)
		passed := !barrierFresh || s*(liquidation-hold.Barrier.Price) >= 10
		oppositePressure := opposite.Active && opposite.QuantitySupport && freshBarrier(opposite.Support, at, n.PriceEvent, c.SourceIndex) && finiteEntry(opposite.Time) && at >= opposite.Time && at-opposite.Time <= 60 && opposite.Index >= 0 && opposite.Index <= c.SourceIndex && opposite.Event >= 0 && opposite.Event <= n.PriceEvent && n.PriceEvent-opposite.Event <= 32
		add("反対圧力", structureKnown, passed && !oppositePressure, "fresh反対Barrierは返済側BBOで10pt通過、反対量支持帯を拒否")
		initial := turn && band && quantity && passed && !oppositePressure
		if valid && (trend || initial) {
			d.Allowed = true
			if trend {
				d.Role = "順行"
			} else {
				d.Role = "転換初動"
			}
		}
	}
	if d.Allowed {
		d.Reason = d.Role + "の現在根拠成立"
		return d
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
	if d.Reason == "" {
		d.Reason = "入口枝不成立"
	}
	return d
}

// Decide は当時入力だけから両方向を直接判定し、競合を待機へ分けます。
//
// 引数: at(float64)は定時、q(Quote)、t(TechnicalView)、c(CurrentEvidence)、policy(string)です。
// 返り値: EntryDecisionは両方向の理由を含み、参照保有の有無には依存しません。
func Decide(at float64, q Quote, t TechnicalView, c CurrentEvidence, policy string) EntryDecision {
	d := EntryDecision{At: at, Policy: policy, Role: "待機", Reason: "現在の新規根拠なし", Quote: q, Technical: t, Evidence: cloneCurrent(c), Directions: []EntryDirection{}}
	for _, side := range []int{1, -1} {
		d.Directions = append(d.Directions, evaluateDirection(at, q, t, d.Evidence, policy, side))
	}
	count := 0
	for _, direction := range d.Directions {
		if direction.Allowed {
			count++
			d.Side, d.Role, d.Reason = direction.Side, direction.Role, direction.Reason
		}
	}
	if count == 1 {
		d.Allowed = true
	} else if count > 1 {
		d.Side, d.Role, d.Reason = 0, "競合待機", "両方向の現在根拠が競合"
	} else {
		d.Reason = "買:" + d.Directions[0].Reason + "／売:" + d.Directions[1].Reason
	}
	return d
}

// Candidate は許可された定時判断を実会計へ渡す一つの新規候補へ写します。
//
// 引数: sessionID/window(string)は場とFAR時間枠、quantity(int)は固定候補枚数です。
// 返り値: ReferenceFrameは1候補又は待機の空値です。Entryは当時BBOで未来約定ではありません。
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
