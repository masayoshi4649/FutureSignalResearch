"""正式保存だけからNK225四案を再集計し、正本・小表・固定順位を確認する。"""
from pathlib import Path
import argparse,ast,gzip,hashlib,json,types,zipfile


def read(path):
    """
    機能: UTF-8の正式JSONを読む。
    引数: path(Path)はJSON/gzip JSON。
    返り値: objectは保存値。
    """
    data=path.read_bytes();return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def main():
    """
    機能: workを参照せず保存Sourceをメモリ読込し、四案と全28順位を照合する。
    引数: CLI --output(Path|省略)は任意の検査票保存先。
    返り値: None。既定は読取と標準出力だけ。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    trial=Path(__file__).resolve().parents[2];folder=trial/'NK225'
    archive=trial/'Source/NK225/新規Source.zip';index=read(folder/'保存索引.json')
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==index['Source']['archive']['sha256']
    module=types.ModuleType('固定安定性183');audit=types.ModuleType('固定独立検査183')
    with zipfile.ZipFile(archive) as source:
        name='work/183損失安定性/安定性183.py';exec(compile(source.read(name),name,'exec'),module.__dict__)
        name='work/183損失安定性/新候補の集計を独立検査する.py';exec(compile(source.read(name),name,'exec'),audit.__dict__)
        name='work/183単純IFD検証/比較を集計する.py';tree=ast.parse(source.read(name),filename=name)
        body=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='compact')
        namespace={'S':module};exec(compile(ast.Module(body=[body],type_ignores=[]),name,'exec'),namespace)
    states=read(folder/'全候補の損失安定性.json.gz')['rows'];states={s['id']:s for s in states}
    small=read(folder/'全候補比較.json.gz');small_rows={s['id']:s for s in small['rows']}
    base=states[small['baseline']];checks=[]
    for path in sorted((folder/'選択4候補').glob('*.json.gz')):
        pack=read(path);scenes=[s['scene'] for s in pack['sessions']]
        periods={'旧73':scenes[:73],'前48':scenes[:48],'後25':scenes[48:73],
                 '追加7':scenes[73:80],'本日1':scenes[80:],'全80':scenes[:80]}
        actual=module.evaluate_pack(pack,periods);assert actual==states[pack['id']],path
        independent=audit.verify(pack,actual)
        compact={'id':pack['id'],'全81':{b:namespace['compact'](g,base['groups'][b]) for b,g in actual['groups'].items()},
                 '期間':{p:{b:namespace['compact'](g,base['periods'][p][b]) for b,g in groups.items()} for p,groups in actual['periods'].items()}}
        assert compact==small_rows[pack['id']],path
        checks.append({'id':pack['id'],'独立属性':independent,'安定性同体':True,'小表同体':True})
    assert len(checks)==4
    for period in ('前48','全80'):
        for band in ('DAY','NIGHT'):
            ordered=sorted(states.values(),key=lambda s:(module.rank_key(s['periods'][period][band],base['periods'][period][band]),s['id']))
            assert [s['id'] for s in ordered]==small['順位'][band+'_'+period]
    result={'成功':True,'work読取なし':True,'金融新生成なし':True,'保存4案':checks,
            '独立照合計':sum(r['独立属性'] for r in checks),'全28の4順位同体':True,
            '検査SourceSHA':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    data=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(data,encoding='utf-8')
    print(data)


if __name__=='__main__':main()
