"""65監査のDI/対応episode四群・同60教師・継承接続を架空値だけで確認する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象を固有名で読み旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。本物教師・モデルは開かない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A=load(HERE/"保存検証.py","現在状態65監査人工対象")


def artificial_rows(source) -> list[dict]:
    """k旗を全0に保ち現在有効旗だけを四群に分ける架空教師を作る。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は800方向行。実価格・教師を読まない。
    """
    old=load(HERE.parent/"局面強弱の複合確認/保存検証人工.py","現在状態65の架空54材料")
    rows=old.artificial_rows(source)
    for i,row in enumerate(rows):
        pair=i//2
        d,valid,other=int(row["side"]==1),(pair//20)%2,(pair//40)%2
        t,r=(valid,other) if d else (other,valid)
        row["features"][0]=1.0 if d else -1.0
        row["features"][18:30]=[1,t,0,-1.0,0.0,0.0,1,r,0,-1.0,0.0,0.0]
        row["features"] += [0.5,0.05,1.0,-0.05,1,1]
        target=2000*other+500*row["features"][17]+row["side"]*7.5
        row.update(pnl0=target+100,pnl5=target,pnl10=target-100)
    return rows


def prepared_paths(used: list[dict]) -> dict:
    """段階・取消・有効旗を別に持つ架空状態辞書を作る。

    引数: used(list[dict])は架空使用教師。
    返り値: dictはID別60特徴と両側T/R状態。市場の価格機械を動かさない。
    """
    output={}
    for row in used:
        feature=output.setdefault(row["slot_id"],{"paths":{},"vectors":{}})
        side=str(row["side"])
        feature["vectors"][side]=row["features"]
        feature["paths"][side]={}
        for role,index in (("T",19),("R",25)):
            valid=bool(row["features"][index])
            feature["paths"][side][role]={"episode_id":role+row["slot_id"],"episode_valid":valid,"k_valid":False,
                "stage":1,"b":{"index":1,"key":[100.0,1]},"f":None,"r":None,"k":None,
                "cancel":None if valid else {"index":2,"key":[200.0,2]},"last_expired":None}
    return output


def self_test() -> dict:
    """架空回帰木と保存形式で独立監査全核を検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fit・入力読取は0。
    """
    source,_,_=A.A.helpers()
    audit=source.Audit()
    learner=load(HERE/"学習.py","現在状態65人工学習")
    recovery=load(HERE.parent/"独立追尾回収/回収集計.py","現在状態65人工固定回収")
    audit.check("同60metadata",learner.feature_metadata(A.feature_metadata(),"U0"),A.R64.feature_metadata())
    audit.check("全RULES literal",learner.RULES,A.expected_rules())
    audit.check("旧64独立60準備を直接再用",A.prepare_features is A.R64.prepare_features,True)
    # ----------------------------------------
    # 旧63の縮約事故を再発させない同じ完全接続を、架空SOURCEで確認する。
    connector=load(HERE.parent/"局面強弱の複合確認/接続補足人工.py","現在状態65完全枠の架空材料")
    thin,full,old46=connector.fixture()
    audit.check("固定50完全枠と独立46出典結合",A.S63.bind_full_slots(thin,full,old46),{full[0]["slot_id"]:full[0]})
    for kind in ("duplicate","missing","line","upper_future","upper_DI"):
        changed=deepcopy(full)
        if kind=="duplicate":changed*=2
        elif kind=="missing":changed=[]
        elif kind=="line":changed[0]["line"]+=1
        elif kind=="upper_future":changed[0]["upper"]["source"]["confirm"]+=1
        else:changed[0]["upper"]["plus_di"]+=1
        denied=False
        try:A.S63.bind_full_slots(thin,changed,old46)
        except ValueError:denied=True
        audit.check("接続拒否:"+kind,denied,True)
    rows=artificial_rows(source)
    evaluation=max(row["recovery_end_time"] for row in rows)+3600
    used,training=A.recovery_training(rows,evaluation)
    audit.check("全60canonicalとbase60",learner.prepare_rows(rows,evaluation),(used,training))
    audit.check("追加除外0と同ID",training["row_ids"],A.R64.recovery_training(rows,evaluation)[1]["row_ids"])
    for key in A.FINGERPRINT_FIELDS:
        audit.check("base60は同canonical:"+key,training["base60_fingerprints"][key],training[key])
    model=learner.fit(rows,A.feature_metadata(),"U0","U0_人工",evaluation)
    digest=hashlib.sha256((HERE/"学習.py").read_bytes()).hexdigest()
    A.check_model(model,used,training,A.feature_metadata(),"U0_人工",digest,audit)
    audit.check("四群200方向ずつ・枝内pair不要",{key:(p["direction_rows"],p["pair_unique"]) for key,p in model["training"]["partition"].items()},
        {f"D{d}_V{v}":(200,200) for d in (0,1) for v in (0,1)})
    audit.check("全k0でもepisode四群を分離",set(A.group_key(row["features"]) for row in used),{"D0_V0","D0_V1","D1_V0","D1_V1"})
    low=[node for node in model["nodes"][3:] if node["left"]!=-1 and node["path"][0]["branch"]=="left"]
    high=[node for node in model["nodes"][3:] if node["left"]!=-1 and node["path"][0]["branch"]=="right"]
    audit.check("低R旗25を除外・相手T19を保持",(25 not in A.CHILD_COLUMNS['D0'],19 in A.CHILD_COLUMNS['D0']),(True,True))
    audit.check("高T旗19を除外・相手R25を保持",(19 not in A.CHILD_COLUMNS['D1'],25 in A.CHILD_COLUMNS['D1']),(True,True))
    audit.check("相手旗が実際に子分岐",(any(n['feature']==19 for n in low),any(n['feature']==25 for n in high)),(True,True))
    audit.check("固定trend+priceで資格は同関数のまま",all(n['method_support'] for n in model['nodes'] if n['left']==-1),True)
    prepared=prepared_paths(used)
    distribution=A.state_distribution(used,prepared)
    for key,item in distribution.items():
        valid=int(key[-1])
        audit.check("出生段階でもV1:"+key,item['対象現在段階'],{'b有効' if valid else 'b取消':200})
        audit.check("有効1はk形成の意味でない:"+key,item[item['対象経路']]['kあり'],0)
        audit.check("方向枠と有効旗は同じ四群:"+key,(item['episode有効'],item['方向行'],item['unique枠']),(valid,200,200))
    absent_row=deepcopy(next(row for row in used if A.group_key(row['features'])=='D0_V0'))
    absent_prepared=deepcopy(prepared)
    absent=absent_prepared[absent_row['slot_id']]['paths'][str(absent_row['side'])]['R']
    absent.update(episode_id=None,episode_valid=False,k_valid=False,stage=0,b=None,f=None,r=None,k=None,cancel=None)
    absent_group=A.state_distribution([absent_row],absent_prepared)['D0_V0']
    audit.check("未IDと取消を別の現在段階へ",absent_group['対象現在段階'],{'未ID又は失効':1})
    audit.check("未IDは形成uniqueへ数えない",(absent_group['R']['形成ID数'],absent_group['R']['形成なし']),(0,1))
    measured={(row['slot_id'],row['side']):{'session':row['session'],'ready':True,'features':row['features'],'barrier':row,'status':'確定完結','recovery_end_time':row['recovery_end_time'],
        'operation':{'closed':[{f'pnl{fee}':float(Decimal(row[f'pnl{fee}'])) for fee in (0,5,10)}]}} for row in used}
    cal=A.expected_calibration(model,measured,evaluation)
    audit.check("全葉回収join",recovery.aggregate(model,measured,evaluation,learner),cal)
    before=deepcopy(model)
    for i in range(0,100,2):
        vectors={'1':used[i]['features'],'-1':used[i+1]['features']}
        prediction=A.predict(model,vectors)
        audit.check("全方向JSON予測",learner.predict(model,vectors),prediction)
        mirrored=A.predict(model,{'1':vectors['-1'],'-1':vectors['1']})
        audit.check("側交換で方向反転・同じ資格",(mirrored['side'],mirrored['winner_side'],mirrored['scores'],mirrored['leafs'],mirrored['eligibility']),
            (-prediction['side'],-prediction['winner_side'],{side:prediction['scores'][str(-int(side))] for side in ('1','-1')},
             {side:prediction['leafs'][str(-int(side))] for side in ('1','-1')},{side:prediction['eligibility'][str(-int(side))] for side in ('1','-1')}))
        for policy,mapped in (('U0','C0'),('U1','R0')):
            audit.check("先着最高側→回収後段:"+policy,recovery.predict(model,cal,vectors,learner,mapped),A.expected_prediction(model,cal,vectors,policy))
    audit.check("局所policy射影で旧木を変更しない",model,before)
    audit.check("全葉episode反復",sum(v['方向行'] for v in A.episode_support(model,used,prepared).values()),len(used))
    # ----------------------------------------
    # 空方向にも固定有効nodeを保ち未知二葉とする。
    empty=deepcopy(rows)
    for row in empty:row['features'][0]=-1.0
    empty_used,empty_training=A.recovery_training(empty,evaluation)
    empty_model=learner.fit(empty,A.feature_metadata(),'U0','U0_空人工',evaluation)
    A.check_model(empty_model,empty_used,empty_training,A.feature_metadata(),'U0_空人工',digest,audit)
    audit.check("空の高側にも固定内部node",(empty_model['nodes'][2]['feature'],empty_model['nodes'][2]['left']>=3,empty_model['nodes'][2]['right']>=3),(19,True,True))
    unknown={'1':deepcopy(empty_used[0]['features']),'-1':deepcopy(empty_used[1]['features'])};unknown['1'][0]=1.0
    audit.check("片側未知は次点救済しない",A.predict(empty_model,unknown)['reason'],'未学習枝WAIT')
    audit.check("片側未知の全予測同型",learner.predict(empty_model,unknown),A.predict(empty_model,unknown))
    tiny=deepcopy(used[0]['features']);tiny[0]=1e-50;tiny[25]=1;tiny[19]=0
    audit.check("微小正DIはR有効枝・raw役割は正",(A.group_key(tiny),tiny[0]>0),('D0_V1',True))
    for field in ('end_time','recovery_end_time'):
        future=deepcopy(rows);future[0][field]=evaluation
        denied=False
        try:A.recovery_training(future,evaluation)
        except ValueError:denied=True
        audit.check("教師終了等号拒否:"+field,denied,True)
    # ----------------------------------------
    # 全13継承に1追加。前巡の旧38等カウンタ漏れを再発させない。
    prior8={'測定特徴方向一致':4884,'旧評価特徴完全一致':3404,'同一新規完結一致':508,'旧18特徴完全一致':2442,
        '旧38特徴保存一致':3404,'旧46特徴保存一致':3404,'旧46射影一致':2442,'旧62特徴保存一致':3404}
    quantity={'数量出典接続足数':100,'公開完全数量足数':90,'同時刻量既知足数':70}
    inherited=A.R64.expected_counts(prior8,3404,1112,quantity)
    audit.check("全14カウンタ",A.expected_counts(inherited,3404,77,quantity),{**inherited,'同一新規完結一致':77,'旧64特徴保存一致':3404})
    for key in inherited:
        wrong=deepcopy(inherited);wrong.pop(key)
        denied=False
        try:A.expected_counts(wrong,3404,77,quantity)
        except (ValueError,KeyError):denied=True
        audit.check("継承項目欠落拒否:"+key,denied,True)
    return {'人工成功':audit.bad==0,'照合項目数':audit.count,'不一致数':audit.bad,'不一致':audit.examples,
        '人工fitAPI回数':2,'人工回帰器fit数':sum(p['fit_performed'] for m in (model,empty_model) for p in m['training']['partition'].values()),
        '本物fit':0,'実教師又はモデル読取':False,'市場戦略再生':False,'新主処理import':False}


if __name__=='__main__':
    payload=self_test()
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    raise SystemExit(0 if payload['人工成功'] else 1)
