// SPDX-License-Identifier: CC0-1.0
/* Local simulation adapter, authored for this case. Upstream CryptoJS stays unchanged. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./crypto-js-4.2.0.js'));
  else root.CaseCrypto = factory(root.CryptoJS);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
  'use strict';
  const ALG = 'AES-256-CBC+HMAC-SHA256';
  const FIELDS = ['v','alg','keyId','direction','requestId','method','path','ts','nonce','challengeId','fingerprint','iv','ciphertext'];
  const META = ['direction','requestId','method','path','ts','nonce','challengeId','fingerprint'];
  const CONTEXT = ['direction','requestId','method','path','nonce','challengeId','fingerprint'];
  const HEX32 = /^[0-9a-f]{32}$/;
  const HEX64 = /^[0-9a-f]{64}$/;
  function fail() { throw new Error('INVALID_ENVELOPE'); }
  function validate(e) {
    if (!e || typeof e !== 'object' || Array.isArray(e)) fail();
    const fields = Object.keys(e).sort().join(',');
    if (fields !== FIELDS.concat('mac').sort().join(',')) fail();
    if (e.v !== 1 || e.alg !== ALG || e.keyId !== 'demo-public-v1') fail();
    if (!['request','response'].includes(e.direction) || e.method !== 'POST' || e.path !== '/local-sim/echo') fail();
    for (const field of ['requestId','nonce','challengeId','iv']) if (typeof e[field] !== 'string' || !HEX32.test(e[field])) fail();
    if (typeof e.fingerprint !== 'string' || !HEX64.test(e.fingerprint) || typeof e.mac !== 'string' || !HEX64.test(e.mac)) fail();
    if (!Number.isSafeInteger(e.ts) || e.ts < 0) fail();
    if (typeof e.ciphertext !== 'string' || e.ciphertext.length > 1400000 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(e.ciphertext)) fail();
    const bytes = C.enc.Base64.parse(e.ciphertext);
    if (!bytes.sigBytes || bytes.sigBytes % 16 || bytes.toString(C.enc.Base64) !== e.ciphertext) fail();
  }
  function canonical(e) { return JSON.stringify(FIELDS.map(f => e[f])); }
  function keyFor(keys, direction) {
    const pair = keys && keys[direction];
    if (!pair || !HEX64.test(pair.encHex) || !HEX64.test(pair.macHex)) throw new Error('INVALID_DEMO_KEYS');
    return { enc: C.enc.Hex.parse(pair.encHex), mac: C.enc.Hex.parse(pair.macHex) };
  }
  function mac(e, key) { return C.HmacSHA256(C.enc.Utf8.parse(canonical(e)), key).toString(C.enc.Hex); }
  function seal(payload, metadata, keys, options = {}) {
    const key = keyFor(keys, metadata.direction);
    const e = { v: 1, alg: ALG, keyId: 'demo-public-v1' };
    for (const field of META) e[field] = metadata[field];
    e.iv = options.ivHex === undefined ? C.lib.WordArray.random(16).toString() : options.ivHex;
    if (typeof e.iv !== 'string' || !HEX32.test(e.iv)) fail();
    const text = JSON.stringify(payload);
    if (typeof text !== 'string') throw new Error('INVALID_JSON_PAYLOAD');
    e.ciphertext = C.AES.encrypt(C.enc.Utf8.parse(text), key.enc, {
      iv: C.enc.Hex.parse(e.iv), mode: C.mode.CBC, padding: C.pad.Pkcs7
    }).ciphertext.toString(C.enc.Base64);
    e.mac = '0'.repeat(64);
    validate(e);
    e.mac = mac(e, key.mac);
    return e;
  }
  function open(e, keys, expected) {
    try {
      validate(e);
      if (!expected || CONTEXT.some(k => expected[k] === undefined || expected[k] !== e[k])) fail();
      const key = keyFor(keys, e.direction);
      const actual = mac(e, key.mac);
      // Full-length compare. JavaScript JIT is NOT a constant-time guarantee.
      let mismatch = 0;
      for (let i = 0; i < 64; i++) mismatch |= actual.charCodeAt(i) ^ e.mac.charCodeAt(i);
      if (mismatch) fail();
      // Authenticate first; validate PKCS#7 explicitly (CryptoJS default unpad only truncates).
      const bytes = C.AES.decrypt({ ciphertext: C.enc.Base64.parse(e.ciphertext) }, key.enc, {
        iv: C.enc.Hex.parse(e.iv), mode: C.mode.CBC, padding: C.pad.NoPadding
      });
      const at = i => (bytes.words[i >>> 2] >>> (24 - (i % 4) * 8)) & 255;
      const n = at(bytes.sigBytes - 1);
      if (n < 1 || n > 16 || bytes.sigBytes < n) fail();
      for (let i = bytes.sigBytes - n; i < bytes.sigBytes; i++) if (at(i) !== n) fail();
      bytes.sigBytes -= n; bytes.clamp();
      return JSON.parse(C.enc.Utf8.stringify(bytes));
    } catch (_) { fail(); }
  }
  function context(e, direction = e.direction) {
    return Object.fromEntries(CONTEXT.map(k => [k, k === 'direction' ? direction : e[k]]));
  }
  return { seal, open, context, canonical, randomHex: () => C.lib.WordArray.random(16).toString(), sha256: text => C.SHA256(C.enc.Utf8.parse(text)).toString() };
});
