# 153の先行高安入力

先行15・30・60分高安の非金融入力を一度だけ恒久保存した。153の戦略Sourceや採否・金融はここでは実行していない。全73場・全40,544q0、適格35,339q0、全43,124配送barを残す。取得・売買選択・参加頻度を表す件数ではない。

正本は[先行高安の入力.json.gz](先行高安の入力.json.gz)。5,238,666 bytes、物理SHA256は`2c020fed5b336ed0b417d8e72a07c6336ea475b09b9a2ff37f26ec4ce4d56bf8`。解凍116,923,668 bytes、解凍SHA256は`8e145275dda385e4c2f87500978716654d10efb0903a4011f2bcc304a7906b14`。元work生成物と保存先の両gzipを全完読し、CRC・解凍SHA・サイズと物理bytesを照合した。plain副本は保存しない。

## 比較域と未知

各q0の最新配送slotをrとし、窓は厳密な`[r.Start−W,r.Start)`、W=15/30/60分である。r自身と前場を含めず、欠測を飛ばして古い足で本数を補わない。旧可用性調査のrを含む`[r.End−W,r.End)`とは別測定である。

全Wslotが配送済み・非Missing・closed・価格既知の場合だけ`known=true`としてHigh/Low、同値極値の市場順で最初のbar ID/Start/End、幅・ゼロ幅を返す。不足・欠測・未closed・価格未知では値/極値参照/幅/ゼロ幅をnullとし、理由と各countを残す。観測高安へのfallbackはない。量未知・BBO異常を価格高安の既知性へ混ぜない。r自体の未知と先行窓の未知は別に保持する。

| r除外窓 | 全q0の既知 / 未知 | 適格q0の既知 / 未知 |
| --- | ---: | ---: |
| 15分 | 28,734 / 11,810 | 26,005 / 9,334 |
| 30分 | 24,528 / 16,016 | 22,127 / 13,212 |
| 60分 | 19,547 / 20,997 | 17,323 / 18,016 |

## schemaと利用

schema IDは`prior_time_range_v1`。top.scenesごとにsession/contract/start/continuous_end、bars、rowsを持つ。barの最小正本を一度保存し、各rowはr_ref・4slot ID・当Raw配送IDを参照する。全window bar ID配列や大量のCSV refsを反復しない。

- `scenes[].bars[]`：id/start/end/available_at/stamp、price_known/volume_known/closed/missing、価格既知時のohlc（open/high/low/close）、未知時はohlc=null。
- `scenes[].rows[]`：event_id/eligible/quote_ref、q0、r_ref、slot_refs、delivered_refs、prior_ranges。r_refを同場bars[].idへ結合する。
- `q0`：time/index/source_line、任意clock、last/bid/ask、各known、quote_ok、normal_bbo。正常Bid<Askと個別価格既知を区別する。
- `prior_ranges`：キー`15`/`30`/`60`。from/to/duration_seconds、expected_count/slot_record_count/observed_count/closed_count/price_known_count/missing_count/absent_count/before_session_count、known/unknown_reasons、high/low/high_first_ref/low_first_ref/range_points/range_zeroを持つ。

最新/全配送/4slot refs、全Quote、End/AvailableAt/Stampとq0の時刻・index・物理行を全件照合した。同Raw catch-upは全配送後のそのq0で利用し、以前から既知だったとはしない。市場時計・モデル公表・価格時計から実受信を復元したものでも、取引所の全約定網羅や真の市場高安を保証するものでもない。

## 由来と再現

原典は[147の共有Source](../00147_中位価格位置と実体回復/README.md)（gzip SHA `b99c49f06fe7e2306e59733b1cff26e3bb351f64edee220c98bc30b62c016d77`、解凍`d42d25ec0fe41e8358c1227fd71b4377ffa90c96a8cf582f1ee4537ebf455d63`）と[148出生台帳](../00148_全1分入口母集団/README.md)（gzip SHA `9d589488bca8e83be3fd23ed230b6f7cae176acbbe96dd2d04a62d3bbfb6e753`、解凍`4f4d3ce3a652170d5d5f15941b591493592d5816bb0985c2e70c86b14323b219`）だけである。今回この原典2gzip・100X・Raw・旧151/152は複写又は変更していない。

[再現資料ZIP](先行高安の再現資料.zip)には、生成純部品・生成器・条件・作者人工7群/構文/CLI準備、Root独立人工3群、自然生成の確認、独立全件監査の最小7点、保存器の計19小点を元repo相対pathで一度格納した。[格納索引](先行高安の再現資料_索引.json)に全member指紋と共有入力参照を残す。元2入力と新入力自体はZIPへ入れない。全格納bytesとCRCを再読した。

再現時はZIPの小源を元相対pathへ復元する。共有2原典を元pathで参照し、ZIP内`条件.md`のCLIで**新しいwork出力先**へ生成する。保存済みの本入力を上書きしない。独立監査はそのREADMEに従い新しい監査folderで行う（コード内に記録された当初のwork生成pathは、保存正本の同体bytesへの検証用参照を用意する）。今回は再生成・再監査を追加実行せず、停止した結果の同体保存を行った。

独立全件監査は作者算術をimportせず全6,990,803末端を一致確認した。主票SHAは`a539ee938669f7bcae875196a150eaa86d51b5cafafc7de0722dcd0925b57997`、停止票SHAは`9ee9c3fa5bff7648838e475799ddeeacefb027ac543f34a6ef9015492dbc7f6c`。100特徴、支持抵抗の効力、先着70%、金融成績の独立検算ではない。

[保存確認](入力の保存確認.json)。確認日：2026-11-12。


## 153新生成3JSON（F1後の追加）

元の先行高安入力案内は全bytesを保持し、この節だけを追記した。新モデルはない。

| 保存 | 物理bytes | 物理SHA256 | 解凍bytes | 解凍SHA256 |
| --- | ---: | --- | ---: | --- |
| [q0の判断.json.gz](q0の判断.json.gz) | 15,652,443 | `382fbf885c14f974eb86d830cc784d907ddb85d395b97d87aa38be27e444f4a5` | 848,212,229 | `4afc6f1f0cd2a37804e610ab16493c34866000dd0ec6ae7b2230690514ed6d7a` |
| [選択対応.json.gz](選択対応.json.gz) | 102,440 | `3ffdab0cfd846e250473206b2e55c9cd45a8b18e1c9a73285537319aa1e99334` | 2,391,872 | `bf5a29225a69e4e8837df9d8b34f263adb59f43ee70908e7668cc35a1a97a758` |
| [選択の確認.json.gz](選択の確認.json.gz) | 1,865 | `1f0a71a67dcce2c0f3834c0a06d9f6855d4e0b9d5984b2f902e14c6e43a8e4b8` | 4,699 | `1fbf5d2a2c7bf518e06ee938ecb697e5b205f73ac787ec15260232ad3571420d` |

各gzipの全CRC/解凍SHAを再読照合。先行高安/148の100特徴・観測/152固定対照は再複写していない。[正式結果](../../study/00153_長い先行域から順行と反転を独立出生する/README.md)・[保管索引](../../study/00153_長い先行域から順行と反転を独立出生する/保管索引.json)を参照する。
