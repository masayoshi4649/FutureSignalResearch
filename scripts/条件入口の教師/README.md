# 共通可知の条件入口教師と実回収の保存表示

[試行69](../../study/00069_条件入口に合わせて技法群の教師を作る/検証計画.md)の結果・成功監査・新六木を読むだけでREADME／設定と結果を表示する。旧68N0/N1保存92運用と、新I0/I1/C0/C1各46場の184運用、Viewer276資源を分ける。正式生成はrootの本物実行と監査成功通知後のみ。

全60特徴と65のDI→対応episode有効の四群、各58列深さ2・全深さ4を維持する。Iは旧即時49/55、Cは新68条件入口の先着と独立O49回収を教師とする。両方向×旧新の四測定がすべて評価開始よりstrict前に可知なpairだけを共通集合とし、I/Cをそれぞれ三phaseで学習する。I1/C1は各0木と同木、別fitしない。

確定無取引0を回帰へ含むが、先着scoreと支持には約定既知だけを使う。未知・品質注意・未解消・障壁不足は0補完せずpair全体を除外。全無取引葉は全平均0/MSE0が既知でもscore/fill済み平均はnull、空回帰葉は両平均/MSEともnullである。全方向行・filled支持・約定率・条件付き先着score・両種回収平均・全node閾値とMSEを表示する。共通使用IDと全除外理由も保存小型JSONから表示し、教師や木を再生成しない。

旧N→新Iは集合と無取引分母の変更込み、I→Cが同一可知集合の教師変更。新Iの実運用も68条件入口で、即時運用ではない。未来の約定有無を予測入力へ渡さない。独立一枠の重複建玉合算を同時実行可能な戦略利益にせず、先着250と実一枚回収を分ける。0/1政策は適格側内選択で逆方向になり得るので、同方向の部分集合とは断定しない。

全予定25/49枠、主待ちと未約定を含む保守待ち、保有継続非待ち、条件発動前の反対端否定、現在費用122円strict正の利益起動と連続非緩和追尾は固定68/O49を維持する。品質注意の全体確定nullを0円へ変えない。全66場既使用、初20専用・後20時系列・選択24・後続2を分け、11月5日Dayを未予約未読のまま残す。

## 当時の実行と表示の順序

以下は固定前からの再現順序。保存接続・人工・固定・開始記録・結果が既にある正本には再実行せず、既存handleを確認する。本物計測・fit・市場運用・監査はrootが一回管理し、表示コードから起動しない。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/入力.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/条件入口の教師/準備する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/条件入口の教師/人工を確認する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/保存検証.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/レポート.py --check
```

既存結果の再表示は最後の2行だけ。通常生成を指示時に一回、続いて`--check`で保存同byte・全60・55×9・内部リンクを検査する。`--self-test`又は`self_test()`は自己完結の人工六木と人工辞書で表示を検査し、正式文書を生成しない。

旧68表示の数値整形・リンク検査・版5表等だけを固有名importし、旧globalや旧正式コードは変更しない。旧分母のvalidate/contextや旧参照三木を新六木へ流用しない。小型結果・モデル・回収JSONを読むだけで、詳細gzip・原板・教師個票を開かず、fit・予測walk・先着・回収・戦略再生も呼ばない。

[反転確認と取得時計の外部整理](../../docs/議論/外部再調査/反転の確認と取得時点と教師をそろえる.md)は本人講義と出版社公開章に基づく参考。二度目も失敗すること、図形比較の割合と取引勝率の違いを残す。心理は推論で、NK短期の70%や利益保証ではない。原典の裁量退出や将来最良点を現行追尾へ移植しない。
