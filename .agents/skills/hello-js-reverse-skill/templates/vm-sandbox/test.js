const test = require('node:test');
const assert = require('node:assert/strict');
const {createSandbox, executeAndExtractCookie} = require('./utils/sandbox');
test('location is self-consistent and document uses the same object', () => {
    const {sandbox, dispose}=createSandbox({url:'https://target.test:8443/a?q=1#f'});
    try {
        assert.equal(sandbox.location.host,'target.test:8443');
        assert.equal(sandbox.location.search,'?q=1');
        assert.equal(sandbox.location.origin,'https://target.test:8443');
        assert.equal(sandbox.document.location,sandbox.location);
    } finally { dispose(); }
});
test('extracts cookies and preserves equals signs', () => {
    const result=executeAndExtractCookie('document.cookie="token=a=b; path=/"', {initialCookie:'sid=demo'});
    assert.equal(result.success,true);
    assert.deepEqual(result.cookies,{sid:'demo',token:'a=b'});
});
test('sync extraction cleans timers on success and failure', async () => {
    const result=executeAndExtractCookie('setTimeout(()=>{document.cookie="late=1"},1); document.cookie="now=1"');
    assert.equal(result.cookieString,'now=1');
    assert.equal(executeAndExtractCookie('throw new Error("fixture")').success,false);
    await new Promise(resolve=>setTimeout(resolve,10));
    assert.equal(result.cookieString,'now=1');
});
