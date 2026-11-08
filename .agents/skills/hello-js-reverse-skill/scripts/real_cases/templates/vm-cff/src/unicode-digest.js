// Task-authored business input, not a VM or obfuscator implementation.
// SPDX-License-Identifier: CC0-1.0
function unicodeDigest(text, salt, state) {
    var hash = salt >>> 0;
    var length = text.length;
    var units = [];
    for (var i = 0; i < length; i++) {
        var unit = text.charCodeAt(i);
        units.push(unit);
        if (unit > 127) {
            state.nonAscii = state.nonAscii + 1;
        }
        hash = ((hash * 33) ^ unit) >>> 0;
    }
    state.calls = state.calls + 1;
    state.last = hash;
    state.events.push('digest:' + length + ':' + hash);
    return { 'length': length, 'units': units, 'hash': hash, 'calls': state.calls };
}
module.exports = unicodeDigest;
