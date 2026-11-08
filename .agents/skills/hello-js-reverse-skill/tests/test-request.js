const test=require('node:test'), assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function clientFor(request){
    const context={require:()=>({create:()=>({request})}),module:{exports:{}},console:{log(){},error(){}},setTimeout};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../templates/node-request/utils/request.js'),'utf8'),context);
    const client=new context.module.exports.RequestClient({delay:0});client.sleep=async()=>{};return client;
}
test('POST failures are not automatically replayed',async()=>{
    let count=0;const error={response:{status:500}};
    const client=clientFor(async()=>{count++;throw error});
    await assert.rejects(client.post('https://example.test'),()=>true);assert.equal(count,1);
});
test('GET retries recover and capture a cookie on success',async()=>{
    let count=0;const client=clientFor(async()=>{
        count++;if(count===1)throw {code:'ECONNRESET'};
        return {headers:{'set-cookie':['sid=demo; Path=/']},data:'ok'};
    });
    assert.equal((await client.get('https://example.test')).data,'ok');assert.equal(count,2);
    assert.equal(client.getCookieString(),'sid=demo');
});
