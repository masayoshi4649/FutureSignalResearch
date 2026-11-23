"""00004の固定入口を再利用し、逆行125pt・順行250pt等の経路ラベルだけを作り直す。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import platform
import sys
from typing import Any, NamedTuple

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOURCE_STUDY = ROOT / "study/00004_逆行200ptと順行400ptの入口分析"
ANALYSIS_PATH = ROOT / "scripts/入口分析/分析.py"
AUDIT_PATH = Path(__file__).with_name("独立照合.py")


def load_module(path: Path, name: str) -> Any:
    """既存コードを変更せず、価格経路APIまたは独立入力読取を読み込む。

    引数: path (Path) はPythonファイル、name (str) は独立したモジュール名。
    返り値: Any は読み込んだモジュール。候補・特徴量の生成関数は実行しない。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


audit = load_module(AUDIT_PATH, "入口探索の独立監査")
analysis = load_module(ANALYSIS_PATH, "固定入口のラベルAPI")
JST = audit.JST


class 正常板(NamedTuple):
    """既存の気配経路APIへ渡す、原順を維持した正常BBOと価格時計。"""

    now: float
    line: int
    bid: float
    ask: float


def write_json(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON化可能な内容。
    返り値: None。非有限数を保存しない。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def self_test_core() -> None:
    """汎用価格幅APIの125/250等号と先着後の打切りを手計算で検証する。

    引数: なし。合成気配だけを使用し、外部データは読まない。
    返り値: None。不一致はAssertionErrorにする。
    """
    cases = [
        ("買い逆行125等号", [(1, 995, 1000), (2, 875, 880), (3, 1250, 1255)], 1, "逆行先着", 2, 0, 125),
        ("買い順行250等号", [(1, 995, 1000), (2, 1250, 1255), (3, 875, 880)], 1, "順行先着", 2, 250, 5),
        ("売り逆行125等号", [(1, 1000, 1005), (2, 1120, 1125), (3, 745, 750)], -1, "逆行先着", 2, 0, 125),
        ("売り順行250等号", [(1, 1000, 1005), (2, 745, 750), (3, 1120, 1125)], -1, "順行先着", 2, 250, 5),
        ("124逆行からの250到達", [(1, 995, 1000), (2, 876, 881), (3, 1250, 1255)], 1, "順行先着", 3, 250, 124),
        ("同時計の原順で逆行が先", [(1, 995, 1000), (2, 875, 880), (2, 1250, 1255)], 1, "逆行先着", 2, 0, 125),
        ("同時計の原順で順行が先", [(1, 995, 1000), (2, 1250, 1255), (2, 875, 880)], 1, "順行先着", 2, 250, 5),
    ]
    for name, values, side, label, at, mfe, mae in cases:
        quotes = [正常板(now, line, bid, ask) for line, (now, bid, ask) in enumerate(values, 1)]
        result = analysis.気配経路(quotes).evaluate(0, 10, 100, side, adverse=125, favorable=250)
        assert result["ラベル"] == label and result["判定時計秒"] == at, (name, result)
        assert result["最大順行pt"] == mfe and result["最大逆行pt"] == mae, (name, result)
    print("ラベルAPIの125/250合成検算7件が通過", flush=True)


# ----------------------------------------
# 固定した要求・特徴・新規を保ち、判定幅に依存する列だけを更新する。

def relabel_row(original: dict[str, str], route: Any, adverse: float, favorable: float) -> dict[str, Any]:
    """一つの固定入口を新しい価格幅で再判定する。

    引数: original (dict[str, str]) は元CSV行、route (Any) は既存の気配経路、
    adverse/favorable (float) は逆行・順行幅。
    返り値: dict[str, Any] は旧幅の列名を除去し、幅と新判定を明記した行。
    """
    replacements = {"400ptのATR倍": ("順行幅のATR倍", favorable), "200ptのATR倍": ("逆行幅のATR倍", adverse)}
    row = {}
    for key, value in original.items():
        if key in replacements:
            renamed, width = replacements[key]
            row[renamed] = width / float(original["ATR5"])
        else:
            row[key] = value
    signal, cutoff, deadline = (float(original[key]) for key in ("要求時計秒", "新規停止時計秒", "期限時計秒"))
    side = int(original["side"])
    delay = signal - float(original["足終了時計秒"])
    result = route.evaluate(signal, cutoff, deadline, side, adverse=adverse, favorable=favorable)
    if delay > 30:
        result = {key: None for key in result}
        result.update({"ラベル": "未約定", "理由": "足確定確認が30秒超"})
    for key in ("新規価格", "新規時計秒", "新規原板行"):
        before = audit.number(original[key])
        if result[key] != before:
            raise ValueError(f"固定入口が変わった: {original['イベントID']} {key}")
    row.update(result)
    row["逆行線"] = None if result["新規価格"] is None else result["新規価格"] - side * adverse
    row["順行線"] = None if result["新規価格"] is None else result["新規価格"] + side * favorable
    for clock in ("新規時計秒", "判定時計秒"):
        value = result[clock]
        row[clock.replace("秒", "JST")] = None if value is None else datetime.fromtimestamp(value, JST).isoformat()
    row["逆行幅pt"], row["順行幅pt"] = adverse, favorable
    return row


def summarize_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """無条件両方向のラベル件数と、方向だけを事後選択する機会上限を数える。

    引数: rows (list[dict[str, Any]]) は固定全入口の再ラベル行。
    返り値: dict[str, Any] は全内訳と観測成功率。条件選択・最適化は行わない。
    """
    labels = Counter(row["ラベル"] for row in rows)
    pairs = defaultdict(list)
    for row in rows:
        if "無条件両方向" not in row["条件群"].split("|"):
            raise ValueError("無条件両方向を含まない入口がある")
        pairs[(row["場"], row["足終了時計秒"])].append(row)
    if any(sorted(int(row["side"]) for row in pair) != [-1, 1] for pair in pairs.values()):
        raise ValueError("固定入口の買い売り対が不正")
    filled = len(rows) - labels["未約定"]
    filled_pairs = [pair for pair in pairs.values() if any(row["ラベル"] != "未約定" for row in pair)]
    any_success = sum(any(row["ラベル"] == "順行先着" for row in pair) for pair in pairs.values())
    both_success = sum(all(row["ラベル"] == "順行先着" for row in pair) for pair in pairs.values())
    return {"基準群": "無条件両方向", "入口行数": len(rows),
            "ラベル内訳": {label: labels[label] for label in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")},
            "約定入口数": filled, "順行先着率_全約定": labels["順行先着"] / filled if filled else None,
            "時点上限": {"全機会数": len(pairs), "約定あり機会数": len(filled_pairs),
                         "どちらか方向が順行先着の機会数": any_success, "両方向とも順行先着の機会数": both_success,
                         "どちらか成功率_全機会": any_success / len(pairs) if pairs else None,
                         "どちらか成功率_約定あり機会": any_success / len(filled_pairs) if filled_pairs else None,
                         "意味": "各時点で買い売りを未来のラベルで事後選択した観測上限。入口時点を全て採る場合の方向選択だけの上限であり、条件で一部時点を選ぶ勝率の上限ではない。期限未達・観測不足を分母から落とさない。"}}


def prepare(source_study: Path, output_dir: Path, cache_root: Path,
            adverse: float = 125, favorable: float = 250) -> dict[str, Any]:
    """元の全入口を維持し、ラベルCSVと入出力・コードSHAを保存する。

    引数: source_study/output_dir/cache_root (Path) は元試行・出力・固定キャッシュ、
    adverse/favorable (float) は逆行・順行の価格幅。
    返り値: dict[str, Any] は固定条件、入力品質、基準件数と時点率を含むメタ情報。
    """
    if min(adverse, favorable) <= 0 or not np.isfinite([adverse, favorable]).all():
        raise ValueError("逆行・順行幅は有限正数が必要")
    self_test_core()
    source_csv = source_study / "入口事例.csv"
    old_audit_path = source_study / "独立照合結果.json"
    old_audit = json.loads(old_audit_path.read_text(encoding="utf-8"))
    if not old_audit["一致"] or old_audit["不一致数"]:
        raise ValueError("元入口の全件独立照合が成功していない")
    if old_audit["ファイルSHA256"].get(audit.show_path(source_csv)) != audit.file_sha(source_csv):
        raise ValueError("旧照合後に元入口CSVが変更されている")
    manifest, manifest_path = audit.read_manifest(source_study)
    entries = [entry for entry in manifest["entries"] if entry["symbol"] == "NK225"]
    if len(entries) != 60:
        raise ValueError("NK225の固定60場でない")
    with source_csv.open(encoding="utf-8-sig", newline="") as source:
        originals = list(csv.DictReader(source))
    if len(originals) != 10588:
        raise ValueError("元入口が固定10,588行でない")
    by_session = defaultdict(list)
    for index, row in enumerate(originals):
        by_session[row["場"]].append((index, row))
    results = [None] * len(originals)
    inputs = []
    for number, entry in enumerate(entries, 1):
        source = Path(manifest["source_root"]) / entry["source_path"]
        status = source.stat()
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError("固定原板のサイズ・更新日時が変わった")
        path = cache_root / entry["cache_path"]
        quotes, _, quality = audit.load_quotes(path, entry)
        normal = [正常板(float(now), int(line), float(bid), float(ask)) for now, line, bid, ask in
                  zip(quotes["now"], quotes["line"], quotes["bid"], quotes["ask"])]
        route = analysis.気配経路(normal)
        for index, row in by_session[entry["session"]]:
            results[index] = relabel_row(row, route, adverse, favorable)
        inputs.append({"場": entry["session"], "原板": entry["source_path"], "原板サイズ": entry["source_size"],
                       "原板更新ns": entry["source_mtime_ns"], "原板stat一致": True,
                       "原板展開SHA256_固定台帳参照": entry["sha256_uncompressed"],
                       "キャッシュ": audit.show_path(path), "キャッシュSHA256": entry["sha256_cache"],
                       "品質": quality})
        print(f"再ラベル {number}/{len(entries)} {entry['session']} 固定入口{len(by_session[entry['session']])}", flush=True)
    if any(row is None for row in results):
        raise ValueError("台帳にない元入口がある")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"入口{favorable:g}_{adverse:g}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    # ----------------------------------------
    # 元の200/400幅を示す列名を残さず、固定条件と依存先を記録する。
    code_paths = (Path(__file__), AUDIT_PATH, ANALYSIS_PATH, ROOT / "scripts/複合検証/再生.py",
                  analysis.shared.LEGACY_PATH, ROOT / "scripts/複合検証/データ準備.py")
    input_paths = (source_csv, old_audit_path, source_study / "入力台帳.json", manifest_path, source_study / "条件.json")
    metadata = {"作成日時": datetime.now(JST).isoformat(), "Python": platform.python_version(), "NumPy": np.__version__,
                "元試行": audit.show_path(source_study), "元入口CSV": audit.show_path(source_csv),
                "固定入口行数": len(originals), "出力CSV": audit.show_path(csv_path), "出力CSV_SHA256": audit.file_sha(csv_path),
                "条件": {"対象": "NK225", "逆行pt": adverse, "順行pt": favorable, "正常板空白許容秒": 300,
                         "新規待機秒": 1, "新規有効秒": 30, "確認遅延許容秒": 30, "入力場数": 60},
                "再ラベル対象": "元10,588行の要求・特徴・入口を固定し、幅に依存する到達・MFE/MAE・線・ATR比だけを更新。feature/candidateは再生成しない。",
                "価格幅API": "scripts/入口分析/分析.py の気配経路.evaluate(adverse=逆行pt,favorable=順行pt)。空白・期限・EOFは00004と同一。",
                "成功定義": "買いは新規Ask/返済Bid、売りは新規Bid/返済Ask。逆行幅の等号で失敗、順行幅の等号で成功。最初の正常板から観測し、先着確定後の経路を見ない。",
                "列名変更": {"400ptのATR倍": "順行幅のATR倍", "200ptのATR倍": "逆行幅のATR倍"},
                "時計の限界": "CurrentPriceTimeは価格時計。受信時刻や全約定を復元せず、ラージ板からmini/microの実際の約定可能性も保証しない。",
                "探索範囲": "既使用NK225全60場の再利用探索。新規場なし。条件の選択や勝率最適化はこの処理では行わない。",
                "入力SHA256": {audit.show_path(path): audit.file_sha(path) for path in input_paths},
                "コードSHA256": {audit.show_path(path): audit.file_sha(path) for path in code_paths},
                "入力監査": inputs,
                "報告分割": {"学習40場": "開始日2026-09-21〜2026-10-16の20日",
                             "条件選択10場": "開始日2026-10-19〜2026-10-23の5日",
                             "後続検査10場": "開始日2026-10-26〜2026-10-30の5日。成績は最終選択固定後に確認。"},
                "基準集計": {"学習40場": summarize_baseline([row for row in results if row["場"][:10] <= "2026-10-16"]),
                             "条件選択10場": summarize_baseline([row for row in results if "2026-10-19" <= row["場"][:10] <= "2026-10-23"]),
                             "後続検査10場": "全行のラベル生成・照合は行うが、最終選択固定前は集計を表示しない。"}}
    write_json(output_dir / "ラベル準備メタ.json", metadata)
    print(json.dumps(metadata["基準集計"], ensure_ascii=False), flush=True)
    return metadata


def main() -> None:
    """固定入口の再ラベルまたはAPI合成検算だけを実行する。

    引数: なし。CLIの元試行・出力・キャッシュ・価格幅・合成検算指定を取得する。
    返り値: None。旧試行・旧コード・原板は変更しない。
    """
    parser = argparse.ArgumentParser(description="固定入口の125/250等への再ラベル")
    parser.add_argument("--source-study", type=Path, default=SOURCE_STUDY)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work/入口探索")
    parser.add_argument("--cache-root", type=Path, default=ROOT / "work/複合検証")
    parser.add_argument("--adverse", type=float, default=125)
    parser.add_argument("--favorable", type=float, default=250)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test_core()
        return
    prepare(arguments.source_study.resolve(), arguments.output_dir.resolve(), arguments.cache_root.resolve(),
            adverse=arguments.adverse, favorable=arguments.favorable)


if __name__ == "__main__":
    main()
