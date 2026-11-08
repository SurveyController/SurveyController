const test=require('node:test'), assert=require('node:assert/strict');
const {SandboxRunner}=require('../scripts/sandbox-runner');
test('runner clears timers and resets per-run snapshots', async()=>{
    const runner=new SandboxRunner({extractCookie:true});
    assert.equal(runner.run('setInterval(()=>{},100);document.cookie="a=1"').success,true);
    assert.equal(runner._timers.size,0);
    assert.deepEqual(runner.run('document.cookie="b=2"').cookies,{b:'2'});
    assert.equal(runner.run('setTimeout(()=>{},10);throw new Error("fixture")').success,false);
    assert.equal(runner._timers.size,0);
});
