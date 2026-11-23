package far90

import (
	"math"
	"testing"
)

// pullback90Fixture は固定88の公開順序器からBuilderの当時出典を作ります。
//
// 引数: t(*testing.T)、side(int)、delayed(bool)は検査器と鏡像/確認別足です。
// 返り値: float64/ReferenceLot/ResumeEvent/EventRecordは要求と候補/event/pです。
func pullback90Fixture(t *testing.T, side int, delayed bool) (float64, ReferenceLot, ResumeEvent, EventRecord) {
	t.Helper()
	tracker := NewEventTracker()
	inputs := event90Sequence(delayed)
	records := []EventRecord{}
	for _, in := range inputs {
		if side < 0 {
			in = event90Mirror(in)
		}
		records = append(records, event90Feed(t, tracker, in)...)
	}
	at := inputs[len(inputs)-1].At
	snapshot, err := tracker.Snapshot(at)
	if err != nil {
		t.Fatal(err)
	}
	for _, state := range snapshot.Directions {
		if state.Side == side && state.EventValid && state.Event != nil {
			for _, record := range records {
				if record.ID == state.Event.Pullback.ObservationID {
					return at, ReferenceLot{ID: "当時参照", Side: side, Quantity: 8}, *state.Event, record
				}
			}
		}
	}
	t.Fatal("当時event又はpがない")
	return 0, ReferenceLot{}, ResumeEvent{}, EventRecord{}
}

// TestPullback90Builder は鏡像/別足/古いp/同時失効/非格子と固定値コピーを検査します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。入口や過去市場の数値は探索しません。
func TestPullback90Builder(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delayed := range []bool{false, true} {
			at, ref, event, record := pullback90Fixture(t, side, delayed)
			record.Kind = "期限失効"
			record.Input.Quote.Valid = false
			record.Input.Technical.Close3 += .25
			anchor, err := BuildPullbackAnchor(at+899, ref, event, record)
			if err != nil {
				t.Fatal(err)
			}
			want := record.Input.Technical.Close3 - float64(side)*10
			if !anchor.Known || anchor.Price != want || anchor.Event != event || anchor.PullbackOrdinal != record.Input.Ordinal {
				t.Fatal("固定p価格又は出典差")
			}
			record.Input.Technical.Close3 = -1
			event.Pullback.BarEnd = -1
			if anchor.Price != want || anchor.Event.Pullback.BarEnd <= 0 {
				t.Fatal("元値変更で固定anchorが変わる")
			}
		}
	}
}

// TestPullback90RejectsBrokenEvidence は既知出典の欠落/未来/epoch/値の矛盾を拒否します。
//
// 引数: t(*testing.T)は境界検査器です。
// 返り値: ありません。未知fallbackにして採否を変えません。
func TestPullback90RejectsBrokenEvidence(t *testing.T) {
	at, ref, event, record := pullback90Fixture(t, 1, true)
	mutations := []func(*float64, *ReferenceLot, *ResumeEvent, *EventRecord){
		func(a *float64, _ *ReferenceLot, _ *ResumeEvent, _ *EventRecord) { *a = math.NaN() },
		func(_ *float64, r *ReferenceLot, _ *ResumeEvent, _ *EventRecord) { r.Side = -1 },
		func(_ *float64, _ *ReferenceLot, e *ResumeEvent, _ *EventRecord) { e.Window = "静観" },
		func(_ *float64, _ *ReferenceLot, e *ResumeEvent, _ *EventRecord) { e.Recovery = e.Pullback },
		func(a *float64, _ *ReferenceLot, e *ResumeEvent, _ *EventRecord) { *a = e.Confirmation.BarEnd + 900 },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.ID++ },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.Input.EpochStart++ },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.Input.At++ },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.Input.Technical.Bar3End++ },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) {
			r.Input.Technical.Close3 = math.Inf(1)
		},
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.Input.Quote.Bid = math.NaN() },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.Input.AfterEOF = true },
		func(_ *float64, _ *ReferenceLot, _ *ResumeEvent, r *EventRecord) { r.Input.Quote.Time = r.Input.At + 1 },
	}
	for n, mutate := range mutations {
		a, r, e, p := at, ref, event, record
		mutate(&a, &r, &e, &p)
		if _, err := BuildPullbackAnchor(a, r, e, p); err == nil {
			t.Fatal("出典破損を受理", n)
		}
	}
	if _, err := BuildPullbackAnchor(at, ref, event, record); err != nil {
		t.Fatal(err)
	}
}

// TestPullback90Index は公開時登録の値コピーと重複/順序の拒否を確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。未公開Recordを後から補完しません。
func TestPullback90Index(t *testing.T) {
	r := &replayRuntime{}
	record := EventRecord{ID: 1, Input: EventInput{Ordinal: 2, Technical: TechnicalView{Close3: 100}}}
	if err := r.indexEventRecord(record); err != nil {
		t.Fatal(err)
	}
	record.Input.Technical.Close3 = 200
	if r.eventIndex[1].Input.Technical.Close3 != 100 {
		t.Fatal("公開値が元入力へ追従")
	}
	if r.indexEventRecord(record) == nil {
		t.Fatal("重複を受理")
	}
	record.ID = 2
	if r.indexEventRecord(record) == nil {
		t.Fatal("ordinal後退を受理")
	}
}

// TestPullback90LevelBinding は実指標非0の候補sidecarと採用注文の価格線を結びます。
//
// 引数: t(*testing.T)は完全合成買売の検査器です。
// 返り値: ありません。元record変更が固定線へ伝わらず、欠落がerrorになることを確認します。
func TestPullback90LevelBinding(t *testing.T) {
	for _, side := range []int{1, -1} {
		r, _, _ := runIndicator90(t, side)
		if len(r.result.PullbackLevels) != 1 || len(r.result.EntryBindings) != 4 {
			t.Fatal("候補別1回又は受理4会計の数が不正")
		}
		level := r.result.PullbackLevels[0]
		for _, binding := range r.result.EntryBindings {
			if binding.At != level.At || binding.ReferenceID != level.ReferenceID || binding.RawRank != level.RawRank || binding.SuppliedRank != level.SuppliedRank {
				t.Fatal("外bindingと候補価格線が不整合")
			}
			if binding.BookKey[:2] == "P1" {
				for _, order := range r.result.Books[binding.BookKey].Orders {
					if order.ID == binding.EntryOrderID && (order.StructureAnchor.Price != level.Anchor.Price || order.StructureAnchor.BarEnd != level.Anchor.Event.Pullback.BarEnd || order.StructureAnchor.At != level.At) {
						t.Fatal("要求固定線と実採用注文が不整合")
					}
				}
			}
		}
		grid := GridDecision{}
		for _, item := range r.result.GridDecisions {
			if item.At == level.At {
				grid = item
			}
		}
		supplied, pool, err := FilterEntry("E1", grid.Source, grid.Entry)
		if err != nil {
			t.Fatal(err)
		}
		id := level.Anchor.Event.Pullback.ObservationID
		original := r.eventIndex[id]
		mutated := original
		mutated.Input.Technical.Close3 += 100
		r.eventIndex[id] = mutated
		if level.Anchor.Close != original.Input.Technical.Close3 || level.Anchor.Price == mutated.Input.Technical.Close3-float64(side)*10 {
			t.Fatal("凍結値が元recordの後変更に追従")
		}
		delete(r.eventIndex, id)
		if _, err := r.pullbackCandidates(grid, supplied, pool); err == nil {
			t.Fatal("既知E1のp欠落を通常見送りにした")
		}
	}
}
