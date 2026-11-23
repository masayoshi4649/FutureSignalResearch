"""00011の全入口先着・運用会計・場内DD・支持・表示選択を独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00011_順行と反転のチャート構造と利益回収"
WORK = ROOT / "work/テクニカル循環/00011"
PERIODS = ("学習", "条件選択", "後続検査")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def load(path: Path, name: str) -> Any:
    """独立監査・表示の補助だけを読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。00011の入口・運用・検証はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A = load(ROOT / "scripts/利益回収/運用独立監査.py", "循環の場内DD独立補助")
U = A.U
L = load(ROOT / "scripts/入口分析/独立照合.py", "循環の素朴先着照合")


def read(path: Path) -> Any:
    """日本語JSONを読む。

    引数: path (Path) は入力。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON値。
    返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")


def rows(path: Path) -> tuple[list[dict], str]:
    """gzipの展開本文をそのまま指紋化しJSONLへ分ける。

    引数: path (Path) は作業gzip。
    返り値: tuple[list[dict],str] は全行と展開SHA256。
    """
    digest, values = hashlib.sha256(), []
    with gzip.open(path, "rb") as stream:
        for line in stream:
            digest.update(line)
            if line.strip():
                values.append(json.loads(line))
    return values, digest.hexdigest()


class ExpectedTP:
    """共通会計監査の固定TP期待値だけをX0/通常出口の仕様へ分岐する。"""

    def __init__(self, audit: Any, fixed: bool) -> None:
        """比較先と固定TP使用を保持する。

        引数: audit (Any) は独立照合、fixed (bool) はX0か。
        返り値: None。保存値を加工しない。
        """
        self.audit, self.fixed = audit, fixed

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """固定TPがない出口の利確価格をNoneとして照合する。

        引数: name (str) は項目、actual/expected (Any) は値。
        返り値: None。他の会計・BBO・注文期待値は共通監査のまま。
        """
        self.audit.check(name, actual, None if name.endswith(":取引:利確価格") and not self.fixed else expected)


# ----------------------------------------
# 入口事例は区間木でなく全返済気配の直接比較で再ラベルする。

def basic(cases: list[dict]) -> dict:
    """先着5分類・全約定率・支持日数を独立集計する。

    引数: cases (list[dict]) は同一入口・期間。
    返り値: dict は件数率と集中度。
    """
    counts = Counter(r["ラベル"] for r in cases)
    filled = [r for r in cases if r["ラベル"] != "未約定"]
    success = Counter(r["場"][:10] for r in cases if r["ラベル"] == "順行先着")
    return {"候補数": len(cases), "約定候補数": len(filled), **{k: counts[k] for k in LABELS},
            "確認率": counts["順行先着"] / len(filled) if filled else None,
            "候補場数": len({r["場"] for r in cases}), "約定場数": len({r["場"] for r in filled}),
            "候補開始日数": len({r["場"][:10] for r in cases}), "約定開始日数": len({r["場"][:10] for r in filled}),
            "成功開始日数": len(success), "最大成功日寄与率": max(success.values()) / counts["順行先着"] if success else None}


def entry_metrics(cases: list[dict], period: str) -> dict:
    """要求時計だけの30分間引きと独立二項の参考区間を作る。

    引数: cases (list[dict]) は対象、period (str) は区分。
    返り値: dict は入口集計。ラベルで間引き起点を選ばない。
    """
    result = basic(cases)
    previous, kept = {}, []
    for index, r in sorted(enumerate(cases), key=lambda item: (Decimal(str(item[1]["要求時計秒"])), item[1]["要求原板行"], item[0])):
        key, clock = (r["場"], r["side"]), Decimal(str(r["要求時計秒"]))
        if key not in previous or clock - previous[key] >= 1800:
            previous[key] = clock
            kept.append(r)
    thin = basic(kept)
    result.update(分割=period)
    for key in ("候補数", "約定候補数", "順行先着", "確認率", "候補場数", "約定場数", "約定開始日数"):
        result["30分間引き_" + key] = thin[key]
    n, wins, z = result["約定候補数"], result["順行先着"], 1.959963984540054
    if n:
        ratio, scale = wins / n, 1 + z * z / n
        center = (ratio + z * z / (2 * n)) / scale
        radius = z * math.sqrt(ratio * (1 - ratio) / n + z * z / (4 * n * n)) / scale
        lower, upper = max(0, center - radius), min(1, center + radius)
    else:
        lower = upper = None
    result.update(Wilson95下限_独立参考=lower, Wilson95上限_独立参考=upper)
    return result


def entry_audit(cases: list[dict], result: dict, entries: dict, config: dict, audit: Any) -> dict:
    """全保存入口の先着を再計算し、8×3集計・支持・目標を照合する。

    引数: cases/result/entries/config は事例・保存結果・台帳・条件、audit (Any) は比較先。
    返り値: dict は入口別期間集計と照合範囲。
    """
    quote_cache, metrics, support_map, seen = {}, {}, {}, set()
    for r in cases:
        name = r["イベントID"]
        audit.check(name + ":入口一意", name not in seen, True)
        seen.add(name)
        session = r["場"]
        if session not in quote_cache:
            entry = entries[session]
            quote_cache[session] = L.load_quotes(ROOT / "work/複合検証" / entry["cache_path"], entry)
        q, source_clocks, quality = quote_cache[session]
        begin, end, cutoff, deadline = L.session_times(session)
        audit.check(name + ":要求原行時計", source_clocks[r["要求原板行"]], r["要求時計秒"])
        audit.check(name + ":上位終了", r["上位足終了秒"] <= r["足終了時計秒"], True)
        audit.check(name + ":上位確認順", (r["上位確認秒"], r["上位確認行"]) <= (r["要求時計秒"], r["要求原板行"]), True)
        audit.check(name + ":時間条件", r["要求時計秒"] < cutoff and deadline - r["要求時計秒"] >= 3600, True)
        if r["確認遅延秒"] > 30:
            expected = {"ラベル": "未約定", "理由": "足確定確認遅延30秒超", **{k: None for k in L.RESULT_NUMBERS}}
        else:
            expected = L.label_direct(q, r["要求時計秒"], cutoff, deadline, r["side"], adverse=125, favorable=250)
        for key, value in expected.items():
            audit.check(name + ":直接先着:" + key, r[key], value)
    for source in result["入口評価"]:
        name = source["入口ID"]
        by_period = {}
        for period in PERIODS:
            values = entry_metrics([r for r in cases if r["入口ID"] == name and r["期間"] == period], period)
            for key, value in values.items():
                audit.check(name + period + ":入口集計:" + key, source[period][key], value)
            metrics[(name, period)], by_period[period] = values, values
        supported = all(all(by_period[p][k] >= minimum for k, minimum in limits.items()) for p, limits in config["入口支持"].items())
        goal = supported and all(by_period[p]["確認率"] >= config["目標確認率"]
            and by_period[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
            and by_period[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        audit.check(name + ":入口支持", source["入口支持"], supported)
        audit.check(name + ":入口70目標", source["70目標"], goal)
        support_map[name] = supported, goal
    audit.check("入口目標達成数", result["入口70目標達成数"], sum(g for s, g in support_map.values()))
    return {"先着直接再判定件数": len(cases), "入口期間群": [{"入口ID": n, "期間": p, **m} for (n, p), m in metrics.items()],
            "支持": support_map, "限界": "保存入口の先着を全再判定。発動漏れの全原板再生成ではなく、入口式/時点は合成18件と少数独立足検査で別確認。"}


# ----------------------------------------
# 保存片のDecimal会計・DDを独立検算し、出口追加の期待値だけを明示分岐する。

def operation_metrics(rows: list[dict], role: str, variant: str) -> dict:
    """場別独立会計から床・ATR到達・単一場DDを集計する。

    引数: rows (list[dict]) は一候補・期間、role/variant (str) は役割・出口。
    返り値: dict は期間運用集計。期間累積DDを作ったとは主張しない。
    """
    result, trades = U.aggregate(rows), [t for r in rows for t in r["取引"]]
    floor = role == "反転" and variant == "X2"
    armed, unarmed = [t for t in trades if t["利益床起動"]], [t for t in trades if not t["利益床起動"]]
    result.update(期間内最大場内DD円=max((r["観測含み込み最大DD円"] for r in rows), default=0),
                  最悪場内時価円=min((r["観測最悪時価円"] for r in rows), default=0),
                  利益床使用=floor, 床起動取引数=len(armed), 床未起動取引数=len(unarmed) if floor else None,
                  床未起動赤字取引数=sum(t["基準純損益円"] < 0 for t in unarmed) if floor else None,
                  床未起動純損益円=sum(Decimal(str(t["基準純損益円"])) for t in unarmed) if floor else None,
                  床起動済純損益円=sum(Decimal(str(t["基準純損益円"])) for t in armed) if floor else None,
                  活動場赤字率=result["赤字場数"] / result["活動場数"] if result["活動場数"] else None,
                  中心線超過新規数=sum(r["中心線超過新規数"] for r in rows))
    for limit in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        result[f"{limit}pt到達取引"] = len(reached)
        result[f"{limit}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    reached = [t for t in trades if t["観測最大順行pt"] >= t["入口ATR"]]
    result.update(**{"1ATR到達取引": len(reached), "1ATR後純赤字": sum(t["基準純損益円"] < 0 for t in reached)})
    return result


def pair(base: list[dict], changed: list[dict]) -> dict:
    """共有する実新規と追加/欠落参加の純額を独立に集計する。

    引数: base/changed (list[dict]) はX0/変更取引。
    返り値: dict は件数・損益差。イベントだけ一致し約定価格が違う新規を共有扱いしない。
    """
    output = A.paired(base, changed)
    output["元黒字だった共通新規の純額差円"] = output.pop("元黒字を早く確定した純額差円")
    a = {(t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]): t for t in base}
    b = {(t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]): t for t in changed}
    output["元のみ純損益円"] = sum(Decimal(str(a[k]["基準純損益円"])) for k in a.keys() - b.keys())
    output["変更のみ純損益円"] = sum(Decimal(str(b[k]["基準純損益円"])) for k in b.keys() - a.keys())
    return output


def check_trade_path(detail: dict, q: dict, audit: Any) -> None:
    """全取引のMFE/MAEとX0要求初着を直接気配から検算する。

    引数: detail (dict) は一候補場、q (dict) は正常板、audit (Any) は比較先。
    返り値: None。X1/2の全要求再実装は別の代表出口確認へ分ける。
    """
    fixed = detail["候補ID"].endswith("_X0")
    for t in detail["取引"]:
        name = detail["候補ID"] + t["場"] + t["建玉ID"]
        first, last = q["at"][t["新規原板行"]], q["at"][t["返済原板行"]]
        side = 1 if t["方向"] == "買い" else -1
        marks = q["bid"] if side == 1 else q["ask"]
        d = side * (marks[first:last + 1] - t["新規価格"])
        audit.check(name + ":直接MFE", t["観測最大順行pt"], max(0, float(np.max(d))))
        audit.check(name + ":直接MAE", t["観測最大逆行pt"], max(0, float(-np.min(d))))
        audit.check(name + ":固定TP区分", t["固定利確使用"], fixed)
        if fixed:
            force = q["bounds"][3]
            eligible = (q["now"][first:last + 1] < force) & ((d <= -125) | (d >= 250))
            hit = np.flatnonzero(eligible)
            if len(hit):
                at = first + int(hit[0])
                expected = (float(q["now"][at]), int(q["line"][at]), "保護" if side * (marks[at] - t["新規価格"]) <= -125 else "利確")
            else:
                expected = (force, 0, "期限")
            audit.check(name + ":X0最初の返済要求", (t["返済要求時計秒"], t["返済要求原板行"], t["返済理由"]), expected)


def viewer(rows: list[dict], api: str, fixed: list[str], audit: Any) -> dict:
    """表示固定のX2と同場X0を代表2資源としてAPI照合する。

    引数: rows (list[dict]) は会計、api (str) は接続先、fixed (list[str]) は表示ID、
    audit (Any) は比較先。
    返り値: dict はAPI数値・指紋・帰属。PNGを追加しない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "循環のViewer補助")
    resources = {(r["method_id"], r["session"]): r for r in read(STUDY / "一覧.resources.json")["resources"]}
    response, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer:全資源集合", {r["id"] for r in json.loads(response)["resources"]}, {r["id"] for r in resources.values()})
    alternative = [r for r in rows if r["候補ID"] in fixed and not r["候補ID"].endswith("_X0")]
    selected = sorted(alternative, key=lambda r: (-abs(r["観測現金増減円"]), r["候補ID"], r["場"]))[0]
    source = selected["候補ID"].rsplit("_", 1)[0]
    checks = []
    for cid in (source + "_X0", selected["候補ID"]):
        row = next(r for r in rows if r["候補ID"] == cid and r["場"] == selected["場"])
        adapted = {"銘柄": "NK225", "場": row["場"], "手法": cid, "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
        item = helper.check_one(api, STUDY, adapted, resources[(cid, row["場"])], "表示固定通常出口の最大絶対観測損益場と同場X0", False)
        item.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
        checks.append(item)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
            "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden", "照合": checks, "追加PNG数": 0,
            "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
            "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"),
            "パス": "market_pathは設定data_root、pnl_pathはpath_base=catalogで一覧親基準。",
            "代表選択": "表示固定の通常出口から最大絶対観測損益、同値候補ID/場順。同場X0と比較。全65場既使用の事後表示。"}


def run(api: str | None) -> dict:
    """全24運用・8入口を監査して正式な明示合否を保存する。

    引数: api (str|None) はViewer接続先。
    返り値: dict は照合数と独立集計。旧研究・固定実装を変更しない。
    """
    audit, config, result = U.Audit(), read(STUDY / "条件.json"), read(STUDY / "結果.json")
    locked = read(STUDY / "固定.json")
    for path, expected in locked["ファイルSHA256"].items():
        audit.check("実行前固定後のSHA:" + path, U.sha(ROOT / path), expected)
    pointer = read(STUDY / "入力台帳.json")
    manifest = (STUDY / pointer["参照"]).resolve()
    audit.check("入力台帳参照SHA", U.sha(manifest), pointer["SHA256"])
    entries = {e["session"]: e for e in read(manifest)["entries"]}
    raw_details, detail_sha = rows(WORK / "全運用詳細.jsonl.gz")
    cases, case_sha = rows(WORK / "入口事例.jsonl.gz")
    contents = {str(WORK / "全運用詳細.jsonl.gz"): detail_sha, str(WORK / "入口事例.jsonl.gz"): case_sha}
    for item in read(STUDY / "作業成果物.json")["ファイル"]:
        path = ROOT / item["パス"]
        audit.check("作業展開SHA:" + str(path), contents[str(path)], item["展開内容SHA256"])
    entrance = entry_audit(cases, result, entries, config, audit)
    details, cached, op_rows = {}, {}, []
    case_map = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    for d in raw_details:
        cid, session = d["候補ID"], d["場"]
        if (cid, session) in details:
            raise ValueError("運用候補・場の重複")
        details[(cid, session)] = d
        if session not in cached:
            cached[session] = U.quotes(entries[session], True)
        q = cached[session]
        row = U.audit_session(d, q, ExpectedTP(audit, cid.endswith("_X0")))
        row.update(A.drawdown(d, q, audit), 中心線超過新規数=d["品質"]["中心線超過新規数"])
        op_rows.append(row)
        check_trade_path(d, q, audit)
        audit.check(cid + session + ":終了建玉0", row["終了建玉"], 0)
        audit.check(cid + session + ":終了返済待機0", row["終了返済待機"], 0)
        source = cid.rsplit("_", 1)[0]
        actual_ids = {s["イベントID"] for s in d["入口取扱"]}
        audit.check(cid + session + ":全入口取扱", actual_ids, {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        for s in d["入口取扱"]:
            r = case_map[(source, session, s["イベントID"])]
            for field in ("要求時計秒", "要求原板行", "side", "確認遅延秒"):
                audit.check(cid + s["イベントID"] + ":入口受渡:" + field, s[field], r[field])
    audit.check("全24×65候補場数", len(details), 1560)
    saved = U.table(STUDY / "全候補_場別.csv")
    saved_by_key = {(r["手法"], r["場"]): r for r in saved}
    audit.check("正式場別CSV一意", len(saved_by_key), len(saved))
    audit.check("正式場別CSV集合", set(saved_by_key), set(details))
    for key, d in details.items():
        for field, value in d["品質"].items():
            audit.check(str(key) + ":場別CSV:" + field, saved_by_key[key][field], value)
    aggregates, qualifications = [], 0
    for candidate in result["結果"]:
        cid, source = candidate["候補ID"], candidate["入口"]["入口ID"]
        role, variant = candidate["入口"]["役割"], candidate["出口"]["出口ID"]
        periods = {}
        for period in PERIODS:
            own = [r for r in op_rows if r["候補ID"] == cid and r["期間"] == period]
            values = operation_metrics(own, role, variant)
            for field, value in values.items():
                audit.check(cid + period + ":運用集計:" + field, candidate[period]["運用"][field], value)
            original = [r for r in op_rows if r["候補ID"] == source + "_X0" and r["期間"] == period]
            paired = pair([t for r in original for t in r["取引"]], [t for r in own for t in r["取引"]])
            for field, value in paired.items():
                audit.check(cid + period + ":共通新規:" + field, candidate[period]["運用"]["共通新規比較"][field], value)
            base_signals = [s for (a, b), d in details.items() if a == source + "_X0" and d["品質"]["期間"] == period for s in d["入口取扱"]]
            signals = [s for (a, b), d in details.items() if a == cid and d["品質"]["期間"] == period for s in d["入口取扱"]]
            transitions = A.signal_changes(base_signals, signals, audit, cid + period)
            shared = next(r for r in result["入口評価"] if r["入口ID"] == source)
            for field, value in shared[period].items():
                audit.check(cid + period + ":出口で入口評価不変:" + field, candidate[period]["入口"][field], value)
            periods[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values, "共通新規比較": paired, "入口取扱差": transitions})
        qualified = all(all(periods[p][field] >= minimum for field, minimum in limits.items()) and periods[p]["品質注意場数"] == 0
                        and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualifications += qualified
    audit.check("費用資格数", result["費用資格数"], qualifications)
    selected = []
    values = {(r["候補ID"], r["期間"]): r for r in aggregates}
    for source in result["入口評価"]:
        sid = source["入口ID"]
        variants = [sid + "_" + x for x in ("X0", "X1", "X2")]
        rank = {cid: min(values[(cid, p)]["追加5pt平均円"] if values[(cid, p)]["追加5pt平均円"] is not None else -math.inf for p in PERIODS[:2]) for cid in variants}
        selected.extend([sid + "_X0", sorted(variants, key=lambda cid: (-rank[cid], cid))[0]])
    audit.check("表示代表は旧二期間だけ", result["表示固定ID"], list(dict.fromkeys(selected)))
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, audit)
    views = viewer(op_rows, api, result["表示固定ID"], audit) if api else None
    if views:
        write(STUDY / "Viewer照合.json", views)
    exit_path = WORK / "出口独立確認.json"
    exit_check = read(exit_path) if exit_path.exists() else None
    if exit_check:
        audit.check("出口6実例の独立確認", exit_check["全件一致"], True)
        write(STUDY / "出口独立確認.json", exit_check)
    attention_path = WORK / "注意経路診断.json"
    attention_check = read(attention_path) if attention_path.exists() else None
    if attention_check:
        audit.check("学習注意2場の独立経路診断", attention_check["全件一致"], True)
        write(STUDY / "注意経路診断.json", attention_check)
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "確認日時": datetime.now(U.HELPER.JST).isoformat(), "コードSHA256": U.sha(Path(__file__)),
              "結果SHA256": U.sha(STUDY / "結果.json"), "全65場既使用": True, "固定後SHA変化件数": sum(1 for x in audit.errors if x["項目"].startswith("実行前固定後のSHA:")),
              "入口": entrance, "運用期間別": aggregates, "正式資源": files, "候補場数": len(details),
              "出口代表独立確認": {"参照": "出口独立確認.json", "照合項目数": exit_check["照合項目数"],
                                "コードSHA256": U.sha(ROOT / "scripts/テクニカル循環/出口独立確認.py")} if exit_check else None,
              "注意経路診断": {"参照": "注意経路診断.json", "照合項目数": attention_check["照合項目数"],
                            "コードSHA256": U.sha(ROOT / "scripts/テクニカル循環/注意経路診断.py"),
                            "結果SHA256": U.sha(STUDY / "注意経路診断.json")} if attention_check else None,
              "独立補助SHA256": {p: U.sha(ROOT / p) for p in ("scripts/利益回収/運用独立監査.py", "scripts/外部探索/運用独立監査.py",
                                  "scripts/広域研究/運用独立監査.py", "scripts/入口分析/独立照合.py")},
              "Viewer記録": "Viewer照合.json" if views else None,
              "DD": "各場0円開始・正常BBO各原行・約定後・将来返済手数料込み。期間欄は最大の一場内DDで累積期間DDではない。",
              "範囲": "保存入口の全先着を直接再判定し8×3集計、全24×65会計/正常板/待機/DD/保存MFE/MAE/正式CSV/JSONL/支持/代表選択を独立照合。",
              "限界": "入口生成漏れを原板から全再生成した監査ではない。新出口全要求の独立実装ではなく代表6例を別再構成。旧007保存取引との同値とは主張しない。"}
    write(STUDY / "独立監査.json", output)
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors[:10], "先着直接再判定件数": len(cases)}, ensure_ascii=False, default=float))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00011入口・運用・Viewer独立監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    output = run(args.api_base.rstrip("/") if args.api_base else None)
    if not output["全件一致"]:
        raise SystemExit(1)
