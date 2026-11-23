"""49の期限同秒行だけを補足照合する。戦略・指標・実運用は再生しない。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00049_15分定時の序盤帯反応"
WORK = ROOT / "work/定時帯反応/00049"
DESTINATION = STUDY / "期限同秒確認.json"
BINDING_FIELDS = ("slot_id", "session", "policy", "scheduled", "time", "line", "side", "role")
POLICIES = ("S0", "S1", "B+", "B-")


def helpers():
    """固定済み監査の読取・正常列抽出・旧期待値だけを取得する。

    引数: なし。
    返り値: ModuleTypeは固定監査モジュール。runと主モデルは呼ばない。
    """
    path = Path(__file__).with_name("保存物確認.py")
    spec = importlib.util.spec_from_file_location("期限同秒の固定監査補助", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def first_force_expected(tape: dict, row: dict, force: float, source) -> dict:
    """最初の期限同秒正常行を含む有限区間で障壁と空白を比較する。

    引数: tape(dict)は原正常BBO列、row(dict)は保存要求、force(float)は期限、source(ModuleType)は固定監査補助。
    返り値: dictは仮約定・障壁・期限・不足・MFE/MAE。全同秒行を含める方式とは区別する。
    """
    q = tape["normal"]
    fill = source.first_normal(tape, row["time"], row["line"])
    result = {"filled": False, "outcome": "未約定", "end_time": row["time"] + 30, "end_line": row["line"]}
    if fill is None or q["now"][fill] > row["time"] + 30:
        return result
    price = float(q["ask"][fill] if row["side"] == 1 else q["bid"][fill])
    result.update(filled=True, entry_time=float(q["now"][fill]), entry_line=int(q["line"][fill]), entry_price=price)
    first_force = int(np.searchsorted(q["now"], force, side="left"))
    stop = first_force + int(first_force < len(q["now"]) and q["now"][first_force] == force)
    if fill >= stop:
        raise ValueError("仮約定は期限より前である必要があります")
    marks = q["bid"][fill:stop] if row["side"] == 1 else q["ask"][fill:stop]
    gain = row["side"] * (marks - price)
    gaps = np.r_[False, np.diff(q["now"][fill:stop]) > 300]
    found = np.flatnonzero(gaps | (gain <= -125) | (gain >= 250))
    if len(found):
        terminal = int(found[0])
        result.update(outcome="不足" if gaps[terminal] else "125" if gain[terminal] <= -125 else "250",
                      end_time=float(q["now"][fill + terminal]), end_line=int(q["line"][fill + terminal]))
    else:
        terminal = len(gain) - 1
        last = float(q["now"][stop - 1])
        if last == force:
            result.update(outcome="期限", end_time=force, end_line=int(q["line"][stop - 1]))
        elif stop < len(q["now"]):
            result.update(outcome="期限" if force - last <= 300 else "不足", end_time=force, end_line=int(q["line"][stop]))
        else:
            result.update(outcome="不足", end_time=last, end_line=int(q["line"][stop - 1]))
    result.update(mfe=max(0.0, float(np.max(gain[:terminal + 1]))), mae=min(0.0, float(np.min(gain[:terminal + 1]))))
    return result


def full_expected(slot: dict, policy: str, tape: dict, force: float, source) -> dict:
    """保存判断の出典と期限補足期待値から先着一行の全属性を構成する。

    引数: slot(dict)は保存済み当時判断、policy(str)は四群、tape(dict)は正常列、force(float)は期限、source(ModuleType)は固定補助。
    返り値: dictは要求出典・先着・既定の取得距離診断。価格パターンや指標は再計算しない。
    """
    binding = {key: slot[key] for key in BINDING_FIELDS}
    binding["policy"] = policy
    if policy in ("B+", "B-"):
        binding.update(side=1 if policy == "B+" else -1, role="時刻基準")
    expected = {**binding, **first_force_expected(tape, binding, force, source)}
    if policy in ("S0", "S1"):
        boundary = slot["OR"]["high" if (slot["role"] == "順行") == (slot["side"] == 1) else "low"]
        distance = slot["side"] * (expected["entry_price"] - boundary) / slot["atr"] if expected["filled"] else None
        bucket = "未約定" if distance is None else "端へ逆戻り" if distance < 0 else "1ATR以下" if distance <= 1 else "1超2ATR以下" if distance <= 2 else "2ATR超"
        expected.update(取得距離ATR=distance, 距離区分=bucket, 帯端=boundary, 入口ATR=slot["atr"])
    return expected


def thin_ids(rows: list[dict], target: str, source) -> list[tuple]:
    """非重複の仮約定集合を識別子まで照合するため列挙する。

    引数: rows(list[dict])は一候補の保存順、target(str)は期間、source(ModuleType)は固定期間関数。
    返り値: list[tuple]は場・候補・枠ID。件数だけが偶然一致する場合も区別できる。
    """
    terminal, selected = {}, []
    for row in rows:
        if source.span(row["session"]) != target or not row["filled"]:
            continue
        session = row["session"]
        if (row["entry_time"], row["entry_line"]) > terminal.get(session, (-math.inf, -1)):
            selected.append((session, row["policy"], row["slot_id"]))
            terminal[session] = (row["end_time"], row["end_line"])
    return selected


# ----------------------------------------
# 架空の同秒後行では障壁結果そのものも変わり得ることを明示する。

def synthetic_tape(now: list[float], bid: list[float], ask: list[float], side: int = 1) -> dict:
    """小型の正常BBOだけを作り、必要なら上下反射する。

    引数: now/bid/ask(list[float])は架空列、side(int)は買い1又は鏡像売り−1。
    返り値: dictは期限期待値関数用の正常列。市場ファイルを読まない。
    """
    bids, asks = np.asarray(bid, dtype=float), np.asarray(ask, dtype=float)
    if side == -1:
        bids, asks = 2000 - asks, 2000 - bids
    return {"normal": {"now": np.asarray(now, dtype=float), "line": np.arange(1, len(now) + 1), "bid": bids, "ask": asks}}


def self_test(source) -> tuple[object, list[dict]]:
    """同秒障壁・鏡像・空白・TTLを明示期待値へ照合する。

    引数: source(ModuleType)は固定監査の純関数。
    返り値: tupleは比較記録と、二つの境界定義が異なる人工結果。証明ファイルは保存しない。
    """
    audit, distinctions = source.Audit(), []
    for side in (1, -1):
        request = {"time": 10.0, "line": 0, "side": side}
        for later, outcome in ((1250, "250"), (875, "125")):
            tape = synthetic_tape([11, 20, 20, 21], [990, 1000, later, 1000], [1000, 1010, later + 10, 1010], side)
            first = first_force_expected(tape, request, 20, source)
            all_same = source.saved_label_expected(tape, request, 20)
            audit.check("同秒初行で期限", (first["outcome"], first["end_line"], first["mfe"], first["mae"]), ("期限", 2, 0.0, -10.0))
            audit.check("全同秒方式は後行障壁へ到達", (all_same["outcome"], all_same["end_line"]), (outcome, 3))
            audit.check("人工では結果が変わる", first["outcome"] != all_same["outcome"], True)
            distinctions.append({"実方向": side, "後行障壁": outcome, "最初正常行を含む": first, "全同秒正常行を含む": all_same})
        for first_bid, later_bid, outcome in ((1250, 875, "250"), (875, 1250, "125")):
            tape = synthetic_tape([11, 20, 20], [990, first_bid, later_bid], [1000, first_bid + 10, later_bid + 10], side)
            first = first_force_expected(tape, request, 20, source)
            audit.check("期限初行の障壁は含む", (first["outcome"], first["end_line"]), (outcome, 2))
        tape = synthetic_tape([11, 19, 21], [990, 1000, 1250], [1000, 1010, 1260], side)
        first = first_force_expected(tape, request, 20, source)
        audit.check("期限同秒行なし後行障壁は含めない", (first["outcome"], first["end_time"], first["end_line"], first["mfe"]), ("期限", 20, 3, 0.0))
        tape = synthetic_tape([11, 400, 400], [990, 1250, 1000], [1000, 1260, 1010], side)
        first = first_force_expected(tape, request, 400, source)
        audit.check("300秒超空白を障壁より優先", (first["outcome"], first["end_line"]), ("不足", 2))
        tape = synthetic_tape([40, 50, 50], [990, 1000, 1250], [1000, 1010, 1260], side)
        audit.check("TTL30秒等号は約定", first_force_expected(tape, request, 50, source)["filled"], True)
        tape = synthetic_tape([41, 50], [990, 1000], [1000, 1010], side)
        audit.check("TTL30秒超は未約定", first_force_expected(tape, request, 50, source)["filled"], False)
    return audit, distinctions


# ----------------------------------------
# 保存済み先着だけを読む。元の失敗証明と固定ファイルは上書きしない。

def run() -> dict:
    """元129差を分類し、期限初行規約の全属性と集計を別証明へ一度保存する。

    引数: なし。既存の定時判断・先着・固定npzを読むだけで、全tick戦略を再生しない。
    返り値: dictは補足照合証明。元の保存物確認.jsonは失敗記録のまま保全する。
    """
    if DESTINATION.exists():
        raise FileExistsError("期限同秒確認.jsonを上書きしません")
    source = helpers()
    audit, distinctions = self_test(source)
    original_path = STUDY / "保存物確認.json"
    original = source.read(original_path)
    paths = {ROOT / name for name in original["参照SHA256"]}
    paths.update((original_path, Path(__file__), STUDY / "検証計画.md"))
    paths.update(path for path in (STUDY / "README.md", STUDY / "設定と結果.md") if path.exists())
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in paths}
    for name, digest in original["参照SHA256"].items():
        audit.check("元監査参照不変:" + name, before[name], digest)
    fixed = source.read(STUDY / "固定.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典不変:" + name, source.sha(ROOT / name), digest)
    audit.check("元監査は失敗記録として保持", original["全件一致"], False)
    audit.check("元監査項目数", original["照合項目数"], 176227)
    audit.check("元監査不一致数", original["不一致数"], 129)
    manifest = source.read(source.MANIFEST)
    saved = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    by_session = defaultdict(list)
    for row in saved:
        by_session[row["session"]].append(row)
    bindings = {}
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        key = (block["session"], block["policy"])
        audit.check("保存判断場候補は一意", key not in bindings, True)
        bindings[key] = {row["slot_id"]: row for row in block["slots"]}
    old_rows, new_rows, changes = [], [], []
    fields, candidate_counts, session_counts = Counter(), Counter(), Counter()
    cache_pins, attribute_count = {}, 0
    for entry in manifest["entries"]:
        session = entry["session"]
        tape, path, digest = source.load_tape(entry, audit)
        cache_pins[path] = digest
        _, force, _, _ = source.calendar(session)
        q = tape["normal"]
        left = int(np.searchsorted(q["now"], force, side="left"))
        right = int(np.searchsorted(q["now"], force, side="right"))
        expected_set = set()
        for policy in ("S0", "S1"):
            for slot_id, slot in bindings[session, policy].items():
                if slot["ready"] and slot["side"]:
                    expected_set.add((policy, slot_id))
                if policy == "S0" and slot["line"] in tape["normal_lines"]:
                    expected_set.update((baseline, slot_id) for baseline in ("B+", "B-"))
        actual = by_session[session]
        audit.check(session + ":全先着集合", {(row["policy"], row["slot_id"]) for row in actual}, expected_set)
        audit.check(session + ":全先着一意", len(actual), len(expected_set))
        for row in actual:
            policy, slot_id = row["policy"], row["slot_id"]
            slot = bindings[session, "S0" if policy in ("B+", "B-") else policy][slot_id]
            expected = full_expected(slot, policy, tape, force, source)
            name = session + ":" + policy + ":" + slot_id
            audit.check(name + ":全属性辞書", row, expected)
            audit.check(name + ":属性集合", set(row), set(expected))
            for key in set(row) | set(expected):
                audit.check(name + ":属性:" + key, row.get(key), expected.get(key))
                attribute_count += 1
            old = source.saved_label_expected(tape, row, force)
            old_rows.append({**row, **old})
            new_rows.append(expected)
            delta = {key: (row.get(key), value) for key, value in old.items() if row.get(key) != value}
            if delta:
                fields.update(delta.keys())
                candidate_counts[policy] += 1
                session_counts[session] += 1
                changes.append((session, policy, slot_id, delta))
                audit.check(name + ":差は期限行のみ", set(delta), {"end_line"})
                audit.check(name + ":両方式は期限", (row["outcome"], old["outcome"]), ("期限", "期限"))
                audit.check(name + ":元差はfirst対last", left < right and row["end_time"] == force and row["end_line"] == int(q["line"][left]) and old["end_line"] == int(q["line"][right - 1]), True)
        print(session + " 期限同秒補足", flush=True)
    audit.check("全5345label", len(saved), 5345)
    audit.check("新期待値も全件", len(new_rows), len(saved))
    audit.check("元差の全分類", dict(fields), {"end_line": 129})
    audit.check("元差のrecord数", len(changes), 129)
    audit.check("原監査に残る未説明差", original["不一致数"] - sum(fields.values()), 0)
    change_index = {(s + p + sid + ":先着" + key, str(pair[0]), str(pair[1])) for s, p, sid, delta in changes for key, pair in delta.items()}
    for item in original["不一致"]:
        audit.check("原証明表示例も分類に包含", (item["項目"], item["実際"], item["期待"]) in change_index, True)
    result = source.read(STUDY / "結果.json")
    summaries = []
    for policy in POLICIES:
        one = [row for row in saved if row["policy"] == policy]
        old = [row for row in old_rows if row["policy"] == policy]
        new = [row for row in new_rows if row["policy"] == policy]
        for period in source.SPANS:
            summary = source.entry_summary(one, period)
            audit.check(policy + period + ":全同秒との集計不変", summary, source.entry_summary(old, period))
            audit.check(policy + period + ":最初同秒との集計不変", summary, source.entry_summary(new, period))
            expected_result = result["候補"][policy][period]["入口"] if policy in ("S0", "S1") else result["時刻基準"][policy][period]
            audit.check(policy + period + ":保存結果の全入口集計", summary, expected_result)
            selected = thin_ids(one, period, source)
            audit.check(policy + period + ":全同秒との間引きID不変", selected, thin_ids(old, period, source))
            audit.check(policy + period + ":最初同秒との間引きID不変", selected, thin_ids(new, period, source))
            summaries.append({"候補": policy, "期間": period, **summary, "間引きID列不変": True})
    for name, digest in before.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {
        "試行": 49, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "市場戦略再生": False, "主モデルimport": False, "指標再計算": False, "実運用再計算": False,
        "正本規約": "固定前の主labelは原順の最初のforce同秒正常BBOで空白と障壁を判定し、その行を含め期限終了する。後行の同秒正常BBOへ進まない。",
        "計画の限定": "計画の『同時刻の正常BBOを含む』は、同秒に複数の物理行があるときの最初行と最終行を明記していなかった。今回の補足は事前に固定された逐行主実装を正本とし、結果後にモデルや保存labelを変更しない。",
        "元監査の原因": "固定監査のsearchsorted(force, right)が全同秒行を含め、期限の最終行を期待値とした。単一force行の人工ではこの相違を検出できていなかった。",
        "元監査の保存": {"パス": original_path.relative_to(ROOT).as_posix(), "SHA256": before[original_path.relative_to(ROOT).as_posix()],
                     "全件一致": original["全件一致"], "照合項目数": original["照合項目数"], "不一致数": original["不一致数"]},
        "元不一致の分類": {"期限end_lineのfirst対last": sum(fields.values()), "対象record数": len(changes), "対象場数": len(session_counts),
                       "候補別": dict(candidate_counts), "場別": dict(session_counts), "その他の元不一致": original["不一致数"] - sum(fields.values())},
        "対象label数": len(saved), "全属性比較数": attribute_count, "対象場数": len(cache_pins),
        "実データ影響": "全5345件の先着区分・仮約定・期限秒・MFE/MAEは不変。4群×3期間の率・支持・間引き件数と識別子も不変。実運用額は再計算せず、保存結果・固定モデル・元監査証明のSHA不変を確認した。",
        "全12入口集計": summaries, "人工で結果が変わる例": distinctions,
        "人工の限定": "force同秒後行が別障壁に届く架空入力では先着区分自体が異なる。実データで経済結果が同じだったことを一般的な同値性としない。",
        "参照SHA256": before, "キャッシュSHA256": cache_pins,
    }
    DESTINATION.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    """人工だけ又は一度の保存物補足を明示指定で起動する。

    引数: なし。CLI引数--self-test又は--runを読む。
    返り値: None。不一致では非零終了し、正式補足の既存上書きは禁止する。
    """
    parser = argparse.ArgumentParser(description="49期限同秒行の独立補足。戦略再生なし")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        audit, distinctions = self_test(helpers())
        print(json.dumps({"人工比較数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "異なる結果の例数": len(distinctions)}, ensure_ascii=False))
        raise SystemExit(int(audit.bad != 0))
    payload = run()
    print(json.dumps({key: payload[key] for key in ("全件一致", "照合項目数", "不一致数", "対象label数", "元不一致の分類")}, ensure_ascii=False))
    raise SystemExit(int(payload["不一致数"] != 0))


if __name__ == "__main__":
    main()
