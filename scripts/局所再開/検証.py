"""固定49基盤を変更せず、局所再開の新入口だけを比較する。"""

import argparse
from bisect import bisect_left
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
STUDY = ROOT / "study/00050_15分定時の局所再開"
WORK = ROOT / "work/局所再開/00050"
OLD = ROOT / "study/00049_15分定時の序盤帯反応"
OLDWORK = ROOT / "work/定時帯反応/00049"
POLICIES = ("P0", "P1")
PERIODS = ("学習", "条件選択", "後続検査")


def load(path: Path, name: str):
    """固定された純関数を固有名で読み込む。

    引数: path(Path)はコード、name(str)は衝突を避ける名前。
    返り値: ModuleTypeは読込結果。旧モジュールの大域値を変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load(ROOT / "scripts/定時帯反応/検証.py", "局所再開_固定49検証")
I49 = load(ROOT / "scripts/定時帯反応/入口.py", "局所再開_固定49入口")
O = load(ROOT / "scripts/定時帯反応/運用.py", "局所再開_固定49運用")


def records(path: Path) -> list[dict]:
    """既存の圧縮正本を行順を保って読む。

    引数: path(Path)はJSONL.gz。
    返り値: list[dict]は保存行。市場再生は行わない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def freeze() -> None:
    """旧基盤の固定を継承し、新入口と帳票の版を結果前に固定する。

    引数: なし。
    返り値: None。既存固定は上書きしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("固定済みです")
    old_lock = C.read_json(OLD / "固定.json")
    pins = dict(old_lock["ファイルSHA256"])
    for rel, expected in pins.items():
        if C.sha(ROOT / rel) != expected:
            raise ValueError("旧固定の変更: " + rel)
    files = [STUDY / "検証計画.md", STUDY / "条件.json", STUDY / "入力台帳.json", STUDY / "人工確認.json",
             *sorted(Path(__file__).parent.glob("*.py")), Path(__file__).with_name("入口仕様.md"),
             Path(__file__).with_name("README.md"), OLD / "固定.json", OLD / "結果.json",
             OLD / "人工確認.json", OLD / "保存物確認.json", OLD / "期限同秒確認.json", OLD / "一覧.resources.json",
             ROOT / "scripts/定時帯反応/期限同秒確認.py",
             OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz",
             ROOT / "docs/議論/外部再調査/局所の調整完了と再開の条件.md"]
    files += sorted((OLD / "viewer").glob("*_S1.trades.jsonl"))
    for path in files:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    C.write_json(STUDY / "固定.json", {"固定日時": datetime.now(C.JST).isoformat(),
        "市場実行前": True, "全66場既使用": True, "Python": platform.python_version(),
        "NumPy": C.np.__version__, "ファイルSHA256": pins})
    print("試行50の条件・入口・固定49基盤を固定しました")


def verify_lock() -> None:
    """新旧すべての指紋を照合する。

    引数: なし。
    返り値: None。不整合は例外。
    """
    for rel, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / rel) != expected:
            raise ValueError("固定後変更: " + rel)


def make_slots(events: list[dict], session: str, bank: dict, signals_module) -> dict:
    """旧予定格子と最初の価格時計を、新入口の状態遷移へ渡す。

    引数: events(list[dict])は価格イベント、session(str)は場、bank(dict)は数値足、
        signals_module(ModuleType)は新入口。
    返り値: dictはP0/P1別の全予定枠。欠測でも消費処理を呼ぶ。
    """
    machine = signals_module.SessionSignals(bank, session)
    times = [e["now"] for e in events]
    result = {p: [] for p in POLICIES}
    for scheduled in O.scheduled_times(session):
        index = bisect_left(times, scheduled)
        event = events[index] if index < len(events) and times[index] <= scheduled + 30 else None
        time, line = (event["now"], event["line"]) if event else (scheduled, None)
        features = machine.evaluate(scheduled, time, line, event is not None and C.normal(event))
        if set(features) != set(POLICIES):
            raise ValueError("入口の候補集合が不一致")
        for policy in POLICIES:
            result[policy].append({**features[policy], "scheduled": scheduled, "time": time, "line": line,
                "slot_id": f"{session}_{int(scheduled)}", "session": session, "policy": policy})
    return result


def diagnostics(slots: list[dict], operations: list[dict], labels: list[dict], baseline: list[dict]) -> dict:
    """全枠の理由と同時刻基準を保存値から集計する。

    引数: slots(list[dict])は新入口、operations(list[dict])は実運用、labels(list[dict])は先着、
        baseline(list[dict])は固定49のB+/B−先着。
    返り値: dictは区分別の被覆と同時刻の実方向・逆方向先着。
    """
    output = {}
    indexed = {(r["slot_id"], r["side"]): r for r in baseline if r["policy"] in ("B+", "B-")}
    for period in PERIODS:
        chosen = [s for s in slots if C.period(s["session"]) == period]
        selected = [s for s in chosen if s["ready"] and s["side"]]
        paired = {"実方向": [], "逆方向": []}
        for slot in selected:
            for key, sign in (("実方向", 1), ("逆方向", -1)):
                row = indexed[(slot["slot_id"], sign * slot["side"])]
                if (row["time"], row["line"]) != (slot["time"], slot["line"]):
                    raise ValueError("時刻基準との時計不一致")
                paired[key].append(row)
        decisions = [d for b in operations if C.period(b["session"]) == period for d in b["decisions"]]
        actions = [a for s in chosen for a in s.get("diagnostic", {}).get("actions", [])]
        consumed = [e for s in chosen for e in s.get("diagnostic", {}).get("consumed_events", [])]
        ages = [e["age_seconds"] for e in consumed]
        stages = Counter()
        for slot in chosen:
            diag = slot.get("diagnostic", {})
            current, upper, band = slot.get("current"), slot.get("upper", {}), slot.get("OR")
            background = bool(current and band and band.get("ready") and upper.get("ready") and (
                current["close"] > band["high"] + 5 and upper["direction"] == 1 or
                current["close"] < band["low"] - 5 and upper["direction"] == -1))
            stage = ("判定不能" if not slot["ready"] else "純入口" if slot["side"] else
                "同枠競合" if slot["reason"] == "同枠複数発動WAIT" else
                "発動済みだが失効" if diag.get("consumed_events") else
                "T再開監視中" if diag.get("T_watch") else
                "R復帰又は確認監視中" if slot["policy"] == "P1" and diag.get("R_watch") else
                "T背景あり調整待ち" if background else "T背景不成立かつ発動なし")
            stages[stage] += 1
        output[period] = {"予定枠": len(chosen), "入口理由": dict(Counter(s["reason"] for s in chosen)),
            "純入口": len(selected), "純入口役割": dict(Counter(s["role"] for s in selected)),
            "実判断": dict(Counter(d["action"] for d in decisions)),
            "機会段階": dict(stages), "足遷移": dict(Counter(a["action"] for a in actions)),
            "消費発動数": len(consumed), "消費時有効発動数": sum(e["active"] for e in consumed),
            "消費時失効理由": dict(Counter(e["cancel_reason"] for e in consumed if not e["active"])),
            "消費発動の古さ秒": {"件数": len(ages), "平均": sum(ages) / len(ages) if ages else None,
                                "最大": max(ages) if ages else None},
            "同時刻基準": {key: C.entry_stats(rows, period) for key, rows in paired.items()}}
    return output


# ----------------------------------------
# 市場計算は固定後に一度だけ行い、対照は保存物を参照する。

def run() -> None:
    """新P0/P1だけを再生し、旧S1は完全な保存対照として接続する。

    引数: なし。
    返り値: None。開始済み又は結果存在時は再実行を拒否する。
    """
    if (STUDY / "結果.json").exists() or (WORK / "実行開始.json").exists():
        raise FileExistsError("既に開始済みです。プロセスと成果物を確認してください")
    verify_lock()
    manifest, sessions = C.inputs()
    bank = I49.build_bank(sessions)
    signals_module = load(Path(__file__).with_name("入口.py"), "局所再開_新入口")
    baseline = records(OLDWORK / "入口先着.jsonl.gz")
    old_result = C.read_json(OLD / "結果.json")
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    labels, operations, all_slots = ({p: [] for p in POLICIES} for _ in range(3))
    resources, summaries = [], []
    old_catalog = C.read_json(OLD / "一覧.resources.json")
    for item in old_catalog["resources"]:
        if item["method_id"] == "S1":
            path = (OLD / item["pnl_path"]).resolve().relative_to(ROOT.resolve()).as_posix()
            resources.append({**item, "pnl_path": path, "title": item["session"] + " S1 固定49対照"})
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as detail:
        for entry in manifest["entries"]:
            session = entry["session"]
            events, quality = C.events_for(entry)
            normals = [e for e in events if C.normal(e)]
            slots = make_slots(events, session, bank, signals_module)
            _, force, _ = C.bounds(session)
            for policy in POLICIES:
                all_slots[policy].extend(slots[policy])
                for slot in slots[policy]:
                    if slot["ready"] and slot["side"]:
                        labels[policy].append(C.label(normals, slot, force))
                operation = O.replay(events, [{k: s[k] for k in O.SLOT_FIELDS} for s in slots[policy]], session, policy)
                operations[policy].append(operation)
                C.jsonline(detail, {"session": session, "policy": policy, "input_quality": quality,
                    "slots": slots[policy], "operation": operation})
                path = STUDY / "viewer" / f"{policy}_{session}.trades.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as stream:
                    for trade in operation["trades"]:
                        C.jsonline(stream, trade)
                resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 局所再開",
                    "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                    "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                    "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                summaries.append({"場": session, "候補": policy, "期間": C.period(session),
                    "入力品質": quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            print(session + " 完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    table = {"S1": deepcopy(old_result["候補"]["S1"])}
    for policy in POLICIES:
        table[policy] = {}
        for period in PERIODS:
            e, o = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": e, "運用": o, "同時適格": e["70目標"] and o["活動適格"] and o["費用適格"]}
    result = {"試行": 50, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table,
        "対照参照": {"候補": "S1", "結果": (OLD / "結果.json").relative_to(ROOT).as_posix(),
                     "結果SHA256": C.sha(OLD / "結果.json"), "再計算": False},
        "役割別入口": {**{"S1": deepcopy(old_result["役割別入口"]["S1"])},
            **{p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s)
                for role in ("順行", "反転")} for s in PERIODS} for p in POLICIES}},
        "被覆診断": {p: diagnostics(all_slots[p], operations[p], labels[p], baseline) for p in POLICIES},
        "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "場別": summaries, "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"候補": table, "採用": result["採用"]}, ensure_ascii=False))


def main() -> None:
    """固定又は一度の実行を選択する。

    引数: なし。CLIから操作を取得する。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    freeze() if args.freeze else run()


if __name__ == "__main__":
    main()
