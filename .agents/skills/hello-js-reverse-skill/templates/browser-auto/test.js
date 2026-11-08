const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {extractPageData,goToNextPage}=require('./main');
test('extracts numeric rows using a local DOM fixture', async () => {
    const page={evaluate: async fn => vm.runInNewContext(`(${fn})()`, {
        document:{querySelectorAll:()=>['12.5',' 7 ',null].map(value=>({querySelector:()=>({textContent:value})}))}
    })};
    assert.equal(JSON.stringify(await extractPageData(page,1)),JSON.stringify([12.5,7,0]));
});
test('pagination awaits the click and load state', async () => {
    const calls=[];
    await goToNextPage({click:async s=>calls.push(s),waitForLoadState:async s=>calls.push(s)},2);
    assert.deepEqual(calls,['.pagination a:has-text("2")','networkidle']);
});
