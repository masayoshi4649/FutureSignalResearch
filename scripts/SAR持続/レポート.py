"""00025の保存結果から二運用の比較と必須51×9表だけを生成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00025_価格イベントとSAR方向持続"
DISPLAY = ROOT / "scripts/局面変化/レポート.py"
POLICIES = ("Q0", "Q1")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """既存の汎用表と保存集計の表示補助だけを読み込む。

    引数: なし。
    返り値: Any は表示モジュール。市場の先着や損益は再計算しない。
    """
    spec = importlib.util.spec_from_file_location("SAR持続帳票の固定22表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """3分Q0/Q1と共通X0の二評価を定義する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は二入口と二運用の対応。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分Q0/Q1・共通X0と異なる")
    if config["終値切替"] != {"チャネル足分": 30, "チャネル本数": 6, "ε_ATR倍率": .25, "内復帰上限本数": 6, "外回復上限本数": 3}:
        raise ValueError("固定チャネルと6/3寿命と異なる")
    if any(config["SAR"][k] != v for k, v in {"初期AF": .02, "増分AF": .02, "上限AF": .2, "時間足分": 3, "比較本数": 2, "出口使用": False}.items()):
        raise ValueError("固定SARの数値条件と異なる")
    rows = []
    for policy in POLICIES:
        source = {"入口ID": "3分_" + policy, "戦略": policy, "時間足分": 3,
                  "名称": policy, "役割": "混合", "複合本命": True}
        rows.append({"候補ID": source["入口ID"] + "_X0", "入口": source,
                     "出口": {"出口ID": "X0"}, "評価ID": "R" + str(len(rows) + 1).zfill(2)})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """二案の分母・費用感度・支持・品質nullを保存値から検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は二案の定義。
    返り値: tuple[dict,dict] は入口と運用のID別正本。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または先着幅が不一致")
    entries = {row["入口ID"]: row for row in report["入口評価"]}
    values = {row["候補ID"]: row for row in report["結果"]}
    if len(entries) != 2 or len(report["入口評価"]) != 2 or len(values) != 2 or len(report["結果"]) != 2:
        raise ValueError("全二入口/二運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("保存ID集合が不一致")
    for rule in rules:
        entry, value = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or value["入口"] != rule["入口"] or value["出口"] != rule["出口"]:
            raise ValueError("二案の定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            item = value[period]["運用"]
            n = item["完結取引数"]
            if value[period]["入口"] != entry[period] or item["入力場数"] != sessions:
                raise ValueError("入口分母または入力場数が不一致")
            if item["活動場数"] + item["無取引場数"] != sessions or item["買い取引数"] + item["売り取引数"] != n or sum(item["役割別完結数"].values()) != n:
                raise ValueError("活動/方向/役割の会計が不一致")
            if not 0 <= item["起動後純赤字取引数"] <= item["追尾起動取引数"] <= n:
                raise ValueError("追尾起動と赤字数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"] - 20 * slip * n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net / n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("品質注意を含む全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
                               and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(value[p]["運用"][k] >= limit for k, limit in limits.items()) and value[p]["運用"]["品質注意場数"] == 0
                        and value[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], value["費用資格"]) != (support, bool(goal), bool(qualified)):
            raise ValueError("支持/70目標/費用資格が不一致")
    if report["表示固定ID"] != [rule["候補ID"] for rule in rules]:
        raise ValueError("事前Q0/Q1表示と異なる")
    if report["入口70目標達成数"] != sum(row["70目標"] for row in entries.values()) or report["費用資格数"] != sum(row["費用資格"] for row in values.values()):
        raise ValueError("目標件数が不一致")
    return entries, values


def previous_display() -> Any:
    """固定24の保存表示と小集計だけを読み込む。

    引数: なし。
    返り値: Any は表示モジュール。価格・先着・損益の再生をしない。
    """
    path = ROOT / "scripts/終値切替/レポート.py"
    spec = importlib.util.spec_from_file_location("SAR帳票の固定24表示", path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


D = previous_display()


def settings(rules: list[dict]) -> list[dict]:
    """SAR準備・SAR方向・MACDと価格構造の役割を51×9へ記録する。

    引数: rules (list[dict]) は二評価。
    返り値: list[dict] は全設定と適用評価。未使用セルを消さない。
    """
    q0, q1 = [rules[0]], [rules[1]]
    groups = [
        (["I03", "I09"], ["m03"], rules, "M24：公開現前C/H有限・現ATR正", "15分公開現前ペア・登録固定30出典・遅延<=30、時間条件別。下位BB/K/RSI/VWAP/量を準備gateへ足さない。Q1でもHの準備は同じ"),
        (["I10"], ["m03"], rules, "共通M25：現前公開SAR有効", "両案にM24 AND 同場隣接公開SAR方向±1。Q0はSAR準備のみ、Q1の方向値条件はS03で区別。旧E0→Q0の準備除外を別計数"),
        (["I10"], ["m03"], q1, "Q1：前方向=現方向=実side", "AF初期/増分.02・上限.2。現在のみの転換は不成立。δH符号/ADX低下を追加ANDせず、SARを出口には使わない"),
        (["I03"], ["m03"], q0, "Q0：価格f/g＋実side×δH>0", "H=MACD−Signal、12/26/9、EMAは算術seed。Q1の比較対象で、MA/RSIだけへ限定しない"),
        (["I05", "I08", "C07"], ["m15"], rules, "公開現前ペアはM24の数値準備のみ", "15分ADX/DI/BB幅の値による上位選別は両案へ不使用。旧E1の非上昇枝を持ち込まない"),
        (["P02", "P03", "P06", "P07", "C07"], ["m30"], rules, "前公開3分pまでの完全公開30分6本R/L", "end<=p.endかつ公開key<=p.key。R/L/6出典を登録時固定、同限月carry/resetは固定24。後段の新窓未準備で取消しない"),
        (["P07", "I09"], ["m03"], rules, "登録b：prevC<=R+ε<C、ε=max5,ceil(.25ATR/5)*5", "売鏡像。時間可、global監視1、used(side,境界)当場一回。S2/勢い/SAR不問・遅延>30可、登録は注文なし"),
        (["P01", "P03", "P04", "P06", "P07"], ["m03"], rules, "f：次1〜6初内復帰r=-s、g：次1〜3初外回復s", "固定24close-only、end>前段confirm・keystrict。初価格eventをM25/SAR/勢い/時間不可でも消費。元端等号待機、反対端等号取消"),
        (["V01"], ["m03"], rules, "観測差分量/RVOLは診断のみ", "固定14helper、量の欠測/0/値でM・状態・採否不変。全約定量や方向別flow/OIは復元せず、量選別効果未検証"),
        (["P06"], ["m03"], rules, "Rの公開終値→反対端/無効化距離は事後集計", "保存当時終値と固定R/Lの構造距離だけ。250余地/125以内の件数は診断で注文gate不使用、約定価格の余地と別。Tの目標は定義しない"),
        (["B01"], ["tick"], rules, "一建玉・新規/返済+1価格秒・TTL30", "ラージBBOをmicro1枚代理、買Ask/売Bid新規と返済側BBO。役割fill固定・SAR反転でドテン/決済しない"),
        (["I09", "C06", "E02"], ["tick"], rules, "A5/実入口ATRceil幅・最低新規同値ratchet", "hard125/TP250/期限、D=max5,ceil(ATR_f又はg/5)*5。pending追尾更新停止。SAR線を追尾幅/保護価格へ使わない"),
        (["E01"], ["tick"], rules, "各新規から125逆行前250先着", "時間かつ遅延可の仮約定が分母。時間優先/次遅延の対象外は通常9数値None。間引き30分は30分足とは別"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def comparison(entries: dict, values: dict) -> str:
    """共通の先着/費用/支持表示を、方式置換の二案へ適用する。

    引数: entries/values (dict) は保存正本。
    返り値: str は三期間の小表。SARを旧E1の上位追加条件としない。
    """
    return (D.comparison(entries, values).replace("E1の上位選別", "Q0/Q1の方式変更")
            .replace("基準円", "基準観測円").replace("追加5pt円", "追加5pt観測円").replace("追加10pt円", "追加10pt観測円"))


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """最終30合成とSARを含む全属性/会計/追尾の明示状態を表示する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: tuple[str,list[Path]] は合否表/参照元。検算数は収益標本にしない。
    """
    text, paths = D.audits(study, output)
    return (text.replace("最終33", "最終30").replace("33合成", "30合成")
            .replace("原価格の固定30窓/監視/全二集合", "原OHLCの全SAR/固定30窓/監視/全二集合")
            .replace("上位選別/episode/参加と回収", "SAR準備/方向置換/episode/参加と回収").replace("E0/E1", "Q0/Q1")), paths


def stages(study: Path) -> str:
    """新旧の数値準備と価格段階を注文の採否から分ける。

    引数: study (Path) は正式試行。
    返り値: str は価格/M/値選別/SAR銀行の小集計。
    """
    data = G.read_json(study / "入口品質.json")
    rows, events = [], []
    keys = ("旧24共通M準備足数", "共通M準備足数", "SAR現在準備足数", "SAR現前準備足数", "設定数", "内復帰価格消費数", "外回復価格消費数", "先着評価対象外数")
    for period in PERIODS:
        own = [r for r in data if r["期間"] == period]
        rows.append([PERIOD_NAMES[period], *[sum(r.get(k, 0) for r in own) for k in keys]])
        for role in ("反転", "順行"):
            stages_rows = [s for r in own for s in r["イベント段階"] if s["役割"] == role]
            fields = ("原価格イベント数", "先着評価対象数", "M24時間通過数", "M25時間通過数", "旧24E0数", "SAR準備でQ0除外数", "Q0採用数", "Q1採用数")
            events.append([PERIOD_NAMES[period], role, *[sum(s[k] for s in stages_rows) for k in fields]])
    text = "## 準備・価格消費・方式選別\n\nM24→M25の差はSAR数値準備の追加であり、方向持続条件の効果ではない。価格登録/監視/f/gの数と出典は固定24から再用する。SAR不成立でも最初のf/gを消費し、後の足へ取り直さない。\n"
    text += G.table(["期間", "M24足", "M25足", "SAR現在可", "SAR現前可", "登録", "内復帰f", "外回復g", "先着対象外event"], rows)
    text += G.table(["期間", "役割", "原event", "先着対象", "M24時間", "M25時間", "旧E0", "SAR準備除外", "Q0", "Q1"], events)
    sar = G.read_json(study / "SAR品質.json")
    fields = ("SAR入力足数", "SAR数値準備足数", "SAR公開準備足数", "SAR初期化数", "SAR反転数", "SAR未公開数値更新数", "SARclear数", "SAR尾部完全欠枠")
    text += "### SAR銀行と公開用途\n\n末尾完全幅NPは内部更新/carryし、局所公開現前値には使わない。clearは欠枠/不正/限月/尾部欠枠による数値銀行の解除で、Q1の見送り件数ではない。場別の全SAR canonical SHAは品質正本と独立準備で照合する。\n"
    text += G.table(["期間", "全足", "数値準備", "公開準備", "seed", "反転", "NP数値更新", "clear", "尾部完全欠枠"], [
        [PERIOD_NAMES[p], *[sum(r[k] for r in sar if r["期間"] == p) for k in fields]] for p in PERIODS])
    return text


def diagnosis(study: Path, output: Path) -> str:
    """同一価格イベント上の準備除外・方式差・実参加/回収を分ける。

    引数: study/output (Path) は正式試行/表示先。
    返り値: str は小集計と正本参照。全明細を複製しない。
    """
    path = study / "対応診断.json"
    text = "## SAR準備・方向持続・実回収\n\nQ1はQ0への追加ANDではなく単足δMACDの値条件を二本SAR方向へ置換する。互いの純集合の包含を仮定せず、共通/Q0のみ/Q1のみを分ける。一建玉の実参加はさらに保有/待機で変わる。\n\n"
    if not path.exists():
        return text + "対応診断は未完・未保存。正式完成後に反映する。\n\n"
    data = G.read_json(path)
    if data["結果SHA256"] != G.sha(study / "結果.json") or data["対応集合全件一致"] is not True:
        raise ValueError("対応診断の結果SHA/明示合否不一致")
    text += G.link(path, output) + "：全件一致・" + number(data["照合項目数"]) + "項目。旧24の価格/全原先着同値とQ0の準備部分集合を確認し、準備除外をSAR方向の効果へ加えない。\n\n"
    text += "### 同じ価格eventの準備と方式別の先着\n"
    rows, groups = [], []
    for r in data["役割別準備と選別"]:
        if r["期間"] not in PERIODS[:2]:
            continue
        a, b = r["Q0価格と勢い"], r["Q1価格とSAR持続"]
        rows.append([PERIOD_NAMES[r["期間"]], r["系統"], r["全価格発動"]["候補数"], r["M24時間通過"]["候補数"],
                     r["M25時間通過"]["候補数"], r["旧24E0"]["候補数"], r["SAR準備で旧E0除外"]["候補数"],
                     f"{a['順行先着']}/{a['約定候補数']}・{G.pct(a['確認率'])}", f"{b['順行先着']}/{b['約定候補数']}・{G.pct(b['確認率'])}"])
        for name in ("共通原採用", "Q0のみ原採用", "Q1のみ原採用"):
            x = r[name]
            groups.append([PERIOD_NAMES[r["期間"]], r["系統"], name, x["候補数"], f"{x['順行先着']}/{x['約定候補数']}",
                           x["逆行先着"], f"{x['期限未達']}/{x['観測不足']}/{x['未約定']}"])
    text += G.table(["期間", "系統", "価格event", "M24時間", "M25時間", "旧E0", "SAR準備除外", "Q0順/仮約定・率", "Q1順/仮約定・率"], rows)
    text += "### 取り逃しと追加参加の原集合\n\n片側のみの250/125先着は、同じ当時価格eventに対する事後分類。Q1のみを追加の独立標本とせず、二案の因果的優劣や将来の勝率と同一視しない。\n"
    text += G.table(["期間", "系統", "集合", "要求", "250/仮約定", "125先着", "期限/不足/未約定"], groups)
    text += "### SARの当時状態\n\n同場公開現前の方向を使い、当足だけの反転は二本持続としない。下表は売買合算、売買別全文は診断正本に残す。\n"
    grouped = {}
    for r in data["SAR状態別"]:
        if r["期間"] not in PERIODS[:2]:
            continue
        count = grouped.setdefault((r["期間"], r["系統"], r["SAR状態"]), Counter())
        for label in ("全価格発動", "Q0採用", "Q1採用"):
            for field in ("候補数", "約定候補数", "順行先着", "逆行先着"):
                count[label+field] += r[label][field]
    text += G.table(["期間", "系統", "SAR状態", "原event", "Q0採用", "Q1順/仮約定", "Q1逆行125"], [
        [PERIOD_NAMES[p], family, state, c["全価格発動候補数"], c["Q0採用候補数"],
         f"{c['Q1採用順行先着']}/{c['Q1採用約定候補数']}", c["Q1採用逆行先着"]] for (p, family, state), c in grouped.items()])
    text += "### 旧24E0とQ0の運用対照\n\n共通準備以外に参照案を変えていないか確認する。準備除外なしの期は同じ実新規/出口/金額であり、旧E0から成績を改善したと数えない。\n"
    text += G.table(["期間", "SAR準備除外なし", "共通/旧のみ/Q0のみ実新規", "共通出口差円", "全純額差円"], [
        [PERIOD_NAMES[r["期間"]], r["SAR準備除外なし"],
         f"{r['運用比較']['共通実新規数']}/{r['運用比較']['左側のみ実新規数']}/{r['運用比較']['右側のみ実新規数']}",
         number(r["運用比較"]["共通実新規純額差円"]), number(r["運用比較"]["全運用純額差円"])] for r in data["旧24E0とQ0運用対応"]])
    text += "### 役割ごとの実回収\n\nR/Tの構成比と役割内の回収を分ける。仮250先着は実返済後の経路も含み、保有中250ptを得て失った件数ではない。\n"
    text += G.table(["候補", "期間", "役割", "実完結", "基準観測円", "追加5pt観測円", "追加5pt平均円", "対応仮250", "仮250だが純赤字", "仮250だがTP以外"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["役割"], r["実新規対応数"], number(r["基準純額円"]), number(r["追加5pt純額円"]),
         number(r["追加5pt純額円"] / r["実新規対応数"] if r["実新規対応数"] else None), r["対応先着250数"], r["先着250だが基準純赤字数"], r["先着250だが250利確以外数"]]
        for r in data["入口先着と利益回収"] if r["期間"] in PERIODS[:2]])
    by_role = {(r["候補ID"], r["期間"], r["役割"]): r for r in data["入口先着と利益回収"]}
    changes = []
    for period in PERIODS[:2]:
        left, right = (by_role[cid, period, "順行"] for cid in ("3分_Q0_X0", "3分_Q1_X0"))
        changes.append(f"{PERIOD_NAMES[period]}{number(left['追加5pt純額円']/left['実新規対応数'] if left['実新規対応数'] else None)}→{number(right['追加5pt純額円']/right['実新規対応数'] if right['実新規対応数'] else None)}円")
    text += "今回の順行だけの追加片道5pt平均は" + "、".join(changes) + "。Rの参加減少という構成差に加え、順行自体の新しい参加集合も変わった。ただし少数のまま赤字で、支持付き70%や費用後安定黒字の裏付けにはならない。共通新規の出口を変えた効果とは分ける。\n\n"
    ranges = [f"{PERIOD_NAMES[p]}{by_role['3分_Q1_X0',p,'反転']['実新規対応数']}件" for p in PERIODS[:2]]
    text += "Q1反転の実参加は"+"、".join(ranges)+"。今回のSAR持続条件では反転をほとんど作れず、反転手法の成績改善を確認したとはしない。順行と反転を同じ総額だけでまとめない。\n\n"
    text += "### 共通実新規の出口差と参加集合差\n\n全純額差＝同じ実新規の出口差＋Q1のみ額−Q0のみ額。損益差をそのままSAR決済の効果とはしない。\n"
    rows = []
    for r in data["運用対応"]:
        pair = r["運用比較"]
        difference = pair["右側のみ純額円"] - pair["左側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"], pair["共通実新規純額差円"]+difference, abs_tol=1e-8):
            raise ValueError("実新規/参加差と全額差不一致")
        rows.append([PERIOD_NAMES[r["期間"]], f"{pair['共通実新規数']}/{pair['左側のみ実新規数']}/{pair['右側のみ実新規数']}",
                     number(pair["共通実新規純額差円"]), number(difference), number(pair["全運用純額差円"])])
    text += G.table(["期間", "共通/Q0のみ/Q1のみ実新規", "共通出口差円", "参加集合差円", "全純額差円"], rows)
    text += "### 同episodeの二役割と保有中抑止\n\n両役割の実参加ではR新規→R返済→T新規の順序と非重複を確認。同じepisode内を独立標本へ加算せず、役割発生で自動ドテンしない。\n"
    text += G.table(["候補", "期間", "Rのみepisode", "Tのみepisode", "両役割episode", "両役割基準観測円"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["反転のみ実参加episode数"], r["順行のみ実参加episode数"], r["両役割実参加episode数"], number(r["両役割基準純額円"])]
        for r in data["同episode役割順序"] if r["期間"] in PERIODS[:2]])
    text += G.table(["候補", "期間", "役割", "入口の取扱件数", "実完結"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["役割"], G.describe(r["運用入口取扱"]), r["実完結数"]]
        for r in data["役割別運用抑止"] if r["期間"] in PERIODS[:2]])
    text += "### 追尾設定と実約定\n\n同値未満/最終線不足は追尾起動後の取引に限る。同値床は手数料後の非赤字や線上の約定を保証しない。\n"
    text += G.table(["候補", "期間", "起動", "起動後純赤字", "同値未満約定", "最終線未満約定", "最終線から不足pt計"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["起動後同値未満約定数"], r["最終設定未満約定数"], number(r["最終設定からの不足pt計"])]
        for r in data["利益保護"] if r["期間"] in PERIODS[:2]])
    text += "### 価格余地の診断だけを次の問いへ残す\n\nRの公開終値から固定範囲反対端までを順方向余地、元境界までを無効化距離として集計した。実約定価格/費用/気配鮮度の余裕とは異なり、以下の条件を今回の注文gateへ加えていない。範囲外のTに架空の目標水準を作らない。\n"
    text += G.table(["期間", "集合", "件数", "反対端余地中央値pt", "無効化中央値pt", "余地>=250かつ無効化<=125"], [
        [PERIOD_NAMES[r["期間"]], r["集合"], r["件数"], number(r["反対端までの距離pt"]["中央値"]), number(r["元境界までの無効化距離pt"]["中央値"]), r["目標余地250以上かつ無効化125以内数"]]
        for r in data["価格余地診断"] if r["期間"] in PERIODS[:2]])
    coverage = [f"{PERIOD_NAMES[r['期間']]}{r['目標余地250以上かつ無効化125以内数']}/{r['件数']}件" for r in data["価格余地診断"] if r["期間"] in PERIODS[:2] and r["集合"] == "Q0"]
    text += "Q0反転のこの終値距離条件は" + "、".join(coverage) + "が既に該当する。ほぼ全件へ付く条件を新しくANDしても、今回の悪い反転を十分に区別する根拠にはならない。気配/約定起点・費用余裕や価格反応の持続を別に考え、成績を見て距離分位点を最適化しない。\n\n"
    return text


def explanation() -> tuple[str, str, str, str]:
    """独自SAR仕様と価格/勢いの役割を計画どおり説明する。

    引数: なし。
    返り値: tuple[str,str,str,str] は準備/状態/執行/限界。保存数値を再計算しない。
    """
    structure = "## 複数手法の役割と共通準備\n\n30分6本高安は価格構造、3分内復帰/外回復は発動位置。Q0はMACD12/26/9のヒスト差符号、Q1は公開済みの前足・現足SAR方向の持続を重ねる。SAR単独の注文は作らず、価格構造とSARが統計的に独立とは主張しない。15分ADX/DI/BB幅は両案の数値準備だけで、旧24E1の値選別へ使わない。\n\n"
    structure += "M24は同場隣接公開3分現在/前C・Hが有限、現在ATR14正、当時公開15分現前ペア準備済み、登録時固定30分出典有効、確認遅延<=30。M25はさらに現在/前の同場隣接公開SAR方向が±1であることを両案に同じく課す。方向が同じかはQ1の値条件で、準備条件へ混ぜない。新規停止前/返済期限まで残60分以上の時間条件も別。\n\n"
    structure += "Q0にもSAR準備を課すため、旧E0からQ0で失う原イベントと実参加を先に検算する。下位BB/K/RSI/VWAP/量をgateへ入れない。指標が数値準備済みなだけ、ATRを保護に使うだけでは複数の入口手法と数えない。量とRの終値構造距離は診断のみ。\n\n"
    logic = "## 価格状態とQ0/Q1\n\nsは元突破side、fの反転実方向r=−s、gは元方向s。売りは全て鏡像。価格登録/監視は固定24を読み取り再用し、SAR不準備でも最初の価格eventは同じ時計で消費する。\n"
    logic += G.table(["段階", "買い突破s=+1の価格条件", "複合採否"], [
        ["登録b", "前C<=R+ε<C、ε=max(5,ceil(.25ATR_b/5)*5)", "既知30分6本R/L・価格準備・時間可。S2/δH/SAR/遅延値で選別せず注文なし"],
        ["内復帰f", "b次1〜6の最初L<C<R、実side=−s", "M25/時間可、Q0は実sideδH>0、Q1は公開済み前足SAR方向=現足方向=実side"],
        ["外回復g", "f次1〜3の最初C>R、実side=s", "同じM25と各値条件。R+εやf高安の再突破は不要"],
    ])
    logic += "30分窓はb前の公開3分pまでにend/keyの両上限で既知の完全公開6本R=max高値/L=min安値を固定する。同限月carry、NP/欠枠/尾部完全欠枠/限月で内部clear。登録後の最新窓未準備で凍結出典を取消さない。\n\n"
    logic += "f/gはend>前段confirm、公開keystrict、同足二遷移なしのclose-only。start>confirmやヒゲ判定は課さない。買起点はC=R待機/C<=L取消、売はC=L待機/C>=R取消。価格不正/場・限月/期限→寿命6/3超過→時点対象外→反対端→初eventの順。時点対象外は寿命のみ進める。M/勢い/SAR/時間/遅延/保有中で不採用でも消費し、同足再登録も禁止する。global監視1件、used(side,境界)は当場一回・場頭reset。\n\n"
    logic += "### 独自SAR数値規約\n\nAF初期0.02・増分0.02・上限0.2。連続二本close差strict正/負で方向をseedし、同値なら未確定で次の隣接対を待つ。seed表示は買min(前low,現low)/売max(前high,現high)、EPは現high/low、AF初期。これはTA-Lib等と同一の初期値/等号規約だとはしない。\n\n"
    logic += "当足の事前線は前足next。買low<事前線/売high>事前線のstrict貫通で先に反転し、等号は非反転。非反転の表示線だけ前二本low以下/high以上へclampし、当足EPをstrict更新した時だけAFを増やす。反転表示は新買min(旧EP,現low)/新売max(旧EP,現high)、EP現・AF初期。次線は表示+AF×(EP−表示)で、next自体はclampしない。\n\n"
    logic += "事前線・足確定後表示・次足線/EP/AFと出典を別保存する。当足高安の確定後方向を当足開始時から使わない。欠枠/不正/尾部完全欠枠/限月変更でreset、同限月場間carry。末尾完全幅未公開足NPも内部数値は更新/carryするが公開現前pairへ不使用。OHLC非有限の原入力は不正clear/非投入で、保存出典の非有限だけNone正規化し時計/keyを補正しない。原OHLCの別手順と全足canonical SHAを照合する。\n\n"
    protection = "## 固定A5の保護・費用・場内完結\n\nSARを出口/保護線へ使わず固定24のnative通常出口なしX0を読み取る。hard125/TP250/期限、正常返済BBOの正益5ptでA5追尾、D=max(5,ceil(入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・線非緩和・最低新規同値。Rはf、TはgのATRをfill固定し、pending中の更新停止、役割fill固定・自動ドテンなし。優先は期限/既存待機約定→hard125→TP250→追尾。\n\n"
    protection += "ラージBBOをmicro1枚代理、倍率10円/pt・呼値5pt・片道11円の仮定。新規/返済要求+1価格秒以上の最初正常BBO、新規TTL30、買Ask/売Bid新規・返済側BBO、同原行気配→確定足→signal。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、参加経路は再生しない。価格時計は実受信時計と別。\n\n"
    protection += "デイは原範囲08:45〜15:40/新規停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50を維持し持ち越さない。同値設定と実約定同値・費用後黒字は別。正常板空白300秒超/EOF等の注意を含む全体確定額はnull。原shadowの先着対象は時間かつ遅延可、対象外は時間優先/次遅延で通常9数値None・未約定へ混ぜない。\n\n"
    limits = "## 限界と次の問い\n\n全65場（学習40/条件選択24/既使用11/4デイ1）は全て既使用の追加開発。SARの二本持続は独自仮説で、Fidelity/TradingViewの一般解説がNK225の125/250先着70%や利益を実証したものではない。出典URL・確認日2026-11-05は計画と共通議論へ残す。SARは極値と経過で動き、時間だけで線が近づくため、売買圧力の急増を直接測ったとはしない。心理は『単発の反応より元から続く方向へ参加が続くか』という仮説で注文動機の観測ではない。\n\n"
    limits += "MACDとSARを総当たりの票へ加算せず、同じ価格event・同じM25で勢いと持続の役割を対照した。数値準備除外、役割構成比、役割内成績、純発動と実参加を区別する。SARのseed/strict貫通/clamp順は固定した独自仕様で最適化した標準値ではない。RSI・移動平均線の例へ限定せず、次候補も手法一覧から役割を考えるが未実行を実績へ加えない。\n\n"
    limits += "仮先着は実返済後の経路も含み、実保有中MFEは事後の峰で全額回収可能とはしない。同episodeのR/Tや二案共通の成功を独立二票へ数えない。最大場内DDは期間累積DDと別。終値の価格余地は当時診断で、実約定/費用余裕や先着予測力を示していない。未来ラベルを当時条件へ戻さず、主条件変更は新試行へ分ける。固定後の未使用場による別確認まで将来の安定収益達成とはしない。\n\n"
    return structure, logic, protection, limits


def run(study: Path, output: Path) -> list[Path]:
    """正式完了後に全正本と固定SHAを確認して二文書を生成する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: list[Path] はREADME/設定と結果。先着・損益を再生しない。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json", "入口品質.json", "SAR品質.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT/path) != digest for path, digest in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定code/条件/計画/入力SHA変化")
    pointer = G.read_json(study/"入力台帳.json")
    manifest = (study/pointer["参照"]).resolve()
    if G.sha(manifest) != pointer["SHA256"]:
        raise ValueError("台帳参照SHA不一致")
    catalog = G.read_json(G.CATALOG)
    if (catalog["version"], len(catalog["methods"]), len(catalog["scales"])) != (1, 51, 9):
        raise ValueError("版1の51×9カタログと異なる")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    intro = "NK225の3分Q0/Q1＝二入口・固定A5/X0の二運用。固定24の30分高安・初終値内復帰R/外回復Tへ、Q0は単足MACDヒスト差、Q1は公開済み前足/現足SAR方向の持続を組み合わせる。両案は同じM25準備を使い、Q1へQ0や旧E1を追加ANDしない。数量とRの終値構造距離は診断のみ。全65場（40/24/既使用11/4デイ1）は既使用の追加開発。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2。** 方式差の純集合、R/T構成と役割内成績、実参加と共通出口差を分けて読む。\n\n"
    warnings = [f"{r['候補ID']}の{PERIOD_NAMES[p]}：{r[p]['運用']['品質注意場数']}場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意は"+"、".join(warnings)+"。注意を含む期の全体確定額はnullで、純額・平均・参加差は観測値として示す。\n\n"
    structure, logic, protection, limits = explanation()
    audit_text, audit_paths = audits(study, readme)
    summary = "# 試行00025：価格イベントとSAR方向持続\n\n"+intro
    summary += " / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json"))+" / "+G.link(mapping, readme)+"\n\n"
    summary += conclusion+structure+logic+protection+stages(study)+comparison(entries, values)+diagnosis(study, readme)+limits+audit_text
    # ----------------------------------------
    # 必須表は全51行/9尺度を保ち、設定と二評価の結果を同じ文書で対応させる。
    common = settings(rules)
    method_ids, scale_ids = {r["id"] for r in catalog["methods"]}, {r["id"] for r in catalog["scales"]}
    if any(set(r["手法ID"])-method_ids or set(r["尺度ID"])-scale_ids for r in common):
        raise ValueError("設定が51×9へ対応しない")
    mapped = "# 試行00025：設定と結果\n\n"+intro+conclusion
    mapped += G.link(G.MASTER, mapping, "コピー元汎用表")+" / "+G.link(readme, mapping)+" / "+G.link(study/"結果.json", mapping, "全二評価正本")+"\n\n"
    mapped += "## 手法×時間スケール\n\n版1の51手法×9尺度、R01/R02は複合評価、S01〜S13は設定。指標単独の効果は未検証。SAR数値準備だけと方向持続選別、数量/終値構造距離の診断だけを区別する。30分6本は構造の期間、30分間引きは機会の間引き。\n\n"
    mapped += G.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [
        [r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件の要約\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k,v in config.items()])
    mapped += "## 全二運用の定義と合否\n"+G.table(["評価", "候補", "共通価格イベント", "値条件", "両期入口支持", "70目標", "費用資格"], [
        [r["評価ID"], r["候補ID"], "初内復帰R/外回復T＋M25/時間", "実sideδH>0" if r["入口"]["戦略"] == "Q0" else "公開済み前足SAR方向=現足方向=実side",
         "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    mapped += comparison(entries, values)+structure+logic+protection+limits+audits(study,mapping)[0]
    # ----------------------------------------
    # 大きな全件転記を避け、正本・コード・独立証明・共通知見のSHAへ結ぶ。
    files = ("入力台帳.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json",
             "局面品質.json", "30窓品質.json", "数量診断品質.json", "SAR品質.json", "入力品質.json", "作業成果物.json")
    sources = [ROOT/"scripts/SAR持続"/n for n in ("README.md", "指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py") if (ROOT/"scripts/SAR持続"/n).exists()]
    docs = [ROOT/"docs/議論"/n for n in ("終値内復帰と外回復を上位状態で選別する.md", "複合手法の持続と価格余地を次に検証する.md", "SARの方向持続と価格内復帰を比較する.md") if (ROOT/"docs/議論"/n).exists()]
    preparation = [ROOT/"work/SAR持続/00025"/n for n in ("準備点検.json", "独立準備点検.json") if (ROOT/"work/SAR持続/00025"/n).exists()]
    viewing = "## 閲覧と再現\n\n"+" / ".join(G.link(study/n,readme) for n in files if (study/n).exists())+"\n\n"
    viewing += "コード："+" / ".join(G.link(p,readme) for p in sources)+"。背景："+" / ".join(G.link(p,readme) for p in docs)+"。\n\n"
    viewing += "ラベル/損益なし固定前準備："+" / ".join(G.link(p,readme) for p in preparation)+"。主/独立件数と65場SAR全足canonical SHAを照合。検算数を収益標本に加算しない。\n\n"
    viewing += "Viewerは事前Q0/Q1両案。market_pathは設定data_root、pnl_pathはcatalog基準。原板/画像/全件MDを複製せず、Git外workの10gzipと展開内容SHAを作業成果物へ残す。\n\n"
    fence = chr(96)*3
    viewing += "保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/SAR持続/レポート.py\n"+fence+"\n\n検証.pyは既存結果.jsonの上書きを拒否する。数値再生はコードREADMEの別保存先手順へ従う。--prepareは先着/損益を計算しない準備点検で正式損益再生ではない。固定後の合成追加は別名へ分け正本を上書きしない。\n\n"
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/終値切替/レポート.py", ROOT/"scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG, manifest,
             *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study/n).exists()], *audit_paths, *sources, *docs, *preparation]
    for path, text in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """保存帳票の表示先を指定して二文書を生成する。

    引数: なし。--study/--outputは正式試行/表示先。
    返り値: None。主価格再生・先着・新規選別をしない。
    """
    parser = argparse.ArgumentParser(description="価格イベントとSAR方向持続の保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study,args.output or args.study)))


if __name__ == "__main__":
    main()

