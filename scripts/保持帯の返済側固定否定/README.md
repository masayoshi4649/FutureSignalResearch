# 保持帯の返済側固定否定

[試行85](../../study/00085_保持帯の返済側固定否定/README.md)のオフライン検証コード。[計画](../../study/00085_保持帯の返済側固定否定/検証計画.md)と[固定条件](../../study/00085_保持帯の返済側固定否定/条件.json)を参照する。固定84C0の複合入口に対し、保持帯off/onと追加価格時計0/1秒の4会計を比較する。内部金融ラベルはS0G1、G1量計画・費用・100microは共通。

Go 1.24.2、Python 3.14.3、Matplotlib 3.11.2、PowerShell 7を使う。CGO無効環境でrace検査は未実施。go.mod/go.sumと固定80..84・兄弟SessionTradeExecuterの依存を条件へ記録してある。実発注は行わない。

## 再現の入口

ルートPowerShellから新規のwork領域へ実行する。固定済みの正式成果物は保持する。

```powershell
go -C scripts/保持帯の返済側固定否定 test ./...
go -C scripts/保持帯の返済側固定否定 vet ./...
New-Item -ItemType Directory -Path work/85再現 -Force | Out-Null
go -C scripts/保持帯の返済側固定否定 build -o ../../work/85再現/batch85.exe ./cmd/batch
& scripts/保持帯の返済側固定否定/ネイティブ実行.ps1 -OutputRoot work/85再現/実行 -ExecutablePath work/85再現/batch85.exe -ValidateOnly
& scripts/保持帯の返済側固定否定/ネイティブ実行.ps1 -OutputRoot work/85再現/実行 -ExecutablePath work/85再現/batch85.exe
```

[ネイティブ実行.ps1](ネイティブ実行.ps1)は固定exe・台帳・金融15のSHAを照合し、非表示の別プロセスへ引数を分けて渡す。起動PID、標準出力/エラー、実プロセスから取得した終了コード、exe/条件/台帳の前後SHA、66場の保存数をworkへ残す。`-ValidateOnly`は起動しない読取確認。全66場には種の準備時間も含まれる。

会話の監視handleが失われても、起動証拠の計算PIDをOS上で確認する。記録ファイルや観測タイムアウトだけで停止と判断せず、稼働中の同じ計算を重複起動しない。終了コード・保存数と、その後の数値監査を別に確認する。

## 集計・独立照合

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/集計.py --input work/85再現/実行/全66場 --out work/85再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/原板監査.py --results work/85再現/実行/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/85再現/原板監査.json --workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/基準と保存判断の照合.py --input work/85再現/実行/全66場 --baseline work/84実行/全66場 --out work/85再現/基準と保存判断の照合.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/表示監査.py --catalog work/85再現/成果物/一覧.resources.json --result work/85再現/成果物/結果.json --out work/85再現/Viewer監査.json --workers 8
```

旧84全66場は固定84の再現手順と正式結果の本文SHAへ結ぶ。表示監査は既存Viewer API（既定8092）を利用し、再起動はしない。Viewerのresource_rootに新規成果物が含まれる環境で実行する。

- `集計.py`：全264会計を固定80のcash_checkへ結び、最終flat・現金・粗損益・費用を確認。Viewer用ラベルだけH0G1/H1G1へ写す。
- `基準と保存判断の照合.py`：旧84C0と共有snapshot、H0全旧会計132件、要求時hold全出典、各片hit時点、金融/方針判断を照合。共有grid・玉診断のcanonical SHAを出す。
- `原板監査.py`：所有・次適格板・初回益・ATR/G1/保持帯床・同原行予約を原板から再構成。候補供給枠だけ要求SourceLineを実原行time/index/Bid/Askへ結び、正spreadと当該行の出現を確認。
- `表示監査.py`：264資源の全約定・最終flat純額を既存APIへ結び、通信未完と数値差を分ける。
- `レポート.py`：11明示正本を全件成功の証拠・固定SHA・canonical内容へ結び、READMEと設定の結果マーカーだけを生成又は同値確認。原板・新売買・API利用は0。

## 人工と範囲

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/基準と保存判断の照合.py --self-test
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/監査確認.py --fixtures work/85Go正式化/非0人工_2 --out work/85再現/原板人工確認.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/レポート.py --self-test
```

原板人工は12場面48会計の手製quoteを原板形式へ接続するもので、全25/49定時のcash_check完了ではない。市場の全66場を使う正式集計で完結検査を行う。保存人工の全66/2442/132は合成データであり、本物66場の検査と区別する。

元のE08出生・EMA/ATR系列を別実装した証明ではなく、保存evidenceとの出典結合とその後の原板規範を検査する。hold出生の物理原行を現在の公開metadataだけで直接同定しない。詳細な停止証拠・11入力CLIは[再現補足](../../study/00085_保持帯の返済側固定否定/再現補足.md)へまとめる。


## 出口差診断の再現

[出口差診断.py](出口差診断.py)から、[全玉対比Markdown](../../study/00085_保持帯の返済側固定否定/出口差診断.md)と[小型JSON正本](../../study/00085_保持帯の返済側固定否定/出口差診断.json)を作る。

完成した結果.json・取引診断.jsonl.gz・定時判断.jsonl.gzと固定台帳を明示する保存後の観測。新金融判断・市場再生・閾値探索は0。上書きを拒否するため、新規work出力の例を示す。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯の返済側固定否定/出口差診断.py --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --result study/00085_保持帯の返済側固定否定/成果物/結果.json --trades study/00085_保持帯の返済側固定否定/成果物/取引診断.jsonl.gz --grids study/00085_保持帯の返済側固定否定/成果物/定時判断.jsonl.gz --out-json work/85出口差再現/出口差診断.json --out-md work/85出口差再現/出口差診断.md
```

同実新規/取得変更/片側参加を正式集計へ結び、救った損失・失った勝ち・両負悪化と正益前後を分ける。差0の同実入口も全件保存し、保持帯返済はclosedの保存理由に対応する実返済枚数で識別する。hitや損益符号から推測しない。集計の宣言と保存玉の観測であり、原板・保存判断・Viewer完了の証拠を代替しない。
