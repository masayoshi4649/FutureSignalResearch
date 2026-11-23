"""同じCCI突破を登録し、即時又は固定高安への指値で仮新規を評価する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("突破指値の固定31入口", ROOT/"scripts/CCI突破/検証.py")
D = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = D
SPEC.loader.exec_module(D)
BASE_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("E0", "E1")
SIGNAL_FIELDS = {"E0": BASE_FIELDS, "E1": BASE_FIELDS+("新規指値価格", "指値根拠")}


def canonical_sha(value: object) -> str:
    """JSON保存値を固定書式で指紋化する。

    引数: value(object)はJSON化できる値。
    返り値: strはSHA256。
    """
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def registration(row: dict) -> dict:
    """当時の原Pから指値に使う過去20高安を固定する。

    引数: row(dict)は固定31のC0採用原P。
    返り値: dictは価格・窓番号・公開keyの出典。将来情報を含まない。
    """
    if not row["戦略判定"]["C0"]["採用"] or row["side"] not in (-1, 1):
        raise ValueError("固定C0採用だけを登録します")
    source = {"旧C0イベントID": row["発動ID"]+"_C0", "場": row["場"], "登録足番号": row["index"],
        "足終了時計秒": row["足終了時計秒"], "公開時計秒": row["要求時計秒"], "公開原板行": row["要求原板行"],
        "前20足番号": deepcopy(row["前20足番号"]), "前20最高H": row["直前最高H"],
        "前20最安L": row["直前最安L"], "当足終値": row["close"], "実side": row["side"]}
    if len(source["前20足番号"]) != 20 or source["前20足番号"][-1] >= source["登録足番号"]:
        raise ValueError("現在を含まない20足窓だけ")
    return source


def select(block: dict) -> dict:
    """同じC0純集合を二種類の当時信号へ射影する。

    引数: block(dict)は固定31の非PnL場材料。
    返り値: dictは登録出典とE0/E1純信号を持つ場材料。
    """
    anchors = {row["発動ID"]+"_C0": registration(row) for row in block["quality"]["全Q発動記録"]
        if row["戦略判定"]["C0"]["採用"]}
    old = block["signals"]["3分_C0"]
    if len(anchors) != len(old) or set(anchors) != {r["イベントID"] for r in old}:
        raise ValueError("C0登録全集合に差")
    grouped = {"3分_"+p: [] for p in POLICIES}
    for row in old:
        source = anchors[row["イベントID"]]
        for policy in POLICIES:
            signal = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in BASE_FIELDS}
            signal.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
            if policy == "E1":
                signal.update(新規指値価格=source["前20最高H"] if row["side"] == 1 else source["前20最安L"],
                    指値根拠=deepcopy(source))
            grouped["3分_"+policy].append(signal)
    block["signals"], block["registrations"] = grouped, list(anchors.values())
    return block


# ----------------------------------------
# 仮参加は登録ごとに独立。実運用の単一pending/保有抑止を混ぜない。

class 入口経路(D.W.OLD.気配経路):
    """原順の正常BBOと区間木で、新規選択後からの125/250先着を判定する。"""

    def entry_index(self, signal: dict, cutoff: float, policy: str, deadline: float | None = None) -> int | None:
        """有効化後の最初の即時又は指値成立BBOを選ぶ。

        引数: signal(dict)は当時信号、cutoff(float)は停止、policy(str)はE0/E1、deadline(float|None)は強制期限。
        返り値: int|Noneは原順の正常BBO位置。30秒等号可、停止等号不可。
        """
        if policy not in POLICIES or signal["side"] not in (-1, 1):
            raise ValueError("固定二案/売買符号だけ")
        start = int(D.W.np.searchsorted(self.now, signal["要求時計秒"]+1, side="left"))
        end = min(int(D.W.np.searchsorted(self.now, signal["要求時計秒"]+30, side="right")),
            int(D.W.np.searchsorted(self.now, cutoff, side="left")))
        if deadline is not None:
            end = min(end, int(D.W.np.searchsorted(self.now, deadline, side="left")))
        if start >= end:
            return None
        if policy == "E0":
            return start
        side, limit = signal["side"], signal["新規指値価格"]
        prices = self.ask if side == 1 else self.bid
        eligible = D.W.np.flatnonzero(side*(prices[start:end]-limit) <= 0)
        return start+int(eligible[0]) if len(eligible) else None

    def evaluate_signal(self, signal: dict, cutoff: float, deadline: float, policy: str) -> dict:
        """各案の仮新規が成立した実在BBOから先着を評価する。

        引数: signal(dict)は純登録、cutoff/deadline(float)は停止/期限、policy(str)はE0/E1。
        返り値: dictは最小先着結果。未約定では九数値をNoneとする。
        """
        index = self.entry_index(signal, cutoff, policy, deadline)
        empty = {"ラベル": "未約定", "理由": "30秒内に正常板なし" if policy == "E0" else "30秒内に指値成立正常BBOなし",
            **{k: None for k in ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
                "判定気配", "最大順行pt", "最大逆行pt", "所要分")}}
        if index is None:
            return empty
        side = signal["side"]
        entry = float(self.ask[index] if side == 1 else self.bid[index])
        marks = self.bid if side == 1 else self.ask
        lower, upper = (entry-125, entry+250) if side == 1 else (entry-250, entry+125)
        end = int(D.W.np.searchsorted(self.now, deadline, side="right"))
        gap_pos = int(D.W.np.searchsorted(self.gaps, index+1))
        next_gap = int(self.gaps[gap_pos]) if gap_pos < len(self.gaps) else None
        limited = next_gap is not None and self.now[next_gap-1]+300 < deadline
        stop = min(end, next_gap) if limited else end
        hit = self.trees[side].first(index, stop, lower, upper)
        if hit is not None:
            last = hit
            label = "順行先着" if side*(marks[last]-entry) >= 250 else "逆行先着"
            reason = "返済気配の閾値初着"
        else:
            last = max(index, stop-1)
            covered = len(self.now) > 0 and self.now[-1] >= deadline
            stale = deadline-self.now[last] > 300
            label = "観測不足" if limited or not covered or stale else "期限未達"
            reason = "正常板価格時計300秒超空白" if limited or stale else ("入力末尾不足" if not covered else "期限内どちらも未到達")
        distances = side*(marks[index:last+1]-entry)
        return {"ラベル": label, "理由": reason, "新規価格": entry,
            "新規時計秒": float(self.now[index]), "新規原板行": int(self.line[index]),
            "判定時計秒": float(self.now[last]), "判定原板行": int(self.line[last]),
            "判定気配": float(marks[last]), "最大順行pt": float(max(0, D.W.np.max(distances))),
            "最大逆行pt": float(max(0, -D.W.np.min(distances))),
            "所要分": float((self.now[last]-self.now[index])/60)}
