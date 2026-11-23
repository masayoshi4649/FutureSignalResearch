"""143のF0原文・共有入力・場別教師を恒久資料だけから新しいworkへ復元する。"""
from pathlib import Path, PureWindowsPath
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL=Path(__file__).resolve().parents[1]
ROOT=FORMAL.parent.parent


def sha(raw: bytes) -> str:
    """
    機能: 原文の指紋を求める。
    引数: raw(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------
def relative(original: str) -> str:
    """
    機能: 元Windows絶対pathからrepository内のwork/study部分を取り出す。
    引数: original(str)。
    返り値: strは安全性を検査した相対path。
    """
    parts=PureWindowsPath(original).parts
    at=next(i for i,value in enumerate(parts) if value in ('work','study'))
    result=Path(*parts[at:]);assert not result.is_absolute() and '..' not in result.parts
    return result.as_posix()


# ----------------------------------------
def main() -> None:
    """
    機能: 保存指紋を照合して全固定源を復元し、任意で保存予測から再集計する。
    引数: --destination(str)は未作成のwork宛先、--replay(bool)は保存実正逆の再集計。
    返り値: None。自然価格読取・教師再射影・学習・モデル再推論・新金融観測を実行しない。
    """
    parser=argparse.ArgumentParser(description='143の入力とコードだけを復元する')
    parser.add_argument('--destination',required=True,type=Path);parser.add_argument('--replay',action='store_true');args=parser.parse_args()
    target=(ROOT/args.destination).resolve() if not args.destination.is_absolute() else args.destination.resolve()
    assert target.is_relative_to((ROOT/'work').resolve()) and not target.exists()
    m=json.loads((FORMAL/'保管索引.json').read_bytes());bodies={}
    def retain(rel: str, raw: bytes, expected: str) -> None:
        """
        機能: 復元登録の二重定義と指紋を検査する。
        引数: rel(str)、raw(bytes)、expected(str)。
        返り値: None。
        """
        p=Path(rel);assert not p.is_absolute() and '..' not in p.parts and sha(raw)==expected
        assert rel not in bodies or bodies[rel]==raw;bodies[rel]=raw
    snap=m['F0文書原文'];packed=(ROOT/snap['保存元']).read_bytes();assert sha(packed)==snap['保存SHA256']
    raw=gzip.decompress(packed);assert sha(raw)==snap['解凍SHA256']
    for item in json.loads(raw)['文書']:retain(item['path'],item['本文'].encode('utf-8'),item['sha256'])
    groups=[m['追加固定資料']]+m['共有固定コード群']+[m['教師入力']]
    if 'F1追加固定資料' in m:groups += [m['F1追加固定資料'],m['学習済み入力']]
    for group in groups:
        zp=ROOT/group['保存元ZIP'] if '保存元ZIP' in group else FORMAL/'再現資料'/group['ZIP']
        assert sha(zp.read_bytes())==group['ZIP_SHA256']
        with zipfile.ZipFile(zp) as z:
            for item in group['格納源']:
                rel=item.get('復元先',item.get('path'));entry=item.get('ZIP内path',item.get('path'))
                retain(rel,z.read(entry),item['sha256'])
    for item in m['共有入力']:
        raw=(ROOT/item['保存元']).read_bytes();assert sha(raw)==item['保存SHA256']
        decoded=gzip.decompress(raw) if item['形式']=='gzip' else raw
        retain(item['復元先'],decoded,item['解凍SHA256'])
    f0=m['元F0の復元参照'];raw=(ROOT/f0['保存元']).read_bytes();retain(f0['復元先'],raw,f0['SHA256'])
    expected=json.loads(raw)['ファイル'];assert len(expected)==27
    f1raw=None
    if 'F1_SHA256' in m:
        f1raw=(FORMAL/'検査/F1予測固定後.json').read_bytes();assert sha(f1raw)==m['F1_SHA256']
        retain('work/143逐次判別の評価/F1予測固定後.json',f1raw,m['F1_SHA256'])
        expected=json.loads(f1raw)['ファイル'];assert len(expected)==178
    for original,h in expected.items():assert sha(bodies[relative(original)])==h
    assert len(m['教師入力']['格納源'])==74
    for rel,raw in bodies.items():
        p=target/rel;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(raw)
    proof={'成功':True,'試行':143,'F0全27源同bytes':True,'教師73場と参照manifest同bytes':True,
           '復元ファイル数':len(bodies),'元F0_SHA256':m['F0_SHA256'],'元ラベル参照SHA256':m['教師入力']['ラベル参照SHA256'],
           '元文書/入力/教師の書換':False,'自然価格/教師再射影/学習/予測/金融/追加2場読取':False,
           '元絶対pathを含むF0と教師参照は不変':True,'再実行には別の再現パス台帳が必要':True,'F1全178源同bytes':f1raw is not None}
    if args.replay:
        assert f1raw is not None
        def remap(value: object) -> object:
            """
            機能: 別票内のrepository絶対pathだけを復元先へ向ける。
            引数: value(object)はJSON要素。
            返り値: object。元保存物は不変で数値/判断は変更しない。
            """
            if isinstance(value,dict):return {remap(k):remap(v) for k,v in value.items()}
            if isinstance(value,list):return [remap(v) for v in value]
            if isinstance(value,str) and PureWindowsPath(value).is_absolute() and 'FutureSignalResearch' in PureWindowsPath(value).parts:
                return str(target/relative(value))
            return value
        def save_adapted(name: str, value: dict) -> Path:
            """
            機能: 金融後再現用の別票だけを作業先へ保存する。
            引数: name(str)、value(dict)。
            返り値: Pathは保存先。
            """
            p=target/name;p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return p
        original_choice=target/'work/143逐次判別の評価/学習予測/全752の方向.json'
        original_prediction=target/'work/143逐次判別の評価/学習予測/全752の予測.json'
        prediction=save_adapted('再現用path変更予測.json',remap(json.loads(original_prediction.read_bytes())))
        choice=remap(json.loads(original_choice.read_bytes()))
        assert choice['sources'].pop(str(original_prediction))==sha(original_prediction.read_bytes())
        choice['sources'][str(prediction)]=sha(prediction.read_bytes())
        choice['predictions_sha256']=sha(prediction.read_bytes());choice['predictions_path']=str(prediction)
        adapted=save_adapted('再現用path変更方向.json',choice)
        mapped={str(target/relative(p)):h for p,h in expected.items()}
        mapped[str(prediction)]=sha(prediction.read_bytes());mapped[str(adapted)]=sha(adapted.read_bytes())
        ledger=save_adapted('再現専用path台帳.json',{'試行':143,'用途':'金融後の保存予測/実正逆再集計。金融前F1を後造りしない',
            '元F1_SHA256':m['F1_SHA256'],'ファイル':mapped})
        model=target/'work/143複合テクニカルの逐次判別/固定条件.json';output=target/'再集計'
        command=[sys.executable,'-X','utf8',str(target/'work/143複合テクニカルの逐次判別/集計する.py')]
        for name,p in [('f1',ledger),('model',model),('choices',adapted)]:command += ['--'+name,str(p),'--'+name+'-sha256',sha(p.read_bytes())]
        command += ['--output-dir',str(output)]
        run=subprocess.run(command,cwd=target,text=True,encoding='utf-8',capture_output=True);assert run.returncode==0,run.stderr+run.stdout
        old=json.loads((FORMAL/'成果物/集計.json').read_bytes());new=json.loads((output/'集計.json').read_bytes())
        assert old['方向SHA256']==sha(original_choice.read_bytes()) and old['F1_SHA256']==m['F1_SHA256']
        for key in ('方向SHA256','F1_SHA256'):old.pop(key);new.pop(key)
        assert old==new and sha((output/'CSV用の表.json').read_bytes())==m['表JSON再現期待SHA256']
        proof.update({'保存予測から全180/適用群/参加頻度/旧120/phase一致':True,'三表JSON全bytes同体':True,
            '集計の差はpath変更方向/F1再現台帳の2指紋だけ':True,'保存モデルの再推論/再学習':False,
            '再現台帳SHA256':sha(ledger.read_bytes())})
    p=target/'入力復元の確認.json';p.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'成功':True,'復元確認SHA256':sha(p.read_bytes()),'復元ファイル数':len(bodies)},ensure_ascii=False))


if __name__=='__main__':main()
