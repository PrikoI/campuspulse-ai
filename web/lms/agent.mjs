import {queryAgent} from './api.mjs';
import {showError,element} from './ui.mjs';
const toolNames = {get_courses:'Предметы и зачисления',get_assignments:'Задания и дедлайны',get_schedule:'Расписание',plan_study:'Расчёт свободного времени',prepare_study_plan:'Подготовка плана к сохранению',get_personal_data:'Личные задачи',get_grades:'Оценки и расчёт баллов',read_materials:'Поиск в материалах',get_attendance:'Посещаемость',query_data:'Запрос данных',list_data_resources:'Каталог данных',prepare_personal_change:'Подготовка изменения'};
export function bindAgent(context, review) {
  let active, version = 0;
  const agent = document.querySelector('#agent');
  agent.addEventListener('submit',async event => {
    event.preventDefault(); const current = ++version; active?.abort(); active = new AbortController();
    const form = event.currentTarget, data = new FormData(form), button = form.querySelector('button');
    const trace = document.querySelector('#trace'), answer = document.querySelector('#answer'); trace.textContent = ''; answer.textContent = ''; button.disabled = true;
    const activity = document.querySelector('#activity'), progress = document.querySelector('#agent-progress'), output = document.querySelector('#agent-results');
    activity?.replaceChildren(); output?.replaceChildren(); if (progress) progress.hidden = false;
    const running = new Map();
    try {
      const result = await queryAgent({...context(),message:data.get('message'),engine:data.get('engine')},item => {
        if (current !== version) return;
        if (activity && ['mcp_ready','model_start','tool_start','tool_result','remote_start'].includes(item.type)) {
          if (item.type === 'tool_result' && running.has(item.tool)) {
            const node = running.get(item.tool); node.classList.add(item.status === 'error' ? 'is-error':'is-complete');
            node.textContent = `${item.status === 'error' ? 'Ошибка' : 'Готово'} · ${toolNames[item.tool] || item.tool}${item.duration_ms!==undefined ? ' · '+item.duration_ms+' мс' : ''}`;
          } else if (item.type !== 'tool_result') {
            const text = item.type === 'tool_start' ? `Проверяю: ${toolNames[item.tool] || item.tool}` : item.type === 'model_start' ? `${item.model || 'Модель'} выбирает следующий шаг · ${item.step}` : item.type === 'remote_start' ? 'Запрос в Agent Engine' : 'MCP подключён · инструменты доступны';
            const node = element('div',text,activity); node.className='activity-step';
            if (item.tool) running.set(item.tool,node);
          }
        }
        if (item.type !== 'complete') { const visible = {...item}; if (visible.result) { const {proposal,...rest} = visible.result; visible.result = rest; } trace.textContent += JSON.stringify(visible,null,2) + '\n'; }
      },active.signal);
      if (current !== version) return;
      answer.textContent = result.answer;
      const proposal = result.results?.prepare_study_plan || result.results?.prepare_personal_change; if (proposal?.proposal) review(proposal);
      if (output) {
        const plan = result.results?.prepare_study_plan?.plan || result.results?.plan_study?.plan;
        if (plan) {
          element('h3',`План · ${plan.scheduled_minutes} минут подготовки`,output);
          for (const block of plan.blocks) { const row=element('div',undefined,output); row.className='plan-block'; element('strong',new Date(block.start).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}),row); element('span',`${block.course} · ${block.title} · ${block.minutes} мин`,row); }
          for (const risk of [...(plan.risks||[]),...(plan.unscheduled||[])]) element('p',`${risk.title}: ${risk.reason}`,output).className='plan-risk';
        }
        const assignments=result.results?.get_assignments?.assignments;
        if (assignments) for (const task of [...assignments].sort((a,b)=>(a.due||'z').localeCompare(b.due||'z'))) {
          const row=element('div',undefined,output);row.className='plan-block';element('strong',task.title,row);element('span',task.due ? new Date(task.due).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda'}) : 'Дедлайн не указан',row);
        }
        for (const lesson of result.results?.get_schedule?.lessons||[]) { const row=element('div',undefined,output);row.className='plan-block';element('strong',new Date(lesson.starts_at).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda'}),row);element('span',lesson.title,row); }
        if (result.source) element('p',`Источник: ${result.source} · ${result.deployment || result.provider} · ${result.transport}`,output).className='schedule-muted';
      }
    } catch(error) { if (current === version && error.name !== 'AbortError') showError(error); } finally { if (current === version) { button.disabled = false; if (progress) progress.hidden=true; } }
  });
  return () => { version++; active?.abort(); active = null; agent.querySelector('button').disabled = false; const progress=document.querySelector('#agent-progress'); if(progress)progress.hidden=true; document.querySelector('#activity')?.replaceChildren(); document.querySelector('#agent-results')?.replaceChildren(); };
}
