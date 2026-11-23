"""00012の4入口先着・8運用会計・旧即時固定同値・構造因果性を独立照合する。"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00012_BB反転の確認と構造リスク"
WORK = ROOT / "work/反転確認/00012"


def load(path: Path, name: str) -> Any:
    """数値エンジンではなく独立監査の補助だけを読み込む。

    引数: path (Path) は補助コード、name (str) は識別名。
    返り値: Any はモジュール。00012入口/運用/検証を再実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


H = load(ROOT / "scripts/テクニカル循環/独立監査.py", "反転確認の共通独立補助")
A, U, PERIODS = H.A, H.U, H.PERIODS


class ValuesAudit:
    """構造保護価格とCSV内設定足dictだけを明示した型で照合する。"""

    def __init__(self, audit: Any, stops: dict[str, float]) -> None:
        """比較先と原行・入口から求めた期待保護価格を保持する。

        引数: audit (Any) は比較先、stops (dict[str,float]) は比較項目別の価格。
        返り値: None。
        """
        self.audit, self.stops = audit, stops

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """保存値を改変せず構造保護とCSVの辞書表記を比較する。

        引数: name (str) は項目、actual/expected (Any) は比較値。
        返り値: None。CSVのdictはliteral_evalで読み、コードを実行しない。
        """
        if name in self.stops:
            expected = self.stops[name]
        if isinstance(expected, dict) and isinstance(actual, str):
            actual = ast.literal_eval(actual)
        self.audit.check(name, actual, expected)


def canonical(value: Any, field: str = "") -> Any:
    """新旧比較で入口/出口/手法の名称だけを旧00011表記へ変換する。

    引数: value (Any) は保存値、field (str) は列名。
    返り値: Any はID変換後。価格・時計・原行・数量・費用を変えない。
    """
    if isinstance(value, dict):
        return {k: canonical(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v, field) for v in value]
    if isinstance(value, str):
        if field == "出口ID" and value == "固定":
            return "X0"
        return value.replace("_即時_固定", "_R2_X0").replace("_即時_", "_R2_")
    return value


def old_equivalence(details: dict, audit: Any) -> dict:
    """即時固定の全65場を00011のR2_X0保存片等へ接合する。

    引数: details (dict) は新正本、audit (Any) は比較先。
    返り値: dict は比較件数。旧エンジン再呼出しだけの証明にしない。
    """
    old_rows, _ = H.rows(ROOT / "work/テクニカル循環/00011/全運用詳細.jsonl.gz")
    count = trades = fills = 0
    for old in old_rows:
        if old["候補ID"] not in ("3分_R2_X0", "5分_R2_X0"):
            continue
        cid = old["候補ID"].replace("_R2_X0", "_即時_固定")
        current = canonical(details[(cid, old["場"])])
        prefix = cid + old["場"]
        for collection in ("約定", "取引", "注文", "入口取扱"):
            audit.check(prefix + ":元11件数:" + collection, len(current[collection]), len(old[collection]))
            for actual, expected in zip(current[collection], old[collection]):
                for field, value in expected.items():
                    audit.check(prefix + ":元11:" + collection + field, actual[field], value)
        for field, value in old["品質"].items():
            audit.check(prefix + ":元11品質:" + field, current["品質"][field], value)
        count += 1
        trades += len(old["取引"])
        fills += len(old["約定"])
    audit.check("2尺度×65場の元11保存対応", count, 130)
    return {"候補場数": count, "完結取引数": trades, "約定片数": fills,
            "変換": "即時→R2、固定→X0、該当手法/入口IDだけ変換。時計・原行・価格・数量・費用は無変換。"}


def pair(base: list[dict], changed: list[dict]) -> dict:
    """共有実新規の損益と構造退出後の固定目標を独立集計する。

    引数: base/changed (list[dict]) は固定/構造の完結取引。
    返り値: dict は集合差・損失縮小・後の元利確要求件数。
    """
    output = H.pair(base, changed)
    a = {(t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]): t for t in base}
    b = {(t["入口イベントID"], t["新規時計秒"], t["新規原板行"], t["新規価格"]): t for t in changed}
    common = a.keys() & b.keys()
    rescued = [k for k in common if a[k]["基準純損益円"] < 0 and b[k]["基準純損益円"] > a[k]["基準純損益円"]]
    later = [k for k in common if b[k]["返済理由"] == "構造保護" and a[k]["返済理由"] == "利確"
             and (b[k]["返済時計秒"], b[k]["返済原板行"]) < (a[k]["返済要求時計秒"], a[k]["返済要求原板行"])]
    output.update(元赤字の損失縮小件数=len(rescued),
                  元赤字の損失縮小純額差円=sum(Decimal(str(b[k]["基準純損益円"])) - Decimal(str(a[k]["基準純損益円"])) for k in rescued),
                  構造退出後に元固定利確要求=len(later))
    return output


def operation_metrics(rows: list[dict], structural: bool) -> dict:
    """基礎会計に構造取消・保護・場内DDを独立集約する。

    引数: rows (list[dict]) は一候補期間、structural (bool) は構造使用か。
    返り値: dict は全運用集計。取消は注文台帳から区別した件数を使う。
    """
    values, trades = U.aggregate(rows), [t for r in rows for t in r["取引"]]
    values.update(期間内最大場内DD円=max((r["観測含み込み最大DD円"] for r in rows), default=0),
                  最悪場内時価円=min((r["観測最悪時価円"] for r in rows), default=0),
                  構造保護使用=structural, 構造無効新規取消数=sum(r["構造無効新規取消数"] for r in rows),
                  構造未確認新規取消数=sum(r["構造未確認新規取消数"] for r in rows),
                  構造保護返済数=sum(t["返済理由"] == "構造保護" for t in trades),
                  基準赤字取引数=sum(t["基準純損益円"] < 0 for t in trades),
                  活動場赤字率=values["赤字場数"] / values["活動場数"] if values["活動場数"] else None,
                  初期125保護返済数=sum(t["返済理由"] == "保護" for t in trades))
    for limit in (20, 50, 100):
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        values[f"{limit}pt到達取引"] = len(reached)
        values[f"{limit}pt後純赤字"] = sum(t["基準純損益円"] < 0 for t in reached)
    return values


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """構造候補の最大絶対観測損益場と同場固定をAPI照合する。

    引数: rows (list[dict]) は場別会計、api (str) は接続先、audit (Any) は比較先。
    返り値: dict は2資源の指紋・会計・帰属。PNGを追加しない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "反転確認の表示補助")
    resources = {(r["method_id"], r["session"]): r for r in H.read(STUDY / "一覧.resources.json")["resources"]}
    data, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer:全資源集合", {r["id"] for r in json.loads(data)["resources"]}, {r["id"] for r in resources.values()})
    alternative = [r for r in rows if r["候補ID"].endswith("_構造")]
    selected = sorted(alternative, key=lambda r: (-abs(r["観測現金増減円"]), r["候補ID"], r["場"]))[0]
    source = selected["候補ID"].rsplit("_", 1)[0]
    checks = []
    for cid in (source + "_固定", source + "_構造"):
        row = next(r for r in rows if r["候補ID"] == cid and r["場"] == selected["場"])
        adapted = {"銘柄": "NK225", "場": row["場"], "手法": cid, "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
        checked = helper.check_one(api, STUDY, adapted, resources[(cid, row["場"])], "構造最大絶対観測損益場と同場固定", False)
        checked.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
        checks.append(checked)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"接続先": api, "API情報": info, "確認日時": datetime.now(U.HELPER.JST).isoformat(),
            "設定": "work/viewer/conf/viewer.toml", "WindowStyle": "Hidden", "照合": checks, "追加PNG数": 0,
            "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
            "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"),
            "パス": "市場は設定data_root、約定はpath_base=catalogで一覧親基準。全65場既使用の事後表示。"}


def run(api: str | None) -> dict:
    """完成した00012出力だけを監査して正式結果へ保存する。

    引数: api (str|None) はViewer接続先。
    返り値: dict は明示合否・件数・範囲。旧結果/原板/coreを変更しない。
    """
    audit = U.Audit()
    locked, config, result = H.read(STUDY / "固定.json"), H.read(STUDY / "条件.json"), H.read(STUDY / "結果.json")
    for path, expected in locked["ファイルSHA256"].items():
        audit.check("固定後SHA:" + path, U.sha(ROOT / path), expected)
    pointer = H.read(STUDY / "入力台帳.json")
    manifest = (STUDY / pointer["参照"]).resolve()
    audit.check("参照入力SHA", U.sha(manifest), pointer["SHA256"])
    entries = {e["session"]: e for e in H.read(manifest)["entries"]}
    raw, detailed_sha = H.rows(WORK / "全運用詳細.jsonl.gz")
    cases, case_sha = H.rows(WORK / "入口事例.jsonl.gz")
    source_cases = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    contents = {str(WORK / "全運用詳細.jsonl.gz"): detailed_sha, str(WORK / "入口事例.jsonl.gz"): case_sha}
    for item in H.read(STUDY / "作業成果物.json")["ファイル"]:
        audit.check("作業展開SHA:" + item["パス"], contents[str(ROOT / item["パス"])], item["展開内容SHA256"])
    entrance = H.entry_audit(cases, result, entries, config, audit)
    details, cached, rows, stops = {}, {}, [], {}
    for d in raw:
        cid, session = d["候補ID"], d["場"]
        if (cid, session) in details:
            raise ValueError("候補・場が重複")
        details[(cid, session)] = d
        source, structural = cid.rsplit("_", 1)[0], cid.endswith("_構造")
        for fill in d["約定"]:
            if fill["type"].endswith("N"):
                continue
            t = next(t for t in d["取引"] if t["建玉ID"] == fill["position_id"])
            r = source_cases[(source, session, t["入口イベントID"])]
            side = 1 if t["方向"] == "買い" else -1
            hard = t["新規価格"] - side * 125
            expected = (max(hard, r["構造価格"]) if side == 1 else min(hard, r["構造価格"])) if structural else hard
            key = cid + "/" + session + "/" + fill["id"] + ":取引:保護価格"
            stops[key] = expected
            audit.check(cid + session + t["建玉ID"] + ":構造保護価格", t["保護価格"], expected)
            audit.check(cid + session + t["建玉ID"] + ":初期125価格", t["初期125保護価格"], hard)
            audit.check(cid + session + t["建玉ID"] + ":設定構造保存", t["構造価格"], r["構造価格"])
            audit.check(cid + session + t["建玉ID"] + ":設定足保存", t["設定足"], r["設定足"])
        if session not in cached:
            cached[session] = U.quotes(entries[session], True)
        q = cached[session]
        row = U.audit_session(d, q, ValuesAudit(audit, stops))
        row.update(A.drawdown(d, q, audit))
        for field, reason in (("構造無効新規取消数", "構造無効で送信前取消"), ("構造未確認新規取消数", "構造未確認で送信前取消")):
            count = sum(o.get("取消理由") == reason for o in d["注文"])
            audit.check(cid + session + ":" + field, d["品質"][field], count)
            row[field] = count
        audit.check(cid + session + ":構造返済数", d["品質"]["構造保護返済数"], sum(t["返済理由"] == "構造保護" for t in d["取引"]))
        audit.check(cid + session + ":終了0", row["終了建玉"], 0)
        audit.check(cid + session + ":返済待機0", row["終了返済待機"], 0)
        for t in d["取引"]:
            first, last = q["at"][t["新規原板行"]], q["at"][t["返済原板行"]]
            side = 1 if t["方向"] == "買い" else -1
            marks = q["bid"] if side == 1 else q["ask"]
            distances = side * (marks[first:last + 1] - t["新規価格"])
            audit.check(cid + t["建玉ID"] + ":直接MFE", t["観測最大順行pt"], max(0, float(np.max(distances))))
            audit.check(cid + t["建玉ID"] + ":直接MAE", t["観測最大逆行pt"], max(0, float(-np.min(distances))))
            if not structural:
                force = q["bounds"][3]
                hits = np.flatnonzero((q["now"][first:last + 1] < force) & ((distances <= -125) | (distances >= 250)))
                if len(hits):
                    at = first + int(hits[0])
                    expected_request = (float(q["now"][at]), int(q["line"][at]),
                                        "保護" if side * (marks[at] - t["新規価格"]) <= -125 else "利確")
                else:
                    expected_request = (force, 0, "期限")
                audit.check(cid + t["建玉ID"] + ":固定の最初返済要求",
                            (t["返済要求時計秒"], t["返済要求原板行"], t["返済理由"]), expected_request)
        audit.check(cid + session + ":入口集合不変", {s["イベントID"] for s in d["入口取扱"]},
                    {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        rows.append(row)
    audit.check("8候補×65場", len(details), 520)
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
        own_metrics = {}
        for period in PERIODS:
            own = [r for r in rows if r["候補ID"] == cid and r["期間"] == period]
            values = operation_metrics(own, cid.endswith("_構造"))
            for field, value in values.items():
                audit.check(cid + period + ":運用集計:" + field, candidate[period]["運用"][field], value)
            base = [t for r in rows if r["候補ID"] == source + "_固定" and r["期間"] == period for t in r["取引"]]
            changed = [t for r in own for t in r["取引"]]
            paired = pair(base, changed)
            for field, value in paired.items():
                audit.check(cid + period + ":共有実新規:" + field, candidate[period]["運用"]["共通新規比較"][field], value)
            entrance_row = next(e for e in result["入口評価"] if e["入口ID"] == source)
            for field, value in entrance_row[period].items():
                audit.check(cid + period + ":保護で入口不変:" + field, candidate[period]["入口"][field], value)
            own_metrics[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values, "共通新規比較": paired})
        qualified = all(all(own_metrics[p][field] >= minimum for field, minimum in limits.items()) and own_metrics[p]["品質注意場数"] == 0
                        and own_metrics[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], qualified)
        qualified_count += qualified
    audit.check("費用資格数", result["費用資格数"], qualified_count)
    expected_ids = [f"{n}分_{m}_{p['出口ID']}" for n in config["時間足分"] for m in config["確認方式"] for p in config["出口"]]
    audit.check("全8の表示で再選択なし", result["表示固定ID"], expected_ids)
    equivalent = old_equivalence(details, audit)
    files = U.artifacts(STUDY, details, result["表示固定ID"], entries, ValuesAudit(audit, stops))
    views = viewer(rows, api, audit) if api else None
    if views:
        H.write(STUDY / "Viewer照合.json", views)
    structural_path = WORK / "構造独立確認.json"
    structural_check = H.read(structural_path) if structural_path.exists() else None
    if structural_check:
        audit.check("構造の原気配因果性独立確認", structural_check["全件一致"], True)
        H.write(STUDY / "構造独立確認.json", structural_check)
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "確認日時": datetime.now(U.HELPER.JST).isoformat(), "コードSHA256": U.sha(Path(__file__)), "全65場既使用": True,
              "固定後SHA変化件数": sum(e["項目"].startswith("固定後SHA:") for e in audit.errors),
              "結果SHA256": U.sha(STUDY / "結果.json"), "入口": entrance, "運用期間別": aggregates,
              "即時固定と元11の同値": equivalent, "正式資源": files, "Viewer記録": "Viewer照合.json" if views else None,
              "構造独立確認": {"参照": "構造独立確認.json", "照合項目数": structural_check["照合項目数"],
                             "コードSHA256": U.sha(ROOT / "scripts/反転確認/構造独立確認.py")} if structural_check else None,
              "独立補助SHA256": {p: U.sha(ROOT / p) for p in ("scripts/テクニカル循環/独立監査.py", "scripts/利益回収/運用独立監査.py",
                                   "scripts/外部探索/運用独立監査.py", "scripts/広域研究/運用独立監査.py", "scripts/入口分析/独立照合.py")},
              "範囲": "保存4入口の全125/250先着を直接再判定。8×65の会計/BBO/待機/保存MFE/MAE/保護価格/DD/正式片・CSV/集計を独立照合。",
              "限界": "入口生成漏れを全原板から再構築した監査ではない。構造の送信前審査と要求初着は別の全記録直接確認に分ける。期間DDは最大一場内DDで累積DDではない。"}
    H.write(STUDY / "独立監査.json", output)
    print(json.dumps({"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors[:10], "元11即時固定": equivalent}, ensure_ascii=False, default=float))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00012原気配・会計・旧即時固定同値監査")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    output = run(args.api_base.rstrip("/") if args.api_base else None)
    if not output["全件一致"]:
        raise SystemExit(1)
