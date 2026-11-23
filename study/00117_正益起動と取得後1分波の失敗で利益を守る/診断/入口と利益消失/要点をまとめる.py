"""抽出済み上位表を薄くし、11月06日の同出生だけを元Nativeへ結合する。"""

import gzip
import json
from pathlib import Path

from 抽出する import detail, jst, point, sha256


def thin(value: dict) -> dict:
    """
    機能: 極値・要求・実返済・保護時刻を少量の列へまとめる。
    引数: value(dict)は認証済み抽出明細。
    返り値: dictは元の数量・Rを残す表示用記録。
    """
    result = {k: value[k] for k in ("session", "key", "position_id", "side", "initial_quantity",
               "entry_price", "entry_jst", "whole_peak", "final_realized_net", "decrease_yen", "closed_jst")}
    result["source"] = {k: value["source"][k] for k in ("method", "signal_id", "kind", "parent")}
    result["exits"] = [{"order_id": e["order_id"], "reason": e["reason"],
                         "request_jst": e["request_jst"], "request_quote": e["request_quote"],
                         "fill_jst": e["fill_jst"], "fill_quote": e["fill_quote"],
                         "latency_seconds": e["latency_seconds"], "later_accepted_rows": e["later_accepted_rows"],
                         "quantity": e["allocation"]["quantity"], "price": e["allocation"]["exit_price"],
                         "net_yen": e["allocation"]["net_yen"]} for e in value["close_allocations"]]
    audit = value["protection"]
    if audit:
        result["protection"] = {k: (None if audit[k] is None else {
            "jst": audit[k]["jst"], "quote": audit[k]["quote"], "phase": audit[k]["phase"],
            "snapshot": {kk: vv for kk, vv in audit[k]["snapshot"].items() if kk != "h0_117"},
            "decision": {kk: vv for kk, vv in audit[k]["decision"].items() if kk in (
                "c", "m", "p", "b", "warning", "gain_points", "whole_net_yen", "peak_floor",
                "whole_floor", "structural_floor", "protect_price", "floor_hit", "all_reserved_hit",
                "free_quantity", "eligible_exit_quantity", "width_source")}})
            for k in ("first_activation", "first_narrowing", "first_floor_hit", "first_all_reserved_hit")}
        result["protection"]["final_state"] = {k: v for k, v in audit["final_state"].items() if k != "h0_117"}
    else:
        result["protection"] = None
    result["entry_source_atr"] = value["atr"]
    return result


def main() -> None:
    """
    機能: 全20上位60件の小JSONと標準費用の表を新規保存する。
    引数: なし。固定済み抽出結果・F1・同出生Nativeだけを読む。
    返り値: None。原板・価格CSV・退出後価格は開かない。
    """
    folder = Path(__file__).resolve().parent
    extracted = folder / "保存極値から最終実現まで.json"
    raw = extracted.read_bytes()
    assert sha256(raw) == "0efda34b957633c6a797b4e7b64c10e28b0da82c0634779d96074631e1db9b08"
    data = json.loads(raw)
    largest = data["全20最大"]
    native_ref = largest["native"]
    native_path = Path(native_ref["path"])
    native_bytes = native_path.read_bytes()
    assert sha256(native_bytes) == native_ref["sha256"]
    native = json.loads(gzip.decompress(native_bytes))
    source = native["source"]["sources"]["NK225mini_D164_15"]
    signal_id = largest["source"]["signal_id"]
    match = {}
    for key in ("S0_C5_D0", "W100_C5_D0", "P100_C5_D0", "H0E_C5_D0", "H0M_C5_D0"):
        book = native["actual"]["books"][key]
        positions = [p for p in book["positions"] if p["source"]["signal_id"] == signal_id]
        assert len(positions) == 1
        match[key] = thin(detail(book, positions[0], native_ref, largest["session"]))
    signals = [s for s in source["signals"] if s["signal"]["id"] in (
        signal_id, "2026-11-06_Day-NK225mini-D164_15-000011")]
    assert len(signals) == 2
    fixed = Path("work/117進行/F1_117金融条件.json")
    fixed_bytes = fixed.read_bytes()
    assert sha256(fixed_bytes) == "522fe2343b914243fadc4f48d32128a79ecdafcabd84d5a58b5ca399af90d1b0"
    condition = json.loads(fixed_bytes)
    code_paths = [
        "work/117正益と短期波を執行する会計/actual.go",
        "work/117正益と短期波を執行する会計/continuous.go",
        "work/113起動前の支持否定と利益保護の純演算/state.go",
        "../SessionTradeExecuter/internal/strategy/selected_source.go",
        "../SessionTradeExecuter/internal/strategy/selected_day164_policy.go",
        "../SessionTradeExecuter/internal/strategy/selected_ledger.go",
        "../SessionTradeExecuter/internal/strategy/s01.go",
        "../SessionTradeExecuter/internal/strategy/active145.go",
        "../SessionTradeExecuter/internal/rules/addon_specs.go",
    ]
    codes = []
    fixed_map = {str(Path(p).resolve()).lower(): s for p, s in condition["code_sha256"].items()}
    for name in code_paths:
        path = Path(name).resolve()
        digest = sha256(path.read_bytes())
        assert fixed_map[str(path).lower()] == digest
        codes.append({"path": str(path), "sha256": digest})
    best = {k: [thin(v) for v in rows] for k, rows in data["政策費用別上位3"].items()}
    result = {"試行": 117, "成功": True, "定義": data["定義"], "限界": data["限界"],
              "抽出Ref": {"path": str(extracted), "sha256": sha256(raw)},
              "政策費用別上位3": best, "標準C5D0同出生": match, "元Source保存Signal": signals,
              "全20最大同額": [{"key": v["key"], "position_id": v["position_id"], "decrease_yen": v["decrease_yen"]}
                  for rows in best.values() for v in rows if v["decrease_yen"] == largest["decrease_yen"]],
              "金融F1": {"path": str(fixed.resolve()), "sha256": sha256(fixed_bytes)},
              "根拠コード": codes, "Source内側理由": "D164_15のsource_endは親終了へ正規化された理由。内側S01/D07の当該close Reason/StateはこのNativeに未保存のため分岐は未同定。",
              "金融再実行": False, "原板読取": False, "価格CSV読取": False,
              "退出後仮想価格参照": False, "11月09読取": False}
    output = folder / "診断の要点.json"
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    lines = ["|政策・費用|順位|実建玉ID末尾|方向・初期枚数|取得JST|最大評価JST|最終要求JST|最終約定JST|最大W（円）|最終実現（円）|減少（円）|",
             "|---|---:|---|---|---|---|---|---|---:|---:|---:|"]
    for policy in ("S0", "W100", "P100", "H0E", "H0M"):
        for cost in ("C0_D0", "C5_D0"):
            key = policy + "_" + cost
            for rank, v in enumerate(best[key], 1):
                values = [key, str(rank), v["session"] + "/" + v["position_id"].split("-")[-1],
                          ("買" if v["side"] > 0 else "売") + str(v["initial_quantity"]),
                          v["entry_jst"], v["whole_peak"]["jst"], v["exits"][-1]["request_jst"], v["closed_jst"],
                          f'{v["whole_peak"]["whole_net"]:,.0f}', f'{v["final_realized_net"]:,.0f}', f'{v["decrease_yen"]:,.0f}']
                values[4:8] = [s[5:19].replace("T", " ") for s in values[4:8]]
                lines.append("|" + "|".join(values) + "|")
    table = folder / "政策別上位3の表.md"
    with table.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    assert sha256(native_path.read_bytes()) == native_ref["sha256"]
    print(json.dumps({"要点": {"path": str(output), "sha256": sha256(output.read_bytes()), "bytes": output.stat().st_size},
                      "標準同出生": {k: {"peak": v["whole_peak"]["whole_net"], "peak_at": v["whole_peak"]["jst"],
                      "final": v["final_realized_net"], "drop": v["decrease_yen"], "close": v["closed_jst"]} for k, v in match.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
