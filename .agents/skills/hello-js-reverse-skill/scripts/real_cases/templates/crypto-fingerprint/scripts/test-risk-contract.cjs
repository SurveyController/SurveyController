// SPDX-License-Identifier: CC0-1.0
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const r=require('./risk-contract.cjs');
const {keys,cases}=require('../samples/roundtrip.json');
const sdk=require('../assets/case-crypto.js');
const e=cases[1].request.envelope, now=e.ts;
const challenge=r.issue({id:e.challengeId,requestId:e.requestId,fingerprint:e.fingerprint,now:now-1000});
const payload={challengeAnswer:r.answer(challenge.id,e.nonce,e.fingerprint),message:'本地模拟🔐'};
const request=sdk.seal(payload,e,keys);
const opened=sdk.open(request,keys,sdk.context(e));
const base={challenge,usedNonces:{},envelope:request,payload:opened,now};
const accepted=r.evaluate(base);assert.equal(accepted.code,'ACCEPT');assert.equal(challenge.used,false);
const tests=[
 ['replay same challenge',{challenge:accepted.nextChallenge,usedNonces:accepted.nextNonces},'CHALLENGE_USED'],
 ['replay nonce under unconsumed challenge',{usedNonces:accepted.nextNonces},'NONCE_REPLAY'],
 ['expired challenge',{now:challenge.expiresAt},'CHALLENGE_EXPIRED'],
 ['future clock',{envelope:{...request,ts:now+30001}},'STALE_TIMESTAMP'],
 ['stale timestamp',{envelope:{...request,ts:now-30001}},'STALE_TIMESTAMP'],
 ['fingerprint changed',{envelope:{...request,fingerprint:'aa'.repeat(32)}},'FINGERPRINT_MISMATCH'],
 ['unknown challenge',{challenge:null},'UNKNOWN_CHALLENGE'],
 ['wrong challenge answer',{payload:{challengeAnswer:'00'.repeat(32)}},'BAD_ANSWER'],
 ['wrong request binding',{envelope:{...request,requestId:'ee'.repeat(16)}},'UNKNOWN_CHALLENGE'],
 ['empty nonce',{envelope:{...request,nonce:''}},'MALFORMED'],
 ['wrong direction',{envelope:{...request,direction:'response'}},'BAD_CONTEXT']
];
for(const [name,patch,code] of tests){const result=r.evaluate({...base,...patch});assert.equal(result.code,code,name);assert.equal(result.accepted,false);assert.equal(result.nextChallenge,undefined);}
const result={status:'PASS',accepted:1,rejections:tests.map(([name,,code])=>({name,code})),scope:'local simulation only, no commercial risk-control reproduction; pure reference functions, no service'};
fs.writeFileSync(path.join(__dirname,'../evidence/risk-contract-selftest.json'),JSON.stringify(result,null,2)+'\n');
fs.writeFileSync(path.join(__dirname,'../samples/risk-contract.json'),JSON.stringify({warning:result.scope,challenge,request,payload,expectedDecision:'ACCEPT',now},null,2)+'\n');
console.log(JSON.stringify(result));
