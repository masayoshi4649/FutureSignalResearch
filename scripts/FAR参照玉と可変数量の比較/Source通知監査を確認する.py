"""87 Source通知監査をGoの手製原板人工と数値手計算で反証する。

既存Go、元人工、実市場を変更又は再生しない。明示workへ原板人工だけを
一時gzip化し、正常・意図破損を同じinspect_oneに通す。
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def load(path: Path) -> object:
    """
    機能: 明示された通知監査Pythonだけを別名で読む。
    引数: path (Path) は新監査コード。
    返り値: object はinspect_one等の監査API。
    """
    spec = importlib.util.spec_from_file_location("source87_notice_art", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    """
    機能: 人工・監査コードのbyte不変を確認する。
    引数: path (Path) は既存ファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(folder: Path, target: Path) -> tuple:
    """
    機能: Go人工の全物理行を時計欠測・Last不良・badBBOごとgzipへ写す。
    引数: folder/target (Path) は明示人工根と一時作業先。
    返り値: tuple は入力台帳と未変更の87保存値の複写。
    """
    rows = json.loads((folder / "raw_quotes.json").read_text(encoding="utf-8"))
    market = target / "book.jsonl.gz"
    with gzip.open(market, "wt", encoding="utf-8", newline="\n") as stream:
        for line, item in enumerate(rows, 1):
            q = item["quote"]
            assert q["line"] == line
            row = {"Symbol": "人工限月"}
            if not item["clock_missing"]:
                row.update(CurrentPriceTime=datetime.fromtimestamp(q["time"], timezone.utc).isoformat(), CurrentPrice=q["last"])
                for n in range(1, 11):
                    row[f"Buy{n}"] = {"Price": q["bid"] - 10 * (n - 1), "Qty": 100}
                    row[f"Sell{n}"] = {"Price": q["ask"] + 10 * (n - 1), "Qty": 100}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    saved = json.loads((folder / "87.json").read_text(encoding="utf-8"))
    entry = {"id": saved["session"], "files": {"NK225_book": {"path": market.name, "size": market.stat().st_size, "sha256": sha(market)}}}
    return entry, saved


def inspect(module: object, target: Path, entry: dict, saved: dict) -> dict:
    """
    機能: 変更可能な人工複写だけを正式inspect_oneへ渡す。
    引数: module (object)、target (Path)、entry/saved (dict) は監査と人工。
    返り値: dict は差分数を含む一場監査。
    """
    (target / (entry["id"] + ".json")).write_text(json.dumps(saved, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return module.inspect_one((str(target), str(target), entry))


def mutate(saved: dict, label: str) -> dict:
    """
    機能: 1つの通知・効果・注文だけを故意に壊す。
    引数: saved (dict)、label (str) は正常人工と反証名。
    返り値: dict は新しい破損複写。
    """
    broken = deepcopy(saved)
    event = broken["source_events"][0]
    book = broken["books"]["R0G1_D0"]
    effect = book["source_effects"][0]
    if label == "源Indexと実Index混同":
        event["source_index"] = event["quote"]["index"]
    elif label == "源時計偽装":
        event["source_at"] -= 1
    elif label == "源物理行偽装":
        event["source_line"] -= 1
    elif label == "実Index偽装":
        event["quote"]["index"] += 1
    elif label == "有効気配偽装":
        event["quote"]["valid"] = not event["quote"]["valid"]
    elif label == "源BBO偽装":
        event["quote"]["bid"] -= 10
    elif label == "要求時計巻戻し":
        event["at"] -= 1
    elif label == "quoteとtimer混同":
        event["origin"] = "timer" if event["origin"] == "quote" else "quote"
    elif label == "未生成手法の通知":
        event["method"] = "NK225_P164_06"
    elif label == "Close比率bool偽装":
        event["closes"][0]["quantity"] = True
    elif label == "Close分母ゼロ":
        event["closes"][0]["before"] = 0
    elif label == "Close通知重複":
        event["closes"].append(deepcopy(event["closes"][0]))
    elif label == "0作用を含む効果欠落":
        book["source_effects"].pop(0)
    elif label == "効果重複":
        book["source_effects"].append(deepcopy(effect))
    elif label == "取消枚数偽装":
        effect["cancelled"] += 1
    elif label == "未予約枚数偽装":
        effect["unreserved_before"] += 1
    elif label == "prefix件数偽装":
        effect["orders_before_count"] += 1
    elif label == "効果通知段階偽装":
        effect["origin"] = "timer" if effect["origin"] == "quote" else "quote"
    elif label == "通知作用比率偽装":
        effect["quantity"] += 1
    elif label == "同原行の架空約定":
        book["orders"][0]["fill_line"] = book["orders"][0]["request_line"]
    elif label == "最終未解消偽装":
        book["unresolved"] = not book["unresolved"]
    elif label == "孤立未計測注文":
        orphan = deepcopy(book["orders"][0])
        orphan.update(id=f"{broken['session']}_S0G1_O{len(book['orders']) + 1:06d}", kind="exit", reason="参照返済:孤立", status="cancelled", filled_quantity=0, cancelled_quantity=orphan["quantity"], remaining=0, fill_time=None, fill_price=None, fill_line=0)
        book["orders"].append(orphan)
    else:
        raise ValueError("未知の破損人工:" + label)
    return broken


def hand_cases(module: object) -> list:
    """
    機能: 小整数の手計算で0丸め・部分取消・全残・予約先行を検査する。
    引数: module (object) は新監査API。
    返り値: list は数値を明示した手計算の証拠。
    """
    output = []
    for free, qty, before, expected in ((0, 5, 17, 0), (1, 1, 17, 0), (7, 5, 17, 2), (17, 5, 17, 5), (12, 1, 100, 0), (3, 17, 17, 3), (100, 33, 100, 33)):
        assert module.proportion(free, qty, before) == expected
        output.append({"計算": "未予約量の整数比率", "未予約": free, "源数量": qty, "源残量": before, "期待作用": expected})

    def order(n: int, quantity: int, kind: str = "entry", reason: str = "FAR参照の初参加要求") -> dict:
        """
        機能: 手計算に必要な最小保存注文を作る。
        引数: n/quantity (int)、kind/reason (str) は連番・量・種別・理由。
        返り値: dict は架空時計の小型注文。
        """
        return {"id": f"手計算_S0G1_O{n:06d}", "kind": kind, "reference_id": "参照", "position_id": "玉", "side": 1, "quantity": quantity, "remaining": 0, "filled_quantity": quantity, "cancelled_quantity": 0, "request_time": float(n), "request_index": n - 1, "request_line": n, "fill_line": n + 1, "reason": reason, "status": "filled", "harvest": False, "source_entry": {"snapshot_method": "NK225_D164_15"}}

    def quote(at: float, index: int) -> dict:
        """
        機能: 架空の正常原行を作る。
        引数: at (float)、index (int) は時計と実連番。
        返り値: dict は小型気配。
        """
        return {"time": float(at), "index": index, "line": index + 1, "last": 1000.0, "bid": 990.0, "ask": 1000.0, "valid": True}

    def event(q: dict, qty: int, before: int, name: str) -> dict:
        """
        機能: 作用だけを手計算する架空通知を作る。
        引数: q (dict)、qty/before (int)、name (str) は気配・比率・識別。
        返り値: dict はSourceイベント。
        """
        return {"at": q["time"], "quote": q, "origin": "quote", "method": "NK225_D164_15", "closes": [{"id": name, "reference_id": "参照", "before": before, "quantity": qty, "reason": name}]}

    def effect(e: dict, pending: int, cancelled: int, free: int, requested: int, after: int, order_id: str, count0: int, count1: int) -> dict:
        """
        機能: 期待する作用台帳を手の数値から組み立てる。
        引数: e (dict)、各量/count (int)、order_id (str) は手計算の定数。
        返り値: dict は期待18字段。
        """
        c, q = e["closes"][0], e["quote"]
        return {"id": c["id"], "reference_id": "参照", "at": e["at"], "quote_time": q["time"], "quote_index": q["index"], "quote_line": q["line"], "origin": "quote", "before": c["before"], "quantity": c["quantity"], "reason": c["reason"], "pending_before": pending, "cancelled": cancelled, "unreserved_before": free, "exit_requested": requested, "unreserved_after": after, "exit_order_id": order_id, "orders_before_count": count0, "orders_after_count": count1}

    base = {"mode": "S0G1", "session": "手計算", "source_policy": "S", "hold_enabled": False, "confirm_enabled": False, "side_cap": 100, "fill_delay_seconds": 1}
    # ----------------------------------------
    # 17の未約定を5だけ取消し、残12を1/100では切り捨て0、後原行だけで12を取得する。
    e1, e2 = event(quote(1.5, 1), 5, 17, "部分取消"), event(quote(1.6, 2), 1, 100, "切捨て0")
    b = module.Ownership("R0G1_D1", {**base, "orders": [order(1, 17)], "source_effects": [effect(e1, 17, 5, 0, 0, 0, "", 1, 1), effect(e2, 12, 0, 0, 0, 0, "", 1, 1)]}, "手計算", module.BASE.Audit())
    b.take("entry", "参照", "玉", 1, 17, 1.0, quote(0.9, 0), "FAR参照の初参加要求")
    b.source(e1)
    b.source(e2)
    assert b.created[0]["remaining"] == 12 and b.created[0]["cancelled"] == 5 and not b.lots
    b.fill(quote(2.0, 3))
    assert b.lots["参照"]["quantity"] == 12 and b.created[0]["filled"] == 12
    assert b.audit.errors == 0
    output.append({"計算": "未約定17の部分取消5→0丸め→後原行fill12", "取消": 5, "実初期量": 12, "通知数": 2})

    # ----------------------------------------
    # 実7のうち旧保護予約4なら、Sourceは3だけを見る。5/17では0、全残では3。
    o1, o2, o3 = order(1, 7), order(2, 4, "exit", "旧保護"), order(3, 3, "exit", "参照返済:全残")
    o3.update(request_index=3, request_line=4)
    e3, e4 = event(quote(2.1, 2), 5, 17, "切捨て0"), event(quote(3.0, 3), 17, 17, "全残")
    b = module.Ownership("R0G1_D1", {**base, "orders": [o1, o2, o3], "source_effects": [effect(e3, 0, 0, 3, 0, 3, "", 2, 2), effect(e4, 0, 0, 3, 3, 0, "手計算_S0G1_O000003", 2, 3)]}, "手計算", module.BASE.Audit())
    b.take("entry", "参照", "玉", 1, 7, 1.0, quote(0.9, 0), "FAR参照の初参加要求")
    b.fill(quote(2.0, 1))
    b.take("exit", "参照", "玉", 1, 4, 2.0, quote(2.0, 1), "旧保護")
    b.source(e3)
    b.source(e4)
    assert b.lots["参照"]["quantity"] == 7 and b.lots["参照"]["reserved"] == 7
    assert b.audit.errors == 0
    output.append({"計算": "実7・既予約4→Source未予約3だけにfloor0/全残3", "既予約": 4, "新Source予約": 3, "合計予約": 7})
    return output


def main() -> None:
    """
    機能: 全Go手製場面と23種類の破損、手計算境界を実行し証拠を新規保存する。
    引数: --fixtures/--work/--out (Path) は人工根・一時領域・小型証拠先。
    返り値: None。見逃し・変更・計算差は非0終了する。
    """
    parser = argparse.ArgumentParser()
    for name in ("fixtures", "work", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists() and args.work.is_dir()
    code = Path(__file__).resolve().parent / "Source通知監査.py"
    module = load(code)
    before = {str(p.resolve()): sha(p) for p in args.fixtures.rglob("*.json")}
    stopped = Path(__file__).resolve().parent
    go_before = {str(p.resolve()): sha(p) for p in stopped.glob("*.go")}
    normal, rejected = [], []
    labels = ("源Indexと実Index混同", "源時計偽装", "源物理行偽装", "実Index偽装", "有効気配偽装", "源BBO偽装", "要求時計巻戻し", "quoteとtimer混同", "未生成手法の通知", "Close比率bool偽装", "Close分母ゼロ", "Close通知重複", "0作用を含む効果欠落", "効果重複", "取消枚数偽装", "未予約枚数偽装", "prefix件数偽装", "効果通知段階偽装", "通知作用比率偽装", "同原行の架空約定", "最終未解消偽装", "孤立未計測注文")
    for folder in sorted(p for p in args.fixtures.iterdir() if p.is_dir()):
        with tempfile.TemporaryDirectory(dir=args.work) as temporary:
            target = Path(temporary)
            entry, saved = materialize(folder, target)
            row = inspect(module, target, entry, saved)
            assert row["不一致数"] == 0 and row["入力前後不変"], (folder.name, row["不一致"])
            normal.append({"場面": folder.name, **row})
            for label in labels:
                try:
                    broken = inspect(module, target, entry, mutate(saved, label))
                    detected, kind = broken["不一致数"] > 0, "保存差分"
                except (ValueError, KeyError, IndexError):
                    detected, kind = True, "構造不正の非0停止"
                assert detected, (folder.name, label)
                rejected.append({"場面": folder.name, "破損": label, "検出": True, "種別": kind})
            broken = deepcopy(saved)
            last_bad = next(item["quote"] for item in json.loads((folder / "raw_quotes.json").read_text(encoding="utf-8")) if item["accepted"] and item["quote"]["last"] <= 0)
            broken["source_events"][0].update(quote=last_bad, at=last_bad["time"], origin="quote", source_at=last_bad["time"], source_line=last_bad["line"])
            try:
                result = inspect(module, target, entry, broken)
                detected = result["不一致数"] > 0
            except (ValueError, KeyError, IndexError):
                detected = True
            assert detected, (folder.name, "Last不良行でSourceStep")
            rejected.append({"場面": folder.name, "破損": "Last不良行でSourceStep", "検出": True, "種別": "保存差分又は構造不正"})
    hand = hand_cases(module)
    assert before == {str(p.resolve()): sha(p) for p in args.fixtures.rglob("*.json")}
    assert go_before == {str(p.resolve()): sha(p) for p in stopped.glob("*.go")}
    output = {"成功": True, "正常場面": len(normal), "正常会計": sum(r["会計数"] for r in normal), "照合項目数": sum(r["照合項目数"] for r in normal), "Source効果数": sum(r["Source効果数"] for r in normal), "破損反証": len(rejected), "手計算": len(hand), "入力前後不変": True, "停止Go前後不変": True,
        "監査コードSHA256": sha(code), "人工確認コードSHA256": sha(Path(__file__)), "固定80監査SHA256": module.HELPER_SHA, "人工入力SHA256": before, "停止GoSHA256": go_before, "新市場再生": 0,
        "限定": "手製Source前史・fake driverの通知を物理行へ接続する人工。Source通知をFAR戦略から自然発生させる証拠ではない。", "限界": module.LIMITS, "正常": normal, "反証": rejected, "手計算結果": hand}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: output[k] for k in ("成功", "正常場面", "正常会計", "照合項目数", "Source効果数", "破損反証", "手計算")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
