"""固定21指標と、公開30分足六本の高安窓を保持する。"""

from collections import deque
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("高安再開の固定21指標", ROOT/"scripts/異種発動/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, Indicators, features = BASE.W, BASE.Indicators, BASE.features
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")


class ChannelBank:
    """同限月の完全公開足だけを場間carryする六本窓。"""

    def __init__(self) -> None:
        """空窓と前場の連続性状態を初期化する。

        引数: なし。
        返り値: None。
        """
        self.window = deque(maxlen=6)
        self.contract = None
        self.last_session = None

    def snapshot(self, session: str, key: tuple, end: float, published: bool,
                 reason: list[str], kind: str) -> dict:
        """現在窓の出典と可否を不変記録へ変換する。

        引数: session/kind (str) は現場/記録種別、key (tuple) は可用時計原行、end (float) は足終了、
        published (bool) はasof採用可否、reason (list[str]) はclear等の理由。
        返り値: dict は六本と境界。未準備は価格を補わない。
        """
        sources = deepcopy(list(self.window))
        upper = max((f["high"] for f in sources), default=None)
        lower = min((f["low"] for f in sources), default=None)
        ready = len(sources) == 6 and upper > lower
        return {"場": session, "種別": kind, "参照ID": f"NK225_{session}_30窓_{kind}_{key[0]}_{key[1]}",
                "confirm": key[0], "confirm_line": key[1], "end": end, "publish": published,
                "30窓準備済": ready, "30窓本数": len(sources), "R": upper if ready else None,
                "L": lower if ready else None, "30足出典": sources, "窓解除理由": reason}

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """公開六本を更新し、初期carryと全30足snapshotを返す。

        引数: frames (list[dict]) は一場の完全幅30足、session (str) は場、contract (tuple) は限月、
        tail_missing (int) は末尾の完全幅欠枠数。
        返り値: tuple[list[dict],dict] はasof記録列と件数。非公開/欠枠後は新窓から再蓄積。
        """
        resets = []
        if self.contract is not None and contract != self.contract:
            self.window.clear()
            resets.append("限月変更")
        self.contract = contract
        first = self.window[-1] if self.window else None
        rows = [self.snapshot(session, (first["confirm"], first["confirm_line"]) if first else (-1.0, 0),
                              first["end"] if first else -1.0, True, resets, "場開始carry")]
        previous_index, previous_key = None, None
        clear_count = int(bool(resets))
        for frame in frames:
            key = frame["confirm"], frame["confirm_line"]
            if frame["minutes"] != 30 or previous_index is not None and frame["index"] <= previous_index:
                raise ValueError("30分足の尺度/順序が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("30分公開の先読み/後退")
            reasons = []
            if previous_index is None and frame["index"] != 0 or previous_index is not None and frame["index"] != previous_index+1:
                reasons.append("30分番号欠枠")
            if frame["missing"]:
                reasons.append("30分欠枠")
            if not frame["publish"]:
                reasons.append("非公開完全30足")
            valid = all(isinstance(frame.get(k), (int, float)) and math.isfinite(frame[k]) and frame[k] > 0 for k in ("high", "low"))
            valid = valid and frame["high"] >= frame["low"]
            if not valid:
                reasons.append("30分高安不正")
            if reasons:
                self.window.clear()
                clear_count += 1
            if valid and frame["publish"]:
                self.window.append({"場": session, **{k: frame[k] for k in SOURCE_FIELDS}})
            rows.append(self.snapshot(session, key, frame["end"], frame["publish"], reasons, str(frame["index"])))
            previous_index = frame["index"]
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.window.clear()
            clear_count += 1
        self.last_session = session
        return rows, {"30足数": len(frames), "30窓準備snapshot数": sum(r["30窓準備済"] for r in rows),
                      "30窓clear数": clear_count, "30尾部欠枠": tail_missing}
