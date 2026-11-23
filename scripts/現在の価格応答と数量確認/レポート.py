"""84の11明示正本を結び、現在価格応答・数量確認の複合帳票を生成する。

固定83の有限値・版5表・会計照合から派生。市場原板・新売買は読まない。
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
POLICIES = ('A0', 'C0', 'C1')
MODES = tuple(p + 'G1' for p in POLICIES)
KEYS = tuple(f'{mode}_D{delay}' for delay in (0, 1) for mode in MODES)
BEGIN = '<!-- 84_RESULTS_BEGIN -->'
END = '<!-- 84_RESULTS_END -->'
STATUS = '**新市場損益前の事前設定。追加条件の収益効果は未検証。**'
# 固定83帳票派生元SHA256: 9f162c9071414ccf0ca21477a49115183ace3586b503273d330c2e2096fbd128

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
    機能: 全396会計と6集計の費用・玉・数量・期間・DDを相互確認する。
    引数: result (dict) は結果正本、sessions (list[str]) は台帳順。
    返り値: dict は場と政策をキーにした保存会計。
    """
    need(count(result["試行"]) == 84 and count(result["場数"]) == 66 and result["全場既使用"] is True, "84の66場が必要")
    need(result["金融内部モード"] == "S0G1", "全金融は固定S0G1が必要")
    need(set(result["比較"]) == set(KEYS), "6比較集合差")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}
    need(len(rows) == len(result["場別"]) == 396 and set(rows) == {(s, key) for s in sessions for key in KEYS}, "396会計の欠落又は重複")
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
    機能: 実玉・部分確定・構造metadataと入口間の参加分解を結合する。
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
    decomposed = result["入口間の同実新規分解"]
    expected_names = {f"{name}_D{delay}" for delay in (0, 1) for name, _, _ in comparison_pairs()}
    need(set(decomposed) == expected_names, "入口比較の対象集合差")
    for delay in (0, 1):
        for name, a, b in comparison_pairs():
            keys = [f"{m}_D{delay}" for m in (a, b)]
            left, right = [grouped[k] for k in keys]
            common = set(left) & set(right)
            exact = {i for i in common if all(left[i]["lot"][n] == right[i]["lot"][n] for n in ("side", "entry_price", "entry_time", "initial_quantity"))}
            only_a, only_b, changed = set(left) - set(right), set(right) - set(left), common - exact
            d = decomposed[f"{name}_D{delay}"]
            need(d["比較"] == keys and d["同実新規"] == len(exact) and d["共通だが取得変更"] == len(changed) and d["Aのみ"] == len(only_a) and d["Bのみ"] == len(only_b), "入口間の参加数差")
            for field, subset, group in (("同実新規A損益円", exact, left), ("同実新規B損益円", exact, right), ("取得変更A損益円", changed, left), ("取得変更B損益円", changed, right), ("Aのみ損益円", only_a, left), ("Bのみ損益円", only_b, right)):
                need(number(d[field]) == sum(number(group[i]["lot"]["net_pnl"]) for i in subset), "入口分解額差:" + field)
            need(number(d["同実新規出口差円"]) == number(d["同実新規B損益円"]) - number(d["同実新規A損益円"]), "出口差の方向差")
    return grouped


def verify_audits(paths: dict, values: dict, result: dict, rows: dict, diagnostics: dict, sessions: list[str]) -> dict:
    """
    機能: 会計・原板・Viewerの対象集合と保存SHAを結合する。
    引数: paths/values (dict) は明示パスと本文、result/rows/diagnostics (dict) は検査済集計、sessions (list[str]) は対象場。
    返り値: dict はKey別の独立保護規範合計。
    """
    cash, raw, viewer, catalog = [values[n] for n in ("cash_audit", "raw_audit", "viewer_audit", "catalog")]
    need(count(cash["会計数"]) == 396 and count(cash["不一致数"]) == 0, "全会計照合が未完")
    checks = {(r["session"], r["key"]): r for r in cash["照合"]}
    need(len(checks) == len(cash["照合"]) == 396 and set(checks) == set(rows), "会計照合対象差")
    for identity, check in checks.items():
        need(number(check["現金円"]) == number(rows[identity]["metrics"]["net_pnl_yen"]) and number(check["粗損益円"]) == number(rows[identity]["metrics"]["gross_pnl_yen"]) and number(check["費用円"]) == number(rows[identity]["metrics"]["total_cost_yen"]) and count(check["残量"]) == 0, "会計照合と正本差")
        count(check["約定数"])
    need(count(raw["試行"]) == 84 and raw["成功"] is True and count(raw["場数"]) == 66 and count(raw["不一致数"]) == 0 and not raw["不一致"], "原板監査が未完又は不一致")
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
    expected_ids = {f"84_{key}_{session}" for session, key in rows}
    need(len(resource_map) == len(resources) == 396 and set(resource_map) == expected_ids, "Viewer396資源の差")
    need(count(viewer["試行"]) == 84 and viewer["成功"] is True and count(viewer["予定資源"]) == count(viewer["完了資源"]) == 396 and count(viewer["不一致数"]) == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "Viewer全件成功が必要")
    need(viewer["結果SHA256"] == sha(paths["result"]) and viewer["一覧SHA256"] == sha(paths["catalog"]), "Viewerの正本SHA差")
    need(viewer["入力SHA256前"] == viewer["入力SHA256後"], "Viewer読取中の入力変更")
    current_files = {str(paths["result"].resolve()), str(paths["catalog"].resolve())}
    for resource in resources:
        session, key = next((s, k) for s, k in rows if resource["id"] == f"84_{k}_{s}")
        need((resource["symbol"], resource["session"], resource["method_id"], resource["product"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", session, key.split("_D")[0], "NK225micro", 10, "trades", "net"), "Viewer資源metadata差")
        path = (paths["catalog"].parent / resource["pnl_path"]).resolve()
        need(path.is_relative_to(paths["catalog"].parent), "約定参照が成果物外です")
        current_files.add(str(path))
    need(set(viewer["入力SHA256前"]) == current_files, "Viewer入力指紋集合差")
    for name, wanted in viewer["入力SHA256前"].items():
        need(sha(Path(name)) == wanted, "Viewer照合後の正本変更")
    by_id = {r["id"]: r for r in viewer["資源"]}
    need(len(by_id) == len(viewer["資源"]) == 396 and set(by_id) == expected_ids, "Viewer資源別の完了集合差")
    for session, key in rows:
        v = by_id[f"84_{key}_{session}"]
        need(v["完了"] is True and v["不一致数"] == 0 and v["APIエラー"] is None, "Viewer個別未完了")
        need(number(v["API費用後円"]) == number(v["原純額円"]) == number(rows[session, key]["metrics"]["net_pnl_yen"]), "Viewer個別純額差")
    need(raw["監査コードSHA256"] == sha(Path(__file__).with_name("原板監査.py")) and raw["固定80監査SHA256"] == sha(ROOT / "scripts/FAR後期15分移植/原板照合.py"), "原板監査コードSHA差")
    need(raw["固定83監査SHA256"] == sha(ROOT / "scripts/構造否定と利益配分/原板監査.py"), "原板監査の固定83SHA差")
    need(viewer["監査コードSHA256"] == sha(Path(__file__).with_name("表示監査.py")), "Viewer監査コードSHA差")
    return normative


def fixed_dependencies(condition: dict, reference: dict, manifest: Path) -> dict[str, str]:
    """
    機能: 84の条件と固定80..83依存・実行ファイルを明示台帳へ結ぶ。
    引数: condition/reference (dict) は保存条件、manifest (Path) は固定80台帳。
    返り値: dict[str,str] は本文SHAが一致した依存。市場原板へは立ち入らない。
    """
    for value in (condition, reference):
        need(value['試行'] == 84 and value['入力台帳SHA256'] == sha(manifest), '84条件・入力台帳差')
        need(value['入力場数'] == 66 and value['全場既使用'] is True, '66既使用場が必要')
    need(reference['入力ファイル数'] == 396 and reference['固定80採用版'] == 2, '固定入力形式差')
    path = Path(reference['入力台帳'])
    need((path if path.is_absolute() else ROOT / path).resolve() == manifest.resolve(), '台帳参照先差')
    need(condition['modes'] == list(MODES) and condition['entry_policies'] == list(POLICIES) and condition['keys'] == list(KEYS), '6政策集合又は順序差')
    need(condition['約定追加価格時計遅延秒'] == [0, 1] and condition['同時一建玉'] is True and condition['新損益前固定'] is True, '時計・所有・事前固定差')
    for name, expected in (('新規数量micro枚',100),('片側上限',100),('point_value',10),('片道手数料円',11),('片道滑りpt',5),('主往復費用円毎枚',122),('G1悪化余裕pt',10),('G1全玉予算目標円',1)):
        need(type(condition[name]) is int and condition[name] == expected, '固定数量・費用差:' + name)
    groups = [condition['コードと依存SHA256']]
    folders = {80:'00080_FAR後期三手法の15分移植と利益保護',81:'00081_定時の現在根拠と部分利益保護',82:'00082_チャートの現在性と補助確認',83:'00083_構造否定と利益配分'}
    for version, folder in folders.items():
        name = f'固定{version}依存'
        need(condition[name] == reference[name + '指紋'], '固定依存集合差:' + name)
        groups.append(condition[name])
        need(reference[f'固定{version}条件SHA256'] == sha(ROOT / 'study' / folder / '条件.json'), '旧条件指紋差')
    groups.append({condition['実行ファイル']: condition['実行ファイルSHA256']})
    checked = {}
    market = Path(read_json(manifest)['source_root']).resolve()
    for group in groups:
        need(type(group) is dict and bool(group), '固定依存が空')
        for name, wanted in group.items():
            path = Path(name)
            path = (path if path.is_absolute() else ROOT / path).resolve()
            need(not path.is_relative_to(market) and sha(path) == wanted, '固定依存変更又は原板参照:' + name)
            checked[str(path)] = wanted
    return checked


def comparison_pairs() -> list[tuple[str, str, str]]:
    """
    機能: 三入口の比較方向をAからBへ固定する。
    引数: なし。
    返り値: list[tuple[str,str,str]] は名称・比較元・比較先。
    """
    return [('C0対A0','A0G1','C0G1'),('C1対A0','A0G1','C1G1'),('C1対C0','C0G1','C1G1')]


def expected_policy(base: dict, policy: str, clock: bool) -> dict:
    """
    機能: 保存旧チェックから追加AND・未知・役割・競合保持を独立に組み立てる。
    引数: base (dict) は旧B1保存判断、policy (str) はA0/C0/C1、clock (bool) は時計許可。
    返り値: dict は公開PolicySnapshotと同じ形。元指標系列自体は再生成しない。
    """
    need(policy in POLICIES and base['policy'] == 'B1', '旧政策又は追加政策差')
    need([direction['side'] for direction in base['directions']] == [1,-1], '旧二方向の順序差')
    directions = []
    ids = [] if policy == 'A0' else ['現在価格帯','反対圧力'] + (['同価格数量支持'] if policy == 'C1' else [])
    for old in base['directions']:
        checks = {check['id']: check for check in old['checks']}
        need(len(checks) == len(old['checks']), '旧チェックID重複')
        added = [{**checks[ident], 'group':'追加必須'} for ident in ids]
        for check in added:
            need(type(check['known']) is bool and type(check['passed']) is bool and (check['known'] or not check['passed']), '追加チェック既知性差')
        allowed = old['allowed'] and all(check['passed'] for check in added)
        unknown = old['required_unknown'] or any(not check['known'] for check in added)
        reasons = [] if old['allowed'] else ['旧B1不成立:' + old['reason']]
        for check in added:
            if not check['known']:
                reasons.append(check['id'] + '未知')
            elif not check['passed']:
                reasons.append(check['id'] + '不成立')
        role = old['role'] if allowed else '判定不能' if unknown else '待機'
        reason = old['role'] + 'の現在価格応答成立' if allowed else '／'.join(reasons)
        if policy == 'A0':
            role, reason, unknown = old['role'], old['reason'], old['required_unknown']
        elif allowed:
            unknown = False
        directions.append({'side':old['side'],'allowed':allowed,'role':role,'reason':reason,'required_unknown':unknown,'added_checks':added})
    selected = [direction for direction in directions if direction['allowed']]
    allowed = len(selected) == 1
    unknown = any(direction['required_unknown'] for direction in directions)
    side, role, reason = 0, '待機', '現在の新規根拠なし'
    if allowed:
        side, role, reason, unknown = selected[0]['side'], selected[0]['role'], selected[0]['reason'], False
    elif len(selected) > 1:
        role, reason, unknown = '競合待機', '両方向の現在根拠が競合', False
    else:
        role = '判定不能' if unknown else '待機'
        reason = '買:' + directions[0]['reason'] + '／売:' + directions[1]['reason']
    if policy == 'A0':
        allowed, side, role, reason, unknown = [base[name] for name in ('allowed','side','role','reason','required_unknown')]
    elif base['role'] == '競合待機':
        allowed, side, role, reason, unknown = False, 0, '競合待機', '旧B1の両方向競合を維持', False
    return {'allowed':allowed,'side':side,'role':role,'reason':reason,'required_unknown':unknown,'directions':directions,'candidate_accepted':clock and allowed}


def verify_grids(rows: list[dict], result: dict, diagnostics: dict, sessions: list[str]) -> tuple[dict, dict]:
    """
    機能: 全2442定時から三入口の可用性・追加AND・未知・役割と実新規の発生元を結ぶ。
    引数: rows (list[dict]) は圧縮判断、result/diagnostics (dict) は結果と玉、sessions (list[str]) は66場。
    返り値: tuple[dict,dict] は可用性と政策別最終状態。原指標は再計算しない。
    """
    need(len(rows) == 66 and {row['session'] for row in rows} == set(sessions), '定時診断66場差')
    availability = {p:{'全定時':0,'時計許可':0,'方向判定成立':0,'候補生成':0,'判定項目':{},'支持未知理由':Counter()} for p in POLICIES}
    stats = {p:Counter() for p in POLICIES}
    supplied = {}
    zone = timezone(timedelta(hours=9))
    for row in rows:
        session = row['session']
        start = datetime.fromisoformat(session[:10]).replace(tzinfo=zone)
        first = start + (timedelta(hours=9,minutes=15) if session.endswith('Day') else timedelta(hours=17,minutes=30))
        length = 25 if session.endswith('Day') else 49
        expected = {(first + timedelta(minutes=15*i)).timestamp() for i in range(length)}
        seen = set()
        for grid in row['grid_decisions']:
            at, base = grid['at'], grid['decision']
            need(at in expected and at not in seen and grid['entry_policy'] == 'B1' and base['at'] == at, '旧B1定時の欠落・重複・時計差')
            seen.add(at)
            need(type(grid['clock_allowed']) is bool and set(grid['policies']) == set(POLICIES), '時計又は政策集合差')
            q, tech, evidence = base['quote'], base['technical'], base['evidence']
            need(number(q['time']) <= number(at) and number(evidence['time']) <= number(at), '未来snapshot使用')
            need(number(tech['bar3_end']) <= number(at) and number(tech['bar15_end']) <= number(at), '未来確定足使用')
            verify_anchor(grid['structure_anchor'], at)
            if grid['structure_anchor']['known']:
                need(tech['exit_known'] and grid['structure_anchor']['price'] == tech['ema8_3'] and grid['structure_anchor']['bar_end'] == tech['bar3_end'], '当時EMA記録差')
            need(grid['candidate_accepted'] == grid['policies']['A0']['candidate_accepted'], '旧候補とA0差')
            for policy in POLICIES:
                current = grid['policies'][policy]
                need(current == expected_policy(base,policy,grid['clock_allowed']), '保存旧チェックからの政策再計算差:' + policy)
                item, state = availability[policy], stats[policy]
                for name, value in (('全定時',1),('時計許可',grid['clock_allowed']),('方向判定成立',current['allowed']),('候補生成',current['candidate_accepted'])):
                    item[name] += value
                state['許可'] += current['allowed']
                state['候補'] += current['candidate_accepted']
                state['必須未知'] += current['required_unknown']
                state['既知不許可'] += not current['allowed'] and not current['required_unknown']
                state['許可初動'] += current['allowed'] and current['role'] == '転換初動'
                for old, added in zip(base['directions'],current['directions'],strict=True):
                    if added['allowed']:
                        item.setdefault('方向許可の役割',Counter())[added['role']] += 1
                    for check in old['checks'] + added['added_checks']:
                        name = check['group'] + ':' + check['id']
                        totals = item['判定項目'].setdefault(name,{'方向数':0,'既知':0,'成立':0,'未知':0})
                        need(type(check['known']) is bool and type(check['passed']) is bool and (check['known'] or not check['passed']), '保存チェック既知性差')
                        for field,value in (('方向数',1),('既知',check['known']),('成立',check['passed']),('未知',not check['known'])):
                            totals[field] += value
                for side in ('buy','sell'):
                    for field in ('own_reason','peer_reason','ofi_reason'):
                        reason = evidence[side][field]
                        if reason:
                            item['支持未知理由'][field + ':' + reason] += 1
                if current['candidate_accepted']:
                    identity = f"{session}_B1_{float(at):.9f}_{current['side']:+d}"
                    supplied[policy,session,identity] = grid
        need(seen == expected, '全予定枠が不足')
    need(availability == result['定時の候補と入力可用性'], '三政策の候補・未知・役割集計差')
    for key, identities in diagnostics.items():
        for identity, row in identities.items():
            joined = (key[:2],*identity)
            need(joined in supplied, '実新規に対応する当時の入口候補がない')
            grid = supplied[joined]
            need(row['lot']['structure_anchor'] == grid['structure_anchor'] and row['entry_order']['request_time'] == grid['at'], '実新規と固定EMA又は定時差')
    return availability, stats


def verify_exports(paths: dict, catalog: dict, diagnostics: dict, sessions: list[str]) -> None:
    """
    機能: Viewer約定の外側ラベルと、内部S0G1所有・価格・数量・費用・時刻を結ぶ。
    引数: paths/catalog (dict) は明示一覧、diagnostics (dict) は内部金融の全玉、sessions (list[str]) は66場。
    返り値: None。表示ラベル以外の変更・欠落・重複を拒否する。
    """
    resources = {row['id']:row for row in catalog['resources']}
    for session in sessions:
        for key in KEYS:
            resource = resources[f'84_{key}_{session}']
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


def verify_entry_audit(paths: dict, values: dict, result: dict, rows: dict, stats: dict, sessions: list[str]) -> None:
    """
    機能: 独立入口監査を全再生SHA・旧基準・政策件数・金融/方針判断へ厳密結合する。
    引数: paths/values (dict) は11明示正本、result/rows/stats (dict) は検査済結果、sessions (list[str]) は66場。
    返り値: None。未完・別入力・対象不足・保存後変更を拒否する。
    """
    audit = values['entry_audit']
    need(audit['試行'] == 84 and audit['成功'] is True and audit['処理完了'] is True and audit['入力不変'] is True, '入口監査が未完')
    need(count(audit['照合項目数']) > 0, '入口監査の照合実績が必要')
    need((count(audit['場数']),count(audit['予定枠']),count(audit['基準会計数'])) == (66,2442,132) and count(audit['不一致数']) == 0 and not audit['不一致'], '入口監査の全対象完了が必要')
    need(audit['入力SHA256前'] == audit['入力SHA256後'] and set(audit['入力SHA256前']) == {'84','83','82'}, '入口監査の前後入力差')
    inventories = audit['入力SHA256前']
    need(inventories['84'] == result['再生結果SHA256'], '入口監査と84結果本文SHA差')
    old_paths = {83:ROOT/'study/00083_構造否定と利益配分/成果物/結果.json',82:ROOT/'study/00082_チャートの現在性と補助確認/成果物/結果.json'}
    for version,path in old_paths.items():
        need(inventories[str(version)] == read_json(path)['再生結果SHA256'], '入口監査の旧基準本文SHA差')
    small_paths = [paths['manifest'],*old_paths.values(),ROOT/'scripts/構造否定と利益配分/基準と入口の照合.py',ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',
        ROOT/'study/00083_構造否定と利益配分/条件.json',ROOT/'study/00082_チャートの現在性と補助確認/条件.json']
    expected = {Path(os.path.relpath(path,ROOT)).as_posix():sha(path) for path in small_paths}
    need(audit['固定小型入力SHA256'] == expected, '入口監査の小型依存集合・SHA差')
    need(audit['照合コードSHA256'] == sha(Path(__file__).with_name('基準と保存判断の照合.py')) and audit['読取helperSHA256'] == sha(ROOT/'scripts/構造否定と利益配分/基準と入口の照合.py'), '入口監査コードSHA差')
    wanted_stats = {policy+':'+name:value for policy,group in stats.items() for name,value in group.items()}
    need(audit['政策件数合計'] == wanted_stats and audit['政策全予定枠'] == {policy:2442 for policy in POLICIES}, '入口監査の三政策可用数差')
    scenes = {row['場']:row for row in audit['対象場']}
    need(len(scenes) == len(audit['対象場']) == 66 and set(scenes) == set(sessions), '入口監査の対象場集合差')
    actions = {(row['session'],row['key']):row for row in audit['方針判断']}
    need(len(actions) == len(audit['方針判断']) == 396 and set(actions) == set(rows), '入口監査の方針判断396件差')
    summed = Counter()
    for session in sessions:
        scene = scenes[session]
        need(scene['予定枠'] == (25 if session.endswith('Day') else 49) and scene['基準会計'] == 2, '入口監査の場別予定枠・基準差')
        summed.update(scene['政策件数'])
        scene_actions = {(row['session'],row['key']):row for row in scene['方針判断']}
        need(len(scene_actions) == len(scene['方針判断']) == 6 and set(scene_actions) == {(session,key) for key in KEYS}, '場別方針判断集合差')
        for key in KEYS:
            identity = session,key
            source, saved = actions[identity], rows[identity]
            need(source == scene_actions[identity] and source['金融判断'] == saved['判断'] and source['方針判断'] == saved['方針判断'], '金融判断又は方針判断の独立集計差')
    need(dict(summed) == wanted_stats, '入口監査の場別政策件数差')


def prepare(paths: dict, study: Path) -> dict:
    """
    機能: 明示11正本を全件検査し、同じ入力の帳票だけを準備する。
    引数: paths (dict[str,Path]) は11入力、study (Path) は保存先。
    返り値: dict は本文・指紋・集計・独立規範を結合した帳票入力。
    """
    required = ('result','catalog','cash_audit','raw_audit','viewer_audit','condition','input_reference','manifest','trades','grids','entry_audit')
    need(set(paths) == set(required), '11明示入力の不足又は余剰')
    hashes = {str(path.resolve()):sha(path) for path in paths.values()}
    values = {name:read_json(paths[name]) for name in required if name not in ('trades','grids')}
    sessions = [row['id'] for row in values['manifest']['sessions']]
    need(len(sessions) == len(set(sessions)) == 66, '一意の66場台帳が必要')
    dependencies = fixed_dependencies(values['condition'],values['input_reference'],paths['manifest'])
    result = values['result']
    need(result['入力台帳SHA256'] == sha(paths['manifest']), '結果の台帳SHA差')
    rows = verify_summary(result,sessions)
    diagnostics = verify_diagnostics(compressed_rows(paths['trades']),result,sessions)
    grids = compressed_rows(paths['grids'])
    availability,stats = verify_grids(grids,result,diagnostics,sessions)
    auxiliary = verify_auxiliary(grids)
    normative = verify_audits(paths,values,result,rows,diagnostics,sessions)
    verify_entry_audit(paths,values,result,rows,stats,sessions)
    verify_exports(paths,values['catalog'],diagnostics,sessions)
    settings = (study/'設定と結果.md').read_text(encoding='utf-8')
    need(settings.count(BEGIN) == settings.count(END) == 1 and STATUS in settings, '固定設定マーカー差')
    verify_table(settings,study)
    need({str(path.resolve()):sha(path) for path in paths.values()} == hashes, '帳票読取中の入力変更')
    return {'result':result,'paths':paths,'input_sha':hashes,'dependencies':dependencies,'settings':settings,'availability':availability,'stats':stats,'auxiliary':auxiliary,'normative':normative,'entry':values['entry_audit'],'raw':values['raw_audit']}


def result_block(data: dict) -> str:
    """
    機能: 三入口・二遅延の6案を同じ費用基準の結果表へ整形する。
    引数: data (dict) は全照合を通過した帳票入力。
    返り値: str は設定専用マーカーへ入れるMarkdown。
    """
    lines = ['正式66場・三入口×二遅延、金融は全て固定83S0G1。全場既使用。','',
        '| ID | 費用後損益円 | 最大DD円 | 赤字場 | 完結玉 | 全玉正益後赤字 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row = data['result']['比較'][key]
        lines.append(f"| {key} | {amount(row['費用後損益円'])} | {amount(row['最大DD円'])} | {row['赤字場数']}/66 | {row['完結玉']} | {ratio(row['全玉旗後赤字'],row['全玉旗'])} |")
    if not sum(row['完結玉'] for row in data['result']['比較'].values()):
        lines.extend(['','実新規0。0損益を入口又は利益保護の改善としない。市場効果は未評価。'])
    lines.extend(['','G1は費用後現在益strict正で最低建値床と部分返済を起動するが、費用後黒字を保証しない。追加条件単独の因果効果又は未使用期間の安定利益とは解釈しない。'])
    return '\n'.join(lines)


def render_readme(data: dict, study: Path) -> str:
    """
    機能: 入口追加条件の仮説と可用性・損益・参加差・保護を再利用可能な帳票へまとめる。
    引数: data (dict) は検査済11正本、study (Path) は相対参照の基準。
    返り値: str はREADME全文。原板や全取引の重複転記はしない。
    """
    result, paths = data['result'],data['paths']
    main = [result['比較'][key] for key in KEYS if key.endswith('_D0')]
    outcome = '実新規0であり市場効果は未評価。' if not sum(row['完結玉'] for row in main) else '主費用で黒字の案はなかった。' if not any(row['費用後損益円']>0 for row in main) else '主費用で観測黒字の案があったが、既使用期間の探索であり安定利益は未確認。'
    text = ['# 00084：現在の価格応答と数量確認','','2026-11-07。'+outcome,'',
        'チャート背景へ取得時点の両気配の進行後維持・反対圧力の解消を加え、さらに表示数量回復を加える入口を比較した。3入口とも固定83S0G1の損失・利益保護を同じに使う。旧70%・125/250先着・待ち50%は合格判定から一旦外す。',
        '[検証計画](検証計画.md)・[設定IDと版5の55×9表](設定と結果.md)・[候補と市場心理](../../docs/議論/チャート方向に現在の価格応答を重ねる候補.md)を参照する。元FAR後期三手法の部品を使う別仮説で、元売買列の同値再現ではない。','',
        '## 入口と共通条件','','| 入口 | 旧チャート背景への追加 |','| --- | --- |',
        '| A0 | 固定82B1をそのまま維持し、固定83S0G1との数値同値を確認 |',
        '| C0 | 同じ方向の旧許可Dに、構造既知K・fresh帯維持B・反対圧力解消AをAND |',
        '| C1 | C0にfresh同価格表示数量回復QをAND |','',
        '共通主軸は3/15分EMA8−21、3分MACDhist増分・EMA8回復・0..1ATR取得位置、RSI/TR同時急変警戒。既知短秒/OFI反対拒否と失速時追加支持も維持する。初動は旧B1のRSI増分・前足からの回復・B/Q/Aを全保持し、旧両方向競合は追加ANDで片方だけ残っても競合待機を続ける。',
        'BはE08同方向holdがactive・未pressured・60秒/32価格更新以内でBid/Ask両方が帯の方向側。源8更新・両気配20pt・方向比0.625・2更新確認を変えない。Qも60秒/32更新以内。Aはfresh障害回復点の返済側BBO10pt通過とfresh反対数量支持の消失。未知と既知不成立を分け、表示数量を実約定量や意図そのものと解釈しない。','',
        '新規は初回を除くDay09:15..15:15/Night17:30..翌05:30の15分枠。NY09:30前後15分は静観し前窓返済、場末15:35/05:50返済要求。保護と確定3分の技法失敗は全原行で連続、売買は符号反転の同条件。',
        '100micro固定・片側100・同時一建玉は比較尺度で推奨数量ではない。1枚10円/pt、片道手数料11円＋想定滑り5pt、往復122円。次正常ラージBBOを代理約定に使い、追加価格時計1秒は別約定列で実時間ちょうど1秒後とは限らない。',
        '全案で新規時ATR3のceil5を15..125ptへ固定し未知125、正益前から非緩和ATR追尾・125pt保護を使う。費用後現在単価益10×方向幅−122円がstrict正になれば最低建値床とG1部分返済を即起動し、全量約定後の実確定益だけを残玉予算へ入れる。固定EMA構造床S1や全量追尾G2は今回使わない。建値返済でも費用と次板悪化で赤字となり得る。','',
        '## 損益と利益保全','',result_block(data),'',
        '| ID | 粗損益円 | 費用円 | 正益未観測円 | 正益観測円 | 残玉正益後赤字 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=result['比較'][key]
        text.append(f"| {key} | {amount(row['総計']['gross_pnl_yen'])} | {amount(row['総計']['total_cost_yen'])} | {amount(row['正益未観測の損益円'])} | {amount(row['正益観測の損益円'])} | {ratio(row['残玉旗後赤字'],row['残玉旗'])} |")
    text.extend(['','全玉旗は実確定部分を含む全取引の費用後額、残玉旗は現在の単価純益。利益を観測した後の赤字を保護成功へ読み替えない。','',
        '| ID | Day円 | Night円 | 赤字日/日数 | 同約定滑り0pt円 | 同約定滑り10pt円 | 上位3場利益円 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |'])
    for key in KEYS:
        row=result['比較'][key]
        day=sum(number(scene['metrics']['net_pnl_yen']) for scene in result['場別'] if scene['key']==key and scene['session'].endswith('Day'))
        text.append(f"| {key} | {amount(day)} | {amount(number(row['費用後損益円'])-day)} | {row['赤字日数']}/{row['日数']} | {amount(row['同約定0pt損益円'])} | {amount(row['同約定10pt損益円'])} | {amount(row['上位3場利益円'])} |")
    text.extend(['','同約定0/10ptは価格列を変えない費用感応、D1は別の約定列。日別・昼夜と費用込みDDを区別する。','',
        '## 同じ実入口と参加差','','比較[A,B]のB−A。同一予定枠・方向でも取得時刻/価格/数量が変わる群を分ける。純候補のC1⊆C0⊆A0と、占有で変わる実参加の包含を混同しない。','',
        '| 比較 | 同実入口 | A円 | B円 | 出口差円 | 取得変更 | Aのみ件/円 | Bのみ件/円 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |'])
    for name,row in result['入口間の同実新規分解'].items():
        text.append(f"| {name} | {row['同実新規']} | {amount(row['同実新規A損益円'])} | {amount(row['同実新規B損益円'])} | {amount(row['同実新規出口差円'])} | {row['共通だが取得変更']} | {row['Aのみ']} / {amount(row['Aのみ損益円'])} | {row['Bのみ']} / {amount(row['Bのみ損益円'])} |")
    text.extend(['','片側の保存損益は除外した損失/失った勝ちの診断であり、その群を加減して未再生の戦略成績を作らない。同実入口の出口が同じなら入口選別の差を利益保護の改善と呼ばない。','',
        '## 候補・追加条件・未知','','| 入口 | 全予定枠 | 時計許可 | 最終許可 | 候補供給 | 必須未知 | 既知不許可 | 許可初動 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |'])
    for policy in POLICIES:
        row,state=data['availability'][policy],data['stats'][policy]
        text.append(f"| {policy} | {row['全定時']} | {row['時計許可']} | {row['方向判定成立']} | {row['候補生成']} | {state['必須未知']} | {state['既知不許可']} | {state['許可初動']} |")
    text.extend(['','| 入口 | 方向許可の役割 | 件数 |','| --- | --- | ---: |'])
    for policy in POLICIES:
        for role,n in sorted(data['availability'][policy].get('方向許可の役割',{}).items()):
            text.append(f'| {policy} | {role} | {n} |')
    text.extend(['','方向許可は方向別、最終許可・必須未知は定時別。片側成立なら他側未知でも最終許可でき、競合は新規不可。これらを同じ分母に合算しない。','',
        '| 入口 | 追加必須チェック | 方向数 | 既知 | 成立 | 未知 |',
        '| --- | --- | ---: | ---: | ---: | ---: |'])
    for policy in POLICIES:
        for name,row in data['availability'][policy]['判定項目'].items():
            if name.startswith('追加必須:'):
                text.append(f"| {policy} | {name.split(':',1)[1]} | {row['方向数']} | {row['既知']} | {row['成立']} | {row['未知']} |")
    text.extend(['','## 金融判断と方針判断','','固定Bookの金融判断はA0基準の全文同値のため無変更。非占有の金融「待ち」で時計許可かつ政策の必須値未知の枠だけ、別集計の方針判断を「判定不能」へ変える。保有・処理中・新規は優先し、未知であることを市場の反対や待ち選択とみなさない。旧待ち率の合格判定には使わない。','',
        '| ID | 分類 | 新規要求 | 保有継続 | 処理中 | 待ち | 判定不能 |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |'])
    for key in KEYS:
        for field,label in (('判断','金融'),('方針判断','方針')):
            row=result['比較'][key][field]
            text.append('| '+key+' | '+label+' | '+' | '.join(str(row.get(name,0)) for name in ('新規要求','保有継続','処理中','待ち','判定不能'))+' |')
    text.extend(['','## 日別損益','','| 日付 | '+' | '.join(KEYS)+' |','| --- | '+' | '.join('---:' for _ in KEYS)+' |'])
    dates=sorted({day for row in result['比較'].values() for day in row['日別円']})
    for day in dates:
        text.append('| '+day+' | '+' | '.join(amount(result['比較'][key]['日別円'][day]) for key in KEYS)+' |')
    text.extend(['','## 独立照合・保存・限界','',
        f"保存会計396件、原板66場、Viewer396資源を結合した。入口監査は{data['entry']['照合項目数']:,}項目・2,442予定枠・132基準会計で差0。追加ANDの再計算と元のEMA/ATR/E08生成器の独立再実装は別であり、後者は範囲外。",''] )
    references=(('result','結果正本'),('catalog','Viewer396資源'),('cash_audit','保存会計'),('raw_audit','原板保護規範'),('viewer_audit','Viewer数値'),('condition','固定条件'),('input_reference','入力参照'),('manifest','固定66場台帳'),('trades','圧縮玉診断'),('grids','圧縮定時判断'),('entry_audit','基準・追加AND・方針判断'))
    text.extend([' · '.join(link(study,paths[name],label) for name,label in references),'',
        '原板監査の予約不足・利確要求不足・構造要求不足は全案0を必要とする。金融内部ラベルはS0G1、Viewerの表示手法名だけ外入口A0G1/C0G1/C1G1へ写し、内部ID・価格・数量・費用・所有・時刻を結合検査する。','',
        '全66場は既使用で、6会計・接続2場を独立標本に増やさない。少数黒字・無取引・日付集中を安定利益とみなさない。ラージBBOでmicro全量を代理約定する仮定であり、実通信・板深さ消費・約定順位・証拠金は未実証。原指標系列自体の独立再生成と保存全峰/谷の個別全値照合は範囲外。','',
        '[閲覧補足](閲覧補足.md)に証拠の読み方と追加診断をまとめる。実行コードは[scripts/現在の価格応答と数量確認](../../scripts/現在の価格応答と数量確認/)へ分離する。帳票処理の原板読取・新売買再生・API利用は0。',''])
    command=['& "work/venvs/technical-tree/Scripts/python.exe" -B -X utf8 "scripts/現在の価格応答と数量確認/レポート.py" --check `','  --study "'+Path(os.path.relpath(study,ROOT)).as_posix()+'" `']
    for index,(name,_) in enumerate(references):
        command.append('  --'+name.replace('_','-')+' "'+Path(os.path.relpath(paths[name],ROOT)).as_posix()+'"'+(' `' if index<len(references)-1 else ''))
    text.extend(['ルートPowerShellから11正本を明示して同値確認する。正式生成は同じ入力で--checkを--runへ置換する。','','```powershell',*command,'```','','[帳票生成証拠](レポート生成証拠.json)へ全入力・固定依存・R・出力のSHAを保存する。',''])
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
    proof={'試行':84,'成功':True,'場数':66,'会計数':396,'Viewer資源数':396,
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


def fake_inputs(base: Path) -> tuple[Path, dict]:
    """
    機能: 市場原板・新売買・APIを使わず66場396会計・全予定枠の人工正本を作る。
    引数: base (Path) はwork配下の新規一時領域。
    返り値: tuple[Path,dict] は人工試行と明示11入力。
    """
    study=base/'人工試行'; output=study/'成果物'; output.mkdir(parents=True)
    paths={name:output/filename for name,filename in (('result','結果.json'),('catalog','一覧.resources.json'),('cash_audit','約定会計照合.json'),('trades','取引診断.jsonl.gz'),('grids','定時判断.jsonl.gz'))}
    paths.update({name:study/filename for name,filename in (('raw_audit','原板監査.json'),('viewer_audit','Viewer監査.json'),('entry_audit','基準と保存判断の照合.json'),('condition','条件.json'),('input_reference','入力参照.json'),('manifest','人工台帳.json'))})
    def save(path: Path, value: dict) -> None:
        """
        機能: 有限な人工JSONを専用領域へ保存する。
        引数: path (Path) は人工先、value (dict) は本文。
        返り値: None。
        """
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    sessions=[(datetime(2026,1,1)+timedelta(days=i)).date().isoformat()+'_'+kind for i in range(33) for kind in ('Day','Night')]
    save(paths['manifest'],{'source_root':str(base/'存在しない原板'),'sessions':[{'id':s} for s in sessions]})
    dep=base/'人工依存.txt';dep.write_text('帳票人工の小型依存。\n',encoding='utf-8')
    deps={str(dep):sha(dep)}
    common={'試行':84,'入力台帳SHA256':sha(paths['manifest']),'入力場数':66,'全場既使用':True}
    reference={**common,'入力台帳':str(paths['manifest']),'入力ファイル数':396,'固定80採用版':2}
    condition={**common,'modes':list(MODES),'entry_policies':list(POLICIES),'keys':list(KEYS),'約定追加価格時計遅延秒':[0,1],'新規数量micro枚':100,'片側上限':100,'point_value':10,'片道手数料円':11,'片道滑りpt':5,'主往復費用円毎枚':122,'G1悪化余裕pt':10,'G1全玉予算目標円':1,'同時一建玉':True,'新損益前固定':True,'コードと依存SHA256':deps,'実行ファイル':str(dep),'実行ファイルSHA256':sha(dep)}
    folders={80:'00080_FAR後期三手法の15分移植と利益保護',81:'00081_定時の現在根拠と部分利益保護',82:'00082_チャートの現在性と補助確認',83:'00083_構造否定と利益配分'}
    for version,folder in folders.items():
        condition[f'固定{version}依存']=deps
        reference[f'固定{version}依存指紋']=deps
        reference[f'固定{version}条件SHA256']=sha(ROOT/'study'/folder/'条件.json')
    save(paths['condition'],condition);save(paths['input_reference'],reference)
    fields=('net_pnl_yen','cash_yen','gross_pnl_yen','total_cost_yen','commission_yen','slippage_yen','open_quantity','pending_entry_quantity','reserved_exit_quantity','entry_quantity','exit_quantity','closed_lots','max_drawdown_yen','min_equity_yen','equity_peak_yen','harvest_orders','harvest_quantity','harvest_filled_quantity','harvest_done_lots','cash_floor_activated_lots','funding_failure_lots','whole_profit_flags','whole_flag_after_loss_lots','structure_known_entries','structure_unknown_entries','structure_activated_lots','structure_entry_breached_lots','structure_hit_lots','structure_exit_orders')
    zero=dict.fromkeys(fields,0)
    result={'試行':84,'場数':66,'全場既使用':True,'金融内部モード':'S0G1','入力台帳SHA256':sha(paths['manifest']),'再生結果SHA256':{s+'.json':hashlib.sha256(s.encode()).hexdigest() for s in sessions},'比較':{},'場別':[],'入口間の同実新規分解':{},'定時の候補と入力可用性':{p:{'全定時':2442,'時計許可':2442,'方向判定成立':0,'候補生成':0,'判定項目':{},'支持未知理由':{'own_reason:人工未準備':4884}} for p in POLICIES}}
    cash={'会計数':396,'不一致数':0,'照合':[]};catalog={'schema_version':1,'path_base':'catalog','resources':[]};viewer_rows=[]
    for key in KEYS:
        mode,delay=key.split('_D')
        result['比較'][key]={'mode':mode,'追加遅延秒':int(delay),'費用後損益円':0,'最大DD円':0,'全場':66,'赤字場数':0,'黒字場数':0,'同値場数':66,'赤字日数':0,'日数':33,'日別円':{s[:10]:0 for s in sessions},'完結玉':0,'残玉旗':0,'残玉旗後赤字':0,'全玉旗':0,'全玉旗後赤字':0,'正益未観測の損益円':0,'正益観測の損益円':0,'同約定0pt損益円':0,'同約定10pt損益円':0,'上位3場利益円':0,'最悪場円':0,'最大場円':0,'総計':deepcopy(zero),'返済理由別枚数':{},'返済理由別損益円':{},'判断':{'待ち':2442},'方針判断':{'判定不能':2442}}
        for session in sessions:
            length=25 if session.endswith('Day') else 49
            result['場別'].append({'session':session,'key':key,'mode':mode,'delay':int(delay),'metrics':deepcopy(zero),'累積損益円':0,'判断':{'待ち':length},'方針判断':{'判定不能':length}})
            cash['照合'].append({'session':session,'key':key,'約定数':0,'現金円':0,'粗損益円':0,'費用円':0,'残量':0})
            name=f'約定/D{delay}/{mode}/{session}.trades.jsonl';path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('',encoding='utf-8')
            identity=f'84_{key}_{session}'
            catalog['resources'].append({'id':identity,'symbol':'NK225','session':session,'method_id':mode,'product':'NK225micro','point_value':10,'pnl_format':'trades','pnl_basis':'net','pnl_path':name,'market_path':f'NK225/{session}/book.jsonl.gz'})
            viewer_rows.append({'id':identity,'完了':True,'不一致数':0,'不一致':[],'APIエラー':None,'API費用後円':0,'原純額円':0})
    for delay in (0,1):
        for label,a,b in comparison_pairs():
            result['入口間の同実新規分解'][f'{label}_D{delay}']={'比較':[f'{a}_D{delay}',f'{b}_D{delay}'],**dict.fromkeys(('同実新規','共通だが取得変更','同実新規A損益円','同実新規B損益円','同実新規出口差円','Aのみ','Bのみ','Aのみ損益円','Bのみ損益円','取得変更A損益円','取得変更B損益円'),0)}
    grid_rows=[];entry_scenes=[]
    for session in sessions:
        start=datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
        first=start+(timedelta(hours=9,minutes=15) if session.endswith('Day') else timedelta(hours=17,minutes=30));length=25 if session.endswith('Day') else 49
        grids=[]
        for index in range(length):
            at=(first+timedelta(minutes=15*index)).timestamp()
            aux={name:{'known':False,'state':'未知','reason':'人工未知'} for name in ('five','fifteen','ofi')}
            aux.update(dict.fromkeys(('slowdown_known','slowdown','structure_known','structure_support','pressure_clear'),False))
            checks=[{'group':'共通','id':'人工','known':False,'passed':False,'reason':'人工未知'}]+[{'group':'転換初動枝','id':name,'known':False,'passed':False,'reason':'人工未知'} for name in ('現在価格帯','反対圧力','同価格数量支持')]
            directions=[{'side':side,'allowed':False,'role':'判定不能','reason':'人工入力不足','required_unknown':True,'checks':deepcopy(checks),'auxiliary':deepcopy(aux)} for side in (1,-1)]
            base_decision={'at':at,'policy':'B1','allowed':False,'side':0,'role':'判定不能','reason':'買:人工入力不足／売:人工入力不足','required_unknown':True,'directions':directions,'quote':{'time':0},'technical':{'bar3_end':0,'bar15_end':0},'evidence':{'time':0,**{side:{'own_reason':'人工未準備','peer_reason':'','ofi_reason':''} for side in ('buy','sell')}}}
            policies={p:expected_policy(base_decision,p,True) for p in POLICIES}
            grids.append({'at':at,'entry_policy':'B1','decision':base_decision,'clock_allowed':True,'candidate_accepted':False,'structure_anchor':{'known':False,'price':0,'at':0,'bar_end':0,'reason':'人工未知'},'policies':policies})
            for p in POLICIES:
                for old,current in zip(directions,policies[p]['directions'],strict=True):
                    for check in old['checks']+current['added_checks']:
                        item=result['定時の候補と入力可用性'][p]['判定項目'].setdefault(check['group']+':'+check['id'],{'方向数':0,'既知':0,'成立':0,'未知':0})
                        item['方向数']+=1;item['未知']+=1
        grid_rows.append({'session':session,'grid_decisions':grids})
        actions=[{'session':session,'key':key,'金融判断':{'待ち':length},'方針判断':{'判定不能':length}} for key in KEYS]
        entry_scenes.append({'場':session,'予定枠':length,'基準会計':2,'政策件数':{p+':'+name:length if name=='必須未知' else 0 for p in POLICIES for name in ('許可','候補','必須未知','既知不許可','許可初動')},'方針判断':actions})
    for name,content in (('trades',[]),('grids',grid_rows)):
        with gzip.open(paths[name],'wt',encoding='utf-8') as stream:
            for row in content:
                stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    for name,value in (('result',result),('catalog',catalog),('cash_audit',cash)):
        save(paths[name],value)
    norms=dict.fromkeys(('正常保有原行','正益後保有原行','床到達原行','125pt到達原行','cash床原行','返済義務原行','予約不足原行','予約不足数量','利確要求義務原行','利確要求不足原行','利確量検査','構造活性原行','構造到達原行','構造要求不足原行'),0)
    raw={'試行':84,'成功':True,'場数':66,'不一致数':0,'不一致':[],'入力台帳SHA256':sha(paths['manifest']),'監査コードSHA256':sha(Path(__file__).with_name('原板監査.py')),'固定80監査SHA256':sha(ROOT/'scripts/FAR後期15分移植/原板照合.py'),'固定83監査SHA256':sha(ROOT/'scripts/構造否定と利益配分/原板監査.py'),'対象場':[{'session':s,'再生結果SHA256':result['再生結果SHA256'][s+'.json'],'不一致数':0,'不一致':[],'診断':{'場':s,'JSON本文走査回数':1,'全玉費用後評価':{k:[] for k in KEYS},'利益床の独立規範':{k:deepcopy(norms) for k in KEYS}}} for s in sessions]}
    save(paths['raw_audit'],raw)
    files=[paths['result'],paths['catalog']]+[output/row['pnl_path'] for row in catalog['resources']];hashes={str(path):sha(path) for path in files}
    save(paths['viewer_audit'],{'試行':84,'成功':True,'完了資源':396,'予定資源':396,'不一致数':0,'APIエラー':[],'入力不変':True,'入力SHA256前':hashes,'入力SHA256後':hashes,'結果SHA256':sha(paths['result']),'一覧SHA256':sha(paths['catalog']),'監査コードSHA256':sha(Path(__file__).with_name('表示監査.py')),'資源':viewer_rows})
    old_paths={83:ROOT/'study/00083_構造否定と利益配分/成果物/結果.json',82:ROOT/'study/00082_チャートの現在性と補助確認/成果物/結果.json'}
    inventories={'84':result['再生結果SHA256'],**{str(v):read_json(path)['再生結果SHA256'] for v,path in old_paths.items()}}
    small_files=[paths['manifest'],*old_paths.values(),ROOT/'scripts/構造否定と利益配分/基準と入口の照合.py',ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',ROOT/'study/00083_構造否定と利益配分/条件.json',ROOT/'study/00082_チャートの現在性と補助確認/条件.json']
    totals=Counter()
    for scene in entry_scenes:
        totals.update(scene['政策件数'])
    save(paths['entry_audit'],{'試行':84,'成功':True,'処理完了':True,'場数':66,'予定枠':2442,'基準会計数':132,'照合項目数':1606382,'不一致数':0,'不一致':[],'入力不変':True,'入力SHA256前':inventories,'入力SHA256後':inventories,'政策件数合計':dict(totals),'政策全予定枠':{p:2442 for p in POLICIES},'対象場':entry_scenes,'方針判断':[row for scene in entry_scenes for row in scene['方針判断']],'固定小型入力SHA256':{Path(os.path.relpath(path,ROOT)).as_posix():sha(path) for path in small_files},'照合コードSHA256':sha(Path(__file__).with_name('基準と保存判断の照合.py')),'読取helperSHA256':sha(ROOT/'scripts/構造否定と利益配分/基準と入口の照合.py')})
    original=ROOT/'study/00084_現在の価格応答と数量確認/設定と結果.md';settings=original.read_text(encoding='utf-8')
    for method in read_json(ROOT/'scripts/レポート/手法カタログ_版5.json')['methods']:
        actual=ROOT/method['source'];settings=settings.replace(']('+Path(os.path.relpath(actual,original.parent)).as_posix()+')',']('+Path(os.path.relpath(actual,study)).as_posix()+')')
    (study/'設定と結果.md').write_text(settings,encoding='utf-8')
    return study,paths


def policy_cases() -> list[str]:
    """
    機能: 保存チェックからの政策計算で初動・競合・未知・数量差と売買鏡像を検査する。
    引数: なし。市場値を持たない二方向人工を使う。
    返り値: list[str] は成功した政策人工の名称。
    """
    checks = [{'id':name,'group':'転換初動枝','known':True,'passed':True,'reason':'人工成立'} for name in ('現在価格帯','反対圧力','同価格数量支持')]
    base = {'policy':'B1','allowed':True,'side':1,'role':'順行','reason':'順行の現在根拠成立','required_unknown':False,
        'directions':[{'side':1,'allowed':True,'role':'順行','reason':'順行の現在根拠成立','required_unknown':False,'checks':deepcopy(checks)},
                      {'side':-1,'allowed':False,'role':'待機','reason':'旧不成立','required_unknown':False,'checks':deepcopy(checks)}]}
    saved = deepcopy(base)
    need(all(expected_policy(base,p,True)['allowed'] for p in POLICIES),'全支持を三入口で保持')
    need(base == saved,'保存旧判断の不変')
    labels = ['全支持の三入口保持と入力不変']
    initial = deepcopy(base);initial['role']='転換初動';initial['reason']='転換初動の現在根拠成立';initial['directions'][0].update(role='転換初動',reason='転換初動の現在根拠成立')
    need(all(expected_policy(initial,p,True)['allowed'] and expected_policy(initial,p,True)['role']=='転換初動' for p in POLICIES),'旧初動を全政策に保持')
    labels.append('旧転換初動の全保持')
    quantity = deepcopy(base);quantity['directions'][0]['checks'][2]['passed']=False
    need(expected_policy(quantity,'C0',True)['allowed'] and not expected_policy(quantity,'C1',True)['allowed'] and not expected_policy(quantity,'C1',True)['required_unknown'],'数量既知不成立を未知へしない')
    labels.append('C0とC1の数量既知不成立差')
    quantity['directions'][0]['checks'][2]['known']=False
    need(expected_policy(quantity,'C0',True)['allowed'] and expected_policy(quantity,'C1',True)['required_unknown'],'数量未知をC0へ強制しない')
    labels.append('数量未知をC1だけに反映')
    band = deepcopy(base);band['directions'][0]['checks'][0].update(known=False,passed=False)
    need(expected_policy(band,'C0',True)['required_unknown'] and not expected_policy(band,'C0',True)['allowed'],'帯未知は必須値未知')
    labels.append('帯未知を必要未知として保持')
    band['directions'][0]['checks'][0]['known']=True
    need(not expected_policy(band,'C0',True)['required_unknown'] and expected_policy(band,'C0',True)['role']=='待機','既知不成立と未知の分離')
    labels.append('帯既知不成立と未知を分離')
    conflict = deepcopy(base);conflict.update(allowed=False,side=0,role='競合待機',reason='両方向の現在根拠が競合');conflict['directions'][1].update(allowed=True,role='順行',reason='順行の現在根拠成立');conflict['directions'][1]['checks'][0]['passed']=False
    need(all(not expected_policy(conflict,p,True)['allowed'] and expected_policy(conflict,p,True)['role']=='競合待機' for p in POLICIES),'旧競合から片側を復活させない')
    labels.append('旧両方向競合からの復活禁止')
    need(expected_policy(base,'C1',False)['allowed'] and not expected_policy(base,'C1',False)['candidate_accepted'],'時計拒否で候補だけを停止')
    labels.append('純許可と時計拒否の分離')
    mirror = deepcopy(base);mirror['side']=-1
    first,second = deepcopy(mirror['directions'][1]),deepcopy(mirror['directions'][0]);first['side']=1;second['side']=-1;mirror['directions']=[first,second]
    need(all(expected_policy(mirror,p,True)['allowed'] and expected_policy(mirror,p,True)['side']==-1 for p in POLICIES),'追加ANDの売買鏡像')
    labels.append('追加ANDの売買鏡像')
    return labels


def self_test() -> dict:
    """
    機能: 396会計と全予定枠の人工で生成同値・11入力・政策・表示の破損検出を確認する。
    引数: なし。work一時領域だけに人工を作り、原板・新売買・APIは使わない。
    返り値: dict は人工確認した項目と件数。
    """
    checks=policy_cases()
    with tempfile.TemporaryDirectory(prefix='84帳票人工_',dir=ROOT/'work') as directory:
        study,paths=fake_inputs(Path(directory).resolve())
        before=(study/'設定と結果.md').read_text(encoding='utf-8')
        generate(paths,study,False);generate(paths,study,True)
        need('実新規0' in (study/'README.md').read_text(encoding='utf-8'),'0取引の未評価表示が必要')
        need(before.split(BEGIN)[0]==(study/'設定と結果.md').read_text(encoding='utf-8').split(BEGIN)[0],'設定冒頭が変化')
        checks+=['人工396会計・全7326政策定時の生成同値','0取引を未評価表示','設定マーカー外不変']
        def reject(name: str, mutate: object, label: str) -> None:
            """
            機能: 一つの人工JSONの改変を帳票の全結合検査が拒否することを確認する。
            引数: name/label (str) は入力名と名称、mutate (callable) は本文変更。
            返り値: None。各人工後に元のbyte列へ戻す。
            """
            path=paths[name];saved=path.read_bytes();value=read_json(path);mutate(value)
            path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            try:
                prepare(paths,study)
            except (ValueError,KeyError,AssertionError):
                checks.append(label)
            else:
                raise AssertionError(label+'を拒否しなかった')
            finally:
                path.write_bytes(saved)
        cases=(('result',lambda v:v.update(試行=85),'試行差拒否'),('result',lambda v:v['場別'].pop(),'396会計欠落拒否'),
            ('result',lambda v:v.update(金融内部モード='C0G1'),'内部金融外ラベル混同拒否'),
            ('result',lambda v:v['比較']['A0G1_D0'].update(費用後損益円=1),'純額差拒否'),
            ('result',lambda v:v['入口間の同実新規分解']['C0対A0_D0'].update(Aのみ=1),'参加分解差拒否'),
            ('result',lambda v:v['比較']['C0G1_D0'].update(方針判断={'待ち':2442}),'方針判断差拒否'),
            ('cash_audit',lambda v:v.update(不一致数=1),'保存会計差拒否'),('raw_audit',lambda v:v.update(成功=False),'原板未完拒否'),
            ('raw_audit',lambda v:v['対象場'][0]['診断']['利益床の独立規範']['A0G1_D0'].update(予約不足原行=1),'連続保護不足拒否'),
            ('raw_audit',lambda v:v.update(固定83監査SHA256='0'*64),'原板固定83差拒否'),
            ('viewer_audit',lambda v:v.update(完了資源=395),'Viewer未完拒否'),('viewer_audit',lambda v:v.update(APIエラー=[{}]),'Viewer通信未完拒否'),
            ('viewer_audit',lambda v:v.update(入力不変=False),'Viewer入力変化拒否'),('condition',lambda v:v.update(entry_policies=['A0']),'政策集合差拒否'),
            ('input_reference',lambda v:v.update(固定83条件SHA256='0'*64),'固定83条件差拒否'),
            ('entry_audit',lambda v:v.update(処理完了=False),'入口監査未完拒否'),('entry_audit',lambda v:v.update(基準会計数=131),'132基準会計欠落拒否'),
            ('entry_audit',lambda v:v['入力SHA256前']['84'].update({'2026-01-01_Day.json':'0'*64}),'入口監査別再生拒否'),
            ('entry_audit',lambda v:v['政策件数合計'].update({'C0:必須未知':2441}),'政策未知数差拒否'),
            ('entry_audit',lambda v:v['方針判断'].pop(),'方針判断396欠落拒否'),
            ('entry_audit',lambda v:v.update(照合コードSHA256='0'*64),'入口照合コード差拒否'))
        for case in cases:
            reject(*case)
        saved=paths['grids'].read_bytes();rows=compressed_rows(paths['grids']);rows[0]['grid_decisions'][0]['policies']['C0']['allowed']=True
        with gzip.open(paths['grids'],'wt',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        try:
            prepare(paths,study)
        except (ValueError,KeyError,AssertionError):checks.append('追加AND破損拒否')
        else:raise AssertionError('追加AND破損を拒否しなかった')
        paths['grids'].write_bytes(saved)
        try:verify_table(before.replace('| I01 |','| I99 |',1),study)
        except (ValueError,KeyError):checks.append('版5手法ID差拒否')
        else:raise AssertionError('表ID差を拒否しなかった')
        generate(paths,study,True)
    return {'成功':True,'人工数':len(checks),'人工':checks,'市場原板読取':0,'新売買再生':0,'実API':0}


def main() -> None:
    """
    機能: 明示11正本による正式生成・同値確認と、市場なし人工を切り替える。
    引数: --run/--check/--self-test (bool)、--studyと11正本 (Path)。
    返り値: None。不整合又は未完監査は非0終了する。
    """
    parser=argparse.ArgumentParser(description='84の11正本から現在価格応答・数量確認の帳票を生成')
    stage=parser.add_mutually_exclusive_group(required=True)
    for name in ('run','check','self-test'):stage.add_argument('--'+name,action='store_true')
    parser.add_argument('--study',type=Path)
    names=('result','catalog','cash-audit','raw-audit','viewer-audit','condition','input-reference','manifest','trades','grids','entry-audit')
    for name in names:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.self_test:
        need(args.study is None and not any(getattr(args,name.replace('-','_')) for name in names),'人工と正式入力を混在させない')
        print(json.dumps(self_test(),ensure_ascii=False));return
    need(args.study is not None and all(getattr(args,name.replace('-','_')) is not None for name in names),'studyと11正本を全て明示する')
    paths={name.replace('-','_'):getattr(args,name.replace('-','_')).resolve() for name in names}
    proof=generate(paths,args.study.resolve(),args.check)
    print(json.dumps({name:proof[name] for name in ('試行','成功','場数','会計数','Viewer資源数','本処理の市場原板読取','新売買再生')},ensure_ascii=False))


if __name__=='__main__':main()
