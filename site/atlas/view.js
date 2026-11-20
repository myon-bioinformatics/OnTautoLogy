import {renderDiagram} from '../shared/mermaid.js';
const el = id => document.getElementById(id);
const slug = new URLSearchParams(location.search).get('set');
let data, selected, page, version = 0;
async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw Error('資料を取得できませんでした。');
  return response.json();
}
function options() {
  const query = el('filter').value.toLocaleLowerCase();
  const select = el('nodes');
  select.replaceChildren();
  data.nodes.forEach(([name, uri], index) => {
    if ((name+' '+uri).toLocaleLowerCase().includes(query)) select.add(new Option(name, index));
  });
  if (select.options.length) {
    if (![...select.options].some(o => +o.value === selected)) selected = +select.value;
    select.value = selected;
  }
}
async function render() {
  const ticket = ++version;
  el('diagram').replaceChildren();
  el('relations').replaceChildren();
  el('status').textContent = '';
  el('page').textContent = el('uri').textContent = '';
  el('prev').disabled = el('next').disabled = true;
  if (!el('nodes').options.length) { el('status').textContent='該当するノードはありません。'; return; }
  try {
    const group = await get(slug+'/'+Math.floor(selected/32)+'.json');
    if (ticket !== version) return;
    const pages = group[selected%32], current = pages[page];
    el('uri').textContent = data.nodes[selected][1];
    el('page').textContent = (page+1)+' / '+pages.length;
    el('prev').disabled = page === 0;
    el('next').disabled = page+1 === pages.length;
    for (const [predicate, value, target, outgoing] of current.edges) {
      const item = document.createElement('li');
      item.append(outgoing ? '→ '+predicate+' → ' : '← '+predicate+' ← ');
      if (target == null) item.append(value);
      else {
        const link = document.createElement('a');
        link.href='#'+target;
        link.textContent=value;
        item.append(link);
      }
      el('relations').append(item);
    }
    try {
      const svg = await renderDiagram('focus-'+ticket, current.diagram);
      if (ticket === version) el('diagram').innerHTML = svg;
    } catch {
      if (ticket === version) el('status').textContent = '図を読み込めませんでした。関係と値は一覧で確認できます。';
    }
  } catch (error) { if (ticket === version) el('status').textContent = error.message; }
}
function focus() {
  const id = Number(location.hash.slice(1));
  selected = location.hash && Number.isInteger(id) && data.nodes[id] ? id : data.start;
  page=0; el('filter').value=''; options(); render();
}
try {
  if (!/^[\w-]+$/.test(slug ?? '')) throw Error('一覧から資料を選んでください。');
  data = await get(slug+'.json');
  el('title').textContent = document.title = data.title;
  el('ttl').href=slug+'.ttl';
  el('nodes').onchange = () => { location.hash=el('nodes').value; };
  el('filter').oninput = () => { page=0; options(); render(); };
  el('prev').onclick = () => { --page; render(); };
  el('next').onclick = () => { ++page; render(); };
  window.addEventListener('hashchange',focus);
  focus();
} catch(error) { el('status').textContent=error.message; }
