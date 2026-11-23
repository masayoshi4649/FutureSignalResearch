# 発動前の反対端否定の保存表示

[試行68](../../study/00068_発動前の反対端否定で条件を取り消す/検証計画.md)の正式結果だけからREADME／設定と結果を生成する。旧67G0/G1保存92運用と新N0/N1の92運用、Viewer184資源を比較する。正式生成はrootの主・保存監査成功通知後だけ行う。

旧67と同じ60特徴、旧65U0三木と三回収集計、教師、純side・role・ATR/D、凍結した3分足高安と15分寿命を維持する。新fit0・新木0・新特徴算術0・新予測0・新独立追尾回収0。旧木は直接参照して全閾値・葉・支持・障壁score・回収平均・MSEを表示し、全60特徴と55手法×9尺度の版5表を保持する。旧教師と回収は即時入口の参考で、今回の条件発動・否定を学習済みとは呼ばない。

追加は発動前だけの反対端否定である。買いLast<=low／売りLast>=highを等号含め否定とし、設定否定は未登録WAIT、監視開始後の前提否定は登録未約定。どちらも価格取消で品質注意ではない。正常BBOかつ有限正Lastで観測し、監視gap>300秒の観測不足は従来どおり先に処理する。新規発動後のpending・保有へこの否定を適用せず、取消後の復活・同枠再登録・自動反対新規はない。

否定比較の十項目を全表示し、旧125の除外だけでなく旧250の取り逃がしも残す。非否定の独立ラベルはpolicy以外全属性一致、残存仮約定の時刻・原行・価格・結果が同じなので、両約定の平均追随・取得遅延は0（対象なしnull）。実一枚の占有が変わるため、仮約定の包含を実戦略へ転用しない。旧Gにも未発動を含む同じ保守式を適用する。

主待ち=WAIT／全予定枠、保守=(WAIT＋判定不能＋条件登録後に実新規なし)／全予定枠で50%以下。保有継続は非待ち、未約定監視は保有でない。当時の条件登録actionと、事後の否定・発動・未約定・実新規・完結を分ける。先着250は固定TPや実利益ではなく、全体確定nullを0円へ補完しない。現在費用122円strict正での利益起動と損失側を含む非緩和追尾、返済pending凍結はO49のまま。

## 再現と再表示

以下は固定前からの再現順序であり、既存の保存接続確認・人工確認・固定・開始記録・結果へは再実行しない。処理中なら既存handleを追い、同じ市場実行を起動し直さない。主・正式監査はrootが一回管理し、表示担当は市場・fitを起動しない。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/検証.py --preflight
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/条件発動前の否定/準備する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/条件発動前の否定/人工を確認する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/保存検証.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/レポート.py --check
```

準備helperは保存接続後に条件・入力台帳を新規作成した根拠であり、既存正本を上書きしない。正式再表示は最後の2コマンドだけで、通常生成を通知時に一回、続いて`--check`を行う。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/レポート.py --self-test
```

`self_test()`は人工辞書のみで成功・テスト件数を返し、正式MDを書かない。`--check`は保存同byte・全60・55×9・内部リンクを検査する。小型結果・成功監査・旧参照木／回収JSONだけを読み、詳細gzip・原板・教師は開かず、予測walk・fit・先着・市場を再実行しない。旧67表示器を固有名importし、固定旧大域定数を書き替えない。

[事前外部整理](../../docs/議論/外部再調査/突破の確認と取得位置と前提否定を分ける.md)は強さ・取得位置・前提否定の役割を分ける参考であり、単一3分足の端が市場の共有線である保証はない。反対側を試してから継続する複雑調整の取り逃がしも反証に含む。今巡並行調査を68の事前根拠へ遡及しない。心理は推論であり、高勝率や固定追尾への退出移植を保証しない。全66場既使用、初20学習専用／後20時系列／選択24／既使用後続2を区別する。
