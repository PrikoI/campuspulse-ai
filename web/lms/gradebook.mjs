import {api} from './api.mjs';
import {element,showError} from './ui.mjs';

export async function gradebook(parent, courseId, reload, active) {
  const kinds = ['courses','users','enrollments','grade_items','grades'];
  const results = [];
  for (const kind of kinds) {
    if (!active()) return;
    results.push(await api('admin/' + kind));
  }
  if (!active()) return;
  const [courses,users,enrollments,items,grades] = results.map(result => result.items);
  const workOrder = row => row.title === 'Midterm' ? 5 : row.title === 'Endterm' ? 10 : /^Assignment \d+$/.test(row.title) ? Number(row.title.split(' ')[1]) : 1000;
  items.sort((a,b) => workOrder(a) - workOrder(b) || a.title.localeCompare(b.title));
  const form = element('form',undefined,parent);
  const select = label => element('select',undefined,element('label',label,form));
  const course = select('Предмет'), student = select('Ученик'), item = select('Работа');
  for (const control of [course,student,item]) control.required = true;
  course.append(new Option('Выберите предмет',''),...courses.filter(row => !row.archived).map(row => new Option(row.name,row.id)));
  course.value = courseId;
  const score = element('input',undefined,element('label','Балл',form));
  score.type = 'number'; score.min = '0'; score.step = 'any'; score.required = true;
  const comment = element('input',undefined,element('label','Комментарий',form)); comment.maxLength = 2000;
  const save = element('button','Поставить оценку',form);
  const notice = element('p',undefined,parent), list = element('section',undefined,parent);
  function draw() {
    const ids = new Set(enrollments.filter(row => row.course_id === course.value && !row.archived).map(row => row.student_id));
    student.replaceChildren(new Option('Выберите ученика',''),...users.filter(row => ids.has(row.id)).map(row => new Option(row.name || row.id,row.id)));
    item.replaceChildren(new Option('Выберите работу',''),...items.filter(row => row.course_id === course.value).map(row => new Option(`${row.title} (макс. ${row.max_score ?? 100})`,row.id)));
    score.value = ''; comment.value = ''; score.removeAttribute('max');
    save.disabled = !course.value || !ids.size || item.options.length < 2;
    notice.textContent = !course.value ? 'Выберите предмет для выставления оценки.' : !ids.size ? 'На этот предмет ещё не зачислены ученики.' : item.options.length < 2 ? 'Сначала создайте оцениваемую работу в разделе grade_items.' : 'Повторное сохранение обновит оценку выбранного ученика за эту работу.';
    list.replaceChildren();
    const table = element('table',undefined,list), head = element('tr',undefined,element('thead',undefined,table));
    ['Предмет','Ученик','Работа','Балл','Комментарий','Действия'].forEach(title => element('th',title,head));
    const body = element('tbody',undefined,table);
    const visible = grades.filter(row => !course.value || row.course_id === course.value);
    if (!visible.length) element('p','Оценок пока нет.',list);
    for (const row of visible) {
      const tr = element('tr',undefined,body);
      [courses.find(x => x.id === row.course_id)?.name || row.course_id, users.find(x => x.id === row.student_id)?.name || row.student_id, items.find(x => x.id === row.item_id)?.title || row.item_id, row.score ?? 'Не выставлена', row.comment || ''].forEach(value => element('td',value,tr));
      const actions = element('td',undefined,tr), remove = element('button','Удалить',actions); remove.type = 'button';
      remove.addEventListener('click',async () => {
        if (!active() || !window.confirm('Удалить эту оценку?')) return;
        remove.disabled = true;
        try { await api('admin/grades/' + encodeURIComponent(row.id),{method:'DELETE'}); if (active()) await reload(); }
        catch(error) { if (active()) showError(error); } finally { remove.disabled = false; }
      });
    }
  }
  function existing() {
    const work = items.find(row => row.id === item.value);
    score.max = String(work?.max_score ?? 100);
    const grade = grades.find(row => row.student_id === student.value && row.item_id === item.value && row.course_id === course.value);
    score.value = grade?.score ?? ''; comment.value = grade?.comment ?? '';
    save.textContent = grade ? 'Обновить оценку' : 'Поставить оценку';
  }
  course.addEventListener('change',draw); student.addEventListener('change',existing); item.addEventListener('change',existing);
  form.addEventListener('submit',async event => {
    event.preventDefault(); if (!active() || save.disabled || !form.reportValidity()) return;
    save.disabled = true;
    const old = grades.find(row => row.course_id === course.value && row.student_id === student.value && row.item_id === item.value);
    try {
      await api('admin/grades' + (old ? '/' + encodeURIComponent(old.id) : ''),{method:old ? 'PATCH' : 'POST',body:{course_id:course.value,student_id:student.value,item_id:item.value,score:Number(score.value),comment:comment.value}});
      if (active()) await reload();
    } catch(error) { if (active()) showError(error); } finally { save.disabled = false; }
  });
  draw();
}
