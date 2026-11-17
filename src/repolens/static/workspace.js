"use strict";
const $ = id => document.getElementById(id);
const terminal = new Set(["succeeded", "partial", "failed", "cancelled"]);
const statuses = {queued:"等待中",running:"调查中",succeeded:"已完成",partial:"部分完成",failed:"失败",cancelled:"已取消"};
const state = {actions:new Map(),refreshEpochs:new Map(),appliedRefreshes:new Map(),refreshSequence:0,task:null, report:null, snapshot:null, events:new Map(), evidence:new Map(), source:null, poll:null, reconnect:null, generation:0, cursor:0, evidenceRequest:0, loading:false,submitting:false,retrievalConfigured:false,rerankConfigured:false};
const intentStorage = "repolens.pendingIntent.v1";

function configureSource(clearInactive=false){
  const github=$("repository-source").value==="github";
  $("local-source-fields").hidden=github;
  $("github-source-fields").hidden=!github;
  $("repo-path").disabled=github;$("repo-path").required=!github;
  $("github-url").disabled=!github;$("github-url").required=github;
  $("github-ref").disabled=!github;
  if(clearInactive){
    if(github)$("repo-path").value="";
    else{$("github-url").value="";$("github-ref").value="";}
    $("import-status").textContent="";
  }
}
$("repository-source").onchange=()=>configureSource(true);
function submissionControls(busy){
  state.submitting=busy;
  for(const id of ["repository-source","repo-path","github-url","github-ref","analysis-mode","retrieval-mode","enable-rerank","context-compression","document-urls","render-pages","question","submit-analysis"])$(id).disabled=busy;
  if(!busy){configureSource();configureRetrieval();}
}
const githubErrors={
  github_rate_limited:"GitHub 请求被限流，请稍后重试（github_rate_limited）。",
  github_repository_not_found:"公开仓库不存在或不可匿名访问（github_repository_not_found）。",
  github_ref_not_found:"没有找到指定分支、标签或 commit（github_ref_not_found）。",
  github_network_error:"GitHub 网络连接失败（github_network_error）。",
  github_import_timeout:"GitHub 导入超过时间限制（github_import_timeout）。",
  github_blob_mismatch:"归档源码与固定 commit 不一致，已停止导入（github_blob_mismatch）。",
  github_tree_truncated:"GitHub 返回的文件树不完整，请选择更小的仓库（github_tree_truncated）。",
  invalid_github_url:"请输入完整的公开 GitHub 仓库 HTTPS 地址，不要附带 tree/blob 页面路径。"
};
function restoreIntent(){
  const intent=pendingIntent();
  if(intent?.descriptor.kind==="new"||intent?.descriptor.kind==="github"){
    const descriptor=intent.descriptor,github=descriptor.kind==="github";
    $("repository-source").value=github?"github":"local";configureSource();
    if(github){$("github-url").value=descriptor.url;$("github-ref").value=descriptor.ref||"";}
    else $("repo-path").value=descriptor.path;
    $("question").value=descriptor.question;$("analysis-mode").value=descriptor.mode||"single";$("retrieval-mode").value=descriptor.retrieval_mode||"keyword";$("enable-rerank").checked=descriptor.rerank||false;$("context-compression").checked=descriptor.context_compression||false;configureRetrieval();
    $("document-urls").value=(descriptor.document_urls||[]).join("\n");$("render-pages").checked=descriptor.render_pages||false;configureRetrieval();
    $("import-status").textContent="上次提交尚未确认，点击开始分析将复用同一请求，不重复创建任务。";
  }else if(intent?.descriptor.kind==="followup")$("followup-question").value=intent.descriptor.question;
}
function appendGitHubLink(item){
  const snapshot=state.snapshot;
  if(snapshot?.source_type!=="github"||!/^https:\/\/github\.com\/[a-z0-9-]+\/[a-z0-9_.-]+$/.test(snapshot.source)||!(/^[a-f0-9]{40}$/).test(item.commit_sha))return;
  const link=node("a","在 GitHub 查看固定版本源码","source-link");
  link.href=`${snapshot.source}/blob/${item.commit_sha}/${item.path.split("/").map(encodeURIComponent).join("/")}#L${item.start_line}-L${item.end_line}`;
  link.target="_blank";link.rel="noopener noreferrer";$("evidence-meta").append(link);
}

function pendingIntent(){try{return JSON.parse(sessionStorage.getItem(intentStorage)||"null");}catch{return null;}}
function storeIntent(intent){sessionStorage.setItem(intentStorage,JSON.stringify(intent));}
function normalizeDescriptor(d){return Object.fromEntries(Object.entries({...d,mode:d.mode||"single",retrieval_mode:d.retrieval_mode||"keyword",rerank:d.rerank||false,context_compression:d.context_compression||false,document_urls:d.document_urls||[],render_pages:d.render_pages||false,document_ids:d.document_ids||[]}).sort(([a],[b])=>a.localeCompare(b)));}
function intentFor(descriptor){const old=pendingIntent();if(old&&JSON.stringify(normalizeDescriptor(old.descriptor))===JSON.stringify(normalizeDescriptor(descriptor)))return old;const intent={descriptor,key:crypto.randomUUID(),importKey:crypto.randomUUID(),snapshot_id:descriptor.snapshot_id||null};storeIntent(intent);return intent;}
function acknowledgeIntent(intent){if(pendingIntent()?.key===intent.key)sessionStorage.removeItem(intentStorage);}
function invalidateTaskRefresh(id){state.refreshEpochs.set(id,(state.refreshEpochs.get(id)||0)+1);}
async function finishTaskAction(id){
  invalidateTaskRefresh(id);
  try{
    if(state.task?.id===id&&!state.loading){
      const currentGeneration=state.generation;
      try{await refreshTask(id,currentGeneration);}
      catch(e){if(currentGeneration===state.generation&&state.task?.id===id)showError(e.message);}
    }
  }finally{
    state.actions.delete(id);
    if(state.task?.id===id){updateTask(state.task);taskControls(state.loading);}
  }
}
function canCancelTask(task){return !!task&&!task.cancel_requested&&!state.actions.has(task.id)&&(!terminal.has(task.status)||(task.status==="partial"&&task.resume_available));}
function taskControls(loading){state.loading=loading;$("resume-task").disabled=loading||!state.task?.resume_available||state.actions.has(state.task?.id);$("cancel-task").disabled=loading||!canCancelTask(state.task);for(const control of $("followup-form").querySelectorAll("input,button"))control.disabled=loading||!state.task;}
const errorLabels = {model_not_configured:"未配置模型。请在本地配置模型名称、API 地址和密钥后重启服务。",interrupted:"上次进程退出中断了分析，请新建任务。",outside_workspace:"仓库不在允许的工作目录内。",provider_unavailable:"模型服务不可用（provider_unavailable）。",idempotency_conflict:"此提交标识已用于其他请求。",snapshot_not_ready:"仓库仍在导入或导入失败。"};
function node(tag, text, className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function showError(code){$("error-message").textContent=errorLabels[code]||githubErrors[code]||`操作失败：${code}`;$("error-message").hidden=false;}
function clearError(){$("error-message").hidden=true;}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{"Content-Type":"application/json",...options.headers}});let data;try{data=await response.json();}catch{throw new Error(`http_${response.status}`);}if(!response.ok)throw new Error(data.error_code||`http_${response.status}`);return data;}
function stopConnections(){if(state.source)state.source.close();state.source=null;clearInterval(state.poll);clearTimeout(state.reconnect);state.poll=null;}
function newAnalysis(){$("document-urls").value="";$("render-pages").checked=false;$("analysis-mode").value="single";$("context-compression").checked=false;$("retrieval-mode").value="keyword";$("enable-rerank").checked=false;configureRetrieval();state.generation++;stopConnections();state.task=null;state.snapshot=null;state.report=null;state.evidenceRequest++;sessionStorage.removeItem(intentStorage);$("new-panel").hidden=false;$("workspace-panel").hidden=true;history.pushState({},"","/");clearError();$("repo-path").focus();}
async function historyList(){try{const tasks=await api("/tasks");$("history-count").textContent=tasks.length;const nav=$("task-history");nav.replaceChildren();if(!tasks.length)nav.append(node("p","还没有分析记录","nav-empty"));for(const task of tasks){const item=node("button",undefined,`history-item${state.task?.id===task.id?" active":""}`);item.append(node("span",task.question.slice(0,60)),node("small",statuses[task.status]||task.status));item.onclick=()=>loadTask(task.id);nav.append(item);}}catch(e){showError(e.message);}}
function activateTab(name){for(const tab of document.querySelectorAll("[data-tab]")){const active=tab.dataset.tab===name;tab.setAttribute("aria-selected",String(active));tab.tabIndex=active?0:-1;$(tab.getAttribute("aria-controls")).hidden=!active;}}
function updateTask(task){state.task=task;renderRecovery(task);$("retrieval-label").textContent=task.mode==="direct"?"直接回答基线 · 无检索 · 未经源码核验":task.retrieval_mode==="hybrid"?`混合检索${task.rerank?" · 重排":""} · 固定索引 ${(task.retrieval_configuration?.index_id||"").slice(0,8)}`:"关键词检索";if(task.context_compression)$("retrieval-label").textContent+=" · 历史片段压缩";$("task-status").textContent=statuses[task.status]||task.status;$("task-status").className=`status-pill ${task.status}`;$("task-question").textContent=task.question;$("cancel-task").disabled=state.loading||!canCancelTask(task);$("cancel-task").textContent=state.actions.get(task.id)==="cancel"||(task.cancel_requested&&!terminal.has(task.status))?"正在取消…":"取消任务";const u=task.usage;$("model-calls").textContent=u?u.model_calls:"暂无";$("tool-calls").textContent=u?u.tool_calls:"暂无";$("token-usage").textContent=u?`${u.input_tokens.toLocaleString()} / ${u.output_tokens.toLocaleString()}${u.estimated?" ≈":""}`:"暂无";$("elapsed").textContent=u?.elapsed_ms?`${(u.elapsed_ms/1000).toFixed(1)} s`:"暂无";if(task.error_code&&!task.resume_available)showError(task.error_code);}
function evidenceButton(id,label){const button=node("button",label||`引用 ${id.slice(0,6)}`,"citation");button.type="button";button.dataset.evidenceId=id;button.onclick=()=>{const generation=state.generation;openEvidence(id).catch(e=>{if(generation===state.generation)showError(e.message);});};return button;}
async function openEvidence(id){const generation=state.generation,taskId=state.task?.id,request=++state.evidenceRequest;const item=await api(`/evidence/${encodeURIComponent(id)}`);if(generation!==state.generation||taskId!==state.task?.id||request!==state.evidenceRequest)return;if(item.snapshot_id!==state.task.snapshot_id)throw new Error("snapshot_mismatch");state.evidence.set(id,item);$("evidence-placeholder").hidden=true;$("evidence-detail").hidden=false;$("evidence-location").textContent=`${item.path}:${item.start_line}–${item.end_line}`;$("evidence-meta").replaceChildren(node("div",`快照 ${item.snapshot_id}`),node("div",`版本 ${item.commit_sha||state.snapshot?.manifest_hash||"内容清单版本"}`),node("div",`SHA-256 ${item.content_hash}`));$("evidence-code").textContent=item.excerpt;$("evidence-meta").prepend(node("div",item.source_type==="repository_document"?"仓库文档":"仓库源码"));if(item.source_type==="web_document")renderWebEvidence(item);else appendGitHubLink(item);if(window.innerWidth<1150)$("evidence-sidebar").scrollIntoView({behavior:"smooth",block:"start"});}
function renderSources(){const container=$("source-list");container.replaceChildren();const ids=new Set();for(const event of state.events.values())for(const id of event.payload.evidence_ids||[])ids.add(id);for(const claim of state.report?.claims||[])for(const id of claim.evidence_ids)ids.add(id);if(!ids.size){container.append(node("p","尚未生成源码证据。","muted"));return;}for(const id of ids){const row=node("div",undefined,"source-item");row.append(evidenceButton(id),node("p",id));container.append(row);}}
function renderReport(report){state.report=report;const panel=$("report-panel");panel.replaceChildren();const intro=node("div",undefined,"report-intro");intro.append(node("h3","调查结论"),node("span",report.mode==="direct"?"UNVERIFIED BASELINE":"SOURCE-VERIFIABLE"));panel.append(intro);if(!report.claims.length)panel.append(node("p",report.mode==="direct"?"本次未生成直接回答，请查看局限。":"本次未得到有有效引用的结论，请查看局限和调查过程。","muted"));for(const [i,claim]of report.claims.entries()){const block=node("article",undefined,"claim");block.append(node("div",String(i+1).padStart(2,"0"),"claim-number"),node("p",claim.text));if(report.mode==="collaborative")block.append(node("p",`模型评审：${reviewLabels[claim.review_status]||"未评审"}`,"review-label"));for(const id of claim.evidence_ids)block.append(evidenceButton(id));panel.append(block);}const limits=node("section",undefined,"limitations");limits.append(node("h4","局限与待确认事项"));for(const line of report.limitations)limits.append(node("p",errorLabels[line]||line));limits.append(node("p",report.mode==="direct"?"本回答未检索源码，没有证据引用，所有结论均未经核验。":"引用位置与内容已校验；这不等于对结论语义的独立验证。"));panel.append(limits);$("download-report").disabled=false;renderSources();}
const eventTitles={context_compressed:"较早工具结果已压缩，可回读原文",task_resumed:"恢复任务已入队",resume_replayed:"恢复请求已确认",model_replayed:"复用已保存模型响应",tool_replayed:"复用已保存工具结果",recovery_checked:"恢复条件已检查",graph_updated:"分工状态已保存",subtask_started:"子任务开始",subtask_finished:"子任务结束",review_completed:"模型评审完成",task_queued:"任务已入队",task_started:"开始调查",model_started:"请求模型",model_completed:"模型响应完成",model_error:"模型请求失败",tool_started:"调用检索工具",tool_completed:"工具返回",cancel_requested:"请求取消",task_finished:"任务结束"};
async function appendEvent(event){if(state.events.has(event.sequence))return;state.events.set(event.sequence,event);state.cursor=Math.max(state.cursor,event.sequence);const li=node("li");li.dataset.sequence=event.sequence;li.append(node("strong",eventTitles[event.type]||event.type),node("small",`#${event.sequence}`));const p=event.payload;if(p.graph&&state.task?.mode==="collaborative")renderGraph(p.graph);if(p.tool)li.append(node("p",`${p.tool} · ${p.status||"started"}${p.error_code?` · ${p.error_code}`:""}`));else if(p.error_code)li.append(node("p",p.error_code));else if(p.status)li.append(node("p",statuses[p.status]||p.status));$("event-list").append(li);if(p.evidence_ids?.length)await renderSources();}
function connectEvents(id,generation){if(generation!==state.generation)return;state.source?.close();const source=new EventSource(`/tasks/${id}/events?after=${state.cursor}`);state.source=source;source.onopen=()=>{$("connection-state").textContent="实时连接";};source.addEventListener("task",event=>{if(generation!==state.generation)return;appendEvent(JSON.parse(event.data)).catch(e=>showError(e.message));});source.addEventListener("end",()=>{source.close();if(generation===state.generation){$("connection-state").textContent="全部事件已保存";refreshTask(id,generation).catch(e=>showError(e.message));}});source.onerror=()=>{source.close();if(generation!==state.generation)return;$("connection-state").textContent="连接中断，正在重连…";state.reconnect=setTimeout(()=>connectEvents(id,generation),800);};}
async function refreshTask(id,generation){
  const epoch=state.refreshEpochs.get(id)||0,sequence=++state.refreshSequence;
  const stale=()=>generation!==state.generation||epoch!==(state.refreshEpochs.get(id)||0)||sequence<(state.appliedRefreshes.get(id)||0);
  const task=await api(`/tasks/${id}`);if(stale())return;
  state.appliedRefreshes.set(id,sequence);updateTask(task);
  if(task.mode==="collaborative"){
    const graph=await api(`/tasks/${id}/graph`);if(stale())return;renderGraph(graph);
  }
  if(terminal.has(task.status)){
    clearInterval(state.poll);
    const response=await fetch(`/tasks/${id}/report`),report=response.ok?await response.json():null;
    if(stale())return;
    if(report)renderReport(report);
    else $("report-panel").replaceChildren(node("p",task.status==="cancelled"?"任务已取消。":"报告尚不可用。","muted"));
    await historyList();
  }
}
async function loadTask(id){stopConnections();$("recovery-panel").hidden=true;$("graph-summary").hidden=true;$("subtask-list").replaceChildren();const generation=++state.generation;state.task=null;state.snapshot=null;taskControls(true);clearError();state.events.clear();state.cursor=0;state.report=null;state.evidenceRequest++;$("event-list").replaceChildren();$("source-list").replaceChildren();$("evidence-placeholder").hidden=false;$("evidence-detail").hidden=true;$("download-report").disabled=true;$("new-panel").hidden=true;$("workspace-panel").hidden=false;$("report-panel").replaceChildren(node("p","正在收集代码证据，可在调查过程中查看工具事件。","muted"));activateTab("report");history.replaceState({},"",`/?task_id=${encodeURIComponent(id)}`);try{const task=await api(`/tasks/${id}`);if(generation!==state.generation)return;const snapshot=await api(`/repositories/${task.snapshot_id}`);if(generation!==state.generation)return;state.snapshot=snapshot;$("snapshot-label").textContent=`SNAPSHOT / ${task.snapshot_id.slice(0,12)}`;$("repository-label").textContent=`${snapshot.source} · ${snapshot.commit_sha?`commit ${snapshot.commit_sha.slice(0,12)}`:`manifest ${snapshot.manifest_hash.slice(0,12)}`}`;updateTask(task);taskControls(false);connectEvents(id,generation);state.poll=setInterval(()=>refreshTask(id,generation).catch(e=>{if(generation===state.generation)showError(e.message);}),1500);await refreshTask(id,generation);}catch(e){if(generation===state.generation)showError(e.message);}}
async function submitTask(snapshotId,question,intent,mode="single",retrieval_mode="keyword",rerank=false){return api("/tasks",{method:"POST",body:JSON.stringify({snapshot_id:snapshotId,question,mode,retrieval_mode,rerank,context_compression:intent.descriptor.context_compression||false,document_ids:intent.document_ids||intent.descriptor.document_ids||[],idempotency_key:intent.key})});}
$("analysis-form").onsubmit=async event=>{
  event.preventDefault();clearError();
  const button=$("submit-analysis"),generation=state.generation,github=$("repository-source").value==="github";
  const question=$("question").value.trim(),mode=$("analysis-mode").value,retrieval_mode=$("retrieval-mode").value,rerank=$("enable-rerank").checked;
  const descriptor=github?{kind:"github",url:$("github-url").value.trim().replace(/\/+$/,"").replace(/\.git$/,"").toLowerCase(),ref:$("github-ref").value.trim()||null,question,mode,retrieval_mode,rerank}:{kind:"new",path:$("repo-path").value.trim(),question,mode,retrieval_mode,rerank};
  descriptor.context_compression=$("context-compression").checked;
  descriptor.document_urls=[...new Set($("document-urls").value.split(/\r?\n/).map(url=>url.trim()).filter(Boolean))];descriptor.render_pages=$("render-pages").checked;
  if(descriptor.document_urls.length>10){showError("document_attachment_limit");return;}
  const intent=intentFor(descriptor);
  submissionControls(true);$("import-status").textContent=github?"正在解析版本、下载并校验 GitHub 源码…":"正在创建固定快照与源码索引…";
  try{
    const body=github?{github_url:descriptor.url,ref:descriptor.ref,idempotency_key:intent.importKey}:{path:descriptor.path,idempotency_key:intent.importKey};
    const snapshot=intent.snapshot_id?await api(`/repositories/${intent.snapshot_id}`):await api("/repositories",{method:"POST",body:JSON.stringify(body)});
    intent.snapshot_id=snapshot.id;if(pendingIntent()?.key===intent.key)storeIntent(intent);
    let current=snapshot;
    while(current.status==="importing"){
      await new Promise(resolve=>setTimeout(resolve,300));current=await api(`/repositories/${snapshot.id}`);
    }
    if(current.status!=="ready"){acknowledgeIntent(intent);throw new Error(current.error_code||"import_failed");}
    if(retrieval_mode==="hybrid")await prepareRetrieval(snapshot.id,intent,generation);
    await prepareDocuments(snapshot.id,intent,generation);
    const task=await submitTask(snapshot.id,question,intent,mode,retrieval_mode,rerank);acknowledgeIntent(intent);
    if(generation===state.generation)await loadTask(task.id);else await historyList();
  }catch(e){if(generation===state.generation)showError(e.message);}
  finally{submissionControls(false);$("import-status").textContent="";}
};
$("followup-form").onsubmit=async event=>{event.preventDefault();if(state.loading||!state.task)return;const button=event.currentTarget.querySelector("button"),generation=state.generation,snapshot_id=state.task.snapshot_id,question=$("followup-question").value.trim();const mode=state.task.mode||"single",retrieval_mode=state.task.retrieval_mode||"keyword",rerank=state.task.rerank||false,intent=intentFor({kind:"followup",snapshot_id,question,mode,retrieval_mode,rerank,context_compression:state.task.context_compression||false,document_ids:state.task.document_ids||[]});button.disabled=true;try{const task=await submitTask(snapshot_id,question,intent,mode,retrieval_mode,rerank);acknowledgeIntent(intent);if(generation===state.generation){$("followup-question").value="";await loadTask(task.id);}else await historyList();}catch(e){if(generation===state.generation)showError(e.message);}finally{if(generation===state.generation)button.disabled=false;}};
$("cancel-task").onclick=async()=>{
  if(state.loading||!canCancelTask(state.task))return;
  const generation=state.generation,id=state.task.id;
  invalidateTaskRefresh(id);state.actions.set(id,"cancel");updateTask(state.task);clearError();
  try{
    const task=await api(`/tasks/${id}/cancel`,{method:"POST"});
    invalidateTaskRefresh(id);
    if(generation===state.generation&&state.task?.id===id)updateTask(task);
  }catch(e){if(generation===state.generation&&state.task?.id===id)showError(e.message);}
  finally{
    await finishTaskAction(id);
  }
};
$("new-analysis").onclick=newAnalysis;
$("download-report").onclick=()=>{if(!state.report)return;const url=URL.createObjectURL(new Blob([state.report.markdown],{type:"text/markdown;charset=utf-8"}));const a=node("a");a.href=url;a.download=`repolens-${state.task.id}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
for(const tab of document.querySelectorAll("[data-tab]")){tab.onclick=()=>activateTab(tab.dataset.tab);tab.onkeydown=event=>{const tabs=[...document.querySelectorAll("[data-tab]")];let index=tabs.indexOf(tab);if(event.key==="ArrowRight")index=(index+1)%tabs.length;else if(event.key==="ArrowLeft")index=(index+tabs.length-1)%tabs.length;else if(event.key==="Home")index=0;else if(event.key==="End")index=tabs.length-1;else return;event.preventDefault();activateTab(tabs[index].dataset.tab);tabs[index].focus();};}
window.addEventListener("popstate",()=>{const id=new URLSearchParams(location.search).get("task_id");if(id)loadTask(id);else newAnalysis();});
(async()=>{try{const health=await api("/health");state.retrievalConfigured=health.retrieval_configured||false;state.rerankConfigured=health.rerank_configured||false;configureRetrieval();$("workspace-hint").textContent=`允许工作目录：${health.workspace_root}`;const banners=[];if(health.test_environment)banners.push("测试环境 · 使用脚本化模型，结果仅用于功能验收。");if(!health.model_configured)banners.push("未配置模型 · 可导入仓库；真实调查需在本地配置模型后重启。");if(banners.length){$("environment-banner").textContent=banners.join(" ");$("environment-banner").hidden=false;}restoreIntent();await historyList();const id=new URLSearchParams(location.search).get("task_id");if(id)await loadTask(id);}catch(e){showError(e.message);}})();

const reviewLabels={model_supported:"支持",model_contradicted:"冲突",model_insufficient:"证据不足",not_reviewed:"未评审"};

async function prepareDocuments(snapshotId,intent,generation){
  const urls=intent.descriptor.document_urls||[];intent.document_jobs=intent.document_jobs||[];const ids=[];
  for(let index=0;index<urls.length;index++){
    let document=intent.document_jobs[index]?await api(`/documents/${encodeURIComponent(intent.document_jobs[index])}`):await api(`/repositories/${snapshotId}/documents`,{method:"POST",body:JSON.stringify({url:urls[index],render:intent.descriptor.render_pages||false,idempotency_key:`${intent.key}:document:${index}`})});
    intent.document_jobs[index]=document.id;if(pendingIntent()?.key===intent.key)storeIntent(intent);
    while(document.status==="queued"||document.status==="running"){
      if(generation===state.generation)$("import-status").textContent=`网页资料 ${index+1}/${urls.length}：${document.status==="queued"?"等待 worker 采集":"正在保存正文"}…`;
      await new Promise(resolve=>setTimeout(resolve,400));document=await api(`/documents/${encodeURIComponent(document.id)}`);
    }
    if(document.status!=="ready")throw new Error(document.error_code||"document_collection_failed");
    ids.push(document.id);
  }
  intent.document_ids=ids;if(pendingIntent()?.key===intent.key)storeIntent(intent);
}

function renderWebEvidence(item){
  $("evidence-location").textContent=`${item.title||"网页资料"} · 段落 ${item.start_line}–${item.end_line}`;
  const rows=["网页正文 · 非可信外部资料",`快照 ${item.snapshot_id}`,`采集时间 ${item.collected_at||"未知"}`,`声明版本 ${item.declared_version||"未提供"} · 与仓库版本关系未核验`,`SHA-256 ${item.content_hash}`,...(item.collection_limitations||[])];
  $("evidence-meta").replaceChildren(...rows.map(text=>node("div",text)));
  try{const url=new URL(item.url);if(url.protocol==="https:"&&!url.username&&!url.password){const link=node("a","打开原网页（内容可能已变化）","source-link");link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";$("evidence-meta").prepend(link);}}catch{}
}

(async()=>{try{const config=await api("/document-config");$("document-hint").textContent=config.enabled?`允许站点：${config.hosts.join("、")}。${config.renderer_configured?"可尝试动态渲染；失败将标明静态降级。":"动态浏览器未配置，仅支持静态正文；请求渲染会标明降级。"}`:"网页采集尚未配置；本地设置允许站点后重启服务。";}catch{$("document-hint").textContent="网页采集配置暂不可读；已有仓库调查不受影响。";}})();
function renderGraph(graph){
  $("graph-summary").hidden=false;
  $("graph-round").textContent=`补查轮次 ${graph.round||0} / 2 · 共享总预算 · 模型判断待人工复核`;
  const list=$("subtask-list");list.replaceChildren();
  const results=new Map((graph.subtasks||[]).map(item=>[item.id,item]));
  for(const task of graph.plan||[]){const row=node("article",undefined,"subtask"),result=results.get(task.id);row.append(node("strong",task.role==="docs"?"文档调查":"代码调查"),node("span",statuses[result?.status]||"等待中"),node("p",task.question));list.append(row);}
  const reviews=$("graph-review");reviews.replaceChildren();
  for(const review of graph.reviews||[])for(const item of review.items||[]){const row=node("p",`模型评审：${reviewLabels["model_"+item.verdict]||item.verdict} · ${item.reason}`,"review-label");for(const id of item.evidence_ids||[])row.append(evidenceButton(id));reviews.append(row);}
  $("graph-issues").textContent=(graph.issues||[]).join(" · ");
}

function configureRetrieval(){
  const direct=$("analysis-mode").value==="direct";
  if(direct){$("retrieval-mode").value="keyword";$("enable-rerank").checked=false;$("context-compression").checked=false;$("document-urls").value="";$("render-pages").checked=false;}
  for(const id of ["retrieval-mode","context-compression","document-urls","render-pages"])$(id).disabled=state.submitting||direct;
  const hybrid=$("retrieval-mode").value==="hybrid";
  $("retrieval-mode").querySelector('[value="hybrid"]').disabled=!state.retrievalConfigured;
  $("enable-rerank").disabled=state.submitting||direct||!hybrid||!state.rerankConfigured;
  if(!hybrid)$("enable-rerank").checked=false;
  $("retrieval-hint").textContent=direct?"仅凭模型已有知识回答，未读取源码或网页，不能作为已核验的调查结果。":!state.retrievalConfigured?"混合检索尚未配置，当前使用关键词检索。":hybrid?"混合检索将源码发送到已配置的 Embedding 服务，可能产生费用。建库与调查分别受预算限制。":"关键词检索不调用 Embedding 或重排服务。";
}
$("retrieval-mode").onchange=configureRetrieval;
$("analysis-mode").onchange=configureRetrieval;
async function prepareRetrieval(snapshotId,intent,generation){
  let index=await api(`/repositories/${snapshotId}/retrieval-index`,{method:"POST",body:JSON.stringify({idempotency_key:intent.importKey})});
  while(index.status==="queued"||index.status==="building"){
    if(generation===state.generation)$("import-status").textContent=`正在创建向量索引 · ${index.chunks||0} 块 · ${index.usage?.model_calls||0} 次模型请求`;
    await new Promise(resolve=>setTimeout(resolve,300));index=await api(`/repositories/${snapshotId}/retrieval-index`);
  }
  if(index.status!=="ready"){acknowledgeIntent(intent);throw new Error(index.error_code||"retrieval_index_failed");}
}

const recoveryIntentStorage="repolens.resumeIntent.v1";
function recoveryIntent(){try{return JSON.parse(sessionStorage.getItem(recoveryIntentStorage)||"null");}catch{return null;}}
function renderRecovery(task){
  const intent=recoveryIntent();
  if(intent?.task_id===task.id&&(task.attempt||1)>intent.from_attempt)sessionStorage.removeItem(recoveryIntentStorage);
  $("recovery-panel").hidden=!task.recovery_enabled||!(task.resume_available||task.recovery_error||(task.attempt||1)>1);
  const deadline=task.recovery_deadline?new Date(task.recovery_deadline*1000).toLocaleString():"以首次执行记录为准";
  $("recovery-info").textContent=`执行轮次 ${task.attempt||1} · 原始截止时间 ${deadline}。恢复沿用同一快照与剩余额度；未知请求可能重复费用。${task.recovery_error?` 当前不可恢复：${task.recovery_error}`:""}`;
  $("resume-task").hidden=!task.resume_available;
  $("resume-task").disabled=state.loading||!task.resume_available||state.actions.has(task.id);
}
$("resume-task").onclick=async()=>{
  if(state.loading||!state.task?.resume_available||state.actions.has(state.task.id))return;
  const generation=state.generation,id=state.task.id,attempt=state.task.attempt||1;
  let intent=recoveryIntent();if(!intent||intent.task_id!==id||intent.from_attempt!==attempt){intent={task_id:id,from_attempt:attempt,key:crypto.randomUUID()};sessionStorage.setItem(recoveryIntentStorage,JSON.stringify(intent));}
  invalidateTaskRefresh(id);state.actions.set(id,"resume");taskControls(state.loading);clearError();
  try{const task=await api(`/tasks/${id}/resume`,{method:"POST",body:JSON.stringify({idempotency_key:intent.key})});invalidateTaskRefresh(id);if(recoveryIntent()?.key===intent.key)sessionStorage.removeItem(recoveryIntentStorage);if(generation===state.generation||state.task?.id===id)await loadTask(task.id);else await historyList();}
  catch(e){if(generation===state.generation)showError(e.message);}
  finally{await finishTaskAction(id);}
};
