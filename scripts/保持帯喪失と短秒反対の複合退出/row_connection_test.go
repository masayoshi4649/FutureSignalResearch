package far86

import (
	"strings"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
)

// input86Row は金融接続人工の同原行出典と正規の短秒未知を作ります。
//
// 引数: q(Quote)は実原行です。
// 返り値: *CurrentEvidenceは実Indexと異なる源Indexを持ち、過去の現在特徴を再用しません。
func input86Row(q Quote) *CurrentEvidence {
	return &CurrentEvidence{CurrentEvidence: far81.CurrentEvidence{Reference: "NK225", Time: q.Time, Received: q.Time,
		SourceIndex: q.Index + 7, SourceLine: q.Line, Last: q.Last, Bid: q.Bid, Ask: q.Ask},
		Short: CurrentShort{Time: q.Time, Mid: q.Bid + (q.Ask-q.Bid)/2,
			Five: CurrentShortWindow{Reason: "人工の過去端不足"}, Fifteen: CurrentShortWindow{Reason: "人工の過去端不足"}}}
}

// TestRuntimeForwardsCurrentPhysicalRow は入口の保存現在値と退出の当原行を分離します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。売買・両遅延の未知証拠が実Indexと異なる当行源Indexを保持します。
func TestRuntimeForwardsCurrentPhysicalRow(t *testing.T) {
	for _, side := range []int{1, -1} {
		runtime, at := input86Runtime(t, side)
		if err := runtime.advanceTimer(at, false); err != nil {
			t.Fatal(err)
		}
		before := runtime.last
		for _, after := range []float64{.5, 1} {
			q := before
			q.Time, q.Index, q.Line = at+after, runtime.last.Index+1, runtime.last.Line+1
			q.Last, q.Bid, q.Ask = before.Last-float64(side)*20, before.Bid-float64(side)*20, before.Ask-float64(side)*20
			row := input86Row(q)
			if err := runtime.observeQuote(q, row); err != nil {
				t.Fatal(err)
			}
		}
		for delay := 0; delay <= 1; delay++ {
			book := runtime.books[bookKey("J1G1", delay)].Result()
			if len(book.Lots) != 1 || book.Lots[0].ConfirmFirstUnknown == nil {
				t.Fatal("当行の価格否定・短秒未知を保存しません", side, delay)
			}
			e := book.Lots[0].ConfirmFirstUnknown
			if e.FeatureIndex != e.QuoteIndex+7 || e.SourceLine != 21+int64(delay) || e.SourceTime != at+.5+float64(delay)*.5 || !e.PriceBreached || e.ShortKnown || e.Confirmed {
				t.Fatal("実Index・源Index・物理行又は未知を取り違えました", side, delay, e)
			}
		}
	}
}

// TestRuntimeNilDoesNotReuseEntryCurrent は不良Lastのnilと正常残玉の接続欠落を区別します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。旧入口用r.currentでnilを補完せず、正常残玉なら接続errorになります。
func TestRuntimeNilDoesNotReuseEntryCurrent(t *testing.T) {
	runtime, at := input86Runtime(t, 1)
	if err := runtime.advanceTimer(at, false); err != nil {
		t.Fatal(err)
	}
	q := runtime.last
	q.Time, q.Index, q.Line = at+.5, q.Index+1, q.Line+1
	if err := runtime.observeQuote(q, input86Row(q)); err != nil {
		t.Fatal(err)
	}
	lastCurrent := runtime.current
	quotes := runtime.books[bookKey("J1G1", 0)].Result().Metrics.ConfirmCounts.NormalQuotes
	q.Time, q.Index, q.Line, q.Last, q.Valid = at+.6, q.Index+1, q.Line+1, 0, false
	if err := runtime.observeQuote(q, nil); err != nil {
		t.Fatal(err)
	}
	if runtime.current.SourceLine != lastCurrent.SourceLine || runtime.books[bookKey("J1G1", 0)].Result().Metrics.ConfirmCounts.NormalQuotes != quotes {
		t.Fatal("不良Lastの当行を源現在又は正常短秒へ読み替えました")
	}
	q.Time, q.Index, q.Line, q.Last, q.Valid = at+.7, q.Index+1, q.Line+1, lastCurrent.Last, true
	err := runtime.observeQuote(q, nil)
	if err == nil || !strings.Contains(err.Error(), "当原行特徴がありません") {
		t.Fatal("正常残玉のnilを古い入口特徴で補完しました", err)
	}
}

// input86SourceRow は既存の源短秒計算を当原行へ結び付けます。
//
// 引数: q(Quote)は実原行、source(*strategy.SelectedDay164Features)は当場だけの人工履歴です。
// 返り値: *CurrentEvidenceは源で計算した窓値を変更せず保存した当原行です。
func input86SourceRow(q Quote, source *strategy.SelectedDay164Features) *CurrentEvidence {
	source.OnBoard(strategy.Board{Reference: "NK225", Time: q.Time, Received: q.Time, Last: q.Last,
		Bid: q.Bid, Ask: q.Ask, BidQuantity: 100, AskQuantity: 100})
	s := source.Short(q.Time)
	c := input86Row(q)
	c.Short = CurrentShort{Time: s.Time, Mid: s.Mid,
		Five:    CurrentShortWindow{Known: s.Five.Known, Move: s.Five.Move, Speed: s.Five.Speed, Elapsed: s.Five.Elapsed, Endpoint: s.Five.Endpoint, Delay: s.Five.Delay, Reason: s.Five.Reason},
		Fifteen: CurrentShortWindow{Known: s.Fifteen.Known, Move: s.Fifteen.Move, Speed: s.Fifteen.Speed, Elapsed: s.Fifteen.Elapsed, Endpoint: s.Fifteen.Endpoint, Delay: s.Fifteen.Delay, Reason: s.Fifteen.Reason}}
	return c
}

// TestSourceShortEndpointBoundaries は端点許容と途中異常を源計算経由で確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。数量不良と価格窓不良を区別します。
func TestSourceShortEndpointBoundaries(t *testing.T) {
	for _, step := range []float64{15, 15.001} {
		source := &strategy.SelectedDay164Features{}
		for _, at := range []float64{0, step, step * 2} {
			q := Quote{Time: at, Index: int64(at), Line: int64(at) + 1, Last: 1000 + at, Bid: 990 + at, Ask: 1010 + at, Valid: true}
			input86SourceRow(q, source)
		}
		s := source.Short(step * 2)
		if s.Five.Known != (step == 15) || s.Fifteen.Known != (step == 15) {
			t.Fatal("15秒空白の包含境界が源と異なります", step, s)
		}
	}
	for _, badQuote := range []bool{false, true} {
		source := &strategy.SelectedDay164Features{}
		for at := 0.; at <= 30; at++ {
			b := strategy.Board{Reference: "NK225", Time: at, Received: at, Last: 1000 + at, Bid: 990 + at, Ask: 1010 + at}
			if badQuote && at == 28 {
				b.Bid, b.Ask = 0, 0
			}
			source.OnBoard(b)
		}
		s := source.Short(30)
		if s.Five.Known == badQuote || s.Fifteen.Known == badQuote {
			t.Fatal("数量欠測と途中異常のKnownを混同しました", badQuote, s)
		}
	}
}

// TestOldProjectionRejectsUndeclaredField は旧投影が未知のconfirm名を隠さないことを確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。宣言済みの追加名だけを除き、旧hold名と未宣言名は保存します。
func TestOldProjectionRejectsUndeclaredField(t *testing.T) {
	original := map[string]any{"confirm_enabled": false, "confirm_unannounced": 1, "hold_active": false, "net_pnl_yen": 1}
	projected := stripConfirmFields(original).(map[string]any)
	if len(projected) != 3 || projected["confirm_unannounced"] != 1 || projected["hold_active"] != false || projected["net_pnl_yen"] != 1 {
		t.Fatal("旧投影が未宣言追加又は旧会計値を隠しました", projected)
	}
}
