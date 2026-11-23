"""Viewerの手法別表示と独立会計を照合し、機械選択した代表図だけを保存する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))


def sha256(path: Path) -> str:
    """
    機能: ファイルの内容をSHA256で識別する。
    引数: path (Path) は対象。
    返り値: str は16進ハッシュ。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url: str) -> tuple[bytes, dict[str, str]]:
    """
    機能: ローカルViewerの応答を改変せず取得する。
    引数: url (str) はメタ情報・数値・画像のURL。
    返り値: tuple[bytes, dict[str, str]] は本文と小文字化したHTTPヘッダ。
    """
    with urlopen(url, timeout=120) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def expected_fills(path: Path, method: str) -> tuple[list[tuple[int, dict]], int]:
    """
    機能: merged約定を最初の新規手法に帰属させ、対応する返済まで抽出する。
    引数: path (Path) はmerged JSONL、method (str) は新規手法ID。
    返り値: tuple[list[tuple[int, dict]], int] は物理行付き対象約定と全約定片数。
    """
    rows = [(line, json.loads(raw)) for line, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if raw.strip()]
    owners = {}
    for _, row in rows:
        if row["type"] in ("LongN", "ShortN"):
            owners.setdefault(row["position_id"], row.get("method_id", ""))
    return [(line, row) for line, row in rows if owners.get(row["position_id"]) == method], len(rows)


def ledger(fills: list[tuple[int, dict]], point_value: float) -> dict[str, Any]:
    """
    機能: 明示建玉IDと手数料からViewerに依存しない会計を復元する。
    引数: fills (list[tuple[int, dict]]) は抽出片、point_value (float) は1枚1価格単位の円。
    返り値: dict[str, Any] は現金損益・残建玉・返済片数。
    """
    positions = {}
    cash = 0.0
    exits = 0
    for _, row in fills:
        kind, qty, price = row["type"], row["qty"], row["price"]
        side = 1 if kind.startswith("Long") else -1
        identity = row["position_id"]
        cash -= row.get("fee_yen", 0)
        if kind.endswith("N"):
            current = positions.setdefault(identity, {"side": side, "qty": 0, "average": 0.0})
            if current["side"] != side:
                raise AssertionError("建玉方向が混在しています")
            current["average"] = (current["average"] * current["qty"] + price * qty) / (current["qty"] + qty)
            current["qty"] += qty
        elif kind.endswith("R"):
            current = positions[identity]
            if current["side"] != side or current["qty"] < qty:
                raise AssertionError("返済対象の方向または数量が不正です")
            cash += side * (price - current["average"]) * qty * point_value
            current["qty"] -= qty
            exits += 1
        else:
            raise AssertionError(f"この試行に想定しない約定種別: {kind}")
    return {"cash": cash, "long_qty": sum(row["qty"] for row in positions.values() if row["side"] == 1),
            "short_qty": sum(row["qty"] for row in positions.values() if row["side"] == -1), "exit_fragments": exits}


def check_one(base: str, trial: Path, row: dict, resource: dict, reason: str, image: bool) -> dict[str, Any]:
    """
    機能: 一資源の数値・約定・指紋を照合し、指定時だけPNGを保存する。
    引数: base (str) は接続先、trial (Path) は試行、row/resource (dict) は集計と一覧、
    reason (str) は機械選択理由、image (bool) はPNG保存の有無。
    返り値: dict[str, Any] は照合した損益・数量・指紋・保存先。
    """
    params = {"catalog_path": (trial / "一覧.resources.json").relative_to(ROOT).as_posix(),
              "resource": resource["id"], "interval": "5", "price": "last", "width": 1600, "height": 1200}
    meta_body, _ = fetch(base + "/api/chart?" + urlencode(params))
    meta = json.loads(meta_body)
    data_body, data_headers = fetch(urljoin(base + "/", meta["data_url"]))
    data = json.loads(data_body)
    fingerprint = meta["data_sha256"]
    assert hashlib.sha256(data_body).hexdigest() == fingerprint, "数値本文の指紋が不一致"
    assert data_headers.get("x-chart-data-sha256") == fingerprint, "数値ヘッダの指紋が不一致"
    merged_path = trial / resource["pnl_path"]
    fills, merged_count = expected_fills(merged_path, resource["entry_method_id"])
    independent = ledger(fills, resource["point_value"])
    expected_cash = float(row["純損益円"])
    assert math.isclose(independent["cash"], expected_cash, abs_tol=1e-8), "独立会計と集計が不一致"
    assert independent["exit_fragments"] == int(row["取引数"]), "返済数と取引数が不一致"
    api_summary = data["summary"]
    assert math.isclose(api_summary["realized_pnl_yen"], expected_cash, abs_tol=1e-8), "APIの損益が不一致"
    assert api_summary == meta["summary"], "メタと数値の最終状態が不一致"
    assert api_summary["long_qty"] == independent["long_qty"] == 0, "買い残数が不一致"
    assert api_summary["short_qty"] == independent["short_qty"] == 0, "売り残数が不一致"
    assert api_summary["unrealized_pnl_yen"] == 0, "終了含みが0ではありません"
    assert len(data["events"]) == len(fills), "手法別の約定片数が不一致"
    for (line, fill), event in zip(fills, data["events"]):
        assert event["sequence"] == line, "merged物理行とAPI連番が不一致"
        assert event["type"] == fill["type"] and event["qty"] == fill["qty"], "約定方向・数量が不一致"
        assert event["position_id"] == fill["position_id"], "帰属建玉が不一致"
        assert event["method_id"] == fill.get("method_id", ""), "手法IDが不一致"
        assert math.isclose(event["price"], fill["price"], abs_tol=1e-8), "価格が不一致"
        expected_ms = datetime.fromisoformat(fill["timestamp"]).timestamp() * 1000
        assert math.isclose(event["timestamp_ms"], expected_ms, abs_tol=0.001), "約定時計が不一致"
    api_resource = data["resource"]
    assert api_resource["entry_method_id"] == resource["entry_method_id"], "帰属フィルターが不一致"
    assert api_resource["point_value"] == resource["point_value"], "倍率が不一致"
    assert Path(data["files"]["pnl"]).resolve() == merged_path.resolve(), "約定の出所が不一致"
    image_path = image_hash = image_header = None
    if image:
        png, png_headers = fetch(urljoin(base + "/", meta["png_url"]))
        assert png.startswith(b"\x89PNG\r\n\x1a\n"), "PNGではありません"
        image_header = png_headers.get("x-chart-data-sha256")
        assert image_header == fingerprint, "画像と数値の指紋が不一致"
        destination = trial / "図" / f"{row['銘柄']}_{reason}_{row['場']}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(png)
        image_path, image_hash = destination.relative_to(trial).as_posix(), hashlib.sha256(png).hexdigest()
    return {"選択理由": reason, "資源ID": resource["id"], "銘柄": row["銘柄"], "場": row["場"], "手法": row["手法"],
            "研究側純損益円": expected_cash, "独立会計": independent, "API最終状態": api_summary,
            "merged全約定片数": merged_count, "帰属手法の約定片数": len(fills), "API約定片数": len(data["events"]),
            "約定ファイル": merged_path.relative_to(trial).as_posix(), "約定SHA256": sha256(merged_path),
            "数値SHA256": fingerprint, "数値本文SHA256一致": True,
            "数値ヘッダSHA256": data_headers.get("x-chart-data-sha256"), "画像ヘッダSHA256": image_header,
            "PNG": image_path, "PNGSHA256": image_hash, "表示範囲": meta["range"], "品質": data["quality"],
            "出所": data["files"], "一致": True}


def select_resources(rows: list[dict], method: str, selection: str) -> list[tuple[dict, str, bool]]:
    """
    機能: 既存の利益・損失各場選択または最大絶対損益場と同場の別手法を選ぶ。
    引数: rows (list[dict]) は場別集計、method (str) は代表手法、selection (str) は選択方式。
    返り値: list[tuple[dict, str, bool]] は行・選択理由・PNG保存の有無。
    """
    selected = []
    for symbol in ("NK225", "TOPIX"):
        candidates = sorted([row for row in rows if row["銘柄"] == symbol and row["手法"] == method], key=lambda row: row["場"])
        if not candidates:
            raise ValueError(f"代表手法の資源がありません: {symbol} {method}")
        if selection == "extrema":
            for reason, select in (("最大利益場", max), ("最大損失場", min)):
                selected.append((select(candidates, key=lambda row: float(row["純損益円"])), reason, True))
        elif selection == "max-absolute":
            row = max(candidates, key=lambda row: abs(float(row["純損益円"])))
            selected.append((row, "最大絶対損益場", True))
            comparisons = sorted([other for other in rows if other["銘柄"] == symbol and other["場"] == row["場"]
                                  and other["手法"] != method], key=lambda other: other["手法"])
            selected.extend((other, "同場の別決済条件", False) for other in comparisons)
        else:
            raise ValueError(f"未知の選択方式: {selection}")
    return selected


def run(trial: Path, base: str, baseline: str = "基準", selection: str = "extrema") -> None:
    """
    機能: 指定方式で代表資源を選び、画像と独立会計・APIの照合JSONを作る。
    引数: trial (Path) は試行、base (str) は接続先、baseline (str) は代表手法、selection (str) は選択方式。
    返り値: None。既定は従来の4画像と無取引資源。max-absoluteは2画像と同場の他手法数値。
    """
    with (trial / "セッション集計.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    catalog_path = trial / "一覧.resources.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    resources = {(resource["symbol"], resource["session"], resource["entry_method_id"]): resource for resource in catalog["resources"]}
    list_query = urlencode({"catalog_path": catalog_path.relative_to(ROOT).as_posix()})
    listed_body, _ = fetch(base + "/api/resources?" + list_query)
    listed = json.loads(listed_body)["resources"]
    assert {resource["id"] for resource in listed} == {resource["id"] for resource in catalog["resources"]}, "API資源一覧が不一致"
    checks = []
    for row, reason, image in select_resources(rows, baseline, selection):
        resource = resources[(row["銘柄"], row["場"], row["手法"])]
        checks.append(check_one(base, trial, row, resource, reason, image))
        print(json.dumps({key: checks[-1][key] for key in ("資源ID", "研究側純損益円", "API約定片数", "一致")}, ensure_ascii=False), flush=True)
    # ----------------------------------------
    # mergedファイルに他手法の約定があるのに対象手法は0という資源を優先する。
    total_by_session = Counter()
    total_by_method = Counter()
    for row in rows:
        total_by_session[(row["銘柄"], row["場"])] += int(row["取引数"])
        total_by_method[row["手法"]] += int(row["取引数"])
    empty = [row for row in rows if int(row["取引数"]) == 0]
    if empty and selection == "extrema":
        row = sorted(empty, key=lambda row: (-total_by_session[(row["銘柄"], row["場"])], row["銘柄"], row["場"], row["手法"]))[0]
        checks.append(check_one(base, trial, row, resources[(row["銘柄"], row["場"], row["手法"])], "無取引手法の帰属分離", False))
    info_body, _ = fetch(base + "/api/info")
    binary = ROOT / "work" / "viewer" / "session-trade-viewer.exe"
    payload = {"確認日時": datetime.now(JST).isoformat(), "接続先": base, "API情報": json.loads(info_body),
               "カタログ": catalog_path.relative_to(ROOT).as_posix(), "カタログSHA256": sha256(catalog_path),
               "API資源数": len(listed), "全期間で無取引の候補": [method for method, count in total_by_method.items() if count == 0],
               "選択手法": baseline, "選択方式": selection,
               "選択規則": ("各指数の指定手法で最大利益/最大損失の場。無取引資源は他手法の取引が多い場を優先。" if selection == "extrema" else
                            "各指数の指定手法で最大絶対損益の場を画像化し、同場の他手法は数値だけ照合。") + "同値は開始日順の先頭。",
               "Viewer実行コピー": str(binary), "Viewer実行コピーSHA256": sha256(binary) if binary.exists() else None,
               "表示設定": {"interval": "5", "price": "last", "width": 1600, "height": 1200},
               "照合": checks, "注意": "研究損益を画像表示から再算出していない。図は表示・会計の代表確認用で、選択した場を収益性の証拠にしない。"}
    (trial / "Viewer照合.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="指定手法の代表場とmerged約定の帰属をViewerで照合する")
    parser.add_argument("--study-root", type=Path, default=ROOT / "study" / "00002_複数時間足と四系統の要因比較")
    parser.add_argument("--api-base", default="http://127.0.0.1:8092")
    parser.add_argument("--method", "--baseline", dest="method", default="基準")
    parser.add_argument("--selection", choices=("extrema", "max-absolute"), default="extrema")
    arguments = parser.parse_args()
    run(arguments.study_root.resolve(), arguments.api_base.rstrip("/"), arguments.method, arguments.selection)
