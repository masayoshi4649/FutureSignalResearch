# 技法の組み合わせへ取得位置を加えた保存表示

[試行71の計画](../../study/00071_技法の組み合わせへ取得位置を加える/検証計画.md)に従い、主と正式監査の成功後だけ二つのMarkdownを生成する。旧70P0/P1保存92運用、新B0/B1/G0/G1各46場184運用、Viewer276を区別する。表示は結果・元学習木・派生木・回収の小型JSONだけを読み、詳細圧縮・原板・教師個票は開かない。fit・剪定・予測walk・独立計測・市場再生を呼ばない。

Bは旧60列、GだけF61 `g=s*(M−E*)/D` を加える。買いMは当時公開15分high、E*は当時ask、売りMはlow、E*はbid。既存P01/priceの価格構造で、新しい独立技法票ではない。gには旧上位幅・終値位置と代数的に重なる部分があり、主要な追加は判断気配との差とDへの変換という表現の組合せ。Mを実証された支持抵抗、gを独立した前方値幅の証拠と呼ばない。

原判断のsession/slot_id/scheduled/time/lineの5項目で正常BBOを結合し、Lastの追加gateなし。旧readyを保ち、気配の欠落・不整合は接続失敗で止める。Fraction(str)による差と除算から有限float64へ、学習・走査はfloat32。clip、追加符号条件、新mask、未知0補完をしない。E*は将来条件発動後の実約定ではなく、後方の構造否定線までの距離とも別。

同69C条件教師・同容量でB/G三phaseずつの元6木を新学習し、同70の約定支持規約で派生6木を作る。最大24子回帰fit、新分類fit0、新独立計測0。固定三節点と四群は維持し、子の現終端にfilled60unique枠・6日・10場未達が一つでもあれば両側を親へ統合する。剪定ではscore・回収・MSEを選別に使わずfitしない。B1/G1は同じ0派生木に主回収総額strict正を加える。

元学習と派生配置を分離する。`training.partition` のroot・node数・fitは今回raw学習の証拠、`pruning.partitions` と全旧新ID対応が剪定後の配置である。統合親の統計をそのまま継承し、子平均の平均や新教師再集計へ置き換えない。計12木（元6＋派生6）の全node閾値/path/支持/回収/MSEを表示し、未知と全無取引0、全回帰分母とfilled支持を区別する。旧69の共通教師IDをMDへ複製せず、件数・指紋・正本リンクだけを置く。

旧P保存対照とB再現確認を経て、B→Gが同教師・同容量・同剪定の情報追加比較になる。旧70との差をg単独効果にしない。0/1政策は適格側内選択により逆方向になり得るので、同方向の部分集合と断定しない。先着250/125と実一枚回収、無取引0と障壁分母、独立一枠合算と戦略利益を混同しない。品質注意時の全体確定nullは0円にしない。

## 当時の処理と再表示

以下は順序の記録で、開始・結果・人工・固定等が既存なら再実行せず、既存handleを確認する。本物fit・剪定・運用・監査はrootが一回管理する。表示コードからそれらを起動しない。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/入力.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/取得位置と支持/準備する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 work/取得位置と支持/人工を確認する.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/保存検証.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/取得位置と支持/レポート.py --check
```

既存成功結果の再表示は最後の二行だけ。通常生成一回と `--check` で同byte・旧60＋F61・版5の55手法×9尺度・内部リンクを検査する。結果SHAへ結合した成功監査を必須とする。`--self-test` 又は `self_test()` は自己完結の人工六群だけを実行し、本物モデル・正式MDを開かず、fitも行わない。旧70/69の純表示補助は固有名importし、旧globalは変更しない。

15分全予定25/49枠と保有継続非待ちを維持し、登録未約定は保守待ちへ含める。同68条件発動・否定と、現在費用122円strict正で起動する固定O49の損失側も連続非緩和の追尾は変えない。取得位置を理由にD・床を緩めたり、原典の部分返済・複数日保有・裁量stopを移植したりしない。全66場既使用、初20専用／後20時系列／選択24／後続2を分離し、11月5日Day未予約未読を維持する。

[事前の銅先物例の整理](../../docs/議論/外部再調査/期待した進行の不発と取得保護の距離を分ける.md)は同じ例の続編を独立二実証とせず、MACD概念と測定の留保を示す。市場心理は推論であり、NK短期の7割や費用後利益を保証しない。今回並行の外部追加メモも、資料の主張と独自g・固定保護を区別する。
