# 167・追加七場の入力と純観測

2026-11-15。167の候補・条件・F0固定後に初めて対象7場の原本を参照した。候補方向はRootが非金融母集団完成後に別途封印し、その完了票を確認してから金融観測を生成した。このfolderでは候補選択・損益比較を行っていない。

固定条件SHAは `73e16eabfc3364a9e038d9697472abe50bb91fbba49b488dd0c8ed8d5eaea9f4`。汎用接続器・Go観測・数値adapterは各停止済Sourceを変更せず利用した。研究trialは167、部品版は166。

## 参照先

|用途|保存先|
|---|---|
|初回前固定と原本指紋|`F0_全段生成前.json`、`新七場の原本指紋.json`|
|1回の原板解析による48byte索引|`原板数値索引/manifest.json` と7個の `*.quotes.bin.gz`|
|非金融母集団|`入口母集団/完了.json` と出生台帳・当時100特徴・取得対応・物理取得・固定取得入力のgzip|
|非金融完成通知|`非金融の完了.json`|
|Root出生封印の結合|`F3前の候補出生封印参照.json`|
|両実側12幅4時計の純観測|`任意幅の純観測/manifest.json` と7個の観測gzip|
|探索器用の数値表|`自然数値表/任意幅配列.npz`、`自然数値表/任意幅識別.json.gz`|
|数値APIのcache参照|`生成の完了.json` の `cache`|

全7場を保持し、q0台帳4,125件、100特徴を生成した適格q0 3,608件、物理q1 3,250件。適格でないq0も台帳から除外していない。全RawのSymbolは仮説161120018と一致した。受理件数・品質は事前期待値を指定せず実測し、manifestの事前期待照合boolはfalse。Rawの事前statと全SHA・CRC・前後stat、CSVのSHA/statは照合した。

原本の物理ハッシュを前後に確認し、RawのJSON解析は各場の索引生成で1回だけ行った。後の特徴と先着観測は同じ数値索引を共有する。Clock文字列は索引timeからJSTへ再整形し、元CurrentPriceTime原文の文字列同体は主張しない。元Rawへはpath/SHAで戻れる。

## Rootの読取API

非金融は `--population work/167追加七場の入力/入口母集団`。

数値は `--numeric work/167追加七場の入力/自然数値表` と `--numeric-proof work/167追加七場の入力/生成の完了.json`。後者は `成功:true` とcacheの2ファイル指紋を持つ。`arrays166.load_table(directory, proof['cache'])` で読む。

caseは辞書順、配列はcase×BUY/SELL×12幅×4期限。保存labelは旧strictのまま、direction/known/exit_timeを保持する。観測済みtouchのIFD_FIRST主時計への射影はRootの固定コードで行う。未知金額0を確定損益0円として集計しない。

## 入力形式の初回停止

最初の実行は、最初の場のファイル名inventoryで生JSONLとgzipの二形式が併存し停止した。価格payload・SHA読取前だった。`F0_初回は二形式併存で停止.json`、訂正前driver、初回stderrを保持した。

Rootの指示によりgzip優先、gzipが無い場だけ生JSONLとし、driverとF0を再固定した。選択に価格条件を使わない。`入力形式の訂正.json` に旧/新driver指紋と理由を記録した。汎用Source・入口閾値・固定bookは変更していない。

`計画と生成を実行する.py --nonfinancial-only` はF2まで。Rootが非金融方向を封印した後、同じdriverへ `--financial-only` を指定して観測・数値化する。既存成果物へ上書き再実行せず、失敗・段階票を残す。
