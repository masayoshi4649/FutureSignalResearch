"""88の固定済み入口・初回利益・取得変更を小型観測へまとめる。"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


def sha(path: Path) -> str:
    """
    機能: 診断入力の内容指紋を計算する。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path: Path) -> list[dict]:
    """
    機能: 圧縮した正式記録を読む。
    引数: path (Path) はJSONL gzip。
    返り値: list[dict] は記録。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def clock(at: float) -> str:
    """
    機能: 価格時計を日本時刻へ表示する。
    引数: at (float) はUnix秒。
    返り値: str は年月日時分秒。
    """
    return datetime.fromtimestamp(at, ZoneInfo("Asia/Tokyo")).isoformat()


def diagnose(paths: dict[str, Path], out: Path, markdown: Path) -> dict:
    """
    機能: 既存会計を再選択せず、入口と利益保護の課題を集計する。
    引数: paths (dict[str,Path]) は4正本、out/markdown (Path) は新規保存先。
    返り値: dict は小型診断。売買再生・原板・API利用は行わない。
    """
    before = {name: sha(path) for name, path in paths.items()}
    result = json.loads(paths["result"].read_text(encoding="utf-8"))
    trades, shared, sources = (lines(paths[name]) for name in ("trades", "grids", "source_decisions"))
    assert result["試行"] == 88 and result["場数"] == 66
    assert len(shared) == len(sources) == 66
    contexts, bindings, grids = {}, {}, {}
    for row in shared:
        session = row["session"]
        for grid in row["grid_decisions"]:
            grids[session, grid["at"]] = grid
        for context in row["profit_contexts"]:
            for trigger in context["triggered_by"]:
                identity = session, trigger["book_key"], trigger["position_id"], trigger["flag_kind"]
                assert identity not in contexts
                contexts[identity] = context, trigger
    for row in sources:
        for binding in row["entry_bindings"]:
            identity = row["session"], binding["book_key"], binding["position_id"]
            assert identity not in bindings
            bindings[identity] = binding
    counts = {key: Counter() for key in result["比較"]}
    by_flag = defaultdict(Counter)
    cases, referenced = [], set()
    for row in trades:
        session, key, lot, order = row["session"], row["key"], row["lot"], row["entry_order"]
        pid, side = lot["id"], lot["side"]
        identity = session, key, pid
        binding = bindings[identity]
        referenced.add(identity)
        assert binding["entry_order_id"] == order["id"] and binding["reference_id"] == lot["reference_id"]
        current = binding["current_qualification"]
        source = lot["source_entry"]["read_lot"]["reference"]
        source_at = source["at"]
        source_price = source["entry"]
        event = current["event"]
        if key.startswith("E1"):
            assert current["e1_allowed"] and event is not None
            assert event["impulse"]["bar_end"] < event["pullback"]["bar_end"] < event["recovery"]["bar_end"] <= event["confirmation"]["bar_end"]
        metric = counts[key]
        metric["完結玉"] += 1
        metric["費用後円"] += lot["net_pnl"]
        metric["勝ち玉"] += lot["net_pnl"] > 0
        metric["負け玉"] += lot["net_pnl"] < 0
        metric["現在資格成立玉"] += current["current_allowed"]
        metric["現在資格と再開履歴の両成立玉"] += current["e1_allowed"]
        metric["正益前損失円"] += lot["net_pnl"] if not lot["flag"] else 0
        metric["正益後損益円"] += lot["net_pnl"] if lot["flag"] else 0
        measured = [c for c in row["closed"] if c["request_to_fill_adverse_yen"] is not None]
        missing = [c for c in row["closed"] if c["request_to_fill_adverse_yen"] is None]
        metric["返済要求後悪化の既知分円"] += sum(c["request_to_fill_adverse_yen"] for c in measured)
        metric["返済要求後悪化の未計測片"] += len(missing)
        metric["返済要求後悪化の未計測枚"] += sum(c["quantity"] for c in missing)
        observation = {"場": session, "候補": key, "参照ID": lot["reference_id"], "方向": side,
            "要求": clock(order["request_time"]), "元手法": binding["source_method"], "実初期量": lot["initial_quantity"],
            "費用後円": lot["net_pnl"], "元参照誕生から要求秒": order["request_time"] - source_at,
            "元参照価格から実取得の方向差pt": side * (lot["entry_price"] - source_price),
            "現在資格": current["current_allowed"], "現在理由": current["reason"], "取得ATR比": current["placement_atr"],
            "現在資格と再開履歴の両成立": current["e1_allowed"], "再開履歴単独有効": current["event_valid"], "再開event": None if event is None else event["id"],
            "確認から要求秒": None if event is None else order["request_time"] - event["confirmation"]["bar_end"],
            "eventが参照前": binding["pool_evaluation"]["event_before_source"],
            "残玉正益": lot["flag"], "全玉正益": lot["whole_flag"]}
        for kind in ("residual", "whole"):
            has_flag = lot["flag" if kind == "residual" else "whole_flag"]
            found = contexts.get((*identity, kind))
            assert has_flag == (found is not None)
            if found is None:
                continue
            context, trigger = found
            tech, quote = context["technical"], context["quote"]
            # ----------------------------------------
            # 当原行の指標状態を診断するだけで、利確条件へ遡及しません。
            momentum = "未知"
            if tech["reversal_known"]:
                momentum = "同方向" if side * (tech["histogram3"] - tech["previous_histogram3"]) > 0 and side * (tech["rsi3"] - tech["previous_rsi3"]) > 0 else "両勢いの同方向は未成立"
            group = by_flag[key, kind, momentum]
            group["玉数"] += 1
            group["最終費用後円"] += lot["net_pnl"]
            group["最終赤字玉"] += lot["net_pnl"] < 0
            observation[kind] = {"初回": clock(quote["time"]), "原行": quote["line"], "同原行全fill後残量": trigger["remaining_after_fill"],
                "同原行実確定益円": trigger["closed_net_after_fill"], "当時のMACDとRSI増分": momentum,
                "確定3分足から原行まで秒": quote["time"] - tech["bar3_end"]}
        if not key.startswith("S_"):
            cases.append(observation)
    assert referenced <= set(bindings)
    unfilled = Counter(identity[1] for identity in set(bindings) - referenced)
    for key, metric in counts.items():
        assert metric["完結玉"] == result["比較"][key]["完結玉"]
        assert metric["費用後円"] == result["比較"][key]["費用後損益円"]
    assert before == {name: sha(path) for name, path in paths.items()}
    value = {"試行": 88, "成功": True, "売買再生": 0, "原板読取": 0, "新期間": 0, "API": 0,
        "入力SHA256": before, "候補別": {key: dict(v) for key, v in counts.items()}, "実玉のない新規要求結合数": dict(unfilled),
        "初回利益当時の勢い別": [{"候補": k, "旗": f, "勢い": m, **dict(v)} for (k, f, m), v in sorted(by_flag.items())],
        "E0E1の取得観測": cases, "対応分解": result["出口間の同実新規分解"],
        "限界": "既使用66場の記述統計。初回利益時の勢いは観測で、反実仮想利確損益・因果・新条件の優位性は未検証。"}
    text = ["# 88：入口と初回利益の診断", "", "15分の取得資格と連続利益保護を共通にした既使用66場の観測。新しい条件で再売買した結果ではない。", "",
        "| 候補 | 完結玉 | 費用後円 | 正益未観測円 | 正益観測円 | 要求後悪化の既知分円 | 未計測片/枚 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, row in counts.items():
        text.append("| " + key + " | " + " | ".join(f"{row[name]:,}" for name in ("完結玉", "費用後円", "正益前損失円", "正益後損益円", "返済要求後悪化の既知分円")) + f" | {row['返済要求後悪化の未計測片']}/{row['返済要求後悪化の未計測枚']} |")
    text += ["", "要求後悪化は約定価格が要求時気配より不利になった額の符号付き合計。要求時気配が未知の返済片は0円へ補完せず、未計測の片数・枚数を併記する。入口の優位性やトレーリング放置と同一視しない。", "",
        "初回利益時のMACD・RSI増分は当原行の確定足に基づく。指標が弱かった群の最終損益だけから、その時点で決済すれば改善したとは言えない。", "",
        "同参照IDを先に合わせ、さらに要求・方向・実取得時刻/価格/量が一致した群だけを同実新規とする。詳細は[JSON](入口と利益の診断.json)の対応分解と取得観測を参照。", "",
        "記録は仮説の材料であり、安定利益の確認や将来成績の保証ではない。"]
    for path, content in ((out, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"), (markdown, "\n".join(text) + "\n")):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return value


def main() -> None:
    """
    機能: 明示した4正本だけから診断を新規保存する。
    引数: result/trades/grids/source-decisions/out/md (Path) は入出力。
    返り値: None。不一致なら停止する。
    """
    parser = argparse.ArgumentParser()
    for name in ("result", "trades", "grids", "source-decisions", "out", "md"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("result", "trades", "grids", "source_decisions")}
    value = diagnose(paths, args.out, args.md)
    print(json.dumps({"成功": value["成功"], "観測玉": len(value["E0E1の取得観測"]), "売買再生": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
