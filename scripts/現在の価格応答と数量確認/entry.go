// 84派生元: work/84入口試作/entry.go
// 84派生元SHA256: 97436939655dfe72470f5ecccea7c70d7dbafd9b69b70163cf03281baeae96db

// Package far84 は固定82B1と現在価格応答・数量支持の追加入口を比較します。
package far84

import (
	"fmt"
	"math"
	"strings"

	far81 "github.com/masayoshi4649/SessionTradeExecuter/research81"
	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// Direction は旧方向を保存し、追加条件と最終採否を分けます。
type Direction struct {
	Base            far82.EntryDirection `json:"base"`
	Allowed         bool                 `json:"allowed"`
	RequiredUnknown bool                 `json:"required_unknown"`
	Role            string               `json:"role"`
	Reason          string               `json:"reason"`
	Added           []far81.EntryCheck   `json:"added"`
}

// Decision は旧B1を保持した純入口の結果で、注文・会計は含みません。
type Decision struct {
	Policy          string              `json:"policy"`
	Base            far82.EntryDecision `json:"base"`
	Allowed         bool                `json:"allowed"`
	Side            int                 `json:"side"`
	Role            string              `json:"role"`
	Reason          string              `json:"reason"`
	RequiredUnknown bool                `json:"required_unknown"`
	Directions      []Direction         `json:"directions"`
}

type checkKey struct{ group, id string }

var beforeOptional = []checkKey{
	{"共通", "政策"}, {"共通", "参照市場"}, {"共通", "自己現在"},
	{"共通", "確定3分時計"}, {"共通", "直前3分結合"}, {"共通", "現在の勢い"},
	{"共通", "終値回復"}, {"共通", "取得位置"}, {"共通", "同時スパイク"},
	{"補助状態", "5秒補助"}, {"補助状態", "15秒補助"}, {"補助状態", "OFI補助"},
	{"補助集約", "既知反対なし"}, {"補助状態", "既知失速"},
}

var afterOptional = []checkKey{
	{"順行枝", "複数尺度方向"}, {"転換初動枝", "RSI増分"},
	{"転換初動枝", "直前平均からの回復"}, {"転換初動枝", "現在価格帯"},
	{"転換初動枝", "同価格数量支持"}, {"転換初動枝", "反対圧力"},
}

// copyValue は補助値のポインターを元判定と分離します。
//
// 引数: value(far82.AuxiliaryValue)は方向別補助値です。
// 返り値: far82.AuxiliaryValueは独立した数値ポインターを持つ複写です。
func copyValue(value far82.AuxiliaryValue) far82.AuxiliaryValue {
	if value.Value != nil {
		number := *value.Value
		value.Value = &number
	}
	return value
}

// copyBase は入力のmap・slice・ポインターを返却値と分離します。
//
// 引数: base(far82.EntryDecision)は既存のB1判定です。
// 返り値: far82.EntryDecisionは現在の公開schemaに対応する独立複写です。
func copyBase(base far82.EntryDecision) far82.EntryDecision {
	base.Directions = append([]far82.EntryDirection(nil), base.Directions...)
	for i := range base.Directions {
		d := &base.Directions[i]
		d.Checks = append([]far81.EntryCheck(nil), d.Checks...)
		if d.PlacementATR != nil {
			number := *d.PlacementATR
			d.PlacementATR = &number
		}
		d.Auxiliary.Five = copyValue(d.Auxiliary.Five)
		d.Auxiliary.Fifteen = copyValue(d.Auxiliary.Fifteen)
		d.Auxiliary.OFI = copyValue(d.Auxiliary.OFI)
	}
	for _, support := range []*far81.CurrentSupport{&base.Evidence.Buy, &base.Evidence.Sell} {
		if support.Windows != nil {
			windows := map[string]far81.CurrentSupportWindow{}
			for name, value := range support.Windows {
				windows[name] = value
			}
			support.Windows = windows
		}
	}
	return base
}

// checkAuxiliary は補助の未知・符号分類と保存チェックの結合を検査します。
//
// 引数: value(far82.AuxiliaryValue)、check(far81.EntryCheck)は同じ補助の二表現です。
// 返り値: errorは不整合又は既知非有限値、正常ならnilです。
func checkAuxiliary(value far82.AuxiliaryValue, check far81.EntryCheck) error {
	state := "未知"
	if value.Known {
		if value.Value == nil || math.IsNaN(*value.Value) || math.IsInf(*value.Value, 0) {
			return fmt.Errorf("既知補助に有限値がありません:%s", check.ID)
		}
		state = "中立"
		if *value.Value > 0 {
			state = "支持"
		} else if *value.Value < 0 {
			state = "反対"
		}
	} else if value.Value != nil {
		return fmt.Errorf("未知補助に値があります:%s", check.ID)
	}
	if value.State != state || check.Known != value.Known || check.Passed != (value.Known && state != "反対") {
		return fmt.Errorf("補助と保存チェックが不整合です:%s", check.ID)
	}
	return nil
}

// readChecks は旧B1のチェックschemaと既存の論理結合を厳密に検査します。
//
// 引数: direction(far82.EntryDirection)は旧方向の保存判定です。
// 返り値: map[string]far81.EntryCheckはID別の既存チェック、errorは欠落・重複・順序・論理不整合です。
func readChecks(direction far82.EntryDirection) (map[string]far81.EntryCheck, error) {
	want := append([]checkKey(nil), beforeOptional...)
	if direction.Auxiliary.SlowdownKnown && direction.Auxiliary.Slowdown {
		want = append(want, checkKey{"失速時確認", "追加支持"})
	}
	want = append(want, afterOptional...)
	if len(direction.Checks) != len(want) {
		return nil, fmt.Errorf("旧チェック数がschemaと異なります:%d/%d", len(direction.Checks), len(want))
	}
	checks := map[string]far81.EntryCheck{}
	for i, check := range direction.Checks {
		if check.Group != want[i].group || check.ID != want[i].id {
			return nil, fmt.Errorf("旧チェックのgroup/ID/順序が異なります:%d:%s/%s", i, check.Group, check.ID)
		}
		if _, duplicate := checks[check.ID]; duplicate {
			return nil, fmt.Errorf("旧チェックIDが重複しています:%s", check.ID)
		}
		if !check.Known && check.Passed {
			return nil, fmt.Errorf("未知チェックが成立しています:%s", check.ID)
		}
		checks[check.ID] = check
	}

	// ----------------------------------------
	// 算術による帯再計算は行わず、既存チェックと公開補助の結合だけを確認します。
	a := direction.Auxiliary
	for _, item := range []struct {
		value far82.AuxiliaryValue
		id    string
	}{{a.Five, "5秒補助"}, {a.Fifteen, "15秒補助"}, {a.OFI, "OFI補助"}} {
		if err := checkAuxiliary(item.value, checks[item.id]); err != nil {
			return nil, err
		}
	}
	slowKnown := a.Five.Known && a.Fifteen.Known
	slow := slowKnown && *a.Fifteen.Value > 0 && *a.Five.Value <= .5*(*a.Fifteen.Value)
	if a.SlowdownKnown != slowKnown || a.Slowdown != slow || checks["既知失速"].Known != slowKnown || checks["既知失速"].Passed != slow {
		return nil, fmt.Errorf("失速補助と保存チェックが不整合です")
	}
	opposition := a.Five.State == "反対" || a.Fifteen.State == "反対" || a.OFI.State == "反対"
	if !checks["既知反対なし"].Known || checks["既知反対なし"].Passed != !opposition {
		return nil, fmt.Errorf("既知反対の集約が不整合です")
	}
	band, quantity, pressure := checks["現在価格帯"], checks["同価格数量支持"], checks["反対圧力"]
	if a.StructureKnown != band.Known || band.Known != quantity.Known || band.Known != pressure.Known || a.StructureSupport != (band.Passed && quantity.Passed) || a.PressureClear != pressure.Passed {
		return nil, fmt.Errorf("構造チェックと公開補助が不整合です")
	}
	if slow {
		positive := a.OFI.State == "支持" || a.StructureSupport
		confirmKnown := positive || (a.OFI.Known && a.StructureKnown)
		confirm := checks["追加支持"]
		if confirm.Known != confirmKnown || confirm.Passed != positive {
			return nil, fmt.Errorf("失速時追加支持が不整合です")
		}
	}

	// ----------------------------------------
	// 旧方向の採否を保存された真偽値から照合し、破損したAllowedを信頼しません。
	valid, unknown := true, false
	for _, check := range direction.Checks[:9] {
		valid = valid && check.Passed
		unknown = unknown || !check.Known
	}
	valid = valid && checks["既知反対なし"].Passed
	if slow {
		valid = valid && checks["追加支持"].Passed
		unknown = unknown || !checks["追加支持"].Known
	}
	trend := checks["複数尺度方向"].Passed
	initial := checks["RSI増分"].Passed && checks["直前平均からの回復"].Passed && band.Passed && quantity.Passed && pressure.Passed
	allowed := valid && (trend || initial)
	initialUnknown := !checks["RSI増分"].Known || !checks["直前平均からの回復"].Known || (checks["RSI増分"].Passed && checks["直前平均からの回復"].Passed && !a.StructureKnown)
	if !trend && !initial && (!checks["複数尺度方向"].Known || initialUnknown) {
		unknown = true
	}
	role := "待機"
	if allowed {
		unknown, role = false, "順行"
		if !trend {
			role = "転換初動"
		}
	} else if unknown {
		role = "判定不能"
	}
	if direction.Allowed != allowed || direction.RequiredUnknown != unknown || direction.Role != role {
		return nil, fmt.Errorf("旧方向の採否/未知/役割がチェックと不整合です")
	}
	return checks, nil
}

// resolve は旧resolveEntryと同じ集約規則を純方向へ適用します。
//
// 引数: directions([]Direction)は追加条件を評価した二方向です。
// 返り値: allowed(bool)、side(int)、role/reason(string)、unknown(bool)は旧規則による集約です。
func resolve(directions []Direction) (allowed bool, side int, role, reason string, unknown bool) {
	role, reason = "待機", "現在の新規根拠なし"
	count := 0
	for _, direction := range directions {
		if direction.Allowed {
			count++
			side, role, reason = direction.Base.Side, direction.Role, direction.Reason
		}
		unknown = unknown || direction.RequiredUnknown
	}
	if count == 1 {
		allowed, unknown = true, false
	} else if count > 1 {
		side, role, reason, unknown = 0, "競合待機", "両方向の現在根拠が競合", false
	} else {
		if unknown {
			role = "判定不能"
		}
		if len(directions) == 2 {
			reason = "買:" + directions[0].Reason + "／売:" + directions[1].Reason
		}
	}
	return
}

// Refine は旧B1判定を検査し、A0の同値対照又はC0/C1の追加ANDを適用します。
//
// 引数: base(far82.EntryDecision)は旧B1の公開判定、policy(string)はA0/C0/C1です。
// 返り値: Decisionは注文を含まない独立した純判定、errorはschema又は旧論理の不整合です。
func Refine(base far82.EntryDecision, policy string) (Decision, error) {
	if OldSchemaSHA256() != acceptedSchemaSHA256 {
		return Decision{}, fmt.Errorf("旧公開保存型のschemaが停止版と異なります")
	}
	if policy != "A0" && policy != "C0" && policy != "C1" {
		return Decision{}, fmt.Errorf("未知の84入口です:%s", policy)
	}
	if base.Policy != "B1" || len(base.Directions) != 2 || base.Directions[0].Side != 1 || base.Directions[1].Side != -1 {
		return Decision{}, fmt.Errorf("旧B1又は買売二方向のschemaが異なります")
	}
	base = copyBase(base)
	d := Decision{Policy: policy, Base: base, Directions: []Direction{}}
	oldDirections := []Direction{}
	for _, old := range base.Directions {
		checks, err := readChecks(old)
		if err != nil {
			return Decision{}, fmt.Errorf("方向%d:%w", old.Side, err)
		}
		oldDirections = append(oldDirections, Direction{Base: old, Allowed: old.Allowed, RequiredUnknown: old.RequiredUnknown, Role: old.Role, Reason: old.Reason, Added: []far81.EntryCheck{}})
		current := Direction{Base: old, Allowed: old.Allowed, RequiredUnknown: old.RequiredUnknown, Role: old.Role, Added: []far81.EntryCheck{}}
		reasons := []string{}
		if !old.Allowed {
			reasons = append(reasons, "旧B1不成立:"+old.Reason)
		}
		ids := []string{}
		if policy != "A0" {
			ids = append(ids, "現在価格帯", "反対圧力")
		}
		if policy == "C1" {
			ids = append(ids, "同価格数量支持")
		}
		for _, id := range ids {
			check := checks[id]
			check.Group = "追加必須"
			current.Added = append(current.Added, check)
			current.Allowed = current.Allowed && check.Passed
			current.RequiredUnknown = current.RequiredUnknown || !check.Known
			if !check.Known {
				reasons = append(reasons, id+"未知")
			} else if !check.Passed {
				reasons = append(reasons, id+"不成立")
			}
		}
		current.Role = "待機"
		if current.Allowed {
			current.Role, current.RequiredUnknown = old.Role, false
			current.Reason = old.Role + "の現在価格応答成立"
		} else {
			if current.RequiredUnknown {
				current.Role = "判定不能"
			}
			current.Reason = strings.Join(reasons, "／")
		}
		d.Directions = append(d.Directions, current)
	}

	// ----------------------------------------
	// 旧集約の破損を拒否し、旧競合から片側を新規許可へ復活させません。
	allowed, side, role, reason, unknown := resolve(oldDirections)
	if base.Allowed != allowed || base.Side != side || base.Role != role || base.Reason != reason || base.RequiredUnknown != unknown {
		return Decision{}, fmt.Errorf("旧B1の最終集約が二方向と不整合です")
	}
	if policy == "A0" {
		d.Directions = oldDirections
		d.Allowed, d.Side, d.Role, d.Reason, d.RequiredUnknown = base.Allowed, base.Side, base.Role, base.Reason, base.RequiredUnknown
		return d, nil
	}
	d.Allowed, d.Side, d.Role, d.Reason, d.RequiredUnknown = resolve(d.Directions)
	if base.Role == "競合待機" {
		d.Allowed, d.Side, d.Role, d.Reason, d.RequiredUnknown = false, 0, "競合待機", "旧B1の両方向競合を維持", false
	}
	return d, nil
}

// Decide は既存82B1を一度評価し、保存チェックをA0/C0/C1へ渡します。
//
// 引数: at(float64)、q(far82.Quote)、chart(far82.ChartView)、evidence(far82.CurrentEvidence)、policy(string)です。
// 返り値: Decisionは純入口、errorは追加wrapperのschema又は論理不整合です。
func Decide(at float64, q far82.Quote, chart far82.ChartView, evidence far82.CurrentEvidence, policy string) (Decision, error) {
	return Refine(far82.Decide(at, q, chart, evidence, "B1"), policy)
}

// Candidate は旧B1の集約値だけを更新し、元ID形式の候補を生成します。
//
// 引数: sessionID/window(string)は場と窓、quantity(int)は研究枚数です。
// 返り値: ReferenceFrameは旧B1の識別子を保つ最大一候補又は空値です。
func (d Decision) Candidate(sessionID, window string, quantity int) ReferenceFrame {
	base := copyBase(d.Base)
	base.Allowed, base.Side, base.Role, base.Reason, base.RequiredUnknown = d.Allowed, d.Side, d.Role, d.Reason, d.RequiredUnknown
	return base.Candidate(sessionID, window, quantity)
}
