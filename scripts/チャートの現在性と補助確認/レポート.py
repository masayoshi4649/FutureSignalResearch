"""82の小型正本を相互照合し、Markdownの設定結果と説明だけを生成する。

81の固定レポート.py（SHA256:
46fcd7638972642c82b3a869fa61f32cf11a2048d648bc7aef8f03fdec1dcc1d）から
有限値・版5表・会計・監査結合を派生し、二入口/G1固定と補助状態へ変更した。
旧コードや市場原板を変更せず、売買再生を行わない。
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
MODES = ("B0G1", "B1G1")
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in MODES)
BEGIN = "<!-- 82_RESULTS_BEGIN -->"
END = "<!-- 82_RESULTS_END -->"
STATUS = "**固定設定。実行状態と結果は末尾の専用欄に記載する。**"


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


def fixed_dependencies(condition: dict, reference: dict, manifest: Path) -> dict[str, str]:
    """
    機能: 固定条件・入力参照を同じ台帳と依存コードへ結ぶ。
    引数: condition/reference (dict) は82正本、manifest (Path) は80固定台帳。
    返り値: dict[str,str] は実際に照合した小型依存のSHA。
    """
    for value in (condition, reference):
        need(count(value["試行"]) == 82 and value["入力台帳SHA256"] == sha(manifest), "82条件と台帳の差")
        need(count(value["入力場数"]) == 66 and value["全場既使用"] is True, "66既使用場の条件が必要")
    need(reference["入力ファイル数"] == 396 and reference["固定80採用版"] == 2, "入力参照又は80版差")
    referenced_manifest = Path(reference["入力台帳"])
    if not referenced_manifest.is_absolute():
        referenced_manifest = ROOT / referenced_manifest
    need(referenced_manifest.resolve() == manifest.resolve(), "入力参照の台帳パス差")
    need(reference["固定80条件SHA256"] == sha(ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/条件.json"), "固定80条件の保存SHA差")
    need(set(condition["modes"]) == set(MODES) and set(condition["keys"]) == set(KEYS), "政策又は遅延集合差")
    need(condition["約定追加価格時計遅延秒"] == [0, 1], "遅延条件差")
    for name, expected in (("新規数量micro枚", 100), ("片側上限", 100), ("point_value", 10), ("片道手数料円", 11), ("片道滑りpt", 5), ("主往復費用円毎枚", 122), ("G1悪化余裕pt", 10), ("G1全玉予算目標円", 1)):
        need(type(condition[name]) is int and condition[name] == expected, "固定数量・費用・予算差:" + name)
    need(condition["同時一建玉"] is True and condition["新損益前固定"] is True, "所有制約又は固定状態差")
    need(condition["固定80依存"] == reference["固定80依存指紋"], "80固定依存集合差")
    need(condition["固定81依存"] == reference["固定81依存指紋"], "81固定依存集合差")
    market_root = Path(read_json(manifest)["source_root"]).resolve()
    checked = {}
    for group in (condition["コードと依存SHA256"], condition["固定80依存"], condition["固定81依存"], {condition["実行ファイル"]: condition["実行ファイルSHA256"]}):
        need(type(group) is dict and bool(group), "固定依存が空です")
        for name, wanted in group.items():
            path = Path(name)
            if not path.is_absolute():
                path = ROOT / path
            path = path.resolve()
            need(not path.is_relative_to(market_root), "帳票生成で市場原板を読みません")
            need(type(wanted) is str and sha(path) == wanted, "固定コード変更:" + name)
            checked[str(path)] = wanted
    return checked


def verify_summary(result: dict, sessions: list[str]) -> dict:
    """
    機能: 全264会計と4集計の費用・玉・数量・期間・DDを相互確認する。
    引数: result (dict) は結果正本、sessions (list[str]) は台帳順。
    返り値: dict は場と政策をキーにした保存会計。
    """
    need(count(result["試行"]) == 82 and count(result["場数"]) == 66 and result["全場既使用"] is True, "82の66場が必要")
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


def verify_diagnostics(rows: list[dict], result: dict, sessions: list[str]) -> dict:
    """
    機能: 圧縮玉診断を比較・部分利確・予算・共通入口分解へ結ぶ。
    引数: rows (list[dict]) は玉診断、result (dict) は集計、sessions (list[str]) は対象場。
    返り値: dict はKey別玉診断。
    """
    grouped = {key: {} for key in KEYS}
    for row in rows:
        need(row["session"] in sessions and row["key"] in KEYS, "診断対象集合差")
        lot = row["lot"]
        identity = (row["session"], lot["reference_id"])
        need(identity not in grouped[row["key"]], "同一参照の実新規重複")
        need(count(lot["initial_quantity"]) == count(lot["closed_quantity"]) == 100 and count(lot["quantity"]) == 0, "玉診断の数量差")
        need(all(type(lot[name]) is bool for name in ("flag", "whole_flag", "cash_floor_active", "funding_failed")), "利益旗と予算状態はboolが必要")
        need(sum(number(c["pnl5"]) for c in row["closed"]) == number(lot["net_pnl"]), "玉の費用後額差")
        need(sum(count(c["quantity"]) for c in row["closed"]) == 100, "返済片の数量差")
        target, filled = count(lot["harvest_target"]), count(lot["harvest_filled"])
        need(filled <= target <= 100, "部分利確の予約又は約定量差")
        if lot["cash_floor_active"]:
            need(target > 0 and filled == target and lot["harvest_done_at"] is not None and lot["cash_floor_at"] >= lot["harvest_done_at"], "未確定利益を予算へ使用")
        grouped[row["key"]][identity] = row
    for key, identities in grouped.items():
        lots = [row["lot"] for row in identities.values()]
        s = result["比較"][key]
        need(len(lots) == s["完結玉"] and sum(number(p["net_pnl"]) for p in lots) == number(s["費用後損益円"]), "全玉と比較額差")
        for flag, label, loss in (("flag", "残玉旗", "残玉旗後赤字"), ("whole_flag", "全玉旗", "全玉旗後赤字")):
            need(sum(p[flag] for p in lots) == s[label] and sum(p[flag] and number(p["net_pnl"]) < 0 for p in lots) == s[loss], "全玉/残玉の旗数差")
        need(number(s["正益観測の損益円"]) == sum((number(p["net_pnl"]) for p in lots if p["flag"]), Decimal(0)), "正益後玉の損益差")
        need(number(s["正益未観測の損益円"]) == sum((number(p["net_pnl"]) for p in lots if not p["flag"]), Decimal(0)), "正益前玉の損益差")
        reason_qty, reason_net = Counter(), Counter()
        for row in identities.values():
            for closed in row["closed"]:
                reason_qty[closed["reason"]] += count(closed["quantity"])
                reason_net[closed["reason"]] += number(closed["pnl5"])
        need(dict(reason_qty) == s["返済理由別枚数"] and dict(reason_net) == s["返済理由別損益円"], "返済理由別の数量又は損益差")
        for field, expected in (("harvest_orders", sum(p["harvest_target"] > 0 for p in lots)), ("harvest_quantity", sum(p["harvest_target"] for p in lots)), ("harvest_filled_quantity", sum(p["harvest_filled"] for p in lots)), ("cash_floor_activated_lots", sum(p["cash_floor_active"] for p in lots)), ("funding_failure_lots", sum(p["funding_failed"] for p in lots))):
            need(s["総計"].get(field, 0) == expected, "利確/確定予算の個数差:" + key + field)
    for delay in (0, 1):
        paired = []
        for policy in ("B0", "B1"):
            matching = {}
            for (session, _), row in grouped[f"{policy}G1_D{delay}"].items():
                identity = (session, number(row["entry_order"]["request_time"]), row["lot"]["side"])
                need(identity not in matching, "同定時・同方向の実新規重複")
                matching[identity] = row
            paired.append(matching)
        left, right = paired
        common = set(left) & set(right)
        exact = {i for i in common if all(left[i]["lot"][n] == right[i]["lot"][n] for n in ("side", "entry_price", "entry_time", "initial_quantity"))}
        need(all(number(left[i]["lot"]["net_pnl"]) == number(right[i]["lot"]["net_pnl"]) for i in exact), "G1固定なのに同実入口の完結額が変化")
        saved = result["入口間の同実新規分解"][f"D{delay}"]
        need(saved["比較"] == [f"B0G1_D{delay}", f"B1G1_D{delay}"], "入口比較キー差")
        need(saved["同実新規"] == len(exact) and saved["共通だが取得変更"] == len(common - exact), "同実入口/取得変更の数差")
        for label, subset, group in (("同実新規B0損益円", exact, left), ("同実新規B1損益円", exact, right),
            ("B0のみ損益円", set(left) - set(right), left), ("B1のみ損益円", set(right) - set(left), right),
            ("取得変更B0損益円", common - exact, left), ("取得変更B1損益円", common - exact, right)):
            need(number(saved[label]) == sum((number(group[i]["lot"]["net_pnl"]) for i in subset), Decimal(0)), "入口分解額差:" + label)
        need(number(saved["同実新規出口差円"]) == number(saved["同実新規B1損益円"]) - number(saved["同実新規B0損益円"]), "同実入口差の符号差")
        need(saved["B0のみ"] == len(set(left) - set(right)) and saved["B1のみ"] == len(set(right) - set(left)), "片側参加数差")
    return grouped


def verify_grids(rows: list[dict], result: dict, diagnostics: dict, sessions: list[str]) -> dict:
    """
    機能: 定時snapshotを候補数・未知理由・実新規の発生元へ結ぶ。
    引数: rows (list[dict]) は圧縮定時、result/diagnostics (dict) は集計と玉、sessions (list[str]) は対象場。
    返り値: dict は入口別の可用性集計。
    """
    need(len(rows) == 66 and {r["session"] for r in rows} == set(sessions), "定時診断66場差")
    availability = {p: {"全定時": 0, "時計許可": 0, "方向判定成立": 0, "候補生成": 0, "判定項目": {}, "支持未知理由": Counter()} for p in ("B0", "B1")}
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
            need(not grid["candidate_accepted"] or grid["clock_allowed"] and decision["allowed"], "静観又は不成立候補を採用")
            q, tech, evidence = decision["quote"], decision["technical"], decision["evidence"]
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
        need(seen == {(at, p) for at in expected for p in ("B0", "B1")}, "全定時×二入口が不足")
    need(availability == result["定時の候補と入力可用性"], "候補/未知理由の保存集計差")
    for key, identities in diagnostics.items():
        for identity, row in identities.items():
            need(identity in supplied and supplied[identity]["entry_policy"] == key[:2], "実新規に対応する当時候補がない")
            need(number(row["entry_order"]["request_time"]) == number(supplied[identity]["at"]), "定時以外の実新規")
    return availability


def verify_auxiliary(rows: list[dict]) -> dict:
    """
    機能: 評価済み補助の状態を未知と中立を混同せず方向別に集計する。
    引数: rows (list[dict]) は圧縮した全定時snapshot。
    返り値: dict はB0/B1の状態件数。市場を再生しない。
    """
    grouped = {p: Counter() for p in ("B0", "B1")}
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
    need(count(raw["試行"]) == 82 and raw["成功"] is True and count(raw["場数"]) == 66 and count(raw["不一致数"]) == 0 and not raw["不一致"], "原板監査が未完又は不一致")
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
            for name in ("予約不足原行", "予約不足数量", "利確要求不足原行"):
                need(counts[name] == 0, "独立規範の保護又は利確要求不足")
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog", "Viewer一覧形式差")
    resources = catalog["resources"]
    resource_map = {r["id"]: r for r in resources}
    expected_ids = {f"82_{key}_{session}" for session, key in rows}
    need(len(resource_map) == len(resources) == 264 and set(resource_map) == expected_ids, "Viewer264資源の差")
    need(count(viewer["試行"]) == 82 and viewer["成功"] is True and count(viewer["予定資源"]) == count(viewer["完了資源"]) == 264 and count(viewer["不一致数"]) == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "Viewer全件成功が必要")
    need(viewer["結果SHA256"] == sha(paths["result"]) and viewer["一覧SHA256"] == sha(paths["catalog"]), "Viewerの正本SHA差")
    need(viewer["入力SHA256前"] == viewer["入力SHA256後"], "Viewer読取中の入力変更")
    current_files = {str(paths["result"].resolve()), str(paths["catalog"].resolve())}
    for resource in resources:
        session, key = next((s, k) for s, k in rows if resource["id"] == f"82_{k}_{s}")
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
        v = by_id[f"82_{key}_{session}"]
        need(v["完了"] is True and v["不一致数"] == 0 and v["APIエラー"] is None, "Viewer個別未完了")
        need(number(v["API費用後円"]) == number(v["原純額円"]) == number(rows[session, key]["metrics"]["net_pnl_yen"]), "Viewer個別純額差")
    need(raw["監査コードSHA256"] == sha(Path(__file__).with_name("原板監査.py")) and raw["固定80監査SHA256"] == sha(ROOT / "scripts/FAR後期15分移植/原板照合.py"), "原板監査コードSHA差")
    need(raw["固定81監査SHA256"] == sha(ROOT / "scripts/定時の現在根拠と部分利益保護/原板監査.py"), "固定81監査コード差")
    need(viewer["監査コードSHA256"] == sha(Path(__file__).with_name("表示監査.py")), "Viewer監査コードSHA差")
    return normative


def prepare(paths: dict, study: Path) -> dict:
    """
    機能: 全明示入力を読み、再生せず帳票生成の全前提を検査する。
    引数: paths (dict[str,Path]) は正本群、study (Path) は正式試行。
    返り値: dict は照合済み本文・診断と入力SHA。
    """
    required = ("result", "catalog", "cash_audit", "raw_audit", "viewer_audit", "condition", "input_reference", "manifest", "trades", "grids")
    need(set(paths) == set(required), "明示入力の不足")
    hashes = {str(p.resolve()): sha(p) for p in paths.values()}
    values = {name: read_json(paths[name]) for name in required if name not in ("trades", "grids")}
    manifest = values["manifest"]
    sessions = [r["id"] for r in manifest["sessions"]]
    need(len(sessions) == len(set(sessions)) == 66, "66場の一意な台帳が必要")
    dependencies = fixed_dependencies(values["condition"], values["input_reference"], paths["manifest"])
    result = values["result"]
    need(result["入力台帳SHA256"] == sha(paths["manifest"]), "結果の固定台帳差")
    rows = verify_summary(result, sessions)
    diag_rows = compressed_rows(paths["trades"])
    diagnostics = verify_diagnostics(diag_rows, result, sessions)
    grid_rows = compressed_rows(paths["grids"])
    availability = verify_grids(grid_rows, result, diagnostics, sessions)
    auxiliary = verify_auxiliary(grid_rows)
    normative = verify_audits(paths, values, result, rows, diagnostics, sessions)
    settings = (study / "設定と結果.md").read_text(encoding="utf-8")
    verify_table(settings, study)
    need(settings.count(BEGIN) == settings.count(END) == 1, "設定結果マーカー差")
    need(all(sha(Path(p)) == wanted for p, wanted in hashes.items()), "帳票読取中の正本変更")
    return {"paths": paths, "values": values, "result": result, "diagnostics": diagnostics, "availability": availability, "auxiliary": auxiliary, "normative": normative, "input_sha": hashes, "dependencies": dependencies, "settings": settings}


def result_block(data: dict) -> str:
    """
    機能: 固定設定のマーカー内へだけ入れる結果表を作る。
    引数: data (dict) は照合済み正本。
    返り値: str はMarkdownの結果表。
    """
    rows = ["正式66場・2入口×2遅延、G1出口固定。全場既使用。", "", "| ID | 遅延 | 費用後損益円 | 最大DD円 | 赤字場 | 完結玉 | 全玉正益後赤字 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        s = data["result"]["比較"][key]
        rows.append(f"| {key} | {s['追加遅延秒']} | {amount(s['費用後損益円'])} | {amount(s['最大DD円'])} | {s['赤字場数']}/66 | {s['完結玉']} | {ratio(s['全玉旗後赤字'],s['全玉旗'])} |")
    if sum(s["完結玉"] for s in data["result"]["比較"].values()) == 0:
        rows.extend(["", "実採用0であり、0損益を保護改善とはしない。G1の市場での保護効果は未評価。"])
    rows.extend(["", "[全条件・補助状態・同実入口と参加差](README.md)。原板の独立保護規範と全264資源の照合を参照する。"])
    return "\n".join(rows)


def render_readme(data: dict, study: Path) -> str:
    """
    機能: 二入口の候補・実参加・補助状態・利益保護を別にした正式説明を作る。
    引数: data (dict) は照合済み正本、study (Path) は出力先。
    返り値: str はREADME全文。
    """
    result, paths = data["result"], data["paths"]
    all_lots = sum(s["完結玉"] for s in result["比較"].values())
    main_positive = [key for key in KEYS if key.endswith("D0") and result["比較"][key]["費用後損益円"] > 0]
    outcome = "主費用で黒字の案はなかった。" if not main_positive else "既使用期の主費用で黒字の案は" + "・".join(main_positive) + "だった。未知期間の安定利益の証明ではない。"
    text = ["# 00082：チャートの現在性と補助確認", "", "2026-11-07。" + outcome + " 全66既使用場で、チャートの現在の勢い・価格回復・取得位置を主軸に二入口を比較した。出口は81G1を固定し、主と追加価格時計1秒の4会計を別にする。旧70%・125/250先着・待ち50%で棄却しない。", "", "D164_15/P164_06/U165_03は元FAR後期の特徴部品と時計窓の出典であり、元三手法の同値売買列ではない。SourcePortfolio保有を入口に写さず、元FARや80の利益を合算しない。81とも入口の式が異なり、総額差を単一指標の因果効果としない。", "", "## 仮説と固定条件", "", "[81の知見](../00081_定時の現在根拠と部分利益保護/README.md)では部分保護だけで総赤字を解消できず、正益前損失と板の必須既知性が次の問いになった。[事前候補](../../docs/議論/チャートの現在性と補助情報の使い分け.md)を新試行として固定した。", "", "新規は初回を除くDay09:15..15:15、Night17:30..翌05:30の15分枠。NY09:30の前後15分は静観し前窓で返済、場末15:35/05:50に返済要求する。保護は全原行で連続、売り買いは方向符号だけを反転して同条件。", "", "100micro固定・片側100・同時一建玉。保有、未約定新規、返済待ちは占有を保つ。推奨枚数ではなく研究尺度。1枚10円/pt、片道手数料11円＋想定滑り5pt=61円、往復122円。主は判断より後の最初の正常ラージBBO、追加価格時計1秒は別約定列。同約定0/10ptの計算は費用感応に限る。", "", "| 入口 | 複数手法を組み合わせた新規根拠 |", "| --- | --- |", "| 共通主軸 | 方向別3分MACDhist増分>0、終値がEMA8方向側、取得BBOがEMA8から方向側0..1ATR。TR>前ATR×2かつRSI差絶対15超の同時急変を除外 |", "| 順行 | 共通主軸＋3/15分EMA8−21がともに実方向 |", "| 転換初動 | 順行不成立＋共通主軸＋RSI増分正＋直前確定3分の終値/同足EMA8から現在の回復＋新鮮なE08帯量支持・反対圧力解消 |", "| B0 | 上記の順行又は初動。個別既知の5秒速度<0、15秒速度<0、OFI30<0だけを拒否 |", "| B1 | B0と同じ。両速度既知・v15>0・v5<=0.5v15の失速時だけ、既知OFI正又は新鮮な帯量支持を追加確認 |", "", "DayShort速度はMove/Elapsedのpt/秒。81のSupport.Own5/Own15という窓別換算bp幅を代用しない。未知・0・反対・支持を区別し、補助の未知だけで順行を自動棄却しない。M/Tは新規確率にせず、相手120秒と自己120/300秒は診断だけに残す。", "", "現在と直前の確定3分足は連続180秒と同一前hist/RSIへの結合を確認する。3/15分の終端は当時以前180/900秒以内。現在Last/BBOは同物理行・自己時計15秒鮮度。未確定足、未来の極値、未知の0埋めは使わない。EMA・RSI・MACDを独立した賛成票へ数えない。", "", "利益保護は両入口で81G1を固定。正益前は入口ATRをceil5・15..125ptへ固定したDで追尾し、3分終値がEMA8反対かつhist増分も反対なら技法失敗返済する。費用後単価益がstrict正なら部分利確を要求し、残玉を最低建値の床で保護する。部分利確が全量約定した後だけ、確定純額Rと残量nから予算床を計算する。未約定益を予算にせず、返済要求を取消・延期しない。", "", "利確量はceil((222Q+1−R)/(u+222))を1..Qへ制限し、完了後の予算床はceil5(max(0,(222+(1−R)/n)/10))。222円は往復122円＋10pt悪化余裕100円で、余裕を費用へ二重加算しない。次板悪化で赤字になる可能性は残る。詳細は[検証計画](検証計画.md)と[全設定・版5の55×9表](設定と結果.md)。", "", "## 結果", "", result_block(data), "", "| 政策 | 粗損益円 | 費用円 | 正益未観測の損益円 | 正益観測の損益円 | 残玉正益後赤字 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        s = result["比較"][key]
        text.append(f"| {key} | {amount(s['総計']['gross_pnl_yen'])} | {amount(s['総計']['total_cost_yen'])} | {amount(s['正益未観測の損益円'])} | {amount(s['正益観測の損益円'])} | {ratio(s['残玉旗後赤字'],s['残玉旗'])} |")
    text.extend(["", "残玉旗は一枚の費用後現在益、全玉旗は既返済部分を含む純額。率の分母を混同しない。DDは返済費用を含む全正常原行の場別評価を時系列で結合し、場末だけのDDとは区別する。", "", "| 政策 | Day純額円 | Night純額円 | 黒字日/日数 | 最悪日円 | 最良日円 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for key in KEYS:
        rows = [r for r in result["場別"] if r["key"] == key]
        day = sum((number(r["metrics"]["net_pnl_yen"]) for r in rows if r["session"].endswith("Day")), Decimal(0))
        night = sum((number(r["metrics"]["net_pnl_yen"]) for r in rows if r["session"].endswith("Night")), Decimal(0))
        daily = [number(v) for v in result["比較"][key]["日別円"].values()]
        text.append(f"| {key} | {amount(day)} | {amount(night)} | {sum(v>0 for v in daily)}/{len(daily)} | {amount(min(daily))} | {amount(max(daily))} |")
    text.extend(["", "## 候補・実参加・補助状態", "", "| 入口 | 全定時 | 時計許可 | 方向判定成立 | 候補供給 | 実採用D0 | 実採用D1 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for policy in ("B0", "B1"):
        a = data["availability"][policy]
        text.append(f"| {policy} | {a['全定時']} | {a['時計許可']} | {a['方向判定成立']} | {a['候補生成']} | {result['比較'][policy+'G1_D0']['完結玉']} | {result['比較'][policy+'G1_D1']['完結玉']} |")
    if all_lots == 0:
        text.extend(["", "**実採用0のためG1市場検証は未発生、保護効果は未評価。0損益を改善としない。**"])
    text.extend(["", "| 政策 | 実会計の定時判断 | 枠数 |", "| --- | --- | ---: |"])
    for key in KEYS:
        actions = result["比較"][key].get("判断")
        if actions is None:
            text.append(f"| {key} | 保存なし・未計測 | — |")
        else:
            for action, n in sorted(actions.items()):
                text.append(f"| {key} | {action} | {n} |")
    text.extend(["", "実会計の保有継続と新規・待ちを候補の成立と分ける。必要なチャート値の未知は方向別required_unknownと以下の判定項目へ残す。保有中を待ちへ加えて率を操作しない。", "", "| 入口 | 補助状態（方向×定時） | 件数 |", "| --- | --- | ---: |"])
    for policy in ("B0", "B1"):
        for name, n in sorted(data["auxiliary"][policy].items()):
            text.append(f"| {policy} | {name} | {n} |")
    text.extend(["", "補助状態は評価時の鮮度・単位・異常を検査したDirections.auxiliaryから集計する。方向×定時が分母で、速度/OFI/構造の各分類は重複するため合算しない。未知を反対や支持の観測へ変換しない。", "", "| 入口 | 判定項目（枝/役割） | 方向数 | 既知 | 成立 | 未知 |", "| --- | --- | ---: | ---: | ---: | ---: |"])
    for policy in ("B0", "B1"):
        for name, c in sorted(data["availability"][policy]["判定項目"].items()):
            text.append(f"| {policy} | {name} | {c['方向数']} | {c['既知']} | {c['成立']} | {c['未知']} |")
    text.extend(["", "支持の元系列の未知理由も、現在の入口で必須かどうかとは別に保存する。非採用枝や診断専用の未知を、全ての新規の判定不能へ読み替えない。", "", "| 入口 | 元支持の未知理由 | 方向×定時件数 |", "| --- | --- | ---: |"])
    for policy in ("B0", "B1"):
        reasons = data["availability"][policy]["支持未知理由"]
        for reason, n in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):
            text.append(f"| {policy} | {reason.replace('|','／')} | {n} |")
    # ----------------------------------------
    # 同一出口の入口比較を、同実入口と参加変更へ分ける。
    text.extend(["", "## 同実入口と参加差", "", "| 遅延 | 同実新規 | 同実B1−B0円 | B0のみ玉/純額 | B1のみ玉/純額 | 取得変更玉/B1−B0円 | 総差円 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for name, d in result["入口間の同実新規分解"].items():
        k0, k1 = d["比較"]
        difference = number(result["比較"][k1]["費用後損益円"]) - number(result["比較"][k0]["費用後損益円"])
        changed = number(d["取得変更B1損益円"]) - number(d["取得変更B0損益円"])
        text.append(f"| {name} | {d['同実新規']} | {amount(d['同実新規出口差円'])} | {d['B0のみ']}/{amount(d['B0のみ損益円'])} | {d['B1のみ']}/{amount(d['B1のみ損益円'])} | {d['共通だが取得変更']}/{amount(changed)} | {amount(difference)} |")
    text.extend(["", "対応は同じ場・候補定時・実方向で取り、同実入口は新規時計・価格・初回枚数も一致した玉。B0/B1で政策接頭辞が違う候補IDをそのまま同一IDとして比較しない。取得変更と片側参加に含まれる損益を、元の早い入口で分かっていた利益へ戻さない。出口は同じG1であり、補助条件の追加効果と保有による参加差を分ける。", "", "## 部分確定・保護・要求後悪化", "", "| 政策 | 利確要求玉 | 要求枚数 | 確定枚数 | 利確完了玉 | cash床玉 | 予算充足不能玉 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for key in KEYS:
        t = result["比較"][key]["総計"]
        text.append(f"| {key} | {t.get('harvest_orders',0)} | {t.get('harvest_quantity',0)} | {t.get('harvest_filled_quantity',0)} | {t.get('harvest_done_lots',0)} | {t.get('cash_floor_activated_lots',0)} | {t.get('funding_failure_lots',0)} |")
    text.extend(["", "| 政策 | 正常保有原行 | 床到達原行 | 全量予約義務 | 予約不足原行/数量 | 利確要求義務/不足 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for key in KEYS:
        n = data["normative"][key]
        text.append(f"| {key} | {n.get('正常保有原行',0)} | {n.get('床到達原行',0)} | {n.get('返済義務原行',0)} | {n['予約不足原行']}/{n['予約不足数量']} | {n.get('利確要求義務原行',0)}/{n['利確要求不足原行']} |")
    text.extend(["", "上表は原板から独立に再構成した保護規範。互換カウンター0だけを遵守の根拠にしない。原板にない期間・通信・実商品の執行は未確認。", "", "| 政策 | 初回正益と同時計の返済要求 | 初回正益と同時計で全返済完了 | 正益後の要求→約定悪化円 |", "| --- | ---: | ---: | ---: |"])
    for key in KEYS:
        flagged = [r for r in data["diagnostics"][key].values() if r["lot"]["flag"]]
        same_request = sum(any(number(c["request_time"]) == number(r["lot"]["flag_time"]) for c in r["closed"]) for r in flagged)
        same_flat = sum(max(number(c["exit_time"]) for c in r["closed"]) == number(r["lot"]["flag_time"]) for r in flagged)
        adverse = sum((number(c["request_to_fill_adverse_yen"]) for r in flagged for c in r["closed"]), Decimal(0))
        text.append(f"| {key} | {ratio(same_request,len(flagged))} | {ratio(same_flat,len(flagged))} | {amount(adverse)} |")
    text.extend(["", "同時計は原価格の秒が同じという集計で、後続原行の順序や未約定待ちを消さない。初回返済要求は部分利確を含む。要求後悪化は保護を放置したことと分ける。返済後も保持していた場合の利益は未計測で、早い返済の損害とは断定しない。", "", "| 政策 | 返済理由 | 枚数 | 費用後円 |", "| --- | --- | ---: | ---: |"])
    for key in KEYS:
        s = result["比較"][key]
        for reason, quantity in sorted(s["返済理由別枚数"].items()):
            text.append(f"| {key} | {reason} | {quantity} | {amount(s['返済理由別損益円'][reason])} |")
    text.extend(["", "## 費用・再現・限界", "", "| 政策 | 同約定滑り0pt・往復22円 | 主滑り5pt・往復122円 | 同約定滑り10pt・往復222円 |", "| --- | ---: | ---: | ---: |"])
    for key in KEYS:
        s = result["比較"][key]
        text.append(f"| {key} | {amount(s['同約定0pt損益円'])} | {amount(s['費用後損益円'])} | {amount(s['同約定10pt損益円'])} |")
    references = [("result", "結果正本"), ("catalog", "Viewer264資源"), ("cash_audit", "約定会計照合"), ("raw_audit", "原板・全玉・床監査"), ("viewer_audit", "Viewer数値監査"), ("condition", "固定条件"), ("input_reference", "入力参照"), ("manifest", "66場固定台帳"), ("trades", "圧縮玉診断"), ("grids", "圧縮定時判断")]
    text.extend(["", " · ".join(link(study, paths[n], label) for n, label in references), "", "コードは[scripts/チャートの現在性と補助確認](../../scripts/チャートの現在性と補助確認/)へ分離。固定81G1と80・兄弟repoを読取再用し、旧試行を書き換えない。batch CLIで16worker再生後、保存会計・原板・Viewerを別検査する。帳票は明示正本だけを読み、市場原板読取0・新売買再生0で生成する。", "", "全66場は既使用で、4会計や接続確認2場を独立標本へ水増ししない。正常ラージBBOへ全量micro約定と一定滑りを仮定した。板深さ消費、実通信遅延、mini/microの約定順位、証拠金制約は未実証。原価格時計を受信時計と同一視しない。", "", "利益後赤字が残る場合は、要求前の不足・要求後悪化・確定予算と正益前損失を分ける。正益前損失が減っても参加減だけ・費用減だけ・失った勝ちが大きい可能性を残す。費用後の安定性は期間・昼夜・日別・遅延を見て判断し、少数の黒字群や指標単独の効果へ読み替えない。", ""])
    command = ['& "work/venvs/technical-tree/Scripts/python.exe" -B -X utf8 "scripts/チャートの現在性と補助確認/レポート.py" --check `', '  --study "' + Path(os.path.relpath(study, ROOT)).as_posix() + '" `']
    for i, (name, _) in enumerate(references):
        command.append('  --' + name.replace("_", "-") + ' "' + Path(os.path.relpath(paths[name], ROOT)).as_posix() + '"' + (' `' if i < len(references)-1 else ''))
    text.extend(["", "ルートPowerShellから保存帳票の同値を確認する。正式生成は同じ明示入力で--checkを--runへ置き換える。", "", "```powershell", *command, "```", "", "[帳票生成証拠](レポート生成証拠.json)へ全入力・固定依存・生成コード・出力のSHAを保存する。", ""])
    return "\n".join(text)


def generate(paths: dict, study: Path, check: bool) -> dict:
    """
    機能: 全guard後にREADMEと専用マーカーだけを生成又は確認する。
    引数: paths (dict) は明示入力、study (Path) は出力、check (bool) は読取確認のみか。
    返り値: dict は正本SHA・出力SHA・非再生を記した証拠。
    """
    data = prepare(paths, study)
    old = data["settings"]
    need(STATUS in old, "固定設定の状態文言が必要")
    left, rest = old.split(BEGIN)
    _, right = rest.split(END)
    settings = left + BEGIN + "\n" + result_block(data) + "\n" + END + right
    readme = render_readme(data, study)
    proof = {"試行": 82, "成功": True, "場数": 66, "会計数": 264, "Viewer資源数": 264,
        "入力パス": {name: str(path.resolve()) for name, path in paths.items()}, "入力SHA256": data["input_sha"],
        "固定依存SHA256": data["dependencies"], "生成コードSHA256": sha(Path(__file__)),
        "設定マーカー外SHA256": hashlib.sha256((left + BEGIN + END + right).encode("utf-8")).hexdigest(),
        "出力SHA256": {"README.md": hashlib.sha256(readme.encode("utf-8")).hexdigest(), "設定と結果.md": hashlib.sha256(settings.encode("utf-8")).hexdigest()},
        "本処理の市場原板読取": 0, "新売買再生": 0}
    if check:
        need((study / "README.md").read_text(encoding="utf-8") == readme, "READMEの生成差")
        need((study / "設定と結果.md").read_text(encoding="utf-8") == settings, "設定結果の生成差")
        need(read_json(study / "レポート生成証拠.json") == proof, "生成証拠の差")
    else:
        (study / "README.md").write_text(readme, encoding="utf-8", newline="\n")
        (study / "設定と結果.md").write_text(settings, encoding="utf-8", newline="\n")
        (study / "レポート生成証拠.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return proof


def fake_inputs(base: Path) -> tuple[Path, dict]:
    """
    機能: 市場入力を開かず、66場・264会計・全定時の人工正本を組み立てる。
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
    reference = {"試行": 82, "入力台帳": str(paths["manifest"]), "入力台帳SHA256": sha(paths["manifest"]), "入力場数": 66, "入力ファイル数": 396, "全場既使用": True, "固定80採用版": 2, "固定80依存指紋": deps, "固定81依存指紋": deps, "固定80条件SHA256": sha(ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/条件.json")}
    condition = {"試行": 82, "入力台帳SHA256": sha(paths["manifest"]), "入力場数": 66, "全場既使用": True, "modes": list(MODES), "keys": list(KEYS), "約定追加価格時計遅延秒": [0, 1], "新規数量micro枚": 100, "片側上限": 100, "point_value": 10, "片道手数料円": 11, "片道滑りpt": 5, "主往復費用円毎枚": 122, "G1悪化余裕pt": 10, "G1全玉予算目標円": 1, "同時一建玉": True, "新損益前固定": True, "固定80依存": deps, "固定81依存": deps, "コードと依存SHA256": deps}
    condition.update({"実行ファイル": str(dependency), "実行ファイルSHA256": sha(dependency)})
    save(paths["input_reference"], reference)
    save(paths["condition"], condition)
    zero_metric = {name: 0 for name in ("net_pnl_yen", "cash_yen", "gross_pnl_yen", "total_cost_yen", "commission_yen", "slippage_yen", "open_quantity", "pending_entry_quantity", "reserved_exit_quantity", "entry_quantity", "exit_quantity", "closed_lots", "max_drawdown_yen", "min_equity_yen", "equity_peak_yen", "harvest_orders", "harvest_quantity", "harvest_filled_quantity", "harvest_done_lots", "cash_floor_activated_lots", "funding_failure_lots")}
    result = {"試行": 82, "場数": 66, "全場既使用": True, "入力台帳SHA256": sha(paths["manifest"]), "再生結果SHA256": {s + ".json": hashlib.sha256(s.encode()).hexdigest() for s in sessions}, "比較": {}, "場別": [], "入口間の同実新規分解": {}, "定時の候補と入力可用性": {p: {"全定時": 0, "時計許可": 0, "方向判定成立": 0, "候補生成": 0, "判定項目": {"共通:人工": {"方向数": 0, "既知": 0, "成立": 0, "未知": 0}}, "支持未知理由": {"own_reason:人工未準備": 0}} for p in ("B0", "B1")}}
    cash = {"会計数": 264, "不一致数": 0, "照合": []}
    catalog = {"schema_version": 1, "path_base": "catalog", "resources": []}
    viewer_rows = []
    for key in KEYS:
        mode, delay = key.split("_D")
        result["比較"][key] = {"mode": mode, "追加遅延秒": int(delay), "費用後損益円": 0, "最大DD円": 0, "全場": 66, "赤字場数": 0, "黒字場数": 0, "同値場数": 66, "赤字日数": 0, "日数": 33, "日別円": {s[:10]: 0 for s in sessions}, "完結玉": 0, "残玉旗": 0, "残玉旗後赤字": 0, "全玉旗": 0, "全玉旗後赤字": 0, "正益未観測の損益円": 0, "正益観測の損益円": 0, "同約定0pt損益円": 0, "同約定10pt損益円": 0, "総計": deepcopy(zero_metric), "返済理由別枚数": {}, "返済理由別損益円": {}}
        for session in sessions:
            result["場別"].append({"session": session, "key": key, "mode": mode, "delay": int(delay), "metrics": deepcopy(zero_metric), "累積損益円": 0})
            cash["照合"].append({"session": session, "key": key, "約定数": 0, "現金円": 0, "粗損益円": 0, "費用円": 0, "残量": 0})
            name = f"約定/D{delay}/{mode}/{session}.trades.jsonl"
            trade_path = output / name
            trade_path.parent.mkdir(parents=True, exist_ok=True)
            trade_path.write_text("", encoding="utf-8")
            identity = f"82_{key}_{session}"
            catalog["resources"].append({"id": identity, "symbol": "NK225", "session": session, "method_id": mode, "product": "NK225micro", "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": name, "market_path": f"NK225/{session}/book.jsonl.gz"})
            viewer_rows.append({"id": identity, "完了": True, "不一致数": 0, "不一致": [], "APIエラー": None, "API費用後円": 0, "原純額円": 0})
    for delay in (0, 1):
        result["入口間の同実新規分解"][f"D{delay}"] = {"比較": [f"B0G1_D{delay}", f"B1G1_D{delay}"], **{name: 0 for name in ("同実新規", "共通だが取得変更", "同実新規B0損益円", "同実新規B1損益円", "同実新規出口差円", "B0のみ", "B1のみ", "B0のみ損益円", "B1のみ損益円", "取得変更B0損益円", "取得変更B1損益円")}}
    grid_rows = []
    for session in sessions:
        start = datetime.fromisoformat(session[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
        first = start + (timedelta(hours=9, minutes=15) if session.endswith("Day") else timedelta(hours=17, minutes=30))
        length = 25 if session.endswith("Day") else 49
        grids = []
        for i in range(length):
            at = (first + timedelta(minutes=15*i)).timestamp()
            for policy in ("B0", "B1"):
                evidence = {"time": 0, **{side: {"own_reason": "人工未準備", "peer_reason": "", "ofi_reason": ""} for side in ("buy", "sell")}}
                auxiliary = {field: {"known": False, "state": "未知", "reason": "人工未知"} for field in ("five", "fifteen", "ofi")}
                auxiliary.update({name: False for name in ("slowdown_known", "slowdown", "structure_known", "structure_support", "pressure_clear")})
                decision = {"at": at, "policy": policy, "allowed": False, "side": 0, "quote": {"time": 0}, "technical": {"bar3_end": 0, "bar15_end": 0},
                    "chart_pair": {"previous_close3": 0, "previous_ema8_3": 0, "previous_bar3_end": 0, "previous3_known": False}, "evidence": evidence,
                    "directions": [{"side": side, "required_unknown": True, "auxiliary": deepcopy(auxiliary), "checks": [{"group": "共通", "id": "人工", "known": False, "passed": False}]} for side in (1, -1)]}
                grids.append({"at": at, "entry_policy": policy, "clock_allowed": True, "candidate_accepted": False, "decision": decision})
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
    norms = {name: 0 for name in ("正常保有原行", "正益後保有原行", "床到達原行", "125pt到達原行", "cash床原行", "返済義務原行", "予約不足原行", "予約不足数量", "利確要求義務原行", "利確要求不足原行", "利確量検査")}
    raw = {"試行": 82, "成功": True, "場数": 66, "不一致数": 0, "不一致": [], "入力台帳SHA256": sha(paths["manifest"]), "監査コードSHA256": sha(Path(__file__).with_name("原板監査.py")), "固定80監査SHA256": sha(ROOT / "scripts/FAR後期15分移植/原板照合.py"), "固定81監査SHA256": sha(ROOT / "scripts/定時の現在根拠と部分利益保護/原板監査.py"), "対象場": [{"session": s, "再生結果SHA256": result["再生結果SHA256"][s + ".json"], "不一致数": 0, "不一致": [], "診断": {"場": s, "JSON本文走査回数": 1, "全玉費用後評価": {k: [] for k in KEYS}, "利益床の独立規範": {k: deepcopy(norms) for k in KEYS}}} for s in sessions]}
    save(paths["raw_audit"], raw)
    viewed_paths = [paths["result"], paths["catalog"]] + [output / r["pnl_path"] for r in catalog["resources"]]
    viewed_hashes = {str(p): sha(p) for p in viewed_paths}
    save(paths["viewer_audit"], {"試行": 82, "成功": True, "完了資源": 264, "予定資源": 264, "不一致数": 0, "APIエラー": [], "入力不変": True, "入力SHA256前": viewed_hashes, "入力SHA256後": viewed_hashes, "結果SHA256": sha(paths["result"]), "一覧SHA256": sha(paths["catalog"]), "監査コードSHA256": sha(Path(__file__).with_name("表示監査.py")), "資源": viewer_rows})
    setting_path = ROOT / "study/00082_チャートの現在性と補助確認/設定と結果.md"
    setting = setting_path.read_text(encoding="utf-8")
    for method in read_json(ROOT / "scripts/レポート/手法カタログ_版5.json")["methods"]:
        actual = ROOT / method["source"]
        original = Path(os.path.relpath(actual, setting_path.parent)).as_posix()
        derived = Path(os.path.relpath(actual, study)).as_posix()
        setting = setting.replace("](" + original + ")", "](" + derived + ")")
    (study / "設定と結果.md").write_text(setting, encoding="utf-8")
    return study, paths


def self_test() -> dict:
    """
    機能: 人工66場の生成/照合と不整合拒否を市場なしで検査する。
    引数: なし。
    返り値: dict は人工の件数・生成同値と市場読取0。
    """
    work = (ROOT / "work").resolve()
    work.mkdir(exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory(prefix="82帳票人工_", dir=work) as directory:
        base = Path(directory).resolve()
        need(base.is_relative_to(work), "人工の削除範囲がwork外です")
        study, paths = fake_inputs(base)
        before_setting = (study / "設定と結果.md").read_text(encoding="utf-8")
        generate(paths, study, False)
        generate(paths, study, True)
        after_setting = (study / "設定と結果.md").read_text(encoding="utf-8")
        need(before_setting.split(BEGIN)[0] == after_setting.split(BEGIN)[0] and before_setting.split(END)[1] == after_setting.split(END)[1], "結果マーカー外の改変")
        need("保護効果は未評価" in (study / "README.md").read_text(encoding="utf-8"), "0取引の効果未評価が必要")
        checks.extend(["66場264会計の生成", "生成同値", "設定マーカー外不変", "0取引の未評価"])

        def reject_json(name: str, change: object, label: str) -> None:
            """
            機能: 人工正本の一欠陥を投入し、出力せず拒否することを検査する。
            引数: name (str) は入力名、change (Callable) は変更、label (str) は人工名。
            返り値: None。常に元人工へ復元する。
            """
            path = paths[name]
            original = path.read_bytes()
            output_before = {p.name: p.read_bytes() for p in study.glob("*.md")}
            try:
                value = read_json(path)
                change(value)
                path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                try:
                    generate(paths, study, False)
                except (ValueError, KeyError, TypeError):
                    checks.append(label)
                else:
                    raise AssertionError("欠陥を拒否しなかった:" + label)
                need(all((study / n).read_bytes() == v for n, v in output_before.items()), "guard前に帳票を変更")
            finally:
                path.write_bytes(original)

        reject_json("result", lambda v: v["比較"][KEYS[0]].update({"費用後損益円": 1}), "集計損益差拒否")
        reject_json("result", lambda v: v["場別"].pop(), "263会計拒否")
        reject_json("result", lambda v: v["場別"][0]["metrics"].update({"open_quantity": True}), "bool個数拒否")
        reject_json("raw_audit", lambda v: v.update({"成功": False}), "原板不成功拒否")
        reject_json("raw_audit", lambda v: v["対象場"].pop(), "原板65場拒否")
        reject_json("raw_audit", lambda v: v["対象場"][0]["診断"]["利益床の独立規範"][KEYS[0]].update({"予約不足原行": 1}), "予約不足拒否")
        reject_json("raw_audit", lambda v: v["対象場"][0]["診断"]["利益床の独立規範"][KEYS[0]].pop("利確要求不足原行"), "独立規範欠落拒否")
        reject_json("viewer_audit", lambda v: v.update({"完了資源": 263}), "Viewer263拒否")
        reject_json("viewer_audit", lambda v: v.update({"APIエラー": ["人工通信欠損"]}), "Viewer通信欠損拒否")
        reject_json("viewer_audit", lambda v: v.update({"結果SHA256": "0" * 64}), "Viewer結果SHA差拒否")
        reject_json("viewer_audit", lambda v: v["資源"].pop(), "Viewer個別欠落拒否")
        reject_json("cash_audit", lambda v: v["照合"].pop(), "会計照合欠落拒否")
        reject_json("catalog", lambda v: v["resources"].append(v["resources"][0]), "資源重複拒否")
        reject_json("condition", lambda v: v.update({"入力台帳SHA256": "0" * 64}), "条件台帳SHA差拒否")
        reject_json("input_reference", lambda v: v.update({"入力台帳SHA256": "0" * 64}), "入力参照台帳SHA差拒否")
        reject_json("condition", lambda v: v.update({"point_value": True}), "費用尺度のbool拒否")
        reject_json("result", lambda v: v["定時の候補と入力可用性"]["B0"].update({"候補生成": 1}), "候補供給数差拒否")
        reject_json("raw_audit", lambda v: v.update({"監査コードSHA256": "0" * 64}), "原板監査コード差拒否")
        reject_json("viewer_audit", lambda v: v.update({"監査コードSHA256": "0" * 64}), "Viewer監査コード差拒否")
        reject_json("condition", lambda v: v.update({"実行ファイルSHA256": "0" * 64}), "再生実行ファイル差拒否")
        reject_json("condition", lambda v: v.update({"固定81依存": {"偽": "0" * 64}}), "固定81依存集合差拒否")
        reject_json("raw_audit", lambda v: v.update({"固定81監査SHA256": "0" * 64}), "固定81監査コード差拒否")
        reject_json("result", lambda v: v["入口間の同実新規分解"]["D0"].update({"B1のみ": 1}), "入口片側数差拒否")
        # ----------------------------------------
        # 時計・既知性は圧縮定時を直接変え、保存集計より前の拒否を検査します。
        grids = compressed_rows(paths["grids"])
        saved_result = read_json(paths["result"])
        sessions = [r["id"] for r in read_json(paths["manifest"])["sessions"]]

        def reject_grid(change: object, label: str) -> None:
            """
            機能: 人工定時の未来/時計/既知性差を拒否する。
            引数: change (Callable) は一箇所変更、label (str) は人工名。
            返り値: None。正式ファイルを保存しない。
            """
            broken = deepcopy(grids)
            change(broken)
            try:
                verify_grids(broken, saved_result, {key: {} for key in KEYS}, sessions)
            except (ValueError, KeyError, TypeError):
                checks.append(label)
            else:
                raise AssertionError("時計差を拒否しなかった:" + label)

        reject_grid(lambda v: v[0]["grid_decisions"][0].update({"candidate_accepted": True, "clock_allowed": False}), "静観中候補供給拒否")
        reject_grid(lambda v: v[0]["grid_decisions"][0]["decision"]["quote"].update({"time": v[0]["grid_decisions"][0]["at"] + 1}), "未来気配拒否")
        reject_grid(lambda v: v[0]["grid_decisions"][0]["decision"]["technical"].update({"bar3_end": v[0]["grid_decisions"][0]["at"] + 1}), "未来確定足拒否")
        reject_grid(lambda v: v[0]["grid_decisions"][0]["decision"]["directions"][0]["checks"][0].update({"passed": True}), "未知を成立へ置換拒否")
        reject_grid(lambda v: v[0]["grid_decisions"].pop(), "定時一枠欠落拒否")
        reject_grid(lambda v: v[0]["grid_decisions"][0]["decision"]["chart_pair"].update({"previous_bar3_end": v[0]["grid_decisions"][0]["at"] + 1}), "未来の直前足拒否")
        # ----------------------------------------
        # 新しい補助状態の未知・符号・失速判定を壊して検査する。
        verify_auxiliary(grids)
        checks.append("補助未知の状態集計")

        def reject_auxiliary(change: object, label: str) -> None:
            """
            機能: 人工定時の評価済み補助状態の矛盾を拒否する。
            引数: change (Callable) は一箇所変更、label (str) は人工名。
            返り値: None。正式ファイルへ保存しない。
            """
            broken = deepcopy(grids[:1])
            aux = broken[0]["grid_decisions"][0]["decision"]["directions"][0]["auxiliary"]
            change(aux)
            try:
                verify_auxiliary(broken)
            except (ValueError, KeyError, TypeError):
                checks.append(label)
            else:
                raise AssertionError("補助差を拒否しなかった:" + label)

        reject_auxiliary(lambda v: v["five"].update({"value": 0}), "未知速度の0補完拒否")
        reject_auxiliary(lambda v: v["ofi"].update({"known": True, "state": "支持", "value": -1}), "OFI符号と状態差拒否")
        reject_auxiliary(lambda v: v.update({"slowdown": True}), "未知速度の失速化拒否")
        reject_auxiliary(lambda v: v.update({"structure_support": True}), "未知帯の支持化拒否")
        setting_path = study / "設定と結果.md"
        setting = setting_path.read_text(encoding="utf-8")
        for replacement, label in ((setting.replace("| I01 |", "| Z01 |", 1), "手法順差拒否"), (setting.replace("[MACD]", "[別名]", 1), "手法名差拒否")):
            try:
                verify_table(replacement, study)
            except ValueError:
                checks.append(label)
            else:
                raise AssertionError("表差を拒否しなかった")
        readme = study / "README.md"
        original_readme = readme.read_bytes()
        readme.write_text("人工改変", encoding="utf-8")
        try:
            generate(paths, study, True)
        except ValueError:
            checks.append("保存README差拒否")
        else:
            raise AssertionError("checkがREADME差を拒否しなかった")
        readme.write_bytes(original_readme)
        # ----------------------------------------
        # 部分利確・確定予算の帳票対応は非0の人工玉で検査します。
        result = read_json(paths["result"])
        session = read_json(paths["manifest"])["sessions"][0]["id"]
        rows = []
        for key in KEYS:
            partial = "G1" in key
            lot = {"id": key + "_玉", "reference_id": key[:2] + "_候補", "initial_quantity": 100, "closed_quantity": 100, "quantity": 0, "flag": True, "whole_flag": True, "net_pnl": 7800, "harvest_target": 75 if partial else 0, "harvest_filled": 75 if partial else 0, "cash_floor_active": partial, "harvest_done_at": 20 if partial else None, "cash_floor_at": 21 if partial else None, "funding_failed": False, "side": 1, "entry_price": 30000, "entry_time": 10}
            closed = [{"quantity": 75, "pnl5": 5850, "reason": "人工利確"}, {"quantity": 25, "pnl5": 1950, "reason": "人工利確"}] if partial else [{"quantity": 100, "pnl5": 7800, "reason": "人工利確"}]
            rows.append({"session": session, "key": key, "lot": lot, "closed": closed, "entry_order": {"request_time": 5}})
            s = result["比較"][key]
            s.update({"完結玉": 1, "費用後損益円": 7800, "残玉旗": 1, "全玉旗": 1, "正益観測の損益円": 7800, "返済理由別枚数": {"人工利確": 100}, "返済理由別損益円": {"人工利確": 7800}})
            s["総計"].update({"harvest_orders": int(partial), "harvest_quantity": 75 if partial else 0, "harvest_filled_quantity": 75 if partial else 0, "cash_floor_activated_lots": int(partial)})
        for d in result["入口間の同実新規分解"].values():
            d.update({"同実新規": 1, "同実新規B0損益円": 7800, "同実新規B1損益円": 7800})
        verify_diagnostics(rows, result, [session])
        checks.append("75枚確定25枚残の予算対応")
        mismatch_rows, mismatch_result = deepcopy(rows), deepcopy(result)
        mismatch_rows[1]["lot"]["net_pnl"] += 1
        mismatch_rows[1]["closed"][0]["pnl5"] += 1
        mismatch_result["比較"][KEYS[1]].update({"費用後損益円": 7801, "正益観測の損益円": 7801, "返済理由別損益円": {"人工利確": 7801}})
        mismatch_result["入口間の同実新規分解"]["D0"].update({"同実新規B1損益円": 7801, "同実新規出口差円": 1})
        try:
            verify_diagnostics(mismatch_rows, mismatch_result, [session])
        except ValueError:
            checks.append("G1固定の同実入口損益差拒否")
        else:
            raise AssertionError("同実入口なのに固定出口の損益が変化")
        # ----------------------------------------
        # 二政策の参照ID接頭辞に依存せず、同定時・同方向で比較する。
        changed_rows, changed_result = deepcopy(rows), deepcopy(result)
        changed_rows[1]["lot"]["entry_price"] += 5
        changed_result["入口間の同実新規分解"]["D0"].update({"同実新規": 0, "同実新規B0損益円": 0,
            "同実新規B1損益円": 0, "共通だが取得変更": 1, "取得変更B0損益円": 7800, "取得変更B1損益円": 7800})
        verify_diagnostics(changed_rows, changed_result, [session])
        checks.append("同定時の取得価格変更を別群")
        changed_rows, changed_result = deepcopy(rows), deepcopy(result)
        changed_rows[1]["entry_order"]["request_time"] += 900
        changed_result["入口間の同実新規分解"]["D0"].update({"同実新規": 0, "同実新規B0損益円": 0,
            "同実新規B1損益円": 0, "B0のみ": 1, "B1のみ": 1, "B0のみ損益円": 7800, "B1のみ損益円": 7800})
        verify_diagnostics(changed_rows, changed_result, [session])
        checks.append("候補定時変更を片側参加へ分離")
        broken = deepcopy(rows)
        broken[1]["lot"]["harvest_filled"] = 74
        try:
            verify_diagnostics(broken, result, [session])
        except ValueError:
            checks.append("部分未完了予算拒否")
        else:
            raise AssertionError("未確定予算を拒否しなかった")
    return {"成功": True, "人工数": len(checks), "人工": checks, "市場原板読取": 0, "新売買再生": 0}


def main() -> None:
    """
    機能: 明示正本の帳票生成・同値確認・人工だけを切り替える。
    引数: CLIの--run/--check/--self-test (bool)、--studyと各正本 (Path)。
    返り値: None。不整合は非0終了し、正式市場を暗黙に読まない。
    """
    parser = argparse.ArgumentParser(description="82の小型正本からMarkdownを生成")
    stage = parser.add_mutually_exclusive_group(required=True)
    for name in ("run", "check", "self-test"):
        stage.add_argument("--" + name, action="store_true")
    parser.add_argument("--study", type=Path)
    names = ("result", "catalog", "cash-audit", "raw-audit", "viewer-audit", "condition", "input-reference", "manifest", "trades", "grids")
    for name in names:
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.self_test:
        need(args.study is None and not any(getattr(args, n.replace("-", "_")) for n in names), "人工と正式入力を同時指定しない")
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    need(args.study is not None and all(getattr(args, n.replace("-", "_")) is not None for n in names), "studyと全正本の明示が必要")
    paths = {n.replace("-", "_"): getattr(args, n.replace("-", "_")).resolve() for n in names}
    proof = generate(paths, args.study.resolve(), args.check)
    print(json.dumps({k: proof[k] for k in ("試行", "成功", "場数", "会計数", "Viewer資源数", "本処理の市場原板読取", "新売買再生")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
