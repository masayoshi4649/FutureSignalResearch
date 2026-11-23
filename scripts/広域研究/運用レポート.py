"""00007の固定済み数値を、汎用表付きMarkdownへ転記する。"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00007_固定入口の単一建玉と費用感度"
SPEC = importlib.util.spec_from_file_location("運用結果の表生成", ROOT / "scripts/レポート/設定結果レポート.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def read_rows(path: Path) -> list[dict]:
    """数値正本のCSVを読む。

    引数: path (Path) はUTF-8のCSV。
    返り値: list[dict] は各行の辞書。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def yen(value: str | float) -> str:
    """円の集計値を符号付きで表示する。

    引数: value (str | float) は円額。
    返り値: str は円単位の文字列。
    """
    return f"{float(value):+,.0f}円"


def settings() -> list[dict]:
    """固定入口と逐次執行を表の設定へ対応させる。

    引数: なし。
    返り値: list[dict] は使用セルと明細の設定。
    """
    values = [
        (["P03"], ["m03"], "開始15分高安", "位置", "デイ08:45/ナイト17:00起点の3分足5本から開始15分高安を固定。初期欠枠ならその場を準備不可。幅の計測後だけ発動。15分足の指標を使う意味ではない"),
        (["P09"], ["m03"], "開始幅の外→内", "入口発動", "買：前C<幅L<=今C<=幅H、売：前C>幅H>=今C>=幅L。同場の前足と今足を使い、終値の外側からの復帰を要求。再復帰も入口要求として残す"),
        (["I08"], ["m03"], "ADX14<20", "環境", "Wilder DMI14・ADX14。前足差分14でATR/DMI初期化、DX14本でADX初期化（足28本目）。ATR0はDI0、DI和0はDX0。売買のDI優劣は要求しない"),
        (["I09"], ["m03"], "Wilder ATR14>0", "共通準備", "同限月の履歴は場をまたいで継続し、欠枠・限月変更で指標を初期化。完全3分足のみ。今足のATR14>0を要求し、利確・保護の幅はATR倍にしない"),
        (["B01", "B02"], ["tick"], "正常BBO・数量>=1", "約定の受入", "Bid>0、Ask>Bid、両最良数量>=1。価格時計非後退・原板順。買Ask新規/Bid返済、売Bid新規/Ask返済。板偏りによる方向判断は未使用"),
        (["E02"], ["tick"], "TP250/SL125・1秒待機", "保護・返済・建玉", "一建玉。新規約定価格から有利250pt・不利125ptへ線を固定。返済側気配の等号込み到達で要求し、1価格時計秒以上後の最初の正常板で成行返済。予定期限15:35/翌05:50、終端15:40/翌05:55未満。先着ラベルE01は運用判定に使わない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short,
             "結果短記": "R01〜R03", "役割": role, "明細": detail}
            for i, (methods, scales, short, role, detail) in enumerate(values, 1)]


def main() -> None:
    """保存済み結果からREADMEと設定表を生成する。

    引数: なし。
    返り値: None。条件・数値正本・固定ハッシュは変更しない。
    """
    periods = read_rows(STUDY / "期間比較.csv") + read_rows(STUDY / "追加確認/期間比較.csv")
    periods = [row for row in periods if row["期間"] in ("学習", "条件選択", "後続検査")]
    trades = read_rows(STUDY / "取引集計.csv") + read_rows(STUDY / "追加確認/取引集計.csv")
    settings_rows = settings()
    names = {"学習": "学習09/21〜10/16", "条件選択": "条件選択10/19〜10/30", "後続検査": "後続11/02〜11/03"}
    summary, handling = [], []
    for phase, label in names.items():
        rows = {int(row["片道追加滑りpt"]): row for row in periods if row["期間"] == phase}
        base = rows[0]
        own = [row for row in trades if row["期間"] == phase]
        wins = sum(float(row["基準純損益円"]) > 0 for row in own)
        summary.append([label, base["場数"], len(own), f"{wins}/{len(own)}＝{wins/len(own):.2%}",
                        *[yen(rows[cost]["観測完結取引純損益円"]) for cost in (0, 5, 10)],
                        f"{base['観測経路注意場数']}場/{base['観測経路注意取引数']}取引"])
        handling.append([label, *[base[key] for key in ("候補要求数", "新規約定数", "建玉中抑止数", "注文待機中抑止数",
                        "確認遅延不可数", "新規取消数", "終了未解消場数")]])
    result_table = G.table(["期間", "入力場数", "完結取引", "基準の黒字取引率", "R01 基準費用", "R02 片道追加5pt", "R03 片道追加10pt", "経路注意"], summary)
    handling_table = G.table(["期間", "全要求", "新規約定", "建玉中抑止", "待機中抑止", "確認遅延不可", "新規失効", "未解消場"], handling)
    common = (
        "NK225micro1枚・倍率10円/pt・呼値5ptを仮定し、NK225ラージ板で代理する。片道手数料11円（往復22円）は仮定であり、最新口座費用の確認値ではない。"
        "R01〜R03はS01〜S06の同一入口・同一約定に対する費用感度で、別々に最適化した戦略ではない。スプレッドは既にBid/Askの価格差へ含む。"
        "R02/R03は完結1取引にそれぞれ100円/200円を追加控除するだけで、約定価格・保護線・次の入口を再計算していない。\n\n"
        "新規要求は3分足を次の観測で確認した時点。確認遅延30秒以内、入口の評価期限まで60分以上。要求+1価格時計秒以上・30秒以内、15:25/翌05:40未満の最初の正常板で新規。"
        "同じ要求時計・原行の両方向は見送り、一建玉と新規待機中の追加入口は抑止。新規約定価格から有利250pt・不利125ptへ線を固定する。返済も要求後1秒以上を待ち、価格が戻っても成行要求を取り消さない。\n\n"
        "各原行では期限・失効、既存待機の約定、新たな閾値返済要求、その原行の入口の順。予定期限と新閾値が同時なら期限を優先し、既に出した返済要求は維持する。"
        "指標初期化・足の確認原行は[00006の条件](../00006_外部手法を1分3分5分で比較/条件.json)、運用詳細は[計画](計画.md)・[条件](条件.json)を参照する。\n\n"
    )
    limitations = (
        "学習の2場2取引には保有経路の300秒超空白がある。旧60場全体の観測損益は基準＋23,628円、追加5pt＋16,028円、追加10pt＋8,428円だが、"
        "全体の「確定対象純損益円」は未定義とした。注意なし58場の部分集計を全体の代用にしない。価格時計CurrentPriceTimeは受信時計ではなく、待機は通信・発注遅延の実測ではない。"
        "条件選択と新4場はこの経路注意・未解消・期限までのEOF不足が0であるが、microで同価格・同数量が実際に約定する保証にはならない。\n\n"
        "学習・条件選択は入口を選ぶために既使用。新4場は2開始日しかなく、00006と同じ標本である。二試行を独立した追試として数えない。"
        "基準の黒字取引率は損益>0の完結取引/全完結取引で、00006の「125pt逆行前250pt順行」確認率とは分母・対象・出口が異なる。"
        "後続の入口先着は5/12＝41.67%、運用の黒字取引は4/8＝50.00%。どちらも70%達成ではない。\n\n"
        "条件選択32取引は基準＋3,796円から片道追加10ptで−2,604円へ変わった。今回の結果は費用に対する余地が小さく、採用確定を支持しない。"
        "次は条件を変えず新しい日・相場環境へ適用し、入口先着率、非重複取引、費用、観測品質を並べて確認する。入口や出口の変更は新試行とする。\n\n"
    )
    validation = "[合成検証26件](合成検証結果.json)は失敗0。[旧60場の別計算](独立事例照合_探索.json)は152約定・76取引、2,488項目で不一致0。[再固定確認](再固定確認.json)では旧結果68ファイルが同一であることを確認した。\n\n"
    if (STUDY / "独立監査.json").exists():
        audit = G.read_json(STUDY / "独立監査.json")
        if not audit["全件一致"]:
            raise ValueError("独立監査に不一致があるため成功として転記しません")
        validation += f"さらに[独立監査](独立監査.json)で全64場・84取引の会計・Viewer資料・キャッシュ上の経路を照合し、{audit['照合項目数']:,}項目が一致した。原板からの前処理監査は00006を参照し、今回の独立監査の範囲・限界も区別する。\n\n"
    validation += "[運用固定](運用固定.json)に条件・コード・00006選択・入力台帳等のSHA256を保存。入口中間物はgzip生成時刻の影響を受けない展開内容SHA256を正本とする。後続結果の確認後に入口や運用条件を変更していない。\n\n"
    output = STUDY / "設定と結果.md"
    text = "# 試行00007：設定と結果\n\n記録日2026-11-04。固定入口の単一建玉・返済待機・費用感度。\n\n"
    text += "[試行README](README.md) / [計画](計画.md) / [運用固定](運用固定.json) / [汎用表](../../docs/議論/手法と時間スケールの汎用表.md)\n\n"
    text += "## 手法×時間スケール（共通表のコピー）\n\nカタログ版1、51手法×9尺度を保持。使用セルはS設定・R評価へ対応。指標単独の効果は未評価。E01は00006の入口選択元であり、本試行の売買処理では未使用。\n\n"
    text += G.matrix(G.read_json(G.CATALOG), output, settings_rows)
    text += "## 設定・閾値・役割\n" + G.table(["設定ID", "手法・尺度", "役割", "具体条件", "複合評価"], [
        [row["設定ID"], " / ".join(row["手法ID"])+"<br>"+" / ".join(row["尺度ID"]), row["役割"], row["明細"], row["結果短記"]] for row in settings_rows])
    text += "## R01〜R03の共通条件と費用\n\n" + common
    text += "## 複合評価の結果\n\n旧60場と固定後の新4場を分離する。金額は観測気配を再生した完結取引の手数料控除後で、税・証拠金・資本収益率は未評価。\n" + result_table
    text += "## 入口要求の取扱い\n" + handling_table
    text += "全期間で両方向見送り0、終了時未解消0。全要求には抑止・不成立も含む。数値正本：[旧60場](期間比較.csv) / [新4場](追加確認/期間比較.csv)。\n\n"
    text += "## 解釈と限界\n\n" + limitations + "## 検証と固定\n\n" + validation
    text += G.provenance([G.CATALOG, Path(__file__), STUDY / "計画.md", STUDY / "条件.json", STUDY / "運用固定.json",
                          STUDY / "期間比較.csv", STUDY / "取引集計.csv", STUDY / "追加確認/期間比較.csv", STUDY / "追加確認/取引集計.csv"], output)
    output.write_text(text, encoding="utf-8")

    # ----------------------------------------
    # 一覧から読む要約と、Viewerへの入口を用意する。

    text = "# 試行00007：固定入口の単一建玉と費用感度\n\n実行日2026-11-04。**新4場は8取引、仮定した手数料控除後＋4,524円。ただし条件選択期間は片道10ptの追加費用で赤字となり、入口の70%目標も未達。**\n\n"
    text += "[設定・汎用表・結果](設定と結果.md) / [計画](計画.md) / [条件](条件.json) / [固定と版](運用固定.json) / [前試行00006](../00006_外部手法を1分3分5分で比較/README.md)\n\n"
    text += "## 仮説・入力\n\n00006で固定した「3分足・開始15分高安から外へ抜けた終値の内側復帰・ADX14<20」を一建玉で扱う。重なる入口の抑止、返済の待機と費用を加えた場合にどれだけ成績が変わるかを調べる。新しい入口探索は行わない。\n\n"
    text += "NK225の旧60場（2026/09/21〜10/30）と新4場（11/02〜11/03）。原板・キャッシュは[00006の入力台帳](../00006_外部手法を1分3分5分で比較/入力台帳.json)を参照し複製しない。日付はセッション開始日。TOPIXは今回の対象外。\n\n"
    text += "## 結果\n" + result_table + "## 執行・費用の仮定\n\n" + common
    text += "## 不成立と観測品質\n" + handling_table + limitations
    text += "## 到達幅と約定幅が違う事例\n\n以下は挙動説明のために選んだ例で、代表性や期待収益の推定には使わない。全件は取引集計へ残す。\n"
    examples = [("2026-09-24_Day", "1"), ("2026-09-24_Night", "3"), ("2026-10-05_Night", "2"), ("2026-11-02_Night", "4")]
    example_rows = []
    for session, suffix in examples:
        matches = [row for row in trades if row["場"] == session and row["建玉ID"] == f"{session}_建玉{int(suffix):04d}"]
        if len(matches) != 1:
            raise ValueError(f"事例の建玉を一意に特定できない: {session} 建玉{suffix}")
        row = matches[0]
        example_rows.append([row["場"], row["建玉ID"], row["方向"], row["新規価格"], row["返済価格"], row["返済理由"], row["要求から返済秒"], yen(row["基準純損益円"]), row["観測経路注意"]])
    text += G.table(["場", "建玉ID", "方向", "新規", "返済", "理由", "要求後秒", "基準純損益", "経路注意"], example_rows)
    text += "TP250/SL125は発動線であり、利確250pt・損失125ptの実約定を約束しない。新4場の11/02ナイト建玉4は返済要求から27秒かかり、観測上は260ptの価格差となった。\n\n"
    text += "## Viewer資料と数値正本\n\n[旧60場の一覧](一覧.resources.json) / [新4場の一覧](追加確認/一覧.resources.json)。市場ルートは `../JP_OSE_Data/future`、約定は各一覧JSON基準の相対パス。Viewerの一覧JSONから開く。表示する約定は基準手数料11円のR01であり、追加費用R02/R03を混ぜない。Viewerは3分足非対応のため、入口の3分条件は設定表と照合し、原板・1分足で約定経路を点検する。\n\n"
    text += "[旧取引集計](取引集計.csv) / [新取引集計](追加確認/取引集計.csv) / [旧注文台帳](注文台帳.csv) / [新注文台帳](追加確認/注文台帳.csv) / [旧入口取扱](入口取扱.csv) / [新入口取扱](追加確認/入口取扱.csv)。未約定も捨てず、経路注意は[旧品質](品質集計.json)・[新品質](追加確認/品質集計.json)へ残す。\n\n"
    if (STUDY / "Viewer照合.json").exists():
        text += "[Viewer照合記録](Viewer照合.json)へ、起動設定・読取API・4代表場の損益と建玉・資料指紋を保存した。次の1枚は新4場で観測利益が最大だった場を表示確認用に選んだもので、典型的な成績を表す画像ではない。表示は5分足、入口条件は3分足である。\n\n"
        text += "![新4場で観測損益が最大だった2026-11-03デイのViewer表示](追加確認/図/NK225_最大観測損益場_2026-11-03_Day.png)\n\n"
    text += "## 検証・再現\n\n" + validation
    text += "Python3.14.3、NumPy2.5.3。[共通の再現手順](../../scripts/広域研究/README.md)で入力と00006入口中間物を復元後、別の作業先へ次を実行する。正式結果の上書きは拒否する。`--allow-future`は固定済み後続を指定する実行段階の確認フラグ。\n\n"
    text += "```powershell\nC:/Python314/python.exe -X utf8 scripts/広域研究/運用の合成検証.py\nC:/Python314/python.exe -X utf8 scripts/広域研究/運用検証.py --phase 探索 --output work/広域研究/再現00007/探索\nC:/Python314/python.exe -X utf8 scripts/広域研究/運用検証.py --phase 後続 --allow-future --output work/広域研究/再現00007/後続\n```\n\n"
    text += "損益の固定後に文書だけを再生成する場合は `C:/Python314/python.exe -X utf8 scripts/広域研究/運用レポート.py` を使う。[共通知見と次の問い](../../docs/議論/外部手法の検証で得た知見.md)へ結果を反映する。\n"
    (STUDY / "README.md").write_text(text, encoding="utf-8")
    print("00007のREADME・設定と結果を生成しました。")


if __name__ == "__main__":
    main()
