import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

/**
 * 機能: 名前付きCLI引数を読み、指定不足を検出する。
 * @param {string} name - 引数名。
 * @returns {string} 指定された文字列。
 */
function argument(name) {
  const i=process.argv.indexOf(name);
  assert.ok(i>=2&&process.argv[i+1],`必要な引数: ${name}`);
  return process.argv[i+1];
}

/**
 * 機能: バイト列のSHA256を返す。
 * @param {Buffer|string} value - 指紋を計算する内容。
 * @returns {string} 十六進SHA256。
 */
function sha(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

/**
 * 機能: 一セルをCSVの引用規則へ変換する。
 * @param {number|string|boolean|null} value - 型付き値。未知はnull。
 * @returns {string} CSVセル。未知は空欄。
 */
function field(value) {
  const text=value===null?'':String(value);
  return /[",\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;
}

// ----------------------------------------
const input=path.resolve(argument('--input'));
const output=path.resolve(argument('--output'));
const proofDir=path.resolve(argument('--proof'));
const dependencyDir=path.resolve(argument('--dependencies'));
const require=createRequire(path.join(dependencyDir,'__provided__.cjs'));
const {Workbook}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const inputBytes=await fs.readFile(input);
const data=JSON.parse(inputBytes);
const names=data.tableNames??{'候補比較':'集計','デイ':'デイ','ナイト_米前':'ナイト_米前','ナイト_米後':'ナイト_米後'};
assert.ok(names['候補比較']==='集計'&&new Set(Object.values(names)).size===Object.keys(names).length);
assert.ok(Object.values(names).every(name=>typeof name==='string'&&name.length>0&&!/[<>:"/\\|?*]/.test(name)));
assert.deepEqual(Object.keys(data.tables),Object.keys(names));
const candidates=[...new Set(data.tables['候補比較'].rows.map(r=>r[0]))];
assert.ok(candidates.length>0);
await fs.mkdir(output,{recursive:true});
await fs.mkdir(proofDir,{recursive:true});
const proof={成功:true,形式:'一つのCSVに一候補だけ',入力SHA256:sha(inputBytes),node:process.version,
  出力器SHA256:sha(await fs.readFile(new URL(import.meta.url))),候補数:candidates.length,files:[]};
const workbook=Workbook.create();
const owners=[];
for (const candidate of candidates) {
  assert.match(candidate,/^\d+:[^<>:"/\\|?*]+$/);
  const folder=candidate.replace(':','_');
  const target=path.join(output,folder);
  assert.ok(path.resolve(target).startsWith(output+path.sep));
  await fs.mkdir(target,{recursive:false});
  for (const [sourceName,fileName] of Object.entries(names)) {
    const table=data.tables[sourceName];
    const rows=table.rows.filter(r=>r[0]===candidate);
    assert.ok(rows.length>0&&rows.every(r=>r[0]===candidate));
    assert.ok(rows.every(r=>r.length===table.headers.length));
    const original=[table.headers,...rows];
    const sheetName=folder+'_'+fileName;
    assert.ok(sheetName.length<=31);
    const sheet=workbook.worksheets.add(sheetName);
    const range=sheet.getRangeByIndexes(0,0,original.length,table.headers.length);
    range.values=original;
    sheet.showGridLines=false;
    range.format.font={name:'Arial',size:10};
    range.format.rowHeight=32;
    range.format.verticalAlignment='center';
    sheet.getRangeByIndexes(0,0,1,table.headers.length).format={fill:'#334155',
      font:{name:'Arial',size:10,color:'#FFFFFF',bold:true},wrapText:true,rowHeight:56,horizontalAlignment:'center'};
    for (let j=0;j<table.headers.length;j++) {
      const column=sheet.getRangeByIndexes(0,j,original.length,1);
      column.format.columnWidthPx=j===0?180:j<3?145:sourceName==='候補比較'?110:j===3?200:160;
      const body=sheet.getRangeByIndexes(1,j,rows.length,1);
      const count=/回数|場数|件数|^主取得$|^補完取得$|^[FANC]$/.test(table.headers[j]);
      body.setNumberFormat(table.headers[j].includes('率')?'0.00%':count?'#,##0':'#,##0.0');
    }
    sheet.freezePanes.freezeRows(1);
    owners.push({candidate,folder,sourceName,fileName,original,range,sheetName,target});
  }
}
workbook.recalculate();
for (const item of owners) {
  const actual=item.range.values;
  assert.deepEqual(actual,item.original);
  assert.ok(item.range.formulas.flat().every(v=>v===''||v===null||v===undefined));
  const body='\uFEFF'+actual.map(r=>r.map(field).join(',')).join('\r\n')+'\r\n';
  const csvPath=path.join(item.target,item.fileName+'.csv');
  await fs.writeFile(csvPath,body,{encoding:'utf8',flag:'wx'});
  const lastRow=Math.min(item.original.length,6);
  const preview=await workbook.render({sheetName:item.sheetName,range:`A1:L${lastRow}`,scale:1,format:'png'});
  await fs.writeFile(path.join(proofDir,item.folder+'_'+item.fileName+'.png'),new Uint8Array(await preview.arrayBuffer()),{flag:'wx'});
  proof.files.push({候補:item.candidate,元表:item.sourceName,相対path:item.folder+'/'+item.fileName+'.csv',
    データ行:item.original.length-1,列:item.original[0].length,全セル照合:item.original.length*item.original[0].length,
    bytes:Buffer.byteLength(body,'utf8'),sha256:sha(body)});
}
assert.equal(sha(await fs.readFile(input)),sha(inputBytes));
await fs.writeFile(path.join(proofDir,'作成確認.json'),JSON.stringify(proof,null,2)+'\n',{encoding:'utf8',flag:'wx'});
console.log(JSON.stringify({成功:true,候補数:candidates.length,CSV数:proof.files.length,全セル照合:proof.files.reduce((s,r)=>s+r.全セル照合,0)}));
