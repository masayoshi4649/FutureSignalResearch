"""00010の固定条件と保存集約から、通常出口比較の3文書を再生成する。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00010_順行と反転の利益保護と通常出口"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}
EXIT_NAMES = {"X00": "固定TP/SL", "X01": "20→10pt床", "X02": "50→20pt床",
              "X03": "1ATR起動・1ATR追尾", "X04": "役割別通常出口", "X05": "通常出口＋50→20pt床"}


def shared() -> Any:
    """共通カタログ生成器の表示関数だけを読み込む。

    引数: なし。
    返り値: Any はmatrix・リンク・表・SHAを持つモジュール。
    """
    spec = importlib.util.spec_from_file_location("利益回収の帳票共通", ROOT / "scripts/レポート/設定結果レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = shared()


def optional(path: Path) -> dict | None:
    """保存済みJSONだけを読み、未保存を合格と扱わない。

    引数: path (Path) はJSON。
    返り値: dict | None は保存値または未保存。
    """
    return G.read_json(path) if path.exists() else None


def number(value: object) -> str:
    """欠測とゼロを区別して数値を表示する。

    引数: value (object) は数値または欠測。
    返り値: str は桁区切りの数値。欠測は未算出。
    """
    if value is None:
        return "未算出"
    numeric = float(value)
    return f"{numeric:,.0f}" if numeric.is_integer() else f"{numeric:,.2f}"


def definitions(config: dict) -> list[dict]:
    """条件JSONの固定順で18評価IDを付ける。

    引数: config (dict) は3入口と6出口の固定定義。
    返り値: list[dict] はR01からR18の候補。順位を付け直さない。
    """
    if [r["入口ID"] for r in config["入口"]] != ["T01", "R01", "R02"] or [r["出口ID"] for r in config["出口"]] != list(EXIT_NAMES):
        raise ValueError("固定した3入口×6出口と異なります")
    rows = [{"候補ID": source["入口ID"] + "_" + policy["出口ID"], "入口": source, "出口": policy}
            for source in config["入口"] for policy in config["出口"]]
    for index, row in enumerate(rows, 1):
        row["評価ID"] = f"R{index:02d}"
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> dict[str, dict]:
    """保存集約の定義・会計・表示用固定集合を独立に照合する。

    引数: config/report (dict) は条件・結果、rules (list[dict]) は固定18定義。
    返り値: dict[str,dict] は候補ID別の保存結果。不整合はValueError。
    """
    if config.get("全65場既使用") is not True or report.get("全65場既使用") is not True or report.get("入口125250評価の変更") is not False:
        raise ValueError("既使用範囲または入口評価の状態が異なります")
    values = {row["候補ID"]: row for row in report["結果"]}
    expected = {row["候補ID"]: row for row in rules}
    if len(values) != 18 or len(report["結果"]) != 18 or values.keys() != expected.keys():
        raise ValueError("結果の候補集合が固定18候補と一致しません")
    for cid, row in values.items():
        if row["入口"] != expected[cid]["入口"] or row["出口"] != expected[cid]["出口"]:
            raise ValueError("保存結果の入口・出口定義が条件と不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            item = row[period]
            count = item["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"] + item["無取引場数"] != sessions:
                raise ValueError("入力場数と活動・無取引が不一致")
            if item["買い取引数"] + item["売り取引数"] != count or not 0 <= item["黒字取引数"] <= count:
                raise ValueError("取引数と売買・黒字件数が不一致")
            for slip in (0, 5, 10):
                net = item[f"追加{slip}pt純損益円"]
                target = item["追加0pt純損益円"] - 2 * slip * config["運用"]["倍率"] * count
                if not math.isclose(net, target, abs_tol=1e-8):
                    raise ValueError("費用感度の往復控除が不一致")
                average = item[f"追加{slip}pt平均円"]
                if (average is None) != (count == 0) or count and not math.isclose(average, net/count, abs_tol=1e-8):
                    raise ValueError("平均額と分母が不一致")
            previous = count
            for threshold in (20, 50, 100):
                reached, red = item[f"{threshold}pt到達取引"], item[f"{threshold}pt後純赤字"]
                if not 0 <= red <= reached <= previous:
                    raise ValueError("順行到達・赤字化件数が不一致")
                previous = reached
            base = values[row["入口"]["入口ID"] + "_X00"][period]
            pair = item["共通新規比較"]
            if pair["共通実新規"] + pair["元のみ新規"] != base["完結取引数"] or pair["共通実新規"] + pair["変更のみ新規"] != count:
                raise ValueError("共通実新規と集合差が不一致")
            if cid.endswith("_X00") and any(pair[k] for k in ("元のみ新規", "変更のみ新規", "共通新規の純損益差円", "元赤字から黒字", "元黒字から赤字", "元黒字を早く確定した純額差円")):
                raise ValueError("X00自己比較がゼロでありません")
            if item["利益床使用"]:
                if item["床未起動取引数"] + item["床起動取引数"] != count or not 0 <= item["床未起動赤字取引数"] <= item["床未起動取引数"]:
                    raise ValueError("床起動と未起動の件数が不一致")
                if not math.isclose(item["床未起動純損益円"] + item["床起動済純損益円"], item["追加0pt純損益円"], abs_tol=1e-8):
                    raise ValueError("床起動状態の損益合計が不一致")
            if item["期間内最大場内DD円"] < 0:
                raise ValueError("場内DDが負です")
    fixed = []
    for source in config["入口"]:
        candidates = [r for r in values.values() if r["入口"]["入口ID"] == source["入口ID"]]
        ranked = sorted(candidates, key=representative_key)
        fixed.extend((source["入口ID"] + "_X00", ranked[0]["候補ID"]))
    if report["表示固定ID"] != list(dict.fromkeys(fixed)):
        raise ValueError("旧二期間だけによる表示代表と保存IDが不一致")
    if report["費用資格数"] != sum(bool(r["費用資格"]) for r in values.values()):
        raise ValueError("費用資格数が不一致")
    return values


def representative_key(row: dict) -> tuple:
    """表示用代表の既定順位を確認し、新1場を順位に使わない。

    引数: row (dict) は一候補の保存集約。
    返り値: tuple は旧二期間の追加5pt平均の最小側を優先する昇順キー。
    """
    worst = min(row[p]["追加5pt平均円"] if row[p]["追加5pt平均円"] is not None else -math.inf for p in PERIODS[:2])
    return -worst, row["候補ID"]


# ----------------------------------------
# 条件と実際に用いた尺度を対応させ、計算しただけの指標へ成績を帰属しない。

def settings(rules: list[dict]) -> list[dict]:
    """使用した手法と尺度だけへ設定ID・R参照を置く。

    引数: rules (list[dict]) は全18定義。
    返り値: list[dict] は共通51×9表へ渡す設定。
    """
    result = []
    groups = []
    for size in (3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        scale = [f"m{size:02d}"]
        groups += [
            (["I04"], scale, [r for r in same if r["入口"]["入口ID"] != "R01"], "RSI14回復・再加速", "T01：前RSI≤50<今RSI、直前3本すべて有効かつRSI≤40あり。R02：前RSI≤40<今RSI。売りは100−RSI"),
            (["I09"], scale, same, "ATR14>0・入口準備", "Wilder14。共通準備。X03だけ入口判断時ATR_eを固定して起動・追尾へ使用"),
            (["P05"], scale, [r for r in same if r["入口"]["入口ID"] != "R01"], "今C>前C", "T01/R02の価格改善。売りは今C<前C。ローソク形状の独立効果ではない"),
            (["I01"], scale, [r for r in same if r["入口"]["役割"] == "反転" and r["出口"]["出口ID"] in ("X04", "X05")], "入口時SMA20・固定目標", "BB20中心のSMA20だけを入口判断時点で固定。BB幅・帯接触の発動は未使用。有利側でない目標は無効記録"),
            (["P02"], scale, [r for r in same if r["入口"]["役割"] == "反転" and r["出口"]["出口ID"] in ("X04", "X05")], "入口足L−5/H＋5の失効", "入口判断足の買い安値−5pt/売り高値＋5ptを固定。保有後の確定終値が厳密に越えたら通常返済要求"),
            (["I09", "C06"], scale, [r for r in same if r["出口"]["出口ID"] == "X03"], "1ATR_e起動・1ATR_e追尾", "返済側気配のMFE≥ATR_eで起動。入口時ATR14固定、観測最高/最低返済気配から1ATR_e。買max/売min、5pt刻みへ買下丸め/売上丸め。原典Chandelierの再現ではない"),
        ]
    trend = [r for r in rules if r["入口"]["入口ID"] == "T01"]
    reverse_range = [r for r in rules if r["入口"]["入口ID"] == "R01"]
    groups += [
        (["I01"], ["m03"], trend, "今C>EMA20", "T01入口の終値位置。X04/X05では保有後の確定3分終値がEMA20の厳密な反対側で通常出口。等号だけは発動なし"),
        (["I01"], ["m15"], trend, "C15>EMA20>前EMA20", "準備済みで利用可能な最後の確定15分方向と整合。未確定足・未来の確認原行を使わない"),
        (["C07"], ["m03", "m15"], trend, "3分発動＋確定15分方向", "T01だけに使用。R01の開始15分は計算窓であり15分足の使用ではない"),
        (["I08"], ["m03"], reverse_range, "ADX14<20", "R01の低方向性条件。DI交差を入口に使わない"),
        (["P03", "P04"], ["m03"], reverse_range, "開始15分高安の失敗復帰", "前終値が開始15分幅の外、今終値が幅内へ復帰。買いは前C<下端≤今C≤上端、売りは対称"),
        (["B01"], ["tick"], rules, "ラージBBO・micro1枚代理", "買Ask/売Bid新規、買Bid/売Ask返済。要求+1価格時計秒以降。価格時計は受信時計ではない"),
        (["E02"], ["tick"], rules, "TP250/SL125・期限＋X00〜05", "全候補で固定TP250/SL125維持。X01は20→10床、X02/X05は50→20床、X03は固定ATR追尾、X04/X05は役割別通常出口。ソフト監視の返済要求で実逆指値の受付再現ではない"),
    ]
    for methods, scales, applies, short, detail in groups:
        if applies:
            refs = [r["評価ID"] for r in applies]
            result.append({"設定ID": f"S{len(result)+1:02d}", "手法ID": methods, "尺度ID": scales,
                           "短記": short, "結果短記": "・".join(refs), "説明": detail, "適用評価": refs})
    return result


def tables(rows: list[dict], values: dict[str, dict], refs: dict[str, str]) -> str:
    """期間別の損益・赤字化・床・対応新規を別表へ写す。

    引数: rows (list[dict]) は表示候補、values (dict[str,dict]) は全保存値、refs (dict[str,str]) はR対応。
    返り値: str は欠測と品質を保持するMarkdown。
    """
    operations, mfe, floors, pairs = [], [], [], []
    for row in rows:
        for period in PERIODS:
            item = row[period]
            count = item["完結取引数"]
            prefix = [refs[row["候補ID"]], PERIOD_NAMES[period]]
            operations.append(prefix + [count, f"{item['黒字取引数']}/{count}・{G.pct(item['黒字取引数']/count if count else None)}",
                f"{item['買い取引数']}/{item['売り取引数']}", f"{item['活動場数']}/{item['入力場数']}", item["無取引場数"],
                *[number(item[f"追加{s}pt純損益円"]) for s in (0, 5, 10)],
                "未確定" if item["追加0pt確定対象円"] is None else number(item["追加0pt確定対象円"]),
                f"{item['品質注意場数']}/{item['EOF期限未達場数']}/{item['未解消場数']}", number(item["期間内最大場内DD円"]),
                G.pct(item["活動場赤字率"])])
            mfe.append(prefix + [f"{item[f'{n}pt後純赤字']}/{item[f'{n}pt到達取引']}・{G.pct(item[f'{n}pt後純赤字']/item[f'{n}pt到達取引'] if item[f'{n}pt到達取引'] else None)}" for n in (20, 50, 100)])
            floor_values = [number(item[k]) if item["利益床使用"] else "対象外" for k in
                            ("床未起動取引数", "床未起動赤字取引数", "床未起動純損益円", "床起動済純損益円")]
            floors.append(prefix + ["あり" if item["利益床使用"] else "なし", item["床起動取引数"],
                *floor_values, item["中心目標無効"], number(item["最悪場内時価円"])])
            base = values[row["入口"]["入口ID"] + "_X00"][period]
            pair = item["共通新規比較"]
            total_difference = item["追加0pt純損益円"] - base["追加0pt純損益円"]
            pairs.append(prefix + [number(total_difference), pair["共通実新規"], pair["元のみ新規"], pair["変更のみ新規"],
                number(pair["共通新規の純損益差円"]), number(total_difference-pair["共通新規の純損益差円"]),
                pair["元赤字から黒字"], pair["元黒字から赤字"], number(pair["元黒字を早く確定した純額差円"])])
    text = "### 運用と費用\n\n金額は円。黒字は追加0ptの完結取引純損益>0。場内DDは期間中で最大だった一場の含み込みDDで、全期間をつないだDDではない。\n"
    text += G.table(["評価", "期間", "完結", "黒字/全取引・率", "買/売", "活動/入力場", "無取引場", "追加0pt", "追加5pt", "追加10pt", "0pt確定対象", "注意/EOF/未解消場", "最大場内DD", "活動場赤字率"], operations)
    text += "### 順行を観測した後の赤字化\n\nセルは『基準純赤字取引/そのMFEへ到達した取引・率』。MFEは実新規から実返済までの返済側正常気配。早期返済では観測窓も短くなるため、同じ将来経路の比較ではない。\n"
    text += G.table(["評価", "期間", "MFE20pt後赤字", "MFE50pt後赤字", "MFE100pt後赤字"], mfe)
    text += "### 床の起動と初期段階の損益\n\n未起動部分は初期SL損失だけではなく、床が起動する前のTP・通常出口・期限等も含む。床なしは対象外であり、未起動損益をゼロとしない。ATR追尾の起動は固定pt利益床の起動に含まれない。\n"
    text += G.table(["評価", "期間", "固定pt床", "床起動取引", "未起動取引", "未起動赤字取引", "未起動純額", "起動済純額", "中心目標無効", "最悪場内時価"], floors)
    text += "### 同じ実新規の出口差と、新規集合の差\n\n基準は同じ入口のX00。共通実新規は入口イベント・新規時計・原行・価格が全て同じ完結取引。集合差の純額は『変更のみ取引の純額−元のみ取引の純額』に相当する差分で、全体差−共通新規差。0pt純額を比較し、未解消があれば全新規集合を網羅した差とはしない。\n"
    text += G.table(["評価", "期間", "全純額差", "共通新規", "元のみ", "変更のみ", "共通新規純額差", "集合差純額", "元赤字→黒字", "元黒字→赤字", "元黒字だった共通新規の純額差"], pairs)
    return text


def findings(values: dict[str, dict]) -> str:
    """固定した説明対象から、利益消失と損益改善の違いを記す。

    引数: values (dict[str,dict]) は全18候補の保存集約。
    返り値: str は探索の数値に限定した所見。追加候補の選定や一般化はしない。
    """
    floor = values["R01_X01"]["条件選択"]
    base = values["R01_X00"]["条件選択"]
    pair = floor["共通新規比較"]
    total = floor["追加0pt純損益円"] - base["追加0pt純損益円"]
    text = "## この比較で確認したこと\n\n"
    text += (f"R01の20→10pt床は条件選択で黒字{floor['黒字取引数']}/{floor['完結取引数']}="
             f"{G.pct(floor['黒字取引数']/floor['完結取引数'] if floor['完結取引数'] else None)}だったが、"
             f"基準純損益は{number(floor['追加0pt純損益円'])}円、追加5pt後は{number(floor['追加5pt純損益円'])}円。"
             "黒字取引率70%超は入口の125/250pt先着率70%ではなく、利益の大きさと損失・費用を無視した採用根拠にしない。\n\n")
    text += (f"同じR01_X00との共通実新規{pair['共通実新規']}件では、赤字→黒字を{pair['元赤字から黒字']}件救い、"
             f"黒字→赤字が{pair['元黒字から赤字']}件あった。一方、元が黒字だった共通新規の純額は合計"
             f"{number(pair['元黒字を早く確定した純額差円'])}円変化し、共通新規全体の純額差は"
             f"{number(pair['共通新規の純損益差円'])}円だった。元のみ{pair['元のみ新規']}件・変更のみ"
             f"{pair['変更のみ新規']}件も生じ、全体差{number(total)}円のうち集合差の純額は"
             f"{number(total-pair['共通新規の純損益差円'])}円。救済件数が増えても、元の大きな黒字の取り分と"
             "追加参加の結果を合わせると純損益が悪化した、というこの条件の観測である。\n\n")
    text += (f"同床の未起動{floor['床未起動取引数']}件は純額{number(floor['床未起動純損益円'])}円、"
             f"起動済{floor['床起動取引数']}件は{number(floor['床起動済純損益円'])}円だった。"
             "床を起動する前の損失は、起動後の小幅利益だけでは埋まらなかった。未起動損益は初期SLだけの内訳ではない。"
             "また追加費用は取引数に比例するため、同じ入口でも早期返済による再参加増加を含めて確認する。\n\n")
    rows = []
    for period in PERIODS[:2]:
        changed, original = values["R02_X04"][period], values["R02_X00"][period]
        shared = changed["共通新規比較"]["共通新規の純損益差円"]
        difference = changed["追加0pt純損益円"]-original["追加0pt純損益円"]
        rows.append([PERIOD_NAMES[period], number(difference), number(shared), number(difference-shared),
                     number(changed["追加5pt純損益円"]-original["追加5pt純損益円"])])
    text += "反転RSI入口R02の通常出口X04も、学習と条件選択で改善の符号が異なった。学習の全純額改善を、同じ実新規の出口だけによる改善とはしない。\n"
    text += G.table(["期間", "R02_X00からの全純額差", "共通新規差", "新規集合差純額", "追加5pt後の全差"], rows)
    return text + "利益床・ATR追尾・通常出口の一般的な否定ではなく、固定18候補とこの既使用65場の結果である。品質注意を事後に除いた部分を全体の代用にせず、表示代表と費用資格の未達を区別する。\n\n"


def audit_section(study: Path, output: Path) -> tuple[str, list[Path]]:
    """保存された明示合否だけを検査状態として表示する。

    引数: study/output (Path) は試行と出力Markdown。
    返り値: tuple[str,list[Path]] は状態表と実在する出典。
    """
    rows, sources = [], []
    for name, label in (("合成検証.json", "合成検証"), ("独立監査.json", "独立監査"), ("Viewer照合.json", "Viewer照合")):
        path = study / name
        value = optional(path)
        if value is None:
            rows.append([label, "未完・結果未保存", "未算出", "なし"])
            continue
        sources.append(path)
        verdict = value.get("全件成功") if label == "合成検証" else value.get("全件一致")
        count = value.get("検証件数", value.get("照合項目数"))
        if label == "Viewer照合" and verdict is None:
            checks = value.get("照合", [])
            verdict = all(r.get("一致") is True for r in checks) if checks else None
            count = len(checks)
        state = "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示判定未確認"
        rows.append([label, state, number(count), G.link(path, output)])
    return "## 検査の状態\n\n集約数値の生成と独立監査は別状態。未保存の独立監査を合格としない。\n" + G.table(["範囲", "状態", "項目数", "正本"], rows), sources


# ----------------------------------------
# 原板・詳細約定の再読や候補の追加を行わず、正式数値JSONの説明を作る。

def run(study: Path, output: Path) -> list[Path]:
    """固定条件と数値JSONから正式3MDを作る。

    引数: study/output (Path) は入力試行と表示先。
    返り値: list[Path] は出力した3文書。結果未保存なら例外で停止する。
    """
    config, report = G.read_json(study / "条件.json"), G.read_json(study / "結果.json")
    fixed = G.read_json(study / "固定.json")
    if fixed["条件SHA256"] != G.sha(study / "条件.json"):
        raise ValueError("固定時の条件SHA256が変わっています")
    rules = definitions(config)
    values = validate(config, report, rules)
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    catalog = G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("汎用表の51×9構成が変わっています")
    pointer = G.read_json(study / "入力台帳.json")
    manifest_path = (study / pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("参照入力台帳のSHA256が変わっています")
    manifest = G.read_json(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output / name for name in ("README.md", "設定と結果.md", "全候補結果.md")]
    status = "全18候補の集約保存済み。全65場は既使用で、採用確定の未見検証ではない。"
    intro = "NK225、3入口×6出口＝18候補。学習40場・条件選択24場・既使用11/4デイ1場を別掲する。内部キー『後続検査』も、この試行では既使用11/4デイを意味する。入口125/250ptの先着評価は変更せず、小利確の黒字取引率を入口70%目標の達成としない。\n\n"
    limits = "ラージBBOによるmicro1枚代理、倍率10円/pt、片道11円は比較用の費用仮定。新規/返済は要求+1価格時計秒以上、追加片道5/10ptは同一完結往復へ100/200円を控除する感度であり、発動価格や再参加を動かした再計算ではない。CurrentPriceTimeは受信時計ではなく、1秒は実通信遅延の実測値ではない。観測品質注意・EOF・未解消を含む全体を確定収益とは呼ばない。\n\n"
    source_rows = [[s["入口ID"], s["役割"], s["候補ID"], s["時間足分"]] for s in config["入口"]]
    exit_rows = [[p["出口ID"], EXIT_NAMES[p["出口ID"]], G.describe(p)] for p in config["出口"]]
    definition = "## 固定した入口と出口\n" + G.table(["入口", "役割", "元入口ID", "足分"], source_rows) + G.table(["出口", "名称", "保存設定"], exit_rows)
    definition += "全出口でTP250/SL125と期限を維持。T01のX04/X05は保有後に公開された確定3分終値のEMA20反対側で通常出口。R01/R02のX04/X05は入口判断時SMA20の有利側目標と、入口判断足の買L−5/売H＋5の確定終値による構造失効。目標が有利側でなければ無効を記録し、遠くへ移さない。通常足の確認遅延>30秒、入口を作った足、未確定足は使わない。\n\n"
    definition += "X03は入口判断時Wilder ATR14を固定し、返済側MFE≥1ATR_e後に最高/最低返済気配から1ATR_eを離し、買max/売minで緩めない。5pt刻みへ買下丸め・売上丸め。原典の日足Chandelierとは別仕様。追加出口はソフト監視の返済要求であり、実際の逆指値訂正の受付遅延を再現しない。床や目標の値で即返済したと扱わない。\n\n"
    fixed_ids = report["表示固定ID"]
    display_rows = [values[cid] for cid in fixed_ids]
    fixed_text = "## 表示用代表と採否\n\n各入口X00と、旧学習/条件選択の追加5pt後1取引平均の低い側が最大の一出口（同値ID順）だけを正式約定表示用に保存する。11/4一場は順位に使わない。これは表示の選択であり、採用や優位性の認定ではない。\n"
    fixed_text += G.table(["評価", "候補", "表示対象", "探索用費用資格"], [[refs[cid], cid, "X00基準" if cid.endswith("_X00") else "旧二期間による表示代表", "充足" if values[cid]["費用資格"] else "未達"] for cid in fixed_ids])
    fixed_text += f"保存結果の費用資格数：{report['費用資格数']}/18。支持・活動・売買・品質の条件は00008の探索規則を継承し、この数だけで採用確定しない。\n\n"
    definitions_rows = [[r["評価ID"], r["候補ID"], r["入口"]["役割"], r["入口"]["候補ID"], EXIT_NAMES[r["出口"]["出口ID"]], "あり" if r["候補ID"] in fixed_ids else "なし", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules]
    all_definitions = "## 全18候補\n" + G.table(["評価", "候補", "役割", "元入口", "出口", "正式約定保存", "探索用費用資格"], definitions_rows)
    audit_readme, audit_paths = audit_section(study, readme)
    viewer = "## 入力・Viewer・再現\n\n入力は00008の台帳をSHA付きで参照し、原板を複製しない。\n\n" + G.link(study / "入力台帳.json", readme) + " / " + G.link(manifest_path, readme, "参照元00008入力台帳") + "\n\n"
    viewer += f"市場データroot：`{manifest['source_root']}`。Viewerのresource_rootは本リポジトリ。`path_base=catalog`の`pnl_path`は一覧の親からの相対パス、`market_path`は市場rootからの相対パス。追加滑り0ptの正式表示固定IDだけを表示する。\n\n"
    for name in ("一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "Viewer照合.json"):
        if (study / name).exists():
            viewer += G.link(study / name, readme) + "\n\n"
    viewer += "集約の再表示は次のコマンド。原板再読・出口探索・代表の再選定は実行しない。\n\n```powershell\npython -X utf8 scripts/利益回収/レポート.py\n```\n\n"
    viewer += "再現コード：" + " / ".join(G.link(ROOT / "scripts/利益回収" / n, readme) for n in ("比較.py", "運用.py", "合成検証.py", "レポート.py")) + "。数値再生は`比較.py --study 検証用保存先`。正式結果の上書きは禁止されているため、固定入力・版を保持して別先で再現する。\n\n"
    links = " / ".join(G.link(study / n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json"))
    summary = "# 試行00010：順行と反転の利益保護と通常出口\n\n状態：" + status + "\n\n" + intro + links + " / " + G.link(setting_path, readme) + " / " + G.link(all_path, readme) + "\n\n" + limits + definition + fixed_text
    summary += findings(values) + tables(display_rows, values, refs) + audit_readme + viewer
    common = settings(rules)
    setting = "# 試行00010：設定と結果\n\n" + intro + G.link(G.MASTER, setting_path, "コピー元の汎用表") + " / " + G.link(readme, setting_path) + " / " + G.link(all_path, setting_path) + "\n\n"
    setting += "## 手法×時間スケール\n\n51手法×9尺度を全て保持。Sは実際の役割、R01〜R18は複合条件の運用評価であり、指標単独の効果ではない。未使用は入力不存在を意味しない。BB中心のSMA20は移動平均へ記録し、帯条件の使用とはしない。入口先着は本試行で再評価していない。\n\n" + G.matrix(catalog, setting_path, common)
    setting += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "閾値・役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"]) + "・" + "/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting += "## 計算と結果の範囲\n\nEMAはSMA初期、RSI/ATR/ADXは00006/00008のWilder14、中心は終値20本SMA。同限月で履歴を継続し、欠枠・限月変更・前場尾部欠枠で指標を切る。同場の有効前足・RSI窓だけを使い、15分未準備を中立へ置かない。出口を変えると後続の新規参加も変わるため、共通新規差と全運用差を分ける。\n\n" + limits + all_definitions
    setting += "各Rの3期間の純損益・赤字化・床・集合差は" + G.link(all_path, setting_path) + "に全件保存する。正本は" + G.link(study / "結果.json", setting_path) + "。表示用代表は採用条件ではない。\n\n"
    audit_all, _ = audit_section(study, all_path)
    all_text = "# 試行00010：全候補結果\n\n状態：" + status + "\n\n" + intro + G.link(readme, all_path) + " / " + G.link(setting_path, all_path) + "\n\n" + limits + all_definitions + definition
    all_text += findings(values) + tables([values[r["候補ID"]] for r in rules], values, refs) + audit_all
    sources = [Path(__file__), ROOT / "scripts/レポート/設定結果レポート.py", G.CATALOG,
               ROOT / "scripts/利益回収/比較.py", ROOT / "scripts/利益回収/運用.py", ROOT / "scripts/利益回収/合成検証.py",
               study / "計画.md", study / "条件.json", study / "固定.json", study / "入力台帳.json", manifest_path, study / "結果.json"] + audit_paths
    for path, content in ((readme, summary), (setting_path, setting), (all_path, all_text)):
        path.write_text(content + G.provenance(sources, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """試行と任意の表示確認先を受け取り帳票を生成する。

    引数: なし。--study/--outputをコマンド行から読む。
    返り値: None。生成先をJSONで表示する。
    """
    parser = argparse.ArgumentParser(description="00010の数値集約から通常出口比較を表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
