"""登録時の水準を保持し、当時可視の公開足だけで再試験の状態を再構成する。"""

from collections import deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("保持再試験が固定参照する53特徴",
    Path(__file__).resolve().parents[1] / "局所帯分岐/特徴.py")
F53 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F53)
I49 = F53.F.I49
SOURCE_FIELDS = F53.SOURCE_FIELDS
BASE_FEATURES = deepcopy(F53.FEATURES)
FEATURES = deepcopy(BASE_FEATURES)
for role, start in (("T", 19), ("R", 25)):
    for offset, (name, method) in enumerate((("最大到達段階", "P10"), ("episode有効", "P10"),
            ("確認k有効", "P10"), ("確認k公開後経過対900秒", "P10"),
            ("確認k終値からの実方向進行対ATR", "P05"), ("既知最大終値進行からの戻り対ATR", "P10"))):
        FEATURES.append({"id": f"F{start + offset:02d}", "name": role + name,
            "method": method, "family": "price", "scale": "m03"})
RULES = {"旧特徴": 18, "保持経路特徴": 12, "全特徴": 30, "登録参照本数": 10,
    "帯端buffer": 5, "TTL秒": 3600, "期限": "b.confirm+3600以上で失効。最大4定時とはしない",
    "参照帯": "未登録又は取消済みの時、当足を除く直前10完全隣接3分足の高安",
    "b": "同じ新Kでq前<5かつq現>=5。前Cは参照10本内なので前条件は自動成立",
    "T_r": "b後の別足q_min<=0かつq_close>=5。最初だけ", "T_k": "r後の別足q_close>q_max(r)",
    "R_f": "b後の別足q_close<=-5。最初だけ", "R_r": "f後の別足q_max>=0かつq_close<=-5。最初だけ",
    "R_k": "r後の別足q_close<q_min(r)", "元突破方向": "Tは実side、Rは-実side",
    "T帯取消": "b後q_close<=-5", "R帯取消": "f後q_close>=5。f前外残留は維持",
    "k否定": "実side*(C-突破したr端)<=0。等号も取消", "取消優先": ["帯失敗又は元外側再取得", "確認kの突破線否定"],
    "置換": "有効中は禁止。取消済みだけ次足以降の新bで置換。Kと参照10本は登録時固定",
    "足内高安順": "使用しない", "同足段階再使用": False,
    "期限越え足": "最初の期限越え公開足は再登録に使わず、次足から探索",
    "判断のみの失効": "足処理後に判断timeでも失効。次回も全prefixから同じ履歴を再構成",
    "期限clear": "現ID/段階/出典をclearしstage0。直近ID/期限/理由はlast_expiredへ保持",
    "欠測": "当時可視なNP/欠枠/不正価格/番号又は終了のgapで全局所状態clear、再準備10本",
    "reset優先": "不良又はgapの観測足はTTLより先にclear。新しい失効記憶は作らず既存last_expiredは保持",
    "入力不正": "可視足の番号重複又は公開key同値/後退は拒否。未来足の価格を検査しない",
    "旧準備": "固定53と同じ。過去の定時readyや保有を機械の更新条件にしない",
    "旧F18": "旧定時の局所帯の旗であり、新episodeの固定Kとは別",
    "stage": "取消後も最大到達。T0..3/R0..4。期限又は局所resetで0",
    "k形成後統計": "取消後も置換又は期限まで既知終値を記述。再点火しない",
    "age": "(判断time-k.confirm)/900。k未形成だけ-1", "進行尺度": "現在判断の旧ATRを全既知終値に共通使用",
    "k未形成数値": {"age": -1, "進行": 0, "戻り": 0},
    "支持": "unique枠は同episodeの反復を含む。episode診断を別記し、gate/重みは変えない"}


def source_ref(row: dict | None) -> dict | None:
    """公開出典を足番号と公開keyだけで参照する。

    引数: row(dict|None)は公開足又は未形成。
    返り値: dict|Noneはindex/key。SOURCE全文は重複保存しない。
    """
    return None if row is None else {"index": row["index"], "key": [row["confirm"], row["confirm_line"]]}


def coordinates(row: dict, level: Fraction, direction: int) -> tuple:
    """固定Kから元突破方向を正とする精密な価格座標を作る。

    引数: row(dict)は有効OHLC、level(Fraction)はK、direction(int)は元突破±1。
    返り値: tuple[Fraction,Fraction,Fraction]はq_min/q_max/q_close。
    """
    extremes = [direction * (Fraction(row[name]) - level) for name in ("high", "low")]
    return min(extremes), max(extremes), direction * (Fraction(row["close"]) - level)


def visible_sources(slot: dict, frames3: list[dict]) -> list[dict]:
    """価格を検査する前に、当場・終了時刻・公開keyで可視prefixを選ぶ。

    引数: slot(dict)は旧準備済み判断、frames3(list[dict])は元SOURCE銀行。
    返り値: list[dict]は当時可視のSOURCE13射影。可視重複や公開順不正は例外。
    """
    if not isinstance(frames3, list):
        raise ValueError("正本3分SOURCE配列なし")
    rows, seen, previous_key = [], set(), None
    limit = slot["time"], slot["line"]
    for row in frames3:
        if not isinstance(row, dict) or "session" not in row:
            raise ValueError("SOURCEの場又は時計を判定できない")
        if row["session"] != slot["session"]:
            continue
        if not I49.finite(row.get("end")):
            raise ValueError("SOURCEの可視時計が不正")
        if row["end"] > slot["scheduled"]:
            continue
        if (not I49.finite(row.get("confirm")) or type(row.get("confirm_line")) is not int
                or row["confirm_line"] < 0):
            raise ValueError("SOURCEの可視時計が不正")
        if I49.key(row) > limit:
            continue
        index = row.get("index")
        if type(index) is not int or index < 0 or index in seen:
            raise ValueError("可視SOURCEの番号不正又は重複")
        if previous_key is not None and I49.key(row) <= previous_key:
            raise ValueError("可視SOURCEの公開key同値又は後退")
        seen.add(index)
        previous_key = I49.key(row)
        rows.append({name: row.get(name) for name in SOURCE_FIELDS})
    return rows


class Route:
    """一つの元方向とT/Rに、一つの保持水準と取消履歴を対応させる。"""

    def __init__(self, session: str, direction: int, role: str) -> None:
        """未登録の独立機械を作る。

        引数: session(str)は場、direction(int)は元突破±1、role(str)はT/R。
        返り値: None。
        """
        if direction not in (-1, 1) or role not in ("T", "R"):
            raise ValueError("価格経路の方向又は種類が不正")
        self.session, self.direction, self.role = session, direction, role
        self.side = direction if role == "T" else -direction
        self.last_expired = None
        self.clear()

    def clear(self) -> None:
        """直近期限診断を残し、現episodeと価格統計を消す。

        引数: self(Route)は対象機械。
        返り値: None。取消済みを復活させる操作ではない。
        """
        self.state = {"role": self.role, "side": self.side, "break_direction": self.direction,
            "episode_id": None, "expiry": None, "level": None, "stage": 0,
            "episode_valid": False, "k_valid": False, "b": None, "f": None, "r": None,
            "k": None, "line": None, "cancel": None, "reference_indices": [],
            "reference_keys": [], "trace": []}
        self.level = self.r_near = self.r_far = self.k_close = None
        self.last_close = self.peak = None

    def expire(self, time: float, line: int, index: int | None, kind: str) -> bool:
        """公開秒又は判断秒の等号を含め、60分期限を反映する。

        引数: time(float)/line(int)は観測key、index(int|None)は足番号、kind(str)は公開足/判断時刻。
        返り値: boolは今回失効したか。旧IDは診断として保持する。
        """
        if self.state["episode_id"] is None or time < self.state["expiry"]:
            return False
        self.last_expired = {"episode_id": self.state["episode_id"], "expiry": self.state["expiry"],
            "reason": "b公開から3600秒失効", "stage": self.state["stage"],
            "b": deepcopy(self.state["b"]), "k": deepcopy(self.state["k"]),
            "observed_at": {"kind": kind, "time": time, "line": line, "index": index}}
        self.clear()
        return True

    def record(self, row: dict, action: str) -> None:
        """現episodeの状態遷移だけを小型traceへ保存する。

        引数: row(dict)は公開足、action(str)は登録/段階/取消の名前。
        返り値: None。待機足の全文やSOURCEは転記しない。
        """
        self.state["trace"].append({**source_ref(row), "action": action,
            "stage": self.state["stage"], "episode_valid": self.state["episode_valid"],
            "k_valid": self.state["k_valid"]})

    def register(self, row: dict, reference: list[dict]) -> bool:
        """当足を除く10本から新Kを作り、同Kで初crossを判定する。

        引数: row(dict)は新足、reference(list[dict])は直前の完全隣接10足。
        返り値: boolは新episodeを登録したか。有効episodeの置換には使わない。
        """
        if len(reference) != 10:
            return False
        name = "high" if self.direction == 1 else "low"
        values = [Fraction(item[name]) for item in reference]
        level = max(values) if self.direction == 1 else min(values)
        previous = coordinates(reference[-1], level, self.direction)[2]
        close = coordinates(row, level, self.direction)[2]
        if not (previous < 5 and close >= 5):
            return False
        self.clear()
        self.level = level
        self.state.update(episode_id=f"{self.session}|{self.role}|{self.direction:+d}|{row['index']}|"
            f"{float(row['confirm']).hex()}|{row['confirm_line']}", expiry=row["confirm"] + 3600,
            level=float(level), stage=1, episode_valid=True, b=source_ref(row),
            reference_indices=[item["index"] for item in reference],
            reference_keys=[[item["confirm"], item["confirm_line"]] for item in reference])
        self.record(row, "b登録")
        return True

    def step(self, row: dict, reference: list[dict]) -> None:
        """期限、取消、段階、取消後の置換を一公開足につき一度だけ処理する。

        引数: row(dict)は有効足、reference(list[dict])は直前10足までの履歴。
        返り値: None。期限越え足と取消足は新bへ使わず、足内順序は推測しない。
        """
        if self.expire(row["confirm"], row["confirm_line"], row["index"], "公開足"):
            return
        state, cancelled_now = self.state, False
        if state["episode_valid"]:
            near, far, close = coordinates(row, self.level, self.direction)
            band_failure = self.role == "T" and close <= -5
            reacquired = self.role == "R" and state["f"] is not None and close >= 5
            denied = state["k"] is not None and self.side * (Fraction(row["close"]) - Fraction(state["line"])) <= 0
            reasons = (["T帯内失敗"] if band_failure else ["R元外側再取得"] if reacquired else [])
            if denied:
                reasons.append("確認kの突破線否定")
            if reasons:
                state.update(episode_valid=False, k_valid=False,
                    cancel={**source_ref(row), "reasons": reasons})
                self.record(row, "取消")
                cancelled_now = True
            elif state["k"] is None:
                if self.role == "T":
                    if state["r"] is None and near <= 0 and close >= 5:
                        state.update(r=source_ref(row), stage=2)
                        self.r_near, self.r_far = near, far
                        self.record(row, "T再試験r")
                    elif state["r"] is not None and close > self.r_far:
                        self.form_k(row, 3, "T再開k")
                elif state["f"] is None and close <= -5:
                    state.update(f=source_ref(row), stage=2)
                    self.record(row, "R内復帰f")
                elif state["f"] is not None and state["r"] is None and far >= 0 and close <= -5:
                    state.update(r=source_ref(row), stage=3)
                    self.r_near, self.r_far = near, far
                    self.record(row, "R再試験r")
                elif state["r"] is not None and close < self.r_near:
                    self.form_k(row, 4, "R再開k")
        # ----------------------------------------
        # 有効中はKを更新しない。以前の足で取消済みなら、新Kのcrossだけを置換候補にする。
        if not self.state["episode_valid"] and not cancelled_now:
            self.register(row, reference)
        # ----------------------------------------
        # k後は取消後も終値統計を記述する。新b置換又は期限/resetで旧統計は消える。
        if self.state["k"] is not None:
            self.last_close = Fraction(row["close"])
            self.peak = max(self.peak, self.side * (self.last_close - self.k_close))

    def form_k(self, row: dict, stage: int, action: str) -> None:
        """最初のkと、突破したr端を固定する。

        引数: row(dict)はk足、stage(int)はT3/R4、action(str)はtraceの動作。
        返り値: None。k自身の高安を確認後最大進行へ使わない。
        """
        boundary = self.r_far if self.role == "T" else self.r_near
        self.state.update(k=source_ref(row), stage=stage, k_valid=True,
            line=float(self.level + self.direction * boundary))
        self.k_close = self.last_close = Fraction(row["close"])
        self.peak = Fraction(0)
        self.record(row, action)

    def snapshot(self, atr: float, time: float) -> dict:
        """判断時のATRで終値統計を正規化し、JSON保存用の状態を返す。

        引数: atr(float)は旧有限正ATR、time(float)は判断秒。
        返り値: dictは57共通schemaとID/期限/小型登録参照。内部Fractionは転記しない。
        """
        result = deepcopy(self.state)
        if self.state["k"] is None:
            age, progress, peak, pullback = -1.0, 0.0, 0.0, 0.0
        else:
            age = (time - self.state["k"]["key"][0]) / 900
            denominator = Fraction(atr)
            current = self.side * (self.last_close - self.k_close)
            progress, peak, pullback = float(current / denominator), float(self.peak / denominator), float((self.peak - current) / denominator)
            if age < 0:
                raise ValueError("確認kが判断より未来")
        if not all(math.isfinite(value) for value in (age, progress, peak, pullback)):
            raise ValueError("保持経路の表示数値が非有限")
        result.update(age=age, progress=progress, max_close_progress=peak, pullback=pullback,
            last_expired=deepcopy(self.last_expired))
        return result


def reconstruct(slot: dict, rows: list[dict], atr: float) -> tuple[dict, dict]:
    """可視prefixを再構成し、過去の定時readyに依存しない四つの機械を作る。

    引数: slot(dict)は判断、rows(list[dict])は可視SOURCE13、atr(float)は判断ATR。
    返り値: tuple[dict,dict]は実side別pathsと小型出典/リセット診断。
    """
    if not I49.finite(atr) or atr <= 0:
        raise ValueError("判断ATRは有限正値が必要")
    routes = {(direction, role): Route(slot["session"], direction, role)
        for direction in (1, -1) for role in ("T", "R")}
    reference, previous, resets, last_reset = deque(maxlen=10), None, 0, None
    for row in rows:
        reason = F53.F._source_reason(row, slot["session"], 3, slot["scheduled"], (slot["time"], slot["line"]))
        if not reason and previous is not None and not I49.adjacent(previous, row):
            reason = "番号又は終了時刻のgap"
        if reason:
            for route in routes.values():
                route.clear()
            reference.clear()
            previous = None
            resets += 1
            last_reset = {**source_ref(row), "reason": reason}
            if F53.F._source_reason(row, slot["session"], 3, slot["scheduled"], (slot["time"], slot["line"])):
                continue
        for route in routes.values():
            route.step(row, list(reference))
        reference.append(row)
        previous = row
    for route in routes.values():
        route.expire(slot["time"], slot["line"], None, "判断時刻")
    paths = {str(side): {"T": routes[(side, "T")].snapshot(atr, slot["time"]),
        "R": routes[(-side, "R")].snapshot(atr, slot["time"])} for side in (1, -1)}
    # ----------------------------------------
    # 元銀行の当時可視な13列だけを指紋化する。非有限な不正価格もhash入力には識別して残す。
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=True)
    history = {"source_prefix_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "source_prefix_count": len(rows), "source_fields": list(SOURCE_FIELDS),
        "source_hash_encoding": "SOURCE13の可視順JSON。ensure_ascii=False/sort_keys=True/compact/allow_nan=True",
        "first_source": source_ref(rows[0]) if rows else None, "last_source": source_ref(rows[-1]) if rows else None,
        "reference_ready_count": len(reference), "reset_count": resets, "last_reset": last_reset}
    return paths, history


def extract(slot: dict, frames3: list[dict]) -> dict:
    """旧18特徴と同じ準備で、登録水準を60分保持するT/R各六列を加える。

    引数: slot(dict)は既存定時判断、frames3(list[dict])は当場の正本SOURCE銀行。
    返り値: dictはready/reason/base/control_vectors18/vectors30/atr/D/background_direction/paths/history。
        旧global/入力/出力を変更せず、教師・約定・損益・未来足価格を使わない。
    """
    base = F53.extract(slot, frames3)
    result = {"ready": base["ready"], "reason": base["reason"], "base": base,
        "control_vectors": deepcopy(base["vectors"]), "vectors": {"1": [], "-1": []},
        "atr": base["atr"], "D": base["D"], "background_direction": base["background_direction"],
        "paths": {"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}}, "history": None}
    if not base["ready"]:
        return result
    rows = visible_sources(slot, frames3)
    if not rows or rows[-1] != base["history"]["reaction_sources"][-1]:
        raise ValueError("保持経路の可視最新SOURCEと旧現足が不一致")
    paths, history = reconstruct(slot, rows, base["atr"])
    result.update(paths=paths, history=history)
    for side in ("1", "-1"):
        additional = []
        for role in ("T", "R"):
            path = paths[side][role]
            additional.extend([path["stage"], int(path["episode_valid"]), int(path["k_valid"]),
                path["age"], path["progress"], path["pullback"]])
        result["vectors"][side] = deepcopy(base["vectors"][side]) + additional
    return result
