package actorport97

import (
	"fmt"
	"strings"
	"testing"
)

// TestIndexStageBoundaries は市場を読まず完全集合と指紋の境界を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。first2/full54と重複/欠落/対象外/壊れた指紋を区別します。
func TestIndexStageBoundaries(t *testing.T) {
	sha := strings.Repeat("a", 64)
	first := TapeIndex{Version: 1, Stage: "first2", Entries: []TapeEntry{{Session: "2026-09-21_Day", Path: "day.json.gz", SHA256: sha}, {Session: "2026-09-21_Night", Path: "night.json.gz", SHA256: sha}}}
	if err := ValidateIndex(first, "first2", nil); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*TapeIndex){
		"欠落":    func(x *TapeIndex) { x.Entries = x.Entries[:1] },
		"重複":    func(x *TapeIndex) { x.Entries[1].Session = x.Entries[0].Session },
		"対象外":   func(x *TapeIndex) { x.Entries[1].Session = "未読場" },
		"指紋長":   func(x *TapeIndex) { x.Entries[0].SHA256 = "a" },
		"非16進":  func(x *TapeIndex) { x.Entries[0].SHA256 = strings.Repeat("z", 64) },
		"欠パス":   func(x *TapeIndex) { x.Entries[0].Path = "" },
		"stage": func(x *TapeIndex) { x.Stage = "full54" },
		"版":     func(x *TapeIndex) { x.Version = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			x := first
			x.Entries = append([]TapeEntry{}, first.Entries...)
			mutate(&x)
			if ValidateIndex(x, "first2", nil) == nil {
				t.Fatal("破損集合を採用")
			}
		})
	}
	allowed := map[string]string{}
	full := TapeIndex{Version: 1, Stage: "full54", Entries: []TapeEntry{}}
	for i := 0; i < 54; i++ {
		id := fmt.Sprintf("人工許可%02d", i)
		allowed[id] = sha
		full.Entries = append(full.Entries, TapeEntry{Session: id, Path: id + ".json.gz", SHA256: sha})
	}
	if err := ValidateIndex(full, "full54", allowed); err != nil {
		t.Fatal(err)
	}
	full.Entries = full.Entries[:53]
	if ValidateIndex(full, "full54", allowed) == nil {
		t.Fatal("全54の欠落を採用")
	}
	if RunBatch(BatchArguments{}) == nil {
		t.Fatal("必須CLI境界の不足を採用")
	}
}
