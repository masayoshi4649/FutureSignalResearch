"""61の保存価格経路・回帰木・実運用を再学習せず二つのMarkdownへ表示する。"""

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
STUDY = ROOT / "study/00061_現在有効な経路を先に分ける"
OLD = ROOT / "study/00060_先行進行と再試験の区間分離"
MEASURED_STUDY = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
SHARED = ROOT / "scripts/回収目的分岐/レポート.py"
SPEC = importlib.util.spec_from_file_location("現行経路の固定56表示純補助", SHARED)
R56 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R56
SPEC.loader.exec_module(R56)
R55, V5 = R56.R55, R56.V5
POLICIES, NEW = ("S0", "S1", "A0", "A1"), ("A0", "A1")
PERIODS, PERIOD_NAMES, PHASES = R56.PERIODS, R56.PERIOD_NAMES, R56.PHASES
sha, read, fingerprint, table = R56.sha, R56.read, R56.fingerprint, R56.table
number, rate, qualification, link, money = R56.number, R56.rate, R56.qualification, R56.link, R56.money
CHILD_FEATURE_INDICES = [i for i in range(46) if i not in (19, 25)]
EXTRA_FORMULAS = ("T最大到達段階0..3", "T episode有効0/1", "T確認k有効0/1", "T(判断time−k.confirm)/900・kなし-1",
                  "s×(現在C−T確認kのC)/現在ATR", "T既知最大終値進行−現在進行（共通ATR）",
                  "R最大到達段階0..4", "R episode有効0/1", "R確認k有効0/1", "R(判断time−k.confirm)/900・kなし-1",
                  "s×(現在C−R確認kのC)/現在ATR", "R既知最大終値進行−現在進行（共通ATR）")
DEPTH_FORMULAS = tuple(value for role in ("T", "R") for value in (
    role + " −min(0,min u_i)/現在ATR", role + " (max(0,max u_i)−u_j)/現在ATR",
    role + " u_j/(現在ATR×n)・n0は0", role + " s×(現在C−登録K)/現在D"))
SEGMENT_FORMULAS = tuple(value for role in ("T", "R") for value in (
    role + " s×(Cb−C[b−10])/(10×現在ATR)", role + " s×(Cb−C[b−10])/Σ|ΔC|・総変動0は0",
    role + " s×(Cr−Cp)/(現在ATR×(r−p))・rなし0", role + " s×(Cj−Cr)/(現在ATR×(j−r))・rなし又はj=rは0"))
FORMULAS = (*R55.G.FORMULAS, *EXTRA_FORMULAS, *DEPTH_FORMULAS, *SEGMENT_FORMULAS)



def validate_result(result: dict) -> None:
    """新旧候補・固定期間・分母・nullとfitの用途を検査する。

    引数: result(dict)は61の保存結果。市場や教師の系列は開かない。
    返り値: None。不一致は例外にする。
    """
    if result.get("試行") != 61 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("61の候補又は既使用契約が不正")
    if type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 12 or (result["新分類器fit"], result["新独立計測"], result["新運用数"]) != (0, 0, 92):
        raise ValueError("回帰最大12・分類0・新独立計測0・新運用92の契約差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・評価46場の区分差")
    if result["対照参照"] != {"候補": ["S0", "S1"], "元試行": 60, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("対照は固定60S0/S1保存値だけ")
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
    if result["検査"]["旧46特徴保存一致"] != 3404:
        raise ValueError("旧60評価3404方向の46特徴一致が必要")
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
    for p in ("S0", "S1"):
        if result["候補"][p] != old["候補"][p] or result["役割別入口"][p] != old["役割別入口"][p]:
            raise ValueError("固定60の対照集計差")
    for k in ("評価場", "学習専用場", "準備比較", "独立測定"):
        if result[k] != old[k]:
            raise ValueError("固定60の期間・準備・測定参照差:" + k)
    if result["対照モデル"] != old["モデル"]:
        raise ValueError("固定60の対照モデル差")
    measured = result["独立測定参照"]
    if measured != old["独立測定参照"]:
        raise ValueError("固定55独立測定参照のパス又はSHA差")
    calibrations = {x["phase"]: x for x in result["回収集計"]}
    models, paths, metadata = {}, [], None
    for entry in result["モデル"]:
        phase = entry["phase"]
        if phase not in PHASES or phase in models or entry["id"] != "A0_" + phase:
            raise ValueError("新3モデルのID・phase差")
        path = (ROOT / entry["path"]).resolve()
        cal_entry = calibrations[phase]
        cal_path = (ROOT / cal_entry["path"]).resolve()
        if any(not p.is_relative_to(STUDY) for p in (path, cal_path)) or sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("新モデル・回収集計の版差")
        model, cal = read(path), read(cal_path)
        validate_model(model)
        prior_entry = next(x for x in old["モデル"] if x["phase"] == phase)
        prior_model = read(ROOT / prior_entry["path"])
        if sha(ROOT / prior_entry["path"]) != prior_entry["SHA256"]:
            raise ValueError("旧60モデルの指紋差")
        validate_prior46(model, prior_model)
        R55.validate_calibration(cal, model)
        if cal["base_model_path"] != entry["path"] or cal["base_model_sha256"] != entry["SHA256"] or cal["phase"] != phase:
            raise ValueError("新回帰木と回収集計の出典差")
        if metadata is None:
            metadata = model["feature_meta"]
        if model["feature_meta"] != metadata or len(metadata) != 46:
            raise ValueError("共通46特徴の順序差")
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
    validate_state_distribution(result["状態分布"], models)
    resources = read(STUDY / "一覧.resources.json")["resources"]
    if len(resources) != 184 or Counter(x["method_id"] for x in resources) != {p: 46 for p in POLICIES}:
        raise ValueError("旧92+新92の184Viewer資源差")
    if any(not (ROOT / x["pnl_path"]).is_file() for x in resources):
        raise ValueError("Viewer約定参照欠落")
    sources = [*required, *paths, Path(__file__), HERE / "README.md", HERE / "検証.py", HERE / "学習.py", HERE / "保存検証.py",
               SHARED, R56.SHARED, R55.SHARED, ROOT / "scripts/レポート/カタログ版5.py", ROOT / "scripts/レポート/設定結果レポート.py",
               V5.CATALOG, V5.MASTER, OLD / "結果.json", OLD / "設定と結果.md", OLD / "保存物確認.json",
               ROOT / "scripts/局所帯分岐/特徴仕様.md", HERE / "特徴.py", HERE / "特徴仕様.md", ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md",
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
    if model["policy"] != "A0" or len(model["feature_meta"]) != 46 or len({n["id"] for n in model["nodes"]}) != len(model["nodes"]):
        raise ValueError("46特徴又はnode一意性の差")
    structure = model["structure"]
    if (structure["kind"], structure["child_depth"], structure["child_features"], structure["max_depth"], structure["fixed_mse_optimized"], structure["child_estimator"], structure["target"]) != ("fixed_current_routes", 2, 44, 4, False, "DecisionTreeRegressor", "pnl5"):
        raise ValueError("固定二段・子回帰目的の差")
    for parameters, depth in ((model["parameters"], 4), (model["subtree_parameters"], 2)):
        if (parameters["criterion"], parameters["max_depth"], parameters["min_samples_leaf"], parameters["random_state"]) != ("squared_error", depth, 60, 51) or "class_weight" in parameters:
            raise ValueError("回帰の固定設定差")
    if structure["child_feature_indices"] != CHILD_FEATURE_INDICES or structure["feature_count"] != 46:
        raise ValueError("F20/F26を除く44列の子投影差")
    if any(n["feature"] in (19, 25) for n in model["nodes"][3:] if n["left"] != -1):
        raise ValueError("子木は固定根F20/F26を再使用しない")
    if [(n["feature"], n["threshold"]) for n in model["nodes"][:3]] != [(19, .5), (25, .5), (25, .5)]:
        raise ValueError("現行T→R有効の固定根が不一致")
    ids = {n["id"] for n in model["nodes"]}
    for n in model["nodes"]:
        if n["left"] != -1 and (n["left"] not in ids or n["right"] not in ids or not 0 <= n["feature"] < 46 or not math.isfinite(n["threshold"])):
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
            raise ValueError("price根と子trend/oscの技法資格が不一致")
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


def validate_prior46(model: dict, prior_model: dict) -> None:
    """同じ46列の旧正本と教師指紋を結び、分岐変更だけを分ける。

    引数: model/prior_model(dict)は61と固定60の同phase保存木。
    返り値: None。base46六指紋と既存18/30/38射影の保持を確認する。
    """
    if model["feature_meta"] != prior_model["feature_meta"]:
        raise ValueError("旧46特徴metadataの順序差")
    keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
    if model["training"]["base46_fingerprints"] != {key: prior_model["training"][key] for key in keys}:
        raise ValueError("旧46特徴教師6指紋が不一致")
    for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints"):
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

    引数: result(dict)は61結果。
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
    """版5全55×9、46特徴、内部リンクを検査する。

    引数: output(dict[str,str])は二つの本文、generated(set[Path])は同時生成又は人工仮想参照。
    返り値: intはリンク確認数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [r for r in text.splitlines() if r.startswith("| ") and r.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(r.split("|")) != 13 for r in rows):
        raise ValueError("版5の55×9が不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 47)):
        raise ValueError("46特徴の表示漏れ")
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
# 新しい価格経路の表示。特徴・木の計算処理はimportしない。


def validate_coverage(coverage: dict) -> None:
    """成績を使わない経路分布の分母と取消・未完了の復元を検査する。

    引数: coverage(dict)は主処理が保存した五つの用途区間。
    返り値: None。不明数を0補完せず、不整合は拒否する。
    """
    groups = {"全66場": 2442, "学習専用20場": 740, "時系列20場": 740, "条件選択24場": 888, "既使用2場": 74}
    if set(coverage) != set(groups):
        raise ValueError("価格経路分布の区間差")
    for name, total in groups.items():
        group = coverage[name]
        if group["全枠"] != total or group["準備枠"] + group["未準備枠"] != total or group["準備方向行"] != group["準備枠"] * 2:
            raise ValueError("価格経路の全枠・準備枠・方向行差")
        for role, last_stage in (("T", 3), ("R", 4)):
            row = group[role]
            if row["方向行"] != group["準備方向行"] or set(row["段階"]) - {str(i) for i in range(last_stage + 1)}:
                raise ValueError("経路の方向行又は最大段階差")
            if sum(row["段階"].values()) != row["方向行"] or row["episode有効"] + row["取消"] != row["方向行"] - row["段階"].get("0", 0):
                raise ValueError("未登録・有効・取消の排他復元差")
            if row["k形成"] != row["段階"].get(str(last_stage), 0) or not 0 <= row["k有効"] <= min(row["k形成"], row["episode有効"]):
                raise ValueError("k形成と有効・最大段階の差")
            ages = row["k経過最小"], row["k経過最大"]
            if not row["k形成"]:
                if ages != (None, None):
                    raise ValueError("k未形成の経過範囲はnull")
            elif any(v is None or not math.isfinite(v) or v < 0 for v in ages) or ages[0] > ages[1]:
                raise ValueError("k公開後経過範囲が不正")
            validate_episode_counts(row, row["方向行"])
    for key in ("全枠", "準備枠", "未準備枠", "準備方向行"):
        if coverage["全66場"][key] != sum(coverage[name][key] for name in groups if name != "全66場"):
            raise ValueError("用途別価格経路分布の全体復元差")


def validate_episode_counts(counts: dict, direction_rows: int) -> None:
    """反復観測とunique episode・なしの分母を分けて検査する。

    引数: counts(dict)は保存6整数、direction_rows(int)は該当する方向行数。
    返り値: None。unique episodeを支持gateや重みへ置き換えない。
    """
    keys = ("episode数", "episode最大反復", "episodeなし", "k形成episode数", "k有効episode数", "期限失効観測")
    if any(type(counts[k]) is not int or counts[k] < 0 for k in keys):
        raise ValueError("episode統計は非負整数が必要")
    observed = direction_rows - counts["episodeなし"]
    unique, repeated = counts["episode数"], counts["episode最大反復"]
    if not 0 <= counts["episodeなし"] <= direction_rows or not 0 <= counts["k有効episode数"] <= counts["k形成episode数"] <= unique <= observed:
        raise ValueError("episode数・k形成・有効・なしの分母差")
    if (unique == 0 and (observed != 0 or repeated != 0)) or (unique > 0 and not 1 <= repeated <= observed):
        raise ValueError("episode最大反復の範囲差")
    if unique and repeated * unique < observed or counts["期限失効観測"] > direction_rows:
        raise ValueError("反復又は期限失効観測の上限差")


def validate_episode_support(support: dict, models: dict) -> None:
    """各学習phaseの全葉方向行を保存modelへ結ぶ。

    引数: support(dict)は主の経路支持、models(dict)は表示用の新3木。
    返り値: None。葉をまたぐ同episodeを独立標本としない。
    """
    if set(support) != set(PHASES):
        raise ValueError("経路支持のphase差")
    for phase in PHASES:
        nodes = {str(n["id"]): n for n in models[phase]["base"]["nodes"] if n["left"] == -1}
        if set(support[phase]) != set(nodes):
            raise ValueError("空葉を含む経路支持の全葉差")
        for identity, row in support[phase].items():
            if row["方向行"] != nodes[identity]["direction_rows"]:
                raise ValueError("葉所属の方向行数差")
            for role in ("T", "R"):
                validate_episode_counts(row[role], row["方向行"])


def validate_state_distribution(distribution: dict, models: dict) -> None:
    """現行有効四群の全使用方向行と形成状態の分母を検査する。

    引数: distribution(dict)は保存状態分布、models(dict)はphase別保存木。
    返り値: None。旗だけをr/k発動や反転成立へ読み替えない。
    """
    if set(distribution) != set(PHASES):
        raise ValueError("状態分布のphase差")
    for phase in PHASES:
        partitions = models[phase]["base"]["training"]["partition"]
        if set(distribution[phase]) != {"T0_R0", "T0_R1", "T1_R0", "T1_R1"}:
            raise ValueError("現行有効の固定四群差")
        for name, group in distribution[phase].items():
            n = group["方向行"]
            if type(n) is not int or n < 0 or n != partitions[name]["direction_rows"]:
                raise ValueError("状態分布の使用方向行差")
            for key, target in (("unique枠", "pair_unique"), ("日数", "days"), ("場数", "sessions")):
                if type(group[key]) is not int or group[key] != partitions[name][target]:
                    raise ValueError("状態分布の非重複枠/日/場差")
            if not 0 <= group["日数"] <= group["場数"] <= group["unique枠"] <= n or (n == 0) != (group["unique枠"] == 0):
                raise ValueError("状態分布の枠/日/場の範囲差")
            for role, flag in (("T", int(name[1])), ("R", int(name[-1]))):
                row = group[role]
                keys = ("形成あり", "形成なし", "取消あり", "rあり", "kあり", "k有効", "形成ID数")
                if any(type(row[key]) is not int or row[key] < 0 for key in keys):
                    raise ValueError("形成状態の件数型差")
                formed = row["形成あり"]
                if formed + row["形成なし"] != n or row["取消あり"] > formed or not 0 <= row["k有効"] <= row["kあり"] <= row["rあり"] <= formed or row["形成ID数"] > formed:
                    raise ValueError("形成/r/k/取消の分母差")
                if (formed == 0) != (row["形成ID数"] == 0):
                    raise ValueError("形成ID数の有無差")
                if flag and (formed != n or row["取消あり"]):
                    raise ValueError("有効1群に未登録又は取消が混入")
                if not flag and row["k有効"]:
                    raise ValueError("有効0群に現在有効kが混入")


def state_distribution_table(context: dict) -> str:
    """現行有効四群を継続/反転の名前に置換せず表示する。

    引数: context(dict)は結果の状態分布。
    返り値: strは全使用教師と各経路の段階分母。状態の再計算はしない。
    """
    rows = []
    for phase in PHASES:
        for name, group in context["result"]["状態分布"][phase].items():
            for role in ("T", "R"):
                state = group[role]
                rows.append([phase, name, role, group["方向行"], group["unique枠"], group["日数"], group["場数"],
                    *(state[key] for key in ("形成あり", "形成なし", "取消あり", "rあり", "kあり", "k有効", "形成ID数"))])
    return ("## 現行有効四群の使用教師分布\n\n全phaseの実使用方向行を現在T/R有効2旗で分ける。評価の純採用・実完結の表ではない。"
            "有効1はb登録からでr/k形成を保証しない。有効0は未ID・取消・TTL等を含む。四群へ継続確定/反転確定という名前を付けない。"
            "形成ID数は反復を除くが群/葉間で重複し得るため非加算。支持gateや重みへ転用しない。\n\n"
            + table(["phase", "現行群", "経路", "使用方向行", "unique枠", "日", "場", "形成あり", "形成なし", "取消あり", "rあり", "kあり", "k有効", "unique形成ID"], rows))


def settings(context: dict) -> list[dict]:
    """全候補共通46特徴と新しい現行有効根を版5へ対応させる。

    引数: context(dict)は保存46列metadata。
    返り値: list[dict]は使用セルの設定。特徴追加の比較とは記さない。
    """
    result = []
    for i, m in enumerate(context["metadata"]):
        result.append({"設定ID": f"S{i + 1:02d}", "手法ID": [m["method"]], "尺度ID": m["scale"].split("+"),
                       "短記": m["id"] + "=" + FORMULAS[i], "結果短記": "R01/R02/R03/R04",
                       "説明": "旧60と同じ46列入力。現在有効2旗で先に分ける根と子投影を変更し、独立票を追加しない"})
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02", "旧60S0/S1保存対照", "同46場の結果を再運用しない。"),
              (["M01"], ["m03", "m15", "m30"], "R03/R04", "現行T→R有効固定・44列回帰d2/MSE", "根はF20/F26の0.5。子からindex19/25を除く44列、F18/DIは子へ。全深さ4・minleaf60・重み0.5・seed51。根2つはpriceで、子にtrend/oscがない葉は技法資格不成立。"),
              (["P10", "P05"], ["m03"], "R03/R04", "登録Kを最大60分保持する再試験とk後進行", "T最低3足/R最低4足、別足順序・最初r固定を維持。Kの寿命は元bの公開から3600秒、取消/再登録は別管理。"),
              (["M01"], ["tick", "m03", "m15", "m30"], "R03/R04", "A0:障壁score最高側＋回収支持60枠6日10場", "回帰平均が高い側へ変更せず、score>=1/3・葉/技法/回収支持。次点救済なし。"),
              (["M01"], ["tick", "m03", "m15", "m30"], "R04", "A1:A0＋主回収平均strict正", "Decimal sum5>0。平均正を将来利益の保証としない。"),
              (["B01", "E02"], ["tick"], "R03/R04", "旧55独立測定4884方向再用・新計測0", "同じ教師集合へ当時の価格経路列を追加。未知を0補完せず、合計は同時実行戦略利益ではない。"),
              (["E02", "C06"], ["tick"], "R01/R02/R03/R04", "固定49O・現在益122円strict", "利益前も連続追尾、名目床、非緩和、pending保護凍結。新規ATR由来のD5..125固定。"),
              (["E01"], ["tick"], "R01/R02/R03/R04", "仮125/250先着・固定TPなし", "先着率・円予測・過去平均・実損益は別。"),
              (["C07"], ["m15"], "R01/R02/R03/R04", "当時公開・現在判断・鮮度", "15分が判断頻度、m30は3分10本OR。過去k価格へ約定を戻さない。")]
    for methods, scales, evaluations, short, description in extras:
        result.append({"設定ID": f"S{len(result) + 1:02d}", "手法ID": methods, "尺度ID": scales,
                       "短記": short, "結果短記": evaluations, "説明": description})
    return result


def feature_table(context: dict) -> str:
    """旧60と共通の全46式を省略せず、根と子の役割を明示する。

    引数: context(dict)は46列metadata。
    返り値: strは全46特徴の表。
    """
    contents = [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i],
                 "全候補共通46"] for i, m in enumerate(context["metadata"])]
    return ("## 全46特徴\n\n全46列は旧60と同じで、特徴追加の比較ではない。新A0/A1はF20(index19)→F26(index25)を0.5で固定分岐し、子はその2列以外の44列を使う。"
            "旧F18の局所ZとDIは子が選択できる。根2つはpriceで、子にtrend/oscがない葉は従来の技法資格を満たさない。"
            "T/R有効旗はb登録時からの現在状態であり、r/k形成を保証しない。F18の旧移動帯Zと、bで固定したKは別の線である。"
            "sは候補の実side、jは現在足。登録へ至る区間はb−10..bの11終値・10差分。Tはa=b、Rはa=fとし、r形成時の[a,r−1]でs×C最大の最初のpを固定する。"
            "IDなしの新4列は既知0。rなしでは後2列0、j=rではr後進行0。段階とmaskで未適用と真の0を区別する。"
            "登録区間は機械的な十差分で、先行推進波全体を完全に検出したとはしない。同じ価格から作った特徴を独立した8票とはしない。\n\n"
            + table(["ID", "特徴", "手法", "family", "尺度", "式・範囲", "用途"], contents)
            + "最大stageはT0..3/R0..4を取消後も保持する。episode有効とk有効を別列にし、高stageだから採用可とはしない。"
            "k未形成なら経過−1・進行/戻り0は既知の未発生値であり、特徴未準備とは別。k形成後は取消後もTTL又は置換まで既知現在の統計を更新し、有効旗を復活させない。"
            "age=(判断time−k.confirm)/900は正規化値で、900秒の新TTL条件ではない。進行と最大終値からの戻りは現在ATRを共通分母にする。"
            "登録平均の分母は10×現在ATR、符号付き効率の分母は同じ十差分の絶対値和で、総変動0なら効率0。"
            "p→r進行の正値も許可し、rが必ず価格的な押戻しだったと先に決めない。pはr時点で固定し、後続峰へ更新しない。"
            "r後の平均純進行は現在jまでで、秒当たり瞬間速度ではない。全て終値で、BBO・実約定価格・将来の残存値幅ではない。"
            "旧F07の一足変化、旧b全期間平均、旧k後進行と情報が重なるため、独立した票とはしない。\n\n")


def model_tables(context: dict, output: Path) -> str:
    """固定56の純表示から全新nodeを46列の元indexで表示する。

    引数: context(dict)は新3木、output(Path)は詳細MD。
    返り値: strは全path/閾値・支持・MSE・先着score・回帰平均。
    """
    text = R56.model_tables(context, output)
    text = text.replace("固定Z（F18<=0.5）→float32 DI（F01<=0/>0）の四区分、子は先頭17列だけの深さ2。",
        "現在T有効F20(index19)<=0.5→現在R有効F26(index25)<=0.5の四群。子は両根以外の44列・深さ2。")
    text = text.replace("priceとtrendの固定段で異種family資格が構造上充足する点は旧54/55と共通。",
        "固定根2つはpriceで、異種family資格は自動充足しない。子pathにtrend/oscが必要。")
    text = text.replace("DI固定段の左はfloat32 F01<=0で同値・float32零化も含む。評価時の背景DI同値は最終WAITで、左枝を全て逆向きと呼ばない。",
        "DIは固定根から子へ移る。背景DI同値の最終WAITは維持し、価格T/Rと実運用のDI順行/反転を別にする。最高score側の技法不足を次点で救済しない。")
    meta = {row["id"]: row for row in context["metadata"]}
    leaves = []
    for phase in PHASES:
        for node in context["models"][phase]["base"]["nodes"]:
            if node["left"] != -1:
                continue
            selected = [meta[p["feature_id"]] for p in node["path"] if p["node"] >= 3 and meta[p["feature_id"]]["family"] in ("trend", "osc")]
            names = "/".join(dict.fromkeys(row["id"] + ":" + row["method"] + ":" + row["family"] for row in selected)) or "なし"
            leaves.append([phase, node["id"], node["direction_rows"], names, qualification(node["method_support"]), "/".join(node["families"]) or "なし"])
    return text + "## 子に選ばれた方向・勢いと全葉の技法資格\n\n根の2旗を二つの異種情報と数えない。子にtrend/osc列がない葉は、priceやvolが選ばれても技法資格を満たさない。他の支持や過去平均が正でも同じである。\n\n" + table(["phase", "leaf", "方向行", "子trend/osc特徴:手法:family", "技法資格", "全path family"], leaves)


def recovery_tables(context: dict, output: Path) -> str:
    """全回収葉の表示純補助だけを再利用する。

    引数: context(dict)は3回収集計、output(Path)は詳細MD。
    返り値: strは全葉と空平均null。新学習・walk・回収集計はしない。
    """
    return R56.recovery_tables(context, output).replace("G1は主合計strict>0", "A1は主合計strict>0")


def coverage_table(result: dict) -> str:
    """取消・未登録・未完了を含む全定時の価格経路分布を表示する。

    引数: result(dict)は主が保存した価格経路分布。
    返り値: strは用途別分母とT/R段階・k形成/有効・取消・経過範囲。
    """
    denominators, contents, episodes = [], [], []
    for name, group in result["価格経路分布"].items():
        denominators.append([name, group["全枠"], group["準備枠"], group["未準備枠"], group["準備方向行"]])
        for role, maximum in (("T", 3), ("R", 4)):
            row = group[role]
            contents.append([name, role, row["方向行"], "/".join(str(row["段階"].get(str(i), 0)) for i in range(maximum + 1)),
                             row["episode有効"], row["k形成"], row["k有効"], row["取消"],
                             R56.full_number(row["k経過最小"]), R56.full_number(row["k経過最大"])])
            episodes.append([name, role, row["方向行"], row["episode数"], row["episode最大反復"], row["episodeなし"],
                             row["k形成episode数"], row["k有効episode数"], row["期限失効観測"]])
    return ("## 全定時の価格経路分布\n\n純採用や250成功だけを抜き出した分布ではない。準備1枠に実方向±の2行、各方向にT/Rの2経路を記述する。"
            "同じ価格の反射や複数役割を独立標本として加算しない。全66場とその用途別部分集合も重ねて加算しない。\n\n"
            + table(["用途区間", "全予定枠", "準備枠", "未準備枠", "準備方向行"], denominators)
            + "stageは最大到達で取消後も保持。episode有効＋取消＋未登録で方向行を復元する。k形成と定時k有効も分離し、"
            "未形成の経過範囲はnull（0ではない）。経過欄の単位は(判断time−k.confirm)/900。\n\n"
            + table(["用途区間", "経路", "方向行", "stage0から最大の順", "episode有効", "k形成", "k有効", "取消", "k経過最小/900", "k経過最大/900"], contents)
            + "同じepisodeが複数定時に見える場合を次表で分ける。episode数はID=Noneを除くunique、最大反復は同IDの最大観測方向行数。"
            "期限失効観測はlast_expiredが残る方向行であり、再登録後にも残る。同じ失効が繰り返し見えるため、独立した失効イベント数ではない。\n\n"
            + table(["用途区間", "経路", "方向行", "unique episode", "最大反復", "IDなし", "k形成episode", "k有効episode", "期限失効観測"], episodes))


def episode_support_table(context: dict) -> str:
    """全phase・全葉の反復を、学習方向行と別の列で表示する。

    引数: context(dict)は結果の経路支持と新model。
    返り値: strは全葉T/Rの診断表。支持gate・学習重みは変えない。
    """
    contents = []
    for phase in PHASES:
        for identity, row in sorted(context["result"]["経路支持"][phase].items(), key=lambda item: int(item[0])):
            for role in ("T", "R"):
                count = row[role]
                contents.append([phase, identity, role, row["方向行"], count["episode数"], count["episode最大反復"], count["episodeなし"],
                                 count["k形成episode数"], count["k有効episode数"], count["期限失効観測"]])
    return ("## 学習葉ごとのepisode反復\n\n全model.training.row_idsを現在の保存葉へ結んだ方向行が分母で、後続で採用された純入口の表ではない。"
            "同じIDが時点と特徴の変化で別葉へ到達し得るため、葉間のunique episodeは非加算。IDなしも分母へ残す。"
            "支持60枠や方向重み0.5をepisode単位へ変更せず、1回消費制限も加えていない。未保有なら同じ形成で再参加し得る。\n\n"
            + table(["phase", "leaf", "経路", "学習方向行", "unique episode", "最大反復", "IDなし", "k形成episode", "k有効episode", "期限失効観測"], contents))


def documents(context: dict) -> dict[str, str]:
    """保存文脈だけから短い概要と全設定を生成する。

    引数: context(dict)は正式又は人工schema。
    返り値: dict[str,str]はREADME/設定と結果。書込や本物データ計算は行わない。
    """
    r, proof = context["result"], context["proof"]
    brief_path, detail_path = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operation = main_tables(r)
    status = "新候補の採用なし。先着70・支持・費用・活動の両期同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。既使用外の利益保証ではない。"
    intro = ("全66場は既使用。初20場は学習専用、学習欄は後20場の時系列検査、条件選択24/既使用後続2場ではF40を固定し再fitしない。\n\n"
             + status + "\n\n旧60S0/S1は保存対照。同じ全46特徴と価格機械を保ち、根だけを現在T有効F20(index19)→現在R有効F26(index25)の各0.5へ変更する。"
             "子は両根を除く44列、F18/DIは子へ移る。子深さ2・全深さ4は回収pnl5のMSEで学習する。"
             + "新回帰器" + str(r["新回帰器fit"]) + "fit（最大12）、分類器fit0・新独立計測0・新混合運用92。"
             "順位は障壁score最高側を維持し、回帰予測の高い側へ変えない。A0は先着score>=1/3と葉/技法/回収支持60枠6日10場、A1は主回収平均strict正も必要。"
             "根2つはpriceなので、子にtrend/oscのない葉は技法資格不成立。次点救済なし。有効1はr/k発動、0は反対成立を意味しない。\n\n")
    mechanics = ("## 価格順序・判断・執行の限定\n\nTはb→r→k最低3本、Rはb→f→r→k最低4本の順序を保ち、反応を5本へ切らずb.confirm+3600まで追う。60分は定時4枠の上限ではなく、出生の位相や公開/欠測により観測枠数が変わる。"
                 "取消・未登録・段階未完了を消さず、完成したkだけを母集団にしない。経路T/Rは仮説の名前であり、採用役割の順行/反転は現在DIで付く。"
                 "k有効を全新規の追加ANDとして強制した実験ではなく、木は未完了・取消も特徴として受け取る。\n\n"
                 "当時既知の同じ帯端Kに対して最初のb/f/rを固定し、取消を次段成立より優先する。別の足と公開key順序を確認し、同足高安の到達順を作らない。"
                 "r足の高安が前段の公開後に形成されたと保証する条件は追加していない。終値の観測順と足内形成順は別。"
                 "有効中は新しい水準へ置換しない。取消した足を新bへ使わず、次足からのみ新登録を検討する。"
                 "判断time又は処理足の公開時刻がb.confirm+3600へ達した同秒を含め失効し、最初の期限越え足は新bへ再使用しない。"
                 "k後の既知統計は取消後もTTL又は置換まで継続する。\n\n"
                 "判断はデイ09:15〜15:15の25枠/ナイト17:30〜05:30の49枠。保有継続は非待ち、全予定枠で判定不能込み保守上限50%以下を要求する。"
                 "定時より前のk価格へ約定を戻さず、現在正常BBOから後行1価格時計秒、新規TTL30秒。新規残り60分条件なし、強制15:35/05:50・終了15:40/05:55。\n\n"
                 "固定49O・micro1枚10円/pt、片道11円＋想定片道5pt。新規時の現ATRを5pt切上げD5..125へ制限し保有中固定。"
                 "損失側も連続追尾、現在返済気配の粗益−122円strict正で利益旗・最低名目新規床・非緩和、返済pendingは保護凍結。"
                 "固定250TPなし。0/10ptは同約定の費用感応で起動122円は不変、名目床は費用後同値の保証ではない。\n\n"
                 "先着率・回帰予測・過去平均・実運用利益は別。旧55単独測定は重複保有を含み合計はstrategy利益でない。"
                 "新価格列は同じOHLCの加工であり、独立した注文票・心理の直測・量情報の追加ではない。価格の不進行だけから吸収や反転成立を断定しない。"
                 "ラージBBO代理で、micro実板・受信時計の測定ではない。\n\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, brief_path) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
             + " / " + link(HERE / "README.md", brief_path, "コードと再現") + "\n\n"
             "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧S0/S1各46＋新A0/A1各46＝184資源。\n\n"
             + link(OLD / "設定と結果.md", brief_path, "旧60の全閾値と回収") + " / "
             + link(ROOT / "docs/議論/回収を分割目的にした技法群の比較.md", brief_path, "価格順序へ進む問い") + " / "
             + link(ROOT / "docs/議論/外部再調査/否定された形と新しい入口を分ける.md", brief_path, "形の否定と新入口の外部確認")
             + "\n\n保存監査：" + number(proof["照合項目数"]) + "照合・差" + number(proof["不一致数"]) + "。Viewer実行確認の範囲は監査JSONを正本とする。\n\n"
             "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n"
             "~~~powershell\nC:/Python314/python.exe -X utf8 scripts/現行経路の状態分岐/レポート.py\n"
             "C:/Python314/python.exe -X utf8 scripts/現行経路の状態分岐/レポート.py --check\n~~~\n")
    settings_rows = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail_path, settings_rows).replace("未使用", "未使用・未検証")
    settings_table = table(["設定ID", "手法/尺度", "設定内容", "解釈と限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in settings_rows])
    sources = table(["出典", "SHA256"], [[link(p, detail_path), sha(p)] for p in context["sources"]])
    external = ("## 外部根拠と独自規約\n\n確認日2026-11-06。Brooks公式の"
                "[Price Action Trading Terms Glossary](https://www.brookstradingcourse.com/price-action-trading-terms-glossary/)"
                "（個別著者・公開日不明、failure/failed failure・minor reversal・setup/signal/entryの項）を確認。"
                "元の形の失敗、失敗した突破の再取得、新規の発動は別であり、小さい逆行が反対トレンド成立とは限らない。"
                "原典failureにはstop/target等の文脈もあり、本研究の取消旗と同一定義ではない。将来のentryからsignalを過去へ付け直す入力にはしない。\n\n"
                "Grimes本人の[Did you miss a trade?](https://www.adamhgrimes.com/did-you-miss-a-trade/)"
                "（2021-08-25、Did you REALLY/Tilting points/So what to doの本文とUSDCAD例）は、既存longの退出、新shortの価格発動、後のmomentum setupを分ける。"
                "後から明瞭に見える入口が当時も明瞭だったとは限らず、既存玉の退出判断をそのまま反対新規へ転用しない。"
                "既読のGrimes/Brooks分類を具体的な観測順へ掘り下げたもので、新発見や独立した二つの収益実証ではない。"
                "単一例・教育説明からNK225の先着70%、費用後利益、最適寿命や心理の実測を得たとはしない。\n\n"
                "現在のT/R有効旗による固定二段は本研究の独自比較。有効1はb登録から始まりr/k形成を保証せず、有効0には未登録・取消・期限失効等が混在する。"
                "四群を継続/反転成立の名称へ置き換えず、元形の否定から反対側を自動採用しない。"
                "別足の公開順と足内形成順を分け、未来の復活や利益を現在入力へ渡さない。旧60と同じ46列・教師・費用122円strict起動・連続保護で比較し、"
                "同じepisodeの反復を独立した機会へ数え替えない。量や注文動機の直接測定は追加していない。\n\n")
    brief = "# 00061：現在有効な経路を先に分ける\n\n" + intro + "## 入口先着\n\n" + entrance + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    detail = ("# 00061：設定と結果\n\n" + intro + "R01=旧S0、R02=旧S1、R03=A0、R04=A1。\n\n"
              + "## 手法×尺度・版5全文\n\n55手法×9尺度を全件保持。未使用・未検証をデータ不足や対象外と取り替えず、複合成績を個別指標の効果としない。\n\n"
              + matrix + feature_table(context) + "## 設定明細\n\n" + settings_table + coverage_table(r)
              + model_tables(context, detail_path) + recovery_tables(context, detail_path) + episode_support_table(context)
              + state_distribution_table(context)
              + "## 全候補の入口先着\n\n" + entrance + "## 全候補の混合運用\n\n" + operation + detail_tables(r) + mechanics + external
              + "## 検査と版\n\n旧教師一致：" + json.dumps(r["旧教師一致"], ensure_ascii=False)
              + "。教師集合一致：" + json.dumps(r["教師集合一致"], ensure_ascii=False) + "。保存検査：" + json.dumps(r["検査"], ensure_ascii=False)
              + "。独立測定参照：" + json.dumps(r["独立測定参照"], ensure_ascii=False)
              + "。表示器は旧測定gzipを開かず、小型参照と新旧監査の証明へ接続する。"
              "各モデルtrainingのbase46_fingerprints六キーを旧60の全46列正本へ照合し、base18/base30/base38の既存射影も不変と確認する。"
              "入力列の追加ではなく同じ46列の固定根と子投影を変える比較であり、全46canonicalの指紋と既存各射影の指紋は別である。\n\n"
              + "## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief_path, detail_path, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detail}


# ----------------------------------------
# 正式結果・教師を開かない表示検査。


def artificial_context() -> dict:
    """固定56の人工文脈だけを46列・A政策へ写す。

    引数: なし。
    返り値: dictは人工の小型保存schema。旧moduleや入力を変更しない。
    """
    c = deepcopy(R56.artificial_context())
    r, old_metadata = c["result"], deepcopy(c["metadata"])
    mapping = {"C0": "S0", "R0": "S1", "G0": "A0", "G1": "A1"}
    for field in ("候補", "役割別入口", "判断理由"):
        r[field] = {mapping[p]: value for p, value in r[field].items()}
    r["試行"] = 61
    r["対照参照"] = {"候補": ["S0", "S1"], "元試行": 60, "同じ評価46場": True, "市場再生": False}
    for i in range(18, 46):
        c["metadata"].append({"id": f"F{i + 1:02d}", "name": "人工" + str(i),
                              "method": "P05" if i in (22, 28, 32, 36) or i >= 38 else "P10", "family": "price", "scale": "m03"})
    for phase, item in c["models"].items():
        m = item["base"]
        m["policy"], m["model_id"] = "A0", "A0_" + phase
        m["feature_meta"] = c["metadata"]
        m["structure"].update(kind="fixed_current_routes", child_features=44, child_feature_indices=CHILD_FEATURE_INDICES, feature_count=46)
        m["nodes"][0]["feature"], m["nodes"][0]["threshold"] = 19, .5
        for node_id in (1, 2):
            m["nodes"][node_id]["feature"], m["nodes"][node_id]["threshold"] = 25, .5
        m["nodes"][5]["feature"] = 1
        for node in m["nodes"]:
            for step in node["path"]:
                split = m["nodes"][step["node"]]
                meta = c["metadata"][split["feature"]]
                step.update(feature=split["feature"], feature_id=meta["id"], family=meta["family"], method=meta["method"], threshold=split["threshold"])
            node["families"] = sorted({step["family"] for step in node["path"]})
            node["method_support"] = len(node["families"]) >= 2 and bool(set(node["families"]) & {"trend", "osc"})
        old_parts = m["training"]["partition"]
        m["training"]["partition"] = {f"T{t}_R{r}": {**old_parts[f"Z{t}_a{r}"], "t": t, "r": r} for t in (0,1) for r in (0,1)}
        item["base_path"] = STUDY / "models" / (m["model_id"] + ".json")
        item["path"] = STUDY / "models" / ("回収_" + phase + ".json")
        item["calibration"]["model_id"] = m["model_id"]
        validate_model(m)
    coverage = {}
    for name, total in (("学習専用20場", 740), ("時系列20場", 740), ("条件選択24場", 888), ("既使用2場", 74)):
        row = {"全枠": total, "準備枠": 1, "未準備枠": total - 1, "準備方向行": 2}
        for role in ("T", "R"):
            row[role] = {"方向行": 2, "段階": {"0": 2}, "episode有効": 0, "k形成": 0, "k有効": 0, "取消": 0,
                         "k経過最小": None, "k経過最大": None}
        coverage[name] = row
    coverage["全66場"] = {"全枠": 2442, "準備枠": 4, "未準備枠": 2438, "準備方向行": 8,
                          **{role: {"方向行": 8, "段階": {"0": 8}, "episode有効": 0, "k形成": 0, "k有効": 0, "取消": 0,
                                    "k経過最小": None, "k経過最大": None} for role in ("T", "R")}}
    r["価格経路分布"] = coverage
    for group in coverage.values():
        for role in ("T", "R"):
            group[role].update(empty_episode_counts(group[role]["方向行"]))
    r["経路支持"] = {phase: {str(n["id"]): {"方向行": n["direction_rows"],
                         "T": empty_episode_counts(n["direction_rows"]), "R": empty_episode_counts(n["direction_rows"])}
                         for n in item["base"]["nodes"] if n["left"] == -1} for phase, item in c["models"].items()}
    r["検査"]["旧46特徴保存一致"] = 3404
    r["状態分布"] = {}
    for phase, item in c["models"].items():
        r["状態分布"][phase] = {}
        for name, part in item["base"]["training"]["partition"].items():
            n = part["direction_rows"]
            row = {"方向行": n, "unique枠": part["pair_unique"], "日数": part["days"], "場数": part["sessions"]}
            for role, flag in (("T",int(name[1])),("R",int(name[-1]))):
                row[role] = {"形成あり": n if flag else 0, "形成なし": 0 if flag else n, "取消あり": 0,
                    "rあり": 0, "kあり": 0, "k有効": 0, "形成ID数": n if flag else 0}
            r["状態分布"][phase][name] = row
    c["sources"] = [Path(__file__).resolve()]
    if c["metadata"][:18] != old_metadata:
        raise ValueError("人工18列prefix変更")
    return c


def empty_episode_counts(direction_rows: int) -> dict:
    """人工用にepisodeなしの全6統計を作る。

    引数: direction_rows(int)は人工の方向行数。
    返り値: dictは既知の未発生。実保存値の欠測を埋める関数ではない。
    """
    return {"episode数": 0, "episode最大反復": 0, "episodeなし": direction_rows,
            "k形成episode数": 0, "k有効episode数": 0, "期限失効観測": 0}


class RenderTests(unittest.TestCase):
    """46列・未知・分母と保存表示を人工で確認する。"""

    def test_documents(self) -> None:
        """人工全node・46列・55×9・リンクと同byteを検査する。

        引数: なし。
        返り値: None。正式MDを生成しない。
        """
        c = artificial_context()
        validate_result(c["result"])
        validate_episode_support(c["result"]["経路支持"], c["models"])
        validate_state_distribution(c["result"]["状態分布"], c["models"])
        before = deepcopy(c)
        a, b = documents(c), documents(c)
        self.assertEqual(a, b)
        self.assertEqual(before, c)
        virtual = {(STUDY / n).resolve() for n in ("README.md", "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
        for item in c["models"].values():
            virtual.update((item["path"].resolve(), item["base_path"].resolve()))
        self.assertGreater(validate_documents(a, virtual), 55)
        self.assertEqual(feature_table(c).count("| F"), 46)
        self.assertIn("F02 <= 0.12345678901234566", a["設定と結果.md"])
        self.assertIn("F02:I07:osc", a["設定と結果.md"])
        self.assertNotIn("構造上充足する", a["設定と結果.md"])
        self.assertIn("null（品質注意）", a["README.md"])
        self.assertIn("null（空葉）", a["設定と結果.md"])
        self.assertIn("最低4本", a["README.md"])
        self.assertIn("旧60S0/S1", a["README.md"])
        self.assertIn("独立した失効イベント数ではない", a["設定と結果.md"])
        self.assertIn("A1は主合計strict>0", a["設定と結果.md"])

    def test_projection_and_unknown(self) -> None:
        """44列投影・未知平均・scoreと円予測の分離を検査する。

        引数: なし。
        返り値: None。
        """
        model = artificial_context()["models"]["W20"]["base"]
        bad = deepcopy(model)
        bad["structure"]["child_feature_indices"] = list(range(45))
        with self.assertRaises(ValueError):
            validate_model(bad)
        bad = deepcopy(model)
        bad["nodes"][4]["recovery"]["pnl5"]["mean"] = 0
        with self.assertRaises(ValueError):
            validate_model(bad)
        bad = deepcopy(model)
        bad["nodes"][3]["score"] = bad["nodes"][3]["regression_value"]
        with self.assertRaises(ValueError):
            validate_model(bad)

    def test_coverage(self) -> None:
        """未発生は有効な記述、取消とk有効は別であることを確認する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context()["result"]["価格経路分布"]
        validate_coverage(c)
        c["時系列20場"]["T"].update(段階={"0": 1, "3": 1}, 取消=1, k形成=1, k有効=0, k経過最小=0.4, k経過最大=0.4)
        c["全66場"]["T"].update(段階={"0": 7, "3": 1}, 取消=1, k形成=1, k有効=0, k経過最小=0.4, k経過最大=0.4)
        c["時系列20場"]["T"].update(episode数=1, episode最大反復=1, episodeなし=1, k形成episode数=1)
        c["全66場"]["T"].update(episode数=1, episode最大反復=1, episodeなし=7, k形成episode数=1)
        validate_coverage(c)
        c["時系列20場"]["T"]["k有効"] = 1
        with self.assertRaises(ValueError):
            validate_coverage(c)

    def test_episode_repetition(self) -> None:
        """同じIDの三反復と、繰り返し見える失効記憶を別にする。

        引数: なし。
        返り値: None。支持や採否を変えない。
        """
        counts = {"episode数": 1, "episode最大反復": 3, "episodeなし": 1,
                  "k形成episode数": 1, "k有効episode数": 0, "期限失効観測": 4}
        validate_episode_counts(counts, 4)
        bad = deepcopy(counts)
        bad["episode最大反復"] = 1
        with self.assertRaises(ValueError):
            validate_episode_counts(bad, 4)
        context = artificial_context()
        context["result"]["経路支持"]["W20"]["3"]["方向行"] += 1
        with self.assertRaises(ValueError):
            validate_episode_support(context["result"]["経路支持"], context["models"])


    def test_state_distribution(self) -> None:
        """有効0の取消と未登録、有効1の未r/kを分けて表示する。

        引数: なし。
        返り値: None。人工の状態件数だけで分母と旗を検査する。
        """
        c = artificial_context()
        source = c["result"]["状態分布"]
        validate_state_distribution(source, c["models"])
        row = source["W20"]["T0_R0"]["T"]
        row.update(形成あり=20, 形成なし=100, 取消あり=20, rあり=10, kあり=8, k有効=0, 形成ID数=10)
        validate_state_distribution(source, c["models"])
        self.assertIn("r/k形成を保証しない", state_distribution_table(c))
        bad = deepcopy(source)
        bad["W20"]["T1_R0"]["T"]["取消あり"] = 1
        with self.assertRaises(ValueError):
            validate_state_distribution(bad, c["models"])
        bad = deepcopy(source)
        bad["W20"]["T0_R0"]["T"]["k有効"] = 1
        with self.assertRaises(ValueError):
            validate_state_distribution(bad, c["models"])
        model = deepcopy(c["models"]["W20"]["base"])
        model["nodes"][3]["method_support"] = True
        with self.assertRaises(ValueError):
            validate_model(model)

    def test_prior46_fingerprints(self) -> None:
        """旧46の六指紋と18/30/38保持・metadata一致を検査する。

        引数: なし。
        返り値: None。人工の旧モデルを使い、本物モデルを開かない。
        """
        model = artificial_context()["models"]["W20"]["base"]
        keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
        prior = {"feature_meta": deepcopy(model["feature_meta"]), "training": {key: "人工" + key for key in keys}}
        model["training"]["base46_fingerprints"] = deepcopy(prior["training"])
        for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints"):
            model["training"][key] = {"人工": key}
            prior["training"][key] = {"人工": key}
        validate_prior46(model, prior)
        model["training"]["base46_fingerprints"][keys[0]] = "別指紋"
        with self.assertRaises(ValueError):
            validate_prior46(model, prior)
        model["training"]["base46_fingerprints"] = {key: prior["training"][key] for key in keys}
        for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints"):
            saved = deepcopy(model["training"][key])
            model["training"][key] = {"人工": "別指紋"}
            with self.assertRaises(ValueError):
                validate_prior46(model, prior)
            model["training"][key] = saved
        prior["feature_meta"][0]["name"] = "別順序"
        with self.assertRaises(ValueError):
            validate_prior46(model, prior)


if __name__ == "__main__":
    main()
