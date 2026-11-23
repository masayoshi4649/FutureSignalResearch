"""81の費用後場末損益を入口・保護・約定遅延で比較する。"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def main() -> None:
    """
    機能: 主条件と追加1秒の4政策比較を新規SVGへ保存する。
    引数: --result/--out (Path)、--preview (Path|None) は正本・図・作業用PNG。
    返り値: None。場内評価を場末損益へ混ぜず、画像を複製しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.preview is not None and args.preview.exists():
        raise FileExistsError("図の既存出力を変更しません")
    value = json.loads(args.result.read_text(encoding="utf-8"))
    assert value["場数"] == 66 and len(value["場別"]) == 528
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((name for name in ("Meiryo", "Yu Gothic", "Noto Sans CJK JP") if name in available), None)
    if font is None:
        raise ValueError("日本語フォントが見つからない")
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False, "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True, constrained_layout=True)
    colors = {"B0G0": "#b43a36", "B0G1": "#c17800", "B1G0": "#146eab", "B1G1": "#36864e"}
    for delay, ax in enumerate(axes):
        for mode, color in colors.items():
            rows = [row for row in value["場別"] if row["key"] == f"{mode}_D{delay}"]
            assert len(rows) == 66
            ax.plot(range(67), [0] + [row["累積損益円"] for row in rows], color=color, label=mode, linewidth=1.6)
        ticks = [1, 13, 25, 37, 49, 61, 66]
        ax.set_xticks(ticks, [rows[i - 1]["session"][5:].replace("_Day", "昼").replace("_Night", "夜") for i in ticks], rotation=35, ha="right")
        ax.set_title("次正常原行" if delay == 0 else "追加価格時計1秒")
        ax.set_xlabel("完了セッション")
        ax.axhline(0, color="#999999", linewidth=0.7)
        ax.grid(axis="y", alpha=0.2)
        ax.legend(frameon=False)
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[0].set_ylabel("累積費用後損益（円）")
    fig.suptitle("定時の現在根拠と部分利益保護：各新規100micro固定")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, format="svg")
    if args.preview is not None:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.preview, format="png", dpi=130)
    plt.close(fig)
    print(f"比較図を保存: {args.out}")


if __name__ == "__main__":
    main()
