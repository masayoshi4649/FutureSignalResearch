"""固定84の保存会計から、純入口選別と占有等の実参加差を事後に分ける。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import statistics


POLICIES = ("A0", "C0", "C1")
KEYS = tuple(f"{policy}G1_D{delay}" for delay in (0, 1) for policy in POLICIES)
PAIRS = (("C0対A0", "A0G1", "C0G1"), ("C1対A0", "A0G1", "C1G1"), ("C1対C0", "C0G1", "C1G1"))
ROLES = ("順行", "転換初動")


def sha(path: Path) -> str:
    """
    機能: 保存結果・条件参照・診断コードの全byte指紋を計算する。
    引数: path(Path)は実ファイル。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def need(condition: bool, message: str) -> None:
    """
    機能: 実行最適化に左右されず診断の必要条件を検査する。
    引数: condition(bool)は成立条件、message(str)は失敗理由。
    返り値: None。不成立ならValueError。
    """
    if not condition:
        raise ValueError(message)


def yen(value: int | float) -> int:
    """
    機能: 費用後会計を整数円として丸めずに検査する。
    引数: value(int|float)は保存金額。
    返り値: intは同じ円額。bool・端数・非有限値は拒否。
    """
    need(type(value) in (int, float) and math.isfinite(value) and value == int(value), "金額が整数円ではありません")
    return int(value)


def boolean(value: object, label: str) -> bool:
    """
    機能: 未知又は0をboolへ暗黙変換しないよう型を検査する。
    引数: value(object)は保存値、label(str)は検査箇所。
    返り値: boolは同じ真偽値。
    """
    need(type(value) is bool, f"真偽値の型不整合:{label}")
    return value


def read_json(path: Path) -> dict:
    """
    機能: 非有限定数を拒否して保存JSONを読む。
    引数: path(Path)は保存先。
    返り値: dictはJSON object。
    """
    def reject(value: str) -> None:
        """
        機能: JSON外のNaN/Infinity定数を拒否する。
        引数: value(str)は不正定数。
        返り値: None。常にValueError。
        """
        raise ValueError(f"非有限JSON定数:{value}")

    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject)
    need(isinstance(value, dict), "JSONのルートはobjectが必要です")
    return value


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 既存完結玉群の金額分布と黒赤を集計する。
    引数: rows(list[dict])は費用後損益円を持つ小型玉情報。
    返り値: dictは件数・合計・黒赤・最小/中央値/最大/平均。未実行戦略の損益ではない。
    """
    values = [yen(row["費用後損益円"]) for row in rows]
    return {"玉数": len(values), "損益円": sum(values),
            "黒字玉": sum(value > 0 for value in values), "黒字損益円": sum(value for value in values if value > 0),
            "赤字玉": sum(value < 0 for value in values), "赤字損益円": sum(value for value in values if value < 0),
            "同値玉": sum(value == 0 for value in values),
            "最小円": min(values) if values else None, "中央値円": statistics.median(values) if values else None,
            "最大円": max(values) if values else None, "平均円": statistics.mean(values) if values else None}


def by_role(rows: list[dict]) -> dict:
    """
    機能: 元B1の順行/転換初動を分け、既存玉金額の分布を保存する。
    引数: rows(list[dict])は元役割を持つ小型玉情報。
    返り値: dictは役割別の同じ金額統計。
    """
    need(all(row["元役割"] in ROLES for row in rows), "元役割が未定義です")
    return {role: aggregate([row for row in rows if row["元役割"] == role]) for role in ROLES}


def collect(sessions: list[dict]) -> tuple[dict, dict]:
    """
    機能: 外側会計と定時を結び、要求時計/方向ごとの実完結玉を集める。
    引数: sessions(list[dict])は保存一場結果。原板・新規売買再生は使わない。
    返り値: tuple[dict,dict]は6会計別玉mapと場/定時別の共有判断。
    """
    books = {key: {} for key in KEYS}
    grids = {}
    for session in sessions:
        name = session["session"]
        need(set(session["books"]) == set(KEYS), "6会計が揃いません")
        at_map = {grid["at"]: grid for grid in session["grid_decisions"]}
        need(len(at_map) == len(session["grid_decisions"]), "同一定時の重複")
        for at, grid in at_map.items():
            need((name, at) not in grids and set(grid["policies"]) == set(POLICIES), "定時又は政策schema不整合")
            grids[name, at] = grid
            flags = [boolean(grid["policies"][p]["candidate_accepted"], p) for p in POLICIES]
            need(not flags[2] or flags[1], "C1候補供給がC0に包含されません")
            need(not flags[1] or flags[0], "C0候補供給がA0に包含されません")
        for key in KEYS:
            book = session["books"][key]
            need(book["mode"] == "S0G1" and book["session"] == name and book["side_cap"] == 100, "金融内部モード又は研究枚数が異なります")
            need(book["fill_delay_seconds"] == int(key[-1]) and not book["unresolved"] and book["metrics"]["open_quantity"] == 0, "遅延又は完結条件の不整合")
            decisions = {decision["at"]: decision for decision in book["decisions"]}
            need(len(decisions) == len(book["decisions"]) and set(decisions) == set(at_map), "金融判断の定時が不一致")
            total = 0
            for lot in book["lots"]:
                orders = [order for order in book["orders"] if order["position_id"] == lot["id"] and order["kind"] == "entry"]
                need(len(orders) == 1, "実玉の新規注文が一意ではありません")
                order = orders[0]
                closed = [piece for piece in book["closed"] if piece["position_id"] == lot["id"]]
                need(lot["quantity"] == 0 and lot["initial_quantity"] == 100 and sum(piece["quantity"] for piece in closed) == 100, "玉と返済量の不一致")
                need(order["filled_quantity"] == 100 and order["fill_time"] == lot["entry_time"] and order["fill_price"] == lot["entry_price"], "新規約定と実玉が不一致")
                pnl = yen(lot["net_pnl"])
                need(sum(yen(piece["pnl5"]) for piece in closed) == pnl, "玉と返済片の1円不整合")
                at, side = order["request_time"], lot["side"]
                need(side in (-1, 1) and order["side"] == side and at in at_map, "要求時計又は方向の不整合")
                grid = at_map[at]
                policy = grid["policies"][key[:2]]
                need(grid["clock_allowed"] and policy["candidate_accepted"] and policy["allowed"] and policy["side"] == side, "実新規と元候補供給が不一致")
                old = [direction for direction in grid["decision"]["directions"] if direction["side"] == side]
                need(len(old) == 1 and old[0]["allowed"] and old[0]["role"] == lot["role"], "元B1方向又は役割が不一致")
                selected = (name, at, side)
                need(selected not in books[key], "同一要求時計方向の実玉重複")
                books[key][selected] = {"場": name, "要求時計": at, "方向": side,
                    "実新規": (lot["entry_time"], lot["entry_price"], lot["initial_quantity"]),
                    "費用後損益円": pnl, "元役割": old[0]["role"], "参照ID": lot["reference_id"]}
                total += pnl
            need(total == yen(book["metrics"]["net_pnl_yen"]), "玉合計と会計総額が不一致")
    return books, grids


def rejection(source: dict, other_key: str, grid: dict, other_book: dict) -> dict:
    """
    機能: 片側実参加を相手の純候補選別と候補供給後の不採用へ分ける。
    引数: source(dict)は実参加玉、other_key(str)は相手会計、grid/other_book(dict)は保存判断。
    返り値: dictは排他的な参加区分と重なり得る追加条件失敗・保存アクション。
    """
    policy = grid["policies"][other_key[:2]]
    accepted = boolean(policy["candidate_accepted"], "相手候補供給")
    directions = [row for row in policy["directions"] if row["side"] == source["方向"]]
    need(len(directions) == 1, "相手の方向判定が一意ではありません")
    direction = directions[0]
    decisions = [row for row in other_book["decisions"] if row["at"] == source["要求時計"]]
    need(len(decisions) == 1, "相手金融判断が一意ではありません")
    decision = decisions[0]
    orders = [row for row in other_book["orders"] if row["kind"] == "entry" and row["request_time"] == source["要求時計"] and row["side"] == source["方向"]]
    need(all(row["filled_quantity"] == 0 for row in orders), "相手に実新規があるのに片側へ分類しました")
    failed = []
    seen = set()
    for check in direction["added_checks"]:
        need(check["id"] not in seen and check["group"] == "追加必須", "追加チェックが重複又は別groupです")
        seen.add(check["id"])
        known, passed = boolean(check["known"], check["id"]), boolean(check["passed"], check["id"])
        need(known or not passed, "未知なのに追加条件が成立")
        if not known or not passed:
            failed.append(check["id"] + (":既知不成立" if known else ":未知"))
    if accepted:
        need(policy["allowed"] and policy["side"] == source["方向"] and direction["allowed"], "相手候補の方向が不一致")
        category, state = "候補供給後の実不採用", "候補あり"
    else:
        need(not direction["allowed"] and not orders, "純選別されていない方向を純選別へ分類しました")
        category = "純候補選別"
        state = "必要値未知" if boolean(direction["required_unknown"], "相手方向の未知") else "既知不成立"
        need(failed, "追加AND以外の原因を純選別へ混ぜました")
    return {"区分": category, "状態": state, "方向未知": direction["required_unknown"], "相手最終未知": policy["required_unknown"],
        "追加失敗": failed, "金融アクション": decision["action"], "金融理由": decision["reason"],
        "新規要求数": len(orders), "新規要求枚数": sum(row["quantity"] for row in orders)}


def one_side(rows: list[dict], other_key: str, grids: dict, sessions: dict) -> dict:
    """
    機能: 片側の既存玉を、純選別・実不採用・役割・重複条件へ集約する。
    引数: rows(list[dict])は片側玉、other_key(str)、grids/sessions(dict)は相手参照。
    返り値: dictは黒赤の排除/追加数・金額分布。群の損益を新戦略へ足し戻さない。
    """
    categories = {"純候補選別": [], "候補供給後の実不採用": []}
    states = {"必要値未知": [], "既知不成立": []}
    overlaps, actions, reasons = defaultdict(list), defaultdict(list), defaultdict(list)
    final_unknown = []
    details = []
    for row in rows:
        detail = rejection(row, other_key, grids[row["場"], row["要求時計"]], sessions[row["場"]]["books"][other_key])
        categories[detail["区分"]].append(row)
        if detail["区分"] == "純候補選別":
            states[detail["状態"]].append(row)
            for failure in detail["追加失敗"]:
                overlaps[failure].append(row)
            if detail["相手最終未知"]:
                final_unknown.append(row)
        else:
            actions[detail["金融アクション"]].append(row)
            reasons[detail["金融アクション"] + ":" + detail["金融理由"]].append(row)
        details.append({**row, **detail})
    need(sum(len(group) for group in categories.values()) == len(rows), "片側参加分類の漏れ")
    return {"既存玉": aggregate(rows), "元役割別": by_role(rows),
        "排他的参加区分": {name: {"既存玉": aggregate(group), "元役割別": by_role(group)} for name, group in categories.items()},
        "純選別の方向状態": {name: aggregate(group) for name, group in states.items()},
        "純選別の追加条件失敗_重複あり": {name: aggregate(group) for name, group in sorted(overlaps.items())},
        "純選別の相手最終未知_重複属性": aggregate(final_unknown),
        "候補あり不採用の保存アクション別": {name: aggregate(group) for name, group in sorted(actions.items())},
        "候補あり不採用の保存理由別": {name: aggregate(group) for name, group in sorted(reasons.items())},
        "代表例_最大絶対既存額2件": sorted(details, key=lambda row: (-abs(row["費用後損益円"]), row["場"], row["要求時計"]))[:2]}


def diagnose(sessions: list[dict], formal: dict) -> dict:
    """
    機能: 6比較の実入口差を算出し、正式の入口間分解と総額へ結ぶ。
    引数: sessions(list[dict])は保存会計、formal(dict)は正式集計の正本。
    返り値: dictは比較と既存玉役割分布。1円差又は分類不一致は停止。
    """
    books, grids = collect(sessions)
    by_session = {session["session"]: session for session in sessions}
    need(len(by_session) == len(sessions), "場が重複しています")
    need(set(formal["比較"]) == set(KEYS), "正式比較の6会計が不一致")
    totals = {key: sum(row["費用後損益円"] for row in values.values()) for key, values in books.items()}
    for key, total in totals.items():
        need(total == yen(formal["比較"][key]["費用後損益円"]), f"正式総額の1円不一致:{key}")
    comparisons = {}
    for delay in (0, 1):
        for label, a_mode, b_mode in PAIRS:
            a_key, b_key = f"{a_mode}_D{delay}", f"{b_mode}_D{delay}"
            left, right = books[a_key], books[b_key]
            common = left.keys() & right.keys()
            exact = {key for key in common if left[key]["実新規"] == right[key]["実新規"]}
            changed, only_a, only_b = common - exact, left.keys() - right.keys(), right.keys() - left.keys()
            amount = lambda values, keys: sum(values[key]["費用後損益円"] for key in keys)
            legacy = {"比較": [a_key, b_key], "同実新規": len(exact),
                "同実新規A損益円": amount(left, exact), "同実新規B損益円": amount(right, exact),
                "同実新規出口差円": amount(right, exact) - amount(left, exact),
                "共通だが取得変更": len(changed), "取得変更A損益円": amount(left, changed), "取得変更B損益円": amount(right, changed),
                "Aのみ": len(only_a), "Bのみ": len(only_b), "Aのみ損益円": amount(left, only_a), "Bのみ損益円": amount(right, only_b)}
            saved = formal["入口間の同実新規分解"][f"{label}_D{delay}"]
            need(saved == legacy, f"正式入口間分解と1円又は件数が不一致:{label}_D{delay}")
            parts = {
                "同実新規の出口差": legacy["同実新規出口差円"],
                "取得変更": legacy["取得変更B損益円"] - legacy["取得変更A損益円"],
                "Aのみの消失": -legacy["Aのみ損益円"], "Bのみの追加": legacy["Bのみ損益円"]}
            delta = totals[b_key] - totals[a_key]
            need(sum(parts.values()) == delta, "4寄与と総額差が不一致")
            exits = {name: {"玉数": 0, "A損益円": 0, "B損益円": 0, "差円": 0} for name in ("同値", "B増加", "B減少")}
            for key in exact:
                a, b = left[key]["費用後損益円"], right[key]["費用後損益円"]
                target = exits["同値" if a == b else "B増加" if b > a else "B減少"]
                target["玉数"] += 1
                target["A損益円"] += a
                target["B損益円"] += b
                target["差円"] += b-a
            need(sum(row["差円"] for row in exits.values()) == legacy["同実新規出口差円"], "同実新規の出口分類が不一致")
            a_only = one_side([left[key] for key in sorted(only_a)], b_key, grids, by_session)
            b_only = one_side([right[key] for key in sorted(only_b)], a_key, grids, by_session)
            need(b_only["排他的参加区分"]["純候補選別"]["既存玉"]["玉数"] == 0, "狭いBだけの参加なのに広いAの元候補供給がありません")
            comparisons[f"{label}_D{delay}"] = {"比較": [a_key, b_key], "正式分解": legacy,
                "全差円": delta, "4寄与円": parts, "同実新規の出口分類": exits,
                "同実新規の元役割別A既存額": by_role([left[key] for key in exact]),
                "取得変更の元役割別A既存額": by_role([left[key] for key in changed]),
                "取得変更の元役割別B既存額": by_role([right[key] for key in changed]),
                "Aのみ": a_only, "Bのみ": b_only}
    need(set(comparisons) == set(formal["入口間の同実新規分解"]), "正式比較キーが余剰又は欠落")
    return {"入口差比較": comparisons, "会計別の元役割と既存玉金額分布": {key: by_role(list(rows.values())) for key, rows in books.items()}}


def markdown(value: dict, entry_link: str) -> str:
    """
    機能: 既存額の排除と参加差を、原因の範囲を明示したMarkdownへ写す。
    引数: value(dict)は診断、entry_link(str)は別の入口監査への相対リンク。
    返り値: strは日本語Markdown。
    """
    lines = ["# 84の入口選別と実参加差", "", "固定結果を見た後の事後診断。全66場は既使用で、C0/C1の候補は少数。新市場損益再生・閾値探索は0。以下は既存会計の比較と金額分布であり、群を足し合わせて未実行の別戦略損益と呼ばない。", "",
        "全案で同じS0G1を使うが、入口変更で保有・新規待機・返済待ちの占有が変わり、後続参加も変わり得る。要求時計/方向に加えて実新規時刻・価格・数量まで同じ玉、取得変更、片側参加を分けた。", "",
        "| A→B | 同実新規 | 出口差円 | 取得変更差円 | Aのみ消失円 | Bのみ追加円 | 全差円 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in value["入口差比較"].values():
        p = row["4寄与円"]
        lines.append(f"| {'→'.join(row['比較'])} | {row['正式分解']['同実新規']} | {p['同実新規の出口差']:,} | {p['取得変更']:,} | {p['Aのみの消失']:,} | {p['Bのみの追加']:,} | {row['全差円']:,} |")
    lines += ["", "## Aだけに残った既存玉", "", "相手のcandidate_accepted=falseを純候補選別、trueなのに実新規がない場合を候補供給後の実不採用とした。後者は保存された金融アクション/理由の分類であり、占有を原板から独立再構築した検査ではない。", "",
        "| A→B | 排他的区分 | 玉数 | 既存赤字玉/額円 | 既存黒字玉/額円 | 元額合計円 |", "|---|---|---:|---:|---:|---:|"]
    for row in value["入口差比較"].values():
        for name, group in row["Aのみ"]["排他的参加区分"].items():
            a = group["既存玉"]
            lines.append(f"| {'→'.join(row['比較'])} | {name} | {a['玉数']} | {a['赤字玉']}/{a['赤字損益円']:,} | {a['黒字玉']}/{a['黒字損益円']:,} | {a['損益円']:,} |")
    lines += ["", "純選別で消えた赤字は除外した既存損失、黒字は失った既存勝ちである。それを当時の将来勝敗判別や新しい戦略の獲得利益とは扱わない。方向の必要値未知と既知不成立は排他的に分け、追加チェックの未知/不成立は重なりを許して別集計した。最終unknownには反対方向由来の未知も含み得るため、同方向の未知と別記する。", "",
        "## Bだけの実参加", "", "| A→B | Aに元候補なし | Aに元候補あり・実不採用 | B既存玉数/額円 |", "|---|---:|---:|---:|"]
    for row in value["入口差比較"].values():
        b = row["Bのみ"]
        lines.append(f"| {'→'.join(row['比較'])} | {b['排他的参加区分']['純候補選別']['既存玉']['玉数']} | {b['排他的参加区分']['候補供給後の実不採用']['既存玉']['玉数']} | {b['既存玉']['玉数']}/{b['既存玉']['損益円']:,} |")
    lines += ["", "Bだけの参加を純条件の拡大と呼ばない。C1⊆C0⊆A0という候補包含の下でも、Aが占有中なら狭いBが後続枠へ参加できる。", "",
        "## 元役割別の既存玉金額分布", "", "| 会計 | 元役割 | 玉数 | 既存額円 | 赤字玉/額円 | 黒字玉/額円 | 最小/中央値/最大円 |", "|---|---|---:|---:|---:|---:|---|"]
    for key, roles in value["会計別の元役割と既存玉金額分布"].items():
        for role, group in roles.items():
            dist = "/".join("未観測" if group[name] is None else f"{group[name]:,}" for name in ("最小円", "中央値円", "最大円"))
            lines.append(f"| {key} | {role} | {group['玉数']} | {group['損益円']:,} | {group['赤字玉']}/{group['赤字損益円']:,} | {group['黒字玉']}/{group['黒字損益円']:,} | {dist} |")
    lines += ["", "各片側区分・同実新規・取得変更にも元役割の分布をJSONへ収録した。金額の閾値選択や良い役割だけの再計算は行っていない。", "",
        f"C1を含む初動の純判断保持は[別の基準・保存判断照合]({entry_link})の検査範囲である。初動が保持されたことを、実参加数や利益効果の証明へ読み替えない。", "",
        "正式総額・入口間の同実新規分解・全差4寄与へ一致させ、入力の前後SHAも確認した。本診断は利益の安定性、未使用期、実商品の約定、元指標系列の独立実装を証明しない。", ""]
    return "\n".join(lines)


def run(source: Path, manifest: Path, result: Path, out_json: Path, out_md: Path) -> dict:
    """
    機能: 完成した固定66場と正式集計だけを読み、事後診断を新規保存する。
    引数: source/manifest/result/out_json/out_md(Path)は明示された5つの入力/出力先。
    返り値: dictは保存した診断。原板は読まず既存文書を上書きしない。
    """
    need(not out_json.exists() and not out_md.exists() and out_json.resolve() != out_md.resolve(), "出力は異なる新規2ファイルが必要です")
    ledger, formal = read_json(manifest), read_json(result)
    need(formal["試行"] == 84 and formal["場数"] == len(ledger["sessions"]) == 66 and formal["全場既使用"] is True, "正式84の全66既使用場が必要です")
    need(formal["入力台帳SHA256"] == sha(manifest), "正式台帳SHA不一致")
    paths = [source / f"{entry['id']}.json" for entry in ledger["sessions"]]
    before = {str(path): sha(path) for path in [manifest, result, *paths]}
    need({path.name: before[str(path)] for path in paths} == formal["再生結果SHA256"], "正式再生入力SHA不一致")
    sessions = [read_json(path) for path in paths]
    need([row["session"] for row in sessions] == [entry["id"] for entry in ledger["sessions"]], "台帳順と場ID不一致")
    value = {"試行": 84, "診断": "固定結果後の純入口選別と実参加差", "場数": 66, "全場既使用": True,
        "新市場損益再生": 0, "閾値探索": 0, "診断コードSHA256": sha(Path(__file__)), "観測入力SHA256": before,
        **diagnose(sessions, formal), "正式集計との不一致数": 0}
    need(all(sha(Path(path)) == digest for path, digest in before.items()), "診断中の入力変更")
    value["入力前後変更数"] = 0
    proof = result.parent.parent / "基準と保存判断の照合.json"
    link = os.path.relpath(proof, out_md.parent).replace("\\", "/")
    value["初動保持の別証拠"] = str(proof)
    text = markdown(value, link)
    for path in (out_json, out_md):
        path.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with out_md.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return value


def main() -> None:
    """
    機能: 必須Path引数から完成後の事後診断を実行する。
    引数: --input/--manifest/--result/--out-json/--out-md(Path)は全て必須。
    返り値: None。成功時に出力と比較数を表示する。
    """
    parser = argparse.ArgumentParser()
    for name in ("input", "manifest", "result", "out-json", "out-md"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    value = run(args.input, args.manifest, args.result, args.out_json, args.out_md)
    print(json.dumps({"出力": str(args.out_json), "比較数": len(value["入口差比較"]), "不一致数": value["正式集計との不一致数"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
