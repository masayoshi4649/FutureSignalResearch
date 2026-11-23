"""固定済み5分CSVの完全な子足から5/15/30分の公表と履歴本数を調べる。"""
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/三尺度可用性の正式参照"
OUT.mkdir(parents=True, exist_ok=True)
MANIFEST = ROOT / "study/00106_収束失速で保護の起動と幅を切り替える/入力台帳_70場.json"
CLOCKS = ROOT / "study/00108_開始静観20分と30分の比較/検査/時計の可用性.json"
COMPLETE = ROOT / "work/106市場/全70場/完了.json"
TZ = timezone(timedelta(hours=9))
WIDTHS = (300, 900, 1800)
THRESHOLDS = {"EMA8": 8, "EMA21": 21, "EMA21傾き": 22, "ATR14": 14, "RSI14": 15, "RSI差": 16, "MACDhist": 34, "MACDhist差": 35}


def sha(path):
    """
    機能: 固定参照の指紋を取得する。
    引数: path(Path)は小型CSV又はmetadata。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(epoch):
    """
    機能: 名目公表時計を日本時間で記述する。
    引数: epoch(int|float)は保存秒。
    返り値: strは日本時間のISO8601。
    """
    return datetime.fromtimestamp(epoch, TZ).isoformat()


def price_valid(row):
    """
    機能: 子足のOHLCを量の完備性と分離して検査する。
    引数: row(dict)は一つの共有5分足。
    返り値: boolは価格正常・closedなら真。
    """
    o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
    return all(math.isfinite(x) and x > 0 for x in (o, h, l, c)) and h >= max(o, c) and l <= min(o, c) and h >= l and row["closed"] == "true"


def volume_valid(row):
    """
    機能: 約定出来高だけの既知性を検査する。
    引数: row(dict)は一つの共有5分足。
    返り値: boolは完全・非負有限の量なら真。
    """
    return row["volume_complete"] == "true" and math.isfinite(float(row["volume"])) and float(row["volume"]) >= 0


def main():
    """
    機能: 完全子足の件数と同限月carry/欠足reset後の履歴本数を集計する。
    引数: なし。原板・Source・金融・指標数値を計算しない。
    返り値: なし。名目公表の可用性上限をworkへ保存する。
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    clock = json.loads(CLOCKS.read_text(encoding="utf-8"))
    completion = json.loads(COMPLETE.read_text(encoding="utf-8"))
    assert clock["成功"] and completion["success"] and len(manifest["sessions"]) == 70
    clocks = {r["session"]["id"]: r["session"] for r in clock["details"]}
    headers = {r["session"]: r["sidecar_header"] for r in completion["results"]}
    sources = [{"path": str(p), "sha256": sha(p)} for p in (MANIFEST, CLOCKS, COMPLETE, Path(__file__).resolve())]
    counts = {(symbol, w): 0 for symbol in ("NK225", "TOPIX") for w in WIDTHS}
    last_contract = None
    scenes = []
    total = {symbol: {str(w): Counter() for w in WIDTHS} for symbol in ("NK225", "TOPIX")}
    grid_total = Counter()
    for scene in manifest["sessions"]:
        sid, contract = scene["id"], scene["contract"]
        s = clocks[sid]
        h_ref = headers[sid]
        h_path = Path(h_ref["path"])
        assert sha(h_path) == h_ref["sha256"]
        header = json.loads(h_path.read_text(encoding="utf-8"))["header"]
        observed_end = header["ending"]["legacy"]["observed_clock"]
        sources.append({"path": str(h_path), "sha256": h_ref["sha256"]})
        carry = last_contract == contract
        if not carry:
            counts = {(symbol, w): 0 for symbol in ("NK225", "TOPIX") for w in WIDTHS}
        detail = {"session": sid, "contract": contract, "同限月carry": carry, "観測末尾": stamp(observed_end), "各尺度": {}, "判断枠の名目可用性上限": {}}
        histories = {}
        for symbol in ("NK225", "TOPIX"):
            ref = scene["files"][f"{symbol}_candle_300"]
            path = Path(manifest["source_root"]) / ref["path"]
            assert sha(path) == ref["sha256"] and path.stat().st_size == ref["size"]
            sources.append({"path": str(path), "sha256": ref["sha256"]})
            with path.open(encoding="utf-8-sig", newline="") as f:
                bars = list(csv.DictReader(f))
            indexed = {int(datetime.fromisoformat(b["time"]).timestamp()): b for b in bars}
            assert len(indexed) == len(bars)
            assert all(s["start"] <= t < s["end"] and (t - s["start"]) % 300 == 0 for t in indexed)
            for width in WIDTHS:
                initial = counts[symbol, width]
                summary = Counter()
                first = {k: None for k in THRESHOLDS}
                history = []
                for start in range(int(s["start"]), int(s["end"]), width):
                    end, due = start + width, start + width + 60
                    assert end <= s["end"]
                    if due > observed_end:
                        summary["観測EOF後のため公表しない"] += 1
                        continue
                    children = [indexed.get(t) for t in range(start, end, 300)]
                    missing = sum(b is None for b in children)
                    valid = missing == 0 and all(price_valid(b) for b in children)
                    quantity = valid and all(volume_valid(b) for b in children)
                    if valid:
                        counts[symbol, width] += 1
                        summary["価格既知公表"] += 1
                        summary["量既知公表" if quantity else "価格既知量未知公表"] += 1
                        for k, n in THRESHOLDS.items():
                            if first[k] is None and counts[symbol, width] >= n:
                                first[k] = stamp(due)
                    else:
                        counts[symbol, width] = 0
                        summary["価格欠足で数値履歴reset"] += 1
                        summary["欠けた子5分足"] += missing
                    history.append({"at": due, "price_known": valid, "history_bars": counts[symbol, width], "end": end})
                histories[symbol, width] = history
                summary["場開始の継承連続本数"] = initial
                summary["場末連続本数"] = counts[symbol, width]
                detail["各尺度"][f"{symbol}_{width//60}分"] = {"件数": dict(summary), "当場の最初の名目既知公表": first}
                for k, v in summary.items():
                    if k not in ("場開始の継承連続本数", "場末連続本数"):
                        total[symbol][str(width)][k] += v
        for quiet in (1200, 1800):
            grids = range(int(s["start"] + quiet), int(s["force_close"]), 300)
            classified = Counter()
            for t in grids:
                known = []
                for w in WIDTHS:
                    hs = [p for p in histories["NK225", w] if p["at"] <= t]
                    p = hs[-1] if hs else None
                    known.append(p is not None and p["price_known"] and p["history_bars"] >= 22 and t - p["end"] < w + 60)
                classified["全枠"] += 1
                classified["三尺度EMA21と傾き名目既知" if all(known) else "少なくとも一尺度が未知"] += 1
                if not known[2]:
                    classified["30分が未知"] += 1
                if not known[1]:
                    classified["15分が未知"] += 1
                if not known[0]:
                    classified["5分が未知"] += 1
            detail["判断枠の名目可用性上限"][str(quiet)] = dict(classified)
            grid_total.update({f"{quiet}_{k}": v for k, v in classified.items()})
        scenes.append(detail)
        last_contract = contract
    result = {"成功": True, "版": 2, "基礎": "固定70場の5分CSV、5/15/30分は同じSession.Start起点",
              "金融実行": 0, "Source実行": 0, "原板Body読取": 0, "指標の数値形成": 0,
              "範囲の限界": "価格子足と名目公開時計・履歴本数だけ。実配送clock未走査の上限で、技法成立率/参加率/損益ではない",
              "公表モデル": "各子5分開始+300+60秒。15/30は全子足の最大名目公開=親足終了+60。観測EOFを越えて強制公表/resetしない",
              "履歴本数": THRESHOLDS, "量未知で価格履歴をresetしない": True,
              "初回cold後同限月carry": True, "価格欠足時は該当尺度履歴reset": True,
              "集約": total, "全判断枠の名目可用性上限": dict(grid_total), "場別": scenes, "入力指紋": sources}
    assert all(sha(Path(r["path"])) == r["sha256"] for r in sources)
    (OUT / "5分15分30分の可用性.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"成功": True, "場数": len(scenes), "集約": total, "名目可用性": dict(grid_total), "指標の数値形成": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
