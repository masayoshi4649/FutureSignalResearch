"""上位方向とForce波三案を、保存証明と版5の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00047_上位方向とForce波からの価格発動"
WORK = ROOT/"work/Force波/00047"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
UPPER_STUDY = ROOT/"study/00028_基準線復帰と上位一目の方向"
COMMON = ROOT/"docs/議論/上位方向とForce波の回復後価格発動を比較する.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES, ROLES = ("T0","R0","S0"), ("順行","反転")
ACTIVE_ROLES = {"T0":("順行",),"R0":("反転",),"S0":("順行","反転")}
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
SPEC = importlib.util.spec_from_file_location("Force47の固定41表示補助",ROOT/"scripts/回帰突破/レポート.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
G,P,F,number = BASE.G,BASE.P,BASE.F,BASE.number
VSPEC = importlib.util.spec_from_file_location("Force47の独立版5表",ROOT/"scripts/レポート/カタログ版5.py")
V5 = importlib.util.module_from_spec(VSPEC)
sys.modules[VSPEC.name] = V5
VSPEC.loader.exec_module(V5)


PREVIOUS = ROOT/"study/00046_二足の実体包みと平均進行"

def rate(value: float | None) -> str:
    """分母0の率を未実行と混同しない表示へ写す。

    引数: value(float|None)は保存率。
    返り値: strは百分率又は対象なし。値を補完しない。
    """
    return "対象なし（分母0）" if value is None else G.pct(value)


def definitions(config: dict) -> list[dict]:
    """順行・反転・切替候補を、単独T/Rと混合Sの三評価へ対応する。

    引数: config(dict)は47条件。
    返り値: list[dict]はR0〜R2。実T/Rは別役割として保持する。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略":p,"出口ID":"XF"} for p in POLICIES]:
        raise ValueError("順行・反転・切替/三XF以外")
    return [{"評価ID":"R"+str(i),"候補ID":cid,"入口":{"入口ID":"3分_"+p,"戦略":p,"時間足分":3,"名称":p,"役割":{"T0":"順行","R0":"反転","S0":"切替"}[p],"複合本命":True},"出口":{"出口ID":"XF"}} for i,(p,cid) in enumerate(zip(POLICIES,CANDIDATES))]

def validate(study: Path) -> tuple:
    """Force波新母集団/三入口/四実役割・支持費用・指標参照と固定を確認する。

    引数: study(Path)は正式先。
    返り値: tupleは条件/結果/評価/入口/運用/台帳。結果なしでは生成しない。
    """
    for name in ("計画.md","条件.json","固定.json","結果.json","指標参照.json","上位参照.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作らない")
    config,report=G.read_json(study/"条件.json"),G.read_json(study/"結果.json")
    rules=definitions(config)
    entries,values={r["入口ID"]:r for r in report["入口評価"]},{r["候補ID"]:r for r in report["結果"]}
    if config["カタログ版"] != 5 or report["全66場既使用"] is not True or (len(entries),len(values),report["入口評価数"],report["運用候補数"],report["現方針運用候補数"]) != (3,3,3,3,3) or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("版5/三入口運用/既使用性に差")
    for rule in rules:
        row,entry=values[rule["候補ID"]],entries[rule["入口"]["入口ID"]]
        if row["入口"] != rule["入口"] or row["出口"] != rule["出口"] or any(entry[k] != v for k,v in rule["入口"].items()):
            raise ValueError("集合役割/出口定義差")
        for period,count in zip(PERIODS,(40,24,2)):
            e,op=entry[period],row[period]["運用"]
            P.validate_entry(e)
            n=op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count or op["買い取引数"]+op["売り取引数"] != n or sum(op["役割別完結数"].get(role,0) for role in ROLES) != n:
                raise ValueError("期間/実役割の分母差")
            for fee in (0,5,10):
                net,mean=op[f"追加{fee}pt純損益円"],op[f"追加{fee}pt平均円"]
                if not math.isclose(net,op["追加0pt純損益円"]-20*fee*n,abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean,net/n,abs_tol=1e-8):
                    raise ValueError("同約定費用/平均差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("品質nullを維持")
        support,goal=F.entrance_flags(entry,config)
        fee_ok=all(all(row[p]["運用"][k]>=v for k,v in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p,limits in config["費用支持"].items())
        if (entry["入口支持"],entry["70目標"],row["入口支持"],row["70目標"],row["費用資格"],row["現方針候補"],row["採用資格"]) != (support,goal,support,goal,fee_ok,True,goal and fee_ok):
            raise ValueError("支持/70/費用/採用差")
    if report["実役割群数"] != 4 or report["対象実役割"] != {p:list(v) for p,v in ACTIVE_ROLES.items()}:
        raise ValueError("実役割数/対象差")
    roles=report["役割別入口評価"]
    if [(r["入口ID"],r["役割"]) for r in roles] != [("3分_"+p,role) for p in POLICIES for role in ACTIVE_ROLES[p]]:
        raise ValueError("実在する四役割群差")
    for row in roles:
        for period in PERIODS:
            P.validate_entry(row[period])
        if (row["入口支持"],row["70目標"]) != F.entrance_flags(row,config):
            raise ValueError("役割別支持の分母差")
    for field,expected in (("入口70目標達成数",sum(r["70目標"] for r in entries.values())),("費用資格数",sum(r["費用資格"] for r in values.values())),("現方針費用資格数",sum(r["費用資格"] for r in values.values())),("採用資格数",sum(r["採用資格"] for r in values.values()))):
        if report[field] != expected:
            raise ValueError("全体資格数差:"+field)
    names={"固定.json","条件.json","結果.json","作業成果物.json","独立監査.json","状態独立確認.json","追尾独立確認.json","入力台帳.json"}
    reference=F.F.F.F.validate_reference(study/"指標参照.json",NUMERIC_STUDY,names)
    if reference["参照試行"] != "00029" or len(reference["共有明細"]) != 1:
        raise ValueError("共有数値一明細だけ")
    upper_ref=F.F.F.F.validate_reference(study/"上位参照.json",UPPER_STUDY,names)
    if upper_ref["参照試行"] != "00028" or len(upper_ref["共有明細"]) != 1 or config["上位価格参照"]["SHA256"] != G.sha(UPPER_STUDY/"条件.json"):
        raise ValueError("上位は固定28価格一明細だけ")
    pointer=G.read_json(study/"入力台帳.json");manifest=(study/pointer["参照"]).resolve()
    if pointer["SHA256"] != G.sha(manifest) or manifest != ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json":
        raise ValueError("固定66場台帳差")
    for key,old in (("指標条件参照",NUMERIC_STUDY),("運用条件参照",EXIT_STUDY)):
        if config[key]["SHA256"] != G.sha(old/"条件.json"):
            raise ValueError("共有条件差")
    if any(G.sha(ROOT/n) != h for n,h in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("全固定現在版差")
    return config,report,rules,entries,values,manifest

def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式小証明を優先し、work正本とのbyte差を拒否する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは同版の保存証明。
    """
    return BASE.proof_path(study,work,name)

def audits(study: Path, work: Path, output: Path) -> tuple:
    """新母集団・数値二経路・直接先着・実会計と追尾を保存証明へ接続する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: tupleは検査表と出典。市場・監査を起動しない。
    """
    rows,paths,proofs=[],[],{}
    for name,title in (("合成検証.json","人工Force種/0量/上位asof/段階優先/鏡像/非PnLguard"),("独立監査.json","新case集計/四実役割/Decimal会計/全資源"),("状態独立確認.json","原8列/Q/Force/上位H二経路/全監視採否/全直接先着"),("追尾独立確認.json","三XF全保有/現在費用起動/名目床/最初返済要求"),("対応診断.json","保存登録/回復/初価格端/純T-R-S/実占有と回収"),("Viewer照合.json","三運用の代表Viewer")):
        path=proof_path(study,work,name);data=G.read_json(path);proofs[name]=data
        verdict,count=data.get("全件一致"),data.get("照合項目数")
        if name == "合成検証.json":
            verdict,count=data["全件成功"] is True and data["合成編集終了"] is True,data["検証件数"]
            if any(G.sha(ROOT/n) != h for n,h in data["ファイルSHA256"].items()):raise ValueError("最終人工の版差")
            for key,file in (("独立数値補助SHA256","状態独立確認.py"),("独立追尾補助SHA256","追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):raise ValueError("人工の独立版差")
        elif name == "Viewer照合.json":verdict,count=len(data.get("照合",[])) == 3 and all(r["一致"] for r in data["照合"]),len(data.get("照合",[]))
        if verdict is not True or data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):raise ValueError("証明未完/結果版差:"+name)
        if name == "対応診断.json" and data["参照SHA256"]["結果.json"] != G.sha(study/"結果.json"):raise ValueError("診断の結果版差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):raise ValueError("独立未接続")
        rows.append([title,"一致/合格",number(count),G.link(path,output)]);paths.append(path)
    main,ip=work/"準備点検.json",proof_path(study,work,"独立準備点検.json")
    prepared,independent,lock,ref=G.read_json(main),G.read_json(ip),G.read_json(study/"固定.json"),G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(ip):raise ValueError("非損益準備join差")
    if any(d["ラベル計算"] is not False or d["損益計算"] is not False for d in (prepared,independent)):raise ValueError("準備は非先着/非PnL")
    definition=prepared["上位数値定義"]
    dp=ROOT/definition["パス"]
    if G.sha(dp) != definition["圧縮SHA256参考"] or any(data["上位数値定義"] != definition for data in (independent,proofs["状態独立確認.json"],proofs["追尾独立確認.json"],proofs["独立監査.json"])):
        raise ValueError("新上位H正本定義join差")
    preserved=study/"上位数値定義.jsonl.gz"
    if preserved.is_file() and G.sha(preserved) != G.sha(dp):raise ValueError("上位H正式保全/work差")
    paths.extend((main,ip,dp))
    if preserved.is_file():paths.append(preserved)
    rows.extend((["固定前主準備・Force26/新上位14/全cross/監視/終端/三採否","66場・非損益",66,G.link(main,output)],["固定前独立・原OHLC/Q/Force精密/上位H二経路/全採否","一致/合格",number(independent["照合項目数"]),G.link(ip,output)],["新上位H小型定義・場/index/macd_histの3列","独立生H数値検算と分離",definition["行数"],G.link(preserved if preserved.is_file() else dp,output)]))
    references=ref["参照"].values() if isinstance(ref["参照"],dict) else ref["参照"]
    if ref.get("大準備複製",False) is not False:raise ValueError("主準備は軽量参照のみ")
    for item in references:
        path=ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:raise ValueError("準備軽量参照差")
        paths.append(path)
    path=proof_path(study,work,"会計人工接続.json");artificial=G.read_json(path)
    if artificial["全件一致"] is not True or artificial["不一致数"] != 0 or artificial["人工経路数"] != 8 or any(G.sha(ROOT/n) != h for n,h in artificial["コードSHA256"].items()):raise ValueError("会計人工未完/版差")
    rows.append(["会計人工・四実役割買売8経路/空群API","主最終人工と別",number(artificial["照合項目数"]),G.link(path,output)]);paths.append(path)
    text="## 検査の状態\n\n新母集団の下位数量/Force・新上位H/当時asof・全登録/監視/終端/採否と全新case実方向BBO直接先着は47状態、全保有/最初返済要求は追尾、即時受付/Decimal/CSV/198資源は財務へ接続する。旧入口/label/運用の完全同値対照はない。Force全分数/時点/準備/方向/採否はstrict。下位ATR/新上位H値とΔH値だけabs1e-10・rel0で独立生数値を検算し、ATR有効/D整数・上位有限準備/ΔH符号=D・全採否はstrict、採否epsilonなし。H水準signは未使用。H正本3列定義へ置いた全内容SHAと生値の表現差を別保証にし、生float全SHA同一と呼ばない。\n"
    for key in ("検証範囲","厳密範囲","数値許容"):
        if independent.get(key):text+=key+"："+G.cell(independent[key]).rstrip("。")+"。\n"
    summary={k:v for k,v in independent.items() if any(s in k for s in ("表現差","最大絶対差","厳密不一致","判断不一致","生数値SHA","独立生全指標SHA")) and not isinstance(v,list)}
    if summary:text+="数値検算の保存要約："+G.describe(summary)+"。\n"
    return text+G.table(["範囲","明示合否","件/項目","正本"],rows),paths


def result_tables(report: dict, entries: dict, values: dict) -> str:
    """三入口と四役割群の先着・支持、実費用を分けて表示する。

    引数: report/entries/values(dict)は保存結果。
    返り値: strは小型表。後続2場へ単独の支持資格を付けない。
    """
    erows,orows,rrows=[],[],[]
    for policy in POLICIES:
        for period in PERIODS:
            e=entries["3分_"+policy][period]
            erows.append([policy,PERIOD_NAMES[period],e["候補数"],e["約定候補数"],f"{e['順行先着']}/{e['約定候補数']}・{rate(e['確認率'])}","/".join(str(e[k]) for k in ("逆行先着","期限未達","観測不足","未約定")),f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{rate(e['30分間引き_確認率'])}"])
    for cid in CANDIDATES:
        row=values[cid]
        for period in PERIODS:
            op=row[period]["運用"]
            orows.append([cid,PERIOD_NAMES[period],op["完結取引数"],*[number(op[f"追加{f}pt純損益円"]) for f in (0,5,10)],number(op["追加5pt平均円"]) if op["完結取引数"] else "対象なし（完結0）",op["品質注意場数"],BASE.confirmed(op["追加0pt確定対象円"],op["品質注意場数"])])
    for role in report["役割別入口評価"]:
        for period in PERIODS:
            e=role[period]
            rrows.append([role["入口ID"],role["役割"],PERIOD_NAMES[period],f"{e['候補数']}/{e['約定候補数']}",f"{e['順行先着']}/{e['約定候補数']}・{rate(e['確認率'])}",f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{rate(e['30分間引き_確認率'])}",f"{e['約定開始日数']}/{e['約定場数']}","充足" if role["入口支持"] else "未達","達成" if role["70目標"] else "未達"])
    text="## 三入口・三XFと四役割群\n\n主先着率は期限/観測不足を含む全仮約定が分母、未約定は別記。終端k/fの要求時計を30分間引きの主にする。T0順行/R0反転/S0集合切替・実T順行/R反転。混合率の変化を両役割の改善や片役割支持へ代用しない。\n"
    text+=G.table(["入口","期間","純要求","仮約定","250/全仮約定・率","125/期限/不足/未約定","k/f30分間引き250/仮約定・率"],erows)
    text+=G.table(["運用","期間","実完結","基準観測円","追加5pt観測円","追加10pt観測円","追加5pt平均円","注意場","基準確定円"],orows)
    text+="入口支持は学習60仮約定/6日/10場・選択20/3/5。70は両期主率/間引き率70%・間引き件数20/10。費用支持は学習20完結/6日/10場/買売各5・選択10/3/6/各3と品質注意0、追加5pt後両期黒字。採用は入口70と費用資格の両方。以下の役割支持/70は学習＋条件選択の両期判定の再掲で、後続2場単独が支持条件を満たす意味ではない。\n"
    return text+G.table(["入口","実役割","期間","要求/仮約定","250/仮約定・率","k/f間引き250/仮約定・率","日/場","両期役割支持","両期役割70"],rrows)

def settings(rules: list[dict]) -> list[dict]:
    """上位背景・Force波・価格端と執行を版5へ役割別に対応する。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は11設定。Forceを独立票や単独効果としない。
    """
    groups = [
        (["I03","C07"],["m15"],rules,"当場可視15分現前ヒスト差D・水準不使用","新中心化MACD12/26/9。end/key両asofの最新と当場隣接前、最新不良を古正常へfallbackしない"),
        (["V07"],["m03"],rules,"Force2=(2X+前F)/3・初2Xmean・元float Fraction","X=終値差×観測q。完全非負0量有効、q不完全はForce解除/正常C保持。真の売買側flowではない"),
        (["V07","P04","C07"],["m03"],rules,"背景p/b既知→Force逆行cross bを一監視","sF前>=0/sF現<0、p/bでD=s。監視中置換なし/b6足共有寿命・終了同足再登録なし。bはdeadline前だけ"),
        (["V07","P03","P04","P07"],["m03"],rules,"最初回復j→後続最初strict終値端T/R/WAIT","回復前逆端失敗優先WAIT、初回復D不一致もmonitorWAIT。j後T端/R端初回だけraw、端等号未到達・後端救済なし"),
        (["V07","P07","C07"],["m03"],rules,"初価格端で現在D/Fが実side一致・R実side=-s","T0順行/R0反転/S0切替。上位0/逆だけでRを発動せず、技術/時間不成立はWAIT消費"),
        (["I09"],["m03"],rules,"終端k/f要求時ATR有限正/固定D・b/jATR不使用","bへATR準備を先に課さない。価格/Force/上位未準備先取消と、ATR初価格端WAITを区別"),
        (["V07","P03","P04"],["m03"],rules,"診断のみ：全cross/受理/回復/初端/同上位u/0量","全登録と価格rawを別分母、T-R純非重複/S和集合と実占有を分け、時間/端距離から新閾値を作らない"),
        (["B01"],["m03"],rules,"最終要求clock/残60分/遅延30秒・pure13","b登録はdeadlineだけ、j時計やb時計の先着へ遡らない。最終要求の30分間引き、全採否後deepcopy"),
        (["B01"],["tick"],rules,"正常BBO新規+1秒/TTL30・一pending一建玉","価格端は過去の停止注文約定ではない。純一監視と実三運用の占有は別機械"),
        (["I09","C06","E02"],["tick"],rules,"XF現在返済利益円-122>0strict/名目entry床","終端要求ATR固定D/MFE-D/非緩和/pending凍結。0/5/10同約定負荷・起動参照5固定"),
        (["E01","B01"],["tick"],rules,"新直接125/250・単独対S同役割/実回収","全新sideを直接検算。T/R各支持とS混合支持、共通出口/片側参加、仮250/実MFE/回収を分ける"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,"結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]} for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """登録/回復/終端と、純和集合/単独対混合実占有を保存小表へ分ける。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは保存値の要約。価格/Force/上位/先着は再計算しない。
    """
    path = proof_path(study,work,"対応診断.json")
    data = G.read_json(path)
    text = "## 逆行cross・登録受理・回復・初価格端\n\n"+G.link(path,output)+"が保存診断の正本。全Force逆行cross候補と受理b、回復j、j後初価格端、三純入口、仮約定、実完結は別分母。回復前失敗/初回復D不一致はmonitorWAITで、価格raw/先着caseへ増やさない。\n"
    text += G.table(["期間","3分/15分足","cross/受理b/回復j/初価格端","構造T/R","最終T/R/WAIT","T0/R0/S0純要求","登録不受理理由・重複"],[[PERIOD_NAMES[r["期間"]],f"{r['下位数値足数']}/{r['上位数値足数']}","/".join(str(r[k]) for k in ("逆行cross候補数","受理b数","初回回復j数","初価格端数")),"/".join(str(r["構造T-R別"].get(k,0)) for k in ("T","R")),"/".join(str(r["最終T-R-WAIT別"].get(k,0)) for k in ("T","R","WAIT")),"/".join(str(r[p+"純入口数"]) for p in POLICIES),G.describe(r["登録不受理理由_重複"])] for r in data["登録と監視の段階"]])
    text += G.table(["期間","取消/満了/対象時点外","回復前失敗/初回復不一致WAIT","初回復固定/初価格端/場末取消"],[[PERIOD_NAMES[r["期間"]],"/".join(str(r["監視動作別"].get(k,0)) for k in ("監視取消","寿命満了","段階時点対象外")),"/".join(str(r["監視動作別"].get(k,0)) for k in ("回復前失敗WAIT","初回回復不一致WAIT")),"/".join(str(r["監視動作別"].get(k,0)) for k in ("初回回復固定","初価格端消費","場末監視取消"))] for r in data["登録と監視の段階"]])
    text += "## 時間・同じ上位参照・数量0の診断\n\n純要求を分母に元b年齢/回復待ち/価格待ちを記述する。b6足はjでresetせず、時点対象外も寿命に数える。分布から新寿命・時間閾値へ戻さない。同じ上位uをp/bで見たことを独立二確認とせず、0qで残る平滑Forceを現在の真のフローと呼ばない。\n"
    text += G.table(["入口/役割/期間","純要求","元b年齢 件/中央/最大","b→j秒 件/中央/最大","j→価格端秒 件/中央/最大"],[[r["入口"]+"/"+r["役割"]+"/"+PERIOD_NAMES[r["期間"]],r["純要求数"],*[str(r[k]["件数"])+"/"+number(r[k]["中央値"])+"/"+number(r[k]["最大"]) for k in ("元bからの本数","bから回復まで秒","回復から価格端まで秒")]] for r in data["診断専用の時間"]])
    text += "固定した発動端は利確目標ではない。要求終値は未約定込み純要求、仮新規はその仮約定だけを分母に、端から既に進んだ距離を符号付きで記す。負を丸めず新余地gateへ戻さない。\n"
    text += G.table(["入口/役割/期間","純要求","要求終値→発動端 件/中央/最小/最大pt","仮新規→発動端 件/中央/最小/最大pt"],[[r["入口"]+"/"+r["役割"]+"/"+PERIOD_NAMES[r["期間"]],r["純要求数"],*[str(r[k]["件数"])+"/"+"/".join(number(r[k][f]) for f in ("中央値","最小","最大")) for k in ("要求終値から発動端まで実方向距離pt","仮新規から発動端まで実方向距離pt")]] for r in data["診断専用の端距離"]])
    text += G.table(["期間/分母","件数","p/b同じ上位u","当足q0","現在Force実方向一致"],[[PERIOD_NAMES[r["期間"]]+"/"+r["分母"],r["件数"],r.get("pとbの上位u同一数","対象外"),r.get("当足q0数",r.get("登録当足q0数","対象外")),r.get("現在Force実方向一致数","対象外")] for r in data["Forceと背景の構成"]])
    text += G.table(["期間/日夜","初価格端","構造T/R","最終T/R/WAIT","T0/R0/S0純要求"],[[PERIOD_NAMES[r["期間"]]+"/"+r["日夜"],r["初価格端数"],"/".join(str(r["構造T-R別"].get(k,0)) for k in ("T","R")),"/".join(str(r["最終T-R-WAIT別"].get(k,0)) for k in ("T","R","WAIT")),"/".join(str(r[p+"純入口数"]) for p in POLICIES)] for r in data["日夜と構造区分"]])
    text += "## 単独T/RとS同役割の実参加・共通出口\n\n純T-R非重複/S和集合を保存caseで検算し、実一建玉の占有を別にする。共通は場/実side/実新規key/価格/終端ATR/D/実役割が同じもの。単独T0対S順行、単独R0対S反転を対応し、全額差=共通出口差＋右のみ額−左のみ額を0/5/10で確認する。共通0の差0は対象なし。\n"
    if all(r[k]["完結取引数"] == 0 for r in data["実参加比較"] for k in ("左のみ","右のみ")):
        text += "今回の全6比較では単独とS同役割の片側参加は0、共通出口差も0で、実S額も単独T/R額の和と同じだった。これは観測結果で、純和集合から一般に実参加/損益和が保証される意味ではない。\n"
    text += G.table(["比較/期間/役割","同P両参加/共通","出口属性差","共通出口差0/5/10円","左のみ完結・0/5/10円","右のみ完結・0/5/10円","全差0/5/10円"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],f"{r['同P両実参加数']}/{r['経済的共通実新規数']}",r["共通出口属性差数"],"/".join(number(v["共通出口差円"]) for v in r["費用別"]),*[str(r[k]["完結取引数"])+"・"+"/".join(number(r[k][f"追加{f}pt純損益円"]) for f in (0,5,10)) for k in ("左のみ","右のみ")],"/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較/期間","左のみの相手取扱","右のみの相手取扱"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],G.describe(r["左のみの相手取扱"]),G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text += "単独T/Rの二運用和は二建玉を許す別経路で、S一建玉portfolioの再現ではない。以下の額をそのまま混合の機会損失や改善可能利益にしない。\n"
    text += G.table(["期間","単独T/R合計完結/S完結","単独和0/5/10円","S0/5/10円","差S引く和0/5/10円"],[[PERIOD_NAMES[r["期間"]],f"{r['単独T-R完結合計']}/{r['S完結数']}",*["/".join(number(v[k]) for v in r["費用別"]) for k in ("単独T-R純額合計円","S純額円","差円_S引く単独和")]] for r in data["単独和と混合"]])
    text+="## 仮250と役割別実回収・利益保護\n\n仮250は実返済後も追う経路。実保有MFE250、実回収、起動後費用赤字とは別である。名目床は費用後同値や遅延後同値約定を保証しない。\n"
    text+=G.table(["運用/役割","期間","実完結","対応仮250/判定前返済","実MFE250","起動/基準赤字","同値費用/不利/正益費用負け"],[[r["候補ID"]+"/"+r["役割"],PERIOD_NAMES[r["期間"]],r["完結取引数"],f"{r['対応仮250数']}/{r['仮250判定前返済数']}",r["実保有MFE250数"],f"{r['起動数']}/{r['起動後基準赤字数']}",f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}/{r['正名目利益の基準費用負け数']}"] for r in (*data["候補別回収"],*data["役割別回収"])])
    text+="以下の同値未満/最終線不足は追尾起動後の取引に限る。\n"
    trades=G.read_csv(study/"固定候補_取引.csv");floors=[]
    for cid in CANDIDATES:
        for period in PERIODS:
            own=[r for r in trades if r["手法"] == cid and r["期間"] == period and r["追尾起動"] == "True"]
            below=sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in own)
            delta=[float(r["最終追尾から実返済方向差pt"]) for r in own if r["最終追尾から実返済方向差pt"] not in ("","None")]
            floors.append([cid,PERIOD_NAMES[period],len(own),below,sum(v < 0 for v in delta),number(min(delta) if delta else None)])
    text+=G.table(["運用","期間","起動済み","実同値未満","最終線未満","最終線から返済の最小差pt"],floors)
    return text+G.table(["運用","期間","注意/未解消/EOF","基準観測円","基準確定円"],[[r["候補ID"],PERIOD_NAMES[r["期間"]],f"{r['品質注意場数']}/{r['未解消場数']}/{r['EOF期限未達場数']}",number(r["観測純額円"]["0"]),BASE.confirmed(r["全体確定対象円"]["0"],r["品質注意場数"])] for r in data["品質と確定額"]])

def run(study: Path, work: Path, output: Path) -> list[Path]:
    """全証明後に保存値だけからT/R/S三案・四役割の二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。正式結果なしでは生成しない。
    """
    config,report,rules,entries,values,manifest = validate(study)
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping = output/"README.md",output/"設定と結果.md"
    common,catalog = settings(rules),V5.load_catalog()
    intro = "公開15分MACD差の背景をp/bで知り、3分Force2逆行cross bを登録、後続の初回回復jを知った後、さらに後の最初終値端だけでT順行/R反転/WAITを判別する。T0順行/R0反転/S0切替・三入口三XF・実四役割群、版5・55手法×9尺度。旧入口AND/旧label転用/旧運用完全対照ではなく、Force/上位/数量単独の寄与実験でもない。全NK66場は既使用の追加開発、TOPIX未参照・11/5Day両商品は対象外/未開封。\n\n"
    conclusion = f"**支持付き入口70目標{report['入口70目標達成数']}/3、費用資格{report['費用資格数']}/3、採用資格{report['採用資格数']}/3。**\n\n"
    for policy in POLICIES:
        e = entries["3分_"+policy]
        conclusion += policy+"："+"、".join(PERIOD_NAMES[q]+"250先着"+rate(e[q]["確認率"])+"（仮約定"+str(e[q]["約定候補数"])+"件）・追加5pt平均"+number(values["3分_"+policy+"_XF"][q]["運用"]["追加5pt平均円"])+"円" for q in PERIODS[:2])+"。両期入口支持は"+("充足" if e["入口支持"] else "未達")+"。\n\n"
    conclusion += "単独T/Rの支持とS混合/役割別支持は別判定。薄いRや既使用後続を混合/両期支持へ代用しない。純S和集合が実参加・実損益和になるとは限らず、総額/平均と同新規出口/占有差を分ける。\n\n"
    model = "## 順序付き複合条件と時点\n\n当時可視の最新15分uと当場隣接前足のH差Dを背景にし、p/bで同じ非0方向sを既知とする。上位end<=下位endと公開key<=要求key両方、最新不良は古正常へfallbackしない。ヒスト水準signは未使用、同じuの二参照を独立二確認としない。上位Hは旧28価格から固定29中心化MACD12/26/9式で新計算し、同契約carry/完全NP内部更新と局所公開参照を分ける。\n\nX=(C現−C前)*q現、Force2は初2有効Xmeanを種に以後(2X+前F)/3。元C/qをFraction化し、完全非負0q/0Fは有効。q不完全でForceを解除しても正常Cを次足価格基準に保持、前価格q不要。NP/欠枠/不正/局所不連続は価格/Forceを解除。真の売買側flowではなく、同正量ならEMA2(価格差)の定数倍になる。\n\nsF前>=0からsFb<0へ逆行cross、p/bでD=sならb候補を一監視受理。bはdeadline前だけでcutoff/残60/遅延/ATRを課さない。元bから6足を両段共有しjでresetせず、Force/最新上位未準備/価格不正/期限を先取消、D0/逆だけなら維持する。監視中・終了同足の別crossは置換/再登録しない。\n\n対象足end>親confirm/key>親keyで初回sF>0をjとし、D=sなら再開端を固定、D不一致はmonitorWAIT。回復前逆端strict終値失敗は先WAITでRにしない。j後、買元方向ならC>HjをT/C<LbをR、売鏡像の最初終値端で一回消費。両端等号は未到達、ヒゲ順序を推定せず後端へ取り直さない。現在DとForceが実side（T=s/R=−s）へ一致し、終端ATR/時間/遅延が有効なら採用、他はWAIT。start>親confirmは要求しない。\n\nT0/R0は純非重複、S0はその和集合。実T順行/R反転を保持し、Tが将来損した補集合からRを作らない。最終k/f時計で新規要求し、b/jや端価格へ遡らない。旧23/42等の多段監視と重なる設計を再用し、Forceという名前だけで全く独立した新手法とはしない。\n\n"
    protection = "## 共通XF・費用と限界\n\nmicro1枚/10円pt/呼値5pt/片道fee11円、正常BBO新規+1秒TTL30・返済+1秒、一pending一建玉。実side×(現在正常返済mark−entry)pt×10円/pt−122円>0strictで起動。終端k/f要求時ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D/最低名目entry床/非緩和/返済pending凍結。b/jATRへ取り替えない。起動参照滑り5込み費用後0円超で旧A5名目5pt起動ではなく、0/5/10同約定費用負荷でも起動参照5固定。hard125/TP250/期限/場内完結。\n\n名目床は費用後同値/遅延後同値約定を保証しない。起動後基準赤字は追加0pt手数料込みで起動122円/追加5pt成績と別尺度。仮250/実MFE250/回収を分ける。価格時計は受信時計ではなく、ラージBBO代理は実micro数量/キュー/部分約定を保証しない。心理の仮説を注文意図の実測へ拡張せず、寿命/構成/待ち時間から新閾値を作らない。\n\n"
    audit_text,audit_paths = audits(study,work,readme)
    table = result_tables(report,entries,values)
    summary = "# 試行00047：上位方向とForce波からの価格発動\n\n"+intro+G.link(mapping,readme)+" / "+G.link(study/"計画.md",readme)+" / "+G.link(study/"結果.json",readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+model+protection+audit_text
    mapped = "# 試行00047：設定と結果\n\n"+intro+conclusion+G.link(V5.MASTER,mapping,"汎用表・版5コピー元")+" / "+G.link(readme,mapping)+"\n\n## 手法×時間スケール\n\n55手法×9尺度。旧54行/9尺度を保持しV07だけ追加。I03は15分背景、V07は3分波、P03/P04/P07は固定端と後続終値、C07は時間幅の役割、I09/XFと執行を分ける。CMF/VR/OBV/MFI/RSI/ADX/TOPIX/OLS等は不使用。\n\n"+V5.matrix(catalog,mapping,common)
    mapped += "## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped += "## 三評価定義\n"+G.table(["評価","運用","入口支持","70目標","費用","採用"],[[r["評価ID"],r["候補ID"],*["充足" if values[r["候補ID"]][k] else "未達" for k in ("入口支持","70目標","費用資格","採用資格")]] for r in rules])
    mapped += table+model+protection+audits(study,work,mapping)[0]
    names = ("計画.md","条件.json","固定.json","結果.json","入力台帳.json","指標参照.json","上位参照.json","準備参照.json","上位数値定義.jsonl.gz","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources = [HERE/n for n in ("README.md","入口.py","指標.py","運用.py","検証.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/ForceIndex.md","docs/technical-analysis/指標/MACD.md","docs/technical-analysis/指標/ATR.md","docs/technical-analysis/組み合わせ/上位足と下位足.md","docs/議論/価格時計と受信時計を分ける.md","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing = "## 閲覧・再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n正式7gzip/共有参照2、価格状態は全cross候補の登録と全3分監視の種別混合。旧入口/label/controlなし。新上位H正本定義は場/index/macd_histの3列だけを正式同byte保全し、work消去時は所定workへ復元して圧縮/展開SHAを照合する。旧全数値や原板を複製しない。Viewer198資源と3代表。--prepareは数値/登録/監視/採否だけで先着/運用/PnLなし、既存結果/部分gzip上書き拒否。\n\n保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/Force波/レポート.py\n```\n\n"
    if COMMON.is_file():viewing += G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers = [ROOT/"scripts"/name/"レポート.py" for name in ("回帰突破","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths = [Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版5.py",V5.BASE,V5.CATALOG,V5.MASTER,manifest,PREVIOUS/"固定.json",*[study/n for n in names if (study/n).is_file()],NUMERIC_STUDY/"条件.json",UPPER_STUDY/"条件.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths,work/"診断予定.json",ROOT/"work/次研究47の独立案.md"]
    for path,body in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全証明後に保存二MDだけを表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。市場/独立/監査/診断を起動しない。
    """
    parser=argparse.ArgumentParser(description="上位方向とForce波の保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK);parser.add_argument("--output",type=Path)
    args=parser.parse_args();print("\n".join(str(p) for p in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__ == "__main__":main()
