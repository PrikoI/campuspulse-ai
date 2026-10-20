import {api} from './api.mjs';
import {element,showError} from './ui.mjs';

export async function assignments(parent,prefix,query,active) {
  const courses = (await api(prefix+'courses')).items;
  if (!active()) return;
  const data=await api(prefix+'assignments'+query);
  if (!active()) return;
  assignmentCards(parent,data.items,courses);
}

export function assignmentCards(parent,items,courses) {
  const names=new Map(courses.map(row=>[row.id,row.name]));
  const cards=element('div',undefined,parent);cards.className='assignment-grid';
  const rows=items.filter(row=>courses.some(course=>course.id===row.course_id&&!course.archived)).sort((a,b)=>(a.due||'z').localeCompare(b.due||'z'));
  if (!rows.length) element('p','Заданий пока нет. Преподаватель может связать работы с дедлайнами.',cards);
  for (const task of rows) {
    const card=element('article',undefined,cards);card.className='assignment-card';
    element('p',names.get(task.course_id),card).className='eyebrow';
    element('h3',task.title,card);
    const due=task.due?new Date(task.due):null;
    element('p',due ? due.toLocaleString('ru-RU',{timeZone:'Asia/Qyzylorda',day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'}) : 'Дедлайн не указан',card).className='assignment-date';
    element('span',due&&due<Date.now()?'Срок прошёл':due?'Предстоит':'Ожидает даты',card).className='status-badge '+(due&&due<Date.now()?'negative':'neutral');
    if (task.minutes) element('p',`Подготовка: ${task.minutes} мин`,card);
    if (task.description) element('p',task.description,card).className='assignment-description';
  }
}

export async function enrollments(parent,active,reload) {
  const courses=(await api('admin/courses')).items.filter(row=>!row.archived);
  if (!active()) return;
  const users=(await api('admin/users')).items;
  if (!active()) return;
  const existing=(await api('admin/enrollments')).items;
  if (!active()) return;
  const form=element('form',undefined,parent);
  const course=element('select',undefined,element('label','Предмет',form));
  course.append(...courses.map(row=>new Option(row.name,row.id)));
  const student=element('select',undefined,element('label','Ученик',form));
  student.append(...users.map(row=>new Option(row.name||row.id,row.id)));
  const submit=element('button','Зачислить на предмет',form);submit.disabled=!courses.length||!users.length;
  form.addEventListener('submit',async event=>{
    event.preventDefault();submit.disabled=true;
    const row=existing.find(row=>row.course_id===course.value&&row.student_id===student.value);
    try {await api('admin/enrollments'+(row?'/'+encodeURIComponent(row.id):''),{method:row?'PATCH':'POST',body:{course_id:course.value,student_id:student.value,archived:false}});if(active())await reload();}
    catch(error){if(active())showError(error);}finally{submit.disabled=false;}
  });
  element('h2','Зачисления',parent);
  for(const row of existing.filter(row=>!row.archived&&courses.some(course=>course.id===row.course_id))){
    const line=element('div',undefined,parent);line.className='enrollment-row';
    element('span',`${users.find(user=>user.id===row.student_id)?.name||row.student_id} · ${courses.find(course=>course.id===row.course_id)?.name}`,line);
    const remove=element('button','Отчислить',line);
    remove.addEventListener('click',async()=>{remove.disabled=true;try{await api('admin/enrollments/'+encodeURIComponent(row.id),{method:'PATCH',body:{archived:true}});if(active())await reload();}catch(error){if(active())showError(error);}finally{remove.disabled=false;}});
  }
}
