"""約定だけから独立会計を作り、初回試行の集計と照合する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


# ----------------------------------------
# 入力の検査と、研究計算から独立した会計

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDY = ROOT / "study" / "00001_MACDと方向条件の比較"
EPSILON = Decimal("0.000001")


def ensure(condition: bool, message: str) -> None:
    """監査条件を満たさなければ処理対象の不合格を通知する。

    引数: condition (bool) は検査結果、message (str) は不合格理由。
    返り値: None。不合格の場合はValueErrorを送出する。
    """
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> Any:
    """数値の小数部分を十進数で読み込む。

    引数: path (Path) はUTF-8のJSONファイル。
    返り値: Any は解析した値。会計用の小数はDecimalとなる。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)


def amount(value: Any, label: str) -> Decimal:
    """有限の数値を独立会計用の十進数へ変換する。

    引数: value (Any) は数値又はCSVの数値文字列、label (str) は検査名。
    返り値: Decimal は有限数。不正値はValueErrorにする。
    """
    ensure(not isinstance(value, bool) and value is not None, f"{label}: 数値ではない")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label}: 数値ではない") from error
    ensure(result.is_finite(), f"{label}: 有限数ではない")
    return result


def positive_integer(value: Any, label: str) -> int:
    """JSONの正整数を検査する。

    引数: value (Any) は数量又は行番号、label (str) は検査名。
    返り値: int は正整数。真偽値と小数型は許可しない。
    """
    ensure(type(value) is int and value > 0, f"{label}: 正整数ではない")
    return value


def timestamp(value: Any) -> datetime:
    """時差付き約定時刻を日本時間へ正規化する。

    引数: value (Any) はISO形式の時刻文字列。
    返り値: datetime は日本時間の時刻。時差なしの値は拒否する。
    """
    ensure(isinstance(value, str) and bool(value), "約定時刻がない")
    result = datetime.fromisoformat(value)
    ensure(result.utcoffset() is not None, "約定時刻に時差がない")
    return result.astimezone(JST)


def bounds(session: str, settings: dict[str, Any]) -> tuple[datetime, datetime, datetime]:
    """試行で採用した連続売買時間と新規停止時刻を求める。

    引数: session (str) は開始日基準の場、settings (dict[str, Any]) は条件。
    返り値: tuple[datetime, datetime, datetime] は開始、ザラバ終了、新規停止。
    """
    ensure(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)", session)), "場名が不正")
    date_text, part = session.split("_")
    day = datetime.fromisoformat(date_text).date()
    finish_day = day if part == "Day" else day + timedelta(days=1)
    start = datetime.combine(day, time(8, 45) if part == "Day" else time(17), JST)
    end = datetime.combine(finish_day, time(15, 40) if part == "Day" else time(5, 55), JST)
    cutoff = datetime.combine(finish_day, time.fromisoformat(settings["新規停止"][part]), JST)
    return start, end, cutoff


@dataclass
class Holding:
    """所有建玉IDに対応する方向、未返済数量、取得価格を保持する。"""

    side: int
    quantity: int
    price: Decimal


def resource_key(resource: dict[str, Any]) -> tuple[str, str, str]:
    """資源と集計行を結び付ける三つの識別子を取り出す。

    引数: resource (dict[str, Any]) はViewerの資源。
    返り値: tuple[str, str, str] は銘柄、場、手法。
    """
    return str(resource["symbol"]), str(resource["session"]), str(resource["method_id"])


def audit_resource(
    folder: Path,
    resource: dict[str, Any],
    settings: dict[str, Any],
    session_row: dict[str, str],
    quality: dict[str, Any],
) -> dict[str, Any]:
    """一資源の約定列から独立会計を作り、セッション集計を照合する。

    引数: folder (Path) は出力ルート、resource (dict[str, Any]) は資源、
    settings (dict[str, Any]) は条件、session_row (dict[str, str]) は集計行、
    quality (dict[str, Any]) は原行数を記録した品質台帳行。
    返り値: dict[str, Any] は数量、費用、損益、入力ハッシュ等の監査結果。
    """
    symbol, session, method = resource_key(resource)
    product = settings["商品"][symbol]
    multiplier = amount(product["point_value"], "商品倍率")
    unit_fee = amount(product["fee_yen"], "片道手数料")
    tick = amount(product["tick"], "呼値")
    ensure(multiplier > 0 and tick > 0 and unit_fee >= 0, "商品仕様が不正")
    ensure(amount(resource["point_value"], "資源倍率") == multiplier, "資源倍率が条件と不一致")
    ensure(resource["product"] == product["product"], "執行商品が条件と不一致")
    ensure(method in settings["候補"], "未定義の手法")
    ensure(resource["pnl_format"] == "trades" and resource["pnl_basis"] == "net", "約定・純損益形式ではない")
    ensure((quality["銘柄"], quality["場"]) == (symbol, session), "品質台帳の対応が不正")
    max_line = positive_integer(quality["原行数"], "品質台帳の原行数")
    start, end, cutoff = bounds(session, settings)
    pnl_path = Path(resource["pnl_path"])
    ensure(not pnl_path.is_absolute(), "想定外の絶対約定パス")
    path = (folder / pnl_path).resolve()
    ensure(path.is_relative_to(folder.resolve()), "約定パスが試行フォルダ外")
    body = path.read_bytes()

    # ----------------------------------------
    # 時刻と所有IDを追跡し、値幅損益と全片の費用を別々に集計する。
    active: dict[str, Holding] = {}
    seen_positions: set[str] = set()
    seen_fills: set[str] = set()
    previous_time: datetime | None = None
    previous_line = 0
    entries = exits = completed = 0
    gross = Decimal(0)
    fees = Decimal(0)
    for row_no, text in enumerate(body.decode("utf-8-sig").splitlines(), 1):
        if not text.strip():
            continue
        try:
            fill = json.loads(text, parse_float=Decimal)
            fill_id = fill["id"]
            position_id = fill["position_id"]
            ensure(isinstance(fill_id, str) and bool(fill_id), "約定IDが空")
            ensure(fill_id not in seen_fills, "約定IDが重複")
            ensure(isinstance(position_id, str) and bool(position_id), "建玉IDが空")
            seen_fills.add(fill_id)
            ensure(fill["method_id"] == method, "約定の手法IDが資源と不一致")
            at = timestamp(fill["timestamp"])
            ensure(start <= at < end, "約定が試行の連続売買時間外")
            ensure(previous_time is None or at >= previous_time, "約定時刻が後退")
            source_line = positive_integer(fill["source_line"], "原板行")
            ensure(previous_line < source_line <= max_line, "原板行の順序又は上限が不正")
            quantity = positive_integer(fill["qty"], "数量")
            ensure(quantity == 1, "試行計画の固定1枚と不一致")
            price = amount(fill["price"], "約定価格")
            ensure(price > 0, "約定価格が非正")
            ensure(price % tick == 0, "約定価格が実行商品の呼値に不整合")
            fee = amount(fill["fee_yen"], "約定費用")
            ensure(fee == unit_fee * quantity, "約定費用が事前条件と不一致")
            kind = fill["type"]
            ensure(kind in {"LongN", "ShortN", "LongR", "ShortR"}, "想定外の約定種別")
            side = 1 if kind.startswith("Long") else -1
            if kind.endswith("N"):
                ensure(at < cutoff, "新規停止時刻以降の新規約定")
                ensure(not active, "同一候補で建玉が重複")
                ensure(position_id not in seen_positions, "建玉IDを再利用")
                active[position_id] = Holding(side, quantity, price)
                seen_positions.add(position_id)
                entries += 1
            else:
                ensure(position_id in active, "所有していない建玉への返済")
                holding = active[position_id]
                ensure(holding.side == side, "返済方向が新規と不一致")
                ensure(quantity <= holding.quantity, "保有数量を超過して返済")
                gross += side * (price - holding.price) * quantity * multiplier
                holding.quantity -= quantity
                exits += 1
                if holding.quantity == 0:
                    del active[position_id]
                    completed += 1
            fees += fee
            previous_time, previous_line = at, source_line
        except (ValueError, KeyError, TypeError, InvalidOperation) as error:
            raise ValueError(f"{path.name}:{row_no}: {error}") from error

    # ----------------------------------------
    # 終端の両方向の残数量と、CSVに保存された独立会計の対象値を照合する。
    long_qty = sum(item.quantity for item in active.values() if item.side == 1)
    short_qty = sum(item.quantity for item in active.values() if item.side == -1)
    ensure(long_qty == 0 and short_qty == 0, "セッション終端に建玉が残っている")
    ensure(entries == exits == completed, "新規・返済・完結件数が不一致")
    net = gross - fees
    expected_values = {
        "取引数": Decimal(completed),
        "値幅損益円": gross,
        "手数料円": fees,
        "純損益円": net,
        "終了建玉": Decimal(0),
    }
    for label, expected in expected_values.items():
        actual = amount(session_row[label], f"集計CSVの{label}")
        ensure(abs(actual - expected) <= EPSILON, f"{label}が不一致: CSV={actual}, 独立会計={expected}")
    ensure(amount(session_row["終了未約定"], "申告された終了未約定") == 0, "CSV申告で未約定が残っている")
    return {
        "資源ID": resource["id"], "銘柄": symbol, "場": session, "手法": method,
        "合格": True, "約定片数": len(seen_fills), "新規数": entries,
        "返済数": exits, "完結取引数": completed, "値幅損益円": gross,
        "手数料円": fees, "純損益円": net, "終了買数量": long_qty,
        "終了売数量": short_qty, "最終約定時刻": previous_time.isoformat() if previous_time else None,
        "約定パス": pnl_path.as_posix(), "約定SHA256": hashlib.sha256(body).hexdigest(),
    }


# ----------------------------------------
# 全資源の網羅性と、監査結果の保存

def run_audit(folder: Path, conditions: Path, expected_resources: int) -> dict[str, Any]:
    """完成した出力を読み、全資源とセッション集計を照合する。

    引数: folder (Path) は出力ルート、conditions (Path) は事前条件JSON、
    expected_resources (int) は期待する資源数。
    返り値: dict[str, Any] は総合合否、理由、資源別結果と監査範囲。
    """
    settings = read_json(conditions)
    catalog_path = folder / "一覧.resources.json"
    catalog = read_json(catalog_path)
    ensure(catalog.get("schema_version") == 1 and catalog.get("path_base") == "catalog", "一覧の基本仕様が不一致")
    resources = catalog["resources"]
    errors: list[str] = []
    if len(resources) != expected_resources:
        errors.append(f"資源数: 期待{expected_resources}, 実際{len(resources)}")
    with (folder / "セッション集計.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    indexed_rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = row["銘柄"], row["場"], row["手法"]
        if key in indexed_rows:
            errors.append(f"セッション集計の重複: {key}")
        indexed_rows[key] = row
    qualities = read_json(folder / "データ品質と入力台帳.json")
    indexed_quality = {(row["銘柄"], row["場"]): row for row in qualities}
    if len(indexed_quality) != len(qualities):
        errors.append("品質台帳に銘柄・場の重複がある")
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    results: list[dict[str, Any]] = []
    for resource in resources:
        try:
            identifier = resource["id"]
            key = resource_key(resource)
            ensure(isinstance(identifier, str) and bool(identifier), "資源IDが空")
            ensure(identifier not in seen_ids, "資源IDが重複")
            ensure(key not in seen_keys, "銘柄・場・手法の資源が重複")
            seen_ids.add(identifier)
            seen_keys.add(key)
            ensure(key in indexed_rows, "対応するセッション集計がない")
            ensure(key[:2] in indexed_quality, "対応する品質台帳がない")
            results.append(audit_resource(folder, resource, settings, indexed_rows[key], indexed_quality[key[:2]]))
        except (ValueError, KeyError, TypeError, OSError, InvalidOperation) as error:
            errors.append(f"{resource.get('id', '識別子なし')}: {error}")
    if set(indexed_rows) != seen_keys:
        errors.append("一覧とセッション集計の銘柄・場・手法の集合が一致しない")
    totals = {
        "約定片数": sum(row["約定片数"] for row in results),
        "完結取引数": sum(row["完結取引数"] for row in results),
        "値幅損益円": sum((row["値幅損益円"] for row in results), Decimal(0)),
        "手数料円": sum((row["手数料円"] for row in results), Decimal(0)),
        "純損益円": sum((row["純損益円"] for row in results), Decimal(0)),
    }
    return {
        "監査日時": datetime.now(JST).isoformat(), "合格": not errors,
        "試行出力": str(folder.resolve()), "条件": str(conditions.resolve()),
        "条件SHA256": hashlib.sha256(conditions.read_bytes()).hexdigest(),
        "一覧SHA256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "期待資源数": expected_resources, "実際資源数": len(resources),
        "セッション集計行数": len(rows), "合格資源数": len(results),
        "無取引資源数": sum(row["約定片数"] == 0 for row in results),
        "集計": totals, "不合格理由": errors, "資源別": results,
        "独立性": "再現.pyを読み込まず、標準ライブラリとDecimalで約定から会計を再構成した。原板を再読していない。",
        "監査範囲外": [
            "原板気配と約定価格の一致、判断・約定遅延、指標と保護発動の正しさ",
            "終了未約定ゼロはCSV申告の検査。約定だけでは注文残を独立確認できない",
            "含み損益・含み込み最大DD、MFE・MAE、全原板のViewer再生",
        ],
    }


def main() -> int:
    """引数を解析して監査し、作業領域へ小さな報告を保存する。

    引数: なし。実行時引数はargparseで取得する。
    返り値: int は全項目合格なら0、不合格なら1、入力不備なら2。
    """
    parser = argparse.ArgumentParser(description="約定列を独立会計で監査する")
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--conditions", type=Path, default=DEFAULT_STUDY / "条件.json")
    parser.add_argument("--expected-resources", type=int, default=342)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "監査結果.json")
    args = parser.parse_args()
    try:
        ensure(args.expected_resources > 0, "期待資源数は正数が必要")
        report = run_audit(args.study.resolve(), args.conditions.resolve(), args.expected_resources)
    except (ValueError, KeyError, TypeError, OSError, InvalidOperation) as error:
        print(f"監査入力を確認できません: {error}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "資源別"}, ensure_ascii=False, indent=2, default=str))
    return 0 if report["合格"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
