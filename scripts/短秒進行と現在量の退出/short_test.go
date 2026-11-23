package minishortexit

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	far82 "github.com/masayoshi4649/SessionTradeExecuter/research82"
)

// fixture は停止済み公開人工のInputだけを再用し、短秒値を手製で追加します。
//
// 引数: t(*testing.T)、side(int)、kind(string)は鏡像と場の選択です。
// 返り値: TechnicalGateInputはSource/指標を運転しない手製の現在根拠です。
func fixture(t *testing.T, side int, kind string) TechnicalGateInput {
	t.Helper()
	body, err := os.ReadFile(filepath.Join("..", "保有の3分複合失効の純式", "testdata", "公開型.json"))
	if err != nil {
		t.Fatal(err)
	}
	h := sha256.Sum256(body)
	if hex.EncodeToString(h[:]) != "3e644241ba177976172f461720748f7cfccb73f4ccd9f5d698de48830a6787f6" {
		t.Fatal("元公開型指紋差")
	}
	var stored struct {
		Cases []struct {
			Name  string             `json:"name"`
			Input TechnicalGateInput `json:"input"`
			Side  int                `json:"side"`
		} `json:"cases"`
	}
	if err = json.Unmarshal(body, &stored); err != nil {
		t.Fatal(err)
	}
	for _, row := range stored.Cases {
		if row.Side != side || row.Input.Kind != kind || !strings.HasSuffix(row.Name, "三反対") {
			continue
		}
		in := row.Input
		c := &in.Current
		c.Short = far82.CurrentShort{Time: c.Time, Mid: c.Bid + (c.Ask-c.Bid)/2,
			Five:    far82.CurrentShortWindow{Known: true, Move: -10 * float64(side), Speed: -2 * float64(side), Elapsed: 5, Endpoint: c.Time - 5, Reason: "手製の既知"},
			Fifteen: far82.CurrentShortWindow{Known: true, Move: -15 * float64(side), Speed: -float64(side), Elapsed: 15, Endpoint: c.Time - 15, Reason: "手製の既知"}}
		return in
	}
	t.Fatal("元人工に対象なし")
	return TechnicalGateInput{}
}

// assess は正常入力の不変性を検査し、純出力を返します。
//
// 引数: t(*testing.T)、in(TechnicalGateInput)、side(int)、policy(string)です。
// 返り値: Assessmentはerrorがない公開値です。
func assess(t *testing.T, in TechnicalGateInput, side int, policy string) Assessment {
	t.Helper()
	before, _ := json.Marshal(in)
	got, err := AssessShortExit(in, side, policy)
	after, _ := json.Marshal(in)
	if err != nil || string(before) != string(after) {
		t.Fatal("正常入力の変更/error", err)
	}
	return got
}

// TestMirror は買売/日夜/2政策と、確定足の反対を必要としない役割を検査します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestMirror(t *testing.T) {
	for _, kind := range []string{"Day", "Night"} {
		for _, side := range []int{1, -1} {
			for _, policy := range []string{"S5Q", "S515Q"} {
				t.Run(fmt.Sprintf("%s/%d/%s", kind, side, policy), func(t *testing.T) {
					in := fixture(t, side, kind)
					v := &in.Chart.Chart.Technical
					v.Close3 = v.EMA8_3 + 5*float64(side)
					v.Histogram3 = v.PreviousHistogram3 + float64(side)
					got := assess(t, in, side, policy)
					if !got.Decision.Known || !got.Decision.Allowed || got.Decision.Policy != policy || *got.Evidence.Five.SignedSpeed != -2 || *got.Evidence.SignedQuantity != -5 {
						t.Fatal(got)
					}
					if len(got.Checks) != 3 && policy == "S5Q" || len(got.Checks) != 4 && policy == "S515Q" {
						t.Fatal("必要集合が不正")
					}
				})
			}
		}
	}
}

// TestPoliciesAndTruth は15秒の役割・等号・未知と既知否定優先を確認します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestPoliciesAndTruth(t *testing.T) {
	tests := []struct {
		name                               string
		change                             func(*TechnicalGateInput)
		aKnown, aAllowed, bKnown, bAllowed bool
	}{
		{"15秒未知", func(in *TechnicalGateInput) { in.Current.Short.Fifteen.Known = false }, true, true, false, false},
		{"15秒同方向", func(in *TechnicalGateInput) { in.Current.Short.Fifteen.Move = 15; in.Current.Short.Fifteen.Speed = 1 }, true, true, true, false},
		{"5秒等号", func(in *TechnicalGateInput) { in.Current.Short.Five.Move = 0; in.Current.Short.Five.Speed = 0 }, true, false, true, false},
		{"量等号", func(in *TechnicalGateInput) { in.Current.Buy.OFI30 = 0 }, true, false, true, false},
		{"量未知", func(in *TechnicalGateInput) { in.Current.Buy.OFIKnown = false }, false, false, false, false},
		{"量未知かつ5秒否定", func(in *TechnicalGateInput) {
			in.Current.Buy.OFIKnown = false
			in.Current.Short.Five.Move = 10
			in.Current.Short.Five.Speed = 2
		}, true, false, true, false},
		{"5秒未知", func(in *TechnicalGateInput) { in.Current.Short.Five.Known = false }, false, false, false, false},
		{"5秒未知かつ量否定", func(in *TechnicalGateInput) { in.Current.Short.Five.Known = false; in.Current.Buy.OFI30 = 5 }, true, false, true, false},
		{"15秒価格齢", func(in *TechnicalGateInput) { in.At = in.Current.Time + 15; in.Chart.At = in.At }, true, true, true, true},
		{"16秒価格齢", func(in *TechnicalGateInput) { in.At = in.Current.Time + 16; in.Chart.At = in.At }, false, false, false, false},
		{"未知窓の長い遅れ", func(in *TechnicalGateInput) {
			in.Current.Short.Fifteen.Known = false
			in.Current.Short.Fifteen.Delay = 16
		}, true, true, false, false},
	}
	for _, row := range tests {
		t.Run(row.name, func(t *testing.T) {
			in := fixture(t, 1, "Day")
			row.change(&in)
			a, b := assess(t, in, 1, "S5Q"), assess(t, in, 1, "S515Q")
			if a.Decision.Known != row.aKnown || a.Decision.Allowed != row.aAllowed || b.Decision.Known != row.bKnown || b.Decision.Allowed != row.bAllowed {
				t.Fatal(a.Decision, b.Decision)
			}
		})
	}
}

// TestCorruption は使用/未使用の既知窓破損と全公開値の破損を拒否します。
//
// 引数: t(*testing.T)です。
// 返り値: ありません。
func TestCorruption(t *testing.T) {
	changes := []struct {
		name   string
		change func(*TechnicalGateInput)
	}{
		{"速度単位", func(in *TechnicalGateInput) { in.Current.Short.Five.Speed = -10 }},
		{"両端", func(in *TechnicalGateInput) { in.Current.Short.Five.Endpoint-- }},
		{"未使用15秒", func(in *TechnicalGateInput) { in.Current.Short.Fifteen.Delay = 16 }},
		{"未使用未来窓", func(in *TechnicalGateInput) {
			in.Current.Short.Fifteen.Known = false
			in.Current.Short.Fifteen.Endpoint = in.At + 1
		}},
		{"中央", func(in *TechnicalGateInput) { in.Current.Short.Mid++ }},
		{"時刻", func(in *TechnicalGateInput) { in.Current.Short.Time-- }},
		{"非有限", func(in *TechnicalGateInput) { in.Current.Short.Five.Move = math.Inf(1) }},
		{"未使用RSI", func(in *TechnicalGateInput) { in.Chart.Chart.Technical.RSI3 = 101 }},
	}
	for _, row := range changes {
		t.Run(row.name, func(t *testing.T) {
			in := fixture(t, 1, "Day")
			row.change(&in)
			if _, err := AssessShortExit(in, 1, "S5Q"); err == nil {
				t.Fatal("破損受理")
			}
		})
	}
	in := fixture(t, 1, "Day")
	if _, err := AssessShortExit(in, 0, "S5Q"); err == nil {
		t.Fatal("side0受理")
	}
	if _, err := AssessShortExit(in, 1, "X5"); err == nil {
		t.Fatal("別政策受理")
	}
}

// TestExport はGo公開型の人工を新規ファイルにだけ保存します。
//
// 引数: t(*testing.T)、環境変数SHORT_EXIT_FIXTURE_OUT(string)は新規保存先です。
// 返り値: ありません。未指定の通常テストではskipします。
func TestExport(t *testing.T) {
	path := os.Getenv("SHORT_EXIT_FIXTURE_OUT")
	if path == "" {
		t.Skip("人工export専用")
	}
	type row struct {
		Name   string             `json:"name"`
		Input  TechnicalGateInput `json:"input"`
		Side   int                `json:"side"`
		Policy string             `json:"policy"`
		Result Assessment         `json:"result"`
	}
	rows := []row{}
	for _, kind := range []string{"Day", "Night"} {
		for _, side := range []int{1, -1} {
			for _, policy := range []string{"S5Q", "S515Q"} {
				in := fixture(t, side, kind)
				result := assess(t, in, side, policy)
				rows = append(rows, row{fmt.Sprintf("%s/%d/%s", kind, side, policy), in, side, policy, result})
			}
		}
	}
	for _, name := range []string{"15秒同方向", "15秒未知", "量未知", "量未知かつ5秒否定"} {
		for _, policy := range []string{"S5Q", "S515Q"} {
			in := fixture(t, 1, "Day")
			switch name {
			case "15秒同方向":
				in.Current.Short.Fifteen.Move, in.Current.Short.Fifteen.Speed = 15, 1
			case "15秒未知":
				in.Current.Short.Fifteen.Known = false
			case "量未知":
				in.Current.Buy.OFIKnown = false
			case "量未知かつ5秒否定":
				in.Current.Buy.OFIKnown = false
				in.Current.Short.Five.Move, in.Current.Short.Five.Speed = 10, 2
			}
			result := assess(t, in, 1, policy)
			rows = append(rows, row{name + "/" + policy, in, 1, policy, result})
		}
	}
	body, err := json.MarshalIndent(map[string]any{"人工": true, "scope": "手製短秒値と停止X5公開Input・Source形成/市場/金融なし", "cases": rows}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.Write(append(body, '\n')); err != nil {
		f.Close()
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
}
