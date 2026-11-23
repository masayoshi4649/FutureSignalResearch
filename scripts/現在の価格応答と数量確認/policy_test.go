package far84

import (
	"encoding/json"
	"reflect"
	"testing"
)

// TestCandidateCompleteValue は全入口の候補全値と旧B1識別子を確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。候補は新規ID・Source・Owner・時刻・枚数を含めて同値を要求します。
func TestCandidateCompleteValue(t *testing.T) {
	for _, x := range []input{fixture(), mirror(fixture())} {
		base := oldDecision(x)
		before := copyBase(base)
		expected := base.Candidate("人工場", "D164_15", 100)
		if len(expected.Lots) != 1 {
			t.Fatal("非0候補の前提がありません")
		}
		for _, policy := range []string{"A0", "C0", "C1"} {
			decision, err := Refine(base, policy)
			if err != nil {
				t.Fatal(err)
			}
			actual := decision.Candidate("人工場", "D164_15", 100)
			if !reflect.DeepEqual(actual, expected) {
				t.Fatalf("候補全値を変更しました:%s %+v/%+v", policy, actual, expected)
			}
			if !reflect.DeepEqual(base, before) {
				t.Fatal("候補生成で元B1を変更しました")
			}
		}
	}
}

// TestPolicySavedSchema は旧全snapshotが保存policyへ重複しないことを確認します。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。保存fieldと追加チェック順序を厳密に確認します。
func TestPolicySavedSchema(t *testing.T) {
	base := oldDecision(fixture())
	for _, policy := range []string{"A0", "C0", "C1"} {
		decision, err := Refine(base, policy)
		if err != nil {
			t.Fatal(err)
		}
		snapshot := policySnapshot(decision, true)
		raw, err := json.Marshal(snapshot)
		if err != nil {
			t.Fatal(err)
		}
		var saved map[string]json.RawMessage
		if err = json.Unmarshal(raw, &saved); err != nil {
			t.Fatal(err)
		}
		want := []string{"allowed", "side", "role", "reason", "required_unknown", "directions", "candidate_accepted"}
		if len(saved) != len(want) {
			t.Fatal("保存policyへ旧全snapshotを重複しました", string(raw))
		}
		for _, key := range want {
			if _, ok := saved[key]; !ok {
				t.Fatal("保存policyの必須fieldが欠落", key)
			}
		}
		direction := snapshot.Directions[0]
		ids := []string{}
		if policy != "A0" {
			ids = append(ids, "現在価格帯", "反対圧力")
		}
		if policy == "C1" {
			ids = append(ids, "同価格数量支持")
		}
		if len(direction.AddedChecks) != len(ids) {
			t.Fatal("追加チェックの数が違います", policy)
		}
		for i, check := range direction.AddedChecks {
			if check.ID != ids[i] || check.Group != "追加必須" || !check.Known || !check.Passed {
				t.Fatal("追加チェックの順序又は値が違います", policy, check)
			}
		}
	}
}

// TestReplayPolicyRejection は純入口の未知/不成立を金融の待機理由へ混ぜません。
//
// 引数: t(*testing.T)は人工検査器です。
// 返り値: ありません。C0/C1の拒否・許可差とA0の同値対照を確認します。
func TestReplayPolicyRejection(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, unknown := range []bool{false, true} {
			runtime, at := input84Runtime(t, side)
			if unknown {
				runtime.current.Night.Known = false
			} else if side > 0 {
				runtime.current.Night.Buy.QuantitySupport = false
			} else {
				runtime.current.Night.Sell.QuantitySupport = false
			}
			if err := runtime.advanceTimer(at, false); err != nil {
				t.Fatal(err)
			}
			grid := runtime.result.GridDecisions[0]
			for _, policy := range []string{"A0", "C0", "C1"} {
				want := policy == "A0" || (policy == "C0" && !unknown)
				if grid.Policies[policy].CandidateAccepted != want {
					t.Fatal("純候補供給の包含差", side, unknown, policy)
				}
				if policy != "A0" && grid.Policies[policy].RequiredUnknown != unknown {
					t.Fatal("未知と既知不成立を混同", side, unknown, policy)
				}
				for delay := 0; delay <= 1; delay++ {
					book := runtime.books[bookKey(policy+"G1", delay)].Result()
					if book.Mode != "S0G1" || (len(book.Orders) > 0) != want {
						t.Fatal("金融の内部政策又は注文包含差", policy, delay)
					}
					if !want && (len(book.Decisions) != 1 || book.Decisions[0].Action != "待ち") {
						t.Fatal("空候補の金融待機を変更しました", policy, book.Decisions)
					}
				}
			}
		}
	}
}
