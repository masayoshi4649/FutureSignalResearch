"""54の固定二段モデルと旧53の二対照を保存JSONだけから表示する。"""

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00054_方向と局所帯を先に分岐"
OLD = ROOT / "study/00053_局所帯の反応で先に分岐"
SHARED = ROOT / "scripts/局所帯分岐/レポート.py"
SPEC = importlib.util.spec_from_file_location("方向局面表示の固定53純ヘルパー", SHARED)
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)
V5 = G.V5
POLICIES, CONTROLS, NEW = ("B0", "F0", "D0"), ("B0", "F0"), ("D0",)
PERIODS, PERIOD_NAMES, PHASES = G.PERIODS, G.PERIOD_NAMES, G.PHASES
EVALUATIONS = {"B0": "R01", "F0": "R02", "D0": "R03"}
FORMULAS = G.FORMULAS
sha, read, fingerprint, table = G.sha, G.read, G.fingerprint, G.table
number, rate, qualification, confirmed, link = G.number, G.rate, G.qualification, G.confirmed, G.link


def validate_result(result: dict) -> None:
    """旧二対照と新一候補の評価分母・費用・活動を保存集計内で結ぶ。

    引数: result(dict)は54正式結果。
    返り値: None。不整合は拒否し、市場又は戦略を再計算しない。
    """
    if result.get("試行") != 54 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("54の候補/既使用契約が不整合")
    if len(result["評価場"]) != 46 or len(set(result["評価場"])) != 46 or len(result["学習専用場"]) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初期20場と運用46場が不整合")
    if result["対照参照"] != {"候補": list(CONTROLS), "元試行": 53, "同じ評価46場に保存値を再集計": True, "市場再生": False}:
        raise ValueError("対照は固定53B0/F0の保存値")
    for period, count in zip(PERIODS, (740, 888, 74)):
        ready = result["準備比較"][period]
        if ready["全予定枠"] != count or not 0 <= ready["共通履歴準備"] <= ready["旧特徴準備"] <= count:
            raise ValueError("予定枠/準備分母差")
        if ready["旧特徴準備"] - ready["共通履歴準備"] != ready["履歴追加で未準備"] or sum(ready["追加未準備理由"].values()) != ready["履歴追加で未準備"]:
            raise ValueError("準備除外分割差")
        if set(ready["買売Z分布"]) - {"00", "01", "10", "11"} or sum(ready["買売Z分布"].values()) != ready["共通履歴準備"]:
            raise ValueError("全ready枠のZ分布差")
        for policy in POLICIES:
            group = result["候補"][policy][period]
            e, o = group["入口"], group["運用"]
            if sum(e["結果別"].values()) != e["候補"] or e["候補"] - e["結果別"].get("未約定", 0) != e["約定"]:
                raise ValueError("純入口と仮約定分母差")
            if (e["率"] is None) != (e["約定"] == 0) or e["約定"] and not math.isclose(e["率"], e["250"] / e["約定"], abs_tol=1e-12, rel_tol=0):
                raise ValueError("主率の分母差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            if o["予定枠"] != count or sum(o["判断別"].values()) != count or (o["待ち数"], o["判定不能"], o["活動適格"], o["全枠判定可能"]) != (wait, invalid, (wait + invalid) * 2 <= count, invalid == 0):
                raise ValueError("活動の全予定枠分母差")
            if not math.isclose(o["待ち率保守上限"], (wait + invalid) / count, abs_tol=1e-12, rel_tol=0):
                raise ValueError("保守待ち率差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定の費用感応差")
                if o["品質注意場"] and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意時の確定null差")
            if group["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("総合資格差")
    if result["採用"] != (["D0"] if all(result["候補"]["D0"][p]["同時適格"] for p in PERIODS[:2]) else []):
        raise ValueError("新D0だけが採用対象")


def context_for(study: Path) -> dict:
    """正式結果・監査・旧6/新3モデルを同版へ接続する。

    引数: study(Path)は正式先。
    返り値: dictは小型保存物の文脈。市場・特徴・学習コードをimportしない。
    """
    required = [study / name for name in ("結果.json", "保存物確認.json", "固定.json", "検証計画.md", "条件.json", "一覧.resources.json")]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError("正式結果と監査の完成後だけ表示可能: " + str(path))
    result, proof, fixed = read(required[0]), read(required[1]), read(required[2])
    validate_result(result)
    old = read(OLD / "結果.json")
    if result["固定SHA256"] != sha(study / "固定.json") or proof.get("全件一致") is not True or proof.get("不一致数") != 0:
        raise ValueError("正式版又は保存監査が不整合")
    for key in ("評価場", "学習専用場", "準備比較", "価格SOURCE"):
        if result[key] != old[key]:
            raise ValueError("53から変更できない保存範囲: " + key)
    for policy in CONTROLS:
        if result["候補"][policy] != old["候補"][policy] or result["役割別入口"][policy] != old["役割別入口"][policy]:
            raise ValueError("旧53の完全保存対照差")
    if result["対照モデル"] != old["モデル"]:
        raise ValueError("対照6モデルmetadata差")
    all_sessions = result["学習専用場"] + result["評価場"]
    expected_phases = {"W20": (all_sessions[:20], all_sessions[20:30]), "W30": (all_sessions[:30], all_sessions[30:40]), "F40": (all_sessions[:40], all_sessions[40:])}
    models, controls, model_paths = {}, {}, []
    for entry in result["対照モデル"]:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(OLD) or not path.is_file() or sha(path) != entry["SHA256"] or entry["policy"] not in CONTROLS:
            raise ValueError("旧6モデルの参照差")
        model = read(path)
        if model["model_id"] != entry["id"] or entry["id"] in controls:
            raise ValueError("旧モデルID差")
        controls[entry["id"]] = {"entry": entry, "model": model, "path": path}
        model_paths.append(path)
    if set(controls) != {p + "_" + phase for p in CONTROLS for phase in PHASES}:
        raise ValueError("旧53の6モデルが必要")
    fixed_nodes = [{"id": 0, "feature": "F18", "index": 17, "threshold": 0.5},
        {"id": 1, "feature": "F01", "index": 0, "threshold": 0.0}, {"id": 2, "feature": "F01", "index": 0, "threshold": 0.0}]
    for entry in result["モデル"]:
        path = (ROOT / entry["path"]).resolve()
        identity, phase = entry["id"], entry["phase"]
        if not path.is_relative_to(study) or not path.is_file() or sha(path) != entry["SHA256"]:
            raise ValueError("新モデル参照差")
        model = read(path)
        if entry["policy"] != "D0" or phase not in PHASES or identity != "D0_" + phase or identity in models or (model["model_id"], model["policy"]) != (identity, "D0"):
            raise ValueError("新モデルID差")
        if (entry["学習場"], entry["評価場"]) != expected_phases[phase] or entry["特徴数"] != 18 or len(model["feature_meta"]) != 18:
            raise ValueError("新モデル時系列/18列契約差")
        training = model["training"]
        if training["period"]["evaluation_start"] != entry["評価開始"] or training["period"]["max_input_label_end_key"][0] >= entry["評価開始"]:
            raise ValueError("未来教師境界差")
        for control in CONTROLS:
            expected_keys = {"row_ids_sha256", "period_sha256"} | ({"input_rows_sha256", "used_rows_sha256"} if control == "F0" else set())
            matches = result["教師一致"][phase][control]
            prior = controls[control + "_" + phase]["model"]["training"]
            if set(matches) != expected_keys or any(v is not True for v in matches.values()) or any(training[k] != prior[k] for k in expected_keys):
                raise ValueError("旧53との教師指紋差")
        if model["feature_meta"] != controls["F0_" + phase]["model"]["feature_meta"] or model["feature_meta_sha256"] != fingerprint(model["feature_meta"]):
            raise ValueError("旧53と同じ18列metadataが必要")
        if model["structure"] != {"kind": "fixed_root_and_direction", "fixed_nodes": fixed_nodes, "child_depth": 2, "child_features": 17, "max_depth": 4, "fixed_gini_optimized": False}:
            raise ValueError("新固定二段の構造差")
        nodes, parts = model["nodes"], training["partition"]
        if [n["id"] for n in nodes] != list(range(len(nodes))) or max(len(n["path"]) for n in nodes) > 4 or model["parameters"]["max_depth"] != 4 or model["subtree_parameters"]["max_depth"] != 2:
            raise ValueError("全体ID/深さ差")
        if (nodes[0]["left"], nodes[0]["right"]) != (1, 2) or any((nodes[f["id"]]["feature"], nodes[f["id"]]["threshold"]) != (f["index"], f["threshold"]) for f in fixed_nodes) or any(n["feature"] >= 17 for n in nodes[3:]):
            raise ValueError("固定三node/17列子木差")
        if set(parts) != {f"Z{z}_a{a}" for z in (0, 1) for a in (0, 1)} or sum(p["direction_rows"] for p in parts.values()) != training["direction_rows"]:
            raise ValueError("四群分割差")
        for z in (0, 1):
            for a in (0, 1):
                p = parts[f"Z{z}_a{a}"]
                if (p["z"], p["a"], p["policy"], p["root"]) != (z, a, "D0", nodes[1 + z]["left" if a == 0 else "right"]) or p["fit_performed"] != (p["direction_rows"] > 0) or p["fit_parameters"] != model["subtree_parameters"]:
                    raise ValueError("四群の所属/fit接続差")
        for node in nodes:
            if node["data_absent"]:
                if node["direction_rows"] != 0 or node["score"] is not None or node["impurity"] is not None or (node["id"] >= 3 and (node["left"] != -1 or node["right"] != -1)):
                    raise ValueError("未知内部固定node/leafのnull差")
            elif not isinstance(node["score"], (int, float)) or not 0 <= node["score"] <= 1:
                raise ValueError("学習済みnode率差")
            if node["left"] == node["right"] == -1 and (not {"price", "trend"} <= set(node["families"]) or node["method_support"] is not True):
                raise ValueError("固定二段で技法条件を構造上満たす契約差")
        models[identity] = {"entry": entry, "model": model, "path": path}
        model_paths.append(path)
    if set(models) != {"D0_" + phase for phase in PHASES}:
        raise ValueError("新D0の3合成モデルが必要")
    metadata = models["D0_W20"]["model"]["feature_meta"]
    if any(item["model"]["feature_meta"] != metadata for item in models.values()):
        raise ValueError("新3モデルの特徴順差")
    # ----------------------------------------
    # 葉・局面の評価は新D0の元運用への帰属であり、再運用は行わない。
    expected = {(identity, n["id"], period) for identity, item in models.items() for n in item["model"]["nodes"]
        if n["left"] == n["right"] == -1 for period in PHASES[item["entry"]["phase"]][2]}
    observed = set()
    for row in result["葉別評価"]:
        key = row["model_id"], row["leaf"], row["period"]
        if key in observed or key not in expected or row["policy"] != "D0" or row["phase"] != models[row["model_id"]]["entry"]["phase"] or row["品質注意の範囲"] != "同じモデル評価期間全体。葉への帰属ではない":
            raise ValueError("葉別評価の識別/品質範囲差")
        observed.add(key)
    if observed != expected:
        raise ValueError("空群を含む全新leafの評価が必要")
    contexts = result["局面別評価"]
    if len(contexts) != 6 or {(r["policy"], r["period"], r["z"]) for r in contexts} != {("D0", p, z) for p in PERIODS for z in (0, 1)}:
        raise ValueError("新D0局面6行が必要")
    for period in PERIODS:
        group = result["候補"]["D0"][period]
        for rows in ([r for r in result["葉別評価"] if r["period"] == period], [r for r in contexts if r["period"] == period]):
            for key in ("候補", "約定", "250"):
                if sum(r["入口"][key] for r in rows) != group["入口"][key]:
                    raise ValueError("葉/局面と入口の合計差")
            if sum(r["実完結"] for r in rows) != group["運用"]["完結数"] or sum(r["実観測純額5"] for r in rows) != group["運用"]["完結観測額円"]["5"]:
                raise ValueError("葉/局面と元実完結の合計差")
        if any(r["品質注意場"] != group["運用"]["品質注意場"] or r["品質注意の範囲"] != "同じ候補の期間全体。局面への帰属ではない" for r in contexts if r["period"] == period):
            raise ValueError("局面の品質範囲差")
    viewer = read(study / "一覧.resources.json")
    resources = viewer["resources"]
    if viewer.get("path_base") not in (None, "") or len(resources) != 138 or len({r["id"] for r in resources}) != 138:
        raise ValueError("Viewerは旧92＋新46の138資源")
    for policy in POLICIES:
        if {r["session"] for r in resources if r["method_id"] == policy} != set(result["評価場"]):
            raise ValueError("各候補同46場のViewerが必要")
    for row in resources:
        path = (ROOT / row["pnl_path"]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Viewer参照欠落")
    sources = [*required, *model_paths, Path(__file__), SHARED, V5.CATALOG, V5.MASTER,
        ROOT / "scripts/レポート/カタログ版5.py", OLD / "結果.json", OLD / "固定.json", OLD / "保存物確認.json", OLD / "設定と結果.md",
        ROOT / "scripts/定時帯反応/運用.py", ROOT / "scripts/局所帯分岐/特徴.py", ROOT / "scripts/局所帯分岐/特徴仕様.md",
        ROOT / "scripts/局所帯分岐/学習.py"]
    sources += [p for p in (study / "入力台帳.json", study / "人工確認.json", HERE / "検証.py", HERE / "学習.py", HERE / "学習仕様.md", HERE / "保存物確認.py", HERE / "README.md") if p.is_file()]
    for path in sources:
        rel = path.relative_to(ROOT).as_posix()
        if rel in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][rel]:
            raise ValueError("固定出典の変更: " + rel)
    return {"study": study, "result": result, "proof": proof, "config": read(study / "条件.json"),
        "models": models, "controls": controls, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def settings(context: dict) -> list[dict]:
    """18入力と固定二段・旧対照・既存運用を版5へ対応させる。

    引数: context(dict)は保存文脈。
    返り値: list[dict]は設定。入力候補や固定分岐を単独効果としない。
    """
    output = []
    for i, m in enumerate(context["metadata"]):
        applies = ["R01", "R02", "R03"] if i < 17 else ["R02", "R03"]
        output.append({"設定ID": f"S{i + 1:02d}", "手法ID": [m["method"]], "尺度ID": m["scale"].split("+"),
            "短記": m["id"] + "=" + FORMULAS[i] + "・固定/学習閾値は木表", "結果短記": "/".join(applies), "適用評価": applies,
            "説明": "旧53と同じ入力。D0はF18とF01符号を固定段で使い、F01強さは子でも可。未分岐入力の効果は未評価"})
    extra = [(["M01"], ["m03", "m15", "m30"], ["R01", "R02"], "固定53B0/F0・旧6木/同46場保存対照", "旧2候補は再fit/再運用なし。旧の全閾値・葉評価は53設定を参照"),
        (["M01"], ["m03", "m15", "m30"], ["R03"], "Z固定→DI符号固定→17列d2×4群", "全pair除外後のfloat32所属。固定price+trendで技法条件を構造上満たすが、独立二票や学習の発見とはしない"),
        (["B01"], ["tick"], list(EVALUATIONS.values()), "全定時枠/正常BBO/+1秒TTL30", "保有非待ち、判定不能込み保守上限50%。全評価740/888/74枠を維持"),
        (["E02"], ["tick"], list(EVALUATIONS.values()), "固定49O・現在益122円strict", "損失/利益連続追尾・名目床・非緩和・pending凍結。実要求時最新3分ATRのD固定"),
        (["E01"], ["tick"], list(EVALUATIONS.values()), "同時計B±の125/250/期限", "主分母は全仮約定。force最初正常行inclusive、固定250TPなし"),
        (["C07"], ["m15"], list(EVALUATIONS.values()), "当時3/15分公開/隣接/鮮度", "m30は3分10本のORで新30分OHLCではない"),
        (["P03", "P10"], ["m03"], list(EVALUATIONS.values()), "53と同じ参照10足＋反応5足/ready", "追加準備なし、Z0有効/未知別。両方向Z1可。全保存feature・教師の一致は監査へ接続")]
    for methods, scales, applies, short, detail in extra:
        output.append({"設定ID": f"S{len(output) + 1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short,
            "結果短記": "/".join(applies), "適用評価": applies, "説明": detail})
    return output


def main_tables(result: dict) -> tuple[str, str]:
    """旧二対照と新D0の主要先着・活動・費用を小型表にする。

    引数: result(dict)は保存結果。
    返り値: tuple[str,str]は入口表と運用表。
    """
    entry, cash = [], []
    for p in POLICIES:
        for s in PERIODS:
            e, o = result["候補"][p][s]["入口"], result["候補"][p][s]["運用"]
            entry.append([p, PERIOD_NAMES[s], e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]), rate(e["間引き率"]), qualification(e["支持"]), qualification(e["70目標"])])
            cash.append([p, PERIOD_NAMES[s], o["完結数"], number(o["台帳観測額円"]["5"]), confirmed(o["全体確定額円"]["5"]), rate(o["待ち率保守上限"]), len(o["品質注意場"]), o["未解消"], qualification(result["候補"][p][s]["同時適格"])])
    return (table(["候補", "評価範囲", "純候補", "仮250/全仮約定", "主率", "非重複率", "入口支持", "70目標"], entry),
        table(["候補", "評価範囲", "実完結", "台帳観測5円", "全体確定5円", "保守待ち率", "注意場", "未解消", "全条件"], cash))


def feature_table(context: dict) -> str:
    """18特徴の入力・固定段・新3モデルの学習分岐を分ける。

    引数: context(dict)は保存モデルとmetadata。
    返り値: strは実分岐対応表。旧6木は旧53設定への参照とする。
    """
    locations = {i: [] for i in range(18)}
    for identity, item in context["models"].items():
        for node in item["model"]["nodes"]:
            if node["feature"] >= 0:
                locations[node["feature"]].append(identity + (":固定node" if node["id"] < 3 else ":学習node") + str(node["id"]))
    rows = [[f"S{i + 1:02d}", m["id"], m["name"], m["method"] + "/" + m["family"], m["scale"], FORMULAS[i], "、".join(locations[i]) or "入力候補・新3モデルで分岐未使用", "単独未評価"] for i, m in enumerate(context["metadata"])]
    return ("## 全18特徴と固定/学習分岐\n\n53の18列とreadyをそのまま使う。sは実方向、KはFastK14、CLV零幅0は明示定義。F11/F12は売で高安役割を交換する。m30のORは3分10本の序盤帯であり、新30分OHLCではない。\n\n"
        "F16/17はj−14..j−5の固定参照帯の幅/中央距離、F18はj−4..jの5終値によるZ。Z0も有効、両方向Z1も可能。旧53と同一で新機械や閾値を加えていない。F18固定rootとF01固定DI符号は学習器が選んだ分岐ではない。子ではF01強さの追加分割を許す。\n\n"
        + table(["設定", "特徴", "名前", "技法/family", "尺度", "式", "新3合成モデルの分岐位置", "効果範囲"], rows))


def readiness_table(result: dict) -> str:
    """準備と全ready枠の買売Z分布を旧53同値として示す。

    引数: result(dict)は準備比較。
    返り値: strは全予定枠分母の表。採用局面と分母を混同しない。
    """
    rows, zs = [], []
    for period in PERIODS:
        r = result["準備比較"][period]
        rows.append([PERIOD_NAMES[period], r["全予定枠"], r["旧特徴準備"], r["共通履歴準備"], r["履歴追加で未準備"], r["追加未準備理由"]])
        zs.append([PERIOD_NAMES[period], r["共通履歴準備"], *[r["買売Z分布"].get(z, 0) for z in ("00", "01", "10", "11")]])
    return ("以下は旧53からの準備表を維持したもの。『追加未準備』は53で基礎15列へ局所帯を加えた差で、54の追加除外ではない。54は旧B0/F0と全特徴・ready・評価枠を一致させた。\n\n"
        + table(["範囲", "全枠", "基礎15準備", "全候補共通準備", "53局所追加の除外", "理由"], rows)
        + "買売Z分布は全ready枠で、文字列は買Z/売Zの順。採用方向だけの局面評価とは別の分母。\n\n"
        + table(["範囲", "全ready枠", "00", "01", "10", "11"], zs))


def model_tables(context: dict, output: Path) -> str:
    """旧6参照と新3合成モデル・四群教師・全葉を分けて表示する。

    引数: context(dict)はモデル文脈、output(Path)は設定文書。
    返り値: strは全葉path/学習率/支持と対応評価。未知scoreを0率としない。
    """
    controls, models, partitions, leaves, evaluations = [], [], [], [], []
    for identity, item in context["controls"].items():
        e = item["entry"]
        controls.append([link(item["path"], output, identity), "17列自由d4" if e["policy"] == "B0" else "Z固定＋17列d3", e["phase"], e["特徴数"], len(e["学習場"]), len(e["評価場"]), "再fitなし・旧53閾値参照"])
    for identity, item in context["models"].items():
        m, e = item["model"], item["entry"]
        t, ready = m["training"], e["特徴準備"]
        models.append([link(item["path"], output, identity), e["phase"], len(e["学習場"]), len(e["評価場"]), ready["特徴準備枠"], ready["特徴未準備枠"], t["used_pairs"], t["excluded_pair_count"], t["period"]["max_label_end_key"], e["評価開始"]])
        for key, p in t["partition"].items():
            partitions.append([identity, key, p["root"], p["node_count"], p["direction_rows"], f"{p['pair_unique']}/{p['days']}/{p['sessions']}", "fit済み" if p["fit_performed"] else "空群・未学習", p["row_ids_sha256"]])
        for n in m["nodes"]:
            if n["left"] != -1 or n["right"] != -1:
                continue
            path = " ∧ ".join(p["feature_id"] + ("（固定）" if p["node"] < 3 else "") + " " + p["comparison"] + " " + format(p["threshold"], ".17g") for p in n["path"])
            leaves.append([identity, n["id"], path, "未学習" if n["data_absent"] else "学習済み", n["direction_rows"], number(n["success_weight"], 1) + "/" + number(n["total_weight"], 1), "未学習（score未定）" if n["data_absent"] else rate(n["score"]), f"{n['unique_slots']}/{n['days']}/{n['sessions']}", qualification(n["leaf_support"]), "/".join(n["families"]), qualification(n["method_support"])])
    for row in context["result"]["葉別評価"]:
        e = row["入口"]
        evaluations.append([row["model_id"], row["phase"], row["leaf"], row["period"], e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]), f"{e['間引き250']}/{e['間引き約定']}", rate(e["間引き率"]), row["実完結"], number(row["実観測純額5"]), row["品質注意場"]])
    return ("## 旧6保存モデルと新3合成モデル\n\n旧B0/F0は同46場の保存対照で、再fit/再運用していない。旧全葉閾値と葉評価は" + link(OLD / "設定と結果.md", output, "旧53設定") + "を正本として参照する。\n\n"
        + table(["旧モデルJSON", "構造", "phase", "列", "fit場", "評価場", "扱い"], controls)
        + "### 新D0の時系列境界\n\n初期20場は運用評価へ含めない。特徴準備除外と、未約定/不足教師pair除外を別にする。全入力教師の終了秒は評価開始よりstrict過去、同秒不可。旧53B0/F0の使用ID/期間と一致し、18列F0とは入力/使用行JSON指紋も一致する。\n\n"
        + table(["新モデルJSON", "phase", "fit場", "評価場", "共通準備枠", "特徴未準備枠", "使用pair", "先着不明pair", "使用教師最大終了key", "評価開始秒"], models)
        + "### 固定二段と四群教師\n\nnode0=F18<=0.5、node1/2=F01<=0を事前固定。a1はfloat32 F01>0、a0は<=0で同値を含む。DI0の最終役割未確定WAITは維持する。全pair除外後に四群へ分け、枝内pair揃いを要求しない。固定3nodeは空Zでも保持し、空群には未知leafを残す。各子木は17列・深さ2、F01は子でも使えるがF18は除く。\n\n固定段はgini最適分割ではなくmin_samples_leaf60で選ばれた分岐でもない。支持/giniは全体使用行から再計数し、枝unique枠は非加算。\n\n"
        + table(["モデル", "Z/DI群", "全体子root", "node数", "方向行", "枠/日/場", "子fit", "方向ID指紋"], partitions)
        + "## 新D0全葉の学習経路・率・支持\n\nfloat32化後に左<=/右>で走査し、固定閾値と子の学習閾値を分ける。葉率は0.5重みの学習標本内比率で将来確率ではない。葉支持は方向行60とは別のunique枠60/6日/10場。固定price+trendが全pathへ入るので技法条件は構造上充足する。条件の撤廃や技法の独立二票・学習の発見を意味しない。未知scoreは0%ではなく、一方向でも未知leaf到達なら両方向WAIT。\n\n"
        + table(["モデル", "葉", "全path・閾値", "状態", "方向行", "成功重み/全重み", "学習葉率", "枠/日/場", "葉支持", "path family", "技法条件"], leaves)
        + "## 新D0全葉の対応評価\n\n選ばれた純入口だけの評価で、全方向scoreの校正ではない。全leaf×phase内期間に空群も残す。葉別間引きは群内診断で全体間引きへ加算しない。実額は元運用の帰属で葉限定の再運用ではない。品質注意場は同モデル評価期間全体で葉への帰属ではなく重複加算しない。未解消は運用期間正本へ。\n\n"
        + table(["モデル", "phase", "葉", "評価期間", "純入口", "仮250/仮約定", "率", "仮250/非重複", "非重複率", "実完結", "実観測5円", "品質注意場"], evaluations))


def detailed_results(result: dict) -> str:
    """費用・活動・役割・利益回収とD0局面6行を詳細へ表示する。

    引数: result(dict)は保存集計。
    返り値: strは小型表。新しい選別運用を計算しない。
    """
    fees, activities, roles, protection, contexts = [], [], [], [], []
    for p in POLICIES:
        for s in PERIODS:
            o = result["候補"][p][s]["運用"]
            fees.append([p, s, *[number(o["台帳観測額円"][str(f)]) for f in (0, 5, 10)], *[confirmed(o["全体確定額円"][str(f)]) for f in (0, 5, 10)], qualification(o["費用支持"]), qualification(o["費用適格"])])
            activities.append([p, s, o["予定枠"], o["待ち数"], rate(o["主待ち率"]), o["判定不能"], rate(o["待ち率保守上限"]), qualification(o["活動適格"]), o["判断別"]])
            protection.append([p, s, o["利益起動件数"], o["起動後赤字件数5"], o["実250到達件数"], o["定時外返済件数"], o["返済理由"], o["品質注意場"]])
            for role in ("順行", "反転"):
                e, actual = result["役割別入口"][p][s][role], o["役割別完結"][role]
                roles.append([p, s, role, e["候補"], f"{e['250']}/{e['約定']}", rate(e["率"]), qualification(e["支持"]), actual["件数"], number(actual["観測純額5"])])
    for row in result["局面別評価"]:
        e = row["入口"]
        contexts.append([row["period"], row["z"], e["候補"], e["結果別"].get("未約定", 0), f"{e['250']}/{e['約定']}", rate(e["率"]), f"{e['間引き250']}/{e['間引き約定']}", rate(e["間引き率"]), row["実完結"], number(row["実観測純額5"]), row["品質注意場"]])
    return ("## 費用・活動・役割・回収\n\n0/5/10は同じ実約定への追加片道pt費用。起動参照122円は変えない。台帳観測には未解消の新規片道費用を含み、品質nullを観測額で埋めない。\n\n"
        + table(["候補", "期間", "台帳0", "台帳5", "台帳10", "確定0", "確定5", "確定10", "費用支持", "費用適格"], fees)
        + table(["候補", "期間", "全枠", "待ち", "主待ち率", "判定不能", "保守上限", "活動適格", "実判断"], activities)
        + "順行/反転は当時15分DIと選択方向の説明ラベルで、心理の正解教師ではない。DI同値はWAIT。混合支持を片役割へ代用しない。\n\n"
        + table(["候補", "期間", "役割", "純入口", "仮250/仮約定", "率", "役割支持", "実完結", "実観測5円"], roles)
        + "起動後赤字5は追加5pt費用後の実完結で、起動参照122円とは別の集計。実MFE250も固定250利確ではない。\n\n"
        + table(["候補", "期間", "利益起動", "起動後赤字5", "実MFE250", "定時外返済", "返済理由", "品質注意場"], protection)
        + "## D0採用方向の局面別評価\n\n新D0×3期間×Z0/1の6行。採用方向のZへ純入口と元実完結を帰属し、全ready枠/両方向の校正表や局面限定再運用ではない。ZはDI役割と別。群別間引きは非加算。品質注意は候補/期間全体で、局面へ帰属せず重複加算しない。未解消は運用正本へ。\n\n"
        + table(["期間", "採用Z", "純入口", "未約定", "仮250/全仮約定", "率", "仮250/非重複", "非重複率", "実完結", "実観測5円", "期間品質注意場"], contexts))


def documents(context: dict) -> dict[str, str]:
    """小型READMEと全設定・全葉を含む詳細を同じ保存文脈から作る。

    引数: context(dict)は読取済み文脈。
    返り値: dict[str,str]は二文書の文字列。ここでは保存しない。
    """
    study, result, proof = context["study"], context["result"], context["proof"]
    readme, detail = study / "README.md", study / "設定と結果.md"
    entry, cash = main_tables(result)
    fits = sum(p["fit_performed"] for item in context["models"].values() for p in item["model"]["training"]["partition"].values())
    intro = ("保存実行日時：" + result["実行日時"] + "。全66場は研究に既使用。初期20場はfit専用、後半20場/条件選択24場/既使用後続2場の46場を運用評価する。『学習』は後半20場の時系列検査でfit40場への当てはめ成績ではない。\n\n"
        "B0/F0は固定53の同46場保存対照。D0だけを新計算し、53と同じ18特徴・ready・教師・O49を使い、Z→DI符号の二段を事前固定して四群の17列深さ2子木を学習した。旧6＋新3の保存モデル表示9本と、新分類器fit " + str(fits) + "回を区別する。\n\n"
        + ("両期同時適格の新候補：D0。\n\n" if result["採用"] else "**新D0の両期同時適格は未達。** 入口・支持・活動・費用は以下で分ける。\n\n"))
    limits = ("## 読み方と限界\n\n"
        "- 仮250/全仮約定は入口経路の率で、125・期限・不足を含み未約定は別。実黒字率や固定250利確ではない。群内非重複間引きは30分間引きではない。\n"
        "- 全予定枠は740/888/74。保有非待ち、判定不能も含む保守待ち上限=(待ち+判定不能)/全枠<=50%。欠測枠や初期warmupを分母から除かない。\n"
        "- 学習葉率は重み0.5の標本内率で未来確率ではない。葉評価は採用入口だけ、全score校正ではない。葉/局面の間引きは非加算、実額は元運用の帰属で限定再運用ではない。\n"
        "- 固定ZとDI符号はgini最適分割ではない。固定price+trendで技法条件が構造上充足するため、複数心理の独立二票や学習発見の証拠とはしない。D0は群分けと子の探索深さを変える総合比較。\n"
        "- 未知leafのscore=nullは0%ではない。一方向でも未知なら両方向WAIT。既知側へ救済せず、双方既知でも最高側だけにscore>=1/3・unique枠60/6日/10場・family条件を課し、不適格なら待つ。\n"
        "- 運用は固定49。定時最新3分ATRでD固定、現在正常返済BBO粗益−122円>0strictで利益旗・最低名目entry床。損失/利益追尾は定時外も行い、返済pending中保護は凍結。費用0/5/10は同約定、品質nullと観測額を混同しない。\n"
        "- 全66場は開発既使用、未予約11/5Day両商品は不使用。未見利益・市場心理の因果実証、別算法による最適分岐の独立再学習まで保証しない。\n\n")
    links = ("## 詳細・再表示\n\n" + " / ".join(link(study / n, readme) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + "。保存監査" + number(proof["照合項目数"]) + "項目・不一致0。Viewerは旧92＋新46の138資源。帳票は市場系列や新2gzipを展開しない。\n\n"
        + link(HERE / "学習仕様.md", readme) + " / " + link(ROOT / "scripts/局所帯分岐/特徴仕様.md", readme) + " / " + link(OLD / "設定と結果.md", readme, "旧6モデルの全閾値と評価") + "。新3モデルの全葉・四群教師・局面6行・18特徴・出典SHAは詳細へ。\n\n"
        "```powershell\nC:/Python314/python.exe -X utf8 scripts/方向局面分岐/レポート.py\nC:/Python314/python.exe -X utf8 scripts/方向局面分岐/レポート.py --check\n```\n\n正式結果/監査完成後だけ表示し、特徴・教師・fit・先着・戦略を再実行しない。\n")
    brief = "# 00054：方向と局所帯を先に分岐\n\n" + intro + "## 同じ準備\n\n" + readiness_table(result) + "## 入口先着\n\n" + entry + "## 実運用・活動\n\n追加5ptは片道、台帳観測は未解消新規の片道費用を含む。\n\n" + cash + limits + links
    groups = settings(context)
    details = ("# 設定と結果：方向と局所帯を先に分岐\n\n" + intro
        + "## 手法×尺度・版5\n\n55手法×9尺度。S01..18は53と同じ入力で、D0のF18とF01符号は固定段。R01=旧B0、R02=旧F0、R03=新D0。未使用セル、入力候補の未分岐、固定分岐、学習分岐を分け、複合成績を指標単独の効果としない。\n\n"
        + V5.matrix(V5.load_catalog(), detail, groups) + feature_table(context)
        + "## 共通設定\n\n" + table(["設定", "技法/尺度", "短記", "役割・限定", "評価"], [[g["設定ID"], "/".join(g["手法ID"]) + "・" + "/".join(g["尺度ID"]), g["短記"], g["説明"], "/".join(g["適用評価"])] for g in groups[18:]])
        + "## 準備・同教師\n\n" + readiness_table(result)
        + table(["phase", "旧対照", "教師指紋一致"], [[phase, p, result["教師一致"][phase][p]] for phase in PHASES for p in CONTROLS])
        + model_tables(context, detail)
        + "## 複合評価\n\n" + table(["評価", "候補", "構成", "扱い"], [[EVALUATIONS[p], p, {"B0": "固定53自由17列d4", "F0": "固定53Z根＋17列d3", "D0": "Z→DI固定二段＋17列d2四群"}[p], "保存対照・採用対象外" if p in CONTROLS else "採用" if p in result["採用"] else "未達"] for p in POLICIES])
        + "## 主結果\n\n" + entry + cash + detailed_results(result)
        + "## D0判断理由\n\n" + table(["期間", "保存理由別枠数"], [[p, result["判断理由"]["D0"][p]] for p in PERIODS])
        + "## 全固定条件\n\n" + table(["項目", "値"], [[k, v] for k, v in context["config"].items()]) + limits
        + "## 保存出典\n\n" + table(["出典", "SHA256"], [[link(p, detail), "`" + sha(p) + "`"] for p in context["sources"]])
        + "## 再表示\n\n" + link(readme, detail, "概要と再表示CLI") + "。モデルJSONと正式結果が正本で、帳票は再学習を起動しない。\n")
    return {"README.md": brief.rstrip() + "\n", "設定と結果.md": details.rstrip() + "\n"}


def render(study: Path = STUDY, check: bool = False) -> dict:
    """保存値を二MDへ表示又は同byteで確認する。

    引数: study(Path)は正式先、check(bool)は書込なし確認。
    返り値: dictは出力指紋/表/リンク数。市場・本物fitは起動しない。
    """
    import hashlib

    study = study.resolve()
    context = context_for(study)
    output = documents(context)
    generated, report, links = {(study / n).resolve() for n in output}, {}, 0
    for name, text in output.items():
        path, data = study / name, text.encode("utf-8")
        links += G.check_links(text, path, generated)
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("保存帳票と再表示が不一致: " + name)
        else:
            path.write_bytes(data)
        report[name] = {"bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()}
    return {"文書": report, "リンク検査件数": links, "欠落リンク": [], "カタログ手法数": 55, "尺度数": 9,
        "特徴設定数": 18, "政策特徴数": {"D0": 18}, "共通設定数": len(settings(context)) - 18,
        "保存モデル表示数": len(context["controls"]) + len(context["models"]), "旧保存モデル数": len(context["controls"]), "新保存モデル数": len(context["models"]),
        "新分類器fit回数": sum(p["fit_performed"] for item in context["models"].values() for p in item["model"]["training"]["partition"].values()),
        "葉別評価行数": len(context["result"]["葉別評価"]), "局面別評価行数": len(context["result"]["局面別評価"]),
        "市場再計算": False, "学習再実行": False}


def main() -> None:
    """正式完成後だけ生成又は照合を呼ぶCLIを提供する。

    引数: --study(Path)/--check(bool)はargparseから読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="54方向局面分岐の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(render(args.study, args.check), ensure_ascii=False))


if __name__ == "__main__":
    main()
