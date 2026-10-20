'use strict';
window.addEventListener('error', event => console.error(`Interface error at app.js:${event.lineno}`));
const $ = selector => document.querySelector(selector);
const STORAGE = 'campuspulse.v1';
const ZONE = 'Asia/Qyzylorda';
const dateOnly = date => new Intl.DateTimeFormat('sv-SE', { timeZone: ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
const localStamp = date => `${dateOnly(date)}T${new Intl.DateTimeFormat('en-GB', { timeZone: ZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date)}`;
const clock = date => new Intl.DateTimeFormat('ru-RU', { timeZone: ZONE, hour: '2-digit', minute: '2-digit' }).format(new Date(date));
const dueLabel = date => date ? new Intl.DateTimeFormat('ru-RU', { timeZone: ZONE, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(date)) : 'Без дедлайна';
let state = { tasks: [], hours_per_day: 3, repository: '', busy: [] };
try { const saved = JSON.parse(localStorage.getItem(STORAGE) || 'null'); if (saved && Array.isArray(saved.tasks)) state = { ...state, ...saved }; } catch { /* Recover from unavailable/corrupted browser storage. */ }
let notes = [], plan = null, working = false, toastTimer;
let connectionStatus = { mode: 'local', gemini_connected: false };
function make(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
function toast(text) { clearTimeout(toastTimer); $('#toast').textContent = text; $('#toast').hidden = false; toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 6000); }
function persist() { try { localStorage.setItem(STORAGE, JSON.stringify(state)); } catch { toast('Браузер не смог сохранить данные. Экспортируй задания перед закрытием.'); } }
function invalidate() { plan = null; render(); }
function context() { return { ...state, notes }; }
async function api(path, body) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 110000);
  try {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Сервер не смог выполнить запрос.');
    return result;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Время ожидания истекло. Проверь локальный сервер.');
    throw error;
  } finally { clearTimeout(timer); }
}
function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], { type })), link = make('a');
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function showView(view) {
  const copy = { week: ['Неделя под контролем', 'Собери дедлайны. Найди время на главное.', 'НЕДЕЛЯ'], tasks: ['Каждое задание на своём месте', 'Твои сроки и оценки времени — основа реалистичного плана.', 'ЗАДАНИЯ'], notes: ['Материалы под рукой', 'Находи нужные фрагменты в собственных конспектах.', 'МАТЕРИАЛЫ'] };
  if (!copy[view]) return;
  document.querySelectorAll('.view').forEach(el => { el.hidden = el.id !== `${view}-view`; });
  document.querySelectorAll('.nav').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('#page-title').replaceChildren(document.createTextNode(copy[view][0]), make('span', '', '.'));
  $('#page-subtitle').textContent = copy[view][1]; $('#breadcrumb').textContent = copy[view][2];
}
function taskRow(task, compact = false) {
  const row = make('div', 'task-row'), check = document.createElement('input');
  check.type = 'checkbox'; check.checked = !!task.done; check.setAttribute('aria-label', `Выполнено: ${task.title}`);
  check.addEventListener('change', () => { task.done = check.checked; persist(); invalidate(); });
  const info = make('div', `task-info${task.done ? ' done' : ''}`);
  info.append(make('strong', '', task.title), make('small', '', `${task.course} · ${task.minutes} мин${task.demo ? ' · учебный пример' : ''}`));
  const deadline = make('span', `task-date${task.due && new Date(task.due) < new Date() && !task.done ? ' overdue' : ''}`, dueLabel(task.due));
  row.append(check, info, deadline);
  if (!compact) {
    const edit = make('button', 'icon-button', '✎'); edit.setAttribute('aria-label', `Изменить ${task.title}`); edit.addEventListener('click', () => openTask(task));
    const remove = make('button', 'icon-button', '×'); remove.setAttribute('aria-label', `Удалить ${task.title}`); remove.addEventListener('click', () => { state.tasks = state.tasks.filter(t => t.id !== task.id); persist(); invalidate(); });
    row.append(edit, remove);
  }
  return row;
}
function render() {
  const active = state.tasks.filter(task => !task.done), count = active.length;
  $('#nav-count').textContent = count; $('#stat-tasks').textContent = count;
  $('#stat-hours').textContent = plan ? (plan.scheduled_minutes / 60).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '—';
  $('#stat-risks').textContent = plan ? plan.risks.length + plan.unscheduled.length : '—';
  $('#plan-empty').hidden = !!plan?.blocks.length; $('#export-calendar').disabled = !plan?.blocks.length;
  $('#plan-empty h3').textContent = plan && count ? 'Нужны уточнения' : 'У недели ещё нет плана';
  $('#plan-empty p').textContent = plan && count ? 'Посмотри предупреждения ниже: возможно, срок уже прошёл или не хватает доступного времени.' : 'Добавь задания с дедлайнами, а затем рассчитай нагрузку с учётом доступного времени.';
  $('#calendar').replaceChildren();
  const now = new Date(), first = new Date(`${dateOnly(now)}T12:00:00+05:00`);
  const days = Array.from({ length: 7 }, (_, i) => new Date(first.getTime() + i * 86400000));
  $('#week-range').textContent = `${dueLabel(days[0]).split(',')[0]} — ${dueLabel(days[6]).split(',')[0]} · UTC+5`;
  for (const day of days) {
    const key = dateOnly(day), column = make('div', `day${key === dateOnly(now) ? ' is-today' : ''}`), heading = make('div', 'day-heading');
    heading.append(document.createTextNode(new Intl.DateTimeFormat('ru-RU', { timeZone: ZONE, weekday: 'short' }).format(day)), make('b', '', new Intl.DateTimeFormat('ru-RU', { timeZone: ZONE, day: 'numeric' }).format(day)));
    column.append(heading);
    for (const block of plan?.blocks || []) {
      if (block.start.slice(0, 10) !== key) continue;
      const item = make('div', 'study-block'); item.append(make('strong', '', `${clock(block.start)}–${clock(block.end)}`), document.createTextNode(block.title), make('span', '', `${block.minutes} мин`));
      item.title = `${block.course}: ${block.title}`; column.append(item);
    }
    $('#calendar').append(column);
  }
  $('#risks').replaceChildren();
  const issues = [...(plan?.risks || []), ...(plan?.unscheduled || [])];
  $('#risks-panel').hidden = !issues.length;
  for (const issue of issues) {
    const row = make('div', 'risk-row'); row.append(make('b', '', issue.title), make('div', '', `${issue.reason}${issue.remaining_minutes ? ` · осталось ${issue.remaining_minutes} мин` : ''}`)); $('#risks').append(row);
  }
  const sorted = [...active].sort((a, b) => (a.due ? new Date(a.due).getTime() : Infinity) - (b.due ? new Date(b.due).getTime() : Infinity));
  $('#upcoming-list').replaceChildren(...sorted.slice(0, 4).map(t => taskRow(t, true)));
  if (!sorted.length) $('#upcoming-list').append(make('div', 'empty-list', 'Пока нет открытых заданий. Добавь первое — начнём с него.'));
  $('#task-list').replaceChildren(...[...sorted, ...state.tasks.filter(t => t.done)].map(t => taskRow(t)));
  if (!state.tasks.length) $('#task-list').append(make('div', 'empty-list', 'Задания ещё не добавлены. Можно внести их вручную или импортировать JSON.'));
}
function renderNotes() {
  $('#notes-list').replaceChildren();
  notes.forEach((note, i) => {
    const row = make('div', 'note-row'), label = make('div', '', note.name), remove = make('button', 'icon-button', '×');
    label.append(make('small', '', `${note.text.length.toLocaleString('ru-RU')} символов${note.truncated ? ' · текст сокращён до 50 000 символов' : ''}`));
    remove.setAttribute('aria-label', `Удалить материал ${note.name}`); remove.addEventListener('click', () => { notes.splice(i, 1); renderNotes(); }); row.append(label, remove); $('#notes-list').append(row);
  });
}
function openTask(task) {
  const form = $('#task-form'); form.reset();
  $('#task-dialog-title').textContent = task ? 'Изменить задание' : 'Новое задание';
  form.elements.task_id.value = task?.id || ''; form.elements.title.value = task?.title || ''; form.elements.course.value = task?.course || '';
  form.elements.minutes.value = task?.minutes || 120;
  form.elements.due.value = task?.due ? localStamp(new Date(task.due)) : `${dateOnly(new Date(Date.now() + 2 * 86400000))}T23:59`;
  $('#task-dialog').showModal();
}
async function ask(message, requestedMode = connectionStatus.mode) {
  if (working) return;
  working = true; $('#send-button').disabled = true; $('#plan-button').disabled = true; $('#connection').textContent = 'Выполняю инструменты…';
  const user = make('div', 'user-message', message); $('#messages').append(user);
  const reply = make('div', 'answer-message'), text = make('p', 'answer-text', 'Проверяю данные…'); reply.append(make('span', 'small-label', 'CAMPUSPULSE'), text); $('#messages').append(reply);
  while ($('#messages').children.length > 12) $('#messages').firstChild.remove();
  $('#chat-scroll').scrollTop = $('#chat-scroll').scrollHeight;
  try {
    const result = await api('/api/query', { message, context: context(), mode: requestedMode });
    text.textContent = result.answer;
    reply.prepend(make('small', 'response-provider', result.mode === 'developer' ? `Gemini · ${result.model}` : 'Локальный алгоритм · без модели'));
    if (result.plan) { plan = result.plan; render(); }
    $('#trace').replaceChildren(); $('#trace-section').hidden = !result.trace.length; $('#trace-count').textContent = `${result.trace.length} вызова`;
    for (const item of result.trace) {
      const details = make('details', `trace-item ${item.status}`), summary = make('summary', '', `${item.status === 'ok' ? '✓' : '!'} ${item.tool}()`);
      details.append(summary, make('small', '', `${item.transport === 'mcp' ? 'MCP · stdio' : 'Прямой вызов'} · ${item.duration_ms} мс\n${item.summary}`), make('pre', '', JSON.stringify({ arguments: item.arguments, result: item.result || item.summary }, null, 2)));
      $('#trace').append(details);
    }
    $('#source-results').replaceChildren();
    if (result.github) {
      const warning = make('div', 'source-card', result.github.warning); $('#source-results').append(warning);
      for (const task of result.github.tasks) {
        const card = make('div', 'source-card'), link = make('a', '', task.title);
        if (task.url?.startsWith('https://github.com/')) { link.href = task.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
        card.append(link, make('small', '', `${dueLabel(task.due)} · оценка 60 мин (предположение)`)); $('#source-results').append(card);
      }
    }
    for (const match of result.materials?.matches || []) {
      const card = make('div', 'source-card'); card.append(make('strong', '', match.filename), make('blockquote', '', match.excerpt)); $('#source-results').append(card);
    }
  } catch (error) { text.textContent = error.message; text.classList.add('error'); toast(error.message); }
  finally { working = false; $('#send-button').disabled = false; $('#plan-button').disabled = false; renderConnection(connectionStatus); }
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(`#${button.dataset.close}`).close()));
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => ask(button.dataset.prompt)));
$('#task-open').addEventListener('click', () => openTask());
$('#task-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget, previous = state.tasks.find(t => t.id === form.elements.task_id.value);
  if (!previous && state.tasks.length >= 100) { toast('Допускается до 100 задач.'); return; }
  const task = { id: previous?.id || crypto.randomUUID(), title: form.elements.title.value.trim(), course: form.elements.course.value.trim(), due: `${form.elements.due.value}:00+05:00`, minutes: Number(form.elements.minutes.value), done: previous?.done || false, demo: previous?.demo || false };
  if (previous) Object.assign(previous, task); else state.tasks.push(task);
  persist(); invalidate(); $('#task-dialog').close(); toast('Задание сохранено. План можно пересчитать.');
});
$('#settings-open').addEventListener('click', () => {
  const form = $('#settings-form'); form.elements.hours.value = state.hours_per_day; form.elements.repository.value = state.repository; form.elements.busy.value = JSON.stringify(state.busy, null, 2); $('#settings-dialog').showModal();
});
$('#settings-mobile').addEventListener('click', () => $('#settings-open').click());
$('#settings-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  try {
    const busy = JSON.parse(form.elements.busy.value || '[]');
    if (!Array.isArray(busy) || busy.length > 100 || busy.some(b => !b.start || !b.end || !/([+-]\d{2}:\d{2}|Z)$/.test(b.start) || !/([+-]\d{2}:\d{2}|Z)$/.test(b.end) || !Number.isFinite(Date.parse(b.start)) || !Number.isFinite(Date.parse(b.end)) || Date.parse(b.end) <= Date.parse(b.start))) throw new Error();
    state.hours_per_day = Number(form.elements.hours.value); state.repository = form.elements.repository.value.trim(); state.busy = busy; persist(); invalidate(); $('#settings-dialog').close(); toast('Настройки сохранены.');
  } catch { toast('Проверь JSON занятых интервалов: нужны start и end с часовым поясом, конец позже начала.'); }
});
$('#privacy-open').addEventListener('click', () => $('#privacy-dialog').showModal());
$('#clear-data').addEventListener('click', () => { if (confirm('Удалить задания, настройки и материалы из этого пространства?')) { state = { tasks: [], hours_per_day: 3, repository: '', busy: [] }; notes = []; persist(); invalidate(); renderNotes(); $('#messages').replaceChildren(); $('#trace-section').hidden = true; $('#source-results').replaceChildren(); $('#privacy-dialog').close(); toast('Локальные данные удалены.'); } });
$('#plan-button').addEventListener('click', () => ask('Составь план на неделю', 'local'));
$('#chat-form').addEventListener('submit', event => { event.preventDefault(); const message = $('#message').value.trim(); if (message) { $('#message').value = ''; ask(message); } });
$('#message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#chat-form').requestSubmit(); } });
$('#demo-button').addEventListener('click', () => {
  if (state.tasks.some(task => task.demo)) { toast('Учебные примеры уже добавлены.'); return; }
  if (state.tasks.length > 96) { toast('Недостаточно места для примеров.'); return; }
  const example = (title, course, days, minutes) => ({ id: crypto.randomUUID(), title, course, due: `${dateOnly(new Date(Date.now() + days * 86400000))}T20:00:00+05:00`, minutes, done: false, demo: true });
  state.tasks.push(example('Лабораторная: перегрузка функций', 'ДЕМО · C++', 1, 120), example('Практика по линейной алгебре', 'ДЕМО · Математика', 3, 150), example('Подготовка защиты проекта', 'ДЕМО · Хакатон', 5, 180), example('Просроченный отчёт', 'ДЕМО · Пример риска', -1, 60));
  persist(); invalidate(); toast('Добавлены учебные примеры, а не реальные задания.'); ask('Составь план на неделю');
});
$('#export-tasks').addEventListener('click', () => download('campuspulse-tasks.json', JSON.stringify({ tasks: state.tasks, hours_per_day: state.hours_per_day, busy: state.busy, repository: state.repository }, null, 2), 'application/json'));
$('#import-tasks').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 500000) throw new Error('JSON должен быть меньше 500 КБ.');
    const data = JSON.parse(await file.text()), tasks = Array.isArray(data) ? data : data.tasks;
    if (!Array.isArray(tasks) || tasks.length + state.tasks.length > 100) throw new Error('Ожидается массив tasks; суммарно до 100 заданий.');
    const imported = tasks.map(t => {
      if (typeof t.title !== 'string' || !t.title.trim() || t.title.length > 200 || !Number.isFinite(t.minutes) || t.minutes < 10 || t.minutes > 2400 || (t.due && (!Number.isFinite(Date.parse(t.due)) || !/([+-]\d{2}:\d{2}|Z)$/.test(t.due)))) throw new Error('Проверь title, minutes (10–2400) и due (ISO с часовым поясом).');
      return { id: crypto.randomUUID(), title: t.title.trim(), course: String(t.course || 'Импорт').slice(0, 80), minutes: Math.floor(t.minutes), due: t.due || null, done: t.done === true, demo: t.demo === true };
    });
    state.tasks.push(...imported); persist(); invalidate(); toast(`Импортировано заданий: ${imported.length}. Настройки не заменены.`);
  } catch (error) { toast(error.message); } finally { event.target.value = ''; }
});
$('#upload-note').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (notes.length >= 5) throw new Error('Можно добавить до пяти материалов.');
    if (file.size > 5000000) throw new Error('Файл должен быть меньше 5 МБ.');
    toast('Извлекаю текст локально…');
    const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); });
    const note = await api('/api/extract', { name: file.name, data }); notes.push(note); renderNotes(); toast('Материал добавлен. Введи в чат: «Найди в материалах: ключевое слово».');
  } catch (error) { toast(error.message || 'Не удалось прочитать файл.'); } finally { event.target.value = ''; }
});
$('#export-calendar').addEventListener('click', () => {
  if (!plan?.blocks.length) return;
  const escape = value => String(value).replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;');
  const stamp = value => new Date(value).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CampusPulse//Student Planner//RU', 'CALSCALE:GREGORIAN'];
  for (const block of plan.blocks) lines.push('BEGIN:VEVENT', `UID:${crypto.randomUUID()}@campuspulse.local`, `DTSTAMP:${stamp(new Date())}`, `DTSTART:${stamp(block.start)}`, `DTEND:${stamp(block.end)}`, `SUMMARY:${escape(block.title)}`, `DESCRIPTION:${escape(block.course + ' · План CampusPulse, не официальный дедлайн')}`, 'END:VEVENT');
  lines.push('END:VCALENDAR');
  // Fold by UTF-8 octets, preserving code points (RFC 5545, 75-octet limit).
  const folded = lines.map(line => { let current = '', size = 0, output = []; for (const char of line) { const n = new TextEncoder().encode(char).length; if (size + n > 75) { output.push(current); current = ' '; size = 1; } current += char; size += n; } output.push(current); return output.join('\r\n'); });
  download('campuspulse-week.ics', folded.join('\r\n') + '\r\n', 'text/calendar;charset=utf-8'); toast('Файл скачан. Импорт в календарь выполняется вручную.');
});
$('#today-label').textContent = new Intl.DateTimeFormat('ru-RU', { timeZone: ZONE, day: 'numeric', month: 'long', year: 'numeric' }).format(new Date());
render(); renderNotes();
function renderConnection(status) {
  connectionStatus = status;
  const live = status.gemini_connected;
  $('#connection').textContent = live ? 'Gemini + MCP подключены' : 'Локальные инструменты доступны';
  $('#mode-label').textContent = live ? 'Gemini Developer API · биллинг проекта отключён' : 'Локальный режим · подключи ключ для ответов Gemini';
  $('#assistant-mode').textContent = live ? 'Gemini · MCP-инструменты' : 'Без модели · локальные инструменты';
  $('#composer-caption').textContent = live ? 'Gemini · бесплатная квота' : 'Gemini ещё не подключён';
  $('#gemini-open').textContent = live ? 'Настройки Gemini ↗' : 'Подключить Gemini ↗';
  $('#gemini-status').textContent = live ? `Ключ подключён. Проект: ${status.key_project}. Биллинг проверен и отключён; доступность модели подтвердится первым запросом.` : 'Ключ не подключён. Локальные инструменты работают без модели.';
  $('#gemini-disconnect').hidden = !live;
  $('#gemini-key').required = !live;
}
$('#gemini-open').addEventListener('click', () => { renderConnection(connectionStatus); $('#gemini-dialog').showModal(); });
$('#gemini-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (working) { toast('Дождись завершения запроса помощника.'); return; }
  const input = $('#gemini-key'), button = $('#gemini-connect');
  button.disabled = true; $('#gemini-status').textContent = 'Проверяю проект ключа и отключённый биллинг…';
  try {
    const status = await api('/api/gemini/connect', { api_key: input.value.trim() });
    renderConnection(status); toast('Ключ подключён. Отправь запрос помощнику для проверки Gemini.');
  } catch (error) {
    renderConnection({ ...connectionStatus, mode: 'local', gemini_connected: false });
    $('#gemini-status').textContent = error.message;
  } finally { input.value = ''; button.disabled = false; }
});
$('#gemini-disconnect').addEventListener('click', async () => {
  if (working) { toast('Дождись завершения запроса помощника.'); return; }
  try { renderConnection(await api('/api/gemini/disconnect', {})); $('#gemini-key').value = ''; toast('Ключ удалён из памяти. Gemini отключён.'); }
  catch (error) { toast(error.message); }
});
$('#gemini-dialog').addEventListener('close', () => { $('#gemini-key').value = ''; });
fetch('/api/status').then(response => { if (!response.ok) throw new Error(); return response.json(); }).then(status => {
  renderConnection(status);
  if (!status.mcp_available) toast('Библиотека MCP не установлена: используются прямые инструменты. Установи requirements.txt.');
}).catch(() => { $('#connection').textContent = 'Нет связи с локальным сервером'; toast('Не удалось подключиться к серверу. Перезапусти приложение.'); });
