# 利益前ATR追尾を同じTapeへ接続する24口座

Source/Features/助走を再運転せず、固定97と同じ完成Tapeの11Scalar・公開NativeBatch・5分ChartGridを使う。H0は固定、Gate空/G0・AB×Risk空/R05/R10×C0/C5×D0/D1の24口座。金融は正式 `FAR利益前ATR追尾` をimportし、本文を複製しない。

旧97の `Config.Harvest` にRiskを偽装せず、RiskFactoryへRiskPolicyを別指定する。旧 `RunProduction` を独立八口座ずつ三回呼ぶ。三配送は同じ不変Tapeを独立金融へ渡すもので、Source判断を三回実行する意味ではない。新RiskのEntryCandidate/SourceIdentity/NativeBatch/GateDecisionを全field明示変換し、ABはその時の各候補から固定96純式を評価する。

`gate_assessments` は `{key,ordinal,source,candidate,assessment}`。全checksを保存し、candidate.at→実factory生成24key順位→ordinalでcanonical mergeする。G0はcallbackを持たないため、AB内は空/R05/R10→C0/C5→D0/D1の順となる。key/ordinal/at集合、callback回数、SnapshotIDと当時gridを照合する。全原行Book Snapshot連鎖は人工だけで、本番は旧RunProductionの省略観測を使う。

## 入力と出力

固定97完了SHA：`0d7111c41c4c25140be69fe8b06d0118496ddd6de3bc9ac7467ec2f01f6aef79`。固定96完了SHA：`33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483`。

新envelopeの主欄は `books`（24）、`chart_grids`、`gate_assessments`、`shadows`、`feature_config`、`source_rows`、`chart_end`、`quality`。後五欄は旧保存値である。出典を次に分ける。

- `input96_provenance`：旧97が記録した96/Source入力の出典。
- `input97_provenance`：正式97 gzip/SHA/完了証拠と旧比較scope。旧P0対96の証拠もこの内側へ置く。
- `tape_provenance`：実際に使ったTape path/SHA/capabilities。Source/原板/ATRの詳細由来は完成Tapeのprovenanceへリンクする。
- `source_reexecuted=false`、`charts_recomputed=false`。
- `empty_risk_97_match`：新98の空Risk/H0八会計を正式97H0と全field・除外0比較。旧P0へ対応させない。JSONキー順・数値表記を正規化するだけで、全fieldを比較する。
- `actual_run_complete`：24金融の完結。旧保存対照のtrueを新成功としてコピーしない。

CLIのindexは旧97と同じ `{version:1,stage,entries:[{session,path,sha256}]}`。`first2` は09/21 Day/Nightだけ、`full54` は固定96/97が共通に持つ54場全部、重複を拒否する。

```powershell
# このフォルダを作業dirとする。条件・index固定とRoot許可後だけ市場CLIを実行する。
go run ./cmd/batch --run --index <Tape台帳.json> --condition <98条件.json> --proof97 <97完了記録.json> --proof96 <96完了記録.json> --out <新規出力dir> --workers 8 --stage first2
```

条件キーは `試行:98`、`固定97完了SHA256`、`固定96完了SHA256`、`台帳SHA256`、`コードSHA256`、`市場損益を開く前の固定:true`。完了記録へindex/条件/両証拠/台帳/対象Native97/Tapeとコードの前後指紋を保存する。

## 人工のscope

停止prototypeの14手製Source/ATRに、固定96の手製A/B文脈を当時Quoteへ結合する。公開NativeBatchを直接Tapeへ保存する器具で、LedgerからのSource復元や原板からの指標形成を証明しない。Forceのnull配送列も保持する。元fixtureは変更しない。

14×24金融、空Risk112の旧97H0 API全時点/最終JSON、Run/RunProductionの全24最終・現在Gate回数を確認する。risk要求非0、Source予約・ATR・Forceとログ破損拒否を検査する。旧P0への偽装、半円差、未知field差も拒否する。人工は収益性の実証ではない。市場/Raw/98損益の実行は停止時点で0。
