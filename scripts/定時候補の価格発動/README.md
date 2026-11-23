# 定時候補と将来価格発動の保存表示

[試行67](../../study/00067_定時候補を将来価格の突破で発動/検証計画.md)の正式結果だけから、README／設定と結果を生成する。旧66E0/E1保存92運用に、新G0/G1各46場の92運用を比較し、Viewer184資源を表示する。本物生成はrootの主・正式保存監査成功通知後だけ行う。

同じ保存60特徴、旧65U0三木と三回収集計、教師、定時の純side・role・ATR/Dを維持。新fit0・新保存木0・新独立追尾回収0。新G木は複製しない。旧木の全閾値・葉・支持・障壁score・回収平均とMSE、55手法×9尺度を参照表示する。旧回収は旧即時入口の評価であり、新しい条件入口の回収を学習済みとは呼ばない。

変わるのは、定時に最新公開完全3分足の方向端を凍結し、後続Lastのstrict突破で要求すること。設定既超過拒否、normal BBO＋有限正Lastで監視する。設定時Last／BBO不正は判定不能、監視開始後のgap>300秒は観測不足取消／品質注意。次定時T+900に未発動watchと発動済entrypendingを取消し、発動後1価格時計秒・後行正常BBO・TTL30秒も次定時未満へ制限する。約定価格を発動線へ戻さない。利益・損失の連続非緩和追尾と122円strict起動、返済pending凍結はO49会計を維持する。

当時の条件登録actionと事後の発動・未約定被覆は別欄。主待ちはWAIT／全予定、保守は（WAIT＋判定不能＋条件登録してentryなし）／全予定で50%以下、保有継続は非待ち。候補488と新条件ラベル488、発動、仮約定、実登録、実新規、完結を区別し、未発動を分母から落とさない。旧49ラベル・旧55単独回収を新時刻へ流用しない。新規に計算した条件入口先着と一建玉の実回収を分ける。

## 当時の主実行と表示の順序

以下は固定前からの再現順序を記録したもの。**保存接続確認・人工確認・固定・実行開始・結果のある正本へは再実行しない。** 長処理中なら既存handleを確認し、同じ実行を起動し直さない。rootが主・正式監査を一回管理し、担当レポートから市場・fitを起動しない。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/検証.py --preflight
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/定時候補の価格発動/準備する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/定時候補の価格発動/人工を確認する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/保存検証.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/レポート.py --check
```

準備helperは保存接続確認後、`条件.json`と`入力台帳.json`を新規作成した根拠であり、既存条件を上書きしない。集約人工はモデル・運用・独立先着・監査・表示の人工を接続する。既存の正本を読む再表示は最後の表示2コマンドだけで、通常生成もrootの通知時に一回、続いて`--check`を行う。

表示だけの人工は次のコマンド又は`self_test()`で確認できる。これは主の市場実行ではない。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時候補の価格発動/レポート.py --self-test
```

`self_test()`は実入力なしの成功・テスト件数を返す。`--check`は同byte・全60・55×9・内部リンクを検査する。レポートは小型結果・監査・参照モデル／回収JSONを読むだけで、詳細gzip・原板・教師を開かず、予測walk・fit・先着・回収・市場を再実行しない。旧66表示器の純表示補助を固有名importし、大域定数を書き替えない。

[外部資料](../../docs/議論/外部再調査/判断時刻と条件注文の発動を分ける.md)はWilliams本人の先物例、CME注文仕様、CFTC注文研究。候補・発動・約定の分離を参考にするが、3分端・15分寿命・Last・BBO代理は独自規約で、OSE native注文や原典の完全再現ではない。心理は推論であり、条件発動の高勝率保証や現在追尾への退出移植はしない。全66場既使用、初20学習専用／後20時系列／選択24／既使用後続2を区別する。
