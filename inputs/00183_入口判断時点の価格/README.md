# 判断時点q0の価格

NK225の純入口183で、当時のEMA価格・BB帯端・突破端を固定するための小型入力。後の取得q1や金融成績を含まない。

`旧73_q0.npz`、`追加7_q0.npz`、`本日1_q0.npz` に `last/bid/ask/time/line/normal` を保存する。各 `.json` は100特徴の意味内容SHA、共用価格索引manifest/場別SHA、生成Source、NPZのサイズ/SHA、元q0行との照合件数を持つ。原板・48byte価格索引は複製しない。

元100特徴の `q0_index` で共用163/167/180の索引行を取り出し、元行番号・時刻・場・限月を照合した。`time` は既存入力の価格時計であり受信時計ではない。正常BBOでもmini実約定を保証しない。

生成Sourceは [183新規Source](../../study/00183_単純IFDで両指数の入口と損失安定性を検証する/Source/NK225/新規Source.zip) 内の `work/183単純IFD検証/当時価格183.py`。親Sourceを復元した作業コピーで `python -X utf8 work/183単純IFD検証/当時価格183.py` を実行する。既存入力があれば元Source/入力/内容SHAの一致を検査する。

| ファイル | byte | SHA256 |
|---|---:|---|
|旧73_q0.json|24512|`333dce8ba461c7614618e386ff147d66ebd976d5dd1b8d33fdbf44776e9004c9`|
|旧73_q0.npz|308408|`b9d0d0712d22dbd0f3b610188b410fc698f90ba0b629f392afbffb7aa47aea2b`|
|本日1_q0.json|1208|`d76300d6077e002a5eed68046081c018fa2024bab3c81c04d8ed4a27d0f3cb31`|
|本日1_q0.npz|4841|`5cbe09f12265128b1d2ae42e8031a5c651b037aaba51d5726bba6b0368e08cf1`|
|追加7_q0.json|3281|`c98867b7af219fb0346944d36680b0c0aa4386474d9f422e7513b40b4f5ed93d`|
|追加7_q0.npz|33931|`581d7acd8721c85ef9b0c4e959fc250576fb18c8fe7fd232009d13db84e38416`|
