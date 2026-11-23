"""新終値突破の回帰方向と標本内直線性を、版3の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00041_終値突破と回帰の方向と直線性"
WORK = ROOT/"work/回帰突破/00041"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/終値突破へ回帰方向と直線性を加えた比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("L0", "L1", "L2")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)

spec = importlib.util.spec_from_file_location("回帰41の固定37保存表示", ROOT/"scripts/構造判別/レポート.py")
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
G, P, number = F.G, F.P, F.number
vspec = importlib.util.spec_from_file_location("回帰41の独立版3表", ROOT/"scripts/レポート/カタログ版3.py")
V3 = importlib.util.module_from_spec(vspec)
sys.modules[vspec.name] = V3
vspec.loader.exec_module(V3)


def definitions(config: dict) -> list[dict]:
    """新しい順行基準の三段階を、現在XF三評価へ対応する。

    引数: config(dict)は41条件。
    返り値: list[dict]はR0〜R2。全案が現在方針候補。
    """
    expected = [{"戦略": p, "出口ID": "XF"} for p in POLICIES]
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != expected:
        raise ValueError("3分L0/L1/L2・XF三案以外")
    return [{"評価ID": "R"+str(i), "候補ID": cid,
        "入口": {"入口ID": "3分_"+p, "戦略": p, "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True},
        "出口": {"出口ID": "XF"}} for i, (p, cid) in enumerate(zip(POLICIES, CANDIDATES))]


def validate(study: Path) -> tuple:
    """新三入口/三運用・版3・支持/費用・数値参照と全固定を検査する。

    引数: study(Path)は41正式先。
    返り値: tupleは条件/結果/評価/入口/運用/実台帳。正式結果なしでは拒否する。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "指標参照.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作らない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    if config["カタログ版"] != 3 or report["全66場既使用"] is not True:
        raise ValueError("版3/既使用性の差")
    entries, values = {r["入口ID"]:r for r in report["入口評価"]}, {r["候補ID"]:r for r in report["結果"]}
    if (len(entries),len(values),report["入口評価数"],report["運用候補数"],report["現方針運用候補数"]) != (3,3,3,3,3) or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("新三入口/三運用の分母差")
    for rule in rules:
        row, entry = values[rule["候補ID"]], entries[rule["入口"]["入口ID"]]
        if row["入口"] != rule["入口"] or row["出口"] != rule["出口"] or any(entry[k] != v for k,v in rule["入口"].items()):
            raise ValueError("入口/順行/出口定義差")
        for period,count in zip(PERIODS,(40,24,2)):
            e,op = entry[period],row[period]["運用"]
            P.validate_entry(e)
            n=op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count or op["買い取引数"]+op["売り取引数"] != n or op["役割別完結数"].get("順行",0) != n:
                raise ValueError("期間/活動/方向/役割分母差")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾分母差")
            for fee in (0,5,10):
                net,mean=op[f"追加{fee}pt純損益円"],op[f"追加{fee}pt平均円"]
                if not math.isclose(net,op["追加0pt純損益円"]-20*fee*n,abs_tol=1e-8) or (mean is None) != (n==0) or n and not math.isclose(mean,net/n,abs_tol=1e-8):
                    raise ValueError("保存費用/平均差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("注意期の全体確定nullを維持")
        support,goal=F.entrance_flags(entry,config)
        fee_ok=all(all(row[p]["運用"][k]>=v for k,v in limits.items()) and row[p]["運用"]["品質注意場数"]==0 and row[p]["運用"]["追加5pt純損益円"]>0 for p,limits in config["費用支持"].items())
        if (entry["入口支持"],entry["70目標"],row["入口支持"],row["70目標"],row["費用資格"],row["現方針候補"],row["採用資格"]) != (support,goal,support,goal,fee_ok,True,goal and fee_ok):
            raise ValueError("支持/70/費用/現在/採用差")
    for period in PERIODS:
        if entries["3分_L0"][period] != entries["3分_L1"][period] or values[CANDIDATES[0]][period]["運用"] != values[CANDIDATES[1]][period]["運用"]:
            raise ValueError("数学的冗長L0/L1の保存集計差")
    roles=report["役割別入口評価"]
    if [(r["入口ID"],r["役割"]) for r in roles] != [("3分_"+p,"順行") for p in POLICIES]:
        raise ValueError("順行三役割群差")
    for row in roles:
        if any(row[p] != entries[row["入口ID"]][p] for p in PERIODS) or (row["入口支持"],row["70目標"]) != F.entrance_flags(row,config):
            raise ValueError("役割別の分母差")
    for field,expected in (("入口70目標達成数",sum(r["70目標"] for r in entries.values())),("費用資格数",sum(r["費用資格"] for r in values.values())),("現方針費用資格数",sum(r["費用資格"] for r in values.values())),("採用資格数",sum(r["採用資格"] for r in values.values()))):
        if report[field] != expected:
            raise ValueError("全体資格数差:"+field)
    names={"固定.json","条件.json","結果.json","作業成果物.json","独立監査.json","状態独立確認.json","追尾独立確認.json","入力台帳.json"}
    reference=F.F.F.F.validate_reference(study/"指標参照.json",NUMERIC_STUDY,names)
    if len(reference["共有明細"]) != 1 or reference["参照試行"] != "00029":
        raise ValueError("固定29全数値一明細だけを共有")
    pointer=G.read_json(study/"入力台帳.json");manifest=(study/pointer["参照"]).resolve()
    if pointer["SHA256"] != G.sha(manifest) or manifest != ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json":
        raise ValueError("固定66場台帳差")
    for key,old_study in (("指標条件参照",NUMERIC_STUDY),("運用条件参照",EXIT_STUDY)):
        if config[key]["SHA256"] != G.sha(old_study/"条件.json"):
            raise ValueError("共有条件現在版差")
    if any(G.sha(ROOT/n) != h for n,h in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("全固定現在版差")
    return config,report,rules,entries,values,manifest


def settings(rules: list[dict]) -> list[dict]:
    """新P・回帰方向・R2準備/値と共通執行を版3へ役割分けする。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は11設定。旧BB/量M/上位/TRcapを採用扱いにしない。
    """
    groups=[
        (["P07"],["m03"],rules,"新P：前20高安を現Cがstrict突破","当場21連続公開有効OHLC、現在を旧20窓へ含めず、各rolling突破を新原Pにする。旧T1の反転s/BB/量Mなし"),
        (["I14"],["m03"],rules,"OLS20：当足含む20C・実side×b>0strict","x0..19/切片付き最小二乗、元floatをFraction化しDxx13300。符号だけを使いMA傾きと同一計算としない"),
        (["I14"],["m03"],rules[1:],"L1共通：R2定義可能","有限20点/strict非零傾きから数学的に冗長。未定義を0/1へ補完せず、差が出れば数値規約を点検"),
        (["I14"],["m03"],rules[2:],"L2追加：R2>=1/2・等号可","半分差の精密分子又は交差積で判定、表示丸め/epsilon/clampなし。標本内直線性で未来確率/有意水準ではない"),
        (["I03"],["m03"],rules,"中心化MACD12/26/9：実side×δH>0","固定29数値を共有、当場隣接公開現前ヒスト有限。交差一般の再現や独立した証拠票としない"),
        (["I09"],["m03"],rules,"共通：現ATR14正・実入口D固定","数量M/旧BB/上位/CLV/TRcapなし。出口D=max(5,ceil(現ATR/5)*5)を維持し、回帰線や前ATRに変更しない"),
        (["B01"],["m03"],rules,"元P公開key/残60分/遅延30秒/同key複数見送り","全Pと技術/時間採否を分け、同方向複数も見送り。全採否確定後にlive13列へdeepcopy、未来labelなし"),
        (["B01"],["tick"],rules,"共通：市場+1秒/TTL30・一pending/一建玉","買ask/売bid新規・正常返済BBO、後続抑止を空き時計へ延期しない。受信時計や実microのキューは別"),
        (["I09","C06","E02"],["tick"],rules,"XF：現在返済BBO利益円−122>0strict","参照片道5pt/往復fee22、入口現ATR固定D/MFE−D/最低名目entry床・非緩和・pending凍結。費用後同値床ではない"),
        (["E01"],["tick"],rules,"全新case：実side新規BBOから125/250直接判定","新母集団なので旧40label/旧全運用対照なし。共通L0/L1/L2は同時計新先着を対応、未約定/期限/不足を分離"),
        (["I14","I03","E01","B01","P05"],["m03","tick"],rules,"診断のみ：全P/方向勢い/R2区分/実参加/回収","全P採否と純入口を分け、同じ実新規出口/片側参加の全費用差を照合。R2の新閾値や旧全体差の単独効果へ戻さない"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,
        "結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]}
        for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同byteの正式証明を優先し、作業正本との版差を拒否する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは保存済み証明。
    """
    return F.proof_path(study, work, name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """人工・非損益準備・回帰再構成・先着・会計・追尾を区別する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tupleは小型検査表と全出典。計算一致は収益標本ではない。
    """
    rows, paths = [], []
    groups = (("合成検証.json", "人工OLS/定値/半分等号/鏡像/新母集団/固定guard"),
        ("独立監査.json", "新case集計/Decimal会計/全資源"),
        ("状態独立確認.json", "新全P/精密OLS/全L/新直接先着"),
        ("追尾独立確認.json", "三XFの全保有・初回要求・名目床"),
        ("対応診断.json", "全新P/回帰方向/R2準備と値/実参加/回収"),
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
    rows += [["固定前主準備・全新P/OLS/三採否", "66場・非損益", 66, G.link(main, output)],
        ["固定前独立新P/OLS/数値と三採否", "一致/合格", number(independent["照合項目数"]), G.link(independent_path, output)]]
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
    text = "## 検査の状態\n\n固定29の3分OHLC/ATR/中心化MACDだけを共有し、41では新P/OLS/三採否/全新case直接先着を独立照合する。旧40の完全同値対照は設けず、同一試行L0/L1の数学的冗長性を別に確認。精密OLS/R2/価格/時点/全採否/D整数は厳密、MACD/ATR表現差の許容は正式計画の範囲に限定し採否epsilonへ使わない。準備は先着/運用/PnLなし、正式の直接先着/新規会計/全追尾と分ける。\n"
    if independent.get("検証範囲"):
        text += "独立準備の実施範囲："+G.cell(independent["検証範囲"])+"。\n"
    text += "全"+str(independent["新3分全数値照合足数"])+"足の別算でATRは"+str(independent["独立atr表現差足数"])+"足、MACDヒストは"+str(independent["独立macd_hist表現差足数"])+"足に表現差があり、最大絶対差はそれぞれ"+str(independent["独立atr最大絶対差"])+"/"+str(independent["独立macd_hist最大絶対差"])+"。ATR・ヒスト・現前ヒスト差だけabs1e−10/rel0で検算し、差符号/ATR正有効/D整数/全採否はstrict一致。保存正本全内容SHAと独立再算の生float SHAが同一という主張ではない。\n"
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
            orows.append([cid, PERIOD_NAMES[period], op["完結取引数"], *[number(op[f"追加{f}pt純損益円"]) for f in (0, 5, 10)], number(op["追加5pt平均円"]), op["品質注意場数"], confirmed(op["追加0pt確定対象円"], op["品質注意場数"])])
            if period in PERIODS[:2]:
                supports.append([cid, PERIOD_NAMES[period], f"{e['約定候補数']}/{e['約定開始日数']}/{e['約定場数']}", f"{op['完結取引数']}/{op['活動開始日数']}/{op['活動場数']}", f"{op['買い取引数']}/{op['売り取引数']}", "充足" if row["入口支持"] else "未達", "達成" if row["70目標"] else "未達", "充足" if row["費用資格"] else "未達", "充足" if row["採用資格"] else "未達"])
    text = "## 三入口・三XF運用の結果\n\n先着主率は期限/観測不足を含む全仮約定が分母、未約定は別記。仮250は実返済後も追う反事実で、実完結の費用後勝率ではない。全案順行・現在XFで、役割別入口三群はそれぞれ同じ入口全件と一致する。\n"
    text += G.table(["入口", "期間", "純要求", "仮約定", "250/全仮約定・率", "125/期限/不足/未約定", "30分間引き250/仮約定・率"], erows)
    text += G.table(["運用", "期間", "実完結", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "注意場", "基準確定円"], orows)
    text += "入口支持は学習60仮約定/6日/10場・選択20/3/5、70は両期主率/間引き率70%・間引き件数20/10。費用支持は学習20完結/6日/10場/買売各5・選択10/3/6/各3と品質注意0、追加5pt後両期黒字。採用は入口70と費用資格の両方。支持/70は学習＋条件選択を合わせた判定で、後続2場単独の支持確認ではない。\n"
    return text+G.table(["運用", "期間", "仮約定/日/場", "実完結/日/場", "実買/売", "両期入口支持", "両期70", "費用資格", "採用資格"], supports)


def confirmed(value: float | None, quality: int) -> str:
    """品質注意による確定nullを、計算未実施と区別して表示する。

    引数: value(float|None)は保存確定額、quality(int)は注意場数。
    返り値: strは41帳票専用表示。観測額を確定額へ補完しない。
    """
    if value is None:
        return "確定不能（品質注意）" if quality else "確定対象なし"
    return number(value)


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """回帰準備・精密R2境界・実占有・回収を保存診断から表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは集計本文。全個別上位値・大明細を転記しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    text = "## 全新Pから回帰方向・勢い・直線性を分ける\n\n"+G.link(path, output)+"が正本。新価格発動全体と純入口は別分母。L0→L1は数学的に冗長なR2定義準備、L1→L2は同時計のR2半分以上による選別。旧40の188登録や旧labelを基準へ流用しない。\n"
    text += G.table(["期間","全新P/M/M時間可","L0/L1/L2純数","候補別競合"],[[PERIOD_NAMES[r["期間"]],f"{r['新原P数']}/{r['共通M準備数']}/{r['M時間遅延通過数']}","/".join(str(r[p+"純入口数"]) for p in POLICIES),G.describe(r["候補別競合数"])] for r in data["全新Pと三入口"]])
    text += G.table(["期間","実傾き","実ヒスト差","全P/M時間可","L0/L1/L2採用"],[[PERIOD_NAMES[r["期間"]],r["実方向傾き"],r["実方向ヒスト差"],f"{r['新原P数']}/{r['M時間可数']}","/".join(str(r[p+"採用数"]) for p in POLICIES)] for r in data["方向と勢い全区分"] if r["新原P数"]])
    text += G.table(["比較/期間","保持要求/仮約定・250率","除外要求/仮約定・250率","保持125/期限/不足/未約定","除外125/期限/不足/未約定","純追加"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],*[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口","除外入口")],*["/".join(str(r[k][f]) for f in ("逆行先着","期限未達","観測不足","未約定")) for k in ("保持入口","除外入口")],r["新規追加入口数"]] for r in data["入口追加比較"]])
    text += G.table(["期間","L0でR2定義","要求/仮約定","250/全仮約定・率"],[[PERIOD_NAMES[r["期間"]],"可能" if r["R2定義可能"] else "未定義",f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["L0のR2定義区分"]])
    text += G.table(["期間","R2区分","全新P","L1要求/仮約定","250/全仮約定・率"],[[PERIOD_NAMES[r["期間"]],r["R2区分"],r["全新原P数"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["R2半分区分"]])
    text += "## 当時の回帰値の記述\n\nL1純要求全件の当時値で、未約定を含む。R2は当該20終値の直線性、傾きはpt/3分足であり、未来成功確率や統計的有意判定ではない。新しい区切りや閾値探索を行わない。\n"
    text += G.table(["期間","L2保持","純要求","R2中央値/最小/最大","実傾き中央値pt毎足"],[[PERIOD_NAMES[r["期間"]],"保持" if r["L2保持"] else "除外",r["要求数"],"/".join(number(r["R2"][k]) for k in ("中央値","最小","最大")),number(r["実方向傾きpt毎足"]["中央値"])] for r in data["保持除外の回帰記述"]])
    text += "## 共通出口と一建玉の実参加差\n\n厳密共通は場/実side/実役割/新規key/価格/入口ATR/D。純入口は部分集合でも、先行建玉やpendingが減ると右だけの実参加が生じ得る。共通0の出口差0は比較対象なし。総額差を一取引平均の改善や共通回収改善と読み替えない。\n"
    text += "今回の右だけの実参加は全比較/全期間で計"+str(sum(r["右のみ"]["完結取引数"] for r in data["実参加比較"]))+"件。一般に生じ得る占有変化と、今回観測した集合を区別する。\n"
    text += G.table(["比較/期間", "同元P両参加/厳密共通", "共通出口属性差", "共通出口差0/5/10円", "左のみ完結・0/5/10円", "右のみ完結・0/5/10円", "全差0/5/10円"], [[r["比較"]+"/"+PERIOD_NAMES[r["期間"]], f"{r['同元P両実参加数']}/{r['厳密共通実新規数']}", r["共通出口属性差数"], "/".join(number(v["共通出口差円"]) for v in r["費用別"]), *[str(r[k]["完結取引数"])+"・"+"/".join(number(r[k][f"追加{f}pt純損益円"]) for f in (0, 5, 10)) for k in ("左のみ", "右のみ")], "/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
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
    return text+G.table(["運用", "期間", "注意/未解消/EOF", "基準観測円", "基準確定円"], [[r["候補ID"], PERIOD_NAMES[r["期間"]], f"{r['品質注意場数']}/{r['未解消場数']}/{r['EOF期限未達場数']}", number(r["観測純額円"]["0"]), confirmed(r["全体確定対象円"]["0"], r["品質注意場数"])] for r in data["品質と確定額"]])


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """新三入口の保存値と全証明だけから、版3の正式二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。結果なしでは生成せず、市場・監査を起動しない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    common,catalog=settings(rules),V3.load_catalog()
    diagnostic=G.read_json(proof_path(study,work,"対応診断.json"))
    intro="新しい3分終値高安突破に、当足含20終値OLSの方向と中心化MACDヒスト差を組み合わせるL0を基準に、L1はR2定義準備、L2はR2>=1/2を追加する。三入口・三XF運用、カタログ版3・53手法×9尺度。全66場（学習40・選択24・既使用11/4Day/Night2）は既使用の開発で、未使用確認ではない。旧40の188登録への追加条件ではなく、新母集団・全新caseである。\n\n"
    conclusion=f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3、現在費用資格は{report['現方針費用資格数']}/3、採用資格は{report['採用資格数']}/3。**\n\n"
    for p in POLICIES:
        conclusion+=p+"XF："+"、".join(PERIOD_NAMES[t]+"は250先着率"+G.pct(entries["3分_"+p][t]["確認率"])+"・追加5pt平均"+number(values["3分_"+p+"_XF"][t]["運用"]["追加5pt平均円"])+"円" for t in PERIODS[:2])+"。\n\n"
    train,select=entries["3分_L2"]["学習"],entries["3分_L2"]["条件選択"]
    conclusion+="L2学習仮約定"+str(train["約定候補数"])+"件/支持下限"+str(config["入口支持"]["学習"]["約定候補数"])+"件、学習間引き"+str(train["30分間引き_順行先着"])+"/"+str(train["30分間引き_約定候補数"])+"="+G.pct(train["30分間引き_確認率"])+"、選択主率"+str(select["順行先着"])+"/"+str(select["約定候補数"])+"="+G.pct(select["確認率"])+"。支持判定は"+("充足" if entries["3分_L2"]["入口支持"] else "未達")+"。一期間/少数群/既使用後続2場を両期資格へ代用しない。\n\n"
    conclusion+="L0→L1の純除外は全期間で計"+str(sum(r["除外入口"]["候補数"] for r in diagnostic["入口追加比較"] if r["比較"]=="R2定義追加"))+"件。strict非零傾きならR2は定義可能なので数学的に冗長な対照で、新しい確認票や予測効果としない。\n\n"
    changes=[r for r in diagnostic["実参加比較"] if r["比較"]=="R2半分選別追加"]
    conclusion+="L1→L2の実共通は学習/選択/後続の順に"+"/".join(str(r["厳密共通実新規数"]) for r in changes)+"件、右だけの実参加は"+"/".join(str(r["右のみ"]["完結取引数"]) for r in changes)+"件。全額差/平均と、共通出口/片側参加を分ける。\n\n"
    for period in PERIODS[:2]:
        r=next(v for v in changes if v["期間"]==period)
        conclusion+=PERIOD_NAMES[period]+"の追加5pt全額差は"+number(r["費用別"][1]["総差円_右引く左"])+"円、一取引平均は"+number(values[CANDIDATES[1]][period]["運用"]["追加5pt平均円"])+"→"+number(values[CANDIDATES[2]][period]["運用"]["追加5pt平均円"])+"円。\n\n"
    conclusion+="L2は条件選択期の先着率が上がっても、追加5pt後の一取引平均は学習/条件選択の両期で悪化した。件数減少による総赤字縮小を平均回収の改善とせず、選択期の先着率だけを採用根拠にしない。\n\n"
    warnings=[r["候補ID"]+"/"+PERIOD_NAMES[t]+"="+str(r[t]["運用"]["品質注意場数"])+"場" for r in values.values() for t in PERIODS if r[t]["運用"]["品質注意場数"]]
    conclusion+=("品質注意は"+"、".join(warnings)+"。該当期の円/全額差は観測値で、全体確定額nullを観測額で置換しない。\n\n") if warnings else "全案各期の品質注意0。実microの約定や将来の経路品質を保証しない。\n\n"
    logic="## 新P・回帰方向・直線性を分ける\n\n新Pは同場直前20公開有効3分の最高H/最安Lを現Cがstrict突破した買/売。現在を旧20高安へ入れず、各rolling突破を別原Pとして保存する。旧T1の元反転P/BB内/元k数量Mを基準へ持ち込まない。OLSは当足を含む20C、x0..19の時計順、切片付き最小二乗。元floatC各値をFraction化し、Dxx13300/Dxy/Dyyから傾きとR2を精密保存する。\n\n"
    logic+="L0は新Pかつ実side×傾き>0・実side×MACDヒスト一足差>0、共通M/時間を満たす順行。L1はR2定義可能、L2はR2>=1/2。全同値ならb0は定義できてもR2は未定義で補完しない。strict傾きならSyy>0なのでL1は理論上L0と同じ。半分等号は採用、表示丸め/epsilon/clampなし。傾き0・勢い0/不一致は待機とし逆注文へ変えない。\n\n"
    logic+="R2は当てはめた20点の直線性で、将来の250先着確率・有意水準・投資家の確信度ではない。19点一定＋最後だけA上昇なら人工OLS20はb=A/70・R2=1/7、直線ならR2=1。ERは一回の一方向急変でも1となり得て別の記述である。高R2でも次から反転し、急変/ヒゲを全て排除しない。価格P/OLS/MACDを独立した三票へ換算しない。\n\n"
    clocks="## 局所窓・新母集団・時計と独立標本の限界\n\n価格前20＋当足、回帰当足含20は同場/公開/有効OHLC/missing0/完全180秒・隣接index/endの局所区間。NP/欠枠/不正/終了前公開で窓を解除し、番号/end/key不連続はclear後の現有効足を新seed可。MACD/ATR数値銀行は固定29の同限月carry/clear/NP内部更新と別管理する。未来足で過去の回帰を引き直さず、元公開keyで一回判断。\n\n"
    clocks+="原P→共通M→傾き/勢い→R2準備/値→時間/遅延→新仮約定→実参加を分ける。同key複数は同方向も見送り、全採否後にlive純13列へdeepcopyし未来labelを混ぜない。連続rolling突破や重複20窓は独立標本と仮定せず、原要求30分間引き/日/場の支持を別表示する。\n\n"
    clocks+="旧40の全属性対照ファイルや旧labelは用いない。全新caseを実sideの新規+1秒正常BBOから直接125/250検算し、同一新Pの各案は新先着11列を対応させる。未保存不採用Pの成績を後段で補算しない。旧40/MA/P12との全体差は発動・準備・母集団も違い、R2単独の因果効果ではない。\n\n"
    protection="## 共通XF・費用・利益保護\n\nmicro1枚代理・倍率10円/pt・呼値5pt・片道fee11円、市場要求+1秒以降TTL30の最初正常BBO（買ask/売bid）、一pending/一建玉、返済要求+1秒を維持。現在正常返済BBOの実side有利額×10−122>0strictでXF起動、往復fee22＋参照片道5pt往復100。過去MFEだけでは起動せず、入口現ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D・最低名目entry床・非緩和・返済pending凍結。hard125/TP250/期限は不変。\n\n"
    protection+="名目床は費用後同値や遅延後同値約定を保証しない。追加0/5/10ptは同約定への費用負荷で起動参照5を変えない。デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。価格時計は受信時計でなく、ラージBBOで実microのキュー/数量/部分約定を保証しない。\n\n"
    limits="## 限界と再利用\n\nL0を新母集団基準とし、L0/L1の冗長確認とL1/L2の直線性選別を分ける。純subsetでも実追加はあり得る。全額差=共通出口差＋右のみ額−左のみ額を全費用で検算し、総額/平均/仮先着/実回収を混ぜない。共通0の出口差0は比較対象なし。\n\n全66場既使用で、計算一致・高R2・少数高率は未使用確認や将来利益の証明でない。品質注意期の全体確定nullを観測額で置換せず、倍率/期間/閾値探索や事後群から採否への反映をしない。主要変更は新試行へ分ける。\n\n"
    table,(audit_text,audit_paths)=result_tables(report,entries,values),audits(study,work,readme)
    links=" / ".join(G.link(study/n,readme) for n in ("計画.md","条件.json","固定.json","結果.json","指標参照.json"))
    summary="# 試行00041：終値突破と回帰の方向と直線性\n\n"+intro+links+" / "+G.link(mapping,readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+logic+clocks+protection+limits+audit_text
    mapped="# 試行00041：設定と結果\n\n"+intro+conclusion+G.link(V3.MASTER,mapping,"コピー元汎用表・版3")+" / "+G.link(readme,mapping)+"\n\n"
    mapped+="## 手法×時間スケール\n\n53手法×9尺度。R0=L0XF新基準/R1=L1XF冗長R2準備/R2=L2XF半分以上。I14の方向S02/準備S03/値S04を区別する。I05旧BB/V01V02量M/上位/C01/CLV/TRcapを採用扱いにしない。未使用・未検証・データ不足・対象外を分ける。\n\n"+V3.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped+="## 三評価の定義\n"+G.table(["評価","候補","役割","入口支持","70目標","費用資格","採用資格"],[[r["評価ID"],r["候補ID"],"順行","充足" if values[r["候補ID"]]["入口支持"] else "未達","達成" if values[r["候補ID"]]["70目標"] else "未達","充足" if values[r["候補ID"]]["費用資格"] else "未達","充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped+=table+logic+clocks+protection+limits+audits(study,work,mapping)[0]
    names=("入力台帳.json","指標参照.json","準備参照.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources=[HERE/n for n in ("README.md","入口.py","運用.py","検証.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs=[ROOT/n for n in ("docs/technical-analysis/指標/線形回帰と決定係数.md","docs/technical-analysis/指標/MACD.md","docs/technical-analysis/指標/ATR.md","docs/technical-analysis/01_チャートの読み方と仮説化.md","scripts/入口探索/探索.py","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing="## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n"
    viewing+="指標参照は固定29全指標一明細の3分限定15列（場/出典/ATR/ヒスト）だけ。旧case/全運用対照を参照せず、新大明細は回帰判定/最小case/全運用/追尾の4gzip。rawとdecisionsは同じ全P列なので二重保存しない。Viewerは3運用各66場・198資源と3代表。\n\n--prepareは新P/精密OLS/純三入口/採否だけで先着/運用/PnLなし。正式は既存結果/部分gzipを上書きしない。再現はコードREADME、保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/回帰突破/レポート.py\n```\n\n"
    if COMMON.is_file():viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers=[ROOT/"scripts"/name/"レポート.py" for name in ("発動値幅継続","上位中心継続","上位雲継続","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths=[Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版3.py",V3.BASE,V3.CATALOG,V3.MASTER,V3.TEXTBOOK,manifest,
        *[study/n for n in ("計画.md","条件.json","固定.json","結果.json",*names) if (study/n).is_file()],NUMERIC_STUDY/"条件.json",NUMERIC_STUDY/"固定.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths]
    for path in (work/"診断予定.json",ROOT/"work/回帰品質41の記録案.md",ROOT/"work/回帰品質41の独立案.md",ROOT/"work/回帰品質41の事前案.md"):
        if path.is_file():paths.append(path)
    for path,body in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全proof完成後の保存二MDだけをCLIで再表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。実市場や監査を呼び出さない。
    """
    parser = argparse.ArgumentParser(description="新終値突破と回帰方向/直線性・保存帳票版3")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
