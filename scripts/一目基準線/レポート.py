"""28の保存正本だけから、上位一目の値追加と全51×9設定表を表示する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00028_基準線復帰と上位一目の方向"
WORK = ROOT / "work/一目基準線/00028"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("B0", "B1", "B2")


def helper() -> Any:
    """既存のMarkdown表示/分母検査だけを読み込む。

    引数: なし。
    返り値: Anyは表示モジュール。入口/先着/運用を再生しない。
    """
    path = ROOT / "scripts/反転確認時計/レポート.py"
    spec = importlib.util.spec_from_file_location("一目帳票の保存表示", path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


F = helper()
G, P, number = F.G, F.P, F.number


def definitions(config: dict) -> list[dict]:
    """事前B0/B1/B2の全三案を表示IDと対応させる。

    引数: config(dict)は正式条件。
    返り値: list[dict]は三入口・三運用の表示定義。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("事前3分B0/B1/B2・X0と異なる")
    return [{"評価ID": f"R{i:02d}", "候補ID": f"3分_{p}_X0", "入口": {"入口ID": "3分_" + p,
             "戦略": p, "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True}, "出口": {"出口ID": "X0"}}
            for i, p in enumerate(POLICIES, 1)]


def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict]:
    """固定/全三集合/40・24・2分母/費用/支持を保存値から検算する。

    引数: study(Path)は正式試行。
    返り値: tuple[dict,dict,list[dict],dict,dict]は条件/結果/定義/入口別/運用別。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "入口品質.json", "指標品質.json"):
        if not (study / name).is_file():
            raise ValueError(name + "未保存。正式完了前に実測帳票を作らない")
    config, report = G.read_json(study / "条件.json"), G.read_json(study / "結果.json")
    if report["全66場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性/先着幅の保存値不一致")
    rules = definitions(config)
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 3 or len(values) != 3 or len(report["入口評価"]) != 3 or len(report["結果"]) != 3:
        raise ValueError("全三案の集合が不一致")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("事前IDと保存集合が不一致")
    if report["表示固定ID"] != [r["候補ID"] for r in rules]:
        raise ValueError("結果による表示選択をしない")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("役割/入口/出口の定義差")
        for period, count in zip(PERIODS, (40, 24, 2)):
            P.validate_entry(entry[period])
            op = row[period]["運用"]
            if row[period]["入口"] != entry[period] or op["入力場数"] != count:
                raise ValueError("入口又は期間分母差")
            n = op["完結取引数"]
            if op["活動場数"] + op["無取引場数"] != count or op["買い取引数"] + op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n:
                raise ValueError("活動/方向/順行役割の会計差")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾分母不一致")
            for slip in (0, 5, 10):
                net, average = op[f"追加{slip}pt純損益円"], op[f"追加{slip}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"] - 20 * slip * n, abs_tol=1e-8):
                    raise ValueError("追加費用の往復感度差")
                if (average is None) != (n == 0) or n and not math.isclose(average, net / n, abs_tol=1e-8):
                    raise ValueError("平均の分母差")
                if op["品質注意場数"] and op[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意込み観測額を確定額としない")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], row["入口支持"], entry["70目標"], row["70目標"], row["費用資格"]) != (support, support, bool(goal), bool(goal), qualified):
            raise ValueError("支持/70/費用資格差")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in values.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("目標件数差")
    pins = G.read_json(study / "固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT / name) != digest for name, digest in pins.items()):
        raise ValueError("固定版の変更")
    manifest = G.read_json(study / "入力台帳.json")
    if len(manifest["entries"]) != 66 or len({r["session"] for r in manifest["entries"]}) != 66:
        raise ValueError("既使用66入力の分母差")
    return config, report, rules, entries, values


def settings(rules: list[dict]) -> list[dict]:
    """価格発動/Fast/上位準備/値選別/保護を51×9へ分けて記入する。

    引数: rules(list[dict])は三複合評価。
    返り値: list[dict]は10設定。共通上位準備をB0も含む全案へ課す。
    """
    groups = [
        (["I11", "P01"], ["m03"], rules, "価格P：Cprev<=J26prev<Cを売買鏡像", "同場隣接公開2本、前基準線を固定。前終値等号可/現終値等号不可。現Jへ置換せず、M/Fast/時間/保有と別にraw保存"),
        (["I07"], ["m03"], rules, "生K14対FastD3の厳密差符号=実side", "rawKと3生K平均、最速14/16。元OHLCのFraction差の符号/分子/分母を保存。同値0は両方向不採用、表示float差や20/50/80/slowDで判定しない"),
        (["I11", "C07"], ["m15"], rules, "共通M：現公開15分の現在雲/転換/基準準備", "9/26/52・shift26、現在雲=A/B(t−26)、最速78本。B0も準備を要求。end/key双方asof、同key/end可、古正常や前場公開へ戻らない。3分現在雲は不要"),
        (["I11", "C07"], ["m15"], rules[1:], "B1/B2：15Cが実方向の現在雲外strict", "買C>雲上端、売C<雲下端。雲内/端等号は不採用。B0の部分集合、逆方向注文へ切り替えない"),
        (["I11"], ["m15"], rules[2:], "B2：実side*(転換9−基準26)>0", "B1に高安中心整列を追加。転換=基準は不採用。B1の部分集合を同時点で比較し後足を待たない"),
        (["I09"], ["m03"], rules, "共通M：現ATR14有限正", "固定26のWilder更新を読取再用。Fast/上位の準備と全案共通、時間/確認遅延は別。ATR保護だけを複数入口手法と数えない"),
        (["I11"], ["m03", "m15"], rules, "数値銀行carryと場内公開履歴を分離", "同限月carry、欠枠/番号欠/不正/限月/尾部欠clear。欠枠後有効当足は初足、不正不投入。全幅末尾NPは数値更新だけ、局所前足/上位公開に使わない"),
        (["B01"], ["tick"], rules, "一建玉・新規/返済1秒・新規TTL30", "ラージBBOをmicro1枚代理、買Ask/売Bid新規・返済側BBO。同原行は気配→確定足→signal、順行role固定、自動ドテンなし"),
        (["I09", "C06", "E02"], ["tick"], rules, "固定26 A5：有利5pt起動・最低新規同値", "hard125/TP250/期限、D=max5,ceil(実入口ATR/5)*5。保護利益max(0,MFE−D)、買ceil/売floor、非緩和。返済pending中追尾停止、SAR/雲を通常出口にしない"),
        (["E01"], ["tick"], rules, "各仮新規125逆行前250順行・費用/支持別", "raw先着対象は時間AND遅延のみ、対象外は通常9数値None。仮先着と一建玉実運用の分母は別、30分間引きは評価感度で30分足と別"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def comparison(entries: dict, values: dict) -> str:
    """入口/実運用/費用/支持を三期間の別分母で表示する。

    引数: entries/values(dict)は保存入口/運用のID別正本。
    返り値: strは小集計表。全明細の複製や再生をしない。
    """
    rows, labels, supports, protections = [], [], [], []
    for eid, entry in entries.items():
        value = values[eid + "_X0"]
        for period in PERIODS:
            e, op = entry[period], value[period]["運用"]
            rows.append([eid, PERIOD_NAMES[period], e["候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}", op["完結取引数"], *[number(op[f"追加{s}pt純損益円"]) for s in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"]])
            labels.append([eid, PERIOD_NAMES[period], e["約定候補数"], e["順行先着"], e["逆行先着"], e["期限未達"], e["観測不足"], e["未約定"]])
            protections.append([eid, PERIOD_NAMES[period], op["追尾起動取引数"], op["起動後純赤字取引数"], f"{op['活動場数']}/{op['無取引場数']}", op["未解消場数"], op["EOF期限未達場数"], number(op["期間内最大場内DD円"]), number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                supports.append([eid, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達", "充足" if value["費用資格"] else "未達"])
    text = "## 三運用の結果\n\n仮先着は各要求後の仮新規を125/250又は期限まで観測し、実返済後も含む。全仮約定を分母とし、期限/不足を除かない。一建玉の参加数/実黒字率・金額とは別である。注意期の全体確定額はnull、以下の総額/平均は観測値。\n"
    text += G.table(["入口", "期間", "純要求", "250/仮約定・率", "30分間引き250/仮約定・率", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場"], rows)
    text += G.table(["入口", "期間", "仮約定", "250先着", "125先着", "期限", "不足", "未約定"], labels)
    text += "### 支持と活動頻度\n\n入口支持は学習60約定/6日/10場、選択20/3/5。70目標は両期主率と30分間引き率70%以上、間引き件数20/10も必要。費用資格は学習20完結/6日/10場/買売各5、選択10/3/6/各3、注意0・追加片道5pt後の両期黒字を全て要する。既使用後続2場や期間合算で不足を代用しない。\n"
    text += G.table(["入口", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "両期入口支持", "70目標", "費用資格"], supports)
    text += "### 利益保護と品質\n\n最大場内DDは各場0開始の時価下落で、期間を接合した累積DDとしない。起動後基準赤字と、追加費用後の赤字は別。\n"
    return text + G.table(["入口", "期間", "追尾起動", "起動後基準赤字", "活動/無取引場", "未解消場", "EOF未達場", "最大場内DD円", "基準確定対象円"], protections)


def stages(study: Path) -> str:
    """足の共通準備と価格raw/三純採用の保存件数を分ける。

    引数: study(Path)は正式試行。
    返り値: strは小集計と除外理由。重複理由を直列減算しない。
    """
    quality, numeric = G.read_json(study / "入口品質.json"), G.read_json(study / "指標品質.json")
    rows, reasons = [], {p: Counter() for p in PERIODS}
    for period in PERIODS:
        local = [r for r in quality if r["期間"] == period]
        rows.append([PERIOD_NAMES[period], len(local), sum(r.get("足数", 0) for r in local), sum(r.get("共通M準備足数", 0) for r in local), sum(r["原価格発動数"] for r in local), sum(r["先着評価対象外数"] for r in local), *[sum(r["戦略別発動数"]["3分_" + p] for r in local) for p in POLICIES]])
        for r in local:
            reasons[period].update(r["M除外理由別"])
    text = "## 準備・価格発動・純採用\n\n共通M足数は全3分足の準備件数、原P/純採用はイベント件数で分母が異なる。M/時間/遅延/Fastの不成立でも価格crossを消さず、後続を待って同じ原発動へ取り直さない。B1はB0、B2はB1の純集合に含まれるが、保有抑止後の実参加は別である。\n"
    text += G.table(["期間", "入力場", "全3分足", "共通M足", "原P", "先着対象外P", "B0", "B1", "B2"], rows)
    all_reasons = sorted({k for counts in reasons.values() for k in counts})
    text += G.table(["共通Mの足単位除外理由", *[PERIOD_NAMES[p] for p in PERIODS]], [[reason, *[reasons[p][reason] for p in PERIODS]] for reason in all_reasons])
    fields = ("入力足数", "基準線準備足数", "一目準備足数", "一目公開準備足数", "Fast準備足数", "非公開数値更新数", "clear数", "尾部完全欠枠")
    text += "### 数値銀行と公開用途\n\n3分完全雲の保存/準備数を下位エントリー条件へ加えない。15分Fastは採否に使わない。NPの内部更新と現在公開参照、銀行clearと値条件の不採用を区別する。\n"
    return text + G.table(["期間", "分足", "全足", "基準準備", "完全一目", "公開一目", "Fast準備", "NP内部更新", "clear", "尾部欠枠"], [[PERIOD_NAMES[p], minutes, *[sum(r[k] for r in numeric if r["期間"] == p and r["時間足分"] == minutes) for k in fields]] for p in PERIODS for minutes in (3, 15)])


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式証明と作業正本が同値であることを確かめて表示元を選ぶ。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは正式優先の正本。未保存又は版差は例外。
    """
    formal, original = study / name, work / name
    if formal.is_file():
        if original.is_file() and G.sha(formal) != G.sha(original):
            raise ValueError("証明版差:" + name)
        return formal
    if original.is_file():
        return original
    raise ValueError("証明未保存:" + name)


def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """全証明の明示合否と結果への指紋を検査する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tuple[str,list[Path]]は検査表/参照元。検算を収益標本へ合算しない。
    """
    groups = [("合成検証.json", "人工境界と非label/PnL経路"), ("独立監査.json", "全先着/Decimal会計/成果物"),
              ("状態独立確認.json", "全数値/一目/Fast厳密分数/原P/全B"), ("追尾独立確認.json", "全保有A5最初要求/気配"),
              ("対応診断.json", "上位値追加/除外/実参加/回収"), ("Viewer照合.json", "事前三運用の代表Viewer表示")]
    rows, paths = [], []
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致", data.get("対応集合全件一致")), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
            for key, digest in data["ファイルSHA256"].items():
                if G.sha(ROOT / key) != digest:
                    raise ValueError("最終合成のpin差")
        elif name == "Viewer照合.json":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 3 and all(r.get("一致") is True for r in checks), len(checks)
        if verdict is not True:
            raise ValueError("明示監査未完:" + name)
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("正式会計に状態/追尾が未接続")
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study / "結果.json"):
            raise ValueError("証明の結果SHA差:" + name)
        if name == "対応診断.json":
            result_key = (study / "結果.json").relative_to(ROOT).as_posix()
            if data["ファイルSHA256"].get(result_key) != G.sha(study / "結果.json"):
                raise ValueError("対応診断の結果pin差")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    reference = G.read_json(study / "準備参照.json")
    main_preparation = ROOT / reference["主準備"]
    independent_preparation = proof_path(study, work, "独立準備点検.json")
    if G.sha(main_preparation) != reference["主準備SHA256"] or G.sha(independent_preparation) != reference["独立準備SHA256"]:
        raise ValueError("固定前準備参照のSHA差")
    if reference["ラベル計算"] is not False or reference["損益計算"] is not False:
        raise ValueError("固定前準備でラベル/損益なしの証拠不一致")
    preparation = G.read_json(independent_preparation)
    if preparation["全件一致"] is not True or preparation["主準備SHA256"] != reference["主準備SHA256"]:
        raise ValueError("主独立準備の明示一致/対象版差")
    paths += [main_preparation, independent_preparation]
    rows += [["固定前主準備・ラベル/PnLなし", "66場・非損益", 66, G.link(main_preparation, output)],
             ["固定前独立数値・原P/全B再構成", "一致/合格", number(preparation["照合項目数"]), G.link(independent_preparation, output)]]
    supplement_path = work / "保存物読取補足.json"
    supplement = G.read_json(supplement_path)
    if supplement["全件一致"] is not True or supplement["不一致"] or supplement["読取対象SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
        raise ValueError("保存物読取補足の合否/対象診断SHA差")
    paths.append(supplement_path)
    rows.append(["独立読取・全参加/全費用分解", "一致/合格", "9比較×0/5/10pt", G.link(supplement_path, output)])
    text = "## 検査の状態\n\n固定前は人工検証/ラベルなし主独立準備、正式固定後は全状態/先着/会計/保有追尾/代表Viewerを別計算した。ATRだけ絶対許容1e−10・相対0と追尾D整数厳密照合、新一目/精密Fast符号分数/価格/時点/採否へ許容を広げない。検算数を独立収益標本へ合算しない。\n"
    text += G.table(["範囲", "明示合否", "件/項目", "正本"], rows)
    viewer = G.read_json(proof_path(study, work, "Viewer照合.json"))
    checks = viewer["照合"]
    if all("API最終状態" in r for r in checks):
        text += G.table(["代表候補", "場", "研究/API実現円", "API買/売保有", "数値本文SHA"], [[r["手法"], r["場"], f"{number(r['研究側純損益円'])}/{number(r['API最終状態']['realized_pnl_yen'])}", f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}", "一致" if r.get("数値本文SHA256一致") else "未確認"] for r in checks])
    text += "Viewerは一覧66×3資源から事前各案の代表3資源をAPI照合。画像追加" + str(viewer.get("追加PNG数", 0)) + "枚。保存模型の一致は実micro約定・将来収益を証明しない。\n\n"
    return text, paths


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """正式対応診断を参照し、同時点純集合と実参加/出口差を分離する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: strは除外/実参加/回収の小集計。全件明細を複製しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    result_key = (study / "結果.json").relative_to(ROOT).as_posix()
    if data["全件一致"] is not True or data["ファイルSHA256"].get(result_key) != G.sha(study / "結果.json"):
        raise ValueError("対応診断の合否/結果版差")
    text = "## 上位値追加と実参加の対応\n\n" + G.link(path, output) + "が全対応の正本。B0→B1の雲外追加とB1→B2の転換基準追加を分け、準備除外を方向条件の効果に数えない。共通実新規の出口差、各案だけの実参加、仮250逸失/125回避を別集合として扱う。総損失減少だけを入口改善又は安定収益とせず、取引数・平均・費用後回収と併記する。\n\n"
    text += G.table(["期間", "原P", "Pの共通M準備", "先着time/delay可", "B0", "B1", "B2"], [[PERIOD_NAMES[r["期間"]], r["原価格発動数"], r["共通M準備数"], r["先着評価対象数"], *[r["全案採用数"][p] for p in POLICIES]] for r in data["期間別原発動"]])
    text += "### 段階追加で保持/除外した純入口\n\n保持群と除外群は同じ当時Pの分割。除外群の250先着は取り逃した仮機会、125先着は避けた仮逆行で、実現円へ直接変換しない。重なるB0/B1/B2を独立標本にしない。\n"
    rows = []
    for r in data["入口追加比較"]:
        if (r["左"], r["右"]) not in (("B0", "B1"), ("B1", "B2")):
            continue
        for name in ("保持入口", "除外入口"):
            entry = r[name]
            rows.append([PERIOD_NAMES[r["期間"]], r["左"] + "→" + r["右"], name, entry["候補数"],
                         f"{entry['順行先着']}/{entry['約定候補数']}・{G.pct(entry['確認率'])}", entry["逆行先着"],
                         f"{entry['期限未達']}/{entry['観測不足']}/{entry['未約定']}", r["新規追加入口数"]])
    text += G.table(["期間", "追加", "群", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定", "追加純入口"], rows)
    text += "雲外条件が保持した群の率は学習で高くても、条件選択では保持29/113＝25.66%に対し除外51/155＝32.90%。さらに転換基準を足した選択保持22/86＝25.58%・除外7/27＝25.93%で、上位整列だけによる継続/待機の安定識別は確認できない。\n\n"
    text += "### B0の当時上位状態\n\n分母は共通M/Fast/時間を通過したB0純入口で、全原Pや実参加の率ではない。区分は当時公開の値で作れるが、表の未来先着を見て区分の向きや閾値を選び直していない。逆雲外群の率が高かったことを、不採用時の反転売買の成績へ読み替えない。転換基準の非整列には等号も含み、学習7件/選択8件を逆向き整列としない。\n"
    text += G.table(["期間", "当時の区分", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定"], [[PERIOD_NAMES[r["期間"]], r["当時上位区分"], r["候補数"], f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", r["逆行先着"], f"{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in data["B0の当時上位区分"]])
    text += "### 実参加は純集合の部分集合とは限らない\n\n共通実新規は役割・方向・新規価格/時刻/原行で対応させる。少なく入れば前の保有/注文待機が減り、対照が保有中に見送った後続へ参加できる。共通出口差と参加差を分ける。\n"
    text += G.table(["期間", "比較", "共通実新規", "共通出口差円", "左のみ完結・追加5総額/平均円", "右のみ完結・追加5総額/平均円", "全体基準差円"], [[PERIOD_NAMES[r["期間"]], r["左"] + "→" + r["右"], r["共通実新規数"], number(r["共通出口差円"]), f"{r['左のみ']['完結取引数']}・{number(r['左のみ']['追加5pt純損益円'])}/{number(r['左のみ']['追加5pt平均円'])}", f"{r['右のみ']['完結取引数']}・{number(r['右のみ']['追加5pt純損益円'])}/{number(r['右のみ']['追加5pt平均円'])}", number(r["総基準損益差円"])] for r in data["実参加比較"]])
    text += "B0→B1の学習/選択は共通129/103件、左のみ194/142件、右のみ22/9件で、右だけの実参加は左案の建玉中抑止に対応する。一方、当試行のB1→B2は全三期間で実参加も部分集合（右のみ0）。全比較の共通出口差は0円。B1の追加実参加があることや総赤字が減ったことを、共通出口の改善としない。選択の追加5pt平均はB0−184.45円→B1−233.61円→B2−251.41円へ悪化した。\n\n"
    text += "### 先着と実保有の回収\n\n仮250先着を実保有中の250pt獲得やその利益逸失としない。実保有250到達も事後MFEであり、任意の時点で全額回収できた証拠ではない。\n"
    text += G.table(["候補", "期間", "実完結", "対応仮250", "その判定前返済", "実保有MFE250", "追尾起動", "起動後基準赤字", "起動後最大同値床不足pt"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], r["仮250先着取引数"], r["仮250判定前返済数"], r["実保有250到達取引数"], r["追尾起動数"], r["起動後純赤字数"], number(r["起動後最大返済不足pt"])] for r in data["候補別回収"]])
    text += "B0の学習/選択の仮250対応92/72件のうち、実返済がその判定より前なのは91/70件。仮先着率と実回収を別の目的として検証する必要がある。設定を最低同値へ保護しても、実返済待機/気配変化と費用により起動後赤字は残る。\n\n"
    supplement = G.read_json(work / "保存物読取補足.json")
    text += "独立読取補足によるB0の内訳は次の通り。同値返済の純赤字は往復22円の手数料で、価格の逆行と区別する。不利返済の待機秒は本モデルの価格時計で、実ネットワーク遅延を測った値ではない。\n"
    text += G.table(["期間", "追尾起動", "起動後基準赤字", "うち同値返済手数料赤字", "うち不利価格返済", "不利返済待機秒中央値/最大"], [[PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["うち同値返済手数料赤字数"], r["うち不利価格返済数"], f"{number(r['不利返済の要求から約定秒中央値'])}/{number(r['不利返済の要求から約定秒最大'])}"] for r in supplement["B0回収内訳"]])
    trades = G.read_csv(study / "固定候補_取引.csv")
    rows = []
    for period in PERIODS:
        for policy in POLICIES:
            cid = "3分_" + policy + "_X0"
            armed = [r for r in trades if r["期間"] == period and r["手法"] == cid and r["追尾起動"] == "True"]
            entry_short = sum((1 if r["方向"] == "買い" else -1) * (float(r["返済価格"]) - float(r["新規価格"])) < 0 for r in armed)
            line_short = sum(float(r["最終追尾から実返済方向差pt"]) < 0 for r in armed)
            rows.append([cid, PERIOD_NAMES[period], len(armed), entry_short, line_short, number(sum(max(0., -float(r["最終追尾から実返済方向差pt"])) for r in armed))])
    text += "### 追尾設定と実約定\n\n以下の同値未満/最終線不足は追尾起動後の取引に限る。起動後基準赤字は手数料を含み、同値未満約定と同じ分母の別現象。設定下限と実約定・費用後非赤字を区別する。\n"
    text += G.table(["候補", "期間", "追尾起動", "同値未満約定", "最終線未満約定", "線不足pt計"], rows)
    return text + "表示float差と厳密Fast符号が異なった原Pは" + number(data["表示丸めと厳密Fast符号の相違原発動数"]) + "件。厳密仕様は損益を見る前に固定し、この実測に合わせたεやゲートの調整はしていない。\n\n"


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式結果と全証明が揃った後だけ保存値を二文書へ表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。原板/cache/主再生を呼ばない。
    """
    config, report, rules, entries, values = validate(study)
    catalog = G.read_json(G.CATALOG)
    if (catalog["version"], len(catalog["methods"]), len(catalog["scales"])) != (1, 51, 9):
        raise ValueError("版1の51手法×9尺度を保持する")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output / "README.md", output / "設定と結果.md"
    common = settings(rules)
    intro = "NK225・3分基準線復帰PとFast14/3を共通に、15分一目の現在雲外をB1、さらに転換9/基準26の方向をB2へ追加した三運用。全案の上位数値準備・当時の価格時計・X0/A5を共通にする。全66場は既使用（40/24/11月4日Day・Night2場）で、未使用確認ではない。全role順行で、不採用を逆売買へ変換しない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3。** 主率/間引き・支持・実参加・費用後平均・共通出口差を別に判定する。\n\n"
    warnings = [r["候補ID"] + "の" + PERIOD_NAMES[p] for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意あり：" + "、".join(warnings) + "。該当期の観測総額/平均を確定成績としない。\n\n"
    logic = "## 複数手法の役割と当時の時計\n\n3分は同場隣接公開2本で、前基準線J26に対し買Cprev≤Jprev<C、売Cprev≥Jprev>C。前終値等号可/現在終値等号不可、現Jへ置換しない。生K14とFastD3の差は元OHLCのFractionから厳密な符号/既約分子分母を保存し、実方向と一致する場合だけ採る。数学同値0は両方向不採用。表示floatの微差や20/50/80、slowD、K/D当足crossを追加条件にしない。\n\n"
    logic += "15分の転換9/基準26、先行A=(転換+基準)/2、B=52本高安中心。現在雲は26数値足前のA/Bで最速78本、現在算出A/Bを未来から持ち込まない。上位参照はend≤現在3分endかつ公開(time,line)≤現在3分keyの最新当場公開足。最新が不準備なら古正常や前場公開へ戻らない。NPは内部数値/carryだけ、局所前足/上位公開へ使わない。\n\n"
    logic += "共通Mは公開現前価格/前J、現ATR14正、表示Fast有限と厳密符号準備、最新15分の完全一目。B0にも同じ上位準備、3分現在雲は不要。B1は買15C>雲上端/売15C<雲下端、B2はさらに実side*(転換−基準)>0。雲内/端等号/転換基準等号は各値条件不成立。時間/遅延は準備と別、原Pの先着対象は時間AND遅延だけ。全B採否/同時競合を確定してからcase深複写し、未来labelは運用signalへ付けない。\n\n"
    protection = "## 保護・執行・費用・場内完結\n\n固定26の一建玉X0/A5を読取再用し新出口を作らない。hard125/TP250/期限、正常返済BBOで有利5ptになれば必須追尾。D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低新規同値。返済pending中追尾停止、役割fill固定、自動ドテンなし。優先は期限/既存待機→hard→TP→追尾。雲や基準線を通常出口に使わない。\n\n"
    protection += "ラージBBOのmicro1枚代理、10円/pt・呼値5pt・片道11円。新規/返済は要求+1価格秒以上の最初正常BBO、新規TTL30、買Ask/売Bid新規・返済側BBO。同原行は気配→確定足→signal。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、別の参加経路の再生ではない。同値設定は実同値約定/費用後非赤字を保証しない。\n\n"
    protection += "デイ入力08:45〜15:40/新規停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50を維持。正常板空白300秒超/EOF/未解消等の品質と確定不能を別記し、持ち越さない。価格時計は実受信時計ではなく、実microの板・約定を証明しない。\n\n"
    limits = "## 限界と知見の扱い\n\n基準線復帰を短期の高安中心への復帰、現在雲外を上位方向の継続、Fastを下位終値位置の勢いと読むのは心理の仮説である。すべて価格由来で独立した成功票ではなく、雲を投資家平均建値/雲厚を板数量とは解釈しない。一般的な一目の説明はNK225の本条件・70%・収益を証明しない。\n\n"
    limits += "移動平均線・RSIに限定せず一目/ストキャス/価格crossを組み合わせる一方、量・SAR・30分窓/fgh・遅行線・他尺度は本案で未使用、各指標単独効果は未検証。ATR準備/利益保護だけを複数入口手法として数えない。純集合の包含と一建玉の実参加包含は別。未来先着/事後MFEを当時の切替へ戻さず、主要条件変更は別試行に分ける。\n\n"
    audit_text, audit_paths = audits(study, work, readme)
    results = comparison(entries, values)
    summary = "# 試行00028：基準線復帰と上位一目の方向\n\n" + intro + " / ".join(G.link(study / n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json")) + " / " + G.link(mapping, readme) + "\n\n"
    summary += conclusion + results + stages(study) + diagnosis(study, work, readme) + logic + protection + limits + audit_text
    # ----------------------------------------
    # 全51手法と9尺度を残し、使用・準備・保護と未使用を分けて記入する。
    mapped = "# 試行00028：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, mapping, "コピー元汎用表") + " / " + G.link(readme, mapping) + "\n\n"
    mapped += "## 手法×時間スケール\n\n版1の51×9。S01〜S10は設定、R01〜R03は複合評価。共通15分一目準備は全案、上位方向の値追加はB1/B2へ分ける。3分現在雲と15分Fastは保存数値で採否には使わない。未使用尺度の有効性や単独効果を検証した表ではない。\n\n" + G.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"]) + "・" + "/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n" + G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 全三評価の定義と判定\n" + G.table(["評価", "候補", "同時点条件", "入口支持", "70目標", "費用資格"], [[r["評価ID"], r["候補ID"], config["一目基準線"][r["入口"]["戦略"]], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    mapped += results + logic + protection + limits + audits(study, work, mapping)[0]
    # ----------------------------------------
    # 巨大全件転記をせず、六系列・全証明・固定版・閲覧先の指紋を残す。
    files = ("入力台帳.json", "準備参照.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "指標品質.json", "入力品質.json", "作業成果物.json")
    sources = [HERE / n for n in ("README.md", "指標.py", "入口.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py") if (HERE / n).is_file()]
    docs = [ROOT / n for n in ("docs/technical-analysis/指標/一目均衡表.md", "docs/technical-analysis/指標/ストキャスティクス.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md")]
    common_doc = ROOT / "docs/議論/基準線復帰へ上位一目を加えた比較.md"
    if common_doc.is_file():
        docs.append(common_doc)
    viewing = "## 閲覧と再表示\n\n" + " / ".join(G.link(study / n, readme) for n in files if (study / n).is_file()) + "\n\nコード：" + " / ".join(G.link(p, readme) for p in sources) + "。\n\n"
    viewing += "原板/実cache/大量画像を複製せず、Git外の六gzipを作業成果物の展開内容SHAで参照する。Viewer一覧は事前B0/B1/B2の各66場、APIは代表3資源。market_pathはdata_root・pnl_pathはcatalog基準。--prepareは数値/原P/全B採否だけでlabel/PnLなし。主再生は既存結果/正式中間物を拒否する。保存値の再表示は次のコマンド。再生の手順と版はコードREADMEを参照し、固定資産を上書きしない。\n\n"
    fence = chr(96) * 3
    viewing += fence + "powershell\npython -X utf8 scripts/一目基準線/レポート.py\n" + fence + "\n\n"
    paths = [Path(__file__), ROOT / "scripts/反転確認時計/レポート.py", F.DISPLAY, ROOT / "scripts/SAR持続/レポート.py", ROOT / "scripts/終値切替/レポート.py", ROOT / "scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG,
             *[study / n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study / n).is_file()], *audit_paths, *sources, *docs]
    for path, text in ((readme, summary + viewing), (mapping, mapped)):
        path.write_text(text + G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存帳票だけを指定先へ再生成する。

    引数: なし。--study/--work/--outputは正式/作業/表示先。
    返り値: None。市場の入口/先着/会計を再実行しない。
    """
    parser = argparse.ArgumentParser(description="基準線復帰と上位一目の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
