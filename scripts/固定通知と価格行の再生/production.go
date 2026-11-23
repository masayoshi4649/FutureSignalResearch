package lighttape97

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"reflect"

	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// ProductionInput は既読先頭2場だけのScalar/時計と明示Originを受け取ります。
type ProductionInput struct {
	Version    int               `json:"version"`
	NativePath string            `json:"native_path"`
	NativeSHA  string            `json:"native_sha256"`
	Session    actual.Session    `json:"session"`
	Routes     []CancelRoute     `json:"cancel_routes"`
	Events     []TapeEvent       `json:"events"`
	Evidence   map[string]string `json:"input_sha256"`
}

// Digest は保存入力のbytes指紋を返します。
//
// 引数: path(string)は許可された入力です。
// 返り値: string/errorはSHA256又は読取不整合です。
func Digest(path string) (string, error) {
	body, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	v := sha256.Sum256(body)
	return hex.EncodeToString(v[:]), nil
}

// BuildProduction は96公開Ledgerを使い、先頭2場のSource配送Tapeを構築します。
//
// 引数: in(ProductionInput)は固定Raw/ATRから作った明示イベント列です。
// 返り値: Tape/actual.ReplayResult/errorはTapeと旧比較元又は未結合です。Sourceは再運転しません。
func BuildProduction(in ProductionInput) (Tape, actual.ReplayResult, error) {
	var base actual.ReplayResult
	if in.Version != 1 || (in.Session.ID != "2026-09-21_Day" && in.Session.ID != "2026-09-21_Night") {
		return Tape{}, base, fmt.Errorf("許可先頭2場/版だけ")
	}
	digest, err := Digest(in.NativePath)
	if err != nil {
		return Tape{}, base, err
	}
	if digest != in.NativeSHA {
		return Tape{}, base, fmt.Errorf("元96保存SHA差")
	}
	body, err := os.ReadFile(in.NativePath)
	if err != nil {
		return Tape{}, base, err
	}
	if err = json.Unmarshal(body, &base); err != nil {
		return Tape{}, base, err
	}
	if base.Session != in.Session.ID || !base.ShadowMatch.All || !base.NeutralMatch.All {
		return Tape{}, base, fmt.Errorf("元96の完了対照が不明")
	}
	if !reflect.DeepEqual(base.Books["B5Q_P0_C0_D0"].Session, in.Session) {
		return Tape{}, base, fmt.Errorf("元96場時計と不一致")
	}
	index, err := NewSourceIndex(base.Shadows, in.Routes)
	if err != nil {
		return Tape{}, base, err
	}
	expected := map[string]actual.SourceEventTrace{}
	for _, e := range base.Books["B5Q_P0_C0_D0"].SourceEvents {
		if e.Kind == "close_notice" {
			k := key(e.Method, e.NoticeID)
			if _, ok := expected[k]; ok {
				return Tape{}, base, fmt.Errorf("旧G0 notice重複")
			}
			expected[k] = e
		}
	}
	used := map[string]bool{}
	gridIndex := 0
	tape := Tape{Version: 1, Scope: "固定96先頭2場の公開Source通知/Scalar/既存ChartGrid再用。Source判断再運転0", Session: in.Session, Capabilities: Capabilities(), Events: []TapeEvent{}, Provenance: in.Evidence}
	for i, e := range in.Events {
		if e.Ordinal != i+1 || len(e.NonEmpty) != 0 {
			return Tape{}, base, fmt.Errorf("入力イベント連番/元通知の架空注入")
		}
		if e.Kind == "grid" {
			if gridIndex >= len(base.ChartGrids) || e.Context == nil || !reflect.DeepEqual(*e.Context, base.ChartGrids[gridIndex]) {
				return Tape{}, base, fmt.Errorf("96共有ChartGridを変更又は欠落")
			}
			gridIndex++
			tape.Events = append(tape.Events, e)
			continue
		}
		origin := "quote"
		var q actual.QuoteStamp
		if e.Kind == "force" {
			origin = "timer"
		} else if e.Kind == "quote" && e.Quote != nil {
			q = e.Quote.stamp()
		} else {
			return Tape{}, base, fmt.Errorf("生原行/Force種別不明")
		}
		batches, err := index.Take(e.At, origin, q, e.Methods)
		if err != nil {
			return Tape{}, base, err
		}
		for _, b := range batches {
			position := 0
			for _, r := range b.Delta.Signals {
				if r.Signal.Action != "close" {
					continue
				}
				for _, target := range r.Signal.Targets {
					if position >= len(b.Delta.Closes) {
						return Tape{}, base, fmt.Errorf("再構成Close不足")
					}
					n := b.Delta.Closes[position]
					position++
					k := key("NK225_"+b.Method, n.ID)
					old, ok := expected[k]
					if !ok || used[k] || old.At != e.At || old.SignalID != r.Signal.ID || old.HoldID != target.ID || old.NoticeID != n.ID || old.Before != n.Before || old.Quantity != n.Quantity || old.Reason != n.Reason || old.Quote != r.Quote || old.Phase != "source_close" {
						return Tape{}, base, fmt.Errorf("Source Before/TargetsがG0明示noticeと相違")
					}
					used[k] = true
				}
			}
		}
		e.Methods, e.NonEmpty, err = CompressBatches(batches)
		if err != nil {
			return Tape{}, base, err
		}
		tape.Events = append(tape.Events, e)
	}
	if len(used) != len(expected) || gridIndex != len(base.ChartGrids) || !reflect.DeepEqual(index.rows, base.SourceRows) {
		return Tape{}, base, fmt.Errorf("全notice/grid/Source行数の欠落")
	}
	if err = index.Finish(); err != nil {
		return Tape{}, base, err
	}
	return tape, base, nil
}

// CompareEight は元96と再現結果を除外0のJSON全文で比較します。
//
// 引数: got(map)、base(actual.ReplayResult)は再現8Bookと元96です。
// 返り値: errorは8Bookの件数/全文相違です。損益だけの一致を採用条件にしません。
func CompareEight(got map[string]actual.ActualResult, base actual.ReplayResult) error {
	if len(got) != 8 {
		return fmt.Errorf("八口座の件数不整合")
	}
	for k, r := range got {
		old, ok := base.Books[k]
		if !ok {
			return fmt.Errorf("元96にないkey")
		}
		a, _ := json.Marshal(r)
		b, _ := json.Marshal(old)
		if string(a) != string(b) {
			return fmt.Errorf("元96とのBook全文相違:%s", k)
		}
	}
	return nil
}
