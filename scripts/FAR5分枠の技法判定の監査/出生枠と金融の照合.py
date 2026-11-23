"""固定95/94の全原行金融規範を再用し、96の技法採否だけを出生一枠へ結合する。"""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/FAR5分判断と出生一回の監査/出生と5分境界の照合.py"
OLD_SHA = "329fb9958f708bbf34fd939978f358e35333ad80053e4b5ce78521d95afca693"
TECH_PATH = ROOT / "scripts/FAR5分枠の技法判定の監査/技法の保存照合.py"
if not TECH_PATH.is_file():
    TECH_PATH = ROOT / "work/96保存監査案/技法の保存照合.py"
TECH_SHA = "b5d1af7fb85d4446a47573a4389abfa433177189cb01d901bdd53a8a38b8d5e6"
PROOF95 = ROOT / "study/00095_5分判断と開始30分見送り/完了記録.json"
PROOF95_SHA = "b7df0d9f793fca1ee9fbb489e045b927f8cf4b46e0e81a6c199920f128e4d943"
BASELINE95 = PROOF95.parent / "成果物"
KEYS = tuple(("" if p == "G0" else p + "_") + f"B5Q_P0_C{c}_D{d}"
             for p in ("G0", "A", "B", "AB") for c in (0, 5) for d in (0, 1))


def digest(path: Path) -> str:
    """
    機能: 明示保存ファイルの内容指紋を計算する。
    引数: path(Path)は許可済み入力。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fixed_module(name: str, path: Path, expected: str):
    """
    機能: 停止済み金融/技法の独立Pythonを指紋確認して直接再用する。
    引数: name(str)、path(Path)、expected(str)はmodule名・コード・固定SHA。
    返り値: moduleは読取専用の固定部品。Go/金融/市場は実行しない。
    """
    if digest(path) != expected:
        raise ValueError("固定部品SHA差:" + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OLD = fixed_module("固定95の出生原板監査96", OLD_PATH, OLD_SHA)
TECH = fixed_module("固定96の純技法照合Raw", TECH_PATH, TECH_SHA)
BASE, Audit = OLD.BASE, OLD.Audit


class GatePath(OLD.GridPath):
    """旧95のSource/約定/全MTMを継承し、旧min後の技法採否だけを独立に追加する。"""

    def __init__(self, actual: dict, audit: Audit, gates):
        """
        機能: ラベルと任意gate metadataだけを初期化の旧型へ投影し、全金融出典は保持する。
        引数: actual(dict)、audit(Audit)、gates(GateIndex)は保存口座/比較器/共有技法索引。
        返り値: None。注文・受理・時計・Signalの内容を改変しない。
        """
        audit.need(actual["key"] in KEYS, "96の16key")
        policy = actual["config"].get("gate_policy", "")
        audit.need(policy in ("", "A", "B", "AB") and actual["config"]["entry_timing"] == "B5Q"
                   and actual["config"]["policy"] == "P0", "96固定B5Q/P0/gate")
        projection = copy.deepcopy(actual)
        projection["config"].pop("gate_policy", None)
        expected = f"B5Q_P0_C{actual['config']['slip_pts']:g}_D{actual['config']['delay_seconds']}"
        audit.equal(actual["key"], (policy + "_" if policy else "") + expected, "96外keyとpolicy")
        projection["key"] = expected
        for p in projection["entry_opportunities"]:
            p.pop("gate", None)
        super().__init__(projection, audit)
        # ID採番は元の96keyを使う。旧部品へのラベル射影を受理偽装へ用いない。
        self.key = actual["key"]
        self.extra_actual = actual
        self.policy, self.gates = policy, gates

    def evaluate(self, p: dict, at: float, quiet: bool, trace: dict) -> None:
        """
        機能: 旧95の前資格と旧min量をRaw状態から確定後、純技法へ一度だけ結ぶ。
        引数: p/trace(dict)、at(float)、quiet(bool)は独立機会・枠・既存quiet。
        返り値: None。許可だけ旧requestへ進み、未知/拒否は当枠消費する。
        """
        key = p["source"]["method"], p["source"]["signal_id"]
        source = self.sources[key]
        p.update(consumed=True, evaluated_at=at, status="expired", source_state=source["state"], available=self.capacity(p["side"]))
        if self.last is not None:
            p.update(quote=copy.deepcopy(self.last), quote_age_seconds=at-self.last["time"])
        hold = self.holds.get((key[0], source["hold"])) if source["hold"] else None
        if hold is not None:
            p.update(source_hold_id=source["hold"], source_quantity=hold["quantity"], source_reserved=hold["reserved"])
        deadline = min(self.session["force_close"], self.us-900) if key[0] == "NK225_P164_06" else self.session["force_close"]
        reason = ""
        if p["assigned_at"] != at:
            reason = "割当枠を通過・後の枠へ復活しない"
        elif at >= deadline:
            reason = "元手法Force境界以降"
        elif quiet and self.timing == "B5Q":
            reason = "割当枠が開始30分見送り"
        elif source["state"] == "cancelled":
            reason = "Native取消済みの出生"
        elif source["state"] == "pending":
            reason = "割当枠でSource未取得"
        elif source["state"] != "filled" or hold is None:
            raise ValueError("取得済みSource Hold出典なし")
        elif hold["quantity"] == 0:
            reason = "割当枠でSource完結済み"
        elif hold["reserved"] > 0:
            reason = "割当枠でSource返済予約あり"
        elif not trace["quote_known"]:
            reason = "割当枠の最新原行の正常気配が必要未知"
            p["required_unknown"] = True
        elif p["available"] == 0:
            reason = "片側上限に空きなし"
            self.count("cap_rejected_entries")
        else:
            quantity = min(source["signal"]["quantity"], hold["quantity"], p["available"])
            self.audit.need(quantity > 0, "slot正の要求量")
            decision = self.gates.claim(self.key, p) if self.policy else None
            if decision is not None:
                self.audit.equal(decision["policy"], self.policy, "金融と技法の政策")
                p["gate"] = copy.deepcopy(decision)
            if decision is not None and (not decision["known"] or not decision["allowed"]):
                p["required_unknown"], reason = not decision["known"], decision["reason"]
            else:
                if p["available"] < min(source["signal"]["quantity"], hold["quantity"]):
                    self.count("cap_clipped_entries")
                order = self.request("entry", p["side"], quantity, source["identity"], at, self.last, source["signal"]["reason"])
                order["source_hold_id"] = source["hold"]
                self.entry_sources[key] = len(self.orders)-1
                p.update(requested=quantity, entry_order_id=order["id"], status="accepted")
                reason = "出生量・Source現在残量・片側余力のminを一度受理"
                trace["accepted_count"] += 1
                trace["accepted_quantity"] += quantity
                self.gm["accepted"] += 1
        p["reason"] = reason
        if p["status"] != "accepted":
            self.entry_sources[key] = None
            trace["expired_count"] += 1
            self.gm["expired"] += 1
        if p["required_unknown"]:
            trace["unknown_count"] += 1
            self.gm["required_unknown"] += 1


def bind_grid_current(gates, at: float, q: dict | None, audit: Audit) -> None:
    """
    機能: 候補なしを含む全gridのCurrentを、直前Native NK原行へ結ぶ。
    引数: gates(GateIndex)、at(float)、q(dict|None)、audit(Audit)は共有入力と独立最新原行。
    返り値: None。OFI/技法の数値自体を原板から再生成したとは扱わない。
    """
    matches = [v for v in gates.grids.values() if v["at"] == at]
    audit.need(len(matches) == 1, "全grid共有Current一意")
    c = matches[0]["current"]
    expected = {"reference": "", "time": 0, "received": 0, "source_index": 0, "source_line": 0, "last": 0, "bid": 0, "ask": 0}
    if q is not None:
        expected = {"reference": "NK225", "time": q["time"], "received": q["time"], "source_index": q["index"],
                    "source_line": q["source_line"], "last": q["last"], "bid": q["bid"], "ask": q["ask"]}
    for field, value in expected.items():
        audit.equal(c[field], value, "grid Currentと直前Native NK:" + field)


def inspect_fixture(value: dict) -> dict:
    """
    機能: Go型手製API人工を旧金融全経路と独立技法全checkへ同時に結ぶ。
    引数: value(dict)は16actors/共有技法/明示eventsを含むGo Marshal。
    返り値: dictは非0を含む保存・金融・純判定の照合件数。原板自然生成は範囲外。
    """
    audit, gates = Audit(), TECH.GateIndex(value)
    books = value.get("actors", value.get("books"))
    audit.equal(set(books), set(KEYS), "人工16口座")
    models = [GatePath(books[k], audit, gates) for k in KEYS]
    clocks = []
    for call in OLD.fixture_calls(value):
        if call["kind"] == "quote":
            q, atr = BASE.observation_quote(call["observation"], call["source_line"])
            for model in models:
                model.step(q, call["batches"], atr)
        elif call["kind"] == "timer":
            for model in models:
                model.timer(call["at"], call["batches"])
        else:
            bind_grid_current(gates, call["at"], models[0].last, audit)
            for model in models:
                model.grid(call["at"])
            clocks.append(call["at"])
    details = [m.finish() for m in models]
    gate_counts = gates.finish(clocks)
    return {"成功": True, "scope": "Go型API人工の全旧金融/出生一枠/純技法結合。Source/Chart/ATRの原板自然生成未計測",
            "会計数": 16, "非0会計数": sum(d["positions"] > 0 for d in details), "照合項目数": audit.checks,
            "不一致数": 0, "技法": gate_counts, "details": details}


def inspect_one(task: tuple) -> dict:
    """
    機能: 既使用の明示一場を両市場EOF・全旧金融・Source・gateへ独立結合する。
    引数: task(tuple)は96保存Path/台帳場/source_root/固定95保存先。
    返り値: dictは16会計とG0四全文、全原行損益/入口時計の照合。
    """
    result_path, entry, source_root, baseline_folder = task
    result_path, source_root, baseline_folder = Path(result_path), Path(source_root), Path(baseline_folder)
    session = entry["id"]
    if not "2026-09-21" <= session[:10] <= "2026-10-27":
        raise ValueError("既使用54場の期間外は読まない")
    inputs = {k: source_root/entry["files"][k]["path"] for k in ("NK225_book", "TOPIX_book", "NK225_candle_300")}
    old_path = baseline_folder/(session+".json.gz")
    paths = [result_path, old_path, PROOF95, Path(__file__), OLD_PATH, OLD.BASE_PATH, BASE.BASE_PATH, TECH_PATH] + list(inputs.values())
    before = {str(p.resolve()): digest(p) for p in paths}
    audit = Audit()
    audit.equal(before[str(PROOF95.resolve())], PROOF95_SHA, "固定95完了指紋")
    fixed = BASE.load(PROOF95)["自己を除く正式指紋"]
    audit.equal(before[str(old_path.resolve())], fixed["成果物/"+old_path.name], "固定95保存指紋")
    for key, p in inputs.items():
        audit.need(before[str(p.resolve())] == entry["files"][key]["sha256"] and p.stat().st_size == entry["files"][key]["size"], "固定原入力:"+key)
    value, previous = BASE.load(result_path), BASE.load(old_path)
    audit.equal((value["session"], previous["session"]), (session, session), "新旧場")
    audit.need(value["shadow_match"]["all"] is True and value["baseline95_match"]["all"] is True, "旧比較保存証拠")
    audit.equal(value["baseline95_match"]["sha256"], before[str(old_path.resolve())], "G0保存基準")
    audit.equal(value["baseline95_match"]["proof_sha256"], PROOF95_SHA, "G0保存完了証拠")
    audit.equal(set(value["books"]), set(KEYS), "96全16Actor")
    clock = BASE.BASE.session_clock(session)
    expected_session = dict(id=session, kind=session.split("_")[1], start=clock["start"], end=clock["end"], force_close=clock["force"],
                            us_open=clock["us"], extra_at=clock["us"]+1800 if clock["us"] else clock["start"]+225*60)
    endpoints = []
    for ref in ("NK225", "TOPIX"):
        end, quality = OLD.scan_board_clock(inputs[ref+"_book"], session)
        if end is not None:
            endpoints.append(end)
        for field, expected in quality.items():
            BASE.compare_tree(value["quality"][ref][field], expected, audit, ref+":時計品質/"+field)
    end = max(endpoints) if endpoints else None
    clocks = OLD.grid_schedule(session, end)
    gates = TECH.GateIndex(value)
    models = []
    for key in KEYS:
        actual = value["books"][key]
        audit.need(actual["finished"] is True and actual["complete"] is True and actual["failure"] == "", "96金融完了")
        BASE.compare_tree(actual["session"], expected_session, audit, key+":場時計")
        audit.equal(actual["config"]["us_open"], clock["us"], key+":正式NY時計")
        audit.equal([g["at"] for g in actual["grid_traces"]], clocks, key+":両市場EOFまでの全grid")
        if key.startswith("B5Q_"):
            BASE.compare_tree(actual, previous["books"][key], audit, key+":G0対95除外0全文")
        models.append(GatePath(actual, audit, gates))
    cfg = value["feature_config"]
    audit.need(cfg["atr_period"] == 12 and cfg["atr_min_bars"] == 3 and cfg["candle_delay_seconds"] == 60, "固定ATR条件")
    native = BASE.NativeTape(value["shadows"], session, audit)
    atr = BASE.ATRSeries(BASE.candles_from_csv(inputs["NK225_candle_300"], session), clock["start"])
    force = [clock["force"]] + ([clock["us"]-900] if clock["us"] else [])
    events = sorted([(at, 0) for at in force]+[(at, 1) for at in clocks])
    ei = 0

    def clock_event(at: float, kind: int) -> None:
        """
        機能: 元Force→gridを原行より先に配送し、価格/受理を前倒ししない。
        引数: at(float)、kind(int)は元時計とForce0/grid1。
        返り値: None。
        """
        if kind == 0:
            batches = native.take(at)
            for model in models:
                model.timer(at, batches)
        else:
            bind_grid_current(gates, at, models[0].last, audit)
            for model in models:
                model.grid(at)

    quality = {}
    for q in BASE.walk_raw(inputs["NK225_book"], session, quality):
        while ei < len(events) and events[ei][0] <= q["time"]:
            clock_event(*events[ei])
            ei += 1
        batches, width = native.take(q["time"], q["source_line"]), atr.asof(q["time"])
        for model in models:
            model.step(q, batches, width)
    for event in events[ei:]:
        clock_event(*event)
    native.finish()
    BASE.compare_tree(value["source_rows"], native.source_rows, audit, "全Source行数")
    BASE.compare_tree(value["quality"]["NK225"], quality, audit, "全NK品質")
    audit.equal(value["contract"], entry["contract"], "限月")
    details = [model.finish() for model in models]
    gate_counts = gates.finish(clocks)
    audit.need(all(digest(Path(p)) == expected for p, expected in before.items()), "入力/code前後不変")
    return {"session": session, "成功": True, "会計数": 16, "G0基準会計数": 4, "全grid数": len(clocks),
            "EOF受理時計上限": end, "照合項目数": audit.checks, "不一致数": 0, "入力前後不変": True,
            "入力SHA256": before, "技法": gate_counts, "details": details,
            "scope": "両市場EOF/旧金融全NK原行/Source/出生一枠/純技法保存結合。新チャートnumericの原板再生成は別監査。"}


def main() -> int:
    """
    機能: 明示Go人工又は許可済み保存場だけを独立読取し、新規証拠を保存する。
    引数: --fixture(Path)又は--input/--manifest/--baseline95(Path)、--limit(int、既定2)、--out(Path)。
    返り値: intは成功0/不一致1。全54は別の完了通知後にだけ実行する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--baseline95", type=Path, default=BASELINE95)
    parser.add_argument("--limit", type=int, choices=(2, 54), default=2)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("新規証拠先だけ")
    before = {str(p.resolve()): digest(p) for p in (Path(__file__), OLD_PATH, OLD.BASE_PATH, BASE.BASE_PATH, TECH_PATH)}
    try:
        if args.fixture:
            before[str(args.fixture.resolve())] = digest(args.fixture)
            result = inspect_fixture(BASE.load(args.fixture))
        else:
            if args.input is None or args.manifest is None:
                raise ValueError("保存dir/固定manifestを明示")
            before[str(args.manifest.resolve())] = digest(args.manifest)
            if before[str(args.manifest.resolve())] != BASE.BASE.MANIFEST_SHA:
                raise ValueError("固定80台帳SHA差")
            manifest = BASE.load(args.manifest)
            selected = [s for s in manifest["sessions"] if "2026-09-21" <= s["id"][:10] <= "2026-10-27"]
            if len(selected) != 54 or len({s["id"] for s in selected}) != 54:
                raise ValueError("既使用54場集合差")
            details = [inspect_one((args.input/(s["id"]+".json"), s, manifest["source_root"], args.baseline95)) for s in selected[:args.limit]]
            result = {"成功": all(d["成功"] for d in details), "scope": "接続2場" if args.limit == 2 else "正式既使用54場",
                      "セッション数": len(details), "会計数": sum(d["会計数"] for d in details), "G0基準会計数": 4*len(details),
                      "照合項目数": sum(d["照合項目数"] for d in details), "不一致数": 0, "details": details}
        result["入力前後不変"] = all(digest(Path(p)) == expected for p, expected in before.items())
        result["コード入力SHA256"] = before
        result["成功"] = result["成功"] and result["入力前後不変"]
    except Exception as error:
        result = {"成功": False, "不整合": str(error), "コード入力SHA256": before}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("成功", "不整合", "会計数", "照合項目数") if k in result}, ensure_ascii=False))
    return 0 if result["成功"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
