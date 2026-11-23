"""57の保存価格経路・回帰木・実運用を再学習せず二つのMarkdownへ表示する。"""

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
STUDY = ROOT / "study/00057_再試験と再開後の価格進行"
OLD = ROOT / "study/00056_追尾回収を目的に技法を分岐"
MEASURED_STUDY = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
SHARED = ROOT / "scripts/回収目的分岐/レポート.py"
SPEC = importlib.util.spec_from_file_location("再試験の価格経路の固定56表示純補助", SHARED)
R56 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R56
SPEC.loader.exec_module(R56)
R55, V5 = R56.R55, R56.V5
POLICIES, NEW = ("G0", "G1", "N0", "N1"), ("N0", "N1")
PERIODS, PERIOD_NAMES, PHASES = R56.PERIODS, R56.PERIOD_NAMES, R56.PHASES
sha, read, fingerprint, table = R56.sha, R56.read, R56.fingerprint, R56.table
number, rate, qualification, link, money = R56.number, R56.rate, R56.qualification, R56.link, R56.money
CHILD_FEATURE_INDICES = [*range(17), *range(18, 30)]
EXTRA_FORMULAS = ("T最大到達段階0..3", "T episode有効0/1", "T確認k有効0/1", "T(判断time−k.confirm)/900・kなし-1",
                  "s×(現在C−T確認kのC)/現在ATR", "T既知最大終値進行−現在進行（共通ATR）",
                  "R最大到達段階0..4", "R episode有効0/1", "R確認k有効0/1", "R(判断time−k.confirm)/900・kなし-1",
                  "s×(現在C−R確認kのC)/現在ATR", "R既知最大終値進行−現在進行（共通ATR）")
FORMULAS = (*R55.G.FORMULAS, *EXTRA_FORMULAS)



def validate_result(result: dict) -> None:
    """新旧候補・固定期間・分母・nullとfitの用途を検査する。

    引数: result(dict)は57の保存結果。市場や教師の系列は開かない。
    返り値: None。不一致は例外にする。
    """
    if result.get("試行") != 57 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("57の候補又は既使用契約が不正")
    if type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 12 or (result["新分類器fit"], result["新独立計測"], result["新運用数"]) != (0, 0, 92):
        raise ValueError("回帰最大12・分類0・新独立計測0・新運用92の契約差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用・評価46場の区分差")
    if result["対照参照"] != {"候補": ["G0", "G1"], "元試行": 56, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("対照は固定56G0/G1保存値だけ")
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
    for p in ("G0", "G1"):
        if result["候補"][p] != old["候補"][p] or result["役割別入口"][p] != old["役割別入口"][p]:
            raise ValueError("固定56の対照集計差")
    for k in ("評価場", "学習専用場", "準備比較", "独立測定"):
        if result[k] != old[k]:
            raise ValueError("固定56の期間・準備・測定参照差:" + k)
    if result["対照モデル"] != old["モデル"]:
        raise ValueError("固定56の対照モデル差")
    measured = result["独立測定参照"]
    if measured != old["独立測定参照"]:
        raise ValueError("固定55独立測定参照のパス又はSHA差")
    calibrations = {x["phase"]: x for x in result["回収集計"]}
    models, paths, metadata = {}, [], None
    for entry in result["モデル"]:
        phase = entry["phase"]
        if phase not in PHASES or phase in models or entry["id"] != "N0_" + phase:
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
        if model["feature_meta"] != metadata or len(metadata) != 30:
            raise ValueError("共通30特徴の順序差")
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
    if model["policy"] != "N0" or len(model["feature_meta"]) != 30 or len({n["id"] for n in model["nodes"]}) != len(model["nodes"]):
        raise ValueError("30特徴又はnode一意性の差")
    structure = model["structure"]
    if (structure["kind"], structure["child_depth"], structure["child_features"], structure["max_depth"], structure["fixed_mse_optimized"], structure["child_estimator"], structure["target"]) != ("fixed_root_and_direction", 2, 29, 4, False, "DecisionTreeRegressor", "pnl5"):
        raise ValueError("固定二段・子回帰目的の差")
    for parameters, depth in ((model["parameters"], 4), (model["subtree_parameters"], 2)):
        if (parameters["criterion"], parameters["max_depth"], parameters["min_samples_leaf"], parameters["random_state"]) != ("squared_error", depth, 60, 51) or "class_weight" in parameters:
            raise ValueError("回帰の固定設定差")
    if structure["child_feature_indices"] != CHILD_FEATURE_INDICES or structure["feature_count"] != 30:
        raise ValueError("F18を除く29列の子投影差")
    if any(n["feature"] == 17 for n in model["nodes"][3:] if n["left"] != -1):
        raise ValueError("子木はF18を再使用しない")
    ids = {n["id"] for n in model["nodes"]}
    for n in model["nodes"]:
        if n["left"] != -1 and (n["left"] not in ids or n["right"] not in ids or not 0 <= n["feature"] < 30 or not math.isfinite(n["threshold"])):
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


def validate_documents(output: dict[str, str], generated: set[Path]) -> int:
    """版5全55×9、30特徴、内部リンクを検査する。

    引数: output(dict[str,str])は二つの本文、generated(set[Path])は同時生成又は人工仮想参照。
    返り値: intはリンク確認数。
    """
    text = output["設定と結果.md"]
    ids = {m["id"] for m in V5.load_catalog()["methods"]}
    rows = [r for r in text.splitlines() if r.startswith("| ") and r.split("|")[1].strip() in ids]
    if len(rows) != 55 or any(len(r.split("|")) != 13 for r in rows):
        raise ValueError("版5の55×9が不足")
    if any("| " + f"F{i:02d}" + " |" not in text for i in range(1, 31)):
        raise ValueError("30特徴の表示漏れ")
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
    for key in ("全枠", "準備枠", "未準備枠", "準備方向行"):
        if coverage["全66場"][key] != sum(coverage[name][key] for name in groups if name != "全66場"):
            raise ValueError("用途別価格経路分布の全体復元差")


def settings(context: dict) -> list[dict]:
    """旧18と新T/R各6特徴を版5の技法・時間尺度へ対応させる。

    引数: context(dict)は保存30列metadata。
    返り値: list[dict]は使用セルの設定。旧対照へ新12列を使用したと記さない。
    """
    result = []
    for i, m in enumerate(context["metadata"]):
        result.append({"設定ID": f"S{i + 1:02d}", "手法ID": [m["method"]], "尺度ID": m["scale"].split("+"),
                       "短記": m["id"] + "=" + FORMULAS[i], "結果短記": "R01/R02/R03/R04" if i < 18 else "R03/R04",
                       "説明": "旧18列は56と不変" if i < 18 else "新しい価格順序の記述。独立した注文情報の票ではなく、未完了・取消も含めて入力"})
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02", "旧56G0/G1保存対照", "同46場の結果を再運用しない。"),
              (["M01"], ["m03", "m15", "m30"], "R03/R04", "Z→DI固定・29列回帰d2/MSE", "全30列からF18だけを除く29列を子へ投影し、node番号は元の特徴indexへ戻して保存。全深さ4・minleaf60・重み0.5・seed51。"),
              (["P10", "P05"], ["m03"], "R03/R04", "同じ凍結帯・反応5本の再試験とk後進行", "Tはb→r→k最低3足、Rはb→f→r→k最低4足。足内順は推測せず、取消後も最大段階と既知終値進行を記録。"),
              (["M01"], ["tick", "m03", "m15", "m30"], "R03/R04", "N0:障壁score最高側＋回収支持60枠6日10場", "回帰平均が高い側へ変更せず、score>=1/3・葉/技法/回収支持。次点救済なし。"),
              (["M01"], ["tick", "m03", "m15", "m30"], "R04", "N1:N0＋主回収平均strict正", "Decimal sum5>0。平均正を将来利益の保証としない。"),
              (["B01", "E02"], ["tick"], "R03/R04", "旧55独立測定4884方向再用・新計測0", "同じ教師集合へ当時の価格経路列を追加。未知を0補完せず、合計は同時実行戦略利益ではない。"),
              (["E02", "C06"], ["tick"], "R01/R02/R03/R04", "固定49O・現在益122円strict", "利益前も連続追尾、名目床、非緩和、pending保護凍結。新規ATR由来のD5..125固定。"),
              (["E01"], ["tick"], "R01/R02/R03/R04", "仮125/250先着・固定TPなし", "先着率・円予測・過去平均・実損益は別。"),
              (["C07"], ["m15"], "R01/R02/R03/R04", "当時公開・現在判断・鮮度", "15分が判断頻度、m30は3分10本OR。過去k価格へ約定を戻さない。")]
    for methods, scales, evaluations, short, description in extras:
        result.append({"設定ID": f"S{len(result) + 1:02d}", "手法ID": methods, "尺度ID": scales,
                       "短記": short, "結果短記": evaluations, "説明": description})
    return result


def feature_table(context: dict) -> str:
    """旧18列と新12列の全式・用途を省略せず記す。

    引数: context(dict)は30列metadata。
    返り値: strは全30特徴の表。
    """
    contents = [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i],
                 "旧18" if i < 18 else "T経路" if i < 24 else "R経路"] for i, m in enumerate(context["metadata"])]
    return ("## 全30特徴\n\n最初18列は旧56から不変。新T/R各6は現在判断までに公表済みの価格だけから作った記述で、独立した12票ではない。\n\n"
            + table(["ID", "特徴", "手法", "family", "尺度", "式・範囲", "用途"], contents)
            + "最大stageはT0..3/R0..4を取消後も保持する。episode有効とk有効を別列にし、高stageだから採用可とはしない。"
            "k未形成なら経過−1・進行/戻り0は既知の未発生値であり、特徴未準備とは別。k形成後は失効しても既知現在まで統計を更新し、再点火しない。"
            "age=(判断time−k.confirm)/900は正規化値で、900秒の新TTL条件ではない。進行と最大終値からの戻りは全て現在ATRを共通分母にする。\n\n")


def model_tables(context: dict, output: Path) -> str:
    """固定56の純表示から全新nodeを30列の元indexで表示する。

    引数: context(dict)は新3木、output(Path)は詳細MD。
    返り値: strは全path/閾値・支持・MSE・先着score・回帰平均。
    """
    text = R56.model_tables(context, output)
    return text.replace("子は先頭17列だけの深さ2", "子はF18(index17)を除く29列の深さ2").replace("旧54/55と共通", "旧54〜56と共通")


def recovery_tables(context: dict, output: Path) -> str:
    """全回収葉の表示純補助だけを再利用する。

    引数: context(dict)は3回収集計、output(Path)は詳細MD。
    返り値: strは全葉と空平均null。新学習・walk・回収集計はしない。
    """
    return R56.recovery_tables(context, output).replace("G1は主合計strict>0", "N1は主合計strict>0")


def coverage_table(result: dict) -> str:
    """取消・未登録・未完了を含む全定時の価格経路分布を表示する。

    引数: result(dict)は主が保存した価格経路分布。
    返り値: strは用途別分母とT/R段階・k形成/有効・取消・経過範囲。
    """
    denominators, contents = [], []
    for name, group in result["価格経路分布"].items():
        denominators.append([name, group["全枠"], group["準備枠"], group["未準備枠"], group["準備方向行"]])
        for role, maximum in (("T", 3), ("R", 4)):
            row = group[role]
            contents.append([name, role, row["方向行"], "/".join(str(row["段階"].get(str(i), 0)) for i in range(maximum + 1)),
                             row["episode有効"], row["k形成"], row["k有効"], row["取消"],
                             R56.full_number(row["k経過最小"]), R56.full_number(row["k経過最大"])])
    return ("## 全定時の価格経路分布\n\n純採用や250成功だけを抜き出した分布ではない。準備1枠に実方向±の2行、各方向にT/Rの2経路を記述する。"
            "同じ価格の反射や複数役割を独立標本として加算しない。全66場とその用途別部分集合も重ねて加算しない。\n\n"
            + table(["用途区間", "全予定枠", "準備枠", "未準備枠", "準備方向行"], denominators)
            + "stageは最大到達で取消後も保持。episode有効＋取消＋未登録で方向行を復元する。k形成と定時k有効も分離し、"
            "未形成の経過範囲はnull（0ではない）。経過欄の単位は(判断time−k.confirm)/900。\n\n"
            + table(["用途区間", "経路", "方向行", "stage0から最大の順", "episode有効", "k形成", "k有効", "取消", "k経過最小/900", "k経過最大/900"], contents))


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
             + status + "\n\n旧56G0/G1は保存対照。同じ凍結帯・反応5本に、順行b→r→kと反転b→f→r→kの段階・有効旗・k後進行を各6列加えた。"
             "旧18＋価格経路12＝30特徴。固定Z(index17)→DI四区分、F18を除く29列の子深さ2・全深さ4は回収pnl5のMSEで学習する。"
             + "新回帰器" + str(r["新回帰器fit"]) + "fit（最大12）、分類器fit0・新独立計測0・新混合運用92。"
             "順位は障壁score最高側を維持し、回帰予測の高い側へ変えない。N0は先着score>=1/3と葉/技法/回収支持60枠6日10場、N1は主回収平均strict正も必要。次点救済なし。\n\n")
    mechanics = ("## 価格順序・判断・執行の限定\n\nTはb→r→k最低3本、Rはb→f→r→k最低4本なので、反応5本内でk後に進行を観測できる足は短い。"
                 "取消・未登録・段階未完了を消さず、完成したkだけを母集団にしない。経路T/Rは仮説の名前であり、採用役割の順行/反転は現在DIで付く。"
                 "k有効を全新規の追加ANDとして強制した実験ではなく、木は未完了・取消も特徴として受け取る。\n\n"
                 "当時既知の同じ帯端Kに対して最初のb/f/rを固定し、取消を次段成立より優先する。別の足と公開key順序を確認し、同足高安の到達順を作らない。"
                 "r足の高安が前段の公開後に形成されたと保証する条件は追加していない。終値の観測順と足内形成順は別。"
                 "各定時の新しい窓へ前のepisodeを接ぎ替えず、取消後も最大到達を残す一方、再開始・再点火はしない。\n\n"
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
             "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧G0/G1各46＋新N0/N1各46＝184資源。\n\n"
             + link(OLD / "設定と結果.md", brief_path, "旧56の全閾値と回収") + " / "
             + link(ROOT / "docs/議論/回収を分割目的にした技法群の比較.md", brief_path, "価格順序へ進む問い") + " / "
             + link(ROOT / "docs/議論/外部再調査/突破失敗と再テストを順序で確認する.md", brief_path, "心理・順序の外部確認")
             + "\n\n保存監査：" + number(proof["照合項目数"]) + "照合・差" + number(proof["不一致数"]) + "。Viewer実行確認の範囲は監査JSONを正本とする。\n\n"
             "再表示はfit・予測walk・独立測定・回収集計・市場運用を再実行しない。\n\n"
             "~~~powershell\nC:/Python314/python.exe -X utf8 scripts/再試験の価格経路/レポート.py\n"
             "C:/Python314/python.exe -X utf8 scripts/再試験の価格経路/レポート.py --check\n~~~\n")
    settings_rows = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail_path, settings_rows).replace("未使用", "未使用・未検証")
    settings_table = table(["設定ID", "手法/尺度", "設定内容", "解釈と限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in settings_rows])
    sources = table(["出典", "SHA256"], [[link(p, detail_path), sha(p)] for p in context["sources"]])
    external = ("## 外部根拠と独自規約\n\n確認日2026-11-06、公式/本人の公開本文だけを確認。"
                "Fidelity Jonathan Lord/Robert Kwonの[公式講義](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Transcript_Chart-patterns_v2.pdf)"
                "（公開日不明、印刷12〜21頁）は既読の再点検。再試験を待つ確認の代償、撤退と反対新規を分ける説明で、再試験が来ない場合もある。"
                "[Grimes本人のS&P500記事](https://www.adamhgrimes.com/this-is-how-breakouts-work-lessons-from-the-sp-500/)（2020-07-20、本文A/B/C）は、"
                "下落可能性から即売りせず、その後の再取得を見て売り仮説を棄却した事例。同じ著者の既存分類と重複し、新しいNK統計の発見ではない。\n\n"
                "b/f/r/k別足・5本窓・±5pt・終値突破・取消線・15分定時への搬送は独自の機械規約。原典がこれらを処方したとはしない。"
                "b/f/rは非注文の記述段階で、架空の失敗費用を課さない。一方、別の突破時参加戦略との比較なら先行した失敗取引の費用を消せない。"
                "今回の旧対照は56保存運用であって、その突破時参加戦略を新たに再現したものではない。両資料にNK場内・125/250先着70%・本費用・活動制約を満たす実証はない。\n\n")
    brief = "# 00057：再試験と再開後の価格進行\n\n" + intro + "## 入口先着\n\n" + entrance + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    detail = ("# 00057：設定と結果\n\n" + intro + "R01=旧G0、R02=旧G1、R03=N0、R04=N1。\n\n"
              + "## 手法×尺度・版5全文\n\n55手法×9尺度を全件保持。未使用・未検証をデータ不足や対象外と取り替えず、複合成績を個別指標の効果としない。\n\n"
              + matrix + feature_table(context) + "## 設定明細\n\n" + settings_table + coverage_table(r)
              + model_tables(context, detail_path) + recovery_tables(context, detail_path)
              + "## 全候補の入口先着\n\n" + entrance + "## 全候補の混合運用\n\n" + operation + detail_tables(r) + mechanics + external
              + "## 検査と版\n\n旧教師一致：" + json.dumps(r["旧教師一致"], ensure_ascii=False)
              + "。教師集合一致：" + json.dumps(r["教師集合一致"], ensure_ascii=False) + "。保存検査：" + json.dumps(r["検査"], ensure_ascii=False)
              + "。独立測定参照：" + json.dumps(r["独立測定参照"], ensure_ascii=False)
              + "。表示器は旧測定gzipを開かず、小型参照と新旧監査の証明へ接続する。\n\n"
              + "## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief_path, detail_path, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detail}


# ----------------------------------------
# 正式結果・教師を開かない表示検査。


def artificial_context() -> dict:
    """固定56の人工文脈だけを30列・N政策へ写す。

    引数: なし。
    返り値: dictは人工の小型保存schema。旧moduleや入力を変更しない。
    """
    c = deepcopy(R56.artificial_context())
    r, old_metadata = c["result"], deepcopy(c["metadata"])
    mapping = {"C0": "G0", "R0": "G1", "G0": "N0", "G1": "N1"}
    for field in ("候補", "役割別入口", "判断理由"):
        r[field] = {mapping[p]: value for p, value in r[field].items()}
    r["試行"] = 57
    r["対照参照"] = {"候補": ["G0", "G1"], "元試行": 56, "同じ評価46場": True, "市場再生": False}
    for i in range(18, 30):
        c["metadata"].append({"id": f"F{i + 1:02d}", "name": "人工" + ("T" if i < 24 else "R") + str(i),
                              "method": "P05" if i in (22, 28) else "P10", "family": "price", "scale": "m03"})
    for phase, item in c["models"].items():
        m = item["base"]
        m["policy"], m["model_id"] = "N0", "N0_" + phase
        m["feature_meta"] = c["metadata"]
        m["structure"].update(child_features=29, child_feature_indices=CHILD_FEATURE_INDICES, feature_count=30)
        m["nodes"][5]["feature"] = 28
        for node in m["nodes"]:
            for p in node["path"]:
                if p["node"] == 5:
                    p["feature_id"] = "F29"
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
    c["sources"] = [Path(__file__).resolve()]
    if c["metadata"][:18] != old_metadata:
        raise ValueError("人工18列prefix変更")
    return c


class RenderTests(unittest.TestCase):
    """30列・未知・分母と保存表示を人工で確認する。"""

    def test_documents(self) -> None:
        """人工全node・30列・55×9・リンクと同byteを検査する。

        引数: なし。
        返り値: None。正式MDを生成しない。
        """
        c = artificial_context()
        validate_result(c["result"])
        before = deepcopy(c)
        a, b = documents(c), documents(c)
        self.assertEqual(a, b)
        self.assertEqual(before, c)
        virtual = {(STUDY / n).resolve() for n in ("README.md", "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
        for item in c["models"].values():
            virtual.update((item["path"].resolve(), item["base_path"].resolve()))
        self.assertGreater(validate_documents(a, virtual), 55)
        self.assertEqual(feature_table(c).count("| F"), 30)
        self.assertIn("F29 <= 0.12345678901234566", a["設定と結果.md"])
        self.assertIn("null（品質注意）", a["README.md"])
        self.assertIn("null（空葉）", a["設定と結果.md"])
        self.assertIn("最低4本", a["README.md"])

    def test_projection_and_unknown(self) -> None:
        """29列投影・未知平均・scoreと円予測の分離を検査する。

        引数: なし。
        返り値: None。
        """
        model = artificial_context()["models"]["W20"]["base"]
        bad = deepcopy(model)
        bad["structure"]["child_feature_indices"] = list(range(29))
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
        validate_coverage(c)
        c["時系列20場"]["T"]["k有効"] = 1
        with self.assertRaises(ValueError):
            validate_coverage(c)


if __name__ == "__main__":
    main()
