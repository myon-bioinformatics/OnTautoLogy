const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), statuses=['調査中','着手中','完了','保留','ブロッカー'];
const repo='https://github.com/myon-bioinformatics/OnTautoLogy', discussion=repo+'/discussions/19', sha='79eba5343276f328d1de0854f162c42a21849e7b', blob='c84feff6748a0708899f6bfb95091c0cea9edfb9', source=repo+'/blob/'+sha+'/', KEY='otl-third-board-v1';
const uid=()=>crypto.randomUUID(), now=()=>new Date().toISOString(), date=s=>new Date(s).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})+' JST';
let evidence, data, page=location.hash.slice(1)||'overview', formHandler, sessionNotice='';
const navs=[['overview','◫','概要'],['design','◇','設計案'],['compare','▤','評価比較'],['cases','≡','ケース・評価順序'],['case-graph','◇','事例と知識グラフ'],['discussion','☷','議論・下書き'],['decisions','↳','判断・再評価']];
function legacyProtocol(d){
  return JSON.stringify({steps:d.steps.map(x=>[x.id,x.title,x.detail]),cases:d.cases.map(x=>[x.id,x.input,x.expected,x.context,x.suite,x.stage])});
}

function protocol(d, scope){
  const steps = scope === 'corpus28' ? d.steps.filter(step => step.id === 's1') : d.steps;
  const item = d.cases.find(candidate => candidate.id === scope);
  return JSON.stringify({scope, input:caseInput(scope,d), stage:item?.stage, suite:item?.suite,
    steps:steps.map(step=>[step.id,step.title,step.detail]),
    criteria:d.criteria.map(c=>[c.id,c.title,c.unit,c.direction,c.rule,Boolean(c.sample)])});
}

function addReviewRecords(d){
  if (d.reviewRevision === 1) return d;
  const currentBaselineStep=d.steps.find(step=>step.id==='s1');
  d.criteria = structuredClone(defaultCriteria);
  for (const run of d.runs) {
    if (!['baseline-0','baseline-1'].includes(run.id)||run.input!==blob||!currentBaselineStep) continue;
    const originalStep=JSON.parse(run.signature).steps.find(([id])=>id==='s1');
    const {id,title,detail}=currentBaselineStep;
    if (JSON.stringify(originalStep)===JSON.stringify([id,title,detail])) run.signature=protocol(d,run.scope);
  }

  d.cases.push(...caseFixtures.map((item, index) => ({
    id:item.id, title:item.id.slice(0,4)+' '+['夜間のDB','共有だけ','交代','一報'][index],
    suite:'PR #23 固定事例', stage:'s3', status:'調査中',
    input:item.statement,
    context:[item.context, '証跡：'+item.evidence, '役割：'+item.role,
      Object.entries(item.six).map(pair=>pair.join('＝')).join(' / '),
      '要素：'+item.elements.join('、')].join('\n'),
    expected:caseObservations[index][3],
    next:'同一入力と sure=1 で、候補・判断・未登録要素を照合する。'
  })).filter(item => !d.cases.some(existing => existing.id === item.id)));

  const plans = [
    {id:'case-judgment',title:'専用 Case・Judgment',type:'接続案',status:'調査中',
      detail:'事例と判断に専用クラスを設け、事例の版から観測・判断にたどる。',
      risk:'証跡・語彙検査・履歴を既存クラスと共通化する接続規約が必要。',
      next:'K001〜K004を保存し、候補と人の判断を別々に取得できるか確認する。',basis:repo+'/pull/25'},
    {id:'observation-evidence',title:'Observation・Evidence の再利用',type:'接続案',status:'調査中',
      detail:'Observation・Evidence・Snapshotを用い、事例、候補を出した実行、人の判断を対象版に紐付ける。',
      risk:'record_kindと関係で取得するため、事例用の参照・語彙検査が必要。',
      next:'担当者名の変更、未判断、矛盾する判断、訂正後の旧版参照をK001〜K004で確認する。',basis:repo+'/pull/25'}
  ];
  d.plans.push(...plans.filter(plan => !d.plans.some(existing => existing.id === plan.id)));

  const decision = d.decisions.find(item => item.id === 'd2');
  if (decision?.reason === '現行の例は28概念・6 seeds。追加5語の評価結果は存在しない。') {
    Object.assign(decision, {
      title:'11語の共通入力と正解ID',
      reason:'PR #20で追加5語の例データを整備。11語を固定した全方式の比較は未記録。',
      next:'表記、文脈、正解ID、反例を揃え、既存方式から再計測する。'
    });
  }
  if (!d.decisions.some(item => item.id === 'd-case-graph')) {
    d.decisions.push({id:'d-case-graph',title:'事例と知識グラフの接続方式',status:'調査中',
      reason:'PR #23のcasesで候補と人の判断を分離できた。PR #25は専用クラス案と既存クラス再利用案を検討中。',
      affected:'K001〜K004、判断権限、事例の訂正履歴、概念ID参照',
      next:'両案で同じ順に実行し、状態・根拠・元の記録を保持できるか確認する。'});
  }
  d.reviewRevision = 1;
  return d;
}
function fresh(upgrade=true){const d={schema:'otl-third-board/1',revision:1,plans:[
{id:'baseline',title:'既存方式 / guess・wobble',type:'基準方式',status:'完了',detail:'28概念の評価結果を設定付きで固定。Name は候補提示に用い、概念の定義から分離する。',risk:'未知拒否と忘却対応は設定により変わる。誤統合は独立指標として追加測定が必要。',next:'鮭の表記ごとの正解IDと誤候補の数え方を固定する。',basis:discussion+'#discussioncomment-19675534'},
{id:'middle',title:'中間層 / 概念ID・文脈・根拠',type:'設計案',status:'調査中',detail:'入力→意味解釈→推論→判断評価を関数の分担で試作。概念IDに表記を紐付け、actor・roleと観測・判断を分ける。',risk:'同音語や上位概念を同じIDへ寄せる危険。候補の命中と確定判断を混同しない。',next:'鮭で基準方式と同一の入力を実行し、改善と誤統合を記録する。',basis:discussion+'#discussioncomment-19675268'},
{id:'bert',title:'多言語モデル / 候補JSON',type:'代替案',status:'保留',detail:'外部スクリプトの多言語モデルは basis=hypothesis の候補JSONを返す。OTL本体への依存追加は別判断。',risk:'モデル・閾値・版の違いが結果に影響する。自動的な同一概念への確定は行わない。',next:'中間層の入力・出力契約と誤統合の測定定義を先に決める。',basis:discussion+'#discussioncomment-19675534'}],
steps:[{id:'s1',title:'既存方式の基準値を固定',detail:'28概念 / lies・sure / 入力SHA / 実行結果を保存'}, {id:'s2',title:'鮭の多言語・表記揺れ',detail:'同音語・別名・上位概念を含めてIDと誤統合を比較'}, {id:'s3',title:'エスカレーションの文脈',detail:'送り手・送り先・役割・確信度・判断根拠を比較'}, {id:'s4',title:'11語へ拡張して再評価',detail:'同じケースと順序で各案を評価。未確定事項を判断'}],
cases:[
{id:'c-salmon',title:'鮭 / 多言語・表記揺れ',suite:'第三弾11語',stage:'s2',status:'調査中',input:'鮭 / さけ / シャケ / Salmon / Chum salmon / シロザケ',expected:'正解IDを先に固定。同一概念の候補を返し、酒・サケ属・サケ科を自動統合しない。',context:'既存namesを再利用。Salmonの総称と種の差、同音語の扱いは要判断。',next:'正解IDと negative case を合意する'},
{id:'c-esc',title:'エスカレーション / 役割・文脈',suite:'第三弾11語',stage:'s3',status:'調査中',input:'インシデントを担当者から責任者へエスカレーションする。',expected:'actorとrole、送り手・送り先、期限、方法、根拠を分離。不足情報は質問する。',context:'6W1H、抽象度、確信度を記録する。正解ラベルと採点基準は未確定。',next:'同じ語で文脈の異なる反例を追加する'},
...['iPhone','ルイージ','ピカチュウ','エナジードリンク','ギター','スパイダーマン','AIエージェント','インシデント','不安'].map((x,i)=>({id:'c-'+i,title:x,suite:'第三弾11語',stage:'s4',status:'調査中',input:x,expected:i<5?'既存Concept・Name・属性を用い、同じ概念と近似概念を区別する。':'定義、類似概念2つ以上、属性:値、正解IDを準備する。',context:i<5?'既存28概念コーパスの一部。11語の評価結果は未測定。':'PR #20で追加された概念。固定した正解ラベルと共通の採点が必要。',next:'表記・文脈・反例と正解を追加する'}))],
runs:[],comments:[
{id:'19675268',title:'OTL bot / 第三弾の範囲',summary:'概念IDと表記、観測と判断、候補JSON、関数から始める中間層、同一指標の比較を提案。',covered:'概念ID・観測分離・hypothesis・中間層・基準値',url:discussion+'#discussioncomment-19675268'},
{id:'19675534',title:'Claude / 実装に合わせた補足',summary:'任意ID、namesの属性、wobble候補を自動確定しない方針。誤統合を計測し、設定付きで基準値を残す。',covered:'互換性・誤統合・lies/sure・鮭の表記・完了条件',url:discussion+'#discussioncomment-19675534'},
{id:'19675729',title:'OTL第三弾の設計・評価順序',summary:'Concept・Name・Observationを整理。懸念と代替案を残し、鮭→エスカレーションの順で評価する。',covered:'評価順序・設計の懸念・代替案・Discussions/Issue/PR/Wikiの分担',url:discussion+'#discussioncomment-19675729'}],
proposal:{novel:'比較単位を入力・正解ラベル・評価順序・設定の版で固定し、既存方式の保存結果に中間層結果を紐付ける。候補の誤一致と確定した誤統合を別々に数える案を確認する。',overlap:'概念ID、観測と判断の分離、誤統合の計測、鮭→エスカレーションの順序は既存コメントで提案済み。',check:'一部重複あり',draft:'追加で確認したい点（未投稿の下書き）\n\n1. 同一入力・同一正解ラベル・同一評価順序・同一設定の版を、比較結果ごとに記録する。\n2. 候補段階で別IDに当たった件数と、判断後に確定した誤統合を区別して残す。どちらを主指標にするかを合意する。\n3. 入力・正解・設定・順序を変更した場合は、基準方式も再評価してから差分を判断する。\n\n既存の設計方針と評価順序の再提案は省き、上記の測定・比較条件のみを追加確認する。',posted:'',reason:'既存コメントは設計と指標の方向を示している。比較結果の版管理と候補/確定の数え分けは追加確認が必要。'},
decisions:[{id:'d1',title:'誤統合の分母・候補/確定の区別',status:'調査中',reason:'#19は「別の概念に当たった件数」を提案。確定誤統合との区別は未確定。',next:'候補誤一致と確定誤統合を分けた採点表を決める',affected:'鮭・11語・中間層・多言語モデル'}, {id:'d2',title:'11語コーパスと正解IDの追加',status:'保留',reason:'現行の例は28概念・6 seeds。追加5語の評価結果は存在しない。',next:'追加5語の定義・類似語・属性と正解を準備する',affected:'11語への拡張・既存方式の再実行'},{id:'d3',title:'モデル導入と閾値の採用条件',status:'保留',reason:'BERT型との比較は次段階の案。性能の改善・誤統合・質問数の実測が必要。',next:'同じ入力で結果が揃ってから採否を判断する',affected:'外部候補JSON・中間層案'}],history:[],savedAt:now()};
const sig=legacyProtocol(d);for(const setting of ['0','1']){const v=evidence['guess'+setting].summary;d.runs.push({id:'baseline-'+setting,plan:'baseline',scope:'corpus28',signature:sig,settings:'lies='+setting+';sure=1',input:blob,model:sha,accuracy:100*v.honest.rate,unknown:100*v.unseen.rate,forget:100*v.forget.rate,questions:v.honest.mean_questions,max:v.honest.max_questions,merges:null,denominator:null,evidence:'baseline-evidence.json',note:'既存コードを固定SHAで再実行。未知拒否・忘却のrateはguess_report。誤統合は未測定。',locked:true,createdAt:now()});}
d.history.push({time:now(),text:'固定SHAの既存方式を再実行し、lies=0/1・sure=1 の基準値と生データを保存。'});return upgrade?addReviewRecords(d):d;}
function save(message,history=true){data.savedAt=now();if(history&&message)data.history.unshift({time:now(),text:message});try{localStorage.setItem(KEY,JSON.stringify(data));$('#saved').textContent='保存済み '+date(data.savedAt);}catch{sessionNotice='ブラウザへの保存に失敗しました。JSON保存で書き出してください。';}if(message)toast(message);}
function toast(t){$('#toast').textContent=t;$('#toast').classList.add('show');setTimeout(()=>$('#toast').classList.remove('show'),2600);}
function link(url,label){let safe;try{const u=new URL(url,location.href);safe=['https:','http:'].includes(u.protocol)?u.href:'#';}catch{safe='#';}return `<a href="${esc(safe)}" target="_blank" rel="noopener">${esc(label)} ↗</a>`;}
const status=(value)=>`<span class="status ${esc(value)}">${esc(value)}</span>`;
function statusSelect(kind,id,value){return `<select aria-label="${esc(id)}の状態" class="status-select" data-status="${kind}" data-id="${esc(id)}">${statuses.map(s=>`<option ${s===value?'selected':''}>${s}</option>`).join('')}</select>`;}
function heading(eyebrow,title,sub,extra=''){return `<div class="heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${sub}</p></div>${extra}</div>`;}
function panel(title,body,extra='',note=''){return `<section class="panel"><div class="panel-head"><h2>${title}</h2>${extra}</div>${body}${note?`<p class="note">${note}</p>`:''}</section>`;}
function num(v,suffix=''){return v===null||v===undefined?'未測定':Number(v).toFixed(Number.isInteger(Number(v))?0:2)+suffix;}
function reference(){return data.runs.find(r=>r.id==='baseline-0');}
function current(run){return run.signature===protocol(data, run.scope)&&run.input===caseInput(run.scope);}
function caseInput(id, board=data){
  if(id==='corpus28') return blob;
  const c=board.cases.find(x=>x.id===id);
  return c?JSON.stringify([c.input,c.expected,c.context]):'missing';
}
function metric(label,val,unit,sub){return `<div class="metric"><div class="label">${label}</div><div class="value">${val}<small>${unit}</small></div><div class="sub">${sub}</div></div>`;}

function overview(){
  const r=reference();
  const count=data.runs.filter(run=>run.plan!=='baseline'&&current(run)).length;
  const milestones=data.steps.map((step,i)=>`<div class="step"><span class="stepnum">${i+1}</span>
    <div><b>${esc(step.title)}</b><p>${esc(step.detail)}</p></div></div>`).join('');
  const next=data.decisions.filter(item=>item.status!=='完了').slice(0,4).map(item=>`
    <article class="proposal"><h3>${esc(item.title)}</h3><p>${esc(item.next)}</p></article>`).join('');
  return heading('','設計・評価ワークボード','共通の入力・評価順序・判定基準で既存方式と比較案を検証する。')+
    `<div class="metrics">
      ${metric('未知概念の拒否',num(r.unknown),'%','27 / 28 · lies=0, sure=1')}
      ${metric('忘却への対応',num(r.forget),'%','210 / 287 · lies=0, sure=1')}
      ${metric('平均質問数',num(r.questions),'問','正直な回答 · 最大8問')}
      ${metric('比較案の有効な記録',count,'件','現行の評価条件に一致')}
    </div>
    <div class="grid">
      ${panel('固定済みの基準と試作結果',`<div class="panel-body">
        <p>28概念の基準値を固定。43概念の試作では、属性と上位階層の追加で平均質問数が6.6問から3.2問に減少しました。</p>
        <p><a href="#case-graph">K001〜K004の現行結果</a>には、候補と人の判断が食い違うK002も含まれます。</p>
      </div>`,'<a href="#compare">表とグラフを見る ↗</a>')}
      ${panel('共通の評価順序',`<div class="panel-body">${milestones}</div>`,'<a href="#cases">条件を編集 ↗</a>')}
    </div>`+plansTable()+
    `<div class="grid">
      ${panel('次に確認する項目',next||'<div class="empty">未完了の判断項目はありません。</div>','<a href="#decisions">判断・再評価 ↗</a>')}
      ${panel('Discussion #19',`<div class="panel-body"><p>既存コメント ${data.comments.length}件を記録。</p>
        <p>重複確認　${esc(data.proposal.check)}</p><p>この下書きの投稿URL　${data.proposal.posted?link(data.proposal.posted,'記録済み'):'未記録'}</p>
      </div>`,'<a href="#discussion">議論・下書き ↗</a>')}
    </div>`;
}

function plansTable(){return panel('設計案と進捗',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>設計案</th><th>種別</th><th>状態</th><th>次に確認する項目</th><th></th></tr></thead><tbody>${data.plans.map((p,i)=>`<tr><td><span class="rowcode">DESIGN ${String(i+1).padStart(2,'0')}</span><div class="rowtitle">${esc(p.title)}</div></td><td><span class="tag">${esc(p.type)}</span></td><td>${statusSelect('plans',p.id,p.status)}</td><td class="wrap">${esc(p.next)}</td><td><button class="text-link" data-edit-plan="${esc(p.id)}">詳細・編集 ↗</button></td></tr>`).join('')}</tbody></table></div>`,'','案の状態は手動の作業状況です。評価値の有無・再評価の必要性とは別に記録します。');}
function design(){return heading('DESIGN REGISTER','設計案','懸念と代替案を残し、評価結果を根拠に設計を判断する。','<button class="primary" id="add-plan">＋ 設計案を追加</button>')+plansTable()+data.plans.map(p=>panel(esc(p.title),`<div class="panel-body"><p>${esc(p.detail)}</p><p class="input-hint"><b>懸念・未確定事項</b><br>${esc(p.risk)}</p><p class="form-help">設計の根拠：${link(p.basis,'出典を確認')}</p></div>`,status(p.status))).join('');}
let selectedScope='corpus28',selectedPlan='middle',selectedSetting='lies=0;sure=1';

function scopeOptions(){
  const stages = data.steps.map(step=>step.id);
  const cases = [...data.cases].sort((a,b)=>stages.indexOf(a.stage)-stages.indexOf(b.stage));
  return [['corpus28','既存28概念 / guess_report'], ...cases.map(c=>[c.id,c.title])];
}
function scopeLabel(id){return scopeOptions().find(([key])=>key===id)?.[1] || id;}
function defaultSetting(scope){return caseFixtures.some(item=>item.id===scope)?'sure=1':'lies=0;sure=1';}
function selectScope(scope){
  selectedScope=scope;
  selectedSetting=data.runs.filter(run=>run.scope===scope&&current(run)).at(-1)?.settings||defaultSetting(scope);
}
function latest(plan,scope,settings){
  const records=data.runs.filter(r=>r.plan===plan&&r.scope===scope&&r.settings===settings);
  return records.findLast(current)||records.at(-1);
}
function comparable(b,c){return Boolean(b&&c&&b.locked&&current(b)&&current(c)&&b.signature===c.signature&&b.settings===c.settings&&b.scope===c.scope&&b.input===c.input);}
function resultValue(run,key){return run?.metrics?.[key]??run?.[key]??null;}
function sampleSize(run,key){return run?.samples?.[key]??(key==='merges'?run?.denominator:null)??null;}
function metricDelta(criterion,b,c,paired){
  const before=resultValue(b,criterion.id), after=resultValue(c,criterion.id);
  if (!paired||before===null||after===null) return {label:'比較待ち'};
  if (criterion.sample&&sampleSize(b,criterion.id)!==sampleSize(c,criterion.id)) {
    return {label:'評価対象数が異なるため保留'};
  }
  const delta=after-before;
  const direction=delta*criterion.direction;
  const unit=criterion.unit==='%'?' pt':criterion.unit;
  return {label:`${delta>0?'+':''}${num(delta,unit)} · ${direction===0?'同等':direction>0?'改善':'悪化'}`, direction};
}
function resultChart(b,c,paired){
  const rows=data.criteria.map(criterion=>{
    const vals=[resultValue(b,criterion.id),paired?resultValue(c,criterion.id):null];
    const max=criterion.unit==='%'?100:Math.max(1,...vals.filter(Number.isFinite));
    return `<div class="paired-chart-row"><b>${esc(criterion.title)}</b>${vals.map((value,i)=>`
      <div class="paired-bar"><span>${i?'比較案':'基準'}</span><div aria-hidden="true" class="track ${value===null?'empty-bar':''}"><div class="bar ${i?'candidate-bar':''}" style="width:${value===null?0:(value/max)*100}%"></div></div>
      <span>${i&&c&&!paired?'比較待ち':num(value,esc(criterion.unit))}</span></div>`).join('')}</div>`;
  });
  return panel('指標グラフ',`<div class="panel-body">${rows.join('')}</div>`,'','質問数と件数は各指標内で同じ目盛りを使います。');
}

function recordedCasePanel(){
  const rows=caseFixtures.map((item,index)=>`<tr><th scope="row">${esc(item.id.slice(0,4))} ${['夜間のDB','共有だけ','交代','一報'][index]}</th>${caseObservations[index].map((value,column)=>`<td${column===3?' class="wrap"':''}>${esc(value)}</td>`).join('')}<td><button class="text-link" data-open-case="${item.id}">比較へ</button></td></tr>`);
  return panel('K001〜K004 · 現行 cases の固定記録',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table>
    <thead><tr><th>入力</th><th>候補（hypothesis）</th><th>人の判断（observed）</th><th>状態</th><th>次の比較で保持する点</th><th></th></tr></thead>
    <tbody>${rows.join('')}</tbody></table></div>
    <p class="note">cases --sure 1 · ${link(caseSource,'固定入力・判断')} · ${link(repo+'/pull/23','PR #23 実績')} · ${link(repo+'/pull/25','PR #25 接続設計案（両案とも未測定）')}</p>`);
}

function recordedEvaluation(){
  const rows=recordedHierarchy.map(([label,plain,tolerant,forget])=>`<tr><th scope="row">${label}</th><td>${plain}問</td><td>${tolerant}問</td><td>${forget}%</td><td>未記録</td><td>未記録</td></tr>`);
  return panel('43概念 · 属性と上位階層の試作結果',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table>
    <thead><tr><th>方式</th><th>平均質問数 lies=0</th><th>平均質問数 lies=1</th><th>1要素の忘却対応 lies=1</th><th>未知拒否</th><th>確定した誤統合</th></tr></thead>
    <tbody>${rows.join('')}</tbody></table></div>
    <div class="panel-body"><b>平均質問数 · lies=0、sure=1</b>
      ${recordedHierarchy.map(([label,value])=>`<div class="paired-bar history-bar"><span>${label}</span><div class="track" aria-hidden="true"><div class="bar" style="width:${value/6.6*100}%"></div></div><span>${value}問</span></div>`).join('')}
      <p class="form-help">属性と上位階層の追加で平均6.6問から3.2問に減少。忘却時の正解率は93%から100%。${link(repo+'/pull/23','測定条件と出典')}</p>
    </div>`);
}

function baselineEvidencePanel(){
  const report=[
    [0,0,3.4,83,57],[0,1,4.4,73,96],[0,2,5.6,62,100],
    [1,0,7.3,100,82],[1,1,8.3,100,100],[1,2,9.6,100,100]
  ];
  return panel('28概念 · 確信度と追加確認の既存評価',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table>
    <thead><tr><th>許容する食い違い</th><th>確信度しきい値</th><th>正直な回答の平均質問数</th><th>忘却への対応</th><th>未知拒否</th></tr></thead>
    <tbody>${report.map(row=>`<tr>${row.map((value,index)=>`<td>${value}${['回','','問','%','%'][index]}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
    <p class="note">正直な回答では全設定28/28。${link(repo+'/pull/18','PR #18 の報告値')} · ${link('baseline-evidence.json','sure=1 固定結果の内訳と生データ')}</p>`);
}

function compare(){
  const b=latest('baseline',selectedScope,selectedSetting);
  const c=latest(selectedPlan,selectedScope,selectedSetting);
  const paired=comparable(b,c);
  const ready=b&&current(b);
  const item=data.cases.find(x=>x.id===selectedScope);
  let message='既存方式の結果を先に記録してください';
  if (b) {
    if (!ready) message='評価条件が変わりました。既存方式から再評価してください';
    else if (!b.locked) message='既存方式の結果を固定してから比較してください';
    else if (!c) message='比較案の結果は未測定です';
    else message=paired?'同じ条件で比較できます':'比較案の再評価が必要です';
  }
  const settings=[...new Set([defaultSetting(selectedScope),...(selectedScope==='corpus28'?['lies=1;sure=1']:[]),
    ...data.runs.filter(r=>r.scope===selectedScope).map(r=>r.settings)])];
  const options=(values,selected)=>values.map(([id,title])=>`<option value="${esc(id)}" ${id===selected?'selected':''}>${esc(title)}</option>`).join('');
  const pairedRows=data.criteria.map(criterion=>{
    const {label,direction}=metricDelta(criterion,b,c,paired);
    const value=run=>`${num(resultValue(run,criterion.id),esc(criterion.unit))}${criterion.sample?`<small>評価対象 ${num(sampleSize(run,criterion.id),'件')}</small>`:''}`;
    return `<tr><th scope="row">${esc(criterion.title)}</th><td>${value(b)}</td><td>${value(c)}</td><td class="${direction<0?'danger':'muted'}">${label}</td></tr>`;
  }).join('');
  const history=data.runs.filter(r=>r.scope===selectedScope).slice().reverse().map(r=>`
    <tr><td>${esc(data.plans.find(p=>p.id===r.plan)?.title||r.plan)}</td><td>${esc(r.settings)}<small>${esc(r.model)}</small></td>
    <td><span class="status ${current(r)?'完了':'保留'}">${current(r)?r.locked?'固定済み':'記録済み':'過去の条件'}</span><small>${date(r.createdAt)}</small></td>
    <td class="wrap">${link(r.evidence,'結果の証跡')}<small>${esc(r.note)}</small></td>
    <td><button class="text-link" data-run-details="${esc(r.id)}">詳細</button>
      ${!r.locked&&current(r)?`<button class="text-link" data-edit-run="${esc(r.id)}">編集</button>`:''}</td></tr>`).join('');
  return heading('','評価比較','入力・評価順序・判定基準・設定が一致した記録を比較する。','<button class="primary" id="add-run">＋ 結果を記録</button>')+
    `<div class="toolbar">
      <label>比較入力 <select id="scope">${options(scopeOptions(),selectedScope)}</select></label>
      <label>比較案 <select id="comparison-plan">${options(data.plans.filter(p=>p.id!=='baseline').map(p=>[p.id,p.title]),selectedPlan)}</select></label>
      <label>設定 <select id="setting">${options(settings.map(s=>[s,s]),selectedSetting)}</select></label>
    </div><div class="callout"><div><b>${message}</b><p>${esc(scopeLabel(selectedScope))} / ${esc(selectedSetting)} · 評価条件の版 ${data.revision}</p></div>
    ${ready&&!b.locked?`<button class="primary" id="lock-baseline" data-id="${esc(b.id)}">基準結果を固定</button>`:''}</div>`+
    panel('同じ入力での結果',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>評価指標</th><th>既存方式</th>
      <th>${esc(data.plans.find(p=>p.id===selectedPlan)?.title)}</th><th>差分 / 改善方向</th></tr></thead>
      <tbody>${pairedRows}</tbody></table></div>`)+
    `<div class="grid">${resultChart(ready?b:null,c,paired)}
      ${panel('比較する入力と根拠',`<div class="panel-body">
        <p class="record-text">${esc(item?.input||'concepts-20261115.json / 28概念')}</p>
        ${item?`<p class="record-text form-help">${esc(item.context)}</p><p>期待する結果　${esc(item.expected)}</p>`:
          `<p>入力 blob　<code>${blob.slice(0,12)}</code></p><p>${link(source+'tools/tautology.py','実装')} · ${link('baseline-evidence.json','生データ')}</p>`}
        <p><a href="#cases">評価順序・判定基準を確認</a></p>
      </div>`)}</div>`+
    panel('結果の履歴',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>方式</th><th>設定 / 実装・モデル</th><th>状態</th><th>証跡・メモ</th><th></th></tr></thead>
      <tbody>${history||'<tr><td colspan="5" class="empty">この入力の結果はまだありません。</td></tr>'}</tbody></table></div>`)+
    recordedEvaluation()+baselineEvidencePanel()+
    panel('既存評価の補助指標',`<div class="panel-body"><p>holdout（28概念、6 seeds）初見の誤り 0/162、マスクで見落とし 17/67。</p>
    <p>wobble 往復（28概念）TP 78、FP 8、FN 0、TN 2,098。FPは別概念への候補ヒットです。${link(repo+'/pull/20','PR #20 の報告と定義')}</p></div>`);
}

function cases(){return heading('SHARED PROTOCOL','ケース・評価順序','全案で共有する入力・正解・文脈を固定する。編集すると既存結果に再評価が必要になります。','<button class="primary" id="add-case">＋ ケースを追加</button>')+panel('共通の評価順序',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>順序</th><th>評価段階</th><th>確認内容</th><th>変更</th></tr></thead><tbody>${data.steps.map((s,i)=>`<tr><td>${String(i+1).padStart(2,'0')}</td><td>${esc(s.title)}</td><td class="wrap">${esc(s.detail)}</td><td><button data-move="${s.id}" data-dir="-1" ${i===0?'disabled':''} aria-label="${esc(s.title)}を上へ">↑</button> <button data-move="${s.id}" data-dir="1" ${i===data.steps.length-1?'disabled':''} aria-label="${esc(s.title)}を下へ">↓</button> <button class="text-link" data-edit-step="${s.id}">編集</button></td></tr>`).join('')}</tbody></table></div>`,`<button id="add-step">＋ 段階</button>`)+criteriaPanel()+`<div class="toolbar"><input id="case-search" aria-label="ケースを検索" placeholder="ケース名・入力で検索"><span class="muted">${data.cases.length}ケース / 評価条件の版 ${data.revision}</span></div>`+`<div id="case-table">${casesTable('')}</div>`+`<p class="input-hint">11語を通した全方式の比較は未記録です。個別ケースの基準値は、各ケースの入力で記録してください。</p>`;}
function casesTable(query){let cases=data.cases.filter(c=>(c.title+c.input+c.context).toLowerCase().includes(query.toLowerCase()));cases.sort((a,b)=>data.steps.findIndex(s=>s.id===a.stage)-data.steps.findIndex(s=>s.id===b.stage));return panel('共有する評価ケース',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>ケース / 段階</th><th>入力・文脈</th><th>期待する結果 / 次の確認</th><th>状態</th><th></th></tr></thead><tbody>${cases.map(c=>`<tr><td><div class="rowtitle">${esc(c.title)}</div><small>${esc(data.steps.find(s=>s.id===c.stage)?.title||'未分類')}</small></td><td class="wrap"><div class="case-input">${esc(c.input)}</div><small>${esc(c.context)}</small></td><td class="wrap">${esc(c.expected)}<small>次：${esc(c.next)}</small></td><td>${statusSelect('cases',c.id,c.status)}</td><td><button class="text-link" data-edit-case="${esc(c.id)}">編集</button><button class="text-link" data-open-case="${esc(c.id)}">比較へ</button></td></tr>`).join('')||'<tr><td colspan="5" class="empty">一致するケースがありません。</td></tr>'}</tbody></table></div>`);}
function discussionView(){const p=data.proposal;return heading('DISCUSSION NOTES','議論・下書き','既存コメントとの重複と、追加で確認する論点を整理する。','')+`<div class="grid">${panel('既存コメント / #19',data.comments.map(c=>`<article class="proposal"><h3>${esc(c.title)}</h3><p>${esc(c.summary)}</p><small class="muted">既存論点：${esc(c.covered)}</small><p>${link(c.url,'コメントを確認')}</p><button class="text-link" data-edit-comment="${esc(c.id)}">記録を編集</button></article>`).join(''),'<button id="add-comment">＋ 記録</button>','2026-11-18 JSTに本文と3件のコメントを照合。追加コメントは一覧に記録してください。')}${panel('重複確認と追加論点',`<div class="panel-body"><p class="form-help"><b>既存コメントと重なる内容</b></p><p style="font-size:12px">${esc(p.overlap)}</p><p class="form-help"><b>追加で確認する内容 / 未合意</b></p><p style="font-size:12px">${esc(p.novel)}</p><p class="form-help"><b>追加する根拠</b></p><p style="font-size:12px">${esc(p.reason)}</p><p><a href="#decisions">設計変更の根拠・再評価の一覧</a></p><label class="form-help">重複の確認状態 <select id="duplicate-check" class="status-select">${['未確認','一部重複あり','要修正','重複なし（手動確認）'].map(x=>`<option ${p.check===x?'selected':''}>${x}</option>`).join('')}</select></label><p><button id="edit-proposal">論点と根拠を編集</button></p></div>`)}</div>${panel('投稿前の下書き',`<div class="panel-body"><textarea aria-label="投稿前の下書き" id="draft" class="editor" rows="12">${esc(p.draft)}</textarea><div class="toolbar" style="margin-top:12px"><button id="save-draft" class="primary">下書きを保存</button><button id="copy-draft">下書きをコピー</button><span class="form-help">下書きはこのボード内の記録です。</span></div><div class="field"><label for="posted">投稿済みコメントURL（別途投稿した場合に記録）</label><input id="posted" type="url" value="${esc(p.posted)}" placeholder="https://github.com/.../discussions/19#discussioncomment-..."><small>${p.posted?'この下書きに紐づく投稿を確認できます。':'この下書きの投稿URLは未記録です。既存の提案は上の一覧にあります。'}</small></div><button id="save-posted">URLを保存</button>${p.posted?` <span>${link(p.posted,'記録したコメント')}</span>`:''}</div>`)} `;}
function decisionsView(){const stale=pendingReevaluations();return heading('DECISIONS & RE-EVALUATION','判断・再評価','設計を変更した理由、未確定事項、再評価の対象を残す。','<button id="add-decision" class="primary">＋ 判断項目を追加</button>')+`<div class="callout"><div><b>${stale.length}件の結果に再評価が必要です</b><p>入力・正解・文脈・評価順序・判定基準を変更した結果を追跡します。固定した基準値も履歴として残ります。</p></div><span class="pill">評価条件の版 ${data.revision}</span></div>`+panel('未確定事項と設計変更の根拠',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>判断項目</th><th>根拠</th><th>影響 / 次に確認する項目</th><th>状態</th><th></th></tr></thead><tbody>${data.decisions.map(d=>`<tr><td class="wrap"><b>${esc(d.title)}</b></td><td class="wrap">${esc(d.reason)}</td><td class="wrap">${esc(d.affected)}<small>次：${esc(d.next)}</small></td><td>${statusSelect('decisions',d.id,d.status)}</td><td><button class="text-link" data-edit-decision="${d.id}">編集</button></td></tr>`).join('')}</tbody></table></div>`)+panel('再評価が必要な結果',stale.length?`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>方式</th><th>入力</th><th>設定</th><th>確認する項目</th></tr></thead><tbody>${stale.map(r=>`<tr><td>${esc(data.plans.find(p=>p.id===r.plan)?.title)}</td><td>${esc(scopeLabel(r.scope))}</td><td>${esc(r.settings)}</td><td>現行の評価条件を使って実行し、結果を記録。</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">保存された入力・順序との相違はありません。<br>次の評価は設計案ごとの確認項目を参照してください。</div>')+panel('変更履歴',`<div class="panel-body">${data.history.slice(0,60).map(h=>`<div class="change"><small>${date(h.time)}</small>${esc(h.text)}</div>`).join('')}</div>`);}
function render(){if(!navs.some(x=>x[0]===page))page='overview';$('#nav').innerHTML=navs.map(([id,icon,label])=>`<a class="${id===page?'active':''}" href="#${id}"><span>${icon}</span>${label}</a>`).join('');$('#crumb').textContent=navs.find(x=>x[0]===page)[2];$('#view').innerHTML=(sessionNotice?`<div class="callout">${esc(sessionNotice)}</div>`:'')+({overview,design,compare,cases,'case-graph':caseGraphReview,discussion:discussionView,decisions:decisionsView}[page])();$('#saved').textContent='保存済み '+date(data.savedAt);bind();}
function field(name,label,value='',type='text',options){const val=esc(value);return `<div class="field"><label for="f-${name}">${esc(label)}</label>${type==='textarea'?`<textarea id="f-${name}" name="${name}">${val}</textarea>`:type==='select'?`<select id="f-${name}" name="${name}">${options.map(x=>{let [v,l]=Array.isArray(x)?x:[x,x];return `<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(l)}</option>`;}).join('')}</select>`:`<input id="f-${name}" name="${name}" type="${type}" value="${val}" ${type==='number'?'step="any" min="0"':''}>`}</div>`;}
function modal(title,fields,handler){$('#dialog').classList.remove('read-only');$('#dialog-title').textContent=title;$('#fields').innerHTML=fields;$('#form-error').textContent='';formHandler=handler;$('#dialog').showModal();}
function required(v,k){if(!v[k]?.trim())throw Error('必須項目を入力してください。');return v[k].trim();}
function editPlan(id){const p=data.plans.find(p=>p.id===id)||{id:uid(),title:'',type:'設計案',status:'調査中',detail:'',risk:'',next:'',basis:discussion};modal(id?'設計案を編集':'設計案を追加',field('title','案の名前 *',p.title)+field('type','種別',p.type)+field('status','状態',p.status,'select',statuses)+field('detail','設計内容',p.detail,'textarea')+field('risk','懸念・未確定事項',p.risk,'textarea')+field('next','次に確認する項目',p.next)+field('basis','設計の根拠URL',p.basis,'url'),v=>{required(v,'title');Object.assign(p,v);if(!id)data.plans.push(p);save('設計案を保存：'+p.title);});}
function bump(reason){data.revision++;save(reason+'。評価条件の版を更新しました。');}
function editCase(id){const c=data.cases.find(c=>c.id===id)||{id:uid(),title:'',suite:'第三弾11語',stage:data.steps[1]?.id||data.steps[0].id,status:'調査中',input:'',expected:'',context:'',next:''};const before=JSON.stringify([c.input,c.expected,c.context,c.suite,c.stage]);modal(id?'共有ケースを編集':'共有ケースを追加',field('title','ケース名 *',c.title)+field('suite','評価セット',c.suite)+field('stage','評価段階',c.stage,'select',data.steps.map(s=>[s.id,s.title]))+field('status','状態',c.status,'select',statuses)+field('input','入力 *',c.input,'textarea')+field('expected','期待する結果・正解 *',c.expected,'textarea')+field('context','文脈',c.context,'textarea')+field('next','次に確認する項目',c.next),v=>{required(v,'title');required(v,'input');required(v,'expected');Object.assign(c,v);if(!id)data.cases.push(c);if(!id||before!==JSON.stringify([c.input,c.expected,c.context,c.suite,c.stage]))bump('評価ケースを更新：'+c.title);else save('ケースを更新：'+c.title);});}
function editStep(id){const s=data.steps.find(x=>x.id===id)||{id:uid(),title:'',detail:''};modal(id?'評価段階を編集':'評価段階を追加',field('title','段階の名前 *',s.title)+field('detail','共通の確認内容',s.detail,'textarea'),v=>{required(v,'title');Object.assign(s,v);if(!id)data.steps.push(s);bump('共通の評価段階を更新：'+s.title);});}
function editDecision(id){const d=data.decisions.find(x=>x.id===id)||{id:uid(),title:'',status:'調査中',reason:'',next:'',affected:''};modal('判断・再評価の項目',field('title','判断項目 *',d.title)+field('status','状態',d.status,'select',statuses)+field('reason','設計変更・判断の根拠 *',d.reason,'textarea')+field('affected','影響する案・ケース・再評価項目',d.affected)+field('next','次に確認する項目',d.next),v=>{required(v,'title');required(v,'reason');Object.assign(d,v);if(!id)data.decisions.push(d);save('判断項目を保存：'+d.title);});}
function discussionCommentUrl(url){return url.startsWith(discussion+'#discussioncomment-')&&/^\d+$/.test(url.slice((discussion+'#discussioncomment-').length));}
function editComment(id){const c=data.comments.find(x=>x.id===id)||{id:uid(),title:'',summary:'',covered:'',url:''};modal('既存コメントの記録',field('title','見出し *',c.title)+field('summary','提案の要点',c.summary,'textarea')+field('covered','既存の論点',c.covered)+field('url','コメントURL *',c.url,'url'),v=>{required(v,'title');required(v,'url');if(!discussionCommentUrl(v.url))throw Error('Discussion #19 のコメントURLを指定してください。');Object.assign(c,v);if(!id)data.comments.push(c);data.proposal.check='未確認';save('既存コメントの記録を更新');});}

function criteriaPanel(){
  const rows=data.criteria.map(c=>`<tr><th scope="row">${esc(c.title)}</th>
    <td>${esc(c.unit)} / ${c.direction===1?'高いほど良い':'少ないほど良い'}</td>
    <td class="wrap record-text">${esc(c.rule)}</td>
    <td><button class="text-link" data-edit-criterion="${esc(c.id)}">編集</button></td></tr>`).join('');
  return panel('共通の判定基準',`<div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table>
    <thead><tr><th>指標</th><th>単位 / 改善方向</th><th>採点方法・合格条件</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table></div>`,'<button id="add-criterion">＋ 基準を追加</button>',
    '判定基準の変更前に記録した結果は、元の条件とあわせて履歴に残ります。');
}

function editCriterion(id){
  const existing=data.criteria.find(item=>item.id===id);
  const criterion=existing||{id:uid(),title:'',unit:'%',direction:1,rule:'',sample:false};
  modal(id?'判定基準を編集':'判定基準を追加',
    field('title','指標名 *',criterion.title)+
    (existing?`<p class="form-help">単位　${criterion.unit}${criterion.sample?' / 評価対象数あり':''}</p>`:
      field('unit','単位・評価対象数',criterion.unit,'select',[['%','%'],['問','問'],['件','件'],['sample','件 / 評価対象数も記録'],['点','点']]))+
    field('direction','改善方向',criterion.direction,'select',[[1,'高いほど良い'],[-1,'少ないほど良い']])+
    field('rule','採点方法・合格条件 *',criterion.rule,'textarea'), values=>{
      const updated={title:required(values,'title'),direction:Number(values.direction),rule:required(values,'rule')};
      if (!existing) {
        updated.unit=values.unit==='sample'?'件':values.unit;
        updated.sample=values.unit==='sample';
      }
      if (existing&&Object.entries(updated).every(([key,value])=>existing[key]===value)) return;
      Object.assign(criterion,updated);
      if (!existing) data.criteria.push(criterion);
      bump('判定基準を更新：'+criterion.title);
    });
}

function metricInput(raw,criterion){
  if (!raw?.trim()) return null;
  const value=Number(raw);
  if (!Number.isFinite(value)||value<0||(criterion.unit==='%'&&value>100)||
      ((criterion.id==='max'||criterion.unit==='件')&&!Number.isInteger(value))) {
    throw Error(criterion.title+'の値を確認してください。');
  }
  return value;
}

function editRun(id){
  const existing=data.runs.find(run=>run.id===id);
  if (existing&&(existing.locked||!current(existing))) return;
  const baseline=latest('baseline',selectedScope,selectedSetting);
  const r=existing||{id:uid(),plan:baseline?.locked&&current(baseline)?selectedPlan:'baseline',
    scope:selectedScope,settings:selectedSetting,model:'',evidence:'',note:''};
  const mode=existing?`<p class="form-help">${esc(scopeLabel(r.scope))} / ${esc(r.settings)}</p>`:
    field('plan','方式',r.plan,'select',data.plans.map(p=>[p.id,p.title]))+
    field('scope','同じ入力',r.scope,'select',scopeOptions())+
    field('settings','評価設定 *',r.settings);
  const inputs=data.criteria.map(c=>field('metric-'+c.id,c.title+' ('+c.unit+')',resultValue(r,c.id),'number')+
    (c.sample?field('sample-'+c.id,c.title+'の評価対象数 (件)',sampleSize(r,c.id),'number'):'')
  ).join('');
  modal('評価結果を記録','<p class="form-help">実行済みの結果を転記します。空欄は未測定として保存します。</p>'+
    mode+field('model','実装SHA・モデル名と版 *',r.model)+
    `<div class="form-grid">${inputs}</div>`+
    field('evidence','結果・ログの証跡URL *',r.evidence,'url')+
    field('note','測定条件・所見・次の確認',r.note,'textarea'),v=>{
      const plan=existing?r.plan:v.plan, scope=existing?r.scope:v.scope, settings=existing?r.settings:required(v,'settings');
      const model=required(v,'model'), evidenceUrl=required(v,'evidence');
      const base=latest('baseline',scope,settings);
      if (plan!=='baseline'&&(!base?.locked||!current(base))) {
        throw Error('同じ入力・順序・判定基準・設定で既存方式を記録し、固定してください。');
      }
      const metrics={}, samples={};
      for (const criterion of data.criteria) {
        const key=criterion.id;
        const value=metricInput(v['metric-'+key],criterion);
        metrics[key]=value;
        if (!criterion.sample) continue;
        const sample=metricInput(v['sample-'+key],{title:criterion.title+'の評価対象数',unit:'件'});
        if (value!==null&&(sample===null||sample===0||value>sample)) {
          throw Error(criterion.title+'の評価対象数には1以上かつ件数以上の整数を入力してください。');
        }
        samples[key]=sample;
      }
      if (Object.values(metrics).every(value=>value===null)) throw Error('少なくとも1つの測定値を入力してください。');
      if (metrics.max!==null&&metrics.questions!==null&&metrics.questions>metrics.max) {
        throw Error('平均質問数は最大質問数以下で入力してください。');
      }
      Object.assign(r,{plan,scope,settings,model,metrics,samples,evidence:evidenceUrl,note:v.note,
        accuracy:metrics.accuracy,unknown:metrics.unknown,forget:metrics.forget,questions:metrics.questions,
        max:metrics.max,merges:metrics.merges,denominator:samples.merges,
        input:caseInput(scope),signature:protocol(data,scope),locked:false,createdAt:now()});
      if (!existing) data.runs.push(r);
      selectedScope=scope;
      selectedSetting=settings;
      if (plan!=='baseline') selectedPlan=plan;
      save('評価結果を保存：'+scopeLabel(scope));
    });
}

function runDetails(id){
  const run=data.runs.find(item=>item.id===id);
  const snapshot=JSON.parse(run.signature);
  const criteria=(snapshot.criteria||defaultCriteria.filter(c=>c.id!=='candidate-errors').map(c=>[c.id,c.id==='merges'?'誤統合（旧記録）':c.title,c.unit,c.direction,'保存時の基準は測定メモを参照。',c.sample]));
  const input=run.scope==='corpus28'?[run.input]:JSON.parse(run.input);
  const rows=criteria.map(([key,label,unit,,rule,sample])=>`<tr><th scope="row">${esc(label)}</th>
    <td>${num(resultValue(run,key),esc(unit))}${sample?`<small>評価対象 ${num(sampleSize(run,key),'件')}</small>`:''}</td>
    <td class="wrap">${esc(rule)}</td></tr>`).join('');
  const order=snapshot.steps.map(([,title,detail])=>`<li><b>${esc(title)}</b>　${esc(detail)}</li>`).join('');
  modal('保存時の評価条件',`<p>${esc(scopeLabel(run.scope))} / ${esc(run.settings)}</p>
    <p class="record-text">${esc(input.join('\n'))}</p>
    <h3>評価順序</h3><ol>${order}</ol><h3>判定基準と結果</h3>
    <div class="table-wrap" data-ui-scroll="table" aria-label="評価・設計の表"><table><thead><tr><th>指標</th><th>結果</th><th>採点方法</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="record-text">${esc(run.note)}</p><p>${link(run.evidence,'結果の証跡')}</p>`,()=>{});
  $('#dialog').classList.add('read-only');
}

function pendingReevaluations(){
  const byCondition=new Map();
  for (const run of data.runs) {
    const key=JSON.stringify([run.plan,run.scope,run.settings]);
    const group=byCondition.get(key)||{stale:null,ready:false};
    if (current(run)&&(run.plan!=='baseline'||run.locked)) group.ready=true;
    if (!current(run)) group.stale=run;
    byCondition.set(key,group);
  }
  return [...byCondition.values()].filter(group=>group.stale&&!group.ready).map(group=>group.stale);
}

function bind(){document.querySelectorAll('[data-status]').forEach(el=>el.onchange=()=>{const x=data[el.dataset.status].find(x=>x.id===el.dataset.id);x.status=el.value;save('状態を更新：'+(x.title||x.id)+' / '+x.status);});document.querySelectorAll('[data-edit-plan]').forEach(x=>x.onclick=()=>editPlan(x.dataset.editPlan));document.querySelectorAll('[data-edit-case]').forEach(x=>x.onclick=()=>editCase(x.dataset.editCase));document.querySelectorAll('[data-edit-step]').forEach(x=>x.onclick=()=>editStep(x.dataset.editStep));document.querySelectorAll('[data-edit-decision]').forEach(x=>x.onclick=()=>editDecision(x.dataset.editDecision));document.querySelectorAll('[data-edit-comment]').forEach(x=>x.onclick=()=>editComment(x.dataset.editComment));document.querySelectorAll('[data-edit-run]').forEach(x=>x.onclick=()=>editRun(x.dataset.editRun));document.querySelectorAll('[data-open-case]').forEach(x=>x.onclick=()=>{selectScope(x.dataset.openCase);if(page==='compare')render();else location.hash='compare';});document.querySelectorAll('[data-move]').forEach(x=>x.onclick=()=>{const i=data.steps.findIndex(s=>s.id===x.dataset.move),j=i+Number(x.dataset.dir);[data.steps[i],data.steps[j]]=[data.steps[j],data.steps[i]];bump('共通の評価順序を変更');render();});const on=(id,fn)=>{const e=$('#'+id);if(e)e.onclick=fn;};on('add-plan',()=>editPlan());on('add-case',()=>editCase());on('add-step',()=>editStep());on('add-criterion',()=>editCriterion());document.querySelectorAll('[data-edit-criterion]').forEach(el=>el.onclick=()=>editCriterion(el.dataset.editCriterion));document.querySelectorAll('[data-run-details]').forEach(el=>el.onclick=()=>runDetails(el.dataset.runDetails));on('add-decision',()=>editDecision());on('add-comment',()=>editComment());on('add-run',()=>editRun());if($('#scope'))$('#scope').onchange=e=>{selectScope(e.target.value);render();};if($('#comparison-plan'))$('#comparison-plan').onchange=e=>{selectedPlan=e.target.value;render();};if($('#setting'))$('#setting').onchange=e=>{selectedSetting=e.target.value;render();};on('lock-baseline',()=>{const r=data.runs.find(x=>x.id===$('#lock-baseline').dataset.id);r.locked=true;save('基準結果を固定：'+scopeLabel(r.scope));render();});if($('#case-search'))$('#case-search').oninput=e=>{const query=e.target.value;$('#case-table').innerHTML=casesTable(query);bindCaseRows();};if($('#duplicate-check'))$('#duplicate-check').onchange=e=>{data.proposal.check=e.target.value;save('重複の確認状態を更新');};on('edit-proposal',()=>{const p=data.proposal;modal('追加論点と根拠',field('overlap','既存コメントと重なる内容',p.overlap,'textarea')+field('novel','追加で確認する内容',p.novel,'textarea')+field('reason','追加する根拠',p.reason,'textarea'),v=>{Object.assign(p,v,{check:'未確認'});save('追加論点と根拠を更新');});});on('save-draft',()=>{const draft=$('#draft').value;if(draft!==data.proposal.draft)data.proposal.check='未確認';data.proposal.draft=draft;save('下書きを保存');if($('#duplicate-check'))$('#duplicate-check').value=data.proposal.check;});on('copy-draft',async()=>{try{await navigator.clipboard.writeText($('#draft').value);toast('下書きをコピーしました');}catch{toast('コピーできません。下書き欄から選択してください。');}});on('save-posted',()=>{const url=$('#posted').value.trim();if(url&&!discussionCommentUrl(url)){toast('Discussion #19 のコメントURLを入力してください');return;}data.proposal.posted=url;save('投稿済みURLの記録を保存');render();});}
function bindCaseRows(){document.querySelectorAll('[data-edit-case]').forEach(x=>x.onclick=()=>editCase(x.dataset.editCase));document.querySelectorAll('[data-open-case]').forEach(x=>x.onclick=()=>{selectScope(x.dataset.openCase);if(page==='compare')render();else location.hash='compare';});document.querySelectorAll('[data-status="cases"]').forEach(x=>x.onchange=()=>{data.cases.find(c=>c.id===x.dataset.id).status=x.value;save('ケースの状態を更新');});}
$('#form').onsubmit=e=>{e.preventDefault();try{const v=Object.fromEntries(new FormData(e.target));formHandler(v);$('#dialog').close();render();}catch(err){$('#form-error').textContent=err.message;}};$('#close').onclick=$('#cancel').onclick=()=>$('#dialog').close();
window.addEventListener('hashchange',()=>{page=location.hash.slice(1);render();window.scrollTo({top:0});});
$('#export').onclick=()=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=url;a.download='otl-third-workboard-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('JSONを書き出しました');};

function validateImport(board){
  if(board?.schema!=='otl-third-board/1'||!Number.isInteger(board.revision)||board.revision<1) {
    throw Error('このボードのJSONを選んでください。');
  }
  const groups=['plans','cases','steps','comments','decisions','runs'];
  for(const key of [...groups,'history']){
    if(!Array.isArray(board[key])) throw Error('必要な項目がありません：'+key);
  }
  const validId=id=>typeof id==='string'&&/^[a-zA-Z0-9-]+$/.test(id);
  for(const key of groups){
    const rows=board[key];
    if(rows.some(row=>!validId(row?.id)||(key!=='runs'&&typeof row.title!=='string'))||
      new Set(rows.map(row=>row.id)).size!==rows.length) throw Error('項目またはIDが不正です：'+key);
  }
  if(!board.steps.length||!board.plans.some(plan=>plan.id==='baseline')) throw Error('基準方式または評価順序がありません。');
  for(const key of ['plans','cases','decisions']){
    if(board[key].some(item=>!statuses.includes(item.status))) throw Error('状態の値が不正です。');
  }
  if(board.reviewRevision!==undefined&&board.reviewRevision!==1) throw Error('記録の形式に対応していません。');
  const criteria=board.reviewRevision===1?board.criteria:defaultCriteria;
  if(!Array.isArray(criteria)||criteria.some(c=>!validId(c?.id)||typeof c.title!=='string'||
    typeof c.rule!=='string'||!['%','問','件','点'].includes(c.unit)||![1,-1].includes(c.direction)||
    (c.sample!==undefined&&typeof c.sample!=='boolean')||(c.sample&&c.unit!=='件'))||
    new Set(criteria.map(c=>c.id)).size!==criteria.length||
    defaultCriteria.some(item=>!criteria.some(c=>c.id===item.id&&c.unit===item.unit&&Boolean(c.sample)===Boolean(item.sample)))) {
    throw Error('判定基準の形式が不正です。');
  }
  for(const run of board.runs){
    if(!board.plans.some(plan=>plan.id===run.plan)||typeof run.signature!=='string'||typeof run.settings!=='string'||
      (run.scope!=='corpus28'&&!board.cases.some(item=>item.id===run.scope))||typeof run.locked!=='boolean') {
      throw Error('結果の形式が不正です。');
    }
    const snapshot=JSON.parse(run.signature);
    if(!Array.isArray(snapshot?.steps)||snapshot.steps.some(step=>!Array.isArray(step))||
      (snapshot.criteria!==undefined&&(!Array.isArray(snapshot.criteria)||snapshot.criteria.some(row=>!Array.isArray(row))))||
      (run.scope!=='corpus28'&&!Array.isArray(JSON.parse(run.input)))) throw Error('保存した評価条件が不正です。');
    for(const criterion of criteria){
      const value=resultValue(run,criterion.id);
      const sample=sampleSize(run,criterion.id);
      if(value!==null&&(typeof value!=='number'||!Number.isFinite(value)||value<0||(criterion.unit==='%'&&value>100))) {
        throw Error('評価値が不正です。');
      }
      if(sample!==null&&(!Number.isInteger(sample)||sample<0||(value!==null&&sample<value))) {
        throw Error('評価対象数が不正です。');
      }
    }
  }
  for(const original of fresh(false).runs){
    const run=board.runs.find(r=>r.id===original.id);
    const same=run&&['plan','scope','denominator','input','settings','model','locked','evidence'].every(key=>run[key]===original[key])&&
      criteria.every(c=>resultValue(run,c.id)===resultValue(original,c.id)&&sampleSize(run,c.id)===sampleSize(original,c.id));
    if(!same) throw Error('固定済みの既存基準値は変更できません。');
  }
  if(typeof board.proposal?.draft!=='string') throw Error('下書きの形式が不正です。');
  return addReviewRecords(board);
}

$('#import').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>5000000)throw Error('5MB以下のJSONを選んでください。');const incoming=validateImport(JSON.parse(await f.text()));modal('JSONを読み込む',`<p>現在の記録を置き換えます。必要なら先にキャンセルしてJSON保存してください。</p><p class="form-help">${incoming.plans.length}案 / ${incoming.cases.length}ケース / ${incoming.runs.length}結果</p>`,()=>{data=incoming;selectedPlan=data.plans.find(p=>p.id==='middle')?.id||data.plans.find(p=>p.id!=='baseline')?.id;selectScope('corpus28');save('JSONから記録を読み込み');});}catch(err){toast(err.message);}e.target.value='';};
(async()=>{try{const res=await fetch('baseline-evidence.json');if(!res.ok)throw Error('基準値の読み込みに失敗');evidence=await res.json();let stored;try{stored=localStorage.getItem(KEY);}catch{}if(stored){try{const parsed=JSON.parse(stored);const needsUpgrade=parsed.reviewRevision===undefined;data=validateImport(parsed);if(needsUpgrade)save('',false);}catch{data=fresh();sessionNotice='保存データを読み込めないため、初期状態を表示しています。保存データはJSON読み込みで確認できます。';}}else{data=fresh();save('',false);}render();}catch(err){$('#view').innerHTML=`<div class="callout">${esc(err.message)}。ページを再読み込みしてください。</div>`;}})();

// Review of the public #23 fixture. This view is independent of editable board data.
function caseGraphReview(){
  const revision=caseRevision;
  const pinned=repo+'/blob/'+revision+'/';
  const table=(title,headers,rows)=>panel(title,`<div class="table-wrap" data-ui-scroll="table" aria-label="${esc(title)}"><table>
    <thead><tr>${headers.map(label=>`<th scope="col">${esc(label)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(([label,...cells])=>`<tr><th scope="row" class="wrap">${esc(label)}</th>${cells.map(cell=>`<td class="wrap">${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>`);
  const checks=[
    'K001〜K004を同じコーパスと sure=1 で再実行し、候補、判断、適合先、未登録要素、6W1Hの空欄を保存前後で照合する。',
    '候補なしの事例に肯定・否定の判断を追加し、両方を取得する。別概念への否定だけの場合は、候補への明示的な承認と区別する。',
    '未判断、holds=false、未登録の要素、未登録概念への判断を区別する。未登録の概念や同名の概念から自動で同一関係を作らない。',
    '担当者名を変更して候補・比較状態が一致すること、同じ役割の複数の判断が残ることを確認する。',
    '同一版の再取得、訂正、再推論を試し、重複登録なしで旧版を取得できることを確認する。',
    '事例・判断の追加前後で define・rules・guess、概念スナップショット、既存監査の検査・計画結果を比較する。'
  ];
  return heading('設計レビュー','事例と知識グラフ','観測・候補・人の判断をつなぐ2方式を、PR #23の同じ4事例で比較します。')+
    `<div class="callout"><div><b>推奨案は Observation・Evidence・Snapshot の再利用</b><p>事例、候補を出した実行、人の判断を別の記録にします。人の判断は対象事例の版に紐付け、候補生成と概念定義は従来の入力で評価します。</p></div><span class="pill">接続方式は検討中</span></div>`+
    table('方式の比較',['評価軸','専用の Case・Judgment クラス','既存クラスの再利用'],[
      ['重複実装','型は明快。既存の監視層と共通化する設計が必要','digest・証跡・語彙検査を共有。事例用の変換と検査を追加'],
      ['履歴','Caseを軸に観測・判断の版をたどる','case_keyと変更不能な記録IDを分けてたどる'],
      ['証跡','専用クラスと既存証跡の接続を規定する','hasEvidence と derived_from の接続規約を再利用'],
      ['問い合わせ','クラスで対象を絞り込める','record_kind で対象を絞り、判断・候補を関係から取得する']
    ])+
    recordedCasePanel()+
    panel('最小のデータ契約',`<div class="panel-body">
      <p>事例キーと記録IDを分け、対象版、出典SHA・ファイル・記録位置を保存します。出典に日時がない場合は空欄とし、収集時刻は別欄に置きます。</p>
      <p>事例には元の発言・文脈・要素・6W1Hを保持します。候補には実装とコーパスの版、sure、適合先、空欄、to_modelを添えます。判断は対象版、概念参照、真偽の holds、根拠を持ちます。</p>
      <p>担当者と役割を別属性にし、氏名のノード化は設計対象外とします。概念は登録済みIDで参照し、IDがないときはコーパス版と既存識別子を組にします。未解決の参照は検査結果に残します。</p>
      <p>既存監査の observes は PullRequest 向けで、監査の作業状態は5種です。事例用の変換・検査を設け、比較状態は専用の欄に置きます。</p>
    </div>`)+
    table('関係種別の案',['関係','接続','記録の意味'],[
      ['about_case','推論・判断のObservation → 事例Observation','対象となった事例の版'],
      ['proposes','推論のObservation → Concept','候補（hypothesis）'],
      ['asserts','判断のObservation → Concept','その人が判断したという記録（observed）。holdsで肯定・否定を保持'],
      ['hasEvidence / derived_from','Observation → Evidence / Snapshot','既存の証跡と入力版への参照'],
      ['revises','新しいObservation → 旧Observation','訂正対象を明示し、旧記録を保持']
    ])+
    panel('回帰テスト案',`<div class="panel-body"><p>現行の judged は候補がない状態で複数判断が矛盾しても返ります。confirmed は他概念への否定だけでも返る場合があります。比較状態と個々の判断を合わせて確認します。</p><ol>${checks.map(check=>`<li>${esc(check)}</li>`).join('')}</ol></div>`)+
    panel('未確定事項と出典',`<div class="panel-body">
      <p>役割ごとの判断権限、複数判断の採用規則、訂正の識別方法、ID未付与概念の移行、未解決参照の保管方式は検討中です。</p>
      <p>現行結果は統合コミット <code>${revision.slice(0,7)}</code> の事例データを <code>cases --sure 1</code> で評価したものです。グラフ欄は設計案です。</p>
      <p>${link(repo+'/pull/23','PR #23')} · ${link(pinned+'examples/concepts-20261115.json','事例データ')} · ${link(pinned+'tools/tautology.py#L439','cases 実装')} · ${link(pinned+'gh_audit/gh_audit.py#L32','監査語彙')} · ${link(discussion,'Discussion #19')}</p>
    </div>`);
}
