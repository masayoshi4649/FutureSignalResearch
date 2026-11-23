# 固定通知と価格行の再生

固定96の公開入力再用と97金融接続のコードです。新Source判断の再運転とは呼びません。停止元の本文と配置差は [由来と配置差.json](由来と配置差.json) を参照してください。

人工だけを検査する場合は `go test ./...` と `go vet ./...` を実行します。市場の54場TapeとHは、条件固定後に明示したCLIで実行するまで未実行です。詳細のAPI・範囲は研究計画と再現補足に記録します。

`BuildProduction` は旧先頭2場用のままです。別 `BuildSelectedProduction` は固定96完了記録 `33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483` の正式54gzipだけを許可します。gzip/許可集合/Scope以外のSource通知再構成と価格入力の計算本文は旧関数と同体です。旧関数を解除・再時刻化して別場へ適用しません。

`許可済み保存入力を作る.py` は一場を明示し、元96の公開通知、G0取消出典、ChartGridsと固定94のRaw/ATR部品から入力を作ります。全Last正値NK行、異常BBO、特徴Index/物理行、空Pを含むactive手法順、Force→grid→rawを保持します。Source/Features/助走は再運転しません。Receivedは固定loaderの価格時計複写で実受信時刻ではありません。新しい技法の未計算入力へ、このTapeを流用しません。

```powershell
# Rootによる対象・条件の固定後だけ実行する。値は明示した一場と新規出力へ置換する。
python -B -X utf8 scripts/固定通知と価格行の再生/許可済み保存入力を作る.py --run --session <場ID> --native study/00096_5分枠の順行反転と現在数量/成果物 --out <構築入力.json.gz> --proof <構築証拠.json>
# このフォルダを作業ディレクトリとする。Source再構成と旧P0八会計だけを確認し完成Tapeを保存。
go run ./cmd/selected --input <構築入力.json.gz> --completion ../../study/00096_5分枠の順行反転と現在数量/完了記録.json --out <新規Tape保存dir>
```

取消Originの不足・曖昧さは拒否します。実先頭2場では取消0なので、その境界は人工でのみ検査しています。新wrapperの2場接続は既存Scalar入力と正式96の2gzipだけを使い、旧wrapperのEvent全値と旧/正式P0全16会計の全文一致を確認しています。Raw再走査0・他52場本文/H市場0です。速度優位は未計測です。
