"""78のT資格からADX変化符号だけを外し、同じ執行で比較する。"""

import argparse
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00078_ADXの水準と変化を分ける"
PARENT = ROOT / "work/ADX水準と変化の資格"
WORK = PARENT / "00078"
OLD = ROOT / "study/00077_押戻し再開の確認を早める"
OLDWORK = ROOT / "work/押戻し再開の確認幅/00077"
LEDGER = OLDWORK.parent / "77完了記録.json"
LEDGER_SHA = "d97ea4ed7c35a185e808f0639675ccf2321c95b6d47aedf2b8ce1aec69e58bd2"
POLICIES = ("S0", "S1")
REFERENCES = ("E0", "E1")
ALL_POLICIES = (*REFERENCES, *POLICIES)
PERIODS = ("学習", "条件選択", "後続検査")
PURE = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")
NAME_MAP = {"E0": "L0", "E1": "L1", "S0": "E0", "S1": "E1"}


def sha(path: Path) -> str:
    """ファイル内容の指紋を求める。

    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict:
    """UTF-8の小型JSONを読む。

    引数: path(Path)はJSON。
    返り値: dictは保存値。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def load(path: Path, name: str, digest: str | None = None):
    """市場実行を起動せず固有名で補助を読み込む。

    引数: path(Path)はコード、name(str)は固有名、digest(str|None)は要求指紋。
    返り値: ModuleTypeは補助。既存moduleのglobalsは変更しない。
    """
    if digest is not None and sha(path) != digest:
        raise ValueError("固定補助の変更:" + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if sha(LEDGER) != LEDGER_SHA:
    raise ValueError("77完了台帳の変更")
OLD_MAIN = ROOT / "scripts/押戻し再開の確認幅/検証.py"
P77 = load(OLD_MAIN, "確認幅78の固定77純補助", read(LEDGER)["成果物SHA256"][OLD_MAIN.relative_to(ROOT).as_posix()])
C, O49, P55 = P77.C, P77.O49, P77.P55
rows = P77.rows


def verify_previous() -> dict:
    """77の完了対象133件を検査する。

    引数: なし。
    返り値: dictは完了台帳。旧工程を再生しない。
    """
    if sha(LEDGER) != LEDGER_SHA:
        raise ValueError("77完了台帳の変更")
    value = read(LEDGER)
    if value["試行"] != 77 or len(value["成果物SHA256"]) != 133:
        raise ValueError("77完了対象の差")
    for relative, digest in value["成果物SHA256"].items():
        if sha(ROOT / relative) != digest:
            raise ValueError("77完了物の差:" + relative)
    return value


# ----------------------------------------
def prepare() -> None:
    """新価格観測の前に条件と入力指紋を保存する。

    引数: なし。
    返り値: None。既存条件・台帳を上書きしない。
    """
    verify_previous()
    if (STUDY / "入力台帳.json").exists():
        raise FileExistsError("78の条件・台帳は保存済み")
    old = read(OLD / "条件.json")
    rules = deepcopy(old)
    rules.update(試行=78, 政策={
        "E0": {"保存参考": True, "出典": "77終値反応Tのみ・49即時"},
        "E1": {"保存参考": True, "出典": "77同親T/R・49即時"},
        "S0": {"保存参考": False, "採用": "同じT確認・ADX変化の符号要求なし・Tのみ", "注文": "49即時"},
        "S1": {"保存参考": False, "採用": "S0と同じ全親履歴からT/R", "注文": "49即時"}},
        参考77条件SHA256=sha(OLD / "条件.json"))
    rules["複合"]["T"] = "F01>0 AND F51=F52=1 AND F47>=0.20、順行。F48は観測するが符号を要求しない"
    rules["入力"]["出生ATR"] = "76成功保存参照をSHA固定再用。出生ATRの再計算・複製0"
    rules["複合"]["選択"] = "最新k公開key、同keyT優先。S0はTのみ。旧判断fallbackなし"
    paths = [LEDGER, STUDY / "検証計画.md", OLD / "結果.json", OLD / "保存物確認.json", OLD / "固定.json",
        OLD / "条件.json", OLDWORK / "技法観測.jsonl.gz", ROOT / "work/局所波の出生と切替/00076/出生ATR参照.jsonl.gz",
        OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz",
        P77.P76.OLDWORK / "参照帯.json", P77.P76.PREVIOUS.PREVIOUS.IMMEDIATE, C.MANIFEST, C.FRAMES]
    cache = read(OLD / "入力台帳.json")["cacheSHA256"]
    inputs = {"試行": 78, "価格計算前": True, "全66場既使用": True,
        "参照SHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}, "cacheSHA256": cache,
        "新市場取得": 0, "新独立測定": 0, "11月5日Day読取": 0, "FAR新市場取得": 0}
    condition = STUDY / "条件.json"
    if condition.exists():
        if read(condition) != rules:
            raise ValueError("途中保存した78条件との不一致")
    else:
        C.write_json(condition, rules)
    C.write_json(STUDY / "入力台帳.json", inputs)
    print("78のADX資格と入力指紋を新観測の前に保存しました", flush=True)


def check_prepared() -> None:
    """条件保存時の全入力指紋を確認する。

    引数: なし。
    返り値: None。不一致で停止する。
    """
    for group in ("参照SHA256", "cacheSHA256"):
        for relative, digest in read(STUDY / "入力台帳.json")[group].items():
            if sha(ROOT / relative) != digest:
                raise ValueError("78入力保存後の差:" + relative)


def source_inputs() -> tuple:
    """旧73指標と保存77の参考二政策を読む。

    引数: なし。
    返り値: tupleは77結果、評価46台帳、旧指標block、77参考block索引。
    """
    verify_previous()
    _, entries, base, _ = P77.source_inputs()
    reference = {(b["session"], b["policy"]): b for b in rows(OLDWORK / "定時判断と運用.jsonl.gz") if b["policy"] in REFERENCES}
    if set(reference) != {(e["session"], p) for e in entries for p in REFERENCES}:
        raise ValueError("77参考全92運用集合差")
    return read(OLD / "結果.json"), entries, base, reference


def parent_guard(old: dict, new: dict) -> int:
    """資格以外の公開構造とT/R形成を全文同値検査する。

    引数: old/new(dict)は同定時の元/新観測。
    返り値: intは比較した延べ親数。独立標本数ではない。
    """
    for name in ("base_ready", "ready", "source_count", "source_sha256", "atr_source_sha256", "history", "band", "location", "parents", "formations", "candidates"):
        if old[name] != new[name]:
            raise ValueError("資格以外の公開構造差:" + name)
    return len(old["parents"])


def qualification_guard(old: dict, new: dict) -> None:
    """旧資格の理由列から許可した一理由だけが取り除かれたことを検査する。

    引数: old/new(dict)は同定時の旧/新観測。
    返り値: None。R・観測値・価格又は他の理由が変化すれば停止する。
    """
    before, after = old["qualifications"], new["qualifications"]
    if set(before) != set(after):
        raise ValueError("資格対象の形成集合差")
    forms = {c["id"]: c for c in new["candidates"]}
    for identity in before:
        a, b = before[identity], after[identity]
        if forms[identity]["kind"] == "R":
            if a != b:
                raise ValueError("R資格全文の差")
            continue
        expected = [r for r in a["reasons"] if r != "継続TのADXが減速"]
        if b != {**a, "reasons": expected, "qualified": not expected}:
            raise ValueError("T資格にADX符号以外の差")
    for old_policy, new_policy in (("E0", "S0"), ("E1", "S1")):
        a = old["selected_by_policy"][old_policy]
        b = new["selected_by_policy"][new_policy]
        if a["side"] and (a["side"], a["role"], a["selected"]) != (b["side"], b["role"], b["selected"]):
            raise ValueError("元純採用の包含差")
        if b["side"] and not a["side"]:
            selected = b["selected"]
            q = before[selected["id"]]
            if (selected["kind"] != "T" or q["reasons"] != ["継続TのADXが減速"]
                    or q["values"]["F48"] >= 0 or q["values"]["F51"] != 1 or q["values"]["F52"] != 1):
                raise ValueError("追加純Tが既知ADX減速だけの拡張でない")


def preflight() -> None:
    """全公開prefixの新資格を独立照合し、損益結合前に保存する。

    引数: なし。
    返り値: None。新ATR・先着・モデル・運用は計算しない。
    """
    destination = WORK / "技法観測.jsonl.gz"
    proof_path = PARENT / "入力確認.json"
    if destination.exists() or proof_path.exists():
        raise FileExistsError("78の入力は開始済み。既存handleを確認すること")
    verify_previous()
    check_prepared()
    art = read(STUDY / "入力人工確認.json")
    if not art["成功"] or art["不一致数"]:
        raise ValueError("78人工が未成功")
    for relative, digest in art["コードSHA256"].items():
        if sha(ROOT / relative) != digest:
            raise ValueError("78人工後のコード差")
    feature = load(HERE / "入力.py", "確認幅78本物の入力")
    independent = load(HERE / "入力監査.py", "確認幅78本物の独立入力")
    birth_path = ROOT / "work/局所波の出生と切替/00076/出生ATR参照.jsonl.gz"
    birth = P77.load(P77.P76.HERE / "出生ATR.py", "確認幅78の固定可視ATR補助")
    prepared = {r["session"]: r["package"] for r in rows(birth_path)}
    old_obs = {r["slot_id"]: r["observation"] for r in rows(OLDWORK / "技法観測.jsonl.gz")}
    _, entries, base, _ = source_inputs()
    identities = {s["slot_id"] for b in base.values() for s in b["slots"]}
    if set(old_obs) != identities or len(identities) != 1702 or len(prepared) != 66:
        raise ValueError("78全予定又は保存出生ATR集合差")
    quotes = P77.P76.PREVIOUS.quote_bank(identities)
    _, sessions = C.inputs()
    histories = {s["session"]: [{"session": s["session"], **r} for r in s["frames3"]] for s in sessions}
    bands = read(P77.P76.OLDWORK / "参照帯.json")
    counts = {"全予定": 0, "基礎準備": 0, "局所準備": 0, "S0方向": 0, "S1方向": 0, "R追加": 0, "親履歴不変件数": 0}
    WORK.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination, "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            prior = P77.P76.PREVIOUS.reference_for("P0", session, bands)
            for slot in base[session]["slots"]:
                visible = birth.visible_rows(prepared[session], slot["scheduled"], slot["time"], slot["line"]) if slot["ready"] else []
                args = slot, histories[session], visible, quotes[slot["slot_id"]], prior
                obs, expected = feature.extract(*args), independent.derive(*args)
                if obs != expected:
                    raise ValueError("78の資格入力独立差:" + slot["slot_id"])
                selected = {p: feature.choose(slot, obs, p) for p in POLICIES}
                for policy in POLICIES:
                    if selected[policy] != independent.choose(slot, obs, policy):
                        raise ValueError("78純射影の独立差")
                a, b = selected["S0"], selected["S1"]
                if a["side"] and any(a[k] != b[k] for k in PURE):
                    raise ValueError("S0純TのS1包含差")
                if b["side"] and not a["side"] and b["formation"] != "R":
                    raise ValueError("S1だけの追加がR以外")
                counts["親履歴不変件数"] += parent_guard(old_obs[slot["slot_id"]], obs)
                qualification_guard(old_obs[slot["slot_id"]], obs)
                counts["全予定"] += 1
                counts["基礎準備"] += bool(slot["ready"])
                counts["局所準備"] += bool(obs["ready"])
                counts["S0方向"] += bool(a["side"])
                counts["S1方向"] += bool(b["side"])
                counts["R追加"] += bool(b["side"] and not a["side"])
                C.jsonline(stream, {"session": session, "slot_id": slot["slot_id"], "observation": obs})
            print(session + " ADX資格と不変な公開履歴を照合", flush=True)
    if (counts["全予定"], counts["基礎準備"], counts["局所準備"]) != (1702, 1468, 1465):
        raise ValueError("78の入力完了集合差")
    C.write_json(proof_path, {"試行": 78, "成功": True, **counts, "観測SHA256": sha(destination),
        "出生ATR参照SHA256": sha(birth_path), "出生ATR再計算": 0,
        "コードSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in (HERE / "入力.py", HERE / "入力監査.py")},
        "新fit": 0, "新独立測定": 0, "新場内運用": 0, "ラベルによる採否選択": False})
    print(json.dumps({"入力確認": True, **counts}, ensure_ascii=False), flush=True)


# ----------------------------------------
def summarize(operations: dict, labels: dict, slots: dict, observations: dict) -> dict:
    """固定77の純集計へ局所対応し、結果の政策名を78へ戻す。

    引数: operations/labels/slots/observations(dict)は保存可能な記録。
    返り値: dictは六集計。旧moduleや入力辞書を変更しない。
    """
    obs = deepcopy(observations)
    for value in obs.values():
        value["selected_by_policy"] = {"E0": value["selected_by_policy"]["S0"], "E1": value["selected_by_policy"]["S1"]}
    args = [{NAME_MAP[p]: v for p, v in collection.items()} for collection in (operations, labels, slots)]
    value = P77.summarize(*args, obs)
    inverse = {v: k for k, v in NAME_MAP.items()}
    result = {key: {inverse[p]: data for p, data in value[key].items()} for key in ("候補", "利益保護", "技法被覆", "形成別", "場所別")}
    result["比較"] = {"対".join(inverse[p] for p in name.split("対")): data for name, data in value["比較"].items()}
    return result


def freeze() -> None:
    """成功入力と全新コードを場内運用前に固定する。

    引数: なし。
    返り値: None。既存固定を上書きしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("78は固定済み")
    verify_previous()
    check_prepared()
    art, entry = read(STUDY / "人工確認.json"), read(PARENT / "入力確認.json")
    if not art["成功"] or art["不一致数"] or not entry["成功"] or entry["全予定"] != 1702:
        raise ValueError("78の人工又は入力が未成功")
    for proof in (art, entry):
        for relative, digest in proof["コードSHA256"].items():
            if sha(ROOT / relative) != digest:
                raise ValueError("78成功後のコード差")
    if entry["観測SHA256"] != sha(WORK / "技法観測.jsonl.gz"):
        raise ValueError("78事前観測結合差")
    pins = dict(read(OLD / "固定.json")["ファイルSHA256"])
    pins.update(read(LEDGER)["成果物SHA256"])
    paths = [p for folder in (HERE, STUDY) for p in folder.iterdir() if p.is_file() and p.suffix in (".py", ".md", ".json")]
    paths += [LEDGER, PARENT / "入力確認.json", WORK / "技法観測.jsonl.gz"]
    paths += [ROOT / "docs/議論/外部再調査/ADXの水準と変化を入口で分ける.md",
              ROOT / "work/78候補/ADXの強さと変化の資格.md"]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative in pins and pins[relative] != sha(path):
            raise ValueError("78依存する旧対象の差")
        pins[relative] = sha(path)
    C.write_json(STUDY / "固定.json", {"試行": 78, "新運用前": True, "全66場既使用": True,
        "固定日時": datetime.now(C.JST).isoformat(), "Python": platform.python_version(),
        "NumPy": C.np.__version__, "ファイルSHA256": pins})
    print("78の新92運用前固定を保存しました", flush=True)


def verify_lock() -> None:
    """運用前の固定対象を検査する。

    引数: なし。
    返り値: None。既存固定を変更しない。
    """
    for relative, digest in read(STUDY / "固定.json")["ファイルSHA256"].items():
        if sha(ROOT / relative) != digest:
            raise ValueError("78固定後の差:" + relative)


def run() -> None:
    """新二政策だけ一度運用し、保存参考二政策と比較する。

    引数: なし。
    返り値: None。開始済みなら再起動せず停止する。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("78新運用は開始済み")
    verify_lock()
    old_result, entries, base, reference = source_inputs()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": sha(STUDY / "固定.json")})
    feature = load(HERE / "入力.py", "確認幅78の本物純射影")
    obs = {r["slot_id"]: r["observation"] for r in rows(WORK / "技法観測.jsonl.gz")}
    identities = {s["slot_id"] for b in base.values() for s in b["slots"]}
    if set(obs) != identities:
        raise ValueError("78保存観測の集合差")
    bank = P77.P76.measurement_bank(identities)
    operations, labels, slots = ({p: [] for p in ALL_POLICIES} for _ in range(3))
    for r in rows(OLDWORK / "入口先着.jsonl.gz"):
        if r["policy"] in REFERENCES:
            labels[r["policy"]].append(deepcopy(r))
    resources = [deepcopy(r) for r in read(OLD / "一覧.resources.json")["resources"] if r["method_id"] in REFERENCES]
    matched, summaries = {"実独立新規一致": 0, "実独立完結一致": 0}, []
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            for p in REFERENCES:
                operations[p].append(reference[session, p]["operation"])
                slots[p].extend(deepcopy(reference[session, p]["slots"]))
            events, quality = C.events_for(entry)
            for p in POLICIES:
                selected = [feature.choose(s, obs[s["slot_id"]], p) for s in base[session]["slots"]]
                slots[p].extend(selected)
                for s in selected:
                    if not s["side"]:
                        continue
                    measured = bank[s["slot_id"], s["side"]]
                    if any(measured["binding"][k] != s[k] for k in measured["binding"]):
                        raise ValueError("78採用方向の旧55入力差")
                    prior = measured["barrier"]
                    if prior is None or any(prior[k] != s[k] for k in ("session", "slot_id", "scheduled", "time", "line", "side")):
                        raise ValueError("78旧55先着出典差")
                    value = deepcopy(prior)
                    value.update(policy=p, role=s["role"], origin=s["origin"], pattern_id=s["pattern_id"], parent_id=s["parent_id"], formation=s["formation"])
                    labels[p].append(value)
                operation = O49.replay(events, [{k: s[k] for k in PURE} for s in selected], session, p)
                for order in operation["orders"]:
                    if order["kind"] == "entry" and order["status"] == "filled":
                        prior = bank[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                        if not prior["filled"] or any(order["fill_" + k] != prior["entry_" + k] for k in ("time", "line", "price")):
                            raise ValueError("78新規と独立先着の差")
                        matched["実独立新規一致"] += 1
                for closed in operation["closed"]:
                    prior = bank[closed["slot_id"], closed["side"]]["closed"]
                    if len(prior) != 1 or not P55.equivalent_close(closed, prior[0]):
                        raise ValueError("78回収と独立完結の差")
                    matched["実独立完結一致"] += 1
                operations[p].append(operation)
                C.jsonline(stream, {"session": session, "phase": base[session]["phase"], "policy": p,
                    "slots": selected, "input_quality": quality, "operation": operation})
                path = STUDY / "viewer" / (p + "_" + session + ".trades.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as trades:
                    for trade in operation["trades"]:
                        C.jsonline(trades, trade)
                resources.append({"id": session + "_" + p, "title": session + " " + p + " ADX水準と変化の資格", "symbol": "NK225", "session": session,
                    "product": "NK225micro", "method_id": p, "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                    "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                summaries.append({"場": session, "候補": p, "期間": C.period(session), "入力品質": quality,
                    "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            print(session + " ADX資格の新二政策運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for p in POLICIES:
            for r in labels[p]:
                C.jsonline(stream, r)
    result = summarize(operations, labels, slots, obs)
    for p in REFERENCES:
        if result["候補"][p] != old_result["候補"][p] or result["利益保護"][p] != old_result["利益保護"][p]:
            raise ValueError("78保存参考再集計差")
    if len(summaries) != 92 or len(resources) != 184:
        raise ValueError("78新92/参考92/Viewer184集合差")
    result.update(試行=78, 実行日時=datetime.now(C.JST).isoformat(), 全66場既使用=True, 固定SHA256=sha(STUDY / "固定.json"),
        新fit=0, 新分類器fit=0, 新モデル=0, 新独立測定=0, 新運用数=92, 保存参照運用数=92, Viewer資源=184,
        評価場=[e["session"] for e in entries], 設定=read(STUDY / "条件.json"), 検査=matched, 場別=summaries,
        入力確認=read(PARENT / "入力確認.json"),
        採用=[p for p in POLICIES if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])],
        詳細={p.name: sha(p) for p in WORK.glob("*.gz")})
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新運用": 92, "保存参考": 92, "検査": matched}, ensure_ascii=False), flush=True)


def self_test() -> dict:
    """空集計の政策対応・null・比較名と親防御の拒否を確かめる。

    引数: なし。
    返り値: dictは人工結果。市場本文は読まない。
    """
    empty = {p: [] for p in ALL_POLICIES}
    value = summarize(deepcopy(empty), deepcopy(empty), deepcopy(empty), {})
    count = 0
    for policy in ALL_POLICIES:
        for period in PERIODS:
            row = value["候補"][policy][period]
            assert row["入口"]["率"] is None and row["入口"]["間引き率"] is None
            assert row["同時適格"] is False
            count += 2
    assert set(value["比較"]) == {"E0対S0", "E0対S1", "E1対S1", "S0対S1"}
    count += 1
    for p in POLICIES:
        for period in PERIODS:
            assert set(value["形成別"][p][period]) == {"T", "R"} and len(value["場所別"][p][period]) == 6
            count += 1
    old = {k: [] for k in ("parents", "formations", "candidates", "history", "band", "location")}
    old.update(base_ready=True, ready=True, source_count=0, source_sha256="a", atr_source_sha256="b")
    assert parent_guard(old, deepcopy(old)) == 0
    new = deepcopy(old)
    new["ready"] = False
    try:
        parent_guard(old, new)
    except ValueError:
        count += 1
    else:
        raise AssertionError("親防御の拒否なし")
    return {"成功": True, "不一致数": 0, "テスト件数": 3, "照合項目数": count, "本物入力読取": False}


# ----------------------------------------
def main() -> None:
    """新入力から場内運用までの一工程だけを選ぶ。

    引数: CLIのprepare/check-prepared/preflight/freeze/run/self-test(bool)は排他的。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "check-prepared", "preflight", "freeze", "run", "self-test"):
        group.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    for name, action in (("prepare", prepare), ("check_prepared", check_prepared), ("preflight", preflight), ("freeze", freeze), ("run", run)):
        if getattr(args, name):
            action()
            return
    print(json.dumps(self_test(), ensure_ascii=False))


if __name__ == "__main__":
    main()
