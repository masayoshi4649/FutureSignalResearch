# 正益経験分母版の実行先

最終の候補別44列・全セッション40列は本フォルダの二つの停止済みスクリプトで生成する。停止Refは`人工_停止版/停止.json`、SHA256は`20d9db6467a3baefca459fe2dca666c006f3afee604d50edd37da9ef46b79ff8`。

凍結READMEのCLI例には派生元`work/115損益CSVの出力`のパスが残っている。分母追加版の実行には次のパスを使う。凍結README・コード・停止は変更せず、この案内を後段資料として追加した。

```powershell
& 'C:/Users/masay/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' 'work/115損益CSVの出力_正益経験分母/出力する.mjs' <全70独立結果JSON> <SHA256> <未作成CSV先> --root-authorized
python -X utf8 'work/115損益CSVの出力_正益経験分母/CSVを独立再読する.py' --result <同じJSON> --sha256 <同じSHA256> --folder <CSV先> --output <新規確認JSON> --root-authorized
```

Rootの成功全70・840会計の明示解禁後に実行する。唯一の最終出力は候補別集計.csvと全セッション.csvの二点で、未定義比率は空欄、0取引場も保持する。経験分母はwhole_positive_positions、赤字率はwhole_positive_closed_negative / whole_positive_positions ×100。候補別は加算した分母から計算し、場別率の平均を使わない。

115の操作markerは前段で一度だけ成功している。`../115損益CSVの出力/操作markerの記録.json`のSHA256は`ee57f3cc87f6c7065533fb1fdd5b1c88854b73506b71bdae0a19c32d05217360`。この後段で追加発行はしない。xlsxは生成しない。
