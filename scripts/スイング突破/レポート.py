"""新スイング突破とDI/Fast三案を、保存証明と版4の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00045_確定スイング突破と方向優勢"
WORK = ROOT/"work/スイング突破/00045"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/確定スイング突破へ方向優勢とFastを加えた比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES, ROLES = ("C0","C1","C2"), ("順行","反転")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
SPEC = importlib.util.spec_from_file_location("スイング45の固定41表示補助",ROOT/"scripts/回帰突破/レポート.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
G,P,F,number = BASE.G,BASE.P,BASE.F,BASE.number
VSPEC = importlib.util.spec_from_file_location("スイング45の独立版4表",ROOT/"scripts/レポート/カタログ版4.py")
V4 = importlib.util.module_from_spec(VSPEC)
sys.modules[VSPEC.name] = V4
VSPEC.loader.exec_module(V4)


PREVIOUS = ROOT/"study/00044_TOPIX方向とNK再テスト"

def definitions(config: dict) -> list[dict]:
    """三つの切替候補を、準備と値の三評価へ対応する。

    引数: config(dict)は45条件。
    返り値: list[dict]はR0〜R2。実T/Rは別役割として保持する。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略":p,"出口ID":"XF"} for p in POLICIES]:
        raise ValueError("三切替入口/三XF以外")
    return [{"評価ID":"R"+str(i),"候補ID":cid,"入口":{"入口ID":"3分_"+p,"戦略":p,"時間足分":3,"名称":p,"役割":"切替","複合本命":True},"出口":{"出口ID":"XF"}} for i,(p,cid) in enumerate(zip(POLICIES,CANDIDATES))]

def validate(study: Path) -> tuple:
    """新スイング母集団/三切替/六役割・支持費用・指標参照と固定を確認する。

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
            raise ValueError("集合切替/出口定義差")
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
    roles=report["役割別入口評価"]
    if [(r["入口ID"],r["役割"]) for r in roles] != [("3分_"+p,role) for p in POLICIES for role in ROLES]:
        raise ValueError("三案×二実役割の六群差")
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
    for name,title in (("合成検証.json","人工確定極値/初cross消費/公開時点/鏡像/境界/非PnLguard"),("独立監査.json","新case集計/六役割/Decimal会計/全資源"),("状態独立確認.json","原8列/新極値と消費/DI二経路/Fast/全採否/全直接先着"),("追尾独立確認.json","三XF全保有/現在費用起動/名目床/最初返済要求"),("対応診断.json","保存価格状態/Fast準備と値/実参加と回収"),("Viewer照合.json","三運用の代表Viewer")):
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
    definition=prepared["DMI数値定義"];dp=ROOT/definition["パス"]
    if G.sha(dp) != definition["圧縮SHA256参考"] or any(d["DMI数値定義"] != definition for d in (independent,proofs["状態独立確認.json"],proofs["追尾独立確認.json"],proofs["独立監査.json"])):raise ValueError("DMI4列正本定義の版join差")
    preserved=study/"DMI数値定義.jsonl.gz"
    if preserved.is_file() and G.sha(preserved) != G.sha(dp):raise ValueError("DMI正式保全/work差")
    paths.extend((main,ip,dp));paths.extend([preserved] if preserved.is_file() else [])
    rows.extend((["固定前主準備・全極値/監視/初P/DI/Fast/三採否","66場・非損益",66,G.link(main,output)],["固定前独立・原OHLC/DI二経路/Fast/消費/全採否","一致/合格",number(independent["照合項目数"]),G.link(ip,output)],["DMI正本小型定義・場/index/plus_di/minus_diだけ","独立生値の数値検算と分離",definition["行数"],G.link(preserved if preserved.is_file() else dp,output)]))
    references=ref["参照"].values() if isinstance(ref["参照"],dict) else ref["参照"]
    if ref.get("大準備複製",False) is not False:raise ValueError("主準備は軽量参照のみ")
    for item in references:
        path=ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:raise ValueError("準備軽量参照差")
        paths.append(path)
    path=proof_path(study,work,"会計人工接続.json");artificial=G.read_json(path)
    if artificial["全件一致"] is not True or artificial["不一致数"] != 0 or any(G.sha(ROOT/n) != h for n,h in artificial["コードSHA256"].items()):raise ValueError("会計人工未完/版差")
    rows.append(["会計人工・三案買売実役割12経路/空群API","主最終人工と別",number(artificial["照合項目数"]),G.link(path,output)]);paths.append(path)
    text="## 検査の状態\n\n新価格母集団の全極値/監視/初cross消費/DI/Fast/全採否と全新case実方向BBO直接先着は45状態へ接続する。旧245/旧11label/旧運用の完全同値対照はなく、旧29は価格/ATR材料の共有参照だけ。全保有と最初返済要求は追尾、即時受付/Decimal/CSV/全198資源は財務へ分ける。DI正本4列定義を使う全内容hashと独立生floatの限定許容/準備・DI優勢符号/全採否strict、旧ATR正本strictコピーと独立再算表現/D整数、Fast Fraction差strictを別保証にする。生float全SHA同一とは主張せず、未定義の差件数を0としない。\n"
    for key in ("検証範囲","厳密範囲","数値許容"):
        if independent.get(key):text+=key+"："+G.cell(independent[key]).rstrip("。")+"。\n"
    summary={k:v for k,v in independent.items() if any(s in k for s in ("表現差","最大絶対差","厳密不一致","判断不一致","生数値SHA","独立生全指標SHA")) and not isinstance(v,list)}
    if summary:text+="数値検算の保存要約："+G.describe(summary)+"。\n"
    return text+G.table(["範囲","明示合否","件/項目","正本"],rows),paths


def result_tables(report: dict, entries: dict, values: dict) -> str:
    """混合全体と六役割群の先着・支持、実費用を分けて表示する。

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
    text="## 三入口・三XFと六役割群\n\n主先着率は期限/観測不足を含む全仮約定が分母、未約定は別記。新要求j時計を30分間引きの主にする。集合は切替、実Tは順行/実Rは反転。混合率の変化を両役割の改善や片役割支持へ代用しない。\n"
    text+=G.table(["入口","期間","純要求","仮約定","250/全仮約定・率","125/期限/不足/未約定","j30分間引き250/仮約定・率"],erows)
    text+=G.table(["運用","期間","実完結","基準観測円","追加5pt観測円","追加10pt観測円","追加5pt平均円","注意場","基準確定円"],orows)
    text+="入口支持は学習60仮約定/6日/10場・選択20/3/5。70は両期主率/間引き率70%・間引き件数20/10。費用支持は学習20完結/6日/10場/買売各5・選択10/3/6/各3と品質注意0、追加5pt後両期黒字。採用は入口70と費用資格の両方。以下の役割支持/70は学習＋条件選択の両期判定の再掲で、後続2場単独が支持条件を満たす意味ではない。\n"
    return text+G.table(["入口","実役割","期間","要求/仮約定","250/仮約定・率","j間引き250/仮約定・率","日/場","両期役割支持","両期役割70"],rrows)

def settings(rules: list[dict]) -> list[dict]:
    """新価格構造/DI/Fastと固定XFを版4の役割別セルへ対応する。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は11設定。旧245/ADX/上位/量を採用扱いにしない。
    """
    groups=[
        (["P02","P03"],["m03"],rules,"左右2確定極値/最新2高2安のD・T/R/WAIT","左strict右同値可、pまでのpivotだけ。各2未満Noneと同値混在0を分け、役割だけで出口を変えない"),
        (["P07"],["m03"],rules,"初終値cross：Cp<=R<Cj/売鏡像・一回消費","j.end>p.confirm/keystrict、当j新pivotは判断後登録。技術/時間/保有不採用でも(side,pivotID)consume、lateはP/消費なし"),
        (["I08"],["m03"],rules,"DI14実方向優勢>0strict・ADX不使用","14差分seedで15足初DI・同契約carry。TR0None、DM0/0かつTR正は方向0不採用。DI正本定義と独立生値を分離"),
        (["I09"],["m03"],rules,"旧29現在jATR有限正・同じ入口D","価格/ATRは共有材料、旧MACD/RSI/量等の数値を持ち込まない"),
        (["I07"],["m03"],rules[1:],"Fast14/3当場準備だけ・最速16公開足","14HLC生K+連続K3、14幅0はK3だけclear。C0へ準備を先に課さない、差0は準備可"),
        (["I07"],["m03"],rules[2:],"実side*(rawK-FastD)>0strict・0不採用","元OHLC Fraction差、80/20/交差/前符号ANDなし。価格構造/DIとの複合効果で単独Fast効果ではない"),
        (["P02","P03","P07","I07"],["m03"],rules,"診断のみ：消費/出生時点/古さ/日夜/T-R/Fast区分","古さ・構成を新閾値へ戻さず、raw消費と実占有を分ける。C0/C1同値も観測として扱う"),
        (["B01"],["m03"],rules,"j時計/残60分/遅延30秒/純13非label","j30分間引き、全採否後deepcopy。旧11転用や中心価格への遡り新規なし"),
        (["B01"],["tick"],rules,"正常BBO市場+1秒/TTL30・一pending一建玉","技術の消費とportfolio抑止は別で、抑止を後の空き時刻へ延期しない"),
        (["I09","C06","E02"],["tick"],rules,"XF現在返済利益円−122>0strict/名目entry床","現在j入口ATR固定D/MFE-D/非緩和/pending凍結。0/5/10は同約定ストレス、起動参照5固定"),
        (["E01","B01"],["tick"],rules,"新直接125/250・厳密共通出口/実参加/回収","全新case実方向を直接検算。旧control無し、仮250/実MFE/回収/費用資格を分ける"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,"結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]} for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """保存価格機械とFast準備/値、実回収を小表へ分ける。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは保存値だけの要約。極値/DI/Fast/先着を再計算しない。
    """
    path=proof_path(study,work,"対応診断.json");data=G.read_json(path)
    text="## 新価格状態・初cross消費と三入口\n\n"+G.link(path,output)+"が正本。旧245AND/旧label/旧運用controlはない。rawの(side,pivotID)初消費と、実一建玉/pendingの抑止を別機械とする。j以前pまでの極値だけを使い、j新pivotは判断後。late足はP/消費なしで履歴を進める。\n"
    text+=G.table(["期間","全足/極値/初P","局所解除/時点外/再cross抑止","T/R/WAIT","構造未準備/先着対象外","C0/C1/C2要求","C0C1原P集合同値"],[[PERIOD_NAMES[r["期間"]],f"{r['数値足数']}/{r['極値数']}/{r['原P数']}","/".join(str(r["動作別"].get(k,0)) for k in ("局所解除","価格観測対象外","使用済みcross見送り")),"/".join(str(r["構造別"].get(k,0)) for k in ("T","R","WAIT")),f"{r['構造準備なし']}/{r['先着対象外P数']}","/".join(str(r[p+"純入口数"]) for p in POLICIES),r["C0C1原P集合同値"]] for r in data["価格状態と新P"]])
    text+="C0/C1保存caseの識別子正規化同値は"+str(data["C0C1保存case識別正規化同値"])+"。これは観測結果で、crossからFast準備が数学的に自動成立する意味ではない。\n"
    text+=G.table(["比較/期間/役割","保持要求/仮約定・250率","除外要求/仮約定・250率","純追加","Fast準備除外"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],*[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口","除外入口")],r["新規追加入口数"],G.describe(r["準備除外理由_重複あり"])] for r in data["入口追加比較"]])
    text+="## 同じC0内のFast符号と日夜・役割構成\n\n未準備と準備後の正/0/負を分ける。符号別の別運用/新閾値を追加せず、T/Rのラベルだけの差を独立した出口効果にしない。\n"
    text+=G.table(["期間/役割","実方向Fast差","要求/仮約定","250/全仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["実方向Fast差"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["C0のFast区分"] if r["候補数"]])
    text+=G.table(["期間/役割/日夜","全原P","T/R/WAIT","C0/C1/C2要求"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"]+"/"+r["日夜"],r["原P数"],"/".join(str(r["構造別"].get(k,0)) for k in ("T","R","WAIT")),"/".join(str(r[p+"純入口数"]) for p in POLICIES)] for r in data["日夜と役割構成"] if r["原P数"]])
    text+="## 使用水準の古さ・診断のみ\n\n純要求を分母に、中心/確認からjまでの本数と公開後待ち秒を記述する。中央値等からTTL・距離上限を後付けせず、14窓/極値中心/確認/要求時計を同一視しない。\n"
    text+=G.table(["入口/期間/役割","純要求","中心→j本 中央/最大","確認→j本 中央/最大","確認公開→j秒 中央/最大"],[[r["入口"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["純要求数"],*[number(r[k]["中央値"])+"/"+number(r[k]["最大"]) for k in ("中心から判断までの本数","確認から判断までの本数","確認後の待ち秒")]] for r in data["極値の古さ"] if r["純要求数"]])
    text+="## 厳密共通出口と実参加\n\n厳密共通は場/実side/実役割/新規key/価格/入口jATR/D。極値中心一致だけを共通出口としない。純subsetでも実追加は起こり得るが、今回の件数を下表で区別する。共通0の差0は比較対象なし。全額差=共通出口差＋右のみ額−左のみ額を追加0/5/10別に確認する。総赤字縮小を平均回収改善へ読み替えない。\n"
    text+=G.table(["比較/期間/役割","同P両参加/厳密共通","共通出口属性差","共通出口差0/5/10円","左のみ完結・0/5/10円","右のみ完結・0/5/10円","全差0/5/10円"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],f"{r['同P両実参加数']}/{r['厳密共通実新規数']}",r["共通出口属性差数"],"/".join(number(v["共通出口差円"]) for v in r["費用別"]),*[str(r[k]["完結取引数"])+"・"+"/".join(number(r[k][f"追加{f}pt純損益円"]) for f in (0,5,10)) for k in ("左のみ","右のみ")],"/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in (*data["実参加比較"],*data["役割別実参加比較"])])
    text+=G.table(["比較/期間","左のみの相手取扱","右のみの相手取扱"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],G.describe(r["左のみの相手取扱"]),G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
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
    """全証明後の新母集団の保存値だけから二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。正式結果前には生成しない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    output.mkdir(parents=True,exist_ok=True);readme,mapping=output/"README.md",output/"設定と結果.md"
    common,catalog=settings(rules),V4.load_catalog()
    intro="新しい確定スイング水準の初終値crossを母集団とし、pまでの最新2高2安でT順行/R反転/WAIT、DMI実方向優勢をC0、Fast14/3準備をC1、実方向精密Fast差正をC2とする。三切替入口/三XF/六実役割群、版4・54手法×9尺度。旧245のAND/旧11label転用/旧全運用controlではない。全NK66場は既使用の追加開発で未使用実証ではなく、TOPIX未参照・11/5Day両商品は対象外/未開封。\n\n"
    conclusion=f"**支持付き入口70目標{report['入口70目標達成数']}/3、費用資格{report['費用資格数']}/3、採用資格{report['採用資格数']}/3。**\n\n"
    for p in POLICIES:
        e=entries["3分_"+p]
        conclusion+=p+"："+"、".join(PERIOD_NAMES[q]+"250先着"+G.pct(e[q]["確認率"])+"（仮約定"+str(e[q]["約定候補数"])+"件）・追加5pt平均"+number(values["3分_"+p+"_XF"][q]["運用"]["追加5pt平均円"])+"円" for q in PERIODS[:2])+"。両期入口支持は"+("充足" if e["入口支持"] else "未達")+"。\n\n"
    for period in PERIODS[:2]:
        left,right=(values[cid][period]["運用"] for cid in ("3分_C1_XF","3分_C2_XF"))
        conclusion+="C1→C2の"+PERIOD_NAMES[period]+"追加5pt総額差は"+number(right["追加5pt純損益円"]-left["追加5pt純損益円"])+"円、平均は"+number(left["追加5pt平均円"])+"→"+number(right["追加5pt平均円"])+"円。総額縮小を平均回収の改善に読み替えない。\n\n"
    text="## 価格機械・複合条件と時点\n\n左右2の中心を右2公開で確定し、左strict/右同値可。jはpまでに確定した最新R/LだけでCp<=R<Cj（売鏡像）を判定する。j.end>p.confirm/keystrict、lateはP/消費なし・履歴j投入。j右2確認の新pivotはj判断後に登録し、生誕同足へ戻さない。初(side,pivotID)crossは構造/指標/時間/保有都合で不採用でもconsume、再crossを後で救済しない。\n\n最新2高2安とも切上げD+1/切下げD−1、同値混在0、履歴不足None。s=DをT、s=−DをRと分類するが実sideを反転せず、役割名だけでXF返済を変えない。C0は価格構造＋現在DI方向優勢という複合条件で、ADX/RSI/MACD/量/上位/CMF/TOPIXを加えない。\n\nDI14は初HLC種→14差分算術seedで15足初DI、以後(13prev+x)/14、同契約carry。TRavg0はNoneでbank保持、平滑TR正/平滑DM平均が両0はDI0準備・方向不採用。Fastは同場公開14HLCと連続K3、最速16、14幅0はK3だけclearして価格14窓を保持、個々のH=L足は有効。精密FractionのrawK−FastDを使い、0不採用/80-20/交差なし。C0/C1同値なら観測結果と限定する。\n\n"
    protection="## 共通XF・費用と限界\n\nmicro1枚/倍率10円/pt/呼値5pt/片道fee11円、正常BBO新規+1秒TTL30・返済+1秒、一pending一建玉。実side×(現在返済mark−entry)pt×10円/pt−122円>0strictで起動、現在j入口ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D/最低名目entry床/非緩和/返済pending凍結。『5+0』は参照滑り5込み費用後0円超で、旧A5名目5pt起動ではない。追加0/5/10は同約定への費用負荷で起動参照5固定。hard125/TP250/期限/場内完結を保持する。\n\n名目床は費用後同値/遅延後同値約定を保証せず、仮250/実MFE250/回収と費用資格を分ける。価格時計は実受信時計ではなく、ラージBBO代理は実micro数量/キュー/部分約定を保証しない。構造・DI・Fastは同価格由来で独立票ではなく、古さ/日夜の事後区分を新閾値へ戻さない。新母集団の成績差を旧44との因果効果や、T/R命名だけの利益にしない。\n\n"
    audit_text,audit_paths=audits(study,work,readme);table=result_tables(report,entries,values)
    summary="# 試行00045：確定スイング突破と方向優勢\n\n"+intro+G.link(mapping,readme)+" / "+G.link(study/"計画.md",readme)+" / "+G.link(study/"結果.json",readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+text+protection+audit_text
    mapped="# 試行00045：設定と結果\n\n"+intro+conclusion+G.link(V4.MASTER,mapping,"汎用表・版4コピー元")+" / "+G.link(readme,mapping)+"\n\n## 手法×時間スケール\n\n54手法×9尺度不変。P02/P03/P07・I08方向/ADX不使用・I07Fast・I09共有ATRと固定XFを分ける。旧P10再テスト/量/上位/関連指数/R²は不使用。\n\n"+V4.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped+="## 三評価定義\n"+G.table(["評価","運用","入口支持","70目標","費用","採用"],[[r["評価ID"],r["候補ID"],*["充足" if values[r["候補ID"]][k] else "未達" for k in ("入口支持","70目標","費用資格","採用資格")]] for r in rules])
    mapped+=table+text+protection+audits(study,work,mapping)[0]
    names=("計画.md","条件.json","固定.json","結果.json","入力台帳.json","指標参照.json","準備参照.json","DMI数値定義.jsonl.gz","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources=[HERE/n for n in ("README.md","入口.py","指標.py","運用.py","検証.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs=[ROOT/n for n in ("docs/technical-analysis/指標/確定スイングの突破.md","docs/technical-analysis/指標/DMIとADX.md","docs/technical-analysis/指標/ストキャスティクス.md","docs/technical-analysis/指標/ATR.md","docs/議論/価格時計と受信時計を分ける.md","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing="## 閲覧・再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n新正式6gzip/指標共有参照1。旧245/旧label/旧全運用controlはなく、pivot全出典を価格状態へ一回保存しIDで辿る。DMI定義は場/index/plus_di/minus_diの4列だけを正式同byte保全し、work消去時は所定workへ復元して圧縮/展開SHAを照合する。原板/全旧数値を複製しない。Viewerは198資源と3代表。--prepareは全数値/極値/監視/P/採否だけで先着/運用/PnLなし、既存結果/部分gzipは上書き拒否。\n\n保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/スイング突破/レポート.py\n```\n\n"
    if COMMON.is_file():viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers=[ROOT/"scripts"/name/"レポート.py" for name in ("回帰突破","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths=[Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版4.py",V4.BASE,V4.CATALOG,V4.MASTER,manifest,PREVIOUS/"固定.json",*[study/n for n in names if (study/n).is_file()],NUMERIC_STUDY/"条件.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths,work/"診断予定.json",ROOT/"work/次研究45の独立案.md"]
    for path,body in ((readme,summary+viewing),(mapping,mapped)):path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全証明後に保存二MDだけを表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。市場/独立/監査/診断を起動しない。
    """
    parser=argparse.ArgumentParser(description="新スイング価格構造/DI/Fastの保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK);parser.add_argument("--output",type=Path)
    args=parser.parse_args();print("\n".join(str(p) for p in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__ == "__main__":main()
