const test = require('node:test');
const assert = require('node:assert/strict');
const {loadWasm} = require('./utils/wasm-loader');
test('loads a real portable WASM fixture and invokes its export', async () => {
    const bytes=Buffer.from('0061736d0100000001070160027f7f017f030201000707010361646400000a09010700200020016a0b','hex');
    const result=await loadWasm(bytes);
    assert.equal(result.exports.add(2,3),5);
    assert.deepEqual(result.imports,[]);
});
test('invalid WASM fails explicitly', async () => {
    await assert.rejects(loadWasm(Buffer.from('not wasm')));
});
