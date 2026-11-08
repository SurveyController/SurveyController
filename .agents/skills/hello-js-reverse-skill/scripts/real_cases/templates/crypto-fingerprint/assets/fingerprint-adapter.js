// SPDX-License-Identifier: CC0-1.0
/* Local-only adapter. Call load({monitoring:false}) on every initialization. */
(function (root) {
  'use strict';
  const selected = ['platform','languages','timezone','colorDepth','hardwareConcurrency','pdfViewerEnabled'];
  let agent;
  function component(value) {
    if ('error' in value) return { status: 'error', error: String(value.error && (value.error.message || value.error)) };
    if (value.value === undefined) return { status: 'unavailable' };
    return { status: 'value', value: value.value };
  }
  async function collect() {
    agent = agent || root.FingerprintJS.load({ monitoring: false, debug: false });
    const result = await (await agent).get();
    const components = Object.fromEntries(Object.entries(result.components).map(([k, v]) => [k, { ...component(v), durationMs: v.duration }]));
    const stableInput = { schema: 'local-fp-subset-v1', sdkVersion: result.version,
      fields: selected.map(k => [k, component(result.components[k] || {})]) };
    return {
      sdk: 'FingerprintJS', version: result.version, visitorId: result.visitorId,
      confidence: result.confidence, components, stableInput,
      fingerprint: root.CaseCrypto.sha256(JSON.stringify(stableInput)),
      observedAt: Date.now(), monitoring: false
    };
  }
  root.CaseFingerprint = { collect, selected: selected.slice() };
})(globalThis);
