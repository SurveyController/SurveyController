// SPDX-License-Identifier: CC0-1.0
'use strict';
// Independent protocol implementation: ONLY Node builtins, never imports CryptoJS or the adapter.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const fields = ['v','alg','keyId','direction','requestId','method','path','ts','nonce','challengeId','fingerprint','iv','ciphertext'];
const contextFields = ['direction','requestId','method','path','nonce','challengeId','fingerprint'];
function reject() { throw Error('INVALID_ENVELOPE'); }
function verify(e, keys, expected) {
  try {
    if (Object.keys(e).sort().join() !== [...fields,'mac'].sort().join()) reject();
    if (e.v !== 1 || e.alg !== 'AES-256-CBC+HMAC-SHA256' || e.keyId !== 'demo-public-v1' || !['request','response'].includes(e.direction)) reject();
    if (e.method !== 'POST' || e.path !== '/local-sim/echo' || !Number.isSafeInteger(e.ts) || e.ts < 0) reject();
    for (const k of ['requestId','nonce','challengeId','iv']) if (typeof e[k] !== 'string' || !/^[a-f0-9]{32}$/.test(e[k])) reject();
    for (const k of ['fingerprint','mac']) if (typeof e[k] !== 'string' || !/^[a-f0-9]{64}$/.test(e[k])) reject();
    if (typeof e.ciphertext !== 'string' || e.ciphertext.length > 1400000) reject();
    const ciphertext = Buffer.from(e.ciphertext,'base64');
    if (!ciphertext.length || ciphertext.length % 16 || ciphertext.toString('base64') !== e.ciphertext) reject();
    if (!expected || contextFields.some(k => expected[k] === undefined || e[k] !== expected[k])) reject();
    const key = keys[e.direction];
    const canonical = JSON.stringify(fields.map(k => e[k]));
    const mac = crypto.createHmac('sha256',Buffer.from(key.macHex,'hex')).update(canonical,'utf8').digest();
    if (!crypto.timingSafeEqual(mac,Buffer.from(e.mac,'hex'))) reject();
    const decipher = crypto.createDecipheriv('aes-256-cbc',Buffer.from(key.encHex,'hex'),Buffer.from(e.iv,'hex'));
    const plaintext = Buffer.concat([decipher.update(ciphertext),decipher.final()]);
    return { value: JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plaintext)), utf8Hex: plaintext.toString('hex') };
  } catch (_) { reject(); }
}
function encrypt(value, metadata, keys, iv) {
  const e = Object.fromEntries(fields.slice(0,-2).map(k=>[k,metadata[k]]));
  e.iv = iv;
  const cipher = crypto.createCipheriv('aes-256-cbc',Buffer.from(keys[e.direction].encHex,'hex'),Buffer.from(iv,'hex'));
  e.ciphertext = Buffer.concat([cipher.update(JSON.stringify(value),'utf8'),cipher.final()]).toString('base64');
  e.mac = crypto.createHmac('sha256',Buffer.from(keys[e.direction].macHex,'hex')).update(JSON.stringify(fields.map(k=>e[k])),'utf8').digest('hex');
  return e;
}
function run() {
  const file = process.argv[2] || path.join(__dirname,'../samples/roundtrip.json');
  const samples = JSON.parse(fs.readFileSync(file,'utf8'));
  let passed = 0, rejected = 0;
  for (const c of samples.cases) for (const dir of ['request','response']) {
    const sample = c[dir], e = sample.envelope;
    const expected = { ...e };
    const result = verify(e,samples.keys,expected);
    assert.deepEqual(result.value,sample.plaintext);
    assert.equal(result.utf8Hex,sample.plaintextUtf8Hex);
    assert.deepEqual(encrypt(sample.plaintext,e,samples.keys,e.iv),e);
    passed++;
    for (const field of ['iv','ciphertext','mac','ts','direction','nonce','fingerprint','requestId','challengeId','path','keyId']) {
      const bad = structuredClone(e);
      if (field === 'ts') bad[field]++;
      else if (field === 'direction') bad[field] = dir === 'request' ? 'response' : 'request';
      else bad[field] = (bad[field][0] === 'a' ? 'b' : 'a') + bad[field].slice(1);
      assert.throws(()=>verify(bad,samples.keys,expected),/INVALID_ENVELOPE/); rejected++;
    }
  }
  const result = { status: 'PASS', implementation: 'independent Node node:crypto / OpenSSL', node: process.version, openssl: process.versions.openssl, source: path.basename(file), envelopesVerified: passed, tamperedEnvelopesRejected: rejected };
  fs.writeFileSync(path.join(__dirname,'../evidence/node-independent.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
}
module.exports = { verify, encrypt };
if (require.main === module) run();
