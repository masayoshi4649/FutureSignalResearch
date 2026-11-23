"""00009の事後診断を汎用表と全手法のMarkdownへ転記する。"""

from pathlib import Path
import importlib.util
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00009_含み益の赤字化と決済時点の診断"
SPEC = importlib.util.spec_from_file_location("診断の共通表", ROOT / "scripts/レポート/設定結果レポート.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def main() -> None:
    """固定済み診断JSONから51×9表と全33手法の結果を生成する。

    引数: なし。
    返り値: None。元の取引と集計を変更しない。
    """
    data = json.loads((STUDY / "集計.json").read_text(encoding="utf-8"))
    groups = data["手法別期間別"]
    methods = sorted({r["手法"] for r in groups})
    ids = {method: f"R{i:02d}" for i, method in enumerate(methods, 1)}
    settings = [
        {"設定ID": "S01", "手法ID": ["I04"], "尺度ID": ["m03", "m05"], "短記": "00008のRSI30/40・50復帰継承", "結果短記": "出典条件別R一覧"},
        {"設定ID": "S02", "手法ID": ["I05"], "尺度ID": ["m03", "m05"], "短記": "BB20・2/2.5σ復帰継承", "結果短記": "出典条件別R一覧"},
        {"設定ID": "S03", "手法ID": ["I08"], "尺度ID": ["m03", "m05"], "短記": "Wilder14・ADX条件継承", "結果短記": "出典条件別R一覧"},
        {"設定ID": "S04", "手法ID": ["I01", "C07"], "尺度ID": ["m03", "m05", "m15"], "短記": "自身/上位EMA20の入口文脈継承", "結果短記": "該当Rだけ・単独未評価"},
        {"設定ID": "S05", "手法ID": ["P03", "P09"], "尺度ID": ["m03"], "短記": "開始15分幅の失敗復帰継承", "結果短記": "旧対照R"},
        {"設定ID": "S06", "手法ID": ["B01", "B02"], "尺度ID": ["tick"], "短記": "保存正常BBO・全経路再走査", "結果短記": "全RのMFE/MAE診断"},
        {"設定ID": "S07", "手法ID": ["E02"], "尺度ID": ["tick"], "短記": "既存TP250/SL125の要求/返済を診断", "結果短記": "全R・新出口は未評価"},
        {"設定ID": "S08", "手法ID": ["I09"], "尺度ID": ["m03", "m05"], "短記": "元入口のWilder ATR14>0継承", "結果短記": "全R・ATR効果未評価"}]
    output = STUDY / "設定と結果.md"
    text = "# 00009：設定と結果\n\n確認日2026-11-04。新規売買の最適化ではなく、00008の保存取引の事後診断。各指標セルは出典の入口条件を継承した文脈であり、この試行で指標を加除した効果を測っていない。\n\n"
    text += "[README](README.md) / [条件](条件.json) / [全結果JSON](集計.json) / [元の全閾値](../00008_外部研究を共通尺度へ移して探索/全候補の閾値と結果.md)\n\n"
    text += "## 手法×時間スケール（共通表のコピー）\n\n51手法×9尺度を保持。未使用はこの診断で使用していない意味。独立した入口先着の再評価E01は今回未使用。\n\n"
    text += G.matrix(G.read_json(G.CATALOG), output, settings)
    text += "## 診断の閾値\n\n返済側BBOと実新規の差を使い、5/20/50/100ptに一度到達した取引を分母とする。終了純赤字は往復22円後0円未満、途中純赤字再訪は最初の到達原行より後だけ。同時計も物理原行で切る。300秒超空白がある経路を完全とは扱わない。未来峰で返せた利益や、新たな出口の回収可能益は未検証。\n\n"
    text += "## 全手法・全期間の結果\n\n各閾値セルは『終了純赤字/到達数（率）、途中純赤字再訪数』。未実行31候補の11/4を0件にしない。候補間の重複取引を独立標本として合算しない。\n"
    rows = []
    for group in groups:
        values = {r["到達pt"]: r for r in group["到達後の赤字"]}
        cells = []
        for threshold in (5, 20, 50, 100):
            row = values[threshold]
            cells.append(f"{row['最終純赤字数']}/{row['到達取引数']}（{G.pct(row['最終純赤字率'])}）<br>再訪{row['途中純赤字再訪数']}・注意{row['到達取引の経路注意数']}")
        rows.append([ids[group["手法"]], group["手法"], group["期間"], group["完結取引数"], *cells,
                     group["正粗含み益を一度も観測しない終了赤字数"], group["返済待機で純黒字から純赤字数"], group["実現純損益円"]])
    text += G.table(["評価ID", "元手法", "期間", "完結", "5pt", "20pt", "50pt", "100pt", "正益未観測赤字", "返済待機で黒→赤", "観測純額円"], rows)
    text += "## 検査と次の問い\n\n2,957完結のMFE/MAE5,914項目が保存値と一致。合成8件・独立確認1,668項目も一致。[合成](診断合成検証.json) / [独立確認](独立確認.json)。全経路の途中再訪を二重独立再計算した保証ではない。\n\n"
    text += "20pt以上の含み益から赤字になった件数だけで、20pt利確が優位とは言えない。いったん赤字へ戻ってから大きく利益化した経路と、起動前の損失を同時に評価する。[00010](../00010_順行と反転の利益保護と通常出口/計画.md)で出口を逐次再生して比較する。\n\n"
    text += G.provenance([Path(__file__), G.CATALOG, STUDY / "条件.json", STUDY / "集計.json", STUDY / "診断合成検証.json", STUDY / "独立確認.json"], output)
    output.write_text(text, encoding="utf-8")
    print("00009の全診断結果と51×9設定表を生成しました。")


if __name__ == "__main__":
    main()
