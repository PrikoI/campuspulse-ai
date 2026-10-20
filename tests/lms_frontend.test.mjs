import test from 'node:test';
import assert from 'node:assert/strict';
import {api, readEvents, onUnauthorized, ApiError} from '../web/lms/api.mjs';
import {safeURL} from '../web/lms/ui.mjs';
import {bindAgent} from '../web/lms/agent.mjs';

function stream(text) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  }}));
}

test('SSE handles fragmented UTF8, CRLF and structured completion', async () => {
  const events = [];
  const result = await readEvents(stream('data: {"type":"tool_start","tool":"get_courses"}\r\n\r\ndata: {"type":"complete","response":{"answer":"Привет"}}\r\n\r\n'), event => events.push(event));
  assert.equal(result.answer, 'Привет');
  assert.equal(events.length, 2);
});

test('SSE errors reset unauthorized state; truncated stream fails', async () => {
  let reset = 0; onUnauthorized(() => reset++);
  await assert.rejects(readEvents(stream('data: {"type":"error","status":401,"error":"Session expired"}\n\n'), () => {}), error => error instanceof ApiError && error.status === 401);
  assert.equal(reset, 1);
  await assert.rejects(readEvents(stream('data: {"type":"started"}\n\n'), () => {}), /без complete/);
});

test('API uses same-origin cookie and JSON; propagates 401', async () => {
  const original = globalThis.fetch;
  let calls = [], reset = 0;
  onUnauthorized(() => reset++);
  globalThis.fetch = async (...args) => { calls.push(args); return Response.json({items: []}); };
  try {
    assert.deepEqual(await api('data/query', {method:'POST', body:{resource:'courses'}}), {items:[]});
    assert.equal(calls[0][0], '/api/v1/data/query');
    assert.equal(calls[0][1].credentials, 'same-origin');
    assert.deepEqual(JSON.parse(calls[0][1].body), {resource:'courses'});
    globalThis.fetch = async () => Response.json({error:'Expired'}, {status:401});
    await assert.rejects(api('me'), error => error.status === 401);
    assert.equal(reset, 1);
    await assert.rejects(api('https://attacker.example'), /путь/);
  } finally { globalThis.fetch = original; }
});

test('Source links reject executable schemes and relative paths', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,evil', '/api/v1/me', 'file:///secret']) assert.equal(safeURL(value), '');
  assert.equal(safeURL('https://example.org/course'), 'https://example.org/course');
});

test('Logout prevents late SSE completion from restoring another session data', async () => {
  const original = {fetch:globalThis.fetch, document:globalThis.document, FormData:globalThis.FormData};
  let submit, respond, reviews = 0;
  const button = {disabled:false}, trace = {textContent:''}, answer = {textContent:''};
  const form = {addEventListener(name, handler) { submit = handler; }, querySelector() { return button; }};
  globalThis.document = {querySelector(selector) { return {'#agent':form,'#trace':trace,'#answer':answer}[selector]; }};
  globalThis.FormData = class { get(name) { return name === 'message' ? 'My tasks' : 'local'; } };
  globalThis.fetch = () => new Promise(resolve => { respond = resolve; });
  try {
    const stop = bindAgent(() => ({}), () => reviews++);
    const pending = submit({preventDefault() {}, currentTarget:form});
    stop();
    respond(stream('data: {"type":"tool_result","result":{"private":"previous-user"}}\n\ndata: {"type":"complete","response":{"answer":"previous-user","results":{"prepare_personal_change":{"proposal":"private"}}}}\n\n'));
    await pending;
    assert.equal(answer.textContent, '');
    assert.equal(trace.textContent, '');
    assert.equal(reviews, 0);
    assert.equal(button.disabled, false);
  } finally { Object.assign(globalThis, original); }
});
