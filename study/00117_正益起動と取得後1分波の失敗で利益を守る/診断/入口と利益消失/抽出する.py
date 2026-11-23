"""保存された保有中全玉評価の最大点と、最終実現額の差だけを記述する。"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


EXPECTED_COMPLETION = "f9d5dfc49bef7f9b2dcf6bba55fe264b689dc2e8312e0e26c4530e4b1d2872e0"
JST = timezone(timedelta(hours=9))
POLICIES = ("S0", "W100", "P100", "H0E", "H0M")


def sha256(value: bytes) -> str:
    """
    機能: 純bytesのSHA256を返す。
    引数: value(bytes)は入力bytes。
    返り値: strは16進指紋。
    """
    return hashlib.sha256(value).hexdigest()


def jst(value: float | None) -> str | None:
    """
    機能: 保存されたUnix価格時計を日本時間へ表示変換する。
    引数: value(float|None)は秒単位の価格時計。
    返り値: str|NoneはJST日時。実受信時刻とはしない。
    """
    if value is None:
        return None
    return datetime.fromtimestamp(value, JST).isoformat(timespec="milliseconds")


def point(value: dict | None) -> dict | None:
    """
    機能: 保存点を値複写し、JSTの表示列を追加する。
    引数: value(dict|None)はMTM点又は保護点。
    返り値: dict|Noneは元値を保持する小さな表示用点。
    """
    if value is None:
        return None
    result = copy.deepcopy(value)
    stamp = result.get("quote")
    at = result.get("at", stamp.get("time") if stamp else None)
    result["jst"] = jst(at)
    if "snapshot" in result:
        snapshot = result["snapshot"]
        selected = ("policy", "active", "activated_at", "quantity", "remaining", "reserved",
                    "realized_net_yen", "whole_net_yen", "unit_net_yen", "gain_points",
                    "peak_points", "normal_width_points", "width_points", "floor_points",
                    "whole_target_yen", "narrowed", "narrowed_at", "finished", "h0_117")
        result["snapshot"] = {k: snapshot[k] for k in selected if k in snapshot}
        result.pop("after_request", None)
    return result


def detail(book: dict, position: dict, native: dict, session: str) -> dict:
    """
    機能: 一実建玉の極値・注文・返済片・保護保存点を結合する。
    引数: book(dict)は実口座、position(dict)は建玉、native(dict)は出典Ref、session(str)は場。
    返り値: dictは退出後価格を含まない当該実建玉の記述証拠。
    """
    marks = position["marks"]
    peak = marks["whole_max"]
    config = book["config"]
    expected_unit = (Decimal(str(peak["gain_points"])) * 100
                     - (77 + 200 * Decimal(str(config["slip_pts"]))))
    assert expected_unit == Decimal(str(peak["unit_net"]))
    assert (Decimal(str(peak["realized_net"])) + peak["quantity"] * expected_unit
            == Decimal(str(peak["whole_net"])))
    assert position["quantity"] == position["reserved"] == 0
    assert position["initial_quantity"] == position["closed_quantity"]
    orders = [o for o in book["orders"] if o["position_id"] == position["id"]]
    by_order = {o["id"]: o for o in orders}
    events = []
    allocated_net = Decimal(0)
    for fill in book["fills"]:
        allocations = [a for a in fill["allocations"] if a["position_id"] == position["id"]]
        if not allocations:
            continue
        order = by_order[fill["order_id"]]
        for allocation in allocations:
            allocated_net += Decimal(str(allocation["net_yen"]))
            events.append({"order_id": order["id"], "kind": order["kind"],
                           "reason": fill["reason"], "request_jst": jst(order["request_time"]),
                           "request_quote": order["request_quote"], "fill_jst": jst(fill["quote"]["time"]),
                           "fill_quote": fill["quote"], "latency_seconds": fill["quote"]["time"] - order["request_time"],
                           "later_accepted_rows": fill["quote"]["index"] - order["request_quote"]["index"],
                           "allocation": allocation})
    assert allocated_net == Decimal(str(position["realized_net"]))
    audit = position.get("protection117")
    protection = None
    if audit:
        names = ("first_activation", "first_narrowing", "first_floor_update", "last_floor_update",
                 "first_floor_hit", "first_all_reserved_hit", "last")
        protection = {name: point(audit.get(name)) for name in names}
        protection["initial_definition"] = audit["initial"].get("definition")
        protection["final_state"] = point({"snapshot": audit["final_state"]})["snapshot"]
        protection["evaluations"] = audit["evaluations"]
        protection["missing_quote"] = audit["missing_quote"]
    return {"session": session, "key": book["key"], "native": native,
            "position_id": position["id"], "source": position["source"],
            "side": position["side"], "initial_quantity": position["initial_quantity"],
            "entry_price": position["entry_price"], "entry_quote": position["entry_quote"],
            "entry_jst": jst(position["entry_quote"]["time"]), "whole_peak": point(peak),
            "final_realized_net": position["realized_net"],
            "decrease_yen": peak["whole_net"] - position["realized_net"],
            "closed_quote": position["closed_quote"], "closed_jst": jst(position["closed_quote"]["time"]),
            "first_whole_positive": point(marks.get("first_whole_positive")),
            "first_whole_negative_after": point(marks.get("first_whole_negative_after")),
            "last_mark": point(marks.get("last")), "atr": position.get("atr"),
            "protection_active": position["protection_active"], "protection": protection,
            "orders": [{**o, "request_jst": jst(o["request_time"])} for o in orders],
            "close_allocations": events}


def execute(completion_path: Path, output: Path) -> dict:
    """
    機能: 許可済み完了台帳のNative70だけを認証し、各20候補の上位3実建玉を抽出する。
    引数: completion_path(Path)は固定台帳、output(Path)は未作成JSON先。
    返り値: dictは計60件以下の保存極値診断。Rawや価格CSVを開かない。
    """
    if output.exists():
        raise ValueError("既存出力への上書きは禁止")
    payload = completion_path.read_bytes()
    assert sha256(payload) == EXPECTED_COMPLETION
    completion = json.loads(payload)
    assert completion["success"] and completion["trial"] == 117 and completion["sessions"] == 70
    assert completion["books"] == 1400 and completion["unchanged"]
    assert completion["all_reference112_equal"] and completion["all_source111_equal"]
    best: dict[str, list[dict]] = {}
    counts: dict[str, dict] = {}
    refs = []
    for row in completion["results"]:
        ref = row["native"]
        path = Path(ref["path"])
        if not path.is_absolute():
            path = completion_path.parent / path
        raw = path.read_bytes()
        assert sha256(raw) == ref["sha256"]
        scene = json.loads(gzip.decompress(raw))
        assert scene["trial"] == 117
        books = scene["actual"]["books"]
        assert len(books) == 20
        refs.append({"session": row["session"], **ref})
        for key, book in books.items():
            stats = counts.setdefault(key, {"positions": 0, "positive_peak_positions": 0})
            target = best.setdefault(key, [])
            for position in book["positions"]:
                stats["positions"] += 1
                peak = position.get("marks", {}).get("whole_max")
                if peak is None or peak["whole_net"] <= 0:
                    continue
                stats["positive_peak_positions"] += 1
                difference = peak["whole_net"] - position["realized_net"]
                if len(target) >= 3 and difference <= target[-1]["decrease_yen"]:
                    continue
                target.append(detail(book, position, ref, row["session"]))
                target.sort(key=lambda v: (-v["decrease_yen"], v["session"], v["position_id"]))
                del target[3:]
        assert sha256(path.read_bytes()) == ref["sha256"]
    assert len(refs) == len({r["session"] for r in refs}) == 70
    assert sha256(completion_path.read_bytes()) == EXPECTED_COMPLETION
    result = {"試行": 117, "成功": True, "金融再実行": False, "原板読取": False,
              "価格CSV読取": False, "11月09読取": False, "退出後価格参照": False,
              "定義": "保存marks.whole_max.whole_net>0の実建玉について、同一実Positionの最終realized_netを引く。whole_maxは部分返済Rを含む。",
              "限界": "元Actorが受理原行で更新した保存極値の診断。原板で最大点/初回性を独立再計算しない。最大値同値は元Actorの先着点。",
              "completion": {"path": str(completion_path.resolve()), "sha256": EXPECTED_COMPLETION},
              "Native70": refs, "件数": counts, "政策費用別上位3": best,
              "全20最大": max((v for values in best.values() for v in values), key=lambda v: v["decrease_yen"]),
              "コード": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).read_bytes())}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def main() -> None:
    """
    機能: 固定台帳と新規出力を指定して記述診断だけを実行する。
    引数: なし。CLIの--completion/--outputでPathを受ける。
    返り値: None。短い結果所在と最大差だけを表示する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--completion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.completion, args.output)
    largest = result["全20最大"]
    print(json.dumps({"output": str(args.output), "sha256": sha256(args.output.read_bytes()),
                      "最大": {k: largest[k] for k in ("session", "key", "position_id", "decrease_yen", "final_realized_net")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
