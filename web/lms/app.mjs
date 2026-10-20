import {schedule} from './schedule.mjs';
import {enrollments} from './academics.mjs';
import {courseList} from './courses.mjs';
import {gradebook} from './gradebook.mjs';
import {api,onUnauthorized} from './api.mjs';
import {element,showError,studyPlan} from './ui.mjs';
import {personalForm} from './forms.mjs';
import {bindAgent} from './agent.mjs';
import {courseCards,students,gradeSummary,attendanceSummary,personalTasks,reviewChange,empty} from './views.mjs';
import {collectionPage,dataBrowser} from './screens.mjs';

const $=selector=>document.querySelector(selector);
const pages={students:'Студенты',courses:'Дисциплины',enrollments:'Зачисление',assignments:'Задания',grade_items:'Работы',materials:'Материалы',grades:'Оценки',attendance:'Посещаемость',schedule:'Расписание',plan:'План подготовки',data:'Доступные данные',personal:'Личные задачи'};
let user=null,page='courses',requestVersion=0,pendingProposal=null;

function reset(){user=null;requestVersion++;pendingProposal=null;stopAgent();delete $('#workspace').dataset.role;$('#workspace').hidden=true;$('#login-panel').hidden=false;$('#logout').hidden=true;$('#identity').textContent='';$('#content').replaceChildren();$('#review').hidden=true;$('#course').replaceChildren(new Option('Все дисциплины',''));}
onUnauthorized(reset);
function review(proposal){pendingProposal=proposal;reviewChange($('#review-data'),proposal.change);$('#review').hidden=false;$('#review').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});}
const prepare=async change=>{const actor=user,proposal=await api('actions/prepare',{method:'POST',body:change});if(actor===user)review(proposal);};
const stopAgent=bindAgent(()=>({page:['personal','data','students','enrollments','grade_items'].includes(page)?'overview':page,...($('#course').value?{course_id:$('#course').value}:{})}),review);

function courseOptions(rows){const current=$('#course').value;const active=rows.filter(row=>!row.archived);$('#course').replaceChildren(new Option('Все дисциплины',''),...active.map(row=>new Option(row.name,row.id)));$('#course').value=active.some(row=>row.id===current)?current:'';}
function navigate(name,cid){if(cid!==undefined)$('#course').value=cid;page=name;for(const item of $('#navigation').children){if(item.dataset.page===name)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');}load();}

async function load(){
  const version=++requestVersion,container=$('#content'),cid=$('#course').value;
  const active=()=>version===requestVersion;
  container.replaceChildren();$('#error').textContent='';$('#page-title').textContent=pages[page]||page;
  const loading=element('div',undefined,container);loading.className='page-loading';loading.setAttribute('role','status');
  const spinner=element('span',undefined,loading);spinner.className='loading-spinner';spinner.setAttribute('aria-hidden','true');element('span','Загрузка…',loading);
  const target=element('div',undefined,container);target.hidden=true;target.setAttribute('aria-busy','true');
  const prefix=user?.role==='admin'?'admin/':'',query=cid?'?course_id='+encodeURIComponent(cid):'';
  try{
    if(page==='courses'){
      if(user.role==='admin')await courseList(target,load,active,courseOptions,navigate);
      else {const data=await api('courses');if(!active())return;courseOptions(data.items);courseCards(target,cid?data.items.filter(row=>row.id===cid):data.items,navigate);}
    } else if(page==='students'&&user.role==='admin'){
      const data=await api('admin/users');if(active())students(target,data.items);
    } else if(page==='enrollments'&&user.role==='admin'){
      await enrollments(target,active,load);
    } else if(page==='grades'&&user.role==='admin'){
      await gradebook(target,cid,load,active);
    } else if(page==='schedule'){
      await schedule(target,prefix,query,active);
    } else if(['assignments','materials','grade_items'].includes(page)||(page==='attendance'&&user.role==='admin')){
      await collectionPage(target,page,cid,prefix,active,load);
    } else if(['grades','attendance'].includes(page)){
      if(!cid){empty(target,'Выберите дисциплину',`Выберите предмет в меню слева, чтобы увидеть ${page==='grades'?'свои оценки':'посещаемость'}.`);return;}
      const data=await api((page==='grades'?'grade':'attendance')+'-summary'+query);if(!active())return;
      if(data.error)throw new Error(data.error);
      if(page==='grades')gradeSummary(target,data);else attendanceSummary(target,data);
    } else if(page==='plan'){
      const result=await api('agent/query',{method:'POST',body:{message:'План подготовки',page:'plan',...(cid?{course_id:cid}:{})}});if(!active())return;
      const plan=result.results?.plan_study?.plan;
      if(plan)studyPlan(target,plan);else empty(target,'План пока недоступен',result.answer||'Проверьте наличие заданий с дедлайнами.');
    } else if(page==='personal'){
      const data=await api('personal');if(!active())return;personalTasks(target,data,prepare);personalForm(target,prepare);
      const form=element('form',undefined,target);form.className='preferences-form';element('h3','Нагрузка на день',form);
      const hours=element('input',undefined,element('label','Часов подготовки в день',form));hours.type='number';hours.min=1;hours.max=8;hours.step='.5';hours.required=true;hours.value=data.preferences.hours_per_day;
      element('button','Изменить нагрузку',form);
      form.addEventListener('submit',event=>{event.preventDefault();if(form.reportValidity())prepare({target:'preferences',payload:{hours_per_day:Number(hours.value)}}).catch(showError);});
    } else if(page==='data')await dataBrowser(target,active);
  }catch(error){if(active())showError(error);}
  finally{loading.remove();if(active()){target.hidden=false;target.removeAttribute('aria-busy');}}
}

function signedIn(actor){user=actor;$('#login-panel').hidden=true;$('#workspace').dataset.role=actor.role;$('#workspace').hidden=false;$('#logout').hidden=false;$('#identity').textContent=actor.name;$('#agent-panel').hidden=actor.role!=='student';
  const available=actor.role==='admin'?['courses','students','enrollments','assignments','grade_items','grades','attendance','materials','schedule','data']:['courses','assignments','materials','grades','attendance','schedule','plan','personal','data'];
  $('#navigation').replaceChildren();for(const name of available){const button=element('button',pages[name],$('#navigation'));button.type='button';button.dataset.page=name;button.addEventListener('click',()=>navigate(name));}navigate('courses');
}
$('#login').addEventListener('submit',async event=>{event.preventDefault();const button=event.currentTarget.querySelector('button');button.disabled=true;const data=new FormData(event.currentTarget);try{const result=await api('auth/login',{method:'POST',body:{username:data.get('username'),password:data.get('password')}});event.target.reset();signedIn(result.user);}catch(error){showError(error);}finally{button.disabled=false;}});
$('#logout').addEventListener('click',async()=>{try{await api('auth/logout',{method:'POST',body:{}});reset();}catch(error){showError(error);}});
$('#course').addEventListener('change',load);
$('#confirm').addEventListener('click',async()=>{if(!pendingProposal)return;$('#confirm').disabled=true;try{await api(pendingProposal.change?.target==='study_plan'?'actions/confirm-plan':'actions/confirm',{method:'POST',body:{proposal:pendingProposal.proposal,confirmed:true}});pendingProposal=null;$('#review').hidden=true;await load();}catch(error){showError(error);}finally{$('#confirm').disabled=false;}});
$('#cancel').addEventListener('click',()=>{pendingProposal=null;$('#review').hidden=true;});
$('#agent-prompts')?.addEventListener('click',event=>{if(event.target.tagName==='BUTTON'){$('#agent textarea').value=event.target.textContent;$('#agent textarea').focus();}});
try{document.documentElement.dataset.theme=localStorage.getItem('campuspulse-theme')||'light';}catch{}
$('#theme').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('campuspulse-theme',theme);}catch{}});
try{const data=await api('status'),model=data.llm||data.vertex;$('#status').textContent=`${data.team_database_connected?'Учебные данные доступны':'Нет подключения к учебным данным'} · ${model?.calls_enabled?'AI-помощник готов':'AI-помощник ожидает настройки'}`;const pill=document.querySelector('.live-pill');if(pill)pill.textContent=data.team_database_connected?'● База подключена':'○ Нет подключения';const option=document.querySelector('#agent select option[value="llm"]');if(option&&model?.model)option.textContent=model.model;}catch(error){showError(error);}
try{const data=await api('me');signedIn(data.user);}catch(error){if(error.status!==401)showError(error);}
