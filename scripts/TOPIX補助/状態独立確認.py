"""00044のTOPIX原8列・中心化MACD・場内OLSと跨商品公開採否を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00044_TOPIX方向とNK再テスト"
WORK = ROOT / "work/TOPIX補助/00044"
ENTRY_STUDY = ROOT / "study/00042_突破再テストと数量加重終値位置"
ENTRY_WORK = ROOT / "work/再テスト量方向/00042"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("X0", "X1", "X2")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)


def helper(path: Path, name: str) -> Any:
    """既固定独立補助だけをCLI起動せず読み込む。

    引数: path(Path)は独立補助、name(str)は識別。
    返り値: Anyは補助。44主の指標・入口・運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


OLD = helper(ROOT / "scripts/CMF変化/状態独立確認.py", "TOPIX補助の固定43独立出典")
Y, G, N, S, V = OLD.Y, OLD.G, OLD.N, OLD.S, OLD.V
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS, FRAME_FIELDS = OLD.SIGNAL_FIELDS, OLD.LABEL_FIELDS, OLD.SOURCE_FIELDS, OLD.FRAME_FIELDS
AUX_FIELDS = ("場", *SOURCE_FIELDS, "価格数値入力可", "macd_hist", "MACD原点", "MACD原点出典")
canonical_sha, decision_signal, finite, exact = OLD.canonical_sha, OLD.decision_signal, OLD.finite, OLD.exact
normal_columns, label_direct, frame_projection, saved_rows = OLD.normal_columns, OLD.label_direct, OLD.frame_projection, OLD.saved_rows
rename = OLD.rename
NO_VISIBLE = "TOPIX同終了strict事前公開参照なし"
H_FIELDS = ("macd_hist", "MACDヒスト現", "MACDヒスト前", "MACDヒスト変化")


class Audit(G.Audit):
    """H本体・現前表示alias・差だけを限定許容とし全符号は厳密比較する。"""

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """Hの数値表現差を記録し、有限準備・符号を許容へ混ぜない。

        引数: name(str)は末端経路、actual/expected(Any)は比較値。
        返り値: None。非H価格・出典の厳密性は別射影と正本定義SHAでも要求する。
        """
        field = name.rsplit(":", 1)[-1]
        if field in H_FIELDS and finite(actual) and finite(expected):
            stats = self.macd_differences.setdefault(field, {"全数値leaf": 0, "leaf差数": 0, "最大絶対差": 0.0})
            stats["全数値leaf"] += 1
            stats["leaf差数"] += int(actual != expected)
            stats["最大絶対差"] = max(stats["最大絶対差"], abs(actual - expected))
            if actual != expected and len(self.macd_examples) < 20:
                self.macd_examples.append({"経路": name, "主": actual, "独立": expected, "絶対差": abs(actual - expected)})
            self.leaf(name, actual, expected, math.isclose(actual, expected, abs_tol=1e-10, rel_tol=0))
            left, right = (actual > 0) - (actual < 0), (expected > 0) - (expected < 0)
            self.macd_sign_diffs += int(left != right)
            self.leaf(name + ":厳密符号", left, right, left == right)
            return
        super().check(name, actual, expected)


def judgment_projection(value: Any) -> Any:
    """H表示値だけを有限性・符号へ写して全残余属性を保持する。

    引数: value(Any)は全足・全panel・全decision等のJSON値。
    返り値: Anyは準備・全符号・全採否を厳密比較する新しい射影。
    """
    if isinstance(value, dict):
        return {key: ({"有限": True, "符号": (item > 0) - (item < 0)} if finite(item) else deepcopy(item))
                if key in H_FIELDS else judgment_projection(item) for key, item in value.items()}
    if isinstance(value, list):
        return [judgment_projection(item) for item in value]
    return deepcopy(value)


def compare_h_scope(name: str, defined: Any, independent: Any, audit: Audit) -> bool:
    """Hだけ限定許容で比較し、全残余値・有限性・符号・採否を別の厳密JSONで確認する。

    引数: name(str)は範囲、defined/independent(Any)は定義/生値、audit(Audit)は比較先。
    返り値: boolは表示Hを除く全判断射影の厳密一致。不一致はauditにも保存する。
    """
    audit.check(name + ":全数値", defined, independent)
    left, right = judgment_projection(defined), judgment_projection(independent)
    same = canonical_sha(left) == canonical_sha(right)
    audit.check(name + ":非H/準備/符号/採否の厳密射影", same, True)
    return same


# ----------------------------------------
# 新しい関連市場だけを原8列から再構築する。NK旧監視は固定証明と保存出典を共有する。

def aux_projection(row: dict | None) -> dict | None:
    """TOPIXの価格出典と限定数値17列を選ぶ。

    引数: row(dict|None)はTOPIX数値足。
    返り値: dict|Noneは出典とH/原点。数量・ATR・BBO正常を採否へ混ぜない。
    """
    if row is None:
        return None
    if row["minutes"] != 3:
        raise ValueError("TOPIX補助は3分だけ")
    return {key: deepcopy(row[key]) for key in AUX_FIELDS}


class AuxiliaryHistory:
    """固定独立EMAを使い、TOPIX固有の原点と契約銀行を保持する。"""

    def __init__(self) -> None:
        """TOPIX銀行を未準備にする。

        引数: なし。
        返り値: None。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """中心化MACDと原点出典を解除する。

        引数: なし。
        返り値: None。契約識別は保持する。
        """
        self.center, self.origin_source = G.CenteredMACD(), None

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """OHLCから独立Hを順次計算し、全幅NPも内部銀行へ投入する。

        引数: frames(list[dict])は3分原足、session(str)は場、contract(tuple)はTOPIX限月、
        tail_missing(int)は末尾完全欠枠。
        返り値: tuple[list[dict],dict]は17列と限定品質。局所公開可否は別判定。
        """
        if len(contract) != 1 or any(f["minutes"] != 3 or f["end"] - f["start"] != 180 for f in frames):
            raise ValueError("一意のTOPIX契約と完全180秒足のみ")
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous_index, previous_key, clears = [], None, None, int(changed)
        for f in frames:
            index, key = f["index"], (f["confirm"], f["confirm_line"])
            if previous_index is not None and index <= previous_index:
                raise ValueError("TOPIX足番号順")
            if f["publish"] and (f["confirm"] < f["end"] or previous_key is not None and key < previous_key):
                raise ValueError("TOPIX終了前公開または公開key後退")
            valid = N.valid_ohlc(f)
            if index != (0 if previous_index is None else previous_index + 1) or f["missing"] or not valid:
                self.clear()
                clears += 1
            hist = None
            if valid:
                if self.center.origin is None:
                    self.origin_source = {"場": session, **N.source(f)}
                hist = self.center.add(f["close"])["macd_hist"]
            rows.append({"場": session, **N.source(f), "価格数値入力可": valid, "macd_hist": hist,
                         "MACD原点": self.center.origin, "MACD原点出典": deepcopy(self.origin_source)})
            previous_index = index
            if f["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        quality = {"場": session, "時間足分": 3, "入力足数": len(rows),
                   "価格数値入力足数": sum(r["価格数値入力可"] for r in rows),
                   "MACD準備足数": sum(finite(r["macd_hist"]) for r in rows),
                   "数値clear数": clears, "尾部完全欠枠": tail_missing,
                   "非公開価格数値更新数": sum(not r["publish"] and r["価格数値入力可"] for r in rows),
                   "場末MACD原点": self.center.origin, "全足SHA256": canonical_sha(rows)}
        return rows, quality


def slope20(values: list[float]) -> dict:
    """中心偏差の共分散和から20終値OLS傾きを別式で求める。

    引数: values(list[float])は古い順の終値。
    返り値: dictは準備・厳密傾き・符号。ゼロ傾きも準備可。
    """
    ready = len(values) == 20 and all(finite(v) for v in values)
    value = None
    if ready:
        ys = [Fraction(v) for v in values]
        mean_y, mean_x = sum(ys) / 20, Fraction(19, 2)
        denominator = sum((Fraction(i) - mean_x) ** 2 for i in range(20))
        value = sum((Fraction(i) - mean_x) * (y - mean_y) for i, y in enumerate(ys)) / denominator
    return {"準備": ready, "傾き": exact(value), "符号": (value > 0) - (value < 0) if ready else None}


def price_reasons(frame: dict) -> list[str]:
    """TOPIXの公開価格足の適格性を数量・気配から分けて検査する。

    引数: frame(dict)は限定価格足。
    返り値: list[str]は順序固定の理由。
    """
    reasons = []
    if not frame["publish"]:
        reasons.append("TOPIX非公開足")
    if not frame["価格数値入力可"] or not N.valid_ohlc(frame):
        reasons.append("TOPIX価格数値入力不正")
    if frame["missing"] != 0:
        reasons.append("TOPIX欠枠あり")
    if frame["minutes"] != 3 or frame["end"] - frame["start"] != 180:
        reasons.append("TOPIX完全180秒不成立")
    if frame["confirm"] < frame["end"]:
        reasons.append("TOPIX終了前公開")
    return reasons


def auxiliary_panels(frames: list[dict], session: str) -> list[dict]:
    """切断ごとのprefix末尾を直接sliceし、OLSと隣接ヒストを計算する。

    引数: frames(list[dict])は当場17列、session(str)は場。
    返り値: list[dict]は全補助判定。未可視足を採否へ入れない。
    """
    history, previous, public_key, output = [], None, None, []
    for raw in frames:
        frame = aux_projection(raw)
        if frame["場"] != session:
            raise ValueError("当場TOPIXだけ")
        if previous is not None and previous["index"] >= frame["index"]:
            raise ValueError("TOPIX足番号はstrict昇順")
        key = frame["confirm"], frame["confirm_line"]
        if frame["publish"]:
            if public_key is not None and key < public_key:
                raise ValueError("TOPIX公開key後退")
            public_key = key
        current_bad = price_reasons(frame)
        joined = previous is not None and (previous["index"] + 1 == frame["index"]
            and previous["end"] == frame["start"]
            and (previous["confirm"], previous["confirm_line"]) <= key)
        reasons = list(current_bad)
        if previous is not None and not joined:
            reasons.append("TOPIX番号区間公開順非連続")
        if reasons:
            history = []
        if not current_bad:
            history.append(frame)
        window = history[-20:]
        ols = slope20([r["close"] for r in window])
        pair = not current_bad and joined and not price_reasons(previous)
        prior = previous if pair else None
        change = frame["macd_hist"] - prior["macd_hist"] if prior is not None and finite(frame["macd_hist"]) and finite(prior["macd_hist"]) else None
        exclusions = list(current_bad)
        if not ols["準備"]:
            exclusions.append("TOPIX同場OLS20未準備")
        if not pair:
            exclusions.append("TOPIX当場隣接公開現前未準備")
        if not finite(change):
            exclusions.append("TOPIX現前MACDヒスト有限未準備")
        latest = max(((r["confirm"], r["confirm_line"]) for r in window), default=None)
        output.append({"場": session, "index": frame["index"], "足出典": frame,
            "前足出典": deepcopy(prior), "OLS20窓足番号": [r["index"] for r in window],
            "OLS20傾き": ols["傾き"], "OLS20傾き符号": ols["符号"],
            "MACDヒスト現": frame["macd_hist"], "MACDヒスト前": prior["macd_hist"] if prior else None,
            "MACDヒスト変化": change, "補助数値準備": not exclusions,
            "補助準備除外理由": exclusions, "窓解除理由": reasons,
            "窓最遅公開key": list(latest) if latest is not None else None})
        previous = frame
    return output


def pure_signal(row: dict, policy: str = "X0") -> dict:
    """旧A0純13から候補IDだけを変更する。

    引数: row(dict)は旧A0、policy(str)はX0/X1/X2。
    返り値: dictは当時のNK価格・ATR・役割を保持する。
    """
    if policy not in POLICIES or row["入口ID"] != "3分_A0" or not row["イベントID"].endswith("_A0"):
        raise ValueError("固定A0から三Xだけ")
    if row["役割"] not in ("順行", "反転") or row["side"] not in (-1, 1) or row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("固定実役割/方向不一致")
    value = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    value.update(入口ID="3分_" + policy, イベントID=row["イベントID"][:-3] + "_" + policy)
    return value


def select(block: dict, session: str | None = None) -> dict:
    """全TOPIX足を直接列挙し、strict先行かつ同終了だけを当時参照する。

    引数: block(dict)は固定NK純/旧j/下位出典とTOPIX全足、session(str|None)は場。
    返り値: dictは三集合・全j判定・全補助panel・小品質。
    """
    actual_session = session or block.get("場") or next((r["場"] for r in block["signals"]["3分_A0"]), None)
    if actual_session is None or type(block["商品照合"]) is not bool:
        raise ValueError("当場名と商品照合boolが必要")
    original, contexts = block["signals"]["3分_A0"], block["旧j判定"]
    panels = auxiliary_panels(block["補助足"], actual_session)
    nk_by_index = {r["index"]: r for r in block["frames"][3]}
    if len(nk_by_index) != len(block["frames"][3]):
        raise ValueError("NKindex重複")
    originals = {r["イベントID"]: r for r in original}
    expected = {r["発動ID"] + "_A0": Y.pure_signal(r, "A0") for r in contexts if r["戦略判定"]["A0"]["採用"]}
    keys = [(r["要求時計秒"], r["要求原板行"]) for r in original]
    if originals != expected or len(originals) != len(original) or keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError("旧A0純13集合不一致")
    if len({r["発動ID"] for r in contexts}) != len(contexts):
        raise ValueError("旧jID重複")
    decisions, metadata = [], {}
    for row in contexts:
        source = nk_by_index[row["index"]]
        if row["場"] != actual_session or source["場"] != actual_session or any(row[k] != source[k] for k in SOURCE_FIELDS):
            raise ValueError("NK旧j出典不一致")
        if (row["要求時計秒"], row["要求原板行"]) != (source["confirm"], source["confirm_line"]):
            raise ValueError("旧j公開key不一致")
        candidates = []
        for panel in panels:
            f = panel["足出典"]
            if f["publish"] and f["confirm"] < row["要求時計秒"] and f["end"] == source["end"]:
                candidates.append(panel)
        if len(candidates) > 1:
            raise ValueError("同終了TOPIXが複数")
        upper = candidates[0] if candidates else None
        exclusions = [] if block["商品照合"] else ["NKとTOPIXの限月年月不一致"]
        if upper is None:
            exclusions.append(NO_VISIBLE)
        else:
            if upper["窓最遅公開key"] is not None and upper["窓最遅公開key"][0] >= row["要求時計秒"]:
                raise ValueError("回帰窓の未来公開")
            if upper["前足出典"] is not None and upper["前足出典"]["confirm"] >= row["要求時計秒"]:
                raise ValueError("前足の未来公開")
            exclusions.extend(upper["補助準備除外理由"])
        ready, side = not exclusions, row["side"]
        aligned = bool(ready and side in (-1, 1) and side * upper["OLS20傾き符号"] > 0 and side * upper["MACDヒスト変化"] > 0)
        old = bool(row["戦略判定"]["A0"]["採用"])
        verdicts = {"X0": {"採用": old, "理由": list(row["戦略判定"]["A0"]["理由"]), "同時競合": row["戦略判定"]["A0"].get("同時競合", False)},
            "X1": {"採用": old and ready, "理由": ["旧A0採用・TOPIX共通準備"] if old and ready else ["旧A0不採用"] if not old else list(exclusions), "同時競合": False},
            "X2": {"採用": old and aligned, "理由": ["旧A0採用・TOPIX方向勢い一致"] if old and aligned else ["旧A0不採用"] if not old else list(exclusions) if not ready else ["TOPIX方向勢い実方向strict正不成立"], "同時競合": False}}
        event, old_id = row["発動ID"], row["発動ID"] + "_A0"
        parent = {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
            "元登録時計秒": row["登録参照"]["登録足"]["confirm"],
            "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]}
        if old:
            metadata[old_id] = parent
        decisions.append({"場": actual_session, "発動ID": event, "元42j発動ID": event,
            "元42A0イベントID": old_id if old else None, **parent,
            "index": row["index"], "足終了時計秒": row["end"],
            "要求時計秒": row["要求時計秒"], "要求原板行": row["要求原板行"], "side": side, "役割": row["役割"],
            "旧A0採用": old, "商品照合": block["商品照合"], "補助参照": deepcopy(upper),
            "補助準備": ready, "準備除外理由": exclusions, "戦略判定": verdicts})
    selected = {r["元42A0イベントID"]: r for r in decisions if r["旧A0採用"]}
    grouped = {"3分_" + p: [] for p in POLICIES}
    for row in original:
        if row["場"] != actual_session:
            raise ValueError("旧A0場不一致")
        for p in POLICIES:
            if selected[row["イベントID"]]["戦略判定"][p]["採用"]:
                grouped["3分_" + p].append(pure_signal(row, p))
    quality = {"場": actual_session, "時間足分": 3, "旧j判定数": len(contexts), "旧A0純登録数": len(original), "旧A0純登録同値": True,
        "TOPIX足数": len(block["補助足"]), "補助判定足数": len(panels), "TOPIX補助数値準備足数": sum(p["補助数値準備"] for p in panels),
        "同終了事前公開参照数": sum(d["補助参照"] is not None for d in decisions),
        "戦略別発動数": {sid: len(values) for sid, values in grouped.items()},
        "戦略採否理由別": {p: dict(Counter(reason for d in decisions for reason in d["戦略判定"][p]["理由"])) for p in POLICIES}}
    block.update(signals=grouped, decisions=decisions, aux_panels=panels, quality=quality, metadata=metadata)
    return block


# ----------------------------------------
# 準備・正式CLIはrootがそれぞれ一回起動する。

def dependency_pins() -> dict:
    """固定独立数値・直接先着・追尾と入力監査の依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対パスと現在SHA。
    """
    paths = ("scripts/CMF変化/状態独立確認.py", "scripts/TOPIX補助/入力監査.py",
             "scripts/CMF変化/追尾独立確認.py")
    return dict(sorted({**OLD.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))


def shared_bundle(audit: Audit) -> dict:
    """旧42全j/純と29のNK保存数値だけを出典検査して共有する。

    引数: audit(Audit)は比較先。
    返り値: dictはNK材料と旧共有SHA。旧ラベルは直ちに純13へ射影する。
    """
    base = Y.shared_bundle(audit)
    cases, case_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    pure, old_j = defaultdict(list), defaultdict(list)
    for row in cases:
        if row["入口ID"] == "3分_A0":
            pure[row["場"]].append({key: deepcopy(row[key]) for key in SIGNAL_FIELDS})
    old_rows, decision_sha = saved_rows(ENTRY_STUDY, ENTRY_WORK, "発動判定.jsonl.gz", audit)
    for row in old_rows:
        old_j[row["場"]].append({key: deepcopy(value) for key, value in row.items() if key != "期間"})
    return {**base, "pure": pure, "old_j": old_j,
            "共有入口事例展開SHA256": case_sha, "共有旧発動判定展開SHA256": decision_sha}


def input_bindings(study: Path) -> dict:
    """TOPIX参照・台帳・監査・予約の4指紋を正本へ接続する。

    引数: study(Path)は44。
    返り値: dictは現在SHA256。
    """
    ref = V.read(study / "TOPIX入力参照.json")
    return {"TOPIX入力参照SHA256": V.sha(study / "TOPIX入力参照.json"),
            **{"TOPIX" + name + "SHA256": V.sha(ROOT / ref[name]["パス"])
               for name in ("入力台帳", "入力監査", "入力予約")}}


def references(study: Path, audit: Audit) -> None:
    """旧NK証明と新TOPIX入力監査を結び未監査入力は数値計算前に止める。

    引数: study(Path)は44、audit(Audit)は比較先。
    返り値: None。NK原監視/Q/ATR/Hの再計算は行わない。
    """
    OLD.references(study, audit)
    old43 = V.read(ROOT / "study/00043_再テスト時のCMF変化方向/状態独立確認.json")
    audit.check("固定43状態成功", (old43["全件一致"], old43["不一致数"]), (True, 0))
    audit.check("固定43旧42純245", old43["旧A0登録数"], 245)
    ref = V.read(study / "TOPIX入力参照.json")
    audit.check("TOPIX入力参照集合", set(ref), {"入力台帳", "入力監査", "入力予約", "原板複製"})
    audit.check("TOPIX原複製なし", ref["原板複製"], False)
    for name in ("入力台帳", "入力監査", "入力予約"):
        path = (ROOT / ref[name]["パス"]).resolve()
        audit.check("TOPIX参照範囲:" + name, path.is_relative_to(WORK.resolve()), True)
        audit.check("TOPIX参照SHA:" + name, V.sha(path), ref[name]["SHA256"])
    proof = V.read(ROOT / ref["入力監査"]["パス"])
    for name, expected in (("全件一致", True), ("不一致数", 0), ("不一致", [])):
        audit.check("TOPIX入力監査:" + name, proof[name], expected)
    audit.check("TOPIX監査予約SHA", proof["入力予約SHA256"], ref["入力予約"]["SHA256"])
    audit.check("TOPIX監査台帳SHA", proof["入力台帳SHA256"], ref["入力台帳"]["SHA256"])
    for path, digest in proof["出典SHA256"].items():
        audit.check("TOPIX監査出典現在:" + path, V.sha(ROOT / path), digest)
    reservation = V.read(ROOT / ref["入力予約"]["パス"])
    manifest, _ = G.resolved_manifest(study)
    names = [entry["session"] for entry in manifest["entries"]]
    audit.check("TOPIX予約同66", [entry["session"] for entry in reservation["対象"]], names)
    auxiliary = topix_manifest(study)
    audit.check("TOPIX台帳同66", [entry["session"] for entry in auxiliary["entries"]], names)
    audit.check("TOPIX予約数", len(names), 66)
    for entry in auxiliary["entries"]:
        audit.check(entry["session"] + ":商品TOPIX", entry["symbol"], "TOPIX")
        audit.check(entry["session"] + ":年月", entry["限月年月"], "2026-12")
        audit.check(entry["session"] + ":場内年月", entry["場内限月年月"], ["2026-12"])
    audit.check("未予約11/5Day除外", "2026-11-05_Day" in names, False)


def topix_manifest(study: Path) -> dict:
    """指紋確認済み参照からTOPIX66台帳だけを読む。

    引数: study(Path)は44。
    返り値: dictは入力台帳。原板は開かない。
    """
    ref = V.read(study / "TOPIX入力参照.json")
    return V.read(ROOT / ref["入力台帳"]["パス"])


def read_definition(work: Path, master: dict, audit: Audit) -> dict[str, dict[int, dict]]:
    """主準備が保存した小型H定義を圧縮・展開指紋と全行構造まで検査する。

    引数: work(Path)は44作業先、master(dict)は主準備、audit(Audit)は比較先。
    返り値: dictは場→index→3列定義。独立Hをこれで計算し直さない。
    """
    info = master["TOPIX数値定義"]
    audit.check("H定義参照keys", set(info), {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"})
    if set(info) != {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"}:
        raise ValueError("H定義参照keys不一致")
    path = (ROOT / info["パス"]).resolve()
    audit.check("H定義保存先", path, (work / "TOPIX数値定義.jsonl.gz").resolve())
    if path != (work / "TOPIX数値定義.jsonl.gz").resolve():
        raise ValueError("H定義の保存先範囲差")
    audit.check("H定義圧縮SHA", V.sha(path), info["圧縮SHA256参考"])
    if audit.mismatches:
        raise ValueError("H定義圧縮指紋に差があり展開前停止")
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            rows.append(json.loads(raw))
    audit.check("H定義展開SHA", digest.hexdigest(), info["展開内容SHA256"])
    audit.check("H定義行数", len(rows), info["行数"])
    sessions = [row["場"] for row in master["準備"]]
    output, order = defaultdict(dict), []
    for row in rows:
        valid = (isinstance(row, dict) and set(row) == {"場", "index", "macd_hist"} and row["場"] in sessions
                 and type(row["index"]) is int and row["index"] >= 0
                 and (row["macd_hist"] is None or finite(row["macd_hist"])))
        audit.check("H定義行構造", valid, True)
        if not valid:
            raise ValueError("H定義に想定外の属性・数値がある")
        key = row["場"], row["index"]
        audit.check("H定義足一意:" + str(key), row["index"] not in output[row["場"]], True)
        output[row["場"]][row["index"]] = row
        order.append(key)
    audit.check("H定義全行昇順", order == sorted(order), True)
    expected = [(row["場"], row["TOPIX足数"]) for row in master["準備"]]
    audit.check("H定義場別全足数", [(session, len(output[session])) for session in sessions], expected)
    if audit.mismatches:
        raise ValueError("小型H定義・主準備の出典に差がありcache前停止")
    return dict(output)


def define_rows(rows: list[dict], values: dict[int, dict], session: str) -> list[dict]:
    """独立SOURCE/原点出典を保持し、保存正本Hの定義列を作る。

    引数: rows(list[dict])は独立生17列、values(dict)は同場H定義、session(str)は場。
    返り値: list[dict]はHだけ定義値に置換した列。数値差は別全件照合を必須とする。
    """
    if {row["index"] for row in rows} != set(values):
        raise ValueError("独立足とH定義のindex集合差")
    output = []
    for row in rows:
        value = values[row["index"]]
        if row["場"] != session or value["場"] != session:
            raise ValueError("H定義の場不一致")
        output.append({**deepcopy(row), "macd_hist": value["macd_hist"]})
    return output


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """非損益主準備と三案・費用・入力・使用数値版を市場入力前に照合する。

    引数: study/work(Path)は44保存先、audit(Audit)は比較先。
    返り値: tupleは条件/解決台帳/主準備/台帳path。差があればcache前に停止する。
    """
    config, (manifest, resolved) = V.read(study / "条件.json"), G.resolved_manifest(study)
    references(study, audit)
    old, fee = V.read(INDICATOR_STUDY / "条件.json"), V.read(EXIT_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒",
            "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("固定評価尺度:" + key, config[key], old[key])
    for key in ("運用", "必須追尾"):
        audit.check("固定33費用出口:" + key, config[key], fee[key])
    audit.check("三入口", config["戦略"], list(POLICIES))
    audit.check("三XF", config["運用組合せ"], [{"戦略": p, "出口ID": "XF"} for p in POLICIES])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True, "旧A0純登録同値": True, "旧A0登録数": 245,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        "指標参照SHA256": V.sha(study / "指標参照.json"),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json"), **input_bindings(study)}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/TOPIX補助/" + name for name in ("検証.py", "入口.py", "指標.py", "運用.py")}
    audit.check("主四コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("入力/主準備/数値参照に差があり市場入力前停止")
    return config, manifest, master, resolved



def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """主版・入力・独立依存と数値責任の三段階を結ぶ。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: dictは準備/正式共通proof。旧NK責務は固定証明へ、新TOPIX責務は今回独立計算へ分ける。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "指標参照SHA256": V.sha(study / "指標参照.json"),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "対照参照SHA256": V.sha(study / "対照参照.json"),
        "厳密範囲": "NK旧OHLC/Q/ATR/H/42監視と純13は42/43成功証明と保存SHAを共有。TOPIX原8列からSOURCE/中心化H/原点出典/OLS20を独立再算し、H本体・現/前alias・差だけabs1e-10/rel0で全件検算。H以外・全有限準備・全H/差符号・全採否はstrict。検算済み正本Hで定義17列/全panel/全decisionのSHAを厳密再現し、独立生HのJSON表示差・生SHA差は参考として分離する。採否epsilon/丸めなし。",
        **input_bindings(study), "TOPIX数値定義": deepcopy(master["TOPIX数値定義"]),
        "H限定数値leaf比較_重複含む": deepcopy(audit.macd_differences),
        "H厳密符号不一致leaf数": audit.macd_sign_diffs,
        "数値許容": {"対象": ["TOPIX macd_hist", "TOPIX MACDヒスト現", "TOPIX MACDヒスト前", "TOPIX MACDヒスト変化"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True}}



def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功した独立準備と全固定指紋を正式市場入力前に要求する。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・差ありは停止する。
    """
    prepared, expected = V.read(work / "独立準備点検.json"), proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "指標参照SHA256", "入口参照SHA256", "対照参照SHA256", "TOPIX入力参照SHA256", "TOPIX入力台帳SHA256", "TOPIX入力監査SHA256", "TOPIX入力予約SHA256", "TOPIX数値定義"):
        audit.check("準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("準備成功:" + key, prepared[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があり正式市場入力前停止")



def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """TOPIX原8列だけを新再構築し、固定NK材料へ同時点結合する。

    引数: manifest/bundle/config(dict)はNK台帳/共有NK/44条件。
    返り値: Anyは非先着・非損益の独立場別record。
    """
    auxiliary = bundle["topix_manifest"]
    by_session = {entry["session"]: entry for entry in auxiliary["entries"]}
    bank = AuxiliaryHistory()
    for entry in manifest["entries"]:
        session = entry["session"]
        topix = by_session[session]
        start, finish, _, _ = S.G.times(session)
        data = G.observed(topix, auxiliary)
        formed = S.bars(data, session, 3, N.BareBars())
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        independent, quality = bank.build(formed, session, tuple(topix["in_session_contract_codes"]), tail)
        rows = define_rows(independent, bundle["hist_definition"][session], session)
        material = {"場": session, "signals": {"3分_A0": deepcopy(bundle["pure"].get(session, []))},
            "frames": {3: bundle["lower"][session]}, "旧j判定": deepcopy(bundle["old_j"].get(session, [])),
            "補助足": rows, "商品照合": topix["限月年月"] == "2026-12"}
        selected = select(deepcopy(material), session)
        alternate = select({**deepcopy(material), "補助足": independent}, session)
        pure = [row for p in POLICIES for row in selected["signals"]["3分_" + p]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]),
            "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha(bundle["lower"][session]), "3分投影足数": len(bundle["lower"][session]),
            "入力品質": selected["quality"], "全TOPIX投影SHA256": canonical_sha(rows), "TOPIX足数": len(rows),
            "全補助判定SHA256": canonical_sha(selected["aux_panels"]), "補助判定足数": len(selected["aux_panels"]),
            "_旧A0純": deepcopy(bundle["pure"].get(session, [])), "_TOPIX全足": rows,
            "_TOPIX生全足": independent, "_TOPIX品質": quality, "_正本判断": selected,
            "_再算判断": alternate, "_metadata": selected["metadata"]}


def compare_preparation(main: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """全新数値SHA/全j採否/出典と旧純245のsubsetを照合する。

    引数: main/block(dict)は主/独立record、bundle(dict)は共有NK、audit(Audit)は比較先。
    返り値: dictは場別の検算範囲。差を許容に隠して採否を通さない。
    """
    session = block["場"]
    defined, independent = block["_TOPIX全足"], block["_TOPIX生全足"]
    selected, alternate = block["_正本判断"], block["_再算判断"]
    same_rows = compare_h_scope(session + ":独立生17列", defined, independent, audit)
    same_panels = compare_h_scope(session + ":独立生全補助panel", selected["aux_panels"], alternate["aux_panels"], audit)
    same_decisions = compare_h_scope(session + ":独立生全j判定", selected["decisions"], alternate["decisions"], audit)
    audit.check(session + ":独立生Hの全純13厳密", selected["signals"] == alternate["signals"], True)
    audit.check(session + ":独立生Hの全準備品質厳密", selected["quality"] == alternate["quality"], True)
    expected = {key: value for key, value in block.items() if not key.startswith("_")}
    audit.check(session + ":正本H定義全record", main, expected)
    audit.check(session + ":正本H定義全record厳密JSON", main == expected, True)
    for name in ("全TOPIX投影SHA256", "全補助判定SHA256"):
        audit.check(session + ":正本H定義全内容厳密:" + name, main[name], block[name])
    hist_differences = [abs(a["macd_hist"] - b["macd_hist"]) for a, b in zip(defined, independent, strict=True)
                        if finite(a["macd_hist"]) and finite(b["macd_hist"]) and a["macd_hist"] != b["macd_hist"]]
    alias_stats = {}
    for key in ("MACDヒスト現", "MACDヒスト前", "MACDヒスト変化"):
        differences = [abs(a[key] - b[key]) for a, b in zip(selected["aux_panels"], alternate["aux_panels"], strict=True)
                       if finite(a[key]) and finite(b[key]) and a[key] != b[key]]
        pairs = list(zip(selected["aux_panels"], alternate["aux_panels"], strict=True))
        alias_stats[key] = {"表現差足数": len(differences), "最大絶対差": max(differences, default=0.0),
            "準備不一致足数": sum(finite(a[key]) != finite(b[key]) for a, b in pairs),
            "符号不一致足数": sum((a[key] > 0) - (a[key] < 0) != (b[key] > 0) - (b[key] < 0)
                                    for a, b in pairs if finite(a[key]) and finite(b[key]))}
    old = {r["イベントID"]: r for r in block["_旧A0純"]}
    ids = {p: {r["イベントID"][:-3] + "_A0" for r in main["純信号"] if r["入口ID"] == "3分_" + p} for p in POLICIES}
    audit.check(session + ":X0全旧A0", ids["X0"], set(old))
    audit.check(session + ":X1準備subset", ids["X1"] <= ids["X0"], True)
    audit.check(session + ":X2方向subset", ids["X2"] <= ids["X1"], True)
    for signal in main["純信号"]:
        origin, p = signal["イベントID"][:-3] + "_A0", signal["入口ID"].removeprefix("3分_")
        audit.check(signal["イベントID"] + ":固定純13厳密", signal == pure_signal(old[origin], p), True)
    return {"場": session, "期間": block["期間"], **{p + "登録数": len(ids[p]) for p in POLICIES},
        "3分投影足数": block["3分投影足数"], "TOPIX足数": block["TOPIX足数"],
        "補助判定足数": block["補助判定足数"], "全j数": len(block["判定"]),
        "全TOPIX投影SHA256": block["全TOPIX投影SHA256"],
        "全補助判定SHA256": block["全補助判定SHA256"],
        "独立生TOPIX内容SHA256": canonical_sha(independent),
        "独立生補助判定SHA256": canonical_sha(alternate["aux_panels"]),
        "独立生全j判定SHA256": canonical_sha(alternate["decisions"]),
        "独立H表現差足数": len(hist_differences), "独立H最大絶対差": max(hist_differences, default=0.0),
        "独立H準備不一致足数": sum(finite(a["macd_hist"]) != finite(b["macd_hist"]) for a, b in zip(defined, independent, strict=True)),
        "独立H符号不一致足数": sum((a["macd_hist"] > 0) - (a["macd_hist"] < 0) != (b["macd_hist"] > 0) - (b["macd_hist"] < 0)
            for a, b in zip(defined, independent, strict=True) if finite(a["macd_hist"]) and finite(b["macd_hist"])),
        "H表示alias表現差": alias_stats,
        "独立生17列判断同値": same_rows, "独立生全補助判断同値": same_panels,
        "独立生全j判断同値": same_decisions,
        "独立生TOPIX内容SHA差": canonical_sha(independent) != block["全TOPIX投影SHA256"],
        "独立生補助内容SHA差": canonical_sha(alternate["aux_panels"]) != block["全補助判定SHA256"],
        "独立生全j内容SHA差": canonical_sha(alternate["decisions"]) != block["判定SHA256"],
        "TOPIX全内容厳密SHA同値": main["全TOPIX投影SHA256"] == block["全TOPIX投影SHA256"],
        "定義判定全文厳密同値": main["判定"] == block["判定"],
        "新採否判断厳密同値": same_decisions}


def numeric_summary(stages: list[dict]) -> dict:
    """旧NK共有範囲と新TOPIX直接再算範囲を別集計する。

    引数: stages(list[dict])は場別要約。
    返り値: dictは全足・全jの件数と厳密不一致場数。
    """
    return {"共有NK3分足数": sum(r["3分投影足数"] for r in stages),
        "TOPIX独立再構築足数": sum(r["TOPIX足数"] for r in stages),
        "全TOPIX補助判定足数": sum(r["補助判定足数"] for r in stages),
        "全旧j新採否数": sum(r["全j数"] for r in stages),
        "TOPIX全内容SHA不一致場数": sum(not r["TOPIX全内容厳密SHA同値"] for r in stages),
        "正本定義判定全文不一致場数": sum(not r["定義判定全文厳密同値"] for r in stages),
        "独立生17列判断不一致場数": sum(not r["独立生17列判断同値"] for r in stages),
        "独立生全補助判断不一致場数": sum(not r["独立生全補助判断同値"] for r in stages),
        "新採否厳密不一致場数": sum(not r["新採否判断厳密同値"] for r in stages),
        "独立H表現差足数": sum(r["独立H表現差足数"] for r in stages),
        "独立H最大絶対差": max((r["独立H最大絶対差"] for r in stages), default=0.0),
        "独立H準備不一致足数": sum(r["独立H準備不一致足数"] for r in stages),
        "独立H符号不一致足数": sum(r["独立H符号不一致足数"] for r in stages),
        "独立生TOPIX内容SHA差場数_参考": sum(r["独立生TOPIX内容SHA差"] for r in stages),
        "独立生補助内容SHA差場数_参考": sum(r["独立生補助内容SHA差"] for r in stages),
        "独立生全j内容SHA差場数_参考": sum(r["独立生全j内容SHA差"] for r in stages),
        "H表示alias表現差": {key: {"表現差足数": sum(r["H表示alias表現差"][key]["表現差足数"] for r in stages),
            "最大絶対差": max((r["H表示alias表現差"][key]["最大絶対差"] for r in stages), default=0.0),
            "準備不一致足数": sum(r["H表示alias表現差"][key]["準備不一致足数"] for r in stages),
            "符号不一致足数": sum(r["H表示alias表現差"][key]["符号不一致足数"] for r in stages)}
            for key in ("MACDヒスト現", "MACDヒスト前", "MACDヒスト変化")}}


def prepare(study: Path, work: Path) -> dict:
    """root起動で共有NKと新TOPIX数値・公開時点三案を非損益検算する。

    引数: study/work(Path)は44保存先。
    返り値: dictは旧label/新先着/運用/PnLを計算しない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    bundle["topix_manifest"] = topix_manifest(study)
    bundle["hist_definition"] = read_definition(work, master, audit)
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原TOPIX/中心化H/OLS20・strict跨商品公開/全X", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    count = sum(row["X0登録数"] for row in stages)
    audit.check("旧42A0全245", count, 245)
    audit.check("主旧42A0数", master["旧A0登録数"], count)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    audit.check("H定義実行中圧縮不変", V.sha(work / "TOPIX数値定義.jsonl.gz"), master["TOPIX数値定義"]["圧縮SHA256参考"])
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "旧A0純登録同値": audit.mismatches == 0, "旧A0登録数": count,
        "場別準備": stages, **numeric_summary(stages), "方針別登録数": {p: sum(row[p + "登録数"] for row in stages) for p in POLICIES},
        **{name: value for name, value in bundle.items() if name.endswith("展開SHA256")},
        "検証範囲": "監査済みTOPIX原8列から3分OHLC/中心化H/原点出典を独立構築。中心偏差OLS20/同場連続窓/現前H差/strict跨商品同end事前公開/全三採否を検算。H数値だけ限定許容で検算済み正本定義SHAと、独立生Hによる全準備/符号/採否strictを分離。生JSON表示差を判断差と呼ばない。NK全数値・42監視は固定42/43証明共有で今回再計算しない。",
        "限界": "非先着/非運用/非PnL。旧42caseは直ちに純13へ射影し旧labelをliveへ渡さない。価格時計strict先行は実受信先行を証明しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧A0登録数", "方針別登録数")}, ensure_ascii=False))
    return proof



def run(study: Path, work: Path) -> dict:
    """正式後に全判定/全新先着と旧42A0全属性対照を別に検算する。

    引数: study/work(Path)は44保存先。
    返り値: dictは新五明細/共有旧先着/全属性対照へbindする状態証明。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    bundle["topix_manifest"] = topix_manifest(study)
    bundle["hist_definition"] = read_definition(work, master, audit)
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "入口事例.jsonl.gz", audit)
    old_cases = {row["イベントID"]: row for row in old_rows if row["入口ID"] == "3分_A0"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "全運用詳細.jsonl.gz", audit)
    old_details = {row["場"]: row for row in old_rows if row["候補ID"] == "3分_A0_XF"}
    old_rows, _ = saved_rows(ENTRY_STUDY, ENTRY_WORK, "追尾.jsonl.gz", audit)
    old_logs = defaultdict(list)
    for row in old_rows:
        if row["候補ID"] == "3分_A0_XF":
            old_logs[row["場"]].append(row)
    names = ("TOPIX全指標", "発動判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    audit.check("新五成果物集合", {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    stages, controls, counts = [], [], {p: 0 for p in POLICIES}
    role_counts = {p: {role: 0 for role in ("順行", "反転")} for p in POLICIES}
    entries = {row["session"]: row for row in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period = block["場"], block["期間"]
        expected_topix = [{"期間": period, **row} for row in block["_TOPIX全足"]]
        audit.check(session + ":正式TOPIX全17列", grouped["TOPIX全指標"][session], expected_topix)
        audit.check(session + ":正式TOPIX全17列厳密", grouped["TOPIX全指標"][session] == expected_topix, True)
        for actual, expected_topix_row in zip(grouped["TOPIX全指標"][session], expected_topix):
            for name in AUX_FIELDS:
                if name != "macd_hist":
                    audit.check(session + ":TOPIX厳密:" + name, actual[name] == expected_topix_row[name], True)
            if finite(actual["macd_hist"]) and finite(expected_topix_row["macd_hist"]):
                audit.check(session + ":TOPIXヒスト符号厳密",
                    (actual["macd_hist"] > 0) - (actual["macd_hist"] < 0),
                    (expected_topix_row["macd_hist"] > 0) - (expected_topix_row["macd_hist"] < 0))
        expected_rows = [{"期間": period, **row} for row in block["判定"]]
        audit.check(session + ":正式全jの現前判定", grouped["発動判定"][session], expected_rows)
        audit.check(session + ":正式全j厳密", grouped["発動判定"][session] == expected_rows, True)
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            event, original = signal["イベントID"][:-3], signal["イベントID"][:-3] + "_A0"
            direct = label_direct(quotes, signal, cutoff, deadline)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": event, **deepcopy(block["_metadata"][original]), "旧A0イベントID": original, **direct}
            audit.check(signal["イベントID"] + ":全新case原BBO直接先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全case厳密", cases.get(signal["イベントID"]) == expected, True)
            audit.check(signal["イベントID"] + ":旧同時計A0の11label形式対応", direct, {name: old_cases[original][name] for name in LABEL_FIELDS})
            policy = signal["入口ID"].removeprefix("3分_")
            counts[policy] += 1
            role_counts[policy][signal["役割"]] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
            if detail["候補ID"] == "3分_X0_XF":
                logs = [row for row in grouped["追尾"][session] if row["候補ID"] == detail["候補ID"]]
                adapted, adapted_logs = rename(detail, "_X0", "_A0"), rename(logs, "_X0", "_A0")
                audit.leaf(session + ":旧42A0全ledger同値", adapted, old_details[session], adapted == old_details[session])
                audit.leaf(session + ":旧42A0全trace同値", adapted_logs, old_logs[session], adapted_logs == old_logs[session])
                controls.append({"場": session, "候補ID": detail["候補ID"], "全運用同値": adapted == old_details[session],
                    "全追尾同値": adapted_logs == old_logs[session], "旧識別子全運用内容SHA256": canonical_sha(adapted),
                    "旧識別子追尾内容SHA256": canonical_sha(adapted_logs)})
        print(json.dumps({"場": session, "独立状態": "原TOPIX/OLS/H/asof・全case直接先着・旧A0対照", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    for row in result["入口評価"]:
        audit.check(row["入口ID"] + ":集合役割", row["役割"], "切替")
    role_groups = [(row["入口ID"], row["役割"]) for row in result["役割別入口評価"]]
    audit.check("全三案実二役割6群", set(role_groups), {("3分_" + p, role) for p in POLICIES for role in ("順行", "反転")})
    audit.check("役割群一意", len(role_groups), len(set(role_groups)))
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("X0旧A0全245", counts["X0"], len(old_cases))
    audit.check("X0保存全属性対照", V.read(study / "X0対照同値.json"), {"全件一致": True, "旧先着全件同値": True,
        "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json"),
        "対照参照SHA256": V.sha(study / "対照参照.json")})
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    audit.check("H定義実行中圧縮不変", V.sha(work / "TOPIX数値定義.jsonl.gz"), master["TOPIX数値定義"]["圧縮SHA256参考"])
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "旧A0登録数": counts["X0"], "方針別case数": counts, "方針実役割別case数": role_counts,
        "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": counts,
        "旧同時計実方向先着照合数": sum(counts.values()), "旧42全属性同値場数": len(controls),
        "保存TOPIX全指標数": len(saved["TOPIX全指標"]),
        "保存発動判定数": len(saved["発動判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        **{name: value for name, value in bundle.items() if name.endswith("展開SHA256")},
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "NK数値/42登録監視/全j/A0純245は既固定42/43証明と保存SHA共有。TOPIX原8列からOHLC/中心化H/OLS20/跨商品strict-asof/三採否を別算。H限定許容の数値比較/正本定義SHA/独立生Hでの全準備・符号・採否strictを分離。全新caseを実方向の原BBOから直接125/250検算し、旧A0の11label形式対応とX0全66ledger/trace同値を別確認する。",
        "限界": "旧labelを新判断へ渡さず、受信時計・跨商品行順を補完しない。新規受付/最初約定/Decimalは別会計、全実保有/最初返済要求は別追尾。全66場既使用、未予約11/5Day未読。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "旧A0登録数", "方針別case数")}, ensure_ascii=False))
    return proof



def main() -> None:
    """rootの非損益準備許可又は正式完了後だけ明示CLIを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定又は不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00044固定NK再テストとTOPIX同時点方向の独立検算")
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
