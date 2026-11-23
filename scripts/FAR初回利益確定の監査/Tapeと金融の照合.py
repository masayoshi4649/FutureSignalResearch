"""完成Tapeを全金融へ独立配送し、各現在候補の固定96純判定を再計算する。"""

import argparse
from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
FIN_PATH = ROOT/"scripts/FAR初回利益確定の監査/初回利益確定の金融照合.py"
FIN_SHA = "ab7e95e35514ae0aadf4a833f89a1422eaa53c82339d003bba13b9df4eaec5b0"
CAPABILITIES = ["source93.public_notifications.v1", "actual96.P0.scalar11.v1", "entry96.AB.gate3ba3c2c8.v1"]
SCALAR_FIELDS = {"time", "received", "index", "source_line", "last", "bid", "ask", "quote_ok", "atr", "atr_available", "atr_nominal"}


def digest(path: Path) -> str:
    """
    機能: 明示されたコード又は人工を指紋化する。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_module(name: str, path: Path, expected: str):
    """
    機能: 停止金融監査だけを固定SHAで読み込む。
    引数: name/expected(str)、path(Path)はmodule名・指紋・コード先。
    返り値: moduleは固定部品。Go/市場/原板を実行しない。
    """
    if digest(path) != expected:
        raise ValueError("固定金融監査SHA差")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FIN = fixed_module("固定H0金融97Tape", FIN_PATH, FIN_SHA)
BASE, TECH, Audit = FIN.BASE, FIN.TECH, FIN.Audit


def canonical(value) -> str:
    """
    機能: JSON値の前後不変を比較する正規表現を作る。
    引数: value(any)はTape又は新金融保存値。
    返り値: strは非有限を許さない正規JSON。
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def scalar_quote(value: dict, audit: Audit) -> tuple:
    """
    機能: Scalar11を同じ原行気配と公開ATRへ無補完で射影する。
    引数: value(dict)、audit(Audit)はScalarと比較器。
    返り値: tuple[dict,dict]は金融気配と幅。原板からのATR生成ではない。
    """
    audit.equal(set(value), SCALAR_FIELDS, "Scalar11字段")
    audit.need(all(BASE.finite(value[n]) for n in SCALAR_FIELDS-{"quote_ok"}), "Scalar数値有限")
    audit.need(type(value["quote_ok"]) is bool, "Scalar正常気配flag型")
    q = {n:value[n] for n in ("time", "index", "source_line", "last", "bid", "ask", "quote_ok")}
    BASE.validate_quote(q, audit, "Tape Scalar")
    audit.need(q["last"] > 0, "ScalarはNative Last正の全行")
    atr = {"value":value["atr"], "available":value["atr_available"], "nominal":value["atr_nominal"]}
    audit.need(all(BASE.finite(x) and x >= 0 for x in atr.values()), "Scalar ATR有限/非負")
    audit.need(atr["value"] == 0 or 0 < atr["nominal"] <= atr["available"] <= q["time"], "Scalar公開ATRの因果時計")
    return q, atr


def restore_batches(event: dict, last: dict, audit: Audit) -> list:
    """
    機能: active methodsの元順へ空通知を戻し、Source時刻/位相/物理行を結ぶ。
    引数: event/last(dict)、audit(Audit)はTapeイベント・手法別直前物理行・比較器。
    返り値: list[dict]は全batch。金融へSource判断やBeforeを新たに作らない。
    """
    origin = "quote" if event["kind"] == "quote" else "timer"
    methods, non_empty = event.get("methods", []), event.get("non_empty", [])
    audit.need(type(methods) is list and type(non_empty) is list, "Tape methods/非空通知の型")
    audit.need(all(type(m) is str and m for m in methods) and len(set(methods)) == len(methods), "Tape手法の一意順")
    stored = {}
    for batch in non_empty:
        audit.equal(set(batch), {"method", "delta"}, "NativeBatch字段")
        method = batch["method"]
        audit.need(method in methods and method not in stored, "非空手法の重複/未結合")
        stored[method] = batch
    out = []
    for method in methods:
        line = last.get(method, 0)
        if event["kind"] == "quote":
            line = event["quote"]["source_line"]
            last[method] = line
        if method in stored:
            batch = copy.deepcopy(stored[method])
        else:
            batch = {"method":method, "delta":{"at":event["at"], "origin":origin, "source_line":line,
                                               "signals":[], "fills":[], "cancellations":[], "closes":[]}}
        delta = batch["delta"]
        audit.equal(set(delta), {"at", "origin", "source_line", "signals", "fills", "cancellations", "closes"}, "StepResult全字段")
        audit.equal((delta["at"], delta["origin"], delta["source_line"]), (event["at"], origin, line), "復元通知の時計/位相/物理行")
        out.append(batch)
    return out


# ----------------------------------------
class RecomputedGates:
    """現在Tape文脈と独立金融候補からABを計算し、保存判断は後で照合する。"""

    def __init__(self, contexts: list, new97: dict, audit: Audit):
        """
        機能: 全共有枠を固定96の型/時刻検査へ通し、新callbackを索引化する。
        引数: contexts(list)、new97(dict)、audit(Audit)は全文脈・新保存・比較器。
        返り値: None。保存SnapshotIDで現在文脈を選ばない。
        """
        self.audit, self.books, self.current = audit, new97["books"], None
        # 固定constructorの全grid検査だけを再用し、旧採否recordは渡さない。
        fixed = TECH.GateIndex({"chart_grids":contexts, "gate_assessments":[]})
        self.grids = fixed.grids
        BASE.compare_tree(new97["chart_grids"], contexts, audit, "Tapeと新保存の共有全grid")
        self.records, self.used, self.claim_order = {}, set(), []
        for record in new97["gate_assessments"]:
            audit.equal(set(record), {"key", "ordinal", "source", "candidate", "assessment"}, "新GateAssessment全字段")
            key, ordinal = record["key"], record["ordinal"]
            audit.need(key in FIN.KEYS and type(ordinal) is int and ordinal > 0, "新判定のKey/ordinal")
            audit.need(self.books[key]["config"].get("gate_policy", "") == "AB", "新判定はAB候補だけ")
            identity = key, ordinal
            audit.need(identity not in self.records, "新callback重複")
            self.records[identity] = record
        self.calls = Counter({key:0 for key in FIN.KEYS})

    def begin_grid(self, context: dict, q: dict | None) -> None:
        """
        機能: 今回イベントの文脈だけを公開し、候補なしのCurrentも直前Scalarへ結ぶ。
        引数: context(dict)、q(dict|None)は当枠文脈と独立最新NK原行。
        返り値: None。
        """
        self.audit.need(context["snapshot_id"] in self.grids, "当gridの共有文脈")
        self.current = context
        FIN.OLD.bind_grid_current(self, context["at"], q, self.audit)

    def claim(self, key: str, p: dict) -> dict:
        """
        機能: 金融前資格後の独立候補を純式へ一度渡し、全判断を事後比較する。
        引数: key(str)、p(dict)は独立金融のKeyと現在候補。
        返り値: dictは再計算Decision。保存Allowedを金融へ入力しない。
        """
        self.audit.need(self.current is not None and self.current["at"] == p["evaluated_at"], "当枠だけのgate文脈")
        candidate = {"ordinal":p["ordinal"], "at":p["evaluated_at"], "side":p["side"], "source":copy.deepcopy(p["source"]),
                     "quote":copy.deepcopy(p["quote"]), "available":p["available"],
                     "quantity":min(p["source"]["birth_quantity"], p["source_quantity"], p["available"])}
        result = TECH.assess(self.current, candidate, "AB")
        identity = key, p["ordinal"]
        self.audit.need(identity in self.records and identity not in self.used, "独立callbackの保存結合/一回")
        saved = self.records[identity]
        BASE.compare_tree(saved["source"], candidate["source"], self.audit, key+"/callback出生")
        BASE.compare_tree(saved["candidate"], candidate, self.audit, key+"/現在候補全field")
        BASE.compare_tree(saved["assessment"], result, self.audit, key+"/純技法全checksとDecision")
        self.used.add(identity)
        self.claim_order.append(identity)
        self.calls[key] += 1
        return result["decision"]

    def finish(self, clocks: list) -> dict:
        """
        機能: callback欠落/余剰/順序と全共有grid列を閉じる。
        引数: clocks(list[number])は実際に配送した全grid時計。
        返り値: dictは全callbackと枠計数。
        """
        self.audit.equal(self.used, set(self.records), "新callback集合の完全一致")
        self.audit.equal(self.claim_order, list(self.records), "新callbackの実適用順")
        self.audit.equal([g["at"] for g in self.grids.values()], clocks, "候補なし含む全grid列")
        expected = {(key,p["ordinal"]) for key, book in self.books.items()
                    for p in book["entry_opportunities"] if p.get("gate") is not None}
        self.audit.equal(self.used, expected, "金融機会とcallback集合")
        return {"共有枠":len(clocks), "新callback":len(self.used), "口座別":dict(self.calls)}


# ----------------------------------------
def inspect_tape(tape: dict, new97: dict) -> dict:
    """
    機能: 全Scalar/Source/Force/Gridから97金融と純採否を独立再構成する。
    引数: tape/new97(dict)は完成Tapeと新金融保存。実行許可は呼出側で別に限定する。
    返り値: dictは16口座の全金融/全grid/全callback照合結果。原板源は再生成しない。
    """
    before = canonical({"tape":tape, "new97":new97})
    audit = Audit()
    audit.equal(tape["version"], 1, "Tape版")
    audit.equal(tape["capabilities"], CAPABILITIES, "Tape対応範囲")
    audit.equal(set(tape)-{"provenance"}, {"version", "scope", "session", "capabilities", "events"}, "Tape全字段")
    audit.equal(set(new97["books"]), set(FIN.KEYS), "新16金融集合")
    audit.equal(new97["session"], tape["session"]["id"], "Tapeと新保存の場")
    for key, book in new97["books"].items():
        audit.equal(book["key"], key, "外Keyと金融Key")
        BASE.compare_tree(book["session"], tape["session"], audit, key+"/共通場時計")
    contexts = [e["context"] for e in tape["events"] if e["kind"] == "grid"]
    gates = RecomputedGates(contexts, new97, audit)
    models = [FIN.HarvestPath(new97["books"][key], audit, gates) for key in FIN.KEYS]
    previous, last_lines, clocks = 0, {}, []
    kinds = Counter()
    for i, event in enumerate(tape["events"], 1):
        audit.need(type(event["ordinal"]) is int and event["ordinal"] == i
                   and BASE.finite(event["at"]) and event["at"] >= previous, "Tape eventの全順序")
        audit.need(set(event) <= {"ordinal", "kind", "at", "quote", "methods", "non_empty", "context"}, "Tape event未定義字段")
        previous = event["at"]
        kind = event["kind"]
        kinds[kind] += 1
        if kind in ("quote", "force"):
            audit.need("context" not in event, "Source/原行にgrid文脈混入なし")
            if kind == "quote":
                audit.need("quote" in event and event["at"] == event["quote"]["time"], "当Scalar時計")
                q, atr = scalar_quote(event["quote"], audit)
            else:
                audit.need("quote" not in event, "Forceは古い気配を更新しない")
            batches = restore_batches(event, last_lines, audit)
            batch_before = canonical(batches)
            for model in models:
                if kind == "quote":
                    model.step(q, batches, atr)
                else:
                    model.timer(event["at"], batches)
                audit.equal(canonical(batches), batch_before, "Source全配送の金融前後不変")
        elif kind == "grid":
            audit.need("quote" not in event and not event.get("methods") and not event.get("non_empty"), "gridの架空原行/Sourceなし")
            audit.need(event.get("context") is not None and event["context"]["at"] == event["at"], "当grid文脈")
            gates.begin_grid(event["context"], models[0].last)
            for model in models:
                model.grid(event["at"])
            clocks.append(event["at"])
        else:
            raise ValueError("Tape未知event")
    details = [m.finish() for m in models]
    gate_counts = gates.finish(clocks)
    audit.equal(canonical({"tape":tape, "new97":new97}), before, "Tapeと保存の前後不変")
    return {"成功":True, "会計数":16, "非0会計数":sum(d["positions"] > 0 for d in details),
            "照合項目数":audit.checks, "不一致数":0, "イベント":dict(kinds), "技法":gate_counts,
            "全Scalar/Source/Force/Grid配送":True, "全経路金融MTM":True, "details":details,
            "限定":"Tape内の公開Scalar/Source/Contextを使う独立金融接続。原板又は自然Source/ATR/チャートの生成は再実行しない。"}


def main() -> int:
    """
    機能: 明示production人工6件だけを新規証拠へ照合する。
    引数: --fixtures/--out(Path)は手製人工根と新規結果。
    返り値: intは全成功0。市場Tapeや原板はこのCLIから読まない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("新規証拠先")
    paths = sorted(args.fixtures.glob("*.json"))
    expected = {f"方向{s}_{role}.json" for s in (-1,1) for role in ("A", "B", "容量取消未知")}
    if {p.name for p in paths} != expected:
        raise ValueError("停止6人工だけ")
    code_paths = [Path(__file__), FIN_PATH, FIN.OLD_PATH, FIN.TECH_PATH, FIN.OLD.OLD_PATH, FIN.OLD.OLD.BASE_PATH, BASE.BASE_PATH]
    before = {str(p.resolve()):digest(p) for p in code_paths+paths}
    rows = []
    for path in paths:
        value = BASE.load(path)
        tape = value["tape"]
        if not tape["scope"].startswith("固定96Go型人工") or tape.get("provenance"):
            raise ValueError("人工専用CLIに市場Tape")
        result = inspect_tape(tape, value["output"])
        if result["技法"]["口座別"] != value["callback_counts"]:
            raise ValueError("Go/Python callback件数差")
        rows.append({"fixture":path.name, **result})
    if any(digest(Path(p)) != h for p,h in before.items()):
        raise ValueError("監査前後の入力/コード差")
    result = {"成功":True, "人工場面":6, "会計数":sum(r["会計数"] for r in rows),
              "非0会計数":sum(r["非0会計数"] for r in rows), "照合項目数":sum(r["照合項目数"] for r in rows),
              "不一致数":0, "新callback":sum(r["技法"]["新callback"] for r in rows), "details":rows,
              "入力コードSHA256前後":before, "前後不変":True, "原板/市場/Go金融再生":0,
              "scope":"Go型production手製人工。純技法は現在候補から独立再計算、自然3/15/Source/ATRの原板形成は未証明。"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:result[k] for k in ("成功", "会計数", "非0会計数", "照合項目数", "新callback")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
