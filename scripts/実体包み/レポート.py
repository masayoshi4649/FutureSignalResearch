"""二足実体包みと前平均三案を、保存証明と版4の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00046_二足の実体包みと平均進行"
WORK = ROOT/"work/実体包み/00046"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/二足の実体包みを前平均の進行と位置で分けた比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES, ROLES = ("B0","B1","B2"), ("順行","反転")
ACTIVE_ROLES = {"B0":("反転",),"B1":("反転",),"B2":("順行","反転")}
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
SPEC = importlib.util.spec_from_file_location("実体46の固定41表示補助",ROOT/"scripts/回帰突破/レポート.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
G,P,F,number = BASE.G,BASE.P,BASE.F,BASE.number
VSPEC = importlib.util.spec_from_file_location("実体46の独立版4表",ROOT/"scripts/レポート/カタログ版4.py")
V4 = importlib.util.module_from_spec(VSPEC)
sys.modules[VSPEC.name] = V4
VSPEC.loader.exec_module(V4)


PREVIOUS = ROOT/"study/00045_確定スイング突破と方向優勢"

def definitions(config: dict) -> list[dict]:
    """二反転・一切替候補を、準備と値の三評価へ対応する。

    引数: config(dict)は46条件。
    返り値: list[dict]はR0〜R2。実T/Rは別役割として保持する。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略":p,"出口ID":"XF"} for p in POLICIES]:
        raise ValueError("二反転・一切替/三XF以外")
    return [{"評価ID":"R"+str(i),"候補ID":cid,"入口":{"入口ID":"3分_"+p,"戦略":p,"時間足分":3,"名称":p,"役割":"切替" if p == "B2" else "反転","複合本命":True},"出口":{"出口ID":"XF"}} for i,(p,cid) in enumerate(zip(POLICIES,CANDIDATES))]

def validate(study: Path) -> tuple:
    """二実体母集団/三入口/四実役割・支持費用・指標参照と固定を確認する。

    引数: study(Path)は正式先。
    返り値: tupleは条件/結果/評価/入口/運用/台帳。結果なしでは生成しない。
    """
    for name in ("計画.md","条件.json","固定.json","結果.json","指標参照.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作らない")
    config,report=G.read_json(study/"条件.json"),G.read_json(study/"結果.json")
    rules=definitions(config)
    entries,values={r["入口ID"]:r for r in report["入口評価"]},{r["候補ID"]:r for r in report["結果"]}
    if config["カタログ版"] != 4 or report["全66場既使用"] is not True or (len(entries),len(values),report["入口評価数"],report["運用候補数"],report["現方針運用候補数"]) != (3,3,3,3,3) or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("版4/三入口運用/既使用性に差")
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
    for name,title in (("合成検証.json","人工二実体境界/現足除外平均/公開時点/鏡像/非PnLguard"),("独立監査.json","新case集計/四実役割/Decimal会計/全資源"),("状態独立確認.json","原8列/二実体/ATR-H二経路/全SMA/全採否/全直接先着"),("追尾独立確認.json","三XF全保有/現在費用起動/名目床/最初返済要求"),("対応診断.json","保存二実体/平均準備と値/役割対応/実参加と回収"),("Viewer照合.json","三運用の代表Viewer")):
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
    paths.extend((main,ip))
    rows.extend((["固定前主準備・全27列/二足P/MACD/前平均/三採否","66場・非損益",66,G.link(main,output)],["固定前独立・原OHLC/生ATR-H/全SMA精密/新P/全採否","一致/合格",number(independent["照合項目数"]),G.link(ip,output)]))
    references=ref["参照"].values() if isinstance(ref["参照"],dict) else ref["参照"]
    if ref.get("大準備複製",False) is not False:raise ValueError("主準備は軽量参照のみ")
    for item in references:
        path=ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:raise ValueError("準備軽量参照差")
        paths.append(path)
    path=proof_path(study,work,"会計人工接続.json");artificial=G.read_json(path)
    if artificial["全件一致"] is not True or artificial["不一致数"] != 0 or artificial["人工経路数"] != 8 or any(G.sha(ROOT/n) != h for n,h in artificial["コードSHA256"].items()):raise ValueError("会計人工未完/版差")
    rows.append(["会計人工・四実役割買売8経路/空群API","主最終人工と別",number(artificial["照合項目数"]),G.link(path,output)]);paths.append(path)
    text="## 検査の状態\n\n新二実体母集団の原P/局所SMA/全採否と全新caseの実方向BBO直接先着は46状態へ接続する。旧入口/旧11label/旧運用の完全同値対照はなく、固定29は価格/ATR/中心化MACD-Hの共有材料だけ。全保有と最初返済要求は追尾、即時受付/Decimal/CSV/全198資源は財務へ分ける。正本15列コピーと精密SMAを使う全27列/全判定内容hashは厳密。独立生ATR/H/現前H差だけabs1e-10・rel0、ATR有効/D整数・Hと差の符号/準備/全採否はstrictで、採否epsilonを足さない。DMI定義blobや旧pivot機械は作らず、生float全SHA同一と呼ばない。\n"
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
            erows.append([policy,PERIOD_NAMES[period],e["候補数"],e["約定候補数"],f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}","/".join(str(e[k]) for k in ("逆行先着","期限未達","観測不足","未約定")),f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}"])
    for cid in CANDIDATES:
        row=values[cid]
        for period in PERIODS:
            op=row[period]["運用"]
            orows.append([cid,PERIOD_NAMES[period],op["完結取引数"],*[number(op[f"追加{f}pt純損益円"]) for f in (0,5,10)],number(op["追加5pt平均円"]),op["品質注意場数"],BASE.confirmed(op["追加0pt確定対象円"],op["品質注意場数"])])
    for role in report["役割別入口評価"]:
        for period in PERIODS:
            e=role[period]
            rrows.append([role["入口ID"],role["役割"],PERIOD_NAMES[period],f"{e['候補数']}/{e['約定候補数']}",f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",f"{e['約定開始日数']}/{e['約定場数']}","充足" if role["入口支持"] else "未達","達成" if role["70目標"] else "未達"])
    text="## 三入口・三XFと四役割群\n\n主先着率は期限/観測不足を含む全仮約定が分母、未約定は別記。新要求j時計を30分間引きの主にする。B0/B1は集合/実役割とも反転、B2だけ集合切替で実T順行/R反転。混合率の変化を両役割の改善や片役割支持へ代用しない。\n"
    text+=G.table(["入口","期間","純要求","仮約定","250/全仮約定・率","125/期限/不足/未約定","j30分間引き250/仮約定・率"],erows)
    text+=G.table(["運用","期間","実完結","基準観測円","追加5pt観測円","追加10pt観測円","追加5pt平均円","注意場","基準確定円"],orows)
    text+="入口支持は学習60仮約定/6日/10場・選択20/3/5。70は両期主率/間引き率70%・間引き件数20/10。費用支持は学習20完結/6日/10場/買売各5・選択10/3/6/各3と品質注意0、追加5pt後両期黒字。採用は入口70と費用資格の両方。以下の役割支持/70は学習＋条件選択の両期判定の再掲で、後続2場単独が支持条件を満たす意味ではない。\n"
    return text+G.table(["入口","実役割","期間","要求/仮約定","250/仮約定・率","j間引き250/仮約定・率","日/場","両期役割支持","両期役割70"],rrows)

def settings(rules: list[dict]) -> list[dict]:
    """二実体・MACD・平均の準備/分類と固定XFを版4へ対応する。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は11設定。旧pivot/量/DMI/上位を採用扱いにしない。
    """
    groups = [
        (["P01","P04"],["m03"],rules,"反対色の二実体包み・始値等号可/終値strict","s(Cp-Op)<0/s(Cj-Oj)>0/s(Oj-Cp)<=0/s(Cj-Op)>0。ヒゲ包み/実体比/CLV/新20高安は追加しない"),
        (["I03"],["m03"],rules,"実side*(Hj-Hp)>0strict・現前H有限","固定29中心化MACD12/26/9を共有。水準/交差/RSIを新ANDせず、不一致は見送りで反対新規なし"),
        (["I09"],["m03"],rules,"固定29現在jATR有限正・全3案で入口D固定","旧15列正本コピーと独立生ATR/H検算を分ける。ATR上限/値幅capは使わない"),
        (["I01"],["m03"],rules[1:],"現足除外の前20平均二つの準備だけ","同場過去21終値・現在含め22足/j21最速。B0へ平均準備を先に課さず、0は準備可"),
        (["I01"],["m03"],rules[2:],"実方向dM/dP両正T/両負R・残WAIT","元CをFraction化、dM=Mp-Mpp/dP=Cj-Mp。実side保持しT順行/R反転へ分類、0/不一致は見送り"),
        (["P01","P04","I01"],["m03"],rules,"診断のみ：実体長/平均距離/前端距離/3x3","未約定含む要求と仮約定分母を区別、負距離を丸めず位置を250余地gateへ戻さない"),
        (["P01","P04","I03","I01"],["m03"],rules,"同場隣接二足・j確定時観測/keystrict","p.end=j.start/index隣接・両confirm>=end・p.key<j.key。45のj.end>p.confirm条件は加えない"),
        (["B01"],["m03"],rules,"j時計/残60分/遅延30秒・純13非label","j30分間引き、全採否後deepcopy。重なる二足/平均窓を独立標本としない"),
        (["B01"],["tick"],rules,"正常BBO市場+1秒/TTL30・一pending一建玉","新二足Pは技術/時間/保有で不採用でも保存。pivot/used/後続監視/確認待ちを追加しない"),
        (["I09","C06","E02"],["tick"],rules,"XF現在返済利益円-122>0strict/名目entry床","入口jATR固定D/MFE-D/非緩和/pending凍結。0/5/10は同約定ストレス、起動参照5固定"),
        (["E01","B01"],["tick"],rules,"新直接125/250・同経済的新規/役割差/実回収","同時刻/価格/ATR/Dをrole抜きで対応。役割だけの変更を出口効果とせず、旧control/旧label無し"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,"結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]} for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """二実体母集団/平均の準備と分類/役割対応/回収を小表へ分ける。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは保存値の要約。原窓/指標/先着を再計算しない。
    """
    path = proof_path(study,work,"対応診断.json")
    data = G.read_json(path)
    text = "## 新二実体母集団と平均の準備・値\n\n"+G.link(path,output)+"が正本。旧245AND/旧label/旧運用controlはなく、全原P→MACD/ATR/時間→平均準備→符号分類を分ける。後足待ちやpivot消費はない。\n"
    text += G.table(["期間","全足/原P","共通M/M時間遅延可","先着対象外","B2 T/R/WAIT/未準備","B0/B1/B2要求"],[[PERIOD_NAMES[r["期間"]],f"{r['数値足数']}/{r['原P数']}",f"{r['共通M準備数']}/{r['M時間遅延可数']}",r["先着対象外P数"],"/".join(str(r["B2分類別"].get(k,0)) for k in ("T","R","WAIT","未準備")),"/".join(str(r[p+"純入口数"]) for p in POLICIES)] for r in data["価格と平均の段階"]])
    text += G.table(["比較/期間","保持要求/仮約定・250率","除外要求/仮約定・250率","純追加","保持内役割変更/除外分類"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],*[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口","除外入口")],r["新規追加入口数"],str(r["保持内役割変更数"])+"/"+G.describe(r["除外分類別"])] for r in data["入口追加比較"]])
    text += "## 同じB1内の進行×位置と日夜・買売\n\n実方向dM/dP正・0・負3×3は準備済みB1を分割するshadow集計。別運用や閾値を追加しない。B0/B1反転からB2順行への名称差だけを利益に帰属しない。\n"
    text += G.table(["期間","実方向dM/dP","分類","要求/仮約定","250/全仮約定・率"],[[PERIOD_NAMES[r["期間"]],f"{r['実方向平均進行']}/{r['実方向終値位置']}",r["分類"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["B1の進行と位置区分"]])
    text += G.table(["期間/日夜/方向","全原P","B0/B1/B2要求","B2 T/R/WAIT/未準備"],[[PERIOD_NAMES[r["期間"]]+"/"+r["日夜"]+"/"+r["方向"],r["原P数"],"/".join(str(r[p+"純入口数"]) for p in POLICIES),"/".join(str(r["B2分類別"].get(k,0)) for k in ("T","R","WAIT","未準備"))] for r in data["日夜と買売構成"]])
    text += "## 位置・実体長の診断のみ\n\n実体長と要求終値から前平均/前足実方向端までの距離は未約定を含む純要求、仮新規から平均まではその仮約定かつ平均有効だけを分母とする。各欄の件数を別記し、負距離を0へ丸めない。余地250や形状比率の新gateへ戻さない。\n"
    fields = ("前実体絶対長pt","現実体絶対長pt","要求終値から前SMA実方向距離pt","仮新規から前SMA実方向距離pt","要求終値から前足実方向端までpt")
    text += G.table(["入口/期間/役割","純要求",*[k+" 件/中央/最小/最大" for k in fields]],[[r["入口"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["純要求数"],*[str(r[k]["件数"])+"/"+"/".join(number(r[k][f]) for f in ("中央値","最小","最大")) for k in fields]] for r in data["診断専用の位置"]])
    text += "## 同経済的新規と役割対応・実参加\n\n共通は場/実side/新規key/価格/入口jATR/Dで、役割を含めない。同役割と役割だけ違う共通を分ける。純subsetでも実追加は起こり得るため今回件数を別記し、共通0の差0は対象なし。全額差=共通出口差＋右のみ額−左のみ額を費用0/5/10別に確認する。総額縮小を平均回収改善へ読み替えない。\n"
    text += G.table(["比較/期間","同P両参加/経済的共通","同役割/役割差","出口属性差","共通出口差0/5/10円","左のみ完結・0/5/10円","右のみ完結・0/5/10円","全差0/5/10円"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],f"{r['同P両実参加数']}/{r['経済的共通実新規数']}",f"{r['同役割共通数']}/{r['役割だけ違う共通数']}",r["共通出口属性差数"],"/".join(number(v["共通出口差円"]) for v in r["費用別"]),*[str(r[k]["完結取引数"])+"・"+"/".join(number(r[k][f"追加{f}pt純損益円"]) for f in (0,5,10)) for k in ("左のみ","右のみ")],"/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in data["実参加比較"]])
    text += G.table(["比較/期間","左役割→右役割","共通数","出口差0/5/10円"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],r["左役割"]+"→"+r["右役割"],r["共通数"],"/".join(number(r["共通出口差円"][str(f)]) for f in (0,5,10))] for r in data["共通新規の役割対応"]])
    text += G.table(["比較/期間","左のみの相手取扱","右のみの相手取扱"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],G.describe(r["左のみの相手取扱"]),G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
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
    """全証明後に保存値だけから三案・四役割の二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。結果なしでは生成しない。
    """
    config,report,rules,entries,values,manifest = validate(study)
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping = output/"README.md",output/"設定と結果.md"
    common,catalog = settings(rules),V4.load_catalog()
    intro = "二足の実体包みP＋実方向MACDヒスト差正をB0、前足までのSMA20二つの準備をB1、進行と現終値位置の実方向符号が両正T/両負RをB2とする新母集団。B0/B1反転・B2切替、三入口/三XF/実四役割群、版4・54手法×9尺度。旧245AND/旧label転用/旧全運用controlはない。全NK66場既使用の追加開発で、TOPIX未参照・11/5Day両商品は対象外/未開封。\n\n"
    conclusion = f"**支持付き入口70目標{report['入口70目標達成数']}/3、費用資格{report['費用資格数']}/3、採用資格{report['採用資格数']}/3。**\n\n"
    for policy in POLICIES:
        e = entries["3分_"+policy]
        conclusion += policy+"："+"、".join(PERIOD_NAMES[q]+"250先着"+G.pct(e[q]["確認率"])+"（仮約定"+str(e[q]["約定候補数"])+"件）・追加5pt平均"+number(values["3分_"+policy+"_XF"][q]["運用"]["追加5pt平均円"])+"円" for q in PERIODS[:2])+"。両期入口支持は"+("充足" if e["入口支持"] else "未達")+"。\n\n"
    for left_id,right_id in (("B0","B1"),("B1","B2")):
        for period in PERIODS[:2]:
            left,right = (values["3分_"+p+"_XF"][period]["運用"] for p in (left_id,right_id))
            conclusion += left_id+"→"+right_id+"の"+PERIOD_NAMES[period]+"追加5pt総額差"+number(right["追加5pt純損益円"]-left["追加5pt純損益円"])+"円、平均"+number(left["追加5pt平均円"])+"→"+number(right["追加5pt平均円"])+"円。総額と平均、役割名の変更を分ける。\n\n"
    model = "## 複合条件・公開時点と心理の仮説\n\ns=買+1/売−1に対しs(Cp−Op)<0、s(Cj−Oj)>0、s(Oj−Cp)<=0、s(Cj−Op)>0。始値側等号だけを許し、終値側strict。前足反対実体の打ち返しを反転と呼ぶが、長期トレンド終結の観測ではない。ヒゲ包み/実体比/CLV/20高安条件は加えない。Pならs(Cj−Cp)>0は自動で独立の勢い票ではなく、現前中心化H差sδH>0を組み合わせる。\n\np/jは同場・連続完全公開3分、p.end=j.start、index隣接、両confirm>=end、p.key<j.key。j確定時に二足を観測し、45のj.end>p.confirmを加えない。欠枠/不正/NP/局所不連続で二足/SMAを解除、完全公開窓へmissing>0を投入しない。公開key同値/後退と重複indexは拒否する。\n\nMp=mean(C[j−20..j−1])、Mpp=mean(C[j−21..j−2])、dM=Mp−Mpp、dP=Cj−Mp。元floatをFraction化し当足を除外、共通準備最速j21/現在含22足。両s差正ならT順行、両負ならR反転、0/不一致WAIT、未準備は別記。B0へ平均準備を先に課さずB1は準備だけ。実sideは保持する。dM=(Cp−C[j−21])/20には窓落ちが入り、新注文圧力とは言えない。dPは価格差でI02の割合乖離ではない。\n\nTは背景進行側の打ち返し、Rは背景と逆向きでまだ平均の反対側という心理仮説。投資家の新規/返済を直接観測せず、ローソク/MACD/SMAは同価格由来で独立三票ではない。重なる二足と共通21終値の依存を日場・30分間引きと分ける。\n\n"
    protection = "## 共通XF・費用と限界\n\nmicro1枚/10円pt/呼値5pt/片道fee11円、正常BBO新規+1秒TTL30・返済+1秒、一pending一建玉。実side×(現在返済mark−entry)pt×10円/pt−122円>0strictで起動。現在j入口ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D/最低名目entry床/非緩和/返済pending凍結。参照滑り5込み費用後0円超であり旧A5名目5pt起動ではない。同約定0/5/10費用負荷でも起動参照5固定、hard125/TP250/期限/場内完結を保持する。\n\n名目床は費用後同値/遅延後同値約定を保証しない。起動後基準赤字は追加0pt手数料込みで、起動参照5や追加5pt成績とは別尺度。仮250/実MFE250/回収/費用資格を分ける。価格時計は実受信時計ではなく、ラージBBO代理は実micro数量/キュー/部分約定を保証しない。位置や符号区分から新閾値へ戻さず、役割名変更だけの利益や旧45との差の単独因果効果とはしない。\n\n"
    audit_text,audit_paths = audits(study,work,readme)
    table = result_tables(report,entries,values)
    summary = "# 試行00046：二足の実体包みと平均進行\n\n"+intro+G.link(mapping,readme)+" / "+G.link(study/"計画.md",readme)+" / "+G.link(study/"結果.json",readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+model+protection+audit_text
    mapped = "# 試行00046：設定と結果\n\n"+intro+conclusion+G.link(V4.MASTER,mapping,"汎用表・版4コピー元")+" / "+G.link(readme,mapping)+"\n\n## 手法×時間スケール\n\n54手法×9尺度不変。P01/P04二実体、I03ヒスト差、I01前平均準備/進行/位置、I09共有ATRと固定XFを分ける。pivot/高安突破/再テスト/CLV/割合乖離/DMI/Fast/量/上位/関連指数/回帰は不使用。\n\n"+V4.matrix(catalog,mapping,common)
    mapped += "## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped += "## 三評価定義\n"+G.table(["評価","運用","入口支持","70目標","費用","採用"],[[r["評価ID"],r["候補ID"],*["充足" if values[r["候補ID"]][k] else "未達" for k in ("入口支持","70目標","費用資格","採用資格")]] for r in rules])
    mapped += table+model+protection+audits(study,work,mapping)[0]
    names = ("計画.md","条件.json","固定.json","結果.json","入力台帳.json","指標参照.json","準備参照.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources = [HERE/n for n in ("README.md","入口.py","指標.py","運用.py","検証.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs = [ROOT/n for n in ("docs/technical-analysis/指標/二足の実体包み.md","docs/technical-analysis/指標/移動平均線.md","docs/technical-analysis/指標/MACD.md","docs/technical-analysis/指標/ATR.md","docs/議論/価格時計と受信時計を分ける.md","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing = "## 閲覧・再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n正式5gzip/指標共有参照1。全27列と全P/純caseだけを新保存し、旧29全数値/原板・DMI定義blob・pivot状態を複製しない。旧入口/旧label/旧運用完全対照なし。Viewerは198資源と3代表。--prepareは全数値/P/採否だけで先着/運用/PnLなし、既存結果/部分gzipは上書き拒否。\n\n保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/実体包み/レポート.py\n```\n\n"
    if COMMON.is_file():viewing += G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers = [ROOT/"scripts"/name/"レポート.py" for name in ("回帰突破","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths = [Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版4.py",V4.BASE,V4.CATALOG,V4.MASTER,manifest,PREVIOUS/"固定.json",*[study/n for n in names if (study/n).is_file()],NUMERIC_STUDY/"条件.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths,work/"診断予定.json",ROOT/"work/次研究46の独立案.md"]
    for path,body in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全証明後に保存二MDだけを表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。市場/独立/監査/診断を起動しない。
    """
    parser=argparse.ArgumentParser(description="二足実体包みと前平均の保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK);parser.add_argument("--output",type=Path)
    args=parser.parse_args();print("\n".join(str(p) for p in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__ == "__main__":main()
