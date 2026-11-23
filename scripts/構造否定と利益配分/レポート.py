"""83の小型正本を照合し、構造否定×利益配分の帳票だけを生成する。

固定82レポートの有限値・版5表・会計集約部品から派生する。
元指標・原板・売買を再生せず、明示した正本と保存診断へ結果を結ぶ。
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODES = ("S0G1", "S1G1", "S0G2", "S1G2")
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in MODES)
BEGIN = "<!-- 83_RESULTS_BEGIN -->"
END = "<!-- 83_RESULTS_END -->"
STATUS = "**固定設定。実行状態と結果は末尾の専用欄に記載する。**"
# 固定82派生元SHA256: 97488ac00b38482d1a92663e424a0ea8c421aaf210183da8caad76d5c9e03ab9

def need(ok: bool, message: str) -> None:
    """
    機能: 不整合を日本語の原因とともに拒否する。
    引数: ok (bool) は成立条件、message (str) は原因。
    返り値: None。不成立はValueError。
    """
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    """
    機能: 市場原板を含まない明示ファイルの保存指紋を得る。
    引数: path (Path) は小型正本。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    """
    機能: 有限値だけの辞書JSONを読む。
    引数: path (Path) は明示された正本。
    返り値: dict は本文。市場や売買を再生しない。
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    need(type(value) is dict, "正本の最上位は辞書が必要")
    json.dumps(value, allow_nan=False)
    return value


def number(value: object) -> Decimal:
    """
    機能: 有限な金額を十進比較値へ変換する。
    引数: value (object) はint/float/Decimal。
    返り値: Decimal は厳密な十進比較値。
    """
    need(type(value) in (int, float, Decimal) and math.isfinite(value), "有限な数値が必要")
    return Decimal(str(value))


def count(value: object) -> int:
    """
    機能: boolを個数へ取り違えず非負整数を確認する。
    引数: value (object) は個数のJSON値。
    返り値: int は非負個数。
    """
    need(type(value) is int and value >= 0, "個数は非負intが必要")
    return value


def amount(value: object) -> str:
    """
    機能: 有限金額を桁区切りへ整形する。
    引数: value (object) は数値。
    返り値: str はMarkdown用表示。
    """
    text = format(number(value), ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def ratio(numerator: int, denominator: int) -> str:
    """
    機能: 分子分母を保持して比率を表示する。
    引数: numerator/denominator (int) は個数。
    返り値: str は比率又は分母0の未評価表示。
    """
    return f"{numerator}/{denominator}（{100*numerator/denominator:.1f}%）" if denominator else "0/0（未評価）"


def link(study: Path, path: Path, label: str) -> str:
    """
    機能: 正式試行から小型成果物への相対リンクを作る。
    引数: study/path (Path) は基準と成果物、label (str) は名称。
    返り値: str はMarkdownリンク。
    """
    return f"[{label}](<{Path(os.path.relpath(path, study)).as_posix()}>)"


def compressed_rows(path: Path) -> list[dict]:
    """
    機能: 圧縮した定時又は玉診断だけを読む。
    引数: path (Path) は明示された診断gzip。
    返り値: list[dict] は行本文。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    need(all(type(row) is dict for row in rows), "診断行は辞書が必要")
    json.dumps(rows, allow_nan=False)
    return rows


def verify_table(text: str, study: Path) -> None:
    """
    機能: 版5の55手法・9尺度・元順序と教材リンクを確認する。
    引数: text (str) は設定本文、study (Path) はリンク基準。
    返り値: None。使用セルの内容は設定として保持する。
    """
    catalog = read_json(ROOT / "scripts/レポート/手法カタログ_版5.json")
    template = (ROOT / "docs/議論/手法と時間スケールの汎用表_版5.md").read_text(encoding="utf-8")
    order = [re.match(r"^\| ([A-Z][0-9]{2}) \|", line)[1] for line in template.splitlines() if re.match(r"^\| [A-Z][0-9]{2} \|", line) and len(line.split("|")[1:-1]) == 11]
    methods = {method["id"]: method for method in catalog["methods"]}
    need([line for line in text.splitlines() if line.startswith("| ID | 手法 |")] == [line for line in template.splitlines() if line.startswith("| ID | 手法 |")], "9尺度の見出し差")
    rows = []
    for line in text.splitlines():
        if re.match(r"^\| [A-Z][0-9]{2} \|", line):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == 11:
                rows.append(cells)
    need(len(rows) == 55 and len(catalog["scales"]) == 9, "版5の55×9表が必要")
    need([row[0] for row in rows] == order and len(set(order)) == 55, "版5原本の手法順序又はID差")
    for row in rows:
        method = methods[row[0]]
        match = re.fullmatch(r"\[([^]]+)\]\(([^)]+)\)", row[1])
        need(match is not None and match.group(1) == method["name"], "手法名差")
        need((study / match.group(2).strip("<>")).resolve() == (ROOT / method["source"]).resolve(), "教材リンク差")
        need(all(cell for cell in row[2:]), "9尺度の状態が空です")


def verify_summary(result: dict, sessions: list[str]) -> dict:
    """
    機能: 全528会計と8集計の費用・玉・数量・期間・DDを相互確認する。
    引数: result (dict) は結果正本、sessions (list[str]) は台帳順。
    返り値: dict は場と政策をキーにした保存会計。
    """
    need(count(result["試行"]) == 83 and count(result["場数"]) == 66 and result["全場既使用"] is True, "83の66場が必要")
    need(set(result["比較"]) == set(KEYS), "8比較集合差")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}
    need(len(rows) == len(result["場別"]) == 528 and set(rows) == {(s, key) for s in sessions for key in KEYS}, "528会計の欠落又は重複")
    need(set(result["再生結果SHA256"]) == {s + ".json" for s in sessions}, "66再生指紋集合差")
    for key in KEYS:
        summary = result["比較"][key]
        mode, delay = key.split("_D")
        need(summary["mode"] == mode and summary["追加遅延秒"] == int(delay), "比較案と遅延差")
        chosen = [rows[s, key] for s in sessions]
        for row in chosen:
            need(row["mode"] == mode and row["delay"] == int(delay), "場別の案又は遅延差")
            metric = row["metrics"]
            for name in ("open_quantity", "pending_entry_quantity", "reserved_exit_quantity"):
                need(count(metric[name]) == 0, "未解消会計を正式結果にできません")
            need(number(metric["net_pnl_yen"]) == number(metric["cash_yen"]) == number(metric["gross_pnl_yen"]) - number(metric["total_cost_yen"]), "場別現金差")
        totals = summary["総計"]
        for name, total in totals.items():
            need(number(total) == sum((number(r["metrics"][name]) for r in chosen), Decimal(0)), "場別と総計差:" + key + name)
        qty = count(totals["entry_quantity"])
        need(qty == count(totals["exit_quantity"]) == 100 * count(summary["完結玉"]), "固定100枚又は返済数量差")
        need(number(totals["commission_yen"]) == 22 * qty and number(totals["slippage_yen"]) == 100 * qty, "費用内訳差")
        net = sum((number(r["metrics"]["net_pnl_yen"]) for r in chosen), Decimal(0))
        need(number(summary["費用後損益円"]) == net == number(totals["net_pnl_yen"]) and number(totals["total_cost_yen"]) == 122 * qty, "比較純額又は主費用差")
        need(number(summary["同約定0pt損益円"]) == net + 100 * qty and number(summary["同約定10pt損益円"]) == net - 100 * qty, "同約定費用感応差")
        need(count(summary["完結玉"]) == count(totals["closed_lots"]), "完結玉数差")
        for flag, loss in (("残玉旗", "残玉旗後赤字"), ("全玉旗", "全玉旗後赤字")):
            need(count(summary[loss]) <= count(summary[flag]) <= summary["完結玉"], "正益後赤字の分母差")
        need(number(summary["正益未観測の損益円"]) + number(summary["正益観測の損益円"]) == net, "残玉旗の損益分解差")
        values = [number(r["metrics"]["net_pnl_yen"]) for r in chosen]
        need((count(summary["赤字場数"]), count(summary["黒字場数"]), count(summary["同値場数"])) == (sum(v < 0 for v in values), sum(v > 0 for v in values), sum(v == 0 for v in values)), "場数分類差")
        need(summary["全場"] == 66, "対象場数差")
        cumulative = peak = dd = Decimal(0)
        daily = Counter()
        for row in chosen:
            m = row["metrics"]
            dd = max(dd, number(m["max_drawdown_yen"]), peak - cumulative - number(m["min_equity_yen"]))
            peak = max(peak, cumulative + number(m["equity_peak_yen"]))
            cumulative += number(m["net_pnl_yen"])
            need(number(row["累積損益円"]) == cumulative, "保存累積損益差")
            daily[row["session"][:10]] += number(m["net_pnl_yen"])
        need(number(summary["最大DD円"]) == dd and dd >= 0, "全原行場別のDD結合差")
        need({k: number(v) for k, v in summary["日別円"].items()} == dict(daily), "日別損益差")
        need(summary["赤字日数"] == sum(v < 0 for v in daily.values()) and summary["日数"] == len(daily), "日数分類差")
        if "判断" in summary:
            actions = Counter()
            for row in chosen:
                need(type(row.get("判断")) is dict, "実会計の判断欄が不足")
                for action, n in row["判断"].items():
                    actions[action] += count(n)
            need(dict(actions) == summary["判断"] and sum(actions.values()) == 2442, "実会計の全定時判断差")
    return rows


def verify_auxiliary(rows: list[dict]) -> dict:
    """
    機能: 評価済み補助の状態を未知と中立を混同せず方向別に集計する。
    引数: rows (list[dict]) は圧縮した全定時snapshot。
    返り値: dict はB1の状態件数。市場を再生しない。
    """
    grouped = {p: Counter() for p in ("B1",)}
    for row in rows:
        for grid in row["grid_decisions"]:
            target = grouped[grid["entry_policy"]]
            for direction in grid["decision"]["directions"]:
                need(type(direction["required_unknown"]) is bool, "必要値未知はboolが必要")
                target["必要値:" + ("未知" if direction["required_unknown"] else "判別済み")] += 1
                aux = direction["auxiliary"]
                for field, label in (("five", "5秒速度"), ("fifteen", "15秒速度"), ("ofi", "OFI30")):
                    item = aux[field]
                    need(type(item["known"]) is bool, "補助の既知性はboolが必要")
                    state = item["state"]
                    if item["known"]:
                        value = number(item["value"])
                        need(state == ("支持" if value > 0 else "反対" if value < 0 else "中立"), "補助符号と状態の不一致")
                    else:
                        need(state == "未知" and item.get("value") is None, "未知の補助を0又は支持へ補完")
                    target[label + ":" + state] += 1
                for name in ("slowdown_known", "slowdown", "structure_known", "structure_support", "pressure_clear"):
                    need(type(aux[name]) is bool, "補助の判別状態はboolが必要")
                need(not aux["slowdown"] or aux["slowdown_known"], "未知速度を失速へ分類")
                need(not aux["structure_support"] or aux["structure_known"], "未知構造を支持へ分類")
                target["短期速度:" + ("未知" if not aux["slowdown_known"] else "失速" if aux["slowdown"] else "非失速")] += 1
                target["価格帯:" + ("未知" if not aux["structure_known"] else "支持" if aux["structure_support"] else "不成立")] += 1
                target["反対圧力:" + ("解消" if aux["pressure_clear"] else "未解消")] += 1
    return grouped


def fixed_dependencies(condition: dict, reference: dict, manifest: Path) -> dict[str, str]:
    """
    機能: 83条件と80/81/82の固定読取依存を明示台帳へ結ぶ。
    引数: condition/reference (dict) は正本、manifest (Path) は固定80台帳。
    返り値: dict[str,str] は実照合したコード・実行ファイルのSHA。
    """
    for value in (condition, reference):
        need(value["試行"] == 83 and value["入力台帳SHA256"] == sha(manifest), "83条件・入力台帳差")
        need(value["入力場数"] == 66 and value["全場既使用"] is True, "66既使用場が必要")
    need(reference["入力ファイル数"] == 396 and reference["固定80採用版"] == 2, "固定入力形式差")
    path = Path(reference["入力台帳"])
    need((path if path.is_absolute() else ROOT / path).resolve() == manifest.resolve(), "台帳参照先差")
    need(set(condition["modes"]) == set(MODES) and set(condition["keys"]) == set(KEYS), "8政策集合差")
    need(condition["約定追加価格時計遅延秒"] == [0, 1] and condition["同時一建玉"] is True and condition["新損益前固定"] is True, "時計・所有・固定状態差")
    for name, expected in (("新規数量micro枚", 100), ("片側上限", 100), ("point_value", 10), ("片道手数料円", 11), ("片道滑りpt", 5), ("主往復費用円毎枚", 122), ("G1悪化余裕pt", 10), ("G1全玉予算目標円", 1)):
        need(type(condition[name]) is int and condition[name] == expected, "固定数量・費用差:" + name)
    groups = [condition["コードと依存SHA256"]]
    for version, folder in ((80, "00080_FAR後期三手法の15分移植と利益保護"), (81, "00081_定時の現在根拠と部分利益保護"), (82, "00082_チャートの現在性と補助確認")):
        name = f"固定{version}依存"
        need(condition[name] == reference[name + "指紋"], "固定依存集合差:" + name)
        groups.append(condition[name])
        need(reference[f"固定{version}条件SHA256"] == sha(ROOT / "study" / folder / "条件.json"), "旧条件の指紋差")
    groups.append({condition["実行ファイル"]: condition["実行ファイルSHA256"]})
    checked = {}
    market = Path(read_json(manifest)["source_root"]).resolve()
    for group in groups:
        need(type(group) is dict and bool(group), "固定依存が空")
        for name, wanted in group.items():
            path = Path(name)
            path = (path if path.is_absolute() else ROOT / path).resolve()
            need(not path.is_relative_to(market), "帳票から市場原板を読みません")
            need(sha(path) == wanted, "固定依存変更:" + name)
            checked[str(path)] = wanted
    return checked


def verify_anchor(anchor: dict, at: object | None = None) -> None:
    """
    機能: アンカーの既知性と、要求時に公開済みだった価格線を確認する。
    引数: anchor (dict) は保存値、at (object|None) は対応する新規要求時刻。
    返り値: None。未知を価格線へ創作せず、未来の確定線を拒否する。
    """
    need(type(anchor) is dict and type(anchor["known"]) is bool and type(anchor["reason"]) is str, "アンカー型差")
    price, when, end = [number(anchor[n]) for n in ("price", "at", "bar_end")]
    if anchor["known"]:
        if at is not None:
            need(when == number(at), "アンカー要求時刻差")
        need(price > 0 and end > 0 and 0 <= when - end <= 180, "未来・古い・不正価格アンカー")
    else:
        need(price == when == end == 0, "未知アンカーに価格線・時刻を創作")


def comparison_pairs() -> list[tuple[str, str, str]]:
    """
    機能: 構造差二組と配分差二組の比較方向を固定する。
    引数: なし。
    返り値: list[tuple[str,str,str]] は名称・A政策・B政策。
    """
    return [("G1_S1対S0", "S0G1", "S1G1"), ("G2_S1対S0", "S0G2", "S1G2"),
            ("S0_G2対G1", "S0G1", "S0G2"), ("S1_G2対G1", "S1G1", "S1G2")]


def verify_diagnostics(rows: list[dict], result: dict, sessions: list[str]) -> dict:
    """
    機能: 実玉・部分確定・構造metadataと出口間の参加分解を結合する。
    引数: rows (list[dict]) は圧縮玉、result (dict) は正本、sessions (list[str]) は対象場。
    返り値: dict は政策ごとの実玉診断。入口や出口を選び直さない。
    """
    grouped = {key: {} for key in KEYS}
    for row in rows:
        key, session, lot = row["key"], row["session"], row["lot"]
        need(key in grouped and session in sessions, "玉診断対象差")
        identity = session, lot["reference_id"]
        need(identity not in grouped[key], "同じ候補への実新規重複")
        need(count(lot["initial_quantity"]) == count(lot["closed_quantity"]) == 100 and count(lot["quantity"]) == 0, "100枚完結の数量差")
        need(all(type(lot[n]) is bool for n in ("flag", "whole_flag", "cash_floor_active", "funding_failed", "structure_active", "structure_entry_breached")), "旗・構造状態はboolが必要")
        need(sum(number(c["pnl5"]) for c in row["closed"]) == number(lot["net_pnl"]) and sum(count(c["quantity"]) for c in row["closed"]) == 100, "返済片の数量・純額差")
        order = row["entry_order"]
        need(order["kind"] == "entry" and count(order["quantity"]) == count(order["filled_quantity"]) == 100, "新規注文数量差")
        need(order["position_id"] == lot["id"] and order["reference_id"] == lot["reference_id"], "新規注文の所有対応差")
        anchor = lot["structure_anchor"]
        verify_anchor(anchor, order["request_time"])
        need(order["structure_anchor"] == anchor and order["structure_active"] is False and order["structure_floor"] is None, "新規要求アンカー又は活性状態差")
        active = key.startswith("S1") and anchor["known"]
        need(lot["structure_active"] == active, "構造の活性政策差")
        if active:
            floor = lot["side"] * (number(anchor["price"]) - number(lot["entry_price"]))
            need(abs(number(lot["structure_floor"]) - floor) <= Decimal("0.0000001"), "固定線と実価格の構造床差")
            need(number(lot["structure_activated_at"]) == number(lot["entry_time"]), "構造活性の時点差")
        else:
            need(lot["structure_floor"] is None and lot["structure_activated_at"] is None and lot["structure_entry_breached"] is False and lot["structure_first_hit_at"] is None and lot["structure_first_hit_index"] == -1, "S0又は未知に構造線を創作")
        hit = lot["structure_first_hit_at"]
        need((hit is None) == (lot["structure_first_hit_index"] == -1), "構造到達の時刻・Index差")
        if hit is not None:
            need(active and number(hit) >= number(lot["entry_time"]) and lot["structure_first_hit_index"] >= lot["entry_index"], "構造到達の当時性差")
        for closed in row["closed"]:
            need(closed["structure_anchor"] == anchor and closed["structure_active"] == active and closed["structure_floor"] == lot["structure_floor"] and closed["structure_activated_at"] == lot["structure_activated_at"] and closed["structure_entry_breached"] == lot["structure_entry_breached"], "返済片の固定構造snapshot差")
            first = closed["structure_first_hit_at"]
            need((first is None) == (closed["structure_first_hit_index"] == -1), "返済片の構造到達対差")
            if first is not None:
                need(hit == first and closed["structure_first_hit_index"] == lot["structure_first_hit_index"] and number(first) <= number(closed["exit_time"]), "返済片へ未来の構造到達を転記")
        for exit_order in row["orders"]:
            need(exit_order["structure_anchor"] == anchor, "注文の固定アンカー変更")
            if exit_order["kind"] == "exit":
                need(exit_order["structure_active"] == active and exit_order["structure_floor"] == lot["structure_floor"], "返済注文の構造床差")
        target, filled = count(lot["harvest_target"]), count(lot["harvest_filled"])
        need(filled <= target <= 100, "部分予約と約定数量差")
        if key.split("_D")[0].endswith("G2"):
            need(target == filled == 0 and lot["harvest_done_at"] is None and lot["cash_floor_active"] is False and lot["cash_floor_at"] is None and lot["cash_floor"] is None and lot["funding_failed"] is False, "G2へ部分確定・予算を混入")
            need(all(not o["harvest"] for o in row["orders"]), "G2が部分利確注文を作成")
        elif lot["cash_floor_active"]:
            need(target > 0 and filled == target and lot["harvest_done_at"] is not None and lot["cash_floor_at"] >= lot["harvest_done_at"], "未約定益を予算へ使用")
        grouped[key][identity] = row
    for key, group in grouped.items():
        lots = [r["lot"] for r in group.values()]
        s = result["比較"][key]
        need(len(lots) == s["完結玉"] and sum(number(p["net_pnl"]) for p in lots) == number(s["費用後損益円"]), "実玉と比較額差")
        for flag, label, loss in (("flag", "残玉旗", "残玉旗後赤字"), ("whole_flag", "全玉旗", "全玉旗後赤字")):
            need(sum(p[flag] for p in lots) == s[label] and sum(p[flag] and number(p["net_pnl"]) < 0 for p in lots) == s[loss], "正益後赤字分母差")
        need(sum(number(p["net_pnl"]) for p in lots if p["flag"]) == number(s["正益観測の損益円"]) and sum(number(p["net_pnl"]) for p in lots if not p["flag"]) == number(s["正益未観測の損益円"]), "正益前後の額差")
        reason_qty, reason_net = Counter(), Counter()
        for r in group.values():
            for c in r["closed"]:
                reason_qty[c["reason"]] += count(c["quantity"])
                reason_net[c["reason"]] += number(c["pnl5"])
        need(dict(reason_qty) == s["返済理由別枚数"] and dict(reason_net) == s["返済理由別損益円"], "返済理由集計差")
        expected = {"harvest_orders": sum(p["harvest_target"] > 0 for p in lots), "harvest_quantity": sum(p["harvest_target"] for p in lots),
            "harvest_filled_quantity": sum(p["harvest_filled"] for p in lots), "cash_floor_activated_lots": sum(p["cash_floor_active"] for p in lots),
            "funding_failure_lots": sum(p["funding_failed"] for p in lots), "structure_known_entries": sum(p["structure_anchor"]["known"] for p in lots),
            "structure_unknown_entries": sum(not p["structure_anchor"]["known"] for p in lots), "structure_activated_lots": sum(p["structure_active"] for p in lots),
            "structure_entry_breached_lots": sum(p["structure_entry_breached"] for p in lots), "structure_hit_lots": sum(p["structure_first_hit_at"] is not None for p in lots),
            "structure_exit_orders": sum(o["kind"] == "exit" and o["reason"] == "固定EMA構造否定" for r in group.values() for o in r["orders"]),
            "whole_profit_flags": sum(p["whole_flag"] for p in lots), "whole_flag_after_loss_lots": sum(p["whole_flag"] and number(p["net_pnl"]) < 0 for p in lots)}
        for field, n in expected.items():
            need(s["総計"][field] == n, "構造・利益配分集計差:" + field)
    decomposed = result["出口間の同実新規分解"]
    expected_names = {f"{name}_D{delay}" for delay in (0, 1) for name, _, _ in comparison_pairs()}
    need(set(decomposed) == expected_names, "出口比較の対象集合差")
    for delay in (0, 1):
        for name, a, b in comparison_pairs():
            keys = [f"{m}_D{delay}" for m in (a, b)]
            left, right = [grouped[k] for k in keys]
            common = set(left) & set(right)
            exact = {i for i in common if all(left[i]["lot"][n] == right[i]["lot"][n] for n in ("side", "entry_price", "entry_time", "initial_quantity"))}
            only_a, only_b, changed = set(left) - set(right), set(right) - set(left), common - exact
            d = decomposed[f"{name}_D{delay}"]
            need(d["比較"] == keys and d["同実新規"] == len(exact) and d["共通だが取得変更"] == len(changed) and d["Aのみ"] == len(only_a) and d["Bのみ"] == len(only_b), "出口間の参加数差")
            for field, subset, group in (("同実新規A損益円", exact, left), ("同実新規B損益円", exact, right), ("取得変更A損益円", changed, left), ("取得変更B損益円", changed, right), ("Aのみ損益円", only_a, left), ("Bのみ損益円", only_b, right)):
                need(number(d[field]) == sum(number(group[i]["lot"]["net_pnl"]) for i in subset), "出口分解額差:" + field)
            need(number(d["同実新規出口差円"]) == number(d["同実新規B損益円"]) - number(d["同実新規A損益円"]), "出口差の方向差")
    return grouped


def verify_grids(rows: list[dict], result: dict, diagnostics: dict, sessions: list[str]) -> dict:
    """
    機能: 定時snapshotを候補数・未知理由・実新規の発生元へ結ぶ。
    引数: rows (list[dict]) は圧縮定時、result/diagnostics (dict) は集計と玉、sessions (list[str]) は対象場。
    返り値: dict は入口別の可用性集計。
    """
    need(len(rows) == 66 and {r["session"] for r in rows} == set(sessions), "定時診断66場差")
    availability = {p: {"全定時": 0, "時計許可": 0, "方向判定成立": 0, "候補生成": 0, "判定項目": {}, "支持未知理由": Counter()} for p in ("B1",)}
    supplied = {}
    zone = timezone(timedelta(hours=9))
    for row in rows:
        session = row["session"]
        start = datetime.fromisoformat(session[:10]).replace(tzinfo=zone)
        first = start + timedelta(hours=9, minutes=15) if session.endswith("Day") else start + timedelta(hours=17, minutes=30)
        length = 25 if session.endswith("Day") else 49
        expected = {(first + timedelta(minutes=15 * i)).timestamp() for i in range(length)}
        seen = set()
        for grid in row["grid_decisions"]:
            policy, at, decision = grid["entry_policy"], grid["at"], grid["decision"]
            need(policy in availability and at in expected and (at, policy) not in seen, "定時又は政策の重複/欠落")
            seen.add((at, policy))
            need(decision["at"] == at and decision["policy"] == policy, "定時snapshotと判断差")
            for value in (grid["clock_allowed"], grid["candidate_accepted"], decision["allowed"]):
                need(type(value) is bool, "定時の許可はboolが必要")
            need(grid["candidate_accepted"] == (grid["clock_allowed"] and decision["allowed"]), "候補供給と時計・判断が不一致")
            q, tech, evidence = decision["quote"], decision["technical"], decision["evidence"]
            verify_anchor(grid["structure_anchor"], at)
            if grid["structure_anchor"]["known"]:
                need(tech["exit_known"] and number(grid["structure_anchor"]["price"]) == number(tech["ema8_3"]) and number(grid["structure_anchor"]["bar_end"]) == number(tech["bar3_end"]), "要求時の確定EMAアンカー差")
            need(number(q["time"]) <= number(at) and number(evidence["time"]) <= number(at), "未来snapshotの使用")
            need(number(tech["bar3_end"]) <= number(at) and number(tech["bar15_end"]) <= number(at), "未来足を判断へ使用")
            pair = decision["chart_pair"]
            need(type(pair["previous3_known"]) is bool, "前足の既知性はboolが必要")
            need(number(pair["previous_bar3_end"]) <= number(at), "未来の前足を判断へ使用")
            if decision["allowed"]:
                need(pair["previous3_known"] and number(tech["bar3_end"]) - number(pair["previous_bar3_end"]) == 180, "成立候補の前足結合が欠落")
                need(0 <= number(at) - number(tech["bar3_end"]) <= 180, "成立候補の3分公開時刻が古い")
            item = availability[policy]
            for name, val in (("全定時", 1), ("時計許可", grid["clock_allowed"]), ("方向判定成立", decision["allowed"]), ("候補生成", grid["candidate_accepted"])):
                item[name] += val
            need({d["side"] for d in decision["directions"]} == {1, -1} and len(decision["directions"]) == 2, "両方向の評価が必要")
            for direction in decision["directions"]:
                for check in direction["checks"]:
                    need(type(check["known"]) is bool and type(check["passed"]) is bool and (not check["passed"] or check["known"]), "判定既知性差")
                    name = check["group"] + ":" + check["id"]
                    counts = item["判定項目"].setdefault(name, {"方向数": 0, "既知": 0, "成立": 0, "未知": 0})
                    counts["方向数"] += 1
                    counts["既知"] += check["known"]
                    counts["成立"] += check["passed"]
                    counts["未知"] += not check["known"]
            for side in ("buy", "sell"):
                for field in ("own_reason", "peer_reason", "ofi_reason"):
                    reason = evidence[side][field]
                    if reason:
                        item["支持未知理由"][field + ":" + reason] += 1
            if grid["candidate_accepted"]:
                identity = f"{session}_{policy}_{float(at):.9f}_{decision['side']:+d}"
                supplied[session, identity] = grid
        need(seen == {(at, p) for at in expected for p in ("B1",)}, "全定時×固定B1入口が不足")
    need(availability == result["定時の候補と入力可用性"], "候補/未知理由の保存集計差")
    for key, identities in diagnostics.items():
        for identity, row in identities.items():
            need(identity in supplied and supplied[identity]["entry_policy"] == "B1", "実新規に対応する当時B1候補がない")
            need(row["lot"]["structure_anchor"] == supplied[identity]["structure_anchor"], "候補の固定アンカーと実玉が不一致")
            need(number(row["entry_order"]["request_time"]) == number(supplied[identity]["at"]), "定時以外の実新規")
    return availability


def verify_audits(paths: dict, values: dict, result: dict, rows: dict, diagnostics: dict, sessions: list[str]) -> dict:
    """
    機能: 会計・原板・Viewerの対象集合と保存SHAを結合する。
    引数: paths/values (dict) は明示パスと本文、result/rows/diagnostics (dict) は検査済集計、sessions (list[str]) は対象場。
    返り値: dict はKey別の独立保護規範合計。
    """
    cash, raw, viewer, catalog = [values[n] for n in ("cash_audit", "raw_audit", "viewer_audit", "catalog")]
    need(count(cash["会計数"]) == 528 and count(cash["不一致数"]) == 0, "全会計照合が未完")
    checks = {(r["session"], r["key"]): r for r in cash["照合"]}
    need(len(checks) == len(cash["照合"]) == 528 and set(checks) == set(rows), "会計照合対象差")
    for identity, check in checks.items():
        need(number(check["現金円"]) == number(rows[identity]["metrics"]["net_pnl_yen"]) and number(check["粗損益円"]) == number(rows[identity]["metrics"]["gross_pnl_yen"]) and number(check["費用円"]) == number(rows[identity]["metrics"]["total_cost_yen"]) and count(check["残量"]) == 0, "会計照合と正本差")
        count(check["約定数"])
    need(count(raw["試行"]) == 83 and raw["成功"] is True and count(raw["場数"]) == 66 and count(raw["不一致数"]) == 0 and not raw["不一致"], "原板監査が未完又は不一致")
    need(raw["入力台帳SHA256"] == sha(paths["manifest"]), "原板監査の台帳SHA差")
    raw_rows = {r["session"]: r for r in raw["対象場"]}
    need(len(raw_rows) == len(raw["対象場"]) == 66 and set(raw_rows) == set(sessions), "原板監査66場差")
    normative = {key: Counter() for key in KEYS}
    for session in sessions:
        record = raw_rows[session]
        need(record["不一致数"] == 0 and not record["不一致"] and record["再生結果SHA256"] == result["再生結果SHA256"][session + ".json"], "原板監査の再生指紋差")
        detail = record["診断"]
        need(detail["場"] == session and detail["JSON本文走査回数"] == 1 and set(detail["全玉費用後評価"]) == set(KEYS) and set(detail["利益床の独立規範"]) == set(KEYS), "原板診断の対象差")
        for key in KEYS:
            full = detail["全玉費用後評価"][key]
            actual = {r["lot"]["id"]: r["lot"] for identity, r in diagnostics[key].items() if identity[0] == session}
            need(len(full) == len(actual) and {r["実玉ID"] for r in full} == set(actual), "原板の所有集合差")
            for entry in full:
                lot = actual[entry["実玉ID"]]
                need(entry["残量"] == 0 and entry["初回数量"] == 100 and number(entry["完結部分純額円"]) == number(lot["net_pnl"]), "原板の全玉数量又は純額差")
                need((entry["全玉初回正益"] is not None) == lot["whole_flag"] and entry["保存残玉旗"] == lot["flag"], "原板の全玉/残玉旗差")
                need(entry["全玉正益後に最後赤字"] == (lot["whole_flag"] and number(lot["net_pnl"]) < 0), "原板の旗後赤字差")
            counts = detail["利益床の独立規範"][key]
            for name, val in counts.items():
                normative[key][name] += count(val)
            for name in ("予約不足原行", "予約不足数量", "利確要求不足原行", "構造要求不足原行"):
                need(counts[name] == 0, "独立規範の保護又は利確要求不足")
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog", "Viewer一覧形式差")
    resources = catalog["resources"]
    resource_map = {r["id"]: r for r in resources}
    expected_ids = {f"83_{key}_{session}" for session, key in rows}
    need(len(resource_map) == len(resources) == 528 and set(resource_map) == expected_ids, "Viewer528資源の差")
    need(count(viewer["試行"]) == 83 and viewer["成功"] is True and count(viewer["予定資源"]) == count(viewer["完了資源"]) == 528 and count(viewer["不一致数"]) == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "Viewer全件成功が必要")
    need(viewer["結果SHA256"] == sha(paths["result"]) and viewer["一覧SHA256"] == sha(paths["catalog"]), "Viewerの正本SHA差")
    need(viewer["入力SHA256前"] == viewer["入力SHA256後"], "Viewer読取中の入力変更")
    current_files = {str(paths["result"].resolve()), str(paths["catalog"].resolve())}
    for resource in resources:
        session, key = next((s, k) for s, k in rows if resource["id"] == f"83_{k}_{s}")
        need((resource["symbol"], resource["session"], resource["method_id"], resource["product"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", session, key.split("_D")[0], "NK225micro", 10, "trades", "net"), "Viewer資源metadata差")
        path = (paths["catalog"].parent / resource["pnl_path"]).resolve()
        need(path.is_relative_to(paths["catalog"].parent), "約定参照が成果物外です")
        current_files.add(str(path))
    need(set(viewer["入力SHA256前"]) == current_files, "Viewer入力指紋集合差")
    for name, wanted in viewer["入力SHA256前"].items():
        need(sha(Path(name)) == wanted, "Viewer照合後の正本変更")
    by_id = {r["id"]: r for r in viewer["資源"]}
    need(len(by_id) == len(viewer["資源"]) == 528 and set(by_id) == expected_ids, "Viewer資源別の完了集合差")
    for session, key in rows:
        v = by_id[f"83_{key}_{session}"]
        need(v["完了"] is True and v["不一致数"] == 0 and v["APIエラー"] is None, "Viewer個別未完了")
        need(number(v["API費用後円"]) == number(v["原純額円"]) == number(rows[session, key]["metrics"]["net_pnl_yen"]), "Viewer個別純額差")
    need(raw["監査コードSHA256"] == sha(Path(__file__).with_name("原板監査.py")) and raw["固定80監査SHA256"] == sha(ROOT / "scripts/FAR後期15分移植/原板照合.py"), "原板監査コードSHA差")
    need(raw["派生元81監査SHA256"] == sha(ROOT / "scripts/定時の現在根拠と部分利益保護/原板監査.py"), "原板監査の派生元SHA差")
    need(viewer["監査コードSHA256"] == sha(Path(__file__).with_name("表示監査.py")), "Viewer監査コードSHA差")
    return normative


def prepare(paths: dict, study: Path) -> dict:
    """
    機能: 明示小型入力の集合・指紋・会計・監査を全て検査する。
    引数: paths (dict[str,Path]) は10正本、study (Path) は試行フォルダ。
    返り値: dict は照合済みの帳票入力。市場原板を暗黙に読まない。
    """
    required = ("result", "catalog", "cash_audit", "raw_audit", "viewer_audit", "condition", "input_reference", "manifest", "trades", "grids")
    need(set(paths) == set(required), "明示入力の不足又は余剰")
    hashes = {str(p.resolve()): sha(p) for p in paths.values()}
    values = {n: read_json(paths[n]) for n in required if n not in ("trades", "grids")}
    sessions = [r["id"] for r in values["manifest"]["sessions"]]
    need(len(sessions) == len(set(sessions)) == 66, "一意の66場台帳が必要")
    deps = fixed_dependencies(values["condition"], values["input_reference"], paths["manifest"])
    result = values["result"]
    need(result["入力台帳SHA256"] == sha(paths["manifest"]), "結果台帳SHA差")
    rows = verify_summary(result, sessions)
    diagnostics = verify_diagnostics(compressed_rows(paths["trades"]), result, sessions)
    grids = compressed_rows(paths["grids"])
    availability = verify_grids(grids, result, diagnostics, sessions)
    auxiliary = verify_auxiliary(grids)
    normative = verify_audits(paths, values, result, rows, diagnostics, sessions)
    settings = (study / "設定と結果.md").read_text(encoding="utf-8")
    verify_table(settings, study)
    need(settings.count(BEGIN) == settings.count(END) == 1 and STATUS in settings, "固定設定マーカー差")
    need(all(sha(Path(p)) == s for p, s in hashes.items()), "帳票読取中の入力変更")
    return {"paths": paths, "values": values, "sessions": sessions, "result": result, "rows": rows,
        "diagnostics": diagnostics, "availability": availability, "auxiliary": auxiliary,
        "normative": normative, "input_sha": hashes, "dependencies": deps, "settings": settings}


def result_block(data: dict) -> str:
    """
    機能: 全8案の費用後額と正益後赤字を同じ結果欄へ整形する。
    引数: data (dict) は照合済み帳票入力。
    返り値: str は設定表の専用マーカーへ入れるMarkdown。
    """
    lines = ["正式66場・構造否定2種×利益配分2種×遅延2種。入口は82B1固定、全場既使用。", "",
        "| ID | 遅延 | 費用後損益円 | 最大DD円 | 赤字場 | 完結玉 | 全玉正益後赤字 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        s = data["result"]["比較"][key]
        lines.append(f"| {key} | {s['追加遅延秒']} | {amount(s['費用後損益円'])} | {amount(s['最大DD円'])} | {s['赤字場数']}/66 | {s['完結玉']} | {ratio(s['全玉旗後赤字'], s['全玉旗'])} |")
    if not sum(s["完結玉"] for s in data["result"]["比較"].values()):
        lines.extend(["", "実新規0であり、0損益を構造否定・利益配分の改善としない。両方式の市場効果は未評価。"])
    lines.extend(["", "[全条件・構造metadata・利益前後・同実入口と参加差](設定と結果.md)。G2の建値床は費用後黒字を保証しない。"])
    return "\n".join(lines)


def render_readme(data: dict, study: Path) -> str:
    """
    機能: 入口を固定した2×2の結果・構造・配分・参加差を記述する。
    引数: data (dict) は照合済み正本、study (Path) は試行フォルダ。
    返り値: str はREADME全文。図や全原行の重複転記はしない。
    """
    result, paths = data["result"], data["paths"]
    total = sum(s["完結玉"] for s in result["比較"].values())
    main_black = [k for k in KEYS if k.endswith("D0") and result["比較"][k]["費用後損益円"] > 0]
    outcome = "実新規0、保護の効果は未評価。" if not total else "主費用で黒字の案はなかった。" if not main_black else "主費用で観測黒字の案があったが、既使用期間の探索であり安定利益は未確認。"
    text = ["# 00083：構造否定と利益配分", "", "2026-11-07。" + outcome,
        "全66既使用場、固定82B1入口を同じにし、正益前の構造否定S0/S1と正益後の利益配分G1/G2を2×2で比較した。主約定と追加価格時計1秒を別にする。旧70%・125/250先着・待ち50%で棄却しない。", "",
        "## 仮説と固定条件", "", "[82](../00082_チャートの現在性と補助確認/README.md)では正益前の大きな損失と平均利益の小ささが残った。今回は入口選別を変えず、入口根拠の価格線を失った時の否定と、部分確定して守る量／継続へ残す量を分ける。S0G1がATR・部分保護の対照になる。元FAR三手法の部品を使った別の複合仮説で、元売買列の同値再現ではない。", "",
        "新規は初回を除くDay09:15..15:15、Night17:30..翌05:30の15分枠。NY09:30の前後15分は静観し前窓終了で返済要求、場末15:35/05:50に要求する。保護・技法失敗は全原行で連続、売買は符号反転で同じ条件。", "",
        "82B1の共通主軸は3分MACDhist増分・終値のEMA8回復・0..1ATR取得位置と、3/15分EMA順行又は実際の前足回復＋RSI増分・新鮮な帯量支持。個別既知の短秒/OFI反対を拒否し、既知失速時だけOFI又は構造支持を追加確認する。未知を0・反対・支持へ置換しない。複数技法は方向・現在進行・位置・数量の役割を分け、独立票として数えない。", "",
        "新規100micro固定・片側100・同時一建玉の研究尺度で、推奨数量ではない。1枚10円/pt、片道手数料11円＋想定滑り5pt、往復122円。次正常ラージBBOを価格代理とし、追加価格時計1秒は次の適格原行まで待つ別約定列。同約定滑り0/10ptは費用感応である。", "",
        "| 政策 | 正益前の否定 | 正益後の配分 |", "| --- | --- | --- |",
        "| S0G1 | 既存ATR追尾・125pt・確定技法失敗 | 部分利確、実確定益だけの残玉予算 |",
        "| S1G1 | 要求時EMA8_3固定線を既存床へ追加 | G1 |",
        "| S0G2 | S0 | 全量を最低建値とATRで追尾、部分利確なし |",
        "| S1G2 | S1 | G2 |", "",
        "Dはceil5(新規時ATR3)を15..125ptへ制限、未知125。全案で最高方向幅からDを引く床を正益前から追尾し、床を下げない。S1は要求時に確定公開済みだったEMA8価格を固定し、実新規価格Eへの方向床s×(固定線−E)をmaxで重ねる。将来EMAや約定滑りで線を移さず、未知は線を創作しない。既に線を割った実約定も隠さず、正常保有観測で即否定要求する。", "",
        "全案で現在単価益10×方向幅−122円がstrict正になった原行に利益追尾を起動し、最低床は建値0pt。G1は部分注文の全量約定後だけ実確定純益を予算へ入れ、G2は部分利確・確定益予算を使わず全量を継続する。受理返済の取消・延期、未約定益の予算化は行わない。**G2の建値床は費用後黒字を保証せず、建値返済でも往復費用や次板悪化で赤字となり得る。** 放置の防止と黒字保証を混同しない。[検証計画](検証計画.md)・[設定IDと版5表](設定と結果.md)を数式の正本とする。", "",
        "## 結果", "", result_block(data), "",
        "[閲覧補足](閲覧補足.md)に証拠と閲覧方法、[出口差の診断](出口差の診断.md)に同じ実入口で救った損失と失った利益、[正益後赤字の診断](正益後赤字の診断.md)に利益観測後の赤字化の内訳を整理した。", "",
        "| ID | 粗損益円 | 費用円 | 正益未観測損益円 | 正益観測損益円 | 残玉正益後赤字 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        s = result["比較"][key]
        text.append(f"| {key} | {amount(s['総計']['gross_pnl_yen'])} | {amount(s['総計']['total_cost_yen'])} | {amount(s['正益未観測の損益円'])} | {amount(s['正益観測の損益円'])} | {ratio(s['残玉旗後赤字'], s['残玉旗'])} |")
    text.extend(["", "残玉旗は1枚の費用後現在益、全玉旗は部分確定を含む取引全体の純額。返済費用込みの場内DDと場末確定損益の累積を区別し、Viewerとは全約定と最終flat純額を照合する。", "",
        "| ID | Day損益円 | Night損益円 | 赤字日/日数 | 同約定滑り0pt円 | 同約定滑り10pt円 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for key in KEYS:
        s = result["比較"][key]
        day = sum(number(r["metrics"]["net_pnl_yen"]) for r in result["場別"] if r["key"] == key and r["session"].endswith("Day"))
        night = number(s["費用後損益円"]) - day
        text.append(f"| {key} | {amount(day)} | {amount(night)} | {s['赤字日数']}/{s['日数']} | {amount(s['同約定0pt損益円'])} | {amount(s['同約定10pt損益円'])} |")
    text.extend(["", "## 同じ実入口の出口差と参加差", "", "比較は[A,B]のB−A。共通候補でも時刻・価格・数量の変化を別にし、片側だけの参加と合算しない。", "",
        "| 比較 | A / B | 同実入口 | 同入口A円 | 同入口B円 | 出口差円 | 取得変更 | Aのみ件/円 | Bのみ件/円 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"])
    for name, d in result["出口間の同実新規分解"].items():
        text.append(f"| {name} | {' / '.join(d['比較'])} | {d['同実新規']} | {amount(d['同実新規A損益円'])} | {amount(d['同実新規B損益円'])} | {amount(d['同実新規出口差円'])} | {d['共通だが取得変更']} | {d['Aのみ']} / {amount(d['Aのみ損益円'])} | {d['Bのみ']} / {amount(d['Bのみ損益円'])} |")
    text.extend(["", "## 構造線と利益配分", "", "構造線は要求時固定の値。利確片の到達metadataは各約定時のsnapshotであり、その後の最終lot到達を過去の片へ転記しない。", "",
        "| ID | 線既知/未知 | 活性 | 既に割れた新規 | 線到達玉 | 構造返済要求 | 部分要求/約定枚 | 予算床玉 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |"])
    for key in KEYS:
        m = result["比較"][key]["総計"]
        text.append(f"| {key} | {m['structure_known_entries']}/{m['structure_unknown_entries']} | {m['structure_activated_lots']} | {m['structure_entry_breached_lots']} | {m['structure_hit_lots']} | {m['structure_exit_orders']} | {m['harvest_quantity']}/{m['harvest_filled_quantity']} | {m['cash_floor_activated_lots']} |")
    text.extend(["", "## 候補と判断", "", "B1の定時候補は一度だけ生成し全会計へ供給する。保有・返済待ちによる後続参加の違いは、各会計の判断と実新規で別集計する。", "",
        "| 入口 | 全定時 | 時計許可 | 方向判定成立 | 候補供給 |", "| --- | ---: | ---: | ---: | ---: |"])
    for policy, a in data["availability"].items():
        text.append(f"| {policy} | {a['全定時']} | {a['時計許可']} | {a['方向判定成立']} | {a['候補生成']} |")
    text.extend(["", "| ID | 新規要求 | 保有継続 | 処理中 | 待ち | 判定不能 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for key in KEYS:
        a = result["比較"][key]["判断"]
        text.append(f"| {key} | " + " | ".join(str(a.get(n, 0)) for n in ("新規要求", "保有継続", "処理中", "待ち", "判定不能")) + " |")
    text.extend(["", "| 補助・既知性の分類 | B1方向×定時件数 |", "| --- | ---: |"])
    for name, n in sorted(data["auxiliary"]["B1"].items()):
        text.append(f"| {name} | {n} |")
    text.extend(["", "## 独立照合と再現", "",
        "保存会計528件、原板66場、Viewer528資源が全件成功した正本だけを帳票へ結ぶ。独立規範の予約不足・利確要求不足・構造要求不足は全案0を必要とする。Rの保存metadata照合は元指標や初動構造の独立再生成ではない。", "",
        "| ID | 正常保有原行 | 返済義務原行 | 構造活性原行 | 構造到達原行 | 保護予約不足 | 構造不足 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for key in KEYS:
        n = data["normative"][key]
        text.append(f"| {key} | {n['正常保有原行']} | {n['返済義務原行']} | {n['構造活性原行']} | {n['構造到達原行']} | {n['予約不足原行']} | {n['構造要求不足原行']} |")
    references = (("result", "結果正本"), ("catalog", "Viewer528資源"), ("cash_audit", "保存会計照合"), ("raw_audit", "原板・保護規範"), ("viewer_audit", "Viewer数値監査"),
        ("condition", "固定条件"), ("input_reference", "入力参照"), ("manifest", "66場固定台帳"), ("trades", "圧縮玉診断"), ("grids", "圧縮定時判断"))
    text.extend(["", " · ".join(link(study, paths[n], label) for n, label in references), "",
        "実行コードは[scripts/構造否定と利益配分](../../scripts/構造否定と利益配分/)へ分離し、旧80/81/82と兄弟repoを変更しない。batch CLIで16worker再生し、会計・原板・Viewerを別照合する。帳票は小型正本だけを読み、原板読取0・新売買再生0で生成する。", "",
        "全66場は既使用で、8会計や接続2場を独立標本へ水増ししない。正常ラージBBOへの全量micro約定・一定滑りを仮定し、実通信、板深さ消費、mini/microの約定順位、証拠金制約は未実証。価格時計は受信時計と同一ではなく、追加1秒が実時間1秒後を意味するとは限らない。ATR系列自体の独立実装照合と保存全玉峰/谷の個別全値照合は範囲外。", "",
        "正益後赤字はG1/G2とも残し、要求前の不足、要求後の悪化、費用と正益前損失を分ける。早い構造否定で回復する勝ちを失う場合や、全量継続で小利確を失う場合も反証にする。ここでの総額差を単独指標の効果や未知期間での安定利益へ読み替えない。", ""])
    command = ['& "work/venvs/technical-tree/Scripts/python.exe" -B -X utf8 "scripts/構造否定と利益配分/レポート.py" --check `', '  --study "' + Path(os.path.relpath(study, ROOT)).as_posix() + '" `']
    for i, (name, _) in enumerate(references):
        command.append('  --' + name.replace("_", "-") + ' "' + Path(os.path.relpath(paths[name], ROOT)).as_posix() + '"' + (' `' if i < len(references) - 1 else ''))
    text.extend(["ルートPowerShellから保存帳票の同値を確認する。正式生成は同じ明示入力で--checkを--runへ置換する。", "", "```powershell", *command, "```", "", "[帳票生成証拠](レポート生成証拠.json)へ全入力・依存・コード・出力のSHAを保存する。", ""])
    return "\n".join(text)


def generate(paths: dict, study: Path, check: bool) -> dict:
    """
    機能: 全照合後にREADMEと専用結果マーカーだけを生成又は確認する。
    引数: paths (dict) は明示10入力、study (Path) は出力、check (bool) は読取確認か。
    返り値: dict は生成証拠。元正本とマーカー外は変更しない。
    """
    data = prepare(paths, study)
    left, rest = data["settings"].split(BEGIN)
    _, right = rest.split(END)
    settings = left + BEGIN + "\n" + result_block(data) + "\n" + END + right
    readme = render_readme(data, study)
    proof = {"試行": 83, "成功": True, "場数": 66, "会計数": 528, "Viewer資源数": 528,
        "入力パス": {n: str(p.resolve()) for n, p in paths.items()}, "入力SHA256": data["input_sha"],
        "固定依存SHA256": data["dependencies"], "生成コードSHA256": sha(Path(__file__)),
        "設定マーカー外SHA256": hashlib.sha256((left + BEGIN + END + right).encode("utf-8")).hexdigest(),
        "出力SHA256": {"README.md": hashlib.sha256(readme.encode("utf-8")).hexdigest(), "設定と結果.md": hashlib.sha256(settings.encode("utf-8")).hexdigest()},
        "本処理の市場原板読取": 0, "新売買再生": 0}
    if check:
        need((study / "README.md").read_text(encoding="utf-8") == readme and (study / "設定と結果.md").read_text(encoding="utf-8") == settings, "保存帳票と生成値の差")
        need(read_json(study / "レポート生成証拠.json") == proof, "生成証拠の差")
    else:
        (study / "README.md").write_text(readme, encoding="utf-8", newline="\n")
        (study / "設定と結果.md").write_text(settings, encoding="utf-8", newline="\n")
        (study / "レポート生成証拠.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return proof


def fake_inputs(base: Path) -> tuple[Path, dict]:
    """
    機能: 市場入力を開かず、66場・528会計・全定時の人工正本を組み立てる。
    引数: base (Path) はwork配下の専用一時領域。
    返り値: tuple[Path,dict] は人工試行と明示入力パス。
    """
    study = base / "人工試行"
    output = study / "成果物"
    output.mkdir(parents=True)
    paths = {name: output / filename for name, filename in (("result", "結果.json"), ("catalog", "一覧.resources.json"), ("cash_audit", "約定会計照合.json"), ("trades", "取引診断.jsonl.gz"), ("grids", "定時判断.jsonl.gz"))}
    paths.update({name: study / filename for name, filename in (("raw_audit", "原板監査.json"), ("viewer_audit", "Viewer監査.json"), ("condition", "条件.json"), ("input_reference", "入力参照.json"), ("manifest", "人工台帳.json"))})

    def save(path: Path, value: dict) -> None:
        """
        機能: 人工辞書を有限JSONで保存する。
        引数: path (Path) は人工領域、value (dict) は本文。
        返り値: None。
        """
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    sessions = [(datetime(2026, 1, 1) + timedelta(days=i)).date().isoformat() + "_" + window for i in range(33) for window in ("Day", "Night")]
    save(paths["manifest"], {"source_root": str(base / "存在しない市場"), "sessions": [{"id": session} for session in sessions]})
    dependency = base / "人工依存.txt"
    dependency.write_text("人工依存。市場ではない。\n", encoding="utf-8")
    deps = {str(dependency): sha(dependency)}
    reference = {"試行": 83, "入力台帳": str(paths["manifest"]), "入力台帳SHA256": sha(paths["manifest"]), "入力場数": 66, "入力ファイル数": 396, "全場既使用": True, "固定80採用版": 2, "固定80依存指紋": deps, "固定81依存指紋": deps, "固定82依存指紋": deps, "固定81条件SHA256": sha(ROOT / "study/00081_定時の現在根拠と部分利益保護/条件.json"), "固定82条件SHA256": sha(ROOT / "study/00082_チャートの現在性と補助確認/条件.json"), "固定80条件SHA256": sha(ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/条件.json")}
    condition = {"試行": 83, "入力台帳SHA256": sha(paths["manifest"]), "入力場数": 66, "全場既使用": True, "modes": list(MODES), "keys": list(KEYS), "約定追加価格時計遅延秒": [0, 1], "新規数量micro枚": 100, "片側上限": 100, "point_value": 10, "片道手数料円": 11, "片道滑りpt": 5, "主往復費用円毎枚": 122, "G1悪化余裕pt": 10, "G1全玉予算目標円": 1, "同時一建玉": True, "新損益前固定": True, "固定80依存": deps, "固定81依存": deps, "固定82依存": deps, "コードと依存SHA256": deps}
    condition.update({"実行ファイル": str(dependency), "実行ファイルSHA256": sha(dependency)})
    save(paths["input_reference"], reference)
    save(paths["condition"], condition)
    zero_metric = {name: 0 for name in ("net_pnl_yen", "cash_yen", "gross_pnl_yen", "total_cost_yen", "commission_yen", "slippage_yen", "open_quantity", "pending_entry_quantity", "reserved_exit_quantity", "entry_quantity", "exit_quantity", "closed_lots", "max_drawdown_yen", "min_equity_yen", "equity_peak_yen", "harvest_orders", "harvest_quantity", "harvest_filled_quantity", "harvest_done_lots", "cash_floor_activated_lots", "funding_failure_lots", "whole_profit_flags", "whole_flag_after_loss_lots", "structure_known_entries", "structure_unknown_entries", "structure_activated_lots", "structure_entry_breached_lots", "structure_hit_lots", "structure_exit_orders")}
    result = {"試行": 83, "場数": 66, "全場既使用": True, "入力台帳SHA256": sha(paths["manifest"]), "再生結果SHA256": {s + ".json": hashlib.sha256(s.encode()).hexdigest() for s in sessions}, "比較": {}, "場別": [], "出口間の同実新規分解": {}, "定時の候補と入力可用性": {p: {"全定時": 0, "時計許可": 0, "方向判定成立": 0, "候補生成": 0, "判定項目": {"共通:人工": {"方向数": 0, "既知": 0, "成立": 0, "未知": 0}}, "支持未知理由": {"own_reason:人工未準備": 0}} for p in ("B1",)}}
    cash = {"会計数": 528, "不一致数": 0, "照合": []}
    catalog = {"schema_version": 1, "path_base": "catalog", "resources": []}
    viewer_rows = []
    for key in KEYS:
        mode, delay = key.split("_D")
        result["比較"][key] = {"mode": mode, "追加遅延秒": int(delay), "費用後損益円": 0, "最大DD円": 0, "全場": 66, "赤字場数": 0, "黒字場数": 0, "同値場数": 66, "赤字日数": 0, "日数": 33, "日別円": {s[:10]: 0 for s in sessions}, "完結玉": 0, "残玉旗": 0, "残玉旗後赤字": 0, "全玉旗": 0, "全玉旗後赤字": 0, "正益未観測の損益円": 0, "正益観測の損益円": 0, "同約定0pt損益円": 0, "同約定10pt損益円": 0, "総計": deepcopy(zero_metric), "返済理由別枚数": {}, "返済理由別損益円": {}, "判断": {"待ち": 2442}}
        for session in sessions:
            result["場別"].append({"session": session, "key": key, "mode": mode, "delay": int(delay), "metrics": deepcopy(zero_metric), "累積損益円": 0, "判断": {"待ち": 25 if session.endswith("Day") else 49}})
            cash["照合"].append({"session": session, "key": key, "約定数": 0, "現金円": 0, "粗損益円": 0, "費用円": 0, "残量": 0})
            name = f"約定/D{delay}/{mode}/{session}.trades.jsonl"
            trade_path = output / name
            trade_path.parent.mkdir(parents=True, exist_ok=True)
            trade_path.write_text("", encoding="utf-8")
            identity = f"83_{key}_{session}"
            catalog["resources"].append({"id": identity, "symbol": "NK225", "session": session, "method_id": mode, "product": "NK225micro", "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": name, "market_path": f"NK225/{session}/book.jsonl.gz"})
            viewer_rows.append({"id": identity, "完了": True, "不一致数": 0, "不一致": [], "APIエラー": None, "API費用後円": 0, "原純額円": 0})
    for delay in (0, 1):
        for label, a, b in comparison_pairs():
            result["出口間の同実新規分解"][f"{label}_D{delay}"] = {"比較": [f"{a}_D{delay}", f"{b}_D{delay}"], **{name: 0 for name in ("同実新規", "共通だが取得変更", "同実新規A損益円", "同実新規B損益円", "同実新規出口差円", "Aのみ", "Bのみ", "Aのみ損益円", "Bのみ損益円", "取得変更A損益円", "取得変更B損益円")}}
    grid_rows = []
    for session in sessions:
        start = datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
        first = start + (timedelta(hours=9, minutes=15) if session.endswith("Day") else timedelta(hours=17, minutes=30))
        length = 25 if session.endswith("Day") else 49
        grids = []
        for i in range(length):
            at = (first + timedelta(minutes=15*i)).timestamp()
            for policy in ("B1",):
                evidence = {"time": 0, **{side: {"own_reason": "人工未準備", "peer_reason": "", "ofi_reason": ""} for side in ("buy", "sell")}}
                auxiliary = {field: {"known": False, "state": "未知", "reason": "人工未知"} for field in ("five", "fifteen", "ofi")}
                auxiliary.update({name: False for name in ("slowdown_known", "slowdown", "structure_known", "structure_support", "pressure_clear")})
                decision = {"at": at, "policy": policy, "allowed": False, "side": 0, "quote": {"time": 0}, "technical": {"bar3_end": 0, "bar15_end": 0},
                    "chart_pair": {"previous_close3": 0, "previous_ema8_3": 0, "previous_bar3_end": 0, "previous3_known": False}, "evidence": evidence,
                    "directions": [{"side": side, "required_unknown": True, "auxiliary": deepcopy(auxiliary), "checks": [{"group": "共通", "id": "人工", "known": False, "passed": False}]} for side in (1, -1)]}
                grids.append({"at": at, "entry_policy": policy, "clock_allowed": True, "candidate_accepted": False, "decision": decision, "structure_anchor": {"known": False, "price": 0, "at": 0, "bar_end": 0, "reason": "人工未知"}})
                available = result["定時の候補と入力可用性"][policy]
                available["全定時"] += 1
                available["時計許可"] += 1
                available["判定項目"]["共通:人工"]["方向数"] += 2
                available["判定項目"]["共通:人工"]["未知"] += 2
                available["支持未知理由"]["own_reason:人工未準備"] += 2
        grid_rows.append({"session": session, "grid_decisions": grids})
    with gzip.open(paths["trades"], "wt", encoding="utf-8"):
        pass
    with gzip.open(paths["grids"], "wt", encoding="utf-8") as stream:
        for row in grid_rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    save(paths["result"], result)
    save(paths["catalog"], catalog)
    save(paths["cash_audit"], cash)
    norms = {name: 0 for name in ("正常保有原行", "正益後保有原行", "床到達原行", "125pt到達原行", "cash床原行", "返済義務原行", "予約不足原行", "予約不足数量", "利確要求義務原行", "利確要求不足原行", "利確量検査", "構造活性原行", "構造到達原行", "構造要求不足原行")}
    raw = {"試行": 83, "成功": True, "場数": 66, "不一致数": 0, "不一致": [], "入力台帳SHA256": sha(paths["manifest"]), "監査コードSHA256": sha(Path(__file__).with_name("原板監査.py")), "固定80監査SHA256": sha(ROOT / "scripts/FAR後期15分移植/原板照合.py"), "派生元81監査SHA256": sha(ROOT / "scripts/定時の現在根拠と部分利益保護/原板監査.py"), "対象場": [{"session": s, "再生結果SHA256": result["再生結果SHA256"][s + ".json"], "不一致数": 0, "不一致": [], "診断": {"場": s, "JSON本文走査回数": 1, "全玉費用後評価": {k: [] for k in KEYS}, "利益床の独立規範": {k: deepcopy(norms) for k in KEYS}}} for s in sessions]}
    save(paths["raw_audit"], raw)
    viewed_paths = [paths["result"], paths["catalog"]] + [output / r["pnl_path"] for r in catalog["resources"]]
    viewed_hashes = {str(p): sha(p) for p in viewed_paths}
    save(paths["viewer_audit"], {"試行": 83, "成功": True, "完了資源": 528, "予定資源": 528, "不一致数": 0, "APIエラー": [], "入力不変": True, "入力SHA256前": viewed_hashes, "入力SHA256後": viewed_hashes, "結果SHA256": sha(paths["result"]), "一覧SHA256": sha(paths["catalog"]), "監査コードSHA256": sha(Path(__file__).with_name("表示監査.py")), "資源": viewer_rows})
    setting_path = ROOT / "study/00083_構造否定と利益配分/設定と結果.md"
    setting = setting_path.read_text(encoding="utf-8")
    for method in read_json(ROOT / "scripts/レポート/手法カタログ_版5.json")["methods"]:
        actual = ROOT / method["source"]
        original = Path(os.path.relpath(actual, setting_path.parent)).as_posix()
        derived = Path(os.path.relpath(actual, study)).as_posix()
        setting = setting.replace("](" + original + ")", "](" + derived + ")")
    (study / "設定と結果.md").write_text(setting, encoding="utf-8")
    return study, paths


def artificial_lots(result: dict, session: str) -> tuple[list[dict], dict]:
    """
    機能: 同じ実入口からG1部分/G2全量と後の構造到達を手計算で作る。
    引数: result (dict) は人工空集計、session (str) は人工場。
    返り値: tuple[list[dict],dict] は非0玉診断と対応した比較欄。
    """
    result = deepcopy(result)
    rows = []
    for key in KEYS:
        active, partial = key.startswith("S1"), key.split("_D")[0].endswith("G1")
        anchor = {"known": True, "price": 9970, "at": 9, "bar_end": 8, "reason": "人工の要求時固定EMA"}
        static = {"structure_anchor": anchor, "structure_active": active, "structure_floor": -30 if active else None,
            "structure_activated_at": 10 if active else None, "structure_entry_breached": False}
        final_hit = {"structure_first_hit_at": 14 if active else None, "structure_first_hit_index": 14 if active else -1}
        before_hit = {"structure_first_hit_at": None, "structure_first_hit_index": -1}
        pid, rid = key + "_玉", "人工B1共通候補"
        lot = {"id": pid, "reference_id": rid, "side": 1, "entry_price": 10000, "entry_time": 10, "entry_index": 10,
            "initial_quantity": 100, "closed_quantity": 100, "quantity": 0, "flag": True, "whole_flag": True,
            "net_pnl": 15300 if partial else 37800, "cash_floor_active": partial, "cash_floor": 0 if partial else None,
            "cash_floor_at": 12 if partial else None, "funding_failed": False, "harvest_target": 75 if partial else 0,
            "harvest_filled": 75 if partial else 0, "harvest_done_at": 12 if partial else None, **static, **final_hit}
        entry = {"kind": "entry", "quantity": 100, "filled_quantity": 100, "position_id": pid, "reference_id": rid,
            "request_time": 9, "structure_anchor": anchor, "structure_active": False, "structure_floor": None, "harvest": False, "reason": "人工新規"}
        closed = []
        orders = [entry]
        if partial:
            closed.append({"quantity": 75, "pnl5": 5850, "reason": "人工部分", "exit_time": 12, **static, **before_hit})
            orders.append({"kind": "exit", "quantity": 75, "harvest": True, "reason": "人工部分", "structure_anchor": anchor, "structure_active": active, "structure_floor": static["structure_floor"]})
        closed.append({"quantity": 25 if partial else 100, "pnl5": 9450 if partial else 37800, "reason": "人工最終", "exit_time": 15, **static, **final_hit})
        orders.append({"kind": "exit", "quantity": 25 if partial else 100, "harvest": False, "reason": "人工最終", "structure_anchor": anchor, "structure_active": active, "structure_floor": static["structure_floor"]})
        rows.append({"session": session, "key": key, "lot": lot, "entry_order": entry, "orders": orders, "closed": closed})
        s = result["比較"][key]
        s.update({"完結玉": 1, "費用後損益円": lot["net_pnl"], "残玉旗": 1, "残玉旗後赤字": 0, "全玉旗": 1, "全玉旗後赤字": 0,
            "正益観測の損益円": lot["net_pnl"], "正益未観測の損益円": 0,
            "返済理由別枚数": {"人工部分": 75, "人工最終": 25} if partial else {"人工最終": 100},
            "返済理由別損益円": {"人工部分": 5850, "人工最終": 9450} if partial else {"人工最終": 37800}})
        s["総計"].update({"harvest_orders": int(partial), "harvest_quantity": 75 if partial else 0, "harvest_filled_quantity": 75 if partial else 0,
            "cash_floor_activated_lots": int(partial), "funding_failure_lots": 0, "structure_known_entries": 1, "structure_unknown_entries": 0,
            "structure_activated_lots": int(active), "structure_entry_breached_lots": 0, "structure_hit_lots": int(active), "structure_exit_orders": 0,
            "whole_profit_flags": 1, "whole_flag_after_loss_lots": 0})
    for d in result["出口間の同実新規分解"].values():
        a, b = [result["比較"][k]["費用後損益円"] for k in d["比較"]]
        d.update({"同実新規": 1, "同実新規A損益円": a, "同実新規B損益円": b, "同実新規出口差円": b - a})
    return rows, result


def self_test() -> dict:
    """
    機能: 人工528会計・全B1定時の生成と保存破損の拒否を確認する。
    引数: なし。work内の一時領域だけを使う。
    返り値: dict は人工の成功項目。原板・新売買・APIはいずれも0。
    """
    checks = []
    with tempfile.TemporaryDirectory(prefix="83帳票人工_", dir=ROOT / "work") as temp:
        study, paths = fake_inputs(Path(temp).resolve())
        original_settings = (study / "設定と結果.md").read_text(encoding="utf-8")
        generate(paths, study, False)
        generate(paths, study, True)
        need("実新規0" in (study / "README.md").read_text(encoding="utf-8"), "0取引の未評価表示が必要")
        need(original_settings.split(BEGIN)[0] == (study / "設定と結果.md").read_text(encoding="utf-8").split(BEGIN)[0], "固定設定の冒頭が変化")
        checks += ["人工528会計・全B1定時の正式生成同値", "0取引を未評価表示", "設定マーカー外不変"]

        def reject_json(name: str, mutate: object, label: str) -> None:
            """
            機能: 人工JSONの破損をprepareが拒否することを確認する。
            引数: name/label (str) は入力名と名称、mutate (callable) は人工改変。
            返り値: None。元入力へ戻し、未検出なら例外。
            """
            path = paths[name]
            before = path.read_bytes()
            value = read_json(path)
            mutate(value)
            path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            try:
                prepare(paths, study)
            except (ValueError, KeyError, AssertionError):
                checks.append(label)
            else:
                raise AssertionError(label + "を拒否しなかった")
            finally:
                path.write_bytes(before)

        cases = (
            ("result", lambda v: v.update(試行=84), "試行差拒否"),
            ("result", lambda v: v["場別"].pop(), "528会計欠落拒否"),
            ("result", lambda v: v["比較"]["S0G1_D0"].update(費用後損益円=1), "集計純額差拒否"),
            ("result", lambda v: v["出口間の同実新規分解"]["G1_S1対S0_D0"].update(Aのみ=1), "出口参加差拒否"),
            ("cash_audit", lambda v: v.update(不一致数=1), "会計不一致拒否"),
            ("raw_audit", lambda v: v.update(成功=False), "原板未成功拒否"),
            ("raw_audit", lambda v: v["対象場"][0]["診断"]["利益床の独立規範"]["S1G2_D0"].update(構造要求不足原行=1), "構造要求不足拒否"),
            ("raw_audit", lambda v: v.update(派生元81監査SHA256="0" * 64), "監査派生元差拒否"),
            ("viewer_audit", lambda v: v.update(完了資源=527), "Viewer未完拒否"),
            ("viewer_audit", lambda v: v.update(APIエラー=[{"説明": "人工通信断"}]), "Viewer通信未完拒否"),
            ("viewer_audit", lambda v: v.update(入力不変=False), "Viewer入力変化拒否"),
            ("condition", lambda v: v.update(modes=["S0G1"]), "政策集合差拒否"),
            ("input_reference", lambda v: v.update(固定82条件SHA256="0" * 64), "固定82依存差拒否"),
        )
        for args in cases:
            reject_json(*args)
        # ----------------------------------------
        # 非0の分割・全量と、部分片の後に起こる構造到達を分けて確認します。
        empty = read_json(paths["result"])
        session = read_json(paths["manifest"])["sessions"][0]["id"]
        rows, nonzero = artificial_lots(empty, session)
        verify_diagnostics(rows, nonzero, [session])
        checks.append("非0G1部分・G2全量・構造到達前の部分片")
        mutations = (
            (lambda r, v: r[0]["lot"].update(net_pnl=15301), "非0玉純額差拒否"),
            (lambda r, v: r[0]["lot"].update(structure_active=True), "S0構造創作拒否"),
            (lambda r, v: r[1]["lot"].update(structure_floor=-29), "固定EMA床差拒否"),
            (lambda r, v: r[1]["closed"][0].update(structure_first_hit_at=14, structure_first_hit_index=14), "部分片へ未来hit転記拒否"),
            (lambda r, v: r[2]["lot"].update(harvest_target=1), "G2部分利確混入拒否"),
            (lambda r, v: v["比較"]["S1G1_D0"]["総計"].update(structure_hit_lots=0), "構造集計差拒否"),
            (lambda r, v: v["出口間の同実新規分解"]["S0_G2対G1_D0"].update(同実新規出口差円=1), "配分出口差拒否"),
        )
        for mutate, label in mutations:
            bad_rows, bad_result = deepcopy(rows), deepcopy(nonzero)
            mutate(bad_rows, bad_result)
            try:
                verify_diagnostics(bad_rows, bad_result, [session])
            except (ValueError, KeyError, AssertionError):
                checks.append(label)
            else:
                raise AssertionError(label + "を拒否しなかった")
        bad_anchor = {"known": True, "price": 10000, "at": 10, "bar_end": 11, "reason": "人工未来"}
        try:
            verify_anchor(bad_anchor, 10)
        except ValueError:
            checks.append("未来アンカー拒否")
        else:
            raise AssertionError("未来アンカーを拒否しなかった")
        bad_table = original_settings.replace("| I01 |", "| I99 |", 1)
        try:
            verify_table(bad_table, study)
        except (ValueError, KeyError):
            checks.append("版5手法ID差拒否")
        else:
            raise AssertionError("表ID差を拒否しなかった")
        generate(paths, study, True)
    return {"成功": True, "人工数": len(checks), "人工": checks, "市場原板読取": 0, "新売買再生": 0, "実API": 0}


def main() -> None:
    """
    機能: 明示正本による生成・同値確認と、市場なし人工を切り替える。
    引数: --run/--check/--self-test (bool)、--studyと10正本 (Path)。
    返り値: None。未完監査・不整合は非0終了する。
    """
    parser = argparse.ArgumentParser(description="83の小型正本から構造否定と利益配分の帳票を生成")
    stage = parser.add_mutually_exclusive_group(required=True)
    for name in ("run", "check", "self-test"):
        stage.add_argument("--" + name, action="store_true")
    parser.add_argument("--study", type=Path)
    names = ("result", "catalog", "cash-audit", "raw-audit", "viewer-audit", "condition", "input-reference", "manifest", "trades", "grids")
    for name in names:
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.self_test:
        need(args.study is None and not any(getattr(args, n.replace("-", "_")) for n in names), "人工と正式入力を混在させない")
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    need(args.study is not None and all(getattr(args, n.replace("-", "_")) is not None for n in names), "studyと10正本の明示が必要")
    paths = {n.replace("-", "_"): getattr(args, n.replace("-", "_")).resolve() for n in names}
    proof = generate(paths, args.study.resolve(), args.check)
    print(json.dumps({k: proof[k] for k in ("試行", "成功", "場数", "会計数", "Viewer資源数", "本処理の市場原板読取", "新売買再生")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
