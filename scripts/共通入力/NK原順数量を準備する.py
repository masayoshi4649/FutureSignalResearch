"""共通入口の数量比較に必要なNK225原順8列を、一度だけ恒久保存する。"""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'inputs/NK225原順8列_20260921_20261116'
WORK = ROOT / 'work/188数量入力'
PARSER = ROOT / 'scripts/複合検証/データ準備.py'
ORIGIN = ROOT / 'study/00002_複数時間足と四系統の要因比較/入力台帳.json'
RESERVATION = ROOT / 'work/187共通対照/188向け数量入力の所在.json'
DATA = ROOT.parent / 'JP_OSE_Data/future'


def sha(path: Path) -> str:
    """
    機能: 物理ファイルのSHA256を取得する。
    引数: path(Path)。
    返り値: strは指紋。
    """
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def ref(path: Path) -> dict:
    """
    機能: 入力とSourceの追跡情報を取得する。
    引数: path(Path)。
    返り値: dictはpath、bytes、sha256。
    """
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def parser_module():
    """
    機能: 旧8列の同一パーサを変更せず読み込む。
    引数: なし。
    返り値: moduleは旧データ準備器。
    """
    spec = importlib.util.spec_from_file_location('数量188旧パーサ', PARSER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def one(job: dict) -> dict:
    """
    機能: 1場の旧cache再用又は新生成を行い、原板と数量を照合する。
    引数: job(dict)は場、原板、旧台帳又は予約指紋。
    返り値: dictは固定入力台帳行。原板自体は複製しない。
    """
    p = parser_module()
    scene = job['session']; source = Path(job['source'])
    target = DEST / (scene + '.npz')
    memo = WORK / (scene + '.json.gz')
    source_ref = ref(source)
    if 'source_sha' in job:
        assert source_ref['sha256'] == job['source_sha'], scene
    if memo.exists():
        row = json.loads(gzip.decompress(memo.read_bytes()))
        assert row['current_raw'] == source_ref and row['sha256_cache'] == sha(target)
        return row
    if job['old'] is not None:
        row = dict(job['old'])
        previous = ROOT / 'work/複合検証' / row['cache_path']
        assert sha(previous) == row['sha256_cache']
        opener = gzip.open if source.suffix.lower() == '.gz' else open
        with opener(source, 'rb') as f:
            decoded_sha = hashlib.file_digest(f, 'sha256').hexdigest()
        assert decoded_sha == row['sha256_uncompressed'], scene
        if target.exists():
            assert sha(target) == row['sha256_cache']
        else:
            shutil.copyfile(previous, target)
        reused = True
    else:
        assert not target.exists(), target
        row = p.build_one(source, target, 'NK225', scene, source.parents[2])
        reused = False
    assert source_ref == ref(source), scene
    assert len(row['in_session_contract_codes']) == 1
    with np.load(target, allow_pickle=False) as archive:
        assert set(archive.files) == set(p.FIELDS)
        assert all(len(archive[k]) == row['events'] for k in archive.files)
        lines = archive['line']
        assert np.all(lines[1:] > lines[:-1])
    row.update({'cache_absolute': str(target), 'cache_relative': target.relative_to(ROOT).as_posix(),
                'current_raw': source_ref, '再用': reused})
    memo.write_bytes(gzip.compress((json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n').encode(), mtime=0))
    return row


def main() -> None:
    """
    機能: 固定81場の価格・数量・時計を恒久化し、再利用可能な台帳を保存する。
    引数: CLI --workers(int)は並列原板読取数、既定3。
    返り値: None。入口・損益・CSVは生成しない。
    """
    cli = argparse.ArgumentParser()
    cli.add_argument('--workers', type=int, default=3)
    args = cli.parse_args()
    assert 1 <= args.workers <= 8
    DEST.mkdir(parents=True, exist_ok=True); WORK.mkdir(parents=True, exist_ok=True)
    reservation = json.loads(RESERVATION.read_text(encoding='utf-8'))
    assert sha(ORIGIN) == reservation['正式台帳SHA']
    assert sha(PARSER) == reservation['パーサSHA']
    old = json.loads(ORIGIN.read_text(encoding='utf-8'))
    jobs = []
    for row in old['entries']:
        if row['symbol'] == 'NK225':
            jobs.append({'session': row['session'], 'source': str(DATA/row['source_path']), 'old': row})
    assert len(jobs) == 60
    for row in reservation['不足21']:
        jobs.append({'session': row['session'], 'source': row['raw']['path'],
                     'source_sha': row['raw']['sha256'], 'old': None})
    assert len(jobs) == len({r['session'] for r in jobs}) == 81
    sources = [ref(Path(__file__)), ref(PARSER), ref(ORIGIN), ref(RESERVATION)]
    fixed = {'入力場': [{'場': r['session'], 'source': r['source'], '旧再用': r['old'] is not None} for r in jobs],
             'Source': sources, '原板複製': False, '金融未実行': True}
    pin = WORK / '入力生成前固定.json'
    if pin.exists():
        assert json.loads(pin.read_text(encoding='utf-8')) == fixed
    else:
        pin.write_text(json.dumps(fixed, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(one, job) for job in jobs]
        for future in as_completed(futures):
            row = future.result(); rows.append(row)
            print(json.dumps({'完了': len(rows), '場': row['session'], '再用': row['再用']}, ensure_ascii=False), flush=True)
    rows.sort(key=lambda r: r['session'])
    body = {'成功': True, '対象': 'NK225', '場数': 81, '期間': [rows[0]['session'], rows[-1]['session']],
            'entries': rows, 'Source': sources, 'cache_columns': list(parser_module().FIELDS),
            '旧60再用': sum(r['再用'] for r in rows), '原板複製': False,
            '実装修正': '修正1。inputs/105生成原板の3場も実所在の親を旧パーサへ渡す。価格・数量式は変更なし。旧Sourceと未登録3cacheを保管して数値を照合。',
            '用途': '187の価格q0へ数量可用性と持続を重ねる188以降の比較。真の受信時計は復元しない。'}
    target = DEST / '入力台帳.json.gz'
    encoded = gzip.compress((json.dumps(body, ensure_ascii=False, allow_nan=False)+'\n').encode(), mtime=0)
    if target.exists():
        assert target.read_bytes() == encoded
    else:
        target.write_bytes(encoded)
    assert sources == [ref(Path(__file__)), ref(PARSER), ref(ORIGIN), ref(RESERVATION)]
    print(json.dumps({'成功': True, '場数': 81, '旧再用': body['旧60再用'],
                      'cache合計bytes': sum(r['cache_size'] for r in rows), '台帳SHA': sha(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
