import {schedule} from './schedule.mjs';
import {courseList} from './courses.mjs';
import {gradebook} from './gradebook.mjs';
import {api,onUnauthorized} from './api.mjs';
import {element,records,showError} from './ui.mjs';
import {collections,adminForm,personalForm} from './forms.mjs';
import {bindAgent} from './agent.mjs';
const $ = selector => document.querySelector(selector);
let user = null, page = 'courses', requestVersion = 0, pendingProposal = null;
const pages = {courses:'Дисциплины',assignments:'Задания',materials:'Материалы',grades:'Оценки',attendance:'Посещаемость',schedule:'Расписание',plan:'Учебный план',data:'Каталог данных',personal:'Личные задачи'};
function reset() { user = null; requestVersion++; pendingProposal = null; stopAgent(); $('#workspace').hidden = true; $('#login-panel').hidden = false; $('#logout').hidden = true; $('#identity').textContent = ''; $('#content').replaceChildren(); $('#trace').textContent = ''; $('#answer').textContent = ''; $('#review').hidden = true; $('#course').replaceChildren(new Option('Все доступные','')); }
onUnauthorized(reset);
function review(proposal) { pendingProposal = proposal; $('#review-data').textContent = JSON.stringify(proposal.change,null,2); $('#review').hidden = false; }
const prepare = async change => { const actor = user, proposal = await api('actions/prepare',{method:'POST',body:change}); if (actor === user) review(proposal); };
const stopAgent = bindAgent(() => ({page:Object.hasOwn(pages,page) && !['personal','data'].includes(page) ? page : 'overview',...($('#course').value ? {course_id:$('#course').value} : {})}),review);
$('#confirm').addEventListener('click',async () => { if (!pendingProposal) return; $('#confirm').disabled = true; try { await api('actions/confirm',{method:'POST',body:{proposal:pendingProposal.proposal,confirmed:true}}); pendingProposal = null; $('#review').hidden = true; await load(); } catch(error) { showError(error); } finally { $('#confirm').disabled = false; } });
$('#cancel').addEventListener('click',() => { pendingProposal = null; $('#review').hidden = true; });
async function load() {
  const version = ++requestVersion, container = $('#content'), cid = $('#course').value;
  container.replaceChildren(); $('#error').textContent = ''; $('#page-title').textContent = pages[page] || page;
  const loading = element('div',undefined,container); loading.className = 'page-loading';
  loading.setAttribute('role','status'); loading.setAttribute('aria-live','polite');
  const spinner = element('span',undefined,loading); spinner.className = 'loading-spinner'; spinner.setAttribute('aria-hidden','true');
  element('span','Загрузка…',loading);
  const target = element('div',undefined,container); target.hidden = true; target.setAttribute('aria-busy','true');
  const query = cid ? '?course_id=' + encodeURIComponent(cid) : '', prefix = user?.role === 'admin' ? 'admin/' : '';
  try {
    if (page === 'courses' && user.role === 'admin') {
      await courseList(target, load, () => version === requestVersion, rows => {
        const current = $('#course').value;
        $('#course').replaceChildren(new Option('Все доступные',''), ...rows.filter(row => !row.archived).map(row => new Option(row.name,row.id)));
        $('#course').value = rows.some(row => row.id === current && !row.archived) ? current : '';
      });
    } else if (page === 'grades' && user.role === 'admin') {
      await gradebook(target, cid, load, () => version === requestVersion);
    } else if (page === 'schedule') {
      await schedule(target, prefix, query, () => version === requestVersion);
    } else if (page === 'data') {
      const data = await api('data/resources'); if (version !== requestVersion) return; records(target,data.resources);
      const form = element('form',undefined,target), input = element('textarea',undefined,element('label','Именованный запрос JSON: resource, filters, fields, limit',form)); input.value = '{}'; element('button','Выполнить запрос',form);
      form.addEventListener('submit',async event => { event.preventDefault(); try { const result = await api('data/query',{method:'POST',body:JSON.parse(input.value)}); if (version === requestVersion) { const out = element('section',undefined,target); records(out,result.items); if (result.next_cursor) element('p','Есть следующая страница. Передайте в cursor: ' + result.next_cursor,out); } } catch(error) { showError(error); } });
    } else if (page === 'personal') {
      const data = await api('personal'); if (version !== requestVersion) return; records(target,data.tasks); personalForm(target,prepare);
      for (const task of data.tasks) { const button = element('button',`Удалить: ${task.title}`,target); button.addEventListener('click',() => prepare({target:'task',operation:'delete',record_id:task.id,payload:{}}).catch(showError)); }
      const form = element('form',undefined,target), hours = element('input',undefined,element('label','Часов подготовки в день',form)); hours.type = 'number'; hours.min = '1'; hours.max = '8'; hours.step = '.5'; hours.value = data.preferences.hours_per_day; element('button','Проверить настройку',form);
      form.addEventListener('submit',event => { event.preventDefault(); prepare({target:'preferences',payload:{hours_per_day:Number(hours.value)}}).catch(showError); });
    } else if (page === 'plan' || (['grades','attendance'].includes(page) && user.role === 'student')) {
      if (page !== 'plan' && !cid) { element('p','Выберите дисциплину.',target); return; }
      const result = page === 'plan' ? await api('agent/query',{method:'POST',body:{message:'План подготовки',page:'plan',...(cid ? {course_id:cid} : {})}}) : await api(`${page === 'grades' ? 'grade' : 'attendance'}-summary${query}`);
      if (version !== requestVersion) return; element('pre',JSON.stringify(result,null,2),target);
    } else {
      const kind = page === 'schedule' ? 'lessons' : page;
      if (!collections.includes(kind)) return;
      // The write form remains usable on an empty collection; the server enforces ownership.
      if (user.role === 'admin') adminForm(target,kind,load);
      const data = await api(prefix + kind + query); if (version !== requestVersion) return; records(target,data.items);
      if (kind === 'courses') { const current = $('#course').value; $('#course').replaceChildren(new Option('Все доступные',''),...data.items.filter(row => !row.archived).map(row => new Option(row.name,row.id))); $('#course').value = current; }
    }
  } catch(error) { if (version === requestVersion) showError(error); }
  finally {
    loading.remove();
    if (version === requestVersion) { target.hidden = false; target.removeAttribute('aria-busy'); }
  }
}
function signedIn(actor) {
  user = actor; $('#login-panel').hidden = true; $('#workspace').hidden = false; $('#logout').hidden = false; $('#identity').textContent = `${actor.name} (${actor.role})`; $('#agent-panel').hidden = actor.role !== 'student';
  $('#navigation').replaceChildren(); const available = actor.role === 'admin' ? [...collections.filter(kind => !['lessons'].includes(kind)), 'schedule','data'] : Object.keys(pages);
  for (const name of available) { const button = element('button',pages[name] || name,$('#navigation')); button.addEventListener('click',() => { page = name; for (const item of $('#navigation').children) item.removeAttribute('aria-current'); button.setAttribute('aria-current','page'); load(); }); }
  page = 'courses'; load();
}
$('#login').addEventListener('submit',async event => { event.preventDefault(); const data = new FormData(event.currentTarget); try { const result = await api('auth/login',{method:'POST',body:{username:data.get('username'),password:data.get('password')}}); event.target.reset(); signedIn(result.user); } catch(error) { showError(error); } });
$('#logout').addEventListener('click',async () => { try { await api('auth/logout',{method:'POST',body:{}}); reset(); } catch(error) { showError(error); } });
$('#course').addEventListener('change',load);
try { document.documentElement.dataset.theme = localStorage.getItem('campuspulse-theme') || 'light'; } catch {}
$('#theme').addEventListener('click',() => { const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = theme; try { localStorage.setItem('campuspulse-theme',theme); } catch {} });
try { const data = await api('status'); $('#status').textContent = `${data.source}. ${data.team_database_connected ? 'Хранилище подключено' : 'Учебная база не подключена'}. Vertex AI: ${data.vertex?.calls_enabled ? 'разрешён конфигурацией' : 'выключен'}.`; } catch(error) { showError(error); }
try { const data = await api('me'); signedIn(data.user); } catch(error) { if (error.status !== 401) showError(error); }
