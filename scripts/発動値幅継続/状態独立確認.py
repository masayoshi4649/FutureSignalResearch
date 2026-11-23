"""00040の固定J0純入口と、原8列3分ATR/TR・閾値影響を独立照合する。"""

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
STUDY = ROOT / "study/00040_外側継続と発動足の相対値幅"
WORK = ROOT / "work/発動値幅継続/00040"
ENTRY_STUDY = ROOT / "study/00039_外側継続と上位基準線の進行"
ENTRY_WORK = ROOT / "work/上位中心継続/00039"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
LOWER_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
LOWER_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("W0", "W1", "W2")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)


def helper(path: Path, name: str) -> Any:
    """固定された独立原足・一目・先着補助をCLI起動せず読む。

    引数: path(Path)は独立コード、name(str)は読込識別子。
    返り値: Anyは独立補助。40主入口・運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/上位中心継続/状態独立確認.py", "発動値幅継続の固定39独立共通補助")
G, B, S, V = Y.G, Y.B, Y.S, Y.V
N = G.B
Audit = N.Audit
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = Y.SIGNAL_FIELDS, Y.LABEL_FIELDS, N.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr")
canonical_sha, rename = Y.canonical_sha, Y.rename
decision_signal, normal_columns, label_direct = Y.decision_signal, Y.normal_columns, Y.label_direct


def pure_signal(row: dict, policy: str = "W0") -> dict:
    """固定39J0から識別子以外を変えず、順行の純13列だけを取り出す。

    引数: row(dict)は固定39J0純入口、policy(str)はW0/W1/W2。
    返り値: dictは当時情報だけの辞書。旧caseのラベル・損益を射影しない。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] != "順行":
        raise ValueError("順行の三候補だけです")
    if row["入口ID"] != "3分_J0" or not row["イベントID"].endswith("_J0"):
        raise ValueError("固定39J0の識別子が必要です")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示が不一致")
    value = deepcopy({key: row.get(key) if key == "bb_mean" else row[key] for key in SIGNAL_FIELDS})
    origin = value["イベントID"][:-3]
    value.update(イベントID=origin + "_" + policy, 入口ID="3分_" + policy)
    return value


def frame_projection(row: dict | None) -> dict | None:
    """3分OHLCの出典とATRだけを新しい辞書へ限定射影する。

    引数: row(dict|None)は固定29数値足又は独立再構成足。
    返り値: dict|NoneはMACD/数量/15分数値を含まない限定投影。
    """
    if row is not None and row["minutes"] != 3:
        raise ValueError("発動値幅は3分だけです")
    return None if row is None else deepcopy({key: row[key] for key in FRAME_FIELDS})


class NumericHistory:
    """原3分OHLCからATR14だけを別演算順で計算する独立銀行。"""

    def __init__(self, minutes: int = 3) -> None:
        """3分だけの独立銀行を作る。

        引数: minutes(int)は3。
        返り値: None。MACD/数量/15分は再計算しない。
        """
        if minutes != 3:
            raise ValueError("発動値幅は3分だけです")
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """前終値とATR14の種・更新値を解除する。

        引数: なし。
        返り値: None。同限月識別は保持する。
        """
        self.previous, self.average = None, S.G.Wilder()

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """有効3分OHLCのTRを独立Wilderへ加え、非公開足は数値だけ更新する。

        引数: frames(list[dict])は独立3分OHLC、session(str)は場、contract(tuple)は限月、tail_missing(int)は尾部欠枠。
        返り値: tuple[list[dict],dict]は限定数値と銀行品質。欠枠解除後有効当足は数値の初足へ投入する。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous_index, previous_key, clears = [], None, None, int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("3分足番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("公開時計又は順序が不正")
            clear = index != (0 if previous_index is None else previous_index + 1) or bool(frame["missing"]) or not N.valid_ohlc(frame)
            if clear:
                self.clear()
                clears += 1
            atr = None
            if N.valid_ohlc(frame):
                if self.previous is not None:
                    close = self.previous["close"]
                    tr = max(frame["high"] - frame["low"], abs(frame["high"] - close), abs(frame["low"] - close))
                    atr = self.average.add(tr)
                self.previous = deepcopy(frame)
            rows.append({"場": session, **N.source(frame), "atr": atr})
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        return rows, {"場": session, "時間足分": 3, "入力足数": len(rows),
            "ATR準備足数": sum(row["atr"] is not None for row in rows), "clear数": clears,
            "尾部完全欠枠": tail_missing}


# ----------------------------------------
# 元J0純13列は39証明へ接続し、3分の現前参照/精密TR/ATR閾値影響を別実装する。


def exact(value: Fraction | None) -> dict:
    """精密値と表示値を分け、無効をゼロへ補完しない。

    引数: value(Fraction|None)は元観測値からの精密値。
    返り値: dictは値/分子/分母/有効。
    """
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def range_state(current: dict, previous: dict | None) -> dict:
    """価格ペアと前ATRを分離し、TRを前終値込み包絡幅から別算する。

    引数: current(dict)は公開要求足、previous(dict|None)は当時前3分。
    返り値: dictは準備/三距離/精密TR/前ATRとの差・比/符号。TRは平均の大きさで方向付けしない。
    """
    price_reasons = [] if previous is not None else ["前3分公開参照なし"]
    for prefix, row in (("現", current), ("前", previous)):
        if row is None:
            continue
        conditions = ((row["publish"], "3分非公開"), (N.valid_ohlc(row), "3分OHLC不正"),
            (row["missing"] == 0, "3分欠枠あり"), (row["end"] - row["start"] == 180, "3分完全幅180秒不成立"),
            (row["confirm"] >= row["end"], "3分終了前公開"))
        price_reasons.extend(prefix + message for valid, message in conditions if not valid)
    if previous is not None:
        conditions = ((current["index"] - previous["index"] == 1, "現前3分足番号非隣接"),
            (previous["end"] == current["start"], "現前3分終了開始非隣接"),
            ((previous["confirm"], previous["confirm_line"]) <= (current["confirm"], current["confirm_line"]), "現前3分公開順不整合"))
        price_reasons.extend(message for valid, message in conditions if not valid)
    distances = {name: None for name in ("高安幅", "高値と前終値の距離", "安値と前終値の距離")}
    tr = None
    if not price_reasons:
        high, low, before_close = (Fraction(value) for value in (current["high"], current["low"], previous["close"]))
        distances = {"高安幅": high - low, "高値と前終値の距離": abs(before_close - high), "安値と前終値の距離": abs(before_close - low)}
        tr = max(high, before_close) - min(low, before_close)
    prior = previous["atr"] if previous is not None and N.finite(previous["atr"]) else None
    reasons = list(price_reasons)
    if prior is None or prior <= 0:
        reasons.append("前3分ATR14有限正未準備")
    difference = ratio = None
    if not reasons:
        n, d = prior.as_integer_ratio()
        reference = Fraction(n, d)
        difference = Fraction(tr.numerator * reference.denominator - reference.numerator * tr.denominator,
            tr.denominator * reference.denominator)
        ratio = Fraction(tr.numerator * reference.denominator, tr.denominator * reference.numerator)
    sign = None if difference is None else int(difference > 0) - int(difference < 0)
    return {"値幅準備": not reasons, "準備除外理由": reasons, "TR準備": not price_reasons,
        "TR三距離": {name: exact(value) for name, value in distances.items()}, "TR": exact(tr), "前ATR14": prior,
        "TR前ATR差": exact(difference), "TR前ATR比": exact(ratio), "TR前ATR差符号": sign,
        "値幅区分": "未準備" if reasons else "非拡大" if sign <= 0 else "拡大"}


def select(block: dict, session: str | None = None) -> dict:
    """当足indexから全3分列の隣接前足を別走査し、元J0を三案へ分ける。

    引数: block(dict)は固定39J0純集合/3分frames/下位出典、session(str|None)は場。
    返り値: dictは全W採否と当時情報だけの純13列。未公開/未来/不在前足は同じNone。
    """
    original = block["signals"]["3分_J0"]
    actual = session or block.get("場") or (original[0]["場"] if original else None)
    if actual is None:
        raise ValueError("空集合でも場が必要です")
    frames = block["frames"][3]
    if any(row["場"] != actual or row["minutes"] != 3 for row in frames):
        raise ValueError("当場3分だけです")
    if len({row["index"] for row in frames}) != len(frames):
        raise ValueError("3分足番号は一意です")
    keys = [(row["要求時計秒"], row["要求原板行"]) for row in original]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ValueError("固定J0の競合後・公開順を保持してください")
    if len({row["イベントID"] for row in original}) != len(original):
        raise ValueError("固定J0イベントは一意です")
    grouped, decisions = {"3分_" + policy: [] for policy in POLICIES}, []
    for signal in original:
        pure_signal(signal)
        if signal["場"] != actual:
            raise ValueError("純J0の場が不一致")
        source = block["下位出典"][signal["イベントID"]]
        current = frame_projection(next(row for row in frames if row["index"] == source["index"]))
        if any(current[key] != source[key] for key in SOURCE_FIELDS):
            raise ValueError("当足出典が固定3分足と異なります")
        key = signal["要求時計秒"], signal["要求原板行"]
        if key != (current["confirm"], current["confirm_line"]) or not current["publish"]:
            raise ValueError("純要求keyと当足公開出典が不一致")
        if (signal["low"], signal["high"], signal["atr"]) != (current["low"], current["high"], current["atr"]):
            raise ValueError("純入口高安/現ATRと正本が不一致")
        candidates = [row for row in frames if row["index"] == current["index"] - 1 and row["publish"]
            and row["end"] <= current["end"] and (row["confirm"], row["confirm_line"]) <= key]
        previous = frame_projection(candidates[0]) if candidates else None
        state = range_state(current, previous)
        ready, narrow = state["値幅準備"], state["値幅区分"] == "非拡大"
        verdicts = {"W0": {"採用": True, "理由": ["固定39J0完全入口"], "同時競合": False},
            "W1": {"採用": ready, "理由": ["発動値幅準備採用"] if ready else list(state["準備除外理由"]), "同時競合": False},
            "W2": {"採用": ready and narrow, "理由": list(state["準備除外理由"]) if not ready else
                ["発動TR前ATR以下採用"] if narrow else ["発動TRが前ATR超"], "同時競合": False}}
        decisions.append({"場": actual, "元39J0イベントID": signal["イベントID"], "元index": current["index"],
            "足終了時計秒": current["end"], "要求時計秒": key[0], "要求原板行": key[1], "実side": signal["side"], "役割": "順行",
            "当足参照": current, "前足参照": previous, **state, "戦略判定": verdicts})
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
    paths = {"scripts/上位中心継続/状態独立確認.py", "scripts/一目基準線/状態独立確認.py",
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
    """固定39J0純13列と、旧29の3分OHLC/ATRだけを保存物から読む。

    引数: audit(Audit)は出典と旧要求足の比較先。
    返り値: dictは純入口/元price情報/限定3分/下位出典。15分・未来labelを採否へ渡さない。
    """
    pure, lower, sources, metadata = defaultdict(list), defaultdict(list), defaultdict(dict), {}
    rows, case_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    for row in rows:
        if row["入口ID"] == "3分_J0":
            signal = deepcopy({key: row[key] for key in SIGNAL_FIELDS})
            pure[row["場"]].append(signal)
            metadata[row["イベントID"]] = {key: row[key] for key in ("元価格発動ID", "元価格side")}
    del rows
    rows, previous_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "上位判定.jsonl.gz", audit)
    for row in rows:
        metadata[row["元38H0イベントID"][:-3] + "_J0"]["index"] = row["元index"]
    del rows
    rows, numeric_sha = saved_rows(INDICATOR_STUDY, INDICATOR_WORK, "全指標.jsonl.gz", audit)
    for row in rows:
        if row["minutes"] == 3:
            lower[row["場"]].append(frame_projection(row))
    del rows
    for session, signals in pure.items():
        indexed = {row["index"]: row for row in lower[session]}
        for signal in signals:
            identifier = signal["イベントID"]
            frame = indexed[metadata[identifier]["index"]]
            audit.check(identifier + ":旧要求足key", (frame["confirm"], frame["confirm_line"]), (signal["要求時計秒"], signal["要求原板行"]))
            audit.check(identifier + ":旧要求足公開", frame["publish"], True)
            audit.check(identifier + ":旧高安現ATR厳密", (frame["low"], frame["high"], frame["atr"]) == (signal["low"], signal["high"], signal["atr"]), True)
            sources[session][identifier] = {key: deepcopy(frame[key]) for key in SOURCE_FIELDS}
    return {"pure": pure, "metadata": metadata, "lower": lower, "lower_sources": sources,
        "input_quality": {row["場"]: {key: value for key, value in row.items() if key != "期間"} for row in V.read(ENTRY_STUDY / "入力品質.json")},
        "共有入口事例展開SHA256": case_sha, "共有前試行判定展開SHA256": previous_sha,
        "共有3分全指標展開SHA256": numeric_sha}


# ----------------------------------------
# 旧価格発動は39証明、3分ATR再算/精密TR/閾値符号/全採否は40の新証明。


def references(study: Path, audit: Audit) -> None:
    """39純入口/対照と29指標の完了証明・共有範囲を現在の正本へ結ぶ。

    引数: study(Path)は40、audit(Audit)は比較先。
    返り値: None。39/38/37の旧P証明と40新ATR/TRの証明範囲を混同しない。
    """
    anchors = {ENTRY_STUDY: "bf29f6b59d888b628476bd05fc4827469821c6d28e31ca3fa6fe281df39997dc",
        INDICATOR_STUDY: "353143ea3f7a626736bf44551d17ba6e22b8bfd76ee40e2f4f9b0c190736f48a"}
    for source, expected in anchors.items():
        audit.check("共有固定正本:" + source.name, V.sha(source / "固定.json"), expected)
        for path, digest in V.read(source / "固定.json")["ファイルSHA256"].items():
            audit.check("共有固定現在:" + path, V.sha(ROOT / path), digest)
    Y.references(ENTRY_STUDY, audit)
    for filename in ("入口参照.json", "対照参照.json", "指標参照.json"):
        source = INDICATOR_STUDY if filename == "指標参照.json" else ENTRY_STUDY
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
        wanted = {"全指標.jsonl.gz"} if source == INDICATOR_STUDY else (
            {"全運用詳細.jsonl.gz", "追尾.jsonl.gz"} if filename == "対照参照.json" else None)
        if wanted is not None:
            expected = [item for item in expected if Path(item["パス"]).name in wanted]
        audit.check(filename + ":明細集合", ref["共有明細"], expected)
        if filename == "対照参照.json":
            audit.check(filename + ":旧候補", ref["候補ID"], "3分_J0_XF")
        for item in expected:
            path = ROOT / item["パス"]
            audit.check(filename + path.name + ":圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
            audit.check(filename + path.name + ":bytes", path.stat().st_size, item["圧縮バイト"])


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """三方針・共通出口・主準備と入力/共有の現在指紋を市場入力前に照合する。

    引数: study/work(Path)は40保存先、audit(Audit)は比較先。
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
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧39J0純登録同値": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        **{name.removesuffix(".json") + "SHA256": V.sha(study / name)
            for name in ("入口参照.json", "対照参照.json", "指標参照.json")}}
    for key, value in expected.items():
        audit.check("主準備:" + key, master[key], value)
    paths = {"scripts/発動値幅継続/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
    for path, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + path, V.sha(ROOT / path), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("共有/主準備/入力版に差があるため市場入力前停止")
    return config, manifest, master, resolved


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列3分/ATRを別算し、正本ATRの定義照合と再算ATRの影響照合を分ける。

    引数: manifest/bundle/config(dict)は台帳/共有正本/条件。
    返り値: Anyは非先着・非運用の場別iterator。正本rawSHAを独立ATR全内容SHAと混同しない。
    """
    bank = NumericHistory(3)
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, _, _ = S.G.times(session)
        data = G.observed(entry, manifest)
        formed = S.bars(data, session, 3, N.BareBars())
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        independent, quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail)
        original = {row["index"]: row for row in bundle["lower"][session]}
        defined = [{**deepcopy(row), "atr": original[row["index"]]["atr"]} for row in independent]
        indexed, rebuilt = ({row["index"]: row for row in rows} for rows in (defined, independent))
        signals = deepcopy(bundle["pure"].get(session, []))
        sources = {signal["イベントID"]: {key: deepcopy(indexed[bundle["metadata"][signal["イベントID"]]["index"]][key]) for key in SOURCE_FIELDS} for signal in signals}
        selected = select({"場": session, "signals": {"3分_J0": signals}, "frames": {3: defined}, "下位出典": sources}, session)
        decisions = selected["decisions"]
        alternate = []
        for decision in decisions:
            current = rebuilt[decision["元index"]]
            prior_source = decision["前足参照"]
            previous = rebuilt[prior_source["index"]] if prior_source is not None else None
            state = range_state(current, previous)
            ready, narrow = state["値幅準備"], state["値幅区分"] == "非拡大"
            alternate.append({"元39J0イベントID": decision["元39J0イベントID"], "TR比較符号": state["TR前ATR差符号"],
                "値幅準備": ready, "TR準備": state["TR準備"], "準備除外理由": state["準備除外理由"],
                "採否": {"W0": True, "W1": ready, "W2": ready and narrow}})
        pure = [row for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]), "判定": decisions,
            "判定SHA256": canonical_sha(decisions), "判定判断SHA256": canonical_sha(decisions),
            "全3分投影SHA256": canonical_sha(defined), "3分投影足数": len(defined), "下位出典": sources,
            "入力品質": deepcopy(bundle["input_quality"][session]), "_再算全3分": independent,
            "_正本ATR定義全3分": defined, "_再算ATR判断": alternate, "_銀行品質": quality}


def compare_preparation(main: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """ATR全足を限定許容、正本定義rawSHAと再算ATR閾値符号/採否を厳密に検査する。

    引数: main/block(dict)は主/独立場、bundle(dict)は旧正本、audit(Audit)は比較先。
    返り値: dictは全足/表現差/閾値影響とstrictな正本定義SHAの要約。
    """
    session = block["場"]
    independent, source = block["_再算全3分"], bundle["lower"][session]
    audit.check(session + ":原8列3分SOURCE/独立ATR全足", independent, source)
    differences = [abs(actual["atr"] - expected["atr"]) for actual, expected in zip(independent, source, strict=True)
        if N.finite(actual["atr"]) and N.finite(expected["atr"]) and actual["atr"] != expected["atr"]]
    expected_record = {key: value for key, value in block.items() if not key.startswith("_")}
    audit.check(session + ":正本ATR定義/TR/全W/全source", main, expected_record)
    audit.check(session + ":全正本定義厳密JSON値", main == expected_record, True)
    sign_differences = decision_differences = 0
    for actual, alternate in zip(block["判定"], block["_再算ATR判断"], strict=True):
        identifier = actual["元39J0イベントID"]
        audit.check(identifier + ":再算ATR準備理由厳密", (alternate["値幅準備"], alternate["TR準備"], alternate["準備除外理由"]),
            (actual["値幅準備"], actual["TR準備"], actual["準備除外理由"]))
        same_sign = alternate["TR比較符号"] == actual["TR前ATR差符号"]
        audit.check(identifier + ":再算ATR比較符号strict", same_sign, True)
        sign_differences += int(not same_sign)
        adoption = {policy: actual["戦略判定"][policy]["採用"] for policy in POLICIES}
        same_decision = alternate["採否"] == adoption
        audit.check(identifier + ":再算ATR全採否strict", same_decision, True)
        decision_differences += int(not same_decision)
    ids, old = {policy: set() for policy in POLICIES}, {row["イベントID"]: row for row in bundle["pure"].get(session, [])}
    for row in main["純信号"]:
        policy, origin = row["入口ID"].removeprefix("3分_"), row["イベントID"][:-3] + "_J0"
        audit.check(row["イベントID"] + ":純13列集合", set(row), set(SIGNAL_FIELDS))
        audit.check(row["イベントID"] + ":旧J0現ATR含む厳密13値", row == pure_signal(old[origin], policy), True)
        ids[policy].add(origin)
    audit.check(session + ":W0旧J0全件", ids["W0"], set(old))
    audit.check(session + ":W1準備subsetW0", ids["W1"] <= ids["W0"], True)
    audit.check(session + ":W2値subsetW1", ids["W2"] <= ids["W1"], True)
    return {"場": session, "期間": block["期間"], **{policy + "登録数": len(ids[policy]) for policy in POLICIES},
        "3分投影足数": len(source), "ATR表現差足数": len(differences), "ATR最大絶対差": max(differences, default=0.0),
        "ATR影響照合発動数": len(block["判定"]), "再算ATR符号不一致数": sign_differences, "再算ATR採否不一致数": decision_differences,
        "全3分投影SHA256": block["全3分投影SHA256"], "正本ATR定義全3分投影SHA256": block["全3分投影SHA256"], "独立再算ATR全3分内容SHA256": canonical_sha(independent),
        "全判定SHA256": block["判定SHA256"]}


def numeric_summary(stages: list[dict]) -> dict:
    """全3分のATR表現差と、発動時の閾値/採否影響を別に集計する。

    引数: stages(list[dict])は場別の検算要約。
    返り値: dictは足数・表現差・最大差・比較対象と不一致数。生ATRの完全SHA同一とは記さない。
    """
    return {"新3分全数値照合足数": sum(row["3分投影足数"] for row in stages),
        "独立ATR表現差足数": sum(row["ATR表現差足数"] for row in stages),
        "独立ATR最大絶対差": max((row["ATR最大絶対差"] for row in stages), default=0.0),
        "再算ATR影響照合発動数": sum(row["ATR影響照合発動数"] for row in stages),
        "再算ATR符号不一致数": sum(row["再算ATR符号不一致数"] for row in stages),
        "再算ATR採否不一致数": sum(row["再算ATR採否不一致数"] for row in stages)}


def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """現在の主/独立/共有/入力指紋と、旧証明へ委ねる範囲を記録する。

    引数: study/work/resolved(Path)は保存先/解決台帳、master(dict)は主準備、audit(Audit)は照合先。
    返り値: dictは共通証明骨格。旧価格分析を40で再検算したとは記さない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        **{name.removesuffix(".json") + "SHA256": V.sha(study / name)
            for name in ("入口参照.json", "対照参照.json", "指標参照.json")},
        "旧価格発動の検算": "固定39/38/37の成功証明へSHA接続。40では旧P/MACD/数量Mを再算せず、3分ATR/TRを新たに独立検算する。",
        "厳密範囲": "固定39J0純13列は現ATR原値も完全一致。原8列由来3分SOURCEとTR、正本前ATRfloatを定義とする全判定/全3分投影SHAは厳密。独立ATR全足はabs1e-10/rel0とD整数厳密で別照合し、再算ATRのTR比較符号/全採否もstrict一致必須。生ATR全内容SHA同一を主張せず、許容を採否epsilonへ使わない。"}


def prepare(study: Path, work: Path) -> dict:
    """root起動の準備だけで全3分ATR・精密TR・前ATR影響と全Wを比較する。

    引数: study/work(Path)は40保存先。
    返り値: dictは非先着/非損益証明。原BBO先着・運用・金額は呼ばない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    for main, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "固定J0/原3分ATR/TR/再算符号影響/全W", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    count = sum(row["W0登録数"] for row in stages)
    audit.check("全W0旧J0数", count, sum(len(rows) for rows in bundle["pure"].values()))
    audit.check("主旧J0登録数", master["旧J0登録数"], count)
    old_state = V.read(ENTRY_STUDY / "状態独立確認.json")
    audit.check("旧39J0件数証明", count, old_state["方針別case数"]["J0"])
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "旧39J0純登録同値": audit.mismatches == 0, "旧J0登録数": count,
        "場別準備": stages, **numeric_summary(stages),
        **{key: value for key, value in bundle.items() if key.endswith("展開SHA256")},
        "検証範囲": "固定39J0の全13値を保持。原8列3分OHLC/ATR14を独立再算し保存29全足へ限定許容/追尾D整数で照合。正本ATRを判断の定義として独立OHLCの精密TR/差/比/前足mask/全W/全SHAを厳密再現し、さらに再算ATRでもTR比較符号と全採否がstrict一致することを別確認する。",
        "限界": "非先着/非運用/非PnL。旧P/MACD/数量Mは39/38/37証明へ委ねる。保存前ATRの分数整合と独立ATRの数値/符号影響を分離し、15分を新計算しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧J0登録数")}, ensure_ascii=False))
    return proof


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """正式開始前に成功した独立準備と固定の現在版を要求する。

    引数: study/work/resolved(Path)は保存先/解決台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。差があれば正式の市場入力前に停止する。
    """
    prepared = V.read(work / "独立準備点検.json")
    expected = proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "入口参照SHA256", "対照参照SHA256", "指標参照SHA256"):
        audit.check("独立準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("独立準備成功:" + key, prepared[key], value)
    for path, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + path, V.sha(ROOT / path), digest)
    if audit.mismatches:
        raise ValueError("成功準備/固定/現版に差があり市場入力前停止")


def run(study: Path, work: Path) -> dict:
    """正式後に全値幅判定/全case直接先着と旧J0全属性対照を確認する。

    引数: study/work(Path)は40保存先。
    返り値: dictは正式状態証明。全Wの新caseを正常BBO原列で直接検算する。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    old_cases = {row["イベントID"]: row for row in old_rows if row["入口ID"] == "3分_J0"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "全運用詳細.jsonl.gz", audit)
    old_details = {row["場"]: row for row in old_rows if row["候補ID"] == "3分_J0_XF"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "追尾.jsonl.gz", audit)
    old_logs = defaultdict(list)
    for row in old_rows:
        if row["候補ID"] == "3分_J0_XF":
            old_logs[row["場"]].append(row)
    names = ("値幅判定", "入口事例", "全運用詳細", "追尾")
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
        audit.check(session + ":正式全値幅判定", grouped["値幅判定"][session], [{"期間": period, **row} for row in block["判定"]])
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":case全純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            policy = signal["入口ID"].removeprefix("3分_")
            original = signal["イベントID"][:-3] + "_J0"
            direct = label_direct(quotes, signal, cutoff, deadline)
            metadata = bundle["metadata"][original]
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": metadata["元価格発動ID"], "元価格side": metadata["元価格side"], "旧J0イベントID": original, **direct}
            audit.check(signal["イベントID"] + ":全case原BBO直接先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全case厳密値", cases.get(signal["イベントID"]) == expected, True)
            audit.check(signal["イベントID"] + ":旧同時計順行11label", direct, {key: old_cases[original][key] for key in LABEL_FIELDS})
            label_counts[policy] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] != "3分_W0_XF":
                continue
            trace = [row for row in grouped["追尾"][session] if row["候補ID"] == detail["候補ID"]]
            adapted, adapted_logs = rename(detail, "_W0", "_J0"), rename(trace, "_W0", "_J0")
            audit.leaf(session + ":旧39J0全ledger同値", adapted, old_details[session], adapted == old_details[session])
            audit.leaf(session + ":旧39J0全trace同値", adapted_logs, old_logs[session], adapted_logs == old_logs[session])
            controls.append({"場": session, "候補ID": detail["候補ID"], "全運用同値": adapted == old_details[session],
                "全追尾同値": adapted_logs == old_logs[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
        print(json.dumps({"場": session, "独立状態": "全3分ATR/TR/再算符号影響/全W/直接先着/旧J0対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("全case数", len(saved["入口事例"]), sum(label_counts.values()))
    audit.check("W0旧全J0数", label_counts["W0"], len(old_cases))
    audit.check("W0保存対照証明", V.read(study / "W0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, "旧J0登録数": label_counts["W0"],
        "方針別case数": label_counts, "全先着直接照合件数": sum(label_counts.values()), "方針別先着直接照合件数": label_counts,
        "旧同時計順行先着照合数": sum(label_counts.values()), "旧39全属性同値場数": len(controls),
        **numeric_summary(stages),
        "保存値幅判定数": len(saved["値幅判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        **{key: value for key, value in bundle.items() if key.endswith("展開SHA256")},
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"), "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列3分OHLC/ATR14の全数値と追尾D、元J0の全13値を検算。保存正本ATR定義のTR/精密差比/全W/SHA整合と、独立ATRでの閾値符号/全採否strict一致を分ける。全caseを原正常BBOで直接125/250検算し旧同時計J0の11labelとも一致、W0旧39全66ledger/trace同値を確認。",
        "限界": "旧P/MACD/数量Mの発動再算は39/38/37成功証明へSHA接続。3分ATRは40で別検算するが生ATR完全SHA同値としない。新規受付/Decimalは別財務、全保有線と最初返済要求は別追尾。15分新計算なし。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧J0登録数", "旧39全属性同値場数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可後の準備又は固定後の状態監査だけを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00040の3分ATR/TRと現前値幅の独立検算")
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
