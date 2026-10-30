"use strict";
// The original MorphGLB document is sandboxed and has no dashboard credentials.
// The authenticated parent performs only explicit, user-initiated file transfers.
(() => {
  const $ = id => document.getElementById(id);
  const frame = $("morphglb-frame");
  const result = $("morphglb-transfer-result");
  let loaded = false;
  const show = message => { result.textContent = message; };
  async function request(path, options = {}) {
    const session = await fetch("/api/session", { credentials: "same-origin" });
    if (!session.ok) throw new Error("Sesi tidak aktif. Login ulang melalui dashboard.");
    const { csrf_token } = await session.json();
    const response = await fetch(path, {
      ...options,
      credentials: "same-origin",
      headers: { ...(options.headers || {}), "X-CSRF-Token": csrf_token }
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "Cloudbrowser HTTP " + response.status);
    }
    return response.json();
  }
  function openEditor() {
    $("morphglb-panel").hidden = false;
    $("morphglb-open").setAttribute("aria-expanded", "true");
    if (!loaded) {
      loaded = true;
      frame.src = "/studio/morphglb";
    }
    $("morphglb-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  $("morphglb-open").addEventListener("click", openEditor);
  if (location.hash === "#morphglb") openEditor();

  async function validate(file) {
    const ext = file.name.toLowerCase().split(".").pop();
    const limits = { png: 12 * 1048576, glb: 50 * 1048576, json: 2 * 1048576 };
    if (!limits[ext]) throw new Error("Format harus PNG, GLB, atau JSON.");
    if (!file.size || file.size > limits[ext]) throw new Error("Ukuran file kosong atau terlalu besar untuk format ini.");
    const signature = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    if (ext === "png" && ![137,80,78,71,13,10,26,10].every((x,i) => signature[i] === x))
      throw new Error("File bukan PNG valid.");
    if (ext === "glb" && ![103,108,84,70].every((x,i) => signature[i] === x))
      throw new Error("File bukan GLB valid.");
    if (ext === "json") {
      try { JSON.parse(await file.text()); } catch { throw new Error("File JSON tidak valid."); }
    }
    return ext;
  }

  $("morphglb-transfer").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("morphglb-upload");
    button.disabled = true;
    try {
      const file = $("morphglb-file").files[0];
      if (!file) throw new Error("Pilih berkas hasil ekspor dahulu.");
      const ext = await validate(file);
      const enqueue = $("morphglb-enqueue").checked;
      const prompt = $("morphglb-prompt").value.trim();
      if (enqueue && ext !== "png") throw new Error("Pipeline Studio/Godot saat ini hanya menerima PNG; GLB disimpan sebagai aset.");
      if (enqueue && !prompt) throw new Error("Isi arahan gerakan untuk pipeline Studio/Godot.");
      show("Mengunggah ke katalog aset Cloudbrowser…");
      const artifact = await request("/api/artifacts?filename=" + encodeURIComponent(file.name), {
        method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file
      });
      show("Aset tersimpan: " + artifact.id + " (" + file.name + ").");
      if (!enqueue) return;
      const state = await request("/api/state");
      if (!state.studio_enabled) {
        show("Aset tersimpan: " + artifact.id + ". Studio/Godot belum dikonfigurasi; tidak membuat job.");
        return;
      }
      const text = "Gunakan Studio/Godot untuk membuat animasi dari PNG artifact " + artifact.id
        + ". Arahan: " + prompt
        + ". Buat proyek Studio melalui workflow A2A; periksa QA mesh dan rig, minta persetujuan untuk mesh, rig dan manifest, kemudian render dan verifikasi hasil. Jangan menganggap proses selesai sebelum MP4 disetujui.";
      const job = await request("/api/jobs", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text })
      });
      show("Aset " + artifact.id + " tersimpan. Job A2A " + job.id + " masuk antrean. Persetujuan melalui Workspace/Telegram.");
    } catch (error) {
      show(result.textContent.startsWith("Aset tersimpan:") ? result.textContent + " " + error.message : error.message);
    } finally {
      button.disabled = false;
    }
  });
})();
