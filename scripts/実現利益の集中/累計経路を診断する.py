"""固定8候補のCSVを、累計経路と短い窓の損益へ分解する読取診断。"""
from pathlib import Path
import argparse
import csv
import json

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'outputs/00174_追加禁止と両中央値の比較'


def path_metrics(rows: list) -> dict:
    """
    機能: 場末累計のDD・回復・開始来損失と5/10場窓を算出する。
    引数: rows(list[dict])は同一候補・帯の時刻順40場。
    返り値: dict。未知があれば既知寄与経路だけの診断と明示する。
    """
    cumulative=0.0;peak=0.0;peak_index=-1;worst=None;minimum=0.0;minimum_index=-1
    curves=[];water_start=None;episodes=[];negative_streak=0;max_negative_streak=0
    for i,row in enumerate(rows):
        cumulative+=float(row['収支円_既知分']);curves.append(cumulative)
        if cumulative<minimum:
            minimum=cumulative;minimum_index=i
        if cumulative<peak:
            if water_start is None:water_start=peak_index
            dd=peak-cumulative
            if worst is None or dd>worst['金額']:
                worst={'金額':dd,'ピーク位置':peak_index,'底位置':i,'ピーク日':'開始前' if peak_index<0 else rows[peak_index]['セッション日'],
                       '底日':row['セッション日'],'ピーク値':peak,'底値':cumulative}
        else:
            if water_start is not None:
                episodes.append({'開始位置':water_start,'回復位置':i,'水面下場数':i-water_start-1,'回復までの場数':i-water_start})
                water_start=None
            peak=cumulative;peak_index=i
        negative_streak=negative_streak+1 if float(row['収支円_既知分'])<0 else 0
        max_negative_streak=max(max_negative_streak,negative_streak)
    if water_start is not None:
        episodes.append({'開始位置':water_start,'回復位置':None,'水面下場数':len(rows)-1-water_start,'回復までの場数':None})
    if worst is not None:
        after=[i for i in range(worst['底位置']+1,len(rows)) if curves[i]>=worst['ピーク値']]
        recovery=after[0] if after else None
        worst.update({'回復日':None if recovery is None else rows[recovery]['セッション日'],
            'ピークから回復場数':None if recovery is None else recovery-worst['ピーク位置'],
            '底から回復場数':None if recovery is None else recovery-worst['底位置']})
    unknown=sum(int(row['金融未知件数']) for row in rows)
    windows={}
    for width in (5,10):
        exact=[];unknown_windows=0
        for start in range(len(rows)-width+1):
            part=rows[start:start+width]
            if sum(int(row['金融未知件数']) for row in part):
                unknown_windows+=1;continue
            exact.append({'開始日':part[0]['セッション日'],'終了日':part[-1]['セッション日'],
                '収支':sum(float(row['収支円_既知分']) for row in part),
                '取得':sum(int(row['取得回数']) for row in part)})
        windows[str(width)]={'確定窓数':len(exact),'未知窓数':unknown_windows,
            '赤字窓数':sum(r['収支']<0 for r in exact),'取得0窓数':sum(r['取得']==0 for r in exact),
            '最悪確定窓':min(exact,key=lambda r:r['収支']) if exact else None}
    return {'対象場数':len(rows),'取得':sum(int(row['取得回数']) for row in rows),'未知':unknown,
        '経路の意味':'全件確定の場末累計' if unknown==0 else '既知分のみの場末累計。全件DD・回復ではない。',
        '開始来最小累計':minimum,'開始来最小日':None if minimum_index<0 else rows[minimum_index]['セッション日'],
        '最大DD':worst,'最長水面下':max(episodes,key=lambda r:r['水面下場数']) if episodes else None,
        '最長赤字場連続':max_negative_streak,'窓':windows}


def main() -> None:
    """
    機能: 既存候補の三帯を同じ式で診断し、金融・CSVを変更せず保存する。
    引数: --input(Path)は候補別CSVフォルダ、--output(Path)は診断JSONの保存先。
    返り値: None。診断JSONだけを保存する。新しい採否閾値は設定しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,default=OUTPUT)
    parser.add_argument('--output',type=Path,default=ROOT/'work/安定性の再診断/累計経路の比較.json')
    args=parser.parse_args();result=[]
    for folder in sorted(p for p in args.input.resolve().iterdir() if p.is_dir()):
        bands={}
        for band in ('デイ','ナイト_米前','ナイト_米後'):
            with (folder/(band+'.csv')).open(encoding='utf-8-sig',newline='') as stream:
                rows=sorted(list(csv.DictReader(stream)),key=lambda row:row['セッション日'])
            bands[band]=path_metrics(rows)
        result.append({'候補':folder.name,'帯':bands})
    target=args.output.resolve();target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    selected=[r for r in result if r['候補'] in ('173_前48_J026','174_全期_J002')]
    print(json.dumps(selected,ensure_ascii=False))


if __name__=='__main__':
    main()
