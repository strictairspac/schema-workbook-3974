import {api,download} from './api/client.js';import {relationsStore} from './stores/relations.js';import {dependenciesStore} from './stores/dependencies.js';import {reportsStore} from './stores/reports.js';import {verificationsStore} from './stores/verifications.js';import {samplesStore} from './stores/samples.js';import {samplesApi} from './api/samples.js';import {verificationsApi} from './api/verifications.js';import {session} from './hooks/session.js';import {feedback} from './hooks/feedback.js';import {formValues} from './utils/forms.js';import {esc,date} from './utils/html.js';import {frame} from './components/common/frame.js';import {table} from './components/common/table.js';import {loginPage} from './pages/login.js';import {relationsPage} from './pages/relations.js';import {dependenciesPage} from './pages/dependencies.js';import {verificationPage} from './pages/verification.js';import {reportsPage} from './pages/reports.js';import {evidencePage} from './pages/evidence.js';import {titles} from './router/routes.js';
let timer=null;const app=document.querySelector('#app');const split=s=>s.split(/[,，]/).map(x=>x.trim()).filter(Boolean);
function bindForm(id,path,transform,after){document.querySelector(id)?.addEventListener('submit',async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{let data=transform(formValues(e.target));const ident=data.id;delete data.id;const result=await api(path+(ident?'/'+ident:''),ident?'PUT':'POST',data);await after(result);feedback('保存成功，业务记录已更新。')}catch(err){feedback(err.message,true)}finally{b.disabled=false}})}
async function render(){clearTimeout(timer);if(!session.token){app.innerHTML=loginPage();bindForm('#login','/auth/login',x=>x,async x=>{session.save(x);location.hash='relations';await render()});return}
try{await api('/auth/me');await Promise.all([relationsStore.refresh(),dependenciesStore.refresh(),reportsStore.refresh(),verificationsStore.refresh()]);const [page='relations',id]=location.hash.slice(1).split('/');const rel=relationsStore.items,deps=dependenciesStore.items,reports=reportsStore.items,verifications=verificationsStore.items;let content,report;let selectedRelationId=id?Number(id):null;
if(page==='dependencies')content=dependenciesPage(deps,rel,verifications);
else if(page==='verification'){
  if(!selectedRelationId)selectedRelationId=rel[0]?.id;
  const samples=selectedRelationId?await samplesApi.list(selectedRelationId):[];
  samplesStore.items=samples;samplesStore.relationId=selectedRelationId;
  content=verificationPage(verifications,rel,samples,selectedRelationId);
}
else if(page==='reports')content=reportsPage(reports,rel);else if(page==='evidence'){report=id?await api('/reports/'+id):reports[0];content=evidencePage(report)}else if(page==='audit'){const rows=await api('/audit');content=table(['时间','操作人','动作'],rows.map(x=>[date(x.created_at),esc(x.actor),esc(x.action)]))}else content=relationsPage(rel);
const [title,subtitle]=titles[page]||titles.relations;app.innerHTML=frame(page,title,subtitle,content);document.querySelector('#logout').onclick=()=>{session.clear();render()};
bindForm('#relation-form','/relations',x=>({...x,attributes:split(x.attributes)}),render);
bindForm('#dependency-form','/dependencies',x=>({...x,relation_id:Number(x.relation_id),lhs:split(x.lhs),rhs:split(x.rhs)}),render);
bindForm('#report-form','/reports',x=>({...x,relation_id:Number(x.relation_id)}),async x=>{location.hash='evidence/'+x.id;await render()});
bindSampleForms(rel,verifications);
document.querySelectorAll('.edit-dependency').forEach(b=>b.onclick=()=>{const d=deps.find(x=>x.id===Number(b.dataset.id)),form=document.querySelector('#dependency-form');for(const key of ['id','relation_id','lhs','rhs','note'])form.elements[key].value=Array.isArray(d[key])?d[key].join(','):d[key];document.querySelector('#dependency-heading').textContent='修改业务依赖 #'+d.id;form.scrollIntoView({behavior:'smooth',block:'center'})});
document.querySelector('#export')?.addEventListener('click',async e=>{try{await download(e.target.dataset.id);feedback('报告JSON已下载')}catch(err){feedback(err.message,true)}});
if((page==='evidence'&&report&&['queued','running'].includes(report.status))||(page==='reports'&&reports.some(x=>['queued','running'].includes(x.status))))timer=setTimeout(render,1500);
}catch(err){if(err.message.includes('登录')||err.message.includes('Not authenticated')){session.clear();await render()}else{if(!document.querySelector('#feedback'))app.innerHTML='<main><div id="feedback"></div><button onclick="location.reload()">重新加载</button></main>';feedback(err.message,true)}}}
function bindSampleForms(relations,verifications){
  const picker=document.querySelector('#verify-relation');
  if(picker)picker.onchange=()=>{location.hash='verification/'+picker.value;};
  const form=document.querySelector('#sample-form');
  if(form)form.addEventListener('submit',async e=>{
    e.preventDefault();const b=form.querySelector('button');b.disabled=true;
    try{
      const raw=formValues(form);const relationId=Number(raw.relation_id);
      const relation=relations.find(r=>r.id===relationId);
      const values={};for(const attr of relation.attributes){const v=raw['attr:'+attr];values[attr]=v===undefined||v===''?null:v;}
      const payload={relation_id:relationId,label:raw.label,values};
      if(raw.id)await samplesApi.update(Number(raw.id),{label:raw.label,values});else await samplesApi.create(payload);
      feedback('样本已保存，相关核验结论的版本已更新。');await render();
    }catch(err){feedback(err.message,true);}finally{b.disabled=false;}
  });
  document.querySelectorAll('.edit-sample').forEach(btn=>btn.onclick=async()=>{
    const sample=samplesStore.items.find(x=>x.id===Number(btn.dataset.id));const form=document.querySelector('#sample-form');
    form.elements.id.value=sample.id;form.elements.label.value=sample.label;
    const relation=relations.find(r=>r.id===sample.relation_id);
    for(const attr of relation.attributes){const el=form.elements['attr:'+attr];if(el)el.value=sample.values[attr]??'';}
    document.querySelector('#sample-heading').textContent='更正委托样本 #'+sample.id;
    form.scrollIntoView({behavior:'smooth',block:'center'});
  });
  document.querySelectorAll('.remove-sample').forEach(btn=>btn.onclick=async()=>{
    if(!confirm('移除该委托样本？相关核验结论将因源数据变化而失效。'))return;
    try{await samplesApi.remove(Number(btn.dataset.id));feedback('样本已移除，旧核验结论已失效。');await render();}
    catch(err){feedback(err.message,true);}
  });
  document.querySelectorAll('.act-verify').forEach(btn=>btn.onclick=async()=>{
    try{const r=await verificationsApi.verify(Number(btn.dataset.id));feedback('核验完成：'+({pending:'待核验（样本为空）',adoptable:'可采纳',conflict:'存在冲突反例',adopted:'已采纳'}[r.verify_status]||r.verify_status));await render();}
    catch(err){feedback(err.message,true);}
  });
  document.querySelectorAll('.act-adopt').forEach(btn=>btn.onclick=async()=>{
    try{await verificationsApi.adopt(Number(btn.dataset.id));feedback('已采纳为正式依赖，后续样本写入将受其约束。');await render();}
    catch(err){feedback(err.message,true);}
  });
}
window.addEventListener('hashchange',render);render();
