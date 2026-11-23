"""30の保存結果を、価格突破/幅拡大とPSY方向頻度に分けて表示する。"""

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
STUDY = ROOT / "study/00030_価格突破とBB幅と方向頻度"
WORK = ROOT / "work/PSY突破/00030"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("P0", "P1")


def helper() -> Any:
    """前試行のMarkdown表示と保存分母検算だけを読み込む。

    引数: なし。
    返り値: Anyは表示補助。入口/先着/運用を再生しない。
    """
    spec = importlib.util.spec_from_file_location("PSY帳票の保存表示", ROOT / "scripts/一目基準線/レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value

F = helper()
G, P, number = F.G, F.P, F.number


def definitions(config: dict) -> list[dict]:
    """事前固定した全順行二案を表示評価へ対応させる。

    引数: config(dict)は条件正本。
    返り値: list[dict]は二入口/二運用の定義。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分P0/P1・固定X0の二案と異なる")
    return [{"評価ID": f"R{i:02d}", "候補ID": f"3分_{p}_X0", "入口": {"入口ID": "3分_" + p,
             "戦略": p, "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True}, "出口": {"出口ID": "X0"}}
            for i, p in enumerate(POLICIES, 1)]


def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict, Path]:
    """固定版/全二集合/40・24・2分母と費用/支持を保存値から検算する。

    引数: study(Path)は正式試行。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/定義/入口/運用/解決台帳。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "入口品質.json", "指標品質.json"):
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
            if op["買い取引数"] + op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n:
                raise ValueError("方向/順行役割の会計が不一致")
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


def comparison(entries: dict, values: dict) -> str:
    """共通保存形式の二案・三期間を既存の表示だけで整形する。

    引数: entries/values(dict)は入口/運用正本。
    返り値: strは仮先着/実参加/費用/支持の小表。
    """
    return F.comparison(entries, values).replace("三運用", "二運用")


def settings(rules: list[dict]) -> list[dict]:
    """価格/幅/PSY準備と値追加/保護/診断を51×9へ分ける。

    引数: rules(list[dict])は二評価。
    返り値: list[dict]は採用等9設定と診断専用1設定。
    """
    groups = [
        (["P01", "P02", "P07"], ["m03"], rules, "原P：前20最高H/最安Lを現在Cでstrict突破", "同場連続公開有効20本を固定、現在足除外。買C>HH/売C<LL、等号/ヒゲだけ不可。rolling各突破足は別raw、M/幅/PSY/時間/保有と別保存"),
        (["I05"], ["m03"], rules, "P0：旧/現BB20絶対幅4σの厳密拡大", "旧20Cから最古1本を落とし現Cを入れた現20C、母σ・価格割りなし。Fraction原Cの母分散現前差>0で判定し、分散差の分子/分母を保存。幅差の分数でなく、等号0はM可/値不採用"),
        (["I06"], ["m03"], rules, "共通M：PSY現前12変化準備・最速14close", "現は末尾13close、前は1本前の13close。U/D/F整数で計12、表示上100U/12・下100D/12。同値F中立で100−upを売へ使わない。P0にも同じ準備"),
        (["I06"], ["m03"], rules[1:], "P1：現前(U−D)×sideが両方strict正", "U>DはU>6/上昇率50超/連勝ではなく、U1D0F11も正。strict20突破では現在close変化がside正なので、前正→現正は自動。前state頻度差と等価で独立二票/後続確認としない"),
        (["I09"], ["m03"], rules, "共通M：現在ATR14有限正", "固定26のWilder絶対価格更新を継承。ATRだけ同限月carry、欠枠/不正/尾部/限月でclear。ATR保護だけを複数入口分析と数えない"),
        (["I06", "P02"], ["m03"], rules, "価格20/PSY14は同場公開窓だけ", "missing>0/NP/不正はclear後当足不投入、番号飛越missing0当足は新窓可。ATRは有効missing当足/全幅NPも数値だけ更新。前場公開値を借りず、量/MACD等を準備へ足さない"),
        (["B01"], ["tick"], rules, "一建玉・新規/返済1秒・新規TTL30", "ラージBBOでmicro1枚代理、買Ask/売Bid新規・返済側BBO。同原行は気配→確定足→signal、全role順行・fill固定、自動ドテンなし"),
        (["I09", "C06", "E02"], ["tick"], rules, "固定A5：有利5pt起動・最低新規同値", "hard125/TP250/期限、D=max5,ceil(入口ATR/5)*5。保護利益max(0,MFE−D)、買ceil/売floor・非緩和。返済pending中追尾停止、PSY/BBを通常出口にしない"),
        (["E01"], ["tick"], rules, "125逆行前250順行・実参加/費用と別評価", "原P先着対象は時間AND遅延のみ、対象外は通常9数値None。主率/間引き/支持と一建玉回収を分離し、既使用後続2場を不足支持の代用にしない"),
        (["P05", "I06"], ["m03"], rules, "診断のみ：12変化の一足集中/PSY恒等関係", "事前診断予定の最大一足比率/現一足比率と前PSY全整数区分を記述。PSY頻度を値幅の分散/人数/連勝と同一視せず、比率や区分を現在のgateへ戻さない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
             "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
            for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def stages(study: Path) -> str:
    """価格20窓・共通準備・raw/採用とPSY局所銀行の件数を分ける。

    引数: study(Path)は正式先。
    返り値: strは足/原P/採用の段階と重複理由の表。
    """
    quality, numeric = G.read_json(study / "入口品質.json"), G.read_json(study / "指標品質.json")
    rows, reasons = [], {p: {policy: Counter() for policy in POLICIES} for p in PERIODS}
    for period in PERIODS:
        local = [r for r in quality if r["期間"] == period]
        rows.append([PERIOD_NAMES[period], len(local), sum(r["足数"] for r in local), sum(r["価格20窓準備足数"] for r in local), sum(r["共通M準備足数"] for r in local), sum(r["原価格発動数"] for r in local), sum(r["先着評価対象外数"] for r in local), *[sum(r["戦略別発動数"]["3分_"+p] for r in local) for p in POLICIES]])
        for r in local:
            for policy in POLICIES:
                reasons[period][policy].update(r["戦略採否理由別"][policy])
    text = "## 価格発動・共通準備・値追加の段階\n\n全3分足の価格/共通M準備と、原P/純採用の件数は分母が違う。P0にもPSY現前数値準備を課し、P1での方向値選別の効果へ準備差を混ぜない。幅/PSY/ATR/時間が不成立でも原Pを消さず、後足へ取り直さない。\n"
    text += G.table(["期間", "入力場", "3分足", "20価格準備足", "共通M足", "原P", "先着対象外P", "P0", "P1"], rows)
    fields = ("入力足数", "ATR正準備足数", "PSY現在準備足数", "PSY現前準備足数", "数値clear数", "PSYclear数", "非公開価格数値更新数", "尾部完全欠枠")
    text += G.table(["期間", "全足", "ATR正", "PSY現在", "PSY現前", "ATR数値clear", "局所PSYclear", "NP数値更新", "尾部欠枠"], [[PERIOD_NAMES[p], *[sum(r[k] for r in numeric if r["期間"] == p) for k in fields]] for p in PERIODS])
    all_reasons = sorted({key for per in reasons.values() for counts in per.values() for key in counts})
    text += "採否理由は全原Pに重複して付くため、合計を除外総数にしない。\n"
    return text + G.table(["原Pの採否理由", *[PERIOD_NAMES[p]+"/"+policy for p in PERIODS for policy in POLICIES]], [[reason, *[reasons[p][policy][reason] for p in PERIODS for policy in POLICIES]] for reason in all_reasons])


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
    groups = [("合成検証.json", "人工突破/精密幅/PSY/非PnL境界"), ("独立監査.json", "全先着/Decimal会計/正式資源"),
              ("状態独立確認.json", "原OHLC/ATR/BB/PSY/精密分散/全採否"), ("追尾独立確認.json", "全保有A5最初要求/気配"),
              ("対応診断.json", "共通準備/PSY追加/実参加/回収"), ("Viewer照合.json", "事前二運用の代表Viewer")]
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
    rows += [["固定前主準備・label/PnLなし", "66場・非損益", 66, G.link(main, output)], ["固定前独立数値/PSY/原P", "一致/合格", number(independent["照合項目数"]), G.link(preparation, output)]]
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
    text = "## 検査の状態\n\n固定前人工/主独立準備と、正式固定後の状態/先着/会計/全保有追尾/代表Viewerを分ける。ATRのみabs1e−10・rel0、PSY整数/率/BB表示/精密分散/全採否/価格/時点/追尾D整数は厳密。ゲートへεを足さず、検算件数を独立収益標本へ合算しない。\n"
    return text + G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """正式対応診断を指し、幅/前PSY/実参加と回収を分ける。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: strは幅/前PSY全整数/集中/実参加/回収/品質参考の小集計。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    result_key = (study / "結果.json").relative_to(ROOT).as_posix()
    if data["全件一致"] is not True or data["ファイルSHA256"].get(result_key) != G.sha(study / "結果.json"):
        raise ValueError("対応診断の合否/結果pin差")
    text = "## PSY追加と実参加の対応\n\n" + G.link(path, output) + "を正本とする。P0保持/除外と前PSYの全整数区分、値幅集中、同一実新規の出口差と片側参加、仮250と実回収を分ける。PSY現前の代数関係を独立二票へ増幅せず、診断値を現在のgateへ戻さない。\n"
    text += G.table(["期間", "原P", "原Pの共通M", "time/delay先着可", "P0", "P1"], [[PERIOD_NAMES[r["期間"]], r["原価格発動数"], r["共通M準備数"], r["先着評価対象数"], r["全案採用数"]["P0"], r["全案採用数"]["P1"]] for r in data["期間別原発動"]])
    text += "### 幅拡大が選んだ原価格発動\n\nこの表は共通Mと先着time/delayを満たす原Pの幅区分で、全rawやP0純入口の分割と混ぜない。数学等幅/縮小を非拡大へまとめ、精密符号で分類する。\n"
    text += G.table(["期間", "幅拡大", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定"], [[PERIOD_NAMES[r["期間"]], "該当" if r["BB拡大"] else "非該当", r["候補数"], f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", r["逆行先着"], f"{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in data["幅拡大の価格原発動"]])
    text += "### P0純入口をPSY値で保持/除外した比較\n\n保持/除外の分母はP0純入口。共通準備除外や幅の効果をP1の効果へ足さない。除外の250は仮機会、125は仮逆行で、実現円へ直接変換しない。\n"
    rows = []
    for r in data["入口追加比較"]:
        for name in ("保持入口", "除外入口"):
            e = r[name]
            rows.append([PERIOD_NAMES[r["期間"]], name, e["候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", e["逆行先着"], f"{e['期限未達']}/{e['観測不足']}/{e['未約定']}"])
    text += G.table(["期間", "群", "要求", "250/仮約定・率", "125先着", "期限/不足/未約定"], rows)
    text += "学習の保持110/415＝26.51%は除外32/106＝30.19%より低く、選択の保持76/274＝27.74%は除外18/77＝23.38%より高い。両期で同じ改善は確認できず、固定70%へ届いていない。\n\n"
    text += "### 前PSYの実方向整数別\n\n共通M/時間/幅を通過したP0純入口を、突破前12変化の実方向*(U−D)で全整数へ分類した。これは事前の記述比較で、区分を見て閾値0を選び直していない。空群は当入力で未出現、率未算出である。\n"
    by_key = {(r["期間"], r["前PSY実方向差整数"]): r for r in data["P0の前PSY整数別"]}
    rows = []
    for level in range(-12, 13):
        cells = []
        for period in PERIODS:
            r = by_key.get((period, level))
            cells.append("未出現・率未算出" if r is None else f"{r['候補数']}件・{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}")
        rows.append([level, *cells])
    text += G.table(["前PSY実方向差整数", *[PERIOD_NAMES[p]+"：要求・250/仮約定・率" for p in PERIODS]], rows)
    text += "少数区分の高率を支持付き70%の達成例としない。strict突破では前整数>0なら現在>0が自動となり、P1は突破前の頻度優位による選別と等価。二状態の独立した確認を得た結果ではない。\n\n"
    supplement = G.read_json(work / "保存物読取補足.json")
    text += G.table(["期間", "全原P", "前整数が実方向正", "PSY恒等式の不一致"], [[PERIOD_NAMES[r["期間"]], r["原P数"], r["前整数実方向正数"], r["恒等式不一致"]] for r in supplement["PSY恒等"]])
    text += "### 頻度と値幅の集中\n\n分母はP0純入口の保持/除外群。現12変化のΣ|ΔC|を分母に最大一足/現在一足の比率を取り、群ごとの中央値を示す。中央値が小さいことは、全スパイクを排除した証拠や投資家人数の測定ではない。この比率は採用に使っていない。\n"
    text += G.table(["期間", "群", "要求", "250/仮約定・率", "最大一足比率の中央値", "現一足比率の中央値", "現一足変化pt中央値"], [[PERIOD_NAMES[r["期間"]], "保持" if r["P1保持"] else "除外", r["候補数"], f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", G.pct(r["最大一足比率中央値"]), G.pct(r["現一足比率中央値"]), number(r["現一足変化pt中央値"])] for r in data["保持除外の値幅集中"]])
    text += "学習/選択とも保持群の一足比率中央値は除外群より低いが、学習の先着率改善や両期黒字には結び付いていない。頻度の正と値幅の小ささを同義にせず、次の条件変更は別試行とする。\n\n"
    text += "### 共通出口と片側だけの実参加\n\nP1純入口はP0の部分集合でも、前の保有が減るとP0が抑止した後続へ参加できる。役割/方向/価格/新規時刻/原行で対応し、共通出口差と参加差を分離する。注意を含む学習の額は観測値である。\n"
    text += G.table(["期間", "共通実新規", "共通出口差円", "P0のみ完結・基準/追加5円", "P1のみ完結・基準/追加5円", "全基準差円"], [[PERIOD_NAMES[r["期間"]], r["共通実新規数"], number(r["共通出口差円"]), f"{r['左のみ']['完結取引数']}・{number(r['左のみ']['追加0pt純損益円'])}/{number(r['左のみ']['追加5pt純損益円'])}", f"{r['右のみ']['完結取引数']}・{number(r['右のみ']['追加0pt純損益円'])}/{number(r['右のみ']['追加5pt純損益円'])}", number(r["総基準損益差円"])] for r in data["実参加比較"]])
    text += "学習/選択の共通372/256件は出口差0円。左のみ104/74件に対し右のみ4/3件があり、総損失減少を同じ取引の出口改善としない。追加5pt平均は学習P0−273.68→P1−256.31円、選択−239.27→−237.44円で、どちらも赤字のまま。\n\n"
    text += "### 仮先着と実保有の回収\n\n仮250は実返済後まで観測する。実保有250到達も事後MFEであり、どの時点でも全額回収できたことを示さない。同値床の不足は新規価格基準で、最終追尾線不足は次の別表へ分ける。\n"
    text += G.table(["候補", "期間", "実完結", "対応仮250", "判定前に返済", "実保有MFE250", "追尾起動", "起動後基準赤字", "起動後最大同値床不足pt"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], r["仮250先着取引数"], r["仮250判定前返済数"], r["実保有250到達取引数"], r["追尾起動数"], r["起動後純赤字数"], number(r["起動後最大返済不足pt"])] for r in data["候補別回収"]])
    text += "P0学習の仮250対応134件は全てその判定前にA5返済し、観測された実保有MFE250到達は0件。保有中250ptを得てから失った件数として数えない。起動後赤字も同値返済の往復22円手数料と、不利価格の返済を分ける。\n"
    text += G.table(["候補", "期間", "追尾起動", "起動後基準赤字", "うち同値手数料赤字", "うち不利価格返済"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["同値返済手数料赤字数"], r["不利価格返済数"]] for r in supplement["回収内訳"]])
    trades = G.read_csv(study / "固定候補_取引.csv")
    rows = []
    for period in PERIODS:
        for policy in POLICIES:
            cid = "3分_"+policy+"_X0"
            armed = [r for r in trades if r["期間"] == period and r["手法"] == cid and r["追尾起動"] == "True"]
            below = sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in armed)
            line = sum(float(r["最終追尾から実返済方向差pt"]) < 0 for r in armed)
            rows.append([cid, PERIOD_NAMES[period], len(armed), below, line, number(sum(max(0.,-float(r["最終追尾から実返済方向差pt"])) for r in armed))])
    text += "以下の同値未満/最終線不足は追尾起動後の取引に限る。価格床・実約定・手数料後非赤字を区別する。\n"
    text += G.table(["候補", "期間", "追尾起動", "同値未満約定", "最終線未満約定", "線不足pt計"], rows)
    text += "### 品質注意と結果後の共通場参考\n\n次表の当場最大間隔は正常板の価格時計であり、通信遅延を直接測った値ではない。学習の正式全期間確定額は両案ともnullを維持し、注意が減ったことをPSYの一般的な品質検知効果としない。\n"
    text += G.table(["候補", "場", "観測場純額円", "完結", "注意取引", "注意取引観測円", "保有空白区間", "当場最長正常板間隔秒"], [[r["候補ID"], r["場"], number(r["観測現金増減円"]), r["完結取引数"], r["観測経路注意取引数"], number(r["経路注意取引純損益円"]), r["保有中空白区間数"], number(r["最長正常板間隔秒"])] for r in data["品質注意の実参加"]])
    text += "結果後に両案の注意場和集合（9/22Night・10/9Night）を同じく外した保存成績の参考集計を示す。場を事前に見送る規則でも、時系列を除いて指標を作り直した再生でもなく、正式学習結果/資格を置き換えない。\n"
    text += G.table(["候補", "参考期間", "共通場", "実完結", "基準観測円", "追加5pt観測円", "追加5pt平均円"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["共通場数"], r["完結取引数"], number(r["追加0pt純損益円"]), number(r["追加5pt純損益円"]), number(r["追加5pt平均円"])] for r in data["共通無注意場の結果後参考"] if r["期間"] == "学習"])
    return text + "共通38場の参考でも両案の追加5pt平均は赤字。品質注意だけが今回の未達の原因という結論にはせず、将来に実装できる選別と事後の参考分解を分ける。\n\n"


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式結果と証明が揃った後だけ二Markdownを保存値から作る。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。主再生/市場読取なし。
    """
    config, report, rules, entries, values, manifest = validate(study)
    catalog = G.read_json(G.CATALOG)
    if (catalog["version"], len(catalog["methods"]), len(catalog["scales"])) != (1, 51, 9):
        raise ValueError("版1の51×9表を維持する")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output / "README.md", output / "設定と結果.md"
    common = settings(rules)
    intro = "NK225・3分の前20高安への終値突破を原Pとし、BB絶対幅拡大のP0にPSY12整数方向のP1を追加した二つの順行運用。全案のPSY数値準備/ATR/執行/A5を共通にし、量/OBV/MACD/一目/ADX等を採否へ追加しない。全66場（40/24/既使用11月4日Day・Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2。** 幅拡大と頻度値追加、純入口と実参加、仮先着と利益回収を分けて判定する。\n\n"
    warnings = [r["候補ID"] + "の" + PERIOD_NAMES[p] + "・" + str(r[p]["運用"]["品質注意場数"]) + "場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意は" + "、".join(warnings) + "。該当期の全体確定額はnull、総額/平均/参加差は観測値として表示する。注意場数の減少を一般的な品質検知効果としない。\n\n"
    logic = "## 複数手法の役割と精密境界\n\n原Pは同場の連続公開有効3分20本を固定し、買C>前HH・売C<前LL。現在足を前窓へ混ぜず、等号やヒゲだけの突破は不可。rolling各突破足は別IDで保存し、最初の一件だけへ限定しない。M/幅/PSY/時間/保有不可でも価格発動を消さず、後の確認へ時計や価格を取り直さない。\n\n"
    logic += "旧BBは前20終値、現BBは最古1本を外し現Cを入れた20終値。母σの絶対幅4σで、価格で割った幅ではない。採否は元floatCをFractionへ正確に写した母分散の現前差>0で判定する。同じ20本では分散と幅の増加符号が一致し、数学等幅は厳密0で不採用。分子/分母は分散差で幅差ではなく、表示平均/σ/4σはfloatを維持。任意εは足さない。\n\n"
    logic += "PSY現は末尾13closeの12変化、前はその1本前13closeで最速14close。U/D/Fを整数で数え計12、同値F中立、上100U/12・下100D/12を別保存する。売りを100−upへ変換しない。共通Mは価格20窓・ATR正・PSY現前数値・現前幅有限と厳密比較準備を両案へ課す。P0は幅拡大、P1はさらに現前の実side*(U−D)>0で、0は不成立。\n\n"
    logic += "U>DはU>6/上昇率50%超/連勝/投資家多数と同義ではなく、U1D0F11でも正。S_t=U_t−D_t、sを実方向±1とする。strict20高安終値突破では現close変化が必ず実方向なので、sS_t=sS_(t−1)+1−s×旧変化の符号。実方向を掛けた現在差は前差以上となり、前正なら現正は自動である。二状態条件は予定どおり保つが、突破前の頻度優位と等価で、独立した二票や新しい後続の持続確認とは主張しない。\n\n"
    logic += "価格20/PSYの局所窓は同場公開だけ。missing>0/NP/不正はclear後当足不投入、番号飛越missing0有効当足は新窓可。ATRだけ同限月carryし、欠枠/不正/尾部/限月で解除、missing有効当足/全幅NPは数値だけ更新する。時間/遅延はMと別、原P先着対象は時間AND遅延のみ。全採否/同時競合後にcaseを深複写し、未来labelを運用signalへ混ぜない。\n\n"
    protection = "## 利益保護・執行・費用・場内完結\n\n固定26の一建玉X0/A5を継承し新出口を作らない。hard125/TP250/期限、正常返済BBOの有利5ptで必須追尾。D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低新規同値。返済pending中追尾停止、全role順行でfill固定、自動ドテンなし。PSY/BBを通常出口へ使わない。\n\n"
    protection += "ラージBBOによるmicro1枚代理、10円/pt・呼値5pt・片道11円。新規/返済は要求+1価格秒以上の最初正常BBO、新規TTL30。買Ask/売Bid新規・返済側BBO、同原行は気配→確定足→signal。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、別の参加経路を再生した値ではない。同値設定と実同値約定/費用後非赤字は別。\n\n"
    protection += "デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板空白300秒超/EOF/未解消の品質と確定不能を分け、持ち越さない。価格時計は実受信時計ではなく、実micro板/実約定の証明ではない。\n\n"
    limits = "## 限界と知見の扱い\n\n終値突破を方向、BB絶対幅増を値幅拡大、PSYを直前の上昇/下落回数の偏りと読むのは心理仮説。いずれも価格由来で独立した成功票ではない。頻度は変化幅の大小や順序を保存せず、一発スパイクの全除去も保証しない。最大一足/現在一足の集中は診断専用で、今回の採否を変更していない。\n\n"
    limits += "I06/I05/価格突破を組み合わせる比較で、PSY等の単独効果は未検証。量/OBV/MACD/一目/RSI/ADXと他尺度は本案未使用、ATR準備/保護だけを複数入口分析と数えない。純集合包含と実参加包含は別。事後MFEや未来先着を当時特徴へ戻さず、主要条件変更は別試行へ分ける。既使用後続2場や合算で不足支持を代用しない。\n\n"
    audit_text, audit_paths = audits(study, work, readme)
    results = comparison(entries, values)
    summary = "# 試行00030：価格突破とBB幅と方向頻度\n\n" + intro + " / ".join(G.link(study / n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json")) + " / " + G.link(mapping, readme) + "\n\n"
    summary += conclusion + results + stages(study) + diagnosis(study, work, readme) + logic + protection + limits + audit_text
    # ----------------------------------------
    # 全51×9を保持し、共通準備/値追加/保護/診断と未使用を分ける。
    mapped = "# 試行00030：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, mapping, "コピー元汎用表") + " / " + G.link(readme, mapping) + "\n\n"
    mapped += "## 手法×時間スケール\n\n版1の51×9。S01〜S09は採用/準備/保護・評価、S10は診断のみ、R01/R02は複合評価。PSY準備はP0/P1共通、方向値はP1追加。PSY現前二状態を独立二票にしない。量/OBV/MACD等を使用扱いに残さず、未使用・診断・単独未評価を区別する。\n\n" + G.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n" + G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 二評価の定義と判定\n" + G.table(["評価", "候補", "同時点条件", "入口支持", "70目標", "費用資格"], [[r["評価ID"], r["候補ID"], config["PSY突破"][r["入口"]["戦略"]], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    mapped += results + logic + protection + limits + audits(study, work, mapping)[0]
    # ----------------------------------------
    # 原板・六系列の全件転記を避け、pointer/正本/証明/版/Viewerを参照する。
    files = ("入力台帳.json", "準備参照.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "指標品質.json", "入力品質.json", "作業成果物.json")
    sources = [HERE / n for n in ("README.md", "指標.py", "入口.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py") if (HERE / n).is_file()]
    docs = [ROOT / n for n in ("docs/technical-analysis/指標/サイコロジカルライン.md", "docs/technical-analysis/指標/ボリンジャーバンド.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md", "docs/議論/価格突破へ方向頻度を加えた比較.md") if (ROOT / n).is_file()]
    viewing = "## 閲覧と再表示\n\n" + " / ".join(G.link(study / n, readme) for n in files if (study / n).is_file()) + "\n\nコード：" + " / ".join(G.link(p, readme) for p in sources) + "。\n\n"
    viewing += "同じ66場を小型pointerとSHAで参照し原板を複製/再抽出しない。六gzipはGit外work・展開内容SHAを作業成果物へ保存。Viewer一覧は事前P0/P1各66場、API代表2資源。market_pathはdata_root/pnl_pathはcatalog基準。--prepareは数値/原P/全採否だけでlabel/PnL/量集約なし。主再生は既存結果/正式中間物を拒否し、固定を上書きしない。再生の詳細はコードREADMEへ従う。\n\n"
    fence = chr(96)*3
    viewing += "保存値だけの再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/PSY突破/レポート.py\n" + fence + "\n\n"
    paths = [Path(__file__), ROOT / "scripts/一目基準線/レポート.py", ROOT / "scripts/反転確認時計/レポート.py", F.F.DISPLAY,
             ROOT / "scripts/SAR持続/レポート.py", ROOT / "scripts/終値切替/レポート.py", ROOT / "scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG, manifest,
             *[study / n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study / n).is_file()], *audit_paths, *sources, *docs]
    planned = work / "診断予定.json"
    if planned.is_file():
        paths.append(planned)
    for path, text in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存帳票だけを指定先へ再表示する。

    引数: なし。--study/--work/--outputは正式/作業/表示先。
    返り値: None。主再生/先着/損益を再計算しない。
    """
    parser = argparse.ArgumentParser(description="価格突破とBB幅とPSYの保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
