// Recorded data, including model prose, is rendered only with textContent.
// No browser action applies a dossier, calls a model, or issues a payment.
let recoveryCase = 0;
let recoveryStage = 0;

function deskElement(tag, text, className){
  const node = document.createElement(tag);
  if(text !== undefined) node.textContent = String(text);
  if(className) node.className = className;
  return node;
}
function deskAppend(parent, tag, text, className){
  const node = deskElement(tag, text, className);
  parent.appendChild(node);
  return node;
}
function deskTotal(rows){ return rows.reduce((sum,row)=>sum+row.amount_cents,0); }
function deskTime(ts){ return new Date(ts*1000).toISOString().replace('T',' ').replace('Z',' UTC'); }
function deskMetric(parent, label, amount, note){
  const metric = deskAppend(parent, 'div', undefined, 'desk-metric');
  deskAppend(metric, 'small', label);
  deskAppend(metric, 'strong', money(amount));
  deskAppend(metric, 'span', note);
}
function deskRaw(parent, label, data){
  const details = deskAppend(parent, 'details');
  deskAppend(details, 'summary', label);
  deskAppend(details, 'pre', JSON.stringify(data,null,2));
}

function drawRecovery(){
  const current = DEMO.cases[recoveryCase];
  document.getElementById('agent-label').textContent = DEMO.agent;
  const cases = document.getElementById('recovery-cases');
  cases.replaceChildren();
  DEMO.cases.forEach((item,i)=>{
    const button = deskAppend(cases, 'button', undefined, 'tab');
    button.setAttribute('aria-pressed',i===recoveryCase);
    deskAppend(button,'span','Case '+String(i+1).padStart(2,'0'),'case-number');
    deskAppend(button,'span',item.title);
    button.onclick=()=>{recoveryCase=i;recoveryStage=0;drawRecovery();cases.children[i].focus();};
  });
  const story = document.getElementById('recovery-story');
  story.replaceChildren();
  deskAppend(story,'h2',current.title,'case-heading');
  const facts = deskAppend(story,'div',undefined,'case-facts');
  deskAppend(facts,'span','Refund '+money(current.amount_cents));
  deskAppend(facts,'span',current.crash_confirmed ? 'SIGKILL confirmed' : 'Crash unconfirmed');
  deskAppend(facts,'span','Service: no idempotency or lookup');
  deskAppend(facts,'code','Anchor '+current.anchor.slice(0,12));
  const stages = document.getElementById('recovery-stages');
  stages.replaceChildren();
  const labels = ['The process stops',...current.stages.map(stage=>stage.title)];
  labels.forEach((label,i)=>{
    const button=deskAppend(stages,'button',undefined,'stage-button');
    button.setAttribute('aria-pressed',i===recoveryStage);
    deskAppend(button,'span','Step '+String(i+1).padStart(2,'0'));
    deskAppend(button,'strong',label);
    button.onclick=()=>{recoveryStage=i;drawRecovery();stages.children[i].focus();};
  });
  const card = document.getElementById('recovery-step');
  card.replaceChildren();
  if(recoveryStage===0){
    deskAppend(card,'span',current.initial_status,'status-pill held');
    deskAppend(card,'h3','A durable intent. An uncertain outcome.');
    deskAppend(card,'p',current.crash_at==='in_flight'
      ? 'The sandbox processor committed the $50 refund. SIGKILL ended the caller before it could record the acknowledgment.'
      : 'SIGKILL ended the caller after it recorded its intent, before the sandbox processor received a refund.');
    deskAppend(card,'p','The restarted workflow cannot determine which outcome occurred through this service. Belay leaves the refund paused for evidence review.');
    const metrics=deskAppend(card,'div',undefined,'desk-money');
    deskMetric(metrics,'Order value',current.amount_cents,'Persisted in the workflow');
    deskMetric(metrics,'Processor ledger',deskTotal(current.ledger_initial),'Experiment observer only');
    deskMetric(metrics,'Recovery issued',0,'No retry under uncertainty');
    deskAppend(card,'h4','Who knows what');
    deskAppend(card,'p','The ledger above is visible to the experiment grader. The recovery agent receives only the journaled intent, the evidence catalog, and the records it asks to fetch.');
    deskRaw(card,'Inspect initial sandbox payment records',current.ledger_initial);
  }else{
    const stage=current.stages[recoveryStage-1];
    const dossier=stage.dossier;
    const held=stage.grade==='abstained'||stage.grade==='refused';
    const outcomeLabels = {
      none: 'Held for evidence',
      closed_from_evidence: 'Verified from evidence',
      completed: 'Refund completed',
      refused: 'Permission revoked',
      inconsistent: 'Review required',
    };
    deskAppend(card,'span',outcomeLabels[stage.applied.action]||stage.applied.action.replaceAll('_',' '),
      'status-pill'+(stage.grade==='false'?' bad':held?' held':''));
    deskAppend(card,'h3',stage.title);
    deskAppend(card,'p',stage.agent+' · '+stage.elapsed_ms+' ms adjudication','desk-caption');
    const metrics=deskAppend(card,'div',undefined,'desk-money');
    deskMetric(metrics,'Paid before review',deskTotal(stage.ledger_before),'Sandbox processor ledger');
    deskMetric(metrics,'Issued by recovery',deskTotal(stage.ledger_after)-deskTotal(stage.ledger_before),'Actual ledger difference');
    deskMetric(metrics,'Paid after review',deskTotal(stage.ledger_after),stage.ledger_after.length+' refund record(s)');
    deskAppend(card,'h4','1 / Evidence fetched');
    if(!stage.observations.length) deskAppend(card,'p','No verified observations are available.');
    stage.observations.forEach(obs=>{
      const item=deskAppend(card,'div',undefined,'desk-evidence');
      deskAppend(item,'code',obs.pointer+' · digest '+obs.digest);
      const coverage=obs.payload.coverage;
      if(coverage && coverage.cutoff_ts!==undefined && coverage.cutoff_ts!==null){
        const covered=coverage.cutoff_ts>=stage.intent_ts;
        deskAppend(item,'p','Complete through '+deskTime(coverage.cutoff_ts),'coverage'+(covered?'':' stale'));
        deskAppend(item,'p',(covered?'Covers':'Does not cover')+' the latest intent at '+deskTime(stage.intent_ts),'coverage'+(covered?'':' stale'));
      }
      if(Array.isArray(obs.payload.matches)){
        deskAppend(item,'p',obs.payload.matches.length
          ? obs.payload.matches.map(r=>'Refund '+money(r.amount_cents)+' · receipt '+r.external_id).join('; ')
          : 'No matching refund records. Silence requires sufficient coverage before it proves absence.');
      }
    });
    deskAppend(card,'h4','2 / Agent proposes; verifier decides');
    const reason=deskAppend(card,'div',undefined,'desk-reason');
    deskAppend(reason,'p','Agent claim: '+(stage.claim?stage.claim.verdict:'no claim returned'));
    (stage.claim?.reasoning||[]).forEach(line=>deskAppend(reason,'p',line));
    deskAppend(reason,'p','Verified verdict: '+dossier.verdict);
    dossier.validator_notes.forEach(line=>deskAppend(reason,'p',line));
    deskAppend(card,'h4','3 / Recorded execution outcome');
    if(stage.permission_revoked_after_proposal){
      deskAppend(card,'p',stage.applied.action==='refused'
        ? 'payments:refund was revoked after this proposal and before execution. The execution-time permission check saw the revocation.'
        : 'payments:refund was revoked after this proposal. No completion was attempted; the proposal did not reach the execution-time permission check.');
    }
    deskAppend(card,'p',stage.applied.note);
    deskAppend(card,'p','Ledger check: '+stage.why+'.');
    deskAppend(card,'p',stage.workflow_after_resume
      ? 'Workflow status after resume: '+stage.workflow_after_resume+'.'
      : 'The workflow was not resumed; the refund remains paused.');
    deskRaw(card,'Inspect pointers, citations, and the verified dossier',{
      pointers:stage.pointers,observations:stage.observations,claim:stage.claim,dossier,
    });
    deskRaw(card,'Inspect recorded journal and payment records',{
      journal:stage.journal,ledger_before:stage.ledger_before,ledger_after:stage.ledger_after,
    });
    if(stage.model_metrics) deskRaw(card,'Inspect model request metrics',stage.model_metrics);
  }
  const assumptions=document.getElementById('recovery-assumptions');
  assumptions.replaceChildren();
  DEMO.assumptions.forEach(note=>deskAppend(assumptions,'p',note));
  deskAppend(assumptions,'p','Captured '+DEMO.recorded_at+'. Each case starts from an isolated sandbox copy.');
}
drawRecovery();
