"""00037の旧高安帰還/外側継続と、元P方向から実方向への変換を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00037_高安帰還と外側継続の判別"
WORK = ROOT / "work/構造判別/00037"
ENTRY_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
ENTRY_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("B0", "R1", "T1", "S1")
ROLES = {"B0": "反転", "R1": "反転", "T1": "順行", "S1": "切替"}
OPERATIONS = ("3分_B0_X0", "3分_B0_XF", "3分_R1_XF", "3分_T1_XF", "3分_S1_XF")


def helper(path: Path, name: str) -> Any:
    """固定独立の原足/数量・原BBO先着の共通補助をread再用する。

    引数: path(Path)は独立コード、name(str)は識別名。
    返り値: Anyはモジュール。37主をimportせず、36のVR計算も呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/量比反転/状態独立確認.py", "構造判別の固定36独立共通補助")
G, B, S, V, Audit = Y.G, Y.B, Y.S, Y.V, Y.Audit
SIGNAL_FIELDS, LABEL_FIELDS = Y.SIGNAL_FIELDS, Y.LABEL_FIELDS
canonical_sha, rename, decision_signal = Y.canonical_sha, Y.rename, Y.decision_signal
raw_projection, normal_columns, label_direct = Y.raw_projection, Y.normal_columns, Y.label_direct


def pure_signal(row: dict, policy: str, actual_side: int | None = None, role: str | None = None) -> dict:
    """元Pから実方向/役割を明示した純13列を作る。

    引数: row(dict)は元P又は旧純入口、policy(str)は四案、actual_side(int|None)/role(str|None)は実方向/役割。
    返り値: dictは当時情報だけの新しい辞書。元P側やlabelを混ぜない。
    """
    if policy not in POLICIES:
        raise ValueError("事前の四案だけです")
    side = row["side"] if actual_side is None else actual_side
    entry_role = ROLES[policy] if role is None else role
    if side not in (-1, 1) or entry_role not in ("反転", "順行"):
        raise ValueError("実方向とfillで固定する役割が必要です")
    origin = row["発動ID"] if "発動ID" in row else row["イベントID"][:-3]
    changed = {"イベントID", "入口ID", "役割", "side", "方向"}
    value = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS if key not in changed}
    value.update(イベントID=origin + "_" + policy, 入口ID="3分_" + policy,
        side=side, 方向="買い" if side == 1 else "売り", 役割=entry_role)
    return value


def decision_projection(rows: list[dict]) -> list[dict]:
    """MACD差の表現許容と厳密な符号/他字段を分離する。

    引数: rows(list[dict])は全構造判定。
    返り値: list[dict]はMACD有限/符号へ射影した判断指紋用辞書。
    """
    output = deepcopy(rows)
    for row in output:
        delta = row.pop("MACDヒスト変化")
        valid = B.finite(delta)
        row["MACD差判断"] = {"有限": valid, "符号": int(delta > 0) - int(delta < 0) if valid else None}
    return output


# ----------------------------------------
# 両端は元20足全体から別算。元PのM/kは保存し、実sideへ交換して再参照しない。


def select(block: dict) -> dict:
    """元20足のmin/maxとMACD差から四候補を同時計に分類する。

    引数: block(dict)は旧29のsignals/quality/framesを持つ非損益材料。
    返り値: dictは全原Pの判定と純四集合。同判断競合は候補ごとに全見送り。
    """
    frames = {row["index"]: row for row in block["frames"][3]}
    origins, decisions = {}, []
    for raw in block["quality"]["全Q発動記録"]:
        window = [frames[index] for index in raw["前20足番号"]]
        if len(window) != 20 or max(row["index"] for row in window) >= raw["index"]:
            raise ValueError("元Pより前の20本窓だけです")
        lower = min(row["low"] for row in window)
        upper = max(row["high"] for row in window)
        low_index = max(row["index"] for row in window if row["low"] == lower)
        high_index = max(row["index"] for row in window if row["high"] == upper)
        source_side, close, delta = raw["side"], raw["close"], raw["MACDヒスト変化"]
        level = lower if source_side == 1 else upper
        inside = lower < close < upper
        outside = close < lower if source_side == 1 else close > upper
        old = bool(raw["戦略判定"]["R0"]["採用"])
        common = bool(raw["共通M準備"] and raw["時間条件可"] and raw["確認遅延条件可"])
        reversal = old and inside
        trend = bool(common and outside and B.finite(delta) and (delta < 0 if source_side == 1 else delta > 0))
        kind = "旧範囲内" if inside else "境界等号" if close == lower or close == upper else "元方向外側" if outside else "反対端外側"
        verdicts = {"B0": {"採用": old, "実side": source_side, "役割": "反転", "同時競合": False},
            "R1": {"採用": reversal, "実side": source_side, "役割": "反転", "同時競合": False},
            "T1": {"採用": trend, "実side": -source_side, "役割": "順行", "同時競合": False},
            "S1": {"採用": reversal or trend, "実side": source_side if reversal else -source_side if trend else None,
                "役割": "反転" if reversal else "順行" if trend else None, "同時競合": False}}
        decisions.append({"場": raw["場"], "発動ID": raw["発動ID"], "index": raw["index"], "元価格side": source_side,
            "要求時計秒": raw["要求時計秒"], "要求原板行": raw["要求原板行"],
            "旧L": lower, "旧H": upper, "旧L足番号": low_index, "旧H足番号": high_index,
            "元境界K": level, "終値": close, "構造区分": kind, "MACDヒスト変化": delta,
            "共通M準備": raw["共通M準備"], "時間条件可": raw["時間条件可"], "確認遅延条件可": raw["確認遅延条件可"],
            "旧R0採用": old, "戦略判定": verdicts})
        origins[raw["発動ID"]] = raw
    counts = Counter((policy, row["要求時計秒"], row["要求原板行"]) for row in decisions for policy in POLICIES if row["戦略判定"][policy]["採用"])
    grouped = {"3分_" + policy: [] for policy in POLICIES}
    for row in decisions:
        for policy in POLICIES:
            verdict = row["戦略判定"][policy]
            if verdict["採用"] and counts[policy, row["要求時計秒"], row["要求原板行"]] > 1:
                verdict.update(採用=False, 同時競合=True)
            if verdict["採用"]:
                grouped["3分_" + policy].append(pure_signal(origins[row["発動ID"]], policy, verdict["実side"], verdict["役割"]))
    block.update(signals=grouped, decisions=decisions)
    return block


# ----------------------------------------
# 元29の全数値/Q・原BBO先着だけを共有し、36のVR計算は新試行で使用しない。


def dependency_pins() -> dict:
    """固定36の独立共通補助と、その旧29/33依存を現在指紋へ結ぶ。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathとSHA。37主を期待値へ使わない。
    """
    path = "scripts/量比反転/状態独立確認.py"
    return dict(sorted({**Y.dependency_pins(), path: V.sha(ROOT / path)}.items()))


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """旧共有・時点/費用尺度・四入口五運用と主準備現在版をcache前に照合する。

    引数: study/work(Path)は保存先、audit(Audit)は比較先。
    返り値: tupleは条件/実台帳/主準備/実台帳path。差があれば入力前に停止。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    Y.references(study, audit)
    old, exit_config = V.read(ENTRY_STUDY / "条件.json"), V.read(EXIT_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("旧29入口尺度:" + key, config[key], old[key])
    for key in ("運用", "必須追尾"):
        audit.check("旧33現在費用:" + key, config[key], exit_config[key])
    audit.check("事前四入口", config["戦略"], list(POLICIES))
    audit.check("事前五組合せ", config["運用組合せ"], [{"戦略": p, "出口ID": x} for p, x in
        (("B0", "X0"), ("B0", "XF"), ("R1", "XF"), ("T1", "XF"), ("S1", "XF"))])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧29R0純登録同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "純信号whitelist": list(SIGNAL_FIELDS)}
    for key, value in expected.items():
        audit.check("主準備:" + key, master[key], value)
    paths = {"scripts/構造判別/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("主/共有/入力に差がありcache前停止")
    return config, manifest, master, resolved


def old_references() -> tuple[dict, dict, str]:
    """固定36の共通readerから旧29全足と当時13列だけを読む。

    引数: なし。
    返り値: tupleは旧場別数値/Q・B0へ写した旧R0当時情報・旧全指標SHA。VRを計算しない。
    """
    frames, pure, digest = Y.old_references()
    return frames, {key: rename(row, "_V0", "_B0") for key, row in pure.items()}, digest


def reconstruct(manifest: dict) -> Any:
    """旧29独立の全原Pから構造・実方向/役割・四採否だけを別算する。

    引数: manifest(dict)は既使用66場台帳。
    返り値: Anyは非損益の場別iterator。private旧全足/元Pは照合内だけで使う。
    """
    old = V.read(ENTRY_STUDY / "条件.json")
    for block in G.reconstruct(manifest, old):
        selected = select({"signals": block["純入口"], "frames": block["価格足"], "quality": block["入口品質"]})
        signals = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        decisions = selected["decisions"]
        yield {"場": block["場"], "期間": block["期間"], "純信号": signals,
            "純信号内容SHA256": canonical_sha(signals), "純信号判断SHA256": canonical_sha([decision_signal(row) for row in signals]),
            "判定": decisions, "判定SHA256": canonical_sha(decisions), "判定判断SHA256": canonical_sha(decision_projection(decisions)),
            "旧原P判断SHA256": canonical_sha(raw_projection(block["入口品質"]["全Q発動記録"])), "入力品質": block["入力品質"],
            "_旧全足": block["価格足"][3], "_元P": {row["発動ID"]: row for row in block["入口品質"]["全Q発動記録"]}}


def compare_preparation(main: dict, block: dict, old_frames: dict, old_pure: dict, audit: Audit) -> dict:
    """旧数値/Q・全構造/競合・純四集合を、MACD表現許容と判断SHAへ分離して照合する。

    引数: main/block(dict)は主/独立場、old_frames/old_pure(dict)は旧出典、audit(Audit)は比較先。
    返り値: dictは小型件数/判断SHA。生MACD全列の完全SHA一致とは記さない。
    """
    session = block["場"]
    audit.check(session + ":旧29全数値Q/OBV", block["_旧全足"], old_frames[session])
    excluded = {"純信号内容SHA256", "判定SHA256"}
    audit.check(session + ":全構造/競合/純leaf/入力", {key: value for key, value in main.items() if key not in excluded},
        {key: value for key, value in block.items() if not key.startswith("_") and key not in excluded})
    audit.check(session + ":主生pureSHA", main["純信号内容SHA256"], canonical_sha(main["純信号"]))
    audit.check(session + ":主生判定SHA", main["判定SHA256"], canonical_sha(main["判定"]))
    audit.check(session + ":主判定判断SHA再投影", main["判定判断SHA256"], canonical_sha(decision_projection(main["判定"])))
    ids, indices = {policy: set() for policy in POLICIES}, {policy: set() for policy in POLICIES}
    for row in main["純信号"]:
        policy = row["入口ID"].removeprefix("3分_")
        origin = row["イベントID"][:-3]
        audit.check(row["イベントID"] + ":whitelist", set(row), set(SIGNAL_FIELDS))
        raw = block["_元P"][origin]
        ids[policy].add(origin)
        indices[policy].add(raw["index"])
        if row["役割"] == "反転":
            expected = rename(old_pure.get(origin + "_R0"), "_B0", "_" + policy)
            audit.leaf(row["イベントID"] + ":旧同時計反転13列完全同値", row, expected, row == expected)
        else:
            audit.check(row["イベントID"] + ":元Pから逆実方向固定", (row["side"], row["役割"]), (-raw["side"], "順行"))
    audit.check(session + ":B0旧R0全集合", ids["B0"], {key[:-3] for key, row in old_pure.items() if row["場"] == session})
    audit.check(session + ":R1subsetB0", ids["R1"] <= ids["B0"], True)
    audit.check(session + ":S1subset技術枝", ids["S1"] <= ids["R1"] | ids["T1"], True)
    audit.check(session + ":同足R/T排他", indices["R1"] & indices["T1"], set())
    return {"場": session, "期間": block["期間"], **{policy + "登録数": len(ids[policy]) for policy in POLICIES},
        "旧数値足数": len(block["_旧全足"]), "旧原P数": len(block["判定"]),
        "主生判定SHA256": main["判定SHA256"], "独立生判定SHA256": block["判定SHA256"],
        "判定判断SHA256": block["判定判断SHA256"], "旧原P判断SHA256": block["旧原P判断SHA256"]}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """共通旧29/33出典を使い、自己コード/依存/厳密範囲を37へ明示更新する。

    引数: study/work/resolved(Path)は保存先/実台帳、master(dict)は主準備、audit(Audit)は照合記録。
    返り値: dictは現版・元P/実方向・MACD限定許容を分離した証明骨格。
    """
    value = Y.proof_base(study, work, resolved, master, audit)
    value.update(コードSHA256=V.sha(Path(__file__)), 追尾コードSHA256=V.sha(Path(__file__).with_name("追尾独立確認.py")),
        依存コードSHA256=dependency_pins(),
        厳密範囲="元20窓min/max/最新同値k/価格/原key/元Mと実side/role/全競合後採否は厳密。旧ATR/MACDだけabs1e-10/rel0、D整数/符号を厳密に別確認。判定のMACD原値はleaf許容、生SHAは出典bind、判断SHAは有限/符号へ射影した範囲だけ。")
    return value


def prepare(study: Path, work: Path) -> dict:
    """root許可後に全旧数値/Qと新構造四採否だけを非先着/非PnLで比較する。

    引数: study/work(Path)は37保存先。
    返り値: dictは準備証明。label_direct/運用/会計を呼ばない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    _, manifest, master, resolved = guarded_inputs(study, work, audit)
    old_frames, old_pure, numeric_sha = old_references()
    reference = next(row for row in V.read(ENTRY_STUDY / "作業成果物.json")["ファイル"] if Path(row["パス"]).name == "全指標.jsonl.gz")
    audit.check("旧全指標展開SHA", numeric_sha, reference["展開内容SHA256"])
    stages = []
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, old_frames, old_pure, audit))
        print(json.dumps({"場": block["場"], "独立準備": "旧全数値Q/全範囲帰還/外残/四競合", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    total = sum(row["B0登録数"] for row in stages)
    audit.check("B0全旧R0数", total, len(old_pure))
    audit.check("主旧R0登録数", master["旧R0登録数"], total)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "旧29R0純登録同値": audit.mismatches == 0, "旧R0登録数": total, "場別準備": stages,
        "旧全指標展開SHA256": numeric_sha, "旧全数値Q照合足数": sum(row["旧数値足数"] for row in stages),
        "検証範囲": "旧29独立の原8列OHLC/Q/中心化MACD/ATR/OBVと全原Pを再用し旧全足へ比較。両端とlatest同値indexは元20窓から別算し、元PのM/kを保持した実side/roleの四条件と候補別同key全見送りを全件照合。純13列に未来labelを混ぜない。",
        "限界": "非先着/非運用/PnL準備。B0旧同時計反転と逆実方向Tを区別し、S1混合のfill役割固定と全新先着は固定後の別監査。24の後続監視や36のVRは計算しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧R0登録数")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 固定後は全実方向の新先着と歴史対照を検算する。


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """独立準備・現版・固定出典の一致を正式再構成前に確認する。

    引数: study/work/resolved(Path)は保存先/実台帳、master(dict)は主準備、audit(Audit)は比較。
    返り値: None。古版・差・未完はcache前に停止する。
    """
    proof = V.read(work / "独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins()}
    for key, value in expected.items():
        audit.check("独立準備bind:" + key, proof[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があるためcache前停止")


def run(study: Path, work: Path) -> dict:
    """正式結果後に全構造/四採否・全実side先着と旧B0X0全属性を確認する。

    引数: study/work(Path)は37正式先/作業先。
    返り値: dictは状態証明。新case全件の原BBO直接先着と旧同時計先着11列同値を別に照合する。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    _, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    old_frames, old_pure, numeric_sha = old_references()
    old_cases, old_case_sha = G.Q.compressed_rows(ENTRY_WORK / "入口事例.jsonl.gz")
    old_cases = {row["イベントID"]: row for row in old_cases if row["入口ID"] == "3分_R0"}
    old_details, _ = G.Q.compressed_rows(ENTRY_WORK / "全運用詳細.jsonl.gz")
    old_details = {row["場"]: row for row in old_details if row["候補ID"] == "3分_R0_X0"}
    previous_logs, _ = G.Q.compressed_rows(ENTRY_WORK / "追尾.jsonl.gz")
    old_trace = defaultdict(list)
    for row in previous_logs:
        if row["候補ID"] == "3分_R0_X0":
            old_trace[row["場"]].append(row)
    names = ("構造判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新四成果物集合", set(artifacts), {name + ".jsonl.gz" for name in names})
    for name in names:
        path = work / (name + ".jsonl.gz")
        saved[name], hashes[name] = G.Q.compressed_rows(path)
        item = artifacts[path.name]
        audit.check(name + ":保存path", (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check(name + ":圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
        audit.check(name + ":bytes", path.stat().st_size, item["圧縮バイト"])
        audit.check(name + ":展開SHA", hashes[name], item["展開内容SHA256"])
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全5x66", set(pairs), {(row["session"], cid) for row in manifest["entries"] for cid in OPERATIONS})
    case_ids = [row["イベントID"] for row in saved["入口事例"]]
    audit.check("全最小case一意", len(case_ids), len(set(case_ids)))
    stages, controls, label_counts = [], [], {policy: 0 for policy in POLICIES}
    old_label_count = 0
    inputs = {row["session"]: row for row in manifest["entries"]}
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, old_frames, old_pure, audit))
        session, period = block["場"], block["期間"]
        audit.check(session + ":正式全構造判定", grouped["構造判定"][session], [{"期間": period, **row} for row in block["判定"]])
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(inputs[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for row in block["純信号"]:
            policy = row["入口ID"].removeprefix("3分_")
            original = row["イベントID"][:-3] + "_R0"
            origin = row["イベントID"][:-3]
            raw = block["_元P"][origin]
            direct = label_direct(quotes, row, cutoff, deadline)
            expected = {**deepcopy(row), "期間": period,
                "要求時計JST": datetime.fromtimestamp(row["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": origin, "元価格side": raw["side"],
                "旧R0イベントID": original if row["役割"] == "反転" else None, **direct}
            case = cases.get(row["イベントID"])
            audit.check(row["イベントID"] + ":全case/原正常BBO直接先着/実方向役割", case, expected)
            if row["役割"] == "反転":
                audit.check(row["イベントID"] + ":旧同時計反転先着全11列", direct,
                    {key: old_cases[original][key] for key in LABEL_FIELDS})
                old_label_count += 1
            label_counts[policy] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] != "3分_B0_X0":
                continue
            trace = [row for row in grouped["追尾"][session] if row["候補ID"] == detail["候補ID"]]
            adapted, adapted_trace = rename(detail, "_B0", "_R0"), rename(trace, "_B0", "_R0")
            audit.leaf(session + ":旧R0X0全ledger完全同値", adapted, old_details[session], adapted == old_details[session])
            audit.leaf(session + ":旧R0X0全trace完全同値", adapted_trace, old_trace[session], adapted_trace == old_trace[session])
            controls.append({"場": session, "候補ID": detail["候補ID"], "全運用同値": adapted == old_details[session],
                "全追尾同値": adapted_trace == old_trace[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                "旧識別子追尾内容SHA256": canonical_sha(adapted_trace)})
        print(json.dumps({"場": session, "独立状態": "旧全数値Q/全範囲構造/四採否/実side新先着/B0対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 4, "運用候補数": 5, "現方針運用候補数": 4,
            "入口125250評価の変更": True, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("全case数", len(saved["入口事例"]), sum(label_counts.values()))
    audit.check("B0旧全R0数", label_counts["B0"], len(old_pure))
    audit.check("B0保存対照証明", V.read(study / "B0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages,
        "旧R0登録数": label_counts["B0"], "旧同時計反転先着照合数": old_label_count, "方針別case数": label_counts,
        "全先着直接照合件数": sum(label_counts.values()), "方針別先着直接照合件数": label_counts,
        "旧29全属性同値場数": len(controls), "旧全指標展開SHA256": numeric_sha,
        "旧全数値Q照合足数": sum(row["旧数値足数"] for row in stages),
        "保存構造判定数": len(saved["構造判定"]), "保存入口事例数": len(saved["入口事例"]), "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()}, "共有入口事例展開SHA256": old_case_sha,
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"), "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "旧29独立原8列OHLC/Q/中心化MACD/ATR/OBVと全Pを再構成し旧全足へ全列比較。元20窓から両端とlatest同値indexを別算、元PのM/kを保って四候補の実方向/役割/競合を全件照合。全caseは実sideの原BBO+1秒/TTL30/125250/gap/期限を直接比較し、反転枝だけ旧29同時計11label列同値を追加確認。B0X0全66ledger/traceは識別子以外全属性同値。",
        "限界": "新規受付/代理約定/Decimalは別財務へSHA接続。全保有X0/XF線と最初返済要求は別追尾。MACD原値は限定許容と符号を分離し、新たな後続監視/VRを計算しない。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧R0登録数", "旧29全属性同値場数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可後の非損益準備又は固定後状態監査だけを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00037構造判別と実方向の独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    proof = prepare(args.study.resolve(), args.work.resolve()) if args.prepare else run(args.study.resolve(), args.work.resolve())
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
