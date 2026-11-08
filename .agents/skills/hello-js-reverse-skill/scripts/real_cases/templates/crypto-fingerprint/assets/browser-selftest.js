// SPDX-License-Identifier: CC0-1.0
/* The page stays offline. No HTTP service or remote API is used. */
(async function () {
  const status=document.getElementById('status'), output=document.getElementById('result');
  const violations=[];
  document.addEventListener('securitypolicyviolation',e=>violations.push({blockedURI:e.blockedURI,violatedDirective:e.violatedDirective}));
  function equal(a,b){if(JSON.stringify(a)!==JSON.stringify(b))throw Error('assertion mismatch');}
  try {
    let verified=0,rejected=0;
    for(const c of CaseFixtures.cases)for(const dir of ['request','response']){
      const s=c[dir];equal(CaseCrypto.open(s.envelope,CaseFixtures.keys,CaseCrypto.context(s.envelope)),s.plaintext);verified++;
      for(const field of ['iv','ciphertext','mac']){
        const bad={...s.envelope,[field]:(s.envelope[field][0]==='a'?'b':'a')+s.envelope[field].slice(1)};
        let denied=false;try{CaseCrypto.open(bad,CaseFixtures.keys,CaseCrypto.context(s.envelope));}catch(e){denied=e.message==='INVALID_ENVELOPE';}
        if(!denied)throw Error('Tampering was accepted');rejected++;
      }
    }
    const first=await CaseFingerprint.collect();
    const second=await CaseFingerprint.collect();
    if(first.version!=='5.2.0'||!/^[a-f0-9]{32}$/.test(first.visitorId)||Object.keys(first.components).length<30)throw Error('FingerprintJS did not collect real components');
    const original=CaseFixtures.cases[1];
    const metadata={...original.request.envelope,ts:Date.now(),requestId:CaseCrypto.randomHex(),nonce:CaseCrypto.randomHex(),challengeId:CaseCrypto.randomHex(),fingerprint:first.fingerprint};
    const request=CaseCrypto.seal(original.request.plaintext,metadata,CaseFixtures.keys);
    const response=CaseCrypto.seal(original.response.plaintext,{...metadata,direction:'response',ts:Date.now()},CaseFixtures.keys);
    equal(CaseCrypto.open(request,CaseFixtures.keys,CaseCrypto.context(request)),original.request.plaintext);
    equal(CaseCrypto.open(response,CaseFixtures.keys,CaseCrypto.context(request,'response')),original.response.plaintext);
    const result={status:'PASS',userAgent:navigator.userAgent,crypto:{verified,rejected},
      fingerprint:first,repeat:{sameVisitorId:first.visitorId===second.visitorId,sameSubset:first.fingerprint===second.fingerprint,secondVisitorId:second.visitorId,secondFingerprint:second.fingerprint},
      browserGenerated:{keys:CaseFixtures.keys,cases:[{name:'firefox-unicode-live',request:{plaintext:original.request.plaintext,plaintextUtf8Hex:CryptoJS.enc.Utf8.parse(JSON.stringify(original.request.plaintext)).toString(),envelope:request},response:{plaintext:original.response.plaintext,plaintextUtf8Hex:CryptoJS.enc.Utf8.parse(JSON.stringify(original.response.plaintext)).toString(),envelope:response}}]},violations};
    globalThis.__caseResult=result;
    status.textContent='PASS · 离线加密往返与 FingerprintJS 采集完成';status.dataset.state='pass';
    output.textContent=JSON.stringify(result,null,2);
  }catch(e){globalThis.__caseResult={status:'FAIL',error:String(e.stack||e),violations};status.textContent='FAIL · '+e.message;status.dataset.state='fail';output.textContent=JSON.stringify(globalThis.__caseResult,null,2);}
})();
