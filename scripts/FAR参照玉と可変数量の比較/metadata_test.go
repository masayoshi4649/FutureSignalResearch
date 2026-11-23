// 87派生元: work/87接続試作/metadata_test.go
// 87派生元SHA256: 71873c13bcc7212029a9cbb709b0efbbb764f9d93423d6a2bf0b4f636548d059

package far87

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/masayoshi4649/SessionTradeExecuter/internal/rules"
	"github.com/masayoshi4649/SessionTradeExecuter/internal/strategy"
	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// need87は試作人工の異常を即座に報告します。
//
// 引数: t(*testing.T)、err(error)は人工検査器と呼出結果です。
// 返り値: ありません。不整合なら失敗します。
func need87(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

// session87は市場時計へ結び付けない参照仮想運転専用の場を作ります。
//
// 引数: method(string)は三手法IDです。
// 返り値: strategy.Sessionは固定80が受理する人工時間枠です。
func session87(method string) strategy.Session {
	kind := "Night"
	if method == "D164_15" {
		kind = "Day"
	}
	return strategy.Session{ID: "人工87_" + kind, Kind: kind, Start: 1000, ForceClose: 47000, End: 48000, USOpen: 20000, ExtraAt: 21800}
}

// observation87はSourceの公開入力を満たす、方向予測を含まない正常人工観測です。
//
// 引数: index(int64)、at(float64)は元特徴の原行と時計です。
// 返り値: strategy.Observationは夜間注入時計が一致する人工です。
func observation87(index int64, at float64) strategy.Observation {
	o := strategy.Observation{Reference: "NK225", Index: index, Time: at, Received: at, Last: 10005, Bid: 10000, Ask: 10010, QuoteOK: true, ATR: 100}
	o.Selected.NightAvailable = true
	o.Selected.NightTime = at
	o.Selected.NightIndex = index
	return o
}

// source87はコピーした80driverが持つ元Portfolioを人工内部だけで取得します。
//
// 引数: r(*Reference)は試作参照です。
// 返り値: *strategy.Portfolioは固定Sourceの実体。製品APIへ公開する提案ではありません。
func source87(r *Reference) *strategy.Portfolio { return r.book.(*strategyReferenceBook).Portfolio }

// write87は明示環境変数がある場合にだけ人工snapshotを新規保存します。
//
// 引数: t(*testing.T)、name(string)、value(any)は人工出力です。
// 返り値: ありません。既存出力は上書きしません。
func write87(t *testing.T, name string, value any) {
	t.Helper()
	root := os.Getenv("PROBE87_OUT")
	if root == "" {
		return
	}
	need87(t, os.MkdirAll(root, 0755))
	data, err := json.MarshalIndent(value, "", "  ")
	need87(t, err)
	f, err := os.OpenFile(filepath.Join(root, name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	need87(t, err)
	_, err = f.Write(append(data, '\n'))
	need87(t, err)
	need87(t, f.Close())
}

// TestProbe87OriginalReferenceAPIは元3Portfolioの仮想運転を固定80と逐次全文比較します。
//
// 引数: t(*testing.T)は市場・アプリ・実会計を使わない人工です。
// 返り値: ありません。原driverの通知・現在frameが相違すれば失敗します。
func TestProbe87OriginalReferenceAPI(t *testing.T) {
	report := []map[string]any{}
	for _, method := range []string{"D164_15", "P164_06", "U165_03"} {
		r, err := NewReference(method, session87(method), 100)
		need87(t, err)
		old, err := far80.NewReference(method, session87(method), 100)
		need87(t, err)
		for i := int64(0); i < 8; i++ {
			o := observation87(i, 1100+float64(i))
			a, err := r.Step(o)
			need87(t, err)
			b, err := old.Step(o)
			need87(t, err)
			if !reflect.DeepEqual(a, b) {
				t.Fatal("旧80frameが不同値", method, i, a, b)
			}
			p := source87(r)
			before, err := p.Dump()
			need87(t, err)
			v, err := r.ReadMetadata()
			need87(t, err)
			after, err := p.Dump()
			need87(t, err)
			if !bytes.Equal(before, after) || v.SourceIndex != i || v.At != o.Time {
				t.Fatal("getterがSourceを書換え", method)
			}
		}
		if p := source87(r); p.Selected.Shadow.Config.Cap != 10 || p.Config.Cap != 100 {
			t.Fatal("Source尺度を変更")
		}
		report = append(report, map[string]any{"method": method, "逐次8原行frame同値": true, "限定": "不足指標のため新玉を発生させないSource運転。非0通知順序は派生した固定80人工で別確認。"})
	}
	write87(t, "元Source逐次API.json", report)
}

// TestProbe87DayPublicPolicyは元D164政策の希望32・追加12をそのまま読みJ02を二重適用しません。
//
// 引数: t(*testing.T)は固定Sourceの公開Step/Fillへ元通知を渡す人工です。
// 返り値: ありません。元初回50・希望32・初期32・現在17の区別と追加Kindを検査します。
func TestProbe87DayPublicPolicy(t *testing.T) {
	r, err := NewReference("D164_15", session87("D164_15"), 100)
	need87(t, err)
	p := source87(r)
	d := p.Selected.Day
	runtime, err := rules.NewRuntimeFor("d164_15", nil)
	need87(t, err)
	o := observation87(0, 1100)
	o.Selected.DayBuy = strategy.SelectedDay164Support{Known: true, M: 1, T: 22.0 / 90}
	o.Selected.DayShort = strategy.SelectedDay164Short{Five: strategy.SelectedDay164ShortWindow{Known: true, Move: 10, Speed: 2}, Fifteen: strategy.SelectedDay164ShortWindow{Known: true, Move: 15, Speed: 1}}
	snapshot := strategy.SelectedSnapshot{Cap: 100}
	event := strategy.SelectedSourceEvent{Signal: strategy.Signal{ID: "源初回", Owner: "core", Campaign: 1, Action: "new", Side: 1, Quantity: 5}, Parent: "core/1", SourceID: "源初回", QuantityMicro: 50, ParentRemainingMicro: 50}
	shadowBefore, err := p.Selected.Shadow.Dump()
	need87(t, err)
	intents, err := d.StepSelectedDay(o, []strategy.SelectedSourceEvent{event}, snapshot, runtime, true, true, false)
	need87(t, err)
	if len(intents) != 1 || intents[0].Quantity != 32 || intents[0].Kind != "initial" {
		t.Fatal("元政策32枚を再現できない", intents)
	}
	initial := intents[0]
	lot := strategy.SelectedLot{ID: "参照初回内部", HoldID: "参照初回Hold", EntryID: initial.PolicyID, Parent: initial.Parent, SourceID: initial.SourceID, Owner: initial.Owner, Campaign: initial.Campaign, Kind: initial.Kind, Side: initial.Side, Quantity: 32, InitialQuantity: 32, Entry: 10010, At: 1101}
	snapshot.Lots = []strategy.SelectedLot{lot}
	need87(t, d.FillSelectedDay(strategy.SelectedFillEvent{ExecutionID: "参照初回fill", Intent: initial, LotID: lot.ID, Quantity: 32, Time: 1101}, o, snapshot))
	p.Selected.Lots = append([]strategy.SelectedLot{}, snapshot.Lots...)
	r.refresh()
	first, err := r.ReadMetadata()
	need87(t, err)
	o.Time = 1110
	o.Received = 1110
	o.Index = 1
	o.Selected.DayBuy.T = 78.0 / 90
	event.Signal.ID = "源追加"
	event.Signal.Quantity = 2
	event.SourceID = "源追加"
	event.QuantityMicro = 20
	event.ParentRemainingMicro = 70
	intents, err = d.StepSelectedDay(o, []strategy.SelectedSourceEvent{event}, snapshot, runtime, true, true, false)
	need87(t, err)
	if len(intents) != 1 || intents[0].Quantity != 12 || intents[0].Kind != "source_add" {
		t.Fatal("係数32/50を元追加20へ写す12枚と不一致", intents)
	}
	add := intents[0]
	added := strategy.SelectedLot{ID: "参照追加内部", HoldID: "参照追加Hold", EntryID: add.PolicyID, Parent: add.Parent, SourceID: add.SourceID, Owner: add.Owner, Campaign: add.Campaign, Kind: add.Kind, Side: add.Side, Quantity: 12, InitialQuantity: 12, Entry: 10020, At: 1111}
	snapshot.Lots = append(snapshot.Lots, added)
	need87(t, d.FillSelectedDay(strategy.SelectedFillEvent{ExecutionID: "参照追加fill", Intent: add, LotID: added.ID, Quantity: 12, Time: 1111}, o, snapshot))
	p.Selected.Lots = append([]strategy.SelectedLot{}, snapshot.Lots...)
	p.Selected.Lots[0].Quantity = 17
	r.refresh()
	current, err := r.ReadMetadata()
	need87(t, err)
	if *current.Lots[0].NativeParentInitialMicro != 50 || *current.Lots[0].NativeParentOriginalDesired != 32 || current.Lots[0].ReferenceInitialQuantity != 32 || current.Lots[0].Reference.Quantity != 17 || first.Lots[0].Reference.Quantity != 32 {
		t.Fatal("初期量と現在量を混同", first, current)
	}
	if current.Lots[1].Reference.Kind != "source_add" || ClassifyRealStage(false) != "実側flatで初参加候補" || ClassifyRealStage(true) != "実側保有中の追加候補" {
		t.Fatal("元追加と実初参加の二軸を消した", current)
	}
	*current.Lots[0].NativeParentInitialMicro = 999
	again, err := r.ReadMetadata()
	need87(t, err)
	if *again.Lots[0].NativeParentInitialMicro != 50 || *first.Lots[0].NativeParentInitialMicro != 50 {
		t.Fatal("snapshotポインタをSource又は先行snapshotへ共有")
	}
	shadowAfter, err := p.Selected.Shadow.Dump()
	need87(t, err)
	if !bytes.Equal(shadowBefore, shadowAfter) {
		t.Fatal("人工参照fillで元Shadowを変更")
	}
	write87(t, "日中政策の読取.json", map[string]any{"初回": first, "現在": again, "元追加の実側flat段階": ClassifyRealStage(false), "限定": "元政策Step/Fillは実行。SelectedLot共通帳簿はSourceテストと同様の手製仮想fill。17への減量はmetadata保持の人工で、元返済全ledgerの証明ではない。"})
}

// TestProbe87NightParentQuantityは元親初回量を残量縮小から推測しないことを検査します。
//
// 引数: t(*testing.T)は20/80の元親metadataをJSON注入した境界人工です。
// 返り値: ありません。Sourceに初回量や追尾の新判断を発生させません。
func TestProbe87NightParentQuantity(t *testing.T) {
	for _, method := range []string{"P164_06", "U165_03"} {
		r, err := NewReference(method, session87(method), 100)
		need87(t, err)
		p := source87(r)
		fixture := []byte(`{"Parents":{"core/1":{"Side":1,"InitialSource":"源小量","InitialMicro":20},"core/2":{"Side":1,"InitialSource":"源大初回","InitialMicro":80}}}`)
		need87(t, json.Unmarshal(fixture, p.Selected.Night))
		p.Selected.Lots = []strategy.SelectedLot{
			{ID: "小量内部", HoldID: "小量Hold", Parent: "core/1", SourceID: "源小量", Owner: "core", Kind: "initial", Side: 1, Quantity: 20, InitialQuantity: 20, Entry: 10010, At: 1101},
			{ID: "追加内部", HoldID: "追加Hold", Parent: "core/1", SourceID: "源追加", Owner: "core", Kind: "source_add", Side: 1, Quantity: 12, InitialQuantity: 12, Entry: 10020, At: 1111},
			{ID: "大初回内部", HoldID: "大初回Hold", Parent: "core/2", SourceID: "源大初回", Owner: "core", Kind: "initial", Side: 1, Quantity: 20, InitialQuantity: 80, Entry: 10010, At: 1101},
		}
		r.refresh()
		before, err := p.Dump()
		need87(t, err)
		first, err := r.ReadMetadata()
		need87(t, err)
		after, err := p.Dump()
		need87(t, err)
		if !bytes.Equal(before, after) {
			t.Fatal("getterでSource状態を変更")
		}
		p.Selected.Lots[0].Quantity = 5
		p.Selected.Lots[2].Quantity = 5
		r.refresh()
		last, err := r.ReadMetadata()
		need87(t, err)
		if first.Lots[0].Reference.Quantity != 20 || last.Lots[0].Reference.Quantity != 5 || *last.Lots[0].NativeParentInitialMicro != 20 || *last.Lots[2].NativeParentInitialMicro != 80 {
			t.Fatal("元親量を現在残量へ置換", method, first, last)
		}
		if method == "P164_06" {
			if !*last.Lots[0].NativeSmallInitialEligible || *last.Lots[1].NativeSmallInitialEligible || *last.Lots[2].NativeSmallInitialEligible {
				t.Fatal("親20資格と元追加/元80を混同", last)
			}
			original, err := rules.NewRuntimeFor("p164_06", nil)
			need87(t, err)
			for _, row := range last.Lots {
				expected := original.Bool("selected.p164_06.small_initial", map[string]any{"initial_micro": float64(*row.NativeParentInitialMicro), "is_initial": row.Reference.Kind == "initial" || row.Reference.Kind == "delayed_initial"})
				if expected != *row.NativeSmallInitialEligible {
					t.Fatal("元専用式の分類と不一致")
				}
			}
		} else if last.Lots[0].NativeSmallInitialEligible != nil || last.Lots[0].SmallInitialRuleApplicable {
			t.Fatal("U165にP164小量資格を移植")
		}
		write87(t, fmt.Sprintf("%s_親初回と現在量.json", method), map[string]any{"before": first, "after": last, "限定": "元Portfolioの実型へ当時metadataを注入する読取人工。元P05/D07からこの玉が自然発生した証明ではない。"})
	}
}

// TestProbe87UnknownAndCorruptは親初回未知の非捏造とframe不整合の拒否を検査します。
//
// 引数: t(*testing.T)は欠落親・現在量矛盾の人工です。
// 返り値: ありません。現在20枚を根拠に親初回20を補完すれば失敗します。
func TestProbe87UnknownAndCorrupt(t *testing.T) {
	r, err := NewReference("P164_06", session87("P164_06"), 100)
	need87(t, err)
	p := source87(r)
	p.Selected.Lots = []strategy.SelectedLot{{ID: "内部", HoldID: "Hold", Parent: "不明親", SourceID: "源", Owner: "core", Kind: "initial", Side: 1, Quantity: 20, InitialQuantity: 80, Entry: 10010, At: 1101}}
	r.refresh()
	v, err := r.ReadMetadata()
	need87(t, err)
	if v.Lots[0].NativeParentInitialMicro != nil || v.Lots[0].NativeSmallInitialEligible != nil {
		t.Fatal("未知を小量へ補完")
	}
	p.Selected.Lots[0].Quantity = 21
	if _, err = r.ReadMetadata(); err == nil {
		t.Fatal("staleなframeを受理")
	}
	p.Selected.Lots[0].Quantity = 20
	r.refresh()
	need87(t, json.Unmarshal([]byte(`{"Parents":{"不明親":{"Side":1,"InitialSource":"源","InitialMicro":0}}}`), p.Selected.Night))
	if _, err = r.ReadMetadata(); err == nil {
		t.Fatal("親初回0を小量20以下と捏造")
	}
}
