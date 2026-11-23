# 初回残玉正益の確定（試行97）

試行97へ採用する金融実装。人工検査を完了し、市場運転前の条件固定を準備している。正式96の26コード、条件24e1…、旧試行、純Sourceを変更していない。原板・新しい市場損益・新日付を読まず、H0の市場運転も行わない。技法/Bank/Runtimeは複写せず、96金融7Goを由来SHA付きで派生した。

moduleは`github.com/masayoshi4649/SessionTradeExecuter/miniharvest`、packageは`miniharvest`。新公開JSONは`config.harvest_policy`（`omitempty`）だけ。空なら旧Key/ID/全金融JSONを保つ。`HarvestPolicy="H0"`は`EntryTiming="B5Q" / Policy="P0"`、GatePolicy空又はABだけを許し、Keyを`H0_`で接頭する。

公開methodは96と同じ`NewActualBook/OnNativeStep/OnNativeForce/OnEntryGridWithGate/Snapshot/Finish`。Observation/Session/QuoteStampは固定native93のaliasのまま。NativeBatch/EntryCandidate/SourceIdentity/GateDecisionは同形の新named型で、Tape側では明示値変換する。SourceやScalarの追加fieldはない。利益確定の追加分は既存ActivationとConfigだけを読み、Observationの必要欄を増やさない。

## H0の意味と変更箇所

現在残玉の費用後単価`u=gain*100−77−2*SlipPts*100`が初めてstrict正になれば、従来どおりProtectionActive/Activationを保存する。H0では最低床を`max(0,Activation.GainPoints)`にする。既存の固定2ATR床と前回床をmaxで重ねるため、名目建値以上・非緩和を保つ。ATR未知でも最低床を先に起動する。

初回正益と同じ気配はその床への到達である。床hitは旧どおり記録し、注文要求は`after_source`だけで未予約実残量へ出す。専用reasonは**`初回費用後残玉正益の全量確定`**。これは普通の幅あるATR追尾ではなく、初回費用後残玉正益での全量返済**要求**である。Wだけ正益又はu同値0では起動しない。C5もuの費用に含める。

旧順序は維持する。正常原行のpre_fill評価/起動→既存Actual注文fill→Source close→出生受付→after_source保護要求。pre_fillで新規の返済注文を作らない。Sourceが既に予約した量は二重に要求しない。全予約済み量が当行で返済されて残0なら、その正益旗は残るがH注文は追加しない。

要求と同じ原行ではfillしない。D0もstrict後続Indexかつ正常BBO、D1は要求+1価格秒以上を要求する。次の気配や費用により最終赤字になり得る。予約はActual容量を解放しない。SourceClose ceil配分/全残、未取得new取消、費用38.5円片道・想定滑り、半円会計、Source出生量/入口条件は変更していない。

数学/金融本文の変更は`actual.go`のConfig検査・H0 Key・最低床・reason分岐だけ。`actual_types.go`にomitempty設定を追加した。entry_grid/entry_gateの式はpackage/由来header以外を変更していない。既存テストもpackage/由来header以外を保持し、Runtime helperの新複写は不要だった。

## 人工の根拠と限界

- 空Harvestは旧96を別にimport/運転し、N/B5/B5Q（B5QはGate空/AB）、買売、C0/C5、D0/D1の32会計で、各原行・grid・Finishの全JSON bytesを**除外0**で比較する。
- H0は同じ手製SourceをP0/H0×Gate空/AB×C0/C5×D0/D1の16口座へ配送。買売鏡像、ATR未知、費用による初回起動価格差、同価格秒の後原行、Sourceの先行/同原行部分・全量予約、全fill後残0旗、u正/W負、次気配悪化、予約込み買売各10枚/終了残0を確認する。
- `u=0/W正`はRを持つ単元状態を直接markし、`>=0`又はWによる誤起動を拒否する。これは空口座からのFAR自然運転への到達可能性を主張する人工ではない。他のH系列は全てSource public型の新規/実fill/返済通知を配送する。
- 人工の通常系列ではC0がgain10ptで要求、C5がgain20ptで要求。後続fillの純額は5枚でC0=9,615円/C5=4,615円。悪化系列では同じ正益要求後にC0=−10,385円/C5=−15,385円を実際に記録する。これは手計算照合用の人工額で、市場成績ではない。

```powershell
go test -json -count=1 ./...
go vet ./...
go build ./...
# 実Go型の人工exportは環境MINIHARVEST_EXPORT_DIRへ未作成pathを指定し、
# go test -count=1 -run '^TestExportHarvest97$' を実行する。
```

人工exportは通常買/売、同原行Source部分、次気配悪化の4場面×16口座。生のSource戦略/原板/ATR生成や収益性は未検証。機会損失、退出後価格、将来峰、理想約定価格の置換は評価しない。市場運転の範囲と順序は[試行97の検証計画](../../study/00097_初回費用後利益の全量確定/検証計画.md)に従う。
