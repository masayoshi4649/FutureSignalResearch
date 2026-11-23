# 実建値からの利益前ATR追尾（試行98）

試行98の金融実装。人工検査済みで、市場損益算出前の固定を準備している。97のEntry/Source/数量・片側10枚/費用/5分時計/AB callback/H0を保持する。原板、98市場、97H54結果は未読で、正式155コード・条件を変更しない。

## APIと設定

モジュール `github.com/masayoshi4649/SessionTradeExecuter/minirisk98`、package `minirisk98`。`NewActualBook`、`OnNativeStep`、`OnNativeForce`、`OnEntryGridWithGate`、`Snapshot`、`Finish` は97と同形。Configへ `risk_policy,omitempty` を追加する。

- 空：旧97のKey/JSONを全field保持する。新optional tagは出さない。
- `R05` / `R10`：H0+B5Q+P0、Gate空/G0又はABだけ。Keyの最外側へ政策名を付ける。
- 最初の実取得原行に公開済みの5分ATR（既存native ATR12）を固定する。幅はそれぞれ `clamp(0.5×ATR,20,125)` / `clamp(1×ATR,20,125)` pt。新しい5pt丸めは追加しない。
- ATR未知なら125ptを永久固定し、後の既知ATRで書き換えない。従来H用の2ATR lockは従来どおり別に動く。

利益前だけ `floor=max(-width,観測PeakGain-width,前floor)` とする。初期 `-width` は規定の床で、Peak0を観測した意味ではない。正常板の `pre_fill` / `after_source` で初期riskのPeakを観測する。逆行で床を緩めない。

`gain<=floor` の初到達を記録し、追加要求は `after_source` の未予約残だけ。Sourceの先行・同原行予約を優先し、要求後の同原行fillはしない。Forceは古い板でMTM/fillを追加しない。幅は要求境界であり、次板の飛びや費用を含む実損失上限の保証ではない。

費用後残玉単価 `u>0` の初回に旧H0のProtectionActive/Activationへ移り、riskに戻らない。H0の最小床・2ATR追尾・全量確定要求は変更しない。初期risk要求の受理後に価格が回復しても、その既予約要求を撤回・H要求へ付け替えない。

## 保存を分ける

Positionの `initial_risk,omitempty` は幅の既知/未知出典・取得Quote・観測Peak/床・更新点・first_hit・profit_transition。Hの `activation` / `floor_gain` / `first_floor_hit` へriskの証拠を入れない。

Orderの `initial_risk_point,omitempty` はrisk要求時のMTM/Peak/床。Hの `protection_point` はrisk要求ではnull。理由は `利益前の固定初期幅追尾`。risk要求回数も `initial_risk_exit_requests,omitempty` としてSource/Hの既存counterから分離する。新fieldは空政策で出現しない。

## 人工の範囲

旧97の全呼出時点JSONへ、空risk八会計×買売×通常/次板悪化の32系列を除外0比較する。新riskは買売×7境界波形、各24口座（空/R05/R10×Gate空/AB×C0/C5×D0/D1）。幅のclamp/非丸め/未知後既知、床の非緩和、Source部分・全予約、Force、strict u同値0、利益後の逆行、risk要求後の正益、次板悪化、実fill費用算術を確認する。

Source・ATR・AB許可は手製のAPI人工である。ABの数式や自然Sourceをこの試作で検証したとは呼ばない。値幅指標による利益前保護を比較し、複合入口の技法は既存のまま別に保持する。早期返済で余力が変われば、同じ出生規則でも実参加集合は変わり得る。

```powershell
go test ./...
go vet ./...
go build ./...
```

指定手数料は38.5円/枚片道、C5の5pt/片道は実測ではない感度条件。新しい市場利益・勝率・安定性は未検証である。

正式な範囲は[試行98の計画](../../study/00098_実建値からの利益前ATR追尾/検証計画.md)を参照する。
