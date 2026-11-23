"""複合検証の小型CSVから、因子比較・内訳・累積損益と整合記録を作る。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sys
from typing import Any


JST = timezone(timedelta(hours=9))
FACTORS = "MRVB"
ZERO = Decimal(0)
TOLERANCE = Decimal("0.000001")
INPUT_NAMES = ("セッション集計.csv", "取引集計.csv", "対応差.csv", "発動候補.csv", "候補比較.csv")
FACTOR_FIELDS = ["銘柄", "期間", "因子", "文脈", "追加前", "追加後", "対象場数", "比較可能場数",
                 "比較不可場数", "追加前純損益合計円", "追加後純損益合計円", "差合計円",
                 "場平均純損益差円", "改善場数", "悪化場数", "同値場数", "追加前取引数",
                 "追加後取引数", "取引数差", "場平均取引数差", "結果状態"]
MAIN_FIELDS = ["銘柄", "期間", "因子", "文脈数", "対象場数", "共通比較可能場数", "比較不可場数",
               "8文脈平均_差合計円", "8文脈平均_場平均純損益差円", "8文脈平均_取引数差",
               "8文脈平均_場平均取引数差", "結果状態", "解釈"]
BREAKDOWN_FIELDS = ["銘柄", "期間", "手法", "取引数", "値幅損益円", "手数料円", "純損益円",
                    "費用増純損益円", "勝ち数", "負け数", "同値数", "平均取引損益円"]
OPPORTUNITY_FIELDS = ["銘柄", "期間", "手法", "記録発動候補数", "共通発動可能数", "因子許可数",
                      "因子除外数", "因子許可率", "経路依存入口機会数", "経路依存条件許可数", "注意"]


# ----------------------------------------
# CSV・数値・照合記録の共通処理

def read_csv(path: Path) -> list[dict[str, str]]:
    """UTF-8のCSVを文字列の表として読み、空ファイルは空表にする。

    引数: path (Path) は入力CSVのパス。
    返り値: list[dict[str, str]] は列名をキーとする行。数値はまだ変換しない。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def decimal_value(value: Any) -> Decimal:
    """有限な数値だけを十進数へ変換する。

    引数: value (Any) は文字列、整数またはDecimalの数値。
    返り値: Decimal は有限な値。不正値・空欄・非有限値はValueErrorにする。
    """
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"数値として読めない値: {value!r}") from error
    if not result.is_finite():
        raise ValueError(f"有限でない数値: {value!r}")
    return result


def integer_value(value: Any) -> int:
    """整数値であることを検査して変換する。

    引数: value (Any) は数値を表す値。
    返り値: int は整数。小数部分がある場合はValueErrorにする。
    """
    result = decimal_value(value)
    if result != result.to_integral_value():
        raise ValueError(f"整数でない値: {value!r}")
    return int(result)


def boolean_value(value: Any) -> bool:
    """CSV上の真偽値を曖昧な文字列評価をせずに読む。

    引数: value (Any) はTrue/FalseまたはそのCSV表現。
    返り値: bool は真偽値。不明な表現はValueErrorにする。
    """
    if value is True or str(value) in ("True", "true", "1"):
        return True
    if value is False or str(value) in ("False", "false", "0"):
        return False
    raise ValueError(f"真偽値として読めない値: {value!r}")


def sum_field(rows: list[dict[str, Any]], field: str) -> Decimal:
    """指定列を十進数で合計し、無取引の空表はゼロにする。

    引数: rows (list[dict[str, Any]]) は対象行、field (str) は数値列名。
    返り値: Decimal は対象列の合計。
    """
    return sum((decimal_value(row[field]) for row in rows), ZERO)


def complete(row: dict[str, Any]) -> bool:
    """セッション終了時に建玉と未約定が両方ないかを判定する。

    引数: row (dict[str, Any]) はセッション集計行。
    返り値: bool は終了建玉・終了未約定がともにゼロならTrue。
    """
    return integer_value(row["終了建玉"]) == 0 and integer_value(row["終了未約定"]) == 0


def record_check(report: dict[str, Any], condition: bool, label: str, details: Any = None) -> None:
    """検査数と失敗を記録し、巨大な誤り一覧の保存を避ける。

    引数: report (dict[str, Any]) は照合記録、condition (bool) は合否、
    label (str) は検査名、details (Any) は必要な不一致の文脈。
    返り値: None。失敗の詳細は先頭50件まで保存する。
    """
    report["検査数"] += 1
    if not condition:
        report["不一致数"] += 1
        if len(report["不一致"]) < 50:
            report["不一致"].append({"検査": label, "詳細": details})


def check_number(report: dict[str, Any], actual: Any, expected: Any, label: str, context: Any) -> None:
    """空欄を区別し、数値の微小な直列化誤差だけを許して照合する。

    引数: report (dict[str, Any]) は記録、actual/expected (Any) は値、
    label (str) は検査名、context (Any) は対象キー。
    返り値: None。絶対差1e-6以内を一致として記録する。
    """
    blank = actual is None or actual == ""
    if expected is None:
        matched = blank
    else:
        matched = not blank and abs(decimal_value(actual) - decimal_value(expected)) <= TOLERANCE
    record_check(report, matched, label, {"対象": context, "実際": actual, "期待": expected})


def output_value(value: Any) -> Any:
    """JSON・CSVへ保存する十進数を可読な形式へ変換する。

    引数: value (Any) は保存対象の値。
    返り値: Any はDecimalのみ小数点以下6桁の文字列へ変換した値。
    """
    if isinstance(value, Decimal):
        text = format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    """空表にも見出しを付け、日本語UTF-8のCSVを保存する。

    引数: path (Path) は保存先、rows (list[dict[str, Any]]) は行、
    fields (list[str]) は列の順序。
    返り値: None。Decimalの表示は小数点以下6桁までとする。
    """
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows({key: output_value(row.get(key)) for key in fields} for row in rows)


def selected_rows(rows: list[dict[str, Any]], symbol: str, method: str, period: str) -> list[dict[str, Any]]:
    """候補比較の期間定義に従って同じ銘柄・手法の行を選ぶ。

    引数: rows (list[dict[str, Any]]) は入力表、symbol/method/period (str) は選択キー。
    返り値: list[dict[str, Any]] は全対象または指定期間の対象行。
    """
    return [row for row in rows if row["銘柄"] == symbol and row["手法"] == method
            and (period == "全対象" or row["期間"] == period)]


def load_config(study: Path) -> tuple[dict[str, Any], Path]:
    """追加確認では親試行も調べ、固定済み条件を読む。

    引数: study (Path) は集計対象フォルダ。
    返り値: tuple[dict[str, Any], Path] は条件内容と読み込んだパス。
    """
    for path in (study / "条件.json", study.parent / "条件.json"):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8-sig")), path
    raise ValueError("対象フォルダにも親にも条件.jsonがない")


# ----------------------------------------
# 入力の独立照合と、因子集合の確認

def validate_tables(tables: dict[str, list[dict[str, str]]], rules: list[dict[str, Any]],
                    report: dict[str, Any]) -> None:
    """セッション・完結取引・候補比較・対応差・発動記録の整合を調べる。

    引数: tables (dict[str, list[dict[str, str]]]) は五つの入力表、
    rules (list[dict[str, Any]]) は固定候補、report (dict[str, Any]) は照合記録。
    返り値: None。原板や再生処理の内部関数は参照しない。
    """
    sessions, trades = tables["セッション集計.csv"], tables["取引集計.csv"]
    methods = {rule["名前"] for rule in rules}
    record_check(report, bool(sessions), "セッション集計が空でない")
    record_check(report, len(methods) == len(rules), "条件候補名が一意")
    indexed = {}
    for row in sessions:
        key = row["銘柄"], row["場"], row["手法"]
        record_check(report, key not in indexed, "セッションキーが一意", key)
        record_check(report, row["手法"] in methods, "固定候補に存在する", key)
        indexed[key] = row
    by_session: dict[tuple[str, str], set[str]] = defaultdict(set)
    for symbol, session, method in indexed:
        by_session[symbol, session].add(method)
    for key, present in by_session.items():
        record_check(report, present == methods, "全候補の対象場が一致", key)
        periods = {indexed[key[0], key[1], method]["期間"] for method in present}
        record_check(report, len(periods) == 1, "同一場の全候補で期間が一致", key)
    for row in trades:
        key = row["銘柄"], row["場"], row["手法"]
        record_check(report, key in indexed, "取引に対応する場が存在", key)
        if key in indexed:
            record_check(report, row["期間"] == indexed[key]["期間"], "取引と場の期間が一致", key)
        check_number(report, row["純損益円"], decimal_value(row["値幅損益円"]) - decimal_value(row["手数料円"]),
                     "取引の損益会計", key)
    grouped_trades: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in trades:
        grouped_trades[row["銘柄"], row["場"], row["手法"]].append(row)
    for key, row in indexed.items():
        detail = grouped_trades[key]
        check_number(report, row["取引数"], len(detail), "場ごとの完結取引数", key)
        if complete(row):
            check_number(report, row["純損益円"], sum_field(detail, "純損益円"), "完結場の現金と取引損益", key)
    comparison_keys = set()
    for row in tables["候補比較.csv"]:
        key = row["銘柄"], row["手法"], row["期間"]
        record_check(report, key not in comparison_keys, "候補比較キーが一意", key)
        comparison_keys.add(key)
        chosen_sessions = selected_rows(sessions, *key)
        chosen_trades = selected_rows(trades, *key)
        is_complete = all(complete(item) for item in chosen_sessions)
        expected = {"セッション数": len(chosen_sessions),
                    "無取引場数": sum(integer_value(item["取引数"]) == 0 for item in chosen_sessions),
                    "取引数": len(chosen_trades),
                    "値幅損益円": sum_field(chosen_trades, "値幅損益円"),
                    "手数料円": sum_field(chosen_trades, "手数料円"),
                    "純損益円": sum_field(chosen_trades, "純損益円") if is_complete else None,
                    "完結取引純損益円": sum_field(chosen_trades, "純損益円"),
                    "現金会計合計円": sum_field(chosen_sessions, "純損益円"),
                    "費用増純損益円": sum_field(chosen_trades, "費用増純損益円"),
                    "未解消場数": sum(integer_value(item["終了建玉"]) != 0 for item in chosen_sessions)}
        record_check(report, row["手法"] in methods, "候補比較の手法が存在", key)
        for field, value in expected.items():
            check_number(report, row[field], value, f"候補比較/{field}", key)
    expected_keys = {(symbol, method, period) for symbol in {row["銘柄"] for row in sessions}
                     for method in methods for period in {"全対象"} | {row["期間"] for row in sessions}}
    record_check(report, comparison_keys == expected_keys, "候補比較の銘柄・候補・期間が網羅", sorted(comparison_keys))
    pair_keys = set()
    for row in tables["対応差.csv"]:
        key = row["銘柄"], row["場"], row["追加因子"], row["追加前"], row["追加後"]
        record_check(report, key not in pair_keys, "対応差キーが一意", key)
        pair_keys.add(key)
        before = indexed[row["銘柄"], row["場"], row["追加前"]]
        after = indexed[row["銘柄"], row["場"], row["追加後"]]
        record_check(report, row["期間"] == before["期間"] == after["期間"], "対応差の期間が一致", key)
        valid = complete(before) and complete(after)
        if "結果状態" in row:
            record_check(report, row["結果状態"] == ("完結" if valid else "未解消・比較不可"),
                         "対応差の完結状態", key)
        difference = decimal_value(after["純損益円"]) - decimal_value(before["純損益円"]) if valid else None
        check_number(report, row["純損益差円"], difference, "対応差の場損益", key)
        check_number(report, row["取引数差"], integer_value(after["取引数"]) - integer_value(before["取引数"]),
                     "対応差の取引数", key)
    for row in tables["発動候補.csv"]:
        key = row["銘柄"], row["場"]
        record_check(report, key in by_session, "発動候補の対象場が存在", key)
        if key in by_session:
            method = next(iter(by_session[key]))
            record_check(report, row["期間"] == indexed[key[0], key[1], method]["期間"],
                         "発動候補と場の期間が一致", key)
        record_check(report, integer_value(row["方向"]) in (-1, 1), "発動候補の方向", key)
        record_check(report, integer_value(row["原板行"]) > 0, "発動候補の原板行が正", key)
        boolean_value(row["発動可能"])
        for factor in FACTORS:
            boolean_value(row[factor])
    report["全場完結"] = all(complete(row) for row in sessions)
    report["終了建玉残の場数"] = sum(integer_value(row["終了建玉"]) != 0 for row in sessions)
    report["終了未約定残の場数"] = sum(integer_value(row["終了未約定"]) != 0 for row in sessions)


def factorial_map(rules: list[dict[str, Any]]) -> dict[frozenset[str], str]:
    """全16集合が一意に揃う場合だけ四因子比較の対応表を作る。

    引数: rules (list[dict[str, Any]]) は固定済み候補。
    返り値: dict[frozenset[str], str] は因子集合から候補名への表。非要因計画なら空辞書。
    """
    mapping = {frozenset(rule["因子"]): rule["名前"] for rule in rules}
    expected = {frozenset(factor for factor, enabled in zip(FACTORS, values) if enabled)
                for values in itertools.product((False, True), repeat=4)}
    return mapping if len(rules) == 16 and set(mapping) == expected else {}


def factor_results(sessions: list[dict[str, str]], comparisons: list[dict[str, str]],
                   mapping: dict[frozenset[str], str], report: dict[str, Any],
                   pairs: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """同一場の一因子追加差と、八文脈の記述的平均を作る。

    引数: sessions/comparisons/pairs (list[dict[str, str]]) は入力集計と対応差、
    mapping (dict[frozenset[str], str]) は全16集合、report (dict[str, Any]) は照合記録。
    返り値: tuple[list[dict[str, Any]], list[dict[str, Any]]] は文脈別効果と主効果。
    """
    if not mapping:
        return [], []
    indexed = {(row["銘柄"], row["場"], row["手法"]): row for row in sessions}
    expected_pairs = {(row["銘柄"], row["場"], factor, before, mapping[factors | {factor}])
                      for factors, before in mapping.items() for factor in FACTORS if factor not in factors
                      for row in sessions if row["手法"] == before}
    actual_pairs = {(row["銘柄"], row["場"], row["追加因子"], row["追加前"], row["追加後"])
                    for row in pairs}
    record_check(report, actual_pairs == expected_pairs, "全因子・全8文脈・全場の対応差が網羅",
                 {"期待行数": len(expected_pairs), "実際行数": len(actual_pairs)})
    contexts, main_effects = [], []
    groups = sorted({(row["銘柄"], row["期間"]) for row in comparisons})
    for symbol, period in groups:
        reference = selected_rows(sessions, symbol, mapping[frozenset()], period)
        session_names = sorted(row["場"] for row in reference)
        shared = [session for session in session_names
                  if all(complete(indexed[symbol, session, method]) for method in mapping.values())]
        for factor in FACTORS:
            shared_differences, shared_trade_differences = [], []
            for factors, before in mapping.items():
                if factor in factors:
                    continue
                after = mapping[factors | {factor}]
                valid = [session for session in session_names if complete(indexed[symbol, session, before])
                         and complete(indexed[symbol, session, after])]
                differences = [decimal_value(indexed[symbol, session, after]["純損益円"])
                               - decimal_value(indexed[symbol, session, before]["純損益円"]) for session in valid]
                before_total = sum((decimal_value(indexed[symbol, session, before]["純損益円"])
                                    for session in valid), ZERO)
                after_total = sum((decimal_value(indexed[symbol, session, after]["純損益円"])
                                   for session in valid), ZERO)
                before_count = sum(integer_value(indexed[symbol, session, before]["取引数"]) for session in valid)
                after_count = sum(integer_value(indexed[symbol, session, after]["取引数"]) for session in valid)
                difference_total = sum(differences, ZERO)
                contexts.append({"銘柄": symbol, "期間": period, "因子": factor,
                                 "文脈": ",".join(f"{other}={int(other in factors)}" for other in FACTORS if other != factor),
                                 "追加前": before, "追加後": after, "対象場数": len(session_names),
                                 "比較可能場数": len(valid), "比較不可場数": len(session_names) - len(valid),
                                 "追加前純損益合計円": before_total if valid else None,
                                 "追加後純損益合計円": after_total if valid else None,
                                 "差合計円": difference_total if valid else None,
                                 "場平均純損益差円": difference_total / len(valid) if valid else None,
                                 "改善場数": sum(value > 0 for value in differences),
                                 "悪化場数": sum(value < 0 for value in differences),
                                 "同値場数": sum(value == 0 for value in differences),
                                 "追加前取引数": before_count if valid else None,
                                 "追加後取引数": after_count if valid else None,
                                 "取引数差": after_count - before_count if valid else None,
                                 "場平均取引数差": Decimal(after_count - before_count) / len(valid) if valid else None,
                                 "結果状態": "比較可能場のみ・探索記述" if valid else "比較不可"})
                shared_differences.append(sum((decimal_value(indexed[symbol, session, after]["純損益円"])
                                               - decimal_value(indexed[symbol, session, before]["純損益円"])
                                               for session in shared), ZERO))
                shared_trade_differences.append(sum(integer_value(indexed[symbol, session, after]["取引数"])
                                                    - integer_value(indexed[symbol, session, before]["取引数"])
                                                    for session in shared))
            average_total = sum(shared_differences, ZERO) / 8
            average_trades = Decimal(sum(shared_trade_differences)) / 8
            main_effects.append({"銘柄": symbol, "期間": period, "因子": factor, "文脈数": 8,
                                 "対象場数": len(session_names), "共通比較可能場数": len(shared),
                                 "比較不可場数": len(session_names) - len(shared),
                                 "8文脈平均_差合計円": average_total if shared else None,
                                 "8文脈平均_場平均純損益差円": average_total / len(shared) if shared else None,
                                 "8文脈平均_取引数差": average_trades if shared else None,
                                 "8文脈平均_場平均取引数差": average_trades / len(shared) if shared else None,
                                 "結果状態": "共通比較可能場のみ・探索記述" if shared else "比較不可",
                                 "解釈": "同じ市場経路の8文脈平均。独立8反復・心理の因果効果・有意差の推計ではない"})
    return contexts, main_effects


# ----------------------------------------
# 取引の内訳と、建玉経路に依存しない発動候補

def trade_totals(rows: list[dict[str, str]]) -> dict[str, Any]:
    """完結取引の内訳一群について会計と勝敗を集計する。

    引数: rows (list[dict[str, str]]) は同じ内訳に属する取引。
    返り値: dict[str, Any] は取引数・金額・勝敗・平均。無取引の平均はNone。
    """
    profits = [decimal_value(row["純損益円"]) for row in rows]
    total = sum(profits, ZERO)
    return {"取引数": len(rows), "値幅損益円": sum_field(rows, "値幅損益円"),
            "手数料円": sum_field(rows, "手数料円"), "純損益円": total,
            "費用増純損益円": sum_field(rows, "費用増純損益円"),
            "勝ち数": sum(value > 0 for value in profits), "負け数": sum(value < 0 for value in profits),
            "同値数": sum(value == 0 for value in profits),
            "平均取引損益円": total / len(rows) if rows else None}


def breakdown_results(trades: list[dict[str, str]], comparisons: list[dict[str, str]],
                      report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """新規約定の日本時間の時台と売買方向で、完結取引を分ける。

    引数: trades/comparisons (list[dict[str, str]]) は取引と候補比較、
    report (dict[str, Any]) は全内訳を足し戻す照合記録。
    返り値: tuple[list[dict[str, Any]], list[dict[str, Any]]] は時間帯別・売買別の行。
    """
    by_hour, by_side = [], []
    for comparison in comparisons:
        key = comparison["銘柄"], comparison["手法"], comparison["期間"]
        chosen = selected_rows(trades, *key)
        hours: dict[int, list[dict[str, str]]] = defaultdict(list)
        sides: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in chosen:
            stamp = datetime.fromisoformat(row["新規時刻"])
            if stamp.tzinfo is None:
                raise ValueError(f"新規時刻にタイムゾーンがない: {row['新規時刻']}")
            hours[stamp.astimezone(JST).hour].append(row)
            if row["方向"] not in ("買い", "売り"):
                raise ValueError(f"未知の売買方向: {row['方向']}")
            sides[row["方向"]].append(row)
        common = {"銘柄": key[0], "手法": key[1], "期間": key[2]}
        hourly = [{**common, "新規時台_JST": f"{hour:02d}時台", **trade_totals(hours[hour])} for hour in range(24)]
        directional = [{**common, "方向": side, **trade_totals(sides[side])} for side in ("買い", "売り")]
        for name, rows in (("時間帯", hourly), ("売買", directional)):
            for field in ("取引数", "値幅損益円", "手数料円", "純損益円", "費用増純損益円"):
                expected = len(chosen) if field == "取引数" else sum_field(chosen, field)
                check_number(report, sum_field(rows, field), expected, f"{name}内訳の足戻し/{field}", key)
        by_hour.extend(hourly)
        by_side.extend(directional)
    return by_hour, by_side


def opportunity_results(opportunities: list[dict[str, str]], sessions: list[dict[str, str]],
                        comparisons: list[dict[str, str]], rules: list[dict[str, Any]],
                        report: dict[str, Any]) -> list[dict[str, Any]]:
    """保有の有無に依存しない共通発動候補を分母に因子許可率を作る。

    引数: opportunities/sessions/comparisons (list[dict[str, str]]) は発動・場・候補表、
    rules (list[dict[str, Any]]) は固定条件、report (dict[str, Any]) は照合記録。
    返り値: list[dict[str, Any]] は実際のflat経路の件数も別列に持つ集計。
    """
    by_name = {rule["名前"]: rule for rule in rules}
    result = []
    for comparison in comparisons:
        symbol, method, period = comparison["銘柄"], comparison["手法"], comparison["期間"]
        observed = [row for row in opportunities if row["銘柄"] == symbol
                    and (period == "全対象" or row["期間"] == period)]
        possible = [row for row in observed if boolean_value(row["発動可能"])]
        rule = by_name[method]
        allowed = sum(all(boolean_value(row[factor]) for factor in rule["因子"])
                      and not rule.get("取引禁止", False) for row in possible)
        chosen_sessions = selected_rows(sessions, symbol, method, period)
        path_opportunities = sum(integer_value(row["入口機会数"]) for row in chosen_sessions)
        path_allowed = sum(integer_value(row["条件許可数"]) for row in chosen_sessions)
        record_check(report, 0 <= path_opportunities <= len(possible), "経路依存の機会数は共通候補以下",
                     (symbol, method, period))
        record_check(report, 0 <= path_allowed <= min(allowed, path_opportunities), "経路依存の許可数は候補許可以下",
                     (symbol, method, period))
        result.append({"銘柄": symbol, "期間": period, "手法": method, "記録発動候補数": len(observed),
                       "共通発動可能数": len(possible), "因子許可数": allowed, "因子除外数": len(possible) - allowed,
                       "因子許可率": Decimal(allowed) / len(possible) if possible else None,
                       "経路依存入口機会数": path_opportunities, "経路依存条件許可数": path_allowed,
                       "注意": "因子許可は保有無関係の候補判定。発注・約定数ではなく、保護や板の執行条件も表さない"})
    return result


# ----------------------------------------
# 成績によらない固定選択の図と、実行情報

def draw_cumulative(study: Path, sessions: list[dict[str, str]], rules: list[dict[str, Any]],
                    mapping: dict[frozenset[str], str]) -> dict[str, Any]:
    """候補の成績で選別せず、セッション末の累積純損益を描く。

    引数: study (Path) は図の保存先、sessions (list[dict[str, str]]) は場集計、
    rules (list[dict[str, Any]]) は候補順、mapping (dict[frozenset[str], str]) は全因子対応表。
    返り値: dict[str, Any] は図の候補・版・フォント・未解消時の描画方針。
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    import matplotlib.pyplot as plt

    font_path = Path("C:/Windows/Fonts/meiryo.ttc")
    if not font_path.is_file():
        font_path = Path(font_manager.findfont("Meiryo", fallback_to_default=False))
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    if mapping:
        methods = [mapping[frozenset()], *(mapping[frozenset({factor})] for factor in FACTORS),
                   mapping[frozenset(FACTORS)]]
        selection = "全16候補から成績を参照せず、基準・単独四因子・全因子の6候補"
    else:
        methods = [rule["名前"] for rule in rules]
        selection = "固定条件の全候補"
    symbols = sorted({row["銘柄"] for row in sessions}, key=lambda value: (value != "NK225", value))
    figure, axes = plt.subplots(len(symbols), 1, figsize=(13.5, 4.5 * len(symbols) + 1), squeeze=False,
                                constrained_layout=True)
    colors = ["#444444", "#0072b2", "#009e73", "#e69f00", "#cc79a7", "#d55e00"]
    for axis, symbol in zip(axes.flat, symbols):
        names = sorted({row["場"] for row in sessions if row["銘柄"] == symbol})
        indexed = {(row["場"], row["手法"]): row for row in sessions if row["銘柄"] == symbol}
        for order, method in enumerate(methods):
            total, invalid, values = ZERO, False, [0.0]
            for session in names:
                row = indexed[session, method]
                invalid = invalid or not complete(row)
                total += decimal_value(row["純損益円"])
                values.append(float("nan") if invalid else float(total))
            axis.plot(range(len(names) + 1), values, label=method, color=colors[order % len(colors)],
                      linewidth=2.4 if order in (0, len(methods) - 1) else 1.5,
                      linestyle="-" if order < len(colors) else "--")
        step = max(1, (len(names) + 9) // 10)
        ticks = [0] + list(range(step, len(names) + 1, step))
        if ticks[-1] != len(names):
            ticks.append(len(names))
        axis.set_xticks(ticks)
        axis.set_xticklabels(["開始" if index == 0 else names[index - 1][5:].replace("_Day", "昼").replace("_Night", "夜")
                              for index in ticks], rotation=25, ha="right")
        for index in range(1, len(names)):
            if indexed[names[index - 1], methods[0]]["期間"] != indexed[names[index], methods[0]]["期間"]:
                axis.axvline(index + 0.5, color="#888888", linewidth=0.8, linestyle=":")
        axis.axhline(0, color="#777777", linewidth=0.8)
        axis.set_title(f"{symbol}：セッション末の累積純損益")
        axis.set_ylabel("純損益（円）")
        axis.grid(alpha=0.2)
        axis.legend(loc="best", ncol=min(3, len(methods)), fontsize=9)
    figure.suptitle("固定候補の累積純損益\nセッション末の確定値。含み込み最大DDの系列ではない。", fontsize=13)
    path = study / "累積損益推移.png"
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return {"ファイル": path.name, "候補": methods, "選択規則": selection, "matplotlib": matplotlib.__version__,
            "フォント": str(font_path), "未解消時": "その場以降の累積線を非表示。現金残を完結純損益と呼ばない"}


def run(study: Path) -> bool:
    """入力照合に合格した表からだけ成果物を生成し、成否を保存する。

    引数: study (Path) は探索試行または追加確認の成果物フォルダ。
    返り値: bool は入力と出力の照合・図の生成が完了したときTrue。
    """
    report: dict[str, Any] = {"日時": datetime.now(JST).isoformat(), "対象": str(study),
                              "Python": platform.python_version(), "検査数": 0, "不一致数": 0, "不一致": [],
                              "照合合格": False, "注意": ["原板・約定JSONLを再読しない集計照合。執行仮定の独立検証ではない。",
                              "因子主効果は同一市場経路の8文脈平均。独立反復・有意差・心理の因果効果ではない。",
                              "時間帯・売買内訳は完結取引の新規約定時刻と方向による。未解消建玉の評価を含めない。"]}
    try:
        config, config_path = load_config(study)
        rules = config["候補"]
        tables = {name: read_csv(study / name) for name in INPUT_NAMES}
        report["入力"] = {name: {"行数": len(tables[name]), "SHA256": hashlib.sha256((study / name).read_bytes()).hexdigest()}
                          for name in INPUT_NAMES}
        report["条件"] = {"パス": str(config_path), "SHA256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
        report["集計コードSHA256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        validate_tables(tables, rules, report)
        mapping = factorial_map(rules)
        effects, main_effects = factor_results(tables["セッション集計.csv"], tables["候補比較.csv"], mapping,
                                              report, tables["対応差.csv"])
        hourly, directional = breakdown_results(tables["取引集計.csv"], tables["候補比較.csv"], report)
        opportunities = opportunity_results(tables["発動候補.csv"], tables["セッション集計.csv"],
                                            tables["候補比較.csv"], rules, report)
        report["因子計画"] = "全16組・各8文脈" if mapping else "非要因計画のため因子CSVは見出しのみ"
        report["生成行数"] = {"因子効果": len(effects), "因子主効果": len(main_effects),
                               "時間帯内訳": len(hourly), "売買内訳": len(directional), "発動条件内訳": len(opportunities)}
        if report["不一致数"]:
            raise ValueError("入力集計の不一致があるため、派生成果物を更新しない")
        write_csv(study / "因子効果.csv", effects, FACTOR_FIELDS)
        write_csv(study / "因子主効果.csv", main_effects, MAIN_FIELDS)
        write_csv(study / "内訳_時間帯.csv", hourly, ["銘柄", "期間", "手法", "新規時台_JST"] + BREAKDOWN_FIELDS[3:])
        write_csv(study / "内訳_売買.csv", directional, ["銘柄", "期間", "手法", "方向"] + BREAKDOWN_FIELDS[3:])
        write_csv(study / "発動条件内訳.csv", opportunities, OPPORTUNITY_FIELDS)
        report["図"] = draw_cumulative(study, tables["セッション集計.csv"], rules, mapping)
        report["照合合格"] = True
        report["結果状態"] = "照合合格・全場完結" if report["全場完結"] else "照合合格・未解消あり"
    except Exception as error:
        report["結果状態"] = "照合または生成失敗"
        report["例外"] = f"{type(error).__name__}: {error}"
    target = study / "集計照合結果.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=output_value, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{report['結果状態']}：検査{report['検査数']}件、不一致{report['不一致数']}件。{target}")
    if "例外" in report:
        print(report["例外"], file=sys.stderr)
    return report["照合合格"]


def main() -> None:
    """コマンド引数で集計先だけを指定して実行する。

    引数: なし。argparseから--study (Path) を取得する。
    返り値: None。照合または図生成の失敗時は終了コード1とする。
    """
    parser = argparse.ArgumentParser(description="複合検証CSVの因子比較・内訳・図・整合記録を生成する")
    parser.add_argument("--study", required=True, type=Path, help="CSVのある試行または追加確認フォルダ")
    args = parser.parse_args()
    study = args.study.resolve()
    if not study.is_dir():
        parser.error("--studyは既存の成果物フォルダを指定してください")
    if not run(study):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
