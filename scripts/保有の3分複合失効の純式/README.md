# 保有の3分複合失効の純式

module/packageは`minix5`。停止元f57be6c9の公開Input/sideからP・M・Qを三値で返す純部品を、Go本文同体で再利用配置した。Source/チャート/金融を生成しない。市場採用や利益改善を示す配置ではない。

APIは`AssessHeldTechnicalExit(input TechnicalGateInput, side int) (HeldAssessment,error)`。固定96の公開型を使い、Current/3分公表の品質と必要未知を分離する。未使用の15分等の破損も拒否し、金融active/free/latestQuoteは外側の責務。

`testdata/公開型.json`は停止Go人工3e644241…のbyte同体。自然Source/実原板由来ではない。短秒純式のtestもこの小型器具だけを参照する。

```powershell
go test -count=1 ./...
go vet ./...
go build ./...
```

元SHA・配置差・検査は`由来.json`と`work/101正式配置の準備`へ保存する。旧停止元は不変。新Runtime/市場実行や新試行の条件固定は別工程。機会損失・退出後価格を評価しない。
