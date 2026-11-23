// 由来: production.go の BuildProduction。価格/Source再構成本文はScope文字列以外同体。
package lighttape97

import (
	"fmt"
	actual "github.com/masayoshi4649/SessionTradeExecuter/minichart"
	"reflect"
)

// BuildSelectedProduction は固定96正式gzipだけを新しい許可境界で受けます。
//
// 引数: in(ProductionInput)、completion(string)は明示イベントと固定96完了記録です。
// 返り値: Tape/actual.ReplayResult/errorは再用入力と旧比較元又は出典不整合です。
// 旧BuildProductionの2場制限と本文は変更しません。Source/Featuresの判断は再運転しません。
func BuildSelectedProduction(in ProductionInput, completion string) (Tape, actual.ReplayResult, error) {
	var base actual.ReplayResult
	if in.Version != 1 {
		return Tape{}, base, fmt.Errorf("構築入力版が不明")
	}
	if err := ValidateSelectedNative(completion, in.Session.ID, in.NativePath, in.NativeSHA); err != nil {
		return Tape{}, base, err
	}
	var err error
	base, err = readGzipNative(in.NativePath)
	if err != nil {
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
	tape := Tape{Version: 1, Scope: "固定96完了54許可集合の公開Source通知/Scalar/既存ChartGrid再用。Source判断再運転0", Session: in.Session, Capabilities: Capabilities(), Events: []TapeEvent{}, Provenance: in.Evidence}
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
