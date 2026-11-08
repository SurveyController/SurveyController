const test = require('node:test');
const assert = require('node:assert/strict');
const {md5, sha256, hmacSha256, aesEncrypt, aesDecrypt} = require('./utils/encrypt');
test('standard digest vectors', () => {
    assert.equal(md5('abc'), '900150983cd24fb0d6963f7d28e17f72');
    assert.equal(sha256('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    assert.equal(hmacSha256('The quick brown fox jumps over the lazy dog', 'key'), 'f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8');
});
test('AES round-trip preserves Unicode', () => {
    const key=Buffer.from('0123456789abcdef'), iv=Buffer.alloc(16);
    assert.equal(aesDecrypt(aesEncrypt('通用采集',key,iv),key,iv), '通用采集');
});
