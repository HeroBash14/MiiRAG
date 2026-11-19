# Panduan Memilih Metode Pencarian (Retrieval) untuk Pengguna

Dokumen ini disusun dengan bahasa yang sederhana dan non-teknis agar siapa pun dapat memahami **apa fungsi setiap pilihan di halaman Query Knowledge**, **apa efeknya terhadap hasil dan kecepatan**, serta **kapan sebaiknya mengaktifkan atau mematikannya**.

---

## 1. Memahami 3 Pilihan "Mode Retrieval"

Bayangkan dokumen-dokumen Anda seperti ribuan halaman buku di perpustakaan. Saat Anda mengetik pertanyaan, Anda bisa memilih 3 cara kerja "asisten pencari":

### 1. `Hybrid (Vector + Keyword RRF)` — **Direkomendasikan (Default)**
> **Analogi:** Seperti mencari menggunakan **dua asisten sekaligus**: asisten pertama paham **maksud/arti kalimat** Anda, dan asisten kedua jeli mencari **kata atau kode persis** di dalam teks. Lalu keduanya menggabungkan temuan terbaiknya.

* **Efek jika digunakan:**
  * Hasil pencarian **paling lengkap dan seimbang**.
  * Jika Anda mengetik *"bagaimana cara merawat mesin kopi"* padahal di dokumen tertulis *"prosedur sanitasi espresso"*, tetap ketemu karena maknanya sama.
  * Jika Anda mengetik kode persis seperti `SOP-CHIL-09` atau `HR-CUTI-04`, tetap ditemukan dengan tepat.
* **Kecepatan:** Sangat cepat (sekitar **0,03 detik** tanpa Reranker, atau **0,16 detik** dengan Reranker).
* **Kapan dipilih?** Gunakan mode ini sebagai pilihan utama untuk hampir semua kebutuhan pencarian sehari-hari.

---

### 2. `Dense Vector (pgvector)` — **Cari Berdasarkan Makna Saja**
> **Analogi:** Asisten yang hanya membaca **ide dan maksud utama** pertanyaan Anda, tanpa memperdulikan apakah ejaan kata atau kodenya sama persis.

* **Efek jika digunakan:**
  * Sangat bagus untuk pertanyaan konseptual atau kalimat tanya sehari-hari (contoh: *"apa yang harus dilakukan jika pelanggan marah?"*).
  * **Kelemahan:** Kurang peka terhadap **kode unik, singkatan, nomor surat, atau nomor SKU** (misal `SOP-CHIL-09` sering tertukar atau kalah peringkat dengan kalimat umum tentang SOP lain).
* **Kecepatan:** Sangat cepat (sekitar **0,03 detik**).
* **Kapan dipilih?** Jika Anda hanya ingin mencari topik berdasarkan makna kalimat dan merasa hasil pencocokan kata persis justru terlalu mengganggu.

---

### 3. `Keyword Only (FTS)` — **Cari Kata Persis Saja (Seperti Ctrl+F)**
> **Analogi:** Persis seperti menekan **Ctrl+F** di Word atau PDF — sistem hanya mencari halaman yang memuat kata-kata yang Anda ketik secara persis.

* **Efek jika digunakan:**
  * **100% akurat** untuk mencari nomor kode, ID dokumen, nama orang, istilah teknis baku, atau nomor pasal.
  * **Kelemahan:** Tidak paham sinonim atau maksud kalimat. Jika Anda mengetik *"cara membersihkan kulkas"* padahal dokumen menulis *"sanitasi chiller"*, **hasil tidak akan ditemukan** karena katanya berbeda.
* **Kecepatan:** Paling cepat / instan (**di bawah 0,01 detik**).
* **Kapan dipilih?** Saat Anda sudah tahu persis kata, nama, atau nomor kode unik yang ingin ditemukan secepat mungkin.

---

### Perbandingan Cepat 3 Mode Retrieval

| Mode Retrieval | Paham Sinonim & Maksud? | Tepat untuk Kode / Nomor Seri? | Kecepatan | Cocok Untuk |
| :--- | :---: | :---: | :---: | :--- |
| **`Hybrid (Vector + Keyword RRF)`** | Ya (Sangat Baik) | Ya (Sangat Baik) | Cepat | **Semua kebutuhan (Rekomendasi)** |
| **`Dense Vector (pgvector)`** | Ya (Sangat Baik) | Kurang | Sangat Cepat | Pertanyaan umum / konseptual saja |
| **`Keyword Only (FTS)`** | Tidak | Ya (Mutlak) | Instan | Cari nomor kode, nama, atau kata persis |

---

## 2. Memahami 4 Opsi Tambahan (Checkbox) & Efeknya

Di bawah kolom pencarian terdapat 4 kotak centang (*checkbox*). Berikut efek nyata jika masing-masing Anda centang atau biarkan kosong:

### ☑️ 1. `Cross-Encoder Reranker` *(Penyaring & Pengurut Cerdas)*
* **Cara kerja sederhana:** Pencarian tahap awal mengumpulkan 20 kandidat teratas dengan cepat. Lalu **Reranker** membaca ulang pertanyaan Anda dan isi kandidat secara berpasangan dengan teliti, membuang potongan yang tidak nyambung, lalu menyusun peringkat ulang agar jawaban paling tepat berada di urutan **#1**.
* **Efek jika DICENTANG *(Disarankan)*:**
  * Urutan hasil **jauh lebih akurat** dan relevan di posisi paling atas (#1 dan #2).
  * Mengurangi hasil "false positive" (potongan teks yang cuma kebetulan punya kata yang sama tapi tidak menjawab pertanyaan).
  * Memunculkan label skor baru berwarna biru: **`Rerank XX%`**.
  * *Efek ke kecepatan:* Menambah waktu proses sekitar **+0,12 detik** (masih terasa instan bagi manusia).
* **Efek jika TIDAK dicentang:**
  * Pencarian lebih cepat (~0,03 detik), tetapi urutan ranking teratas hanya mengandalkan kemiripan kasar sehingga hasil paling tepat kadang berada di urutan ke-3 atau ke-4.

---

### ☑️ 2. `Query Expansion` *(Perluas Kata & Singkatan Otomatis)*
* **Cara kerja sederhana:** Sistem otomatis menambahkan kata-kata sinonim atau kepanjangan singkatan umum dari pertanyaan Anda di balik layar.
  * Contoh: Anda mengetik **`SOP`** &rarr; sistem ikut mencari **`standar operasional prosedur`**.
  * Contoh: Anda mengetik **`tamu`** &rarr; sistem ikut mencari **`pelanggan`**.
  * Contoh: Anda mengetik **`cek`** &rarr; sistem ikut mencari **`periksa, pemeriksaan, checklist`**.
* **Efek jika DICENTANG *(Disarankan)*:**
  * Dokumen tetap ditemukan meskipun Anda memakai singkatan atau istilah yang sedikit berbeda dengan penulis dokumen.
  * *Efek ke kecepatan:* **0 ms** (tidak memperlambat sama sekali).
* **Efek jika TIDAK dicentang:**
  * Pencarian kata kunci hanya memakai kata-kata persis yang Anda tulis. Matikan opsi ini hanya jika Anda tidak ingin kata kunci melebar ke sinonim.

---

### ⬜ 3. `HyDE (Hypothetical Doc)` *(Terjemahkan Pertanyaan ke Gaya Bahasa Dokumen)*
* **Cara kerja sederhana:** Cara manusia bertanya (*"berapa modal kasir pagi?"*) sangat berbeda dengan cara buku SOP menulis (*"Prosedur pembukaan kasir mewajibkan ketersediaan modal awal..."*). **HyDE** mengubah pertanyaan pendek Anda menjadi kalimat pernyataan bergaya dokumen terlebih dahulu, baru mencocokkannya ke database.
* **Efek jika DICENTANG:**
  * Sangat membantu untuk **pertanyaan konseptual atau pertanyaan terbuka yang singkat** agar lebih mudah cocok dengan gaya penulisan dokumen resmi/SOP.
  * Di atas hasil pencarian akan muncul kotak pratinjau bertuliskan **`HyDE Passage`**.
  * *Efek ke kecepatan:* Menambah sekitar **+0,03 detik** (pada mode lokal standar) atau **+0,5–1 detik** jika dihubungkan ke LLM eksternal (Gemini/OpenAI/Ollama).
* **Efek jika TIDAK dicentang *(Default)*:**
  * Pencarian langsung memakai pertanyaan asli Anda. Sebaiknya **biarkan tidak dicentang** jika Anda sedang mencari kode persis (misal `SOP-CHIL-09`), karena kata tambahan dari HyDE justru bisa mengaburkan kode spesifik tersebut.

---

### ⬜ 4. `Expand Context` *(Perluas Potongan Sebelum & Sesudahnya)*
* **Cara kerja sederhana:** Normalnya, setiap hasil hanya menampilkan 1 potongan teks inti (±1 paragraf atau 1 tabel). Jika opsi ini dicentang, sistem otomatis ikut mengambil **potongan teks tepat sebelum dan sesudah** bagian yang ditemukan di halaman dokumen.
* **Efek jika DICENTANG:**
  * Teks yang ditampilkan menjadi **lebih panjang dan utuh konteksnya**.
  * Sangat berguna jika potongan hasil terasa "tanggung", kalimatnya terpotong, atau Anda ingin membaca langkah sebelum dan sesudah prosedur tersebut.
  * *Efek ke tampilan:* Kartu hasil menjadi lebih panjang untuk dibaca.
* **Efek jika TIDAK dicentang *(Default)*:**
  * Tampilan hasil tetap **ringkas, fokus, dan mudah dipindai** dengan cepat.

---

### ☑️ 5. `Knowledge Graph (Lintas Dokumen)` *(Zero-LLM berbasis BAAI/bge-m3)*
* **Cara kerja sederhana:** Saat sebuah Knowledge berisi beberapa dokumen (misalnya SOP, Checklist, Struktur Organisasi, dan Excel), sistem secara otomatis memetakan **entitas penghubung bersama** (seperti `Head Barista`, `SOP-CHIL-09`, `Mesin Espresso`) serta **jembatan kemiripan makna (`BAAI/bge-m3`)** antar file berbeda tanpa LLM. Saat diaktifkan, pencarian tidak berhenti di 1 dokumen saja, melainkan ikut melompat 1-hop ke dokumen terkait lainnya lalu memverifikasinya dengan Cross-Encoder Reranker.
* **Efek jika DICENTANG *(Disarankan)*:**
  * Jawaban lintas dokumen (*multi-hop*) seperti *"Siapa penanggung jawab prosedur X dan bagaimana checklist-nya?"* ikut ditemukan meskipun tidak semua kata kuncinya ada di satu file.
  * Memunculkan badge hijau **`Via Graph`** beserta alasan jalur keterhubungannya dan tag **`Entitas terkait`** di setiap kartu hasil.
  * *Efek ke kecepatan:* Sangat cepat (~**+0,02 detik** di PostgreSQL, 100% lokal tanpa biaya token LLM).
* **Efek jika TIDAK dicentang:**
  * Pencarian hanya mengandalkan kemiripan langsung antara teks pertanyaan dan masing-masing potongan dokumen secara terpisah.

---

## 3. Cara Membaca Angka & Label di Hasil Pencarian

Saat hasil muncul, Anda akan melihat beberapa label kecil berwarna di kanan atas setiap kartu hasil:

1. **`Rerank XX%` (Label Biru):**
   * Muncul jika `Cross-Encoder Reranker` dicentang.
   * **Ini adalah indikator paling dapat dipercaya** bahwa teks tersebut benar-benar menjawab pertanyaan Anda. Nilai di atas `70%` berarti sangat relevan.
2. **`XX% Kemiripan` (Label Hijau / Biru / Kuning):**
   * Menunjukkan tingkat kedekatan makna (*semantic similarity*) antara pertanyaan dan potongan dokumen.
3. **`FTS 0.XX` (Label Kuning):**
   * Muncul jika ada kata kunci atau kode yang cocok secara persis di dalam potongan teks tersebut.
4. **`Via Graph` (Label Hijau + Banner Jalur Relasi):**
   * Muncul jika potongan dokumen tersebut berhasil diselamatkan melalui jembatan relasi **Zero-LLM Knowledge Graph** lintas file (misalnya terhubung lewat konsep bersama atau jembatan semantik `BAAI/bge-m3`).
5. **`Bagian: ...` (Teks Hijau di atas konten):**
   * Menunjukkan judul bab/sub-judul tempat potongan teks itu berada (misal: `Bagian: SOP Cafe > 2. Kode Alat & Sanitasi`), sehingga Anda langsung tahu konteksnya walaupun isi potongannya hanya berupa tabel atau daftar poin.
6. **`Score Threshold (KKM)`:**
   * Angka batas minimal kelulusan hasil (default `0.35` atau `35%`).
   * Jika hasil pencarian kosong, coba turunkan angka KKM ke `0.20` atau `0.15`. Sebaliknya, jika hasil terlalu banyak yang kurang nyambung, naikkan ke `0.50`.

---

## 4. Rekomendasi Paket Setting ("Tinggal Pilih Sesuai Kebutuhan")

| Kebutuhan Anda | Mode Retrieval | Reranker | Query Expansion | Knowledge Graph | HyDE | Expand Context |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Sehari-hari & Lintas Dokumen (Rekomendasi)** | `Hybrid` | ☑️ Aktif | ☑️ Aktif | ☑️ Aktif | ⬜ Mati | ⬜ Mati |
| **Cari Kode Alat / Nomor Surat / Nama Persis** | `Keyword Only` | ⬜ Mati | ⬜ Mati | ⬜ Mati | ⬜ Mati | ⬜ Mati |
| **Pertanyaan Panjang / Lupa Istilah Dokumen** | `Hybrid` | ☑️ Aktif | ☑️ Aktif | ☑️ Aktif | ☑️ Aktif | ⬜ Mati |
| **Baca Prosedur Lengkap Sebelum & Sesudah** | `Hybrid` | ☑️ Aktif | ☑️ Aktif | ☑️ Aktif | ⬜ Mati | ☑️ Aktif |
| **Kecepatan Maksimal (Server Tanpa GPU)** | `Hybrid` | ⬜ Mati | ☑️ Aktif | ☑️ Aktif | ⬜ Mati | ⬜ Mati |
