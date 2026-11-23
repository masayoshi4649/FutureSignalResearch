# Choppiness Index：経路の往復と高安幅

確認日：2026-11-13。汎用表V8の識別子I18。[指標目次](README.md) / [効率比ER](効率比ER.md) / [ATR](ATR.md)。

## 一般定義と式

E.W. Dreissに由来する、方向を持たない混雑/往復の尺度。[TradingView公式](https://www.tradingview.com/support/solutions/43000501980-choppiness-index-chop/)と[TT公式](https://library.tradingtechnologies.com/trade/analytics/charts/technical-indicators/choppiness-index/)の計算を確認した。原著そのものの確認ではない。

```text
TR_i = max(H_i, C_(i−1)) − min(L_i, C_(i−1))
R = highest_n(H) − lowest_n(L)
CHOP = 100 × log10(Σ_n TR / R) / log10(n)
```

ATR(1)は各足のTRを意味し、ATR14をn本足す式ではない。TRのため窓先頭の前Closeも必要。概ね高いほど往復、低いほど純進行が大きいが、上昇/下落の向きは表さない。n=2、ΣTR=4、R=2なら100。

## 心理の仮説

同じ高安域で往復を重ねる状態は、ある方向への進行と対抗が釣り合っている可能性がある。合意形成や参加者の迷いを直接測った値ではなく、次の突破方向も分からない。

## 本研究での派生

ER/CHOPは環境、DI/EMAは方向、支持否定/Histは撤退確認として分ける。CHOP上昇だけで狭幅へ切り替えず、価格構造の失効と合わせて判断する。いずれも価格入力を共有するので独立票とはしない。

## 既知性と限界

n>1、必要OHLCと前Closeの連続既知、R>0、ΣTR>0を要求する本研究規約を事前固定する。ゼロ幅をトレンド0で埋めない。一般説明は0〜100の尺度だが、窓前Closeへのギャップを含むTRと窓内高安の比較では式上100超もあり得る。自動clipして原因を隠さない。38.2/61.8等は紹介上の慣例で、NK225分足の最適閾値ではない。
