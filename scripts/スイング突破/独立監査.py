"""同時点新規の最初約定・全Decimal会計と、独立先着/追尾/Viewerを接続する。"""

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
STUDY = ROOT/"study/00045_確定スイング突破と方向優勢"
WORK = ROOT/"work/スイング突破/00045"
IDS = ["3分_C0_XF", "3分_C1_XF", "3分_C2_XF"]
PERIODS = ("学習", "条件選択", "後続検査")
FILES = ("全指標.jsonl.gz", "価格状態.jsonl.gz", "発動判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")


def load(path: Path, name: str) -> Any:
    """主モデルを起動せず、独立会計補助を読み込む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyはモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


G = load(ROOT/"scripts/終値位置/独立監査.py", "スイング突破の固定33独立費用会計")
N_PATH = ROOT/"scripts/突破指値/新規会計.py"
N = load(N_PATH, "スイング突破の固定34即時受付枝")
F, H, U, A = G.F, G.H, G.U, G.A


def code_pins() -> dict:
    """主4コードの現在指紋だけを取得する。

    引数: なし。
    返り値: dictは主接続/入口/指標/運用のリポジトリ相対パスとSHA。主をimportしない。
    """
    return {p.relative_to(ROOT).as_posix(): U.sha(p) for p in
        [Path(__file__).with_name(name) for name in ("検証.py", "入口.py", "指標.py", "運用.py")]}


def definition_binding(prepared: dict, fixed: dict, audit: Any) -> dict:
    """DMIの正本4列小型定義を実blobと固定指紋へ結合する。

    引数: prepared/fixed(dict)は主準備/固定、audit(Any)は照合先。
    返り値: dictはパス/圧縮SHA256参考/展開内容SHA256/行数。DIの値や優勢を再計算しない。
    """
    value = prepared["DMI数値定義"]
    audit.check("DMI定義四項目", set(value), {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"})
    path = (ROOT/value["パス"]).resolve()
    audit.check("DMI定義保存範囲", path.is_relative_to(WORK.resolve()), True)
    current = U.sha(path)
    audit.check("DMI定義圧縮SHA", current, value["圧縮SHA256参考"])
    audit.check("DMI定義固定SHA", fixed["ファイルSHA256"].get(path.relative_to(ROOT).as_posix()), current)
    digest, count = F.content_stats(path)
    audit.check("DMI定義展開SHA", digest, value["展開内容SHA256"])
    audit.check("DMI定義全行", count, value["行数"])
    return value


def sha_value(value: object) -> str:
    """保存値を固定JSON書式で指紋化する。

    引数: value(object)はJSON保存値。
    返り値: strはSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()




class CSV構造照合:
    """費用後起動出典の辞書欄だけをwriterの全表現で比較する。"""

    def __init__(self, audit: Any) -> None:
        """親照合と構造欄件数を初期化する。

        引数: audit(Any)は親の照合。
        返り値: None。金額/他欄/JSONLの型比較を変えない。
        """
        self.audit, self.count = audit, 0

    def check(self, name: str, actual: object, expected: object) -> None:
        """特定の辞書欄を省略せず、CSVの保存形式へ合わせる。

        引数: name(str)は項目、actual/expected(object)はCSV/正本。
        返り値: None。辞書の全キー・値・順序を文字列表現で比較する。
        """
        fields = (":CSV:取引起動判定出典",)
        if name.endswith(fields) and isinstance(expected, dict):
            expected = str(expected)
            self.count += 1
        self.audit.check(name, actual, expected)


def entry_summary(cases: list[dict], result: dict, config: dict, audit: Any) -> dict:
    """保存caseの期間指標・支持・目標を独立に集計する。

    引数: cases(list[dict])は新三入口、result/config(dict)は正本/条件、audit(Any)は照合先。
    返り値: dictは支持と集計。全直接先着は状態独立証明へ接続する。
    """
    summaries, supports = [], {}
    keys = [(r["入口ID"], r["イベントID"]) for r in cases]
    audit.check("新case入口event一意", len(set(keys)), len(keys))
    old_keys = {}
    for source in result["入口評価"]:
        sid, periods = source["入口ID"], {}
        local = [r for r in cases if r["入口ID"] == sid]
        old_keys[sid] = {(r["元価格発動ID"], r["side"], r["役割"]) for r in local}
        for period in PERIODS:
            values = H.entry_metrics([r for r in local if r["期間"] == period], period)
            for field, expected in values.items():
                audit.check(sid+period+field, source[period][field], expected)
            periods[period] = values
            summaries.append({"入口ID": sid, "期間": period, **values})
        supported = all(all(periods[p][field] >= minimum for field, minimum in limits.items())
            for p, limits in config["入口支持"].items())
        goal = supported and all(periods[p]["確認率"] is not None and periods[p]["確認率"] >= config["目標確認率"]
            and periods[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
            and periods[p]["30分間引き_確認率"] is not None
            and periods[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        audit.check(sid+":支持", source["入口支持"], supported)
        audit.check(sid+":70目標", source["70目標"], goal)
        supports[sid] = supported, goal
    audit.check("C1純subset", old_keys["3分_C1"] <= old_keys["3分_C0"], True)
    audit.check("C2純subset", old_keys["3分_C2"] <= old_keys["3分_C1"], True)
    audit.check("入口達成数", result["入口70目標達成数"], sum(g for s, g in supports.values()))
    return {"新case数": len(cases), "入口期間群": summaries, "支持": supports,
        "直接先着検算": "状態独立確認の新case全行/全正常BBO直接走査証明へSHA接続"}


def role_summary(cases: list[dict], result: dict, config: dict, audit: Any) -> None:
    """三切替入口の六実役割別指標と支持を保存caseから別集計する。

    引数: cases(list[dict])は新case、result/config(dict)は正本/条件、audit(Any)は照合先。
    返り値: None。後続2場へ両期支持を代用しない。
    """
    expected_keys = {("3分_"+policy, role) for policy in ("C0", "C1", "C2") for role in ("順行", "反転")}
    saved = {(r["入口ID"], r["役割"]): r for r in result["役割別入口評価"]}
    audit.check("役割別入口集合", set(saved), expected_keys)
    for key, row in saved.items():
        metrics = {}
        for period in PERIODS:
            own = [r for r in cases if (r["入口ID"], r["役割"]) == key and r["期間"] == period]
            metrics[period] = H.entry_metrics(own, period)
            audit.check(str(key)+period+":役割入口", row[period], metrics[period])
        support = all(all(metrics[p][k] >= n for k, n in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(metrics[p]["確認率"] is not None and metrics[p]["確認率"] >= config["目標確認率"]
            and metrics[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
            and metrics[p]["30分間引き_確認率"] is not None and metrics[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        audit.check(str(key)+":役割支持", row["入口支持"], support)
        audit.check(str(key)+":役割70", row["70目標"], goal)


def viewer(rows: list[dict], api: str, audit: Any) -> dict:
    """三運用の表示代表と全198資源をAPIで検査する。

    引数: rows(list[dict])は独立場会計、api(str)は接続先、audit(Any)は照合先。
    返り値: dictは表示確認。代表選択は売買採否へ使わない。
    """
    helper = load(ROOT/"scripts/複合検証/Viewer照合.py", "スイング突破のViewer確認")
    path = STUDY/"一覧.resources.json"
    resources = {(r["method_id"], r["session"]): r for r in H.read(path)["resources"]}
    body, _ = helper.fetch(api+"/api/resources?"+helper.urlencode({"catalog_path": path.relative_to(ROOT).as_posix()}))
    audit.check("Viewer全資源", {r["id"] for r in json.loads(body)["resources"]}, {r["id"] for r in resources.values()})
    checked = []
    for cid in IDS:
        row = sorted([r for r in rows if r["候補ID"] == cid], key=lambda r: (-abs(r["観測現金増減円"]), r["場"]))[0]
        adapted = {"銘柄": "NK225", "場": row["場"], "手法": cid,
            "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
        item = helper.check_one(api, STUDY, adapted, resources[cid, row["場"]], "事前三運用の代表", False)
        item.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
        checked.append(item)
    with urlopen(api+"/api/info", timeout=10) as stream:
        info = json.load(stream)
    return {"確認日時": datetime.now(U.HELPER.JST).isoformat(), "接続先": api, "API情報": info,
        "照合": checked, "追加PNG数": 0, "代表規則": "各事前運用の最大絶対観測現金増減場。売買採否へ不使用",
        "Viewer実行コピーSHA256": U.sha(ROOT/"work/viewer/session-trade-viewer.exe"),
        "指定配布版SHA256": U.sha(ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe")}


def run(api: str | None) -> dict:
    """即時新規の最初BBOと全会計を検算し、独立状態/追尾へ接続する。

    引数: api(str|None)はViewer接続先。
    返り値: dictは合否・出典・範囲。主モデルや正式結果を変更しない。
    """
    audit = U.Audit()
    audit.check("固定34即時受付版", U.sha(N_PATH), "5ee9dd46eb7ecc3bbc21391049e0e3492fc031ddc1185837b30d59ba189e5793")
    config, result, fixed = (H.read(STUDY/n) for n in ("条件.json", "結果.json", "固定.json"))
    for name, expected in fixed["ファイルSHA256"].items():
        audit.check("固定:"+name, U.sha(ROOT/name), expected)
    pointer = H.read(STUDY/"入力台帳.json")
    manifest_path = (STUDY/pointer["参照"]).resolve()
    audit.check("解決台帳", U.sha(manifest_path), pointer["SHA256"])
    manifest = H.read(manifest_path)
    entries = {r["session"]: r for r in manifest["entries"]}
    audit.check("入力66行", len(manifest["entries"]), 66)
    audit.check("入力66場一意", len(entries), 66)
    prepared = H.read(WORK/"準備点検.json")
    current_codes = code_pins()
    for field, expected in (("コードSHA256", current_codes), ("条件SHA256", U.sha(STUDY/"条件.json")),
            ("入力台帳SHA256", U.sha(STUDY/"入力台帳.json")), ("参照台帳SHA256", U.sha(manifest_path)),
            ("指標参照SHA256", U.sha(STUDY/"指標参照.json")), ("ラベル計算", False), ("損益計算", False)):
        audit.check("主準備現在版:"+field, prepared.get(field), expected)
    audit.check("固定主準備版", fixed["主準備SHA256"], U.sha(WORK/"準備点検.json"))
    dmi_definition = definition_binding(prepared, fixed, audit)
    runtime_paths = [Path(__file__), *[ROOT/name for name in current_codes],
        *[STUDY/name for name in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "指標参照.json")],
        WORK/"準備点検.json", ROOT/dmi_definition["パス"]]
    runtime_initial = {p.relative_to(ROOT).as_posix(): U.sha(p) for p in runtime_paths}
    for filename in ("指標参照.json",):
        ref = H.read(STUDY/filename)
        for name, item in ref["文書と証明"].items():
            audit.check(filename+name, U.sha(ROOT/item["パス"]), item["SHA256"])
        for item in ref["共有明細"]:
            audit.check(filename+item["パス"], U.sha(ROOT/item["パス"]), item["圧縮SHA256参考"])
    stats = {}
    artifacts = H.read(STUDY/"作業成果物.json")
    audit.check("共有参照は指標一つ", artifacts["共有参照"], ["指標参照.json"])
    audit.check("正式六系列", {Path(r["パス"]).name for r in artifacts["ファイル"]}, set(FILES))
    for item in artifacts["ファイル"]:
        path = ROOT/item["パス"]
        digest, count = F.content_stats(path)
        audit.check(path.name+":展開SHA", digest, item["展開内容SHA256"])
        stats[path.name] = digest, count
    cases, case_sha = H.rows(WORK/"入口事例.jsonl.gz")
    entrance = entry_summary(cases, result, config, audit)
    role_summary(cases, result, config, audit)
    details, detail_sha = H.rows(WORK/"全運用詳細.jsonl.gz")
    logs, log_sha = H.rows(WORK/"追尾.jsonl.gz")
    grouped = {}
    for row in logs:
        grouped.setdefault((row["候補ID"], row["場"]), []).append(row)
    detail_map, quotes, rows = {}, {}, []
    for detail in details:
        cid, session = detail["候補ID"], detail["場"]
        key = cid, session
        audit.check(str(key)+":一意", key not in detail_map, True)
        detail_map[key] = detail
        sid = cid.rsplit("_", 1)[0]
        own_cases = [r for r in cases if r["入口ID"] == sid and r["場"] == session]
        event_map = {r["イベントID"]: r for r in own_cases}
        if session not in quotes:
            quotes[session] = U.quotes(entries[session], True)
        q = quotes[session]
        N.acceptance(detail, own_cases, q, audit)
        row = U.audit_session(detail, q, audit)
        row.update(A.drawdown(detail, q, audit), 通常線更新回数=0,
            追尾線更新回数=sum(r["動作"] == "追尾線更新" for r in grouped.get(key, [])))
        G.trade_path(detail, q, config["運用"], audit)
        for field in ("終了建玉", "終了返済待機", "追尾線更新回数"):
            audit.check(str(key)+field, row[field], detail["品質"][field])
        if row["終了建玉"] or row["終了返済待機"]:
            audit.check(str(key)+":未解消注意", row["観測経路注意"], True)
            audit.check(str(key)+":未解消確定不能", row["確定対象純損益円"], None)
        for trade in detail["取引"]:
            audit.check(cid+trade["建玉ID"]+":登録ATR", trade["入口ATR"], event_map[trade["入口イベントID"]]["atr"])
            audit.check(cid+trade["建玉ID"]+":役割", trade["入口役割"], event_map[trade["入口イベントID"]]["役割"])
        row.update(期間=detail["品質"]["期間"], 場時間分=detail["品質"]["場時間分"])
        rows.append(row)
    audit.check("全3x66", set(detail_map), {(cid, s) for cid in IDS for s in entries})
    audit.check("固定表示順", result["表示固定ID"], IDS)
    audit.check("三結果順", [r["候補ID"] for r in result["結果"]], IDS)
    table_rows = U.table(STUDY/"全候補_場別.csv")
    table = {(r["手法"], r["場"]): r for r in table_rows}
    audit.check("場CSV一意", len(table), len(table_rows))
    audit.check("場CSV全群", set(table), set(detail_map))
    for key, detail in detail_map.items():
        for field, value in detail["品質"].items():
            audit.check(str(key)+":場CSV:"+field, table[key][field], value)
    qualified, current_qualified, adopted, aggregates = 0, 0, 0, []
    for candidate in result["結果"]:
        cid, sid = candidate["候補ID"], candidate["入口"]["入口ID"]
        support, goal = entrance["支持"][sid]
        for field, expected in (("入口支持", support), ("70目標", goal), ("現方針候補", cid.endswith("_XF"))):
            audit.check(cid+field, candidate[field], expected)
        periods = {}
        for period in PERIODS:
            values = G.B.metrics([r for r in rows if r["候補ID"] == cid and r["期間"] == period])
            for field, value in values.items():
                audit.check(cid+period+field, candidate[period]["運用"][field], value)
            own = next(r for r in result["入口評価"] if r["入口ID"] == sid)
            audit.check(cid+period+":入口コピー", candidate[period]["入口"], own[period])
            periods[period] = values
            aggregates.append({"候補ID": cid, "期間": period, **values})
        okay = all(all(periods[p][field] >= minimum for field, minimum in limits.items()) and periods[p]["品質注意場数"] == 0
            and periods[p]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        audit.check(cid+":費用資格", candidate["費用資格"], okay)
        audit.check(cid+":採用資格", candidate["採用資格"], okay and goal and cid.endswith("_XF"))
        qualified += okay
        current_qualified += okay and cid.endswith("_XF")
        adopted += okay and goal and cid.endswith("_XF")
    for field, expected in (("費用資格数", qualified), ("現方針費用資格数", current_qualified), ("採用資格数", adopted)):
        audit.check(field, result[field], expected)
    adapter = CSV構造照合(audit)
    files = U.artifacts(STUDY, detail_map, IDS, entries, adapter)
    files.update(CSV構造辞書欄数=adapter.count, CSV構造規約="取引の起動判定出典dictだけwriterの全strと比較。他値/金額/JSONLは型比較を維持")
    if api:
        H.write(STUDY/"Viewer照合.json", viewer(rows, api, audit))
    proofs = {}
    for name in ("状態独立確認", "追尾独立確認"):
        path = WORK/(name+".json")
        if not path.exists():
            continue
        proof = H.read(path)
        for field, expected in (("全件一致", True), ("不一致数", 0), ("不一致", []),
            ("コードSHA256", U.sha(Path(__file__).with_name(name+".py"))), ("入力台帳SHA256", U.sha(STUDY/"入力台帳.json")),
            ("参照入力台帳SHA256", U.sha(manifest_path)), ("指標参照SHA256", U.sha(STUDY/"指標参照.json")), ("入口事例展開SHA256", case_sha),
            ("主コードSHA256", current_codes), ("条件SHA256", U.sha(STUDY/"条件.json")),
            ("主準備SHA256", U.sha(WORK/"準備点検.json")), ("結果SHA256", U.sha(STUDY/"結果.json")),
            ("DMI数値定義", dmi_definition)):
            audit.check(name+field, proof[field], expected)
        if name == "状態独立確認":
            audit.check(name+":条件版", proof["条件SHA256"], U.sha(STUDY/"条件.json"))
            audit.check(name+":全明細", set(proof["成果物照合"]), set(stats))
            for filename, values in proof["成果物照合"].items():
                audit.check(filename+":展開SHA", values["展開内容SHA256"], stats[filename][0])
                audit.check(filename+":全行", values["行数"], stats[filename][1])
        else:
            for field, expected in (("全運用詳細展開SHA256", detail_sha), ("追尾展開SHA256", log_sha), ("保存追尾行数", len(logs)),
                ("対象完結取引数", sum(len(d["取引"]) for d in details)), ("状態独立確認SHA256", U.sha(WORK/"状態独立確認.json"))):
                audit.check(name+field, proof[field], expected)
        destination = STUDY/(name+".json")
        H.write(destination, proof)
        proofs[name] = {"ファイル": destination.name, "SHA256": U.sha(destination),
            "全件一致": proof["全件一致"], "照合項目数": proof["照合項目数"]}
    complete = len(proofs) == 2
    runtime_current = {name: U.sha(ROOT/name) for name in runtime_initial}
    audit.check("会計実行中出典不変", runtime_current, runtime_initial)
    output = {"全件一致": not audit.errors, "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
        "確認日時": datetime.now(U.HELPER.JST).isoformat(), "コードSHA256": U.sha(Path(__file__)),
        "固定新規受付SHA256": U.sha(N_PATH), "固定元会計SHA256": U.sha(ROOT/"scripts/外部探索/運用独立監査.py"),
        "結果SHA256": U.sha(STUDY/"結果.json"), "全66場既使用": True,
        "条件SHA256": U.sha(STUDY/"条件.json"), "入力台帳SHA256": U.sha(STUDY/"入力台帳.json"),
        "参照入力台帳SHA256": U.sha(manifest_path), "主準備SHA256": U.sha(WORK/"準備点検.json"),
        "主コードSHA256": current_codes, "DMI数値定義": dmi_definition,
        "実行中code不変": runtime_initial == runtime_current,
        "指標参照SHA256": U.sha(STUDY/"指標参照.json"),
        "状態確認未完": "状態独立確認" not in proofs, "追尾確認未完": "追尾独立確認" not in proofs,
        "入口": entrance, "運用期間別": aggregates, "正式資源": files, "別計算証明": proofs,
        "Viewer記録": "Viewer照合.json" if api else None,
        "一致の範囲": "新3分の確定スイング/当j判断後pivot更新/初cross消費/DI方向/Fast精密差/全三採否と、新case全実方向BBO直接先着は45状態へSHA接続。旧29は原3分数値材料の共有参照だけで、旧245/旧11label/旧運用完全対照を要求しない。DMI4列正本定義hashと独立生float検算/準備符号採否strictは状態の別経路へ接続。固定34最初+1秒正常BBO、固定Decimal全会計/注文/帰属/品質/MFE/MAE/DD/XF起動/現ATR固定D/名目床/CSV/Viewerを照合。最初返済要求/全線は独立追尾へ接続。旧登録/旧先着/旧全運用との同値は要求しない。",
        "限界": "全66場既使用。ラージBBOでの最初気配だけで数量/キュー/実micro成立を証明しない。0/5/10は同約定費用負荷。価格時計は受信時計でない。取消理由の文字列は注文と入口取扱の整合検査で、独立した可否は最初適格BBO/TTL/停止を検算。注意期の全体確定額はnull。"}
    H.write(STUDY/"独立監査.json" if complete else WORK/"会計監査_途中.json", output)
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "状態確認未完", "追尾確認未完")}, ensure_ascii=False))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00045確定スイング突破/DI方向/Fastの三XF運用の独立会計")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    if not run(args.api_base.rstrip("/") if args.api_base else None)["全件一致"]:
        raise SystemExit(1)
