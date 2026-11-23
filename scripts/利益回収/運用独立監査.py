"""00010の全18出口を、会計・場内時価DD・旧保存対照・正式Viewerから独立照合する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import gzip
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00010_順行と反転の利益保護と通常出口"
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
DETAIL = ROOT / "work/利益回収/00010/全運用詳細.jsonl.gz"


def load(path: Path, name: str) -> Any:
    """独立監査または表示の補助だけを読み込む。

    引数: path (Path) は補助コード、name (str) は識別名。
    返り値: Any は読込結果。比較.py・運用.pyは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


U = load(ROOT / "scripts/外部探索/運用独立監査.py", "利益保護の共通独立監査")


def read(path: Path) -> Any:
    """日本語JSONを読む。

    引数: path (Path) は対象。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON値。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")


# ----------------------------------------
# 正常板の各原行で、約定後の現金と返済手数料込み時価を会計から直接構築する。

def drawdown(detail: dict, q: dict, audit: Any) -> dict:
    """単一場0円開始の時価列からDDと最悪時価を独立再計算する。

    引数: detail (dict) は保存片、q (dict) は正常気配、audit (Any) は照合先。
    返り値: dict は場内DD・最悪時価。場を接合した期間DDではない。
    """
    changes = np.zeros(len(q["now"]), dtype=float)
    unrealized = np.zeros(len(q["now"]), dtype=float)
    positions = {}
    for fill in detail["約定"]:
        index = q["at"][fill["source_line"]]
        identity = fill["position_id"]
        changes[index] -= fill["fee_yen"]
        if fill["type"].endswith("N"):
            positions[identity] = {"index": index, "side": 1 if fill["type"].startswith("Long") else -1,
                                   "price": fill["price"], "qty": fill["qty"], "closed": False}
        else:
            p = positions[identity]
            changes[index] += float(Decimal(p["side"]) * (Decimal(str(fill["price"])) - Decimal(str(p["price"]))) * p["qty"] * 10)
            mark = q["bid"] if p["side"] == 1 else q["ask"]
            unrealized[p["index"]:index] = p["side"] * (mark[p["index"]:index] - p["price"]) * p["qty"] * 10 - 11
            p["closed"] = True
    for p in positions.values():
        if not p["closed"]:
            mark = q["bid"] if p["side"] == 1 else q["ask"]
            unrealized[p["index"]:] = p["side"] * (mark[p["index"]:] - p["price"]) * p["qty"] * 10 - 11
    equity = np.r_[0., np.cumsum(changes) + unrealized]
    maximum_dd = float(np.max(np.maximum.accumulate(equity) - equity))
    lowest = float(np.min(equity))
    name = detail["候補ID"] + detail["場"]
    audit.check(name + ":独立場内DD", detail["品質"]["観測含み込み最大DD円"], maximum_dd)
    audit.check(name + ":独立場内最悪時価", detail["品質"]["観測最悪時価円"], lowest)
    audit.check(name + ":終了現金", detail["品質"]["観測現金増減円"], float(np.sum(changes)))
    return {"観測含み込み最大DD円": maximum_dd, "観測最悪時価円": lowest}


def paired(original: list[dict], changed: list[dict]) -> dict:
    """実新規が一致する取引と参加集合の違いを直接比較する。

    引数: original/changed (list[dict]) はX00/変更出口の完結取引。
    返り値: dict は共通新規損益差と集合差。参加差を出口単独の損益としない。
    """
    base = {(t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]): t for t in original}
    alt = {(t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]): t for t in changed}
    common = base.keys() & alt.keys()
    differences = {k: Decimal(str(alt[k]["基準純損益円"])) - Decimal(str(base[k]["基準純損益円"])) for k in common}
    return {"共通実新規": len(common), "元のみ新規": len(base.keys() - alt.keys()), "変更のみ新規": len(alt.keys() - base.keys()),
            "共通新規の純損益差円": sum(differences.values(), Decimal(0)),
            "元赤字から黒字": sum(base[k]["基準純損益円"] < 0 < alt[k]["基準純損益円"] for k in common),
            "元黒字から赤字": sum(alt[k]["基準純損益円"] < 0 < base[k]["基準純損益円"] for k in common),
            "元黒字を早く確定した純額差円": sum((differences[k] for k in common if base[k]["基準純損益円"] > 0), Decimal(0))}


def signal_changes(base: list[dict], changed: list[dict], audit: Any, name: str) -> dict:
    """入口要求の同一性と出口変更による取扱・抑止の差を分ける。

    引数: base/changed (list[dict]) は入口取扱、audit (Any) は比較先、name (str) は名称。
    返り値: dict は取扱遷移と追加抑止の記述。未約定を完結取引へ混ぜない。
    """
    before = {s["イベントID"]: s for s in base}
    after = {s["イベントID"]: s for s in changed}
    audit.check(name + ":入口要求集合", set(before), set(after))
    for identity in before.keys() & after.keys():
        for field in ("要求時計秒", "要求原板行", "確認遅延秒", "side"):
            audit.check(name + ":要求不変:" + field, before[identity][field], after[identity][field])
    transitions = Counter((before[k]["取扱"], after[k]["取扱"]) for k in before.keys() & after.keys() if before[k]["取扱"] != after[k]["取扱"])
    return {"取扱変化": [{"元": a, "変更": b, "件数": n} for (a, b), n in sorted(transitions.items())],
            "建玉中抑止増分": sum(s["取扱"] == "建玉中抑止" for s in changed) - sum(s["取扱"] == "建玉中抑止" for s in base),
            "注文待機中抑止増分": sum(s["取扱"] == "注文待機中抑止" for s in changed) - sum(s["取扱"] == "注文待機中抑止" for s in base)}


def extended_metrics(rows: list[dict], policy: dict) -> dict:
    """共通会計へ利益床・DD・含み益到達後の最終赤字を独立集計する。

    引数: rows (list[dict]) は一候補/期間、policy (dict) は固定出口。
    返り値: dict は保存運用結果と対応する値。床未使用は未起動をNoneにする。
    """
    result = U.aggregate(rows)
    trades = [t for row in rows for t in row["取引"]]
    active_floor = policy.get("床起動pt") is not None
    unarmed = [t for t in trades if not t["利益床起動"]]
    result.update(期間内最大場内DD円=max((r["観測含み込み最大DD円"] for r in rows), default=0),
                  最悪場内時価円=min((r["観測最悪時価円"] for r in rows), default=0),
                  床起動取引数=sum(t["利益床起動"] for t in trades),
                  中心目標無効=sum(r["中心線目標無効取引数"] for r in rows),
                  活動場赤字率=result["赤字場数"] / result["活動場数"] if result["活動場数"] else None,
                  利益床使用=active_floor, 床未起動取引数=len(unarmed) if active_floor else None,
                  床未起動純損益円=sum(Decimal(str(t["基準純損益円"])) for t in unarmed) if active_floor else None,
                  床未起動赤字取引数=sum(t["基準純損益円"] < 0 for t in unarmed) if active_floor else None,
                  床起動済純損益円=sum(Decimal(str(t["基準純損益円"])) for t in trades if t["利益床起動"]) if active_floor else None)
    for limit in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        result[f"{limit}pt到達取引"] = len(reached)
        result[f"{limit}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    return result


# ----------------------------------------
# X00の旧64場を00008の保存片・注文・取引・入口取扱と直接接合する。

def old_equivalence(details: dict, config: dict, audit: Any) -> dict:
    """3入口のX00を元00008へ照合し、旧出力にない新1は対象外と明記する。

    引数: details/config (dict) は00010正本と設定、audit (Any) は比較先。
    返り値: dict は対応場数・取引数と新1比較範囲。
    """
    mapping = {s["候補ID"]: s["入口ID"] + "_X00" for s in config["入口"]}
    checked_sessions = trades = fills = 0
    for filename in ("探索_運用詳細.jsonl.gz", "後続_運用詳細.jsonl.gz"):
        path = ROOT / "work/外部研究/探索00008" / filename
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                old = json.loads(line)
                if old["候補ID"] not in mapping:
                    continue
                cid, session = mapping[old["候補ID"]], old["場"]
                current = details[(cid, session)]
                checked_sessions += 1
                for collection in ("約定", "注文", "取引", "入口取扱"):
                    audit.check(cid + session + ":元008件数:" + collection, len(current[collection]), len(old[collection]))
                    for a, b in zip(current[collection], old[collection]):
                        for key, value in b.items():
                            if key not in ("method_id", "手法"):
                                audit.check(cid + session + ":元008:" + collection + key, a[key], value)
                for key, value in old["品質"].items():
                    if key != "手法":
                        audit.check(cid + session + ":元008品質:" + key, current["品質"][key], value)
                trades += len(old["取引"])
                fills += len(old["約定"])
    audit.check("旧3入口×64＋新1の保存2入口", checked_sessions, 194)
    return {"元008対応候補場数": checked_sessions, "旧64の3入口": 192, "既使用新1の元保存2入口": 2,
            "比較完結取引": trades, "比較約定片": fills,
            "新1T01": "00008では未実行のため元保存との同値比較対象外。0取引の保存があったとは扱わない。"}


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """同じ場のR02基準と通常出口をAPI照合し、PNGを追加せず数値・帰属を確認する。

    引数: rows (list[dict]) は独立場別会計、api (str) は接続先、audit (Any) は比較先。
    返り値: dict は設定・代表2資源の照合。
    """
    path = ROOT / "scripts/複合検証/Viewer照合.py"
    helper = load(path, "利益保護のViewer補助")
    catalog = read(STUDY / "一覧.resources.json")
    resources = {(r["method_id"], r["session"]): r for r in catalog["resources"]}
    data, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer:全資源集合", {r["id"] for r in json.loads(data)["resources"]}, {r["id"] for r in resources.values()})
    reference = [r for r in rows if r["候補ID"] == "R02_X04"]
    selected = sorted(reference, key=lambda r: (-abs(r["観測現金増減円"]), r["場"]))[0]
    checks = []
    for method in ("R02_X00", "R02_X04"):
        row = next(r for r in rows if r["候補ID"] == method and r["場"] == selected["場"])
        adapted = {"銘柄": "NK225", "場": row["場"], "手法": method, "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
        checked = helper.check_one(api, STUDY, adapted, resources[(method, row["場"])], "通常出口の最大絶対観測損益場と同場基準", False)
        checked.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
        checks.append(checked)
    with urlopen(api + "/api/info", timeout=10) as response:
        info = json.load(response)
    binary = ROOT / "work/viewer/session-trade-viewer.exe"
    supplied = ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
            "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden",
            "Viewer実行コピーSHA256": U.sha(binary), "指定配布版SHA256": U.sha(supplied),
            "パス": "market_pathは設定data_root、pnl_pathはpath_base=catalogで一覧親基準。",
            "代表選択": "R02_X04の最大絶対観測損益場。同率は場名順。同場X00を比較。全65場既使用、表示用の事後選択。",
            "表示コードSHA256": U.sha(path), "照合": checks, "追加PNG数": 0,
            "意味": "micro1枚代理・片道11円・追加滑り0ptの観測会計。床や通常出口の一般優位を図から主張しない。"}


def run(api: str | None) -> dict:
    """全18×65の独立監査と任意Viewerを実行して正式結果へ保存する。

    引数: api (str|None) はViewer接続先。
    返り値: dict は明示合否と独立集計。原板と元コードを変更しない。
    """
    audit = U.Audit()
    locked, config, result = read(STUDY / "固定.json"), read(STUDY / "条件.json"), read(STUDY / "結果.json")
    for path, expected in locked["ファイルSHA256"].items():
        audit.check("固定SHA:" + path, U.sha(ROOT / path), expected)
    audit.check("条件固定SHA", U.sha(STUDY / "条件.json"), locked["条件SHA256"])
    pointer = read(STUDY / "入力台帳.json")
    manifest_path = (STUDY / pointer["参照"]).resolve()
    audit.check("参照台帳SHA", U.sha(manifest_path), pointer["SHA256"])
    entries = {e["session"]: e for e in read(manifest_path)["entries"]}
    details, cached, rows = {}, {}, []
    with gzip.open(DETAIL, "rt", encoding="utf-8") as stream:
        for line in stream:
            d = json.loads(line)
            key = d["候補ID"], d["場"]
            if key in details:
                raise ValueError("候補・場の重複")
            details[key] = d
            if key[1] not in cached:
                cached[key[1]] = U.quotes(entries[key[1]], True)
            q = cached[key[1]]
            row = U.audit_session(d, q, audit)
            row.update(drawdown(d, q, audit), 中心線目標無効取引数=d["品質"]["中心線目標無効取引数"])
            rows.append(row)
            audit.check(str(key) + ":終了0", row["終了建玉"], 0)
            audit.check(str(key) + ":返済待機0", row["終了返済待機"], 0)
    audit.check("全18×65候補場", len(details), 1170)
    saved_sessions = U.table(STUDY / "全候補_場別.csv")
    by_session = {(r["手法"], r["場"]): r for r in saved_sessions}
    audit.check("全候補場別CSV一意", len(by_session), len(saved_sessions))
    audit.check("全候補場別CSV集合", set(by_session), set(details))
    for identity, detail in details.items():
        for key, value in detail["品質"].items():
            audit.check(str(identity) + ":場別CSV:" + key, by_session[identity][key], value)
    policies = {p["出口ID"]: p for p in config["出口"]}
    periods = ("学習", "条件選択", "後続検査")
    summaries, qualifications = [], 0
    limits = read(SOURCE / "条件.json")["費用支持"]
    for candidate in result["結果"]:
        cid = candidate["候補ID"]
        policy = policies[cid.split("_")[-1]]
        period_values = {}
        for period in periods:
            part = [r for r in rows if r["候補ID"] == cid and r["期間"] == period]
            values = extended_metrics(part, policy)
            audit.check(cid + period + ":場数", len(part), {"学習": 40, "条件選択": 24, "後続検査": 1}[period])
            for key, value in values.items():
                audit.check(cid + period + ":集計:" + key, candidate[period][key], value)
            base_id = cid.split("_")[0] + "_X00"
            base = [r for r in rows if r["候補ID"] == base_id and r["期間"] == period]
            own_trades = [t for r in part for t in r["取引"]]
            base_trades = [t for r in base for t in r["取引"]]
            pair = paired(base_trades, own_trades)
            for key, value in pair.items():
                audit.check(cid + period + ":共通新規:" + key, candidate[period]["共通新規比較"][key], value)
            base_signals = [s for (a, b), d in details.items() if a == base_id and d["品質"]["期間"] == period for s in d["入口取扱"]]
            own_signals = [s for (a, b), d in details.items() if a == cid and d["品質"]["期間"] == period for s in d["入口取扱"]]
            transition = signal_changes(base_signals, own_signals, audit, cid + period)
            summaries.append({"候補ID": cid, "期間": period, **values, "共通新規比較": pair, "入口取扱差": transition})
            period_values[period] = values
            for r in part:
                audit.check(cid + r["場"] + ":床使用", details[(cid, r["場"])]["品質"]["利益床使用"], policy.get("床起動pt") is not None)
        qualified = all(all(period_values[p][k] >= value for k, value in thresholds.items())
                        and period_values[p]["品質注意場数"] == 0 and period_values[p]["追加5pt純損益円"] > 0 for p, thresholds in limits.items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualifications += qualified
    audit.check("費用資格数", result["費用資格数"], qualifications)
    selected = []
    indexed = {(r["候補ID"], r["期間"]): r for r in summaries}
    for source in config["入口"]:
        family = source["入口ID"]
        variants = [r["候補ID"] for r in result["結果"] if r["候補ID"].startswith(family + "_")]
        rank = {cid: min(indexed[(cid, p)]["追加5pt平均円"] if indexed[(cid, p)]["追加5pt平均円"] is not None else -float("inf")
                         for p in ("学習", "条件選択")) for cid in variants}
        representative = sorted(variants, key=lambda cid: (-rank[cid], cid))[0]
        selected.extend([family + "_X00", representative])
    audit.check("表示固定IDは学習選択だけの順位", result["表示固定ID"], list(dict.fromkeys(selected)))
    equivalence = old_equivalence(details, config, audit)
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, audit)
    views = viewer(rows, api, audit) if api else None
    if views:
        write(STUDY / "Viewer照合.json", views)
    exit_check = ROOT / "work/利益回収/出口独立確認.json"
    independent_exit = None
    if exit_check.exists():
        independent_exit = read(exit_check)
        audit.check("代表出口の独立原行照合", independent_exit["全件一致"], True)
        write(STUDY / "出口独立確認.json", independent_exit)
    output = {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "全件一致": not audit.errors,
              "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "コードSHA256": U.sha(Path(__file__)), "共通会計補助SHA256": U.sha(ROOT / "scripts/外部探索/運用独立監査.py"),
              "共通会計汎用部SHA256": U.sha(ROOT / "scripts/広域研究/運用独立監査.py"),
              "結果SHA256": U.sha(STUDY / "結果.json"), "詳細SHA256": U.sha(DETAIL), "全65場既使用": True,
              "候補場数": len(rows), "旧008X00同値": equivalence, "期間別": summaries, "正式資源": files,
              "Viewer記録": "Viewer照合.json" if views else None,
              "代表出口独立確認": {"参照": "出口独立確認.json", "照合項目数": independent_exit["照合項目数"],
                               "コード": "scripts/利益回収/出口独立確認.py",
                               "コードSHA256": U.sha(ROOT / "scripts/利益回収/出口独立確認.py"),
                               "結果SHA256": U.sha(STUDY / "出口独立確認.json")} if independent_exit else None,
              "DD定義": "正常気配の各原行で約定後の現金と返済手数料込み時価。各場0円開始。期間欄は最大一場内DD・最悪一場内時価で、場を接合した累積DDではない。",
              "範囲": "保存片からDecimal会計・次1秒正常BBO・注文/取引所有・単一建玉/終了0・全18集計/共有新規差/入口取扱差・正式CSV/JSONL・元008X00保存値を照合。",
              "限界": "全出口要求生成の独立再実装ではない。床/ATR/通常出口の実原行は別の少数直接診断で確認。候補再選定は行わない。"}
    write(STUDY / "独立監査.json", output)
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors[:10], "元008同値": equivalence}, ensure_ascii=False, default=float))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00010運用会計・Viewer独立監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    output = run(args.api_base.rstrip("/") if args.api_base else None)
    if not output["全件一致"]:
        raise SystemExit(1)
