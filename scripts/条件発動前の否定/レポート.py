"""68の発動前否定と旧67条件参加を、保存結果だけから表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00068_発動前の反対端否定で条件を取り消す"
OLD = ROOT / "study/00067_定時候補を将来価格の突破で発動"
MODEL_STUDY = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
SHARED = ROOT / "scripts/定時候補の価格発動/レポート.py"
SPEC = importlib.util.spec_from_file_location("反対端否定68の固定67表示純補助", SHARED)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
BASE, R64, R55, V5 = PREVIOUS.BASE, PREVIOUS.R64, PREVIOUS.R55, PREVIOUS.V5
POLICIES, NEW, CONTROLS = ("G0", "G1", "N0", "N1"), ("N0", "N1"), ("G0", "G1")
PERIODS, PERIOD_NAMES, PHASES = PREVIOUS.PERIODS, PREVIOUS.PERIOD_NAMES, PREVIOUS.PHASES
sha, read, table = PREVIOUS.sha, PREVIOUS.read, PREVIOUS.table
number, rate, qualification, link, money = PREVIOUS.number, PREVIOUS.rate, PREVIOUS.qualification, PREVIOUS.link, PREVIOUS.money
EXTERNAL = ROOT / "docs/議論/外部再調査/突破の確認と取得位置と前提否定を分ける.md"
INHERITED = ("評価場", "学習専用場", "準備比較", "独立測定", "独立測定参照", "旧教師一致", "教師集合一致",
    "経路支持", "状態分布", "局面分布", "数量分布", "価格経路分布", "モデル", "回収集計")
STAGE_KEYS = ("全予定枠", "純候補", "条件結果別", "発動", "仮約定", "実条件登録", "実新規", "実登録未約定")
NONFILL = ("未発動", "既超過", "観測不足", "発動未約定")
DENIAL_KEYS = ("同じ純候補", "設定否定", "前提否定", "非否定の全属性一致", "否定群の旧結果",
    "旧仮約定の除外", "旧250の除外", "旧125の除外", "両約定の時刻価格結果一致", "新のみ仮約定")

# ----------------------------------------
# 候補・条件・要求・実新規の分母を別々に表示する。


def main_tables(result: dict) -> tuple[str, str]:
    """旧条件と新しい発動前否定の先着・実回収を別表にする。

    引数: result(dict)は保存結果。
    返り値: tuple[str,str]は入口集計と実運用の二表。
    """
    entrance, cash = [], []
    for policy in POLICIES:
        for period in PERIODS:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            entrance.append([policy, PERIOD_NAMES[period], e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]),
                f'{e["間引き250"]}/{e["間引き約定"]}', rate(e["間引き率"]), f'{e["日数"]}日/{e["場数"]}場',
                qualification(e["支持"]), qualification(e["70目標"])])
            cash.append([policy, PERIOD_NAMES[period], o["完結数"], money(o["完結観測額円"]["5"]), money(o["全体確定額円"]["5"]),
                len(o["品質注意場"]), rate(o["主待ち率"]), rate(o["待ち率保守上限"]), qualification(o["活動適格"]),
                f'{o["利益起動件数"]}/{o["起動後赤字件数5"]}', qualification(o["費用適格"]), qualification(item["同時適格"])])
    return (table(["候補", "期間", "入口集計対象", "250/仮約定", "主率", "非重複250/約定", "非重複率", "日/場", "入口支持", "70目標"], entrance),
        table(["候補", "期間", "実完結", "観測5円", "全体確定5円", "品質注意場数", "主待ち", "保守上限", "活動", "利益旗/旗後赤字", "費用", "同時適格"], cash))


def stage_table(result: dict) -> str:
    """条件登録の当時指示と結果後被覆を保存欄のまま全表示する。

    引数: result(dict)は条件段階を含む結果。
    返り値: strは欠測補完しない段階表。
    """
    rows = []
    for policy in NEW:
        for period in PERIODS:
            for field, value in result["条件段階"][policy][period].items():
                rows.append([policy, PERIOD_NAMES[period], field,
                    json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value])
    return ("## 条件の段階と分母\n\n全予定枠→同じ純候補→条件登録→発動→新規要求→仮約定／実新規・完結を分ける。"
        "条件登録指示は当時のaction、発動・未発動・実登録未約定はその後の被覆であり、後者を当時の入力へ戻さない。"
        "保有又はpendingで登録しない候補も、独立した条件入口評価と混ぜない。未発動監視を保有継続と数えない。\n\n"
        + table(["候補", "期間", "保存段階", "保存値"], rows))


def detail_tables(result: dict) -> str:
    """費用・品質・DI役割・定時判断理由を保存値から表示する。

    引数: result(dict)は四候補の結果。
    返り値: strは詳細表。先着と実利益を同一視しない。
    """
    costs, roles, reasons = [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            o = result["候補"][policy][period]["運用"]
            costs.append([policy, PERIOD_NAMES[period], o["完結数"], *(money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)),
                *(money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)), o["未解消"], o["品質注意場"]])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][policy][period][role], o["役割別完結"][role]
                roles.append([policy, PERIOD_NAMES[period], role, e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]),
                    qualification(e["支持"]), actual["件数"], money(actual["観測純額5"])])
            if policy in NEW:
                reasons.extend([policy, PERIOD_NAMES[period], reason, n] for reason, n in sorted(result["判断理由"][policy][period].items()))
    return ("## 同約定の費用と品質\n\n品質注意又は未解消時の期間全体確定はnull。観測額を確定0円へ置換しない。\n\n"
        + table(["候補", "期間", "完結", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "未解消", "品質注意場"], costs)
        + "## DI役割別の入口と実回収\n\n純side・roleは旧67保存値。DI順行／反転は分類であり心理の直測ではない。役割別観測額も期間全体の品質に従う。\n\n"
        + table(["候補", "期間", "役割", "入口対象", "250/仮約定", "主率", "入口支持", "実完結", "観測5円"], roles)
        + "## 保存された定時の技法候補理由\n\n旧66から維持した純候補の理由であり、実運用の登録拒否・保有継続・発動成否の理由ではない。定時の条件登録指示と、後から判明する発動・未約定を分離する。純候補の同値を実参加の包含へ読み替えない。\n\n"
        + table(["候補", "期間", "保存理由", "枠数"], reasons))


def comparison_table(result: dict) -> str:
    """同じ純候補の全結果対と両約定限定の取得差を表示する。

    引数: result(dict)は主の入口取得比較。
    返り値: strは全保存比較欄。両約定だけを比較全体としない。
    """
    rows = []
    for policy in NEW:
        for period in PERIODS:
            for field, value in result["入口取得比較"][policy][period].items():
                shown = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else "null（対象なし）" if value is None else value
                rows.append([policy, PERIOD_NAMES[period], field, shown])
    return ("## 同じ候補の入口取得比較\n\n全純候補の結果対、旧のみ／新のみ／両方の仮約定を残す。今回の残存仮約定は旧67と時刻・原行・価格・先着結果が同じで、"
        "両約定の平均追随ptと平均取得遅延秒は対象ありなら0、対象なしならnullである。否定による回避と取り逃がしを含む全体利益ではない。"
        "一枚保有・pendingの占有が変わる実運用へ、この仮約定の包含を転用しない。\n\n" + table(["候補", "期間", "保存比較", "保存値"], rows))


def denial_table(result: dict) -> str:
    """否定比較の全十項目を、除外群と残存群に分けて表示する。

    引数: result(dict)は主が保存した否定比較。
    返り値: strは十項目を省略しない表。群の事後結果を採否へ戻さない。
    """
    rows = []
    for policy in NEW:
        for period in PERIODS:
            for field in DENIAL_KEYS:
                value = result["否定比較"][policy][period][field]
                rows.append([policy, PERIOD_NAMES[period], field,
                    json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else value])
    return ("## 発動前否定の除外と残存\n\n設定否定は未登録WAIT、前提否定は監視開始後の登録未約定。どちらも価格による取消であり品質注意ではない。"
        "旧250を取り逃がす件数と旧125を外す件数を同じ純候補分母に残す。非否定はpolicy以外全属性一致、残存仮約定の同値と実一枚の参加差は別に評価する。\n\n"
        + table(["候補", "期間", "否定比較の保存欄", "保存値"], rows))


def validate_result(result: dict) -> None:
    """同じ候補・新しい条件入口・拡張活動分母の保存整合を検査する。

    引数: result(dict)は68主結果。正式又は人工の小型辞書。
    返り値: None。不一致は例外。系列や予測は再計算しない。
    """
    if result.get("試行") != 68 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("68の旧G・新N四候補と既使用契約が必要")
    if (result["新回帰器fit"], result["新分類器fit"], result["新独立計測"], result["新運用数"], result["新保存木数"], result["参照モデル数"]) != (0, 0, 0, 92, 0, 3):
        raise ValueError("fit0・新木0・独立追尾回収0・参照3・新運用92の差")
    if result["対照参照"] != {"候補": list(CONTROLS), "元試行": 67, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("旧67G0/G1の保存対照が必要")
    expected_learning = {**PREVIOUS.PREVIOUS.REFERENCE, "旧即時入口の教師": True, "新条件入口を学習したか": False}
    if result["学習参照"] != expected_learning or result["新条件入口評価"] != 488:
        raise ValueError("旧即時教師の参照と新条件488評価を区別する")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20学習専用と評価46場を混ぜない")
    if result["検査"]["旧67純判断一致"] != 3404 or result["検査"]["当時最新3分出典一致"] != 488:
        raise ValueError("旧純3404・条件候補出典488の接続差")
    if set(result["条件段階"]) != set(NEW):
        raise ValueError("条件段階は新N二政策だけ")
    for period, count in zip(PERIODS, (740, 888, 74)):
        if result["準備比較"][period]["全予定枠"] != count:
            raise ValueError("全予定枠分母差")
        for policy in POLICIES:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            outcomes = e["結果別"]
            unfilled_keys = NONFILL + (("設定否定", "前提否定") if policy in NEW else ())
            if any(type(n) is not int or n < 0 for n in outcomes.values()):
                raise ValueError("先着結果別の件数型差")
            if not set(outcomes) <= set(unfilled_keys) | {"250", "125", "期限", "不足"}:
                raise ValueError("条件入口結果の未知区分")
            if sum(outcomes.values()) != e["候補"] or e["候補"] - sum(outcomes.get(k, 0) for k in unfilled_keys) != e["約定"]:
                raise ValueError("入口集計対象と仮約定の分母差")
            if outcomes.get("250", 0) != e["250"]:
                raise ValueError("250件数と結果別の差")
            for win, total, value in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
                if (e[value] is None) != (e[total] == 0) or e[total] and not math.isclose(e[value], e[win] / e[total], rel_tol=0, abs_tol=1e-12):
                    raise ValueError("先着率の分母又はnull差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            unfilled = o["条件未約定"]
            if o["予定枠"] != count or sum(o["判断別"].values()) != count or (o["待ち数"], o["判定不能"]) != (wait, invalid):
                raise ValueError("実判断の全予定分母差")
            if not 0 <= wait + invalid + unfilled <= count:
                raise ValueError("条件未約定を含む保守分母が不正")
            if not math.isclose(o["主待ち率"], wait / count, rel_tol=0, abs_tol=1e-12) or not math.isclose(o["待ち率保守上限"], (wait + invalid + unfilled) / count, rel_tol=0, abs_tol=1e-12):
                raise ValueError("主待ち又は条件未約定込み保守上限の差")
            if o["活動適格"] != ((wait + invalid + unfilled) * 2 <= count):
                raise ValueError("保守待ち50%の判定差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定の費用感応差")
                if (o["品質注意場"] or o["未解消"]) and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意又は未解消の全体確定はnull")
            if item["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("同時適格の差")
            if policy in NEW:
                validate_stage(result, policy, period)
    if result["採用"] != [p for p in NEW if all(result["候補"][p][t]["同時適格"] for t in PERIODS[:2])]:
        raise ValueError("新候補の採用差")
    if sum(row["純候補"] for periods in result["条件段階"].values() for row in periods.values()) != result["新条件入口評価"]:
        raise ValueError("全条件評価488の期間復元差")


def validate_stage(result: dict, policy: str, period: str) -> None:
    """主の条件段階と入口・実運用の件数を結合する。

    引数: result(dict)は結果、policy(str)はN候補、period(str)は用途期間。
    返り値: None。未知の段階を0補完しない。
    """
    stage = result["条件段階"][policy][period]
    if not set(STAGE_KEYS) <= set(stage):
        raise ValueError("条件段階の必須保存欄不足")
    e, o = result["候補"][policy][period]["入口"], result["候補"][policy][period]["運用"]
    if any(type(stage[k]) is not int or stage[k] < 0 for k in STAGE_KEYS if k != "条件結果別"):
        raise ValueError("条件段階の件数型差")
    if stage["全予定枠"] != o["予定枠"] or sum(stage["条件結果別"].values()) != stage["純候補"]:
        raise ValueError("条件結果別と純候補の復元差")
    control = CONTROLS[NEW.index(policy)]
    if stage["純候補"] != e["候補"] or e["候補"] != result["候補"][control][period]["入口"]["候補"]:
        raise ValueError("条件登録前の純候補は旧67と同一")
    if stage["仮約定"] != e["約定"] or stage["実条件登録"] != o["条件登録数"] or stage["実登録未約定"] != o["条件未約定"]:
        raise ValueError("条件段階と入口・実登録の接続差")
    if not 0 <= stage["仮約定"] <= stage["発動"] <= stage["純候補"] <= stage["全予定枠"]:
        raise ValueError("独立条件入口の段階順序差")
    if not o["完結数"] <= stage["実新規"] <= stage["実条件登録"] <= stage["純候補"]:
        raise ValueError("実新規と条件登録の段階差")
    if stage["実新規"] + stage["実登録未約定"] != stage["実条件登録"]:
        raise ValueError("実登録の約定／未約定分解差")
    comparison = result["入口取得比較"][policy][period]
    if comparison["同じ純候補"] != stage["純候補"] or sum(comparison["結果対"].values()) != stage["純候補"]:
        raise ValueError("旧新全候補の結果対分母差")
    if comparison["両約定"] + comparison["旧のみ約定"] != result["候補"][control][period]["入口"]["約定"] or comparison["両約定"] + comparison["新のみ約定"] != e["約定"]:
        raise ValueError("新旧のみ／両約定の復元差")
    for key in ("両約定の平均追随pt", "両約定の平均取得遅延秒"):
        value = comparison[key]
        if (value is None) != (comparison["両約定"] == 0) or value is not None and not math.isfinite(value):
            raise ValueError("両約定条件付き平均のnull差")
        if value is not None and value != 0:
            raise ValueError("残存仮約定の平均追随と遅延は0")
    validate_denial(result, policy, period)


def validate_denial(result: dict, policy: str, period: str) -> None:
    """否定の排他分解と旧仮約定除外を主の十項目に結合する。

    引数: result(dict)は結果、policy(str)はN候補、period(str)は期間。
    返り値: None。出典や先着を再計算せず保存整合だけを検査する。
    """
    denied = result["否定比較"][policy][period]
    if set(denied) != set(DENIAL_KEYS):
        raise ValueError("否定比較は十項目を全保存する")
    if any(type(denied[k]) is not int or denied[k] < 0 for k in DENIAL_KEYS if k != "否定群の旧結果"):
        raise ValueError("否定比較の件数型差")
    old_results = denied["否定群の旧結果"]
    if not isinstance(old_results, dict) or any(type(n) is not int or n < 0 for n in old_results.values()):
        raise ValueError("否定群の旧結果の件数型差")
    e = result["候補"][policy][period]["入口"]
    stage, comp = result["条件段階"][policy][period], result["入口取得比較"][policy][period]
    n = denied["設定否定"] + denied["前提否定"]
    if denied["同じ純候補"] != e["候補"] or n + denied["非否定の全属性一致"] != e["候補"] or sum(old_results.values()) != n:
        raise ValueError("否定と非否定の全体復元差")
    for field in ("設定否定", "前提否定"):
        if denied[field] != e["結果別"].get(field, 0) or denied[field] != stage["条件結果別"].get(field, 0):
            raise ValueError("否定件数と入口・段階の差")
    if denied["新のみ仮約定"] != 0 or comp["新のみ約定"] != 0:
        raise ValueError("否定だけで独立した新仮約定は増えない")
    if denied["両約定の時刻価格結果一致"] != e["約定"] or comp["両約定"] != e["約定"] or denied["旧仮約定の除外"] != comp["旧のみ約定"]:
        raise ValueError("残存仮約定の同値と除外の差")
    for outcome, field in (("250", "旧250の除外"), ("125", "旧125の除外")):
        if denied[field] != sum(n for key, n in old_results.items() if key.split("/")[-1] == outcome):
            raise ValueError("否定群の旧250・125件数差")
    if denied["旧250の除外"] + denied["旧125の除外"] > denied["旧仮約定の除外"] or denied["旧仮約定の除外"] > n:
        raise ValueError("旧仮約定除外と結果の包含差")

# ----------------------------------------
# 旧木は旧65パス、旧対照は旧67パスでそのまま読む。


def context_for() -> dict:
    """主と監査の成功後に小型結果と旧参照木だけを読む。

    引数: なし。
    返り値: dictは表示文脈。詳細gzip・原板・教師は開かない。
    """
    required = [STUDY / n for n in ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("主と正式保存監査の成功後だけ生成できます")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0]):
        raise ValueError("結果・固定・成功監査の結合差")
    old_context = PREVIOUS.context_for()
    old = old_context["result"]
    for policy in CONTROLS:
        if any(result[key][policy] != old[key][policy] for key in ("候補", "役割別入口")):
            raise ValueError("旧67保存対照の集計差")
    for key in INHERITED:
        if result[key] != old[key]:
            raise ValueError("同じ旧入力・学習・回収の参照差:" + key)
    if result["対照モデル"] != old["モデル"] or result["旧証明検査"] != old["検査"]:
        raise ValueError("旧67参照モデル又は新旧証明の区別に差")
    resources = read(required[-1])["resources"]
    if len(resources) != 184 or Counter(x["method_id"] for x in resources) != {p: 46 for p in POLICIES}:
        raise ValueError("旧G92＋新N92のViewer184資源差")
    if any(not (ROOT / x["pnl_path"]).is_file() for x in resources):
        raise ValueError("Viewer約定参照欠落")
    sources = [*required, *old_context["sources"], SHARED, EXTERNAL, HERE / "README.md", *sorted(HERE.glob("*.py")), *sorted(HERE.glob("*仕様.md"))]
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {**old_context, "result": result, "proof": proof, "fixed": fixed, "sources": list(dict.fromkeys(sources))}


def settings(context: dict) -> list[dict]:
    """同60特徴と発動前否定だけの追加条件を版5へ対応させる。

    引数: context(dict)は旧木の60metadataを持つ表示文脈。
    返り値: list[dict]は設定。否定を独立した技法票へ水増ししない。
    """
    rows = deepcopy(PREVIOUS.settings(context)[:60])
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04", 説明="旧67G・新68Nは同じ保存60特徴、旧65三木・回収を参照。新fit・新特徴・新予測なし。")
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02/R03/R04", "同じ旧66適格方向選択と旧67純候補を参照", "純side・role・ATR/D、旧即時入口の回収資格を維持。新N1も主過去回収strict正資格。"),
        (["P10", "P02", "B01"], ["m03", "tick"], "R01/R02/R03/R04", "定時凍結3分方向端をLast strict突破", "設定既超過拒否、normalBBOかつ有限正Lastで監視。発動線の等号は発動しない。"),
        (["P09", "P02", "C07"], ["m03", "tick"], "R03/R04", "発動前だけ反対端到達で否定", "買Last<=low／売Last>=high。設定否定は未登録WAIT、前提否定は登録未約定。品質注意ではなく、発動後には適用しない。"),
        (["C07", "E02"], ["m15", "tick"], "R01/R02/R03/R04", "次定時T+900で条件・entrypending取消", "発動後1秒・後行BBO、TTL30でも次定時未満。watch後gap>300は観測不足取消／品質注意を優先。"),
        (["E01", "E02", "C06"], ["tick"], "R01/R02/R03/R04", "O49主費用122円strict正・連続非緩和追尾", "固定250TPなし。名目床は費用後同値ではなく、返済pendingで保護凍結。旧新同じ出口。"),
        (["C07"], ["m15"], "R01/R02/R03/R04", "主WAIT／全枠、保守は条件未約定も加算", "旧Gも新Nも同じ保守式。登録指示を実参加にせず、保有継続は非待ち。")]
    for methods, scales, evaluations, short, description in extras:
        rows.append({"設定ID": f"S{len(rows) + 1:02d}", "手法ID": methods, "尺度ID": scales, "結果短記": evaluations, "短記": short, "説明": description})
    return rows


def feature_table(context: dict) -> str:
    """同じ旧60特徴を省略せず、今回の変更が否定だけと明記する。

    引数: context(dict)は旧木metadataを持つ表示文脈。
    返り値: strは旧特徴式を変えない全文表。
    """
    text = PREVIOUS.feature_table(context)
    text = text.replace("旧66E・新67Gの全入力は同じ。", "旧67G・新68Nの全入力は同じ。")
    return text.replace("67でもこの構造を再学習しない。", "68でもこの構造を再学習しない。")


def reference_tables(context: dict, output: Path) -> str:
    """旧65三木と回収の全閾値を、旧即時入口の来歴のまま表示する。

    引数: context(dict)は旧木文脈、output(Path)は出力先。
    返り値: strは参照表。新条件や否定を学習済みとは呼ばない。
    """
    text = PREVIOUS.reference_tables(context, output)
    changes = {"新G0/G1という木を作らず": "新N0/N1という木を作らず",
        "67の回帰fit0・分類fit0・新保存木0。": "68の回帰fit0・分類fit0・新保存木0。",
        "66の適格集合内の方向選択を67でも維持する。": "66の適格集合内の方向選択を旧67と同じく68でも維持する。",
        "67で再集計しない。": "68で再集計しない。", "67の新fit・新測定結果ではない。": "68の新fit・新測定結果ではない。",
        "G1は同じ旧即時入口の参照集計の主合計strict>0": "N1は同じ旧即時入口の参照集計の主合計strict>0",
        "67の条件入口先着は新計算": "68の否定付き条件入口先着は新計算"}
    for before, after in changes.items():
        text = text.replace(before, after)
    return text


def documents(context: dict) -> dict[str, str]:
    """同じ定時候補と発動前否定だけの比較を二文書へ構成する。

    引数: context(dict)は正式又は人工の表示文脈。
    返り値: dict[str,str]は二本文。書込・予測・市場は実行しない。
    """
    r, proof = context["result"], context["proof"]
    brief_path, detail_path = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, cash = main_tables(r)
    status = "新候補の採用なし。支持付き先着70・費用・全予定保守待ち50%以下の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見利益の保証ではない。"
    intro = ("全66場は既使用。初20場は学習専用、学習欄は後20時系列、選択24場・既使用後続2場はF40を使用する。\n\n" + status
        + "\n\n旧67G0/G1各46場は保存対照、新N0/N1各46場の92運用。全60特徴・旧65三木・回収・教師・純side/role・ATR/D保存値を不変参照し、新fit0・新木0・新独立追尾回収0・新予測0。"
        "旧Gも条件型であり、今回の差は発動前の反対端否定だけ。条件入口先着は新しい否定規約で評価し、旧即時先着や旧55回収を新入口へ流用しない。\n\n")
    mechanics = ("## 固定した発動前否定と保護\n\nデイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠で同じ複合技法候補を決める。最新公開・完全な3分足のhigh/lowを定時に凍結し、買Last>high／売Last<lowで発動する。"
        "旧BBO・保有・pending・準備・既超過の優先を維持した後、買Last<=low／売Last>=highは設定否定で未登録WAIT。反対端の等号も否定に含む。\n\n"
        "設定後は設定keystrict後だけ、normal BBOかつ有限正Lastで監視する。watch後gap>300秒の観測不足を優先し、それ以外で反対端へ到達すれば前提否定で登録取消。"
        "設定Last／BBO不正は判定不能。設定否定・前提否定自体は品質注意にしない。否定後の同枠再登録・復活・自動反対注文はなく、次定時に再判断する。発動後のentrypending・保有には新否定を適用しない。\n\n"
        "T+900の次定時timerは境界同秒の価格より先に、未発動watchも発動済entrypendingも取消。発動後1価格時計秒かつ後行の最初の正常BBOで新規、TTL30秒でも次定時未満。"
        "Lastのstrict突破は発動条件で、線やLastへ約定を戻さない。同秒原行順を保持し、OHLCから足内順を補わない。途中の新指標で方向・線・ATR/Dを更新しない。\n\n"
        "旧Gも新Nも主待ち=WAIT／全予定枠、保守上限=(WAIT＋判定不能＋条件登録してentryなし)／全予定枠で50%以下。保有継続は非待ち、未約定監視は保有と数えない。"
        "設定否定はWAIT分子、監視後の前提否定は登録未約定分子に入る。当時の登録指示と事後の発動・未約定・実新規を別分母にする。\n\n"
        "約定後はO49会計・追尾を維持。micro1枚10円/pt、片道11円＋滑り5ptの往復122円。定時保存ATR/Dを使いD5..125、損失側も連続非緩和、"
        "現在正常返済BBOの粗益−122円strict正で利益旗と最低名目新規床。返済pendingはh/L/arm凍結。強制15:35/05:50、終了15:40/05:55、残り60分停止なし・250固定TPなし。"
        "0/10pt感応は同約定・利益旗122円不変。品質注意の全体確定nullと観測額を分け、名目床を費用後同値保証にしない。\n\n")
    external = ("## 一次資料と独自規約\n\n確認日2026-11-06。事前整理のMNQ量・変動プレプリントは事後ピーク反落と事前勝率を区別し、Brooks本人の解説は強さと遅い取得を分ける。"
        "RIETIの先物研究は市場・時間帯・量と流動性の違いを扱い、NK225の突破利益を証明しない。心理は推論。"
        "今回の単一3分足反対端・Last・15分寿命・BBO代理・取消優先は独自規約で、共有水準や原典の完全再現ではない。"
        "反対端を試してから元方向へ進む複雑調整を逃す反例も残し、否定だけで反対方向が成立したとしない。"
        + link(EXTERNAL, detail_path, "書誌・原典の範囲と独自仮説") + "を参照する。並行する今巡の追加外部調査を68の事前根拠へ遡及しない。\n\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, brief_path) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(HERE / "README.md", brief_path, "コードと再現") + "\n\n[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧G92＋新N92＝184資源。\n\n"
        + link(OLD / "設定と結果.md", brief_path, "旧67の条件発動") + " / " + link(EXTERNAL, brief_path, "事前外部整理")
        + f'\n\n保存監査：{number(proof["照合項目数"])}照合・差{number(proof["不一致数"])}。Viewer実施範囲は監査JSONを正本とする。\n\n'
        "再表示はfit・特徴・予測walk・先着・回収・市場を再実行しない。\n\n~~~powershell\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/レポート.py\n"
        "work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件発動前の否定/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail_path, uses).replace("未使用", "未使用・未検証")
    settings_table = table(["設定ID", "手法/尺度", "設定内容", "限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    inherited = ("## 再計算しない旧入力の被覆と旧回収参考\n\n以下は旧67が継承した旧65の入力・教師・価格経路・量・状態・葉反復を参照する。新Nの否定群や実完結群の被覆ではない。"
        "旧55独立測定は旧即時入口の参考で、新条件時刻の独立回収とは呼ばない。\n\n" + BASE.coverage_table(r) + BASE.quantity_table(r)
        + BASE.state_distribution_table(context) + BASE.episode_support_table(context) + BASE.regime_distribution_table(r)
        + table(["旧用途区間", "旧独立測定状態", "方向行数"], [[x["区間"], x["状態"], x["方向行数"]] for x in r["独立測定"]]))
    sources = table(["出典", "SHA256"], [[link(p, detail_path), sha(p)] for p in context["sources"]])
    brief = "# 00068：発動前の反対端否定で条件を取り消す\n\n" + intro + "## 新旧の入口先着\n\n" + entrance + "## 一建玉の実回収\n\n" + cash + mechanics + links
    detail = ("# 00068：設定と結果\n\n" + intro + "R01=旧G0、R02=旧G1、R03=N0、R04=N1。\n\n## 手法×尺度・版5全文\n\n"
        "55手法×9尺度を全件保持。複合評価を各技法単独の効果と呼ばない。\n\n" + matrix + feature_table(context) + "## 設定明細\n\n" + settings_table
        + reference_tables(context, detail_path) + stage_table(r) + comparison_table(r) + denial_table(r) + inherited + "## 新旧の入口先着\n\n" + entrance + "## 一建玉の実回収\n\n" + cash + detail_tables(r)
        + mechanics + external + "## 検査と来歴\n\n学習参照：" + json.dumps(r["学習参照"], ensure_ascii=False) + "。今回検査：" + json.dumps(r["検査"], ensure_ascii=False)
        + "。教師・同60入力・旧木の指紋は旧証明参照で、68の再fit・再特徴計算ではない。新しい否定付き条件入口と実約定の照合は今回監査へ結合する。\n\n"
        + "## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief_path, detail_path, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detail}


def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """全60特徴・55×9表と内部リンクを検査する。

    引数: output(dict[str,str])は二本文、generated(set[Path])は同時生成又は人工参照。
    返り値: intは確認したリンク数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [line for line in text.splitlines() if line.startswith("| ") and line.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(line.split("|")) != 13 for line in rows):
        raise ValueError("55手法×9尺度不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 61)):
        raise ValueError("全60特徴の表示漏れ")
    return sum(R55.G.check_links(text, STUDY / name, generated) for name, text in output.items())


def render(check: bool = False) -> dict:
    """正式結果の二MDを生成するか保存同byteだけを検査する。

    引数: check(bool)は書込なしの照合。
    返り値: dictは文書SHA・表・リンクと再現確認。
    """
    output = documents(context_for())
    links = validate_documents(output, {(STUDY / name).resolve() for name in output})
    reports = {}
    for name, text in output.items():
        path, content = STUDY / name, text.encode("utf-8")
        if check:
            if path.read_bytes() != content:
                raise ValueError("保存MDと同byteでない:" + name)
        else:
            path.write_bytes(content)
        reports[name] = {"SHA256": sha(path), "bytes": len(content)}
    return {"文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "全特徴": 60,
        "表示中fit": 0, "再計測_再集計_市場再生": False, "同byte確認": check}


def self_test() -> dict:
    """正式入力なしの人工表示検査を呼ぶ。

    引数: なし。
    返り値: dictは成功・件数。失敗時は例外又は終了1。
    """
    spec = importlib.util.spec_from_file_location("反対端否定68表示の人工", HERE / "レポートの人工検査.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run(sys.modules[__name__])


def main() -> None:
    """正式生成・同byte・人工のCLIを選ぶ。

    引数: なし。--checkと--self-testは排他的。
    返り値: None。正式生成はrootの主・監査成功通知後だけ行う。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
