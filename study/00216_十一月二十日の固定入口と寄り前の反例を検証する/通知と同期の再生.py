"""215と同じ通知転送口座と同期診断を11月20日の原板に適用する。"""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = next((ROOT/'study').glob('00215_*'))
sys.path.insert(0,str(OLD))
import 通知と同期を比較する as previous


def main() -> None:
    """
    機能：11月19日の通知判断・全建玉を照合し、20日のTOPIX通知口座と両指数の同期観測を保存する。
    引数：なし。両指数の固定再生を先に実行する。
    返り値：None。資源指紋・収支・個々の観測を試行フォルダに記録する。
    """
    read = previous.read
    routed, hashes = {}, {}
    old_scene, new_scene = '2026-11-19_Day','2026-11-20_Day'
    saved = read(OLD/'通知と同期の結果.json')
    inputs = {old_scene:read(OLD/'日経/固定結果.json')['結果']['建玉'],
              new_scene:read(HERE/'日経/固定結果.json')['結果']['建玉']}
    assert previous.follow.digest(previous.PREVIOUS/'日経取得通知の対照/条件.json') == previous.follow.SCHEMA
    out = ROOT/'work/216通知'
    out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out) as tmp:
        runtime = Path(tmp)
        lookup = previous.follow.verification_engine(runtime)
        for scene, orders in inputs.items():
            folder = ROOT.parent/'JP_OSE_Data/future/TOPIX'/scene
            raw = next(p for p in (folder/'book.jsonl',folder/'book.jsonl.gz') if p.is_file())
            path = runtime/(scene+'.npz')
            source = previous.prep.build_one(raw,path,'TOPIX',scene,ROOT.parent/'JP_OSE_Data')
            hashes[scene] = {k:source[k] for k in ('source_path','raw_lines','sha256_uncompressed','sha256_cache')}
            routed[scene] = previous.notification(scene,path,orders,lookup)
            if scene == old_scene:
                assert routed[scene] == saved['通知対照'][scene]
    # ----------------------------------------
    indices = {}
    for symbol, folder in [('NK225','216日経'),('TOPIX','216TOPIX')]:
        root = ROOT/'work'/folder/'原行索引'
        item = next(r for r in read(root/'manifest.json')['scenes'] if r['session']==new_scene)
        indices[symbol] = previous.load_scene(root,item)
    books = {'NK225':inputs[new_scene],'TOPIX':read(HERE/'TOPIX/固定照合.json')['追加']['取得']}
    result = {'11月19日一致通知':len(routed[old_scene]['通知記録']), '11月19日一致建玉':len(routed[old_scene]['取得']),
              '入力':hashes,'通知対照':{new_scene:routed[new_scene]},
              '11月20日同期':previous.synchronized(new_scene,books,indices)}
    (HERE/'通知と同期の結果.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf8')


if __name__ == '__main__':
    main()
