"""保存65の同じ木・特徴・回収で、適格な方向から先着最高側を選ぶ。"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import gzip
import importlib.util
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00066_複数手法の適格方向から優先側を選ぶ"
WORK = ROOT / "work/適格方向の選択/00066"
OLD = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
OLDWORK = ROOT / "work/状態と判断/00065"
COMPLETE = ROOT / "work/状態と判断/65完了記録.json"
PREFLIGHT = ROOT / "work/適格方向の選択/保存接続確認.json"
POLICIES, CONTROLS = ("E0", "E1"), ("U0", "U1")
PERIODS = ("学習", "条件選択", "後続検査")
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"
BASELINE = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
REFERENCE_KEYS = ("評価場", "学習専用場", "準備比較", "旧教師一致", "教師集合一致", "独立測定",
    "価格経路分布", "経路支持", "状態分布", "局面分布", "数量分布", "独立測定参照")


def load(path: Path, name: str):
    """固定コードを独自名で読み、元の大域設定を変更しない。

    引数: path(Path)はコード、name(str)は固有名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(HERE.parent / "現在状態と量価格/検証.py", "適格方向の固定65主")
P55, P, C, O, R, F = PREVIOUS.P55, PREVIOUS.P, PREVIOUS.C, PREVIOUS.O, PREVIOUS.R, PREVIOUS.F
L = load(HERE.parent / "現在状態と量価格/学習.py", "適格方向の固定65走査")


def verified_saved_inputs() -> tuple:
    """65成功証明へ保存入力を結び、旧判断と同60特徴を全枠照合する。

    引数: なし。
    返り値: tupleはentries/blocks/prepared/baseline/measured/old_blocks/models/calibrations/checks。
    """
    proof, ledger = C.read_json(OLD / "保存物確認.json"), C.read_json(COMPLETE)
    if not proof["全件一致"] or proof["不一致数"] or C.sha(OLD / "結果.json") != proof["結果SHA256"]:
        raise ValueError("65成功証明が不成立")
    for relative, expected in ledger["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("65完了物変更:" + relative)
    old = C.read_json(OLD / "結果.json")
    entries = C.read_json(C.MANIFEST)["entries"]
    if len(entries) != 66 or any(e["symbol"] != "NK225" for e in entries):
        raise ValueError("固定NK225の66場が必要")
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    if len(old_blocks) != 92 or {b["policy"] for b in old_blocks} != set(CONTROLS):
        raise ValueError("65保存92運用の範囲差")
    blocks = {b["session"]: b for b in old_blocks if b["policy"] == "U0"}
    prepared = {s["slot_id"]: s["feature"] for b in blocks.values() for s in b["slots"]}
    if len(blocks) != 46 or len(prepared) != 1702:
        raise ValueError("評価46場1702枠の範囲差")
    models = {m["phase"]: C.read_json(ROOT / m["path"]) for m in old["モデル"]}
    calibrations = {m["phase"]: C.read_json(ROOT / m["path"]) for m in old["回収集計"]}
    for meta in old["モデル"] + old["回収集計"]:
        if C.sha(ROOT / meta["path"]) != meta["SHA256"]:
            raise ValueError("65参照木又は回収集計の差")
    checks = {"旧65特徴保存一致": 0, "旧65純判断一致": 0, "同一新規完結一致": 0}
    for block in old_blocks:
        expected = PREVIOUS.slots_for(block, prepared, models[block["phase"]], calibrations[block["phase"]],
            L, block["policy"], block["phase"])
        if expected != block["slots"]:
            raise ValueError("保存65純判断の全属性に差")
        for slot in block["slots"]:
            if prepared[slot["slot_id"]] != slot["feature"]:
                raise ValueError("保存65全60辞書に差")
            checks["旧65特徴保存一致"] += 1
            checks["旧65純判断一致"] += 1
    baseline = {(r["slot_id"], r["side"]): r for r in P.read_rows(BASELINE) if r["policy"] in ("B+", "B-")}
    measured = {(r["slot_id"], r["side"]): r for r in P.read_rows(MEASUREMENTS)}
    if len(baseline) != 4366 or len(measured) != 4884:
        raise ValueError("旧49準備済み入口4366方向又は旧55全4884方向の範囲差")
    if any((identity, side) not in baseline for identity, feature in prepared.items() if feature["ready"] for side in (1, -1)):
        raise ValueError("新評価の準備済み枠に旧49先着がない")
    return entries, blocks, prepared, baseline, measured, old_blocks, models, calibrations, checks


def preflight() -> None:
    """新選択を計算せず、保存物の接続だけを固定前に確認する。

    引数: なし。
    返り値: None。特徴再算・教師再生成・fit・新市場運用なし。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("66接続確認は既存")
    entries, _, prepared, _, _, _, models, calibrations, checks = verified_saved_inputs()
    C.write_json(PREFLIGHT, {"試行": 66, "接続成功": True, "検査": checks,
        "評価全特徴SHA256": L.fingerprint(prepared), "評価場": [e["session"] for e in entries[20:]],
        "モデル指紋": {key: L.fingerprint(value) for key, value in models.items()},
        "回収集計指紋": {key: L.fingerprint(value) for key, value in calibrations.items()},
        "新予測": False, "本物fit": False, "特徴再計算": False, "教師再生成": False, "市場再生": False})
    print(json.dumps({"接続成功": True, "検査": checks, "参照モデル数": len(models)}, ensure_ascii=False), flush=True)


def slots_for(block: dict, model: dict, calibration: dict, selector, policy: str) -> list:
    """同じ当時特徴へ適格集合内の選択を適用する。

    引数: block/model/calibration(dict)は保存入力、selector(ModuleType)は選択器、policy(str)はE0/E1。
    返り値: list[dict]は旧入力全辞書と両側資格を伴う新純判断。
    """
    if policy not in POLICIES:
        raise ValueError("66政策が不正")
    result = []
    for old in block["slots"]:
        feature = old["feature"]
        prediction = selector.predict(model, calibration, feature["vectors"], L, policy) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == feature["background_direction"] else "反転" if side else "待機"
        result.append({**{key: old[key] for key in ("session", "slot_id", "scheduled", "time", "line", "phase", "model_id")},
            "policy": policy, "side": side, "role": role, "ready": feature["ready"], "reason": reason,
            "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": prediction})
    return result


def selection_stats(new: list, old: list) -> dict:
    """同じ予定枠で純参加の差を数え、旧予測全辞書との接続を確認する。

    引数: new/old(list[dict])は同じ期間の新旧slots。
    返り値: dictは分母・同方向共通・追加・除外・方向変更と追加時の旧理由。
    """
    before = {s["slot_id"]: s for s in old}
    if len(before) != len(new) or {s["slot_id"] for s in new} != set(before):
        raise ValueError("純比較の予定枠差")
    pairs = [(s, before[s["slot_id"]]) for s in new]
    for after, prior in pairs:
        if after["feature"] != prior["feature"] or (after["prediction"]["reference"] if after["prediction"] else None) != prior["prediction"]:
            raise ValueError("新選択の旧予測referenceに差")
        if prior["side"] and after["side"] != prior["side"]:
            raise ValueError("旧適格純採用が新方式で失われた")
    added = [(a, b) for a, b in pairs if a["side"] and not b["side"]]
    return {"全予定枠": len(new), "特徴準備枠": sum(s["ready"] for s in new),
        "旧純採用": sum(bool(s["side"]) for s in old), "新純採用": sum(bool(s["side"]) for s in new),
        "共通同方向": sum(bool(a["side"]) and a["side"] == b["side"] for a, b in pairs),
        "追加純候補": len(added), "除外純候補": sum(bool(b["side"]) and not a["side"] for a, b in pairs),
        "反対変更": sum(bool(a["side"] and b["side"]) and a["side"] != b["side"] for a, b in pairs),
        "追加時旧理由": dict(Counter(b["reason"] for _, b in added)),
        "予測救済": sum(bool(s["prediction"] and s["prediction"]["rescued"]) for s in new),
        "DI同値で拒否": sum(bool(s["prediction"] and s["prediction"]["side"] and not s["side"]) for s in new)}


# ----------------------------------------
# 固定前の人工と、単一の市場運用を分ける。

def freeze() -> None:
    """人工・旧成功証明・条件を新運用前に固定する。

    引数: なし。
    返り値: None。既存固定や人工後のコード変更は拒否する。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("66は固定済み")
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"] or not artificial["監査人工"]["人工成功"]:
        raise ValueError("66人工が未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工後の変更:" + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(C.read_json(COMPLETE)["成果物SHA256"])
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("旧固定物変更:" + relative)
    paths = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md", PREFLIGHT, COMPLETE,
        ROOT / "docs/議論/外部再調査/候補の成立と方向の優先順位を分ける.md"]
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    C.write_json(STUDY / "固定.json", {"試行": 66, "固定日時": datetime.now(C.JST).isoformat(),
        "本物運用前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "新fit": False})
    print("66を新運用前に固定しました", flush=True)


def verify_lock() -> None:
    """全固定出典を内容指紋で確認する。

    引数: なし。
    返り値: None。不一致なら例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("固定後変更:" + relative)


def run() -> None:
    """保存木を参照し、新2政策92運用を一度だけ実行する。

    引数: なし。
    返り値: None。開始記録が既存なら再起動しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("66開始済み。既存handleを確認すること")
    verify_lock()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    selector = load(HERE / "選択.py", "適格方向66の本物選択")
    entries, blocks, prepared, baseline, measured, old_blocks, models, calibrations, checks = verified_saved_inputs()
    prior, old_result = C.read_json(PREFLIGHT), C.read_json(OLD / "結果.json")
    if L.fingerprint(prepared) != prior["評価全特徴SHA256"] or checks != prior["検査"]:
        raise ValueError("固定前後の保存接続差")
    if ({k: L.fingerprint(v) for k, v in models.items()} != prior["モデル指紋"]
            or {k: L.fingerprint(v) for k, v in calibrations.items()} != prior["回収集計指紋"]):
        raise ValueError("参照モデル又は回収集計に差")
    operations = {p: [b["operation"] for b in old_blocks if b["policy"] == p] for p in CONTROLS}
    old_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {p: [row for row in old_labels if row["policy"] == p] for p in CONTROLS}
    saved_slots = {p: [s for b in old_blocks if b["policy"] == p for s in b["slots"]] for p in CONTROLS}
    old_by_session = {(b["session"], b["policy"]): b["slots"] for b in old_blocks}
    for policy in POLICIES:
        operations[policy], labels[policy], saved_slots[policy] = [], [], []
    resources = [deepcopy(r) for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in CONTROLS]
    summaries = []
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            model, calibration = models[phase["id"]], calibrations[phase["id"]]
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                for policy in POLICIES:
                    slots = slots_for(blocks[session], model, calibration, selector, policy)
                    selection_stats(slots, old_by_session[session, CONTROLS[POLICIES.index(policy)]])
                    saved_slots[policy].extend(slots)
                    labels[policy].extend({**baseline[s["slot_id"], s["side"]], "policy": policy, "role": s["role"]} for s in slots if s["side"])
                    operation = O.replay(events, [{key: s[key] for key in O.SLOT_FIELDS} for s in slots], session, policy)
                    for close in operation["closed"]:
                        expected = measured[close["slot_id"], close["side"]]["operation"]["closed"]
                        if len(expected) != 1 or not P55.equivalent_close(close, expected[0]):
                            raise ValueError("新運用と旧55同一新規回収に差")
                        checks["同一新規完結一致"] += 1
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "policy": policy, "phase": phase["id"],
                        "input_quality": quality, "slots": slots, "operation": operation})
                    path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 複数手法の適格方向から優先側を選ぶ",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy, "point_value": 10,
                        "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                print(session + " 適格方向2運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    table, comparison = {}, {}
    for policy in (*CONTROLS, *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance, operation = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("65保存対照の集計に差")
    for policy, control in zip(POLICIES, CONTROLS):
        comparison[policy] = {period: selection_stats([s for s in saved_slots[policy] if C.period(s["session"]) == period],
            [s for s in saved_slots[control] if C.period(s["session"]) == period]) for period in PERIODS}
    cross = {}
    for period in PERIODS:
        pair = {p: {s["slot_id"]: s["side"] for s in saved_slots[p] if C.period(s["session"]) == period} for p in POLICIES}
        cross[period] = {"全予定枠": len(pair["E0"]),
            "両採用同方向": sum(bool(v) and v == pair["E1"][k] for k, v in pair["E0"].items()),
            "両採用逆方向": sum(bool(v and pair["E1"][k]) and v != pair["E1"][k] for k, v in pair["E0"].items()),
            "E0のみ採用": sum(bool(v) and not pair["E1"][k] for k, v in pair["E0"].items()),
            "E1のみ採用": sum(not v and bool(pair["E1"][k]) for k, v in pair["E0"].items())}
    result = {"試行": 66, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": old_result["モデル"], "回収集計": old_result["回収集計"],
        "対照モデル": old_result["モデル"], "新回帰器fit": 0, "新分類器fit": 0, "新保存木数": 0, "参照モデル数": 3,
        "新独立計測": 0, "新運用数": 92, "検査": checks, "旧証明検査": old_result["検査"],
        **{key: old_result[key] for key in REFERENCE_KEYS},
        "学習参照": {"元試行": 65, "新fit": False, "教師再生成": False, "特徴再計算": False, "モデル同一": True, "回収集計同一": True},
        "対照参照": {"候補": list(CONTROLS), "元試行": 65, "同じ評価46場": True, "市場再生": False},
        "選択比較": comparison, "新候補方向差": cross,
        "役割別入口": {p: {t: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], t) for role in ("順行", "反転")} for t in PERIODS} for p in (*CONTROLS, *POLICIES)},
        "判断理由": {p: {t: dict(Counter(s["reason"] for s in saved_slots[p] if C.period(s["session"]) == t)) for t in PERIODS} for p in POLICIES},
        "場別": summaries, "採用": [p for p in POLICIES if all(table[p][t]["同時適格"] for t in PERIODS[:2])],
        "詳細": {path.name: C.sha(path) for path in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新fit": 0, "新運用数": 92, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """保存接続・固定・新運用をCLIで分ける。

    引数: CLIの--preflight/--freeze/--run。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    preflight() if args.preflight else freeze() if args.freeze else run()


if __name__ == "__main__":
    main()
