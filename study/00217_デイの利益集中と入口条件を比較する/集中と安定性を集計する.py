"""全デイの固定対照と新入口を同じ時計・同じ指標で比較する。"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "work/217比較"
sys.path.insert(0, str(next((ROOT / "study").glob("00216_*"))))
from 全場を集計する import calculate, sources

GROUPS = {
    "日経": ("日経199_02", "217日経"),
    "通知": ("日経通知でTOPIX", "217通知"),
    "専用": ("TOPIX専用212デイ", "217TOPIX"),
    "移植": ("TOPIX移植03", None),
}
MODES = ("赤字2連続", "損切2連続", "損切当日2回")
SUMMARY = {
    "場数": "場数", "参加場": "参加場数", "取得": "建玉回数", "未知": "未知件数",
    "利益": "既知利益円", "損失": "既知損失円", "収支": "既知収支円",
    "勝": "黒字建玉数", "敗": "赤字建玉数", "順": "順先着数", "逆": "逆先着数",
    "未到達": "未到達数", "不足": "観測不足件数", "黒字場": "確定黒字日数",
    "赤字場": "確定赤字日数", "場末DD既知": "日末最大DD既知円", "保有率": "既知保有時間率",
    "場中央値下限": "場中央値下限円", "場中央値上限": "場中央値上限円",
    "建玉中央値下限": "建玉中央値下限円", "建玉中央値上限": "建玉中央値上限円",
}
DAILY = {
    "場": "セッション", "利益": "既知利益円", "損失": "既知損失円", "収支": "既知収支円",
    "確定収支": "確定収支円", "既知累計": "既知累計円", "確定累計": "確定累計円",
    "取得": "建玉回数", "勝": "黒字建玉数", "敗": "赤字建玉数", "未知": "未知件数",
    "順": "順先着数", "逆": "逆先着数", "未到達": "未到達数", "不足": "観測不足件数",
    "保有率": "既知保有時間率",
}


def stop_entries(trades: list, mode: str) -> list:
    """
    機能：確定した不適合が指定回数に達した日の残りの新規だけを停止する。
    引数：trades（list）は単一枠の固定元帳、mode（str）は停止条件。
    返り値：list。その日最後に採用する決済を含む建玉の並び。
    """
    grouped = defaultdict(list)
    for trade in trades:
        grouped[trade["scene"]].append(trade)
    kept = []
    for group in grouped.values():
        streak = 0
        for trade in sorted(group, key=lambda t: t["entry_time"]):
            kept.append(trade)
            if trade["net"] is None:
                assert trade is group[-1]
                break
            hit = trade["net"] < 0 if mode == "赤字2連続" else trade["label"] == -1
            if hit:
                streak += 1
            elif mode != "損切当日2回":
                streak = 0
            if streak == 2:
                assert trade["exit_time"] is not None
                break
    return kept


def load_books(full: bool) -> tuple:
    """
    機能：試行216の全対象日を保存し、基準と入口変更後の元帳を対応づける。
    引数：full（bool）は指数ごとの新入口元帳を加える場合に真。
    返り値：tuple。日付、口座別・候補別の全建玉。
    """
    dates, old, _ = sources("デイ")
    native_dates, native, _ = sources("TOPIX専用デイ")
    assert dates == native_dates and len(dates) == 45
    old.update(native)
    books = {}
    for group, (key, folder) in GROUPS.items():
        baseline = old["216:" + key]
        choices = {"基準": baseline}
        for mode in MODES:
            choices[mode] = stop_entries(baseline, mode)
        if folder and full:
            raw = json.loads((ROOT / "work" / folder / "比較元帳.json").read_text(encoding="utf-8-sig"))
            for name, rows in raw.items():
                assert {r["scene"] for r in rows} <= set(dates)
                choices["入口" + name] = sorted(rows, key=lambda t: (t["scene"], t["entry_time"]))
        books[group] = choices
    return dates, books


def day_order(daily: list) -> list:
    """
    機能：確定黒字日を収支の大きい順に並べる。同額は日付順。
    引数：daily（list）は1日1行の口座成績。
    返り値：list。日付の列。
    """
    return [r["場"] for r in sorted(daily, key=lambda r: (-r["収支"], r["場"]))
            if r["確定収支"] is not None and r["収支"] > 0]


def comparisons(dates: list, rows: list, base: list) -> tuple:
    """
    機能：固定順の期間別成績と、上位日を外した感度・対照との日別差を計算する。
    引数：dates（list）は全日、rows（list）は候補の元帳、base（list）は固定対照の日別結果。
    返り値：tuple。日別、期間別、同じ日を比較した増減の診断。
    """
    daily, all_days = calculate(dates, rows, "全体")
    top, ref = day_order(daily)[:3], day_order(base)[:3]
    spans = {
        "全45日": dates, "前24日": dates[:24], "後21日": dates[24:],
        "後半のうち最初の18日": dates[24:42], "直近3日": dates[42:],
        "10月20日を除く": [d for d in dates if d != "2026-10-20_Day"],
        "自身の利益上位3日を除く": [d for d in dates if d not in top],
        "基準の利益上位3日を除く": [d for d in dates if d not in ref],
    }
    for day in dates:
        session = date.fromisoformat(day[:10])
        monday = session - timedelta(days=session.weekday())
        spans.setdefault(f"{monday:%m月%d日}の週", []).append(day)
    stats = {key: all_days if key == "全45日" else calculate(sub, rows, "全体")[1]
             for key, sub in spans.items()}
    paired = [(r["場"], round(r["収支"]-b["収支"], 2))
              for r, b in zip(daily, base, strict=True)
              if r["確定収支"] is not None and b["確定収支"] is not None]
    gains = sorted((p for p in paired if p[1] > 0), key=lambda p: -p[1])
    delta = {
        "上位日": top, "基準上位日": ref, "確定比較日": len(paired),
        "改善日": sum(v > 0 for _, v in paired), "悪化日": sum(v < 0 for _, v in paired),
        "改善上位3日": gains[:3], "改善上位3日を除いた差": round(sum(v for _, v in paired)
                                                    - sum(v for _, v in gains[:3]), 2),
    }
    return daily, stats, delta


def make_index(output: dict) -> str:
    """
    機能：各案の頻度・損失・集中度を口座ごとに並べて比較できる表を作る。
    引数：output（dict）は口座・条件別の全期間評価。
    返り値：str。円を単位とした閲覧用Markdown。
    """
    lines = ["# デイの全候補比較", "",
             "金額はmini1枚の費用後、単位は円。損失と最大DDは正の金額。収支と日末DDは確定取引の寄与のみ。"
             "上位3日除外は各案の確定黒字上位3日を外した残り42日の既知収支で、注文の採否には使わない。"
             "未知がある日の既知寄与も残す。前24日は10月22日まで、後21日は10月23日から。", "",
             "[条件と結果の読み方](README.md) ・ [日経の条件](日経/仮説.md) ・ [TOPIX専用の条件](TOPIX専用/候補と選択.md) ・ [日経通知の条件](日経通知/README.md)"]
    for group in GROUPS:
        lines += ["", "## " + group, "",
                  "| 条件 | 参加日/45 | 建玉 | 未知 | 保有率 | 赤字日 | 総損失 | 日末最大DD | 全45日収支 | 前24日 | 後21日 | 10/20除外 | 上位3日除外 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for key, report in output.items():
            kind, name = key.split("/")
            if kind != group or name in ("入口NK00", "入口T00", "入口通知00"):
                continue
            p = report["期間"]
            a = p["全45日"]
            nums = [a["損失"], a["場末DD既知"], a["収支"], p["前24日"]["収支"], p["後21日"]["収支"],
                    p["10月20日を除く"]["収支"], p["自身の利益上位3日を除く"]["収支"]]
            money = [format(x, ",.1f").removesuffix(".0") for x in nums]
            cells = [name.removeprefix("入口"), str(a["参加場"]), str(a["取得"]), str(a["未知"]),
                     f"{a['保有率']:.1%}", str(a["赤字場"]), *money]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    """
    機能：各案の全評価と、閲覧指定した案だけのCSV用データを生成する。
    引数：コマンドラインの --基準のみ（bool）・--閲覧設定（Path、任意）。
    返り値：None。全候補の比較を作業領域に保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--基準のみ", action="store_true")
    parser.add_argument("--閲覧設定", type=Path)
    args = parser.parse_args()
    selected = json.loads(args.閲覧設定.read_text(encoding="utf8")) if args.閲覧設定 else {}
    dates, groups = load_books(not args.基準のみ)
    output = {}
    tables = {
        "候補比較": {"headers": ["候補", "期間"] + list(SUMMARY.values()), "rows": []},
        "デイ": {"headers": ["候補"] + list(DAILY.values()), "rows": []},
    }
    for group, books in groups.items():
        base = calculate(dates, books["基準"], "全体")[0]
        for name, rows in books.items():
            daily, stats, delta = comparisons(dates, rows, base)
            key = group + "/" + name
            output[key] = {"期間": stats, "日別差": delta}
            if key in selected:
                title = "217:" + selected[key]
                for period, summary in stats.items():
                    tables["候補比較"]["rows"].append([title, period] + [summary[k] for k in SUMMARY])
                for row in daily:
                    tables["デイ"]["rows"].append([title] + [row[k] for k in DAILY])
    # ----------------------------------------
    WORK.mkdir(parents=True, exist_ok=True)
    assert set(selected) <= output.keys()
    name = "固定と停止の集計" if args.基準のみ else "全条件の集計"
    (WORK / (name + ".json")).write_text(json.dumps(output, ensure_ascii=False, allow_nan=False), encoding="utf8")
    if selected:
        data = {"tableNames": {"候補比較":"集計", "デイ":"デイ"}, "tables": tables}
        (WORK / "閲覧用入力.json").write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf8")
        (HERE / "全候補の比較.md").write_text(make_index(output), encoding="utf8")


if __name__ == "__main__":
    main()
