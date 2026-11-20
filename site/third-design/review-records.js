const caseFixtures = [
  {
    "id": "K001-night-db",
    "statement": "自分では解けないので、再起動してよいか二次対応に判断を仰ぎます",
    "context": "障害対応・夜間",
    "evidence": "当番チャット",
    "role": "一次対応",
    "six": {
      "誰が": "一次対応",
      "誰へ": "二次対応",
      "何を": "DB の応答遅延",
      "どうやって": "電話",
      "いつまで": "30分以内に返事",
      "どう": "再起動の判断を仰ぐ"
    },
    "elements": [
      "連絡",
      "上位へ引き上げる",
      "判断を委ねる",
      "契機:自分では解けない"
    ]
  },
  {
    "id": "K002-share-only",
    "statement": "状況だけ共有します。対応はこちらで続けます",
    "context": "障害対応・日中",
    "evidence": "チャット",
    "role": "一次対応",
    "six": {
      "誰が": "一次対応",
      "誰へ": "関係者",
      "何を": "応答遅延の状況",
      "どうやって": "チャット",
      "どう": "共有だけ"
    },
    "elements": [
      "連絡",
      "状況を伝える",
      "判断は委ねない",
      "向き:関係者へ"
    ]
  },
  {
    "id": "K003-shift-change",
    "statement": "夜勤から日勤へ、対応中の件を渡します",
    "context": "交代",
    "evidence": "引き継ぎメモ",
    "role": "夜勤",
    "six": {
      "誰が": "夜勤",
      "誰へ": "日勤",
      "何を": "対応中の件",
      "どうやって": "引き継ぎメモ"
    },
    "elements": [
      "連絡",
      "担当を渡す",
      "契機:交代",
      "引き継ぎメモを書く"
    ]
  },
  {
    "id": "K004-first-word",
    "statement": "とりあえず一報入れました",
    "context": "障害対応・日中",
    "evidence": "チャット",
    "role": "一次対応",
    "six": {
      "誰が": "一次対応",
      "どうやって": "チャット"
    },
    "elements": [
      "連絡"
    ]
  }
];

const defaultCriteria = [
  {id:'accuracy', title:'正直な回答の正解率', unit:'%', direction:1, rule:'正解IDを返した既知概念数 ÷ 正直な回答での全試行数。'},
  {id:'unknown', title:'未知概念の拒否', unit:'%', direction:1, rule:'候補コーパスから除外した概念を「知らない」と判定した数 ÷ 未知概念の全試行数。'},
  {id:'forget', title:'忘却への対応', unit:'%', direction:1, rule:'要素を一つ隠しても正解IDに到達した数 ÷ 全忘却試行数。'},
  {id:'questions', title:'平均質問数', unit:'問', direction:-1, rule:'正直な回答の各試行で、追加確認を含む質問数の平均。'},
  {id:'max', title:'最大質問数', unit:'問', direction:-1, rule:'正直な回答の各試行で、追加確認を含む質問数の最大値。'},
  {id:'candidate-errors', title:'候補の誤一致', unit:'件', direction:-1, sample:true, rule:'正解以外の概念IDが候補に入った件数。入力×候補の組を数え、評価対象数を記録する。'},
  {id:'merges', title:'確定した誤統合', unit:'件', direction:-1, sample:true, rule:'異なる概念を同じIDへ確定した件数。分母は判定対象の組数。候補の誤一致は別に数える。暫定基準。'}
];

const caseObservations = [
  ['エスカレーション','障害対応の責任者：エスカレーション','confirmed','候補と責任者の判断が一致。候補の根拠は hypothesis のまま。'],
  ['状況報告','課長：エスカレーション','disputed','候補と課長の判断が食い違う。両方を保持。'],
  ['担当引き継ぎ','未判断','pending','「引き継ぎメモを書く」は未登録。6W1Hの期限と行動が未記入。'],
  ['候補なし（適合先3件）','障害対応の責任者：状況報告','judged','候補なしと責任者の判断を保持。']
];

const caseRevision = '12d1569ac6065085c178d53d348fde5a20a3e5d6';
const caseSource = 'https://github.com/myon-bioinformatics/OnTautoLogy/blob/'+caseRevision+'/examples/concepts-20261115.json';

const recordedHierarchy = [
  ['既存方式', 6.6, 12.6, 93],
  ['属性：値を追加', 5.4, 10.9, 100],
  ['上位階層も追加', 3.2, 7.4, 100]
];

const repo='https://github.com/myon-bioinformatics/OnTautoLogy', discussion=repo+'/discussions/19', sha='79eba5343276f328d1de0854f162c42a21849e7b', blob='c84feff6748a0708899f6bfb95091c0cea9edfb9', source=repo+'/blob/'+sha+'/', KEY='otl-third-board-v1';

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

function caseInput(id, board=data){
  if(id==='corpus28') return blob;
  const c=board.cases.find(x=>x.id===id);
  return c?JSON.stringify([c.input,c.expected,c.context]):'missing';
}
