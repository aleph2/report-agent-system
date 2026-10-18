// Read-only review probe: actual learning.js, isolated DOM and mocked HTTP only.
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const scriptPath = path.join(root, 'src/report_agent/static/learning.js');
const source = fs.readFileSync(scriptPath, 'utf8');
const nodes = new Map(), posts = [];
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this._value = ''; this.checked = false; this.disabled = false; }
  set value(v) { this._value = String(v); }
  get value() { return this._value; }
  append(...items) { this.children.push(...items); if (this.tag === 'select' && this.children.length && !this._value) this.value = this.children[0].value; }
  replaceChildren(...items) { this.children = []; this._value = ''; this.append(...items); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelectorAll(selector) {
    const all = []; const walk = n => { if (n.tag === 'input' && (selector !== 'input:checked' || n.checked)) all.push(n); for (const c of n.children) walk(c); };
    walk(this); return all;
  }
}
const html = fs.readFileSync(path.join(root, 'src/report_agent/static/index.html'), 'utf8');
for (const m of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) nodes.set(m[3], new Node(m[1]));
const snapshotRef = {type:'DocumentSnapshot',id:'snapshot-A',version:1};
const targetRef = {type:'ContentNode',id:'specific-table-B',version:1};
const sourceRef = {type:'SourceArtifact',id:'source-C',version:1};
const context = vm.createContext({
  document: {getElementById: id => nodes.get(id), createElement: tag => new Node(tag), createTextNode: text => ({textContent:text,children:[]})},
  fetch: async (url, options) => {
    if (options?.method === 'POST') { posts.push({url,body:JSON.parse(options.body)}); return {ok:true,json:async()=>({})}; }
    const data = url === '/api/learning' ? {feedback:[],experience:[]}
      : url === '/api/learning/reports' ? {reports:[{ref:snapshotRef,created_at:'test',targets:[{ref:snapshotRef,payload:{},label:'whole'},{ref:targetRef,payload:{},label:'table'}]}]}
      : {items:[{ref:sourceRef,label:'source',excerpt:'source excerpt'}]};
    return {ok:true,json:async()=>data};
  },
});
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  vm.runInContext(source, context); await flush();
  nodes.get('learning-target').value = '1';
  nodes.get('learning-target').listeners.change();
  nodes.get('learning-correction').value = 'Correct this particular table using the selected source.';
  nodes.get('learning-evidence-list').querySelectorAll('input')[0].checked = true;
  const before = {targetIndex:nodes.get('learning-target').value,correction:nodes.get('learning-correction').value,checkedEvidence:nodes.get('learning-evidence-list').querySelectorAll('input:checked').length};
  await nodes.get('learning-refresh').listeners.click();
  const after = {targetIndex:nodes.get('learning-target').value,correction:nodes.get('learning-correction').value,checkedEvidence:nodes.get('learning-evidence-list').querySelectorAll('input:checked').length};
  nodes.get('learning-form').listeners.submit({preventDefault(){}}); await flush();
  const result = {probe:'Explicit refresh during feedback editing changes target and drops selected evidence',method:'actual JS in offline VM, minimal DOM model; no browser rendering or network',source:'src/report_agent/static/learning.js',sha256:crypto.createHash('sha256').update(source).digest('hex'),before,after,posts};
  fs.writeFileSync(path.join(__dirname,'main-ui-diagnostic.json'), JSON.stringify(result,null,2)+'\n');
  process.stdout.write(JSON.stringify(result,null,2)+'\n');
})();
