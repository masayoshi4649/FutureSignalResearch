# ADXの水準と変化を入口で分ける

確認日：2026-11-07。2026-11-06の[78事前資料](../../../work/78候補/ADXの強さと変化の資格.md)を正式な共通知見へ整理した。以下は公式教材の再確認と研究側の仮説であり、新しい市場実証ではない。[78の事前計画](../../../study/00078_ADXの水準と変化を分ける/検証計画.md)や固定条件へ、後続調査の条件を追加しない。

## 一次本文の確認範囲

| 資料・日付 | 実読範囲と限界 |
| --- | --- |
| Fidelity Viewpoints：[ADX: How strong is the current trend in stocks?](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-adx)、2026-03-19。図の基準日は2026-03-18 | How ADX works / How to use ADX / How strong is the current trend in stocks? / What to consider。強弱と方向を分け、ADX上昇を順行手法の裏付け、低下を慎重に扱う理由とする。例はS&P 500の日足・数週間である |
| Fidelity Technical Indicator Guide：[Directional Movement Index (DMI)](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/DMI)、本文に公開・更新日の表示なし | Description / How this indicator works / Calculation。DIの方向、DXの絶対差、ADXの平滑化を確認した。特定市場の費用後成績や標本外検証は示されていない |

Viewpointsは[22／63関連文書](方向の強さと変動幅の変化を別に測る.md)の既読資料である。DMIガイドは同じ提供者の補足で、独立した有効性研究ではない。今回の再読を新しい実証資料として数えない。ADXガイドからViewpointsへの転送、既読Schwabも別資料へ重複計上しない。Wilderの1978年原著は未読である。

## 一般説明と研究側の推論

公式説明ではDIが方向、ADXが方向によらない強さを担う。ADXの低下を価格の下落やDIの逆転と同じ意味にはできない。この区別と[既存の数式整理](../../technical-analysis/指標/DMIとADX.md)から、高いADXが低下する同方向調整も観測対象に残し、反転成立は価格条件で別に確認する、という研究側の問いを立てる。

一方、高いADXは過去の強さを平滑値として残し得る。低下を許すことで消耗や弱い波も増えるという反例を残す。「参加が続く」「利確が増える」は心理の仮説であり、ADXやOHLCから実主体・意図・注文フローを直接観測した事実ではない。

## 固定78への接続と反証

78で比較する唯一の変更は、同じ価格機械のTについてF48>=0を入口の必須条件にしないことである。F47=ADX/100、F48=公開15分足のADX現前差/100。F48=0は従来から許され、解除するのは上昇必須ではなく非減速必須である。

F51=F52=1、F47>=0.20、DI方向、FastK、現在価格進行、確認k、Last/E*のpremise、取消・寿命・O49・費用・連続保護は維持する。Rの現在資格も変更せず、逆DI時のF48<0は残す。未知0を既知の減速として通さず、ADX低下だけで反対注文へ切り替えない。ADXとその差は売買反射でも符号反転しない。

追加候補が入口の質・費用後回収・利益保護を悪化させる、または一枚占有により既存候補を押し出す場合を反証として残す。候補の純包含と実参加の包含は別である。公式本文はNK225の3分/15分、250/125先着、支持付き70%、全枠待ち50%以下や費用後利益を実証していない。78の計測結果は各試行の正本へ帰属させる。
