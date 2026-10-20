import {api} from './api.mjs';
import {element,showError} from './ui.mjs';
export const collections = ['courses','enrollments','assignments','grade_items','grades','lessons','attendance','materials'];
export function adminForm(parent, kind, reload) {
  const form = element('form',undefined,parent);
  const idLabel = element('label','ID для изменения (пусто — создать)',form), id = element('input',undefined,idLabel);
  const bodyLabel = element('label','Поля записи в JSON по контракту API',form), body = element('textarea',undefined,bodyLabel); body.value = '{}';
  const button = element('button','Сохранить',form);
  form.addEventListener('submit',async event => {
    event.preventDefault(); button.disabled = true;
    try { const payload = JSON.parse(body.value); await api(`admin/${kind}${id.value ? '/' + encodeURIComponent(id.value) : ''}`,{method:id.value ? 'PATCH' : 'POST',body:payload}); await reload(); }
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
