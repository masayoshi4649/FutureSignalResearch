// 87派生元: work/87接続試作/metadata.go
// 87派生元SHA256: ac270e17b71fd3f1359a48d78d2738f3fc3b5c9290ea262bb0699c7e9fc43d2d

package far87

import (
	"fmt"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// ReferenceLot/Close/Frameは固定80の値型をそのまま利用します。
type ReferenceLot = far80.ReferenceLot
type ReferenceClose = far80.ReferenceClose
type ReferenceFrame = far80.ReferenceFrame

// ReadLotは元段階・現在量・参照初期量と元親初回量を別に保持する読取専用値です。
// 親量のnilは未取得で、現在量から小量資格や初回を逆算しません。
type ReadLot struct {
	Reference                             ReferenceLot `json:"reference"`
	ReferenceInitialQuantity              int          `json:"reference_initial_quantity"`
	NativeParentInitialMicro              *int         `json:"native_parent_initial_micro"`
	NativeParentOriginalDesired           *int         `json:"native_parent_original_desired"`
	SmallInitialRuleApplicable            bool         `json:"small_initial_rule_applicable"`
	NativeSmallInitialEligible            *bool        `json:"native_small_initial_eligible"`
	NativeParentInitialKnown              bool         `json:"native_parent_initial_known"`
	NativeParentInitialReason             string       `json:"native_parent_initial_reason"`
	NativeParentOriginalDesiredApplicable bool         `json:"native_parent_original_desired_applicable"`
	NativeParentOriginalDesiredKnown      bool         `json:"native_parent_original_desired_known"`
	NativeParentOriginalDesiredReason     string       `json:"native_parent_original_desired_reason"`
	NativeSmallInitialKnown               bool         `json:"native_small_initial_known"`
	NativeSmallInitialReason              string       `json:"native_small_initial_reason"`
}

// ReadSnapshotはSource全原行運転の現在点だけを値複写します。
// RealStageはSource側の状態に保存せず、実側が別に判断する二軸のままです。
type ReadSnapshot struct {
	Method      string           `json:"method"`
	At          float64          `json:"at"`
	SourceIndex int64            `json:"source_index"`
	Started     bool             `json:"started"`
	Lots        []ReadLot        `json:"lots"`
	Closes      []ReferenceClose `json:"closes"`
}

// integerPointerはSourceの可変状態と共有しない数値を作ります。
//
// 引数: value(int)は元状態から読んだ数値です。
// 返り値: *intは独立した値です。
func integerPointer(value int) *int { return &value }

// boolPointerはSourceの可変状態と共有しない真偽値を作ります。
//
// 引数: value(bool)は元状態から読んだ分類です。
// 返り値: *boolは独立した値です。
func boolPointer(value bool) *bool { return &value }

// ReadMetadataは固定80と同じ参照driverが持つ元Portfolioからmetadataだけを値複写します。
//
// 引数: ありません。Sourceの新判断・注文・約定・再数量化を発生させません。
// 返り値: ReadSnapshotは現在玉と出典量、errorは架空book又は所有写像の矛盾です。
func (r *Reference) ReadMetadata() (ReadSnapshot, error) {
	if err := r.check(); err != nil {
		return ReadSnapshot{}, err
	}
	book, ok := r.book.(*strategyReferenceBook)
	if !ok || book.Portfolio.Selected == nil {
		return ReadSnapshot{}, fmt.Errorf("元Portfolioを持つ参照だけが親metadataを公開できます")
	}
	p := book.Portfolio
	frame := r.Frame()
	result := ReadSnapshot{Method: r.method, At: r.lastTime, SourceIndex: r.lastIndex, Started: r.started, Lots: []ReadLot{}, Closes: append([]ReferenceClose{}, frame.Closes...)}
	for _, reference := range frame.Lots {
		index := -1
		for i, lot := range p.Selected.Lots {
			if lot.ID == reference.InternalID && lot.HoldID == reference.ID {
				if index >= 0 {
					return ReadSnapshot{}, fmt.Errorf("同じ参照内部ID/HoldIDが重複")
				}
				index = i
			}
		}
		if index < 0 {
			return ReadSnapshot{}, fmt.Errorf("参照frameに対応する元SelectedLotがありません")
		}
		lot := p.Selected.Lots[index]
		if lot.Quantity != reference.Quantity || lot.InitialQuantity < lot.Quantity || lot.Parent != reference.Parent || lot.Kind != reference.Kind || lot.SourceID != reference.SourceID || lot.Owner != reference.Owner || lot.Side != reference.Side || lot.Entry != reference.Entry || lot.At != reference.At {
			return ReadSnapshot{}, fmt.Errorf("元SelectedLotと参照frameの現在値が不整合")
		}
		row := ReadLot{Reference: reference, ReferenceInitialQuantity: lot.InitialQuantity,
			NativeParentInitialReason: "元親状態未取得", NativeParentOriginalDesiredApplicable: r.method == "NK225_D164_15",
			NativeParentOriginalDesiredReason: "D164の初回希望量は対象外", SmallInitialRuleApplicable: r.method == "NK225_P164_06",
			NativeSmallInitialReason: "P164の小量初回資格は対象外"}
		if row.NativeParentOriginalDesiredApplicable {
			row.NativeParentOriginalDesiredReason = "元親状態未取得"
		}
		if row.SmallInitialRuleApplicable {
			row.NativeSmallInitialReason = "元親初回量未取得"
		}
		if p.Selected.Day != nil {
			if parent := p.Selected.Day.Parents[lot.Parent]; parent != nil && !parent.InitialSeen {
				row.NativeParentInitialReason, row.NativeParentOriginalDesiredReason = "元親初回未観測", "元親初回未観測"
			}
			if parent := p.Selected.Day.Parents[lot.Parent]; parent != nil && parent.InitialSeen {
				if parent.Side != lot.Side || parent.NativeInitial <= 0 || parent.OriginalDesired <= 0 {
					return ReadSnapshot{}, fmt.Errorf("日中の元親初回量・方向が不整合")
				}
				row.NativeParentInitialMicro = integerPointer(parent.NativeInitial)
				row.NativeParentOriginalDesired = integerPointer(parent.OriginalDesired)
				row.NativeParentOriginalDesiredKnown, row.NativeParentOriginalDesiredReason = true, "元親の初回希望量を読取"
			}
		}
		if p.Selected.Night != nil {
			if parent := p.Selected.Night.Parents[lot.Parent]; parent != nil {
				if parent.Side != lot.Side || parent.InitialMicro <= 0 {
					return ReadSnapshot{}, fmt.Errorf("夜間の元親初回量・方向が不整合")
				}
				row.NativeParentInitialMicro = integerPointer(parent.InitialMicro)
			}
		}
		if row.NativeParentInitialMicro != nil {
			row.NativeParentInitialKnown, row.NativeParentInitialReason = true, "元親の初回通知量を読取"
		}
		if row.SmallInitialRuleApplicable && row.NativeParentInitialMicro != nil {
			initial := lot.Kind == "initial" || lot.Kind == "delayed_initial"
			row.NativeSmallInitialEligible = boolPointer(*row.NativeParentInitialMicro <= 20 && initial)
			row.NativeSmallInitialKnown = true
			row.NativeSmallInitialReason = "元親初回量と選定参照Kindの元規則を適用"
		}
		result.Lots = append(result.Lots, row)
	}
	return result, nil
}

// ClassifyRealStageは元Kindを上書きせず、実側保有の有無から参加段階だけを返します。
//
// 引数: owns(bool)は別の実会計に現在所有があるかです。
// 返り値: stringは実側初参加又は保有中追加候補。注文や採否は生成しません。
func ClassifyRealStage(owns bool) string {
	if owns {
		return "実側保有中の追加候補"
	}
	return "実側flatで初参加候補"
}
