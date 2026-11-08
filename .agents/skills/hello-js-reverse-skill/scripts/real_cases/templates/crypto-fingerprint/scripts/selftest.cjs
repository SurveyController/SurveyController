// SPDX-License-Identifier: CC0-1.0
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const sdk = require('../assets/case-crypto.js');
const independent = require('./verify-node.cjs');
const { keys, cases } = require('../samples/roundtrip.json');
let checks = 0;
function check(name, fn) { fn(); checks++; }
const e = cases[1].request.envelope;
for (const c of cases) for (const dir of ['request','response']) {
  const sample = c[dir], env = sample.envelope;
  check(`${c.name}/${dir} decrypt`, () => assert.deepEqual(sdk.open(env,keys,sdk.context(env)),sample.plaintext));
  check(`${c.name}/${dir} Node->CryptoJS`, () => {
    const fromNode = independent.encrypt(sample.plaintext,env,keys,crypto.randomBytes(16).toString('hex'));
    assert.deepEqual(sdk.open(fromNode,keys,sdk.context(env)),sample.plaintext);
  });
  for (const field of Object.keys(env)) check(`${c.name}/${dir}/tamper:${field}`, () => {
    const bad = structuredClone(env);
    if (typeof bad[field] === 'number') bad[field]++;
    else bad[field] = (bad[field][0] === 'a' ? 'b' : 'a') + bad[field].slice(1);
    assert.throws(()=>sdk.open(bad,keys,sdk.context(env)),/INVALID_ENVELOPE/);
  });
}
check('CSPRNG fresh IV', () => {
  const a = sdk.seal({same:'中文'},e,keys), b = sdk.seal({same:'中文'},e,keys);
  assert.notEqual(a.iv,b.iv); assert.notEqual(a.ciphertext,b.ciphertext);
  assert.deepEqual(independent.verify(a,keys,sdk.context(e)).value,{same:'中文'});
});
check('wrong MAC key', () => {
  const bad = structuredClone(keys); bad.request.macHex = '00'.repeat(32);
  assert.throws(()=>sdk.open(e,bad,sdk.context(e)),/INVALID_ENVELOPE/);
});
check('response reflection', () => assert.throws(()=>sdk.open(e,keys,sdk.context(e,'response')),/INVALID_ENVELOPE/));
check('extra field', () => assert.throws(()=>sdk.open({...e,extra:true},keys,sdk.context(e)),/INVALID_ENVELOPE/));
check('noncanonical base64', () => assert.throws(()=>sdk.open({...e,ciphertext:e.ciphertext+'\n'},keys,sdk.context(e)),/INVALID_ENVELOPE/));
check('missing expected binding', () => assert.throws(()=>sdk.open(e,keys),/INVALID_ENVELOPE/));
function signedRaw(plaintext) {
  const bad = structuredClone(e);
  const cipher = crypto.createCipheriv('aes-256-cbc',Buffer.from(keys.request.encHex,'hex'),Buffer.from(e.iv,'hex'));
  cipher.setAutoPadding(false);
  bad.ciphertext = Buffer.concat([cipher.update(plaintext),cipher.final()]).toString('base64');
  bad.mac = crypto.createHmac('sha256',Buffer.from(keys.request.macHex,'hex')).update(sdk.canonical(bad)).digest('hex');
  return bad;
}
check('authenticated but invalid PKCS#7', () => {
  const bad = signedRaw(Buffer.alloc(16,0));
  assert.throws(()=>sdk.open(bad,keys,sdk.context(e)),/INVALID_ENVELOPE/);
  assert.throws(()=>independent.verify(bad,keys,sdk.context(e)),/INVALID_ENVELOPE/);
});
check('authenticated but malformed UTF8', () => {
  const raw = Buffer.alloc(16,15); raw[0]=0xff;
  const bad = signedRaw(raw);
  assert.throws(()=>sdk.open(bad,keys,sdk.context(e)),/INVALID_ENVELOPE/);
  assert.throws(()=>independent.verify(bad,keys,sdk.context(e)),/INVALID_ENVELOPE/);
});
const result = {status:'PASS', checks, implementation:'CryptoJS adapter, cross-checked with independent Node crypto', includes:['Unicode','combining marks','NUL','empty JSON string','block boundaries','all envelope fields tampered','direction binding','fresh IV','strict PKCS7','strict UTF8']};
fs.writeFileSync(path.join(__dirname,'../evidence/crypto-selftest.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));
