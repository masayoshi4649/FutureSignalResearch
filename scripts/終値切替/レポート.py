"""00024の保存結果から二運用の比較と必須51×9表だけを生成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00024_終値の内復帰と外回復による順行反転"
DISPLAY = ROOT / "scripts/局面変化/レポート.py"
POLICIES = ("E0", "E1")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """既存の汎用表と保存集計の表示補助だけを読み込む。

    引数: なし。
    返り値: Any は表示モジュール。市場の先着や損益は再計算しない。
    """
    spec = importlib.util.spec_from_file_location("終値切替帳票の固定22表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """3分E0/E1と共通X0の二評価を定義する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は二入口と二運用の対応。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分E0/E1・共通X0と異なる")
    if config["終値切替"] != {"チャネル足分": 30, "チャネル本数": 6, "ε_ATR倍率": .25, "内復帰上限本数": 6, "外回復上限本数": 3}:
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
        raise ValueError("事前E0/E1表示と異なる")
    if report["入口70目標達成数"] != sum(row["70目標"] for row in entries.values()) or report["費用資格数"] != sum(row["費用資格"] for row in values.values()):
        raise ValueError("目標件数が不一致")
    return entries, values


def settings(rules: list[dict]) -> list[dict]:
    """使用・数値準備・診断の役割を汎用51×9へ対応付ける。

    引数: rules (list[dict]) は事前二評価。
    返り値: list[dict] は設定IDと適用評価。指標単独の効果は示さない。
    """
    e0, e1 = [rules[0]], [rules[1]]
    groups = [
        (["I03", "I09"], ["m03"], rules, "M24：同場隣接公開C/H・現在ATR正", "現在前C/H有限、当時公開15pair・固定30出典・遅延<=30。時間条件別。下位BB/K/RSI/VWAP/量の準備を課さない"),
        (["I05", "I08", "C07"], ["m15"], e0, "E0は公開現前ペアの数値準備のみ", "上位数値の欠測は共通M。E0の方向/採否にS2やΔADXの値は使わず、上位選別の対照とする"),
        (["I05", "I08", "C04", "C07"], ["m15"], e1, "E1：Rは実方向TまたはΔADX<=0、Tは実方向T", "S2T=d!=0,a>0,(A>=25 OR Δw>0)。反転の非上昇は横ばいも含む。DI方向とADX強さを区別しDXを独立票にしない"),
        (["P02", "P03", "P06", "P07", "C07"], ["m30"], rules, "前公開3分pまでの完全公開30分6本R/L", "出典end<=p.endかつ公開key<=p.key。同限月carry、NP/欠枠/尾部完全欠枠/限月でclear。登録時凍結、後段の最新窓未準備でも取消しない"),
        (["P07", "I09"], ["m03"], rules, "登録b：prevC<=R+ε<C、ε=max5,ceil(.25ATR/5)*5", "売り鏡像。時間可、global監視1、used(side,境界)当場一回。登録は注文でなく、S2/勢い不問・遅延>30可"),
        (["P01", "P03", "P04", "P06", "I03"], ["m03"], rules, "反転f：次1〜6足の初L<C<R、r=-s・rΔH>0", "end>前段confirmかつ公開keystrict。最初価格eventをM/勢い/上位/時間/遅延不可でも消費し内側へ。ヒゲ不使用"),
        (["P01", "P03", "P04", "P07", "I03"], ["m03"], rules, "順行g：f次1〜3足の初C>R/売C<L・sΔH>0", "R+εやf高安の再突破不要。初eventを消費して終了、後の都合のよい足へ取り直さない。反対端等号は取消し、元端等号は待機"),
        (["V01"], ["m03"], rules, "観測差分量/RVOLは診断のみ", "固定14helper、欠測/0/値によりM・価格状態・採否は変わらない。全約定量/flow/OIではなく量選別効果は未検証"),
        (["B01"], ["tick"], rules, "一建玉・新規/返済+1価格秒・新規TTL30", "ラージBBOをmicro1枚代理、買Ask/売Bid新規と返済側BBO。役割は実fill固定、自動ドテンなし"),
        (["I09", "C06", "E02"], ["tick"], rules, "A5/実入口ATRceil幅・最低新規同値ratchet", "hard125/TP250/期限。D=max5,ceil(ATR_f又はg/5)*5。pending追尾停止。同値設定と実約定/費用後黒字は別"),
        (["E01"], ["tick"], rules, "各新規から125逆行前250先着", "時間かつ遅延可の仮約定が分母。対象外は時間優先/次に遅延、通常9数値None。30分間引きは30分足不使用"),
    ]
    return [{"設定ID": f"S{index:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(row["評価ID"] for row in applies), "適用評価": [row["評価ID"] for row in applies]}
            for index, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def comparison(entries: dict, values: dict) -> str:
    """固定二案の先着・参加・費用・支持を別分母で表示する。

    引数: entries/values (dict) は入口/運用のID別正本。
    返り値: str は三期間の小表。全明細を複製しない。
    """
    rows, supports = [], []
    for source, entry in entries.items():
        for period in PERIODS:
            e, o = entry[period], values[source + "_X0"][period]["運用"]
            rows.append([source, PERIOD_NAMES[period], e["候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",
                         f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",
                         o["完結取引数"], number(o["追加0pt純損益円"]), number(o["追加5pt純損益円"]),
                         number(o["追加5pt平均円"]), number(o["追加10pt純損益円"]), f"{o['活動場数']}/{o['入力場数']}", o["品質注意場数"]])
            if period in PERIODS[:2]:
                supports.append([source, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}",
                                 f"{o['完結取引数']}/{o['活動開始日数']}/{o['活動場数']}", f"{o['買い取引数']}/{o['売り取引数']}",
                                 "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達",
                                 "充足" if values[source + "_X0"]["費用資格"] else "未達"])
    text = "## 二運用の結果\n\n入口の仮保有先着は、一建玉運用の売買勝率/実現額と別の分母。金額は観測純額で、注意場を含む全体確定額はnullを維持する。\n"
    text += G.table(["入口", "期間", "要求候補", "250先着/仮約定・率", "30分間引き順/仮約定・率", "完結", "基準円", "追加5pt円", "追加5pt平均円", "追加10pt円", "活動/入力場", "注意場"], rows)
    text += "### 支持と活動頻度\n\n入口は学習60約定/6日/10場、条件選択20/3/5と両期70%以上、30分間引き20/10件と両期70%以上。費用は学習20完結/6日/10場/買売各5、選択10/3/6/各3、注意0・追加片道5pt後の両期黒字を全て要する。\n"
    text += G.table(["入口", "期間", "仮約定/日/場", "完結/日/場", "実買/売", "両期入口支持", "70目標", "費用資格"], supports)
    text += "既使用最後1場の高率や両期合算で支持不足を補わない。E1の上位選別で総損失が減っても、取引減少・役割構成比・1取引平均・安定黒字を別々に判定する。\n\n"
    return text


def stages(study: Path) -> str:
    """価格登録から二役割の採否までを保存品質から分ける。

    引数: study (Path) は正式試行。
    返り値: str は三期間の段階/終了理由。注文の採否と価格消費を混ぜない。
    """
    data = G.read_json(study / "入口品質.json")
    rows, events, reasons = [], [], {p: Counter() for p in PERIODS}
    keys = ("共通M準備足数", "登録候補数", "設定数", "登録遅延超数", "内復帰価格消費数", "外回復価格消費数", "対象外足数", "先着評価対象外数")
    for period in PERIODS:
        local = [row for row in data if row["期間"] == period]
        rows.append([PERIOD_NAMES[period], *[sum(row.get(key, 0) for row in local) for key in keys]])
        for row in local:
            reasons[period].update(row["終了理由別"])
        for role in ("反転", "順行"):
            items = [s for row in local for s in row["イベント段階"] if s["役割"] == role]
            fields = ("原価格イベント数", "時間可数", "確認遅延可数", "先着評価対象数", "M時間通過数", "勢い通過E0数", "上位通過E1数")
            events.append([PERIOD_NAMES[period], role, *[sum(s[key] for s in items) for key in fields]])
    text = "## 準備・価格消費・入口選別\n\n価格監視は注文/建玉と独立。登録は遅延30秒超でも可能だが注文ではない。価格イベントの時間/遅延不可や指標不成立も最初のf/gを消費する。『時点対象外足』はend/key条件で反対端も判定しない足、『先着対象外event』は時間/確認遅延でラベルを付けない事例。\n"
    text += G.table(["期間", "M24足", "生登録候補", "登録", "遅延超登録", "内復帰f", "外回復g", "時点対象外足", "先着対象外event"], rows)
    text += G.table(["期間", "役割", "価格event", "時間可", "遅延可", "先着対象", "M+時間", "価格+勢いE0", "上位E1"], events)
    text += "時間可と遅延可は各条件の周辺件数で、直列の減算表ではない。先着対象は両方可、M+時間は数値/公開準備も必要。上位選別前の準備やMACDでの除外を、E1上位条件の効果に加えない。\n\n"
    text += "### 監視の終了理由\n\n第7/第4足は満了。価格不正/期限、寿命、時点、反対端、初価格eventの順を維持し、指標やS2変化だけで監視を取り消さない。\n"
    all_reasons = sorted({r for c in reasons.values() for r in c})
    return text + G.table(["理由", *[PERIOD_NAMES[p] for p in PERIODS]], [[r, *[reasons[p][r] for p in PERIODS]] for r in all_reasons])


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """正式証明の明示合否と検査範囲を表示する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: tuple[str,list[Path]] は合否表と参照元。存在だけで合格扱いしない。
    """
    titles = [("合成検証.json", "最終33人工合成・編集終了"), ("独立監査.json", "先着/Decimal会計/正式成果物"),
              ("状態独立確認.json", "原価格の固定30窓/監視/全二集合"), ("追尾独立確認.json", "全保有のA5初着/原気配/役割"),
              ("対応診断.json", "上位選別/episode/参加と回収"), ("Viewer照合.json", "E0/E1のAPI表示")]
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
            verdict, count = (all(c.get("一致") is True for c in checks) if checks else None), len(checks)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study / "結果.json"):
            raise ValueError(name + "の結果SHA不一致")
        rows.append([title, "一致/合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n最終33合成の編集終了trueと関係6SHAを確認してから固定。ラベルなし主/独立準備も固定前に照合した。原価格再構成・保有追尾・会計・人工経路・対応診断には重なる観測があり、検算件数を独立収益標本へ合算しない。\n"
    text += G.table(["範囲", "明示合否", "件/項目", "正本"], rows)
    text += "全戦略の競合確定後にcaseを深く複写し、全caseの全verdictをcanonical shadowと照合する。保存/模型の一致は、板空白内の実経路や将来収益を証明しない。\n\n"
    viewer = study / "Viewer照合.json"
    if viewer.exists():
        data = G.read_json(viewer)
        text += "Viewerは事前E0/E1の表示。market_pathは設定のdata_root基準、pnl_pathは一覧catalog基準。PNG追加" + str(data.get("追加PNG数", 0)) + "枚。\n\n"
        text += str(data.get("接続先", "接続先未記録")) + "・設定 " + str(data.get("設定", "未記録")) + "・起動 " + str(data.get("WindowStyle", "未記録")) + "。\n\n"
        checks = data.get("照合", [])
        if checks and all("API最終状態" in r for r in checks):
            text += G.table(["候補", "場", "研究/API実現円", "API買/売保有", "指紋", "一致"], [
                [r["手法"], r["場"], f"{number(r['研究側純損益円'])}/{number(r['API最終状態']['realized_pnl_yen'])}",
                 f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}", "一致" if r.get("数値本文SHA256一致") else "不一致/未確認", "一致" if r["一致"] else "不一致"] for r in checks])
    return text, paths


def diagnosis(study: Path, output: Path) -> str:
    """同じ原イベントの上位選別と実参加/利益回収を別に表示する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: str は小集計と診断への参照。未来ラベルで採用条件を作らない。
    """
    path = study / "対応診断.json"
    text = "## 上位選別・役割・参加と回収\n\nE1の純採用はE0の部分集合でも、保有/待機で実参加集合は単純な部分集合とは限らない。f/gの先着はそれぞれ新しい要求後の価格から測り、同episodeの二事例を独立した成功二票へ増幅しない。\n\n"
    if not path.exists():
        return text + "対応診断は未完・未保存。完成後に除外群・役割・参加・回収の保存値を反映する。\n\n"
    data = G.read_json(path)
    if data["結果SHA256"] != G.sha(study / "結果.json") or data["対応集合全件一致"] is not True:
        raise ValueError("対応診断の明示合否/結果SHA不一致")
    text += G.link(path, output) + "：全件一致・" + number(data["照合項目数"]) + "項目。価格だけの登録/価格event、数値準備、MACD勢い、E1上位選別、実運用の抑止を分ける。\n\n"
    text += "### 同じ役割の原イベントで上位選別を比べる\n\n除外群の逆行先着は避けた失敗、順行先着は逃した成功の事後分類。元E0と同じイベント/時点からの診断で、除外の因果効果や将来の再現性を証明しない。\n"
    rows = []
    for row in data["役割別選別"]:
        if row["期間"] not in PERIODS[:2]:
            continue
        raw, e0, e1, removed = (row[k] for k in ("全価格発動", "E0価格と勢い", "E1上位通過", "上位で除外したE0"))
        rows.append([PERIOD_NAMES[row["期間"]], row["系統"], raw["候補数"], f"{raw['対象外時間数']}/{raw['対象外遅延数']}",
                     row["M時間通過"]["候補数"], f"{e0['順行先着']}/{e0['約定候補数']}・{G.pct(e0['確認率'])}",
                     f"{e1['順行先着']}/{e1['約定候補数']}・{G.pct(e1['確認率'])}", removed["候補数"],
                     removed["順行先着"], removed["逆行先着"], f"{removed['期限未達']}/{removed['観測不足']}/{removed['未約定']}"])
    text += G.table(["期間", "系統", "原event", "時間/遅延対象外", "M時間", "E0順/仮約定・率", "E1順/仮約定・率", "上位除外", "逃した250", "避けた125", "期限/不足/未約定"], rows)
    role_index = {(r["期間"], r["系統"]): r for r in data["役割別選別"]}
    observations = []
    for period in PERIODS[:2]:
        current = role_index[period, "R内復帰"]
        left, right = current["E0価格と勢い"], current["E1上位通過"]
        observations.append(f"{PERIOD_NAMES[period]}の反転は{left['順行先着']}/{left['約定候補数']}（{G.pct(left['確認率'])}）→{right['順行先着']}/{right['約定候補数']}（{G.pct(right['確認率'])}）")
    text += "今回のE1では" + "、".join(observations) + "。ADXの非上昇は強さの変化で方向反転そのものではなく、この組み合わせで反転の確認率が改善したとは読めない。実方向Tによる順行選別も学習/選択の両期で一貫した改善を示していない。\n\n"
    text += "### 上位が許可した理由\n\n反転は実方向S2TかADX非上昇、順行は実方向S2T。下表は売買を合算した小集計で、売買別全文は診断正本に残す。ADX横ばいは低ADXや弱い相場と同義ではない。\n"
    grouped = {}
    for row in data["上位理由別"]:
        if row["期間"] not in PERIODS[:2]:
            continue
        key = row["期間"], row["系統"], row["上位理由"]
        counts = grouped.setdefault(key, Counter())
        for field in ("全価格発動", "E0採用", "E1採用"):
            for name in ("候補数", "約定候補数", "順行先着", "逆行先着"):
                counts[field + name] += row[field][name]
    text += G.table(["期間", "系統", "上位理由", "原event", "E0採用", "E1順/仮約定", "E1逆行125"], [
        [PERIOD_NAMES[p], family, reason, c["全価格発動候補数"], c["E0採用候補数"], f"{c['E1採用順行先着']}/{c['E1採用約定候補数']}", c["E1採用逆行先着"]]
        for (p, family, reason), c in grouped.items()])
    text += "### 旧23と登録母集団を同一視しない\n\n24は価格だけで登録し、Mと時間の扱いも変更した。旧方向/勢いの単点資格は旧23の実登録と異なる。下表の共通部分だけ固定出典を照合し、旧23との成績差を純上位選別と呼ばない。\n"
    text += G.table(["期間", "旧23登録", "新24登録", "共通", "旧のみ", "新のみ", "新登録の旧単点資格"], [
        [PERIOD_NAMES[r["期間"]], *[r[k] for k in ("旧23実登録数", "新24実登録数", "共通実登録数", "旧23のみ実登録数", "新24のみ実登録数", "新登録の旧方向勢い単点資格あり")]] for r in data["登録母集団と旧23"]])
    text += "### 役割ごとの実回収\n\n混合平均にはR/Tの構成比が入る。下表は実参加だけの役割別額で、純入口の125/250先着率とは分母が違う。仮250先着には実返済後の経路も含み、保有中250ptを得て失った件数ではない。\n"
    text += G.table(["候補", "期間", "役割", "実完結", "基準円", "追加5pt円", "追加5pt平均円", "対応仮250", "仮250だが純赤字", "仮250だがTP以外"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["役割"], r["実新規対応数"], number(r["基準純額円"]), number(r["追加5pt純額円"]),
         number(r["追加5pt純額円"] / r["実新規対応数"] if r["実新規対応数"] else None), r["対応先着250数"], r["先着250だが基準純赤字数"], r["先着250だが250利確以外数"]]
        for r in data["入口先着と利益回収"] if r["期間"] in PERIODS[:2]])
    text += "### 共通実新規の出口差と参加差\n\nE0→E1の基準純額差＝共通実新規の出口差＋E1のみ額−E0のみ額。全体額だけで追尾の改善と呼ばず、同じ新規の出口が一致することを確認する。\n"
    rows = []
    for row in data["運用対応"]:
        pair = row["運用比較"]
        participation = pair["右側のみ純額円"] - pair["左側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"], pair["共通実新規純額差円"] + participation, abs_tol=1e-8):
            raise ValueError("参加差と出口差の分解不一致")
        rows.append([PERIOD_NAMES[row["期間"]], f"{pair['共通実新規数']}/{pair['左側のみ実新規数']}/{pair['右側のみ実新規数']}",
                     number(pair["共通実新規純額差円"]), number(participation), number(pair["全運用純額差円"])])
    text += G.table(["期間", "共通/E0のみ/E1のみ実新規", "共通出口差円", "参加集合差円", "全純額差円"], rows)
    text += "### 同episodeの反転と順行・保有中の抑止\n\n二役割とも実参加した場合はR新規→R返済→T新規の順序と非重複を確認。反対役割eventの発生は自動ドテンや利益保護解除を意味しない。\n"
    text += G.table(["候補", "期間", "Rのみepisode", "Tのみepisode", "両役割episode", "両役割基準円"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["反転のみ実参加episode数"], r["順行のみ実参加episode数"], r["両役割実参加episode数"], number(r["両役割基準純額円"])]
        for r in data["同episode役割順序"] if r["期間"] in PERIODS[:2]])
    text += G.table(["候補", "期間", "役割", "入口の取扱件数", "実完結"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["役割"], G.describe(r["運用入口取扱"]), r["実完結数"]]
        for r in data["役割別運用抑止"] if r["期間"] in PERIODS[:2]])
    text += "### 追尾設定と実約定\n\n最低同値の設定は費用後黒字を保証しない。以下の同値未満/最終線不足は追尾起動後の取引に限る。最終線未満の実約定と手数料の差を入口先着から分ける。\n"
    text += G.table(["候補", "期間", "起動", "起動後純赤字", "同値未満約定", "最終線未満約定", "最終線から不足pt計"], [
        [r["候補ID"], PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["起動後同値未満約定数"],
         r["最終設定未満約定数"], number(r["最終設定からの不足pt計"])] for r in data["利益保護"] if r["期間"] in PERIODS[:2]])
    return text


def explanation() -> tuple[str, str, str, str]:
    """計画の共通準備・価格状態・執行・限界を表示文へまとめる。

    引数: なし。
    返り値: tuple[str,str,str,str] は四役割の説明。価格再生をしない。
    """
    structure = "## 準備と時間足の役割\n\n30分の高安を価格構造、3分MACDを実方向の勢い、15分ADX/DI/BB幅をE1の方向/強さ/値幅の選別へ使う。E0も価格構造とMACDを必須とする。数値が準備済みなだけ、ATRを出口に使うだけでは複数の入口手法に数えない。\n\n"
    structure += "M24は現在/前の同場隣接公開3分C/Hが有限、現在ATR14が正、当時公開15分現前ペアが準備済み、登録時に固定した30分窓が有効、現在確認遅延<=30。新規停止前・期限まで残60分以上の時間条件は別。下位BB/K/RSI/VWAP/量は準備gateへ加えない。登録後の最新30分窓の未準備は固定出典を取消さない。\n\n"
    structure += "30分は完全公開6本のR=max高値/L=min安値でR>L>0。突破bの前公開3分pまでに出典end<=p.endかつ公開(clock,line)<=p.keyで既知の窓を固定し、bと同時に知る足を先取りしない。同限月carry、完全幅NP/欠枠/尾部完全欠枠/限月変更で内部窓clear、末尾partialは含めない。3/15指標銀行と30窓は固定23を読取再用する。\n\n"
    structure += "15分S2はd!=0,a>0,(A>=25 OR Δw>0)ならd方向T、A<=20,a<=0,Δw<=0ならR、他WAIT。A=ADX/a=現前差/w=4母σ/SMA20/d=DI方向。DX−A=13aは同じ14平滑更新の関係で独立二票にしない。E0は上位ペアの準備のみを要求し、E1だけ以下の値による選別を行う。\n\n"
    logic = "## 価格状態と複合採用\n\nsは元突破方向、内復帰の実方向r=−s、H=MACD−Signal、δH=H現−H前。売りは全て符号反転した同条件。\n"
    logic += G.table(["段階", "買い突破s=+1の場合", "寿命/採用"], [
        ["価格登録b", "前C<=R+ε<C、ε=max(5,ceil(.25ATR_b/5)*5)", "時間可。S2/勢い不問・登録遅延>30可。この時点は注文なし"],
        ["内復帰f・反転r=−1", "最初のL<C<R", "b次1〜6。E0はM24/時間可・rδH>0。E1はさらに実方向S2TまたはΔADX<=0"],
        ["外回復g・順行s=+1", "最初のC>R", "f次1〜3。E0はM24/時間可・sδH>0。E1はさらに実方向S2T"],
    ])
    logic += "f/gはend>前段confirmかつ公開keystrict。同足二遷移なし、close-onlyなのでstart>confirmは課さずヒゲを判定に使わない。gはR+ε/f高安の再突破不要。買い起点はC=R待機・C<=L取消、売り起点はC=L待機・C>=R取消。元端/反対端の等号を区別する。\n\n"
    logic += "価格欠枠/非公開/番号飛越/不正・場/限月/期限→寿命超過→end/key時点対象外→反対端→当段階eventの順。第7/第4足は満了、時点対象外足は寿命のみ進み反対端も判定しない。上位/指標の不準備だけで価格監視は取消さない。最初のf/gはM/勢い/上位/時間/遅延/保有中の採否に関わらず消費し、後の足へ選び直さない。\n\n"
    logic += "global監視は一件、旧監視→新登録。遷移/消費/取消/満了同足の新登録禁止。used(side,境界)は登録で消費して当場一回、場替わりでreset。bは監視trace/context、f/gだけを原shadowへ保存し旧R1は混合しない。監視は建玉から独立で、自動ドテンは行わない。\n\n"
    logic += "原shadowの先着対象は時間可かつ確認遅延<=30。対象外は時間不可の理由を優先し、次に遅延超、ラベル『対象外』・通常9数値Noneで先着評価を呼ばない。未約定へ混ぜない。時間/遅延可でM/勢い/上位不可の原eventは事後先着診断に残すが、採用caseの分母に混ぜない。\n\n"
    protection = "## 利益保護・費用・場内完結\n\n固定21/23のnative通常出口なしX0を読取再用。hard125/TP250/期限と、返済BBOの正益5ptで必須追尾。D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor、最低新規同値・線を緩めない。反転はf、順行はgのATRをfillで固定し、bのATRを保護幅へ流用しない。返済待機中は更新停止、役割はfill固定。優先は期限/既存待機約定→hard125→TP250→追尾。\n\n"
    protection += "ラージBBOをmicro1枚代理、倍率10円/pt・呼値5pt・片道11円を仮定。要求+1価格時計秒以上の最初正常BBO、新規TTL30、買Ask/売Bid新規と返済側BBO。同原行は気配→確定足→signal。価格時計は実受信時計ではない。追加片道5/10ptは同じ完結往復から100/200円控除する費用感度で、参加経路の再生ではない。\n\n"
    protection += "デイは原範囲08:45〜15:40・新規停止15:25・強制15:35、ナイトは17:00〜05:55・停止05:40・強制05:50を維持し持ち越さない。同値設定と実約定同値・費用後黒字は別。正常板空白300秒超/EOF等の注意を含む全体確定額はnullのまま。\n\n"
    limits = "## 限界と次の問い\n\n突破の失敗に追随の手仕舞い、外回復に元方向の参加回復が重なるという心理は仮説で、注文動機・損切り集中・売り吸収を直接観測していない。CMEの支持抵抗、FidelityのMACD、StockChartsのADXは一般的説明の根拠であり、本試行の30分6本/0.25ATR/6・3寿命/70%や収益を実証していない。確認日2026-11-05、URLは計画と共通議論に残す。\n\n"
    limits += "全65場を既に使った追加開発。旧23との差には登録母集団/M/時計の変更も入るため、同一母集団で比較するE0/E1と分ける。役割内の確認率、実回収、構成比、参加差を別々に読む。多数指標の票数増加ではなく、価格構造・勢い・上位状態の役割を組み合わせた検証であり、指標単独の効果は未評価。量は診断のみ、下位BB/K/RSI/VWAPの発動や他尺度は未使用。\n\n"
    limits += "最大場内DDは期間累積DDではない。MFEは実保有中の事後峰で全額回収可能とはしない。仮125/250先着は実返済後も含み、反転失敗率の補数を次の順行/反転成功率へ変換しない。未来ラベルやMFEを当時の切替条件へ戻さず、条件変更は新試行へ分ける。今回の観測からADX非上昇だけを反転許可へ使う妥当性と、値幅/傾き/勢いの持続や急変を事前に区別する候補を考えるが、未検証の次候補を実績へ加えない。固定後の新しい未使用場を別に一回確認するまで将来の安定収益達成とはしない。\n\n"
    return structure, logic, protection, limits


def run(study: Path, output: Path) -> list[Path]:
    """完成通知後に正本から二文書を生成し出典SHAを記録する。

    引数: study/output (Path) は正式試行/文書先。
    返り値: list[Path] はREADME/設定と結果。価格・ラベル・損益を再生しない。
    """
    required = ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json", "入口品質.json")
    for name in required:
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
    if (catalog["version"], len(catalog["methods"]), len(catalog["scales"])) != (1, 51, 9):
        raise ValueError("版1の51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping_path = output / "README.md", output / "設定と結果.md"
    intro = "NK225の3分E0/E1＝二入口・共通A5/X0の二運用。固定30分高安の初終値内復帰で反転、初外回復で順行を判定する。両案とも価格構造＋MACDを必須とし、E1に15分ADX/DI/BB幅の上位選別を加えた。旧R1は混合せず、数量は診断のみ。全65場（学習40/条件選択24/既使用11/4デイ1）は全て既使用の追加開発。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2。** E1学習の基準観測額が黒字でも追加片道5pt後は赤字で、条件選択も赤字。上位選別を達成済みの切替条件とは判定しない。\n\n"
    conclusion += "E0学習は品質注意1場を含み、全体の確定対象額はnull。9/21ナイトの反転売り保有中に正常気配354秒空白を検知した。以下の同期間の純額・平均・参加差は観測値で、確定収益として扱わない。E1がこの事例を除いたことを一般的な品質検知能力とはしない。\n\n"
    structure, logic, protection, limits = explanation()
    summary = "# 試行00024：終値の内復帰と外回復による順行反転\n\n" + intro
    summary += " / ".join(G.link(study / name, readme) for name in ("計画.md", "条件.json", "固定.json", "結果.json")) + " / " + G.link(mapping_path, readme) + "\n\n"
    audit_text, audit_paths = audits(study, readme)
    summary += conclusion + structure + logic + protection + stages(study) + comparison(entries, values) + diagnosis(study, readme) + limits + audit_text
    # ----------------------------------------
    # 元の51手法・9尺度と未使用セルを保持し、閾値と複合二結果を同じ文書へ残す。
    common = settings(rules)
    method_ids, scale_ids = {r["id"] for r in catalog["methods"]}, {r["id"] for r in catalog["scales"]}
    if any(set(r["手法ID"]) - method_ids or set(r["尺度ID"]) - scale_ids for r in common):
        raise ValueError("設定が51×9へ対応しない")
    mapping = "# 試行00024：設定と結果\n\n" + intro + conclusion
    mapping += G.link(G.MASTER, mapping_path, "コピー元の汎用表") + " / " + G.link(readme, mapping_path) + " / " + G.link(study / "結果.json", mapping_path, "全二評価の正本") + "\n\n"
    mapping += "## 手法×時間スケール\n\n版1の51手法×9尺度。R01/R02は複合評価ID、S01〜S11は設定。各セルの使用/数値準備/診断を明細で区別し、指標単独の効果は未検証。30分6本は構造の計算期間、30分間引きは機会の間引き。RSI・下位BB/K・VWAPは今回の発動へ不使用。量は記録のみで選別効果未検証。\n\n"
    mapping += G.matrix(catalog, mapping_path, common)
    mapping += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [
        [r["設定ID"], "/".join(r["手法ID"]) + "・" + "/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapping += "## 全固定条件の要約\n" + G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapping += "## 全二運用の定義と合否\n" + G.table(["評価", "候補", "反転f", "順行g", "入口支持", "70目標", "費用資格"], [
        [r["評価ID"], r["候補ID"], "価格内復帰＋実方向δH>0" + ("＋実方向TまたはΔADX<=0" if r["入口"]["戦略"] == "E1" else ""),
         "価格外回復＋実方向δH>0" + ("＋実方向T" if r["入口"]["戦略"] == "E1" else ""),
         "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    mapping += comparison(entries, values) + structure + logic + protection + limits + audits(study, mapping_path)[0]
    # ----------------------------------------
    # 明細を複製せず、正本・Viewer・コード・共通知見と内容指紋へリンクする。
    files = ("入力台帳.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json",
             "局面品質.json", "30窓品質.json", "数量診断品質.json", "入力品質.json", "作業成果物.json")
    viewing = "## 閲覧と再現\n\n" + " / ".join(G.link(study / n, readme) for n in files if (study / n).exists()) + "\n\n"
    sources = [ROOT / "scripts/終値切替" / n for n in ("README.md", "指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py")
               if (ROOT / "scripts/終値切替" / n).exists()]
    docs = [ROOT / "docs/議論" / n for n in ("高位高安の再テスト待ちと入口価格を比較する.md", "終値内復帰と外回復を上位状態で選別する.md")
            if (ROOT / "docs/議論" / n).exists()]
    preparation = [ROOT / "work/終値切替/00024" / n for n in ("準備点検.json", "独立準備点検.json")
                   if (ROOT / "work/終値切替/00024" / n).exists()]
    viewing += "コード：" + " / ".join(G.link(p, readme) for p in sources) + "。背景：" + " / ".join(G.link(p, readme) for p in docs) + "。\n\n"
    viewing += "ラベル/損益なしの固定前準備：" + " / ".join(G.link(p, readme) for p in preparation) + "。主準備と独立準備の件数一致、人工経路の照合は収益標本数へ加算しない。\n\n"
    viewing += "Viewerは事前E0/E1のみ。原板や大量画像を複製せず、全監視/30窓/raw/context/局面/入口/運用/追尾はGit外workの9圧縮JSONLと展開内容SHAを参照する。\n\n"
    fence = chr(96) * 3
    viewing += "保存結果の再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/終値切替/レポート.py\n" + fence + "\n\n検証.pyは既存の結果.jsonの上書きを拒否する。数値再生はコードREADMEの別保存先の手順へ従う。--prepareはラベル/損益を計算しない準備点検で、正式損益の再生ではない。固定後の合成追加は別名へ分離し既存正本を上書きしない。\n\n"
    paths = [Path(__file__), DISPLAY, ROOT / "scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG, manifest_path,
             *[study / n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study / n).exists()],
             *audit_paths, *sources, *docs, *preparation]
    for path, text in ((readme, summary + viewing), (mapping_path, mapping)):
        path.write_text(text + G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping_path]


def main() -> None:
    """保存帳票の表示先を指定し、二文書を生成する。

    引数: なし。--study/--outputは任意の正式試行/表示先。
    返り値: None。主再生・先着・新規選別は実行しない。
    """
    parser = argparse.ArgumentParser(description="終値内復帰と外回復の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(path) for path in run(args.study, args.output or args.study)))


if __name__ == "__main__":
    main()

