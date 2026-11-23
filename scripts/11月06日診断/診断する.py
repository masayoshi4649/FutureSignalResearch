"""固定済みの試行107を読み、11月06日の実保有と退出を記述する。"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "study/00107_見送り明けの初回取得と利益保護"
OUT = ROOT / "work/11月06日の退出診断"
OUT.mkdir(parents=True, exist_ok=True)
JST = dt.timezone(dt.timedelta(hours=9))


def read_json(path: Path) -> dict:
    """
    機能: UTF-8のJSONまたは圧縮JSONを読み込む。
    引数: path (Path): 入力ファイル。
    返り値: dict: 入力文書。
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ref(path: Path) -> dict:
    """
    機能: 入力の相対パスと指紋を記録する。
    引数: path (Path): 検査対象。
    返り値: dict: パス・SHA256・バイト数。
    """
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def when(value: float | None) -> str | None:
    """
    機能: エポック秒を日本時間のISO表記へ変換する。
    引数: value (float | None): エポック秒または未観測。
    返り値: str | None: 日時または未観測。
    """
    return dt.datetime.fromtimestamp(value, JST).isoformat() if value is not None else None


def point(value: dict | None) -> dict | None:
    """
    機能: 保有中の保存済み観測を必要な数値へ射影する。
    引数: value (dict | None): 保存された観測点。
    返り値: dict | None: 時刻・価格・費用後評価等。
    """
    if value is None:
        return None
    return {"日時": when(value["quote"]["time"]), "参照行": value["quote"]["source_line"],
            **{k: value[k] for k in ("phase", "quantity", "reserved", "mark_price", "gain_points", "unit_net", "realized_net", "whole_net")}}


def project_position(position: dict, book: dict, width: dict, early: dict) -> dict:
    """
    機能: 一つの実保有の新規・返済・保護状態を記述し、約定配賦と照合する。
    引数: position (dict): 実建玉。book (dict): 所属会計。width (dict): 幅監査。early (dict): 起動監査。
    返り値: dict: 実建玉の記述。
    """
    closes = [f for f in book["fills"] if f["position_id"] == position["id"] and f["action"] == "close"]
    allocations = [a for f in closes for a in f["allocations"] if a["position_id"] == position["id"]]
    assert sum(a["net_yen"] for a in allocations) == position["realized_net"]
    assert sum(a["quantity"] for a in allocations) == position["initial_quantity"]
    assert not position["quantity"] and not position["reserved"]
    width_position = next((x for x in width.get("positions", []) if x["position_id"] == position["id"]), None)
    early_position = next((x for x in early.get("positions", []) if x["position_id"] == position["id"]), None)
    marks = position["marks"]
    return {
        "建玉ID": position["id"], "Source信号ID": position["source"]["signal_id"],
        "Source種類": position["source"]["kind"], "方向": "買い" if position["side"] == 1 else "売り",
        "枚数": position["initial_quantity"], "出生日時": when(position["source"]["birth_time"]),
        "新規日時": when(position["entry_quote"]["time"]), "新規価格": position["entry_price"],
        "最終返済日時": when(position["closed_quote"]["time"]), "費用後損益円": position["realized_net"],
        "保護起動": position["protection_active"], "取得ATRpt": position["atr"]["value"] if position["atr"] else None,
        "取得時通常幅pt": position["atr"]["width"] if position["atr"] else None,
        "最終保護床pt": position["floor_gain"], "最初の費用後単位利益": point(marks.get("first_unit_positive")),
        "最初の費用後単位利益後赤字": point(marks.get("first_unit_negative_after")),
        "保護起動点": point(position.get("activation")), "最初の床到達点": point(position.get("first_floor_hit")),
        "実保有観測で通常起動金額に到達": (marks["unit_max"]["unit_net"] >= 100 * max(10, position["atr"]["value"])) if position["atr"] else None,
        "実保有観測で半ATR起動金額に到達": (marks["unit_max"]["unit_net"] >= 100 * max(10, .5 * position["atr"]["value"])) if position["atr"] else None,
        "幅縮小点": point(width_position.get("first_narrow")) if width_position else None,
        "幅縮小時観測": width_position.get("first_narrow_observation") if width_position else None,
        "早期起動種類": early_position.get("trigger") if early_position else None,
        "実返済": [{"日時": when(f["quote"]["time"]), "枚数": f["quantity"], "価格": f["price"],
                     "理由": f["reason"], "費用後配賦円": sum(a["net_yen"] for a in f["allocations"]),
                     "参照行": f["quote"]["source_line"]} for f in closes]
    }


def main() -> None:
    """
    機能: 11月06日48会計の数値を照合し、主6候補の実建玉を診断用JSONへ保存する。
    引数: なし。
    返り値: None。
    """
    summary_path = TRIAL / "成果物/結果.json"
    index_path = TRIAL / "成果物_金融/Native参照台帳.json"
    summary, index = read_json(summary_path), read_json(index_path)
    sources = [ref(summary_path), ref(index_path)]
    rows, primary, checks = [], [], []
    for kind in ("Day", "Night"):
        session = f"2026-11-06_{kind}"
        item = next(x for x in index["Native"] if x["session"] == session)
        path = TRIAL / item["path"]
        record = ref(path)
        assert record["sha256"] == item["sha256"]
        sources.append(record)
        native = read_json(path)
        assert native["complete"] and native["tape_unchanged"]
        for key, book in native["books"].items():
            saved = next(x for x in summary["場別"] if x["session"] == session and x["key"] == key)
            assert book["complete"] and book["finished"] and not book["failure"]
            assert sum(f["net_contribution_yen"] for f in book["fills"]) == saved["net_yen"]
            assert sum(p["realized_net"] for p in book["positions"]) == saved["net_yen"]
            assert book["totals"]["net_yen"] == saved["net_yen"]
            for p in book["positions"]:
                closes = [f for f in book["fills"] if f["position_id"] == p["id"] and f["action"] == "close"]
                assert sum(a["net_yen"] for f in closes for a in f["allocations"]) == p["realized_net"]
            categories = Counter()
            amounts = Counter()
            for p in book["positions"]:
                if p["realized_net"] >= 0:
                    category = "費用後黒字または同値"
                elif p["protection_active"]:
                    category = "保護起動あり費用後赤字"
                elif p["marks"].get("first_unit_positive"):
                    category = "費用後利益観測あり起動前の赤字"
                else:
                    category = "費用後利益観測なし赤字"
                categories[category] += 1
                amounts[category] += p["realized_net"]
            rows.append({**{k: saved[k] for k in (
                "session", "key", "entry_quantity", "positions", "gross_yen", "fee_yen", "slip_yen", "net_yen",
                "unit_positive_closed_negative", "activated_closed_negative", "protection_activated_positions",
                "positive_yen", "negative_yen", "売買別", "活動主表")},
                "赤字の分類": {k: {"建玉数": categories[k], "実現円": amounts[k]} for k in categories}})
            checks.append({"session": session, "key": key, "約定純額和一致": True, "建玉純額和一致": True,
                           "配賦純額一致": True, "末尾保有と予約なし": all(not p["quantity"] and not p["reserved"] for p in book["positions"])})
            if key.endswith("_C0_D0"):
                primary.append({"session": session, "key": key, "実建玉": [project_position(
                    p, book, native["width_audits"][key], native["early_audits"].get(key, {})) for p in book["positions"]]})

    # ----------------------------------------
    matches = []
    for kind in ("Day", "Night"):
        session = f"2026-11-06_{kind}"
        base = next(x for x in primary if x["session"] == session and x["key"] == "B0_C0_D0")
        entry_signature = lambda item: [(p["Source信号ID"], p["方向"], p["枚数"], p["新規日時"], p["新規価格"]) for p in item["実建玉"]]
        for key in ("B1_C0_D0", "BE_C0_D0"):
            candidate = next(x for x in primary if x["session"] == session and x["key"] == key)
            assert entry_signature(base) == entry_signature(candidate)
            candidates = {p["Source信号ID"]: p for p in candidate["実建玉"]}
            differences = [{"新規日時": p["新規日時"], "方向": p["方向"], "枚数": p["枚数"],
                            "B0実現円": p["費用後損益円"], "比較実現円": candidates[p["Source信号ID"]]["費用後損益円"],
                            "差円": candidates[p["Source信号ID"]]["費用後損益円"] - p["費用後損益円"]}
                           for p in base["実建玉"] if candidates[p["Source信号ID"]]["費用後損益円"] != p["費用後損益円"]]
            matches.append({"session": session, "比較": key + "-B0_C0_D0", "入口完全一致": True, "実現差": differences})
    facts = {"対象": "試行107の2026-11-06 Day/Night", "金融再実行": False, "先読みの新規成績": False,
             "確認日": "2026-11-09", "出典": sources, "48会計": rows, "主C0D0実建玉": primary, "検算": checks,
             "主保護間の入口と実現比較": matches,
             "限界": ["記述的な既使用日の診断であり、新しいルールの効果は未検証。", "保有中に実観測した費用後評価と退出を扱い、未参加・退出後の仮想損益を評価しない。",
                      "C5は片道5ptの追加仮定、D1は価格時計1秒遅延であり実測通信遅延ではない。"]}
    (OUT / "事実.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"会計": len(rows), "主会計": len(primary), "主建玉": sum(len(x["実建玉"]) for x in primary), "検算成功": len(checks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
