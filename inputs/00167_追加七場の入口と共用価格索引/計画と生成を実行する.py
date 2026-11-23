"""167の固定宣言に従い追加7場の入力・母集団・純観測だけを生成する。"""
from pathlib import Path
import datetime
import gzip
import importlib.util
import json
import hashlib
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BOOK = ROOT / 'study/00167_固定した複合入口を追加七場へ適用する/条件.json'
BOOK_SHA = '73e16eabfc3364a9e038d9697472abe50bb91fbba49b488dd0c8ed8d5eaea9f4'
INITIAL_F0 = BOOK.parent / '検査/F0_追加価格参照前.json'
STOP_PATHS = ('work/未見入口の同体接続/接続器の停止.json',
              'work/166可変場の観測/可変場観測の停止.json',
              'work/166可変場の数値化/数値化の停止.json')
EXPECTED_CONTRACT = '161120018'


def sha(path: Path) -> str:
    """
    機能: Source又は宣言入力の全物理SHAを計算する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def reference(path: Path) -> dict:
    """
    機能: ファイルの物理参照を返す。
    引数: path(Path)。
    返り値: dictは絶対path/bytes/SHA256。
    """
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def read(path: Path) -> dict:
    """
    機能: 宣言又は完成確認JSONを読む。
    引数: path(Path)。
    返り値: dictはJSON内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> dict:
    """
    機能: 未作成の新規計画又は証跡をUTF-8保存する。
    引数: path(Path)、value(object)。
    返り値: dictは完成物理参照。
    """
    with path.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return reference(path)


def verify_sources(book: dict) -> None:
    """
    機能: 事前固定book・参照・汎用Sourceの不変を照合する。
    引数: book(dict)。
    返り値: None。不一致なら新規段を開始しない。
    """
    assert sha(BOOK) == BOOK_SHA
    for value in book['source_references'].values():
        path = ROOT / value['path']
        assert path.stat().st_size == value['bytes'] and sha(path) == value['sha256'], str(path)
    for stop_path in STOP_PATHS:
        stop = read(ROOT / stop_path)
        assert stop['成功']
        for source in stop['Source']:
            path = ROOT / source['path']
            assert path.stat().st_size == source['bytes'] and sha(path) == source['sha256'], str(path)


def opaque_input(path: Path) -> tuple[dict, dict]:
    """
    機能: 市場値を解析せず新入力全bytesと前後statを固定する。
    引数: path(Path)は宣言対象7場内の原本。
    返り値: tuple[dict,dict]は固定参照とbytes/mtime_ns。
    """
    before = path.stat()
    digest = sha(path)
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
    stat = {'bytes': after.st_size, 'mtime_ns': after.st_mtime_ns}
    return {'path': str(path), 'bytes': after.st_size, 'sha256': digest}, stat


def scene_clock(session: str) -> tuple[int, int, int]:
    """
    機能: 旧122と同じJSTの予定場時計を作る。
    引数: session(str)。
    返り値: tuple[int,int,int]はStart/End/ForceClose秒。
    """
    date, kind = session.split('_')
    day = datetime.date.fromisoformat(date)
    zone = datetime.timezone(datetime.timedelta(hours=9))
    if kind == 'Day':
        start = datetime.datetime.combine(day, datetime.time(8,45), zone)
        end = datetime.datetime.combine(day, datetime.time(15,45), zone)
    else:
        assert kind == 'Night'
        start = datetime.datetime.combine(day, datetime.time(17), zone)
        end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(6), zone)
    return int(start.timestamp()), int(end.timestamp()), int(end.timestamp())-600


def run_stage(name: str, command: list[str], book: dict) -> None:
    """
    機能: 停止済みCLIを実行し、前後Source不変と終了状態を記録する。
    引数: name(str)、command(list[str])、book(dict)。
    返り値: None。失敗はその場で停止する。
    """
    verify_sources(book)
    save(HERE / f'{name}_実行前.json', {'book_sha256': BOOK_SHA, 'driver': reference(Path(__file__)), 'command': command})
    with (HERE / f'{name}_stdout.txt').open('x',encoding='utf-8') as stdout, (HERE / f'{name}_stderr.txt').open('x',encoding='utf-8') as stderr:
        result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    verify_sources(book)
    save(HERE / f'{name}_実行後.json', {'終了コード': result.returncode, 'Source前後同体': True,
         'stdout': reference(HERE / f'{name}_stdout.txt'), 'stderr': reference(HERE / f'{name}_stderr.txt')})
    assert result.returncode == 0, f'{name}失敗。stderr票を確認し、自然再実行しない。'
    print(name + ' 完了', flush=True)


def main() -> None:
    """
    機能: 許可済み167の7場を固定手順で入力から純観測配列まで生成する。
    引数: なし。
    返り値: None。候補適用・採否・損益比較を行わない。
    """
    book = read(BOOK)
    verify_sources(book)
    assert book['trial'] == 167 and len(book['scenes']) == 7 and book['history_through'] == '2026-11-10_Day'
    assert INITIAL_F0.exists() and book['prices_unread_at_lock'] is True
    if '--financial-only' in sys.argv:
        index = HERE / '原板数値索引'
        population = HERE / '入口母集団'
        references = read(HERE / '新七場の原本指紋.json')['scenes']
        sealed = ROOT / 'work/167固定入口の別期間/全出生/完了.json'
        born = read(sealed)
        assert born['成功'] and born['条件SHA256'] == BOOK_SHA and born['金融数値表未入力'] is True
        save(HERE / 'F3前の候補出生封印参照.json', {'book_sha256': BOOK_SHA, '封印出生': reference(sealed), 'driver': reference(Path(__file__))})
        go = ROOT / 'work/166可変場の観測/可変場観測.exe'
    else:
        save(HERE / 'F0_全段生成前.json', {'book': reference(BOOK), 'Rootの価格参照前F0': reference(INITIAL_F0),
             'driver': reference(Path(__file__)), '汎用停止票': [reference(ROOT / path) for path in STOP_PATHS],
             '初回参照前': True, 'argv': sys.argv, '対象': book['scenes'], '候補又は金融結果を選ばない': True})
        # ----------------------------------------
        # 各原本の最初の参照は値を解釈しないstat/SHA固定だけにする。
        scenes = []
        references = []
        data_root = (ROOT / book['input_root']).resolve()
        for session in book['scenes']:
            directory = data_root / session
            candidates = [path for path in (directory / 'book.jsonl.gz', directory / 'book.jsonl') if path.is_file()]
            assert len(candidates) >= 1  # gzipを先に並べた事前固定の優先順を用いる。
            raw, raw_stat = opaque_input(candidates[0])
            csv1, stat1 = opaque_input(directory / 'candle_1min.csv')
            csv5, stat5 = opaque_input(directory / 'candle_5min.csv')
            start, end, force_close = scene_clock(session)
            scenes.append({'session': session, 'contract': EXPECTED_CONTRACT, 'start': start, 'end': end,
                           'force_close': force_close, 'raw': raw, 'expected_raw_stat': raw_stat,
                           'expected_accepted': 0, 'expected_quality': None, 'entries': []})
            references.append({'session': session, 'raw': raw, 'raw_stat': raw_stat,
                               'csv_1m': csv1, 'csv_1m_stat': stat1, 'csv_5m': csv5, 'csv_5m_stat': stat5})
        save(HERE / '新七場の原本指紋.json', {'book_sha256': BOOK_SHA, 'scenes': references,
             '契約仮説': EXPECTED_CONTRACT, 'Symbol全文照合は次の原板解析段で行う': True,
             '価格条件や候補を見て選んだ入力ではない': True})
        index_input = HERE / '索引前の空取得入力.json'
        index_ref = save(index_input, {'trial': 167, 'scenes': scenes, 'expected_entry_count': 0})
        go = ROOT / 'work/166可変場の観測/可変場観測.exe'
        index = HERE / '原板数値索引'
        run_stage('F1_原板索引', [str(go),'--mode','index','--input',str(index_input),'--sha256',index_ref['sha256'],
                  '--output-dir',str(index),'--workers','4'], book)
        manifest = read(index / 'manifest.json')
        assert manifest['success'] and manifest['trial'] == 167 and len(manifest['scenes']) == 7 and manifest['source_entry_count'] == 0
        bridge_scenes = []
        for declared, original, measured in zip(scenes, references, manifest['scenes'], strict=True):
            assert declared['session'] == measured['session'] == original['session']
            assert measured['contract'] == EXPECTED_CONTRACT and measured['success']
            assert measured['expected_raw_stat_compared'] and not measured['expected_accepted_compared'] and not measured['expected_quality_compared']
            bridge_scenes.append({**{key:declared[key] for key in ('session','contract','start','end','force_close','raw')},
                'expected_accepted': measured['rows'], 'expected_quality': measured['quality'],
                'csv_1m': original['csv_1m'], 'csv_5m': original['csv_5m'],
                'quote_index': {'path':str(index / measured['index']['path']),'sha256':measured['index']['sha256'],'bytes':measured['index_bytes']}})
        bridge_plan = HERE / '母集団接続計画.json'
        bridge_ref = save(bridge_plan, {'version':1,'trial':167,'transport':'index48','history_through':book['history_through'],
            'history_plan':reference(ROOT / 'work/122全場入力/公表生成計画.json'),
            'prior_publications':reference(ROOT / 'work/122全場入力/入力.json'),
            'index_manifest':reference(index / 'manifest.json'),'scenes':bridge_scenes})
        population = HERE / '入口母集団'
        bridge = ROOT / 'work/未見入口の同体接続/入口同体接続.exe'
        run_stage('F2_母集団', [str(bridge),'--execute-after-f0','--plan',str(bridge_plan),'--plan-sha',bridge_ref['sha256'],
                  '--plan-bytes',str(bridge_ref['bytes']),'--output',str(population)], book)
        complete_nonfinancial = read(population / '完了.json')
        save(HERE / '非金融の完了.json', {'成功': True, 'trial': 167, 'book_sha256': BOOK_SHA,
             '母集団': str(population), '完了票': reference(population / '完了.json'),
             'counts': complete_nonfinancial['counts'], '金融観測をまだ生成していない': True})
        if '--nonfinancial-only' in sys.argv:
            print('非金融母集団が完成。Rootの出生封印を待つ。', flush=True)
            return
    complete = read(population / '完了.json')
    assert complete['success'] and complete['trial'] == 167
    fixed = population / '固定取得入力.json.gz'
    fixed_ref = reference(fixed)
    assert fixed_ref['sha256'] == complete['files']['固定取得入力.json.gz']['sha256']
    config = ROOT / 'work/163任意幅Raw索引/観測条件の雛形.json'
    config_ref = reference(config)
    assert config_ref['sha256'] == '2c965bc6892cdb351e79dadc53915ba06bf292b95e88fa2e67015a73174a9a5e'
    assert read(config)['widths'] == book['width_controls']
    observed = HERE / '任意幅の純観測'
    run_stage('F3_任意幅観測', [str(go),'--mode','evaluate','--input',str(fixed),'--sha256',fixed_ref['sha256'],
              '--index-dir',str(index),'--index-sha256',reference(index / 'manifest.json')['sha256'],
              '--config',str(config),'--config-sha256',config_ref['sha256'],'--output-dir',str(observed),'--workers','4'], book)
    # ----------------------------------------
    # 数値化も停止済み算術を呼び、取引候補や損益順位は生成しない。
    adapter_path = ROOT / 'work/166可変場の数値化/arrays166.py'
    save(HERE / 'F4_数値化前.json', {'book_sha256':BOOK_SHA,'driver':reference(Path(__file__)),
         'adapter':reference(adapter_path),'fixed':fixed_ref,'index':reference(index / 'manifest.json'),
         'observed':reference(observed / 'manifest.json'),'config':config_ref})
    spec = importlib.util.spec_from_file_location('arrays166_for167', adapter_path)
    adapter = importlib.util.module_from_spec(spec); sys.modules[spec.name] = adapter; spec.loader.exec_module(adapter)
    table = adapter.read_table(index,reference(index / 'manifest.json')['sha256'],observed,reference(observed / 'manifest.json')['sha256'],
                              config,config_ref['sha256'],fixed,fixed_ref['sha256'])
    assert table.session_order == tuple(book['scenes'])
    cache = adapter.save_table(table,HERE / '自然数値表')
    verify_sources(book)
    # 最後にも全新原本のSHA/statを照合し、各段の利用中改変を排除する。
    for original in references:
        for key, stat_key in (('raw','raw_stat'),('csv_1m','csv_1m_stat'),('csv_5m','csv_5m_stat')):
            actual, actual_stat = opaque_input(Path(original[key]['path']))
            assert actual == original[key] and actual_stat == original[stat_key]
    result = {'成功':True,'trial':167,'book':reference(BOOK),'Source前後同体':True,'原本指紋前後同体':True,
         '全対象場':list(table.session_order),'case数':len(table.case_ids),'widths':list(table.widths),'horizons':list(table.horizons),
         '全新原本':reference(HERE / '新七場の原本指紋.json'),'index':reference(index / 'manifest.json'),
         'population':reference(population / '完了.json'),'観測':reference(observed / 'manifest.json'),
         'adapter':reference(adapter_path),'cache':cache,'純観測のみ':True,'候補選択又は損益比較':False,
         'Clock原文':False,'Clock':'索引float正本をJST canonicalへ再整形。原文の元Rawはpath/SHAで保持',
         '取得前の期待受理品質':'未指定。実測を保存し、事前照合済みと称さない',
         'label':'strictを保存、観測済みtouchへの主時計射影はRootが行う。direction/known/exit_timeを保持'}
    save(HERE / '生成の完了.json',result)
    print(json.dumps({'成功':True,'全場':len(table.session_order),'case数':len(table.case_ids),'純観測のみ':True},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
