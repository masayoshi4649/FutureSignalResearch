"""70の支持剪定と条件運用を、保存された小型証拠だけから表示する。"""

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
STUDY = ROOT / "study/00070_約定支持を保つ粒度で技法を組み合わせる"
OLD = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
SHARED = ROOT / "scripts/条件入口の教師/レポート.py"
SPEC = importlib.util.spec_from_file_location("支持表示70が参照する固定69表示", SHARED)
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
V5, R55 = PREVIOUS.V5, PREVIOUS.R55
sha, read, table = PREVIOUS.sha, PREVIOUS.read, PREVIOUS.table
money, rate, qualification, link, shown = PREVIOUS.money, PREVIOUS.rate, PREVIOUS.qualification, PREVIOUS.link, PREVIOUS.shown
POLICIES = ("C0", "C1", "P0", "P1")
CONTROLS, NEW = POLICIES[:2], POLICIES[2:]
PERIODS, PERIOD_NAMES, PHASES = PREVIOUS.PERIODS, PREVIOUS.PERIOD_NAMES, PREVIOUS.PHASES
NONFILL, FORMULAS = PREVIOUS.NONFILL, PREVIOUS.FORMULAS
EXTERNAL = ROOT / "docs/議論/外部再調査/技法群の細分化と約定支持を分ける.md"
LEARNING = {"元試行": 69, "モデル政策": "C0", "同じ60特徴": True, "新fit": False,
    "共通教師": "study/00069_条件入口に合わせて技法群の教師を作る/結果.json", "無取引": "回収0・障壁対象外"}


# ----------------------------------------

def validate_result(result: dict) -> None:
    """新fitなしの三派生木・四政策と条件入口の分母を確認する。

    引数: result(dict)は主の小型結果又は自己完結の人工辞書。
    返り値: None。不一致はValueErrorとし、未知を補完しない。
    """
    if result.get("試行") != 70 or result.get("全66場既使用") is not True or set(result["候補"]) != set(POLICIES):
        raise ValueError("70の旧C対照と新P二政策が必要")
    expected = {"新回帰器fit": 0, "新分類器fit": 0, "新独立計測": 0,
        "新保存木数": 3, "新派生木数": 3, "参照モデル数": 3, "新運用数": 92, "参照独立測定": 4092}
    if any(type(result[k]) is not int or result[k] != n for k, n in expected.items()):
        raise ValueError("新fit0・独立計測0・三派生木・92運用の差")
    if result["学習参照"] != LEARNING or result["対照参照"] != {"候補": list(CONTROLS), "元試行": 69, "市場再生": False}:
        raise ValueError("旧69C0教師・保存対照の参照差")
    if len(set(result["評価場"])) != 46 or len(set(result["学習専用場"])) != 20 or set(result["評価場"]) & set(result["学習専用場"]):
        raise ValueError("初20専用と評価46場の差")
    for key in ("モデル", "回収集計"):
        entries = result[key]
        if len(entries) != 3 or {(r["policy"], r["phase"]) for r in entries} != {("P0", h) for h in PHASES} or {r["id"] for r in entries} != {"P0_" + h for h in PHASES}:
            raise ValueError("P0三phaseの派生モデルと回収が必要")
    if set(result["剪定"]) != set(PHASES) or set(result["条件段階"]) != set(NEW):
        raise ValueError("三phase剪定・新二政策の条件段階が必要")
    for period, scheduled in zip(PERIODS, (740, 888, 74)):
        for policy in POLICIES:
            item = result["候補"][policy][period]
            e, o = item["入口"], item["運用"]
            outcomes = e["結果別"]
            if not set(outcomes) <= set(NONFILL) | {"250", "125", "期限", "不足"} or any(type(n) is not int or n < 0 for n in outcomes.values()):
                raise ValueError("条件入口結果別の分類差")
            if sum(outcomes.values()) != e["候補"] or e["候補"] - sum(outcomes.get(k, 0) for k in NONFILL) != e["約定"] or e["250"] != outcomes.get("250", 0):
                raise ValueError("条件候補・非fill六群・仮約定の分母差")
            for wins, total, field in (("250", "約定", "率"), ("間引き250", "間引き約定", "間引き率")):
                if (e[field] is None) != (e[total] == 0) or e[total] and not math.isclose(e[field], e[wins] / e[total], rel_tol=0, abs_tol=1e-12):
                    raise ValueError("先着率の分母又はnull差")
            wait, invalid = o["判断別"].get("待ち", 0), o["判断別"].get("判定不能", 0)
            conservative = wait + invalid + o["条件未約定"]
            if o["予定枠"] != scheduled or sum(o["判断別"].values()) != scheduled or (o["待ち数"], o["判定不能"]) != (wait, invalid):
                raise ValueError("全予定枠・待ち・判定不能の復元差")
            if not 0 <= conservative <= scheduled or not math.isclose(o["主待ち率"], wait / scheduled, abs_tol=1e-12, rel_tol=0) or not math.isclose(o["待ち率保守上限"], conservative / scheduled, abs_tol=1e-12, rel_tol=0):
                raise ValueError("登録未約定込みの保守待ち分母差")
            if o["活動適格"] != (conservative * 2 <= scheduled):
                raise ValueError("保守待ち50%判定差")
            for fee in (0, 5, 10):
                if o["完結観測額円"][str(fee)] != o["完結観測額円"]["0"] - 20 * fee * o["完結数"]:
                    raise ValueError("同約定の費用感応差")
                if (o["品質注意場"] or o["未解消"]) and o["全体確定額円"][str(fee)] is not None:
                    raise ValueError("品質注意・未解消の確定額はnull")
            if sum(o["役割別完結"][r]["件数"] for r in ("順行", "反転")) != o["完結数"]:
                raise ValueError("役割別実完結の復元差")
            if item["同時適格"] != (e["70目標"] and o["活動適格"] and o["費用適格"]):
                raise ValueError("同時目標の判定差")
            if policy in NEW:
                stage = result["条件段階"][policy][period]
                if stage["全予定枠"] != scheduled or stage["純候補"] != e["候補"] or sum(stage["条件結果別"].values()) != e["候補"] or stage["仮約定"] != e["約定"]:
                    raise ValueError("新純候補と独立条件入口の段階差")
                if not 0 <= stage["仮約定"] <= stage["発動"] <= stage["純候補"] <= scheduled:
                    raise ValueError("純候補・発動・仮約定の順序差")
                if (stage["実条件登録"], stage["実登録未約定"]) != (o["条件登録数"], o["条件未約定"]) or stage["実新規"] + stage["実登録未約定"] != stage["実条件登録"] or not o["完結数"] <= stage["実新規"] <= stage["実条件登録"]:
                    raise ValueError("実一枚の登録・新規・未約定の段階差")
    if sum(result["候補"][p][h]["入口"]["候補"] for p in NEW for h in PERIODS) != result["新条件入口評価"]:
        raise ValueError("新条件入口評価数の復元差")
    if result["採用"] != [p for p in NEW if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])]:
        raise ValueError("新候補採用の差")


def validate_model(model: dict, calibration: dict, source: dict, common: dict) -> None:
    """元親統計と剪定後配置を混同せず、保存由来と回収分母を検査する。

    引数: model/calibration(dict)はP0派生物、source(dict)は旧C0木、common(dict)は旧共通教師要約を含む正本。
    返り値: None。再剪定・fit・教師生成・予測walkは行わない。
    """
    pruning = model["pruning"]
    if model["policy"] != "P0" or source["policy"] != "C0" or model["source_model_id"] != source["model_id"] or pruning["source_model_id"] != source["model_id"] or pruning["fit_count"] != 0:
        raise ValueError("P0の旧C0出所又は新fit0の差")
    if model["source_model_sha256"] != pruning["source_model_sha256"]:
        raise ValueError("派生木と剪定の元byte指紋差")
    for key, value in source.items():
        if key not in ("model_id", "policy", "nodes") and model.get(key) != value:
            raise ValueError("元の学習証拠・metadata・規約変更:" + key)
    old_nodes, nodes = source["nodes"], model["nodes"]
    mapping, reverse = pruning["source_to_new"], pruning["new_to_source"]
    retained = [i for i in range(len(old_nodes)) if mapping.get(str(i)) is not None]
    if pruning["source_node_count"] != len(old_nodes) or pruning["new_node_count"] != len(nodes) or set(mapping) != {str(i) for i in range(len(old_nodes))} or reverse != {str(i): old for i, old in enumerate(retained)} or any(mapping[str(old)] != i for i, old in enumerate(retained)):
        raise ValueError("元ID昇順の圧縮と全旧新対応の差")
    if retained[:3] != [0, 1, 2] or len(nodes) != len(retained):
        raise ValueError("固定三節点は維持する")
    decisions = {d["source_node_id"]: d for d in pruning["decisions"]}
    expected_decisions = {n["id"] for n in old_nodes if n["id"] >= 3 and n["left"] != -1}
    if set(decisions) != expected_decisions or len(decisions) != len(pruning["decisions"]):
        raise ValueError("元の学習分割の全剪定判断が必要")
    for old_id, decision in decisions.items():
        details = [{"source_node_id": i, "unique_slots": old_nodes[i]["unique_slots"], "days": old_nodes[i]["days"], "sessions": old_nodes[i]["sessions"], "supported": old_nodes[i]["unique_slots"] >= 60 and old_nodes[i]["days"] >= 6 and old_nodes[i]["sessions"] >= 10} for i in decision["terminal_source_ids"]]
        keep = all(d["supported"] for d in details)
        if decision["terminal_support"] != details or decision["action"] != ("保持" if keep else "両側統合") or decision["result_terminal_source_ids"] != (decision["terminal_source_ids"] if keep else [old_id]):
            raise ValueError("剪定は終端の約定支持だけで判定する")
        if decision["retained_in_final"] != (old_id in retained) or decision["split_retained_in_final"] != (old_id in retained and keep):
            raise ValueError("途中の剪定判断と最終残存を分離する")
    topology = {"id", "feature", "feature_id", "family", "threshold", "left", "right", "path"}
    reached = {0}
    for new_id, old_id in enumerate(retained):
        current, original = nodes[new_id], old_nodes[old_id]
        if current["id"] != new_id or current["source_node_id"] != old_id or new_id not in reached:
            raise ValueError("新ID又は元ID・到達性の差")
        if {k: v for k, v in current.items() if k not in topology | {"source_node_id"}} != {k: v for k, v in original.items() if k not in topology}:
            raise ValueError("元親の保存統計を変更している")
        expected_path = [{**p, "node": mapping[str(p["node"])]} for p in original["path"]]
        if current["path"] != expected_path:
            raise ValueError("pathは元閾値を保持しnode IDだけ圧縮する")
        collapsed = old_id in decisions and decisions[old_id]["action"] == "両側統合"
        if original["left"] == -1 or collapsed:
            if (current["feature"], current["feature_id"], current["family"], current["threshold"], current["left"], current["right"]) != (-2, None, None, -2.0, -1, -1):
                raise ValueError("統合葉のsentinel差")
        else:
            if any(current[k] != original[k] for k in ("feature", "feature_id", "family", "threshold")) or (current["left"], current["right"]) != (mapping[str(original["left"])], mapping[str(original["right"])]) or not new_id < current["left"] < len(nodes) or not new_id < current["right"] < len(nodes):
                raise ValueError("保持分割又は子対応の差")
            reached.update((current["left"], current["right"]))
    if reached != set(range(len(nodes))):
        raise ValueError("孤立nodeがある")
    for key, old_group in source["training"]["partition"].items():
        item = pruning["partitions"][key]
        stack, members = [old_group["root"]], []
        while stack:
            i = stack.pop()
            members.append(i)
            if old_nodes[i]["left"] != -1:
                stack.extend((old_nodes[i]["left"], old_nodes[i]["right"]))
        expected = {"source_root": old_group["root"], "source_node_count": old_group["node_count"], "new_root": mapping[str(old_group["root"])], "new_node_count": sum(i in retained for i in members)}
        if item != expected:
            raise ValueError("元training配置と新pruning配置の差")
    projected, projected_cal = {**model, "policy": "C0"}, {**calibration, "policy": "C0"}
    PREVIOUS.validate_model(projected, projected_cal, common)


def context_for() -> dict:
    """成功監査・元木・派生木と回収集計を小型保存物から結合する。

    引数: なし。
    返り値: dictは表示文脈。正式成功前は拒否し、詳細圧縮・原板・教師個票は開かない。
    """
    names = ("結果.json", "保存物確認.json", "固定.json", "条件.json", "検証計画.md", "入力台帳.json", "一覧.resources.json")
    required = [STUDY / name for name in names]
    if any(not p.is_file() for p in required):
        raise FileNotFoundError("70主・正式監査成功後だけ生成できます")
    result, proof, fixed = (read(p) for p in required[:3])
    validate_result(result)
    if result["固定SHA256"] != sha(required[2]) or proof.get("全件一致") is not True or proof.get("不一致数") != 0 or proof.get("不一致") != [] or proof["結果SHA256"] != sha(required[0]):
        raise ValueError("成功監査・結果・固定のSHA結合差")
    old_path, old_proof_path = OLD / "結果.json", OLD / "保存物確認.json"
    old, old_proof = read(old_path), read(old_proof_path)
    if old_proof.get("全件一致") is not True or old_proof.get("不一致数") != 0 or old_proof["結果SHA256"] != sha(old_path):
        raise ValueError("旧69の成功証明結合差")
    PREVIOUS.validate_common(old["共通教師"])
    for policy in CONTROLS:
        if any(result[key][policy] != old[key][policy] for key in ("候補", "役割別入口")):
            raise ValueError("旧69C保存対照の集計変更")
    models, metadata = {}, None
    sources = [*required, old_path, old_proof_path, OLD / "設定と結果.md", SHARED, EXTERNAL]
    old_meta = {e["id"]: e for e in old["モデル"]}
    old_cals = {e["id"]: e for e in old["回収集計"]}
    cals = {e["id"]: e for e in result["回収集計"]}
    for entry in result["モデル"]:
        path, cal_entry = ROOT / entry["path"], cals[entry["id"]]
        cal_path, source_path = ROOT / cal_entry["path"], ROOT / entry["元path"]
        source_id = "C0_" + entry["phase"]
        old_entry, old_cal_entry = old_meta[source_id], old_cals[source_id]
        source_cal_path = ROOT / old_cal_entry["path"]
        if entry["元path"] != old_entry["path"] or entry["元SHA256"] != old_entry["SHA256"] or sha(source_path) != entry["元SHA256"] or sha(source_cal_path) != old_cal_entry["SHA256"] or sha(path) != entry["SHA256"] or sha(cal_path) != cal_entry["SHA256"]:
            raise ValueError("元木・派生木・回収JSONのSHA差")
        model, cal, source = read(path), read(cal_path), read(source_path)
        common = old["共通教師"][entry["phase"]]
        PREVIOUS.validate_model(source, read(source_cal_path), common)
        validate_model(model, cal, source, common)
        if model["model_id"] != entry["id"] or model["source_model_sha256"] != entry["元SHA256"] or entry["policy"] != "P0" or cal_entry["phase"] != entry["phase"] or result["剪定"][entry["phase"]] != model["pruning"]:
            raise ValueError("meta・剪定・payloadの結合差")
        if metadata is not None and model["feature_meta"] != metadata:
            raise ValueError("派生三木の同60列metadata差")
        metadata = model["feature_meta"]
        models[entry["id"]] = {"base": model, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry, "source": source, "source_path": source_path}
        sources.extend((path, cal_path, source_path, source_cal_path))
    conditions = read(STUDY / "条件.json")
    if metadata != conditions["特徴"] or any(m["base"]["pruning"]["rules"] != conditions["剪定"] for m in models.values()):
        raise ValueError("固定条件と同60特徴・剪定規約の差")
    resources = read(required[-1])["resources"]
    if len(resources) != 184 or Counter(r["method_id"] for r in resources) != {p: 46 for p in POLICIES} or any(not (ROOT / r["pnl_path"]).is_file() for r in resources):
        raise ValueError("旧92＋新92のViewer184参照差")
    sources.extend([HERE / "README.md", *sorted(HERE.glob("*.py")), *sorted(HERE.glob("*仕様.md"))])
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = path.relative_to(ROOT).as_posix()
        if name in fixed["ファイルSHA256"] and sha(path) != fixed["ファイルSHA256"][name]:
            raise ValueError("固定出典変更:" + name)
    return {"result": result, "proof": proof, "fixed": fixed, "old": old, "models": models, "metadata": metadata, "sources": list(dict.fromkeys(sources))}


def common_table(context: dict) -> str:
    """旧69共通教師の件数と指紋を参照し、全IDの転記を避ける。

    引数: context(dict)は旧結果と派生木を持つ表示文脈。
    返り値: strは旧集合の要約表。今回教師を再生成しない。
    """
    rows, hashes = [], []
    for phase in PHASES:
        group = context["old"]["共通教師"][phase]
        training = context["models"]["P0_" + phase]["base"]["training"]
        rows.append([phase, group["全予定枠"], group["共通可知枠"], group["共通方向行"], group["除外枠数"], shown(group["評価開始"]), shown(group["使用分類"]["C0"])])
        hashes.append([phase, training["row_ids_sha256"], training["input_rows_sha256"], training["target_rows_sha256"]])
    return ("## 旧69の共通可知教師を参照\n\n即時/条件×買/売のどれかが未知、又は評価開始と同秒以後に確定するpairは旧69で全体除外。確定無取引0は回帰に残し、125敗北や障壁分母に入れない。70はこの集合と保存親統計を変えず、新教師・新計測を作らない。使用全IDと全除外理由は旧69正本に一度だけ置く。\n\n"
        + table(["phase", "旧過去全予定枠", "旧共通可知枠", "旧方向行", "旧除外枠", "評価開始・strict前", "旧C0使用分類"], rows)
        + table(["phase", "旧共通ID指紋", "旧入力行指紋", "旧回収目的指紋"], hashes)
        + link(OLD / "結果.json", STUDY / "設定と結果.md", "旧共通集合・全除外の保存JSON") + " / " + link(OLD / "設定と結果.md", STUDY / "設定と結果.md", "旧教師と元六木の説明") + "\n\n")


def pruning_tables(context: dict, output: Path) -> str:
    """全元ID対応・途中判断・四子の新配置を保存値で表示する。

    引数: context(dict)は派生三木、output(Path)は詳細MD。
    返り値: strは全剪定判断と配置。学習統計を再算しない。
    """
    summary, mappings, decisions, partitions = [], [], [], []
    for identity, item in context["models"].items():
        model, p = item["base"], item["base"]["pruning"]
        summary.append([identity, link(item["source_path"], output, p["source_model_id"]), p["source_model_sha256"], p["source_node_count"], p["new_node_count"], p["fit_count"]])
        mappings.extend([identity, old_id, shown(new_id, "削除"), "固定段" if int(old_id) < 3 else "元の学習子"] for old_id, new_id in p["source_to_new"].items())
        for d in p["decisions"]:
            decisions.append([identity, d["source_node_id"], d["action"], shown(d["terminal_source_ids"]), shown(d["terminal_support"]), shown(d["result_terminal_source_ids"]), qualification(d["retained_in_final"]), qualification(d["split_retained_in_final"]), d["reason"]])
        for group, part in p["partitions"].items():
            partitions.append([identity, group, part["source_root"], part["source_node_count"], part["new_root"], part["new_node_count"]])
    return ("## 支持だけによる剪定と旧新ID\n\n固定node0/1/2とDI×現在有効の四群を保持する。各学習子を下から確認し、その時点の終端に一つでもfilled60枠・6日・10場未達があれば両側を親へ統合する。score・回収・MSE・技法資格や評価成績を剪定基準にしない。四群の親も支持不足なら固定段を越えずWAITを残す。両側統合は文脈を混ぜ得るので改善を保証しない。\n\n"
        + table(["派生木", "元保存木", "元byte SHA256", "元node数", "残存node数", "新fit"], summary)
        + table(["派生木", "元群", "元root", "元node数", "新root", "新node数"], partitions)
        + "training.partitionのroot/node数/fitは元69の証拠。新配置は上のpruning.partitionsだけを用いる。残存元ID昇順で新連番にし、各新nodeにsource_node_idを保存する。元学習の閾値・親の回収統計を再用し、新たな教師再集計や子平均の平均で置き換えない。\n\n"
        + table(["派生木", "元ID", "新ID", "種別"], mappings)
        + "以下は元の全学習分割の判断。途中で保持した分割も、後で祖先が統合されれば最終木から除かれる。途中判断と最終残存を分ける。\n\n"
        + table(["木", "判断元ID", "判断", "判断時の終端元ID", "終端filled支持", "判断後終端元ID", "最終残存", "最終分割保持", "理由"], decisions))


def settings(context: dict) -> list[dict]:
    """同60特徴と独自支持剪定を版5セルへ対応させる。

    引数: context(dict)は全60metadataを持つ表示文脈。
    返り値: list[dict]は設定ID・複合評価ID。未使用セルは未検証のまま。
    """
    rows = deepcopy(PREVIOUS.settings(context)[:60])
    for row in rows:
        row.update(結果短記="R01/R02/R03/R04", 説明="旧Cと新Pは同60特徴・同条件教師。新Pは保存木の支持剪定だけ。単独技法の効果ではない。")
    extras = [(["M01", "P10"], ["m03", "m15", "m30"], "旧C0子の約定支持剪定・固定三node維持", "filled60枠6日10場未達の終端があれば両側を親へ統合。score/回収で選別せず、新fit0。"),
        (["M01"], ["m03", "m15", "m30", "tick"], "条件付きscoreとfilled支持・回収資格", "先着250/約定、score>=1/3・複数技法・回収支持。P1だけ主回収総額strict正。"),
        (["P02", "P09", "B01"], ["m03", "tick"], "固定68の将来突破と発動前否定", "定時端を凍結し有限正Laststrict突破。設定否定は未登録WAIT、監視否定は登録未約定。"),
        (["E01", "E02", "C06"], ["tick"], "固定O49・現在益122円strict正・連続追尾", "固定250TPなし。pendingでh/L/arm凍結。費用感応は同約定。"),
        (["C07"], ["m15"], "25/49全予定枠・保守待ち50%以下", "保有継続非待ち。登録未約定を保守待ちへ含める。")]
    for methods, scales, short, description in extras:
        rows.append({"設定ID": f"S{len(rows) + 1:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "結果短記": "R03/R04", "説明": description})
    return rows


def documents(context: dict) -> dict[str, str]:
    """支持剪定の証拠と四政策の結果を二文書へ純表示する。

    引数: context(dict)は正式又は自己完結の人工文脈。
    返り値: dict[str,str]はREADMEと設定と結果。書込・市場再生をしない。
    """
    r, proof = context["result"], context["proof"]
    brief, detail = STUDY / "README.md", STUDY / "設定と結果.md"
    entrance, operations = main_tables(r)
    status = "新候補の採用なし。支持付き先着70・費用・全予定保守待ち50%以下の同時目標は未達。" if not r["採用"] else "保存採用候補：" + "、".join(r["採用"]) + "。未見利益の保証ではない。"
    intro = ("全66場既使用。初20場は学習専用、学習欄は後20時系列・選択24・既使用後続2を分ける。\n\n" + status
        + "\n\n旧69C0/C1保存92運用、新P0/P1各46場の92運用、Viewer184。新派生木3・新回帰fit0・新分類fit0・新独立計測0。旧69C0の三保存木から約定支持だけで学習分割を剪定する。全60特徴・共通教師・66選択・68条件入口・O49保護は同じ。\n\n"
        "細分化を戻すと異なる価格文脈を混ぜ得る。支持の回復と先着score・回収改善は別で、結果の良さに合わせた閾値や葉を選ばない。\n\n")
    mechanics = ("## 固定した判断・条件入口・利益保護\n\nデイ09:15〜15:15の25枠、ナイト17:30〜05:30の49枠。両方向同じ60特徴・保存木、同点又は片側score未知はWAIT。両側資格を先に評価してscore>=1/3・filled支持・異種技法・回収支持を満たす側内で最高側を選ぶ。P1は主回収総額strict正も要求し、P0との同方向部分集合とは断定しない。raw DI0は最終WAIT。\n\n"
        "固定根はfloat32 F01<=0、低側R F26<=0.5／高側T F20<=0.5。DI非正にはfloat32零化が含まれるが、実役割はraw DIとの一致で決める。V1はbから有効でr/k成立を保証せず、V0は未登録・取消・期限・reset等の混合。固定trend+priceで技法資格は構造的に充足し、独立票の増加ではない。\n\n"
        "定時の最新公開完全3分足high/lowを凍結。買Last>high／売Last<lowで要求、設定既超過は拒否。買Last<=low／売Last>=highは発動前否定。設定否定は未登録WAIT、監視後前提否定は登録未約定で、否定自体は品質注意でない。normal BBO＋有限正Lastで監視し、gap>300秒観測不足を優先。次定時T+900でwatchと新規pendingを取消、発動後1価格時計秒・後行正常BBO・TTL30秒も次定時未満。発動後へ新否定を適用せず、足内順や過去線約定を補わない。\n\n"
        "主待ち=WAIT/全予定、保守=(WAIT＋判定不能＋条件登録後entryなし)/全予定で50%以下。保有継続は非待ち。純候補・発動・仮約定・実新規・完結は別分母。micro10円/pt、片道11円＋滑り5ptの往復122円。現在正常返済BBOの粗益−122円strict正で利益旗、最低名目新規床。Dは定時ATRを5pt切上げ・5..125制限。損失側も連続非緩和、返済pendingでh/L/arm凍結。名目床は実損や費用後同値を保証しない。強制15:35/05:50、終了15:40/05:55、残60停止なし・固定250TPなし。費用0/10感応は同約定・起動122円不変。\n\n")
    links = ("## 正本・再表示\n\n" + " / ".join(link(STUDY / n, brief) for n in ("設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json"))
        + " / " + link(HERE / "README.md", brief, "コードと再現") + " / " + link(OLD / "設定と結果.md", brief, "旧69C保存対照")
        + f'\n\n[Viewer](http://127.0.0.1:8092)：旧92＋新92＝184資源。保存監査{proof["照合項目数"]}照合・差{proof["不一致数"]}。監査範囲は保存JSONを正本とする。\n\n'
        "~~~powershell\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/レポート.py\nwork/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/支持を保つ技法群/レポート.py --check\n~~~\n")
    uses = settings(context)
    matrix = V5.matrix(V5.load_catalog(), detail, uses).replace("未使用", "未使用・未検証")
    features = table(["ID", "特徴", "手法", "family", "尺度", "式・範囲"], [[m["id"], m["name"], m["method"], m["family"], m["scale"], FORMULAS[i]] for i, m in enumerate(context["metadata"])])
    setting_rows = table(["設定ID", "手法/尺度", "設定内容", "限定"], [[x["設定ID"], "/".join(x["手法ID"]) + "・" + "/".join(x["尺度ID"]), x["短記"], x["説明"]] for x in uses])
    sources = table(["出典", "SHA256"], [[link(p, detail), sha(p)] for p in context["sources"]])
    external = ("## 原典と独自の支持剪定\n\nscikit-learn公式説明は少数例・深い細分化の過学習と剪定を扱うソフトウェア一次資料。市場心理の実測・NKの勝率保証ではない。公式のコスト複雑度剪定と、今回のfilled60枠・6日・10場を守る両側統合は別方式。心理は推論で、DI・価格・量を独立票へ数えない。" + link(EXTERNAL, detail, "読取範囲・既読との差・適用限界") + "。原典のモデル選択を評価期間へ持ち込まず、O49退出も変更しない。\n\n")
    overview = "# 00070：約定支持を保つ粒度で技法を組み合わせる\n\n" + intro + "## 条件入口先着\n\n" + entrance + "## 実一枚の回収\n\n" + operations + mechanics + links
    detailed = ("# 00070：設定と結果\n\n" + intro + "R01=旧C0、R02=旧C1、R03=P0、R04=P1。\n\n## 手法×尺度・版5全文\n\n55手法×9尺度を全文保持。複合評価を単独技法の効果としない。\n\n" + matrix
        + "## 同じ全60特徴\n\n新しい特徴列・教師・数量基準を追加しない。未知値0＋maskと教師未知の除外を分ける。b/r数量は同種・同限月の直近10完了場の同index基準、完全q5以上・平均正。一足価格差は現在ATRで尺度化し、量を方向票にしない。未登録・数量基準不足・既知0量とjointmaskは別。\n\n" + features + "## 設定明細\n\n" + setting_rows
        + common_table(context) + pruning_tables(context, detail) + model_tables(context, detail)
        + "## 条件入口先着\n\n" + entrance + "## 実一枚の回収\n\n" + operations + detail_tables(r) + mechanics + external
        + "## 検査・限界\n\n独立一枠教師の重複建玉合算は同時実行可能な戦略利益ではない。参照独立測定4092方向は旧69保存物であり今回計測ではない。新規と同じ独立回収の経済属性は正式保存監査で照合し、表示で再生しない。全66場既使用、11月5日Day未予約未読。新fitなしでも事後選択の限界があり、未見検証と呼ばない。\n\n入力検査：" + shown(r["入力検査"]) + "。今回検査：" + shown(r["検査"]) + "。\n\n## 保存出典\n\n" + sources + "## 再表示\n\n" + link(brief, detail, "概要と表示コマンド") + "\n")
    return {"README.md": overview, "設定と結果.md": detailed}


# ----------------------------------------

def model_tables(context: dict, output: Path) -> str:
    """三派生木の全node・全path・支持・二種類の回収平均を表示する。

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
    return ("## 三派生木の全nodeと全回収葉\n\n旧69C0の三phase保存木を支持だけで剪定し、P1はP0と同木。新fitは0。固定根はfloat32 F01<=0、低側RのF26<=0.5／高側TのF20<=0.5。"
        "元学習はDI非正子index0/25、DI正子index0/19を除く58列深さ2・全深さ4・minleaf60・seed51・方向重み0.5。70は元の閾値と親統計を再用する。"
        "V1はbから有効でr/k確認を意味しない。V0は未登録・取消・TTL等の混合。raw DI同値は最終WAIT、float32零化と混同しない。\n\n"
        + table(["保存木", "教師", "phase", "全node数", "回帰目的", "過去場", "評価場"], meta)
        + table(["木", "固定群", "対応", "全方向行", "unique枠", "日", "場", "元子root", "元子node数", "元fit"], parts)
        + "上の元子root/node数/fitはtraining.partitionに残る69の学習証拠であり、70の配置や新fitではない。新配置は剪定対応表を参照する。先着scoreは250/約定既知だけ、無取引0は回帰に含む。支持60枠・6日・10場も約定既知だけで、全回帰行のminleaf60とは異なる。固定trend+priceは従来技法資格を構造的に充足するが、独立証拠が増えたとはしない。\n\n"
        + table(["木", "node", "分岐・左<=右>", "左/右", "全path", "全回帰行", "filled行", "無取引行", "約定率", "条件付き先着score", "全unique/日/場", "filled unique/日/場", "filled葉支持", "path family", "技法資格"], nodes)
        + "回帰目的は無取引0込みpnl5のMSE。目的平均を先着確率とは呼ばず、方向順位は障壁score、両側資格を先に評価する固定66選択を維持する。同点・片側score未知はWAITで、0政策と正回収1政策は逆方向になり得る。\n\n"
        + table(["木", "node", "滑りpt", "回帰/障壁の状態", "全合計円", "全平均Decimal円", "filled合計円", "filled平均Decimal円", "元保存予測5円", "元保存MSE5円²", "元Decimal MSE5円²"], cash)
        + "全無取引葉は全平均0・MSE0が既知でもscoreとfilled平均はnull。空回帰葉は両平均・MSEともnull。親を葉へ統合しても平均・MSEはその旧親の保存値であり、新fit値ではない。固定三nodeは元学習器の生予測対象外で、所属からの統計と区別する。calのpositive=Falseは不適格であり空の平均0ではない。\n\n"
        + table(["木", "葉", "全行", "filled行", "filled unique/日/場", "約定率", "合計円0/5/10", "filled平均円0/5/10", "全平均円0/5/10", "回収支持", "主合計strict正"], calibrations))

def main_tables(result: dict) -> tuple[str, str]:
    """四政策の条件入口先着と一枚実回収を異なる分母で表示する。

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

def detail_tables(result: dict) -> str:
    """全期間・実役割・費用・判断理由と条件段階を保存値で表示する。

    引数: result(dict)は四政策の結果。
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
    spec = importlib.util.spec_from_file_location("支持剪定70表示の人工", HERE / "レポートの人工検査.py")
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
