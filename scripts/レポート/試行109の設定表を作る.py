"""試行109の固定前の設定と24複合評価を、版6の全セルを残して記録する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "study/00109_三時間軸の取得確認と一定利益の必須保護"
OUTPUT = TRIAL / "設定と結果.md"
SPEC = importlib.util.spec_from_file_location("試行109の版6描画", ROOT / "scripts/レポート/カタログ版6.py")
CAT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAT
SPEC.loader.exec_module(CAT)
G = CAT.G


def setting(identifier: str, methods: list[str], scales: list[str], short: str,
            detail: str, results: str = "R01〜24・未検証") -> dict:
    """手法と尺度に対応する一つの設定記録を組み立てる。

    引数: identifier(str)は設定ID、methods/scales(list[str])は表のID、short/detail(str)は短記と定義、results(str)は評価参照。
    返り値: dictは共通描画へ渡す設定。実績数値を含まない。
    """
    return {"設定ID": identifier, "手法ID": methods, "尺度ID": scales,
            "短記": short, "定義": detail, "結果短記": results}


def settings() -> list[dict]:
    """元Sourceの継承、新入口、保護、診断を明示した設定を返す。

    引数: なし。
    返り値: list[dict]は市場結果前の設定一覧。未使用指標を実行済みにしない。
    """
    entry = "R13〜24・未検証"
    guard = "R05〜12/R17〜24・未検証"
    g2 = "R09〜12/R21〜24・未検証"
    rows = [
        setting("S01", ["I01"], ["m01"], "元EMA15/60・固定Source",
                "106保存Sourceの方向と遅い平均の3本変化。元閾値・公表・種を維持し、109で出生を再生成しない。具体式は11/06診断の元Source節と固定コードを参照。"),
        setting("S02", ["I09"], ["m05"], "元ATR12・取得A固定",
                "既存native ATR12のValueと幅を区別。当場最初TR=High−Low、Wilder1/12。取得Aを保護の旧幅へ使う。新入口ATR14と混ぜない。"),
        setting("S03", ["P03", "P07", "P10"], ["m01"], "元20/40分mid帯・再試験",
                "元Sourceは1分境界直前の正常BBO midを蓄える帯。20/40は窓長。ローソク終値の高安帯に置き換えない。日中/米国前/後の元条件を維持。"),
        setting("S04", ["P05"], ["tick"], "元5/15秒進行",
                "元Sourceの短秒進行・初回失速・追撃の内式を固定参照。109の5分発注時計と異なる。"),
        setting("S05", ["B02", "B03", "X01"], ["tick"], "元NK/TOPIX支持・板更新",
                "元Sourceの二市場支持、表示数量の変化、価格帯更新を保持。表示板から実約定フローを捏造せず、追加出来高gateを足さない。"),
        setting("S06", ["E02"], ["tick"], "元Source返済/取消を維持",
                "元Source損失返済と部分返済は維持。追加保護との既予約優先・正数量受理後の出生lockをActorが管理。元の実現利益は新mini建玉へ転記しない。"),
        setting("S10", ["I01", "C07"], ["m05", "m15", "m30"], "EMA8/21並び＋両傾き",
                "各軸EMA8/21はSMA初期化後EMA更新。順行Tはs*(EMA8−EMA21)>0、s*ΔEMA8>0、s*ΔEMA21>0の三軸AND。反転Rでは背景ラベルとし整列を強制しない。", entry),
        setting("S11", ["I04"], ["m05", "m15"], "RSI14・維持と回復を区別",
                "5分Tは連続2本でs*(RSI−50)>0かつs*ΔRSI>=0。Rはs*(RSI−50)>=−10かつs*ΔRSI>0。15分Tは50側/同値、Rは方向差>=0。Wilder14、両変化0=50、損失0=100。", entry),
        setting("S12", ["I03", "C01"], ["m05", "m15"], "MACD12/26/9・hist増分",
                "5分は連続2本s*Δhist>0、15分はs*Δhist>=0。EMA/RSI/価格構造と複合し、独立した統計票として加算しない。", entry),
        setting("S13", ["P01", "P03", "P08"], ["m15"], "事前15分risk端と押戻し",
                "試験5分足Startよりstrict前に公表済みの最新15分OHLC。買いrisk=Low/売りrisk=Highを固定。Tは逆/同値実体又は速EMA接触、固定端を5分高安が失わない。15分pivot必須にしない。", entry),
        setting("S14", ["P02", "P07", "P10"], ["m05"], "事前pivot突破/別足再試験",
                "左右2足。左strict・右ties。試験Startよりstrict前に確認済みのPriorPivotのみ。Tは終値突破又は後続別5分足で接触し保持、終値喪失で失効。setup期限1800秒、同線即再作成なし。", entry),
        setting("S15", ["P04", "P09"], ["m05", "m15"], "旧方向失敗→復帰→突破",
                "Rは固定15分risk端の旧方向試験→後続5分終値復帰→さらに後続5分の事前pivot突破。失敗端の再更新/復帰後喪失で失効。15/30整合と局所反転を事前ラベル化。", entry),
        setting("S16", ["I09"], ["m05"], "ATR14・距離≤1ATR/複合spike",
                "当時取得側BBOと固定線のs距離は0<距離<=ATR14。直近2本でTR>2*前ATRかつs*ΔRSI>20なら警戒待機。TRのみ又は高RSIのみで警戒にしない。ATRはSMA14→Wilder。", entry),
        setting("S17", ["V01"], ["m05", "m15", "m30"], "量の既知/未知・診断のみ",
                "全子がvolume_completeの場合だけ合計を既知とする。不完全をゼロ量とせず、今回の入口ANDや枚数変更には使わない。", "診断・単独効果未検証"),
        setting("S18", ["I03", "I04"], ["m30"], "数値形成/既知性のみ",
                "30分MACD/RSIも形成するが入口の選別には使わない。30分はEMA方向/両傾きによる背景。", "診断・売買選別なし"),
        setting("S19", ["I09"], ["m15", "m30"], "ATR14・正規化/既知性",
                "EMA/前値と共にATR14の既知を共通可用性に要求する。三軸方向差のATR正規化を監査し、追加の正規化数値閾値は課さない。価格既知と履歴不足を区別。", entry),
        setting("S20", ["I01"], ["m03"], "保護C=絶対間隔3本縮小",
                "既存3分EMA8/21間隔が新しい確定3本でstrict連続縮小。同値/未知は成立にしない。", g2),
        setting("S21", ["I03"], ["m03"], "保護M=s*Δhist<0",
                "既存3分MACD12/26/9の方向差が負。G2はM AND (C OR P)で狭幅を起動し、解除で幅を拡大しない。", g2),
        setting("S22", ["P02", "P07"], ["m03"], "事前pivot否定Pと構造床",
                "当足登録前の既知pivotを使う。P=s*(Close−prior線)<0。構造床はG2かつその時点の警戒真、中心足Start>=新規時刻、実確認/公表後だけ。買priorLow−5/売priorHigh＋5の粗床が最低床を超える場合に採用。狭幅旗の継続だけで追加しない。", g2),
        setting("S23", ["I15"], ["m03"], "V=max(5,直近5本H−L中央値)",
                "連続確定3分足5本だけ。欠足/価格未知で窓reset、当場外を持ち込まない。G1/G2起動Hの新規時Vを固定し、G2幅の当時Vに使う。TR中央値やATRと区別。", guard),
        setting("S24", ["I04", "I05", "I08", "I09"], ["m03"], "旧Bank形成/既知性のみ",
                "保存公表の数値として保持されるが、RSI/BB/ADX/独立ATR14を新保護の選別や旧Aへ使わない。", "診断・追加選別なし"),
        setting("S25", ["I01", "I03", "I04", "I05", "I08", "I09"], ["m15"], "旧15分Bankも別に保持",
                "既存3/15分Bankの15分は出典と既知性の監査。S10等の新CSV由来15分とは同名でも系列/形成/公表が別で、二重配送しない。", "旧Bank診断・追加選別なし"),
        setting("K01", ["B01"], ["tick"], "正常BBO・strict後原行fill",
                "mini各側上限10枚・可変、100円/pt、38.5円/片道。C0はlarge BBO、C5はさらに5pt/片道。D1は価格時計1秒仮定。同原行fill禁止・実mini板の流動性は未証明。"),
        setting("K02", ["C06", "E02"], ["tick"], "G0=旧1A起動/2A幅",
                "旧108Q0の起動u>=100*max(10,A)、幅ceil5(2A)、最低建値。entry_E0_G0のBook/Width/Clock全JSONを旧108の4費用と一致させる。", "R01〜04/R13〜16・未検証"),
        setting("K03", ["C06", "E02"], ["tick"], "G1/G2=一定利益必須起動",
                "K=.77+2S、H=ceil5(max(20,2K,.25V_entry))、V不明時ceil5(max(20,2K))。1枚費用後u>=100Hで警戒不要の必須起動。最低粗床ceil5(K+5)、以前床から不利に緩めない。", guard),
        setting("K04", ["C06", "E02"], ["tick"], "G2=VとC/M/Pで可変追尾",
                "通常ceil5(max(15,min(2A,2V)))、警戒時ceil5(max(10,min(A,V)))。未知fallbackは純仕様参照。max(既存床,費用床,peak−width,S22条件を満たす構造床)。狭幅はlatched、構造床の追加は現在警戒真が必要。発注/約定gap損失は保証せず実測。", g2),
    ]
    return rows


def render() -> str:
    """市場損益を作らず設定明細と24の未実行評価欄を生成する。

    引数: なし。
    返り値: strは版6の全56行9尺度と設定・評価・出典を含むMarkdown。
    """
    catalog = CAT.load_catalog()
    rows = settings()
    method_ids = {r["id"] for r in catalog["methods"]}
    scale_ids = {r["id"] for r in catalog["scales"]}
    assert len({r["設定ID"] for r in rows}) == len(rows)
    assert all(set(r["手法ID"]) <= method_ids and set(r["尺度ID"]) <= scale_ids for r in rows)
    config = json.loads((TRIAL / "研究条件案.json").read_text(encoding="utf-8"))
    assert len(config["configs"]) == 24
    text = "# 00109：設定と結果\n\n2026-11-09。市場結果前の設定記入。人工検査済みの部品があるが、新しい市場損益は未計算、採用・目標達成は未確認。金融条件の固定記録とは分ける。\n\n"
    text += "[研究計画](README.md) / [汎用表・版6](../../docs/議論/手法と時間スケールの汎用表_版6.md) / [11/06診断](../../docs/議論/11月06日の赤字を入口と利益保護から診断する.md)\n\n"
    text += "## 手法×時間スケール\n\n版6、56手法×9尺度＝504セルを保持。未使用は今回の不使用であり無効という結論ではない。旧Source継承、新入口、診断のみを区別する。複合成績を単独指標の効果にしない。\n\n"
    matrix = CAT.matrix(catalog, OUTPUT, rows)
    lines = matrix.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("| X04 |") or line.startswith("| E01 |"):
            cells = line.split(" | ")
            cells[2] = "データ不足（mini実板なし）" if line.startswith("| X04 |") else "対象外（旧先着合否は保留）"
            lines[i] = " | ".join(cells)
    text += "\n".join(lines)+"\n"
    text += "## 設定明細\n\n全て売りは買いの符号反転。s=買い+1/売り−1、ceil5は5pt単位の切上げ。期間は本数、尺度は足幅。EMA8/21と5/15/30分は別概念。\n\n"
    text += G.table(["設定ID", "手法ID・尺度", "短い定義", "計算・閾値・役割", "評価・実行状態"],
                    [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["定義"], r["結果短記"]] for r in rows])
    text += "## 時計・入力・取得・参加の共通条件\n\n"
    text += "5分strict次枠、開始/米国開始20分静観と静観明け一回繰越。元Source出生の方向/数量を追加入口が作り直さず、一出生一取得。5/15/30は同限月数値carry、当場公表maskとpivotはreset、欠足は該当系列をreset。新入口の公表は足終+60秒をRecord.Atで配送する仮定`csv_end_plus60_at_record_scheduler`で、実受信時計ではない。EOF/Sealedを入口政策値から除き、未完末尾を確定しない。\n\n"
    text += "実参加は同枠の新規fill又は実保有。主分母は[Start+1200,ForceClose)の7,980枠。元手法のForceClose=End−600（デイ15:35/ナイト05:50）を維持し、末尾10分を除く。副分母は[Start+1200,End−1800)の7,700枠。予定Endまでの8,120枠とは異なる。US静観・未知・欠測・EOF前の未観測枠も所定分母に残す。最低25%/目標50%。技術成立頻度は金融適格性や実参加率と別である。未参加・退出後の仮想利益は計算しない。\n\n"
    text += "## 24複合評価\n\nG0/G1/G2とentry_E0/E1を分ける。各Rは既使用70場での探索比較であり、独立な24組の実証ではない。4費用はC0/C5×D0/D1。金額・回数・参加率は金融と保存検査の完了後に追記し、未実行を0円や成功としない。\n\n"
    evaluations = []
    for i, c in enumerate(config["configs"], 1):
        evaluations.append([f"R{i:02}", c["candidate"], f"C{c['slip_pts']}/D{c['delay_seconds']}",
                            "S01〜06・K01＋該当入口/保護設定", "既使用70場予定", "未検証", "未検証", "未検証"])
    text += G.table(["評価ID", "入口/保護", "費用", "構成", "分母", "費用後純額", "利益後赤字/DD", "実参加"], evaluations)
    text += "## 再現と出典\n\n設定の詳細は純仕様・停止物を金融条件で指紋固定する。現在の表は固定前の記入版。\n\n"
    paths = [ROOT / "scripts/レポート/手法カタログ_版6.json", TRIAL / "研究条件案.json",
             ROOT / "work/三時間軸の入口判定/README.md", ROOT / "work/三時間軸の入口判定/仕様.json",
             ROOT / "work/三時間軸の公開器/停止.json", ROOT / "work/一定利益と三時間軸の保護会計/停止.json",
             ROOT / "scripts/レポート/試行109の設定表を作る.py"]
    text += G.provenance(paths, OUTPUT)
    text += "\n```powershell\nC:/Python314/python.exe -X utf8 scripts/レポート/試行109の設定表を作る.py\nC:/Python314/python.exe -X utf8 scripts/レポート/試行109の設定表を作る.py --check\n```\n"
    return text


def main() -> None:
    """109の設定記入表だけを生成又は照合する。

    引数: なし。CLIは--checkを受け付ける。
    返り値: None。金融実行や市場本文読取は行わない。
    """
    parser = argparse.ArgumentParser(description="109の56手法×9尺度と24設定")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if (TRIAL / "金融条件.json").exists() and not args.check:
        raise ValueError("金融固定後は実行前の表を上書きせず、結果を追記してください")
    value = render()
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != value:
            raise ValueError("109設定表と生成定義に差があります")
    else:
        OUTPUT.write_text(value, encoding="utf-8")
    print("109の56手法・9尺度・24複合評価を確認しました")


if __name__ == "__main__":
    main()
