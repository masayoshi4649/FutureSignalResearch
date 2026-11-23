package far80

import (
	"compress/gzip"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// replayTestStamp は市場と無関係な人工Unix時計を保存形式へ写します。
//
// 引数: at(float64)は人工Unix秒です。
// 返り値: stringはRFC3339Nano時計です。
func replayTestStamp(at float64) string {
	return time.Unix(0, int64(math.Round(at*1e9))).UTC().Format(time.RFC3339Nano)
}

// replayTestRaw は原板の形だけを持つ人工JSON行を作ります。
//
// 引数: at/last(float64)は人工時計/Last、code(string)は限月IDです。
// 返り値: map[string]anyは毎回独立した行で、実市場データではありません。
func replayTestRaw(at, last float64, code string) map[string]any {
	row := map[string]any{"Symbol": code, "CurrentPriceTime": replayTestStamp(at), "CurrentPrice": last}
	for i := 1; i <= 10; i++ {
		row[fmt.Sprintf("Buy%d", i)] = map[string]float64{"Price": last - float64(i), "Qty": 10}
		row[fmt.Sprintf("Sell%d", i)] = map[string]float64{"Price": last + float64(i), "Qty": 10}
	}
	return row
}

// replayTestPin は人工ファイルの全byteを固定情報へまとめます。
//
// 引数: t(*testing.T)は検査、root/name(string)は人工一時領域と相対名です。
// 返り値: InputFileはサイズとSHA256を持つ人工指紋です。
func replayTestPin(t *testing.T, root, name string) InputFile {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(data)
	return InputFile{Path: filepath.ToSlash(name), SHA256: hex.EncodeToString(digest[:]), Size: int64(len(data))}
}

// replayTestGzip は人工行だけを新しい一時gzipへ保存します。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([]map[string]any)は人工行です。
// 返り値: InputFileは新しい人工gzipの指紋です。
func replayTestGzip(t *testing.T, root, name string, rows []map[string]any) InputFile {
	t.Helper()
	f, err := os.Create(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	z := gzip.NewWriter(f)
	encoder := json.NewEncoder(z)
	for _, row := range rows {
		if err := encoder.Encode(row); err != nil {
			t.Fatal(err)
		}
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return replayTestPin(t, root, name)
}

// replayTestCSV は確定足の形だけを持つ人工CSVを作ります。
//
// 引数: t(*testing.T)は検査、root/name(string)は一時先、rows([][]string)は人工足です。
// 返り値: InputFileは人工CSVの指紋です。
func replayTestCSV(t *testing.T, root, name string, rows [][]string) InputFile {
	t.Helper()
	f, err := os.Create(filepath.Join(root, name))
	if err != nil {
		t.Fatal(err)
	}
	w := csv.NewWriter(f)
	if err := w.Write([]string{"time", "open", "high", "low", "close", "closed"}); err != nil {
		t.Fatal(err)
	}
	for _, row := range rows {
		if err := w.Write(row); err != nil {
			t.Fatal(err)
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return replayTestPin(t, root, name)
}

// replayTestFixture は二市場・6入力の自己完結した人工場を作ります。
//
// 引数: t(*testing.T)は検査、id(string)は場ID、times([]float64)は人工原行時計です。
// 返り値: stringは一時領域、InputSessionは全6人工指紋です。
func replayTestFixture(t *testing.T, id string, times []float64) (string, InputSession) {
	t.Helper()
	root := t.TempDir()
	input := InputSession{ID: id, Contract: "NK202612", Files: map[string]InputFile{}}
	for _, ref := range []string{"NK225", "TOPIX"} {
		code, price := "NK202612", 1000.0
		if ref == "TOPIX" {
			code, price = "TP202612", 4000
		}
		rows := []map[string]any{}
		for _, at := range times {
			rows = append(rows, replayTestRaw(at, price, code))
		}
		input.Files[ref+"_book"] = replayTestGzip(t, root, ref+".jsonl.gz", rows)
		for _, interval := range []int{60, 300} {
			name := fmt.Sprintf("%s_%d.csv", ref, interval)
			input.Files[fmt.Sprintf("%s_candle_%d", ref, interval)] = replayTestCSV(t, root, name, nil)
		}
	}
	return root, input
}

// TestReplayFingerprint はサイズ・SHAの片方だけが変わる場合も拒否します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。人工一時ファイル以外を読みません。
func TestReplayFingerprint(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "人工.txt"), []byte("固定した人工入力"), 0600); err != nil {
		t.Fatal(err)
	}
	pin := replayTestPin(t, root, "人工.txt")
	if _, err := verifyInput(root, pin); err != nil {
		t.Fatal(err)
	}
	for _, change := range []func(*InputFile){
		func(f *InputFile) { f.Size++ },
		func(f *InputFile) { f.SHA256 = strings.Repeat("0", 64) },
	} {
		bad := pin
		change(&bad)
		if _, err := verifyInput(root, bad); err == nil {
			t.Fatal("指紋の不一致を受理")
		}
	}
}

// TestReplayRawClockQuality は同時計・元行番号・欠落時計・逆順の内訳を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。正常LastとBBO不良を別々に数えます。
func TestReplayRawClockQuality(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	rows := []map[string]any{}
	for _, at := range []float64{session.Start - 1, session.Start, session.Start, session.Start + 1, session.Start + 1, session.Start + 2, session.Start + 1, session.End, session.Start + 3} {
		rows = append(rows, replayTestRaw(at, 1000, "NK202612"))
	}
	delete(rows[1], "CurrentPriceTime")
	rows[2]["CurrentPriceTime"] = nil
	rows[4]["CurrentPrice"] = nil
	rows[5]["Buy1"] = map[string]float64{"Price": 1002, "Qty": 10}
	pin := replayTestGzip(t, root, "品質.gz", rows)
	got, quality, err := readBoards(filepath.Join(root, pin.Path), "NK225", session)
	if err != nil {
		t.Fatal(err)
	}
	if quality.Lines != 9 || quality.ClockMissing != 2 || quality.Outside != 2 || quality.Backward != 1 || quality.BadLast != 1 || quality.BadQuote != 1 || quality.Accepted != 4 {
		t.Fatalf("原行品質の独立内訳が不一致: %+v", quality)
	}
	lines := []int64{}
	for _, row := range got {
		lines = append(lines, row.Line)
	}
	if !reflect.DeepEqual(lines, []int64{4, 5, 6, 9}) || got[0].Board.Time != got[1].Board.Time {
		t.Fatal("同時計原行の省略又は原行番号の置換")
	}
	if got[2].Board.Last != 1000 || got[2].Board.Bid <= got[2].Board.Ask {
		t.Fatal("正常Lastと交差BBOの分離が不正")
	}
}

// TestReplayCandlePublication は確定足を終端と公開遅延の後へだけ配置します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。途中足・場外足を当場へ持ち込みません。
func TestReplayCandlePublication(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	rows := [][]string{
		{replayTestStamp(session.Start), "100", "110", "90", "105", "true"},
		{replayTestStamp(session.Start + 60), "100", "110", "90", "105", "false"},
		{replayTestStamp(session.End), "100", "110", "90", "105", "true"},
	}
	pin := replayTestCSV(t, root, "足.csv", rows)
	got, err := readCandles(filepath.Join(root, pin.Path), "NK225", 60, 2, session)
	if err != nil || len(got) != 1 {
		t.Fatalf("確定足の集合が不正: %v %v", got, err)
	}
	if got[0].At != session.Start+62 || got[0].Candle.Time != session.Start || got[0].Candle.Close != 105 {
		t.Fatal("足の開始と公開時計又は終値が混同")
	}
}

// TestReplayGridUsesPreviousRow は定時の現在原行不使用とEOF後全枠記録を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。人工一場のI/Oだけを通し、将来気配を約定しません。
func TestReplayGridUsesPreviousRow(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	grids, err := ScheduledTimes(session.ID)
	if err != nil {
		t.Fatal(err)
	}
	root, input := replayTestFixture(t, session.ID, []float64{session.Start, grids[0] - 1, grids[0]})
	before, _ := json.Marshal(input)
	result, err := Replay(root, input, NewTechnicalBank(), 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"F0", "P1", "T1"} {
		book := result.Books[mode]
		if len(book.Decisions) != 25 {
			t.Fatal("EOF後の定時を省略")
		}
		first := book.Decisions[0]
		if first.At != grids[0] || first.QuoteTime != grids[0]-1 || first.QuoteIndex != 1 {
			t.Fatalf("定時でcurrent行を先取り: %+v", first)
		}
		if len(book.Trades) != 0 || book.Unresolved {
			t.Fatal("人工の無信号から約定又は未決を創作")
		}
	}
	after, _ := json.Marshal(input)
	if string(before) != string(after) || session.End-session.ForceClose != 600 {
		t.Fatal("元台帳変更又はForceCloseが場末10分前でない")
	}
	for _, pin := range input.Files {
		if _, err := verifyInput(root, pin); err != nil {
			t.Fatal("再生で元人工ファイルを変更")
		}
	}
}

// TestReplayNightTimerUniqueness はUS境界と定時の同時計を一回だけ処理します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。米国前後とForceCloseを人工全行で通します。
func TestReplayNightTimerUniqueness(t *testing.T) {
	session, err := sessionClock("2026-11-06_Night")
	if err != nil {
		t.Fatal(err)
	}
	root, input := replayTestFixture(t, session.ID, []float64{session.Start, session.USOpen - 901, session.USOpen - 900, session.USOpen - 899, session.USOpen + 899, session.USOpen + 900, session.USOpen + 901, session.ForceClose - 1, session.ForceClose, session.End - 1})
	result, err := Replay(root, input, NewTechnicalBank(), 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"F0", "P1", "T1"} {
		seen := map[float64]bool{}
		for _, decision := range result.Books[mode].Decisions {
			if seen[decision.At] || decision.QuoteTime > decision.At {
				t.Fatal("US境界の二重定時又は将来気配")
			}
			seen[decision.At] = true
		}
		if len(seen) != 49 {
			t.Fatalf("夜間の全枠数が不正: %d", len(seen))
		}
	}
	if result.ReferenceCounts["U165_03"] == 0 || result.ReferenceCounts["P164_06"] != 10 {
		t.Fatal("US前後の参照起動又は元全行供給の件数が不正")
	}
}

// TestReplayStrictPeerPast は同時計TOPIXを先に追加しても未来相手値を使わないことを確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。固定純特徴APIへ人工板3行だけを渡します。
func TestReplayStrictPeerPast(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	params, err := strategy.ParametersForMethod("NK225", "Day", "D164_15")
	if err != nil {
		t.Fatal(err)
	}
	f, err := strategy.NewFeatures(session, map[string]float64{"NK225": 10, "TOPIX": .5}, params.Features)
	if err != nil {
		t.Fatal(err)
	}
	for _, b := range []strategy.Board{
		{Reference: "TOPIX", Time: session.Start + 1, Received: session.Start + 1, Last: 4000, Bid: 3999, Ask: 4001},
		{Reference: "TOPIX", Time: session.Start + 2, Received: session.Start + 2, Last: 5000, Bid: 4999, Ask: 5001},
	} {
		if _, err := f.OnBoard(b); err != nil {
			t.Fatal(err)
		}
	}
	o, err := f.OnBoard(strategy.Board{Reference: "NK225", Time: session.Start + 2, Received: session.Start + 2, Last: 1000, Bid: 999, Ask: 1001})
	if err != nil {
		t.Fatal(err)
	}
	for _, market := range []strategy.Market{o.DayMarket, o.LastMarket, o.MidMarket} {
		if market.PeerTime != session.Start+1 || market.Peer != 4000 {
			t.Fatalf("同時計相手板を参照: %+v", market)
		}
	}
}

// TestReplayContractAndManifest は限月・台帳順序・コード指紋の異常を拒否します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。全指紋は人工一時ファイルのものです。
func TestReplayContractAndManifest(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	root, input := replayTestFixture(t, session.ID, []float64{session.Start})
	input.Contract = "別限月"
	if _, err := Replay(root, input, NewTechnicalBank(), 0); err == nil || !strings.Contains(err.Error(), "限月") {
		t.Fatal("保存NK限月と台帳の不一致を受理")
	}
	input.Contract = "NK202612"
	if err := os.WriteFile(filepath.Join(root, "人工純戦略.go"), []byte("人工のコード指紋だけ"), 0600); err != nil {
		t.Fatal(err)
	}
	code := replayTestPin(t, root, "人工純戦略.go")
	valid := InputManifest{Root: root, Sessions: []InputSession{input}, StrategyRoot: root, StrategySHA256: map[string]string{code.Path: code.SHA256}}
	if err := ValidateManifest(valid); err != nil {
		t.Fatal(err)
	}
	for _, example := range []string{"重複", "逆順", "限月空", "コード差", "空台帳", "入力key", "入力SHA", "入力サイズ"} {
		encoded, err := json.Marshal(valid)
		if err != nil {
			t.Fatal(err)
		}
		var bad InputManifest
		if err := json.Unmarshal(encoded, &bad); err != nil {
			t.Fatal(err)
		}
		switch example {
		case "重複":
			bad.Sessions = append(bad.Sessions, bad.Sessions[0])
		case "逆順":
			second := bad.Sessions[0]
			second.ID = "2026-11-05_Night"
			bad.Sessions = append(bad.Sessions, second)
		case "限月空":
			bad.Sessions[0].Contract = ""
		case "コード差":
			bad.StrategySHA256[code.Path] = strings.Repeat("0", 64)
		case "空台帳":
			bad.Sessions = nil
		case "入力key":
			file := bad.Sessions[0].Files["NK225_book"]
			delete(bad.Sessions[0].Files, "NK225_book")
			bad.Sessions[0].Files["不正key"] = file
		case "入力SHA":
			file := bad.Sessions[0].Files["NK225_book"]
			file.SHA256 = "不正SHA"
			bad.Sessions[0].Files["NK225_book"] = file
		case "入力サイズ":
			file := bad.Sessions[0].Files["NK225_book"]
			file.Size = 0
			bad.Sessions[0].Files["NK225_book"] = file
		}
		if err := ValidateManifest(bad); err == nil {
			t.Fatalf("台帳異常を受理: %s", example)
		}
	}
}

// TestReplayLastChartIndependent は再生全経路でLast技法とBBO会計の品質を分離します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。交差BBOでも正常Lastは足を作り、未知Lastだけをresetします。
func TestReplayLastChartIndependent(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	times := []float64{}
	for at := session.Start; at < session.End; at += 60 {
		times = append(times, at)
	}
	for _, badLast := range []bool{false, true} {
		root, input := replayTestFixture(t, session.ID, times)
		rows := []map[string]any{}
		for _, at := range times {
			row := replayTestRaw(at, 1000, input.Contract)
			row["Buy1"], row["Sell1"] = map[string]float64{"Price": 1002, "Qty": 10}, map[string]float64{"Price": 1001, "Qty": 10}
			if badLast && at == session.End-600 {
				row["CurrentPrice"] = nil
			}
			rows = append(rows, row)
		}
		input.Files["NK225_book"] = replayTestGzip(t, root, "交差Last.gz", rows)
		if badLast {
			other := []map[string]any{}
			for _, at := range times {
				row := replayTestRaw(at, 4000, "TP202612")
				if at == session.End-600 {
					row["CurrentPrice"] = nil
				}
				other = append(other, row)
			}
			input.Files["TOPIX_book"] = replayTestGzip(t, root, "相手Last未知.gz", other)
		}
		bank := NewTechnicalBank()
		result, err := Replay(root, input, bank, 0)
		if err != nil {
			t.Fatalf("Last未知=%vで再生中断: %v", badLast, err)
		}
		if result.Quality["NK225"].BadQuote != int64(len(times)) {
			t.Fatal("交差BBOの品質件数が不正")
		}
		if bank.View().TrendKnown == badLast || bank.View().ATRKnown == badLast {
			t.Fatalf("BBO不良とLast不良の技法maskを混同: Last不良=%v view=%+v", badLast, bank.View())
		}
		for _, book := range result.Books {
			if len(book.Trades) != 0 || book.Decisions[0].Action != "判定不能" {
				t.Fatal("BBO不良で実新規又は正常判断を創作")
			}
		}
	}
}

// TestReplayBadLastKeepsRawIndex はLast不良でも実原行連番を進め定時を保留します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。源特徴器の連番を実約定時計へ流用しません。
func TestReplayBadLastKeepsRawIndex(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	grids, err := ScheduledTimes(session.ID)
	if err != nil {
		t.Fatal(err)
	}
	root, input := replayTestFixture(t, session.ID, []float64{session.Start, grids[0] - 1, grids[0]})
	rows := []map[string]any{replayTestRaw(session.Start, 1000, input.Contract), replayTestRaw(grids[0]-1, 1000, input.Contract), replayTestRaw(grids[0], 1000, input.Contract)}
	delete(rows[1], "CurrentPrice")
	input.Files["NK225_book"] = replayTestGzip(t, root, "Last欠落.gz", rows)
	result, err := Replay(root, input, NewTechnicalBank(), 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, book := range result.Books {
		first, second := book.Decisions[0], book.Decisions[1]
		if first.QuoteIndex != 1 || first.Action != "判定不能" || second.QuoteIndex != 2 {
			t.Fatalf("Last未知の原行又は鮮度が補完: %+v %+v", first, second)
		}
	}
	if result.Quality["NK225"].BadLast != 1 || result.ReferenceCounts["D164_15"] != 2 {
		t.Fatal("Last未知で源判断を創作又は品質件数を隠した")
	}
}

// TestReplayEndPendingContract はdriverが使うForce契約のEOF未決を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。返済の後原行がなければ実現益や返済約定を作りません。
func TestReplayEndPendingContract(t *testing.T) {
	session, err := sessionClock("2026-11-06_Day")
	if err != nil {
		t.Fatal(err)
	}
	for _, filled := range []bool{false, true} {
		book, err := NewBook(session.ID, "F0", 100)
		if err != nil {
			t.Fatal(err)
		}
		at := session.ForceClose - 1200
		q := Quote{Time: at, Index: 0, Line: 1, Last: 1000, Bid: 999, Ask: 1001, Valid: true}
		if err := book.OnQuote(q, ReferenceFrame{}, TechnicalView{}); err != nil {
			t.Fatal(err)
		}
		frame := ReferenceFrame{Lots: []ReferenceLot{{ID: "人工参照", Side: 1, Quantity: 1, Entry: 1001, At: at, Method: "NK225_D164_15", Kind: "人工"}}}
		if err := book.OnGrid(at, q, frame, TechnicalView{}); err != nil {
			t.Fatal(err)
		}
		if filled {
			q.Time, q.Index, q.Line = at+1, 1, 2
			if err := book.OnQuote(q, ReferenceFrame{}, TechnicalView{}); err != nil {
				t.Fatal(err)
			}
		}
		if err := book.Force(session.ForceClose, q, "人工場末10分前"); err != nil {
			t.Fatal(err)
		}
		result := book.Result()
		if filled {
			if !result.Unresolved || result.Metrics.OpenQuantity != 1 || result.Metrics.ReservedExitQuantity != 1 || len(result.Trades) != 1 || result.Metrics.NetPnLYen != 0 {
				t.Fatal("EOF返済未決を架空約定又は確定損益へ補完")
			}
		} else if result.Unresolved || result.Metrics.EntryQuantity != 0 || len(result.Trades) != 0 || result.Orders[0].Status != "cancelled" {
			t.Fatal("Forceで未約定新規を取消していない")
		}
	}
}

// TestReplayCanonicalSessionClocks は正本fixtureの昼夜別時計を独立の日本時計へ照合します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。日中の米国時計0、夜間のUS相対補完とCoreStart既定を固定します。
func TestReplayCanonicalSessionClocks(t *testing.T) {
	for _, example := range []struct {
		id, start, end, force, extra, us string
	}{
		{"2026-09-21_Day", "2026-09-21 08:45", "2026-09-21 15:45", "2026-09-21 15:35", "2026-09-21 12:30", ""},
		{"2026-11-02_Day", "2026-11-02 08:45", "2026-11-02 15:45", "2026-11-02 15:35", "2026-11-02 12:30", ""},
		{"2026-09-21_Night", "2026-09-21 17:00", "2026-09-22 06:00", "2026-09-22 05:50", "2026-09-21 23:00", "2026-09-21 22:30"},
		{"2026-11-02_Night", "2026-11-02 17:00", "2026-11-03 06:00", "2026-11-03 05:50", "2026-11-03 00:00", "2026-11-02 23:30"},
	} {
		session, err := sessionClock(example.id)
		if err != nil {
			t.Fatal(err)
		}
		wantUS := 0.0
		if example.us != "" {
			wantUS = tokyoArtificial(t, example.us)
		}
		actual := []float64{session.Start, session.End, session.ForceClose, session.ExtraAt, session.USOpen, session.NightCoreStart}
		expected := []float64{tokyoArtificial(t, example.start), tokyoArtificial(t, example.end), tokyoArtificial(t, example.force), tokyoArtificial(t, example.extra), wantUS, 0}
		if !reflect.DeepEqual(actual, expected) {
			t.Fatalf("正本の場時計と不一致: %s 実値=%v 期待=%v", example.id, actual, expected)
		}
	}
}

// replayTestPortfolio は参照会計の可視の純Portfolioだけを読み取ります。
//
// 引数: t(*testing.T)は検査、ref(*Reference)は人工初期化した参照です。
// 返り値: *strategy.Portfolioは同じpackageのwrapperから読んだ純状態で、設定・アプリを起動しません。
func replayTestPortfolio(t *testing.T, ref *Reference) *strategy.Portfolio {
	t.Helper()
	book, ok := ref.book.(*strategyReferenceBook)
	if !ok || book.Portfolio == nil || book.Selected == nil || book.Selected.Shadow == nil {
		t.Fatal("参照の可視純Portfolio構造が不正")
	}
	return book.Portfolio
}

// replayTestCoreSource は公開Research構造からcore担当を読取します。
//
// 引数: t(*testing.T)は検査、p(*strategy.Portfolio)は人工D07会計です。
// 返り値: *strategy.ResearchSourceはLegacy/Supplementを持つcore源です。
func replayTestCoreSource(t *testing.T, p *strategy.Portfolio) *strategy.ResearchSource {
	t.Helper()
	if p == nil || p.Research == nil {
		t.Fatal("D07研究会計が未生成")
	}
	for _, sleeve := range p.Research.Sleeves {
		if sleeve.Name == "core" {
			if sleeve.Source == nil || sleeve.Source.Legacy == nil || sleeve.Source.Supplement == nil {
				t.Fatal("core源の可視構造が不正")
			}
			return sleeve.Source
		}
	}
	t.Fatal("core担当が存在しない")
	return nil
}

// TestReplayReferenceNightClockPropagation はP/Uで異なるCoreStartとUS相対時計を確認します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。純参照の初期化だけを行い、観測・発注・市場を進めません。
func TestReplayReferenceNightClockPropagation(t *testing.T) {
	for _, id := range []string{"2026-09-21_Night", "2026-11-02_Night"} {
		session, err := sessionClock(id)
		if err != nil {
			t.Fatal(err)
		}
		original := session
		u, err := NewReference("U165_03", session, 100)
		if err != nil {
			t.Fatal(err)
		}
		up := replayTestPortfolio(t, u)
		ucore := replayTestCoreSource(t, up.Selected.Shadow)
		if up.Selected.Shadow.Config.Parameters.Method != "D07" {
			t.Fatal("Uの源がD07ではない")
		}
		for name, s := range map[string]strategy.Session{"root": up.Session, "shadow": up.Selected.Shadow.Session,
			"source": ucore.Session, "legacy": ucore.Legacy.Session, "supplement": ucore.Supplement.Session} {
			if s.ExtraAt != session.USOpen+1800 || s.NightCoreStart != 0 || s.USOpen != session.USOpen || s.ForceClose != session.ForceClose {
				t.Fatalf("UのUS相対時計が末端へ未伝播: %s %+v", name, s)
			}
		}
		if ucore.Legacy.Config.Parameters.Night.PostOpenPrepareSeconds != 1320 || ucore.Supplement.Config.Parameters.Night.PostOpenPrepareSeconds != 1320 {
			t.Fatal("U主担当の正本US+22分準備が変化")
		}
		// ----------------------------------------
		// P05は独立仮想Legacyだけを場開始へ変更し、Supplementへ広げません。
		p, err := NewReference("P164_06", session, 100)
		if err != nil {
			t.Fatal(err)
		}
		pp := replayTestPortfolio(t, p)
		shadow := pp.Selected.Shadow
		if shadow.Config.Parameters.Method != "P05" || shadow.P05 == nil || shadow.P05.Shadow == nil {
			t.Fatal("P05独立仮想源の接続が不正")
		}
		pbase := shadow.P05.Shadow
		pcore := replayTestCoreSource(t, pbase)
		for name, s := range map[string]strategy.Session{"selected": shadow.Session, "p05shadow": pbase.Session,
			"source": pcore.Session, "supplement": pcore.Supplement.Session} {
			if s.ExtraAt != session.USOpen+1800 || s.NightCoreStart != 0 || s.ForceClose != session.USOpen-900 {
				t.Fatalf("P05内部上書きの範囲が不正: %s %+v", name, s)
			}
		}
		if pcore.Legacy.Session.NightCoreStart != session.Start || pcore.Legacy.Session.ExtraAt != session.USOpen+1800 ||
			pcore.Legacy.Session.ForceClose != session.USOpen-900 || pcore.Supplement.Config.Parameters.Night.PostOpenPrepareSeconds != 1320 {
			t.Fatal("P05がLegacyだけを場開始へ上書きする正本と不一致")
		}
		if session != original {
			t.Fatal("参照初期化が元の場時計を変更")
		}
		t.Logf("%s: U準備US+1320/補完US+1800、P LegacyだけStart、P SupplementはUS+1320", id)
	}
}

// TestReplayLegacyWrongClockReachesSource は初版の誤時計が実際に源まで届くことを示します。
//
// 引数: t(*testing.T)はGo検査器です。
// 返り値: ありません。初版時計を人工的に与える比較で、源判断や市場は実行しません。
func TestReplayLegacyWrongClockReachesSource(t *testing.T) {
	correct, err := sessionClock("2026-09-21_Night")
	if err != nil {
		t.Fatal(err)
	}
	wrong := correct
	wrong.ExtraAt, wrong.NightCoreStart = wrong.Start+13500, wrong.Start
	u, err := NewReference("U165_03", wrong, 100)
	if err != nil {
		t.Fatal(err)
	}
	up := replayTestPortfolio(t, u)
	ucore := replayTestCoreSource(t, up.Selected.Shadow)
	if ucore.Legacy.Session.NightCoreStart != wrong.Start || ucore.Supplement.Session.NightCoreStart != wrong.Start ||
		ucore.Session.ExtraAt != wrong.Start+13500 || ucore.Legacy.Session.ExtraAt != wrong.Start+13500 {
		t.Fatal("初版時計を与えた人工で、伝播経路が想定と異なる")
	}
	p, err := NewReference("P164_06", wrong, 100)
	if err != nil {
		t.Fatal(err)
	}
	pp := replayTestPortfolio(t, p)
	pcore := replayTestCoreSource(t, pp.Selected.Shadow.P05.Shadow)
	if pcore.Session.ExtraAt != correct.USOpen+1800 || pcore.Legacy.Session.NightCoreStart != wrong.Start ||
		pcore.Supplement.Session.NightCoreStart != wrong.Start {
		t.Fatal("P05の内部上書きと、外部誤時計のSupplement伝播が不一致")
	}
}
