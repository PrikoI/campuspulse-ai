import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {api,ApiError,onUnauthorized,studentSession} from '../web/lms/api.mjs';
import {chatDOM} from './chat_dom.mjs';

const student = {id:'student1',role:'student',name:'Студент 1'};

test('automatic entry signs in as student1 through the ordinary login endpoint',async()=>{
  const calls=[];
  const actor=await studentSession(async(path,options)=>{
    calls.push({path,options});
    if(path==='me')throw new ApiError(401);
    return {user:student};
  });
  assert.deepEqual(actor,student);
  assert.deepEqual(calls,[{path:'me',options:undefined},{path:'auth/login',options:{method:'POST',body:{username:'student1',password:'student1'}}}]);
});

test('existing student1 session is reused; other identities are replaced',async()=>{
  for(const current of [student,{id:'admin',role:'admin'},{id:'student2',role:'student'}]){
    const calls=[];
    const actor=await studentSession(async path=>{calls.push(path);return {user:path==='me'?current:student};});
    assert.deepEqual(actor,student);
    assert.deepEqual(calls,current===student?['me']:['me','auth/login']);
  }
});

test('database and login failures remain visible instead of inventing a session',async()=>{
  const unavailable=new ApiError(503,{error:'Firestore unavailable'}),calls=[];
  await assert.rejects(studentSession(async path=>{calls.push(path);throw unavailable;}),error=>error===unavailable);
  assert.deepEqual(calls,['me']);
  await assert.rejects(studentSession(async path=>{if(path==='me')throw new ApiError(401);throw new ApiError(403,{error:'Profile role mismatch'});}),/Profile role mismatch/);
  await assert.rejects(studentSession(async()=>({user:{id:'admin',role:'admin'}})),/кабинет студента 1/);
});

test('page opens the student cabinet without login controls and renews expired sessions',async()=>{
  const saved=Object.fromEntries(['document','fetch','Option','localStorage'].map(key=>[key,globalThis[key]]));
  const dom=chatDOM(['workspace','session-panel','session-spinner','session-retry','session-message','identity','content','review','review-data','course','navigation','agent-panel','page-title','error','status','theme','confirm','cancel'].map(id=>[id,id==='course'?'select':'div']));
  document.documentElement={dataset:{}};
  globalThis.Option=function(label,value){const node=document.createElement('option');node.textContent=label;node.value=value;return node;};
  globalThis.localStorage={getItem(){return null;},setItem(){}};
  let authenticated=false,logins=0;
  globalThis.fetch=async(path,options)=>{
    if(path==='/api/v1/me')return Response.json(authenticated?{user:student}:{error:'Expired'},{status:authenticated?200:401});
    if(path==='/api/v1/auth/login'){
      assert.deepEqual(JSON.parse(options.body),{username:'student1',password:'student1'});
      authenticated=true;logins++;return Response.json({user:student});
    }
    if(path==='/api/v1/status')return Response.json({team_database_connected:true,llm:{calls_enabled:true,model:'gemma4'}});
    if(path==='/api/v1/courses')return Response.json({items:[]});
    if(path==='/api/v1/personal')return Response.json({error:'Expired'},{status:401});
    throw new Error('Unexpected API path: '+path);
  };
  try{
    const html=readFileSync(new URL('../web/lms/index.html',import.meta.url),'utf8');
    assert.doesNotMatch(html,/id="login"|name="username"|name="password"|id="logout"/);
    await import('../web/lms/app.mjs');
    assert.equal(logins,1);assert.equal(dom.workspace.hidden,false);assert.equal(dom.workspace.dataset.role,'student');
    assert.equal(dom['session-panel'].hidden,true);assert.equal(dom.identity.textContent,'Студент 1');assert.equal(dom['agent-panel'].hidden,false);
    assert.match(dom.navigation.textContent,/План подготовки/);assert.doesNotMatch(dom.navigation.textContent,/Студенты|Зачисление/);
    authenticated=false;
    await assert.rejects(api('personal'),error=>error.status===401);
    await new Promise(resolve=>setTimeout(resolve,10));
    assert.equal(logins,2);assert.equal(dom.workspace.hidden,false);
  }finally{onUnauthorized(()=>{});dom.restore();Object.assign(globalThis,saved);}
});
