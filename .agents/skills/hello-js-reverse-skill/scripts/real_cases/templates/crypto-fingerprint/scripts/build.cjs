// SPDX-License-Identifier: CC0-1.0
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
process.chdir(root);
(async () => {
  fs.mkdirSync('assets', { recursive: true });
  fs.copyFileSync('vendor/crypto-js-source/crypto-js.js', 'assets/crypto-js-4.2.0.js');
  fs.copyFileSync('vendor/crypto-js-source/LICENSE', 'assets/LICENSE.crypto-js.txt');
  const license = fs.readFileSync('vendor/fingerprintjs-source/LICENSE', 'utf8');
  fs.writeFileSync('assets/LICENSE.fingerprintjs.txt', license);
  const result = await esbuild.build({
    entryPoints: ['vendor/fingerprintjs-source/src/index.ts'],
    outfile: 'assets/fingerprintjs-5.2.0.js', bundle: true,
    format: 'iife', globalName: 'FingerprintJS', platform: 'browser', target: 'firefox115',
    minify: false, sourcemap: true, metafile: true,
    banner: { js: '/*! FingerprintJS 5.2.0, original source e196578ba35362fdf15647e013d66ac28b3c9fb5.\n' + license + '\n*/' }
  });
  fs.writeFileSync('evidence/fingerprint-build-metafile.json', JSON.stringify(result.metafile, null, 2) + '\n');
  fs.writeFileSync('evidence/build.json', JSON.stringify({
    node: process.version, esbuild: esbuild.version, target: 'firefox115',
    fingerprintSourceUnmodified: true, cryptoBundle: 'byte-for-byte copy from pinned GitHub release tree',
    fingerprintBundle: 'local esbuild IIFE from original TypeScript; not the upstream Rollup release binary'
  }, null, 2) + '\n');
  console.log('Built local browser assets from pinned GitHub sources.');
})().catch(error => { console.error(error); process.exitCode = 1; });
