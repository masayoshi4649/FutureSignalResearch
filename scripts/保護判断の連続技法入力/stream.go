package continuous101

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"runtime"
	"time"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
	oldtape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
)

type Budget struct {
	MaxHeapBytes uint64 `json:"max_go_heap_bytes"`
	MaxNKRows    int    `json:"max_positive_nk_rows"`
}
type StreamStats struct {
	Records        int     `json:"records"`
	Rows           int     `json:"rows"`
	Elapsed        float64 `json:"elapsed_seconds"`
	SampledHeapMax uint64  `json:"sampled_go_heap_max_bytes"`
	SampledSysMax  uint64  `json:"sampled_go_sys_max_bytes"`
	SampleInterval int     `json:"sample_interval_records"`
}

// sampleHeap はGoヒープ標本と資源上限を検査します。
//
// 引数: stats(*StreamStats)、budget(Budget)は標本最大と計算資源の上限です。
// 返り値: errorは上限超過です。OSの真のRSS最大を保証しません。
func sampleHeap(stats *StreamStats, budget Budget) error {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	if m.HeapAlloc > stats.SampledHeapMax {
		stats.SampledHeapMax = m.HeapAlloc
	}
	if m.Sys > stats.SampledSysMax {
		stats.SampledSysMax = m.Sys
	}
	if budget.MaxHeapBytes > 0 && m.HeapAlloc > budget.MaxHeapBytes {
		return fmt.Errorf("Go heap資源上限を超過")
	}
	return nil
}

// WriteStream は旧Scalarを逐次照合してCurrent/状態をJSONLへ渡します。
//
// 引数: req(Request)、seed(*warm.Seed)、old(oldtape.Tape)、w(io.Writer)、budget(Budget)は当場/種/旧入力/出力/資源上限です。
// 返り値: Sidecar/*warm.Seed/LegacyMatch/StreamStats/errorは小型header/次種/同値/標本/不正です。
func WriteStream(req Request, seed *warm.Seed, old oldtape.Tape, w io.Writer, budget Budget) (Sidecar, *warm.Seed, LegacyMatch, StreamStats, error) {
	start := time.Now()
	stats := StreamStats{SampleInterval: 1024}
	empty := Sidecar{}
	match := LegacyMatch{Bindings: []Binding{}}
	if old.Session != req.Session || old.Version != 1 {
		return empty, nil, match, stats, fmt.Errorf("旧Tape場/版不一致")
	}
	quotes, grids := []int{}, []int{}
	prior := 0.0
	for i, ev := range old.Events {
		if ev.Ordinal != i+1 || ev.At < prior {
			return empty, nil, match, stats, fmt.Errorf("旧Tape呼出順不正")
		}
		prior = ev.At
		switch ev.Kind {
		case "quote":
			if ev.Quote == nil || ev.At != ev.Quote.Time {
				return empty, nil, match, stats, fmt.Errorf("旧Quote不正")
			}
			quotes = append(quotes, i)
		case "grid":
			if ev.Context == nil || ev.Context.At != ev.At || ev.Quote != nil || len(ev.Methods)+len(ev.NonEmpty) != 0 {
				return empty, nil, match, stats, fmt.Errorf("旧Grid不正")
			}
			grids = append(grids, i)
		case "force":
		default:
			return empty, nil, match, stats, fmt.Errorf("旧種別不正")
		}
	}
	positive := 0
	for _, r := range req.Rows {
		if r.Board.Reference == "NK225" && r.Board.Last > 0 {
			positive++
		}
	}
	if budget.MaxNKRows > 0 && positive > budget.MaxNKRows {
		return empty, nil, match, stats, fmt.Errorf("場単位positiveNK行資源上限を超過")
	}
	if e := sampleHeap(&stats, budget); e != nil {
		return empty, nil, match, stats, e
	}
	enc := json.NewEncoder(w)
	ri, gi := 0, 0
	sink := func(rec Record) error {
		if rec.Kind == "row" {
			if rec.Row == nil || ri >= len(quotes) {
				return fmt.Errorf("逐次Scalar11集合不一致: 新行%d", ri+1)
			}
			if !reflect.DeepEqual(*old.Events[quotes[ri]].Quote, rec.Row.Scalar) {
				return fmt.Errorf("逐次Scalar11不一致: 旧ordinal%d 物理行%d 時計%.9f 旧%+v 新%+v", old.Events[quotes[ri]].Ordinal, rec.Row.Scalar.SourceLine, rec.Row.Scalar.Time, *old.Events[quotes[ri]].Quote, rec.Row.Scalar)
			}
			rec.TapeOrdinal = old.Events[quotes[ri]].Ordinal
			ri++
			stats.Rows++
		} else if rec.Control != nil && rec.Control.Kind == "grid" {
			if gi >= len(grids) || old.Events[grids[gi]].At != rec.Control.At {
				return fmt.Errorf("逐次Grid時計差")
			}
			rec.TapeOrdinal = old.Events[grids[gi]].Ordinal
			match.Bindings = append(match.Bindings, Binding{rec.TapeOrdinal, "grid", gi + 1})
			gi++
		}
		if e := enc.Encode(rec); e != nil {
			return e
		}
		stats.Records++
		if stats.Records%stats.SampleInterval == 0 {
			return sampleHeap(&stats, budget)
		}
		return nil
	}
	value, next, e := BuildToSink(req, seed, sink)
	if e != nil {
		return value, nil, match, stats, e
	}
	if ri != len(quotes) || gi != len(grids) || ri != value.RowCount || len(value.Grids) != len(grids) {
		return value, nil, match, stats, fmt.Errorf("逐次旧集合不足")
	}
	for i, pos := range grids {
		if !reflect.DeepEqual(*old.Events[pos].Context, value.Grids[i]) {
			return value, nil, match, stats, fmt.Errorf("旧5分Input全文差: 枠%d 時計%.9f", i+1, value.Grids[i].At)
		}
	}
	raw, e := json.Marshal(old)
	if e != nil {
		return value, nil, match, stats, e
	}
	match.LegacySHA = hashBytes(raw)
	match.Quotes, match.Grids, match.Events = ri, gi, len(old.Events)
	value.LegacySHA, value.Bindings = match.LegacySHA, match.Bindings
	stats.Elapsed = time.Since(start).Seconds()
	e = sampleHeap(&stats, budget)
	return value, next, match, stats, e
}

// hashBytes は保存旧入力のcanonical JSON指紋を得ます。
//
// 引数: raw([]byte)は明示値です。
// 返り値: stringはSHA256です。元gzipの指紋とは分けます。
func hashBytes(raw []byte) string { return fmt.Sprintf("%x", sha256.Sum256(raw)) }
