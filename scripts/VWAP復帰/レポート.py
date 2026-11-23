"""00019の保存済み12入口と36運用を先着と通常出口へ分けて表示する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00019_VWAP復帰の入口と通常出口"
DISPLAY = ROOT/"scripts/収縮反転/レポート.py"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
FAMILIES = {"Q1": ("VWAP再獲得順行", "順行"), "Q2": ("VWAP乖離内復帰反転", "反転")}
EXTRAS = ("なし", "15分方向一致")
EXITS = ("X0", "X1", "X2")


def display_helper() -> Any:
    """既存の汎用表・先着・費用表示だけを読み込む。

    引数: なし。
    返り値: Any は表示module。価格や売買を再生しない。
    """
    spec = importlib.util.spec_from_file_location("VWAP復帰の帳票共通表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


P = display_helper()
G, number = P.G, P.number


def definitions(config: dict) -> list[dict]:
    """固定三尺度二役割二上位三出口を全36評価へ対応付ける。

    引数: config (dict) は条件正本。
    返り値: list[dict] は12入口・36運用・R01〜R36の定義。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != list(FAMILIES) or config["補助"] != list(EXTRAS) or config["出口"] != [{"出口ID": x} for x in EXITS]:
        raise ValueError("1/3/5分・Q1/Q2・二上位・三出口と異なる")
    if config["参照条件"] != {"連続点数": 4, "傾き差本数": 3, "判断時点": True} or (config["逆行pt"], config["順行pt"]) != (125, 250):
        raise ValueError("固定N4・判断時点・125/250と異なる")
    if config["運用"]["利確pt"] != 250 or config["運用"]["保護逆行pt"] != 125:
        raise ValueError("全出口のhard250/125が変化")
    rows = []
    for size in (1, 3, 5):
        for family, (name, role) in FAMILIES.items():
            for extra in EXTRAS:
                source = {"入口ID": f"{size}分_{family}_{extra}", "入口系統": family,
                          "時間足分": size, "補助": extra, "名称": name, "役割": role}
                for exit_id in EXITS:
                    rows.append({"候補ID": source["入口ID"]+"_"+exit_id, "入口": source,
                                 "出口": {"出口ID": exit_id}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """保存12入口・36運用と費用支持・品質・事前表示を検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は固定定義。
    返り値: tuple[dict,dict] は入口ID別/候補ID別の正本。再探索しない。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性/独立先着条件が不一致")
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 12 or len(report["入口評価"]) != 12 or len(values) != 36 or len(report["結果"]) != 36:
        raise ValueError("12入口・36運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("保存ID集合が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("保存定義が固定条件と不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            if row[period]["入口"] != entry[period]:
                raise ValueError("出口で入口先着が変化")
            item, n = row[period]["運用"], row[period]["運用"]["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n:
                raise ValueError("活動/取引数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("固定往復への費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意を含む全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["費用資格"]) != (support, bool(goal), qualified):
            raise ValueError("支持/70/費用資格が不一致")
    displayed = [r["候補ID"] for r in rules if r["入口"]["時間足分"] == 3]
    if report["表示固定ID"] != displayed or report["入口70目標達成数"] != sum(e["70目標"] for e in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("表示代表12または資格数が不一致")
    return entries, values


# ----------------------------------------
# 入口先着を出口の黒字率と分け、同じ入口に対する三出口を同じ行へ置く。

def comparison_tables(entries: dict, values: dict) -> str:
    """12入口の先着と三出口の費用後額を旧二期間で並べる。

    引数: entries/values (dict) は正本入口/運用。
    返り値: str は24行の比較と記述的所見。結果から候補を再選択しない。
    """
    rows = []
    for source, entry in entries.items():
        for period in PERIODS[:2]:
            e = entry[period]
            ops = [values[source+"_"+x][period]["運用"] for x in EXITS]
            rows.append([source, PERIOD_NAMES[period], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",
                         *[number(o["追加5pt純損益円"]) for o in ops], "/".join(str(o["完結取引数"]) for o in ops),
                         "/".join(str(o["品質注意場数"]) for o in ops)])
    positive = [cid for cid, row in values.items() if all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2])]
    text = "## 同じ入口と三出口の比較\n\n先着は12入口を一度だけ採点し三出口へ共通参照。X1/X2で小さい通常返済の黒字率が上がっても、250pt先着70%達成とはしない。金額は追加片道5ptの観測純額。注意場を含む全体の確定対象額は下段で未確定とする。\n"
    text += G.table(["入口", "期間", "250先着/仮約定・率", "X0追加5pt円", "X1追加5pt円", "X2追加5pt円", "X0/X1/X2完結", "X0/X1/X2注意場"], rows)
    text += "両旧期間で追加5pt後の観測純額が正の運用："+("、".join(positive) if positive else "なし")+"。観測黒字は支持・品質を満たす費用資格と別であり、最終1場の結果で旧期間の不足を補わない。\n\n"
    example = values["5分_Q1_なし_X0"]
    text += f"5分Q1なしX0は追加5pt後に学習{number(example['学習']['運用']['追加5pt純損益円'])}円/選択{number(example['条件選択']['運用']['追加5pt純損益円'])}円だが、学習注意{example['学習']['運用']['品質注意場数']}場を含むため全体確定額は未確定で、費用資格を満たさない。\n\n"
    for period in PERIODS[:2]:
        q2 = [values["3分_Q2_なし_"+x][period]["運用"]["追加5pt純損益円"] for x in EXITS]
        text += f"3分Q2なしの{PERIOD_NAMES[period]}はX0/X1/X2で追加5pt後{number(q2[0])}/{number(q2[1])}/{number(q2[2])}円。通常出口による損失縮小があっても黒字化とは呼ばない。\n\n"
    return text


def normal_tables(values: dict, refs: dict) -> str:
    """通常線による返済/更新とhard保護返済を全36運用で表示する。

    引数: values/refs (dict) は運用正本/評価対応。
    返り値: str は全108期間行。返済理由件数を先着率へ読み替えない。
    """
    rows = []
    for cid, row in values.items():
        for period in PERIODS:
            item = row[period]["運用"]
            rows.append([refs[cid], PERIOD_NAMES[period], item["完結取引数"], item["利確要求返済数"],
                         item["初期125保護返済数"], item["通常VWAP返済数"], item["VWAP起算失効返済数"], item["通常線更新回数"]])
    return "## 通常線の返済と更新\n\n全Xでhard TP250/SL125・期限を維持する。通常返済は順行逆抜けと反転到達を含む。TP/SL/通常/起算以外には期限等があり、この4理由だけで完結総数になるとは限らない。更新数は取引数ではない。\n"+G.table(["評価", "期間", "完結", "TP", "SL", "通常VWAP", "起算失効", "通常線更新"], rows)


def distance_table(study: Path) -> str:
    """正式3分表示のX1/X2で判断/実新規から通常線の距離を表示する。

    引数: study (Path) は正式試行。
    返り値: str は役割・出口・期間別の記述統計。全36の距離分布とは呼ばない。
    """
    groups = defaultdict(list)
    with (study/"固定候補_取引.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["出口ID"] in ("X1", "X2"):
                groups[(row["入口役割"], row["出口ID"], row["期間"])].append(row)
    rows = []
    for (role, exit_id, period), items in groups.items():
        a, b = [[float(item[key]) for item in items] for key in ("判断終値からnative方向距離pt", "実新規から初期通常線方向距離pt")]
        rows.append([role, exit_id, PERIOD_NAMES[period], len(items),
                     f"{number(min(a))}/{number(statistics.median(a))}/{number(max(a))}",
                     f"{number(min(b))}/{number(statistics.median(b))}/{number(max(b))}",
                     sum(value <= 2.2 for value in b), sum(value <= 0 for value in b)])
    text = "## 判断と実新規から通常線までの距離\n\n正式3分12運用の完結取引CSVだけを表示する。全36の分布ではなく、同じ原入口がX1/X2や方向条件で重複し得る記述統計。両列はside×(入口native−基準価格)、基準はそれぞれ判断終値/実新規価格。順行では通常負、反転では通常正で、絶対値ではない。判断から+1秒以上待つ間の価格移動/スプレッドにより距離が変わる。反転で実距離<=0も除外せず、実新規後に通常要求して往復費用を負う。\n\n"
    text += "<=2.2ptは往復22円/倍率10の単純費用目安で、黒字可能性を判定する厳密閾値ではない。返済待機/返済気配/滑りを含まず、順行の負距離にも同じ列を表示するため、順行を『目標が近い』と読む列ではない。結果を見た小距離除外はしていない。\n"
    return text+G.table(["役割", "出口", "期間", "完結", "判断距離min/中央値/max pt", "実距離min/中央値/max pt", "実距離<=2.2", "実距離<=0"], rows)


def auxiliary_diagnosis(study: Path, output: Path, full: bool = False) -> str:
    """保存された対応診断を任意表示し未保存なら未完を明示する。

    引数: study/output (Path) は試行/文書出力先、full (bool) は全36の距離を別掲する指定。
    返り値: str は対応診断のリンクと保存済み集計。市場経路は再生しない。
    """
    path = study/"対応診断.json"
    if not path.exists():
        return "## 共通新規と参加集合の診断\n\n未完・正式対応診断は未保存。同じ入口でも早期返済で後続参加が変わるため、総純額差を同じ取引の利益回収差とはしない。保存後に帳票を再生成する。\n\n"
    data = G.read_json(path)
    if "結果SHA256" in data and data["結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("対応診断の結果SHAが不一致")
    verdict = "全件一致" if data.get("対応集合全件一致") is True else "不一致または未確認"
    text = "## 共通新規と参加集合の診断\n\n"+G.link(path, output)+f"は{data['対照期間群数']}期間群・{number(data['照合項目数'])}項目{verdict}。同じ実新規の出口差と、早期返済/抑止で増減する片側だけの参加を分ける。X0のMFE20/50/100到達取引を起点にした対応も、X1/X2の短い観測区間の単純比較と分けて読む。事後MFE峰で即利確できた証明ではない。\n\n"
    selected = [r for r in data["結果"] if r["足分"] == 3 and r["比較"] == "出口" and "_なし_" in r["左"] and r["期間"] != "後続検査"]
    rows, mfe_rows = [], []
    for row in selected:
        part = row["運用比較"]
        participation = part["右側のみ純額円"]-part["左側のみ純額円"]
        if not math.isclose(part["全運用純額差円"], part["共通実新規純額差円"]+participation, abs_tol=1e-8):
            raise ValueError("対応診断の参加集合会計が不一致")
        prefix = [row["左"], row["右"], PERIOD_NAMES[row["期間"]]]
        rows.append(prefix+[row["比較"], f"{part['共通実新規数']}/{part['左側のみ実新規数']}/{part['右側のみ実新規数']}",
            number(part["共通実新規純額差円"]), number(participation), number(part["全運用純額差円"]),
            part["左赤字から右黒字数"], part["左黒字から右赤字数"]])
        if row["比較"] == "出口":
            for item in part["左保有区間を基準とした利益消失"]:
                mfe_rows.append(prefix+[item["左MFE下限pt"], item["共通実新規数"], item["左純赤字数"],
                    item["右純赤字数"], item["左赤字から右黒字数"], number(item["共通純額差円"])])
    text += "全運用差＝共通実新規の右−左純額差＋右側のみ純額−左側のみ純額。共通の照合単位は同じ実新規であり、入口候補だけの対応とは異なる。下表は事前表示と同じ3分・上位なしの旧二期間を記述し、15分方向選別を含む全162群は対応診断.jsonへ残して同じ大表の重複を避ける。\n"
    text += G.table(["左", "右", "期間", "比較", "共通/左のみ/右のみ新規", "共通出口差円", "参加集合差円", "全純額差円", "赤→黒", "黒→赤"], rows)
    if not full:
        text += "事前表示の3分・上位なしでは、Q1のX0→X1の共通新規差は学習−12,000円/選択−5,400円、Q2は＋17,800円/＋25,200円。同じ通常線でも役割で作用が異なり、入口の常時固定や出口の一律短縮だけで改善が保証されない。これはこの保存標本の記述であり、当時のテクニカル局面から有利な役割を予測できた証明ではない。\n\n"
    text += "### 左の保有区間を固定したMFE後赤字\n\n左がMFE幅へ達した共通新規を分母に固定し、その同じ新規の左右最終額を比較。左の到達後に右が実際も同じ峰へ達した意味ではなく、右で早く終えた取引を後の峰で選別する事後診断である。右のみ参加した取引もこの表には含まない。\n"
    text += G.table(["左", "右", "期間", "左MFE下限pt", "共通新規", "左純赤字", "右純赤字", "赤→黒", "共通右−左純額円"], mfe_rows)
    if full:
        text += "### 全36の実新規から初期nativeまでの距離\n\nside×(入口native−実新規価格)の記述統計。X0には通常線出口がないが、同じ入口参照への仮想距離を残す。非正/12.2pt以下の件数は順行の負距離も含むので、小目標の件数とは読まない。12.2ptは往復22円＋追加片道5pt相当の単純費用幅であり、返済待機や経路を含む実現可能益の証明ではない。\n"
        text += G.table(["候補", "期間", "件数", "min pt", "中央値pt", "max pt", "非正", "<=12.2pt"],
            [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["件数"], *[number(r.get("実新規から初期通常線方向距離pt_"+suffix)) for suffix in ("最小", "中央値", "最大")], r["非正距離数"], r["12.2pt以下距離数"]] for r in data["通常線距離"]])
    return text


# ----------------------------------------
# 使用指標と尺度を明示し、通常線決済を入力の位置選別と混ぜない。

def settings(rules: list[dict]) -> list[dict]:
    """51×9表へ全使用セルと固定閾値・複合評価を対応付ける。

    引数: rules (list[dict]) は36複合評価。
    返り値: list[dict] は設定S。下位未使用指標へ利用済み印を付けない。
    """
    groups = []
    for size in (1, 3, 5):
        scale = [f"m{size:02d}"]
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        q1, q2 = [[r for r in same if r["入口"]["入口系統"] == q] for q in FAMILIES]
        normal = [r for r in same if r["出口"]["出口ID"] != "X0"]
        groups += [
            (["I12"], scale, same, "native現＋連続3前・同epoch N4", "現N4だけ。前足自身のN4は不要、同場隣接公開/確認遅延<=30。D差分未使用"),
            (["I09"], scale, same, "Wilder ATR14：現/前とも有限正", "Q2は各時点ATRを使用。下位EMA/ADX/RSI/BBをgateにしない"),
            (["I12", "P05"], scale, q1, "Q1：前距離<=0→現>0・native3前傾き>0", "side方向の終値改善strictも要求。nativeの位置変化を直接発動とする"),
            (["I12", "I09", "P09"], scale, q2, "Q2：前距離<−前ATR、−現ATR<=現距離<0", "終値改善strict。1ATR外から内へ復帰して線の手前。native傾きは条件にしない"),
            (["I12", "E02"], scale, normal, "X1入口native固定/X2有効公開native更新", "順行逆抜け<=0/反転到達>=0。全hardTP250/SL125維持。X2更新のみend>実新規"),
        ]
    groups += [
        (["I01", "C07"], ["m15"], rules, "公開15分EMA20と前値は全入口共通準備", "なしは方向制約だけ省略。一致は実sideとC>EMA20>前値/鏡像。下位終了/公開key以下"),
        (["I12", "V01"], ["tick"], rules, "当場量時計/正値/比率整合/identityを満たす最新raw", "累積数量はnative入力の整合条件。RVOLや数量フロー手法は未使用。固有時計なし"),
        (["B01"], ["tick"], rules, "ラージBBO代理・全要求+1価格時計秒", "micro1枚。新規買Ask/売Bid、返済買Bid/売Ask。native価格で約定しない"),
        (["E01"], ["tick"], rules, "独立125逆行/250順行の先着", "全仮約定分母に期限/不足を残す。12入口一度採点、通常出口の黒字率とは別"),
        (["E02"], ["tick"], rules, "hard125→hard250→通常線・期限優先", "通常線は全要求後+1秒正常BBO。既存返済待機は上書きせずepoch失効/同原行更新を記録"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """明示合否がある正式合成/会計/状態/出口/対応/Viewerを別掲する。

    引数: study/output (Path) は試行/表示先。
    返り値: tuple[str,list[Path]] は状態表/出典。主と独立子の項目数は合算しない。
    """
    rows, paths = [], []
    checks = [("合成検証.json", "編集終了済み最終合成"), ("独立監査.json", "先着・会計・集計"),
              ("状態独立確認.json", "全足参照・Q候補・12発動集合"), ("通常出口独立確認.json", "X1/X2初着要求・通常線"),
              ("対応診断.json", "同新規出口差と参加集合"), ("Viewer照合.json", "事前3分表示のAPI照合")]
    for name, label in checks:
        path = study/name
        if not path.exists():
            rows.append([label, "未完・未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
        elif name == "対応診断.json" and verdict is None:
            verdict, count = data.get("対応集合全件一致"), data.get("照合項目数")
        elif name == "Viewer照合.json" and verdict is None:
            parts = data.get("照合", [])
            verdict, count = (all(p.get("一致") is True for p in parts) if parts else None), len(parts)
        rows.append([label, "合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n最終合成は35件・編集終了true/5SHA一致後に固定。途中proofで開始しない。主会計、状態6,741,381項目、通常出口1,207,742項目は確認範囲が重なるため合算せず別掲する。保存ファイルの存在だけで合格とせず、以下は明示判定を読む。\n"
    text += G.table(["範囲", "明示判定", "件/項目数", "正本"], rows)
    text += "状態側は全56,351参照足・Q候補1,421・入口1,990、出口側はX1/X2の3,291完結・通常線ログ29,384行を照合した。原板全行を新しく別抽出した証明ではない。固有受信時計/空白内経路/将来の収益性は検査合格の範囲外。未保存検査は未完のまま表示し、保存後再生成する。\n\n"
    viewer_path = study/"Viewer照合.json"
    if viewer_path.exists():
        data = G.read_json(viewer_path)
        text += "### Viewerの表示確認\n\n"+str(data["接続先"])+"、設定 "+str(data["設定"])+"、市場rootはAPI情報のdata_rootを使用。Hidden起動で隣repoは変更しない。以下は事前3分表示12の中のQ1/Q2同入口三出口6資源で、全12資源をAPI表示確認したという意味ではない。PNG追加は"+str(data["追加PNG数"])+"枚。\n"
        text += G.table(["候補", "場", "研究純額円", "API実現円", "API買/売保有", "数値指紋", "一致"],
            [[r["手法"], r["場"], number(r["研究側純損益円"]), number(r["API最終状態"]["realized_pnl_yen"]),
              f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}",
              "一致" if r["数値本文SHA256一致"] else "不一致", "一致" if r["一致"] else "不一致"] for r in data["照合"]])
    return text, paths


# ----------------------------------------
# 正式数値を変更せず、指紋を照合した保存結果のみ三Markdownへ転記する。

def run(study: Path, output: Path) -> list[Path]:
    """保存12入口/36運用をREADME・設定と結果・全候補結果へ転記する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: list[Path] は三文書。監査未保存時は未完表示を維持する。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json", "補助入力台帳.json"):
        if not (study/name).is_file():
            raise ValueError(name+"が未保存")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT/name) != expected for name, expected in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定core/合成/条件/入力のSHAが変化")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("価格入力台帳の参照SHA不一致")
    aux_pointer = G.read_json(study/"補助入力台帳.json")
    aux_paths = [(study/aux_pointer["参照"]).resolve(), (study/aux_pointer["作業台帳参照"]).resolve()]
    if any(G.sha(path) != aux_pointer[key] for path, key in zip(aux_paths, ("SHA256", "作業台帳SHA256"))):
        raise ValueError("補助結果/作業台帳の参照SHA不一致")
    manifest, catalog = G.read_json(manifest_path), G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output/name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の1/3/5分×Q1再獲得順行/Q2ATR乖離内復帰×上位方向2条件＝12入口を、各X0/X1/X2の36運用で比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も未見検証ではない。保存結果の表示だけを行い、価格・補助・注文を再生しない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/12、探索用費用資格は{report['費用資格数']}/36。** 通常出口の黒字率と250pt先着率を分け、3分表示代表を採用と呼ばない。\n\n"
    layers = "## 入口と出口の固定条件\n\nsideは買1/売−1。Cは確定終値、Vはその公開判断キーのnative、Aはその尺度のATR14。\n"
    layers += G.table(["入口", "役割", "発動"], [["Q1", "順行", "side×(前C−前V)<=0→side×(C−V)>0、side×(V−V3)>0、side×(C−前C)>0"], ["Q2", "反転", "side×(前C−前V)<−前A、−現A<=side×(C−V)<0、side×(C−前C)>0"]])
    layers += "全入口は現N4（native現＋連続3前・同epoch）、現/前ATR14有限正、同場隣接公開前足、現在公開15分EMA20/前値、確認遅延<=30秒を共通要求。前足自身のN4は不要。上位なしは方向制約だけ省略し、15分方向一致は実sideとC15>EMA20>前EMA/鏡像が一致。下位EMA/BB/ADX/RSI、RVOL、当場差分VWAPはgateに使わない。\n\n"
    layers += G.table(["出口", "通常線", "返済"], [["X0", "なし・旧11CORE.replay直接", "hardTP250/SL125・期限"], ["X1", "入口要求signalのnativeを固定", "hard条件＋順行逆抜け/反転到達"], ["X2", "X1初期値→有効保有後公開nativeへ更新", "hard条件＋同じ通常閾値"]])
    timing = "## 通常線と原順\n\n全Xでhard TP250/SL125・期限を維持し、旧00011のX1/X2とは別定義。返済markは買Bid/売Ask、順行side×(mark−line)<=0、反転>=0で要求。nativeを呼値へ丸めず、線価格での約定も作らず、さらに1価格時計秒以上後の最初正常BBOで返済する。新規時点ですでに線を超えても実新規を除外せず同原行で返済要求し往復費用を負う。\n\n"
    timing += "同原行はquote→公開足→signal。期限/既存要求を先に処理し、quoteのhard125→hard250→通常線を維持。既存pendingを通常線で上書きしない。X2更新だけend>実新規を要求し、native現在有効ならN4未回復でも更新できる。通常線は上下とも更新し単調追尾ではない。不正/欠測参照では既知建玉の線を据置く。新規特徴を過去正常値へ補完する操作とは別。\n\n"
    timing += "保有中に知れた有効公開nativeのepoch不一致はX1/X2とも失効要求。epochにはend>実新規も同key正常BBOも不要。X2更新直後の価格閾値だけは最新正常BBO(clock,line)==確認keyを要求し、古いBBOで新しい線の到達を作らない。\n\n"
    timing += "固定18参照は公開判断keyまでの原順as-of、同時計次原行不可、最大既知キー先行/最新不正から古正常へfallback不可。固有VWAP/代金時計と正確な受信時計は未収録。repeat全長は抽出後に分かるオフライン出典metadataであり、入口・注文・先着の特徴へ使わない。参照dict全列が当時の予測特徴という意味ではない。\n\n"
    limits = "## 費用と解釈の限界\n\nラージBBOでmicro1枚代理、倍率10円/pt・呼値5pt・片道11円・新規/返済要求+1価格時計秒、新規有効30秒・停止前・期限残60分を仮定。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑り後の判断や再参加を再生したものではない。300秒超正常BBO空白/EOF/未解消を含む全体確定対象額はnullを維持する。\n\n"
    limits += "MFE20/50/100pt後純赤字は観測した事後峰と最終純額の関係で、その峰で回収可能だった証明ではない。通常出口は観測保有区間自体を短くし後続参加も変える。同じ実新規の出口差・X0を基準にした到達後の対応・片側だけの参加を分け、単純な赤字件数減少を利確改善と断定しない。最大場内DDは期間最大の一場で全期間累積DDではない。\n\n"
    limits += "VWAP近辺への戻り/再獲得を需給の説明仮説として扱うが、参加者の建値・心理・全約定を直接観測していない。Q1/Q2の苦手局面を挙げるだけでは切替の有効性は示せない。本試行は固定手法/出口の対照であり、局面判別による順行/反転/待機の切替は別試行で当時の情報だけを使って確認する。\n\n"
    thresholds = "## 全固定条件\n"+G.table(["項目", "設定"], [[k, G.describe(v)] for k, v in config.items()])
    definition_table = "## 全36評価と事前表示\n\n全12入口の先着と全36運用を記録。Viewerは事前の3分12運用だけ、1/5分明細はwork指紋と正式集計へ残し、表示なしを未実行としない。\n"+G.table(["評価", "候補", "役割", "出口", "Viewer", "費用資格"], [[r["評価ID"], r["候補ID"], r["入口"]["役割"], r["出口"]["出口ID"], "表示" if r["入口"]["時間足分"] == 3 else "work明細・正式集計", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_text, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00019：VWAP復帰の入口と通常出口\n\n"+intro+links+" / "+G.link(setting_path, readme)+" / "+G.link(all_path, readme)+"\n\n"+conclusion+layers+timing+comparison_tables(entries, values)+distance_table(study)+auxiliary_diagnosis(study, readme)+limits+audit_text
    viewer = "## 入力・閲覧・再現\n\n"+G.link(study/"入力台帳.json", readme)+" / "+G.link(study/"補助入力台帳.json", readme)+" / "+G.link(manifest_path, readme, "固定価格台帳")+"\n\n"
    viewer += f"市場rootは{manifest['source_root']}。market_pathはViewer設定の市場root基準、pnl_pathはpath_base=catalogで一覧親基準。追加滑り0ptの3分12運用を表示し、原板を複製しない。全36運用と通常線ログはGit外work五gzipに保存し、正式には展開SHA/サイズを記録する。\n\n"
    artifacts = ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "参照品質.json", "入力品質.json", "作業成果物.json", "Viewer照合.json")
    viewer += " / ".join(G.link(study/name, readme) for name in artifacts if (study/name).exists())+"\n\n"
    names = ("入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "通常出口独立確認.py", "対応診断.py")
    sources = [ROOT/"scripts/VWAP復帰"/n for n in names if (ROOT/"scripts/VWAP復帰"/n).exists()]
    viewer += "コード："+" / ".join(G.link(p, readme) for p in sources)+" / "+G.link(ROOT/"scripts/VWAP入口/参照.py", readme, "固定18参照")+" / "+G.link(ROOT/"scripts/テクニカル循環/運用.py", readme, "固定X0")+"。\n\n"
    docs = [ROOT/"docs/議論"/n for n in ("配信元VWAPとセッション起算を確認する.md", "VWAP補助列を確定足へ結合する.md", "VWAPの位置と傾きを価格入口へ加える.md", "VWAP復帰と通常出口を対応させる.md")]
    viewer += "背景："+" / ".join(G.link(p, readme) for p in docs)+"。\n\n"
    fence = chr(96)*3
    viewer += "保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/VWAP復帰/レポート.py\n"+fence+"\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。合成検証.py --finalは固定5SHAを確認し、固定後変更を拒否する。追加検査は別ファイルへ分離する。\n\n"
    common = settings(rules)
    method_ids, scale_ids = {m["id"] for m in catalog["methods"]}, {s["id"] for s in catalog["scales"]}
    if any(set(s["手法ID"])-method_ids or set(s["尺度ID"])-scale_ids for s in common):
        raise ValueError("設定が51×9カタログへ対応しない")
    mapping = "# 試行00019：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(all_path, setting_path)+"\n\n"
    mapping += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sはnative/ATR/上位/執行/通常出口、R01〜R36は複合運用。下位EMA/BB/ADX/RSIは未使用、数量はnative内部条件だけでRVOL未使用。30分間引きは30分足ではない。\n\n"+G.matrix(catalog, setting_path, common)
    mapping += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    mapping += thresholds+layers+timing+definition_table+limits+audits(study, setting_path)[0]
    full = "# 試行00019：全候補結果\n\n"+intro+conclusion+G.link(readme, all_path)+" / "+G.link(setting_path, all_path)+" / "+G.link(study/"結果.json", all_path)+"\n\n"+layers+timing+limits+thresholds+definition_table
    full += comparison_tables(entries, values)+P.entry_table(entries).replace("8純入口", "12純入口")
    operations = P.operation_tables(values, refs, config).replace("8固定運用", "36固定運用").replace("全案X0＝TP250/SL125・期限。", "全案でTP250/SL125・期限を維持しX1/X2は通常線出口を追加。")
    full += operations+normal_tables(values, refs)+distance_table(study)+auxiliary_diagnosis(study, all_path, True)+audits(study, all_path)[0]
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER,
             *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "補助入力台帳.json", "参照品質.json", "入口品質.json", "固定候補_取引.csv", "作業成果物.json")],
             manifest_path, *aux_paths, *audit_paths, *sources, *docs, ROOT/"scripts/VWAP入口/参照.py", ROOT/"scripts/テクニカル循環/運用.py"]
    for path, text in ((readme, summary+viewer), (setting_path, mapping), (all_path, full)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """正式保存結果から三文書を生成する。

    引数: なし。--study/--outputは任意の試行/表示先。
    返り値: None。売買・先着・入力再計算は行わない。
    """
    parser = argparse.ArgumentParser(description="VWAP復帰と通常出口の保存結果を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study, args.output or args.study)))


if __name__ == "__main__":
    main()
