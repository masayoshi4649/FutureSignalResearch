"""固定済みの事前観測帯と現在の反応を、三政策の場内運用で比較する。"""

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
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00075_事前帯の外保持と内回帰を判別"
PARENT = ROOT / "work/事前帯と現在の反応"
WORK = PARENT / "00075"
OLD = ROOT / "study/00074_内包足の偽突破確認と局面切替"
OLDWORK = ROOT / "work/内包足の偽突破と局面切替/00074"
LEDGER = OLDWORK.parent / "74完了記録.json"
LEDGER_SHA = "7f7c42a9ca883e426bda8a92ff473e99ab9ba19d3bd42dba4c6fd2d199e9c686"
POLICIES = ("O0", "P0", "P1")
ALL_POLICIES = ("Q0", *POLICIES)
PERIODS = ("学習", "条件選択", "後続検査")
PURE = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")


def load(path: Path, name: str):
    """固定補助又は新しい純補助を固有名で読む。

    引数: path(Path)はファイル、name(str)は読込名。
    返り値: ModuleTypeは読込結果。市場処理を起動しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(ROOT / "scripts/内包足の偽突破と局面切替/検証.py", "事前帯75の固定74主")
C, P, O49, B68, P68, P55 = PREVIOUS.C, PREVIOUS.P, PREVIOUS.O49, PREVIOUS.B68, PREVIOUS.P68, PREVIOUS.P55


def rows(path: Path):
    """保存JSONLを展開ファイルを作らず一行ずつ読む。

    引数: path(Path)はgzip形式。
    返り値: Iterator[dict]は保存行。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def verify_previous() -> dict:
    """74完了台帳182対象の不変を確認する。

    引数: なし。
    返り値: dictは成功台帳。不一致は停止する。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("74完了台帳の変更")
    ledger = C.read_json(LEDGER)
    if ledger["試行"] != 74 or len(ledger["成果物SHA256"]) != 182:
        raise ValueError("74完了対象数の差")
    for relative, digest in ledger["成果物SHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("74完了物の変更:" + relative)
    return ledger


def source_inputs() -> tuple:
    """旧73Q0の全予定判断と固定66場台帳を参照する。

    引数: なし。
    返り値: tupleは旧結果、評価46場台帳、Q0保存block。
    """
    verify_previous()
    old, entries, blocks = PREVIOUS.source_inputs()
    return old, entries, blocks


# ----------------------------------------
# 事前条件と入力指紋を保存する。

def prepare() -> None:
    """価格本文を読む前に比較条件と全入力の指紋を保存する。

    引数: なし。
    返り値: None。保存済みの条件は上書きしない。
    """
    verify_previous()
    if any((STUDY / name).exists() for name in ("条件.json", "入力台帳.json")):
        raise FileExistsError("75条件は保存済み")
    if C.sha(C.MANIFEST) != C.MANIFEST_SHA:
        raise ValueError("66場台帳の指紋差")
    entries = C.read_json(C.MANIFEST)["entries"]
    cache_pins = {}
    for entry in entries:
        path = ROOT / "work/複合検証" / entry["cache_path"]
        if C.sha(path) != entry["sha256_cache"]:
            raise ValueError("参照cacheの指紋差")
        cache_pins[path.relative_to(ROOT).as_posix()] = entry["sha256_cache"]
    rules = {"試行": 75, "全66場既使用": True,
        "政策": {"Q0": {"保存参考": True, "注文": "68条件", "純候補": "73保存Q0"},
            "O0": {"保存参考": False, "注文": "49即時", "帯": "当場最初30分正常Last観測帯", "位置条件": False},
            "P0": {"保存参考": False, "注文": "49即時", "帯": "直前収録異種セッション正常Last全連続区間帯", "位置条件": False},
            "P1": {"保存参考": False, "注文": "49即時", "帯": "P0同値", "位置条件": True}},
        "帯": {"価格人口": "有限非後退価格時計・場内・元valid正常正bid<ask・正有限Last",
            "区間": "Day[08:45,15:40),Night[17:00,翌05:55)、ORは開始後1800秒半開",
            "被覆": "正常2件以上・head/tail各300秒以下・正常観測間最大gap300秒以下",
            "公開": "ORは終端に最初到達する有限非後退原行、前帯は終了境界timer・架空lineなし",
            "平坦": "H=Lは既知対象外WAIT。欠測へしない",
            "前帯": "台帳開始順で直前収録の異種場・同実限月・前end<当start。不良の古いgood代用なし",
            "留保": "公式全約定高安・実受信時計・直前公式市場セッションとは認定しない"},
        "反応": {"buffer_pt": 5, "T": "外側終値>=5の完全隣接2本、以後>=5の間active",
            "R": "同じ外試行の最後外足後1..3足で最初の内側<=-5をf、f後1..3別足で内側維持かつf反対端strict終値突破をk",
            "失効": "f後内側逸脱/期限超過又はk後内側逸脱/前提線否定で消費、同外試行復活なし",
            "履歴": "当場全確定3分SOURCE prefix、ORは形成終端以降開始足。未来排除後の既知欠足等は状態reset",
            "継続": "有効形は次定時にも観測、形成ID/確認経過/反復を記録"},
        "複合": {"全候補": "F02>=0 AND F03>0 AND F07>0 AND F01!=0。LastとE*が実方向前提線strict外",
            "T": "F01>0 AND F51=F52=1 AND F47>=0.20 AND F48>=0、順行",
            "R同向": "F01>0、順行", "R逆向": "F01<0 AND F52=1 AND F48<0 AND F15>0、反転",
            "単位": "F47=ADX/100、F48=deltaADX/100、F15はCLV[-1,1]。保存float64を直接比較",
            "P1": "0<s*(E*-line)<=D、Rのみs*(算術中央-E*)>=250、Tの中央余地は対象外",
            "選択": "位置条件を含む適格集合の最新k、同keyはT優先。FastK進行鏡像により反対同時適格不可、矛盾は停止",
            "fallback": False, "量": "未使用・未検証。旧b/rの量を現在/新帯へ流用しない"},
        "定時": "Day09:15..15:15,Night17:30..05:30・900秒、保有非待ち・待ち率全枠50%以下",
        "利益保護": "O49連続追尾、正常返済BBO費用後現在益strict正で起動・最低名目新規床、損失非緩和、pending中h/L/arm凍結",
        "費用": {"商品": "ラージBBOによるmicro代理1枚", "円毎pt": 10, "片道手数料円": 11, "主片道滑りpt": 5, "往復主費用円": 122, "同約定感応片道pt": [0, 5, 10]},
        "新fit": 0, "新モデル": 0, "新独立測定": 0, "新運用": 138, "保存参考": 46, "Viewer資源": 184,
        "表版": 5, "手法数": 55, "尺度数": 9,
        "保存参考セル": [{"method": method, "scale": scale} for method, scale in sorted({
            (r["method"], r["scale"]) for r in C.read_json(PREVIOUS.OLD / "条件.json")["特徴"]})],
        "採用": "主/非重複支持付き70%・費用/品質・全枠活動の同時適格。全66場既使用で未使用期確認は別"}
    paths = (OLD / "結果.json", OLD / "保存物確認.json", PREVIOUS.OLDWORK / "定時判断と運用.jsonl.gz",
        PREVIOUS.IMMEDIATE, PREVIOUS.CONDITIONAL, C.MANIFEST, C.FRAMES, LEDGER, STUDY / "検証計画.md")
    C.write_json(STUDY / "条件.json", rules)
    C.write_json(STUDY / "入力台帳.json", {"試行": 75, "全66場既使用": True,
        "価格集約前": True, "参照SHA256": {p.relative_to(ROOT).as_posix(): C.sha(p) for p in paths},
        "cacheSHA256": cache_pins, "場": [e["session"] for e in entries],
        "新市場取得": 0, "11月5日Day読取": 0, "FAR新市場取得": 0})
    print("75の条件と66場入力指紋を価格集約前に保存しました", flush=True)


def check_prepared() -> None:
    """価格前に保存した計画・入力指紋を確認する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    value = C.read_json(STUDY / "入力台帳.json")
    for group in ("参照SHA256", "cacheSHA256"):
        for relative, digest in value[group].items():
            if C.sha(ROOT / relative) != digest:
                raise ValueError("75準備後の変更:" + relative)


# ----------------------------------------
# 損益を候補へ渡さず、当時の気配と参照帯だけを接続する。

def quote_bank(identities: set) -> dict:
    """旧55から当時気配だけを取り出し、両方向の出典同値を確認する。

    引数: identities(set[str])は対象全予定枠。
    返り値: dict[str,dict]は枠別の気配。教師・実回収は返さない。
    """
    result, seen = {}, set()
    for row in rows(PREVIOUS.IMMEDIATE):
        key = row["slot_id"]
        if key not in identities:
            continue
        side_key = key, row["side"]
        if side_key in seen:
            raise ValueError("旧55判断気配の方向重複")
        seen.add(side_key)
        quote = row["decision_bbo"]
        if key in result and result[key] != quote:
            raise ValueError("旧55の両方向判断気配差")
        result[key] = deepcopy(quote)
    if set(result) != identities or len(seen) != len(identities) * 2:
        raise ValueError("旧55判断気配の全予定方向集合差")
    return result


def reference_for(policy: str, session: str, bands: dict) -> dict:
    """当場へ渡す帯を一つに限定し、現在全区間の未来高安を隔離する。

    引数: policy/session(str)は政策と当場、bands(dict)は集約銀行。
    返り値: dictは当場OR又は選定前帯。元銀行を変更しない。
    """
    if policy == "O0":
        result = deepcopy(bands["opening"][session])
        result.update(id="OR30:" + session, session=session, current_session=session, reference_type="OR30", prior_gap_seconds=None, reference_available=True)
    elif policy in ("P0", "P1"):
        prior = bands["previous"][session]
        if not prior["ready"]:
            return {"ready": False, "reason": prior["reason"], "id": "FULL:なし:" + session,
                "reference_available": False, "published": False,
                "current_session": session, "session": None, "reference_type": "FULL", "prior_gap_seconds": None,
                "begin": None, "end": None, "publication": "timer", "publication_key": None,
                "open": None, "high": None, "low": None, "close": None, "sources": None, "coverage": None}
        source = prior["prior_session"]
        result = deepcopy(bands["full"][source])
        result.update(id="FULL:" + source, session=source, current_session=session, reference_type="FULL", prior_gap_seconds=prior["gap_seconds"], reference_available=True)
    else:
        raise ValueError("新帯政策以外を要求")
    return result


def preflight() -> None:
    """正常価格帯と可視prefixを一度集約し、別算法と一致させる。

    引数: なし。
    返り値: None。新独立測定や場内運用は起動しない。
    """
    destination = WORK / "技法観測.jsonl.gz"
    if destination.exists() or (PARENT / "入力確認.json").exists() or (WORK / "参照帯.json").exists():
        raise FileExistsError("75価格入力は開始済み。既存出力を確認すること")
    check_prepared()
    _, entries, blocks = source_inputs()
    _, sessions = C.inputs()
    band_module = load(HERE / "参照帯.py", "事前帯75の集約")
    feature = load(HERE / "入力.py", "事前帯75の純入力")
    independent = load(HERE / "入力監査.py", "事前帯75の事前別算")
    all_entries = C.read_json(C.MANIFEST)["entries"]
    enriched = [{**e, "begin": C.bounds(e["session"])[0], "end": C.bounds(e["session"])[2]} for e in all_entries]
    bands = {"full": {}, "opening": {}, "previous": band_module.choose_previous(enriched)}
    counts = Counter()
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in enriched:
        session = entry["session"]
        events, quality = C.events_for(entry)
        for name, end, publication in (("full", entry["end"], "timer"), ("opening", entry["begin"] + 1800, "row")):
            band = band_module.aggregate(events, entry["begin"], end, publication=publication)
            expected = independent.aggregate(events, entry["begin"], end, publication=publication)
            if band != expected:
                raise ValueError("75帯集約の独立算術差:" + name + session)
            bands[name][session] = band
            counts[name + "準備"] += bool(band["ready"])
            counts[name + "平坦"] += bool(band["coverage"] and band["coverage"]["flat"])
        counts["帯照合"] += 2
        print(session + " 事前帯の集約と別算照合完了", flush=True)
    if bands["previous"] != independent.choose_previous(enriched):
        raise ValueError("75前収録の選定差")
    C.write_json(WORK / "参照帯.json", bands)
    histories = {s["session"]: [{"session": s["session"], **row} for row in s["frames3"]] for s in sessions}
    identities = {s["slot_id"] for block in blocks.values() for s in block["slots"]}
    quotes = quote_bank(identities)
    with gzip.open(destination, "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            references = {p: reference_for(p, session, bands) for p in POLICIES}
            for slot in blocks[session]["slots"]:
                observations = {}
                for policy in POLICIES:
                    observation = feature.extract(slot, histories[session], references[policy], quotes[slot["slot_id"]], policy)
                    expected = independent.derive(slot, histories[session], references[policy], quotes[slot["slot_id"]], policy)
                    if observation != expected:
                        raise ValueError("75純入力の独立算術差:" + policy + slot["slot_id"])
                    pure = feature.choose(slot, observation, policy)
                    if pure != independent.choose(slot, observation, policy):
                        raise ValueError("75純候補射影の独立差")
                    observations[policy] = observation
                    counts[policy + "準備"] += bool(observation["ready"])
                    counts[policy + "方向"] += bool(pure["side"])
                    counts["観測照合"] += 1
                a, b = (feature.choose(slot, observations[p], p) for p in ("P0", "P1"))
                if b["side"] and b["side"] != a["side"]:
                    raise ValueError("P1はP0と同方向又はWAITのはず")
                C.jsonline(stream, {"session": session, "slot_id": slot["slot_id"], "observations": observations})
    if counts["観測照合"] != 5106 or len(identities) != 1702:
        raise ValueError("75全枠×三政策の入力数差")
    C.write_json(PARENT / "入力確認.json", {"試行": 75, "成功": True, "全予定": 1702, **dict(counts),
        "旧独立測定から採否へ渡した情報": "decision_bboのみ、両方向同値検査",
        "新運用": 0, "新独立測定": 0, "新市場取得": 0,
        "帯SHA256": C.sha(WORK / "参照帯.json"), "観測SHA256": C.sha(destination),
        "コードSHA256": {p.relative_to(ROOT).as_posix(): C.sha(p) for p in (HERE / "参照帯.py", HERE / "入力.py", HERE / "入力監査.py")}})
    print(json.dumps({"入力確認": True, **dict(counts)}, ensure_ascii=False), flush=True)


# ----------------------------------------
# 人工・価格入力・実装を運用前に固定する。

def freeze() -> None:
    """人工・帯・観測・全実装を新場内運用の前に固定する。

    引数: なし。
    返り値: None。固定済みは上書きしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("75は固定済み")
    ledger = verify_previous()
    check_prepared()
    for name in ("人工確認.json",):
        proof = C.read_json(STUDY / name)
        if not proof["成功"]:
            raise ValueError("75人工が未成功")
        for relative, digest in proof["コードSHA256"].items():
            if C.sha(ROOT / relative) != digest:
                raise ValueError("75人工後のコード変更")
    check = C.read_json(PARENT / "入力確認.json")
    if not check["成功"] or check["観測SHA256"] != C.sha(WORK / "技法観測.jsonl.gz") or check["帯SHA256"] != C.sha(WORK / "参照帯.json"):
        raise ValueError("75入力確認の結合差")
    for relative, digest in check["コードSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("75入力確認後のコード変更")
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(ledger["成果物SHA256"])
    paths = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md", LEDGER,
        WORK / "参照帯.json", WORK / "技法観測.jsonl.gz", PARENT / "入力確認.json"]
    paths += list((ROOT / "work/75設計").glob("*.md")) + list((ROOT / "work/外部調査_75").glob("*.md"))
    paths += [ROOT / "docs/議論/外部再調査/事前帯の外保持と内回帰を判別する.md"]
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    for relative, digest in pins.items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("75固定依存の差:" + relative)
    C.write_json(STUDY / "固定.json", {"試行": 75, "新運用前": True, "全66場既使用": True,
        "固定日時": datetime.now(C.JST).isoformat(), "Python": platform.python_version(), "NumPy": C.np.__version__, "ファイルSHA256": pins})
    print("75を新一枚運用の前に固定しました", flush=True)


def verify_lock() -> None:
    """運用前の全固定指紋を照合する。

    引数: なし。
    返り値: None。不一致は停止する。
    """
    for relative, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("75固定後の変更:" + relative)


# ----------------------------------------
# 保存値の集計と、一度だけの場内運用を扱う。

def summarize(operations: dict, labels: dict, slots: dict, observations: dict) -> dict:
    """保存可能な運用と入口を集計し、帯・形・位置除外を分離する。

    引数: operations/labels/slots/observations(dict)は政策別の記録。
    返り値: dictは集計結果。新しい売買や最良群選択は行わない。
    """
    result = {"候補": {}, "利益保護": {}, "技法被覆": {}, "形成別": {}, "比較": {}}
    closes = {p: [{**r, "session": op["session"]} for op in operations[p] for r in op["closed"]] for p in ALL_POLICIES}
    for policy in ALL_POLICIES:
        for group in ("候補", "利益保護", "技法被覆", "形成別"):
            result[group][policy] = {}
        for period in PERIODS:
            ss = [s for s in slots[policy] if C.period(s["session"]) == period]
            ll = [r for r in labels[policy] if C.period(r["session"]) == period]
            cc = [r for r in closes[policy] if C.period(r["session"]) == period]
            stat = P68.operation_stats(operations[policy], period) if policy == "Q0" else C.operation_stats(operations[policy], period)
            if policy != "Q0":
                stat.update(条件登録数=0, 条件未約定=0)
            entrance = B68.entry_stats(ll, period, C.period)
            result["候補"][policy][period] = {"入口": entrance, "運用": stat,
                "同時適格": entrance["70目標"] and stat["活動適格"] and stat["費用適格"]}
            lm = {r["slot_id"]: r for r in ll}
            red = [r for r in cc if r["arm"] and r["pnl5"] < 0]
            result["利益保護"][policy][period] = {"利益旗": sum(r["arm"] for r in cc), "旗後赤": len(red),
                "同値": sum(r["exit_price"] == r["entry_price"] for r in red),
                "有利費用負け": sum(r["side"] * (r["exit_price"] - r["entry_price"]) > 0 for r in red),
                "不利": sum(r["side"] * (r["exit_price"] - r["entry_price"]) < 0 for r in red),
                "先着250前の実退出": sum(lm[r["slot_id"]]["outcome"] == "250" and (r["exit_time"], r["exit_line"]) < (lm[r["slot_id"]]["end_time"], lm[r["slot_id"]]["end_line"]) for r in cc)}
            if policy == "Q0":
                continue
            result["形成別"][policy][period] = {}
            oo = [observations[s["slot_id"]][policy] for s in ss]
            patterns = [r for o in oo for r in o["formations"]]
            adopted = [s for s in ss if s["side"]]
            sm = {s["slot_id"]: s for s in ss}
            result["技法被覆"][policy][period] = {"定時枠": len(ss), "準備済み": sum(o["ready"] for o in oo),
                "理由別": dict(Counter(o["reason"] for o in oo)), "形観測": len(patterns), "形unique": len({r["id"] for r in patterns}),
                "状態別": dict(Counter(r["status"] for r in patterns)),
                "現在active観測": sum(len(o["candidates"]) for o in oo), "適格方向": len(adopted),
                "順行": sum(s["role"] == "順行" for s in adopted), "反転": sum(s["role"] == "反転" for s in adopted),
                "採用形unique": len({s["pattern_id"] for s in adopted}), "形成別採用": dict(Counter(s["formation"] for s in adopted)),
                "基本適格形成観測": sum(q["basic_qualified"] for o in oo for q in o["qualifications"].values()),
                "位置除外形成観測": sum(q["basic_qualified"] and not q["position_qualified"] for o in oo for q in o["qualifications"].values()),
                "基本不適格理由観測": dict(Counter(reason for o in oo for q in o["qualifications"].values() for reason in q["basic_reasons"])),
                "位置除外理由観測": dict(Counter(reason for o in oo for q in o["qualifications"].values() if q["basic_qualified"] for reason in q["position_reasons"])),
                "採用k経過秒": PREVIOUS.distribution([o["selected"]["k_age_seconds"] for o in oo if o["side"]]),
                "同形成最大反復枠": max(Counter(s["pattern_id"] for s in adopted).values(), default=0)}
            for kind in ("T", "R"):
                group_s = [s for s in adopted if s["formation"] == kind]
                group_l = [r for r in ll if sm[r["slot_id"]]["formation"] == kind]
                group_c = [r for r in cc if sm[r["slot_id"]]["formation"] == kind]
                result["形成別"][policy][period][kind] = {"純候補": len(group_s), "形unique": len({s["pattern_id"] for s in group_s}),
                    "入口": B68.entry_stats(group_l, period, C.period), "実完結": len(group_c),
                    "費用別観測円": {str(f): sum(r["pnl" + str(f)] for r in group_c) for f in (0, 5, 10)},
                    "役割別完結": {role: sum(r["role"] == role for r in group_c) for role in ("順行", "反転")}}
    # ----------------------------------------
    # 純方向の違いと、実建玉の占有による参加の違いを別に数える。
    for left, right in (("Q0", "O0"), ("O0", "P0"), ("P0", "P1")):
        result["比較"][left + "対" + right] = {}
        for period in PERIODS:
            a = {s["slot_id"]: s for s in slots[left] if C.period(s["session"]) == period}
            b = {s["slot_id"]: s for s in slots[right] if C.period(s["session"]) == period}
            pure = Counter()
            for key in a:
                x, y = a[key]["side"], b[key]["side"]
                pure["双方待機" if not x and not y else "左のみ" if x and not y else "右のみ" if y and not x else "同方向" if x == y else "反対切替"] += 1
            ca = {(r["slot_id"], r["side"]): r for r in closes[left] if C.period(r["session"]) == period}
            cb = {(r["slot_id"], r["side"]): r for r in closes[right] if C.period(r["session"]) == period}
            common, onlya, onlyb = sorted(set(ca) & set(cb)), sorted(set(ca) - set(cb)), sorted(set(cb) - set(ca))
            exact = [k for k in common if all(ca[k][n] == cb[k][n] for n in ("entry_time", "entry_line", "entry_price"))]
            result["比較"][left + "対" + right][period] = {"純": dict(pure),
                "準備共通": sum(a[k]["ready"] and b[k]["ready"] for k in a),
                "左準備のみ": sum(a[k]["ready"] and not b[k]["ready"] for k in a), "右準備のみ": sum(b[k]["ready"] and not a[k]["ready"] for k in a),
                "実": {"左完結": len(ca), "右完結": len(cb), "共通元枠同方向": len(common), "左のみ": len(onlya), "右のみ": len(onlyb),
                    "共通元枠差額5": sum(cb[k]["pnl5"] - ca[k]["pnl5"] for k in common),
                    "左のみ額5": sum(ca[k]["pnl5"] for k in onlya), "右のみ額5": sum(cb[k]["pnl5"] for k in onlyb),
                    "厳密同新規": len(exact), "厳密同新規出口差5": sum(cb[k]["pnl5"] - ca[k]["pnl5"] for k in exact)}}
    return result


def run() -> None:
    """固定済み三政策を各46場一度だけ運用する。

    引数: なし。
    返り値: None。開始済みは再起動しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("75開始済み。既存handleの終端を確認すること")
    verify_lock()
    old_result, entries, blocks = source_inputs()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    feature = load(HERE / "入力.py", "事前帯75本物の純入力")
    observations = {r["slot_id"]: r["observations"] for r in rows(WORK / "技法観測.jsonl.gz")}
    identities = {s["slot_id"] for block in blocks.values() for s in block["slots"]}
    if set(observations) != identities:
        raise ValueError("75保存観測の全予定集合差")
    banks = PREVIOUS.measurement_banks(identities)
    operations, labels, slots = ({p: [] for p in ALL_POLICIES} for _ in range(3))
    resources = [deepcopy(r) for r in C.read_json(PREVIOUS.OLD / "一覧.resources.json")["resources"] if r["method_id"] == "Q0"]
    matches = {"実独立新規一致": 0, "実独立完結一致": 0}
    summaries = []
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            block = blocks[session]
            qslots = [{**{k: s[k] for k in PURE}, "session": session, "policy": "Q0", "origin": "保存Q0", "pattern_id": None, "formation": None} for s in block["slots"]]
            slots["Q0"].extend(qslots)
            operations["Q0"].append(block["operation"])
            for s in qslots:
                if s["side"]:
                    value = deepcopy(banks["条件"][s["slot_id"], s["side"]]["barrier"])
                    value.update(policy="Q0", role=s["role"], origin="保存Q0", pattern_id=None, formation=None)
                    labels["Q0"].append(value)
            events, quality = C.events_for(entry)
            for policy in POLICIES:
                selected = [feature.choose(s, observations[s["slot_id"]][policy], policy) for s in block["slots"]]
                slots[policy].extend(selected)
                for s in selected:
                    if not s["side"]:
                        continue
                    measured = banks["即時"][s["slot_id"], s["side"]]
                    if any(measured["binding"][key] != s[key] for key in measured["binding"]):
                        raise ValueError("独立測定と元判断/ATR/D/readyの差")
                    prior = measured["barrier"]
                    if prior is None or any(prior[key] != s[key] for key in ("session", "slot_id", "scheduled", "time", "line", "side")):
                        raise ValueError("75即時先着の出典差")
                    value = deepcopy(prior)
                    value.update(policy=policy, role=s["role"], origin=s["origin"], pattern_id=s["pattern_id"], formation=s["formation"])
                    labels[policy].append(value)
                operation = O49.replay(events, [{k: s[k] for k in PURE} for s in selected], session, policy)
                for order in operation["orders"]:
                    if order["kind"] == "entry" and order["status"] == "filled":
                        prior = banks["即時"][order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                        if not prior["filled"] or any(order["fill_" + k] != prior["entry_" + k] for k in ("time", "line", "price")):
                            raise ValueError("75一枚新規と独立先着の差")
                        matches["実独立新規一致"] += 1
                for closed in operation["closed"]:
                    prior = banks["即時"][closed["slot_id"], closed["side"]]["closed"]
                    if len(prior) != 1 or not P55.equivalent_close(closed, prior[0]):
                        raise ValueError("75一枚完結と独立回収の差")
                    matches["実独立完結一致"] += 1
                operations[policy].append(operation)
                C.jsonline(stream, {"session": session, "phase": block["phase"], "policy": policy, "slots": selected, "input_quality": quality, "operation": operation})
                path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as trades:
                    for trade in operation["trades"]:
                        C.jsonline(trades, trade)
                resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 事前帯と現在の反応", "symbol": "NK225", "session": session,
                    "product": "NK225micro", "method_id": policy, "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            print(session + " 事前帯の新三政策運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    result = summarize(operations, labels, slots, observations)
    if result["候補"]["Q0"] != old_result["候補"]["Q0"]:
        raise ValueError("75保存Q0の再集計差")
    if len(summaries) != 138 or len(resources) != 184:
        raise ValueError("75新138運用/184資源の差")
    result.update(試行=75, 実行日時=datetime.now(C.JST).isoformat(), 全66場既使用=True, 固定SHA256=C.sha(STUDY / "固定.json"),
        新fit=0, 新分類器fit=0, 新モデル=0, 新独立測定=0, 新運用数=138, 保存参照運用数=46, Viewer資源=184,
        評価場=[e["session"] for e in entries], 設定=C.read_json(STUDY / "条件.json"), 検査=matches, 場別=summaries,
        採用=[p for p in POLICIES if all(result["候補"][p][period]["同時適格"] for period in PERIODS[:2])],
        詳細={path.name: C.sha(path) for path in WORK.glob("*.jsonl.gz")}, 帯SHA256=C.sha(WORK / "参照帯.json"))
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新運用": 138, "保存参考": 46, "検査": matches}, ensure_ascii=False), flush=True)


# ----------------------------------------
# CLIの段階を一つだけ選ぶ。

def main() -> None:
    """事前準備、価格入力、固定、単一運用を排他的に実行する。

    引数: CLIのprepare/preflight/freeze/run(bool)は作業段階。
    返り値: None。未指定なら説明だけを表示する。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "preflight", "freeze", "run"):
        group.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    {"prepare": prepare, "preflight": preflight, "freeze": freeze, "run": run}[next(k for k, v in vars(args).items() if v)]()


if __name__ == "__main__":
    main()
