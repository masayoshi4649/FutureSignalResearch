"""共有入口の先着証明と、新しい四運用の会計・追尾・Viewerを接続する。"""

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00032_最低同値床と公開SAR追尾"
WORK = ROOT / "work/SAR追尾/00032"
PREVIOUS = ROOT / "study/00031_CCI持続と上位BB幅"
IDS = [f"3分_{entry}_{policy}" for entry in ("C0", "C1") for policy in ("X0", "XS")]


def load(path: Path, name: str) -> Any:
    """固定の独立会計補助を読み、主運用は起動しない。

    引数: path(Path)は補助コード、name(str)はモジュール名。
    返り値: Anyは読取モジュール。32の主SAR/運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = load(ROOT / "scripts/CCI突破/独立監査.py", "SAR追尾の固定入口会計補助")
F, H, U, A, PERIODS = B.F, B.H, B.U, B.A, B.PERIODS


def canonical_sha(rows: list) -> str:
    """保存列を固定JSON書式で指紋化する。

    引数: rows(list)は明細又は追尾の保存値。
    返り値: strはUTF-8正規書式のSHA256。主指標を呼ばない。
    """
    body = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class CSV構造照合:
    """CSVがstr化するSAR参照欄だけを、同じ出力表現で照合する。"""

    def __init__(self, audit: Any) -> None:
        """既存会計の照合先と構造欄の件数を保持する。

        引数: audit(Any)は親の独立照合記録。
        返り値: None。数値・金額・JSONLの比較を変更しない。
        """
        self.audit, self.structured = audit, 0

    def check(self, name: str, actual: object, expected: object) -> None:
        """辞書欄をCSV writerのstr表現で比較し、他は元の型で比較する。

        引数: name(str)は照合項目、actual/expected(object)はCSV読取値/正本。
        返り値: None。SAR参照を省略せず全キー・値・表記を照合する。
        """
        if name.endswith(":CSV:取引最終SAR適用参照") and isinstance(expected, dict):
            expected = str(expected)
            self.structured += 1
        self.audit.check(name, actual, expected)


def trade_path(detail: dict, quotes: dict, audit: Any) -> None:
    """実保有MFE/MAEと同値床を照合し、SARにATR幅を偽装しない。

    引数: detail(dict)は場別明細、quotes(dict)は原正常BBO、audit(Any)は照合記録。
    返り値: None。SARの精密線・最初要求は別の追尾証明へ接続する。
    """
    sar = detail["候補ID"].endswith("_XS")
    for trade in detail["取引"]:
        name = detail["候補ID"] + trade["建玉ID"]
        first, last = quotes["at"][trade["新規原板行"]], quotes["at"][trade["返済原板行"]]
        side = 1 if trade["方向"] == "買い" else -1
        marks = quotes["bid"] if side == 1 else quotes["ask"]
        moves = side*(marks[first:last+1]-trade["新規価格"])
        audit.check(name + ":直接MFE", trade["観測最大順行pt"], max(0, float(F.np.max(moves))))
        audit.check(name + ":直接MAE", trade["観測最大逆行pt"], max(0, float(-F.np.min(moves))))
        audit.check(name + ":TP250", trade["固定利確使用"], True)
        audit.check(name + ":必須追尾", trade["必須追尾使用"], True)
        audit.check(name + ":初回床A5", trade["追尾起動幅pt"], 5)
        audit.check(name + ":出口ID", trade["出口ID"], "XS" if sar else "X0")
        distance = None if sar else max(5, F.np.ceil(trade["入口ATR"]/5)*5)
        audit.check(name + ":ATR幅の使用区別", trade["追尾距離pt"], distance)
        audit.check(name + ":起動後赤字", trade["起動後純赤字"], bool(trade["追尾起動"] and trade["基準純損益円"] < 0))
        if trade["追尾起動"]:
            audit.check(name + ":名目最低同値", side*(trade["最終追尾価格"]-trade["新規価格"]) >= 0, True)
            audit.check(name + ":起動出典存在", trade["追尾起動時計秒"] is not None and trade["追尾起動原板行"] is not None, True)
            audit.check(name + ":設定線と実返済差", trade["最終追尾から実返済方向差pt"], side*(trade["返済価格"]-trade["最終追尾価格"]))
        else:
            audit.check(name + ":未起動の線なし", trade["最終追尾価格"], None)


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """事前に決めた四運用を価格・約定・損益のAPIで照合する。

    引数: rows(list[dict])は独立会計、api(str)はViewer URL、audit(Any)は照合先。
    返り値: dictは四代表と全資源の確認。表示代表を売買選択に使わない。
    """
    helper = load(ROOT / "scripts/複合検証/Viewer照合.py", "SAR追尾のViewer確認")
    catalog_path = STUDY / "一覧.resources.json"
    resources = {(r["method_id"], r["session"]): r for r in H.read(catalog_path)["resources"]}
    body, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": catalog_path.relative_to(ROOT).as_posix()}))
    audit.check("Viewer全資源集合", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    checked = []
    for cid in IDS:
        own = [r for r in rows if r["候補ID"] == cid]
        selected = sorted(own, key=lambda r: (-abs(r["観測現金増減円"]), r["場"]))[0]
        adapted = {"銘柄": "NK225", "場": selected["場"], "手法": cid,
            "純損益円": float(selected["観測現金増減円"]), "取引数": selected["完結取引数"]}
        item = helper.check_one(api, STUDY, adapted, resources[cid, selected["場"]], "事前四運用の代表", False)
        item.update(観測経路注意=selected["観測経路注意"], 確定対象純損益円=selected["確定対象純損益円"])
        checked.append(item)
    with urlopen(api + "/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
        "代表規則": "事前C0/C1×X0/XS。各運用の最大絶対観測現金増減場、同値は場順。表示選択は売買採用に使わない。",
        "照合": checked, "追加PNG数": 0,
        "Viewer実行コピーSHA256": U.sha(ROOT / "work/viewer/session-trade-viewer.exe"),
        "指定配布版SHA256": U.sha(ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe")}


def run(api: str | None) -> dict:
    """四運用の全会計を検算し、二つの独立証明が揃えば正式保存する。

    引数: api(str | None)はViewer接続先。
    返り値: dictは範囲・明示合否・出典。旧入口明細や主結果を変更しない。
    """
    audit = U.Audit()
    config, result, fixed = H.read(STUDY / "条件.json"), H.read(STUDY / "結果.json"), H.read(STUDY / "固定.json")
    for name, expected in fixed["ファイルSHA256"].items():
        audit.check("固定:" + name, U.sha(ROOT / name), expected)
    pointer = H.read(STUDY / "入力台帳.json")
    manifest_path = (STUDY / pointer["参照"]).resolve()
    audit.check("入力台帳指紋", U.sha(manifest_path), pointer["SHA256"])
    manifest = H.read(manifest_path)
    entries = {e["session"]: e for e in manifest["entries"]}
    audit.check("入力一意66場", len(entries), 66)
    audit.check("入力全66行", len(manifest["entries"]), 66)
    reference = H.read(STUDY / "入口参照.json")
    for name, item in reference["文書と証明"].items():
        audit.check("入口参照:" + name, U.sha(ROOT / item["パス"]), item["SHA256"])
    shared = {Path(item["パス"]).name: item for item in reference["共有明細"]}
    for name, item in shared.items():
        audit.check("旧共有明細:" + name, U.sha(ROOT / item["パス"]), item["圧縮SHA256参考"])
    cases, case_sha = H.rows(ROOT / shared["入口事例.jsonl.gz"]["パス"])
    audit.check("共有入口の展開版", case_sha, shared["入口事例.jsonl.gz"]["展開内容SHA256"])
    old_result, old_proof = H.read(PREVIOUS / "結果.json"), H.read(PREVIOUS / "独立監査.json")
    audit.check("旧31会計証明成功", old_proof["全件一致"], True)
    audit.check("二入口評価の不変", result["入口評価"], old_result["入口評価"])
    entrance = B.entry_audit(cases, result, entries, config, audit)
    entrance.update(共有試行="00031", 新しい入口仮説=False,
        限界="同一の既使用入力・共有入口を再照合したもので、独立した新市場標本や新しい未見性能ではない。SAR値/公開時点とlive信号whitelistは状態証明へ接続する。")
    stats = {}
    for item in H.read(STUDY / "作業成果物.json")["ファイル"]:
        path = ROOT / item["パス"]
        digest, count = F.content_stats(path)
        audit.check("新成果物展開版:" + path.name, digest, item["展開内容SHA256"])
        stats[path.name] = digest, count
    details, detail_sha = H.rows(WORK / "全運用詳細.jsonl.gz")
    logs, log_sha = H.rows(WORK / "追尾.jsonl.gz")
    updates, detail_map, quotes, rows, grouped_logs = {}, {}, {}, [], {}
    for log in logs:
        key = log["候補ID"], log["場"]
        updates[key] = updates.get(key, 0) + (log["動作"] == "追尾線更新")
        grouped_logs.setdefault(key, []).append(log)
    event_map = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    for detail in details:
        cid, session = detail["候補ID"], detail["場"]
        if (cid, session) in detail_map:
            raise ValueError("候補と場が重複")
        detail_map[cid, session] = detail
        source = cid.rsplit("_", 1)[0]
        if session not in quotes:
            quotes[session] = U.quotes(entries[session], True)
        q = quotes[session]
        row = U.audit_session(detail, q, audit)
        row.update(A.drawdown(detail, q, audit), 通常線更新回数=0, 追尾線更新回数=updates.get((cid, session), 0))
        trade_path(detail, q, audit)
        audit.check(cid + session + ":線更新数", detail["品質"]["追尾線更新回数"], row["追尾線更新回数"])
        audit.check(cid + session + ":終了建玉の記録", row["終了建玉"], detail["品質"]["終了建玉"])
        audit.check(cid + session + ":終了返済待機の記録", row["終了返済待機"], detail["品質"]["終了返済待機"])
        if row["終了建玉"] or row["終了返済待機"]:
            audit.check(cid + session + ":未解消は品質注意", row["観測経路注意"], True)
            audit.check(cid + session + ":未解消は確定不能", row["確定対象純損益円"], None)
        audit.check(cid + session + ":入口受渡全集合", {r["イベントID"] for r in detail["入口取扱"]},
            {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        for signal in detail["入口取扱"]:
            entry = event_map[source, session, signal["イベントID"]]
            for key in ("要求時計秒", "要求原板行", "side", "確認遅延秒"):
                audit.check(cid + signal["イベントID"] + key, signal[key], entry[key])
        for trade in detail["取引"]:
            audit.check(cid + trade["建玉ID"] + ":入口ATR", trade["入口ATR"], event_map[source, session, trade["入口イベントID"]]["atr"])
            audit.check(cid + trade["建玉ID"] + ":入口役割", trade["入口役割"], "順行")
        row["期間"], row["場時間分"] = detail["品質"]["期間"], detail["品質"]["場時間分"]
        rows.append(row)
    audit.check("全四運用×66場", set(detail_map), {(cid, s) for cid in IDS for s in entries})
    audit.check("表示固定順序", result["表示固定ID"], IDS)
    audit.check("結果四案", [r["候補ID"] for r in result["結果"]], IDS)
    control_path = STUDY / "X0対照同値.json"
    control = H.read(control_path)
    audit.check("旧31X0対照成功", control["全件一致"], True)
    audit.check("旧31X0対照132場候補", control["場候補数"], 132)
    audit.check("旧31X0対照の入口版", control["入口参照SHA256"], U.sha(STUDY / "入口参照.json"))
    control_keys = {(r["候補ID"], r["場"]) for r in control["照合"]}
    audit.check("旧31X0対照全集合", control_keys, {(cid, s) for cid in IDS if cid.endswith("_X0") for s in entries})
    audit.check("旧31X0対照重複なし", len(control_keys), len(control["照合"]))
    for item in control["照合"]:
        key = item["候補ID"], item["場"]
        audit.check(str(key) + ":全運用同値宣言", item["全運用同値"], True)
        audit.check(str(key) + ":全追尾同値宣言", item["全追尾同値"], True)
        audit.check(str(key) + ":現在詳細へbind", item["全運用内容SHA256"], canonical_sha([detail_map[key]]))
        audit.check(str(key) + ":現在追尾へbind", item["追尾内容SHA256"], canonical_sha(grouped_logs.get(key, [])))
    aggregates, qualified = [], 0
    for candidate in result["結果"]:
        cid, source = candidate["候補ID"], candidate["候補ID"].rsplit("_", 1)[0]
        periods = {}
        for phase in PERIODS:
            values = B.metrics([r for r in rows if r["候補ID"] == cid and r["期間"] == phase])
            for key, value in values.items():
                audit.check(cid + phase + key, candidate[phase]["運用"][key], value)
            original = next(r for r in result["入口評価"] if r["入口ID"] == source)
            audit.check(cid + phase + ":共有入口集計", candidate[phase]["入口"], {k: original[phase][k] for k in candidate[phase]["入口"]})
            periods[phase] = values
            aggregates.append({"候補ID": cid, "期間": phase, **values})
        okay = all(all(periods[p][field] >= n for field, n in limits.items()) and periods[p]["品質注意場数"] == 0
            and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid + ":費用資格", candidate["費用資格"], okay)
        qualified += okay
    audit.check("費用資格数", result["費用資格数"], qualified)
    artifact_audit = CSV構造照合(audit)
    files = U.artifacts(STUDY, detail_map, IDS, entries, artifact_audit)
    files.update(CSV構造化参照欄数=artifact_audit.structured,
        CSV構造欄の規約="最終SAR適用参照はCSV writerが辞書をstr化した表記と全件比較。JSONL/金額/他列の型比較は変更しない。")
    if api:
        H.write(STUDY / "Viewer照合.json", viewer(rows, api, audit))
    proofs = {}
    for name in ("状態独立確認", "追尾独立確認"):
        path = WORK / (name + ".json")
        if not path.exists():
            continue
        proof = H.read(path)
        audit.check(name + ":成功", proof["全件一致"], True)
        audit.check(name + ":実装版", proof["コードSHA256"], U.sha(ROOT / "scripts/SAR追尾" / (name + ".py")))
        audit.check(name + ":入力版", proof["入力台帳SHA256"], U.sha(STUDY / "入力台帳.json"))
        audit.check(name + ":解決台帳版", proof["参照入力台帳SHA256"], U.sha(manifest_path))
        audit.check(name + ":共有入口版", proof["入口事例展開SHA256"], case_sha)
        audit.check(name + ":入口参照版", proof["入口参照SHA256"], U.sha(STUDY / "入口参照.json"))
        if name == "状態独立確認":
            audit.check(name + ":新成果物集合", set(proof["成果物照合"]), set(stats))
            for filename, values in proof["成果物照合"].items():
                audit.check(filename + ":展開内容", values["展開内容SHA256"], stats[filename][0])
                audit.check(filename + ":行数", values["行数"], stats[filename][1])
        else:
            for key, value in (("全運用詳細展開SHA256", detail_sha), ("追尾展開SHA256", log_sha), ("保存追尾行数", len(logs)),
                ("対象完結取引数", sum(len(d["取引"]) for d in details)), ("結果SHA256", U.sha(STUDY / "結果.json")),
                ("状態独立確認SHA256", U.sha(WORK / "状態独立確認.json"))):
                audit.check(name + key, proof[key], value)
        destination = STUDY / (name + ".json")
        H.write(destination, proof)
        proofs[name] = {"ファイル": destination.name, "SHA256": U.sha(destination), "全件一致": proof["全件一致"], "照合項目数": proof["照合項目数"]}
    complete = len(proofs) == 2
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
        "確認日時": datetime.now(U.HELPER.JST).isoformat(), "全66場既使用": True,
        "状態確認未完": "状態独立確認" not in proofs, "追尾確認未完": "追尾独立確認" not in proofs,
        "コードSHA256": U.sha(Path(__file__)), "結果SHA256": U.sha(STUDY / "結果.json"),
        "入口参照SHA256": U.sha(STUDY / "入口参照.json"), "入口": entrance, "運用期間別": aggregates,
        "場内未解消候補場数": sum(bool(r["終了建玉"] or r["終了返済待機"]) for r in rows),
        "正式資源": files, "別計算証明": proofs, "Viewer記録": "Viewer照合.json" if api else None,
        "X0対照証明": {"ファイル": control_path.name, "SHA256": U.sha(control_path), "場候補数": control["場候補数"]},
        "会計補助SHA256": {str(p.relative_to(ROOT).as_posix()): U.sha(p) for p in (ROOT / "scripts/CCI突破/独立監査.py", ROOT / "scripts/局面切替/独立監査.py")},
        "一致の範囲": "固定31の共有二入口・全先着を直接再照合し、四運用のDecimal注文/約定/帰属/単一建玉/費用/品質/MFE/MAE/DD/同値床/CSV/Viewerを照合。精密SAR・公開時点・全最初要求は別の状態/追尾証明へ接続。",
        "限界": "同じ既使用66場の比較。価格時計は実受信時計ではなく、ラージBBO代理は実micro約定を保証しない。注意期の全体確定額はnull。場内DDを期間接合したDDと呼ばない。二入口と四運用の件数を区別する。"}
    H.write(STUDY / "独立監査.json" if complete else WORK / "会計監査_途中.json", output)
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "状態確認未完", "追尾確認未完")}, ensure_ascii=False))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00032共有入口と四運用の独立会計")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    if not run(args.api_base.rstrip("/") if args.api_base else None)["全件一致"]:
        raise SystemExit(1)
