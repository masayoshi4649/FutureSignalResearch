"""76の局所波研究に必要な、価格計算前の条件と固定入力を保存する。"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00076_局所波の押戻しと起点喪失を分ける"
PARENT = ROOT / "work/局所波の出生と切替"
WORK = PARENT / "00076"
OLD = ROOT / "study/00075_事前帯の外保持と内回帰を判別"
OLDWORK = ROOT / "work/事前帯と現在の反応/00075"
LEDGER = OLDWORK.parent / "75完了記録.json"
LEDGER_SHA = "13deab86d335ac62bc5ac93b3fe1f0006efbead2752ea0b26d2406dca1781031"
BIRTH_CODE = ROOT / "scripts/定時帯反応/入口.py"
BIRTH_CODE_SHA = "f42aea5cbb7d5f46d62dff7fd7769e5328c9951c213aaeccb9a912a6f67bd373"
POLICIES = ("L0", "L1")
REFERENCES = ("O0", "P0")
ALL_POLICIES = (*REFERENCES, *POLICIES)
PERIODS = ("学習", "条件選択", "後続検査")
PURE = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")
PAIRS = (("O0", "L0"), ("O0", "L1"), ("P0", "L1"), ("L0", "L1"))
STAGE = PARENT / "入力段階記録.json"
STAGE_SHA = "d0617465782bf943fb0582c345a8dce079395fe2f5523c6c6fe085e880818635"


def load(path: Path, name: str):
    """旧固定補助を固有名で読み、CLIの処理を起動しない。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(ROOT / "scripts/事前帯と現在の反応/検証.py", "局所波76の固定75主")
C, P, O49, B68, P55 = PREVIOUS.C, PREVIOUS.P, PREVIOUS.O49, PREVIOUS.B68, PREVIOUS.P55


def rows(path: Path):
    """gzipを展開ファイルへ複写せず一行ずつ読む。

    引数: path(Path)はJSONL gzip。
    返り値: Iterator[dict]は保存行。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def verify_previous() -> dict:
    """75完了台帳190対象の不変を検査する。

    引数: なし。
    返り値: dictは完了台帳。不一致なら停止。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("75完了台帳の変更")
    value = C.read_json(LEDGER)
    if value["試行"] != 75 or len(value["成果物SHA256"]) != 190:
        raise ValueError("75完了対象数の差")
    for relative, digest in value["成果物SHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("75完了物の変更:" + relative)
    return value


# ----------------------------------------
# 本文の価格や損益を計算する前に、入力と独自条件を固定する。

def prepare() -> None:
    """76の条件と全入力指紋を、追加数値銀行の構成前に保存する。

    引数: なし。
    返り値: None。既存の条件・入力台帳は上書きしない。
    """
    verify_previous()
    if any((STUDY / name).exists() for name in ("条件.json", "入力台帳.json")):
        raise FileExistsError("76の事前条件は保存済み")
    if C.sha(C.MANIFEST) != C.MANIFEST_SHA or C.sha(BIRTH_CODE) != BIRTH_CODE_SHA:
        raise ValueError("66場台帳又は固定49数値規約の変更")
    manifest = C.read_json(C.MANIFEST)
    entries = manifest["entries"]
    if len(entries) != 66 or len({e["session"] for e in entries}) != 66:
        raise ValueError("元66場の集合差")
    cache = {}
    for entry in entries:
        path = ROOT / "work/複合検証" / entry["cache_path"]
        if C.sha(path) != entry["sha256_cache"]:
            raise ValueError("66場cacheの指紋差")
        cache[path.relative_to(ROOT).as_posix()] = entry["sha256_cache"]
    result = C.read_json(OLD / "結果.json")
    proof = C.read_json(OLD / "保存物確認.json")
    if not proof["全件一致"] or proof["不一致数"] or proof["結果SHA256"] != C.sha(OLD / "結果.json"):
        raise ValueError("75の成功証明と結果の結合差")
    rules = {"試行": 76, "全66場既使用": True,
        "政策": {"O0": {"保存参考": True, "出典": "75当場OR30・49即時"},
            "P0": {"保存参考": True, "出典": "75前収録帯・49即時"},
            "L0": {"保存参考": False, "採用": "同親局所波のTのみ", "注文": "49即時"},
            "L1": {"保存参考": False, "採用": "L0と同じ全履歴からT/R", "注文": "49即時"}},
        "親": {"同時数": 1, "出生足": 3, "最低進行ATR倍": 1,
            "出生": "a/m/b完全隣接・2終値差が同じsへstrict正・s(Cb-Ca)>=ATR_b",
            "origin": "s=+1ならa.low、-1ならa.high。bで固定、完成pivotではない",
            "登録": "存続中新bなし。終端/reset足と次a兼用なし、後続3足から再登録",
            "準備と待機": "初期/品質/ATR未知後3足までは未準備、正常終端後はprepared維持・再出生buffer0..2は既知待機",
            "T": "最初逆終値r、別足の最初r実方向端strict終値突破k。k前origin維持、k後originとr反対端の厳しい線維持",
            "f": "最初s(C-origin)<=0をT取消/r/kより優先し、同じ親Rへ。T戦術取消だけでRを開始しない",
            "R": "f後1..3別足で最初のf実R方向端strict終値突破k。待機中origin再獲得で終了。k後originとf反対端の厳しい線維持",
            "親寿命秒": 1620, "R確認秒": 540,
            "期限": "足endと公開confirmが期限以内、strict超は確認より先に終了、実判断timeにも適用。Rのk後は親期限まで",
            "価格否定": "終値で等号込み。現在Last/E*はpremise strict側、ヒゲ順序の推測0",
            "鮮度": "独立900秒gateは未使用。親TTLで制限し、k経過と反復を診断"},
        "入力": {"基礎ready": "旧73readyを維持。未使用履歴/旧OR/TV等の継承を限界と記録",
            "出生ATR": "固定49 NumericBank(3).buildのみを元66場SOURCE順/同限月carryで構成、bのSOURCE/keyへ結合",
            "未知": "出生ATR未知/不良SOURCEは親とbufferをclearし3つの新準備済み足で再準備。未知を0補完しない",
            "判断値": "旧73float64のF01/02/03/07/15/47/48/51/52とATR_j/D、旧55当時quoteを厳密再用",
            "前帯": "75保存前帯は内外/前方線の診断のみ。不明でもLreadyを落とさない", "新量gate": False},
        "複合": {"全候補": "F01非零/rawDI非同値・F02>=0・F03>0・F07>0・LastとE*はpremise strict外",
            "T": "F01>0 AND F51=F52=1 AND F47>=0.20 AND F48>=0、順行",
            "R": "F01>0なら順行、F01<0ならF52=1/F48<0/F15>0で反転",
            "単位": "F47=ADX/100、F48=deltaADX/100、F15=実方向CLV",
            "選択": "最新k公開key、同keyT優先。L0はTのみ。旧判断fallbackなし",
            "追加しない選別": ["前提距離<=D", "中央250余地", "量", "独立900秒鮮度"]},
        "運用": deepcopy(C.read_json(OLD / "条件.json")["利益保護"]),
        "費用": deepcopy(C.read_json(OLD / "条件.json")["費用"]),
        "定時": "Day09:15..15:15・Night17:30..05:30、全1702枠、保有非待ち",
        "入口": "49即時要求後1価格秒・後原行正常BBO、TTL30、Dは保存ATR_jによる5pt切上5..125",
        "先着": "250pt以上が125pt以上逆行より先、主/非重複の支持付き70%",
        "評価場": result["評価場"], "新fit": 0, "新モデル": 0, "新独立測定": 0,
        "新運用": 92, "保存参考": 92, "Viewer資源": 184, "表版": 5, "手法数": 55, "尺度数": 9,
        "採用": "入口/費用/品質/全枠待ち50%以下を別検査。未使用期確認は別に必要"}
    paths = [LEDGER, STUDY / "検証計画.md", OLD / "結果.json", OLD / "保存物確認.json", OLD / "固定.json",
        OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz", OLDWORK / "参照帯.json",
        PREVIOUS.PREVIOUS.OLDWORK / "定時判断と運用.jsonl.gz", PREVIOUS.PREVIOUS.IMMEDIATE,
        C.MANIFEST, C.FRAMES, BIRTH_CODE]
    C.write_json(STUDY / "条件.json", rules)
    C.write_json(STUDY / "入力台帳.json", {"試行": 76, "価格計算前": True, "全66場既使用": True,
        "参照SHA256": {p.relative_to(ROOT).as_posix(): C.sha(p) for p in paths}, "cacheSHA256": cache,
        "新市場取得": 0, "新独立測定": 0, "11月5日Day読取": 0, "FAR新市場取得": 0})
    print("76の独自条件と元66場入力指紋を、出生ATR計算前に保存しました", flush=True)


def check_prepared() -> None:
    """事前入力の指紋を確認する。

    引数: なし。
    返り値: None。不一致なら停止する。
    """
    value = C.read_json(STUDY / "入力台帳.json")
    for group in ("参照SHA256", "cacheSHA256"):
        for relative, digest in value[group].items():
            if C.sha(ROOT / relative) != digest:
                raise ValueError("76の事前保存後の差:" + relative)


def preflight() -> None:
    """出生ATRと全予定の親波を別算照合し、損益を結ぶ前に保存する。

    引数: なし。
    返り値: None。新独立測定・fit・場内運用を起動しない。
    """
    destination = WORK / "技法観測.jsonl.gz"
    birth_path = WORK / "出生ATR参照.jsonl.gz"
    if destination.exists() or birth_path.exists() or (PARENT / "入力確認.json").exists():
        raise FileExistsError("76の入力は開始済み。既存handleと保存物を確認すること")
    verify_previous()
    check_prepared()
    artificial = C.read_json(STUDY / "入力人工確認.json")
    if not artificial["成功"] or artificial["不一致数"]:
        raise ValueError("76の入力人工が未成功")
    for relative, digest in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("76入力人工後のコード差:" + relative)
    birth = load(HERE / "出生ATR.py", "局所波76の出生参照")
    birth_audit = load(HERE / "出生ATR監査.py", "局所波76の独立出生参照")
    feature = load(HERE / "入力.py", "局所波76の親波入力")
    independent = load(HERE / "入力監査.py", "局所波76の独立親波")
    numeric_rules = load(BIRTH_CODE, "局所波76の固定49距離規約")
    _, sessions = C.inputs()
    prepared = birth.build(sessions)
    expected = birth_audit.derive_atr(sessions)
    if list(prepared) != list(expected) or list(prepared) != [s["session"] for s in sessions]:
        raise ValueError("出生ATRの66場元順の差")
    count = {"出生ATR場": 0, "出生ATR行": 0, "全予定": 0, "基礎準備": 0,
        "局所準備": 0, "L0方向": 0, "L1方向": 0, "R追加": 0, "判断ATR同値": 0}
    WORK.mkdir(parents=True, exist_ok=True)
    with gzip.open(birth_path, "wt", encoding="utf-8") as stream:
        for session, package in prepared.items():
            if birth.canonical(package) != birth.canonical(expected[session]):
                raise ValueError("出生ATRの別算法差:" + session)
            count["出生ATR場"] += 1
            count["出生ATR行"] += len(package["rows"])
            C.jsonline(stream, {"session": session, "package": package})
    _, entries, blocks = PREVIOUS.source_inputs()
    identities = {s["slot_id"] for block in blocks.values() for s in block["slots"]}
    if len(identities) != 1702:
        raise ValueError("76の全予定集合差")
    quotes = PREVIOUS.quote_bank(identities)
    histories = {s["session"]: [{"session": s["session"], **r} for r in s["frames3"]] for s in sessions}
    bands = C.read_json(OLDWORK / "参照帯.json")
    with gzip.open(destination, "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            history = histories[session]
            numeric = prepared[session]["rows"]
            indexed = {r["index"]: r for r in numeric}
            if len(indexed) != len(numeric):
                raise ValueError("出生ATR足番号の重複")
            prior = PREVIOUS.reference_for("P0", session, bands)
            for slot in blocks[session]["slots"]:
                if slot["ready"]:
                    current = slot["feature"]["base"]["base"]["sources"]["current"]
                    row = indexed[current["index"]]
                    birth.bind(row, current)
                    if not row["ready"] or row["atr"] != slot["atr"] or numeric_rules.distance(row["atr"]) != slot["D"]:
                        raise ValueError("判断時の再構成ATR/Dと旧73の差")
                    count["判断ATR同値"] += 1
                visible_numeric = birth.visible_rows(prepared[session], slot["scheduled"], slot["time"], slot["line"]) if slot["ready"] else []
                observation = feature.extract(slot, history, visible_numeric, quotes[slot["slot_id"]], prior)
                check = independent.derive(slot, history, visible_numeric, quotes[slot["slot_id"]], prior)
                if observation != check:
                    raise ValueError("76親波の独立算術差:" + slot["slot_id"])
                selected = {p: feature.choose(slot, observation, p) for p in POLICIES}
                for policy in POLICIES:
                    if selected[policy] != independent.choose(slot, observation, policy):
                        raise ValueError("76政策射影の独立差")
                left, right = selected["L0"], selected["L1"]
                if left["side"] and any(left[k] != right[k] for k in PURE):
                    raise ValueError("L0のTはL1でも同じ純判断でなければならない")
                if right["side"] and not left["side"] and right["formation"] != "R":
                    raise ValueError("L1だけの追加は同親Rに限る")
                count["全予定"] += 1
                count["基礎準備"] += bool(slot["ready"])
                count["局所準備"] += bool(observation["ready"])
                count["L0方向"] += bool(left["side"])
                count["L1方向"] += bool(right["side"])
                count["R追加"] += bool(right["side"] and not left["side"])
                C.jsonline(stream, {"session": session, "slot_id": slot["slot_id"], "observation": observation})
            print(session + " 局所波の公開prefixと独立選択を照合", flush=True)
    if count["全予定"] != 1702 or count["出生ATR場"] != 66:
        raise ValueError("76の入力完了集合差")
    C.write_json(PARENT / "入力確認.json", {"試行": 76, "成功": True, **count,
        "観測SHA256": C.sha(destination), "出生ATR参照SHA256": C.sha(birth_path),
        "コードSHA256": {p.relative_to(ROOT).as_posix(): C.sha(p) for p in (
            HERE / "出生ATR.py", HERE / "出生ATR監査.py", HERE / "入力.py", HERE / "入力監査.py")},
        "新fit": 0, "新独立測定": 0, "新場内運用": 0, "ラベルによる採否選択": False})
    print(json.dumps({"入力確認": True, **count}, ensure_ascii=False), flush=True)


def verify_stage() -> dict:
    """完了した76入力段階と不変入力を確認し、再生成しない。

    引数: なし。
    返り値: dictは入力段階記録。主の後続コード追加は許すが、入力を変更しない。
    """
    if C.sha(STAGE) != STAGE_SHA:
        raise ValueError("76入力段階記録の変更")
    stage = C.read_json(STAGE)
    if stage["試行"] != 76 or not stage["入力"]["成功"] or stage["入力"]["全予定"] != 1702:
        raise ValueError("76入力段階が未成功")
    for relative, digest in stage["不変とする入力SHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("76入力段階後の差:" + relative)
    proof = C.read_json(STUDY / "入力人工確認.json")
    for relative, digest in proof["コードSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("76入力人工後の変更:" + relative)
    return stage


def source_inputs() -> tuple:
    """旧75の二参考運用と、旧73の同じ予定・指標を読む。

    引数: なし。
    返り値: tupleは75結果、評価46台帳、73Q0指標block、75参考block索引。
    """
    verify_previous()
    verify_stage()
    _, entries, base = PREVIOUS.source_inputs()
    reference = {(b["session"], b["policy"]): b for b in rows(OLDWORK / "定時判断と運用.jsonl.gz") if b["policy"] in REFERENCES}
    if len(reference) != 92 or set(reference) != {(e["session"], p) for e in entries for p in REFERENCES}:
        raise ValueError("75の二参考46場の集合差")
    for entry in entries:
        identifiers = [s["slot_id"] for s in base[entry["session"]]["slots"]]
        for policy in REFERENCES:
            if [s["slot_id"] for s in reference[entry["session"], policy]["slots"]] != identifiers:
                raise ValueError("旧参考と同じ全予定ID順が必要")
    return C.read_json(OLD / "結果.json"), entries, base, reference


def measurement_bank(identities: set) -> dict:
    """旧55即時銀行だけを読み、全予定両方向と入力を維持する。

    引数: identities(set[str])は全1,702枠。
    返り値: dictは元枠/sideからbinding/barrier/closedへの索引。69は使わない。
    """
    path = PREVIOUS.PREVIOUS.IMMEDIATE
    pin = C.read_json(STUDY / "入力台帳.json")["参照SHA256"][path.relative_to(ROOT).as_posix()]
    if C.sha(path) != pin:
        raise ValueError("旧55独立銀行の変更")
    result = {}
    for row in rows(path):
        if row["slot_id"] not in identities:
            continue
        key = row["slot_id"], row["side"]
        if key in result:
            raise ValueError("旧55の全予定方向重複")
        binding = {k: row[k] for k in ("session", "slot_id", "scheduled", "time", "line", "side", "ready", "atr", "D")}
        result[key] = {"binding": binding, "barrier": row["barrier"],
            "closed": row["operation"]["closed"] if row["operation"] is not None else None}
    if set(result) != {(i, s) for i in identities for s in (1, -1)}:
        raise ValueError("旧55の全予定両方向集合差")
    return result


def distribution(values: list) -> dict:
    """同じ定義の確認経過や価格距離を小型統計へまとめる。

    引数: values(list[float])は有限観測。
    返り値: dictは平均/中央値/最小/最大。空では各None。
    """
    return {"平均": sum(values) / len(values) if values else None, "中央値": statistics.median(values) if values else None,
        "最小": min(values) if values else None, "最大": max(values) if values else None}


# ----------------------------------------
# 保存値だけを集計し、独立ラベルと一枚回収の分母を分ける。

def summarize(operations: dict, labels: dict, slots: dict, observations: dict) -> dict:
    """二参考と新二政策の回収・支持・親波・場所・参加差を集計する。

    引数: operations/labels/slots/observations(dict)は保存可能な記録。
    返り値: dictは集計。条件を変更した仮想hybridの額は作らない。
    """
    result = {name: {p: {} for p in ALL_POLICIES} for name in ("候補", "利益保護", "技法被覆", "形成別", "場所別")}
    result["比較"] = {}
    closes = {p: [{**r, "session": o["session"]} for o in operations[p] for r in o["closed"]] for p in ALL_POLICIES}
    for policy in ALL_POLICIES:
        for period in PERIODS:
            ss = [s for s in slots[policy] if C.period(s["session"]) == period]
            ll = [r for r in labels[policy] if C.period(r["session"]) == period]
            cc = [r for r in closes[policy] if C.period(r["session"]) == period]
            stat = C.operation_stats(operations[policy], period)
            stat.update(条件登録数=0, 条件未約定=0)
            entrance = B68.entry_stats(ll, period, C.period)
            result["候補"][policy][period] = {"入口": entrance, "運用": stat,
                "同時適格": entrance["70目標"] and stat["活動適格"] and stat["費用適格"]}
            label_map = {r["slot_id"]: r for r in ll}
            red = [r for r in cc if r["arm"] and r["pnl5"] < 0]
            result["利益保護"][policy][period] = {"利益旗": sum(r["arm"] for r in cc), "旗後赤": len(red),
                "同値": sum(r["exit_price"] == r["entry_price"] for r in red),
                "有利費用負け": sum(r["side"] * (r["exit_price"] - r["entry_price"]) > 0 for r in red),
                "不利": sum(r["side"] * (r["exit_price"] - r["entry_price"]) < 0 for r in red),
                "先着250前の実退出": sum(label_map[r["slot_id"]]["outcome"] == "250" and
                    (r["exit_time"], r["exit_line"]) < (label_map[r["slot_id"]]["end_time"], label_map[r["slot_id"]]["end_line"]) for r in cc)}
            if policy in REFERENCES:
                continue
            oo = [observations[s["slot_id"]] for s in ss]
            parents = [p for o in oo for p in o["parents"]]
            forms = [f for o in oo for f in o["formations"]]
            adopted = [s for s in ss if s["side"]]
            picked = [o["selected_by_policy"][policy]["selected"] for o in oo if o["selected_by_policy"][policy]["side"]]
            result["技法被覆"][policy][period] = {"定時枠": len(ss), "基礎準備": sum(o["base_ready"] for o in oo),
                "準備済み": sum(o["ready"] for o in oo), "追加未準備": sum(o["base_ready"] and not o["ready"] for o in oo),
                "理由別": dict(Counter(s["reason"] for s in ss)), "観測理由別": dict(Counter(o["reason"] for o in oo)),
                "親観測": len(parents), "親unique": len({p["id"] for p in parents}), "親状態別": dict(Counter(p["status"] for p in parents)),
                "起点喪失f観測": sum(p["f"] is not None for p in parents),
                "遅いf観測": sum(p["late_f"] is not None and p["late_f"]["reason"] is not None for p in parents),
                "形観測": len(forms), "形unique": len({f["id"] for f in forms}), "状態別": dict(Counter(f["status"] for f in forms)),
                "現在active観測": sum(len(o["candidates"]) for o in oo), "適格方向": len(adopted),
                "順行": sum(s["role"] == "順行" for s in adopted), "反転": sum(s["role"] == "反転" for s in adopted),
                "採用形unique": len({s["pattern_id"] for s in adopted}), "採用親unique": len({s["parent_id"] for s in adopted}),
                "形成別採用": dict(Counter(s["formation"] for s in adopted)),
                "基本不適格理由観測": dict(Counter(r for o in oo for q in o["qualifications"].values() for r in q["reasons"])),
                "採用k経過秒": distribution([f["k_age_seconds"] for f in picked]),
                "採用k終了経過秒": distribution([f["k_end_age_seconds"] for f in picked]),
                "採用tip距離pt": distribution([f["tip_distance"] for f in picked]),
                "同形成最大反復枠": max(Counter(s["pattern_id"] for s in adopted).values(), default=0),
                "reset観測": sum(len(o["history"]["resets"]) for o in oo),
                "出生拒否観測": sum(len(o["history"]["rejected_births"]) for o in oo)}
            sm = {s["slot_id"]: s for s in ss}
            result["形成別"][policy][period] = {}
            for kind in ("T", "R"):
                gs = [s for s in adopted if s["formation"] == kind]
                gl = [r for r in ll if sm[r["slot_id"]]["formation"] == kind]
                gc = [r for r in cc if sm[r["slot_id"]]["formation"] == kind]
                result["形成別"][policy][period][kind] = {"純候補": len(gs), "形unique": len({s["pattern_id"] for s in gs}),
                    "入口": B68.entry_stats(gl, period, C.period), "実完結": len(gc),
                    "費用別観測円": {str(f): sum(r["pnl" + str(f)] for r in gc) for f in (0, 5, 10)},
                    "役割別完結": {role: sum(r["role"] == role for r in gc) for role in ("順行", "反転")}}
            position = {s["slot_id"]: observations[s["slot_id"]]["location"]["by_side"][str(s["side"])]["position"] for s in adopted}
            result["場所別"][policy][period] = {}
            for where in ("上外", "上端", "帯内", "下端", "下外", "未知"):
                gs = [s for s in adopted if position[s["slot_id"]] == where]
                gl = [r for r in ll if position[r["slot_id"]] == where]
                gc = [r for r in cc if position[r["slot_id"]] == where]
                result["場所別"][policy][period][where] = {"純候補": len(gs), "入口": B68.entry_stats(gl, period, C.period),
                    "実完結": len(gc), "費用別観測円": {str(f): sum(r["pnl" + str(f)] for r in gc) for f in (0, 5, 10)}}
    # ----------------------------------------
    # 純候補集合と、保有占有を通った実参加集合を別に比較する。
    for left, right in PAIRS:
        result["比較"][left + "対" + right] = {}
        for period in PERIODS:
            a = {s["slot_id"]: s for s in slots[left] if C.period(s["session"]) == period}
            b = {s["slot_id"]: s for s in slots[right] if C.period(s["session"]) == period}
            if set(a) != set(b):
                raise ValueError("76政策の全予定集合差")
            pure = Counter()
            for key in a:
                x, y = a[key]["side"], b[key]["side"]
                pure["双方待機" if not x and not y else "左のみ" if x and not y else "右のみ" if y and not x else "同方向" if x == y else "反対切替"] += 1
            ca = {(r["slot_id"], r["side"]): r for r in closes[left] if C.period(r["session"]) == period}
            cb = {(r["slot_id"], r["side"]): r for r in closes[right] if C.period(r["session"]) == period}
            common, onlya, onlyb = sorted(set(ca) & set(cb)), sorted(set(ca) - set(cb)), sorted(set(cb) - set(ca))
            exact = [k for k in common if all(ca[k][n] == cb[k][n] for n in ("entry_time", "entry_line", "entry_price"))]
            result["比較"][left + "対" + right][period] = {"純": dict(pure), "準備共通": sum(a[k]["ready"] and b[k]["ready"] for k in a),
                "左準備のみ": sum(a[k]["ready"] and not b[k]["ready"] for k in a), "右準備のみ": sum(b[k]["ready"] and not a[k]["ready"] for k in a),
                "実": {"左完結": len(ca), "右完結": len(cb), "共通元枠同方向": len(common), "左のみ": len(onlya), "右のみ": len(onlyb),
                    "共通元枠差額5": sum(cb[k]["pnl5"] - ca[k]["pnl5"] for k in common),
                    "左のみ額5": sum(ca[k]["pnl5"] for k in onlya), "右のみ額5": sum(cb[k]["pnl5"] for k in onlyb),
                    "厳密同新規": len(exact), "厳密同新規出口差5": sum(cb[k]["pnl5"] - ca[k]["pnl5"] for k in exact)}}
    return result


# ----------------------------------------
# 事前固定と、二つの新政策だけの一回運用を行う。

def freeze() -> None:
    """成功入力と人工・実装・表示設定を新運用前に固定する。

    引数: なし。
    返り値: None。既存固定を上書きしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("76は固定済み")
    previous = verify_previous()
    verify_stage()
    check_prepared()
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"] or artificial["不一致数"]:
        raise ValueError("76の運用前人工が未成功")
    for relative, digest in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("76人工後のコード差")
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(previous["成果物SHA256"])
    paths = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), *STUDY.glob("*.md"), LEDGER, STAGE,
        WORK / "出生ATR参照.jsonl.gz", WORK / "技法観測.jsonl.gz", PARENT / "入力確認.json"]
    paths += list((ROOT / "work/76設計").glob("*.md")) + list((ROOT / "work/外部調査_76").glob("*.md"))
    paths += [ROOT / "docs/議論/外部再調査/局所波の押戻しと確認時点を分ける.md",
        ROOT / "docs/議論/外部再調査/広い帯の内側と局所の波を分ける.md"]
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    for relative, digest in pins.items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("76固定依存の差:" + relative)
    C.write_json(STUDY / "固定.json", {"試行": 76, "新運用前": True, "全66場既使用": True,
        "固定日時": datetime.now(C.JST).isoformat(), "Python": platform.python_version(), "NumPy": C.np.__version__, "ファイルSHA256": pins})
    print("76を新92一枚運用の前に固定しました", flush=True)


def verify_lock() -> None:
    """新運用前の全指紋を確認する。

    引数: なし。
    返り値: None。不一致なら停止する。
    """
    for relative, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("76固定後の差:" + relative)


def run() -> None:
    """保存観測から新L0/L1を一度だけ場内運用し、二参考と比較する。

    引数: なし。
    返り値: None。開始済みは既存handleの終端確認を要求し、再起動しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("76の新運用は開始済み")
    verify_lock()
    old_result, entries, base, reference = source_inputs()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    feature = load(HERE / "入力.py", "局所波76本物の純射影")
    observations = {r["slot_id"]: r["observation"] for r in rows(WORK / "技法観測.jsonl.gz")}
    identities = {s["slot_id"] for b in base.values() for s in b["slots"]}
    if set(observations) != identities:
        raise ValueError("76保存観測の全予定集合差")
    bank = measurement_bank(identities)
    operations, labels, slots = ({p: [] for p in ALL_POLICIES} for _ in range(3))
    for r in rows(OLDWORK / "入口先着.jsonl.gz"):
        if r["policy"] in REFERENCES:
            labels[r["policy"]].append(deepcopy(r))
    resources = [deepcopy(r) for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in REFERENCES]
    matched = {"実独立新規一致": 0, "実独立完結一致": 0}
    summaries = []
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            for p in REFERENCES:
                operations[p].append(reference[session, p]["operation"])
                slots[p].extend(deepcopy(reference[session, p]["slots"]))
            events, quality = C.events_for(entry)
            for p in POLICIES:
                selected = [feature.choose(s, observations[s["slot_id"]], p) for s in base[session]["slots"]]
                slots[p].extend(selected)
                for s in selected:
                    if not s["side"]:
                        continue
                    measured = bank[s["slot_id"], s["side"]]
                    if any(measured["binding"][key] != s[key] for key in measured["binding"]):
                        raise ValueError("76採用方向の旧55入力差")
                    prior = measured["barrier"]
                    if prior is None or any(prior[k] != s[k] for k in ("session", "slot_id", "scheduled", "time", "line", "side")):
                        raise ValueError("76採用方向の旧55先着出典差")
                    value = deepcopy(prior)
                    value.update(policy=p, role=s["role"], origin=s["origin"], pattern_id=s["pattern_id"], parent_id=s["parent_id"], formation=s["formation"])
                    labels[p].append(value)
                operation = O49.replay(events, [{k: s[k] for k in PURE} for s in selected], session, p)
                for order in operation["orders"]:
                    if order["kind"] == "entry" and order["status"] == "filled":
                        prior = bank[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                        if not prior["filled"] or any(order["fill_" + k] != prior["entry_" + k] for k in ("time", "line", "price")):
                            raise ValueError("76一枚新規と旧55独立先着の差")
                        matched["実独立新規一致"] += 1
                for closed in operation["closed"]:
                    prior = bank[closed["slot_id"], closed["side"]]["closed"]
                    if len(prior) != 1 or not P55.equivalent_close(closed, prior[0]):
                        raise ValueError("76一枚回収と旧55独立完結の差")
                    matched["実独立完結一致"] += 1
                operations[p].append(operation)
                C.jsonline(stream, {"session": session, "phase": base[session]["phase"], "policy": p,
                    "slots": selected, "input_quality": quality, "operation": operation})
                path = STUDY / "viewer" / (p + "_" + session + ".trades.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as trades:
                    for trade in operation["trades"]:
                        C.jsonline(trades, trade)
                resources.append({"id": session + "_" + p, "title": session + " " + p + " 局所波の出生と切替", "symbol": "NK225", "session": session,
                    "product": "NK225micro", "method_id": p, "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                    "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                summaries.append({"場": session, "候補": p, "期間": C.period(session), "入力品質": quality,
                    "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            print(session + " 局所波の新二政策運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for p in POLICIES:
            for r in labels[p]:
                C.jsonline(stream, r)
    result = summarize(operations, labels, slots, observations)
    for p in REFERENCES:
        if result["候補"][p] != old_result["候補"][p] or result["利益保護"][p] != old_result["利益保護"][p]:
            raise ValueError("76の保存参考の再集計差")
    if len(summaries) != 92 or len(resources) != 184:
        raise ValueError("76新92/参考92/Viewer184の差")
    result.update(試行=76, 実行日時=datetime.now(C.JST).isoformat(), 全66場既使用=True, 固定SHA256=C.sha(STUDY / "固定.json"),
        新fit=0, 新分類器fit=0, 新モデル=0, 新独立測定=0, 新運用数=92, 保存参照運用数=92, Viewer資源=184,
        評価場=[e["session"] for e in entries], 設定=C.read_json(STUDY / "条件.json"), 検査=matched, 場別=summaries,
        採用=[p for p in POLICIES if all(result["候補"][p][h]["同時適格"] for h in PERIODS[:2])],
        詳細={p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")})
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新運用": 92, "保存参考": 92, "検査": matched}, ensure_ascii=False), flush=True)


def self_test() -> dict:
    """空の集計でnull・支持・形成の期別初期化を確認する。

    引数: なし。市場や保存ラベルを読まない。
    返り値: dictは人工成功と照合数。
    """
    empty = {p: [] for p in ALL_POLICIES}
    value = summarize(deepcopy(empty), deepcopy(empty), deepcopy(empty), {})
    checks = 0
    for policy in ALL_POLICIES:
        for period in PERIODS:
            row = value["候補"][policy][period]
            assert row["入口"]["率"] is None and row["入口"]["間引き率"] is None
            assert row["同時適格"] is False and row["運用"]["活動適格"] is False
            checks += 2
    for p in POLICIES:
        for h in PERIODS:
            assert set(value["形成別"][p][h]) == {"T", "R"} and len(value["場所別"][p][h]) == 6
            checks += 1
    return {"成功": True, "不一致数": 0, "テスト件数": 2, "照合項目数": checks, "本物入力読取": False}


# ----------------------------------------
# CLIでは入力準備・固定・単一運用の一段階だけを選ぶ。

def main() -> None:
    """76の事前条件を保存するか、その不変を確認する。

    引数: CLIのprepare/check-prepared/preflight/freeze/run(bool)は排他的な段階。
    返り値: None。先着再計測やfitは起動しない。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--check-prepared", action="store_true")
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.preflight:
        preflight()
    elif args.freeze:
        freeze()
    elif args.run:
        run()
    else:
        check_prepared()
        print("76の事前入力は不変です", flush=True)


if __name__ == "__main__":
    main()
