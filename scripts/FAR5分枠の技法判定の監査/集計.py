"""96の複合技法gateと出生一回採否を保存から結合し、固定94/95金融を再用する。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import types


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/FAR5分判断と出生一回の監査/集計.py"
OLD_SHA = "193acf7f0ddcd6b532b52d7ac7a105e2a1f61905bb97368dfeb79c177c5f5395"
DIAG_PATH = ROOT / "scripts/FAR5分判断と出生一回の監査/実現取引の診断.py"
DIAG_SHA = "14fd080723084854fb4799efdded2185220da7774d89f505a4b449d346a87be8"
BASELINE_PROOF = ROOT / "study/00095_5分判断と開始30分見送り/完了記録.json"
BASELINE_SHA = "b7df0d9f793fca1ee9fbb489e045b927f8cf4b46e0e81a6c199920f128e4d943"
BASELINE_DIR = BASELINE_PROOF.parent / "成果物"


def load_module(name: str, path: Path, expected: str):
    """
    機能: 旧codeを固定指紋で読み、globalを書き換えず再用する。
    引数: name(str)、path(Path)、expected(str)はmodule名/コード/正本SHA。
    返り値: moduleは固定旧code。原板や市場結果は読み込まない。
    """
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("固定依存SHA差: " + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


OLD = load_module("固定95出生と5分保存", OLD_PATH, OLD_SHA)
DIAG = load_module("固定95実現額の算術", DIAG_PATH, DIAG_SHA)
BASE = OLD.BASE
need, equal, number, integer = OLD.need, OLD.equal, OLD.number, OLD.integer
read_json, write_json, serial = OLD.read_json, OLD.write_json, OLD.serial
clock_delta, source_at, available_at, pending_quantity = OLD.clock_delta, OLD.source_at, OLD.available_at, OLD.pending_quantity
POLICIES = ("G0", "A", "B", "AB")
KEYS = tuple(("" if p == "G0" else p + "_") + f"B5Q_P0_C{c}_D{d}"
             for p in POLICIES for c in (0, 5) for d in (0, 1))


def key_config(key: str) -> tuple:
    """
    機能: 16口座を政策/旧95名/旧94名/費用/遅延に分ける。
    引数: key(str)は明示されたActor名。
    返り値: tuple[str,str,str,int,int]は対応情報。
    """
    need(key in KEYS, "96 Actor key")
    policy = "G0" if key.startswith("B5Q_") else key.split("_")[0]
    old95 = key if policy == "G0" else key[len(policy) + 1:]
    old94 = old95[len("B5Q_"):]
    _, cost, delay = old94.split("_")
    return policy, old95, old94, int(cost[1:]), int(delay[1:])


def project95(book: dict) -> dict:
    """
    機能: gate追加2箇所と外keyだけを除き95形式へ値投影する。
    引数: book(dict)は96ActualResult。
    返り値: dictは独立複写。注文/約定/出典/時計/採否を改変しない。
    """
    result = copy.deepcopy(book)
    result["config"].pop("gate_policy", None)
    for opportunity in result["entry_opportunities"]:
        opportunity.pop("gate", None)
    result["key"] = key_config(book["key"])[1]
    return result


def project94(book: dict) -> dict:
    """
    機能: 旧95の明示5field除外を重ねて共通金融形式へ投影する。
    引数: book(dict)は96正本。
    返り値: dictは94検算用。実ID・要求/約定時刻・費用・量は不変。
    """
    return OLD.project94(project95(book))


def accepted_entries_at_grid(book: dict, at, q: dict | None) -> set:
    """
    機能: gate後に本当に受理されたnewだけを当枠の予約へ数える。
    引数: book(dict)、at(number)、q(dict|None)は保存値と公開時計。
    返り値: set[str]は実注文ID。旧関数へ偽受理を挿入しない。
    """
    return OLD.accepted_entries_at_grid(project95(book), at, q)


def verify_book(book: dict, key: str, gate_index, full_clock: bool = False) -> dict:
    """
    機能: 固定94金融と固定95Source通知を保ち、gateを別規範へ結ぶ。
    引数: book(dict)、key(str)、gate_indexは独立技法照合器、full_clock(bool)は正式prefix検査。
    返り値: dictは金融/MTM点/機会の検算結果。
    """
    policy, _, old_key, _, _ = key_config(key)
    equal(book["key"], key, "96 key")
    fields = {"policy", "slip_pts", "delay_seconds", "entry_timing", "us_open"}
    equal(set(book["config"]), fields | ({"gate_policy"} if policy != "G0" else set()), "96 config集合")
    equal(book["config"].get("gate_policy", ""), "" if policy == "G0" else policy, "96 gate policy")
    equal(book["config"]["entry_timing"], "B5Q", "96全B5Q")
    need(number(book["config"]["us_open"], "USOpen") >= 0, "USOpen負")

    def source_validator(projected, orders, timeline):
        """
        機能: 元通知を旧95のB出生規範へ結び、96の実受理IDをそのまま使う。
        引数: projected/orders(dict)、timelineは固定94検算の型。
        返り値: None。偽のnew_signalや改時刻を作らない。
        """
        OLD.verify_source_b(book, orders, timeline)

    namespace = dict(vars(BASE))
    namespace["verify_source_events"] = source_validator
    verifier = types.FunctionType(BASE.verify_book.__code__, namespace, "固定94金融と96出生採否の結合")
    checked = verifier(project94(book), old_key)
    verify_grid(book, checked["orders"], checked["timeline"], gate_index, full_clock)
    return checked


def verify_grid_columns(value: dict, full_clock: bool = True) -> None:
    """
    機能: 同Replay全16口座のgrid連続prefixを比較する。
    引数: value(dict)は保存Replay、full_clock(bool)は正式連続prefix検査。
    返り値: None。最終EOFの取り落としは独立原板境界監査の範囲。
    """
    equal(set(value["books"]), set(KEYS), "96全16Actor")
    clocks = [row["at"] for row in value["books"][KEYS[0]]["grid_traces"]]
    for key in KEYS:
        equal([row["at"] for row in value["books"][key]["grid_traces"]], clocks, "96全16時計列")
        if full_clock: OLD.verify_grid_prefix(value["books"][key]["session"], clocks)


class Baseline95:
    """完了b7dfへ結んだ旧95B5Q四口座だけをG0全文対照にする。"""

    def __init__(self, folder: Path, proof_path: Path):
        """
        機能: 正式95完了記録と既存保存指紋を検査する。
        引数: folder(Path)、proof_path(Path)は明示された旧正本。
        返り値: None。95実績の別評価や条件変更はしない。
        """
        self.folder, self.proof_path = folder.resolve(), proof_path.resolve()
        equal(hashlib.sha256(self.proof_path.read_bytes()).hexdigest(), BASELINE_SHA, "固定95完了SHA")
        self.files = {name.replace("\\", "/"): sha for name, sha in read_json(self.proof_path)["自己を除く正式指紋"].items()}
        self.reads = {}

    def compare(self, value: dict) -> dict:
        """
        機能: G0四口座を旧95B5Qへ全field比較する。
        引数: value(dict)は96Replay。
        返り値: dictは旧圧縮保存指紋と一致件数。金額の再推定をしない。
        """
        path = self.folder / (value["session"] + ".json.gz")
        body = path.read_bytes(); sha = hashlib.sha256(body).hexdigest()
        equal(sha, self.files["成果物/" + path.name], "固定95圧縮NativeSHA")
        self.reads[path] = sha
        old = json.loads(gzip.decompress(body), parse_float=Decimal)
        equal(old["session"], value["session"], "G0基準場")
        keys = [key for key in KEYS if key_config(key)[0] == "G0"]
        for key in keys:
            equal(value["books"][key], old["books"][key], "G0対95B5Q全文:" + key)
        return {"session": value["session"], "基準保存SHA256": sha, "基準完了SHA256": BASELINE_SHA,
                "一致口座": keys, "G0除外field": []}


def verify_grid(book: dict, orders: dict, timeline, gate_index, full_clock: bool) -> None:
    """
    機能: 一枠寿命/quiet/Source状態/受理順/実注文とgrid分母を保存から独立結合する。
    引数: book/orders(dict)、timeline(Timeline)、gate_index(独立技法照合器)、full_clock(bool)は正式の開始からの連続prefixを要求するか。
    返り値: None。全原行の最新気配/slot取り落としは別境界監査にも分担する。
    """
    policy, _, _, _, _ = key_config(book["key"]); timing = "B5Q"
    cfg, session = book["config"], book["session"]
    opportunities, grids = book["entry_opportunities"], book["grid_traces"]
    births = {(e["method"], e["signal_id"]): e for e in book["source_events"] if e["kind"] == "new_signal"}
    need(len(opportunities) == len(births), "全出生/全Opportunity")
    accepted, seen, source_cache = set(), set(), {}
    cap_rejected = cap_clipped = 0
    previous = None
    for n, p in enumerate(opportunities, 1):
        need(type(p["ordinal"]) is int, "Opportunity連番の型")
        equal(p["ordinal"], n, "Opportunity連番")
        key = BASE.source_identity(p["source"]); need(key in births and key not in seen, "Opportunity出生一意"); seen.add(key)
        event = births[key]
        equal(p["source"]["birth_time"], event["at"], "出生時刻不変")
        equal(p["source"]["birth_quote"], event["quote"], "出生原行不変")
        equal(p["side"], event["side"], "出生方向")
        assigned = (number(event["at"], "birth") // 300 + 1) * 300
        equal(p["assigned_at"], assigned, "strict次5分")
        order = (event["at"], event["quote"]["index"], event["quote"]["source_line"], integer(p["batch_index"], "batch"), integer(p["signal_index"], "signal"))
        need(previous is None or previous <= order, "出生の安定順"); previous = order
        need(p["consumed"] is True and p["evaluated_at"] is not None and p["status"] in ("accepted", "expired")
             and type(p["required_unknown"]) is bool, "最終機会状態")
        if timing == "N":
            equal(p["evaluated_at"], event["at"], "N評価時計")
            equal(p["requested"], event["actual_accepted"], "N実受理")
            equal(p["entry_order_id"], event["order_id"], "N注文結合")
            need(p["required_unknown"] is False, "NにB系未知gateを追加しない")
        else:
            at, q = p["evaluated_at"], p["quote"]
            need(at >= event["at"], "出生前の受付")
            if q is not None:
                BASE.quote(q, "Opportunity.quote", normal=False)
                need(q["time"] <= at, "未来気配")
                equal(p["quote_age_seconds"], clock_delta(at, q["time"]), "気配age")
                equal(p["available"], available_at(book, orders, timeline, at, q, p["side"], accepted), "slot前の予約込み空き")
            else: need(p["quote_age_seconds"] is None, "quoteなしage")
            cache_key = at, None if q is None else q["index"]
            if cache_key not in source_cache: source_cache[cache_key] = source_at(book, at, q)
            h = source_cache[cache_key][key]
            equal(p["source_state"], h["state"], "当時Source状態")
            equal(p["source_hold_id"], h["hold"], "当時SourceHold")
            equal(p["source_quantity"], h["q"], "当時Source残量")
            equal(p["source_reserved"], h["reserved"], "当時Source予約")
            eof = p["reason"] == "EOFで未消費出生機会を失効"
            deadline = min(session["force_close"], cfg["us_open"] - 900) if key[0] == "NK225_P164_06" else session["force_close"]
            quiet = session["start"] <= at < session["start"] + 1800 or (session["kind"] == "Night" and cfg["us_open"] > 0 and cfg["us_open"] <= at < cfg["us_open"] + 1800)
            known_quote = q is not None and q["quote_ok"] and q["ask"] > q["bid"] > 0
            refusal = eof or at != assigned or at >= deadline or (timing == "B5Q" and quiet) or h["state"] in ("pending", "cancelled") or h["q"] == 0 or (h["reserved"] or 0) > 0
            unknown = not refusal and not known_quote
            eligible = not refusal and not unknown and p["available"] > 0
            cap_rejected += not refusal and not unknown and p["available"] == 0
            if policy == "G0":
                need("gate" not in p, "G0へ新gateを混ぜない")
            elif eligible:
                decision = gate_index.claim(book["key"], p)
                need(isinstance(p.get("gate"), dict) and all(type(p["gate"].get(n)) is bool for n in ("known", "allowed")), "機会Gateのbool型")
                equal(p.get("gate"), decision, "96適格機会の技法判定全値")
                unknown = not decision["known"]
                eligible = decision["known"] and decision["allowed"]
                if not eligible: equal(p["reason"], decision["reason"], "96技法見送り理由")
            else:
                need("gate" not in p, "元金融の不適格候補へgateを呼ばない")
            equal(p["required_unknown"], unknown, "政策必須未知")
            equal(p["status"], "accepted" if eligible else "expired", "機会の独立採否")
            expected_quantity = min(p["source"]["birth_quantity"], h["q"], p["available"]) if eligible else 0
            equal(p["requested"], expected_quantity, "slot要求の3値min")
            cap_clipped += eligible and p["available"] < min(p["source"]["birth_quantity"], h["q"])
        if p["status"] == "accepted":
            o = orders[p["entry_order_id"]]
            for field, expected in (("kind", "entry"), ("source", p["source"]), ("side", p["side"]),
                ("quantity", p["requested"]), ("request_time", p["evaluated_at"]), ("request_quote", p["quote"])):
                equal(o[field], expected, "機会/実注文." + field)
            if timing != "N": equal(o["source_hold_id"], p["source_hold_id"], "grid取得済SourceHold")
            accepted.add(o["id"])
        else: need(p["requested"] == 0 and not p["entry_order_id"], "失効機会の架空注文")
    equal(accepted, {o["id"] for o in orders.values() if o["kind"] == "entry"}, "全新規注文の機会結合")
    by_grid = defaultdict(list)
    for p in opportunities:
        if timing != "N" and p["reason"] != "EOFで未消費出生機会を失効": by_grid[p["evaluated_at"]].append(p)
    last = None
    for trace in grids:
        at = trace["at"]
        need(at % 300 == 0 and session["start"] <= at < session["end"] and (last is None or last < at), "grid時計")
        last = at; equal(trace["timing"], timing, "grid入口名")
        q = trace["quote"]
        if q is not None:
            BASE.quote(q, "Grid.quote", normal=False); need(q["time"] <= at, "grid未来原行")
            equal(trace["quote_age_seconds"], clock_delta(at, q["time"]), "grid age")
        else: need(trace["quote_age_seconds"] is None, "grid quoteなしage")
        equal(trace["quote_known"], q is not None and q["quote_ok"] and q["ask"] > q["bid"] > 0, "grid正常性")
        equal(trace["us_clock_known"], session["kind"] == "Day" or cfg["us_open"] > 0, "米国時計既知")
        us_quiet = cfg["us_open"] <= at < cfg["us_open"] + 1800 if session["kind"] == "Night" and cfg["us_open"] > 0 else None
        equal(trace["us_quiet"], us_quiet, "米国quiet")
        quiet = session["start"] <= at < session["start"] + 1800 or us_quiet is True
        equal(trace["quiet"], quiet, "quiet半開境界"); equal(trace["quiet_applied"], quiet and timing == "B5Q", "quiet実適用")
        points = by_grid.get(at, [])
        equal(trace["ordinals"], [p["ordinal"] for p in points], "枠の候補順")
        for field, expected in (("candidate_count", len(points)), ("accepted_count", sum(p["status"] == "accepted" for p in points)),
            ("accepted_quantity", sum(p["requested"] for p in points)), ("expired_count", sum(p["status"] == "expired" for p in points)),
            ("unknown_count", sum(p["required_unknown"] for p in points))): equal(trace[field], expected, "grid." + field)
        if q is not None:
            point = {"quote": q, "phase": "after_source"}
            for side, field in ((1, "open_buy"), (-1, "open_sell")):
                owned = sum(h["quantity"] for pid in timeline.histories if (h := timeline.state_at(pid, point)) is not None and h["side"] == side)
                equal(trace[field], owned, "grid実保有")
            known_orders = accepted_entries_at_grid(book, at, q)
            for side, field in ((1, "pending_buy"), (-1, "pending_sell")):
                equal(trace[field], pending_quantity(book, orders, timeline, at, q, side, known_orders),
                      f"grid new予約量 {session['id']}/{book['key']}/at={at}/side={side}")
        action = "新規" if trace["accepted_count"] else "保有" if trace["open_buy"] + trace["open_sell"] else "判定不能" if trace["unknown_count"] else "待機"
        equal(trace["action"], action, "grid行動優先")
    if full_clock:
        OLD.verify_grid_prefix(session, [t["at"] for t in grids])
    metrics = {"births": len(opportunities), "grid_calls": len(grids), "quiet_grids": sum(t["quiet"] for t in grids),
        "unknown_us_grids": sum(not t["us_clock_known"] for t in grids), "accepted": sum(p["status"] == "accepted" for p in opportunities),
        "expired": sum(p["status"] == "expired" for p in opportunities), "required_unknown": sum(p["required_unknown"] for p in opportunities),
        "eof_expired": sum(p["reason"] == "EOFで未消費出生機会を失効" for p in opportunities)}
    for action, field in (("新規", "new_grids"), ("保有", "holding_grids"), ("待機", "waiting_grids"), ("判定不能", "unknown_grids")):
        metrics[field] = sum(t["action"] == action for t in grids)
    equal(book["grid_metrics"], metrics, "96 grid計数全体")
    equal(book["metrics"]["cap_rejected_entries"], cap_rejected, "96金融前のcap拒否件数")
    equal(book["metrics"]["cap_clipped_entries"], cap_clipped, "96受理時のcap縮小件数")


def realized_row(book: dict) -> dict:
    """
    機能: 完結玉の正負/uW赤字額/PFと保存MTMを旧算術で要約する。
    引数: book(dict)は独立金融検算済みの96口座。
    返り値: dictは実取引だけの計数。極値の全原板再生成はしない。
    """
    row = DIAG.new_row()
    for position in book["positions"]:
        DIAG.OLD.add_position(row, position)
    DIAG.finish_row(row, key_config(book["key"])[1])
    account = book["account"]
    if account["first"] is not None:
        equal(account["first"]["equity"], 0, "場頭flatのMTM")
        equal(account["last"]["equity"], row["純額円"], "実現額と末尾MTM")
        equal(account["last"]["open_buy"] + account["last"]["open_sell"], 0, "場末flat")
    row.update({"場内最大DD円": account["max_drawdown"],
                "場内MTM最大円": account["max"]["equity"] if account["max"] else Decimal(0),
                "場内MTM最小円": account["min"]["equity"] if account["min"] else Decimal(0)})
    return row


def analyze_saved(values, baseline, scope: str) -> dict:
    """
    機能: G0固定対照と全16口座を1場ずつ保存検算・集約する。
    引数: values(iterable[dict])、baseline(比較器)、scope(str)は正式/接続/人工。
    返り値: dictは会計・実現額・gate条件計数。未参加仮想利益は計算しない。
    """
    need(scope in ("正式", "接続", "人工"), "96集計scope")
    gate_path = Path(__file__).with_name("技法の保存照合.py")
    gates = load_module("96独立技法保存", gate_path, hashlib.sha256(gate_path.read_bytes()).hexdigest())
    groups = {key:defaultdict(Decimal) for key in KEYS}
    diagnostics = {key:DIAG.new_row() for key in KEYS}
    rows, matches, sessions, comparisons = [], [], set(), defaultdict(list)
    gate_groups = defaultdict(Counter)
    gate_calls = Counter()
    session_diagnostics = {key:[] for key in KEYS}
    for value in values:
        session = value["session"]; need(session not in sessions, "96場重複");sessions.add(session)
        verify_grid_columns(value, full_clock=scope != "人工")
        if scope != "人工":
            need(value["shadow_match"]["all"] is True and value["shadow_match"]["baseline_proof_sha256"] == "e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37", "固定93Shadow")
            methods = {"D164_15"} if session.endswith("_Day") else {"P164_06", "U165_03"}
            equal(set(value["shadows"]), methods, "96Source手法集合")
            equal(value["shadow_match"]["methods"], {m:True for m in methods}, "全SourceShadow一致")
        if baseline is not None:
            matches.append(baseline.compare(value))
        else:
            need(scope == "人工", "正式/接続ではG0旧正本比較必須")
        gate_index = gates.GateIndex(value)
        checked = {}
        for key in KEYS:
            book = value["books"][key]
            current = checked[key] = verify_book(book,key,gate_index,full_clock=scope != "人工")
            row = realized_row(book)
            equal(row["玉数"], current["counts"]["positions"], "実玉分母")
            equal(row["純額円"], current["totals"]["net_yen"], "実玉/金融純額")
            for name in DIAG.COUNTERS:
                diagnostics[key][name] += row[name]
            session_diagnostics[key].append({"session":session,**row})
            rows.append({"session":session,"key":key,"gate_policy":book["config"].get("gate_policy",""),"gate_label":key_config(key)[0],"totals":current["totals"],
                         "counts":current["counts"],"grid_metrics":book["grid_metrics"],
                         "account_max_drawdown_yen":current["account_max_drawdown_yen"],"実現診断":row})
            group = groups[key]
            for name,amount in current["totals"].items():group[name] += amount
            for name,amount in current["counts"].items():group[name] += amount
            for name,amount in book["grid_metrics"].items():group["grid_"+name] += amount
            group["active_sessions"] += current["counts"]["positions"] > 0
            group["negative_sessions"] += current["totals"]["net_yen"] < 0
            group["max_session_mtm_drawdown_yen"] = max(group["max_session_mtm_drawdown_yen"],current["account_max_drawdown_yen"])
            for opportunity in book["entry_opportunities"]:
                d = opportunity.get("gate")
                if d is not None:
                    state = "成立" if d["allowed"] else "既知不成立" if d["known"] else "未知"
                    gate_calls[key+"/"+state] += 1
                else: gate_calls[key+"/技法前の金融判定又はEOF"] += 1
        gate_summary = gate_index.finish([t["at"] for t in value["books"][KEYS[0]]["grid_traces"]])
        for name,counts in gate_summary["条件別"].items(): gate_groups[name].update(counts)
        gate_calls["共有枠"] += gate_summary["共有枠"]
        gate_calls["適格出生判定"] += gate_summary["適格出生判定"]
        for cost in (0,5):
            for delay in (0,1):
                old = f"B5Q_P0_C{cost}_D{delay}"
                for policy in ("A","B","AB"):
                    new = policy+"_"+old
                    comparisons[new+"対"+old].append({"session":session,**BASE.compare_positions(checked[old],checked[new])})
    if scope != "人工": equal(len(sessions),54 if scope == "正式" else 2,"96場数")
    for key,row in diagnostics.items():
        DIAG.finish_row(row,key_config(key)[1])
        chronological = sorted(session_diagnostics[key],key=lambda s:(s["session"][:10],0 if s["session"].endswith("_Day") else 1))
        row["保存極値を連結した最大DD円"] = DIAG.joined_dd(chronological)
        row["場内最大DD円"] = max((s["場内最大DD円"] for s in chronological),default=Decimal(0))
    return {"試行":96,"成功":True,"scope":scope,"場数":len(sessions),"Actor数":16,"会計数":len(rows),
            "Actor設定":{key:{"gate_policy":"" if key_config(key)[0] == "G0" else key_config(key)[0],"gate_label":key_config(key)[0],"entry_timing":"B5Q","policy":"P0","slip_pts":key_config(key)[3],"delay_seconds":key_config(key)[4]} for key in KEYS},
            "集計":{key:dict(row) for key,row in groups.items()},"実現診断":diagnostics,"場別":rows,
            "Gate条件採否":{name:dict(counts) for name,counts in gate_groups.items()},"Gate呼出分母":dict(gate_calls),
            "同実入口と実現額差":dict(comparisons),"G0四会計の固定95対照":matches,
            "基準95完了SHA256":BASELINE_SHA,"由来95集計SHA256":OLD_SHA,"由来95診断SHA256":DIAG_SHA,
            "検算範囲":"固定94の金融/費用/配賦/MTM点と95のSource通知・出生一回を維持し、96の元適格後gateの全checks・三値採否・一枠消費を独立結合。",
            "評価":"実取得玉の実現額/PF/uW赤字額/保存極値DD。未参加や決済後の仮想利益を計算しない。",
            "限界":"保存MTM極値の全原板取り落とし・チャート原行からの全再計算はこの集計の範囲外。available_atは論理公開時計、実受信時計の証拠ではない。量支持は板数量/OFIで約定出来高ではない。",
            "未実施":{"金融再生":0,"原板本文読取":0,"ViewerAPI":0,"未参加仮想利益":0,"資本金ROI":None}}


def render(result: dict) -> str:
    """
    機能: 16口座の実現額と技法分母を短いMarkdownへ出す。
    引数: result(dict)は全保存検算済み集計。
    返り値: strは閲覧用。利益保証や単独指標の効果と呼ばない。
    """
    lines = ["# 96：現在の複合技法と出生一回・保存会計", "",
             f"{result['場数']}場/{result['会計数']}会計、scope={result['scope']}。全B5Q/P0、C0は指定片道38.5円、C5は追加5pt片道を含む別運転。", "",
             "| 政策/key | 玉/枚 | gross円 | 指定fee円 | 仮定slip円 | net円 | PF | u正益後最終赤字/正益玉 | W正益後最終赤字/正益玉 | 保存極値連結DD円 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        r,d = result["集計"][key],result["実現診断"][key]
        pf = d["PF"] if d["PF"] is not None else "未定義"
        lines.append(f"| {key_config(key)[0]}/{key} | {r['positions']}/{r['entry_quantity']} | {r['gross_yen']} | {r['fee_yen']} | {r['slip_yen']} | {r['net_yen']} | {pf} | {d['u正益後最終赤字玉']}/{d['u正益玉']} | {d['W正益後最終赤字玉']}/{d['W正益玉']} | {d['保存極値を連結した最大DD円']} |")
    lines += ["", "| 口座 | 技法成立 | 既知不成立 | 必要未知 | 技法前の金融判定又はEOF |", "| --- | ---: | ---: | ---: | ---: |"]
    calls = result["Gate呼出分母"]
    for key in KEYS:
        lines.append("| " + key + " | " + " | ".join(str(calls.get(key+"/"+name,0)) for name in ("成立","既知不成立","未知","技法前の金融判定又はEOF")) + " |")
    lines += ["", "G0四口座は固定95 B5Qの全fieldと一致する対照。A/B/ABは元のSource・quiet・気配・容量が適格な出生だけへ追加する。ABはA/Bの三値ORであり、両役割の同時ANDではない。", "",
              "個別checkの分母は実際にgateを呼んだ候補。先行する保有と予約が変わるため、政策間の全実新規集合の包含までは仮定しない。", "",
              "PFは完結玉の正純額/負純額絶対値、負純額0なら未定義。u/W赤字額は該当玉の最終実純額合計。DDは独立検算済み保存極値をflat境界で連結した値で、全原板から極値を再生成した証明と区別する。", "",
              "各口座で成立した実取引を評価し、未参加/決済後の仮想利益は計算しない。チャート指標や板数量の複合効果を単独指標の収益効果としない。", ""]
    return "\n".join(lines)


def main() -> None:
    """
    機能: 指紋付きNative保存のみを読んで96資源と保存集計を作る。
    引数: --run/--out(Path)、--limit(2又は54)、--baseline/--baseline-proof(Path)。
    返り値: None。不整合は非0、既存保存先へは書き込まない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--limit",type=int,choices=(2,54),default=54)
    parser.add_argument("--baseline",type=Path,default=BASELINE_DIR)
    parser.add_argument("--baseline-proof",type=Path,default=BASELINE_PROOF)
    args = parser.parse_args();need(not args.out.exists(),"新規保存先のみ")
    completion_path = args.run/"完了.json";completion = read_json(completion_path)
    equal(completion["場数"],args.limit,"96完了場数");equal(len(completion["結果SHA256"]),args.limit,"96保存数")
    gate_path = Path(__file__).with_name("技法の保存照合.py")
    code_files = [Path(__file__),gate_path,OLD_PATH,DIAG_PATH,OLD.BASE_PATH,DIAG.OLD_PATH,completion_path,args.baseline_proof]
    code_before = {str(path.resolve()):hashlib.sha256(path.read_bytes()).hexdigest() for path in code_files}
    baseline = Baseline95(args.baseline,args.baseline_proof)
    before,resources = {},[]
    args.out.mkdir(parents=True)

    def values():
        """
        機能: 1場ずつ圧縮複写/Viewer変換し、実正本を独立検算へ渡す。
        引数: なし。外側CLIの入力/出力を使用する。
        返り値: iterator[dict]。元の金融/技法値は改変しない。
        """
        for name,expected in sorted(completion["結果SHA256"].items()):
            path = (args.run/name).resolve()
            need(path.is_relative_to(args.run.resolve()) and path.suffix == ".json","96入力path境界")
            body = path.read_bytes();equal(hashlib.sha256(body).hexdigest(),expected,"96Native保存SHA")
            value = json.loads(body,parse_float=Decimal,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
            before[name] = expected
            yield value
            for key in KEYS:
                policy = key_config(key)[0];identity = "96_"+key+"_"+value["session"]
                trade_path = identity+".trades.jsonl"
                with (args.out/trade_path).open("x",encoding="utf-8",newline="\n") as stream:
                    for row in OLD.viewer_trades(value["books"][key]):
                        stream.write(json.dumps(row,ensure_ascii=False,default=serial,allow_nan=False)+"\n")
                resources.append({"id":identity,"title":"複合技法 "+policy+"/"+key+" "+value["session"],"symbol":"NK225","product":"NK225mini","session":value["session"],"method_id":key,"point_value":100,"pnl_format":"trades","pnl_basis":"net","pnl_path":trade_path,"market_path":"NK225/"+value["session"]+"/book.jsonl.gz"})
            with (args.out/(Path(name).name+".gz")).open("xb") as file:
                with gzip.GzipFile(filename="",mode="wb",fileobj=file,mtime=0) as stream:stream.write(body)

    result = analyze_saved(values(),baseline,"正式" if args.limit == 54 else "接続")
    equal(len(resources),args.limit*16,"96Viewer資源数")
    after = {name:hashlib.sha256((args.run/name).read_bytes()).hexdigest() for name in before}
    equal(after,before,"96入力前後不変")
    code_after = {name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in code_before}
    equal(code_after,code_before,"96コード/完了前後不変")
    for path,expected in baseline.reads.items():equal(hashlib.sha256(path.read_bytes()).hexdigest(),expected,"旧95入力前後不変")
    result.update(入力SHA256=before,入力SHA256前=before,入力SHA256後=after,入力前後不変=True,
                  完了記録SHA256=code_before[str(completion_path.resolve())],集計コードSHA256=code_before[str(Path(__file__).resolve())],
                  技法照合コードSHA256=code_before[str(gate_path.resolve())],依存SHA256前=code_before,依存SHA256後=code_after)
    write_json(args.out/"結果.json",result)
    write_json(args.out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
    (args.out/"結果.md").write_text(render(result),encoding="utf-8",newline="\n")
    print(json.dumps({"成功":True,"scope":result["scope"],"場数":args.limit,"会計数":args.limit*16,"閲覧資源":len(resources)},ensure_ascii=False))


if __name__ == "__main__":
    main()
