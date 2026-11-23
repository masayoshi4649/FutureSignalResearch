"""00018の保存済み36入口/運用を、N/Dの共通準備を分けて表示する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00018_VWAPの位置と傾きで順行反転を比較"
DISPLAY = ROOT/"scripts/収縮反転/レポート.py"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
FAMILIES = {"T1": ("押し目再開", "順行"), "R2": ("BB内復帰", "反転")}
SETTINGS = ("N_A", "N_B", "N_C", "D_A", "D_B", "D_D")


def display_helper() -> Any:
    """以前の汎用表と保存件数検査だけを読み込む。

    引数: なし。
    返り値: Any は表表示/入口検算。価格・補助・売買の再生は行わない。
    """
    spec = importlib.util.spec_from_file_location("VWAP入口の帳票共通表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


P = display_helper()
G, number = P.G, P.number


def definitions(config: dict) -> list[dict]:
    """固定三尺度・二役割・六条件を全36評価へ対応付ける。

    引数: config (dict) は条件正本。
    返り値: list[dict] は36入口/36X0とR01〜R36。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(SETTINGS) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("固定三尺度・T1/R2・六条件・X0と異なる")
    if config["参照条件"] != {"連続点数": 4, "傾き差本数": 3, "判断時点": True} or (config["逆行pt"], config["順行pt"]) != (125, 250):
        raise ValueError("同場四点・三足前・判断時点・125/250と異なる")
    rows = []
    for size in (1, 3, 5):
        for family, (name, role) in FAMILIES.items():
            for setting in SETTINGS:
                source = {"入口ID": f"{size}分_{family}_{setting}", "入口系統": family, "時間足分": size,
                          "補助": setting, "名称": name, "役割": role}
                rows.append({"候補ID": source["入口ID"]+"_X0", "入口": source, "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """全36の保存件数・支持・費用と事前3分表示12を検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は固定定義。
    返り値: tuple[dict,dict] は入口ID別/候補ID別の正本。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または先着条件が不一致")
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 36 or len(report["入口評価"]) != 36 or len(values) != 36 or len(report["結果"]) != 36:
        raise ValueError("固定36入口・36運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("入口/候補IDが不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("定義が保存結果と不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            if row[period]["入口"] != entry[period]:
                raise ValueError("入口集計が運用欄と不一致")
            item, n = row[period]["運用"], row[period]["運用"]["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n:
                raise ValueError("場数/取引数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意を含む全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["費用資格"]) != (support, bool(goal), qualified):
            raise ValueError("支持/70目標/費用資格が不一致")
    displayed = [r["候補ID"] for r in rules if r["入口"]["時間足分"] == 3]
    if report["表示固定ID"] != displayed or report["入口70目標達成数"] != sum(e["70目標"] for e in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("事前表示12または資格数が不一致")
    return entries, values


# ----------------------------------------
# 価格P、共通N/Dマスク、位置/傾きの付け外しを別の段階で表示する。

def preparation_table(study: Path) -> str:
    """全足参照と元価格発動の保存品質を集計する。

    引数: study (Path) は試行。
    返り値: str は尺度/期間別の準備表。N/Dを重複した独立母集団として加算しない。
    """
    refs, prices = defaultdict(Counter), defaultdict(Counter)
    for row in G.read_json(study/"参照品質.json"):
        refs[(row["時間足分"], row["期間"])].update({k: v for k, v in row.items() if isinstance(v, (int, float)) and k != "時間足分"})
    for row in G.read_json(study/"入口品質.json"):
        prices[(row["時間足分"], row["期間"])].update({k: row.get(k, 0) for k in ("価格発動数", "N共通準備通過価格発動数", "D共通準備通過価格発動数")})
    rows = []
    for size in (1, 3, 5):
        for period in PERIODS:
            a, b = refs[(size, period)], prices[(size, period)]
            if not 0 <= a["D共通準備足数"] <= a["N共通準備足数"] <= a["公開足数"] or not 0 <= b["D共通準備通過価格発動数"] <= b["N共通準備通過価格発動数"] <= b["価格発動数"]:
                raise ValueError("N/D準備の包含関係が不一致")
            rows.append([size, PERIOD_NAMES[period], a["価格足数"], a["公開足数"], a["native有効足数"], a["差分有効足数"],
                         a["N共通準備足数"], a["D共通準備足数"], b["価格発動数"], b["N共通準備通過価格発動数"], b["D共通準備通過価格発動数"]])
    text = "## 価格Pと共通準備の母集団\n\n旧11の価格準備/発動Pを残し、N_A/B/Cは同じnative四点、D_A/B/D_Dはさらに同じ基準の差分四点を要求する。DはNの部分集合。N/Dの発動数を足して独立の機会数としない。足の準備数とT1/R2合計の価格発動数も異なる。\n"
    total = sum(prices.values(), Counter())
    text += "全65場・三尺度の価格P"+number(total["価格発動数"])+"件から、共通準備通過はN_A "+number(total["N共通準備通過価格発動数"])+"件、D_A "+number(total["D共通準備通過価格発動数"])+"件。これは位置や傾きをまだ追加していない段階の除外であり、N_Aを元の無条件P全件と取り違えない。\n\n"
    return text+G.table(["足分", "期間", "価格足", "公開足", "native可", "差分可", "N四点足", "D四点足", "元価格P", "N通過P=N_A", "D通過P=D_A"], rows)


def comparison_tables(entries: dict, values: dict) -> str:
    """全六組をN三条件/D三条件の二層で比較する。

    引数: entries/values (dict) は保存入口/運用。
    返り値: str は旧二期間の記述表。条件や表示代表を選び直さない。
    """
    native, differential = [], []
    for size in (1, 3, 5):
        for family in FAMILIES:
            for period in PERIODS[:2]:
                for settings, output in ((("N_A", "N_B", "N_C"), native), (("D_A", "D_B", "D_D"), differential)):
                    rates, amounts, attention = [], [], []
                    for setting in settings:
                        key = f"{size}分_{family}_{setting}"
                        e, v = entries[key][period], values[key+"_X0"][period]["運用"]
                        rates.append(f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}")
                        amounts.append(number(v["追加5pt純損益円"]))
                        attention.append(str(v["品質注意場数"]))
                    output.append([size, family, PERIOD_NAMES[period], *rates, " / ".join(amounts), "/".join(attention)])
    text = "## 同じ共通準備での三条件比較\n\n順/仮約定の主率と追加片道5pt後の観測純額を並べる。NとDの全運用額を差し引いて起算の単独効果とはしない。D_B対D_Dだけが同じDマスク・同じ価格Pにnative/差分の位置を付ける起算置換であり、互いの部分集合とは限らない。\n\n### N層：native四点共通\n"
    text += G.table(["足分", "系統", "期間", "N_A率", "N_B率", "N_C率", "追加5pt円 A/B/C", "注意場 A/B/C"], native)
    text += "### D層：nativeと差分の四点共通\n"+G.table(["足分", "系統", "期間", "D_A率", "D_B率", "D_D率", "追加5pt円 A/B/D", "注意場 A/B/D"], differential)
    positive = sum(all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2]) for row in values.values())
    text += "両期間で追加5pt後の観測純額が正の候補は"+number(positive)+"/36。支持・70目標・費用資格は別に確認する。0取引は実行済みで、率/平均は未算出。既使用11/4は全候補結果へ分離し旧二期間の資格へ加えない。\n\n"
    sparse = []
    for size in (1, 3, 5):
        row = entries[f"{size}分_R2_N_C"]
        sparse.append(str(size)+"分 "+str(row["学習"]["約定候補数"])+"/"+str(row["条件選択"]["約定候補数"]))
    text += "N_C反転の仮約定数（学習/条件選択）は"+"、".join(sparse)+"。100%が表示される少数例や0件を、支持付きの高率や勝率0%へ読み替えない。位置に傾きを重ねる条件は今回強い件数減少を伴い、二つを独立な確認票とは数えない。\n\n"
    example = values["3分_R2_D_B_X0"]
    a, b = [example[p]["運用"] for p in PERIODS[:2]]
    text += "3分R2_D_Bは追加5pt後に学習"+number(a["追加5pt純損益円"])+"円/条件選択"+number(b["追加5pt純損益円"])+"円を観測したが、完結取引は"+number(a["完結取引数"])+"/"+number(b["完結取引数"])+"件。追加10ptでは学習"+number(a["追加10pt純損益円"])+"円で、固定した支持条件と費用資格を満たしていない。良い一部分だけで採用を決めず、今回のP/助走/起算/固定X0/既使用期間の組合せについての結果として扱う。\n\n"
    return text


def preparation_diagnosis(study: Path, output: Path, full: bool = False) -> str:
    """保存準備診断から遅延・四点助走と位置条件を分離する。

    引数: study/output (Path) は試行/表示先、full (bool) は全18価格P群も表示するか。
    返り値: str は準備除外の分解。保存診断を新しい独立市場標本へ加算しない。
    """
    path = study/"準備診断.json"
    if not path.exists():
        return ""
    data = G.read_json(path)
    if data["結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("準備診断と結果SHAが不一致")
    item, feet = data["全体価格P集計"], data["全体足集計"]
    if item["価格P全数"] != item["P確認遅延30秒超数"]+item["P確認遅延30秒以内数"] or item["P確認遅延30秒以内数"] != item["遅延以内PからN通過数"]+item["遅延以内PからN除外数"] or item["P確認遅延30秒以内数"] != item["遅延以内PからD通過数"]+item["遅延以内PからD除外数"]:
        raise ValueError("準備診断の分母分解が不一致")
    status = "全件一致" if data.get("全件一致") is True else "不一致または未確認"
    text = "## 共通準備で落ちた理由と位置選別の区別\n\n"+G.link(path, output)+"："+status+"、"+number(data["照合項目数"])+"項目。これは保存足/P/caseと集合対応の診断で、価格・先着・損益を再生せず、主/状態監査と件数を独立標本へ合算しない。\n"
    text += G.table(["段階", "分母P", "通過P", "除外P", "意味"], [
        ["確認遅延30秒以内", item["価格P全数"], item["P確認遅延30秒以内数"], item["P確認遅延30秒超数"], "両共通マスクより前の実行可能性"],
        ["N四点共通", item["P確認遅延30秒以内数"], item["遅延以内PからN通過数"], item["遅延以内PからN除外数"], "現在native可でも連続四点が未準備"],
        ["D四点共通", item["P確認遅延30秒以内数"], item["遅延以内PからD通過数"], item["遅延以内PからD除外数"], "さらに正差分四点/同基準を要求"]])
    text += "N_Aと元Pの差"+number(item["全PからN除外数"])+"件は確認遅延"+number(item["P確認遅延30秒超数"])+"件と、遅延以内かつ現在native有効だが四点未準備の"+number(item["現在native有効だがN助走未準備P数"])+"件に分かれる。位置/傾きで落ちた件数ではない。元Pで現在補助観測にも不可理由があったのは"+number(item["現在補助観測にも不可理由があるP数"])+"件、内部比率の許容超/未定義も"+number(item["内部比率の数値差が許容超のP数"])+"/"+number(item["内部比率が未定義のP数"])+"件だった。\n\n"
    text += "全足のnative有効flagには確認遅延条件も含む。公開足の遅延超"+number(feet["公開かつ確認遅延30秒超足数"])+"足と、現在補助観測にも不可理由がある"+number(feet["現在補助観測にも不可理由がある足数"])+"足を分ける。後者は今回すべて価格時計場外で、配信比率の数値不整合を意味しない。非公開"+number(feet["非公開足数"])+"足も別状態。N履歴理由と現在理由、Dの複数理由の和を一意の除外件数へ置き換えない。\n\n"
    if full:
        rows = [[row["時間足分"], row["系統"], PERIOD_NAMES[row["期間"]], row["価格P全数"], row["P確認遅延30秒超数"], row["P確認遅延30秒以内数"], row["全PからN通過数"], row["遅延以内PからN除外数"], row["全PからD通過数"], row["遅延以内PからD除外数"]] for row in data["尺度期間系統別の価格P"]]
        text += G.table(["分", "系統", "期間", "全P", "遅延超", "遅延以内P", "N_A", "以内PからN除外", "D_A", "以内PからD除外"], rows)
    return text


def auxiliary_diagnosis(study: Path, output: Path, full: bool = False) -> str:
    """七対照の共通入口・参加集合差を保存診断から表示する。

    引数: study/output (Path) は試行/表示先、full (bool) は全126群を表へ出すか。
    返り値: str は診断の範囲と任意全表。売買の再生は行わない。
    """
    path = study/"補助対応診断.json"
    data = G.read_json(path)
    if data["結果SHA256"] != G.sha(study/"結果.json") or len(data["結果"]) != 126:
        raise ValueError("対応診断のSHAまたは126群が不一致")
    rows = []
    for row in data["結果"]:
        pair = row["運用比較"]
        if row["左入口数"] != row["共通入口数"]+row["左のみ入口数"] or row["右入口数"] != row["共通入口数"]+row["右のみ入口数"]:
            raise ValueError("対応する入口集合が不一致")
        if row["部分集合検査"] and row["右のみ入口数"]:
            raise ValueError("包含対照に右のみ入口がある")
        difference = pair["右側のみ純額円"]-pair["左側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"], pair["共通実新規純額差円"]+difference, abs_tol=1e-8):
            raise ValueError("参加集合純額の接合が不一致")
        rows.append([row["足分"], row["系統"], PERIOD_NAMES[row["期間"]], row["左"]+"→"+row["右"], row["比較条件"],
                     f"{row['左入口数']}/{row['右入口数']}/{row['共通入口数']}", f"{row['左のみ入口数']}/{row['右のみ入口数']}",
                     f"{pair['共通実新規数']}/{pair['左側のみ実新規数']}/{pair['右側のみ実新規数']}",
                     number(pair["共通実新規純額差円"]), number(difference), number(pair["全運用純額差円"])])
    status = "全件一致" if data.get("対応集合全件一致") is True else "不一致または未確認"
    text = "## 対応集合と単一建玉の参加差\n\n"+G.link(path, output)+"："+status+"、"+number(data["同じ仮約定の照合項目数"])+"項目。7対照×3尺度×2役割×3期間＝126群。native位置/傾き/差分位置/D共通準備の包含六対照と、D_B対D_Dの起算置換を分ける。共通仮約定を独立標本へ加算しない。\n\n"
    text += "同じ実新規のX0返済時計/原行/価格/理由/純額は全値一致を確認する。全純額差＝共通実新規差＋右だけ純額−左だけ純額。除外で保有中抑止と再参加が変わるため、部分集合の入口でも実運用取引が単純な部分集合になるとは限らない。\n\n"
    if full:
        text += G.table(["分", "系統", "期間", "左→右", "対照", "左/右/共通入口", "左/右のみ入口", "共通/左/右のみ実新規", "共通純額差", "集合純額差", "全純額差"], rows)
    return text


# ----------------------------------------
# 旧価格準備・オンライン参照・六条件・約定と出口を別セルへ写す。

def settings(rules: list[dict]) -> list[dict]:
    """全36へ使用セル/閾値/評価IDを対応付ける。

    引数: rules (list[dict]) は固定36評価。
    返り値: list[dict] はS設定。N/Dの助走と線の追加条件を区別する。
    """
    groups = []
    for size in (1, 3, 5):
        scale = [f"m{size:02d}"]
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        t1, r2 = [[r for r in same if r["入口"]["入口系統"] == family] for family in FAMILIES]
        n = [r for r in same if r["入口"]["補助"].startswith("N_")]
        d = [r for r in same if r["入口"]["補助"].startswith("D_")]
        n_pos = [r for r in same if r["入口"]["補助"] in ("N_B", "N_C", "D_B")]
        n_slope = [r for r in same if r["入口"]["補助"] == "N_C"]
        d_pos = [r for r in same if r["入口"]["補助"] == "D_D"]
        groups += [
            (["I01", "I05", "I08", "I09"], scale, same, "旧P：EMA20/ATR14/ADX14/BB20と前6足", "固定11の準備を保持。1分も同じ式。VWAP追加前の全価格Pを保存"),
            (["I01", "P08"], scale, t1, "T1 EMA押し目再開", "前CがEMA反対側から現Cが有利側・EMA向き・終値改善・上位方向を旧11同値利用"),
            (["I05", "P09"], scale, r2, "R2 BB20×2外→内・ADX<20・中心有利", "前C帯外/当C帯内・改善、母標準偏差を旧11同値利用"),
            (["I12"], scale, n, "N共通：現＋直前3のnative同epoch", "N_A/B/Cに同じ四点。判断時点参照を足終端値と呼ばない"),
            (["I12"], scale, d, "D共通：N＋正差分四点同基準", "D_A/B/D_Dだけ。将来の23Day一覧を朝の許可に使わずオンライン判定"),
            (["I12"], scale, n_pos, "native位置strict：T1 C側/R2線側", "side×(C−native)>0が順行、side×(native−C)>0が反転。D_Bもnativeだけで位置選別"),
            (["I12"], scale, n_slope, "N_C：N_B＋side×(native−3前)>0", "等号除外、反転でも傾きは実sideへ。位置と傾きを独立二票と数えない"),
            (["I12"], scale, d_pos, "D_D：差分位置strict", "同じDマスクでD_B(native位置)と起算置換。傾きは追加しない")]
    groups += [
        (["I01", "C07"], ["m15"], rules, "旧P当場公開15分EMA20と前値", "T1は旧定義の方向条件、R2は準備。現在下位足終了/公開キー以下だけ利用"),
        (["I12", "V01"], ["tick"], rules, "最新原行の正値/内部比率/量時計/identity", "00017監査済み小列。固有時計なし、後退/最新不正から古正常へfallbackしない。RVOLは未使用"),
        (["B01"], ["tick"], rules, "ラージBBO・新規/返済+1価格時計秒", "micro1枚代理。新規買Ask/売Bid・返済買Bid/売Ask。VWAP価格で約定しない"),
        (["E01"], ["tick"], rules, "逆125/順250の先着", "全仮約定分母に期限/不足を残す。30分間引きは30分足ではない"),
        (["E02"], ["tick"], rules, "全X0：TP250/SL125・期限", "単一建玉・費用0/5/10pt感度。VWAPへの通常回帰出口は未使用")]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """最終合成・主/状態監査・対応・Viewerを明示判定で表示する。

    引数: study/output (Path) は試行/表示先。
    返り値: tuple[str,list[Path]] は検査表と出典。主と状態の項目数は合算しない。
    """
    rows, paths = [], []
    checks = [("合成検証.json", "編集終了済み最終合成"), ("独立監査.json", "先着・会計・集計"),
              ("状態独立確認.json", "全足参照・価格P・36発動集合"), ("補助対応診断.json", "7対照126期間群"), ("Viewer照合.json", "事前3分表示の代表照合")]
    if (study/"準備診断.json").exists():
        checks.append(("準備診断.json", "保存準備・分母診断"))
    for name, label in checks:
        path = study/name
        if not path.exists():
            rows.append([label, "未完・未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
        elif name == "補助対応診断.json":
            verdict, count = data.get("対応集合全件一致"), data["同じ仮約定の照合項目数"]
        elif name == "Viewer照合.json" and verdict is None:
            parts = data.get("照合", [])
            verdict, count = (all(p.get("一致") is True for p in parts) if parts else None), len(parts)
        rows.append([label, "合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n途中proofで固定せず、編集終了trueの最終合成39件と5SHA一致を確認して固定した。主監査が状態監査を参照するときは両件数を合算せず別掲する。同じ価格P/仮約定/市場観測を独立標本へ加算しない。正確な受信時計、空白内経路、将来の収益性は検査合格の証明範囲外。\n"
    text += G.table(["範囲", "明示判定", "件/項目数", "正本"], rows)
    state_path = study/"状態独立確認.json"
    if state_path.exists():
        data = G.read_json(state_path)
        fields = (("保存参照足数", "参照足"), ("保存価格発動数", "価格P"), ("保存入口数", "入口"), ("旧11同値比較価格数", "旧11の3/5分P全文同値"))
        scope = [number(data[key])+label for key, label in fields if key in data]
        text += "状態側は原順小列のas-of/基準/epoch/四点と位置・傾き、独立価格Pと全発動集合を確認した。"+("照合範囲："+"、".join(scope)+"。" if scope else "")+"主監査への件数重複加算はしない。\n\n"
    return text, paths


# ----------------------------------------
# 数値再生をせず、全正式検査が揃った保存結果だけをMarkdownへ写す。

def run(study: Path, output: Path) -> list[Path]:
    """固定36案を三文書へ転記する。

    引数: study/output (Path) は正式試行と表示先。
    返り値: list[Path] はREADME/設定と結果/全候補結果。結果・主・対応が未保存なら生成しない。
    """
    for name in ("条件.json", "計画.md", "入力台帳.json", "補助入力台帳.json", "固定.json", "結果.json", "独立監査.json", "補助対応診断.json"):
        if not (study/name).is_file():
            raise ValueError(name+"が未保存のため正式数値文書を生成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT/name) != expected for name, expected in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定されたcore・合成・条件・入力が変更されている")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("価格入力台帳参照が不一致")
    manifest, catalog = G.read_json(manifest_path), G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output/name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の1/3/5分×旧11のT1順行/R2反転×六VWAP条件＝36入口を、全X0固定36運用で比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も未見検証ではない。保存JSONの表示だけを行い、価格/参照/売買を再計算しない。\n\n"
    conclusion = f"**入口70目標は{report['入口70目標達成数']}/36、探索用費用資格は{report['費用資格数']}/36。** 支持・費用・品質・活動は全36で確認し、表示代表を採用と呼ばない。\n\n"
    timing = "## 判断原行へ結合する基準\n\n公開判断キー(confirm,confirm_line)までに存在した最新補助を原順で使い、前足終端VWAPとは呼ばない。同時計の次原行を混ぜず、cache省略列の違いから原行の完全一致は要求しない。repeatは同一状態の物理行数で約定数量ではない。補助最大キーが先行した場合や最新行が欠測/後退/不整合/先行数量時計なら参照不可とし、古い正常値へfallbackしない。\n\n"
    timing += "repeat全長は抽出後に確定するオフラインの出典metadata。参照dictへ保存するが位置/傾き/四点助走/注文/先着には使わない。参照dictの全列が当時の予測特徴という意味ではなく、将来学習で用いる場合は特徴を明示選択し、出典metadataを一括投入しない。\n\n"
    timing += "nativeの起算区間epochと、既知接頭基準からの正差分を別に保存。量/代金減少・数量時計後退・既知identity不一致で区間を切り基準を永久破棄。一時identity欠測は基準候補を不変保持してその行を除外し、手法の四点履歴は取り直す。初期累積を0と補わない。Day23という事後の可否一覧を朝の発動許可には使わず、各公開原行でオンライン判定する。\n\n"
    layers = "## 六条件の比較層\n"+G.table(["設定", "共通準備", "Pへの追加"], [["N_A", "N：native現＋連続3前・同epoch", "なし・同マスクの価格対照"], ["N_B", "N", "native位置strict"], ["N_C", "N", "N_B＋side×(native現−3足前)>0"], ["D_A", "D：N＋正差分四点・同基準", "なし・差分比較用の価格対照"], ["D_B", "D", "native位置strict"], ["D_D", "D", "差分位置strict"]])
    layers += "位置は順行T1でside×(確定C−線)>0、反転R2でside×(線−確定C)>0。位置/傾きの等号は不成立。N_A/BもCと同じ四点を待ち、D三条件も同じ共通準備に揃える。旧PのEMA20/ATR14/ADX14/BB20/前6足/当場15分準備を削らず、1分だけ新閾値へ変えない。\n\n"
    limits = "ラージBBOでmicro1枚代理、倍率10円/pt・片道11円・呼値5pt・新規/返済要求+1価格時計秒を仮定。新規有効30秒・残り60分・既存停止/期限、全X0 TP250/SL125を維持。VWAP価格で約定せず、VWAPへの通常回帰出口も今回未使用。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑り後の発動/再参加を再生したものではない。\n\n"
    limits += "数量時計<=価格時計等は必要条件だけで、VWAP/代金固有時計・受信時計や同時生成を保証しない。正常BBO空白300秒超・EOF・未解消のある全体の確定対象額はnullを維持する。MFE20/50/100pt後赤字は事後の観測峰に到達した取引の最終純赤字で、その峰で即利確できた実証ではない。場内最大DDは期間最大の一場で、全期間累積DDと区別する。\n\n"
    psychology = "基準付近での参加/手仕舞いや回帰は説明仮説で、注文主体・全参加者の建値を観測していない。線の位置と傾きは同じ価格/量の加工であり、独立した二票と数えない。"+G.link(ROOT/"docs/議論/VWAPの位置と傾きを価格入口へ加える.md", readme, "根拠と次の問い")+"、"+G.link(ROOT/"docs/議論/VWAP補助列を確定足へ結合する.md", readme, "結合設計")+"、"+G.link(ROOT/"study/00017_配信元VWAPと売買代金の入力監査/README.md", readme, "入力監査")+"を参照。\n\n"
    thresholds = "## 全固定条件\n"+G.table(["項目", "設定"], [[k, G.describe(v)] for k, v in config.items()])
    definition_table = "## 固定36評価と表示代表\n\nViewerは実行前に決めた3分12運用だけを保存。1/5分の結果も下表・全候補集計へ残し、無表示を未実行としない。\n"+G.table(["評価", "候補", "役割", "条件", "Viewer", "費用資格"], [[r["評価ID"], r["候補ID"], r["入口"]["役割"], r["入口"]["補助"], "表示" if r["入口"]["時間足分"] == 3 else "work全明細・正式集計", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_text, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00018：VWAPの位置と傾きで順行反転を比較\n\n"+intro+links+" / "+G.link(setting_path, readme)+" / "+G.link(all_path, readme)+"\n\n"+conclusion+layers+timing+preparation_table(study)+preparation_diagnosis(study, readme)+comparison_tables(entries, values)+auxiliary_diagnosis(study, readme)+definition_table+limits+psychology+audit_text
    viewer = "## 入力・閲覧・再現\n\n"+G.link(study/"入力台帳.json", readme)+" / "+G.link(study/"補助入力台帳.json", readme)+" / "+G.link(manifest_path, readme, "固定価格台帳")+"\n\n"
    viewer += f"市場root：{manifest['source_root']}。market_pathはこの設定root基準、pnl_pathはpath_base=catalogで一覧親基準。3分12の追加滑り0ptをViewerへ表示し原板を複製しない。全36の入口/運用、全足参照/価格発動はwork四gzipで展開SHA正本、正式には集約と事前表示12の約定を残す。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "参照品質.json", "入力品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study/name).exists():
            viewer += G.link(study/name, readme)+"\n\n"
    names = ["参照.py", "入口.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "補助対応診断.py", "準備診断.py"]
    viewer += "コード："+" / ".join(G.link(ROOT/"scripts/VWAP入口"/n, readme) for n in names if (ROOT/"scripts/VWAP入口"/n).exists())+" / "+G.link(ROOT/"scripts/テクニカル循環/入口.py", readme, "固定旧11価格P")+" / "+G.link(ROOT/"scripts/テクニカル循環/運用.py", readme, "固定X0")+"。\n\n"
    fence = chr(96)*3
    viewer += "保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/VWAP入口/レポート.py\n"+fence+"\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。固定版の最終合成は合成検証.py --finalでSHAを照合し、固定後変更を拒否する。固定後の追加検査は別ファイルへ分離する。\n\n"
    common = settings(rules)
    method_ids, scale_ids = {m["id"] for m in catalog["methods"]}, {s["id"] for s in catalog["scales"]}
    if any(set(s["手法ID"])-method_ids or set(s["尺度ID"])-scale_ids for s in common):
        raise ValueError("設定が汎用表の手法/尺度へ対応しない")
    mapping = "# 試行00018：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(all_path, setting_path)+"\n\n"
    mapping += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sは旧価格P/参照時点と共通N・D助走/位置・傾き/執行、R01〜R36は複合運用で指標単独効果ではない。VWAPは公開判断時点の値を1/3/5分足へ結合し、30分間引きは30分足の計算ではない。V01は累積数量の入力条件でRVOL未使用。通常VWAP回帰決済は未使用。\n\n"+G.matrix(catalog, setting_path, common)
    mapping += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    mapping += thresholds+layers+timing+preparation_diagnosis(study, setting_path)+definition_table+limits+psychology
    full_audits, _ = audits(study, all_path)
    full = "# 試行00018：全候補結果\n\n"+intro+conclusion+G.link(readme, all_path)+" / "+G.link(setting_path, all_path)+" / "+G.link(study/"結果.json", all_path)+"\n\n"+layers+timing+limits+thresholds+definition_table+preparation_table(study)+preparation_diagnosis(study, all_path, True)+comparison_tables(entries, values)+auxiliary_diagnosis(study, all_path, True)
    full += P.entry_table(entries).replace("8純入口", "36純入口")+P.operation_tables(values, refs, config).replace("8固定運用", "36固定運用")+full_audits
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER, study/"計画.md", study/"条件.json", study/"固定.json", study/"結果.json", study/"入力台帳.json", study/"補助入力台帳.json", manifest_path, study/"参照品質.json", study/"入口品質.json", *audit_paths]
    paths += [ROOT/"scripts/VWAP入口"/n for n in names if n != "レポート.py" and (ROOT/"scripts/VWAP入口"/n).exists()]
    paths += [ROOT/name for name in ("scripts/テクニカル循環/入口.py", "scripts/テクニカル循環/運用.py", "docs/議論/配信元VWAPとセッション起算を確認する.md", "docs/議論/VWAP補助列を確定足へ結合する.md", "docs/議論/VWAPの位置と傾きを価格入口へ加える.md")]
    for path, text in ((readme, summary+viewer), (setting_path, mapping), (all_path, full)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """保存結果と正式監査が揃った三文書を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。市場データ再計算や固定コードの変更は行わない。
    """
    parser = argparse.ArgumentParser(description="VWAP位置/傾きの固定36案を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
