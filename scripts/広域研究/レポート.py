"""00006の固定設定・全探索結果・後続結果を、汎用表付きMarkdownへ記録する。"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00006_外部手法を1分3分5分で比較"
SPEC = importlib.util.spec_from_file_location("広域研究の表生成", ROOT / "scripts/レポート/設定結果レポート.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)
FAMILIES = ["開始幅突破", "開始幅失敗復帰", "狭幅突破", "高安端復帰", "BB内復帰", "EMA復帰"]
RESULT_IDS = {name: f"R{index:02d}" for index, name in enumerate(FAMILIES, 1)}


def settings() -> list[dict]:
    """実装した手法と尺度の参照を一覧にする。

    引数: なし。
    返り値: list[dict] は表セルと設定明細に用いる設定。
    """
    rows = []
    def add(methods: list[str], scales: list[str], short: str, results: str, role: str, detail: str) -> None:
        """一設定を登録する。

        引数: methods/scales (list[str]) はID、short/results/role/detail (str) は表示内容。
        返り値: None。
        """
        rows.append({"設定ID": f"S{len(rows)+1:02d}", "手法ID": methods, "尺度ID": scales,
                     "短記": short, "結果短記": results, "役割": role, "明細": detail})
    scales = ["m01", "m03", "m05"]
    add(["P03"], scales, "開始15/30分高安", "R01・R02", "開始幅・位置",
        "デイ08:45/ナイト17:00起点の15/30分幅を固定。当該尺度の初めの足が揃うこと。幅計測後だけ発動。現物09:00起点は未使用")
    add(["P07"], scales, "開始幅終値突破", "R01", "追随発動",
        "買：前C<=開始幅H<今C、売：前C>=開始幅L>今C。15/30分幅、再突破も評価。瞬間突破の逆指値型とは異なる")
    add(["P09"], scales, "開始幅へ終値復帰", "R02", "反転発動",
        "買：前C<開始幅L<=今C<=開始幅H、売：前C>開始幅H>=今C>=開始幅L。単なる当足ヒゲ越えとは区別")
    add(["P01", "P07"], scales, "NR4/7・次足突破", "R03", "収縮の準備・追随発動",
        "前足H−Lがそれ以前3/6本より厳密に小さい。今C>前Hで買、今C<前Lで売。次の1本だけ。inside条件・TR拡大条件は課さない")
    add(["P03", "P09"], scales, "過去10/20本端復帰", "R04", "位置・反転発動",
        "当足除外・同場10/20本。買：今L<過去L<今C<=過去H、売は対称。20日Turtle Soupの原著再現ではない")
    add(["I05", "P09"], scales, "BB20・2/2.5σ復帰", "R05", "帯からの反転発動",
        "終値20本平均±2/2.5×母標準偏差(ddof0)。前Cが前帯の厳密な外、今Cが今の同側帯以上/以下へ復帰。反対側帯の範囲制約は追加しない")
    add(["I01", "P08"], scales, "EMA10/20交差＋傾き", "R06", "追随発動",
        "買：前C<=前EMA、今C>今EMA>前EMA。売は対称。期間SMAで初期化。上位足条件は補助で分離した派生条件")
    add(["I01"], ["m15"], "EMA20・位置と傾き", "R01〜R06の上位方向", "上位環境",
        "当場で最後に確定した15分足。買：C>EMA20>前EMA、売：C<EMA20<前EMA。確認時計・原行とも入口時点以下。30分は未使用")
    add(["C07"], scales + ["m15"], "判断1/3/5・上位15", "R01〜R06の上位方向", "複数足の参照関係",
        "発動足1/3/5分と確定15分EMA方向を同じ側へ揃える。補助なし・ADX・RSI候補へ上位方向一致を要求しない")
    add(["I08"], scales, "ADX14>=25/<20", "R01〜R06のADX環境", "強さ・方向の補助",
        "追随R01/R03/R06はADX>=25かつ買+DI>−DI/売−DI>+DI。反転R02/R04/R05はADX<20。DMI14・ADX14はWilder。ATR0→DI0、DI和0→DX0")
    add(["I04"], scales, "RSI14・50〜70/30〜50", "R01〜R06のRSI帯", "勢い・位置の補助",
        "Wilder RSI14。方向側=買RSI/売100−RSI。追随50以上70未満、反転30以上50以下。上下幅とも0は欠測")
    add(["I09"], scales, "Wilder ATR14>0", "全評価", "共通準備",
        "前足差分14本で初期化し、ATR>0だけを母集団にする。ATR幅の利確/保護は今回未使用。足幅ごとに別計算")
    add(["B01", "B02"], ["tick"], "正常BBO・数量>=1", "全評価", "仮新規・観測",
        "Bid/Ask正、Bid<Ask、両最良数量>=1。Buy1=Bid、Sell1=Ask。価格時計非後退・原板順。注文フローや板偏りの方向判断は未使用")
    add(["E01"], ["tick"], "逆行125/順行250", "全評価", "先着ラベル",
        "買Ask/売Bid新規、返済側気配で等号込み到達。要求+1秒以上30秒以内、確認遅延<=30秒、残り>=60分。期限15:35/翌05:50、未決着300秒超空白/EOFは不足")
    return rows


def number(value: str | None) -> float:
    """比較用の集計値を読み取る。

    引数: value (str | None) はCSVの値。
    返り値: float は欠測を負数にした値。
    """
    return float(value) if value not in (None, "") else -1.0


def ranking(row: dict) -> tuple:
    """探索と同じ優先順で表示用代表候補を選ぶ。

    引数: row (dict) は探索集計。
    返り値: tuple は表示順位。後続成績を利用しない。
    """
    return (row["探索70条件"] == "True", row["支持条件"] == "True",
            min(number(row["学習_確認率"]), number(row["条件選択_確認率"])),
            min(number(row["学習_30分間引き_確認率"]), number(row["条件選択_30分間引き_確認率"])), number(row["条件選択_約定候補数"]))


def ratio(row: dict, prefix: str = "") -> str:
    """先着の分子・分母・比率を一つに表示する。

    引数: row (dict) は集計、prefix (str) は期間名の接頭辞。
    返り値: str は分子/分母と率。
    """
    return f"{row[prefix+'順行先着']}/{row[prefix+'約定候補数']}＝{G.pct(row[prefix+'確認率'])}"


def points(value: str | None) -> str:
    """比率差を欠測と区別して表示する。

    引数: value (str | None) は百分率差。
    返り値: str は符号付きpp値、または未算出。
    """
    return "未算出" if value in (None, "") else f"{float(value):+.2f}"


def main() -> None:
    """数値正本から試行READMEと設定結果Markdownを作る。

    引数: なし。
    返り値: None。保存済み結果の転記だけを行う。
    """
    catalog = G.read_json(G.CATALOG)
    config, fixed = G.read_json(STUDY / "条件.json"), G.read_json(STUDY / "選択固定.json")
    with (STUDY / "全候補_探索.csv").open(encoding="utf-8-sig", newline="") as stream:
        candidates = list(csv.DictReader(stream))
    follow = G.read_json(STUDY / "後続結果.json") if (STUDY / "後続結果.json").exists() else None
    settings_rows = settings()
    output = STUDY / "設定と結果.md"
    text = "# 試行00006：設定と結果\n\n記録日2026-11-04。NK225、確定1/3/5分の六仮説と四補助条件を比較。\n\n"
    text += "[試行README](README.md) / [計画](計画.md) / [条件](条件.json) / [汎用表](../../docs/議論/手法と時間スケールの汎用表.md)\n\n"
    text += "**147候補（対照3を含む）で探索70条件は0件。** 足の始値/終値と期間、記事の原手法と本試行の独自定義を区別する。\n\n"
    text += "## 手法×時間スケール（共通表のコピー）\n\nカタログ版1、51手法×9尺度を保持。新しい発動は既存の手法群の派生設定として明細に記録する。R01〜R06は入口群であり、各群24候補の成績を下段に列挙する。指標単独の利益・効果は未評価。\n\n"
    text += G.matrix(catalog, output, settings_rows)
    text += "## 設定・閾値・役割\n" + G.table(["設定ID", "手法・尺度", "役割", "具体条件", "複合評価"], [
        [s["設定ID"], " / ".join(s["手法ID"]) + "<br>" + " / ".join(s["尺度ID"]), s["役割"], s["明細"], s["結果短記"]] for s in settings_rows])
    text += "## 共通条件と分母\n\n同場の前足とATR14>0を持ち、評価期限まで60分以上を残す時点。各手法固有の履歴が必要。指標は同限月で継続し、欠枠・限月変更で再初期化。パターン窓と交差の前足は場ごとに切る。完全な足だけを使い、3/15分の末尾端数足を使わない。\n\n"
    text += "主確認率=順行先着/全約定。五分類は順行/逆行/期限未達/観測不足/未約定の順。手数料込み運用勝率ではない。30分間引きは要求時計・場・方向ごとで、未約定も起点。同時刻対照は各選択入口に買売一対を対応し、率差は価格ptでなくパーセントポイント（pp）。\n\n"
    text += "学習40場（09/21〜10/16）・条件選択20場（10/19〜10/30）は既使用。後続4場（11/02〜11/03）は固定後の一候補だけに使う。支持は学習60約定/6日/10場、選択・後続20約定/3日/5場。探索70条件は両期間70%に加え30分間引きの件数/70%を要求。後続2日4場では支持基準自体を満たせない。\n\n"
    text += "## 固定一候補の結果\n\n固定：**" + fixed["候補ID"] + "**。低ADXの開始幅失敗復帰で、診断用の固定。70%達成候補ではない。\n"
    results = dict(fixed["探索結果"])
    if follow:
        results["後続検査"] = follow["結果"]
    text += G.table(["期間", "順行/全約定", "五分類", "約定開始日/場", "30分間引き", "同時刻対照との差"], [
        [phase, ratio(row), "/".join(str(row[key]) for key in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")),
         f"{row['約定開始日数']}日/{row['約定場数']}場", ratio(row, "30分間引き_"),
         f"{row['同時刻差pp']:+.2f}pp" if "同時刻差pp" in row else "後続では追加選択用の対照を未集計"] for phase, row in results.items()])
    text += "## 全147候補の閾値と結果\n\n各候補の閾値は上段Sと、時間足・パラメータ・補助の組で一意。補助は一つずつ。対照以外で両期間の支持を満たした候補は119件。以下の代表以外も省略せず残す。数値正本は[全候補_探索.csv](全候補_探索.csv)。\n\n"
    for family in ["全時点両方向"] + FAMILIES:
        rid = RESULT_IDS.get(family, "R00")
        text += f"### {rid}：{family}\n"
        rows = []
        for row in candidates:
            if row["手法"] != family:
                continue
            rows.append([row["候補ID"], row["時間足分"], row["パラメータ"] or "なし", row["補助"],
                ratio(row, "学習_"), ratio(row, "条件選択_"),
                "/".join(row["条件選択_"+key] for key in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")),
                ratio(row, "学習_30分間引き_"), ratio(row, "条件選択_30分間引き_"),
                f"{points(row['学習_同時刻差pp'])}/{points(row['条件選択_同時刻差pp'])}",
                "充足" if row["支持条件"] == "True" else "不足", "達成" if row["探索70条件"] == "True" else "未達"])
        text += G.table(["候補ID", "分", "パラメータ", "補助", "学習", "選択", "選択五分類", "学習30分", "選択30分", "対照差pp 学習/選択", "支持", "探索70"], rows)
    text += "## 限界と次の問い\n\n同じ相場・重なる入口を使った探索で、候補数を独立な実証回数として数えない。異なる足幅は欠枠・指標準備・確認遅延の影響も異なる。支持件数が足りたことは将来70%の証明ではない。固定入口の一建玉・返済遅延・費用は[00007](../00007_固定入口の単一建玉と費用感度/README.md)で別に検証した。\n\n"
    paths = [G.CATALOG, Path(__file__), ROOT / "scripts/広域研究/検証.py", STUDY / "計画.md", STUDY / "条件.json", STUDY / "入力台帳.json", STUDY / "全候補_探索.csv", STUDY / "選択固定.json"]
    if follow:
        paths.append(STUDY / "後続結果.json")
    text += G.provenance(paths, output)
    output.write_text(text, encoding="utf-8")

    # ----------------------------------------
    # READMEは一覧から読み始めるための要約。全閾値の正本へ戻れるようにする。

    text = "# 試行00006：外部手法を1分・3分・5分で比較\n\n実行日2026-11-04。**今回の147候補で、支持条件付きの先着確認率70%は確認できなかった。** 固定した開始幅失敗復帰＋低ADXの新4場は5/12＝41.67%。\n\n"
    text += "[設定・汎用表・全147候補の結果](設定と結果.md) / [計画](計画.md) / [条件](条件.json) / [入力台帳](入力台帳.json) / [選択固定](選択固定.json) / [後続結果](後続結果.json)\n\n"
    text += "## 仮説と実施範囲\n\n研究論文、取引所・指標作者、個人や商用サービスの実践記事から、開始幅突破・失敗復帰・NR4/7・高安端ヒゲ復帰・BB内復帰・EMA復帰を具体化した。1/3/5分×6手法×2パラメータ×4補助（なし/上位15分EMA方向/ADX環境/RSI帯）の144候補と両方向対照3候補。原記事の厳密再現ではなく、125pt逆行前250pt順行という共通目標へ合わせた独自条件である。\n\n"
    text += "外部資料の根拠と不足は[一次資料](../../docs/議論/先物手法の調査_一次資料.md)・[実践記事](../../docs/議論/先物手法の調査_実践記事.md)。外部の成功例や成績をこの試行の結果へ混ぜない。\n\n"
    text += "## 入力・先着・分割\n\nNK225ラージ原板64場。旧60場は固定元・キャッシュが不変であることを監査し、新11/2〜11/3の4場だけ追加した。学習40場・条件選択20場は既使用。新4場は価格の方向や成績を開かず品質だけ確認し、コード・一候補の固定後に評価した。日付はセッション開始日基準。\n\n"
    text += "買Ask/売Bidで仮新規、返済側気配が125pt逆行または250pt順行へ達する順番を追う。要求+1秒以上・30秒以内、確認遅延30秒以内、残り60分以上。期限15:35/翌05:50。正常板300秒超の空白やEOF不足は観測不足。主率の分母に期限・不足を残す。独立入口の観測であり運用損益は未算出。\n\n"
    text += "## 探索内の各手法の代表候補\n\n以下は事前の順位規則を各群へ適用した探索上の代表。新4場で確認したのは全体から固定した一候補だけで、各行が未使用期間を通過したわけではない。\n"
    representatives = []
    for family in FAMILIES:
        usable = [r for r in candidates if r["手法"] == family and number(r["学習_約定候補数"]) >= 20 and number(r["条件選択_約定候補数"]) >= 10]
        if usable:
            row = max(usable, key=ranking)
            representatives.append([family, row["時間足分"], row["パラメータ"], row["補助"], ratio(row, "学習_"), ratio(row, "条件選択_"), "充足" if row["支持条件"] == "True" else "不足"])
    text += G.table(["手法", "分", "設定", "補助", "学習", "条件選択", "支持"], representatives)
    text += "## 一候補固定後の確認\n\n固定条件は3分足、開始15分高安の外側終値から内側への復帰、ADX14<20。売りは一度上に終値で抜けた後の幅内復帰、買いは下へ抜けた後の幅内復帰。両方向を同じ定義で扱い、RSI・上位EMA条件は追加していない。\n"
    text += G.table(["期間", "順行/全約定", "逆行/期限/不足/未約定", "30分間引き", "約定開始日/場"], [
        [name, ratio(row), "/".join(str(row[key]) for key in ("逆行先着", "期限未達", "観測不足", "未約定")), ratio(row, "30分間引き_"), f"{row['約定開始日数']}日/{row['約定場数']}場"] for name, row in results.items()])
    text += "後続の11/2は1/5、11/3は4/7。候補がない1場も入力から除外していない。新後続は2日4場しかなく、要求した3開始日・5場・20約定の支持にも不足する。70%未達を維持し、短い後続の41.67%を安定した将来確率とみなさない。\n\n"
    text += "## 検証・再現・保存\n\n[合成検証](合成検証.json)34件が成功。半開足・確認時刻・今足除外・NR厳密比較・左右対称・指標初期化・上位足利用可能時刻・未来列を変えても発動不変等を確認した。率差列名と初期化説明の明文化前後で全147候補の数値は一致。別実装の選択・集計・先着監査は[独立監査](独立監査.json)を参照。\n\n"
    text += "[入力監査](入力監査.json)と[探索品質](入力品質_探索.json)・[後続品質](入力品質_後続.json)に欠枠等を保存。大きな入口中間表はworkのgzip、正式試行は全候補の小さなCSV・固定一候補の事例・JSONとMarkdownを基本にした。原板を複製しない。\n\n"
    text += "```powershell\nC:/Python314/python.exe -X utf8 scripts/広域研究/合成検証.py\nC:/Python314/python.exe -X utf8 scripts/広域研究/検証.py --phase 探索\nC:/Python314/python.exe -X utf8 scripts/広域研究/検証.py --phase 後続\nC:/Python314/python.exe -X utf8 scripts/広域研究/レポート.py\n```\n\n"
    text += "上は新しい再現先での順序。`--study <再現先>`へ計画・条件・入力台帳をコピーして実行する。正式00006は後続済みのため探索/後続の上書きを拒否する。新しい条件で研究する場合は新試行番号を使う。Python3.14.3・NumPy2.5.3、CPU。GPUや追加の学習ライブラリは使っていない。入力cacheの復元は[scripts/広域研究](../../scripts/広域研究/README.md)を参照。\n\n"
    text += "## 知見と次の試行\n\n上位方向・ADX・RSIは、付ければ一律に改善する条件ではなかった。時間足を変えると、情報の粒度に加え欠枠・準備本数・確定遅延も変わる。[比較から得た知見](../../docs/議論/外部手法の検証で得た知見.md)に全群の対応比較を残す。固定入口の一建玉・費用・返済遅延は[00007](../00007_固定入口の単一建玉と費用感度/README.md)で切り分けて検証した。\n"
    (STUDY / "README.md").write_text(text, encoding="utf-8")
    print("00006の汎用表コピー・全147閾値と結果・READMEを生成した")


if __name__ == "__main__":
    main()
