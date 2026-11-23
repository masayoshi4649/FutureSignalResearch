// 固定80から入力部分のみを機械派生。金融本文の複写は0。
// 派生元 replay.go SHA256: 8ade985b170c65183ffe62526d9bc92e6d125ca0e5dcffbf8c913682e813cee6
// 派生元 schedule.go SHA256: fd3b1a977a90de40d9a2f8039f729afb8834d9740a80636113b754589b00c040
package mininative

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
	"sort"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata"

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

// USOpen は同日ニューヨーク09:30を自動DSTでUnix時計へ写します。
//
// 引数: day(string)はナイトの開始日YYYY-MM-DDです。
// 返り値: float64は米国開始Unix秒、errorは不正日付又は時計設定です。
func USOpen(day string) (float64, error) {
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		return 0, fmt.Errorf("米国時計の読込: %w", err)
	}
	date, err := time.ParseInLocation("2006-01-02", day, zone)
	if err != nil || date.Format("2006-01-02") != day {
		return 0, fmt.Errorf("米国開始の日付が不正です: %s", day)
	}
	at := time.Date(date.Year(), date.Month(), date.Day(), 9, 30, 0, 0, zone)
	return float64(at.Unix()), nil
}
