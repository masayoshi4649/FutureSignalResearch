# 98初期ATR追尾の独立金融監査

試行98の独立監査。市場損益を算出する前に人工を確認した。固定97の独立金融`ab7e95…`とTape接続`31fdf1…`をSHA参照し、Source・一回枠・現在純技法・予約・次気配約定・費用・MTMを再用する。Go金融計算器は呼ばない。

`RiskPath`はrisk空/R05/R10 × Gate空/AB × C0/C5 × D0/D1の24口座。新規が実fillした同原行ATRを0.5/1倍して20..125へ固定し、未知なら125を永久固定する。初期peak0を観測値にしない。利益前だけ非緩和床を観測し、strict u>0でHへ不可逆に移る。初期riskはSource後の未予約量だけへ専用point/理由で要求し、既予約riskを利益化後に撤回・Hへ付け替えない。

新しいPosition/Order/metrics fieldは最終全文比較から落とさない。旧APIの初期化に限って設定と新counterを射影し、期待注文IDは新Keyのまま独立採番する。新counterは正数時だけ出すomitemptyも検査する。空riskは固定97のH markを直接呼ぶ。

公開API：

- `inspect_fixture(value)`：Go型手製steps/timers/grids/events/actorsの24金融を独立再構成。ABは明示の常時allow人工で、自然技法成立を主張しない。
- `inspect_tape(tape, new98)`：固定97と同じScalar11/Source/Force/Gridを24金融へ配送。`books`・`chart_grids`・exact5tag `gate_assessments`を持つ新保存を受け、当時の現在候補から固定96純式を再計算する。Key順はrisk空/R05/R10→Gate空/AB→C0/C5→D0/D1。返却件数は全検査detailsの24件へ明示対応する。
- `compare_no_risk97(new98, old97)`：新8口座を旧97H0へ除外0全文比較する別対照。正式baselineと手製API baselineはscopeを分け、未提供の正本を補完しない。

Goの配送名`force`を旧監査APIの`timer`へ対応し、既知4配送列のnil slice（null）だけをGoと同じ空配送（[]）として扱う。値・位相・時刻・Source量・未知fieldを捨てず、元入力は変更しない。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR利益前ATR追尾の監査/初期ATR追尾の金融照合.py `
  --fixtures work/98初期ATR追尾案/人工/停止版 --out work/98金融監査案/再現_API14.json

& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR利益前ATR追尾の監査/productionを確認する.py `
  --fixtures work/98再生接続案/人工/初回 --out work/98金融監査案/再現_production14.json
```

停止人工の範囲は別々に記録する。

- 常時allowの手製14場面×24＝336非0会計、649,800照合差0。幅/位相/未知固定/床/H移行/point分類/同原行fill等18破損を拒否。
- production手製14場面×24＝336非0会計、717,240照合差0、Force14配送、現在純技法168。NoRisk最終112会計を旧97H0 APIへ除外0全文比較。純判定/Source位相/記録順/欠落等8破損を拒否。
- 取得ATR境界128件は小型summaryから幅/既知/取得Quoteを独立算術で比較。Force32系列・288 snapshotの旧97全文一致はGo停止の由来参照。未保存の全call/金融本文までPythonが照合したとは呼ばない。

両14場面は同じ手製市場波形の用途違いで、独立市場標本や自然Source/ATR/チャートの原板形成証明へ合算しない。原板・市場・98損益・未参加/退出後仮想利益の実行0。旧97完了`0d7111…`と固定155は変更しない。

## 市場の配送と成果物

上の「実行0」は人工を停止した時点の範囲。[試行98](../../study/00098_実建値からの利益前ATR追尾/README.md)の正式実行状態とは区別する。金融の固定条件は183コード、以下の集計・表示・報告は事後処理として別指紋で固定する。

- `市場Tapeを照合する.py`：`--index --run98 --condition --out --stage first2|full54 --workers 1..8`。固定台帳・完了・前後指紋を確かめ、全24会計と旧97H0八対照を独立計算へ渡す。
- `集計.py`：成功した全経路独立監査を同じNative指紋へ結び、圧縮Native・結果・一覧・約定を保存する。Source/H/Riskは別々の要求・約定回数と枚数を記録する。
- `表示監査.py`：`--run` は保存会計の結合を確認した後、既存8092の全資源・全約定へ照合する。`--catalog --result --out` を明示する。Viewerを起動・停止・再設定しない。`--self-test` の人工は通信代替として分ける。
- `報告.py`：成功した保存・独立・Viewerと固定した計画から報告を生成する。`--run` と `--check`、7入力 `--result --audit --viewer --condition --plan --readme --settings` と `--out` を使う。REPORT98 markerから原計画をbytes復元し、55×9・39設定・24評価を維持する。

保存例はリポジトリルートから実行する。出力は新規フォルダを使い、独立監査が未完なら進めない。

```powershell
& 'work/venvs/technical-tree/Scripts/python.exe' -B -X utf8 `
  'scripts/FAR利益前ATR追尾の監査/集計.py' `
  --run 'work/98実行/正式54' --audit 'work/98実行/正式54_独立照合.json' `
  --condition 'study/00098_実建値からの利益前ATR追尾/条件.json' `
  --index 'study/00098_実建値からの利益前ATR追尾/正式54Tape台帳.json' `
  --out 'work/98再現/成果物' --limit 54
```

指標・Source・金融を再生成したとは呼ばず、成果物の算術、全経路金融、表示の各検査を分担する。手数料・仮定滑り・利益前後の実損失・PF・DD・回数枚数を評価し、未参加や退出後の仮想利益・回収率は算出しない。
