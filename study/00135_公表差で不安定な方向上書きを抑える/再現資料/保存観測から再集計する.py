"""135の固定評価関数へパス写像台帳を渡し、元観測だけの同体再集計を確認する。"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]
OWN = 'work/公表差で反転が不安定な入口を保守化する'


def sha(path: Path) -> str:
    """
    機能: 再集計入力と出力の指紋を返す。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------
def main() -> None:
    """
    機能: 元F1を変更せず、別作業先で保存方向・旧観測を同じ算術へ再入力する。
    引数: CLI --restored(Path)、--proof(Path|None)は未作成の証跡先。
    返り値: None。新しい出生・閾値・Raw走査・CSV生成は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--restored', required=True, type=Path)
    parser.add_argument('--proof', type=Path)
    args = parser.parse_args(); restored = args.restored.resolve()
    assert restored.is_relative_to(ROOT / 'work')
    own = restored / OWN; ledger = json.loads((own / '再現用パス台帳.json').read_bytes())
    assert ledger['成功'] and not ledger['新しい事前F1として扱う']
    assert sha(own / 'F1.json') == ledger['元F1_SHA256'] == '841514160f4ea92036a06688cbce5b1404f6f3ae0040751e0a7aa44b0211a0c2'
    assert all(sha(Path(p)) == h for p,h in ledger['ファイル'].items())
    source = own / '評価する.py'
    assert sha(source) == '3e0fe51623e1b2af05145eacffae801bef20f03cce6634f687ab965517d2c808'
    assert not (own / '集計.json').exists() and not (own / 'CSV用の表.json').exists()
    spec = importlib.util.spec_from_file_location('135保存観測再集計', source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.evaluate(ledger)
    assert sha(own / '集計.json') == sha(FORMAL / '成果物/集計.json') == '90b8ea3eeff6314b36f15637fcf7608c8336fe0202a9d3b41486ab91330a5c29'
    assert sha(own / 'CSV用の表.json') == 'dff78180df502ee24f642defded977b187a655d3045c130384479e79a88dda7b'
    proof = {'成功': True, '試行': 135, '保存観測からの再集計': True, '原F1同体': True,
             '原F1_SHA256': ledger['元F1_SHA256'], '再現用パス台帳SHA256': sha(own / '再現用パス台帳.json'),
             '台帳は新しい事前F1ではない': True, '原文のevaluateへ台帳を渡す': True,
             '集計は原F1_SHA参照を含む全bytes同体': True, '集計SHA256': sha(own / '集計.json'),
             '全三表JSON_SHA256同体': sha(own / 'CSV用の表.json'),
             '全15源の前後同体': all(sha(Path(p)) == h for p,h in ledger['ファイル'].items()),
             'Raw/巨大入力読取': False, '出生/条件変更': False, '新仮説の金融実行': False, '新CSV生成': False,
             'コードSHA256': sha(Path(__file__))}
    target = args.proof.resolve() if args.proof else FORMAL / '検査/保存観測からの再現確認.json'
    assert target.is_relative_to(ROOT) and not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'成功': True, '集計/全三表は原bytes同体': True, '原板読取': False,
                      '証跡SHA256': sha(target)},ensure_ascii=False))


if __name__ == '__main__':
    main()
