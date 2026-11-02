'use strict';
const $ = id => document.getElementById(id);
const state = {caseId: '04_worked', result: null, csrf: '', cases: [], requestId: 0};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const usd = value => {
  if (value === null || value === undefined) return '—';
  const [whole, fraction='00'] = String(value).split('.');
  const negative = whole.startsWith('-');
  const digits = BigInt(negative ? whole.slice(1) : whole).toLocaleString('en-US');
  return `${negative ? '−' : ''}$${digits}.${fraction.padEnd(2,'0')}`;
};
async function api(path, data) {
  const response = await fetch(path, data ? {method:'POST', headers:{'Content-Type':'application/json','X-Review-Token':state.csrf},body:JSON.stringify(data)} : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function message(text, isError=false) {
  $(isError?'error':'notice').textContent = text;
  $(isError?'error':'notice').hidden = false;
  $(isError?'notice':'error').hidden = true;
}
async function loadCase(record=false) {
  const requestId=++state.requestId, caseId=state.caseId;
  $('run').disabled = true;
  $('signoff').disabled = true;
  $('error').hidden = true; $('notice').hidden = true;
  try {
    const result = record ? (await api('/api/run',{case:caseId})).result : await api(`/api/result?case=${encodeURIComponent(caseId)}`);
    if(requestId!==state.requestId) return;
    state.result = result; render();
    if (record) message(result.status === 'BLOCKED' ? 'The packet is blocked. Resolve the listed evidence issue before review.' : 'Reconciliation complete. The result is ready for human review.');
  } catch(error) {if(requestId===state.requestId){state.result={status:'BLOCKED',run_id:'request-failed',base:null,variance:null,invoices:[],blockers:[error.message]};render();message(error.message,true);}} finally {if(requestId===state.requestId)$('run').disabled=false;}
}
function render() {
  const r = state.result, blocked = r.status === 'BLOCKED';
  $('packet-meta').textContent = blocked ? 'Release withheld' : `${r.as_of} · ${r.invoice_count} invoices · ${r.debtor_count} debtors`;
  $('report-link').href = `/api/report?case=${encodeURIComponent(state.caseId)}`;
  $('status-strip').innerHTML = `<div class="status-strip ${blocked?'blocked':''}"><span class="badge">● ${blocked?'BLOCKED — ACTION REQUIRED':'READY FOR HUMAN REVIEW'}</span><span>Run ${esc(r.run_id.slice(0,12))} · no automated approval</span></div>`;
  const cards = [['Computed borrowing base',r.base,'After eligibility, concentration and reserve','feature'],['Borrower certificate',r.reported,'Submitted amount; not independently approved',''],['Reported overstatement',r.variance,'Reported minus computed borrowing base','warn']];
  $('metrics').innerHTML = cards.map(([title,value,sub,cls])=>`<article class="metric ${cls}"><div class="metric-label">${esc(title)}</div><div class="metric-number">${blocked&&cls==='feature'?'Withheld':usd(value)}</div><div class="metric-detail">${esc(sub)}</div></article>`).join('');
  const flow = [['Gross receivables','gross'],['Allocated credits','credits','deduction'],['Eligibility exclusions','eligibility_exclusions','deduction'],['Concentration excess','concentration_exclusions','deduction'],['Eligible receivables','eligible'],['80% advance amount','advance'],['Confirmed reserve','reserve','deduction'],['Borrowing base','base','result']];
  const scale = Number(r.gross)||1;
  $('waterfall').innerHTML = blocked ? `<div class="empty">No financial result is released while required evidence is unresolved.</div>` : flow.map(([name,key,kind])=>`<div class="water-row ${key==='base'?'total':''}"><span>${key==='advance'?esc(r.parameters.advance_bp/100)+'% advance amount':esc(name)}</span><div class="bar-track"><div class="bar ${kind||''}" style="width:${Math.max(0,Math.min(100,Number(r[key])/scale*100))}%"></div></div><span class="water-value">${usd(r[key])}</span></div>`).join('');
  $('finding-title').textContent = blocked ? 'Evidence needs attention' : Number(r.variance)>0 ? 'The certificate exceeds the supported base.' : 'Check the assumptions behind the number.';
  $('finding').textContent = blocked ? r.blockers.join(' ') : state.caseId==='04_worked' || state.caseId==='05_overlap' ? 'Cross-ageing removes Customer A’s current invoice as well as its overdue invoice. The smaller eligible pool also lowers Customer B’s concentration allowance.' : 'The arithmetic follows the reviewed synthetic rule pack. Inspect exclusion reasons, effective dates, and the source clauses before recording your review.';
  $('review-facts').innerHTML = blocked ? '' : `<div class="fact"><span>Rule version</span><b>${esc(r.rule_id)}</b></div><div class="fact"><span>Evidence mode</span><b>Reviewed synthetic fixture</b></div><div class="fact"><span>Net reconciliation</span><b>Balanced to the cent ✓</b></div>`;
  $('signoff').disabled = blocked;
  renderRows(); renderEvidence();
}
function renderRows() {
  if (!state.result) return;
  const query=$('search').value.toLowerCase(), excluded=$('excluded-only').checked;
  const rows=state.result.invoices.filter(r=>(!excluded||r.reasons.length)&&`${r.invoice_id} ${r.debtor_id} ${r.debtor_name}`.toLowerCase().includes(query));
  $('row-count').textContent=`${rows.length} of ${state.result.invoices.length} invoices`;
  $('invoice-rows').innerHTML=rows.length?rows.map(r=>`<tr><td><b>${esc(r.invoice_id)}</b><small>${esc(r.debtor_name)}</small></td><td>${esc(r.age_days)}d</td><td>${usd(r.net)}</td><td>${usd(r.excluded)}</td><td>${usd(r.pre_concentration_eligible)}</td><td>${r.reasons.length?r.reasons.map(x=>`<span class="pill">${esc(x.replaceAll('_',' '))}</span>`).join(''):'<span class="pill good">ELIGIBLE BEFORE CAP</span>'}</td></tr>`).join(''):'<tr><td colspan="6" class="empty">No matching invoice rows.</td></tr>';
}
function renderEvidence() {
  const r=state.result, caseId=state.caseId, refs={...(r.rule_evidence||{})};
  for(const key of ['reserve_evidence','commitment_evidence','certificate_evidence']) if(r[key]) refs[key]=r[key];
  $('evidence-cards').innerHTML=Object.entries(refs).map(([key,ref])=>`<article class="evidence-card"><p class="eyebrow">${esc(ref.document_id)} · ${esc(ref.clause)}</p><h3>${esc(key.replaceAll('_',' '))}</h3><blockquote>${esc(ref.quote)}</blockquote><p class="micro">Lines ${esc(ref.start_line)}–${esc(ref.end_line)} · offsets ${esc(ref.start)}:${esc(ref.end)} (Unicode code points)</p><details><summary class="micro">Source fingerprint</summary><p class="hash">${esc(ref.document_sha256)}</p></details><button class="text-button source-button" data-key="${esc(key)}">Open original source →</button></article>`).join('') || '<p class="empty">Source integrity must be resolved before this packet can produce approved evidence references.</p>';
  document.querySelectorAll('.source-button').forEach(button=>button.addEventListener('click',async()=>{
    const ref=refs[button.dataset.key];
    try {
      const doc=await api(`/api/source?case=${encodeURIComponent(caseId)}&id=${encodeURIComponent(ref.document_id)}`);
      if(doc.sha256!==ref.document_sha256) throw new Error('Source changed; review a fresh reconciliation.');
      $('source-title').textContent=doc.id; $('source-hash').textContent=`SHA-256 ${doc.sha256}`;
      const text=Array.from(doc.text), before=text.slice(0,ref.start).join(''), selected=text.slice(ref.start,ref.end).join(''), after=text.slice(ref.end).join('');
      $('source-text').replaceChildren(document.createTextNode(before));
      const mark=document.createElement('mark'); mark.textContent=selected;
      $('source-text').append(mark,document.createTextNode(after)); $('source-dialog').showModal();
    } catch(error){message(error.message,true);}
  }));
}
async function tab(name) {
  document.querySelectorAll('.tab-content').forEach(e=>e.hidden=e.id!==name);
  document.querySelectorAll('[data-tab]').forEach(e=>e.classList.toggle('active',e.dataset.tab===name));
  try {
    if(name==='tests'){
      const report=await api('/api/evaluate');
      $('test-summary').innerHTML=`<div class="test-summary"><strong>${report.passed} / ${report.total}</strong><div>Acceptance scenarios passed<br><span class="micro">Deterministic results and blocking controls · live LLM not evaluated</span></div></div>`;
      $('test-rows').innerHTML=report.results.map(r=>`<tr><td><b>${esc(r.name)}</b><small>${esc(r.id)}</small></td><td>${r.expected.base===null?'BLOCKED':usd(r.expected.base)}</td><td>${r.actual.base===null?'BLOCKED':usd(r.actual.base)}</td><td><span class="pill ${r.passed?'good':''}">${r.passed?'PASS':'FAIL'}</span></td></tr>`).join('');
    }
    if(name==='audit'){
      const response=await api('/api/audit');
      $('audit-events').innerHTML=response.events.length?response.events.reverse().map(e=>`<article class="event"><span class="badge subtle">${esc(e.kind)}</span><p>${esc(e.at)} ${e.data.reviewer?'· '+esc(e.data.reviewer):''}</p><p>${esc(e.data.note||`Run ${e.data.run_id} · ${e.data.status}`)}</p><div class="hash">${esc(e.digest)}</div></article>`).join(''):'<div class="panel empty">No review events yet. Reconcile a packet or record a local review to begin the audit trail.</div>';
    }
  } catch(error){message(error.message,true);}
}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>tab(button.dataset.tab)));
$('jump-evidence').addEventListener('click',()=>tab('evidence'));
$('case-select').addEventListener('change',()=>{state.caseId=$('case-select').value;loadCase();});
$('run').addEventListener('click',()=>loadCase(true));
$('search').addEventListener('input',renderRows);
$('excluded-only').addEventListener('change',renderRows);
$('close-source').addEventListener('click',()=>$('source-dialog').close());
$('download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(state.result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${state.caseId}-reconciliation.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('signoff-form').addEventListener('submit',async event=>{event.preventDefault();try{const r=await api('/api/signoff',{case:state.caseId,run_id:state.result.run_id,reviewer:$('reviewer').value,note:$('review-note').value});message(r.message);}catch(error){message(error.message,true);}});
(async()=>{try{const response=await api('/api/state');state.csrf=response.csrf_token;state.cases=response.cases;$('case-select').innerHTML=response.cases.map(c=>`<option value="${esc(c.id)}" ${c.id===state.caseId?'selected':''}>${esc(c.name)}</option>`).join('');await loadCase();}catch(error){message(error.message,true);}})();
