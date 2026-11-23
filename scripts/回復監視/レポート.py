"""同登録の30秒/180秒指値と到達後回復を、四段階・二比較で表示する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00035_CCI突破の到達後回復"
WORK = ROOT/"work/回復監視/00035"
PREVIOUS = ROOT/"study/00034_CCI突破の水準指値"
ENTRY_STUDY = ROOT/"study/00031_CCI持続と上位BB幅"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("E1", "E2", "E3")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
COMMON = ROOT/"docs/議論/CCI突破の到達と回復を別々に評価する.md"


def helper() -> Any:
    """固定34の表示と版2描画を読取再用する。

    引数: なし。
    返り値: Anyは保存表示補助。旧global/旧ファイルを変更しない。
    """
    spec = importlib.util.spec_from_file_location("回復35の固定34保存表示", ROOT/"scripts/突破指値/レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


F = helper()
G, P, V2, number = F.G, F.P, F.V2, F.number


def definitions(config: dict) -> list[dict]:
    """E1完全対照・E2寿命延長・E3回復の三評価を固定順に対応する。

    引数: config(dict)は35条件。
    返り値: list[dict]はR1/R2/R3。全案XF・順行。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["出口"] != [{"出口ID": "XF"}]:
        raise ValueError("固定三案/3分/XF以外")
    return [{"評価ID": "R"+str(i), "候補ID": cid, "入口": {"入口ID": "3分_"+p,
        "戦略": p, "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True}, "出口": {"出口ID": "XF"}}
        for i, (p, cid) in enumerate(zip(POLICIES, CANDIDATES), 1)]


def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict, Path]:
    """正式三案・全期間・費用/支持・同ID旧対照・全固定を確認する。

    引数: study(Path)は35正式先。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/評価/入口/運用/実台帳。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "E1対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    _, _, _, previous_entries, previous_values, manifest = F.validate(PREVIOUS)
    if config["カタログ版"] != 2 or report["全66場既使用"] is not True or report["入口125250評価の変更"] is not True:
        raise ValueError("版2/既使用性/新先着評価が不一致")
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 3 or len(values) != 3 or report["入口評価数"] != 3 or report["運用候補数"] != 3 or report["現方針運用候補数"] != 3 or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("三入口/三運用の集合又は分母差")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("入口/出口/役割定義の差")
        for period, count in zip(PERIODS, (40, 24, 2)):
            e, op = entry[period], row[period]["運用"]
            P.validate_entry(e)
            n = op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count:
                raise ValueError("期間/入口/活動の分母差")
            if op["買い取引数"]+op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n or not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("方向/役割/利益保護の分母差")
            for fee in (0, 5, 10):
                net, mean = op[f"追加{fee}pt純損益円"], op[f"追加{fee}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*fee*n, abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean, net/n, abs_tol=1e-8):
                    raise ValueError("費用/平均の保存値差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意期の確定額nullを維持する")
            if rule["候補ID"] == CANDIDATES[0] and (e != previous_entries["3分_E1"][period] or op != previous_values[CANDIDATES[0]][period]["運用"]):
                raise ValueError("同ID E1が旧34と異なる")
            if e["候補数"] != entries["3分_E1"][period]["候補数"]:
                raise ValueError("無発動/未約定を元登録から消さない")
        supported = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = supported and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        fee_ok = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["入口支持"], row["70目標"], row["費用資格"], row["現方針候補"], row["採用資格"]) != (supported, bool(goal), supported, bool(goal), fee_ok, True, bool(goal) and fee_ok):
            raise ValueError("支持/70/費用/採用資格の判定差")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()) or report["現方針費用資格数"] != report["費用資格数"] or report["採用資格数"] != sum(r["採用資格"] for r in values.values()):
        raise ValueError("目標/資格件数の差")

    # ----------------------------------------
    # 入口の旧31参照と、同ID完全対照の旧34参照を混ぜない。
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    source = F.validate_reference(study/"入口参照.json", ENTRY_STUDY, names)
    control_ref = F.validate_reference(study/"対照参照.json", PREVIOUS, names)
    if source["参照試行"] != "00031" or len(source["共有明細"]) != 6 or control_ref["参照試行"] != "00034" or control_ref["候補ID"] != CANDIDATES[0] or len(control_ref["共有明細"]) != 3:
        raise ValueError("旧31入口/旧34三系列対照の参照差")
    proof = G.read_json(study/"E1対照同値.json")
    if proof["全件一致"] is not True or proof["旧先着全件同値"] is not True or proof["場候補数"] != 66 or len(proof["照合"]) != 66 or not all(r["全運用同値"] and r["全追尾同値"] for r in proof["照合"]) or proof["対照参照SHA256"] != G.sha(study/"対照参照.json"):
        raise ValueError("同ID E1全属性対照未完")
    pointer = G.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != manifest or pointer["SHA256"] != G.sha(manifest):
        raise ValueError("既使用66場の台帳参照差")
    if config["入口条件参照"]["SHA256"] != G.sha(ENTRY_STUDY/"条件.json") or config["運用条件参照"]["SHA256"] != G.sha(EXIT_STUDY/"条件.json"):
        raise ValueError("共通入口/費用後起動の版差")
    if any(G.sha(ROOT/n) != digest for n, digest in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定出典の現在版差")
    return config, report, rules, entries, values, manifest


def settings(rules: list[dict]) -> list[dict]:
    """共通技術登録と寿命/回復・占有・新先着を版2へ分ける。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は採用等12設定と診断専用1設定。
    """
    groups = [
        (["P01", "P02", "P07"], ["m03"], rules, "共通登録：固定31C0の前20高安strict突破", "現在足を除いた当場20公開高安へC>R/C<L。旧C0同801登録・同時計/方向を共有、CLVや別の反転を足さない"),
        (["I13"], ["m03"], rules, "共通登録：現前CCI20実方向100超", "元H/L/C FractionのTP、各同窓20平均/MD・係数3/200。MD0無効、±100等号不可、当場21公開を要求。待機中CCIで取り直さない"),
        (["I05"], ["m15"], rules, "共通M：当場BB20現前公開pair準備のみ", "15分数値carryと当場隣接u/u−1/end-key asofを継承。最新不準備へ古正常fallbackなし。BB幅値選別は使わない"),
        (["P03", "P07"], ["m03"], rules, "共通水準：登録時R/L・窓を固定", "旧20高安・出典・登録ATRを保持。tick列は既知水準の監視/執行で、tick高安を再計算しない"),
        (["B01", "P03", "P07"], ["tick"], rules[:1], "E1：旧34の30秒指値完全対照", "登録+1〜30秒、買ask<=R/売bid>=Lの最初正常BBO現在価格。30秒等号有効。旧34と同IDの全case/detail/traceを属性除外なしで照合"),
        (["B01", "P03", "P07"], ["tick"], rules[1:2], "E2：同指値を180秒へ延長", "価格条件/登録ATRは同じ。+1〜180秒で最初成立、180秒等号可。E1既存群は同新規/同先着、延長追加群を別に数える"),
        (["B01", "P03", "P07"], ["tick"], rules[2:], "E3：到達→strict後key回復→市場要求+1秒", "到達は買ask<=R/売bid>=L、回復は買bid>R/売ask<L。初回を一回消費、残60分/回復+1<=元期限可のみ要求。元180秒期限不変、回復後の市場価格へ指値上限を課さない"),
        (["I09"], ["m03"], rules, "共通：登録ATR14正・全案のD固定", "登録時ATRを保持し、回復時最新足へ差替しない。Wilder数値carry/局所公開は固定31仕様"),
        (["C07"], ["m03", "m15"], rules, "共通：公開/分割/間引きは元登録b", "要求時計/原行は元b、E3新規要求b′を別列。無回復Noneをbへfallbackしない。回復待機を元足の確認遅延へ置き換えない"),
        (["B01"], ["tick"], rules, "実占有：一注文/建玉、E3は一監視予約", "全登録の仮監視と独立。E3監視中/注文中/保有中の後続を記録して消費。新しい水準へ予約差替・延期・自動ドテンなし"),
        (["I09", "C06", "E02"], ["tick"], rules, "共通XF：現在BBO利益円−122>0strict起動", "参照片道滑り5pt/往復fee22+滑り100。起動後D=max(5,ceil(登録ATR/5)*5)、MFE−D/最低名目entry床・非緩和、hard125/TP250/期限、pending中更新停止"),
        (["E01"], ["tick"], rules, "各新仮約定から125/250・元bで30分間引き", "成立前の動きをMFE/先着へ加えない。全仮約定に期限/不足を残し未約定別記、全登録あたり発動/約定/250率と実参加・支持・費用を分離"),
        (["P05", "P07", "E01"], ["m03", "tick"], rules, "診断のみ：延長群/回復四群/実占有と同約定出口", "延長の共通/追加、E2全体→回復技術群→E3仮約定群→同群E3を分解。結果後の群を新採否へ戻さず、異価格/時計同episode差を価格単独/出口単独効果としない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同一の正式/作業証明から正式側を優先する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは既存証明。未保存/版差は拒否する。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """非PnL準備と正式状態/直接先着/会計/追尾の範囲を分ける。

    引数: study/work/output(Path)は保存先と表示先。
    返り値: tuple[str,list[Path]]は検査表/出典。検算数を収益標本に加えない。
    """
    rows, paths = [], []
    groups = [("合成検証.json", "人工回復/期限/同key/非PnL"), ("独立監査.json", "新先着集計/受付/Decimal会計/全資源"),
        ("状態独立確認.json", "同登録/仮監視/新case直接先着/旧E1全属性"), ("追尾独立確認.json", "全保有XF起動/最初要求"),
        ("対応診断.json", "延長/回復四群/実占有/同約定出口"), ("Viewer照合.json", "三運用の代表Viewer")]
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data["全件成功"] is True and data["合成編集終了"] is True, data["検証件数"]
            if any(G.sha(ROOT/n) != digest for n, digest in data["ファイルSHA256"].items()):
                raise ValueError("合成の主版差")
            for key, file in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):
                    raise ValueError("合成の独立版差")
        elif name == "Viewer照合.json":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 3 and all(r["一致"] for r in checks), len(checks)
        if verdict is not True:
            raise ValueError("検査未完:"+name)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("検査対象の結果版差")
        if name == "対応診断.json" and data["ファイルSHA256"].get((study/"結果.json").relative_to(ROOT).as_posix()) != G.sha(study/"結果.json"):
            raise ValueError("診断結果のpin差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("会計へ状態/追尾が未接続")
        paths.append(path)
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
    main, independent_path = work/"準備点検.json", proof_path(study, work, "独立準備点検.json")
    independent, lock, ref = G.read_json(independent_path), G.read_json(study/"固定.json"), G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(independent_path):
        raise ValueError("主/独立準備の版差")
    if independent["ラベル計算"] is not False or independent["損益計算"] is not False or ref.get("先着計算", ref.get("ラベル計算")) is not False or ref["損益計算"] is not False:
        raise ValueError("準備の非先着/非PnLが不一致")
    for name, path in (("主準備", main), ("独立準備", independent_path)):
        if ref["参照"][name]["SHA256"] != G.sha(path):
            raise ValueError("軽量準備参照の版差")
    for item in ref["参照"].values():
        path = ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("準備参照内容の差")
        paths.append(path)
    paths += [main, independent_path]
    rows += [["固定前主準備・技術観測のみ/新規先着Pnlなし", "66場・非損益", 66, G.link(main, output)], ["固定前独立登録/仮到達・回復", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
    for name, title in (("新規会計人工接続.json", "後段会計補助の人工接続・主最終合成と別"), ("保存物読取補足.json", "保存物の独立読取/分母/費用分解")):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path = proof_path(study, work, name)
        data = G.read_json(path)
        if data["全件一致"] is not True or data["不一致数"] != 0 or data["不一致"]:
            raise ValueError("後段証明の合否差:"+name)
        if name == "保存物読取補足.json" and data["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
            raise ValueError("補足対象の診断版差")
        if name == "新規会計人工接続.json" and any(G.sha(ROOT/n) != digest for n, digest in data["コードSHA256"].items()):
            raise ValueError("会計人工の現在版bind差")
        paths.append(path)
        rows.append([title, "一致/合格", number(data["照合項目数"]), G.link(path, output)])
    text = "## 検査の状態\n\n固定前の登録/技術的な仮到達・回復観測と、新仮約定/先着・損益を計算する正式段階を区別する。登録/水準/時点/監視/採否/D整数は厳密、独立Wilderの入口ATR表現だけ計画の限定許容。全取消理由の独立走査範囲は各証明本文に従い、保存取扱文字列の対応だけを過大に述べない。検算件数は独立の収益標本ではない。\n"
    return text+G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def entry_table(rows: list[dict]) -> str:
    """群の全登録・全仮約定と各先着を小表へ整形する。

    引数: rows(list[dict])は群名又は入口名を持つ保存集計。
    返り値: strはMarkdown表。結果後群の登録を全801と混同しない。
    """
    return G.table(["期間", "群/入口", "群登録/仮約定", "約定率", "250/全仮約定・率", "250/群登録", "125/期限/不足/未約定"],
        [[PERIOD_NAMES[r["期間"]], r.get("群", r.get("入口")), f"{r['候補数']}/{r['約定候補数']}", G.pct(r["登録あたり約定率"]), f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", G.pct(r["登録あたり250先着率"]), f"{r['逆行先着']}/{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in rows])


def comparison(entries: dict, values: dict) -> str:
    """三案の主先着/間引き/費用/支持を別分母で表示する。

    引数: entries/values(dict)は三入口/三運用。
    返り値: strは小集計。回復時刻で間引きを取り直さない。
    """
    rows, ops, supports = [], [], []
    for policy, cid in zip(POLICIES, CANDIDATES):
        e, row = entries["3分_"+policy], values[cid]
        for period in PERIODS:
            item, op = e[period], row[period]["運用"]
            rows.append([policy, PERIOD_NAMES[period], item["候補数"], item["約定候補数"], item["未約定"], f"{item['順行先着']}/{item['約定候補数']}・{G.pct(item['確認率'])}", f"{item['30分間引き_順行先着']}/{item['30分間引き_約定候補数']}・{G.pct(item['30分間引き_確認率'])}"])
            ops.append([cid, PERIOD_NAMES[period], op["完結取引数"], *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"], number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                supports.append([cid, PERIOD_NAMES[period], f"{item['約定候補数']}/{item['約定開始日数']}/{item['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if e["入口支持"] else "未達", "達成" if e["70目標"] else "未達", "充足" if row["費用資格"] else "未達", "充足" if row["採用資格"] else "未達"])
    text = "## 三入口・三運用の結果\n\n全登録は同じC0集合、仮参加は各登録独立。先着主率は期限/不足を含む全仮約定が分母で、未約定を別記する。30分間引きは原登録bが基準。仮先着は実返済後も観測する反事実で、実参加や費用後売買勝率とは別。注意期の円は観測値で確定額nullを置き換えない。\n"
    text += G.table(["入口", "期間", "全登録", "仮約定", "未約定", "250/全仮約定・率", "原bの30分間引き250/仮約定・率"], rows)
    text += G.table(["運用", "期間", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場", "基準確定円"], ops)
    text += "入口支持は学習60仮約定/6日/10場・選択20/3/5。70目標は両期主率/間引き率70%と間引き件数20/10。費用資格は学習20完結/6日/10場/買売各5・選択10/3/6/各3、注意0・追加5pt後の両期黒字を要する。全案現方針XFで、採用には入口70と費用資格の双方を要する。後続2場や期間合算を支持の代用にしない。\n"
    return text+G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "入口支持", "70目標", "費用資格", "採用資格"], supports)


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """純四段階と実予約・二比較・回収を保存診断から表示する。

    引数: study/work/output(Path)は保存先と表示先。
    返り値: strは小表。監視/先着/運用を再生しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    text = "## 全登録・技術発動・新規要求・仮約定・実参加\n\n"+G.link(path, output)+"を正本とする。E1/E2の指値到達とE3の回復技術発動は同じ意味ではない。E3は回復を観測しても時間不可なら未発注とし、発動数を約定/実参加数へ置き換えない。\n"
    text += G.table(["期間", "共通登録", "30秒既存/延長追加", "E2仮約定/E3到達", "E3回復技術", "時間可/新規要求", "E3仮約定"],
        [[PERIOD_NAMES[r["期間"]], r["共通元登録数"], f"{r['30秒既存仮約定数']}/{r['延長追加仮約定数']}", f"{r['E2仮約定数']}/{r['E3到達数']}", r["E3回復技術発動数"], f"{r['E3回復時間可数']}/{r['E3新規要求数']}", r["E3仮約定数"]] for r in data["登録と価格発動と要求と仮約定"]])
    text += entry_table(data["全登録の三入口先着"])
    text += "## E1→E2：寿命延長の共通群と追加群\n\n30秒以内の共通群は同じ最初のtouch・価格/key・先着を同値照合する。30秒超の新群に架空のE1取得価格を作らない。率の変化は既存群と延長追加群の構成差であり、既存入口の価格改善ではない。\n"+entry_table(data["寿命延長の入口群"])
    text += "## E2→E3：回復技術・時間可用性・取得方法の四群\n\nAはE2全体、Bは結果後にE3回復を観測した同登録でのE2、CはE3が仮約定した同登録でのE2、Dは同群のE3。A→Bは回復群、B→Cは時間/市場約定可用性の選別、C→Dは確認後の時計/価格を含む全取得方針差。B/C/Dの群登録を全801と混同しない。\n"+entry_table(data["回復確認の四入口群"])
    text += G.table(["期間", "E3未約定", "段階理由", "同群E2の250/仮約定"], [[PERIOD_NAMES[r["期間"]], r["E3未約定登録数"], G.describe(r["段階別未約定数"]), f"{r['同登録E2の先着']['順行先着']}/{r['同登録E2の先着']['約定候補数']}"] for r in data["E3未約定のE2機会"]])
    text += "未約定でもE2なら仮250だった群は取り逃した機会で、E3の実現損失や回収可能利益ではない。\n"
    text += G.table(["期間", "回復発動/E3仮約定", "同秒後行回復", "到達→回復秒中央値", "回復→新規秒中央値", "E2→E3秒中央値", "新価格差pt E3−E2中央値", "旧線から新規の実方向pt中央値"], [[PERIOD_NAMES[r["期間"]], f"{r['回復技術発動数']}/{r['E3仮約定数']}", r["同秒後行の到達回復数"], number(r["到達から回復秒"]["中央値"]), number(r["回復からE3新規秒"]["中央値"]), number(r["E2からE3新規秒"]["中央値"]), number(r["実方向新規価格差pt_E3引くE2"]["中央値"]), number(r["元水準からE3新規の実方向距離pt"]["中央値"])] for r in data["回復時計と価格"]])
    text += "新価格差が正なら、買いはより高い/売りはより安い取得である。秒差0でも原行が進めば別key。回復判定BBOと+1秒後の市場新規BBOを分ける。\n"
    text += "## 実一予約と新規注文\n\n以下は実運用の受理された予約で、全登録を独立に観測した仮監視とは別分母。監視終了理由は保存記録/品質の対応で、ここで全気配から取消理由を独立再生成した意味ではない。\n"
    text += G.table(["期間", "原登録取扱", "監視受理/到達/回復", "新要求列/新規注文", "実完結", "監視中抑止", "終了時残監視", "監視終了理由"], [[PERIOD_NAMES[r["期間"]], r["原登録取扱数"], f"{r['監視受理数']}/{r['初回到達数']}/{r['初回回復数']}", f"{r['新規要求列あり数']}/{r['実新規注文数']}", r["実完結数"], r["監視中抑止数"], r["終了監視数"], G.describe(r["監視終了理由数"])] for r in data["実E3監視と新規要求"]])
    text += "## 同元登録と厳密同約定の二比較\n\n同実新規key/価格かつ同登録ATR/Dだけを共通出口とし、返済時計/行/価格/理由と費用差を比べる。厳密片側取引には異価格/時計の同episodeも含むので、片側元登録数と分ける。厳密共通が0件なら、表の出口差0は比較対象がないことを表し、出口単独効果が0だと確認できた意味ではない。\n"
    text += G.table(["比較/期間", "両実参加episode/同約定ATR", "左だけ/右だけepisode", "実方向新価格差中央値pt", "新規時計差中央値秒", "同episode追加5差中央値円"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['両実参加元登録数']}/{r['同約定ATR数']}", f"{r['左のみ元登録数']}/{r['右のみ元登録数']}", number(r["新規価格差pt_右引く左"]["中央値"]), number(r["新規待機秒_右引く左"]["中央値"]), number(r["追加5pt純額差円_右引く左"]["中央値"])] for r in data["同元登録の実参加対応"]])
    text += G.table(["比較/期間", "厳密共通/元登録差/出口差数", "共通出口差0/5/10円", "左のみ完結・0/5/10円", "右のみ完結・0/5/10円", "総差0/5/10円"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['同約定ATR共通実新規数']}/{r['共通の元登録相違数']}/{r['共通出口属性差数']}", "/".join(number(v["同約定ATR共通出口差円"]) for v in r["費用別"]), str(r["左のみ"]["完結取引数"])+"・"+"/".join(number(r["左のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), str(r["右のみ"]["完結取引数"])+"・"+"/".join(number(r["右のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), "/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較/期間", "左のみの相手取扱", "右のみの相手取扱"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], G.describe(r["左のみの相手取扱"]), G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text += "## 仮先着と実回収・利益保護\n\n仮先着は実返済後も観測する反事実。実保有MFE250も回収済み利益へ変換しない。起動後基準赤字は名目同値の費用と不利返済を分ける。\n"
    text += G.table(["運用", "期間", "実完結", "対応仮250/判定前返済", "実MFE250", "起動/基準赤字", "同値費用/不利返済"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], f"{r['対応仮250数']}/{r['仮250判定前返済数']}", r["実保有MFE250数"], f"{r['起動数']}/{r['起動後基準赤字数']}", f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}"] for r in data["候補別回収"]])
    text += "以下の同値未満/最終線不足は追尾起動後の取引に限る。設定線と遅延後実返済を分ける。\n"
    trades, floors = G.read_csv(study/"固定候補_取引.csv"), []
    for cid in CANDIDATES:
        for period in PERIODS:
            own = [r for r in trades if r["手法"] == cid and r["期間"] == period and r["追尾起動"] == "True"]
            below = sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in own)
            delta = [float(r["最終追尾から実返済方向差pt"]) for r in own if r["最終追尾から実返済方向差pt"] not in ("", "None")]
            floors.append([cid, PERIOD_NAMES[period], len(own), below, sum(v < 0 for v in delta), number(min(delta) if delta else None)])
    text += G.table(["運用", "期間", "起動済み", "実同値未満", "最終線未満", "最終線から返済の最小差pt"], floors)
    return text+G.table(["運用", "期間", "注意/未解消/EOF", "基準観測円", "基準確定円"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], f"{r['品質注意場数']}/{r['未解消場数']}/{r['EOF期限未達場数']}", number(r["観測純額円"]["0"]), number(r["全体確定対象円"]["0"])] for r in data["品質と確定額"]])


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式結果と全証明が揃った保存値だけから二MDを生成する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場/監視/先着/運用を再計算しない。
    """
    config, report, rules, entries, values, manifest = validate(study)
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    catalog, common = V2.load_catalog(), settings(rules)
    intro = "NK225・固定31C0の同じ元登録を、E1旧34の30秒指値完全対照、E2指値180秒、E3到達後回復180秒で比較する三入口・共通XFの三運用。価格突破/現前CCI、上位BB公開準備、登録ATRを共有。記録はカタログ版2・52手法×9尺度。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3、採用資格は{report['採用資格数']}/3。** 全登録・発動・仮約定・実参加を区別する。\n\n"
    for name, left_id, right_id in (("寿命延長", CANDIDATES[0], CANDIDATES[1]), ("回復確認", CANDIDATES[1], CANDIDATES[2])):
        left, right = values[left_id], values[right_id]
        conclusion += name+"の"+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(left[p]["入口"]["確認率"])+"→"+G.pct(right[p]["入口"]["確認率"])+"、追加5pt平均"+number(left[p]["運用"]["追加5pt平均円"])+"→"+number(right[p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    warnings = [r["候補ID"]+"/"+PERIOD_NAMES[p]+"="+str(r[p]["運用"]["品質注意場数"])+"場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意は"+"、".join(warnings)+"。該当期の全体確定額nullを観測額で置き換えない。\n\n"
    logic = "## 共通の技術登録と三つの取得方法\n\n元登録は当場3分前20高安strict終値突破＋現前CCI20実方向100超。元OHLC FractionのTP・各同窓20平均/MD・係数3/200、MD0無効/±100等号不可、当場21公開/ATR正、当場最新15分BB現前pair/end-key asofを保持する。CLVや上位BB幅値、SAR・量・別のANDは足さない。元R/Lと登録ATRは固定する。\n\n"
    logic += "E1は同IDで旧34の全case/detail/traceと全dict同値。E2は同じ+1秒有効化/正常BBO価格条件のまま30→180秒へ延長。E3は買ask<=R/売bid>=Lの初回到達後、strict後の原行keyで買bid>R/売ask<Lの初回回復を待つ。同秒後行も可、同key二遷移は不可。180秒は3分1本分の価格時計幅という事前仮説で、次の3分確定足を待つ条件ではない。\n\n"
    logic += "E3回復の残60分・新規停止前・回復+1<=元登録+180が可のとき市場要求。初回回復が時刻不可でも消費し、後を取り直さない。新規は要求+1秒以降の最初正常BBOで元期限内、期限等号可/停止等号不可。回復でTTLをリセットせず、新市場価格へ旧指値の上限を課さない。単発回復は支持持続や将来の継続を証明しない。\n\n"
    logic += "caseの要求時計/原行は元登録b、E3の新規要求b′と回復観測を別列へ分離する。無回復/時間不可の新規要求Noneをbへfallbackしない。間引き・分割はb、待機秒は元足の確認遅延と別である。仮監視は各登録独立、実運用は一予約/一注文/建玉。E3だけの監視記録はXF追尾とは別で、後続抑止の時計を空き時刻へ延期しない。未来観測/labelをlive純信号に混ぜない。\n\n"
    logic += "23は30分高安の突破→確定3分足の再テスト→その足高安の再突破とS2/MACDを待った。35は固定C0/旧水準へBBOで到達・回復する別の時計/価格で、6/3足寿命・同水準一回・失敗反転を継承しない。待機中の新しいCCIやATRで選び直さない。支持/抵抗を取り返す心理仮説は、吸収注文や参加者動機を直接観測した事実と区別する。\n\n"
    protection = "## 利益保護・費用・場内完結\n\n全案XFは現在正常返済BBOのs×(mark−新規)×10−122>0strictで初回起動。往復手数料22円＋想定片道追加5pt往復100円、名目境界12.2pt超で、過去MFEだけでは起動しない。起動後は登録ATRのD=max(5,ceil(ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低名目entry床を維持する。hard125/TP250/期限、返済pending中更新停止を継承。名目床は同値約定や費用後黒字を保証しない。\n\n"
    protection += "ラージBBOでmicro1枚代理、倍率10円/pt・呼値5pt・片道11円。買ask/売bid新規・返済側BBO、返済要求+1価格秒以降の最初正常板。追加0/5/10ptは同約定の費用負荷で、起動や指値成立・新市場価格を感度ごとに取り直さない。実キュー/部分約定/mini-micro全量成立を再現したものではない。\n\n"
    protection += "デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50を継承。正常板300秒超空白・未解消/EOF不足は品質へ残す。価格時計は受信時計ではなく、監視時間を実注文応答秒へ読み替えない。\n\n"
    limits = "## 限界と知見の扱い\n\nE1→E2は寿命延長、E2→E3は回復群選別・時間可用性・市場新規の時計/価格と実予約占有を含む全方針差。回復した群や仮約定した群だけを全登録へ一般化せず、異約定同episode差を価格単独/出口単独効果とはしない。未約定でも別案なら仮250だった機会も残す。\n\n"
    limits += "三案は同じ元登録に依存し、標本を三倍にしない。既使用66場の計算一致・少数高率・総損失縮小を未使用確認や将来の安定利益としない。距離/回復/未起動/利益保護群の事後分割を新フィルターへ戻さず、閾値や主要条件を変えるなら新試行で固定する。\n\n"
    result_text, (audit_text, audit_paths) = comparison(entries, values), audits(study, work, readme)
    summary = "# 試行00035：CCI突破の到達後回復\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json"))+" / "+G.link(mapping, readme)+"\n\n"+conclusion+result_text+diagnosis(study, work, readme)+logic+protection+limits+audit_text

    # ----------------------------------------
    # 固定版2へ三案の登録・水準・時計・占有・評価の役割を写す。
    mapped = "# 試行00035：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER, mapping, "コピー元汎用表・版2")+" / "+G.link(readme, mapping)+"\n\n"
    mapped += "## 手法×時間スケール\n\n52手法×9尺度。S01〜S04/S08/S09は共通登録/準備、S05=E1指値30秒、S06=E2指値180秒、S07=E3到達後回復、S10=実占有、S11=XF、S12=各新規からの先着、S13=診断のみ。R1/R2/R3は複合評価、逐次列のP03/P07は既知水準の利用でtick高安再計算ではない。未使用・未検証・データ不足・対象外を区別する。\n\n"+V2.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 三評価の定義と判定\n"+G.table(["評価", "候補", "取得方法", "入口支持", "70目標", "費用資格", "採用資格"], [[r["評価ID"], r["候補ID"], {"E1": "30秒指値/旧34完全対照", "E2": "同指値180秒", "E3": "到達後回復/市場要求+1秒"}[r["入口"]["戦略"]], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達", "充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped += result_text+logic+protection+limits+audits(study, work, mapping)[0]

    # ----------------------------------------
    # 最小caseとE3監視記録だけを新規にし、旧全指標・原板を複製しない。
    names = ("入力台帳.json", "入口参照.json", "対照参照.json", "準備参照.json", "E1対照同値.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "作業成果物.json")
    sources = [HERE/n for n in ("README.md", "入口.py", "運用.py", "検証.py", "合成検証.py", "新規会計.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py", "レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/CCI.md", "docs/technical-analysis/組み合わせ/ATRと追尾決済.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md")]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing = "## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n, readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p, readme) for p in sources)+"。\n\n"
    viewing += "入口参照は旧31六明細、対照参照は旧34の最小case/運用/追尾三系列と八文書/証明へ接続する。旧CCI/context/原板/大準備を複製せず、新大明細は最小三入口case・全運用詳細（E3だけ監視記録）・XF追尾の3gzip。E1の全dictは旧34と同一。Git外workの展開内容SHAを正本とし、Viewerは三運用各66場の198資源と3代表。market_pathはdata_root、pnl_pathはcatalog基準。\n\n"
    viewing += "--prepareは純登録/技術的到達・回復観測だけで、仮新規・新先着・運用・損益を計算しない。正式は既存結果/partialを上書きしない。詳細はコードREADMEに従う。保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/回復監視/レポート.py\n```\n\n"
    if COMMON.is_file():
        viewing += G.link(COMMON, readme, "共通知見")+"。\n\n"
    display_sources = [ROOT/"scripts"/name/"レポート.py" for name in ("突破指値", "終値位置", "CCI突破", "一目基準線", "反転確認時計", "SAR持続", "終値切替")]
    paths = [Path(__file__), *display_sources, F.F.F.F.F.DISPLAY, ROOT/"scripts/レポート/設定結果レポート.py", ROOT/"scripts/レポート/カタログ版2.py", V2.BASE, V2.CATALOG, V2.MASTER, manifest,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *names) if (study/n).is_file()], PREVIOUS/"結果.json", PREVIOUS/"固定.json", PREVIOUS/"条件.json", EXIT_STUDY/"条件.json", ENTRY_STUDY/"条件.json", *sources, *docs, *audit_paths]
    for path in (work/"診断予定.json", ROOT/"work/回復確認35の記録案.md"):
        if path.is_file():
            paths.append(path)
    for path, text in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """正式保存値だけの帳票再表示を起動する。

    引数: なし。CLIは--study/--work/--output。
    返り値: None。市場prepare/監視/先着/運用を再計算しない。
    """
    parser = argparse.ArgumentParser(description="CCI突破の寿命延長と到達後回復・保存帳票版2")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
