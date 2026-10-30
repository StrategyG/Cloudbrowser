"use strict";
const $ = id => document.getElementById(id);
let csrf = "", selectedJob = "", stateTimer, screenTimer, screenUrl, refreshingScreen = false, currentState;
let dragStart = null;
let projectDirty = false;
$("project-name").oninput = $("project-brief").oninput = () => { projectDirty = true; };
function toast(message) { $("toast").textContent = message; $("toast").hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $("toast").hidden = true, 6500); }
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body === "string") headers["Content-Type"] = "application/json";
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401) showLogin();
    let message = `Permintaan gagal (${response.status})`;
    try { const data = await response.json(); if (typeof data.detail === "string") message = data.detail; } catch { /* use status */ }
    throw new Error(message);
  }
  return response.json();
}
const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });
function showLogin() { $("login").hidden = false; $("workspace").hidden = true; csrf = ""; clearInterval(stateTimer); clearInterval(screenTimer); }
async function showWorkspace() {
  $("login").hidden = true; $("workspace").hidden = false;
  await refresh();
  clearInterval(stateTimer); stateTimer = setInterval(() => refresh().catch(e => toast(e.message)), 3000);
}
$("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  try { const result = await post("/api/login", { password: $("password").value }); csrf = result.csrf_token; $("password").value = ""; await showWorkspace(); } catch(e) { toast(e.message); }
});
$("logout").onclick = async () => { try { await post("/api/logout"); showLogin(); if(screenUrl) URL.revokeObjectURL(screenUrl); $("screen").hidden = true; $("screen-placeholder").hidden = false; } catch(e) { toast(e.message); } };
function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function button(label, action) { const node = element("button", "", label); node.onclick = () => Promise.resolve().then(action).catch(e => toast(e.message)); return node; }
function renderList(id, items, render, empty) { const host = $(id); host.replaceChildren(); host.classList.toggle("empty", !items.length); if (!items.length) host.textContent = empty; else items.forEach(item => host.append(render(item))); }
async function refresh() {
  currentState = await api("/api/state"); const state = currentState;
  $("model-name").textContent = state.model;
  $("vision-status").textContent = state.vision ? "Vision + browser tools" : "Teks + browser tools";
  $("mode").value = state.mode;
  $("mode-note").textContent = state.mode === "auto" ? "Persiapan otomatis. Klik, unggah, keyboard dan delegasi remote tetap memerlukan persetujuan. Fill/select mengikuti izin server." : "Klik, pengetikan dan unggahan AI menunggu persetujuan Anda.";
  if (!projectDirty) {
    $("project-name").value = state.project.id;
    $("project-brief").value = state.project.brief;
  }
  renderList("uncertain-actions", state.unresolved_actions || [], action => {
    const row = element("div", "item");
    row.append(element("div", "item-title", action.summary), element("div", "item-meta", action.id));
    const actions = element("div", "item-actions");
    for (const [label, applied] of [["Sudah terjadi", true], ["Belum terjadi", false]]) {
      actions.append(button(label, async () => {
        if (!confirm("Anda sudah memeriksa hasil di website atau peer?")) return;
        await post("/api/actions/" + action.id + "/resolve", { approved: applied });
        await refresh();
      }));
    }
    row.append(actions); return row;
  }, "Tidak ada tindakan yang perlu dipastikan.");
  $("bot-status").textContent = state.telegram.connected ? `Telegram · @${state.telegram.username}` : state.telegram.error || (state.telegram.enabled ? "Telegram · menunggu koneksi" : "Telegram · tidak aktif");
  $("bot-status").classList.toggle("online", state.telegram.connected);
  $("approval-count").textContent = String(state.approvals.length);
  renderList("agents", state.agents || [], agent => {
    const row = element("div", "item"); row.append(element("div", "item-title", agent.name), element("div", "item-meta", `${agent.id} · ${agent.profile}`)); return row;
  }, "AI akan membangun tim sesuai pekerjaan.");
  renderList("approvals", state.approvals, approval => {
    const row = element("div", "item"); row.append(element("div", "item-title", approval.summary), element("div", "item-meta", `Job ${approval.job_id} · ${approval.id}`));
    const actions = element("div", "item-actions");
    actions.append(button("Setujui", async () => { await post(`/api/approvals/${approval.id}`, { approved: true }); await refresh(); }), button("Tolak", async () => { await post(`/api/approvals/${approval.id}`, { approved: false }); await refresh(); })); row.append(actions); return row;
  }, "Belum ada permintaan persetujuan.");
  renderList("jobs", state.jobs, job => {
    const row = element("div", "item"), copy = element("div", "item-copy"); copy.append(element("div", "item-title", job.goal.slice(0,170)), element("div", "item-meta", `${job.id} · ${new Date(job.updated*1000).toLocaleString("id-ID")}`));
    const actions = element("div", "item-actions"); actions.append(element("span", `status ${job.status}`, job.status), button("Lihat", () => openJob(job.id))); row.append(copy, actions); return row;
  }, "Belum ada pekerjaan.");
  renderList("artifacts", state.artifacts, artifact => {
    const row = element("div", "item"), copy = element("div", "item-copy"); copy.append(element("div", "item-title", artifact.filename), element("div", "item-meta", `${(artifact.size/1024/1024).toFixed(2)} MB · ${artifact.id}`));
    const link = element("a", "small", "Unduh ↓"); link.href = `/api/artifacts/${artifact.id}`; link.download = artifact.filename; row.append(copy, link); return row;
  }, "Belum ada file.");
  const selectedTab = $("tabs").value; $("tabs").replaceChildren();
  state.tabs.forEach(tab => { const opt = element("option", "", `${tab.index+1} · ${tab.url.slice(0,45)}`); opt.value = String(tab.index); $("tabs").append(opt); });
  if ([...$("tabs").options].some(option => option.value === selectedTab)) $("tabs").value = selectedTab;
}
async function manual(kind, args = {}) { const result = await post("/api/browser/manual", { kind, args }); $("url").value = result.url || ""; await refreshScreen(); await refresh(); }
$("navigate-form").onsubmit = event => { event.preventDefault(); manual("navigate", { url: $("url").value }).catch(e => toast(e.message)); };
document.querySelectorAll("[data-site]").forEach(node => node.onclick = () => manual("navigate", { url: node.dataset.site }).catch(e => toast(e.message)));
$("new-tab").onclick = () => manual("new_tab").catch(e => toast(e.message));
$("tabs").onchange = () => manual("tab", { index: Number($("tabs").value) }).catch(e => toast(e.message));
$("type-form").onsubmit = async event => { event.preventDefault(); const text = $("type-text").value; try { await manual("type", { text }); $("type-text").value = ""; } catch(e) { toast(e.message); } };
$("press-key").onclick = () => manual("press", { key: $("key").value }).catch(e => toast(e.message));
$("scroll-up").onclick = () => manual("scroll", { pixels: -600 }).catch(e => toast(e.message));
$("scroll-down").onclick = () => manual("scroll", { pixels: 600 }).catch(e => toast(e.message));
function point(event) { const rect = $("screen").getBoundingClientRect(); return { x: Math.min(1279,Math.max(0,(event.clientX-rect.left)/rect.width*1280)), y: Math.min(719,Math.max(0,(event.clientY-rect.top)/rect.height*720)) }; }
$("screen").onpointerdown = event => { dragStart = point(event); $("screen").setPointerCapture(event.pointerId); };
$("screen").onpointerup = event => { if (!dragStart) return; const end = point(event), start = dragStart; dragStart = null; if ($("drag-mode").checked) manual("drag", { ...start, end_x: end.x, end_y: end.y }).catch(e => toast(e.message)); else manual("coordinate_click", end).catch(e => toast(e.message)); };
$("screen").onpointercancel = () => { dragStart = null; };
async function refreshScreen() {
  if (refreshingScreen || $("workspace").hidden) return; refreshingScreen = true;
  try {
    const response = await fetch(`/api/browser/screenshot?t=${Date.now()}`);
    if (!response.ok) { if (response.status === 401) showLogin(); throw new Error("Browser belum siap. Periksa Xvfb/display, Chromium dan sandbox di server."); }
    const blob = await response.blob(), old = screenUrl; screenUrl = URL.createObjectURL(blob); $("screen").src = screenUrl; $("screen").hidden = false; $("screen-placeholder").hidden = true; if (old) URL.revokeObjectURL(old);
  } finally { refreshingScreen = false; }
}
$("live").onchange = () => { clearInterval(screenTimer); if ($("live").checked) { refreshScreen().catch(e => toast(e.message)); screenTimer = setInterval(() => refreshScreen().catch(() => {}), 1800); } };
// A retry after a lost response reuses the same key; changed input starts a new intent.
let pendingGoalSubmission = null;
let creatingGoal = false;
$("job-form").onsubmit = async event => {
  event.preventDefault();
  if (creatingGoal) return;
  const goal = $("goal").value;
  if (!pendingGoalSubmission || pendingGoalSubmission.goal !== goal) {
    pendingGoalSubmission = {goal, key: crypto.randomUUID()};
  }
  creatingGoal = true;
  try {
    const job = await post("/api/jobs", {text: goal, idempotency_key: pendingGoalSubmission.key});
    pendingGoalSubmission = null;
    $("goal").value = "";
    toast(`Job ${job.id} masuk antrean.`);
    await refresh();
  } catch (e) {
    toast(e.message);
  } finally {
    creatingGoal = false;
  }
};
$("mode").onchange = async () => { const mode = $("mode").value; try { await post("/api/mode", { mode }); await refresh(); } catch(e) { toast(e.message); $("mode").value = currentState.mode; } };
$("project-form").onsubmit = async event => { event.preventDefault(); try { await post("/api/project", { id: $("project-name").value, brief: $("project-brief").value }); projectDirty = false; toast("Konteks proyek tersimpan."); await refresh(); } catch(e) { toast(e.message); } };
$("file").onchange = async () => { const file = $("file").files[0]; if (!file) return; try { const result = await api(`/api/artifacts?filename=${encodeURIComponent(file.name)}`, { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file }); toast(`Unggahan tersimpan. ID: ${result.id}`); await refresh(); } catch(e) { toast(e.message); } finally { $("file").value = ""; } };
async function openJob(id) {
  const job = await api(`/api/jobs/${id}`); selectedJob = id;
  $("job-title").textContent = `${id} · ${job.status} · ${job.project_id}`;
  $("job-goal").textContent = job.goal;
  $("job-result").textContent = job.result || "Pekerjaan sedang diproses.";
  const tasks = new Map((job.agent_tasks || []).map(task => [task.step_id, task]));
  $("job-workflow").textContent = (job.workflow?.steps || []).map(step => {
    const task = tasks.get(step.id), review = task ? JSON.parse(task.review) : {};
    return `${step.id} · ${task?.agent_id || "belum ditugaskan"} · ${task?.status || "pending"} · review: ${review.passed ? "lulus" : "belum lulus"}\n${step.description}`;
  }).join("\n\n") || "Workflow belum disusun.";
  $("job-budget").textContent = `Pemakaian model: ${job.budget.model_calls}/${job.model_limits.calls} panggilan · ${job.budget.output_tokens_charged}/${job.model_limits.output_tokens} token keluaran diperhitungkan.\nSaat pemakaian belum dilaporkan penyedia, batas keluaran tiap panggilan dicadangkan penuh.`;
  $("job-events").textContent = job.events.map(event => `${new Date(event.created*1000).toLocaleTimeString()}  ${event.kind}  ${event.detail}`).join("\n") || "Belum ada aktivitas.";
  $("resume-text").value = ""; $("job-dialog").showModal();
}
$("close-dialog").onclick = () => $("job-dialog").close();
$("stop-job").onclick = async () => { try { await post(`/api/jobs/${selectedJob}/stop`); $("job-dialog").close(); await refresh(); } catch(e) { toast(e.message); } };
$("resume-job").onclick = async () => { try { await post(`/api/jobs/${selectedJob}/resume`, { text: $("resume-text").value || "Lanjutkan setelah memeriksa browser saat ini." }); $("job-dialog").close(); await refresh(); } catch(e) { toast(e.message); } };
(async () => { try { const session = await api("/api/session"); csrf = session.csrf_token; await showWorkspace(); } catch { showLogin(); } })();
