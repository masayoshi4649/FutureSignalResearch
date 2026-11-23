"""機械選択済みの四代表例を、円損益でなく新規価格からの順逆行ptで描く。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------
# 固定メタデータと正常板原行の照合

def load_reader() -> Any:
    """既存の独立照合から固定台帳・正常板の読取処理だけを読み込む。

    引数: なし。
    返り値: Any は独立照合モジュール。先着ラベルや代表例は再選択しない。
    """
    path = Path(__file__).with_name("独立照合.py")
    spec = importlib.util.spec_from_file_location("代表経路図の正常板読取", path)
    if spec is None or spec.loader is None:
        raise ImportError("独立照合の読取処理を読み込めない")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_index(quotes: dict[str, np.ndarray], line: int, clock: float) -> int:
    """正常板列から原板行を一意に探し、メタデータの価格時計と照合する。

    引数: quotes (dict[str, np.ndarray]) は原順正常板、line (int) は原板行、
    clock (float) は期待する価格時計秒。
    返り値: int は列内の位置。不一致時はAssertionErrorにする。
    """
    positions = np.flatnonzero(quotes["line"] == line)
    assert len(positions) == 1, f"正常板の原行が一意でない: {line}"
    index = int(positions[0])
    assert float(quotes["now"][index]) == clock, f"原行と価格時計が不一致: {line}"
    return index


def example_path(example: dict[str, Any], quotes: dict[str, np.ndarray], reader: Any) -> dict[str, Any]:
    """新規から最初の到達までの返済気配差と、後の返済点を分けて取り出す。

    引数: example (dict[str, Any]) は固定代表メタデータ、quotes (dict[str, np.ndarray]) は正常板、
    reader (Any) はセッション時刻の読取モジュール。
    返り値: dict[str, Any] は順逆行ptの原順系列と、到達・返済・初期スプレッド。
    """
    side = int(example["side"])
    assert side in (1, -1), "売買方向が不正"
    assert example["方向"] == ("買い" if side == 1 else "売り"), "売買方向の表記が不一致"
    entry_index = source_index(quotes, int(example["新規原板行"]), float(example["新規時計秒"]))
    hit_index = source_index(quotes, int(example["到達原板行"]), float(example["到達時計秒"]))
    exit_index = source_index(quotes, int(example["返済原板行"]), float(example["返済時計秒"]))
    assert entry_index <= hit_index < exit_index, "新規・到達・返済の原順が不正"
    assert np.all(np.diff(quotes["line"]) > 0), "正常板の原板行が非増加"
    assert np.all(np.diff(quotes["now"]) >= 0), "正常板の価格時計が後退"
    assert np.all(np.isfinite(quotes["bid"])) and np.all(np.isfinite(quotes["ask"])), "正常板価格が非有限"
    assert np.all((quotes["bid"] > 0) & (quotes["ask"] > quotes["bid"])), "正常板のBid/Askが不正"
    entry = float(quotes["ask"][entry_index] if side == 1 else quotes["bid"][entry_index])
    mark = quotes["bid"] if side == 1 else quotes["ask"]
    assert entry == float(example["新規価格"]), "新規モデル価格がメタデータと不一致"
    assert float(mark[hit_index]) == float(example["到達返済気配"]), "到達気配がメタデータと不一致"
    assert float(mark[exit_index]) == float(example["返済価格"]), "返済価格がメタデータと不一致"
    assert float(example["逆行線"]) == entry - side * 200, "逆行線が固定200ptと不一致"
    assert float(example["順行線"]) == entry + side * 400, "順行線が固定400ptと不一致"

    # ----------------------------------------
    # 同時計の異なる原行もそのまま残し、到達より後の経路を線へ含めない。
    path_slice = slice(entry_index, hit_index + 1)
    times = quotes["now"][path_slice]
    minutes = (times - float(example["新規時計秒"])) / 60
    distances = side * (mark[path_slice] - entry)
    spread = float(quotes["ask"][entry_index] - quotes["bid"][entry_index])
    assert float(distances[0]) == -spread, "初期スプレッドの不利分が反映されていない"
    assert np.all(np.diff(times) <= 300), "到達前に300秒超の正常板空白がある"
    assert not np.any((distances[:-1] >= 400) | (distances[:-1] <= -200)), "保存された到達より前に閾値到達がある"
    hit_distance = float(distances[-1])
    expected_label = "順行先着" if hit_distance >= 400 else "逆行先着" if hit_distance <= -200 else None
    assert expected_label == example["ラベル"], "到達点の順逆行ptとラベルが不一致"

    # ----------------------------------------
    # hit+1価格時計秒以後の最初の正常板という既存返済モデルも照合する。
    _, end, _, _ = reader.session_times(example["場"])
    possible = np.flatnonzero((quotes["now"] >= float(example["到達時計秒"]) + 1)
                              & (quotes["now"] < end) & (quotes["line"] > int(example["到達原板行"])))
    assert len(possible) and int(possible[0]) == exit_index, "返済が固定モデルの最初の正常板でない"
    exit_distance = side * (float(mark[exit_index]) - entry)
    assert exit_distance == float(example["単独例価格差pt"]), "返済価格差ptがメタデータと不一致"
    wait = float(example["返済時計秒"]) - float(example["到達時計秒"])
    assert wait >= 1 and wait == float(example["到達後返済待機秒"]), "到達後の価格時計待機が不一致"
    return {"分": minutes, "順逆行pt": distances, "初期pt": float(distances[0]),
            "到達分": float(minutes[-1]), "到達pt": hit_distance,
            "返済分": (float(example["返済時計秒"]) - float(example["新規時計秒"])) / 60,
            "返済pt": exit_distance, "返済待機秒": wait, "観測数": len(distances)}


def read_examples(study: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """四例の固定キャッシュだけを読み、ハッシュ・原行範囲・根拠価格を検査する。

    引数: study (Path) は代表事例.jsonと入力台帳のある試行フォルダ。
    返り値: tuple[list[dict[str, Any]], list[dict[str, Any]]] は代表メタデータと描画用系列。
    """
    metadata = json.loads((study / "代表事例.json").read_text(encoding="utf-8"))
    examples = metadata["代表"]
    expected = {(group, label) for group in ("整合突破", "押し戻り復帰") for label in ("順行先着", "逆行先着")}
    assert len(examples) == 4 and {(row["条件群"], row["ラベル"]) for row in examples} == expected, "固定四例が揃っていない"
    assert not metadata["欠落"], "代表例に欠落がある"
    reader = load_reader()
    manifest, _ = reader.read_manifest(study)
    entries = {(entry["symbol"], entry["session"]): entry for entry in manifest["entries"]}
    cached = {}
    paths = []
    for example in examples:
        entry = entries["NK225", example["場"]]
        cache = (ROOT / example["キャッシュ"]).resolve()
        assert example["キャッシュSHA256"] == entry["sha256_cache"], "代表と固定台帳のキャッシュ指紋が不一致"
        if cache not in cached:
            assert hashlib.sha256(cache.read_bytes()).hexdigest() == example["キャッシュSHA256"], "キャッシュSHA256不一致"
            quotes, _, _ = reader.load_quotes(cache, entry)
            cached[cache] = quotes
        quotes = cached[cache]
        for field in ("新規原板行", "到達原板行", "返済原板行"):
            assert 1 <= int(example[field]) <= int(entry["raw_lines"]), f"原板行が固定台帳範囲外: {field}"
        paths.append(example_path(example, quotes, reader))
    return examples, paths


# ----------------------------------------
# 2×2の価格pt経路図。一枚だけを正式成果物へ追加する。

def draw(study: Path, examples: list[dict[str, Any]], paths: list[dict[str, Any]]) -> Path:
    """到達前の観測経路と、到達・返済の異なる点を同じ価格pt尺度で描く。

    引数: study (Path) は出力先、examples (list[dict[str, Any]]) は固定代表、
    paths (list[dict[str, Any]]) は照合済みの系列。
    返り値: Path は一枚のPNG。メタデータと価格・時計・原行は変更しない。
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
    figure, axes = plt.subplots(2, 2, figsize=(14, 10), sharey=True)
    lower = min(-200.0, *(float(np.min(path["順逆行pt"])) for path in paths), *(path["返済pt"] for path in paths)) - 65
    upper = max(400.0, *(float(np.max(path["順逆行pt"])) for path in paths), *(path["返済pt"] for path in paths)) + 65
    for axis, example, path in zip(axes.flat, examples, paths):
        axis.axhline(400, color="#007c52", linestyle="--", linewidth=1.1)
        axis.axhline(-200, color="#be3c00", linestyle="--", linewidth=1.1)
        axis.axhline(0, color="#777777", linewidth=0.8)
        axis.plot(path["分"], path["順逆行pt"], color="#0072b2", linewidth=1.1,
                  drawstyle="steps-post", label="保存正常板の順逆行（新規〜到達）")
        axis.scatter([0], [path["初期pt"]], marker="s", color="#444444", s=30, zorder=5, label="新規時の返済気配")
        axis.scatter([path["到達分"]], [path["到達pt"]], marker="o", s=120, facecolors="white",
                     edgecolors="#6f4c9b", linewidths=2, zorder=6, label="閾値の最初の到達")
        axis.scatter([path["返済分"]], [path["返済pt"]], marker="x", s=85, color="#d55e00",
                     linewidths=2, zorder=7, label="1価格時計秒以後の返済約定")
        hit_offset = (-18, -19) if path["到達pt"] > 0 else (-18, 52)
        exit_offset = (-18, -57) if path["到達pt"] > 0 else (-18, 12)
        annotation_box = {"facecolor": "white", "edgecolor": "none", "alpha": 0.88, "pad": 1.5}
        axis.annotate(f"到達 {path['到達pt']:+g}pt", xy=(path["到達分"], path["到達pt"]),
                      xytext=hit_offset, textcoords="offset points", ha="right", fontsize=10,
                      bbox=annotation_box, arrowprops={"arrowstyle": "-", "color": "#6f4c9b"})
        axis.annotate(f"返済 {path['返済pt']:+g}pt\n到達後{path['返済待機秒']:g}価格時計秒", xy=(path["返済分"], path["返済pt"]),
                      xytext=exit_offset, textcoords="offset points", ha="right", fontsize=9,
                      bbox=annotation_box, arrowprops={"arrowstyle": "-", "color": "#d55e00"})
        axis.annotate(f"初期 {path['初期pt']:+g}pt\nスプレッドを含む", xy=(0, path["初期pt"]),
                      xytext=(8, -33), textcoords="offset points", fontsize=8, color="#444444")
        stamp = example["新規時計JST"].replace("T", " ").removesuffix("+09:00")
        axis.set_title(f"{example['条件群']}・{example['ラベル']}（{example['方向']}）\n新規 {stamp} JST", fontsize=11)
        axis.set_xlabel("新規からの経過分（価格時計）")
        axis.set_ylim(lower, upper)
        axis.set_xlim(-2, max(path["到達分"], path["返済分"]) * 1.07 + 1)
        axis.set_yticks([-200, 0, 200, 400])
        axis.grid(alpha=0.18)
    for axis in axes[:, 0]:
        axis.set_ylabel("新規モデル価格からの順逆行（価格pt）")
    figure.suptitle("代表4例の順逆行経路：200pt逆行と400pt順行の先着\n線は新規から到達まで。返済約定は別の点で示す（例：到達＋400pt、返済＋390pt）。", fontsize=14, y=0.98)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.095), ncol=2, fontsize=10)
    figure.text(0.5, 0.055, "買いはBid・売りはAskで評価。時計はCurrentPriceTimeの価格時計であり受信時計ではない。到達後の経路は線で追わない。",
                ha="center", fontsize=9)
    figure.text(0.5, 0.025, "過去の候補から規則で選んだ単独例。一般性を保証せず、実運用の損益や全入口の合算成績ではない。",
                ha="center", fontsize=9)
    figure.subplots_adjust(left=0.075, right=0.98, top=0.84, bottom=0.23, hspace=0.45, wspace=0.12)
    destination = study / "図" / "代表事例の順逆行経路.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=150)
    plt.close(figure)
    return destination


def main() -> None:
    """対象試行の四例を照合し、一枚の価格pt経路図を生成する。

    引数: なし。argparseで--study (Path) を読み取る。
    返り値: None。不一致時は例外で停止し、根拠を変更して描画しない。
    """
    parser = argparse.ArgumentParser(description="固定代表4例の順逆行pt経路と到達・返済の差を一枚に描く")
    parser.add_argument("--study", type=Path, required=True)
    study = parser.parse_args().study.resolve()
    examples, paths = read_examples(study)
    for example, path in zip(examples, paths):
        print(f"{example['条件群']}・{example['ラベル']}：正常板{path['観測数']}点、初期{path['初期pt']:+g}pt、"
              f"到達{path['到達pt']:+g}pt、返済{path['返済pt']:+g}pt、待機{path['返済待機秒']:g}価格時計秒")
    print(draw(study, examples, paths))


if __name__ == "__main__":
    main()
