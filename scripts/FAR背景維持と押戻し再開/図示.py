# 固定87派生元SHA256: bc136b1976e0ad2cf4989452d9a26f34ff739165684b2cdca8fa5a90ae5afa20

"""88の費用後場末損益を現在資格・再開順序・約定遅延で比較する。"""

# 固定85派生元SHA256: a78d56c16ddaa925a0fadc3d4c1c8da4faa9f8907c24d962d1b991c22585c9e3

import argparse

# 派生元83のSHA256: bdac1aadd857bebe2c79e2fcffc342d39df918e167abc66a8f30f227700cf763
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def main() -> None:
    """
    機能: 主条件と追加1秒のS/E0/E1比較を新規SVGへ保存する。
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
    assert value["試行"] == 88 and value["場数"] == 66 and len(value["場別"]) == 396
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((name for name in ("Meiryo", "Yu Gothic", "Noto Sans CJK JP") if name in available), None)
    if font is None:
        raise ValueError("日本語フォントが見つからない")
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False, "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True, constrained_layout=True)
    colors = {"S": "#c17800", "E0": "#146eab", "E1": "#a63d70"}
    for delay, ax in enumerate(axes):
        for mode, color in colors.items():
            rows = [row for row in value["場別"] if row["key"] == f"{mode}_D{delay}"]
            assert len(rows) == 66
            label = f"{mode}（{value['比較'][f'{mode}_D{delay}']['完結玉']}玉）"
            ax.plot(range(67), [0] + [row["累積損益円"] for row in rows], color=color, label=label, linewidth=1.6)
        ticks = [1, 13, 25, 37, 49, 61, 66]
        ax.set_xticks(ticks, [rows[i - 1]["session"][5:].replace("_Day", "昼").replace("_Night", "夜") for i in ticks], rotation=35, ha="right")
        ax.set_title("次正常原行" if delay == 0 else "追加価格時計1秒")
        ax.set_xlabel("完了セッション")
        ax.axhline(0, color="#999999", linewidth=0.7)
        ax.grid(axis="y", alpha=0.2)
        ax.legend(frameon=False)
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[0].set_ylabel("累積費用後損益（円）")
    fig.suptitle("FAR背景維持と押戻し再開：現在資格E0・順序E1・共通G1")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, format="svg")
    if args.preview is not None:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.preview, format="png", dpi=130)
    plt.close(fig)
    print(f"比較図を保存: {args.out}")


if __name__ == "__main__":
    main()
