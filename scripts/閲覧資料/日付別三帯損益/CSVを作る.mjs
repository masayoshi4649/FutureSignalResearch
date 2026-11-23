import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {Workbook} from '@oai/artifact-tool';

const root=path.resolve(process.argv[2]??process.cwd());
const work=path.join(root,'work','172日付別三帯損益');
const output=path.join(root,'outputs','00172_日付別三帯損益');
const input=path.join(work,'型付き入力.json');
const epoch=Date.UTC(1899,11,30);

/**
 * 機能: 入力又は出力のSHA256を返す。
 * @param {Buffer|string} value - 指紋化する内容。
 * @returns {string} 十六進SHA256。
 */
function sha(value) { return crypto.createHash('sha256').update(value).digest('hex'); }

/**
 * 機能: CSVの引用・空欄規則へ変換する。
 * @param {string|number|null} value - 一セルの値。
 * @returns {string} エスケープ済みCSVセル。
 */
function field(value) {
  const s=value===null?'':String(value);
  return /[",\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;
}

// ----------------------------------------
const inputBytes=await fs.readFile(input);
const data=JSON.parse(inputBytes);
assert.deepEqual(Object.keys(data.表),['デイ','ナイト_米前','ナイト_米後']);
for (const ref of [...data.出典,data.集計Source]) {
  const body=await fs.readFile(path.join(root,ref.path));
  assert.equal(body.length,ref.bytes);assert.equal(sha(body),ref.sha256);
}
const wb=Workbook.create();
const owners=[];
for (const [name,t] of Object.entries(data.表)) {
  const typed=[t.見出し,...t.行.map(r=>[(Date.parse(r[0]+'T00:00:00Z')-epoch)/86400000,...r.slice(1)])];
  const sheet=wb.worksheets.add(name);
  const range=sheet.getRangeByIndexes(0,0,typed.length,t.見出し.length);
  range.values=typed;
  sheet.showGridLines=false;
  range.format.font={name:'Arial',size:11};
  range.format.rowHeight=26;
  range.format.verticalAlignment='center';
  range.format.columnWidthPx=118;
  sheet.getRangeByIndexes(0,0,1,t.見出し.length).format={
    fill:'#334155',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},
    wrapText:true,rowHeight:44,horizontalAlignment:'center'
  };
  sheet.getRange('A:A').format.columnWidthPx=126;
  sheet.getRangeByIndexes(1,0,t.行.length,1).setNumberFormat('yyyy-mm-dd');
  sheet.getRangeByIndexes(1,1,t.行.length,7).setNumberFormat('#,##0');
  sheet.freezePanes.freezeRows(1);
  owners.push({name,t,typed,range});
}
wb.recalculate();
await fs.mkdir(output,{recursive:true});
const proof={成功:true,入力SHA256:sha(inputBytes),対象候補:data.対象候補,定義:data.定義,出典:data.出典,
  集計Source:data.集計Source,著作SourceSHA256:sha(await fs.readFile(fileURLToPath(import.meta.url))),表:{}};
for (const {name,t,typed,range} of owners) {
  const actual=range.values;
  assert.deepEqual(actual,typed);
  const exported=[actual[0],...actual.slice(1).map(r=>[new Date(epoch+r[0]*86400000).toISOString().slice(0,10),...r.slice(1)])];
  assert.deepEqual(exported,[t.見出し,...t.行]);
  const csv='\uFEFF'+exported.map(r=>r.map(field).join(',')).join('\r\n')+'\r\n';
  await fs.writeFile(path.join(output,name+'.csv'),csv,{encoding:'utf8',flag:'wx'});
  const inspect=await wb.inspect({kind:'table',range:name+'!A1:I6',include:'values,formulas',maxChars:800});
  const preview=await wb.render({sheetName:name,range:'A1:I12',scale:1,format:'png'});
  await fs.writeFile(path.join(work,name+'_表示確認.png'),new Uint8Array(await preview.arrayBuffer()));
  proof.表[name]={日付行数:t.行.length,列数:t.見出し.length,全セル照合:typed.length*t.見出し.length,
    SHA256:sha(csv),inspect:inspect.ndjson,合計:data.合計[name]};
}
proof.エラー走査=(await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',
  options:{useRegex:true,maxResults:5},maxChars:500})).ndjson;
assert.equal(sha(await fs.readFile(input)),sha(inputBytes));
await fs.writeFile(path.join(output,'作成確認.json'),JSON.stringify(proof,null,2)+'\n',{encoding:'utf8',flag:'wx'});
console.log(JSON.stringify({成功:true,表:Object.fromEntries(Object.entries(proof.表).map(([k,v])=>[k,{日付行数:v.日付行数,合計:v.合計}]))}));
