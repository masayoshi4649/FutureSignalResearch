"""同じCCI突破登録の即時/水準指値を、保存先着と実運用に分けて表示する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00034_CCI突破の水準指値"
WORK = ROOT/"work/突破指値/00034"
PREVIOUS = ROOT/"study/00033_CCI突破と足内終値位置"
ENTRY_STUDY = ROOT/"study/00031_CCI持続と上位BB幅"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("E0", "E1")
CANDIDATES = ("3分_E0_XF", "3分_E1_XF")
COMMON = ROOT/"docs/議論/CCI突破の即時と固定高安指値を比較する.md"


def helper() -> Any:
    """固定33の保存表示と版2描画だけを読み込む。

    引数: なし。
    返り値: Anyは表示補助。旧globalを書き換えず、市場/指標/先着を再計算しない。
    """
    spec = importlib.util.spec_from_file_location("突破指値34の保存帳票補助", ROOT/"scripts/終値位置/レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


F = helper()
G, P, number, V2 = F.G, F.P, F.number, F.V2


def definitions(config: dict) -> list[dict]:
    """同登録の即時と指値を二評価へ対応させる。

    引数: config(dict)は34固定条件。
    返り値: list[dict]はR0即時/R1指値。両案とも現方針XF。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["出口"] != [{"出口ID": "XF"}]:
        raise ValueError("3分E0/E1・共通XF以外")
    return [{"評価ID": f"R{i}", "候補ID": cid, "入口": {"入口ID": "3分_"+p, "戦略": p,
        "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True}, "出口": {"出口ID": "XF"}}
        for i, (p, cid) in enumerate(zip(POLICIES, CANDIDATES))]


def validate_reference(path: Path, expected_study: Path, names: set[str]) -> dict:
    """共有文書と明細の参照先・現在版を確認する。

    引数: path(Path)は小型pointer、expected_study(Path)は固定参照先、names(set[str])は必須文書。
    返り値: dictは参照正本。大明細を複製しない。
    """
    ref = G.read_json(path)
    if ref["大明細複製"] is not False or ref["旧固定SHA256"] != G.sha(expected_study/"固定.json") or set(ref["文書と証明"]) != names:
        raise ValueError("共有文書/固定先が不一致")
    for name, item in ref["文書と証明"].items():
        if (ROOT/item["パス"]).resolve() != (expected_study/name).resolve() or G.sha(ROOT/item["パス"]) != item["SHA256"]:
            raise ValueError("共有先文書/証明の版差")
    return ref


def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict, Path]:
    """正式保存値の二案・費用・支持・旧即時対照・固定を検算する。

    引数: study(Path)は34正式先。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/評価/入口/運用/実台帳。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "E0対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    _, _, _, previous_entries, previous_values, manifest = F.validate(PREVIOUS)
    if config["カタログ版"] != 2 or report["全66場既使用"] is not True or report["入口125250評価の変更"] is not True:
        raise ValueError("版2/既使用性/新先着評価が不一致")
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 2 or len(values) != 2 or report["入口評価数"] != 2 or report["運用候補数"] != 2 or report["現方針運用候補数"] != 2:
        raise ValueError("二入口二運用の分母差")
    if report["表示固定ID"] != list(CANDIDATES) or set(entries) != {"3分_E0", "3分_E1"} or set(values) != set(CANDIDATES):
        raise ValueError("事前二案の集合/順序が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("二案の入口/出口/役割差")
        for period, count in zip(PERIODS, (40, 24, 2)):
            e, op = entry[period], row[period]["運用"]
            P.validate_entry(e)
            n = op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count:
                raise ValueError("期間/入口/活動の分母差")
            if op["買い取引数"]+op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n:
                raise ValueError("方向/役割の分母差")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾起動の分母差")
            for fee in (0, 5, 10):
                net, mean = op[f"追加{fee}pt純損益円"], op[f"追加{fee}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*fee*n, abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean, net/n, abs_tol=1e-8):
                    raise ValueError("費用/平均の保存値差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意期の確定額nullを維持する")
            if rule["入口"]["戦略"] == "E0" and (e != previous_entries["3分_T0"][period] or op != previous_values["3分_T0_XF"][period]["運用"]):
                raise ValueError("即時E0の先着/運用が旧33対照と異なる")
            if entries["3分_E0"][period]["候補数"] != entries["3分_E1"][period]["候補数"]:
                raise ValueError("指値未約定を元登録集合から消さない")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        fee_ok = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["入口支持"], row["70目標"], row["費用資格"], row["現方針候補"], row["採用資格"]) != (support, bool(goal), support, bool(goal), fee_ok, True, bool(goal) and fee_ok):
            raise ValueError("支持/70/費用/採用資格の判定差")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()) or report["現方針費用資格数"] != report["費用資格数"] or report["採用資格数"] != sum(r["採用資格"] for r in values.values()):
        raise ValueError("目標/資格件数が不一致")
    required = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    source = validate_reference(study/"入口参照.json", ENTRY_STUDY, required)
    control_ref = validate_reference(study/"対照参照.json", PREVIOUS, required)
    if source["参照試行"] != "00031" or len(source["共有明細"]) != 6 or control_ref["参照試行"] != "00033" or control_ref["候補ID"] != "3分_T0_XF" or len(control_ref["共有明細"]) != 2:
        raise ValueError("旧入口と旧運用対照の参照を分ける")
    control = G.read_json(study/"E0対照同値.json")
    if control["全件一致"] is not True or control["旧先着全件同値"] is not True or control["場候補数"] != 66 or len(control["照合"]) != 66 or not all(r["全運用同値"] and r["全追尾同値"] for r in control["照合"]):
        raise ValueError("E0の旧33全属性対照が未確認")
    if control["対照参照SHA256"] != G.sha(study/"対照参照.json"):
        raise ValueError("対照証明の参照版差")
    pointer = G.read_json(study/"入力台帳.json")
    if (study/pointer["参照"]).resolve() != manifest or pointer["SHA256"] != G.sha(manifest):
        raise ValueError("既使用66場台帳の参照差")
    if config["入口条件参照"]["SHA256"] != G.sha(ENTRY_STUDY/"条件.json") or config["運用条件参照"]["SHA256"] != G.sha(PREVIOUS/"条件.json"):
        raise ValueError("入口/費用後起動条件の共有版差")
    pins = G.read_json(study/"固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT/n) != digest for n, digest in pins.items()):
        raise ValueError("固定出典の現在版に差")
    return config, report, rules, entries, values, manifest


def settings(rules: list[dict]) -> list[dict]:
    """共通CCI突破と価格取得方法・保護・診断を版2へ記す。

    引数: rules(list[dict])は二評価。
    返り値: list[dict]は採用等10設定と診断専用1設定。指値を新たな指標確認と数えない。
    """
    groups = [
        (["P01", "P02", "P07"], ["m03"], rules, "共通登録：固定31C0の前20高安strict突破",
         "同場連続公開前20H/L、現在足除外、C>HH/C<LL。旧C0全801登録を同じ時計/方向で二案へ。CLV条件は追加しない"),
        (["I13"], ["m03"], rules, "共通登録：現前CCI20実方向100超",
         "元H/L/C FractionのTP、各20窓の同じμ/MD、係数3/200。MD0無効、±100等号不可、当場21公開を要する。待機中に新しいCCIで再選別しない"),
        (["I05"], ["m15"], rules, "共通M：当場BB20現前公開ペア準備のみ",
         "15分BB数値carryと当場隣接u/u−1のend/key asof。最新不準備を古正常へ戻さない。BB幅拡大の値条件は使わない"),
        (["P03", "P07"], ["m03"], rules[1:], "E1水準：登録時の旧R/Lを凍結",
         "買target=前20最高H、売target=前20最安L。現在足を含まない出所20番号/登録足/公開keyを保存し、後続窓へ差替・延命しない"),
        (["B01", "P03", "P07"], ["tick"], rules[1:], "E1：+1秒〜30秒内の指値成立BBO価格",
         "買ask<=R/売bid>=Lの最初正常BBOで現在ask/bid約定。等号/価格改善可、30秒等号有効・超過取消、接触後の追加+1秒なし。逐次列は固定水準の執行でtick高安再計算ではない"),
        (["I09"], ["m03"], rules, "共通：元登録ATR正・両案のD固定",
         "固定31の3分ATR14有限正。登録時のATRを保持し、指値待機後の最新足ATRへ差し替えない。3分局所と数値carryは固定31仕様"),
        (["C07"], ["m03", "m15"], rules, "共通：固定31公開・pure登録を継承",
         "3分現前CCIと上位当場pair/asofを同登録で使用。旧13pureとE1指値根拠だけをliveへ、旧label/未来MFEは渡さない。保有/注文中も原登録を消さない"),
        (["B01"], ["tick"], rules[:1], "E0：+1秒〜30秒内の最初正常BBO",
         "旧33T0_XF即時の完全対照。_E0→_T0だけ正規化し全注文/約定/品質/取引/追尾を同値照合。両案一注文・一建玉、後続登録を空き時刻へ延期しない"),
        (["I09", "C06", "E02"], ["tick"], rules, "共通XF：現在返済BBO利益円−122>0strict起動",
         "往復fee22円＋想定片道追加5pt往復100円。起動後D=max(5,ceil(登録ATR/5)*5)、MFE−D/最低名目entry床、買ceil/売floor・非緩和。hard125/TP250/期限、pending中追尾停止"),
        (["E01"], ["tick"], rules, "各新仮約定から125/250を34で直接再判定",
         "旧labelsはE1へ流用不可。成立前の経路を除き新価格/keyから評価し、全仮約定に期限/不足を残す。未約定・登録あたり約定/250、支持/費用/実参加は別"),
        (["P05", "P07", "E01"], ["m03", "tick"], rules, "診断のみ：三群・待機機会・同約定出口",
         "E0全体→E1約定集合のE0→同集合E1。約定群は結果後選別、同時/待機/未約定と実抑止を分ける。同実約定key/価格/ATR/Dだけを共通出口比較し、別約定同episode差を価格単独効果としない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式コピーと作業正本の同一性を確認し、正式側を優先する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは既存証明。未保存/版差は拒否する。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """固定前非PnL準備と正式先着/会計/状態/追尾を別に表示する。

    引数: study/work/output(Path)は保存先と表示先。
    返り値: tuple[str,list[Path]]は明示合否/出典。検算件数を収益標本へ加えない。
    """
    rows, paths = [], []
    groups = [("合成検証.json", "人工指値/原順/TTL/非PnL境界"), ("独立監査.json", "新二先着集計/Decimal会計/全資源"),
        ("状態独立確認.json", "同登録/固定R/L/全新case直接先着/即時対照"), ("追尾独立確認.json", "全保有XF起動/最初要求"),
        ("対応診断.json", "三群先着/未約定機会/参加/共通出口"), ("Viewer照合.json", "二運用の代表Viewer")]
    for name, title in groups:
        path, verdict, count = proof_path(study, work, name), None, None
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data["全件成功"] is True and data["合成編集終了"] is True, data["検証件数"]
            if any(G.sha(ROOT/n) != digest for n, digest in data["ファイルSHA256"].items()):
                raise ValueError("最終合成の主版差")
            for key, file in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):
                    raise ValueError("合成の独立補助版差")
        elif name == "Viewer照合.json":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 2 and all(r["一致"] for r in checks), len(checks)
        if verdict is not True:
            raise ValueError("検査未完:"+name)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("検査の結果版差:"+name)
        if name == "対応診断.json" and data["ファイルSHA256"].get((study/"結果.json").relative_to(ROOT).as_posix()) != G.sha(study/"結果.json"):
            raise ValueError("診断の結果pin差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("会計へ状態/追尾が未接続")
        paths.append(path)
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
    main, independent_path = work/"準備点検.json", proof_path(study, work, "独立準備点検.json")
    independent, lock, ref = G.read_json(independent_path), G.read_json(study/"固定.json"), G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(independent_path):
        raise ValueError("主/独立準備の固定版差")
    if independent["ラベル計算"] is not False or independent["損益計算"] is not False or ref.get("先着計算", ref.get("ラベル計算")) is not False or ref["損益計算"] is not False:
        raise ValueError("非先着/非PnL準備が不一致")
    if "参照" in ref:
        if ref["参照"]["主準備"]["SHA256"] != G.sha(main) or ref["参照"]["独立準備"]["SHA256"] != G.sha(independent_path):
            raise ValueError("軽量準備参照の主独立版差")
        for item in ref["参照"].values():
            path = ROOT/item["パス"]
            if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
                raise ValueError("準備参照の内容版差")
            paths.append(path)
    elif ref["主準備SHA256"] != G.sha(main) or ref["独立準備SHA256"] != G.sha(independent_path):
        raise ValueError("準備参照の主独立版差")
    for key, path in (("条件SHA256", study/"条件.json"), ("入力台帳SHA256", study/"入力台帳.json"), ("入口参照SHA256", study/"入口参照.json"), ("対照参照SHA256", study/"対照参照.json")):
        if independent[key] != G.sha(path):
            raise ValueError("独立準備の現在版差:"+key)
    paths += [main, independent_path]
    rows += [["固定前主準備・label/PnLなし", "66場・非損益", 66, G.link(main, output)], ["固定前独立登録/指値出典", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
    connection_path = proof_path(study, work, "新規会計人工接続.json")
    connection = G.read_json(connection_path)
    if connection["全件一致"] is not True or connection["不一致数"] != 0 or connection["不一致"] or connection["市場資料使用"] is not False or connection["実市場再生"] is not False or connection["実行中code不変"] is not True:
        raise ValueError("新規会計補助の人工接続が未完")
    if any(G.sha(ROOT/n) != digest for n, digest in connection["コードSHA256"].items()):
        raise ValueError("新規会計人工の現在版bind差")
    if G.read_json(proof_path(study, work, "独立監査.json"))["新規会計SHA256"] != G.sha(HERE/"新規会計.py"):
        raise ValueError("会計proofと現在の新規会計補助が不一致")
    paths += [connection_path, HERE/"新規会計.py"]
    rows.append(["後段会計補助の人工接続・主最終合成と別", "一致/合格", number(connection["照合項目数"]), G.link(connection_path, output)])
    if (study/"保存物読取補足.json").is_file() or (work/"保存物読取補足.json").is_file():
        path = proof_path(study, work, "保存物読取補足.json")
        data = G.read_json(path)
        if data["全件一致"] is not True or data["不一致"] or data["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
            raise ValueError("保存物読取補足の合否/対象版差")
        paths.append(path)
        rows.append(["保存物の独立読取/分母/費用分解", "一致/合格", number(data["照合項目数"]), G.link(path, output)])
    text = "## 検査の状態\n\n固定前人工/非先着・非PnL準備と、正式固定後の新仮約定/先着・会計・全状態・全保有追尾を分ける。原登録・価格/公開key/指値/採否/D整数は厳密。独立Wilderの入口ATR表現だけ正式計画の限定許容を使い、任意εを採否へ足さない。検算件数は独立の収益標本ではない。\n"
    return text+G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def comparison(entries: dict, values: dict) -> str:
    """同登録の約定可否と実参加・費用・支持を分けて表示する。

    引数: entries/values(dict)は保存二入口/二運用。
    返り値: strは小集計。未約定を登録集合から落とさない。
    """
    entry_rows, op_rows, supports, quality = [], [], [], []
    for policy, cid in zip(POLICIES, CANDIDATES):
        entry, value = entries["3分_"+policy], values[cid]
        for period in PERIODS:
            e, op = entry[period], value[period]["運用"]
            entry_rows.append([policy, PERIOD_NAMES[period], e["候補数"], e["約定候補数"], e["未約定"],
                G.pct(e["約定候補数"]/e["候補数"] if e["候補数"] else None),
                f"{e['順行先着']}/{e['候補数']}・{G.pct(e['順行先着']/e['候補数'] if e['候補数'] else None)}",
                f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}", f"{e['逆行先着']}/{e['期限未達']}/{e['観測不足']}"])
            op_rows.append([cid, PERIOD_NAMES[period], op["完結取引数"], *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"]])
            quality.append([cid, PERIOD_NAMES[period], op["追尾起動取引数"], op["起動後純赤字取引数"], f"{op['活動場数']}/{op['無取引場数']}", op["未解消場数"], op["EOF期限未達場数"], number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                supports.append([cid, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if entry["入口支持"] else "未達", "達成" if entry["70目標"] else "未達", "充足" if value["費用資格"] else "未達", "充足" if value["採用資格"] else "未達"])
    text = "## 同じ登録からの新先着と実運用\n\n二入口は同じ元登録を持つが、指値の未約定と新規価格/時計が異なる。先着主率の分母は期限/不足も含む全仮約定、未約定は別記。先着は実返済後も観測する反事実で、実参加や費用後売買勝率ではない。注意期の総額/平均は観測値で確定額nullを置き換えない。\n"
    text += G.table(["入口", "期間", "全登録", "仮約定", "未約定", "全登録の仮約定率", "250/全登録・率", "250/全仮約定・率", "30分間引き250/仮約定・率", "125/期限/不足"], entry_rows)
    text += G.table(["運用", "期間", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場"], op_rows)
    text += "### 支持と採用資格\n\n入口支持は学習60仮約定/6日/10場・選択20/3/5。70目標は両期主率と30分間引き率70%以上、間引き件数20/10も必要。費用資格は学習20完結/6日/10場/買売各5・選択10/3/6/各3、注意0・追加片道5pt後の両期黒字を要する。両案XFの現方針候補で、採用には入口70と費用資格の双方を要する。後続2場や期間合算で不足を代用しない。\n"
    text += G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "入口支持", "70目標", "費用資格", "採用資格"], supports)
    return text+G.table(["運用", "期間", "追尾起動", "起動後基準赤字", "活動/無取引場", "未解消", "EOF未達", "基準確定対象円"], quality)


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """約定群の選別・待機・取り逃しと実参加の差を表示する。

    引数: study/work/output(Path)は保存先と表示先。
    返り値: strは診断小表。新先着/運用の再生は行わない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    if data["全件一致"] is not True:
        raise ValueError("対応診断未完")
    text = "## 元登録で対応する三群の先着\n\n"+G.link(path, output)+"を正本とする。Aは即時E0の全登録、Bは結果後にE1が仮約定した同じ登録だけのE0、Cはその登録のE1。A→Bは約定群の選別、B→Cは同群で取得方法を変えた差。B/Cの登録数は選別後の群で、全登録に対するE1の仮約定率/250率は上の二入口表で読む。Cの率だけで全登録や指値単独の効果を代表させない。\n"
    text += G.table(["期間", "群", "群の登録/仮約定", "群の仮約定率", "250/群の全仮約定・率", "250/群の登録", "125/期限/不足/未約定"],
        [[PERIOD_NAMES[r["期間"]], r["群"], f"{r['候補数']}/{r['約定候補数']}", G.pct(r["登録あたり約定率"]), f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", G.pct(r["登録あたり250先着率"]), f"{r['逆行先着']}/{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in data["先着三群"]])
    text += "### 同時・待機・未約定\n\n同時は新規時計・原行・価格が同じ場合。秒差0でも後行なら待機として数える。価格条件は正常BBO現在価格で判定し、登録足のヒゲ接触を約定にしない。\n"
    text += G.table(["期間", "仮約定対応", "元登録数", "E0の250/約定", "E1の250/約定"],
        [[PERIOD_NAMES[r["期間"]], r["約定対応"], r["元登録数"], f"{r['E0']['順行先着']}/{r['E0']['約定候補数']}", f"{r['E1']['順行先着']}/{r['E1']['約定候補数']}"] for r in data["元登録の約定四区分"]])
    text += G.table(["期間", "最初適格BBOの指値条件", "両仮約定", "同秒後行待機", "登録→指値秒中央値", "即時→指値秒中央値", "取得改善pt中央値"],
        [[PERIOD_NAMES[r["期間"]], G.describe(r["最初適格BBOの指値条件"]), r["両仮約定元登録数"], r["同秒別行待機数"], number(r["登録からE1仮約定秒"]["中央値"]), number(r["E0からE1仮約定秒"]["中央値"]), number(r["実方向の取得価格改善pt"]["中央値"])] for r in data["両仮約定の待機と取得価格"]])
    supplement_path = proof_path(study, work, "保存物読取補足.json")
    supplement = G.read_json(supplement_path)
    text += "### 原行まで分けた保存値の四分位\n\n"+G.link(supplement_path, output)+"による同じ元登録の別分割。『待機』を同秒後行/時計後続に分け、E1未約定には両未約定も含む。先の四区分へ加算しない。Q1/中央値/Q3は結果後の記述で、要求終値から固定突破線までの距離は当時既知でも、約定key群や距離帯を新しい採否にしていない。\n"
    text += G.table(["期間", "仮約定key群", "元登録数", "取得改善pt Q1/中/Q3", "E0→E1秒 Q1/中/Q3", "登録終値→旧線pt Q1/中/Q3"],
        [[PERIOD_NAMES[r["期間"]], r["約定key区分"], r["元登録数"],
          "/".join(number(r["実方向取得価格改善pt"][k]) for k in ("Q1", "中央値", "Q3")),
          "/".join(number(r["E0からE1まで価格時計秒"][k]) for k in ("Q1", "中央値", "Q3")),
          "/".join(number(r["登録要求終値から固定突破線までpt"][k]) for k in ("Q1", "中央値", "Q3"))]
         for r in supplement["純仮約定key四区分"]])
    text += "### 指値未約定でも即時では仮250だった機会\n\n未約定群は参加を断った機会であり、指値の実現損失や回収できた利益ではない。観測正常気配なしと、観測気配はあるが指値不成立を分け、観測の間の未知の価格接触を推定しない。\n"
    text += G.table(["期間", "E1未約定登録", "同登録E0の250/仮約定", "E0の125/期限/不足/未約定", "未約定の観測区分"],
        [[PERIOD_NAMES[r["期間"]], r["E1未約定登録数"], f"{r['同登録E0の先着']['順行先着']}/{r['同登録E0の先着']['約定候補数']}", "/".join(str(r["同登録E0の先着"][k]) for k in ("逆行先着", "期限未達", "観測不足", "未約定")), G.describe(r["未約定の観測区分"])] for r in data["指値未約定の即時機会"]])
    text += "## 同元登録と同実新規の二つの対応\n\n同episodeでも新規価格/時計が変われば、hard/TP・残り観測時間・現在費用後起動の原点が変わる。差は取得方法と待機を含む方針差で、価格だけ/出口だけの効果ではない。共通出口に使うのは同実約定key・価格かつ同入口ATR/Dだけ。別元登録が同じ実新規になった場合も別記する。\n"
    text += G.table(["期間", "両実参加episode", "同約定ATR共通/他の約定", "E0のみ/E1のみepisode", "取得改善pt中央値", "待機秒中央値", "同episode追加5差中央値円"],
        [[PERIOD_NAMES[r["期間"]], r["両実参加元登録数"], f"{r['同約定ATR数']}/{r['異約定ATR数']}", f"{r['E0のみ元登録数']}/{r['E1のみ元登録数']}", number(r["同元登録の実方向取得価格改善pt"]["中央値"]), number(r["同元登録の新規待機秒"]["中央値"]), number(r["同元登録の追加5pt純額差円"]["中央値"])] for r in data["同元登録の実参加対応"]])
    text += "以下の厳密片側取引には、同じ元登録に両案が別価格/時計で入った取引も含む。E0のみ/E1のみの元登録数とは異なる。\n"
    text += G.table(["期間", "厳密共通新規/元登録差/出口差数", "共通出口差0/5/10円", "厳密E0のみ完結・0/5/10円", "厳密E1のみ完結・0/5/10円", "総差0/5/10円"],
        [[PERIOD_NAMES[r["期間"]], f"{r['同約定ATR共通実新規数']}/{r['共通の元登録相違数']}/{r['共通出口属性差数']}", "/".join(number(v["同約定ATR共通出口差円"]) for v in r["費用別"]), str(r["E0のみ"]["完結取引数"])+"・"+"/".join(number(r["E0のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), str(r["E1のみ"]["完結取引数"])+"・"+"/".join(number(r["E1のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), "/".join(number(v["総差円_E1引くE0"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["期間", "E0のみ取引の相手E1取扱", "E1のみ取引の相手E0取扱"], [[PERIOD_NAMES[r["期間"]], G.describe(r["E0のみの相手取扱"]), G.describe(r["E1のみの相手取扱"])] for r in data["実参加比較"]])
    text += "## 仮先着と実回収・利益保護\n\n仮先着は実返済後も観測する反事実。実保有MFE250も回収済み250利益とは限らない。起動後基準赤字の同値費用と不利返済を分ける。\n"
    text += G.table(["運用", "期間", "実完結", "対応仮250", "判定前返済", "実MFE250", "起動/基準赤字", "同値費用/不利返済"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], r["対応仮250数"], r["仮250判定前返済数"], r["実保有MFE250数"], f"{r['起動数']}/{r['起動後基準赤字数']}", f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}"] for r in data["候補別回収"]])
    text += "### E1実完結の事後利益保護群\n\n分母はE1実完結で、純仮約定や全登録とは別。未起動・起動後名目同値費用赤字・不利返済赤字・その他を分ける。『その他』は基準赤字以外だが追加費用後に赤字となる取引を含む。距離分布の重なりや事後群を当時の入口に戻さず、同約定への費用感度を新しい指値約定と解釈しない。\n"
    text += G.table(["期間", "実完結後区分", "取引数", "登録終値→旧線pt Q1/中/Q3", "赤字数0/5/10pt"],
        [[PERIOD_NAMES[r["期間"]], r["実完結後区分"], r["取引数"],
          "/".join(number(r["登録要求終値から固定突破線までpt"][k]) for k in ("Q1", "中央値", "Q3")),
          "/".join(str(r["追加費用別純赤字数"][str(f)]) for f in (0, 5, 10))] for r in supplement["E1実完結の利益保護区分"]])
    text += "以下の同値未満/最終線不足は追尾起動後の取引に限る。名目設定線の床と、実返済BBO価格を分ける。\n"
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
    """正式保存値と全証明の完成後だけ二Markdownを生成する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場・先着・運用を再計算しない。
    """
    config, report, rules, entries, values, manifest = validate(study)
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    common, catalog = settings(rules), V2.load_catalog()
    intro = "NK225・固定31C0の同じ登録を、E0即時とE1登録時の前20高安指値で比較する二入口・共通XFの二運用。価格構造と現前CCIを共通にし、上位BBは公開準備のみ。記録はカタログ版2・52手法×9尺度。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2、採用資格は{report['採用資格数']}/2。** 取得価格改善・未約定機会・先着・実参加・費用後の総額と平均を別々に読む。\n\n"
    left, right = values[CANDIDATES[0]], values[CANDIDATES[1]]
    conclusion += "E0→E1の"+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(left[p]["入口"]["確認率"])+"→"+G.pct(right[p]["入口"]["確認率"])+"、追加5pt平均"+number(left[p]["運用"]["追加5pt平均円"])+"→"+number(right[p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    warning = [r["候補ID"]+"/"+PERIOD_NAMES[p]+"="+str(r[p]["運用"]["品質注意場数"])+"場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warning:
        conclusion += "品質注意は"+"、".join(warning)+"。該当期の全体確定額はnullで、総額/平均/参加差は観測値。\n\n"
    logic = "## 共有登録と価格取得方法\n\n元登録は固定31C0の当場3分前20高安strict終値突破＋現前CCI20実方向100超。元H/L/C FractionのTP・各20窓の同じ平均/MD・係数3/200、MD0無効/±100等号不可、当場21公開とATR正、当場最新15分BB現前公開ペア/end-key asofを保持する。CLV・上位BB幅の値・SAR・量/OBV/PSY等は追加しない。\n\n"
    logic += "両案は旧C0イベントIDを元登録キーとし、登録時計/方向/ATRを共有。E1は登録時の前20最高H/最安Lを固定し、買ask<=R/売bid>=Lの最初の適格正常BBOで現在価格を使う。要求+1秒以上、+30秒等号有効/超過取消、新規停止/期限が先。価格成立後に追加1秒を待つ案ではない。指値そのものの価格へ仮約定を作らず、窓更新・指値差替・延命・待機中CCI再判定をしない。\n\n"
    logic += "買ask<=RはRを下へ貫いた最初の板も含み、Rで反発したことや支持が維持されたことを確認していない。売りも鏡像。価格が安く/高く戻ったことと、戻った後に元方向へ続くことを区別する。\n\n"
    logic += "23の再テスト足高安の再突破や24の終値f/gを待つ案ではなく、33の同key CLV選別とも異なる。反発確認や失敗反転は今回未実行。支持抵抗への戻りで高値追いを減らせるという心理仮説と、突破失敗側に約定しやすい可能性を両方残す。注文動機や吸収を直接観測したものではない。\n\n"
    logic += "純登録は旧31の再構成から明示13列だけへ射影し、E1は固定指値/根拠を追加。新caseはそのpure・登録出典・新labelだけで旧CCI/contextを全複製しない。旧labelをliveへ渡さず、各案の新規BBOから34で新125/250先着を直接評価する。E0は旧33T0_XFの全注文/約定/品質/取引/追尾を_E0→_T0だけの正規化で一致検査し、数値・属性を除外しない。\n\n"
    protection = "## 利益保護・費用・場内完結\n\n共通XFは現在正常返済BBOのs×(mark−新規)×10−122>0strictで初回追尾起動。122円は往復手数料22＋想定片道追加5pt往復100、境界は12.2pt超で、過去MFEだけでは起動しない。参照滑り5pt固定、感度0/5/10ごとに起動や注文を再選択しない。起動後は登録ATRからD=max(5,ceil(ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低名目新規同値。hard125/TP250/期限、返済pending中更新停止を継承する。設定同値は同値約定や費用後黒字の保証ではない。\n\n"
    protection += "ラージBBOでmicro1枚代理、倍率10円/pt・呼値5pt・片道11円。買ask/売bid新規・返済側BBO、返済は要求+1価格秒以降の最初正常板。追加5/10ptは同じ約定の費用ストレスであり、指値上限を越える新規価格へ変えて成立させた意味ではない。全順行・一注文/一建玉、待機注文や建玉で抑止した後続を空き時刻へ延期しない。自動ドテンや新通常出口を追加しない。\n\n"
    protection += "デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板空白300秒超、未解消/EOF不足を品質へ残す。価格時計は受信時計ではなく、実microの指値キュー・部分約定・実約定可能性を検証したものではない。\n\n"
    limits = "## 限界と知見の扱い\n\n指値約定群は結果後の選別で、良い取得価格だけでは利益の優位性を示さない。未約定で即時なら仮250へ進んだ群も残す。A→Bの選別とB→Cの同群方針差を分け、異なる価格/時計の同episode損益差を価格単独又は出口単独の改善としない。実参加では注文待機/先行建玉/返済待機の抑止を別記する。\n\n"
    limits += "同じ実約定key/価格でも入口ATR/Dが違えば共通出口比較へ混ぜない。同登録二案や密接なrolling発動を独立標本として水増しせず、既使用資料の計算一致・価格改善・少数黒字を将来の安定利益へ読み替えない。確認反発/失敗反転/TTL変更などを加えるなら別試行で固定する。\n\n"
    audit_text, audit_paths = audits(study, work, readme)
    results = comparison(entries, values)
    summary = "# 試行00034：CCI突破の水準指値\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json"))+" / "+G.link(mapping, readme)+"\n\n"+conclusion+results+diagnosis(study, work, readme)+logic+protection+limits+audit_text

    # ----------------------------------------
    # 固定カタログ版2をコピーし、登録/執行/診断の役割を各セルへ記す。
    mapped = "# 試行00034：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER, mapping, "コピー元汎用表・版2")+" / "+G.link(readme, mapping)+"\n\n"
    mapped += "## 手法×時間スケール\n\n52手法×9尺度。S01〜S03/S06/S07は共有登録/準備、S04/S05はE1の固定水準と逐次執行、S08はE0即時対照、S09は共通XF、S10は新先着、S11は診断のみ。R0=E0_XF/R1=E1_XF。逐次のP03/P07は既知水準の執行で、tick高安を新計算していない。未使用・未検証・データ不足・対象外を区別する。\n\n"
    mapped += V2.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 二評価の定義と判定\n"+G.table(["評価", "候補", "取得方法", "入口支持", "70目標", "費用資格", "採用資格"], [[r["評価ID"], r["候補ID"], "即時最初正常BBO" if i == 0 else "固定R/L指値成立BBO", "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達", "充足" if values[r["候補ID"]]["採用資格"] else "未達"] for i, r in enumerate(rules)])
    mapped += results+logic+protection+limits+audits(study, work, mapping)[0]

    # ----------------------------------------
    # 巨大な旧明細を複製せず、小型参照/Viewer/出典指紋を保存する。
    names = ("入力台帳.json", "入口参照.json", "対照参照.json", "準備参照.json", "E0対照同値.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "作業成果物.json")
    sources = [HERE/n for n in ("README.md", "入口.py", "運用.py", "検証.py", "合成検証.py", "新規会計.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py", "レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/CCI.md", "docs/technical-analysis/組み合わせ/ATRと追尾決済.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md")]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing = "## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n, readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p, readme) for p in sources)+"。\n\n"
    viewing += "入口参照は旧31の八文書/証明・六明細、対照参照は旧33の八文書/証明・運用/追尾二系列を共有する。旧全CCI/context/原板/大きな準備は複製せず、新大明細は最小入口事例・全運用詳細・追尾の3gzip。Git外workの展開内容SHAを正本とし、Viewerは二運用各66場の132資源・2代表。market_pathはdata_root、pnl_pathはcatalog基準。\n\n"
    viewing += "--prepareは同登録/指値出典/純信号だけで新先着・運用・損益なし。正式は新caseの先着を計算し、既存結果/partialを上書きしない。コードREADMEの順序に従う。保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/突破指値/レポート.py\n```\n\n"
    if COMMON.is_file():
        viewing += G.link(COMMON, readme, "共通知見")+"。\n\n"
    paths = [Path(__file__), Path(F.__file__), ROOT/"scripts/CCI突破/レポート.py", ROOT/"scripts/一目基準線/レポート.py", ROOT/"scripts/反転確認時計/レポート.py", F.F.F.F.DISPLAY,
        ROOT/"scripts/SAR持続/レポート.py", ROOT/"scripts/終値切替/レポート.py", ROOT/"scripts/レポート/設定結果レポート.py", ROOT/"scripts/レポート/カタログ版2.py", V2.BASE, V2.CATALOG, V2.MASTER, manifest,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *names) if (study/n).is_file()],
        PREVIOUS/"結果.json", PREVIOUS/"固定.json", PREVIOUS/"条件.json", ENTRY_STUDY/"条件.json", *sources, *docs, *audit_paths]
    for path in (work/"診断予定.json", ROOT/"work/入口価格比較34の記録案.md"):
        if path.is_file():
            paths.append(path)
    for path, text in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存値だけの帳票再表示をCLI起動する。

    引数: なし。CLIは--study/--work/--output。
    返り値: None。市場prepare/先着/運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="CCI突破の水準指値・保存帳票版2")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
