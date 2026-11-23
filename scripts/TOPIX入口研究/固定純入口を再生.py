"""恒久純入口とSourceだけから、TOPIXの固定金融を隔離作業領域で再生する。"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,shutil,subprocess,sys,uuid,zipfile
ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    """
    機能: ファイルのSHA256を計算する。
    引数: path(Path)。
    返り値: strは16進の内容指紋。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_link(source,target):
    """
    機能: 原板を複製せず、隔離領域へ恒久入力ディレクトリを接続する。
    引数: source/target(Path)。
    返り値: None。Windowsはjunction、他OSはディレクトリsymlink。
    """
    if os.name=='nt':
        import _winapi
        _winapi.CreateJunction(str(source.resolve()),str(target.resolve()))
    else:target.symlink_to(source.resolve(),target_is_directory=True)


# ----------------------------------------
def restore_missing_sources(workspace,condition):
    """
    機能: 固定条件が参照する不足Sourceを既存恒久ZIPの同一SHAからだけ復元する。
    引数: workspace(Path)は新規作業root、condition(dict)は金融前のSource一覧。
    返り値: list[dict]は復元元の記録。既存ファイルと固定条件を変更しない。
    """
    needed={p:digest for p,digest in condition['Source'].items() if not (workspace/p).exists()}
    restored=[]
    for archive_path in sorted((ROOT/'study').glob('*/Source.zip'),reverse=True):
        if not needed:break
        with zipfile.ZipFile(archive_path) as archive:
            found=set(archive.namelist())&set(needed)
            for name in sorted(found):
                body=archive.read(name)
                if hashlib.sha256(body).hexdigest()!=needed[name]:continue
                target=(workspace/name).resolve();assert target.is_relative_to(workspace.resolve())
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
                restored.append({'path':name,'sha256':needed.pop(name),'archive':str(archive_path.relative_to(ROOT))})
    assert not needed,('恒久保存に不足Source',needed)
    assert all(sha(workspace/p)==digest for p,digest in condition['Source'].items())
    return restored


# ----------------------------------------
def main():
    """
    機能: 指定試行の金融を再生し、正本の集計SHAと一致することを確認する。
    引数: CLIの試行(int)と任意の--監査(bool)。
    返り値: None。既存work、旧正本、入力は上書きせず作業領域を削除しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('試行',type=int,choices=(192,196,197,200,202,203,205,208,210));parser.add_argument('--監査',action='store_true');args=parser.parse_args()
    number=args.試行;studies=list((ROOT/'study').glob(f'{number:05d}_*'));inputs=list((ROOT/'inputs').glob(f'{number:05d}_*'))
    assert len(studies)==len(inputs)==1,(studies,inputs);study=studies[0];permanent=inputs[0]
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');workspace=ROOT/'work'/f'再現_TOPIX{number}_{stamp}_{uuid.uuid4().hex[:6]}'
    workspace.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(study/'Source.zip') as archive:
        for info in archive.infolist():
            target=(workspace/info.filename).resolve();assert target.is_relative_to(workspace.resolve()),info.filename
            archive.extract(info,workspace)
    directory_link(ROOT/'inputs',workspace/'inputs')
    task=workspace/'work'/f'{number}TOPIX';task.mkdir(parents=True,exist_ok=True)
    for name in ('条件.json','人工確認.json'):shutil.copy2(study/name,task/name)
    restored=restore_missing_sources(workspace,json.loads((task/'条件.json').read_text(encoding='utf-8')))
    shutil.copy2(permanent/'純入口.json.gz',task/'純入口.json.gz')
    old_path=workspace/'work/190TOPIX/金融正本/TOPIX190_D4_量不明でも動力改善_N01_共通q0の旧_DayA25_NightW15_H60.json.gz'
    old_path.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'inputs/00192_TOPIXの構造と数量の純入口/旧190固定対照.json.gz',old_path)
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    if number==210:
        shutil.copy2(study/'旧同体期待.json',task/'旧同体期待.json')
        if args.監査:
            with (workspace/'独立純ログ.txt').open('w',encoding='utf-8') as log:
                subprocess.run([sys.executable,str(task/'独立純確認210.py')],cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    command=([sys.executable,str(workspace/'scripts/TOPIX入口研究/共通金融.py'),
        '--condition',str(task/'条件.json'),'--births',str(task/'純入口.json.gz'),
        '--output',str(task/'金融'),'--id-template',f'TOPIX{number}_{{name}}_DayA25_H60']
        if number in (205,208,210) else [sys.executable,str(task/f'金融{number}.py')])
    if number==210:command.append('--extra')
    with (workspace/'金融ログ.txt').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    expected=[study/'全13組全83安定性.json.gz'] if number==210 else list(study.glob('全*組安定性.json.gz'));assert len(expected)==1
    generated=task/'金融/安定性.json.gz' if number in (205,208,210) else task/expected[0].name
    assert sha(expected[0])==sha(generated),'固定金融の集計SHA不一致'
    if args.監査:
        with (workspace/'独立ログ.txt').open('w',encoding='utf-8') as log:
            audit=task/'独立金融確認210.py' if number==210 else task/f'独立確認{number}.py'
            subprocess.run([sys.executable,str(audit)],cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    result={'試行':number,'金融正本同体':True,'安定性SHA':sha(generated),'独立監査を再実行':args.監査,'作業領域':str(workspace),'恒久入力':'junction/symlinkで参照、原板複製なし','別恒久Sourceから補完':restored}
    (workspace/'再現確認.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
