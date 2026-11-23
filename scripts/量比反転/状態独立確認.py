"""00036の旧29価格・数量を独立再用し、B20現前と三採否を別式で検算する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import gzip
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00036_価格失敗と量比の方向変化"
WORK = ROOT / "work/量比反転/00036"
ENTRY_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
ENTRY_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
ENTRY_LOCK_SHA = "353143ea3f7a626736bf44551d17ba6e22b8bfd76ee40e2f4f9b0c190736f48a"
PERIOD = 20
POLICIES = ("V0", "V1", "V2")
OPERATIONS = ("3分_V0_X0", "3分_V0_XF", "3分_V1_XF", "3分_V2_XF")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
LABEL_FIELDS = ("ラベル", "理由", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
    "判定気配", "最大順行pt", "最大逆行pt", "所要分")


def helper(path: Path, name: str) -> Any:
    """固定済み独立補助だけを起動なしで読む。

    引数: path(Path)は補助、name(str)は識別名。
    返り値: Anyはモジュール。36主入口・指標・運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


G = helper(ROOT / "scripts/OBV反転/状態独立確認.py", "量比反転の固定29独立価格数量")
L = helper(ROOT / "scripts/入口探索/独立照合.py", "量比反転の固定独立正常気配先着")
B, S, V, Audit = G.B, G.S, G.V, G.Audit


def canonical_sha(value: Any) -> str:
    """保存値を日本語UTF-8正規JSONの内容指紋へ写す。

    引数: value(Any)はJSON保存可能な値。
    返り値: strはSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def pure_signal(row: dict, policy: str = "V0") -> dict:
    """旧R0の当時13列だけを取り出し、識別子だけを三案へ変える。

    引数: row(dict)は旧純入口又はcase、policy(str)は三案。
    返り値: dictはラベル・未来量比を含まない新しい当時信号。
    """
    if policy not in POLICIES:
        raise ValueError("事前三方針だけです")
    result = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    result.update(入口ID="3分_" + policy, イベントID=row["イベントID"][:-3] + "_" + policy)
    return result


# ----------------------------------------
# 旧Qのqを正確な二進観測値として扱い、窓スライス和と交差積から現前差を別算する。


def ratio_parts(changes: list[tuple]) -> tuple[Fraction | None, dict, Fraction, Fraction]:
    """方向ごとの独立スライス和から量比と比較用N/Tを返す。

    引数: changes(list[tuple])は足番号/方向/観測qの窓。
    返り値: tupleはB又はNone/表示量/N=U−D/T。全0量は欠測で片側0は有効。
    """
    exact = [(direction, Fraction(Decimal.from_float(float(q)))) for _, direction, q in changes]
    up = sum((amount for direction, amount in exact if direction > 0), Fraction(0))
    down = sum((amount for direction, amount in exact if direction < 0), Fraction(0))
    flat = sum((amount for direction, amount in exact if direction == 0), Fraction(0))
    total, signed = up + down + flat, up - down
    value = signed / total if len(changes) == PERIOD and total > 0 else None
    return value, {"上昇量": float(up), "下落量": float(down), "同値量": float(flat), "合計量": float(total)}, signed, total


def volume_panels(frames: list[dict], session: str) -> list[dict]:
    """価格の比較元と数量変化区間を別管理し、全足B20を直接スライスで作る。

    引数: frames(list[dict])は独立29の3分数値足、session(str)は場。
    返り値: list[dict]は小型全足。最古closeのqは不要、量badでも有効closeを次基準へ残す。
    """
    previous, last_index, segment, number, changes = None, None, None, 0, []
    rows = []
    for frame in frames:
        if frame["場"] != session or frame["minutes"] != 3:
            raise ValueError("当場3分足だけです")
        index = frame["index"]
        adjacent = last_index is not None and index == last_index + 1
        reasons = []
        if last_index is None:
            reasons.append("場開始")
        elif not adjacent:
            reasons.append("足番号欠枠")
        if not frame["publish"]:
            reasons.append("非公開足")
        if frame["missing"]:
            reasons.append("欠枠")
        if not frame["価格数値入力可"]:
            reasons.append("OHLC不正")
        price_ok = bool(frame["publish"] and frame["価格数値入力可"] and not frame["missing"])
        if not adjacent or not price_ok:
            changes, previous, segment = [], None, None
        quantity = frame.get("数量参照")
        q = None if quantity is None else quantity.get("観測差分量")
        quantity_ok = bool(quantity is not None and quantity.get("数量基準完全") and B.finite(q) and q >= 0)
        if not quantity_ok:
            reasons.append("数量基準不完全又は不正")
            changes, segment = [], None
        reference = previous
        eligible = price_ok and reference is not None and quantity_ok
        direction = None
        if eligible:
            if segment is None:
                number += 1
                segment = f"{session}_量比区間{number:04d}"
            direction = int(frame["close"] > reference["close"]) - int(frame["close"] < reference["close"])
            changes.append((index, direction, float(q)))
        current_window = changes[-PERIOD:] if eligible else []
        prior_window = changes[-PERIOD - 1:-1] if eligible and len(changes) >= PERIOD + 1 else []
        current, current_amounts, current_n, current_t = ratio_parts(current_window)
        prior, prior_amounts, prior_n, prior_t = ratio_parts(prior_window)
        difference = (current_n * prior_t - prior_n * current_t) / (current_t * prior_t) if current is not None and prior is not None else None
        row = {"場": session, "index": index, "公開時計秒": frame["confirm"], "公開原板行": frame["confirm_line"],
            "価格入力可": price_ok, "数量入力可": quantity_ok, "VR入力可": eligible,
            "比較元足番号": None if reference is None else reference["index"], "分類方向": direction,
            "観測差分量": float(q) if quantity_ok else None, "VR解除理由": reasons,
            "VR区間ID": segment, "VR区間変化数": len(changes), "現窓足番号": [r[0] for r in current_window],
            "前窓足番号": [r[0] for r in prior_window], "現方向別量": current_amounts,
            "前方向別量": prior_amounts, "現前B準備": difference is not None}
        for name, value in (("B現", current), ("B前", prior), ("B差", difference)):
            row[name] = None if value is None else float(value)
            row[name + "分子"] = None if value is None else value.numerator
            row[name + "分母"] = None if value is None else value.denominator
        rows.append(row)
        previous, last_index = frame if price_ok else None, index
    return rows


def select(block: dict) -> dict:
    """旧R0、量比準備、量比方向改善の三段階を同時点で別判定する。

    引数: block(dict)は旧29独立のsignals/frames/quality/input_quality。
    返り値: dictは同じ旧Pの三採否と小型量比。旧共通Mや純時計を変更しない。
    """
    session = block["input_quality"]["場"]
    panels = volume_panels(block["frames"][3], session)
    by_index = {row["index"]: row for row in panels}
    decisions = []
    for raw in block["quality"]["全Q発動記録"]:
        panel = by_index[raw["index"]]
        old, ready = bool(raw["戦略判定"]["R0"]["採用"]), panel["現前B準備"]
        improved = ready and raw["side"] * panel["B差分子"] > 0
        verdicts = {"V0": {"採用": old, "理由": list(raw["戦略判定"]["R0"]["理由"])},
            "V1": {"採用": old and ready, "理由": ["旧R0採用・現前B20準備"] if old and ready else ["旧R0不採用"] if not old else ["現前B20未準備"]},
            "V2": {"採用": old and ready and improved, "理由": ["旧R0採用・量比実方向改善"] if old and ready and improved else
                ["旧R0不採用"] if not old else ["現前B20未準備"] if not ready else ["量比差実方向不成立"]}}
        decisions.append({"場": session, "発動ID": raw["発動ID"], "index": raw["index"], "side": raw["side"],
            "要求時計秒": raw["要求時計秒"], "要求原板行": raw["要求原板行"], "旧R0採用": old,
            "現前B準備": ready, "B差分子": panel["B差分子"], "B差分母": panel["B差分母"], "戦略判定": verdicts})
    by_event = {row["発動ID"]: row for row in decisions}
    selected = {"3分_" + policy: [] for policy in POLICIES}
    for source in block["signals"]["3分_R0"]:
        for policy in POLICIES:
            if by_event[source["発動ID"]]["戦略判定"][policy]["採用"]:
                selected["3分_" + policy].append(pure_signal(source, policy))
    block.update(signals=selected, volume_panels=panels, decisions=decisions)
    return block


# ----------------------------------------
# 旧29の入力と完了証明へbindし、全旧数値/Qは共有、VRの新列だけを保存する。


def rename(value: Any, old: str, new: str) -> Any:
    """候補・入口識別子だけを深い保存値まで変換する。

    引数: value(Any)は保存値、old/new(str)は識別子断片。
    返り値: Anyは全数値/属性/型を保持する比較値。
    """
    if isinstance(value, dict):
        return {key: rename(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [rename(item, old, new) for item in value]
    return value.replace(old, new) if isinstance(value, str) else value


def decision_signal(row: dict) -> dict:
    """ATR原値の限定許容と判断用D整数を分離する。

    引数: row(dict)は純13列。
    返り値: dictはATR以外全列を保持する判断射影。
    """
    value = deepcopy(row)
    atr = value.pop("atr")
    valid = atr is not None and atr > 0
    value["ATR判断"] = {"正有効": valid, "D整数": max(5, math.ceil(atr / 5) * 5) if valid else None}
    return value


def raw_projection(rows: list[dict]) -> list[dict]:
    """旧29原Pの価格/窓/旧M/採否をMACD浮動値と分離する。

    引数: rows(list[dict])は独立29の全原P。
    返り値: list[dict]は旧価格判断の厳密射影。ラベルは含めない。
    """
    fields = ("場", "発動ID", "index", "side", "要求時計秒", "要求原板行", "low", "high", "close",
        "前20足番号", "旧BB下端", "旧BB上端", "共通M準備", "時間条件可", "確認遅延条件可")
    return [{**{key: deepcopy(row[key]) for key in fields}, "旧R0採用": row["戦略判定"]["R0"]["採用"]} for row in rows]


def dependency_pins() -> dict:
    """旧29数値/Qと旧33独立追尾の推移的コード指紋を列挙する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。実行する主36はimportしない。
    """
    paths = {"scripts/OBV反転/状態独立確認.py", "scripts/OBV反転/追尾独立確認.py", "scripts/終値位置/追尾独立確認.py", "scripts/入口探索/独立照合.py"}
    for study in (ENTRY_STUDY, EXIT_STUDY):
        paths.update(name for name in V.read(study / "固定.json")["ファイルSHA256"] if name.endswith(".py"))
    return {name: V.sha(ROOT / name) for name in sorted(paths)}


def references(study: Path, audit: Audit) -> None:
    """旧29正本・完了証明・共有六系列/対照二系列をcache前に検査する。

    引数: study(Path)は36保存先、audit(Audit)は比較先。
    返り値: None。旧証明の成功を新VRの成功と混同しない。
    """
    audit.check("旧29固定anchor", V.sha(ENTRY_STUDY / "固定.json"), ENTRY_LOCK_SHA)
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    artifacts = V.read(ENTRY_STUDY / "作業成果物.json")["ファイル"]
    for filename in ("入口参照.json", "対照参照.json"):
        ref = V.read(study / filename)
        for key, expected in (("参照試行", "00029"), ("旧固定SHA256", ENTRY_LOCK_SHA), ("大明細複製", False)):
            audit.check(filename + key, ref[key], expected)
        audit.check(filename + ":全完了証明", set(ref["文書と証明"]), names)
        for name, item in ref["文書と証明"].items():
            audit.check(filename + name + ":正本", (ROOT / item["パス"]).resolve(), (ENTRY_STUDY / name).resolve())
            audit.check(filename + name + ":SHA", item["SHA256"], V.sha(ENTRY_STUDY / name))
        expected = artifacts if filename == "入口参照.json" else [row for row in artifacts if Path(row["パス"]).name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]
        if filename == "対照参照.json":
            audit.check(filename + ":旧候補", ref["候補ID"], "3分_R0_X0")
        audit.check(filename + ":明細集合", ref["共有明細"], expected)
        for item in expected:
            path = ROOT / item["パス"]
            audit.check(filename + path.name + ":範囲", path.resolve().parent, ENTRY_WORK.resolve())
            audit.check(filename + path.name + ":圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
            audit.check(filename + path.name + ":bytes", path.stat().st_size, item["圧縮バイト"])
    for name, digest in V.read(ENTRY_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("旧29固定現在:" + name, V.sha(ROOT / name), digest)
    for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        proof = V.read(ENTRY_STUDY / name)
        audit.check("旧29完了:" + name, proof["全件一致"], True)
        audit.check("旧29差0:" + name, proof["不一致数"], 0)


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """三入口/四運用・旧継承値・主準備現在版をcache前に確認する。

    引数: study/work(Path)は保存先、audit(Audit)は比較先。
    返り値: tupleは条件/実台帳/主準備/実台帳path。差は入力前に拒否。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    references(study, audit)
    old, exit_config = V.read(ENTRY_STUDY / "条件.json"), V.read(EXIT_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("旧29入口尺度継承:" + key, config[key], old[key])
    for key in ("運用", "必須追尾"):
        audit.check("旧33現在費用継承:" + key, config[key], exit_config[key])
    audit.check("事前三入口", config["戦略"], list(POLICIES))
    audit.check("固定VR期間", config["VR期間"], PERIOD)
    audit.check("事前四組合せ", config["運用組合せ"], [{"戦略": p, "出口ID": x} for p, x in (("V0", "X0"), ("V0", "XF"), ("V1", "XF"), ("V2", "XF"))])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧29R0純登録同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "純信号whitelist": list(SIGNAL_FIELDS)}
    for key, value in expected.items():
        audit.check("主準備:" + key, master[key], value)
    paths = {"scripts/量比反転/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("主/共有/入力の不一致によりcache前停止")
    return config, manifest, master, resolved


def old_references() -> tuple[dict, dict, str]:
    """旧全数値/Qと純R0当時13列だけを保存物から読む。

    引数: なし。
    返り値: tupleは場別旧全足/旧R0純V0射影/全指標展開SHA。準備ではラベル字段を使わない。
    """
    frames, digest = defaultdict(list), hashlib.sha256()
    with gzip.open(ENTRY_WORK / "全指標.jsonl.gz", "rb") as stream:
        for line in stream:
            digest.update(line)
            row = json.loads(line)
            row.pop("期間")
            frames[row["場"]].append(row)
    pure = {}
    with gzip.open(ENTRY_WORK / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["入口ID"] == "3分_R0":
                pure[row["イベントID"]] = pure_signal(row)
    return frames, pure, digest.hexdigest()


def reconstruct(manifest: dict) -> Any:
    """固定29の独立足/Q/中心化MACD/OBVをread再用し、新VRだけ別算する。

    引数: manifest(dict)は既使用66台帳。
    返り値: Anyは場別iterator。private旧全足は照合だけに使い保存しない。
    """
    old = V.read(ENTRY_STUDY / "条件.json")
    for block in G.reconstruct(manifest, old):
        selected = select({"signals": block["純入口"], "frames": block["価格足"], "quality": block["入口品質"], "input_quality": block["入力品質"]})
        signals = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        yield {"場": block["場"], "期間": block["期間"], "純信号": signals,
            "純信号内容SHA256": canonical_sha(signals), "純信号判断SHA256": canonical_sha([decision_signal(row) for row in signals]),
            "量比": selected["volume_panels"], "量比SHA256": canonical_sha(selected["volume_panels"]),
            "採否": selected["decisions"], "採否SHA256": canonical_sha(selected["decisions"]),
            "旧原P判断SHA256": canonical_sha(raw_projection(block["入口品質"]["全Q発動記録"])), "入力品質": block["入力品質"],
            "_旧全足": block["価格足"][3]}


def compare_preparation(main: dict, block: dict, old_frames: dict, old_pure: dict, audit: Audit) -> dict:
    """全旧数値/Q、全新量比/採否と三純集合を同時点で比較する。

    引数: main/block(dict)は主/独立場、old_frames/old_pure(dict)は旧保存出典、audit(Audit)は比較。
    返り値: dictは段階件数と内容SHA。ATR/MACD限定許容を他の値へ広げない。
    """
    session = block["場"]
    audit.check(session + ":旧29全数値/Q/OBV出典", block["_旧全足"], old_frames[session])
    audit.check(session + ":全量比/採否/純leaf/入力", {key: value for key, value in main.items() if key != "純信号内容SHA256"},
        {key: value for key, value in block.items() if not key.startswith("_") and key != "純信号内容SHA256"})
    audit.check(session + ":主生pureSHA", main["純信号内容SHA256"], canonical_sha(main["純信号"]))
    ids = {policy: set() for policy in POLICIES}
    for row in main["純信号"]:
        policy = row["入口ID"].removeprefix("3分_")
        audit.check(row["イベントID"] + ":whitelist", set(row), set(SIGNAL_FIELDS))
        original = row["イベントID"][:-3] + "_R0"
        expected = rename(old_pure.get(original), "_V0", "_" + policy)
        audit.leaf(row["イベントID"] + ":旧R0当時13列完全同値", row, expected, row == expected)
        ids[policy].add(original)
    audit.check(session + ":V0旧R0全集合", ids["V0"], {key for key, row in old_pure.items() if row["場"] == session})
    audit.check(session + ":V1subsetV0", ids["V1"] <= ids["V0"], True)
    audit.check(session + ":V2subsetV1", ids["V2"] <= ids["V1"], True)
    return {"場": session, "期間": block["期間"], **{policy + "登録数": len(ids[policy]) for policy in POLICIES},
        "旧数値足数": len(block["_旧全足"]), "量比足数": len(block["量比"]), "旧原P数": len(block["採否"]),
        "量比SHA256": block["量比SHA256"], "採否SHA256": block["採否SHA256"], "旧原P判断SHA256": block["旧原P判断SHA256"]}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """主独立現在版・共有出典と限定数値許容を共通証明へ保存する。

    引数: study/work/resolved(Path)は保存先/実台帳、master(dict)は主準備、audit(Audit)は記録。
    返り値: dictは全phaseの証明骨格。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": 66, "全66場既使用": True, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json"), "旧29固定SHA256": ENTRY_LOCK_SHA,
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0とD整数厳密"},
        "MACD照合": {"表現差": audit.macd_differences, "符号不一致数": audit.macd_sign_diffs, "許容": "abs1e-10/rel0・符号/採否厳密"},
        "厳密範囲": "旧Q全属性・OBV・価格/窓/公開key/採否・量比全分数/方向/量和/窓/全三判定は厳密。旧ATR/MACDだけ限定許容、VR表示float差へepsilonを追加せず分子で採否。"}


def prepare(study: Path, work: Path) -> dict:
    """root許可後だけ旧全数値/Qと新量比・三採否を非損益で照合する。

    引数: study/work(Path)は36保存先。
    返り値: dictは独立準備証明。先着/新規/運用/PnLは呼ばない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    _, manifest, master, resolved = guarded_inputs(study, work, audit)
    old_frames, old_pure, numeric_sha = old_references()
    reference = next(row for row in V.read(ENTRY_STUDY / "作業成果物.json")["ファイル"] if Path(row["パス"]).name == "全指標.jsonl.gz")
    audit.check("旧全指標展開SHA", numeric_sha, reference["展開内容SHA256"])
    stages = []
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, old_frames, old_pure, audit))
        print(json.dumps({"場": block["場"], "独立準備": "旧29全数値Q/VR分数/三採否", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    total = sum(row["V0登録数"] for row in stages)
    audit.check("旧R0全登録数", total, len(old_pure))
    audit.check("主旧R0登録数", master["旧R0登録数"], total)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "旧29R0純登録同値": audit.mismatches == 0, "旧R0登録数": total, "場別準備": stages,
        "旧全指標展開SHA256": numeric_sha, "旧全数値Q照合足数": sum(row["旧数値足数"] for row in stages),
        "検証範囲": "旧29独立原8列OHLC/Q/中心化MACD/ATR/OBVを再用し保存旧全指標へ全列照合。VRだけDecimal.from_float精密量・全区間スライス和/交差積で別算し、22close/21q・最古q不要・量badclose保持・三採否/時点を全件確認。",
        "限界": "V0旧MはVR準備で除外せず、V0→V1準備、V1→V2方向、X0→XF運用を分離。準備では先着/運用/PnLを計算せず、既使用66場を未見としない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧R0登録数")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 正式は旧同時計ラベルの出典と新選別を検算し、実受付/会計・最初返済要求は別proofへbindする。


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


def normal_columns(entry: dict, manifest: dict) -> dict:
    """元8列の非後退価格時計から正常BBOだけを独立に取り出す。

    引数: entry/manifest(dict)は固定入力行/実台帳。
    返り値: dictはnow/line/bid/ask列。新規や先着の結果を入力選択に使わない。
    """
    data = G.observed(entry, manifest)
    valid = data["valid"].astype(bool)
    if S.np.any(valid & (~S.np.isfinite(data["bid"]) | ~S.np.isfinite(data["ask"]) |
            (data["bid"] <= 0) | (data["ask"] < data["bid"]))):
        raise ValueError("正常BBOフラグと価格が不一致")
    return {key: data[key][valid] for key in ("now", "line", "bid", "ask")}


def label_direct(quotes: dict, signal: dict, cutoff: float, deadline: float) -> dict:
    """正式時だけ旧独立の原列比較で即時新規から125/250を直接検算する。

    引数: quotes/signal(dict)は原正常列/純登録、cutoff/deadline(float)は新規停止/強制。
    返り値: dictはラベル/理由/九数値。+30秒等号可、停止/force等号の新規は不可。
    """
    first = int(S.np.searchsorted(quotes["now"], signal["要求時計秒"] + 1, side="left"))
    if first >= len(quotes["now"]) or quotes["now"][first] > signal["要求時計秒"] + 30 or quotes["now"][first] >= cutoff or quotes["now"][first] >= deadline:
        return {"ラベル": "未約定", "理由": "30秒内に正常板なし", **{key: None for key in LABEL_FIELDS[2:]}}
    return L.label_direct(quotes, signal["要求時計秒"], cutoff, deadline, signal["side"],
        adverse=125, favorable=250, wait=1, ttl=30, allowed_gap=300)


def run(study: Path, work: Path) -> dict:
    """正式結果後に全量比/採否・全最小caseと旧V0X0全属性を確認する。

    引数: study/work(Path)は36正式先/作業先。
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
    names = ("量比", "入口事例", "全運用詳細", "追尾")
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
    audit.check("全4x66", set(pairs), {(row["session"], cid) for row in manifest["entries"] for cid in OPERATIONS})
    case_ids = [row["イベントID"] for row in saved["入口事例"]]
    audit.check("全最小case一意", len(case_ids), len(set(case_ids)))
    stages, controls, label_counts = [], [], {policy: 0 for policy in POLICIES}
    inputs = {row["session"]: row for row in manifest["entries"]}
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, old_frames, old_pure, audit))
        session, period = block["場"], block["期間"]
        audit.check(session + ":正式全量比", grouped["量比"][session], [{"期間": period, **row} for row in block["量比"]])
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(inputs[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for row in block["純信号"]:
            policy = row["入口ID"].removeprefix("3分_")
            original = row["イベントID"][:-3] + "_R0"
            old = old_cases[original]
            expected = {**deepcopy(row), "期間": period, "要求時計JST": old["要求時計JST"],
                "旧R0イベントID": original, **{key: old[key] for key in LABEL_FIELDS}}
            audit.check(row["イベントID"] + ":最小case/旧同時計先着全11列", cases.get(row["イベントID"]), expected)
            case = cases.get(row["イベントID"])
            audit.check(row["イベントID"] + ":原正常BBO直接先着全11列",
                None if case is None else {key: case[key] for key in LABEL_FIELDS}, label_direct(quotes, row, cutoff, deadline))
            label_counts[policy] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] != "3分_V0_X0":
                continue
            trace = [row for row in grouped["追尾"][session] if row["候補ID"] == detail["候補ID"]]
            adapted, adapted_trace = rename(detail, "_V0", "_R0"), rename(trace, "_V0", "_R0")
            audit.leaf(session + ":旧R0X0全ledger完全同値", adapted, old_details[session], adapted == old_details[session])
            audit.leaf(session + ":旧R0X0全trace完全同値", adapted_trace, old_trace[session], adapted_trace == old_trace[session])
            controls.append({"場": session, "候補ID": detail["候補ID"], "全運用同値": adapted == old_details[session],
                "全追尾同値": adapted_trace == old_trace[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                "旧識別子追尾内容SHA256": canonical_sha(adapted_trace)})
        print(json.dumps({"場": session, "独立状態": "旧全数値Q/量比/採否/同時計case/V0対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 4, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("全case数", len(saved["入口事例"]), sum(label_counts.values()))
    audit.check("V0旧全R0数", label_counts["V0"], len(old_pure))
    audit.check("V0保存対照証明", V.read(study / "V0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages,
        "旧R0登録数": label_counts["V0"], "旧同時計先着引用照合数": sum(label_counts.values()), "方針別case数": label_counts,
        "全先着直接照合件数": sum(label_counts.values()), "方針別先着直接照合件数": label_counts,
        "旧29全属性同値場数": len(controls), "旧全指標展開SHA256": numeric_sha,
        "旧全数値Q照合足数": sum(row["旧数値足数"] for row in stages),
        "保存量比数": len(saved["量比"]), "保存入口事例数": len(saved["入口事例"]), "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()}, "共有入口事例展開SHA256": old_case_sha,
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"), "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列から旧29独立OHLC/Q/中心化MACD/ATR/OBVを再構成して旧保存全足へ全列比較。新VRは精密スライス和/交差積で全panel・原P三採否・純13列を別算し、同時点subset/準備効果を分離。全V0/V1/V2caseは原正常BBOの+1秒/TTL30/停止/forceと125250/gap/期限を直接列比較し、旧R0の同登録・同時計11label列の出典同値も別確認。V0X0は旧29全66ledger/traceの識別子以外全属性同値。",
        "限界": "新規受付/代理約定/Decimalは別財務へSHA接続。全保有X0/XF線と最初返済要求は別追尾。VR表示floatで採否を決めず、新たな待機や入口価格を作らない。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧R0登録数", "旧29全属性同値場数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可後の非損益準備又は固定後状態監査だけを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00036量比方向の独立確認")
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
