# 約定支持を保つ粒度で技法を組み合わせた保存表示

[試行70の計画](../../study/00070_約定支持を保つ粒度で技法を組み合わせる/検証計画.md)に従い、主と正式保存監査の成功後に二つのMarkdownを生成する。小型の結果・元木・派生木・回収JSONだけを読み、原板・詳細圧縮・教師個票を開かない。fit・剪定・予測walk・教師生成・独立計測・市場再生を表示から呼ばない。

旧69C0/C1の保存92運用を対照に、新P0/P1各46場の92運用、Viewer184資源を表示する。全60特徴・共通可知教師・66選択・68条件入口・O49保護を維持し、新fit0・新独立計測0。P0の三派生木は旧C0保存木の学習子を下から確認し、現終端が一つでも約定支持60unique枠・6日・10場未達なら両側を親へ統合する。score・回収・MSE・評価成績は剪定基準へ使わない。P1は同木に主回収総額strict正を加える。

固定三節点0/1/2を保ち、DI×対応episode有効の四群は統合しない。四群の親自身も支持不足ならWAITが残る。V1はbから有効でr/k成立ではなく、V0は未登録・取消・TTL・reset等の混合。統合は異なる価格文脈を混ぜ得るため、広い葉へ戻すことを改善の保証としない。

元の `training.partition` は69学習時のroot・node数・fitの証拠として保存される。新しい配置は `pruning.partitions` と旧新ID対応表で説明する。残存旧IDを昇順連番にし、各節点の `source_node_id`、途中の全剪定判断と最終残存を分ける。統合葉の平均・MSE・支持は元親の保存値であり、新しいfitや教師再計数ではない。全node閾値/path、全回帰行とfilled支持・条件付き先着score・両種回収平均を省略せず表示する。

旧69共通教師は件数・除外数・保存指紋とリンクで参照し、全IDを再転記しない。確定無取引0は回帰へ残すが、125敗北や先着scoreの分母にしない。全無取引葉は全平均0/MSE0が既知でもscore/filled平均はnull、空回帰葉は両平均/MSEともnull。旧独立一枠の回収合算を同時実行戦略の利益とせず、実一枚完結と仮先着250を別に扱う。品質注意の全体確定nullは0円へ変えない。

## 当時の実行と保存表示

以下は処理の記録用。条件・人工・固定・開始・結果が既にある正本には再実行せず、既存handleの終端を確認する。本物剪定・運用・監査はrootが一回管理する。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/支持を保つ技法群/準備する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/支持を保つ技法群/人工を確認する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/保存検証.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/レポート.py --check
```

既存成功結果の再表示は最後の二行だけ。通常生成一回と `--check` により、同byte・全60特徴・版5の55手法×9尺度・内部リンクを検査する。正式表示には結果SHAと結合した成功監査を要求する。`--self-test` 又は `self_test()` は架空の元木・剪定木と辞書の人工六群だけを実行し、本物モデルや正式MDには触れない。

15分全予定25/49枠と保有継続非待ちを維持し、未発動を含む登録未約定は保守待ちへ残す。現在BBOで往復122円を超えるstrict正益の利益旗と、損失側も連続非緩和のO49追尾は変えない。P0/P1は適格内選択で逆方向になり得るため、同方向の部分集合と断定しない。全66場既使用・初20専用/後20時系列/選択24/後続2を分け、11月5日Day未予約未読を維持する。

[技法群の細分化と約定支持](../../docs/議論/外部再調査/技法群の細分化と約定支持を分ける.md)はscikit-learn公式説明の読取と独自規約を分けた参考である。公式のコスト複雑度剪定と今回のfilled支持剪定は別方式。市場心理の実測、NK短期70%や利益の保証へ転用しない。旧69表示の純表示補助だけを固有名importし、旧global・固定コード・原典の退出を変更しない。
