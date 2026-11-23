"""00023の保存結果から二運用の比較と必須51×9表だけを生成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00023_上位高安の再テストと順行再開"
DISPLAY = ROOT / "scripts/局面変化/レポート.py"
POLICIES = ("B0", "C0")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """既存の汎用表と保存集計の表示補助だけを読み込む。

    引数: なし。
    返り値: Any は表示モジュール。市場の先着や損益は再計算しない。
    """
    spec = importlib.util.spec_from_file_location("高安再開帳票の固定22表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """3分B0/C0と共通X0の二評価を定義する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は二入口と二運用の対応。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分B0/C0・共通X0と異なる")
    if config["価格再開"] != {"チャネル足分": 30, "チャネル本数": 6, "ε_ATR倍率": .25, "再テスト上限本数": 6, "再開上限本数": 3}:
        raise ValueError("固定チャネルと6/3寿命と異なる")
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
        raise ValueError("事前B0/C0表示と異なる")
    if report["入口70目標達成数"] != sum(row["70目標"] for row in entries.values()) or report["費用資格数"] != sum(row["費用資格"] for row in values.values()):
        raise ValueError("目標件数が不一致")
    return entries, values


def settings(rules: list[dict]) -> list[dict]:
    """価格構造・局面・発動・診断だけの量を51×9へ対応付ける。

    引数: rules (list[dict]) は二評価。
    返り値: list[dict] は使用セルの設定。未実行C1を評価済みにしない。
    """
    b, c = [rules[0]], [rules[1]]
    groups = [
        (["I03", "I05", "I07", "I09"], ["m03"], rules, "固定22下位三公開足・BB/H/K/ATR準備", "現在遅延<=30。時間条件は数値Mと別、数量/EMA/RSI/VWAPをgateへ加えない"),
        (["I05", "I08", "C04", "C07"], ["m15"], rules, "固定22 S2・同場公開現前ペア", "d!=0,a>0,(A>=25 OR Δw>0)でdT。A<=20,a<=0,Δw<=0でR、他WAIT。DXを独立二票にしない"),
        (["P02", "P03", "P06", "P07", "C07"], ["m30"], rules, "前3分pまでの完全公開30分6本高安", "同限月carry、NP/欠枠/尾部完全欠枠/限月clear。p.end/key両上限。R/Lと出典を設定で固定"),
        (["P07", "I03", "I09"], ["m03"], b, "B0：prevC<=R+ε<C・同方向S2T・sideΔH>0", "売鏡像。ε=max5,ceil(.25ATR_b/5)*5。新設定は停止前/残60以上、同水準sideは当場一回"),
        (["P10", "P04", "P03", "I03"], ["m03"], c, "C0：再test次1〜6→再開次1〜3", "start>setup/j.confirm strict。zone端等号可・回復/再開終値strict。初eligible crossは勢い/時間不可でも消費"),
        (["P01", "P03", "P06"], ["m03"], rules, "固定帯失敗・strict内復帰は別記録", "帯失敗L/Hはstart>setup.confirmだけ。内復帰は寿命内監視中L<C<R、等号/反対端別。取消後追跡なし"),
        (["I05", "I07"], ["m03"], rules, "S2Rは両案同じ旧22R1", "中心反対半面のSlowK20/80領域復帰。D/外帯内制約/価格改善の追加なし、共通30窓準備で除いた元Rも保存"),
        (["V01"], ["m03"], rules, "観測差分量/RVOLは診断だけ", "固定14helper、採否/状態/Mへ不使用。欠測でも発動不変。量選別C1は未実行で単独効果も未検証"),
        (["B01"], ["tick"], rules, "一建玉・新規/返済+1価格時計秒・TTL30", "ラージBBOをmicro1枚代理、買Ask/売Bid新規と返済側BBO、数量・流動性の同一性は仮定"),
        (["I09", "C06", "E02"], ["tick"], rules, "固定21 A5/入口ATRceil幅・最低同値ratchet", "hard125/TP250/期限、pending追尾停止、役割は実fill固定。設定同値と費用後黒字は別"),
        (["E01"], ["tick"], rules, "各新規から125逆行前250先着", "全仮約定分母、30分間引きは30分足でない。時間外shadowは対象外として未約定と区別"),
    ]
    return [{"設定ID": f"S{index:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(row["評価ID"] for row in applies), "適用評価": [row["評価ID"] for row in applies]}
            for index, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def comparison(entries: dict, values: dict) -> str:
    """二運用の三期間を先着・参加・費用後額へ分けて要約する。

    引数: entries/values (dict) は入口/運用のID別正本。
    返り値: str は小さな比較表。全保存列や全約定は転記しない。
    """
    rows = []
    for source, entry in entries.items():
        for period in PERIODS:
            e, o = entry[period], values[source + "_X0"][period]["運用"]
            rows.append([source, PERIOD_NAMES[period], e["候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",
                         f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",
                         o["完結取引数"], number(o["追加0pt純損益円"]), number(o["追加5pt純損益円"]),
                         number(o["追加5pt平均円"]), number(o["追加10pt純損益円"]), f"{o['活動場数']}/{o['入力場数']}", o["品質注意場数"]])
    text = "## 二運用の結果\n\n入口の仮保有先着と、一建玉運用の勝率/純額は別の分母。金額は観測純額で、注意場を含む全体の確定対象額はnullを維持する。既使用最終1場で旧二期間の支持不足を補わない。\n" + G.table(
        ["入口", "期間", "要求候補", "250先着/仮約定・率", "30分間引き順/仮約定・率", "完結", "基準円", "追加5pt円", "追加5pt平均円", "追加10pt円", "活動/入力場", "注意場"], rows)
    b, c = values["3分_B0_X0"], values["3分_C0_X0"]
    descriptions = []
    for period in PERIODS[:2]:
        a, z = b[period]["運用"], c[period]["運用"]
        change = "改善" if z["追加5pt平均円"] > a["追加5pt平均円"] else "悪化" if z["追加5pt平均円"] < a["追加5pt平均円"] else "同額"
        descriptions.append(f"{PERIOD_NAMES[period]}の完結{a['完結取引数']}→{z['完結取引数']}、追加5pt平均{number(a['追加5pt平均円'])}→{number(z['追加5pt平均円'])}円（{change}）")
    text += "B0→C0では" + "、".join(descriptions) + "。総損失が小さくても、取引数を減らした差と1取引の回収改善を同一視しない。\n\n"
    text += f"C0学習の仮約定は{entries['3分_C0']['学習']['約定候補数']}件。事前の学習支持は60件以上を要求し、条件選択や既使用最後1場を足して補わない。両案の複合全体の率だけで、遅い順行入口Tが改善したとは判定しない。\n\n"
    return text


def stages(study: Path) -> str:
    """共通価格監視の段階と取消理由を保存品質から要約する。

    引数: study (Path) は正式試行。
    返り値: str は三期間の段階件数。建玉や二戦略の重複件数と区別する。
    """
    data = G.read_json(study / "入口品質.json")
    keys = ("旧M22準備足数", "共通M準備足数", "設定数", "再テスト登録数", "再開価格消費数", "再開条件採用数",
            "再開採用数", "対象外足数", "先着評価対象外数", "旧R1発動数")
    rows, reasons = [], {period: Counter() for period in PERIODS}
    for period in PERIODS:
        local = [row for row in data if row["期間"] == period]
        rows.append([PERIOD_NAMES[period], *[sum(row[key] for row in local) for key in keys]])
        for row in local:
            reasons[period].update(row["終了理由別"])
    text = "## 準備と価格監視の段階\n\n価格監視は注文/建玉から独立した共通一件。設定→再テスト→価格再開→条件可→競合後のC0採用を分ける。『対象外足』はstrict開始条件で足全体の反応を使えなかった足、『先着評価対象外』は時間不可で消費した価格eventで、通常の未約定とは異なる。元R1には30分準備で除いた原発動も含む。\n"
    text += G.table(["期間", "旧M22足", "新M23足", "設定", "再test", "価格再開", "再開条件可", "C0T採用", "開始対象外足", "先着対象外event", "元R1"], rows)
    all_reasons = sorted({reason for counter in reasons.values() for reason in counter})
    text += "### 監視の終了理由\n\n寿命外の第7/第4足を帯失敗や内復帰に加算せず、数値/公開不正・期限は満了より先に扱う。取消同足のstrict内復帰と、取消後の未来足を分け、後者は追跡しない。\n"
    text += G.table(["理由", *[PERIOD_NAMES[period] for period in PERIODS]], [[reason, *[reasons[period][reason] for period in PERIODS]] for reason in all_reasons])
    return text


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """正式proofの存在と明示合否を別々に表示する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: tuple[str,list[Path]] は合否表と参照元。検査数を収益標本へ合算しない。
    """
    titles = [("合成検証.json", "最終43人工合成・編集終了"), ("独立監査.json", "先着/会計/正式成果物"),
              ("状態独立確認.json", "原価格の30窓/監視/全集合"), ("追尾独立確認.json", "A5初着と原気配/役割"),
              ("対応診断.json", "episode/共通R/参加と回収"), ("Viewer照合.json", "B0/C0のAPI表示")]
    rows, paths = [], []
    for name, title in titles:
        path = study / name
        if not path.exists():
            rows.append([title, "未完・未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
        elif name == "対応診断.json" and verdict is None:
            verdict = data.get("対応集合全件一致")
        elif name == "Viewer照合.json" and verdict is None:
            checks = data.get("照合", [])
            verdict, count = (all(check.get("一致") is True for check in checks) if checks else None), len(checks)
        rows.append([title, "一致/合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n最終43合成の編集終了trueと関係6SHAを確認してから固定した。存在だけで合格とせず明示判定を読み、未保存は未完表示にする。主/状態/追尾/人工/対応は重なる観測を含む別範囲で、独立収益標本へ合算しない。\n"
    text += G.table(["範囲", "明示合否", "件/項目", "正本"], rows)
    text += "全戦略の競合確定後にcaseを深く複写し、自己採否だけでなく全caseの全verdictとcanonical shadowの一致を確認する。模型と保存成果物の一致は、空白内経路や将来収益の証明ではない。\n\n"
    viewer = study / "Viewer照合.json"
    if viewer.exists():
        data = G.read_json(viewer)
        text += "Viewerは事前B0/C0の表示で、結果から案を採用する操作ではない。market_pathは設定のdata_root基準、pnl_pathは一覧のcatalog基準。PNG追加" + str(data.get("追加PNG数", 0)) + "枚。\n"
        text += str(data.get("接続先", "接続先未記録")) + "・設定 " + str(data.get("設定", "未記録")) + "・起動 " + str(data.get("WindowStyle", "未記録")) + "。\n\n"
        checks = data.get("照合", [])
        if checks and all("API最終状態" in row for row in checks):
            text += G.table(["候補", "場", "研究/API実現円", "API買/売保有", "指紋", "一致"], [
                [row["手法"], row["場"], f"{number(row['研究側純損益円'])}/{number(row['API最終状態']['realized_pnl_yen'])}",
                 f"{row['API最終状態']['long_qty']}/{row['API最終状態']['short_qty']}",
                 "一致" if row.get("数値本文SHA256一致") else "不一致/未確認", "一致" if row["一致"] else "不一致"] for row in checks])
    return text, paths


def diagnosis(study: Path, output: Path) -> str:
    """対応診断の明示状態を表示し、入口移動と出口差を混同しない。

    引数: study/output (Path) は正式試行/表示先。
    返り値: str は要約と正本へのリンク。全件の転記は行わない。
    """
    path = study / "対応診断.json"
    text = "## episodeと参加集合の解釈\n\nB0とC0は同じ突破episodeでも新規時点/価格が異なる。B0新規からの250先着とC0新規からの250先着を同じ事例の成功二票へ数えない。純発動は保有に依存せず、実運用は一建玉/待機により参加が変わる。共通R1の純候補が同じでも、順行取引の保有時間によってR1の実参加も変わる。\n\n"
    if not path.exists():
        return text + "対応診断は未完・未保存。保存後に同episode/共通実新規/片側参加/費用と追尾不足を反映する。\n\n"
    data = G.read_json(path)
    if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study / "結果.json"):
        raise ValueError("対応診断の結果SHA不一致")
    verdict = data.get("全件一致", data.get("対応集合全件一致"))
    text += G.link(path, output) + "：" + ("一致" if verdict is True else "不一致/明示合否未確認") + "・" + number(data.get("照合項目数")) + "項目。総純額差をそのまま出口改善とせず、実新規が共通の出口差と片側の参加額を別に参照する。未来先着/MFEは診断限定で、再参加の当時条件へ戻さない。\n\n"
    text += "### 元の発動・要求採用・遅い新規を分ける\n\n下表は価格原発動と戦略採用を分けた事後診断。T再開の時間外消費は対象外へ分け、未約定にも失敗にも入れない。採用率が上がっても元の発動と同一の新規時計/価格ではない。\n"
    rows = []
    for period in PERIODS[:2]:
        for family in ("T突破", "T再開", "R1"):
            subset = [row for row in data["発動と監視終了別"] if row.get("期間") == period and row.get("系統") == family]
            raw, accepted = Counter(), Counter()
            for row in subset:
                raw.update({key: value for key, value in row["全原発動"].items() if key != "確認率"})
                accepted.update({key: value for key, value in row["採用"].items() if key != "確認率"})
            rows.append([PERIOD_NAMES[period], family, raw["候補数"], raw["対象外数"],
                         f"{raw['順行先着']}/{raw['約定候補数']}", accepted["候補数"],
                         f"{accepted['順行先着']}/{accepted['約定候補数']}"])
    text += G.table(["期間", "元の系統", "原発動", "時間対象外", "原250/仮約定", "戦略採用", "採用250/仮約定"], rows)
    continuation = []
    for period in PERIODS[:2]:
        subset = [row["採用"] for row in data["発動と監視終了別"] if row.get("期間") == period and row.get("系統") == "T再開"]
        continuation.append(f"{PERIOD_NAMES[period]}{sum(row['順行先着'] for row in subset)}/{sum(row['約定候補数'] for row in subset)}")
    text += "C0の順行再開だけの250先着は" + "、".join(continuation) + "。複合C0全体には共通R1の成功も含むため、全体率のわずかな上昇をT再開の改善に読み替えない。\n\n"
    text += "### 共通R1の30分準備除外\n\n純R1の式は変更していない。旧22採用と新M23採用の差を、R1の発動式が改善した効果へ数えない。\n"
    text += G.table(["期間", "旧22S2のR採用", "新M23のR採用", "除外数", "除外の順/逆/期限/不足/未約定"], [
        [PERIOD_NAMES[row["期間"]], row["旧22S2_R1採用"]["候補数"], row["新M23_R1採用"]["候補数"],
         row["30窓等で除外された旧採用"]["候補数"],
         "/".join(str(row["30窓等で除外された旧採用"][key]) for key in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定"))]
        for row in data["旧R1準備差"] if row["期間"] in PERIODS[:2]])
    text += "### C0まで進んだ同episodeの入口比較\n\n再開を採用できたepisodeだけの条件付き対応で、待てば必ず改善するという因果的比較ではない。方向化価格差の正はC0が順行側へ動いた後の新規、負はより有利な価格。突破時と再開時の125/250は各新価格を起点にする。\n"
    text += G.table(["期間", "再開採用episode", "同群B0時250/仮約定", "C0時250/仮約定", "待機分中央値", "方向化価格差中央値pt"], [
        [PERIOD_NAMES[row["期間"]], row["再開採用episode数"],
         f"{row['同じepisode突破時先着']['順行先着']}/{row['同じepisode突破時先着']['約定候補数']}",
         f"{row['同じepisode再開時先着']['順行先着']}/{row['同じepisode再開時先着']['約定候補数']}",
         number(row["要求待機分"]["中央値"]), number(row["方向化した仮新規価格差pt_C0引くB0"]["中央値"])]
        for row in data["同episode入口対応"] if row["期間"] in PERIODS[:2]])
    text += "### 順行と反転の平均を分ける\n\n混合平均には役割の構成比が入る。下表は追加片道5pt後の完結取引を役割ごとに集計したもので、純入口の先着率とは別。\n"
    by_role = {(row["候補ID"], row["期間"], row["役割"]): row for row in data["入口先着と利益回収"]}
    role_rows = []
    for period in PERIODS[:2]:
        for role in ("順行", "反転"):
            left, right = by_role["3分_B0_X0", period, role], by_role["3分_C0_X0", period, role]
            a, b = left["実新規対応数"], right["実新規対応数"]
            role_rows.append([PERIOD_NAMES[period], role, a, b, number(left["追加5pt純額円"]), number(right["追加5pt純額円"]),
                              number(left["追加5pt純額円"] / a if a else None), number(right["追加5pt純額円"] / b if b else None)])
        trend_left, trend_right = by_role["3分_B0_X0", period, "順行"], by_role["3分_C0_X0", period, "順行"]
        if trend_right["追加5pt純額円"] / trend_right["実新規対応数"] >= trend_left["追加5pt純額円"] / trend_left["実新規対応数"]:
            raise ValueError("固定観測の順行平均悪化と異なる結果")
        range_left, range_right = by_role["3分_B0_X0", period, "反転"], by_role["3分_C0_X0", period, "反転"]
        if (range_left["実新規対応数"], range_left["追加5pt純額円"]) != (range_right["実新規対応数"], range_right["追加5pt純額円"]):
            raise ValueError("固定観測のR1実参加同値と異なる結果")
    text += G.table(["期間", "役割", "B0完結", "C0完結", "B0追加5pt円", "C0追加5pt円", "B0平均円", "C0平均円"], role_rows)
    text += "今回の順行だけの追加5pt平均は、学習・条件選択ともC0で悪化した。条件選択の混合平均だけの改善を、T再テスト/待機の質改善とはしない。共通R1の14/22完結と金額は同値で、条件選択ではR1の平均が順行より良い。順行の参加を50→4へ減らし、相対的にR1の比率を上げた構成比の変化を分けて読む。\n\n"
    text += "### 共通実新規の出口差と参加差\n\n同じ実新規での右−左出口差と、右だけ純額−左だけ純額を加えた値が全純額差。順行の新規を遅らせることで反転R1の参加も変わるため、共通R1の候補同値だけから実運用同値とはしない。\n"
    paired_rows = []
    for row in data["運用対応"]:
        if row["期間"] not in PERIODS[:2]:
            continue
        pair = row["運用比較"]
        participation = pair["右側のみ純額円"] - pair["左側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"], pair["共通実新規純額差円"] + participation, abs_tol=1e-8):
            raise ValueError("共通実新規と参加差の分解が不一致")
        paired_rows.append([PERIOD_NAMES[row["期間"]], f"{pair['共通実新規数']}/{pair['左側のみ実新規数']}/{pair['右側のみ実新規数']}",
                            number(pair["共通実新規純額差円"]), number(participation), number(pair["全運用純額差円"])])
    text += G.table(["期間", "共通/B0のみ/C0のみ実新規", "共通出口差円", "参加集合差円", "全純額差円"], paired_rows)
    text += "同じepisodeで両運用が実参加した順行取引は、時点/価格/入口ATRが違うので純粋な出口比較から分ける。\n"
    text += G.table(["期間", "両側実参加episode", "同群B0純額円", "C0純額円", "B0のみ/C0のみepisode"], [
        [PERIOD_NAMES[row["期間"]], row["両運用実参加episode数"], number(row["同episode_B0純額円"]), number(row["同episode_C0純額円"]),
         f"{row['B0のみ実参加episode数']}/{row['C0のみ実参加episode数']}"]
        for row in data["同episode実参加対応"] if row["期間"] in PERIODS[:2]])
    text += "### 追尾設定と実回収\n\n同値以上の設定と費用後の黒字は別。実新規から期限までの仮250先着は、追尾返済後の経路も含む。保有中250ptを得て失った件数とは呼ばない。\n"
    text += G.table(["候補", "期間", "起動", "起動後純赤字", "同値未満約定", "最終線未満約定", "最終線から不足pt計"], [
        [row["候補ID"], PERIOD_NAMES[row["期間"]], row["追尾起動数"], row["起動後純赤字数"], row["起動後同値未満約定数"],
         row["最終設定未満約定数"], number(row["最終設定からの不足pt計"])] for row in data["利益保護"] if row["期間"] in PERIODS[:2]])
    return text


def run(study: Path, output: Path) -> list[Path]:
    """正式完成通知後に保存値から二文書を生成する。

    引数: study/output (Path) は正式試行/文書先。
    返り値: list[Path] はREADMEと設定と結果。価格再生や新しい選別はしない。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json", "入口品質.json"):
        if not (study / name).is_file():
            raise ValueError(name + "未保存")
    config, report = G.read_json(study / "条件.json"), G.read_json(study / "結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT / path) != digest for path, digest in G.read_json(study / "固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定code/条件/計画/入力SHAが変化")
    pointer = G.read_json(study / "入力台帳.json")
    manifest_path = (study / pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳参照のSHA不一致")
    catalog = G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping_path = output / "README.md", output / "設定と結果.md"
    intro = "NK225の3分B0/C0＝二入口・共通A5/X0の二運用。30分高安を価格構造、15分S2を局面、3分を発動時計へ分担した。数量は診断のみでC1未実行。全65場（学習40/条件選択24/既使用11/4デイ1）は全て既使用の追加開発で、内部の後続確認も未見ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2。** 先着率は運用勝率ではなく、候補数・活動・品質と費用後額を分けて読む。\n\n"
    structure = "## 準備と各時間足の役割\n\n固定22の下位三公開足BB/H/K/ATR・同場15分現前ペア・現在確認遅延<=30に、前公開3分足pまでの30分6本窓を加える。R1も両案でこのM23へ揃え、30分準備で失う元R1を別記録。数値Mと新規停止/残60分の時間条件は分ける。下位EMA/RSI/nativeVWAP/数量を新しいgateへ足さない。\n\n"
    structure += "30分は完全公開6本のR=max高値/L=min安値、R>L。各出典end<=p.endかつ公開(clock,line)<=p判断key。突破足bと同時に知る30分足を先取りしない。同限月carry可、完全幅NP/欠枠/尾部完全欠枠/限月変更で内部窓clear、末尾partialは含めない。非公開markerは過去public snapshotを改訂せず、次の公開足から窓を再構成する。\n\n"
    structure += "15分S2はd!=0,a>0,(A>=25 OR Δw>0)ならd方向T、A<=20,a<=0,Δw<=0ならR、他WAIT。A=ADX/a=現前差/w=4母σ/SMA20/d=DI方向。DX−A=13aは同じ14平滑の恒等式で独立二票ではない。公開現前の準備・as-ofと指標bankは固定21/22同値。\n\n"
    logic = "## 価格状態の順序\n" + G.table(["段階", "買い側", "時点/消費"], [
        ["突破b・B0", "前C<=R+ε<C、同方向S2T、ΔH>0", "ε=max(5,ceil(.25ATR_b/5)*5)。境界/ε/30分出所を凍結して要求"],
        ["再テストj", "low∈[R−ε,R+ε]、C>R", "b次1〜6、start>b.confirm strict。最初の足を固定"],
        ["再開k・C0", "C>j.high、同方向S2T、ΔH>0", "j次1〜3、start>j.confirm strict。前C追加crossなし。最初eligible価格超えを消費"],
        ["反転R1", "S2Rで中心反対半面のSlowK20/80復帰", "両案で同じ固定22発動。T取消同足にも独立受付可"],
    ])
    logic += "売りは鏡像。再テストzone端は等号可、回復/再開終値はstrict。開始<=公開の足はヒゲや再開を使わず寿命だけ進め、後の最初eligible超えを使う。帯割れ高安の判定もstart>setup.confirmに限定し、再開待ちでも基準はsetup.confirm。\n\n"
    logic += "監視は全体一件、旧監視→新設定の順。公開/数値/連続性不正・返済期限→age>6/3満了→eligible帯失敗→同方向S2T消失→対象足/再開を優先する。取消/満了/消費同足のT再登録は禁止、used(side,境界)は取消後も当場保持し場頭reset。既存監視の初価格再開は有限H差非正や時間不可でも消費するが、数値/公開不正は先に取消。新設定は時間不可で登録しない。建玉中だから価格監視を延命しない。\n\n"
    logic += "時間外に消費したshadowは先着APIへ渡さず、評価対象false・ラベル対象外・要求時間条件外・通常数値9個None。未約定や通常五分類の先着率分母へ混ぜない。時間内で勢い条件だけ不成立のshadowは通常の事後先着診断が可能。量の欠測・RVOL値はM/状態/採否を変えない。\n\n"
    protection = "## 出口・費用は変更しない\n\n固定21/22のnative不使用A5エンジンを読取再用。hard125/TP250/期限、5pt正益の実観測で追尾起動、D=max(5,ceil(入口ATR/5)*5)、最低新規同値・買ceil/売floor・ratchetのみ。C0の入口ATRはkの値で、bのATRを追尾へ流用しない。pending中追尾更新停止、役割は実fillで固定し保有中の局面だけでドテンしない。\n\n"
    protection += "ラージBBOをmicro1枚代理、倍率10円/pt・呼値5pt・片道11円。要求+1価格時計秒以上の最初正常BBO、新規TTL30、買Ask/売Bid新規・返済側BBO。価格時計は受信時計ではない。追加片道5/10ptは同じ完結往復から100/200円控除する費用感度で、参加経路を再生し直した結果ではない。同値設定は実約定同値や費用後黒字の保証でない。\n\n"
    limits = "## 限界\n\n突破後の支持抵抗の役割変化や売り吸収は仮説で、参加者の意図を測ったものではない。30分6本/0.25ATR/寿命6・3が最適と示した実験でもない。旧22との直接差にはM23準備と新発動の変更が入り、同一母集団の入口改善とは呼ばない。C0待機の減少分には失敗の回避と成功の取り逃しの両方がある。\n\n"
    limits += "観測BBO空白300秒超/EOF/未解消を含む全体確定額はnullのまま。最大場内DDは期間の累積DDではない。保存MFEは実保有区間の将来峰で、回収可能額ではない。仮125-250先着は実返済後の経路も含むため、実現利益や当時の再参加特徴へ変換しない。共通発動・同episode・重複候補を独立の成功票へ重複計数しない。\n\n"
    audit_text, audit_paths = audits(study, readme)
    summary = "# 試行00023：上位高安の再テストと順行再開\n\n" + intro
    summary += " / ".join(G.link(study / name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json")) + " / " + G.link(mapping_path, readme) + "\n\n"
    summary += conclusion + structure + logic + protection + stages(study) + comparison(entries, values) + diagnosis(study, readme) + limits + audit_text
    common = settings(rules)
    method_ids, scale_ids = {row["id"] for row in catalog["methods"]}, {row["id"] for row in catalog["scales"]}
    if any(set(row["手法ID"]) - method_ids or set(row["尺度ID"]) - scale_ids for row in common):
        raise ValueError("設定が51×9へ対応しない")
    mapping = "# 試行00023：設定と結果\n\n" + intro + conclusion
    mapping += G.link(G.MASTER, mapping_path, "コピー元の汎用表") + " / " + G.link(readme, mapping_path) + " / " + G.link(study / "結果.json", mapping_path, "全二評価の正本") + "\n\n## 手法×時間スケール\n\n51手法×9尺度。R01/R02は複合評価で、30分6本は過去3時間程度の構造、30分間引きは機会の間引き。量は記録だけ・C1未実行で、量単独の採用効果は未検証。\n\n"
    mapping += G.matrix(catalog, mapping_path, common)
    mapping += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [
        [row["設定ID"], "/".join(row["手法ID"]) + "・" + "/".join(row["尺度ID"]), row["短記"], row["説明"], "・".join(row["適用評価"])] for row in common])
    mapping += "## 全固定条件の要約\n" + G.table(["項目", "固定値"], [[key, G.describe(value)] for key, value in config.items()])
    mapping += "## 全二運用の定義と合否\n" + G.table(["評価", "候補", "順行発動", "R1", "支持", "70目標", "費用資格"], [
        [row["評価ID"], row["候補ID"], "突破即時" if row["入口"]["戦略"] == "B0" else "再テスト後再開", "共通固定22", "充足" if values[row["候補ID"]]["入口支持"] else "未達",
         "達成" if values[row["候補ID"]]["70目標"] else "未達", "充足" if values[row["候補ID"]]["費用資格"] else "未達"] for row in rules])
    mapping += structure + logic + protection + limits + audits(study, mapping_path)[0]
    files = ("入力台帳.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json",
             "局面品質.json", "30窓品質.json", "数量診断品質.json", "入力品質.json", "作業成果物.json")
    viewing = "## 閲覧と再現\n\n" + " / ".join(G.link(study / name, readme) for name in files if (study / name).exists()) + "\n\n"
    sources = [ROOT / "scripts/高安再開" / name for name in ("指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py")
               if (ROOT / "scripts/高安再開" / name).exists()]
    docs = [ROOT / "docs/議論" / name for name in ("ADXと上位BB幅で始動と失速を分ける.md", "高位高安の再テスト待ちと入口価格を比較する.md")
            if (ROOT / "docs/議論" / name).exists()]
    viewing += "コード：" + " / ".join(G.link(path, readme) for path in sources) + "。背景：" + " / ".join(G.link(path, readme) for path in docs) + "。\n\n"
    viewing += "Viewerは事前B0/C0のみ、market_pathは設定の市場root基準。原板や大量画像を複製せず、全監視/30窓/raw/context/局面/入口/運用/追尾はGit外workの圧縮JSONLと内容SHAを参照する。\n\n"
    fence = chr(96) * 3
    viewing += "保存結果の再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/高安再開/レポート.py\n" + fence + "\n\n数値再生は検証.pyの別保存先へ行う。固定後の合成追加は別名へ分離し、既存正本を上書きしない。\n\n"
    paths = [Path(__file__), DISPLAY, ROOT / "scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG, manifest_path,
             *[study / name for name in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study / name).exists()],
             *audit_paths, *sources, *docs]
    for path, text in ((readme, summary + viewing), (mapping_path, mapping)):
        path.write_text(text + G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping_path]


def main() -> None:
    """正式結果の完成通知後に表示先を指定して二文書を生成する。

    引数: なし。--study/--outputは任意の正式試行/表示先。
    返り値: None。価格・ラベル・損益の再生をしない。
    """
    parser = argparse.ArgumentParser(description="上位高安の再テストと再開の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(path) for path in run(args.study, args.output or args.study)))


if __name__ == "__main__":
    main()
