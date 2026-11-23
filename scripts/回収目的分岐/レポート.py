"""56の保存結果・回帰木・回収集計を再学習せず二つのMarkdownへ表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal, localcontext
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00056_追尾回収を目的に技法を分岐"
OLD = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
OLD_WORK = ROOT / "work/独立追尾回収/00055"
SHARED = ROOT / "scripts/独立追尾回収/レポート.py"
SPEC = importlib.util.spec_from_file_location("回収目的分岐の固定55表示純補助", SHARED)
R55 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R55
SPEC.loader.exec_module(R55)
V5 = R55.V5
POLICIES = ("C0", "R0", "G0", "G1")
NEW = ("G0", "G1")
PERIODS = R55.PERIODS
PERIOD_NAMES = R55.PERIOD_NAMES
PHASES = R55.PHASES
EVALUATIONS = {p: f"R{i + 1:02d}" for i, p in enumerate(POLICIES)}
sha, read, fingerprint, table = R55.sha, R55.read, R55.fingerprint, R55.table
number, rate, qualification, link, money = R55.number, R55.rate, R55.qualification, R55.link, R55.money


def validate_result(result: dict) -> None:
    """新旧候補・固定期間・分母・nullとfitの用途を検査する。

    引数: result(dict)は56の保存結果。市場や教師の系列は開かない。
    返り値: None。不一致は例外にする。
    """
    if result.get("試行") != 56 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("56の候補又は既使用契約が不正")
    if type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 12 or (result["新分類器fit"], result["新独立計測"], result["新運用数"]) != (0, 0, 92):
        raise ValueError("回帰最大12・分類0・新独立計測0・新運用92の契約差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・評価46場の区分差")
    if result["対照参照"] != {"候補": ["C0", "R0"], "元試行": 55, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("対照は固定55C0/R0保存値だけ")
    if result["独立測定参照"]["元試行"] != 55 or result["独立測定参照"]["再計測"] is not False:
        raise ValueError("独立測定は固定55参照だけ")
    if sum(r["方向行数"] for r in result["独立測定"]) != 4884:
        raise ValueError("既存2442枠両方向4884記録の差")
    keys = {"input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256"}
    if set(result["旧教師一致"]) != set(PHASES) or any(set(x) != keys or any(v is not True for v in x.values()) for x in result["旧教師一致"].values()):
        raise ValueError("旧教師4指紋一致が必要")
    if result["教師集合一致"] != {p: True for p in PHASES}:
        raise ValueError("旧D0・新回帰・55回収の教師集合一致が必要")
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
    for p in ("C0", "R0"):
        if result["候補"][p] != old["候補"][p] or result["役割別入口"][p] != old["役割別入口"][p]:
            raise ValueError("固定55の対照集計差")
    for k in ("評価場", "学習専用場", "準備比較", "独立測定"):
        if result[k] != old[k]:
            raise ValueError("固定55の期間・準備・測定参照差:" + k)
    if result["対照モデル"] != old["モデル"]:
        raise ValueError("固定55の対照モデル差")
    measured = result["独立測定参照"]
    measured_path = (ROOT / measured["path"]).resolve()
    if not measured_path.is_relative_to(OLD_WORK) or measured["sha256"] != old["詳細"].get(measured_path.name):
        raise ValueError("固定55独立測定参照のパス又はSHA差")
    calibrations = {x["phase"]: x for x in result["回収集計"]}
    models, paths, metadata = {}, [], None
    for entry in result["モデル"]:
        phase = entry["phase"]
        if phase not in PHASES or phase in models or entry["id"] != "G0_" + phase:
            raise ValueError("新3モデルのID・phase差")
        path = (ROOT / entry["path"]).resolve()
        cal_entry = calibrations[phase]
        cal_path = (ROOT / cal_entry["path"]).resolve()
        if any(not p.is_relative_to(STUDY) for p in (path, cal_path)) or sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("新モデル・回収集計の版差")
        model, cal = read(path), read(cal_path)
        validate_model(model)
        R55.validate_calibration(cal, model)
        if cal["base_model_path"] != entry["path"] or cal["base_model_sha256"] != entry["SHA256"] or cal["phase"] != phase:
            raise ValueError("新回帰木と回収集計の出典差")
        if metadata is None:
            metadata = model["feature_meta"]
        if model["feature_meta"] != metadata or len(metadata) != 18:
            raise ValueError("共通18特徴の順序差")
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
    resources = read(STUDY / "一覧.resources.json")["resources"]
    if len(resources) != 184 or Counter(x["method_id"] for x in resources) != {p: 46 for p in POLICIES}:
        raise ValueError("旧92+新92の184Viewer資源差")
    if any(not (ROOT / x["pnl_path"]).is_file() for x in resources):
        raise ValueError("Viewer約定参照欠落")
    sources = [*required, *paths, Path(__file__), HERE / "README.md", HERE / "検証.py", HERE / "学習.py", HERE / "保存物確認.py",
               SHARED, R55.SHARED, ROOT / "scripts/レポート/カタログ版5.py", ROOT / "scripts/レポート/設定結果レポート.py",
               V5.CATALOG, V5.MASTER, OLD / "結果.json", OLD / "設定と結果.md", OLD / "保存物確認.json",
               ROOT / "scripts/局所帯分岐/特徴仕様.md", ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md",
               ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md"]
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
    if model["policy"] != "G0" or len(model["feature_meta"]) != 18 or len({n["id"] for n in model["nodes"]}) != len(model["nodes"]):
        raise ValueError("18特徴又はnode一意性の差")
    structure = model["structure"]
    if (structure["kind"], structure["child_depth"], structure["child_features"], structure["max_depth"], structure["fixed_mse_optimized"], structure["child_estimator"], structure["target"]) != ("fixed_root_and_direction", 2, 17, 4, False, "DecisionTreeRegressor", "pnl5"):
        raise ValueError("固定二段・子回帰目的の差")
    for parameters, depth in ((model["parameters"], 4), (model["subtree_parameters"], 2)):
        if (parameters["criterion"], parameters["max_depth"], parameters["min_samples_leaf"], parameters["random_state"]) != ("squared_error", depth, 60, 51) or "class_weight" in parameters:
            raise ValueError("回帰の固定設定差")
    ids = {n["id"] for n in model["nodes"]}
    for n in model["nodes"]:
        if n["left"] != -1 and (n["left"] not in ids or n["right"] not in ids or not 0 <= n["feature"] < 18 or not math.isfinite(n["threshold"])):
            raise ValueError("分岐参照又は閾値が不正")
        if n["impurity_kind"] != "squared_error" or n["total_weight"] != n["direction_rows"] * .5:
            raise ValueError("node目的又は方向重み差")
        count = n["direction_rows"]
        if (n["score"] is None) != (count == 0) or count and n["score"] != n["success_weight"] / n["total_weight"]:
            raise ValueError("障壁scoreは回帰予測とは別の先着割合が必要")
        if n["data_absent"] != (count == 0):
            raise ValueError("空node表示差")
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


def settings(context: dict) -> list[dict]:
    """18技法特徴と回収目的の区分・支持・実行を版5へ対応させる。

    引数: context(dict)はmetadataを含む表示文脈。
    返り値: list[dict]は使用セルの設定。未使用は未検証のまま。
    """
    result = [{"設定ID": f"S{i + 1:02d}", "手法ID": [m["method"]], "尺度ID": m["scale"].split("+"),
               "短記": m["id"] + "=" + R55.G.FORMULAS[i] + "・54/55不変", "結果短記": "R01/R02/R03/R04",
               "説明": "全18入力。新回帰木の探索は先頭17列、F18は固定価格段。指標単独の効果ではない。"}
              for i, m in enumerate(context["metadata"])]
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02", "旧55C0/R0保存対照", "再fit・再計測・再運用なし。同46場を保存参照。"),
              (["M01"], ["m03", "m15", "m30"], "R03/R04", "Z→DI固定・17列回帰d2/MSE", "全深さ4/minleaf60/方向重み0.5/seed51。主費用後回収pnl5の二乗誤差で区分し、障壁ラベルは分割目的にしない。"),
              (["M01"], ["tick", "m03", "m15", "m30"], "R03/R04", "G0:障壁score最高側＋回収支持60枠6日10場", "score>=1/3・葉支持・複数familyも必要。回帰予測が高い側へ順位を変えず、不適格側から次点へ救済しない。"),
              (["M01"], ["tick", "m03", "m15", "m30"], "R04", "G1:G0＋主回収平均strict正", "過去十進sum5>0。正平均を将来利益の確率や保証としない。"),
              (["B01", "E02"], ["tick"], "R03/R04", "旧55独立測定4884記録共有・新測定0", "ready両側確定pairと旧D0教師の同集合。未知を0補完せず、独立合算は同時実行strategy利益ではない。"),
              (["E02", "C06"], ["tick"], "R01/R02/R03/R04", "固定49O・現在益122円strict", "連続追尾・名目床・非緩和・pending保護凍結。新規ATRのD5..125固定。"),
              (["E01"], ["tick"], "R01/R02/R03/R04", "仮125/250先着・固定TPなし", "先着率・過去平均回収・実戦略損益を分離。"),
              (["C07"], ["m15"], "R01/R02/R03/R04", "公開時点・3分/15分鮮度", "判断15分、m30は3分10本ORの集計。未来回収を評価入力へ渡さない。")]
    for methods, scales, evaluations, short, detail in extras:
        result.append({"設定ID": f"S{len(result) + 1:02d}", "手法ID": methods, "尺度ID": scales,
                       "短記": short, "結果短記": evaluations, "説明": detail})
    return result


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


def model_tables(context: dict, output: Path) -> str:
    """新3回帰木の全閾値・node目的値・葉の得点と支持を表示する。

    引数: context(dict)は保存model、output(Path)は詳細MD。
    返り値: strは全nodeと全葉の表。回帰平均と障壁scoreを別列にする。
    """
    models, partitions, nodes, objectives = [], [], [], []
    for phase in PHASES:
        item, model = context["models"][phase], context["models"][phase]["base"]
        models.append([phase, link(item["base_path"], output, model["model_id"]), len(model["nodes"]),
                       len(item["entry"]["学習場"]), len(item["entry"]["評価場"]), "squared_error", "pnl5円"])
        for key, group in sorted(model["training"]["partition"].items()):
            partitions.append([phase, key, group["direction_rows"], group["pair_unique"], group["days"], group["sessions"],
                               group["root"], group["node_count"], "実施" if group["fit_performed"] else "未実施・未知枝"])
        for n in sorted(model["nodes"], key=lambda x: x["id"]):
            terminal = n["left"] == n["right"] == -1
            split = "葉" if terminal else context["metadata"][n["feature"]]["id"] + " <= " + format(n["threshold"], ".17g")
            path = " ∧ ".join(p["feature_id"] + " " + p["comparison"] + " " + format(p["threshold"], ".17g") for p in n["path"]) or "根"
            nodes.append([phase, n["id"], len(n["path"]), split + ("（固定）" if n["id"] < 3 else ""),
                          f'{n["left"]}/{n["right"]}', path, n["direction_rows"], n["total_weight"],
                          f'{n["unique_slots"]}/{n["days"]}/{n["sessions"]}',
                          full_number(n["score"]), full_number(n["barrier_gini"]),
                          qualification(n["leaf_support"]), "/".join(n["families"]), qualification(n["method_support"])])
            objectives.append([phase, n["id"], full_number(n["regression_value"]),
                               n["recovery"]["pnl5"]["mean_decimal"] if n["direction_rows"] else "null（未知）",
                               n["recovery"]["pnl5"]["sum"], "null（未知）" if n["recovery_positive"] is None else qualification(n["recovery_positive"]),
                               full_number(n["impurity"]), n["recovery_mse_decimal"] if n["direction_rows"] else "null（未知）"])
    return ("## 新回帰木3つの全分岐\n\n固定Z（F18<=0.5）→float32 DI（F01<=0/>0）の四区分、子は先頭17列だけの深さ2。"
            "固定段はMSE最適分割ではない。全深さ4、最小方向行60、方向重み0.5、seed51。"
            "子の探索目的は費用後pnl5のsquared_error、障壁ラベルは分割目的にしない。"
            "回帰fitは最大12（3phase×4子）、空子はfitしない。新分類器fit0。分割後の障壁scoreは葉内先着ラベルの平均で、回帰の円予測とは別である。\n\n"
            + table(["phase", "モデル", "node数", "過去場", "評価場", "子の目的", "教師単位"], models)
            + table(["phase", "固定区分", "方向行", "unique枠", "日", "場", "子root", "子node数", "回帰fit"], partitions)
            + "全nodeを載せ、閾値は保存floatの17桁。MSEは円の二乗で、固定段も使用教師のばらつきを記録する。"
            "未知葉のscore/平均はnullで、0成功・0円ではない。priceとtrendの固定段で異種family資格が構造上充足する点は旧54/55と共通。\n\n"
            "DI固定段の左はfloat32 F01<=0で同値・float32零化も含む。評価時の背景DI同値は最終WAITで、左枝を全て逆向きと呼ばない。\n\n"
            + table(["phase", "node", "深さ", "分岐（左<=/右>）", "左/右", "全path", "方向行", "重み和",
                     "unique/日/場", "障壁score", "障壁gini参考", "葉支持", "path family", "技法資格"], nodes)
            + "生回帰予測と生MSEは学習器のfloat値、Decimal欄は80桁算術の表示値。平均はabs1e-10/rel1e-12、"
            "MSEはabs1e-8＋1e-10×max(1,E[pnl5²])だけを監査で許容し、閾値・先着score・支持・正額符号・採否へ転用しない。"
            "空nodeの回帰正額は未知null、後段の校正positive=Falseは不適格という意味で別に記す。\n\n"
            + table(["phase", "node", "生回帰予測5円", "Decimal平均5円", "合計5円", "主合計strict正", "生MSE円²", "Decimal MSE円²"], objectives))


def full_number(value: float | None) -> str:
    """生floatを丸めた円表示と分け、17桁で表示する。

    引数: value(float|None)は保存数値。
    返り値: strは数値又は明示的な未知null。
    """
    return "null（未知）" if value is None else format(value, ".17g")


def recovery_tables(context: dict, output: Path) -> str:
    """新木へ結合した過去回収の全葉を空葉込みで表示する。

    引数: context(dict)は3回収集計、output(Path)は詳細MD。
    返り値: strはpair除外と全葉の回収支持・平均表。
    """
    phases, leaves, excluded = [], [], []
    for phase in PHASES:
        item = context["models"][phase]
        cal, entry = item["calibration"], item["entry"]
        phases.append([phase, link(item["path"], output, "回収集計"), len(entry["学習場"]), len(entry["評価場"]),
                       cal["old_teacher_direction_rows"], cal["input_pairs"], cal["used_pairs"], len(cal["excluded_pairs"]), cal["used_direction_rows"], cal["evaluation_start"]])
        for states, count in sorted(Counter(json.dumps(x["states"], ensure_ascii=False, sort_keys=True) for x in cal["excluded_pairs"]).items()):
            excluded.append([phase, states, count])
        for key, leaf in sorted(cal["leaves"].items(), key=lambda x: int(x[0])):
            leaves.append([phase, key, leaf["direction_rows"], leaf["unique_slots"], f'{leaf["days"]}日/{leaf["sessions"]}場',
                           "/".join(leaf["sum_yen"][f] for f in ("0", "5", "10")),
                           "/".join(money(leaf["mean_yen"][f], "null（空葉）") for f in ("0", "5", "10")),
                           qualification(leaf["support"]), qualification(leaf["positive"]), "null" if leaf["max_teacher_end"] is None else leaf["max_teacher_end"]])
    return ("## 全phaseの回収支持と全葉\n\n旧55測定を再利用し、新独立測定0。旧D0使用教師ID・新木使用ID・旧55校正IDの同集合を確認する。"
            "片側の回収が不明ならpair全体を除外し、障壁/回収の終了は評価開始よりstrict過去。"
            "各方向重み0.5は共通、平均は十進純額合計/方向行数。G1は主合計strict>0、表示丸めを採否へ使わない。\n\n"
            + table(["phase", "保存集計", "過去場", "評価場", "旧方向教師", "入力pair", "使用pair", "除外pair", "使用方向行", "評価開始秒"], phases)
            + "独立測定の同時に持てない重複建玉を含む合計であり、実行可能な一戦略の利益ではない。\n\n"
            + table(["phase", "leaf", "方向行", "unique枠", "日/場", "合計円0/5/10", "平均円0/5/10", "回収支持", "主合計>0", "最大教師終了秒"], leaves)
            + table(["phase", "除外pairの状態", "pair数"], excluded))


def detail_tables(result: dict) -> str:
    """費用感応・品質・DI役割・保存理由を表示する。

    引数: result(dict)は56結果。
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


def documents(context: dict) -> dict[str, str]:
    """保存文脈だけから概要と詳細を生成する純関数。

    引数: context(dict)は正式又は人工文脈。
    返り値: dict[str,str]は二つのUTF-8 Markdown本文。書込や再計算は行わない。
    """
    result, proof = context["result"], context["proof"]
    readme, detail = STUDY / "README.md", STUDY / "設定と結果.md"
    entry, operation = main_tables(result)
    status = "新候補の採用なし。先着70・支持・費用・活動の両期同時目標は未達。" if not result["採用"] else "保存された採用候補：" + "、".join(result["採用"]) + "。既使用外の利益保証ではない。"
    intro = ("全66場は既使用。初20場は学習専用、学習欄は後20場の時系列検査、条件選択24/後続2場はF40を固定し再fitしない。\n\n"
             + status + "\n\n旧55C0/R0は保存対照。新G0/G1は同じ18特徴・同じ使用教師集合で、Z→DIの固定四区分の子を費用後pnl5の回帰へ変更した。"
             + "新回帰器" + str(result["新回帰器fit"]) + "fit（最大12、空子は未実施）、新分類器fit0、新独立計測0、新混合運用92。回帰目的で区分しても、順位は葉の障壁score最高側を維持し、回帰予測の高い側へ変更しない。"
             "G0はscore>=1/3・葉/異種技法支持・回収60unique枠6日10場、G1はさらに主回収平均strict正。次点救済なし。\n\n")
    mechanics = ("## 判断・執行と限界\n\n15分定時はデイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。全予定枠を分母に保有継続は非待ち、"
                 "判定不能を含む待ち保守上限50%以下を要求する。新規残り60分制約なし。正常BBOの後行1価格時計秒、新規TTL30秒、強制15:35/05:50、終了15:40/05:55。\n\n"
                 "固定49Oを変更せず、利益前も損失側を連続追尾する。現ATRの5pt切上げを5..125に制限したDを新規時固定。"
                 "現在正常返済BBOの粗含み益−122円がstrict正なら利益旗・最低名目新規床・非緩和、返済pending中は保護を凍結する。"
                 "micro1枚10円/pt、片道11円＋想定片道5pt。0/10ptは同約定への費用感応、起動122円不変。固定250TPなし、名目同値床は費用後同値の保証ではない。\n\n"
                 "仮125/250先着率、回帰の円予測、過去葉平均、混合一建玉の実損益は別。二乗誤差は平均回収を狙う区分で、分布の尾部や将来利益を保証しない。"
                 "独立測定は重複する一枠両側取引で、合計は同時実行戦略利益ではない。評価時の将来回収を特徴へ渡さない。"
                 "量・注文フロー・新価格発動は追加せず、心理も直測していない。同じ価格由来の多特徴を独立した証拠票としない。"
                 "ラージBBO代理でありmicro実板や受信時計を測った利益ではない。\n\n")
    commands = ("~~~powershell\nC:/Python314/python.exe -X utf8 scripts/回収目的分岐/レポート.py\n"
                "C:/Python314/python.exe -X utf8 scripts/回収目的分岐/レポート.py --check\n~~~\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, readme) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
             + " / " + link(HERE / "README.md", readme, "コードと再現") + "\n\n"
             + "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧C0/R0各46＋新G0/G1各46＝184資源。独立教師合算の資産曲線は作らない。\n\n"
             + link(OLD / "設定と結果.md", readme, "旧55の支持・平均と全葉") + " / "
             + link(ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md", readme, "先着と退出の順序")
             + " / " + link(ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md", readme, "外部調査と研究仮説")
             + "\n\n保存監査：" + number(proof["照合項目数"]) + "照合・不一致" + number(proof["不一致数"]) + "。Viewerの実行確認範囲は監査JSON参照。"
             "再表示だけを行い、fit・独立計測・回収集計・市場運用を再実行しない。\n\n" + commands)
    brief = "# 00056：追尾回収を目的に技法を分岐\n\n" + intro + "## 入口先着\n\n" + entry + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    entries = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail, entries).replace("未使用", "未使用・未検証")
    extra = table(["設定ID", "手法/尺度", "設定内容", "解釈と限定"], [[r["設定ID"], "/".join(r["手法ID"]) + "・" + "/".join(r["尺度ID"]), r["短記"], r["説明"]] for r in entries])
    provenance = table(["出典", "SHA256"], [[link(p, detail), sha(p)] for p in context["sources"]])
    detailed = ("# 00056：設定と結果\n\n" + intro + "R01=C0、R02=R0、R03=G0、R04=G1。旧55対照を再運用せず、新区分の効果を指標単独効果とはしない。\n\n"
                + "## 手法×尺度・版5全文\n\n55手法×9尺度＝495セル。全18特徴を保持し、未分岐も含めて入力を省略しない。未使用・未検証はデータ不足や対象外と別。\n\n"
                + matrix + R55.feature_table(context) + "## 設定明細\n\n" + extra + model_tables(context, detail)
                + recovery_tables(context, detail) + "## 全候補の入口先着\n\n" + entry + "## 全候補の混合運用\n\n" + operation
                + detail_tables(result) + mechanics + "## 検査と版\n\n旧教師4指紋：" + json.dumps(result["旧教師一致"], ensure_ascii=False)
                + "。教師集合同値：" + json.dumps(result["教師集合一致"], ensure_ascii=False) + "。保存検査：" + json.dumps(result["検査"], ensure_ascii=False)
                + "。旧測定参照：" + json.dumps(result["独立測定参照"], ensure_ascii=False) + "。"
                "表示器は旧測定gzipを開かず、参照SHAを55の小型結果へ照合する。内容の検算は新旧保存監査の成功証明へ接続する。\n\n"
                + "## 外部資料の限定\n\n期待平均と有限回の分布を分ける数学的着想は既存調査と重複し、新しいNK成績の発見ではない。"
                "Grimes本人の[2013年模擬例](https://www.adamhgrimes.com/the-slings-and-arrow-of-outrageous-fortune/)は平均が正でも有限経路がばらつく説明、"
                "[2018年短期ボラ商品解説](https://adamhgrimes.com/lessons-on-risk-short-volatility/)は頻繁な小益と稀な大損の機序である。"
                "確認日2026-11-06、本人記事本文を閲覧。両者はNK分足・固定費用・本Oの統計検定ではなく、後者のETN構造をNKへ移植しない。\n\n"
                + "## 保存出典\n\n" + provenance + "## 再表示\n\n" + link(readme, detail, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detailed}


def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """版5全55×9、18特徴、内部リンクを検査する。

    引数: output(dict[str,str])は二つの本文、generated(set[Path])は同時生成又は人工仮想参照。
    返り値: intはリンク確認数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [r for r in text.splitlines() if r.startswith("| ") and r.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(r.split("|")) != 13 for r in rows):
        raise ValueError("版5の55×9が不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 19)):
        raise ValueError("18特徴の表示漏れ")
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


def main() -> None:
    """正式表示と人工schema検査をCLIで選ぶ。

    引数: なし。--checkと--self-testは排他的。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
        if not result.wasSuccessful():
            raise SystemExit(1)
    else:
        print(json.dumps(render(args.check), ensure_ascii=False))


# ----------------------------------------
# 人工schemaだけで表示・null・表・リンクを検査する。正式結果や教師は読まない。


class RenderTests(unittest.TestCase):
    """正式結果を開かない表示検査。"""

    def test_metadata_matrix(self) -> None:
        """全18列と55×9の未使用表記を検査する。

        引数: なし。
        返り値: None。
        """
        context = artificial_context()
        text = V5.matrix(V5.load_catalog(), STUDY / "設定と結果.md", settings(context))
        self.assertEqual(R55.feature_table(context).count("| F"), 18)
        self.assertIn("未使用", text)
        self.assertIn("G1:G0＋主回収平均strict正", text)

    def test_documents(self) -> None:
        """人工2MDのnull・全node・同byteと非改変を検査する。

        引数: なし。
        返り値: None。ファイル生成や実教師読取はしない。
        """
        context = artificial_context()
        validate_result(context["result"])
        before = deepcopy(context)
        a, b = documents(context), documents(context)
        self.assertEqual(a, b)
        self.assertEqual(context, before)
        virtual = {(STUDY / n).resolve() for n in ("README.md", "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
        for item in context["models"].values():
            virtual.update((item["path"].resolve(), item["base_path"].resolve()))
        self.assertGreater(validate_documents(a, virtual), 55)
        self.assertIn("null（品質注意）", a["README.md"])
        self.assertIn("null（空葉）", a["設定と結果.md"])
        self.assertIn("squared_error", a["設定と結果.md"])
        self.assertIn("F17 <= 0.12345678901234566", a["設定と結果.md"])

    def test_saved_numeric_and_unknown_contract(self) -> None:
        """回帰値と障壁scoreを分け、未知nullと非正を混同しない。

        引数: なし。
        返り値: None。人工の保存値だけを検査する。
        """
        context = artificial_context()
        for item in context["models"].values():
            validate_model(item["base"])
            R55.validate_calibration(item["calibration"], item["base"])
        model = context["models"]["W20"]["base"]
        self.assertIsNone(model["nodes"][4]["recovery_positive"])
        self.assertFalse(context["models"]["W20"]["calibration"]["leaves"]["4"]["positive"])
        bad = deepcopy(model)
        bad["nodes"][4]["recovery"]["pnl5"]["mean"] = 0.
        with self.assertRaises(ValueError):
            validate_model(bad)
        bad = deepcopy(model)
        bad["nodes"][3]["score"] = bad["nodes"][3]["regression_value"]
        with self.assertRaises(ValueError):
            validate_model(bad)
        bad = deepcopy(model)
        bad["nodes"][8]["recovery_positive"] = True
        with self.assertRaises(ValueError):
            validate_model(bad)


def artificial_context() -> dict:
    """市場を使わない最小の四候補・三木文脈を作る。

    引数: なし。
    返り値: dictは人工schemaのみ。ファイルに保存しない。
    """
    methods = ("I08", "I07", "I07", "I09", "P03", "P06", "P05", "P01", "P01", "P01", "P02", "P02", "P01", "P01", "P01", "P03", "P06", "P10")
    metadata = [{"id": f"F{i + 1:02d}", "name": "人工特徴", "method": m,
                 "family": "trend" if i == 0 else "osc" if i in (1, 2) else "vol" if i == 3 else "price", "scale": "m03"}
                for i, m in enumerate(methods)]
    r = {"試行": 56, "全66場既使用": True, "候補": {}, "新回帰器fit": 9, "新分類器fit": 0, "新独立計測": 0, "新運用数": 92,
         "評価場": ["評価" + str(i) for i in range(46)], "学習専用場": ["専用" + str(i) for i in range(20)],
         "対照参照": {"候補": ["C0", "R0"], "元試行": 55, "同じ評価46場": True, "市場再生": False},
         "独立測定参照": {"元試行": 55, "path": "人工", "sha256": "人工", "再計測": False},
         "独立測定": [{"区間": "人工", "状態": "技法未準備", "方向行数": 4884}],
         "準備比較": {p: {"全予定枠": n} for p, n in zip(PERIODS, (740, 888, 74))}, "役割別入口": {}, "判断理由": {p: {} for p in NEW},
         "旧教師一致": {p: {k: True for k in ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")} for p in PHASES},
         "教師集合一致": {p: True for p in PHASES}, "採用": [], "検査": {}}
    for policy in POLICIES:
        r["候補"][policy], r["役割別入口"][policy] = {}, {}
        for period, n in zip(PERIODS, (740, 888, 74)):
            e = {"候補": 0, "約定": 0, "250": 0, "結果別": {}, "率": None, "間引き約定": 0, "間引き250": 0,
                 "間引き率": None, "日数": 0, "場数": 0, "支持": False, "70目標": False}
            caution = ["人工注意"] if period == "学習" and policy == "C0" else []
            o = {"予定枠": n, "判断別": {"待ち": n}, "待ち数": n, "判定不能": 0, "主待ち率": 1., "待ち率保守上限": 1., "活動適格": False,
                 "完結数": 0, "完結観測額円": {f: 0. for f in ("0", "5", "10")}, "全体確定額円": {f: None if caution else 0. for f in ("0", "5", "10")},
                 "品質注意場": caution, "未解消": 0, "利益起動件数": 0, "起動後赤字件数5": 0, "費用適格": False,
                 "役割別完結": {role: {"件数": 0, "観測純額5": 0.} for role in ("順行", "反転")}}
            r["候補"][policy][period] = {"入口": e, "運用": o, "同時適格": False}
            r["役割別入口"][policy][period] = {role: deepcopy(e) for role in ("順行", "反転")}
            if policy in NEW:
                r["判断理由"][policy][period] = {"人工WAIT": n}
    models = {}
    for phase, train, evaluate in (("W20", 20, 10), ("W30", 30, 10), ("F40", 40, 26)):
        nodes = [dict(id=0, feature=17, threshold=.5, left=1, right=2),
                 dict(id=1, feature=0, threshold=0., left=3, right=4),
                 dict(id=2, feature=0, threshold=0., left=5, right=6),
                 dict(id=3, feature=-2, threshold=-2., left=-1, right=-1),
                 dict(id=4, feature=-2, threshold=-2., left=-1, right=-1),
                 dict(id=5, feature=16, threshold=.12345678901234567, left=7, right=8),
                 dict(id=6, feature=-2, threshold=-2., left=-1, right=-1),
                 dict(id=7, feature=-2, threshold=-2., left=-1, right=-1),
                 dict(id=8, feature=-2, threshold=-2., left=-1, right=-1)]
        topology = {0: ([], [1., -2., 0., -1.]), 1: ([(0, "<=")], [1.]), 2: ([(0, ">")], [-2., 0., -1.]),
                    3: ([(0, "<="), (1, "<=")], [1.]), 4: ([(0, "<="), (1, ">")], []),
                    5: ([(0, ">"), (2, "<=")], [-2., 0.]), 6: ([(0, ">"), (2, ">")], [-1.]),
                    7: ([(0, ">"), (2, "<="), (5, "<=")], [-2.]), 8: ([(0, ">"), (2, "<="), (5, ">")], [0.])}
        leaves, identities = {}, []
        for n in nodes:
            path_parts, values = topology[n["id"]]
            path = [{"node": node_id, "feature_id": metadata[nodes[node_id]["feature"]]["id"], "comparison": comparison,
                     "threshold": nodes[node_id]["threshold"], "family": metadata[nodes[node_id]["feature"]]["family"]}
                    for node_id, comparison in path_parts]
            count = len(values) * 120
            total5 = sum(Decimal(str(x)) * 120 for x in values)
            with localcontext() as decimal_context:
                decimal_context.prec = 80
                mean = total5 / count if count else None
                mse = sum((Decimal(str(x)) - mean) ** 2 for x in values) / len(values) if count else None
                recovery = {f"pnl{fee}": {"sum": str(total5 + (5 - fee) * 20 * count),
                            "mean": float((total5 + (5 - fee) * 20 * count) / count) if count else None,
                            "mean_decimal": str((total5 + (5 - fee) * 20 * count) / count) if count else None}
                            for fee in (0, 5, 10)}
            families = sorted({p["family"] for p in path})
            n.update(path=path, direction_rows=count, weighted_rows=count * .5, total_weight=count * .5, success_weight=count * .25,
                     unique_slots=count // 2, days=6 if count else 0, sessions=10 if count else 0, score=.5 if count else None,
                     barrier_gini=.5 if count else None, impurity_kind="squared_error", data_absent=not count,
                     recovery=recovery, recovery_positive=total5 > 0 if count else None,
                     recovery_mse_decimal=str(mse) if count else None, impurity=float(mse) if count else None,
                     regression_value=float(mean) if count else None, leaf_support=count >= 120, families=families,
                     method_support="price" in families and "trend" in families)
            if n["left"] == -1:
                rows = [{"session": "人工", "slot_id": str(i), "side": 1 if i % 2 else -1} for i in range(len(identities), len(identities) + count)]
                identities.extend(rows)
                leaves[str(n["id"])] = {"leaf": n["id"], "direction_rows": count, "unique_slots": count // 2,
                    "days": 6 if count else 0, "sessions": 10 if count else 0,
                    "sum_yen": {str(f): recovery[f"pnl{f}"]["sum"] for f in (0, 5, 10)},
                    "mean_yen": {str(f): recovery[f"pnl{f}"]["mean"] for f in (0, 5, 10)},
                    "support": count >= 120, "positive": bool(count) and total5 > 0,
                    "max_teacher_end": 990. if count else None, "rows": rows}
        partitions = {key: {"direction_rows": count, "pair_unique": count // 2, "days": 6 if count else 0, "sessions": 10 if count else 0,
                            "root": node, "node_count": 3 if node == 5 else 1, "fit_performed": bool(count)}
                      for key, node, count in (("Z0_a0", 3, 120), ("Z0_a1", 4, 0), ("Z1_a0", 5, 240), ("Z1_a1", 6, 120))}
        model = {"policy": "G0", "model_id": "G0_" + phase, "feature_meta": metadata, "nodes": nodes,
                 "structure": {"kind": "fixed_root_and_direction", "child_depth": 2, "child_features": 17, "max_depth": 4,
                               "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"},
                 "parameters": {"criterion": "squared_error", "max_depth": 4, "min_samples_leaf": 60, "random_state": 51},
                 "subtree_parameters": {"criterion": "squared_error", "max_depth": 2, "min_samples_leaf": 60, "random_state": 51},
                 "training": {"partition": partitions, "row_ids": identities, "period": {"evaluation_start": 1000.}}}
        validate_model(model)
        models[phase] = {"entry": {"学習場": ["人工"] * train, "評価場": ["人工"] * evaluate}, "base": model,
                         "base_path": STUDY / "models" / ("G0_" + phase + ".json"), "path": STUDY / "models" / ("回収_" + phase + ".json"),
                         "calibration": {"model_id": model["model_id"], "classifier_fit_count": 0,
                                         "old_teacher_direction_rows": len(identities), "old_teacher_ids_sha256": fingerprint(identities),
                                         "input_pairs": len(identities) // 2, "used_pairs": len(identities) // 2,
                                         "used_direction_rows": len(identities), "evaluation_start": 1000., "excluded_pairs": [], "leaves": leaves}}
    return {"result": r, "proof": {"照合項目数": 0, "不一致数": 0}, "models": models, "metadata": metadata, "sources": [Path(__file__).resolve()]}


if __name__ == "__main__":
    main()
