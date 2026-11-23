"""55の単独回収・過去葉集計・二候補の保存運用を独立に検査する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
WORK = ROOT / "work/独立追尾回収/00055"
OLD = ROOT / "study/00054_方向と局所帯を先に分岐"
OLDWORK = ROOT / "work/方向局面分岐/00054"
BASEWORK = ROOT / "work/局所再開/00050"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
LABELS = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
POLICIES = ("C0", "R0")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")


def load(path: Path, name: str):
    """固定純補助を独自名で読み、元の大域値を変更しない。

    引数: path(Path)はコード、name(str)は固有読込名。
    返り値: ModuleTypeはモジュール。新主処理や学習処理は正式監査で呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(ROOT / "scripts/局所帯分岐/保存物確認.py", "独立追尾監査_固定53")
P = load(ROOT / "scripts/方向局面分岐/保存物確認.py", "独立追尾監査_固定54")
fingerprint = A.fingerprint


# ----------------------------------------
# 過去教師の四則計算とJSON予測だけで、回収追加の正本を別算する。

def expected_calibration(model: dict, measurements: dict, evaluation_start: float) -> dict:
    """旧D0の使用教師へ確定回収pairを結び、全葉を独立集計する。

    引数: model(dict)は固定D0木、measurements(dict)は枠/side→測定、evaluation_start(float)は後続開始。
    返り値: dictは全葉の支持・十進純額・平均・採否符号・教師指紋。新fitをしない。
    """
    identities = model["training"]["row_ids"]
    pairs = {}
    for identity in identities:
        key = identity["slot_id"], identity["side"]
        row = measurements[key]
        if row["session"] != identity["session"] or row["ready"] is not True:
            raise ValueError("旧教師の準備又は場が不一致")
        barrier = row["barrier"]
        if barrier is None or barrier["outcome"] not in ("250", "125", "期限"):
            raise ValueError("旧使用教師の障壁結果が未知")
        if not A.finite(barrier["end_time"]) or not A.finite(row["recovery_end_time"]) or max(barrier["end_time"], row["recovery_end_time"]) >= evaluation_start:
            raise ValueError("障壁又は回収が評価開始よりstrict前ではない")
        pair = pairs.setdefault(identity["slot_id"], {})
        if identity["side"] in pair:
            raise ValueError("過去教師の重複")
        pair[identity["side"]] = row
    if any(set(pair) != {-1, 1} for pair in pairs.values()):
        raise ValueError("過去教師の片側抜け")
    excluded = [{"slot_id": key, "states": {str(s): pair[s]["status"] for s in (1, -1)}}
                for key, pair in pairs.items() if any(pair[s]["status"] != "確定完結" for s in (1, -1))]
    blocked = {row["slot_id"] for row in excluded}
    leaf_rows = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    used = []
    for identity in identities:
        if identity["slot_id"] in blocked:
            continue
        row = measurements[identity["slot_id"], identity["side"]]
        if len(row["operation"]["closed"]) != 1:
            raise ValueError("確定回収は単独一完結が必要")
        leaf, _, _ = A.walk(model, row["features"])
        closed = row["operation"]["closed"][0]
        value = {**identity, "leaf": leaf, "recovery_end_time": row["recovery_end_time"], "barrier_end_time": row["barrier"]["end_time"],
                 **{f"pnl{fee}": closed[f"pnl{fee}"] for fee in (0, 5, 10)}}
        leaf_rows[leaf].append(value)
        used.append(value)
    leaves = {}
    for leaf, selected in leaf_rows.items():
        sums = {str(f): sum((Decimal(str(r[f"pnl{f}"])) for r in selected), Decimal(0)) for f in (0, 5, 10)}
        unique, days, sessions = len({r["slot_id"] for r in selected}), len({r["session"][:10] for r in selected}), len({r["session"] for r in selected})
        leaves[str(leaf)] = {"leaf": leaf, "direction_rows": len(selected), "unique_slots": unique, "days": days, "sessions": sessions,
            "sum_yen": {f: str(v) for f, v in sums.items()}, "mean_yen": {f: float(v / len(selected)) if selected else None for f, v in sums.items()},
            "support": unique >= 60 and days >= 6 and sessions >= 10, "positive": bool(selected) and sums["5"] > 0, "rows": selected,
            "max_teacher_end": max((max(r["barrier_end_time"], r["recovery_end_time"]) for r in selected), default=None)}
    return {"model_id": model["model_id"], "evaluation_start": evaluation_start, "old_teacher_direction_rows": len(identities),
        "old_teacher_ids_sha256": fingerprint(identities), "input_pairs": len(pairs), "used_pairs": len(pairs) - len(excluded),
        "excluded_pairs": excluded, "used_direction_rows": len(used), "weight_per_direction": .5, "used_rows_sha256": fingerprint(used),
        "leaves": leaves, "classifier_fit_count": 0,
        "meaning": "旧木の全過去教師と回収確定pairの共通部分による葉内記述。未来確率の校正ではない"}


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """旧最高raw側を維持し、回収支持と正額の除外だけを加える。

    引数: model/calibration(dict)は過去木と回収集計、vectors(dict)は当時18列、policy(str)はC0/R0。
    返り値: dictは旧全予測と新採否。評価回収や未来の品質を引数に取らない。
    """
    if policy not in POLICIES or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又はモデルの対応不正")
    prior = A.predict(model, vectors)
    side, reason, recovery = prior["side"], prior["reason"], None
    if side:
        recovery = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not recovery["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy == "R0" and not recovery["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": recovery["leaf"] if recovery else None,
        "recovery_support": recovery["support"] if recovery else None, "recovery_mean5": recovery["mean_yen"]["5"] if recovery else None}


def decision_event(slot: dict, tape: dict) -> dict | None:
    """当時判断原行の最小6列を原キャッシュから射影する。

    引数: slot(dict)は保存時計、tape(dict)は49監査の原配列。
    返り値: dict|Noneはnow/line/last/bid/ask/valid。placeholderならNone。
    """
    if slot["line"] is None:
        return None
    events = tape["events"]
    i = int(events["line"].searchsorted(slot["line"], side="left"))
    if i >= len(events["line"]) or int(events["line"][i]) != slot["line"]:
        raise ValueError("判断原行が一意でない")
    return {"now": float(events["now"][i]), "line": int(events["line"][i]), "last": float(events["last"][i]),
            "bid": float(events["bid"][i]), "ask": float(events["ask"][i]), "valid": bool(events["valid"][i])}


def measurement_status(operation: dict | None, end: float) -> tuple:
    """単独の完結・品質・未約定を0円へ補完せず分類する。

    引数: operation(dict|None)は保存O49結果、end(float)は場末。
    返り値: tuple[str,float]は状態と教師の確定境界。未確定は場末を用いる。
    """
    if operation is None:
        return "技法未準備", end
    if len(operation["closed"]) > 1:
        raise ValueError("独立測定に複数完結")
    if operation["closed"]:
        if operation["quality"]["損益確定可能"]:
            return "確定完結", operation["closed"][0]["exit_time"]
        return "品質注意完結", end
    if operation["final_state"]["position"] is not None or operation["final_state"]["pending"] is not None:
        return "未解消", end
    return "未約定", end


def check_single_decision(operation: dict, expected: dict, tape: dict, source, audit) -> None:
    """単独一枠の新規判断と、当時最初原行の整合を確認する。

    引数: operation(dict)は測定、expected(dict)は純slot、tape(dict)は原配列、source(ModuleType)/audit(Audit)は補助。
    返り値: None。分母1の活動を本物の全予定活動へ流用しない。
    """
    audit.check("単独判断一枠", len(operation["decisions"]), 1)
    d = operation["decisions"][0]
    for k, v in expected.items():
        audit.check("単独純判断:" + k, d[k], v)
    audit.check("単独判断は正常BBO", expected["line"] in tape["normal_lines"], True)
    audit.check("単独判断前は空き", (d["holding"], d["pending_kind"], d["position_id"]), (False, None, None))
    audit.check("単独新規判断", d["action"], "買い新規要求" if expected["side"] == 1 else "売り新規要求")
    audit.check("単独新規一要求", len([o for o in operation["orders"] if o["kind"] == "entry"]), 1)


def check_measurement_quality(operation: dict, tape: dict, audit) -> None:
    """建玉の実保有区間に重なる正常気配300秒超を直接検査する。

    引数: operation(dict)は単独記録、tape(dict)は正常原配列、audit(Audit)は記録。
    返り値: None。価格戦略を再生せず、気配間隔と保存残状態だけを照合する。
    """
    positions = list(operation["closed"])
    if operation["final_state"]["position"] is not None:
        positions.append(operation["final_state"]["position"])
    q, gaps = tape["normal"], 0
    for p in positions:
        finish = p.get("exit_line", float("inf"))
        begin = max(1, int(q["line"].searchsorted(p["entry_line"], side="right")))
        stop = int(q["line"].searchsorted(finish, side="right"))
        gaps += int(((q["now"][begin:stop] - q["now"][begin - 1:stop - 1]) > 300).sum())
    audit.check("単独保有中気配間隔数", operation["quality"]["保有中長気配間隔数"], gaps)
    unresolved = operation["final_state"]["position"] is not None or operation["final_state"]["pending"] is not None
    reasons = []
    if gaps:
        reasons.append("建玉又は返済pending中に正常気配間隔300秒超")
    if unresolved:
        reasons.append("場末の建玉又は返済pending未解消")
    audit.check("単独確定可否", operation["quality"]["損益確定可能"], not bool(reasons))
    audit.check("単独損益注意理由", operation["quality"]["損益注意理由"], reasons)


def load_tape(entry: dict, source, audit) -> tuple:
    """固定8列から49独立抽出を再用し、表示照合用Lastだけを保持する。

    引数: entry(dict)は予約台帳、source(ModuleType)は49監査、audit(Audit)は検査記録。
    返り値: tupleはtape/cache相対path/SHA/入力品質。元キャッシュを変更しない。
    """
    path = ROOT / "work/複合検証" / entry["cache_path"]
    digest = source.sha(path)
    audit.check("cacheSHA", digest, entry["sha256_cache"])
    with source.np.load(path, allow_pickle=False) as archive:
        audit.check("元8列", set(archive.files), {"now", "line", "last", "bid", "ask", "valid", "volume", "volume_time"})
        data = {k: archive[k] for k in archive.files}
    tape = source.tape_from_arrays(data, entry["session"], audit)
    indices = source.np.searchsorted(data["line"], tape["events"]["line"])
    tape["events"]["last"] = data["last"][indices]
    begin, _, end, _ = source.calendar(entry["session"])
    now = source.np.asarray(data["now"], dtype=float)
    finite = source.np.isfinite(now)
    maximum = source.np.maximum.accumulate(source.np.where(finite, now, -source.np.inf))
    backwards = finite & (now < maximum)
    outside = finite & ~backwards & ((now < begin) | (now >= end))
    quality = {k: n for k, n in (("時計欠測", int((~finite).sum())), ("時計後退", int(backwards.sum())), ("場外", int(outside.sum()))) if n}
    return tape, path.resolve().relative_to(ROOT.resolve()).as_posix(), digest, quality


def strict_close_equal(first: dict, second: dict) -> bool:
    """候補の建玉ID以外の全完結項目を型と値まで比較する。

    引数: first/second(dict)は単独測定と元実完結。
    返り値: boolはIDを除く項目集合・型・値が全て一致するか。
    """
    keys = set(first) - {"id"}
    return keys == set(second) - {"id"} and all(type(first[k]) is type(second[k]) and first[k] == second[k] for k in keys)


def check_measurement(row: dict, old: dict, feature: dict, barrier: dict | None, tape: dict, group: str, source, audit) -> dict:
    """一方向の保存測定を出典・注文・独立現金・追尾・確定境界へ照合する。

    引数: row(dict)は測定、old/feature(dict)は当時枠・独立特徴、barrier(dict|None)は固定先着、
        tape(dict)は原配列、group(str)は期間用途、source(ModuleType)/audit(Audit)は補助。
    返り値: dictは後段の葉集計に必要な小型測定。元行を書き換えない。
    """
    side = row["side"]
    if type(side) is not int or side not in (-1, 1):
        raise ValueError("独立測定の方向不正")
    operation = row["operation"]
    _, _, end, _ = source.calendar(old["session"])
    status, recovery_end = measurement_status(operation, end)
    background = feature["background_direction"]
    role = "未準備" if not feature["ready"] else "上位同値" if background == 0 else "順行" if side == background else "反転"
    quote = decision_event(old, tape) if feature["ready"] else None
    if quote is not None:
        quote = {k: None if k in ("now", "last", "bid", "ask") and not A.finite(v) else v for k, v in quote.items()}
    expected = {**{k: old[k] for k in BINDING}, "side": side, "ready": feature["ready"], "feature_reason": feature["reason"],
        "features": feature["vectors"][str(side)], "background_direction": background, "atr": feature["atr"], "D": feature["D"],
        "role": role, "measurement_group": group, "barrier": barrier, "operation": operation, "status": status,
        "recovery_end_time": recovery_end, "decision_bbo": quote}
    audit.check("測定全項目契約", row, expected)
    if not feature["ready"]:
        audit.check("未準備を未実行", operation, None)
    else:
        if operation is None:
            raise ValueError("準備済みの測定なし")
        pure = {k: old[k] for k in ("scheduled", "time", "line", "slot_id")}
        pure.update(side=side, role="順行" if background in (0, side) else "反転", atr=feature["atr"], D=feature["D"], ready=True, reason="全定時独立計測")
        audit.check("測定の場", operation["session"], old["session"])
        audit.check("単独候補ID", operation["candidate_id"], "I55_" + str(int(old["scheduled"])) + ("買" if side == 1 else "売"))
        check_single_decision(operation, pure, tape, source, audit)
        source.check_orders(operation, tape, audit)
        source.check_cash(operation, operation["trades"], tape, audit)
        source.check_trail(operation, tape, audit)
        check_measurement_quality(operation, tape, audit)
        audit.check("単独完結数は0又は1", len(operation["closed"]) in (0, 1), True)
        opened = [o for o in operation["orders"] if o["kind"] == "entry" and o["status"] == "filled"]
        audit.check("先着と単独の新規可否", bool(opened), barrier["filled"])
        if opened:
            for key in ("time", "line", "price"):
                actual, expected_value = opened[0]["fill_" + key], barrier["entry_" + key]
                audit.check("先着新規の型と値:" + key, (type(actual).__name__, actual), (type(expected_value).__name__, expected_value))
        metadata = operation["measurement"]
        event = tape["events"]
        start = int(event["line"].searchsorted(old["line"]))
        q = tape["normal"]
        n = int(q["line"].searchsorted(old["line"], side="left"))
        prefix = {"last_time": float(event["now"][start - 1]) if start else None,
                  "last_line": int(event["line"][start - 1]) if start else None, "raw_line": int(event["line"][start - 1]) if start else 0,
                  "last_quote_time": float(q["now"][n - 1]) if n else None, "非正常BBO行数": start - n,
                  "空き時間長気配間隔数": int(((q["now"][1:n] - q["now"][:max(0, n - 1)]) > 300).sum())}
        audit.check("strict過去prefix", metadata["prefix"], prefix)
        audit.check("prefixイベント数", metadata["prefixイベント数"], start)
        audit.check("入力イベント数", metadata["入力イベント数"], len(event["line"]))
        audit.check("切出開始key", metadata["切出開始key"], [float(event["now"][start]), int(event["line"][start])])
        audit.check("単独測定の分母と用途", (metadata["独立一枠測定"], metadata["予定枠分母"], metadata["全予定枠活動の評価には使わない"]), (True, 1, True))
        audit.check("単独測定の当時背景", metadata["background_direction"], background)
        audit.check("固定O49版", metadata["固定運用SHA256"], source.sha(ROOT / "scripts/定時帯反応/運用.py"))
        if operation["closed"]:
            p = operation["closed"][0]
            audit.check("完結後の入力を打切り", metadata["走査最終key"], [p["exit_time"], p["exit_line"]])
        last = metadata["走査最終key"]
        if last is not None:
            stop = int(event["line"].searchsorted(last[1], side="left"))
            audit.check("最終走査key実在", [float(event["now"][stop]), int(event["line"][stop])], last)
            audit.check("供給は連続原行区間", metadata["供給イベント数"], stop - start + 1)
    return {**{k: row[k] for k in ("session", "slot_id", "side", "ready", "features", "barrier", "status", "recovery_end_time")},
            "operation": {"closed": operation["closed"]} if operation is not None else None}


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary, audit) -> None:
    """全予定分母・先着70目標・実費用を三候補で独立集計する。

    引数: accounts/labelsは検算済み会計と先着、result(dict)は結果、source/summary(ModuleType)/audit(Audit)は補助。
    返り値: None。単独測定の分母1や損益合計を混合運用の成績に使わない。
    """
    for policy in ("D0", *POLICIES):
        selected = [r for r in accounts if r["candidate"] == policy]
        for period in PERIODS:
            entry = source.entry_summary(labels[policy], period)
            operation = summary.operation_summary(selected, period, source)
            audit.check(policy + period + ":入口", result["候補"][policy][period]["入口"], entry)
            audit.check(policy + period + ":運用", result["候補"][policy][period]["運用"], operation)
            audit.check(policy + period + ":同時適格", result["候補"][policy][period]["同時適格"], entry["70目標"] and operation["活動適格"] and operation["費用適格"])
            for role in ("順行", "反転"):
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], source.entry_summary([r for r in labels[policy] if r["role"] == role], period))
            if policy in POLICIES:
                reasons = Counter(d["reason"] for a in selected if source.span(a["session"]) == period for d in a["decisions"])
                audit.check(policy + period + ":全判断理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新候補だけの採用", result["採用"], [p for p in POLICIES if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])])


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """全138資源と新二候補一代表ずつのAPI台帳・約定を検査する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は資源/会計、source(ModuleType)/audit(Audit)は補助。
    返り値: dictは実行範囲。未指定ならAPI未検証を明記する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新92保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API138全集合", {r["id"] for r in listing["resources"]}, {r["id"] for r in resources})
    audit.check("API資源数", len(listing["resources"]), 138)
    representatives = []
    for policy in POLICIES:
        account = sorted([a for a in accounts if a["candidate"] == policy], key=lambda a: (-abs(a["ledger"]["5"]), a["session"]))[0]
        resource = next(r for r in resources if r["method_id"] == policy and r["session"] == account["session"])
        parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API集計alias", data["summary"], meta["summary"])
        audit.check("API台帳純額5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        trades = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API約定片数", len(data["events"]), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data["events"]), 1):
            for k in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + k, event[k], trade[k])
            audit.check("API順", event["sequence"], sequence)
            audit.check("API時刻", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "全資源数": 138, "新政策代表": representatives, "代表規約": "候補別最大絶対台帳観測額。採否へ不使用"}


# ----------------------------------------
# 全測定は一場ずつ監査し、葉内集計には完結と出典だけを保持する。

def run(viewer_url: str | None = None) -> dict:
    """root本物実行後の独立測定・葉内回収・新92運用を一度だけ監査する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは差数・出典・保証範囲。旧モデルfitや市場戦略再生を行わない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper, summary = A.helpers()
    audit = source.Audit()
    files = [STUDY / n for n in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / n for n in ("独立測定.jsonl.gz", "定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [OLD / "結果.json", OLD / "保存物確認.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz",
              OLDWORK / "入口先着.jsonl.gz", BASEWORK / "定時判断と運用.jsonl.gz", LABELS, FRAMES, source.MANIFEST,
              Path(__file__), Path(__file__).with_name("回収集計.py"), Path(__file__).with_name("計測.py")]
    before = {p.relative_to(ROOT).as_posix(): source.sha(p) for p in files}
    fixed, result, old_result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json"), source.read(OLD / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
    audit.check("監査自己の固定包含", Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"], True)
    audit.check("試行・固定bind", (result["試行"], result["固定SHA256"]), (55, source.sha(STUDY / "固定.json")))
    audit.check("候補集合", set(result["候補"]), {"D0", *POLICIES})
    audit.check("新fit0と新92運用", (result["新分類器fit"], result["新運用数"]), (0, 92))
    old_proof = source.read(OLD / "保存物確認.json")
    audit.check("旧54成功証明", (old_proof["全件一致"], old_proof["不一致数"]), (True, 0))
    old_result_rel = (OLD / "結果.json").relative_to(ROOT).as_posix()
    audit.check("旧54結果の監査bind", source.sha(OLD / "結果.json"), old_proof["参照SHA256"][old_result_rel])
    for filename in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"):
        rel = (OLDWORK / filename).relative_to(ROOT).as_posix()
        audit.check("旧証明の詳細bind:" + filename, source.sha(ROOT / rel), old_proof["参照SHA256"][rel])
    entries = source.read(source.MANIFEST)["entries"]
    phases = A.phases(entries, source)
    evaluated = [e["session"] for e in entries[20:]]
    audit.check("評価46場順", result["評価場"], evaluated)
    audit.check("初期20場は学習専用", result["学習専用場"], [e["session"] for e in entries[:20]])
    audit.check("旧D0三モデルmetadata", result["対照モデル"], old_result["モデル"])
    audit.check("準備全dict同値", result["準備比較"], old_result["準備比較"])
    audit.check("旧D0参照", result["対照参照"], {"候補": ["D0"], "元試行": 54, "同じ評価46場": True, "市場再生": False})
    frames, blocks, old_blocks = defaultdict(list), {}, {}
    for row in source.json_rows(FRAMES):
        if row["minutes"] == 3:
            frames[row["場"]].append({"session": row["場"], **{k: row[k] for k in A.SOURCE if k != "session"}})
    for block in source.json_rows(BASEWORK / "定時判断と運用.jsonl.gz"):
        if block["policy"] == "P0":
            audit.check("50P0場一意", block["session"] not in blocks, True)
            blocks[block["session"]] = block
    features, old_slots = {}, {}
    for block in blocks.values():
        audit.check("50全予定", [s["scheduled"] for s in block["slots"]], source.calendar(block["session"])[3])
        for slot in block["slots"]:
            if slot["slot_id"] in old_slots:
                raise ValueError("元slot ID重複")
            old_slots[slot["slot_id"]] = slot
            features[slot["slot_id"]] = A.expected_feature(slot, frames[block["session"]])
    audit.check("全2442slot", len(features), 2442)
    for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"):
        audit.check("旧D0一意", block["session"] not in old_blocks and block["policy"] == "D0", True)
        old_blocks[block["session"]] = block
        for slot in block["slots"]:
            audit.check("旧54全特徴と一致", features[slot["slot_id"]], slot["feature"])
    audit.check("旧評価46集合", set(old_blocks), set(evaluated))
    baseline = {}
    for row in source.json_rows(LABELS):
        if row["policy"] in ("B+", "B-"):
            key = row["slot_id"], row["side"]
            audit.check("B±一意", key not in baseline, True)
            baseline[key] = row
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細は評価46場", set(detail), set(evaluated))
    labels, actual_labels = {"D0": list(source.json_rows(OLDWORK / "入口先着.jsonl.gz")), **{p: [] for p in POLICIES}}, defaultdict(list)
    actual_sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    for row in actual_sequence:
        actual_labels[row["session"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(r["session"], r["method_id"]): r for r in resources}
    audit.check("138資源全集合", set(resource_map), {(s, p) for s in evaluated for p in ("D0", *POLICIES)})
    audit.check("138資源一意", (len(resources), len({r["id"] for r in resources})), (138, 138))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] == "D0":
            audit.check("旧D0資源全属性", resource_map[row["session"], "D0"], row)
            audit.check("旧Viewer固定包含", row["pnl_path"] in fixed["ファイルSHA256"], True)
    model_pins, models, calibrations, teacher_matches = {}, {}, {}, {}
    manifests = {m["phase"]: m for m in result["モデル"]}
    audit.check("回収三集計の順序", [m["phase"] for m in result["モデル"]], [p["id"] for p in phases])
    audit.check("回収三集計一意", len(manifests), 3)
    for phase in phases:
        path = OLD / "models" / ("D0_" + phase["id"] + ".json")
        models[phase["id"]] = source.read(path)
        relative, digest = path.relative_to(ROOT).as_posix(), source.sha(path)
        model_pins[relative] = digest
        old_manifest = next(m for m in old_result["モデル"] if m["phase"] == phase["id"])
        audit.check("旧D0モデルの元manifest", (relative, digest), (old_manifest["path"], old_manifest["SHA256"]))
        audit.check("旧D0モデルの元監査bind", digest, old_proof["モデルSHA256"][relative])
    independent_stream = iter(source.json_rows(WORK / "独立測定.jsonl.gz"))
    slim, counts, accounts, summaries, cache_pins, viewer_pins = {}, Counter(), [], [], {}, {}
    measured, opened_count, old_closed_count, full_samples, mixed_slots = 0, 0, 0, 0, 0
    for session_index, entry in enumerate(entries):
        session = entry["session"]
        tape, cache_path, digest, input_quality = load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        group = "初期20学習専用" if session_index < 20 else "時系列20" if session_index < 40 else source.span(session)
        first_ready = False
        for old in blocks[session]["slots"]:
            feature = features[old["slot_id"]]
            for side in (1, -1):
                row = next(independent_stream)
                audit.check("4884行の完全順", (row["slot_id"], row["side"]), (old["slot_id"], side))
                record = check_measurement(row, old, feature, baseline.get((old["slot_id"], side)), tape, group, source, audit)
                key = old["slot_id"], side
                audit.check("独立測定一意", key not in slim, True)
                slim[key] = record
                counts[group, row["status"]] += 1
                measured += 1
                if row["operation"] is not None:
                    opened_count += int(any(o["kind"] == "entry" and o["status"] == "filled" for o in row["operation"]["orders"]))
                if feature["ready"] and not first_ready:
                    full_samples += 1
            if feature["ready"]:
                first_ready = True
        if session_index < 20:
            print(session + " 単独回収確認", flush=True)
            continue
        phase = next(p for p in phases if session in {e["session"] for e in p["evaluation"]})
        phase_id, model = phase["id"], models[phase["id"]]
        if phase_id not in calibrations:
            path = STUDY / "models" / ("回収_" + phase_id + ".json")
            calibration = source.read(path)
            digest = source.sha(path)
            model_pins[path.relative_to(ROOT).as_posix()] = digest
            base_path = OLD / "models" / ("D0_" + phase_id + ".json")
            feature_rows = {key: {"ready": value["ready"], "reason": value["reason"], "vectors": value["vectors"]} for key, value in features.items()}
            _, original_training, _ = A.training_rows(phase["train"], blocks, feature_rows, baseline, phase["evaluation_start"], 18)
            teacher_keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")
            teacher_matches[phase_id] = {k: original_training[k] == model["training"][k] for k in teacher_keys}
            audit.check("旧D0教師4指紋:" + phase_id, teacher_matches[phase_id], dict.fromkeys(teacher_keys, True))
            expected = expected_calibration(model, slim, phase["evaluation_start"])
            expected.update(phase=phase_id, base_model_path=base_path.relative_to(ROOT).as_posix(), base_model_sha256=source.sha(base_path))
            audit.check("回収全leaf・過去教師・支持・符号:" + phase_id, calibration, expected)
            audit.check("回収meta:" + phase_id, manifests[phase_id], {"id": model["model_id"], "phase": phase_id,
                "path": path.relative_to(ROOT).as_posix(), "SHA256": digest, "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]]})
            calibrations[phase_id] = expected
        calibration = calibrations[phase_id]
        old_block = old_blocks[session]
        for closed in old_block["operation"]["closed"]:
            counterpart = slim[closed["slot_id"], closed["side"]]["operation"]["closed"]
            audit.check("旧D0一完結対応", len(counterpart), 1)
            if counterpart:
                audit.check("旧D0全完結型値一致", strict_close_equal(counterpart[0], closed), True)
            old_closed_count += 1
        accounts.append(P.account(old_block["operation"], source, audit))
        saved_old_slots = {s["slot_id"]: s for s in old_block["slots"]}
        audit.check("新二候補順", [b["policy"] for b in detail[session]], list(POLICIES))
        choices = {}
        for block in detail[session]:
            policy, operation = block["policy"], block["operation"]
            audit.check("新運用ID/場/phase", (operation["candidate_id"], operation["session"], block["phase"]), (policy, session, phase_id))
            audit.check("入力品質", block["input_quality"], input_quality)
            source.check_decisions(block, tape, audit)
            source.check_orders(operation, tape, audit)
            source.check_trail(operation, tape, audit)
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規保存先", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            accounts.append(source.check_cash(operation, list(source.json_rows(path)), tape, audit))
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality,
                "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            choices[policy] = {}
            for slot in block["slots"]:
                mixed_slots += 1
                old = old_slots[slot["slot_id"]]
                feature = features[slot["slot_id"]]
                predicted = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
                side, reason = (predicted["side"], predicted["reason"]) if predicted else (0, feature["reason"])
                if side and feature["background_direction"] == 0:
                    side, reason = 0, "上位DI同値の役割未確定WAIT"
                role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
                expected_slot = {**{k: old[k] for k in BINDING}, "policy": policy, "phase": phase_id, "model_id": model["model_id"],
                    "side": side, "role": role, "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": predicted}
                audit.check("新slot全属性/採否", slot, expected_slot)
                audit.check("旧D0 raw予測不変", predicted["prior"] if predicted else None, saved_old_slots[slot["slot_id"]]["prediction"])
                if side:
                    audit.check("旧D0採用側だけを保持", side, saved_old_slots[slot["slot_id"]]["side"])
                    labels[policy].append({**baseline[slot["slot_id"], side], "policy": policy, "role": role})
                choices[policy][slot["slot_id"]] = side
        audit.check("純R0はC0同側subset", all(not side or choices["C0"][key] == side for key, side in choices["R0"].items()), True)
        for row in actual_labels[session]:
            _, force, _, _ = source.calendar(session)
            expected_label = {**{k: row[k] for k in (*BINDING, "policy", "side", "role")}, **label_helper.first_force_expected(tape, row, force, source)}
            audit.check("新先着の原BBO全属性", row, expected_label)
        print(session + " 単独回収・過去leaf・新二運用確認", flush=True)
    if next(independent_stream, None) is not None:
        raise ValueError("独立測定に余分な行")
    audit.check("全4884方向行", measured, 4884)
    audit.check("旧教師一致表示", result["旧教師一致"], teacher_matches)
    audit.check("新3404予定枠", mixed_slots, 3404)
    audit.check("独立測定状態集計", result["独立測定"], [{"区間": k[0], "状態": k[1], "方向行数": n} for k, n in sorted(counts.items())])
    audit.check("主内検査の全日標本数", result["検査"]["全日単独比較"], full_samples)
    audit.check("主内検査の旧D0一致数", result["検査"]["旧D0実完結一致"], old_closed_count)
    audit.check("主内検査の先着一致数", result["検査"]["先着新規一致"], opened_count)
    audit.check("新先着全属性コピー/全順", actual_sequence, [r for p in POLICIES for r in labels[p]])
    audit.check("全場別表示", result["場別"], summaries)
    check_periods(accounts, labels, result, source, summary, audit)
    audit.check("D0保存対照全属性", result["候補"]["D0"], old_result["候補"]["D0"])
    audit.check("D0役割対照全属性", result["役割別入口"]["D0"], old_result["役割別入口"]["D0"])
    audit.check("詳細三系列", set(result["詳細"]), {"独立測定.jsonl.gz", "定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins}.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 55, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0, "照合項目数": audit.count,
        "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "市場戦略再生": False, "新主処理import": False, "新計測集計を期待値に使用": False,
        "測定方向行数": measured, "新運用数": 92, "新予定比較数": mixed_slots, "旧D0実完結比較数": old_closed_count,
        "回収集計数": len(calibrations), "参照SHA256": before, "モデルSHA256": model_pins,
        "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "独立18特徴・4884測定の出典/状態/注文/先着新規/現金/保存追尾/保有区間gap、旧D0全完結型値、旧row_idsへの回収確定pair結合・全leaf支持/十進合計/平均/符号/strict過去、二候補採否・純subset・混合全予定/先着/会計/活動。",
        "限定": "全日単独との本物標本比較は固定主処理が行った検査数を参照し、本監査は再生しない。変化しない全tickの独自保護再生、未見利益、葉内平均の未来確率校正を証明しない。独立一枠の活動分母/損益合計を混合運用成績へ使わない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
# 人工APIは主処理を読み込まず、純集計と小型O49入力だけを検査する。

def old_walk(model: dict, values: list) -> tuple:
    """固定53の独立JSON走査を二項目APIへ写す。

    引数: model(dict)は人工又は検算済み固定木、values(list)は18特徴。
    返り値: tupleは葉ID/path。大域値やモデルは変更しない。
    """
    leaf, path, _ = A.walk(model, values)
    return leaf, path


def artificial_tree(rows: list[dict]) -> dict:
    """固定Z・DI二段と四つの既知葉を持つ人工木を作る。

    引数: rows(list[dict])は人工の方向教師。
    返り値: dictはfitを行わないD0風JSON。実モデルの代用品として保存しない。
    """
    meta, nodes, paths = A.feature_metadata(), [], {0: []}
    for i in range(7):
        internal = i < 3
        feature = 17 if i == 0 else 0 if internal else -2
        left, right = ((1, 2) if i == 0 else (3, 4) if i == 1 else (5, 6)) if internal else (-1, -1)
        node = {"id": i, "feature": feature, "feature_id": meta[feature]["id"] if internal else None,
            "family": meta[feature]["family"] if internal else None, "threshold": .5 if i == 0 else 0. if internal else -2.,
            "left": left, "right": right, "path": paths[i], "score": .4 if i in (3, 4) else .8,
            "unique_slots": 100, "days": 10, "sessions": 20, "direction_rows": 100, "data_absent": False}
        nodes.append(node)
        if internal:
            for branch, child in (("left", left), ("right", right)):
                paths[child] = paths[i] + [{"node": i, "feature": feature, "feature_id": meta[feature]["id"],
                    "method": meta[feature]["method"], "family": meta[feature]["family"], "threshold": node["threshold"],
                    "comparison": "<=" if branch == "left" else ">", "branch": branch}]
    return {"policy": "D0", "model_id": "D0_人工", "feature_meta": meta, "nodes": nodes,
            "training": {"row_ids": [{k: row[k] for k in ("session", "slot_id", "side")} for row in rows]}}


def artificial_rows(source) -> list[dict]:
    """分類器を読まず、20場・400pairの既知障壁教師を紙上で作る。

    引数: source(ModuleType)は固定49の暦だけを使う。
    返り値: list[dict]は800人工方向行。実データや学習factoryを参照しない。
    """
    rows = []
    for index in range(400):
        session = f"2026-01-{1 + index % 20 // 2:02d}_" + ("Day" if index % 2 == 0 else "Night")
        now = source.calendar(session)[0] + 900 * (1 + index // 20)
        for side in (1, -1):
            values = [0.] * 18
            values[0], values[17] = side * (1. if index // 20 % 2 else -1.), int(side == 1)
            rows.append({"session": session, "slot_id": "人工枠" + str(index), "scheduled": now, "time": now, "line": index * 10 + 1,
                "side": side, "features": values, "filled": True, "outcome": "125" if index % 3 == 0 else "250",
                "entry_time": now + 1, "entry_line": index * 10 + 2, "entry_price": 100., "end_time": now + 61, "end_line": index * 10 + 3})
    return rows


def self_test() -> dict:
    """人工だけで回収母数・純除外・単独現金/保護/品質の接続を検査する。

    引数: なし。主検証はimportせず、実教師・実モデル・原板も読まない。
    返り値: dictは成功/差数/範囲。人工を含め分類器fitは0。
    """
    source, label_helper, _ = A.helpers()
    audit = source.Audit()
    recovery = load(Path(__file__).with_name("回収集計.py"), "回収監査_人工集計対象")
    measure = load(Path(__file__).with_name("計測.py"), "回収監査_人工計測対象")
    rows = artificial_rows(source)
    evaluation = max(r["end_time"] for r in rows) + 3600
    model = artificial_tree(rows)
    adapter = SimpleNamespace(walk=old_walk, predict=A.predict)
    measurements = {}
    for row in rows:
        leaf, _ = old_walk(model, row["features"])
        pnl = {3: -200., 4: 300., 5: 0., 6: 100.}[leaf]
        measurements[row["slot_id"], row["side"]] = {**{k: row[k] for k in ("session", "slot_id", "side")},
            "ready": True, "features": row["features"], "status": "確定完結", "barrier": {"outcome": row["outcome"], "end_time": row["end_time"]},
            "recovery_end_time": row["end_time"] + 10, "operation": {"closed": [{"pnl0": pnl + 100, "pnl5": pnl, "pnl10": pnl - 100}]}}
    expected = expected_calibration(model, measurements, evaluation)
    audit.check("全葉回収集計の全属性", recovery.aggregate(model, measurements, evaluation, adapter), expected)
    audit.check("全過去方向を使う", (expected["old_teacher_direction_rows"], expected["used_direction_rows"], expected["used_pairs"]), (800, 800, 400))
    audit.check("全葉4群空群も保存", set(expected["leaves"]), {"3", "4", "5", "6"})
    audit.check("各方向重み半分", expected["weight_per_direction"], .5)
    audit.check("平均正を額の符号で判定", [expected["leaves"][str(i)]["positive"] for i in (3, 4, 5, 6)], [False, True, False, True])
    unknown = deepcopy(measurements)
    first = next(iter(unknown))
    unknown[first]["status"] = "品質注意完結"
    subset = expected_calibration(model, unknown, evaluation)
    audit.check("品質片側でpair全体除外", (subset["used_pairs"], subset["used_direction_rows"], len(subset["excluded_pairs"])), (399, 798, 1))
    audit.check("未知をゼロへ補完しない", recovery.aggregate(model, unknown, evaluation, adapter), subset)
    for column in ("recovery_end_time", "barrier"):
        future = deepcopy(measurements)
        if column == "barrier":
            future[first][column]["end_time"] = evaluation
        else:
            future[first][column] = evaluation
        audit.check("各終了同秒を拒否", A.rejects(expected_calibration, model, future, evaluation), True)
        audit.check("主集計も終了同秒拒否", A.rejects(recovery.aggregate, model, future, evaluation, adapter), True)
    missing = deepcopy(measurements)
    del missing[first]
    audit.check("教師の片側欠落拒否", A.rejects(expected_calibration, model, missing, evaluation), True)
    pair_ids = model["training"]["row_ids"][:2]
    small_model = {**model, "training": {"row_ids": pair_ids}}
    pair = {k: deepcopy(measurements[k]) for k in ((i["slot_id"], i["side"]) for i in pair_ids)}
    same = deepcopy(next(iter(pair.values()))["features"])
    for i, row in enumerate(pair.values()):
        row["features"] = same
        row["operation"]["closed"][0].update(pnl0=100. if i else -100., pnl5=100. if i else -100., pnl10=100. if i else -100.)
    minimal = expected_calibration(small_model, pair, evaluation)
    leaf = str(old_walk(model, same)[0])
    audit.check("同leaf両側はunique一枠", (minimal["leaves"][leaf]["direction_rows"], minimal["leaves"][leaf]["unique_slots"]), (2, 1))
    audit.check("厳密平均ゼロは非正", (minimal["leaves"][leaf]["mean_yen"]["5"], minimal["leaves"][leaf]["positive"]), (0., False))
    audit.check("空葉平均None", all(v["mean_yen"]["5"] is None for k, v in minimal["leaves"].items() if k != leaf), True)
    buy, sell = [0.] * 18, [0.] * 18
    buy[0], buy[17], sell[0], sell[17] = 1., 0., -1., 1.
    vectors = {"1": buy, "-1": sell}
    calibration = deepcopy(expected)
    for record in calibration["leaves"].values():
        record["support"] = True
    calibration["leaves"]["5"].update(positive=False, mean_yen={"0": 0., "5": 0., "10": 0.})
    for policy in POLICIES:
        prediction = expected_prediction(model, calibration, vectors, policy)
        audit.check("両候補全予測", prediction, recovery.predict(model, calibration, vectors, adapter, policy))
    audit.check("最高側に非正を追加し次点救済なし", (expected_prediction(model, calibration, vectors, "C0")["side"], expected_prediction(model, calibration, vectors, "R0")["side"]), (-1, 0))
    calibration["leaves"]["5"]["support"] = False
    audit.check("共通支持で両WAIT", [expected_prediction(model, calibration, vectors, p)["side"] for p in POLICIES], [0, 0])
    audit.check("評価の未来結果を引数へ渡さない", expected_prediction(model, calibration, vectors, "C0")["prior"], A.predict(model, vectors))

    # ----------------------------------------
    # 単独測定の分母1を全予定活動へ混ぜず、通常/欠落/鏡像を小型O49で確認する。
    O = measure.O49
    session = "2026-10-01_Day"
    bounds = O.session_bounds(session)
    scheduled = bounds["start"] + 900
    base = {"session": session, "slot_id": "人工回収枠", "scheduled": scheduled, "time": scheduled, "line": 2}
    for side in (1, -1):
        for gap in (False, True):
            prices = [(bounds["start"] + 1, 100., 105.), (scheduled, 100., 105.), (scheduled + 1, 100., 105.),
                      (scheduled + 2, 125., 130.), (scheduled + 3, 105., 110.), (scheduled + (305 if gap else 4), 105., 110.)]
            events = [{"now": t, "line": i, "last": (b + a) / 2, "bid": b if side == 1 else 300 - a,
                       "ask": a if side == 1 else 300 - b, "valid": True} for i, (t, b, a) in enumerate(prices, 1)]
            pure = {k: base[k] for k in ("slot_id", "scheduled", "time", "line")}
            pure.update(side=side, role="順行", ready=True, atr=40., D=40., reason="全定時独立計測")
            identity = "I55_" + str(int(scheduled)) + ("買" if side == 1 else "売")
            operation = measure.MeasurementBank(events, session).measure(pure, identity, background_direction=side)
            full = O.replay(events, [pure], session, identity)
            audit.check("人工の全日単独射影一致", measure.comparison_view(operation), measure.comparison_view(full))
            arrays = {k: source.np.array([e[k] for e in events]) for k in ("now", "line", "last", "bid", "ask", "valid")}
            arrays.update(volume=source.np.zeros(len(events)), volume_time=source.np.zeros(len(events)))
            tape = source.tape_from_arrays(arrays, session, audit)
            tape["events"]["last"] = arrays["last"]
            _, force, end, _ = source.calendar(session)
            barrier = {**base, "side": side, "policy": "B+" if side == 1 else "B-", "role": "時刻基準",
                       **label_helper.first_force_expected(tape, {**base, "side": side}, force, source)}
            feature = {"ready": True, "reason": "", "vectors": {str(side): buy}, "background_direction": side, "atr": 40., "D": 40.}
            status, boundary = measurement_status(operation, end)
            row = {**base, "side": side, "ready": True, "feature_reason": "", "features": buy, "background_direction": side,
                "atr": 40., "D": 40., "role": "順行", "measurement_group": "人工", "barrier": barrier, "operation": operation,
                "status": status, "recovery_end_time": boundary, "decision_bbo": events[1]}
            check_measurement(row, base, feature, barrier, tape, "人工", source, audit)
            audit.check("保有間隔欠落を品質別にする", status, "品質注意完結" if gap else "確定完結")
            close = operation["closed"][0]
            audit.check("名目同値費用負け", close["pnl5"], -122.)
            different = deepcopy(close)
            different["id"] = "別候補建玉"
            audit.check("旧実完結はIDのみ除外", strict_close_equal(close, different), True)
            different["entry_price"] = int(different["entry_price"])
            audit.check("新規価格の型差は拒否", strict_close_equal(close, different), False)
    audit.check("未準備を0円実績へしない", measurement_status(None, 123.), ("技法未準備", 123.))
    boundary, cases = label_helper.self_test(source)
    audit.check("期限同秒の先頭正常原行", (boundary.bad, len(cases)), (0, 4))
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
            "分類器fit数": 0, "本物教師読取": False, "市場戦略再生": False, "主検証import": False}


def main() -> None:
    """人工又はroot本物実行後の一度の保存監査を選択する。

    引数: なし。--self-test/--run/--viewer-urlを読む。
    返り値: None。不一致で非零終了し、既存の正式証明は上書きしない。
    """
    parser = argparse.ArgumentParser(description="55の独立追尾回収・過去葉・保存運用を検査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    result = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps({k: result[k] for k in ("人工成功", "全件一致", "照合項目数", "不一致数", "分類器fit数") if k in result}, ensure_ascii=False))
    if not result.get("全件一致", result.get("人工成功")):
        print(json.dumps(result["不一致"], ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
