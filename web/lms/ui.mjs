export function safeURL(value) {
  try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
}
export const format = value => value === null || value === undefined ? '—' : typeof value === 'boolean' ? (value?'Да':'Нет') : Array.isArray(value) ? `${value.length} записей` : typeof value === 'object' ? 'Дополнительные сведения' : String(value);
export function element(tag, text, parent) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (parent) parent.append(node); return node; }
export function records(parent, rows) {
  if (!rows.length) { element('p','Записей нет.',parent); return; }
  const labels={name:'Название',title:'Название',code:'Код',description:'Описание',due:'Дедлайн',minutes:'Подготовка, минут',week:'Неделя',score:'Балл',max_score:'Максимум',weight:'Вес',component:'Компонент оценки',status:'Статус',comment:'Комментарий',starts_at:'Начало',ends_at:'Окончание',source_url:'Источник',text:'Материал',done:'Завершено',role:'Роль',kind:'Тип',label:'Название',fields:'Доступные поля',filterable:'Фильтры'};
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))].filter(key=>key!=='id'&&!key.endsWith('_id')&&!['policy','instructor_ids','archived','source','url','owner_id','record_id'].includes(key)), table = element('table',undefined,parent);
  const heading = element('tr',undefined,element('thead',undefined,table)); keys.forEach(key => element('th',labels[key]||key.replaceAll('_',' '),heading));
  const body = element('tbody',undefined,table);
  for (const row of rows) {
    const tr = element('tr',undefined,body);
    for (const key of keys) {
      const td = element('td',undefined,tr), value = row[key];
      if (key === 'source_url' && safeURL(value)) { const a = element('a','Источник',td); a.href = safeURL(value); a.target = '_blank'; a.rel = 'noopener noreferrer'; }
      else {
        const values={present:'Присутствовал',absent:'Отсутствовал',late:'Опоздал',excused:'Уважительная причина',regmid:'Текущие работы · 1-я аттестация',regend:'Текущие работы · 2-я аттестация',midterm:'Midterm',endterm:'Endterm',attestation1:'1-я аттестация',attestation2:'2-я аттестация',final:'Финальный экзамен',student:'Студент',admin:'Преподаватель',lecture:'Лекция',class:'Занятие'};
        const text=['due','starts_at','ends_at'].includes(key)&&value?new Date(value).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda'}):['role','status','component','kind'].includes(key)&&values[value]?values[value]:format(value);
        element('span',text,td);
      }
    }
  }
}
export function showError(error) {
  document.querySelector('#error').textContent = error.message;
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
