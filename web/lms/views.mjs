import {api} from './api.mjs';
import {element,safeURL,showError} from './ui.mjs';

export const names={courses:'Дисциплины',assignments:'Задания',materials:'Материалы',grade_items:'Работы',grades:'Оценки',lessons:'Занятия',attendance:'Посещаемость',enrollments:'Зачисления',users:'Студенты',personal_data:'Личные задачи'};
export const components={regmid:'Текущие работы · 1-я аттестация',midterm:'Midterm',regend:'Текущие работы · 2-я аттестация',endterm:'Endterm',attestation1:'1-я аттестация',attestation2:'2-я аттестация',final:'Финальный экзамен'};
export const statuses={present:'Присутствовал',absent:'Отсутствовал',late:'Опоздал',excused:'Уважительная причина'};
export const dateText=(value,time=true)=>value&&Number.isFinite(new Date(value).getTime())?new Date(value).toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda',day:'numeric',month:'long',...(time?{hour:'2-digit',minute:'2-digit'}:{})}):'Без даты';
export const numberText=value=>value===null||value===undefined?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value);

export function empty(parent,title,description='') {
  const node=element('div',undefined,parent);node.className='empty-state';
  element('span','○',node).className='empty-symbol';element('h3',title,node);if(description)element('p',description,node);
}
export function badge(parent,text,variant='neutral') {const node=element('span',text,parent);node.className='status-badge '+variant;return node;}
export function intro(parent,text){element('p',text,parent).className='view-intro';}
export function metrics(parent,values){const grid=element('div',undefined,parent);grid.className='metric-grid';for(const [label,value,note] of values){const card=element('div',undefined,grid);card.className='metric-card';element('span',label,card);element('strong',value,card);if(note)element('small',note,card);}}
export function table(parent,columns,rows){
  const wrap=element('div',undefined,parent);wrap.className='friendly-table';const node=element('table',undefined,wrap);
  const head=element('tr',undefined,element('thead',undefined,node));for(const column of columns)element('th',column.label,head).scope='col';
  const body=element('tbody',undefined,node);for(const row of rows){const tr=element('tr',undefined,body);for(const column of columns){const cell=element('td',undefined,tr);const value=column.value(row);if(typeof value==='function')value(cell);else cell.textContent=value??'—';}}
  return node;
}
export function courseCards(parent,rows,open){
  rows=rows.filter(row=>!row.archived);intro(parent,'Все ваши предметы в одном месте. Откройте задания, оценки или расписание нужной дисциплины.');
  const grid=element('div',undefined,parent);grid.className='course-grid';const cards=new Map();
  if(!rows.length){empty(grid,'Пока нет дисциплин','После зачисления здесь появятся ваши предметы.');return cards;}
  rows.forEach((row,index)=>{
    const card=element('article',undefined,grid);card.className='course-card';card.dataset.tone=String(index%6);
    const header=element('div',undefined,card);header.className='course-card-header';element('span',row.name.split(/\s+/).filter(Boolean).slice(0,2).map(word=>word[0]).join('').toUpperCase(),header).className='course-monogram';badge(header,'Активная','positive');
    element('h2',row.name,card);
    const teachers=row.instructor_ids?.length;if(teachers)element('p',`Преподавателей: ${teachers}`,card).className='card-caption';
    const policy=row.policy;
    if(policy&&[policy.attestation1_weight,policy.attestation2_weight,policy.final_weight].every(value=>typeof value==='number')){
      const rules=element('details',undefined,card);rules.className='course-rules';element('summary','Как считается итог',rules);
      element('p',`1-я аттестация — ${numberText(policy.attestation1_weight*100)}%, 2-я — ${numberText(policy.attestation2_weight*100)}%, финальный экзамен — ${numberText(policy.final_weight*100)}%.`,rules);
      if(safeURL(policy.source_url)){const link=element('a','Правила оценивания',rules);link.href=safeURL(policy.source_url);link.target='_blank';link.rel='noopener noreferrer';}
    }
    const actions=element('div',undefined,card);actions.className='course-actions';
    if(open)for(const [page,label] of [['assignments','Задания'],['grades','Оценки'],['schedule','Расписание']]){const button=element('button',label,actions);button.type='button';button.addEventListener('click',()=>open(page,row.id));}
    const management=element('div',undefined,card);management.className='course-management';cards.set(row.id,management);
  });return cards;
}
export function students(parent,rows){
  intro(parent,'Выберите ученика в разделе «Зачисление», чтобы добавить его на дисциплину.');
  if(!rows.length){empty(parent,'Список студентов пуст');return;}
  const grid=element('div',undefined,parent);grid.className='student-grid';
  for(const row of rows){const card=element('article',undefined,grid);card.className='student-card';element('span',(row.name||'С')[0].toUpperCase(),card).className='student-avatar';const copy=element('div',undefined,card);element('h3',row.name||'Студент',copy);element('p',`Логин: ${row.id}`,copy);badge(card,'Студент');}
}
export function gradeSummary(parent,data){
  const calc=data.calculation||{};
  metrics(parent,[['Рейтинг допуска',numberText(calc.register),'По двум аттестациям'],['Итоговая оценка',calc.grade||numberText(calc.total),calc.total==null?'Пока недостаточно оценок':`${numberText(calc.total)} из 100`],['Нужно на финальном',numberText(calc.required_final),`Для итога ${numberText(calc.target_total??50)}`]]);
  intro(parent,'Невыставленные оценки не считаются нулями. Итог появится, когда будут известны необходимые компоненты.');
  const rows=data.items||[];if(!rows.length){empty(parent,'Работ пока нет','Преподаватель ещё не добавил оцениваемые работы.');return;}
  table(parent,[{label:'Работа',value:row=>row.title},{label:'Тип',value:row=>components[row.component]||'Работа'},{label:'Балл',value:row=>cell=>{
    const line=element('strong',row.score==null?'—':`${numberText(row.score)} / ${numberText(row.max_score??100)}`,cell);
    if(row.score!=null){const meter=element('progress',undefined,cell);meter.max=row.max_score??100;meter.value=row.score;meter.setAttribute('aria-label',`Балл за ${row.title}`);}
  }},{label:'Статус',value:row=>cell=>badge(cell,row.score==null?'Не выставлена':'Оценено',row.score==null?'neutral':'positive')},{label:'Комментарий',value:row=>row.comment||'—'}],rows);
  for(const warning of calc.warnings||[])element('p',warning,parent).className='notice-text';
  for(const reason of calc.admission_reasons||[])element('p',reason,parent).className='notice-text';
}
export function attendanceSummary(parent,data){
  const summary=data.summary||{};
  metrics(parent,[['Посещаемость',summary.attendance_percent==null?'—':numberText(summary.attendance_percent)+'%','По отмеченным занятиям'],['Посещено',numberText((summary.present||0)+(summary.late||0)),'Включая опоздания'],['Пропуски',numberText(summary.absent||0),'Только подтверждённые отметки'],['Без отметки',numberText(summary.unmarked||0),'Не считаются пропусками']]);
  const records=new Map((data.records||[]).map(row=>[row.lesson_id,row]));const lessons=[...(data.lessons||[])].sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
  if(!lessons.length){empty(parent,'Занятий пока нет');return;}
  table(parent,[{label:'Дата',value:row=>dateText(row.starts_at,false)},{label:'Занятие',value:row=>row.title},{label:'Время',value:row=>new Date(row.starts_at).toLocaleTimeString('ru-RU',{timeZone:'Asia/Qyzylorda',hour:'2-digit',minute:'2-digit'})},{label:'Отметка',value:row=>cell=>{const status=records.get(row.id)?.status;badge(cell,statuses[status]||(new Date(row.ends_at)>Date.now()?'Предстоит':'Не отмечено'),status==='absent'?'negative':status==='present'?'positive':'neutral');}}],lessons);
}
export function materials(parent,rows,courseNames){
  if(!rows.length){empty(parent,'Материалы пока не добавлены','Здесь появятся конспекты, лекции и ссылки преподавателя.');return;}
  const grid=element('div',undefined,parent);grid.className='material-grid';
  for(const row of rows){const card=element('article',undefined,grid);card.className='material-card';element('p',courseNames.get(row.course_id)||'Учебный материал',card).className='eyebrow';element('h3',row.name,card);if(row.week)badge(card,`${row.week}-я неделя`);if(row.text){element('p',row.text.slice(0,180)+(row.text.length>180?'…':''),card).className='material-excerpt';if(row.text.length>180){const details=element('details',undefined,card);element('summary','Читать полностью',details);element('p',row.text,details).className='material-text';}}if(safeURL(row.source_url)){const link=element('a','Открыть источник ↗',card);link.href=safeURL(row.source_url);link.target='_blank';link.rel='noopener noreferrer';}}
}
export function workItems(parent,rows,courseNames){
  if(!rows.length){empty(parent,'Оцениваемых работ пока нет');return;}
  table(parent,[{label:'Работа',value:row=>row.title},{label:'Дисциплина',value:row=>courseNames.get(row.course_id)||'Дисциплина'},{label:'Компонент оценки',value:row=>components[row.component]||'Работа'},{label:'Максимум',value:row=>numberText(row.max_score??100)+' баллов'},{label:'Неделя',value:row=>row.week?`${row.week}-я`:'—'}],rows);
}
export function personalTasks(parent,data,prepare){
  const tasks=data.tasks||[];metrics(parent,[['В работе',String(tasks.filter(row=>!row.done).length),'Личные задачи'],['Завершено',String(tasks.filter(row=>row.done).length),'Сохранённый прогресс']]);
  if(!tasks.length)empty(parent,'Добавьте первую задачу','Или попросите помощника составить план подготовки.');
  const list=element('div',undefined,parent);list.className='personal-list';
  for(const row of tasks){
    const card=element('article',undefined,list);card.className='personal-task'+(row.done?' is-done':'');
    const copy=element('div',undefined,card);element('h3',row.title,copy);element('p',[row.course,dateText(row.due),row.minutes?`${row.minutes} мин`:null].filter(Boolean).join(' · '),copy);
    const actions=element('div',undefined,card);actions.className='task-actions';
    const done=element('button',row.done?'Вернуть в работу':'Завершить',actions);done.type='button';done.addEventListener('click',()=>prepare({target:'task',record_id:row.id,payload:{done:!row.done}}).catch(showError));
    const remove=element('button','Удалить',actions);remove.type='button';remove.className='text-button danger';remove.addEventListener('click',()=>prepare({target:'task',operation:'delete',record_id:row.id,payload:{}}).catch(showError));
    const details=element('details',undefined,card);details.className='task-edit';element('summary','Изменить задачу',details);
    const form=element('form',undefined,details);form.className='friendly-form';
    const title=element('input',undefined,element('label','Название',form));title.required=true;title.maxLength=200;title.value=row.title;
    const due=element('input',undefined,element('label','Сделать до · время Кызылорды',form));due.type='datetime-local';due.value=row.due?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Qyzylorda',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(row.due)).replace(' ','T'):'';
    const minutes=element('input',undefined,element('label','Подготовка, минут',form));minutes.type='number';minutes.min=10;minutes.max=2400;minutes.required=true;minutes.value=row.minutes||60;
    const save=element('button','Подготовить изменение',form);
    form.addEventListener('submit',async event=>{event.preventDefault();if(!form.reportValidity()||save.disabled)return;save.disabled=true;try{await prepare({target:'task',record_id:row.id,payload:{title:title.value.trim(),minutes:Number(minutes.value),due:due.value?due.value+':00+05:00':null}});}catch(error){showError(error);}finally{save.disabled=false;}});
  }
}
export function reviewChange(parent,change){
  parent.replaceChildren();
  if(change.target==='study_plan'){
    intro(parent,`Будет добавлено задач: ${change.tasks.length}. Проверьте список перед сохранением.`);
    table(parent,[{label:'Задача',value:row=>row.title},{label:'Предмет',value:row=>row.course||'Личное'},{label:'До',value:row=>dateText(row.due)},{label:'Время',value:row=>`${row.minutes} мин`}],change.tasks);return;
  }
  const after=change.after;
  if(change.target==='preferences'){element('p',`Нагрузка: ${change.before?.hours_per_day??3} → ${after.hours_per_day} ч в день.`,parent);return;}
  if(change.operation==='delete'){element('p',`Удалить задачу «${change.before?.title||'Задача'}»?`,parent);return;}
  element('h3',after?.title||change.before?.title||'Новая задача',parent);
  for(const [label,value] of [['Предмет',after?.course||'Личное'],['Дедлайн',dateText(after?.due)],['Подготовка',`${after?.minutes??60} мин`],['Статус',after?.done?'Завершено':'В работе']]){const line=element('p',undefined,parent);element('strong',label+': ',line);element('span',value,line);}
}
