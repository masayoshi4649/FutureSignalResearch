// 89派生元: scripts/FAR背景維持と押戻し再開/input.go
// 89派生元SHA256: 01f4bba16d224a7c44f1e6f123dacfd9a2ab115f34c09bf1651201a6622a24d9

// 88派生元: scripts/FAR参照玉と可変数量の比較/input.go
// 88派生元SHA256: 2310c274bb5a4cb0450132b469e4f045889c52609fef533d9ba6cce8683d534f

// 87派生元: scripts/保持帯喪失と短秒反対の複合退出/input.go
// 87派生元SHA256: acbebe253e9b8b33e26c086908d9a059649dc9939099150c4ea19c280fece737

// 86派生元: scripts/保持帯の返済側固定否定/input.go
// 86派生元SHA256: f9598c0b114e0ce2934a8377fc890a311ddae8d778a05e83cdee9b36e9b32160

// 85派生元: scripts/現在の価格応答と数量確認/input.go
// 85派生元SHA256: 5a783582d535a5a0138e9d3d53ab4cdda0ab8baad39898c33353f9897d1052d7

// 84派生元: scripts/構造否定と利益配分/input.go
// 84派生元SHA256: 1f5b645ae8580851dd27d5aba869c69247735bbd42831b7f9f02c63f6278fc26

package far89

// 83派生元: scripts/チャートの現在性と補助確認/input.go
// 83派生元SHA256: 8bfc7e6f601abe671db6fb04dd77b40c0721659f707e9db651f179d92cb672a1

// 派生元: scripts/定時の現在根拠と部分利益保護/input.go
// 派生元SHA256: 6b73b297868218474a262f4a12aa290fad448f342de198afc7a9a69c46dd15d0
// 元ファイルは固定のまま編集しません。

// 入力読取と内部時計は固定80の非公開helperから派生したものです。
// 由来: scripts/FAR後期15分移植/replay.go
// 由来SHA256: 8ade985b170c65183ffe62526d9bc92e6d125ca0e5dcffbf8c913682e813cee6
// 88は87と同じ源Portfolioと元Featuresを旧呼出順で進めます。

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

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

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
	us, e := far80.USOpen(parts[0])
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
