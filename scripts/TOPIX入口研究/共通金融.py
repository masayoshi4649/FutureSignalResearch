"""試行番号を文字列置換せず、固定純出生から同一IFDを再生する。"""
from pathlib import Path
from collections import defaultdict
import argparse
import gzip
import hashlib
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/183TOPIX'))
import 金融を比較する as F
M=F.M


def read(path: Path) -> object:
    """
    機能: JSON又はgzip JSONを読む。
    引数: path(Path)。
    返り値: objectは解析値。
    """
    raw=path.read_bytes();return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


# ----------------------------------------
def ref(path: Path) -> dict:
    """
    機能: 参照位置・容量・内容指紋を返す。
    引数: path(Path)。
    返り値: dictは絶対path・bytes・SHA256。
    """
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    return {'path':str(path.resolve()),'bytes':path.stat().st_size,'sha256':digest}


# ----------------------------------------
def entries(include_extra: bool=False) -> list:
    """
    機能: 恒久原順8列の81場又は83場を、既存Routeと同じ形式で返す。
    引数: include_extra(bool)は194の追加2場を含めるか。
    返り値: list[dict]は固定場順。全ファイルSHAを確認する。
    """
    manifest=read(ROOT/'inputs/TOPIX原順8列_20260921_20261116/台帳.json');result=[]
    for row in manifest['entries']:
        path=ROOT/row['path'];assert ref(path)['sha256']==row['sha256']
        result.append({'session':row['session'],'cache_absolute':str(path),'sha256_cache':row['sha256']})
    assert len(result)==81 and result[80]['session']=='2026-11-16_Day'
    if include_extra:
        added=read(ROOT/'inputs/00194_20261116夜と1117昼の固定適用入力/原順8列/入力台帳.json')['entries']
        for row in added:
            if row['symbol']=='TOPIX':
                assert ref(Path(row['cache_absolute']))['sha256']==row['sha256_cache'];result.append(row)
        assert [r['session'] for r in result[81:]]==['2026-11-16_Night','2026-11-17_Day']
    return result


# ----------------------------------------
def replay(rows: list, identifiers: list[str], resources: list) -> list:
    """
    機能: 任意候補数の固定出生を予約・保有一枠と従来Routeで再生する。
    引数: rows(list[dict])はsignals/widths/origins、identifiers(list[str])は各候補ID、resources(list[dict])は場順。
    返り値: list[dict]は全場を保持する候補別金融pack。幅・方向を再設定しない。
    """
    assert identifiers and len(identifiers)==len(set(identifiers))
    meta=F.sessions(resources);scene_names=[r['scene'] for r in meta]
    assert len(scene_names)==len(set(scene_names)) and all(meta[i]['start']<meta[i+1]['start'] for i in range(len(meta)-1))
    by=defaultdict(list);previous={}
    for row in rows:
        scene=row['session'];assert scene in scene_names
        assert all(len(row[k])==len(identifiers) for k in ('signals','widths','origins'))
        if scene in previous:assert previous[scene][0]<=row['time'] and previous[scene][1]<row['line']
        previous[scene]=(row['time'],row['line']);by[scene].append(row)
    packs=[]
    for identity in identifiers:
        pack=F.empty(identity,meta);pack['ledger']['origin']=[];packs.append(pack)
    for resource in resources:
        route=M.Route(resource);cache={}
        for ci,pack in enumerate(packs):
            busy=-math.inf;pending=False;counts={'純成立':0,'保有棄却':0,'予約棄却':0,'取得':0,'失効':0}
            for row in by[resource['session']]:
                side=row['signals'][ci];assert side in (-1,0,1)
                if not side:continue
                counts['純成立']+=1
                if row['time']<=busy:counts['予約棄却' if pending else '保有棄却']+=1;continue
                width=row['widths'][ci];assert width is not None and math.isfinite(width) and width>0
                key=(row['time'],row['line'],side,width)
                if key not in cache:cache[key]=route.cell(*key)
                cell=cache[key]
                if cell is None:counts['失効']+=1;busy=min(row['time']+30,route.force);pending=True;continue
                counts['取得']+=1;F.append(pack,dict(cell,origin=row['origins'][ci]));pending=False
                busy=route.end if cell['unknown'] else cell['exit_time']
            pack['diagnostics'].append({'scene':resource['session'],**counts})
    return packs


# ----------------------------------------
def periods(pack: dict) -> dict:
    """
    機能: 旧81又は全83の期間分母を候補数から独立して定義する。
    引数: pack(dict)は場を省略していない固定金融。
    返り値: dict[str,list[str]]は既定の期間。候補数でスライスを置換しない。
    """
    scenes=[s['scene'] for s in pack['sessions']];assert len(scenes) in (81,83)
    assert scenes[80]=='2026-11-16_Day'
    result={'全80':scenes[:80],'前48':scenes[:48],'後25':scenes[48:73],'追加7':scenes[73:80],'本日1':scenes[80:81]}
    assert {k:len(v) for k,v in result.items()}=={'全80':80,'前48':48,'後25':25,'追加7':7,'本日1':1}
    if len(scenes)==83:
        assert scenes[81:]==['2026-11-16_Night','2026-11-17_Day'];result.update(旧81=scenes[:81],追加2=scenes[81:])
    return result


# ----------------------------------------
def main() -> None:
    """
    機能: 明示した候補名・IDテンプレートで新規計算し、任意の既存結果へ同体照合する。
    引数: CLI --condition/--births/--output/--id-template、任意--extra/--expected-dir/--expected-metrics。
    返り値: None。既存出力先・固定開始票へ上書きしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--condition',type=Path,required=True);parser.add_argument('--births',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--id-template',required=True);parser.add_argument('--extra',action='store_true')
    parser.add_argument('--expected-dir',type=Path);parser.add_argument('--expected-metrics',type=Path);args=parser.parse_args()
    assert not args.output.exists();condition=read(args.condition);names=condition['候補'];assert len(names)==condition['規模']
    assert args.id_template.count('{name}')==1
    assert all(M.sha(ROOT/p)==digest for p,digest in condition['Source'].items())
    assert ref(args.births)['sha256']==condition['純入口SHA']
    resources=entries(args.extra);rows=read(args.births);ids=[args.id_template.format(name=name) for name in names]
    args.output.mkdir(parents=True)
    start={'条件':ref(args.condition),'純出生':ref(args.births),'Source':ref(Path(__file__)),
           '金融部':ref(Path(F.__file__)),'Route':ref(Path(M.__file__)),'到達木':ref(ROOT/'scripts/入口分析/分析.py'),
           '集計':ref(Path(F.A.__file__)),'場数':len(resources),'候補数':len(ids),'ID':ids,
           '原順入力':[{'session':r['session'],'ref':ref(Path(r['cache_absolute']))} for r in resources]}
    M.save(args.output/'金融開始前固定.json',start)
    packs=replay(rows,ids,resources);states=[];checks=[]
    for pack in packs:
        if args.expected_dir:
            expected=read(args.expected_dir/(pack['id']+'.json.gz'));assert pack==expected,pack['id'];checks.append(pack['id'])
        M.save(args.output/'金融正本'/(pack['id']+'.json.gz'),pack)
        states.append(F.A.evaluate_pack(pack,periods(pack)))
    if args.expected_metrics:
        expected=read(args.expected_metrics);assert states==expected['metrics']
    M.save(args.output/'安定性.json.gz',{'metrics':states})
    M.save(args.output/'検算.json',{'成功':True,'母体一致':checks,'全集計同体':bool(args.expected_metrics),'全場分母':len(resources),'候補数':len(ids)})
    assert all(M.sha(ROOT/p)==digest for p,digest in condition['Source'].items())
    print(json.dumps({'成功':True,'口座':len(ids),'取得':sum(len(p['ledger']['known']) for p in packs),'全台帳同体':len(checks),'全集計同体':bool(args.expected_metrics)},ensure_ascii=False))


# ----------------------------------------
if __name__=='__main__':main()
