/* web-ui scroll: ‹ › buttons, edge fades and (tables) a top scrollbar for every [data-ui-scroll="row"|"table"] (scroll_html). No dependencies, nothing stored or sent; scroll.css draws it. */
const mounted=new WeakSet(),states=new Set();
let identity=0,scheduled=false,watching=false;
const LABELS={row:"横スクロール",table:"表",suffix:"（横スクロール）",hint:"表を横に移動",top:"表ヘッダーの横スクロール",left:"を左へスクロール",right:"を右へスクロール"};
export function refreshScroll(){
  scheduled=false;
  for(const state of states){
    if(!state.viewport.isConnected){state.observer?.disconnect();states.delete(state);continue}
    const {viewport,shell,toolbar,top,spacer,previous,next}=state;
    const maximum=Math.max(0,viewport.scrollWidth-viewport.clientWidth),overflow=maximum>1;
    shell.classList.toggle("ui-scroll-over",overflow);
    shell.classList.toggle("ui-scroll-left",overflow&&viewport.scrollLeft>1);
    shell.classList.toggle("ui-scroll-right",overflow&&viewport.scrollLeft<maximum-1);
    previous.disabled=!overflow||viewport.scrollLeft<=1;
    next.disabled=!overflow||viewport.scrollLeft>=maximum-1;
    if(previous.hidden!==!overflow)previous.hidden=!overflow;
    if(next.hidden!==!overflow)next.hidden=!overflow;
    if(toolbar){
      if(toolbar.hidden!==!overflow)toolbar.hidden=!overflow;
      // Both scrollbars need the same range, even though the toolbar also holds the buttons.
      spacer.style.width=`${maximum+top.clientWidth}px`;
      if(Math.abs(top.scrollLeft-viewport.scrollLeft)>1)top.scrollLeft=viewport.scrollLeft;
    }
  }
}
const schedule=()=>{if(!scheduled){scheduled=true;requestAnimationFrame(refreshScroll)}};
function bindKeys(control,viewport){
  control.addEventListener("keydown",event=>{
    // Text fields, selects and other children keep their own arrow / Home / End keys.
    if(event.target!==control||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return;
    if(event.key==="ArrowLeft"||event.key==="ArrowRight")viewport.scrollLeft+=event.key==="ArrowLeft"?-100:100;
    else if(event.key==="Home")viewport.scrollLeft=0;
    else if(event.key==="End")viewport.scrollLeft=viewport.scrollWidth;
    else return;
    event.preventDefault();
    if(control!==viewport)control.scrollLeft=viewport.scrollLeft;
    schedule();
  });
}
function enhance(viewport,labels){
  if(mounted.has(viewport))return;
  mounted.add(viewport);
  const table=viewport.dataset.uiScroll==="table",label=viewport.dataset.scrollLabel||(table?labels.table:labels.row);
  const shell=document.createElement("div");
  shell.className=table?"ui-scroll ui-scroll-table":"ui-scroll ui-scroll-row";
  viewport.before(shell);shell.append(viewport);
  if(!viewport.id)viewport.id=`ui-scroll-${++identity}`;
  if(!viewport.hasAttribute("tabindex"))viewport.tabIndex=0;
  if(!viewport.hasAttribute("aria-label"))viewport.setAttribute("aria-label",label+labels.suffix);
  if(table)viewport.setAttribute("role","region");
  const state={viewport,shell};
  const arrow=direction=>{
    const button=document.createElement("button");
    button.type="button";button.className="ui-scroll-arrow";button.textContent=direction<0?"‹":"›";
    button.setAttribute("aria-label",label+(direction<0?labels.left:labels.right));
    button.setAttribute("aria-controls",viewport.id);
    button.addEventListener("click",()=>viewport.scrollBy({left:direction*Math.max(120,viewport.clientWidth*.7),behavior:"auto"}));
    return button;
  };
  state.previous=arrow(-1);state.next=arrow(1);
  if(table){
    const toolbar=document.createElement("div"),hint=document.createElement("span"),top=document.createElement("div"),spacer=document.createElement("div");
    toolbar.className="ui-scroll-bar";hint.className="ui-scroll-hint";hint.textContent=labels.hint;
    top.className="ui-scroll-top";top.tabIndex=0;top.setAttribute("role","region");top.setAttribute("aria-label",labels.top);top.setAttribute("aria-controls",viewport.id);
    spacer.className="ui-scroll-spacer";top.append(spacer);
    toolbar.append(hint,state.previous,top,state.next);shell.prepend(toolbar);
    Object.assign(state,{toolbar,top,spacer});
    top.addEventListener("scroll",()=>{if(Math.abs(viewport.scrollLeft-top.scrollLeft)>1)viewport.scrollLeft=top.scrollLeft;schedule()},{passive:true});
    bindKeys(top,viewport);
  }else{shell.prepend(state.previous);shell.append(state.next)}
  viewport.addEventListener("scroll",schedule,{passive:true});
  viewport.addEventListener("focusin",event=>{
    if(event.target===viewport)return;
    const bounds=viewport.getBoundingClientRect(),target=event.target.getBoundingClientRect();
    if(target.left<bounds.left)viewport.scrollLeft+=target.left-bounds.left;
    else if(target.right>bounds.right)viewport.scrollLeft+=target.right-bounds.right;
    schedule();
  });
  bindKeys(viewport,viewport);
  if(typeof ResizeObserver!=="undefined"){
    state.observer=new ResizeObserver(schedule);state.observer.observe(viewport);
    for(const child of viewport.children)state.observer.observe(child);
  }
  states.add(state);
}
/* Enhance every region under root, now and as the page adds more (one observer per page). labels overrides LABELS (another language). */
export function bindScroll(root=document,options={}){
  const labels={...LABELS,...(options.labels||{})};
  const mount=()=>{root.querySelectorAll('[data-ui-scroll="row"],[data-ui-scroll="table"]').forEach(v=>enhance(v,labels));schedule()};
  if(!watching){
    watching=true;
    new MutationObserver(mutations=>{if(mutations.some(m=>m.type==="childList"))mount();else schedule()})
      .observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:["open","hidden"]});
    window.addEventListener("resize",schedule,{passive:true});
    document.addEventListener("toggle",schedule,true);
    document.addEventListener("load",schedule,true);
  }
  mount();
  return {mount,refresh:refreshScroll};
}
if(typeof document!=="undefined")bindScroll();
