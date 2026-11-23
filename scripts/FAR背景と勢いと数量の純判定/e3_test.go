package minie3

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"

	fixed96 "github.com/masayoshi4649/SessionTradeExecuter/minichart"
)

// repo99 は試験の由来ファイルと既使用保存だけのルートを求めます。
//
// 引数: なし。
// 返り値: stringはwork/このmoduleの2段上です。市場を列挙しません。
func repo99() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Dir(filepath.Dir(filepath.Dir(file)))
}

// hash99 は停止指紋を計算します。
//
// 引数: body([]byte)は既存コード/保存本文です。
// 返り値: stringはSHA256です。
func hash99(body []byte) string {
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}

// assess99 は純評価の予期しないerrorを直ちに報告します。
//
// 引数: t(*testing.T)、in(TechnicalGateInput)、c(EntryCandidate)、policy(string)。
// 返り値: TechnicalAssessmentは実関数の返り値です。
func assess99(t *testing.T, in TechnicalGateInput, c EntryCandidate, policy string) TechnicalAssessment {
	t.Helper()
	result, err := AssessTechnicalGate(in, c, policy)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

// sync99 は人工の最新c足と現在公開Technicalを同じ値にそろえます。
//
// 引数: in(*TechnicalGateInput)は手製fixtureです。
// 返り値: ありません。価格再生や指標計算ではありません。
func sync99(in *TechnicalGateInput) {
	in.Recent3[2].Chart = in.Chart.Chart
}

// Test99FixedAndMirror は固定本文SHA、売買鏡像、使用checksと入力不変を検査します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。
func Test99FixedAndMirror(t *testing.T) {
	path := filepath.Join(repo99(), "scripts", "FAR5分枠の順行反転と数量", "technical_gate.go")
	body, err := os.ReadFile(path)
	if err != nil || hash99(body) != FixedTechnicalGateSHA256 {
		t.Fatal("固定96純本文のSHA差", err)
	}
	for _, side := range []int{1, -1} {
		for _, kind := range []string{"Day", "Night"} {
			in, c := technicalFixture99(side, "A")
			in.Kind = kind
			before, _ := json.Marshal([]any{in, c})
			base, err := fixed96.AssessTechnicalGate(in, c, "A")
			if err != nil {
				t.Fatal(err)
			}
			for _, policy := range []string{"E3", "E3S"} {
				got := assess99(t, in, c, policy)
				if !got.Decision.Known || !got.Decision.Allowed || got.Decision.Policy != policy || got.Decision.SnapshotID != in.SnapshotID || got.Decision.Role != "順行" {
					t.Fatal(got.Decision)
				}
				want := 8
				if policy == "E3S" {
					want++
				}
				if len(got.Checks) != want {
					t.Fatal("使用check集合", got.Checks)
				}
				for _, check := range got.Checks {
					found := false
					for _, old := range base.Checks {
						if old.ID == check.ID {
							found = reflect.DeepEqual(old, check)
						}
					}
					if !found {
						t.Fatal("既存checkを改変", check)
					}
				}
			}
			after, _ := json.Marshal([]any{in, c})
			if string(before) != string(after) || c.Side != side {
				t.Fatal("入力map/slice/SourceSideを変更")
			}
		}
	}
}

// Test99ExcludedAndSpike は除外した旧条件とE3Sだけの追加条件を区別します。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。固定0/1/2/15境界だけを使います。
func Test99ExcludedAndSpike(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, kind := range []string{"CloseEMA反対", "距離1ATR超", "ATR必要未知", "Close進行同値", "同時スパイク", "TR等号", "RSI等号"} {
			t.Run(kind+map[int]string{1: "買", -1: "売"}[side], func(t *testing.T) {
				in, c := technicalFixture99(side, "A")
				v := &in.Chart.Chart.Technical
				s := float64(side)
				switch kind {
				case "CloseEMA反対":
					v.Close3 = v.EMA8_3 - s*10
				case "距離1ATR超":
					c.Quote.Bid += s * 100
					c.Quote.Ask += s * 100
					c.Quote.Last += s * 100
					in.Current.Bid, in.Current.Ask, in.Current.Last = c.Quote.Bid, c.Quote.Ask, c.Quote.Last
				case "ATR必要未知":
					v.ATRKnown, v.ATR3 = false, 0
				case "Close進行同値":
					in.Chart.Chart.PreviousClose3 = v.Close3
				case "同時スパイク", "TR等号", "RSI等号":
					v.TR3 = 41
					v.RSI3, v.PreviousRSI3 = 90, 74
					if side < 0 {
						v.RSI3, v.PreviousRSI3 = 10, 26
					}
					if kind == "TR等号" {
						v.TR3 = 40
					}
					if kind == "RSI等号" {
						v.PreviousRSI3 = v.RSI3 - s*15
					}
				}
				sync99(&in)
				e3 := assess99(t, in, c, "E3")
				e3s := assess99(t, in, c, "E3S")
				if !e3.Decision.Known || !e3.Decision.Allowed || !e3s.Decision.Known || e3s.Decision.Allowed != (kind != "同時スパイク") {
					t.Fatal(kind, e3.Decision, e3s.Decision)
				}
				old, err := fixed96.AssessTechnicalGate(in, c, "A")
				if err != nil {
					t.Fatal(err)
				}
				if kind != "TR等号" && kind != "RSI等号" && old.Decision.Allowed {
					t.Fatal("外した旧条件が元Aでも成立", kind)
				}
			})
		}
	}
}

// Test99UnknownAndCorruption は必要未知と既知拒否、未来/破損を分けます。
//
// 引数: t(*testing.T)は試験器です。
// 返り値: ありません。値を0支持に補完しません。
func Test99UnknownAndCorruption(t *testing.T) {
	for _, side := range []int{1, -1} {
		for _, kind := range []string{"量未知", "価格鮮度未知", "未知と反対増分", "量零", "スパイク未知E3S", "価格未知とスパイク拒否E3S", "未来公開", "未来Source", "未来Current", "未使用ATR非有限", "未使用ATR負値", "別物理行", "政策不正"} {
			t.Run(kind+map[int]string{1: "買", -1: "売"}[side], func(t *testing.T) {
				in, c := technicalFixture99(side, "A")
				policy, wantErr, wantKnown, wantAllowed := "E3", false, false, false
				volume := &in.Current.Buy
				if side < 0 {
					volume = &in.Current.Sell
				}
				switch kind {
				case "量未知", "未知と反対増分":
					volume.OFIKnown = false
					if kind == "未知と反対増分" {
						in.Chart.Chart.Technical.Histogram3 = in.Chart.Chart.Technical.PreviousHistogram3 - float64(side)
						wantKnown = true
					}
				case "価格鮮度未知":
					c.At += 15
					in.At, in.Chart.At, in.Current.Received = c.At, c.At, in.Current.Time
				case "量零":
					volume.OFI30, wantKnown = 0, true
				case "スパイク未知E3S":
					policy = "E3S"
					in.Chart.Chart.Technical.SpikeKnown = false
				case "価格未知とスパイク拒否E3S":
					policy, wantKnown = "E3S", true
					c.At += 15
					in.At, in.Chart.At = c.At, c.At
					v := &in.Chart.Chart.Technical
					v.TR3, v.RSI3, v.PreviousRSI3 = 41, 90, 74
					if side < 0 {
						v.RSI3, v.PreviousRSI3 = 10, 26
					}
				case "未来公開":
					in.Chart.Three.AvailableAt, wantErr = in.At+1, true
				case "未来Source":
					c.Source.BirthTime, wantErr = in.At+1, true
				case "未来Current":
					in.Current.Received, wantErr = in.At+1, true
				case "未使用ATR非有限":
					in.Chart.Chart.Technical.ATR3, wantErr = math.NaN(), true
				case "未使用ATR負値":
					in.Chart.Chart.Technical.ATR3, wantErr = -1, true
				case "別物理行":
					in.Current.SourceLine++
					wantErr = true
				case "政策不正":
					policy, wantErr = "A", true
				}
				sync99(&in)
				got, err := AssessTechnicalGate(in, c, policy)
				if wantErr {
					if err == nil {
						t.Fatal("破損を成功", kind, got)
					}
					return
				}
				if err != nil || got.Decision.Known != wantKnown || got.Decision.Allowed != wantAllowed {
					t.Fatal(kind, err, got.Decision)
				}
			})
		}
	}
}
