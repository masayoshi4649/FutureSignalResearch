"""固定37T1を保ち、上位一目の準備差と同時点の雲方向差を分離する。"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math

SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "open", "high", "low", "close")
ICHI_FIELDS = ("ichimoku_tenkan", "ichimoku_kijun", "ichimoku_a", "ichimoku_b",
    "cloud_a", "cloud_b", "cloud_upper", "cloud_lower")
UPPER_FIELDS = ("場", *SOURCE_FIELDS, *ICHI_FIELDS, "雲計算元足", "一目数値入力可", "一目準備済",
    "一目公開可", "一目窓本数", "銀行解除理由")
POLICIES = ("H0", "H1", "H2")
ROLES = {p: "順行" for p in POLICIES}


def finite(value: object) -> bool:
    """欠測・真偽値・非有限値を除いた実数か検査する。

    引数: value(object)は任意の末端値。
    返り値: boolは有限な価格又は指標値であること。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def canonical_sha(value: object) -> str:
    """小型の純採否・公開出典を厳密JSON指紋へ写す。

    引数: value(object)はJSON互換値。
    返り値: strは並びと全末端値を保持するSHA256。非有限値は拒否する。
    """
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def upper_projection(row: dict | None) -> dict | None:
    """固定28の15分保存足から、上位一目とその出典だけを取り出す。

    引数: row(dict|None)は固定28の全指標足又は当場未公開。
    返り値: dict|Noneは限定射影。ATR・Stoch・Fast・未来ラベルを含めない。
    """
    if row is None:
        return None
    if row["minutes"] != 15:
        raise ValueError("上位参照は固定28の15分だけ")
    return {key: deepcopy(row[key]) for key in UPPER_FIELDS}


def pure_signal(row: dict, policy: str = "H0") -> dict:
    """固定37T1の13列を、識別子だけ変更して三案へ写す。

    引数: row(dict)は旧37T1純入口、policy(str)はH0/H1/H2。
    返り値: dictは値・要求時計・役割を変えない13列。追加の診断やラベルは渡さない。
    """
    if policy not in POLICIES:
        raise ValueError("事前の上位雲三案だけです")
    if row["入口ID"] != "3分_T1" or not row["イベントID"].endswith("_T1"):
        raise ValueError("固定37T1の純入口だけを受け取ります")
    if row["役割"] != "順行" or row["side"] not in (-1, 1):
        raise ValueError("全入口は実方向が明示された順行だけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("方向表示と実sideが不一致")
    value = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    value.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
    return value


def classification(upper: dict | None, side: int) -> tuple[bool, list[str], str, str]:
    """最新公開足の数値準備、雲位置、診断だけの転換基準方向を分ける。

    引数: upper(dict|None)は最新当場公開参照、side(int)は実注文方向。
    返り値: tuple[bool,list[str],str,str]は準備可/除外理由/雲方向/TJ方向。
    """
    if upper is None:
        return False, ["当場公開15分なし"], "未準備", "未準備"
    required = ("ichimoku_tenkan", "ichimoku_kijun", "cloud_upper", "cloud_lower")
    ready = bool(upper["一目公開可"] and all(finite(upper[k]) for k in required))
    reasons = [] if ready else ["当場最新公開15分一目未準備"]
    tj = "未準備"
    if all(finite(upper[k]) for k in ("ichimoku_tenkan", "ichimoku_kijun")):
        direction = side*(upper["ichimoku_tenkan"]-upper["ichimoku_kijun"])
        tj = "同方向" if direction > 0 else "逆方向" if direction < 0 else "等号"
    cloud = "未準備"
    if ready:
        close, lower, higher = upper["close"], upper["cloud_lower"], upper["cloud_upper"]
        if not finite(close) or lower > higher:
            raise ValueError("公開可の上位終値又は雲上下端が不正")
        if close in (lower, higher):
            cloud = "等号"
        elif close > higher:
            cloud = "実方向外" if side == 1 else "逆方向外"
        elif close < lower:
            cloud = "実方向外" if side == -1 else "逆方向外"
        else:
            cloud = "内"
    return ready, reasons, cloud, tj


# ----------------------------------------
# 元T1を同じ時計で一回消費し、公開済みの上位値だけで部分集合を作る。

def select(block: dict, higher15: list[dict], session: str | None = None) -> dict:
    """旧T1純集合に上位準備と雲位置を順に追加し、三採否を保存する。

    引数: block(dict)はsignals/frames[3]/下位出典、higher15(list[dict])は固定28の当場15分列、
    session(str|None)は場。省略時はblockの場又は元純入口の場を使う。
    返り値: dictは三signalsとdecisionsを追加した場材料。元Pや未来caseは受け取らない。
    """
    original = block["signals"]["3分_T1"]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None:
        raise ValueError("空のT1場でも場を明示してください")
    if any(r["場"] != actual_session or r["minutes"] != 15 for r in higher15):
        raise ValueError("当場の15分足だけを上位参照へ渡します")
    frames = block["frames"][3]
    if any(f["minutes"] != 3 for f in frames):
        raise ValueError("下位出典は固定29の3分だけです")
    frame_by_index = {f["index"]: f for f in frames}
    if len(frame_by_index) != len(frames):
        raise ValueError("下位足番号は一意だけです")
    keys = [(r["要求時計秒"], r["要求原板行"]) for r in original]
    if keys != sorted(keys) or any(n > 1 for n in Counter(keys).values()):
        raise ValueError("固定37T1の競合後・公開順の純集合だけです")
    if len({r["イベントID"] for r in original}) != len(original):
        raise ValueError("旧T1イベントIDは一意だけです")
    projected = [upper_projection(row) for row in higher15]
    published = sorted((r for r in projected if r["publish"]), key=lambda r: (r["confirm"], r["confirm_line"], r["index"]))
    visible, pointer, decisions = [], 0, []
    grouped = {"3分_"+p: [] for p in POLICIES}
    for row in original:
        if row["場"] != actual_session:
            raise ValueError("旧T1純入口の場が不一致")
        pure_signal(row)
        lower = block["下位出典"][row["イベントID"]]
        source = frame_by_index[lower["index"]]
        if any(lower[k] != source[k] for k in SOURCE_FIELDS):
            raise ValueError("元T1の足番号出典が固定29の3分足と不一致")
        key = (row["要求時計秒"], row["要求原板行"])
        if key != (lower["confirm"], lower["confirm_line"]) or not lower["publish"]:
            raise ValueError("元T1要求keyと下位公開出典が不一致")
        while pointer < len(published) and (published[pointer]["confirm"], published[pointer]["confirm_line"]) <= key:
            visible.append(published[pointer])
            pointer += 1
        upper = next((r for r in reversed(visible) if r["end"] <= lower["end"]), None)
        ready, reasons, cloud, tj = classification(upper, row["side"])
        verdicts = {
            "H0": {"採用": True, "理由": ["固定37T1完全入口"], "同時競合": False},
            "H1": {"採用": ready, "理由": ["上位数値準備採用"] if ready else list(reasons), "同時競合": False},
            "H2": {"採用": ready and cloud == "実方向外", "理由": list(reasons) if not ready else
                ["上位現在雲外実方向採用"] if cloud == "実方向外" else ["上位現在雲外実方向不成立"], "同時競合": False}}
        decisions.append({"場": actual_session, "元37T1イベントID": row["イベントID"], "元index": lower["index"],
            "足終了時計秒": lower["end"], "要求時計秒": key[0], "要求原板行": key[1],
            "実side": row["side"], "役割": "順行", "上位参照": deepcopy(upper),
            "上位準備": ready, "準備除外理由": reasons, "雲方向": cloud, "TJ方向": tj, "戦略判定": verdicts})
        for policy in POLICIES:
            if verdicts[policy]["採用"]:
                grouped["3分_"+policy].append(pure_signal(row, policy))
    block.update(signals=grouped, decisions=decisions)
    return block
