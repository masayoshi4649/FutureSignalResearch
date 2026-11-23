# Chande Kroll Stop：二段の高安/ATR窓

確認日：2026-11-13。汎用表V8の識別子I21。[指標目次](README.md) / [ATR](ATR.md) / [Chandelier](ChandelierExit.md)。

## 一般定義と参照実装

[TradingView公式](https://www.tradingview.com/support/solutions/43000589105-chande-kroll-stop/)はChande/Kroll『The New Technical Trader』を由来とし、高安/TRによるstopを説明する。書籍の原式は今回未照合。[Wickra公式実装資料](https://docs.wickra.org/Indicators/Indicator-ChandeKrollStop)は次の二段式を公開する。

```text
high_stop_i = highest_p(H) − x ATR_p
low_stop_i  = lowest_p(L) ＋ x ATR_p
stop_short_t = highest_q(high_stop)
stop_long_t  = lowest_q(low_stop)
```

線名を直感で入れ替えない。上記providerの平坦例H11/L9/ATR2/x1ではstop_long=11、stop_short=9となる。どちらの線をどの保有方向/状態へ使うかは、値の幾何と採用実装を確認して固定する。この説明を原著全仕様の認定とはしない。

## 心理の仮説

単発の広い足だけでなく、一定窓で維持される価格域をstopへ反映する考え方である。価格が線間にあることを、参加者が迷っている証拠や方向確率とは呼ばない。

## 本研究の派生

方向MA/DIと勢い/量で状態を確認し、保有側の適格な線だけを候補床にする。初期SL/arm/利益床/非緩和は共通契約。線が現在価格の不適格な側にある場合は、都合で別の線へ差し替えず候補不適格を記録する。

## 限界と固定点

p/x/q、ATR平均法、n足の包含範囲、窓不足/欠分、線名、方向初期化を固定する。第二窓の古い値が抜けると線が後退し得るため、計算線と注文保護床を分ける。似たATR stopでもChandelier/SuperTrendと同じ実装ではない。単独の高成績や特定商品での安定利益は本教材から主張しない。
