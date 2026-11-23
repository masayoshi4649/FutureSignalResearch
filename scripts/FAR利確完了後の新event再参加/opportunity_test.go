package far91

import (
	"math"
	"testing"
)

// opportunity91Fixture は固定公開APIから現在E1と全point出典を作ります。
//
// 引数: t(*testing.T)、side(int)、delayed(bool)は検査器と鏡像/別足指定です。
// 返り値: float64/Quote/ReferenceLot/EntryDirectionEvaluation/map[int64]EventRecordはBuilderの当時入力です。
func opportunity91Fixture(t *testing.T, side int, delayed bool) (float64, Quote, ReferenceLot, EntryDirectionEvaluation, map[int64]EventRecord) {
	t.Helper()
	inputs := event91Sequence(delayed)
	tracker := NewEventTracker()
	records := map[int64]EventRecord{}
	var last, previous EventInput
	for _, in := range inputs {
		if side < 0 {
			in = event91Mirror(in)
		}
		for _, record := range event91Feed(t, tracker, in) {
			records[record.ID] = record
		}
		previous, last = last, in
	}
	at := last.At
	state, err := tracker.Snapshot(at)
	if err != nil {
		t.Fatal(err)
	}
	chart := ChartView{Technical: last.Technical, PreviousClose3: previous.Technical.Close3, PreviousEMA8_3: previous.Technical.EMA8_3, PreviousBar3End: previous.Technical.Bar3End, Previous3Known: true}
	evaluation, err := EvaluateEntry(at, last.Quote, chart, state)
	if err != nil {
		t.Fatal(err)
	}
	for _, direction := range evaluation.Directions {
		if direction.Side == side && direction.E1Allowed {
			return at, last.Quote, ReferenceLot{ID: "当時参照", Side: side, Quantity: 8}, direction, records
		}
	}
	t.Fatal("現在E1が成立しない")
	return 0, Quote{}, ReferenceLot{}, EntryDirectionEvaluation{}, nil
}

// TestOpportunity91Builder は鏡像/別足/期限境界と公開値の固定を検査します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。履歴利益や金融の未来値は渡しません。
func TestOpportunity91Builder(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, delayed := range []bool{false, true} {
			at, q, reference, direction, records := opportunity91Fixture(t, side, delayed)
			p := records[direction.Event.Pullback.ObservationID]
			p.Kind = "期限失効"
			p.Input.Quote.Valid = false
			records[p.ID] = p
			opportunity, err := BuildEntryOpportunity("人工場", at, q, reference, direction, records)
			if err != nil {
				t.Fatal(err)
			}
			want := 3
			if delayed {
				want = 4
			}
			if len(opportunity.Publications) != want || opportunity.OpportunityID != (OpportunityKey{"人工場", reference.ID, direction.Event.ID}) {
				t.Fatal("unique point又は機会tupleが不整合")
			}
			before := opportunity.Publications[1]
			p.Input.Quote.Line++
			records[p.ID] = p
			direction.Event.Pullback.BarEnd++
			if opportunity.Publications[1] != before || opportunity.Event.Pullback.BarEnd == direction.Event.Pullback.BarEnd {
				t.Fatal("固定機会が元入力に追従")
			}
		}
	}
}

// TestOpportunity91RejectsBrokenEvidence は既知E1の矛盾を通常見送りへ変えません。
//
// 引数: t(*testing.T)は純API境界の検査器です。
// 返り値: ありません。欠落/未来/別epoch/locked気配を拒否します。
func TestOpportunity91RejectsBrokenEvidence(t *testing.T) {
	mutations := []func(*float64, *Quote, *EntryDirectionEvaluation, map[int64]EventRecord){
		func(a *float64, _ *Quote, _ *EntryDirectionEvaluation, _ map[int64]EventRecord) { *a = math.NaN() },
		func(_ *float64, q *Quote, _ *EntryDirectionEvaluation, _ map[int64]EventRecord) { q.Ask = q.Bid },
		func(_ *float64, q *Quote, _ *EntryDirectionEvaluation, _ map[int64]EventRecord) { q.Valid = false },
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, _ map[int64]EventRecord) { d.Event.Side *= -1 },
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, _ map[int64]EventRecord) {
			d.Event.Recovery = d.Event.Pullback
		},
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, records map[int64]EventRecord) {
			delete(records, d.Event.Pullback.ObservationID)
		},
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, records map[int64]EventRecord) {
			p := records[d.Event.Pullback.ObservationID]
			p.Input.At++
			records[p.ID] = p
		},
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, records map[int64]EventRecord) {
			p := records[d.Event.Pullback.ObservationID]
			p.Input.EpochStart++
			records[p.ID] = p
		},
		func(_ *float64, q *Quote, d *EntryDirectionEvaluation, records map[int64]EventRecord) {
			p := records[d.Event.Pullback.ObservationID]
			p.Input.Quote.Index = q.Index + 1
			records[p.ID] = p
		},
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, records map[int64]EventRecord) {
			p := records[d.Event.Pullback.ObservationID]
			p.Input.Quote.Bid = math.NaN()
			records[p.ID] = p
		},
		func(_ *float64, _ *Quote, d *EntryDirectionEvaluation, records map[int64]EventRecord) {
			p := records[d.Event.Pullback.ObservationID]
			p.Input.AfterEOF = true
			records[p.ID] = p
		},
	}
	for n, mutate := range mutations {
		at, q, reference, direction, records := opportunity91Fixture(t, 1, true)
		mutate(&at, &q, &direction, records)
		if _, err := BuildEntryOpportunity("人工場", at, q, reference, direction, records); err == nil {
			t.Fatal("破損した既知E1を受理", n)
		}
	}
}

// TestOpportunity91Index は場内の公開時登録と値型保持を確認します。
//
// 引数: t(*testing.T)は検査器です。
// 返り値: ありません。欠番/重複/未来ordinalを後から補完しません。
func TestOpportunity91Index(t *testing.T) {
	r := &replayRuntime{}
	record := EventRecord{ID: 1, Input: EventInput{Ordinal: 2, Technical: TechnicalView{Close3: 100}}}
	if err := r.indexEventRecord(record); err != nil {
		t.Fatal(err)
	}
	record.Input.Technical.Close3 = 200
	if r.eventIndex[1].Input.Technical.Close3 != 100 || r.indexEventRecord(record) == nil {
		t.Fatal("値型保持又は重複拒否が不成立")
	}
	record.ID = 2
	if r.indexEventRecord(record) == nil {
		t.Fatal("ordinal後退を受理")
	}
}
