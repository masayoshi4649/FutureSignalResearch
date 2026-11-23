"""固定C0の費用起動変更と同時点CLV選別を、二入口三運用から表示する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
WORK = ROOT/"work/終値位置/00033"
OLD_STUDY = ROOT/"study/00031_CCI持続と上位BB幅"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("T0", "T1")
CANDIDATES = ("3分_T0_X0", "3分_T0_XF", "3分_T1_XF")
COMMON = ROOT/"docs/議論/CCI突破に足内終値位置を加え費用後に追尾を起動する.md"


def helper() -> Any:
    """固定31の表示・版2描画だけを読取再用する。

    引数: なし。
    返り値: Anyは表示補助。旧global/旧ファイルを書き換えず、市場を再生しない。
    """
    spec = importlib.util.spec_from_file_location("終値位置33の固定31保存表示", ROOT/"scripts/CCI突破/レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


F = helper()
G, P, number, V2 = F.G, F.P, F.number, F.V2


def definitions(config: dict) -> list[dict]:
    """二入口・三運用を二段比較の表示評価へ対応させる。

    引数: config(dict)は33条件正本。
    返り値: list[dict]はR0旧参考/R1費用起動/R2CLV追加。T1_X0を作らない。
    """
    exits = {r["出口ID"]: r for r in config["出口"]}
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or set(exits) != {"X0", "XF"}:
        raise ValueError("3分T0/T1・旧参考X0/現方針XF以外")
    return [{"評価ID": f"R{i}", "候補ID": cid, "入口": {"入口ID": "3分_"+cid.split("_")[1],
        "戦略": cid.split("_")[1], "時間足分": 3, "名称": cid.split("_")[1], "役割": "順行", "複合本命": True},
        "出口": exits[cid.split("_")[2]]} for i, cid in enumerate(CANDIDATES)]


def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict, Path]:
    """保存正本の二案・全期間・旧T0対照・費用・固定を確認する。

    引数: study(Path)は33正式先。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/定義/入口/運用/実台帳。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "T0対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    _, old_report, _, old_entries, old_values, manifest = F.validate(OLD_STUDY)
    if report["全66場既使用"] is not True or report["入口125250評価の変更"] is not True:
        raise ValueError("既使用性又は二入口選別の評価対象が不一致")
    if config["カタログ版"] != 2 or config["入口条件参照"]["SHA256"] != G.sha(OLD_STUDY/"条件.json"):
        raise ValueError("版2又は固定31条件参照と異なる")
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 2 or len(values) != 3 or report["入口評価数"] != 2 or report["運用候補数"] != 3:
        raise ValueError("二入口三運用の分母が不一致")
    if report["表示固定ID"] != [r["候補ID"] for r in rules] or set(entries) != {r["入口"]["入口ID"] for r in rules}:
        raise ValueError("事前二案の集合/順序が不一致")
    for rule in rules:
        row, entry = values[rule["候補ID"]], entries[rule["入口"]["入口ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("入口/出口/役割定義が不一致")
        for period, count in zip(PERIODS, (40, 24, 2)):
            P.validate_entry(entry[period])
            op = row[period]["運用"]
            n = op["完結取引数"]
            if row[period]["入口"] != entry[period] or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count:
                raise ValueError("期間/入口/活動分母が不一致")
            if op["買い取引数"]+op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n:
                raise ValueError("方向/役割分母が不一致")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾起動の分母が不一致")
            for fee in (0, 5, 10):
                net, mean = op[f"追加{fee}pt純損益円"], op[f"追加{fee}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*fee*n, abs_tol=1e-8):
                    raise ValueError("費用感度の保存値が不一致")
                if (mean is None) != (n == 0) or n and not math.isclose(mean, net/n, abs_tol=1e-8):
                    raise ValueError("費用後平均の分母が不一致")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意込み観測額を確定額へ変換しない")
            if rule["入口"]["戦略"] == "T0" and entry[period] != old_entries["3分_C0"][period]:
                raise ValueError("T0入口集計が固定31C0と異なる")
            if rule["候補ID"] == "3分_T0_X0" and op != old_values["3分_C0_X0"][period]["運用"]:
                raise ValueError("T0_X0運用集計が固定31C0と異なる")
        support = all(all(entry[p][key] >= limit for key, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][key] >= limit for key, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], row["入口支持"], entry["70目標"], row["70目標"], row["費用資格"]) != (support, support, bool(goal), bool(goal), qualified):
            raise ValueError("支持/70/費用資格の判定が不一致")
        current = rule["出口"]["出口ID"] == "XF"
        if row["現方針候補"] != current or row["採用資格"] != (current and bool(goal) and qualified):
            raise ValueError("旧参考を現方針へ含めず、採用には70と費用の双方を要する")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("目標/資格の件数が不一致")
    if report["現方針運用候補数"] != 2 or report["現方針費用資格数"] != sum(r["現方針候補"] and r["費用資格"] for r in values.values()) or report["採用資格数"] != sum(r["採用資格"] for r in values.values()):
        raise ValueError("現方針候補/費用/採用の件数が不一致")
    control = G.read_json(study/"T0対照同値.json")
    if control["全件一致"] is not True or control["場候補数"] != 66 or len(control["照合"]) != 66 or not all(r["全運用同値"] and r["全追尾同値"] for r in control["照合"]):
        raise ValueError("T0旧C0全ledger/trace同値が未確認")
    pointer = G.read_json(study/"入口参照.json")
    required = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    if pointer["参照試行"] != "00031" or pointer["大明細複製"] is not False or pointer["旧固定SHA256"] != G.sha(OLD_STUDY/"固定.json") or set(pointer["文書と証明"]) != required:
        raise ValueError("共有31の固定参照が不一致")
    for name, item in pointer["文書と証明"].items():
        if (ROOT/item["パス"]).resolve() != (OLD_STUDY/name).resolve() or G.sha(ROOT/item["パス"]) != item["SHA256"]:
            raise ValueError("共有先の文書/証明版差")
    pins = G.read_json(study/"固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT/name) != digest for name, digest in pins.items()):
        raise ValueError("固定出典が変更")
    input_pointer = G.read_json(study/"入力台帳.json")
    if (study/input_pointer["参照"]).resolve() != manifest or input_pointer["SHA256"] != G.sha(manifest):
        raise ValueError("既使用66場の台帳参照差")
    return config, report, rules, entries, values, manifest


def settings(rules: list[dict]) -> list[dict]:
    """価格/CCI/上位準備とCLV値追加・執行・診断を版2へ分ける。

    引数: rules(list[dict])は二評価。
    返り値: list[dict]は採用等10設定と診断専用1設定。上位幅値/SARは採用しない。
    """
    groups = [
        (["P01", "P02", "P07"], ["m03"], rules, "固定31C0：前20高安strict終値突破",
         "当場連続公開20H/LへC>HH/C<LL。現在足を前窓から除外、等号/ヒゲ不可。原PをM/CCI/時間/保有で消さず後足へ取り直さない"),
        (["I13"], ["m03"], rules, "共通：現前CCI20実方向100超",
         "元H/L/C FractionのTP、各同窓20平均/MD、係数3/200。MD0無効、現前には当場21公開。±100等号不可、任意ε/表示floatで判定しない"),
        (["I05"], ["m15"], rules, "共通M：当場最新公開BB20現前準備のみ",
         "15分BB数値同限月carry、当場隣接u/u−1の公開/end-key asofを要求。最新不準備を古正常へ戻さない。幅0数値も準備可、BB幅拡大の値を33へ加えない"),
        (["P01"], ["m03"], rules[2:], "T1値追加：H>Lかつ実side×CLV>0strict",
         "CLV=(2C−H−L)/(H−L)を元OHLC Fractionで精密計算。同じ突破足の同公開keyで選別、0不採用。幅0は未定義でT1だけ不採用、T0の共通Mへ移さない。売買符号鏡像"),
        (["I09"], ["m03"], rules, "共通M：ATR14有限正・両出口の入口D固定",
         "3分ATRは同限月carry、欠枠/不正/尾部/限月でclear。X0/XFとも実入口ATRからD固定。前ATR規格化距離の欠測を入口除外へ使わない"),
        (["C07"], ["m03", "m15"], rules, "共通公開：固定31 asofと純信号whitelist",
         "3分局所21公開と上位当場隣接pair/end-keyを維持。純再構成の当時情報だけを新信号へ深複写し、共有caseのlabel/仮新規/未来MFEをliveへ渡さない"),
        (["B01"], ["tick"], rules, "共通：一建玉・新規/返済1価格秒・TTL30",
         "ラージBBOでmicro1枚代理、買Ask/売Bid新規・返済側BBO。同原行は気配→公開足→signal、全順行、自動ドテンなし。価格時計と実受信時計を区別"),
        (["I09", "C06", "E02"], ["tick"], rules[:1], "旧参考X0：MFE5ptで追尾起動",
         "固定31旧A5完全対照。D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、最低名目新規同値、買ceil/売floor・非緩和。現方針採用候補には数えない"),
        (["I09", "C06", "E02"], ["tick"], rules[1:], "現方針XF：現在BBO利益円−122>0strict起動",
         "現在正常返済BBOでs*(mark−新規)*10−(往復手数料22+片道追加5pt往復100)>0。MFEだけで起動しない。起動後のMFE−D/最低名目entry床とhard125/TP250/期限/pending停止は共通。費用感度0/5/10でも参照滑り5の起動を変えない"),
        (["E01"], ["tick"], rules, "共有case選別：125逆行前250順行・支持/費用別",
         "旧31C0の同時計/同仮新規caseを二集合へ選別し、先着経路を再計算しない。T0/T1の純入口・仮約定・実参加・費用/品質を分離、期限/不足を主率から除かない"),
        (["P01", "P05", "P06", "P07", "I09"], ["m03"], rules, "診断のみ：CLV四区分・当時突破位置",
         "T0純入口を幅0無効/実方向正/0/負へ分割。要求終値/仮新規、前ATR・直前20高安幅の規格化距離を記述し、帯域閾値や事後群を今回の採否へ戻さない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同じ正式コピーと作業正本から正式側を優先する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは存在・同一性確認済み正本。版差は拒否する。
    """
    return F.proof_path(study, work, name)


def comparison(entries: dict, values: dict) -> str:
    """二入口と三運用・経済資格と現方針資格の分母を分ける。

    引数: entries/values(dict)は保存された二入口/三運用。
    返り値: strは先着・費用・支持・品質の小表。出口を入口標本へ足さない。
    """
    text = "## 二入口の共有先着\n\nT0/T1の入口は二つ。X0/XFで同じT0先着を独立標本へ増やさない。旧31C0の同時計caseを選別し、全仮約定を分母に期限/不足を除かない。仮先着は実返済後も観測する反事実で、一建玉の実参加や費用後利益とは別である。\n"
    text += G.table(["入口", "期間", "純要求", "250/仮約定・率", "30分間引き250/仮約定・率", "125/期限/不足/未約定"],
        [[eid, PERIOD_NAMES[p], r[p]["候補数"], f"{r[p]['順行先着']}/{r[p]['約定候補数']}・{G.pct(r[p]['確認率'])}",
          f"{r[p]['30分間引き_順行先着']}/{r[p]['30分間引き_約定候補数']}・{G.pct(r[p]['30分間引き_確認率'])}",
          f"{r[p]['逆行先着']}/{r[p]['期限未達']}/{r[p]['観測不足']}/{r[p]['未約定']}"] for eid, r in entries.items() for p in PERIODS])
    text += "## 旧参考と現方針の三運用\n\nR0=T0_X0は旧A5参考、R1=T0_XFは同じ入口で費用後正起動へ変更、R2=T1_XFは同じXFにCLV選別を追加。三つを総当たりにせず二段の比較で読む。経済的な費用資格は各運用で計算するが、現方針候補はXFの二つだけ。採用資格には現方針候補・入口70目標・費用資格を全て要する。注意期の総額/平均は観測値で、全体確定額nullを置き換えない。\n"
    rows, support, protected = [], [], []
    for cid in CANDIDATES:
        row = values[cid]
        entry = entries[row["入口"]["入口ID"]]
        for period in PERIODS:
            op = row[period]["運用"]
            rows.append([cid, PERIOD_NAMES[period], op["完結取引数"], *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"]])
            protected.append([cid, PERIOD_NAMES[period], op["追尾起動取引数"], op["起動後純赤字取引数"], f"{op['活動場数']}/{op['無取引場数']}", op["未解消場数"], op["EOF期限未達場数"], number(op["期間内最大場内DD円"]), number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                e = entry[period]
                support.append([cid, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}",
                    f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}",
                    "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達", "充足" if row["費用資格"] else "未達",
                    "対象外（旧参考）" if cid.endswith("_X0") else "充足" if row["採用資格"] else "未達"])
    text += G.table(["運用", "期間", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場"], rows)
    text += "### 支持・資格・活動\n\n入口支持は学習60仮約定/6日/10場、選択20/3/5。70目標は両期主率と30分間引き率70%以上、間引き件数20/10も要る。経済的費用資格は学習20完結/6日/10場/買売各5、選択10/3/6/各3、注意0・追加片道5pt後の両期黒字を要する。既使用後続2場や期間合算で不足を代用しない。\n"
    text += G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "入口支持", "70目標", "経済費用資格", "現方針採用資格"], support)
    text += "### 利益保護と品質\n\n起動後基準赤字と追加費用後赤字は別。最大場内DDは各場0開始の時価下落で、期間接合の累積DDとはしない。\n"
    return text+G.table(["運用", "期間", "追尾起動", "起動後基準赤字", "活動/無取引場", "未解消場", "EOF未達場", "最大場内DD円", "基準確定対象円"], protected)


def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """固定前準備/人工と正式状態・会計等を別々に表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tuple[str,list[Path]]は合否表/出典。全件検算を収益標本に加えない。
    """
    groups = [("合成検証.json", "人工CLV/鏡像/同時点/非PnL境界"), ("独立監査.json", "共有先着/会計/正式資源"),
        ("状態独立確認.json", "固定31再構成/精密CLV/全採否"), ("追尾独立確認.json", "全保有X0/XF起動と最初要求"),
        ("対応診断.json", "費用起動/形状選別/参加/出口/回収"), ("Viewer照合.json", "三運用の代表Viewer")]
    rows, paths = [], []
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
            if any(G.sha(ROOT/key) != digest for key, digest in data["ファイルSHA256"].items()):
                raise ValueError("合成の主版bind差")
        elif name == "Viewer照合.json":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 3 and all(r["一致"] is True for r in checks), len(checks)
        if verdict is not True:
            raise ValueError("正式検査未完:"+name)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("検査対象の結果版差:"+name)
        if name == "対応診断.json" and data["ファイルSHA256"].get((study/"結果.json").relative_to(ROOT).as_posix()) != G.sha(study/"結果.json"):
            raise ValueError("対応診断の結果pin差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("独立状態/追尾が会計へ未接続")
        paths.append(path)
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
    main, independent_path = work/"準備点検.json", proof_path(study, work, "独立準備点検.json")
    independent, locked, ref = G.read_json(independent_path), G.read_json(study/"固定.json"), G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or locked["主準備SHA256"] != G.sha(main) or ref["参照"]["主準備"]["SHA256"] != G.sha(main) or locked["独立準備SHA256"] != G.sha(independent_path) or ref["参照"]["独立準備"]["SHA256"] != G.sha(independent_path):
        raise ValueError("主独立準備/固定/参照の版差")
    if independent["ラベル計算"] is not False or independent["損益計算"] is not False or ref["先着計算"] is not False or ref["損益計算"] is not False:
        raise ValueError("非PnL準備の明示が不一致")
    for item in ref["参照"].values():
        path = ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("軽量準備参照の版差")
        paths.append(path)
    if independent["条件SHA256"] != G.sha(study/"条件.json") or independent["入力台帳SHA256"] != G.sha(study/"入力台帳.json"):
        raise ValueError("独立準備の条件/入力pointer版差")
    paths += [main, independent_path]
    rows += [["固定前主準備・label/PnLなし", "66場・非損益", 66, G.link(main, output)],
        ["固定前独立数値/CLV/全採否", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
    if (study/"保存物読取補足.json").is_file() or (work/"保存物読取補足.json").is_file():
        path = proof_path(study, work, "保存物読取補足.json")
        data = G.read_json(path)
        if data["全件一致"] is not True or data["不一致"] or data["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
            raise ValueError("保存物読取補足の合否/対象版差")
        paths.append(path)
        rows.append(["保存物の独立読取/費用分解", "一致/合格", number(data["照合項目数"]), G.link(path, output)])
    text = "## 検査の状態\n\n固定前の人工/非PnL準備と、固定後の全状態/共有先着/会計/全保有追尾/代表Viewerを分ける。CLV分数・符号・採否・価格・時点・D整数は厳密。ATRと前ATR規格化距離の独立検算許容は正式計画に従い、閾値へεを加えない。検算件数は独立の収益標本ではない。\n"
    return text+G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """純入口の四区分と実参加/位置/回収/品質を保存診断から表示する。

    引数: study/work/output(Path)は保存先と表示先。
    返り値: strは小集計。原形状全件や共有caseを転載しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    if data["全件一致"] is not True:
        raise ValueError("対応診断未完")
    text = "## 同時点CLVの純入口選別\n\n"+G.link(path, output)+"を正本とし、全原P・共通準備・T0採用・CLV幅有効・符号の各分母を区別する。幅0はT1だけ不採用で、T0に準備条件を加えていない。\n"
    text += G.table(["期間", "全原P", "原Pの共通M", "時間/遅延可P", "先着対象P", "T0", "T0の幅有効", "T1"],
        [[PERIOD_NAMES[r["期間"]], *[r[k] for k in ("原価格発動数", "共通M準備数", "時間遅延可数", "先着評価対象数", "T0純入口数", "T0幅有効数", "T1純入口数")]] for r in data["期間別原発動"]])
    text += "### T0純入口のCLV四区分\n\n全rawではなく、固定31C0と同じT0純入口の分割。正だけT1へ保持し、0/負/幅0無効を見送る。CLV正群の成績をCLV単独の性能としない。\n"
    text += G.table(["期間", "実方向CLV", "純要求", "250/仮約定・率", "125", "期限/不足/未約定"],
        [[PERIOD_NAMES[r["期間"]], r["実方向CLV区分"], r["候補数"],
          f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", r["逆行先着"], f"{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in data["T0純入口のCLV四区分"]])
    text += G.table(["期間", "保持/除外", "純要求", "250/仮約定・率", "125", "期限/不足/未約定"],
        [[PERIOD_NAMES[r["期間"]], group, r[group]["候補数"], f"{r[group]['順行先着']}/{r[group]['約定候補数']}・{G.pct(r[group]['確認率'])}",
          r[group]["逆行先着"], f"{r[group]['期限未達']}/{r[group]['観測不足']}/{r[group]['未約定']}"] for r in data["入口追加比較"] for group in ("保持入口", "除外入口")])
    text += "### 当時の突破位置・前ATR距離は診断のみ\n\n要求終値は未約定を含むT0純入口の保持/除外全件、仮新規はその仮約定だけを分母にする。前ATRや前20高安幅の欠測は補完せず各有効件数を示す。CLV選別で生じた同時点の構成差であり、後足まで待った価格進行ではない。規格化距離の帯域閾値を今回の採否に用いていない。\n"
    text += G.table(["期間", "群", "要求/仮約定", "要求突破pt中央値", "仮新規突破pt中央値", "前ATR有効・距離中央値", "前範囲有効・距離中央値"],
        [[PERIOD_NAMES[r["期間"]], "保持" if r["T1保持"] else "除外", f"{r['要求数']}/{r['仮約定数']}",
          number(r["突破距離pt"]["中央値"]), number(r["仮新規の突破距離pt"]["中央値"]),
          str(r["前ATR規格化突破距離"]["件数"])+"・"+number(r["前ATR規格化突破距離"]["中央値"]),
          str(r["直前範囲規格化突破距離"]["件数"])+"・"+number(r["直前範囲規格化突破距離"]["中央値"])] for r in data["保持除外の当時位置"]])
    supplement = G.read_json(proof_path(study, work, "保存物読取補足.json"))
    text += "### 保存された結果別距離の重なり\n\n"+G.link(proof_path(study, work, "保存物読取補足.json"), output)+"による結果後の記述。T0/T1の250先着群と125先着群について、当時の要求終値の突破距離を前ATR/前範囲で規格化したQ1・中央値・Q3を示す。先着の主率は期限/不足も含む全仮約定を分母とし、ここで二つの結果群だけを比較して分母を変えない。距離分布は重なり、250群と125群の大小は期間を通じて揃わない。四分位を採否閾値へ使っていない。\n"
    text += G.table(["入口", "期間", "事後ラベル", "群件数", "前ATR有効・Q1/中央値/Q3", "前範囲有効・Q1/中央値/Q3"],
        [[r["候補"], PERIOD_NAMES[r["期間"]], r["結果ラベル"], r["候補件数"],
          str(r["前ATR規格化突破距離"]["有効数"])+"・"+"/".join(number(r["前ATR規格化突破距離"][k]) for k in ("Q1", "中央値", "Q3")),
          str(r["直前範囲規格化突破距離"]["有効数"])+"・"+"/".join(number(r["直前範囲規格化突破距離"][k]) for k in ("Q1", "中央値", "Q3"))]
         for r in supplement["先着結果別の保存突破距離四分位"] if r["期間"] in PERIODS[:2] and r["結果ラベル"] in ("順行先着", "逆行先着")])
    text += "### 二段比較の共通実新規と片側参加\n\n費用起動変更はT0_X0→T0_XF、CLV追加はT0_XF→T1_XFで比較する。同入口でも出口変更が後続参加を変える。T1の純入口はT0の部分集合でも、先行建玉の抑止が変わりT1だけ実参加する入口が生じうる。同じ実新規の返済差と各側のみの参加額を全費用0/5/10で分ける。以下の円は品質注意期には観測値である。\n"
    text += G.table(["比較・期間", "左→右", "共通新規・出口属性差", "共通出口差0/5/10円", "左のみ完結・0/5/10円", "右のみ完結・0/5/10円", "総差0/5/10円"],
        [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], r["左"]+"→"+r["右"], f"{r['共通実新規数']}/{r['共通出口属性差数']}",
          "/".join(number(v["共通出口差円"]) for v in r["費用別"]),
          str(r["左のみ"]["完結取引数"])+"・"+"/".join(number(r["左のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)),
          str(r["右のみ"]["完結取引数"])+"・"+"/".join(number(r["右のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)),
          "/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較・期間", "左のみの相手取扱", "右のみの相手取扱"],
        [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], G.describe(r["左のみの相手取扱"]), G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text += "### 仮先着と実保有の回収\n\n共有仮先着は実返済後も観測する反事実。仮250や実保有MFEを回収済み利益へ変換しない。起動後基準赤字は同値返済費用と不利返済に分ける。\n"
    text += G.table(["候補", "期間", "実完結", "対応仮250", "判定前返済", "実MFE250", "起動", "起動後赤字", "同値費用/不利返済"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], *[r[k] for k in ("完結取引数", "仮250先着取引数", "仮250判定前返済数", "実保有MFE250取引数", "追尾起動数", "起動後純赤字数")],
          f"{r['同値返済費用赤字数']}/{r['不利返済赤字数']}"] for r in data["候補別回収"]])
    text += "### 現在費用後正で起動した保存出典\n\n分母は完結取引の初回XF起動出典で、全BBO試行や未完建玉の数ではない。現在返済気配で参照費用122円を控除した値を保存し、過去MFEによる起動と混同しない。起動後に費用後含み益が再び下がっても起動を解除しない。\n"
    text += G.table(["候補", "期間", "完結/起動出典", "現在名目利益pt最小/中央値", "現在控除後円最小/中央値", "参照費用/片道滑り"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], f"{r['実完結数']}/{r['起動出典数']}",
          number(r["現在名目利益pt"]["最小"])+"/"+number(r["現在名目利益pt"]["中央値"]),
          number(r["現在控除後含み益円"]["最小"])+"/"+number(r["現在控除後含み益円"]["中央値"]),
          f"{r['参照費用円']}円/{r['参照片道滑りpt']}pt"] for r in data["XF起動判定の保存出典"]])
    text += "最小/四分位の20ptはこの標本の観測値であり、モデルの名目利益12.2pt超というstrict境界を20ptへ置き換えない。\n\n"
    text += "### 追加5pt後の起動済み赤字の内訳\n\n起動参照と同じ追加5pt尺度でも、名目同値の費用赤字、新規より不利な返済、名目正益が費用を覆えない赤字を分ける。同一約定への費用感度であり、感度ごとに起動/注文を再選択していない。\n"
    text += G.table(["運用", "期間", "起動済み", "追加5後赤字", "名目同値費用", "不利返済", "名目正益の費用負け"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], *[r[k] for k in ("起動済完結数", "起動後純赤字数", "名目同値の費用赤字数", "新規価格より不利な返済赤字数", "名目正益でも費用赤字数")]]
         for r in supplement["起動後赤字の費用別内訳"] if r["片道追加pt"] == 5])
    armed_rows = []
    trades = G.read_csv(study/"固定候補_取引.csv")
    for period in PERIODS:
        for cid in CANDIDATES:
            own = [r for r in trades if r["期間"] == period and r["手法"] == cid and r["追尾起動"] == "True"]
            below = sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in own)
            deficit = [float(r["最終追尾から実返済方向差pt"]) for r in own if r["最終追尾から実返済方向差pt"] not in ("", "None")]
            armed_rows.append([cid, PERIOD_NAMES[period], len(own), below, sum(v < 0 for v in deficit), number(min(deficit) if deficit else None)])
    text += "以下の同値未満/最終線不足は追尾起動後の取引に限る。設定線の床と実際の返済価格を分ける。\n"
    text += G.table(["候補", "期間", "起動済み", "実同値未満", "最終線未満", "最終線から返済の最小差pt"], armed_rows)
    text += G.table(["候補", "期間", "注意/未解消/EOF", "基準観測円", "基準確定対象円"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], f"{r['品質注意場数']}/{r['未解消場数']}/{r['EOF期限未達場数']}", number(r["観測純額円"]["0"]), number(r["全体確定対象円"]["0"])] for r in data["品質と確定額"]])
    return text


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式結果・証明完成後だけ二Markdownを生成する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場入力・主計算は呼ばない。
    """
    config, report, rules, entries, values, manifest = validate(study)
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    catalog, common = V2.load_catalog(), settings(rules)
    intro = "NK225・3分の固定31C0（前20高安strict終値突破＋現前CCI20実方向100超）をT0とし、T1は同じ突破足の実方向CLVstrict正だけを追加する。入口は2案、運用はT0_X0旧A5参考・T0_XF費用後正起動・T1_XFという3案で、現在方針候補はXFの2案。上位15分BBは共通数値/公開ペアの準備のみ。カタログ版2・52手法×9尺度で記録する。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、経済的費用資格は{report['費用資格数']}/3、現方針費用資格は{report['現方針費用資格数']}/2、採用資格は{report['採用資格数']}/2。** 採用には現方針XF・入口70・費用の全てを要する。純入口の選別、実参加の費用後平均、品質注意と確定額を分ける。\n\n"
    for name, left_id, right_id in (("費用起動変更", CANDIDATES[0], CANDIDATES[1]), ("CLV追加", CANDIDATES[1], CANDIDATES[2])):
        left, right = values[left_id], values[right_id]
        conclusion += name+"（"+left_id+"→"+right_id+"）の追加5pt平均は"+"、".join(PERIOD_NAMES[p]+number(left[p]["運用"]["追加5pt平均円"])+"→"+number(right[p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    warnings = [r["候補ID"]+"/"+PERIOD_NAMES[p]+"="+str(r[p]["運用"]["品質注意場数"])+"場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意は"+"、".join(warnings)+"。該当期の全体確定額はnull、総額/平均/参加差は観測値として示す。\n\n"
    logic = "## 複合条件と同時点選別の意味\n\nT0は固定31C0を識別子だけT0へ写した完全対照。3分の当場連続公開前20高安へのstrict終値突破、現前CCI20の実方向100超、ATR14正、当場最新15分BB現前公開ペア準備と時間/遅延を保持する。CCIは元OHLC FractionのTP・各20窓の同じ平均/MD・係数3/200、MD0無効、現前には21公開。BB数値は同限月carryし、当場隣接u/u−1のend/key asofを要する。上位BB幅拡大の値条件、SAR、量/OBV/PSY/ADX/一目を追加していない。\n\n"
    logic += "T1は当時の突破足のH>Lかつs×CLV>0（s=買+1/売−1）だけを追加し、CLV=(2C−H−L)/(H−L)を元H/L/C Fractionで求める。H=Lは未定義、実方向0もstrict不成立。幅0をT0共通Mへ加えず、表示float/任意εで採否を変えない。上下反射でCLV符号とsideがともに反転し、同じ実方向条件になる。CLV不成立を逆張り注文へ変えない。\n\n"
    logic += "価格突破は過去高安を越えた位置、CCIは同窓平均からの乖離、CLVは当該足高安内の終値位置を表す。同じOHLC由来で独立した票ではない。方向側で終えた足は押し戻しが比較的小さいという解釈を仮説とするが、参加者心理/需給の実測や継続の保証ではない。後足確認を待たず同じ公開keyで候補を選別する。\n\n"
    logic += "liveは固定31の純再構成から明示whitelistの当時情報だけを新辞書へ写す。旧C0 case・先着ラベルは正式集計だけに共有し、仮新規/判定/未来MFE等を運用へ渡さない。T0_X0と旧C0_X0の全fill/order/取引/入口取扱/追尾は識別文字列_T0→_C0だけの正規化で一致を検査し、数値や属性を除外しない。前ATR/前20高安幅による距離は記述専用で、欠測も採否へ混ぜない。\n\n"
    protection = "## 利益保護・執行・費用・場内完結\n\nX0は固定31旧A5の完全対照でMFE>=5pt起動。現方針XFは現在正常返済BBOのs×(mark−新規)×10−122>0strictで起動する。122円は往復手数料22円＋想定片道追加5ptの往復100円で、MFEが過去に伸びただけでは起動しない。起動モデルの参照滑りは5pt固定、0/5/10の損益感度ごとに別の起動条件を再生していない。\n\n"
    protection += "起動後は両出口とも入口ATRからD=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低名目新規同値を維持する。起動条件が費用後正でも設定床は名目entryで、手数料込み黒字を保証する床ではない。hard125/TP250/期限と返済pending中追尾停止を維持し、CLVによる通常出口/SARは足さない。設定線は実同値約定や費用後非赤字を保証しない。\n\n"
    protection += "ラージBBOでmicro1枚代理、10円/pt・呼値5pt・片道11円。買Ask/売Bid新規・返済側BBO、要求+1価格秒以降の最初正常板、新規TTL30秒。同原行は気配→公開足→signal。片道追加5/10ptは同じ完結往復へ100/200円を控除する費用感度で、異なる発注経路の再生ではない。全順行、一建玉、自動ドテンなし。\n\n"
    protection += "デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50を継承。正常板空白300秒超、未解消/EOF不足を品質として残す。価格時計は実受信時計ではなく、待機1価格秒は実注文遅延や実micro約定の実測ではない。\n\n"
    limits = "## 限界と次の問い\n\nT0_X0→T0_XFは追尾起動定義だけを変え、T0_XF→T1_XFは同じ費用起動にCLV選別を加える二段比較。T1_X0は実行しておらず、2×2の全交互作用を識別しない。旧A5参考は現在方針採用候補へ数えない。T1純入口はT0の部分集合だが、出口や一建玉の占有時間が後続参加を変える。保持/除外の仮先着、同一実新規の出口差、片側参加差を分け、除外の仮250を実現可能な利益へ置き換えない。共通実新規/仮250対応/CLV符号群は結果後の集計で、良い群だけを当時の別フィルターへ戻さない。\n\n"
    limits += "当時の要求終値位置と、要求後に決まる仮新規価格を区別する。前ATR規格化距離や前範囲距離に新しい帯域を加えるなら別試行で事前固定する。既使用66場の結果を未使用確認や将来成功率とせず、注意込み観測額で確定額nullを埋めない。複合条件の成績をCLV/CCI単独の性能としない。\n\n"
    comparison_text = comparison(entries, values)
    audit_text, audit_paths = audits(study, work, readme)
    summary = "# 試行00033：CCI突破と足内終値位置\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json"))+" / "+G.link(mapping, readme)+"\n\n"
    summary += conclusion+comparison_text+diagnosis(study, work, readme)+logic+protection+limits+audit_text

    # ----------------------------------------
    # 固定カタログ版2をコピーし、同じP01でも値追加と診断を区別する。
    mapped = "# 試行00033：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER, mapping, "コピー元汎用表・版2")+" / "+G.link(readme, mapping)+"\n\n"
    mapped += "## 手法×時間スケール\n\nカタログ版2の52手法×9尺度。S01〜S03/S05/S06は共通入口/準備、S04はT1だけのCLV値追加、S07は執行、S08は旧参考X0、S09は現方針XF、S10は二入口の先着評価、S11は診断のみ。R0=T0_X0旧参考/R1=T0_XF費用起動/R2=T1_XFのCLV追加。I05の15分は準備のみ、幅値選別ではない。未使用・未検証・データ不足・対象外を区別する。\n\n"
    mapped += V2.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目", "固定値"], [[key, G.describe(value)] for key, value in config.items()])
    mapped += "## 三運用の定義と判定\n"+G.table(["評価", "候補", "入口/起動の変更", "入口支持", "70目標", "経済費用資格", "現方針採用資格"],
        [[r["評価ID"], r["候補ID"], {"R0": "固定31C0/旧A5参考", "R1": "同T0/現在BBO利益円−122>0", "R2": "同XF/T0かつCLVstrict正"}[r["評価ID"]], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達", "対象外（旧参考）" if r["出口"]["出口ID"] == "X0" else "充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped += comparison_text+logic+protection+limits+audits(study, work, mapping)[0]

    # ----------------------------------------
    # 固定31の大明細を複製せず、共有参照と新三系列だけを案内する。
    names = ("入力台帳.json", "入口参照.json", "準備参照.json", "T0対照同値.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "作業成果物.json")
    sources = [HERE/n for n in ("README.md", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/CCI.md", "docs/technical-analysis/01_チャートの読み方と仮説化.md", "docs/technical-analysis/組み合わせ/ATRと追尾決済.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md")]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing = "## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n, readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p, readme) for p in sources)+"。\n\n"
    viewing += "固定31C0のcase/全指標/原板・447MB準備を33へ複製しない。入口参照.jsonが旧八文書/証明と六明細を指し、共有caseを旧イベントIDで選別して正式集計だけに使う。新規大明細は形状選別/全運用詳細/追尾の3gzipで、Git外work・展開内容SHAを作業成果物へ保存。新casegzipや全指標コピーは作らない。Viewer一覧は三運用各66場の198資源と3代表。market_pathはdata_root、pnl_pathはcatalog基準。\n\n"
    viewing += "--prepareは純再構成/CLV形状/全採否だけで、label/運用/PnLなし。正式は旧caseラベルを選別し先着経路を再計算せず、既存結果/partialを上書きしない。主再生の詳細はコードREADMEに従う。保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/終値位置/レポート.py\n```\n\n"
    if COMMON.is_file():
        viewing += G.link(COMMON, readme, "共通知見")+"。\n\n"
    paths = [Path(__file__), Path(F.__file__), ROOT/"scripts/一目基準線/レポート.py", ROOT/"scripts/反転確認時計/レポート.py", F.F.F.DISPLAY,
        ROOT/"scripts/レポート/設定結果レポート.py", ROOT/"scripts/レポート/カタログ版2.py", V2.BASE, V2.CATALOG, V2.MASTER, manifest,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *names) if (study/n).is_file()],
        OLD_STUDY/"結果.json", OLD_STUDY/"固定.json", OLD_STUDY/"条件.json", *sources, *docs, *audit_paths]
    if (work/"診断予定.json").is_file():
        paths.append(work/"診断予定.json")
    for path, text in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存正本だけの再表示を起動する。

    引数: なし。CLIは--study/--work/--output。
    返り値: None。市場prepare/先着/運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="同時点CLV選別の保存帳票・版2")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
