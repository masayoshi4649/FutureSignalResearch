# FAR初回利益確定の再生

固定96の公開入力再用と97金融接続のコードです。新Source判断の再運転とは呼びません。停止元の本文と配置差は [由来と配置差.json](由来と配置差.json) を参照してください。

人工だけを検査する場合は `go test ./...` と `go vet ./...` を実行します。市場の54場TapeとHは、条件固定後に明示したCLIで実行するまで未実行です。詳細のAPI・範囲は研究計画と再現補足に記録します。

`Factory` は固定96と新97の金融を接続します。Observation/Session/QuoteStampは同native alias、NativeBatch/SourceIdentity/EntryCandidate/GateDecisionは全fieldを明示変換します。ABは各金融の現在余力から出る候補を固定96純式へ再評価します。旧採否は転記しません。

`Run` は人工用の全原行Snapshot連鎖観測を維持します。別 `RunProduction` は同じ配送順でこの重い観測を省略し、非空通知と全Tapeの前後不変、最終Book、旧P0八会計の全文照合を保持します。6人工の全96Bookと現在callback回数は両Runで完全一致しています。速度優位は未計測です。

新envelopeの `books` は空/H0×G0/AB×C0/C5×D0/D1の16口座、`gate_assessments` は `{key,ordinal,source,candidate,assessment}` です。candidateは当時の現在候補全文、assessmentは全Checksを含みます。旧96の対照・品質は `input96_provenance` 内の出典で、`source_reexecuted=false` と `charts_recomputed=false` を明記します。`P0_96_match` は新しく空97を運転した八会計と固定96の全文一致であり、Hの利益やSource再生成の証明ではありません。

Tape indexの形式は次のとおりです。`first2` は2026-09-21 Day/Nightだけ、`full54` は固定96の全54場を一度ずつ要求します。パスはindexからの相対又は絶対です。

```json
{"version":1,"stage":"first2","entries":[{"session":"2026-09-21_Day","path":"Day/tape.json.gz","sha256":"<完成TapeのSHA256>"},{"session":"2026-09-21_Night","path":"Night/tape.json.gz","sha256":"<完成TapeのSHA256>"}]}
```

```powershell
# このフォルダを作業ディレクトリとする。Rootの計画/条件/index固定後だけ実行する。
go run ./cmd/batch --run --stage first2 --index <Tape台帳.json> --condition ../../study/00097_初回費用後利益の全量確定/条件.json --proof96 ../../study/00096_5分枠の順行反転と現在数量/完了記録.json --out <新規出力dir> --workers 8
```

条件JSONは `試行`、`固定96完了SHA256`、`台帳SHA256`、`コードSHA256`、`市場損益を開く前の固定` を検査します。出力の完了記録は各場の16口座完了/P0全文一致と入力・コードの前後指紋を保存します。`source_rows`、`shadows`、`chart_grids`、`chart_end` 等は保存96の出典値です。未参加や退出後の仮想利益を計算しません。
