export function safeURL(value) {
  try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
}
export const format = value => value === null ? 'Неизвестно' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
export function element(tag, text, parent) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (parent) parent.append(node); return node; }
export function records(parent, rows) {
  if (!rows.length) { element('p','Записей нет.',parent); return; }
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))], table = element('table',undefined,parent);
  const heading = element('tr',undefined,element('thead',undefined,table)); keys.forEach(key => element('th',key,heading));
  const body = element('tbody',undefined,table);
  for (const row of rows) {
    const tr = element('tr',undefined,body);
    for (const key of keys) {
      const td = element('td',undefined,tr), value = row[key];
      if (key === 'source_url' && safeURL(value)) { const a = element('a','Источник',td); a.href = safeURL(value); a.target = '_blank'; a.rel = 'noopener noreferrer'; }
      else element(typeof value === 'object' ? 'pre' : 'span',value === undefined ? '—' : format(value),td);
    }
  }
}
export function showError(error) {
  document.querySelector('#error').textContent = error.message + (error.data_access?.length ? '\n' + JSON.stringify(error.data_access,null,2) : '');
}
export function studyPlan(parent, plan) {
  element('p',`${plan.scheduled_minutes} минут подготовки · ${plan.blocks.length} блоков · ${plan.risks.length} рисков`,parent).className='schedule-summary';
  for (const block of plan.blocks) {
    const line=element('div',undefined,parent);line.className='plan-block';
    element('strong',new Date(block.start).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}),line);
    element('span',`${block.course} · ${block.title} · ${block.minutes} мин`,line);
  }
  if (!plan.blocks.length) element('p','Нет доступных блоков. Проверьте дедлайны и оценку времени подготовки.',parent);
  if (plan.risks.length || plan.unscheduled.length) {
    const details=element('details',undefined,parent);element('summary','Риски и задания без подтверждённых данных',details);
    for(const risk of [...plan.risks,...plan.unscheduled])element('p',`${risk.title}: ${risk.reason}`,details).className='plan-risk';
  }
}
