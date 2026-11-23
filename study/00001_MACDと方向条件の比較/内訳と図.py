"""主計算の成果物だけから内訳表とセッション末の累積損益図を作る。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager, ticker


# ----------------------------------------
# 入力の確認と共通集計

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
PHASES = ("全期間", "開発", "未使用評価")
METHODS = ("MACDのみ", "方向条件", "方向条件とRSI")
SYMBOLS = ("NK225", "TOPIX")
TOLERANCE = 1e-7


def read_csv(path: Path) -> list[dict[str, str]]:
    """日本語の集計CSVを読み取る。

    引数: path (Path) はUTF-8のCSV。空の取引CSVも許容する。
    返り値: list[dict[str, str]] は列名をキーとする行。
    """
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def number(row: dict[str, Any], key: str) -> float:
    """集計に必要な有限数を取り出し、欠測を黙って0にしない。

    引数: row (dict[str, Any]) は行、key (str) は数値列の名前。
    返り値: float は有限の列値。不正な値ならValueErrorを送出する。
    """
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"数値列が欠測または不正: {key}") from error
    if not math.isfinite(value):
        raise ValueError(f"有限でない数値: {key}")
    return value


def unfinished(row: dict[str, Any]) -> bool:
    """場末の建玉または未約定が残るか確認する。

    引数: row (dict[str, Any]) はセッション集計の1行。
    返り値: bool は未解消を含む場合に真。
    """
    return number(row, "終了建玉") != 0 or number(row, "終了未約定") != 0


def selected(rows: list[dict[str, Any]], symbol: str, method: str, phase: str) -> list[dict[str, Any]]:
    """商品・手法・事前に定めた期間で行を抽出する。

    引数: rows (list[dict[str, Any]]) は元の行、symbol/method/phase (str) は抽出条件。
    返り値: list[dict[str, Any]] は条件に合う行。全期間では期間を限定しない。
    """
    return [row for row in rows if row["銘柄"] == symbol and row["手法"] == method
            and (phase == "全期間" or row["期間"] == phase)]


def metrics(sessions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    """無取引場を含めて内訳を集計し、未解消があれば主損益を空欄にする。

    引数: sessions (list[dict[str, Any]]) は対象場、trades (list[dict[str, Any]]) は内訳対象の完結取引。
    返り値: dict[str, Any] は件数・状態・損益。売買別も同じ場集合を分母にする。
    """
    by_session = {row["場"]: 0.0 for row in sessions}
    active_sessions: set[str] = set()
    for trade in trades:
        if trade["場"] not in by_session:
            raise ValueError("対象場にない取引が内訳へ混入した")
        by_session[trade["場"]] += number(trade, "純損益円")
        active_sessions.add(trade["場"])
    profits = [number(trade, "純損益円") for trade in trades]
    gross = sum(number(trade, "値幅損益円") for trade in trades)
    fees = sum(number(trade, "手数料円") for trade in trades)
    total = sum(profits)
    gains = sum(max(value, 0) for value in profits)
    losses = -sum(min(value, 0) for value in profits)
    incomplete_count = sum(unfinished(row) for row in sessions)
    complete = incomplete_count == 0
    return {
        "セッション数": len(sessions), "無取引場数": len(sessions) - len(active_sessions),
        "未解消場数": incomplete_count, "結果状態": "完結" if complete else "不完全・持越し制約違反",
        "取引数": len(trades), "値幅損益円": gross if complete else None,
        "手数料円": fees if complete else None, "純損益円": total if complete else None,
        "平均場損益円": total / len(sessions) if sessions and complete else None,
        "平均取引損益円": total / len(trades) if trades and complete else None,
        "勝率": sum(value > 0 for value in profits) / len(trades) if trades and complete else None,
        "PF": gains / losses if losses and complete else None,
        "最悪場円": min(by_session.values(), default=None) if complete else None,
        "費用増純損益円": sum(number(trade, "費用増純損益円") for trade in trades) if complete else None,
        "完結取引純損益円": total,
    }


def validate_inputs(sessions: list[dict[str, Any]], trades: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    """入力の重複、対応関係、主計算との合計一致を確認する。

    引数: sessions/trades/results (list[dict[str, Any]]) は主計算の3成果物。
    返り値: None。不整合・未完成の成果物ならValueErrorを送出する。
    """
    if not sessions or not results:
        raise ValueError("セッション集計と結果JSONが揃っていない")
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    methods_by_session: dict[tuple[str, str], set[str]] = {}
    for row in sessions:
        key = (row["銘柄"], row["場"], row["手法"])
        if key in seen:
            raise ValueError(f"セッション行の重複: {key}")
        if row["銘柄"] not in SYMBOLS or row["手法"] not in METHODS or row["期間"] not in PHASES[1:]:
            raise ValueError(f"この試行で未定義の分類: {key}")
        session_end(row["場"])
        seen[key] = row
        methods_by_session.setdefault(key[:2], set()).add(row["手法"])
    if any(value != set(METHODS) for value in methods_by_session.values()):
        raise ValueError("同じセッションの3候補が揃っていない")
    for trade in trades:
        key = (trade["銘柄"], trade["場"], trade["手法"])
        if key not in seen or trade["期間"] != seen[key]["期間"] or trade["方向"] not in ("買い", "売り"):
            raise ValueError(f"取引とセッションの対応が不正: {key}")
    result_keys: set[tuple[str, str, str]] = set()
    for row in results:
        key = (row["銘柄"], row["期間"], row["手法"])
        if key in result_keys:
            raise ValueError(f"結果JSONの重複: {key}")
        result_keys.add(key)
        group_sessions = selected(sessions, key[0], key[2], key[1])
        group_trades = selected(trades, key[0], key[2], key[1])
        current = metrics(group_sessions, group_trades)
        if number(row, "セッション数") != current["セッション数"] or number(row, "取引数") != current["取引数"]:
            raise ValueError(f"主計算と件数が不一致: {key}")
        if current["純損益円"] is None:
            if row["純損益円"] is not None:
                raise ValueError(f"未解消を含む主損益が欠測になっていない: {key}")
        else:
            cash = sum(number(item, "純損益円") for item in group_sessions)
            if not math.isclose(cash, current["純損益円"], abs_tol=TOLERANCE, rel_tol=1e-12):
                raise ValueError(f"完結取引とセッションの純損益が不一致: {key}")
            if not math.isclose(number(row, "純損益円"), cash, abs_tol=TOLERANCE, rel_tol=1e-12):
                raise ValueError(f"結果JSONとセッションの純損益が不一致: {key}")
    expected = {(symbol, phase, method) for symbol in SYMBOLS for phase in PHASES for method in METHODS}
    if result_keys != expected:
        raise ValueError("結果JSONの銘柄・期間・候補の集合が事前分類と一致しない")


# ----------------------------------------
# 時間帯別・売買別・対応差の小さな表

def breakdowns(sessions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """時間帯別と売買別の小集計を作る。

    引数: sessions/trades (list[dict[str, Any]]) は検査済みの主計算成果物。
    返り値: tuple[list[dict[str, Any]], list[dict[str, Any]]] は時間帯別・売買別の行。
    """
    time_rows, side_rows = [], []
    for symbol in SYMBOLS:
        for phase in PHASES:
            for method in METHODS:
                group_sessions = selected(sessions, symbol, method, phase)
                group_trades = selected(trades, symbol, method, phase)
                for suffix, label in (("_Day", "デイ"), ("_Night", "ナイト")):
                    time_rows.append({"銘柄": symbol, "期間": phase, "手法": method, "時間帯": label,
                                      **metrics([row for row in group_sessions if row["場"].endswith(suffix)],
                                                [row for row in group_trades if row["場"].endswith(suffix)])})
                for side in ("買い", "売り"):
                    side_rows.append({"銘柄": symbol, "期間": phase, "手法": method, "売買": side,
                                      **metrics(group_sessions, [row for row in group_trades if row["方向"] == side])})
    return time_rows, side_rows


def paired_differences(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """事前に定めた隣接候補のセッション対応差を期間別にまとめる。

    引数: sessions (list[dict[str, Any]]) は検査済みのセッション集計。
    返り値: list[dict[str, Any]] は正差・負差・同値の場数と合計・平均。未解消時は主合計を空欄にする。
    """
    rows = []
    pairs = (("方向条件", "MACDのみ", "方向追加差"), ("方向条件とRSI", "方向条件", "RSI追加差"))
    for symbol in SYMBOLS:
        for phase in PHASES:
            for added, baseline, label in pairs:
                first = {row["場"]: row for row in selected(sessions, symbol, added, phase)}
                second = {row["場"]: row for row in selected(sessions, symbol, baseline, phase)}
                if set(first) != set(second):
                    raise ValueError("対応比較のセッション集合が一致しない")
                differences = []
                incomplete = 0
                for name in sorted(first):
                    if unfinished(first[name]) or unfinished(second[name]):
                        incomplete += 1
                    else:
                        differences.append(number(first[name], "純損益円") - number(second[name], "純損益円"))
                rows.append({"銘柄": symbol, "期間": phase, "比較": label, "追加候補": added, "基準候補": baseline,
                             "対象場数": len(first), "比較可能場数": len(differences), "未解消を含む場数": incomplete,
                             "正差場数": sum(value > TOLERANCE for value in differences),
                             "負差場数": sum(value < -TOLERANCE for value in differences),
                             "同値場数": sum(abs(value) <= TOLERANCE for value in differences),
                             "差合計円": sum(differences) if not incomplete else None,
                             "差平均円": sum(differences) / len(differences) if differences and not incomplete else None,
                             "結果状態": "完結" if not incomplete else "不完全・持越し制約違反"})
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """集計表を日本語UTF-8のCSVへ保存する。

    引数: path (Path) は出力先、rows (list[dict[str, Any]]) は同じ列構造の行。
    返り値: None。Noneは空欄にし、欠測を0に置き換えない。
    """
    if not rows:
        raise ValueError("出力する集計行がない")
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# ----------------------------------------
# 原板を読み直さない参考図

def session_end(name: str) -> datetime:
    """開始日基準のセッション識別子をJSTのセッション末へ変換する。

    引数: name (str) は日付_Dayまたは日付_Night。
    返り値: datetime は日中15:45または翌日06:00。実際の最終約定時計とは別の表示位置。
    """
    date, part = name.split("_")
    day = datetime.fromisoformat(date).replace(tzinfo=JST)
    if part == "Day":
        return day.replace(hour=15, minute=45)
    if part == "Night":
        return day + timedelta(days=1, hours=6)
    raise ValueError(f"未定義のセッション名: {name}")


def configure_font(font_path: Path | None) -> str:
    """ローカルの日本語フォントを直接参照して描画設定へ登録する。

    引数: font_path (Path | None) は明示フォント。省略時はWindowsの既存フォントから探す。
    返り値: str は採用したフォントの絶対パス。フォントファイルの複製は行わない。
    """
    candidates = [font_path] if font_path is not None else [Path("C:/Windows/Fonts/meiryo.ttc"),
                                                          Path("C:/Windows/Fonts/YuGothM.ttc")]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            font_manager.fontManager.addfont(str(candidate))
            font = font_manager.FontProperties(fname=str(candidate))
            plt.rcParams.update({"font.family": font.get_name(), "font.size": 10, "axes.unicode_minus": False})
            return str(candidate.resolve())
    raise FileNotFoundError("日本語フォントがない。--fontでローカルのフォントファイルを指定する")


def plot_cumulative(sessions: list[dict[str, Any]], path: Path, font_path: Path | None) -> str:
    """指数別2パネルでセッション末の累積純損益を描く。

    引数: sessions (list[dict[str, Any]]) は主計算の場別結果、path (Path) はPNG先、
    font_path (Path | None) はローカルの日本語フォント。
    返り値: str は採用フォント。含み損益や含み込みDDはこの図から計算しない。
    """
    font = configure_font(font_path)
    evaluation_dates = [row["場"][:10] for row in sessions if row["期間"] == "未使用評価"]
    if not evaluation_dates:
        raise ValueError("未使用評価の開始日を図へ示せない")
    boundary = datetime.fromisoformat(min(evaluation_dates)).replace(tzinfo=JST)
    figure, axes = plt.subplots(2, 1, figsize=(13, 8.2), sharex=True)
    colors = ("#3366AA", "#D78128", "#26856A")
    incomplete_any = False
    for axis, symbol in zip(axes, SYMBOLS):
        for method, color in zip(METHODS, colors):
            ordered = sorted((session_end(row["場"]), row["場"], row)
                             for row in selected(sessions, symbol, method, "全期間"))
            if not ordered:
                raise ValueError(f"描画するセッションがない: {symbol}/{method}")
            first_name = ordered[0][1]
            origin = datetime.fromisoformat(first_name[:10]).replace(tzinfo=JST)
            origin += timedelta(hours=8, minutes=45) if first_name.endswith("_Day") else timedelta(hours=17)
            times, values = [origin], [0.0]
            cumulative = 0.0
            stopped = False
            for at, name, row in ordered:
                if unfinished(row):
                    stopped = True
                    incomplete_any = True
                    break
                cumulative += number(row, "純損益円")
                times.append(at)
                values.append(cumulative)
            label = method + ("（未解消以降は非表示）" if stopped else "")
            axis.step(times, values, where="post", color=color, linewidth=1.7, label=label)
        axis.axhline(0, color="#66717D", linewidth=0.7)
        axis.axvline(boundary, color="#5A6370", linestyle="--", linewidth=1)
        axis.text(boundary, 0.97, " 未使用評価開始\n " + boundary.strftime("%Y-%m-%d"),
                  transform=axis.get_xaxis_transform(), va="top", ha="left", fontsize=9,
                  bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 2})
        product = "日経225マイクロ 1枚" if symbol == "NK225" else "ミニTOPIX 1枚"
        axis.set_title(f"{symbol} ／ {product}", loc="left", fontsize=12)
        axis.set_ylabel("累積純損益（円）")
        axis.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
        axis.grid(axis="y", alpha=0.22)
        axis.legend(loc="lower right", bbox_to_anchor=(1, 1.005), fontsize=9,
                    frameon=False, ncol=3, borderaxespad=0)
    locator = mdates.AutoDateLocator(minticks=6, maxticks=11, tz=JST)
    axes[-1].xaxis.set_major_locator(locator)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d", tz=JST))
    axes[-1].set_xlabel("セッション末（日本時間）")
    figure.suptitle("3候補のセッション末累積純損益", fontsize=16, y=0.985)
    note = "手数料控除済み・ラージ気配による代理評価。含み込み最大DDは主計算の別集計を参照。"
    if incomplete_any:
        note += " 未解消を含む手法は、その場以降の累積を表示していない。"
    figure.text(0.055, 0.018, note, fontsize=9, color="#44505D")
    figure.tight_layout(rect=(0.025, 0.045, 0.995, 0.96), h_pad=2.4)
    figure.savefig(path, dpi=160, facecolor="white")
    plt.close(figure)
    return font


def run(folder: Path, output: Path, font_path: Path | None) -> None:
    """主計算が揃った後に内訳CSV3件と参考PNG1件を生成する。

    引数: folder (Path) は主計算成果物のある試行フォルダ、output (Path) は出力先、
    font_path (Path | None) は既存日本語フォントへの任意の参照。
    返り値: None。再現.pyや主計算成果物は書き換えない。
    """
    sessions = read_csv(folder / "セッション集計.csv")
    trades = read_csv(folder / "取引集計.csv")
    results = json.loads((folder / "結果.json").read_text(encoding="utf-8"))
    validate_inputs(sessions, trades, results)
    time_rows, side_rows = breakdowns(sessions, trades)
    difference_rows = paired_differences(sessions)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "内訳_時間帯.csv", time_rows)
    write_csv(output / "内訳_売買.csv", side_rows)
    write_csv(output / "対応差集計.csv", difference_rows)
    font = plot_cumulative(sessions, output / "損益推移.png", font_path)
    print(f"内訳の生成完了: 時間帯{len(time_rows)}行、売買{len(side_rows)}行、対応差{len(difference_rows)}行")
    print(f"参考図: {output / '損益推移.png'}")
    print(f"参照フォント: {font}")
    print(f"描画ライブラリ: matplotlib {matplotlib.__version__}")


# ----------------------------------------
# 再現用の実行入口

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="試行00001の内訳表と累積損益の参考図を作る")
    parser.add_argument("--folder", type=Path, default=HERE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    run(args.folder.resolve(), (args.output or args.folder).resolve(), args.font)
