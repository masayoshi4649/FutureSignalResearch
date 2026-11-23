"""64監査の数量基準・完全枠接続・二種類の木を架空材料だけで検査する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象と固定純補助を固有名で読み込む。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読取結果。本物教師・モデルを開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE/"保存検証.py", "量価格64監査人工対象")


def quantity_fixture(count: int = 15) -> tuple:
    """同じindexを持つ架空Day場と完全Q11を作る。

    引数: count(int)は時系列場数。
    返り値: tuple[list,dict]は価格場と数量。原板を参照しない。
    """
    sessions, quantities = [], {}
    for i in range(count):
        name, begin = f"人工{i:02d}_Day", 1000.0+i*10000
        rows = []
        for j in range(4):
            start, end = begin+180*j, begin+180*(j+1)
            rows.append({"session":name,"index":j,"minutes":3,"start":start,"end":end,"confirm":end+1,
                "confirm_line":j*10+5,"publish":True,"missing":0,"open":1000.+j,"high":1004.+j,"low":998.+j,"close":1002.+j,
                "quantity":{"観測差分量":float(i+1),"数量基準完全":True,"直前数量足数":0,"直前数量合計":None,
                    "直前数量平均":None,"RVOL":None,"数量準備済":False,"最終採用数量時計":end-2,
                    "最終採用価格時計":end-1,"最終採用原行":j*10+1,"数量不完全理由":[]}})
        quantities[name] = rows
        sessions.append({"session":name,"contract":("人工限月",),"begin":begin,"end":begin+800,
            "frames3":[{k:v for k,v in row.items() if k not in ("session","quantity")} for row in rows]})
    return sessions, quantities


def quantity_checks(feature, audit) -> None:
    """過去窓・時計・出典・0量・反射・共同maskを独立算術と明示値で検査する。

    引数: feature(ModuleType)は新F、audit(Audit)は照合記録。
    返り値: None。実入力の読取や市場再生は行わない。
    """
    sessions, quantity = quantity_fixture()
    original = deepcopy((sessions,quantity))
    independent = A.quantity_context(sessions,quantity)
    audit.check("全数量文脈の独立一致",feature.build_context(sessions,quantity),independent)
    audit.check("数量入力非改変",(sessions,quantity),original)
    row = independent[sessions[-1]["session"]][1]
    audit.check("先選び10場",row["baseline"]["window_sessions"],[item["session"] for item in sessions[4:14]])
    audit.check("10量5..14の平均9.5",(row["baseline"]["count"],row["baseline"]["mean"],row["rvol"]),(10,9.5,30/19))
    audit.check("未来追加前prefix不変",A.quantity_context(sessions[:10],{k:quantity[k] for k in list(quantity)[:10]}),
        {k:independent[k] for k in list(quantity)[:10]})
    # ----------------------------------------
    # 最近10場中4標本なら、それ以前の完全場があっても伸ばさない。
    missing = deepcopy(quantity)
    for item in sessions[4:10]:
        missing[item["session"]][1]["quantity"]["数量基準完全"] = False
    limited = A.quantity_context(sessions,missing)
    audit.check("欠測で過去窓を延長しない",feature.build_context(sessions,missing),limited)
    audit.check("10候補中4標本は未知",(limited[sessions[-1]["session"]][1]["baseline"]["count"],limited[sessions[-1]["session"]][1]["rvol"]),(4,None))
    zeros = deepcopy(quantity)
    for rows in zeros.values():
        for r in rows:r["quantity"]["観測差分量"] = 0.0
    zerocontext=A.quantity_context(sessions,zeros)
    audit.check("基準0は未知",feature.build_context(sessions,zeros),zerocontext)
    audit.check("完全0量は標本に数える",zerocontext[sessions[-1]["session"]][1]["baseline"]["count"],10)
    onlyzero = deepcopy(quantity)
    onlyzero[sessions[-1]["session"]][1]["quantity"]["観測差分量"]=0.0
    zeroresult=A.quantity_context(sessions,onlyzero)
    audit.check("正基準の当量0は既知",zeroresult[sessions[-1]["session"]][1]["rvol"],0.0)
    # ----------------------------------------
    # 同種・同限月だけを使い、開始時刻以前の未来公開を許さない。
    separated=deepcopy(sessions)
    separated[-1]["contract"]=("別限月",)
    audit.check("別限月は基準無し",A.quantity_context(separated,quantity)[separated[-1]["session"]][1]["baseline"]["count"],0)
    night=deepcopy(sessions)
    nightq=deepcopy(quantity)
    oldname,newname=night[-1]["session"],"人工14_Night"
    night[-1]["session"]=newname
    nightq[newname]=nightq.pop(oldname)
    for r in nightq[newname]:r["session"]=newname
    audit.check("夜と昼は別標本",A.quantity_context(night,nightq)[newname][1]["baseline"]["count"],0)
    for kind in ("end_equal","confirm_equal","quantity_clock","source_duplicate","source_changed"):
        items,q=deepcopy((sessions,quantity))
        if kind=="end_equal":items[0]["end"]=items[1]["begin"]
        elif kind=="confirm_equal":
            r=q[items[0]["session"]][1]
            r["confirm"]=items[5]["begin"]
            items[0]["frames3"][1]["confirm"]=r["confirm"]
        elif kind=="quantity_clock":q[items[0]["session"]][1]["quantity"]["最終採用数量時計"]+=1000
        elif kind=="source_duplicate":q[items[0]["session"]][1]["index"]=0
        else:q[items[0]["session"]][1]["close"]+=1
        rejected=False
        try:A.quantity_context(items,q)
        except ValueError:rejected=True
        audit.check("量基準拒否:"+kind,rejected,True)
    # ----------------------------------------
    # 接続だけの人工SOURCE/Q11。重複・欠落・型を独立joinで拒否する。
    raw=[{"場":r["session"],**{k:r[k] for k in A.A.SOURCE if k!="session"},"数量参照":r["quantity"]} for rows in quantity.values() for r in rows]
    audit.check("数量SOURCE型値結合",A.join_quantity(sessions,raw),quantity)
    for kind in ("duplicate","missing","type","q_schema"):
        changed=deepcopy(raw)
        if kind=="duplicate":changed.append(deepcopy(changed[0]))
        elif kind=="missing":changed.pop()
        elif kind=="type":changed[0]["index"]=0.0
        else:changed[0]["数量参照"].pop("RVOL")
        rejected=False
        try:A.join_quantity(sessions,changed)
        except ValueError:rejected=True
        audit.check("SOURCE結合拒否:"+kind,rejected,True)
    slot={"session":sessions[-1]["session"],"scheduled":sessions[-1]["begin"]+720,"time":sessions[-1]["begin"]+722,"line":100}
    rows=independent[slot["session"]]
    refs={name:{"index":i,"key":[rows[i]["confirm"],rows[i]["confirm_line"]]} for name,i in (("b",1),("r",2))}
    vectors={"1":[0.0]*54,"-1":[0.0]*54}
    vectors["1"][0],vectors["-1"][0]=1.0,-1.0
    old={"ready":True,"reason":"","vectors":vectors,"atr":20.0,"付随":{"保持":True},
        "paths":{side:{role:deepcopy(refs) for role in ("T","R")} for side in ("1","-1")}}
    expected=A.expected_feature(old,slot,rows)
    audit.check("対応b/rペア全文",feature.extend(slot,old,rows),expected)
    audit.check("旧54完全射影",A.control_projection(expected),old)
    audit.check("正DIはT/非正DIはR",[expected["quantity"][side]["role"] for side in ("1","-1")],["T","R"])
    audit.check("b進行の明示算術",expected["vectors"]["1"][55],1/20)
    larger=deepcopy(old);larger["atr"]=40.0
    audit.check("現在ATRのみ再尺度化",A.expected_feature(larger,slot,rows)["vectors"]["1"][55],1/40)
    audit.check("数量比は現在ATRで変化しない",A.expected_feature(larger,slot,rows)["vectors"]["1"][54],expected["vectors"]["1"][54])
    none=deepcopy(old)
    for side in ("1","-1"):
        for role in ("T","R"):none["paths"][side][role]["r"]=None
    audit.check("r無しは既知0mask0",feature.extend(slot,none,rows),A.expected_feature(none,slot,rows))
    bad=deepcopy(rows);bad[1]["rvol"]=None;bad[1]["quantity_reason"]="数量基準不完全又は不正"
    unknown=A.expected_feature(old,slot,bad)
    audit.check("不完全qは両値0共同mask0",unknown["vectors"]["1"][54:],[0.0,0.0,expected["vectors"]["1"][56],expected["vectors"]["1"][57],0,1])
    audit.check("未知でも診断価格は保持",unknown["quantity"]["1"]["b"]["progress"],1/20)
    no_previous=[r for r in rows if r["index"]!=0]
    audit.check("前足欠落は共同未知",feature.extend(slot,old,no_previous),A.expected_feature(old,slot,no_previous))
    hidden=deepcopy(old);hidden["paths"]["1"]["T"]["b"]["key"][1]+=1
    rejected=False
    try:A.expected_feature(hidden,slot,rows)
    except ValueError:rejected=True
    audit.check("段階参照改竄拒否",rejected,True)
    reflected=deepcopy(rows)
    for r in reflected:r.update(open=3000-r["open"],high=3000-r["low"],low=3000-r["high"],close=3000-r["close"])
    mirrored=deepcopy(old)
    mirrored["vectors"]={"1":deepcopy(old["vectors"]["-1"]),"-1":deepcopy(old["vectors"]["1"])}
    reflected_value=A.expected_feature(mirrored,slot,reflected)
    audit.check("売買反射で量価格6は側交換同値",reflected_value["vectors"]["-1"][54:],expected["vectors"]["1"][54:])
    unready={"ready":False,"reason":"旧未準備","vectors":{"1":[],"-1":[]}}
    audit.check("追加量で旧未準備を救済しない",feature.extend({},unready,[]),A.expected_feature(unready,{},[]))


def self_test() -> dict:
    """架空教師と数量だけで全監査の純計算を検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fitと教師読取は0。
    """
    source,_,_=A.A.helpers()
    audit=source.Audit()
    learner=load(HERE/"学習.py","量価格64人工学習")
    feature=load(HERE/"特徴.py","量価格64人工特徴")
    recovery=load(HERE.parent/"独立追尾回収/回収集計.py","量価格64人工固定回収")
    old=load(HERE.parent/"局面強弱の複合確認/保存検証人工.py","量価格64架空54材料")
    audit.check("数量price metadata60",feature.FEATURES,A.feature_metadata())
    audit.check("規約の全literal",learner.RULES,A.expected_rules())
    quantity_checks(feature,audit)
    connection=load(HERE.parent/"局面強弱の複合確認/接続補足人工.py","量価格64完全枠接続人工").self_test()
    audit.check("完全50枠・旧46出典接続21項目",(connection["人工成功"],connection["不一致数"]),(True,0))
    audit.count += connection["照合項目数"]

    rows=old.artificial_rows(source)
    for index,row in enumerate(rows):
        x=(index//2%20)/20
        row["features"] += [x,.05,1.0,-.05,1,1]
        target=x*4000-1000
        row.update(pnl0=target+100,pnl5=target,pnl10=target-100)
    evaluation=max(row["recovery_end_time"] for row in rows)+3600
    models=[]
    for policy,count in (("B0",54),("Q0",60)):
        material=[{**row,"features":row["features"][:count]} for row in rows]
        used,training=A.recovery_training(material,evaluation,count)
        audit.check("教師canonicalとbase54:"+policy,learner.prepare_rows(material,evaluation,count),(used,training))
        model=learner.fit(material,A.feature_metadata(count),policy,policy+"_人工",evaluation)
        digest=hashlib.sha256((HERE/"学習.py").read_bytes()).hexdigest()
        A.check_model(model,used,training,A.feature_metadata(count),policy+"_人工",digest,audit)
        models.append(model)
        audit.check("二方向群は枝内pair不要:"+policy,{key:(p["direction_rows"],p["pair_unique"]) for key,p in model["training"]["partition"].items()},{"D0":(400,400),"D1":(400,400)})
        measured={(r["slot_id"],r["side"]):{"session":r["session"],"ready":True,"features":r["features"],"barrier":r,"status":"確定完結", "recovery_end_time":r["recovery_end_time"],
            "operation":{"closed":[{f"pnl{f}":float(Decimal(r[f"pnl{f}"])) for f in (0,5,10)}]}} for r in used}
        calibration=A.expected_calibration(model,measured,evaluation)
        audit.check("全葉回収:"+policy,recovery.aggregate(model,measured,evaluation,learner),calibration)
        for i in range(0,80,2):
            vectors={"1":used[i]["features"],"-1":used[i+1]["features"]}
            audit.check("両方向予測:"+policy,learner.predict(model,vectors),A.predict(model,vectors))
            for p,mapped in ((policy,"C0"),(policy[0]+"1","R0")):
                audit.check("最高側後段回収:"+p,recovery.predict(model,calibration,vectors,learner,mapped),A.expected_prediction(model,calibration,vectors,p))
        empty=deepcopy(material)
        for row in empty:row["features"][0]=-1.0
        used_empty,training_empty=A.recovery_training(empty,evaluation,count)
        model_empty=learner.fit(empty,A.feature_metadata(count),policy,policy+"_空人工",evaluation)
        A.check_model(model_empty,used_empty,training_empty,A.feature_metadata(count),policy+"_空人工",digest,audit)
        models.append(model_empty)
        pair={"1":deepcopy(used_empty[0]["features"]),"-1":deepcopy(used_empty[1]["features"])}
        pair["1"][0]=1.0
        audit.check("未知片側で救済無し:"+policy,A.predict(model_empty,pair)["reason"],"未学習枝WAIT")
    audit.check("Qでは新量数値が実際に分岐候補",any(n["feature"]==54 for n in models[2]["nodes"] if n["left"]!=-1),True)
    # ----------------------------------------
    # 固定DIだけのprice無し経路は旧資格を構造的に自動充足しない。
    node={"unique_slots":100,"days":10,"sessions":20,"score":.7}
    audit.check("trend単独は複数技法不成立",A.A.eligibility(node,[{"family":"trend"}])["method_support"],False)
    for kind in ("q_negative","mask_bool","mask_zero_value","infinite"):
        invalid=deepcopy(rows[0]["features"])
        if kind=="q_negative":invalid[54]=-1
        elif kind=="mask_bool":invalid[58]=True
        elif kind=="mask_zero_value":invalid[58],invalid[54]=0,1
        else:invalid[55]=float("inf")
        rejected=False
        try:A.float32(invalid)
        except ValueError:rejected=True
        audit.check("新量域の拒否:"+kind,rejected,True)
    tiny=deepcopy(rows[0]["features"]);tiny[0]=1e-50
    audit.check("float32零化はR投影・rawは正",(A.group_key(tiny),tiny[0]>0),("D0",True))
    inherited={"測定特徴方向一致":4884,"旧評価特徴完全一致":3404,"同一新規完結一致":508,"旧18特徴完全一致":2442,
        "旧38特徴保存一致":3404,"旧46特徴保存一致":3404,"旧46射影一致":2442,"旧62特徴保存一致":3404}
    quantity_counts={"数量出典接続足数":100,"公開完全数量足数":90,"同時刻量既知足数":70}
    audit.check("全旧カウンタを継承",A.expected_counts(inherited,3404,100,quantity_counts),{**inherited,"同一新規完結一致":100,"旧54射影一致":2442,"旧63特徴保存一致":3404,**quantity_counts})
    for missing in inherited:
        wrong=deepcopy(inherited);wrong.pop(missing)
        rejected=False
        try:A.expected_counts(wrong,3404,100,quantity_counts)
        except ValueError:rejected=True
        audit.check("継承項目欠落拒否:"+missing,rejected,True)
    return {"人工成功":audit.bad==0,"照合項目数":audit.count,"不一致数":audit.bad,"不一致":audit.examples,
        "完全枠接続人工":connection,"人工fitAPI回数":4,"人工回帰器fit数":sum(p["fit_performed"] for model in models for p in model["training"]["partition"].values()),
        "本物fit":0,"実教師又はモデル読取":False,"市場戦略再生":False,"新主処理import":False}


if __name__=="__main__":
    proof=self_test()
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    raise SystemExit(0 if proof["人工成功"] else 1)
