"""内包足の偽突破確認による候補追加と、二つの既存注文方式を比較する。"""

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
STUDY = ROOT / "study/00074_内包足の偽突破確認と局面切替"
PARENT = ROOT / "work/内包足の偽突破と局面切替"
WORK = PARENT / "00074"
OLD = ROOT / "study/00073_直近の集中と方向効率を組み合わせる"
OLDWORK = ROOT / "work/直近進行の集中と効率/00073"
LEDGER = ROOT / "work/直近進行の集中と効率/73完了記録.json"
LEDGER_SHA = "8dee76e55114a68c18c40da3514a3c1b417f27d79969bf2ff91f14f9f00231ae"
IMMEDIATE = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"
CONDITIONAL = ROOT / "work/条件入口の教師/00069/条件独立測定.jsonl.gz"
POLICIES = ("I0", "H0", "H1")
ALL_POLICIES = ("Q0", *POLICIES)
PERIODS = ("学習", "条件選択", "後続検査")
PURE = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")


def load(path: Path, name: str):
    """旧固定補助又は当試行の純補助を固有名で読む。

    引数: path(Path)はファイル、name(str)は読込名。
    返り値: ModuleTypeは読込結果。main・市場・学習を起動しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(ROOT / "scripts/直近進行の集中と効率/検証.py", "内包74が参照する固定73主")
C, P = PREVIOUS.C, PREVIOUS.P
O49 = load(ROOT / "scripts/定時帯反応/運用.py", "内包74の固定即時49")
O68 = load(ROOT / "scripts/条件発動前の否定/運用.py", "内包74の固定条件68")
B68 = load(ROOT / "scripts/条件発動前の否定/先着.py", "内包74の固定先着集計68")
P68 = PREVIOUS.I.I69.P68
P55 = PREVIOUS.I.I69.P65.P55


def rows(path: Path):
    """保存JSONLを一行ずつ読み、大量の中間複製を作らない。

    引数: path(Path)はgzip形式。
    返り値: Iterator[dict]は保存行。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def verify_previous() -> dict:
    """73の完了台帳と固定対象を確認する。

    引数: なし。
    返り値: dictは成功台帳。不一致は例外。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("73完了台帳の変更")
    ledger = C.read_json(LEDGER)
    if ledger["試行"] != 73 or len(ledger["成果物SHA256"]) != 259:
        raise ValueError("73完了対象数の差")
    for relative, digest in ledger["成果物SHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("73完了物の変更:" + relative)
    return ledger


def source_inputs() -> tuple:
    """73の純Q0だけを再利用し、対象46場の元入力台帳を結ぶ。

    引数: なし。
    返り値: tupleは旧結果・46台帳行・Q0保存block。新特徴や損益を計算しない。
    """
    verify_previous()
    result = C.read_json(OLD / "結果.json")
    proof = C.read_json(OLD / "保存物確認.json")
    if not proof["全件一致"] or proof["不一致数"] or proof["結果SHA256"] != C.sha(OLD / "結果.json"):
        raise ValueError("73の成功結合差")
    if C.sha(C.MANIFEST) != C.MANIFEST_SHA:
        raise ValueError("旧66場台帳の変更")
    all_entries = C.read_json(C.MANIFEST)["entries"]
    if len(all_entries) != 66:
        raise ValueError("旧台帳は66場が必要")
    wanted = result["評価場"]
    entries = [entry for entry in all_entries if entry["session"] in set(wanted)]
    blocks = {block["session"]: block for block in rows(OLDWORK / "定時判断と運用.jsonl.gz") if block["policy"] == "Q0"}
    if [entry["session"] for entry in entries] != wanted or list(blocks) != wanted or len(blocks) != 46:
        raise ValueError("73Q0の46場の順序又は集合差")
    if sum(len(block["slots"]) for block in blocks.values()) != 1702:
        raise ValueError("73Q0の全予定1702枠の差")
    return result, entries, blocks


def condition_for(slot: dict) -> dict:
    """73で既に検証した現3分SOURCEから同じ68条件を作る。

    引数: slot(dict)は73Q0の準備済み純判断。
    返り値: dictはhigh/low/source/expires。方向に依存しない。
    """
    source = slot["feature"]["base"]["base"]["sources"]["current"]
    if source["end"] > slot["scheduled"] or (source["confirm"], source["confirm_line"]) > (slot["time"], slot["line"]):
        raise ValueError("68条件に未来SOURCE")
    return {"high": source["high"], "low": source["low"], "source": deepcopy(source), "expires": slot["scheduled"] + 900}


def measurement_banks(identities: set) -> dict:
    """旧55/69の対象方向測定を必要な先着・完結へ縮約する。

    引数: identities(set[str])は今回の全予定ID。
    返り値: dictは即時/条件→(slot_id,side)→barrier/closed。新測定はしない。
    """
    result = {}
    fixed = C.read_json(OLD / "固定.json")["ファイルSHA256"]
    for kind, path in (("即時", IMMEDIATE), ("条件", CONDITIONAL)):
        if C.sha(path) != fixed[path.relative_to(ROOT).as_posix()]:
            raise ValueError("独立測定の変更:" + kind)
        bank = {}
        for row in rows(path):
            if row["slot_id"] not in identities:
                continue
            key = row["slot_id"], row["side"]
            if key in bank:
                raise ValueError("独立測定の方向重複")
            binding = {name:row[name] for name in ("session","slot_id","scheduled","time","line","side")}
            pure = row if kind == "即時" else row["operation"]["conditions"][row["slot_id"]]["slot"]
            binding.update({name:pure[name] for name in ("ready","atr","D")})
            bank[key] = {"barrier": row["barrier"], "closed": row["operation"]["closed"] if row["operation"] is not None else None,
                "binding": binding}
        result[kind] = bank
    return result


def prepare() -> None:
    """事前計画を機械可読な条件と入力参照へ保存する。

    引数: なし。
    返り値: None。既存条件を上書きしない。
    """
    verify_previous()
    if any((STUDY / name).exists() for name in ("条件.json", "入力台帳.json")):
        raise FileExistsError("74条件は保存済み")
    rules = {"試行": 74, "全66場既使用": True, "政策": {
        "Q0": {"純候補": "73保存Q0", "注文": "条件", "保存参考": True},
        "I0": {"純候補": "73保存Q0", "注文": "即時", "保存参考": False},
        "H0": {"純候補": "適格内包偽突破優先・他Q0", "注文": "条件", "保存参考": False},
        "H1": {"純候補": "H0同値", "注文": "即時", "保存参考": False}},
        "内包": "I高値<A高値 AND I安値>A安値・全strict",
        "偽突破": "次Bの高安が共にIより下なら買候補、共に上なら売候補",
        "確認": "B後1..3足の最初の反対I端を越す終値。原典price-crossへの独自適応",
        "無効化": "C後最初の既知終値が買B安値以下/売B高値以上。復活なし",
        "使用窓": "C.endは予定-900よりstrict後、予定以下。公開keyは実判断以下。最新C→最新B",
        "FastK": "F02>=0 AND F03>0", "順行": "F01>0かつrawDI非零",
        "反転": "F01<0 AND F52=1 AND F48<0 AND F15>0かつrawDI非零",
        "未知": "旧readyを保持。未知を0補完しない。有効Hなしは保存Q0純判断",
        "価格尺度": "NK225指数pt。125逆行以上前の250順行以上",
        "定時": "Day09:15..15:15・Night17:30..05:30・900秒間隔、保有は非待ち",
        "利益保護": "O49共通・費用後現在益strict正で利益旗と最低名目同値床。D=clip(5pt切上ATR,5,125)、非緩和、pending中h/L/arm凍結",
        "費用": {"商品": "ラージBBOによるmicro代理1枚", "円毎pt": 10, "片道手数料円": 11, "主片道滑りpt": 5, "往復主費用円": 122, "同約定感応片道pt": [0, 5, 10]},
        "新学習": 0, "新モデル": 0, "新独立測定": 0, "新運用": 138, "保存参考": 46,
        "Viewer資源": 184, "表版": 5, "手法数": 55, "尺度数": 9,
        "採用": "主/非重複の支持付き70%・費用/品質・活動を別検査。新H由来へfallback支持を流用しない"}
    C.write_json(STUDY / "条件.json", rules)
    paths = (OLD / "結果.json", OLD / "保存物確認.json", OLDWORK / "定時判断と運用.jsonl.gz", IMMEDIATE, CONDITIONAL, C.MANIFEST, LEDGER)
    C.write_json(STUDY / "入力台帳.json", {"試行": 74, "全66場既使用": True,
        "参照SHA256": {path.relative_to(ROOT).as_posix(): C.sha(path) for path in paths},
        "参照独立測定": {"即時": "55保存4884方向行", "条件": "69保存4092準備方向行"},
        "対象": "73評価46場1702予定、初20学習専用を新評価へ加えない", "新市場取得": 0})
    print("74の条件と入力参照を保存しました", flush=True)


def preflight() -> None:
    """価格だけで新観測と純候補を作り、ラベル読取前に接続を確認する。

    引数: なし。
    返り値: None。既存の観測を上書きしない。
    """
    destination = WORK / "技法観測.jsonl.gz"
    if destination.exists() or (PARENT / "入力確認.json").exists():
        raise FileExistsError("74入力確認は実行済み")
    _, entries, blocks = source_inputs()
    feature = load(HERE / "入力.py", "内包74の事前入力")
    independent = load(HERE / "入力監査.py", "内包74の事前別算")
    counts, checked, ready = Counter(), 0, 0
    WORK.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination, "wt", encoding="utf-8") as stream:
        for entry in entries:
            for slot in blocks[entry["session"]]["slots"]:
                observation = feature.extract(slot, slot["feature"])
                if observation != independent.derive(slot, slot["feature"]):
                    raise ValueError("74の入力と独立算術の差:" + slot["slot_id"])
                selected = {policy: feature.choose(slot, observation, policy) for policy in POLICIES}
                for policy in POLICIES:
                    if selected[policy] != independent.choose(slot, observation, policy):
                        raise ValueError("74の直接選択と独立算術の差")
                if {k:v for k,v in selected["H0"].items() if k != "policy"} != {k:v for k,v in selected["H1"].items() if k != "policy"}:
                    raise ValueError("H0/H1の非policy差")
                if any(selected["I0"][key] != slot[key] for key in PURE):
                    raise ValueError("I0は保存Q0純候補を変更できない")
                ready += bool(observation["ready"])
                counts["新H採用"] += selected["H0"]["origin"] == "内包偽突破"
                checked += 1
                C.jsonline(stream, {"session": entry["session"], "slot_id": slot["slot_id"], "observation": observation})
    if checked != 1702:
        raise ValueError("74入力は全1702枠が必要")
    C.write_json(PARENT / "入力確認.json", {"試行":74,"成功":True,"全予定":checked,"準備済み":ready,
        "別算一致":checked,"新H採用":counts["新H採用"],"保存Q0正本の読取":True,"旧独立測定読取":False,
        "先着損益による新候補選択":False,"新先着回収計算":False,"新市場再生":False,
        "観測SHA256":C.sha(destination),"入力コードSHA256":C.sha(HERE/"入力.py"),"入力監査コードSHA256":C.sha(HERE/"入力監査.py")})
    print(json.dumps({"入力確認": True, "全予定": checked, "準備済み": ready, **dict(counts)}, ensure_ascii=False), flush=True)


def freeze() -> None:
    """入力と人工と全実装を新一枚運用の前に固定する。

    引数: なし。
    返り値: None。既存固定を上書きしない。
    """
    if (STUDY/"固定.json").exists():
        raise FileExistsError("74は固定済み")
    ledger = verify_previous()
    artificial = C.read_json(STUDY/"人工確認.json")
    if not artificial["成功"]:
        raise ValueError("74人工が未成功")
    for relative, digest in artificial["コードSHA256"].items():
        if C.sha(ROOT/relative) != digest:
            raise ValueError("74人工後の変更:"+relative)
    check = C.read_json(PARENT/"入力確認.json")
    if not check["成功"] or check["入力コードSHA256"] != C.sha(HERE/"入力.py") or check["入力監査コードSHA256"] != C.sha(HERE/"入力監査.py") or check["観測SHA256"] != C.sha(WORK/"技法観測.jsonl.gz"):
        raise ValueError("74入力確認の結合差")
    pins = dict(C.read_json(OLD/"固定.json")["ファイルSHA256"])
    pins.update(ledger["成果物SHA256"])
    paths = [*HERE.glob("*.py"),*HERE.glob("*.md"),*STUDY.glob("*.json"),STUDY/"検証計画.md",LEDGER,WORK/"技法観測.jsonl.gz"]
    paths += [path for path in PARENT.iterdir() if path.is_file()]
    paths += [path for path in (ROOT/"work/74設計").glob("*.md")]
    paths += [ROOT/"docs/議論/外部再調査/内包足の偽突破と価格帯への受容.md"]
    for path in paths:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    for relative, digest in pins.items():
        if C.sha(ROOT/relative) != digest:
            raise ValueError("74固定依存の差:"+relative)
    C.write_json(STUDY/"固定.json",{"試行":74,"新市場実行前":True,"全66場既使用":True,
        "固定日時":datetime.now(C.JST).isoformat(),"Python":platform.python_version(),"NumPy":C.np.__version__,"ファイルSHA256":pins})
    print("74を新一枚運用の前に固定しました",flush=True)


def verify_lock() -> None:
    """固定した全入力・コード・仕様を確認する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for relative,digest in C.read_json(STUDY/"固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT/relative) != digest:
            raise ValueError("74固定後の変更:"+relative)


def distribution(values: list) -> dict:
    """同じ元枠の取得差を固定した四統計へ要約する。

    引数: values(list[float])は符号付き価格差又は秒差。
    返り値: dictは平均・中央値・最小・最大。空集合は各None。
    """
    return {"平均":sum(values)/len(values) if values else None,"中央値":statistics.median(values) if values else None,
        "最小":min(values) if values else None,"最大":max(values) if values else None}


def summarize(operations: dict, labels: dict, slots: dict, observations: dict) -> dict:
    """四政策の参加・費用・保護・由来・取得差を保存値から集計する。

    引数: operations/labels/slots/observations(dict)は政策別と入力別の保存可能な値。
    返り値: dictは結果の集計層。新たな売買・学習・最良群選択をしない。
    """
    result = {"候補":{},"由来別":{},"利益保護":{},"比較":{},"技法被覆":{}}
    closes = {policy:[{**row,"session":op["session"]} for op in operations[policy] for row in op["closed"]] for policy in ALL_POLICIES}
    for policy in ALL_POLICIES:
        result["候補"][policy],result["由来別"][policy],result["利益保護"][policy] = {},{},{}
        slot_map = {slot["slot_id"]:slot for slot in slots[policy]}
        label_map = {row["slot_id"]:row for row in labels[policy]}
        for period in PERIODS:
            local_slots = [s for s in slots[policy] if C.period(s["session"])==period]
            local_labels = [r for r in labels[policy] if C.period(r["session"])==period]
            local_closed = [r for r in closes[policy] if C.period(r["session"])==period]
            entrance = B68.entry_stats(local_labels,period,C.period)
            operation = P68.operation_stats(operations[policy],period) if policy in ("Q0","H0") else C.operation_stats(operations[policy],period)
            if policy not in ("Q0","H0"):
                operation.update(条件登録数=0,条件未約定=0)
            result["候補"][policy][period] = {"入口":entrance,"運用":operation,"同時適格":entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
            by_origin = {}
            for origin in ("保存Q0","内包偽突破"):
                ss = [s for s in local_slots if s["side"] and s["origin"]==origin]
                ll = [r for r in local_labels if slot_map[r["slot_id"]]["origin"]==origin]
                cc = [r for r in local_closed if slot_map[r["slot_id"]]["origin"]==origin]
                cautions = [op["session"] for op in operations[policy] if C.period(op["session"])==period and not op["quality"]["損益確定可能"] and any(slot_map[r["slot_id"]]["origin"]==origin for r in op["closed"])]
                by_origin[origin] = {"純候補":len(ss),"入口":B68.entry_stats(ll,period,C.period),"実完結":len(cc),
                    "費用別観測円":{str(f):sum(r["pnl"+str(f)] for r in cc) for f in (0,5,10)},
                    "利益旗":sum(r["arm"] for r in cc),"旗後赤":sum(r["arm"] and r["pnl5"]<0 for r in cc),
                    "役割別完結":{role:sum(r["role"]==role for r in cc) for role in ("順行","反転")},"品質注意場":cautions,
                    "品質注意場の範囲":"同由来の完結がある場の全体品質注意。由来別の未解消を網羅しない。額は観測小計で、確定性は政策全体を参照"}
            result["由来別"][policy][period] = by_origin
            red = [r for r in local_closed if r["arm"] and r["pnl5"]<0]
            protection = {"利益旗":sum(r["arm"] for r in local_closed),"旗後赤":len(red),
                "同値":sum(r["exit_price"]==r["entry_price"] for r in red),
                "有利費用負け":sum(r["side"]*(r["exit_price"]-r["entry_price"])>0 for r in red),
                "不利":sum(r["side"]*(r["exit_price"]-r["entry_price"])<0 for r in red),
                "先着250前の実退出":sum(label_map[r["slot_id"]]["outcome"]=="250" and (r["exit_time"],r["exit_line"])<(label_map[r["slot_id"]]["end_time"],label_map[r["slot_id"]]["end_line"]) for r in local_closed)}
            if protection["旗後赤"] != sum(protection[k] for k in ("同値","有利費用負け","不利")):
                raise ValueError("利益旗後赤字の会計分類が復元しない")
            result["利益保護"][policy][period] = protection
    # ----------------------------------------
    # 比較は同じ元枠の符号付き取得差と、一枚運用の追加/除外を分ける。
    for left,right in (("Q0","I0"),("Q0","H0"),("I0","H1"),("H0","H1")):
        comparison = {}
        for period in PERIODS:
            a = {s["slot_id"]:s for s in slots[left] if C.period(s["session"])==period}
            b = {s["slot_id"]:s for s in slots[right] if C.period(s["session"])==period}
            if set(a)!=set(b):
                raise ValueError("比較する純候補の全予定集合差")
            pure = {"同方向":0,"左のみ":0,"右のみ":0,"反対切替":0,"双方待機":0}
            for key in a:
                x,y=a[key]["side"],b[key]["side"]
                name = "双方待機" if not x and not y else "左のみ" if x and not y else "右のみ" if y and not x else "同方向" if x==y else "反対切替"
                pure[name]+=1
            ca={(r["slot_id"],r["side"]):r for r in closes[left] if C.period(r["session"])==period}
            cb={(r["slot_id"],r["side"]):r for r in closes[right] if C.period(r["session"])==period}
            common,onlya,onlyb=sorted(set(ca)&set(cb)),sorted(set(ca)-set(cb)),sorted(set(cb)-set(ca))
            exact=[key for key in common if all(ca[key][k]==cb[key][k] for k in ("entry_time","entry_line","entry_price"))]
            comparison[period]={"純":pure,"実":{"左完結":len(ca),"右完結":len(cb),"共通元枠同方向":len(common),"左のみ":len(onlya),"右のみ":len(onlyb),
                "共通元枠差額5":sum(cb[k]["pnl5"]-ca[k]["pnl5"] for k in common),"左のみ額5":sum(ca[k]["pnl5"] for k in onlya),"右のみ額5":sum(cb[k]["pnl5"] for k in onlyb),
                "厳密同新規":len(exact),"厳密同新規出口差5":sum(cb[k]["pnl5"]-ca[k]["pnl5"] for k in exact)},
                "取得差":{"件数":len(common),"実方向価格差pt":distribution([ca[k]["side"]*(cb[k]["entry_price"]-ca[k]["entry_price"]) for k in common]),
                    "時間差秒":distribution([cb[k]["entry_time"]-ca[k]["entry_time"] for k in common])}}
        result["比較"][left+"対"+right]=comparison
    for period in PERIODS:
        ss=[s for s in slots["H0"] if C.period(s["session"])==period]
        source={s["slot_id"]:s for s in slots["Q0"]}
        oo=[observations[s["slot_id"]] for s in ss]
        candidates=[row for o in oo for row in o["candidates"]]
        adopted=[s for s in ss if s["origin"]=="内包偽突破"]
        result["技法被覆"][period]={"定時枠":len(ss),"準備済み":sum(o["ready"] for o in oo),"形観測":len(candidates),"形unique":len({row["id"] for row in candidates}),
            "状態別":dict(Counter(row["status"] for row in candidates)),"適格方向":sum(bool(o["side"]) for o in oo),
            "順行適格":sum(o["side"]!=0 and o["role"]=="順行" for o in oo),"反転適格":sum(o["side"]!=0 and o["role"]=="反転" for o in oo),
            "新H追加":sum(source[s["slot_id"]]["side"]==0 for s in adopted),"新H同方向":sum(source[s["slot_id"]]["side"]==s["side"] for s in adopted),
            "新H反対切替":sum(source[s["slot_id"]]["side"]==-s["side"] for s in adopted)}
    return result


def run() -> None:
    """固定後に新三政策を一度だけ運用し、四政策の比較を保存する。

    引数: なし。
    返り値: None。開始済みは拒否し、既存handleの終端確認を要求する。
    """
    if (WORK/"実行開始.json").exists() or (STUDY/"結果.json").exists():
        raise FileExistsError("74開始済み。既存handleを確認すること")
    verify_lock()
    old_result,entries,blocks=source_inputs()
    C.write_json(WORK/"実行開始.json",{"開始":datetime.now(C.JST).isoformat(),"固定SHA256":C.sha(STUDY/"固定.json")})
    feature=load(HERE/"入力.py","内包74本物の純入力")
    observations={row["slot_id"]:row["observation"] for row in rows(WORK/"技法観測.jsonl.gz")}
    identities={s["slot_id"] for block in blocks.values() for s in block["slots"]}
    if set(observations)!=identities:
        raise ValueError("保存観測の全予定集合差")
    banks=measurement_banks(identities)
    operations={p:[] for p in ALL_POLICIES}
    labels={p:[] for p in ALL_POLICIES}
    slots={p:[] for p in ALL_POLICIES}
    resources=[deepcopy(r) for r in C.read_json(OLD/"一覧.resources.json")["resources"] if r["method_id"]=="Q0"]
    matches={"実独立新規一致":0,"実独立完結一致":0}
    summaries=[]
    with gzip.open(WORK/"定時判断と運用.jsonl.gz","wt",encoding="utf-8") as stream:
        for entry in entries:
            session=entry["session"]
            block=blocks[session]
            source_slots={s["slot_id"]:s for s in block["slots"]}
            qslots=[{**{k:s[k] for k in PURE},"session":session,"policy":"Q0","origin":"保存Q0","pattern_id":None} for s in block["slots"]]
            slots["Q0"].extend(qslots)
            operations["Q0"].append(block["operation"])
            for s in qslots:
                if s["side"]:
                    value=deepcopy(banks["条件"][s["slot_id"],s["side"]]["barrier"])
                    value.update(policy="Q0",role=s["role"],origin=s["origin"],pattern_id=None)
                    labels["Q0"].append(value)
            events,quality=C.events_for(entry)
            for policy in POLICIES:
                selected=[feature.choose(s,observations[s["slot_id"]],policy) for s in block["slots"]]
                slots[policy].extend(selected)
                kind="条件" if policy=="H0" else "即時"
                frozen={s["slot_id"]:condition_for(source_slots[s["slot_id"]]) for s in selected if s["side"]} if kind=="条件" else {}
                for s in selected:
                    if not s["side"]:
                        continue
                    measured=banks[kind][s["slot_id"],s["side"]]
                    prior=measured["barrier"]
                    if any(measured["binding"][key]!=s[key] for key in measured["binding"]):
                        raise ValueError("独立測定と元判断/ATR/D/readyの差")
                    if prior is None:
                        raise ValueError("採用した準備方向の独立先着なし")
                    for key in ("session","slot_id","scheduled","time","line","side"):
                        actual=prior.get("origin_slot",prior).get(key,prior.get(key))
                        if actual!=s[key]:
                            raise ValueError("独立先着と元判断の差:"+key)
                    if kind=="条件" and prior["condition"]!=frozen[s["slot_id"]]:
                        raise ValueError("保存独立条件と新条件の差")
                    value=deepcopy(prior)
                    value.update(policy=policy,role=s["role"],origin=s["origin"],pattern_id=s["pattern_id"])
                    labels[policy].append(value)
                pure=[{k:s[k] for k in PURE} for s in selected]
                operation=O68.replay(events,pure,frozen,session,policy) if kind=="条件" else O49.replay(events,pure,session,policy)
                for order in operation["orders"]:
                    if order["kind"]=="entry" and order["status"]=="filled":
                        prior=banks[kind][order["slot"]["slot_id"],order["slot"]["side"]]["barrier"]
                        if not prior["filled"] or any(order["fill_"+k]!=prior["entry_"+k] for k in ("time","line","price")):
                            raise ValueError("一枚新規と独立先着の差")
                        matches["実独立新規一致"]+=1
                for closed in operation["closed"]:
                    prior=banks[kind][closed["slot_id"],closed["side"]]["closed"]
                    if len(prior)!=1 or not P55.equivalent_close(closed,prior[0]):
                        raise ValueError("一枚完結と独立回収の差")
                    matches["実独立完結一致"]+=1
                operations[policy].append(operation)
                C.jsonline(stream,{"session":session,"phase":block["phase"],"policy":policy,"slots":selected,"conditions":frozen,"input_quality":quality,"operation":operation})
                path=STUDY/"viewer"/(policy+"_"+session+".trades.jsonl")
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open("w",encoding="utf-8") as trades:
                    for trade in operation["trades"]:
                        C.jsonline(trades,trade)
                resources.append({"id":session+"_"+policy,"title":session+" "+policy+" 内包足の偽突破と局面切替","symbol":"NK225","session":session,"product":"NK225micro","method_id":policy,
                    "point_value":10,"pnl_format":"trades","pnl_basis":"net","pnl_path":path.relative_to(ROOT).as_posix(),"market_path":entry["source_path"]})
                summaries.append({"場":session,"候補":policy,"期間":C.period(session),"入力品質":quality,"運用品質":operation["quality"],"運用集計":operation["metrics"]})
            print(session+" 内包偽突破の新三政策運用完了",flush=True)
    with gzip.open(WORK/"入口先着.jsonl.gz","wt",encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream,row)
    result=summarize(operations,labels,slots,observations)
    if result["候補"]["Q0"]!=old_result["候補"]["Q0"]:
        raise ValueError("保存参考Q0の再集計差")
    if len(summaries)!=138 or len(resources)!=184:
        raise ValueError("予定した138新運用/184資源の差")
    result.update(試行=74,実行日時=datetime.now(C.JST).isoformat(),全66場既使用=True,固定SHA256=C.sha(STUDY/"固定.json"),
        新fit=0,新分類器fit=0,新モデル=0,新独立測定=0,新運用数=138,保存参照運用数=46,Viewer資源=184,
        評価場=[entry["session"] for entry in entries],設定=C.read_json(STUDY/"条件.json"),検査=matches,場別=summaries,
        採用=[policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])],
        詳細={path.name:C.sha(path) for path in WORK.glob("*.jsonl.gz")})
    C.write_json(STUDY/"結果.json",result)
    C.write_json(STUDY/"一覧.resources.json",{"schema_version":1,"resources":resources})
    C.write_json(WORK/"実行完了.json",{"完了":datetime.now(C.JST).isoformat(),"結果SHA256":C.sha(STUDY/"結果.json")})
    print(json.dumps({"採用":result["採用"],"新運用":138,"保存参考":46,"検査":matches},ensure_ascii=False),flush=True)


def main() -> None:
    """事前準備・価格入力・固定・単一本物運用を排他的に公開する。

    引数: CLIのprepare/preflight/freeze/run(bool)は作業段階。
    返り値: None。指定がなければ説明だけ表示する。
    """
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare","preflight","freeze","run"):
        group.add_argument("--"+name,action="store_true")
    args=parser.parse_args()
    {"prepare":prepare,"preflight":preflight,"freeze":freeze,"run":run}[next(k for k,v in vars(args).items() if v)]()


if __name__=="__main__":
    main()
