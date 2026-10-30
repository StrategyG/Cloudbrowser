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
el("inspect").onsubmit = async event => {
  event.preventDefault();
  try {
    const id = el("project").value.trim();
    if (!/^[a-f0-9]{32}$/.test(id)) throw Error("ID proyek tidak valid.");
    const base = "/api/studio/projects/" + id;
    const info = await api(base); el("qa").textContent = JSON.stringify(info, null, 2);
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
