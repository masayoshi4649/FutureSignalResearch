"""65の保存全60入力・現在有効の固定根と実運用を再計算せず表示する。"""

import argparse
from collections import Counter
from decimal import Decimal, localcontext
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
OLD = ROOT / "study/00064_再試験の量と価格進行を別々に確認"
SHARED = ROOT / "scripts/量と価格進行/レポート.py"
SPEC = importlib.util.spec_from_file_location("現在状態65の固定64表示純補助", SHARED)
R64 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R64
SPEC.loader.exec_module(R64)
R63, R56, R55, V5 = R64.BASE, R64.R56, R64.R55, R64.V5
POLICIES, NEW = ("Q0", "Q1", "U0", "U1"), ("U0", "U1")
PERIODS, PERIOD_NAMES, PHASES = R56.PERIODS, R56.PERIOD_NAMES, R56.PHASES
sha, read, fingerprint, table = R56.sha, R56.read, R56.fingerprint, R56.table
number, rate, qualification, link, money = R56.number, R56.rate, R56.qualification, R56.link, R56.money
FORMULAS = R64.FORMULAS
CHILD_FEATURE_INDICES = {"D0": [i for i in range(60) if i not in (0, 25)], "D1": [i for i in range(60) if i not in (0, 19)]}
EXTERNAL = ROOT / "docs/議論/外部再調査/初動と現在の前提と再点火を分ける.md"
validate_coverage = R63.validate_coverage
validate_regime_distribution = R63.validate_regime_distribution
validate_episode_counts = R63.validate_episode_counts
coverage_table = R63.coverage_table
regime_distribution_table = R63.regime_distribution_table
quantity_table = R64.quantity_table

# ----------------------------------------
# 目的・分母・保存状態だけを検査し、学習・予測・市場再生をしない。
def validate_result(result: dict) -> None:
    """新旧候補・固定期間・分母・nullとfitの用途を検査する。

    引数: result(dict)は65の保存結果。市場や教師の系列は開かない。
    返り値: None。不一致は例外にする。
    """
    if result.get("試行") != 65 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("65の候補又は既使用契約が不正")
    if type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 12 or (result["新分類器fit"], result["新独立計測"], result["新運用数"]) != (0, 0, 92):
        raise ValueError("回帰最大12・分類0・新独立計測0・新運用92の契約差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・評価46場の区分差")
    if result["対照参照"] != {"候補": ["Q0", "Q1"], "元試行": 64, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("対照は固定64Q0/Q1保存値だけ")
    if result["独立測定参照"]["元試行"] != 55 or result["独立測定参照"]["再計測"] is not False:
        raise ValueError("独立測定は固定55参照だけ")
    if sum(r["方向行数"] for r in result["独立測定"]) != 4884:
        raise ValueError("既存2442枠両方向4884記録の差")
    keys = {"input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256"}
    if set(result["旧教師一致"]) != set(PHASES) or any(set(x) != keys or any(v is not True for v in x.values()) for x in result["旧教師一致"].values()):
        raise ValueError("旧教師4指紋一致が必要")
    if result["教師集合一致"] != {p: True for p in PHASES}:
        raise ValueError("旧D0・新回帰・55回収の教師集合一致が必要")
    validate_coverage(result["価格経路分布"])
    validate_regime_distribution(result["局面分布"], result["価格経路分布"])
    if result["検査"]["旧64特徴保存一致"] != 3404:
        raise ValueError("旧64評価3404方向の全60特徴一致が必要")
    for period, count in zip(PERIODS, (740, 888, 74)):
        if result["準備比較"][period]["全予定枠"] != count:
            raise ValueError("全予定枠分母差")
        for policy in POLICIES:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            if sum(e["結果別"].values()) != e["候補"] or e["候補"] - e["結果別"].get("未約定", 0) != e["約定"]:
                raise ValueError("純採用と仮約定の分母差")
            for win, total, value in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
                if (e[value] is None) != (e[total] == 0) or e[total] and not math.isclose(e[value], e[win] / e[total], abs_tol=1e-12, rel_tol=0):
                    raise ValueError("先着率分母差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            if o["予定枠"] != count or sum(o["判断別"].values()) != count or (o["待ち数"], o["判定不能"]) != (wait, invalid):
                raise ValueError("実運用予定枠差")
            if not math.isclose(o["主待ち率"], wait / count, abs_tol=1e-12, rel_tol=0) or not math.isclose(o["待ち率保守上限"], (wait + invalid) / count, abs_tol=1e-12, rel_tol=0):
                raise ValueError("活動率分母差")
            if o["活動適格"] != ((wait + invalid) * 2 <= count):
                raise ValueError("保守上限50%の判定差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定費用感応差")
                if o["品質注意場"] and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意の確定null差")
            if item["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("同時適格差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][t]["同時適格"] for t in PERIODS[:2])]:
        raise ValueError("新候補の採用差")

def context_for() -> dict:
    """正式結果と監査が完成してから小型保存物だけを読む。

    引数: なし。
    返り値: dictは表示文脈。原板・圧縮詳細・計測・fit・予測walkは利用しない。
    """
    required = [STUDY / n for n in ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError("正式結果・保存監査の完成後だけ生成できます: " + str(path))
    result, proof, fixed = read(required[0]), read(required[1]), read(required[2])
    validate_result(result)
    if result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0]):
        raise ValueError("固定・正式保存監査・結果SHAの差")
    old = read(OLD / "結果.json")
    for p in ("Q0", "Q1"):
        if result["候補"][p] != old["候補"][p] or result["役割別入口"][p] != old["役割別入口"][p]:
            raise ValueError("固定64の対照集計差")
    for k in ("評価場", "学習専用場", "準備比較", "独立測定", "価格経路分布", "局面分布", "数量分布"):
        if result[k] != old[k]:
            raise ValueError("固定64の期間・準備・測定参照差:" + k)
    if result["対照モデル"] != [m for m in old["モデル"] if m["policy"] == "Q0"]:
        raise ValueError("固定64の対照モデル差")
    measured = result["独立測定参照"]
    if measured != old["独立測定参照"]:
        raise ValueError("固定55独立測定参照のパス又はSHA差")
    if len(result["モデル"]) != 3 or len(result["回収集計"]) != 3:
        raise ValueError("新U0三木・三回収集計が必要")
    calibrations = {x["phase"]: x for x in result["回収集計"]}
    models, paths, metadata = {}, [], None
    for entry in result["モデル"]:
        phase = entry["phase"]
        if phase not in PHASES or phase in models or entry["id"] != "U0_" + phase or entry["policy"] != "U0":
            raise ValueError("新3モデルのID・phase差")
        path = (ROOT / entry["path"]).resolve()
        cal_entry = calibrations[phase]
        if cal_entry["id"] != entry["id"] or cal_entry["policy"] != "U0":
            raise ValueError("U0回収metaのID又は政策差")
        cal_path = (ROOT / cal_entry["path"]).resolve()
        if any(not p.is_relative_to(STUDY) for p in (path, cal_path)) or sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("新モデル・回収集計の版差")
        model, cal = read(path), read(cal_path)
        validate_model(model)
        prior_entry = next(x for x in old["モデル"] if x["phase"] == phase and x["policy"] == "Q0")
        prior_model = read(ROOT / prior_entry["path"])
        if sha(ROOT / prior_entry["path"]) != prior_entry["SHA256"]:
            raise ValueError("旧64モデルの指紋差")
        validate_prior60(model, prior_model)
        R55.validate_calibration(cal, model)
        if cal["base_model_path"] != entry["path"] or cal["base_model_sha256"] != entry["SHA256"] or cal["phase"] != phase or cal["policy"] != "U0":
            raise ValueError("新回帰木と回収集計の出典差")
        if metadata is None:
            metadata = model["feature_meta"]
        if model["feature_meta"] != metadata or len(metadata) != 60:
            raise ValueError("共通60特徴の順序差")
        models[phase] = {"entry": entry, "base": model, "calibration": cal, "path": cal_path, "base_path": path}
        for key, leaf in cal["leaves"].items():
            node = next(n for n in model["nodes"] if n["id"] == int(key))
            if bool(node["direction_rows"]) and node["recovery_positive"] != leaf["positive"]:
                raise ValueError("回帰木と回収集計の正額差")
            for cost in (0, 5, 10):
                saved = node["recovery"][f"pnl{cost}"]
                if Decimal(saved["sum"]) != Decimal(leaf["sum_yen"][str(cost)]) or saved["mean"] != leaf["mean_yen"][str(cost)]:
                    raise ValueError("回帰木と回収集計の合計/平均差")
        paths.extend((path, cal_path))
    if set(models) != set(PHASES) or set(calibrations) != set(PHASES):
        raise ValueError("W20/W30/F40の新木・回収集計各3が必要")
    if sum(p["fit_performed"] for m in models.values() for p in m["base"]["training"]["partition"].values()) != result["新回帰器fit"]:
        raise ValueError("保存した実回帰fit数と全partition合計の差")
    validate_episode_support(result["経路支持"], models)
    R64.validate_quantity_distribution(result["数量分布"], result["価格経路分布"])
    validate_state_distribution(result["状態分布"], models)
    resources = read(STUDY / "一覧.resources.json")["resources"]
    if len(resources) != 184 or Counter(x["method_id"] for x in resources) != {p: 46 for p in POLICIES}:
        raise ValueError("旧92+新92の184Viewer資源差")
    if any(not (ROOT / x["pnl_path"]).is_file() for x in resources):
        raise ValueError("Viewer約定参照欠落")
    sources = [*required, *paths, Path(__file__), HERE / "README.md", HERE / "検証.py", HERE / "学習.py", HERE / "保存検証.py",
               HERE / "レポートの人工検査.py", EXTERNAL, SHARED, R56.SHARED, R55.SHARED, ROOT / "scripts/レポート/カタログ版5.py", ROOT / "scripts/レポート/設定結果レポート.py",
               V5.CATALOG, V5.MASTER, OLD / "結果.json", OLD / "設定と結果.md", OLD / "保存物確認.json",
               ROOT / "scripts/局所帯分岐/特徴仕様.md", ROOT / "scripts/量と価格進行/特徴.py", ROOT / "scripts/量と価格進行/特徴仕様.md", ROOT / "scripts/波の区間分離/特徴仕様.md", ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md",
               ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md", ROOT / "docs/議論/回収を分割目的にした技法群の比較.md"]
    for x in result["対照モデル"]:
        p = ROOT / x["path"]
        if sha(p) != x["SHA256"]:
            raise ValueError("旧回収集計のSHA差")
        sources.append(p)
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "models": models, "metadata": metadata,
            "sources": list(dict.fromkeys(sources))}

def validate_model(model: dict) -> None:
    """保存回帰木の表示に必要な全nodeと葉の有効性を検査する。

    引数: model(dict)は学習担当の保存schema。実予測は行わない。
    返り値: None。不明な目的・欠けたnode・不正数値は拒否する。
    """
    if model["policy"] != "U0" or len(model["feature_meta"]) != 60 or len({n["id"] for n in model["nodes"]}) != len(model["nodes"]):
        raise ValueError("60特徴又はnode一意性の差")
    for index, meta in enumerate(model["feature_meta"][54:], 54):
        price = index in (55, 57)
        if (meta["method"], meta["family"], meta["scale"]) != ("P05" if price else "V01", "price" if price else "volume", "m03"):
            raise ValueError("既存量価格六列のmetadata差")
    structure = model["structure"]
    if (structure["kind"], structure["child_depth"], structure["child_features"], structure["max_depth"], structure["fixed_mse_optimized"], structure["child_estimator"], structure["target"]) != ("fixed_direction_current_episode", 2, 58, 4, False, "DecisionTreeRegressor", "pnl5"):
        raise ValueError("固定二段・子回帰目的の差")
    for parameters, depth in ((model["parameters"], 4), (model["subtree_parameters"], 2)):
        if (parameters["criterion"], parameters["max_depth"], parameters["min_samples_leaf"], parameters["random_state"]) != ("squared_error", depth, 60, 51) or "class_weight" in parameters:
            raise ValueError("回帰の固定設定差")
    if structure["child_feature_indices"] != CHILD_FEATURE_INDICES or structure["feature_count"] != 60 or structure["excluded_feature_indices"] != {"D0": [0, 25], "D1": [0, 19]}:
        raise ValueError("DI枝ごとの58列の子投影差")
    if [(n["feature"], n["threshold"]) for n in model["nodes"][:3]] != [(0, 0.0), (25, .5), (19, .5)]:
        raise ValueError("DI→対応経路episode有効の固定根が不一致")
    if structure["fixed_nodes"] != [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0},
            {"id": 1, "feature": "F26", "index": 25, "threshold": .5},
            {"id": 2, "feature": "F20", "index": 19, "threshold": .5}]:
        raise ValueError("固定三nodeのmetadata差")
    for node in model["nodes"][3:]:
        direction = int(node["path"][0]["comparison"] == ">")
        if node["left"] != -1 and node["feature"] not in CHILD_FEATURE_INDICES[f"D{direction}"]:
            raise ValueError("子木は当該方向枝の固定2列を再使用しない")
    partitions = model["training"]["partition"]
    if set(partitions) != {f"D{d}_V{k}" for d in (0, 1) for k in (0, 1)}:
        raise ValueError("DIと対応現在有効の四群差")
    for d in (0, 1):
        route, flag = ("R", 25) if d == 0 else ("T", 19)
        for k in (0, 1):
            row = partitions[f"D{d}_V{k}"]
            if (row["d"], row["v"], row["route"], row["policy"], row["excluded_feature_indices"], row["child_feature_indices"]) != (d, k, route, "U0", [0, flag], CHILD_FEATURE_INDICES[f"D{d}"]):
                raise ValueError("方向partitionの対象経路又は子投影差")
    ids = {n["id"] for n in model["nodes"]}
    for n in model["nodes"]:
        if n["left"] != -1 and (n["left"] not in ids or n["right"] not in ids or not 0 <= n["feature"] < 60 or not math.isfinite(n["threshold"])):
            raise ValueError("分岐参照又は閾値が不正")
        if n["impurity_kind"] != "squared_error" or n["total_weight"] != n["direction_rows"] * .5:
            raise ValueError("node目的又は方向重み差")
        count = n["direction_rows"]
        if (n["score"] is None) != (count == 0) or count and n["score"] != n["success_weight"] / n["total_weight"]:
            raise ValueError("障壁scoreは回帰予測とは別の先着割合が必要")
        if n["data_absent"] != (count == 0):
            raise ValueError("空node表示差")
        families = {model["feature_meta"][p["feature"]]["family"] if "feature" in p else p["family"] for p in n["path"]}
        expected_method = len(families) >= 2 and bool(families & {"trend", "osc"})
        if set(n["families"]) != families or n["method_support"] != expected_method:
            raise ValueError("固定trend/priceを含むpath技法資格が不一致")
        for key in ("pnl0", "pnl5", "pnl10"):
            recovery = n["recovery"][key]
            total = Decimal(recovery["sum"])
            if not total.is_finite():
                raise ValueError("回収合計は有限十進数が必要")
            if not count:
                if total != 0 or recovery["mean"] is not None or recovery["mean_decimal"] is not None:
                    raise ValueError("空nodeの平均はnull")
            else:
                with localcontext() as decimal_context:
                    decimal_context.prec = 80
                    mean = total / count
                if recovery["mean"] != float(mean) or Decimal(recovery["mean_decimal"]) != mean:
                    raise ValueError("Decimal平均表示差")
        expected_positive = Decimal(n["recovery"]["pnl5"]["sum"]) > 0 if count else None
        if n["recovery_positive"] is not expected_positive:
            raise ValueError("回収正は十進合計の符号、空nodeは未知")
        if not count:
            if n["regression_value"] is not None or n["impurity"] is not None or n["recovery_mse_decimal"] is not None:
                raise ValueError("空nodeの回帰予測/MSEはnull")
        elif not math.isclose(n["regression_value"], n["recovery"]["pnl5"]["mean"], abs_tol=1e-10, rel_tol=1e-12):
            raise ValueError("生回帰平均の限定許容外")

def validate_prior60(model: dict, prior_model: dict) -> None:
    """同じ全60入力の六指紋を旧64正本へ結ぶ。

    引数: model/prior_model(dict)は65と固定64の同phase保存木。
    返り値: None。base60六指紋と既存18/30/38/46/54射影の保持を確認する。
    """
    if model["feature_meta"][:60] != prior_model["feature_meta"] or len(prior_model["feature_meta"]) != 60:
        raise ValueError("旧60特徴metadataの順序差")
    keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
    if model["training"]["base60_fingerprints"] != {key: prior_model["training"][key] for key in keys}:
        raise ValueError("旧60特徴教師6指紋が不一致")
    if any(model["training"][key] != prior_model["training"][key] for key in keys):
        raise ValueError("新旧全60canonicalの六指紋差")
    for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints", "base54_fingerprints"):
        if model["training"][key] != prior_model["training"][key]:
            raise ValueError("既存射影の教師指紋が変化: " + key)

def main_tables(result: dict) -> tuple[str, str]:
    """四候補の入口と一建玉の実運用を別表にする。

    引数: result(dict)は保存結果。
    返り値: tuple[str,str]は先着表と運用表。
    """
    entrance, cash = [], []
    for p in POLICIES:
        for t in PERIODS:
            e, o = result["候補"][p][t]["入口"], result["候補"][p][t]["運用"]
            entrance.append([p, PERIOD_NAMES[t], e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]),
                             f'{e["間引き250"]}/{e["間引き約定"]}', rate(e["間引き率"]), f'{e["日数"]}日/{e["場数"]}場',
                             qualification(e["支持"]), qualification(e["70目標"])])
            cash.append([p, PERIOD_NAMES[t], o["完結数"], money(o["完結観測額円"]["5"]), money(o["全体確定額円"]["5"]),
                         len(o["品質注意場"]), rate(o["主待ち率"]), rate(o["待ち率保守上限"]), qualification(o["活動適格"]),
                         f'{o["利益起動件数"]}/{o["起動後赤字件数5"]}', qualification(o["費用適格"]), qualification(result["候補"][p][t]["同時適格"])])
    return (table(["候補", "期間", "純採用", "250/仮約定", "主率", "非重複250/約定", "非重複率", "日/場", "入口支持", "70目標"], entrance),
            table(["候補", "期間", "実完結", "観測5円", "全体確定5円", "品質注意場数", "待ち", "保守上限", "活動", "利益旗/旗後赤字", "費用", "同時適格"], cash))

def detail_tables(result: dict) -> str:
    """費用感応・品質・DI役割・保存理由を表示する。

    引数: result(dict)は65結果。
    返り値: strは全四候補の詳細表。
    """
    costs, roles, reasons = [], [], []
    for p in POLICIES:
        for t in PERIODS:
            o = result["候補"][p][t]["運用"]
            costs.append([p, t, o["完結数"], *(money(o["完結観測額円"][str(f)]) for f in (0, 5, 10)),
                          *(money(o["全体確定額円"][str(f)]) for f in (0, 5, 10)), o["未解消"], o["品質注意場"]])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][p][t][role], o["役割別完結"][role]
                roles.append([p, t, role, e["候補"], f'{e["250"]}/{e["約定"]}', rate(e["率"]), qualification(e["支持"]), actual["件数"], money(actual["観測純額5"])])
            if p in NEW:
                reasons.extend([p, t, why, n] for why, n in sorted(result["判断理由"][p][t].items()))
    return ("## 同約定の費用・品質\n\n品質注意時の期間全体確定はnull、観測額は別に残す。\n\n"
            + table(["候補", "期間", "完結", "観測0", "観測5", "観測10", "確定0", "確定5", "確定10", "未解消", "品質注意場"], costs)
            + "## DI役割別の入口と実完結\n\nDI同方向=順行、逆方向=反転という保存分類。転換の時系列確認や心理の直測ではない。役割別額も候補期間全体の品質に従う。\n\n"
            + table(["候補", "期間", "役割", "純採用", "250/仮約定", "主率", "入口支持", "実完結", "観測5円"], roles)
            + "## 新候補の保存判断理由\n\n最高障壁score側を先に選び、支持/技法/回収で不適格でも次点へ救済しない。純採否と実待ちは異なる。\n\n"
            + table(["候補", "期間", "保存理由", "枠数"], reasons)
            + "## 再利用した独立測定の状態\n\n新たな独立計測は0。未準備・未約定・品質注意・未解消を確定0円へ写さない。\n\n"
            + table(["用途区間", "状態", "方向行数"], [[x["区間"], x["状態"], x["方向行数"]] for x in result["独立測定"]]))

def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """版5全55×9、60特徴、内部リンクを検査する。

    引数: output(dict[str,str])は二つの本文、generated(set[Path])は同時生成又は人工仮想参照。
    返り値: intはリンク確認数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [r for r in text.splitlines() if r.startswith("| ") and r.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(r.split("|")) != 13 for r in rows):
        raise ValueError("版5の55×9が不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 61)):
        raise ValueError("60特徴の表示漏れ")
    return sum(R55.G.check_links(value, STUDY / name, generated) for name, value in output.items())

def render(check: bool = False) -> dict:
    """正式結果から2MDを一度生成するか同byteだけを検査する。

    引数: check(bool)は書込なしの一致検査。
    返り値: dictはSHA・リンク・表検査。fitや市場運用を呼ばない。
    """
    output = documents(context_for())
    count = validate_documents(output, {(STUDY / n).resolve() for n in output})
    reports = {}
    for name, text in output.items():
        path, content = STUDY / name, text.encode("utf-8")
        if check:
            if path.read_bytes() != content:
                raise ValueError("保存MDと同byteでない:" + name)
        else:
            path.write_bytes(content)
        reports[name] = {"SHA256": sha(path), "bytes": len(content)}
    return {"文書": reports, "内部リンク検査": count, "欠落": 0, "版": 5, "手法": 55, "尺度": 9,
            "表示中fit": 0, "再計測_再集計_市場再生": False, "同byte確認": check}

def validate_episode_support(support: dict, models: dict) -> None:
    """各学習phaseの全葉方向行を保存modelへ結ぶ。

    引数: support(dict)は主の経路支持、models(dict)は表示用の新3木。
    返り値: None。葉をまたぐ同episodeを独立標本としない。
    """
    if set(support) != {models[p]["base"]["model_id"] for p in PHASES}:
        raise ValueError("経路支持のphase差")
    for phase in PHASES:
        nodes = {str(n["id"]): n for n in models[phase]["base"]["nodes"] if n["left"] == -1}
        if set(support[models[phase]["base"]["model_id"]]) != set(nodes):
            raise ValueError("空葉を含む経路支持の全葉差")
        for identity, row in support[models[phase]["base"]["model_id"]].items():
            if row["方向行"] != nodes[identity]["direction_rows"]:
                raise ValueError("葉所属の方向行数差")
            for role in ("T", "R"):
                validate_episode_counts(row[role], row["方向行"])

def validate_state_distribution(distribution: dict, models: dict) -> None:
    """DIと対応episode現在有効四群の教師・段階・反復を照合する。

    引数: distribution(dict)は状態分布、models(dict)はphase別新三木。
    返り値: None。有効1へr/k形成を余分要求しない。
    """
    if set(distribution) != set(PHASES):
        raise ValueError("状態分布のphase差")
    for phase, groups in distribution.items():
        parts = models[phase]["base"]["training"]["partition"]
        if set(groups) != {f"D{d}_V{v}" for d in (0, 1) for v in (0, 1)}:
            raise ValueError("DIと対応現在有効の四群差")
        for key, group in groups.items():
            part = parts[key]
            d, v, n = part["d"], part["v"], group["方向行"]
            target = "R" if d == 0 else "T"
            if (group["方向枝"], group["対象経路"], group["episode有効"]) != ("DI非正" if d == 0 else "DI正", target, v):
                raise ValueError("方向枝・対象経路・現在有効旗差")
            if n != part["direction_rows"] or any(group[a] != part[b] for a, b in (("unique枠", "pair_unique"), ("日数", "days"), ("場数", "sessions"))):
                raise ValueError("状態分布と木の教師分母差")
            if not 0 <= group["日数"] <= group["場数"] <= group["unique枠"] <= n or sum(group["対象現在段階"].values()) != n:
                raise ValueError("状態群の枠・日・場・現在段階分母差")
            for role in ("T", "R"):
                row = group[role]
                keys = ("形成あり", "形成なし", "取消あり", "episode有効", "bあり", "fあり", "rあり", "kあり", "k有効", "形成ID数", "最大反復")
                if any(type(row[k]) is not int or row[k] < 0 for k in keys):
                    raise ValueError("価格状態件数は非負整数")
                formed = row["形成あり"]
                if (formed + row["形成なし"] != n or row["bあり"] != formed or row["取消あり"] + row["episode有効"] > formed
                        or not 0 <= row["k有効"] <= row["kあり"] <= row["rあり"] <= formed
                        or row["fあり"] > formed or row["形成ID数"] > formed or sum(row["段階"].values()) != n):
                    raise ValueError("現在有効・取消・b/f/r/k・最大段階の分母差")
                if role == target and row["episode有効"] != n * v:
                    raise ValueError("対応経路の現在有効と群旗差")
                if (formed == 0) != (row["形成ID数"] == 0) or (formed == 0) != (row["最大反復"] == 0):
                    raise ValueError("形成IDと反復の有無差")
                if formed and (row["最大反復"] > formed or row["最大反復"] * row["形成ID数"] < formed):
                    raise ValueError("同形成の最大反復範囲差")


def state_distribution_table(context: dict) -> str:
    """同教師四群の現在段階と両経路を、採用群と分けて表示する。

    引数: context(dict)は保存状態分布。
    返り値: strは全方向行・段階・形成反復表。
    """
    rows, stages = [], []
    for phase, groups in context["result"]["状態分布"].items():
        for name, group in groups.items():
            stages.extend([phase, name, stage, n] for stage, n in group["対象現在段階"].items())
            for role in ("T", "R"):
                state = group[role]
                rows.append([phase, name, group["方向枝"], group["対象経路"], group["episode有効"], role,
                    group["方向行"], group["unique枠"], group["日数"], group["場数"],
                    *(state[k] for k in ("形成あり", "形成なし", "取消あり", "episode有効", "bあり", "fあり", "rあり", "kあり", "k有効", "形成ID数", "最大反復")),
                    json.dumps(state["段階"], ensure_ascii=False, sort_keys=True)])
    return ("## 対応する現在有効四群の使用教師分布\n\n分母は各phaseの実使用方向行。木の固定群はfloat32 DI非正/正と対応R/Tの現在episode有効で、k形成ではない。"
        "V1はb登録から立ち、r/k未形成を含む。V0は未登録・取消・TTL・reset等を含み、反転成立や未発動だけを意味しない。"
        "対象外の経路も残す。最大段階と現在段階、現在有効、k有効を混同しない。これは純採用や実完結の分布ではない。"
        "unique形成IDと枠は群や葉で重複し非加算、最大反復も独立支持数ではない。\n\n"
        + table(["phase", "固定群", "方向枝", "対象経路", "対象episode有効", "記述経路", "方向行", "unique枠", "日", "場", "形成あり", "形成なし", "取消", "episode有効", "bあり", "fあり", "rあり", "kあり", "k有効", "unique ID", "最大反復", "最大段階別"], rows)
        + table(["phase", "固定群", "対象現在段階", "方向行"], stages))


def model_tables(context: dict, output: Path) -> str:
    """固定56の純表示から全新nodeを元60列indexと枝別58投影で表示する。

    引数: context(dict)は新3木、output(Path)は詳細MD。
    返り値: strは全閾値・支持・MSE・score・平均と子の方向/勢い選択。
    """
    text = R56.model_tables(context, output)
    text = text.replace("固定Z（F18<=0.5）→float32 DI（F01<=0/>0）の四区分、子は先頭17列だけの深さ2。",
        "float32 DI F01(index0)<=0→低側Rのepisode有効F26(index25)<=0.5/高側Tのepisode有効F20(index19)<=0.5の四群。子は各枝のDIと対応旗以外の58列・深さ2。")
    text = text.replace("priceとtrendの固定段で異種family資格が構造上充足する点は旧54/55と共通。",
        "trendとpriceの固定段で従来の複数技法gateが構造上充足する。旧64から固定段がtrend+priceへ変わるが、gateの式自体は緩和せず、根の二技法を独立した証拠とはしない。")
    text = text.replace("DI固定段の左はfloat32 F01<=0で同値・float32零化も含む。評価時の背景DI同値は最終WAITで、左枝を全て逆向きと呼ばない。",
        "DI固定段の左はfloat32 F01<=0で同値・float32零化も含む。評価時の背景DI同値は最終WAITで、左枝を全て反転進行中と呼ばない。対応V0も残し、最高score側の資格不足を次点で救済しない。")
    meta = {row["id"]: row for row in context["metadata"]}
    leaves = []
    for phase in PHASES:
        for node in context["models"][phase]["base"]["nodes"]:
            if node["left"] != -1:
                continue
            d = int(node["path"][0]["comparison"] == ">")
            selected = [meta[p["feature_id"]] for p in node["path"] if p["node"] >= 3 and meta[p["feature_id"]]["family"] in ("trend", "osc")]
            names = "/".join(dict.fromkeys(row["id"] + ":" + row["method"] + ":" + row["family"] for row in selected)) or "なし"
            leaves.append([phase, node["id"], "DI非正/R" if d == 0 else "DI正/T", node["direction_rows"], names, qualification(node["method_support"]), "/".join(node["families"]) or "なし"])
    return text + "## 子の方向・勢いと全葉の技法資格\n\n固定根のDIと対応episode有効はtrend+priceなので、子にtrend/oscがない葉でも従来技法gateは構造的に充足する。有効旗はr/k成立を要求しない。子の選択は透明化するが追加資格にはしない。空葉の未知score・回収平均を0補完せず、他の支持・回収条件は別途必要。\n\n" + table(["phase", "leaf", "方向枝/対応経路", "方向行", "子trend/osc特徴:手法:family", "技法資格", "全path family"], leaves)

def recovery_tables(context: dict, output: Path) -> str:
    """全回収葉の表示純補助だけを再利用する。

    引数: context(dict)は3回収集計、output(Path)は詳細MD。
    返り値: strは全葉と空平均null。新学習・walk・回収集計はしない。
    """
    return R56.recovery_tables(context, output).replace("G1は主合計strict>0", "U1は主合計strict>0")

def episode_support_table(context: dict) -> str:
    """全phase・全葉の反復を、学習方向行と別の列で表示する。

    引数: context(dict)は結果の経路支持と新model。
    返り値: strは全葉T/Rの診断表。支持gate・学習重みは変えない。
    """
    contents = []
    for phase in PHASES:
        for identity, row in sorted(context["result"]["経路支持"][context["models"][phase]["base"]["model_id"]].items(), key=lambda item: int(item[0])):
            for role in ("T", "R"):
                count = row[role]
                contents.append([phase, identity, role, row["方向行"], count["episode数"], count["episode最大反復"], count["episodeなし"],
                                 count["k形成episode数"], count["k有効episode数"], count["期限失効観測"]])
    return ("## 学習葉ごとのepisode反復\n\n全model.training.row_idsを現在の保存葉へ結んだ方向行が分母で、後続で採用された純入口の表ではない。"
            "同じIDが時点と特徴の変化で別葉へ到達し得るため、葉間のunique episodeは非加算。IDなしも分母へ残す。"
            "支持60枠や方向重み0.5をepisode単位へ変更せず、1回消費制限も加えていない。未保有なら同じ形成で再参加し得る。\n\n"
            + table(["phase", "leaf", "経路", "学習方向行", "unique episode", "最大反復", "IDなし", "k形成episode", "k有効episode", "期限失効観測"], contents))


# ----------------------------------------
# 全60列と同じ量分母を保ち、固定根の変更だけを明示する。


def settings(context: dict) -> list[dict]:
    """同60列と現在有効二段根を版5の設定セルへ対応させる。

    引数: context(dict)は全60metadataを持つ保存表示文脈。
    返り値: list[dict]は設定と複合評価ID。単独指標の効果へ分解しない。
    """
    rows = R64.settings(context)[:60]
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04", 説明="旧64Qと新65Uは同じ全60入力。新情報追加や追加欠測除外の比較ではない。")
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02", "旧64Q0/Q1保存対照", "同46場の旧92運用を再生しない。DI一段・子59列深さ3。"),
        (["M01", "P10"], ["m03", "m15", "m30"], "R03/R04", "DI→対応episode有効・子58列深さ2", "DI非正はRのF26、正はTのF20を0.5で固定。二固定段trend+priceにより技法資格が構造的に充足する。容量配分も変わるため複合構造差とする。"),
        (["M01"], ["tick", "m03", "m15", "m30"], "R03/R04", "U0:最高障壁score側と回収支持60枠6日10場", "score>=1/3、葉支持・複数技法・回収支持。回帰平均で順位を変えず次点救済なし。"),
        (["M01"], ["tick", "m03", "m15", "m30"], "R04", "U1:同U0木＋主回収strict正", "Decimal sum5>0、空回収nullを0へ補完しない。新U1木の別fitはない。"),
        (["V01", "P05"], ["m03"], "R01/R02/R03/R04", "旧64同時刻量とb/r一足価格進行を保持", "同種・同限月の直近10完了場、同index完全q5以上・平均正。現在ATRで価格差を尺度化。量のみの方向判定ではない。"),
        (["B01", "E02"], ["tick"], "R03/R04", "旧55一枠回収再用・新計測0", "重複建玉の合算は同時実行strategy利益でない。教師・回収終了は評価開始より前。"),
        (["E02", "C06", "E01"], ["tick"], "R01/R02/R03/R04", "固定49O・現在益122円strict正・固定250TPなし", "新規D5..125固定、損失側も連続追尾、名目床・非緩和・返済pending保護凍結。先着と実回収を分ける。"),
        (["C07"], ["m15"], "R01/R02/R03/R04", "25/49全予定枠・保守待ち50%以下", "保有非待ち、判定不能込み。過去の形成価格へ約定を戻さない。")]
    for methods, scales, evaluations, short, description in extras:
        rows.append({"設定ID": f"S{len(rows) + 1:02d}", "手法ID": methods, "尺度ID": scales,
            "短記": short, "結果短記": evaluations, "説明": description})
    return rows


def feature_table(context: dict) -> str:
    """旧64と同じ全60特徴を省略せず、現在有効の使い方を説明する。

    引数: context(dict)は新三木と全metadata。
    返り値: strは60式・手法・尺度・固定/子の役割。
    """
    rows = [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i]] for i, m in enumerate(context["metadata"])]
    return ("## 全60特徴・追加情報なし\n\n旧64Q0/Q1と新U0/U1は同じ全60列、同じready、同じ教師pairを受け取る。"
        "F01がfloat32で非正ならRのepisode有効F26(index25)、正ならTのepisode有効F20(index19)を先に分ける。"
        "非正子はindex0/25、正子はindex0/19だけを除く58列・深さ2。F18、対応k有効、他方の経路状態、量・価格列も子へ残る。\n\n"
        + table(["ID", "特徴", "手法", "family", "尺度", "式・範囲"], rows)
        + "V1はbからtrueで、r/k未形成も含む。V0は未登録・取消・TTL・reset等の混合で、反転成立や値0の相場という意味ではない。"
        "価格T/Rは仮説の名前、実運用の順行/反転は現在raw DIとの関係で別に付く。float32零化やDI同値を左枝に含むが最終DI同値WAITは保持する。\n\n"
        "F55/F57は過去同時刻量、F56/F58は当該b/rと直前隣接公開足の一足価格差/現在ATR。b→r区間の差ではない。"
        "共同mask0は対応2数値を両0にし、完全q0の既知値と分ける。基準は直近10同種・同限月完了場の同index、完全q5以上・平均正。祝日層化なし。"
        "数量の段階なし、基準不足、現在有効の欠如を混同せず、追加準備で旧readyを落とさない。\n\n"
        "保持Kはbで固定し、初期局所F18の移動帯とは別。k形成後は取消後もTTL又は置換まで既知現在の統計を更新し、有効旗を復活させない。"
        "登録へ至る十差分はb−10..bの11終値で、推進波全体ではない。r前pはr時点で固定、rなしの区間値0とr当足0を区別する。"
        "終値の記述をBBO約定位置・将来残存値幅・心理の直接測定と呼ばない。\n\n")


def documents(context: dict) -> dict[str, str]:
    """保存済みの数値だけで概要と全設定を組み立てる。

    引数: context(dict)は正式又は人工の表示文脈。
    返り値: dict[str,str]は二本文。fit・予測・市場再生は呼ばない。
    """
    r, proof = context["result"], context["proof"]
    brief_path, detail_path = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operation = main_tables(r)
    status = "新候補の採用なし。両期の先着70・支持・費用・活動の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見の利益保証ではない。"
    intro = ("全66場は既使用。初20場は学習専用、学習欄は後20場の時系列検査。選択24場・既使用後続2場ではF40固定で再fitしない。\n\n"
        + status + "\n\n旧64Q0/Q1は保存対照。全60入力・教師・回収支持・score最高側・O49は同じ。"
        "旧DI一段の子59列/深さ3から、DI→対応する現在episode有効の二段・子58列/深さ2へ変える。全深さ4は同じでも学習容量の配分が変わる。"
        "固定trend+priceで従来の複数技法資格が構造的に充足し、旧64DI一段とは制約の強さが異なる。新情報追加や独立票の増加ではなく、複合構造の比較である。\n\n"
        "根はfloat32 F01<=0。低側はRのF26(index25)、高側はTのF20(index19)を各0.5で固定し、D0_V0/D0_V1/D1_V0/D1_V1へ分ける。"
        "V1はb出生から、V0は未登録・取消・TTL・reset等を含む。r/k成立の名前を四群へ付けない。"
        "最終raw DI同値WAITは保持し、左枝の同値/float32零化を全て反転進行中とは呼ばない。\n\n"
        + f'新回帰器{r["新回帰器fit"]}fit（新三木・最大12）、分類器fit0・新独立計測0・新92運用。'
        "子の目的はpnl5のMSE、順位は障壁score最高側のまま。U0はscore>=1/3・葉/技法/回収60枠6日10場、U1は同木に主回収Decimal合計strict正も要求する。次点救済なし。\n\n")
    mechanics = ("## 判断・執行と価格機械の限定\n\nTはb→r→k、Rはb→f→r→k。別足・公開key順を確認し、未完了・取消・失効も残す。"
        "寿命はb.confirm+3600で同秒を含め失効、60分を定時4枠と同一視しない。有効中置換なし、取消足や最初の期限越え足を新bへ再使用しない。"
        "足の公開順は高安の足内形成順を保証せず、将来の極値を過去の水準へ遡及しない。\n\n"
        "デイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。保有継続は非待ち、全予定枠分母で待ち＋判定不能の保守上限50%以下。"
        "現在正常BBOから1価格時計秒後の最初の正常気配へ要求し、新規TTL30秒、過去b/r/k価格へ約定を戻さない。残り60分停止なし。強制15:35/05:50、終了15:40/05:55。\n\n"
        "固定49O、micro1枚10円/pt、片道11円＋想定片道5ptで往復122円。現ATRの5pt切上げをD5..125へ制限し新規時固定。"
        "損失側も連続追尾し、現在返済気配の粗益−122円strict正で利益旗・最低名目新規床、非緩和、返済pendingのh/L/arm保護凍結。"
        "固定250TPなし。費用0/10pt感応は同約定・起動122円不変。名目床は費用後同値保証ではない。\n\n"
        "仮125/250先着、回帰円予測、過去平均、実回収を別にする。旧55一枠回収の重複建玉合計は同時実行strategy利益でない。"
        "品質注意時は期間全体確定nullを保ち、観測・役割別額を無条件確定としない。ラージBBO代理でmicro実板や受信時計を測定していない。\n\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, brief_path) for n in (
        "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(HERE / "README.md", brief_path, "コードと再現") + "\n\n"
        "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧Q0/Q1各46＋新U0/U1各46＝184資源。\n\n"
        + link(OLD / "設定と結果.md", brief_path, "旧64全閾値と量の定義") + " / " + link(EXTERNAL, brief_path, "初動・現在の前提・再点火")
        + f'\n\n保存監査：{number(proof["照合項目数"])}照合・差{number(proof["不一致数"])}。Viewerの範囲は監査JSONを正本とする。\n\n'
        "再表示はfit・予測walk・独立計測・市場運用を再実行しない。\n\n~~~powershell\n"
        "C:/Python314/python.exe -X utf8 scripts/現在状態と量価格/レポート.py\n"
        "C:/Python314/python.exe -X utf8 scripts/現在状態と量価格/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail_path, uses).replace("未使用", "未使用・未検証")
    settings_table = table(["設定ID", "手法/尺度", "設定内容", "限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    sources = table(["出典", "SHA256"], [[link(p, detail_path), sha(p)] for p in context["sources"]])
    external = ("## 実務一次資料と独自規約\n\n確認日2026-11-06。"
        "[Brooks公式Q&A文字起こし](https://www.brookstradingcourse.com/ask-al/breakouts/)（2016-09-25）では初動の強さと、押戻しが直近の強い進行の根元を守る現在の前提を分ける。"
        "[GrimesのTWTR Anti適用](https://www.adamhgrimes.com/chart-of-the-day-anti-in-twtr/)（2014-01-06）は短期逆行のsetupと、元方向へ実際に動く参加時計を分け、逆行継続なら入らない。"
        "既存の失敗後確認と重複し、新手法発見やRaschke原著の全規則を確認した主張ではない。\n\n"
        "今回のepisode有効旗は、独自の登録・取消・TTL/resetの状態で、原典の前提有効そのものではない。"
        "心理は推論、全件費用後・未見・NK先着70の実証ではない。元仮説否定だけで反対側が成立するとはせず、Brooksの裁量退出・買増し・広いstopを固定O49へ移植しない。"
        + link(EXTERNAL, detail_path, "読取範囲・既読との重複・反証") + "を参照する。\n\n")
    brief = "# 00065：方向に対応する現在の有効状態を先に分ける\n\n" + intro + "## 入口先着\n\n" + entrance + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    detail = ("# 00065：設定と結果\n\n" + intro + "R01=旧Q0、R02=旧Q1、R03=U0、R04=U1。\n\n"
        "## 手法×尺度・版5全文\n\n55手法×9尺度を全件保持。未使用・未検証とデータ不足・対象外を分ける。複合成績を指標単独へ帰属しない。\n\n"
        + matrix + feature_table(context) + "## 設定明細\n\n" + settings_table + coverage_table(r) + quantity_table(r)
        + model_tables(context, detail_path) + recovery_tables(context, detail_path) + state_distribution_table(context)
        + episode_support_table(context)
        + "以下のADX/BB局面分布は旧63から共有する準備診断で、65の追加列ではない。\n\n" + regime_distribution_table(r)
        + "## 全候補の入口先着\n\n" + entrance + "## 全候補の混合運用\n\n" + operation + detail_tables(r) + mechanics + external
        + "## 検査と版\n\n旧教師一致：" + json.dumps(r["旧教師一致"], ensure_ascii=False)
        + "。教師集合一致：" + json.dumps(r["教師集合一致"], ensure_ascii=False)
        + "。保存検査：" + json.dumps(r["検査"], ensure_ascii=False)
        + "。独立測定参照：" + json.dumps(r["独立測定参照"], ensure_ascii=False)
        + "。base60_fingerprints六キーと全60canonicalを旧64Q同phase正本へ照合し、base18/30/38/46/54も保持する。"
        "列追加・追加欠測除外・教師変更はない。四群は今回の木の固定群で、旧64のDI×k診断群とは異なる。\n\n"
        + "## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief_path, detail_path, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detail}


def self_test() -> dict:
    """別ファイルの人工表示検査を呼び、正式人工記録用の件数を返す。

    引数: なし。
    返り値: dictは成功とテスト件数。失敗時終了1、実データは開かない。
    """
    spec = importlib.util.spec_from_file_location("現在状態65表示の人工", HERE / "レポートの人工検査.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run(sys.modules[__name__])


def main() -> None:
    """正式表示と人工表示検査の排他的CLIを選ぶ。

    引数: なし。--checkは書込なし、--self-testは人工のみ。
    返り値: None。正式表示は主・監査成功後の通知でのみ行う。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_test() if args.self_test else render(args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
