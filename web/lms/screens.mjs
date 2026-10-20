import {api} from './api.mjs';
import {element,records,showError} from './ui.mjs';
import {assignmentCards} from './academics.mjs';
import {empty,intro,table,badge,names,components,statuses,dateText,materials,workItems} from './views.mjs';

const titles={assignments:'задание',grade_items:'работу',materials:'материал',attendance:'отметку'};
const inputTime=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Qyzylorda',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)).replace(' ','T'):'';

export async function editor(parent,kind,cid,courses,rows,active,reload){
  const panel=element('details',undefined,parent);panel.className='editor-panel';element('summary',`Добавить или изменить ${titles[kind]||'запись'}`,panel);
  const form=element('form',undefined,panel);form.className='friendly-form';const fields={};
  const selection=element('select',undefined,element('label','Запись',form));selection.append(new Option('Создать новую',''),...rows.map(row=>new Option(row.title||row.name||`${statuses[row.status]||'Отметка'} · ${dateText(row.starts_at,false)}`,row.id)));
  const field=(name,label,type='text',options=null)=>{
    const labelNode=element('label',label,form);const control=element(options?'select':type==='textarea'?'textarea':'input',undefined,labelNode);
    if(options)control.append(new Option('Выберите…',''),...options.map(([value,text])=>new Option(text,value)));else if(type!=='textarea')control.type=type;
    fields[name]=control;return control;
  };
  field('course_id','Дисциплина','text',courses.map(row=>[row.id,row.name])).required=true;
  if(kind==='assignments'){
    field('title','Название задания').required=true;fields.title.maxLength=200;
    field('description','Описание','textarea').maxLength=10000;
    field('due','Сдать до · время Кызылорды','datetime-local');
    const minutes=field('minutes','Время подготовки, минут · необязательно','number');minutes.min=10;minutes.max=2400;
  } else if(kind==='grade_items'){
    field('title','Название работы').required=true;fields.title.maxLength=200;
    field('component','Компонент оценки','text',Object.entries(components)).required=true;
    const max=field('max_score','Максимальный балл','number');max.required=true;max.min='.001';max.max='100000';max.step='any';
    const weight=field('weight','Вес работы внутри компонента','number');weight.min='.001';weight.max='1000';weight.step='any';weight.required=true;
    const week=field('week','Учебная неделя · необязательно','number');week.min=1;week.max=100;
  } else if(kind==='materials'){
    field('name','Название материала').required=true;fields.name.maxLength=200;
    field('text','Текст материала','textarea').required=true;fields.text.maxLength=50000;
    field('source_url','Ссылка на источник · необязательно','url');
  } else if(kind==='attendance'){
    field('student_id','Студент','text',[]).required=true;field('lesson_id','Занятие','text',[]).required=true;
    field('status','Посещаемость','text',Object.entries(statuses)).required=true;
  }
  const submit=element('button',`Добавить ${titles[kind]}`,form);submit.type='submit';
  const users=kind==='attendance'?(await api('admin/users')).items:[];if(!active())return;
  let relatedVersion=0;
  async function related(row=null){
    if(kind!=='attendance')return;const version=++relatedVersion;submit.disabled=true;
    if(!fields.course_id.value){for(const key of ['student_id','lesson_id'])fields[key].replaceChildren(new Option('Сначала выберите предмет',''));return;}
    try{
      const enrollments=(await api('admin/enrollments?course_id='+encodeURIComponent(fields.course_id.value))).items;if(!active()||version!==relatedVersion)return;
      const lessons=(await api('admin/lessons?course_id='+encodeURIComponent(fields.course_id.value))).items;if(!active()||version!==relatedVersion)return;
      const allowed=new Set(enrollments.filter(row=>!row.archived).map(row=>row.student_id));
      fields.student_id.replaceChildren(new Option('Выберите студента',''),...users.filter(user=>allowed.has(user.id)).map(user=>new Option(user.name||'Студент',user.id)));
      fields.lesson_id.replaceChildren(new Option('Выберите занятие',''),...lessons.sort((a,b)=>a.starts_at.localeCompare(b.starts_at)).map(lesson=>new Option(`${dateText(lesson.starts_at)} · ${lesson.title}`,lesson.id)));
      if(row){fields.student_id.value=row.student_id;fields.lesson_id.value=row.lesson_id;}
    }catch(error){if(active())showError(error);}finally{if(active()&&version===relatedVersion)submit.disabled=false;}
  }
  function fill(row){
    for(const [key,control] of Object.entries(fields)){control.value=key==='due'?inputTime(row?.due):row?.[key]??({course_id:cid,max_score:100,weight:1,component:'regmid',status:'present'}[key]??'');}
    fields.course_id.disabled=!!row;submit.textContent=row?'Сохранить изменения':`Добавить ${titles[kind]}`;
    related(row);
  }
  selection.addEventListener('change',()=>fill(rows.find(row=>row.id===selection.value)));
  fields.course_id.addEventListener('change',()=>related());
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!active()||submit.disabled||!form.reportValidity())return;submit.disabled=true;
    const payload={};for(const [key,control] of Object.entries(fields)){
      if(key==='due')payload[key]=control.value?control.value+':00+05:00':null;
      else if(control.type==='number')payload[key]=control.value===''?null:Number(control.value);
      else payload[key]=control.value.trim();
    }
    try{await api('admin/'+kind+(selection.value?'/'+encodeURIComponent(selection.value):''),{method:selection.value?'PATCH':'POST',body:payload});if(active())await reload();}
    catch(error){if(active())showError(error);}finally{if(active())submit.disabled=false;}
  });fill(null);
}

export async function collectionPage(parent,kind,cid,prefix,active,reload){
  const courses=(await api(prefix+'courses')).items.filter(row=>!row.archived);if(!active())return;
  if(kind==='attendance'&&!cid){empty(parent,'Выберите дисциплину','Выберите предмет в меню слева, чтобы отметить посещаемость и увидеть журнал.');return;}
  const rows=(await api(prefix+kind+(cid?'?course_id='+encodeURIComponent(cid):''))).items.filter(row=>!row.course_id||courses.some(course=>course.id===row.course_id));if(!active())return;
  const courseNames=new Map(courses.map(row=>[row.id,row.name]));
  if(prefix==='admin/')await editor(parent,kind,cid,courses,rows,active,reload);if(!active())return;
  if(kind==='materials')materials(parent,rows,courseNames);
  else if(kind==='assignments')assignmentCards(parent,rows,courses);
  else if(kind==='grade_items')workItems(parent,rows,courseNames);
  else if(kind==='attendance'){
    const users=(await api('admin/users')).items;if(!active())return;
    const lessons=(await api('admin/lessons?course_id='+encodeURIComponent(cid))).items;if(!active())return;
    if(!rows.length){empty(parent,'Журнал пока пуст','Добавьте первую отметку через форму выше.');return;}
    const lessonNames=new Map(lessons.map(row=>[row.id,row]));const userNames=new Map(users.map(row=>[row.id,row.name]));
    table(parent,[{label:'Студент',value:row=>userNames.get(row.student_id)||'Студент'},{label:'Дата',value:row=>dateText(lessonNames.get(row.lesson_id)?.starts_at)},{label:'Занятие',value:row=>lessonNames.get(row.lesson_id)?.title||'Занятие'},{label:'Отметка',value:row=>cell=>badge(cell,statuses[row.status]||'Не отмечено',row.status==='present'?'positive':row.status==='absent'?'negative':'neutral')}],rows);
  }
}

export async function dataBrowser(parent,active){
  const resources=(await api('data/resources')).resources;if(!active())return;
  intro(parent,'Выберите набор данных. Здесь доступны только записи, разрешённые для вашей учётной записи.');
  if(!resources.length){empty(parent,'Нет доступных наборов данных');return;}
  const form=element('form',undefined,parent);form.className='friendly-form';
  const resource=element('select',undefined,element('label','Данные',form));resource.append(...resources.map(row=>new Option(names[row.name]||row.label||row.name,row.name)));
  const filter=element('select',undefined,element('label','Фильтр · необязательно',form));
  const value=element('input',undefined,element('label','Значение фильтра',form));
  const labels={title:'Название',name:'Название',component:'Компонент оценки',status:'Посещаемость',done:'Завершено',week:'Неделя',archived:'В архиве',code:'Код дисциплины',score:'Балл',minutes:'Подготовка, минут',due:'Дедлайн'};
  function filters(){const selected=resources.find(row=>row.name===resource.value);filter.replaceChildren(new Option('Без фильтра',''),...(selected.filterable||[]).filter(key=>labels[key]).map(key=>new Option(labels[key],key)));value.value='';value.disabled=true;}
  resource.addEventListener('change',filters);filter.addEventListener('change',()=>{value.disabled=!filter.value;value.required=!!filter.value;});filters();
  const submit=element('button','Показать записи',form);const output=element('div',undefined,parent);output.className='data-results';
  let request=0;
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!form.reportValidity())return;const version=++request;submit.disabled=true;output.replaceChildren();
    const query={resource:resource.value,limit:25};
    if(filter.value){const meta=resources.find(row=>row.name===resource.value);const type=meta.fields?.[filter.value];let parsed=value.value;if(['number','integer'].includes(type)){parsed=Number(value.value);if(!Number.isFinite(parsed)){showError(new Error('Введите число для выбранного фильтра.'));submit.disabled=false;return;}}else if(type==='boolean'){if(!['true','false','да','нет'].includes(value.value.toLowerCase())){showError(new Error('Для этого фильтра введите «да» или «нет».'));submit.disabled=false;return;}parsed=['true','да'].includes(value.value.toLowerCase());}query.filters={[filter.value]:parsed};}
    async function fetchPage(cursor){
      const result=await api('data/query',{method:'POST',body:{...query,...(cursor?{cursor}:{})}});if(!active()||version!==request)return;
      records(output,result.items);
      if(result.next_cursor){const more=element('button','Показать ещё',output);more.type='button';more.addEventListener('click',async()=>{more.disabled=true;try{await fetchPage(result.next_cursor);more.remove();}catch(error){if(active())showError(error);more.disabled=false;}});}
    }
    try{await fetchPage();}catch(error){if(active()&&version===request)showError(error);}finally{if(active()&&version===request)submit.disabled=false;}
  });
}
