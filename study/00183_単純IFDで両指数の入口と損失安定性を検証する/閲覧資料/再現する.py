"""正式保存Sourceと9金融正本だけで、型付きJSONを別の空rootへ再生成する。"""
from pathlib import Path
import argparse,hashlib,json,platform,subprocess,sys,zipfile


def digest(path):
    """
    機能: 内容の指紋を取得する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_copy(stage,relative,data):
    """
    機能: 空root内に限り元相対パスで新規ファイルを配置する。
    引数: stage(Path),relative(str),data(bytes)。
    返り値: Pathは新規保存先。既存ファイルやroot外は拒否する。
    """
    target=(stage/relative).resolve();assert target.is_relative_to(stage)
    assert not target.exists(),target
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    return target


def main():
    """
    機能: 保存済み9packから2型付きJSONを実生成し、元SHAと同体検査する。
    引数: CLI --root(Path)は空の別root、--proof(Path|省略)は検査票の保存先。
    返り値: None。CSV・xlsx・markerを生成せず、元workを読まない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--proof',type=Path);args=parser.parse_args()
    here=Path(__file__).resolve().parent;repo=here.parents[2]
    index=json.loads((here/'保存索引.json').read_text(encoding='utf-8'))
    stage=args.root.resolve();assert stage!=repo and not repo.is_relative_to(stage)
    assert not stage.exists() or not any(stage.iterdir()),stage
    stage.mkdir(parents=True,exist_ok=True)
    source=repo/index['Source']['archive']['path'];assert digest(source)==index['Source']['archive']['sha256']
    with zipfile.ZipFile(source) as archive:
        for member in index['Source']['members']:
            data=archive.read(member['path']);assert hashlib.sha256(data).hexdigest()==member['sha256']
            safe_copy(stage,member['path'],data)
    common=index['共通安定性Source'];parent=repo/common['archive']['path']
    assert digest(parent)==common['archive']['sha256']
    with zipfile.ZipFile(parent) as archive:
        data=archive.read(common['member']['path']);assert hashlib.sha256(data).hexdigest()==common['member']['sha256']
        safe_copy(stage,common['member']['path'],data)
    for item in index['正本対応']:
        original=repo/item['saved']['path'];assert digest(original)==item['saved']['sha256']
        assert item['saved']['sha256']==item['original']['sha256']
        safe_copy(stage,item['original']['path'],original.read_bytes())
    # ----------------------------------------
    executions=[]
    for name in ('NKの型付き入力を作る.py','TOPIXの型付き入力を作る.py'):
        relative=Path('work/183閲覧資料')/name
        result=subprocess.run([sys.executable,'-I','-X','utf8',str(stage/relative)],cwd=stage,
            check=True,capture_output=True,text=True,encoding='utf-8')
        executions.append({'Source':relative.as_posix(),'終了コード':result.returncode,'標準出力':result.stdout.strip()})
    expected=index['型付き入力は指紋のみ']+index['照合票の元指紋']
    generated=[]
    for item in expected:
        path=stage/item['path'];assert path.stat().st_size==item['bytes'] and digest(path)==item['sha256'],item['path']
        generated.append({**item,'同体':True})
    assert not (stage/'outputs').exists()
    report={'成功':True,'旧work読取なし':True,'正式9packのみ':len(index['正本対応'])==9,
        'CSV再生成なし':True,'marker生成なし':True,'空root':str(stage),'Python':platform.python_version(),
        '実行':executions,'再生成同体':generated,'SourceSHA':digest(Path(__file__))}
    data=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.proof:
        assert not args.proof.exists(),args.proof
        args.proof.parent.mkdir(parents=True,exist_ok=True);args.proof.write_text(data,encoding='utf-8')
    print(data)


if __name__=='__main__':main()
