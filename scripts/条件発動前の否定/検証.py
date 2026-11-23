"""同じ複数技法の定時候補で、発動前の反対端否定を比較する。"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00068_発動前の反対端否定で条件を取り消す"
WORK = ROOT / "work/条件発動前の否定/00068"
OLD = ROOT / "study/00067_定時候補を将来価格の突破で発動"
OLDWORK = ROOT / "work/定時候補の価格発動/00067"
LEDGER = ROOT / "work/定時候補の価格発動/67完了記録.json"
PREFLIGHT = ROOT / "work/条件発動前の否定/保存接続確認.json"
POLICIES, CONTROLS = ("N0", "N1"), ("G0", "G1")
PERIODS = ("学習", "条件選択", "後続検査")
EXTERNAL = ROOT / "docs/議論/外部再調査/突破の確認と取得位置と前提否定を分ける.md"


def load(path: Path, name: str):
    """固定コードを固有名で読み、大域設定を変更しない。

    引数: path(Path)はコード、name(str)は固有名。
    返り値: ModuleTypeは読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(HERE.parent / "定時候補の価格発動/検証.py", "価格発動の固定67")
P, C, O = PREVIOUS.P, PREVIOUS.C, PREVIOUS.O


def fingerprint(value: object) -> str:
    """保存辞書の値を順序によらない指紋へ写す。

    引数: value(object)は非NaN JSON互換値。
    返り値: strはSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def condition_for(slot: dict, frames: list[dict]) -> dict:
    """当時の最新公開3分足を銀行と照合し、価格線を凍結する。

    引数: slot(dict)は旧67純採用、frames(list[dict])は当場3分SOURCE。
    返り値: dictはhigh/low/source/expires。未来価格を条件へ含めない。
    """
    if not slot["side"] or not slot["ready"] or slot["line"] is None:
        raise ValueError("条件線は当時の準備済み純候補だけ")
    source = slot["feature"]["base"]["base"]["sources"]["current"]
    visible = [r for r in frames if r["publish"] and r["end"] <= slot["scheduled"]
        and r["confirm"] is not None and r["confirm_line"] is not None
        and (r["confirm"], r["confirm_line"]) <= (slot["time"], slot["line"])]
    if not visible:
        raise ValueError("当時可視3分足なし")
    latest = max(visible, key=lambda r: (r["end"], r["index"]))
    expected = {**latest, "session": slot["session"]}
    if source != expected or source["minutes"] != 3 or source["missing"] != 0:
        raise ValueError("保存現在足と当時最新完全3分足に差")
    if any(not O.finite(source[k]) or source[k] <= 0 for k in ("open", "high", "low", "close")):
        raise ValueError("凍結するOHLCが不正")
    if not source["low"] <= min(source["open"], source["close"]) <= max(source["open"], source["close"]) <= source["high"]:
        raise ValueError("凍結するOHLCの順序不正")
    expires = slot["scheduled"] + 900
    if not slot["time"] < expires < O.session_bounds(slot["session"])["force"]:
        raise ValueError("条件寿命が当場の新規可能範囲外")
    return {"high": source["high"], "low": source["low"], "source": deepcopy(source), "expires": expires}


def verified_saved_inputs() -> tuple:
    """旧成功証明と同じ純候補・当時出典を結合する。

    引数: なし。
    返り値: tupleは台帳、旧blocks、新blocks、条件、照合数。新予測・市場なし。
    """
    if C.sha(LEDGER) != "cc741ca48dc4efeac4a3732f070fce8c19aba599660dc414f42774cb254ca730":
        raise ValueError("67完了台帳指紋差")
    ledger, proof = C.read_json(LEDGER), C.read_json(OLD / "保存物確認.json")
    if not proof["全件一致"] or proof["不一致数"] or C.sha(OLD / "結果.json") != proof["結果SHA256"]:
        raise ValueError("67成功証明差")
    for relative, expected in ledger["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("67完了物変更:" + relative)
    manifest, sessions = C.inputs()
    frames = {s["session"]: s["frames3"] for s in sessions}
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    if len(old_blocks) != 92 or {b["policy"] for b in old_blocks} != set(CONTROLS):
        raise ValueError("旧67対照92運用の範囲差")
    blocks, conditions = {}, {}
    checks = {"旧67純判断一致": 0, "当時最新3分出典一致": 0, "同一条件実仮新規一致": 0}
    for old in old_blocks:
        policy = POLICIES[CONTROLS.index(old["policy"])]
        slots, frozen = [], {}
        if [s["scheduled"] for s in old["slots"]] != O.scheduled_times(old["session"]):
            raise ValueError("全予定25又は49枠の保存差")
        for prior in old["slots"]:
            slot = {**deepcopy(prior), "policy": policy}
            if {**slot, "policy": old["policy"]} != prior:
                raise ValueError("旧純候補の属性変化")
            slots.append(slot)
            checks["旧67純判断一致"] += 1
            if slot["side"]:
                frozen[slot["slot_id"]] = condition_for(slot, frames[old["session"]])
                if frozen[slot["slot_id"]] != old["conditions"][slot["slot_id"]]:
                    raise ValueError("旧67保存条件と最新足再結合の差")
                checks["当時最新3分出典一致"] += 1
        key = (old["session"], policy)
        blocks[key] = {"session": old["session"], "policy": policy, "phase": old["phase"], "slots": slots}
        conditions[key] = frozen
    if checks["旧67純判断一致"] != 3404 or checks["当時最新3分出典一致"] != 488:
        raise ValueError("旧純枠3404又は純候補488の範囲差")
    return manifest["entries"], old_blocks, blocks, conditions, checks


def preflight() -> None:
    """条件の出典だけを先に照合し、市場結果を見ずに保存する。

    引数: なし。
    返り値: None。新fit・新予測・特徴再計算・市場再生なし。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("68保存接続は既存")
    entries, _, blocks, conditions, checks = verified_saved_inputs()
    C.write_json(PREFLIGHT, {"試行": 68, "接続成功": True, "検査": checks,
        "評価場": [e["session"] for e in entries[20:]],
        "新純候補指紋": {p: fingerprint([b for (_, q), b in blocks.items() if q == p]) for p in POLICIES},
        "条件指紋": {p: fingerprint({s: c for (s, q), c in conditions.items() if q == p}) for p in POLICIES},
        "条件数": {p: sum(len(c) for (_, q), c in conditions.items() if q == p) for p in POLICIES},
        "新fit": False, "新予測": False, "特徴再計算": False, "市場再生": False})
    print(json.dumps({"接続成功": True, "検査": checks}, ensure_ascii=False), flush=True)


# ----------------------------------------
# 新しい活動被覆と、旧方式と同じ会計・支持を分ける。

def operation_stats(operations: list[dict], period: str) -> dict:
    """旧会計集計へ条件未約定の保守待ちを加える。

    引数: operations(list[dict])は新運用、period(str)は期間。
    返り値: dictはC49互換項目と新しい条件登録被覆。
    """
    result = C.operation_stats(operations, period)
    chosen = [o for o in operations if C.period(o["session"]) == period]
    registered = sum(o["metrics"]["条件登録数"] for o in chosen)
    unfilled = sum(o["metrics"]["条件未約定"] for o in chosen)
    n = result["予定枠"]
    numerator = result["待ち数"] + result["判定不能"] + unfilled
    result.update(条件登録数=registered, 条件未約定=unfilled,
        待ち率保守上限=numerator / n if n else None,
        活動適格=bool(n) and numerator * 2 <= n)
    return result


def stage_stats(slots: list[dict], labels: list[dict], operations: list[dict], period: str) -> dict:
    """純候補から実参加までの別分母を保存する。

    引数: slots/labels/operations(list[dict])は判断・仮想・実運用、period(str)は期間。
    返り値: dictは条件段階。未発動を実保有へ足さない。
    """
    ss = [s for s in slots if C.period(s["session"]) == period]
    ll = [r for r in labels if C.period(r["session"]) == period]
    oo = [o for o in operations if C.period(o["session"]) == period]
    return {"全予定枠": len(ss), "純候補": sum(bool(s["side"]) for s in ss),
        "条件結果別": dict(Counter(r["condition_outcome"] for r in ll)),
        "発動": sum(r.get("trigger") is not None for r in ll), "仮約定": sum(r["filled"] for r in ll),
        "実条件登録": sum(o["metrics"]["条件登録数"] for o in oo),
        "実新規": sum(t["type"] in ("LongN", "ShortN") for o in oo for t in o["trades"]),
        "実登録未約定": sum(o["metrics"]["条件未約定"] for o in oo)}


def comparison_stats(new: list[dict], old: list[dict], period: str) -> dict:
    """同じ純候補で新旧仮想入口の被覆と取得位置を比べる。

    引数: new/old(list[dict])は否定あり/なしの条件ラベル、period(str)は期間。
    返り値: dictは全候補結果対と両約定の価格差。両約定だけを全体効果としない。
    """
    before = {r["slot_id"]: r for r in old if C.period(r["session"]) == period}
    after = [r for r in new if C.period(r["session"]) == period]
    if {r["slot_id"] for r in after} != set(before):
        raise ValueError("同じ純候補の比較母数差")
    pairs = [(r, before[r["slot_id"]]) for r in after]
    both = [(a, b) for a, b in pairs if a["filled"] and b["filled"]]
    differences = [O.signed_distance(a["side"], a["entry_price"], b["entry_price"]) for a, b in both]
    return {"同じ純候補": len(pairs), "両約定": len(both),
        "旧のみ約定": sum(b["filled"] and not a["filled"] for a, b in pairs),
        "新のみ約定": sum(a["filled"] and not b["filled"] for a, b in pairs),
        "結果対": dict(Counter(b["outcome"] + "→" + a["condition_outcome"] + "/" + a["outcome"] for a, b in pairs)),
        "両約定の平均追随pt": sum(differences) / len(both) if both else None,
        "両約定の平均取得遅延秒": sum(a["entry_time"] - b["entry_time"] for a, b in both) / len(both) if both else None}



def denial_stats(new: list[dict], old: list[dict], period: str) -> dict:
    """否定だけが独立仮参加を除くことを全属性で確認する。

    引数: new/old(list[dict])は新旧条件ラベル、period(str)は期間。
    返り値: dictは否定群と残存群の対応。事後集合を当時の入力に戻さない。
    """
    before = {r["slot_id"]: r for r in old if C.period(r["session"]) == period}
    after = [r for r in new if C.period(r["session"]) == period]
    if {r["slot_id"] for r in after} != set(before):
        raise ValueError("否定比較の全純候補差")
    denied, retained, filled = [], [], []
    for row in after:
        prior = before[row["slot_id"]]
        if row["condition_outcome"] in ("設定否定", "前提否定"):
            if row["filled"] or row["trigger"] is not None or row["watch_quality"]:
                raise ValueError("否定は発動前かつ品質注意と別")
            denied.append((row, prior))
        else:
            if {**row, "policy": prior["policy"]} != prior:
                raise ValueError("否定以外の独立先着変化")
            retained.append(row)
        if row["filled"]:
            if not prior["filled"] or any(row[k] != prior[k] for k in ("entry_time", "entry_line", "entry_price", "outcome", "end_time", "end_line", "mfe", "mae")):
                raise ValueError("残存仮約定は旧67と同一")
            filled.append(row)
    return {"同じ純候補": len(after), "設定否定": sum(r["condition_outcome"] == "設定否定" for r in after),
        "前提否定": sum(r["condition_outcome"] == "前提否定" for r in after), "非否定の全属性一致": len(retained),
        "否定群の旧結果": dict(Counter(b["condition_outcome"] + "/" + b["outcome"] for _, b in denied)),
        "旧仮約定の除外": sum(b["filled"] for _, b in denied),
        "旧250の除外": sum(b["outcome"] == "250" for _, b in denied),
        "旧125の除外": sum(b["outcome"] == "125" for _, b in denied),
        "両約定の時刻価格結果一致": len(filled), "新のみ仮約定": 0}


def freeze() -> None:
    """人工成功と旧保存証拠を本物実行前に固定する。

    引数: なし。
    返り値: None。既存固定の上書きを拒否する。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("68固定済み")
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"]:
        raise ValueError("人工未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工後コード変更:" + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(C.read_json(LEDGER)["成果物SHA256"])
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("旧固定物変更:" + relative)
    paths = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"),
        STUDY / "検証計画.md", PREFLIGHT, LEDGER, EXTERNAL]
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    C.write_json(STUDY / "固定.json", {"試行": 68, "固定日時": datetime.now(C.JST).isoformat(),
        "本物運用前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "新fit": False})
    print("68を条件入口の本物評価前に固定しました", flush=True)


def verify_lock() -> None:
    """固定出典の指紋を検査する。

    引数: なし。
    返り値: None。不一致なら例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("固定後変更:" + relative)


def run() -> None:
    """新条件入口と92運用を一度だけ再生する。

    引数: なし。
    返り値: None。既存開始記録があれば再起動しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("68は開始済み。既存handleを確認")
    verify_lock()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    engine = load(HERE / "運用.py", "価格発動68本物運用")
    labels_module = load(HERE / "先着.py", "価格発動68独立先着")
    entries, old_blocks, blocks, conditions, checks = verified_saved_inputs()
    prior, old_result = C.read_json(PREFLIGHT), C.read_json(OLD / "結果.json")
    if checks != prior["検査"]:
        raise ValueError("固定前後接続差")
    for policy in POLICIES:
        if fingerprint([b for (_, q), b in blocks.items() if q == policy]) != prior["新純候補指紋"][policy]:
            raise ValueError("純候補指紋差")
        if fingerprint({s: c for (s, q), c in conditions.items() if q == policy}) != prior["条件指紋"][policy]:
            raise ValueError("条件指紋差")
    operations = {p: [b["operation"] for b in old_blocks if b["policy"] == p] for p in CONTROLS}
    old_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {p: [r for r in old_labels if r["policy"] == p] for p in CONTROLS}
    saved_slots = {p: [s for b in old_blocks if b["policy"] == p for s in b["slots"]] for p in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy], saved_slots[policy] = [], [], []
    resources = [deepcopy(r) for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in CONTROLS]
    summaries = []
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for entry in entries[20:]:
            session = entry["session"]
            events, quality = C.events_for(entry)
            indexed = labels_module.prepare_events(events)
            bounds = O.session_bounds(session)
            for policy in POLICIES:
                block, frozen = blocks[session, policy], conditions[session, policy]
                slots = block["slots"]
                saved_slots[policy].extend(slots)
                local_labels = [labels_module.label(indexed, slot, frozen[slot["slot_id"]], bounds["force"], bounds["end"])
                    for slot in slots if slot["side"]]
                labels[policy].extend(local_labels)
                operation = engine.replay(events, [{key: s[key] for key in O.SLOT_FIELDS} for s in slots], frozen, session, policy)
                by_id = {r["slot_id"]: r for r in local_labels}
                for order in operation["orders"]:
                    if order["kind"] != "entry" or order["status"] != "filled":
                        continue
                    label = by_id[order["slot"]["slot_id"]]
                    if not label["filled"] or (label["entry_time"], label["entry_line"], label["entry_price"]) != (order["fill_time"], order["fill_line"], order["fill_price"]):
                        raise ValueError("条件入口の実新規と独立仮約定に差")
                    checks["同一条件実仮新規一致"] += 1
                operations[policy].append(operation)
                C.jsonline(stream, {**block, "input_quality": quality, "conditions": frozen, "operation": operation})
                path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as trades:
                    for trade in operation["trades"]:
                        C.jsonline(trades, trade)
                resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 定時候補の価格発動",
                    "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy, "point_value": 10,
                    "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                    "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            print(session + " 条件先着と2運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    table = {}
    for policy in (*CONTROLS, *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance = labels_module.entry_stats(labels[policy], period, C.period)
            operation = operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("67保存対照の集計差")
    result = {"試行": 68, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table,
        "モデル": old_result["モデル"], "回収集計": old_result["回収集計"], "対照モデル": old_result["モデル"],
        "新回帰器fit": 0, "新分類器fit": 0, "新保存木数": 0, "参照モデル数": 3,
        "新独立計測": 0, "新条件入口評価": sum(len(labels[p]) for p in POLICIES), "新運用数": 92,
        "検査": checks, "旧証明検査": old_result["検査"],
        **{key: old_result[key] for key in PREVIOUS.PREVIOUS.REFERENCE_KEYS},
        "学習参照": {"元試行": 65, "新fit": False, "教師再生成": False, "特徴再計算": False,
            "モデル同一": True, "回収集計同一": True, "旧即時入口の教師": True, "新条件入口を学習したか": False},
        "対照参照": {"候補": list(CONTROLS), "元試行": 67, "同じ評価46場": True, "市場再生": False},
        "条件段階": {p: {t: stage_stats(saved_slots[p], labels[p], operations[p], t) for t in PERIODS} for p in POLICIES},
        "入口取得比較": {p: {t: comparison_stats(labels[p], labels[c], t) for t in PERIODS} for p, c in zip(POLICIES, CONTROLS)},
        "否定比較": {p: {t: denial_stats(labels[p], labels[c], t) for t in PERIODS} for p, c in zip(POLICIES, CONTROLS)},
        "役割別入口": {p: {t: {role: (labels_module.entry_stats(
            [r for r in labels[p] if r["role"] == role], t, C.period)) for role in ("順行", "反転")} for t in PERIODS} for p in (*CONTROLS, *POLICIES)},
        "判断理由": {p: {t: dict(Counter(s["reason"] for s in saved_slots[p] if C.period(s["session"]) == t)) for t in PERIODS} for p in POLICIES},
        "場別": summaries, "採用": [p for p in POLICIES if all(table[p][t]["同時適格"] for t in PERIODS[:2])],
        "詳細": {path.name: C.sha(path) for path in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新運用数": 92, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """保存接続・固定・本物運用のCLIを分ける。

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
