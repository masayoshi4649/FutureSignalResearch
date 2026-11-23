"""69の共通可知教師・新六木と条件運用を、保存物だけから二文書へ表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
OLD = ROOT / "study/00068_発動前の反対端否定で条件を取り消す"
PREFLIGHT = ROOT / "work/条件入口の教師/入力接続確認.json"
SHARED = ROOT / "scripts/条件発動前の否定/レポート.py"
SPEC = importlib.util.spec_from_file_location("条件教師69が参照する固定68表示補助", SHARED)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
V5, R55 = PREVIOUS.V5, PREVIOUS.R55
sha, read, table = PREVIOUS.sha, PREVIOUS.read, PREVIOUS.table
money, rate, qualification, link = PREVIOUS.money, PREVIOUS.rate, PREVIOUS.qualification, PREVIOUS.link
POLICIES = ("N0", "N1", "I0", "I1", "C0", "C1")
NEW, CONTROLS, MODEL_POLICIES = POLICIES[2:], POLICIES[:2], ("I0", "C0")
PERIODS, PERIOD_NAMES, PHASES = PREVIOUS.PERIODS, PREVIOUS.PERIOD_NAMES, PREVIOUS.PHASES
NONFILL = ("未発動", "既超過", "観測不足", "発動未約定", "設定否定", "前提否定")
FORMULAS = PREVIOUS.BASE.FORMULAS
EXTERNAL = ROOT / "docs/議論/外部再調査/反転の確認と取得時点と教師をそろえる.md"
LEARNING = {"元構造": 65, "同じ60特徴": True, "同じ可知集合": True,
    "I教師": "旧即時49/55", "C教師": "新68条件入口の独立先着とO49回収", "無取引": "回収0・障壁対象外"}


def shown(value: object, missing: str = "null（未知）") -> str:
    """保存された有限数・辞書を、未知とゼロを区別して表示する。

    引数: value(object)は保存値、missing(str)はNoneの表示。
    返り値: strは再計算や丸めで採否を変えない表示。
    """
    if value is None:
        return missing
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if type(value) is float:
        return format(value, ".17g")
    return str(value)


def validate_result(result: dict) -> None:
    """新六木・共通教師・六政策の異なる分母を検査する。

    引数: result(dict)は主の小型結果又は人工辞書。
    返り値: None。未知を補完せず、不一致はValueError。
    """
    if result.get("試行") != 69 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("69の旧N二政策と新I/C四政策が必要")
    if (result["新分類器fit"], result["新保存木数"], result["参照モデル数"], result["新運用数"]) != (0, 6, 3, 184):
        raise ValueError("新分類0・新六木・旧参照三木・184運用の差")
    if type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 24:
        raise ValueError("六木四子の最大24回帰fitが必要")
    if result["学習参照"] != LEARNING or result["対照参照"] != {"候補": list(CONTROLS), "元試行": 68, "市場再生": False}:
        raise ValueError("同可知集合の即時/条件教師と旧68保存対照の差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用と評価46場の分離差")
    for field in ("モデル", "回収集計"):
        if len(result[field]) != 6 or {(m["policy"], m["phase"]) for m in result[field]} != {(p, h) for p in MODEL_POLICIES for h in PHASES}:
            raise ValueError("I0/C0各三phaseのモデル又は回収が必要")
        if len({m["id"] for m in result[field]}) != 6:
            raise ValueError("新六木又は回収IDの重複")
    classes = result["独立教師分類"]
    if not set(classes) <= {"確定無取引", "確定約定", "未知"} or any(type(n) is not int or n < 0 for n in classes.values()):
        raise ValueError("独立教師の三分類差")
    if sum(classes.values()) != result["新独立計測"] or result["検査"]["独立方向数"] != result["新独立計測"]:
        raise ValueError("独立測定の分類復元差")
    validate_common(result["共通教師"])
    if set(result["条件段階"]) != set(NEW):
        raise ValueError("条件段階は新四政策が必要")
    for period, scheduled in zip(PERIODS, (740, 888, 74)):
        for policy in POLICIES:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            outcomes = e["結果別"]
            if not set(outcomes) <= set(NONFILL) | {"250", "125", "期限", "不足"} or any(type(n) is not int or n < 0 for n in outcomes.values()):
                raise ValueError("条件入口の結果別差")
            if sum(outcomes.values()) != e["候補"] or e["候補"] - sum(outcomes.get(k, 0) for k in NONFILL) != e["約定"] or e["250"] != outcomes.get("250", 0):
                raise ValueError("条件候補と仮約定・250の分母差")
            for wins, total, field in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
                if (e[field] is None) != (e[total] == 0) or e[total] and not math.isclose(e[field], e[wins] / e[total], rel_tol=0, abs_tol=1e-12):
                    raise ValueError("先着率の分母又はnull差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            conservative = wait + invalid + o["条件未約定"]
            if o["予定枠"] != scheduled or sum(o["判断別"].values()) != scheduled or (o["待ち数"], o["判定不能"]) != (wait, invalid):
                raise ValueError("全予定枠と実判断の分母差")
            if not 0 <= conservative <= scheduled or not math.isclose(o["主待ち率"], wait / scheduled, abs_tol=1e-12, rel_tol=0) or not math.isclose(o["待ち率保守上限"], conservative / scheduled, abs_tol=1e-12, rel_tol=0):
                raise ValueError("条件未約定込み保守待ち率の差")
            if o["活動適格"] != (conservative * 2 <= scheduled):
                raise ValueError("保守待ち50%判定の差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定の費用感応差")
                if (o["品質注意場"] or o["未解消"]) and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意又は未解消の全体確定はnull")
            if sum(o["役割別完結"][r]["件数"] for r in ("順行", "反転")) != o["完結数"]:
                raise ValueError("実役割別完結の件数復元差")
            if item["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("同時適格の差")
            if policy in NEW:
                stage = result["条件段階"][policy][period]
                if stage["全予定枠"] != scheduled or stage["純候補"] != e["候補"] or sum(stage["条件結果別"].values()) != e["候補"] or stage["仮約定"] != e["約定"]:
                    raise ValueError("新四政策の純候補・独立先着段階差")
                if not 0 <= stage["仮約定"] <= stage["発動"] <= stage["純候補"] <= scheduled:
                    raise ValueError("発動段階の順序差")
                if (stage["実条件登録"], stage["実登録未約定"]) != (o["条件登録数"], o["条件未約定"]) or stage["実新規"] + stage["実登録未約定"] != stage["実条件登録"] or not o["完結数"] <= stage["実新規"] <= stage["実条件登録"]:
                    raise ValueError("実一枚の登録・新規・未約定段階差")
    if sum(result["候補"][p][h]["入口"]["候補"] for p in NEW for h in PERIODS) != result["新条件入口評価"]:
        raise ValueError("新条件入口評価数の復元差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])]:
        raise ValueError("新政策の採用差")


def validate_common(groups: dict) -> None:
    """全phaseの共通可知集合と全除外を重複なく復元する。

    引数: groups(dict)は共通教師のphase辞書。
    返り値: None。結果に保存された理由を再判定しない。
    """
    if set(groups) != set(PHASES):
        raise ValueError("共通教師は三phaseが必要")
    for phase, group in groups.items():
        used, excluded = group["使用枠"], group["除外"]
        identities = lambda rows: [(r["session"], r["slot_id"]) for r in rows]
        if group["phase"] != phase or group["共通ID同順序"] is not True or group["方向重み"] != 0.5:
            raise ValueError("共通教師のphase・ID・重み差")
        if len(used) != group["共通可知枠"] or group["共通方向行"] != len(used) * 2 or len(excluded) != group["除外枠数"] or len(used) + len(excluded) != group["全予定枠"]:
            raise ValueError("共通使用/除外枠の全体復元差")
        if len(set(identities(used))) != len(used) or len(set(identities(excluded))) != len(excluded) or set(identities(used)) & set(identities(excluded)):
            raise ValueError("共通教師の使用/除外IDが重複")
        if any(not isinstance(r["理由"], dict) or not r["理由"] for r in excluded):
            raise ValueError("全除外枠に理由が必要")
        for counts in group["全測定分類"].values():
            if sum(counts.values()) != group["全予定枠"] * 2:
                raise ValueError("全方向測定分類の復元差")
        for policy in MODEL_POLICIES:
            if sum(group["使用分類"][policy].values()) != group["共通方向行"]:
                raise ValueError("同一共通集合の方向行数差")


def validate_model(model: dict, calibration: dict, common: dict) -> None:
    """新教師の全回帰行と約定先着支持を分けて全nodeを検査する。

    引数: model/calibration(dict)は同ID保存物、common(dict)は共通教師。
    返り値: None。木の走査・fit・教師再計算はしない。
    """
    structure, training = model["structure"], model["training"]
    if model["policy"] not in MODEL_POLICIES or len(model["feature_meta"]) != 60 or structure["kind"] != "fixed_direction_current_episode":
        raise ValueError("新I0/C0・全60・同65構造の差")
    fixed = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}, {"id": 1, "feature": "F26", "index": 25, "threshold": 0.5}, {"id": 2, "feature": "F20", "index": 19, "threshold": 0.5}]
    projection = {"D0": [i for i in range(60) if i not in (0, 25)], "D1": [i for i in range(60) if i not in (0, 19)]}
    if structure["fixed_nodes"] != fixed or structure["child_feature_indices"] != projection or (structure["max_depth"], structure["child_depth"], structure["child_features"]) != (4, 2, 58):
        raise ValueError("固定三nodeと枝別58列の差")
    ids = [{**r, "side": side} for r in common["使用枠"] for side in (1, -1)]
    if training["row_ids"] != ids or training["direction_rows"] != len(ids) or training["input_pairs"] != len(common["使用枠"]) or training["evaluation_start"] != common["評価開始"]:
        raise ValueError("新木と共通教師ID・方向数・評価時計の差")
    period = training["period"]
    if period["same_second_allowed"] is not False or period["evaluation_start"] != common["評価開始"] or any(not math.isfinite(period[k]) or period[k] >= common["評価開始"] for k in ("max_label_end_time", "max_recovery_end_time")):
        raise ValueError("新木の障壁・回収終端は評価開始よりstrict前")
    if set(training["partition"]) != {f"D{d}_V{v}" for d in (0, 1) for v in (0, 1)}:
        raise ValueError("DI×現在有効の四子が必要")
    if sum(x["direction_rows"] for x in training["partition"].values()) != len(ids):
        raise ValueError("四子の方向行復元差")
    if calibration["model_id"] != model["model_id"] or calibration["policy"] != model["policy"] or calibration["evaluation_start"] != common["評価開始"]:
        raise ValueError("回収集計と新木のID・政策・時点差")
    leaves = set()
    for n in model["nodes"]:
        total, filled = n["direction_rows"], n["filled_direction_rows"]
        if not 0 <= filled <= total or n["unfilled_direction_rows"] != total - filled or n["total_weight"] != total * 0.5 or n["barrier_total_weight"] != filled * 0.5:
            raise ValueError("全回帰行と約定先着分母の差")
        if n["data_absent"] != (total == 0) or n["barrier_data_absent"] != (filled == 0):
            raise ValueError("空回帰葉と全無取引葉の区別差")
        if (n["score"] is None) != (filled == 0) or filled and not math.isclose(n["score"], n["success_weight"] / (filled * 0.5), rel_tol=0, abs_tol=1e-12):
            raise ValueError("障壁scoreは約定既知だけが分母")
        if (n["fill_rate"] is None) != (total == 0) or total and not math.isclose(n["fill_rate"], filled / total, rel_tol=0, abs_tol=1e-12):
            raise ValueError("約定率の全方向分母差")
        if (n["recovery_mse_decimal"] is None) != (total == 0):
            raise ValueError("全無取引MSE0と空MSE未知の区別差")
        expected_support = n["unique_slots"] >= 60 and n["days"] >= 6 and n["sessions"] >= 10
        if n["leaf_support"] != expected_support:
            raise ValueError("約定既知の60枠6日10場と葉支持の差")
        expected_positive = Decimal(n["recovery"]["pnl5"]["sum"]) > 0 if total else None
        if n["recovery_positive"] is not expected_positive:
            raise ValueError("主回収総額の符号と木の正額資格の差")
        for cost in (0, 5, 10):
            all_cash, fill_cash = n["recovery"]["pnl" + str(cost)], n["recovery_filled"]["pnl" + str(cost)]
            if Decimal(all_cash["sum"]) != Decimal(fill_cash["sum"]) or (all_cash["mean"] is None) != (total == 0) or (fill_cash["mean"] is None) != (filled == 0):
                raise ValueError("全回収とfilled回収の合計・null差")
        if n["left"] != -1:
            continue
        leaves.add(str(n["id"]))
        cal = calibration["leaves"][str(n["id"])]
        if cal["positive"] is not bool(expected_positive):
            raise ValueError("主回収総額の符号と回収正額資格の差")
        if (cal["all_direction_rows"], cal["direction_rows"], cal["support"], cal["fill_rate"]) != (total, filled, n["leaf_support"], n["fill_rate"]):
            raise ValueError("回収資格は約定支持・全平均は別欄")
        for cost in (0, 5, 10):
            if (cal["sum_yen"][str(cost)], cal["mean_yen"][str(cost)], cal["mean_all_yen"][str(cost)]) != (n["recovery_filled"]["pnl" + str(cost)]["sum"], n["recovery_filled"]["pnl" + str(cost)]["mean"], n["recovery"]["pnl" + str(cost)]["mean"]):
                raise ValueError("calのfilled平均と全平均の転記差")
    if set(calibration["leaves"]) != leaves:
        raise ValueError("回収集計の全葉不足")


# ----------------------------------------
# 正式表示は成功監査後だけ、小型の結果と新モデルを読む。


def context_for() -> dict:
    """結果・監査・固定・新六木と旧保存対照を結合する。

    引数: なし。
    返り値: dictは表示文脈。詳細gzip・教師個票・原板は開かない。
    """
    names = ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")
    required = [STUDY / n for n in names]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("主と正式保存監査の成功後だけ生成できます")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0]):
        raise ValueError("成功監査・結果・固定のSHA結合差")
    old = read(OLD / "結果.json")
    for p in CONTROLS:
        if any(result[k][p] != old[k][p] for k in ("候補", "役割別入口")):
            raise ValueError("旧68N保存対照の集計差")
    models, sources, metadata = {}, [*required, PREFLIGHT, OLD / "結果.json", OLD / "設定と結果.md", SHARED, EXTERNAL], None
    calibrations = {m["id"]: m for m in result["回収集計"]}
    for entry in result["モデル"]:
        path, cal_entry = ROOT / entry["path"], calibrations[entry["id"]]
        cal_path = ROOT / cal_entry["path"]
        if sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("新モデル又は回収JSONのSHA差")
        model, cal = read(path), read(cal_path)
        if model["model_id"] != entry["id"] or model["policy"] != entry["policy"] or cal_entry["phase"] != entry["phase"]:
            raise ValueError("モデルmetaとpayloadの対応差")
        validate_model(model, cal, result["共通教師"][entry["phase"]])
        if metadata is not None and model["feature_meta"] != metadata:
            raise ValueError("六木の同60metadata差")
        metadata = model["feature_meta"]
        models[entry["id"]] = {"base": model, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry}
        sources.extend((path, cal_path))
    if sum(x["fit_performed"] for m in models.values() for x in m["base"]["training"]["partition"].values()) != result["新回帰器fit"]:
        raise ValueError("新六木の実回帰fit数差")
    if metadata != read(STUDY / "条件.json")["特徴"]:
        raise ValueError("新六木と固定条件の全60metadata差")
    resources = read(required[-1])["resources"]
    if len(resources) != 276 or Counter(r["method_id"] for r in resources) != {p: 46 for p in POLICIES} or any(not (ROOT / r["pnl_path"]).is_file() for r in resources):
        raise ValueError("旧92＋新184のViewer276参照差")
    sources.extend([HERE / "README.md", *sorted(HERE.glob("*.py")), *sorted(HERE.glob("*仕様.md"))])
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "models": models, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def main_tables(result: dict) -> tuple[str, str]:
    """六政策の条件入口先着と一枚実回収を異なる分母で表示する。

    引数: result(dict)は小型結果。
    返り値: tuple[str,str]は入口と実運用の二表。
    """
    entrances, operations = [], []
    for p in POLICIES:
        for h in PERIODS:
            e, o = result["候補"][p][h]["入口"], result["候補"][p][h]["運用"]
            entrances.append([p, PERIOD_NAMES[h], e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]), f'{e["間引き250"]}/{e["間引き約定"]}', rate(e["間引き率"]), f'{e["日数"]}日/{e["場数"]}場', qualification(e["支持"]), qualification(e["70目標"])])
            operations.append([p, PERIOD_NAMES[h], o["完結数"], money(o["完結観測額円"]["5"]), money(o["全体確定額円"]["5"]), len(o["品質注意場"]), rate(o["主待ち率"]), rate(o["待ち率保守上限"]), qualification(o["活動適格"]), f'{o["利益起動件数"]}/{o["起動後赤字件数5"]}', qualification(o["費用適格"]), qualification(result["候補"][p][h]["同時適格"])])
    return table(["候補", "期間", "純候補", "250/仮約定", "主率", "非重複250/約定", "非重複率", "日/場", "入口支持", "70目標"], entrances), table(["候補", "期間", "実完結", "観測5円", "全体確定5円", "品質注意場", "主待ち", "保守上限", "活動", "利益旗/旗後赤字", "費用", "同時適格"], operations)


def common_table(context: dict) -> str:
    """共通教師の全件数・使用ID・全除外理由を表示する。

    引数: context(dict)は三phaseの共通集合と六木。
    返り値: strは全理由とID。未来分類を当時の入力へ戻さない。
    """
    summary, classification, used, excluded, fingerprints = [], [], [], [], []
    for h in PHASES:
        g = context["result"]["共通教師"][h]
        summary.append([h, g["全予定枠"], g["共通可知枠"], g["共通方向行"], g["除外枠数"], shown(g["評価開始"]), g["方向重み"]])
        classification.extend([h, "全測定・" + source, shown(counts)] for source, counts in g["全測定分類"].items())
        classification.extend([h, "共通使用・" + policy, shown(counts)] for policy, counts in g["使用分類"].items())
        used.extend([h, r["session"], r["slot_id"], "+1/-1共通"] for r in g["使用枠"])
        excluded.extend([h, r["session"], r["slot_id"], shown(r["理由"])] for r in g["除外"])
        for policy in MODEL_POLICIES:
            m = context["models"][policy + "_" + h]["base"]
            fingerprints.append([h, policy, m["training"]["row_ids_sha256"], m["training"]["input_rows_sha256"], m["training"]["target_rows_sha256"]])
    return ("## 共通可知教師の集合と全除外\n\nIとCの四測定（即時/条件×買/売）の一つでも未知、又は結果が評価開始と同秒以後ならpair全体を両対照から除外する。"
        "両方向とも確定無取引のpairも残し、回帰回収0・障壁対象外にする。可知終端は障壁と回収の遅い方。原判断より前の終端や不整合は入力エラーで、未知0へ補完しない。\n\n"
        + table(["phase", "過去全予定枠", "共通可知枠", "使用方向行", "除外枠", "評価開始秒・strict前", "方向重み"], summary)
        + table(["phase", "分類母集団", "保存分類件数"], classification)
        + table(["phase", "教師", "共通ID指紋", "入力行指紋", "回収目的指紋"], fingerprints)
        + "使用IDはI/Cで同順序・同じ当時60特徴。結果や目的額は同値を要求しない。全除外理由は次表のまま残し、良い群だけを事後復帰させない。\n\n"
        + table(["phase", "除外場", "除外slot ID", "全除外理由"], excluded)
        + "<details>\n<summary>共通使用枠の全ID（各枠に買・売の二方向）</summary>\n\n" + table(["phase", "場", "使用slot ID", "方向"], used) + "</details>\n\n")


def model_tables(context: dict, output: Path) -> str:
    """新六木の全node・全path・支持・二種類の回収平均を表示する。

    引数: context(dict)は新モデル、output(Path)は詳細MD。
    返り値: strは閾値を省略しない表。円予測を先着率に読み替えない。
    """
    meta, parts, nodes, cash, calibrations = [], [], [], [], []
    for identity, item in context["models"].items():
        m, cal = item["base"], item["calibration"]
        meta.append([link(item["base_path"], output, identity), m["policy"], item["entry"]["phase"], len(m["nodes"]), "pnl5・squared_error", len(item["entry"]["学習場"]), len(item["entry"]["評価場"])])
        for key, group in m["training"]["partition"].items():
            parts.append([identity, key, group["route"], group["direction_rows"], group["pair_unique"], group["days"], group["sessions"], group["root"], group["node_count"], qualification(group["fit_performed"])])
        for n in m["nodes"]:
            split = "葉" if n["left"] == -1 else m["feature_meta"][n["feature"]]["id"] + " <= " + shown(n["threshold"]) + ("（固定）" if n["id"] < 3 else "")
            path = " ∧ ".join(p["feature_id"] + p["comparison"] + shown(p["threshold"]) for p in n["path"]) or "根"
            nodes.append([identity, n["id"], split, f'{n["left"]}/{n["right"]}', path, n["direction_rows"], n["filled_direction_rows"], n["unfilled_direction_rows"], shown(n["fill_rate"]), shown(n["score"]), f'{n["all_unique_slots"]}/{n["all_days"]}/{n["all_sessions"]}', f'{n["unique_slots"]}/{n["days"]}/{n["sessions"]}', qualification(n["leaf_support"]), "/".join(n["families"]) or "なし", qualification(n["method_support"])])
            state = "空回帰・先着未知" if n["data_absent"] else "全無取引・回帰0既知/先着未知" if n["barrier_data_absent"] else "約定既知あり"
            for fee in (0, 5, 10):
                a, f = n["recovery"]["pnl" + str(fee)], n["recovery_filled"]["pnl" + str(fee)]
                cash.append([identity, n["id"], fee, state, a["sum"], shown(a["mean_decimal"]), f["sum"], shown(f["mean_decimal"]), shown(n.get("regression_value"), "対象外又は空"), shown(n.get("impurity"), "対象外又は空"), shown(n["recovery_mse_decimal"])])
            if n["left"] == -1:
                q = cal["leaves"][str(n["id"]) ]
                calibrations.append([identity, n["id"], q["all_direction_rows"], q["direction_rows"], f'{q["unique_slots"]}/{q["days"]}/{q["sessions"]}', shown(q["fill_rate"]), shown(q["sum_yen"]), shown(q["mean_yen"]), shown(q["mean_all_yen"]), qualification(q["support"]), qualification(q["positive"])])
    return ("## 新六木の全nodeと全回収葉\n\nI0/C0を三phaseずつ学習し、I1/C1はそれぞれ同木。固定根はfloat32 F01<=0、低側RのF26<=0.5／高側TのF20<=0.5。"
        "DI非正子はindex0/25、DI正子はindex0/19を除く58列深さ2、全深さ4・minleaf60・seed51・方向重み0.5。"
        "V1はbから有効でr/k確認を意味しない。V0は未登録・取消・TTL等の混合。raw DI同値は最終WAIT、float32零化と混同しない。\n\n"
        + table(["保存木", "教師", "phase", "全node数", "回帰目的", "過去場", "評価場"], meta)
        + table(["木", "固定群", "対応", "全方向行", "unique枠", "日", "場", "子root", "子node数", "fit"], parts)
        + "先着scoreは250/約定既知だけ、無取引0は回帰に含む。支持60枠・6日・10場も約定既知だけで、全回帰行のminleaf60とは異なる。固定trend+priceは従来技法資格を構造的に充足するが、独立証拠が増えたとはしない。\n\n"
        + table(["木", "node", "分岐・左<=右>", "左/右", "全path", "全回帰行", "filled行", "無取引行", "約定率", "条件付き先着score", "全unique/日/場", "filled unique/日/場", "filled葉支持", "path family", "技法資格"], nodes)
        + "回帰目的は無取引0込みpnl5のMSE。目的平均を先着確率とは呼ばず、方向順位は障壁score、両側資格を先に評価する固定66選択を維持する。同点・片側score未知はWAITで、0政策と正回収1政策は逆方向になり得る。\n\n"
        + table(["木", "node", "滑りpt", "回帰/障壁の状態", "全合計円", "全平均Decimal円", "filled合計円", "filled平均Decimal円", "生回帰予測5円", "生MSE5円²", "Decimal MSE5円²"], cash)
        + "全無取引葉は全平均0・MSE0が既知でもscoreとfilled平均はnull。空回帰葉は両平均・MSEともnull。固定三nodeは学習器の生予測対象外で、所属からの統計と区別する。calのpositive=Falseは不適格であり空の平均0ではない。\n\n"
        + table(["木", "葉", "全行", "filled行", "filled unique/日/場", "約定率", "合計円0/5/10", "filled平均円0/5/10", "全平均円0/5/10", "回収支持", "主合計strict正"], calibrations))


def detail_tables(result: dict) -> str:
    """全期間・実役割・費用・判断理由と条件段階を保存値で表示する。

    引数: result(dict)は六政策の結果。
    返り値: strは純と実を加算せずに示す詳細表。
    """
    costs, roles, stages, reasons = [], [], [], []
    for p in POLICIES:
        for h in PERIODS:
            o = result["候補"][p][h]["運用"]
            costs.append([p, PERIOD_NAMES[h], o["予定枠"], shown(o["判断別"]), o["条件登録数"], o["条件未約定"], o["完結数"], *(money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)), *(money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)), o["未解消"], shown(o["品質注意場"])])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][p][h][role], o["役割別完結"][role]
                roles.append([p, PERIOD_NAMES[h], role, e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]), qualification(e["支持"]), actual["件数"], money(actual["観測純額5"])])
            if p in NEW:
                stages.extend([p, PERIOD_NAMES[h], k, shown(v)] for k, v in result["条件段階"][p][h].items())
                reasons.extend([p, PERIOD_NAMES[h], k, n] for k, n in result["判断理由"][p][h].items())
    return ("## 予定枠・費用と品質\n\n品質注意又は未解消は期間全体確定null。観測額・役割別観測額を無条件確定としない。\n\n"
        + table(["政策", "期間", "全予定", "実判断別", "登録", "登録未約定", "完結", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "未解消", "品質注意場"], costs)
        + "## DI役割別の純入口と実回収\n\n価格T/Rの名称、現在episode有効、raw DIに対する実役割は別。薄化・仮先着と実一枚を加算しない。\n\n"
        + table(["政策", "期間", "実役割", "純候補", "250/仮約定", "主率", "入口支持", "実完結", "観測5円"], roles)
        + "## 条件段階と当時の保存判断理由\n\n条件登録actionは当時の指示、発動・未約定等はその後の結果。保有又はpendingの占有と独立仮入口を混同しない。\n\n"
        + table(["政策", "期間", "段階", "保存値"], stages) + table(["政策", "期間", "保存判断理由", "枠数"], reasons))


# ----------------------------------------
# 全60特徴と版5全文を表示し、生成時に市場計算をしない。


def settings(context: dict) -> list[dict]:
    """同60特徴・新教師・固定条件入口を版5セルへ対応させる。

    引数: context(dict)はmetadataを持つ表示文脈。
    返り値: list[dict]は設定IDと複合評価ID。
    """
    rows = deepcopy(PREVIOUS.settings(context)[:60])
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04/R05/R06", 説明="旧Nと新I/Cは同60特徴。I/Cは共通可知pairで教師の入口だけを比較。単独技法の効果ではない。")
    extras = [(["M01", "P10"], ["m03", "m15", "m30"], "I/C同65根・子58列深さ2", "六木・最大24回帰fit、I1/C1別fitなし。回帰pnl5には確定無取引0を含む。"),
        (["M01"], ["m03", "m15", "m30", "tick"], "先着scoreと回収・支持の分母を分離", "score=250/約定既知。filled60枠6日10場、複数技法・回収支持。1政策だけDecimal主合計strict正。"),
        (["P02", "P09", "B01"], ["m03", "tick"], "同68条件発動・発動前反対端否定", "設定否定は未登録WAIT、監視否定は登録未約定。gap>300観測不足は品質、否定自体は品質注意でない。"),
        (["E01", "E02", "C06"], ["tick"], "同O49・現在益122円strict正・連続非緩和追尾", "固定250TPなし。返済pendingでh/L/arm凍結、費用感応は同約定・起動122円不変。"),
        (["C07"], ["m15"], "全25/49枠・条件未約定込み保守待ち50%以下", "保有継続非待ち。未約定監視を実参加へ数えず、全予定分母に残す。")]
    for methods, scales, short, description in extras:
        rows.append({"設定ID": f"S{len(rows) + 1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "結果短記": "R03/R04/R05/R06", "説明": description})
    return rows


def documents(context: dict) -> dict[str, str]:
    """新教師と実運用の二文書を純表示として構成する。

    引数: context(dict)は正式又は人工文脈。
    返り値: dict[str,str]はREADMEと設定と結果。書込はしない。
    """
    r, proof = context["result"], context["proof"]
    brief, detail = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operations = main_tables(r)
    status = "新候補の採用なし。支持付き先着70・費用・全予定保守待ち50%以下の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見利益の保証ではない。"
    intro = ("全66場既使用。初20場は学習専用、結果の学習欄は後20時系列、選択24・既使用後続2は別評価。\n\n" + status
        + f'\n\n旧68N0/N1保存92運用、新I0/I1/C0/C1各46場の184運用、Viewer276。新六木・回帰fit{r["新回帰器fit"]}、新分類fit0、全ready条件独立測定{r["新独立計測"]}方向。全60特徴・65の固定構造・68条件入口・O49保護は維持。\n\n'
        "旧N→新Iは共通可知集合と無取引分母の変更を含む。I→Cが同じ可知集合・同じ技法/学習構造・同じ条件運用に対する教師変更の比較。Iの教師は旧即時49/55、Cの教師は新68条件入口。Iの実売買も条件入口であり、即時運用の再実行ではない。\n\n")
    mechanics = ("## 固定した判断・条件発動・利益保護\n\nデイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。定時の60特徴から両方向を同じ関数で評価し、同点・片側score未知はWAIT。"
        "両側のscore>=1/3・filled支持・複数技法・回収支持を先に評価し適格内最高側。I1/C1だけ主回収strict正も要求するため、0と1を同方向の部分集合とは断定しない。raw DI0は最終WAIT。\n\n"
        "最新公開完全3分足high/lowを定時凍結。買Last>high／売Last<lowで要求し、設定既超過は拒否。買Last<=low／売Last>=highは発動前否定。設定否定は未登録WAIT、監視後前提否定は登録未約定で、否定自体は品質注意でない。"
        "normal BBO＋有限正Lastで監視、gap>300秒の観測不足を優先。否定後の同枠復活・自動逆注文はなく、発動後pendingや保有へこの否定を追加しない。\n\n"
        "次定時T+900 timerでwatchと新規pendingを取消。発動後1価格時計秒・後行正常BBO・TTL30秒も次定時未満。Lastや過去線価格へ約定を戻さず、足内順をOHLCから補わない。途中の新指標で候補やDを更新しない。\n\n"
        "主待ち=WAIT/全予定、保守=(WAIT＋判定不能＋条件登録後entryなし)/全予定で50%以下。保有は非待ち。候補・登録・発動・仮約定・実新規・完結は別分母。"
        "micro10円/pt、片道11円＋滑り5ptの往復122円。現在正常返済BBOの粗益−122円strict正で利益旗と最低名目新規床。Dは定時ATRの5pt切上げを5..125へ制限し、損失側も連続非緩和。"
        "返済pendingでh/L/arm凍結。強制15:35/05:50、終了15:40/05:55、残60停止なし・固定250TPなし。費用0/10感応は同約定・利益旗122円不変。名目保護線は実損や費用後同値の保証でない。\n\n")
    links = ("## 正本・再表示\n\n" + " / ".join(link(STUDY / n, brief) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(HERE / "README.md", brief, "コードと再現") + " / " + link(OLD / "設定と結果.md", brief, "旧68N保存対照") + "\n\n[Viewer](http://127.0.0.1:8092)：旧92＋新184＝276資源。"
        + f'保存監査{proof["照合項目数"]}照合・差{proof["不一致数"]}。実施範囲は監査JSONを正本とする。\n\n'
        "~~~powershell\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/レポート.py\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/条件入口の教師/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail, uses).replace("未使用", "未使用・未検証")
    features = table(["ID", "特徴", "手法", "family", "尺度", "式・範囲"], [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i]] for i, m in enumerate(context["metadata"])])
    settings_table = table(["設定ID", "手法/尺度", "設定内容", "限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    external = ("## 原典と独自の教師規約\n\nBrooks本人2017講義とBulkowski出版社2021公開章は、二度目の反転も失敗する例、図形確認と取得時計、選んだ好例と比較分母を分ける参考。"
        "図形種類の成績比較割合を取引勝率にせず、日週株式やEmini例をNK短期の利益証明にしない。心理は推論で、量から新規/返済や主体を直測したものではない。"
        + link(EXTERNAL, detail, "出典・読取範囲・未検証候補") + "。共通pair、無取引0、条件付きscore、15分/Last/BBO/費用122円は独自規約であり、原典の退出をO49へ移植しない。\n\n")
    sources = table(["出典", "SHA256"], [[link(p, detail), sha(p)] for p in context["sources"]])
    overview = "# 00069：条件入口に合わせて技法群の教師を作る\n\n" + intro + "## 条件入口先着\n\n" + entrance + "## 実一枚の回収\n\n" + operations + mechanics + links
    settings_doc = ("# 00069：設定と結果\n\n" + intro + "R01=旧N0、R02=旧N1、R03=I0、R04=I1、R05=C0、R06=C1。\n\n## 手法×尺度・版5全文\n\n55手法×9尺度を全件保持。複合評価を指標単独の効果としない。\n\n" + matrix
        + "## 同じ全60特徴\n\n現在有効とr/k成立は別。旧特徴を再生成せず、六木の同じmetadataを表示する。未知値0＋maskと、教師未知の除外は別規約。"
        "b/rの量は同種・同限月の直近10完了場の同index基準、完全q5以上・平均正。b/rの一足価格差は現在ATRで尺度化し、量だけの方向票にしない。段階なし・数量基準不足・既知0量と共同maskを分ける。\n\n" + features + "## 設定明細\n\n" + settings_table
        + common_table(context) + model_tables(context, detail) + "## 条件入口先着\n\n" + entrance + "## 実一枚の回収\n\n" + operations + detail_tables(r) + mechanics + external
        + "## 検査と独立教材の限界\n\n独立教材の重複建玉合算は同時実行可能な戦略利益ではない。新規と同じ独立回収との経済属性照合は保存検査で行い、表示時に再生しない。"
        + "入力検査：" + shown(r["入力検査"]) + "。今回検査：" + shown(r["検査"]) + "。独立教師分類：" + shown(r["独立教師分類"]) + "。\n\n## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief, detail, "概要と表示コマンド") + "\n")
    return {"README.md": overview, "設定と結果.md": settings_doc}


def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """全文表・全60特徴と内部リンクを検査する。

    引数: output(dict[str,str])は二本文、generated(set[Path])は同時生成又は人工参照。
    返り値: intは検査したリンク数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [s for s in text.splitlines() if s.startswith("| ") and s.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(s.split("|")) != 13 for s in rows):
        raise ValueError("55手法×9尺度不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 61)):
        raise ValueError("全60特徴不足")
    return sum(R55.G.check_links(s, STUDY / name, generated) for name, s in output.items())


def render(check: bool = False) -> dict:
    """正式結果の二文書を生成するか保存同byteを検査する。

    引数: check(bool)は書込なしの同byte照合。
    返り値: dictは成果物SHA・サイズ・表・リンク。
    """
    output = documents(context_for())
    links = validate_documents(output, {(STUDY / n).resolve() for n in output})
    reports = {}
    for name, text in output.items():
        path, content = STUDY / name, text.encode("utf-8")
        if check:
            if path.read_bytes() != content:
                raise ValueError("保存文書と同byteでない:" + name)
        else:
            path.write_bytes(content)
        reports[name] = {"SHA256": sha(path), "bytes": len(content)}
    return {"文書": reports, "内部リンク検査": links, "欠落": 0, "版": 5, "手法": 55, "尺度": 9, "全特徴": 60,
        "表示中fit": 0, "再計測_教師再生成_市場再生": False, "同byte確認": check}


def self_test() -> dict:
    """実入力なしの人工表示検査を呼ぶ。

    引数: なし。
    返り値: dictは成功とテスト件数。失敗時は終了1。
    """
    spec = importlib.util.spec_from_file_location("条件教師69表示の人工", HERE / "レポートの人工検査.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run(sys.modules[__name__])


def main() -> None:
    """正式生成・同byte・人工だけのCLIを選択する。

    引数: なし。--checkと--self-testは排他的。
    返り値: None。正式生成はrootの主・監査成功通知後だけ行う。
    """
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true")
    options.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
