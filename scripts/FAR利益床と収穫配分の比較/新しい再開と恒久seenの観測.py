"""89の主E1G1で、当時資格と恒久seenによる再参加不可を保存値だけから観測する。"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path


HELPER_PATH = Path(__file__).with_name("再開価格構造の事後観測.py")
SPEC = importlib.util.spec_from_file_location("当時観測の共通読取", HELPER_PATH)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)
BOOK = "E1G1_D0"
SEEN_REASON = "同じ参照HoldIDへ再参加しない"


def through_quote(piece: dict, quote: dict) -> bool:
    """
    機能: 返済片が定時直前の正常原行までに実行済みかを判定する。
    引数: piece(dict)は保存返済片、quote(dict)は定時の最後の原行。
    返り値: boolは時計と同時計物理行で観測済みなら真。
    """
    return (piece["exit_time"], piece["exit_line"]) <= (quote["time"], quote["line"])


def point_relation(point: dict, exit_piece: dict | None, observations: dict) -> dict:
    """
    機能: event点の公開と前回の全返済の前後を、当時時計と原行で分ける。
    引数: point(dict)は保存EventPoint、exit_piece(dict|None)は全返済の最後片、observations(dict)はID索引。
    返り値: dictは前/後/同原行/不明。eventID差だけで新局面とはしない。
    """
    if exit_piece is None:
        return {"関係": "前回の全返済未完了又は実玉なし", "返済後公開": None, "公開秒差": None}
    record = observations.get(point["observation_id"])
    if record is None:
        return {"関係": "観測ID欠落", "返済後公開": None, "公開秒差": None}
    data = record["input"]
    delta = point["published_at"] - exit_piece["exit_time"]
    if delta != 0:
        return {"関係": "返済後" if delta > 0 else "返済前", "返済後公開": delta > 0, "公開秒差": delta}
    if data["quote"]["line"] != exit_piece["exit_line"]:
        after = data["quote"]["line"] > exit_piece["exit_line"]
        return {"関係": "同時計の返済後原行" if after else "同時計の返済前原行", "返済後公開": after, "公開秒差": 0}
    if data["origin"] == "quote":
        # ----------------------------------------
        # Runtimeは当行event公開→金融fillの順。同原行のeventは返済より先。
        return {"関係": "同原行のevent公開が返済fillより前", "返済後公開": False, "公開秒差": 0}
    return {"関係": "同時計で公開と返済の詳細順序未確定", "返済後公開": None, "公開秒差": 0}


def bind_event(event: dict, at: float, observations: dict) -> dict:
    """
    機能: eventのi/p/r/kを当時の保存Technicalと公開順へ結合する。
    引数: event(dict)、at(float)、observations(dict)はevent・当時要求・同場ID索引。
    返り値: dictは当時点の簡潔な出典。欠落や未来は拒否する。
    """
    result = {}
    for label, field in (("i", "impulse"), ("p", "pullback"), ("r", "recovery"), ("k", "confirmation")):
        point = event[field]
        record = observations[point["observation_id"]]
        data = record["input"]
        assert data["window"] == event["window"] and data["epoch_start"] == event["epoch_start"]
        assert data["technical"]["bar3_end"] == point["bar_end"] and data["at"] == point["published_at"]
        assert event["epoch_start"] < point["bar_end"] <= point["published_at"] <= at and not data["after_eof"]
        result[label] = {**point, "ordinal": data["ordinal"], "close": data["technical"]["close3"]}
    assert result["i"]["bar_end"] < result["p"]["bar_end"] < result["r"]["bar_end"] <= result["k"]["bar_end"]
    assert result["i"]["ordinal"] < result["p"]["ordinal"] < result["r"]["ordinal"] <= result["k"]["ordinal"]
    return result


def previous_state(binding: dict, trade: dict | None, decision: dict, quote: dict, effects: list) -> dict:
    """
    機能: 過去参加の保有・取消・実確定益と正益旗を、今回定時までで集計する。
    引数: binding(dict)、trade(dict|None)、decision(dict)、quote(dict)、effects(list)は保存値。
    返り値: dictは当時の前回状態。未観測の返済や最終利益を用いない。
    """
    prior_effects = [effect for effect in effects if effect["reference_id"] == binding["reference_id"] and effect["at"] <= decision["at"] and (effect["origin"] == "timer" or effect["quote_index"] <= quote["index"])]
    cancelled = sum(effect["cancelled"] for effect in prior_effects)
    state = {"前回entry_order_id": binding["entry_order_id"], "前回position_id": binding["position_id"], "前回要求時計": binding["at"], "前回要求枚数": binding["requested_quantity"], "当時までの取消枚数": cancelled}
    if trade is None:
        status = "取消のみ" if cancelled == binding["requested_quantity"] else "未約定pending"
        state.update({"状態": status, "当時までの取得枚数": 0, "当時までの返済枚数": 0, "当時までの費用後実確定円": 0, "実確定符号": "実玉なし", "前回strict正益旗を観測済": False, "前回全玉正益旗を観測済": False, "返済完了時計": None, "最後の返済片": None, "部分利確済枚数": 0})
        return state
    lot = trade["lot"]
    assert (lot["entry_time"], lot["entry_line"]) <= (quote["time"], quote["line"])
    pieces = [piece for piece in trade["closed"] if through_quote(piece, quote)]
    closed = sum(piece["quantity"] for piece in pieces)
    realized = sum(piece["pnl5"] for piece in pieces)
    pending = binding["requested_quantity"] - lot["initial_quantity"] - cancelled
    assert pending >= 0 and closed <= lot["initial_quantity"]
    complete = closed == lot["initial_quantity"] and pending == 0
    last = max(pieces, key=lambda piece: (piece["exit_time"], piece["exit_line"])) if complete and pieces else None
    residual_flag = lot["flag"] and (lot["flag_time"], lot["flag_index"]) <= (quote["time"], quote["index"])
    whole_flag = lot["whole_flag"] and (lot["whole_flag_time"], lot["whole_flag_index"]) <= (quote["time"], quote["index"])
    state.update({"状態": "実玉返済済" if complete else "実玉又は未約定残あり", "当時までの取得枚数": lot["initial_quantity"], "当時までの返済枚数": closed, "当時の未約定新規残": pending, "当時の保有残": lot["initial_quantity"] - closed, "当時までの費用後実確定円": realized, "実確定符号": ">0" if realized > 0 else "<=0", "前回strict正益旗を観測済": residual_flag, "前回全玉正益旗を観測済": whole_flag, "返済完了時計": last["exit_time"] if last else None, "最後の返済片": {key: last[key] for key in ("exit_time", "exit_line", "reason")} if last else None, "部分利確済枚数": sum(piece["quantity"] for piece in pieces if piece["harvest"])})
    return state


def artificial() -> dict:
    """
    機能: 同秒未来片の排除、event公開前後、取消のみを手計算で確認する。
    引数: ありません。
    返り値: dictは成功と照合数。市場データは利用しない。
    """
    piece = {"exit_time": 100, "exit_line": 11}
    assert through_quote(piece, {"time": 100, "line": 11})
    assert not through_quote(piece, {"time": 100, "line": 10})
    points = {1: {"input": {"origin": "quote", "quote": {"line": 11}}}}
    assert not point_relation({"observation_id": 1, "published_at": 100}, piece, points)["返済後公開"]
    assert point_relation({"observation_id": 1, "published_at": 101}, piece, points)["返済後公開"]
    assert not point_relation({"observation_id": 1, "published_at": 99}, piece, points)["返済後公開"]
    binding = {"reference_id": "参照1", "entry_order_id": "要求1", "position_id": "玉1", "at": 80, "requested_quantity": 3}
    effect = {"reference_id": "参照1", "at": 90, "origin": "timer", "cancelled": 3}
    assert previous_state(binding, None, {"at": 110}, {"time": 109, "index": 3}, [effect])["状態"] == "取消のみ"
    assert previous_state(binding, None, {"at": 85}, {"time": 84, "index": 3}, [effect])["状態"] == "未約定pending"
    return {"成功": True, "照合数": 7, "対象": ["同秒後Lineの未来返済除外", "同原行eventはfill前", "公開前後", "当時までに取消のみ", "将来取消は当時pending"]}


def main() -> None:
    """
    機能: 明示3gzからE1G1_D0のseen阻害候補を数え、旧参加eventと前回返済へ結合する。
    引数: --decisions/--source-decisions/--diagnostics/--out-json/--out-md(Path)、--self-test(bool)。
    返り値: ありません。新売買・将来結果による選別・正式変更は行わない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("decisions", "source-decisions", "diagnostics", "out-json", "out-md"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    tests = artificial()
    if args.self_test:
        print(json.dumps(tests, ensure_ascii=False))
        return
    assert all((args.decisions, args.source_decisions, args.diagnostics, args.out_json, args.out_md)), "5明示Pathが必須"
    assert not args.out_json.exists() and not args.out_md.exists(), "新規出力先が必須"
    root = Path(__file__).resolve().parents[2]
    fixed = HELPER.fixed_files(root)
    inputs = [args.decisions.resolve(), args.source_decisions.resolve(), args.diagnostics.resolve()]
    before = {str(path): HELPER.digest(path) for path in inputs}
    scenes = {row["session"]: row for row in HELPER.json_lines(inputs[0])}
    source_scenes = {row["session"]: row for row in HELPER.json_lines(inputs[1])}
    trades = [row for row in HELPER.json_lines(inputs[2]) if row["key"] == BOOK]
    by_order = {(row["session"], row["entry_order"]["id"]): row for row in trades}
    assert len(scenes) == len(source_scenes) == 66 and set(scenes) == set(source_scenes)
    assert len(trades) == len(by_order) == 33
    counts, all_reasons = Counter(), Counter()
    rows, all_seen = [], []
    for session, scene in scenes.items():
        source = source_scenes[session]
        book = source["books"][BOOK]
        assert book["source_policy"] == "S"
        bindings = [row for row in source["entry_bindings"] if row["book_key"] == BOOK]
        grids = {grid["at"]: grid for grid in scene["grid_decisions"]}
        decisions = {decision["at"]: decision for decision in book["decisions"]}
        observations = {record["id"]: record for record in scene["entry_observations"]}
        assert set(grids) == set(decisions) and len(observations) == len(scene["entry_observations"])
        counts["新規要求binding"] += len(bindings)
        for at, grid in grids.items():
            decision = decisions[at]
            context = decision["source_context"]
            quote = grid["c0"]["base"]["quote"]
            counts["全定時"] += 1
            counts["時計許可定時"] += grid["clock_allowed"]
            flat = not context["occupied"]
            counts["時計許可かつ占有なし定時"] += grid["clock_allowed"] and flat
            direction_e1 = any(direction["e1_allowed"] for direction in grid["entry"]["directions"])
            counts["時計許可かつ占有なし外E1成立定時"] += grid["clock_allowed"] and flat and direction_e1
            raw = {row["reference"]["id"]: row for row in grid["source"]["lots"]}
            pool = {row["reference_id"]: row for row in grid["policies"]["E1"]["pool"]}
            counts["時計許可かつ占有なし外E1許可raw候補"] += sum(row["allowed"] for row in pool.values()) if grid["clock_allowed"] and flat else 0
            for candidate in decision["candidates"]:
                check = candidate["source_check"]
                ref_id = candidate["reference_id"]
                all_reasons[candidate["reason"]] += 1
                assert ref_id in raw and ref_id in pool
                evaluation = pool[ref_id]
                reference = raw[ref_id]["reference"]
                assert check["rank"] == evaluation["supplied_rank"] and candidate["side"] == reference["side"]
                if not check["seen"]:
                    continue
                all_seen.append({"session": session, "at": at, "reference_id": ref_id, "時計許可": grid["clock_allowed"], "占有なし": flat, "外E1許可": evaluation["allowed"], "closing": reference["closing"], "保存拒否理由": candidate["reason"]})
                if not (grid["clock_allowed"] and flat and evaluation["allowed"] and candidate["reason"] == SEEN_REASON):
                    continue
                assert not reference["closing"] and not check["selected"] and candidate["requested_quantity"] == 0
                prior = [binding for binding in bindings if binding["reference_id"] == ref_id and binding["at"] < at]
                assert len(prior) == 1
                prior = prior[0]
                previous = previous_state(prior, by_order.get((session, prior["entry_order_id"])), decision, quote, book["source_effects"])
                old_event = prior["current_qualification"]["event"]
                current_direction = next(direction for direction in grid["entry"]["directions"] if direction["side"] == reference["side"])
                current_event = current_direction["event"]
                assert current_event and current_direction["event_valid"] and current_event["id"] == evaluation["event_id"]
                old_points = bind_event(old_event, prior["at"], observations)
                current_points = bind_event(current_event, at, observations)
                relations = {label: point_relation(current_event[field], previous["最後の返済片"], observations) for label, field in (("i", "impulse"), ("p", "pullback"), ("r", "recovery"), ("k", "confirmation"))}
                selected_id = context["selected_id"]
                selected_rank = pool[selected_id]["supplied_rank"] if selected_id else None
                quality = quote["valid"] and quote["last"] > 0 and quote["bid"] > 0 and quote["ask"] > quote["bid"] and 0 <= at - quote["time"] <= 15 and grid["source"]["started"] and grid["source"]["at"] == quote["time"]
                gates = {"時計許可": grid["clock_allowed"], "占有なし": flat, "Source生存": reference["quantity"] > 0, "Source_closing": reference["closing"], "外E1許可": evaluation["allowed"], "保存quality関連未知": context["required_unknown"], "保存入力のSource気配当時性": quality, "C0はgate対象外": context["c0_used"] is False, "cap空きは占有なし100枚枠": flat, "同枠の他参照採用": bool(selected_id), "先行順位の他参照採用": selected_rank is not None and selected_rank < check["rank"]}
                rows.append({"session": session, "book_key": BOOK, "at": at, "reference_id_seenキー": ref_id, "native_source_id": reference["source_id"], "side": reference["side"], "Source当時枚数": reference["quantity"], "Source_kind": reference["kind"], "Source_at": reference["at"], "raw_rank": evaluation["raw_rank"], "supplied_rank": evaluation["supplied_rank"], "前回event_id": old_event["id"], "今回event_id": current_event["id"], "eventIDが異なる": old_event["id"] != current_event["id"], "点の変更": {label: old_points[label]["observation_id"] != current_points[label]["observation_id"] for label in old_points}, "前回の当時点": old_points, "今回の当時点": current_points, "今回点と前回返済の順序": relations, "前回参加の当時状態": previous, "他gate": gates, "実際の同枠会計判断": decision["action"], "同枠の別採用reference_id": selected_id or None})
    summary = {"候補出現数": len(rows), "該当定時数": len({(row["session"], row["at"]) for row in rows}), "一意参照HoldID_eventID数": len({(row["reference_id_seenキー"], row["今回event_id"]) for row in rows}), "一意nativeSourceID_eventID数": len({(row["session"], row["native_source_id"], row["今回event_id"]) for row in rows}), "一意参照HoldID数": len({row["reference_id_seenキー"] for row in rows}), "eventID相違": sum(row["eventIDが異なる"] for row in rows), "四点全て相違": sum(all(row["点の変更"].values()) for row in rows), "前回状態": dict(Counter(row["前回参加の当時状態"]["状態"] for row in rows)), "前回費用後実確定符号": dict(Counter(row["前回参加の当時状態"]["実確定符号"] for row in rows)), "前回strict正益旗後": sum(row["前回参加の当時状態"]["前回strict正益旗を観測済"] for row in rows), "前回全玉正益旗後": sum(row["前回参加の当時状態"]["前回全玉正益旗を観測済"] for row in rows), "前回部分利確済": sum(row["前回参加の当時状態"]["部分利確済枚数"] > 0 for row in rows), "前回全返済後のk公開": sum(row["今回点と前回返済の順序"]["k"]["返済後公開"] is True for row in rows), "前回全返済後のp公開": sum(row["今回点と前回返済の順序"]["p"]["返済後公開"] is True for row in rows), "同枠会計判断": dict(Counter(row["実際の同枠会計判断"] for row in rows)), "先行順位の他参照採用": sum(row["他gate"]["先行順位の他参照採用"] for row in rows), "品質関連未知": sum(row["他gate"]["保存quality関連未知"] for row in rows)}
    summary["全返済後p_k公開かつ前回実確定正"] = sum(row["今回点と前回返済の順序"]["p"]["返済後公開"] is True and row["今回点と前回返済の順序"]["k"]["返済後公開"] is True and row["前回参加の当時状態"]["当時までの費用後実確定円"] > 0 for row in rows)
    # ----------------------------------------
    # 候補の繰り返しと前回玉を分け、既存利益を出現回数だけ重複加算しない。
    prior_positions = {}
    for row in rows:
        state = row["前回参加の当時状態"]
        key = (row["session"], state["前回position_id"])
        prior_positions.setdefault(key, {"session": row["session"], **{key: state[key] for key in ("前回position_id", "状態", "当時までの費用後実確定円", "実確定符号", "前回strict正益旗を観測済", "返済完了時計")}})
    summary["一意今回event数"] = len({(row["session"], row["今回event_id"]) for row in rows})
    summary["前回全返済後のi公開"] = sum(row["今回点と前回返済の順序"]["i"]["返済後公開"] is True for row in rows)
    summary["iは返済前だがp_r_kは返済後"] = sum(row["今回点と前回返済の順序"]["i"]["返済後公開"] is False and all(row["今回点と前回返済の順序"][label]["返済後公開"] is True for label in ("p", "r", "k")) for row in rows)
    summary["同枠会計判断別の一意定時数"] = {action: len({(row["session"], row["at"]) for row in rows if row["実際の同枠会計判断"] == action}) for action in ("待ち", "新規要求")}
    summary["前回一意実玉数"] = len(prior_positions)
    summary["前回一意実玉の費用後実確定符号"] = dict(Counter(row["実確定符号"] for row in prior_positions.values()))
    summary["前回一意実玉のstrict正益旗後"] = sum(row["前回strict正益旗を観測済"] for row in prior_positions.values())
    summary["前回状態"] = {status: summary["前回状態"].get(status, 0) for status in ("実玉返済済", "取消のみ", "未約定pending", "実玉又は未約定残あり")}
    summary["Source生存かつclosingなし"] = sum(row["他gate"]["Source生存"] and not row["他gate"]["Source_closing"] for row in rows)
    summary["Source気配当時性成立"] = sum(row["他gate"]["保存入力のSource気配当時性"] for row in rows)
    unchanged = before == {str(path): HELPER.digest(path) for path in inputs} and fixed == HELPER.fixed_files(root)
    assert unchanged
    result = {"成功": True, "対象": BOOK, "確認時刻UTC": datetime.now(timezone.utc).isoformat(), "入力SHA256": before, "コードSHA256": {str(Path(__file__)): HELPER.digest(Path(__file__)), str(HELPER_PATH): HELPER.digest(HELPER_PATH)}, "人工": tests, "母数": dict(counts), "全金融候補の保存理由": dict(all_reasons), "全seen候補のgate分布": dict(Counter(json.dumps({key: row[key] for key in ("時計許可", "占有なし", "外E1許可", "closing", "保存拒否理由")}, ensure_ascii=False, sort_keys=True) for row in all_seen)), "主観測": summary, "全該当出現": rows, "前回実玉を一度だけ数える一覧": list(prior_positions.values()), "入力と88_89固定コード前後不変": unchanged, "固定コード指紋正本": "work/89Go正式化/停止.json", "限界": ["恒久seenはReference.ID（参照HoldID）単位。native source_idは別物。", "候補出現と一意(参照HoldID,eventID)と前回実玉を別集計。D1は加算しない。", "eventID差だけで新局面と断定せず、i/p/r/k差と前回全返済後の公開を区別。", "同枠で別の参照玉が採用されている場合は、seenを外しても単純な追加新規とならない。", "過去の費用後実確定額は今回定時までのClosed片のみ。新しい再参加の仮定損益や将来選別は計算しない。"], "新売買": 0, "新原板読取": 0, "閾値scan": 0, "89変更": 0}
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 恒久seenと新しい再開の観測（89・主E1G1）", "", "正本3gzだけから、時計許可・実玉/注文の占有なし・外E1許可・金融拒否理由が恒久seenである候補を結合した。再参加を仮定する売買や損益は生成していない。", "", "seenのキーはReference.ID（参照HoldID）で、native source_idとは異なる。両者をJSONに残す。", "", "| 観測 | 数 |", "|---|---:|"]
    for label, value in summary.items():
        lines.append(f"| {label} | {json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value} |")
    lines += ["", "母数：" + json.dumps(dict(counts), ensure_ascii=False), "", "前回玉の実確定正負・正益旗と、今回i/p/r/kの公開前後を区別した。同時計は公開レコードの原行とRuntimeのevent→金融fill順を使い、同原行の公開を返済後とはしない。", "", "全該当候補のSource生存量、closing、raw/supplied順位、品質関連未知、同枠の他採用もJSONへ保存した。別候補が同枠採用された出現や、同枠の複数候補を、そのまま追加新規数としては扱わない。", "", "恒久seenは同一会計のセッション内で維持される。新しい再開で候補を止めるかという仕組みの観測であり、seen解除による将来利益の証明ではない。前回実玉の損益も追加再参加戦略の損益として足し上げない。", "", f"人工{tests['照合数']}照合成功。入力3gzと88/89固定コードは前後不変。新売買・原板読取・閾値scan・89変更0。詳細は[{args.out_json.name}]({args.out_json.name})。"]
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"成功": True, "母数": dict(counts), "主観測": summary, "一意前回実玉数": len(prior_positions), "不変": unchanged}, ensure_ascii=False))


if __name__ == "__main__":
    main()
