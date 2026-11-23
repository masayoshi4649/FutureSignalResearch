# 133期限別集計器の準備

2026-11-11、自然金融未実行。`work/133期限別の集計/`の条件・計算・CLI・人工検査を準備し、編集停止した。主はL1。O0/L0はSource L0集合、O1/L1/R1はSource L1集合だけを使い、statsへ別集合を渡さない。

人工8群で、可変2件対3件・全73場と0取得・0known・既知0円・Last金額null・前48/後25・適用外policyセルnull・異時計ペア禁止・主と同群O1だけのbootstrap・未来phase/結合改変・F1不足拒否を確認した。準備票は `work/133期限別の集計/準備の確認.json`、SHA256 `d43dbd7abb5037b0f5a3688ba8f5e2623ae95a61b3de356ff73aa5fc1cfdaf39`。

Root完成の固定取得入力と方向metadataへ非金融接続も行い、全158取得（L0=79/L1=79）・全73場、全ID/元方向/取得Quoteと保存方向式の一致を確認した。[metadata接続.json](metadata接続.json) SHA256 `dccacb31901e17fa3d54c18646c9f1741a59a492801aeb159d44fdc01dd9bec5`。この接続は新しいoutcomes・損益を読み込んでいない。

CLIは `集計する.py --f1 PATH --f1-sha256 SHA --fixed-input PATH --fixed-input-sha256 SHA --metadata PATH --metadata-sha256 SHA --result PATH --result-sha256 SHA --output-dir NEWDIR`。Root F1へ固定入力/metadata/条件/計算.py/集計する.py/人工検査.pyを含める。自然Go結果はF1後にRootが明示するSHAへ固定する。SOURCESには旧124算術/旧正逆/旧124集計/旧131集計の指紋を宣言した。

自然実行時には、L0旧79の全4stream/全outcomes/取得時計と、旧対照の全140集計条件へ同体assertする。不一致なら3表を保存しない。出力は比較300×29、入口（L0+L1可変）×54、全73×67。全場最低1取得と主L1のH60±125到達済み70%を両方判定し、未知を0円や不参加場の除外へ変えない。

元124算術をSHA固定のままimportし、政策別のsubsetとselectedだけを差し替える。bootstrapの内部名O0は専用moduleだけで同群O1へ対応し、出力名もO1差へ変更する。L0/L1の時計が異なるcaseをペア化しない。Raw FileRefのpath/shaを必須照合し、任意のbytes/mod_time_nsはstat_before.bytes/mtime_nsへ対応させる。

新しい自然金融集計、Raw走査、入口条件・閾値探索、CSV生成は担当していない。自然結果の検算と正式保存はRootが実行後に行う。
