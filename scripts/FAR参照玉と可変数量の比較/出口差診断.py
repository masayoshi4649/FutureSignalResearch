"""固定87のS/SC参加・取得条件・費用後損失を保存成果物だけから診断する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "scripts/保持帯喪失と短秒反対の複合退出/出口差診断.py"
BASE_SHA = "66e8fbf629352625813a56c29538b6e9b0b4a757357d96971361a9089f1f000a"
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("R0G1", "R1G1"))


def load_base() -> object:
    """
    機能: 固定86の保存読取・整数円・固定83符号分類だけを再用する。
    引数: なし。旧mainや市場データは実行しない。
    返り値: objectは停止SHA一致の純診断モジュール。
    """
    import hashlib
    if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError("固定86診断が変わりました")
    spec = importlib.util.spec_from_file_location("固定86診断87", BASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_base()
need, sha, yen, read_json = BASE.need, BASE.sha, BASE.yen, BASE.read_json


def read_lines(path: Path) -> list[dict]:
    """
    機能: 圧縮された正式小型JSON行を読む。
    引数: path(Path)は明示された圧縮成果物。
    返り値: list[dict]はJSON行。原板や未指定期間は開かない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def total(rows: list[dict]) -> dict:
    """
    機能: 保存済み玉の数量・黒赤・実純額を集約する。
    引数: rows(list[dict])は小型診断玉。
    返り値: dictは実績群の統計。未再生戦略の損益ではない。
    """
    return {"玉数": len(rows), "実新規枚数": sum(r["実新規"]["枚数"] for r in rows),
        "損益円": sum(r["損益円"] for r in rows), "黒字玉": sum(r["損益円"] > 0 for r in rows),
        "赤字玉": sum(r["損益円"] < 0 for r in rows), "同値玉": sum(r["損益円"] == 0 for r in rows)}


def small_state(read: dict) -> str:
    """
    機能: 元小量規則の対象外・未知・既知適格/不適格を区別する。
    引数: read(dict)は要求時ReadLotの正本。
    返り値: strは源規則の保存状態。現在量から資格を補完しない。
    """
    if not read["small_initial_rule_applicable"]:
        need(not read["native_small_initial_known"] and read["native_small_initial_eligible"] is None, "対象外小量資格の捏造")
        return "対象外"
    if not read["native_small_initial_known"]:
        need(read["native_small_initial_eligible"] is None, "未知小量資格の値補完")
        return "未知"
    need(type(read["native_small_initial_eligible"]) is bool, "既知小量資格の型不正")
    return "既知適格" if read["native_small_initial_eligible"] else "既知不適格"


def entry_d02(lot: dict, order: dict) -> dict:
    """
    機能: 実新規と要求時の参照価格・時計・数量を結ぶD02観測を作る。
    引数: lot/order(dict)は完結玉と唯一の実新規注文。
    返り値: dictは二つのSource時計と価格差・元量。事後gateは作らない。
    """
    binding = lot["source_entry"]
    need(binding is not None and binding == order["source_entry"], "SourceEntryが注文と玉で不一致")
    read, reference = binding["read_lot"], binding["read_lot"]["reference"]
    quantity, requested, current = lot["initial_quantity"], binding["requested_quantity"], reference["quantity"]
    need(reference["id"] == lot["reference_id"] == order["reference_id"] and reference["side"] == lot["side"], "参照ID/方向の不一致")
    need(reference["method"] == binding["snapshot_method"] and reference["kind"] == binding["reference_kind"] == lot["role"], "元手法/選定参照Kindを上書きしました")
    need(1 <= quantity <= requested <= current <= read["reference_initial_quantity"] and current <= 100, "要求/実取得/参照現在・初期量が不一致")
    need(order["quantity"] == requested and order["filled_quantity"] == quantity, "可変量注文の要求とfillが不一致")
    need(order["fill_time"] == lot["entry_time"] and order["fill_price"] == lot["entry_price"], "取得時刻/価格と注文が不一致")
    need(reference["at"] <= binding["snapshot_at"] <= order["request_time"] <= lot["entry_time"], "D02の参照/要求/取得時計が不正")
    need(lot["real_entry_stage"] == "実初参加" and order["real_entry_stage"] == "初参加要求", "要求と実初参加を混同しました")
    for value, known in (("native_parent_initial_micro", "native_parent_initial_known"), ("native_parent_original_desired", "native_parent_original_desired_known")):
        need(read[known] is (read[value] is not None), "元親量の既知とnullable値が不一致")
    gap = lot["entry_price"]-reference["entry"]
    return {"元手法": reference["method"], "選定参照Kind": reference["kind"], "元小量資格": small_state(read),
        "参照取得時刻": reference["at"], "Source観測時刻": binding["snapshot_at"],
        "参照取得から要求秒": order["request_time"]-reference["at"], "Source観測から要求秒": order["request_time"]-binding["snapshot_at"],
        "要求から実取得秒": lot["entry_time"]-order["request_time"], "参照Entry": reference["entry"],
        "実Entryとの差pt": gap, "方向付き実Entryとの差pt": lot["side"]*gap,
        "参照現在量": current, "参照初期量": read["reference_initial_quantity"], "元親初回量": read["native_parent_initial_micro"],
        "元親初回既知": read["native_parent_initial_known"], "元親初回理由": read["native_parent_initial_reason"],
        "元親初回希望量": read["native_parent_original_desired"], "元親希望量適用": read["native_parent_original_desired_applicable"],
        "元親希望量既知": read["native_parent_original_desired_known"], "元親希望量理由": read["native_parent_original_desired_reason"],
        "元小量資格理由": read["native_small_initial_reason"], "実要求量": requested, "実初期量": quantity,
        "SourceID": reference["source_id"], "Parent": reference["parent"], "参照内部ID": reference["internal_id"]}


def protection(lot: dict, orders: list[dict], pieces: list[dict], effects: list[dict]) -> dict:
    """
    機能: 保存された初回正益・Source予約・部分fillだけからG1の限界時点を観測する。
    引数: lot(dict)、orders/pieces/effects(list[dict])は同所有の保存記録。
    返り値: dictは観測時点と返済片属性。未保存の全原行件数を推定しない。
    """
    source_orders = {o["id"]: o for o in orders if o["kind"] == "exit" and o["reason"].startswith("参照返済:")}
    flag_source = []
    if lot["flag"]:
        for effect in effects:
            if effect["origin"] == "quote" and effect["quote_index"] == lot["flag_index"] and effect["exit_requested"] > 0:
                order = source_orders.get(effect["exit_order_id"])
                need(order is not None and order["request_index"] == lot["flag_index"], "初回flagのSource予約注文が不一致")
                new_harvest = [o for o in orders if o["harvest"] and o["request_index"] == lot["flag_index"]]
                need(not new_harvest, "初回flagのSource予約中に収穫要求が存在")
                flag_source.append({"時刻": effect["at"], "原行Index": effect["quote_index"], "物理行": effect["quote_line"],
                    "Source予約枚数": effect["exit_requested"], "Source要求時単価純額円": order["net_per_unit"], "同原行新収穫要求数": 0})
    # ----------------------------------------
    # fillの同原行全片を一度まとめて残量を出し、後のfloorを過去へ付けません。
    grouped = defaultdict(list)
    for piece in pieces:
        grouped[(piece["exit_time"], piece["exit_line"])].append(piece)
    closed_quantity, nonpositive = 0, []
    for (at, line), group in sorted(grouped.items()):
        closed_quantity += sum(p["quantity"] for p in group)
        residual = lot["initial_quantity"]-closed_quantity
        source_piece = [p for p in group if p["reason"].startswith("参照返済:") and p["flag"]]
        if residual <= 0 or not source_piece:
            continue
        price = group[0]["exit_price"]
        need(all(p["exit_price"] == price for p in group), "同原行の返済側価格が不一致")
        unit = lot["side"]*(price-lot["entry_price"])*10-122
        if unit <= 0:
            new_harvest = [o for o in orders if o["harvest"] and o["request_time"] == at and o["request_line"] == line]
            need(not new_harvest, "現在単価純額非正で新収穫要求")
            nonpositive.append({"時刻": at, "物理行": line, "Source実返済枚数": sum(p["quantity"] for p in source_piece),
                "全fill後残量": residual, "返済側価格": price, "残玉現在単価純額円": unit, "同原行新収穫要求数": 0})
    adverse = [yen(p["request_to_fill_adverse_yen"]) for p in pieces if p["request_to_fill_adverse_yen"] is not None]
    return {"G1起動": lot["flag"], "初回G1時刻": lot["flag_time"], "全玉正益": lot["whole_flag"],
        "初回G1と同原行Source予約": flag_source, "Source部分fill後の単価非正観測": nonpositive,
        "次板不利変動円": sum(max(v, 0) for v in adverse), "次板改善円": sum(min(v, 0) for v in adverse),
        "要求値不明の返済片数": sum(p["request_to_fill_adverse_yen"] is None for p in pieces),
        "費用で赤字の正幅返済片数": sum(p["cost_loss"] for p in pieces), "名目同値返済片数": sum(p["nominal_flat"] for p in pieces),
        "要求時既に床未満の返済片数": sum(p["floor_jump"] for p in pieces),
        "起動前返済片の損益円": sum(yen(p["pnl5"]) for p in pieces if not p["flag"]),
        "起動後返済片の損益円": sum(yen(p["pnl5"]) for p in pieces if p["flag"])}


def load_artifacts(formal: dict, diagnostics: Path, decisions: Path, source_decisions: Path) -> tuple[list[dict], dict, dict]:
    """
    機能: 正式集計の場別metrics・圧縮玉・共有定時・Source判断を結合する。
    引数: formal(dict)、diagnostics/decisions/source_decisions(Path)は明示成果物。
    返り値: tupleは玉行・共有場map・会計別判断map。未保存の原行は補完しない。
    """
    names = list(dict.fromkeys(row["session"] for row in formal["場別"]))
    shared = {row["session"]: row for row in read_lines(decisions)}
    source_rows = read_lines(source_decisions)
    source = {row["session"]: row["books"] for row in source_rows}
    need(len(shared) == len(names) == len(source_rows) == len(source) and set(shared) == set(source) == set(names), "成果物の場集合が不一致")
    for name in names:
        need(set(source[name]) == set(KEYS), "Source判断の4会計が不一致")
        shared[name]["grid_map"] = {row["at"]: row for row in shared[name]["grid_decisions"]}
        need(len(shared[name]["grid_map"]) == len(shared[name]["grid_decisions"]), "共有定時の重複")
        for key in KEYS:
            book = source[name][key]
            need(book["source_policy"] == ("S" if key.startswith("R0") else "SC"), "Source政策が不一致")
            book["decision_map"] = {row["at"]: row for row in book["decisions"]}
            need(len(book["decision_map"]) == len(book["decisions"]) and set(book["decision_map"]) == set(shared[name]["grid_map"]), "金融/共有定時集合が不一致")
    return read_lines(diagnostics), shared, source


def collect(diags: list[dict], shared: dict, source: dict) -> dict:
    """
    機能: 全実玉をSourceEntry・当時pool・選択判断・実返済へ結ぶ。
    引数: diags(list[dict])、shared/source(dict)は明示成果物からの保存値。
    返り値: dictは会計別の全玉。gzのlot/orders/closed全文は再保存しない。
    """
    output, seen = {key: [] for key in KEYS}, set()
    for saved in diags:
        name, key, lot = saved["session"], saved["key"], saved["lot"]
        need(name in shared and key in KEYS, "玉の場/会計が不正")
        orders, pieces, entry = saved["orders"], saved["closed"], saved["entry_order"]
        need([o for o in orders if o["kind"] == "entry"] == [entry], "新規注文が唯一でない又は不一致")
        need(lot["quantity"] == 0 and all(o["position_id"] == lot["id"] for o in orders) and all(p["position_id"] == lot["id"] for p in pieces), "所有又は完結量が不一致")
        identity = (name, lot["reference_id"])
        need((key, identity) not in seen, "同参照IDへの実再参加が重複")
        seen.add((key, identity))
        d02 = entry_d02(lot, entry)
        binding, reference = lot["source_entry"], lot["source_entry"]["read_lot"]["reference"]
        policy = "S" if key.startswith("R0") else "SC"
        need(binding["policy"] == policy and binding["c0_used"] is (policy == "SC"), "SourceEntry政策不一致")
        need(all(o["source_entry"] == binding for o in orders) and all(p["source_entry"] == binding for p in pieces), "不変SourceEntryの継承が不一致")
        grid = shared[name]["grid_map"].get(entry["request_time"])
        need(grid is not None and grid["clock_allowed"], "実新規の共有定時又は時計許可が欠落")
        pool = [row for row in grid["source"]["lots"] if row["reference"]["id"] == lot["reference_id"]]
        need(pool == [binding["read_lot"]] and not reference["closing"], "要求時参照全poolとの結合不一致")
        need(binding["snapshot_at"] == grid["source"]["at"] and binding["snapshot_index"] == grid["source"]["source_index"], "要求時Source時計不一致")
        actual = source[name][key]["decision_map"][entry["request_time"]]
        candidate = [c for c in actual["candidates"] if c["reference_id"] == lot["reference_id"]]
        need(len(candidate) == 1 and candidate[0]["requested_quantity"] == entry["quantity"] and candidate[0]["source_check"]["selected"] and actual["source_context"]["selected_id"] == lot["reference_id"], "保存選定と注文の不一致")
        if policy == "SC":
            need(grid["c0"]["allowed"] and grid["c0"]["side"] == lot["side"] and binding["c0_allowed"] and binding["c0_side"] == lot["side"], "SC最終C0と実方向不一致")
        quantity, pnl = lot["initial_quantity"], yen(lot["net_pnl"])
        need(sum(p["quantity"] for p in pieces) == quantity and sum(yen(p["pnl5"]) for p in pieces) == pnl, "返済枚数又は玉純額の不一致")
        gross = sum(yen(p["gross_pnl"]) for p in pieces)
        cost = sum(yen(p["commission"]+p["slippage"]) for p in pieces)
        need(cost == 122*quantity and gross-cost == pnl, "可変量の費用会計が不一致")
        effects = [e for e in source[name][key]["source_effects"] if e["reference_id"] == lot["reference_id"] and e["at"] >= entry["request_time"]]
        order_map = {o["id"]: o for o in orders}
        for effect in effects:
            if effect["exit_requested"]:
                order = order_map.get(effect["exit_order_id"])
                need(order is not None and order["quantity"] == effect["exit_requested"] and order["request_time"] == effect["at"], "Source作用と実注文の結合不一致")
        reasons = defaultdict(lambda: {"枚数": 0, "損益円": 0})
        for piece in pieces:
            reasons[piece["reason"]]["枚数"] += piece["quantity"]
            reasons[piece["reason"]]["損益円"] += yen(piece["pnl5"])
        output[key].append({"場": name, "参照ID": lot["reference_id"], "実玉ID": lot["id"], "要求時刻": entry["request_time"], "方向": lot["side"],
            "実新規": {"時刻": lot["entry_time"], "価格": lot["entry_price"], "枚数": quantity}, "損益円": pnl, "費用前損益円": gross, "往復費用円": cost,
            "D02": d02, "G1": protection(lot, orders, pieces, effects), "返済理由別": dict(reasons),
            "Source実返済枚数": sum(p["quantity"] for p in pieces if p["reason"].startswith("参照返済:")),
            "G1収穫実返済枚数": sum(p["quantity"] for p in pieces if p["harvest"])})
    for key in KEYS:
        output[key].sort(key=lambda r: (r["場"], r["要求時刻"], r["参照ID"], r["方向"]))
    return output


def identity(row: dict) -> tuple:
    """
    機能: 正式87の第一層として、場と参照IDのidentityを作る。
    引数: row(dict)は小型実玉。
    返り値: tupleは場・参照ID。要求/方向/取得差は第二層で比較する。
    """
    return row["場"], row["参照ID"]


def counterpart(row: dict, key: str, source: dict) -> dict:
    """
    機能: 片側参加の相手候補の当時状態を保存判断から読む。
    引数: row(dict)、key(str)、source(dict)は実玉・相手会計・保存判断。
    返り値: dictは占有/seen/C0/選定と理由。後の損益を入口判別へ使わない。
    """
    decision = source[row["場"]][key]["decision_map"][row["要求時刻"]]
    candidates = [c for c in decision["candidates"] if c["reference_id"] == row["参照ID"]]
    need(len(candidates) <= 1, "相手参照候補の重複")
    return {"判断": decision["action"], "占有": decision["source_context"]["occupied"],
        "候補": candidates[0] if candidates else None, "理由": decision["reason"]}


def compare(a_rows: list[dict], b_rows: list[dict], source: dict, delay: int) -> dict:
    """
    機能: 同実新規の差と取得変更/片側参加を正式4寄与へ完全分解する。
    引数: a_rows/b_rows(list[dict])、source(dict)、delay(int)はS/SC実績と保存判断。
    返り値: dictは全対比の行参照・符号分類・片側の勝敗別実績。
    """
    a, b = {identity(r): r for r in a_rows}, {identity(r): r for r in b_rows}
    need(len(a) == len(a_rows) and len(b) == len(b_rows), "比較identityの重複")
    common = a.keys() & b.keys()
    exact = {k for k in common if a[k]["要求時刻"] == b[k]["要求時刻"] and a[k]["方向"] == b[k]["方向"] and a[k]["実新規"] == b[k]["実新規"]}
    changed, only_a, only_b = common-exact, a.keys()-b.keys(), b.keys()-a.keys()
    sums = lambda rows, keys: sum(rows[k]["損益円"] for k in keys)
    legacy = {"比較": [f"R0G1_D{delay}", f"R1G1_D{delay}"], "同参照ID": len(common), "同実新規": len(exact),
        "同実新規A損益円": sums(a, exact), "同実新規B損益円": sums(b, exact), "同実新規出口差円": sums(b, exact)-sums(a, exact),
        "共通だが取得変更": len(changed), "取得変更A損益円": sums(a, changed), "取得変更B損益円": sums(b, changed),
        "Aのみ": len(only_a), "Bのみ": len(only_b), "Aのみ損益円": sums(a, only_a), "Bのみ損益円": sums(b, only_b)}
    groups = {name: {"玉数": 0, "S損益円": 0, "SC損益円": 0, "差円": 0} for name in BASE.CLASSIFY.CATEGORIES}
    changed_groups = {name: {"玉数": 0, "S損益円": 0, "SC損益円": 0, "差円": 0} for name in BASE.CLASSIFY.CATEGORIES}
    pairs, a_only, b_only = [], [], []
    index_a, index_b = {identity(r): i for i, r in enumerate(a_rows)}, {identity(r): i for i, r in enumerate(b_rows)}
    for k in sorted(a.keys() | b.keys()):
        x, y = a.get(k), b.get(k)
        delta = (y["損益円"] if y is not None else 0)-(x["損益円"] if x is not None else 0)
        category = BASE.CLASSIFY.classify(x["損益円"], y["損益円"]) if k in exact else "取得変更" if k in changed else "Sのみ" if k in only_a else "SCのみ"
        sign = BASE.CLASSIFY.classify(x["損益円"], y["損益円"]) if k in common else None
        if k in common:
            group = (groups if k in exact else changed_groups)[sign]
            group["玉数"] += 1
            group["S損益円"] += x["損益円"]
            group["SC損益円"] += y["損益円"]
            group["差円"] += delta
        if k in only_a:
            a_only.append({"S行": index_a[k], "既存損益円": x["損益円"], "相手状態": counterpart(x, f"R1G1_D{delay}", source)})
        if k in only_b:
            b_only.append({"SC行": index_b[k], "既存損益円": y["損益円"], "相手状態": counterpart(y, f"R0G1_D{delay}", source)})
        pairs.append({"S行": index_a.get(k), "SC行": index_b.get(k), "分類": category, "符号分類": sign, "同実新規": k in exact, "差寄与円": delta,
            "SC要求の遅れ秒": y["要求時刻"]-x["要求時刻"] if k in common else None,
            "方向付きSC取得価格差pt": x["方向"]*(y["実新規"]["価格"]-x["実新規"]["価格"]) if k in common and x["方向"] == y["方向"] else None,
            "SC実量差": y["実新規"]["枚数"]-x["実新規"]["枚数"] if k in common else None})
    contribution = {"同実新規出口差": legacy["同実新規出口差円"], "取得変更差": legacy["取得変更B損益円"]-legacy["取得変更A損益円"],
        "Sのみの消失": -legacy["Aのみ損益円"], "SCのみの追加": legacy["Bのみ損益円"]}
    total_delta = sum(r["損益円"] for r in b_rows)-sum(r["損益円"] for r in a_rows)
    need(sum(contribution.values()) == sum(r["差寄与円"] for r in pairs) == total_delta, "4寄与と全差が不一致")
    need(sum(g["差円"] for g in groups.values()) == legacy["同実新規出口差円"] and sum(g["玉数"] for g in groups.values()) == len(exact), "同実新規の符号分解漏れ")
    need(sum(g["差円"] for g in changed_groups.values()) == contribution["取得変更差"] and sum(g["玉数"] for g in changed_groups.values()) == len(changed), "取得変更の符号分解漏れ")
    return {"正式分解": legacy, "差寄与円": contribution, "全差円": total_delta, "同実新規の符号分類": groups,
        "取得変更の符号分類": changed_groups,
        "全対比行参照": pairs, "Sのみ": a_only, "SCのみ": b_only,
        "SC不参加で失ったS黒字": total([a[k] for k in only_a if a[k]["損益円"] > 0]),
        "SC不参加で除いたS赤字": total([a[k] for k in only_a if a[k]["損益円"] < 0])}


def statistics(values: list[int | float]) -> dict:
    """
    機能: D02観測値の件数・最小・最大・平均だけを示す。
    引数: values(list[int|float])は固定実績からの観測。
    返り値: dictは記述統計。成績閾値・将来gateは探索しない。
    """
    return {"件数": len(values), "最小": min(values) if values else None, "最大": max(values) if values else None,
        "平均": sum(values)/len(values) if values else None}


def diagnose(formal: dict, diags: list[dict], shared: dict, source: dict) -> dict:
    """
    機能: 全玉・D02・因果属性とS/SC差を正式集計へ結ぶ。
    引数: formal(dict)、diags(list[dict])、shared/source(dict)は保存正本群。
    返り値: dictは重複全文を含まない小型診断。
    """
    books = collect(diags, shared, source)
    need(set(formal["比較"]) == set(KEYS), "正式4比較が不一致")
    metrics = {(r["session"], r["key"]): r["metrics"] for r in formal["場別"]}
    need(len(metrics) == len(formal["場別"]) == len(shared)*4, "場別metricsの重複/欠落")
    summaries, d02 = {}, {}
    for key, rows in books.items():
        old = formal["比較"][key]
        need(len(rows) == old["完結玉"] and sum(r["損益円"] for r in rows) == yen(old["費用後損益円"]), "正式完結玉/純額と不一致")
        need(sum(r["損益円"] for r in rows if not r["G1"]["G1起動"]) == yen(old["正益未観測の損益円"]), "G1起動前総額不一致")
        need(sum(r["損益円"] for r in rows if r["G1"]["G1起動"]) == yen(old["正益観測の損益円"]), "G1起動後総額不一致")
        need(sum(r["G1"]["全玉正益"] and r["損益円"] < 0 for r in rows) == old["全玉旗後赤字"], "全玉旗後赤字不一致")
        for name in shared:
            chosen = [r for r in rows if r["場"] == name]
            metric = metrics[name, key]
            need(sum(r["損益円"] for r in chosen) == yen(metric["net_pnl_yen"]) and sum(r["実新規"]["枚数"] for r in chosen) == metric["entry_quantity"], "場別実量/損益不一致")
            need(metric["open_quantity"] == metric["pending_entry_quantity"] == metric["reserved_exit_quantity"] == 0, "未完結金融を診断できません")
        groups = {}
        for dimension in ("元手法", "選定参照Kind", "元小量資格", "実初期量"):
            labels = {str(r["D02"][dimension]) for r in rows}
            groups[dimension] = {label: total([r for r in rows if str(r["D02"][dimension]) == label]) for label in sorted(labels)}
            need(sum(g["損益円"] for g in groups[dimension].values()) == old["費用後損益円"], "元属性別の損益合計漏れ")
        summaries[key] = {"全玉": total(rows), "G1起動前赤字": total([r for r in rows if not r["G1"]["G1起動"] and r["損益円"] < 0]),
            "G1起動後赤字": total([r for r in rows if r["G1"]["G1起動"] and r["損益円"] < 0]), "元属性別": groups,
            "初回G1同原行Source予約の観測時点数": sum(len(r["G1"]["初回G1と同原行Source予約"]) for r in rows),
            "Source部分fill後unit非正の観測時点数": sum(len(r["G1"]["Source部分fill後の単価非正観測"]) for r in rows),
            "次板不利変動円": sum(r["G1"]["次板不利変動円"] for r in rows),
            "要求値不明の返済片数": sum(r["G1"]["要求値不明の返済片数"] for r in rows),
            "費用で赤字の正幅返済片数": sum(r["G1"]["費用で赤字の正幅返済片数"] for r in rows),
            "名目同値返済片数": sum(r["G1"]["名目同値返済片数"] for r in rows)}
        d02[key] = {field: statistics([r["D02"][field] for r in rows]) for field in
            ("参照取得から要求秒", "Source観測から要求秒", "要求から実取得秒", "方向付き実Entryとの差pt", "参照現在量", "参照初期量", "実要求量", "実初期量")}
    comparisons = {}
    for delay in (0, 1):
        key = f"SC対S_D{delay}"
        row = compare(books[f"R0G1_D{delay}"], books[f"R1G1_D{delay}"], source, delay)
        need(row["正式分解"] == formal["出口間の同実新規分解"][key], "正式SC対S分解と不一致")
        comparisons[key] = row
    need(set(comparisons) == set(formal["出口間の同実新規分解"]), "正式分解の余剰/欠落")
    examples = []
    for key, rows in books.items():
        red = sorted(enumerate(rows), key=lambda v: (v[1]["損益円"], v[1]["場"], v[1]["要求時刻"]))
        if red and red[0][1]["損益円"] < 0:
            i, row = red[0]
            examples.append({"会計": key, "全玉行": i, "表示理由": "同会計の最悪実玉（表示用事後抽出）", "損益円": row["損益円"]})
    return {"比較": comparisons, "会計集計": summaries, "全玉": books, "D02": d02, "代表反例": examples}


def markdown(value: dict) -> str:
    """
    機能: 正式差・群集計・代表反例を簡潔に示し、全玉正本の転記を避ける。
    引数: value(dict)は正式集計へ照合した診断。
    返り値: strは閲覧補足。全玉の必要観測値はJSONへ保持する。
    """
    lines = ["# 87のSource基礎とC0追加の事後診断", "",
        "全66場は既使用。SとSCは同じG1とSource返済を使い、SCだけC0最終許可を追加する。数量、参照の生存、占有、要求時計を分けて読む。新金融判断・新市場生成・事後閾値gateは0。原板/G1・Source・保存・Viewerの独立監査完了を本資料では宣言しない。", "",
        "| 比較 | 同実新規 | 同実出口差円 | 取得変更差円 | Sのみ消失円 | SCのみ追加円 | 全差円 |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for key, row in value["比較"].items():
        c = row["差寄与円"]
        lines.append(f"| {key} | {row['正式分解']['同実新規']} | {c['同実新規出口差']:,} | {c['取得変更差']:,} | {c['Sのみの消失']:,} | {c['SCのみの追加']:,} | {row['全差円']:,} |")
    lines += ["", "| 共同参照の取得変更 | S行/SC行 | SC要求遅れ秒 | 方向付きSC取得差pt | SC実量差 | S純額円 | SC純額円 | 差円 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for key, row in value["比較"].items():
        left, right = row["正式分解"]["比較"]
        for pair in row["全対比行参照"]:
            if pair["分類"] != "取得変更":
                continue
            a, b = value["全玉"][left][pair["S行"]], value["全玉"][right][pair["SC行"]]
            lines.append(f"| {key} {a['場']} | {pair['S行']}/{pair['SC行']} | {pair['SC要求の遅れ秒']} | {pair['方向付きSC取得価格差pt']} | {pair['SC実量差']} | {a['損益円']:,} | {b['損益円']:,} | {pair['差寄与円']:,} |")
    lines += ["", "第一層はsession/reference_idの共通参照。同じ参照への遅い要求を片側参加と呼ばず取得変更へ分ける。第二層でrequest_time/sideと実Entry時刻・価格・枚数がすべて一致する場合だけ同実新規とする。別参照IDや取得変更を純出口差に混ぜない。Sのみ群の黒字喪失・赤字除外にはC0拒否に加え占有やseenも関係し得る。JSONに相手の当時候補理由を残す。保存群の合計を未再生戦略の利益と呼ばない。", "",
        "| 会計 | 玉数 | 実枚数 | 純額円 | G1前赤字玉/円 | G1後赤字玉/円 | 初回flag同原行Source予約 | Source部分fill後unit非正 |", "|---|---:|---:|---:|---|---|---:|---:|"]
    for key, row in value["会計集計"].items():
        all_rows, before, after = row["全玉"], row["G1起動前赤字"], row["G1起動後赤字"]
        lines.append(f"| {key} | {all_rows['玉数']} | {all_rows['実新規枚数']} | {all_rows['損益円']:,} | {before['玉数']}/{before['損益円']:,} | {after['玉数']}/{after['損益円']:,} | {row['初回G1同原行Source予約の観測時点数']} | {row['Source部分fill後unit非正の観測時点数']} |")
    for key, row in value["会計集計"].items():
        lines += ["", f"## {key}の元属性", "", "各分類軸は重複するため、異なる軸の玉数/損益を足さない。小量資格は元親初回量と選定参照Kindの保存値であり、現在残量の小ささから補完しない。", "",
            "| 軸 | 値 | 玉数 | 実枚数 | 純額円 |", "|---|---|---:|---:|---:|"]
        for dimension, groups in row["元属性別"].items():
            for label, item in groups.items():
                lines.append(f"| {dimension} | {label} | {item['玉数']} | {item['実新規枚数']} | {item['損益円']:,} |")
    lines += ["", "## D02の取得条件", "",
        "参照取得から要求はreference.At基準の生存時間、Source観測から要求はsnapshot_at基準の鮮度。方向付き価格差はside×(実Entry−参照Entry)で、正なら参照より不利な取得。参照の費用0成績を実側へ移さず、実要求量とSource取消後の実初期量も分ける。", "",
        "| 会計 | 観測 | 件数 | 最小 | 最大 | 平均 |", "|---|---|---:|---:|---:|---:|"]
    for key, fields in value["D02"].items():
        for field, row in fields.items():
            cells = ["-" if row[n] is None else f"{row[n]:.3f}" for n in ("最小", "最大", "平均")]
            lines.append(f"| {key} | {field} | {row['件数']} | {' | '.join(cells)} |")
    lines += ["", "## 代表反例", "", "各会計の最悪玉を表示用に一つ選ぶ。将来の入口判別や閾値選択には使っていない。全玉のID・D02・損益・因果属性は診断JSON、lot/orders/closedの正本全文はSHAで結んだ圧縮成果物を参照する。", "",
        "| 会計/JSON行 | 場/方向 | 参照age秒 | 方向付きEntry差pt | 元段階/量 | 純額円 | G1 |", "|---|---|---:|---:|---|---:|---|"]
    for e in value["代表反例"]:
        row = value["全玉"][e["会計"]][e["全玉行"]]
        d = row["D02"]
        lines.append(f"| {e['会計']}/{e['全玉行']} | {row['場']}/{'買' if row['方向'] > 0 else '売'} | {d['参照取得から要求秒']} | {d['方向付き実Entryとの差pt']} | {d['選定参照Kind']}/{d['実初期量']} | {row['損益円']:,} | {'後' if row['G1']['G1起動'] else '前'} |")
    lines += ["", "## 読み取れる範囲", ""]
    lines += [f"- {line}" for line in value["限界"]]
    return "\n".join(lines)+"\n"


def run(result: Path, diagnostics: Path, decisions: Path, source_decisions: Path, out_json: Path, out_md: Path) -> dict:
    """
    機能: 明示された87集計4成果物だけから小型事後診断を新規保存する。
    引数: result/diagnostics/decisions/source_decisions/out_json/out_md(Path)は全て必須。
    返り値: dictは成功診断。入力の前後SHAが変われば保存しない。
    """
    need(not out_json.exists() and not out_md.exists() and out_json.resolve() != out_md.resolve(), "出力は異なる新規2ファイルが必要")
    inputs = {name: str(path) for name, path in (("result", result), ("diagnostics", diagnostics), ("decisions", decisions), ("source_decisions", source_decisions))}
    before = {path: sha(Path(path)) for path in inputs.values()}
    formal = read_json(result)
    need(formal["試行"] == 87 and formal["場数"] == 66 and formal["全場既使用"] is True, "87の全66既使用場が必要")
    need(formal["金融内部モード"] == "S0G1" and formal["保持帯床有効"] is False and formal["Source入口"] == {"R0G1": "S", "R1G1": "SC"}, "Source金融宣言不一致")
    diags, shared, source = load_artifacts(formal, diagnostics, decisions, source_decisions)
    need(len(shared) == 66, "正式66場が揃いません")
    value = {"試行": 87, "成功": True, "入力": inputs, "入力SHA256": before, "診断コードSHA256": sha(Path(__file__)),
        "固定86診断SHA256": BASE_SHA, "全場既使用": True, "新金融判断": 0, "新市場生成": 0, "閾値探索": 0,
        "限界": ["全66場は既使用。SCの少数玉や群合計を未使用期間の安定収益としない。",
            "SourceとG1は共通でも、C0による選択・占有・seen・要求時計の変更を分ける。同実取得の費用後差だけを純出口差と呼ぶ。",
            "初回flagと同原行Source予約は保存効果/注文が揃う時点だけ観測する。技法失敗など他予約との排他原因は全原行監査へ委ねる。",
            "unit非正はSource部分fill後に残玉がある保存時点だけ観測する。保存されない全原行の未知率・延期件数を推定しない。",
            "G1のflag後もSource予約や現在unit非正で収穫が出ない場合がある。建値床や要求は次板の実約定価格・費用後黒字を保証しない。",
            "次板不利変動、費用で赤字の正幅、名目同値は重なり得る。保存floor_jumpは要求時gain<floorであり次板悪化と同義ではない。",
            "JSON全玉は必要観測値のみで、lot/orders/closed全文は入力gzを正本とする。原板/Source/G1/Viewer監査完了は別証拠。"],
        **diagnose(formal, diags, shared, source)}
    need(all(sha(Path(path)) == digest for path, digest in before.items()), "診断中に入力が変更されました")
    value["正式集計差"], value["入力前後変更"] = 0, 0
    for path in (out_json, out_md):
        path.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    with out_md.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(markdown(value))
    return value


def main() -> None:
    """
    機能: 4明示入力と2新規出力から87の保存読取診断を実行する。
    引数: --result/--diagnostics/--decisions/--source-decisions/--out-json/--out-mdは必須Path。
    返り値: None。成功時は比較数と入力不変を表示する。
    """
    parser = argparse.ArgumentParser()
    for name in ("result", "diagnostics", "decisions", "source-decisions", "out-json", "out-md"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    value = run(args.result, args.diagnostics, args.decisions, args.source_decisions, args.out_json, args.out_md)
    print(json.dumps({"比較数": len(value["比較"]), "全玉": {key: len(rows) for key, rows in value["全玉"].items()}, "入力変更": 0, "出力": str(args.out_json)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
