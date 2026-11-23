package far87

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

type rawArtificialQuote struct {
	Quote           Quote `json:"quote"`
	ClockMissing    bool  `json:"clock_missing"`
	Accepted        bool  `json:"accepted"`
	FeatureExpected int64 `json:"feature_expected"`
}
type artificialObservation struct {
	Quote     Quote            `json:"quote"`
	Current   *CurrentEvidence `json:"current"`
	Technical TechnicalView    `json:"technical"`
}

// writeArtificialJSON は明示した新規人工ファイルだけを保存します。
//
// 引数: t(*testing.T)、path(string)、value(any)は検査器・保存先・人工値です。
// 返り値: ありません。既存ファイルを上書きしません。
func writeArtificialJSON(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(data); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
}

// rawPrefix87 は全物理20行とbefore8/Source7を持つ金融接続前史を保存します。
//
// 引数: t(*testing.T)、r(*replayRuntime)は手製Source seedを持つRuntimeです。
// 返り値: []rawArtificialQuoteは8正常源行・Last0一行・11欠測時計行です。FAR自然発生前史とはしません。
func rawPrefix87(t *testing.T, r *replayRuntime) []rawArtificialQuote {
	t.Helper()
	before := r.last
	raw := []rawArtificialQuote{}
	for line := int64(1); line <= 11; line++ {
		raw = append(raw, rawArtificialQuote{Quote: Quote{Index: -1, Line: line}, ClockMissing: true, FeatureExpected: -1})
	}
	index, source := int64(-1), int64(-1)
	for i := 0; i < 8; i++ {
		q := before
		index++
		source++
		q.Time, q.Index, q.Line = before.Time-35+float64(i)*5, index, int64(len(raw)+1)
		raw = append(raw, rawArtificialQuote{Quote: q, Accepted: true, FeatureExpected: source})
		if i == 4 {
			bad := q
			index++
			bad.Time, bad.Index, bad.Line, bad.Last, bad.Valid = q.Time+2.5, index, int64(len(raw)+1), 0, false
			raw = append(raw, rawArtificialQuote{Quote: bad, Accepted: true, FeatureExpected: -1})
		}
	}
	before.Index = index
	r.last = Quote{Index: -1}
	r.books = map[string]*Book{}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			b, err := NewSourceBook(r.session.ID, sourcePolicy(mode), 100)
			if err != nil {
				t.Fatal(err)
			}
			if err = b.SetFillDelay(float64(delay)); err != nil {
				t.Fatal(err)
			}
			r.books[bookKey(mode, delay)] = b
		}
	}
	current := r.current
	if err := r.observeQuote(before, &current, nil); err != nil {
		t.Fatal(err)
	}
	return raw
}

// scriptClose87 は指定源原行へ手製返済を予約し、二参照を同条件で進めます。
//
// 引数: r(*replayRuntime)、at(float64)、side/quantity(int)、id(string)は通知の出典です。
// 返り値: ありません。実G1の状態や損益をSourceへ入力しません。
func scriptClose87(r *replayRuntime, at float64, side, quantity int, id string) {
	index := r.current.SourceIndex + 1
	s := referenceTestSignal(id, "close", quantity, index, "参照追加")
	s.Time, s.Side = at, -side
	r.refs["D164_15"].(*fixtureReference).fake.scripts[index] = []strategy.Signal{s}
	r.legacyRefs["D164_15"].(*fixtureReference).fake.scripts[index] = []strategy.Signal{s}
}

// TestExportArtificialSnapshots は全原行付き非0Source金融接続を買売7状態で保存します。
//
// 引数: t(*testing.T)、環境変数FAR87_ARTIFICIAL_OUT(string)は検査器と新規絶対保存先です。
// 返り値: ありません。Source生存前史と通知は手製で、FAR自然発生の原板証明ではありません。
func TestExportArtificialSnapshots(t *testing.T) {
	out := os.Getenv("FAR87_ARTIFICIAL_OUT")
	if out == "" {
		t.Skip("人工保存根が明示されていません")
	}
	if !filepath.IsAbs(out) {
		t.Fatal("人工保存は絶対パスが必要です")
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatal("人工保存根は新規である必要があります")
	}
	if err := os.MkdirAll(out, 0700); err != nil {
		t.Fatal(err)
	}
	for _, side := range []int{1, -1} {
		for _, scene := range []string{"源全返済", "新規待機中の源全返済", "timer優先", "非正常板の源部分返済", "正益と源部分予約", "正益予約後の収穫非適格", "C0不成立のS"} {
			r, at := input87Runtime(t, side)
			raw := rawPrefix87(t, r)
			if scene == "C0不成立のS" {
				r.current.Night.Known = false
			}
			initial, _ := r.refs["D164_15"].ReadMetadata()
			if err := r.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			before, q := r.last, r.last
			beforeCurrent := r.current
			observations := []artificialObservation{{Quote: before, Current: &beforeCurrent, Technical: r.bank.View().Technical}}
			observe := func(q Quote) {
				observe87(t, r, q)
				c := r.current
				observations = append(observations, artificialObservation{Quote: q, Current: &c, Technical: r.bank.View().Technical})
				raw = append(raw, rawArtificialQuote{Quote: q, Accepted: true, FeatureExpected: c.SourceIndex})
			}
			for _, after := range []float64{.5, 1, 2, 3, 4, 5, 6} {
				q.Time, q.Index, q.Line = at+after, q.Index+1, q.Line+1
				q.Last, q.Bid, q.Ask, q.Valid = before.Last, before.Bid, before.Ask, true
				partial := scene == "非正常板の源部分返済" || scene == "正益と源部分予約" || scene == "正益予約後の収穫非適格"
				if scene == "正益と源部分予約" && (after == 2 || after == 3) {
					q.Last, q.Bid, q.Ask = before.Last+float64(side)*40, before.Bid+float64(side)*40, before.Ask+float64(side)*40
				}
				if scene == "正益予約後の収穫非適格" {
					move := 0.0
					if after == 2 {
						move = 40
					}
					if after == 3 {
						move = 20
					}
					q.Last, q.Bid, q.Ask = before.Last+float64(side)*move, before.Bid+float64(side)*move, before.Ask+float64(side)*move
				}
				if scene == "非正常板の源部分返済" && after == 2 {
					q.Ask = q.Bid - 10
					q.Valid = false
				}
				if partial && after == 2 {
					scriptClose87(r, q.Time, side, 5, "源部分")
				}
				if partial && after == 4 {
					scriptClose87(r, q.Time, side, 12, "源全残")
				}
				if scene == "新規待機中の源全返済" && after == .5 {
					scriptClose87(r, q.Time, side, 17, "源全残")
				}
				if (scene == "源全返済" || scene == "C0不成立のS") && after == 2 {
					scriptClose87(r, q.Time, side, 17, "源全残")
				}
				observe(q)
				if (scene == "正益と源部分予約" || scene == "正益予約後の収穫非適格") && after == 2 {
					for _, b := range r.books {
						v := b.Result()
						if len(v.Lots) != 1 || !v.Lots[0].Flag || v.Lots[0].Floor < 0 || v.Lots[0].ReservedExit != 5 || v.Lots[0].HarvestOrderID != "" {
							t.Fatal("Source先行の正益同原行規範が不一致", side, v)
						}
					}
				}
				if scene == "正益予約後の収穫非適格" && after == 3 {
					for _, b := range r.books {
						v := b.Result()
						p := v.Lots[0]
						gain := float64(side) * (actualMark(q, side) - p.EntryPrice)
						if !p.Flag || p.Floor < 0 || p.ReservedExit != 0 || p.HarvestOrderID != "" || gain != 10 {
							t.Fatal("現在unitが非正の収穫を発行しました", side, v)
						}
					}
				}
			}
			if scene == "timer優先" {
				if err := r.advanceTimer(r.session.ForceClose, false); err != nil {
					t.Fatal(err)
				}
				for _, after := range []float64{0, 1} {
					q.Time, q.Index, q.Line = r.session.ForceClose+after, q.Index+1, q.Line+1
					observe(q)
				}
			}
			for _, mode := range Modes {
				for delay := 0; delay <= 1; delay++ {
					key := bookKey(mode, delay)
					b := r.books[key].Result()
					r.result.Books[key] = b
					want := 17
					if scene == "C0不成立のS" && mode == "R1G1" || scene == "新規待機中の源全返済" && delay == 1 {
						want = 0
					}
					if b.Metrics.EntryQuantity != want || b.Metrics.ExitQuantity != want || b.Metrics.OpenQuantity != 0 || b.Unresolved {
						t.Fatal("人工Source実数量又は完結に差", scene, side, key, b.Metrics)
					}
					if scene != "正益と源部分予約" && scene != "正益予約後の収穫非適格" && b.Metrics.NetPnLYen != float64(-222*want) {
						t.Fatal("変数量手計算17枚−3774円と不一致", scene, side, key, b.Metrics.NetPnLYen)
					}
					if scene == "正益予約後の収穫非適格" && b.Metrics.NetPnLYen != -2774 {
						t.Fatal("5枚10pt＋12枚−10ptの手計算純額−2774円と不一致", side, key, b.Metrics.NetPnLYen)
					}
				}
			}
			dir := filepath.Join(out, fmt.Sprintf("%s_%+d", scene, side))
			if err := os.Mkdir(dir, 0700); err != nil {
				t.Fatal(err)
			}
			writeArtificialJSON(t, filepath.Join(dir, "87.json"), r.result)
			writeArtificialJSON(t, filepath.Join(dir, "raw_quotes.json"), raw)
			writeArtificialJSON(t, filepath.Join(dir, "人工観測.json"), observations)
			writeArtificialJSON(t, filepath.Join(dir, "人工Source初期状態.json"), map[string]any{"snapshot": initial, "限定": "生存17・初期32・親初回50とSource通知は架空driverへのseed。FAR自然発生の再構成ではない。固定80実driverの全pool保持は別Replay人工。", "ForceClose": r.session.ForceClose, "session_start": r.session.Start, "session_end": r.session.End})
		}
	}
	writeArtificialJSON(t, filepath.Join(out, "説明.json"), map[string]any{"種類": "Source返済とG1の非0金融接続人工", "場面": 14, "会計": 56, "元段階": "選定参照source_add", "実段階": "初参加要求と実初参加を区別", "市場原板読取": 0, "市場新損益再生": 0, "限定": "全物理行を保存するがSource生存前史は手製。FAR自然発生の原板証明又は旧80別実装の証明ではない。正益同原行はSource部分5先行でG1収穫延期・建値床同原行を確認。部分fill後gain10ptでは現在unit−22なので収穫なし・建値床維持も確認。"})
}
