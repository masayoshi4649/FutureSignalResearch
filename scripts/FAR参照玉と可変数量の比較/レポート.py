"""87の13明示正本を結び、FAR参照玉・可変量・C0追加の帳票を生成する。

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
POLICIES = ('S','SC')
MODES = ('R0G1','R1G1')
KEYS = tuple(f'{mode}_D{delay}' for delay in (0,1) for mode in MODES)
BEGIN = '<!-- 87_RESULTS_BEGIN -->'
END = '<!-- 87_RESULTS_END -->'
STATUS = '**新市場損益前の事前設定。Source参照生存・可変量へ現在C0を加える効果は未検証。**'
SAVED_SHA = '6763c012e0a3a9e03f9272555f6e40f80426074ea71fd380cc5f6877a5769df0'
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
    need(count(result["試行"]) == 87 and count(result["場数"]) == 66 and result["全場既使用"] is True, "87の66場が必要")
    need(result["金融内部モード"] == "S0G1", "全金融は固定S0G1が必要")
    need(result["保持帯床有効"] is False and result["複合確認有効"] == {"R0G1":False,"R1G1":False} and result["Source入口"] == {"R0G1":"S","R1G1":"SC"} and all(type(value) is bool for value in result["複合確認有効"].values()), "旧保持帯床off又は新複合確認設定差")
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
        expected_counts = {name: sum(count(r['metrics']['confirm_counts'][name]) for r in chosen) for name in SAVED.OLD.COUNTS}
        need(summary['複合確認5群'] == expected_counts, '確認5群の場別合計差')
        audit = SAVED.BASE.Audit(); SAVED.OLD.validate_counts(expected_counts, audit, key)
        need(audit.bad == 0, '複合確認5群の分母差')
        totals = summary["総計"]
        for name, total in totals.items():
            need(number(total) == sum((number(r["metrics"][name]) for r in chosen), Decimal(0)), "場別と総計差:" + key + name)
        qty = count(totals["entry_quantity"])
        need(qty == count(totals["exit_quantity"]) == count(summary["新規枚数"]), "変数量の新規/返済枚数差")
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
        need(1 <= count(lot["initial_quantity"]) == count(lot["closed_quantity"]) <= 100 and count(lot["quantity"]) == 0, "1..100枚完結の数量差")
        need(all(type(lot[n]) is bool for n in ("flag", "whole_flag", "cash_floor_active", "funding_failed", "structure_active", "structure_entry_breached")), "旗・構造状態はboolが必要")
        need(sum(number(c["pnl5"]) for c in row["closed"]) == number(lot["net_pnl"]) and sum(count(c["quantity"]) for c in row["closed"]) == lot["initial_quantity"], "返済片の数量・純額差")
        order = row["entry_order"]
        need(order["kind"] == "entry" and count(order["quantity"]) >= count(order["filled_quantity"]) == lot["initial_quantity"], "新規注文数量差")
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
        need(filled <= target <= lot["initial_quantity"], "部分予約と約定数量差")
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
            exact = {i for i in common if left[i]["entry_order"]["request_time"]==right[i]["entry_order"]["request_time"] and all(left[i]["lot"][n] == right[i]["lot"][n] for n in ("side", "entry_price", "entry_time", "initial_quantity"))}
            only_a, only_b, changed = set(left) - set(right), set(right) - set(left), common - exact
            d = decomposed[f"{name}_D{delay}"]
            need(d["比較"] == keys and d["同実新規"] == len(exact) and d["共通だが取得変更"] == len(changed) and d["Aのみ"] == len(only_a) and d["Bのみ"] == len(only_b), "出口間の参加数差")
            for field, subset, group in (("同実新規A損益円", exact, left), ("同実新規B損益円", exact, right), ("取得変更A損益円", changed, left), ("取得変更B損益円", changed, right), ("Aのみ損益円", only_a, left), ("Bのみ損益円", only_b, right)):
                need(number(d[field]) == sum(number(group[i]["lot"]["net_pnl"]) for i in subset), "出口分解額差:" + field)
            need(number(d["同実新規出口差円"]) == number(d["同実新規B損益円"]) - number(d["同実新規A損益円"]), "出口差の方向差")
    return grouped


def verify_viewer_correction(paths: dict, viewer: dict, result: dict) -> str:
    """
    機能: 対応分類だけの訂正を旧JSON/旧Viewer bytes復元で検査しAPI時点を保持する。
    引数: paths/viewer/result (dict) は現行正本と完了済みViewer証拠。
    返り値: str はAPI取得時の結果SHA。訂正なしなら現行結果SHA。
    """
    current=sha(paths['result'])
    if '対応分類訂正' not in viewer:return current
    correction=viewer['対応分類訂正']
    fields={'訂正対象','旧結果SHA256','新結果SHA256','訂正前の出口間の同実新規分解','旧経済射影SHA256','新経済射影SHA256','その他成果物SHA256','元Viewer監査SHA256','再集計コードSHA256','新市場再生'}
    need(type(correction) is dict and set(correction)==fields and correction['訂正対象']=='出口間の同実新規分解' and type(correction['新市場再生']) is int and correction['新市場再生']==0,'Viewer訂正の範囲差')
    need(correction['新結果SHA256']==current and correction['再集計コードSHA256']==sha(Path(__file__).with_name('集計.py')),'Viewer訂正の新結果/コード差')
    previous=deepcopy(result);previous['出口間の同実新規分解']=deepcopy(correction['訂正前の出口間の同実新規分解'])
    previous_bytes=(json.dumps(previous,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    oldsha=hashlib.sha256(previous_bytes).hexdigest()
    need(oldsha==correction['旧結果SHA256']==viewer['結果SHA256'],'分類一欄差戻しによる旧結果bytes復元差')
    projection={name:value for name,value in result.items() if name!='出口間の同実新規分解'}
    old_projection={name:value for name,value in previous.items() if name!='出口間の同実新規分解'}
    need(SAVED.canonical_sha(projection)==SAVED.canonical_sha(old_projection)==correction['旧経済射影SHA256']==correction['新経済射影SHA256'],'Viewer旧新経済射影の同値差')
    plain=deepcopy(viewer);plain.pop('対応分類訂正')
    plain_sha=hashlib.sha256((json.dumps(plain,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')).hexdigest()
    need(plain_sha==correction['元Viewer監査SHA256'],'完了済み元Viewer監査bytesの復元差')
    folder=paths['result'].parent
    inventory={path.relative_to(folder).as_posix():sha(path) for path in folder.rglob('*') if path.is_file() and path.resolve()!=paths['result'].resolve()}
    need(len(inventory)==269 and inventory==correction['その他成果物SHA256'],'Viewer分類以外の269成果物不変差')
    return oldsha


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
    need(count(raw["試行"]) == 87 and raw["成功"] is True and count(raw["場数"]) == 66 and count(raw["不一致数"]) == 0 and not raw["不一致"], "原板監査が未完又は不一致")
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
                need(entry["残量"] == 0 and entry["初回数量"] == lot["initial_quantity"] and number(entry["完結部分純額円"]) == number(lot["net_pnl"]), "原板の全玉数量又は純額差")
                need((entry["全玉初回正益"] is not None) == lot["whole_flag"] and entry["保存残玉旗"] == lot["flag"], "原板の全玉/残玉旗差")
                need(entry["全玉正益後に最後赤字"] == (lot["whole_flag"] and number(lot["net_pnl"]) < 0), "原板の旗後赤字差")
            counts = detail["利益床の独立規範"][key]
            for name, val in counts.items():
                normative[key][name] += count(val)
            for name in ("予約不足原行", "予約不足数量", "利確要求不足原行", "構造要求不足原行", "保持帯要求不足原行"):
                need(counts[name] == 0, "独立規範の保護又は利確要求不足")
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog", "Viewer一覧形式差")
    resources = catalog["resources"]
    resource_map = {r["id"]: r for r in resources}
    expected_ids = {f"87_{key}_{session}" for session, key in rows}
    need(len(resource_map) == len(resources) == 264 and set(resource_map) == expected_ids, "Viewer264資源の差")
    need(count(viewer["試行"]) == 87 and viewer["成功"] is True and count(viewer["予定資源"]) == count(viewer["完了資源"]) == 264 and count(viewer["不一致数"]) == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "Viewer全件成功が必要")
    api_result_sha=verify_viewer_correction(paths,viewer,result)
    need(viewer["結果SHA256"] == api_result_sha and viewer["一覧SHA256"] == sha(paths["catalog"]), "Viewer API取得時の正本SHA差")
    need(viewer["入力SHA256前"] == viewer["入力SHA256後"], "Viewer読取中の入力変更")
    current_files = {str(paths["result"].resolve()), str(paths["catalog"].resolve())}
    for resource in resources:
        session, key = next((s, k) for s, k in rows if resource["id"] == f"87_{k}_{s}")
        need((resource["symbol"], resource["session"], resource["method_id"], resource["product"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", session, key.split("_D")[0], "NK225micro", 10, "trades", "net"), "Viewer資源metadata差")
        path = (paths["catalog"].parent / resource["pnl_path"]).resolve()
        need(path.is_relative_to(paths["catalog"].parent), "約定参照が成果物外です")
        current_files.add(str(path))
    need(set(viewer["入力SHA256前"]) == current_files, "Viewer入力指紋集合差")
    for name, wanted in viewer["入力SHA256前"].items():
        need((wanted==api_result_sha if Path(name).resolve()==paths["result"].resolve() else sha(Path(name))==wanted), "Viewer照合後の正本変更又は訂正元SHA差")
    by_id = {r["id"]: r for r in viewer["資源"]}
    need(len(by_id) == len(viewer["資源"]) == 264 and set(by_id) == expected_ids, "Viewer資源別の完了集合差")
    for session, key in rows:
        v = by_id[f"87_{key}_{session}"]
        need(v["完了"] is True and v["不一致数"] == 0 and v["APIエラー"] is None, "Viewer個別未完了")
        need(number(v["API費用後円"]) == number(v["原純額円"]) == number(rows[session, key]["metrics"]["net_pnl_yen"]), "Viewer個別純額差")
    need(raw['監査コードSHA256'] == sha(Path(__file__).with_name('原板監査.py')) and raw['固定80監査SHA256'] == sha(ROOT/'scripts/FAR後期15分移植/原板照合.py') and raw['原板本文走査回数毎場'] == 1,'G1原板の停止コード又は1走査差')
    need(viewer["監査コードSHA256"] == sha(Path(__file__).with_name("表示監査.py")), "Viewer監査コードSHA差")
    return normative


def verify_exports(paths: dict, catalog: dict, diagnostics: dict, sessions: list[str]) -> None:
    """
    機能: Viewer約定の外側ラベルと、内部S0G1所有・価格・数量・費用・時刻を結ぶ。
    引数: paths/catalog (dict) は明示一覧、diagnostics (dict) は内部金融の全玉、sessions (list[str]) は66場。
    返り値: None。表示ラベル以外の変更・欠落・重複を拒否する。
    """
    resources = {row['id']:row for row in catalog['resources']}
    for session in sessions:
        for key in KEYS:
            resource = resources[f'87_{key}_{session}']
            path = (paths['catalog'].parent / resource['pnl_path']).resolve()
            trades = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            events = []
            for identity,row in diagnostics[key].items():
                if identity[0] != session:
                    continue
                lot,order = row['lot'],row['entry_order']
                prefix = 'Long' if lot['side'] == 1 else 'Short'
                events.append({'position_id':lot['id'],'time':lot['entry_time'],'type':prefix+'N','price':lot['entry_price'],'qty':lot['initial_quantity'],'fee_yen':61*lot['initial_quantity'],'source_line':lot['entry_line'],'reason':order['reason']})
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
    機能: 87条件・固定80..86依存・実行ファイルと旧条件7pathを結ぶ。
    引数: condition/reference (dict)、manifest (Path) は固定設定と台帳。
    返り値: dict[str,str] は本文SHA一致の依存。市場原板は開かない。
    """
    for value in (condition, reference):
        need(value['試行'] == 87 and value['入力台帳SHA256'] == sha(manifest), '87条件・入力台帳差')
        need(value['入力場数'] == 66 and value['全場既使用'] is True, '66既使用場が必要')
    need(reference['入力ファイル数'] == 396, '固定入力形式差')
    path = Path(reference['入力台帳'])
    need((path if path.is_absolute() else ROOT/path).resolve() == manifest.resolve(), '台帳参照先差')
    need(condition['modes'] == list(MODES) and condition['entry_policies'] == list(POLICIES) and condition['keys'] == list(KEYS), '4会計集合又は順序差')
    need(condition['金融内部モード'] == 'S0G1' and condition['hold_enabled'] == dict.fromkeys(MODES, False) and condition['confirm_enabled'] == dict.fromkeys(MODES,False) and condition['source_policy'] == {'R0G1':'S','R1G1':'SC'} and all(type(value) is bool for name in ('hold_enabled','confirm_enabled') for value in condition[name].values()), '金融・旧床off・複合on/off差')
    need(condition['約定追加価格時計遅延秒'] == [0,1] and condition['同時一建玉'] is True and condition['新損益前固定'] is True, '時計・所有・事前固定差')
    for name, expected in (('片側上限',100),('point_value',10),('片道手数料円',11),('片道滑りpt',5),('主往復費用円毎枚',122),('G1悪化余裕pt',10),('G1全玉予算目標円',1)):
        need(type(condition[name]) is int and condition[name] == expected, '固定数量・費用差:'+name)
    folders = {80:'00080_FAR後期三手法の15分移植と利益保護',81:'00081_定時の現在根拠と部分利益保護',82:'00082_チャートの現在性と補助確認',83:'00083_構造否定と利益配分',84:'00084_現在の価格応答と数量確認',85:'00085_保持帯の返済側固定否定',86:'00086_保持帯喪失と短秒反対の複合退出'}
    need(condition['新規数量micro枚']=='min(現在参照量,実空き量)' and condition['原板本文走査回数毎場']==2,'Source可変量又は原板計2走査差')
    groups = [condition['コードと依存SHA256']]
    for version in folders:
        key = f'固定{version}依存'
        need(condition[key] == reference[key+'指紋'], '固定依存集合差:'+key)
        groups.append(condition[key])
    expected_conditions = {f'study/{folder}/条件.json':sha(ROOT/'study'/folder/'条件.json') for folder in folders.values()}
    need(reference['旧条件SHA256'] == expected_conditions and len(reference['旧条件SHA256']) == 7, '旧条件7path明示指紋差')
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
    機能: 停止87保存監査の出典・型・canonical結合部品を読取で再用する。
    引数: なし。宣言済みSHAのPythonだけを読む。
    返り値: object は保存監査モジュール。原板・Go・売買は実行しない。
    """
    path=Path(__file__).with_name('基準と保存判断の照合.py')
    need(sha(path)==SAVED_SHA,'87保存監査の停止SHA差')
    spec=importlib.util.spec_from_file_location('saved87_for_report',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


SAVED = load_saved()


def comparison_pairs() -> list[tuple[str,str,str]]:
    """
    機能: Source＋C0のSCをSourceのみSへ対比する方向を固定する。
    引数: なし。
    返り値: list[tuple[str,str,str]] は名称・比較元・比較先。
    """
    return [('SC対S','R0G1','R1G1')]


def verify_grids(rows: list[dict], result: dict, diagnostics: dict, sessions: list[str]) -> tuple[dict,dict,dict]:
    """
    機能: 共有C0全判断と全Source poolの当時性を確認し、C0可用性を再集計する。
    引数: rows (list[dict])、result/diagnostics (dict)、sessions (list[str]) は保存資料。
    返り値: tuple[dict,dict,dict] はC0可用性・純判断件数・全pool数。Source資格とC0を混同しない。
    """
    need(len(rows)==66 and {row['session'] for row in rows}==set(sessions),'共有判断66場差')
    available={'C0':{'全定時':0,'時計許可':0,'方向判定成立':0,'候補生成':0,'判定項目':{},'支持未知理由':Counter()}}
    stats=Counter();pool_counts=Counter()
    for row in rows:
        session=row['session'];need([g['at'] for g in row['grid_decisions']]==SAVED.BASE.scheduled(session),'共有2442定時順序')
        need(set(row)=={'session','grid_decisions','source_events','source_equivalence'},'共有gz4field差')
        for grid in row['grid_decisions']:
            need(set(grid)==SAVED.GRID_FIELDS and grid['c0']['policy']=='C0','Source共有grid集合又はC0差')
            c0=grid['c0'];base=c0['base'];need(base['at']==grid['at'],'C0と定時の時計差')
            need(grid['structure_anchor']==SAVED.BASE.expected_anchor(grid['at'],base['technical']),'当時EMA出典差')
            pool=SAVED.sorted_pool(grid['source'],grid['at']);pool_counts['全pool候補']+=len(pool);pool_counts['時計許可pool候補']+=len(pool)*grid['clock_allowed']
            item=available['C0']
            for name,value in (('全定時',1),('時計許可',grid['clock_allowed']),('方向判定成立',c0['allowed']),('候補生成',grid['clock_allowed'] and c0['allowed'])):item[name]+=value
            for name,value in (('許可',c0['allowed']),('必須未知',c0['required_unknown']),('既知不許可',not c0['allowed'] and not c0['required_unknown']),('許可初動',c0['allowed'] and c0['role']=='転換初動')):stats[name]+=value
            for old,current in zip(base['directions'],c0['directions'],strict=True):
                need(current['base']==old,'C0方向Baseの同一性差')
                if current['allowed']:item.setdefault('方向許可の役割',Counter())[current['role']]+=1
                for check in old['checks']+current['added']:
                    name=check['group']+':'+check['id'];total=item['判定項目'].setdefault(name,dict.fromkeys(('方向数','既知','成立','未知'),0))
                    need(type(check['known']) is bool and type(check['passed']) is bool and (check['known'] or not check['passed']),'C0保存check既知型差')
                    for field,value in (('方向数',1),('既知',check['known']),('成立',check['passed']),('未知',not check['known'])):total[field]+=value
            for side in ('buy','sell'):
                for field in ('own_reason','peer_reason','ofi_reason'):
                    reason=base['evidence'][side][field]
                    if reason:item['支持未知理由'][field+':'+reason]+=1
    need(available==result['定時の候補と入力可用性'],'C0可用性集計差')
    return available,dict(stats),dict(pool_counts)


def verify_hold_diagnostics(diagnostics: dict, rows: dict, grids: list[dict], sessions: list[str]) -> None:
    """
    機能: 完結玉のSource出典/変量費用/全旧保護offを保存規範へ結ぶ。
    引数: diagnostics/rows (dict)、grids (list[dict])、sessions (list[str]) は検査済正本。
    返り値: None。取消済未取得注文と全Source決定は別gzのcanonical監査へ分担する。
    """
    shared={row['session']:row['grid_decisions'] for row in grids};schema=SAVED.BASE.schemas()
    for session in sessions:
        by_time={g['at']:g for g in shared[session]}
        for key in KEYS:
            chosen=[row for identity,row in diagnostics[key].items() if identity[0]==session]
            policy='S' if key.startswith('R0') else 'SC';bindings={}
            for row in chosen:
                order=row['entry_order'];grid=by_time[order['request_time']];pool=SAVED.sorted_pool(grid['source'],grid['at'])
                matches=[(i,r) for i,r in enumerate(pool,1) if r['reference']['id']==order['reference_id']]
                need(len(matches)==1,'実取得の共有Source候補が一意でない')
                rank,source=matches[0];bindings[order['reference_id']]=SAVED.binding_value(policy,grid,source,rank,min(100,source['reference']['quantity']))
            book=dict.fromkeys(schema['BookResult']);book.update(hold_enabled=False,confirm_enabled=False,source_policy=policy,source_effects=[],lots=[r['lot'] for r in chosen],orders=[o for r in chosen for o in r['orders']],closed=[c for r in chosen for c in r['closed']],positions=[],pending_entries=[],decisions=[],metrics=rows[session,key]['metrics'])
            audit=SAVED.BASE.Audit();SAVED.validate_book_schema(book,audit,session+key);SAVED.bind_entries(book,bindings,shared[session],audit,session+key)
            need(audit.bad==0,'Source実玉出典・変量費用差:'+json.dumps(audit.examples[:3],ensure_ascii=False))


def verify_entry_audit(paths: dict, values: dict, result: dict, rows: dict, stats: dict, holds: dict, grids: list[dict], trade_rows: list[dict], sessions: list[str], source_rows: list[dict]) -> dict:
    """
    機能: 旧86基準C0/全pool保存監査を共有2gz・玉gzと全264判断へ直接結ぶ。
    引数: paths/values/result/rows/stats/holds (dict)、grids/trade_rows/source_rows/sessions (list) は明示13入力。
    返り値: dict はSource適用/採用の全件観測。旧132金融会計の同値とはしない。
    """
    entry=values['entry_audit'];need(entry['試行']==87 and entry['成功'] is True and entry['処理完了'] is True and entry['入力不変'] is True,'保存監査未完')
    need((entry['場数'],entry['基準C0枠'],entry['保存会計'])==(66,2442,264) and entry['不一致数']==0 and not entry['不一致'] and count(entry['照合項目数'])>0,'保存監査全対象差')
    need(set(entry['入力SHA256前'])=={'87','86'} and entry['入力SHA256前']==entry['入力SHA256後'] and entry['入力SHA256前']['87']==result['再生結果SHA256'],'保存監査入力指紋差')
    old_result=ROOT/'study/00086_保持帯喪失と短秒反対の複合退出/成果物/結果.json'
    need(entry['入力SHA256前']['86']==read_json(old_result)['再生結果SHA256'],'旧86基準入力差')
    small=[paths['manifest'],old_result,SAVED.OLD_PATH,SAVED.OLD.BASE_PATH,SAVED.OLD.OLD.BASE_PATH,ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',paths['condition'],ROOT/'study/00086_保持帯喪失と短秒反対の複合退出/条件.json']
    need(entry['固定小型入力SHA256']=={Path(os.path.relpath(p,ROOT)).as_posix():sha(p) for p in small} and entry['照合コードSHA256']==SAVED_SHA and entry['読取helperSHA256']==SAVED.OLD_SHA,'保存監査停止依存差')
    scenes={row['場']:row for row in entry['対象場']};gmap={row['session']:row for row in grids};smap={row['session']:row for row in source_rows}
    need(len(scenes)==len(entry['対象場'])==len(smap)==len(source_rows)==66 and set(scenes)==set(smap)==set(sessions),'Source/保存gzの66場差')
    observed={key:{'全定時':0,'占有定時':0,'pool候補数':0,'適格候補数':0,'既取得候補数':0,'選定候補数':0,'候補未知数':0,'候補理由':Counter()} for key in KEYS}
    effects={key:[] for key in KEYS};equivalence=Counter()
    for session in sessions:
        scene=scenes[session];shared=gmap[session];source=smap[session]
        need(scene['基準C0枠']==len(shared['grid_decisions']) and scene['保存会計']==4,'場別基準C0/会計差')
        need(scene['共有判断SHA256']==SAVED.canonical_sha({k:shared[k] for k in ('grid_decisions','source_events','source_equivalence')}),'共有C0/Source/events/二指紋canonical差')
        need(scene['参照判断と通知効果SHA256']==SAVED.canonical_sha(source),'Source全判断/効果canonical差')
        need(set(source)=={'session','books'} and set(source['books'])==set(KEYS),'Source gz集合差')
        eq=shared['source_equivalence']
        need(set(eq)==SAVED.EQUIVALENCE_FIELDS and eq['mismatches']==0 and eq['grid_frames']==len(shared['grid_decisions']) and eq['current_sha256']==eq['legacy_sha256'] and re.fullmatch('[0-9a-f]{64}',eq['current_sha256']) is not None,'Source逐次二hash又は比較件数不整合')
        need(scene['Source互換']==eq,'Source互換二hash差');equivalence.update({k:shared['source_equivalence'][k] for k in ('step_frames','force_frames','grid_frames','mismatches')})
        for key in KEYS:
            chosen=[r for r in trade_rows if r['session']==session and r['key']==key];need(scene['玉診断SHA256'][key]==SAVED.canonical_sha(chosen),'玉診断canonical差')
            book=source['books'][key];need(set(book)=={'source_policy','decisions','source_effects'} and book['source_policy']==('S' if key.startswith('R0') else 'SC'),'Source gz政策差')
            financial=dict(Counter(d['action'] for d in book['decisions']));need(financial==rows[session,key]['判断']==rows[session,key]['方針判断'],'全Source判断の保存会計対応差')
            need([d['at'] for d in book['decisions']]==[g['at'] for g in shared['grid_decisions']],'全Source判断の2442枠順序差')
            effect=book['source_effects'];effects[key]+=effect
            item=observed[key];item['全定時']+=len(book['decisions']);item['占有定時']+=sum(d['source_context']['occupied'] for d in book['decisions'])
            for decision in book['decisions']:
                for candidate in decision['candidates']:
                    check=candidate['source_check'];item['pool候補数']+=1
                    for dest,field in (('適格候補数','eligible'),('既取得候補数','seen'),('選定候補数','selected'),('候補未知数','required_unknown')):item[dest]+=check[field]
                    item['候補理由'][check['reason']]+=1
            expected_effect={'通知':len(effect),'0作用':sum(e['cancelled']==e['exit_requested']==0 for e in effect),'取消枚':sum(e['cancelled'] for e in effect),'返済要求枚':sum(e['exit_requested'] for e in effect),'timer通知':sum(e['origin']=='timer' for e in effect)}
            need(scene['Source通知適用'][key]==expected_effect,'Source通知保存効果合計差')
    need(dict(equivalence)==entry['Source互換件数'] and equivalence['grid_frames']==2442 and equivalence['mismatches']==0,'Source全互換件数差')
    need(observed==result['参照poolと実採用'],'参照poolと採用集計差')
    for key in KEYS:
        summary=result['比較'][key];local=effects[key]
        need(summary['Source通知数']==len(local) and summary['Source要求枚数']==sum(e['exit_requested'] for e in local) and summary['Source取消枚数']==sum(e['cancelled'] for e in local),'Source通知/要求/取消集計差')
    return {'source_rows':smap,'shared':gmap,'effects':effects,'availability':observed,'equivalence':dict(equivalence)}


def verify_source_audit(paths: dict, values: dict, result: dict, source: dict, sessions: list[str]) -> None:
    """
    機能: Source通知の独立一走査を全共有通知/各会計効果/入力SHAへ結ぶ。
    引数: paths/values/result/source (dict)、sessions (list[str]) は13明示正本。
    返り値: None。G1一走査と通知一走査を混ぜて一回と表示しない。
    """
    proof=values['source_audit'];need(proof['試行']==87 and proof['成功'] is True and proof['処理完了'] is True and proof['入力前後不変'] is True,'Source通知原板未完')
    need(proof['場数']==66 and proof['会計数']==264 and proof['不一致数']==0 and not proof['不一致'] and count(proof['照合項目数'])>0,'Source通知原板の全対象差')
    need(proof['入力台帳SHA256']==proof['入力台帳SHA256前']==proof['入力台帳SHA256後']==sha(paths['manifest']),'Source通知原板台帳差')
    need(proof['監査コードSHA256']==sha(Path(__file__).with_name('Source通知監査.py'))=='d9e1a91c7f9fcdfb3a255348bb96e8cd190195a2f494e2195f6db62efabb76cb' and proof['固定80監査SHA256']==sha(ROOT/'scripts/FAR後期15分移植/原板照合.py') and proof['原板本文走査回数毎場']==1,'Source通知停止code又は1走査差')
    records={row['session']:row for row in proof['対象場']};need(len(records)==len(proof['対象場'])==66 and set(records)==set(sessions),'Source通知66場差')
    summary=Counter();events=notifications=effects=0
    manifest={r['id']:r for r in values['manifest']['sessions']}
    for session in sessions:
        row=records[session];shared=source['shared'][session];books=source['source_rows'][session]['books']
        need(row['入力前後不変'] is True and row['会計数']==4 and row['不一致数']==0 and not row['不一致'],'Source通知場別未完')
        need(row['再生結果SHA256']==row['再生結果SHA256前']==row['再生結果SHA256後']==result['再生結果SHA256'][session+'.json'],'Source通知の保存本文SHA差')
        need(row['原板SHA256前']==row['原板SHA256後']==manifest[session]['files']['NK225_book']['sha256'],'Source通知の原板前後SHA差')
        need(row['source_equivalence']==shared['source_equivalence'],'Source通知の元driver二指紋差')
        n_events=len(shared['source_events']);n_notifications=sum(len(event['closes']) for event in shared['source_events']);n_effects=sum(len(book['source_effects']) for book in books.values())
        need((row['Sourceイベント数'],row['Source通知数'],row['Source効果数'])==(n_events,n_notifications,n_effects),'Source共有通知と原板証拠件数差')
        by_key={account['会計']:account for account in row['各会計通知要約']};need(len(by_key)==len(row['各会計通知要約'])==4 and set(by_key)==set(KEYS),'Source通知原板4会計差')
        for key,account in by_key.items():
            local=books[key]['source_effects']
            need(account['通知']==len(local) and account['取消枚数']==sum(e['cancelled'] for e in local) and account['返済要求枚数']==sum(e['exit_requested'] for e in local) and account['0作用通知']==sum(e['cancelled']==e['exit_requested']==0 for e in local) and account['未解消会計']==0,'Source原板と保存比例作用差')
            summary.update({k:v for k,v in account.items() if k!='会計'})
        events+=n_events;notifications+=n_notifications;effects+=n_effects
    need((proof['Sourceイベント数'],proof['Source通知数'],proof['Source効果数'])==(events,notifications,effects) and proof['要約']==dict(summary),'Source通知原板全場集計差')


def verify_source_totals(diagnostics: dict, result: dict) -> tuple[dict,dict]:
    """
    機能: 元手法/段階/親量/実量別の損益とD02取得時点差を保存玉から再計算する。
    引数: diagnostics/result (dict) は玉と正式集計。
    返り値: tuple[dict,dict] は数量別内訳と全玉D02。生存を現在優位性と読み替えない。
    """
    all_groups={};observations={}
    for key,items in diagnostics.items():
        groups={};observed=[]
        for identity,row in items.items():
            lot=row['lot'];binding=lot['source_entry'];read=binding['read_lot'];reference=read['reference'];order=row['entry_order']
            elapsed=number(order['request_time'])-number(reference['at']);premium=lot['side']*(number(lot['entry_price'])-number(reference['entry']))
            need(elapsed>=0,'元参照の未来出生から実参加')
            observed.append({'session':identity[0],'reference_id':lot['reference_id'],'request_time':order['request_time'],'参照経過秒':elapsed,'方向付き実取得差pt':premium,'実初期量':lot['initial_quantity'],'元Kind':binding['reference_kind'],'親small_initial':read['native_small_initial_eligible']})
            for group,label in (('元手法',reference['method']),('元段階',binding['reference_kind']),('実初期量',str(lot['initial_quantity'])),('元親初回量',str(read['native_parent_initial_micro'])),('元small_initial',str(read['native_small_initial_eligible']))):
                groups.setdefault(group+':'+label,[]).append(lot)
        totals={name:{'完結玉':len(lots),'新規枚数':sum(p['initial_quantity'] for p in lots),'費用後円':sum(number(p['net_pnl']) for p in lots),'往復費用円':sum(122*p['initial_quantity'] for p in lots),'正益玉':sum(p['flag'] for p in lots),'正益後赤字玉':sum(p['flag'] and number(p['net_pnl'])<0 for p in lots)} for name,lots in groups.items()}
        need(totals==result['比較'][key]['数量別内訳'] and sum(row['lot']['initial_quantity'] for row in items.values())==result['比較'][key]['新規枚数'],'可変量・元段階別集計差')
        all_groups[key]=totals;observations[key]=observed
    return all_groups,observations


def prepare(paths: dict, study: Path) -> dict:
    """
    機能: 明示13正本を金融・Source・2種原板・Viewer・canonicalへ全件結合する。
    引数: paths (dict[str,Path])、study (Path) は明示入力と出力先。
    返り値: dict は検査済帳票入力。市場原板・新売買・APIは使わない。
    """
    required=('result','catalog','cash_audit','raw_audit','viewer_audit','condition','input_reference','manifest','trades','grids','entry_audit','source_audit','source_decisions')
    need(set(paths)==set(required),'13明示入力の不足/余剰')
    hashes={str(path.resolve()):sha(path) for path in paths.values()};values={name:read_json(paths[name]) for name in required if name not in ('trades','grids','source_decisions')}
    sessions=[row['id'] for row in values['manifest']['sessions']];need(len(sessions)==len(set(sessions))==66,'一意66場が必要')
    dependencies=fixed_dependencies(values['condition'],values['input_reference'],paths['manifest']);result=values['result'];need(result['入力台帳SHA256']==sha(paths['manifest']),'結果台帳SHA差')
    rows=verify_summary(result,sessions);trade_rows=compressed_rows(paths['trades']);diagnostics=verify_diagnostics(trade_rows,result,sessions);grids=compressed_rows(paths['grids']);source_rows=compressed_rows(paths['source_decisions'])
    availability,stats,holds=verify_grids(grids,result,diagnostics,sessions);verify_hold_diagnostics(diagnostics,rows,grids,sessions)
    normative=verify_audits(paths,values,result,rows,diagnostics,sessions)
    source=verify_entry_audit(paths,values,result,rows,stats,holds,grids,trade_rows,sessions,source_rows)
    verify_source_audit(paths,values,result,source,sessions);verify_exports(paths,values['catalog'],diagnostics,sessions)
    quantities,observations=verify_source_totals(diagnostics,result)
    settings=(study/'設定と結果.md').read_text(encoding='utf-8');need(settings.count(BEGIN)==settings.count(END)==1 and STATUS in settings,'設定マーカー差');verify_table(settings,study)
    need({str(path.resolve()):sha(path) for path in paths.values()}==hashes,'13入力読取中の変更')
    return {'result':result,'paths':paths,'input_sha':hashes,'dependencies':dependencies,'settings':settings,'availability':availability,'stats':stats,'holds':holds,'normative':normative,'source':source,'quantities':quantities,'observations':observations,'entry':values['entry_audit'],'raw':values['raw_audit'],'source_audit':values['source_audit'],'exit_categories':exit_categories(diagnostics,result)}


def exit_categories(diagnostics: dict, result: dict) -> dict:
    """
    機能: 同実入口のR0/R1を救った損失・失った勝ち・損益幅の変化へ分解する。
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
            if left[identity]['entry_order']['request_time']!=right[identity]['entry_order']['request_time'] or not all(a[name]==b[name] for name in ('side','entry_time','entry_price','initial_quantity')):continue
            x,y=number(a['net_pnl']),number(b['net_pnl'])
            label='赤字→非赤字' if x<0<=y else '黒字→非黒字' if x>0>=y else '両赤字の損失縮小' if x<y<0 else '両赤字の損失拡大' if y<x<0 else '両黒字の増益' if 0<x<y else '両黒字の減益' if 0<y<x else '同額・その他'
            row=categories[label];row['件数']+=1;row['A円']+=x;row['B円']+=y;row['差円']+=y-x
        summary=result['出口間の同実新規分解'][f'SC対S_D{delay}']
        need(sum(row['件数'] for row in categories.values())==summary['同実新規'] and sum(row['A円'] for row in categories.values())==number(summary['同実新規A損益円']) and sum(row['B円'] for row in categories.values())==number(summary['同実新規B損益円']),'同入口の救済・早切り分解差')
        grouped[f'D{delay}']=categories
    return grouped


def result_block(data: dict) -> str:
    """
    機能: S/SCの費用後額・実枚数・利益旗の分母を同じ比較表へ示す。
    引数: data (dict) は13正本の照合済入力。
    返り値: str は設定専用マーカー内のMarkdown。
    """
    text=['正式66場、Source可変量＋G1を共通にし、SCだけ現在C0を追加。全場既使用。','',
        '| ID | 費用後損益円 | 最大DD円 | 赤字場 | 完結玉/実新規枚 | 全玉正益後赤字 |','| --- | ---: | ---: | ---: | --- | ---: |']
    for key in KEYS:
        row=data['result']['比較'][key]
        text.append(f"| {key} | {amount(row['費用後損益円'])} | {amount(row['最大DD円'])} | {row['赤字場数']}/66 | {row['完結玉']}/{row['新規枚数']} | {ratio(row['全玉旗後赤字'],row['全玉旗'])} |")
    if not sum(row['完結玉'] for row in data['result']['比較'].values()):text+=['','実新規0。Source/C0の収益効果は未評価。']
    text+=['','参照玉の生存は現在取得の優位性を意味しない。費用前Source利益と実建値/費用後利益を分け、86との差を数量単独効果としない。']
    return '\n'.join(text)


def render_readme(data: dict, study: Path) -> str:
    """
    機能: 元参照生存と現在取得の差を、Source/C0/数量/利益保護/二原板監査と説明する。
    引数: data (dict) は13正本、study (Path) はリンク基準。
    返り値: str は正式README全文。元Kindと実初参加を混同しない。
    """
    result,paths=data['result'],data['paths'];main=[result['比較'][key] for key in KEYS if key.endswith('_D0')]
    outcome='実新規0で市場効果は未評価。' if not sum(row['完結玉'] for row in main) else '主費用で黒字の案はなかった。' if not any(row['費用後損益円']>0 for row in main) else '既使用期間に費用後黒字を観測した案があるが、安定利益は未確認。'
    text=['# 00087：FAR参照玉と可変数量の比較','','2026-11-08。'+outcome,'',
        '元D164_15/P164_06/U165_03の選定Portfolioを全有効原行で運転し、15分時点に生存する参照玉の現在量を実側へ写すSと、同じ参照候補に現在C0最終許可を加えるSCを比較した。元Sourceの複数量/段階を戻す比較であり、100枚固定C0の86との差を数量又は一指標だけの効果とはしない。',
        '[検証計画](検証計画.md)・[事前IDと版5の55×9表](設定と結果.md)・[固定86](../00086_保持帯喪失と短秒反対の複合退出/README.md)を参照する。旧70%・125/250先着・待ち50%の合格条件は外している。','',
        '## 仮説・時計・数量','','| 外ラベル | 政策 | 15分実新規の資格 |','| --- | --- | --- |',
        '| R0G1 | S | 生存・未参加・返済予約なしの参照玉をAt/ID安定順で先頭から取得 |',
        '| R1G1 | SC | Sと同じ候補へC0最終AllowedかつSide一致を追加 |','',
        'SCは方向行単独のpassedで最終競合待機を迂回しない。SはC0を診断保存しても資格にせず、freshHoldやC0未知を隠れたgateにしない。両案とも元Source内部の複数手法/支持/量条件を保ち、Source量へJ02係数をもう一度掛けない。',
        '新規は初回を除くDay09:15..15:15/Night17:30..翌05:30の15分枠。NY09:30前後15分は静観/前窓返済、場末15:35/05:50に要求する。timerを次原行より先に処理し、ちょうど定時の原行を先取りしない。元U165はUSOpen+900に初めて生成する。Source内の30秒解除で定時外実新規を生まない。',
        '一枠一参照ID、同時一建玉、保有中実追加なし。実要求量=min(当時の現在参照量,実空き量)、上限100micro。seenは要求受理時だけ増やし、取消/全返済後も同じIDへ再参加しない。元段階source_addでもflat時の実初参加は可能で、元親の初回又は保有中追撃と呼び替えない。',
        '1枚10円/pt、片道手数料11円＋想定滑り5pt、往復122円/枚。費用は各実約定量で計算する。D0は次正常原行、D1は追加価格時計1秒の次適格原行で、実通信の1秒後保証ではない。内部mode/注文/玉/TradeIDはS0G1、Viewer手法名だけR0G1/R1G1へ写す。','',
        '## 共通のSource返済とG1','',
        '実fill→現在Source返済通知→旧テクニカル/G1の順で連続保護する。未約定新規は通知比率で取消し、実未予約量にはQuantity/Beforeを掛けて整数切捨て。0丸め/実所有なしも記録し、末尾全通知は残全量を要求する。timerはLastやfillを進めず、要求時計を古い気配時刻へ巻き戻さない。受理済返済を取消/延期しない。',
        '費用後現在単価益10×方向幅−122円がstrict正なら即最低建値床。予約がなく現在単価益も正の場合にG1部分利確を要求し、実約定した確定益だけを残玉予算へ入れる。Source部分予約中は床を維持して収穫を重ねず、解消後に単価益が非正なら過去の旗だけで収穫しない。',
        '利益前ATRは新規時ceil5・15..125pt（未知125）、非緩和床/125pt/確定3分失敗を維持する。構造EMA床・保持帯床・86複合確認は全off。小量では整数丸めによりG1が全量返済になる場合もあり、100枚成績の比例換算を使わない。','',
        '## 損益と利益保全','',result_block(data),'',f"SC主遅延は{result['比較']['R1G1_D0']['完結玉']}玉、全玉正益旗{result['比較']['R1G1_D0']['全玉旗']}玉。少数の取得結果や旗後赤字0件だけで安定利益・利益保護達成としない。",'',
        '| ID | 粗損益円 | 費用円 | 正益未観測円 | 正益観測円 | 残玉正益後赤字 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=result['比較'][key];text.append(f"| {key} | {amount(row['総計']['gross_pnl_yen'])} | {amount(row['総計']['total_cost_yen'])} | {amount(row['正益未観測の損益円'])} | {amount(row['正益観測の損益円'])} | {ratio(row['残玉旗後赤字'],row['残玉旗'])} |")
    text+=['','全玉旗は実確定部分を含む取引全体、残玉旗は現在単価純益。旗後赤字は分母と併記し、早切りによる分母減を利益保全達成としない。','',
        '| ID | Day円 | Night円 | 赤字日/日数 | 同約定0pt円 | 同約定10pt円 | 上位3場円 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        row=result['比較'][key];day=sum(number(s['metrics']['net_pnl_yen']) for s in result['場別'] if s['key']==key and s['session'].endswith('Day'))
        text.append(f"| {key} | {amount(day)} | {amount(number(row['費用後損益円'])-day)} | {row['赤字日数']}/{row['日数']} | {amount(row['同約定0pt損益円'])} | {amount(row['同約定10pt損益円'])} | {amount(row['上位3場利益円'])} |")
    text+=['','同約定0/10ptは価格列を変えない費用感応で、D1の別約定列と区別する。','',
        '## 同参照・同実新規と参加差','','比較A=S、B=SCのB−A。まず(session,reference_id)で同参照を取り、その中で要求時刻/方向/実取得時刻/価格/初期量も一致する群だけを同実新規とする。要求が遅れた同参照を片側参加へ分断しない。','',
        '| 比較 | 同実新規 | A円 | B円 | 出口差円 | 取得変更 | Aのみ件/円 | Bのみ件/円 |','| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    for name,row in result['出口間の同実新規分解'].items():text.append(f"| {name} | {row['同実新規']} | {amount(row['同実新規A損益円'])} | {amount(row['同実新規B損益円'])} | {amount(row['同実新規出口差円'])} | {row['共通だが取得変更']} | {row['Aのみ']} / {amount(row['Aのみ損益円'])} | {row['Bのみ']} / {amount(row['Bのみ損益円'])} |")
    text+=['','| 遅延 | 同実新規の内訳 | 件数 | A円 | B円 | 差円 |','| --- | --- | ---: | ---: | ---: | ---: |']
    for delay,categories in data['exit_categories'].items():
        for label,row in categories.items():text.append(f"| {delay} | {label} | {row['件数']} | {amount(row['A円'])} | {amount(row['B円'])} | {amount(row['差円'])} |")
    text+=['','この分解は検証済みの救済/失った勝ち/悪化を説明する診断であり、片側成績を組み替えた未実行戦略ではない。','',
        '## 元段階・可変数量・現在取得差','','| ID | 分類 | 玉数 | 実新規枚 | 費用後円 | 往復費用円 | 正益玉/旗後赤字 |','| --- | --- | ---: | ---: | ---: | ---: | --- |']
    for key in KEYS:
        for label,row in data['quantities'][key].items():text.append(f"| {key} | {label} | {row['完結玉']} | {row['新規枚数']} | {amount(row['費用後円'])} | {amount(row['往復費用円'])} | {row['正益玉']}/{row['正益後赤字玉']} |")
    text+=['','分類軸は重複しており合計して独立標本を増やさない。native親初回/参照初期量/参照現在量/実要求/実取得を別保存し、現在残量<=20からP164小量初回を捏造しない。nullは対象外と理由付き未知を区別する。','',
        '| ID | D02観測玉 | 参照経過秒 最小/平均/最大 | 方向付き実取得差pt 最小/平均/最大 |','| --- | ---: | --- | --- |']
    for key,observations in data['observations'].items():
        if not observations: text.append('| '+key+' | 0 | 未評価 | 未評価 |');continue
        age=[r['参照経過秒'] for r in observations];premium=[r['方向付き実取得差pt'] for r in observations]
        text.append('| '+key+' | '+str(len(age))+' | '+' / '.join(format(number(v),',.2f') for v in (min(age),sum(age)/len(age),max(age)))+' | '+' / '.join(format(number(v),',.2f') for v in (min(premium),sum(premium)/len(premium),max(premium)))+' |')
    text+=['','D02の正の価格差は元参照より方向に不利な取得。参照生存は現在取得の優位性ではなく、良い玉が15分前に利確され回復待ちがpoolへ残る可能性もある。これらは観測で、新しい閾値gateへ使わない。全玉の読み方は[出口差診断](出口差診断.md)・[小型JSON](出口差診断.json)に分離する。','',
        '## 全poolとSource連続通知','','| ID | 定時 | 占有 | pool候補 | 適格 | 既参加 | 選定 | 候補未知 | Source通知/取消枚/要求枚 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for key in KEYS:
        row=result['参照poolと実採用'][key];s=result['比較'][key]
        text.append('| '+key+' | '+' | '.join(str(row[n]) for n in ('全定時','占有定時','pool候補数','適格候補数','既取得候補数','選定候補数','候補未知数'))+f" | {s['Source通知数']}/{s['Source取消枚数']}/{s['Source要求枚数']} |")
    text+=['','pool候補は候補出現回数で、参照ID一意数や約定数ではない。0作用/0丸めもSource通知原板監査で確認する。現在C0の純許可と実採用は別の分母である。','',
        '| ID | 分類 | 新規要求 | 保有継続 | 処理中 | 待ち | 判定不能 |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for key in KEYS:
        for field,label in (('判断','金融'),('方針判断','方針')):text.append('| '+key+' | '+label+' | '+' | '.join(str(result['比較'][key][field].get(n,0)) for n in ('新規要求','保有継続','処理中','待ち','判定不能'))+' |')
    text+=['','## 日別損益','','| 日付 | '+' | '.join(KEYS)+' |','| --- | '+' | '.join('---:' for _ in KEYS)+' |']
    for day in sorted({day for row in result['比較'].values() for day in row['日別円']}):text.append('| '+day+' | '+' | '.join(amount(result['比較'][key]['日別円'][day]) for key in KEYS)+' |')
    refs=(('result','結果正本'),('catalog','Viewer264資源'),('cash_audit','保存会計'),('raw_audit','G1原板規範'),('source_audit','Source通知原板'),('viewer_audit','Viewer数値'),('condition','固定条件'),('input_reference','入力参照'),('manifest','固定台帳'),('trades','玉診断gz'),('grids','共有C0/Source/events/二hash gz'),('source_decisions','全Book判断/通知効果gz'),('entry_audit','基準C0/全pool保存監査'))
    e=data['source']['equivalence'];text+=['','## 独立照合・限界・再現','',
        f"基準C0は旧86の2442枠、保存監査は264会計・{data['entry']['照合項目数']:,}項目差0。Source別インスタンスの比較はStep {e['step_frames']:,}/Force {e['force_frames']}/Grid {e['grid_frames']}、各場の二hash一致・不一致0。旧86の132金融会計全文同値は主張しない。",'',
        ' · '.join(link(study,paths[name],label) for name,label in refs),'',
        '原板はG1/価格所有の一走査とSource通知の一走査、計二走査。Source通知はbadBBO/Last不良/timerも対象とし、予約・取消・0丸めを全原行順で再構成する。元Sourceの生成戦略は固定driverを信頼する範囲で、別戦略実装や独立したFAR全構造生成の証明ではない。',
        '全66場は既使用。4会計/二遅延/人工を独立標本へ水増しせず、少数黒字や無取引を安定利益としない。ラージ板のmicro代理約定で、板深さ消費・約定順番・実通信/証拠金は未実証。利益起動と次板約定・費用後黒字保証は別である。',
        '[再現補足](再現補足.md)と[実装CLI](../../scripts/FAR参照玉と可変数量の比較/README.md)へ停止・再現・診断の範囲を残す。帳票自体の市場原板読取/新売買/API利用は0。','']
    command=['& "work/venvs/technical-tree/Scripts/python.exe" -B -X utf8 "scripts/FAR参照玉と可変数量の比較/レポート.py" --check `','  --study "'+Path(os.path.relpath(study,ROOT)).as_posix()+'" `']
    for index,(name,_) in enumerate(refs):command.append('  --'+name.replace('_','-')+' "'+Path(os.path.relpath(paths[name],ROOT)).as_posix()+'"'+(' `' if index<len(refs)-1 else ''))
    text+=['13入力を明示する。正式生成は--checkを--runへ置換する。','','```powershell',*command,'```','','[生成証拠](レポート生成証拠.json)へ13入力・依存・R・出力のSHAを保存する。','']
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
    proof={'試行':87,'成功':True,'場数':66,'会計数':264,'Viewer資源数':264,'明示入力数':13,
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
    機能: 停止86の零取引人工を13入力・Source空poolの正式schemaへ写す。
    引数: base (Path) は新規work人工領域。
    返り値: tuple[Path,dict] は人工試行と13正本。市場/Go/APIは実行しない。
    """
    old_path=ROOT/'scripts/保持帯喪失と短秒反対の複合退出/レポート.py'
    need(sha(old_path)=='aab96b40e7b0eef873bbf59f3a597a76ac6607ee60dd3a83670b4f758f2a095c','停止86R指紋差')
    spec=importlib.util.spec_from_file_location('fixed86_fake_for87',old_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.MODES=MODES;module.KEYS=KEYS;module.comparison_pairs=comparison_pairs
    study,paths=module.fake_inputs(base)
    paths['source_decisions']=study/'成果物/参照判断と通知効果.jsonl.gz';paths['source_audit']=study/'Source通知監査.json'
    def save(name: str,value: dict) -> None:
        """
        機能: 人工JSONを同じ専用領域へ保存する。
        引数: name (str)、value (dict) は人工名と本文。
        返り値: None。
        """
        paths[name].write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def gzip_rows(path: Path,rows: list[dict]) -> None:
        """
        機能: 小型人工のJSON行を圧縮保存する。
        引数: path (Path)、rows (list[dict]) は人工先と行。
        返り値: None。
        """
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    manifest=read_json(paths['manifest']);sessions=[r['id'] for r in manifest['sessions']]
    for row in manifest['sessions']:row['files']={'NK225_book':{'sha256':hashlib.sha256(row['id'].encode()).hexdigest()}}
    save('manifest',manifest)
    actual=ROOT/'study/00087_FAR参照玉と可変数量の比較'
    condition=read_json(actual/'条件.json');reference=read_json(actual/'入力参照.json')
    for v in (condition,reference):v['入力台帳SHA256']=sha(paths['manifest'])
    reference['入力台帳']=str(paths['manifest']);save('condition',condition);save('input_reference',reference)
    result=read_json(paths['result']);result.update(試行=87,入力台帳SHA256=sha(paths['manifest']),保持帯床有効=False,複合確認有効=dict.fromkeys(MODES,False),Source入口={'R0G1':'S','R1G1':'SC'},参照poolと実採用={})
    for row in result['場別']:row.update(判断={'待ち':25 if row['session'].endswith('Day') else 49},方針判断={'待ち':25 if row['session'].endswith('Day') else 49})
    for key,row in result['比較'].items():
        row.update(判断={'待ち':2442},方針判断={'待ち':2442},新規枚数=0,数量別内訳={},Source通知数=0,Source要求枚数=0,Source取消枚数=0)
        result['参照poolと実採用'][key]={'全定時':2442,'占有定時':0,'pool候補数':0,'適格候補数':0,'既取得候補数':0,'選定候補数':0,'候補未知数':0,'候補理由':{}}
    save('result',result)
    old_grids=compressed_rows(paths['grids']);grids=[];sources=[];hashes={}
    for row in old_grids:
        session=row['session'];values=[];books={}
        for g in row['grid_decisions']:
            c0=SAVED.expected_c0(g);at=g['at']
            values.append({'at':at,'window':'D164_15' if session.endswith('Day') else 'P164_06','clock_allowed':g['clock_allowed'],'block_reason':'','c0':c0,'source':{'method':'','at':0,'source_index':-1,'started':False,'lots':[],'closes':[]},'source_line':0,'structure_anchor':g['structure_anchor']})
        eq={'step_frames':0,'force_frames':0,'grid_frames':len(values),'current_sha256':'1'*64,'legacy_sha256':'1'*64,'mismatches':0}
        for key in KEYS:
            policy='S' if key.startswith('R0') else 'SC'
            ds=[{'at':g['at'],'quote_time':0,'quote_index':-1,'action':'待ち','reason':'有効な参照玉なし','candidates':[],'source_context':{'policy':policy,'method':'','snapshot_at':0,'snapshot_index':-1,'started':False,'occupied':False,'seen_before_count':0,'seen_after_count':0,'selected_id':'','required_unknown':False,'c0_used':policy=='SC'}} for g in values]
            books[key]={'source_policy':policy,'decisions':ds,'source_effects':[]}
        shared={'session':session,'grid_decisions':values,'source_events':[],'source_equivalence':eq};src={'session':session,'books':books}
        grids.append(shared);sources.append(src);hashes[session]=(SAVED.canonical_sha({k:shared[k] for k in ('grid_decisions','source_events','source_equivalence')}),SAVED.canonical_sha(src),eq)
    gzip_rows(paths['grids'],grids);gzip_rows(paths['source_decisions'],sources)
    catalog=read_json(paths['catalog'])
    for r in catalog['resources']:r['id']=r['id'].replace('86_','87_',1)
    save('catalog',catalog)
    raw=read_json(paths['raw_audit']);raw.update(試行=87,入力台帳SHA256=sha(paths['manifest']),監査コードSHA256=sha(Path(__file__).with_name('原板監査.py')),原板本文走査回数毎場=1)
    for row in raw['対象場']:row['診断']['JSON本文走査回数']=1
    save('raw_audit',raw)
    viewer=read_json(paths['viewer_audit']);viewer.update(試行=87,結果SHA256=sha(paths['result']),一覧SHA256=sha(paths['catalog']),監査コードSHA256=sha(Path(__file__).with_name('表示監査.py')))
    for r in viewer['資源']:r['id']=r['id'].replace('86_','87_',1)
    files=[paths['result'],paths['catalog']]+[paths['catalog'].parent/r['pnl_path'] for r in catalog['resources']];pins={str(p.resolve()):sha(p) for p in files};viewer.update(入力SHA256前=pins,入力SHA256後=pins);save('viewer_audit',viewer)
    scenes=[];actions=[]
    for shared,source in zip(grids,sources,strict=True):
        session=shared['session'];local=[{'session':session,'key':key,'金融判断':{'待ち':len(shared['grid_decisions'])},'方針判断':{'待ち':len(shared['grid_decisions'])}} for key in KEYS];actions+=local
        h,s,eq=hashes[session]
        scenes.append({'場':session,'予定枠':len(shared['grid_decisions']),'基準C0枠':len(shared['grid_decisions']),'保存会計':4,'Source互換':eq,'Source通知適用':{key:{'通知':0,'0作用':0,'取消枚':0,'返済要求枚':0,'timer通知':0} for key in KEYS},'方針判断':local,'共有判断SHA256':h,'参照判断と通知効果SHA256':s,'玉診断SHA256':dict.fromkeys(KEYS,SAVED.canonical_sha([]))})
    old_result=ROOT/'study/00086_保持帯喪失と短秒反対の複合退出/成果物/結果.json';inventory={'87':result['再生結果SHA256'],'86':read_json(old_result)['再生結果SHA256']}
    small=[paths['manifest'],old_result,SAVED.OLD_PATH,SAVED.OLD.BASE_PATH,SAVED.OLD.OLD.BASE_PATH,ROOT/'scripts/定時の現在根拠と部分利益保護/actual.go',paths['condition'],ROOT/'study/00086_保持帯喪失と短秒反対の複合退出/条件.json']
    entry={'試行':87,'成功':True,'処理完了':True,'場数':66,'基準C0枠':2442,'予定枠':2442,'保存会計':264,'入力不変':True,'入力SHA256前':inventory,'入力SHA256後':inventory,'照合項目数':1757783,'不一致数':0,'不一致':[],'照合コードSHA256':SAVED_SHA,'読取helperSHA256':SAVED.OLD_SHA,'固定小型入力SHA256':{Path(os.path.relpath(p,ROOT)).as_posix():sha(p) for p in small},'Source互換件数':{'step_frames':0,'force_frames':0,'grid_frames':2442,'mismatches':0},'対象場':scenes,'方針判断':actions};save('entry_audit',entry)
    accounts=[{'会計':key,'通知':0,'timer通知':0,'取消枚数':0,'返済要求枚数':0,'0作用通知':0,'0丸め通知':0,'未解消会計':0} for key in KEYS]
    summary={k:0 for k in accounts[0] if k!='会計'}
    source_proof={'試行':87,'成功':True,'処理完了':True,'場数':66,'会計数':264,'Sourceイベント数':0,'Source通知数':0,'Source効果数':0,'照合項目数':1,'不一致数':0,'不一致':[],'入力前後不変':True,'入力台帳SHA256':sha(paths['manifest']),'入力台帳SHA256前':sha(paths['manifest']),'入力台帳SHA256後':sha(paths['manifest']),'監査コードSHA256':sha(Path(__file__).with_name('Source通知監査.py')),'固定80監査SHA256':sha(ROOT/'scripts/FAR後期15分移植/原板照合.py'),'原板本文走査回数毎場':1,'要約':summary,'対象場':[]}
    for row in manifest['sessions']:
        session=row['id'];pin=result['再生結果SHA256'][session+'.json'];rawpin=row['files']['NK225_book']['sha256']
        source_proof['対象場'].append({'session':session,'再生結果SHA256':pin,'再生結果SHA256前':pin,'再生結果SHA256後':pin,'原板SHA256前':rawpin,'原板SHA256後':rawpin,'入力前後不変':True,'会計数':4,'Sourceイベント数':0,'Source通知数':0,'Source効果数':0,'不一致数':0,'不一致':[],'各会計通知要約':deepcopy(accounts),'source_equivalence':hashes[session][2]})
    save('source_audit',source_proof)
    original=actual/'設定と結果.md';settings=original.read_text(encoding='utf-8')
    for method in read_json(ROOT/'scripts/レポート/手法カタログ_版5.json')['methods']:
        target=ROOT/method['source'];settings=settings.replace(']('+Path(os.path.relpath(target,original.parent)).as_posix()+')',']('+Path(os.path.relpath(target,study)).as_posix()+')')
    (study/'設定と結果.md').write_text(settings,encoding='utf-8')
    return study,paths


def self_test() -> dict:
    """
    機能: 13明示入力/264会計/2442枠の生成同値とSource特有破損を市場なしで検査する。
    引数: なし。新規一時workだけを利用する。
    返り値: dict は成功証拠。原板/Source自然発生/実APIの代替とはしない。
    """
    tests=[]
    with tempfile.TemporaryDirectory(prefix='87帳票人工_',dir=ROOT/'work') as directory:
        study,paths=fake_inputs(Path(directory).resolve());before=(study/'設定と結果.md').read_text(encoding='utf-8')
        generate(paths,study,False);generate(paths,study,True)
        need('実新規0' in (study/'README.md').read_text(encoding='utf-8'),'0取引は未評価')
        tests+=['13入力264会計2442枠の生成check同値','0取引を未評価','設定マーカー外保持']
        def reject(name: str,mutate: object,label: str) -> None:
            """
            機能: 人工JSONの一変更を全結合で拒否することを確認する。
            引数: name/label (str)、mutate (callable) は入力名と変更。
            返り値: None。元bytesを各反証後に復元する。
            """
            path=paths[name];saved=path.read_bytes();v=read_json(path);mutate(v);path.write_text(json.dumps(v,ensure_ascii=False,allow_nan=False),encoding='utf-8');refused=False
            try:prepare(paths,study)
            except (ValueError,KeyError,AssertionError):refused=True
            finally:path.write_bytes(saved)
            need(refused,'拒否しなかった:'+label);tests.append(label)
        for case in (
            ('result',lambda v:v.update(試行=88),'試行差'),('result',lambda v:v['場別'].pop(),'264会計欠落'),
            ('result',lambda v:v['比較']['R0G1_D0'].update(新規枚数=100),'固定100流用'),
            ('result',lambda v:v['比較']['R1G1_D0'].update(Source要求枚数=1),'Source量差'),
            ('result',lambda v:v['参照poolと実採用']['R0G1_D0'].update(選定候補数=1),'pool採用差'),
            ('result',lambda v:v['出口間の同実新規分解']['SC対S_D0'].update(Aのみ=1),'参加差'),
            ('condition',lambda v:v.update(source_policy={'R0G1':'SC','R1G1':'SC'}),'Sへの隠れC0'),
            ('condition',lambda v:v.update(新規数量micro枚=100),'固定量条件拒否'),
            ('input_reference',lambda v:v['旧条件SHA256'].popitem(),'旧条件map欠落'),
            ('source_audit',lambda v:v.update(成功=False),'通知原板未完'),
            ('source_audit',lambda v:v.update(原板本文走査回数毎場=2),'通知走査回数'),
            ('source_audit',lambda v:v['対象場'][0].update(再生結果SHA256後='0'*64),'通知保存前後SHA'),
            ('source_audit',lambda v:v['対象場'][0]['各会計通知要約'][0].update(取消枚数=1),'通知取消枚差'),
            ('raw_audit',lambda v:v.update(成功=False),'G1原板未完'),
            ('viewer_audit',lambda v:v.update(完了資源=263),'Viewer欠落'),
            ('entry_audit',lambda v:v.update(基準C0枠=132),'132金融同値と混同'),
            ('entry_audit',lambda v:v['対象場'][0].update(共有判断SHA256='0'*64),'共有canonical'),
            ('entry_audit',lambda v:v['対象場'][0].update(参照判断と通知効果SHA256='0'*64),'Source判断効果canonical'),
            ('entry_audit',lambda v:v['対象場'][0]['玉診断SHA256'].update(R0G1_D0='0'*64),'玉canonical'),
        ):reject(*case)
        saved=paths['source_decisions'].read_bytes();rows=compressed_rows(paths['source_decisions']);rows[0]['books']['R0G1_D0']['decisions'][0]['source_context']['c0_used']=True
        with gzip.open(paths['source_decisions'],'wt',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        refused=False
        try:prepare(paths,study)
        except ValueError:refused=True
        paths['source_decisions'].write_bytes(saved);need(refused,'Source未使用項目のcanonical破損を拒否しない');tests.append('意味集計同値のSource gz破損')
        viewer_plain=read_json(paths['viewer_audit']);current=read_json(paths['result']);old=deepcopy(current)
        old['出口間の同実新規分解']['SC対S_D0']['Aのみ']=1
        oldsha=hashlib.sha256((json.dumps(old,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()).hexdigest()
        original=deepcopy(viewer_plain);original['結果SHA256']=oldsha
        for field in ('入力SHA256前','入力SHA256後'):original[field][str(paths['result'].resolve())]=oldsha
        original_sha=hashlib.sha256((json.dumps(original,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()).hexdigest()
        projection=SAVED.canonical_sha({k:v for k,v in current.items() if k!='出口間の同実新規分解'})
        inventory={p.relative_to(paths['result'].parent).as_posix():sha(p) for p in paths['result'].parent.rglob('*') if p.is_file() and p!=paths['result']}
        correction={'訂正対象':'出口間の同実新規分解','旧結果SHA256':oldsha,'新結果SHA256':sha(paths['result']),'訂正前の出口間の同実新規分解':old['出口間の同実新規分解'],'旧経済射影SHA256':projection,'新経済射影SHA256':projection,'その他成果物SHA256':inventory,'元Viewer監査SHA256':original_sha,'再集計コードSHA256':sha(Path(__file__).with_name('集計.py')),'新市場再生':0}
        corrected={**original,'対応分類訂正':correction}
        need(verify_viewer_correction(paths,corrected,current)==oldsha,'分類訂正の旧bytes正規復元');tests.append('旧API結果と旧Viewer bytesを正規復元')
        for label,mutation in (
            ('訂正の市場再生拒否',lambda v:v['対応分類訂正'].__setitem__('新市場再生',1)),
            ('訂正旧mapの破損拒否',lambda v:v['対応分類訂正']['訂正前の出口間の同実新規分解']['SC対S_D0'].__setitem__('Aのみ',2)),
            ('旧経済射影の破損拒否',lambda v:v['対応分類訂正'].__setitem__('旧経済射影SHA256','0'*64)),
            ('269成果物変更拒否',lambda v:v['対応分類訂正']['その他成果物SHA256'].__setitem__('一覧.resources.json','0'*64)),
            ('元Viewer bytes変更拒否',lambda v:v['対応分類訂正'].__setitem__('元Viewer監査SHA256','0'*64)),
            ('API旧結果を現行へ偽装拒否',lambda v:v.__setitem__('結果SHA256',sha(paths['result']))),
        ):
            value=deepcopy(corrected);mutation(value);refused=False
            try:verify_viewer_correction(paths,value,current)
            except ValueError:refused=True
            need(refused,'訂正破損を拒否しない:'+label);tests.append(label)
        generate(paths,study,True)
    return {'成功':True,'人工数':len(tests),'人工':tests,'新市場再生':0,'本物原板読取':0,'実API':0}


def main() -> None:
    """
    機能: 13明示正本の正式生成・同値確認と、市場なし人工を切り替える。
    引数: --run/--check/--self-test (bool)、--studyと11入力 (Path)。
    返り値: None。未完・不整合は非0終了する。
    """
    parser=argparse.ArgumentParser(description='87のFAR参照玉と可変数量の比較を11正本から帳票化')
    stage=parser.add_mutually_exclusive_group(required=True)
    for name in ('run','check','self-test'):stage.add_argument('--'+name,action='store_true')
    parser.add_argument('--study',type=Path);names=('result','catalog','cash-audit','raw-audit','viewer-audit','condition','input-reference','manifest','trades','grids','entry-audit','source-audit','source-decisions')
    for name in names:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.self_test:
        need(args.study is None and not any(getattr(args,name.replace('-','_')) for name in names),'人工と正式入力を混在させない')
        print(json.dumps(self_test(),ensure_ascii=False));return
    need(args.study is not None and all(getattr(args,name.replace('-','_')) is not None for name in names),'studyと13正本を全て明示する')
    paths={name.replace('-','_'):getattr(args,name.replace('-','_')).resolve() for name in names};proof=generate(paths,args.study.resolve(),args.check)
    print(json.dumps({name:proof[name] for name in ('試行','成功','場数','会計数','Viewer資源数','本処理の市場原板読取','新売買再生')},ensure_ascii=False))


if __name__=='__main__':main()
