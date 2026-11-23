"""00015のRSI価格極値を、独立指標と区間内の全極値列挙から再構成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00015_RSIの山谷と価格構造"
WORK = ROOT / "work/RSI構造/00015"
MANIFEST = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
HELPER = ROOT / "scripts/収縮反転/状態独立確認.py"


def independent_helper() -> Any:
    """過去に別計算した価格足・EMA・Wilderの補助だけを読む。

    引数: なし。
    返り値: Any は独立補助。今回の入口/driverや元の指標classは読み込まない。
    """
    spec = importlib.util.spec_from_file_location("RSI構造の独立価格補助", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


S = independent_helper()


class Indicators(S.Indicators):
    """独立OHLC/EMA/ATRへ、14差分から初期化する独立RSIを加える。"""

    def __init__(self) -> None:
        """同じ尺度の指標を未準備にする。

        引数: なし。
        返り値: None。親の独立足が欠枠・尾部欠枠で呼ぶresetにも対応する。
        """
        super().__init__()
        self.gain, self.loss = S.G.Wilder(), S.G.Wilder()
        self.previous_close = None

    def add(self, bar: dict) -> dict:
        """正負終値差をWilder平均し、現足RSIを計算する。

        引数: bar (dict) は独立の確定OHLC。
        返り値: dict は独立足/EMA/ATR/BBとRSI。上下差とも0ならRSIはNone。
        """
        result, rsi = super().add(bar), None
        if self.previous_close is not None:
            difference = bar["close"] - self.previous_close
            gain = self.gain.add(max(difference, 0.0))
            loss = self.loss.add(max(-difference, 0.0))
            if gain is not None and loss is not None and gain + loss > 0:
                rsi = 100 * gain / (gain + loss)
        self.previous_close = bar["close"]
        return {**result, "rsi": rsi}


def compressed_rows(path: Path) -> tuple[list[dict], str]:
    """全保存行と展開内容SHAを読む。

    引数: path (Path) はUTF-8 JSONLのgzip。
    返り値: tuple[list[dict],str] は行と展開SHA256。
    """
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for line in stream:
            digest.update(line)
            if line.strip():
                rows.append(json.loads(line))
    return rows, digest.hexdigest()


# ----------------------------------------
# オンラインの前極値状態を使わず、公開連続区間の全中心を先に列挙する。

def segments(frames: list[dict]) -> list[list[dict]]:
    """公開・連続番号の価格足を区間へ分ける。

    引数: frames (list[dict]) は一場一尺度の独立足。
    返り値: list[list[dict]] は欠枠/非公開をまたがない区間。
    """
    result, current = [], []
    for frame in frames:
        if not frame["publish"]:
            if current:
                result.append(current)
                current = []
            continue
        if current and (frame["missing"] or frame["index"] != current[-1]["index"] + 1):
            result.append(current)
            current = []
        current.append(frame)
    if current:
        result.append(current)
    return result


def upper_context(current: dict, higher: list[dict]) -> dict:
    """判断キーと足終了の双方を満たす最後の15分足を選ぶ。

    引数: current (dict) は判断足、higher (list[dict]) は独立15分足。
    返り値: dict は上位準備・方向・利用可能キー。
    """
    available = [u for u in higher if u["end"] <= current["end"] and
                 (u["confirm"], u["confirm_line"]) <= (current["confirm"], current["confirm_line"])]
    upper = available[-1] if available else None
    ready = bool(upper and upper["publish"] and S.finite(upper["close"], upper["ema20"], upper["ema20_previous"]))
    direction = 0
    if ready:
        direction = 1 if upper["close"] > upper["ema20"] > upper["ema20_previous"] else (
            -1 if upper["close"] < upper["ema20"] < upper["ema20_previous"] else 0)
    return {"上位準備済": ready, "上位方向": direction, "上位確認秒": upper["confirm"] if upper else None,
            "上位確認行": upper["confirm_line"] if upper else None, "上位足終了秒": upper["end"] if upper else None,
            "上位足番号": upper["index"] if upper else None}


def listed_pairs(frames: list[dict], higher: list[dict], session: str) -> list[dict]:
    """全価格極値列を作り、各方向の隣接する二要素だけを比較する。

    引数: frames/higher (list[dict]) は独立の下位/15分足、session (str) は場。
    返り値: list[dict] は非採用を含む全極値と、隣接組・中心除外ネック・判断時点の独立情報。
    """
    _, _, cutoff, deadline = S.G.times(session)
    output = []
    for interval in segments(frames):
        for side in (1, -1):
            field = "low" if side == 1 else "high"
            extrema = [i for i in range(2, len(interval) - 2)
                       if all(side * (interval[i][field] - interval[j][field]) < 0 for j in (i - 2, i - 1))
                       and all(side * (interval[i][field] - interval[j][field]) <= 0 for j in (i + 1, i + 2))]
            # 隣接列なので、RSI未準備・本数不適合・発動不可の極値も次の組へ必ず参加する。
            for order, at in enumerate(extrema):
                previous_at = extrema[order - 1] if order else None
                center, decision = interval[at], interval[at + 2]
                previous = interval[previous_at] if previous_at is not None else None
                between = interval[previous_at + 1:at] if previous_at is not None else []
                high = max((r["high"] for r in between), default=None)
                low = min((r["low"] for r in between), default=None)
                neck = high if side == 1 else low
                neck_ok = bool(neck is not None and side * (decision["close"] - neck) > 0)
                distance = center["index"] - previous["index"] if previous is not None else None
                upper = upper_context(decision, higher)
                center_ready = bool(previous is not None and S.finite(previous["rsi"], center["rsi"]))
                pattern = None
                if center_ready:
                    price_difference = side * (center[field] - previous[field])
                    rsi_difference = side * (center["rsi"] - previous["rsi"])
                    if price_difference < 0 and rsi_difference > 0:
                        pattern = "反転乖離"
                    elif price_difference > 0 and rsi_difference < 0:
                        pattern = "押し戻り継続"
                # 型や本数を満たさなくても、全価格極値をこの列へ残す。
                reasons = []
                if previous is None:
                    reasons.append("前極値なし")
                elif not 3 <= distance <= 20:
                    reasons.append("中心間隔範囲外")
                if not center_ready:
                    reasons.append("中心RSI未準備")
                if pattern is None:
                    reasons.append("価格RSI型不成立")
                if not S.finite(decision["atr"], decision["rsi"]) or decision["atr"] <= 0:
                    reasons.append("判断RSI_ATR未準備")
                if not upper["上位準備済"]:
                    reasons.append("上位未準備")
                if decision["confirm"] >= cutoff or deadline - decision["confirm"] < 3600:
                    reasons.append("時間条件不成立")
                if side * (decision["close"] - interval[at + 1]["close"]) <= 0:
                    reasons.append("終値改善不成立")
                if pattern == "押し戻り継続" and upper["上位方向"] != side:
                    reasons.append("継続上位方向不一致")
                emitted = []
                if not reasons:
                    emitted.append(f'{decision["minutes"]}分_{pattern}_なし')
                    if neck_ok:
                        emitted.append(f'{decision["minutes"]}分_{pattern}_ネック位置確認')
                output.append({"side": side, "中心足": center, "前中心足": previous,
                    "判断足": decision, "前判断足": interval[at + 1], "前中心の判断足": interval[previous_at + 2] if previous_at is not None else None,
                    "間隔": distance, "間高値": high, "間安値": low, "ネック": neck, "ネック成立": neck_ok,
                    "型": pattern, "独立理由": reasons, "発動": emitted, **upper})
    return sorted(output, key=lambda r: (r["判断足"]["confirm"], r["判断足"]["confirm_line"], -r["side"]))


def pivot_descriptor(center: dict | None, judgment: dict | None, side: int) -> dict | None:
    """独立に求めた中心と確認足を保存schemaへ変換する。

    引数: center/judgment (dict|None) は中心足/その二本後の足、side (int) は安値1/高値−1。
    返り値: dict|None は両公開時点を分離した不変の極値記録。
    """
    if center is None:
        return None
    return {"中心番号": center["index"], "中心足開始秒": center["start"], "中心足終了秒": center["end"],
            "中心足公開時計秒": center["confirm"], "中心足公開原行": center["confirm_line"],
            "中心高値": center["high"], "中心安値": center["low"], "中心終値": center["close"],
            "中心RSI14": center["rsi"] if S.finite(center["rsi"]) else None,
            "極値価格": center["low"] if side == 1 else center["high"],
            "極値確認足index": judgment["index"], "極値確認足終了秒": judgment["end"],
            "極値確認時計秒": judgment["confirm"], "極値確認原行": judgment["confirm_line"]}


def canonical(pair: dict, session: str, period: str) -> tuple[dict, dict[str, dict]]:
    """独立の全極値・組情報を保存レコードと発動signalへ写像する。

    引数: pair (dict) は独立列挙行、session/period (str) は場と固定期間。
    返り値: tuple[dict,dict[str,dict]] は全極値一行とイベントID別の発動。元の型判定は呼ばない。
    """
    _, _, cutoff, deadline = S.G.times(session)
    current, previous, row, side = pair["中心足"], pair["前中心足"], pair["判断足"], pair["side"]
    now_pivot = pivot_descriptor(current, row, side)
    old_pivot = pivot_descriptor(previous, pair["前中心の判断足"], side)
    reasons = pair["独立理由"]
    upper = {k: pair[k] for k in ("上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒", "上位足番号")}
    indicators = S.finite(row["rsi"], row["atr"]) and row["atr"] > 0
    common = bool(indicators and upper["上位準備済"])
    time_ok = row["confirm"] < cutoff and deadline - row["confirm"] >= 3600
    by_extra = {extra: reasons + (["ネック位置不成立"] if extra != "なし" and not pair["ネック成立"] else [])
                for extra in ("なし", "ネック位置確認")}
    record = {"場": session, "期間": period, "時間足分": row["minutes"], "side": side,
        "極値種別": "安値" if side == 1 else "高値", "現極値": now_pivot, "前極値": old_pivot,
        "極値間隔本数": pair["間隔"], "極値間高値": pair["間高値"], "極値間安値": pair["間安値"],
        "ネック価格": pair["ネック"], "ネック条件成立": pair["ネック成立"], "価格RSI型": pair["型"],
        "判断足番号": row["index"], "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"],
        "判断終値": row["close"], "直前終値": pair["前判断足"]["close"], "判断RSI14": row["rsi"], "判断ATR14": row["atr"],
        **upper, "中心間隔適合": pair["間隔"] is not None and 3 <= pair["間隔"] <= 20,
        "中心RSI準備済": bool(previous is not None and S.finite(previous["rsi"], current["rsi"])),
        "共通準備済": common, "時間条件成立": time_ok,
        "終値改善": side * (row["close"] - pair["前判断足"]["close"]) > 0,
        "除外理由": list(reasons), "追加確認別除外理由": by_extra, "発動入口ID": list(pair["発動"])}
    events = {}
    for source in pair["発動"]:
        extra = "ネック位置確認" if source.endswith("_ネック位置確認") else "なし"
        identity = f'NK225_{session}_{source}_{row["index"]:04d}_{side}'
        family = pair["型"]
        signal = {**row, **upper, **{k: record[k] for k in
            ("現極値", "前極値", "極値間隔本数", "極値間高値", "極値間安値", "ネック価格", "ネック条件成立")},
            "場": session, "期間": period, "時間足分": row["minutes"], "入口ID": source,
            "入口系統": family, "補助": extra, "追加確認": extra, "役割": "反転" if family == "反転乖離" else "順行",
            "side": side, "方向": "買い" if side == 1 else "売り", "イベントID": identity,
            "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"],
            "確認遅延秒": row["confirm"] - row["end"], "期限時計秒": deadline, "足終了時計秒": row["end"],
            "残り分_判断時": (deadline - row["confirm"]) / 60,
            "入口中心まで方向距離pt": side * (row["bb_mean"] - row["close"]) if S.finite(row["bb_mean"]) else None,
            "250ptのATR倍": 250 / row["atr"]}
        events[identity] = signal
    return record, events


def quality(frames: list[dict], records: list[dict], events: dict[str, dict]) -> dict:
    """全独立価格極値と発動から、保存品質の共通件数を計算する。

    引数: frames (list[dict]) は独立足、records (list[dict]) は全極値、events (dict[str,dict]) は発動。
    返り値: dict は準備・隣接組・不採用理由・全四入口件数。
    """
    minutes = frames[0]["minutes"] if frames else None
    counter = Counter({"公開足": sum(r["publish"] for r in frames),
        "極値五足窓不足": sum(min(4, len(part)) for part in segments(frames)),
        "非公開リセット": sum(not r["publish"] for r in frames)})
    previous_index = None
    for frame in frames:
        if frame["publish"] and (frame["missing"] or previous_index is not None and frame["index"] != previous_index + 1):
            counter["連続窓リセット"] += 1
        previous_index = frame["index"]
    for row in records:
        for key, active in (
            ("確定安値数" if row["side"] == 1 else "確定高値数", True),
            ("隣接対数", row["前極値"] is not None), ("距離適合対数", row["中心間隔適合"]),
            ("中心RSI準備対数", row["中心RSI準備済"]), ("価格RSI型適合対数", row["価格RSI型"] is not None),
            ("共通準備可極値数", row["共通準備済"]),
            ("共通時間条件可極値数", row["共通準備済"] and row["時間条件成立"])):
            counter[key] += int(active)
    counter["確認遅延超過発動"] = sum(r["確認遅延秒"] > 30 for r in events.values())
    return {**dict(counter), "極値除外理由": dict(Counter(reason for row in records for reason in row["除外理由"])),
            "系統別発動数": {f"{minutes}分_{family}_{extra}": sum(r["入口ID"] == f"{minutes}分_{family}_{extra}" for r in events.values())
                for family in ("反転乖離", "押し戻り継続") for extra in ("なし", "ネック位置確認")}}


def write_output(path: Path, output: dict) -> None:
    """監査結果だけをUTF-8 JSONとして保存する。

    引数: path (Path) は出力先、output (dict) は監査結果。
    返り値: None。原板や旧結果は変更しない。
    """
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


# ----------------------------------------
# 保存全極値・全発動の集合を照合し、元の入口が正しいという前提を置かない。

def compare_keys(audit: Any, name: str, actual: set, expected: set) -> None:
    """集合の不足と余分を小さい差分記録で比較する。

    引数: audit (Any) は比較先、name (str) は項目、actual/expected (set) は集合。
    返り値: None。大きな全キー一覧を結果へ複製しない。
    """
    for label, difference in (("不足", expected - actual), ("余分", actual - expected)):
        audit.check(name + ":" + label + "数", len(difference), 0)
        if difference and audit.errors:
            audit.errors[-1]["差分の先頭例"] = sorted(difference)[:20]


def run(study: Path, work: Path) -> dict:
    """正式再生後の全65場を別計算し、全極値・不採用理由・12発動を照合する。

    引数: study/work (Path) は00015正式試行/作業先。
    返り値: dict は明示合否・範囲・指紋。先着ラベル・運用会計は親の別監査へ分ける。
    """
    for name in ("結果.json", "固定.json", "入口品質.json"):
        if not (study / name).exists():
            raise ValueError("正式再生の完了資料がないため実行しません")
    audit = S.Audit()
    manifest, config = S.read(MANIFEST), S.read(study / "条件.json")
    entries = manifest["entries"]
    saved_pivots, pivots_sha = compressed_rows(work / "全pivot.jsonl.gz")
    cases, cases_sha = compressed_rows(work / "入口事例.jsonl.gz")
    pivots = {(r["場"], r["時間足分"], r["side"], r["現極値"]["中心番号"]): r for r in saved_pivots}
    saved_events = {r["イベントID"]: r for r in cases}
    audit.check("保存pivotキー一意", len(pivots), len(saved_pivots))
    audit.check("保存イベントID一意", len(saved_events), len(cases))
    saved_quality = {(r["場"], r["時間足分"]): r for r in S.read(study / "入口品質.json")}
    banks, contract = {n: Indicators() for n in (1, 3, 5, 15)}, None
    all_pivots, all_events, frame_count, period_count = {}, {}, Counter(), Counter()
    for entry in entries:
        session, codes = entry["session"], tuple(entry["in_session_contract_codes"])
        if len(codes) != 1:
            raise ValueError("限月が一意でない")
        if contract is not None and codes != contract:
            banks = {n: Indicators() for n in banks}
        contract = codes
        period = "後続検査" if session[:10] >= config["分割"]["後続開始日"] else (
            "条件選択" if session[:10] >= config["分割"]["選択開始日"] else "学習")
        period_count[period] += 1
        data = S.observed(entry)
        formed = {n: S.bars(data, session, n, bank) for n, bank in banks.items()}
        for minutes in (1, 3, 5):
            pair_list, records, events = listed_pairs(formed[minutes], formed[15], session), [], {}
            for pair in pair_list:
                record, signals = canonical(pair, session, period)
                records.append(record)
                all_pivots[session, minutes, pair["side"], pair["中心足"]["index"]] = record
                events.update(signals)
            all_events.update(events)
            own_quality = quality(formed[minutes], records, events)
            actual = saved_quality.get((session, minutes), {})
            for field, expected in own_quality.items():
                audit.check(f"{session}:{minutes}分:極値品質:{field}", actual.get(field, 0), expected)
            frame_count[str(minutes)] += len(formed[minutes])
        frame_count["15"] += len(formed[15])
        print(json.dumps({"場": session, "独立確認": "1/3/5/15原価格・RSI・全極値", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全65入力", len(entries), 65)
    audit.check("固定分割40/24/1", dict(period_count), {"学習": 40, "条件選択": 24, "後続検査": 1})
    compare_keys(audit, "全pivot集合", set(pivots), set(all_pivots))
    for key in pivots.keys() & all_pivots.keys():
        audit.check(f"極値{key}", pivots[key], all_pivots[key])
    compare_keys(audit, "全12入口発動集合", set(saved_events), set(all_events))
    event_fields = ("index", "start", "end", "minutes", "open", "high", "low", "close", "missing", "publish",
        "confirm", "confirm_line", "ema20", "ema20_previous", "atr", "rsi", "adx", "bb_mean", "bb_sd", "plus_di", "minus_di",
        "上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒", "上位足番号",
        "現極値", "前極値", "極値間隔本数", "極値間高値", "極値間安値", "ネック価格", "ネック条件成立",
        "場", "期間", "時間足分", "入口ID", "入口系統", "補助", "追加確認", "役割", "side", "方向",
        "要求時計秒", "要求原板行", "確認遅延秒", "期限時計秒", "足終了時計秒", "残り分_判断時", "入口中心まで方向距離pt", "250ptのATR倍")
    for identity in saved_events.keys() & all_events.keys():
        for field in event_fields:
            audit.check(identity + ":" + field, saved_events[identity][field], all_events[identity][field])
    output = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "入力場数": len(entries), "期間場数": dict(period_count), "独立足数": dict(frame_count),
        "保存pivot数": len(saved_pivots), "独立pivot数": len(all_pivots), "保存入口数": len(cases), "独立入口数": len(all_events),
        "入口別件数": dict(Counter(r["入口ID"] for r in all_events.values())),
        "全pivot公開時点と不採用理由を確認": True,
        "コードSHA256": S.sha(Path(__file__)), "独立足指標補助SHA256": S.sha(HELPER),
        "独立Wilder補助SHA256": S.sha(S.HELPER), "入力台帳SHA256": S.sha(MANIFEST),
        "全pivot展開SHA256": pivots_sha, "入口事例展開SHA256": cases_sha,
        "検証範囲": "原cacheから1/3/5/15分半開OHLCと最初の確認原行・欠枠・同限月持越しEMA20/ATR14/RSI14を別計算。公開連続区間の左右2中心を先に全列挙し、side別隣接要素だけを組にする別方式で、全極値・前極値更新・中心間隔3〜20・中心RSI・両中心除外の間高安・ネック・二本後判断時点・全不採用理由・上位公開キーと12発動集合を照合。非公開/欠枠では区間を分ける。",
        "限界": "00015の入口/driver/元指標classはimportして再生しない。以前の独立OHLC/指標補助だけを再利用。原板本文の再取得や真の受信時計を証明するものではない。RSIは上下14差分の算術種後Wilder平均、上下とも0は未定義。先着・運用・会計は別監査。"}
    write_output(work / "状態独立確認.json", output)
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "保存pivot数", "保存入口数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return output


def main() -> None:
    """正式再生完了の明示指定後だけ実データ監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。許可指定がなければ実データを開かない。
    """
    parser = argparse.ArgumentParser(description="00015価格RSI極値の独立再構成")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("正式再生完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

