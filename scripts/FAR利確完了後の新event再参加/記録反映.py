"""91の13明示正本を結合し、固定E1/G1と新event再参加を帳票化する。

固定87帳票の経済/版5/Viewer照合を明示派生。新市場・売買・APIは実行しない。
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
POLICIES=('E1',)
MODES=('R0','R1')
INTERNAL={'R0':'S0G1','R1':'S0G1'}
KEYS=tuple(f'{m}_D{d}' for d in (0,1) for m in MODES)
BEGIN='<!-- 91_RESULTS_BEGIN -->'
END='<!-- 91_RESULTS_END -->'
PRE_BLOCK='未実行。66場264会計・旧89対照132・複数実世代の保存/原板/Source/Viewer全証拠が揃うまで成績を記載しない。'
SAVED_SHA='88095ffd5cb3d2a7d4919cde4cfbf57439a44a3866e34afeafa163366b661eaf'
SOURCE_SHA='c7293751dbf9da86626cfedceaf94db913324e84150c41afaff107693cdaee07'
EVENT_SHA='64375860dbc02e21674c4af99b14c9c14baacad61833541a8c62d4027e97b14a'
RAW_EVENT_SHA='e380e5ea0035c913eaaff586694c735df9a75fec0961b0c9ef2152b5262e7e5a'
PRETABLE_SHA='7e7ccfba72783b7126fe60eabc11bc642130a87fec30ed3a1ac69c13758f0c8c'


# 固定87帳票派生元SHA256: bcda3a1091b4dc7ca81e1296fcc1faed6a3b0fdc34d80309dc9945cd9460a836

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
    headers=[line for line in text.splitlines() if line.startswith("| ID | 手法 |")]
    expected_header=next(line for line in template.splitlines() if line.startswith("| ID | 手法 |"))
    need(bool(headers) and all(line==expected_header for line in headers), "9尺度の見出し差")
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
    need(count(result["試行"]) == 91 and count(result["場数"]) == 66 and result["全場既使用"] is True, "91の66場が必要")
    need(result["金融内部モード"] == INTERNAL, "全金融S0G1の対応差")
    need(result['外入口']==dict.fromkeys(MODES,'E1') and result['利益配分']==dict.fromkeys(MODES,'G1'),'外入口と収穫配分の二軸対応差')
    need(result['構造床有効']=={'R0':False,'R1':False} and all(type(v) is bool for v in result['構造床有効'].values()),'構造床off差')
    need(result['再参加有効']=={'R0':False,'R1':True} and all(type(v) is bool for v in result['再参加有効'].values()),'再参加off/on差')
    need(result["保持帯床有効"] is False and result["複合確認有効"] == dict.fromkeys(MODES,False) and result["Source入口"] == dict.fromkeys(MODES,"S") and all(type(value) is bool for value in result["複合確認有効"].values()), "旧保持帯床off又は新複合確認設定差")
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
        expected_counts = {name: sum(count(r['metrics']['confirm_counts'][name]) for r in chosen) for name in LEGACY.OLD.COUNTS}
        need(summary['複合確認5群'] == expected_counts, '確認5群の場別合計差')
        audit = LEGACY.BASE.Audit(); LEGACY.OLD.validate_counts(expected_counts, audit, key)
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
        identity = session, lot["id"]
        need(identity not in grouped[key], "同じ実建玉IDの重複")
        need(1 <= count(lot["initial_quantity"]) == count(lot["closed_quantity"]) <= 100 and count(lot["quantity"]) == 0, "1..100枚完結の数量差")
        need(all(type(lot[n]) is bool for n in ("flag", "whole_flag", "cash_floor_active", "funding_failed", "structure_active", "structure_entry_breached")), "旗・構造状態はboolが必要")
        need(sum(number(c["pnl5"]) for c in row["closed"]) == number(lot["net_pnl"]) and sum(count(c["quantity"]) for c in row["closed"]) == lot["initial_quantity"], "返済片の数量・純額差")
        order = row["entry_order"]
        need(order["kind"] == "entry" and count(order["quantity"]) >= count(order["filled_quantity"]) == lot["initial_quantity"], "新規注文数量差")
        need(order["position_id"] == lot["id"] and order["reference_id"] == lot["reference_id"], "新規注文の所有対応差")
        need(lot["id"].startswith(session + "_" + INTERNAL[key.split("_D")[0]] + "_P") and order["id"].startswith(session + "_" + INTERNAL[key.split("_D")[0]] + "_O"), "内部金融IDを外ラベルへ変更")
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
        need(row['entry_role'] in ('初参加','利確後再参加'),'実参加役割enum差')
        if key.startswith('R0_'):need(row['entry_role']=='初参加' and row['opportunity_id'] is None and row['accepted_serial'] is None,'R0へ再参加metadataを創作')
        else:need(type(row['accepted_serial']) is int and row['accepted_serial']>0 and type(row['opportunity_id']) is dict and row['opportunity_id']['session']==session and row['opportunity_id']['reference_id']==lot['reference_id'],'R1受理出典差')
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
            "structure_exit_orders": sum(o["kind"] == "exit" and o["reason"] == "構造否定" for r in group.values() for o in r["orders"]),
            "whole_profit_flags": sum(p["whole_flag"] for p in lots), "whole_flag_after_loss_lots": sum(p["whole_flag"] and number(p["net_pnl"]) < 0 for p in lots)}
        for field, n in expected.items():
            need(s["総計"][field] == n, "構造・利益配分集計差:" + field)
    for key,group in grouped.items():
        role_groups={}
        for row in group.values():role_groups.setdefault(row['entry_role'],[]).append(row['lot'])
        expected={role:{'実参加数':len(lots),'新規枚数':sum(p['initial_quantity'] for p in lots),'費用後円':sum(number(p['net_pnl']) for p in lots),'正益玉':sum(p['flag'] for p in lots),'正益後赤字玉':sum(p['flag'] and number(p['net_pnl'])<0 for p in lots)} for role,lots in role_groups.items()}
        need(expected==result['比較'][key]['実参加役割別'],'実参加役割別の分母/量/純額差')
    return grouped

def verify_exports(paths: dict, catalog: dict, diagnostics: dict, sessions: list[str]) -> None:
    """
    機能: Viewer約定の外側ラベルと、内部S0G1所有・価格・数量・費用・時刻を結ぶ。
    引数: paths/catalog (dict) は明示一覧、diagnostics (dict) は内部金融の全玉、sessions (list[str]) は66場。
    返り値: None。表示ラベル以外の変更・欠落・重複を拒否する。
    """
    resources = {row['id']:row for row in catalog['resources']}
    for session in sessions:
        for key in KEYS:
            resource = resources[f'91_{key}_{session}']
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
                need(trade['method_id'] == key.split('_D')[0] and trade['id'] == f'{session}_{INTERNAL[key.split("_D")[0]]}_T{index:06d}', '内部ID又は表示手法名差')
                need(abs(Decimal(str(datetime.fromisoformat(trade['timestamp']).timestamp())) - number(event.pop('time'))) <= Decimal('0.000001'), '表示約定時刻差')
                need(all(trade[name] == value for name,value in event.items()), '表示約定の所有・価格・数量・費用差')

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
    need(count(raw["試行"]) == 91 and raw["成功"] is True and count(raw["場数"]) == 66 and count(raw["不一致数"]) == 0 and not raw["不一致"], "原板監査が未完又は不一致")
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
    expected_ids = {f"91_{key}_{session}" for session, key in rows}
    need(len(resource_map) == len(resources) == 264 and set(resource_map) == expected_ids, "Viewer264資源の差")
    need(count(viewer["試行"]) == 91 and viewer["成功"] is True and count(viewer["予定資源"]) == count(viewer["完了資源"]) == 264 and count(viewer["不一致数"]) == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "Viewer全件成功が必要")
    api_result_sha=verify_viewer_correction(paths,viewer,result)
    need(viewer["結果SHA256"] == api_result_sha and viewer["一覧SHA256"] == sha(paths["catalog"]), "Viewer API取得時の正本SHA差")
    need(viewer["入力SHA256前"] == viewer["入力SHA256後"], "Viewer読取中の入力変更")
    current_files = {str(paths["result"].resolve()), str(paths["catalog"].resolve())}
    for resource in resources:
        session, key = next((s, k) for s, k in rows if resource["id"] == f"91_{k}_{s}")
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
        v = by_id[f"91_{key}_{session}"]
        need(v["完了"] is True and v["不一致数"] == 0 and v["APIエラー"] is None, "Viewer個別未完了")
        need(number(v["API費用後円"]) == number(v["原純額円"]) == number(rows[session, key]["metrics"]["net_pnl_yen"]), "Viewer個別純額差")
    need(raw['監査コードSHA256'] == sha(Path(__file__).with_name('原板監査.py')) and raw['固定87監査SHA256'] == sha(ROOT/'scripts/FAR参照玉と可変数量の比較/原板監査.py') and raw['原板本文走査回数毎場'] == 1,'G1原板の停止コード又は1走査差')
    need(viewer["監査コードSHA256"] == sha(Path(__file__).with_name("表示監査.py")), "Viewer監査コードSHA差")
    return normative


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
        need(set(row)=={'session','grid_decisions','source_events','source_equivalence','entry_observations','technical_equivalence','seed_view','profit_contexts','input_end','entry_opportunities'},'共有gz10field差')
        for grid in row['grid_decisions']:
            need(set(grid)==SAVED.GRID_FIELDS and grid['c0']['policy']=='C0','Source共有grid集合又はC0差')
            c0=grid['c0'];base=c0['base'];need(base['at']==grid['at'],'C0と定時の時計差')
            need(grid['structure_anchor']==SAVED.BASE.expected_anchor(grid['at'],base['technical']),'当時EMA出典差')
            pool=SAVED.OLD.sorted_pool(grid['source'],grid['at']);pool_counts['全pool候補']+=len(pool);pool_counts['時計許可pool候補']+=len(pool)*grid['clock_allowed']
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


def load_saved() -> object:
    """
    機能: 停止89保存監査と固定88独立イベント式を本文SHAへ固定して読む。
    引数: なし。
    返り値: objectは読取helper。正式市場/売買/原板走査は行わない。
    """
    path=Path(__file__).with_name('基準と保存判断の照合.py')
    need(sha(path)==SAVED_SHA and sha(ROOT/'scripts/FAR背景維持と押戻し再開/イベント保存照合.py')==EVENT_SHA,'停止保存/eventコード差')
    spec=importlib.util.spec_from_file_location('saved91_for_report',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


SAVED=load_saved()
LEGACY=SAVED.OLD


def comparison_pairs() -> list[tuple[str,str,str]]:
    """
    機能: 共通現在資格と順序追加の比較方向を事前に固定する。
    引数: なし。
    返り値: list[tuple[str,str,str]]は名称/A/Bの四比較。
    """
    return [('R1対R0','R0','R1')]


def verify_viewer_correction(paths: dict, viewer: dict, result: dict) -> str:
    """
    機能: 今回は現行結果を取得したViewer正本だけを受ける。
    引数: paths/viewer/result(dict)は明示パス・API証拠・現行結果。
    返り値: strは現行結果SHA。未宣言の旧訂正proofは拒否する。
    """
    need('対応分類訂正' not in viewer,'89へ旧87の対応分類訂正proofを流用できない')
    return sha(paths['result'])


def fixed_dependencies(condition: dict, reference: dict, manifest: Path) -> dict:
    """
    機能: 91固定金融と80..90依存・旧89基準・旧90保存を現物へ結ぶ。
    引数: condition/reference(dict)、manifest(Path)は13入力の宣言。
    返り値: dictは絶対pathとSHA。固定コード数は条件の実数を使う。
    """
    for value in (condition,reference):need(value['試行']==91 and value['入力台帳SHA256']==sha(manifest) and value['入力場数']==66 and value['全場既使用'] is True,'91条件/台帳差')
    need(reference['入力ファイル数']==396 and (ROOT/reference['入力台帳']).resolve()==manifest.resolve(),'396入力参照差')
    need(condition['modes']==list(MODES) and condition['entry_policies']==['E1'] and condition['guards']==['G1'] and condition['keys']==list(KEYS),'4会計/入口/配分差')
    need(condition['source_policy']=='全会計S' and condition['金融内部モード']==INTERNAL,'内部金融対応差')
    need(condition['hold_enabled'] is False and condition['confirm_enabled'] is False and condition['structure_enabled']=={'R0':False,'R1':False} and condition['reentry_enabled']=={'R0':False,'R1':True},'off/on一因子差')
    need(condition['約定追加価格時計遅延秒']==[0,1] and condition['同時一建玉'] is True and condition['新損益前固定'] is True,'時計/所有/事前固定差')
    need(condition['原板本文走査回数毎場']==2 and condition['新規数量micro枚']=='min(現在参照量,実空き量)','二走査又は現量差')
    for name,wanted in (('片側上限',100),('point_value',10),('片道手数料円',11),('片道滑りpt',5),('主往復費用円毎枚',122),('G1悪化余裕pt',10),('G1全玉予算目標円',1)):need(type(condition[name]) is int and condition[name]==wanted,'固定数量/費用差:'+name)
    groups=[condition['コードと依存SHA256']]
    for version in range(80,91):
        key=f'固定{version}依存';need(condition[key]==reference[key+'指紋'],'固定依存集合差:'+key);groups.append(condition[key])
    old=reference['旧条件SHA256'];need(len(old)==11 and {int(Path(n).parent.name[2:5]) for n in old}==set(range(80,91)),'旧11条件集合差')
    groups.append(old)
    for label in ('旧90保存','旧89基準保存'):
        need(reference[label+'一致数']==len(reference[label+'SHA256'])>0,'旧保存指紋数差');groups.append(reference[label+'SHA256'])
    groups.append({condition['実行ファイル']:condition['実行ファイルSHA256']})
    checked={};market=Path(read_json(manifest)['source_root']).resolve()
    for group in groups:
        need(type(group) is dict and bool(group),'固定依存空')
        for name,wanted in group.items():
            p=Path(name);p=(p if p.is_absolute() else ROOT/p).resolve()
            need(not p.is_relative_to(market) and re.fullmatch('[0-9a-f]{64}',wanted) is not None and sha(p)==wanted,'固定依存変更/市場参照:'+name)
            need(str(p) not in checked or checked[str(p)]==wanted,'依存指紋矛盾');checked[str(p)]=wanted
    return checked


def verify_two_layers(diagnostics: dict, result: dict) -> None:
    """
    機能: 参照親と実位置を分けた二比較の全寄与を正本へ照合する。
    引数: diagnostics/result(dict)は実玉と全比較。
    返り値: None。同実0、同ref複数玉、役割交差を失わない。
    """
    expected_names={f'R1対R0_D{d}' for d in (0,1)}
    need(set(result['出口間の同実新規分解'])==expected_names,'比較集合差')
    for delay in (0,1):
        keys=[f'R{m}_D{delay}' for m in (0,1)]
        expected=participation_decomposition(*[list(diagnostics[k].values()) for k in keys]);actual=result['出口間の同実新規分解'][f'R1対R0_D{delay}']
        need(actual=={'比較':keys,**expected},'多重集合の同実/同ref未一致/ref片側/役割分解差')
        need(expected['全差円']==number(result['比較'][keys[1]]['費用後損益円'])-number(result['比較'][keys[0]]['費用後損益円']),'政策全差と実参加総額差')


def verify_shared_statistics(shared_rows: list[dict], result: dict) -> dict:
    """
    機能: 全元poolの外資格・供給・現在check・trace種別・利益原行を再集計する。
    引数: shared_rows(list[dict])、result(dict)は共有gzと正本。
    返り値: dictは外資格集計。供給後の金融候補分母と分ける。
    """
    availability={};checks={};kinds=Counter();contexts=0
    for policy in POLICIES:
        pool=[p for scene in shared_rows for g in scene['grid_decisions'] for p in g['policies'][policy]['pool']]
        availability[policy]={'原pool延べ候補':len(pool),'資格既知':sum(p['known'] for p in pool),'資格成立':sum(p['allowed'] for p in pool),
                              '必須未知':sum(p['required_unknown'] for p in pool),'理由':dict(Counter(p['reason'] for p in pool)),
                              '供給延べID':sum(len(g['policies'][policy]['supplied_ids']) for s in shared_rows for g in s['grid_decisions'])}
    for scene in shared_rows:
        kinds.update(r['kind'] for r in scene['entry_observations']);contexts+=len(scene['profit_contexts'])
        for grid in scene['grid_decisions']:
            for d in grid['entry']['directions']:
                need(not d['e1_allowed'] or d['e0_allowed'],'E1がE0現在資格を迂回')
                for check in d['checks']:
                    row=checks.setdefault(check['id'],dict.fromkeys(('方向','既知','成立','未知'),0))
                    for name,value in (('方向',1),('既知',check['known']),('成立',check['passed']),('未知',not check['known'])):row[name]+=value
    need(availability==result['外資格と供給'] and checks==result['現在資格項目'],'全元pool外資格/供給又は現在check集計差')
    need(dict(kinds)==result['履歴入力種別'] and contexts==result['利益初回原行数'],'trace種別/初回利益原行数差')
    return availability


def derived_policy_actions(book: dict, shared: dict, policy: str, entry_bindings: list[dict], key: str, diagnostics: dict) -> dict:
    """
    機能: 金融待ちに限り全元poolの必要未知を履歴資格別に分類する。
    引数: book/shared/diagnostics(dict)、policy/key(str)、entry_bindings(list)は三保存系統。
    返り値: dictは政策判断件数。実金融actionへ書き戻さない。
    """
    counts=Counter()
    for decision,grid in zip(book['decisions'],shared['grid_decisions'],strict=True):
        action=decision['action']
        if action=='待ち' and grid['clock_allowed'] and not decision['source_context']['occupied']:
            at=grid['at'];q=grid['c0']['base']['quote'];seen={b['reference_id'] for b in entry_bindings if b['book_key']==key and b['at']<at};raw=set()
            for row in grid['source']['lots']:
                p=row['reference'];identity=p['id']
                if p['closing']:continue
                if identity not in seen:raw.add(identity);continue
                if key.startswith('R0_'):continue
                earlier=[r for r in diagnostics[key].values() if r['session']==shared['session'] and r['lot']['reference_id']==identity and r['lot']['entry_time']<=at and r['lot']['entry_line']<=q['line']]
                if not earlier:continue
                last=max(earlier,key=lambda r:(r['lot']['entry_time'],r['lot']['entry_index'],r['lot']['entry_line'],r['lot']['id']))
                closed=[c for c in last['closed'] if c['exit_time']<=at and c['exit_line']<=q['line']]
                if sum(c['quantity'] for c in closed)==last['lot']['initial_quantity'] and sum(c['pnl5'] for c in closed)>0:raw.add(identity)
            source=grid['source'];quality=q['valid'] and q['last']>0 and 0<q['bid']<q['ask'] and q['index']>=0 and q['line']>0 and 0<=at-q['time']<=15 and source['started'] and source['at']==q['time']
            if raw and (not quality or any(p['required_unknown'] for p in grid['policies'][policy]['pool'] if p['reference_id'] in raw)):action='判定不能'
        counts[action]+=1
    return dict(counts)


def verify_entry_audit(paths: dict, values: dict, result: dict, rows: dict, shared_rows: list[dict], source_rows: list[dict], trade_rows: list[dict], diagnostics: dict, sessions: list[str]) -> dict:
    """
    機能: 旧R0金融132/C02442保存証拠を3gzと全264金融判断へ直接結ぶ。
    引数: paths/values/result/rows/diagnostics(dict)、各rows/sessions(list)は13明示正本。
    返り値: dictは全場の共有/供給/通知/外binding観測。
    """
    proof=values['entry_audit']
    need(proof['試行']==91 and proof['成功'] is True and proof['処理完了'] is True and proof['入力不変'] is True,'保存監査未完')
    need((proof['場数'],proof['基準C0枠'],proof['基準会計'],proof['保存会計'])==(66,2442,132,264) and proof['不一致数']==0 and not proof['不一致'] and count(proof['照合項目数'])>0,'全保存/旧金融/C0対象差')
    need(proof['照合コードSHA256']==SAVED_SHA and proof['イベント照合コードSHA256']==EVENT_SHA and proof['読取helperSHA256']==SAVED.OLD_SHA,'保存停止コード/依存差')
    before=proof['入力SHA256前'];need(set(before)=={'91','89'} and before==proof['入力SHA256後'] and before['91']==result['再生結果SHA256'],'保存入力前後指紋差')
    old_result=read_json(ROOT/'study/00089_最低建値床を共通にした収穫配分の比較/成果物/結果.json')
    need(before['89']==old_result['再生結果SHA256'],'旧89基準66再生の本文指紋差')
    for name,wanted in proof['固定小型入力SHA256'].items():need(sha(ROOT/name)==wanted,'保存小型依存変更:'+name)
    scene_map={r['場']:r for r in proof['対象場']};gmap={r['session']:r for r in shared_rows};smap={r['session']:r for r in source_rows}
    need(len(scene_map)==len(gmap)==len(smap)==len(proof['対象場'])==len(source_rows)==len(shared_rows)==66 and set(gmap)==set(smap)==set(scene_map)==set(sessions),'共有/全Book/保存66場集合差')
    effects={key:[] for key in KEYS};equivalence=Counter();observed={key:{'全定時':0,'占有定時':0,'pool候補数':0,'適格候補数':0,'既取得候補数':0,'選定候補数':0,'候補未知数':0,'候補理由':Counter()} for key in KEYS}
    for session in sessions:
        scene,shared,source=scene_map[session],gmap[session],smap[session]
        need((scene['保存会計'],scene['基準会計'],scene['基準C0枠'])==(4,2,len(shared['grid_decisions'])),'保存場別対象差')
        need(scene['共有判断SHA256']==SAVED.canonical_sha({k:v for k,v in shared.items() if k!='session'}),'共有trace/seed/利益/EOF/全grid canonical差')
        need(set(source)=={'session','books','entry_bindings'} and set(source['books'])==set(KEYS) and scene['参照判断と通知効果SHA256']==SAVED.canonical_sha(source),'全Book/外binding canonical差')
        audit=SAVED.BASE.Audit();SAVED.inspect_events(shared,audit,session);levels=SAVED.inspect_opportunities(shared,audit,session);need(scene['再参加機会候補']==len(levels),'再参加機会候補数差');need(audit.bad==0,'共有gzの独立event/公開出典再構成差:'+str(audit.examples[:2]))
        eq=shared['source_equivalence'];need(scene['Source互換']==eq and eq['mismatches']==0 and eq['current_sha256']==eq['legacy_sha256'] and re.fullmatch('[0-9a-f]{64}',eq['current_sha256']) is not None,'Source全frame二指紋差')
        equivalence.update({k:eq[k] for k in ('step_frames','force_frames','grid_frames','mismatches')})
        need(scene['Technical互換']==shared['technical_equivalence'] and scene['イベント入力']==len(shared['entry_observations']) and scene['外新規binding']==len(source['entry_bindings']),'新Technical/trace/外binding件数差')
        need(shared['technical_equivalence']['mismatches']==0 and shared['technical_equivalence']['actual_sha256']==shared['technical_equivalence']['event_sha256'] and re.fullmatch('[0-9a-f]{64}',shared['technical_equivalence']['actual_sha256']) is not None,'Technical全call二指紋差')
        virtual={'books':{},'grid_decisions':shared['grid_decisions'],'profit_contexts':shared['profit_contexts']}
        for key in KEYS:
            chosen=[r for r in trade_rows if r['session']==session and r['key']==key]
            need(scene['玉診断SHA256'][key]==SAVED.canonical_sha(chosen),'玉/注文/返済片のcanonical差')
            book=source['books'][key];need(set(book)=={'source_policy','decisions','source_effects'} and book['source_policy']=='S','全Bookの内部Source政策差')
            need([d['at'] for d in book['decisions']]==[g['at'] for g in shared['grid_decisions']],'全Book定時順差')
            financial=dict(Counter(d['action'] for d in book['decisions']));policy=derived_policy_actions(book,shared,'E1',source['entry_bindings'],key,diagnostics)
            need(financial==rows[session,key]['判断'] and policy==rows[session,key]['方針判断'],'金融判断/外政策未知の独立分類差')
            action=next(a for a in scene['方針判断'] if a['key']==key);need(action['金融判断']==financial and action['方針判断']==policy,'保存証拠の二判断差')
            item=observed[key];item['全定時']+=len(book['decisions']);item['占有定時']+=sum(d['source_context']['occupied'] for d in book['decisions'])
            for decision in book['decisions']:
                for candidate in decision['candidates']:
                    check=candidate['source_check'];item['pool候補数']+=1;item['候補理由'][check['reason']]+=1
                    for dest,field in (('適格候補数','eligible'),('既取得候補数','seen'),('選定候補数','selected'),('候補未知数','required_unknown')):item[dest]+=check[field]
            effect=book['source_effects'];effects[key]+=effect
            summary={'通知':len(effect),'0作用':sum(e['cancelled']==e['exit_requested']==0 for e in effect),'取消枚':sum(e['cancelled'] for e in effect),'返済要求枚':sum(e['exit_requested'] for e in effect),'timer通知':sum(e['origin']=='timer' for e in effect)}
            need(scene['Source通知適用'][key]==summary,'Source通知作用の保存合計差')
            virtual['books'][key]={'lots':[r['lot'] for r in chosen],'closed':[c for r in chosen for c in r['closed']]}
        audit=SAVED.BASE.Audit();profit=SAVED.inspect_profit_contexts(virtual,audit,session)
        need(audit.bad==0 and profit==scene['初回利益観測'],'利益初回全trigger/全fill後の独立再計算差')
        verify_bindings(shared,source,diagnostics,session)
    need(dict(equivalence)==proof['Source互換件数'] and equivalence['grid_frames']==2442,'Source全件数の集計差')
    need(observed==result['参照poolと実採用'],'供給後金融候補の分母差')
    for key in KEYS:
        s=result['比較'][key];local=effects[key]
        need((s['Source通知数'],s['Source要求枚数'],s['Source取消枚数'])==(len(local),sum(e['exit_requested'] for e in local),sum(e['cancelled'] for e in local)),'Source全量/取消/通知数差')
    return {'shared':gmap,'source_rows':smap,'effects':effects,'availability':observed,'equivalence':dict(equivalence)}


def verify_bindings(shared: dict, source: dict, diagnostics: dict, session: str) -> None:
    """
    機能: 受理注文ID/実位置IDごとに外bindingと機会assessmentを一意に結ぶ。
    引数: shared/source/diagnostics(dict)、session(str)は保存三系統と場。
    返り値: None。同refの世代と未取得取消要求を区別する。
    """
    bindings=source['entry_bindings'];by={(b['book_key'],b['at']):b for b in bindings};need(len(by)==len(bindings),'外binding会計/定時重複')
    need(len({(b['book_key'],b['entry_order_id']) for b in bindings})==len(bindings),'受理注文ID重複')
    accepted={};expected=[]
    for level in shared['entry_opportunities']:
        for key,a in level['assessments'].items():
            if a['selected']:
                need(a['consumed'] and a['at']==level['at'] and a['reference_id']==level['reference_id'],'受理機会の消費/親結合差')
                token=key,a['entry_order_id'];need(token not in accepted,'受理機会の注文重複');accepted[token]=a
    for g in shared['grid_decisions']:
        for key in KEYS:
            token=key,g['at'];d=next(d for d in source['books'][key]['decisions'] if d['at']==g['at'])
            if d['action']!='新規要求':need(token not in by,'非受理へbinding創作');continue
            need(token in by,'受理binding欠落');b=by[token];delay=int(key[-1]);identity=d['source_context']['selected_id']
            need(set(b)==SAVED.ENTRY_BIND_FIELDS and b['policy']=='E1' and b['delay_seconds']==delay,'外binding型/政策差')
            p=next(p for p in g['policies']['E1']['pool'] if p['reference_id']==identity);ref=next(r['reference'] for r in g['source']['lots'] if r['reference']['id']==identity);direction=next(d for d in g['entry']['directions'] if d['side']==ref['side'])
            need(b['reference_id']==identity and b['requested_quantity']==min(100,ref['quantity']) and b['raw_rank']==p['raw_rank'] and b['supplied_rank']==p['supplied_rank'] and b['pool_evaluation']==p and b['current_qualification']==direction,'受理量/二順位/資格の凍結差')
            need((b['source_method'],b['source_at'],b['source_index'])==(g['source']['method'],g['source']['at'],g['source']['source_index']),'Source出典差')
            a=accepted.get((key,b['entry_order_id']))
            if key.startswith('R1_'):need(a is not None and (a['at'],a['reference_id'],a['position_id'])==(b['at'],identity,b['position_id']),'R1受理assessmentとbinding差')
            else:need(a is None,'R0へ再参加機会を使用')
            row=diagnostics[key].get((session,b['position_id']))
            if row is not None:
                o=row['entry_order'];need((o['id'],o['position_id'],o['quantity'],o['request_time'])==(b['entry_order_id'],b['position_id'],b['requested_quantity'],b['at']),'実位置の要求binding差')
                if a is not None:need((row['entry_role'],row['opportunity_id'],row['accepted_serial'])==(a['role'],a['opportunity_id'],a['accepted_serial']),'実役割/機会/serialを別世代から転記')
            expected.append(token)
    need(set(expected)==set(by) and set(accepted)=={(b['book_key'],b['entry_order_id']) for b in bindings if b['book_key'].startswith('R1_')},'全受理要求と機会/外bindingの集合差')


def verify_source_audit(paths: dict, values: dict, result: dict, source: dict, sessions: list[str]) -> None:
    """
    機能: Sourceと新eventの一走査証拠を全共有/全効果/利益/原板SHAへ結ぶ。
    引数: paths/values/result/source(dict)、sessions(list[str])は13明示入力。
    返り値: None。元指標/Source全戦略を独立再実装したとはしない。
    """
    p=values['source_audit'];need(p['試行']==91 and p['成功'] is True and p['処理完了'] is True and p['入力前後不変'] is True,'Source/event原板未完')
    need((p['場数'],p['会計数'],p['不一致数'])==(66,264,0) and not p['不一致'] and count(p['照合項目数'])>0,'Source/event全対象差')
    need(sha(Path(__file__).with_name('Source通知監査.py'))==SOURCE_SHA and p['イベント原板コードSHA256']==sha(ROOT/'scripts/FAR背景維持と押戻し再開/イベント原板結合.py')==RAW_EVENT_SHA and p['イベント保存コードSHA256']==EVENT_SHA,'Source/event停止コード差')
    need('訂正' not in p and p['監査コードSHA256']==SOURCE_SHA,'旧失敗訂正proof又はSourceコード差')
    need(p['固定88通知監査SHA256']==sha(ROOT/'scripts/FAR背景維持と押戻し再開/Source通知監査.py') and p['固定88所有ID比較SHA256']==sha(ROOT/'scripts/FAR背景維持と押戻し再開/Source所有順の照合.py'),'Source固定88依存差')
    need(all(r.get('Source生成全面同値計測') is True for r in p['対象場']),'市場証拠へ未計測人工scopeを混入')
    need(p['固定87通知監査SHA256']==sha(ROOT/'scripts/FAR参照玉と可変数量の比較/Source通知監査.py') and p['固定80監査SHA256']==sha(ROOT/'scripts/FAR後期15分移植/原板照合.py'),'Source固定読取依存差')
    need(p['入力台帳SHA256']==p['入力台帳SHA256前']==p['入力台帳SHA256後']==sha(paths['manifest']) and p['原板本文走査回数毎場']==1,'Source台帳/一走査差')
    records={r['session']:r for r in p['対象場']};need(len(records)==len(p['対象場'])==66 and set(records)==set(sessions),'Source/event原板66場集合差')
    ledger={e['id']:e for e in values['manifest']['sessions']};summary=Counter();events=notifications=effects=trace_count=profit_count=calls=0
    for session in sessions:
        row,shared,book_rows=records[session],source['shared'][session],source['source_rows'][session]['books']
        need(row['入力前後不変'] is True and row['会計数']==4 and row['不一致数']==0 and not row['不一致'],'Source場別未完')
        need(row['再生結果SHA256']==row['再生結果SHA256前']==row['再生結果SHA256後']==result['再生結果SHA256'][session+'.json'],'Sourceの保存本文前後SHA差')
        need(row['原板SHA256前']==row['原板SHA256後']==ledger[session]['files']['NK225_book']['sha256'] and row['source_equivalence']==shared['source_equivalence'],'Source原板前後/元二hash差')
        n_events=len(shared['source_events']);n_notifications=sum(len(e['closes']) for e in shared['source_events']);n_effects=sum(len(b['source_effects']) for b in book_rows.values())
        need((row['Sourceイベント数'],row['Source通知数'],row['Source効果数'])==(n_events,n_notifications,n_effects),'Sourceイベント/通知/作用件数差')
        accounts={a['会計']:a for a in row['各会計通知要約']};need(len(accounts)==len(row['各会計通知要約'])==4 and set(accounts)==set(KEYS),'Source四会計集合差')
        for key,a in accounts.items():
            local=book_rows[key]['source_effects'];need(a['通知']==len(local) and a['取消枚数']==sum(e['cancelled'] for e in local) and a['返済要求枚数']==sum(e['exit_requested'] for e in local) and a['0作用通知']==sum(e['cancelled']==e['exit_requested']==0 for e in local) and a['未解消会計']==0,'Source原板と保存作用差')
            summary.update({k:v for k,v in a.items() if k!='会計'})
        detail=row['入口足原板結合'];tech=shared['technical_equivalence']
        need(detail['処理完了'] is True and detail['原板結合trace']==len(shared['entry_observations']) and detail['利益snapshot']==len(shared['profit_contexts']) and detail['入力終端']==shared['input_end'],'入口trace/利益/EOFの原板結合差')
        need(detail['内訳'].get('core_timer',0)==tech['core_calls'] and detail['内訳'].get('quote',0)==tech['quote_calls']==result['入力品質'][session]['NK225']['accepted'],'全clock/quoteと原板/Go計測件数差')
        need(detail['全call']==tech['core_calls']+tech['quote_calls']+detail['内訳']['three_timer'],'全callの段階分解差')
        events+=n_events;notifications+=n_notifications;effects+=n_effects;trace_count+=len(shared['entry_observations']);profit_count+=len(shared['profit_contexts']);calls+=detail['全call']
    need((p['Sourceイベント数'],p['Source通知数'],p['Source効果数'])==(events,notifications,effects) and p['要約']==dict(summary),'Source原板の全場集計差')
    need(p['入口足原板結合']=={'場数':66,'原板結合trace':trace_count,'利益snapshot':profit_count,'全call':calls},'入口足/利益原板の全場件数差')


def replace_marker(text: str, block: str) -> str:
    """
    機能: 事前設定の結果マーカー内だけを置換する。
    引数: text/block(str)は既存全文と新結果。
    返り値: strはマーカー外が不変の全文。
    """
    need(text.count(BEGIN)==text.count(END)==1,'設定結果マーカーの不足/重複')
    before,tail=text.split(BEGIN,1);_,after=tail.split(END,1)
    return before+BEGIN+'\n'+block.rstrip()+'\n'+END+after


def restore_original_order(text: str) -> str:
    """
    機能: 91事前表の元順をそのまま本文指紋へ結ぶ。
    引数: text(str)は結果を事前文へ復元した表。
    返り値: strは元本文。91は表示順訂正を行わない。
    """
    need(hashlib.sha256(text.encode('utf-8')).hexdigest()==PRETABLE_SHA,'91事前表の固定本文差')
    return text


def prepare(paths: dict, study: Path) -> dict:
    """
    機能: 13明示正本を一意に読み、全会計・保存・原板・Viewerと固定依存を照合する。
    引数: paths(dict[str,Path])、study(Path)は明示入力と今回の試行。
    返り値: dictは帳票用検査済値。市場再生/新API取得0。
    """
    required={'result','catalog','cash_audit','raw_audit','source_audit','viewer_audit','condition','input_reference','manifest','trades','grids','source_decisions','entry_audit'}
    need(set(paths)==required and len({str(p.resolve()).casefold() for p in paths.values()})==13,'13明示入力の不足/余剰/重複')
    hashes={str(p.resolve()):sha(p) for p in paths.values()}
    values={name:read_json(p) for name,p in paths.items() if name not in ('trades','grids','source_decisions')}
    sessions=[s['id'] for s in values['manifest']['sessions']];need(len(sessions)==len(set(sessions))==66,'固定一意66場が必要')
    dependencies=fixed_dependencies(values['condition'],values['input_reference'],paths['manifest'])
    result=values['result'];need(result['入力台帳SHA256']==sha(paths['manifest']),'結果の入力台帳SHA差')
    rows=verify_summary(result,sessions);trade_rows=compressed_rows(paths['trades'])
    diagnostics=verify_diagnostics(trade_rows,result,sessions);verify_two_layers(diagnostics,result)
    shared_rows=compressed_rows(paths['grids']);source_rows=compressed_rows(paths['source_decisions'])
    availability,stats,pool=verify_grids(shared_rows,result,diagnostics,sessions)
    outer=verify_shared_statistics(shared_rows,result)
    normative=verify_audits(paths,values,result,rows,diagnostics,sessions)
    source=verify_entry_audit(paths,values,result,rows,shared_rows,source_rows,trade_rows,diagnostics,sessions)
    verify_source_audit(paths,values,result,source,sessions);verify_exports(paths,values['catalog'],diagnostics,sessions)
    declared={str((ROOT/name).resolve()):wanted for name,wanted in values['entry_audit']['固定小型入力SHA256'].items()}
    for name,wanted in declared.items():
        need(str(Path(name).resolve()) not in dependencies or dependencies[str(Path(name).resolve())]==wanted,'宣言済観測依存の矛盾SHA')
        need(sha(Path(name))==wanted,'宣言済観測依存の本文差');dependencies[str(Path(name).resolve())]=wanted
    quantities,observations=verify_source_totals(diagnostics,result)
    text=(study/'設定と結果.md').read_text(encoding='utf-8');verify_table(text,study)
    corrected=replace_marker(text,PRE_BLOCK);restored=restore_original_order(corrected)
    need(hashlib.sha256(restored.encode('utf-8')).hexdigest()==values['condition']['事前設定表SHA256'],'事前表のマーカー外又は数値表が固定後に変化')
    need({str(p.resolve()):sha(p) for p in paths.values()}==hashes,'13入力読取中の変更')
    need(all(sha(Path(p))==wanted for p,wanted in dependencies.items()),'依存読取中の変更')
    return {'result':result,'values':values,'paths':paths,'sessions':sessions,'input_sha':hashes,'dependencies':dependencies,'settings':text,
            'rows':rows,'diagnostics':diagnostics,'source':source,'outer':outer,'availability':availability,'stats':stats,'pool':pool,'normative':normative,
            'quantities':quantities,'observations':observations}


def result_block(data: dict) -> str:
    """
    機能: 四会計の費用後純額と実参加/正益分母を表示する。
    引数: data(dict)は検査済13正本。
    返り値: strは設定マーカー内の結果。
    """
    lines=['全66場・既使用期間。以下は固定済み条件の実行結果。','',
      '| 会計 | 費用後円 | 最大DD円 | 赤字場 | 実参加/実枚 | 全玉正益後赤字 | 残玉正益後赤字 |',
      '| --- | ---: | ---: | ---: | --- | --- | --- |']
    for key in KEYS:
        s=data['result']['比較'][key];lines.append(f"| {key} | {amount(s['費用後損益円'])} | {amount(s['最大DD円'])} | {s['赤字場数']}/66 | {s['完結玉']}/{s['新規枚数']} | {ratio(s['全玉旗後赤字'],s['全玉旗'])} | {ratio(s['残玉旗後赤字'],s['残玉旗'])} |")
    return '\n'.join(lines+['','R0は恒久seenの旧89 E1/G1、R1は利確完了後の別eventへ再参加。初参加の取得変更と追加参加を分け、既使用期間の成績を安定利益の証明にしない。'])


def render_readme(data: dict, study: Path) -> str:
    """
    機能: 利確後再参加の仮説・結果・分解・根拠を簡潔な正本案内へ生成する。
    引数: data(dict)、study(Path)は検査済入力と今回試行。
    返り値: strはREADME本文。再現補足はRoot所有。
    """
    result=data['result'];v=data['values']
    lines=['# 00091：利確完了後の新しい再開へ再参加','','2026-11-08。固定89のE1入口・G1配分を維持し、恒久seenのR0と、直近の実参加が費用後strict正で全返済した後だけ新しいE1のp/r/k公開へ再参加するR1を比較した。全66場は既使用。','',result_block(data),'',
      '現在資格は複数時間軸のEMA/MACD/RSI/ATRと背景→推進→押し→回復→勢い確認を毎回要求する。過去の利確は履歴資格であり現在方向の証拠ではない。freshを同枠で優先し、一枠一要求・同時一玉・Source現量以内のcap100を維持する。','',
      '同じ(session,ref,event)は受理時に永久消費し、取消でも再利用しない。0取得取消は実世代を作らず、別eventなら直近実利確を再検討できる。後の実取得世代が損失又は同値なら昔の勝ちへ戻らない。','',
      '売買は符号反転の同条件。費用控除後の現在単価益strict正で最低建値床を起動し、G1部分収穫・実確定益cash床・ATR/125pt/3分失敗/Source連続返済を維持する。往復122円/実枚（片道手数料11円＋滑り5pt）、D0次正常行・D1追加価格時計1秒。ラージ板のmicro代理約定。','',
      '| 比較 | 同参照 | 同実参加 | 同ref未一致 R0/R1 | ref片側 R0/R1 | 同実出口差円 | 全差円 |','| --- | ---: | ---: | --- | --- | ---: | ---: |']
    for delay in (0,1):
        d=result['出口間の同実新規分解'][f'R1対R0_D{delay}'];lines.append(f"| R1対R0_D{delay} | {d['同参照ID']} | {d['同実新規']} | {d['同ref未一致A']}/{d['同ref未一致B']} | {d['ref片側A']}/{d['ref片側B']} | {amount(d['同実新規出口差円'])} | {amount(d['全差円'])} |")
    lines+=['','要求時刻・方向・実取得時計・価格・量の完全一致だけを多重集合で対応させる。参照ID一件への集約や順番による強制対応はしない。全差は同実出口差＋同ref未一致B−A＋ref片側B−Aで、実役割の組合せも保存する。正益分母の減少や少数の再参加だけで保全改善とはしない。','',
      f"旧89 R0全132 Book全文・全2442枠と新264会計の保存照合{v['entry_audit']['照合項目数']:,}、金融原板{v['raw_audit']['照合項目数']:,}、Source/event原板{v['source_audit']['照合項目数']:,}項目は差0。Viewer264資源も全件照合済み。原板は計2走査。完結IndexはSource原板で独立復元し、元指標前史とSource生成は固定数値器・seed・元driver同値へ依存する。",'',
      '[計画](検証計画.md) / [全設定と結果](設定と結果.md) / [再現補足・13入力CLI](再現補足.md) / [コード](../../scripts/FAR利確完了後の新event再参加/README.md) / [損益比較図](損益比較.svg)','']
    for name,label in (('result','結果正本'),('catalog','Viewer一覧'),('cash_audit','会計照合'),('raw_audit','金融原板'),('source_audit','Sourceとevent原板'),('viewer_audit','Viewer照合'),('condition','固定条件'),('input_reference','入力参照'),('manifest','固定台帳'),('trades','玉診断gz'),('grids','定時・公開機会・trace・利益gz'),('source_decisions','金融判断・通知・外binding gz'),('entry_audit','基準と保存判断')):lines.append('- '+link(study,data['paths'][name],label))
    lines+=['','[再現補足](再現補足.md)の13明示入力で--run後に--check。市場/原板/APIの再実行は0。[生成証拠](レポート生成証拠.json)に入力・依存・R・出力SHAを保存する。','']
    return '\n'.join(lines)+'\n'


def generate(paths: dict, study: Path, check: bool) -> dict:
    """
    機能: 正本全照合後にREADME・マーカー内・生成証拠だけを生成又は照合する。
    引数: paths(dict)、study(Path)、check(bool)は13入力・今回試行・照合指定。
    返り値: dictは生成証拠。入力とマーカー外を変更しない。
    """
    data=prepare(paths,study);before=data['settings'];settings=replace_marker(before,result_block(data));readme=render_readme(data,study)
    outputs={study/'README.md':readme,study/'設定と結果.md':settings}
    proof={'試行':91,'成功':True,'場数':66,'会計数':264,'Viewer資源数':264,'明示入力数':13,
           '入力':{name:str(p.resolve()) for name,p in paths.items()},'入力SHA256':data['input_sha'],'固定依存SHA256':data['dependencies'],
           '生成コードSHA256':sha(Path(__file__)),'保存コードSHA256':SAVED_SHA,'金融固定コード数':len(data['values']['condition']['コードと依存SHA256']),'出力SHA256':{p.name:hashlib.sha256(t.encode('utf-8')).hexdigest() for p,t in outputs.items()},
           '事前表SHA256':data['values']['condition']['事前設定表SHA256'],'設定マーカー外不変':replace_marker(before,'')==replace_marker(settings,''),
           '版5表':{'手法':55,'尺度':9,'セル':495,'基礎設定':37,'再参加設定':2,'全設定':39,'複合評価':4,'表示順訂正':False},
           '新市場再生':0,'新API取得':0}
    outputs[study/'レポート生成証拠.json']=json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if check:
        for p,t in outputs.items():need(p.is_file() and p.read_text(encoding='utf-8')==t,'生成内容不一致:'+p.name)
    else:
        for p,t in outputs.items():p.write_text(t,encoding='utf-8',newline='\n')
    need({str(p.resolve()):sha(p) for p in paths.values()}==data['input_sha'],'生成前後で13入力が変化')
    need(all(sha(Path(p))==wanted for p,wanted in data['dependencies'].items()),'生成前後で固定依存が変化')
    need(replace_marker(before,'')==replace_marker((study/'設定と結果.md').read_text(encoding='utf-8'),''),'設定マーカー外を変更')
    return proof


def self_test() -> dict:
    """
    機能: 同ref複数世代・役割交差・片側参照・完全一致の多重性を反証する。
    引数: なし。局所非0人工だけを作る。
    返り値: dictは人工件数と事前表検査。市場/APIは実行しない。
    """
    def row(pid: str, ref: str, request: int, net: int, role: str) -> dict:
        """
        機能: 比較専用の経済的な実参加を作る。
        引数: pid/ref/role(str)、request/net(int)は人工の所有・入口・純額。
        返り値: dictは実参加の最小診断。
        """
        return {'session':'人工場','lot':{'id':pid,'reference_id':ref,'side':1,'entry_time':request+1,'entry_price':40000,'initial_quantity':8,'net_pnl':net},'entry_order':{'request_time':request},'entry_role':role}
    a=[row('A1','X',1000,100,'初参加'),row('A2','X',1900,-200,'初参加'),row('A3','Y',1000,-300,'初参加'),row('A4','Q',1000,40,'初参加')]
    b=[row('B1','X',1000,-50,'利確後再参加'),row('B2','X',2800,500,'利確後再参加'),row('B3','Z',1000,60,'初参加'),row('B4','Q',1000,80,'初参加'),row('B5','Q',1000,90,'利確後再参加')]
    d=participation_decomposition(a,b)
    need((d['同参照ID'],d['同実新規'],d['同ref未一致A'],d['同ref未一致B'],d['ref片側A'],d['ref片側B'])==(2,2,1,2,1,1),'多重集合人工の期待数差')
    diagnostics={k:{} for k in KEYS};result={'比較':{},'出口間の同実新規分解':{}}
    for delay in (0,1):
        for mode,rows in (('R0',a),('R1',b)):
            key=f'{mode}_D{delay}';diagnostics[key]={(r['session'],r['lot']['id']):r for r in rows};result['比較'][key]={'費用後損益円':sum(r['lot']['net_pnl'] for r in rows)}
        result['出口間の同実新規分解'][f'R1対R0_D{delay}']={'比較':[f'R0_D{delay}',f'R1_D{delay}'],**d}
    verify_two_layers(diagnostics,result);rejected=0
    for field in ('同参照ID','同実新規','同ref未一致B','ref片側A損益円','同実新規出口差円','全差円'):
        broken=deepcopy(result);broken['出口間の同実新規分解']['R1対R0_D0'][field]+=1
        try:verify_two_layers(diagnostics,broken)
        except ValueError:rejected+=1
    need(rejected==6,'分解破損を未検出')
    study=ROOT/'study/00091_利確完了後の新しい再開へ再参加';text=(study/'設定と結果.md').read_text(encoding='utf-8');verify_table(text,study);restore_original_order(replace_marker(text,PRE_BLOCK))
    definitions=text.split('## 37基礎設定の継承と2再参加設定\n',1)[1].split('\n## ',1)[0];ids=re.findall(r'^\| ([A-Z][0-9]{2}) \|',definitions,re.M)
    need(len(ids)==len(set(ids))==39 and ids[-2:]==['F01','F02'],'39設定差')
    need(replace_marker(text,'')==replace_marker(replace_marker(text,'人工結果'),''),'marker外変更')
    return {'成功':True,'非0会計':4,'実参加':18,'破損拒否':rejected,'版5':'55×9','設定':39,'複合':4,'事前表SHA256':PRETABLE_SHA,'市場再生':0,'API取得':0}


def participation_decomposition(left: list[dict], right: list[dict]) -> dict:
    """
    機能: 同参照の複数実参加を完全一致の多重集合と残差へ独立分解する。
    引数: left/right(list[dict])は位置ID一意の玉診断。
    返り値: dictは全額差と役割組合せ。異なる取得を順番で強制対応しない。
    """
    groups=[];refs=[]
    for rows in (left,right):
        need(len({(r['session'],r['lot']['id']) for r in rows})==len(rows),'実位置ID重複')
        by={};parents=set()
        for r in rows:
            p=r['lot'];need(p['initial_quantity']>0,'0取得要求を実参加へ混入')
            token=(r['session'],p['reference_id'],r['entry_order']['request_time'],p['side'],p['entry_time'],p['entry_price'],p['initial_quantity'])
            by.setdefault(token,[]).append(r);parents.add(token[:2])
        groups.append(by);refs.append(parents)
    common=refs[0]&refs[1];matches=[];rests=[[],[]]
    for token in sorted(set(groups[0])|set(groups[1])):
        a,b=[g.get(token,[]) for g in groups];n=min(len(a),len(b))
        matches.extend(zip(a[:n],b[:n],strict=True));rests[0].extend(a[n:]);rests[1].extend(b[n:])
    shared=[[r for r in rows if (r['session'],r['lot']['reference_id']) in common] for rows in rests]
    single=[[r for r in rows if (r['session'],r['lot']['reference_id']) not in common] for rows in rests]
    net=lambda rows:sum(number(r['lot']['net_pnl']) for r in rows)
    na,nb=net([a for a,b in matches]),net([b for a,b in matches])
    out={'同参照ID':len(common),'同実新規':len(matches),'同実新規A損益円':na,'同実新規B損益円':nb,'同実新規出口差円':nb-na,
         '同実役割組合せ':dict(Counter(a['entry_role']+'→'+b['entry_role'] for a,b in matches)),
         '同ref未一致A':len(shared[0]),'同ref未一致B':len(shared[1]),'同ref未一致A損益円':net(shared[0]),'同ref未一致B損益円':net(shared[1]),
         'ref片側A':len(single[0]),'ref片側B':len(single[1]),'ref片側A損益円':net(single[0]),'ref片側B損益円':net(single[1]),
         '同ref未一致A役割':dict(Counter(r['entry_role'] for r in shared[0])),'同ref未一致B役割':dict(Counter(r['entry_role'] for r in shared[1])),
         '全差円':net(right)-net(left)}
    need(out['全差円']==nb-na+net(shared[1])-net(shared[0])+net(single[1])-net(single[0]),'全額の寄与分解差')
    need(len(left)==len(matches)+len(rests[0]) and len(right)==len(matches)+len(rests[1]),'実参加の多重集合分母差')
    return out



def main() -> None:
    """
    機能: 明示13入力で正式帳票を作るか、一致を確認する。
    引数: --study/各正本(Path)、--run/--check/--self-test(bool)はCLI。
    返り値: None。未完/矛盾/既存固定条件変更は非0。
    """
    parser=argparse.ArgumentParser(description='91の13正本を結ぶ記録反映')
    parser.add_argument('--study',type=Path)
    names=('result','catalog','cash_audit','raw_audit','source_audit','viewer_audit','condition','input_reference','manifest','trades','grids','source_decisions','entry_audit')
    for name in names:parser.add_argument('--'+name.replace('_','-'),type=Path)
    modes=parser.add_mutually_exclusive_group(required=True)
    for mode in ('run','check','self-test'):modes.add_argument('--'+mode,action='store_true')
    args=parser.parse_args()
    if args.self_test:
        need(args.study is None and all(getattr(args,n) is None for n in names),'人工と正式入力を混在させない');print(json.dumps(self_test(),ensure_ascii=False));return
    need(args.study is not None and all(getattr(args,n) is not None for n in names),'studyと13正本はすべて明示必須')
    proof=generate({name:getattr(args,name).resolve() for name in names},args.study.resolve(),args.check)
    print(json.dumps({k:proof[k] for k in ('試行','成功','場数','会計数','Viewer資源数','明示入力数','設定マーカー外不変')},ensure_ascii=False))


if __name__=='__main__':main()
