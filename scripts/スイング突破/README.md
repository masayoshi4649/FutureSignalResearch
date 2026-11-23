# 確定スイング突破と方向優勢

[事前計画](../../study/00045_確定スイング突破と方向優勢/計画.md) / [個別教材](../../docs/technical-analysis/指標/確定スイングの突破.md)。新しい確定スイング水準の終値crossを母集団とし、最新2高2安の構造とDMI方向をC0、Fast14/3準備をC1、実方向の精密Fast差正をC2とする。全三XF・集合切替、実T順行/R反転の六役割群。旧245へのANDや旧先着・旧運用の完全同値比較ではない。

|ファイル|役割|
|---|---|
|[指標.py](指標.py)|共有29の価格/ATRから、新DMI同契約銀行と当場Fastを分けて作る|
|[入口.py](入口.py)|前足までの確定pivotで原cross・初回消費・構造T/R/WAITと三採否を作る|
|[検証.py](検証.py)|非損益準備/小型DI定義/固定、新全case先着・三XF・六役割の保存を接続|
|[運用.py](運用.py)|固定33の現在費用後正起動XFを再用|
|[合成検証.py](合成検証.py)|右2確認時点/当j不利用/一回消費/DI/Fast/鏡像/非PnLguardの人工境界|
|[状態独立確認.py](状態独立確認.py)|原8列から新価格状態・数値・全採否と全新case直接先着を別手順で検算|
|[追尾独立確認.py](追尾独立確認.py)|全保有/現在益起動/名目床/最初返済要求を別機械で照合|
|[独立監査.py](独立監査.py)|新case集計/六役割、固定34即時受付、Decimal/CSV/場別/Viewerを照合|
|[対応診断.py](対応診断.py)|保存6系列から価格消費/Fast準備と値/実参加/共通出口/回収を分離|
|[レポート.py](レポート.py)|全証明後の保存値だけを二MD/版4表へ表示|

高値中心は左2本よりstrictに高く、右2本以上。安値は鏡像とし、中心iはi+2の公開で初めて確定する。jはpまでに確定した最新高安だけを使い、買Cp<=R<Cj/売Cp>=L>Cj、j.end>p.confirmと公開keystrictを要求する。jで新確定するpivotは判断後へ回し、中心価格へ遡らない。late足はP/消費なし・monitor理由を残し、局所履歴は進める。

最初の(side,pivotID)crossは構造/指標/時間/保有不成立でも一回消費する。使用済みcrossを後で取り直さず、同価格でも新pivotIDには新crossが必要。価格機械の消費と、実一pending/一建玉による抑止は別である。最新2高2安とも上ならD+1/下ならD−1、同値混在0と履歴不足Noneを分ける。s=DをT、s=−DをRにするが、実sideを反転せず役割名だけで返済も変えない。

DMI14は最初HLC種→14差分算術seedで15足初DI、以後(13prev+x)/14。TR平均0はDI Noneで銀行保持、平滑TR正で平滑DM平均が両0はDI0/0準備・方向不採用。DMIは同契約carry/完全NP内部更新、Fast/pivot/usedは同場公開局所resetとする。Fastは当足含14HLC生Kと連続K3平均、最速16足。14幅0はK3だけclearし14価格窓を保持、個々のH=L足は有効。元float各値のFractionによる差を使い、数学的同値0・80/20・交差・Slow%Dを混同しない。

DI正本4列`{場,index,plus_di,minus_di}`の小型定義hashと、独立生DIのabs1e−10/rel0・優勢符号/準備/採否strictを二経路に分ける。ATRは旧29正本strictコピーと独立生ATR/D整数の検算を分け、Fastは精密差をstrict照合する。生float全SHA同一とは主張しない。小型定義は完了時に正式同byte保全し、work消去時は所定`work/スイング突破/00045/DMI数値定義.jsonl.gz`へ復元して圧縮/展開SHAを照合する。原板/旧全数値を複製しない。

正式新6gzipは全指標/価格状態/発動判定/入口事例/全運用詳細/追尾。価格状態は極値/監視の種別混合で、pivot全出典を一回保存しmonitor/decisionからIDで辿る。旧29数値は共有参照1本、旧入口/label/全運用control参照はない。新caseは純13＋期間/要求JST/元価格発動ID＋metadata5＋新11labelで、liveへ未来labelや仮約定値を渡さない。

Python3.14.3、NumPy2.5.3、orjson3.13.0。以下は再現順で、実市場・人工・主/独立/財務の起動はrootが管理する。既存結果/部分gzipを上書きしない。別再現先へ同条件/入力/共有参照を用意し、`--study`/`--work`や財務/表示のパス定数を明示して使用する。

```powershell
C:/Python314/python.exe -X utf8 scripts/スイング突破/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/スイング突破/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/スイング突破/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/スイング突破/検証.py
C:/Python314/python.exe -X utf8 scripts/スイング突破/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/スイング突破/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/スイング突破/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/スイング突破/対応診断.py
C:/Python314/python.exe -X utf8 scripts/スイング突破/レポート.py
```

`--prepare`は数値/極値/監視/原P/採否/純信号だけで先着・運用・PnLなし。全新caseの実side・新要求+1秒から125/250を原BBOへ直接検算し、旧labelを転用しない。後段保存診断は全正式証明後の許可で担当一人が一回だけ起動し、二MDは保存値だけを表示する。診断/表示からモデル・独立・会計を再起動しない。

XFは正常返済BBOの実side×(mark−entry)pt×10円/pt−122円>0strictで起動し、現j入口ATR固定D/MFE−D/最低名目entry床/非緩和/返済pending凍結を保持する。起動参照滑り5ptと費用後0円超という5+0で、旧A5名目5pt起動ではない。追加0/5/10は同約定費用ストレスで参照5固定。名目床は費用後同値や遅延後同値約定を保証しない。

版4・54×9を維持し、価格構造P02/P03/P07・DIのみI08・Fast I07・ATR I09・固定XF/執行/評価を分ける。ADX/RSI/MACD/上位/量/CMF/TOPIX/R²/旧再テストは不使用。C0/C1同値は実観測で数学的必然とせず、新母集団のT/R分類や条件間の総額差を各指標単独の効果にしない。仮250/実MFE/回収、純subset/実追加、共通出口/片側額、品質観測/確定nullと六役割支持を分ける。

全NK66場は既使用の追加開発。TOPIX未参照・11/5Dayは両商品とも対象外/未開封。価格時計は受信時計ではなく、ラージBBO代理は実micro約定/数量/キューを保証しない。支持/70/費用を結果から緩めない。
