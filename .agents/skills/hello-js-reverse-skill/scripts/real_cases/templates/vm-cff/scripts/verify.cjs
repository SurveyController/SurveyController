// SPDX-License-Identifier: CC0-1.0
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const parser=require('@babel/parser');
const root=path.resolve(__dirname,'..'); process.chdir(root);
const context=vm.createContext({console});
vm.runInContext('window = globalThis;',context);
for(const file of ['baseline.bundle.js','vm.bundle.js','cff.bundle.js','cff-disabled.bundle.js','selftest.js']) {
    vm.runInContext(fs.readFileSync('dist/'+file,'utf8'),context,{filename:file,timeout:10000});
}
const report=vm.runInContext('RealCasesTest.run()',context,{timeout:30000});
function structure(file) {
    const code=fs.readFileSync(file,'utf8');
    const ast=parser.parse(code,{sourceType:'script',plugins:['estree']}).program;
    const counts={SwitchStatement:0,SwitchCase:0,WhileStatement:0};
    const switches=[]; let dispatchers=0;
    function walk(node,ancestors=[]) {
        if(!node || typeof node!=='object') return;
        if(node.type in counts) counts[node.type]++;
        if(node.type==='SwitchStatement') {
            const isDispatcher=ancestors.some(n=>n.type==='WhileStatement') && node.discriminant.type==='MemberExpression';
            if(isDispatcher) dispatchers++;
            switches.push({line:node.loc.start.line,cases:node.cases.length,discriminant:code.slice(node.discriminant.start,node.discriminant.end),withinWhile:isDispatcher});
        }
        for(const [key,value] of Object.entries(node)) {
            if(key==='loc')continue;
            if(Array.isArray(value))value.forEach(x=>walk(x,ancestors.concat(node)));
            else if(value && typeof value==='object')walk(value,ancestors.concat(node));
        }
    }
    walk(ast); return {file,counts,dispatchers,switches};
}
const structural=['dist/baseline.bundle.js','dist/vm.bundle.js','dist/cff.bundle.js','dist/cff-disabled.bundle.js'].map(structure);
fs.writeFileSync('evidence/structure.json',JSON.stringify(structural,null,2)+'\n');
fs.writeFileSync('evidence/verification.json',JSON.stringify({execution:'Node.js '+process.version+' V8 context with window=globalThis; not Camoufox', ...report},null,2)+'\n');
console.log(JSON.stringify({ok:report.ok,total:report.total,passed:report.passed,failed:report.failed,failures:report.failures.slice(0,3),structural},null,2));
assert.equal(report.failed,0,'differential or known-answer mismatch');
assert(structural[2].dispatchers>=2,'CFF must have real generated while/switch dispatchers');
assert.equal(structural[0].counts.SwitchStatement,0);
assert.equal(structural[3].counts.SwitchStatement,0,'disabled CFF control must not have dispatch switches');
