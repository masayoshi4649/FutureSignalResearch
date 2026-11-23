"""旧反転の費用起動・数量準備・量比値を、保存値だけから分けて表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00036_価格失敗と量比の方向変化"
WORK = ROOT/"work/量比反転/00036"
ENTRY_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/価格失敗へ量比の方向変化を加えた比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
PAIRS = (("V0", "X0"), ("V0", "XF"), ("V1", "XF"), ("V2", "XF"))
CANDIDATES = tuple("3分_"+p+"_"+x for p, x in PAIRS)

spec = importlib.util.spec_from_file_location("量比36の固定35表示補助", ROOT/"scripts/回復監視/レポート.py")
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
G, P, V2, number = F.G, F.P, F.V2, F.number


def definitions(config: dict) -> list[dict]:
    """三入口を旧X0参考と現在XF三案の四評価へ対応させる。

    引数: config(dict)は36条件。
    返り値: list[dict]はR0/R1/R2/R3。全反転、順序を結果で選ばない。
    """
    if config["戦略"] != ["V0", "V1", "V2"] or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略": p, "出口ID": x} for p, x in PAIRS]:
        raise ValueError("三入口/四運用の固定組合せ以外")
    return [{"評価ID": "R"+str(i), "候補ID": cid,
        "入口": {"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p, "役割": "反転", "複合本命": True},
        "出口": {"出口ID": x}} for i, ((p, x), cid) in enumerate(zip(PAIRS, CANDIDATES))]


def validate(study: Path) -> tuple:
    """正式の三入口・四運用・旧対照・支持/費用と全固定を確認する。

    引数: study(Path)は正式先。
    返り値: tupleは条件/結果/四評価/入口/運用/解決台帳。未実行時は表示を拒否する。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json", "V0対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を生成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    if config["カタログ版"] != 2 or config["VR期間"] != 20 or report["全66場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("版2/事前20/既使用/同先着の差")
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 3 or len(values) != 4 or report["入口評価数"] != 3 or report["運用候補数"] != 4 or report["現方針運用候補数"] != 3 or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("三入口/四運用/現在三候補の集合差")
    previous = G.read_json(ENTRY_STUDY/"結果.json")
    old_entry = next(r for r in previous["入口評価"] if r["入口ID"] == "3分_R0")
    old_op = next(r for r in previous["結果"] if r["候補ID"] == "3分_R0_X0")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("入口/役割/出口の定義差")
        current = rule["出口"]["出口ID"] == "XF"
        for period, count in zip(PERIODS, (40, 24, 2)):
            item, op = entry[period], row[period]["運用"]
            P.validate_entry(item)
            n = op["完結取引数"]
            if row[period]["入口"] != item or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count or op["買い取引数"]+op["売り取引数"] != n or op["役割別完結数"].get("反転", 0) != n:
                raise ValueError("期間/方向/役割/活動の分母差")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("起動/赤字の件数差")
            for fee in (0, 5, 10):
                net, mean = op[f"追加{fee}pt純損益円"], op[f"追加{fee}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*fee*n, abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean, net/n, abs_tol=1e-8):
                    raise ValueError("費用感度/平均差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意期の確定nullを保持する")
            if rule["入口"]["戦略"] == "V0" and item != old_entry[period]:
                raise ValueError("旧29R0とV0の入口数値差")
            if rule["候補ID"] == CANDIDATES[0] and any(op.get(k) != v for k, v in old_op[period]["運用"].items()):
                raise ValueError("旧29X0参考の保存運用値差")
        supported = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = supported and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        fee_ok = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["入口支持"], row["70目標"], row["費用資格"], row["現方針候補"], row["採用資格"]) != (supported, bool(goal), supported, bool(goal), fee_ok, current, current and bool(goal) and fee_ok):
            raise ValueError("入口支持/70/費用/現在/採用の判定差")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()) or report["現方針費用資格数"] != sum(r["費用資格"] and r["現方針候補"] for r in values.values()) or report["採用資格数"] != sum(r["採用資格"] for r in values.values()):
        raise ValueError("合計資格の差")
    names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json", "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    reference = F.F.validate_reference(study/"入口参照.json", ENTRY_STUDY, names)
    control_ref = F.F.validate_reference(study/"対照参照.json", ENTRY_STUDY, names)
    if reference["参照試行"] != "00029" or len(reference["共有明細"]) != 6 or control_ref["参照試行"] != "00029" or len(control_ref["共有明細"]) != 2:
        raise ValueError("旧29六明細/対照二明細の参照差")
    control = G.read_json(study/"V0対照同値.json")
    if control["全件一致"] is not True or control["旧先着全件同値"] is not True or control["場候補数"] != 66 or len(control["照合"]) != 66 or not all(r["全運用同値"] and r["全追尾同値"] for r in control["照合"]):
        raise ValueError("旧V0X0全属性対照未完")
    for name in ("入口参照.json", "対照参照.json"):
        if control[name[:-5]+"SHA256"] != G.sha(study/name):
            raise ValueError("旧対照参照の版差")
    pointer = G.read_json(study/"入力台帳.json")
    manifest = (study/pointer["参照"]).resolve()
    if pointer["SHA256"] != G.sha(manifest) or manifest != ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json":
        raise ValueError("固定66場台帳差")
    if config["入口条件参照"]["SHA256"] != G.sha(ENTRY_STUDY/"条件.json") or config["運用条件参照"]["SHA256"] != G.sha(EXIT_STUDY/"条件.json"):
        raise ValueError("旧入口/現在費用起動の版差")
    if any(G.sha(ROOT/n) != h for n, h in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定出典の現在版差")
    return config, report, rules, entries, values, manifest


def settings(rules: list[dict]) -> list[dict]:
    """旧数量M、新準備と値、旧参考と現在保護を別の使用セルへ写す。

    引数: rules(list[dict])は四評価。
    返り値: list[dict]は14設定。VR以外の未使用セルを残す。
    """
    groups = [
        (["P01", "P02", "I05"], ["m03"], rules, "共通登録：旧29極値更新＋旧BBstrict内", "現在L/Hが直前20の極値をstrict更新し旧20終値BB20・2σ内。現在足除外、ヒゲBB外/前C帯外を追加しない"),
        (["I03"], ["m03"], rules, "共通登録：中心化MACD12/26/9のδH実方向正", "reset初有効Cを原点としてC−oへ算術seedEMA。現前ヒスト差のside正、同限月carry。待機して再確認しない"),
        (["V01", "V02"], ["m03"], rules, "旧M継承：完全非負q・t/k同OBV区間だけ", "kは前20極値の最新同値足。旧29R0自体の観測量準備を保持し、OBV比較差の値方向やRVOL/正平均は採用しない。量なし基準とは呼ばない"),
        (["V01", "V04"], ["m03"], rules[2:], "観測量：VR2中心化B20=(U−D)/(U+D+F)", "終値上昇/下落/同値に当足観測差分qを分類。q=Fraction(float(q))、同値量はF。真の全量/積極売買/人数ではない"),
        (["V04"], ["m03"], rules[2:], "V1/V2共通準備：当場22C/21q・現前T正", "現20変化t−19..t/前t−20..t−1。最古closeのq不要、量不完全でも有効closeを比較元へ保持。完全0可/全0比無効、欠測を0補完しない"),
        (["V04"], ["m03"], rules[3:], "V2：side×(B現−B前)>0strict", "分数差分子で採否、表示float/εを使わず等号0不成立。B優勢/過熱やOBV値を重ねない。古い量の窓落ちでも変化する"),
        (["I09"], ["m03"], rules, "共通：入口ATR14正・全出口でD固定", "旧29現ATRを保持しD=max(5,ceil(ATR/5)*5)。価格/ATRと数量窓の解除を混ぜない"),
        (["C07"], ["m03"], rules, "共通：旧P公開key・時間/遅延/競合不変", "旧Pは全保存、採否は旧R0へ準備/値を追加するだけ。原公開時計で分割/30分間引き、後足/回復/指値待機なし"),
        (["B01"], ["tick"], rules, "共通取得：市場要求+1秒/有効30秒・一建玉", "買ask/売bid新規、正常BBO/旧単一pending保有制約。純subsetでも空き方が変わり実追加参加が生じ得る"),
        (["I09", "C06", "E02"], ["tick"], rules[:1], "X0参考：旧A5・名目5pt起動", "V0_X0は旧29R0_X0の識別子を除く全属性対照。現在方針候補外、利益保護の旧参考として残す"),
        (["I09", "C06", "E02"], ["tick"], rules[1:], "XF：現在返済BBO利益円−122>0strict起動", "往復fee22＋参照片道5pt往復100。過去MFEだけで起動せず、以後登録D/MFE−D・最低名目entry床・非緩和。pending中更新停止"),
        (["E01"], ["tick"], rules, "共通先着：旧R0同時計/同価格の11列共有", "純三入口の共通イベントは同じ仮約定/125250/判定key。期限/不足を分母に残し未約定別記。仮先着と実回収を分ける"),
        (["V04", "V02"], ["m03"], rules, "診断のみ：準備/値群・当足と窓落ち・20/21量", "V0→V1準備とV1→V2値を分離。当足/脱落分類とq0、現20正同量/両窓21正同量の機序を区分し、結果後の群を採否へ戻さない"),
        (["E01", "P05", "B01"], ["tick"], rules, "診断のみ：厳密同約定出口と実参加/全費用", "場/side/実新規key/価格/ATR/Dだけを共通出口へ。同元登録/片側追加を別記し、0/5/10全額差と回収を分解する"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式/作業証明の同一性を確認して既存証明を解決する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは証明先。正式コピーと正本の差は拒否する。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """非PnL準備・直接先着・会計・利益保護・保存診断を区別する。

    引数: study/work/output(Path)は保存先と表示先。
    返り値: tupleは検査表/出典一覧。検算数を独立の収益標本にしない。
    """
    rows, paths = [], []
    groups = (("合成検証.json", "人工窓/0量/鏡像/現在費用起動"), ("独立監査.json", "共有先着集計/Decimal会計/全資源"),
        ("状態独立確認.json", "量比/全採否/純同時点/旧X0対照"), ("追尾独立確認.json", "X0/XF全保有・起動と最初要求"),
        ("対応診断.json", "準備/値/費用起動の三比較と実参加"), ("Viewer照合.json", "四運用の代表Viewer"))
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data["全件成功"] is True and data["合成編集終了"] is True, data["検証件数"]
            if any(G.sha(ROOT/n) != h for n, h in data["ファイルSHA256"].items()):
                raise ValueError("最終人工の現在主版差")
            for key, file in (("独立数値補助SHA256", "状態独立確認.py"), ("独立追尾補助SHA256", "追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):
                    raise ValueError("最終人工の独立版差")
        elif name == "Viewer照合.json":
            verdict, count = len(data.get("照合", [])) == 4 and all(r["一致"] for r in data["照合"]), len(data.get("照合", []))
        if verdict is not True:
            raise ValueError("検査未完:"+name)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("検査結果の版差")
        if name == "対応診断.json" and data["参照SHA256"]["結果.json"] != G.sha(study/"結果.json"):
            raise ValueError("診断対象の結果版差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("会計の独立監査接続未完")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    main, independent_path = work/"準備点検.json", proof_path(study, work, "独立準備点検.json")
    independent, lock, ref = G.read_json(independent_path), G.read_json(study/"固定.json"), G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(independent_path):
        raise ValueError("主/独立準備の版差")
    if independent["ラベル計算"] is not False or independent["損益計算"] is not False or ref.get("先着計算", ref.get("ラベル計算")) is not False or ref["損益計算"] is not False:
        raise ValueError("準備の非ラベル/非PnL規約差")
    for name, path in (("主準備", main), ("独立準備", independent_path)):
        if ref["参照"][name]["SHA256"] != G.sha(path):
            raise ValueError("軽量準備参照の版差")
    for item in ref["参照"].values():
        path = ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("準備参照内容差")
        paths.append(path)
    paths += [main, independent_path]
    rows += [["固定前主準備・純三入口/量比/採否", "66場・非損益", 66, G.link(main, output)], ["固定前独立数量窓/採否/入口", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
    for name in ("保存物読取補足.json", "会計人工接続.json", "新規会計人工接続.json"):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path = proof_path(study, work, name)
        data = G.read_json(path)
        if data["全件一致"] is not True or data["不一致数"] != 0:
            raise ValueError("後段小証明未完")
        if name == "保存物読取補足.json" and data["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
            raise ValueError("補足の診断版差")
        if name.endswith("会計人工接続.json") and any(G.sha(ROOT/n) != h for n, h in data["コードSHA256"].items()):
            raise ValueError("会計人工の現在版差")
        rows.append([name, "一致/合格", number(data["照合項目数"]), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n非損益準備は旧R0純13列・量比・採否を対象とし、新先着/運用/損益を計算しない。価格/公開key/量比分数/全採否/D整数は厳密、ATR・中心化MACD等の独立表現許容は正式計画の範囲だけで、採否のεには使わない。保存先着の射影同値と、実保有/会計の検査を分ける。検算数は収益標本数ではない。\n"
    return text+G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def result_tables(entries: dict, values: dict) -> str:
    """三入口の先着/間引きと四運用の損益/支持を別表へ表示する。

    引数: entries/values(dict)は正式保存結果。
    返り値: strは小型Markdown表。旧参考と現在三候補の分母を区別する。
    """
    erows, orows, supports = [], [], []
    for policy in ("V0", "V1", "V2"):
        source = entries["3分_"+policy]
        for p in PERIODS:
            e = source[p]
            erows.append([policy, PERIOD_NAMES[p], e["候補数"], e["約定候補数"], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}", f"{e['逆行先着']}/{e['期限未達']}/{e['観測不足']}/{e['未約定']}", f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}"])
    for cid in CANDIDATES:
        row = values[cid]
        for p in PERIODS:
            op, e = row[p]["運用"], row[p]["入口"]
            orows.append([cid, "現在" if row["現方針候補"] else "旧参考", PERIOD_NAMES[p], op["完結取引数"], *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"], number(op["追加0pt確定対象円"])])
            if p in PERIODS[:2]:
                supports.append([cid, PERIOD_NAMES[p], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if row["入口支持"] else "未達", "達成" if row["70目標"] else "未達", "充足" if row["費用資格"] else "未達", "現在" if row["現方針候補"] else "対象外", "充足" if row["採用資格"] else "未達"])
    text = "## 三入口と四運用の結果\n\n先着主率は期限/観測不足を含む全仮約定が分母、未約定は別記する。実完結の費用後売買勝率と別。V0X0/V0XFは同じ入口評価を共有し、入口を二重に数えない。30分間引きは原Pの要求時計を使う。\n"
    text += G.table(["入口", "期間", "純要求", "仮約定", "250/全仮約定・率", "125/期限/不足/未約定", "30分間引き250/仮約定・率"], erows)
    text += G.table(["運用", "位置づけ", "期間", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場", "基準確定円"], orows)
    text += "入口支持は学習60仮約定/6日/10場・選択20/3/5、70目標は両期主率と間引き率70%・間引き件数20/10。費用資格は学習20完結/6日/10場/買売各5、選択10/3/6/各3、品質注意0・両期追加5pt後黒字。現在採用には入口70と費用資格の双方を要する。旧X0は費用資格を表示しても現在候補へ昇格しない。\n"
    return text+G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "入口支持", "70目標", "費用資格", "現方針", "採用資格"], supports)


def entry_groups(rows: list[dict], key: str) -> str:
    """準備二群又は値三群の分母と各先着を表示する。

    引数: rows(list[dict])は保存診断、key(str)は群列名。
    返り値: strはMarkdown表。
    """
    return G.table(["期間", "分母", "区分", "要求/仮約定", "250/全仮約定・率", "125/期限/不足/未約定"], [[PERIOD_NAMES[r["期間"]], r["分母"], "準備済み" if r[key] is True else "未準備" if r[key] is False else r[key], f"{r['候補数']}/{r['約定候補数']}", f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}", f"{r['逆行先着']}/{r['期限未達']}/{r['観測不足']}/{r['未約定']}"] for r in rows])


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """三段の比較鎖を、保存診断だけから表示する。

    引数: study/work/output(Path)は保存先/表示先。
    返り値: strは準備/値/実参加/回収。群の成績を新採否へ戻さない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    text = "## 価格P・旧R0・新準備・値の段階\n\n"+G.link(path, output)+"を正本とする。原Pと旧R0純入口は別分母で、旧R0には数量準備が既にある。新未準備を値0/負へ混ぜず、重複理由は合算して総除外数にしない。\n"
    text += G.table(["期間", "全P/B準備P", "V0/V1/V2", "V0のB未準備/正0負", "V0不採用理由・重複"], [[PERIOD_NAMES[r["期間"]], f"{r['原P数']}/{r['原P量比準備数']}", f"{r['V0純入口数']}/{r['V1純入口数']}/{r['V2純入口数']}", G.describe(r["V0内量比区分"]), G.describe(r["V0不採用理由別_重複"])] for r in data["原発動と三入口"]])
    text += G.table(["期間", "全量比足", "準備区分・相互排他", "完全0量足", "解除理由・重複"], [[PERIOD_NAMES[r["期間"]], r["全足数"], G.describe(r["準備区分_相互排他"]), r["完全0量足数"], G.describe(r["解除理由別_重複"])] for r in data["量比全足品質"]])
    text += "## 準備による選別と、値による選別\n\n最初の二群はV0純入口、次の三群はV1純入口が分母。同時点の採用構成差で、数量改善を待って取得を遅らせた効果ではない。除外群の仮250は取り逃した機会、仮125は同方向入口の回避で、逆売買収益や回収可能円ではない。\n"
    text += entry_groups(data["V0の量比準備二群"], "B現前準備")+entry_groups(data["V1の量比差三群"], "実方向B差区分")
    text += G.table(["比較/期間", "保持要求/仮250/仮約定", "除外要求/仮250/仮約定", "純追加入口"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['保持入口']['候補数']}/{r['保持入口']['順行先着']}/{r['保持入口']['約定候補数']}", f"{r['除外入口']['候補数']}/{r['除外入口']['順行先着']}/{r['除外入口']['約定候補数']}", r["新規追加入口数"]] for r in data["入口追加比較"]])
    text += "## 当足と窓落ち・方向回数へ退化する群\n\n保存panelの分類方向/qと現前窓番号だけを対応した記述診断。各セルは区分ごとの要求数・250/全仮約定（率）。V1/V2の当時純入口が分母で、同じ群の同時計先着を使う。分類実方向0は同値終値、q0は量0であり別の軸。複数軸は重なり、表の合計を追加の除外数にしない。\n"
    def mechanism_cell(policy: str, period: str, axis: str) -> str:
        """機序別の保存小集計だけを一セルへまとめる。

        引数: policy/period/axis(str)は入口/期間/診断軸。
        返り値: strは区分/件数/先着。値や採否を再計算しない。
        """
        own = [r for r in data["当足と窓落ちの機序"] if r["入口"] == policy and r["期間"] == period and r["区分軸"] == axis]
        return "<br>".join(("該当" if r["当時区分"] is True else "非該当" if r["当時区分"] is False else r["当時区分"])+f"：{r['候補数']}件・{r['順行先着']}/{r['約定候補数']}（{G.pct(r['確認率'])}）" for r in own)
    text += G.table(["入口", "期間", "当足分類の実方向", "窓落ち分類の実方向"], [[policy, PERIOD_NAMES[p], mechanism_cell(policy, p, "当足分類の実方向"), mechanism_cell(policy, p, "窓落ち分類の実方向")] for policy in ("V1", "V2") for p in PERIODS])
    text += "現20量が同じ正量なら現在Bは方向回数比になる。両窓とも数量の大小に依らない方向回数式になることを保証する十分条件は、脱落足を含む和集合21量が同じ正量であること。これは必要条件ではなく、方向が全て同じ等なら不均一量でも偶然一致し得る。20同量を21同量の証拠にしない。以下は採否へ使わず、数量大小の情報と窓移動の説明を混同しないための区分。\n"
    text += G.table(["入口", "期間", "当足q0", "窓落ちq0", "現20が同じ正量", "両窓21が同じ正量"], [[policy, PERIOD_NAMES[p], *[mechanism_cell(policy, p, axis) for axis in ("当足q0", "窓落ちq0", "現20が同じ正量", "両窓21が同じ正量")]] for policy in ("V1", "V2") for p in PERIODS])
    text += "## 実参加と厳密共通出口\n\n厳密共通は場/side/実新規key/価格/入口ATR/Dが同じ取引。旧参考→V0XFでは出口差を観測し、準備/値追加は同じXFの共通出口が同値かを確認する。厳密共通0なら出口差0は比較対象なしで、出口効果0の証明ではない。純subsetでも実際の空き時刻が変わるため、右だけの実新規はあり得る。\n"
    text += G.table(["比較/期間", "両実参加元登録/同約定ATR", "左だけ/右だけ元登録", "新価格差中央値pt", "新規時計差中央値秒"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['両実参加元登録数']}/{r['同約定ATR数']}", f"{r['左のみ元登録数']}/{r['右のみ元登録数']}", number(r["新規価格差pt_右引く左"]["中央値"]), number(r["新規時計差秒_右引く左"]["中央値"])] for r in data["同元登録の実参加対応"]])
    text += G.table(["比較/期間", "厳密共通/出口属性差数", "共通出口差0/5/10円", "左のみ完結・0/5/10円", "右のみ完結・0/5/10円", "総差0/5/10円"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['同約定ATR共通実新規数']}/{r['共通出口属性差数']}", "/".join(number(v["同約定ATR共通出口差円"]) for v in r["費用別"]), str(r["左のみ"]["完結取引数"])+"・"+"/".join(number(r["左のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), str(r["右のみ"]["完結取引数"])+"・"+"/".join(number(r["右のみ"][f"追加{f}pt純損益円"]) for f in (0, 5, 10)), "/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較/期間", "左のみの相手取扱", "右のみの相手取扱"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], G.describe(r["左のみの相手取扱"]), G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text += "## 仮先着と実回収・利益保護\n\n仮250は実返済後も観測する反事実で、実保有MFE250も回収済み利益へ変換しない。起動後の名目同値費用赤字、不利返済、正の名目利益でも費用負けとなる群を分ける。\n"
    text += G.table(["運用", "期間", "実完結", "仮250/判定前返済", "実MFE250", "起動/基準赤字", "同値費用/不利/正益費用負け", "起動後正益の追加5費用負け"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["完結取引数"], f"{r['対応仮250数']}/{r['仮250判定前返済数']}", r["実保有MFE250数"], f"{r['起動数']}/{r['起動後基準赤字数']}", f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}/{r['正名目利益の基準費用負け数']}", r["起動後正名目利益の追加5費用負け数"]] for r in data["候補別回収"]])
    text += "以下の実同値未満/最終線不足は追尾起動後の取引に限る。設定された名目床と、遅延後の実返済を分ける。\n"
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
    """全正式証明が揃った保存値だけからREADMEと設定表を生成する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]は二MD。旧生成処理/globalを変更しない。
    """
    config, report, rules, entries, values, manifest = validate(study)
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output/"README.md", output/"設定と結果.md"
    catalog, common = V2.load_catalog(), settings(rules)
    intro = "NK225・旧29の価格失敗P＋中心化MACD差による反転を、V0旧R0、V1量比現前準備、V2実方向B差の順で比較する。三入口、旧V0X0参考と現在V0/V1/V2XFの四運用。カタログ版2・52手法×9尺度。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は旧参考を含む{report['費用資格数']}/4、現在方針の費用資格は{report['現方針費用資格数']}/3、採用資格は{report['採用資格数']}/3。**\n\n"
    for name, left, right in (("費用起動変更", CANDIDATES[0], CANDIDATES[1]), ("量比準備追加", CANDIDATES[1], CANDIDATES[2]), ("量比値追加", CANDIDATES[2], CANDIDATES[3])):
        conclusion += name+"："+"、".join(PERIOD_NAMES[p]+"の追加5pt平均"+number(values[left][p]["運用"]["追加5pt平均円"])+"→"+number(values[right][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    warnings = [r["候補ID"]+"/"+PERIOD_NAMES[p]+"="+str(r[p]["運用"]["品質注意場数"])+"場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "品質注意は"+"、".join(warnings)+"。該当期の総額/平均/差額は観測値で、全体確定額nullを観測額で置き換えない。\n\n"
    logic = "## 価格失敗・勢い・数量の役割\n\n価格Pは買い現在L<前20最安Lかつ旧20終値BB20・2σ内のstrict終値、売りは高値更新の鏡像。ヒゲBB外や前C帯外を追加しない。MACDはreset初C原点のC−oへ12/26/9の算術seedEMA、隣接ヒスト差の実方向正を要求する。価格/ATR/MACDは固定29規約をread再用する。\n\n"
    logic += "V0は旧R0の数量準備も含む。完全非負当足qとt/k同OBV区間（kは前20極値の最新同値足）を保ち、OBV比較差の値は使わない。V0を量なし基準とせず、V0→V1で固定窓の準備、V1→V2で同じ準備のもと値選別を測る。全原Pは旧時点の採否を準備正本から共有し、大きい旧contextを複製しない。\n\n"
    logic += "B20=(U−D)/(U+D+F)は終値上昇/下落/同値へ分類した観測差分量の比。現20変化t−19..tと前t−20..t−1には当場連続22終値/21完全qが必要で、最古終値のqは不要。数量不完全は量窓を切り、有効公開closeは次の比較元へ保持する。完全0量は有効、全0分母は欠測、片側0は±1、同値量だけならB0。価格欠/NP/欠枠/不正と量の解除を分ける。\n\n"
    logic += "V2はside×(B現−B前)>0strictだけを追加し、元qのFractionによる分数差分子を使う。0等号不成立、表示floatや任意εを使わず、B優勢/過熱/MFI/OBV値を重ねない。反射でU/D交換・F不変、BとΔBの符号反転を守る。期間20は旧価格/BB尺度との事前仮説で、期間探索の最良値ではない。\n\n"
    logic += "ΔBは現在量だけでなく古い方向量の窓落ちや分母変化でも動く。方向比改善を当足量増勢、積極買売、新しい参加人数、純資金流入の実測と呼ばない。価格失敗に逆側の量配分変化が伴えば反転候補となるという心理は仮説で、支持維持や将来継続を直接見たものではない。\n\n"
    protection = "## 同時計の取得・費用起動・場内完結\n\nV1/V2は旧Pの同じ公開keyで選別し、次足/指値/35の到達後回復を待たない。純13列と保存label11列は別で、liveへ未来先着や量比パネルを混ぜない。同元イベントの共通仮新規は同時計/同価格/同入口ATR・全先着同値で、保持群の率変化は採用構成の差。30分間引き・期間分割は原要求時計。\n\n"
    protection += "取得は旧市場要求+1価格秒以降・有効30秒内の最初正常BBO、買ask/売bid。実は一注文/一建玉で、後続抑止を空き時刻へ延期しない。旧X0は名目5pt起動、XFは現在正常返済BBOのs×(mark−entry)×10−122>0strict（往復fee22＋想定片道5pt往復100）で一度起動する。名目境界12.2pt超、過去MFEだけでは起動しない。\n\n"
    protection += "起動後は入口D=max(5,ceil(ATR/5)*5)、max(0,MFE−D)、買ceil/売floor、最低名目新規床・非緩和、返済pending中更新停止。hard125/TP250/期限を継承する。最低名目床は費用後同値や遅延後同値約定を保証しない。\n\n"
    protection += "ラージBBOによるmicro1枚代理、倍率10円/pt・呼値5pt・片道11円、返済要求+1秒以降の正常返済BBO。追加0/5/10ptは同約定に対する費用負荷で、起動参照5ptを感度ごとに変えない。デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板300秒超空白等は品質へ残す。\n\n"
    limits = "## 限界と再利用\n\n三比較は旧A5→現在起動、準備追加、値追加の順。同じ純入口でも出口変更で実再参加が変わり、準備/値の純subsetでも実追加参加がある。総損失縮小だけを一取引平均や共通出口の改善へ読み替えず、共通出口差＋右のみ額−左のみ額を全費用で分解する。\n\n"
    limits += "三入口/四運用は同じ原Pに依存し、標本を合算しない。未準備/値不採用を逆向きに売買した成績ではない。既使用の高率小群や計算一致は未使用確認・将来利益の証明ではなく、閾値や主要条件を変えるなら新試行で固定する。数量基準完全は真の全約定量を保証せず、板数量・建玉残高・資金入出金とも違う。価格時計は受信時計ではなく、実キュー/部分約定/実microの成立は別に確認が必要。\n\n"
    table, (audit_text, audit_paths) = result_tables(entries, values), audits(study, work, readme)
    summary = "# 試行00036：価格失敗と量比の方向変化\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json", "入口参照.json", "対照参照.json"))+" / "+G.link(mapping, readme)+"\n\n"+conclusion+table+diagnosis(study, work, readme)+logic+protection+limits+audit_text

    # ----------------------------------------
    # 版2を変更せず、準備と値と旧/現保護を使用セルへ記録する。
    mapped = "# 試行00036：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER, mapping, "コピー元汎用表・版2")+" / "+G.link(readme, mapping)+"\n\n"
    mapped += "## 手法×時間スケール\n\n52手法×9尺度。R0=旧V0X0参考/R1=V0XF/R2=V1XF/R3=V2XF。S03のOBVは旧M準備のみ、S04/S05のVRはV1/V2準備、S06がV2だけの値条件。S10は旧参考、S11は現在XF、S13/S14は診断のみ。未使用・未検証・データ不足・対象外を区別する。\n\n"+V2.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    mapped += "## 四評価の定義\n"+G.table(["評価", "候補", "入口支持", "70目標", "費用資格", "現在方針", "採用資格"], [[r["評価ID"], r["候補ID"], "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達", "現在" if values[r["候補ID"]]["現方針候補"] else "旧参考・対象外", "充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped += table+logic+protection+limits+audits(study, work, mapping)[0]

    # ----------------------------------------
    # 旧全指標は参照し、新量比と最小case/運用/追尾の4gzipだけを新規記録にする。
    names = ("入力台帳.json", "入口参照.json", "対照参照.json", "準備参照.json", "V0対照同値.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入力品質.json", "作業成果物.json")
    sources = [HERE/n for n in ("README.md", "入口.py", "運用.py", "検証.py", "合成検証.py", "新規会計.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py", "レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/ボリュームレシオ.md", "docs/technical-analysis/指標/OBV.md", "docs/technical-analysis/指標/MACD.md", "docs/議論/テクニカル手法の検証範囲と次の複合候補.md") if (ROOT/n).is_file()]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing = "## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n, readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p, readme) for p in sources)+"。\n\n"
    viewing += "入口参照は旧29六明細、対照参照は旧29全ledger/trace二明細と八文書/証明を共有する。新量比は小型全足、caseは純13列＋旧R0 ID/期間/JST＋保存label11列。VR観測はlive/caseへ混ぜず、全P採否は非損益準備正本を読取共有する。旧OHLC/MACD/OBV全contextや原板の複製を避け、新大明細は量比・入口事例・全運用詳細・追尾の4gzip。Viewerは4運用各66場・264資源と4代表。\n\n"
    viewing += "--prepareは純入口/量比/全P採否だけを保存し、新先着・運用・損益を計算しない。旧caseは純信号射影の同値確認に参照する。正式は既存結果/部分gzipを上書きしない。コードREADMEに再現手順、保存値だけの再表示は次のとおり。\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/量比反転/レポート.py\n```\n\n"
    if COMMON.is_file():
        viewing += G.link(COMMON, readme, "共通知見")+"。\n\n"
    display_sources = [ROOT/"scripts"/name/"レポート.py" for name in ("回復監視", "突破指値", "終値位置", "CCI突破", "一目基準線", "反転確認時計", "SAR持続", "終値切替")]
    paths = [Path(__file__), *display_sources, F.F.F.F.F.F.DISPLAY, ROOT/"scripts/レポート/設定結果レポート.py", ROOT/"scripts/レポート/カタログ版2.py", V2.BASE, V2.CATALOG, V2.MASTER, manifest,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *names) if (study/n).is_file()], ENTRY_STUDY/"条件.json", ENTRY_STUDY/"固定.json", ENTRY_STUDY/"結果.json", EXIT_STUDY/"条件.json", *sources, *docs, *audit_paths]
    for path in (work/"診断予定.json", ROOT/"work/数量方向36の記録案.md", ROOT/"work/次反転候補36.md", ROOT/"work/数量方向36の独立案.md"):
        if path.is_file():
            paths.append(path)
    for path, body in ((readme, summary+viewing), (mapping, mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存結果だけの二MD生成をCLIから起動する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。市場/数値/先着/運用/監査は起動しない。
    """
    parser = argparse.ArgumentParser(description="価格失敗と量比の方向変化・保存帳票版2")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
