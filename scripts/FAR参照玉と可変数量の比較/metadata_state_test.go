package far87

import (
	"encoding/json"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
)

// TestMetadataKnownAndApplicability は元親量の未知と規則の対象外を別に保存します。
//
// 引数: t(*testing.T)は読取境界の人工です。
// 返り値: ありません。現在17を親初回20へ補完せず、元追加の小量不適格も既知として残します。
func TestMetadataKnownAndApplicability(t *testing.T) {
	for _, method := range []string{"D164_15", "P164_06", "U165_03"} {
		r, err := NewReference(method, session87(method), 100)
		need87(t, err)
		p := source87(r)
		p.Selected.Lots = []strategy.SelectedLot{{ID: "内部", HoldID: "Hold", Parent: "親", SourceID: "源", Owner: "core", Kind: "source_add", Side: 1, Quantity: 17, InitialQuantity: 32, Entry: 10010, At: 1101}}
		r.refresh()
		unknown, err := r.ReadMetadata()
		need87(t, err)
		row := unknown.Lots[0]
		if row.NativeParentInitialKnown || row.NativeParentInitialMicro != nil || row.NativeParentInitialReason != "元親状態未取得" {
			t.Fatal("親初回未知の捏造", method, row)
		}
		if row.NativeParentOriginalDesiredApplicable != (method == "D164_15") || row.NativeParentOriginalDesiredKnown || row.NativeParentOriginalDesired == nil && row.NativeParentOriginalDesiredReason == "" {
			t.Fatal("希望量の未知・対象外不明", method, row)
		}
		if row.SmallInitialRuleApplicable != (method == "P164_06") || row.NativeSmallInitialKnown || row.NativeSmallInitialEligible != nil || row.NativeSmallInitialReason == "" {
			t.Fatal("小量資格の未知・対象外不明", method, row)
		}
		if method == "D164_15" {
			need87(t, json.Unmarshal([]byte(`{"Parents":{"親":{"Side":1,"InitialSeen":false}}}`), p.Selected.Day))
			x, err := r.ReadMetadata()
			need87(t, err)
			if x.Lots[0].NativeParentInitialReason != "元親初回未観測" || x.Lots[0].NativeParentOriginalDesiredReason != "元親初回未観測" {
				t.Fatal("親未観測を対象外へ変更", x)
			}
			need87(t, json.Unmarshal([]byte(`{"Parents":{"親":{"Side":1,"InitialSeen":true,"NativeInitial":50,"OriginalDesired":32}}}`), p.Selected.Day))
		} else {
			need87(t, json.Unmarshal([]byte(`{"Parents":{"親":{"Side":1,"InitialSource":"源","InitialMicro":20}}}`), p.Selected.Night))
		}
		known, err := r.ReadMetadata()
		need87(t, err)
		row = known.Lots[0]
		if !row.NativeParentInitialKnown || row.NativeParentInitialMicro == nil || row.Reference.Quantity != 17 || row.ReferenceInitialQuantity != 32 {
			t.Fatal("元初回と現在量を混同", method, row)
		}
		if method == "D164_15" {
			if !row.NativeParentOriginalDesiredKnown || row.NativeParentOriginalDesired == nil || *row.NativeParentOriginalDesired != 32 {
				t.Fatal("日中希望量の既知状態不一致", row)
			}
		} else if row.NativeParentOriginalDesiredKnown || row.NativeParentOriginalDesired != nil || row.NativeParentOriginalDesiredApplicable {
			t.Fatal("夜間へ希望量を推測", row)
		}
		if method == "P164_06" {
			if !row.NativeSmallInitialKnown || row.NativeSmallInitialEligible == nil || *row.NativeSmallInitialEligible {
				t.Fatal("P元追加を小量初回として扱いました", row)
			}
		} else if row.NativeSmallInitialKnown || row.NativeSmallInitialEligible != nil {
			t.Fatal("他手法へP小量資格を適用", row)
		}
	}
}
