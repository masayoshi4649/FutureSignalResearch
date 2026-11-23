"""00013の保存済み8入口・8固定運用を3文書と51×9表へ転記する。"""

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
STUDY = ROOT / "study/00013_収縮後の突破と失敗反転"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def shared() -> Any:
    """汎用表の表示・リンク・指紋関数だけを読む。

    引数: なし。
    返り値: Any は共通表示。原板再生・入口生成・売買処理は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("収縮反転帳票の共通表示", ROOT / "scripts/レポート/設定結果レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = shared()


def number(value: float | int | None) -> str:
    """ゼロと未算出を区別して数値を表示する。

    引数: value (float|int|None) は保存値。
    返り値: str は桁区切り値または未算出。
    """
    if value is None:
        return "未算出"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def definitions(config: dict) -> list[dict]:
    """2足×2系統×2補助・X0だけの固定8定義を作る。

    引数: config (dict) は固定条件。
    返り値: list[dict] は入口・運用・R01〜R08の対応。
    """
    if config["時間足分"] != [3, 5] or config["入口系統"] != ["突破追随", "突破失敗反転"] or config["補助"] != ["なし", "15分方向一致"] or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("固定2足×2系統×2補助・X0と異なる")
    if [config["状態本数"][k] for k in ("帯幅参照", "固定高安", "突破待機", "復帰待機")] != [20, 6, 6, 3] or (config["BB期間"], config["母標準偏差倍率"], config["逆行pt"], config["順行pt"]) != (20, 2, 125, 250):
        raise ValueError("20/6/6/3・BB20×2・125/250と異なる")
    rules = []
    for size in config["時間足分"]:
        for family in config["入口系統"]:
            for extra in config["補助"]:
                source = {"入口ID": f"{size}分_{family}_{extra}", "入口系統": family, "時間足分": size,
                          "補助": extra, "名称": family, "役割": "順行" if family == "突破追随" else "反転"}
                rules.append({"候補ID": source["入口ID"] + "_X0", "入口": source, "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rules)+1:02d}"})
    return rules


def validate_entry(item: dict) -> None:
    """入口の五分類・全仮約定分母・間引き率を検査する。

    引数: item (dict) は一入口一期間の集約。
    返り値: None。不一致は例外。
    """
    if item["候補数"] != sum(item[k] for k in LABELS) or item["約定候補数"] != item["候補数"] - item["未約定"]:
        raise ValueError("入口ラベルと分母が不一致")
    for success, total, rate in (("順行先着", "約定候補数", "確認率"), ("30分間引き_順行先着", "30分間引き_約定候補数", "30分間引き_確認率")):
        expected = item[success] / item[total] if item[total] else None
        if (expected is None) != (item[rate] is None) or expected is not None and not math.isclose(expected, item[rate], abs_tol=1e-12):
            raise ValueError("入口率と件数が不一致")


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """8入口・8運用の定義・件数・費用・資格を検査する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は固定定義。
    返り値: tuple[dict,dict] は入口ID別と候補ID別の正本値。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または入口評価が不一致")
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    sources = {r["入口"]["入口ID"]: r["入口"] for r in rules}
    if len(entries) != 8 or len(report["入口評価"]) != 8 or entries.keys() != sources.keys() or len(values) != 8 or len(report["結果"]) != 8 or values.keys() != {r["候補ID"] for r in rules}:
        raise ValueError("固定8入口・8運用と異なる集合")
    for source_id, entry in entries.items():
        if any(entry[k] != v for k, v in sources[source_id].items()):
            raise ValueError("入口定義が不一致")
        for period in PERIODS:
            validate_entry(entry[period])
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
                               and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        if (entry["入口支持"], entry["70目標"]) != (support, bool(goal)):
            raise ValueError("入口支持・目標判定が不一致")
    for definition in rules:
        row = values[definition["候補ID"]]
        if row["入口"] != definition["入口"] or row["出口"] != definition["出口"]:
            raise ValueError("運用定義が不一致")
        entry = entries[row["入口"]["入口ID"]]
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            if row[period]["入口"] != entry[period]:
                raise ValueError("純入口集約が運用と不一致")
            item = row[period]["運用"]
            n = item["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"] + item["無取引場数"] != sessions or item["買い取引数"] + item["売り取引数"] != n or not 0 <= item["黒字取引数"] <= n:
                raise ValueError("運用の期間・件数が不一致")
            if not 0 <= item["利確要求返済数"] + item["初期125保護返済数"] <= n:
                raise ValueError("固定出口の件数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"] - 2 * slip * config["運用"]["倍率"] * n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net / n, abs_tol=1e-8):
                    raise ValueError("平均額の分母が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意場を含む全体が確定額になっている")
            prior = n
            for k in (20, 50, 100):
                reached, red = item[f"{k}pt到達取引"], item[f"{k}pt後純赤字"]
                if not 0 <= red <= reached <= prior:
                    raise ValueError("MFE件数が不一致")
                prior = reached
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if row["費用資格"] != qualified:
            raise ValueError("費用資格が不一致")
    if report["表示固定ID"] != [r["候補ID"] for r in rules] or report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("全8表示または資格集計が不一致")
    return entries, values


# ----------------------------------------
# 先着観測と一建玉運用は別分母で表示する。

def entry_table(entries: dict) -> str:
    """8入口の先着と支持を三期間で表示する。

    引数: entries (dict) は正本8入口。
    返り値: str は24行の先着表。
    """
    rows = []
    for source, entry in entries.items():
        for period in PERIODS:
            item = entry[period]
            rows.append([source, PERIOD_NAMES[period], item["候補数"], item["約定候補数"], *[item[k] for k in LABELS], G.pct(item["確認率"]),
                         f"{item['30分間引き_順行先着']}/{item['30分間引き_約定候補数']}・{G.pct(item['30分間引き_確認率'])}",
                         f"{item['約定開始日数']}日/{item['約定場数']}場", "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達"])
    return "## 8純入口の125/250pt先着\n\n主率は順行250pt先着/全仮約定。逆行125pt・期限未達・観測不足を分母へ残し、未約定を別記する。仮想保有は重複し得る。30分間引きは30分足ではない。支持・70目標は旧二期間の固定条件で、11/4単独の合否ではない。\n" + G.table(
        ["入口", "期間", "候補", "仮約定", "順", "逆", "期限", "不足", "未約定", "主率", "間引き順/約定・率", "約定日/場", "旧二期間支持", "旧二期間70目標"], rows)


def operation_tables(values: dict, refs: dict, config: dict) -> str:
    """全8固定運用の費用・活動・出口・保有を表示する。

    引数: values (dict) は8運用、refs (dict) はR参照、config (dict) は費用仮定。
    返り値: str は三期間の運用表。
    """
    operations, holdings = [], []
    for cid, row in values.items():
        for period in PERIODS:
            item, prefix = row[period]["運用"], [refs[cid], PERIOD_NAMES[period]]
            n = item["完結取引数"]
            operations.append(prefix + [n, f"{item['黒字取引数']}/{n}・{G.pct(item['黒字取引数']/n if n else None)}",
                f"{item['買い取引数']}/{item['売り取引数']}", f"{item['活動場数']}/{item['入力場数']}", item["無取引場数"],
                *[number(item[f"追加{k}pt純損益円"]) for k in (0, 5, 10)],
                "未確定" if item["追加0pt確定対象円"] is None else number(item["追加0pt確定対象円"]),
                f"{item['品質注意場数']}/{item['EOF期限未達場数']}/{item['未解消場数']}", number(item["期間内最大場内DD円"])])
            average_pt = (item["追加0pt純損益円"] + 2 * config["運用"]["片道手数料円"] * n) / (config["運用"]["倍率"] * n) if n else None
            holdings.append(prefix + [number(item["追加0pt平均円"]), number(average_pt), number(item["保有分合計"] / n if n else None),
                G.pct(item["保有時間率_観測"]), item["利確要求返済数"], item["初期125保護返済数"],
                *[f"{item[f'{k}pt後純赤字']}/{item[f'{k}pt到達取引']}" for k in (20, 50, 100)], G.pct(item["活動場赤字率"]), number(item["最悪場内時価円"])])
    text = "## 8固定運用の費用と活動\n\n全案X0＝TP250/SL125・期限。金額は円。黒字率は追加0ptの完結純額>0/全完結で、入口先着率とは異なる。最大場内DDは期間で最大だった一場の観測含み込みDDで、全期間累積DDではない。0取引は実行済みで、率・平均は未算出。\n"
    text += G.table(["評価", "期間", "完結", "黒字/全・率", "買/売", "活動/入力場", "無取引場", "追加0pt", "追加5pt", "追加10pt", "0pt確定対象", "注意/EOF/未解消場", "最大場内DD"], operations)
    text += "### 保有と返済理由、MFE後の赤字\n\n手数料前平均ptは（基準純額＋往復料×完結数）/倍率/完結数。目標幅や平均勝ち幅ではない。MFE欄は『最終純赤字/そのMFE到達取引』で、事後の峰がその価格で回収できたことを保証しない。\n"
    return text + G.table(["評価", "期間", "基準平均円", "手数料前平均pt", "平均保有分", "観測保有率", "TP要求返済", "SL要求返済", "MFE20後赤字", "MFE50後赤字", "MFE100後赤字", "活動場赤字率", "最悪場内時価"], holdings)


def findings(entries: dict, values: dict) -> str:
    """補助ありなしと全候補の観測額を記述的に比較する。

    引数: entries/values (dict) は8入口/8運用。
    返り値: str は表。追加選定は行わない。
    """
    rows = []
    for size in (3, 5):
        for family in ("突破追随", "突破失敗反転"):
            for period in PERIODS[:2]:
                a, b = [entries[f"{size}分_{family}_{extra}"][period] for extra in ("なし", "15分方向一致")]
                qa, qb = [values[f"{size}分_{family}_{extra}_X0"][period]["運用"] for extra in ("なし", "15分方向一致")]
                rows.append([size, family, PERIOD_NAMES[period], f"{a['順行先着']}/{a['約定候補数']}・{G.pct(a['確認率'])}",
                             f"{b['順行先着']}/{b['約定候補数']}・{G.pct(b['確認率'])}", f"{a['約定候補数']}/{b['約定候補数']}",
                             number(qa["追加5pt純損益円"]), number(qb["追加5pt純損益円"])])
    text = "## 補助なし・15分方向一致の比較\n\n補助なしも準備済み15分EMA20を必要とし、方向だけを制約しない。状態登録・消費は補助と独立。方向一致は入口集合を絞り、一建玉では後続参加も変える。運用純額差を同一取引だけの方向効果としない。突破追随と失敗反転も時計・方向が異なる別入口。\n"
    text += G.table(["足分", "系統", "期間", "なし：順/仮約定・率", "方向一致：順/仮約定・率", "仮約定数 なし/一致", "なし：追加5pt純額", "一致：追加5pt純額"], rows)
    positive = [cid for cid, row in values.items() if all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2])]
    return text + "両旧期間で追加5pt後の観測純額が正の候補：" + ("、".join(positive) if positive else "なし") + "。観測黒字と支持・品質を含む費用資格は別に読む。\n\n"


def auxiliary_diagnosis(study: Path, output: Path) -> str:
    """任意の対応診断から同じ入口と参加集合差を表示する。

    引数: study/output (Path) は正式試行/出力文書。
    返り値: str は対応診断。未保存なら空文字列。結果SHA不一致は停止する。
    """
    path = study / "補助対応診断.json"
    if not path.exists():
        return ""
    data = G.read_json(path)
    if data["結果SHA256"] != G.sha(study / "結果.json"):
        raise ValueError("補助対応診断と結果の固定SHAが不一致")
    rows = []
    for row in data["結果"]:
        pair = row["運用比較"]
        if row["方向一致入口数"] + row["方向不一致で除く入口数"] != row["補助なし入口数"]:
            raise ValueError("補助対応の入口数が不一致")
        set_difference = pair["方向一致のみ純額円"] - pair["なし側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"], pair["共通実新規純額差円"] + set_difference, abs_tol=1e-8):
            raise ValueError("補助対応の会計分解が不一致")
        rows.append([row["足分"], row["系統"], PERIOD_NAMES[row["期間"]], row["補助なし入口数"], row["方向一致入口数"],
                     row["方向不一致で除く入口数"],
                     f"{pair['共通実新規数']}/{pair['なし側のみ実新規数']}/{pair['方向一致のみ実新規数']}",
                     number(pair["共通実新規純額差円"]), number(set_difference), number(pair["全運用純額差円"])])
    verdict = "全件一致" if data.get("対応集合全件一致") is True else "不一致または未確認"
    text = "## 補助対応と参加集合の診断\n\n" + G.link(path, output) + "に4組×3期間の対応と全65場状態件数を保存した。方向一致入口がなし側の当時の方向一致部分に対応する検査は" + verdict + "、照合" + number(data["同じ仮約定の照合項目数"]) + "項目。同じ仮約定を独立な標本として重複加算しない。\n\n"
    text += "以下は基準費用の円。全運用差＝共通実新規の純額差＋方向一致側のみ純額−なし側のみ純額。同じ実新規でも出口を変えた比較ではなく、X0固定のまま参加・抑止が変わる診断である。方向一致側だけで後から参加できた取引もあるため、入口を除いた取引の損益だけで全差を説明しない。\n"
    return text + G.table(["足分", "系統", "期間", "なし入口", "一致入口", "方向で除く", "共通/なしのみ/一致のみ実新規", "共通純額差", "参加集合純額差", "全運用純額差"], rows)


# ----------------------------------------
# 共通準備・収縮・突破・復帰・上位補助・執行を異なるS設定として51×9表へ置く。

def settings(rules: list[dict]) -> list[dict]:
    """実使用セルへ条件とR参照を割り当てる。

    引数: rules (list[dict]) は8複合評価。
    返り値: list[dict] は汎用matrix用の設定。
    """
    groups = []
    for size in (3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        follow = [r for r in same if r["入口"]["入口系統"] == "突破追随"]
        failure = [r for r in same if r["入口"]["入口系統"] == "突破失敗反転"]
        extra = [r for r in same if r["入口"]["補助"] == "15分方向一致"]
        scale = [f"m{size:02d}"]
        groups += [
            (["I01", "I05", "I08", "I09"], scale, same, "EMA20/ATR14>0/ADX14/BB20・準備", "有限・準備済みを要求。ADXの大小フィルタなし。ATRは準備と250pt/ATR診断でTP/SLは固定幅"),
            (["I05", "P11"], scale, same, "4σ/SMA20・同場20足当足最小", "BB20・母標準偏差2倍。正の幅と中心。当足含む20有効公開足の最小以下、等値可。20は足本数"),
            (["P03", "P06"], scale, same, "設定足含む6本高安を固定", "設定足含む直近6足H/Lを保存。旧状態を先に処理し未突破なら最後に最新収縮へ置換"),
            (["P07", "P11"], scale, follow, "次1〜6足・strict突破と幅増大", "C>固定HまたはC<固定L、当幅>設定幅。端等号は突破せず、非拡大の範囲外は設定失効"),
            (["P04", "P09"], scale, failure, "突破後1〜3足・strict内復帰", "固定L<C<固定Hの最初だけ逆向き。買突破後C<=L/売突破後C>=Hは失効。同じ突破足は使わない"),
            (["C07"], scale + ["m15"], extra, "当時公開済み15分方向一致", "買C15>EMA20>前EMA、売は逆。確認時計/原行と足終了が判断足以下。補助不可でも状態消費")]
    groups += [
        (["I01"], ["m15"], rules, "確定15分EMA20と前値の準備", "補助なしを含む全案の準備。方向一致を要求するのは指定した4入口だけ"),
        (["B01"], ["tick"], rules, "ラージBBO・+1価格時計秒", "micro1枚代理、新規買Ask/売Bid、返済買Bid/売Ask。価格時計は受信時計ではない"),
        (["E01"], ["tick"], rules, "入口8の逆125/順250先着", "全仮約定分母に期限/不足を残す。保有中抑止を入口ラベルへ反映しない"),
        (["E02"], ["tick"], rules, "固定X0：TP250/SL125・期限", "全8案同じ出口。要求1秒後以降の最初正常BBO。空白/EOF/未解消を記録")]
    rows = []
    for methods, scales, applies, short, detail in groups:
        refs = [r["評価ID"] for r in applies]
        rows.append({"設定ID": f"S{len(rows)+1:02d}", "手法ID": methods, "尺度ID": scales,
                     "短記": short, "説明": detail, "結果短記": "・".join(refs), "適用評価": refs})
    return rows


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """存在する監査の明示合否だけを表示する。

    引数: study/output (Path) は試行/出力。
    返り値: tuple[str,list[Path]] は状態表/出典。未保存を合格にしない。
    """
    rows, paths, notes = [], [], []
    for name, label in (("合成検証.json", "境界合成"), ("独立監査.json", "独立会計・集計"),
                        ("状態独立確認.json", "状態独立確認・別資料"), ("補助対応診断.json", "補助対応診断"), ("Viewer照合.json", "Viewer照合")):
        path = study / name
        if not path.exists():
            rows.append([label, "別資料なし（任意）" if label == "状態独立確認・別資料" else "未完・結果未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        paths.append(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if label == "境界合成":
            verdict, count = data.get("全件成功"), data.get("検証件数", data.get("件数"))
            if verdict is None:
                parts = list(data.get("結果", {}).values())
                verdict = all(v.get("全件成功") is True for v in parts) if parts else None
                count = sum(v.get("検証件数", v.get("件数", 0)) for v in parts) if parts else None
        elif label == "Viewer照合" and verdict is None:
            parts = data.get("照合", [])
            verdict, count = (all(v.get("一致") is True for v in parts) if parts else None), len(parts)
        elif label == "補助対応診断":
            verdict, count = data.get("対応集合全件一致"), data.get("同じ仮約定の照合項目数")
        if label == "状態独立確認・別資料" and verdict is True:
            notes.append(f"状態独立確認は原価格cacheの{data['入力場数']}場から3/5/15分足・指標・収縮状態を別計算し、保存{number(data['保存入口数'])}件と独立生成{number(data['独立入口数'])}件の全入口集合を照合した。主監査もこの正本を参照しており、主監査の項目数と足して独立標本数にしない。")
        rows.append([label, "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示合否未確認", number(count), G.link(path, output)])
    return "## 検査の状態\n\n集約保存と独立検査は別状態。範囲と限界は各正本を参照し、検査件数を独立な市場標本として加算しない。\n" + G.table(["範囲", "状態", "項目数", "正本"], rows) + "\n\n".join(notes) + "\n\n", paths


def state_counts(study: Path) -> str:
    """状態カウンターを尺度ごとに表示する。

    引数: study (Path) は試行。
    返り値: str は共有状態表。品質未保存なら空文字列。
    """
    path = study / "入口品質.json"
    if not path.exists():
        return ""
    totals = defaultdict(Counter)
    for row in G.read_json(path):
        for key, value in row.items():
            if isinstance(value, int):
                totals[row["時間足分"]][key] += value
    columns = ("収縮設定登録", "未突破設定置換", "拡大突破消費", "突破失敗消費", "非拡大範囲外失効", "反対端飛越失効", "未突破満了", "突破後満了", "帯幅無効リセット", "欠枠リセット", "非公開リセット")
    return "## 共有状態の診断\n\n各尺度の状態は補助2案へ共通で、保有や発注と独立に進む。登録/消費を8入口の独立標本数へ足さない。\n" + G.table(["足分", *columns], [[size, *[totals[size][key] for key in columns]] for size in (3, 5)])


# ----------------------------------------
# 結果が揃ってから3Markdownだけを生成する。原板・特徴・売買経路は再計算しない。

def run(study: Path, output: Path) -> list[Path]:
    """保存JSONからREADME・設定と結果・全候補結果を生成する。

    引数: study/output (Path) は正式試行/任意出力先。
    返り値: list[Path] は3文書。未保存や固定変更は例外。
    """
    for name in ("条件.json", "固定.json", "結果.json", "入力台帳.json"):
        if not (study / name).is_file():
            raise ValueError(name + "が未保存のため生成しない")
    config, report = G.read_json(study / "条件.json"), G.read_json(study / "結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    for name, expected in G.read_json(study / "固定.json")["ファイルSHA256"].items():
        if G.sha(ROOT / name) != expected:
            raise ValueError("固定されたコード・条件・入力が変更されている")
    pointer = G.read_json(study / "入力台帳.json")
    manifest_path = (study / pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳参照が不一致")
    manifest, catalog = G.read_json(manifest_path), G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("汎用表51×9が変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output / name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    intro = "NK225の3/5分×突破追随/突破失敗反転×補助なし/15分方向一致＝8入口を、同じ固定X0の8運用で比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部キー『後続検査』も未見確認ではない。帳票は保存JSONを表示し、再生・候補追加・閾値変更・再選定をしない。\n\n"
    conclusion = f"**入口70目標は{report['入口70目標達成数']}/8、探索用費用資格は{report['費用資格数']}/8。** 全8表示を採用と呼ばない。\n\n"
    limits = "ラージBBOでmicro1枚代理、倍率10円/pt、片道11円は比較仮定。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑りによる発動・再参加の再計算ではない。CurrentPriceTimeは受信時計ではなく、1秒待機は実通信遅延の実測ではない。注意・EOF・未解消を含む全体を確定収益としない。\n\n"
    definitions_table = "## 固定8複合評価\n" + G.table(["評価", "候補", "足分", "系統/役割", "補助", "出口", "費用資格"],
        [[r["評価ID"], r["候補ID"], r["入口"]["時間足分"], r["入口"]["入口系統"] + "/" + r["入口"]["役割"], r["入口"]["補助"], "TP250/SL125・期限", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    threshold_keys = ("状態本数", "帯幅", "収縮設定", "突破追随", "突破失敗反転", "リセット", "共通準備", "補助定義", "出口定義", "入口支持", "間引き必要件数", "費用支持", "運用")
    thresholds = "## 固定条件と処理順\n" + G.table(["項目", "設定"], [[key, G.describe(config[key])] for key in threshold_keys])
    thresholds += "20/6/6/3は3分または5分足の本数。帯幅4σ/SMA20が同場の当足含む20有効公開足の最小以下なら収縮、設定足含む6足高安を固定する。設定の次1〜6足でstrict終値突破と幅増大、突破の次1〜3足で固定L<C<固定Hへの最初の復帰を逆向き入口にする。反対端の等号を含む飛越は失効。\n\n"
    thresholds += "旧状態を先に処理し、消費・準備時刻・補助を判定後に幅窓を更新、未突破なら最後に最新収縮を登録する。突破後は新設定を置かず幅窓は更新。欠枠・非公開・未定義/非有限/非正幅・SMA<=0は窓/設定/突破後状態を全リセット。EMA/ATR/ADX/上位だけの準備不足は状態を切らず発動を抑止する。\n\n"
    thresholds += "EMA20は最初20終値の算術平均を種とし、ATR14/ADX14は固定Wilder平滑。同限月の指標履歴と同場の20幅窓を区別し、欠枠・限月変更・前場末欠枠では指標を再初期化。補助なしも準備済み15分EMA20・前値が必要で、上位の足終了・確認時計/原行は判断足以下。\n\n"
    thresholds += "全8案でX0固定TP250/SL125・期限を維持する。新規要求+1価格時計秒以上30秒以内・残り60分以上、新規停止15:25/翌05:40、期限15:35/翌05:50。返済も要求+1秒以上の最初正常BBO。20/6/6/3は独自仮説で、原著の標準再現や最適値とはしない。\n\n"
    audit_readme, audit_paths = audits(study, readme)
    links = " / ".join(G.link(study / name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json"))
    discussion = ROOT / "docs/議論/収縮拡大と突破失敗をどう分けるか.md"
    basis = "設計の根拠と反例：" + G.link(discussion, readme) + "。\n\n" if discussion.exists() else ""
    summary = "# 試行00013：収縮後の突破と失敗反転\n\n状態：固定8案の集約保存済み。\n\n" + intro + links + " / " + G.link(setting_path, readme) + " / " + G.link(all_path, readme) + "\n\n" + conclusion + limits + basis + findings(entries, values) + auxiliary_diagnosis(study, readme) + definitions_table + audit_readme
    viewer = "## 入力・閲覧・再現\n\n" + G.link(study / "入力台帳.json", readme) + " / " + G.link(manifest_path, readme, "00008参照台帳") + "\n\n"
    viewer += f"市場root：{manifest['source_root']}。Viewerのresource_rootは本repo。pnl_pathはpath_base=catalogで一覧親、market_pathは市場root基準。全8の追加滑り0ptを表示し原板を複製しない。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "入口品質.json", "作業成果物.json", "Viewer照合.json"):
        if (study / name).exists():
            viewer += G.link(study / name, readme) + "\n\n"
    fence = chr(96) * 3
    viewer += "保存結果の再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/収縮反転/レポート.py\n" + fence + "\n\n数値再生は固定版の検証.pyへ別の保存先と作業先を指定する。正式結果上書きと固定後変更を拒否する。\n\n"
    code_names = ["入口.py", "検証.py", "合成検証.py", "レポート.py"]
    code_names += [name for name in ("独立監査.py", "状態独立確認.py", "補助対応診断.py") if (ROOT / "scripts/収縮反転" / name).exists()]
    viewer += "コード：" + " / ".join(G.link(ROOT / "scripts/収縮反転" / name, readme) for name in code_names) + " / " + G.link(ROOT / "scripts/テクニカル循環/運用.py", readme, "読取利用する固定X0") + "。\n\n"
    common = settings(rules)
    setting = "# 試行00013：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, setting_path, "コピー元の汎用表") + " / " + G.link(readme, setting_path) + " / " + G.link(all_path, setting_path) + "\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を保持。Sは準備・設定・発動・上位補助・執行、R01〜R08は複合運用であり指標単独効果ではない。20幅や6足高安の期間本数と3/5分尺度を区別する。RSI/MACD/数量と1/30/60分等は未使用で、データ不存在の意味ではない。\n\n" + G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "閾値と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"]) + "・" + "/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += thresholds + definitions_table + "全期間の数値は" + G.link(all_path, setting_path) + "、正本は" + G.link(study / "結果.json", setting_path) + "。\n\n" + limits
    audit_all, _ = audits(study, all_path)
    all_text = "# 試行00013：全候補結果\n\n" + intro + conclusion + G.link(readme, all_path) + " / " + G.link(setting_path, all_path) + "\n\n" + limits + thresholds + definitions_table + findings(entries, values) + auxiliary_diagnosis(study, all_path) + entry_table(entries) + operation_tables(values, refs, config) + state_counts(study) + audit_all
    paths = [Path(__file__), ROOT / "scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER, study / "計画.md", study / "条件.json", study / "固定.json",
             study / "入力台帳.json", manifest_path, study / "結果.json", ROOT / "scripts/収縮反転/入口.py", ROOT / "scripts/収縮反転/検証.py",
             ROOT / "scripts/収縮反転/合成検証.py", ROOT / "scripts/テクニカル循環/運用.py", *audit_paths]
    if (study / "入口品質.json").exists():
        paths.append(study / "入口品質.json")
    if discussion.exists():
        paths.append(discussion)
    if (study / "補助対応診断.json").exists():
        paths.append(ROOT / "scripts/収縮反転/補助対応診断.py")
    paths += [ROOT / "scripts/収縮反転" / name for name in ("独立監査.py", "状態独立確認.py") if (ROOT / "scripts/収縮反転" / name).exists()]
    for path, text in ((readme, summary + viewer), (setting_path, setting), (all_path, all_text)):
        path.write_text(text + G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """試行と任意出力先を受け取って3文書を生成する。

    引数: なし。--study/--outputを読む。
    返り値: None。結果未保存なら生成しない。
    """
    parser = argparse.ArgumentParser(description="00013の8入口と8固定運用を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
