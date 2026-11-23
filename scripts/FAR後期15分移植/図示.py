"""試行80の場末累積損益を主約定と追加1秒で比較する。"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def main() -> None:
    """
    機能: 固定結果から全66場の累積損益比較図を新規保存する。
    引数: --main/--delay (Path) は集計JSON、--out (Path) は新規SVG。
    返り値: None。場内評価額は図へ混ぜず、場末実現損益だけを使う。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", required=True, type=Path)
    parser.add_argument("--delay", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("図の出力先は新規である必要がある")
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((name for name in ("Meiryo", "Yu Gothic", "Noto Sans CJK JP") if name in available), None)
    if font is None:
        raise ValueError("日本語フォントが見つからない")
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False, "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True, constrained_layout=True)
    colors = {"F0": "#777777", "P1": "#146eab", "T1": "#a94c06"}
    for ax, path, title in zip(axes, (args.main, args.delay), ("次正常原行", "追加価格時計1秒")):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["場数"] == 66
        for mode in ("F0", "P1", "T1"):
            rows = [row for row in value["場別"] if row["mode"] == mode]
            assert len(rows) == 66
            ax.plot(range(67), [0] + [row["累積損益円"] for row in rows], label=mode, color=colors[mode], linewidth=1.7)
        ticks = [1, 13, 25, 37, 49, 61, 66]
        ax.set_xticks(ticks, [rows[i - 1]["session"][5:].replace("_Day", "昼").replace("_Night", "夜") for i in ticks], rotation=35, ha="right")
        ax.axhline(0, color="#bbbbbb", linewidth=0.8)
        ax.grid(axis="y", alpha=0.2)
        ax.set_title(title)
        ax.set_xlabel("完了セッション")
        ax.legend(frameon=False)
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[0].set_ylabel("累積費用後損益（円）")
    fig.suptitle("FAR後期三手法の15分移植：100micro片側上限の研究対照")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, format="svg")
    if args.preview is not None:
        if args.preview.exists():
            raise ValueError("プレビュー出力先は新規である必要がある")
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.preview, format="png", dpi=130)
    plt.close(fig)
    print(f"比較図を保存: {args.out}")


if __name__ == "__main__":
    main()
