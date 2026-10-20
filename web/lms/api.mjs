let unauthorized = () => {};
export const onUnauthorized = callback => { unauthorized = callback; };
export class ApiError extends Error {
  constructor(status, data = {}) { super(data.error || `HTTP ${status}`); this.status = status; this.data_access = data.data_access || []; }
}
async function failure(response) {
  let data = {}; try { data = await response.json(); } catch {}
  if (response.status === 401) unauthorized();
  throw new ApiError(response.status, data);
}
export async function api(path, {method = 'GET', body, signal} = {}) {
  if (!/^[a-z][a-z0-9/?=&%._-]*$/i.test(path)) throw new Error('Некорректный путь API');
  const response = await fetch(`/api/v1/${path}`, {method, credentials:'same-origin', signal,
    headers: {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) return failure(response);
  return response.json();
}
export async function studentSession(request = api) {
  // Temporary demo entry uses the same signed HttpOnly session as normal login.
  let current;
  try { current = await request('me'); }
  catch (error) { if (error.status !== 401) throw error; }
  const isStudentOne = actor => actor?.id === 'student1' && actor.role === 'student';
  if (isStudentOne(current?.user)) return current.user;
  const result = await request('auth/login', {method:'POST', body:{username:'student1',password:'student1'}});
  if (!isStudentOne(result?.user)) throw new Error('Не удалось открыть кабинет студента 1.');
  return result.user;
}
export async function readEvents(response, receive) {
  if (!response.ok) return failure(response);
  if (!response.body) throw new Error('Поток ответа отсутствует');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', lines = [];
  const event = () => {
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    lines = []; return data ? JSON.parse(data) : null;
  };
  try {
    for (;;) {
      const {value, done} = await reader.read(); buffer += decoder.decode(value, {stream:!done});
      let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0,end).replace(/\r$/, ''); buffer = buffer.slice(end+1);
        if (line) { lines.push(line); continue; }
        const data = event(); if (!data) continue;
        receive(data);
        if (data.type === 'error') { if (data.status === 401) unauthorized(); throw new ApiError(data.status || 503, data); }
        if (data.type === 'complete') return data.response;
      }
      if (done) throw new Error('Поток завершился без complete/error. Результат не подтверждён.');
    }
  } finally { try { await reader.cancel(); } finally { reader.releaseLock(); } }
}
export async function queryAgent(payload, receive, signal) {
  const response = await fetch('/api/v1/agent/stream', {method:'POST', credentials:'same-origin', signal,
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  return readEvents(response, receive);
}
