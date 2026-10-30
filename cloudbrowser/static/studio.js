"use strict";
const el = id => document.getElementById(id);
let csrf = "";
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...(options.headers || {}), "X-CSRF-Token": csrf}});
  if (response.status === 401) { location.href = "/"; throw Error("Login diperlukan."); }
  if (!response.ok) { const error = await response.json(); throw Error(error.detail || "Permintaan gagal."); }
  return response.json();
}
el("create").onsubmit = async event => {
  event.preventDefault();
  try {
    const file = el("png").files[0];
    if (!file || file.size > 12*1024*1024) throw Error("Pilih PNG hingga 12 MB.");
    const artifact = await api("/api/artifacts?filename=" + encodeURIComponent(file.name), {method:"PUT", headers:{"Content-Type":"application/octet-stream"}, body:file});
    const text = `Gunakan Studio/Godot untuk membuat video dari PNG artifact ${artifact.id}. Arahan: ${el("prompt").value}. Susun workflow A2A, buat proyek Studio, periksa QA mesh dan pose rig, minta persetujuan pemilik untuk mesh, rig dan manifest. Poll job tanpa mengulang render. Import MP4 completed ke katalog hasil dan lakukan review video sebelum selesai. Laporkan ID proyek Studio.`;
    const job = await api("/api/jobs", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})});
    el("result").textContent = `Job ${job.id} masuk antrean. Buka Workspace untuk persetujuan dan progres.`;
  } catch (error) { el("result").textContent = error.message; }
};
el("generated-create").onsubmit = async event => {
  event.preventDefault();
  const status = el("generated-status");
  const button = el("generated-create").querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const file = el("generated-png").files[0];
    if (!file || file.size > 12*1024*1024 || !file.name.toLowerCase().endsWith(".png"))
      throw Error("Pilih PNG transparan hingga 12 MB.");
    const artifact = await api("/api/artifacts?filename=" + encodeURIComponent(file.name),
      {method:"PUT",headers:{"Content-Type":"application/octet-stream"},body:file});
    const dims = el("generated-resolution").value.split("x").map(Number);
    const body = {
      artifact_id:artifact.id, prompt:el("generated-prompt").value,
      mesh_mode:el("generated-mode").value, character:el("generated-character").value,
      fps:Number(el("generated-fps").value), width:dims[0],height:dims[1]
    };
    const job = await api("/api/studio/generate",
      {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    el("project").value = job.id;
    status.textContent = "Studio project " + job.id + ": membangun draft. Periksa progres di Tinjau proyek. Approval mesh, rig dan manifest tetap diperlukan.";
    el("inspect").dispatchEvent(new Event("submit", {cancelable:true}));
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
};
el("generated-approve").onclick = async () => {
  const stage = el("generated-approve").dataset.stage;
  const pid = el("project").value.trim();
  if (!["mesh","rig","manifest"].includes(stage) || !/^[a-f0-9]{32}$/.test(pid)) return;
  if (!confirm("Saya telah memeriksa QA dan aset. Setujui " + stage + " lalu lanjutkan tahap berikutnya?")) return;
  const button = el("generated-approve");
  button.disabled = true;
  try {
    const answer = await api("/api/studio/projects/" + pid + "/approve",
      {method:"POST",headers:{"Content-Type":"application/json"},
       body:JSON.stringify({project_id:pid,stage})});
    el("generated-status").textContent = JSON.stringify(answer);
    el("inspect").dispatchEvent(new Event("submit", {cancelable:true}));
  } catch (error) { el("generated-status").textContent = error.message; }
  finally { button.disabled = false; }
};
el("inspect").onsubmit = async event => {
  event.preventDefault();
  try {
    const id = el("project").value.trim();
    if (!/^[a-f0-9]{32}$/.test(id)) throw Error("ID proyek tidak valid.");
    const base = "/api/studio/projects/" + id;
    const info = await api(base); el("qa").textContent = JSON.stringify(info, null, 2);
    const stage = {mesh_review:"mesh",rig_review:"rig",manifest_review:"manifest"}[info.state] || "";
    const generated = Boolean(info.metadata?.generation?.auto_advance);
    el("generated-approval").hidden = !stage || !generated;
    el("generated-approve").dataset.stage = stage;
    el("generated-approve").textContent = "Setujui " + stage + " dan lanjutkan";
    el("generated-mesh").hidden = info.state !== "mesh_review" || !generated;
    if (!el("generated-mesh").hidden) {
      el("generated-mesh").href = base + "/assets/mesh";
      el("generated-mesh").download = "draft.glb";
    }
    el("copilot-studio").value = id;
    const evidence = await Promise.allSettled([api(base + "/scene"), api(base + "/motion-qa")]);
    el("scene-inspection").textContent = evidence[0].status === "fulfilled"
      ? JSON.stringify(evidence[0].value, null, 2) : evidence[0].reason.message;
    el("motion-preflight").textContent = evidence[1].status === "fulfilled"
      ? JSON.stringify(evidence[1].value, null, 2) : evidence[1].reason.message;
    el("poses").replaceChildren();
    if (info.metadata?.rig_qa) for (const pose of ["rest", "arms", "legs", "combo"]) {
      const image = document.createElement("img"); image.src = base + "/assets/rig_" + pose; image.alt = "Rig pose " + pose; image.width = 280; el("poses").append(image);
    }
    el("manifest").hidden = !["manifest_review","manifest_approved","rendering","completed"].includes(info.state);
    el("manifest").href = base + "/assets/manifest"; el("manifest").target = "_blank"; el("manifest").rel = "noopener";
    el("video").hidden = info.state !== "completed";
    if (info.state === "completed") el("video").src = base + "/assets/mp4";
  } catch (error) { el("qa").textContent = error.message; }
};
(async () => {
  try { const session = await api("/api/session"); csrf = session.csrf_token; const state = await api("/api/state"); el("connection").textContent = state.studio_enabled ? "Layanan Studio sudah dikonfigurasi." : "Studio belum dikonfigurasi. Jalankan configure-studio di terminal server."; }
  catch (error) { el("connection").textContent = error.message; }
})();
