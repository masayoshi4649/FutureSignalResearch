# 短秒進行と現在量の退出

module/packageは`minishortexit`。停止元0e2e50bcの`AssessShortExit(input,side,policy)`をGo本文同体で配置した。政策は本名`S5Q`/`S515Q`、公開型/品質はcanonical minix5へ依存する。[仕様](仕様.md)は停止元と同体。

確定足背景、当原行短秒価格、表示数量の役割を分け、未知を不成立や0へ補完しない。判断を金融の返済要求/約定と同一視しない。Source/特徴/チャートは生成しない。配置信頼性の検査であり市場での有効性を示さない。

```powershell
go test -count=1 ./...
go vet ./...
go build ./...
```

testの元X5公開型は隣のcanonical X5 `testdata/公開型.json`を固定SHA3e644241…で読む。旧work fixtureに依存しない。由来と許可差は`由来.json`。市場Runtime/金融採用は別工程、PnLや機会損失をこの純部品で計算しない。
