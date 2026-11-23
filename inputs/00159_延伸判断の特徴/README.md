# 159：延伸判断時点の固定特徴

[判断時点の特徴.json.gz](判断時点の特徴.json.gz)は、158で固定した837物理case・924所属・73場を維持し、各case×H60/SESSIONの1,674行を残す。977行に最初TP125のgateがあり、残り697行はgate/特徴部null。977はcase×期限の票数で、新しい取引回数ではない。共通87を所属別に物理二重計上しない。

|対象|bytes|SHA256|
|---|---:|---|
|gzip物理|3,600,073|`b7be610367196246af4125cabc10ea46157d4068896d29c35d0939084b41a148`|
|解凍JSON|33,662,878|`3ac97f2372c3c58b5c0e2584e0d72b27f08f3a50dec6c2cfcfe40e85db63fe7e`|

由来は[158出口結果](../../study/00158_複合技術で出口の役割と局面を切り替える/成果物/出口結果.json.gz)（物理`70a4c3178206bbb3c8641901c7515f2121da11c28403b88c3f8e6f93cc0baa6c`）と[158特徴manifest](../00158_複合技術特徴/特徴/特徴の確認.json)（`a6dce32eb35102d95f44647d0a10811bf13ed6e36f46b08ef0956c52bb783d11`）。元147 canonical OHLCVと122旧背景公表の時計を継承する。大入力は再複写していない。

C0=`F125S125`の`trigger.reason=take_profit`原行をqueryとし、全D0/D1・費用C0/C5の最初Quote全値一致を確認する。ctxはtime/index/source_lineの全てがquery以下だけを採り、query時刻で期限切れをunknown/nullへする。1分End+180、背景は旧Sourceの早いEnd+width+60期限。未知から古いknownへ戻らない。149個の物理特徴はside投影・採否・ラベルを含まず、入口/所属/時計はlookup metadataとして別に残す。

[抽出完了票](判断時点の特徴.json.gz.完了.json)、[159正式再現資料](../../study/00159_延伸する局面を複合技術から学ぶ/再現資料/README.md)、[159実行条件](../../study/00159_延伸する局面を複合技術から学ぶ/実行条件.md)からgzipを開かず由来・再現コード・限界を辿れる。snapshotの保存確認はCRC/両SHA/全149列の形と非未来/TTLを扱い、最初TPのRaw別再生や149式の別再実装とは区別する。
