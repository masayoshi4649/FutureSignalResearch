"""帰還反転・外側継続と混合占有を、正式保存値だけから表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00037_高安帰還と外側継続の判別"
WORK = ROOT/"work/構造判別/00037"
ENTRY_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/高安帰還と外側継続の同時点判別.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
PAIRS = (("B0", "X0"), ("B0", "XF"), ("R1", "XF"), ("T1", "XF"), ("S1", "XF"))
CANDIDATES = tuple("3分_"+p+"_"+x for p, x in PAIRS)
ROLES = {"B0": "反転", "R1": "反転", "T1": "順行", "S1": "切替"}
ROLE_PAIRS = (("B0", "反転"), ("R1", "反転"), ("T1", "順行"), ("S1", "反転"), ("S1", "順行"))

spec = importlib.util.spec_from_file_location("構造37の固定36表示補助", ROOT/"scripts/量比反転/レポート.py")
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
G, P, V2, number = F.G, F.P, F.V2, F.number


def definitions(config: dict) -> list[dict]:
    """四入口を旧参考と現在XF四案の五評価へ対応する。

    引数: config(dict)は37条件。
    返り値: list[dict]はR0〜R4。集合の切替と実取引役割を区別する。
    """
    if config["戦略"] != ["B0", "R1", "T1", "S1"] or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略": p, "出口ID": x} for p, x in PAIRS]:
        raise ValueError("四入口/五運用の固定組合せ以外")
    return [{"評価ID": "R"+str(i), "候補ID": cid,
        "入口": {"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p, "役割": ROLES[p], "複合本命": True},
        "出口": {"出口ID": x}} for i, ((p, x), cid) in enumerate(zip(PAIRS, CANDIDATES))]


def entrance_flags(entry: dict, config: dict) -> tuple[bool, bool]:
    """保存した期間別指標から固定支持と70条件を検算する。

    引数: entry/config(dict)は期間集計と固定条件。
    返り値: tuple[bool,bool]は支持/70。役割別も同じ基準で参考判定する。
    """
    support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
    goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
    return support, bool(goal)


def validate(study: Path) -> tuple:
    """正式四入口/五運用/五役割群と旧対照・支持・費用・全固定を検算する。

    引数: study(Path)は37正式先。
    返り値: tupleは条件/結果/評価/入口/運用/解決台帳。未実行時は拒否する。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json", "B0対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作らない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if config["カタログ版"] != 2 or report["全66場既使用"] is not True or report["入口125250評価の変更"] is not True:
        raise ValueError("版2/既使用/新方向先着の差")
    if len(entries) != 4 or len(values) != 5 or report["入口評価数"] != 4 or report["運用候補数"] != 5 or report["現方針運用候補数"] != 4 or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("入口4/運用5/現方針4の分母差")
    old = G.read_json(ENTRY_STUDY/"結果.json")
    old_entry = next(r for r in old["入口評価"] if r["入口ID"] == "3分_R0")
    old_op = next(r for r in old["結果"] if r["候補ID"] == "3分_R0_X0")
    for rule in rules:
        row, entry = values[rule["候補ID"]], entries[rule["入口"]["入口ID"]]
        if row["入口"] != rule["入口"] or row["出口"] != rule["出口"] or any(entry[k] != v for k, v in rule["入口"].items()):
            raise ValueError("入口/集合役割/出口定義差")
        for period, count in zip(PERIODS, (40, 24, 2)):
            e, op = entry[period], row[period]["運用"]
            P.validate_entry(e)
            n = op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count or op["買い取引数"]+op["売り取引数"] != n:
                raise ValueError("期間/活動/方向分母差")
            roles = ("反転", "順行") if rule["入口"]["戦略"] == "S1" else (rule["入口"]["役割"],)
            if sum(op["役割別完結数"].get(r, 0) for r in roles) != n or not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("実役割/追尾分母差")
            for fee in (0, 5, 10):
                net, mean = op[f"追加{fee}pt純損益円"], op[f"追加{fee}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*fee*n, abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean, net/n, abs_tol=1e-8):
                    raise ValueError("費用感度/平均差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意期の全体確定nullを保持")
            if rule["入口"]["戦略"] == "B0" and e != old_entry[period]:
                raise ValueError("B0旧R0入口数値差")
            if rule["候補ID"] == CANDIDATES[0] and any(op.get(k) != v for k, v in old_op[period]["運用"].items()):
                raise ValueError("旧X0参考数値差")
        support, goal = entrance_flags(entry, config)
        fee_ok = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        current = rule["出口"]["出口ID"] == "XF"
        if (entry["入口支持"], entry["70目標"], row["入口支持"], row["70目標"], row["費用資格"], row["現方針候補"], row["採用資格"]) != (support, goal, support, goal, fee_ok, current, current and goal and fee_ok):
            raise ValueError("支持/70/費用/現在/採用判定差")
    expected_roles = [("3分_"+p, r) for p, r in ROLE_PAIRS]
    if [(r["入口ID"], r["役割"]) for r in report["役割別入口評価"]] != expected_roles:
        raise ValueError("役割別入口五群の差")
    for row in report["役割別入口評価"]:
        for p in PERIODS:
            P.validate_entry(row[p])
        if (row["入口支持"], row["70目標"]) != entrance_flags(row, config):
            raise ValueError("役割別支持/70の差")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()) or report["現方針費用資格数"] != sum(r["費用資格"] and r["現方針候補"] for r in values.values()) or report["採用資格数"] != sum(r["採用資格"] for r in values.values()):
        raise ValueError("全体資格数差")
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    reference = F.F.F.validate_reference(study/"入口参照.json", ENTRY_STUDY, names)
    control_ref = F.F.F.validate_reference(study/"対照参照.json", ENTRY_STUDY, names)
    if len(reference["共有明細"]) != 6 or len(control_ref["共有明細"]) != 2 or reference["参照試行"] != "00029" or control_ref["参照試行"] != "00029":
        raise ValueError("旧29六明細/対照二明細差")
    control = G.read_json(study/"B0対照同値.json")
    if control["全件一致"] is not True or control["旧先着全件同値"] is not True or control["場候補数"] != 66 or len(control["照合"]) != 66 or not all(r["全運用同値"] and r["全追尾同値"] for r in control["照合"]):
        raise ValueError("旧B0X0対照未完")
    for name in ("入口参照.json", "対照参照.json"):
        if control[name[:-5]+"SHA256"] != G.sha(study/name):
            raise ValueError("旧対照参照版差")
    pointer = G.read_json(study/"入力台帳.json")
    manifest = (study/pointer["参照"]).resolve()
    if pointer["SHA256"] != G.sha(manifest) or manifest != ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json":
        raise ValueError("固定66場台帳差")
    if config["入口条件参照"]["SHA256"] != G.sha(ENTRY_STUDY/"条件.json") or config["運用条件参照"]["SHA256"] != G.sha(EXIT_STUDY/"条件.json") or any(G.sha(ROOT/n) != h for n, h in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("共有/全固定の現在版差")
    return config, report, rules, entries, values, manifest


def settings(rules: list[dict]) -> list[dict]:
    """価格母集団・R/T判別・S占有・旧/現保護を版2の14設定に分ける。

    引数: rules(list[dict])は五評価。
    返り値: list[dict]は設定。VR/MFI/上位S2を採用扱いにしない。
    """
    groups = [
        (["P01", "P02", "I05"], ["m03"], rules, "元P：前20極値更新＋旧BB20strict内", "同場前20公開価格足・現在除外。新安値買P/新高値売Pの元s、元k/両端出典を保持。ヒゲBB外/前C帯外を追加しない"),
        (["I03"], ["m03"], rules, "中心化MACD12/26/9：実注文方向×δH>0", "B0/R1は元s、T1は−元s。Sは実役割ごとの方向。reset初C原点・算術seedEMA/同限月carryを継承、後足確認なし"),
        (["V01", "V02"], ["m03"], rules, "元M：完全q・元Pのt/k同OBV区間", "Tの実sideへkを取り直さない。有限非負観測差分q、完全0可。OBV値/VR準備・値/RVOL正平均は使わない"),
        (["P03", "P07"], ["m03"], [rules[2], rules[4]], "R脚：B0かつ旧L<C<旧H strict全範囲内", "反対端超えを内帰還へ含めず、両端等号を除く。R1はB0部分集合、S反転脚も同式"),
        (["P03", "P07"], ["m03"], rules[3:], "T脚：元s(C−K)<0かつ(−元s)δH>0", "全旧Pから元M/時間を通し、実side=−元s・順行。旧B0補数や旧125先着の反転ではない。外側終値と新極値を独立二票にしない"),
        (["C07", "P03"], ["m03"], rules[4:], "S：同時点R/T和・同方向複数も見送り", "R/T技術候補和から独立競合。実建玉ごとの役割固定、保有役割の変更/自動ドテン/後足待機なし"),
        (["I09"], ["m03"], rules, "共通：当足ATR14正・入口D固定", "元Pの現ATRからD=max(5,ceil(ATR/5)*5)。Tでも同足ATRで、数量kの方向を変更しない"),
        (["C07"], ["m03"], rules, "共通：元P公開key/時間/遅延/分割不変", "元M・残60分・確認遅延30秒・新規停止前を維持。30分間引きは元要求。旧24のb/f/g寿命や上位準備を継承しない"),
        (["B01"], ["tick"], rules, "共通執行：市場要求+1秒/TTL30・一建玉", "買ask/売bid新規・正常返済BBO、単一pending/保有。単独R/Tは別運用、Sは一つの占有を共有して後続を抑止"),
        (["I09", "C06", "E02"], ["tick"], rules[:1], "X0参考：旧A5名目5pt起動", "B0_X0の識別子を旧29R0へ戻して全ledger/trace属性対照。現在方針候補外"),
        (["I09", "C06", "E02"], ["tick"], rules[1:], "XF：現在返済BBO利益円−122>0strict", "往復fee22＋参照片道5pt往復100。現在益で一度起動、以後MFE−D/最低名目entry床・非緩和・pending中凍結"),
        (["E01"], ["tick"], rules, "新先着：実sideの新規から125/250直接判定", "Tに旧反転labelの補数を使わない。B0/R1同時計反転は旧11列同値、Sと単独脚も同新規同値を検算。期限/不足/未約定を分離"),
        (["P03", "P07", "I03"], ["m03"], rules, "診断のみ：全構造×元MACD/保持除去/競合", "旧範囲内/元外側/反対端外側/等号と元向き/継続向き/0/未準備を保存。事後の成功群を新採否へ戻さない"),
        (["E01", "B01", "P05"], ["tick"], rules, "診断のみ：役割支持/混合占有/異役割同新規", "同元Pと同side/role/key/price/ATR/D共通、別元Pの同新規異役割を分ける。S役割額の和と全額差を0/5/10で検算"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同じ正式/作業証明から正式側を優先する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは既存証明。版差は拒否する。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """純準備・直接先着・全会計・実保護・保存対応を区別して表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: tupleは検査表/出典。検算件数を独立収益標本へ加えない。
    """
    rows, paths = [], []
    groups = (("合成検証.json", "人工構造/方向/役割/混合/固定guard"), ("独立監査.json", "新先着集計/Decimal会計/全資源"),
        ("状態独立確認.json", "全原P/四判定/新方向直接先着/旧X0対照"), ("追尾独立確認.json", "五運用の全保有X0/XFと固定役割"),
        ("対応診断.json", "帰還選別/新T/混合占有/役割/異役割同新規"), ("Viewer照合.json", "五運用の代表Viewer"))
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data["全件成功"] is True and data["合成編集終了"] is True, data["検証件数"]
            if any(G.sha(ROOT/n) != h for n, h in data["ファイルSHA256"].items()):
                raise ValueError("最終人工の主版差")
            for key, file in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):
                    raise ValueError("最終人工の独立版差")
        elif name == "Viewer照合.json":
            verdict, count = len(data.get("照合", [])) == 5 and all(r["一致"] for r in data["照合"]), len(data.get("照合", []))
        if verdict is not True or data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("未完又は結果版差:"+name)
        if name == "対応診断.json" and data["参照SHA256"]["結果.json"] != G.sha(study/"結果.json"):
            raise ValueError("診断の結果版差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("会計へ独立状態/追尾未接続")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    main, independent_path = work/"準備点検.json", proof_path(study, work, "独立準備点検.json")
    independent, lock, ref = G.read_json(independent_path), G.read_json(study/"固定.json"), G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(independent_path):
        raise ValueError("主/独立準備版差")
    if independent["ラベル計算"] is not False or independent["損益計算"] is not False or ref.get("先着計算", ref.get("ラベル計算")) is not False or ref["損益計算"] is not False:
        raise ValueError("準備の非先着/非PnL差")
    for item in ref["参照"].values():
        path = ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("軽量準備参照差")
        paths.append(path)
    paths += [main, independent_path]
    rows += [["固定前主準備・旧R0/全構造/純四入口", "66場・非損益", 66, G.link(main, output)], ["固定前独立構造/元M/全採否", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
    for name in ("会計人工接続.json", "保存物読取補足.json"):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path = proof_path(study, work, name)
        data = G.read_json(path)
        if data["全件一致"] is not True or data["不一致数"] != 0:
            raise ValueError("後段小証明未完")
        if name == "会計人工接続.json" and any(G.sha(ROOT/n) != h for n, h in data["コードSHA256"].items()):
            raise ValueError("会計人工現在版差")
        if name == "保存物読取補足.json" and data["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
            raise ValueError("補足の診断版差")
        rows.append([name+"・主最終人工と別", "一致/合格", number(data["照合項目数"]), G.link(path, output)])
        paths.append(path)
    return "## 検査の状態\n\n非損益準備は旧R0純13列・構造判定・四採否を対象とし、新先着/運用/損益を計算しない。Tの新方向先着は正式で直接検算し、反転の同時計旧先着同値と分ける。ATR/MACD等の独立表現許容は正式計画の範囲だけ、符号/元M/価格/役割/全採否/D整数は厳密。計算一致を収益の独立標本にしない。\n"+G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def result_tables(report: dict, entries: dict, values: dict) -> str:
    """四入口・五役割群・五運用の率/支持/費用を別表へ表示する。

    引数: report/entries/values(dict)は正式保存結果。
    返り値: strは小型表。混合合算を役割単独の支持へ代用しない。
    """
    erows, orows, supports = [], [], []
    for policy in ("B0", "R1", "T1", "S1"):
        for period in PERIODS:
            e = entries["3分_"+policy][period]
            erows.append([policy, ROLES[policy], PERIOD_NAMES[period], e["候補数"], e["約定候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", f"{e['逆行先着']}/{e['期限未達']}/{e['観測不足']}/{e['未約定']}", f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}"])
    for cid in CANDIDATES:
        row = values[cid]
        for period in PERIODS:
            e, op = row[period]["入口"], row[period]["運用"]
            orows.append([cid, "現在" if row["現方針候補"] else "旧参考", PERIOD_NAMES[period], op["完結取引数"], G.describe(op["役割別完結数"]), *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"], number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                supports.append([cid, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if row["入口支持"] else "未達", "達成" if row["70目標"] else "未達", "充足" if row["費用資格"] else "未達", "現在" if row["現方針候補"] else "対象外", "充足" if row["採用資格"] else "未達"])
    text = "## 四入口・五運用の結果\n\n先着主率は期限/観測不足を含む全仮約定が分母、未約定は別記。仮250は実返済後も観測する反事実で、実完結の費用後勝率ではない。B0X0/B0XFは同じ入口評価を共有し二重に数えない。間引きは原P要求時計。\n"
    text += G.table(["入口", "集合役割", "期間", "純要求", "仮約定", "250/全仮約定・率", "125/期限/不足/未約定", "30分間引き250/仮約定・率"], erows)
    text += G.table(["運用", "位置付け", "期間", "実完結", "実役割数", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場", "基準確定円"], orows)
    text += "入口支持は学習60仮約定/6日/10場・選択20/3/5、70目標は両期主率/間引き率70%・間引き件数20/10。費用資格は学習20完結/6日/10場/買売各5、選択10/3/6/各3、品質注意0・追加5pt後両期黒字。現在採用は候補全体の入口70と費用資格を要し、役割別成績も別記する。旧X0は現在候補外。\n"
    text += G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "入口支持", "70目標", "費用資格", "現方針", "採用資格"], supports)
    text += "## 役割別入口の支持と先着\n\nS1の反転/順行はそれぞれの仮約定で評価し、混合合算の支持を片方へ代用しない。役割別判定は正式結果の五群を表示し、候補全体の採用gateとは分ける。役割支持/70は学習＋条件選択の両期判定の再掲であり、後続2場単独が支持条件を満たす意味ではない。\n"
    return text+G.table(["入口/役割", "期間", "要求/仮約定", "仮約定/日/場", "250/全仮約定・率", "間引き250/仮約定・率", "両期の役割支持", "両期の役割70"], [[r["入口ID"]+"/"+r["役割"], PERIOD_NAMES[p], f"{r[p]['候補数']}/{r[p]['約定候補数']}", f"{r[p]['約定候補数']}/{r[p]['約定開始日数']}/{r[p]['約定場数']}", f"{r[p]['順行先着']}/{r[p]['約定候補数']}・{G.pct(r[p]['確認率'])}", f"{r[p]['30分間引き_順行先着']}/{r[p]['30分間引き_約定候補数']}・{G.pct(r[p]['30分間引き_確認率'])}", "充足" if r["入口支持"] else "未達", "達成" if r["70目標"] else "未達"] for r in report["役割別入口評価"] for p in PERIODS])


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """全P・帰還選別・混合占有・異役割同新規を保存診断から表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは小型集計。全個別ログや旧contextを転記しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    text = "## 全価格Pから構造/勢いを判別する段階\n\n"+G.link(path, output)+"が正本。元Pのsと実side、旧両端/元K・元Mを分ける。全構造×勢いの0群はJSONへ残し、下表は原Pが存在した区分だけを表示する。原P数は入口の仮約定数と別。\n"
    text += G.table(["期間", "全P/元M時間遅延可", "B0/R1/T1/S1", "構造区分", "候補別競合"], [[PERIOD_NAMES[r["期間"]], f"{r['原P数']}/{r['元M時間遅延通過数']}", f"{r['B0純入口数']}/{r['R1純入口数']}/{r['T1純入口数']}/{r['S1純入口数']}", G.describe(r["構造区分数"]), G.describe(r["候補別同時競合数"])] for r in data["原発動と四入口"]])
    text += G.table(["期間", "構造", "元sに対するδH", "全P/元M時間可", "B0/R1/T1/S1採用"], [[PERIOD_NAMES[r["期間"]], r["構造区分"], r["元Pに対するMACD"], f"{r['原P数']}/{r['元M時間遅延通過数']}", f"{r['B0採用数']}/{r['R1採用数']}/{r['T1採用数']}/{r['S1採用数']}"] for r in data["構造と勢いの全区分"] if r["原P数"]])
    text += "## B0→R1：同時点の帰還選別\n\n保持/除外はB0純入口の分割。除外の仮250を取り逃した機会として残し、逆売買や実現可能円に変換しない。R1は同じ元方向/要求/取得で、保持群自身の先着が変化したわけではない。\n"
    text += G.table(["期間", "保持要求/仮約定・250率", "除外要求/仮約定・250率", "保持125/期限/不足/未約定", "除外125/期限/不足/未約定", "除外構造"], [[PERIOD_NAMES[r["期間"]], f"{r['保持入口']['候補数']}/{r['保持入口']['約定候補数']}・{r['保持入口']['順行先着']}/{r['保持入口']['約定候補数']}={G.pct(r['保持入口']['確認率'])}", f"{r['除外入口']['候補数']}/{r['除外入口']['約定候補数']}・{r['除外入口']['順行先着']}/{r['除外入口']['約定候補数']}={G.pct(r['除外入口']['確認率'])}", "/".join(str(r["保持入口"][k]) for k in ("逆行先着", "期限未達", "観測不足", "未約定")), "/".join(str(r["除外入口"][k]) for k in ("逆行先着", "期限未達", "観測不足", "未約定")), G.describe(r["除外した構造区分"])] for r in data["B0の帰還保持除外"]])
    text += "## 単独R/TとS混合の純役割・実運用\n\n同じ役割の単独と混合で純イベントが同じでも、一建玉の実参加は変わる。単独R/Tの円の和をSの実装可能損益としない。役割別の円は観測値で、品質/確定額の適用は候補全体の欄も参照する。\n"
    text += G.table(["期間", "単独/混合役割", "単独/混合純数", "共通元P", "単独だけ/混合だけ"], [[PERIOD_NAMES[r["期間"]], r["単独入口"]+"/"+r["混合役割"], f"{r['単独純入口数']}/{r['混合純入口数']}", r["共通元P数"], f"{r['単独のみ数']}/{r['混合のみ数']}"] for r in data["単独と混合の純役割"]])
    text += G.table(["運用/実役割", "期間", "完結/日/場", "買/売", "基準/追加5/追加10観測円", "追加5平均円"], [[r["候補ID"]+"/"+r["役割"], PERIOD_NAMES[r["期間"]], f"{r['完結取引数']}/{r['活動日数']}/{r['活動場数']}", f"{r['買い数']}/{r['売り数']}", "/".join(number(r[f"追加{f}pt純損益円"]) for f in (0, 5, 10)), number(r["追加5pt平均円"])] for r in data["役割別実運用"]])
    text += "## 同役割共通出口と実参加の差\n\n厳密共通は場/実side/実役割/実新規key/価格/ATR/D。同元Pの対応と分け、混合役割比較はSの該当役割だけが右側の分母。共通0なら出口差0は比較対象なし。厳密片側には同新規で役割だけ違う取引も含むため、次の別表を併読する。\n"
    text += G.table(["比較/期間", "対象役割", "同元P同役割/厳密共通", "共通元P相違/出口差数", "共通出口差0/5/10円", "左のみ完結・0/5/10円", "右のみ完結・0/5/10円", "全差0/5/10円"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], r["対象役割"], f"{r['同元P同役割の両実参加数']}/{r['同役割厳密共通数']}", f"{r['厳密共通の元P相違数']}/{r['共通出口属性差数']}", "/".join(number(v["同役割共通出口差円"]) for v in r["費用別"]), str(r["左のみ"]["完結取引数"])+"・"+"/".join(number(r["左のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), str(r["右のみ"]["完結取引数"])+"・"+"/".join(number(r["右のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), "/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較/期間", "左のみの相手取扱", "右のみの相手取扱"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], G.describe(r["左のみの相手取扱"]), G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text += "## 別元P・異役割だが同じ実新規だった群\n\n同足の安値P反転買と高値P継続買は、元Pも役割も違っても同じ実side/key/価格/ATR/Dになり得る。これを独立した新しい機会と数えず、同役割厳密共通とは別に照合する。\n"
    text += G.table(["比較/期間", "同新規異役割", "同元P/別元P", "役割対応", "出口属性差数", "全費用差0/5/10円"], [[r["左"]+"→"+r["右"]+"/"+PERIOD_NAMES[r["期間"]], r["同新規異役割数"], f"{r['同元P数']}/{r['元P相違数']}", G.describe(r["役割対応"]), r["出口属性差数"], "/".join(number(r["同新規異役割の費用差円"][str(f)]) for f in (0, 5, 10))] for r in data["同新規異役割"]])
    text += "## Sの役割順序と抑止\n\n連続取引は前の建玉を返済してから次に参加した保存列で、自動ドテンを行った実績ではない。役割変更と実方向変更も別。保有/約定済み注文の要求〜約定keyを対応し、取消時刻のない待機種は未確定のまま残す。\n"
    text += G.table(["期間", "S実完結", "連続役割", "役割変更・同方向/逆方向", "前返済→次新規秒中央値", "候補役割/保有pending/相手役割", "全入口取扱"], [[PERIOD_NAMES[r["期間"]], r["S実完結数"], G.describe(r["連続実役割"]), f"{r['役割変更かつ実方向同じ数']}/{r['役割変更かつ実方向反対数']}", number(r["前返済から次新規秒"]["中央値"]), G.describe(r["抑止の候補役割と保有待機"]), G.describe(r["全入口取扱"])] for r in data["Sの役割順序と抑止"]])
    text += "## 仮先着と実回収・利益保護\n\n仮250と実保有MFE250、判定前返済を分ける。設定された最低名目床は費用後同値や同値約定を保証しない。\n"
    text += G.table(["運用", "期間", "実完結", "仮250/判定前返済", "実MFE250", "起動/基準赤字", "同値費用/不利/正益費用負け"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], f"{r['対応仮250数']}/{r['仮250判定前返済数']}", r["実保有MFE250数"], f"{r['起動数']}/{r['起動後基準赤字数']}", f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}/{r['正名目利益の基準費用負け数']}"] for r in data["候補別回収"]])
    text += "以下の同値未満/最終線不足は追尾起動後の取引に限る。\n"
    trades, floors = G.read_csv(study/"固定候補_取引.csv"), []
    for cid in CANDIDATES:
        for p in PERIODS:
            own = [r for r in trades if r["手法"] == cid and r["期間"] == p and r["追尾起動"] == "True"]
            below = sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in own)
            deltas = [float(r["最終追尾から実返済方向差pt"]) for r in own if r["最終追尾から実返済方向差pt"] not in ("", "None")]
            floors.append([cid, PERIOD_NAMES[p], len(own), below, sum(v < 0 for v in deltas), number(min(deltas) if deltas else None)])
    text += G.table(["運用", "期間", "起動済み", "実同値未満", "最終線未満", "最終線から返済の最小差pt"], floors)
    return text+G.table(["運用", "期間", "注意/未解消/EOF", "基準観測円", "基準確定円"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], f"{r['品質注意場数']}/{r['未解消場数']}/{r['EOF期限未達場数']}", number(r["観測純額円"]["0"]), number(r["全体確定対象円"]["0"])] for r in data["品質と確定額"]])


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """全証明を結合し、保存結果だけから二MDを再表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場や先着を再生しない。
    """
    config, report, rules, entries, values, manifest = validate(study)
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    catalog, common = V2.load_catalog(), settings(rules)
    intro = "NK225・旧29価格Pを、B0旧反転、R1全高安帰還の反転、T1元側外残留の順行、S1混合へ同時点で分ける。四入口、旧B0X0参考と現在B0/R1/T1/S1XFの五運用。カタログ版2・52手法×9尺度。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/4、費用資格は旧参考を含む{report['費用資格数']}/5、現在方針の費用資格は{report['現方針費用資格数']}/4、採用資格は{report['採用資格数']}/4。**\n\n"
    for policy in ("B0", "R1", "T1", "S1"):
        cid = "3分_"+policy+"_XF"
        conclusion += policy+"XF："+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(entries["3分_"+policy][p]["確認率"])+"・追加5pt平均"+number(values[cid][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    warnings = [r["候補ID"]+"/"+PERIOD_NAMES[p]+"="+str(r[p]["運用"]["品質注意場数"])+"場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意は"+"、".join(warnings)+"。該当期の円と差額は観測値で、全体確定額nullを観測額で置き換えない。\n\n"
    recovery = next(r for r in G.read_json(proof_path(study, work, "対応診断.json"))["候補別回収"] if r["候補ID"] == "3分_T1_XF" and r["期間"] == "条件選択")
    conclusion += f"T1XFの条件選択では、実参加に対応する仮250先着{recovery['対応仮250数']}件のうち{recovery['仮250判定前返済数']}件が判定前返済、実保有MFE250は{recovery['実保有MFE250数']}件。起動{recovery['起動数']}件の基準赤字は{recovery['起動後基準赤字数']}件（同値費用{recovery['名目同値費用赤字数']}・不利返済{recovery['不利返済赤字数']}）。仮先着と利益保護後の実回収を別に評価する。\n\n"
    logic = "## 元P・価格構造・実方向の判別\n\n元Pは同場3分前20価格足の極値更新＋前20終値BB20・2母標準偏差のstrict内終値。新安値買Pの元s=+1/旧K=L、新高値売Pの元s=−1/旧K=H。旧29の中心化MACD12/26/9はreset初有効Cを原点とするC−oへ算術seedEMA、隣接ヒスト差δHを使う。\n\n"
    logic += "B0は旧29R0の全純入口を保つ。R1はB0かつ旧L<C<旧H strict全範囲内。片端を戻しただけで反対端を越えたCは帰還へ含めず、両端等号を除く。T1は全元Pから元M/時間を通し、元s(C−K)<0かつ(−元s)δH>0で実side=−元s・順行。TをB0から選ぶとMACD符号が相反するため、B0の補数/損失群を反転したものではない。\n\n"
    logic += "S1はR/Tの技術候補和から独立に競合処理し、同判断複数は同方向も全見送り。新R1/T1/S1の判別では構造/勢い不一致・境界等号・δH0はWAIT。旧B0へ新しい位置規約は追加せず、境界等号の旧B0入口も対照へ残す。元Pのs/k/Kと実side/役割を別保存し、全採否確定後に複写する。Sの集合名称は切替だが、各建玉はfill時の反転/順行役割を固定し、保有役割の変更や自動ドテンをしない。\n\n"
    logic += "元数量Mは当足完全非負qと元Pのt/k同OBV区間等をそのまま維持する。Tの実sideへ反対端kを取り直さない。完全0量は有効、欠測は0補完せず、量不完全だけでMACD/ATRをresetしない。OBV値の非追随、VR現前準備/値、MFI、上位S2/ADX、SARを追加しない。数量Mを持つB0は量なし基準ではない。\n\n"
    logic += "Tでは有効OHLCの終値が旧端の外に残るだけで、対応する当足高安も旧端を越える。新極値と外側終値を独立した二票に数えない。旧BB内終値と旧高安全範囲内は別の位置情報であり、心理的な支持/抵抗の維持や参加者動機を直接観測したわけではない。\n\n"
    clocks = "## 24・36との差と新先着\n\n旧24は30分6本の登録b後、初内復帰f/外回復gを次の3分足で待ち、寿命6/3足と上位準備を持った。37は同場3分20窓のP当足で分類し、過去登録・後続監視・新たな確定待機・上位S2を継承しない。24の元突破sと37の元反転Pのsは意味が違い、65場対66場や量M/出口も違うため、全体率差を単一条件の改善と扱わない。36のVR不採用群もTへ変換しない。\n\n"
    clocks += "全四入口は実sideの要求+1秒以降正常BBOから新125/250を正式評価する。B0/R1の同時計反転は旧29の11列と照合し、Sと単独脚も同新規の先着を照合する。Tは逆側新規BBOが原点で、旧sのlabelの反転/補数、MFE/判定時計の流用をしない。labelや未来判定をlive純13列へ混ぜない。\n\n"
    clocks += "同元Pでも実side/役割が違えば別入口。逆に同足の別元Pから、同じ実side/key/価格/ATR/Dとなることがあるので、元Pの新規追加だけで独立した機会増加としない。同役割厳密共通と、同新規異役割は別に照合する。間引き・分割は元P要求時計で、後の都合のよい時点に取り直さない。\n\n"
    protection = "## 共通執行・利益保護・費用\n\n取得は市場要求+1価格秒以降・有効30秒以内の最初正常BBO、買ask/売bid。各運用は一注文/一建玉、SだけはR/Tで同じ占有を共有する。後続抑止を空き時刻へ延期しない。価格時計は受信時計ではなく、ラージBBO/観測量から実microのキュー・数量/部分約定を保証しない。\n\n"
    protection += "旧X0参考は名目5pt起動、現在XFは現在正常返済BBOのs_trade×(mark−entry)×10−122>0strictで一度起動。往復fee22円＋参照片道5pt往復100円、名目境界12.2pt超。過去MFEだけでは起動しない。以後入口D=max(5,ceil(ATR/5)*5)、max(0,MFE−D)、買ceil/売floor・最低名目entry床・非緩和、返済pending中凍結。hard125/TP250/期限を維持する。名目床は費用後同値や遅延後の同値約定を保証しない。\n\n"
    protection += "micro1枚代理・倍率10円/pt・呼値5pt・片道11円、返済要求+1秒以降の正常返済BBO。追加0/5/10ptは同約定に対する費用負荷で、起動参照5ptを取り直さない。デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板300秒超空白等は品質に残し、未解消/EOF/経路注意を確定額へ混ぜない。\n\n"
    limits = "## 知見の限界と再利用\n\nB0→R1は帰還の選別、Tは新方向、Sは単独と異なる一建玉占有を含む全方針差。共通出口差＋右のみ額−左のみ額を全費用で分解し、総損失縮小だけを一取引平均・共通回収改善としない。候補全体の支持/採用gateと役割別評価を分け、混合合算で薄い役割を支持済みにしない。\n\n"
    limits += "全入口は同じ旧Pに依存し、同元P/同新規を独立標本として重複加算しない。少数の高率や計算一致、既使用66場の差は未使用確認や将来利益の証明ではない。事後の位置/勢い/抑止/利益保護群を新しい採否へ戻さず、主要条件や閾値を変えるなら別試行で固定する。\n\n"
    table, (audit_text, audit_paths) = result_tables(report, entries, values), audits(study, work, readme)
    summary = "# 試行00037：高安帰還と外側継続の判別\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json"))+" / "+G.link(mapping, readme)+"\n\n"+conclusion+table+diagnosis(study, work, readme)+logic+clocks+protection+limits+audit_text

    # ----------------------------------------
    # 固定版2へ元P・R/T脚・S競合・役割支持と旧/現保護を記録する。
    mapped = "# 試行00037：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER, mapping, "コピー元汎用表・版2")+" / "+G.link(readme, mapping)+"\n\n"
    mapped += "## 手法×時間スケール\n\n52手法×9尺度。R0=旧B0X0参考/R1=B0XF/R2=R1XF/R3=T1XF/R4=S1XF。S04はR脚、S05はT脚、S06はS混合、S10旧参考/S11現在XF、S13/S14は診断のみ。元量Mを値条件とせず、VR/MFI/上位S2を採用扱いにしない。未使用・未検証・データ不足・対象外を区別する。\n\n"+V2.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 五評価の定義\n"+G.table(["評価", "候補", "集合役割", "入口支持", "70目標", "費用資格", "現方針", "採用資格"], [[r["評価ID"], r["候補ID"], r["入口"]["役割"], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達", "現在" if values[r["候補ID"]]["現方針候補"] else "旧参考・対象外", "充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped += table+logic+clocks+protection+limits+audits(study, work, mapping)[0]

    # ----------------------------------------
    # 新しい列は構造判定・最小case・ledger・traceの4gzipに限定する。
    names = ("入力台帳.json", "入口参照.json", "対照参照.json", "準備参照.json", "B0対照同値.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "作業成果物.json")
    sources = [HERE/n for n in ("README.md", "入口.py", "運用.py", "検証.py", "合成検証.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py", "レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/MACD.md", "docs/technical-analysis/指標/OBV.md", "docs/議論/終値内復帰と外回復を上位状態で選別する.md", "docs/README.md", "docs/議論/README.md", "docs/議論/PDCAの進行.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md", "study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing = "## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n, readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p, readme) for p in sources)+"。\n\n"
    viewing += "入口参照は旧29六明細、対照参照は旧29全ledger/trace二明細と八文書/証明。旧全OHLC/数量/contextや原板を複製せず、新大明細は構造判定・純13列＋元P/元side/旧R0 ID＋新label11列のcase・全運用詳細・追尾の4gzip。Tの旧R0 IDはNone。全展開内容SHAを正本とし、Viewerは5運用各66場・330資源と5代表。\n\n"
    viewing += "--prepareは純四入口/全構造/採否だけで新先着・運用・損益を計算しない。旧caseは純射影の同値確認に参照する。正式は既存結果/部分gzipを上書きしない。再現はコードREADME、保存値だけの再表示は次のとおり。\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/構造判別/レポート.py\n```\n\n"
    if COMMON.is_file():
        viewing += G.link(COMMON, readme, "共通知見")+"。\n\n"
    display_sources = [ROOT/"scripts"/name/"レポート.py" for name in ("量比反転", "回復監視", "突破指値", "終値位置", "CCI突破", "一目基準線", "反転確認時計", "SAR持続", "終値切替")]
    paths = [Path(__file__), *display_sources, F.F.F.F.F.F.F.DISPLAY, ROOT/"scripts/レポート/設定結果レポート.py", ROOT/"scripts/レポート/カタログ版2.py", V2.BASE, V2.CATALOG, V2.MASTER, manifest,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *names) if (study/n).is_file()], ENTRY_STUDY/"条件.json", ENTRY_STUDY/"固定.json", ENTRY_STUDY/"結果.json", EXIT_STUDY/"条件.json", *sources, *docs, *audit_paths]
    for path in (work/"診断予定.json", ROOT/"work/構造判別37の記録案.md", ROOT/"work/構造判別37の事前案.md", ROOT/"work/構造判別37の独立案.md"):
        if path.is_file():
            paths.append(path)
    for path, body in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存結果だけの正式二MD生成をCLIで起動する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。市場/数値/先着/運用/監査を起動しない。
    """
    parser = argparse.ArgumentParser(description="高安帰還と外側継続・保存帳票版2")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
