# 効率比ER：移動距離に対する純進行

確認日：2026-11-13。汎用表V8の識別子I17。[指標目次](README.md) / [CHOP](ChoppinessIndex.md)。教材の追加であり、売買条件の採用や自然検証の成功を意味しない。

## 一般定義と式

KaufmanのEfficiency Ratioを、ここでは方向を持たない絶対値版として扱う。n個の終値変化には連続n+1個の終値が必要。

```text
純進行 = abs(C_t − C_(t−n))
道のり = Σ_(i=t−n+1..t) abs(C_i − C_(i−1))
ER = 純進行 / 道のり
```

道のりが正なら0〜1。100→101→100→102では純進行2・道のり4でER=.5。一方向だけへ進めば1に近く、往復して元へ戻れば0に近い。買い/売りの方向は別にEMA傾き・DI等で調べる。

[QuantConnect公式資料](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/kaufman-efficiency-ratio)と[公開LEAN実装](https://raw.githubusercontent.com/QuantConnect/Lean/master/Indicators/KaufmanEfficiencyRatio.cs)を実読した。発明者の書籍本文を今回再確認したものではない。[TC2000公式](https://help.tc2000.com/m/69404/l/749623-kaufman-efficiency-ratio)の符号付き×100版は−100〜100であり、同じ尺度ではない。

## 心理の仮説

売買が繰り返されても価格の純進行が乏しいなら、一定方向を維持する働きが弱い可能性がある。ただしERは注文主体や意図を観測せず、往復の後にどちらへ突破するかも予測しない。

## 本研究での派生

高ER＋方向DI/EMA維持なら通常幅、ER低下＋支持否定＋勢い減速なら保護を締める、と役割を分ける。ERだけで退出/反転を決めない。足の配送時計・実連続窓・欠分を固定し、既設床を緩めない。

## 既知性と限界

平坦な0/0は数学的には未定義。LEANや[TA-Lib公式ER](https://ta-lib.org/functions/er.html)には平坦を1とする実装規約がある。本研究でunknownを選ぶ場合はその差を明示し、未準備/平坦を「完全なトレンド」へ補完しない。期間がn本なのかn変化なのか、丸め/clip/初期化も固定する。ER低下は後から分かる過去窓の特徴で、将来収益の保証ではない。
