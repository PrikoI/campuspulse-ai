import {api} from './api.mjs';
import {element,showError} from './ui.mjs';

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
  const firstWeek = monday('2026-09-07');
  let start = new Date(firstWeek);
  const root = element('div',undefined,parent); root.className = 'schedule-view';
  const originals = new Map(rows.map(row=>[row.id,{...row}]));
  const pending = new Map();
  let editing=false,saving=false;
  const toolbar = element('div',undefined,root); toolbar.className = 'schedule-toolbar';
  const heading = element('div',undefined,toolbar);
  const title = element('h2',undefined,heading);
  element('p','Время Кызылорды · UTC+5',heading).className = 'schedule-muted';
  const controls = element('div',undefined,toolbar); controls.className = 'schedule-controls';
  const previous = element('button','←',controls); previous.setAttribute('aria-label','Предыдущая неделя');
  const current = element('button','Эта неделя',controls);
  const following = element('button','→',controls); following.setAttribute('aria-label','Следующая неделя');
  const editBar=element('div',undefined,root);editBar.className='schedule-editbar';
  const edit=element('button','Изменить расписание',editBar);edit.hidden=prefix!=='admin/';
  const save=element('button','Сохранить',editBar);save.hidden=true;
  const cancel=element('button','Отмена',editBar);cancel.hidden=true;
  const hint=element('span',undefined,editBar);
  function editMode(value){editing=value;edit.hidden=value||prefix!=='admin/';save.hidden=cancel.hidden=!value;hint.textContent=value?'Перетаскивайте карточки. Шаг 20 минут. Или выберите карточку и используйте стрелки.':'';draw();}
  edit.addEventListener('click',()=>editMode(true));
  cancel.addEventListener('click',()=>{if(saving)return;for(const row of rows)Object.assign(row,originals.get(row.id));pending.clear();editMode(false);});
  save.addEventListener('click',async()=>{
    if(saving||!pending.size||!active())return;
    saving=true;save.disabled=cancel.disabled=true;
    try{await api('admin/schedule',{method:'POST',body:{changes:[...pending.values()]}});if(!active())return;for(const row of rows)originals.set(row.id,{...row});pending.clear();editMode(false);hint.textContent='Расписание и связанные дедлайны сохранены.';}
    catch(error){if(active())showError(error);}finally{saving=false;save.disabled=cancel.disabled=false;}
  });
  function move(row,key,minute){
    if(!editing||saving)return;
    const duration=new Date(row.ends_at)-new Date(row.starts_at);
    const start=new Date(key+'T00:00:00+05:00');start.setTime(start.getTime()+minute*60000);
    const end=new Date(start.getTime()+duration);
    if(rows.some(other=>other.id!==row.id&&new Date(other.starts_at)<end&&new Date(other.ends_at)>start)){
      showError(new Error('В это время уже есть занятие. Выберите свободный интервал.'));return;
    }
    row.starts_at=start.toISOString();row.ends_at=end.toISOString();
    const original=originals.get(row.id);
    pending.set(row.id,{id:row.id,starts_at:row.starts_at,ends_at:row.ends_at,expected_start:original.starts_at,expected_end:original.ends_at});
    draw();
  }
  const monthLabel = element('label','Перейти к месяцу',root); monthLabel.className = 'schedule-month-label';
  const monthSelect = element('select',undefined,monthLabel);
  const lastDate = rows.length ? new Date(rows.at(-1).starts_at) : firstWeek;
  const monthEnd = Math.max(Date.UTC(2027,7,1),Date.UTC(lastDate.getUTCFullYear(),lastDate.getUTCMonth(),1));
  for (let date = new Date(Date.UTC(2026,8,1)); date.getTime()<=monthEnd; date.setUTCMonth(date.getUTCMonth()+1)) {
    const key = date.toISOString().slice(0,7);
    monthSelect.append(new Option(date.toLocaleDateString('ru-RU',{timeZone:'UTC',month:'long',year:'numeric'}),key));
  }
  const summary = element('p',undefined,root); summary.className = 'schedule-summary';
  const grid = element('div',undefined,root); grid.className = 'schedule-grid schedule-timetable';
  function draw() {
    grid.replaceChildren();
    grid.classList.toggle('is-editing',editing);save.disabled=saving||!pending.size;save.textContent=`Сохранить${pending.size?' ('+pending.size+')':''}`;
    const end = shift(start,6), from = dateKey(start), to = dateKey(end);
    const monthKey = from.slice(0,7);
    if (![...monthSelect.options].some(option => option.value===monthKey)) {
      monthSelect.append(new Option(start.toLocaleDateString('ru-RU',{timeZone:'UTC',month:'long',year:'numeric'}),monthKey));
    }
    monthSelect.value = monthKey;
    previous.disabled = start.getTime()<=firstWeek.getTime();
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
      timeline.dataset.date=key;timeline.dataset.firstHour=firstHour;timeline.dataset.lastHour=lastHour;
      const daily = weekly.filter(row => dateKey(row.starts_at)===key);
      if (!daily.length) element('p',i===6 ? 'Выходной' : 'Нет занятий',timeline).className = 'schedule-empty';
      for (const row of daily) {
        const card = element('article',undefined,timeline); card.className = 'lesson-card';
        if(pending.has(row.id))card.classList.add('is-changed');
        if(editing){
          card.tabIndex=0;card.setAttribute('aria-label',`${names.get(row.course_id)}. Стрелки вверх/вниз: время, влево/вправо: день.`);
          card.addEventListener('keydown',event=>{
            if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key))return;
            event.preventDefault();const direction={ArrowUp:-20,ArrowDown:20,ArrowLeft:-1440,ArrowRight:1440}[event.key];
            const date=new Date(new Date(row.starts_at).getTime()+direction*60000);const parts=clock(date).split(':').map(Number);move(row,dateKey(date),parts[0]*60+parts[1]);
          });
          card.addEventListener('pointerdown',event=>{
            if(event.button!==0||saving)return;
            const origin={x:event.clientX,y:event.clientY,offset:event.clientY-card.getBoundingClientRect().top};
            card.setPointerCapture(event.pointerId);card.classList.add('is-dragging');
            const update=event=>{card.style.transform=`translate(${event.clientX-origin.x}px,${event.clientY-origin.y}px)`;};
            const finish=event=>{
              card.removeEventListener('pointermove',update);card.removeEventListener('pointerup',finish);card.removeEventListener('pointercancel',abort);
              card.style.transform='';card.classList.remove('is-dragging');
              if(Math.hypot(event.clientX-origin.x,event.clientY-origin.y)<5)return;
              card.style.pointerEvents='none';const destination=document.elementFromPoint(event.clientX,event.clientY)?.closest('.schedule-timeline[data-date]');card.style.pointerEvents='';
              if(!destination)return;
              const first=Number(destination.dataset.firstHour)*60,last=Number(destination.dataset.lastHour)*60;
              const minute=Math.round((first+(event.clientY-destination.getBoundingClientRect().top-origin.offset)*60/80)/20)*20;
              const duration=(new Date(row.ends_at)-new Date(row.starts_at))/60000;
              if(minute<first||minute+duration>last)return;
              move(row,destination.dataset.date,minute);
            };
            const abort=()=>{card.style.transform='';card.classList.remove('is-dragging');card.removeEventListener('pointermove',update);card.removeEventListener('pointerup',finish);card.removeEventListener('pointercancel',abort);};
            card.addEventListener('pointermove',update);card.addEventListener('pointerup',finish);card.addEventListener('pointercancel',abort);
          });
        }
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
  let animation;
  function navigate(date) {
    if (!active()) return;
    const destination = date < firstWeek ? new Date(firstWeek) : date;
    const direction = destination>=start ? 1 : -1;
    start=destination;
    animation?.cancel();
    draw();
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      animation = grid.animate([
        {opacity:0,transform:`translateX(${direction*22}px)`},
        {opacity:1,transform:'translateX(0)'}
      ],{duration:220,easing:'cubic-bezier(.2,.7,.3,1)'});
    }
  }
  previous.addEventListener('click',() => navigate(shift(start,-7)));
  following.addEventListener('click',() => navigate(shift(start,7)));
  current.addEventListener('click',() => navigate(monday(today)));
  monthSelect.addEventListener('change',() => {
    const date = dayDate(monthSelect.value+'-01');
    const offset = (8-date.getUTCDay())%7;
    navigate(shift(date,offset));
  });
  draw();
}
