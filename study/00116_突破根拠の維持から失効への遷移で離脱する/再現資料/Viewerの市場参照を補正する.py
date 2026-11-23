"""Viewerのmarket_pathを明示絶対参照へ結び、旧保存を保持する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / 'study/00116_突破根拠の維持から失効への遷移で離脱する'
NAME = '閲覧用_市場絶対参照.resources.json'


def ref(path: Path, expected: str | None = None) -> dict:
    """機能: 明示コード・metadataのSHAを認証する。

    引数: path(Path)、expected(str|None)は対象と既知SHA。
    返り値: dictは絶対path/SHA。価格やNativeを渡さない。
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and expected != digest:
        raise ValueError('SHA不一致: ' + str(path))
    return {'path': str(path), 'sha256': digest}


def save(path: Path, value: dict) -> dict:
    """機能: 小metadataを新規先だけに保存する。

    引数: path(Path)、value(dict)は保存先と内容。
    返り値: dictは保存Ref。既存先は拒否する。
    """
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return ref(path)


def main() -> None:
    """機能: 市場だけの絶対参照一覧と同体HTTP検査クライアントを追補する。

    引数: なし。
    返り値: None。旧一覧/停止/金融/CSVを変更せず、Raw本文を読まない。
    """
    original_path = STUDY / '成果物/一覧.resources.json'
    original_ref = ref(original_path, 'ba54b2e194619555a8e1d29f6202d4dfbd27e8b915fa7cba56e14eab0816e199')
    binding_path = STUDY / '検査/Viewer市場参照の接続.json'
    binding_ref = ref(binding_path)
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    targets = {r['session']: r['viewer_canonical']['path'] for r in binding['場別']}
    if len(targets) != 70 or binding['Viewer資源'] != 2520 or not binding['成功']:
        raise ValueError('既固定の70市場接続')
    original = json.loads(original_path.read_text(encoding='utf-8'))
    result = deepcopy(original)
    for old, row in zip(original['resources'], result['resources']):
        expected = Path(targets[row['session']])
        if (original_path.parent / old['market_path']).resolve() != expected or expected.is_relative_to(ROOT / 'work'):
            raise ValueError('元保存の字句参照と恒久価格は同じ')
        row['market_path'] = str(expected)
        if {k: v for k, v in row.items() if k != 'market_path'} != {k: v for k, v in old.items() if k != 'market_path'}:
            raise ValueError('市場以外の変更')
    output_ref = save(original_path.with_name(NAME), result)

    # ----------------------------------------
    old_client = ROOT / 'work/116Viewer確認の準備/Viewer取得を確認する.py'
    old_client_ref = ref(old_client, '7a82c743610362d8701da2f77dd130f1f481ee443263160c884549afa9a646c0')
    client = old_client.read_text(encoding='utf-8')
    if client.count('成果物/一覧.resources.json') != 2:
        raise ValueError('クライアントの固定catalog参照2箇所')
    new_client_dir = ROOT / 'work/116Viewer確認の市場参照補正'
    new_client_dir.mkdir(exist_ok=False)
    new_client = new_client_dir / old_client.name
    with new_client.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(client.replace('成果物/一覧.resources.json', '成果物/' + NAME))
    archived_client = STUDY / '再現資料/Viewer取得の市場参照補正版.py'
    with new_client.open('rb') as src, archived_client.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    own = Path(__file__).resolve()
    archived_own = STUDY / '再現資料/Viewerの市場参照を補正する.py'
    with own.open('rb') as src, archived_own.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    if ref(original_path) != original_ref or ref(binding_path) != binding_ref or ref(old_client) != old_client_ref:
        raise ValueError('旧保存と旧クライアントの不変')
    proof = {'成功': True, '試行': 116, '旧一覧': original_ref, '価格接続証拠': binding_ref, '閲覧用一覧': output_ref,
             '仕様': 'pnl_pathはpath_base=catalog、market_pathは常にdata_root基準。明示絶対market_pathで固定70所在へ結ぶ。',
             '変更はmarket_pathの表記のみ': True, '資源数': len(result['resources']), '市場数': len(targets),
             'Raw/価格CSV/Native/損益CSV本文読取': 0, '金融再実行': False, '旧保存不変': True,
             '元HTTP検査コード': old_client_ref, '補正HTTP検査コード': ref(archived_client), '補正コード': ref(archived_own),
             'Viewer一次コード': [ref(ROOT.parent / 'SessionTradeViewer/catalog.go'), ref(ROOT.parent / 'SessionTradeViewer/config.go')],
             '採用': False, '研究目標達成': False}
    proof_ref = save(STUDY / '検査/Viewer市場参照の補正.json', proof)
    print(json.dumps({'成功': True, '一覧': output_ref, '検査クライアント': ref(new_client), '証拠': proof_ref}, ensure_ascii=False))


if __name__ == '__main__':
    main()
