// Task-authored business input, not a VM or obfuscator implementation.
// SPDX-License-Identifier: CC0-1.0
function numericLedger(values, state) {
    var unsigned = 0;
    var signed = 0;
    var reciprocals = [];
    var ticks = state.ticks;
    var previous = ticks;
    for (var i = 0; i < values.length; i++) {
        var value = values[i];
        state.events.push('value:' + i + ':' + value);
        state.total = state.total + value;
        unsigned = (unsigned + (value >>> 0)) >>> 0;
        signed = value | 0;
        reciprocals.push(1 / value);
        previous = ticks++;
        state.ticks = ticks;
    }
    state.calls = state.calls + 1;
    state.events.push('done:' + state.ticks);
    return { 'total': state.total, 'unsigned': unsigned, 'signed': signed, 'reciprocals': reciprocals, 'previous': previous, 'ticks': state.ticks, 'calls': state.calls };
}
module.exports = numericLedger;
