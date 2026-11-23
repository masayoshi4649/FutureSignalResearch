"""作成した候補別CSVを再読し、元の型付き表、旧CSV、米国前後の和と照合する。"""
import csv
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = next((ROOT/'outputs').glob('00216_*'))


def records(path: Path) -> list:
    """
    機能：UTF-8のCSVを列名付きで読む。
    引数：path（Path）は候補CSV。
    返り値：listはデータ行の列。
    """
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def same(left: str, right: object) -> bool:
    """
    機能：既知数値に丸め誤差を許し、未知と文字列をそのまま照合する。
    引数：left（str）はCSV文字列、right（object）は照合先の値。
    返り値：boolは一致なら真。
    """
    if right is None:
        return left==''
    try:
        return math.isclose(float(left),float(right),rel_tol=1e-13,abs_tol=1e-7)
    except (ValueError,TypeError):
        return left==right


def main() -> None:
    """
    機能：全セル・過去日次・夜間の帯別寄与を検算し、確認件数を保存する。
    引数：なし。先に全場集計と候補別CSV作成を行う。
    返り値：None。照合を通過した件数を試行フォルダに記録する。
    """
    cells = files = historic = night_checks = 0
    for path in sorted((ROOT/'work/216閲覧').glob('*の型付き入力.json')):
        spec = json.loads(path.read_bytes())
        for key,table in spec['tables'].items():
            for candidate in sorted({r[0] for r in table['rows']}):
                dest = OUT/candidate.replace(':','_')/(spec['tableNames'][key]+'.csv')
                with dest.open(encoding='utf-8-sig',newline='') as stream:
                    rows = list(csv.reader(stream))
                expected = [table['headers']]+[r for r in table['rows'] if r[0]==candidate]
                for a,b in zip(rows,expected,strict=True):
                    assert all(same(x,y) for x,y in zip(a,b,strict=True)), (dest,a,b)
                    cells += len(a)
                files += 1
    # ----------------------------------------
    cols = ['既知利益円','既知損失円','既知収支円','確定収支円','既知累計円','確定累計円','建玉回数','未知件数','保有時間率下限']
    legacy_cols = ['利益既知寄与_円','損失絶対額既知寄与_円','収支既知寄与_円','収支確定_円','累計既知寄与_円','累計収支確定_円','建玉回数','未知件数','保有時間率下限']
    for folder in sorted(d for d in OUT.iterdir() if d.is_dir()):
        native = '専用' in folder.name
        night = 'ナイト' in folder.name
        if native:
            old = next((ROOT/'outputs').glob('00212_*/212_06*'))
        elif night:
            old = next((ROOT/'outputs').glob('00199_*/199_02*'))
        else:
            old = next((ROOT/'outputs').glob('00215_*/'+folder.name.replace('216_','215_',1)))
        for stem in (('ナイト','ナイト_米前','ナイト_米後') if night else ('デイ',)):
            earlier = records(old/(('ナイト全体' if stem=='ナイト' else stem)+'.csv'))
            today = records(folder/(stem+'.csv'))
            assert len(today)==45
            for prev,now in zip(earlier,today):
                assert now['セッション'].startswith(prev['開始日又は期間'] if native or night else prev['セッション'])
                for a,b in zip(cols,legacy_cols if native or night else cols,strict=True):
                    assert same(now[a],prev[b]),(folder,stem,now['セッション'],a,prev[b],now[a])
                historic += 1
        if night:
            full,pre,post = [records(folder/(s+'.csv')) for s in ('ナイト','ナイト_米前','ナイト_米後')]
            for r,a,b in zip(full,pre,post,strict=True):
                assert r['セッション']==a['セッション']==b['セッション']
                for col in ('既知利益円','既知損失円','既知収支円','建玉回数','未知件数','順先着件数','逆先着件数','未到達件数','不足件数'):
                    assert same(r[col],float(a[col])+float(b[col])),(folder,r['セッション'],col)
                night_checks += 1
    assert (files,cells,historic,night_checks)==(16,8832,420,90)
    result = {'CSV数':files,'全セル確認':cells,'旧日別行と照合':historic,'米前後の和を検査したナイト行':night_checks}
    (HERE/'CSVの照合.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
