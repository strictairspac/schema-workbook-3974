import {verifyBadge} from '../components/common/badge.js';
import {esc} from '../utils/html.js';
import {session} from '../hooks/session.js';
import {VERIFY_STATES,VERIFY_HINT} from '../constants/enums.js';

const fd=(lhs,rhs)=>`${esc(lhs.length?lhs.join(', '):'∅')} → ${esc(rhs.join(', '))}`;
const canWrite=()=>session.user.role!=='viewer';

function counterexampleBlock(dep){
  if(dep.verify_status!=='conflict'||!dep.counterexamples?.length)return '';
  return `<div class="ce-box"><h4>反例行（可定位）· ${dep.counterexamples.length} 组</h4>${dep.counterexamples.map(ce=>`
    <div class="ce-row"><span class="ce-tag">${esc(ce.attribute)}</span>
      样本 <b>#${ce.sample_a.id} ${esc(ce.sample_a.label)}</b> 取值 <code>${esc(String(ce.values[ce.sample_a.label]))}</code>
      与 <b>#${ce.sample_b.id} ${esc(ce.sample_b.label)}</b> 取值 <code>${esc(String(ce.values[ce.sample_b.label]))}</code> 冲突
      <small>决定项取值：${Object.keys(ce.lhs).length?esc(Object.entries(ce.lhs).map(([k,v])=>`${k}=${v??'空（未知）'}`).join('；')):'∅（空决定项，全体已知值须相同）'}</small>
    </div>`).join('')}</div>`;
}

function depCard(dep,relation,stale){
  const disabled=canWrite()?'':'disabled';
  return `<article class="dep-card ${esc(dep.verify_status)}">
    <div class="dep-head"><div><h3>${fd(dep.lhs,dep.rhs)}</h3><small>${esc(relation?.code||'')} · 依赖 #${dep.id} · 样本 ${dep.sample_count} 条</small></div>
      ${verifyBadge(dep.verify_status)}${stale?'<span class="stale-tag">结论已失效</span>':''}</div>
    <p class="dep-hint">${esc(VERIFY_HINT[dep.verify_status]||'')}${stale?' 源数据在核验后发生变化，旧结论已失效，采纳将被拒绝，请重新核验。':''}</p>
    ${counterexampleBlock(dep)}
    <div class="dep-actions">
      <button class="small act-verify" data-id="${dep.id}" ${disabled}>核验全体样本</button>
      <button class="small primary act-adopt" data-id="${dep.id}" ${disabled} ${dep.verify_status==='adopted'?'disabled':''}>${dep.verify_status==='adopted'?'已采纳（重复采纳不登记）':'采纳为正式依赖'}</button>
    </div></article>`;
}

function sampleTable(samples,relation){
  if(!relation)return '<div class="empty">请先选择一个关系草案。</div>';
  const attrs=relation.attributes;
  const head=['标签',...attrs,'操作'];
  const rows=samples.map(s=>[esc(s.label),...attrs.map(a=>s.values[a]===null||s.values[a]===undefined?'<span class="null-cell">空（未知）</span>':esc(String(s.values[a]))),
    `<button class="small edit-sample" data-id="${s.id}" ${canWrite()?'':'disabled'}>更正</button>
     <button class="small danger remove-sample" data-id="${s.id}" ${canWrite()?'':'disabled'}>移除</button>`]);
  const table=samples.length
    ?`<div class="table-wrap"><table><thead><tr>${head.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(x=>`<td>${x}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
    :'<div class="empty">该关系还没有委托样本。空样本不允许采纳，请先在右侧录入。</div>';
  return table;
}

export function verificationPage(verifications,relations,samples,selectedRelationId){
  const relation=relations.find(r=>r.id===Number(selectedRelationId))||relations[0];
  const relId=relation?.id;
  const shown=verifications.filter(d=>!relId||d.relation_id===relId);
  const staleOf=Object.fromEntries(verifications.map(d=>[d.id,d.stale]));
  return `<div class="split"><section>
    <div class="section-top"><h2>规则核验台</h2><span>SAMPLE-BASED FD CHECK</span></div>
    <label class="rel-picker">选择关系草案
      <select id="verify-relation">${relations.map(r=>`<option value="${r.id}" ${r.id===relId?'selected':''}>${esc(r.code)} · ${esc(r.title)}</option>`).join('')}</select>
    </label>
    <div class="dep-grid">${shown.length?shown.map(d=>depCard(d,relation,staleOf[d.id])).join(''):'<div class="empty">该关系还没有登记函数依赖。</div>'}</div>
    <div class="section-top" style="margin-top:28px"><h2>委托样本（${samples.length}）</h2><span>空值 = 未知，不相等</span></div>
    ${sampleTable(samples,relation)}
    <div class="notice">核验只表示“当前样本支持”，不证明依赖恒真；样本变化会使旧结论失效。已采纳规则会约束后续写入，违反时整批拒绝。</div>
  </section>
  <section class="form-panel">
    <span class="eyebrow">DELEGATION SAMPLE</span>
    <h2 id="sample-heading">录入委托样本</h2>
    <form id="sample-form">
      <input type="hidden" name="id"><input type="hidden" name="relation_id" value="${relId||''}">
      <label>定位标签（如 委托 W1 · 拉伸）<input name="label" required maxlength="120" placeholder="委托 W1 · 拉伸"></label>
      <div class="sample-fields">${(relation?.attributes||[]).map(a=>`<label>${esc(a)}<input name="attr:${esc(a)}" placeholder="留空表示未知（null）"></label>`).join('')}</div>
      <button class="primary" ${canWrite()?'':'disabled'}>保存样本 +</button>
    </form>
    <p class="help">留空的属性以 null 保存，核验时视为“未知”：既不与任何值相等，也不构成反例。标签用于在反例提示中定位具体委托行。</p>
  </section></div>`;
}
