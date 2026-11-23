"""外部00170の保存済み62入口だけを125/250の観測先着へ移す。

結果閲覧前の固定規則:
 Aは保存新規の価格・価格時計・物理原行を維持し、その行の返済側BBOから追う。
 同じ時計の後続原行も順番通り使い、元の返済は無視する。新規時計が場内期限
 15:35/翌05:50ちょうど以降なら対象外。Aに残り60分条件は課さない。
 Bはdecision_nsを要求時計とし、要求+1秒以上・要求+30秒以下の最初正常板で
 買Ask/売Bid新規。要求時点で残り60分以上、新規停止15:25/翌05:40未満を要求する。
 両方とも逆行125pt以上より先の順行250pt以上、期限等号を含む。300秒超の
 正常板空白が先なら観測不足、期限前EOFも観測不足。確定後の逆行は参照しない。
 全62入口を各モデル1行ずつ保存する。主率の分母は全評価対象約定で、期限未達・
 観測不足を含む。対象外・B未約定を別掲し、全保存入口を分母にした率も併記する。
 これは保存入口の再採点であり、元手法の継続・再参加を再実行した戦略成績でも
 元100/50成績の再現でもない。新1場のcache・特徴・ラベル・損益は読み込まない。
"""

from __future__ import annotations

from collections import Counter
import copy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/外部研究"
STUDY = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
COMMIT = "cf0717daa1eed78759f78a428bce50129e7f705b"
JST = timezone(timedelta(hours=9))
MODELS = ("A_保存新規維持", "B_共通1秒待機")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "対象外")
NUMBERS = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
           "判定気配", "最大順行pt", "最大逆行pt", "所要分")


def sha(path: Path) -> str:
    """小型資料またはcacheのSHA256を求める。

    引数: path (Path) は対象。原板本文には使わない。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    """UTF-8のJSONを読む。

    引数: path (Path) は対象。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON値。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def session_times(session: str) -> tuple[float, float, float, float]:
    """既定の場内時刻を求める。

    引数: session (str) は開始日基準の場名。
    返り値: tuple[float,float,float,float] は開始・ザラバ終了・新規停止・期限の秒。
    """
    day, part = session.split("_")
    date = datetime.fromisoformat(day).replace(tzinfo=JST)
    if part == "Day":
        dates = (date.replace(hour=8, minute=45), date.replace(hour=15, minute=40),
                 date.replace(hour=15, minute=25), date.replace(hour=15, minute=35))
    elif part == "Night":
        following = date + timedelta(days=1)
        dates = (date.replace(hour=17), following.replace(hour=5, minute=55),
                 following.replace(hour=5, minute=40), following.replace(hour=5, minute=50))
    else:
        raise ValueError("未対応の場名")
    return tuple(item.timestamp() for item in dates)


def blank(label: str, reason: str) -> dict[str, Any]:
    """未評価または未約定の結果を作る。

    引数: label/reason (str) は区分と理由。
    返り値: dict[str,Any] は価格列が欠測の結果。
    """
    return {"ラベル": label, "理由": reason, **{key: None for key in NUMBERS}}


# ----------------------------------------
# 区間木や既存label関数を使わず、返済側気配の順列を直接比較する。

def trace(quotes: dict[str, np.ndarray], first: int, price: float, side: int,
          deadline: float) -> dict[str, Any]:
    """新規行から期限・空白・125/250先着までを追う。

    引数: quotes (dict[str,np.ndarray]) は正常板4列、first (int) は開始位置、
    price/deadline (float) は新規価格・期限秒、side (int) は買い1または売り-1。
    返り値: dict[str,Any] は先着と打切りまでの順逆行幅。
    """
    if side not in (1, -1) or first >= len(quotes["now"]) or quotes["now"][first] > deadline:
        raise ValueError("追跡起点が不正")
    now, mark = quotes["now"], quotes["bid"] if side == 1 else quotes["ask"]
    end = int(np.searchsorted(now, deadline, side="right"))
    distances = side * (mark[first:end] - price)
    hits = np.flatnonzero((distances <= -125) | (distances >= 250))
    hit = first + int(hits[0]) if len(hits) else None
    gaps = np.flatnonzero((np.diff(now[first:]) > 300) & (now[first:-1] + 300 < deadline))
    gap_left = first + int(gaps[0]) if len(gaps) else None
    if hit is not None and (gap_left is None or hit <= gap_left):
        last = hit
        label = "順行先着" if side * (mark[last] - price) >= 250 else "逆行先着"
        reason = "返済気配の閾値初着"
    else:
        last = gap_left if gap_left is not None else end - 1
        if gap_left is not None or deadline - now[last] > 300:
            label, reason = "観測不足", "正常板価格時計300秒超空白"
        elif now[-1] < deadline:
            label, reason = "観測不足", "入力末尾不足"
        else:
            label, reason = "期限未達", "期限内どちらも未到達"
    observed = side * (mark[first:last + 1] - price)
    return {"ラベル": label, "理由": reason, "新規価格": float(price),
            "新規時計秒": float(now[first]), "新規原板行": int(quotes["line"][first]),
            "判定時計秒": float(now[last]), "判定原板行": int(quotes["line"][last]),
            "判定気配": float(mark[last]), "最大順行pt": float(max(0, np.max(observed))),
            "最大逆行pt": float(max(0, -np.min(observed))),
            "所要分": float((now[last] - now[first]) / 60)}


def common_entry(quotes: dict[str, np.ndarray], signal: float, cutoff: float,
                 deadline: float, side: int, begin: float = -math.inf) -> dict[str, Any]:
    """Bの要求時刻条件と新規待機・失効を適用する。

    引数: quotes (dict[str,np.ndarray]) は正常板、signal/cutoff/deadline/begin (float)
    は要求・新規停止・期限・場開始秒、side (int) は方向。
    返り値: dict[str,Any] は対象外・未約定または先着結果。
    """
    if signal < begin or signal >= cutoff:
        return blank("対象外", "要求時計が場内新規受付時刻外")
    if deadline - signal < 3600:
        return blank("対象外", "要求時点の残り時間60分未満")
    first = int(np.searchsorted(quotes["now"], signal + 1, side="left"))
    if first >= len(quotes["now"]) or quotes["now"][first] > signal + 30 or quotes["now"][first] >= cutoff:
        return blank("未約定", "30秒以内かつ新規停止未満に正常板なし")
    price = float(quotes["ask"][first] if side == 1 else quotes["bid"][first])
    return trace(quotes, first, price, side, deadline)


def load_quotes(entry: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """固定cacheの時計を場内・非後退に絞って正常板を抽出する。

    引数: entry (dict[str,Any]) は固定台帳行。
    返り値: tuple[dict,dict] は正常板と原状態。新1場を明示的に拒否する。
    """
    if entry["symbol"] != "NK225" or entry["session"] > "2026-10-29_Day":
        raise ValueError("外部保存入口の旧57場以外は読み込まない")
    path = ROOT / "work/複合検証" / entry["cache_path"]
    if path.stat().st_size != entry["cache_size"] or sha(path) != entry["sha256_cache"]:
        raise ValueError("cache指紋不一致")
    with np.load(path, allow_pickle=False) as archive:
        raw = {key: archive[key] for key in ("now", "line", "bid", "ask", "valid")}
    if len(raw["now"]) != entry["events"] or np.any(np.diff(raw["line"]) <= 0):
        raise ValueError("cache行数・原順不一致")
    begin, end, _, _ = session_times(entry["session"])
    positions = np.flatnonzero(np.isfinite(raw["now"]) & (raw["now"] >= begin) & (raw["now"] <= end))
    times = raw["now"][positions]
    if len(times):
        positions = positions[np.r_[True, times[1:] >= np.maximum.accumulate(times[:-1])]]
    normal = positions[raw["valid"][positions].astype(bool)]
    quotes = {key: raw[key][normal] for key in ("now", "line", "bid", "ask")}
    if not len(normal) or not np.all(quotes["ask"] > quotes["bid"]):
        raise ValueError("正常板なし、または気配矛盾")
    return quotes, raw


def saved_entry(quotes: dict[str, np.ndarray], raw: dict[str, np.ndarray],
                fill: dict[str, Any], deadline: float, begin: float) -> dict[str, Any]:
    """Aの保存原行を同一状態省略区間から復元して追跡する。

    引数: quotes/raw (dict[str,np.ndarray]) は正常板・原状態、fill (dict) は保存新規、
    deadline/begin (float) は期限・場開始秒。
    返り値: dict[str,Any] は対象外または保存新規からの先着結果。
    """
    clock = datetime.fromisoformat(fill["timestamp"]).timestamp()
    if clock < begin or clock >= deadline:
        return blank("対象外", "保存新規時計が場開始未満または場内期限以降")
    line, side = int(fill["source_line"]), 1 if fill["type"] == "LongN" else -1
    index = int(np.searchsorted(raw["line"], line, side="right")) - 1
    if index < 0 or not raw["valid"][index] or raw["now"][index] != clock:
        raise ValueError("保存新規の原行状態が正常cacheと不一致")
    expected = raw["ask"][index] if side == 1 else raw["bid"][index]
    if fill["price"] != expected:
        raise ValueError("保存新規価格が方向別BBOと不一致")
    previous = np.flatnonzero(quotes["line"] <= line)
    if len(previous) and quotes["now"][previous[-1]] > clock:
        raise ValueError("保存新規が後退時計で共通正常列に採用できない")
    following = quotes["line"] > line
    anchored = {key: np.concatenate((np.asarray([line if key == "line" else raw[key][index]]), quotes[key][following]))
                for key in ("now", "line", "bid", "ask")}
    return trace(anchored, 0, float(fill["price"]), side, deadline)


# ----------------------------------------
# 合成境界確認と、全保存入口を保持する集計・出典の正式保存。

def self_test() -> dict[str, Any]:
    """125/250等号・同時計原順・期限・空白・B待機の境界を確認する。

    引数: なし。合成データのみ使用する。
    返り値: dict[str,Any] は通過件数と検査名。実データは読まない。
    """
    passed = []

    def quote(values: list[tuple[float, float, float]]) -> dict[str, np.ndarray]:
        """合成の時計・Bid・Askへ原行を付ける。

        引数: values (list[tuple[float,float,float]]) は正常気配。
        返り値: dict[str,np.ndarray] は4列。
        """
        return {"now": np.array([v[0] for v in values]), "line": np.arange(1, len(values) + 1),
                "bid": np.array([v[1] for v in values]), "ask": np.array([v[2] for v in values])}

    cases = [
        ("買い125等号", [(1, 995, 1000), (2, 875, 880), (3, 1250, 1255)], 1, "逆行先着", 2),
        ("買い250等号確定後の逆行無視", [(1, 995, 1000), (2, 1250, 1255), (3, 800, 805)], 1, "順行先着", 2),
        ("売り125等号", [(1, 1000, 1005), (2, 1120, 1125), (3, 745, 750)], -1, "逆行先着", 2),
        ("売り250等号", [(1, 1000, 1005), (2, 745, 750), (3, 1200, 1205)], -1, "順行先着", 2),
        ("同時計の物理原順", [(1, 995, 1000), (1, 875, 880), (1, 1250, 1255)], 1, "逆行先着", 1),
        ("起点スプレッド125", [(1, 875, 1000), (2, 1250, 1255)], 1, "逆行先着", 1),
    ]
    for name, values, side, label, at in cases:
        q = quote(values)
        result = trace(q, 0, 1000, side, 10)
        assert result["ラベル"] == label and result["判定時計秒"] == at, (name, result)
        passed.append(name)
    for name, values, deadline, expected in (
        ("期限等号到達", [(1, 995, 1000), (10, 1250, 1255), (11, 800, 805)], 10, "順行先着"),
        ("300秒超空白が先", [(1, 995, 1000), (302, 1250, 1255), (500, 800, 805)], 500, "観測不足"),
        ("300秒ちょうど継続", [(1, 995, 1000), (301, 1250, 1255), (500, 800, 805)], 500, "順行先着"),
        ("期限前EOF", [(1, 995, 1000), (2, 1000, 1005)], 10, "観測不足"),
        ("期限未達", [(1, 995, 1000), (10, 1000, 1005)], 10, "期限未達"),
    ):
        result = trace(quote(values), 0, 1000, 1, deadline)
        assert result["ラベル"] == expected, (name, result)
        passed.append(name)
    for name, values, signal, cutoff, deadline, expected in (
        ("B同時計禁止と1秒等号", [(0, 995, 1000), (1, 1000, 1005), (2, 1255, 1260)], 0, 100, 4000, "順行先着"),
        ("B30秒等号", [(30, 995, 1000), (31, 1250, 1255)], 0, 100, 4000, "順行先着"),
        ("B30秒超失効", [(31, 995, 1000)], 0, 100, 4000, "未約定"),
        ("B新規停止等号不可", [(30, 995, 1000)], 0, 30, 4000, "未約定"),
        ("B残60分等号許可", [(1, 995, 1000), (2, 1250, 1255)], 0, 100, 3600, "順行先着"),
        ("B残60分未満除外", [(1, 995, 1000)], 0, 100, 3599, "対象外"),
    ):
        result = common_entry(quote(values), signal, cutoff, deadline, 1)
        assert result["ラベル"] == expected, (name, result)
        passed.append(name)
    q = quote([(1, 995, 1000), (2, 1250, 1255), (10, 800, 805)])
    raw = {**q, "valid": np.ones(3, dtype=bool)}
    fill = {"timestamp": datetime.fromtimestamp(1, JST).isoformat(), "source_line": 1, "type": "LongN", "price": 1000}
    assert saved_entry(q, raw, fill, 1, 0)["ラベル"] == "対象外"
    passed.append("A期限等号新規は除外")
    raw["line"] = np.array([1, 4, 5])
    q["line"] = raw["line"]
    fill["source_line"] = 2
    result = saved_entry(q, raw, fill, 10, 0)
    assert result["新規原板行"] == 2 and result["判定原板行"] == 4 and result["ラベル"] == "順行先着"
    passed.append("A完全同一省略区間の物理原行復元")
    return {"通過": len(passed), "不一致": 0, "検査": passed}


def summarize(rows: list[dict[str, Any]], model: str, period: str) -> dict[str, Any]:
    """全対象約定を分母にしたモデル別・期間別集計を作る。

    引数: rows (list[dict]) は全事例、model/period (str) は対象。
    返り値: dict[str,Any] はラベル件数・率・除外理由。
    """
    part = [row for row in rows if row["モデル"] == model and (period == "外部57場全体" or row["期間"] == period)]
    counts = Counter(row["ラベル"] for row in part)
    filled = [row for row in part if row["ラベル"] not in ("対象外", "未約定")]
    return {"モデル": model, "期間": period, "保存入口数": len(part), **{k: counts[k] for k in LABELS},
            "約定入口数": len(filled), "順行先着率_全約定": counts["順行先着"] / len(filled) if filled else None,
            "順行先着率_保存入口": counts["順行先着"] / len(part) if part else None,
            "約定場数": len({row["場"] for row in filled}),
            "約定開始日数": len({row["場"][:10] for row in filled}),
            "対象外理由": dict(Counter(row["理由"] for row in part if row["ラベル"] == "対象外")),
            "未約定理由": dict(Counter(row["理由"] for row in part if row["ラベル"] == "未約定"))}


def copy_evidence() -> dict[str, Any]:
    """部分取得済み資料と入力監査を正式試行へ小型のまま残す。

    引数: なし。workの取得envelopeだけを複製する。
    返り値: dict[str,Any] は正式資料の相対パス・サイズ・SHA。原板は複製しない。
    """
    folder = STUDY / "資料"
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted((WORK / "取得").glob("*.json")) + [WORK / "外部約定取得.json"]:
        target = folder / source.name
        shutil.copyfile(source, target)
        copied.append({"保存": target.relative_to(ROOT).as_posix(), "bytes": target.stat().st_size, "SHA256": sha(target)})
    audit = copy.deepcopy(read(WORK / "入力監査.json"))
    audit["作業版監査"] = {"参照": "work/外部研究/入力監査.json", "SHA256": sha(WORK / "入力監査.json")}
    for item in audit["外部小型証拠"]:
        item["保存"] = (folder / Path(item["保存"]).name).relative_to(ROOT).as_posix()
    audit["00170外部約定の原行照合"]["出所"] = (folder / "外部約定取得.json").relative_to(ROOT).as_posix()
    audit["正式保存資料"] = copied
    write(STUDY / "入力監査.json", audit)
    return {"保存資料": copied, "資料合計bytes": sum(v["bytes"] for v in copied),
            "入力監査": {"保存": "入力監査.json", "SHA256": sha(STUDY / "入力監査.json")}}


def run() -> dict[str, Any]:
    """旧57場の保存62入口を二つの固定モデルで再採点して保存する。

    引数: なし。固定外部約定・00008台帳・旧cacheだけを読む。
    返り値: dict[str,Any] は規則・集計・出典・合成検査。新1結果は生成しない。
    """
    tests = self_test()
    evidence = copy_evidence()
    listing = read(STUDY / "入力台帳.json")
    inputs = {(v["symbol"], v["session"]): v for v in listing["entries"]}
    source_path = STUDY / "資料/外部約定取得.json"
    source = read(source_path)
    if source["commit"] != COMMIT:
        raise ValueError("外部約定commit不一致")
    downloads = {v["path"]: v for v in source["downloads"]}
    results, fingerprints, originals = [], [], 0
    for item in sorted(source["files"], key=lambda v: v["path"]):
        body = downloads[item["path"]]["content"].encode("utf-8") if item["size"] else b""
        digest = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if len(body) != item["size"] or digest != item["sha"]:
            raise ValueError("外部約定Git blob指紋不一致")
        session = re.fullmatch(r"NK225_(\d{4}-\d{2}-\d{2}_(?:Day|Night))_.+\.trades\.jsonl", item["path"]).group(1)
        fills = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        opens = [fill for fill in fills if fill["type"] in ("LongN", "ShortN")]
        if not opens:
            continue
        entry = inputs[("NK225", session)]
        quotes, raw = load_quotes(entry)
        begin, _, cutoff, deadline = session_times(session)
        fingerprints.append({"場": session, "cache": entry["cache_path"], "SHA256": entry["sha256_cache"]})
        for fill in opens:
            originals += 1
            side = 1 if fill["type"] == "LongN" else -1
            signal = fill["decision_ns"] / 1e9
            original = {"外部入口ID": fill["id"], "外部建玉ID": fill["position_id"], "外部手法ID": fill["method_id"],
                        "場": session, "期間": "学習40場" if session[:10] < "2026-10-19" else "条件選択17場",
                        "方向": "買い" if side == 1 else "売り", "保存新規価格": fill["price"],
                        "保存新規時計秒": datetime.fromisoformat(fill["timestamp"]).timestamp(),
                        "保存新規原板行": fill["source_line"], "要求時計秒": signal,
                        "要求原板行": fill["decision_line"], "新規停止時計秒": cutoff, "期限時計秒": deadline,
                        "残り分_要求時": (deadline - signal) / 60,
                        "外部約定ファイル": item["path"], "外部約定Git_blob_SHA": item["sha"]}
            for model in MODELS:
                label = saved_entry(quotes, raw, fill, deadline, begin) if model == MODELS[0] else common_entry(quotes, signal, cutoff, deadline, side, begin)
                results.append({"モデル": model, **original, **label})
    if originals != 62 or len(results) != 124:
        raise ValueError("外部保存62入口を欠落または追加している")
    csv_path = STUDY / "外部入口事例.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    report = {"版": 1, "固定commit": COMMIT, "対象": "外部00170のNK選定済みI約定ファイル57件・保存新規62入口",
              "入力証跡": {"入力台帳": "入力台帳.json", "入力台帳SHA256": sha(STUDY / "入力台帳.json"),
                           "外部約定": "資料/外部約定取得.json", "外部約定SHA256": sha(source_path),
                           "再採点コード": Path(__file__).relative_to(ROOT).as_posix(), "コードSHA256": sha(Path(__file__)),
                           "事例CSV": "外部入口事例.csv", "事例CSVSHA256": sha(csv_path), "利用cache": fingerprints},
              "規則": {"逆行pt": 125, "順行pt": 250, "正常板空白許容秒": 300, "期限": "15:35/翌05:50・等号含む",
                       "A": "保存価格・時計・物理原行を維持し同原行の返済BBOから追う。期限ちょうど以降新規は対象外。残60分条件なし。",
                       "B": "decision_ns要求、+1秒以上・30秒以下の最初正常板、買Ask/売Bid。要求は15:25/翌05:40未満かつ残60分以上。",
                       "元返済": "両モデルで無視。新規後125/250・期限・空白だけで観測先着を付ける。",
                       "原順": "同価格時計の状態変化は維持。省略された完全同一状態の保存原行は直前保持状態で復元。",
                       "率の分母": "全評価対象約定。期限未達・観測不足を含む。対象外・未約定を別掲。保存62入口率も併記。",
                       "判定時計": "順行/逆行先着は到達時計、それ以外は最後に採用した正常板時計。期限時計とは別。"},
              "集計": [summarize(results, model, period) for model in MODELS for period in ("外部57場全体", "学習40場", "条件選択17場")],
              "合成検査": tests, "正式資料": evidence,
              "限界": ["保存された外部入口の2通りの再採点。原手法の継続・再参加を再実行した戦略成績ではない。",
                       "元100/50成績、mini10枚・費用0の損益とは混ぜない。ここではROI・運用損益を算出していない。",
                       "外部57場はローカル既使用入力と同一であり、独立な後続標本ではない。",
                       "11/4Day新1場は入力品質だけで、価格・特徴・ラベル・損益をこの処理へ読み込んでいない。"]}
    write(STUDY / "外部入口再採点.json", report)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({"合成通過": result["合成検査"]["通過"], "集計": result["集計"]}, ensure_ascii=False))
