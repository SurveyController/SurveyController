// SPDX-License-Identifier: CC0-1.0
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const sdk = require('../assets/case-crypto.js');
const keys = { warning: 'PUBLIC DEMO KEYS ONLY. Never use for real data.', keyId: 'demo-public-v1' };
for (const [i, direction] of ['request','response'].entries()) keys[direction] = {
  encHex: sdk.sha256(`PUBLIC local-case ${direction} AES key ${i}`),
  macHex: sdk.sha256(`PUBLIC local-case ${direction} HMAC key ${i}`)
};
const meta = { direction: 'request', requestId: '11'.repeat(16), method: 'POST', path: '/local-sim/echo',
  ts: 1788825600000, nonce: '22'.repeat(16), challengeId: '33'.repeat(16), fingerprint: sdk.sha256('synthetic fingerprint fixture; not a real browser') };
const payloads = [
  { name: 'ascii', request: { message: 'hello local open source', count: 3 }, response: { ok: true, echo: 'hello local open source' } },
  { name: 'unicode', request: { message: '中文🔐 café e\u0301 العربية 日本語 👩🏽‍💻', nested: { text: '换行\n制表\tNUL\u0000', list: [null, true, 0] } }, response: { ok: true, reply: '响应已验签✅，往返完成🚀', combining: 'é|e\u0301', music: '𝄞' } },
  { name: 'empty-string', request: '', response: '' },
  { name: 'block-boundary', request: 'a'.repeat(14), response: 'b'.repeat(30) }
];
const cases = payloads.map((p, i) => {
  const request = sdk.seal(p.request, { ...meta, requestId: (11 + i).toString(16).padStart(32,'0') }, keys, { ivHex: i.toString(16).padStart(32, '0') });
  const response = sdk.seal(p.response, { ...request, direction: 'response', ts: meta.ts + 50 }, keys, { ivHex: (i+16).toString(16).padStart(32,'0') });
  return { name: p.name, request: { plaintext: p.request, plaintextUtf8Hex: Buffer.from(JSON.stringify(p.request)).toString('hex'), envelope: request },
    response: { plaintext: p.response, plaintextUtf8Hex: Buffer.from(JSON.stringify(p.response)).toString('hex'), envelope: response } };
});
fs.writeFileSync(path.join(root,'samples/demo-keys.json'), JSON.stringify(keys,null,2)+'\n');
const samples = { schema: 'local-crypto-fixtures-v1', note: 'Synthetic application messages encrypted by REAL CryptoJS 4.2.0. Fixed IVs/timestamps ONLY for deterministic vectors.', keys, cases };
fs.writeFileSync(path.join(root,'samples/roundtrip.json'), JSON.stringify(samples,null,2)+'\n');
fs.writeFileSync(path.join(root,'assets/demo-fixtures.js'), '/* Public synthetic fixtures; no production keys. */\nglobalThis.CaseFixtures = '+JSON.stringify(samples,null,2)+';\n');
console.log(`Generated ${cases.length} encrypted request/response pairs.`);
