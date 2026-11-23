"""00014の保存済み12入口・12X0運用を3Markdownと51×9表へ転記する。"""

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
STUDY = ROOT / "study/00014_反転入口と観測差分量"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
DISPLAY_HELPER = ROOT / "scripts/収縮反転/レポート.py"


def display_helper() -> Any:
    """旧帳票の汎用表示と入口件数検査だけを読み込む。

    引数: なし。
    返り値: Any は表・リンク・費用表示の補助。原板・特徴・売買処理は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("数量反転の共通帳票表示", DISPLAY_HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


P = display_helper()
G, number = P.G, P.number


def definitions(config: dict) -> list[dict]:
    """固定3足・2価格系統・2数量補助を列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は12入口・12運用・R01〜R12の対応。
    """
    if config["時間足分"] != [1, 3, 5] or config["入口系統"] != ["R1", "R2"] or config["補助"] != ["なし", "RVOL1.2以上"] or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("固定3足×2価格系統×2補助・X0と異なる")
    if (config["数量条件"]["参照足数"], config["数量条件"]["RVOL下限"], config["数量条件"]["数量準備両側共通"], config["逆行pt"], config["順行pt"]) != (20, 1.2, True, 125, 250):
        raise ValueError("数量20足・RVOL1.2・両側共通準備・125/250と異なる")
    names = {"R1": "端の失敗突破", "R2": "BB内復帰"}
    rows = []
    for size in config["時間足分"]:
        for family in config["入口系統"]:
            for extra in config["補助"]:
                source = {"入口ID": f"{size}分_{family}_{extra}", "入口系統": family, "時間足分": size,
                          "補助": extra, "名称": names[family], "役割": "反転"}
                rows.append({"候補ID": source["入口ID"] + "_X0", "入口": source, "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """保存12入口・12運用の件数・率・費用・資格を検査する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は固定定義。
    返り値: tuple[dict,dict] は入口ID別/候補ID別の正本値。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または入口評価が不一致")
    entries, values = ({r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]})
    if len(entries) != 12 or len(report["入口評価"]) != 12 or len(values) != 12 or len(report["結果"]) != 12:
        raise ValueError("固定12入口・12運用と異なる")
    if entries.keys() != {r["入口"]["入口ID"] for r in rules} or values.keys() != {r["候補ID"] for r in rules}:
        raise ValueError("保存候補IDが固定定義と不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("入口・運用定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            if row[period]["入口"] != entry[period]:
                raise ValueError("入口集計が運用欄と不一致")
            item, n = row[period]["運用"], row[period]["運用"]["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"] + item["無取引場数"] != sessions or item["買い取引数"] + item["売り取引数"] != n or not 0 <= item["黒字取引数"] <= n:
                raise ValueError("運用件数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"] - 20 * slip * n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意場を含む全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["費用資格"]) != (support, bool(goal), qualified):
            raise ValueError("支持・入口目標・費用資格が不一致")
    if report["表示固定ID"] != [r["候補ID"] for r in rules] or report["入口70目標達成数"] != sum(e["70目標"] for e in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("全12表示または資格集計が不一致")
    return entries, values


# ----------------------------------------
# 元価格入口・共通数量助走・RVOL追加選別を別々に表示する。

def quantity_tables(study: Path) -> str:
    """保存品質から数量準備の除外と足数を表示する。

    引数: study (Path) は試行。
    返り値: str は準備・数量品質の表。元価格入口は観測足数と区別する。
    """
    entry_path, quantity_path = study/"入口品質.json", study/"数量品質.json"
    if not entry_path.exists() or not quantity_path.exists():
        return "## 数量の準備と除外\n\n数量品質または元価格入口の集計が未保存。\n\n"
    totals, reasons, quantity = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for row in G.read_json(entry_path):
        key = row["時間足分"], row["期間"]
        for name in ("基準価格入口数", "数量準備除外数", "数量準備通過数", "RVOL補助除外数"):
            totals[key][name] += row[name]
        reasons[key].update(row.get("数量準備除外理由", {}))
        if row["基準価格入口数"] != row["数量準備除外数"] + row["数量準備通過数"]:
            raise ValueError("元価格入口と数量準備除外が不一致")
    for row in G.read_json(quantity_path):
        key = row["時間足分"], row["期間"]
        for name, value in row.items():
            if isinstance(value, (int, float)) and name not in ("時間足分", "最大数量時計先行秒", "最大数量時計遅延秒"):
                quantity[key][name] += value
    selected, foot_rows = [], []
    for size in (1, 3, 5):
        for period in PERIODS:
            item, q = totals[(size, period)], quantity[(size, period)]
            selected.append([size, PERIOD_NAMES[period], item["基準価格入口数"], item["数量準備除外数"], item["数量準備通過数"],
                             item["RVOL補助除外数"], item["数量準備通過数"]-item["RVOL補助除外数"], G.describe(dict(reasons[(size, period)]))])
            foot_rows.append([size, PERIOD_NAMES[period], q["数量価格足数"], q["数量基準完全足数"], q["数量基準不完全足数"],
                              q["数量準備済足数"], q["公開数量準備済足数"], q["数量時計先行観測数"],
                              q["数量欠測不正観測数"], q["数量時計欠測不正観測数"], q["無価格枠後基準切替数"]])
    text = "## 数量の準備で元価格入口から何を除いたか\n\n元価格入口は固定00011の価格・ADX<20・中心有利・共通準備・時間条件を通った発動で、数量条件をまだ付けていない。数量準備を両側共通に要求し、通過分が補助なし入口、そこからRVOL<1.2を除いた分が数量補助入口となる。R1/R2が同じ足で発動すれば別入口として数えるため、価格足数とは違う。確認遅延による未約定はこの後に別記する。\n"
    text += G.table(["足分", "期間", "元価格入口", "共通数量準備で除外", "通過=なし入口", "RVOL<1.2で除外", "RVOL条件入口", "数量準備除外理由"], selected)
    text += "### 数量足の品質\n\n基準完全は定義上の観測累積差分が利用可能な状態で、真の全約定の完全収録を意味しない。数量準備済と価格の公開は別状態。各尺度は同じ原観測を参照するため、先行/欠測観測数を尺度間で足して別観測の件数にしない。\n"
    return text + G.table(["足分", "期間", "価格数量足", "基準完全", "基準不完全", "数量準備済", "公開かつ準備済", "数量時計先行", "数量欠測不正", "数量時計欠測不正", "無価格枠後再基準"], foot_rows)


def quantity_summary(study: Path, output: Path) -> str:
    """数量準備と公開済み準備の全65場合計を別々に表示する。

    引数: study/output (Path) は試行と表示先。
    返り値: str は尺度別の数量足数、事前照合の範囲、利用可能集合の注意。
    """
    path = study/"数量品質.json"
    if not path.exists():
        return ""
    totals = defaultdict(Counter)
    fields = ("数量価格足数", "数量基準完全足数", "数量基準不完全足数", "数量準備済足数", "公開数量準備済足数")
    for row in G.read_json(path):
        totals[row["時間足分"]].update({name: row.get(name, 0) for name in fields})
    rows = []
    for size in (1, 3, 5):
        item = totals[size]
        if item["数量価格足数"] != item["数量基準完全足数"] + item["数量基準不完全足数"] or item["公開数量準備済足数"] > item["数量準備済足数"]:
            raise ValueError("全65場の数量完全性・公開準備数が不一致")
        rows.append([size, *[number(item[name]) for name in fields], number(item["数量準備済足数"] - item["公開数量準備済足数"])])
    text = "## 足幅と利用可能な数量集合\n\n全65場の合計。数量準備済は量の状態で、公開済み価格足で利用できるとは限らない。\n"
    text += G.table(["足分", "価格数量足", "基準完全", "基準不完全", "数量準備済", "公開かつ準備済", "準備済だが非公開"], rows)
    text += "1分は欠枠と不完全足の後に20本の助走を数え直す影響が大きく、3/5分と価格条件だけを変えた比較にはならない。5分の準備済と公開済みの差には非公開末尾が含まれる。さらに価格R1/R2準備と時間条件で絞るため、この表の足数を入口数・仮約定数と取り違えない。\n\n"
    precheck = study/"数量事前照合.json"
    if precheck.exists():
        data = G.read_json(precheck)
        text += G.link(precheck, output) + "は旧5分保存監査の共通10項目×65場＝" + number(data["照合項目数"]) + "項目の事前入力ゲート。合否は" + ("全件一致" if data.get("全件一致") is True else "不一致または未確認") + "。数量.pyを用いた比較で、入口先着・損益は実行しておらず、後の独立数量再構成とは別の検査である。無価格枠後の再基準化など追加仕様が旧定義と常に同一であるとは示さない。\n\n"
    return text


def findings(entries: dict, values: dict) -> str:
    """6組のRVOLありなしを旧二期間で比較する。

    引数: entries/values (dict) は12入口/12運用の保存値。
    返り値: str は記述表。新しい閾値の選定は行わない。
    """
    rows = []
    for size in (1, 3, 5):
        for family in ("R1", "R2"):
            for period in PERIODS[:2]:
                a, b = [entries[f"{size}分_{family}_{extra}"][period] for extra in ("なし", "RVOL1.2以上")]
                qa, qb = [values[f"{size}分_{family}_{extra}_X0"][period]["運用"] for extra in ("なし", "RVOL1.2以上")]
                rows.append([size, family, PERIOD_NAMES[period], f"{a['順行先着']}/{a['約定候補数']}・{G.pct(a['確認率'])}",
                             f"{b['順行先着']}/{b['約定候補数']}・{G.pct(b['確認率'])}", f"{a['約定候補数']}/{b['約定候補数']}",
                             number(qa["追加5pt純損益円"]), number(qb["追加5pt純損益円"])])
    text = "## 共通助走後のRVOL条件あり・なし\n\n両側とも当足基準完全・直前20数量足・正の平均を必要とする。RVOL>=1.2の効果と、数量準備そのものによる除外を混ぜない。数量条件は入口選別だけに使い、開いた建玉を取り消す条件にはしない。\n"
    text += G.table(["足分", "価格系統", "期間", "なし：順/仮約定・率", "RVOL：順/仮約定・率", "仮約定数 なし/RVOL", "なし：追加5pt純額", "RVOL：追加5pt純額"], rows)
    sample = values["3分_R2_RVOL1.2以上_X0"]
    a, b = [sample[p] for p in PERIODS[:2]]
    text += "3分R2のRVOL条件は追加片道10pt後にも学習" + number(a["運用"]["追加10pt純損益円"]) + "円、条件選択" + number(b["運用"]["追加10pt純損益円"]) + "円を観測した。ただし学習は品質注意" + number(a["運用"]["品質注意場数"]) + "場を含み全体確定額は未確定。入口は学習" + str(a["入口"]["順行先着"]) + "/" + str(a["入口"]["約定候補数"]) + "＝" + G.pct(a["入口"]["確認率"]) + "、条件選択" + str(b["入口"]["順行先着"]) + "/" + str(b["入口"]["約定候補数"]) + "＝" + G.pct(b["入口"]["確認率"]) + "で70%に届かず、費用資格も満たしていない。正額の部分だけを理由に採用とはしない。\n\n"
    text += "5分R2では数量補助後の追加5pt純額が両期間で低下して赤字となる。数量増加はこの固定条件で一様な改善要因ではない。共通数量助走による母集団変更、RVOLによる入口選別、単一建玉での参加集合変更を分け、将来の未見期間での再現性を今回の既使用65場から推定しない。\n\n"
    return text


def auxiliary_diagnosis(study: Path, output: Path) -> str:
    """任意の同じ仮約定と運用参加集合差の診断を表示する。

    引数: study/output (Path) は試行/出力。
    返り値: str は6組×3期間の対応表。未保存なら空文字列。
    """
    path = study/"補助対応診断.json"
    if not path.exists():
        return ""
    data = G.read_json(path)
    if data["結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("補助対応診断と結果SHAが不一致")
    rows = []
    for row in data["結果"]:
        pair = row["運用比較"]
        if row["元の価格入口数"] - row["共通数量準備で除く入口数"] != row["補助なし入口数"] or row["補助なし入口数"] - row["RVOL1.2未満で除く入口数"] != row["RVOL条件入口数"]:
            raise ValueError("補助対応の入口集合数が不一致")
        difference = pair["RVOL条件のみ純額円"] - pair["なし側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"], pair["共通実新規純額差円"] + difference, abs_tol=1e-8):
            raise ValueError("運用参加集合差の接合が不一致")
        rows.append([row["足分"], row["系統"], PERIOD_NAMES[row["期間"]], row["元の価格入口数"], row["共通数量準備で除く入口数"],
                     row["補助なし入口数"], row["RVOL条件入口数"],
                     f"{pair['共通実新規数']}/{pair['なし側のみ実新規数']}/{pair['RVOL条件のみ実新規数']}",
                     number(pair["共通実新規純額差円"]), number(difference), number(pair["全運用純額差円"])])
    status = "全件一致" if data.get("対応集合全件一致") is True else "不一致または未確認"
    text = "## 同じ仮約定と運用参加集合の診断\n\n" + G.link(path, output) + "の対応検査は" + status + "、照合" + number(data["同じ仮約定の照合項目数"]) + "項目。共通する仮約定と先着ラベルを独立標本へ重複加算しない。\n\n"
    text += "以下は基準費用の円。全運用差＝共通実新規差＋RVOL側のみ純額−なし側のみ純額。出口は同じX0だが、入口を絞ると保有中の抑止と後続参加が変わる。RVOL側だけで新たに参加できた取引もあるため、除いた取引の純額だけで全差を説明しない。\n"
    return text + G.table(["足分", "系統", "期間", "元価格", "共通準備除外", "なし入口", "RVOL入口", "共通/なしのみ/RVOLのみ実新規", "共通純額差", "参加集合純額差", "全純額差"], rows)


def attention_diagnosis(study: Path, output: Path) -> str:
    """任意の注意経路診断を結果の確定性と区別して案内する。

    引数: study/output (Path) は試行と表示先。
    返り値: str は事後診断へのリンクと限界。未保存なら空文字列。
    """
    path = study/"注意経路診断.json"
    if not path.exists():
        return ""
    data = G.read_json(path)
    if data["原結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("注意経路診断と結果SHAが不一致")
    groups = data["全12候補3期間"]
    if len(groups) != 36 or len({(r["候補ID"], r["期間"]) for r in groups}) != 36:
        raise ValueError("注意経路診断が全12候補×3期間ではない")
    links = G.link(path, output)
    narrative = study/"注意経路診断.md"
    if narrative.exists():
        links += " / " + G.link(narrative, output)
    status = "全件一致" if data.get("全件一致") is True else "不一致または未確認"
    text = "## 注意経路の事後診断\n\n" + links + "は固定結果後の注意経路診断。照合は" + status + "、" + number(data.get("照合項目数")) + "項目。全12候補×3期間の全体観測額・注意場・注意取引・事後除外参考額を区別する。\n\n"
    focus = data["注目候補"]["学習寄与"]
    if focus["候補ID"] != "3分_R2_RVOL1.2以上_X0" or focus["期間"] != "学習" or focus["全体確定対象純額円"] is not None:
        raise ValueError("注目候補または確定性が不一致")
    if not math.isclose(focus["全体観測現金増減円"], focus["注意場の観測現金増減円"] + focus["事後_注意場除外参考円"], abs_tol=1e-8):
        raise ValueError("注意場分解が全体へ接合しない")
    text += "3分R2・RVOL条件の学習は基準費用で全体" + number(focus["全体観測現金増減円"]) + "円、注意" + number(focus["注意場数"]) + "場の全取引" + number(focus["注意場の観測現金増減円"]) + "円。その内訳は注意取引" + number(focus["注意取引の観測純額円"]) + "円と、同じ注意場内の注意なし完結取引" + number(focus["注意場内の注意なし完結取引純額円"]) + "円である。注意取引と注意場全体を混同しない。\n\n"
    rows = []
    for row in focus["費用感度"]:
        confirmed = "未確定" if row["全体確定対象純額円"] is None else number(row["全体確定対象純額円"])
        rows.append([row["片道追加滑りpt"], number(row["全体観測完結取引純額円"]), number(row["注意場内の全完結取引純額円"]), number(row["注意取引の観測純額円"]), number(row["事後_注意場除外の完結取引参考円"]), number(row["事後_注意取引だけ除外の完結取引参考円"]), confirmed])
    text += G.table(["追加片道pt", "全体観測純額", "注意場内全取引", "注意取引", "注意場除外の事後参考", "注意取引だけ除外の事後参考", "全体確定対象"], rows)
    text += "注意場を取り除いた額は事後的な参考値で、全体の実現可能利益や採用条件へ置き換えない。局所BBOの前後を確認しても空白内のSL/TP到達と、その後の単一建玉での参加経路は復元できない。3分R2のRVOL条件も学習注意3場を含む全体確定対象額を未確定のまま保つ。新しい閾値・候補の選び直しや未見検証は行っていない。\n\n"
    text += "全36群のうち確定対象額が未確定の" + number(sum(r["全体確定対象純額円"] is None for r in groups)) + "群は、この診断後も未確定である。\n\n"
    return text


# ----------------------------------------
# 価格条件・数量準備・RVOL・執行を異なる役割のS設定として記す。

def settings(rules: list[dict]) -> list[dict]:
    """1/3/5分の実使用と共通15分準備だけを51×9表へ置く。

    引数: rules (list[dict]) は12複合評価。
    返り値: list[dict] はS設定。参照20本と時間足を区別する。
    """
    groups = []
    for size in (1, 3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        first = [r for r in same if r["入口"]["入口系統"] == "R1"]
        band = [r for r in same if r["入口"]["入口系統"] == "R2"]
        extra = [r for r in same if r["入口"]["補助"] != "なし"]
        scale = [f"m{size:02d}"]
        groups += [
            (["I01", "I05", "I08", "I09"], scale, same, "EMA20/ATR14>0/ADX14/BB20・準備", "同場直前6足と当時公開済み15分EMA20/前値。1分も旧価格式・同じ本数"),
            (["I08"], scale, same, "ADX14<20・中心有利・価格改善", "R1/R2共通の価格条件。上位の方向一致は要求しない"),
            (["P01", "P03", "P09"], scale, first, "当足の端失敗と直前6高安", "買L<前6L<C<=前6H、今C>前Cかつ中心有利。売り対称。6窓へ当足を含めない"),
            (["I05", "P09"], scale, band, "BB20×2の帯外から内へ復帰", "買前C<前下帯、今下帯<=今C<今SMA20、今C>前C。母標準偏差、売り対称"),
            (["V01"], scale, same, "当足完全＋直前20数量足・正平均", "数量の助走を両側共通にする。現在足を分母に含めず、当足0量はRVOL0としてなし側へ残す"),
            (["V01"], scale, extra, "観測RVOL>=1.2", "価格時計で利用可能な累積差分量/同場直前20数量足平均。真の全約定量や方向別フローではない")]
    groups += [
        (["I01", "C07"], ["m15"], rules, "当場公開済み15分EMA20の準備", "方向は制約しない。上位の終了時計・公開時計/原行は判断足以下"),
        (["V01"], ["tick"], rules, "非負累積・数量時計<=価格時計", "原順で採用して現在の価格時計足へ加算。数量時計へ遡及せず、提示板数量を使わない"),
        (["B01"], ["tick"], rules, "ラージBBO・+1価格時計秒", "micro1枚代理、新規買Ask/売Bid・返済買Bid/売Ask。価格時計は受信時計ではない"),
        (["E01"], ["tick"], rules, "12入口の逆125/順250先着", "全仮約定分母に期限/不足を残す。運用の建玉中抑止を入口へ反映しない"),
        (["E02"], ["tick"], rules, "全案X0：TP250/SL125・期限", "数量で保有を取り消さない。+1秒後最初BBO、空白/EOF/未解消を記録")]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """保存された検査の明示合否を表示する。

    引数: study/output (Path) は試行/出力。
    返り値: tuple[str,list[Path]] は検査表/出典。未保存は未完とする。
    """
    rows, sources = [], []
    checks = [("合成検証.json", "境界合成"), ("数量事前照合.json", "旧5分共通集計の事前入力ゲート"), ("独立監査.json", "会計・集計"),
              ("数量独立確認.json", "数量・全入口の独立確認"), ("補助対応診断.json", "補助対応"), ("Viewer照合.json", "Viewer照合")]
    if (study/"注意経路診断.json").exists():
        checks.append(("注意経路診断.json", "注意経路の事後照合"))
    for name, label in checks:
        path = study/name
        if not path.exists():
            rows.append([label, "未完・結果未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        sources.append(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if label == "境界合成":
            verdict, count = data.get("全件成功"), data.get("検証件数", data.get("件数"))
            if verdict is None:
                parts = list(data.get("結果", {}).values())
                verdict, count = (all(p.get("全件成功") is True for p in parts) if parts else None), sum(p.get("検証件数", p.get("件数", 0)) for p in parts) if parts else None
        elif label == "補助対応":
            verdict, count = data.get("対応集合全件一致"), data.get("同じ仮約定の照合項目数")
        elif label == "Viewer照合" and verdict is None:
            parts = data.get("照合", [])
            verdict, count = (all(p.get("一致") is True for p in parts) if parts else None), len(parts)
        rows.append([label, "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示合否未確認", number(count), G.link(path, output)])
    text = "## 検査の状態\n\n集約保存と独立検査は別状態。同じ市場入力への検査件数を独立標本として加算せず、主監査が参照する別監査の範囲・限界も各正本で確認する。数量独立確認は主監査が参照するため、両者の項目数を合算しない。\n" + G.table(["範囲", "状態", "項目数", "正本"], rows)
    quantity_path = study/"数量独立確認.json"
    if quantity_path.exists():
        data = G.read_json(quantity_path)
        text += "数量側は原cacheから" + number(data["独立数量足数"]) + "数量足・" + number(data["基準価格入口数"]) + "元価格入口・" + number(data["独立12入口数"]) + "適用後入口の全集合を再構成した検査で、数量.pyや入口.pyの再呼び出しではない。原板の完全性や将来利益の証明にはならない。\n\n"
    return text, sources


# ----------------------------------------
# 数値再生は行わず、保存結果が揃ってから3文書だけを生成する。

def run(study: Path, output: Path) -> list[Path]:
    """固定された保存JSONからREADME・設定表・全候補結果を作る。

    引数: study/output (Path) は正式試行/任意表示先。
    返り値: list[Path] は3文書。結果不足・固定変更時は生成しない。
    """
    for name in ("条件.json", "固定.json", "結果.json", "入力台帳.json"):
        if not (study/name).is_file():
            raise ValueError(name + "が未保存のため数値文書を生成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    for name, expected in G.read_json(study/"固定.json")["ファイルSHA256"].items():
        if G.sha(ROOT/name) != expected:
            raise ValueError("固定されたcore・条件・入力が変更されている")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳参照が不一致")
    manifest, catalog = G.read_json(manifest_path), G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("共通表51×9が変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output/name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の1/3/5分×R1端の失敗突破/R2BB内復帰×数量なし/RVOL>=1.2＝12入口を、同じX0固定12運用で比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も未見確認ではない。表示処理は保存JSONを写し、原板・特徴・売買を再生せず、候補や閾値を増やさない。\n\n"
    conclusion = f"**入口70目標は{report['入口70目標達成数']}/12、探索用費用資格は{report['費用資格数']}/12。** 全12表示を採用と呼ばない。\n\n"
    limits = "ラージBBOでmicro1枚代理、倍率10円/pt、片道11円は比較仮定。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑りで発動・再参加が変わる再計算ではない。CurrentPriceTimeは受信時計ではなく、1秒待機は実通信遅延の実測ではない。注意・EOF・未解消を含む全体を確定収益としない。\n\n"
    quantity_note = "## 観測差分量の意味と心理仮説\n\n数量は価格時計で利用可能だった累積差分量で、真の全約定出来高・全約定VWAP・方向別フロー・建玉ではない。RVOL>=1.2は過去平均より観測数量が増えたという条件で、買い圧力・売り圧力や反転の原因を直接測らない。参加の活発化という仮説と、その後の方向・収益性の立証は別にする。1.2は結果前に固定した比較値で最適値ではない。\n\n"
    quantity_note += "数量なし側にも同じ数量助走を課す。従来の価格だけの全入口と比べる場合、準備で除いた母集団が異なることを先に示す。旧5分台帳との共通定義を保ちつつ、観測があっても有効Lastのない無価格枠の直後に累積基準をリセットする点を今回追加した。旧台帳の単純な再集計ではなく、1/3分も新たに集約する。\n\n"
    thresholds = "## 固定した条件\n" + G.table(["項目", "設定"], [[key, G.describe(config[key])] for key in ("価格条件", "共通準備", "数量条件", "出口定義", "入口支持", "間引き必要件数", "費用支持", "運用")])
    thresholds += "数量は同場非後退価格時計で有限非負累積かつ数量時計<=価格時計だけ採用し、その価格時計足へ加算する。初回・採用累積減少・採用数量時計後退・欠足/無価格枠後は再基準化。当足の欠測不正は不完全だが最後の有効基準を保持する。数量時計先行は保留のみで、当足開始以後の数量時計を持つ採用がなければ当足不完全。\n\n"
    thresholds += "RVOLは当足量/直前20連続数量足平均で現在足を分母へ入れない。当足と直前20足が基準完全・平均>0を両側共通に要求し、当足0量はRVOL0。不完全/欠足/非公開で数量履歴を切り、確認行の次足増分を前足へ混ぜない。数量の基準完全と数量準備、価格公開と価格R1/R2準備を区別する。20は足本数で、1/3/5分の尺度とは別。\n\n"
    thresholds += "価格式は旧00011R1/R2を読取利用し、1分も同じ式・本数とする。確定15分EMA20/前値の準備は必要だが方向制約なし。出口は全案X0：TP250/SL125・期限、新規要求+1秒以上30秒以内・残り60分以上、返済も要求+1秒以上後の最初正常BBO。数量は保有を取り消す条件には使わない。\n\n"
    definition_table = "## 固定12評価\n" + G.table(["評価", "候補", "足分", "価格系統", "数量補助", "出口", "費用資格"],
        [[r["評価ID"], r["候補ID"], r["入口"]["時間足分"], r["入口"]["名称"], r["入口"]["補助"], "X0固定", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_readme, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00014：反転入口と観測差分量\n\n状態：固定12案の集約保存済み。\n\n" + intro + links + " / " + G.link(setting_path, readme) + " / " + G.link(all_path, readme) + "\n\n" + conclusion + limits + quantity_note + quantity_summary(study, readme) + findings(entries, values) + auxiliary_diagnosis(study, readme) + attention_diagnosis(study, readme) + definition_table + audit_readme
    viewer = "## 入力・閲覧・再現\n\n" + G.link(study/"入力台帳.json", readme) + " / " + G.link(manifest_path, readme, "00008参照台帳") + "\n\n"
    viewer += f"市場root：{manifest['source_root']}。pnl_pathはpath_base=catalogで一覧親、market_pathは市場root基準。Viewerは全12の追加滑り0ptを表示し原板を複製しない。大量の数量足/基準価格入口/入口/運用詳細はwork、正式には集約と必要な約定だけを残す。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "数量品質.json", "入口品質.json", "入力品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study/name).exists():
            viewer += G.link(study/name, readme) + "\n\n"
    code_names = ["入口.py", "数量.py", "検証.py", "合成検証.py", "レポート.py"]
    code_names += [name for name in ("数量事前照合.py", "独立監査.py", "数量独立確認.py", "補助対応診断.py", "注意経路診断.py") if (ROOT/"scripts/数量反転"/name).exists()]
    viewer += "コード：" + " / ".join(G.link(ROOT/"scripts/数量反転"/name, readme) for name in code_names) + " / " + G.link(ROOT/"scripts/テクニカル循環/運用.py", readme, "読取利用するX0") + "。\n\n"
    fence = chr(96)*3
    viewer += "保存結果の再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/数量反転/レポート.py\n" + fence + "\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。正式結果上書き・固定後の変更を拒否する。\n\n"
    common = settings(rules)
    setting = "# 試行00014：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, setting_path, "コピー元の汎用表") + " / " + G.link(readme, setting_path) + " / " + G.link(all_path, setting_path) + "\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sは価格準備/発動・数量の時点/助走・RVOL・執行、R01〜R12は複合運用であり指標単独効果ではない。1/3/5分と15分準備だけを使用し、30分間引きは30分足の計算ではない。数量は観測差分proxyで、板提示数量や方向別売買の指標ではない。未使用はデータ不存在を意味しない。\n\n" + G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += thresholds + quantity_note + definition_table + "全期間の数値は" + G.link(all_path, setting_path) + "、数値正本は" + G.link(study/"結果.json", setting_path) + "。\n\n" + limits + attention_diagnosis(study, setting_path)
    audit_all, _ = audits(study, all_path)
    all_text = "# 試行00014：全候補結果\n\n" + intro + conclusion + G.link(readme, all_path) + " / " + G.link(setting_path, all_path) + "\n\n" + limits + quantity_note + thresholds + definition_table + quantity_summary(study, all_path) + quantity_tables(study) + findings(entries, values) + auxiliary_diagnosis(study, all_path) + attention_diagnosis(study, all_path)
    all_text += P.entry_table(entries).replace("8純入口", "12純入口") + P.operation_tables(values, refs, config).replace("8固定運用", "12固定運用") + audit_all
    all_text += "注意を含む運用の確定対象欄で『未算出』と表示される値は、品質上の未確定（正本null）を表す。無取引時の平均・率の未算出とは理由が異なる。\n\n"
    paths = [Path(__file__), DISPLAY_HELPER, ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER,
             study/"計画.md", study/"条件.json", study/"固定.json", study/"入力台帳.json", manifest_path, study/"結果.json", *audit_paths]
    paths += [ROOT/"scripts/数量反転"/name for name in code_names if name != "レポート.py"]
    paths += [study/name for name in ("入口品質.json", "数量品質.json", "注意経路診断.md") if (study/name).exists()]
    paths += [ROOT/name for name in ("docs/議論/入力と数量の監査.md", "docs/議論/数量台帳の追加集計.md", "scripts/テクニカル循環/入口.py", "scripts/テクニカル循環/運用.py")]
    for path, text in ((readme, summary+viewer), (setting_path, setting), (all_path, all_text)):
        path.write_text(text + G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """正式試行と任意の表示先を受け取り3文書を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。結果保存前は生成しない。
    """
    parser = argparse.ArgumentParser(description="00014の数量補助と12固定運用を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
