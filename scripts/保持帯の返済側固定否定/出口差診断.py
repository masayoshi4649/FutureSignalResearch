"""固定85の出口差を同実入口・取得変更・片側参加と正益前後へ事後分解する。"""

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


KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("H0G1", "H1G1"))
HOLD_REASON = "保持帯返済側1tick否定"
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
    spec = importlib.util.spec_from_file_location("固定83出口符号分類85", CLASSIFY_PATH)
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
        "保持帯取得時否定": [row for row in rows if row["保持帯取得時否定"]],
        "保持帯保護段階hit": [row for row in rows if row["保持帯hit時計"] is not None],
        "保持帯理由返済あり": [row for row in rows if row["保持帯理由の実返済枚数"] > 0]}
    return {name: totals(group) for name, group in groups.items()}


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
            active = key.startswith("H1")
            projected = book.get("_集計投影", False)
            need(book["session"] == name and book["fill_delay_seconds"] == int(key[-1]), "場又は遅延不一致")
            if projected:
                metric = book["metrics"]
                need(metric["open_quantity"] == metric["pending_entry_quantity"] == metric["reserved_exit_quantity"] == 0, "集計会計に未完結の量があります")
            else:
                need(book["mode"] == "S0G1" and book["hold_enabled"] is active and book["side_cap"] == 100, "金融内部mode/保持帯off/on/数量不一致")
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
                need(lot["hold_active"] is active, "保持帯活性がoff/onと不一致")
                reasons = defaultdict(lambda: {"返済枚数": 0, "損益円": 0})
                for piece in closed:
                    reasons[piece["reason"]]["返済枚数"] += piece["quantity"]
                    reasons[piece["reason"]]["損益円"] += yen(piece["pnl5"])
                identity = (name, at, side)
                need(identity not in output[key], "同一要求時計方向の実玉重複")
                output[key][identity] = {"実新規": (lot["entry_time"], lot["entry_price"], lot["initial_quantity"]),
                    "元役割": lot["role"], "費用後損益円": pnl, "残玉正益": lot["flag"], "初回残玉正益時計": lot["flag_time"],
                    "全玉正益": lot["whole_flag"], "初回全玉正益時計": lot["whole_flag_time"],
                    "保持帯": anchor, "保持帯活性": lot["hold_active"], "保持帯取得時否定": lot["hold_entry_breached"],
                    "保持帯hit時計": lot["hold_first_hit_at"], "保持帯hit原行": lot["hold_first_hit_line"],
                    "保持帯理由の返済注文数": sum(order["kind"] == "exit" and order["reason"] == HOLD_REASON for order in orders),
                    "保持帯理由の実返済枚数": sum(piece["quantity"] for piece in closed if piece["reason"] == HOLD_REASON),
                    "返済理由別": dict(reasons)}
            need(sum(row["費用後損益円"] for identity, row in output[key].items() if identity[0] == name) == yen(book["metrics"]["net_pnl_yen"]), "玉合計と会計総額が不一致")
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
    引数: left/right(dict)はH0/H1の要求時計別玉。
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
    all_rows = []
    for identity in sorted(left.keys() | right.keys()):
        a, b = left.get(identity), right.get(identity)
        if a is not None and b is not None:
            need(a["保持帯"] == b["保持帯"] and a["元役割"] == b["元役割"], "同一C0要求の保持帯又は役割が不一致")
        anchor = (a if a is not None else b)["保持帯"]
        delta = (b["費用後損益円"] if b is not None else 0) - (a["費用後損益円"] if a is not None else 0)
        category = "取得変更" if identity in changed else "H0のみ" if identity in only_a else "H1のみ" if identity in only_b else CLASSIFY.classify(a["費用後損益円"], b["費用後損益円"])
        if identity in exact:
            group = groups[category]
            flag_group = flags[f"A{'正益観測' if a['残玉正益'] else '未観測'}/B{'正益観測' if b['残玉正益'] else '未観測'}"]
            for group_value in (group, flag_group):
                group_value["玉数"] += 1
                group_value["A損益円"] += a["費用後損益円"]
                group_value["B損益円"] += b["費用後損益円"]
                group_value["差円"] += delta
        all_rows.append({"場": identity[0], "要求時計": identity[1], "方向": identity[2], "実入口分類": category,
            "同実新規": identity in exact, "保持帯": anchor, "H0": snapshot(a), "H1": snapshot(b), "差寄与円": delta})
    contributions = {"同実新規出口差": legacy["同実新規出口差円"],
        "取得変更差": legacy["取得変更B損益円"]-legacy["取得変更A損益円"],
        "H0のみの消失": -legacy["Aのみ損益円"], "H1のみの追加": legacy["Bのみ損益円"]}
    total = sum(row["費用後損益円"] for row in right.values()) - sum(row["費用後損益円"] for row in left.values())
    need(sum(contributions.values()) == sum(row["差寄与円"] for row in all_rows) == total, "差寄与又は全実玉表と全差が不一致")
    need(sum(row["玉数"] for row in groups.values()) == len(exact), "符号分類の漏れ")
    need(sum(row["差円"] for row in groups.values()) == sum(row["差円"] for row in flags.values()) == legacy["同実新規出口差円"], "符号/正益状態と同実入口差が不一致")
    return {"正式分解": legacy, "全差円": total, "差寄与円": contributions, "同実新規の符号分類": groups,
        "同実新規の残玉正益状態": flags, "全実玉対比": all_rows,
        "H0のみの既存額": totals([left[key] for key in only_a]), "H1のみの既存額": totals([right[key] for key in only_b])}


def diagnose(sessions: list[dict], formal: dict) -> dict:
    """
    機能: 4会計と2遅延比較を正式総額・出口間分解へ結ぶ。
    引数: sessions(list[dict])は保存会計、formal(dict)は85集計の正本。
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
    pairs = {}
    for delay in (0, 1):
        a, b = f"H0G1_D{delay}", f"H1G1_D{delay}"
        row = compare(books[a], books[b])
        row["正式分解"] = {"比較": [a, b], **row["正式分解"]}
        need(row["正式分解"] == formal["出口間の同実新規分解"][f"H1対H0_D{delay}"], "正式出口分解と1円又は件数が不一致")
        need(row["全差円"] == yen(formal["比較"][b]["費用後損益円"])-yen(formal["比較"][a]["費用後損益円"]), "正式総差が不一致")
        pairs[f"H1対H0_D{delay}"] = {"比較": [a, b], **row}
    need(set(pairs) == set(formal["出口間の同実新規分解"]), "正式出口比較キーが余剰又は欠落")
    return {"会計別属性": summaries, "出口差比較": pairs}


def markdown(value: dict) -> str:
    """
    機能: 救った損失・失った勝ちと全実玉の保持帯/正益前後をMarkdownへ写す。
    引数: value(dict)は照合済みの診断。
    返り値: strは日本語本文。未来成績で新規を判別できたとは扱わない。
    """
    lines = ["# 85の保持帯固定否定による出口差", "", "固定結果後の事後診断。全66場は既使用で、入口C0とG1は共通。新金融判断・新市場損益再生・閾値探索は0。H0をA、H1をBとして差はB−A。金額は往復手数料と片道5pt滑りを控除した玉全体の純額。原板・保存判断・Viewerの監査完了を示す資料ではない。", "",
        "同実新規は場・要求時計・方向・実新規時刻・価格・枚数が全て同じ玉。取得変更や片側参加を分け、早い返済で変わり得る後続参加を出口だけの効果へ混ぜない。", "",
        "| 比較 | 同実新規 | 同実入口出口差円 | 取得変更差円 | H0のみ消失円 | H1のみ追加円 | 全差円 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key, row in value["出口差比較"].items():
        p = row["差寄与円"]
        lines.append(f"| {key} | {row['正式分解']['同実新規']} | {p['同実新規出口差']:,} | {p['取得変更差']:,} | {p['H0のみの消失']:,} | {p['H1のみの追加']:,} | {row['全差円']:,} |")
    lines += ["", "## 同実新規の符号と増減", "", "| 比較 | 分類 | 玉数 | H0円 | H1円 | 差円 |", "|---|---|---:|---:|---:|---:|"]
    for key, row in value["出口差比較"].items():
        for name, group in row["同実新規の符号分類"].items():
            if group["玉数"]:
                lines.append(f"| {key} | {name} | {group['玉数']} | {group['A損益円']:,} | {group['B損益円']:,} | {group['差円']:,} |")
    lines += ["", "A赤字からB黒字は損失を救い黒字化した例、両赤字で損失縮小は黒字化前の軽減。A黒字からB赤字は既存の勝ちを失った例で、両赤字の拡大と区別する。この事後分類を、入口時点で将来の勝敗を識別した証明にはしない。", "",
        "## 正益前後と保持帯状態", "", "| 会計 | 全玉/円 | 正益未観測玉/円 | 正益観測後赤字玉/円 | 取得時否定玉 | 保護段階hit玉 | 保持帯理由玉 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key, groups in value["会計別属性"].items():
        total, no_profit, loss = groups["全玉"], groups["残玉正益未観測"], groups["残玉正益観測後の最終赤字"]
        lines.append(f"| {key} | {total['玉数']}/{total['損益円']:,} | {no_profit['玉数']}/{no_profit['損益円']:,} | {loss['玉数']}/{loss['損益円']:,} | {groups['保持帯取得時否定']['玉数']} | {groups['保持帯保護段階hit']['玉数']} | {groups['保持帯理由返済あり']['玉数']} |")
    lines += ["", "残玉単価の正益と、既返済片込みの全玉正益は別。属性は重なり合うため加算しない。保持帯で返済したかはclosedの保存理由から実返済枚数を数え、損益符号やhitから推定しない。返済注文数も別保存する。hitは全fill後に正常な残玉がある保護段階の記録で、全raw接触回数ではない。先行部分返済片へ最終lotのhitを遡及しない。", "",
        "## 全実玉の対比", "", "保持帯は入口時に固定した共通出典、PnL・益旗・hitは入口後の観測である。全実玉を載せ、救済例や赤字例だけへ絞らない。Pは買いhold.Bid−10／売りhold.Ask＋10。", "",
        "| 比較 | 場/要求日本時間 | 売買/元役割 | 分類 | 保持帯Bid/Ask→P | H0円/残玉正益 | H1円/残玉正益 | H1取得否定/hit/保持帯理由枚数 | 差寄与円 |", "|---|---|---|---|---|---:|---:|---|---:|"]
    for key, pair in value["出口差比較"].items():
        for row in pair["全実玉対比"]:
            a, b, anchor = row["H0"], row["H1"], row["保持帯"]
            current = a if a is not None else b
            clock = datetime.fromtimestamp(row["要求時計"], ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")
            a_text = "不参加" if a is None else f"{a['費用後損益円']:,}/{'有' if a['残玉正益'] else '未観測'}"
            b_text = "不参加" if b is None else f"{b['費用後損益円']:,}/{'有' if b['残玉正益'] else '未観測'}"
            hold_text = "不参加" if b is None else f"{'有' if b['保持帯取得時否定'] else '無'}/{'有' if b['保持帯hit時計'] is not None else '無'}/{b['保持帯理由の実返済枚数']}"
            lines.append(f"| {key} | {row['場']} {clock} | {'買' if row['方向'] > 0 else '売'}/{current['元役割']} | {row['実入口分類']} | {anchor['hold_bid']:g}/{anchor['hold_ask']:g}→{anchor['stop_price']:g} | {a_text} | {b_text} | {hold_text} | {row['差寄与円']:,} |")
    lines += ["", "全固定出典、実取得時刻/価格/枚数、初回正益時計、保持帯hit原行、返済理由別の量/額はJSONへ保存した。保持帯の源生成、原板の金融床・予約・次適格fillの検査は別監査の範囲で、この診断で再生していない。", "",
        "同じ66場と両遅延を独立標本として水増ししない。保存群の金額を足して未実行の別戦略利益と呼ばず、少数の黒字・救済例だけで安定収益や局面切替を達成したとはしない。", ""]
    return "\n".join(lines)


def artifact_sessions(formal: dict, trades: Path, grids: Path, names: list[str]) -> list[dict]:
    """
    機能: 圧縮玉診断・共有定時と正式場別metricsを、観測用の会計集合へ結ぶ。
    引数: formal(dict)、trades/grids(Path)、names(list[str])は正本・明示圧縮成果物・固定場順序。
    返り値: list[dict]は観測用投影。未収録の金融判断や内部modeを生成した値とは扱わない。
    """
    need(formal["金融内部モード"] == "S0G1" and formal["保持帯有効"] == {"H0G1": False, "H1G1": True}, "結果の金融宣言が不一致")
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
    機能: 完成した85の3集計成果物と台帳を指紋で結び、新規診断を保存する。
    引数: manifest/result/trades/grids/out_json/out_md(Path)は明示した6入出力先。
    返り値: dictは保存診断。既存入力を変更せず、前後SHAを照合する。
    """
    need(not out_json.exists() and not out_md.exists() and out_json.resolve() != out_md.resolve(), "診断出力は異なる新規2ファイルが必要です")
    ledger, formal = read_json(manifest), read_json(result)
    need(formal["試行"] == 85 and formal["場数"] == len(ledger["sessions"]) == 66 and formal["全場既使用"] is True, "正式85の全66既使用場が必要です")
    before = {str(path): sha(path) for path in (manifest, result, trades, grids)}
    need(formal["入力台帳SHA256"] == before[str(manifest)], "正式台帳SHAが不一致")
    sessions = artifact_sessions(formal, trades, grids, [entry["id"] for entry in ledger["sessions"]])
    value = {"試行": 85, "診断": "固定結果後の保持帯出口差", "確認日": "2026-11-08", "場数": 66, "全場既使用": True,
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
