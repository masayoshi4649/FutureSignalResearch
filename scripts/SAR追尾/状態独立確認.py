"""00032の精密SARと公開時点、固定31入口のlive射影を独立に確認する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00032_最低同値床と公開SAR追尾"
WORK = ROOT / "work/SAR追尾/00032"
ENTRY_STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
ENTRY_WORK = ROOT / "work/CCI突破/00031"
POLICIES = ("C0", "C1")
EXITS = ("X0", "XS")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
OLD_LOCK_SHA = "b1a8cc4aec9def6907f65e0372ad8d280d62390e8059e83c1f38d6c927615cce"
OLD_CONDITION_SHA = "8d4cd04e02e26144f16375dea7e722fb84f7f6384a75606b925f1ea792d9ded1"


def helper(path: Path, name: str) -> Any:
    """既固定の独立OHLC・入口・比較補助だけを読み込む。

    引数: path (Path) は補助、name (str) は識別名。
    返り値: Any はモジュール。32主のSAR/運用をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


G = helper(ROOT / "scripts/CCI突破/状態独立確認.py", "SAR追尾の固定31独立足と入口")
B, S, V, P, SOURCE_FIELDS = G.B, G.S, G.V, G.P, G.SOURCE_FIELDS
Audit = G.Audit


# ----------------------------------------
# 精密SARは主を呼ばず、前状態の数式を原OHLCの有理数へ適用する。

class RationalSAR:
    """整数AFと有理数の前状態を用いてSARを別実装する。"""

    def __init__(self) -> None:
        """方向・前状態・直近原足を未準備へ戻す。

        引数: なし。
        返り値: None。
        """
        self.clear()

    def clear(self) -> None:
        """数値状態と原足の連続履歴を空にする。

        引数: なし。
        返り値: None。場/限月の管理は銀行側で行う。
        """
        self.direction, self.display, self.forecast, self.extreme, self.af = 0, None, None, None, 0
        self.history = []

    def step(self, frame: dict, session: str) -> dict:
        """原OHLC一足から事前線/現在表示/次足投影を有理数で求める。

        引数: frame (dict) は完全幅3分OHLC、session (str) は場。
        返り値: dict はFractionを含む独立数値。保存形式への変換は別処理で行う。
        """
        before_direction, before_forecast = self.direction, self.forecast
        before_extreme, before_af = self.extreme, self.af
        previous = deepcopy(self.history[-2:])
        numeric = B.valid_ohlc(frame)
        initial = reversed_now = False
        if numeric:
            high, low, close = (Fraction(frame[name]) for name in ("high", "low", "close"))
            if before_direction == 0:
                if previous and close != Fraction(previous[-1]["close"]):
                    direction = 1 if close > Fraction(previous[-1]["close"]) else -1
                    old_bound = Fraction(previous[-1]["low" if direction > 0 else "high"])
                    display = min(old_bound, low) if direction > 0 else max(old_bound, high)
                    extreme = high if direction > 0 else low
                    af, initial = 2, True
                else:
                    direction, display, extreme, af = 0, None, None, 0
            else:
                reverse = low < before_forecast if before_direction > 0 else high > before_forecast
                if reverse:
                    direction, af, reversed_now = -before_direction, 2, True
                    display = min(before_extreme, low) if direction > 0 else max(before_extreme, high)
                    extreme = high if direction > 0 else low
                else:
                    direction = before_direction
                    boundaries = [Fraction(row["low" if direction > 0 else "high"]) for row in previous]
                    display = min([before_forecast, *boundaries]) if direction > 0 else max([before_forecast, *boundaries])
                    observed_extreme = high if direction > 0 else low
                    improved = direction * (observed_extreme - before_extreme) > 0
                    extreme = observed_extreme if improved else before_extreme
                    af = min(20, before_af + 2) if improved else before_af
            self.direction, self.display, self.extreme, self.af = direction, display, extreme, af
            self.forecast = display + Fraction(af, 100) * (extreme - display) if direction else None
            self.history.append({"場": session, **B.source(frame)})
        ready = bool(numeric and self.direction != 0)
        return {"ready": ready, "numeric": numeric, "direction": self.direction if ready else 0,
            "before_direction": before_direction, "before_line": before_forecast if before_direction else None,
            "display": self.display if ready else None, "next_line": self.forecast if ready else None,
            "extreme": self.extreme if ready else None, "af": self.af if ready else 0,
            "before_extreme": before_extreme, "before_af": before_af,
            "initial": initial, "reversed": reversed_now, "previous_sources": previous}


def round_tick(value: Fraction, side: int) -> int:
    """Fractionの分子分母を整数除算し、買ceil/売floorの5pt線を求める。

    引数: value (Fraction) は精密価格、side (int) は買1/売-1。
    返り値: int は呼値単位の価格。floatへ戻して丸めない。
    """
    if side not in (-1, 1) or not isinstance(value, Fraction):
        raise ValueError("精密線と実方向±1が必要")
    numerator, denominator = value.numerator, value.denominator * 5
    ticks = -((-numerator) // denominator) if side > 0 else numerator // denominator
    return 5 * ticks


def pack(value: Fraction | None) -> dict | None:
    """精密値を符号付き16進の既約分子/正分母へ変換する。

    引数: value (Fraction|None) は精密SAR価格。
    返り値: dict|None は分子16進/分母16進。十進桁数制限やfloat丸めに依存しない。
    """
    return {"分子16進": hex(value.numerator), "分母16進": hex(value.denominator)} if value is not None else None


def unpack(value: dict | None) -> Fraction | None:
    """保存hexを有理数へ戻し、正分母と既約の正本表現を検査する。

    引数: value (dict|None) は精密保存値。
    返り値: Fraction|None は元の精密値。不正な非正分母や非正本表現は拒否する。
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"分子16進", "分母16進"}:
        raise ValueError("精密分数の保存属性が不正")
    numerator, denominator = int(value["分子16進"], 16), int(value["分母16進"], 16)
    if denominator <= 0:
        raise ValueError("精密分母は正")
    exact = Fraction(numerator, denominator)
    if pack(exact) != value:
        raise ValueError("精密値は既約hex正本だけ")
    return exact


class NumericHistory:
    """旧SAR主を使わず、精密核の同限月carryと全足出典を保持する。"""

    def __init__(self) -> None:
        """未確定限月と空の独立SARを作る。

        引数: なし。
        返り値: None。
        """
        self.contract = None
        self.kernel = RationalSAR()

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0) -> tuple[list[dict], dict]:
        """原3分OHLCの切断とNPを判定して、精密SAR全足を保存形式へ写す。

        引数: frames (list[dict]) は独立完全幅原足、session (str) は当場、contract (tuple) は限月、
        tail_missing (int) は完全尾部欠枠。
        返り値: tuple[list[dict],dict] は全数値/hex/公開出典と品質。先着/運用を含まない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.kernel.clear()
        self.contract = contract
        rows, prior_index, prior_key, resets = [], None, None, int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or prior_index is not None and index <= prior_index:
                raise ValueError("独立SARの足幅/番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or prior_key is not None and key < prior_key):
                raise ValueError("独立SARの公開前足/key後退")
            reasons = ["限月変更"] if changed and prior_index is None else []
            if index != (0 if prior_index is None else prior_index + 1):
                reasons.append("3分番号欠枠")
            if frame["missing"]:
                reasons.append("3分欠枠")
            if not B.valid_ohlc(frame):
                reasons.append("3分OHLC不正")
            if any(reason != "限月変更" for reason in reasons):
                self.kernel.clear()
                resets += 1
            state = self.kernel.step(frame, session)
            ready = state["ready"]
            as_float = {name: float(state[name]) if state[name] is not None else None for name in
                ("before_line", "display", "next_line", "extreme", "before_extreme")}
            rows.append({"場": session, **B.source(frame), "SAR準備済": ready, "SAR公開可": bool(ready and frame["publish"]),
                "SAR方向": state["direction"], "SAR事前方向": state["before_direction"],
                "SAR事前線": as_float["before_line"], "SAR表示線": as_float["display"], "SAR次足線": as_float["next_line"],
                "SAR_EP": as_float["extreme"], "SAR_AF": state["af"] / 100 if ready else None,
                "SAR事前EP": as_float["before_extreme"], "SAR事前AF": state["before_af"] / 100 if state["before_af"] else None,
                "SAR精密事前線": pack(state["before_line"]), "SAR精密表示線": pack(state["display"]),
                "SAR精密次足線": pack(state["next_line"]), "SAR精密EP": pack(state["extreme"]),
                "SAR精密事前EP": pack(state["before_extreme"]),
                "SAR_AF整数": state["af"] if ready else None, "SAR事前AF整数": state["before_af"] or None,
                "SAR反転": state["reversed"], "SAR初期化": state["initial"], "SAR数値入力可": state["numeric"],
                "SAR前二足": state["previous_sources"], "SAR解除理由": reasons})
            prior_index = index
            if frame["publish"]:
                prior_key = key
        if tail_missing:
            self.kernel.clear()
            resets += 1
        precision_sizes = [unpack(row[name]) for row in rows for name in
            ("SAR精密事前線", "SAR精密表示線", "SAR精密次足線", "SAR精密EP", "SAR精密事前EP") if row[name] is not None]
        quality = {"場": session, "SAR入力足数": len(rows), "SAR数値準備足数": sum(row["SAR準備済"] for row in rows),
            "SAR公開準備足数": sum(row["SAR公開可"] for row in rows), "SAR初期化数": sum(row["SAR初期化"] for row in rows),
            "SAR反転数": sum(row["SAR反転"] for row in rows), "SAR未公開数値更新数": sum(not row["publish"] and row["SAR数値入力可"] for row in rows),
            "SARclear数": resets, "SAR尾部完全欠枠": tail_missing, "SAR場末方向": self.kernel.direction,
            "SAR場末次線精密": pack(self.kernel.forecast), "SAR場末EP精密": pack(self.kernel.extreme),
            "SAR場末AF整数": self.kernel.af if self.kernel.direction else None,
            "最大分子bit長": max((abs(value.numerator).bit_length() for value in precision_sizes), default=0),
            "最大分母bit長": max((value.denominator.bit_length() for value in precision_sizes), default=0),
            "最大分数保存文字数": max((len(hex(value.numerator)) + len(hex(value.denominator)) for value in precision_sizes), default=0),
            "精密分数表現": "符号付き正規形16進文字列/正分母",
            "SAR全足内容SHA256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()}
        return rows, quality


# ----------------------------------------
# 旧入口の大明細を複製せず、固定指紋と当時情報の明示射影で接続する。

def canonical_sha(value: Any) -> str:
    """保存値のJSON正規形を内容指紋へ変換する。

    引数: value (Any) はJSON安全な値。
    返り値: str はSHA256。精密値は既約hex、ATR原値の許容は別照合する。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def pure_signal(row: dict) -> dict:
    """入口の当時情報だけを明示whitelistへ投影する。

    引数: row (dict) は独立純信号又は比較用の旧case。
    返り値: dict は新しいlive辞書。ラベル/仮約定/未来価格/判定等の属性を渡さない。
    """
    return {name: deepcopy(row.get(name)) if name == "bb_mean" else deepcopy(row[name]) for name in SIGNAL_FIELDS}


def decision_signal(row: dict) -> dict:
    """ATRだけを正有効性とD整数へ分離し、判断用厳密射影を作る。

    引数: row (dict) は全leafを別照合するlive信号。
    返り値: dict はATR判断以外を一切変えない射影。ATR数値同値の証明ではない。
    """
    result = deepcopy(row)
    atr = result.pop("atr")
    valid = B.finite(atr) and atr > 0
    result["ATR判断"] = {"正有効": valid, "Dpt整数": max(5, math.ceil(atr / 5) * 5) if valid else None}
    return result


def raw_projection(rows: list[dict]) -> list[dict]:
    """原価格発動の厳密な採否/価格/時計だけを小型射影にする。

    引数: rows (list[dict]) は独立31純再構成の原P。
    返り値: list[dict] はATRfloatを含まない全原P射影。ラベルは読み取らない。
    """
    names = ("場", "発動ID", "index", "side", "close", "要求時計秒", "要求原板行", "足終了時計秒",
        "直前最高H", "直前最安L", "共通M準備", "M除外理由", "時間条件可", "確認遅延条件可", "先着評価対象",
        "戦略判定", "BB幅比較厳密符号")
    return [{**{name: deepcopy(row[name]) for name in names},
        **{name: None if row[name] is None else {field: row[name][field] for field in ("分子", "分母", "有効")}
            for name in ("CCI現", "CCI前")}} for row in rows]


def entry_reference(study: Path, audit: Audit) -> dict:
    """共有入口の正本パス・固定・証明と6圧縮明細をcache前に検査する。

    引数: study (Path) は32正式先、audit (Audit) は照合先。
    返り値: dict は検査済み参照台帳。旧収益やラベルを新たに計算しない。
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
        expected = ENTRY_STUDY / name
        audit.check("共有証明正本:" + name, (ROOT / item["パス"]).resolve(), expected.resolve())
        audit.check("共有証明SHA:" + name, item["SHA256"], V.sha(expected))
    locked = V.read(ENTRY_STUDY / "固定.json")
    for name, digest in locked["ファイルSHA256"].items():
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
        old_proof = V.read(ENTRY_STUDY / name)
        audit.check("共有完了証明:" + name, old_proof["全件一致"], True)
        audit.check("共有完了不一致0:" + name, old_proof["不一致数"], 0)
    return pointer


def shared_signals() -> list[dict]:
    """旧caseを一行ずつ当時情報へ射影し、未来属性を直ちに捨てる。

    引数: なし。
    返り値: list[dict] は比較用live属性だけ。再構成する運用信号は別に作る。
    """
    import gzip
    output = []
    with gzip.open(ENTRY_WORK / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            output.append(pure_signal(json.loads(line)))
    return output


def dependency_pins() -> dict:
    """推移的な旧独立補助へpath付きの現在指紋を付ける。

    引数: なし。
    返り値: dict[str,str] は固定31独立とその旧補助の指紋。32主を読まない。
    """
    return dict(sorted({**G.dependency_pins(), "scripts/CCI突破/状態独立確認.py": V.sha(Path(G.__file__))}.items()))


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path, dict]:
    """主準備と共有入口の現在版を、原cache計算より先に照合する。

    引数: study/work (Path) は正式/作業先、audit (Audit) は記録。
    返り値: tuple は32条件/実台帳/主準備/解決台帳/共有入口参照。
    """
    config = V.read(study / "条件.json")
    manifest, resolved = G.resolved_manifest(study)
    pointer = entry_reference(study, audit)
    old = V.read(ENTRY_STUDY / "条件.json")
    overrides = {"出口", "表示代表", "出口定義", "依存"}
    for name, expected in old.items():
        if name not in overrides:
            audit.check("固定31継承条件:" + name, config[name], expected)
    audit.check("32二出口", config["出口"], [{"出口ID": name} for name in EXITS])
    audit.check("32固定31条件参照", (study / config["入口条件参照"]["パス"]).resolve(), (ENTRY_STUDY / "条件.json").resolve())
    audit.check("32固定31条件指紋", config["入口条件参照"]["SHA256"], OLD_CONDITION_SHA)
    for name, expected in {"AF初期整数": 2, "AF増分整数": 2, "AF上限整数": 20, "AF分母": 100, "時間足分": 3}.items():
        audit.check("精密SAR固定数値:" + name, config["SAR追尾"][name], expected)
    master = V.read(work / "準備点検.json")
    for name, expected in (("ラベル計算", False), ("損益計算", False), ("旧31純信号同値", True),
            ("条件SHA256", V.sha(study / "条件.json")), ("入力台帳SHA256", V.sha(study / "入力台帳.json")),
            ("参照台帳SHA256", V.sha(resolved)), ("入口参照SHA256", V.sha(study / "入口参照.json")),
            ("純信号whitelist", list(SIGNAL_FIELDS)), ("共有入口参照", pointer)):
        audit.check("主準備:" + name, master[name], expected)
    paths = {"scripts/SAR追尾/" + name for name in ("検証.py", "指標.py", "運用.py")}
    audit.check("32主三コード集合", set(master["コードSHA256"]), paths)
    if set(master["コードSHA256"]) == paths:
        for name, digest in master["コードSHA256"].items():
            audit.check("32主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主準備66場順", [row["場"] for row in master["準備"]], [row["session"] for row in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("主/共有入力の不一致によりcache前停止")
    return config, manifest, master, resolved, pointer


def reconstruct(manifest: dict) -> Any:
    """固定31独立再構成の原足から精密SARとpure信号だけを追加する。

    引数: manifest (dict) は既使用66台帳。
    返り値: Any は場別iterator。旧CCI/context/label大列を32へ保存しない。
    """
    config = V.read(ENTRY_STUDY / "条件.json")
    bank = NumericHistory()
    for block in G.reconstruct(manifest, config):
        session = block["場"]
        entry = next(row for row in manifest["entries"] if row["session"] == session)
        sar, quality = bank.build(block["価格足"][3], session, tuple(entry["in_session_contract_codes"]), block["入力品質"]["尾部欠枠"]["3"])
        signals = [pure_signal(row) for name in ("3分_C0", "3分_C1") for row in block["純入口"][name]]
        small = {name: value for name, value in block["入口品質"].items() if name not in ("全Q発動記録", "複合context記録")}
        yield {"場": session, "期間": block["期間"], "純信号": signals,
            "純信号内容SHA256": canonical_sha(signals), "純信号判断SHA256": canonical_sha([decision_signal(row) for row in signals]),
            "原P判定SHA256": canonical_sha(raw_projection(block["入口品質"]["全Q発動記録"])),
            "入口品質": small, "SAR品質": quality, "入力品質": block["入力品質"], "SAR全足": sar}


def proof_base(study: Path, work: Path, resolved: Path, audit: Audit, master: dict) -> dict:
    """全監査で共通する指紋と、ATR許容/精密値厳密の範囲を保存する。

    引数: study/work/resolved (Path) は正式/作業/台帳、audit (Audit) は記録、master (dict) は主準備。
    返り値: dict はproof基礎。生liveのATR完全SHA同値とは主張しない。
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
        "ATR照合": {"leaf数": audit.atr_count, "表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾D整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0と正有効/D整数厳密"},
        "厳密範囲": "SAR有理数hex/AF整数/公開元・価格/key/ID/役割/入口採否は厳密。liveは全leaf照合後にatrだけ正有効/D整数へ明示投影した判断SHAを比較。主生liveSHAと旧31case完全同値は別出典bind"}


def compare_preparation(master: dict, block: dict, saved_signals: dict, audit: Audit) -> dict:
    """主準備の各leafと判断SHAを比較し、主生liveを旧caseへ厳密照合する。

    引数: master/block (dict) は主/独立の当場、saved_signals (dict) は旧case当時射影、audit (Audit) は記録。
    返り値: dict は小型の場別証明。独立ATRfloatの全文SHA一致とはしない。
    """
    exclude = {"純信号内容SHA256"}
    audit.check(block["場"] + ":全SAR/判断/品質/純信号leaf", {name: value for name, value in master.items() if name not in exclude},
        {name: value for name, value in block.items() if name not in exclude})
    audit.check(block["場"] + ":主生live出典SHA", master["純信号内容SHA256"], canonical_sha(master["純信号"]))
    for row in master["純信号"]:
        audit.check(row["イベントID"] + ":主live whitelist", set(row), set(SIGNAL_FIELDS))
        expected = saved_signals.get(row["イベントID"])
        audit.leaf(row["イベントID"] + ":主liveは固定31case完全同値", row, expected, row == expected)
    return {"場": block["場"], "期間": block["期間"], "純信号数": len(block["純信号"]),
        "主生live内容SHA256": master["純信号内容SHA256"], "独立ATR判断射影SHA256": block["純信号判断SHA256"],
        "原P判定SHA256": block["原P判定SHA256"], "SAR全足内容SHA256": block["SAR品質"]["SAR全足内容SHA256"],
        "SAR足数": len(block["SAR全足"])}


def prepare(study: Path, work: Path) -> dict:
    """root明示起動で全66の非PnL数値/live準備を主へ照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は小型独立準備proof。ラベル/運用/損益は計算しない。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved, pointer = guarded_inputs(study, work, audit)
    shared = shared_signals()
    saved = {row["イベントID"]: row for row in shared}
    audit.check("共有live一意", len(saved), len(shared))
    stages, identities = [], set()
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        stages.append(compare_preparation(main, block, saved, audit))
        identities.update(row["イベントID"] for row in block["純信号"])
        print(json.dumps({"場": block["場"], "独立準備": "原OHLC/精密SAR/公開元/31純入口", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("旧31pure全集合", identities, set(saved))
    audit.check("主純信号全件数", master["純信号数"], len(identities))
    audit.check("独立実行中code不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, audit, master), "ラベル計算": False, "損益計算": False,
        "旧31純信号同値": audit.mismatches == 0, "純信号数": len(identities), "場別準備": stages,
        "SAR全足数": sum(row["SAR足数"] for row in stages),
        "検証範囲": "固定8列cacheから独立31の3/15分数値と原P/採否を再構成し、当時whitelistだけを比較。3分原OHLCへ別実装の有理数SAR/AF整数を当て全精密/表示/前二足/公開/品質を厳密照合。原ATRは既定許容/D整数を全leaf比較してから判断SHAへ投影。生liveの旧31完全同値/共有6明細は別出典へbind。",
        "限界": "準備はlabel/PnL/実運用を呼ばない。旧caseは当時属性だけを直ちに射影し、将来属性を運用信号へ渡さない。既使用66場の開発内検算であり未見成績ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({name: proof[name] for name in ("全件一致", "照合項目数", "不一致数", "純信号数", "SAR全足数")}, ensure_ascii=False))
    return proof


# ----------------------------------------
# 正式後は新3明細の全行と旧X0を照合し、先着は固定31証明へ結び付ける。

def public_reference(row: dict) -> dict:
    """当場公開SARの運用用小型参照を作る。

    引数: row (dict) は独立精密SAR全足の一行。
    返り値: dict は公開元/方向/精密次足線だけのsnapshot。
    """
    names = ("場", "index", "end", "confirm", "confirm_line", "publish", "missing", "SAR準備済", "SAR公開可",
        "SAR方向", "SAR次足線", "SAR精密次足線", "SAR_AF整数", "SAR解除理由")
    return deepcopy({name: row[name] for name in names})


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """独立準備の現コードと共有入口bindを正式cacheより前に再確認する。

    引数: study/work/resolved (Path) は保存先/台帳、master (dict) は主準備、audit (Audit) は記録。
    返り値: None。不一致は以降の入力計算を拒否する。
    """
    proof = V.read(work / "独立準備点検.json")
    expected = {"全件一致": True, "不一致数": 0, "ラベル計算": False, "損益計算": False,
        "コードSHA256": V.sha(Path(__file__)), "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "依存コードSHA256": dependency_pins()}
    for name, value in expected.items():
        audit.check("独立準備bind:" + name, proof[name], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("独立準備/固定の現版不一致によりcache前停止")


def run(study: Path, work: Path) -> dict:
    """root正式完了後に新SAR全足・共有入口・X0完全同値を検証する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は状態proof。XS最初要求/全線は別追尾監査に分ける。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("root正式完了後だけ状態監査を実行します")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved, pointer = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    names = ("SAR全足", "全運用詳細", "追尾")
    saved_rows, hashes, grouped = {}, {}, {}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新保存3系列", set(artifacts), {name + ".jsonl.gz" for name in names})
    sessions = {entry["session"] for entry in manifest["entries"]}
    for name in names:
        saved_rows[name], hashes[name] = B.compressed_rows(work / (name + ".jsonl.gz"))
        audit.check("新成果物SHA:" + name, hashes[name], artifacts[name + ".jsonl.gz"]["展開内容SHA256"])
        groups = defaultdict(list)
        for row in saved_rows[name]:
            audit.check("新成果物場範囲:" + name, row["場"] in sessions, True)
            groups[row["場"]].append(row)
        grouped[name] = groups
    shared = shared_signals()
    signals = {row["イベントID"]: row for row in shared}
    audit.check("共有live一意", len(signals), len(shared))
    old_details, _ = B.compressed_rows(ENTRY_WORK / "全運用詳細.jsonl.gz")
    old_logs, _ = B.compressed_rows(ENTRY_WORK / "追尾.jsonl.gz")
    old_map = {(row["候補ID"], row["場"]): row for row in old_details}
    old_trace = defaultdict(list)
    for row in old_logs:
        old_trace[row["候補ID"], row["場"]].append(row)
    inputs, qualities = (V.read(study / name) for name in ("入力品質.json", "指標品質.json"))
    audit.check("入力品質66場", len(inputs), 66)
    audit.check("SAR品質66場", len(qualities), 66)
    inputs, qualities = {row["場"]: row for row in inputs}, {row["場"]: row for row in qualities}
    stages, controls, identities = [], [], set()
    for main, block in zip(master["準備"], reconstruct(manifest), strict=True):
        session, period = block["場"], block["期間"]
        stages.append(compare_preparation(main, block, signals, audit))
        identities.update(row["イベントID"] for row in block["純信号"])
        audit.check(session + ":全SAR数値/精密/出典", grouped["SAR全足"][session], [{"期間": period, **row} for row in block["SAR全足"]])
        audit.check(session + ":入力品質", inputs[session], {"期間": period, **block["入力品質"]})
        audit.check(session + ":SAR品質", qualities[session], {"期間": period, **block["SAR品質"]})
        details = grouped["全運用詳細"][session]
        candidates = {"3分_" + policy + "_" + exit_name for policy in POLICIES for exit_name in EXITS}
        audit.check(session + ":四運用一意", len(details), 4)
        audit.check(session + ":四候補集合", {row["候補ID"] for row in details}, candidates)
        start, finish, _, _ = S.G.times(session)
        public = [row for row in block["SAR全足"] if row["publish"] and start <= row["confirm"] < finish]
        expected_publication = [{"時計秒": row["confirm"], "原板行": row["confirm_line"],
            "最新SAR参照": public_reference(row), "SAR候補有効": row["SAR公開可"]} for row in public]
        for detail in details:
            cid = detail["候補ID"]
            logs = [row for row in grouped["追尾"][session] if row["候補ID"] == cid]
            audit.check(cid + session + ":期間", detail["品質"]["期間"], period)
            if cid.endswith("_X0"):
                old = old_map.get((cid, session))
                audit.leaf(cid + session + ":旧31全運用完全同値", detail, old, detail == old)
                previous_logs = old_trace[cid, session]
                audit.leaf(cid + session + ":旧31全追尾完全同値", logs, previous_logs, logs == previous_logs)
                controls.append({"場": session, "候補ID": cid, "全運用同値": detail == old,
                    "全追尾同値": logs == previous_logs, "全運用内容SHA256": canonical_sha([detail]),
                    "追尾内容SHA256": canonical_sha(logs)})
            else:
                fields = ("時計秒", "原板行", "最新SAR参照", "SAR候補有効")
                publication = [{name: row[name] for name in fields} for row in logs if row["動作"] == "SAR公開参照更新"]
                audit.check(cid + session + ":全公開参照順/出典", publication, expected_publication)
        print(json.dumps({"場": session, "独立状態": "精密SAR/31live/全公開元/X0完全同値", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("旧31live全集合", identities, set(signals))
    old_result, result = V.read(ENTRY_STUDY / "結果.json"), V.read(study / "結果.json")
    for name, expected in (("入口評価", old_result["入口評価"]), ("入口70目標達成数", old_result["入口70目標達成数"]),
            ("入口125250評価の変更", False), ("入口評価数", 2), ("運用候補数", 4),
            ("表示固定ID", ["3分_" + policy + "_" + exit_name for policy in POLICIES for exit_name in EXITS])):
        audit.check("共有入口と新運用:" + name, result[name], expected)
    audit.check("X0完全同値保存証明", V.read(study / "X0対照同値.json"),
        {"全件一致": True, "場候補数": len(controls), "照合": controls, "入口参照SHA256": V.sha(study / "入口参照.json")})
    audit.check("独立実行中code不変", V.sha(Path(__file__)), initial)
    old_state = V.read(ENTRY_STUDY / "状態独立確認.json")
    proof = {**proof_base(study, work, resolved, audit, master), "場別準備": stages,
        "期間場数": {period: sum(row["期間"] == period for row in stages) for period in ("学習", "条件選択", "後続検査")},
        "保存SAR数": len(saved_rows["SAR全足"]), "保存運用詳細数": len(saved_rows["全運用詳細"]), "保存追尾数": len(saved_rows["追尾"]),
        "共有入口数": len(signals), "旧31X0完全同値数": len(controls), "旧31先着再計算": False,
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved_rows[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()}, "SAR展開SHA256": hashes["SAR全足"],
        "入口事例展開SHA256": old_state["入口事例展開SHA256"], "共有入口事例展開SHA256": old_state["入口事例展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列から独立OHLC/精密SAR/公開出典と固定31純入口を再構成。新3gzip全行指紋・全SAR/品質・XS全公開参照、2×66のX0全運用/追尾と旧31の完全同値を検査。旧31入口/125250先着は既完了証明と共有指紋へbind。",
        "限界": "XS全線/起動/最初要求/公開strict key/pending凍結は別の追尾監査。新規受入/+1秒BBO約定/費用と期間集計は会計監査。既使用66場を未見と呼ばず、精密SARを旧floatの完全同値とはしない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({name: proof[name] for name in ("全件一致", "照合項目数", "不一致数", "保存SAR数", "旧31X0完全同値数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root明示起動で非PnL準備又は正式状態監査だけを選ぶ。

    引数: なし。CLIの--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致は非0終了。無指定では実観測へ進まない。
    """
    parser = argparse.ArgumentParser(description="00032精密SARと共有入口の独立確認")
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
