import {api} from './api.mjs';
import {element,showError} from './ui.mjs';
export const collections = ['courses','enrollments','assignments','grade_items','grades','lessons','attendance','materials'];
const examples = {
  courses: {code:'CS101',instructor_ids:['teacher1','teacher2'],name:'Название дисциплины',archived:false},
  enrollments: {course_id:'ID дисциплины',student_id:'логин студента',archived:false},
  assignments: {course_id:'ID дисциплины',title:'Название задания',description:'Описание',due:'2026-12-31T23:59:00+05:00',minutes:60},
  grade_items: {course_id:'ID дисциплины',title:'Рубежный контроль 1',component:'attestation1',max_score:100,weight:1},
  grades: {course_id:'ID дисциплины',student_id:'логин студента',item_id:'ID элемента оценки',score:80,comment:''},
  lessons: {course_id:'ID дисциплины',title:'Лекция',starts_at:'2026-10-21T09:00:00+05:00',ends_at:'2026-10-21T10:00:00+05:00',kind:'lecture'},
  attendance: {course_id:'ID дисциплины',student_id:'логин студента',lesson_id:'ID занятия',status:'present'},
  materials: {course_id:'ID дисциплины',name:'Материал',text:'Текст материала',source_url:'https://example.org'}
};
export function adminForm(parent, kind, reload, courseId = '') {
  const form = element('form',undefined,parent);
  const idLabel = element('label','ID для изменения (пусто — создать)',form), id = element('input',undefined,idLabel);
  const bodyLabel = element('label','Поля записи в JSON',form), body = element('textarea',undefined,bodyLabel);
  body.value = JSON.stringify({...examples[kind], ...(courseId && kind !== 'courses' ? {course_id:courseId} : {})},null,2);
  element('p','Замените значения-примеры на реальные ID. Для оценки сначала создайте элемент оценки.',form);
  const button = element('button','Сохранить',form);
  form.addEventListener('submit',async event => {
    event.preventDefault(); button.disabled = true;
    try { const payload = JSON.parse(body.value); await api(`admin/${kind}${id.value ? '/' + encodeURIComponent(id.value) : ''}`,{method:id.value ? 'PATCH' : 'POST',body:payload}); await reload(); }
    catch(error) { showError(error); } finally { button.disabled = false; }
  });
}
function selectField(form, label, rows, value, title) {
  const select = element('select',undefined,element('label',label,form)); select.required = true;
  select.append(new Option('Выберите…',''));
  for (const row of rows) select.append(new Option(title(row),value(row)));
  return select;
}
export function enrollmentForm(parent, courseId, students, reload) {
  if (!courseId) { element('p','Сначала выберите дисциплину сверху.',parent); return; }
  const form = element('form',undefined,parent);
  const student = selectField(form,'Студент',students,row => row.id,row => `${row.name} (${row.id})`);
  const button = element('button','Зачислить на дисциплину',form);
  form.addEventListener('submit',async event => {
    event.preventDefault(); button.disabled = true;
    try { await api('admin/enrollments',{method:'POST',body:{course_id:courseId,student_id:student.value,archived:false}}); await reload(); }
    catch(error) { showError(error); } finally { button.disabled = false; }
  });
}
export function gradeForm(parent, courseId, students, items, reload) {
  if (!courseId) { element('p','Сначала выберите дисциплину сверху.',parent); return; }
  if (!students.length) { element('p','В этой дисциплине нет зачисленных студентов. Сначала откройте «Зачисление».',parent); return; }
  if (!items.length) { element('p','В этой дисциплине нет элементов оценки. Сначала откройте «Элементы оценок».',parent); return; }
  const form = element('form',undefined,parent);
  const student = selectField(form,'Студент',students,row => row.id,row => `${row.name} (${row.id})`);
  const item = selectField(form,'Работа или контроль',items,row => row.id,row => `${row.title} — максимум ${row.max_score}`);
  const score = element('input',undefined,element('label','Балл',form)); score.type = 'number'; score.min = '0'; score.step = '0.01'; score.required = true;
  item.addEventListener('change',() => { const selected = items.find(row => row.id === item.value); score.max = selected ? String(selected.max_score) : ''; });
  const comment = element('input',undefined,element('label','Комментарий (необязательно)',form)); comment.maxLength = 2000;
  const button = element('button','Выставить оценку',form);
  form.addEventListener('submit',async event => {
    event.preventDefault(); button.disabled = true;
    try { await api('admin/grades',{method:'POST',body:{course_id:courseId,student_id:student.value,item_id:item.value,score:Number(score.value),comment:comment.value}}); await reload(); }
    catch(error) { showError(error); } finally { button.disabled = false; }
  });
}
export function personalForm(parent, prepare) {
  const form = element('form',undefined,parent);
  const fields = {};
  for (const [name,label,type] of [['record_id','ID для изменения (пусто — новая задача)','text'],['title','Название','text'],['due','Дедлайн ISO 8601 с часовым поясом (необязательно)','text'],['minutes','Время, минут','number']]) {
    const wrapper = element('label',label,form), input = element('input',undefined,wrapper); input.type = type; fields[name] = input;
  }
  fields.minutes.min = '10'; fields.minutes.max = '2400'; fields.minutes.value = '60';
  const done = element('input',undefined,element('label','Завершено',form)); done.type = 'checkbox';
  element('button','Подготовить изменение',form);
  form.addEventListener('submit',async event => {
    event.preventDefault();
    const payload = {done:done.checked};
    if (fields.title.value) payload.title = fields.title.value;
    if (fields.due.value) payload.due = fields.due.value;
    if (fields.minutes.value) payload.minutes = Number(fields.minutes.value);
    try { await prepare({target:'task',record_id:fields.record_id.value || null,payload}); } catch(error) { showError(error); }
  });
}
