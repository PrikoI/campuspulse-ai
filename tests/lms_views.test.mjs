import test from 'node:test';
import assert from 'node:assert/strict';
import {courseCards,gradeSummary,attendanceSummary,reviewChange,personalTasks} from '../web/lms/views.mjs';
import {editor} from '../web/lms/screens.mjs';

class Node {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.handlers={};this.dataset={};this.value='';this.type='';this.ownText='';}
  set textContent(value){this.ownText=String(value);this.children=[];}
  get textContent(){return this.ownText+this.children.map(child=>child.textContent).join(' ');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.ownText='';this.children=[...children];}
  addEventListener(name,handler){this.handlers[name]=handler;}
  setAttribute(name,value){this[name]=value;}
  reportValidity(){return true;}
  get options(){return this.children;}
}
const all=(node,tag)=>[...(node.tagName===tag.toUpperCase()?[node]:[]),...node.children.flatMap(child=>all(child,tag))];
function dom(){globalThis.document={createElement:tag=>new Node(tag),querySelector:()=>new Node('p')};globalThis.Option=class extends Node {constructor(label,value){super('option');this.textContent=label;this.value=value;}};return new Node('div');}

test('course cards show subjects and useful actions without database internals',()=>{
  const root=dom();const opened=[];
  courseCards(root,[{id:'private-course-document-id',name:'Introduction To Programming',code:'SUB-internal',instructor_ids:['teacher1','teacher2'],policy:{name:'internal-policy',attestation1_weight:.3,attestation2_weight:.3,final_weight:.4,source_url:'https://example.org/guide'}}],(...args)=>opened.push(args));
  assert.match(root.textContent,/Introduction To Programming/);assert.match(root.textContent,/30%/);
  assert.doesNotMatch(root.textContent,/private-course-document-id|instructor_ids|internal-policy|SUB-internal|\{/);
  all(root,'button').find(button=>button.textContent==='Оценки').handlers.click();
  assert.deepEqual(opened,[['grades','private-course-document-id']]);
});

test('grade view preserves zero scores and distinguishes ungraded work',()=>{
  const root=dom();gradeSummary(root,{calculation:{register:null,total:null,required_final:null,target_total:50},items:[{id:'hidden-grade',title:'Assignment 1',component:'regmid',score:0,max_score:100},{title:'Midterm',component:'midterm',score:null,max_score:100}]});
  assert.match(root.textContent,/0 \/ 100/);assert.match(root.textContent,/Не выставлена/);assert.match(root.textContent,/Оценено/);
  assert.doesNotMatch(root.textContent,/hidden-grade|regmid|"calculation"|\{/);
});

test('attendance distinguishes absent, unmarked and future lessons',()=>{
  const root=dom();attendanceSummary(root,{summary:{present:0,late:0,absent:1,unmarked:1,attendance_percent:0},records:[{lesson_id:'one',status:'absent'}],lessons:[{id:'one',title:'Lecture',starts_at:'2000-01-01T10:00:00+05:00',ends_at:'2000-01-01T11:00:00+05:00'},{id:'two',title:'Practice',starts_at:'2000-01-02T10:00:00+05:00',ends_at:'2000-01-02T11:00:00+05:00'},{id:'three',title:'Future',starts_at:'2050-01-02T10:00:00+05:00',ends_at:'2050-01-02T11:00:00+05:00'}]});
  assert.match(root.textContent,/Отсутствовал/);assert.match(root.textContent,/Не отмечено/);assert.match(root.textContent,/Предстоит/);
});

test('personal task action prepares the correct record without exposing its ID',async()=>{
  const root=dom();const proposals=[];personalTasks(root,{tasks:[{id:'private-task-id',title:'Read chapter',due:null,minutes:30,done:false}]},async change=>proposals.push(change));
  await all(root,'button').find(button=>button.textContent==='Завершить').handlers.click();
  assert.equal(proposals[0].record_id,'private-task-id');assert.equal(proposals[0].payload.done,true);assert.doesNotMatch(root.textContent,/private-task-id/);
});

test('review shows the proposed tasks without proposal tokens or JSON',()=>{
  const root=dom();reviewChange(root,{target:'study_plan',tasks:[{id:'hidden-id',title:'Prepare Midterm',course:'Physics I',due:'2030-01-01T12:00:00+05:00',minutes:50}]});
  assert.match(root.textContent,/Prepare Midterm/);assert.match(root.textContent,/Physics I/);assert.doesNotMatch(root.textContent,/hidden-id|"tasks"|\{/);
});

test('material form submits selected subject IDs through typed controls',async()=>{
  const root=dom();const requests=[];const original=globalThis.fetch;globalThis.fetch=async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return Response.json({item:{}});};
  try{
    await editor(root,'materials','subject-id',[{id:'subject-id',name:'Physics I'}],[],()=>true,async()=>{});
    const form=all(root,'form')[0];const labels=all(form,'label');
    const input=label=>labels.find(node=>node.ownText===label).children[0];
    input('Название материала').value='Lecture notes';input('Текст материала').value='Read <script> as plain text';
    await form.handlers.submit({preventDefault(){}});
    assert.equal(requests[0].path,'/api/v1/admin/materials');assert.equal(requests[0].body.course_id,'subject-id');assert.equal(requests[0].body.name,'Lecture notes');
    assert.equal(requests[0].body.text,'Read <script> as plain text');assert.doesNotMatch(root.textContent,/Поля записи в JSON|ID для изменения/);
  }finally{globalThis.fetch=original;}
});
