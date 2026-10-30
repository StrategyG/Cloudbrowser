# Memperbarui StrategyG/Cloudbrowser

Paket ini berisi Cloudbrowser A2A + Studio/Godot 0.4. Kode dapat dijalankan langsung dari ZIP
atau dari checkout repository. Mulai browser dengan `sh scripts/start.sh`; mulai stack Studio
opsional dengan `sh scripts/start_studio.sh`. Konfigurasi dan token dimasukkan di server.

Untuk mengunggah melalui checkout/Codespaces yang sudah terautentikasi, simpan perubahan lokal,
buat branch baru, salin isi folder Cloudbrowser dari ZIP (termasuk .github), lalu jalankan:

```bash
git status
git switch -c upgrade/cloudbrowser-studio-v04
git add .
git commit -m "feat: integrate Studio Godot with Cloudbrowser A2A"
git push -u origin upgrade/cloudbrowser-studio-v04
```

Jangan salin folder .git dari checkout lain. Jangan commit .env, data, profil browser, workspace
Studio atau token. Koneksi penulis memerlukan izin Contents write dan akses yang sesuai untuk
workflow GitHub. Jangan kirim token melalui chat. Lihat tab Actions untuk hasil CI aktual;
file workflow dan hasil tes lokal tidak membuktikan suatu run GitHub sudah lulus.
