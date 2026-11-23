"""139の保存入力から規則選定・全752方向・保存観測集計を再現する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL=Path(__file__).resolve().parent.parent
ROOT=FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 保存資料の指紋を求める。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path,name: str,body: bytes) -> Path:
    """
    機能: 作業先内に同体資料を置く。
    引数: root(Path)、name(str)、body(bytes)。
    返り値: Pathは復元先。既存は同体だけ許す。
    """
    p=(root/name).resolve();assert p.is_relative_to(root);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==body
    else:
        with p.open('xb') as handle:handle.write(body)
    return p


# ----------------------------------------
def main() -> None:
    """
    機能: F1全30/F2全3源を復元し、任意に保存入力だけから再現する。
    引数: CLI --destination(Path)、--replay/--with-post(bool)。
    返り値: None。Raw/新Source/新金融観測/CSVを生成しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--replay',action='store_true');parser.add_argument('--with-post',action='store_true');args=parser.parse_args()
    destination=args.destination.resolve();assert destination.is_relative_to(ROOT/'work') and not destination.exists();destination.mkdir(parents=True)
    m=json.loads((FORMAL/'保管索引.json').read_bytes())
    groups=[('新',m['追加固定資料'])]+[('共有',x) for x in m['共有固定コード群']]
    if args.with_post:groups.append(('新',m['後発資料']))
    for kind,item in groups:
        path=FORMAL/'再現資料'/item['ZIP'] if kind=='新' else ROOT/item['保存元ZIP'];assert sha(path.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for record in item['格納源']:
                name=record['path'] if kind=='新' else record['ZIP内path'];target=record['path'] if kind=='新' else record['復元先']
                body=z.read(name);assert sha(body)==record['sha256'];put(destination,target,body)
    for item in m['共有入力']+m['新共用入力']+[m['固定モデル'],m['前48選定報告'],m['固定方向']]:
        body=(ROOT/item['保存元']).read_bytes();assert sha(body)==item['保存SHA256']
        raw=gzip.decompress(body) if item['形式']=='gzip' else body;assert sha(raw)==item['解凍SHA256'];put(destination,item['復元先'],raw)
    f1raw=(FORMAL/'検査/F1学習前.json').read_bytes();f2raw=(FORMAL/'検査/F2モデル固定.json').read_bytes()
    assert sha(f1raw)==m['F1_SHA256'] and sha(f2raw)==m['F2_SHA256']
    put(destination,'work/139複合方向切替/F1学習前.json',f1raw);put(destination,'work/139複合方向切替/F2モデル固定.json',f2raw)
    f1=json.loads(f1raw);f2=json.loads(f2raw)
    old_root=next(Path(p).parents[2] for p in f1['ファイル'] if p.endswith('00139_全取得を維持して価格位置と別役割で方向を切り替える\\README.md'))
    mapped={}
    for p,expected in f1['ファイル'].items():
        target=destination/Path(p).relative_to(old_root);assert sha(target.read_bytes())==expected;mapped[str(target)]=expected
    for p,expected in f2['ファイル'].items():assert sha((destination/Path(p).relative_to(old_root)).read_bytes())==expected
    assert len(mapped)==30
    proof={'成功':True,'試行':139,'F1全30源/F2全3源同体':True,'原F1/F2改変':False,'Raw/Source/新金融観測/CSV生成':False}
    if args.replay:
        own=destination/'work/139複合方向切替';features=own/'入力/出生特徴.json';train=own/'入力/前48場のラベル.json'
        recreated_model=destination/'再生したモデル.json';recreated_report=destination/'再生した選定報告.json';recreated_choices=destination/'再生した全752方向.json'
        command=[sys.executable,'-X','utf8',str(own/'学習する.py'),'--features',str(features),'--features-sha256',sha(features.read_bytes()),
            '--train',str(train),'--train-sha256',sha(train.read_bytes()),'--output-model',str(recreated_model),'--output-report',str(recreated_report),'--execute-after-f1']
        subprocess.run(command,cwd=destination,capture_output=True,text=True,encoding='utf-8',check=True)
        assert recreated_model.read_bytes()==(ROOT/m['固定モデル']['保存元']).read_bytes()
        assert recreated_report.read_bytes()==(ROOT/m['前48選定報告']['保存元']).read_bytes()
        command=[sys.executable,'-X','utf8',str(own/'適用する.py'),'--features',str(features),'--features-sha256',sha(features.read_bytes()),
            '--model',str(recreated_model),'--model-sha256',sha(recreated_model.read_bytes()),'--output',str(recreated_choices),'--execute-after-model-freeze']
        subprocess.run(command,cwd=destination,capture_output=True,text=True,encoding='utf-8',check=True)
        assert sha(recreated_choices.read_bytes())==m['固定方向']['解凍SHA256']
        ledger1={'試行':139,'段階':'事後の再現専用パス台帳。学習前F1ではない','元F1_SHA256':sha(f1raw),'ファイル':mapped}
        body=(json.dumps(ledger1,ensure_ascii=False,indent=2)+'\n').encode('utf-8');p1=put(destination,'再現専用F1台帳.json',body)
        ledger2={'試行':139,'段階':'事後の再現専用パス台帳。モデル固定F2ではない','元F2_SHA256':sha(f2raw),'F1_SHA256':sha(body),
            'モデルSHA256':sha(recreated_model.read_bytes()),'ファイル':{str(p1):sha(body),str(recreated_model):sha(recreated_model.read_bytes()),str(recreated_report):sha(recreated_report.read_bytes())}}
        p2=put(destination,'再現専用F2台帳.json',(json.dumps(ledger2,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        command=[sys.executable,'-X','utf8',str(destination/'work/139固定モデルの方向を再集計する.py')]
        for name,path in [('f1',p1),('f2',p2),('model',recreated_model),('choices',recreated_choices)]:
            command += ['--'+name,str(path),'--'+name+'-sha256',sha(path.read_bytes())]
        output=destination/'再集計';command+=['--output-dir',str(output)]
        subprocess.run(command,cwd=destination,capture_output=True,text=True,encoding='utf-8',check=True)
        generated=json.loads((output/'集計.json').read_bytes());expected=json.loads((FORMAL/'成果物/集計.json').read_bytes())
        for key,path in [('F1_SHA256',p1),('F2_SHA256',p2)]:assert generated.pop(key)==sha(path.read_bytes());expected.pop(key)
        assert generated==expected
        assert sha((output/'CSV用の表.json').read_bytes())=='f0b077b63308651ec526a7d2bccd9b60e5a3235bedb7c5c5d9748f28b932ec1d'
        proof.update({'前48だけの28候補/モデルbytes同体':True,'全752方向bytes同体':True,'全金融数値/参加/頻度/phase同体':True,
            '三表JSON全bytes同体':True,'新CSVを生成':False,'差分はF1/F2参照の再現専用台帳SHAだけ':True})
    out=put(destination,'保存入力の再現確認.json',(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({**proof,'proof_SHA256':sha(out.read_bytes())},ensure_ascii=False))


if __name__=='__main__':
    main()
