"""86の固定複合退出を保存会計から事後診断する。"""
# 派生元: scripts/保持帯の返済側固定否定/出口差診断.py
# 派生元SHA256: 9ed9fc1496670120731c488ddb25fba31b47fbff4c5b03ed55f90ba917700611
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo


KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("J0G1", "J1G1"))
CONFIRM_REASON = "保持帯両気配1tick・短秒反対確認"
COUNTS = ("normal_quotes", "price_not_breached_short_known", "price_not_breached_short_unknown", "price_breached_short_unknown", "price_breached_not_opposed", "confirmed")
ROOT = Path(__file__).resolve().parents[2]
CLASSIFY_PATH = ROOT / "scripts/構造否定と利益配分/出口差の診断.py"
CLASSIFY_SHA = "de0c8d544185a24dd67e5a2e2a1799082b4c49f6ef998cf291683a3b8d53ae96"


def need(condition: bool, message: str) -> None:
    """
    機能: 診断の必要条件を最適化設定に関係なく検査する。
    引数: condition(bool)、message(str)は条件と失敗理由。
    返り値: None。不成立ならValueError。
    """
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    """
    機能: 入力・依存・コードの全byte指紋を計算する。
    引数: path(Path)は実ファイル。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def yen(value: int | float) -> int:
    """
    機能: この研究の整数円会計を丸めず検査する。
    引数: value(int|float)は保存金額。
    返り値: intは同じ円額。bool・非有限・端数は拒否。
    """
    need(type(value) in (int, float) and math.isfinite(value) and value == int(value), "整数円の会計が必要です")
    return int(value)


def load_classification() -> object:
    """
    機能: 固定83の11符号分類関数だけを読取再用する。
    引数: なし。停止SHAが一致する小型コードだけを対象とする。
    返り値: objectはclassify/CATEGORIESを持つモジュール。市場・旧mainは実行しない。
    """
    need(sha(CLASSIFY_PATH) == CLASSIFY_SHA, "旧83分類コードが変わりました")
    spec = importlib.util.spec_from_file_location("固定83出口符号分類86", CLASSIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLASSIFY = load_classification()


def read_json(path: Path) -> dict:
    """
    機能: 非有限JSON定数を拒否して保存objectを読む。
    引数: path(Path)は保存ファイル。
    返り値: dictはJSON object。
    """
    def reject(value: str) -> None:
        """
        機能: NaN/Infinityを保存観測へ混ぜないよう拒否する。
        引数: value(str)は不正定数。
        返り値: None。常にValueError。
        """
        raise ValueError(f"非有限JSON定数:{value}")

    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject)
    need(isinstance(value, dict), "JSONルートはobjectが必要です")
    return value


def totals(rows: list[dict]) -> dict:
    """
    機能: 既存玉群の黒赤・件数・費用後金額を集約する。
    引数: rows(list[dict])は小型玉記録。
    返り値: dictは既存玉の金額統計。別戦略の再生利益ではない。
    """
    values = [row["費用後損益円"] for row in rows]
    return {"玉数": len(values), "損益円": sum(values), "黒字玉": sum(value > 0 for value in values),
        "黒字損益円": sum(value for value in values if value > 0), "赤字玉": sum(value < 0 for value in values),
        "赤字損益円": sum(value for value in values if value < 0), "同値玉": sum(value == 0 for value in values)}


def attributes(rows: list[dict]) -> dict:
    """
    機能: 正益前後と保持帯状態の重なり得る属性を既存玉全体へ付ける。
    引数: rows(list[dict])は小型実玉記録。
    返り値: dictは属性別既存金額。属性間は加算しない。
    """
    groups = {"全玉": rows,
        "残玉正益未観測": [row for row in rows if not row["残玉正益"]],
        "残玉正益観測": [row for row in rows if row["残玉正益"]],
        "残玉正益観測後の最終赤字": [row for row in rows if row["残玉正益"] and row["費用後損益円"] < 0],
        "全玉正益観測後の最終赤字": [row for row in rows if row["全玉正益"] and row["費用後損益円"] < 0],
        "複合確認成立あり": [row for row in rows if row["初回複合確認"] is not None],
        "複合確認の実返済あり": [row for row in rows if row["複合確認理由の実返済枚数"] > 0],
        "複合確認時は残玉正益前": [row for row in rows if row["複合確認時の残玉正益"] is False],
        "複合確認時は残玉正益後": [row for row in rows if row["複合確認時の残玉正益"] is True]}
    return {name: totals(group) for name, group in groups.items()}


def counts(value: dict) -> dict:
    """
    機能: 正常残玉原行の排他的5群と分母の整数整合を検査する。
    引数: value(dict)は保存ConfirmCounts。
    返り値: dictは同じ6値。不正又は分母の不一致は停止。
    """
    need(set(value) == set(COUNTS), "確認5群のschema不一致")
    need(all(type(value[name]) is int and value[name] >= 0 for name in COUNTS), "確認5群は非負整数が必要")
    need(value["normal_quotes"] == sum(value[name] for name in COUNTS[1:]), "確認5群と正常残玉原行の分母が不一致")
    return dict(value)


def known_rates(value: dict) -> dict:
    """
    機能: 保存された正常残玉原行について短秒既知率を分母付きで計算する。
    引数: value(dict)は照合済み6counter。
    返り値: dictは全正常行と価格否定行の二分母。分母0の率はNone。
    """
    known = value["price_not_breached_short_known"] + value["price_breached_not_opposed"] + value["confirmed"]
    breached = value["price_breached_short_unknown"] + value["price_breached_not_opposed"] + value["confirmed"]
    breached_known = value["price_breached_not_opposed"] + value["confirmed"]
    return {"正常残玉原行": value["normal_quotes"], "短秒両既知原行": known,
        "短秒両既知率": known / value["normal_quotes"] if value["normal_quotes"] else None,
        "価格否定原行": breached, "価格否定かつ短秒両既知原行": breached_known,
        "価格否定時の短秒両既知率": breached_known / breached if breached else None}


def evidence(value: dict, lot: dict) -> None:
    """
    機能: 保存された確認snapshotの当時出典と固定条件の内部整合だけを検査する。
    引数: value(dict)、lot(dict)は保存証拠と所有玉。
    返り値: None。原板の窓再構成や新たな金融要求は行わない。
    """
    need(value["rule_version"] == 1 and value["at"] == value["source_time"] == value["received"], "確認証拠の版・当原行時計が不一致")
    need(all(type(value[name]) is int and value[name] >= (1 if name == "source_line" else 0) for name in ("quote_index", "source_line", "feature_index")), "確認証拠の源番号が不正")
    need(all(type(value[name]) in (int, float) and math.isfinite(value[name]) for name in ("at", "last", "bid", "ask")), "確認証拠に非有限値")
    need(value["last"] > 0 and 0 < value["bid"] < value["ask"] and value["bid"] % 10 == value["ask"] % 10 == 0, "確認証拠の正常気配・格子が不正")
    short = value["short"]
    need(short["time"] == value["at"] and short["mid"] == value["bid"]+(value["ask"]-value["bid"])/2, "確認証拠の短秒現在が不一致")
    for name, horizon in (("five", 5), ("fifteen", 15)):
        window = short[name]
        need(type(window["known"]) is bool and all(type(window[n]) in (int, float) and math.isfinite(window[n]) for n in ("move", "speed", "elapsed", "endpoint", "delay")), "確認証拠の短秒schema・有限性が不正")
        if window["known"]:
            need(window["elapsed"] >= horizon and window["elapsed"] == short["time"]-window["endpoint"] and window["endpoint"] <= short["time"]-horizon and window["delay"] == window["elapsed"]-horizon and 0 <= window["delay"] <= 15 and window["speed"] == window["move"]/window["elapsed"], "既知短秒の両端・単位が不整合")
    side, anchor = lot["side"], lot["hold_anchor"]
    price = side*(value["bid"]-anchor["hold_bid"]) <= -10 and side*(value["ask"]-anchor["hold_ask"]) <= -10
    known = short["five"]["known"] and short["fifteen"]["known"]
    opposed = known and side*short["five"]["speed"] < 0 and side*short["fifteen"]["speed"] < 0
    need(value["price_breached"] is price and value["short_known"] is known and value["opposed"] is opposed and value["confirmed"] is (price and opposed), "保存確認booleanと保存値が不一致")
    need(value["quote_index"] >= lot["entry_index"] and value["at"] >= lot["entry_time"], "確認証拠が実取得より過去")


def confirm_lot(lot: dict, orders: list[dict], closed: list[dict], active: bool) -> dict:
    """
    機能: 確認成立と新理由の実返済を分離し、先行返済片への初回証拠の遡及を防ぐ。
    引数: lot(dict)、orders/closed(list[dict])、active(bool)は保存玉・同所有の注文/片・J1設定。
    返り値: dictは当時証拠と事後実返済・既知率。符号から返済理由を推定しない。
    """
    counter = counts(lot["confirm_counts"])
    firsts = {name: lot[name] for name in ("confirm_first_price_breach", "confirm_first_unknown", "confirm_first_confirmed")}
    for name, value in firsts.items():
        if value is not None:
            evidence(value, lot)
            need(value["price_breached"], "初回証拠に価格否定がありません")
            if name == "confirm_first_unknown":
                need(not value["short_known"], "未知初回に既知短秒")
            elif name == "confirm_first_confirmed":
                need(value["confirmed"], "成立初回が未成立")
    need((firsts["confirm_first_confirmed"] is not None) == (counter["confirmed"] > 0), "確認成立counterと初回が不一致")
    need((firsts["confirm_first_unknown"] is not None) == (counter["price_breached_short_unknown"] > 0), "確認未知counterと初回が不一致")
    need((firsts["confirm_first_price_breach"] is not None) == (sum(counter[n] for n in COUNTS[3:]) > 0), "価格否定counterと初回が不一致")
    order_by_request = {}
    for order in orders:
        value = order["confirm_evidence"]
        is_new = order["kind"] == "exit" and order["reason"] == CONFIRM_REASON
        need((value is not None) is is_new, "新理由と注文確認証拠が不一致")
        if is_new:
            evidence(value, lot)
            need(value["confirmed"] and value["reason"] == CONFIRM_REASON and value["at"] == order["request_time"] and value["quote_index"] == order["request_index"] and value["source_line"] == order["request_line"], "新要求と成立原行の結合不一致")
        if order["kind"] == "exit":
            identity = (order["request_time"], order["reason"])
            need(identity not in order_by_request, "同時同理由の返済要求が重複")
            order_by_request[identity] = order
    for piece in closed:
        order = order_by_request.get((piece["request_time"], piece["reason"]))
        need(order is not None and piece["confirm_request_evidence"] == order["confirm_evidence"], "返済片と受理済み要求証拠が不一致")
        for name, final_value in firsts.items():
            value = piece[name]
            if value is not None:
                need(value == final_value and (value["at"], value["source_line"]) < (piece["exit_time"], piece["exit_line"]), "先行返済片へ後の確認を遡及しました")
    if not active:
        need(not any(counter.values()) and all(value is None for value in firsts.values()) and all(order["confirm_evidence"] is None for order in orders), "J0に追加観測又は要求")
    first = firsts["confirm_first_confirmed"]
    return {"複合確認5群": counter, "短秒既知率": known_rates(counter),
        "初回価格否定": firsts["confirm_first_price_breach"], "初回価格否定時の短秒未知": firsts["confirm_first_unknown"], "初回複合確認": first,
        "複合確認時の残玉正益": None if first is None else bool(lot["flag"] and lot["flag_index"] <= first["quote_index"]),
        "複合確認理由の返済注文数": sum(order["reason"] == CONFIRM_REASON for order in orders),
        "複合確認理由の実返済枚数": sum(piece["quantity"] for piece in closed if piece["reason"] == CONFIRM_REASON)}


def collect(sessions: list[dict]) -> dict:
    """
    機能: 全4会計の完結玉を要求時計/方向へ結び、固定保持帯と事後属性を小型化する。
    引数: sessions(list[dict])は順序固定の保存結果。原板は使わない。
    返り値: dictは外側会計別の一意な実玉map。不整合は停止。
    """
    output = {key: {} for key in KEYS}
    for session in sessions:
        name = session["session"]
        need(set(session["books"]) == set(KEYS), "4会計が揃いません")
        grids = {grid["at"]: grid for grid in session["grid_decisions"]}
        need(len(grids) == len(session["grid_decisions"]), "定時が重複しています")
        for key in KEYS:
            book = session["books"][key]
            active = key.startswith("J1")
            projected = book.get("_集計投影", False)
            need(book["session"] == name and book["fill_delay_seconds"] == int(key[-1]), "場又は遅延不一致")
            if projected:
                metric = book["metrics"]
                need(metric["open_quantity"] == metric["pending_entry_quantity"] == metric["reserved_exit_quantity"] == 0, "集計会計に未完結の量があります")
            else:
                need(book["mode"] == "S0G1" and book["hold_enabled"] is False and book["confirm_enabled"] is active and book["side_cap"] == 100, "金融内部mode/保持帯off/on/数量不一致")
                need(not book["unresolved"] and book["metrics"]["open_quantity"] == 0, "未完結会計を診断できません")
                decision_map = {decision["at"]: decision for decision in book["decisions"]}
                need(len(decision_map) == len(book["decisions"]) and set(decision_map) == set(grids), "金融の定時が不一致")
            for lot in book["lots"]:
                orders = [order for order in book["orders"] if order["position_id"] == lot["id"]]
                entries = [order for order in orders if order["kind"] == "entry"]
                closed = [piece for piece in book["closed"] if piece["position_id"] == lot["id"]]
                need(len(entries) == 1 and lot["quantity"] == 0 and lot["initial_quantity"] == 100, "新規又は完結玉の不整合")
                entry = entries[0]
                at, side = entry["request_time"], lot["side"]
                need(at in grids and side in (-1, 1) and type(side) is int and entry["side"] == side, "要求時計又は方向が不一致")
                need(entry["filled_quantity"] == 100 and entry["fill_time"] == lot["entry_time"] and entry["fill_price"] == lot["entry_price"], "実新規と注文が不一致")
                need(sum(piece["quantity"] for piece in closed) == 100, "返済量が不一致")
                pnl = yen(lot["net_pnl"])
                need(sum(yen(piece["pnl5"]) for piece in closed) == pnl, "玉と返済片の1円不一致")
                grid, anchor = grids[at], lot["hold_anchor"]
                need(grid["clock_allowed"] and grid["candidate_accepted"] and grid["policies"]["C0"]["candidate_accepted"], "実新規に元C0候補がありません")
                need(anchor["known"] and anchor == entry["hold_anchor"] == grid["hold_anchor"], "当時の保持帯出典が不一致")
                need(anchor["side"] == side and anchor["at"] == at and anchor["tick"] == 10 and anchor["rule_version"] == 1, "保持帯の方向/時計/版が不一致")
                stop = anchor["hold_bid"] - 10 if side > 0 else anchor["hold_ask"] + 10
                need(anchor["stop_price"] == stop and all(order["hold_anchor"] == anchor for order in orders) and all(piece["hold_anchor"] == anchor for piece in closed), "固定停止線又は固定出典継承が不一致")
                need(lot["hold_active"] is False and lot["hold_floor"] is None, "旧保持帯床を活性化しました")
                confirmation = confirm_lot(lot, orders, closed, active)
                reasons = defaultdict(lambda: {"返済枚数": 0, "損益円": 0})
                for piece in closed:
                    reasons[piece["reason"]]["返済枚数"] += piece["quantity"]
                    reasons[piece["reason"]]["損益円"] += yen(piece["pnl5"])
                identity = (name, at, side)
                need(identity not in output[key], "同一要求時計方向の実玉重複")
                output[key][identity] = {"実新規": (lot["entry_time"], lot["entry_price"], lot["initial_quantity"]),
                    "元役割": lot["role"], "費用後損益円": pnl, "残玉正益": lot["flag"], "初回残玉正益時計": lot["flag_time"],
                    "全玉正益": lot["whole_flag"], "初回全玉正益時計": lot["whole_flag_time"],
                    "保持帯": anchor, **confirmation,
                    "返済理由別": dict(reasons)}
            need(sum(row["費用後損益円"] for identity, row in output[key].items() if identity[0] == name) == yen(book["metrics"]["net_pnl_yen"]), "玉合計と会計総額が不一致")
            chosen = [row for identity, row in output[key].items() if identity[0] == name]
            total_counts = {field: sum(row["複合確認5群"][field] for row in chosen) for field in COUNTS}
            need(total_counts == counts(book["metrics"]["confirm_counts"]), "玉と会計の複合確認5群が不一致")
            need(sum(row["初回複合確認"] is not None for row in chosen) == book["metrics"]["confirm_confirmed_lots"], "成立玉数が会計と不一致")
            need(sum(row["複合確認理由の返済注文数"] for row in chosen) == book["metrics"]["confirm_exit_orders"], "新理由要求数が会計と不一致")
            need(total_counts["confirmed"] == book["metrics"]["confirm_exit_obligations"] and book["metrics"]["confirm_missing_quantity"] == 0, "成立原行又は未予約量が不整合")
    return output


def amount(values: dict, chosen: set) -> int:
    """
    機能: 指定した要求時計集合の既存金額を合計する。
    引数: values(dict)は玉map、chosen(set)は要求時計/方向の集合。
    返り値: intは既存玉金額の合計。
    """
    return sum(values[key]["費用後損益円"] for key in chosen)


def snapshot(row: dict | None) -> dict | None:
    """
    機能: 共通保持帯を全玉表へ一度だけ置くため側別値を小型化する。
    引数: row(dict|None)は片側実玉又は不参加。
    返り値: dict|Noneは保持帯出典以外の実約定・事後結果。
    """
    return None if row is None else {name: value for name, value in row.items() if name != "保持帯"}


def compare(left: dict, right: dict) -> dict:
    """
    機能: 同実入口の出口差と、取得変更/片側参加による差を完全分解する。
    引数: left/right(dict)はJ0/J1の要求時計別玉。
    返り値: dictは符号分類・正益前後・全実玉表と差寄与。
    """
    common = left.keys() & right.keys()
    exact = {key for key in common if left[key]["実新規"] == right[key]["実新規"]}
    changed, only_a, only_b = common-exact, left.keys()-right.keys(), right.keys()-left.keys()
    legacy = {"同実新規": len(exact), "同実新規A損益円": amount(left, exact), "同実新規B損益円": amount(right, exact),
        "同実新規出口差円": amount(right, exact)-amount(left, exact), "共通だが取得変更": len(changed),
        "取得変更A損益円": amount(left, changed), "取得変更B損益円": amount(right, changed),
        "Aのみ": len(only_a), "Bのみ": len(only_b), "Aのみ損益円": amount(left, only_a), "Bのみ損益円": amount(right, only_b)}
    groups = {name: {"玉数": 0, "A損益円": 0, "B損益円": 0, "差円": 0} for name in CLASSIFY.CATEGORIES}
    flags = {f"A{a}/B{b}": {"玉数": 0, "A損益円": 0, "B損益円": 0, "差円": 0} for a in ("未観測", "正益観測") for b in ("未観測", "正益観測")}
    confirm_groups = {name: {"玉数": 0, "A損益円": 0, "B損益円": 0, "差円": 0} for name in ("新理由実返済あり", "成立のみ・新理由実返済なし", "確認未成立")}
    all_rows = []
    for identity in sorted(left.keys() | right.keys()):
        a, b = left.get(identity), right.get(identity)
        if a is not None and b is not None:
            need(a["保持帯"] == b["保持帯"] and a["元役割"] == b["元役割"], "同一C0要求の保持帯又は役割が不一致")
        anchor = (a if a is not None else b)["保持帯"]
        delta = (b["費用後損益円"] if b is not None else 0) - (a["費用後損益円"] if a is not None else 0)
        category = "取得変更" if identity in changed else "J0のみ" if identity in only_a else "J1のみ" if identity in only_b else CLASSIFY.classify(a["費用後損益円"], b["費用後損益円"])
        if identity in exact:
            group = groups[category]
            flag_group = flags[f"A{'正益観測' if a['残玉正益'] else '未観測'}/B{'正益観測' if b['残玉正益'] else '未観測'}"]
            confirm_group = confirm_groups["新理由実返済あり" if b["複合確認理由の実返済枚数"] > 0 else "成立のみ・新理由実返済なし" if b["初回複合確認"] is not None else "確認未成立"]
            for group_value in (group, flag_group, confirm_group):
                group_value["玉数"] += 1
                group_value["A損益円"] += a["費用後損益円"]
                group_value["B損益円"] += b["費用後損益円"]
                group_value["差円"] += delta
        all_rows.append({"場": identity[0], "要求時計": identity[1], "方向": identity[2], "実入口分類": category,
            "同実新規": identity in exact, "保持帯": anchor, "J0": snapshot(a), "J1": snapshot(b), "差寄与円": delta})
    contributions = {"同実新規出口差": legacy["同実新規出口差円"],
        "取得変更差": legacy["取得変更B損益円"]-legacy["取得変更A損益円"],
        "J0のみの消失": -legacy["Aのみ損益円"], "J1のみの追加": legacy["Bのみ損益円"]}
    total = sum(row["費用後損益円"] for row in right.values()) - sum(row["費用後損益円"] for row in left.values())
    need(sum(contributions.values()) == sum(row["差寄与円"] for row in all_rows) == total, "差寄与又は全実玉表と全差が不一致")
    need(sum(row["玉数"] for row in groups.values()) == len(exact), "符号分類の漏れ")
    need(sum(row["差円"] for row in groups.values()) == sum(row["差円"] for row in flags.values()) == legacy["同実新規出口差円"], "符号/正益状態と同実入口差が不一致")
    need(sum(row["玉数"] for row in confirm_groups.values()) == len(exact) and sum(row["差円"] for row in confirm_groups.values()) == legacy["同実新規出口差円"], "確認・実返済群の分解漏れ")
    return {"正式分解": legacy, "全差円": total, "差寄与円": contributions, "同実新規の符号分類": groups,
        "同実新規の残玉正益状態": flags, "同実新規のJ1実返済状態": confirm_groups, "全実玉対比": all_rows,
        "J0のみの既存額": totals([left[key] for key in only_a]), "J1のみの既存額": totals([right[key] for key in only_b])}


def diagnose(sessions: list[dict], formal: dict) -> dict:
    """
    機能: 4会計と2遅延比較を正式総額・出口間分解へ結ぶ。
    引数: sessions(list[dict])は保存会計、formal(dict)は86集計の正本。
    返り値: dictは小型診断。1円・件数・固定出典の差は停止する。
    """
    books = collect(sessions)
    need(set(formal["比較"]) == set(KEYS), "正式4会計キーが不一致")
    summaries = {key: attributes(list(rows.values())) for key, rows in books.items()}
    for key, groups in summaries.items():
        old = formal["比較"][key]
        need(groups["全玉"]["玉数"] == old["完結玉"] and groups["全玉"]["損益円"] == yen(old["費用後損益円"]), "正式総額/玉数と不一致")
        need(groups["残玉正益未観測"]["損益円"] == yen(old["正益未観測の損益円"]), "正式の正益前額と不一致")
        need(groups["残玉正益観測"]["損益円"] == yen(old["正益観測の損益円"]), "正式の正益後額と不一致")
        need(groups["全玉正益観測後の最終赤字"]["玉数"] == old["全玉旗後赤字"], "全玉旗後赤字数が不一致")
    confirmations = {}
    for key, rows in books.items():
        counter = {field: sum(row["複合確認5群"][field] for row in rows.values()) for field in COUNTS}
        need(counts(counter) == formal["比較"][key]["複合確認5群"], "正式の複合確認5群と不一致")
        confirmations[key] = {"複合確認5群": counter, "短秒既知率": known_rates(counter),
            "確認成立玉": sum(row["初回複合確認"] is not None for row in rows.values()),
            "確認成立したが追加注文なし玉": sum(row["初回複合確認"] is not None and row["複合確認理由の返済注文数"] == 0 for row in rows.values()),
            "新理由の返済注文数": sum(row["複合確認理由の返済注文数"] for row in rows.values()),
            "新理由の実返済枚数": sum(row["複合確認理由の実返済枚数"] for row in rows.values())}
    pairs = {}
    for delay in (0, 1):
        a, b = f"J0G1_D{delay}", f"J1G1_D{delay}"
        row = compare(books[a], books[b])
        row["正式分解"] = {"比較": [a, b], **row["正式分解"]}
        need(row["正式分解"] == formal["出口間の同実新規分解"][f"J1対J0_D{delay}"], "正式出口分解と1円又は件数が不一致")
        need(row["全差円"] == yen(formal["比較"][b]["費用後損益円"])-yen(formal["比較"][a]["費用後損益円"]), "正式総差が不一致")
        pairs[f"J1対J0_D{delay}"] = {"比較": [a, b], **row}
    need(set(pairs) == set(formal["出口間の同実新規分解"]), "正式出口比較キーが余剰又は欠落")
    return {"会計別属性": summaries, "複合確認の観測": confirmations, "出口差比較": pairs}


def markdown(value: dict) -> str:
    """
    機能: 追加退出の救済・早切り・全参加差と当時確認状態を日本語で示す。
    引数: value(dict)は照合済みの保存事後診断。
    返り値: strはMarkdown。既存玉群の合計を未再生の別戦略利益としない。
    """
    lines = ["# 86の両気配・短秒複合退出による出口差", "",
        "固定結果後の事後診断。全66場は既使用で、少数のC0候補に基づく。入口とG1は共通で、新金融判断・新市場損益再生・閾値探索は0。J0をA、J1をBとして差はB−A。金額は往復手数料と片道5pt滑りを控除した玉全体の純額。原板・保存判断・Viewerの監査完了は別証拠。", "",
        "同実新規は場・要求時計・方向・実取得時刻・価格・枚数がすべて同じ玉。取得変更と片側参加を分ける。同じG1でも退出時刻が変わると占有と後続参加が変わり得る。保存群の足し算は、未実行の別戦略を再生した利益ではない。", "",
        "| 比較 | 同実新規 | 同実入口出口差円 | 取得変更差円 | J0のみ消失円 | J1のみ追加円 | 全差円 |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for key, row in value["出口差比較"].items():
        p = row["差寄与円"]
        lines.append(f"| {key} | {row['正式分解']['同実新規']} | {p['同実新規出口差']:,} | {p['取得変更差']:,} | {p['J0のみの消失']:,} | {p['J1のみの追加']:,} | {row['全差円']:,} |")
    lines += ["", "## 確認成立・実返済・既知率", "",
        "確認成立原行、成立した玉、新理由で受理した要求、新理由で実返済した枚数を分ける。損益符号や成立snapshotだけでは、新理由で切ったと判定しない。旧要求で全量予約済みでも成立観測は残る。", "",
        "短秒両既知率の分母はJ1の全fill後に残玉がある正常原行（全予約済みも含む）。J0は追加観測offのため0/nullであり、既知率0%とはしない。この保存入力からは、退出で消えた将来原行やJ0の反実仮想の確認率は求めない。", "",
        "| 会計 | 正常残玉原行 | 短秒両既知 | 両既知率 | 価格否定原行 | 否定時両既知率 | 成立玉 | 成立したが追加要求なし玉 | 新要求数 | 新理由実返済枚数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, row in value["複合確認の観測"].items():
        rate = row["短秒既知率"]
        r1 = "対象外" if rate["短秒両既知率"] is None else f"{rate['短秒両既知率']:.1%}"
        r2 = "分母0" if rate["価格否定時の短秒両既知率"] is None else f"{rate['価格否定時の短秒両既知率']:.1%}"
        lines.append(f"| {key} | {rate['正常残玉原行']} | {rate['短秒両既知原行']} | {r1} | {rate['価格否定原行']} | {r2} | {row['確認成立玉']} | {row['確認成立したが追加注文なし玉']} | {row['新理由の返済注文数']} | {row['新理由の実返済枚数']} |")
    for key, pair in value["出口差比較"].items():
        lines += ["", f"## {key}の同実新規", "", "変化0も含む全玉を残す。分類は同実入口群だけに適用し、同じ固定帯を持っていても取得変更群を出口効果へ合算しない。", "",
            "| 符号分類 | 玉数 | J0損益円 | J1損益円 | 差円 |", "|---|---:|---:|---:|---:|"]
        for name, row in pair["同実新規の符号分類"].items():
            lines.append(f"| {name} | {row['玉数']} | {row['A損益円']:,} | {row['B損益円']:,} | {row['差円']:,} |")
        lines += ["", "| 残玉正益状態 | 玉数 | J0損益円 | J1損益円 | 差円 |", "|---|---:|---:|---:|---:|"]
        for name, row in pair["同実新規の残玉正益状態"].items():
            lines.append(f"| {name} | {row['玉数']} | {row['A損益円']:,} | {row['B損益円']:,} | {row['差円']:,} |")
        lines += ["", "| J1の確認・実返済状態 | 玉数 | J0損益円 | J1損益円 | 差円 |", "|---|---:|---:|---:|---:|"]
        for name, row in pair["同実新規のJ1実返済状態"].items():
            lines.append(f"| {name} | {row['玉数']} | {row['A損益円']:,} | {row['B損益円']:,} | {row['差円']:,} |")
        lines += ["", "| 場・要求 | 向き/役割 | 分類 | J0円 | J1円 | 差円 | J0/J1残玉正益 | J1初回確認時刻 | 確認時正益 | 新理由実返済枚数 | 凍結Bid/Ask |", "|---|---|---|---:|---:|---:|---|---|---|---:|---|"]
        for row in pair["全実玉対比"]:
            a, b = row["J0"], row["J1"]
            role = (a if a is not None else b)["元役割"]
            time = datetime.fromtimestamp(row["要求時計"], ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
            x, y = "不参加" if a is None else f"{a['費用後損益円']:,}", "不参加" if b is None else f"{b['費用後損益円']:,}"
            first = b["初回複合確認"] if b is not None else None
            confirmation = "なし" if first is None else datetime.fromtimestamp(first["at"], ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S.%f").rstrip("0").rstrip(".")
            positive = "なし" if first is None else "後" if b["複合確認時の残玉正益"] else "前"
            flag = f"{'-' if a is None else int(a['残玉正益'])}/{'-' if b is None else int(b['残玉正益'])}"
            anchor = row["保持帯"]
            lines.append(f"| {row['場']} {time} | {'買' if row['方向'] > 0 else '売'}/{role} | {row['実入口分類']} | {x} | {y} | {row['差寄与円']:,} | {flag} | {confirmation} | {positive} | {0 if b is None else b['複合確認理由の実返済枚数']} | {anchor['hold_bid']}/{anchor['hold_ask']} |")
    lines += ["", "初回確認は保存した当原行の証拠であり、源Indexを実Indexや物理行と同じ番号とみなさない。先行するG1部分返済片へ、後で発生した確認証拠を遡って付けない。JSONには初回価格否定・短秒未知・複合確認、5群counter、実返済理由別数量/金額と固定帯出典を残す。", "",
        "全66場は選択・改善に既使用である。少数玉で観測した救済や早切りを、次の閾値・未使用期間の成績・実運用の安定利益へ外挿しない。新条件の有効性と将来の切替判別は別の検証が必要。", ""]
    return "\n".join(lines)


def artifact_sessions(formal: dict, trades: Path, grids: Path, names: list[str]) -> list[dict]:
    """
    機能: 圧縮玉診断・共有定時と正式場別metricsを、観測用の会計集合へ結ぶ。
    引数: formal(dict)、trades/grids(Path)、names(list[str])は正本・明示圧縮成果物・固定場順序。
    返り値: list[dict]は観測用投影。未収録の金融判断や内部modeを生成した値とは扱わない。
    """
    need(formal["金融内部モード"] == "S0G1" and formal["保持帯床有効"] is False and formal["複合確認有効"] == {"J0G1": False, "J1G1": True}, "結果の金融宣言が不一致")
    sessions = {name: {"session": name, "books": {}, "grid_decisions": None} for name in names}
    need(len(sessions) == len(names), "台帳場が重複")
    for row in formal["場別"]:
        name, key = row["session"], row["key"]
        need(name in sessions and key in KEYS and key not in sessions[name]["books"], "場別metricsの余剰/重複")
        need(row["mode"] == key.split("_D")[0] and row["delay"] == int(key[-1]), "場別外mode又は遅延不一致")
        sessions[name]["books"][key] = {"_集計投影": True, "session": name, "fill_delay_seconds": row["delay"],
            "metrics": row["metrics"], "lots": [], "orders": [], "closed": []}
    need(all(set(session["books"]) == set(KEYS) for session in sessions.values()), "全場4会計が揃いません")
    with gzip.open(grids, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            need(row["session"] in sessions and sessions[row["session"]]["grid_decisions"] is None, "圧縮定時の場が重複又は余剰")
            sessions[row["session"]]["grid_decisions"] = row["grid_decisions"]
    need(all(session["grid_decisions"] is not None for session in sessions.values()), "圧縮定時の場欠落")
    seen = set()
    with gzip.open(trades, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            name, key, lot = row["session"], row["key"], row["lot"]
            need(name in sessions and key in KEYS and (name, key, lot["id"]) not in seen, "圧縮玉診断の場/key/重複不整合")
            seen.add((name, key, lot["id"]))
            entries = [order for order in row["orders"] if order["kind"] == "entry"]
            need(len(entries) == 1 and entries[0] == row["entry_order"], "圧縮診断の新規注文が不一致")
            need(all(order["position_id"] == lot["id"] for order in row["orders"]) and all(piece["position_id"] == lot["id"] for piece in row["closed"]), "圧縮玉と注文/返済片の所有不一致")
            book = sessions[name]["books"][key]
            book["lots"].append(lot)
            book["orders"].extend(row["orders"])
            book["closed"].extend(row["closed"])
    return [sessions[name] for name in names]


def run(manifest: Path, result: Path, trades: Path, grids: Path, out_json: Path, out_md: Path) -> dict:
    """
    機能: 完成した86の3集計成果物と台帳を指紋で結び、新規診断を保存する。
    引数: manifest/result/trades/grids/out_json/out_md(Path)は明示した6入出力先。
    返り値: dictは保存診断。既存入力を変更せず、前後SHAを照合する。
    """
    need(not out_json.exists() and not out_md.exists() and out_json.resolve() != out_md.resolve(), "診断出力は異なる新規2ファイルが必要です")
    ledger, formal = read_json(manifest), read_json(result)
    need(formal["試行"] == 86 and formal["場数"] == len(ledger["sessions"]) == 66 and formal["全場既使用"] is True, "正式86の全66既使用場が必要です")
    before = {str(path): sha(path) for path in (manifest, result, trades, grids)}
    need(formal["入力台帳SHA256"] == before[str(manifest)], "正式台帳SHAが不一致")
    sessions = artifact_sessions(formal, trades, grids, [entry["id"] for entry in ledger["sessions"]])
    value = {"試行": 86, "診断": "固定結果後の両気配・短秒複合退出差", "確認日": "2026-11-08", "場数": 66, "全場既使用": True,
        "新金融判断": 0, "市場新売買再生": 0, "閾値探索": 0, "診断コードSHA256": sha(Path(__file__)),
        "符号分類の固定83依存SHA256": CLASSIFY_SHA, "観測入力SHA256": before,
        "観測範囲": "明示した集計3成果物の玉/注文/返済片/定時/場別metrics。内部modeは集計宣言を参照し、未収録の金融判断や元全会計fieldの再検査は行わない。原板/保存判断/Viewer完了は別証拠。",
        **diagnose(sessions, formal)}
    need(all(sha(Path(path)) == digest for path, digest in before.items()), "診断中に入力が変わりました")
    value["正式集計との不一致数"], value["入力前後変更数"] = 0, 0
    for path in (out_json, out_md):
        path.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with out_md.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(markdown(value))
    return value


def main() -> None:
    """
    機能: 6つの必須Pathから完成後の出口事後診断を実行する。
    引数: --manifest/--result/--trades/--grids/--out-json/--out-md(Path)は全て必須。
    返り値: None。成功時に比較数と入力変更0を表示する。
    """
    parser = argparse.ArgumentParser()
    for name in ("manifest", "result", "trades", "grids", "out-json", "out-md"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    value = run(args.manifest, args.result, args.trades, args.grids, args.out_json, args.out_md)
    print(json.dumps({"出力": str(args.out_json), "比較数": len(value["出口差比較"]), "不一致数": 0, "入力変更": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
