# 96の保存会計と技法gateの独立照合

固定95の出生一回・5分枠と固定94の共通金融をSHA pinして再用する。旧95/94の関数やglobalは変更しない。新しい売買や原板からの金融再生は行わない。

## 再用と新しい検査

| 部分 | 処理 |
| --- | --- |
| 金融/半円/配賦/所有/保護・MTM保存点 | 固定94 `verify_book`を再用。旧95と同じ専用namespaceでSource検査を結ぶ |
| Source出生/取得/取消/比例返済/cap | 固定95 `verify_source_b/source_at/available_at/pending_quantity`を再用 |
| 5分枠の採否 | 固定95 `verify_grid`の最小派生。金融の元資格・量計算を維持し、適格かつcap>0の出生へだけgateを追加 |
| 現在技法 | `技法の保存照合.py`が公開保存入力からA/B/ABの全checksとdecisionを独立に計算 |
| 対照G0 | 指定の追加fieldを除く投影ではなく、旧95 B5Q四口座の全fieldへ直接一致 |
| 実現額/PF/u/W赤字額/DD | 固定95診断の完結玉加算・費用・PF・保存極値のflat連結を再用 |
| Viewer | 固定94/95の実Fill変換。mini倍率100、指定片道38.5円、C5追加滑りを別運転のまま保持 |

金融の投影では96の`config.gate_policy`と各Opportunityの`gate`、95の追加5field、外keyだけを明示的に除く。注文/約定/PositionのID、時計、実採否、費用、Source通知を書き換えない。旧関数を通すための偽受理イベント・未来時刻化は行わない。

G0は実configでGatePolicy空（JSONでは省略）。`Actor設定.gate_policy`は空文字、`gate_label`は表示名`G0`に分ける。A/B/ABは接頭辞付きkey。全16口座がB5Q/P0、費用C0/C5と遅延D0/D1を分ける。

## 分母と因果

quiet・Force・Source pending/cancelled/完結/返済予約・最新気配・片側空きの順で、旧金融の採否を先に検査する。gateを呼ぶべきでない候補の判定追加と、適格候補のgate欠落を拒否する。一度受理/失効した出生を後枠へ戻さない。未知と既知不成立の混在時は三値ANDの既知否定が優先され、ABは既知成立優先のORとする。

`chart_grids`は全金融枠と同じ列で1copy、`snapshot_id`で当枠の公開入力へ結ぶ。`gate_assessments`は`(key,ordinal)`とSourceIdentityから当時の適格出生へ一度ずつ結び、孤立・重複・欠落を拒否する。Opportunity.gateの全値を独立結果と比較する。条件計数は**各Actor別の実callback回数**であり、費用/遅延を独立市場標本へ水増ししない。政策ごとに先行保有と予約が変わるため、全実新規集合の包含は仮定しない。

Current.SourceIndex/候補Quote.IndexはFeaturesの連番。Chart.LastInput.Indexは受理全NK行の連番であり、同一とはしない。Currentと候補のTime/価格/物理SourceLineは完全一致させる。ObservedClockはdrainの上限、available_atは再生上の論理公開時計で、実受信時刻の証拠とは呼ばない。板数量/OFIを生の約定出来高と呼ばない。

PFは完結玉の最終費用後純額の正額/負額絶対値。u/W正益後最終赤字額は該当玉の最終純額合計で、含み益からの減少額とは異なる。DDは保存済み場内max/min/DDをflat場境界で連結する。全原板からの極値再生成やチャート形成の独立再計算を、この保存監査の成功へ含めない。未参加/決済後の仮想利益は計算しない。

## 再現

Go型人工（手製Source/Current/技法/ATR）を先に検査する。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 `
  work/96保存監査案/人工と破損を確認する.py `
  --fixtures work/96結合人工/初回 `
  --out work/96保存監査案/Go人工の照合_停止版.json
```

許可されたNative接続2場だけの保存検算例。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 `
  work/96保存監査案/集計.py `
  --run work/96実行/接続2場 --limit 2 `
  --baseline study/00095_5分判断と開始30分見送り/成果物 `
  --baseline-proof study/00095_5分判断と開始30分見送り/完了記録.json `
  --out work/96保存監査/実2場_停止版
```

出力先は新規だけ。54場はRootの許可後に`--limit 54`で別保存先へ実行する。正式95と96の金融/core/条件は変更しない。

## 人工と接続範囲

6scene/96口座（計72非0）と純Go120件、三値AND手計算9件を照合する。元slotの変更、cap11、半円費用、Source返済量、check反転、known数値0、必要判定の欠落/重複/孤立、現在特徴の原行違い、未来snapshot等、72破損を拒否する。全16口座が人工のいずれかで非0取得することを確認する。

人工には旧95正本の擬似指紋や架空の自然Shadowを補わない。新A/B/ABの非0金融はGo結合人工、旧95全文対照は実接続G0で別々に確認する。
