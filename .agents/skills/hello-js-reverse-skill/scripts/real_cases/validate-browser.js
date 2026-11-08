// SPDX-License-Identifier: CC0-1.0
// Expressions evaluated by the real MCP evaluate_js tool in the page main world.
({
  vm() {
    const report = RealCasesTest.run();
    return {...report, tapInstalled: !!window.__mcp_tap_installed};
  },
  async fingerprint() {
    const first = await collectFingerprint();
    const second = await collectFingerprint();
    return {first, second, stable: first.fingerprint === second.fingerprint,
      version: window.fingerprintOutput.version,
      visitorId: window.fingerprintOutput.visitorId,
      components: Object.keys(window.fingerprintOutput.components),
      monitoring: window.fingerprintOutput.monitoring,
      tapInstalled: !!window.__mcp_tap_installed};
  },
  async exchange() {
    const messages = ['GitHub真实CryptoJS 🔐', {unicode:'中文😀\u2028é', n:17, list:[null,true,0]}];
    const outputs = [];
    for (const message of messages) {
      const plain = await runExchange(message);
      const {request, response} = window.exchangeOutput;
      const keys = await (await fetch('/demo-keys')).json();
      const tampered = {...response, mac: (response.mac[0] === 'a' ? 'b' : 'a') + response.mac.slice(1)};
      let rejected = false;
      try { CaseCrypto.open(tampered, keys, CaseCrypto.context(request, 'response')); }
      catch (e) { rejected = e.message === 'INVALID_ENVELOPE'; }
      const replay = await fetch('/local-sim/echo', {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(request)});
      outputs.push({ok: plain.ok === true && JSON.stringify(plain.echo) === JSON.stringify(message)
          && plain.requestId === request.requestId && plain.fingerprint === request.fingerprint
          && response.iv !== request.iv && rejected,
        plain, request, response, tamperRejected: rejected,
        replayStatus: replay.status, replay: await replay.json()});
    }
    return {outputs, tapInstalled: !!window.__mcp_tap_installed};
  }
})
