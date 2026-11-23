"""00034の固定C0登録と指値代理の新規・125/250先着を原価格列から独立確認する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00034_CCI突破の水準指値"
WORK = ROOT / "work/突破指値/00034"
ENTRY_STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
ENTRY_WORK = ROOT / "work/CCI突破/00031"
CONTROL_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
CONTROL_WORK = ROOT / "work/終値位置/00033"
POLICIES = ("E0", "E1")
OPERATIONS = ("3分_E0_XF", "3分_E1_XF")
BASE_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
SIGNAL_FIELDS = {"E0": BASE_FIELDS, "E1": BASE_FIELDS + ("新規指値価格", "指値根拠")}
RESULT_NUMBERS = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
    "判定気配", "最大順行pt", "最大逆行pt", "所要分")
OLD_LOCK_SHA = "b1a8cc4aec9def6907f65e0372ad8d280d62390e8059e83c1f38d6c927615cce"
OLD_CONDITION_SHA = "8d4cd04e02e26144f16375dea7e722fb84f7f6384a75606b925f1ea792d9ded1"
CONTROL_LOCK_SHA = "7067c992e7751e91044ef2aea7d29845b1308683d9a2227fbafaed340124e721"


def helper(path: Path, name: str) -> Any:
    """固定済みの独立足・入口・照合補助だけを読む。

    引数: path (Path) は旧独立補助、name (str) は識別名。
    返り値: Any はモジュール。34主入口・区間木・運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


G = helper(ROOT / "scripts/CCI突破/状態独立確認.py", "突破指値の固定31独立原足")
B, S, V, P = G.B, G.S, G.V, G.P
Audit = G.Audit


def canonical_sha(value: Any) -> str:
    """JSON安全な値を正規内容SHAへ写す。

    引数: value (Any) は保存値。
    返り値: str はUTF-8正規JSONのSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def pure_signal(row: dict, policy: str | None = None) -> dict:
    """既知の基礎列だけを新しい当時情報辞書へ写す。

    引数: row (dict) は純信号又は比較用旧case、policy (str|None) はE0/E1。
    返り値: dict は明示列の深複写。仮約定・先着・未来価格を渡さない。
    """
    names = BASE_FIELDS if policy is None else SIGNAL_FIELDS[policy]
    return {name: deepcopy(row.get(name)) if name == "bb_mean" else deepcopy(row[name]) for name in names}


def decision_signal(row: dict) -> dict:
    """ATR浮動値だけを正有効性とD整数へ明示分離する。

    引数: row (dict) は全leafを別比較する純信号。
    返り値: dict はATR判断以外の全列を保持した厳密判断射影。
    """
    output = deepcopy(row)
    atr = output.pop("atr")
    valid = B.finite(atr) and atr > 0
    output["ATR判断"] = {"正有効": valid, "Dpt整数": max(5, math.ceil(atr / 5) * 5) if valid else None}
    return output


# ----------------------------------------
# 過去20高安・足番号・公開keyは登録時に固定し、後続足で改訂しない。

def registration(row: dict) -> dict:
    """独立再構成の原C0採用足から価格窓の登録出典を作る。

    引数: row (dict) は固定31独立の原価格発動。
    返り値: dict はATR重複なしの価格/窓/時点出典。
    """
    if row["side"] not in (-1, 1) or not row["戦略判定"]["C0"]["採用"]:
        raise ValueError("C0採用原足だけを登録します")
    indices = list(row["前20足番号"])
    if len(indices) != 20 or indices[-1] >= row["index"]:
        raise ValueError("当足より前の20本窓が必要です")
    return {"旧C0イベントID": row["発動ID"] + "_C0", "場": row["場"], "登録足番号": row["index"],
        "足終了時計秒": row["足終了時計秒"], "公開時計秒": row["要求時計秒"], "公開原板行": row["要求原板行"],
        "前20足番号": indices, "前20最高H": row["直前最高H"], "前20最安L": row["直前最安L"],
        "当足終値": row["close"], "実side": row["side"]}


def select(block: dict) -> dict:
    """同じ純C0全登録を即時E0/固定境界指値E1へ射影する。

    引数: block (dict) はquality/signalsを持つ非損益材料。
    返り値: dict は同集合二案と全登録出典。CCI/ATR/要求時計を取り直さない。
    """
    anchors = {}
    for row in block["quality"]["全Q発動記録"]:
        if row["戦略判定"]["C0"]["採用"]:
            source = registration(row)
            if source["旧C0イベントID"] in anchors:
                raise ValueError("登録IDが重複")
            anchors[source["旧C0イベントID"]] = source
    original = block["signals"]["3分_C0"]
    if set(anchors) != {row["イベントID"] for row in original} or len(anchors) != len(original):
        raise ValueError("純C0と登録全集合が不一致")
    selected = {"3分_" + policy: [] for policy in POLICIES}
    for row in original:
        source = anchors[row["イベントID"]]
        for policy in POLICIES:
            signal = pure_signal(row)
            signal["イベントID"] = row["イベントID"][:-3] + "_" + policy
            signal["入口ID"] = "3分_" + policy
            if policy == "E1":
                signal["新規指値価格"] = source["前20最高H"] if row["side"] == 1 else source["前20最安L"]
                signal["指値根拠"] = deepcopy(source)
            selected["3分_" + policy].append(signal)
    block["signals"], block["registrations"] = selected, list(anchors.values())
    return block


def normal_columns(entry: dict, manifest: dict) -> dict:
    """元8列の独立時計選択から正常BBOだけを原行順へ取り出す。

    引数: entry/manifest (dict) は固定入力行/実台帳。
    返り値: dict はnow/line/bid/askの独立配列。新しい原板を探索しない。
    """
    data = G.observed(entry, manifest)
    valid = data["valid"].astype(bool)
    if S.np.any(valid & (~S.np.isfinite(data["bid"]) | ~S.np.isfinite(data["ask"]) |
            (data["bid"] <= 0) | (data["ask"] < data["bid"]))):
        raise ValueError("正常フラグと気配が矛盾")
    return {name: data[name][valid] for name in ("now", "line", "bid", "ask")}


# ----------------------------------------
# 先着は区間木を使わず、純登録ごとに独立の仮注文を直接価格列で走査する。

def entry_index(quotes: dict, signal: dict, cutoff: float, policy: str, deadline: float | None = None) -> int | None:
    """+1秒からTTL30秒等号内の最初の即時/指値成立BBOを直接選ぶ。

    引数: quotes (dict) は正常価格列、signal (dict) は純登録、cutoff (float) は新規停止、policy (str) はE0/E1、deadline (float|None) は期限。
    返り値: int|None は原行順の最初位置。停止等号とTTL超過は候補にしない。
    """
    if policy not in POLICIES or signal["side"] not in (-1, 1):
        raise ValueError("E0/E1と売買符号だけ")
    start, end = signal["要求時計秒"] + 1, signal["要求時計秒"] + 30
    now = S.np.asarray(quotes["now"])
    allowed = (now >= start) & (now <= end) & (now < cutoff)
    if deadline is not None:
        allowed &= now < deadline
    if policy == "E1":
        prices = S.np.asarray(quotes["ask"] if signal["side"] == 1 else quotes["bid"])
        allowed &= prices <= signal["新規指値価格"] if signal["side"] == 1 else prices >= signal["新規指値価格"]
    positions = S.np.flatnonzero(allowed)
    return int(positions[0]) if len(positions) else None


def label_direct(quotes: dict, signal: dict, cutoff: float, deadline: float, policy: str) -> dict:
    """仮新規BBOを起点に全返済列を走査して125/250の最初到達を求める。

    引数: quotes/signal (dict) は原正常列/純登録、cutoff/deadline (float) は停止/評価期限、policy (str) はE0/E1。
    返り値: dict は旧形式のラベル/理由/九数値。約定前の値動きを順逆行へ算入しない。
    """
    first = entry_index(quotes, signal, cutoff, policy, deadline)
    empty = {"ラベル": "未約定", "理由": "30秒内に正常板なし" if policy == "E0" else "30秒内に指値成立正常BBOなし",
        **{name: None for name in RESULT_NUMBERS}}
    if first is None:
        return empty
    now = S.np.asarray(quotes["now"])
    if deadline < now[first]:
        raise ValueError("仮新規より前の評価期限")
    side = signal["side"]
    entered = float(quotes["ask"][first] if side == 1 else quotes["bid"][first])
    marks = S.np.asarray(quotes["bid"] if side == 1 else quotes["ask"])
    in_time = S.np.flatnonzero(now[first:] <= deadline)
    last = first + int(in_time[-1])
    distances = side * (marks[first:last + 1] - entered)
    crossings = S.np.flatnonzero((distances <= -125) | (distances >= 250))
    hit = first + int(crossings[0]) if len(crossings) else None
    gaps = S.np.flatnonzero((S.np.diff(now[first:]) > 300) & (now[first:-1] + 300 < deadline))
    gap_left = first + int(gaps[0]) if len(gaps) else None
    if hit is not None and (gap_left is None or hit <= gap_left):
        last = hit
        label, reason = ("順行先着" if side * (float(marks[last]) - entered) >= 250 else "逆行先着"), "返済気配の閾値初着"
    else:
        if gap_left is not None:
            last = gap_left
        stale = deadline - now[last] > 300
        if gap_left is not None or stale:
            label, reason = "観測不足", "正常板価格時計300秒超空白"
        elif now[-1] < deadline:
            label, reason = "観測不足", "入力末尾不足"
        else:
            label, reason = "期限未達", "期限内どちらも未到達"
    observed = side * (marks[first:last + 1] - entered)
    return {"ラベル": label, "理由": reason, "新規価格": entered,
        "新規時計秒": float(now[first]), "新規原板行": int(quotes["line"][first]),
        "判定時計秒": float(now[last]), "判定原板行": int(quotes["line"][last]), "判定気配": float(marks[last]),
        "最大順行pt": float(max(0, S.np.max(observed))), "最大逆行pt": float(max(0, -S.np.min(observed))),
        "所要分": float((now[last] - now[first]) / 60)}


# ----------------------------------------
# 固定31の当時属性と証明だけを共有し、旧大明細を新試行へ複製しない。

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

    引数: study (Path) は34正式先、audit (Audit) は比較記録。
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
# 指値以外の運用値と旧33対照を原cacheへ進む前に固定出典へ接続する。

def dependency_pins() -> dict:
    """旧独立足と固定33独立費用追尾の推移的な現在指紋を列挙する。

    引数: なし。
    返り値: dict[str,str] はROOT相対pathとSHA。34主を読み込まない。
    """
    paths = {"scripts/CCI突破/状態独立確認.py", "scripts/終値位置/状態独立確認.py", "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**G.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))


def rename(value: Any, old: str, new: str) -> Any:
    """比較用の候補・イベント識別子だけを再帰変換する。

    引数: value (Any) はJSON保存値、old/new (str) はID断片。
    返り値: Any は全数値・型・属性を保持する新しい比較値。
    """
    if isinstance(value, dict):
        return {key: rename(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [rename(item, old, new) for item in value]
    return value.replace(old, new) if isinstance(value, str) else value


def control_reference(study: Path, audit: Audit) -> dict:
    """旧33T0_XFの正本・全証明と二圧縮明細を原cache前に検査する。

    引数: study (Path) は34保存先、audit (Audit) は記録。
    返り値: dict は対照参照。旧損益の再計算や旧明細の複製はしない。
    """
    pointer = V.read(study / "対照参照.json")
    for key, expected in {"参照試行": "00033", "候補ID": "3分_T0_XF", "全66場既使用": True,
            "大明細複製": False, "旧固定SHA256": CONTROL_LOCK_SHA}.items():
        audit.check("対照参照:" + key, pointer[key], expected)
    audit.check("旧33固定anchor", V.sha(CONTROL_STUDY / "固定.json"), CONTROL_LOCK_SHA)
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    audit.check("旧33全証明集合", set(pointer["文書と証明"]), names)
    for name, item in pointer["文書と証明"].items():
        path = CONTROL_STUDY / name
        audit.check("旧33証明正本:" + name, (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check("旧33証明SHA:" + name, item["SHA256"], V.sha(path))
    for name, digest in V.read(CONTROL_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("旧33固定現在:" + name, V.sha(ROOT / name), digest)
    expected = [row for row in V.read(CONTROL_STUDY / "作業成果物.json")["ファイル"]
        if Path(row["パス"]).name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]
    audit.check("旧33二明細宣言", pointer["共有明細"], expected)
    audit.check("旧33二明細数", len(expected), 2)
    for item in expected:
        path = ROOT / item["パス"]
        audit.check("旧33明細範囲:" + path.name, path.resolve().parent, CONTROL_WORK.resolve())
        audit.check("旧33明細圧縮SHA:" + path.name, V.sha(path), item["圧縮SHA256参考"])
        audit.check("旧33明細bytes:" + path.name, path.stat().st_size, item["圧縮バイト"])
    for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        proof = V.read(CONTROL_STUDY / name)
        audit.check("旧33完了:" + name, proof["全件一致"], True)
        audit.check("旧33差0:" + name, proof["不一致数"], 0)
    return pointer


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """主準備の版と指値以外の数値を固定31/33へ結び付ける。

    引数: study/work (Path) は34保存先、audit (Audit) は記録。
    返り値: tuple は条件/実台帳/主準備/解決台帳。差があればcache前停止。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    entry_reference(study, audit)
    control_reference(study, audit)
    previous = V.read(CONTROL_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
            "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("固定33継承:" + key, config[key], previous[key])
    audit.check("固定33XF追尾", config["必須追尾"], {key: value for key, value in previous["必須追尾"].items() if key != "旧X0起動幅pt"})
    audit.check("新二方針", config["戦略"], list(POLICIES))
    audit.check("XF一出口", config["出口"], [{"出口ID": "XF"}])
    for name, base in (("入口条件参照", ENTRY_STUDY), ("運用条件参照", CONTROL_STUDY)):
        audit.check(name + ":正本", (study / config[name]["パス"]).resolve(), (base / "条件.json").resolve())
        audit.check(name + ":SHA", config[name]["SHA256"], V.sha(base / "条件.json"))
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧31C0純登録同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"),
        "純信号whitelist": {policy: list(names) for policy, names in SIGNAL_FIELDS.items()}}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/突破指値/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主準備66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("主/共有/対照の不一致によりcache前停止")
    return config, manifest, master, resolved


def reconstruct(manifest: dict) -> Any:
    """原8列から独立C0全採否と固定R/Lを再構成する。

    引数: manifest (dict) は既使用66場台帳。
    返り値: Any はラベル/PnLなしの場別準備iterator。大きい全指標列は保存しない。
    """
    old = V.read(ENTRY_STUDY / "条件.json")
    for block in G.reconstruct(manifest, old):
        selected = select({"quality": block["入口品質"], "signals": block["純入口"]})
        signals = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        anchors = selected["registrations"]
        yield {"場": block["場"], "期間": block["期間"], "純信号": signals,
            "純信号内容SHA256": canonical_sha(signals), "純信号判断SHA256": canonical_sha([decision_signal(row) for row in signals]),
            "登録台帳": anchors, "登録内容SHA256": canonical_sha(anchors),
            "原P判定SHA256": canonical_sha(raw_projection(block["入口品質"]["全Q発動記録"])), "入力品質": block["入力品質"]}


def compare_preparation(main: dict, block: dict, saved: dict, audit: Audit) -> dict:
    """全登録・純信号leafと厳密判断SHAを比較し、双方の元C0全集合を検査する。

    引数: main/block (dict) は主/独立場、saved (dict) は旧31当時射影、audit (Audit) は記録。
    返り値: dict は小型場別証明。ATR原floatの全文同一とは主張しない。
    """
    session = block["場"]
    audit.check(session + ":全登録/原P/判断/入力/純leaf", {key: value for key, value in main.items() if key != "純信号内容SHA256"},
        {key: value for key, value in block.items() if key != "純信号内容SHA256"})
    audit.check(session + ":主生pure出典SHA", main["純信号内容SHA256"], canonical_sha(main["純信号"]))
    ids = {policy: set() for policy in POLICIES}
    for row in main["純信号"]:
        policy = row["入口ID"].removeprefix("3分_")
        audit.check(row["イベントID"] + ":二方針内", policy in POLICIES, True)
        if policy not in POLICIES:
            continue
        audit.check(row["イベントID"] + ":whitelist", set(row), set(SIGNAL_FIELDS[policy]))
        original = rename(pure_signal(row), "_" + policy, "_C0")
        expected = saved.get(original["イベントID"])
        audit.leaf(row["イベントID"] + ":旧C0基礎13列完全同値", original, expected, original == expected)
        ids[policy].add(original["イベントID"])
    for policy in POLICIES:
        audit.check(session + ":" + policy + "元C0全集合", ids[policy], {key for key, row in saved.items() if row["場"] == session})
    audit.check(session + ":二純登録同集合", ids["E0"], ids["E1"])
    return {"場": session, "期間": block["期間"], "原C0登録数": len(block["登録台帳"]),
        "E0純信号数": len(ids["E0"]), "E1純信号数": len(ids["E1"]),
        "主生純信号内容SHA256": main["純信号内容SHA256"], "独立純信号判断SHA256": block["純信号判断SHA256"],
        "登録内容SHA256": block["登録内容SHA256"], "原P判定SHA256": block["原P判定SHA256"]}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """主独立の現在版・台帳・旧証明とATRの限定許容を保存する。

    引数: study/work/resolved (Path) は保存先/実台帳、master (dict) は主準備、audit (Audit) は記録。
    返り値: dict は共通proof。指値価格/出典/時計/採否は厳密。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": 66, "全66場既使用": True, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json"),
        "旧31固定SHA256": OLD_LOCK_SHA, "旧33固定SHA256": CONTROL_LOCK_SHA,
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/D整数厳密"},
        "厳密範囲": "登録価格/前20窓/公開key/side/基礎採否と新先着全数値は厳密。独立ATRは全leafを限定許容/D整数で別照合し判断SHAへ投影。主生pureの旧31完全一致を別出典bind"}


def prepare(study: Path, work: Path) -> dict:
    """root許可後だけ全66の純登録/指値出典を主非損益準備へ照合する。

    引数: study/work (Path) は34保存先。
    返り値: dict は小型独立準備証明。新先着・約定・PnLは呼ばない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    saved_rows = shared_signals()
    saved = {row["イベントID"]: row for row in saved_rows}
    audit.check("旧C0当時属性一意", len(saved), len(saved_rows))
    stages = []
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, saved, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原C0/同登録801/固定R-L", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    total = sum(row["原C0登録数"] for row in stages)
    audit.check("元C0全登録数", total, len(saved))
    audit.check("主全登録数", master["原C0登録数"], total)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "旧31C0純登録同値": audit.mismatches == 0, "原C0登録数": total, "場別準備": stages,
        "検証範囲": "原8列から独立31の3/15分足・CCI・上位BB公開M・全原P採否を再構成し、C0全登録をE0/E1同集合へ写す。R/L/窓/登録keyを厳密照合し、元ATRと明示判断射影/旧31pure13列の出典同一を分離。",
        "限界": "先着/注文/実運用/損益は準備で計算しない。既使用66場の開発内検算で未見評価ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "原C0登録数")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 正式では全1602仮caseを直接列走査し、実運用の単一pendingとは分離する。

def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """独立準備・固定と現在コードのbindを正式原価格走査前に確認する。

    引数: study/work/resolved (Path) は保存先/実台帳、master (dict) は主準備、audit (Audit) は記録。
    返り値: None。未完・古版・出典変更は以後の検算を拒否する。
    """
    prepared = V.read(work / "独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json"), "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins()}
    for name, value in expected.items():
        audit.check("独立準備bind:" + name, prepared[name], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版の不一致によりcache前停止")


def run(study: Path, work: Path) -> dict:
    """正式完了後に原登録・全新先着・旧E0対照の全属性を独立確認する。

    引数: study/work (Path) は34保存先。
    返り値: dict は状態/直接先着証明。新規受入の単一pendingとPnLは別会計へ分ける。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけ起動できます")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    names = ("入口事例", "全運用詳細", "追尾")
    records, hashes, grouped = {}, {}, {}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("正式3系列宣言", set(artifacts), {name + ".jsonl.gz" for name in names})
    sessions = {row["session"] for row in manifest["entries"]}
    for name in names:
        path = work / (name + ".jsonl.gz")
        records[name], hashes[name] = B.compressed_rows(path)
        item = artifacts[path.name]
        audit.check("新正本path:" + name, (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check("新展開SHA:" + name, hashes[name], item["展開内容SHA256"])
        audit.check("新圧縮SHA:" + name, V.sha(path), item["圧縮SHA256参考"])
        audit.check("新圧縮bytes:" + name, path.stat().st_size, item["圧縮バイト"])
        mapping = defaultdict(list)
        for row in records[name]:
            audit.check("新成果物場範囲:" + name, row["場"] in sessions, True)
            mapping[row["場"]].append(row)
        grouped[name] = mapping
    old_cases, old_case_sha = B.compressed_rows(ENTRY_WORK / "入口事例.jsonl.gz")
    old_cases = {row["イベントID"]: row for row in old_cases if row["入口ID"] == "3分_C0"}
    saved = {key: pure_signal(row) for key, row in old_cases.items()}
    old_details, _ = B.compressed_rows(CONTROL_WORK / "全運用詳細.jsonl.gz")
    old_logs, _ = B.compressed_rows(CONTROL_WORK / "追尾.jsonl.gz")
    control_map = {row["場"]: row for row in old_details if row["候補ID"] == "3分_T0_XF"}
    control_trace = defaultdict(list)
    for row in old_logs:
        if row["候補ID"] == "3分_T0_XF":
            control_trace[row["場"]].append(row)
    input_rows = V.read(study / "入力品質.json")
    inputs = {row["場"]: row for row in input_rows}
    audit.check("正式入力品質66場", len(input_rows), 66)
    audit.check("正式入力品質場集合", set(inputs), sessions)
    pairs = [(row["場"], row["候補ID"]) for row in records["全運用詳細"]]
    audit.check("全2x66一意", len(pairs), len(set(pairs)))
    audit.check("全2x66集合", set(pairs), {(session, cid) for session in sessions for cid in OPERATIONS})
    case_ids = [row["イベントID"] for row in records["入口事例"]]
    audit.check("全新case一意", len(case_ids), len(set(case_ids)))
    stages, controls, label_counts = [], [], {policy: 0 for policy in POLICIES}
    paired = {"E1約定E0未約定数": 0, "指値約定時刻逆転数": 0, "指値新規不利価格数": 0}
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        session, period = block["場"], block["期間"]
        stages.append(compare_preparation(main, block, saved, audit))
        audit.check(session + ":入力品質", inputs[session], {"期間": period, **block["入力品質"]})
        entry = next(row for row in manifest["entries"] if row["session"] == session)
        quotes = normal_columns(entry, manifest)
        _, _, cutoff, deadline = S.G.times(session)
        anchors = {row["旧C0イベントID"]: row for row in block["登録台帳"]}
        expected_cases, by_original = [], defaultdict(dict)
        for signal in block["純信号"]:
            policy = signal["入口ID"].removeprefix("3分_")
            original = signal["イベントID"][:-3] + "_C0"
            label = label_direct(quotes, signal, cutoff, deadline, policy)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "旧C0イベントID": original, "登録出典": deepcopy(anchors[original]), **label}
            expected_cases.append(expected)
            label_counts[policy] += 1
            by_original[original][policy] = label
        audit.check(session + ":全新case数", len(grouped["入口事例"][session]), len(expected_cases))
        for actual, expected in zip(grouped["入口事例"][session], expected_cases):
            audit.check(expected["イベントID"] + ":直接列全先着/登録", actual, expected)
            if expected["入口ID"] == "3分_E0":
                core = {**rename(pure_signal(actual), "_E0", "_C0"),
                    **{name: actual[name] for name in ("ラベル", "理由", *RESULT_NUMBERS)}}
                old = old_cases[actual["旧C0イベントID"]]
                previous = {**pure_signal(old), **{name: old[name] for name in ("ラベル", "理由", *RESULT_NUMBERS)}}
                audit.leaf(expected["イベントID"] + ":旧31の13列と先着全属性同値", core, previous, core == previous)
        for original, pair in by_original.items():
            left, right = pair["E0"], pair["E1"]
            filled_left, filled_right = left["新規価格"] is not None, right["新規価格"] is not None
            paired["E1約定E0未約定数"] += int(filled_right and not filled_left)
            audit.check(original + ":指値仮約定subset", not filled_right or filled_left, True)
            if filled_right and filled_left:
                side = anchors[original]["実side"]
                later = (right["新規時計秒"], right["新規原板行"]) >= (left["新規時計秒"], left["新規原板行"])
                improved = side * (left["新規価格"] - right["新規価格"]) >= 0
                paired["指値約定時刻逆転数"] += int(not later)
                paired["指値新規不利価格数"] += int(not improved)
                audit.check(original + ":指値仮新規後続key", later, True)
                audit.check(original + ":指値仮新規非不利", improved, True)
        details = grouped["全運用詳細"][session]
        audit.check(session + ":二運用集合", {row["候補ID"] for row in details}, set(OPERATIONS))
        for detail in details:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] != "3分_E0_XF":
                continue
            trace = [row for row in grouped["追尾"][session] if row["候補ID"] == "3分_E0_XF"]
            adapted, adapted_trace = rename(detail, "_E0", "_T0"), rename(trace, "_E0", "_T0")
            audit.leaf(session + ":旧33全運用完全同値", adapted, control_map[session], adapted == control_map[session])
            audit.leaf(session + ":旧33全追尾完全同値", adapted_trace, control_trace[session], adapted_trace == control_trace[session])
            controls.append({"場": session, "候補ID": "3分_E0_XF", "全運用同値": adapted == control_map[session],
                "全追尾同値": adapted_trace == control_trace[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                "旧識別子追尾内容SHA256": canonical_sha(adapted_trace)})
        print(json.dumps({"場": session, "独立状態": "全原登録/直接先着/旧33対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    total = sum(row["原C0登録数"] for row in stages)
    audit.check("新全2case数", len(records["入口事例"]), total * 2)
    for policy in POLICIES:
        audit.check(policy + ":全原登録先着数", label_counts[policy], total)
    result = V.read(study / "結果.json")
    for name, expected in {"全66場既使用": True, "入口評価数": 2, "運用候補数": 2, "現方針運用候補数": 2,
            "入口125250評価の変更": True, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + name, result[name], expected)
    audit.check("E0保存対照証明", V.read(study / "E0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages,
        "原C0登録数": total, "全先着直接照合件数": sum(label_counts.values()), "方針別先着直接照合件数": label_counts,
        "仮新規対応不変条件": paired, "旧E0先着同値数": label_counts["E0"], "旧33全属性同値場数": len(controls),
        "保存入口事例数": len(records["入口事例"]), "保存運用詳細数": len(records["全運用詳細"]), "保存追尾数": len(records["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(records[name])} for name in names},
        **{name + "展開SHA256": value for name, value in hashes.items()}, "共有入口事例展開SHA256": old_case_sha,
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "元8列から独立31の原足/数値/M/CCI/登録時計とR/Lを再構成。新E0/E1の全仮登録を各々独立の+1～30秒指値/即時として原正常価格列で直接評価し、約定以降125/250・gap/期限・全新caseを照合。E0基礎13列/先着は旧31、実全ledger/trace66群は旧33と識別子以外除外なしの完全同値。",
        "限界": "純先着に実運用の単一pending/建玉抑止を混ぜない。新規受入/実最初指値約定/会計は別財務、現在費用後strict正・全追尾線・最初返済要求は別追尾監査。価格改善と待機時点・未約定集合は同時に変わり価格だけの因果効果ではない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "全先着直接照合件数", "旧33全属性同値場数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可後の非損益準備又は固定後正式監査だけを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定と不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00034固定C0登録と直接指値先着の独立確認")
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
