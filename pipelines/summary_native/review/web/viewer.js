"use strict";
const $=id=>document.getElementById(id),state={review:null,items:[],current:null,verdict:null,proposal:null,identityDisposition:null,selected:new Set(),csrf:null,pending:null,pendingAdvance:false,pendingNextId:null},base=new URL("./",location.href).pathname;
const text=(node,value)=>{node.textContent=value==null?"":String(value)};
async function api(path,options={}){const response=await fetch(base+path,options),body=await response.json();if(!response.ok||!body.ok){const e=new Error(body.message||"Request failed");e.code=body.code;throw e}return body.data}
function counts(){const c=state.review.counts;text($("progress"),`${c.settled} of ${c.total} settled${c.stale?`; ${c.stale} stale`:""}`)}
function visible(){const category=$("category").value,hide=$("hide-approved").checked;return state.items.filter(i=>(category==="all"||i.categories.includes(category))&&(!hide||i.disposition!=="approve"))}
function selection(){text($("selected"),`${state.selected.size} selected`);$("save-selected").disabled=!state.selected.size}
function render(){const items=visible(),queue=$("queue");queue.replaceChildren();for(const item of items){const li=document.createElement("li"),check=document.createElement("input"),label=document.createElement("label"),button=document.createElement("button"),status=document.createElement("span");check.type="checkbox";check.checked=state.selected.has(item.item_id);if(!item.item_id.match(/-\d\d/))check.setAttribute("aria-label",`Select ${item.item_id}`);check.onchange=()=>{check.checked?state.selected.add(item.item_id):state.selected.delete(item.item_id);selection()};button.textContent=item.claim_text||item.item_id;button.onclick=()=>openItem(item.item_id);label.append(check,button);li.append(label);const labels={approve:"Approved",reject:"Rejected",discuss:"Discuss",pending:"Pending"},stale=item.freshness==="stale";status.className=`queue-status ${stale?"is-stale":`is-${item.disposition||"pending"}`}`;status.textContent=stale?"Stale — review again":labels[item.disposition]||"Pending";li.append(status);if(item.saved_note_summary&&!stale){const note=document.createElement("span");note.className="queue-note";note.textContent=`Saved note: ${item.saved_note_summary}`;li.append(note)}if(item.rerun){const run=document.createElement("span");run.textContent=` — Rerun ${item.rerun.check_ids.join(", ")} — ${item.rerun.outcome}: ${item.rerun.message}`;li.append(run)}queue.append(li)}text($("filtered"),`${items.length} filtered`);selection()}
function setVerdictSelection(verdict,saved=false){state.verdict=verdict||null;for(const button of document.querySelectorAll("[data-verdict]")){const selected=button.dataset.verdict===verdict;button.classList.toggle("is-selected",selected);button.setAttribute("aria-pressed",String(selected))}const label=verdict?verdict[0].toUpperCase()+verdict.slice(1):"";const status=$("decision-selection");status.classList.toggle("is-saved",Boolean(saved&&verdict));text(status,verdict?`${saved?"Saved decision":"Unsaved selection"}: ${label}.${saved?"":" Save decision to record it."}`:"No decision selected.")}
function clearIdentitySelection(){state.proposal=null;state.identityDisposition=null;for(const button of document.querySelectorAll("#identity button"))button.setAttribute("aria-pressed","false");text($("identity-selection"),"")}
function selectIdentity(disposition,proposal=null,saved=false){clearIdentitySelection();state.identityDisposition=disposition;state.proposal=proposal;if(disposition==="distinct")$("identity-distinct").setAttribute("aria-pressed","true");else if(proposal)document.querySelector(`[data-proposal-id="${CSS.escape(proposal.proposal_id)}"]`)?.setAttribute("aria-pressed","true");text($("identity-selection"),disposition==="distinct"?`${saved?"Saved":"Unsaved"} identity choice: these identities are distinct.`:`${saved?"Saved":"Unsaved"} exact merge proposal: ${proposal?.proposal_digest||"unknown"}.`)}
async function loadDocumentSection(id,offset,append=false){const item=await api(`items/${encodeURIComponent(id)}?section_offset=${offset}`),section=item.document_section;if(!append)text($("document-text"),"");$("document-text").append(document.createTextNode(section.content));text($("document-digest"),`Exact full-document digest: ${section.full_document_sha256}; ${section.total_bytes} bytes`);$("document-more").hidden=section.next_offset===null;$("document-more").onclick=()=>loadDocumentSection(id,section.next_offset,true)}
async function openItem(id){const item=await api(`items/${encodeURIComponent(id)}`);state.current=item;setVerdictSelection(null);clearIdentitySelection();$("queue").hidden=true;$("detail").hidden=true;text($("claim"),item.claim_text||item.failure_context);text($("severity"),item.severity);text($("categories"),item.categories.join(", "));text($("locator"),item.locator.source_path);text($("rationale"),item.rationale);text($("freshness"),item.freshness==="stale"?`${item.stale_reason||"Approval inputs changed."} This approval is no longer current; review again.`:"");text($("rerun"),item.rerun?`Selected checks: ${item.rerun.check_ids.join(", ")}. ${item.rerun.message}`:"");const identity=$("identity"),options=$("identity-options");options.replaceChildren();identity.hidden=item.domain!=="duplicate_identity";text($("identity-application"),item.application?item.application.state==="applied"?`Applied as receipt ${item.application.receipt_id}. Changed: ${item.application.changed_paths.join(", ")||"none"}. Remaining reviewed work: ${item.application.remaining_review_work.join(", ")||"none"}.`:`Approved and waiting for explicit apply (${item.application.proposal_digest}).`:"");for(const proposal of item.identity_proposals||[]){const box=document.createElement("section"),heading=document.createElement("h4"),paths=document.createElement("p"),button=document.createElement("button");heading.textContent=proposal.canonical_registry_name;paths.textContent=`${proposal.applicable?"Applicable":"Blocked"}. ${proposal.blocked_reasons.join(", ")} Affected: ${proposal.affected_paths.join(", ")||"none"}. Inspected: ${proposal.inspected_paths.join(", ")||"none"}. Pending generation: ${proposal.generative_rebuilds.join(", ")||"none"}.`;button.textContent=`Select ${proposal.canonical_registry_name} (${proposal.proposal_digest.slice(0,12)})`;button.className="identity-choice";button.dataset.proposalId=proposal.proposal_id;button.setAttribute("aria-pressed","false");button.disabled=!proposal.applicable;button.onclick=()=>selectIdentity("merge",proposal,false);box.append(heading,paths,button);options.append(box)}const isDocument=item.domain==="grounding_document";$("document").hidden=!isDocument;if(isDocument)await loadDocumentSection(id,0);const evidence=$("evidence");evidence.replaceChildren();for(const entry of item.evidence){const p=document.createElement("p");p.textContent=entry.exact_excerpt||entry.missing_reason||"Missing evidence";evidence.append(p)}$("note").value=item.decision?.note||"";text($("saved-note"),item.decision?.note||"");setVerdictSelection(item.decision?.verdict||null,Boolean(item.decision));if(item.domain==="duplicate_identity"&&item.decision?.disposition==="distinct")selectIdentity("distinct",null,true);else if(item.domain==="duplicate_identity"&&item.decision?.disposition==="merge"){const savedProposal=(item.identity_proposals||[]).find(value=>value.proposal_id===item.decision.proposal_id);if(savedProposal)selectIdentity("merge",savedProposal,true)}text($("save-state"),item.decision?"Saved":"");$("retry").hidden=true;$("reload").hidden=true;$("detail").hidden=false}
function choose(verdict){setVerdictSelection(verdict,false);text($("save-state"),"Decision changed locally; save to record it.")}
function request(){const v=state.verdict;if(v==="approve"&&state.review.kind==="duplicate_identity"&&state.selected.size>1)throw new Error("Review one identity pair at a time");if(v==="approve"&&state.review.kind==="duplicate_identity"&&!state.identityDisposition)throw new Error("Choose an exact merge proposal or confirm the identities are distinct");const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);const requestId=Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join(""),ids=state.selected.size?[...state.selected]:[state.current.item_id];return{version:1,request_id:requestId,review_generation:state.review.generation,reviewer:"GM",decisions:ids.map(id=>{const i=state.items.find(item=>item.item_id===id);return{item_id:i.item_id,item_revision:i.revision,review_digest:i.review_digest,expected_decision_revision:i.decision_revision||0,verdict:v,disposition:v==="approve"?(state.review.kind==="grounding_documents"?"document_signoff":state.review.kind==="duplicate_identity"?state.identityDisposition:"accept_no_change"):v==="reject"?"reject_action":"defer",note:$("note").value,...(v==="approve"&&state.proposal?{proposal_id:state.proposal.proposal_id,proposal_digest:state.proposal.proposal_digest}:{})}})}}
async function advanceNext(){
  const nextId=state.pendingNextId;
  if(!nextId)return;
  try{
    await openItem(nextId);
    state.pendingNextId=null;
    $("retry").textContent="Retry save";
    $("claim").focus();
    $("claim").scrollIntoView({block:"start"});
  }catch(e){
    text($("save-state"),`Saved. Next item could not be loaded: ${e.message}`);
    $("retry").textContent="Retry next item";
    $("retry").hidden=false;
  }
}
async function save(retry=false,advance=false){
  if(!state.verdict&&!state.pending)return;
  state.pendingAdvance=retry?state.pendingAdvance:advance;
  state.pendingNextId=null;
  text($("save-state"),"Saving…");
  $("retry").textContent="Retry save";
  $("retry").hidden=true;
  let payload,nextId;
  try{
    payload=retry?state.pending:request();
    state.pending=payload;
    const order=visible().map(item=>item.item_id),currentIndex=order.indexOf(state.current.item_id),savedIds=new Set(payload.decisions.map(decision=>decision.item_id));
    nextId=state.pendingAdvance?order.slice(currentIndex+1).find(id=>!savedIds.has(id)):null;
    if(!navigator.onLine)throw new Error("offline");
    const shell=await fetch(base);
    if(!shell.ok)throw new Error("review session unavailable");
    state.csrf=shell.headers.get("X-Review-CSRF");
    await api("decisions",{method:"POST",headers:{"Content-Type":"application/json","X-Review-CSRF":state.csrf},body:JSON.stringify(payload)});
    state.pending=null;
    text($("save-state"),`Saved ${payload.decisions.length} decision${payload.decisions.length===1?"":"s"}`);
    text($("saved-note"),payload.decisions[0].note);
    for(const decision of payload.decisions){
      const item=state.items.find(i=>i.item_id===decision.item_id),prior=item.disposition,next=decision.verdict;
      const wasSettled=prior==="approve",isSettled=next==="approve";
      if(!wasSettled&&isSettled){state.review.counts.settled++;state.review.counts.pending--}
      else if(wasSettled&&!isSettled){state.review.counts.settled--;state.review.counts.pending++}
      if(prior!=="pending"){
        const priorKey=prior==="approve"?"approved":prior==="reject"?"rejected":"discussed";
        state.review.counts[priorKey]--;
      }
      item.disposition=next;
      item.decision_revision=(item.decision_revision||0)+1;
      item.saved_note_summary=decision.note;
      state.review.counts[next==="approve"?"approved":next==="reject"?"rejected":"discussed"]++;
    }
    const current=state.items.find(i=>i.item_id===state.current.item_id),saved=payload.decisions[0];
    state.current.decision_revision=current.decision_revision;
    state.current.decision={note:saved.note,verdict:saved.verdict,disposition:saved.disposition,proposal_id:saved.proposal_id};
    setVerdictSelection(saved.verdict,true);
    if(state.review.kind==="duplicate_identity")selectIdentity(state.identityDisposition,state.proposal,true);
    state.selected.clear();
    counts();
    render();
  }catch(e){
    text($("save-state"),e.code==="REVIEW_STALE_DECISION"?"A newer decision changed in another tab.":`Decision was not saved: ${e.message}`);
    $(e.code==="REVIEW_STALE_DECISION"?"reload":"retry").hidden=false;
    return;
  }
  const shouldAdvance=state.pendingAdvance;
  state.pendingAdvance=false;
  if(shouldAdvance&&nextId){state.pendingNextId=nextId;await advanceNext()}
  else if(shouldAdvance)text($("save-state"),"Saved. End of the visible review queue.");
}
async function loadQueue(){state.review=await api("review");state.items=[...state.review.items];let cursor=state.review.next_cursor;while(cursor){const page=await api(`review?cursor=${encodeURIComponent(cursor)}`);state.items.push(...page.items);cursor=page.next_cursor}}
async function boot(){try{const shell=await fetch(base);state.csrf=shell.headers.get("X-Review-CSRF");await loadQueue();for(const c of [...new Set(state.items.flatMap(i=>i.categories))].sort()){const o=document.createElement("option");o.value=c;o.textContent=c.replaceAll("_"," ");$("category").append(o)}text($("title"),state.review.title);text($("transport"),state.review.transport);counts();render()}catch(e){text($("progress"),`Review unavailable: ${e.message}`)}}
$("category").onchange=render;$("hide-approved").onchange=render;$("select-all").onchange=e=>{for(const i of visible())e.target.checked?state.selected.add(i.item_id):state.selected.delete(i.item_id);render()};$("save-selected").onclick=async()=>{const first=[...state.selected][0],size=state.selected.size;if(first){await openItem(first);text($("save-state"),`Batch includes ${size} selected items. Choose one verdict and note, then save.`)}};$("back").onclick=()=>{$("detail").hidden=true;$("queue").hidden=false};$("identity-distinct").setAttribute("aria-pressed","false");$("identity-distinct").onclick=()=>selectIdentity("distinct",null,false);document.querySelectorAll("[data-verdict]").forEach(b=>b.onclick=()=>choose(b.dataset.verdict));$("save").onclick=()=>save(false,false);$("save-next").onclick=()=>save(false,true);$("retry").onclick=()=>state.pendingNextId?advanceNext():save(true,state.pendingAdvance);$("reload").onclick=async()=>{const id=state.current.item_id;await loadQueue();counts();render();await openItem(id)};boot();
