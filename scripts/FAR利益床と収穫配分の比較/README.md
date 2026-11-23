# FAR利益床と収穫配分の比較

[試行89](../../study/00089_最低建値床を共通にした収穫配分の比較/README.md)のオフライン検証。固定88のE0/E1入口と元Sourceを再用し、G1部分収穫とG2保護付き残全量追尾をD0/D1で比較する。実注文は行わない。

## 役割

- `actual.go`・`source_entry.go`・`hold.go`・`confirm.go`：停止87の金融を派生。旧`NewSourceBook`を保持し、`NewSourceGuardBook`でG2を選択可能にする。G1は旧87と各原行JSON全文同値を検査する。
- `types.go`：入力/Sourceは87、入口・イベントは88の公開型/APIを再用。入口の本文・数式は複写しない。
- `replay.go`・`input.go`・`batch.go`・`source_equivalence.go`・`cmd/batch/`：時計、種、Source、8金融会計、要求結合と初回利益の当原行出典を保存する。
- `集計.py`：528会計・二層対応分解・費用・共有圧縮記録・Viewer528資源を生成する。
- `原板監査.py`：独立所有でG1/G2の床・予約・価格・費用・初回利益を1走査検査する。旧87に残る独立G2分岐を再用し、G2の床理由と注文も検査する。
- `Source通知監査.py`：別1走査でSource通知・比率予約/取消・イベントと利益原行の出典を検査する。所有はID一意集合と全項目で比較する。
- `基準と保存判断の照合.py`：88のG1全264会計と共有判断へ結び、89の入口/供給/外Bindingを検査する。
- `表示監査.py`・`図示.py`：Viewerの全528資源と場別損益を照合し、入口ごとの二配分と遅延を図示する。
- `利益配分と参加差の診断.py`：結果/玉診断の2正本から同実出口の最終黒赤遷移と参加差を集計する。
- `再開価格構造の事後観測.py`：固定88主E1の33玉だけで、平均回復と過去推進Close回復を分ける別の記述統計。89の売買条件には使わない。
- `初回正益の現在性を読む.py`：利益初回の足更新とCurrent各情報の既知性を16玉で照合する。
- `新しい再開と恒久seenの観測.py`：参照HoldIDの既参加による拒否を、前回実返済と新eventの公開順へ結ぶ。再参加売買を仮定しない。

内部modeはS0G1/S0G2、source_policyは全S、入口policyはE0/E1、外book_keyはE0G1等と遅延。ラベルの意味を混ぜない。

## 検査と再生

Go 1.24.2 windows/amd64、CGO=0、Python 3.14.3。依存は`go.mod`の相対`replace`と条件のSHA256を参照する。

```powershell
Push-Location 'scripts/FAR利益床と収穫配分の比較'
go test -count=1 ./...
go vet ./...
go build -trimpath -o '../../work/再現89.exe' ./cmd/batch
Pop-Location
```

正式再生は停止exeと条件が一致した場合だけ実行する。未使用の`work/`子領域へ保存し、既存成果物へ上書きしない。

```powershell
& 'scripts/FAR利益床と収穫配分の比較/ネイティブ実行.ps1' -OutputRoot 'work/89再現' -ValidateOnly
& 'scripts/FAR利益床と収穫配分の比較/ネイティブ実行.ps1' -OutputRoot 'work/89再現'
```

集計・各監査は各Pythonの`--help`、帳票の明示入力は[試行README](../../study/00089_最低建値床を共通にした収穫配分の比較/README.md)、証明範囲は[再現補足](../../study/00089_最低建値床を共通にした収穫配分の比較/再現補足.md)を参照する。

## 保護と限界

G2も費用後現在単価益がstrict正になれば最低建値床を即起動し、ATR・125pt・確定3分失敗・Source・場末返済を維持する。部分収穫とcash床だけを作らない。旧100枚固定G2の成績を数量比例で移植しない。

利益初回の残量/確定益は同原行全fill後。残0旗・同秒別Lineを区別し、未約定益や後の指標を遡及しない。Source生成と指標前史は固定依存で、独立再実装と呼ばない。ラージBBOのmicro代理約定、実通信・順番・板深さの限界を保持する。
