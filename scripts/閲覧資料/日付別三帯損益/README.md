# 日付別三帯損益CSVの生成

172の固定取得・共有金融から、Day171固定／Night B05_11の各40日を集計する。新しい戦略の探索ではなく閲覧形式の追加なので、試行番号を採番しない。

リポジトリルートで `集計する.py` を実行し、`work/172日付別三帯損益/型付き入力.json` を作る。Python3.14.3／NumPy2.5.4を使用した。Rawや大量中間データを複製せず、正式172ZIPと恒久共有163/167を直接読む。

```powershell
python -X utf8 'scripts/閲覧資料/日付別三帯損益/集計する.py'
```

CSVの著作は提供環境のNode24.22.1／`@oai/artifact-tool`2.8.157を使用。Sourceを同じbyteのままworkへコピーし、そのworkに提供runtimeの `node_modules` をJunctionで接続して実行する。Source自身はリポジトリルートを現在ディレクトリとして読む（第一引数によるroot指定も可能）。依存関係はリポジトリへ複製しない。

```powershell
Copy-Item -LiteralPath 'scripts/閲覧資料/日付別三帯損益/CSVを作る.mjs' -Destination 'work/172日付別三帯損益/CSVを作る.mjs'
node 'work/172日付別三帯損益/CSVを作る.mjs'
```

`outputs/00172_日付別三帯損益` へCSV3つと作成確認JSONを保存する。既存ファイルへの上書きは拒否する。再生成は別checkout等の未作成出力先を使い、固定成果物を削除しない。xlsxは生成しない。

日付は内部では数値日付として著作し、CSVではユーザー指定のISO日付へ戻す。全セルの元入力一致、既存172の帯別合計一致、三表の表示を確認。別担当が取得参照と共用数値から独立に各日を再集計し、最終CSVへ照合した。
