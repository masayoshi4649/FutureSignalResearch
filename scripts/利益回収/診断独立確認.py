"""診断関数を読み込まず、保存集計と少数の価格経路を独立に確認する。"""

from collections import defaultdict
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
STUDY = ROOT / "study/00009_含み益の赤字化と決済時点の診断"
WORK = ROOT / "work/外部研究/探索00008"
JST = timezone(timedelta(hours=9))
checks, errors = 0, []


def check(name, actual, expected):
    """独立値と保存値を照合する。

    引数: name (str) は項目、actual/expected (数値またはNone) は比較値。
    返り値: None。不一致を記録する。
    """
    global checks
    checks += 1
    if actual is not None and expected is not None:
        same = abs(float(actual) - float(expected)) < 1e-8
    else:
        same = actual == expected
    if not same:
        errors.append({"項目": name, "独立": actual, "保存": expected})


def number(value):
    """CSV空欄を欠測、それ以外を数値へ変換する。

    引数: value (str) はCSVセル。
    返り値: float|None は数値または欠測。
    """
    return None if value == "" else float(value)


def clock_bounds(session):
    """合成ではなく暦から独立に場内時刻を作る。

    引数: session (str) は開始日基準の場名。
    返り値: tuple[float,float] は場開始・終了。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("Day"):
        return day.replace(hour=8, minute=45).timestamp(), day.replace(hour=15, minute=40).timestamp()
    return day.replace(hour=17).timestamp(), (day + timedelta(days=1)).replace(hour=5, minute=55).timestamp()


def path_rows(trade, entry):
    """正常な場内・非後退の状態を素朴に順走査する。

    引数: trade (dict) は保存取引、entry (dict) は固定入力台帳。
    返り値: list[dict] は時計・原行・返済気配差の採用列。
    """
    begin, end = clock_bounds(trade["場"])
    side, price = (1 if trade["方向"] == "買い" else -1), trade["新規価格"]
    path = ROOT / "work/複合検証" / entry["cache_path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256_cache"]
    previous, result = -float("inf"), []
    with np.load(path, allow_pickle=False) as a:
        for now, line, bid, ask, valid in zip(a["now"], a["line"], a["bid"], a["ask"], a["valid"]):
            if not np.isfinite(now) or not begin <= now < end or now < previous:
                continue
            previous = now
            if valid:
                result.append({"now": float(now), "line": int(line), "d": side * ((float(bid) if side == 1 else float(ask)) - price)})
    return result


# ----------------------------------------
# 全33候補は保存MFEと最終額だけから閾値件数を独立集計する。

grouped, all_trades = defaultdict(list), {}
for stage in ("探索", "後続"):
    with gzip.open(WORK / (stage + "_運用詳細.jsonl.gz"), "rt", encoding="utf-8") as stream:
        for raw in stream:
            detail = json.loads(raw)
            period = "既使用11月4日" if stage == "後続" else detail["品質"]["期間"]
            grouped[(detail["候補ID"], period)].extend(detail["取引"])
            for trade in detail["取引"]:
                all_trades[trade["手法"] + "/" + trade["場"] + "/" + trade["建玉ID"]] = trade

saved = json.loads((STUDY / "集計.json").read_text(encoding="utf-8"))
for row in saved["手法別期間別"]:
    trades = grouped[(row["手法"], row["期間"])]
    prefix = row["手法"] + "/" + row["期間"]
    check(prefix + ":完結数", len(trades), row["完結取引数"])
    check(prefix + ":実現粗額", sum(t["粗損益円"] for t in trades), row["実現粗損益円"])
    check(prefix + ":実現純額", sum(t["基準純損益円"] for t in trades), row["実現純損益円"])
    for threshold in row["到達後の赤字"]:
        limit = threshold["到達pt"]
        reached = [t for t in trades if t["観測最大順行pt"] >= limit]
        gross_red = sum(t["粗損益円"] < 0 for t in reached)
        net_red = sum(t["基準純損益円"] < 0 for t in reached)
        for key, actual in (("到達取引数", len(reached)), ("最終粗赤字数", gross_red), ("最終純赤字数", net_red),
                            ("最終粗赤字率", gross_red / len(reached) if reached else None),
                            ("最終純赤字率", net_red / len(reached) if reached else None)):
            check(prefix + f":{limit}:" + key, actual, threshold[key])


# ----------------------------------------
# 含み益消失・全区間赤字・大きな返済待機変化の3例を直接確認する。

entries = {entry["session"]: entry for entry in json.loads((SOURCE / "入力台帳.json").read_text(encoding="utf-8"))["entries"]}
with (STUDY / "事例.csv").open(encoding="utf-8-sig", newline="") as stream:
    samples = list(csv.DictReader(stream))
reports = []
for sample_index in (0, 1, 8):
    sample = samples[sample_index]
    trade = all_trades[sample["診断ID"]]
    whole = path_rows(trade, entries[trade["場"]])
    rows = [r for r in whole if trade["新規原板行"] <= r["line"] <= trade["返済原板行"]]
    ds = [r["d"] for r in rows]
    peak = max(ds)
    peak_index = ds.index(peak)
    positive = next((i for i, d in enumerate(ds) if d > 0), None)
    positive_net = next((i for i, d in enumerate(ds) if d * 10 - 22 > 0), None)
    red = next((i for i in range(positive + 1, len(ds)) if ds[i] < 0), None) if positive is not None else None
    red_net = next((i for i in range(positive_net + 1, len(ds)) if ds[i] * 10 - 22 < 0), None) if positive_net is not None else None
    selected = { "観測最大順行pt": max(0, peak), "観測最大逆行pt": max(0, -min(ds)),
                 "最大観測返済差pt": peak, "観測峰時計秒": rows[peak_index]["now"], "観測峰原板行": rows[peak_index]["line"],
                 "観測峰最終時計秒": next(r["now"] for r in reversed(rows) if r["d"] == peak),
                 "初正粗益時計秒": None if positive is None else rows[positive]["now"],
                 "初正純額時計秒": None if positive_net is None else rows[positive_net]["now"],
                 "正粗益後の初粗赤字時計秒": None if red is None else rows[red]["now"],
                 "正純額後の初純赤字時計秒": None if red_net is None else rows[red_net]["now"],
                 "峰までのMAEpt": max(0, -min(ds[:peak_index + 1])),
                 "初正粗益までのMAEpt": None if positive is None else max(0, -min(ds[:positive + 1])),
                 "新規要求から約定秒_再計算": trade["新規時計秒"] - trade["新規要求時計秒"],
                 "返済要求から約定秒_再計算": trade["返済時計秒"] - trade["返済要求時計秒"],
                 "峰から返済秒": trade["返済時計秒"] - rows[peak_index]["now"],
                 "峰から返済の返し幅pt": peak - ds[-1],
                 "MFEから返済の差pt": max(0, peak) - ds[-1],
                 "失った正含み益pt": max(0, peak) - max(0, ds[-1]), "追跡正常板数": len(rows)}
    for limit in (5, 20, 50, 100):
        first_reach = next((i for i, d in enumerate(ds) if d >= limit), None)
        r = next((i for i in range(first_reach + 1, len(ds)) if ds[i] < 0), None) if first_reach is not None else None
        n = next((i for i in range(first_reach + 1, len(ds)) if ds[i] * 10 - 22 < 0), None) if first_reach is not None else None
        selected.update({f"{limit}pt初到達時計秒": None if first_reach is None else rows[first_reach]["now"],
                         f"{limit}pt後の初粗赤字時計秒": None if r is None else rows[r]["now"],
                         f"{limit}pt後の初純赤字時計秒": None if n is None else rows[n]["now"]})
    request = next(r for r in whole if r["line"] == trade["返済要求原板行"])
    selected["返済要求参照の返済差pt"] = request["d"]
    selected["返済要求参照板の古さ秒"] = trade["返済要求時計秒"] - request["now"]
    selected["返済要求参照から約定の差pt"] = ds[-1] - request["d"]
    for key, actual in selected.items():
        check(sample["診断ID"] + ":" + key, actual, number(sample[key]))
    reports.append({"診断ID": sample["診断ID"], "直接確認項目数": len(selected),
                    "同価格時計の状態変化": sum(a["now"] == b["now"] for a, b in zip(rows[:-1], rows[1:])),
                    "MFE": max(0, peak), "実際の峰d": peak, "返済粗pt": ds[-1],
                    "始終を含む正常板数": len(rows)})

# ----------------------------------------
# 小事例10件に期限理由はないため、全保存取引の期限1件とコードを別確認する。

deadline_trade = next(t for t in all_trades.values() if t["返済要求原板行"] == 0)
whole = path_rows(deadline_trade, entries[deadline_trade["場"]])
strict_previous = [r for r in whole if r["now"] < deadline_trade["返済要求時計秒"]][-1]
check("期限要求参照はstrict<force", strict_previous["now"] < deadline_trade["返済要求時計秒"], True)
code = (ROOT / "scripts/利益回収/診断.py").read_text(encoding="utf-8")
check("診断の期限板参照はleft境界の一つ前", 'np.searchsorted(q["now"], request_time, side="left")) - 1' in code, True)
output = {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
          "閾値集計": {"比較群数": len(saved["手法別期間別"]), "閾値": [5, 20, 50, 100],
                      "対象": "旧33×学習40/選択24と既使用11月4日の固定実行候補だけ。未実行をゼロ化しない。"},
          "監査コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "診断集計SHA256": hashlib.sha256((STUDY / "集計.json").read_bytes()).hexdigest(),
          "事例": reports,
          "期限参照補足": {"場": deadline_trade["場"], "手法": deadline_trade["手法"],
                           "force": deadline_trade["返済要求時計秒"], "strict直前時計": strict_previous["now"],
                           "strict直前原行": strict_previous["line"], "小事例に期限なし": True},
          "方法": "診断.py/diagnoseをimportせず、集計は元gzipの保存MFEと最終額から独立再集計。3事例はnpzを素朴逐次走査。",
          "限界": "全2957取引の峰時刻・途中赤字を独立に全走査したものではない。期限例は出力CSVにないためコード境界と直前板の別確認。"}
target = STUDY / "独立確認.json"
target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors}, ensure_ascii=False))
if errors:
    raise SystemExit(1)
