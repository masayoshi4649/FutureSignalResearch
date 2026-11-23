# Kase DevStops：逆行幅の平均と散らばり

確認日：2026-11-13。汎用表V8の識別子I19。[指標目次](README.md) / [ATR](ATR.md) / [Chandelier](ChandelierExit.md)。

## 原著の定義

Cynthia Kaseの[価格変動を用いたstop論文（2005）](https://www.kaseco.com/support/articles/Setting_Stop-Losses_Using_Price_Volatility.pdf)と[TRD計算欄のある原著（2005）](https://www.kaseco.com/support/articles/Proof_That_Technical_Analysis_Really_Works.pdf)を確認した。通常ATRの平均だけでなく、2足True Rangeの標準偏差と歪度を扱う。

```text
TRD_i = max(H_i,H_(i−1),C_(i−2)) − min(L_i,L_(i−1),C_(i−2))
幅 D_k = mean_n(TRD) + k × sd_n(TRD)
買い側候補 = 基準高値 − D_k
売り側候補 = 基準安値 ＋ D_k
```

TRDは二足の区間とその前Closeの範囲で、単なる2×一足TRではない。原著は警戒線/Dev1/2/3に0/1/2.2/3.6の係数を示す。例えば平均20pt・標準偏差5pt・k=2.2なら幅31pt。これは架空の算術例。

## 心理の仮説

平均の揺れが同じでも、稀に大きい逆行が出る市場と均質な市場を分けて許容幅を考える。散らばりは観測値の性質であり、恐怖/投げ/主体の注文を識別する指標ではない。

## 本研究の派生

取得後の峰からDを引く床候補を、勢い・量・価格根拠の維持と組み合わせる。初期SL、一定利益arm、名目床0、非緩和は別の共通規則。原著のMAで切り替える方向や商品全体の売買システムをそのまま移植したものではない。

## 限界と実装の固定点

分足幅/n、TRDの必要履歴、標準偏差の分母nかn−1か、基準高安の開始点、配送時点、未知/resetを明示する。幅が増えても既設の保護床を不利に戻さない。原著の他先物/日足の分布や歪度補正を、NK分足での特定確率や利益保証としない。警戒線だけの効果と、勢い/量条件を含む複合政策の成績も分ける。
