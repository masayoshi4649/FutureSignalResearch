"""VWAP純入力の当時可用性と起算差だけを集計する。損益は読まない。"""
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import gzip
import hashlib
import json
import statistics

ROOT=Path(__file__).resolve().parents[2];DEST=ROOT/'inputs/00204_両指数の配信VWAP純入力'


def read(path: Path) -> object:
    """
    機能: 純入力JSONを読む。
    引数: path(Path)。
    返り値: objectはJSON内容。
    """
    with gzip.open(path,'rt',encoding='utf-8') if path.suffix=='.gz' else path.open(encoding='utf-8') as f:return json.load(f)


def summary(values: list) -> dict:
    """
    機能: 純価格・時計差の分布を要約する。
    引数: values(list[float])。
    返り値: dictは件数、最小、中央値、最大。
    """
    return {'件数':len(values),'最小':min(values),'中央値':statistics.median(values),'最大':max(values)} if values else {'件数':0}


def main() -> None:
    """
    機能: 場別と三帯別の可用性・数量時計・起算・差分を保存する。
    引数: なし。
    返り値: None。金融・最適化・候補採否を行わない。
    """
    done=read(DEST/'完了_TOPIX.json');groups=defaultdict(Counter);lags=defaultdict(list);diffs=defaultdict(list)
    allraw=Counter();scenes=[];maxdiff=None;native_size=0;ny=ZoneInfo('America/New_York');jst=ZoneInfo('Asia/Tokyo')
    for p in done['scenes']:
        scene=p['session'];phase='Day' if scene.endswith('_Day') else 'Night';path=DEST/'TOPIX'/(scene+'.json.gz')
        data=read(path);native_size+=path.stat().st_size;allraw.update(p['全原行診断']);counts=Counter();base_lines=set();origins=set()
        for r in data['rows']:
            local=datetime.fromtimestamp(r['time'],ny);part=phase if phase=='Day' else ('PRE' if (local.hour,local.minute)<(9,30) else 'POST')
            origin=datetime.fromtimestamp(r['opening_time'],jst).isoformat();origins.add(origin)
            for group in ('全体',phase,part) if phase=='Night' else ('全体',phase):
                c=groups[group];c['q0']+=1;c['native既知']+=int(r['native_known']);c['比率不整合']+=int(not r['ratio_ok'])
                c['当場差分既知']+=int(r['session_delta'] is not None);c['起算時計が場前']+=int(origin[:10]<scene[:10] or (phase=='Day' and origin[11:19]<'08:45:00'))
                lag=r['time']-r['volume_time'];lags[group].append(lag);c['数量時計同秒']+=int(lag==0);c['数量時計60秒超']+=int(lag>60)
                c['起算観測区間0']+=int(r['epoch']==0)
                if r['session_delta'] is not None:diffs[group].append(abs(r['native']-r['session_delta']))
            counts['q0']+=1;counts['native既知']+=int(r['native_known']);counts['当場差分既知']+=int(r['session_delta'] is not None)
            if r['base']:base_lines.add(r['base']['line'])
            if r['session_delta'] is not None:
                d=abs(r['native']-r['session_delta'])
                if maxdiff is None or d>maxdiff['差']:maxdiff={'session':scene,'line':r['line'],'time':r['time'],'native':r['native'],'当場差分':r['session_delta'],'差':d}
        groups[phase]['場']+=1;groups[phase]['当場差分がある場']+=int(counts['当場差分既知']>0)
        scenes.append({'session':scene,**counts,'接頭基準原行':sorted(base_lines),'始値時計':sorted(origins),'原板区間変更':p['全原行診断'].get('区間変更',0)})
    out={'金融未使用':True,'q0入力容量':native_size,'場数':len(scenes),'全原行':dict(allraw),
        '帯別':{k:{**v,'数量時計遅れ秒':summary(lags[k]),'nativeと当場差分の絶対差pt':summary(diffs[k])} for k,v in groups.items()},
        '差分最大例':maxdiff,'scenes':scenes,'SourceSHA':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    path=DEST/'TOPIX可用性集計.json';body=(json.dumps(out,ensure_ascii=False,indent=2)+'\n').encode()
    if path.exists():assert path.read_bytes()==body
    else:path.write_bytes(body)
    print(json.dumps({k:v for k,v in out.items() if k!='scenes'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
