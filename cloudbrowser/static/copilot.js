"use strict";
// Only the authenticated Studio parent talks to /api/copilot. There is no
// postMessage bridge to the opaque-origin MorphGLB editor.
(() => {
  const $ = id => document.getElementById(id);
  const status = $("copilot-status");
  const output = $("copilot-output");
  const terminal = new Set(["completed", "failed", "canceled", "stopped", "incomplete", "waiting_user", "awaiting_approval"]);
  let jobId = "";
  let timer = null;
  let requestKey = null;

  async function call(path, options = {}) {
    const session = await fetch("/api/session", {credentials: "same-origin"});
    if (session.status === 401) throw Error("Login diperlukan; kembali ke workspace.");
    if (!session.ok) throw Error("Sesi Studio tidak dapat diverifikasi.");
    const csrf = (await session.json()).csrf_token;
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: {...(options.headers || {}), "X-CSRF-Token": csrf}
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw Error(typeof error.detail === "string" ? error.detail : "HTTP " + response.status);
    }
    return response.json();
  }

  async function loadAgents() {
    try {
      const data = await call("/api/copilot/agents");
      const list = $("copilot-agents");
      list.replaceChildren();
      for (const agent of data.agents) {
        const item = document.createElement("li");
        item.textContent = agent.name + " (" + agent.profile + ") — " +
          (agent.installed ? "terdaftar" : "didaftarkan saat job pertama");
        list.appendChild(item);
      }
      if (!data.studio_enabled) {
        status.textContent = "Studio/Godot belum dikonfigurasi. Chat dan Plan tersedia; Edit memerlukan Studio aktif.";
      }
    } catch (error) { status.textContent = error.message; }
  }

  async function refresh() {
    if (!jobId) return;
    const info = await call("/api/jobs/" + encodeURIComponent(jobId));
    const progress = (info.agent_tasks || []).map(task =>
      task.agent_id + ": " + task.status).join(" | ");
    status.textContent = "Job " + jobId + ": " + info.status + (progress ? " | " + progress : "");
    // Print text only. Never render model output or untrusted scene notes as HTML.
    output.textContent = JSON.stringify({
      status: info.status,
      result: info.result,
      workflow: info.workflow,
      agent_tasks: (info.agent_tasks || []).map(task => ({
        agent_id: task.agent_id, step_id: task.step_id,
        status: task.status, result: task.result, outputs: task.outputs
      })),
      approvals: "Periksa workspace / Telegram untuk keputusan yang memerlukan persetujuan."
    }, null, 2);
    if (terminal.has(info.status) && timer) { clearInterval(timer); timer = null; }
    return info;
  }

  $("copilot-form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("copilot-run");
    if (button.disabled) return;
    button.disabled = true;
    try {
      const mode = $("copilot-mode").value;
      const projectId = $("copilot-project").value.trim();
      const studio = $("copilot-studio").value.trim();
      const artifact = $("copilot-artifact").value.trim();
      const prompt = $("copilot-prompt").value.trim();
      if (mode === "edit" && !studio && !artifact) {
        throw Error("Pilih Studio project ID atau artifact PNG/GLB sebelum mode Edit.");
      }
      if (!requestKey) {
        const random = new Uint8Array(16);
        crypto.getRandomValues(random);
        requestKey = "studio-" + Array.from(random, x => x.toString(16).padStart(2, "0")).join("");
      }
      status.textContent = "Mengirim pekerjaan Copilot...";
      const body = {
        mode, prompt, project_id: projectId,
        studio_project_id: studio || null,
        artifact_id: artifact || null,
        target_name: $("copilot-target").value.trim(),
        scene_notes: $("copilot-notes").value.trim(),
        idempotency_key: requestKey
      };
      const job = await call("/api/copilot/jobs", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      jobId = job.id;
      requestKey = null; // New user submission creates a new operation.
      $("copilot-job").hidden = false;
      $("copilot-job-id").textContent = jobId;
      $("copilot-refresh").disabled = false;
      await refresh();
      if (!terminal.has(job.status) && !timer) {
        timer = setInterval(() => refresh().catch(err => {
          status.textContent = err.message;
          clearInterval(timer);
          timer = null;
        }), 4000);
      }
      await loadAgents();
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  $("copilot-preview").addEventListener("click", async () => {
    const button = $("copilot-preview");
    button.disabled = true;
    try {
      const project = $("copilot-studio").value.trim();
      if (!/^[a-f0-9]{32}$/.test(project)) {
        throw Error("Preview memerlukan Studio project ID yang valid.");
      }
      const body = {
        project_id: project,
        prompt: $("copilot-prompt").value.trim(),
        character: $("copilot-target").value.trim() || "KIO",
        fps: 24, width: 1280, height: 720
      };
      const result = await call("/api/studio/projects/" + project + "/plan-preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      const box = $("copilot-preview-output");
      box.hidden = false;
      box.textContent = JSON.stringify(result, null, 2);
      status.textContent = "Preview dihasilkan tanpa mengubah manifest. Untuk menerapkan, jalankan mode Edit dengan approval.";
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  $("copilot-refresh").addEventListener("click", () =>
    refresh().catch(error => { status.textContent = error.message; }));

  loadAgents();
  // Do not read the editor's iframe internals: use authenticated, explicitly
  // selected project IDs and input fields instead.
})();
