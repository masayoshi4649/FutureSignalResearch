"""上位準備と現在雲方向の保存結果を、版2の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00038_外側継続と上位の現在雲"
WORK = ROOT/"work/上位雲継続/00038"
ENTRY_STUDY = ROOT/"study/00037_高安帰還と外側継続の判別"
UPPER_STUDY = ROOT/"study/00028_基準線復帰と上位一目の方向"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/外側継続へ上位の現在雲を加えた比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("H0", "H1", "H2")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)

spec = importlib.util.spec_from_file_location("上位38の固定37保存表示", ROOT/"scripts/構造判別/レポート.py")
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
G, P, V2, number = F.G, F.P, F.V2, F.number


def definitions(config: dict) -> list[dict]:
    """同じ順行登録の三段階を、現在XF三評価へ対応する。

    引数: config(dict)は38条件。
    返り値: list[dict]はR0〜R2。H0対照も現在方針候補。
    """
    expected = [{"戦略": p, "出口ID": "XF"} for p in POLICIES]
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != expected:
        raise ValueError("3分H0/H1/H2・XF三案以外")
    return [{"評価ID": "R"+str(i), "候補ID": cid,
        "入口": {"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True},
        "出口": {"出口ID": "XF"}} for i, (p, cid) in enumerate(zip(POLICIES, CANDIDATES))]


def validate(study: Path) -> tuple:
    """保存された三入口/三運用/対照/資格/共有参照/固定を検査する。

    引数: study(Path)は38正式先。
    返り値: tupleは条件/結果/評価/入口/運用/実台帳。正式結果がない場合は拒否する。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json", "上位参照.json", "H0対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作らない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    if config["カタログ版"] != 2 or report["全66場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("版2/既使用/同時計先着継承の差")
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if (len(entries), len(values), report["入口評価数"], report["運用候補数"], report["現方針運用候補数"]) != (3, 3, 3, 3, 3) or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("三入口/三運用/現在三案の分母差")
    previous = G.read_json(ENTRY_STUDY/"結果.json")
    old_entry = next(r for r in previous["入口評価"] if r["入口ID"] == "3分_T1")
    old_op = next(r for r in previous["結果"] if r["候補ID"] == "3分_T1_XF")
    for rule in rules:
        row, entry = values[rule["候補ID"]], entries[rule["入口"]["入口ID"]]
        if row["入口"] != rule["入口"] or row["出口"] != rule["出口"] or any(entry[k] != v for k, v in rule["入口"].items()):
            raise ValueError("入口/順行/出口定義差")
        for period, count in zip(PERIODS, (40, 24, 2)):
            e, op = entry[period], row[period]["運用"]
            P.validate_entry(e)
            n = op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count or op["買い取引数"]+op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n:
                raise ValueError("期間/活動/方向/役割分母差")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾の分母差")
            for fee in (0, 5, 10):
                net, mean = op[f"追加{fee}pt純損益円"], op[f"追加{fee}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*fee*n, abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean, net/n, abs_tol=1e-8):
                    raise ValueError("保存費用/平均差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意期の全体確定nullを維持する")
            if rule["候補ID"] == CANDIDATES[0] and (e != old_entry[period] or op != old_op[period]["運用"]):
                raise ValueError("H0の旧37T1先着/全運用集計差")
        support, goal = F.entrance_flags(entry, config)
        fee_ok = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["入口支持"], row["70目標"], row["費用資格"], row["現方針候補"], row["採用資格"]) != (support, goal, support, goal, fee_ok, True, goal and fee_ok):
            raise ValueError("支持/70/費用/現在/採用差")
    role_entries = report["役割別入口評価"]
    if [(r["入口ID"], r["役割"]) for r in role_entries] != [("3分_"+p, "順行") for p in POLICIES]:
        raise ValueError("順行三役割群差")
    for row in role_entries:
        if any(row[p] != entries[row["入口ID"]][p] for p in PERIODS) or (row["入口支持"], row["70目標"]) != F.entrance_flags(row, config):
            raise ValueError("役割別は順行入口全件と同じ分母")
    for field, expected in (("入口70目標達成数", sum(r["70目標"] for r in entries.values())), ("費用資格数", sum(r["費用資格"] for r in values.values())), ("現方針費用資格数", sum(r["費用資格"] for r in values.values())), ("採用資格数", sum(r["採用資格"] for r in values.values()))):
        if report[field] != expected:
            raise ValueError("全体資格数差:"+field)
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    validate_ref = F.F.F.F.validate_reference
    for name, previous_study, files, count in (("入口参照.json", ENTRY_STUDY, names|{"入力品質.json"}, 4),
            ("対照参照.json", ENTRY_STUDY, names|{"入力品質.json"}, 2), ("上位参照.json", UPPER_STUDY, names, 1)):
        ref = validate_ref(study/name, previous_study, files)
        if len(ref["共有明細"]) != count:
            raise ValueError("共有大明細数差:"+name)
    control = G.read_json(study/"H0対照同値.json")
    if control["全件一致"] is not True or control["旧先着全件同値"] is not True or control["場候補数"] != 66 or len(control["照合"]) != 66 or not all(r["全運用同値"] and r["全追尾同値"] for r in control["照合"]):
        raise ValueError("H0全属性対照未完")
    for name in ("入口参照.json", "対照参照.json"):
        if control[name[:-5]+"SHA256"] != G.sha(study/name):
            raise ValueError("対照参照版差")
    pointer = G.read_json(study/"入力台帳.json")
    manifest = (study/pointer["参照"]).resolve()
    if pointer["SHA256"] != G.sha(manifest) or manifest != ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json":
        raise ValueError("固定66場台帳差")
    for key, old_study in (("入口条件参照", ENTRY_STUDY), ("上位条件参照", UPPER_STUDY), ("運用条件参照", EXIT_STUDY)):
        if config[key]["SHA256"] != G.sha(old_study/"条件.json"):
            raise ValueError("共有条件現在版差")
    if any(G.sha(ROOT/n) != h for n, h in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("全固定現在版差")
    return config, report, rules, entries, values, manifest


def settings(rules: list[dict]) -> list[dict]:
    """継承した複合T1と上位準備・値・診断を版2の設定へ分ける。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は13設定。上位T/J診断を採用gateにしない。
    """
    groups = [
        (["P01", "P02", "I05"], ["m03"], rules, "旧P：前20極値更新＋前20CのBB20strict内", "固定29→37の価格Pを共有。現在を除く同場前20公開足、ヒゲBB外/前C帯外を追加しない"),
        (["I03"], ["m03"], rules, "中心化MACD12/26/9：実side×δH>0", "reset初有効C原点のC−oと算術seedEMA。固定37の順行T1値を共有し、38で旧数値を再計算しない"),
        (["V01", "V02"], ["m03"], rules, "元M：完全非負q・元Pのt/k同OBV区間", "元Pのkを実sideへ取り直さない。完全0量可。OBV値選別/RVOL正平均/VR/MFIは追加しない"),
        (["P03", "P07"], ["m03"], rules, "T1：元s(C−K)<0、実side=−元s", "旧全Pの外側残留と実向きMACDを使う順行。元Pの新極値と外側終値は独立二票にしない。反転/S混合/後足待機なし"),
        (["I09"], ["m03"], rules, "共通：当足ATR14正・入口D固定", "元T1の入口ATRを保持。D=max(5,ceil(ATR/5)*5)、上位ATR/Fastを準備へ混ぜない"),
        (["C07"], ["m03"], rules, "元T1要求key・時間・遅延・分割不変", "残60分/確認遅延30秒・旧競合後集合を保持。同key複数を上位選別で復活させず、30分間引きは元要求"),
        (["I11"], ["m15"], rules[1:], "H1共通：最新当場公開雲/T9/J26準備", "固定28の9/26/52・26本shift・最短78数値足。数値carryと当場公開参照を分け、最新不良へ古正常fallbackしない。H0には課さない"),
        (["I11"], ["m15"], rules[2:], "H2追加：実買15分C>雲上端/実売C<雲下端", "H1の準備済みからstrict雲外実方向。同値・雲内・逆雲外は不採用。3分Cを上位Cの代わりに使わない"),
        (["I11", "C07"], ["m15"], rules, "参照：end15<=end3 AND key15<=要求key3", "同足終了/同公開keyは可。両条件を満たす当場publish15の最新一つ。H0も診断参照を保存するが未準備では除外しない"),
        (["B01"], ["tick"], rules, "共通：市場要求+1秒/TTL30・一建玉", "買ask/売bid新規・正常返済BBO、一pending/一建玉。後続抑止を空き時計へ延期しない"),
        (["I09", "C06", "E02"], ["tick"], rules, "XF：現在返済BBO利益円−122>0strict", "往復fee22＋参照片道5pt往復100。以後MFE−D/最低名目entry床・非緩和・pending凍結。費用後同値床ではない"),
        (["E01"], ["tick"], rules, "同時計同新規125/250・旧T1の11label同値", "新規+1秒BBOから正式直接検算し旧37同時計先着と照合。準備/雲選別後の率差は同じ保持入口の先着改善ではない"),
        (["I11", "E01", "B01", "P05"], ["m15", "tick"], rules, "診断のみ：T/J整列・準備/雲区分・占有/回収", "T/Jの同方向/等号/逆方向は診断だけ。準備除外と値選別、純subsetと実追加、同新規出口差と片側損益を分ける"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同byteの正式証明を優先し、作業正本との版差を拒否する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは保存済み証明。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """人工・非損益準備・上位再構成・先着・会計・追尾を区別する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tupleは小型検査表と全出典。計算一致は収益標本ではない。
    """
    rows, paths = [], []
    groups = (("合成検証.json", "人工asof/鏡像/準備と値/純射影/固定guard"),
        ("独立監査.json", "新case集計/Decimal会計/全資源"),
        ("状態独立確認.json", "上位15分数値/全asof/三採否/直接先着/旧T1対照"),
        ("追尾独立確認.json", "三XFの全保有・初回要求・名目床"),
        ("対応診断.json", "上位準備/雲値/TJ診断/実参加/共通出口/回収"),
        ("Viewer照合.json", "三運用の代表Viewer"))
    for name, title in groups:
        path, data = proof_path(study, work, name), G.read_json(proof_path(study, work, name))
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data["全件成功"] is True and data["合成編集終了"] is True, data["検証件数"]
            if any(G.sha(ROOT/n) != h for n, h in data["ファイルSHA256"].items()):
                raise ValueError("人工の主版差")
            for key, file in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):
                    raise ValueError("人工の独立補助版差")
        elif name == "Viewer照合.json":
            verdict, count = len(data.get("照合", [])) == 3 and all(r["一致"] for r in data["照合"]), len(data.get("照合", []))
        if verdict is not True or data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("検査未完又は結果版差:"+name)
        if name == "対応診断.json" and data["参照SHA256"]["結果.json"] != G.sha(study/"結果.json"):
            raise ValueError("診断の結果版差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("会計へ独立状態/追尾未接続")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    main, independent_path = work/"準備点検.json", proof_path(study, work, "独立準備点検.json")
    independent, lock, ref = G.read_json(independent_path), G.read_json(study/"固定.json"), G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(independent_path):
        raise ValueError("主/独立準備join差")
    prepared = G.read_json(main)
    if any(data["ラベル計算"] is not False or data["損益計算"] is not False for data in (prepared, independent)):
        raise ValueError("準備は非先着・非PnL")
    references = ref["参照"].values() if isinstance(ref["参照"], dict) else ref["参照"]
    if ref.get("大準備複製", False) is not False:
        raise ValueError("大準備は軽量参照だけを保存する")
    for item in references:
        path = ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("準備の軽量参照差")
        paths.append(path)
    paths += [main, independent_path]
    rows += [["固定前主準備・旧T1/全15分射影/三採否", "66場・非損益", 66, G.link(main, output)],
        ["固定前独立上位一目/asof/三採否", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
    for name in ("会計人工接続.json", "保存物読取補足.json"):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path, data = proof_path(study, work, name), G.read_json(proof_path(study, work, name))
        if data["全件一致"] is not True or data["不一致数"] != 0:
            raise ValueError("後段小証明未完")
        if name == "会計人工接続.json" and any(G.sha(ROOT/n) != h for n, h in data["コードSHA256"].items()):
            raise ValueError("会計人工の現在版差")
        if name == "保存物読取補足.json" and data["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
            raise ValueError("補足の診断版差")
        rows.append([name+"・主最終人工と別", "一致/合格", number(data["照合項目数"]), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n旧P/MACD/元Pのk・数量M・T1実sideは固定37証明へ接続し、38で再計算したとはしない。下位出典は固定29保存3分、上位数値は固定28保存15分を主が共有し、新独立状態は原8列から上位数値/出典を別再構成する。非損益準備には先着/運用/PnLがなく、正式の全直接先着・新規会計・全追尾は別範囲。\n"
    return text+G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def result_tables(report: dict, entries: dict, values: dict) -> str:
    """先着・支持・費用・現在資格を、三案同じ分母定義で表示する。

    引数: report/entries/values(dict)は正式保存値。
    返り値: strは小型表。後続2場を独立した支持確認にしない。
    """
    erows, orows, supports = [], [], []
    for policy in POLICIES:
        for period in PERIODS:
            e = entries["3分_"+policy][period]
            erows.append([policy, PERIOD_NAMES[period], e["候補数"], e["約定候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", "/".join(str(e[k]) for k in ("逆行先着", "期限未達", "観測不足", "未約定")), f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}"])
    for cid in CANDIDATES:
        row = values[cid]
        for period in PERIODS:
            e, op = row[period]["入口"], row[period]["運用"]
            orows.append([cid, PERIOD_NAMES[period], op["完結取引数"], *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"], number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                supports.append([cid, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if row["入口支持"] else "未達", "達成" if row["70目標"] else "未達", "充足" if row["費用資格"] else "未達", "充足" if row["採用資格"] else "未達"])
    text = "## 三入口・三XF運用の結果\n\n先着主率は期限/観測不足を含む全仮約定が分母、未約定は別記。仮250は実返済後も追う反事実で、実完結の費用後勝率ではない。全案順行・現在XFで、役割別入口三群はそれぞれ同じ入口全件と一致する。\n"
    text += G.table(["入口", "期間", "純要求", "仮約定", "250/全仮約定・率", "125/期限/不足/未約定", "30分間引き250/仮約定・率"], erows)
    text += G.table(["運用", "期間", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場", "基準確定円"], orows)
    text += "入口支持は学習60仮約定/6日/10場・選択20/3/5、70は両期主率/間引き率70%・間引き件数20/10。費用支持は学習20完結/6日/10場/買売各5・選択10/3/6/各3と品質注意0、追加5pt後両期黒字。採用は入口70と費用資格の両方。支持/70は学習＋条件選択を合わせた判定で、後続2場単独の支持確認ではない。\n"
    return text+G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "両期入口支持", "両期70", "費用資格", "採用資格"], supports)


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """準備差・雲値・TJ記述・実占有・回収を保存診断から表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは集計本文。全個別上位値・大明細を転記しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    text = "## 上位準備と雲値の二段比較\n\n"+G.link(path, output)+"が正本。H0→H1は同じ旧T1登録から数値準備だけを選別し、H1→H2は準備済みの当時上位終値を使う。保持/除外は左の純入口の分割であり、保持群自身の先着が条件追加で変化したわけではない。\n"
    text += G.table(["期間", "旧T1/H0/H1/H2純数"], [[PERIOD_NAMES[r["期間"]], "/".join(str(r[k]) for k in ("旧T1登録数", "H0純入口数", "H1純入口数", "H2純入口数"))] for r in data["旧T1と三入口"]])
    text += G.table(["比較/期間", "保持要求/仮約定・250率", "除外要求/仮約定・250率", "保持125/期限/不足/未約定", "除外125/期限/不足/未約定", "純追加数"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], *[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口", "除外入口")], *["/".join(str(r[k][f]) for f in ("逆行先着", "期限未達", "観測不足", "未約定")) for k in ("保持入口", "除外入口")], r["新規追加入口数"]] for r in data["入口追加比較"]])
    text += G.table(["期間", "H0の上位準備区分", "要求/仮約定", "250/全仮約定・率"], [[PERIOD_NAMES[r["期間"]], r["準備区分"], f"{r['候補数']}/{r['約定候補数']}", f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["H0の上位準備区分"]])
    text += G.table(["期間", "H1の雲位置", "要求/仮約定", "250/全仮約定・率"], [[PERIOD_NAMES[r["期間"]], r["雲方向"], f"{r['候補数']}/{r['約定候補数']}", f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["H1の雲位置区分"]])
    text += "## 診断だけの転換/基準方向と参照時計\n\nT/J同方向・等号・逆方向の成績を採否へ戻さない。雲内/逆雲外を反転注文にも変えない。参照秒差0と同じ公開keyは区別する。H0の時計表は上位参照が存在した登録だけが分母。\n"
    text += G.table(["入口/期間", "実sideに対するT/J", "要求/仮約定", "250/全仮約定・率"], [[r["入口"]+"/"+PERIOD_NAMES[r["期間"]], r["TJ方向"], f"{r['候補数']}/{r['約定候補数']}", f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["TJ診断"]])
    text += G.table(["入口/期間", "上位参照あり", "終了差秒中央値", "要求−公開秒中央値", "公開同key", "準備済み雲幅0"], [[r["入口"]+"/"+PERIOD_NAMES[r["期間"]], r["上位参照のある純入口数"], number(r["下位終了引く上位終了秒"]["中央値"]), number(r["要求引く上位公開秒"]["中央値"]), r["公開同key数"], r["雲幅0数"]] for r in data["上位参照の時計診断"]])
    text += "## 共通出口と一建玉の実参加差\n\n厳密共通は場/実side/実役割/新規key/価格/入口ATR/D。純入口は部分集合でも、先行建玉やpendingが減ると右だけの実参加が生じ得る。共通0の出口差0は比較対象なし。総額差を一取引平均の改善や共通回収改善と読み替えない。\n"
    text += "今回の右だけの実参加は全比較/全期間で計"+str(sum(r["右のみ"]["完結取引数"] for r in data["実参加比較"]))+"件。一般に生じ得る占有変化と、今回観測した集合を区別する。\n"
    text += G.table(["比較/期間", "同元T1両参加/厳密共通", "共通出口属性差", "共通出口差0/5/10円", "左のみ完結・0/5/10円", "右のみ完結・0/5/10円", "全差0/5/10円"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['同元T1両実参加数']}/{r['厳密共通実新規数']}", r["共通出口属性差数"], "/".join(number(v["共通出口差円"]) for v in r["費用別"]), *[str(r[k]["完結取引数"])+"・"+"/".join(number(r[k][f"追加{f}pt純損益円"]) for f in (0, 5, 10)) for k in ("左のみ", "右のみ")], "/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較/期間", "左のみの相手取扱", "右のみの相手取扱"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], G.describe(r["左のみの相手取扱"]), G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text += "## 仮250と実回収・利益保護\n\n仮250、仮判定前返済、実保有MFE250を分ける。名目床は費用後同値や実約定同値を保証しない。\n"
    text += G.table(["運用", "期間", "実完結", "対応仮250/判定前返済", "実MFE250", "起動/基準赤字", "同値費用/不利/正益費用負け"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], f"{r['対応仮250数']}/{r['仮250判定前返済数']}", r["実保有MFE250数"], f"{r['起動数']}/{r['起動後基準赤字数']}", f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}/{r['正名目利益の基準費用負け数']}"] for r in data["候補別回収"]])
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
    """全証明を結合し、保存値だけから正式二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場/先着/運用/監査を起動しない。
    """
    config, report, rules, entries, values, manifest = validate(study)
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    catalog, common = V2.load_catalog(), settings(rules)
    intro = "固定37T1の順行入口をH0全保持→H1上位15分準備だけ→H2上位現在雲外実方向へ順に選別する。三入口・三XF運用、カタログ版2・52手法×9尺度。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3、現在方針費用資格は{report['現方針費用資格数']}/3、採用資格は{report['採用資格数']}/3。**\n\n"
    for policy in POLICIES:
        conclusion += policy+"XF："+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(entries["3分_"+policy][p]["確認率"])+"・追加5pt平均"+number(values["3分_"+policy+"_XF"][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    diagnostic = G.read_json(proof_path(study, work, "対応診断.json"))
    conclusion += "H1→H2の雲方向選別では、"+"、".join(PERIOD_NAMES[p]+"の追加5pt総額差は"+number(next(r for r in diagnostic["実参加比較"] if r["比較"] == "雲方向追加" and r["期間"] == p)["費用別"][1]["総差円_右引く左"])+"円だが、一取引平均は"+number(values[CANDIDATES[1]][p]["運用"]["追加5pt平均円"])+"→"+number(values[CANDIDATES[2]][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。総額と平均を分けて評価する。\n\n"
    recovered = next(r for r in diagnostic["候補別回収"] if r["候補ID"] == CANDIDATES[2] and r["期間"] == "条件選択")
    conclusion += f"H2XFの条件選択は実参加対応の仮250先着{recovered['対応仮250数']}件中{recovered['仮250判定前返済数']}件が仮判定前返済、実保有MFE250は{recovered['実保有MFE250数']}件。入口先着と利益保護後の回収を別に見る。\n\n"
    warnings = [r["候補ID"]+"/"+PERIOD_NAMES[p]+"="+str(r[p]["運用"]["品質注意場数"])+"場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    conclusion += ("品質注意は"+"、".join(warnings)+"。該当期の円/差額は観測値で、全体確定額nullを観測額で置換しない。\n\n") if warnings else "全案各期の品質注意は0。将来の実約定や経路品質を保証する意味ではない。\n\n"
    logic = "## 同時点の三段階と役割\n\nH0は固定37T1の競合後純13列を全保持する。元Pは旧3分前20高安の新極値＋旧BB20strict内終値、元sは新安値買P+1/新高値売P−1。T1は元s(C−K)<0と実向きMACDヒスト差(−元s)δH>0で実side=−元s、元Pのk/数量Mを保持する。旧P/MACD/数量Mを38で再計算せず、固定37成功証明へ責任を分ける。\n\n"
    logic += "H1はH0に当場最新公開15分の現在雲上下端・転換9・基準26の有限性だけを追加する。上位数値は固定28の9/26/52・現在雲A(u−26)/B(u−26)、最短78数値足。H2はH1かつ実買なら上位15分C>雲上端、実売ならC<雲下端strict。同値・雲内・逆雲外は不採用。判断に使うのは上位終値で、3分終値や元Pの反転sideへ置き換えない。\n\n"
    logic += "T/J整列、雲色/厚さ/傾き、Fast/ATR上位準備、ADX、量の追加値条件は採用gateにしない。T/J方向は診断だけ。価格派生情報の重なりを独立した票数と数えず、雲不一致を反転注文へ変えない。S/Rの追加は未実行。\n\n"
    clocks = "## 公開時点・共有責任と旧試行との差\n\n上位は当場publish15のうちend15<=end3かつ公開key15<=元T1要求key3を同時に満たす最新。両時点の等号は可。最新参照が不良/未準備でも古正常へfallbackしない。当場未公開時に前場の公開足を局所参照へ持ち越さない。一方で数値銀行には固定28の限月/欠枠/NP規約を持つ履歴carryがあり、当場公開参照と区別する。幅0の雲は数値準備可で、上位C等号は雲外にならない。\n\n"
    clocks += "固定29保存3分は元index/end/key、固定28保存15分は数値/出典、固定37T1は元P/勢い/数量M/実sideを共有する。主は新指標を作らず、新独立状態は原8列から上位15分を別再構成し、asof/採否/出典/純射影を照合する。旧28の3分基準線cross＋Fast/上位T/J選別の全戦略を移植したものではない。\n\n"
    clocks += "三案は元要求時計を変えず、保持入口の純13列と11labelは同値。正式先着は+1秒以降の正常BBOから直接検算し旧37同時計の125/250と一致を確認する。新しい待機・後足発動・指値・反対売買はなく、間引きは元要求。未来labelはlive純13列へ渡さない。H0は識別子だけ旧T1へ正規化し、全66場の全ledger/trace属性を対照する。\n\n"
    protection = "## 共通執行・利益保護・費用\n\nmicro1枚代理・倍率10円/pt・呼値5pt・片道fee11円。市場要求+1価格秒以降、有効30秒以内の最初正常BBO（買ask/売bid）で新規。一pending/一建玉、後続抑止を空き時計へ延期しない。返済要求+1秒、hard125/TP250/期限の優先を維持。ラージBBOの価格時計は受信時計ではなく、実microのキュー・数量・部分約定を保証しない。\n\n"
    protection += "XFは現在正常返済BBOの実side×(mark−entry)×10−122>0strictで一度起動する。往復fee22＋参照片道5pt往復100、名目境界12.2pt超で、過去MFEだけでは起動しない。以後D=max(5,ceil(入口ATR/5)*5)、max(0,MFE−D)、買ceil/売floor・最低名目entry床・非緩和、返済pending凍結。最低床は費用後同値や遅延後の同値約定を保証しない。\n\n"
    protection += "追加0/5/10ptは同約定への費用負荷で、起動参照滑り5ptを感度別に変更しない。デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板300秒超空白等・未解消/EOFは品質へ残し、注意期の観測円を全体確定額にしない。\n\n"
    limits = "## 知見の限界と再利用\n\nH0→H1の準備差、H1→H2の値選別、純入口と実占有、仮先着と実回収を混ぜない。同実side/役割/key/価格/ATR/Dの共通出口差＋右のみ額−左のみ額で全費用差を分ける。全体損失が減っても取引平均や共通回収が改善したとは限らない。\n\n全66場既使用で、少数の高率・計算一致・旧対照同値は未使用確認や将来利益の証明ではない。T/J/参照時計/回収の事後群を新採否へ戻さず、主要条件を変える場合は新試行で固定する。\n\n"
    table, (audit_text, audit_paths) = result_tables(report, entries, values), audits(study, work, readme)
    header_links = " / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json", "上位参照.json"))
    summary = "# 試行00038：外側継続と上位の現在雲\n\n"+intro+header_links+" / "+G.link(mapping, readme)+"\n\n"+conclusion+table+diagnosis(study, work, readme)+logic+clocks+protection+limits+audit_text
    mapped = "# 試行00038：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER, mapping, "コピー元汎用表・版2")+" / "+G.link(readme, mapping)+"\n\n"
    mapped += "## 手法×時間スケール\n\n52手法×9尺度。R0=H0XF全保持/R1=H1XF上位準備/R2=H2XF雲外方向。I11のS07はH1/H2準備、S08はH2値、S09は共通参照、S13は診断のみ。Fastや旧28の3分基準線crossを今回採用扱いにしない。未使用・未検証・データ不足・対象外を区別する。\n\n"+V2.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 三評価の定義\n"+G.table(["評価", "候補", "役割", "入口支持", "70目標", "費用資格", "採用資格"], [[r["評価ID"], r["候補ID"], "順行", "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達", "充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped += table+logic+clocks+protection+limits+audits(study, work, mapping)[0]

    # ----------------------------------------
    # 共有資料は参照し、新しい大明細と旧計算の全件転記を避ける。
    names = ("入力台帳.json", "入口参照.json", "対照参照.json", "上位参照.json", "準備参照.json", "H0対照同値.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "作業成果物.json")
    sources = [HERE/n for n in ("README.md", "入口.py", "運用.py", "検証.py", "合成検証.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py", "レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/一目均衡表.md", "docs/technical-analysis/指標/MACD.md", "docs/technical-analysis/指標/OBV.md", "docs/議論/高安帰還と外側継続の同時点判別.md", "docs/README.md", "docs/議論/README.md", "docs/議論/PDCAの進行.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md", "study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing = "## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n, readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p, readme) for p in sources)+"。\n\n"
    viewing += "入口参照は旧37四明細、対照参照は旧37ledger/trace、上位参照は旧28全指標一明細。旧29下位3分は旧37入口参照から共有する。新大明細は上位判定/純13列＋元P・元side・旧T1 ID＋11labelのcase/全運用詳細/追尾の4gzipだけで、旧CCI/context/数量/全指標を複製しない。Viewerは三運用各66場・198資源と3代表。\n\n--prepareは純三入口/全15分限定射影/全asof採否だけで新先着・運用・損益を計算しない。正式は既存結果/部分gzipを上書きしない。再現はコードREADME、保存値だけの再表示は次のとおり。\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/上位雲継続/レポート.py\n```\n\n"
    if COMMON.is_file():
        viewing += G.link(COMMON, readme, "共通知見")+"。\n\n"
    display_sources = [ROOT/"scripts"/name/"レポート.py" for name in ("構造判別", "量比反転", "回復監視", "突破指値", "終値位置", "CCI突破", "一目基準線", "反転確認時計", "SAR持続", "終値切替")]
    paths = [Path(__file__), *display_sources, ROOT/"scripts/レポート/設定結果レポート.py", ROOT/"scripts/レポート/カタログ版2.py", V2.BASE, V2.CATALOG, V2.MASTER, manifest,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *names) if (study/n).is_file()],
        *[s/n for s in (ENTRY_STUDY, UPPER_STUDY, EXIT_STUDY) for n in ("条件.json", "固定.json", "結果.json")], *sources, *docs, *audit_paths]
    for path in (work/"診断予定.json", ROOT/"work/上位方向38の記録案.md", ROOT/"work/上位方向38の事前案.md", ROOT/"work/上位方向38の独立案.md"):
        if path.is_file():
            paths.append(path)
    for path, body in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """全proof完成後の保存二MDだけをCLIで再表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。実市場や監査を呼び出さない。
    """
    parser = argparse.ArgumentParser(description="上位の準備と現在雲方向・保存帳票版2")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
