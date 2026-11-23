"""86の11明示正本を結び、保持帯両気配と短秒反対の複合退出帳票を生成する。

停止85の有限値・版5表・会計照合から派生。市場原板・新売買は再生しない。
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ('C0',)
MODES = ('J0G1','J1G1')
KEYS = tuple(f'{mode}_D{delay}' for delay in (0,1) for mode in MODES)
BEGIN = '<!-- 86_RESULTS_BEGIN -->'
END = '<!-- 86_RESULTS_END -->'
STATUS = '**新市場損益前の事前設定。複合退出の収益効果は未検証。**'
SAVED_SHA = '13c922961ec54ab63782cf5c11d8e54f45619a74d906a415bc8128b52380b862'
# 固定85帳票派生元SHA256: aa093bed2432b138070febe059b56e9e5d4abe34e0fca09e1e54f890280685db

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
    機能: 全264会計と4集計の費用・玉・数量・期間・DDを相互確認する。
    引数: result (dict) は結果正本、sessions (list[str]) は台帳順。
    返り値: dict は場と政策をキーにした保存会計。
    """
    need(count(result["試行"]) == 86 and count(result["場数"]) == 66 and result["全場既使用"] is True, "86の66場が必要")
    need(result["金融内部モード"] == "S0G1", "全金融は固定S0G1が必要")
    need(result["保持帯床有効"] is False and result["複合確認有効"] == {"J0G1":False,"J1G1":True} and all(type(value) is bool for value in result["複合確認有効"].values()), "旧保持帯床off又は新複合確認設定差")
    need(set(result["比較"]) == set(KEYS), "4比較集合差")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}
    need(len(rows) == len(result["場別"]) == 264 and set(rows) == {(s, key) for s in sessions for key in KEYS}, "264会計の欠落又は重複")
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
        expected_counts = {name: sum(count(r['metrics']['confirm_counts'][name]) for r in chosen) for name in SAVED.COUNTS}
        need(summary['複合確認5群'] == expected_counts, '確認5群の場別合計差')
        audit = SAVED.BASE.Audit(); SAVED.validate_counts(expected_counts, audit, key)
        need(audit.bad == 0, '複合確認5群の分母差')
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
        need(number(summary["上位3場利益円"]) == sum(sorted(values, reverse=True)[:3]) and number(summary["最悪場円"]) == min(values) and number(summary["最大場円"]) == max(values), "利益集中又は最大最小場の差")
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
        policy_actions = Counter()
        for row in chosen:
            need(type(row.get("方針判断")) is dict, "方針判断の場別保存が不足")
            for action, n in row["方針判断"].items():
                policy_actions[action] += count(n)
        need(dict(policy_actions) == summary["方針判断"] and sum(policy_actions.values()) == 2442, "方針判断の全定時集計差")
    return rows


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
        need(lot["id"].startswith(session + "_S0G1_P") and order["id"].startswith(session + "_S0G1_O"), "内部金融IDを外ラベルへ変更")
        anchor = lot["structure_anchor"]
        verify_anchor(anchor, order["request_time"])
        need(order["structure_anchor"] == anchor and order["structure_active"] is False and order["structure_floor"] is None, "新規要求アンカー又は活性状態差")
        active = False
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


def verify_audits(paths: dict, values: dict, result: dict, rows: dict, diagnostics: dict, sessions: list[str]) -> dict:
    """
    機能: 会計・原板・Viewerの対象集合と保存SHAを結合する。
    引数: paths/values (dict) は明示パスと本文、result/rows/diagnostics (dict) は検査済集計、sessions (list[str]) は対象場。
    返り値: dict はKey別の独立保護規範合計。
    """
    cash, raw, viewer, catalog = [values[n] for n in ("cash_audit", "raw_audit", "viewer_audit", "catalog")]
    need(count(cash["会計数"]) == 264 and count(cash["不一致数"]) == 0, "全会計照合が未完")
    checks = {(r["session"], r["key"]): r for r in cash["照合"]}
    need(len(checks) == len(cash["照合"]) == 264 and set(checks) == set(rows), "会計照合対象差")
    for identity, check in checks.items():
        need(number(check["現金円"]) == number(rows[identity]["metrics"]["net_pnl_yen"]) and number(check["粗損益円"]) == number(rows[identity]["metrics"]["gross_pnl_yen"]) and number(check["費用円"]) == number(rows[identity]["metrics"]["total_cost_yen"]) and count(check["残量"]) == 0, "会計照合と正本差")
        count(check["約定数"])
    need(count(raw["試行"]) == 86 and raw["成功"] is True and count(raw["場数"]) == 66 and count(raw["不一致数"]) == 0 and not raw["不一致"], "原板監査が未完又は不一致")
    need(raw["入力台帳SHA256"] == sha(paths["manifest"]), "原板監査の台帳SHA差")
    raw_rows = {r["session"]: r for r in raw["対象場"]}
    need(len(raw_rows) == len(raw["対象場"]) == 66 and set(raw_rows) == set(sessions), "原板監査66場差")
    normative = {key: Counter() for key in KEYS}
    for session in sessions:
        record = raw_rows[session]
        need(record["不一致数"] == 0 and not record["不一致"] and record["再生結果SHA256"] == result["再生結果SHA256"][session + ".json"], "原板監査の再生指紋差")
        detail = record["診断"]
        need(detail["場"] == session and detail["JSON本文走査回数"] == 2 and set(detail["全玉費用後評価"]) == set(KEYS) and set(detail["利益床の独立規範"]) == set(KEYS), "原板診断の対象差")
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
            for name in ("予約不足原行", "予約不足数量", "利確要求不足原行", "構造要求不足原行", "保持帯要求不足原行", "複合要求不足原行", "複合要求不足数量"):
                need(counts[name] == 0, "独立規範の保護又は利確要求不足")
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog", "Viewer一覧形式差")
    resources = catalog["resources"]
    resource_map = {r["id"]: r for r in resources}
    expected_ids = {f"86_{key}_{session}" for session, key in rows}
    need(len(resource_map) == len(resources) == 264 and set(resource_map) == expected_ids, "Viewer264資源の差")
    need(count(viewer["試行"]) == 86 and viewer["成功"] is True and count(viewer["予定資源"]) == count(viewer["完了資源"]) == 264 and count(viewer["不一致数"]) == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "Viewer全件成功が必要")
    need(viewer["結果SHA256"] == sha(paths["result"]) and viewer["一覧SHA256"] == sha(paths["catalog"]), "Viewerの正本SHA差")
    need(viewer["入力SHA256前"] == viewer["入力SHA256後"], "Viewer読取中の入力変更")
    current_files = {str(paths["result"].resolve()), str(paths["catalog"].resolve())}
    for resource in resources:
        session, key = next((s, k) for s, k in rows if resource["id"] == f"86_{k}_{s}")
        need((resource["symbol"], resource["session"], resource["method_id"], resource["product"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", session, key.split("_D")[0], "NK225micro", 10, "trades", "net"), "Viewer資源metadata差")
        path = (paths["catalog"].parent / resource["pnl_path"]).resolve()
        need(path.is_relative_to(paths["catalog"].parent), "約定参照が成果物外です")
        current_files.add(str(path))
    need(set(viewer["入力SHA256前"]) == current_files, "Viewer入力指紋集合差")
    for name, wanted in viewer["入力SHA256前"].items():
        need(sha(Path(name)) == wanted, "Viewer照合後の正本変更")
    by_id = {r["id"]: r for r in viewer["資源"]}
    need(len(by_id) == len(viewer["資源"]) == 264 and set(by_id) == expected_ids, "Viewer資源別の完了集合差")
    for session, key in rows:
        v = by_id[f"86_{key}_{session}"]
        need(v["完了"] is True and v["不一致数"] == 0 and v["APIエラー"] is None, "Viewer個別未完了")
        need(number(v["API費用後円"]) == number(v["原純額円"]) == number(rows[session, key]["metrics"]["net_pnl_yen"]), "Viewer個別純額差")
    need(raw["監査コードSHA256"] == sha(Path(__file__).with_name("原板監査.py")) and raw["固定85監査SHA256"] == sha(ROOT/"scripts/保持帯の返済側固定否定/原板監査.py") and raw["原板本文走査回数毎場"] == 2, "原板監査コード・固定85・2走査差")
    need(raw["固定80監査SHA256"] == sha(ROOT/"scripts/FAR後期15分移植/原板照合.py") and raw["固定83監査SHA256"] == sha(ROOT/"scripts/構造否定と利益配分/原板監査.py"), "原板監査の固定80/83指紋差")
    need(viewer["監査コードSHA256"] == sha(Path(__file__).with_name("表示監査.py")), "Viewer監査コードSHA差")
    return normative


def verify_raw_confirmation(raw: dict, diagnostics: dict, rows: dict, sessions: list[str]) -> dict:
    """
    機能: 原板独立shadowと金融onの保存counter/初回証拠を結び、off0と分離する。
    引数: raw/diagnostics/rows (dict)、sessions (list[str]) は検査済正本。
    返り値: dict は4キー別の独立shadow6カウンター合計。
    """
    totals = {key:Counter() for key in KEYS}
    for scene in raw['対象場']:
        session = scene['session']; detail = scene['診断']
        need(session in sessions and type(detail['短秒キャッシュ行数']) is int and detail['短秒キャッシュ行数'] >= 0, '独立短秒キャッシュ数差')
        independent = detail['複合退出の独立規範']
        need(set(independent) == set(KEYS), '独立複合shadow4キー差')
        for key in KEYS:
            shadow = independent[key]; enabled = key.startswith('J1G1')
            need(shadow['金融有効'] is enabled and type(shadow['限定']) is str, '独立shadowの金融on/off差')
            audit = SAVED.BASE.Audit(); SAVED.validate_counts(shadow['影観測'],audit,session+key)
            need(audit.bad == 0, '独立shadow5群の分母差')
            totals[key].update(shadow['影観測'])
            saved = {row['lot']['id']:row['lot'] for identity,row in diagnostics[key].items() if identity[0] == session}
            observed = {row['実玉']:row for row in shadow['玉']}
            need(len(observed) == len(shadow['玉']) == len(saved) and set(observed) == set(saved), '独立shadowの全実玉集合差')
            local = Counter()
            for identity, event in observed.items():
                lot = saved[identity]; check = SAVED.BASE.Audit(); SAVED.validate_counts(event['counts'],check,session+key+identity)
                need(check.bad == 0, '独立玉shadow分母差'); local.update(event['counts'])
                need(lot['confirm_counts'] == (event['counts'] if enabled else SAVED.zero_counts()), '金融on玉と独立全原行shadow差')
                for field in SAVED.FIRSTS:
                    evidence = event[field]
                    if evidence is not None:
                        need(evidence == SAVED.expected_evidence(evidence,lot), '独立shadow初回式差')
                    need(lot[field] == (evidence if enabled else None), '金融on初回証拠と全原行shadow差')
            need({name:local[name] for name in SAVED.COUNTS} == shadow['影観測'], '独立shadow玉別合計差')
            metric = rows[session,key]['metrics']
            need(metric['confirm_counts'] == (shadow['影観測'] if enabled else SAVED.zero_counts()), '金融on場別確認と独立shadow差')
            expected_obligations = shadow['影観測']['confirmed'] if enabled else 0
            need(metric['confirm_exit_obligations'] == expected_obligations and metric['confirm_missing_quantity'] == 0, '複合成立義務又は不足差')
    return {key:{name:total[name] for name in SAVED.COUNTS} for key,total in totals.items()}


def verify_exports(paths: dict, catalog: dict, diagnostics: dict, sessions: list[str]) -> None:
    """
    機能: Viewer約定の外側ラベルと、内部S0G1所有・価格・数量・費用・時刻を結ぶ。
    引数: paths/catalog (dict) は明示一覧、diagnostics (dict) は内部金融の全玉、sessions (list[str]) は66場。
    返り値: None。表示ラベル以外の変更・欠落・重複を拒否する。
    """
    resources = {row['id']:row for row in catalog['resources']}
    for session in sessions:
        for key in KEYS:
            resource = resources[f'86_{key}_{session}']
            path = (paths['catalog'].parent / resource['pnl_path']).resolve()
            trades = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            events = []
            for identity,row in diagnostics[key].items():
                if identity[0] != session:
                    continue
                lot,order = row['lot'],row['entry_order']
                prefix = 'Long' if lot['side'] == 1 else 'Short'
                events.append({'position_id':lot['id'],'time':lot['entry_time'],'type':prefix+'N','price':lot['entry_price'],'qty':100,'fee_yen':6100,'source_line':lot['entry_line'],'reason':order['reason']})
                for closed in row['closed']:
                    events.append({'position_id':lot['id'],'time':closed['exit_time'],'type':prefix+'R','price':closed['exit_price'],'qty':closed['quantity'],'fee_yen':61*closed['quantity'],'source_line':closed['exit_line'],'reason':closed['reason']})
            events.sort(key=lambda event:event['source_line'])
            need(len(events) == len(trades), '表示約定数差')
            for index,(event,trade) in enumerate(zip(events,trades,strict=True),1):
                need(set(trade) == {'id','timestamp','type','position_id','price','qty','fee_yen','method_id','source_line','reason'}, '表示約定field集合差')
                need(trade['method_id'] == key.split('_D')[0] and trade['id'] == f'{session}_S0G1_T{index:06d}', '内部ID又は表示手法名差')
                need(abs(Decimal(str(datetime.fromisoformat(trade['timestamp']).timestamp())) - number(event.pop('time'))) <= Decimal('0.000001'), '表示約定時刻差')
                need(all(trade[name] == value for name,value in event.items()), '表示約定の所有・価格・数量・費用差')


def fixed_dependencies(condition: dict, reference: dict, manifest: Path) -> dict[str, str]:
    """
    機能: 86条件・固定80..85依存・実行ファイルと旧条件6pathを結ぶ。
    引数: condition/reference (dict)、manifest (Path) は固定設定と台帳。
    返り値: dict[str,str] は本文SHA一致の依存。市場原板は開かない。
    """
    for value in (condition, reference):
        need(value['試行'] == 86 and value['入力台帳SHA256'] == sha(manifest), '86条件・入力台帳差')
        need(value['入力場数'] == 66 and value['全場既使用'] is True, '66既使用場が必要')
    need(reference['入力ファイル数'] == 396 and reference['固定80採用版'] == 2, '固定入力形式差')
    path = Path(reference['入力台帳'])
    need((path if path.is_absolute() else ROOT/path).resolve() == manifest.resolve(), '台帳参照先差')
    need(condition['modes'] == list(MODES) and condition['entry_policies'] == list(POLICIES) and condition['keys'] == list(KEYS), '4会計集合又は順序差')
    need(condition['金融内部モード'] == 'S0G1' and condition['hold_enabled'] == dict.fromkeys(MODES, False) and condition['confirm_enabled'] == {'J0G1':False,'J1G1':True} and all(type(value) is bool for name in ('hold_enabled','confirm_enabled') for value in condition[name].values()), '金融・旧床off・複合on/off差')
    for name, expected in (('保持帯tick',10),('確認規則版',1),('短秒端点許容秒',15),('原板本文走査回数毎場',2)):
        need(type(condition[name]) is int and condition[name] == expected, '確認規則の固定値差:'+name)
    need(condition['確認理由'] == SAVED.EXIT_REASON and condition['短秒窓秒'] == [5,15] and all(type(value) is int for value in condition['短秒窓秒']), '複合確認理由又は5/15秒窓差')
    need(condition['約定追加価格時計遅延秒'] == [0,1] and condition['同時一建玉'] is True and condition['新損益前固定'] is True, '時計・所有・事前固定差')
    for name, expected in (('新規数量micro枚',100),('片側上限',100),('point_value',10),('片道手数料円',11),('片道滑りpt',5),('主往復費用円毎枚',122),('G1悪化余裕pt',10),('G1全玉予算目標円',1)):
        need(type(condition[name]) is int and condition[name] == expected, '固定数量・費用差:'+name)
    folders = {80:'00080_FAR後期三手法の15分移植と利益保護',81:'00081_定時の現在根拠と部分利益保護',82:'00082_チャートの現在性と補助確認',83:'00083_構造否定と利益配分',84:'00084_現在の価格応答と数量確認',85:'00085_保持帯の返済側固定否定'}
    groups = [condition['コードと依存SHA256']]
    for version in folders:
        key = f'固定{version}依存'
        need(condition[key] == reference[key+'指紋'], '固定依存集合差:'+key)
        groups.append(condition[key])
    expected_conditions = {f'study/{folder}/条件.json':sha(ROOT/'study'/folder/'条件.json') for folder in folders.values()}
    need(reference['旧条件SHA256'] == expected_conditions and len(reference['旧条件SHA256']) == 6, '旧条件6path明示指紋差')
    need(reference['固定85条件SHA256'] == expected_conditions['study/'+folders[85]+'/条件.json'], '直近85条件参照差')
    groups.append({condition['実行ファイル']:condition['実行ファイルSHA256']})
    checked = {}; market = Path(read_json(manifest)['source_root']).resolve()
    for group in groups:
        need(type(group) is dict and bool(group), '固定依存が空')
        for name, wanted in group.items():
            path = Path(name); path = (path if path.is_absolute() else ROOT/path).resolve()
            need(not path.is_relative_to(market) and sha(path) == wanted, '固定依存変更又は原板参照:'+name)
            need(str(path) not in checked or checked[str(path)] == wanted, '同依存の矛盾指紋')
            checked[str(path)] = wanted
    return checked


def load_saved() -> object:
    """
    機能: 停止86保存監査の出典・型・canonical結合部品を読取で再用する。
    引数: なし。宣言済みSHAのPythonだけを読む。
    返り値: object は保存監査モジュール。原板・Go・売買は実行しない。
    """
    path=Path(__file__).with_name('基準と保存判断の照合.py')
    need(sha(path)==SAVED_SHA,'86保存監査の停止SHA差')
    spec=importlib.util.spec_from_file_location('saved86_for_report',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


SAVED = load_saved()


def comparison_pairs() -> list[tuple[str,str,str]]:
    """
    機能: 複合確認有効J1を無効J0へ対比する方向を固定する。
    引数: なし。
    返り値: list[tuple[str,str,str]] は名称・比較元・比較先。
    """
    return [('J1対J0','J0G1','J1G1')]


def verify_grids(rows: list[dict], result: dict, diagnostics: dict, sessions: list[str]) -> tuple[dict,dict,dict]:
    """
    機能: 2442定時の固定C0・未知・役割・保持帯出典を検査し実新規へ結ぶ。
    引数: rows (list[dict]) は圧縮共有判断、result/diagnostics (dict) は集計と玉、sessions (list[str]) は66場。
    返り値: tuple[dict,dict,dict] はC0可用性・政策件数・保持帯枠数。源指標は再生成しない。
    """
    need(len(rows)==66 and {row['session'] for row in rows}==set(sessions),'共有判断66場差')
    available={'C0':{'全定時':0,'時計許可':0,'方向判定成立':0,'候補生成':0,'判定項目':{},'支持未知理由':Counter()}}
    counts=Counter();holds=Counter();supplied={}
    for row in rows:
        session=row['session'];times=SAVED.BASE.scheduled(session);seen=[]
        for grid in row['grid_decisions']:
            at=grid['at'];seen.append(at);base=grid['decision']
            need(grid['entry_policy']=='C0' and set(grid['policies'])=={'C0'} and at in times and base['at']==at,'固定C0定時差')
            need(type(grid['clock_allowed']) is bool,'時計許可はboolが必要')
            audit=SAVED.BASE.Audit();expected=SAVED.POLICY.refined(base,'C0',audit,session)
            source=SAVED.POLICY.candidate(session,grid,expected);expected['candidate_accepted']=source is not None
            need(audit.bad==0 and grid['policies']['C0']==expected and grid['candidate_accepted']==expected['candidate_accepted'],'固定C0の採否・候補差')
            anchor=SAVED.OLD.expected_hold_anchor(grid,source['side'] if source else 0)
            need(grid['hold_anchor']==anchor,'共有判断の保持帯全出典差')
            holds['既知枠' if anchor['known'] else '未知未使用枠']+=1
            verify_anchor(grid['structure_anchor'],at)
            need(grid['structure_anchor']==SAVED.BASE.expected_anchor(at,base['technical']),'EMA線を保持帯へ偽装')
            item=available['C0']
            for name,value in (('全定時',1),('時計許可',grid['clock_allowed']),('方向判定成立',expected['allowed']),('候補生成',expected['candidate_accepted'])):item[name]+=value
            for name,value in (('許可',expected['allowed']),('候補',expected['candidate_accepted']),('必須未知',expected['required_unknown']),('既知不許可',not expected['allowed'] and not expected['required_unknown']),('許可初動',expected['allowed'] and expected['role']=='転換初動')):counts['C0:'+name]+=value
            for old,current in zip(base['directions'],expected['directions'],strict=True):
                if current['allowed']:item.setdefault('方向許可の役割',Counter())[current['role']]+=1
                for check in old['checks']+current['added_checks']:
                    name=check['group']+':'+check['id'];total=item['判定項目'].setdefault(name,{'方向数':0,'既知':0,'成立':0,'未知':0})
                    need(type(check['known']) is bool and type(check['passed']) is bool and (check['known'] or not check['passed']),'保存チェックの既知性差')
                    for field,value in (('方向数',1),('既知',check['known']),('成立',check['passed']),('未知',not check['known'])):total[field]+=value
            for side in ('buy','sell'):
                for field in ('own_reason','peer_reason','ofi_reason'):
                    reason=base['evidence'][side][field]
                    if reason:item['支持未知理由'][field+':'+reason]+=1
            if source is not None:supplied[session,source['id']]=grid
        need(seen==times,'2442予定枠の順序・欠落・重複差')
    need(available==result['定時の候補と入力可用性'],'固定C0可用性集計差')
    for key,group in diagnostics.items():
        for identity,row in group.items():
            need(identity in supplied,'実新規の当時C0供給がない')
            grid=supplied[identity]
            need(row['entry_order']['request_time']==grid['at'] and row['lot']['hold_anchor']==grid['hold_anchor'],'実新規と当時保持帯出典差')
    return available,dict(counts),dict(holds)


def verify_hold_diagnostics(diagnostics: dict, rows: dict, grids: list[dict], sessions: list[str]) -> None:
    """
    機能: 圧縮玉の新confirm型・旧床off・初回snapshot・新集計を保存規範へ結ぶ。
    引数: diagnostics/rows (dict)、grids (list[dict])、sessions (list[str]) は照合済資料。
    返り値: None。全原行の見逃しは独立原板監査へ分担する。
    """
    by_session = {row['session']:{grid['at']:grid for grid in row['grid_decisions']} for row in grids}
    schema = SAVED.BASE.schemas()
    for session in sessions:
        for key in KEYS:
            group = [row for identity,row in diagnostics[key].items() if identity[0] == session]
            book = dict.fromkeys(schema['BookResult'])
            book.update(hold_enabled=False,confirm_enabled=key.startswith('J1G1'),lots=[row['lot'] for row in group],orders=[order for row in group for order in row['orders']],closed=[closed for row in group for closed in row['closed']],positions=[],pending_entries=[],metrics=rows[session,key]['metrics'])
            audit = SAVED.BASE.Audit(); projected = SAVED.validate_schema(book,audit,session+key)
            SAVED.OLD.bind_hold_metadata(projected,False,by_session[session],audit,session+key)
            SAVED.bind_confirmation(book,book['confirm_enabled'],audit,session+key)
            need(audit.bad == 0,'保存複合metadata又は集計差:'+json.dumps(audit.examples[:2],ensure_ascii=False))


def verify_entry_audit(paths: dict, values: dict, result: dict, rows: dict, stats: dict, holds: dict, grids: list[dict], trade_rows: list[dict], sessions: list[str]) -> None:
    """
    機能: 独立保存監査と11正本を本文SHA・canonical内容・132基準会計へ結ぶ。
    引数: paths/values/result/rows/stats/holds (dict)、grids/trade_rows (list[dict])、sessions (list[str]) は検査済入力。
    返り値: None。圧縮診断の別内容・未完・入力変化・方針判断差を拒否する。
    """
    entry=values['entry_audit']
    need(entry['試行']==86 and entry['成功'] is True and entry['処理完了'] is True and entry['入力不変'] is True,'保存監査が未完')
    need((count(entry['場数']),count(entry['予定枠']),count(entry['基準会計数']))==(66,2442,132) and count(entry['照合項目数'])>0 and count(entry['不一致数'])==0 and not entry['不一致'],'保存監査全対象完了が必要')
    need(entry['入力SHA256前']==entry['入力SHA256後'] and set(entry['入力SHA256前'])=={'86','85'},'保存監査の前後入力差')
    need(entry['入力SHA256前']['86']==result['再生結果SHA256'],'保存監査と86本文SHA差')
    old_result=ROOT/'study/00085_保持帯の返済側固定否定/成果物/結果.json'
    need(entry['入力SHA256前']['85']==read_json(old_result)['再生結果SHA256'],'保存監査の85基準本文SHA差')
    small_files=[paths['manifest'],old_result,SAVED.BASE_PATH,SAVED.OLD.BASE_PATH,SAVED.OLD.OLD.BASE_PATH,ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',paths['condition'],ROOT/'study/00085_保持帯の返済側固定否定/条件.json',ROOT/'study/00084_現在の価格応答と数量確認/条件.json',ROOT/'study/00083_構造否定と利益配分/条件.json']
    need(entry['固定小型入力SHA256']=={Path(os.path.relpath(path,ROOT)).as_posix():sha(path) for path in small_files},'保存監査の小型依存集合・SHA差')
    need(entry['照合コードSHA256']==SAVED_SHA and entry['読取helperSHA256']==SAVED.BASE_SHA and entry['旧比較helperSHA256']==SAVED.OLD.BASE_SHA,'保存監査の停止コードSHA差')
    need(entry['政策件数合計']==stats and entry['政策全予定枠']=={'C0':2442} and entry['保持帯枠合計']==holds,'保存監査の政策・保持帯枠集計差')
    scenes={row['場']:row for row in entry['対象場']};need(len(scenes)==len(entry['対象場'])==66 and set(scenes)==set(sessions),'保存監査の66場差')
    actions={(row['session'],row['key']):row for row in entry['方針判断']};need(len(actions)==len(entry['方針判断'])==264 and set(actions)==set(rows),'保存監査の264方針判断差')
    grid_map={row['session']:row['grid_decisions'] for row in grids};total=Counter();hold_total=Counter()
    for session in sessions:
        scene=scenes[session]
        need(scene['予定枠']==(25 if session.endswith('Day') else 49) and scene['基準会計']==2,'保存監査の場別予定数差')
        total.update(scene['政策件数']);hold_total.update(scene['保持帯枠'])
        need(scene['共有判断SHA256']==SAVED.canonical_sha(grid_map[session]),'圧縮共有判断と原保存canonical差')
        need(set(scene['玉診断SHA256'])==set(KEYS),'玉診断canonical集合差')
        local_actions={(row['session'],row['key']):row for row in scene['方針判断']}
        need(len(local_actions)==len(scene['方針判断'])==4 and set(local_actions)=={(session,key) for key in KEYS},'場別方針判断集合差')
        for key in KEYS:
            chosen=[row for row in trade_rows if row['session']==session and row['key']==key]
            need(scene['玉診断SHA256'][key]==SAVED.canonical_sha(chosen),'圧縮玉診断と原保存canonical差')
            identity=session,key;actual=actions[identity];saved=rows[identity]
            need(scene['複合確認'][key] == {name:saved['metrics'][name] for name in SAVED.METRIC_FIELDS}, '保存監査の複合集計差')
            need(actual==local_actions[identity] and actual['金融判断']==saved['判断'] and actual['方針判断']==saved['方針判断'],'金融判断又は方針判断の独立集計差')
    need(dict(total)==stats and dict(hold_total)==holds,'保存監査の場別合計差')


def prepare(paths: dict, study: Path) -> dict:
    """
    機能: 明示11正本の集合・固定依存・会計・保持帯・原板・表示を全件検査する。
    引数: paths (dict[str,Path]) は明示入力、study (Path) は保存先。
    返り値: dict は検査済み帳票入力。市場原板・新売買を読まない。
    """
    required=('result','catalog','cash_audit','raw_audit','viewer_audit','condition','input_reference','manifest','trades','grids','entry_audit')
    need(set(paths)==set(required),'11明示入力の不足又は余剰')
    hashes={str(path.resolve()):sha(path) for path in paths.values()};values={name:read_json(paths[name]) for name in required if name not in ('trades','grids')}
    sessions=[row['id'] for row in values['manifest']['sessions']];need(len(sessions)==len(set(sessions))==66,'一意の66場台帳が必要')
    dependencies=fixed_dependencies(values['condition'],values['input_reference'],paths['manifest']);result=values['result']
    need(result['入力台帳SHA256']==sha(paths['manifest']),'結果の台帳SHA差')
    rows=verify_summary(result,sessions);trade_rows=compressed_rows(paths['trades']);diagnostics=verify_diagnostics(trade_rows,result,sessions);grids=compressed_rows(paths['grids'])
    availability,stats,holds=verify_grids(grids,result,diagnostics,sessions)
    verify_hold_diagnostics(diagnostics,rows,grids,sessions)
    normative=verify_audits(paths,values,result,rows,diagnostics,sessions)
    shadow=verify_raw_confirmation(values['raw_audit'],diagnostics,rows,sessions)
    verify_entry_audit(paths,values,result,rows,stats,holds,grids,trade_rows,sessions)
    verify_exports(paths,values['catalog'],diagnostics,sessions)
    settings=(study/'設定と結果.md').read_text(encoding='utf-8');need(settings.count(BEGIN)==settings.count(END)==1 and STATUS in settings,'固定設定マーカー差');verify_table(settings,study)
    need({str(path.resolve()):sha(path) for path in paths.values()}==hashes,'帳票読取中の入力変更')
    return {'result':result,'paths':paths,'input_sha':hashes,'dependencies':dependencies,'settings':settings,'availability':availability,'stats':stats,'holds':holds,'normative':normative,'entry':values['entry_audit'],'raw':values['raw_audit'],'shadow':shadow,'exit_categories':exit_categories(diagnostics,result)}


def exit_categories(diagnostics: dict, result: dict) -> dict:
    """
    機能: 同実入口のJ0/J1を救った損失・失った勝ち・損益幅の変化へ分解する。
    引数: diagnostics/result (dict) は検査済玉と複合集計。
    返り値: dict は遅延別の件数・A/B純額・差額。未実行の戦略利益ではない。
    """
    grouped={}
    labels=('赤字→非赤字','黒字→非黒字','両赤字の損失縮小','両赤字の損失拡大','両黒字の増益','両黒字の減益','同額・その他')
    for delay in (0,1):
        left,right=[diagnostics[f'{mode}_D{delay}'] for mode in MODES]
        categories={label:{'件数':0,'A円':Decimal(0),'B円':Decimal(0),'差円':Decimal(0)} for label in labels}
        for identity in set(left)&set(right):
            a,b=left[identity]['lot'],right[identity]['lot']
            if not all(a[name]==b[name] for name in ('side','entry_time','entry_price','initial_quantity')):continue
            x,y=number(a['net_pnl']),number(b['net_pnl'])
            label='赤字→非赤字' if x<0<=y else '黒字→非黒字' if x>0>=y else '両赤字の損失縮小' if x<y<0 else '両赤字の損失拡大' if y<x<0 else '両黒字の増益' if 0<x<y else '両黒字の減益' if 0<y<x else '同額・その他'
            row=categories[label];row['件数']+=1;row['A円']+=x;row['B円']+=y;row['差円']+=y-x
        summary=result['出口間の同実新規分解'][f'J1対J0_D{delay}']
        need(sum(row['件数'] for row in categories.values())==summary['同実新規'] and sum(row['A円'] for row in categories.values())==number(summary['同実新規A損益円']) and sum(row['B円'] for row in categories.values())==number(summary['同実新規B損益円']),'同入口の救済・早切り分解差')
        grouped[f'D{delay}']=categories
    return grouped


def result_block(data: dict) -> str:
    """
    機能: 保持帯off/onと二遅延の4案を同じ費用基準で整形する。
    引数: data (dict) は照合済の11正本。
    返り値: str は設定専用マーカーへ入れる結果Markdown。
    """
    text=['正式66場、入口は固定84C0・G1共通、複合退出off/on×二遅延。全場既使用。','',
        '| ID | 費用後損益円 | 最大DD円 | 赤字場 | 完結玉 | 全玉正益後赤字 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=data['result']['比較'][key]
        text.append(f"| {key} | {amount(row['費用後損益円'])} | {amount(row['最大DD円'])} | {row['赤字場数']}/66 | {row['完結玉']} | {ratio(row['全玉旗後赤字'],row['全玉旗'])} |")
    if not sum(row['完結玉'] for row in data['result']['比較'].values()):text+=['','実新規0。0損益を複合退出の改善とはせず、市場効果は未評価。']
    text+=['','複合確認は返済要求の条件であり、その線での約定や費用後黒字を保証しない。救った損失と早切りで失った勝ちを同実入口から分ける。']
    return '\n'.join(text)


def render_readme(data: dict, study: Path) -> str:
    """
    機能: 複合退出の仮説・全会計・原板shadow・利益保護・参加差・限界を説明する。
    引数: data (dict) は11正本、study (Path) は相対リンク基準。
    返り値: str はREADME全文。心理仮説と検証結果を区別する。
    """
    result,paths=data['result'],data['paths'];main=[result['比較'][key] for key in KEYS if key.endswith('_D0')]
    outcome='実新規0で市場効果は未評価。' if not sum(row['完結玉'] for row in main) else '主費用で黒字の案はなかった。' if not any(row['費用後損益円']>0 for row in main) else '主費用で観測黒字の案があったが、既使用期間の探索で安定利益は未確認。'
    text=['# 00086：保持帯喪失と短秒反対の複合退出','','2026-11-08。'+outcome,'',
        '固定84C0の複合テクニカル入口と固定85H0のG1保護を保ち、要求時凍結帯の両気配1tick喪失に当原行5/15秒の反対進行も重なった場合だけ追加退出する。数量Q追加・数量ATR調整・85H1単線床を混ぜず、旧70%・125/250先着・待ち50%は合格判定から一旦外した。',
        '[検証計画](検証計画.md)・[全条件と版5の55×9表](設定と結果.md)・[固定85](../00085_保持帯の返済側固定否定/README.md)を参照する。元FAR三手法の売買列全値再現ではない。','',
        '## 仮説と固定条件','','| 設定 | 追加処理 | 旧保護 |','| --- | --- | --- |',
        '| J0G1 | 複合確認off。counter0/firstnull | 85H0旧本文全値同値 |',
        '| J1G1 | 凍結帯の両BBO1tick逆側 AND 既知5/15秒速度strict両反対 | J0と同じ旧保護の後に未予約残量だけ追加返済 |','',
        '入口C0は確定3/15分EMA方向、3分MACDhist現在増分・EMA8回復、0..1ATR取得位置、RSI/TR同時急変警戒、既知短秒/OFI個別反対拒否・失速支持とfresh帯維持/反対圧力解消を組み合わせる。売買は方向符号だけ反転する。',
        'Day09:15..15:15/Night17:30..翌05:30の15分枠で初回09:00/17:15を除く。NY09:30前後15分は静観し前窓返済、場末15:35/05:50返済要求。保護は定時外も連続する。100micro・片側100・同時一建玉、1枚10円/pt、片道手数料11円＋滑り5pt、往復122円を固定。内部金融/注文/玉/約定IDはS0G1で、Viewer手法名だけ外ラベルへ写す。',
        '費用後現在単価益10×方向幅−122円がstrict正になれば即最低建値床とG1部分利確を起動し、約定済みの実確定益だけを残玉予算へ入れる。正益前の非緩和ATR/125pt、確定3分技法失敗も維持。新条件が未成立/未知でも旧保護を止めず、受理した返済を取消・延期しない。','',
        '## 価格構造・短秒・市場心理','',
        '買いはBid<=Hold.Bid−10かつAsk<=Hold.Ask−10、売りはBid>=Hold.Bid+10かつAsk>=Hold.Ask+10で価格成立。等号を含み、片側の喪失だけでは未成立とする。加えて当原行の既知5/15秒Mid速度がともに方向とstrict反対なら新理由「保持帯両気配1tick・短秒反対確認」で退出する。速度0/片窓未知は成立させない。二つの短秒窓は同じ価格系列に由来し、独立した二票ではない。',
        '心理仮説は、帯の一時接触と、両気配の逆側移動に現在の反対進行も重なった局面を分けること。板から参加者の意図を断定しない。HoldAnchorの出生Bid/Askと確認時刻・番号を分けて保存する。旧Hold床は全案false/null、新条件もFloorへ加えない。',
        '短秒は当原行CurrentEvidenceだけを使い、物理行・価格時計・BBO/Last/Received・Short.Time/Midへ結ぶ。既知窓の実経過・端点遅れ・Move/Elapsedを厳密検査する。Source genuine Known=falseだけ通常未知とし、必要nil・別原行・未来・非有限・既知数式矛盾はerror。QuoteIndexとFeatureIndexは別連番。',
        '全fill→旧技法失敗/正益/ATR/G1床/旧返済/部分利確の順序を保って最後に確認する。J1は全量予約済を含む正常postfill残玉原行を観測し、成立回数と追加要求数を分ける。全fillで残玉0の原行は分母外。Closedはfill時点snapshotだけを持ち、同原行後段や未来の初回値を遡及しない。','',
        '## 損益と利益保全','',result_block(data),'',
        '| ID | 粗損益円 | 費用円 | 正益未観測円 | 正益観測円 | 残玉正益後赤字 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=result['比較'][key];text.append(f"| {key} | {amount(row['総計']['gross_pnl_yen'])} | {amount(row['総計']['total_cost_yen'])} | {amount(row['正益未観測の損益円'])} | {amount(row['正益観測の損益円'])} | {ratio(row['残玉旗後赤字'],row['残玉旗'])} |")
    text+=['','全玉旗は実確定部分を含む取引全体の費用後額、残玉旗は現在単価純益。全玉正益後赤字率は旗の分母とともに示す。早期退出で分母が減る効果を利益保護達成へ読み替えない。','',
        '| ID | Day円 | Night円 | 赤字日/日数 | 同約定滑り0pt円 | 同約定滑り10pt円 | 上位3場利益円 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=result['比較'][key];day=sum(number(scene['metrics']['net_pnl_yen']) for scene in result['場別'] if scene['key']==key and scene['session'].endswith('Day'))
        text.append(f"| {key} | {amount(day)} | {amount(number(row['費用後損益円'])-day)} | {row['赤字日数']}/{row['日数']} | {amount(row['同約定0pt損益円'])} | {amount(row['同約定10pt損益円'])} | {amount(row['上位3場利益円'])} |")
    text+=['','同約定0/10ptは費用だけの感応。D0は次正常原行、D1は追加価格時計1秒を満たす次適格原行で、実通信の1秒後を保証しない。要求条件の線で約定した架空利益や費用後黒字保証を作らない。','',
        '## 同実入口の出口差と参加差','','A=J0、B=J1のB−A。同じ候補でも取得が変わる群と、片側だけの後続参加を分ける。','',
        '| 比較 | 同実入口 | A円 | B円 | 出口差円 | 取得変更 | Aのみ件/円 | Bのみ件/円 |','| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    for name,row in result['出口間の同実新規分解'].items():
        text.append(f"| {name} | {row['同実新規']} | {amount(row['同実新規A損益円'])} | {amount(row['同実新規B損益円'])} | {amount(row['同実新規出口差円'])} | {row['共通だが取得変更']} | {row['Aのみ']} / {amount(row['Aのみ損益円'])} | {row['Bのみ']} / {amount(row['Bのみ損益円'])} |")
    text+=['','| 遅延 | 同実入口の内訳 | 件数 | A円 | B円 | 差円 |','| --- | --- | ---: | ---: | ---: | ---: |']
    for delay,categories in data['exit_categories'].items():
        for label,row in categories.items():text.append(f"| {delay} | {label} | {row['件数']} | {amount(row['A円'])} | {amount(row['B円'])} | {amount(row['差円'])} |")
    text+=['','検証済み同実入口の損失救済・失った勝ち・損失拡大を全玉で示す診断であり、保存額を組み替えた未実行戦略の成績ではない。','',
        '## 複合確認の観測分母','','| ID | 金融観測 | 価格未成立/短秒既知 | 価格未成立/短秒未知 | 価格成立/短秒未知 | 価格成立/非反対 | 成立原行 | 成立玉 | 追加要求 | 不足量 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=result['比較'][key];c=row['複合確認5群'];m=row['総計']
        text.append('| '+key+' | '+' | '.join(str(c[name]) for name in SAVED.COUNTS)+' | '+str(m['confirm_confirmed_lots'])+' | '+str(m['confirm_exit_orders'])+' | '+str(m['confirm_missing_quantity'])+' |')
    text+=['','後5群が金融観測分母をちょうど分解する。first_unknownは価格成立かつ短秒未知の初回だけ。J0の0/nullは処理offであり、データ不足や短秒未知ではない。','',
        '| ID | 原板独立shadow分母 | 価格未成立/既知 | 価格未成立/未知 | 価格成立/未知 | 価格成立/非反対 | 成立 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        text.append('| '+key+' | '+' | '.join(str(data['shadow'][key][name]) for name in SAVED.COUNTS)+' |')
    text+=['','このshadowは両案の実所有に対する別の独立観測で、J0の金融counter0へ足さない。J1は保存Knownや初回snapshotだけを信じず、全正常残玉原行の独立短秒再構成と比較して見逃しも検査した。','',
        '| ID | 正常保有原行 | G1部分要求/約定枚 | 予算床玉 | 保護予約不足 | 複合要求不足 |','| --- | ---: | --- | ---: | ---: | ---: |']
    for key in KEYS:
        row=data['normative'][key];m=result['比較'][key]['総計']
        text.append(f"| {key} | {row['正常保有原行']} | {m['harvest_quantity']}/{m['harvest_filled_quantity']} | {m['cash_floor_activated_lots']} | {row['予約不足原行']} | {row['複合要求不足原行']} |")
    a=data['availability']['C0'];s=data['stats'];text+=['','## 候補と判断','',
        '| 入口 | 全予定枠 | 時計許可 | 許可 | 候補 | 必須未知 | 既知不許可 | 許可初動 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
        f"| C0 | {a['全定時']} | {a['時計許可']} | {a['方向判定成立']} | {a['候補生成']} | {s['C0:必須未知']} | {s['C0:既知不許可']} | {s['C0:許可初動']} |",'',
        '金融の保存判断を変更せず、時計許可中で非占有の金融「待ち」かつC0必須未知だけ別の方針判断を「判定不能」へ分類する。保有・処理中・新規を優先する。','',
        '| ID | 分類 | 新規要求 | 保有継続 | 処理中 | 待ち | 判定不能 |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        for field,label in (('判断','金融'),('方針判断','方針')):
            text.append('| '+key+' | '+label+' | '+' | '.join(str(result['比較'][key][field].get(name,0)) for name in ('新規要求','保有継続','処理中','待ち','判定不能'))+' |')
    text+=['','## 日別損益','','| 日付 | '+' | '.join(KEYS)+' |','| --- | '+' | '.join('---:' for _ in KEYS)+' |']
    for day in sorted({day for row in result['比較'].values() for day in row['日別円']}):
        text.append('| '+day+' | '+' | '.join(amount(result['比較'][key]['日別円'][day]) for key in KEYS)+' |')
    references=(('result','結果正本'),('catalog','Viewer264資源'),('cash_audit','保存会計'),('raw_audit','独立原板規範'),('viewer_audit','Viewer数値'),('condition','固定条件'),('input_reference','入力参照'),('manifest','固定66場台帳'),('trades','圧縮玉診断'),('grids','圧縮定時判断'),('entry_audit','旧基準・保存証拠・方針判断'))
    text+=['','## 独立照合・限界・再現','',
        f"保存会計264件、原板66場、Viewer264資源を全件結合。保存監査は{data['entry']['照合項目数']:,}項目・2442枠・132旧基準会計で差0。共有判断と全玉診断のcanonical SHAを原保存へ直接結ぶ。",'',
        ' · '.join(link(study,paths[name],label) for name,label in references),'',
        '原板は短秒履歴準備と旧規範＋複合退出の2走査で、前後SHAを検査する。巨大な原行短秒系列は正式保存しない。候補出典を実原行へ結合し、新退出のpostfill短秒だけ全残玉原行で独立再構成する。共有入口Shortは85全文同値の範囲で、未知全枠・元FAR帯出生・EMA/ATR生成器の独立再実装とはしない。',
        '全66場は既使用。二遅延/4会計/接続人工を独立標本へ水増ししない。少数黒字・無取引・日付集中は安定利益の証明ではない。ラージBBOによるmicro代理約定で、板深さ消費・約定順位・実通信・証拠金は未実証。',
        '[再現補足](再現補足.md)に停止証拠・ネイティブ実行・原板2走査・人工の範囲をまとめる。コードは[scripts/保持帯喪失と短秒反対の複合退出](../../scripts/保持帯喪失と短秒反対の複合退出/)へ分離。帳票自体の市場原板読取・新売買再生・API利用は0。','']
    command=['& "work/venvs/technical-tree/Scripts/python.exe" -B -X utf8 "scripts/保持帯喪失と短秒反対の複合退出/レポート.py" --check `','  --study "'+Path(os.path.relpath(study,ROOT)).as_posix()+'" `']
    for index,(name,_) in enumerate(references):
        command.append('  --'+name.replace('_','-')+' "'+Path(os.path.relpath(paths[name],ROOT)).as_posix()+'"'+(' `' if index<len(references)-1 else ''))
    text+=['11入力を明示して同値確認する。正式生成は--checkを--runへ置換する。','','```powershell',*command,'```','','[帳票生成証拠](レポート生成証拠.json)へ入力・依存・コード・出力のSHAを残す。','']
    return '\n'.join(text)


def generate(paths: dict, study: Path, check: bool) -> dict:
    """
    機能: 全11正本の照合後にREADMEと設定専用マーカーだけを生成又は同値確認する。
    引数: paths (dict) は明示入力、study (Path) は出力先、check (bool) は保存値の確認か。
    返り値: dict は生成証拠。入力・設定マーカー外は変更しない。
    """
    data=prepare(paths,study)
    left,rest=data['settings'].split(BEGIN)
    _,right=rest.split(END)
    settings=left+BEGIN+'\n'+result_block(data)+'\n'+END+right
    readme=render_readme(data,study)
    proof={'試行':86,'成功':True,'場数':66,'会計数':264,'Viewer資源数':264,
        '入力パス':{name:str(path.resolve()) for name,path in paths.items()},'入力SHA256':data['input_sha'],'固定依存SHA256':data['dependencies'],'生成コードSHA256':sha(Path(__file__)),
        '設定マーカー外SHA256':hashlib.sha256((left+BEGIN+END+right).encode('utf-8')).hexdigest(),
        '出力SHA256':{'README.md':hashlib.sha256(readme.encode('utf-8')).hexdigest(),'設定と結果.md':hashlib.sha256(settings.encode('utf-8')).hexdigest()},'本処理の市場原板読取':0,'新売買再生':0}
    if check:
        need((study/'README.md').read_text(encoding='utf-8')==readme and (study/'設定と結果.md').read_text(encoding='utf-8')==settings,'保存帳票と生成値の差')
        need(read_json(study/'レポート生成証拠.json')==proof,'生成証拠の差')
    else:
        (study/'README.md').write_text(readme,encoding='utf-8',newline='\n')
        (study/'設定と結果.md').write_text(settings,encoding='utf-8',newline='\n')
        (study/'レポート生成証拠.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return proof


def fake_inputs(base: Path) -> tuple[Path,dict]:
    """
    機能: 停止84の人工生成部品を一時モジュールで再用し、86の11正本へ変換する。
    引数: base (Path) はwork配下の新規人工領域。
    返り値: tuple[Path,dict] は人工試行と11入力。旧ファイル・市場原板・Goは変更しない。
    """
    old_path=ROOT/'scripts/現在の価格応答と数量確認/レポート.py'
    need(sha(old_path)=='e75f2dfa012ad675a53ed258fc4438ddc75c0cffc9207925ef90893f40f28561','人工用の停止84帳票SHA差')
    spec=importlib.util.spec_from_file_location('fixed84_artificial_for86',old_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.POLICIES=POLICIES;module.MODES=MODES;module.KEYS=KEYS;module.comparison_pairs=comparison_pairs
    study,paths=module.fake_inputs(base)
    def save(name: str, value: dict) -> None:
        """
        機能: 人工辞書だけを86形へ保存する。
        引数: name (str) は明示入力名、value (dict) は有限本文。
        返り値: None。
        """
        paths[name].write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    condition,reference=read_json(paths['condition']),read_json(paths['input_reference'])
    for value in (condition,reference):value['試行']=86
    condition.update(金融内部モード='S0G1',hold_enabled=dict.fromkeys(MODES,False),confirm_enabled={'J0G1':False,'J1G1':True},保持帯tick=10,確認規則版=1,確認理由=SAVED.EXIT_REASON,短秒窓秒=[5,15],短秒端点許容秒=15,原板本文走査回数毎場=2)
    old_reference_path=ROOT/'study/00084_現在の価格応答と数量確認/入力参照.json'
    condition['固定84依存']={**condition['固定83依存'],old_reference_path.relative_to(ROOT).as_posix():sha(old_reference_path)}
    reference['固定84依存指紋']=deepcopy(condition['固定84依存']);reference['固定84条件SHA256']=sha(ROOT/'study/00084_現在の価格応答と数量確認/条件.json')
    fixed85_reference=ROOT/'study/00085_保持帯の返済側固定否定/入力参照.json'
    condition['固定85依存']={fixed85_reference.relative_to(ROOT).as_posix():sha(fixed85_reference)}
    reference['固定85依存指紋']=deepcopy(condition['固定85依存']);reference['固定85条件SHA256']=sha(ROOT/'study/00085_保持帯の返済側固定否定/条件.json')
    reference['旧条件SHA256']={f'study/{folder}/条件.json':sha(ROOT/'study'/folder/'条件.json') for folder in ('00080_FAR後期三手法の15分移植と利益保護','00081_定時の現在根拠と部分利益保護','00082_チャートの現在性と補助確認','00083_構造否定と利益配分','00084_現在の価格応答と数量確認','00085_保持帯の返済側固定否定')}
    for version in (80,81,82,83,84):reference.pop(f'固定{version}条件SHA256',None)
    save('condition',condition);save('input_reference',reference)
    result=read_json(paths['result']);result.update(試行=86,保持帯床有効=False,複合確認有効={'J0G1':False,'J1G1':True});result['出口間の同実新規分解']=result.pop('入口間の同実新規分解')
    metric_fields=SAVED.BASE.schemas()['BookMetrics']|SAVED.BASE.EXTRA['BookMetrics']|SAVED.OLD.HOLD_METRICS|(SAVED.METRIC_FIELDS-{'confirm_counts'})
    for row in result['場別']:row['metrics']={**dict.fromkeys(metric_fields,0),'confirm_counts':SAVED.zero_counts()}
    for row in result['比較'].values():row.update(総計=dict.fromkeys(metric_fields,0),複合確認5群=SAVED.zero_counts())
    save('result',result)
    grid_rows=compressed_rows(paths['grids'])
    for row in grid_rows:
        for grid in row['grid_decisions']:
            grid['entry_policy']='C0';grid['hold_anchor']=SAVED.OLD.unknown_hold()
            grid['structure_anchor']=SAVED.BASE.expected_anchor(grid['at'],grid['decision']['technical'])
    with gzip.open(paths['grids'],'wt',encoding='utf-8') as stream:
        for row in grid_rows:stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    catalog=read_json(paths['catalog'])
    for row in catalog['resources']:row['id']=row['id'].replace('84_','86_',1)
    save('catalog',catalog)
    cash=read_json(paths['cash_audit']);cash['会計数']=264;save('cash_audit',cash)
    raw=read_json(paths['raw_audit']);raw['試行']=86;raw['監査コードSHA256']=sha(Path(__file__).with_name('原板監査.py'));raw['固定85監査SHA256']=sha(ROOT/'scripts/保持帯の返済側固定否定/原板監査.py');raw['原板本文走査回数毎場']=2
    for scene in raw['対象場']:
        scene['診断'].update(JSON本文走査回数=2,短秒キャッシュ行数=0,複合退出の独立規範={key:{'金融有効':key.startswith('J1G1'),'影観測':SAVED.zero_counts(),'玉':[],'限定':'人工0玉の独立shadow'} for key in KEYS})
        for norms in scene['診断']['利益床の独立規範'].values():norms.update(dict.fromkeys(('保持帯活性原行','保持帯到達原行','保持帯要求不足原行','複合成立原行','複合要求不足原行','複合要求不足数量'),0))
    save('raw_audit',raw)
    viewer=read_json(paths['viewer_audit']);viewer.update(試行=86,完了資源=264,予定資源=264,監査コードSHA256=sha(Path(__file__).with_name('表示監査.py')),結果SHA256=sha(paths['result']),一覧SHA256=sha(paths['catalog']))
    for row in viewer['資源']:row['id']=row['id'].replace('84_','86_',1)
    files=[paths['result'],paths['catalog']]+[paths['catalog'].parent/row['pnl_path'] for row in catalog['resources']]
    hashes={str(path):sha(path) for path in files};viewer.update(入力SHA256前=hashes,入力SHA256後=hashes);save('viewer_audit',viewer)
    entry=read_json(paths['entry_audit']);entry.update(試行=86,照合コードSHA256=SAVED_SHA,読取helperSHA256=SAVED.BASE_SHA,旧比較helperSHA256=SAVED.OLD.BASE_SHA,保持帯枠合計={'未知未使用枠':2442})
    old_result=ROOT/'study/00085_保持帯の返済側固定否定/成果物/結果.json';inventory={'86':result['再生結果SHA256'],'85':read_json(old_result)['再生結果SHA256']};entry.update(入力SHA256前=inventory,入力SHA256後=inventory)
    small=[paths['manifest'],old_result,SAVED.BASE_PATH,SAVED.OLD.BASE_PATH,SAVED.OLD.OLD.BASE_PATH,ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',paths['condition'],ROOT/'study/00085_保持帯の返済側固定否定/条件.json',ROOT/'study/00084_現在の価格応答と数量確認/条件.json',ROOT/'study/00083_構造否定と利益配分/条件.json']
    entry['固定小型入力SHA256']={Path(os.path.relpath(path,ROOT)).as_posix():sha(path) for path in small}
    grids={row['session']:row['grid_decisions'] for row in grid_rows}
    for scene in entry['対象場']:
        scene['複合確認']={key:{name:SAVED.zero_counts() if name=='confirm_counts' else 0 for name in SAVED.METRIC_FIELDS} for key in KEYS}
        scene.update(保持帯枠={'未知未使用枠':scene['予定枠']},共有判断SHA256=SAVED.canonical_sha(grids[scene['場']]),玉診断SHA256={key:SAVED.canonical_sha([]) for key in KEYS})
    save('entry_audit',entry)
    original=ROOT/'study/00086_保持帯喪失と短秒反対の複合退出/設定と結果.md';settings=original.read_text(encoding='utf-8')
    for method in read_json(ROOT/'scripts/レポート/手法カタログ_版5.json')['methods']:
        actual=ROOT/method['source'];settings=settings.replace(']('+Path(os.path.relpath(actual,original.parent)).as_posix()+')',']('+Path(os.path.relpath(actual,study)).as_posix()+')')
    (study/'設定と結果.md').write_text(settings,encoding='utf-8')
    return study,paths


def self_test() -> dict:
    """
    機能: 264会計・2442枠の11入力人工と保持帯/canonical/表示の破損検出を確認する。
    引数: なし。一時workで人工を作り、正式新市場保存・原板・Go・APIを使わない。
    返り値: dict は人工の成功項目と件数。
    """
    checks=[]
    with tempfile.TemporaryDirectory(prefix='86帳票人工_',dir=ROOT/'work') as directory:
        study,paths=fake_inputs(Path(directory).resolve());before=(study/'設定と結果.md').read_text(encoding='utf-8')
        generate(paths,study,False);generate(paths,study,True)
        need('実新規0' in (study/'README.md').read_text(encoding='utf-8'),'0取引は未評価が必要')
        need(before.split(BEGIN)[0]==(study/'設定と結果.md').read_text(encoding='utf-8').split(BEGIN)[0],'事前設定冒頭の不変')
        checks+=['人工264会計2442枠の生成同値','0取引を未評価表示','設定マーカー外不変']
        def reject(name: str, mutate: object, label: str) -> None:
            """
            機能: 一つの人工JSONを改変し、帳票の全結合検査による拒否を確認する。
            引数: name/label (str) は明示入力名と名称、mutate (callable) は本文変更。
            返り値: None。各人工の後で元byte列へ戻す。
            """
            path=paths[name];saved=path.read_bytes();value=read_json(path);mutate(value);path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            try:prepare(paths,study)
            except (ValueError,KeyError,AssertionError):checks.append(label)
            else:raise AssertionError(label+'を拒否しなかった')
            finally:path.write_bytes(saved)
        cases=(('result',lambda v:v.update(試行=87),'試行差拒否'),('result',lambda v:v['場別'].pop(),'264会計欠落拒否'),
            ('result',lambda v:v.update(複合確認有効={'J0G1':True,'J1G1':True}),'保持帯設定差拒否'),
            ('result',lambda v:v.update(金融内部モード='J1G1'),'金融内部と表示ラベル混同拒否'),
            ('result',lambda v:v['比較']['J0G1_D0'].update(費用後損益円=1),'純額差拒否'),
            ('result',lambda v:v['出口間の同実新規分解']['J1対J0_D0'].update(Aのみ=1),'出口参加差拒否'),
            ('result',lambda v:v['比較']['J1G1_D0'].update(方針判断={'待ち':2442}),'方針判断差拒否'),
            ('cash_audit',lambda v:v.update(不一致数=1),'保存会計差拒否'),('raw_audit',lambda v:v.update(成功=False),'原板未完拒否'),
            ('raw_audit',lambda v:v.update(原板本文走査回数毎場=1),'原板2走査差拒否'),
            ('raw_audit',lambda v:v['対象場'][0]['診断']['複合退出の独立規範']['J0G1_D0'].update(金融有効=True),'J0影観測と金融設定混同拒否'),
            ('raw_audit',lambda v:v['対象場'][0]['診断']['複合退出の独立規範']['J1G1_D0']['影観測'].update(normal_quotes=1),'独立影観測分母差拒否'),
            ('raw_audit',lambda v:v['対象場'][0]['診断']['利益床の独立規範']['J1G1_D0'].update(保持帯要求不足原行=1),'保持帯保護不足拒否'),
            ('raw_audit',lambda v:v.update(固定85監査SHA256='0'*64),'原板固定85差拒否'),
            ('viewer_audit',lambda v:v.update(完了資源=263),'Viewer未完拒否'),('viewer_audit',lambda v:v.update(APIエラー=[{}]),'Viewer通信未完拒否'),
            ('viewer_audit',lambda v:v.update(入力不変=False),'Viewer入力変化拒否'),('condition',lambda v:v.update(entry_policies=['A0']),'入口C0差拒否'),
            ('input_reference',lambda v:v.update(固定85条件SHA256='0'*64),'固定85条件差拒否'),
            ('input_reference',lambda v:v['旧条件SHA256'].__setitem__('study/00083_構造否定と利益配分/条件.json','0'*64),'旧条件6path差拒否'),
            ('condition',lambda v:v.update(confirm_enabled={'J0G1':True,'J1G1':True}),'複合確認変更拒否'),
            ('condition',lambda v:v.update(保持帯tick=20),'保持帯刻み差拒否'),
            ('condition',lambda v:v.update(確認規則版=2),'確認規則版差拒否'),
            ('condition',lambda v:v.update(確認理由='別理由'),'確認理由差拒否'),
            ('condition',lambda v:v.update(短秒窓秒=[5,30]),'短秒窓変更拒否'),
            ('condition',lambda v:v.update(短秒端点許容秒=16),'短秒端点遅れ変更拒否'),
            ('condition',lambda v:v.update(原板本文走査回数毎場=1),'条件2走査差拒否'),
            ('condition',lambda v:v.update(hold_enabled={'J0G1':True,'J1G1':True}),'条件の保持帯有効差拒否'),
            ('entry_audit',lambda v:v.update(処理完了=False),'保存監査未完拒否'),('entry_audit',lambda v:v.update(基準会計数=131),'132基準会計欠落拒否'),
            ('entry_audit',lambda v:v['入力SHA256前']['86'].update({'2026-01-01_Day.json':'0'*64}),'保存監査の別原保存拒否'),
            ('entry_audit',lambda v:v['政策件数合計'].update({'C0:必須未知':2441}),'政策未知数差拒否'),
            ('entry_audit',lambda v:v['保持帯枠合計'].update(既知枠=1),'保持帯枠差拒否'),
            ('entry_audit',lambda v:v['対象場'][0].update(共有判断SHA256='0'*64),'共有判断canonical差拒否'),
            ('entry_audit',lambda v:v['対象場'][0]['玉診断SHA256'].update(J1G1_D0='0'*64),'玉診断canonical差拒否'),
            ('entry_audit',lambda v:v['方針判断'].pop(),'264方針判断欠落拒否'),
            ('entry_audit',lambda v:v.update(照合コードSHA256='0'*64),'保存照合コード差拒否'))
        for case in cases:reject(*case)
        saved=paths['grids'].read_bytes();rows=compressed_rows(paths['grids']);rows[0]['grid_decisions'][0]['decision']['quote']['未使用の改変']=1
        with gzip.open(paths['grids'],'wt',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        try:prepare(paths,study)
        except ValueError as error:
            need('canonical' in str(error),'未使用値の改変は原保存canonicalで拒否');checks.append('意味集計が同じ圧縮snapshot改変を拒否')
        else:raise AssertionError('圧縮snapshotの未使用値改変を拒否しなかった')
        paths['grids'].write_bytes(saved)
        try:verify_table(before.replace('| I01 |','| I99 |',1),study)
        except (ValueError,KeyError):checks.append('版5手法ID差拒否')
        else:raise AssertionError('版5手法差を拒否しなかった')
        generate(paths,study,True)
    return {'成功':True,'人工数':len(checks),'人工':checks,'市場原板読取':0,'新売買再生':0,'実API':0}


def main() -> None:
    """
    機能: 11明示正本の正式生成・同値確認と、市場なし人工を切り替える。
    引数: --run/--check/--self-test (bool)、--studyと11入力 (Path)。
    返り値: None。未完・不整合は非0終了する。
    """
    parser=argparse.ArgumentParser(description='86の保持帯喪失と短秒反対の複合退出を11正本から帳票化')
    stage=parser.add_mutually_exclusive_group(required=True)
    for name in ('run','check','self-test'):stage.add_argument('--'+name,action='store_true')
    parser.add_argument('--study',type=Path);names=('result','catalog','cash-audit','raw-audit','viewer-audit','condition','input-reference','manifest','trades','grids','entry-audit')
    for name in names:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.self_test:
        need(args.study is None and not any(getattr(args,name.replace('-','_')) for name in names),'人工と正式入力を混在させない')
        print(json.dumps(self_test(),ensure_ascii=False));return
    need(args.study is not None and all(getattr(args,name.replace('-','_')) is not None for name in names),'studyと11正本を全て明示する')
    paths={name.replace('-','_'):getattr(args,name.replace('-','_')).resolve() for name in names};proof=generate(paths,args.study.resolve(),args.check)
    print(json.dumps({name:proof[name] for name in ('試行','成功','場数','会計数','Viewer資源数','本処理の市場原板読取','新売買再生')},ensure_ascii=False))


if __name__=='__main__':main()
