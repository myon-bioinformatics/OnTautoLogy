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
