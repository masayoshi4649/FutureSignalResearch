"""29の保存結果を、共通数量準備とOBV値追加を分けて二文書へ表示する。"""

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
STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
WORK = ROOT / "work/OBV反転/00029"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("R0", "R1")


def helper() -> Any:
    """前試行のMarkdown表示と保存分母検算だけを読み込む。

    引数: なし。
    返り値: Anyは表示補助。入口/先着/運用を再生しない。
    """
    spec = importlib.util.spec_from_file_location("OBV帳票の保存表示", ROOT / "scripts/一目基準線/レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


F = helper()
G, P, number = F.G, F.P, F.number


def definitions(config: dict) -> list[dict]:
    """事前固定した全反転二案を表示評価へ対応させる。

    引数: config(dict)は条件正本。
    返り値: list[dict]は二入口/二運用の定義。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分R0/R1・固定X0の二案と異なる")
    return [{"評価ID": f"R{i:02d}", "候補ID": f"3分_{p}_X0", "入口": {"入口ID": "3分_" + p,
             "戦略": p, "時間足分": 3, "名称": p, "役割": "反転", "複合本命": True}, "出口": {"出口ID": "X0"}}
            for i, p in enumerate(POLICIES, 1)]


def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict, Path]:
    """固定版/全二集合/40・24・2分母と費用/支持を保存値から検算する。

    引数: study(Path)は正式試行。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/定義/入口/運用/解決台帳。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "入口品質.json", "指標品質.json", "数量品質.json"):
        if not (study / name).is_file():
            raise ValueError(name + "未保存。正式完了前に実測帳票を生成しない")
    config, report = G.read_json(study / "条件.json"), G.read_json(study / "結果.json")
    if report["全66場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性/先着幅が不一致")
    rules = definitions(config)
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 2 or len(values) != 2 or len(report["入口評価"]) != 2 or len(report["結果"]) != 2:
        raise ValueError("全二案の分母が不一致")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules} or report["表示固定ID"] != [r["候補ID"] for r in rules]:
        raise ValueError("事前二案の集合が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("二案の役割/定義が不一致")
        for period, count in zip(PERIODS, (40, 24, 2)):
            P.validate_entry(entry[period])
            op = row[period]["運用"]
            n = op["完結取引数"]
            if row[period]["入口"] != entry[period] or op["入力場数"] != count or op["活動場数"] + op["無取引場数"] != count:
                raise ValueError("入口/活動/入力の期間分母が不一致")
            if op["買い取引数"] + op["売り取引数"] != n or op["役割別完結数"].get("反転", 0) != n:
                raise ValueError("方向/反転役割の会計が不一致")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾の起動分母が不一致")
            for slip in (0, 5, 10):
                net, average = op[f"追加{slip}pt純損益円"], op[f"追加{slip}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("費用感度の保存値が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額の分母が不一致")
                if op["品質注意場数"] and op[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意込み観測額を確定対象へ変換しない")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], row["入口支持"], entry["70目標"], row["70目標"], row["費用資格"]) != (support, support, bool(goal), bool(goal), qualified):
            raise ValueError("支持/70/費用資格が不一致")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in values.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("目標件数が不一致")
    pins = G.read_json(study / "固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT / name) != digest for name, digest in pins.items()):
        raise ValueError("固定版が変更")
    pointer = G.read_json(study / "入力台帳.json")
    manifest_path = (study / pointer["参照"]).resolve()
    if manifest_path != ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json" or G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("固定28の入力台帳参照が不一致")
    manifest = G.read_json(manifest_path)
    if len(manifest["entries"]) != 66 or len({r["session"] for r in manifest["entries"]}) != 66:
        raise ValueError("既使用66場の分母が不一致")
    return config, report, rules, entries, values, manifest_path


def settings(rules: list[dict]) -> list[dict]:
    """BB価格発動/MACD/共通量準備/OBV値/保護を51×9へ分ける。

    引数: rules(list[dict])は二複合評価。
    返り値: list[dict]は採用/準備等10設定と診断専用1設定。RVOL/一目を使用扱いに残さない。
    """
    groups = [
        (["I05", "P01", "P02"], ["m03"], rules, "原P：新20極値strict＋旧BB20±2σ内の終値", "同場連続公開有効20本の母標準偏差、現在足除外。買currentL<旧最安/売currentH>旧最高、旧下<C<旧上。ヒゲBB外/前C帯外は要求せず、M/値/時間/保有と別にraw保存"),
        (["I03"], ["m03"], rules, "中心化MACD12/26/9の現前H差×side>0", "reset初有効Cを原点o、C−oの算術seed EMA。原点/出典を保存し同限月carry、任意εなし。現前H有限が共通準備、差0/逆向きは両案不採用"),
        (["V02"], ["m03"], rules, "共通M：完全非負量＋t/k同一有効OBV区間", "R0も同じ量準備。固定14Qの数量基準完全＋有限q>=0、完全0有効。kより前の全20量完全やRVOL準備/正平均を要求しない"),
        (["V02"], ["m03"], rules[1:], "R1：実side*(OBV_t−OBV_k)>0", "R0への値追加。価格の新安値買い/新高値売りに対する観測OBV非追随、差等号は不採用。OBVは初足0種、次足sign終値差×当足q、終値同値増分0"),
        (["P02", "V02"], ["m03"], rules, "k：前20最安L/最高Hの最新同値足", "買/売別にkを当時窓から固定、未来山谷確認なし。共通Mを実side別に作る。反対側kの欠測を実sideへ混ぜない"),
        (["I09"], ["m03"], rules, "共通M：現ATR14有限正", "固定26Wilderの絶対価格更新を維持。ATRだけを複数入口分析として数えず、中心化MACDと数量区間の準備を別にする"),
        (["I03", "V02"], ["m03"], rules, "価格銀行carryと場内OBV/公開20窓を分離", "量不完全だけでMACD/ATR/価格20窓を切らない。OBV毎場/NP/欠量でclear。missing当足は価格窓/OBV不投入、数値だけ有効当足更新。missing0番号飛越後は新窓/新種可"),
        (["B01"], ["tick"], rules, "一建玉・新規/返済1秒・新規TTL30", "ラージBBOをmicro1枚代理、買Ask/売Bid新規・返済側BBO。同原行は気配→確定足→signal。全role反転、固定役割、自動ドテンなし"),
        (["I09", "C06", "E02"], ["tick"], rules, "固定A5：有利5pt起動・最低新規同値", "hard125/TP250/期限、D=max5,ceil(入口ATR/5)*5。保護利益max(0,MFE−D)、買ceil/売floor、非緩和。返済pending中追尾停止、BB/MACD/OBVを通常出口にしない"),
        (["E01"], ["tick"], rules, "仮新規125逆行前250順行・実参加と別評価", "原P先着対象は時間AND遅延のみ。対象外は通常9数値Noneで未約定と別。仮先着/支持/30分間引きと一建玉の実回収/費用を分離する"),
        (["P05", "P06", "V02"], ["m03"], rules, "診断のみ：k終値差/単位量回数・反発距離/旧BB余地", "量対単位量回数/終値差は事前診断予定。回数はk+1..t可変長で標準PSY不使用。現足端距離<=125/旧BB反対端余地>=250は結果後追加の当時C記述で、未来仮約定価格/gateに使わない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def comparison(entries: dict, values: dict) -> str:
    """共通保存形式の二案・三期間を既存の表示だけで整形する。

    引数: entries/values(dict)は入口/運用正本。
    返り値: strは仮先着/実参加/費用/支持の小表。
    """
    return F.comparison(entries, values).replace("三運用", "二運用")


def stages(study: Path) -> str:
    """全足/価格20窓/原P/採用と数量銀行の保存数を分ける。

    引数: study(Path)は正式試行。
    返り値: strは段階・量準備と除外理由。足とイベントを直列減算しない。
    """
    quality, numeric = G.read_json(study / "入口品質.json"), G.read_json(study / "指標品質.json")
    rows, reasons = [], {p: {r: Counter() for r in POLICIES} for p in PERIODS}
    for period in PERIODS:
        local = [r for r in quality if r["期間"] == period]
        rows.append([PERIOD_NAMES[period], len(local), sum(r["足数"] for r in local), sum(r["価格20窓準備足数"] for r in local), sum(r["原価格発動数"] for r in local), sum(r["先着評価対象外数"] for r in local), *[sum(r["戦略別発動数"]["3分_" + p] for r in local) for p in POLICIES]])
        for row in local:
            for policy in POLICIES:
                reasons[period][policy].update(row["戦略採否理由別"][policy])
    text = "## 価格発動と数量準備の段階\n\n価格20窓準備は足数、原Pと純採用はイベント数で分母が異なる。価格rawは量/MACD/OBV/時間の不成立でも保存。量準備を両案へ共通に課し、その除外をR1のOBV値追加の効果へ数えない。\n"
    text += G.table(["期間", "入力場", "3分足", "価格20窓準備足", "原P", "先着対象外P", "R0", "R1"], rows)
    fields = ("入力足数", "MACD準備足数", "数量入力可足数", "完全0量足数", "OBV公開足数", "OBV区間数", "数値clear数", "OBVclear数", "非公開価格数値更新数")
    text += G.table(["期間", "数値全足", "MACD H準備", "完全非負量", "完全0量", "OBV公開", "量区間", "数値clear", "OBVclear", "NP数値更新"], [[PERIOD_NAMES[p], *[sum(r[k] for r in numeric if r["期間"] == p) for k in fields]] for p in PERIODS])
    all_reasons = sorted({key for per in reasons.values() for counter in per.values() for key in counter})
    text += "採否理由は同じ原Pに複数付く重複計数で、合計を除外総数としない。\n"
    return text + G.table(["原Pの採否理由", *[PERIOD_NAMES[p] + "/" + policy for p in PERIODS for policy in POLICIES]], [[reason, *[reasons[p][policy][reason] for p in PERIODS for policy in POLICIES]] for reason in all_reasons])


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同値の正式コピー又は作業正本を選ぶ。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは正式優先。版差や未保存は例外。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """人工/主独立準備/正式六証明の明示合否と対象版を表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tuple[str,list[Path]]は検査表/出典。検算を収益標本へ加えない。
    """
    groups = [("合成検証.json", "人工価格/数量/原点/非PnL境界"), ("独立監査.json", "全先着/Decimal会計/正式資源"),
              ("状態独立確認.json", "原OHLC/数量/中心化MACD/OBV/全採否"), ("追尾独立確認.json", "全保有A5最初要求/気配"),
              ("対応診断.json", "共通準備/OBV追加/実参加/回収"), ("Viewer照合.json", "事前二運用の代表Viewer")]
    rows, paths = [], []
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致", data.get("対応集合全件一致")), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
            if any(G.sha(ROOT / k) != digest for k, digest in data["ファイルSHA256"].items()):
                raise ValueError("最終合成のpin差")
        elif name == "Viewer照合.json":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 2 and all(r.get("一致") is True for r in checks), len(checks)
        if verdict is not True:
            raise ValueError("明示監査未完:" + name)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study / "結果.json"):
            raise ValueError("証明の結果版差:" + name)
        if name == "対応診断.json" and data["ファイルSHA256"].get((study / "結果.json").relative_to(ROOT).as_posix()) != G.sha(study / "結果.json"):
            raise ValueError("対応診断の結果pin差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("状態/追尾が正式会計へ未接続")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    preparation = proof_path(study, work, "独立準備点検.json")
    independent = G.read_json(preparation)
    main = work / "準備点検.json"
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main):
        raise ValueError("主独立準備の対象版差")
    paths += [main, preparation]
    rows += [["固定前主準備・label/PnLなし", "66場・非損益", 66, G.link(main, output)], ["固定前独立数値/量/原P", "一致/合格", number(independent["照合項目数"]), G.link(preparation, output)]]
    ref = G.read_json(study / "準備参照.json")
    resolved = (study / G.read_json(study / "入力台帳.json")["参照"]).resolve()
    if G.sha(main) != G.read_json(study / "固定.json")["主準備SHA256"] or G.sha(main) != ref["主準備SHA256"] or G.sha(preparation) != ref["独立準備SHA256"]:
        raise ValueError("準備参照/実行前固定と準備SHAの版差")
    if independent["条件SHA256"] != G.sha(study / "条件.json") or independent["入力台帳SHA256"] != G.sha(study / "入力台帳.json") or independent["解決入力台帳SHA256"] != G.sha(resolved):
        raise ValueError("独立準備の条件/pointer/台帳bind差")
    if ref["ラベル計算"] is not False or ref["損益計算"] is not False or independent["ラベル計算"] is not False or independent["損益計算"] is not False:
        raise ValueError("準備の非label/PnL証拠が不一致")
    supplement_path = work / "保存物読取補足.json"
    supplement = G.read_json(supplement_path)
    if supplement["全件一致"] is not True or supplement["不一致"] or supplement["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
        raise ValueError("保存物読取補足の合否/対象診断版差")
    paths.append(supplement_path)
    rows.append(["保存物の独立読取/全費用分解", "一致/合格", number(supplement["照合項目数"]), G.link(supplement_path, output)])
    text = "## 検査の状態\n\n固定前人工/主独立準備と、正式固定後の状態/先着/会計/全保有追尾/代表Viewerを分ける。ATRと中心化MACD/Signal/H/現前差のみabs1e−10・rel0、差符号/全採否/量/OBV/BB/価格/時点/追尾D整数は厳密。ゲートへεを足さず、検算件数を独立収益標本へ合算しない。\n"
    return text + G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """正式対応の保存先を参照し、準備/値追加/参加の比較を区別する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: strは共通量準備/保持除外/単位量比較/実参加/回収の小表。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    result_key = (study / "結果.json").relative_to(ROOT).as_posix()
    if data["全件一致"] is not True or data["ファイルSHA256"].get(result_key) != G.sha(study / "結果.json"):
        raise ValueError("対応診断の合否/結果版差")
    text = "## OBV値追加と実参加の対応\n\n" + G.link(path, output) + "が正本。同じ量準備を持つR0の保持/除外、共通実新規の出口差と片側だけの実参加、仮250と実回収を別に評価する。量の重みと単位数量による終値方向回数の重複も診断し、記述比較を見て採否を変更しない。\n"
    text += G.table(["期間", "原P", "Pの共通M", "time/delay先着可", "R0", "R1"], [[PERIOD_NAMES[r["期間"]], r["原価格発動数"], r["共通M準備数"], r["先着評価対象数"], r["全案採用数"]["R0"], r["全案採用数"]["R1"]] for r in data["期間別原発動"]])
    rows = []
    for r in data["入口追加比較"]:
        for name in ("保持入口", "除外入口"):
            e = r[name]
            rows.append([PERIOD_NAMES[r["期間"]], name, e["候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", e["逆行先着"], f"{e['期限未達']}/{e['観測不足']}/{e['未約定']}"])
    text += "### 同じ量準備で保持/除外した純入口\n\nR0純入口を保持群/除外群に分けた表で、全原Pの分割ではない。除外の250は取り逃した仮機会、125は避けた仮逆行で、実現円へ直接変換しない。\n"
    text += G.table(["期間", "群", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定"], rows)
    text += "OBV追加の保持率は学習15/75＝20.00%に対し除外22/66＝33.33%、選択11/63＝17.46%に対し除外17/63＝26.98%。追加条件が低品質群を安定的に除いた結果ではない。逆側の成績も同じ新規方向の仮先着で、不採用を逆売買へ切り替えた収益とはしない。\n\n"
    text += "### 数量の重みと終値方向の重複\n\n以下は共通M/時間/MACD差を通過したR0純入口が分母で、全原Pや一建玉の実参加ではない。k+1からtまで各量を1へ置換した終値方向回数と、観測量の符号付き累積を比較する。回数は可変長で、標準期間のサイコロジカルラインを使った条件ではない。価格終値差の区分も当時値で記述する。事前診断予定に沿った比較で採否の変更や単位量戦略の運用再生はしない。\n"
    text += G.table(["期間", "区分軸", "当時区分", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定"], [[PERIOD_NAMES[r["期間"]], r["区分軸"], r["当時区分"], r["候補数"], f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", r["逆行先着"], f"{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in data["R0の量と価格方向区分"]])
    text += "量だけ実方向の学習2/7・選択2/5、回数だけ実方向の学習1/1・選択0/1は少数。観測量を重み付けしたことの独立した予測効果や、100%の小群の将来率を実証したとはしない。\n\n"
    supplement = G.read_json(work / "保存物読取補足.json")
    text += G.table(["期間", "R0純入口", "R1量方向可", "単位量回数可", "量と回数の共通", "終値差方向可", "量と終値差の共通"], [[PERIOD_NAMES[r["期間"]], r["R0候補数"], r["R1量方向可数"], r["単位量回数方向可数"], r["量と回数共通数"], r["終値差方向可数"], r["量と終値共通数"]] for r in supplement["単位量と終値の重複"]])
    text += "学習では量方向可と終値差方向可がともに83件でも、共通は79件。件数が等しいことを同一集合とはしない。量と回数の共通76/83・62/67という重複も、別系統の独立した裏付けとして二重計上しない。\n\n"
    text += "### 結果開示後に追加した価格位置の記述\n\nこの節は先着/損益の開示後に追加した探索的診断で、当試行の入口条件ではない。原発動時のcloseと現足high/low・旧BBだけを使い、未来の仮約定価格を選別へ使っていない。買いはC−現L/旧BB上−C、売りは現H−C/C−旧BB下を計算する。BBの端は将来到達や支持抵抗を保証しない。\n"
    text += G.table(["案", "期間", "純要求", "現足端からの反発距離中央値pt", "旧BB反対端までの余地中央値pt"], [[r["戦略"], PERIOD_NAMES[r["期間"]], r["候補数"], number(r["現足端からの距離中央値pt"]), number(r["旧BB反対端までの余地中央値pt"])] for r in data["結果後の位置中央値"]])
    text += "学習/選択のR1はR0より既に反発した距離が大きく、旧帯内の反対端までの余地が小さい面を観測した。両案は同じ原Pの同じ要求時計で判定し、この距離差は選んだイベント構成の差で、追加の待機時間を設定していない。成績悪化の原因や次の有効な閾値が確定したとはしない。\n"
    text += G.table(["案", "期間", "現足端距離<=125", "旧BB余地>=250", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定"], [[r["戦略"], PERIOD_NAMES[r["期間"]], "該当" if r["現足端距離125以下"] else "非該当", "該当" if r["旧BB反対端余地250以上"] else "非該当", r["候補数"], f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", r["逆行先着"], f"{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in data["結果後の位置区分"] if r["期間"] in PERIODS[:2]])
    text += "区分別成績は同じ既使用資料を結果後に分けた値で、新しい切替/入口の未見性能ではない。この診断で現在の採否・返済・支持判定を変更していない。\n\n"
    text += "### 純集合と実参加の差\n\nR1純採用はR0の部分集合だが、一建玉では前の保有が減り、R0が保有中に抑止した後続へ参加できる。新規の役割/方向/価格/時刻/原行で対応させ、共通出口差と片側参加を分ける。\n"
    text += G.table(["期間", "共通実新規", "共通出口差円", "R0のみ完結・基準/追加5円", "R1のみ完結・基準/追加5円", "全基準差円"], [[PERIOD_NAMES[r["期間"]], r["共通実新規数"], number(r["共通出口差円"]), f"{r['左のみ']['完結取引数']}・{number(r['左のみ']['追加0pt純損益円'])}/{number(r['左のみ']['追加5pt純損益円'])}", f"{r['右のみ']['完結取引数']}・{number(r['右のみ']['追加0pt純損益円'])}/{number(r['右のみ']['追加5pt純損益円'])}", number(r["総基準損益差円"])] for r in data["実参加比較"]])
    text += "学習/選択は共通71/57件で出口差0円。R0のみ60/58件を減らす一方、R1のみ3/6件の基準純額は−2,566/−932円。総赤字の減少を共通出口改善や安定黒字としない。追加5pt平均はR0−206.73/−254.17円→R1−257.14/−342.63円へ悪化した。\n\n"
    text += "### 先着と実利益回収\n\n仮250先着は実返済後も含む。実保有250到達は事後MFEで任意の時点に全額回収できたという意味ではない。最低同値床からの不足は新規価格基準で、最終追尾線不足は後の別表で分ける。\n"
    text += G.table(["候補", "期間", "実完結", "対応仮250", "判定前に返済", "実保有MFE250", "追尾起動", "起動後基準赤字", "起動後最大同値床不足pt"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], r["仮250先着取引数"], r["仮250判定前返済数"], r["実保有250到達取引数"], r["追尾起動数"], r["起動後純赤字数"], number(r["起動後最大返済不足pt"])] for r in data["候補別回収"]])
    text += "R0の学習/選択の仮250対応33/24件中、判定前に返済したのは31/21件。先着目標と保有中の回収を別に扱い、仮250を得てから赤字へ転落した件数として数えない。\n\n"
    text += "補足読取で同値返済の往復22円手数料赤字と不利価格返済を区別した。同値保護は価格の下限設定で、費用を相殺する利益床ではない。\n"
    text += G.table(["候補", "期間", "追尾起動", "起動後基準赤字", "うち同値手数料赤字", "うち不利価格返済"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["同値返済手数料赤字数"], r["不利価格返済数"]] for r in supplement["回収内訳"]])
    trades = G.read_csv(study / "固定候補_取引.csv")
    rows = []
    for period in PERIODS:
        for policy in POLICIES:
            cid = "3分_" + policy + "_X0"
            armed = [r for r in trades if r["期間"] == period and r["手法"] == cid and r["追尾起動"] == "True"]
            below = sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in armed)
            line = sum(float(r["最終追尾から実返済方向差pt"]) < 0 for r in armed)
            rows.append([cid, PERIOD_NAMES[period], len(armed), below, line, number(sum(max(0., -float(r["最終追尾から実返済方向差pt"])) for r in armed))])
    text += "### 追尾設定と実約定\n\n以下の同値未満/最終線不足は追尾起動後の取引に限る。同値設定・実同値返済・費用後非赤字を区別し、価格時計の待機を実通信遅延と呼ばない。\n"
    return text + G.table(["候補", "期間", "追尾起動", "同値未満約定", "最終線未満約定", "線不足pt計"], rows)


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式結果と全証明を保存値だけで二Markdownへ表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。原板/cache/先着/PnL再生なし。
    """
    config, report, rules, entries, values, manifest_path = validate(study)
    catalog = G.read_json(G.CATALOG)
    if (catalog["version"], len(catalog["methods"]), len(catalog["scales"])) != (1, 51, 9):
        raise ValueError("版1の51×9表を維持する")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output / "README.md", output / "設定と結果.md"
    common = settings(rules)
    intro = "NK225の3分反転二案。直前20価格極値更新＋旧BB内終値と中心化MACD一足差をR0、同じ量準備のもとOBV非追随をR1へ追加する。全66場（40/24/既使用11月4日Day・Night2）は既使用の追加開発で、未使用確認ではない。固定28から125/250・支持/費用・X0/A5を継承し、新出口や上位一目/ADX等を足していない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2。** 数量準備とOBV値追加、純採用と実参加、先着と利益回収を分けて判定する。\n\n"
    logic = "## 複数手法の役割と同時点の判断\n\n価格rawPは同場の連続公開有効20本の高安/終値を固定し、買currentL<旧最安L・売currentH>旧最高H、かつ旧BB下<C<旧BB上。BBは前20終値の平均±2母標準偏差で現在足除外。ヒゲBB外/前C帯外を追加しない。kは買最安L/売最高Hの最新同値足で、未来山谷確認はしない。価格rawをM/値/時間/保有の不成立で消さず、後続確認で時計を取り直さない。\n\n"
    logic += "MACDはreset最初の有効Cを原点oとしてC−oへ12/26/9の算術seed EMAを適用し、原点/出典を保存。同限月carry、量不完全だけではresetしない。価格欠枠/不正/尾部/限月で解除、全幅NPは価格数値のみ更新。原点を未来から選ばず任意εを加えない。現前H差×実side>0が両案の値条件で、MACD水準だけの反転判断にしない。\n\n"
    logic += "観測OBVは同場の連続完全公開数量区間の初足0種、次足からsign(C−前C)×当足qを加算。終値同値/完全0量は増分0で有効。共通Mは価格20窓・現前H有限・現ATR正・当足完全非負量・t/k同一OBV有効区間を実方向ごとに作りR0にも課す。R1だけside*(OBV_t−OBV_k)>0を追加し、等号は不採用。k以前の全20数量完全、RVOL準備/正平均は要求しない。\n\n"
    logic += "量不完全で価格20窓/MACD/ATRを切らず、OBVを切る。missing>0足は数値clear後有効OHLCを更新する一方、価格20窓/OBV種へ不投入、次missing0公開足から再開。missing0番号飛越後の当足は新窓/新種可。NP/量不完全/不正/毎場でもOBV切断。時間/遅延は準備と別、raw先着対象は時間AND遅延だけ。二案全採否/同時競合確定後にcaseを深複写し、未来labelを運用signalへ混ぜない。\n\n"
    protection = "## 利益保護・執行・費用\n\n固定26の一建玉X0/A5を固定28経由で読取再用。hard125/TP250/期限、正常返済BBOで有利5ptなら必須追尾。D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低新規同値。返済pending中追尾停止、全role反転でfill固定、自動ドテンなし。BB/MACD/OBVを通常出口にしない。\n\n"
    protection += "micro1枚代理・10円/pt・呼値5pt・片道11円、ラージBBOで新規/返済は要求+1価格秒以上の最初正常BBO、新規TTL30。買Ask/売Bid新規・返済側BBO、同原行は気配→確定足→signal。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、別参加経路の再生ではない。同値設定は実同値約定/費用後非赤字を保証しない。\n\n"
    protection += "デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板空白300秒超/EOF/未解消の品質と確定不能を別に残し持ち越さない。価格時計は実受信時計ではなく、実micro板/実約定を証明しない。\n\n"
    limits = "## 限界と知見の扱い\n\n新安値/新高値と旧帯内終値を一時的な極値更新の失敗、MACD差を価格方向変化、OBV非追随を観測量で支持されない極値と読むのは心理仮説。OBVは終値方向で量を符号化した加工値で、攻撃側売買量/吸収/投資家心理を直接観測していない。BBを将来95%の確率範囲とせず、全指標は価格/数量由来で独立成功票ではない。\n\n"
    limits += "原量はラージの観測累積差分で全約定の完全性を証明しない。RVOL/一目/ADX/SAR/RSI等は本案未使用、各指標単独効果も未検証。ATR準備/保護だけを複数入口分析に数えない。R1の純集合包含と保有抑止後の実参加包含は別。未来先着/事後MFEを当時特徴へ戻さず、主要条件変更は新試行へ分ける。\n\n"
    audit_text, audit_paths = audits(study, work, readme)
    results = comparison(entries, values)
    summary = "# 試行00029：BB内復帰とOBV非追随\n\n" + intro + " / ".join(G.link(study / n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json")) + " / " + G.link(mapping, readme) + "\n\n"
    summary += conclusion + results + stages(study) + diagnosis(study, work, readme) + logic + protection + limits + audit_text
    # ----------------------------------------
    # 使用セルを価格/勢い/量準備/量値/保護へ分け、前試行の一目/RVOLを残さない。
    mapped = "# 試行00029：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, mapping, "コピー元汎用表") + " / " + G.link(readme, mapping) + "\n\n"
    mapped += "## 手法×時間スケール\n\n版1の51×9。S01〜S10は採用/準備/保護・評価、S11は診断のみ、R01/R02は複合評価。共通量準備は両案、OBV値追加はR1のみ。RVOL/上位一目等を使用へ残さず、診断・未使用・単独未評価を区別する。\n\n" + G.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"]) + "・" + "/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n" + G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 二評価の定義と判定\n" + G.table(["評価", "候補", "同時点条件", "入口支持", "70目標", "費用資格"], [[r["評価ID"], r["候補ID"], config["OBV反転"][r["入口"]["戦略"]], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    mapped += results + logic + protection + limits + audits(study, work, mapping)[0]
    # ----------------------------------------
    # 六系列の全件転記を避け、小型pointer/全証明/版/Viewerへ参照する。
    files = ("入力台帳.json", "準備参照.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "指標品質.json", "数量品質.json", "入力品質.json", "作業成果物.json")
    sources = [HERE / n for n in ("README.md", "指標.py", "入口.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py") if (HERE / n).is_file()]
    docs = [ROOT / n for n in ("docs/technical-analysis/指標/OBV.md", "docs/technical-analysis/指標/MACD.md", "docs/technical-analysis/指標/ボリンジャーバンド.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md", "docs/議論/極値更新とOBV非追随の反転を比較する.md") if (ROOT / n).is_file()]
    viewing = "## 閲覧と再表示\n\n" + " / ".join(G.link(study / n, readme) for n in files if (study / n).is_file()) + "\n\nコード：" + " / ".join(G.link(p, readme) for p in sources) + "。\n\n"
    viewing += "入力は固定28の66台帳へ小型pointerとSHAで参照し重複保存しない。六gzipはGit外work・展開内容SHAを作業成果物へ保持。Viewer一覧は事前R0/R1各66場、APIは各案代表2資源。market_pathはdata_root/pnl_pathはcatalog基準。--prepareは数値/量/原P/全採否だけでlabel/PnLなし。主再生は既存結果/正式中間物を拒否。固定を上書きせず、再生詳細はコードREADMEへ従う。\n\n"
    fence = chr(96)*3
    viewing += "保存値だけの再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/OBV反転/レポート.py\n" + fence + "\n\n"
    paths = [Path(__file__), ROOT / "scripts/一目基準線/レポート.py", ROOT / "scripts/反転確認時計/レポート.py", F.F.DISPLAY,
             ROOT / "scripts/SAR持続/レポート.py", ROOT / "scripts/終値切替/レポート.py", ROOT / "scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG, manifest_path,
             *[study / n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study / n).is_file()], *audit_paths, *sources, *docs]
    planned = work / "診断予定.json"
    if planned.is_file():
        paths.append(planned)
    for path, text in ((readme, summary + viewing), (mapping, mapped)):
        path.write_text(text + G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存帳票だけを指定先へ再表示する。

    引数: なし。--study/--work/--outputは正式/作業/表示先。
    返り値: None。市場の入口/先着/会計を再計算しない。
    """
    parser = argparse.ArgumentParser(description="BB内復帰とOBV非追随の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
