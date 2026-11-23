"""明示的なForce波失敗fと後続価格確認kで、反転確認と禁止不在を比べる。"""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("Force失敗確認の精密数値", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
SOURCE_FIELDS, FRAME_FIELDS, UPPER_FIELDS = J.SOURCE_FIELDS, J.FRAME_FIELDS, J.UPPER_FIELDS
finite, exact, fraction_value, canonical_sha = J.finite, J.exact, J.fraction_value, J.canonical_sha
frame_projection, upper_projection = J.frame_projection, J.upper_projection
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("S0", "S1")
ROLES = {policy: "切替" for policy in POLICIES}
ACTIVE_ROLES = {policy: ("順行", "反転") for policy in POLICIES}
FAILURE_FIELDS = ("失敗足番号", "失敗時計秒", "失敗原板行", "失敗ID", "失敗段階", "失敗確認端")
METADATA_FIELDS = ("元登録ID", "元価格side", "元登録時計秒", "元登録原板行", "回復足番号", "回復時計秒", "判別種別", *FAILURE_FIELDS)
WATCH_FIELDS = ("登録ID", "元価格side", "登録足番号", "登録時計秒", "登録原板行", "初期逆端", "段階",
    "回復足番号", "回復時計秒", "回復原板行", "回復ID", "再開端", *FAILURE_FIELDS)
RULES = {
    **deepcopy(J.RULES),
    "上位参照": "当場公開15分uとindex-1を下位end/key両asofで参照。最新はmax(confirm,line,index)、前足は同可視集合から選び不在/NP/未来をNone同理由へ。両完全900/missing0/有効OHLC/H有限/index-end隣接/前key<=現key。最新不良から古正常へ戻らない",
    "背景": "D=sign(H現-H前)、E=sign(EMA13現-前)、Iは有限準備のD=E非0なら同符号、他0、欠測None。bとTにはEMA準備/値gateなし。H水準符号は使わずp/bの各当時D=s非0を要求、同一上位uを独立二票にしない",
    "登録": "s*Force前>=0かつs*Force現<0の全crossを候補記録。p/bのD=s、一監視空き、同足終了なし、b.confirm<deadlineで受理。bにcutoff/残60/遅延30/ATR/EMAを追加しない",
    "寿命": "age=現index-b.index、1..6を回復j/失敗f/確認kで共有し再起算しない。年齢7以降先満了、場末終了。同足消費/取消/満了後の新候補は不受理で保存",
    "回復": "対象足end>b.confirmかつkey>b.key。回復前の元逆端strict終値失敗をForce回復より先にf固定。最初s*Force>0はD=sならj固定、不一致ならWAIT消費。start>親confirmは要求しない",
    "失敗": "回復前の元逆端strict終値失敗又はj後初失敗端をfとし、失敗足low(元s買)/high(売)をB固定。fでD反転/逆Force/ATR/EMAを要求せずmonitorだけへ保存。f後はTへ戻らない",
    "価格": "j後end>j.confirmかつkey>j.keyの最初終値端でCが再開端外ならT一回採否、元逆端外ならfへ。f後end>f.confirmかつkey>f.keyの対象足はs*(C-元逆端)>=0を先取消し、r*(C-B)>0の初kだけR一回採否。等号B未到達、元逆端等号は取消。r=-s、同足f/k不可",
    "終端": "共通Tは現在D=s/Force方向s/現ATR正/時間遅延可。Rは現在Force方向r/有限H現前とEMA現前/現ATR正/時間遅延可を共通、S0はD=r、S1はI!=sを追加。初k不採用は消費し後の値で救済しない",
    "優先": "価格公開不正/番号-endgap/Force又は最新上位Hペア未準備/期限→age>6→段階時点対象外(寿命のみ)→f後元逆端回復取消→各段階の価格/Force。D0/逆/EMA未準備だけでは監視取消せずATRは終端だけ",
    "比較": "同じ新母機械のS0/S1切替2案・active4役割・全XF。純Tは両案同値、共通EMA準備下で純R/S全体S0はS1部分集合。旧47は母占有/時計が変わるため完全対照なし。実一建玉の包含/額和は保証しない",
    "執行": "T端又は新R確認kの要求時ATR固定D、現時計+1秒正常BBO/TTL30/125250/費用後現在益122円strict正起動/名目床を継承。先着は新要求/実sideで直接計算、fの価格/ATR/時計を転用しない",
    "競合": "同判断の候補複数は同方向も全見送り。全採否確定後にenriched深写しpure13化、親/回復/失敗/上位/将来labelは実運用へ渡さない",
}


def key_of(row: dict) -> tuple:
    """価格公開の同秒行順を得る。

    引数: row(dict)は価格足。
    返り値: tupleはconfirm/confirm_line。
    """
    return row["confirm"], row["confirm_line"]


def price_source(row: dict) -> dict:
    """価格公開SOURCEだけを深写する。

    引数: row(dict)は当場足。
    返り値: dictは場/SOURCE12。
    """
    return {name: deepcopy(row[name]) for name in ("場", *SOURCE_FIELDS)}


def pair_state(current: dict | None, previous: dict | None, lower: dict) -> dict:
    """最新当場15分の現前ヒスト差と未準備理由を作る。

    引数: current/previous(dict|None)は当時可視の最新/隣接前足、lower(dict)は3分判断足。
    返り値: dictは公開参照/準備/ヒスト現前差/方向。未来前足の有無は露出しない。
    """
    reasons = []
    if current is None: reasons.append("当場公開15分なし")
    elif previous is None: reasons.append("前上位公開参照なし")
    for label, row in (("現", current), ("前", previous)):
        if row is None: continue
        if not row["publish"]: reasons.append(label+"15分非公開")
        if not J.price_valid(row, 15): reasons.append(label+"15分完全価格不正")
        if row["missing"]: reasons.append(label+"15分欠枠")
        if row["confirm"] < row["end"]: reasons.append(label+"15分終了前公開")
        if row["end"] > lower["end"] or key_of(row) > key_of(lower): reasons.append(label+"15分asof不成立")
        if not finite(row["macd_hist"]): reasons.append(label+"15分MACDヒスト未準備")
    if current is not None and previous is not None:
        if previous["index"]+1 != current["index"] or previous["end"] != current["start"]:
            reasons.append("上位現前番号又は終了非隣接")
        if key_of(previous) > key_of(current): reasons.append("上位前後公開順不整合")
    ready = not reasons
    delta = current["macd_hist"]-previous["macd_hist"] if ready else None
    if ready and not finite(delta):
        reasons.append("上位MACDヒスト差非有限"); ready = False; delta = None
    sign = (delta > 0)-(delta < 0) if delta is not None else None
    ema_reasons = [reason for reason in reasons if "MACDヒスト" not in reason]
    for label, row in (("現", current), ("前", previous)):
        if row is not None and not finite(row["ema13_centered"]):
            ema_reasons.append(label+"15分EMA13未準備")
    ema_ready = not ema_reasons
    ema_delta = current["ema13_centered"]-previous["ema13_centered"] if ema_ready else None
    if ema_ready and not finite(ema_delta):
        ema_reasons.append("上位EMA13差非有限")
        ema_ready, ema_delta = False, None
    ema_sign = (ema_delta > 0)-(ema_delta < 0) if ema_delta is not None else None
    impulse = sign if ready and ema_ready and sign == ema_sign and sign != 0 else 0 if ready and ema_ready else None
    return {"上位参照": upper_projection(current), "前上位参照": upper_projection(previous),
        "上位現前準備": ready, "上位除外理由": reasons,
        "上位ヒスト現": current["macd_hist"] if current is not None else None,
        "上位ヒスト前": previous["macd_hist"] if previous is not None else None,
        "上位ヒスト差": delta, "上位ヒスト差符号": sign, "上位方向": sign,
        "上位EMA現": current["ema13_centered"] if current is not None else None,
        "上位EMA前": previous["ema13_centered"] if previous is not None else None,
        "上位EMA差": ema_delta, "上位EMA差符号": ema_sign,
        "上位EMA現前準備": ema_ready, "上位EMA除外理由": ema_reasons,
        "上位Impulse方向": impulse}


def upper_state(higher15: list[dict], lower: dict) -> dict:
    """可視集合だけから上位の最新と隣接前足を選ぶ。

    引数: higher15(list[dict])は当場上位15列、lower(dict)は3分判断足。
    返り値: dictはpair_state。最新未準備を古正常で代替しない。
    """
    visible = [row for row in higher15 if row["publish"] and row["end"] <= lower["end"] and key_of(row) <= key_of(lower)]
    current = max(visible, key=lambda row: (*key_of(row), row["index"]), default=None)
    previous = next((row for row in visible if row["index"] == current["index"]-1), None) if current is not None else None
    return pair_state(current, previous, lower)


def pure_signal(row: dict, policy: str = "S0") -> dict:
    """最初価格端の実side/役割と当時13列だけを実運用へ渡す。

    引数: row(dict)は採用enriched又は判定、policy(str)はS0/S1。
    返り値: dictは純13。上位・登録・回復・将来labelを含めない。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] not in ACTIVE_ROLES[policy]:
        raise ValueError("候補の実役割と実方向に差")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示に差")
    value = {name: deepcopy(row[name]) for name in SIGNAL_FIELDS if name not in ("イベントID", "入口ID", "bb_mean")}
    value.update(イベントID=row["発動ID"]+"_"+policy, 入口ID="3分_"+policy, bb_mean=None)
    return value


def verdicts(row: dict) -> dict:
    """共通Tと、同じ新R確認でD反転/旧方向禁止不在を比較する。

    引数: row(dict)はT初端又はR確認kの全当時判定。
    返り値: dictはS0/S1の採否。値条件と共通準備を分離する。
    """
    common = list(row["M除外理由"])
    if not row["技術方向可"]:
        common.append("終端Force又は共通T上位実方向不一致")
    if not row["時間条件可"]:
        common.append("新要求時間条件外")
    if not row["確認遅延条件可"]:
        common.append("新要求確認遅延上限外")
    result = {}
    for policy in POLICIES:
        reasons = list(common)
        if row["価格区分"] == "R":
            if policy == "S0" and row["上位方向"] != row["side"]:
                reasons.append("反転確認kの上位D反転不一致")
            if policy == "S1" and (row["上位Impulse方向"] is None or row["上位Impulse方向"] == row["元価格side"]):
                reasons.append("反転確認kの旧方向Impulse禁止又は未準備")
        result[policy] = {"採用": not reasons, "理由": reasons or ["共通T又は失敗後初価格確認R採用"], "同時競合": False}
    return result


def event_row(frame: dict, watch: dict, upper: dict, kind: str, cutoff: float, deadline: float, config: dict) -> dict:
    """T初端又は新R確認kに当時の実方向・役割・二案採否を保存する。

    引数: frame/watch/upper(dict)は現足/親監視/上位状態、kind(str)はT/R、
    cutoff/deadline(float)とconfig(dict)は新要求の時間規約。
    返り値: dictは新P全判定。f自体の時計/ATR/価格を要求へ転用しない。
    """
    side = watch["元価格side"] if kind == "T" else -watch["元価格side"]
    now = frame["confirm"]
    time_ok = now < cutoff and now < deadline and deadline-now >= config["残り時間下限分"]*60
    delay_ok = now-frame["end"] <= config["確認遅延上限秒"]
    missing = []
    if not upper["上位現前準備"]:
        missing.append("最新上位現前未準備")
    if kind == "R" and not upper["上位EMA現前準備"]:
        missing.append("反転確認kの共通EMA現前未準備")
    if not frame["Force2"]["有効"]:
        missing.append("Force2未準備")
    if not finite(frame["atr"]) or frame["atr"] <= 0:
        missing.append("現在ATR14有限正未準備")
    direction_ok = bool(frame["Force符号"] == side and (kind == "R" or upper["上位方向"] == side))
    event = watch["登録ID"]+f"_{'順行初端' if kind == 'T' else '反転確認'}_{frame['index']:04d}"
    row = {**J.numeric_projection(frame), "時間足分": 3, "入口系統": "Force失敗後の価格確認",
        "発動ID": event, "イベントID": event, "入口ID": "3分_Force失敗確認", "元登録ID": watch["登録ID"],
        "元価格side": watch["元価格side"], "元登録時計秒": watch["登録時計秒"], "元登録原板行": watch["登録原板行"],
        "登録足番号": watch["登録足番号"], "回復足番号": watch["回復足番号"], "回復時計秒": watch["回復時計秒"],
        "回復原板行": watch["回復原板行"], "回復ID": watch["回復ID"], "初期逆端": watch["初期逆端"], "再開端": watch["再開端"],
        **{name: deepcopy(watch[name]) for name in FAILURE_FIELDS},
        "年齢": frame["index"]-watch["登録足番号"], "価格区分": kind,
        "役割": "順行" if kind == "T" else "反転", "side": side, "方向": "買い" if side == 1 else "売り",
        **deepcopy(upper), "共通M準備": not missing, "M除外理由": missing, "技術方向可": direction_ok,
        "時間条件可": time_ok, "確認遅延条件可": delay_ok, "要求時計秒": now, "要求原板行": frame["confirm_line"],
        "足終了時計秒": frame["end"], "確認遅延秒": now-frame["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline-now)/60, "先着評価対象": time_ok and delay_ok, "bb_mean": None}
    row["戦略判定"] = verdicts(row)
    row["判別種別"] = kind if any(value["採用"] for value in row["戦略判定"].values()) else "WAIT"
    return row


def fix_failure(frame: dict, watch: dict, upper: dict, stage: str, age: int) -> dict:
    """最初の失敗fとその極値Bを監視へ固定する。

    引数: frame/watch/upper(dict)はf/監視/上位、stage(str)は回復前/回復後、age(int)はbからの年齢。
    返り値: dictは出典を一度持つ監視action。watchを反転確認待ちへ更新する。
    """
    event = watch["登録ID"]+f"_失敗_{frame['index']:04d}"
    watch.update(段階="反転確認待ち", 失敗足番号=frame["index"], 失敗時計秒=frame["confirm"],
        失敗原板行=frame["confirm_line"], 失敗ID=event, 失敗段階=stage,
        失敗確認端=frame["low"] if watch["元価格side"] == 1 else frame["high"])
    return {"動作": "初回失敗固定", "登録ID": watch["登録ID"], "失敗ID": event, "失敗段階": stage, "年齢": age,
        "失敗参照": {"足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]), **deepcopy(upper)}}


# ----------------------------------------
# 一監視の純価格機械。実pendingや建玉占有は後段の二運用へだけ委ねる。

def generate(frames: list[dict], higher15: list[dict], session: str,
             cutoff: float, deadline: float, config: dict) -> dict:
    """背景→逆行cross→回復又は失敗f→後続価格確認kの一巡を構築する。

    引数: frames(list[dict])は新Force26列、higher15(list[dict])は当場上位15列、session(str)は場、
    cutoff/deadline(float)は新規停止/強制、config(dict)は終端の残時間/遅延条件。
    返り値: dictは全数値/全cross登録/全監視/新P/二enriched/metadata/品質。先着・運用は計算しない。
    """
    upper_rows = [upper_projection(row) for row in higher15]
    if any(row["場"] != session or row["minutes"] != 15 for row in upper_rows):
        raise ValueError("当場15分の新H/EMAだけです")
    if len({row["index"] for row in upper_rows}) != len(upper_rows):
        raise ValueError("上位足番号は一意だけです")
    rows = [J.numeric_projection(row) for row in frames]
    records, registrations, trace = [], [], []
    watch, previous, prior_upper, public_key = None, None, None, None
    for frame in rows:
        if frame["場"] != session or frame["minutes"] != 3: raise ValueError("当場Force3分だけです")
        if previous is not None and frame["index"] <= previous["index"]: raise ValueError("下位足番号重複又は後退")
        key = key_of(frame)
        if frame["publish"] and (frame["confirm"] < frame["end"] or public_key is not None and key <= public_key):
            raise ValueError("下位公開key同値/後退又は終了前公開")
        upper = upper_state(upper_rows, frame)
        actions, before = [], deepcopy(watch)
        had_watch = watch is not None
        price_ok = bool(frame["publish"] and not frame["missing"] and J.price_valid(frame))
        adjacent = previous is None or previous["index"]+1 == frame["index"] and previous["end"] == frame["start"]
        cancel_reasons = []
        if not price_ok: cancel_reasons.append("完全公開3分価格不正")
        if not adjacent: cancel_reasons.append("価格番号又は終了非連続")
        if not frame["Force2"]["有効"]: cancel_reasons.append("Force2未準備")
        if not upper["上位現前準備"]: cancel_reasons.append("最新上位現前未準備")
        if frame["confirm"] >= deadline: cancel_reasons.append("強制期限到達")
        if watch is not None:
            age = frame["index"]-watch["登録足番号"]
            parent_prefix = "登録" if watch["段階"] == "回復待ち" else "回復" if watch["段階"] == "価格待ち" else "失敗"
            parent_time, parent_line = watch[parent_prefix+"時計秒"], watch[parent_prefix+"原板行"]
            if cancel_reasons:
                actions.append({"動作": "監視取消", "登録ID": watch["登録ID"], "年齢": age, "理由": cancel_reasons})
                watch = None
            elif age > 6:
                actions.append({"動作": "寿命満了", "登録ID": watch["登録ID"], "年齢": age, "理由": ["元bから6足超"]})
                watch = None
            elif frame["end"] <= parent_time or key <= (parent_time, parent_line):
                actions.append({"動作": "段階時点対象外", "登録ID": watch["登録ID"], "年齢": age, "理由": ["親確認後の終了key未成立"]})
            else:
                side = watch["元価格side"]
                failed = side*(Fraction(frame["close"])-Fraction(watch["初期逆端"])) < 0
                if watch["段階"] == "回復待ち":
                    if failed:
                        actions.append(fix_failure(frame, watch, upper, "回復前", age))
                    elif side*frame["Force符号"] > 0:
                        if upper["上位方向"] != side:
                            actions.append({"動作": "初回回復不一致WAIT", "登録ID": watch["登録ID"], "年齢": age, "理由": ["初Force回復時の上位D不一致"]})
                            watch = None
                        else:
                            recovery = watch["登録ID"]+f"_回復_{frame['index']:04d}"
                            watch.update(段階="価格待ち", 回復足番号=frame["index"], 回復時計秒=frame["confirm"],
                                回復原板行=frame["confirm_line"], 回復ID=recovery,
                                再開端=frame["high"] if side == 1 else frame["low"])
                            actions.append({"動作": "初回回復固定", "登録ID": watch["登録ID"], "回復ID": recovery, "年齢": age,
                                "回復参照": {"足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]), **deepcopy(upper)}})
                elif watch["段階"] == "価格待ち":
                    resumed = side*(Fraction(frame["close"])-Fraction(watch["再開端"])) > 0
                    if failed:
                        actions.append(fix_failure(frame, watch, upper, "回復後", age))
                    elif resumed:
                        record = event_row(frame, watch, upper, "T", cutoff, deadline, config)
                        records.append(record)
                        actions.append({"動作": "順行初端消費", "登録ID": watch["登録ID"], "発動ID": record["発動ID"],
                            "年齢": age, "価格区分": "T", "判別種別": record["判別種別"]})
                        watch = None
                else:
                    returned = side*(Fraction(frame["close"])-Fraction(watch["初期逆端"])) >= 0
                    confirmed = -side*(Fraction(frame["close"])-Fraction(watch["失敗確認端"])) > 0
                    if returned:
                        actions.append({"動作": "失敗後元逆端回復取消", "登録ID": watch["登録ID"], "失敗ID": watch["失敗ID"],
                            "年齢": age, "理由": ["失敗後に元逆端を終値回復又は等号"]})
                        watch = None
                    elif confirmed:
                        record = event_row(frame, watch, upper, "R", cutoff, deadline, config)
                        records.append(record)
                        actions.append({"動作": "反転初確認消費", "登録ID": watch["登録ID"], "発動ID": record["発動ID"],
                            "失敗ID": watch["失敗ID"], "年齢": age, "価格区分": "R", "判別種別": record["判別種別"]})
                        watch = None
        if frame["Force前"]["有効"] and frame["Force2"]["有効"]:
            old_force, current_force = fraction_value(frame["Force前"]), fraction_value(frame["Force2"])
            for side in (1, -1):
                if not (side*old_force >= 0 and side*current_force < 0): continue
                reasons = []
                if previous is None or not adjacent or not price_ok: reasons.append("登録の同場隣接価格未準備")
                if prior_upper is None or not prior_upper["上位現前準備"] or not upper["上位現前準備"]:
                    reasons.append("登録p/b上位現前未準備")
                elif prior_upper["上位方向"] != side or upper["上位方向"] != side:
                    reasons.append("登録p/b背景D不一致")
                if had_watch: reasons.append("監視中又は同足で監視終了")
                if frame["confirm"] >= deadline: reasons.append("登録強制期限以降")
                event = f"NK225_{session}_3分_Force失敗登録_{frame['index']:04d}_{side}"
                registration = {"場": session, "登録ID": event, "元価格side": side, "登録足": frame_projection(frame),
                    "前足番号": previous["index"] if previous is not None else None, "前足Force": deepcopy(frame["Force前"]),
                    "登録Force": deepcopy(frame["Force2"]), "前上位状態": deepcopy(prior_upper), "登録上位状態": deepcopy(upper),
                    "受理": not reasons, "登録除外理由": reasons}
                registrations.append(registration)
                actions.append({"動作": "Force波登録不受理" if reasons else "Force波登録", "登録ID": event,
                    "元価格side": side, "理由": list(reasons)})
                if not reasons:
                    watch = {"登録ID": event, "元価格side": side, "登録足番号": frame["index"],
                        "登録時計秒": frame["confirm"], "登録原板行": frame["confirm_line"],
                        "初期逆端": frame["low"] if side == 1 else frame["high"], "段階": "回復待ち",
                        "回復足番号": None, "回復時計秒": None, "回復原板行": None, "回復ID": None, "再開端": None,
                        **{name: None for name in FAILURE_FIELDS}}
        trace.append({"場": session, "index": frame["index"], "足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]),
            "上位参照足番号": upper["上位参照"]["index"] if upper["上位参照"] is not None else None,
            "前上位参照足番号": upper["前上位参照"]["index"] if upper["前上位参照"] is not None else None,
            "上位現前準備": upper["上位現前準備"], "上位除外理由": deepcopy(upper["上位除外理由"]),
            "上位方向": upper["上位方向"], "上位EMA現前準備": upper["上位EMA現前準備"],
            "上位EMA差符号": upper["上位EMA差符号"], "上位Impulse方向": upper["上位Impulse方向"], "監視前": before, "動作": actions, "監視後": deepcopy(watch)})
        previous, prior_upper = frame, upper
        if frame["publish"]: public_key = key
    ending = watch is not None
    if ending:
        trace[-1]["動作"].append({"動作": "場末監視取消", "登録ID": watch["登録ID"], "理由": ["場末"]})
        trace[-1]["監視後"] = None
    competing = defaultdict(list)
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                competing[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), same in competing.items():
        if len(same) > 1:
            for row in same: row["戦略判定"][policy].update(採用=False, 理由=["同判断複数信号見送り"], 同時競合=True)
    signals = {"3分_"+policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_"+policy].append({**deepcopy(row), "イベントID": row["発動ID"]+"_"+policy,
                    "入口ID": "3分_"+policy, "戦略": policy, "複合判定": deepcopy(row["戦略判定"][policy])})
    metadata = {row["発動ID"]: {name: deepcopy(row[name]) for name in METADATA_FIELDS} for row in records}
    actions = Counter(action["動作"] for item in trace for action in item["動作"])
    quality = {"場": session, "時間足分": 3, "入力足数": len(rows), "Force逆行cross候補数": len(registrations),
        "監視受理数": sum(row["受理"] for row in registrations), "初回回復数": actions["初回回復固定"],
        "初価格端数": len(records), "初回失敗数": actions["初回失敗固定"],
        "失敗段階別": dict(Counter(action["失敗段階"] for item in trace for action in item["動作"] if action["動作"] == "初回失敗固定")), "価格区分別": dict(Counter(row["価格区分"] for row in records)),
        "判別種別": dict(Counter(row["判別種別"] for row in records)), "監視動作別": dict(actions),
        "場末残監視取消数": int(ending), "終了時監視残数": 0,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {sid: len(values) for sid, values in signals.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in records for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    return {"場": session, "frames": {3: rows, 15: upper_rows}, "signals": signals, "raw": records, "decisions": records,
        "registrations": registrations, "monitor_trace": trace, "metadata": metadata, "quality": quality}
