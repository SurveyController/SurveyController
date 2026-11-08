// SPDX-License-Identifier: CC0-1.0
'use strict';
// PURE REFERENCE CONTRACT. No listener, routes, timers, cookies or persistence.
// Main Agent must call after successful MAC verification + decryption.
const {createHash} = require('node:crypto');
const ID=/^[a-f0-9]{32}$/, FP=/^[a-f0-9]{64}$/;
const TTL=120000, SKEW=30000;
function answer(challengeId, nonce, fingerprint) {
  return createHash('sha256').update(JSON.stringify(['local-challenge-v1',challengeId,nonce,fingerprint]),'utf8').digest('hex');
}
function issue({id,requestId,fingerprint,now}) {
  if (!ID.test(id) || !ID.test(requestId) || !FP.test(fingerprint) || !Number.isSafeInteger(now) || now < 0 || !Number.isSafeInteger(now+TTL)) throw Error('BAD_CHALLENGE_INPUT');
  return {schema:'local-challenge-v1',id,requestId,fingerprint,issuedAt:now,expiresAt:now+TTL,used:false};
}
function evaluate({challenge,usedNonces={},envelope,payload,now}) {
  const deny = code => ({accepted:false,code});
  if (!Number.isSafeInteger(now) || now < 0 || !envelope || !ID.test(envelope.nonce || '') || !Number.isSafeInteger(envelope.ts)) return deny('MALFORMED');
  if (envelope.direction !== 'request' || envelope.method !== 'POST' || envelope.path !== '/local-sim/echo') return deny('BAD_CONTEXT');
  if (!challenge || challenge.schema !== 'local-challenge-v1' || challenge.id !== envelope.challengeId || challenge.requestId !== envelope.requestId) return deny('UNKNOWN_CHALLENGE');
  if (now < challenge.issuedAt || now >= challenge.expiresAt) return deny('CHALLENGE_EXPIRED');
  if (Math.abs(now-envelope.ts) > SKEW || envelope.ts < challenge.issuedAt || envelope.ts >= challenge.expiresAt) return deny('STALE_TIMESTAMP');
  if (challenge.used) return deny('CHALLENGE_USED');
  if ((usedNonces[envelope.nonce] || 0) > now) return deny('NONCE_REPLAY');
  if (envelope.fingerprint !== challenge.fingerprint) return deny('FINGERPRINT_MISMATCH');
  if (!payload || payload.challengeAnswer !== answer(challenge.id,envelope.nonce,envelope.fingerprint)) return deny('BAD_ANSWER');
  // Copy-on-accept, no state changes on rejection. Main service must atomically CAS these states.
  return {accepted:true,code:'ACCEPT',nextChallenge:{...challenge,used:true},nextNonces:{...usedNonces,[envelope.nonce]:now+TTL}};
}
module.exports={answer,issue,evaluate,TTL,SKEW};
