import {queryAgent} from './api.mjs';
import {element} from './ui.mjs';

const toolNames = {get_courses:'Предметы и зачисления',get_assignments:'Задания и дедлайны',get_schedule:'Расписание',plan_study:'Расчёт свободного времени',prepare_study_plan:'Подготовка плана к сохранению',get_personal_data:'Личные задачи',get_grades:'Оценки и расчёт баллов',read_materials:'Поиск в материалах',get_attendance:'Посещаемость',query_data:'Запрос данных',list_data_resources:'Каталог данных',prepare_personal_change:'Подготовка изменения'};

// Only successful text exchanges enter model context. Actions and signed proposals never do.
export function chatHistory(turns) {
  const pairs = [];
  let size = 0;
  for (const turn of [...turns].reverse()) {
    if (!turn.answer || turn.message.length > 8000 || turn.answer.length > 8000) continue;
    const length = turn.message.length + turn.answer.length;
    if (pairs.length === 4 || size + length > 20000) break;
    pairs.unshift([{role:'user',content:turn.message},{role:'assistant',content:turn.answer}]);
    size += length;
  }
  return pairs.flat();
}

function renderResults(output, result) {
  const plan = result.results?.prepare_study_plan?.plan || result.results?.plan_study?.plan;
  if (plan) {
    const details = element('details',undefined,output);
    element('summary',`План подготовки · ${plan.scheduled_minutes} мин`,details);
    for (const block of plan.blocks || []) {
      const row = element('div',undefined,details); row.className = 'plan-block';
      element('strong',new Date(block.start).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}),row);
      element('span',`${block.course} · ${block.title} · ${block.minutes} мин`,row);
    }
    for (const risk of [...(plan.risks||[]),...(plan.unscheduled||[])]) element('p',`${risk.title}: ${risk.reason}`,details).className = 'plan-risk';
  }
  const assignments = result.results?.get_assignments?.assignments;
  if (assignments?.length) {
    const details = element('details',undefined,output); element('summary',`Задания · ${assignments.length}`,details);
    for (const task of [...assignments].sort((a,b)=>(a.due||'z').localeCompare(b.due||'z'))) {
      const row = element('div',undefined,details); row.className = 'plan-block'; element('strong',task.title,row);
      element('span',task.due ? new Date(task.due).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda'}) : 'Дедлайн не указан',row);
    }
  }
  const lessons = result.results?.get_schedule?.lessons;
  if (lessons?.length) {
    const details = element('details',undefined,output); element('summary',`Занятия · ${lessons.length}`,details);
    for (const lesson of lessons) {
      const row = element('div',undefined,details); row.className = 'plan-block';
      element('strong',new Date(lesson.starts_at).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda'}),row); element('span',lesson.title,row);
    }
  }
}

export function bindAgent(context, review) {
  const $ = selector => document.querySelector(selector);
  const form = $('#agent'), feed = $('#chat-messages'), input = $('#chat-input');
  const send = $('#chat-send'), stop = $('#chat-stop'), newChat = $('#new-chat');
  let active = null, version = 0, turns = [], pending = null;

  const scroll = () => { feed.scrollTop = feed.scrollHeight; };
  const busy = value => {
    send.disabled = value; send.hidden = value; stop.hidden = !value;
    form.setAttribute('aria-busy',String(value));
  };
  const resize = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight || 52,150) + 'px'; };
  function welcome() {
    const intro = element('div',undefined,feed); intro.className = 'chat-welcome';
    element('span','✦',intro).className = 'chat-welcome-icon';
    element('strong','С чего начнём?',intro);
    element('p','Разберём дедлайны, оценки и планы на неделю.',intro);
    const prompts = element('div',undefined,intro); prompts.className = 'chat-suggestions';
    for (const text of ['Какие у меня ближайшие дедлайны?','Составь план подготовки на неделю','Покажи моё расписание']) {
      const button = element('button',text,prompts); button.type = 'button';
      button.addEventListener('click',() => { input.value = text; resize(); input.focus(); });
    }
  }
  function message(role, text) {
    const node = element('article',undefined,feed); node.className = `chat-message chat-${role}`;
    element('span',role === 'user' ? 'Вы' : 'CampusPulse',node).className = 'chat-author';
    const body = element('div',text,node); body.className = 'chat-text';
    scroll(); return {node,body};
  }
  function cancel() {
    version++; active?.abort(); active = null;
    if (pending) {
      pending.body.textContent = 'Ответ остановлен. Можно отправить новое сообщение.';
      pending.node.classList.remove('is-pending'); pending = null;
    }
    busy(false);
  }
  function reset() {
    cancel(); turns = []; feed.replaceChildren(); input.value = ''; resize(); welcome();
  }
  stop.addEventListener('click',() => { cancel(); input.focus(); });
  newChat.addEventListener('click',() => { reset(); input.focus(); });
  input.addEventListener('input',resize);
  input.addEventListener('keydown',event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); if (!active && input.value.trim()) form.requestSubmit();
    }
  });
  form.addEventListener('submit',async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (active || !text) return;
    const history = chatHistory(turns), current = ++version;
    const controller = new AbortController(); active = controller; busy(true);
    feed.querySelector('.chat-welcome')?.remove();
    message('user',text); input.value = ''; resize();
    const reply = message('assistant',''); pending = reply; reply.node.classList.add('is-pending');
    reply.body.setAttribute('role','status'); reply.body.setAttribute('aria-label','Помощник готовит ответ');
    const typing = element('span',undefined,reply.body); typing.className = 'chat-typing'; typing.setAttribute('aria-hidden','true');
    for (let i = 0; i < 3; i++) element('i',undefined,typing);
    element('span','Думаю…',reply.body).className = 'chat-thinking';
    const details = element('details',undefined,reply.node); details.className = 'chat-tools';
    element('summary','Действия инструментов',details);
    const activity = element('div',undefined,details); activity.className = 'agent-activity';
    const technical = element('details',undefined,details); element('summary','Технический журнал',technical);
    const trace = element('pre','',technical), running = new Map();
    let journalSize = 0;
    try {
      const result = await queryAgent({...context(),message:text,engine:form.querySelector('[name="engine"]').value,history},item => {
        if (current !== version) return;
        if (item.type === 'tool_result' && running.has(item.tool)) {
          const node = running.get(item.tool); node.classList.add(item.status === 'error' ? 'is-error' : 'is-complete');
          node.textContent = `${item.status === 'error' ? 'Ошибка' : 'Готово'} · ${toolNames[item.tool] || item.tool}`;
        } else if (['mcp_ready','model_start','tool_start','remote_start'].includes(item.type)) {
          const label = item.type === 'tool_start' ? `Проверяю: ${toolNames[item.tool] || item.tool}` : item.type === 'model_start' ? 'Готовлю ответ' : item.type === 'remote_start' ? 'Запрос в Agent Engine' : 'Подключено к учебным данным';
          const node = element('div',label,activity); node.className = 'activity-step';
          if (item.tool) running.set(item.tool,node);
          const status = reply.body.querySelector('.chat-thinking'); if (status) status.textContent = label + '…';
        }
        if (item.type !== 'complete' && journalSize < 24000) {
          const visible = {...item};
          if (visible.result) { const {proposal,...rest} = visible.result; visible.result = rest; }
          const line = JSON.stringify(visible,null,2) + '\n';
          if (journalSize + line.length <= 24000) trace.textContent += line;
          journalSize += line.length;
        }
      },controller.signal);
      if (current !== version) return;
      reply.body.replaceChildren(); reply.body.textContent = result.answer || 'Помощник не вернул текст ответа.';
      reply.body.removeAttribute('role'); reply.body.removeAttribute('aria-label');
      reply.node.classList.remove('is-pending');
      if (result.answer) turns.push({message:text,answer:result.answer});
      renderResults(reply.node,result);
      const proposal = result.results?.prepare_study_plan || result.results?.prepare_personal_change;
      if (proposal?.proposal) {
        const button = element('button','Проверить изменение',reply.node); button.type = 'button'; button.className = 'chat-review';
        button.addEventListener('click',() => review(proposal)); review(proposal);
      }
    } catch (error) {
      if (current !== version || error.name === 'AbortError') return;
      reply.body.replaceChildren(); reply.body.textContent = error.message || 'Не удалось получить ответ. Попробуйте ещё раз.';
      reply.node.classList.remove('is-pending'); reply.node.classList.add('is-error');
      reply.body.removeAttribute('aria-label'); reply.body.setAttribute('role','alert');
      const retry = element('button','Повторить вопрос',reply.node); retry.type = 'button'; retry.className = 'chat-retry secondary';
      retry.addEventListener('click',() => { if (!active) { input.value = text; resize(); input.focus(); } });
    } finally {
      if (current === version) { active = null; pending = null; busy(false); scroll(); input.focus(); }
    }
  });
  welcome();
  return reset;
}
