# Force失敗後の価格確認と上位禁止

[計画](../../study/00048_Force失敗後の価格確認と上位禁止/計画.md) / [正式結果](../../study/00048_Force失敗後の価格確認と上位禁止/README.md) / [Impulse教材](../../docs/technical-analysis/組み合わせ/Impulseと売買の禁止.md) / [版5](../../docs/議論/手法と時間スケールの汎用表_版5.md)。回復前/後の価格失敗fを観測し、別足の最初の価格確認kから反転を要求する新母機械。S0/S1の二切替・二XF・実四役割を比較する。原典Impulse Releaseの複製ではない。

|ファイル|役割|
|---|---|
|[指標.py](指標.py)|旧29価格/ATR/Qから精密Force2、旧28の15分価格から中心化HとEMA13を作る|
|[入口.py](入口.py)|当時上位asof・b登録・j回復・前後f観測・新T端/k・候補別採否を保存する|
|[検証.py](検証.py)|非損益準備・上位4列定義・固定・新全先着・二運用と四役割を接続する|
|[運用.py](運用.py)|固定33のXFへ純13列だけを渡す|
|[合成検証.py](合成検証.py)|鏡像・f/k別足・取消優先・初回消費・EMA局所ゲート・非損益guardを検査する|
|[状態独立確認.py](状態独立確認.py)|原8列/Q/Force/上位二経路・全状態/採否・新case全直接先着を別手順で検算する|
|[追尾独立確認.py](追尾独立確認.py)|全保有・現在益起動・最低名目床・最初返済要求を別機械で照合する|
|[独立監査.py](独立監査.py)|純T同値/R包含・四役割・即時受付/Decimal/CSV/Viewerを照合する|
|[対応診断.py](対応診断.py)|保存七系列から前後f/k・保持追加R・実占有・回収と品質を分ける|
|[レポート.py](レポート.py)|全証明後の保存値だけを二MDと55×9へ表示する|

上位は当場の最新15分uと隣接前足を、end≤下位endかつ公開key≤下位要求keyで参照する。最新不良を古正常へ戻さない。H差DとEMA13差Eを使い、IはE=D≠0のときその方向、準備済の他は0、欠測None。H/EMA水準signは未使用。b/TにEMA準備・I=sのゲートはなく、新Rだけ現前EMA準備を共通に課す。

Force素X=(C現−C前)×q現、初2有効Xの平均を種に以後F=(2X+前F)/3。Fractionで厳密に計算し、完全非負0q/0Fは有効。q不完全でForceを解除しても正常Cを次足価格基準に保持し、前価格足qは不要。観測数量を真の売買側フローとみなさない。

背景sをp/bで知り、sF前≥0→sFb<0を一監視に登録する。寿命b+6はj/fでリセットしない。回復前の元逆端失敗を先にf固定し、別経路で初回sF>0・D=sならj回復。j後のT端が先なら順行発動、逆端失敗なら回復後fへ移る。fは観測だけで注文しない。f後の別足の初確認kは不採用でも消費、元逆端への回復は等号を含め先取消する。

Tは実方向s、Rはr=−s。新Rは共通EMA準備と現在Force方向を満たした上で、S0はD=r、S1はI≠sを要求する。純Tは両案同値、純S0R⊆S1R。ただし追加Rの建玉占有で実T参加は変わるため実参加包含を要求しない。I=0は反転確認や禁止解除の遷移を意味しない。旧47はf時消費だったため、旧47全期T・旧label・旧運用完全対照はない。

新規要求・ATR・30分間引きの時計は**順行T端/反転確認k**に統一し、b/j/fへ遡らない。正式七gzipは全指標26列/上位15分15列/価格状態（登録・監視）/発動判定/入口事例/全運用詳細/追尾。caseは純13＋期間/要求JST/元価格発動ID＋metadata13＋新11label。liveへ親/上位/未来labelを渡さない。

共有ref2は旧29の指標参照・旧28の上位価格参照。新上位数値定義.jsonl.gzは場/index/macd_hist/ema13_centeredの**4列だけ**をprepareで保存・固定・正式同byte保全する。work消去時は正式保全から所定workへ復元し、圧縮/展開SHAを照合する。旧全数値・原板を複製しない。下位ATR/上位H・EMAとその差の値だけ独立abs1e−10/rel0、Force分数・有限準備・差方向E/D・ImpulseI・全採否はstrict。正本定義からの全内容SHAと独立生値の表現差は別保証。

Python3.14.3、NumPy2.5.3、orjson3.13.0。主/独立/財務/人工/保存診断は担当者一人が許可後に一回管理する。既存結果・部分gzipを上書きせず、再現には別出力先と同じ条件/refを指定する。

```powershell
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/検証.py
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/対応診断.py
C:/Python314/python.exe -X utf8 scripts/Force失敗確認/レポート.py
```

XFは現在正常返済BBOの含み粗利益円−122円>0strictで起動。T端/k要求時ATRからDを固定し、MFE−D/最低名目entry床/非緩和/pending凍結を維持する。起動参照滑り5ptは同約定費用0/5/10でも固定。起動後基準赤字は追加0pt手数料込みであり、122円/追加5pt成績と別尺度。名目床は費用後同値や遅延後同値約定を保証しない。

会計人工は四実役割×買売の8経路。正式Viewer132資源/2代表。学習は両案NK運用品質注意1場のため0/5/10pt全体確定対象額null、観測額/平均と入口観測不足を区別する。全NK66既使用、TOPIX未参照、11/5Day両商品未開封。次49算法は未採用、ユーザー指示により外部実証・心理起点の再調査へ移る。
