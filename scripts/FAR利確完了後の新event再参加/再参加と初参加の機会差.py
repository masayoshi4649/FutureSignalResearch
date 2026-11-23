"""91の3正本だけから再参加収益・同実出口差・初参加機会を分ける後段診断。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path


KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("R0", "R1"))
ROLES = ("初参加", "利確後再参加")
SIGNS = ("黒字", "赤字", "同値")


def need(condition: bool, reason: str) -> None:
    """
    機能: 入力欠落・対応矛盾を未計測成功に変えず停止する。
    引数: condition (bool)、reason (str) は成立条件と原因。
    返り値: None。不成立はValueError。
    """
    if not condition:
        raise ValueError(reason)


def sha(path: Path) -> str:
    """
    機能: 正本本文と診断コードを指紋に結ぶ。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def number(value: object) -> bool:
    """
    機能: boolと非有限値を除いた数値だけを認める。
    引数: value (object) は保存数値。
    返り値: bool は有限のint/floatなら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def read_rows(path: Path) -> list[dict]:
    """
    機能: 明示した圧縮正本を辞書行へ読む。
    引数: path (Path) はgzip JSON行。
    返り値: list[dict] は有限JSON行。欠測を0補完しない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    need(all(isinstance(r, dict) for r in rows), "圧縮正本の辞書行が必要")
    json.dumps(rows, allow_nan=False)
    return rows


def sign(value: float) -> str:
    """
    機能: 最終費用後額の符号を事後ラベルへ写す。
    引数: value (float) は純額。
    返り値: str は黒字/赤字/同値。
    """
    return "黒字" if value > 0 else "赤字" if value < 0 else "同値"


def fingerprint(row: dict) -> tuple:
    """
    機能: 同参照内の経済的に同じ実入口を識別する。
    引数: row (dict) は正式取引診断。
    返り値: tuple は場/ref/要求/方向/実取得時刻/価格/実初期量。
    """
    p = row["lot"]
    return (row["session"], p["reference_id"], row["entry_order"]["request_time"], p["side"], p["entry_time"], p["entry_price"], p["initial_quantity"])


def metrics(rows: list[dict]) -> dict:
    """
    機能: 役割又は対応群の全実参加を費用後で集計する。
    引数: rows (list[dict]) は実取得・完結済み診断。
    返り値: dict は分母・額・旗・平均勝敗。空群の平均/PFはnull。
    """
    lots = [r["lot"] for r in rows]
    wins = [p["net_pnl"] for p in lots if p["net_pnl"] > 0]
    losses = [p["net_pnl"] for p in lots if p["net_pnl"] < 0]
    return {"実参加数": len(lots), "新規枚数": sum(p["initial_quantity"] for p in lots), "費用後円": sum(p["net_pnl"] for p in lots),
            "勝ち": len(wins), "負け": len(losses), "同値": sum(p["net_pnl"] == 0 for p in lots),
            "平均勝ち円": sum(wins)/len(wins) if wins else None, "平均負け円": sum(losses)/len(losses) if losses else None,
            "PF": sum(wins)/abs(sum(losses)) if losses else None,
            "残玉正益": sum(p["flag"] for p in lots), "残玉正益後赤字": sum(p["flag"] and p["net_pnl"] < 0 for p in lots),
            "全玉正益": sum(p["whole_flag"] for p in lots), "全玉正益後赤字": sum(p["whole_flag"] and p["net_pnl"] < 0 for p in lots)}


def small(row: dict) -> dict:
    """
    機能: 実参加の重複全転記を避けた小型出典を作る。
    引数: row (dict) は取引診断。
    返り値: dict は役割/実玉/要求・取得・純額の出典。
    """
    p, o = row["lot"], row["entry_order"]
    return {"場": row["session"], "実玉ID": p["id"], "参照ID": p["reference_id"], "役割": row["entry_role"],
            "新規注文ID": o["id"], "要求時刻": o["request_time"], "方向": p["side"], "実取得時刻": p["entry_time"],
            "実取得価格": p["entry_price"], "実初期量": p["initial_quantity"], "費用後円": p["net_pnl"],
            "残玉正益": p["flag"], "全玉正益": p["whole_flag"]}


def participation(left: list[dict], right: list[dict]) -> tuple[dict, list, list, list, list, list]:
    """
    機能: fingerprint多重集合を対応し、同ref未一致とref片側を落とさず分解する。
    引数: left/right (list[dict]) はR0/R1実参加。
    返り値: tuple は正式照合用分解、同実pair、同ref未一致A/B、片refA/B。
    """
    groups = []
    for rows in (left, right):
        group = defaultdict(list)
        ids = [(r["session"], r["lot"]["id"]) for r in rows]
        need(len(ids) == len(set(ids)), "会計内のpositionが重複")
        for row in rows:
            group[fingerprint(row)].append(row)
        groups.append(group)
    a, b = groups
    refs = [{key[:2] for key in g} for g in groups]
    common_refs = refs[0] & refs[1]
    paired, unmatched_a, unmatched_b = [], [], []
    for token in sorted(set(a) | set(b)):
        first, second = a.get(token, []), b.get(token, [])
        n = min(len(first), len(second))
        paired.extend(zip(first[:n], second[:n], strict=True))
        unmatched_a.extend(first[n:])
        unmatched_b.extend(second[n:])
    same_a = [r for r in unmatched_a if (r["session"], r["lot"]["reference_id"]) in common_refs]
    same_b = [r for r in unmatched_b if (r["session"], r["lot"]["reference_id"]) in common_refs]
    only_a = [r for r in unmatched_a if (r["session"], r["lot"]["reference_id"]) not in common_refs]
    only_b = [r for r in unmatched_b if (r["session"], r["lot"]["reference_id"]) not in common_refs]
    net = lambda rows: sum(r["lot"]["net_pnl"] for r in rows)
    same_net_a, same_net_b = net([x for x, _ in paired]), net([y for _, y in paired])
    output = {"同参照ID": len(common_refs), "同実新規": len(paired), "同実新規A損益円": same_net_a, "同実新規B損益円": same_net_b,
              "同実新規出口差円": same_net_b-same_net_a, "同実役割組合せ": dict(Counter(x["entry_role"]+"→"+y["entry_role"] for x, y in paired)),
              "同ref未一致A": len(same_a), "同ref未一致B": len(same_b), "同ref未一致A損益円": net(same_a), "同ref未一致B損益円": net(same_b),
              "ref片側A": len(only_a), "ref片側B": len(only_b), "ref片側A損益円": net(only_a), "ref片側B損益円": net(only_b),
              "同ref未一致A役割": dict(Counter(r["entry_role"] for r in same_a)), "同ref未一致B役割": dict(Counter(r["entry_role"] for r in same_b)),
              "全差円": net(right)-net(left)}
    need(output["全差円"] == output["同実新規出口差円"]+net(same_b)-net(same_a)+net(only_b)-net(only_a), "全損益差の足し戻し不一致")
    need(len(left) == len(paired)+len(same_a)+len(only_a) and len(right) == len(paired)+len(same_b)+len(only_b), "多重集合の実参加数不一致")
    return output, paired, same_a, same_b, only_a, only_b


def publication_after(pub: dict, done: dict) -> tuple[bool, bool]:
    """
    機能: 保存公開点と実全返済stampの前後を読み取る。
    引数: pub/done (dict) は保存値。元Raw Index生成の独立証明はしない。
    返り値: tuple[bool,bool] は既知とstrict後。
    """
    if pub["at"] > done["at"]:
        return True, True
    if pub["at"] < done["at"]:
        return True, False
    q = pub["quote"]
    if q["time"] == done["at"] and q["index"] > done["quote_index"] and q["line"] > done["quote_line"]:
        return True, True
    if q["time"] <= done["at"] and q["index"] <= done["quote_index"] and q["line"] <= done["quote_line"]:
        return True, False
    return False, False


def sign_transitions(pairs: list[tuple[dict, dict]]) -> dict:
    """
    機能: 同実入口だけの最終黒赤/同値9群を差0も含めて記述する。
    引数: pairs (list[tuple[dict,dict]]) は多重集合で一致した実参加。
    返り値: dict は全9群の数と両純額/差額。
    """
    output = {f"{a}→{b}": {"実参加数": 0, "R0円": 0, "R1円": 0, "差円": 0, "差0玉": 0} for a in SIGNS for b in SIGNS}
    for a, b in pairs:
        pa, pb = a["lot"]["net_pnl"], b["lot"]["net_pnl"]
        group = output[sign(pa)+"→"+sign(pb)]
        for name, amount in (("実参加数", 1), ("R0円", pa), ("R1円", pb), ("差円", pb-pa), ("差0玉", pa == pb)):
            group[name] += amount
    return output


def row_prefix(row: dict, quote: dict) -> tuple[int, float]:
    """
    機能: 直前原行までに返済済みの量・実確定額を保存片から合算する。
    引数: row/quote (dict) は完結診断と定時の直前原行。
    返り値: tuple[int,float] は当時までの返済枚数・純額。未来片は除く。
    """
    pieces = [c for c in row["closed"] if c["exit_line"] <= quote["line"]]
    need(all(c["exit_time"] <= quote["time"] for c in pieces), "原行と時計の前後が不整合")
    return sum(c["quantity"] for c in pieces), sum(c["pnl5"] for c in pieces)


def analyze(result: dict, trades: list[dict], shared_rows: list[dict]) -> dict:
    """
    機能: 3正本から役割・履歴資格・対応差・占有見送りを独立集計する。
    引数: result (dict)、trades/shared_rows (list[dict]) は91正式3正本。
    返り値: dict は66場264会計の記述統計。仮想の追加売買は作らない。
    """
    need(result["試行"] == 91 and result["場数"] == 66 and result["全場既使用"] is True and set(result["比較"]) == set(KEYS), "91の固定66場4会計が必要")
    shared = {r["session"]: r for r in shared_rows}
    need(len(shared) == len(shared_rows) == 66, "共有66場は一意である必要")
    formal_pairs = {(r["session"], r["key"]) for r in result["場別"]}
    need(len(result["場別"]) == len(formal_pairs) == 264 and formal_pairs == {(s, k) for s in shared for k in KEYS}, "正式場別264会計の集合差")
    for r in result["場別"]:
        need(r["metrics"]["open_quantity"] == r["metrics"]["pending_entry_quantity"] == r["metrics"]["reserved_exit_quantity"] == 0, "未解消会計を完結実績へ混入")
    grids, selected, levels, consumed = {}, {}, [], set()
    for session, scene in shared.items():
        gm = {g["at"]: g for g in scene["grid_decisions"]}
        need(len(gm) == len(scene["grid_decisions"]), "共有定時が重複")
        grids[session] = gm
        seen = set()
        for level in scene["entry_opportunities"]:
            token = session, level["at"], level["reference_id"]
            need(token not in seen and level["at"] in gm and set(level["assessments"]) == {"R1_D0", "R1_D1"}, "機会候補の定時/ref又は遅延集合が不正")
            seen.add(token)
            op = level["opportunity"]
            need(op["known"] is True and op["at"] == level["at"] and op["reference_id"] == level["reference_id"] and op["opportunity_id"] == {"session": session, "reference_id": level["reference_id"], "event_id": op["event"]["id"]}, "機会IDと出典が不整合")
            levels.append((session, level))
            for key, a in level["assessments"].items():
                need(a["at"] == level["at"] and a["reference_id"] == level["reference_id"] and a["opportunity_id"] == op["opportunity_id"] and a["role"] in ROLES, "金融資格snapshotと機会が不一致")
                need(type(a["selected"]) is bool and type(a["consumed"]) is bool and a["selected"] == a["consumed"], "受理と今回機会消費の不一致")
                if a["selected"]:
                    identity = session, key, a["entry_order_id"]
                    need(identity not in selected and a["entry_order_id"] and a["position_id"] and type(a["accepted_serial"]) is int and a["accepted_serial"] > 0, "受理役割の注文重複/欠落")
                    opportunity_token = session, key, a["reference_id"], op["event"]["id"]
                    need(opportunity_token not in consumed and a["opportunity_seen"] is False, "同じ機会を再受理又は消費前値の不整合")
                    consumed.add(opportunity_token)
                    selected[identity] = level
    grouped = {k: [] for k in KEYS}
    by_position, actual_accepted = {}, set()
    for row in trades:
        session, key, p, o = row["session"], row["key"], row["lot"], row["entry_order"]
        identity = session, key, p["id"]
        need(session in shared and key in grouped and identity not in by_position, "実玉の対象外又は重複")
        need(type(p["initial_quantity"]) is int and 1 <= p["initial_quantity"] <= 100 and p["quantity"] == 0 and p["closed_quantity"] == p["initial_quantity"], "実取得0又は未完結玉")
        need(sum(c["quantity"] for c in row["closed"]) == p["initial_quantity"] and sum(c["pnl5"] for c in row["closed"]) == p["net_pnl"] and number(p["net_pnl"]), "返済量又は純額差")
        need(o["id"] and o["kind"] == "entry" and o["position_id"] == p["id"] and o["reference_id"] == p["reference_id"] and o["filled_quantity"] == p["initial_quantity"] and o["request_time"] in grids[session], "新規注文と実玉/定時の差")
        role = row["entry_role"]
        need(role in ROLES, "実役割が欠落")
        if key.startswith("R0_"):
            need(role == "初参加" and row["opportunity_id"] is None and row["accepted_serial"] is None, "R0役割又は未保存機会を補完")
        else:
            sid = session, key, o["id"]
            need(sid in selected, "実参加の受理assessmentが欠落")
            a = selected[sid]["assessments"][key]
            need(a["role"] == role and a["position_id"] == p["id"] and a["reference_id"] == p["reference_id"] and a["at"] == o["request_time"] and a["opportunity_id"] == row["opportunity_id"] and a["accepted_serial"] == row["accepted_serial"], "実役割/機会/受理serialの結合差")
            need(o["real_entry_stage"] == ("初参加要求" if role == "初参加" else "利確後再参加要求") and p["real_entry_stage"] == ("実初参加" if role == "初参加" else "利確後再参加"), "要求/実取得の段階が不一致")
            actual_accepted.add(sid)
        grouped[key].append(row)
        by_position[identity] = row
    accounts = {}
    for key, rows in grouped.items():
        m, formal = metrics(rows), result["比較"][key]
        need((m["実参加数"], m["新規枚数"], m["費用後円"], m["残玉正益"], m["全玉正益"], m["全玉正益後赤字"]) == tuple(formal[n] for n in ("完結玉", "新規枚数", "費用後損益円", "残玉旗", "全玉旗", "全玉旗後赤字")), "実参加と正式会計合計差")
        roles = {role: metrics([r for r in rows if r["entry_role"] == role]) for role in ROLES}
        need({r["entry_role"] for r in rows} <= set(formal["実参加役割別"]) <= set(ROLES), "正式役割集計の欠落又は対象外役割")
        requests = formal["判断"].get("新規要求", 0)
        need(type(requests) is int and requests >= len(rows), "受理要求数と実参加数が不整合")
        if key.startswith("R1_"):
            chosen = [level["assessments"][key] for (s, k, o), level in selected.items() if k == key]
            need(len(chosen) == requests, "R1全受理要求と共有資格の結合差")
            accepted_roles = dict(Counter(a["role"] for a in chosen))
        else:
            accepted_roles = {"初参加": requests}
        accounts[key] = {**m, "実役割別": roles, "受理要求": requests, "受理要求役割": accepted_roles, "実取得0の受理": requests-len(rows)}
        for role, numbers in formal["実参加役割別"].items():
            need(role in roles and all(roles[role][n] == numbers[n] for n in ("実参加数", "新規枚数", "費用後円")), "実役割別と正式集計差")
    histories, cancelled = [], []
    for sid, level in selected.items():
        session, key, order_id = sid
        a, op = level["assessments"][key], level["opportunity"]
        filled = sid in actual_accepted
        entry = {"場": session, "会計": key, "役割": a["role"], "新規注文ID": order_id, "実玉ID": a["position_id"], "参照ID": a["reference_id"],
                 "機会ID": a["opportunity_id"], "受理serial": a["accepted_serial"], "要求時刻": a["at"], "実取得あり": filled}
        if not filled:
            cancelled.append(entry)
        if a["role"] != "利確後再参加":
            continue
        previous = a["previous_actual"]
        need(previous is not None and previous["completion"] is not None, "再参加の前回実完了が欠落")
        need(previous["opportunity_id"]["event_id"] != op["event"]["id"], "前回実参加と同じeventへ再参加")
        pid = session, key, previous["position_id"]
        need(pid in by_position, "前回実参加を実取得0要求へ置換")
        prior = by_position[pid]
        q = grids[session][a["at"]]["c0"]["base"]["quote"]
        current_actuals = [r for r in grouped[key] if r["session"] == session and r["lot"]["reference_id"] == a["reference_id"] and r["lot"]["entry_line"] <= q["line"]]
        need(current_actuals and max(current_actuals, key=lambda r: r["lot"]["entry_line"])["lot"]["id"] == prior["lot"]["id"], "直近実参加を以前の勝ちへ置換")
        closed, net = row_prefix(prior, q)
        done = previous["completion"]
        pieces = [c for c in prior["closed"] if c["exit_line"] <= q["line"]]
        last = max(pieces, key=lambda c: c["exit_line"])
        need(closed == prior["lot"]["initial_quantity"] and net > 0 and previous["net_pnl"] == net and previous["quantity"] == previous["reserved_exit"] == previous["pending_entry"] == previous["pending_exit"] == 0, "再参加時に利確完了/未約定0を確認できない")
        need((done["position_id"], done["entry_order_id"], done["at"], done["quote_line"], done["initial_quantity"], done["closed_quantity"], done["net_pnl"]) == (prior["lot"]["id"], prior["entry_order"]["id"], last["exit_time"], last["exit_line"], closed, closed, net), "保存完結stampと既存実返済片が不一致")
        need(type(done["quote_index"]) is int and prior["lot"]["entry_index"] <= done["quote_index"] <= q["index"], "完結Index範囲が不正")
        pubs = {p["observation_id"]: p for p in op["publications"]}
        chronology = []
        for name, field in (("p", "pullback"), ("r", "recovery"), ("k", "confirmation")):
            point = op["event"][field]
            pub = pubs[point["observation_id"]]
            known, after = publication_after(pub, done)
            need(known and after and pub["at"] == point["published_at"] and pub["bar_end"] == point["bar_end"], "受理再参加の新p/r/kが完了後でない")
            chronology.append({"点": name, "観測ID": pub["observation_id"], "確定足時刻": pub["bar_end"], "公開時刻": pub["at"], "公開原行": pub["quote"]["line"]})
        histories.append({**entry, "前回実玉ID": prior["lot"]["id"], "前回実役割": prior["entry_role"], "前回実確定円": net,
                          "実全返済時刻": done["at"], "実全返済原行": done["quote_line"], "新p/r/k": chronology})
    comparisons = {}
    for delay in (0, 1):
        k0, k1 = f"R0_D{delay}", f"R1_D{delay}"
        decomposition, pairs, same_a, same_b, only_a, only_b = participation(grouped[k0], grouped[k1])
        formal = result["出口間の同実新規分解"][f"R1対R0_D{delay}"]
        need(all(formal[k] == v for k, v in decomposition.items()), "多重集合分解と正式正本が不一致")
        transitions = sign_transitions(pairs)
        initial0, initial1 = [r for r in grouped[k0] if r["entry_role"] == "初参加"], [r for r in grouped[k1] if r["entry_role"] == "初参加"]
        retry = [r for r in grouped[k1] if r["entry_role"] == "利確後再参加"]
        initial_delta = metrics(initial1)["費用後円"]-metrics(initial0)["費用後円"]
        need(decomposition["全差円"] == initial_delta+metrics(retry)["費用後円"], "初参加差＋再参加額の全体足し戻し不一致")
        comparisons[f"R1対R0_D{delay}"] = {**decomposition, "同実の最終黒赤同値遷移": transitions,
            "同ref未一致A役割別": {role: metrics([r for r in same_a if r["entry_role"] == role]) for role in ROLES},
            "同ref未一致B役割別": {role: metrics([r for r in same_b if r["entry_role"] == role]) for role in ROLES},
            "ref片側A役割別": {role: metrics([r for r in only_a if r["entry_role"] == role]) for role in ROLES},
            "ref片側B役割別": {role: metrics([r for r in only_b if r["entry_role"] == role]) for role in ROLES},
            "役割による別分解": {"初参加R0円": metrics(initial0)["費用後円"], "初参加R1円": metrics(initial1)["費用後円"], "初参加差円": initial_delta, "R1再参加円": metrics(retry)["費用後円"], "全差円": decomposition["全差円"]},
            "未一致の実玉出典": {"同refA": [small(r) for r in same_a], "同refB": [small(r) for r in same_b], "片refA": [small(r) for r in only_a], "片refB": [small(r) for r in only_b]}}
    blocking = {}
    for delay in (0, 1):
        key, events = f"R1_D{delay}", []
        for session, level in levels:
            a = level["assessments"][key]
            if a["role"] != "初参加" or a["reason"] != "実保有又は注文で占有":
                continue
            q = grids[session][level["at"]]["c0"]["base"]["quote"]
            owners = []
            for row in grouped[key]:
                if row["session"] != session or row["lot"]["entry_line"] > q["line"]:
                    continue
                closed, _ = row_prefix(row, q)
                if closed < row["lot"]["initial_quantity"]:
                    owners.append(row)
            need(len(owners) <= 1, "定時に複数実保有を推定")
            owner = owners[0] if owners else None
            category = owner["entry_role"]+"の実玉保有" if owner else "注文処理等・保有世代未特定"
            benchmark = [r for r in grouped[f"R0_D{delay}"] if r["session"] == session and r["lot"]["reference_id"] == a["reference_id"] and r["entry_order"]["request_time"] == a["at"]]
            need(len(benchmark) <= 1, "R0同枠の実参加が一意でない")
            events.append({"場": session, "定時": a["at"], "見送り参照ID": a["reference_id"], "eventID": a["opportunity_id"]["event_id"],
                           "分類": category, "保有実玉ID": owner["lot"]["id"] if owner else None,
                           "R0同枠実取得あり": bool(benchmark), "参考R0費用後円": benchmark[0]["lot"]["net_pnl"] if benchmark else None})
        categories = {name: {"候補数": sum(r["分類"] == name for r in events), "R0同枠実取得数": sum(r["分類"] == name and r["R0同枠実取得あり"] for r in events)} for name in ("初参加の実玉保有", "利確後再参加の実玉保有", "注文処理等・保有世代未特定")}
        blocking[key] = {"fresh占有見送り候補": len(events), "定時数": len({(r["場"], r["定時"]) for r in events}), "参照event数": len({(r["場"], r["見送り参照ID"], r["eventID"]) for r in events}), "占有元別": categories, "小型出典": events}
    return {"会計別": accounts, "対応比較": comparisons, "再参加受理の前回実完了と新event": histories, "実取得0の受理出典": cancelled, "初参加の占有見送り": blocking}


def diagnose(result_path: Path, trades_path: Path, grids_path: Path, output: Path, markdown: Path) -> dict:
    """
    機能: 明示3正本を前後不変で読み、新規JSON/MDへ後段診断を保存する。
    引数: result_path/trades_path/grids_path (Path) は正本、output/markdown (Path) は新規先。
    返り値: dict は記述統計。金融/Source/core/原板/APIに触れない。
    """
    inputs = {"結果": result_path, "取引診断": trades_path, "共有判断": grids_path}
    need(not output.exists() and not markdown.exists() and output.resolve() != markdown.resolve() and not any(p.resolve() in (output.resolve(), markdown.resolve()) for p in inputs.values()), "入力外の新規2出力が必要")
    before = {n: sha(p) for n, p in inputs.items()}
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    json.dumps(result, allow_nan=False)
    data = analyze(result, read_rows(trades_path), read_rows(grids_path))
    need(before == {n: sha(p) for n, p in inputs.items()}, "診断中の入力変化")
    value = {"試行": 91, "成功": True, "入力": {n: str(p.resolve()) for n, p in inputs.items()}, "入力SHA256": before, "診断コードSHA256": sha(Path(__file__)), **data,
             "限定": ["既使用66場の小標本に対する記述統計。再参加玉の利益だけを全体改善としない。", "同実は経済fingerprint多重集合で対応。受理ordinalや同refの1件辞書で強制対応しない。", "最終黒赤/同値と途中の正益旗は別。旗分母減を保護改善へ読み替えない。", "前回完結Indexは保存値の範囲と後先を使い、原板からの精密生成は正式Source監査へ依存。元E1/指標生成の独立再実装ではない。", "占有見送りは保存fresh assessmentの理由を分母にし、当時Lineまでの実片で保有世代を特定する。取消時計を持たない0取得処理は未特定とし、参考R0実績を失った利益や全差へ二重加算しない。", "未約定取消のみは実玉損益の分母外。受理履歴として別記し、仮想の約定/新規戦略成績を作らない。"],
             "仮想新規売買": 0, "市場再生": 0, "原板読取": 0, "API": 0, "金融変更": 0, "Source変更": 0, "core変更": 0, "閾値探索": 0}
    lines = ["# 91：再参加と初参加の機会差", "", "既存3正本だけを用いた記述統計。再参加額・初参加差・同実入口の出口差を分け、全損益差へ足し戻す。仮想の追加売買は0。", "",
             "| 会計 | 実参加/枚 | 初参加円 | 再参加円 | 全体円 | 全玉正益後赤字/正益 | 0取得受理 |", "| --- | --- | ---: | ---: | ---: | --- | ---: |"]
    for key, r in data["会計別"].items():
        lines.append(f"| {key} | {r['実参加数']}/{r['新規枚数']} | {r['実役割別']['初参加']['費用後円']:,} | {r['実役割別']['利確後再参加']['費用後円']:,} | {r['費用後円']:,} | {r['全玉正益後赤字']}/{r['全玉正益']} | {r['実取得0の受理']} |")
    lines += ["", "| 比較 | 同実出口差円 | 同ref未一致B−A円 | ref片側B−A円 | 全差円 |", "| --- | ---: | ---: | ---: | ---: |"]
    for key, r in data["対応比較"].items():
        lines.append(f"| {key} | {r['同実新規出口差円']:,} | {r['同ref未一致B損益円']-r['同ref未一致A損益円']:,} | {r['ref片側B損益円']-r['ref片側A損益円']:,} | {r['全差円']:,} |")
    lines.append("")
    for key, r in data["対応比較"].items():
        d = r["役割による別分解"]
        lines += [f"{key}の別分解：初参加差 {d['初参加差円']:,}円＋R1再参加 {d['R1再参加円']:,}円＝全差 {d['全差円']:,}円。上表とは同じ全差の別表現であり、足し合わせない。", ""]
    lines += ["同ref未一致には取得条件の変化と追加再参加が混じるため、JSONでは両側の初参加/再参加を分ける。受理serialによる強制対応はしない。", "", "初参加の占有見送りは候補・定時・参照eventを別分母で数える。", ""]
    for key, r in data["初参加の占有見送り"].items():
        lines.append(f"- {key}：fresh {r['fresh占有見送り候補']}候補/{r['定時数']}定時。このうち再参加実玉保有中 {r['占有元別']['利確後再参加の実玉保有']['候補数']}候補。")
    lines += ["", "参考R0の同枠実績は既存対照の観測であり、仮想の機会利益ではない。取消だけの処理と実保有を混ぜず、分からない取消時計を補完しない。", "",
              f"[全群と小型出典]({output.name})に、差0・同値を含む9黒赤遷移、実役割の組合せ、未一致実玉、前回実完了と新p/r/k、実取得0の受理を保持する。", "",
              "既使用小標本であり、安定利益・未使用期間での再現性は未確認。金融/Source/core変更、原板再読、閾値探索、API、新規売買再生は0。", ""]
    for path, text in ((output, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n"), (markdown, "\n".join(lines))):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    return value


def main() -> None:
    """
    機能: 将来の91正式3正本を明示して後段診断を新規保存する。
    引数: --result/--trades/--grids/--out/--md (Path) は入力3/出力2。
    返り値: None。部分入力・不整合・既存出力は停止する。
    """
    parser = argparse.ArgumentParser()
    for name in ("result", "trades", "grids", "out", "md"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    value = diagnose(args.result, args.trades, args.grids, args.out, args.md)
    print(json.dumps({"成功": value["成功"], "会計": len(value["会計別"]), "比較": len(value["対応比較"]), "仮想新規売買": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
