"""固定した序盤帯反応を、定時枠・仮想先着・実保護へ分けて検証する。"""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00049_15分定時の序盤帯反応"
WORK = ROOT / "work/定時帯反応/00049"
MANIFEST = ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
FRAME_SHA = "db5afa37a5cd7de91a4f649b8f9cbcc21f301cb73e9ca4930d09cc24234cd6fa"
MANIFEST_SHA = "680b831ee6bef1ec1cf49dc6283931f5b0ca9611f15f5c19d81af6e4738aaf9b"
SOURCE = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
JST = timezone(timedelta(hours=9))
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("S0", "S1")


def sha(path: Path) -> str:
    """ファイルの内容指紋を計算する。

    引数: path(Path)は入力。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict | list) -> None:
    """日本語JSONをUTF-8で保存する。

    引数: path(Path)は保存先、value(dict|list)は内容。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    """JSON正本を読む。

    引数: path(Path)は入力。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def module(filename: str):
    """同フォルダの純機械を読み込む。

    引数: filename(str)はファイル名。
    返り値: ModuleTypeは読込モジュール。
    """
    spec = importlib.util.spec_from_file_location("定時帯反応_" + filename, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def bounds(session: str) -> tuple[float, float, float]:
    """場名から開始・強制・連続終了時計を求める。

    引数: session(str)は開始日を含む場名。
    返り値: tuple[float,float,float]はUNIX秒。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        return tuple((day + timedelta(hours=h, minutes=m)).timestamp() for h, m in ((8, 45), (15, 35), (15, 40)))
    if session.endswith("_Night"):
        return tuple((day + timedelta(hours=h, minutes=m)).timestamp() for h, m in ((17, 0), (29, 50), (29, 55)))
    raise ValueError("場名が不正です")


def period(session: str) -> str:
    """既使用データの固定区分を返す。

    引数: session(str)は場名。
    返り値: strは期間名。
    """
    return "後続検査" if session[:10] >= "2026-11-04" else "条件選択" if session[:10] >= "2026-10-19" else "学習"


def inputs() -> tuple[dict, list[dict]]:
    """固定台帳と価格足だけを照合し、入口計算用に射影する。

    引数: なし。
    返り値: tuple[dict,list[dict]]は台帳と場別SOURCE。
    """
    if sha(MANIFEST) != MANIFEST_SHA or sha(FRAMES) != FRAME_SHA:
        raise ValueError("固定済みの価格入力に変更があります")
    manifest = read_json(MANIFEST)
    grouped = defaultdict(lambda: {3: [], 15: []})
    with gzip.open(FRAMES, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["minutes"] in (3, 15):
                grouped[row["場"]][row["minutes"]].append({k: row[k] for k in SOURCE})
    sessions = []
    for entry in manifest["entries"]:
        if entry["symbol"] != "NK225" or len(entry["in_session_contract_codes"]) != 1:
            raise ValueError("NK225の単一限月だけを使用します")
        session = entry["session"]
        begin, _, end = bounds(session)
        sessions.append({"session": session, "contract": tuple(entry["in_session_contract_codes"]),
                         "begin": begin, "end": end, "frames3": grouped[session][3], "frames15": grouped[session][15]})
    if len(sessions) != 66 or len(grouped) != 66:
        raise ValueError("既使用66場の入力集合が不一致です")
    return manifest, sessions


def events_for(entry: dict) -> tuple[list[dict], dict]:
    """共有8列キャッシュから有限非後退の場内イベントだけを読む。

    引数: entry(dict)は台帳行。
    返り値: tuple[list[dict],dict]は原行順のイベントと除外件数。
    """
    path = ROOT / "work/複合検証" / entry["cache_path"]
    if sha(path) != entry["sha256_cache"]:
        raise ValueError("共有キャッシュの指紋が不一致です")
    begin, _, end = bounds(entry["session"])
    events, quality, previous = [], Counter(), -math.inf
    with np.load(path, allow_pickle=False) as data:
        names = ("now", "line", "last", "bid", "ask", "valid", "volume", "volume_time")
        if set(data.files) != set(names):
            raise ValueError("キャッシュ列が不一致です")
        for raw in zip(*(data[k] for k in names)):
            now, line, last, bid, ask, valid, _, _ = raw
            if not math.isfinite(float(now)):
                quality["時計欠測"] += 1
                continue
            if now < previous:
                quality["時計後退"] += 1
                continue
            previous = now
            if not begin <= now < end:
                quality["場外"] += 1
                continue
            events.append({"now": float(now), "line": int(line), "last": float(last),
                           "bid": float(bid), "ask": float(ask), "valid": bool(valid)})
    return events, dict(quality)


def normal(event: dict) -> bool:
    """数量を含む元flagとBBO価格の正常性を判定する。

    引数: event(dict)は価格イベント。
    返り値: boolは約定・追尾への利用可否。
    """
    return bool(event["valid"] and math.isfinite(event["bid"]) and math.isfinite(event["ask"])
                and 0 < event["bid"] < event["ask"])


def make_slots(events: list[dict], session: str, bank: dict, entry_module, operation_module) -> dict:
    """各予定枠を一つの判定イベント又は欠測へ対応付ける。

    引数: events(list[dict])は価格、session(str)は場、bank(dict)は指標、二moduleは純実装。
    返り値: dictはS0/S1の全予定枠。
    """
    times = [event["now"] for event in events]
    result = {p: [] for p in POLICIES}
    for scheduled in operation_module.scheduled_times(session):
        index = bisect_left(times, scheduled)
        event = events[index] if index < len(events) and times[index] <= scheduled + 30 else None
        for policy in POLICIES:
            base = {"scheduled": scheduled, "time": event["now"] if event else scheduled,
                    "line": event["line"] if event else None,
                    "slot_id": f"{session}_{int(scheduled)}", "session": session, "policy": policy}
            if event is None or not normal(event):
                feature = {"side": 0, "role": "", "atr": None, "D": None, "ready": False,
                           "reason": "判断時計欠測" if event is None else "判断BBO不正"}
            else:
                feature = entry_module.evaluate_slot(bank, session, scheduled, event["now"], event["line"], policy)
            result[policy].append({**feature, **base})
    return result


def label(events: list[dict], slot: dict, force: float) -> dict:
    """実建玉占有とは独立に、仮想約定後の125/250先着を調べる。

    引数: events(list[dict])は正常板のみ、slot(dict)は当時入口、force(float)は期限。
    返り値: dictは未約定・先着・期限・不足と出典。
    """
    result = {k: slot[k] for k in ("slot_id", "session", "policy", "scheduled", "time", "line", "side", "role")}
    result.update(filled=False, outcome="未約定", end_time=slot["time"] + 30, end_line=slot["line"])
    fill_index = next((i for i, e in enumerate(events) if slot["time"] + 1 <= e["now"] <= slot["time"] + 30
                       and e["line"] > slot["line"]), None)
    if fill_index is None:
        return result
    fill = events[fill_index]
    side = slot["side"]
    price = fill["ask"] if side == 1 else fill["bid"]
    result.update(filled=True, entry_time=fill["now"], entry_line=fill["line"], entry_price=price)
    previous, high, low = fill["now"], 0.0, 0.0
    result["outcome"] = "不足"
    for e in events[fill_index:]:
        if e["now"] > force:
            result.update(outcome="期限" if force - previous <= 300 else "不足", end_time=force, end_line=e["line"])
            break
        r = side * ((e["bid"] if side == 1 else e["ask"]) - price)
        high, low = max(high, r), min(low, r)
        result.update(end_time=e["now"], end_line=e["line"], mfe=high, mae=low)
        if e["now"] - previous > 300:
            result["outcome"] = "不足"
            break
        previous = e["now"]
        if r <= -125 or r >= 250:
            result["outcome"] = "125" if r <= -125 else "250"
            break
        if e["now"] == force:
            result["outcome"] = "期限"
            break
    return result


def entry_stats(rows: list[dict], target_period: str) -> dict:
    """先着母数と重ならない間引き、支持を集計する。

    引数: rows(list[dict])は仮想記録、target_period(str)は区分。
    返り値: dictは率・母数・支持。
    """
    chosen = [r for r in rows if period(r["session"]) == target_period]
    filled = [r for r in chosen if r["filled"]]
    thin, last = [], {}
    for r in filled:
        key = r["session"]
        if (r["entry_time"], r["entry_line"]) > last.get(key, (-math.inf, -1)):
            thin.append(r)
            last[key] = r["end_time"], r["end_line"]
    n, nt = len(filled), len(thin)
    wins, wt = sum(r["outcome"] == "250" for r in filled), sum(r["outcome"] == "250" for r in thin)
    days, sessions = len({r["session"][:10] for r in filled}), len({r["session"] for r in filled})
    req = (60, 6, 10, 20) if target_period == "学習" else (20, 3, 5, 10)
    support = n >= req[0] and days >= req[1] and sessions >= req[2] and nt >= req[3]
    return {"候補": len(chosen), "約定": n, "250": wins, "結果別": dict(Counter(r["outcome"] for r in chosen)),
            "率": wins / n if n else None, "間引き約定": nt, "間引き250": wt, "間引き率": wt / nt if nt else None,
            "日数": days, "場数": sessions, "支持": support,
            "70目標": support and wins / n >= .7 and wt / nt >= .7 if n and nt else False}


def freeze() -> None:
    """結果前の計画・実装・使用入力を固定する。

    引数: なし。
    返り値: None。既存固定は上書きしない。
    """
    target = STUDY / "固定.json"
    if target.exists():
        raise FileExistsError("既存固定を上書きしません")
    manifest, _ = inputs()
    files = [STUDY / "検証計画.md", STUDY / "条件.json", STUDY / "入力台帳.json", MANIFEST, FRAMES,
             *sorted(Path(__file__).parent.glob("*.py")),
             Path(__file__).with_name("運用仕様.md"), Path(__file__).with_name("README.md"),
             ROOT / "docs/議論/手法と時間スケールの汎用表_版5.md"]
    files += [ROOT / "work/複合検証" / e["cache_path"] for e in manifest["entries"]]
    write_json(target, {"固定日時": datetime.now(JST).isoformat(), "市場実行前": True,
                       "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
                       "Python": platform.python_version(), "NumPy": np.__version__, "全66場既使用": True})
    print("条件・入力・実行コードの固定を保存しました")


def verify_lock() -> None:
    """固定からの変更を市場実行前に拒否する。

    引数: なし。
    返り値: None。不整合は例外。
    """
    lock = read_json(STUDY / "固定.json")
    for relative, expected in lock["ファイルSHA256"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError("固定後の変更: " + relative)


def operation_stats(blocks: list[dict], target_period: str) -> dict:
    """予定枠・実約定・費用・品質を期間別に合計する。

    引数: blocks(list[dict])は場別運用、target_period(str)は区分。
    返り値: dictは観測額と全体確定額を分けた成績。
    """
    chosen = [b for b in blocks if period(b["session"]) == target_period]
    decisions = [r for b in chosen for r in b["decisions"]]
    closed = [{**r, "session": b["session"]} for b in chosen for r in b["closed"]]
    counts = Counter(r["action"] for r in decisions)
    waiting = counts["待ち"]
    invalid = counts["判定不能"]
    n = len(decisions)
    caution = [b["session"] for b in chosen if not b["quality"]["損益確定可能"]]
    unresolved = sum(b["quality"]["未解消建玉数"] for b in chosen)
    observed = {str(f): sum(r["pnl" + str(f)] for r in closed) for f in (0, 5, 10)}
    ledger = {str(f): observed[str(f)] - unresolved * (11 + f * 10) for f in (0, 5, 10)}
    days = len({r["session"][:10] for r in closed})
    sessions = len({r["session"] for r in closed})
    buys = sum(r["side"] == 1 for r in closed)
    sells = len(closed) - buys
    req = (20, 6, 10, 5, 5) if target_period == "学習" else (10, 3, 6, 3, 3)
    support = all(a >= b for a, b in zip((len(closed), days, sessions, buys, sells), req))
    flat = [r for r in decisions if not r["holding"] and r["pending_kind"] is None]
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for trade in sorted(closed, key=lambda r: (r["exit_time"], r["exit_line"])):
        equity += trade["pnl5"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"予定枠": n, "判断別": dict(counts), "待ち数": waiting, "主待ち率": waiting / n if n else None,
            "判定不能": invalid, "待ち率保守上限": (waiting + invalid) / n if n else None,
            "全枠判定可能": invalid == 0, "活動適格": n > 0 and (waiting + invalid) / n <= .5,
            "空き枠待ち率": waiting / len(flat) if flat else None,
            "完結数": len(closed), "買い": buys, "売り": sells, "日数": days, "場数": sessions,
            "品質注意場": caution, "未解消": unresolved, "完結観測額円": observed,
            "台帳観測額円": ledger, "全体確定額円": {k: v if not caution else None for k, v in ledger.items()},
            "費用支持": support, "費用適格": support and not caution and ledger["5"] > 0,
            "起動後赤字件数5": sum(r["arm"] and r["pnl5"] < 0 for r in closed),
            "利益起動件数": sum(r["arm"] for r in closed),
            "役割別完結": {role: {"件数": sum(r["role"] == role for r in closed),
                                    "観測純額5": sum(r["pnl5"] for r in closed if r["role"] == role)}
                            for role in ("順行", "反転")},
            "実250到達件数": sum(r["mfe"] >= 250 for r in closed),
            "定時外返済件数": sum(r["exit_time"] not in {d["time"] for d in decisions} for r in closed),
            "返済理由": dict(Counter(r["exit_reason"] for r in closed)),
            "平均保有秒": sum(r["exit_time"] - r["entry_time"] for r in closed) / len(closed) if closed else None,
            "完結確定系列最大DD5円": drawdown,
            "完結黒字率5": sum(r["pnl5"] > 0 for r in closed) / len(closed) if closed else None,
            "売買別損益5": {"買い": sum(r["pnl5"] for r in closed if r["side"] == 1),
                            "売り": sum(r["pnl5"] for r in closed if r["side"] == -1)}}


def jsonline(stream, value: dict) -> None:
    """一つの詳細行を非NaN JSONで保存する。

    引数: stream(TextIO)は保存先、value(dict)は内容。
    返り値: None。
    """
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")


def run() -> None:
    """固定後の全66場を一度だけ評価し、再計算なしで帳票を作る。

    引数: なし。
    返り値: None。結果がある場合は上書きしない。
    """
    if (STUDY / "結果.json").exists() or (WORK / "実行開始.json").exists():
        raise FileExistsError("実行済み又は開始済みです。既存のプロセスと成果物を調べてください")
    verify_lock()
    manifest, sessions = inputs()
    I, O = module("入口.py"), module("運用.py")
    bank = I.build_bank(sessions)
    WORK.mkdir(parents=True, exist_ok=True)
    write_json(WORK / "実行開始.json", {"開始": datetime.now(JST).isoformat(), "固定SHA256": sha(STUDY / "固定.json")})
    labels = {p: [] for p in (*POLICIES, "B+", "B-")}
    operations = {p: [] for p in POLICIES}
    feature_pairs, resources, sessions_summary = [], [], []
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as detail:
        for entry in manifest["entries"]:
            session = entry["session"]
            events, input_quality = events_for(entry)
            normal_events = [e for e in events if normal(e)]
            slots = make_slots(events, session, bank, I, O)
            _, force, _ = bounds(session)
            for a, b in zip(slots["S0"], slots["S1"]):
                feature_pairs.append({"session": session, "slot_id": a["slot_id"], "S0": {k: a[k] for k in ("side", "role", "reason", "ready")},
                                      "S1": {k: b[k] for k in ("side", "role", "reason", "ready")}})
                if a["line"] is not None and a["reason"] != "判断BBO不正":
                    for side, policy in ((1, "B+"), (-1, "B-")):
                        baseline = {**a, "side": side, "policy": policy, "role": "時刻基準"}
                        labels[policy].append(label(normal_events, baseline, force))
            for policy in POLICIES:
                for slot in slots[policy]:
                    if slot["ready"] and slot["side"]:
                        row = label(normal_events, slot, force)
                        boundary = slot["OR"]["high" if (slot["role"] == "順行") == (slot["side"] == 1) else "low"]
                        distance = slot["side"] * (row["entry_price"] - boundary) / slot["atr"] if row["filled"] else None
                        bucket = "未約定" if distance is None else "端へ逆戻り" if distance < 0 else "1ATR以下" if distance <= 1 else "1超2ATR以下" if distance <= 2 else "2ATR超"
                        row.update(取得距離ATR=distance, 距離区分=bucket, 帯端=boundary, 入口ATR=slot["atr"])
                        labels[policy].append(row)
                pure = [{k: s[k] for k in O.SLOT_FIELDS} for s in slots[policy]]
                result = O.replay(events, pure, session, policy)
                operations[policy].append(result)
                jsonline(detail, {"session": session, "policy": policy, "input_quality": input_quality,
                                  "slots": slots[policy], "operation": result})
                trade_path = STUDY / "viewer" / (session + "_" + policy + ".trades.jsonl")
                trade_path.parent.mkdir(parents=True, exist_ok=True)
                with trade_path.open("w", encoding="utf-8") as stream:
                    for trade in result["trades"]:
                        jsonline(stream, trade)
                resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 定時帯反応",
                                  "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                                  "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                                  "pnl_path": trade_path.relative_to(STUDY).as_posix(), "market_path": entry["source_path"]})
                sessions_summary.append({"場": session, "候補": policy, "期間": period(session),
                                         "入力品質": input_quality, "運用品質": result["quality"], "運用集計": result["metrics"]})
            print(session + " 完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for rows in labels.values():
            for row in rows:
                jsonline(stream, row)
    table = {}
    for policy in POLICIES:
        table[policy] = {}
        for span in PERIODS:
            e, o = entry_stats(labels[policy], span), operation_stats(operations[policy], span)
            table[policy][span] = {"入口": e, "運用": o, "同時適格": e["70目標"] and o["活動適格"] and o["費用適格"]}
    paired = {}
    for span in PERIODS:
        rows = [r for r in feature_pairs if period(r["session"]) == span and r["S0"]["side"]]
        excluded = [r for r in rows if not r["S1"]["side"]]
        excluded_ids = {r["slot_id"] for r in excluded}
        paired[span] = {"S0採用": len(rows), "S1除外": len(excluded), "除外理由": dict(Counter(r["S1"]["reason"] for r in excluded)),
                        "除外群先着": entry_stats([r for r in labels["S0"] if r["slot_id"] in excluded_ids], span)}
    result = {"試行": 49, "実行日時": datetime.now(JST).isoformat(), "全66場既使用": True,
              "固定SHA256": sha(STUDY / "固定.json"), "候補": table, "上位追加の対応": paired,
              "時刻基準": {p: {s: entry_stats(labels[p], s) for s in PERIODS} for p in ("B+", "B-")},
              "役割別入口": {p: {s: {role: entry_stats([r for r in labels[p] if r["role"] == role], s)
                                   for role in ("順行", "反転")} for s in PERIODS} for p in POLICIES},
              "局面診断": {p: {s: {role: {bucket: entry_stats([r for r in labels[p] if r["role"] == role and r["距離区分"] == bucket], s)
                                           for bucket in ("端へ逆戻り", "1ATR以下", "1超2ATR以下", "2ATR超")}
                                     for role in ("順行", "反転")} for s in PERIODS} for p in POLICIES},
              "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
              "場別": sessions_summary, "詳細": {p.name: sha(p) for p in WORK.glob("*.jsonl.gz")}}
    write_json(STUDY / "結果.json", result)
    write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    write_json(WORK / "実行完了.json", {"完了": datetime.now(JST).isoformat(), "結果SHA256": sha(STUDY / "結果.json")})
    print(json.dumps({"候補": table, "採用": result["採用"]}, ensure_ascii=False))


def main() -> None:
    """固定又は一度の市場検証をCLIから実行する。

    引数: なし。argparseから操作を受け取る。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.freeze == args.run:
        parser.error("--freeze 又は --run を一つ指定してください")
    if args.freeze:
        freeze()
    else:
        run()


if __name__ == "__main__":
    main()
