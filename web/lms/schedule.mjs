import {api} from './api.mjs';
import {element} from './ui.mjs';

const zone = 'Asia/Qyzylorda';
const dateKey = value => new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
const clock = value => new Intl.DateTimeFormat('ru-RU',{timeZone:zone,hour:'2-digit',minute:'2-digit'}).format(new Date(value));
const dayDate = key => new Date(key + 'T12:00:00Z');
const shift = (date, days) => new Date(date.getTime() + days * 86400000);
export function monday(key) {
  const date = dayDate(key);
  return shift(date,-((date.getUTCDay()+6)%7));
}

export async function schedule(parent, prefix, query, active) {
  const courses = await api(prefix + 'courses');
  if (!active()) return;
  const names = new Map(courses.items.filter(row => !row.archived).map(row => [row.id,row.name]));
  const lessons = {items:[]};
  const selected = new URLSearchParams(query).get('course_id');
  for (const course of courses.items.filter(row => !row.archived && (!selected || row.id === selected))) {
    if (!active()) return;
    const result = await api(prefix + 'lessons?course_id=' + encodeURIComponent(course.id));
    lessons.items.push(...result.items);
  }
  if (!active()) return;
  const rows = lessons.items.filter(row => names.has(row.course_id)).sort((a,b) => new Date(a.starts_at)-new Date(b.starts_at));
  const today = dateKey(new Date());
  const next = rows.find(row => dateKey(row.starts_at) >= today);
  let start = monday(next ? dateKey(next.starts_at) : rows.length ? dateKey(rows.at(-1).starts_at) : today);
  const root = element('div',undefined,parent); root.className = 'schedule-view';
  const toolbar = element('div',undefined,root); toolbar.className = 'schedule-toolbar';
  const heading = element('div',undefined,toolbar);
  const title = element('h2',undefined,heading);
  element('p','Время Кызылорды · UTC+5',heading).className = 'schedule-muted';
  const controls = element('div',undefined,toolbar); controls.className = 'schedule-controls';
  const previous = element('button','←',controls); previous.setAttribute('aria-label','Предыдущая неделя');
  const current = element('button','Эта неделя',controls);
  const following = element('button','→',controls); following.setAttribute('aria-label','Следующая неделя');
  const summary = element('p',undefined,root); summary.className = 'schedule-summary';
  const grid = element('div',undefined,root); grid.className = 'schedule-grid schedule-timetable';
  function draw() {
    grid.replaceChildren();
    const end = shift(start,6), from = dateKey(start), to = dateKey(end);
    const dateLabel = date => date.toLocaleDateString('ru-RU',{timeZone:'UTC',day:'numeric',month:'long'});
    title.textContent = `${dateLabel(start)} — ${dateLabel(end)}, ${end.getUTCFullYear()}`;
    const weekly = rows.filter(row => dateKey(row.starts_at)>=from && dateKey(row.starts_at)<=to);
    summary.textContent = `${weekly.length} занятий · ${new Set(weekly.map(row => row.course_id)).size} дисциплин`;
    const minutes = value => { const [h,m] = clock(value).split(':').map(Number); return h*60+m; };
    const firstHour = Math.min(9,...weekly.map(row => Math.floor(minutes(row.starts_at)/60)));
    const lastHour = Math.max(16,...weekly.map(row => Math.ceil(minutes(row.ends_at)/60)));
    const height = (lastHour-firstHour)*80;
    const axis = element('div',undefined,grid); axis.className = 'schedule-axis';
    element('div','Время',axis).className = 'schedule-day-heading';
    const scale = element('div',undefined,axis); scale.className = 'schedule-timeline'; scale.style.height = height+'px';
    for (let h=firstHour;h<=lastHour;h++) { const tick=element('span',String(h).padStart(2,'0')+':00',scale); tick.className='schedule-tick'; tick.style.top=((h-firstHour)*80)+'px'; }
    const days = 7;
    for (let i=0;i<days;i++) {
      const date = shift(start,i), key = dateKey(date);
      const column = element('div',undefined,grid); column.className = 'schedule-day' + (key===today ? ' is-today' : '');
      const label = element('div',undefined,column); label.className = 'schedule-day-heading';
      element('span',date.toLocaleDateString('ru-RU',{timeZone:'UTC',weekday:'short'}),label);
      element('strong',String(date.getUTCDate()),label);
      const timeline = element('div',undefined,column); timeline.className='schedule-timeline'; timeline.style.height=height+'px';
      const daily = weekly.filter(row => dateKey(row.starts_at)===key);
      if (!daily.length) element('p',i===6 ? 'Выходной' : 'Нет занятий',timeline).className = 'schedule-empty';
      for (const row of daily) {
        const card = element('article',undefined,timeline); card.className = 'lesson-card';
        card.style.top = ((minutes(row.starts_at)-firstHour*60)*80/60)+'px';
        card.style.height = ((new Date(row.ends_at)-new Date(row.starts_at))/60000*80/60)+'px';
        card.style.setProperty('--lesson-color', ['#008577','#5375d1','#b16d24','#a75591','#487c37','#ae5555'][[...names.keys()].indexOf(row.course_id)%6]);
        element('p',`${clock(row.starts_at)} – ${clock(row.ends_at)}`,card).className = 'lesson-time';
        element('h3',names.get(row.course_id),card);
        if (row.title && row.title!==names.get(row.course_id)) element('p',row.title,card);
        const duration = Math.round((new Date(row.ends_at)-new Date(row.starts_at))/60000);
        element('span',`${duration} мин`,card).className = 'lesson-duration';
      }
    }
    if (!weekly.length) summary.textContent = 'На эту неделю занятий нет. Переключите неделю стрелками.';
  }
  previous.addEventListener('click',() => { start=shift(start,-7); draw(); });
  following.addEventListener('click',() => { start=shift(start,7); draw(); });
  current.addEventListener('click',() => { start=monday(today); draw(); });
  draw();
}
