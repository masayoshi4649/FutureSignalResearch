"""83の8出口・遅延会計を独立照合し、Viewerと小型研究資料へまとめる。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path


def load_base() -> object:
    """
    機能: 固定80の約定・所有・費用照合だけを読取で再用する。
    引数: なし。
    返り値: object はcash_checkを公開するモジュール。
    """
    path = Path(__file__).resolve().parent.parent / "FAR後期15分移植/集計.py"
    spec = importlib.util.spec_from_file_location("fixed80_summary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dump(path: Path, value: object) -> None:
    """
    機能: UTF-8の正式JSONを新規保存する。
    引数: path (Path) は保存先、value (object) はJSON互換値。
    返り値: None。既存結果は上書きしない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path: Path) -> str:
    """
    機能: 入力・成果物の指紋を計算する。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compressed(path: Path, rows: list[dict]) -> None:
    """
    機能: 重複する中間原板を含めず、判断又は取引診断を圧縮保存する。
    引数: path (Path) は保存先、rows (list[dict]) は小型JSON行。
    返り値: None。既存ファイルは変更しない。
    """
    with path.open("xb") as binary:
        with gzip.GzipFile(fileobj=binary, mode="wb", mtime=0) as stream:
            for row in rows:
                stream.write((json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8"))


def summarize(source: Path, output: Path, manifest: Path) -> dict:
    """
    機能: 全66場8会計を検査し、結果・比較・Viewer互換約定を保存する。
    引数: source/output/manifest (Path) は再生結果・新規出力根・固定台帳。
    返り値: dict は比較の正本。部分入力や会計矛盾は例外で停止する。
    """
    base = load_base()
    ledger = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(ledger["sessions"]) == 66
    modes = ["S0G1", "S1G1", "S0G2", "S1G2"]
    keys = [f"{mode}_D{delay}" for delay in (0, 1) for mode in modes]
    inputs = {}
    sessions = []
    for entry in ledger["sessions"]:
        path = source / f"{entry['id']}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["session"] == entry["id"] and set(result["books"]) == set(keys)
        inputs[path.name] = digest(path)
        sessions.append(result)
    if output.exists():
        raise ValueError("正式出力先は新規である必要があります")
    output.mkdir(parents=True)
    summaries = {}
    per_session = []
    diagnostics = []
    decisions = []
    availability = {policy: {"全定時": 0, "時計許可": 0, "方向判定成立": 0, "候補生成": 0, "判定項目": {}, "支持未知理由": Counter()} for policy in ("B1",)}
    checks = []
    resources = []
    # ----------------------------------------
    # 生きた候補の生成と実新規は別の記録へ分けます。
    for result in sessions:
        decisions.append({"session": result["session"], "grid_decisions": result["grid_decisions"]})
        for grid in result["grid_decisions"]:
            item = availability[grid["entry_policy"]]
            decision = grid["decision"]
            item["全定時"] += 1
            item["時計許可"] += grid["clock_allowed"]
            item["方向判定成立"] += decision["allowed"]
            item["候補生成"] += grid["candidate_accepted"]
            for direction in decision["directions"]:
                for check in direction["checks"]:
                    name = f"{check['group']}:{check['id']}"
                    count = item["判定項目"].setdefault(name, {"方向数": 0, "既知": 0, "成立": 0, "未知": 0})
                    count["方向数"] += 1
                    count["既知"] += check["known"]
                    count["成立"] += check["passed"]
                    count["未知"] += not check["known"]
            for side in ("buy", "sell"):
                support = decision["evidence"][side]
                for field in ("own_reason", "peer_reason", "ofi_reason"):
                    if support[field]:
                        item["支持未知理由"][field + ":" + support[field]] += 1
    for key in keys:
        mode, delay_text = key.split("_D")
        delay = int(delay_text)
        cumulative = peak = drawdown = 0
        totals = Counter()
        day_pnl = defaultdict(float)
        actions = Counter()
        reasons = Counter()
        reason_pnl = Counter()
        values = []
        all_lots = []
        for result in sessions:
            book = result["books"][key]
            assert book["mode"] == mode and book["session"] == result["session"]
            assert book["fill_delay_seconds"] == delay and book["side_cap"] == 100
            check = base.cash_check(book)
            assert not book["unresolved"] and book["metrics"]["open_quantity"] == 0
            checks.append({"session": result["session"], "key": key, **check})
            metric = book["metrics"]
            drawdown = max(drawdown, metric["max_drawdown_yen"], peak - cumulative - metric["min_equity_yen"])
            peak = max(peak, cumulative + metric["equity_peak_yen"])
            cumulative += metric["net_pnl_yen"]
            values.append(metric["net_pnl_yen"])
            day_pnl[result["session"].split("_")[0]] += metric["net_pnl_yen"]
            for name, number in metric.items():
                if name.endswith("_yen") and name in ("cash_yen", "net_pnl_yen", "gross_pnl_yen", "commission_yen", "slippage_yen", "total_cost_yen"):
                    totals[name] += number
                elif type(number) is int and not name.endswith("_yen") and name != "request_before_floor_violations":
                    totals[name] += number
            actions.update(d["action"] for d in book["decisions"])
            for closed in book["closed"]:
                reasons[closed["reason"]] += closed["quantity"]
                reason_pnl[closed["reason"]] += closed["pnl5"]
            for lot in book["lots"]:
                assert lot["quantity"] == 0
                all_lots.append(lot)
                entry_orders = [o for o in book["orders"] if o["position_id"] == lot["id"] and o["kind"] == "entry"]
                assert len(entry_orders) == 1 and lot["initial_quantity"] == 100
                diagnostics.append({"session": result["session"], "key": key, "lot": lot, "entry_order": entry_orders[0],
                    "orders": [o for o in book["orders"] if o["position_id"] == lot["id"]],
                    "closed": [c for c in book["closed"] if c["position_id"] == lot["id"]]})
            name = f"約定/D{delay}/{mode}/{result['session']}.trades.jsonl"
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                for trade in book["trades"]:
                    stream.write(json.dumps(trade, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
            resources.append({"id": f"83_{key}_{result['session']}", "title": f"83 {key} {result['session']}", "symbol": "NK225", "session": result["session"], "product": "NK225micro", "method_id": mode, "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": name, "market_path": f"NK225/{result['session']}/book.jsonl.gz"})
            per_session.append({"session": result["session"], "key": key, "mode": mode, "delay": delay,
                "metrics": metric, "累積損益円": cumulative, "判断": dict(Counter(d["action"] for d in book["decisions"])), "警告": book["warnings"]})
        flagged = [p for p in all_lots if p["flag"]]
        whole = [p for p in all_lots if p.get("whole_flag", False)]
        summaries[key] = {"mode": mode, "追加遅延秒": delay, "費用後損益円": cumulative, "最大DD円": drawdown,
            "全場": len(values), "赤字場数": sum(v < 0 for v in values), "黒字場数": sum(v > 0 for v in values), "同値場数": sum(v == 0 for v in values),
            "赤字日数": sum(v < 0 for v in day_pnl.values()), "日数": len(day_pnl), "日別円": dict(day_pnl),
            "完結玉": len(all_lots), "残玉旗": len(flagged), "残玉旗後赤字": sum(p["net_pnl"] < 0 for p in flagged),
            "全玉旗": len(whole), "全玉旗後赤字": sum(p["net_pnl"] < 0 for p in whole),
            "正益未観測の損益円": sum(p["net_pnl"] for p in all_lots if not p["flag"]),
            "正益観測の損益円": sum(p["net_pnl"] for p in flagged),
            "上位3場利益円": sum(sorted(values, reverse=True)[:3]), "最悪場円": min(values), "最大場円": max(values),
            "総計": dict(totals), "判断": dict(actions), "返済理由別枚数": dict(reasons), "返済理由別損益円": dict(reason_pnl),
            "同約定0pt損益円": sum(c["pnl0"] for r in sessions for c in r["books"][key]["closed"]),
            "同約定10pt損益円": sum(c["pnl10"] for r in sessions for c in r["books"][key]["closed"])}
    # ----------------------------------------
    # 同一候補でも占有により参加が変わるため、実新規まで一致した群を分けます。
    decompositions = {}
    pairs = (("G1_S1対S0", "S0G1", "S1G1"), ("G2_S1対S0", "S0G2", "S1G2"),
             ("S0_G2対G1", "S0G1", "S0G2"), ("S1_G2対G1", "S1G1", "S1G2"))
    for delay in (0, 1):
        for label, mode0, mode1 in pairs:
            k0, k1 = f"{mode0}_D{delay}", f"{mode1}_D{delay}"
            groups = []
            for key in (k0, k1):
                chosen = [d for d in diagnostics if d["key"] == key]
                group = {(d["session"], d["entry_order"]["request_time"], d["lot"]["side"]): d["lot"] for d in chosen}
                assert len(group) == len(chosen), "同一定時方向の実新規重複"
                groups.append(group)
            left, right = groups
            common = set(left) & set(right)
            exact = {k for k in common if all(left[k][n] == right[k][n] for n in ("side", "entry_price", "entry_time", "initial_quantity"))}
            changed, only0, only1 = common - exact, set(left) - set(right), set(right) - set(left)
            decompositions[f"{label}_D{delay}"] = {"比較": [k0, k1], "同実新規": len(exact),
                "同実新規A損益円": sum(left[k]["net_pnl"] for k in exact), "同実新規B損益円": sum(right[k]["net_pnl"] for k in exact),
                "同実新規出口差円": sum(right[k]["net_pnl"] - left[k]["net_pnl"] for k in exact),
                "共通だが取得変更": len(changed), "取得変更A損益円": sum(left[k]["net_pnl"] for k in changed),
                "取得変更B損益円": sum(right[k]["net_pnl"] for k in changed),
                "Aのみ": len(only0), "Bのみ": len(only1), "Aのみ損益円": sum(left[k]["net_pnl"] for k in only0),
                "Bのみ損益円": sum(right[k]["net_pnl"] for k in only1)}
    value = {"試行": 83, "場数": 66, "全場既使用": True, "入力台帳SHA256": digest(manifest), "再生結果SHA256": inputs,
        "比較": summaries, "出口間の同実新規分解": decompositions, "定時の候補と入力可用性": availability, "場別": per_session,
        "入力品質": {r["session"]: r["quality"] for r in sessions},
        "未計測欄の注意": "互換のrequest_before_floor_violationsを0違反の根拠にしない。独立原板監査を別に参照する。"}
    dump(output / "結果.json", value)
    dump(output / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    dump(output / "約定会計照合.json", {"会計数": len(checks), "不一致数": 0, "内容": "80固定cash_checkを読取再用し、所有・数量・現金・費用・全返済・全玉・注文対応・定時を照合", "照合": checks})
    compressed(output / "取引診断.jsonl.gz", diagnostics)
    compressed(output / "定時判断.jsonl.gz", decisions)
    assert all(digest(source / name) == wanted for name, wanted in inputs.items())
    return value


def main() -> None:
    """
    機能: 全66場の照合集計を明示入力から実行する。
    引数: --input/--out/--manifest (Path) は入力・新規成果物・固定台帳。
    返り値: None。成功時は比較の小型要約を表示する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    value = summarize(args.input, args.out, args.manifest)
    print(json.dumps({"会計数": len(value["場別"]), "比較": {k: {n: v[n] for n in ("費用後損益円", "最大DD円", "赤字場数", "完結玉", "全玉旗後赤字")} for k, v in value["比較"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
