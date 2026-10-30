# 移動平均線・MACD・RSI：方向と勢いを分ける

識別子：C01。確認日：2026-10-30。[組み合わせの目次と共通条件](README.md)

## 1. 一般に紹介される判断

長めの方向が上を向く中で、一時的な調整の後に勢いが回復した場面を探す考え方である。移動平均線で取引する方向を限定し、MACDで短期の変化を捉える。

StockChartsの公式教材には、200日MAより上にある米国株から、負の領域でMACDがシグナルを上抜ける候補を探す例がある。これは日足の選別例であり、本研究の5分足の設定や利益を裏付けるものではない。[MACD教材・提案される検索条件](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-moving-average-convergence-divergence-oscillator)

RSIを追加するなら、上昇・下落の値幅の配分が回復しているかを確認する役割になる。FidelityはRSIの解釈を相場の方向に応じて変える考え方を紹介する。ただし「MA・MACD・RSIの三つを同時に満たせば優位」という結論は、ここで確認した資料からは得られない。[RSI教材・方向による読み方](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/rsi)

## 2. 三つを何のために使うか

| 指標 | 担当する問い | 単独では分からないこと |
| --- | --- | --- |
| [移動平均線](../指標/移動平均線.md) | 長めの価格の方向は上か | 調整が終わったか |
| [MACD](../指標/MACD.md) | 短長期の平滑差が回復したか | 回復が続くか、費用を上回るか |
| [RSI](../指標/RSI.md) | 上向きと下向きの値幅の配分はどうか | 新しい買い資金が入ったか |

三つとも価格由来なので、独立した三つの証拠ではない。まずMAとMACDの組を基準にし、RSIの追加が何を変えるかを別に比べる。

## 3. 心理の説明を一つの流れにする

仮想例として、上昇を見て買いたいが高値を追いたくない参加者がいる。価格が少し下がった後、下げ止まりが見えると買いを再開するかもしれない。売り建玉の返済買いが加わる可能性もある。これが[追随P03・買い戻しP04](../市場心理/追随と買い戻し.md)による説明候補である。

MA上向きとMACD交差は、その説明に合う価格変化を捉える。しかし、長めの平均がまだ上向きなだけで、実際には下落への移行途中かもしれない。価格の推移と注文目的を同一視しない。

## 4. 再利用する教材カード

| 項目 | 基準例Aと追加例B |
| --- | --- |
| 環境 | 確定5分足で `C_t > EMA60_t`、`EMA60_t > EMA60_(t−1)` |
| 発動A | MACD(12,26,9、各EMA)がシグナルを上抜ける |
| 追加B | Aに `RSI14_t > 50` を追加。RSIはWilder型、Aと別候補として記録 |
| 前提崩れ | 終値がEMA60を下回る、またはMACDがシグナルを下抜ける |
| 通常決済 | 前提崩れを確定足で観測後に返済。保護と期限は共通条件 |
| 比較 | MACDのみ、A、Bを同期間・費用で比較 |
| 心理と反証 | P03・P04は推論。買い再開を意味する注文目的の情報は未確認 |

このカードは資料を参考にした本研究の教材であり、上記200日MAの例と同一手法ではない。売り側は不等号・交差を反転して別に定義する。MACDが負か正かを追加条件にする変更も、同じ結果へ後付けせず別候補にする。

## 5. よくある読み違いと失敗

MAが上向き、MACD上向き、RSI75という場面は、強い上昇の継続にも短期調整の直前にもなり得る。RSI75だから新規売り、という別方向の仮説を無条件に混ぜない。

MACDの反応を待つほど、押し目の底から離れた価格になる場合がある。RSIを追加して勝率が上がっても、遅延による利益縮小や取引数減少を含めて比較する。SMAの傾きには古い価格が計算窓を外れる影響があり、EMAでは過去の影響が徐々に減衰する。

## 6. 根拠の対応表

| 資料 | 支えること | 本研究で付け加えたこと |
| --- | --- | --- |
| [StockCharts・MACD](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-moving-average-convergence-divergence-oscillator) | MAを方向条件とするMACDの検索例 | EMA60、5分足、RSI追加、通常決済の具体条件 |
| [Fidelity・RSI](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/rsi) | RSIの相場方向による解釈、極端値の継続 | 50という追加条件の採否は未検証 |
| [心理P03・P04の資料](../市場心理/追随と買い戻し.md) | 追随と返済注文を考える背景 | この交差の原因がそれらであるとは立証していない |
