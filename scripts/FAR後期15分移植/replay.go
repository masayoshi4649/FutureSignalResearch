package far80

import (
	"bufio"
	"compress/gzip"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// InputFile は実行前に固定した一つの入力の指紋です。
type InputFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

// InputSession は同場の二市場板と確定足をまとめます。
type InputSession struct {
	ID       string               `json:"id"`
	Contract string               `json:"contract"`
	Files    map[string]InputFile `json:"files"`
}

// InputManifest は複製しない原データへの固定参照です。
type InputManifest struct {
	Root           string            `json:"source_root"`
	Sessions       []InputSession    `json:"sessions"`
	StrategyRoot   string            `json:"純戦略repo"`
	StrategySHA256 map[string]string `json:"純戦略SHA256"`
}

// RawQuality は価格時計への配置可否と約定気配の品質を分けた件数です。
type RawQuality struct {
	Lines        int64    `json:"lines"`
	ClockMissing int64    `json:"clock_missing"`
	Outside      int64    `json:"outside"`
	Backward     int64    `json:"backward"`
	BadLast      int64    `json:"bad_last"`
	BadQuote     int64    `json:"bad_quote"`
	Accepted     int64    `json:"accepted"`
	Contracts    []string `json:"contracts"`
}

// ReplayResult は一場の入力品質・参照観測・三案の実所有を保存します。
type ReplayResult struct {
	Session         string                `json:"session"`
	Quality         map[string]RawQuality `json:"quality"`
	ReferenceCounts map[string]int        `json:"reference_counts"`
	Books           map[string]BookResult `json:"books"`
}

type replayBoard struct {
	Board strategy.Board
	Line  int64
}
type candleEvent struct {
	Reference string
	Interval  int
	Candle    strategy.Candle
	At        float64
}

// verifyInput は圧縮された実ファイルを固定SHAと照合します。
//
// 引数: rootはstringの入力根、fはInputFileの固定情報です。
// 返り値: stringは絶対パス、errorはファイル変更又は入出力異常です。
func verifyInput(root string, f InputFile) (string, error) {
	p := filepath.Join(root, filepath.FromSlash(f.Path))
	in, e := os.Open(p)
	if e != nil {
		return "", e
	}
	defer in.Close()
	h := sha256.New()
	n, e := io.Copy(h, in)
	if e != nil {
		return "", e
	}
	if n != f.Size || hex.EncodeToString(h.Sum(nil)) != f.SHA256 {
		return "", fmt.Errorf("入力指紋が変わりました: %s", p)
	}
	return p, nil
}

// ValidateManifest は場の重複・逆順と参照純戦略の変更を拒否します。
//
// 引数: mはInputManifestの固定入力です。
// 返り値: errorは重複・逆順・指紋変更、正常ならnilです。
func ValidateManifest(m InputManifest) error {
	if len(m.Sessions) == 0 || m.Root == "" || len(m.StrategySHA256) == 0 {
		return fmt.Errorf("固定台帳の必須入力が空です")
	}
	previous := 0.0
	seen := map[string]bool{}
	for _, s := range m.Sessions {
		clock, e := sessionClock(s.ID)
		if e != nil {
			return e
		}
		if seen[s.ID] || clock.Start <= previous {
			return fmt.Errorf("場IDが重複又は時系列逆順です:%s", s.ID)
		}
		seen[s.ID] = true
		previous = clock.Start
		if s.Contract == "" || len(s.Files) != 6 {
			return fmt.Errorf("場の限月又は6入力が不正:%s", s.ID)
		}
		for _, key := range []string{"NK225_book", "TOPIX_book", "NK225_candle_60", "NK225_candle_300", "TOPIX_candle_60", "TOPIX_candle_300"} {
			f, ok := s.Files[key]
			if !ok || f.Path == "" || f.Size <= 0 || len(f.SHA256) != 64 {
				return fmt.Errorf("必須入力が不正:%s %s", s.ID, key)
			}
		}
	}
	for name, expected := range m.StrategySHA256 {
		p := filepath.Join(m.StrategyRoot, filepath.FromSlash(name))
		file, e := os.Open(p)
		if e != nil {
			return e
		}
		h := sha256.New()
		_, e = io.Copy(h, file)
		file.Close()
		if e != nil {
			return e
		}
		if hex.EncodeToString(h.Sum(nil)) != expected {
			return fmt.Errorf("純戦略指紋が変わりました:%s", name)
		}
	}
	return nil
}

// sessionClock は場IDから売買可能な原セッション時計を作ります。
//
// 引数: idはstringの場IDです。
// 返り値: strategy.Sessionは場末10分前返済付きの時計、errorは場ID不正です。
func sessionClock(id string) (strategy.Session, error) {
	parts := strings.Split(id, "_")
	if len(parts) != 2 {
		return strategy.Session{}, fmt.Errorf("場ID不正:%s", id)
	}
	zone, e := time.LoadLocation("Asia/Tokyo")
	if e != nil {
		return strategy.Session{}, e
	}
	day, e := time.ParseInLocation("2006-01-02", parts[0], zone)
	if e != nil {
		return strategy.Session{}, e
	}
	start, end := day.Add(8*time.Hour+45*time.Minute), day.Add(15*time.Hour+45*time.Minute)
	if parts[1] == "Night" {
		start = day.Add(17 * time.Hour)
		end = day.AddDate(0, 0, 1).Add(6 * time.Hour)
	} else if parts[1] != "Day" {
		return strategy.Session{}, fmt.Errorf("場種不正")
	}
	us, e := USOpen(parts[0])
	if e != nil {
		return strategy.Session{}, e
	}
	extraAt := float64(start.Add(225 * time.Minute).Unix())
	if parts[1] == "Night" {
		extraAt = us + 1800
	} else {
		us = 0
	}
	return strategy.Session{ID: id, Kind: parts[1], Start: float64(start.Unix()), End: float64(end.Unix()), ForceClose: float64(end.Add(-10 * time.Minute).Unix()), USOpen: us, ExtraAt: extraAt, NightCoreStart: 0}, nil
}

// readBoards は時計を持つ全原行を読み、同値行を省略せず品質を数えます。
//
// 引数: path/refはstringのgzip原板と市場、sessionはstrategy.Sessionです。
// 返り値: []replayBoardは原行順の採用板、RawQualityは除外内訳、errorは壊れたJSON等です。
func readBoards(path, ref string, session strategy.Session) ([]replayBoard, RawQuality, error) {
	file, e := os.Open(path)
	if e != nil {
		return nil, RawQuality{}, e
	}
	defer file.Close()
	z, e := gzip.NewReader(file)
	if e != nil {
		return nil, RawQuality{}, e
	}
	defer z.Close()
	scan := bufio.NewScanner(z)
	scan.Buffer(make([]byte, 65536), 4*1024*1024)
	out := []replayBoard{}
	q := RawQuality{}
	previous := session.Start
	codes := map[string]bool{}
	for scan.Scan() {
		q.Lines++
		raw := map[string]json.RawMessage{}
		if e = json.Unmarshal(scan.Bytes(), &raw); e != nil {
			return nil, q, fmt.Errorf("%s:%d: %w", path, q.Lines, e)
		}
		var clock, code string
		var last float64
		if e = json.Unmarshal(raw["Symbol"], &code); e != nil {
			return nil, q, e
		}
		codes[code] = true
		if len(raw["CurrentPriceTime"]) == 0 {
			q.ClockMissing++
			continue
		}
		if e = json.Unmarshal(raw["CurrentPriceTime"], &clock); e != nil {
			return nil, q, e
		}
		at, err := time.Parse(time.RFC3339Nano, clock)
		if err != nil {
			q.ClockMissing++
			continue
		}
		t := float64(at.UnixNano()) / 1e9
		if t < session.Start || t >= session.End {
			q.Outside++
			continue
		}
		if t < previous {
			q.Backward++
			continue
		}
		previous = t
		if len(raw["CurrentPrice"]) > 0 {
			if e = json.Unmarshal(raw["CurrentPrice"], &last); e != nil {
				return nil, q, e
			}
		}
		if last <= 0 {
			q.BadLast++
		}
		b := strategy.Board{Reference: ref, Time: t, Received: t, Last: last}
		for i := 0; i < 10; i++ {
			var buy, sell struct{ Price, Qty float64 }
			if e = json.Unmarshal(raw[fmt.Sprintf("Buy%d", i+1)], &buy); e != nil {
				return nil, q, e
			}
			if e = json.Unmarshal(raw[fmt.Sprintf("Sell%d", i+1)], &sell); e != nil {
				return nil, q, e
			}
			b.BidLevels[i] = strategy.ResearchLevel{Price: buy.Price, Quantity: buy.Qty}
			b.AskLevels[i] = strategy.ResearchLevel{Price: sell.Price, Quantity: sell.Qty}
		}
		b.Bid, b.Ask, b.BidQuantity, b.AskQuantity = b.BidLevels[0].Price, b.AskLevels[0].Price, b.BidLevels[0].Quantity, b.AskLevels[0].Quantity
		if b.Bid <= 0 || b.Ask <= b.Bid {
			q.BadQuote++
		}
		out = append(out, replayBoard{b, q.Lines})
		q.Accepted++
	}
	for c := range codes {
		q.Contracts = append(q.Contracts, c)
	}
	sort.Strings(q.Contracts)
	return out, q, scan.Err()
}

// readCandles はCSVの確定足を終端と既定公開遅延の後にだけ公開します。
//
// 引数: path/refはstring、intervalはintの秒、delayはfloat64、sessionは場時計です。
// 返り値: []candleEventは未確定を除いた公開予定、errorは値又は形式の不正です。
func readCandles(path, ref string, interval int, delay float64, session strategy.Session) ([]candleEvent, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, e
	}
	defer f.Close()
	r := csv.NewReader(f)
	head, e := r.Read()
	if e != nil {
		return nil, e
	}
	cols := map[string]int{}
	for i, k := range head {
		cols[strings.TrimPrefix(k, "\ufeff")] = i
	}
	for _, k := range []string{"time", "open", "high", "low", "close", "closed"} {
		if _, ok := cols[k]; !ok {
			return nil, fmt.Errorf("足の列不足:%s", k)
		}
	}
	out := []candleEvent{}
	for {
		row, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if row[cols["closed"]] != "true" {
			continue
		}
		t, err := time.Parse(time.RFC3339Nano, row[cols["time"]])
		if err != nil {
			return nil, err
		}
		c := strategy.Candle{Time: float64(t.UnixNano()) / 1e9, Closed: true}
		vals := []*float64{&c.Open, &c.High, &c.Low, &c.Close}
		for i, k := range []string{"open", "high", "low", "close"} {
			*vals[i], err = strconv.ParseFloat(row[cols[k]], 64)
			if err != nil {
				return nil, err
			}
		}
		if c.Time < session.Start || c.Time >= session.End {
			continue
		}
		out = append(out, candleEvent{ref, interval, c, c.Time + float64(interval) + delay})
	}
	return out, nil
}

// Replay は実注文機構を一切呼ばず、一場を原行・公開時計順に再生します。
//
// 引数: rootはstringの入力根、inputはInputSession、bankは同限月TechnicalBank、delayは約定遅延秒です。
// 返り値: ReplayResultは実会計三案と品質、errorは入力又は状態不整合です。
func Replay(root string, input InputSession, bank *TechnicalBank, delay float64) (ReplayResult, error) {
	result := ReplayResult{Session: input.ID, Quality: map[string]RawQuality{}, ReferenceCounts: map[string]int{}, Books: map[string]BookResult{}}
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
		up, err := strategy.ParametersForMethod("NK225", "Night", "U165_03")
		if err != nil {
			return result, err
		}
		if !reflect.DeepEqual(params.Features, up.Features) {
			return result, fmt.Errorf("二夜手法の特徴条件が異なります")
		}
	}
	features, e := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if e != nil {
		return result, e
	}
	features.EnableResearch()
	boards := []replayBoard{}
	candles := []candleEvent{}
	for _, ref := range []string{"TOPIX", "NK225"} {
		p, err := verifyInput(root, input.Files[ref+"_book"])
		if err != nil {
			return result, err
		}
		rows, quality, err := readBoards(p, ref, session)
		if err != nil {
			return result, err
		}
		result.Quality[ref] = quality
		boards = append(boards, rows...)
		if len(quality.Contracts) != 1 {
			return result, fmt.Errorf("限月混在又は不明:%s %v", ref, quality.Contracts)
		}
		if ref == "NK225" && quality.Contracts[0] != input.Contract {
			return result, fmt.Errorf("NK限月不一致")
		}
		for _, iv := range []int{60, 300} {
			key := fmt.Sprintf("%s_candle_%d", ref, iv)
			p, err = verifyInput(root, input.Files[key])
			if err != nil {
				return result, err
			}
			rows, err := readCandles(p, ref, iv, params.Features.CandleDelay, session)
			if err != nil {
				return result, err
			}
			candles = append(candles, rows...)
		}
	}
	sort.SliceStable(boards, func(i, j int) bool { return boards[i].Board.Time < boards[j].Board.Time })
	sort.SliceStable(candles, func(i, j int) bool { return candles[i].At < candles[j].At })
	refs := map[string]*Reference{}
	ref, err := NewReference(method, session, 100)
	if err != nil {
		return result, err
	}
	refs[method] = ref
	books := map[string]*Book{}
	for _, mode := range []string{"F0", "P1", "T1"} {
		b, err := NewBook(input.ID, mode, 100)
		if err != nil {
			return result, err
		}
		if err = b.SetFillDelay(delay); err != nil {
			return result, err
		}
		books[mode] = b
	}
	bank.BeginSession(session.Start)
	grids, e := ScheduledTimes(input.ID)
	if e != nil {
		return result, e
	}
	timers := append([]float64{}, grids...)
	timers = append(timers, session.ForceClose)
	if session.Kind == "Night" {
		timers = append(timers, session.USOpen-900, session.USOpen+900)
	}
	sort.Float64s(timers)
	unique := timers[:0]
	for _, at := range timers {
		if len(unique) == 0 || unique[len(unique)-1] != at {
			unique = append(unique, at)
		}
	}
	timers = unique
	gridSet := map[float64]bool{}
	for _, at := range grids {
		gridSet[at] = true
	}
	timerIndex, candleIndex := 0, 0
	last := Quote{Index: -1}
	forceDone := false
	actualIndex := int64(-1)
	// ----------------------------------------
	// 元参照の返済通知は当原行に限り、定時では現在有効玉だけを参照します。
	for _, row := range boards {
		for timerIndex < len(timers) && timers[timerIndex] <= row.Board.Time {
			at := timers[timerIndex]
			timerIndex++
			if err = bank.Advance(at); err != nil {
				return result, err
			}
			if at == session.ForceClose || (session.Kind == "Night" && at == session.USOpen-900) {
				reason := "場末10分前"
				if at != session.ForceClose {
					reason = "米国前枠終了"
				}
				for _, b := range books {
					if err = b.Force(at, last, reason); err != nil {
						return result, err
					}
				}
				for _, r := range refs {
					if err = r.Force(at, reason); err != nil {
						return result, err
					}
				}
				if at == session.ForceClose {
					forceDone = true
				}
			}
			if session.Kind == "Night" && at == session.USOpen+900 {
				u, err := NewReference("U165_03", session, 100)
				if err != nil {
					return result, err
				}
				refs["U165_03"] = u
			}
			if gridSet[at] {
				active, err := WindowMethod(at, session.USOpen, session.Kind)
				if err != nil {
					return result, err
				}
				frame := ReferenceFrame{}
				if !forceDone && refs[active] != nil {
					frame = refs[active].Frame()
					frame.Closes = nil
				}
				for _, b := range books {
					if err = b.OnGrid(at, last, frame, bank.View()); err != nil {
						return result, err
					}
				}
			}
		}
		for candleIndex < len(candles) && candles[candleIndex].At <= row.Board.Time {
			c := candles[candleIndex]
			candleIndex++
			if _, err = features.AddCandles(c.Reference, c.Interval, []strategy.Candle{c.Candle}, c.At); err != nil {
				return result, err
			}
		}
		if row.Board.Last <= 0 {
			if row.Board.Reference == "NK225" {
				actualIndex++
				q := Quote{Time: row.Board.Time, Index: actualIndex, Line: row.Line, Last: row.Board.Last, Bid: row.Board.Bid, Ask: row.Board.Ask, Valid: false}
				if err = bank.Observe(q); err != nil {
					return result, err
				}
				frame := ReferenceFrame{}
				for _, r := range refs {
					frame.Lots = append(frame.Lots, r.Frame().Lots...)
				}
				for _, b := range books {
					if err = b.OnQuote(q, frame, bank.View()); err != nil {
						return result, err
					}
				}
				last = q
			}
			continue
		}
		o, err := features.OnBoard(row.Board)
		if err != nil {
			return result, err
		}
		if o.Reference != "NK225" {
			continue
		}
		actualIndex++
		q := Quote{Time: o.Time, Index: actualIndex, Line: row.Line, Last: o.Last, Bid: o.Bid, Ask: o.Ask, Valid: o.QuoteOK && o.Last > 0}
		chart := q
		chart.Valid = q.Last > 0
		if err = bank.Observe(chart); err != nil {
			return result, err
		}
		frame := ReferenceFrame{}
		for _, name := range []string{"D164_15", "P164_06", "U165_03"} {
			if r := refs[name]; r != nil {
				part, err := r.Step(o)
				if err != nil {
					return result, err
				}
				frame.Lots = append(frame.Lots, part.Lots...)
				frame.Closes = append(frame.Closes, part.Closes...)
				result.ReferenceCounts[name]++
			}
		}
		for _, b := range books {
			if err = b.OnQuote(q, frame, bank.View()); err != nil {
				return result, err
			}
		}
		last = q
	}
	// ----------------------------------------
	// 最終原行以後の定時も記録しますが、架空の気配で約定させません。
	for timerIndex < len(timers) {
		at := timers[timerIndex]
		timerIndex++
		if err = bank.Advance(at); err != nil {
			return result, err
		}
		if at == session.ForceClose || (session.Kind == "Night" && at == session.USOpen-900) {
			for _, b := range books {
				if err = b.Force(at, last, "データ末以後の強制返済要求"); err != nil {
					return result, err
				}
			}
		}
		if gridSet[at] {
			for _, b := range books {
				if err = b.OnGrid(at, last, ReferenceFrame{}, bank.View()); err != nil {
					return result, err
				}
			}
		}
	}
	for mode, b := range books {
		result.Books[mode] = b.Result()
	}
	return result, nil
}
