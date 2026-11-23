"""00039の固定H0純入口と、原8列からの上位現前J・公開時点を独立照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00039_外側継続と上位基準線の進行"
WORK = ROOT / "work/上位中心継続/00039"
ENTRY_STUDY = ROOT / "study/00038_外側継続と上位の現在雲"
ENTRY_WORK = ROOT / "work/上位雲継続/00038"
UPPER_STUDY = ROOT / "study/00028_基準線復帰と上位一目の方向"
UPPER_WORK = ROOT / "work/一目基準線/00028"
LOWER_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
LOWER_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("J0", "J1", "J2")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)


def helper(path: Path, name: str) -> Any:
    """固定された独立原足・一目・先着補助をCLI起動せず読む。

    引数: path(Path)は独立コード、name(str)は読込識別子。
    返り値: Anyは独立補助。39主入口・運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/上位雲継続/状態独立確認.py", "上位中心継続の固定38独立共通補助")
G, B, S, V = Y.G, Y.B, Y.S, Y.V
N = G.B
Audit = N.Audit
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = Y.SIGNAL_FIELDS, Y.LABEL_FIELDS, N.SOURCE_FIELDS
ICHI_FIELDS = tuple(N.ICHI_NAMES.values())
UPPER_FIELDS = ("場", *SOURCE_FIELDS, *ICHI_FIELDS, "雲計算元足", "一目数値入力可", "一目準備済",
    "一目公開可", "一目窓本数", "銀行解除理由")
canonical_sha, rename = Y.canonical_sha, Y.rename
decision_signal, normal_columns, label_direct = Y.decision_signal, Y.normal_columns, Y.label_direct


def pure_signal(row: dict, policy: str = "J0") -> dict:
    """固定38H0から識別子以外を変えず、順行の純13列だけを取り出す。

    引数: row(dict)は固定38H0純入口、policy(str)はJ0/J1/J2。
    返り値: dictは当時情報だけの辞書。旧caseのラベル・損益を射影しない。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] != "順行":
        raise ValueError("順行の三候補だけです")
    if row["入口ID"] != "3分_H0" or not row["イベントID"].endswith("_H0"):
        raise ValueError("固定38H0の識別子が必要です")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示が不一致")
    value = deepcopy({key: row.get(key) if key == "bb_mean" else row[key] for key in SIGNAL_FIELDS})
    origin = value["イベントID"][:-3]
    value.update(イベントID=origin + "_" + policy, 入口ID="3分_" + policy)
    return value


def upper_projection(row: dict | None) -> dict | None:
    """一目の上位出典と使用数値だけを新しい辞書へ限定射影する。

    引数: row(dict|None)は固定28の数値足又は独立再構成足。
    返り値: dict|Noneは未使用のATR/Stoch/Fastを含まない上位投影。
    """
    if row is not None and row["minutes"] != 15:
        raise ValueError("上位は15分だけです")
    return None if row is None else deepcopy({key: row[key] for key in UPPER_FIELDS})


class NumericHistory:
    """固定28の高安窓別走査を、15分の一目投影へ限定してread再用する。"""

    def __init__(self, minutes: int = 15) -> None:
        """15分だけの独立銀行を作る。

        引数: minutes(int)は15。
        返り値: None。旧P/MACD/数量Mは再構成しない。
        """
        if minutes != 15:
            raise ValueError("上位一目は15分だけです")
        self.bank = N.NumericHistory(15)

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """元OHLCから一目を別走査し、未使用系列を除いて返す。

        引数: frames(list[dict])は独立15分OHLC、session(str)は場、contract(tuple)は限月、tail_missing(int)は尾部欠枠。
        返り値: tuple[list[dict],dict]は限定数値と固定28の銀行品質。NPの内部更新と局所公開を分ける。
        """
        rows, quality = self.bank.build(frames, session, contract, tail_missing)
        return [upper_projection(row) for row in rows], quality


# ----------------------------------------
# 元H0の13列は38証明へ接続し、新しい上位ペア/asof/厳密進行を別実装する。


def classification(upper: dict | None, side: int) -> tuple[bool, list[str], str, str]:
    """準備不足と雲位置を分け、転換基準の関係は診断だけにする。

    引数: upper(dict|None)は最新公開上位、side(int)は実方向。
    返り値: tuple[bool,list[str],str,str]は準備/理由/雲/TJの診断。
    """
    if upper is None:
        return False, ["当場公開15分なし"], "未準備", "未準備"
    tj, cloud = "未準備", "未準備"
    tenkan, kijun = upper["ichimoku_tenkan"], upper["ichimoku_kijun"]
    if N.finite(tenkan) and N.finite(kijun):
        tj = "等号" if tenkan == kijun else "同方向" if (tenkan > kijun) == (side > 0) else "逆方向"
    ready = bool(upper["一目公開可"] and all(N.finite(upper[name]) for name in
        ("ichimoku_tenkan", "ichimoku_kijun", "cloud_upper", "cloud_lower")))
    if ready:
        close, lower, higher = upper["close"], upper["cloud_lower"], upper["cloud_upper"]
        if not N.finite(close) or lower > higher:
            raise ValueError("公開上位の価格又は雲上下端が不正")
        if close == lower or close == higher:
            cloud = "等号"
        elif lower < close < higher:
            cloud = "内"
        elif (close > higher) == (side > 0):
            cloud = "実方向外"
        else:
            cloud = "逆方向外"
    return ready, [] if ready else ["当場最新公開15分一目未準備"], cloud, tj


def pair_state(current: dict | None, previous: dict | None, lower: dict, side: int) -> dict:
    """雲準備を使わず現前Jの有効性を列挙し、分数の交差積で差を別算する。

    引数: current/previous(dict|None)は当時利用可能な現前15分、lower(dict)は下位出典、side(int)は実方向。
    返り値: dictはペア準備/全理由/現前J/厳密差/符号。前の高安窓を追加選別しない。
    """
    reasons = ["当場公開15分なし"] if current is None else (["前上位公開参照なし"] if previous is None else [])
    request = lower["confirm"], lower["confirm_line"]
    for prefix, row in (("現", current), ("前", previous)):
        if row is None:
            continue
        conditions = ((row["publish"], "15分非公開"),
            (row["一目数値入力可"], "15分数値入力不可"),
            (N.finite(row["ichimoku_kijun"]), "15分基準26未準備"),
            (row["missing"] == 0, "15分欠枠あり"),
            (row["end"] - row["start"] == 900, "15分完全幅900秒不成立"),
            (row["end"] <= lower["end"], "15分終了が下位未来"),
            ((row["confirm"], row["confirm_line"]) <= request, "15分公開keyが要求未来"))
        reasons.extend(prefix + message for valid, message in conditions if not valid)
    if current is not None and previous is not None:
        for valid, message in ((current["index"] - previous["index"] == 1, "上位現前足番号非隣接"),
                (previous["end"] == current["start"], "上位現前終了開始非隣接"),
                ((previous["confirm"], previous["confirm_line"]) <= (current["confirm"], current["confirm_line"]), "前後公開順不整合")):
            if not valid:
                reasons.append(message)
    now = current["ichimoku_kijun"] if current is not None and N.finite(current["ichimoku_kijun"]) else None
    before = previous["ichimoku_kijun"] if previous is not None and N.finite(previous["ichimoku_kijun"]) else None
    delta = None
    if not reasons:
        numerator_now, denominator_now = now.as_integer_ratio()
        numerator_before, denominator_before = before.as_integer_ratio()
        delta = Fraction(numerator_now * denominator_before - numerator_before * denominator_now,
            denominator_now * denominator_before)
    sign = None if delta is None else int(delta > 0) - int(delta < 0)
    direction = "未準備" if sign is None else "等号" if sign == 0 else "同方向" if sign == side else "逆方向"
    return {"上位現前準備": not reasons, "準備除外理由": reasons, "基準線現値": now, "基準線前値": before,
        "基準線差": float(delta) if delta is not None else None,
        "基準線差厳密分子": delta.numerator if delta is not None else None,
        "基準線差厳密分母": delta.denominator if delta is not None else None,
        "基準線差厳密符号": sign, "進行方向": direction}


def select(block: dict, higher15: list[dict], session: str | None = None) -> dict:
    """全15分の直接列挙で最新uと公開隣接前足だけを選び、全Jを判定する。

    引数: block(dict)は固定38H0純集合/3分足/下位出典、higher15(list[dict])は当場上位、session(str|None)は場。
    返り値: dictは三純集合と判定。不在/未来/NPの前足は同じNoneとして消費する。
    """
    original = block["signals"]["3分_H0"]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None:
        raise ValueError("空集合でも場が必要です")
    if any(row["場"] != actual_session or row["minutes"] != 15 for row in higher15):
        raise ValueError("当場15分以外の参照は禁止です")
    frames = block["frames"][3]
    if any(row["minutes"] != 3 for row in frames):
        raise ValueError("下位は3分だけです")
    indexed = {row["index"]: row for row in frames}
    if len(indexed) != len(frames) or len({row["index"] for row in higher15}) != len(higher15):
        raise ValueError("上下の足番号は一意です")
    keys = [(row["要求時計秒"], row["要求原板行"]) for row in original]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ValueError("固定H0の競合後・公開順を保持してください")
    if len({row["イベントID"] for row in original}) != len(original):
        raise ValueError("H0登録は一意です")
    grouped, decisions = {"3分_" + policy: [] for policy in POLICIES}, []
    for signal in original:
        if signal["場"] != actual_session:
            raise ValueError("純H0の場が不一致")
        pure_signal(signal)
        lower = block["下位出典"][signal["イベントID"]]
        if any(lower[key] != indexed[lower["index"]][key] for key in SOURCE_FIELDS):
            raise ValueError("下位出典が保存3分足と異なります")
        key = signal["要求時計秒"], signal["要求原板行"]
        if key != (lower["confirm"], lower["confirm_line"]) or not lower["publish"]:
            raise ValueError("要求keyと公開下位足が異なります")
        available = [row for row in higher15 if row["publish"] and row["end"] <= lower["end"]
            and (row["confirm"], row["confirm_line"]) <= key]
        latest = max(available, key=lambda row: (row["confirm"], row["confirm_line"], row["index"])) if available else None
        prior = next((row for row in available if latest is not None and row["index"] == latest["index"] - 1), None)
        upper, previous = upper_projection(latest), upper_projection(prior)
        pair = pair_state(upper, previous, lower, signal["side"])
        _, _, cloud, tj = classification(upper, signal["side"])
        ready, progress = pair["上位現前準備"], pair["進行方向"] == "同方向"
        verdicts = {"J0": {"採用": True, "理由": ["固定38H0完全入口"], "同時競合": False},
            "J1": {"採用": ready, "理由": ["上位基準線現前準備採用"] if ready else list(pair["準備除外理由"]), "同時競合": False},
            "J2": {"採用": ready and progress, "理由": list(pair["準備除外理由"]) if not ready else
                ["上位基準線実方向進行採用"] if progress else ["上位基準線実方向進行不成立"], "同時競合": False}}
        decisions.append({"場": actual_session, "元38H0イベントID": signal["イベントID"], "元index": lower["index"],
            "足終了時計秒": lower["end"], "要求時計秒": key[0], "要求原板行": key[1],
            "実side": signal["side"], "役割": "順行", "上位参照": upper, "前上位参照": previous,
            **pair, "雲方向": cloud, "TJ方向": tj, "戦略判定": verdicts})
        for policy in POLICIES:
            if verdicts[policy]["採用"]:
                grouped["3分_" + policy].append(pure_signal(signal, policy))
    block.update(signals=grouped, decisions=decisions)
    return block


def dependency_pins() -> dict:
    """固定独立足・一目・原BBO先着とXF追尾の推移的コードを識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現SHA。旧Pを新再計算する意味ではない。
    """
    paths = {"scripts/上位雲継続/状態独立確認.py", "scripts/一目基準線/状態独立確認.py",
        "scripts/終値位置/追尾独立確認.py"}
    values = {**Y.dependency_pins(), **{path: V.sha(ROOT / path) for path in paths}}
    return dict(sorted(values.items()))


def saved_rows(study: Path, work: Path, name: str, audit: Audit) -> tuple[list[dict], str]:
    """共有大明細を正本の圧縮・展開SHAとサイズへ照合して読む。

    引数: study/work(Path)は共有試行/作業先、name(str)はgzip名、audit(Audit)は比較先。
    返り値: tuple[list[dict],str]は保存全行と展開SHA。新しい市場入力を開かない。
    """
    path = work / name
    matches = [row for row in V.read(study / "作業成果物.json")["ファイル"]
        if Path(row["パス"]).name == name]
    if len(matches) != 1:
        raise ValueError("共有成果物が一意ではありません")
    item = matches[0]
    audit.check("共有path:" + str(path), (ROOT / item["パス"]).resolve(), path.resolve())
    audit.check("共有圧縮SHA:" + str(path), V.sha(path), item["圧縮SHA256参考"])
    audit.check("共有bytes:" + str(path), path.stat().st_size, item["圧縮バイト"])
    rows, digest = G.Q.compressed_rows(path)
    audit.check("共有展開SHA:" + str(path), digest, item["展開内容SHA256"])
    return rows, digest


def shared_bundle(audit: Audit) -> dict:
    """旧38H0純入口・元足index・下位OHLC・上位一目を別々に読み込む。

    引数: audit(Audit)は共有出典と足対応の比較先。
    返り値: dictは純信号/価格出典/数値投影だけ。先着ラベル・旧損益を採否材料へ渡さない。
    """
    pure, lower, upper, sources = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(dict)
    metadata = {}
    cases, case_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    for row in cases:
        if row["入口ID"] == "3分_H0":
            projected = deepcopy({key: row[key] for key in SIGNAL_FIELDS})
            audit.check(projected["イベントID"] + ":旧H0順行", projected["役割"], "順行")
            pure[row["場"]].append(projected)
            metadata[row["イベントID"]] = {key: row[key] for key in ("元価格発動ID", "元価格side")}
    del cases
    metadata_rows, decision_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "上位判定.jsonl.gz", audit)
    for row in metadata_rows:
        identifier = row["元37T1イベントID"][:-3] + "_H0"
        metadata[identifier]["index"] = row["元index"]
    del metadata_rows
    lower_rows, lower_sha = saved_rows(LOWER_STUDY, LOWER_WORK, "全指標.jsonl.gz", audit)
    for row in lower_rows:
        lower[row["場"]].append({"場": row["場"], **{key: row[key] for key in SOURCE_FIELDS}})
    del lower_rows
    for session, signals in pure.items():
        mapping = {row["index"]: row for row in lower[session]}
        for signal in signals:
            identifier = signal["イベントID"]
            meta = metadata[identifier]
            frame = mapping[meta["index"]]
            audit.check(identifier + ":旧下位key", (frame["confirm"], frame["confirm_line"]),
                (signal["要求時計秒"], signal["要求原板行"]))
            audit.check(identifier + ":旧下位公開", frame["publish"], True)
            audit.check(identifier + ":旧下位高安", (frame["low"], frame["high"]), (signal["low"], signal["high"]))
            sources[session][identifier] = {key: deepcopy(frame[key]) for key in SOURCE_FIELDS}
    upper_rows, upper_sha = saved_rows(UPPER_STUDY, UPPER_WORK, "全指標.jsonl.gz", audit)
    for row in upper_rows:
        if row["minutes"] == 15:
            upper[row["場"]].append(upper_projection(row))
    del upper_rows
    return {"pure": pure, "metadata": metadata, "lower": lower, "lower_sources": sources, "upper": upper,
        "input_quality": {row["場"]: {key: value for key, value in row.items() if key != "期間"}
            for row in V.read(ENTRY_STUDY / "入力品質.json")},
        "共有入口事例展開SHA256": case_sha, "共有上位判定展開SHA256": decision_sha,
        "共有下位全指標展開SHA256": lower_sha, "共有上位全指標展開SHA256": upper_sha}


# ----------------------------------------
# 共有証明は旧価格発動の正本へ、新上位数値と時点は39の独立走査へ接続する。


def references(study: Path, audit: Audit) -> None:
    """38純入口/対照と28上位の完了証明・共有範囲を現在の正本へ結ぶ。

    引数: study(Path)は39、audit(Audit)は比較先。
    返り値: None。38/37の旧P証明と39新上位の証明範囲を混同しない。
    """
    anchors = {ENTRY_STUDY: "a874ebd229effc24f5ac4af7088086ab139b48ac8e3029fa3aeffabcc3bf0e6e",
        UPPER_STUDY: "24169522b4245c77c32a36e709322de841a7a6a7e8aa0faf0b21968676cf5801"}
    for source, expected in anchors.items():
        audit.check("共有固定正本:" + source.name, V.sha(source / "固定.json"), expected)
        for path, digest in V.read(source / "固定.json")["ファイルSHA256"].items():
            audit.check("共有固定現在:" + path, V.sha(ROOT / path), digest)
    Y.references(ENTRY_STUDY, audit)
    for filename in ("入口参照.json", "対照参照.json", "上位参照.json"):
        source = UPPER_STUDY if filename == "上位参照.json" else ENTRY_STUDY
        ref = V.read(study / filename)
        audit.check(filename + ":試行", ref["参照試行"], source.name[:5])
        audit.check(filename + ":固定SHA", ref["旧固定SHA256"], anchors[source])
        audit.check(filename + ":複製なし", ref["大明細複製"], False)
        expected_names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json",
            "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
        if source == ENTRY_STUDY:
            expected_names.add("入力品質.json")
        audit.check(filename + ":証明集合", set(ref["文書と証明"]), expected_names)
        for name, item in ref["文書と証明"].items():
            audit.check(filename + name + ":正本", (ROOT / item["パス"]).resolve(), (source / name).resolve())
            audit.check(filename + name + ":SHA", item["SHA256"], V.sha(source / name))
        for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
            proof = V.read(source / name)
            audit.check(source.name + name + ":成功", proof["全件一致"], True)
            audit.check(source.name + name + ":差0", proof["不一致数"], 0)
        expected = V.read(source / "作業成果物.json")["ファイル"]
        wanted = {"全指標.jsonl.gz"} if source == UPPER_STUDY else (
            {"全運用詳細.jsonl.gz", "追尾.jsonl.gz"} if filename == "対照参照.json" else None)
        if wanted is not None:
            expected = [item for item in expected if Path(item["パス"]).name in wanted]
        audit.check(filename + ":明細集合", ref["共有明細"], expected)
        if filename == "対照参照.json":
            audit.check(filename + ":旧候補", ref["候補ID"], "3分_H0_XF")
        for item in expected:
            path = ROOT / item["パス"]
            audit.check(filename + path.name + ":圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
            audit.check(filename + path.name + ":bytes", path.stat().st_size, item["圧縮バイト"])


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """三方針・共通出口・主準備と入力/共有の現在指紋を市場入力前に照合する。

    引数: study/work(Path)は39保存先、audit(Audit)は比較先。
    返り値: tupleは条件/実台帳/主準備/実台帳path。差があればcache前に停止する。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    references(study, audit)
    old, current_exit = V.read(ENTRY_STUDY / "条件.json"), V.read(EXIT_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒",
            "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("固定38入口尺度:" + key, config[key], old[key])
    for key in ("運用", "必須追尾"):
        audit.check("固定33現費用:" + key, config[key], current_exit[key])
    audit.check("事前三方針", config["戦略"], list(POLICIES))
    audit.check("事前三XF", config["運用組合せ"], [{"戦略": policy, "出口ID": "XF"} for policy in POLICIES])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧38H0純登録同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        **{name.removesuffix(".json") + "SHA256": V.sha(study / name)
            for name in ("入口参照.json", "対照参照.json", "上位参照.json")}}
    for key, value in expected.items():
        audit.check("主準備:" + key, master[key], value)
    paths = {"scripts/上位中心継続/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for path, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + path, V.sha(ROOT / path), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("共有/主準備/入力版に差があるため市場入力前停止")
    return config, manifest, master, resolved


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列から15分一目と下位出典を形成し、固定純H0へ独立現前ペア/asofを結ぶ。

    引数: manifest/bundle/config(dict)は既使用66場台帳/共有純材料/条件。
    返り値: Anyは非先着・非運用の場別iterator。旧P/MACD/数量Mは再算出しない。
    """
    bank = NumericHistory(15)
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, _, _ = S.G.times(session)
        data = G.observed(entry, manifest)
        upper_ohlc = S.bars(data, session, 15, N.BareBars())
        lower_ohlc = S.bars(data, session, 3, N.BareBars())
        tail = max(0, int((finish - start) // 900) - 1 - (upper_ohlc[-1]["index"] if upper_ohlc else -1))
        upper, quality = bank.build(upper_ohlc, session, tuple(entry["in_session_contract_codes"]), tail)
        indexed = {row["index"]: row for row in lower_ohlc}
        signals = deepcopy(bundle["pure"].get(session, []))
        sources = {signal["イベントID"]: deepcopy(indexed[bundle["metadata"][signal["イベントID"]]["index"]]) for signal in signals}
        block = select({"場": session, "signals": {"3分_H0": signals}, "frames": {3: lower_ohlc}, "下位出典": sources}, upper, session)
        pure = [row for policy in POLICIES for row in block["signals"]["3分_" + policy]]
        decisions = block["decisions"]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else (
            "条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": decisions, "判定SHA256": canonical_sha(decisions), "判定判断SHA256": canonical_sha(decisions),
            "全15分投影SHA256": canonical_sha(upper), "15分投影足数": len(upper), "下位出典": sources,
            "入力品質": deepcopy(bundle["input_quality"][session]), "_上位": upper, "_下位": lower_ohlc, "_銀行品質": quality}


def compare_preparation(main: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """原足/全上位数値/当時参照と全三採否を、コピーATRも含め厳密に照合する。

    引数: main/block(dict)は主/独立場、bundle(dict)は共有正本、audit(Audit)は比較先。
    返り値: dictは場別件数と全15分判断SHA。新上位の許容epsilonは使用しない。
    """
    session = block["場"]
    audit.check(session + ":原8列15分全投影", block["_上位"], bundle["upper"][session])
    lower = [{"場": session, **{key: row[key] for key in SOURCE_FIELDS}} for row in block["_下位"]]
    audit.check(session + ":原8列3分出典", lower, bundle["lower"][session])
    independent = {key: value for key, value in block.items() if not key.startswith("_")}
    audit.check(session + ":全時点/上位/純三採否", main, independent)
    audit.leaf(session + ":全準備厳密JSON値", main, independent, main == independent)
    ids = {policy: set() for policy in POLICIES}
    old = {row["イベントID"]: row for row in bundle["pure"].get(session, [])}
    for row in main["純信号"]:
        policy = row["入口ID"].removeprefix("3分_")
        original = row["イベントID"][:-3] + "_H0"
        audit.check(row["イベントID"] + ":純13列集合", set(row), set(SIGNAL_FIELDS))
        expected = pure_signal(old[original], policy)
        audit.leaf(row["イベントID"] + ":旧H0全13値厳密", row, expected, row == expected)
        ids[policy].add(original)
    audit.check(session + ":J0旧H0全件", ids["J0"], set(old))
    audit.check(session + ":J1準備subsetJ0", ids["J1"] <= ids["J0"], True)
    audit.check(session + ":J2値subsetJ1", ids["J2"] <= ids["J1"], True)
    return {"場": session, "期間": block["期間"], **{policy + "登録数": len(ids[policy]) for policy in POLICIES},
        "15分投影足数": block["15分投影足数"], "下位OHLC足数": len(lower),
        "全15分投影SHA256": block["全15分投影SHA256"], "全判定SHA256": block["判定SHA256"]}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """現在の主/独立/共有/入力指紋と、旧証明へ委ねる範囲を記録する。

    引数: study/work/resolved(Path)は保存先/解決台帳、master(dict)は主準備、audit(Audit)は照合先。
    返り値: dictは共通証明骨格。旧価格分析を39で再検算したとは記さない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        **{name.removesuffix(".json") + "SHA256": V.sha(study / name)
            for name in ("入口参照.json", "対照参照.json", "上位参照.json")},
        "旧価格発動の検算": "固定38/37状態独立確認へSHA接続。39では旧P/MACD/数量M/ATRを再計算しない。",
        "厳密範囲": "固定38H0純13列はATR原値も完全一致。原8列由来3分SOURCE/全15分一目投影/雲元/公開key/asof/個別J準備/現前差分数/全採否/全判断SHAは厳密。新上位に許容epsilonは使わない。"}


def prepare(study: Path, work: Path) -> dict:
    """root起動の準備だけで全15分一目・asof・三採否を比較する。

    引数: study/work(Path)は39保存先。
    返り値: dictは非先着/非損益証明。原BBO先着・運用・金額は呼ばない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    for main, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "固定純H0/原15一目/個別Jペア/厳密進行/全J", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    count = sum(row["J0登録数"] for row in stages)
    audit.check("全J0旧H0数", count, sum(len(rows) for rows in bundle["pure"].values()))
    audit.check("主旧H0登録数", master["旧H0登録数"], count)
    old_state = V.read(ENTRY_STUDY / "状態独立確認.json")
    audit.check("旧38H0件数証明", count, old_state["方針別case数"]["H0"])
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "旧38H0純登録同値": audit.mismatches == 0, "旧H0登録数": count,
        "場別準備": stages, "新15分全数値照合足数": sum(row["15分投影足数"] for row in stages),
        **{key: value for key, value in bundle.items() if key.endswith("展開SHA256")},
        "検証範囲": "固定38H0の識別子以外全13値を保持。原8列から3/15分半開OHLCを別形成、固定28独立高安窓別走査で現在雲とT/J/雲元/銀行状態を全足照合。各H0で全公開上位を直接列挙し、end/key両asofと公開隣接前足/個別J準備、交差積の厳密現前差、三採否を照合。雲準備はJ採否へ使わない。",
        "限界": "非先着/非運用/非PnL。旧P/MACD/数量Mの再構成は38/37証明へ委ねる。HH/LL機序panelを新計算せず、新上位全足を39gzipへ重複保存しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧H0登録数")}, ensure_ascii=False))
    return proof


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """正式開始前に成功した独立準備と固定の現在版を要求する。

    引数: study/work/resolved(Path)は保存先/解決台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。差があれば正式の市場入力前に停止する。
    """
    prepared = V.read(work / "独立準備点検.json")
    expected = proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "入口参照SHA256", "対照参照SHA256", "上位参照SHA256"):
        audit.check("独立準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("独立準備成功:" + key, prepared[key], value)
    for path, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + path, V.sha(ROOT / path), digest)
    if audit.mismatches:
        raise ValueError("成功準備/固定/現版に差があり市場入力前停止")


def run(study: Path, work: Path) -> dict:
    """正式後に全上位判定/全case直接先着と旧H0全属性対照を確認する。

    引数: study/work(Path)は39保存先。
    返り値: dictは正式状態証明。全Hの新caseを正常BBO原列で直接検算する。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    old_cases = {row["イベントID"]: row for row in old_rows if row["入口ID"] == "3分_H0"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "全運用詳細.jsonl.gz", audit)
    old_details = {row["場"]: row for row in old_rows if row["候補ID"] == "3分_H0_XF"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "追尾.jsonl.gz", audit)
    old_logs = defaultdict(list)
    for row in old_rows:
        if row["候補ID"] == "3分_H0_XF":
            old_logs[row["場"]].append(row)
    names = ("上位判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新四成果物集合", set(artifacts), {name + ".jsonl.gz" for name in names})
    for name in names:
        path = work / (name + ".jsonl.gz")
        saved[name], hashes[name] = G.Q.compressed_rows(path)
        item = artifacts[path.name]
        audit.check(name + ":正本path", (ROOT / item["パス"]).resolve(), path.resolve())
        audit.check(name + ":圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
        audit.check(name + ":bytes", path.stat().st_size, item["圧縮バイト"])
        audit.check(name + ":展開SHA", hashes[name], item["展開内容SHA256"])
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    stages, controls, label_counts = [], [], {policy: 0 for policy in POLICIES}
    entries = {row["session"]: row for row in manifest["entries"]}
    for main, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main, block, bundle, audit))
        session, period = block["場"], block["期間"]
        audit.check(session + ":正式全上位判定", grouped["上位判定"][session], [{"期間": period, **row} for row in block["判定"]])
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":case全純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            policy = signal["入口ID"].removeprefix("3分_")
            original = signal["イベントID"][:-3] + "_H0"
            direct = label_direct(quotes, signal, cutoff, deadline)
            metadata = bundle["metadata"][original]
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": metadata["元価格発動ID"], "元価格side": metadata["元価格side"], "旧H0イベントID": original, **direct}
            audit.check(signal["イベントID"] + ":全case原BBO直接先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全case厳密値", cases.get(signal["イベントID"]) == expected, True)
            audit.check(signal["イベントID"] + ":旧同時計順行11label", direct, {key: old_cases[original][key] for key in LABEL_FIELDS})
            label_counts[policy] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] != "3分_J0_XF":
                continue
            trace = [row for row in grouped["追尾"][session] if row["候補ID"] == detail["候補ID"]]
            adapted, adapted_logs = rename(detail, "_J0", "_H0"), rename(trace, "_J0", "_H0")
            audit.leaf(session + ":旧38H0全ledger同値", adapted, old_details[session], adapted == old_details[session])
            audit.leaf(session + ":旧38H0全trace同値", adapted_logs, old_logs[session], adapted_logs == old_logs[session])
            controls.append({"場": session, "候補ID": detail["候補ID"], "全運用同値": adapted == old_details[session],
                "全追尾同値": adapted_logs == old_logs[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
        print(json.dumps({"場": session, "独立状態": "全上位一目/個別Jペア/asof/全J/直接先着/旧H0対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("全case数", len(saved["入口事例"]), sum(label_counts.values()))
    audit.check("J0旧全H0数", label_counts["J0"], len(old_cases))
    audit.check("J0保存対照証明", V.read(study / "J0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, "旧H0登録数": label_counts["J0"],
        "方針別case数": label_counts, "全先着直接照合件数": sum(label_counts.values()), "方針別先着直接照合件数": label_counts,
        "旧同時計順行先着照合数": sum(label_counts.values()), "旧38全属性同値場数": len(controls),
        "新15分全数値照合足数": sum(row["15分投影足数"] for row in stages),
        "保存上位判定数": len(saved["上位判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        **{key: value for key, value in bundle.items() if key.endswith("展開SHA256")},
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"), "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列から上位15分一目と下位OHLC出典を別再構成。全当場公開15分を列挙した最新asof/公開隣接ペア/個別J準備/厳密進行と全J採否/出典を全件照合。固定38H0の全13値厳密保持、全caseの原正常BBO直接125/250と旧同時計順行11label同値、J0全66ledger/trace同値を確認。",
        "限界": "旧P/MACD/数量M/ATRの価格発動再検算は38/37成功証明へSHA接続。新規受付/Decimalは別財務、全保有線と最初返済要求は別追尾。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧H0登録数", "旧38全属性同値場数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可後の準備又は固定後の状態監査だけを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00039の上位基準線進行と当場ペアの独立検算")
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
