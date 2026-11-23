"""00008の保存済み集約と固定条件から、設定表と結果のMarkdownを再生成する。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDY = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
PERIODS = ("学習", "条件選択")
FAMILIES = {"RSI回復": "F01", "RSI再加速": "F02", "DMI方向発生": "F03", "BB復帰価格確認": "F04"}
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def load_generator() -> Any:
    """既存の汎用表生成器を、書き込み処理を実行せず読み込む。

    引数: なし。
    返り値: Any はmatrix・catalogパス・表整形を持つ既存モジュール。
    """
    path = ROOT / "scripts/レポート/設定結果レポート.py"
    spec = importlib.util.spec_from_file_location("外部探索の共通表", path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = load_generator()


def read_optional(path: Path) -> dict | list | None:
    """存在する集約だけを読み、未保存を数値ゼロへ変換しない。

    引数: path (Path) はJSON。
    返り値: dict | list | None は保存値、または未保存。
    """
    return G.read_json(path) if path.exists() else None


def number(value: object) -> str:
    """数値を桁区切りで表示し、未算出とゼロを区別する。

    引数: value (object) は数値・欠測。
    返り値: str は表示値。
    """
    if value is None or value == "":
        return "未算出"
    return f"{float(value):,.0f}" if float(value).is_integer() else f"{float(value):,.2f}"


def definitions(config: dict) -> list[dict]:
    """条件JSONの順序で新32条件と対照を記録用に列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は33件の定義。探索や順位付けはしない。
    """
    result = [{"候補ID": f"{size}分_{family}_{parameter}_{extra}", "時間足分": size,
               "手法": family, "パラメータ": parameter, "補助": extra}
              for size in config["時間足分"] for family, values in config["手法"].items()
              for parameter in values for extra in config["補助"]]
    if len(result) != config["新候補数"] or len(result) != 32:
        raise ValueError("00008の新32条件と異なります")
    result.append({"候補ID": config["対照ID"], "時間足分": 3, "手法": "開始幅失敗復帰", "パラメータ": 15, "補助": "ADX環境"})
    for index, row in enumerate(result, 1):
        row["評価ID"] = f"R{index:02d}"
    if len({r["候補ID"] for r in result}) != 33:
        raise ValueError("候補IDが重複しています")
    return result


def condition_text(rule: dict) -> tuple[str, str]:
    """一候補の買い発動と補助を、固定計画の式で記述する。

    引数: rule (dict) は候補定義。
    返り値: tuple[str, str] は発動と補助。売りは方向を対称化する。
    """
    family, value = rule["手法"], rule["パラメータ"]
    if family == "開始幅失敗復帰":
        return "開始15分の高安を固定。前C<下端≤今C≤上端", "ADX14<20。00006固定入口の対照"
    base = {
        "RSI回復": f"前RSI≤{value}<今RSI、今C>前C",
        "RSI再加速": f"前RSI≤50<今RSI、今足を除く過去{value}本の全RSIが有効かつ最小≤40、今C>EMA20、今C>前C",
        "DMI方向発生": f"前(+DI−−DI)≤0<今(+DI−−DI)、今ADX≥{value}かつ今ADX>前ADX、今C>EMA20、今C>前C",
        "BB復帰価格確認": f"BB20・母標準偏差×{value}。前C<前下帯、今C≥今下帯、今C>前C。反対側の帯は上限にしない",
    }[family]
    extra = {"RSI回復": "ADX14<20かつ今ADX≤前ADX",
             "RSI再加速": "準備済み確定15分方向が買い",
             "DMI方向発生": "準備済み確定15分方向が売りでない",
             "BB復帰価格確認": "ADX14<20かつ今ADX≤前ADX、準備済み確定15分方向が中立"}[family]
    return base, extra if rule["補助"] == "役割別" else "なし"


def validate_entry(entry: dict) -> None:
    """入口集約の分母と率を、五ラベルから独立に照合する。

    引数: entry (dict) は保存済み入口集約。
    返り値: None。不整合はValueError。
    """
    total, filled = entry["候補数"], entry["約定候補数"]
    if total != sum(entry[key] for key in LABELS) or filled != total - entry["未約定"]:
        raise ValueError("入口の五ラベルと分母が一致しません")
    expected = entry["順行先着"] / filled if filled else None
    actual = entry["確認率"]
    if (expected is None) != (actual is None) or expected is not None and not math.isclose(expected, actual, abs_tol=1e-12):
        raise ValueError("入口確認率と件数が一致しません")


def validate_result(result: dict | None, rules: list[dict], periods: tuple[str, ...], expected_ids: set[str]) -> dict[str, dict]:
    """結果を正規化し、未完の候補集合を全候補の成功結果と扱わない。

    引数: result (dict | None) は集約、rules (list[dict]) は定義、periods (tuple[str, ...]) は期間、expected_ids (set[str]) は許可集合。
    返り値: dict[str, dict] は候補ID別の集約。未保存なら空。
    """
    if result is None:
        return {}
    rows = result["結果"]
    by_id = {r["候補ID"]: r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != expected_ids:
        raise ValueError("保存結果の候補集合が固定定義と一致しません")
    source = {r["候補ID"]: r for r in rules}
    for cid, row in by_id.items():
        if any(row[key] != source[cid][key] for key in ("時間足分", "手法", "パラメータ", "補助")):
            raise ValueError("結果の候補定義が条件JSONと一致しません")
        for period in periods:
            validate_entry(row[period]["入口"])
            operation = row[period]["運用"]
            n = operation["完結取引数"]
            for slip in (5, 10):
                if not math.isclose(operation[f"追加{slip}pt純損益円"], operation["追加0pt純損益円"] - 2 * slip * 10 * n, abs_tol=1e-8):
                    raise ValueError("運用の追加費用が基準と一致しません")
    return by_id


def settings(rules: list[dict]) -> list[dict]:
    """実際に判断・準備・執行へ使うセルを評価IDへ対応させる。

    引数: rules (list[dict]) は33候補。
    返り値: list[dict] は共通matrixへ渡す設定。計算しただけの指標を発動条件としない。
    """
    result = []
    groups = []
    for size in (3, 5):
        base = [r for r in rules if r["時間足分"] == size]
        groups.extend([
            (["I04"], [f"m{size:02d}"], [r for r in base if r["手法"] in ("RSI回復", "RSI再加速")], "RSI14・回復/再加速", "Wilder14。F01は30/40回復、F02は50回復と過去3/5本のRSI≤40。売りは100−RSI"),
            (["I01"], [f"m{size:02d}"], [r for r in base if r["手法"] in ("RSI再加速", "DMI方向発生")], "EMA20・終値位置", "F02/F03の終値>EMA20。SMA20で初期化するEMA。売りは反対"),
            (["I08"], [f"m{size:02d}"], [r for r in base if r["手法"] == "DMI方向発生" or r["手法"] in ("RSI回復", "BB復帰価格確認") and r["補助"] == "役割別" or r["手法"] == "開始幅失敗復帰"], "DMI/ADX14・方向/低方向性", "Wilder14。F03はDI交差とADX20/25以上・上昇。F01/F04補助はADX<20・非上昇、対照はADX<20"),
            (["I05"], [f"m{size:02d}"], [r for r in base if r["手法"] == "BB復帰価格確認"], "BB20・2/2.5σ復帰", "終値20本・母標準偏差。前帯外から対応帯境界へ戻り、価格も改善。反対帯の範囲制約なし"),
            (["I09"], [f"m{size:02d}"], base, "ATR14>0・共通準備", "Wilder14。入口母集団の準備だけ。利確250/保護125ptはATR倍率ではなく固定値"),
            (["P05"], [f"m{size:02d}"], [r for r in base if r["手法"] != "開始幅失敗復帰"], "今C>前C・価格改善", "全新32候補の価格改善。売りは今C<前C。実体/ヒゲ条件や指標単独効果は未評価"),
        ])
    upper = [r for r in rules if r["補助"] == "役割別" and r["手法"] in ("RSI再加速", "DMI方向発生", "BB復帰価格確認")]
    groups.extend([
        (["I01"], ["m15"], upper, "EMA20・上位方向", "確定15分のC>EMA20>前EMA20で買い、逆で売り、その他中立。未準備は中立としない"),
        (["P03", "P04"], ["m03"], [rules[-1]], "開始15分幅の失敗復帰", "3分足から開始15分幅を固定。前終値が幅外、今終値が幅内へ戻る対照。15分は計算窓であり15分足の利用ではない"),
        (["B01"], ["tick"], rules, "正常Bid/Ask・代理執行", "ラージBBOでmicro1枚を代理。新規/返済は要求後1価格時計秒以上。板数量や注文フローは未使用"),
        (["E01"], ["tick"], rules, "順250/逆125pt先着", "返済側気配・期限/不足を全約定分母へ含む。入口を独立追跡し保有は重複し得る"),
        (["E02"], ["tick"], rules, "TP250/SL125・1枚", "単一建玉。利確/保護は原板逐次、返済も+1秒。期限・空白・EOF未解消を区別"),
    ])
    for size in (3, 5):
        groups.extend([
            (["C07"], [f"m{size:02d}", "m15"], [r for r in upper if r["時間足分"] == size], f"{size}分と確定15分", "F02は同方向、F03は逆方向でない、F04は中立。同じ発動足の候補だけへ参照を付ける"),
            (["C04"], [f"m{size:02d}"], [r for r in rules if r["時間足分"] == size and r["手法"] == "DMI方向発生"], "DI交差＋ADX上昇", "F03の複合条件。単独のDIまたはADXの効果ではない"),
        ])
    for methods, scales, applies, short, detail in groups:
        if applies:
            refs = [r["評価ID"] for r in applies]
            result.append({"設定ID": f"S{len(result)+1:02d}", "手法ID": methods, "尺度ID": scales,
                           "短記": short, "結果短記": "・".join(refs), "説明": detail, "適用評価": refs})
    return result


# ----------------------------------------
# 保存された数字の表示。選定・ラベル計算・原板の読み直しは行わない。

def metric_tables(rows: list[dict], periods: tuple[str, ...], ref_ids: dict[str, str]) -> str:
    """入口と運用を別表へ転記し、不明・未約定・品質を落とさない。

    引数: rows (list[dict]) は候補集約、periods (tuple[str, ...]) は期間、ref_ids (dict[str, str]) は評価ID。
    返り値: str は二つのMarkdown表。
    """
    entries, operations = [], []
    for row in rows:
        for period in periods:
            e, o = row[period]["入口"], row[period]["運用"]
            prefix = [ref_ids[row["候補ID"]], period]
            entries.append(prefix + [e["候補数"], e["約定候補数"], *[e[k] for k in LABELS], G.pct(e["確認率"]),
                f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",
                f"{e['約定開始日数']}日/{e['約定場数']}場"])
            operations.append(prefix + [o["完結取引数"], f"{o['買い取引数']}/{o['売り取引数']}",
                f"{o['活動場数']}/{o['入力場数']}", o["無取引場数"], *[number(o[f"追加{s}pt純損益円"]) for s in (0, 5, 10)],
                "未確定" if o["追加0pt確定対象円"] is None else number(o["追加0pt確定対象円"]),
                f"{o['品質注意場数']}/{o['EOF期限未達場数']}/{o['未解消場数']}", G.pct(o["保有時間率_観測"]), G.pct(o["黒字場利益の最大場寄与"])])
    return "### 入口の先着評価\n" + G.table(
        ["評価", "期間", "候補", "約定", "順行", "逆行", "期限未達", "観測不足", "未約定", "主率", "30分間引き順/約定・率", "約定日/場"], entries
    ) + "### 単一建玉の運用評価\n\n金額は円。追加0/5/10ptは同じ約定への片道追加費用感度。確定対象の欠測をゼロへ置かない。保有時間率は完結取引の観測時間で、未解消があれば完全な保有時間率ではない。\n" + G.table(
        ["評価", "期間", "完結", "買/売", "活動/入力場", "無取引場", "追加0pt純額", "追加5pt純額", "追加10pt純額", "0pt確定対象", "注意/EOF/未解消場", "観測保有率", "最大黒字場寄与"], operations)


def quality_section(study: Path) -> str:
    """保存済みの足・板品質を段階別に集約表示する。

    引数: study (Path) は試行。
    返り値: str は品質表。品質だけの新場監査を結果評価と呼ばない。
    """
    rows = []
    for phase in ("探索", "後続"):
        items = read_optional(study / f"入力品質_{phase}.json")
        if items is not None:
            for size in (3, 5, 15):
                rows.append([phase, len(items), size, sum(r["正常板数"] for r in items),
                    sum(r["確定足数"].get(str(size), 0) for r in items), sum(r["尾部欠枠"].get(str(size), 0) for r in items)])
    return "## 入力・足品質\n\n正常板数は尺度ごとに同じ入力を再掲するため、尺度間で足し合わせない。尾部欠枠は内部欠枠と異なり、内部欠枠の件数はこの品質JSONだけでは分解できない。\n" + (
        G.table(["段階", "場数", "尺度分", "正常板数", "確定足数", "尾部欠枠"], rows) if rows else "品質の完了集約は未保存。入力品質だけの監査を先着・損益の評価済みとはしない。\n\n")


def external_section(study: Path, output: Path) -> str:
    """外部62歴史入口の再採点があれば、モデルと期間を分けて記す。

    引数: study (Path) は試行、output (Path) は出力Markdown。
    返り値: str は独立の再採点節。外部戦略の再実行や旧幅からの外挿にしない。
    """
    source = study / "外部入口再採点.json"
    value = read_optional(source)
    text = "## 外部62歴史入口の再採点\n\n外部00170の保存済み入口の診断。外部の100/50pt成績を125/250ptへ外挿せず、保存入口を別に追跡する。元の返済を無視し、出口変更後の再参加や建玉抑止を再実行した戦略成績・損益とはしない。\n\n"
    if value is None:
        return text + "再採点の完了集約は未保存。未検証または作成途中であり、数字を推測しない。\n\n"
    rows = []
    for row in value["集計"]:
        if row["保存入口数"] != row["対象外"] + row["未約定"] + row["約定入口数"]:
            raise ValueError("外部再採点の入口数が一致しません")
        if row["約定入口数"] != sum(row[k] for k in LABELS[:-1]):
            raise ValueError("外部再採点のラベル数が一致しません")
        rows.append([row["モデル"], row["期間"], row["保存入口数"], row["対象外"], row["約定入口数"],
            row["未約定"], *[row[k] for k in LABELS[:-1]], G.pct(row["順行先着率_全約定"]), G.pct(row["順行先着率_保存入口"])])
    text += "Aは保存新規の時計・原行・価格を維持、Bは元decision_nsから共通の1秒待機・30秒有効・残り60分以上を要求する。入口集合と価格の違いを改善効果と呼ばない。両モデルは同じ歴史入口で独立標本ではない。\n"
    text += G.table(["モデル", "期間", "保存入口", "対象外", "約定", "未約定", "順行", "逆行", "期限", "不足", "全約定分母率", "保存入口分母率"], rows)
    return text + G.link(source, output, "再採点の定義・除外理由") + " / " + G.link(study / "外部入口事例.csv", output, "全62入口×両モデルの事例") + "\n\n"


def audit_section(study: Path, output: Path) -> str:
    """数値実行と合成・独立監査の完了状態を分けて示す。

    引数: study (Path) は試行、output (Path) は出力Markdown。
    返り値: str は明示された判定だけを使う検査表。
    """
    rows = []
    for label, name in (("合成検証", "合成検証結果.json"), ("入口の独立監査", "入口独立監査.json"), ("運用会計の独立監査", "運用独立監査.json")):
        path = study / name
        value = read_optional(path)
        if value is None:
            rows.append([label, "未完・結果未保存", "未算出", "なし"])
            continue
        verdict = value.get("成功") if label == "合成検証" else value.get("全件一致")
        state = "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示判定未確認"
        rows.append([label, state, number(value.get("検査数", value.get("照合項目数"))), G.link(path, output)])
    viewer_path = study / "Viewer照合.json"
    viewer = read_optional(viewer_path)
    if viewer is not None:
        checks = viewer.get("照合", [])
        verdict = all(row.get("一致") is True for row in checks) if checks else None
        state = "合格" if verdict is True else "不一致・失敗" if verdict is False else "資料あり・明示判定未確認"
        rows.append(["Viewer表示の照合", state, len(checks), G.link(viewer_path, output)])
    return "## 検査と監査の状態\n\n数値の集約保存と独立監査の合格は別の状態。未保存の監査を合格とは扱わない。入口監査は保存された候補和集合の整合と固定事例の直接照合であり、未保存の全時点における候補生成漏れや指標値の全面再計算を保証しない。\n" + G.table(["範囲", "保存済みの判定", "検査・照合項目数", "正本"], rows)


def observations(values: dict[str, dict], control_id: str, fixed_ids: list[str]) -> str:
    """全新候補の支持と観測黒字を、資格判定から分けて記す。

    引数: values (dict[str, dict]) は探索結果、control_id (str) は対照、fixed_ids (list[str]) は後続固定ID。
    返り値: str は結果の取りこぼしを防ぐ探索記述。候補の追加選定はしない。
    """
    if not values:
        return ""
    new = [r for cid, r in values.items() if cid != control_id]
    positive = [r for r in new if all(r[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS)]
    text = f"## 探索の観測黒字と資格の違い\n\n入口支持を満たした新候補は{sum(bool(r.get('入口支持')) for r in new)}/{len(new)}。両期間で追加5pt後の観測純損益が正なのは{len(positive)}件。観測黒字と、品質・支持を含む費用資格は別であり、全候補が赤字だったと要約しない。\n\n"
    rows = []
    for row in positive:
        cells = [row["候補ID"]]
        for phase in PERIODS:
            op = row[phase]["運用"]
            cells.append(f"{op['完結取引数']}取引、活動{op['活動場数']}/{op['入力場数']}場。0/5/10pt：" + "/".join(number(op[f"追加{s}pt純損益円"]) for s in (0, 5, 10)) + f"円。品質注意{op['品質注意場数']}場")
        cells += ["充足" if row.get("費用資格") else "未達", "固定済みの範囲だけ評価" if row["候補ID"] in fixed_ids else "後続固定の対象外・新1場では未評価"]
        rows.append(cells)
    if rows:
        text += G.table(["候補", "学習", "条件選択", "費用資格", "後続の扱い"], rows)
    return text + "観測黒字を次の問いとして残しても、新1場の結果を見て未固定候補を追加採点しない。\n\n"


def run(study: Path, output: Path) -> list[Path]:
    """条件・集約だけから3枚のMarkdownを生成する。

    引数: study (Path) は入力試行、output (Path) はMarkdown保存先。
    返り値: list[Path] は出力3ファイル。原板・作業特徴・他試行を更新しない。
    """
    config = G.read_json(study / "条件.json")
    catalog = G.read_json(G.CATALOG)
    if len(catalog["methods"]) != 51 or len(catalog["scales"]) != 9:
        raise ValueError("共通カタログの51×9構成が変わっています")
    rules = definitions(config)
    refs = {r["候補ID"]: r["評価ID"] for r in rules}
    exploration = read_optional(study / "探索結果.json")
    chosen = read_optional(study / "選定固定.json")
    follow = read_optional(study / "後続結果.json")
    values = validate_result(exploration, rules, PERIODS, set(refs))
    selection = exploration["選定"] if exploration else None
    if chosen is not None and chosen["選定"] != selection:
        raise ValueError("探索結果と選定固定が一致しません")
    if chosen is not None and chosen.get("探索結果SHA256") and chosen["探索結果SHA256"] != G.sha(study / "探索結果.json"):
        raise ValueError("選定固定時の探索結果SHA256と一致しません")
    fixed_ids = selection["固定ID"] if selection else []
    if len(set(fixed_ids)) != len(fixed_ids) or len(fixed_ids) > 3 or fixed_ids and config["対照ID"] not in fixed_ids:
        raise ValueError("後続の最大2新ID＋対照という固定集合と異なります")
    if follow is not None and chosen is None:
        raise ValueError("選定固定のない後続結果は転記できません")
    if follow is not None and follow.get("選定固定SHA256") and follow["選定固定SHA256"] != G.sha(study / "選定固定.json"):
        raise ValueError("後続が参照した選定固定SHA256と一致しません")
    followed = validate_result(follow, rules, ("後続検査",), set(fixed_ids))
    status = "探索・後続集約あり" if follow else "探索集約あり・後続未実行または未完" if exploration else "探索・後続とも未実行または未完"
    missing = [name for name in ("選定固定.json", "入力品質_探索.json", "一覧.resources.json", "固定候補_探索事例.csv") if exploration and not (study / name).exists()]
    missing += [name for name in ("入力品質_後続.json", "追加確認/一覧.resources.json", "後続事例.csv") if follow and not (study / name).exists()]
    if missing:
        status += "。成果物未完：" + "・".join(missing)
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path = [output / name for name in ("README.md", "設定と結果.md", "全候補の閾値と結果.md")]
    intro = "NK225、旧64場は全て既使用の探索（学習40場・条件選択24場）。11/4デイ1場は固定後に最大2新IDと対照だけを確認する。新1場だけで支持・安定性・採用を確立しない。\n\n"
    limits = "入口の主率は順行250pt先着/全約定。逆行125pt・期限未達・観測不足を分母に残し、未約定を別記する。運用はmicro1枚のラージBBO代理、倍率10円/pt、片道11円。片道11円は比較用の仮定で、最新の口座費用を確認した値ではない。追加5/10ptは完結往復へ100/200円を控除する費用感度で、約定価格や後続入口を動かした再計算ではない。CurrentPriceTimeは受信時計ではなく、1秒待機は実通信遅延の実測値ではない。品質注意・EOF・未解消を含む全体を確定利益としない。\n\n"
    result_text = "## 固定した候補と現在の結果\n\n"
    if selection:
        result_text += f"**新32候補の探索70目標達成数は{selection['70目標達成数']}、費用資格数は{selection['費用資格数']}。** 新1場だけで高勝率の発見・採用を確定しない。\n\n"
        result_text += G.table(["項目", "保存済みの値"], [[k, ("充足" if selection[k] else "未達") if isinstance(selection[k], bool) else G.describe(selection[k])] for k in ("入口用ID", "入口用支持", "費用用ID", "費用資格数", "70目標達成数")])
        result_text += "費用用IDの『なし』は資格候補なしを表す。入口用IDは診断用で、支持未達でも記録され得る。保存結果から選び直さない。\n\n"
        result_text += metric_tables([values[cid] for cid in fixed_ids], PERIODS, refs)
    else:
        result_text += "探索の完了集約は未保存。固定候補・70%達成・費用資格を推測しない。\n\n"
    result_text += "## 固定後の新1場\n\n"
    result_text += metric_tables(list(followed.values()), ("後続検査",), refs) if follow else "後続の完了集約は未保存。未実行・実行中・失敗をこの生成器だけで区別せず、評価済みとは表示しない。\n\n"
    result_text += "後続確認で再順位付け・条件変更を行わない。高率の少数件や一場の利益だけを採用根拠にしない。\n\n"
    viewer = "## Viewerと再現\n\n市場データrootは入力台帳の `source_root`（通常 `../JP_OSE_Data/future`）。Viewerのresource_rootは本リポジトリ。`path_base=catalog` の `pnl_path` は一覧ファイルのあるフォルダからの相対パス、`market_path` は市場データrootからの相対パスである。原板は複製しない。Viewerの約定は追加滑り0ptの基準だけを表示する。\n\n"
    manifest = G.read_json(study / "入力台帳.json")
    viewer += f"今回の市場データroot：`{manifest['source_root']}`。\n\n"
    for name in ("一覧.resources.json", "追加確認/一覧.resources.json"):
        viewer += (G.link(study / name, readme) if (study / name).exists() else f"`{name}`：未保存") + "\n\n"
    viewer += "実行順は入力監査→合成検証→探索・選定固定→固定後の後続一回→独立照合。再集計は次で行い、探索・後続自体を再実行しない。\n\n```powershell\npython -X utf8 scripts/外部探索/レポート.py\n```\n\n"
    viewer += "再現コード：" + " / ".join(G.link(ROOT / "scripts/外部探索" / name, readme) for name in ("入力監査.py", "探索.py", "合成検証.py", "外部入口再採点.py", "レポート.py")) + "。探索のCLIは `探索.py --study 対象フォルダ --phase 探索`、後続は `--phase 後続`。既存の正式結果は上書きを拒否するため、計画・入力・依存版を保持した検証用保存先で再現する。新1場を再び未見扱いしない。\n\n"
    links = " / ".join(G.link(study / name, readme) for name in ("計画.md", "条件.json", "入力台帳.json", "外部参照台帳.json"))
    summary = f"# 試行00008：外部研究を共通尺度へ移して探索\n\n状態：{status}。\n\n" + intro + links + " / " + G.link(setting_path, readme) + " / " + G.link(all_path, readme) + "\n\n" + limits + result_text
    summary += "## 33候補と外部資料の位置付け\n\nRSI回復、RSI再加速、DI交差とADX上昇、BB復帰＋価格改善の四系統×3/5分×二閾値×補助なし/役割別＝新32条件。00006固定対照1条件を加え33。外部の非Wilder DMI・標本SD・場内初期化を厳密再現せず、本研究のWilder14・母SD・同限月継続で移植する別仮説。外部100/50ptの確率を125/250ptへ外挿しない。\n\n"
    summary += observations(values, config["対照ID"], fixed_ids) + external_section(study, readme) + quality_section(study) + audit_section(study, readme) + viewer
    common = settings(rules)
    setting_text = "# 試行00008：設定と結果\n\n" + intro + G.link(G.MASTER, setting_path, "コピー元の汎用表") + " / " + G.link(readme, setting_path) + " / " + G.link(all_path, setting_path) + "\n\n"
    setting_text += "## 手法×時間スケール\n\nカタログ版1、51手法×9尺度を保持。未使用セルは未使用。Sは実際の役割、Rは複合候補の評価であり、指標単独の有効性・損益を表さない。表にない単独条件は未検証。\n\n" + G.matrix(catalog, setting_path, common)
    setting_text += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "閾値・役割", "評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])
    setting_text += "## 計算・初期化と適用範囲\n\nEMA20はSMA20で初期化。ATR/RSI/DMI14は前足差分14本、ADX14はさらにDX14本で初期化する。ATR0はDI0、DI和0はDX0、RSI上下幅とも0は未定義。BBは終値20本の母標準偏差。同限月で履歴継続し、欠枠・限月変更・前場尾部欠枠で切る。パターンとRSI窓は同場だけ。15分は確定時刻・原行と足終了を守り、未準備を中立にしない。\n\n"
    setting_text += limits + "実行条件は計画・条件・固定コードが正本。各Rの全閾値と学習/選択・後続の件数、率、費用、無取引、品質は" + G.link(all_path, setting_path) + "を参照する。運用損益と先着率、未使用とデータ不存在を混同しない。\n\n"
    definition_rows = [[r["評価ID"], r["候補ID"], FAMILIES.get(r["手法"], "対照"), r["時間足分"], *condition_text(r)] for r in rules]
    all_text = f"# 試行00008：全33候補の閾値と結果\n\n状態：{status}。\n\n" + intro + G.link(readme, all_path) + " / " + G.link(setting_path, all_path) + "\n\n売りは方向を対称化し、RSIは100−RSI。閾値交差の等号は下表のとおり。補助なしでも共通ATR>0・同場前足・残り60分以上等を要求する。\n"
    all_text += G.table(["評価", "候補ID", "系統", "足分", "買い発動", "補助"], definition_rows)
    all_text += limits + "## 学習・条件選択の全結果\n\n" + (metric_tables(list(values.values()), PERIODS, refs) if values else "探索集約未保存。全33候補とも本試行の結果は未検証。\n\n")
    all_text += result_text + observations(values, config["対照ID"], fixed_ids) + external_section(study, all_path) + quality_section(study) + audit_section(study, all_path)
    sources = [Path(__file__), G.CATALOG, study / "計画.md", study / "条件.json", study / "入力台帳.json", study / "外部参照台帳.json"]
    sources += [study / name for name in ("探索結果.json", "選定固定.json", "後続結果.json", "外部入口再採点.json", "入力品質_探索.json", "入力品質_後続.json", "合成検証結果.json", "入口独立監査.json", "運用独立監査.json", "Viewer照合.json") if (study / name).exists()]
    for path, content in ((readme, summary), (setting_path, setting_text), (all_path, all_text)):
        path.write_text(content + G.provenance(sources, path), encoding="utf-8")
    return [readme, setting_path, all_path]


def main() -> None:
    """入力試行と任意の表示確認用出力先を受け取る。

    引数: なし。--study/--outputをコマンド行から読む。
    返り値: None。生成したファイル名を表示する。
    """
    parser = argparse.ArgumentParser(description="00008の固定条件と数値集約からMarkdownを生成")
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    paths = run(study, args.output.resolve() if args.output else study)
    print(json.dumps({"生成": [str(p) for p in paths]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
