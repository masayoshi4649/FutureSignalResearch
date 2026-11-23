"""固定CCI突破の寿命延長と、旧水準の到達後回復を別々に評価する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("回復監視の固定34入口", ROOT/"scripts/突破指値/入口.py")
OLD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OLD
SPEC.loader.exec_module(OLD)
D, canonical_sha, registration = OLD.D, OLD.canonical_sha, OLD.registration
BASE_FIELDS = OLD.BASE_FIELDS
POLICIES = ("E1", "E2", "E3")
SIGNAL_FIELDS = {p: OLD.SIGNAL_FIELDS["E1"] for p in POLICIES}


def select(block: dict) -> dict:
    """旧34の登録水準と純15列を三案へ射影する。

    引数: block(dict)は固定31の場材料。
    返り値: dictは同じ801登録に基づく三案。未来の到達や回復を含めない。
    """
    value = OLD.select(block)
    signals = {"3分_"+p: [] for p in POLICIES}
    for row in value["signals"]["3分_E1"]:
        for policy in POLICIES:
            item = deepcopy(row)
            item.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
            signals["3分_"+policy].append(item)
    value["signals"] = signals
    return value


# ----------------------------------------
# 準備では技術的な初回到達/回復だけを観測し、仮新規も先着も計算しない。

class 入口経路(OLD.入口経路):
    """原順の正常BBOから登録別の監視と、成立後の先着を評価する。"""

    def observe_signal(self, signal: dict, cutoff: float, deadline: float, policy: str = "E3") -> dict:
        """最初の水準到達と、そのstrict後keyでの最初回復を固定する。

        引数: signal(dict)は純登録、cutoff/deadline(float)は停止/強制、policy(str)は三案。
        返り値: dictは内部観測。位置・元期限・新規要求keyだけで、fillを選ばない。
        """
        if policy not in POLICIES or signal["side"] not in (-1, 1):
            raise ValueError("固定三案と売買鏡像だけ")
        registered, side, level = signal["要求時計秒"], signal["side"], signal["新規指値価格"]
        expires = registered+(30 if policy == "E1" else 180)
        output = {"接触位置": None, "回復位置": None, "絶対期限": expires,
            "新規要求key": (float(registered), int(signal["要求原板行"])) if policy != "E3" else None,
            "回復時間可": None, "回復時間除外理由": []}
        start = int(D.W.np.searchsorted(self.now, registered+1, side="left"))
        end = min(int(D.W.np.searchsorted(self.now, expires, side="right")),
            int(D.W.np.searchsorted(self.now, cutoff, side="left")),
            int(D.W.np.searchsorted(self.now, deadline, side="left")))
        prices = self.ask if side == 1 else self.bid
        touches = D.W.np.flatnonzero(side*(prices[start:end]-level) <= 0)
        if not len(touches):
            return output
        first = start+int(touches[0])
        output["接触位置"] = first
        if policy != "E3":
            return output
        marks = self.bid if side == 1 else self.ask
        recoveries = D.W.np.flatnonzero(side*(marks[first+1:end]-level) > 0)
        if not len(recoveries):
            return output
        recovery = first+1+int(recoveries[0])
        if (self.now[recovery], self.line[recovery]) <= (self.now[first], self.line[first]):
            raise ValueError("原順keyのstrict後が必要")
        output["回復位置"] = recovery
        clock = float(self.now[recovery])
        reasons = []
        if deadline-clock < 3600:
            reasons.append("回復時残り60分未満")
        if clock+1 > expires:
            reasons.append("回復後1秒が元期限外")
        output.update(回復時間除外理由=reasons, 回復時間可=not reasons)
        if not reasons:
            output["新規要求key"] = (clock, int(self.line[recovery]))
        return output

    def observation(self, signal: dict, cutoff: float, deadline: float) -> dict:
        """内部位置を小さな時点出典へ変換し、未来値を純信号から隔離する。

        引数: signal(dict)は登録、cutoff/deadline(float)は停止/強制。
        返り値: dictはE3用の別観測。未回復/時刻不可は新規要求をNoneにする。
        """
        value = self.observe_signal(signal, cutoff, deadline)
        snapshots = {}
        for name, key in (("初回到達出典", "接触位置"), ("初回回復出典", "回復位置")):
            index = value[key]
            snapshots[name] = None if index is None else {"時計秒": float(self.now[index]),
                "原板行": int(self.line[index]), "bid": float(self.bid[index]), "ask": float(self.ask[index])}
        requested = value["新規要求key"]
        return {"絶対失効時計秒": value["絶対期限"], **snapshots,
            "回復時間可": value["回復時間可"], "回復時間除外理由": value["回復時間除外理由"],
            "新規要求時計秒": None if requested is None else requested[0],
            "新規要求原板行": None if requested is None else requested[1]}

    def entry_index(self, signal: dict, cutoff: float, policy: str, deadline: float | None = None) -> int | None:
        """元絶対期限内の最初指値又は回復要求後の最初市場BBOを選ぶ。

        引数: signal(dict)は登録、cutoff(float)は停止、policy(str)は三案、deadline(float|None)は強制。
        返り値: int|Noneは仮新規位置。E3は回復価格や旧指値でfillしない。
        """
        if policy == "E1":
            return super().entry_index(signal, cutoff, policy, deadline)
        observed = self.observe_signal(signal, cutoff, float("inf") if deadline is None else deadline, policy)
        if policy == "E2":
            return observed["接触位置"]
        request = observed["新規要求key"]
        if request is None:
            return None
        index = int(D.W.np.searchsorted(self.now, request[0]+1, side="left"))
        if index >= len(self.now) or self.now[index] > observed["絶対期限"] or self.now[index] >= cutoff:
            return None
        if deadline is not None and self.now[index] >= deadline:
            return None
        return index

    def evaluate_signal(self, signal: dict, cutoff: float, deadline: float, policy: str) -> dict:
        """各案の実在仮新規BBOから125/250を新しく評価する。

        引数: signal(dict)は登録、cutoff/deadline(float)は停止/強制、policy(str)は三案。
        返り値: dictは先着結果。E1は旧34と全列同値。
        """
        value = super().evaluate_signal(signal, cutoff, deadline, policy)
        if policy != "E1" and value["ラベル"] == "未約定":
            if policy == "E2":
                value["理由"] = "180秒内に指値成立正常BBOなし"
            else:
                observed = self.observe_signal(signal, cutoff, deadline)
                value["理由"] = ("180秒内に水準到達なし" if observed["接触位置"] is None else
                    "到達後に水準回復なし" if observed["回復位置"] is None else
                    "・".join(observed["回復時間除外理由"]) if not observed["回復時間可"] else
                    "回復要求後に元期限内の正常BBOなし")
        return value
