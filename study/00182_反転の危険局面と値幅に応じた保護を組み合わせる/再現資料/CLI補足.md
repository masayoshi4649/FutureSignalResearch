# 182の再現CLI補足

[保存済み再現資料](README.md)の復元を完了した後の実行例。Source・条件・保存索引は変更しない。

## 復元後の実行例

リポジトリルートで実行する。下記の型付き入力出力先は未作成の `work/182再実行` を想定する。同名入力への上書きを禁止しているため、既存なら別の作業名を用いる。

既定の旧73特徴読込は151の特徴専用cacheを使う。cacheがない場合は[181の正式148射影を使う実行例](../../00181_反転確認と利益保護を分けて改善する/再現資料/README.md)を用い、例の `target` を `work/182局面と値幅の改善/実行182.py` へ替えて最初の再生を行う。同体の100特徴・q0・場順SHAを確認してから実行する。Sourceを編集する必要はない。正式射影との内容一致は確認したが、182全28組のcache隔離再実行を完了したという意味ではない。

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$researchPython = 'work/複合テクニカル学習環境/Scripts/python.exe'
& $researchPython 'work/182局面と値幅の改善/実行182.py' --resume
& $researchPython 'work/182局面と値幅の改善/比較を集約する.py'
& $researchPython 'work/182局面と値幅の改善/閲覧候補を保存する.py'
& $researchPython 'work/182閲覧資料/型付き入力を作る.py' --input 'work/182局面と値幅の改善/保存する候補.json.gz' --mapping 'work/182局面と値幅の改善/閲覧名.json' --output 'work/182再実行/型付き入力.json' --proof 'work/182再実行/型付き入力の確認.json'

$researchNode = 'C:/Users/masay/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$researchDependencies = 'C:/Users/masay/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
& $researchNode 'scripts/損益CSV/候補別に出力する.mjs' --input 'work/182再実行/型付き入力.json' --output 'work/182再実行/CSV' --proof 'work/182再実行/CSV検査' --dependencies $researchDependencies
```

Source.zip内の固定7案再生成runnerは、全28組を計算し直さずに保存候補の同体を点検する経路である。正式索引の21期間packのSHAと照合し、入力キャッシュが残る点も監査票へ記載する。CSVの新しい生成先と既存42本の本文は比較できるが、生成時刻などを含む補助票のbyte同一を要求しない。
