import test from 'node:test';
import assert from 'node:assert/strict';
import {bindAgent,chatHistory} from '../web/lms/agent.mjs';
import {chatDOM,all,completionStream} from './chat_dom.mjs';

test('follow-up questions carry successful text context and preserve previous bubbles',async()=>{
  const dom=chatDOM(),original=globalThis.fetch,calls=[];
  globalThis.fetch=async(url,options)=>{calls.push(JSON.parse(options.body));return completionStream({answer:calls.length===1?'First answer':'Follow-up answer'});};
  try {
    bindAgent(()=>({page:'grades',course_id:'physics'}),()=>{});
    dom['chat-input'].value='<script>question</script>';await dom.agent.requestSubmit();
    dom['chat-input'].value='Explain that';await dom.agent.requestSubmit();
    assert.deepEqual(calls[0].history,[]);
    assert.deepEqual(calls[1].history,[{role:'user',content:'<script>question</script>'},{role:'assistant',content:'First answer'}]);
    assert.equal(calls[1].course_id,'physics');
    assert.equal(dom['chat-messages'].querySelector('script'),null);
    assert.match(dom['chat-messages'].textContent,/First answer/);assert.match(dom['chat-messages'].textContent,/Follow-up answer/);
    assert.equal(all(dom['chat-messages']).filter(node=>node.tagName==='ARTICLE').length,4);
    assert.equal(dom['chat-input'].value,'');assert.equal(dom['chat-send'].disabled,false);
  }finally{globalThis.fetch=original;dom.restore();}
});

test('failed turns stay visible but are excluded from later model context',async()=>{
  const dom=chatDOM(),original=globalThis.fetch,calls=[];
  globalThis.fetch=async(url,options)=>{calls.push(JSON.parse(options.body));return calls.length===1?Response.json({error:'Provider unavailable'},{status:503}):completionStream({answer:'OK'});};
  try{
    bindAgent(()=>({}),()=>{});dom['chat-input'].value='Failed question';await dom.agent.requestSubmit();
    assert.match(dom['chat-messages'].textContent,/Provider unavailable/);
    dom['chat-input'].value='New question';await dom.agent.requestSubmit();assert.deepEqual(calls[1].history,[]);
  }finally{globalThis.fetch=original;dom.restore();}
});

test('new chat clears context and review remains an explicit action',async()=>{
  const dom=chatDOM(),original=globalThis.fetch,calls=[],reviews=[];
  const proposal={proposal:'signed-private-token',change:{target:'task'}};
  globalThis.fetch=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return completionStream({answer:'Please review',results:{prepare_personal_change:proposal}});};
  try{
    bindAgent(()=>({}),value=>reviews.push(value));dom['chat-input'].value='Prepare task';await dom.agent.requestSubmit();
    assert.equal(reviews.length,1);assert.equal(calls[0].url,'/api/v1/agent/stream');
    assert.doesNotMatch(dom['chat-messages'].textContent,/signed-private-token/);
    dom['new-chat'].handlers.click();assert.doesNotMatch(dom['chat-messages'].textContent,/Prepare task|Please review/);
    dom['chat-input'].value='Fresh question';await dom.agent.requestSubmit();assert.deepEqual(calls[1].body.history,[]);
    assert.equal(calls.length,2); // No confirmation/write API was called.
  }finally{globalThis.fetch=original;dom.restore();}
});

test('stop allows a new request while a late result cannot replace it',async()=>{
  const dom=chatDOM(),original=globalThis.fetch;let respond,count=0;
  globalThis.fetch=()=>++count===1?new Promise(resolve=>{respond=resolve;}):Promise.resolve(completionStream({answer:'Current answer'}));
  try{
    bindAgent(()=>({}),()=>{});dom['chat-input'].value='Old request';const pending=dom.agent.requestSubmit();
    dom['chat-stop'].handlers.click();dom['chat-input'].value='New request';await dom.agent.requestSubmit();
    respond(completionStream({answer:'Late private answer'}));await pending;
    assert.match(dom['chat-messages'].textContent,/Current answer/);assert.doesNotMatch(dom['chat-messages'].textContent,/Late private answer/);
    assert.equal(dom['chat-send'].disabled,false);
  }finally{globalThis.fetch=original;dom.restore();}
});

test('chat context keeps four recent pairs within the server character limit',()=>{
  const turns=Array.from({length:10},(_,index)=>({message:'Question '+index,answer:'Answer '+index}));
  const history=chatHistory(turns);assert.equal(history.length,8);assert.equal(history[0].content,'Question 6');
  assert.equal(chatHistory([{message:'q',answer:'x'.repeat(8001)}]).length,0);
  const bounded=chatHistory(Array.from({length:4},()=>({message:'q'.repeat(5000),answer:'a'.repeat(6000)})));
  assert.ok(bounded.reduce((size,item)=>size+item.content.length,0)<=20000);
});

test('Enter sends, Shift+Enter and IME composition preserve text entry',async()=>{
  const dom=chatDOM(),original=globalThis.fetch;let calls=0;
  globalThis.fetch=async()=>{calls++;return completionStream({answer:'OK'});};
  try{
    bindAgent(()=>({}),()=>{});dom['chat-input'].value='Hello';let prevented=0;
    const key=(shiftKey,isComposing)=>dom['chat-input'].handlers.keydown({key:'Enter',shiftKey,isComposing,preventDefault(){prevented++;}});
    key(true,false);key(false,true);assert.equal(calls,0);key(false,false);
    await new Promise(resolve=>setTimeout(resolve,10));assert.equal(calls,1);assert.equal(prevented,1);
  }finally{globalThis.fetch=original;dom.restore();}
});
