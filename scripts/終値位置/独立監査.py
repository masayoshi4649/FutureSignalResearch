"""CLV選別の二入口先着と三運用会計を、保存値と原正常BBOから検算する。"""

import argparse
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
WORK = ROOT/"work/終値位置/00033"
PREVIOUS = ROOT/"study/00031_CCI持続と上位BB幅"
IDS = ["3分_T0_X0", "3分_T0_XF", "3分_T1_XF"]


def load(path: Path, name: str) -> Any:
    """主モデルを実行せず、固定独立会計だけを読み込む。

    引数: path(Path)は補助コード、name(str)は識別名。
    返り値: Anyはモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


B = load(ROOT/"scripts/CCI突破/独立監査.py", "終値位置の固定31会計")
F, H, U, A, PERIODS = B.F, B.H, B.U, B.A, B.PERIODS


def canonical_sha(value: object) -> str:
    """JSON保存値を精密な固定書式で指紋化する。

    引数: value(object)はJSON化できる値。
    返り値: strはSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def old_identity(value: object) -> object:
    """T0の識別子だけを旧C0へ戻して全属性比較に使う。

    引数: value(object)はJSON値。
    返り値: objectは価格・金額等を変更しない旧識別子の値。
    """
    if isinstance(value, dict):
        return {k: old_identity(v) for k, v in value.items()}
    if isinstance(value, list):
        return [old_identity(v) for v in value]
    return value.replace("_T0", "_C0") if isinstance(value, str) else value


class CSV構造照合:
    """起動出典の辞書欄だけをCSV writerの全値表現で比較する。"""

    def __init__(self, audit: Any) -> None:
        """元照合と対象欄件数を保持する。

        引数: audit(Any)は親の照合記録。
        返り値: None。金額・他欄の比較を変更しない。
        """
        self.audit, self.count = audit, 0

    def check(self, name: str, actual: object, expected: object) -> None:
        """辞書を省略せずwriterと同じ文字列表現で全件比較する。

        引数: name(str)は項目、actual/expected(object)はCSV/正本値。
        返り値: None。他の値は元の型で比較する。
        """
        if name.endswith(":CSV:取引起動判定出典") and isinstance(expected, dict):
            expected = str(expected)
            self.count += 1
        self.audit.check(name, actual, expected)


def trade_path(detail: dict, quotes: dict, config: dict, audit: Any) -> None:
    """保有MFE/MAE・同値床と費用後起動出典を原気配から照合する。

    引数: detail/quotes/config(dict)は保存詳細/正常気配/条件、audit(Any)は照合先。
    返り値: None。最初の起動・要求の全区間走査は別独立追尾へ接続する。
    """
    fee_mode = detail["候補ID"].endswith("_XF")
    cost = 2*Decimal(str(config["数量"]))*Decimal(str(config["片道手数料円"])) + 2*Decimal(str(config["数量"]))*Decimal(str(config["倍率"]))*Decimal(5)
    boundary = cost/(Decimal(str(config["数量"]))*Decimal(str(config["倍率"])))
    for trade in detail["取引"]:
        name = detail["候補ID"]+trade["建玉ID"]
        first, last = quotes["at"][trade["新規原板行"]], quotes["at"][trade["返済原板行"]]
        side = 1 if trade["方向"] == "買い" else -1
        marks = quotes["bid"] if side == 1 else quotes["ask"]
        moves = side*(marks[first:last+1]-trade["新規価格"])
        audit.check(name+":MFE", trade["観測最大順行pt"], max(0, float(F.np.max(moves))))
        audit.check(name+":MAE", trade["観測最大逆行pt"], max(0, float(-F.np.min(moves))))
        audit.check(name+":TP250", trade["固定利確使用"], True)
        audit.check(name+":必須追尾", trade["必須追尾使用"], True)
        audit.check(name+":起動境界", trade["追尾起動幅pt"], float(boundary) if fee_mode else 5)
        audit.check(name+":出口", trade["出口ID"], "XF" if fee_mode else "X0")
        audit.check(name+":D", trade["追尾距離pt"], max(5, F.np.ceil(trade["入口ATR"]/5)*5))
        audit.check(name+":起動後赤字", trade["起動後純赤字"], bool(trade["追尾起動"] and trade["基準純損益円"] < 0))
        if fee_mode:
            for field, expected in (("起動定義", "現在費用控除後strict正"), ("起動境界strict", True),
                ("起動参照費用円", float(cost)), ("起動参照片道滑りpt", 5)):
                audit.check(name+field, trade[field], expected)
        if trade["追尾起動"]:
            audit.check(name+":最低名目同値", side*(trade["最終追尾価格"]-trade["新規価格"]) >= 0, True)
            audit.check(name+":設定線と返済差", trade["最終追尾から実返済方向差pt"], side*(trade["返済価格"]-trade["最終追尾価格"]))
            if fee_mode:
                arm = quotes["at"][trade["追尾起動原板行"]]
                point = Decimal(side)*(Decimal(str(float(marks[arm])))-Decimal(str(trade["新規価格"])))
                gross = point*Decimal(str(config["数量"]))*Decimal(str(config["倍率"]))
                net = gross-cost
                exact = Fraction(net)
                expected = {"返済気配": float(marks[arm]), "新規価格": trade["新規価格"], "実side": side,
                    "名目利益pt": float(point), "粗含み益円": float(gross), "控除後含み益円": float(net),
                    "控除後含み益円分子": exact.numerator, "控除後含み益円分母": exact.denominator,
                    "strict正": net > 0, "起動参照費用円": float(cost), "起動参照片道滑りpt": 5,
                    "境界pt": float(boundary), "価格時計秒": float(quotes["now"][arm]),
                    "原板行": trade["追尾起動原板行"], "元bid": float(quotes["bid"][arm]), "元ask": float(quotes["ask"][arm])}
                audit.check(name+":費用後strict正", net > 0, True)
                audit.check(name+":起動時計", trade["追尾起動時計秒"], expected["価格時計秒"])
                audit.check(name+":起動全出典", trade["起動判定出典"], expected)
        else:
            audit.check(name+":未起動線なし", trade["最終追尾価格"], None)
            if fee_mode:
                audit.check(name+":未起動出典なし", trade["起動判定出典"], None)


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """三運用のViewer価格・約定・損益と全198資源を検査する。

    引数: rows(list[dict])は独立場会計、api(str)は接続先、audit(Any)は照合先。
    返り値: dictは表示確認。代表選択は売買選択に使わない。
    """
    helper = load(ROOT/"scripts/複合検証/Viewer照合.py", "終値位置のViewer確認")
    path = STUDY/"一覧.resources.json"
    resources = {(r["method_id"], r["session"]): r for r in H.read(path)["resources"]}
    body, _ = helper.fetch(api+"/api/resources?"+helper.urlencode({"catalog_path": path.relative_to(ROOT).as_posix()}))
    audit.check("Viewer全資源集合", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    checks = []
    for cid in IDS:
        own = [r for r in rows if r["候補ID"] == cid]
        selected = sorted(own, key=lambda r: (-abs(r["観測現金増減円"]), r["場"]))[0]
        adapted = {"銘柄": "NK225", "場": selected["場"], "手法": cid,
            "純損益円": float(selected["観測現金増減円"]), "取引数": selected["完結取引数"]}
        item = helper.check_one(api, STUDY, adapted, resources[cid, selected["場"]], "事前三運用の代表", False)
        item.update(観測経路注意=selected["観測経路注意"], 確定対象純損益円=selected["確定対象純損益円"])
        checks.append(item)
    with urlopen(api+"/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
        "代表規則": "事前T0_X0/T0_XF/T1_XF。各案最大絶対観測現金増減場、同値は場順。売買採否へ不使用。",
        "照合": checks, "追加PNG数": 0,
        "Viewer実行コピーSHA256": U.sha(ROOT/"work/viewer/session-trade-viewer.exe"),
        "指定配布版SHA256": U.sha(ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe")}


def run(api: str | None) -> dict:
    """全先着・全三運用を検算し、状態と追尾証拠へ接続する。

    引数: api(str|None)はViewer接続先。
    返り値: dictは明示合否・範囲・指紋。主モデルや結果を変更しない。
    """
    audit = U.Audit()
    config, result, fixed = (H.read(STUDY/name) for name in ("条件.json", "結果.json", "固定.json"))
    for name, expected in fixed["ファイルSHA256"].items():
        audit.check("固定:"+name, U.sha(ROOT/name), expected)
    pointer = H.read(STUDY/"入力台帳.json")
    manifest_path = (STUDY/pointer["参照"]).resolve()
    audit.check("解決台帳指紋", U.sha(manifest_path), pointer["SHA256"])
    manifest = H.read(manifest_path)
    entries = {e["session"]: e for e in manifest["entries"]}
    audit.check("入力66場一意", len(entries), 66)
    audit.check("入力66行", len(manifest["entries"]), 66)
    reference = H.read(STUDY/"入口参照.json")
    for name, item in reference["文書と証明"].items():
        audit.check("共有証明:"+name, U.sha(ROOT/item["パス"]), item["SHA256"])
    shared = {Path(r["パス"]).name: r for r in reference["共有明細"]}
    for name, item in shared.items():
        audit.check("共有明細:"+name, U.sha(ROOT/item["パス"]), item["圧縮SHA256参考"])
    old_cases, case_sha = H.rows(ROOT/shared["入口事例.jsonl.gz"]["パス"])
    old_cases = [r for r in old_cases if r["入口ID"] == "3分_C0"]
    old_lookup = {r["イベントID"]: r for r in old_cases}
    audit.check("共有先着展開版", case_sha, shared["入口事例.jsonl.gz"]["展開内容SHA256"])
    shapes, shape_sha = H.rows(WORK/"形状選別.jsonl.gz")
    cases, chosen = [], {p: set() for p in ("T0", "T1")}
    for shape in shapes:
        for policy in chosen:
            if not shape[policy+"採用"]:
                continue
            old_id = shape["旧イベントID"]
            audit.check(policy+old_id+":一意", old_id not in chosen[policy], True)
            chosen[policy].add(old_id)
            row = deepcopy(old_lookup[old_id])
            row.update(入口ID="3分_"+policy, イベントID=old_id[:-3]+"_"+policy)
            for key in ("場", "side", "要求時計秒", "要求原板行", "確認遅延秒"):
                audit.check(row["イベントID"]+key, row[key], shape[key])
            cases.append(row)
    audit.check("T0共有C0全集合", chosen["T0"], set(old_lookup))
    audit.check("T1純subset", chosen["T1"] <= chosen["T0"], True)
    audit.check("旧先着証明成功", H.read(PREVIOUS/"独立監査.json")["全件一致"], True)
    entrance = B.entry_audit(cases, result, entries, config, audit)
    previous_result = next(r for r in H.read(PREVIOUS/"結果.json")["入口評価"] if r["入口ID"] == "3分_C0")
    t0 = next(r for r in result["入口評価"] if r["入口ID"] == "3分_T0")
    for period in PERIODS:
        audit.check("T0旧入口集計:"+period, t0[period], previous_result[period])
    stats = {}
    for item in H.read(STUDY/"作業成果物.json")["ファイル"]:
        path = ROOT/item["パス"]
        digest, count = F.content_stats(path)
        audit.check("新明細展開:"+path.name, digest, item["展開内容SHA256"])
        stats[path.name] = digest, count
    details, detail_sha = H.rows(WORK/"全運用詳細.jsonl.gz")
    logs, log_sha = H.rows(WORK/"追尾.jsonl.gz")
    old_details, _ = H.rows(ROOT/shared["全運用詳細.jsonl.gz"]["パス"])
    old_logs, _ = H.rows(ROOT/shared["追尾.jsonl.gz"]["パス"])
    old_details = {r["場"]: r for r in old_details if r["候補ID"] == "3分_C0_X0"}
    old_group = {}
    for row in old_logs:
        if row["候補ID"] == "3分_C0_X0":
            old_group.setdefault(row["場"], []).append(row)
    detail_map, quotes, rows, grouped_logs = {}, {}, [], {}
    for log in logs:
        grouped_logs.setdefault((log["候補ID"], log["場"]), []).append(log)
    events = {(r["入口ID"], r["場"], r["イベントID"]): r for r in cases}
    for detail in details:
        cid, session = detail["候補ID"], detail["場"]
        key = cid, session
        audit.check(str(key)+":重複なし", key not in detail_map, True)
        detail_map[key] = detail
        source = cid.rsplit("_", 1)[0]
        if session not in quotes:
            quotes[session] = U.quotes(entries[session], True)
        q = quotes[session]
        row = U.audit_session(detail, q, audit)
        row.update(A.drawdown(detail, q, audit), 通常線更新回数=0,
            追尾線更新回数=sum(r["動作"] == "追尾線更新" for r in grouped_logs.get(key, [])))
        trade_path(detail, q, config["運用"], audit)
        audit.check(str(key)+":線更新数", detail["品質"]["追尾線更新回数"], row["追尾線更新回数"])
        for field in ("終了建玉", "終了返済待機"):
            audit.check(str(key)+field, row[field], detail["品質"][field])
        if row["終了建玉"] or row["終了返済待機"]:
            audit.check(str(key)+":未解消品質", row["観測経路注意"], True)
            audit.check(str(key)+":未解消確定不能", row["確定対象純損益円"], None)
        audit.check(str(key)+":入口全集合", {r["イベントID"] for r in detail["入口取扱"]},
            {r["イベントID"] for r in cases if r["入口ID"] == source and r["場"] == session})
        for signal in detail["入口取扱"]:
            original = events[source, session, signal["イベントID"]]
            for field in ("要求時計秒", "要求原板行", "side", "確認遅延秒"):
                audit.check(cid+signal["イベントID"]+field, signal[field], original[field])
        for trade in detail["取引"]:
            audit.check(cid+trade["建玉ID"]+":ATR", trade["入口ATR"], events[source, session, trade["入口イベントID"]]["atr"])
            audit.check(cid+trade["建玉ID"]+":役割", trade["入口役割"], "順行")
        if cid == "3分_T0_X0":
            audit.check(session+":旧C0全運用", old_identity(detail), old_details[session])
            audit.check(session+":旧C0全追尾", old_identity(grouped_logs.get(key, [])), old_group.get(session, []))
        row.update(期間=detail["品質"]["期間"], 場時間分=detail["品質"]["場時間分"])
        rows.append(row)
    audit.check("三運用66場全集合", set(detail_map), {(cid, s) for cid in IDS for s in entries})
    audit.check("事前表示順", result["表示固定ID"], IDS)
    audit.check("三結果", [r["候補ID"] for r in result["結果"]], IDS)
    control_path = STUDY/"T0対照同値.json"
    control = H.read(control_path)
    audit.check("対照成功", control["全件一致"], True)
    audit.check("対照66群", control["場候補数"], 66)
    audit.check("対照共有版", control["入口参照SHA256"], U.sha(STUDY/"入口参照.json"))
    audit.check("対照群全集合", {(r["候補ID"], r["場"]) for r in control["照合"]}, {("3分_T0_X0", s) for s in entries})
    for item in control["照合"]:
        key = item["候補ID"], item["場"]
        audit.check(str(key)+":対照運用指紋", item["旧識別子全運用内容SHA256"], canonical_sha(old_identity(detail_map[key])))
        audit.check(str(key)+":対照追尾指紋", item["旧識別子追尾内容SHA256"], canonical_sha(old_identity(grouped_logs.get(key, []))))
    csv = U.table(STUDY/"全候補_場別.csv")
    table = {(r["手法"], r["場"]): r for r in csv}
    audit.check("場別CSV一意", len(table), len(csv))
    audit.check("場別CSV全集合", set(table), set(detail_map))
    for key, detail in detail_map.items():
        for field, value in detail["品質"].items():
            audit.check(str(key)+":場別CSV:"+field, table[key][field], value)
    aggregates, qualified, current_qualified, adopted = [], 0, 0, 0
    for candidate in result["結果"]:
        cid = candidate["候補ID"]
        support, goal = entrance["支持"][candidate["入口"]["入口ID"]]
        audit.check(cid+":支持コピー", candidate["入口支持"], support)
        audit.check(cid+":目標コピー", candidate["70目標"], goal)
        periods = {}
        for period in PERIODS:
            values = B.metrics([r for r in rows if r["候補ID"] == cid and r["期間"] == period])
            for field, value in values.items():
                audit.check(cid+period+field, candidate[period]["運用"][field], value)
            original = next(r for r in result["入口評価"] if r["入口ID"] == candidate["入口"]["入口ID"])
            audit.check(cid+period+":入口コピー", candidate[period]["入口"], original[period])
            periods[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values})
        okay = all(all(periods[p][field] >= minimum for field, minimum in limits.items()) and periods[p]["品質注意場数"] == 0
            and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid+":費用資格", candidate["費用資格"], okay)
        current = cid.endswith("_XF")
        audit.check(cid+":現方針候補", candidate["現方針候補"], current)
        audit.check(cid+":採用資格", candidate["採用資格"], current and goal and okay)
        qualified += okay
        current_qualified += current and okay
        adopted += current and goal and okay
    audit.check("費用資格数", result["費用資格数"], qualified)
    audit.check("現方針費用資格数", result["現方針費用資格数"], current_qualified)
    audit.check("採用資格数", result["採用資格数"], adopted)
    artifact_audit = CSV構造照合(audit)
    files = U.artifacts(STUDY, detail_map, IDS, entries, artifact_audit)
    files.update(CSV起動出典辞書欄数=artifact_audit.count, CSV構造欄規約="起動判定出典dictだけwriterのstr全表記と比較。他値/JSONL/金額の型比較は不変")
    if api:
        H.write(STUDY/"Viewer照合.json", viewer(rows, api, audit))
    proofs = {}
    for name in ("状態独立確認", "追尾独立確認"):
        path = WORK/(name+".json")
        if not path.exists():
            continue
        proof = H.read(path)
        for field, expected in (("全件一致", True), ("不一致数", 0), ("不一致", []),
            ("コードSHA256", U.sha(Path(__file__).with_name(name+".py"))),
            ("入力台帳SHA256", U.sha(STUDY/"入力台帳.json")), ("参照入力台帳SHA256", U.sha(manifest_path)),
            ("入口参照SHA256", U.sha(STUDY/"入口参照.json")), ("入口事例展開SHA256", case_sha),
            ("主準備SHA256", U.sha(WORK/"準備点検.json")), ("結果SHA256", U.sha(STUDY/"結果.json"))):
            audit.check(name+field, proof[field], expected)
        if name == "状態独立確認":
            audit.check(name+":条件版", proof["条件SHA256"], U.sha(STUDY/"条件.json"))
            audit.check(name+":全新明細", set(proof["成果物照合"]), set(stats))
            for filename, values in proof["成果物照合"].items():
                audit.check(filename+":内容指紋", values["展開内容SHA256"], stats[filename][0])
                audit.check(filename+":全行数", values["行数"], stats[filename][1])
        else:
            for field, expected in (("全運用詳細展開SHA256", detail_sha), ("追尾展開SHA256", log_sha), ("保存追尾行数", len(logs)),
                ("対象完結取引数", sum(len(d["取引"]) for d in details)), ("結果SHA256", U.sha(STUDY/"結果.json")),
                ("状態独立確認SHA256", U.sha(WORK/"状態独立確認.json"))):
                audit.check(name+field, proof[field], expected)
        destination = STUDY/(name+".json")
        H.write(destination, proof)
        proofs[name] = {"ファイル": destination.name, "SHA256": U.sha(destination),
            "全件一致": proof["全件一致"], "照合項目数": proof["照合項目数"]}
    complete = len(proofs) == 2
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
        "確認日時": datetime.now(U.HELPER.JST).isoformat(), "コードSHA256": U.sha(Path(__file__)),
        "結果SHA256": U.sha(STUDY/"結果.json"), "入口参照SHA256": U.sha(STUDY/"入口参照.json"),
        "全66場既使用": True, "状態確認未完": "状態独立確認" not in proofs, "追尾確認未完": "追尾独立確認" not in proofs,
        "入口": entrance, "運用期間別": aggregates, "正式資源": files, "別計算証明": proofs,
        "T0対照証明": {"ファイル": control_path.name, "SHA256": U.sha(control_path), "場候補数": 66},
        "Viewer記録": "Viewer照合.json" if api else None,
        "一致の範囲": "旧C0先着を選別した二入口全件を原正常BBOから直接再判定。三運用198群のDecimal会計/注文/約定/帰属/費用/品質/MFE/MAE/DD/名目同値/CSV/Viewer、旧C0対照全属性を照合。CLVと公開採否/費用後現在正の最初起動・追尾要求は独立証明へ接続。",
        "限界": "全66場既使用。価格時計は受信時計ではなく、実micro指値/約定は未確認。品質注意期の全体確定額はnull。場内DDを期間接合DDと呼ばない。"}
    H.write(STUDY/"独立監査.json" if complete else WORK/"会計監査_途中.json", output)
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "状態確認未完", "追尾確認未完")}, ensure_ascii=False))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00033二入口・三運用の独立会計")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    if not run(args.api_base.rstrip("/") if args.api_base else None)["全件一致"]:
        raise SystemExit(1)
