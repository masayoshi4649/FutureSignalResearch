# 共通知見の目次

更新日：2026-10-30。

最初に [テクニカル分析の教科書](technical-analysis/README.md) を順に読み、実試行の前に [データと閲覧形式](データと閲覧形式.md) と [研究運用](研究運用.md) を確認する。

## 個別の教科書と判断の組み立て

| 入口 | 内容 |
| --- | --- |
| [指標別の目次](technical-analysis/指標/README.md) | 12項目を一つずつ個別調査し、直感・式・数値例・心理・反例・条件カードを整理 |
| [移動平均線](technical-analysis/指標/移動平均線.md) / [MACD](technical-analysis/指標/MACD.md) / [RSI](technical-analysis/指標/RSI.md) | 代表的な指標から読み始める |
| [組み合わせの目次](technical-analysis/組み合わせ/README.md) | 一般に紹介される判断と、応用した教材カードC01〜C07 |
| [市場心理の目次](technical-analysis/市場心理/README.md) | 心理・行動仮説P01〜P06と理論・実証・観測の区別 |
| [判断カードのひな形](technical-analysis/判断カードのひな形.md) | 次の研究へ、条件と根拠を参照して再利用する |

## 目的から探す

| 調べたいこと | 文書・該当項目 |
| --- | --- |
| チャートを読む基礎、ローソク足 | [第1章](technical-analysis/01_チャートの読み方と仮説化.md)・1〜3節 |
| トレンド・レンジ、支持抵抗、チャート形状 | [第1章](technical-analysis/01_チャートの読み方と仮説化.md)・4〜6節 |
| 出来高、板数量、VWAP、ダイバージェンス | [第1章](technical-analysis/01_チャートの読み方と仮説化.md)・7〜8節 |
| 指標の式、EMA/RMA、初期化と必要本数 | [第2章](technical-analysis/02_指標の計算とシグナル.md)・1節と各指標 |
| MACD、RSI、ボリンジャーバンド | [MACD](technical-analysis/指標/MACD.md) / [RSI](technical-analysis/指標/RSI.md) / [BB](technical-analysis/指標/ボリンジャーバンド.md) |
| ストキャス、DMI/ADX、ATR、SAR、一目 | [指標別の目次](technical-analysis/指標/README.md)から個別ページへ |
| ラージ・mini・microの倍率と価格刻み | [第3章](technical-analysis/03_先物と執行の制約.md)・1節 |
| デイ・ナイト、ザラバと板寄せ、限月 | [第3章](technical-analysis/03_先物と執行の制約.md)・2節と6節 |
| 成行・指値・板の偏りの扱い | [第3章](technical-analysis/03_先物と執行の制約.md)・3〜5節 |
| 利確・損切り・保護用逆指値・枚数 | [第4章](technical-analysis/04_決済とリスク管理.md)・1〜4節 |
| 持ち越し防止、注文管理、通信断 | [第4章](technical-analysis/04_決済とリスク管理.md)・5〜7節 |
| 先読み、費用、損益、最大ドローダウン | [第5章](technical-analysis/05_バックテストと改善.md)・2〜6節 |
| MFE/MAE、期間分割、過剰適合、GPU | [第5章](technical-analysis/05_バックテストと改善.md)・7〜10節 |
| 売買ルールの具体的な教材例 | [第6章](technical-analysis/06_検証可能な仮説の例.md) |
| 原板の列、時刻、CSV、圧縮版の制約 | [データと閲覧形式](データと閲覧形式.md)・1〜3節 |
| Viewerの設定、一覧JSON、約定JSONL、画像API | [データと閲覧形式](データと閲覧形式.md)・4〜6節 |
| 試行番号、容量、入力版、共通知見への移行 | [研究運用](研究運用.md) |
| 試行の記録を作る | [記録テンプレート](試行記録テンプレート.md) / [試行一覧](../study/README.md) |
| 原典へ戻る | [参考資料](参考資料.md)と各章内の直接リンク |

## 知見の状態

現時点で保存した内容は、外部資料から整理した基礎知識、隣接リポジトリで確認したデータ・形式、今後の研究用の設計案である。実データで収益性を確認した共通手法はまだない。

今後追加する知見には、確認日、元の試行または一次資料へのリンク、適用範囲、未確認事項を付ける。失敗例・反例も同じ目次から参照できるようにする。
