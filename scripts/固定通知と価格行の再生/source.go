// Package lighttape97 は保存通知の再構成だけを行い、Source戦略を運転しません。
package lighttape97

import (
	"encoding/json"
	"fmt"
	"reflect"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	native "github.com/masayoshi4649/SessionTradeExecuter/mininative"
)

// CancelRoute はLedgerにない取消Originを、元配送イベントから別途固定します。
type CancelRoute struct {
	Method     string  `json:"method"`
	SignalID   string  `json:"signal_id"`
	Origin     string  `json:"origin"`
	At         float64 `json:"at"`
	SourceLine int64   `json:"source_line"`
}

type eventKey struct {
	Origin string
	At     float64
	Line   int64
}
type sourceOrder struct {
	signal native.Signal
	status string
}
type sourceHold struct{ quantity, reserved, side int }

// SourceIndex は元Signal/Fill/取消の公開列と未通知量だけを保持します。
type SourceIndex struct {
	byEvent map[eventKey]map[string]native.StepResult
	orders  map[string]sourceOrder
	holds   map[string]*sourceHold
	last    map[string]native.QuoteStamp
	rows    map[string]int
}

// key は手法間で重複し得る公開IDを明示的な組へ分けます。
//
// 引数: method/id(string)は手法名と公開IDです。
// 返り値: stringは内部索引用で、公開IDを書き換えません。
func key(method, id string) string { return method + "\x00" + id }

// copyValue はRawMessageやslice/mapを共有しない検査用複写を作ります。
//
// 引数: value(T)はJSON保存可能な公開値です。
// 返り値: T/errorは値複写又は型不整合です。
func copyValue[T any](value T) (T, error) {
	var out T
	data, err := json.Marshal(value)
	if err != nil {
		return out, err
	}
	err = json.Unmarshal(data, &out)
	return out, err
}

// empty は省略した空batchを、元のAt/Origin/Lineで復元します。
//
// 引数: at(float64)、origin(string)、line(int64)は元配送の識別です。
// 返り値: native.StepResultは空配列を持つ通知容器です。
func empty(at float64, origin string, line int64) native.StepResult {
	return native.StepResult{At: at, Origin: origin, SourceLine: line, Signals: []native.SignalRecord{}, Fills: []native.FillRecord{}, Cancellations: []native.Cancellation{}, Closes: []native.CloseNotice{}}
}

// NewSourceIndex はLedgerの通知列だけを物理行/timerへ索引化します。
//
// 引数: ledgers(map[string]native.Ledger)、routes([]CancelRoute)は公開履歴と取消Originの元配送証跡です。
// 返り値: *SourceIndex/errorは独立索引又は欠落/重複。不明Originを推測しません。
func NewSourceIndex(ledgers map[string]native.Ledger, routes []CancelRoute) (*SourceIndex, error) {
	s := &SourceIndex{byEvent: map[eventKey]map[string]native.StepResult{}, orders: map[string]sourceOrder{}, holds: map[string]*sourceHold{}, last: map[string]native.QuoteStamp{}, rows: map[string]int{}}
	routeMap := map[string]CancelRoute{}
	for _, r := range routes {
		k := key(r.Method, r.SignalID)
		if _, ok := routeMap[k]; ok {
			return nil, fmt.Errorf("取消Origin重複")
		}
		if r.Origin != "quote" && r.Origin != "timer" {
			return nil, fmt.Errorf("取消Origin不正")
		}
		routeMap[k] = r
	}
	used := map[string]bool{}
	put := func(method string, k eventKey, appendRecord func(*native.StepResult)) error {
		if k.Origin == "timer" {
			k.Line = 0
		}
		if s.byEvent[k] == nil {
			s.byEvent[k] = map[string]native.StepResult{}
		}
		d, ok := s.byEvent[k][method]
		if !ok {
			d = empty(k.At, k.Origin, k.Line)
		}
		appendRecord(&d)
		s.byEvent[k][method] = d
		return nil
	}
	for method, l := range ledgers {
		if method != "D164_15" && method != "P164_06" && method != "U165_03" {
			return nil, fmt.Errorf("未知手法")
		}
		if l.Method != "NK225_"+method {
			return nil, fmt.Errorf("Ledger手法名の不一致")
		}
		for _, r := range l.Signals {
			if r.Origin != "quote" && r.Origin != "timer" {
				return nil, fmt.Errorf("Signal Origin不正")
			}
			v, err := copyValue(r)
			if err != nil {
				return nil, err
			}
			_ = put(method, eventKey{r.Origin, r.At, r.Quote.SourceLine}, func(d *native.StepResult) { d.Signals = append(d.Signals, v) })
		}
		for _, r := range l.Fills {
			v, err := copyValue(r)
			if err != nil {
				return nil, err
			}
			_ = put(method, eventKey{"quote", r.Quote.Time, r.Quote.SourceLine}, func(d *native.StepResult) { d.Fills = append(d.Fills, v) })
		}
		for _, r := range l.Cancellations {
			k := key(method, r.SignalID)
			route, ok := routeMap[k]
			if !ok {
				return nil, fmt.Errorf("取消Originの出典がありません:%s", r.SignalID)
			}
			if route.At != r.At || route.Origin == "quote" && (route.At != r.Quote.Time || route.SourceLine != r.Quote.SourceLine) {
				return nil, fmt.Errorf("取消Originの時計/物理行不整合")
			}
			used[k] = true
			v, err := copyValue(r)
			if err != nil {
				return nil, err
			}
			_ = put(method, eventKey{route.Origin, r.At, route.SourceLine}, func(d *native.StepResult) { d.Cancellations = append(d.Cancellations, v) })
		}
	}
	if len(used) != len(routeMap) {
		return nil, fmt.Errorf("未結合の取消Originがあります")
	}
	return s, nil
}

// apply はSourceの公開所有/返済予約だけを進め、CloseNotice.Beforeを復元します。
//
// 引数: method(string)、d(*native.StepResult)は当イベントの元通知です。
// 返り値: errorは先読み/未知所有/過剰予約/重複です。Sourceの判断を計算しません。
func (s *SourceIndex) apply(method string, d *native.StepResult) error {
	for _, r := range d.Signals {
		if r.Signal.Action == "new" {
			k := key(method, r.Signal.ID)
			if _, ok := s.orders[k]; ok {
				return fmt.Errorf("元new再配送")
			}
			s.orders[k] = sourceOrder{r.Signal, "pending"}
		}
	}
	for _, c := range d.Cancellations {
		k := key(method, c.SignalID)
		o, ok := s.orders[k]
		if !ok || o.status != "pending" || o.signal.Action != "new" {
			return fmt.Errorf("元取消の先行newが不明")
		}
		o.status = "cancelled"
		s.orders[k] = o
	}
	for _, f := range d.Fills {
		k := key(method, f.Fill.SignalID)
		o, ok := s.orders[k]
		if !ok || o.status != "pending" || f.Action != o.signal.Action || f.Fill.Quantity != o.signal.Quantity || f.Quote.Index <= o.signal.SourceIndex {
			return fmt.Errorf("元Fillの先行Signalが不明")
		}
		if f.Action == "new" {
			hk := key(method, f.Fill.HoldID)
			if s.holds[hk] != nil {
				return fmt.Errorf("元Hold重複")
			}
			s.holds[hk] = &sourceHold{quantity: f.Fill.Quantity, side: f.Side}
		} else {
			if !reflect.DeepEqual(f.Fill.Closed, o.signal.Targets) {
				return fmt.Errorf("元返済Targets不一致")
			}
			for _, t := range f.Fill.Closed {
				h := s.holds[key(method, t.ID)]
				if h == nil || h.quantity < t.Quantity || h.reserved < t.Quantity {
					return fmt.Errorf("元返済の所有/予約不足")
				}
				h.quantity -= t.Quantity
				h.reserved -= t.Quantity
			}
		}
		o.status = "filled"
		s.orders[k] = o
	}
	for _, r := range d.Signals {
		sig := r.Signal
		if sig.Action == "new" {
			continue
		}
		if sig.Action != "close" {
			return fmt.Errorf("元Signal種別不正")
		}
		k := key(method, sig.ID)
		if _, ok := s.orders[k]; ok {
			return fmt.Errorf("元close再配送")
		}
		total := 0
		seen := map[string]bool{}
		for _, t := range sig.Targets {
			h := s.holds[key(method, t.ID)]
			if h == nil || seen[t.ID] || t.Quantity <= 0 || h.side != -sig.Side {
				return fmt.Errorf("元返済対象不整合")
			}
			before := h.quantity - h.reserved
			if t.Quantity > before {
				return fmt.Errorf("元未通知量超過")
			}
			seen[t.ID] = true
			d.Closes = append(d.Closes, native.CloseNotice{ID: sig.ID + "|" + t.ID, ReferenceID: t.ID, Before: before, Quantity: t.Quantity, Reason: sig.Reason})
			h.reserved += t.Quantity
			total += t.Quantity
		}
		if total != sig.Quantity {
			return fmt.Errorf("元close総量不整合")
		}
		s.orders[k] = sourceOrder{sig, "pending"}
	}
	return nil
}

// Take は元のactive methods順で空batchも戻し、公開Close通知を結びます。
//
// 引数: at(float64)、origin(string)、q(native.QuoteStamp)、methods([]string)は元配送の時計/位相/当行/生成済順です。
// 返り値: []actual.NativeBatch/errorは元全手法の通知又は未結合。timerは新しい価格へretimeしません。
func (s *SourceIndex) Take(at float64, origin string, q native.QuoteStamp, methods []string) ([]actual.NativeBatch, error) {
	line := q.SourceLine
	if origin == "timer" {
		line = 0
	}
	k := eventKey{origin, at, line}
	saved := s.byEvent[k]
	delete(s.byEvent, k)
	if origin != "quote" && origin != "timer" {
		return nil, fmt.Errorf("元配送位相不正")
	}
	seen := map[string]bool{}
	out := []actual.NativeBatch{}
	for _, m := range methods {
		if seen[m] {
			return nil, fmt.Errorf("active methods重複")
		}
		seen[m] = true
		d, ok := saved[m]
		if !ok {
			d = empty(at, origin, line)
		}
		if origin == "timer" {
			d.SourceLine = s.last[m].SourceLine
		} else {
			d.SourceLine = q.SourceLine
			s.last[m] = q
			s.rows[m]++
		}
		if err := s.apply(m, &d); err != nil {
			return nil, err
		}
		out = append(out, actual.NativeBatch{Method: m, Delta: d})
	}
	for m := range saved {
		if !seen[m] {
			return nil, fmt.Errorf("生成済み手法へ結合しない通知")
		}
	}
	return out, nil
}

// Finish は未配送の公開通知を成功へ隠しません。
//
// 引数: ありません。
// 返り値: errorは元通知の欠落です。Source判断や元戦略の完了を証明しません。
func (s *SourceIndex) Finish() error {
	if len(s.byEvent) > 0 {
		return fmt.Errorf("未配送のSource通知")
	}
	return nil
}
