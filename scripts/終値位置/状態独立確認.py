"""00033の固定31入口と、原OHLCの終値位置による同時点選別を独立確認する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
WORK = ROOT / "work/終値位置/00033"
ENTRY_STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
ENTRY_WORK = ROOT / "work/CCI突破/00031"
POLICIES = ("T0", "T1")
OPERATIONS = ("3分_T0_X0", "3分_T0_XF", "3分_T1_XF")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
OLD_LOCK_SHA = "b1a8cc4aec9def6907f65e0372ad8d280d62390e8059e83c1f38d6c927615cce"
OLD_CONDITION_SHA = "8d4cd04e02e26144f16375dea7e722fb84f7f6384a75606b925f1ea792d9ded1"


def helper(path: Path, name: str) -> Any:
    """固定済みの独立足・CCI・照合補助だけを読み込む。

    引数: path (Path) は旧独立補助、name (str) はモジュール識別名。
    返り値: Any は読み込んだ補助。33主入口・運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


G = helper(ROOT / "scripts/CCI突破/状態独立確認.py", "終値位置の固定31独立足と入口")
B, S, V, P, SOURCE_FIELDS = G.B, G.S, G.V, G.P, G.SOURCE_FIELDS
Audit = G.Audit


# ----------------------------------------
# CLVは買い側と売り側の距離比を別々に作り、その差を原分数で求める。

def clv(frame: dict) -> Fraction | None:
    """原H/L/Cの上下端からの距離比の差でCLVを厳密計算する。

    引数: frame (dict) はhigh/low/closeを持つ当時の原足。
    返り値: Fraction|None はCLV。有限有効OHLCでない足と幅0は欠測。
    """
    values = [frame.get(name) for name in ("high", "low", "close")]
    if not all(B.finite(value) for value in values):
        return None
    high, low, close = map(Fraction, values)
    if not low <= close <= high or high == low:
        return None
    return (close - low) / (high - low) - (high - close) / (high - low)


def ratio(value: Fraction | None) -> dict:
    """精密比を分数出典と表示値へ分けて保存する。

    引数: value (Fraction|None) は厳密比又は欠測。
    返り値: dict は値/分子/分母/有効。幅0をゼロへ補完しない。
    """
    return {"値": None if value is None else float(value), "分子": None if value is None else value.numerator,
        "分母": None if value is None else value.denominator, "有効": value is not None}


def shape(row: dict, previous: dict | None = None) -> dict:
    """原足からCLVと二採否を別式で作り、前ATR距離を診断だけに残す。

    引数: row (dict) は固定31の原価格発動、previous (dict|None) は任意の前足診断参照。
    返り値: dict は全形状列。T0を保ち、CLV幅0/非正符号はT1だけ不採用。
    """
    values = [row[name] for name in ("high", "low", "close")]
    if not all(B.finite(value) for value in values):
        raise ValueError("有限の原OHLCだけを受け付けます")
    high, low, close = map(Fraction, values)
    if high < low or not low <= close <= high or row["side"] not in (-1, 1):
        raise ValueError("有効OHLCと売買符号だけを受け付けます")
    value, side = clv(row), row["side"]
    control = deepcopy(row["戦略判定"]["C0"])
    reasons = list(control["理由"]) if not control["採用"] else []
    if value is None:
        reasons.append("現在足高安幅0")
    elif value * side <= 0:
        reasons.append("実方向CLVstrict正不成立")
    filtered = {"採用": not reasons, "理由": reasons or ["CCI突破と実方向CLVstrict正"],
        "同時競合": control["同時競合"]}
    boundary = Fraction(row["直前最高H"] if side == 1 else row["直前最安L"])
    distance = close - boundary if side == 1 else boundary - close
    previous = previous if previous is not None else row.get("前3分参照")
    atr = previous.get("atr") if previous else None
    positive = B.finite(atr) and atr > 0
    old_range = Fraction(row["直前最高H"]) - Fraction(row["直前最安L"])
    keys = ("場", "index", "open", "high", "low", "close", "side", "方向", "要求時計秒", "要求原板行",
        "足終了時計秒", "確認遅延秒", "共通M準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象")
    return {**{name: deepcopy(row[name]) for name in keys}, "原発動ID": row["発動ID"],
        "旧イベントID": row["発動ID"] + "_C0", "CLV": ratio(value),
        "実方向CLV符号": None if value is None else int(side * value > 0) - int(side * value < 0),
        "高安幅pt": float(high - low), "T0採用": control["採用"], "T1採用": filtered["採用"],
        "戦略判定": {"T0": control, "T1": filtered},
        "診断": {"突破距離pt": float(distance), "突破基準価格": float(boundary),
            "前ATR": atr if positive else None, "前ATR規格化突破距離": ratio(distance / Fraction(atr) if positive else None),
            "直前20高安幅pt": float(old_range), "直前範囲規格化突破距離": ratio(distance / old_range if old_range > 0 else None),
            "採否への使用": False}}


def select(block: dict) -> dict:
    """固定31純C0だけを同時点のT0/T1へ分ける。

    引数: block (dict) はquality/signalsを持つ非損益材料。
    返り値: dict は全原P形状と二案純信号を持つ材料。待機や再発動は追加しない。
    """
    rows = [shape(row) for row in block["quality"]["全Q発動記録"]]
    mapping = {row["旧イベントID"]: row for row in rows}
    if len(mapping) != len(rows):
        raise ValueError("原発動IDが重複")
    original = block["signals"]["3分_C0"]
    if {row["イベントID"] for row in original} != {row["旧イベントID"] for row in rows if row["T0採用"]}:
        raise ValueError("固定31C0とT0の原採否集合が不一致")
    selected = {}
    for policy in POLICIES:
        selected["3分_" + policy] = []
        for row in original:
            if mapping[row["イベントID"]][policy + "採用"]:
                signal = pure_signal(row)
                if row["入口ID"] != "3分_C0" or not row["イベントID"].endswith("_C0"):
                    raise ValueError("固定31C0純信号だけを写します")
                signal["入口ID"] = "3分_" + policy
                signal["イベントID"] = row["イベントID"][:-3] + "_" + policy
                selected["3分_" + policy].append(signal)
    block["signals"], block["shape_rows"] = selected, rows
    return block


def canonical_sha(value: Any) -> str:
    """JSON安全な保存値の正規内容SHAを作る。

    引数: value (Any) は保存対象。
    返り値: str はUTF-8正規JSONのSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def pure_signal(row: dict) -> dict:
    """当時の原足・要求情報だけを明示whitelistへ写す。

    引数: row (dict) は純再構成信号又は出典比較用旧case。
    返り値: dict は新しい当時情報辞書。先着・仮約定・未来情報は渡さない。
    """
    return {name: deepcopy(row.get(name)) if name == "bb_mean" else deepcopy(row[name]) for name in SIGNAL_FIELDS}


def decision_signal(row: dict) -> dict:
    """ATR浮動値だけを正有効性・D整数へ分離して厳密判断射影を作る。

    引数: row (dict) は全leafを別照合する純信号。
    返り値: dict はATR判断以外を一切変更しない射影。
    """
    result = deepcopy(row)
    atr = result.pop("atr")
    valid = B.finite(atr) and atr > 0
    result["ATR判断"] = {"正有効": valid, "Dpt整数": max(5, math.ceil(atr / 5) * 5) if valid else None}
    return result


def decision_shape(row: dict) -> dict:
    """診断の前ATR浮動値とその精密比だけを明示判断射影へ分離する。

    引数: row (dict) は全leafを別照合する形状行。
    返り値: dict はCLV/価格/時点/採否/範囲比を保持した厳密判断用コピー。
    """
    output = deepcopy(row)
    atr = output["診断"].pop("前ATR")
    output["診断"]["前ATR判断"] = {"正有効": atr is not None,
        "Dpt整数": max(5, math.ceil(atr / 5) * 5) if atr is not None else None}
    output["診断"]["前ATR規格化突破距離"] = {"有効": row["診断"]["前ATR規格化突破距離"]["有効"]}
    return output


def check_shape(name: str, actual: dict, expected: dict, audit: Audit) -> None:
    """CLV等を厳密比較し、前ATR由来の診断だけ限定許容と各自算術で照合する。

    引数: name (str) は項目名、actual/expected (dict) は主保存/独立形状、audit (Audit) は記録。
    返り値: None。前ATR比の分数同一は要求せず、双方が各自の元ATRへ厳密一致することを要求する。
    """
    audit.check(name + ":厳密判断列", decision_shape(actual), decision_shape(expected))
    audit.check(name + ":前ATR:atr", actual["診断"]["前ATR"], expected["診断"]["前ATR"])
    for label, row in (("保存", actual), ("独立", expected)):
        diagnostic = row["診断"]
        atr = diagnostic["前ATR"]
        boundary = Fraction(diagnostic["突破基準価格"])
        distance = (Fraction(row["close"]) - boundary) * row["side"]
        value = distance / Fraction(atr) if atr is not None else None
        audit.check(name + ":" + label + ":前ATR比各自元分数算術", diagnostic["前ATR規格化突破距離"], ratio(value))
    left = actual["診断"]["前ATR規格化突破距離"]["値"]
    right = expected["診断"]["前ATR規格化突破距離"]["値"]
    numeric = B.finite(left) and B.finite(right)
    equal = math.isclose(left, right, rel_tol=0, abs_tol=1e-10) if numeric else left == right
    audit.leaf(name + ":前ATR診断比表示abs1e-10", left, right, equal)
    audit.ratio_count = getattr(audit, "ratio_count", 0) + 1
    audit.ratio_repr_diff = getattr(audit, "ratio_repr_diff", 0) + int(left != right)
    audit.ratio_max_abs = max(getattr(audit, "ratio_max_abs", 0.0), abs(left - right) if numeric else 0.0)


def to_old(value: Any, policy: str = "T0") -> Any:
    """明示した新方針IDだけを固定31のC0へ戻す。

    引数: value (Any) は比較用JSON値、policy (str) はT0又はT1。
    返り値: Any は再帰コピー。ID以外の価格・時計・型・属性を除外しない。
    """
    if policy not in POLICIES:
        raise ValueError("T0/T1だけをC0へ射影します")
    if isinstance(value, dict):
        return {key: to_old(item, policy) for key, item in value.items()}
    if isinstance(value, list):
        return [to_old(item, policy) for item in value]
    if isinstance(value, str):
        return "C0" if value == policy else value.replace("3分_" + policy, "3分_C0").replace("_" + policy, "_C0")
    return value


def dependency_pins() -> dict:
    """固定31独立とその推移的補助の現在SHAを列挙する。

    引数: なし。
    返り値: dict[str,str] はROOT相対pathと指紋。主33を依存に含めない。
    """
    return dict(sorted({**G.dependency_pins(), "scripts/CCI突破/状態独立確認.py": V.sha(Path(G.__file__))}.items()))


# ----------------------------------------
# 共有31の固定・証明・当時属性だけを接続し、大明細やラベルを複製しない。

def raw_projection(rows: list[dict]) -> list[dict]:
    """固定31の全原価格発動からATR浮動値以外の厳密判断列を取り出す。

    引数: rows (list[dict]) は原OHLCから独立再構成した31原発動。
    返り値: list[dict] は価格・時点・CCI分数・全旧採否。ラベルを含めない。
    """
    names = ("場", "発動ID", "index", "side", "close", "要求時計秒", "要求原板行", "足終了時計秒",
        "直前最高H", "直前最安L", "共通M準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象",
        "戦略判定", "BB幅比較厳密符号")
    return [{**{name: deepcopy(row[name]) for name in names},
        **{name: None if row[name] is None else {field: row[name][field] for field in ("分子", "分母", "有効")}
            for name in ("CCI現", "CCI前")}} for row in rows]


def entry_reference(study: Path, audit: Audit) -> dict:
    """共有31の正本・固定・完了証明と六圧縮明細を原cache前に検査する。

    引数: study (Path) は33正式先、audit (Audit) は比較記録。
    返り値: dict は検査済み入口参照。先着・損益を新たに計算しない。
    """
    pointer = V.read(study / "入口参照.json")
    audit.check("共有入口試行", pointer["参照試行"], "00031")
    audit.check("共有入口既使用", pointer["全66場既使用"], True)
    audit.check("共有入口非複製", pointer["大明細複製"], False)
    audit.check("旧31固定anchor", V.sha(ENTRY_STUDY / "固定.json"), OLD_LOCK_SHA)
    audit.check("旧31条件anchor", V.sha(ENTRY_STUDY / "条件.json"), OLD_CONDITION_SHA)
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    audit.check("共有入口証明全集合", set(pointer["文書と証明"]), names)
    for name, item in pointer["文書と証明"].items():
        path = ENTRY_STUDY / name
        audit.check("共有証明正本:" + name, (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check("共有証明SHA:" + name, item["SHA256"], V.sha(path))
    for name, digest in V.read(ENTRY_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("旧31固定現在:" + name, V.sha(ROOT / name), digest)
    artifacts = V.read(ENTRY_STUDY / "作業成果物.json")["ファイル"]
    audit.check("共有6明細宣言", pointer["共有明細"], artifacts)
    audit.check("共有6明細数", len(artifacts), 6)
    for item in artifacts:
        path = ROOT / item["パス"]
        audit.check("共有明細範囲:" + path.name, path.resolve().parent, ENTRY_WORK.resolve())
        audit.check("共有明細圧縮SHA:" + path.name, V.sha(path), item["圧縮SHA256参考"])
        audit.check("共有明細bytes:" + path.name, path.stat().st_size, item["圧縮バイト"])
    for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        old = V.read(ENTRY_STUDY / name)
        audit.check("共有完了証明:" + name, old["全件一致"], True)
        audit.check("共有不一致0:" + name, old["不一致数"], 0)
    return pointer


def shared_signals() -> list[dict]:
    """旧C0のcaseから比較に必要な当時属性だけを一行ずつ射影する。

    引数: なし。
    返り値: list[dict] は旧C0の比較用信号。未来属性を採否や運用へ渡さない。
    """
    import gzip
    output = []
    with gzip.open(ENTRY_WORK / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["入口ID"] == "3分_C0":
                output.append(pure_signal(row))
    return output


# ----------------------------------------
# 実入力へ進む前に主準備と正本指紋を照合し、独立準備へ現コードを結び付ける。

def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path, dict]:
    """33条件と非損益主準備を共有31の正本へ結び付ける。

    引数: study/work (Path) は33保存先、audit (Audit) は比較記録。
    返り値: tuple は条件/実台帳/主準備/解決台帳/入口参照。不一致ならcache前停止。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    pointer = entry_reference(study, audit)
    old = V.read(ENTRY_STUDY / "条件.json")
    changed = {"CCI突破", "戦略", "表示代表", "出口定義", "依存", "出口", "運用", "必須追尾"}
    for name, expected in old.items():
        if name not in changed:
            audit.check("固定31継承条件:" + name, config[name], expected)
    audit.check("旧共通運用数値不変", {name: config["運用"][name] for name in old["運用"]}, old["運用"])
    audit.check("新起動参照片道滑り", config["運用"]["追尾起動想定片道滑りpt"], 5)
    audit.check("旧共通追尾幅/床/丸め/優先不変",
        {name: config["必須追尾"][name] for name in old["必須追尾"] if name != "起動幅pt"},
        {name: value for name, value in old["必須追尾"].items() if name != "起動幅pt"})
    for name, expected in {"起動幅pt": None, "起動参照想定片道滑りpt": 5, "起動参照往復費用円": 122, "旧X0起動幅pt": 5}.items():
        audit.check("ユーザー指定起動:" + name, config["必須追尾"][name], expected)
    audit.check("33二出口定義", config["出口"], [{"出口ID": "X0"}, {"出口ID": "XF"}])
    audit.check("33三運用組合せ", config["運用組合せ"], [{"戦略": "T0", "出口ID": "X0"},
        {"戦略": "T0", "出口ID": "XF"}, {"戦略": "T1", "出口ID": "XF"}])
    audit.check("現方針候補はXF", config["現方針候補出口"], ["XF"])
    audit.check("33二方針", config["戦略"], list(POLICIES))
    audit.check("入口条件正本", (study / config["入口条件参照"]["パス"]).resolve(), (ENTRY_STUDY / "条件.json").resolve())
    audit.check("入口条件指紋", config["入口条件参照"]["SHA256"], OLD_CONDITION_SHA)
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧31C0純信号同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "純信号whitelist": list(SIGNAL_FIELDS), "共有入口参照": pointer}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/終値位置/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主準備66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("主/共有入力の不一致によりcache前停止")
    return config, manifest, master, resolved, pointer


def reconstruct(manifest: dict) -> Any:
    """固定31の独立原OHLC/CCI/公開準備を再構成し、原PのCLVだけを加える。

    引数: manifest (dict) は既使用66場台帳。
    返り値: Any は場別iterator。旧指標/context大列を保存せず先着・損益を呼ばない。
    """
    old = V.read(ENTRY_STUDY / "条件.json")
    for block in G.reconstruct(manifest, old):
        selected = select({"quality": block["入口品質"], "signals": block["純入口"]})
        signals = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        shapes = selected["shape_rows"]
        yield {"場": block["場"], "期間": block["期間"], "純信号": signals,
            "純信号内容SHA256": canonical_sha(signals),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in signals]),
            "原P判定SHA256": canonical_sha(raw_projection(block["入口品質"]["全Q発動記録"])),
            "形状判断SHA256": canonical_sha([decision_shape(row) for row in shapes]),
            "形状選別": shapes, "入力品質": block["入力品質"]}


def compare_preparation(main: dict, block: dict, saved: dict, audit: Audit) -> dict:
    """主の全形状・全純信号を独立値と比較し、T0/T1の旧出典と集合を検査する。

    引数: main/block (dict) は主/独立場、saved (dict) は旧C0当時射影、audit (Audit) は記録。
    返り値: dict は小型場別証明。ATR診断分数の全文同一とは主張しない。
    """
    session = block["場"]
    exclude = {"純信号内容SHA256", "形状選別"}
    audit.check(session + ":全純入口/原P/判断/品質", {k: v for k, v in main.items() if k not in exclude},
        {k: v for k, v in block.items() if k not in exclude})
    audit.check(session + ":主純信号全文SHA", main["純信号内容SHA256"], canonical_sha(main["純信号"]))
    audit.check(session + ":主形状判断SHA", main["形状判断SHA256"], canonical_sha([decision_shape(row) for row in main["形状選別"]]))
    audit.check(session + ":全原P形状数", len(main["形状選別"]), len(block["形状選別"]))
    for actual, expected in zip(main["形状選別"], block["形状選別"]):
        check_shape(session + ":" + expected["原発動ID"], actual, expected, audit)
    ids = {policy: set() for policy in POLICIES}
    for row in main["純信号"]:
        policy = row["入口ID"].removeprefix("3分_")
        audit.check(row["イベントID"] + ":二方針内", policy in POLICIES, True)
        if policy not in POLICIES:
            continue
        audit.check(row["イベントID"] + ":明示列", set(row), set(SIGNAL_FIELDS))
        original = to_old(row, policy)
        expected = saved.get(original["イベントID"])
        audit.leaf(row["イベントID"] + ":旧31当時属性完全同値", original, expected, original == expected)
        ids[policy].add(original["イベントID"])
    audit.check(session + ":T1同時点subset", ids["T1"].issubset(ids["T0"]), True)
    audit.check(session + ":T0旧C0全採否", ids["T0"], {eid for eid, row in saved.items() if row["場"] == session})
    return {"場": session, "期間": block["期間"], "原価格発動数": len(block["形状選別"]),
        "T0純信号数": len(ids["T0"]), "T1純信号数": len(ids["T1"]),
        "主生純信号内容SHA256": main["純信号内容SHA256"], "独立純信号判断SHA256": block["純信号判断SHA256"],
        "原P判定SHA256": block["原P判定SHA256"], "形状判断SHA256": block["形状判断SHA256"],
        "主生形状内容SHA256": canonical_sha(main["形状選別"])}


def proof_base(study: Path, work: Path, resolved: Path, audit: Audit, master: dict) -> dict:
    """主独立の版・入力と限定許容/厳密範囲を共通proofへ残す。

    引数: study/work/resolved (Path) は保存先/実台帳、audit (Audit) は記録、master (dict) は主準備。
    返り値: dict は共通証明。前ATR診断比の同一分数や生ATR全文SHA一致を主張しない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": 66, "全66場既使用": True, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主コードSHA256": master["コードSHA256"], "主準備SHA256": V.sha(work / "準備点検.json"),
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "旧31固定SHA256": OLD_LOCK_SHA,
        "旧31状態証明SHA256": V.sha(ENTRY_STUDY / "状態独立確認.json"),
        "旧31追尾証明SHA256": V.sha(ENTRY_STUDY / "追尾独立確認.json"),
        "ユーザー指定起動": {"現方針": "正常返済BBOの現在費用後含み益strict正。起動後名目entry床と旧MFE-D継続",
            "参照往復費用円": 122, "参照片道滑りpt": 5, "旧A5参考": "3分_T0_X0のみ"},
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/D整数厳密"},
        "前ATR診断比照合": {"leaf数": getattr(audit, "ratio_count", 0), "表示表現差数": getattr(audit, "ratio_repr_diff", 0),
            "表示最大絶対差": getattr(audit, "ratio_max_abs", 0.0),
            "許容": "表示比だけabs1e-10/rel0。双方の分子分母は各自の元前ATRによるFraction算術と厳密照合し、相互の同一分数は要求しない"},
        "厳密範囲": "原OHLC/CLV分数・符号/幅/時計/ID/共通M/全採否/直前範囲比は厳密。ATRだけ全leaf許容とD整数を別照合し、明示判断射影SHAを比較。主生pureの旧31完全同値と生形状SHAは別出典bind"}


def prepare(study: Path, work: Path) -> dict:
    """root明示起動で非損益の全66形状・純入口準備を照合する。

    引数: study/work (Path) は33正式/作業先。
    返り値: dict は独立準備証明。主準備が保存される前には起動できない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved, pointer = guarded_inputs(study, work, audit)
    shared = shared_signals()
    saved = {row["イベントID"]: row for row in shared}
    audit.check("共有C0純信号一意", len(saved), len(shared))
    stages = []
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, saved, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原OHLC/CLV/31C0同時点subset", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    count = sum(row["T0純信号数"] for row in stages)
    audit.check("旧C0全集合数", count, len(saved))
    audit.check("主T0純信号数", master["T0純信号数"], count)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, audit, master), "ラベル計算": False, "損益計算": False,
        "旧31C0純信号同値": audit.mismatches == 0, "T0純信号数": count,
        "T1純信号数": sum(row["T1純信号数"] for row in stages), "場別準備": stages,
        "原価格発動数": sum(row["原価格発動数"] for row in stages),
        "検証範囲": "元8列cacheから固定31の独立3/15分OHLC/CCI/上位BB公開M/全原Pを別構築。原HLCの上下距離比差でCLVを厳密別式計算し、同時点T0旧C0完全同値/T1subsetと全形状を照合。前ATR診断比だけ事前限定許容と各自分数算術で検算。",
        "限界": "先着/約定/運用/PnLは準備で計算しない。共有caseは当時whitelistだけ即射影し未来情報を新信号へ渡さない。全66場既使用の開発内照合で未見評価ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "T0純信号数", "T1純信号数")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 固定後だけ正式三明細を開き、全形状とT0対照を照合する。PnLは別会計証明。

def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """独立準備と固定出典を正式の原cache走査より先に検査する。

    引数: study/work/resolved (Path) は保存先/台帳、master (dict) は主準備、audit (Audit) は記録。
    返り値: None。未完・古版・変更出典があれば以降を拒否する。
    """
    prepared = V.read(work / "独立準備点検.json")
    values = {"全件一致": True, "不一致数": 0, "ラベル計算": False, "損益計算": False,
        "コードSHA256": V.sha(Path(__file__)), "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "依存コードSHA256": dependency_pins()}
    for name, expected in values.items():
        audit.check("独立準備bind:" + name, prepared[name], expected)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("独立準備/固定の版が異なるためcache前停止")


def run(study: Path, work: Path) -> dict:
    """root正式完了後に全形状・純入口とT0の旧全運用/追尾同値を検査する。

    引数: study/work (Path) は33正式/作業先。
    返り値: dict は状態証明。先着・返済再生・PnLはここで計算しない。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("正式結果/固定が必要です")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved, pointer = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    names = ("形状選別", "全運用詳細", "追尾")
    rows, hashes, grouped = {}, {}, {}
    artifacts = {Path(item["パス"]).name: item for item in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新成果物3系列", set(artifacts), {name + ".jsonl.gz" for name in names})
    sessions = {entry["session"] for entry in manifest["entries"]}
    for name in names:
        path = work / (name + ".jsonl.gz")
        rows[name], hashes[name] = B.compressed_rows(path)
        item = artifacts[name + ".jsonl.gz"]
        audit.check("成果物正本path:" + name, (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check("成果物展開SHA:" + name, hashes[name], item["展開内容SHA256"])
        audit.check("成果物圧縮SHA:" + name, V.sha(path), item["圧縮SHA256参考"])
        audit.check("成果物圧縮bytes:" + name, path.stat().st_size, item["圧縮バイト"])
        by_session = defaultdict(list)
        for row in rows[name]:
            audit.check("成果物場範囲:" + name, row["場"] in sessions, True)
            by_session[row["場"]].append(row)
        grouped[name] = by_session
    shared = shared_signals()
    saved = {row["イベントID"]: row for row in shared}
    audit.check("旧C0当時属性一意", len(saved), len(shared))
    old_details, _ = B.compressed_rows(ENTRY_WORK / "全運用詳細.jsonl.gz")
    old_logs, _ = B.compressed_rows(ENTRY_WORK / "追尾.jsonl.gz")
    old_map = {row["場"]: row for row in old_details if row["候補ID"] == "3分_C0_X0"}
    old_trace = defaultdict(list)
    for row in old_logs:
        if row["候補ID"] == "3分_C0_X0":
            old_trace[row["場"]].append(row)
    input_rows = V.read(study / "入力品質.json")
    audit.check("入力品質場数", len(input_rows), 66)
    inputs = {row["場"]: row for row in input_rows}
    audit.check("入力品質場集合", set(inputs), sessions)
    stages, controls = [], []
    candidates = set(OPERATIONS)
    audit.check("全運用場候補数", len(rows["全運用詳細"]), 198)
    pairs = [(row["場"], row["候補ID"]) for row in rows["全運用詳細"]]
    audit.check("全運用場候補一意", len(pairs), len(set(pairs)))
    audit.check("全運用3x66集合", set(pairs), {(session, cid) for session in sessions for cid in candidates})
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        session, period = block["場"], block["期間"]
        stages.append(compare_preparation(main, block, saved, audit))
        actual = grouped["形状選別"][session]
        audit.check(session + ":正式形状数", len(actual), len(block["形状選別"]))
        for index, (stored, expected) in enumerate(zip(actual, block["形状選別"])):
            audit.check(session + ":形状期間:" + str(index), stored["期間"], period)
            check_shape(session + ":正式形状:" + str(index), {k: v for k, v in stored.items() if k != "期間"}, expected, audit)
        audit.check(session + ":入力品質", inputs[session], {"期間": period, **block["入力品質"]})
        details = grouped["全運用詳細"][session]
        audit.check(session + ":全三候補集合", {row["候補ID"] for row in details}, candidates)
        for detail in details:
            cid = detail["候補ID"]
            audit.check(cid + session + ":期間", detail["品質"]["期間"], period)
            if cid != "3分_T0_X0":
                continue
            trace = [row for row in grouped["追尾"][session] if row["候補ID"] == cid]
            normalized_detail, normalized_trace = to_old(detail), to_old(trace)
            audit.leaf(session + ":T0旧C0全運用完全同値", normalized_detail, old_map[session], normalized_detail == old_map[session])
            audit.leaf(session + ":T0旧C0全追尾完全同値", normalized_trace, old_trace[session], normalized_trace == old_trace[session])
            controls.append({"場": session, "候補ID": cid, "全運用同値": normalized_detail == old_map[session],
                "全追尾同値": normalized_trace == old_trace[session],
                "旧識別子全運用内容SHA256": canonical_sha(normalized_detail),
                "旧識別子追尾内容SHA256": canonical_sha(normalized_trace)})
        print(json.dumps({"場": session, "独立状態": "CLV/全採否/T0全属性対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result, old_result = V.read(study / "結果.json"), V.read(ENTRY_STUDY / "結果.json")
    for name, expected in (("全66場既使用", True), ("入口評価数", 2), ("運用候補数", 3), ("現方針運用候補数", 2),
            ("入口125250評価の変更", True), ("表示固定ID", list(OPERATIONS))):
        audit.check("正式結果:" + name, result[name], expected)
    audit.check("正式二入口順", [row["入口ID"] for row in result["入口評価"]], ["3分_" + policy for policy in POLICIES])
    for operation in result["結果"]:
        audit.check(operation["候補ID"] + ":現方針候補", operation["現方針候補"], operation["候補ID"].endswith("_XF"))
    original = next(row for row in old_result["入口評価"] if row["入口ID"] == "3分_C0")
    control = next(row for row in result["入口評価"] if row["入口ID"] == "3分_T0")
    for name in ("学習", "条件選択", "後続検査", "入口支持", "70目標"):
        audit.check("T0旧C0共有入口:" + name, control[name], original[name])
    audit.check("T0保存対照証明", V.read(study / "T0対照同値.json"),
        {"全件一致": True, "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    old_state = V.read(ENTRY_STUDY / "状態独立確認.json")
    proof = {**proof_base(study, work, resolved, audit, master), "場別準備": stages,
        "保存形状選別数": len(rows["形状選別"]), "保存運用詳細数": len(rows["全運用詳細"]), "保存追尾数": len(rows["追尾"]),
        "T0純信号数": sum(row["T0純信号数"] for row in stages), "T1純信号数": sum(row["T1純信号数"] for row in stages),
        "旧31C0完全同値数": len(controls), "旧31先着再計算": False,
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(rows[name])} for name in names},
        **{name + "展開SHA256": value for name, value in hashes.items()},
        "入口事例展開SHA256": old_state["入口事例展開SHA256"], "共有入口事例展開SHA256": old_state["入口事例展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "元8列から独立31の足/数値/公開Mと全原価格発動を再構成し、CLV・二採否・T0完全同値/T1同時点subset・新形状全行と入力品質を照合。3成果物全行SHA/件数、T0の旧C0全運用/追尾66群を除外なしで照合。",
        "限界": "先着ラベルは旧31共有証明へbindし再計算しない。全最初返済要求/追尾線は別追尾監査、新規受入/+1秒代理約定/費用/期間集計は会計監査。既使用66場を未見とは呼ばない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "保存形状選別数", "旧31C0完全同値数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root明示起動だけで非損益準備か正式状態監査を選択する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定では原入力へ進まず、不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00033の終値位置と固定31C0の独立確認")
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
