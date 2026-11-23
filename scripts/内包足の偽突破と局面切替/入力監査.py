"""旧73の可視SOURCEから内包偽突破と直接技法条件を独立再構成する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math


SOURCE = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
SIDES = ("1", "-1")
SLOT_FIELDS = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")
VALUE_INDICES = {"F01":0,"F02":1,"F03":2,"F15":14,"F48":47,"F52":51}
REASONS = {"有効":"直近900秒の終値確認が有効","未確認":"終値確認待ち","確認期限切れ":"B後3足の終値確認なし",
    "確認窓外":"終値確認が直近900秒窓外","否定":"確認後に偽突破端を終値で否定"}


# ----------------------------------------
def finite(value: object) -> bool:
    """boolと非有限値を除いた保存数値を判定する。

    引数: value(object)は保存値。
    返り値: boolは有限int/floatだけ真。
    """
    return type(value) in (int,float) and math.isfinite(value)


def fingerprint(value: object) -> str:
    """可視SOURCEだけをJSONの型・配列順も保つ指紋へ写す。

    引数: value(object)は有限JSON。
    返り値: strはsort_keys/UTF-8のSHA256。未来suffixを含めない。
    """
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()


def same(left: object, right: object) -> bool:
    """出典と純判断をJSONの型・値で比較する。

    引数: left/right(object)はJSON構造。
    返り値: boolはkey順だけを無視した同値。
    """
    return json.dumps(left,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)==json.dumps(right,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)


def projection(row: dict, session: str) -> dict:
    """可視と確認できた一足の型・公開・OHLCを検査してSOURCE13へ写す。

    引数: row(dict)は一足、session(str)は当場。
    返り値: dictは元数値型を保持したSOURCE13。未知・不正を補完しない。
    """
    if not isinstance(row,dict) or any(key not in row for key in SOURCE):
        raise ValueError("監査SOURCE13の項目不足")
    if row["session"]!=session or type(row["minutes"]) is not int or row["minutes"]!=3:
        raise ValueError("監査SOURCEの場又は足幅差")
    if any(type(row[key]) is not int or row[key]<0 for key in ("index","confirm_line","missing")) or type(row["publish"]) is not bool:
        raise ValueError("監査SOURCE番号・公開型不正")
    if any(not finite(row[key]) for key in ("start","end","confirm")):
        raise ValueError("監査SOURCE時計不正")
    if not row["publish"] or row["missing"] or row["end"]-row["start"]!=180 or row["confirm"]<row["end"]:
        raise ValueError("監査可視SOURCEが非公開・欠枠・不完全")
    if any(not finite(row[key]) or row[key]<=0 for key in ("open","high","low","close")):
        raise ValueError("監査SOURCE価格不正")
    if row["low"]>min(row["open"],row["close"]) or row["high"]<max(row["open"],row["close"]) or row["low"]>row["high"]:
        raise ValueError("監査SOURCE高安関係不正")
    return {key:deepcopy(row[key]) for key in SOURCE}


def visible(slot: dict, feature: dict) -> list[dict]:
    """未来suffixを検査前に除外し、既存の参照10足と反応5足を独立に選ぶ。

    引数: slot(dict)は元定時、feature(dict)は旧73Q特徴。
    返り値: list[dict]は15完全公開足。可視な不正/不足/不連続は例外。
    """
    if not isinstance(slot.get("session"),str) or not slot["session"] or not isinstance(slot.get("slot_id"),str) or not slot["slot_id"]:
        raise ValueError("監査slot識別不正")
    if not finite(slot.get("scheduled")) or not finite(slot.get("time")) or slot["time"]<slot["scheduled"] or type(slot.get("line")) is not int or slot["line"]<0:
        raise ValueError("監査slot時計不正")
    try:
        history=feature["base"]["history"]
        current=feature["base"]["base"]["sources"]["current"]
        groups=(history["reference_sources"],history["reaction_sources"])
    except (KeyError,TypeError) as exc:
        raise ValueError("監査旧73のSOURCE履歴不足") from exc
    result=[]
    for material,count in zip(groups,(10,5)):
        if not isinstance(material,list):
            raise ValueError("監査SOURCE配列不正")
        selected=[]
        for raw in material:
            if not isinstance(raw,dict) or raw.get("session")!=slot["session"] or not finite(raw.get("end")):
                raise ValueError("監査SOURCE終端が不明")
            if raw["end"]>slot["scheduled"]:
                continue
            if not finite(raw.get("confirm")) or type(raw.get("confirm_line")) is not int or raw["confirm_line"]<0:
                raise ValueError("監査SOURCE公開key不明")
            if (raw["confirm"],raw["confirm_line"])>(slot["time"],slot["line"]):
                continue
            selected.append(projection(raw,slot["session"]))
        if len(selected)!=count:
            raise ValueError("監査可視参照10/反応5足の不足又は重複")
        result.extend(selected)
    for a,b in zip(result,result[1:]):
        if b["index"]!=a["index"]+1 or b["start"]!=a["end"] or (b["confirm"],b["confirm_line"])<=(a["confirm"],a["confirm_line"]):
            raise ValueError("監査SOURCE15の番号・足境界・公開順不連続")
    if not same(result[-1],projection(current,slot["session"])):
        raise ValueError("監査SOURCE15末尾と旧current差")
    return result


# ----------------------------------------
def candidates_for(slot: dict, bars: list[dict]) -> list[dict]:
    """全内包三足を列挙し、方向正規化高安から最初確認/最初否定を別算する。

    引数: slot(dict)は予定/判断key、bars(list[dict])は可視15足。
    返り値: list[dict]は全候補と5状態。新Iや市場結果を呼ばない。
    """
    found=[]
    for b_position in range(2,len(bars)):
        a,inside,b=bars[b_position-2:b_position+1]
        if not (Fraction(str(inside["high"]))<Fraction(str(a["high"])) and Fraction(str(inside["low"]))>Fraction(str(a["low"]))):
            continue
        for side in (1,-1):
            values={}
            for name,row in (("I",inside),("B",b)):
                endpoints=[side*Fraction(str(row[key])) for key in ("high","low")]
                values[name]=max(endpoints),min(endpoints)
            if not (values["B"][0]<values["I"][0] and values["B"][1]<values["I"][1]):
                continue
            later=bars[b_position+1:b_position+4]
            confirmed=next((row for row in later if side*Fraction(str(row["close"]))>values["I"][0]),None)
            denial=None
            if confirmed is not None:
                denial=next((row for row in bars[b_position+1:] if row["index"]>confirmed["index"] and side*Fraction(str(row["close"]))<=values["B"][1]),None)
            observed=len(later)
            if confirmed is None:
                status="確認期限切れ" if observed==3 else "未確認"
            elif denial is not None:
                status="否定"
            elif not slot["scheduled"]-900<confirmed["end"]<=slot["scheduled"]:
                status="確認窓外"
            else:
                status="有効"
            identity="|".join((slot["session"],"H",f"{side:+d}",str(b["index"]),float(b["confirm"]).hex(),str(b["confirm_line"])))
            found.append({"id":identity,"side":side,"A":deepcopy(a),"I":deepcopy(inside),"B":deepcopy(b),"C":deepcopy(confirmed),
                "denial":deepcopy(denial),"status":status,"reason":REASONS[status],"confirmation_observed":observed,
                "confirmation_complete":observed==3,"confirmation_deadline_end":b["end"]+540,
                "confirmation_line":inside["high"] if side==1 else inside["low"],"denial_line":b["low"] if side==1 else b["high"]})
    return found


def qualify(side: int, selected: dict | None, feature: dict) -> dict:
    """新形と保存技法の明示順序から一方向の資格を独立判定する。

    引数: side(int)は実方向、selected(dict|None)は有効形、feature(dict)は保存64特徴。
    返り値: dictは資格/役割/理由/六値とraw背景。float32やepsilonを使わない。
    """
    values={key:None for key in VALUE_INDICES}
    values["raw_background_direction"]=None
    if not feature["ready"]:
        return {"qualified":False,"role":"待機","reason":"旧73特徴が未準備","values":values}
    vector=feature["vectors"][str(side)]
    values.update({key:vector[index] for key,index in VALUE_INDICES.items()})
    values["raw_background_direction"]=feature["background_direction"]
    role="待機" if feature["background_direction"]==0 or values["F01"]==0 else "順行" if side==feature["background_direction"] else "反転"
    failures=[(selected is None,"有効な終値確認なし"),(feature["background_direction"]==0,"上位DI同値"),(values["F01"]==0,"DI優勢差同値"),
        (values["F02"]<0,"FastK中央差が逆向き"),(values["F03"]<=0,"FastK進行が非正")]
    if values["F01"]<0:
        failures.extend(((values["F52"]!=1,"ADX変化が未知"),(values["F48"]>=0,"ADXが非減速"),(values["F15"]<=0,"15分終値位置が非正")))
    reason=next((text for failed,text in failures if failed),None)
    return {"qualified":reason is None,"role":role,"reason":reason or ("順行条件適格" if values["F01"]>0 else "反転条件適格"),"values":values}


def derive(slot: dict, feature73: dict) -> dict:
    """保存特徴と公開足だけから全H形・二方向資格・優先方向を構成する。

    引数: slot(dict)は旧Q0定時、feature73(dict)は同slotの保存特徴。
    返り値: dictは入力観測全文。新I/主/Engine・教師・成績を参照しない。
    """
    if not isinstance(feature73,dict) or type(feature73.get("ready")) is not bool:
        raise ValueError("監査旧73特徴schema不正")
    if feature73["ready"]:
        vectors=feature73.get("vectors")
        if not isinstance(vectors,dict) or set(vectors)!=set(SIDES):
            raise ValueError("監査旧73の両方向vector不正")
        if any(not isinstance(vector,list) or len(vector)!=64 or any(not finite(vector[index]) for index in VALUE_INDICES.values()) for vector in vectors.values()):
            raise ValueError("監査旧73vector長又は直接6値の有限性不正")
        background=feature73.get("background_direction")
        if type(background) is not int or background not in (-1,0,1):
            raise ValueError("監査raw背景方向不正")
        for side in (1,-1):
            vector=vectors[str(side)]
            if vector[51] not in (0,1) or vector[0] and (1 if vector[0]>0 else -1)!=side*background:
                raise ValueError("監査ADXmask又はF01/raw方向不一致")
        if any(vectors["1"][index]!=-vectors["-1"][index] for index in (0,1,2,14)) or any(vectors["1"][index]!=vectors["-1"][index] for index in (47,51)):
            raise ValueError("監査方向値・不変値の鏡像差")
    rows=visible(slot,feature73) if feature73["ready"] else []
    candidates=candidates_for(slot,rows) if rows else []
    selected={}
    for text in SIDES:
        active=[c for c in candidates if c["side"]==int(text) and c["status"]=="有効"]
        selected[text]=deepcopy(max(active,key=lambda c:(c["C"]["index"],c["B"]["index"]))) if active else None
    qualifications={text:qualify(int(text),selected[text],feature73) for text in SIDES}
    qualified=[int(text) for text in SIDES if qualifications[text]["qualified"]]
    if len(qualified)>1:
        raise ValueError("監査両方向の新H候補が同時適格")
    side=qualified[0] if qualified else 0
    reason="旧73特徴が未準備" if not feature73["ready"] else "内包偽突破の複合候補" if side else "有効な終値確認なし" if all(c is None for c in selected.values()) else "内包偽突破の複合条件不適格"
    return {"ready":feature73["ready"],"reason":reason,"source_count":len(rows),"source_sha256":fingerprint(rows) if rows else None,
        "candidates":candidates,"selected":selected,"qualifications":qualifications,"side":side,"role":qualifications[str(side)]["role"] if side else "待機"}


def choose(slot: dict, obs: dict, policy: str) -> dict:
    """新H方向を優先するか保存Q0へfallbackし、純入力14項目だけを返す。

    引数: slot(dict)は旧Q0、obs(dict)は独立観測、policy(str)はI0/H0/H1。
    返り値: dictはSLOT_FIELDS10＋session/policy/origin/pattern_id。引数を変更しない。
    """
    if policy not in ("I0","H0","H1"):
        raise ValueError("監査政策はI0/H0/H1")
    if any(key not in slot for key in SLOT_FIELDS) or type(slot["ready"]) is not bool or obs.get("ready") is not slot["ready"] or type(slot["side"]) is not int or slot["side"] not in (-1,0,1):
        raise ValueError("監査元Q0と観測の準備・方向不一致")
    if not isinstance(slot.get("session"),str) or not slot["session"] or not isinstance(slot.get("slot_id"),str) or not slot["slot_id"] or not finite(slot.get("scheduled")) or not finite(slot.get("time")) or slot["time"]<slot["scheduled"]:
        raise ValueError("監査純選択の識別・時計不正")
    if not (type(slot.get("line")) is int and slot["line"]>=0 or not slot["ready"] and slot.get("line") is None):
        raise ValueError("監査純選択の原行不正")
    result={key:deepcopy(slot[key]) for key in SLOT_FIELDS}
    result.update(session=slot["session"],policy=policy,origin="保存Q0",pattern_id=None)
    if policy!="I0" and obs["side"]:
        side=obs["side"]
        if type(side) is not int or side not in (-1,1) or not obs["ready"] or not obs["qualifications"][str(side)]["qualified"] or obs["selected"][str(side)] is None or obs["selected"][str(side)]["status"]!="有効" or obs["qualifications"][str(side)]["role"]!=obs["role"]:
            raise ValueError("監査H採用の方向・有効形・資格不整合")
        result.update(side=side,role=obs["role"],reason="内包偽突破の複合候補",origin="内包偽突破",pattern_id=obs["selected"][str(side)]["id"])
    return result


# ----------------------------------------
def fixture(b_index: int = 12, confirmation: int | None = 13, background: int = 1) -> tuple:
    """市場と無関係な15公開足と技法値を人工検査へ用意する。

    引数: b_index(int)は偽突破足、confirmation(int|None)は確認足、background(int)はraw背景。
    返り値: tuple[dict,dict]は旧純slot/旧73特徴。成績・原板・教師を読まない。
    """
    session="2026-01-01_Day"
    bars=[{"session":session,"index":i,"minutes":3,"start":i*180,"end":(i+1)*180,"confirm":(i+1)*180+3,
        "confirm_line":100+i,"publish":True,"missing":0,"open":100.,"high":110.,"low":90.,"close":100.} for i in range(15)]
    bars[b_index-1].update(high=108.,low=92.)
    bars[b_index].update(high=107.,low=90.)
    if confirmation is not None:
        bars[confirmation].update(high=111.,low=98.,close=109.)
    feature={"ready":True,"reason":"","vectors":{text:[0.]*64 for text in SIDES},"background_direction":background,
        "atr":20.,"D":20.,"base":{"history":{"reference_sources":deepcopy(bars[:10]),"reaction_sources":deepcopy(bars[10:])},
        "base":{"sources":{"current":deepcopy(bars[-1])}}}}
    for side in (1,-1):
        vector=feature["vectors"][str(side)]
        vector[0],vector[1],vector[2],vector[14],vector[47],vector[51]=side*background*.2,side*.1,side*.01,side*.3,-.02,1.
    slot={"session":session,"slot_id":"人工74枠","scheduled":2700.,"time":2703.,"line":114,"side":0,"role":"待機",
        "atr":20.,"D":20.,"reason":"旧人工WAIT","ready":True}
    return slot,feature


def self_test() -> dict:
    """架空SOURCEだけで境界と鏡像を手計算し、人工時だけ新I全文へ照合する。

    引数: なし。
    返り値: dictは人工成功/照合件数。本物入力・市場再生・fitは実施しない。
    """
    import importlib.util
    from pathlib import Path
    import sys
    target=Path(__file__).with_name("入力.py")
    spec=importlib.util.spec_from_file_location("74入力監査の人工時だけの出力側",target)
    main=importlib.util.module_from_spec(spec);sys.modules[spec.name]=main;spec.loader.exec_module(main)
    count=tests=0

    def compare(left: object,right: object,where: str = "全文") -> None:
        """人工返却を型と全leaf値まで比較する。

        引数: left/right(object)は独立/出力側のJSON、where(str)は箇所。
        返り値: None。差はAssertionErrorで止める。
        """
        nonlocal count
        count+=1
        if type(left) is not type(right):
            raise AssertionError((where,"型",type(left),type(right)))
        if isinstance(left,dict):
            assert set(left)==set(right),(where,"keys")
            for key in left:compare(left[key],right[key],where+"."+str(key))
        elif isinstance(left,(list,tuple)):
            assert len(left)==len(right),(where,"長さ")
            for i,(a,b) in enumerate(zip(left,right)):compare(a,b,where+"."+str(i))
        else:
            assert left==right,(where,left,right)

    def check(slot: dict,feature: dict,rejected: bool = False) -> dict | None:
        """一人工材料の例外/全文/純選択/非改変を確認する。

        引数: slot/feature(dict)は架空材料、rejected(bool)は両者例外の期待。
        返り値: dict|Noneは独立観測。新Iは出力側としてこの人工内でだけ呼ぶ。
        """
        nonlocal tests
        snapshot=json.dumps([slot,feature],sort_keys=True,ensure_ascii=False,allow_nan=True)
        values=[]
        for function in (derive,main.extract):
            try:values.append((None,function(slot,feature)))
            except ValueError as exc:values.append((type(exc),None))
        if rejected:
            compare([x[0] is ValueError for x in values],[True,True],"入力拒否")
        else:
            assert values[0][0] is None and values[1][0] is None,values
            compare(values[0][1],values[1][1])
            for policy in ("I0","H0","H1"):
                compare(choose(slot,values[0][1],policy),main.choose(slot,values[1][1],policy),"純選択"+policy)
            compare({k:v for k,v in choose(slot,values[0][1],"H0").items() if k!="policy"},
                {k:v for k,v in choose(slot,values[0][1],"H1").items() if k!="policy"},"H純同値")
            compare(tuple(choose(slot,values[0][1],"I0")),(*SLOT_FIELDS,"session","policy","origin","pattern_id"),"14項目")
        compare(json.dumps([slot,feature],sort_keys=True,ensure_ascii=False,allow_nan=True),snapshot,"引数非改変")
        tests+=1
        return values[0][1]

    def change_bar(feature: dict,number: int,**values) -> None:
        """人工の一足と必要なcurrentを同時に置き換える。

        引数: feature(dict)は架空特徴、number(int)は足番号、values(dict)は変更OHLC/時計。
        返り値: None。市場の出典を扱わない。
        """
        rows=feature["base"]["history"]["reference_sources"]+feature["base"]["history"]["reaction_sources"]
        rows[number].update(values)
        if number==14:feature["base"]["base"]["sources"]["current"].update(values)

    def pair_value(feature: dict,index: int,value: float,invariant: bool = False) -> None:
        """人工の方向値又は方向不変値を鏡像を保って変更する。

        引数: feature(dict)は架空特徴、index(int)/value(float)は列/値、invariant(bool)は両側同値か。
        返り値: None。
        """
        feature["vectors"]["1"][index]=value
        feature["vectors"]["-1"][index]=value if invariant else -value

    slot,feature=fixture();base=check(slot,feature)
    compare((base["side"],base["role"],base["selected"]["1"]["C"]["index"]),(1,"順行",13),"手計算T")
    compare(base["selected"]["1"]["id"],"2026-01-01_Day|H|+1|12|"+float(2343).hex()+"|112","出生ID")
    mirrored=deepcopy(feature)
    bars=mirrored["base"]["history"]["reference_sources"]+mirrored["base"]["history"]["reaction_sources"]+[mirrored["base"]["base"]["sources"]["current"]]
    for bar in bars:
        a={key:bar[key] for key in ("open","high","low","close")}
        bar.update({key:1000-a[{"high":"low","low":"high"}.get(key,key)] for key in a})
    mirrored["vectors"]={"1":deepcopy(feature["vectors"]["-1"]),"-1":deepcopy(feature["vectors"]["1"])};mirrored["background_direction"]=-1
    reverse=check(slot,mirrored)
    compare((reverse["side"],reverse["role"],reverse["selected"]["-1"]["C"]["index"]),(-1,"順行",13),"鏡像")
    a,f=fixture(background=-1);obs=check(a,f);compare((obs["side"],obs["role"]),(1,"反転"),"手計算R")
    # ----------------------------------------
    # strict形成/確認、無効化等号、最初Cと満了を区別する。
    for changes in ((11,{"high":110.}),(11,{"low":90.}),(12,{"high":108.})):
        a,f=fixture();change_bar(f,changes[0],**changes[1]);obs=check(a,f)
        compare(obs["candidates"],[],"形成等号なし")
    a,f=fixture();change_bar(f,13,close=108.);obs=check(a,f)
    compare((obs["candidates"][0]["status"],obs["candidates"][0]["confirmation_complete"]),("未確認",False),"確認等号なし")
    a,f=fixture(11,None);obs=check(a,f)
    compare((obs["candidates"][0]["status"],obs["candidates"][0]["confirmation_observed"]),("確認期限切れ",3),"確認期限")
    a,f=fixture(14,None);obs=check(a,f)
    compare((obs["candidates"][0]["status"],obs["candidates"][0]["confirmation_observed"]),("未確認",0),"B同足不可")
    a,f=fixture(8,9);obs=check(a,f);compare(obs["candidates"][0]["status"],"確認窓外","900秒下端等号")
    a,f=fixture(9,10);obs=check(a,f);compare(obs["candidates"][0]["status"],"有効","900秒窓内")
    a,f=fixture();change_bar(f,14,close=90.);obs=check(a,f)
    compare((obs["candidates"][0]["status"],obs["candidates"][0]["denial"]["index"]),("否定",14),"否定同値")
    a,f=fixture(8,9);change_bar(f,10,close=90.);obs=check(a,f);compare(obs["candidates"][0]["status"],"否定","窓外より否定優先")
    a,f=fixture(9,10);change_bar(f,11,close=90.);change_bar(f,12,high=112.,close=111.);obs=check(a,f)
    compare((obs["candidates"][0]["C"]["index"],obs["candidates"][0]["denial"]["index"],obs["candidates"][0]["status"]),(10,11,"否定"),"最初C/否定固定と非復活")
    # ----------------------------------------
    # 同じCへ至る二候補は新しいBを選び、Cを後で差し替えない。
    a,f=fixture(7,10)
    change_bar(f,6,high=115.,low=85.);change_bar(f,5,high=120.,low=80.);change_bar(f,7,high=114.,low=84.)
    change_bar(f,8,high=112.,low=86.);change_bar(f,9,high=111.,low=85.);change_bar(f,10,high=118.,low=90.,close=116.)
    obs=check(a,f);compare((obs["selected"]["1"]["B"]["index"],obs["selected"]["1"]["C"]["index"]),(9,10),"同CのB優先")
    # ----------------------------------------
    # ゲートを一つずつ変え、順序/厳密0/配置roleを検査する。
    for index,value,invariant,reason in ((1,-.1,False,"FastK中央差が逆向き"),(2,0.,False,"FastK進行が非正"),(0,0.,False,"DI優勢差同値")):
        a,f=fixture();pair_value(f,index,value,invariant);obs=check(a,f)
        compare(obs["qualifications"]["1"]["reason"],reason,"順行ゲート")
    a,f=fixture();pair_value(f,1,0.);obs=check(a,f);compare(obs["side"],1,"Fast中央等号可")
    a,f=fixture();f["background_direction"]=0;pair_value(f,0,0.);obs=check(a,f);compare(obs["qualifications"]["1"]["reason"],"上位DI同値","raw0優先")
    for index,value,invariant,reason in ((51,0.,True,"ADX変化が未知"),(47,0.,True,"ADXが非減速"),(14,0.,False,"15分終値位置が非正")):
        a,f=fixture(background=-1);pair_value(f,index,value,invariant);obs=check(a,f)
        compare(obs["qualifications"]["1"]["reason"],reason,"反転ゲート")
    # ----------------------------------------
    # 当時可視prefixだけをhashし、未来の壊れた価格を検査/候補へ入れない。
    for future in ({"session":slot["session"],"end":2880.,"confirm":None,"high":float("nan")},
            {"session":slot["session"],"end":2700.,"confirm":3000.,"confirm_line":999,"low":None}):
        a,f=fixture();f["base"]["history"]["reaction_sources"].append(future);obs=check(a,f);compare(obs,base,"未来suffix不変")
    for field,value in (("publish",False),("missing",1),("index",99),("start",2521.),("confirm",2699.)):
        a,f=fixture();change_bar(f,14,**{field:value});check(a,f,True)
    a,f=fixture();f["vectors"]["-1"][2]=.01;check(a,f,True)
    a,f=fixture();pair_value(f,51,.5,True);check(a,f,True)
    a,f=fixture();pair_value(f,0,-.2);check(a,f,True)
    a,f=fixture();f={"ready":False};a.update(ready=False,line=None,side=0,atr=None,D=None);obs=check(a,f)
    compare((obs["ready"],obs["source_count"],obs["source_sha256"]),(False,0,None),"未準備placeholder")
    return {"人工成功":True,"照合項目数":count,"不一致数":0,"不一致":[],"テスト件数":tests,
        "本物入力読取":False,"新I正式期待値呼出":False,"本物fit":0,"市場戦略再生":False}


if __name__=="__main__":
    print(json.dumps(self_test(),ensure_ascii=False,allow_nan=False))
