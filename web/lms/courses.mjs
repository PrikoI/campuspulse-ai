import {api} from './api.mjs';
import {element,showError} from './ui.mjs';
import {courseCards} from './views.mjs';

export async function courseList(parent, reload, active, updateCourses, open) {
  const form = element('form',undefined,parent);
  form.className='course-create';
  const name = element('input',undefined,element('label','Название дисциплины',form));
  name.required = true; name.maxLength = 200; name.placeholder = 'Например, Математика';
  const add = element('button','Добавить дисциплину',form);
  form.addEventListener('submit',async event => {
    event.preventDefault();
    if (!active() || add.disabled || !form.reportValidity()) return;
    if (!name.value.trim()) { name.setCustomValidity('Введите название дисциплины.'); name.reportValidity(); return; }
    add.disabled = true;
    try {
      const code = 'SUB-' + crypto.randomUUID().replaceAll('-','').slice(0,10);
      await api('admin/courses',{method:'POST',body:{name:name.value.trim(),code}});
      if (active()) await reload();
    }
    catch(error) { if (active()) showError(error); } finally { add.disabled = false; }
  });
  name.addEventListener('input',() => name.setCustomValidity(''));
  const data = await api('admin/courses');
  if (!active()) return;
  updateCourses(data.items);
  const rows = data.items.filter(row => !row.archived);
  if (!rows.length) { element('p','Дисциплин пока нет. Добавьте первую.',parent); return; }
  const cards=courseCards(parent,rows,open);
  for (const row of rows) {
    const actions=cards.get(row.id);
    const remove = element('button','Убрать дисциплину',actions); remove.type = 'button';
    remove.addEventListener('click',async () => {
      if (!active() || !window.confirm(`Удалить дисциплину «${row.name}»?`)) return;
      remove.disabled = true;
      try {
        await api('admin/courses/' + encodeURIComponent(row.id),{method:'DELETE'});
        if (active()) await reload();
      } catch(error) {
        if (!active()) return;
        if (error.status === 409 && window.confirm('У дисциплины есть связанные данные. Убрать её из активного списка в архив, сохранив оценки и работы?')) {
          try { await api('admin/courses/' + encodeURIComponent(row.id),{method:'PATCH',body:{archived:true}}); if (active()) await reload(); }
          catch(failure) { if (active()) showError(failure); }
        } else showError(error);
      } finally { remove.disabled = false; }
    });
  }
}
