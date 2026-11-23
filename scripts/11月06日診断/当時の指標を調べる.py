"""固定済み107の11月6日を、当時公開済みの複数技法と実新規で記述診断する。"""
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/11月06日のテクニカル診断"
OUT.mkdir(parents=True, exist_ok=True)
TRIAL = ROOT / "study/00107_見送り明けの初回取得と利益保護"
TZ = timezone(timedelta(hours=9))
KEYS = [f"{c}_C0_D0" for c in ("B0", "B1", "BE", "Q0", "Q1", "QE")]


def stamp(epoch):
    """
    機能: 保存epochを日本時間へ変換する。
    引数: epoch(int|float)は保存秒。
    返り値: strはISO8601の日本時間。
    """
    return datetime.fromtimestamp(epoch, TZ).isoformat()


def sha(path):
    """
    機能: 参照正本の指紋を取得する。
    引数: path(Path)は参照先。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_bars(path):
    """
    機能: 共有5分足を複製せず読んで確定終了時刻を付ける。
    引数: path(Path)は原CSV。
    返り値: list[dict]は足。時刻列は開始時刻として終了は300秒後。
    """
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            row["epoch"] = datetime.fromisoformat(row["time"]).timestamp()
            for k in ("open", "high", "low", "close", "volume"):
                row[k] = float(row[k])
            rows.append(row)
    return rows


def native_atr_check(bars, reference):
    """
    機能: 保存native ATR12を当場5分足から独立して再計算する。
    引数: bars(list[dict])は共有確定足、reference(dict)は取得時固定ATR。
    返り値: dictは参照利用時刻までの再計算値と差。受信時刻の別推定は行わない。
    """
    previous, running, latest = None, 0.0, None
    for i, b in enumerate(bars):
        available = b["epoch"] + 360
        if available > reference["available"]:
            break
        tr = b["high"] - b["low"]
        if previous is not None:
            tr = max(tr, abs(b["high"] - previous), abs(b["low"] - previous))
        running = tr if i == 0 else running * (11 / 12) + tr * (1 / 12)
        previous = b["close"]
        latest = {"名目公開": stamp(available), "再計算値pt": max(running, 20)}
    assert latest is not None
    latest["保存値との差pt"] = latest["再計算値pt"] - reference["value"]
    assert abs(latest["保存値との差pt"]) < 1e-9
    return latest


def context(grid, at, side, bars, publications):
    """
    機能: 当該5分判断の公開値と直近確定価格構造を抽出する。
    引数: grid(dict)、at(int)、side(int)、bars/publications(list[dict])は記録と方向。
    返り値: dictは既知フラグを伴う説明値。新しい売買成績を計算しない。
    """
    legacy = grid["legacy"]
    t = legacy["chart"]["Technical"]
    closed = [b for b in bars if b["epoch"] + 360 <= at and b["closed"] == "true"]
    recent = closed[-4:]
    ma3 = t["ema8_3"] - t["ema21_3"]
    ma15 = t["ema8_15"] - t["ema21_15"]
    hist_inc = t["histogram3"] - t["previous_histogram3"]
    slopes = {}
    publication_clocks = {}
    for scale in (3, 15):
        end_key = f"bar{scale}_end"
        current = [p for p in publications if p[end_key] == t[end_key]]
        assert current
        first = current[0]
        assert max(first["_observed_clock"], first[f"_available_{scale}"], first["_delivery_at"], first["_frame_available"]) <= at
        fields = (["ema8_3", "ema21_3", "rsi3", "previous_rsi3", "histogram3", "previous_histogram3", "tr3", "atr3", "previous_atr3", "close3"]
                  if scale == 3 else ["ema8_15", "ema21_15"])
        assert all(first[k] == t[k] for k in fields)
        publication_clocks[f"{scale}分"] = {"初回公表観測": stamp(first["_observed_clock"]), "available_at": stamp(first[f"_available_{scale}"]),
                                                "delivery_at": stamp(first["_delivery_at"]), "frame_available_at": stamp(first["_frame_available"]),
                                                "値比較列": fields, "全値同値": True, "全時計が名目要求以前": True}
        ps = [p for p in publications if 0 < p[end_key] < t[end_key] and p["trend_known"]]
        previous = ps[-1] if ps else None
        slopes[f"{scale}分"] = {
            "既知": previous is not None and t["trend_known"],
            "比較元足端": stamp(previous[end_key]) if previous else None,
            "最新足端": stamp(t[end_key]) if t[end_key] else None,
            "EMA8の1足差pt": t[f"ema8_{scale}"] - previous[f"ema8_{scale}"] if previous else None,
            "EMA21の1足差pt": t[f"ema21_{scale}"] - previous[f"ema21_{scale}"] if previous else None,
        }
    return {
        "公開観測時刻": stamp(legacy["observed_clock"]),
        "同限月前場の数値種継承": legacy["carried_numeric_seed"],
        "根拠足の初回公表観測": publication_clocks,
        "方向既知": t["trend_known"], "勢い既知": t["spike_known"],
        "3分足終了": stamp(t["bar3_end"]) if t["bar3_end"] else None,
        "15分足終了": stamp(t["bar15_end"]) if t["bar15_end"] else None,
        "ema8_3": t["ema8_3"], "ema21_3": t["ema21_3"],
        "ema8_15": t["ema8_15"], "ema21_15": t["ema21_15"],
        "取引向き3分EMA差": side * ma3, "取引向き15分EMA差": side * ma15,
        "両時間軸が取引向き": bool(t["trend_known"] and side * ma3 > 0 and side * ma15 > 0),
        "rsi3": t["rsi3"], "前rsi3": t["previous_rsi3"],
        "histogram3": t["histogram3"], "前histogram3": t["previous_histogram3"],
        "取引向きヒストグラム差分": side * hist_inc,
        "EMA傾きの別記": slopes,
        "atr3": t["atr3"], "previous_atr3": t["previous_atr3"],
        "close3": t["close3"],
        "直近確定5分足": recent,
        "5分足公開条件": "元Sourceの保守的モデルに揃え足開始+300+60秒<=名目注文要求の足だけ。volume_completeは別途各行へ保持",
        "直近20分の高値安値": {"high": max(b["high"] for b in recent), "low": min(b["low"] for b in recent)} if recent else None,
        "量の注意": "原CSVのvolume_completeがtrueの足のみ厳密な出来高根拠にできる。未完備をゼロ補完しない",
    }


def main():
    """
    機能: 2場の保存済み公開値と新規を結合し、指紋付き診断JSONを作る。
    引数: なし。
    返り値: なし。市場・金融再実行と原板読取を行わない。
    """
    result = {"対象": "固定107の11月6日Day/Night、C0D0の6候補", "金融再実行": 0, "原板読取": 0, "sources": [], "scenes": []}
    for kind in ("Day", "Night"):
        sid = f"2026-11-06_{kind}"
        native_path = TRIAL / f"成果物_金融/Native/{sid}.Native.json.gz"
        record_path = ROOT / f"work/106市場/全70場/{sid}.public.records.jsonl.gz"
        bars_path = ROOT.parent / f"JP_OSE_Data/future/NK225/{sid}/candle_5min.csv"
        for path in (native_path, record_path, bars_path):
            result["sources"].append({"path": str(path), "sha256": sha(path)})
        with gzip.open(native_path, "rt", encoding="utf-8") as stream:
            native = json.load(stream)
        grids, publications = {}, []
        counts = Counter()
        with gzip.open(record_path, "rt", encoding="utf-8") as stream:
            for line in stream:
                r = json.loads(line)
                counts[r["kind"]] += 1
                if r["kind"] == "grid":
                    grids[r["at"]] = r["grid"]
                elif r["kind"] == "publication":
                    l = r["publication"]["snapshot"]["legacy"]
                    publications.append({**l["chart"]["Technical"], "_observed_clock": l["observed_clock"],
                                         "_available_3": l["three"]["available_at"], "_available_15": l["fifteen"]["available_at"],
                                         "_delivery_at": r["delivery"]["at"], "_frame_available": r["delivery"]["frame"]["available_at"]})
        bars = read_bars(bars_path)
        scene = {"session": sid, "record種別数": dict(counts), "grid数": len(grids),
                 "公開チャート": [{"at": at, "observed_clock": g["legacy"]["observed_clock"],
                                  "Technical": g["legacy"]["chart"]["Technical"]} for at, g in grids.items()], "books": {}}
        scene["価格概況"] = {"始値": bars[0]["open"], "高値": max(b["high"] for b in bars), "安値": min(b["low"] for b in bars), "終値": bars[-1]["close"],
                                  "高値足": [b["time"] for b in bars if b["high"] == max(x["high"] for x in bars)],
                                  "安値足": [b["time"] for b in bars if b["low"] == min(x["low"] for x in bars)]}
        for key in KEYS:
            b = native["books"][key]
            entries = []
            orders = {o["id"]: o for o in b["orders"]}
            for p in b["positions"]:
                order = orders[p["entry_order_id"]]
                at = order["request_time"]
                entries.append({"id": p["id"], "判断": stamp(at), "新規": stamp(p["entry_quote"]["time"]), "方向": "買" if p["side"] == 1 else "売",
                                "数量": p["initial_quantity"], "新規価格": p["entry_price"], "費用後確定損益円": p["realized_net"],
                                "Source出生": stamp(p["source"]["birth_time"]), "Source出生価格": p["source"]["birth_quote"]["last"],
                                "Sourceから判断まで秒": at - p["source"]["birth_time"],
                                "Source手法": p["source"]["method"], "Source親": p["source"]["parent"], "ATR起動参照": p["atr"],
                                "nativeATR独立検算": native_atr_check(bars, p["atr"]),
                                "当時公開値": context(grids[at], at, p["side"], bars, publications)})
            assert sum(e["費用後確定損益円"] for e in entries) == b["totals"]["net_yen"]
            scene["books"][key] = {"totals": b["totals"], "entries": entries}
        result["scenes"].append(scene)
        print(sid, "grid", len(grids), [(k, scene["books"][k]["totals"]["net_yen"]) for k in KEYS], flush=True)
    condition = TRIAL / "金融条件_埋込対応.json"
    pinned = json.loads(condition.read_text(encoding="utf-8"))["code_sha256"]
    suffixes = ["internal/e01/features.go", "internal/strategy/source143.go", "internal/strategy/active143.go", "internal/strategy/episode143.go",
                "internal/strategy/cores.go", "internal/strategy/selected_day164_features.go", "internal/strategy/features143.go"]
    for suffix in suffixes:
        selected = [(Path(p), h) for p, h in pinned.items() if p.replace("\\", "/").endswith(suffix)]
        assert len(selected) == 1
        path, expected = selected[0]
        assert sha(path) == expected
        result["sources"].append({"path": str(path), "sha256": expected, "固定107コード台帳との一致": True})
    prior = ROOT / "work/106市場/全70場/2026-11-05_Night.public.header.json"
    result["sources"].extend({"path": str(p), "sha256": sha(p)} for p in (condition, prior))
    result["前場終端15分EMA"] = json.loads(prior.read_text(encoding="utf-8"))["header"]["ending"]["legacy"]["chart"]["Technical"]
    result["意味"] = {"EMA差": "同一確定足におけるEMA8−EMA21、単位は価格pt。傾きではない", "傾き": "直前の異なる確定足から今回足までのEMA値変化pt/1足。1秒傾きではない",
                       "nativeATR": "当場5分OHLC、先頭TRを初期値とし1/12更新、3足以降known。利用名目は足開始+300+60秒。価格pt。追加3分ATR14と別物",
                       "追加数値carry": "同限月のsealed前場数値種のみ継承。当場の形成/公表/既知フラグは別に開始。15分EMA差には前場の値動きが残る"}
    for ref in result["sources"]:
        assert sha(Path(ref["path"])) == ref["sha256"]
    (OUT / "当時公開値と実新規.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
