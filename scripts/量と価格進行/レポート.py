"""64の保存結果と六つの回帰木だけから二つのMarkdownを表示する。"""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal, localcontext
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00064_再試験の量と価格進行を別々に確認"
OLD = ROOT / "study/00063_方向と再開確認へ局面の強弱を追加"
SHARED = ROOT / "scripts/局面強弱の複合確認/レポート.py"
SPEC = importlib.util.spec_from_file_location("量価格64が参照する固定63表示純補助", SHARED)
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
R56, R55, V5 = BASE.R56, BASE.R55, BASE.V5
POLICIES, NEW, FIT = ("J0", "J1", "B0", "B1", "Q0", "Q1"), ("B0", "B1", "Q0", "Q1"), ("B0", "Q0")
COUNTS = {"B0": 54, "Q0": 60}
PERIODS, PERIOD_NAMES, PHASES = BASE.PERIODS, BASE.PERIOD_NAMES, BASE.PHASES
sha, read, fingerprint, table = BASE.sha, BASE.read, BASE.fingerprint, BASE.table
number, rate, qualification, link, money = BASE.number, BASE.rate, BASE.qualification, BASE.link, BASE.money
full_number = R56.full_number
FORMULAS = (*BASE.FORMULAS, "b足q/過去同時刻q平均・未知0", "s×(Cb−C[b−1])/現在ATR・未知0",
    "r足q/過去同時刻q平均・未知0", "s×(Cr−C[r−1])/現在ATR・未知0", "b量価格ペア有効0/1", "r量価格ペア有効0/1")
FINGERPRINT_KEYS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
INTERVALS = ("全66場", "学習専用20場", "時系列20場", "条件選択24場", "既使用2場")
EXTERNAL = ROOT / "docs/議論/外部再調査/再試験の量と価格進行を段階で分ける.md"

# ----------------------------------------
# 表示と共通分母の算術だけを固定表示器から再利用する。
def main_tables(result: dict) -> tuple[str, str]:
    """六候補の入口と一建玉の実運用を別表にする。

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

    引数: result(dict)は64結果。
    返り値: strは全六候補の詳細表。
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


# ----------------------------------------
# 保存契約の検査。教師・特徴の系列や学習器は読み込まない。


def validate_result(result: dict) -> None:
    """六候補の分母・品質null・目的と表示に必要な保存契約を確認する。

    引数: result(dict)は64の小型結果。
    返り値: None。正式データの再計算はせず、不整合は例外にする。
    """
    if result.get("試行") != 64 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("64の六候補と既使用区分が必要")
    if (type(result["新回帰器fit"]) is not int or not 0 <= result["新回帰器fit"] <= 12
            or (result["新分類器fit"], result["新独立計測"], result["新運用数"]) != (0, 0, 184)):
        raise ValueError("六木・最大12回帰fit・新184運用の契約差")
    if result["対照参照"] != {"候補": ["J0", "J1"], "元試行": 63, "同じ評価46場": True, "市場再生": False}:
        raise ValueError("旧63J0/J1は保存対照だけ")
    # ----------------------------------------
    # 固定表示器の共通分母検査へ二候補ずつ射影する。旧試行の来歴は上で別検査する。
    for pair in (("B0", "B1"), ("Q0", "Q1")):
        projected = deepcopy(result)
        mapping = {"J0": "K0", "J1": "K1", pair[0]: "J0", pair[1]: "J1"}
        projected.update(試行=63, 新運用数=92,
            対照参照={"候補": ["K0", "K1"], "元試行": 62, "同じ評価46場": True, "市場再生": False})
        for field in ("候補", "役割別入口"):
            projected[field] = {mapping[p]: result[field][p] for p in mapping}
        projected["判断理由"] = {mapping[p]: result["判断理由"][p] for p in pair}
        projected["採用"] = [mapping[p] for p in pair if p in result["採用"]]
        BASE.validate_result(projected)
    if result["採用"] != [p for p in NEW if all(result["候補"][p][t]["同時適格"] for t in PERIODS[:2])]:
        raise ValueError("新四候補の採用範囲差")
    validate_quantity_distribution(result["数量分布"], result["価格経路分布"])


def validate_quantity_distribution(distribution: dict, coverage: dict) -> None:
    """量価格ペアの方向行と基準足数を、枠や独立形成数と分けて確認する。

    引数: distribution(dict)は数量分布、coverage(dict)は価格経路分布。
    返り値: None。未知を既知0へ補完しない。
    """
    if set(distribution) != set(INTERVALS):
        raise ValueError("数量分布の五区分差")
    for name, group in distribution.items():
        n = group["方向行"]
        for key in ("全枠", "準備枠", "未準備枠"):
            if group[key] != coverage[name][key]:
                raise ValueError("数量と価格の準備枠差")
        if n != group["準備枠"] * 2 or not 0 <= group["両ペア有効方向"] <= n:
            raise ValueError("量価格ペアの方向行差")
        for stage in ("b", "r"):
            row = group[stage]
            if not 0 <= row["既知0量"] <= row["ペア有効"] <= row["段階あり"] <= n:
                raise ValueError("量の段階・有効・既知0の分母差")
            if sum(row["理由"].values()) != n or any(type(v) is not int or v < 0 for v in row["理由"].values()):
                raise ValueError("量ペア理由の全方向行復元差")
            if sum(row["基準足数"].values()) > row["段階あり"]:
                raise ValueError("基準足数は基準を保存した段階の反復観測数")
            if any(not 0 <= int(k) <= 10 or type(v) is not int or v < 0 for k, v in row["基準足数"].items()):
                raise ValueError("量基準は直近10場内の足数")
        if any(group["両ペア有効方向"] > group[stage]["ペア有効"] for stage in ("b", "r")):
            raise ValueError("両有効は各段階有効の部分集合")
    for key in ("全枠", "準備枠", "未準備枠", "方向行", "両ペア有効方向"):
        if distribution["全66場"][key] != sum(distribution[n][key] for n in INTERVALS[1:]):
            raise ValueError("数量五区分の加算差")


def validate_model(model: dict) -> None:
    """DI一段固定根・政策別列数・全nodeの回収表示を検査する。

    引数: model(dict)はB0又はQ0の保存回帰木。
    返り値: None。保存閾値をたどる予測やfitは行わない。
    """
    policy = model["policy"]
    count = COUNTS.get(policy)
    if count is None or len(model["feature_meta"]) != count:
        raise ValueError("B0は54列、Q0は60列")
    if [m["id"] for m in model["feature_meta"]] != [f"F{i:02d}" for i in range(1, count + 1)]:
        raise ValueError("全特徴の順序差")
    for index, meta in enumerate(model["feature_meta"][54:], 54):
        price = index in (55, 57)
        if (meta["method"], meta["family"], meta["scale"]) != ("P05" if price else "V01", "price" if price else "volume", "m03"):
            raise ValueError("追加六列の手法・family・尺度差")
    structure = model["structure"]
    if (structure["kind"], structure["child_depth"], structure["child_features"], structure["max_depth"],
            structure["fixed_mse_optimized"], structure["child_estimator"], structure["target"]) != (
            "fixed_direction_only", 3, count - 1, 4, False, "DecisionTreeRegressor", "pnl5"):
        raise ValueError("DI固定一段と深さ3の回帰子が必要")
    if (structure["child_feature_indices"], structure["excluded_feature_indices"], structure["feature_count"]) != (list(range(1, count)), [0], count):
        raise ValueError("子はDIだけを除く53又は59列")
    if structure["fixed_nodes"] != [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}]:
        raise ValueError("固定nodeはDI根一つだけ")
    for parameters, depth in ((model["parameters"], 4), (model["subtree_parameters"], 3)):
        if (parameters["criterion"], parameters["max_depth"], parameters["min_samples_leaf"], parameters["random_state"]) != ("squared_error", depth, 60, 51):
            raise ValueError("回帰器の固定設定差")
    nodes = model["nodes"]
    if [n["id"] for n in nodes] != list(range(len(nodes))) or (nodes[0]["feature"], nodes[0]["threshold"]) != (0, 0):
        raise ValueError("一意連番nodeとF01固定根が必要")
    if set(model["training"]["partition"]) != {"D0", "D1"}:
        raise ValueError("DI非正と正の二子が必要")
    for direction in (0, 1):
        row = model["training"]["partition"][f"D{direction}"]
        if (row["d"], row["route"], row["policy"], row["excluded_feature_indices"], row["child_feature_indices"]) != (
                direction, "R" if direction == 0 else "T", policy, [0], list(range(1, count))):
            raise ValueError("政策別二方向子の投影差")
        expected_root = nodes[0]["right" if direction else "left"]
        if row["root"] != expected_root or row["direction_rows"] != nodes[expected_root]["direction_rows"]:
            raise ValueError("子の根と方向行帰属差")
    # ----------------------------------------
    # 数値の共通契約だけを固定63の全node検査から再利用する。
    for node in nodes:
        if node["left"] != -1 and (node["left"] not in range(len(nodes)) or node["right"] not in range(len(nodes))
                or not 0 <= node["feature"] < count or not math.isfinite(node["threshold"])):
            raise ValueError("node参照又は分岐値が不正")
        if node["id"] and node["left"] != -1 and node["feature"] == 0:
            raise ValueError("子は固定DIを再使用しない")
        n = node["direction_rows"]
        if node["impurity_kind"] != "squared_error" or node["total_weight"] != n * .5:
            raise ValueError("node目的と重み差")
        if (node["score"] is None) != (n == 0) or n and node["score"] != node["success_weight"] / node["total_weight"]:
            raise ValueError("障壁scoreと回帰平均は別値")
        families = {model["feature_meta"][p["feature"]]["family"] for p in node["path"]}
        if set(node["families"]) != families or node["method_support"] != (len(families) >= 2 and bool(families & {"trend", "osc"})):
            raise ValueError("DIだけでは技法資格は自動充足しない")
        if node["data_absent"] != (n == 0):
            raise ValueError("空nodeの未知表示差")
        for key in ("pnl0", "pnl5", "pnl10"):
            row = node["recovery"][key]
            value = Decimal(row["sum"])
            if not value.is_finite():
                raise ValueError("回収合計は有限十進数が必要")
            if not n:
                if value != 0 or row["mean"] is not None or row["mean_decimal"] is not None:
                    raise ValueError("空node平均はnull")
            else:
                with localcontext() as decimal_context:
                    decimal_context.prec = 80
                    mean = value / n
                if row["mean"] != float(mean) or Decimal(row["mean_decimal"]) != mean:
                    raise ValueError("回収平均の十進合計との接続差")
        if node["recovery_positive"] is not (Decimal(node["recovery"]["pnl5"]["sum"]) > 0 if n else None):
            raise ValueError("回収strict正又は未知の差")
        if not n:
            if any(node[k] is not None for k in ("regression_value", "impurity", "recovery_mse_decimal")):
                raise ValueError("空node予測・MSEはnull")
        elif not math.isclose(node["regression_value"], node["recovery"]["pnl5"]["mean"], abs_tol=1e-10, rel_tol=1e-12):
            raise ValueError("生回帰平均の許容差外")


def validate_prior54(model: dict, prior: dict) -> None:
    """旧54射影六指紋と既存射影を、新canonicalとは分離して検査する。

    引数: model(dict)は新B/Q木、prior(dict)は旧63同phase木。
    返り値: None。予測・再学習はしない。
    """
    if model["feature_meta"][:54] != prior["feature_meta"] or len(prior["feature_meta"]) != 54:
        raise ValueError("旧54 metadataの順序差")
    expected = {key: prior["training"][key] for key in FINGERPRINT_KEYS}
    if model["training"]["base54_fingerprints"] != expected:
        raise ValueError("旧54教師六指紋差")
    if model["policy"] == "B0" and any(model["training"][key] != expected[key] for key in FINGERPRINT_KEYS):
        raise ValueError("基準B54のcanonical差")
    for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints"):
        if model["training"][key] != prior["training"][key]:
            raise ValueError("既存射影の指紋差:" + key)


def validate_episode_support(support: dict, models: dict) -> None:
    """六モデルIDごとの葉帰属を方向行で検査する。

    引数: support(dict)は経路支持、models(dict)はID別新六木。
    返り値: None。同形成の反復を新機会や支持gateへ変えない。
    """
    if set(support) != set(models):
        raise ValueError("経路支持はphaseではなく六モデルID別")
    for identity, item in models.items():
        nodes = {str(n["id"]): n for n in item["base"]["nodes"] if n["left"] == -1}
        if set(support[identity]) != set(nodes):
            raise ValueError("空葉を含む経路支持の葉集合差")
        for key, row in support[identity].items():
            if row["方向行"] != nodes[key]["direction_rows"]:
                raise ValueError("経路支持の方向行差")
            for role in ("T", "R"):
                BASE.validate_episode_counts(row[role], row["方向行"])


def context_for() -> dict:
    """主実行と監査成功後に、小型正本と六木・六回収集計だけを読む。

    引数: なし。
    返り値: dictは表示文脈。原板・詳細gzip・独立測定・教師系列を開かない。
    """
    required = [STUDY / n for n in ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("主実行と保存監査が完了してから表示してください")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if result["検査"]["旧54射影一致"] != 2442 or result["検査"]["旧63特徴保存一致"] != 3404:
        raise ValueError("旧54全辞書の2442枠・旧63評価3404方向一致が必要")
    if (result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True
            or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0])):
        raise ValueError("固定・監査・結果SHAの接続差")
    old = read(OLD / "結果.json")
    for policy in ("J0", "J1"):
        for key in ("候補", "役割別入口"):
            if result[key][policy] != old[key][policy]:
                raise ValueError("旧63保存対照の集計差")
    for key in ("評価場", "学習専用場", "準備比較", "独立測定", "独立測定参照", "状態分布", "局面分布", "価格経路分布"):
        if result[key] != old[key]:
            raise ValueError("旧63の期間・準備・共通診断差:" + key)
    if result["対照モデル"] != old["モデル"]:
        raise ValueError("旧63保存モデル参照差")
    if len(result["モデル"]) != 6 or len(result["回収集計"]) != 6:
        raise ValueError("新六木・六回収集計が必要")
    calibrations = {x["id"]: x for x in result["回収集計"]}
    models, paths, metadata = {}, [], None
    for entry in result["モデル"]:
        identity, policy, phase = entry["id"], entry["policy"], entry["phase"]
        if policy not in FIT or phase not in PHASES or identity != policy + "_" + phase or identity in models:
            raise ValueError("新木の政策・ID・phase差")
        cal_entry = calibrations[identity]
        if (cal_entry["policy"], cal_entry["phase"]) != (policy, phase):
            raise ValueError("回収metaの政策・phase差")
        path, cal_path = ((ROOT / e["path"]).resolve() for e in (entry, cal_entry))
        if any(not p.is_relative_to(STUDY) for p in (path, cal_path)) or sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("新木・回収集計の保存版差")
        model, cal = read(path), read(cal_path)
        validate_model(model)
        if (model["model_id"], model["policy"]) != (identity, policy):
            raise ValueError("木payloadのID・政策差")
        prior_entry = next(e for e in old["モデル"] if e["phase"] == phase)
        prior_path = ROOT / prior_entry["path"]
        if sha(prior_path) != prior_entry["SHA256"]:
            raise ValueError("旧63木の指紋差")
        validate_prior54(model, read(prior_path))
        R55.validate_calibration(cal, model)
        if (cal["policy"], cal["base_model_path"], cal["base_model_sha256"], cal["phase"]) != (policy, entry["path"], entry["SHA256"], phase):
            raise ValueError("木と回収payloadの結合差")
        for key, leaf in cal["leaves"].items():
            node = model["nodes"][int(key)]
            if node["direction_rows"] and node["recovery_positive"] != leaf["positive"]:
                raise ValueError("木と回収葉の正額差")
            for fee in (0, 5, 10):
                saved = node["recovery"][f"pnl{fee}"]
                if Decimal(saved["sum"]) != Decimal(leaf["sum_yen"][str(fee)]) or saved["mean"] != leaf["mean_yen"][str(fee)]:
                    raise ValueError("木と回収葉の合計・平均差")
        if policy == "Q0":
            if metadata is not None and metadata != model["feature_meta"]:
                raise ValueError("全phaseの新60 metadata差")
            metadata = model["feature_meta"]
        models[identity] = {"entry": entry, "base": model, "calibration": cal, "path": cal_path, "base_path": path}
        paths.extend((path, cal_path, prior_path))
    if set(models) != {p + "_" + phase for p in FIT for phase in PHASES} or set(calibrations) != set(models):
        raise ValueError("B/Qそれぞれ三phaseが必要")
    if any(item["base"]["feature_meta"] != metadata[:len(item["base"]["feature_meta"])] for item in models.values()):
        raise ValueError("基準54と新60の共通prefix差")
    if sum(p["fit_performed"] for m in models.values() for p in m["base"]["training"]["partition"].values()) != result["新回帰器fit"]:
        raise ValueError("保存したfit数と全子の実施合計差")
    validate_episode_support(result["経路支持"], models)
    resources = read(required[-1])["resources"]
    if len(resources) != 276 or Counter(x["method_id"] for x in resources) != {p: 46 for p in POLICIES}:
        raise ValueError("旧92＋新184のViewer276資源差")
    if any(not (ROOT / x["pnl_path"]).is_file() for x in resources):
        raise ValueError("Viewer約定参照欠落")
    sources = [*required, *paths, Path(__file__), HERE / "README.md", HERE / "レポートの人工検査.py", HERE / "検証.py",
        HERE / "学習.py", HERE / "特徴.py", HERE / "特徴仕様.md", HERE / "保存検証.py", SHARED,
        R56.SHARED, R55.SHARED, ROOT / "scripts/レポート/カタログ版5.py", ROOT / "scripts/レポート/設定結果レポート.py",
        V5.CATALOG, V5.MASTER, OLD / "結果.json", OLD / "設定と結果.md", OLD / "保存物確認.json", EXTERNAL,
        ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md"]
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "models": models, "metadata": metadata,
        "sources": list(dict.fromkeys(sources))}


# ----------------------------------------
# 全node・回収表の表示純補助。

def model_tables(context: dict, output: Path) -> str:
    """新六回帰木の全閾値・node目的値・葉の得点と支持を表示する。

    引数: context(dict)はID別保存model、output(Path)は詳細MD。
    返り値: strは全nodeと全葉の表。回帰平均と障壁scoreを別列にする。
    """
    models, partitions, nodes, objectives = [], [], [], []
    for phase, item in context["models"].items():
        model = item["base"]
        models.append([phase, link(item["base_path"], output, model["model_id"]), len(model["nodes"]),
                       len(item["entry"]["学習場"]), len(item["entry"]["評価場"]), "squared_error", "pnl5円"])
        for key, group in sorted(model["training"]["partition"].items()):
            partitions.append([phase, key, group["direction_rows"], group["pair_unique"], group["days"], group["sessions"],
                               group["root"], group["node_count"], "実施" if group["fit_performed"] else "未実施・未知枝"])
        for n in sorted(model["nodes"], key=lambda x: x["id"]):
            terminal = n["left"] == n["right"] == -1
            split = "葉" if terminal else model["feature_meta"][n["feature"]]["id"] + " <= " + format(n["threshold"], ".17g")
            path = " ∧ ".join(p["feature_id"] + " " + p["comparison"] + " " + format(p["threshold"], ".17g") for p in n["path"]) or "根"
            nodes.append([phase, n["id"], len(n["path"]), split + ("（固定）" if n["id"] == 0 else ""),
                          f'{n["left"]}/{n["right"]}', path, n["direction_rows"], n["total_weight"],
                          f'{n["unique_slots"]}/{n["days"]}/{n["sessions"]}',
                          full_number(n["score"]), full_number(n["barrier_gini"]),
                          qualification(n["leaf_support"]), "/".join(n["families"]), qualification(n["method_support"])])
            objectives.append([phase, n["id"], full_number(n["regression_value"]),
                               n["recovery"]["pnl5"]["mean_decimal"] if n["direction_rows"] else "null（未知）",
                               n["recovery"]["pnl5"]["sum"], "null（未知）" if n["recovery_positive"] is None else qualification(n["recovery_positive"]),
                               full_number(n["impurity"]), n["recovery_mse_decimal"] if n["direction_rows"] else "null（未知）"])
    return ("## 六回帰木の全分岐と目的値\n\n固定根はfloat32 F01(index0)<=0の一段だけ。B0は旧54列のDI以外53列、Q0は新60列のDI以外59列を子で使う。"
            "子深さ3・全深さ4、minleaf60・方向重み0.5・seed51。固定根はMSE最適分割ではない。"
            "B0/Q0各3木、2方向子で最大12fit。B1/Q1は同じ木を使い別fitしない。"
            "子の目的はpnl5のsquared_error、順位は障壁score最高側で、円予測の高い側へ変えない。\n\n"
            + table(["phase", "モデル", "node数", "過去場", "評価場", "子の目的", "教師単位"], models)
            + table(["phase", "固定区分", "方向行", "unique枠", "日", "場", "子root", "子node数", "回帰fit"], partitions)
            + "全nodeを載せ、閾値は保存floatの17桁。MSEは円の二乗で、固定段も使用教師のばらつきを記録する。"
            "未知葉のscore/平均はnullで、0成功・0円ではない。固定根はtrendだけで技法資格は自動充足しない。子pathを含めfamily2以上かつtrend又はoscが必要。\n\n"
            "DI固定段の左はfloat32 F01<=0で同値・float32零化も含む。評価時の背景DI同値は最終WAITで、左枝を全て逆向きと呼ばない。\n\n"
            + table(["phase", "node", "深さ", "分岐（左<=/右>）", "左/右", "全path", "方向行", "重み和",
                     "unique/日/場", "障壁score", "障壁gini参考", "葉支持", "path family", "技法資格"], nodes)
            + "生回帰予測と生MSEは学習器のfloat値、Decimal欄は80桁算術の表示値。平均はabs1e-10/rel1e-12、"
            "MSEはabs1e-8＋1e-10×max(1,E[pnl5²])だけを監査で許容し、閾値・先着score・支持・正額符号・採否へ転用しない。"
            "空nodeの回帰正額は未知null、後段の校正positive=Falseは不適格という意味で別に記す。\n\n"
            + table(["phase", "node", "生回帰予測5円", "Decimal平均5円", "合計5円", "主合計strict正", "生MSE円²", "Decimal MSE円²"], objectives))

def recovery_tables(context: dict, output: Path) -> str:
    """新木へ結合した過去回収の全葉を空葉込みで表示する。

    引数: context(dict)は六回収集計、output(Path)は詳細MD。
    返り値: strはpair除外と全葉の回収支持・平均表。
    """
    phases, leaves, excluded = [], [], []
    for phase, item in context["models"].items():
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
            "各方向重み0.5は共通、平均は十進純額合計/方向行数。B1/Q1は主合計strict>0、表示丸めを採否へ使わない。\n\n"
            + table(["phase", "保存集計", "過去場", "評価場", "旧方向教師", "入力pair", "使用pair", "除外pair", "使用方向行", "評価開始秒"], phases)
            + "独立測定の同時に持てない重複建玉を含む合計であり、実行可能な一戦略の利益ではない。\n\n"
            + table(["phase", "leaf", "方向行", "unique枠", "日/場", "合計円0/5/10", "平均円0/5/10", "回収支持", "主合計>0", "最大教師終了秒"], leaves)
            + table(["phase", "除外pairの状態", "pair数"], excluded))


def settings(context: dict) -> list[dict]:
    """全60列と新旧構造・執行条件を版5の使用セルへ対応させる。

    引数: context(dict)は全60metadataを持つ表示文脈。
    返り値: list[dict]は設定IDと複合評価ID。指標単独の成績とはしない。
    """
    result = []
    for i, meta in enumerate(context["metadata"]):
        result.append({"設定ID": f"S{i + 1:02d}", "手法ID": [meta["method"]], "尺度ID": meta["scale"].split("+"),
            "短記": meta["id"] + "=" + FORMULAS[i], "結果短記": "R01/R02/R03/R04/R05/R06" if i < 54 else "R05/R06",
            "説明": "旧J・新Bの54列と新Q60列を分ける。追加未知は量価格両0＋共同mask0、旧準備を落とさない。"})
    extras = [(["M01"], ["m03", "m15", "m30"], "R01/R02", "旧63J0/J1保存対照", "旧92運用を再生しない。DI→対応kの旧固定根を持つ。"),
        (["M01"], ["m03", "m15", "m30"], "R03/R04", "B0/B1:旧54・DI一段固定・子53列深さ3", "旧J→Bはk固定解除、子容量変更、技法資格の自動充足消失も含み、情報追加単独の比較ではない。"),
        (["M01", "V01", "P05"], ["m03", "m15", "m30"], "R05/R06", "Q0/Q1:新60・同DI根・子59列深さ3", "B→Qが同じ構造・教師・出口で6列を追加する比較。量だけで方向を選ばない。"),
        (["V01"], ["m03"], "R05/R06", "同時刻RVOL:直近10完了同種同限月場・完全q5場以上・平均正", "同index。欠測で11場目以前へ延長せず、当場と未来場を分母に入れない。祝日別層化なし。"),
        (["P10", "P05"], ["m03"], "R03/R04/R05/R06", "既知b/rを量と一足価格進行へ対応", "float32 F01正はT、非正はR。量価格共同maskは段階なしと既知0を分ける。r必須gateではない。"),
        (["M01"], ["tick", "m03", "m15", "m30"], "R03/R04/R05/R06", "最高障壁score側＋score>=1/3・葉/技法/回収支持", "60枠6日10場、次点救済なし。B1/Q1だけDecimal主回収合計strict正。円予測で順位を変えない。"),
        (["B01", "E02"], ["tick"], "R03/R04/R05/R06", "旧55独立測定4884方向を再用・新計測0", "同時に持てない重複建玉合計はstrategy利益でない。未知回収を0補完しない。"),
        (["E02", "C06"], ["tick"], "R01/R02/R03/R04/R05/R06", "固定49O・現在費用後122円strict正起動", "新規D5..125固定、損失側も連続追尾、名目床、非緩和、pending保護凍結。"),
        (["E01"], ["tick"], "R01/R02/R03/R04/R05/R06", "仮125/250先着・固定250TPなし", "先着率・過去回収平均・回帰予測・実利益を区別する。"),
        (["C07"], ["m15"], "R01/R02/R03/R04/R05/R06", "全予定枠・現在公開・15分判断", "保有非待ち、待ち＋判定不能の保守上限50%以下。定時以前の発動価格へ約定を戻さない。")]
    for methods, scales, evaluations, short, description in extras:
        result.append({"設定ID": f"S{len(result) + 1:02d}", "手法ID": methods, "尺度ID": scales,
            "短記": short, "結果短記": evaluations, "説明": description})
    return result


def feature_table(context: dict) -> str:
    """基準54と新60の差を保ち、全特徴式と欠測規約を表示する。

    引数: context(dict)は60列metadata。
    返り値: strは全60列の表と共通価格機械の限定。
    """
    rows = [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i],
        "旧J/新B/新Q共通" if i < 54 else "新Qのみ追加"] for i, m in enumerate(context["metadata"])]
    return ("## 全60特徴と基準54射影\n\n旧J0/J1・基準B0/B1は全54列、新Q0/Q1はその54列＋量と一足価格進行と共同maskの6列。"
        "旧54のreadyと教師pairを維持する。旧F47..54の数値未知0＋個別maskと、新F55..60の量価格共同maskを区別する。\n\n"
        + table(["ID", "特徴", "手法", "family", "尺度", "式・範囲", "使用候補"], rows)
        + "F55/F57の観測qは配信累積差分由来で、約定契約数の完全収録や新規/返済の区別を保証しない。"
        "b/rの直前公開完全隣接足との一足終値差を、現在判断のATRで正規化する。b→r区間変化でもイベント時点ATRでもない。"
        "量と価格が揃うときだけ2数値と共同mask1を渡し、不成立は両0＋mask0。完全q0と正基準はRVOL0という既知値。"
        "基準足5本以上でも量の比較可能性や心理の実測を保証しない。祝日・イベント別の補正は未実施。\n\n"
        "b/rは候補側float32 F01>0ならT、非正ならRから取る。これは特徴投影で、DIの生差から付く実運用役割と別。"
        "同値やfloat32零化は根の左に入り得るが、最終の背景DI同値WAITは保持する。"
        "価格T/Rはb→r→k／b→f→r→kの機械仮説。F18の局所Zと、bで保持するKは別の水準である。"
        "最大stage・episode有効・k有効を別に持ち、未完了や取消も残す。k形成後は取消後もTTL又は置換まで既知現在の統計を更新し、有効旗を復活させない。"
        "ageは(判断time−k.confirm)/900で新TTLではない。寿命はb.confirm+3600、60分を定時4枠と同一視しない。\n\n"
        "登録へ至る十差分はb−10..bの11終値で、推進波全体の完全な検出ではない。r前のpはr時点の先頭極値に固定し、r後の峰へ更新しない。"
        "rなしの対応値0、r当足の経過0も既知の状態としてmaskと分ける。全て終値から作る記述で、BBO約定位置や将来残存値幅ではない。"
        "価格・DI・FastK・ADX・BB・ATRは重なり、追加量も2段階の6独立票ではない。\n\n")


def quantity_table(result: dict) -> str:
    """量の段階・有効・既知0と理由を、基準足数の反復観測と分ける。

    引数: result(dict)は保存数量分布。
    返り値: strは五区分の枠とb/r方向行表。
    """
    totals, stages, reasons, baselines = [], [], [], []
    for name, group in result["数量分布"].items():
        totals.append([name, *(group[k] for k in ("全枠", "準備枠", "未準備枠", "方向行", "両ペア有効方向"))])
        for stage in ("b", "r"):
            row = group[stage]
            stages.append([name, stage, group["方向行"], row["段階あり"], row["ペア有効"], row["既知0量"]])
            reasons.extend([name, stage, key, value] for key, value in sorted(row["理由"].items()))
            baselines.extend([name, stage, key, value] for key, value in sorted(row["基準足数"].items(), key=lambda x: int(x[0])))
    return ("## 数量と価格ペアの被覆\n\n準備1枠から候補±の2方向行を記述し、選択したT/Rのbとrを別に集計する。"
        "基準足数は各段階へ保存された分母サンプル数で、独立形成数でも新規機会数でもない。"
        "同じb/rが複数定時や両候補側で反復し得る。全66場と部分集合、b/r、unique episodeは加算しない。\n\n"
        + table(["区間", "全枠", "旧準備枠", "未準備枠", "方向行", "b/r両有効方向"], totals)
        + table(["区間", "段階", "方向行", "段階あり", "量価格ペア有効", "有効かつRVOL0"], stages)
        + table(["区間", "段階", "保存理由", "方向行"], reasons)
        + table(["区間", "段階", "基準の完全足数", "観測方向行"], baselines))


def episode_support_table(context: dict) -> str:
    """六モデルの全葉に、同形成の反復と方向行分母を表示する。

    引数: context(dict)はID別経路支持。
    返り値: strは診断表。支持や学習重みを変更しない。
    """
    rows = []
    for identity, groups in context["result"]["経路支持"].items():
        for key, group in sorted(groups.items(), key=lambda x: int(x[0])):
            for role in ("T", "R"):
                row = group[role]
                rows.append([identity, key, role, group["方向行"], *(row[k] for k in (
                    "episode数", "episode最大反復", "episodeなし", "k形成episode数", "k有効episode数", "期限失効観測"))])
    return ("## 六モデルの葉別episode反復\n\n使用教師全方向行が分母。同じ形成IDは別の葉や時点にも到達し得るためuniqueは非加算。"
        "期限失効観測はlast_expiredが残る行数で、独立失効イベント数ではない。支持60枠をepisode数に変更しない。\n\n"
        + table(["modelid", "leaf", "経路", "方向行", "unique episode", "最大反復", "IDなし", "k形成episode", "k有効episode", "期限失効観測"], rows))


def path_qualification_table(context: dict) -> str:
    """実pathの技法資格と、新6列が共同maskだけかを明示する。

    引数: context(dict)は新六木。
    返り値: strは全葉の技法と量入力の種類。新しい採否には使わない。
    """
    rows = []
    for identity, item in context["models"].items():
        model = item["base"]
        for node in model["nodes"]:
            if node["left"] != -1:
                continue
            indexes = sorted({p["feature"] for p in node["path"]})
            added = [i for i in indexes if i >= 54]
            category = "新6列なし" if not added else "新6列はmaskのみ" if set(added) <= {58, 59} else "量又は価格の数値列あり"
            rows.append([identity, node["id"], node["direction_rows"], "/".join(model["feature_meta"][i]["id"] for i in indexes),
                "/".join(node["families"]), qualification(node["method_support"]), category])
    return ("## pathの複数技法資格と新量列の種類\n\n固定根はtrendだけ。子でprice・vol・osc・volume等の別familyを選んで従来資格が成立する。"
        "新maskのfamilyもvolumeなので、maskだけで資格を満たし得るが、実量の大小や価格再開を確認した意味ではない。"
        "この分類は表示診断で、gateを変更しない。\n\n"
        + table(["modelid", "leaf", "方向行", "実path列", "全family", "技法資格", "新6列の種類"], rows))


def documents(context: dict) -> dict[str, str]:
    """小型保存正本から概要と全設定を同じ数値で構成する。

    引数: context(dict)は正式又は人工の表示文脈。
    返り値: dict[str,str]は二本文。ファイルの書込や数値再計算はしない。
    """
    result, proof = context["result"], context["proof"]
    brief_path, detail_path = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operation = main_tables(result)
    status = "新候補の採用なし。両期の先着70・支持・費用・活動の同時目標は未達。" if not result["採用"] else "保存採用候補：" + "、".join(result["採用"]) + "。未見市場での保証ではない。"
    intro = ("全66場は既使用。初20場は学習専用、学習欄は後20場の時系列検査。選択24場と既使用後続2場はF40固定で再fitしない。\n\n"
        + status + "\n\n旧63J0/J1は保存対照。B0/B1は旧54特徴で固定根をDI一段にし、Q0/Q1は同じ構造へ量価格6列を加える。"
        "旧J→Bではk固定解除・子深さ2→3・自動技法資格の消失も変わるため、量の効果とは呼ばない。B→Qが同構造の情報追加比較である。"
        "根はfloat32 F01<=0、非正D0/正D1の二子。BはDI以外53列、Qは59列・子深さ3、全深さ4。"
        "DI左枝には同値とfloat32零化を含み、最終raw DI同値WAITは保持する。\n\n"
        + f'新回帰器{result["新回帰器fit"]}fit（六木・最大12）、分類器fit0、新独立計測0、新運用184。'
        "B1/Q1は対応するB0/Q0の同じ木と回収集計を使う。目的は費用後pnl5のMSEだが、方向順位は障壁score最高側のまま。"
        "score>=1/3・葉支持・複数技法資格・過去回収60枠6日10場を要求し、B1/Q1だけDecimal主回収合計strict正も必要。"
        "次点救済なし。DI根だけでは複数技法を自動充足せず、新量maskだけのfamily資格も価格確認と同一視しない。\n\n")
    mechanics = ("## 価格段階・公開時計・連続保護\n\n量は方向票ではない。既存価格機械が保存したb/rへ、当時利用可能な観測qと直前隣接公開終値差を対応させる。"
        "過去同時刻基準は当場開始前に完了した同Day/Night・同限月の直近10場を先に選び、同indexの完全qが5場以上・平均正のときだけ算術する。"
        "q0は基準へ含め、欠測で11場目以前まで延長しない。祝日層化は未実施。価格側ATRだけは現在判断値である。\n\n"
        "Tはb→r→k、Rはb→f→r→kを別足・公開順で追い、未登録・未確認・取消も入力へ残す。最初のb/rを固定し、有効中に水準を置き換えない。"
        "寿命はb.confirm+3600で同秒を含め失効。取消足や最初の期限越え足を新bへ再使用せず、次足から検討する。"
        "k形成後は取消後もTTL又は置換まで既知現在の統計を更新し、有効旗を復活させない。終値観測順は足内高安の形成順を保証しない。\n\n"
        "判断はデイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。保有継続は非待ち、全予定枠分母で待ち＋判定不能の保守上限50%以下。"
        "現在正常BBOから1価格時計秒後の最初の正常気配へ新規要求し、TTL30秒。過去b/r/k価格に約定を戻さない。残り60分の新規停止は使わない。"
        "強制15:35/05:50・終了15:40/05:55。\n\n固定49O、micro1枚10円/pt、片道11円＋想定片道5ptで往復122円。"
        "新規時ATRの5pt切上げをD5..125へ制限し保有中固定。損失側も連続追尾し、現在返済気配の粗益−122円strict正で利益旗と最低名目新規床を起動する。"
        "非緩和、返済pending中のh/L/arm保護は凍結。固定250TPはない。費用0/10pt感応も同じ約定・起動122円を保持し、名目床を費用後同値と呼ばない。\n\n"
        "仮125/250先着率、回帰円予測、過去回収平均、混合一建玉の実損益は別である。旧55一枠測定の重複建玉合計は同時実行できるstrategy利益ではない。"
        "品質注意時は期間全体の確定額nullを保ち、観測額・役割別額を保証へ変えない。ラージBBO代理でmicro実板や受信時計を測定したものではない。\n\n")
    links = ("## 正本・閲覧・再表示\n\n" + " / ".join(link(STUDY / n, brief_path) for n in (
        "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(HERE / "README.md", brief_path, "コードと再現") + "\n\n"
        "[Viewer（ローカル起動時）](http://127.0.0.1:8092)。旧J0/J1各46＋新B0/B1/Q0/Q1各46＝276資源。\n\n"
        + link(OLD / "設定と結果.md", brief_path, "旧63全閾値と回収") + " / " + link(EXTERNAL, brief_path, "再試験の量と価格の外部確認")
        + " / " + link(ROOT / "docs/議論/入口の先着と追尾退出の順序を分ける.md", brief_path, "先着と追尾回収の区別")
        + f'\n\n保存監査：{number(proof["照合項目数"])}照合・差{number(proof["不一致数"])}。Viewerの確認範囲は監査JSONを正本とする。\n\n'
        "再表示はfit・予測walk・独立測定・市場運用を再実行しない。\n\n~~~powershell\n"
        "C:/Python314/python.exe -X utf8 scripts/量と価格進行/レポート.py\n"
        "C:/Python314/python.exe -X utf8 scripts/量と価格進行/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail_path, uses).replace("未使用", "未使用・未検証")
    uses_table = table(["設定ID", "手法/尺度", "設定内容", "解釈と限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    sources = table(["出典", "SHA256"], [[link(p, detail_path), sha(p)] for p in context["sources"]])
    state = BASE.state_distribution_table(context).replace("固定群", "診断群")
    state = "状態四群は旧DI→対象kの診断分類を保持したもので、新B/Qの木のpartitionはD0/D1の二群である。\n\n" + state
    external = ("## 原典と独自機械化の差\n\n確認日2026-11-06。"
        "[WyckoffSMI・Jim O’BrienのSpring Test解説](https://wyckoffsmi.com/testing-the-spring/)（2015-06-20本文）と"
        "[Bruce Fraser本人の例示](https://articles.stockcharts.com/article/articles-wyckoff-2016-05-springing-into-action/)（2016-05-06、AAPL/SCHW）を再読した。"
        "縮量の再試験と、その後の価格再開を別段階として読む一方、低量Springには再試験が必須でない例もある。既読の深掘りで、新発見や普遍的な量ANDではない。\n\n"
        "[Craig F. Schroederの先物向け論考](https://wyckoffsmi.com/wp-content/uploads/2022/06/A-Wyckoff-Approach-To-Futures.pdf)"
        "（Stocks & Commodities V10:2、61–66、1992年2月は発行元索引表示）も本文確認。価格幅・純進行と相対量を組み合わせる説明だが、"
        "後日確定量を当時へ遡及できず、tick volumeを約定契約数や板更新回数と同一視しない。これらは実務例・説明で、NK3分・先着70%や60分保持の統計保証ではない。\n\n"
        "本研究の同時刻10場/最低5場、b/r投影、一足価格差、共同mask、学習木とO49は独自規約。高量不進行から吸収・反転成立を直接断定せず、"
        "新規/返済や売り手枯渇は心理仮説に留める。低量でも価格が進む場合があり、量の増減だけで方向を決めない。"
        + link(EXTERNAL, detail_path, "読取範囲・既存14/36/42/43/47/48との重複と限界") + "を参照する。\n\n")
    brief = "# 00064：再試験の量と価格進行を別々に確認\n\n" + intro + "## 入口先着\n\n" + entrance + "## 混合一建玉の実運用\n\n" + operation + mechanics + links
    detail = ("# 00064：設定と結果\n\n" + intro + "R01=旧J0、R02=旧J1、R03=B0、R04=B1、R05=Q0、R06=Q1。\n\n"
        "## 手法×尺度・版5全文\n\n55手法×9尺度を全件保持。未使用・未検証とデータ不足・対象外を分け、複合成績を指標単独の効果にしない。\n\n"
        + matrix + feature_table(context) + "## 設定明細\n\n" + uses_table + BASE.coverage_table(result) + quantity_table(result)
        + model_tables(context, detail_path) + recovery_tables(context, detail_path) + path_qualification_table(context)
        + episode_support_table(context) + state
        + "次のF47..54局面分布は旧63から共有する診断で、64で新たに加えた量価格6列の準備とは別である。\n\n"
        + BASE.regime_distribution_table(result)
        + "## 全候補の入口先着\n\n" + entrance + "## 全候補の混合運用\n\n" + operation + detail_tables(result) + mechanics + external
        + "## 検査と版\n\n旧教師一致：" + json.dumps(result["旧教師一致"], ensure_ascii=False)
        + "。教師集合一致：" + json.dumps(result["教師集合一致"], ensure_ascii=False)
        + "。保存検査：" + json.dumps(result["検査"], ensure_ascii=False)
        + "。独立測定参照：" + json.dumps(result["独立測定参照"], ensure_ascii=False)
        + "。六木それぞれのbase54_fingerprints六キーを旧63全54正本へ照合し、base18/30/38/46も保持する。"
        "B54canonicalは旧63と一致、Q60canonicalは別で、列追加を教師集合や欠測除外の変更と混同しない。"
        "量の基準足数、stageの反復行、unique episode、非重複入口支持は異なる分母である。\n\n"
        + "## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief_path, detail_path, "概要とコマンド") + "\n")
    return {"README.md": brief, "設定と結果.md": detail}


def self_test() -> dict:
    """別ファイルの人工表示検査を呼び、正式記録用の件数を返す。

    引数: なし。
    返り値: dictは成功・テスト件数。失敗時は終了1、実入力は開かない。
    """
    spec = importlib.util.spec_from_file_location("量価格64表示の人工検査", HERE / "レポートの人工検査.py")
    tests = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tests
    spec.loader.exec_module(tests)
    return tests.run(sys.modules[__name__])


def main() -> None:
    """正式表示と人工表示検査をCLIで選ぶ。

    引数: なし。--checkと--self-testは排他的。
    返り値: None。正式生成は主・保存監査完了後のみ実行する。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False))
    else:
        print(json.dumps(render(args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
