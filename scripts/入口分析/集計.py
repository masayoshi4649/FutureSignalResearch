"""入口イベントの到達ラベルを独立再計数し、事前固定した層だけを記述する。"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any


GROUPS = ("無条件両方向", "5分方向", "複数足整合", "整合突破", "押し戻り復帰", "収縮拡大突破")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
PERIODS = ("全60場", "既使用前半40場", "既使用後半17場", "既使用末尾3場")
SIDES = ("両方向", "買い", "売り")
STRATA = {
    "残り分_判断時": ("60分未満", "60分以上180分未満", "180分以上"),
    "400ptのATR倍": ("2以下", "2超4以下", "4超8以下", "8超"),
    "方向側RSI5": ("50未満", "50以上70未満", "70以上"),
    "観測数量比": ("欠測", "1未満", "1以上1.2未満", "1.2以上"),
    "Day/Night": ("Day", "Night"),
}
RATES = ("順行先着率_全約定", "順行先着率_判定可能", "順行先着率_二閾値到達のみ")
COUNT_FIELDS = ("候補数", "約定候補数", *LABELS, "候補発生場数", "順行発生場数")
EXTRA_FIELDS = ("逆行発生場数", "期限未達発生場数", "観測不足発生場数", "未約定発生場数")
PAIRED_FIELDS = ("条件群", "期間", "方向", *COUNT_FIELDS,
                 *(f"反対方向_{label}" for label in LABELS), "約定した同時刻対数", "約定発生場数",
                 "自分_成功確認割合", "同時刻半々_成功確認割合", "確認割合差", "差_百分率ポイント", "解釈")
JST = timezone(timedelta(hours=9))


# ----------------------------------------
# 文字列の入力と、固定した区分の読み取り

def read_csv(path: Path) -> list[dict[str, Any]]:
    """UTF-8のCSVを読み、空ファイルも空の表として受け付ける。

    引数: path (Path) は入力CSV。
    返り値: list[dict[str, Any]] は文字列の行。元ファイルは変更しない。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def number(value: Any) -> Decimal:
    """有限な十進数へ変換し、空欄や非数値を黙ってゼロにしない。

    引数: value (Any) は数値または数値文字列。
    返り値: Decimal は有限の数値。不正値はValueErrorにする。
    """
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"数値として読めない値: {value!r}") from error
    if not result.is_finite():
        raise ValueError(f"有限でない値: {value!r}")
    return result


def phase_of(session: str) -> str:
    """既使用期間を、事前に固定した40・17・3場の区分へ割り当てる。

    引数: session (str) は日付とDay/Nightを含む場名。
    返り値: str は既使用の前半・後半・末尾区分。未使用を意味しない。
    """
    if session > "2026-10-29_Day":
        return PERIODS[3]
    return PERIODS[2] if session[:10] >= "2026-10-19" else PERIODS[1]


def day_type(session: str) -> str:
    """場名からデイとナイトを明示的に取り出す。

    引数: session (str) は場名。
    返り値: str はDayまたはNight。不明な場名はValueErrorにする。
    """
    suffix = session.rsplit("_", 1)[-1]
    if suffix not in ("Day", "Night"):
        raise ValueError(f"Day/Nightが不明な場名: {session}")
    return suffix


def fixed_strata(row: dict[str, Any]) -> dict[str, str]:
    """判断時の特徴を、事前固定した互いに重ならない層へ割り当てる。

    引数: row (dict[str, Any]) は入口事例の一行。
    返り値: dict[str, str] は五診断軸の層名。結果や所要分を条件に使わない。
    """
    remaining = number(row["残り分_判断時"])
    atr_multiple = number(row["400ptのATR倍"])
    rsi = number(row["方向側RSI5"])
    if remaining < 0 or atr_multiple <= 0 or not 0 <= rsi <= 100:
        raise ValueError(f"入口診断の値域が不正: {row['イベントID']}")
    volume_text = row["観測数量比"]
    if volume_text is None or str(volume_text).strip().lower() in ("", "none", "nan"):
        volume_layer = STRATA["観測数量比"][0]
    else:
        volume = number(volume_text)
        if volume < 0:
            raise ValueError("観測数量比が負")
        volume_layer = STRATA["観測数量比"][1 if volume < 1 else 2 if volume < Decimal("1.2") else 3]
    return {
        "残り分_判断時": STRATA["残り分_判断時"][0 if remaining < 60 else 1 if remaining < 180 else 2],
        "400ptのATR倍": STRATA["400ptのATR倍"][0 if atr_multiple <= 2 else 1 if atr_multiple <= 4 else 2 if atr_multiple <= 8 else 3],
        "方向側RSI5": STRATA["方向側RSI5"][0 if rsi < 50 else 1 if rsi < 70 else 2],
        "観測数量比": volume_layer, "Day/Night": day_type(row["場"]),
    }


def add_check(report: dict[str, Any], passed: bool, name: str, context: Any = None) -> None:
    """照合の件数と不一致を記録する。

    引数: report (dict[str, Any]) は照合記録、passed (bool) は合否、
    name (str) は検査名、context (Any) は対象と不一致値。
    返り値: None。詳細は先頭50件まで保存し、不一致総数は省略しない。
    """
    report["検査数"] += 1
    if not passed:
        report["不一致数"] += 1
        if len(report["不一致"]) < 50:
            report["不一致"].append({"検査": name, "詳細": context})


# ----------------------------------------
# 元の集計関数を使わない、ラベルと分母の独立再計数

def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """入口事例から件数・三つの率・ラベル別発生場数を再計数する。

    引数: rows (list[dict[str, Any]]) は同じ集計に属する入口事例。
    返り値: dict[str, Any] は集計値。ゼロ分母の率はNoneとする。
    """
    counts = Counter(row["ラベル"] for row in rows)
    filled = sum(counts[label] for label in LABELS[:-1])
    known = counts["順行先着"] + counts["逆行先着"] + counts["期限未達"]
    hit = counts["順行先着"] + counts["逆行先着"]
    result = {"候補数": len(rows), "約定候補数": filled, **{label: counts[label] for label in LABELS},
              "順行先着率_全約定": Decimal(counts["順行先着"]) / filled if filled else None,
              "順行先着率_判定可能": Decimal(counts["順行先着"]) / known if known else None,
              "順行先着率_二閾値到達のみ": Decimal(counts["順行先着"]) / hit if hit else None,
              "候補発生場数": len({row["場"] for row in rows})}
    for label in LABELS:
        result[f"{label[:2]}発生場数" if label in ("順行先着", "逆行先着") else f"{label}発生場数"] = len(
            {row["場"] for row in rows if row["ラベル"] == label})
    return result


def select_rows(rows: list[dict[str, Any]], group: str, period: str, side: str) -> list[dict[str, Any]]:
    """六群の所属・既使用期間・売買方向で入口を選ぶ。

    引数: rows (list[dict[str, Any]]) は入口、group/period/side (str) は固定集計キー。
    返り値: list[dict[str, Any]] は該当行。同じイベントの同一群内重複は作らない。
    """
    return [row for row in rows if group in row["_群集合"]
            and (period == PERIODS[0] or row["期間"] == period)
            and (side == SIDES[0] or row["方向"] == side)]


def compare_summary(actual: dict[str, Any], expected: dict[str, Any], report: dict[str, Any], key: Any) -> None:
    """分析側CSVの全件数・率を、入口からの再計数と照合する。

    引数: actual/expected (dict[str, Any]) は既存行と独立計数、
    report (dict[str, Any]) は記録、key (Any) は集計キー。
    返り値: None。率だけは小数直列化の絶対誤差1e-12以内を許す。
    """
    for field in (*COUNT_FIELDS, *RATES):
        value = actual[field]
        target = expected[field]
        if target is None:
            passed = value is None or value == ""
        else:
            tolerance = Decimal("1e-12") if field in RATES else Decimal(0)
            passed = value not in (None, "") and abs(number(value) - number(target)) <= tolerance
        add_check(report, passed, f"集計照合/{field}", {"対象": key, "元集計": value, "再計数": target})


def audit_inputs(events: list[dict[str, Any]], comparisons: list[dict[str, Any]],
                 sessions: list[dict[str, Any]], report: dict[str, Any]) -> set[str]:
    """イベントの一意性と、全期間・方向・場別集計を独立に照合する。

    引数: events/comparisons/sessions (list[dict[str, Any]]) は三入力表、
    report (dict[str, Any]) は照合記録。
    返り値: set[str] はゼロ候補の場も含む対象場集合。
    """
    identifiers = set()
    for row in events:
        identity = row["イベントID"]
        add_check(report, identity not in identifiers, "入口イベントIDが一意", identity)
        identifiers.add(identity)
        groups = row["条件群"].split("|")
        add_check(report, len(groups) == len(set(groups)) and set(groups) <= set(GROUPS)
                  and GROUPS[0] in groups, "条件群が既知・重複なし・基準所属", identity)
        add_check(report, row["ラベル"] in LABELS, "ラベルが既知", identity)
        add_check(report, row["方向"] in SIDES[1:], "売買方向が既知", identity)
        add_check(report, row["期間"] == phase_of(row["場"]), "入口の既使用期間が一致", identity)
        row["_群集合"] = set(groups)
        row["_層"] = fixed_strata(row)
    session_names = {row["場"] for row in sessions}
    add_check(report, len(session_names) == 60, "ゼロ候補の場を含め60場", len(session_names))
    for period, size in zip(PERIODS[1:], (40, 17, 3)):
        actual = sum(phase_of(session) == period for session in session_names)
        add_check(report, actual == size, "既使用期間の場数", {"期間": period, "場数": actual, "期待": size})
    add_check(report, {row["場"] for row in events} <= session_names, "全入口の場が場別集計に存在")
    seen = set()
    for row in comparisons:
        key = row["条件群"], row["期間"], row["方向"]
        add_check(report, key not in seen, "候補比較キーが一意", key)
        seen.add(key)
        compare_summary(row, summarize(select_rows(events, *key)), report, key)
    expected_keys = {(group, period, side) for group in GROUPS for period in PERIODS for side in SIDES}
    add_check(report, seen == expected_keys, "候補比較の六群・全期間・全方向が網羅", len(seen))
    seen_sessions = set()
    for row in sessions:
        key = row["条件群"], row["場"]
        add_check(report, key not in seen_sessions, "場別集計キーが一意", key)
        seen_sessions.add(key)
        add_check(report, row["期間"] == phase_of(row["場"]) and row["方向"] == SIDES[0], "場別集計の期間・方向", key)
        selected = [event for event in events if event["場"] == row["場"] and row["条件群"] in event["_群集合"]]
        compare_summary(row, summarize(selected), report, key)
    add_check(report, seen_sessions == {(group, session) for group in GROUPS for session in session_names},
              "全60場・六群の場別集計が網羅", len(seen_sessions))
    return session_names


# ----------------------------------------
# 固定層別と、その足戻しの確認

def stratified_rows(events: list[dict[str, Any]], session_names: set[str], report: dict[str, Any]) -> list[dict[str, Any]]:
    """各診断軸を別々に集計し、層を結果から選ばない全表を作る。

    引数: events (list[dict[str, Any]]) は入口、session_names (set[str]) は全対象場、
    report (dict[str, Any]) は分割の足戻し記録。
    返り値: list[dict[str, Any]] は六群・四期間・三方向・全固定層の行。
    """
    result = []
    for group in GROUPS:
        for period in PERIODS:
            period_sessions = {session for session in session_names if period == PERIODS[0] or phase_of(session) == period}
            for side in SIDES:
                selected = select_rows(events, group, period, side)
                totals = summarize(selected)
                for axis, layers in STRATA.items():
                    partition = []
                    for layer in layers:
                        part = [row for row in selected if row["_層"][axis] == layer]
                        target_sessions = {session for session in period_sessions
                                           if axis != "Day/Night" or day_type(session) == layer}
                        summary = summarize(part)
                        partition.append(summary)
                        result.append({"条件群": group, "期間": period, "方向": side, "診断軸": axis, "層": layer,
                                       "対象場数": len(target_sessions), **summary})
                    for field in ("候補数", "約定候補数", *LABELS):
                        actual = sum(row[field] for row in partition)
                        add_check(report, actual == totals[field], f"固定層別の足戻し/{field}",
                                  (group, period, side, axis))
    return result


def save_value(value: Any) -> Any:
    """集計に使った十進数を保存可能な値へ変換する。

    引数: value (Any) は保存対象。
    返り値: Any はDecimalだけを小数点以下10桁の文字列へ変換した値。
    """
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.0000000001")), "f")
    return value


def write_strata(path: Path, rows: list[dict[str, Any]]) -> None:
    """固定層別の全行を日本語UTF-8のCSVへ保存する。

    引数: path (Path) は保存先、rows (list[dict[str, Any]]) は集計表。
    返り値: None。候補ゼロの層も見出しとゼロ件数を残す。
    """
    fields = ["条件群", "期間", "方向", "診断軸", "層", "対象場数", *COUNT_FIELDS, *RATES, *EXTRA_FIELDS]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: save_value(row[key]) for key in fields} for row in rows)


# ----------------------------------------
# 同時刻の反対方向を対応させた、方向選択の記述

def paired_direction_rows(events: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    """同一場・足終了時点の対で、自分と買売半々の成功確認割合を比べる。

    引数: events (list[dict[str, Any]]) は共通ラベルを持つ全入口、
    report (dict[str, Any]) は対の存在・未約定一致・基準差の照合記録。
    返り値: list[dict[str, Any]] は六群・全期間・全方向の記述。原板は再読しない。
    """
    pairs: dict[tuple[str, Decimal], dict[str, dict[str, Any]]] = {}
    for row in events:
        key = row["場"], number(row["足終了時計秒"])
        row["_同時刻キー"] = key
        pair = pairs.setdefault(key, {})
        add_check(report, row["方向"] not in pair, "同時刻・同方向イベントが一意", key)
        pair[row["方向"]] = row
    for key, pair in pairs.items():
        add_check(report, set(pair) == set(SIDES[1:]), "同時刻の買い・売り対が存在", key)
        if set(pair) != set(SIDES[1:]):
            continue
        buy, sell = pair["買い"], pair["売り"]
        add_check(report, (buy["ラベル"] == "未約定") == (sell["ラベル"] == "未約定"),
                  "同時刻対の未約定状態が一致", key)
        add_check(report, number(buy["残り分_判断時"]) == number(sell["残り分_判断時"]),
                  "同時刻対の残り時間が一致", key)
        if "新規時計秒" in buy and "新規時計秒" in sell and buy["ラベル"] != "未約定" and sell["ラベル"] != "未約定":
            add_check(report, number(buy["新規時計秒"]) == number(sell["新規時計秒"]),
                      "同時刻対の仮新規時計が一致", key)
    if report["不一致数"]:
        return []
    result = []
    for group in GROUPS:
        for period in PERIODS:
            for side in SIDES:
                selected = select_rows(events, group, period, side)
                filled = [row for row in selected if row["ラベル"] != "未約定"]
                opposite = [pairs[row["_同時刻キー"]]["売り" if row["方向"] == "買い" else "買い"] for row in selected]
                opposite_filled = [pairs[row["_同時刻キー"]]["売り" if row["方向"] == "買い" else "買い"] for row in filled]
                own_success = sum(row["ラベル"] == "順行先着" for row in filled)
                other_success = sum(row["ラベル"] == "順行先着" for row in opposite_filled)
                own_rate = Decimal(own_success) / len(filled) if filled else None
                half_rate = Decimal(own_success + other_success) / (2 * len(filled)) if filled else None
                difference = own_rate - half_rate if filled else None
                opposite_counts = Counter(row["ラベル"] for row in opposite)
                summary = summarize(selected)
                if group == GROUPS[0] and side == SIDES[0]:
                    add_check(report, difference == 0 if filled else difference is None,
                              "両方向基準の同時刻差はゼロ（ゼロ分母は空欄）", (period, len(filled)))
                add_check(report, len(filled) == summary["約定候補数"], "同時刻方向比較の全約定分母", (group, period, side))
                result.append({"条件群": group, "期間": period, "方向": side,
                               **{field: summary[field] for field in COUNT_FIELDS},
                               **{f"反対方向_{label}": opposite_counts[label] for label in LABELS},
                               "約定した同時刻対数": len({row["_同時刻キー"] for row in filled}),
                               "約定発生場数": len({row["場"] for row in filled}),
                               "自分_成功確認割合": own_rate, "同時刻半々_成功確認割合": half_rate,
                               "確認割合差": difference, "差_百分率ポイント": difference * 100 if difference is not None else None,
                               "解釈": "全約定分母。不明は未確認として0、失敗とは呼ばない。同時刻の方向選択の記述であり無作為化実験ではない"})
    report["同時刻対数"] = len(pairs)
    report["同時刻方向比較行数"] = len(result)
    return result


def write_paired(path: Path, rows: list[dict[str, Any]]) -> None:
    """同時刻方向比較をUTF-8のCSVへ保存する。

    引数: path (Path) は保存先、rows (list[dict[str, Any]]) は方向比較表。
    返り値: None。差は割合と百分率ポイントを別列にし、価格ptと区別する。
    """
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PAIRED_FIELDS)
        writer.writeheader()
        writer.writerows({field: save_value(row[field]) for field in PAIRED_FIELDS} for row in rows)


# ----------------------------------------
# 全候補を分母にする一枚の図と実行記録

def draw_labels(study: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    """全60場・両方向の六群を固定順で描き、未約定も同時に見せる。

    引数: study (Path) は保存先、events (list[dict[str, Any]]) は入口事例。
    返り値: dict[str, Any] は図の分母・候補順・版・フォント情報。
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    import matplotlib.pyplot as plt

    font_path = Path("C:/Windows/Fonts/meiryo.ttc")
    if not font_path.is_file():
        font_path = Path(font_manager.findfont("Meiryo", fallback_to_default=False))
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    figure, axis = plt.subplots(figsize=(13, 6), constrained_layout=True)
    summaries = [summarize(select_rows(events, group, PERIODS[0], SIDES[0])) for group in GROUPS]
    colors = ("#009e73", "#d55e00", "#b8b8b8", "#e6b94a", "#b3cde3")
    left = [0.0] * len(GROUPS)
    for label, color in zip(LABELS, colors):
        widths = [100 * row[label] / row["候補数"] if row["候補数"] else 0 for row in summaries]
        axis.barh(range(len(GROUPS)), widths, left=left, color=color, label=label, height=0.65)
        for index, width in enumerate(widths):
            if width >= 7:
                axis.text(left[index] + width / 2, index, f"{width:.1f}%", ha="center", va="center", fontsize=9)
        left = [position + width for position, width in zip(left, widths)]
    axis.set_yticks(range(len(GROUPS)))
    axis.set_yticklabels([f"{group}\n候補{row['候補数']:,}・約定{row['約定候補数']:,}"
                         for group, row in zip(GROUPS, summaries)], fontsize=10)
    axis.invert_yaxis()
    axis.set_xlim(0, 100)
    axis.set_xticks(range(0, 101, 20), [f"{value}%" for value in range(0, 101, 20)])
    axis.set_xlabel("各群の全候補を分母とする割合（未約定も含む）")
    axis.grid(axis="x", alpha=0.2)
    axis.set_axisbelow(True)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=5, fontsize=10)
    figure.suptitle("到達順序の内訳：NK225・全60場・両方向\n全て再利用探索。群と近接入口は重複し、独立な実運用取引ではない。", fontsize=13)
    target = study / "到達順序の内訳.png"
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return {"ファイル": target.name, "分母": "各群の全候補（未約定も含む）", "期間": PERIODS[0],
            "方向": SIDES[0], "条件群": list(GROUPS), "matplotlib": matplotlib.__version__, "フォント": str(font_path)}


def run(study: Path) -> bool:
    """既存三表を照合し、固定層別と図を生成する。

    引数: study (Path) は入口事例・候補比較・場別集計のあるフォルダ。
    返り値: bool は全照合と出力が成功した場合True。不一致時はJSONだけ更新する。
    """
    report: dict[str, Any] = {"日時": datetime.now(JST).isoformat(), "対象": str(study),
                              "Python": platform.python_version(), "検査数": 0, "不一致数": 0, "不一致": [],
                              "照合合格": False,
                              "層別定義": STRATA,
                              "注意": ["全60場は再利用探索。前半・後半・末尾3場を未使用とは呼ばない。",
                              "固定層は記述用。成績のよい層を選んだ追加フィルターや最適化は生成しない。",
                              "全約定率は観測不足も分母。判定可能率は観測不足を除き期限未達は含む。二閾値のみの率で判断しない。",
                              "図だけは全候補を分母に未約定も描く。表の全約定率と分母が異なる。",
                              "時間層別は残り分_判断時のみ。所要分や最後の正常板の時計を実際の期限時刻と解釈しない。",
                              "同時刻方向比較は各群の約定イベントを分母に、自分成功と同時刻反対方向成功の半々平均を比較。不明は未確認として0だが失敗とは呼ばない。",
                              "同時刻対は場+足終了時計秒。半々は方向選択の記述的対照であり、無作為化実験ではない。",
                              "同一市場経路と仮想保有の重複があり、件数は独立反復数でも実運用損益でもない。",
                              "本照合はCSV間の独立再計数。原板の閾値先着や約定可能性を再検証していない。"]}
    try:
        names = ("入口事例.csv", "候補比較.csv", "場別集計.csv")
        tables = {name: read_csv(study / name) for name in names}
        report["入力"] = {name: {"行数": len(tables[name]), "SHA256": hashlib.sha256((study / name).read_bytes()).hexdigest()}
                          for name in names}
        report["集計コードSHA256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        events = tables["入口事例.csv"]
        session_names = audit_inputs(events, tables["候補比較.csv"], tables["場別集計.csv"], report)
        rows = stratified_rows(events, session_names, report)
        paired = paired_direction_rows(events, report)
        report["固定層別行数"] = len(rows)
        if report["不一致数"]:
            raise ValueError("入力または固定層別の足戻しが不一致のため、派生成果物を更新しない")
        write_strata(study / "固定層別.csv", rows)
        write_paired(study / "同時刻方向比較.csv", paired)
        report["図"] = draw_labels(study, events)
        report["照合合格"] = True
        report["結果状態"] = "照合合格・固定層別を生成"
    except Exception as error:
        report["結果状態"] = "照合または生成失敗"
        report["例外"] = f"{type(error).__name__}: {error}"
    target = study / "集計照合結果.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=save_value, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{report['結果状態']}：検査{report['検査数']}件、不一致{report['不一致数']}件。{target}")
    if "例外" in report:
        print(report["例外"], file=sys.stderr)
    return report["照合合格"]


def main() -> None:
    """コマンド引数で対象試行を指定して集計する。

    引数: なし。argparseで--study (Path) を読む。
    返り値: None。失敗時は終了コード1とする。
    """
    parser = argparse.ArgumentParser(description="固定200/400pt入口ラベルの再計数・層別・内訳図")
    parser.add_argument("--study", type=Path, required=True)
    args = parser.parse_args()
    study = args.study.resolve()
    if not study.is_dir():
        parser.error("--studyは既存の成果物フォルダを指定してください")
    if not run(study):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
