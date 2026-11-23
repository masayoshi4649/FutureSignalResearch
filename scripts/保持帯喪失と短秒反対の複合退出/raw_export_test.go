package far86

import (
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// rawArtificialQuote は採用前の全物理原行と源特徴への供給を明示します。
type rawArtificialQuote struct {
	Quote           Quote `json:"quote"`
	ClockMissing    bool  `json:"clock_missing"`
	Accepted        bool  `json:"accepted"`
	FeatureExpected int64 `json:"feature_expected"`
}

// prepareRawRuntime は全物理20行から短秒前史とbefore実Index8/源Index7を構成します。
//
// 引数: t(*testing.T)、runtime(*replayRuntime)、source(*strategy.SelectedDay164Features)は検査器・手製指標種・空の源短秒履歴です。
// 返り値: []rawArtificialQuoteは11欠測時計行と9採用行で、Last0の1行だけ源へ供給しません。
func prepareRawRuntime(t *testing.T, runtime *replayRuntime, source *strategy.SelectedDay164Features) []rawArtificialQuote {
	t.Helper()
	before := runtime.last
	raw := []rawArtificialQuote{}
	for line := int64(1); line <= 11; line++ {
		raw = append(raw, rawArtificialQuote{Quote: Quote{Index: -1, Line: line}, ClockMissing: true, FeatureExpected: -1})
	}
	actual, feature := int64(-1), int64(-1)
	var lastRow *CurrentEvidence
	for i := 0; i < 8; i++ {
		q := before
		q.Time, q.Index, q.Line = before.Time-35+float64(i)*5, actual+1, int64(len(raw)+1)
		actual++
		feature++
		lastRow = input86SourceRow(q, source)
		lastRow.SourceIndex = feature
		raw = append(raw, rawArtificialQuote{Quote: q, Accepted: true, FeatureExpected: feature})
		if i == 4 {
			bad := q
			bad.Time, bad.Index, bad.Line, bad.Last, bad.Valid = q.Time+2.5, actual+1, int64(len(raw)+1), 0, false
			actual++
			raw = append(raw, rawArtificialQuote{Quote: bad, Accepted: true, FeatureExpected: -1})
		}
	}
	if len(raw) != 20 || actual != 8 || feature != 7 || lastRow == nil || !lastRow.Short.Five.Known || !lastRow.Short.Fifteen.Known {
		t.Fatal("全原行付き前史の番号又は短秒既知に差", len(raw), actual, feature)
	}
	before.Index = actual
	current := runtime.current
	current.SourceIndex, current.SourceLine, current.Short = feature, before.Line, lastRow.Short
	// ----------------------------------------
	// 指標種と入口E08は手製のまま、金融は空Bookを再作成しbefore8だけを初回通知します。
	runtime.books = map[string]*Book{}
	runtime.last = Quote{Index: -1}
	for _, mode := range Modes {
		for delay := 0; delay <= 1; delay++ {
			book, err := NewBook(runtime.session.ID, "S0G1", 100, false)
			if err != nil {
				t.Fatal(err)
			}
			if err = book.SetConfirmEnabled(mode == "J1G1"); err != nil {
				t.Fatal(err)
			}
			if err = book.SetFillDelay(float64(delay)); err != nil {
				t.Fatal(err)
			}
			runtime.books[bookKey(mode, delay)] = book
		}
	}
	if err := runtime.observeQuote(before, &current); err != nil {
		t.Fatal(err)
	}
	return raw
}

// TestExportRawArtificialSnapshots は源前史を全原行から再構成できる買売4状態を保存します。
//
// 引数: t(*testing.T)、環境変数FAR86_RAW_ARTIFICIAL_OUT(string)は検査器と新規絶対保存先です。
// 返り値: ありません。未指定はskip。市場読取・新損益再生は行いません。
func TestExportRawArtificialSnapshots(t *testing.T) {
	exportArtificialSnapshots(t, "FAR86_RAW_ARTIFICIAL_OUT", true)
}
