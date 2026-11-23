"""00014の数量付き12入口・固定X0運用を、気配先着と独立会計から監査する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00014_反転入口と観測差分量"
WORK = ROOT / "work/数量反転/00014"
QUANTITY_FIELDS = ("観測差分量", "数量基準完全", "直前数量足数", "直前数量合計", "直前数量平均",
                   "RVOL", "数量準備済", "最終採用数量時計", "最終採用価格時計", "最終採用原行", "数量不完全理由")


def load(path: Path, name: str) -> Any:
    """独立監査または表示の補助だけを読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。入口/検証/運用の数値エンジンは再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


H = load(ROOT / "scripts/テクニカル循環/独立監査.py", "数量反転の共通独立監査")
A, U, PERIODS = H.A, H.U, H.PERIODS


def operation_metrics(rows: list[dict]) -> dict:
    """基礎会計へ固定出口の場内DDとMFE到達後損失を集計する。

    引数: rows (list[dict]) は同じ候補と期間の独立場別会計。
    返り値: dict は保存期間集計に対応する値。場を接合した累積DDではない。
    """
    result, trades = U.aggregate(rows), [t for r in rows for t in r["取引"]]
    result.update(期間内最大場内DD円=max((r["観測含み込み最大DD円"] for r in rows), default=0),
                  最悪場内時価円=min((r["観測最悪時価円"] for r in rows), default=0),
                  基準赤字取引数=sum(t["基準純損益円"] < 0 for t in trades),
                  利確要求返済数=sum(t["返済理由"] == "利確" for t in trades),
                  初期125保護返済数=sum(t["返済理由"] == "保護" for t in trades),
                  活動場赤字率=result["赤字場数"] / result["活動場数"] if result["活動場数"] else None)
    for limit in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        result[f"{limit}pt到達取引"] = len(reached)
        result[f"{limit}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    return result


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """最大絶対観測損益場の同尺度同系統の数量補助なし/ありをAPI比較する。

    引数: rows (list[dict]) は会計、api (str) は接続先、audit (Any) は照合先。
    返り値: dict は代表2資源の表示・会計・指紋。PNGを増やさない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "数量反転の表示確認")
    resources = {(r["method_id"], r["session"]): r for r in H.read(STUDY / "一覧.resources.json")["resources"]}
    body, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer資源集合", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    selected = sorted(rows, key=lambda r: (-abs(r["観測現金増減円"]), r["候補ID"], r["場"]))[0]
    prefix = selected["候補ID"].rsplit("_", 2)[0]
    checks = []
    for extra in ("なし", "RVOL1.2以上"):
        cid = prefix + "_" + extra + "_X0"
        row = next(r for r in rows if r["候補ID"] == cid and r["場"] == selected["場"])
        adapted = {"銘柄": "NK225", "場": row["場"], "手法": cid, "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
        checked = helper.check_one(api, STUDY, adapted, resources[(cid, row["場"])], "最大絶対観測損益場の同系統補助比較", False)
        checked.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
        checks.append(checked)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
            "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden", "照合": checks, "追加PNG数": 0,
            "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
            "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"),
            "パス": "market_pathは設定data_root、pnl_pathはpath_base=catalogで一覧親基準。",
            "代表規則": "全12候補・65場から最大絶対観測損益、同値候補ID/場順。同尺度同系統の数量補助2つを比較する事後表示で、採用選択ではない。"}


# ----------------------------------------
# 量の集約再実装は別コードへ分け、ここでは保存量から選別集合を独立照合する。

def quantity_selection(cases: list[dict], base_rows: list[dict], feet: list[dict],
                       audit: Any) -> dict:
    """基準価格発動・数量足・12候補の対応を保存量から直接検算する。

    引数: cases/base_rows/feet (list[dict]) は純入口・数量選別前入口・全数量足、
    audit (Any) は照合先。
    返り値: dict は集合と数量準備除外の検算要約。原価格からの発動再生成とは区別する。
    """
    indexed = {(r["場"], r["時間足分"], r["index"]): r for r in feet}
    audit.check("数量足の場尺度番号一意", len(indexed), len(feet))
    expected, grouped = {}, defaultdict(list)
    price_keys = set()
    for r in base_rows:
        name = r["基準価格イベントID"]
        key = r["基準価格入口ID"], r["場"], r["index"], r["side"]
        audit.check(name + ":基準価格入口一意", key not in price_keys, True)
        price_keys.add(key)
        q = indexed[(r["場"], r["時間足分"], r["index"])]
        for field in QUANTITY_FIELDS:
            audit.check(name + ":数量足と発動量:" + field, r[field], q[field])
        if r["数量準備済"]:
            reason = None
        elif not r["数量基準完全"]:
            reason = "当足の数量基準不完全"
        elif r["直前数量足数"] < 20:
            reason = "直前20数量足の未準備"
        elif r["直前数量平均"] is None or r["直前数量平均"] <= 0:
            reason = "直前数量平均が非正または未定義"
        else:
            reason = "数量状態が未準備"
        audit.check(name + ":数量除外理由", r["数量準備除外理由"], reason)
        grouped[(r["場"], r["時間足分"])].append(r)
        if not r["数量準備済"]:
            continue
        audit.check(name + ":数量準備の定義", r["数量基準完全"] and r["直前数量足数"] == 20 and r["直前数量平均"] > 0, True)
        audit.check(name + ":RVOL式", r["RVOL"], r["観測差分量"] / r["直前数量平均"])
        audit.check(name + ":価格公開と確認順", q["publish"] and q["confirm"] == r["要求時計秒"]
                    and q["confirm_line"] == r["要求原板行"], True)
        for extra in ("なし", "RVOL1.2以上"):
            if extra != "なし" and r["RVOL"] < 1.2:
                continue
            cid = r["基準価格入口ID"] + "_" + extra
            event_id = f"NK225_{r['場']}_{cid}_{r['index']:04d}_{r['side']}"
            expected[event_id] = r, cid
    saved = {r["イベントID"]: r for r in cases}
    audit.check("数量選別後の入口集合", set(saved), set(expected))
    for identity in saved.keys() & expected.keys():
        r, cid = expected[identity]
        actual = saved[identity]
        for field in (*QUANTITY_FIELDS, "基準価格入口ID", "基準価格イベントID", "要求時計秒", "要求原板行", "side"):
            audit.check(identity + ":選別前後属性:" + field, actual[field], r[field])
        audit.check(identity + ":選別後入口ID", actual["入口ID"], cid)
    qualities = H.read(STUDY / "入口品質.json")
    audit.check("数量入口品質3尺度×65場", len(qualities), 195)
    for info in qualities:
        name = info["場"] + str(info["時間足分"])
        rows = grouped[(info["場"], info["時間足分"])]
        counters = {"基準価格入口数": len(rows),
                    "数量準備除外数": sum(not r["数量準備済"] for r in rows),
                    "数量準備通過数": sum(r["数量準備済"] for r in rows),
                    "RVOL補助除外数": sum(r["数量準備済"] and r["RVOL"] < 1.2 for r in rows)}
        for field, value in counters.items():
            audit.check(name + ":数量入口品質:" + field, info[field], value)
        if "数量準備除外理由" in info:
            audit.check(name + ":数量除外理由別件数", info["数量準備除外理由"],
                        dict(Counter(r["数量準備除外理由"] for r in rows if not r["数量準備済"])))
        if "系統別基準価格入口数" in info:
            for family in ("R1", "R2"):
                source = f"{info['時間足分']}分_{family}"
                own = [r for r in rows if r["基準価格入口ID"] == source]
                audit.check(name + source + ":系統別価格入口", info["系統別基準価格入口数"][source], len(own))
                audit.check(name + source + ":系統別準備除外", info["系統別数量準備除外数"][source],
                            sum(not r["数量準備済"] for r in own))
        if "系統別発動数" in info:
            for cid, count in info["系統別発動数"].items():
                audit.check(name + cid + ":系統別発動", count, sum(r["場"] == info["場"] and r["入口ID"] == cid for r in cases))
    return {"基準価格入口数": len(base_rows), "数量足数": len(feet),
            "数量準備除外数": sum(not r["数量準備済"] for r in base_rows),
            "数量準備通過基準価格入口数": sum(r["数量準備済"] for r in base_rows),
            "数量選別後12入口合計": len(cases),
            "限界": "保存基準価格入口と保存数量足から選別集合を独立再算出。基準価格入口自体の全件再生成ではない。数量足は別コードの原cache独立確認へ分離。"}


def run(api: str | None) -> dict:
    """完成した14出力を検算し、数量独立確認後だけ正式な総合監査を保存する。

    引数: api (str|None) はViewer接続先。
    返り値: dict は明示合否・件数・範囲。原板と固定coreは変更しない。
    """
    audit = U.Audit()
    config, result, locked = H.read(STUDY / "条件.json"), H.read(STUDY / "結果.json"), H.read(STUDY / "固定.json")
    for path, expected in locked["ファイルSHA256"].items():
        audit.check("実行前固定後SHA:" + path, U.sha(ROOT / path), expected)
    pointer = H.read(STUDY / "入力台帳.json")
    manifest = (STUDY / pointer["参照"]).resolve()
    audit.check("参照台帳SHA", U.sha(manifest), pointer["SHA256"])
    entries = {e["session"]: e for e in H.read(manifest)["entries"]}
    raw, detailed_sha = H.rows(WORK / "全運用詳細.jsonl.gz")
    cases, case_sha = H.rows(WORK / "入口事例.jsonl.gz")
    bases, base_sha = H.rows(WORK / "基準価格入口.jsonl.gz")
    feet, feet_sha = H.rows(WORK / "数量足.jsonl.gz")
    contents = {str(WORK / "全運用詳細.jsonl.gz"): detailed_sha, str(WORK / "入口事例.jsonl.gz"): case_sha,
                str(WORK / "基準価格入口.jsonl.gz"): base_sha, str(WORK / "数量足.jsonl.gz"): feet_sha}
    for item in H.read(STUDY / "作業成果物.json")["ファイル"]:
        audit.check("作業展開SHA:" + item["パス"], contents[str(ROOT / item["パス"])], item["展開内容SHA256"])
    entrance = H.entry_audit(cases, result, entries, config, audit)
    entrance["限界"] = "先着を全保存入口について直接再判定。入口式・発動漏れ・共通準備・時点は別の数量独立確認で原cacheから全価格足と全発動集合を再構成する。先着ラベルは実運用の一建玉成績ではない。"
    selection = quantity_selection(cases, bases, feet, audit)
    details, cached, rows = {}, {}, []
    source_cases = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    for d in raw:
        cid, session = d["候補ID"], d["場"]
        if (cid, session) in details:
            raise ValueError("候補・場が重複")
        details[(cid, session)] = d
        source = cid.rsplit("_", 1)[0]
        if session not in cached:
            cached[session] = U.quotes(entries[session], True)
        q = cached[session]
        row = U.audit_session(d, q, audit)
        row.update(A.drawdown(d, q, audit))
        H.check_trade_path(d, q, audit)
        audit.check(cid + session + ":終了建玉0", row["終了建玉"], 0)
        audit.check(cid + session + ":返済待機0", row["終了返済待機"], 0)
        audit.check(cid + session + ":純入口と取扱の集合",
                    {s["イベントID"] for s in d["入口取扱"]},
                    {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        for s in d["入口取扱"]:
            r = source_cases[(source, session, s["イベントID"])]
            for field in ("要求時計秒", "要求原板行", "side", "確認遅延秒"):
                audit.check(cid + s["イベントID"] + ":入口受渡:" + field, s[field], r[field])
        rows.append(row)
    audit.check("12候補×65場", len(details), 780)
    saved = U.table(STUDY / "全候補_場別.csv")
    indexed = {(r["手法"], r["場"]): r for r in saved}
    audit.check("場別CSV一意", len(indexed), len(saved))
    audit.check("場別CSV集合", set(indexed), set(details))
    for key, d in details.items():
        for field, value in d["品質"].items():
            audit.check(str(key) + ":場別CSV:" + field, indexed[key][field], value)
    aggregates, qualified_count = [], 0
    for candidate in result["結果"]:
        cid, source = candidate["候補ID"], candidate["入口"]["入口ID"]
        supported, target = entrance["支持"][source]
        audit.check(cid + ":入口支持コピー", candidate["入口支持"], supported)
        audit.check(cid + ":入口目標コピー", candidate["70目標"], target)
        periods = {}
        for period in PERIODS:
            own = [r for r in rows if r["候補ID"] == cid and r["期間"] == period]
            audit.check(cid + period + ":実行場数", len(own), {"学習": 40, "条件選択": 24, "後続検査": 1}[period])
            values = operation_metrics(own)
            for field, value in values.items():
                audit.check(cid + period + ":運用集計:" + field, candidate[period]["運用"][field], value)
            shared = next(e for e in result["入口評価"] if e["入口ID"] == source)
            for field, value in shared[period].items():
                audit.check(cid + period + ":入口結果コピー:" + field, candidate[period]["入口"][field], value)
            periods[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values})
        qualified = all(all(periods[p][field] >= minimum for field, minimum in limits.items())
                        and periods[p]["品質注意場数"] == 0 and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualified_count += qualified
    audit.check("費用資格数", result["費用資格数"], qualified_count)
    expected_ids = [f"{size}分_{family}_{extra}_X0" for size in config["時間足分"] for family in config["入口系統"] for extra in config["補助"]]
    audit.check("全12表示で再順位なし", result["表示固定ID"], expected_ids)
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, audit)
    views = viewer(rows, api, audit) if api else None
    if views:
        H.write(STUDY / "Viewer照合.json", views)
    state_path = WORK / "数量独立確認.json"
    state_check = H.read(state_path) if state_path.exists() else None
    if state_check:
        audit.check("原cacheからの数量独立集約", state_check["全件一致"], True)
        for field, expected in (("コードSHA256", U.sha(ROOT / "scripts/数量反転/数量独立確認.py")),
                                ("入力台帳SHA256", U.sha(manifest)), ("数量足展開SHA256", feet_sha),
                                ("基準価格入口展開SHA256", base_sha), ("入口事例展開SHA256", case_sha),
                                ("入力場数", 65), ("保存数量足数", len(feet)),
                                ("基準価格入口数", len(bases)), ("保存12入口数", len(cases))):
            audit.check("数量独立確認の対象と版:" + field, state_check[field], expected)
        H.write(STUDY / "数量独立確認.json", state_check)
    complete = state_check is not None
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "数量確認未完": not complete, "確認日時": datetime.now(U.HELPER.JST).isoformat(),
              "コードSHA256": U.sha(Path(__file__)), "結果SHA256": U.sha(STUDY / "結果.json"), "全65場既使用": True,
              "固定後SHA変化件数": sum(e["項目"].startswith("実行前固定後SHA:") for e in audit.errors),
              "入口": entrance, "数量選別": selection, "運用期間別": aggregates, "正式資源": files,
              "数量独立確認": {"参照": "数量独立確認.json", "照合項目数": state_check["照合項目数"],
                             "全件一致": state_check["全件一致"], "SHA256": U.sha(state_path),
                             "検証範囲": state_check["検証範囲"],
                             "コードSHA256": U.sha(ROOT / "scripts/数量反転/数量独立確認.py")} if state_check else None,
              "Viewer記録": "Viewer照合.json" if views else None,
              "独立補助SHA256": {p: U.sha(ROOT / p) for p in ("scripts/テクニカル循環/独立監査.py", "scripts/利益回収/運用独立監査.py",
                                   "scripts/外部探索/運用独立監査.py", "scripts/広域研究/運用独立監査.py", "scripts/入口分析/独立照合.py")},
              "会計範囲": "全12入口先着を気配直接再判定。12×65のDecimal会計/注文・約定・帰属/待機/単一建玉/保存MFE・MAE/全X0要求初着/DD/正式片・CSV/期間集計・支持を検算。",
              "数量範囲": "保存基準価格入口から共通数量準備とRVOL1.2等号の12集合を独立構成。別コードで原cacheから観測累積差分・直前20足/RVOLに加え、1/3/5/15分OHLC・指標・R1/R2の全発動集合を再構築。子の照合件数は主件数へ加算せず別掲。数量基準完全を真の約定出来高の完全性とはしない。",
              "DD": "各場0開始・約定後の正常BBO時価・返済手数料込み。期間は最大一場DDで累積DDではない。"}
    target = STUDY / "独立監査.json" if complete else WORK / "会計監査_途中.json"
    H.write(target, output)
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors[:10], "数量確認未完": not complete, "先着件数": len(cases)}, ensure_ascii=False, default=float))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00014原気配・会計・数量独立監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    output = run(args.api_base.rstrip("/") if args.api_base else None)
    if not output["全件一致"]:
        raise SystemExit(1)
