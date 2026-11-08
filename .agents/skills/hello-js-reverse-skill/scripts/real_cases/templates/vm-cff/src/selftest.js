// Task-authored test harness. SPDX-License-Identifier: CC0-1.0
(function(g) {
    function normalize(x) {
        if (typeof x === 'number') {
            if (Number.isNaN(x)) return {$number:'NaN'};
            if (Object.is(x, -0)) return {$number:'-0'};
            if (x === Infinity) return {$number:'Infinity'};
            if (x === -Infinity) return {$number:'-Infinity'};
            return x;
        }
        if (x === undefined) return {$undefined:true};
        if (Array.isArray(x)) return x.map(normalize);
        if (x && typeof x === 'object') {
            var out = {};
            Object.keys(x).sort().forEach(function(k) { out[k] = normalize(x[k]); });
            return out;
        }
        return x;
    }
    function equal(a,b) { return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b)); }
    function unicodeState() { return {nonAscii:0, calls:0, last:null, events:[]}; }
    function numericState() { return {total:0, ticks:0, calls:0, events:[]}; }
    function cases() {
        var result = [];
        ['', 'ASCII', '中文😀e\u0301', '\u0000\u00ff\u0100', '\ud800X\udfff', 'مرحبا', '𝄞👩‍💻', 'A'.repeat(257)].forEach(function(text, i) {
            result.push({id:'unicode-'+i, method:'unicodeDigest', make:function() { return [text, [0,-1,4294967296,9007199254740991][i%4], unicodeState()]; }});
        });
        [[], [0,-0], [2147483647,2147483648,4294967295,4294967296,-1],
         [0.5,-0.5,1.5,-1.5], [9007199254740991,1,-9007199254740991],
         [Number.MIN_VALUE,Number.MAX_VALUE,-Number.MAX_VALUE],
         [NaN,Infinity,-Infinity], [107,256,65535,-2147483649]].forEach(function(values,i) {
            result.push({id:'numeric-'+i, method:'numericLedger', make:function() { return [values.slice(), numericState()]; }});
        });
        [['This is a string','is'], ['😀😀中文😀','😀'], ['aaaa','aa'], ['', ''], ['abc',''],
         ['\ud800X\ud800','\ud800']].forEach(function(args,i) {
            result.push({id:'upstream-substring-'+i,method:'countSubstrings',make:function() { return args.slice(); }});
        });
        return result;
    }
    function run() {
        var rows = [], failures = [];
        var names = ['RealCasesVM','RealCasesCFF','RealCasesNoCFF'];
        cases().forEach(function(test) {
            var args = test.make();
            var expected = g.RealCasesPlain[test.method].apply(null,args);
            var expectedState = normalize(args);
            names.forEach(function(name) {
                var input = test.make();
                var before = normalize(input);
                try {
                    var actual = g[name][test.method].apply(null,input);
                    var pass = equal(actual,expected) && equal(input,args);
                    var row = {id:test.id,method:test.method,variant:name,pass:pass,input:before,
                        expected:normalize(expected),actual:normalize(actual),expectedArgumentsAfter:expectedState,actualArgumentsAfter:normalize(input)};
                    rows.push(row); if (!pass) failures.push(row);
                } catch(e) { var row={id:test.id,variant:name,pass:false,error:String(e)}; rows.push(row); failures.push(row); }
            });
        });
        // Reuse each mutable state over consecutive calls; include observable setter order.
        names.forEach(function(name) {
            ['unicodeDigest','numericLedger'].forEach(function(method) {
                function sequence(api) {
                    var state = method === 'unicodeDigest' ? unicodeState() : numericState();
                    var writes = [], value = state.calls;
                    Object.defineProperty(state,'calls',{enumerable:true,configurable:true,get:function(){return value;},set:function(v){writes.push(v); value=v;}});
                    var events = state.events;
                    var outputs = [];
                    for (var n=0;n<3;n++) outputs.push(method === 'unicodeDigest' ? api[method]('中😀'+n,n,state) : api[method]([n,-0,4294967296],state));
                    return {outputs:outputs,state:state,writes:writes,eventsIdentity:events===state.events};
                }
                try {
                    var expected=sequence(g.RealCasesPlain), actual=sequence(g[name]);
                    var row={id:'repeated-setter-'+method,variant:name,pass:equal(expected,actual),expected:normalize(expected),actual:normalize(actual)};
                    rows.push(row); if(!row.pass) failures.push(row);
                } catch(e) { var row={id:'repeated-setter-'+method,variant:name,pass:false,error:String(e)}; rows.push(row); failures.push(row); }
            });
        });
        // Independent simple expected values, in addition to baseline differential tests.
        ['RealCasesPlain'].concat(names).forEach(function(name) {
            var s=unicodeState(), output=g[name].unicodeDigest('A',0,s);
            var pass=equal(output,{length:1,units:[65],hash:65,calls:1}) && equal(s,{nonAscii:0,calls:1,last:65,events:['digest:1:65']}) && g[name].countSubstrings('aaaa','aa')===3;
            var row={id:'known-answer-A-and-overlap',variant:name,pass:pass}; rows.push(row); if(!pass) failures.push(row);
        });
        return {ok:failures.length===0,total:rows.length,passed:rows.filter(function(x){return x.pass;}).length,failed:failures.length,rows:rows,failures:failures};
    }
    g.RealCasesTest={run:run, normalize:normalize, cases:cases};
})(globalThis);
