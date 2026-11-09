# DATARA: Sistem Informasi Pemantauan dan Prediksi Harga Pangan Indonesia

DATARA adalah sistem informasi berbasis web (Flask) untuk memantau dan memprediksi harga 9 komoditas pangan di 222 pasar Indonesia. Sistem menggabungkan tiga sumber data (harga pangan World Bank RTFP, cuaca NASA POWER, dan indeks iklim ENSO dari NOAA, ditambah kalender Ramadan) lalu menghasilkan peta harga, prediksi harga 6 bulan, dan peringatan dini lonjakan harga berupa daftar pasar berisiko tertinggi bulan depan.

---

## Latar Belakang

Harga pangan yang naik tiba-tiba menekan rumah tangga berpendapatan rendah dan menyulitkan pemerintah daerah menentukan di mana harus bertindak lebih dulu. Pantauan yang ada umumnya berupa angka rata-rata nasional, padahal harga dan gejolaknya berbeda jauh antarwilayah dan antarpasar.

DATARA menjawab tiga pertanyaan: berapa harga pangan di tiap wilayah dan seberapa bergejolak, ke mana arah harga enam bulan ke depan, dan pasar mana yang berisiko mengalami lonjakan harga bulan depan.

---

## Dataset dan Sumber Data

### 1. Harga Pangan (utama)
- Sumber: World Bank, Real-Time Food Prices (RTFP) Indonesia
- Cakupan: 222 pasar, 34 provinsi, 111 kabupaten/kota, 9 komoditas, Januari 2007 sampai Agustus 2026
- Ukuran setelah pembersihan: 52.392 baris x 78 kolom
- Isi: harga open-high-low-close bulanan, inflasi tahunan, dan skor kepercayaan per komoditas
- Peran: sumber target (status inflasi) dan seluruh visualisasi harga

### 2. Cuaca Bulanan
- Sumber: NASA POWER (API titik, komunitas AG)
- Variabel: curah hujan terkoreksi (PRECTOTCORR) dan suhu 2 m (T2M) di koordinat tiap pasar
- Peran: fitur prediktor (anomali terhadap baseline 2007 sampai 2019, jeda 0 sampai 2 bulan)

### 3. Indeks ENSO dan Kalender Ramadan
- Sumber: NOAA Climate Prediction Center (Oceanic Nino Index) dan kalender Hijriah tabular
- Peran: fitur prediktor (ONI saat ini dan jeda 3 bulan, penanda Ramadan dan Idulfitri bulan ini dan bulan depan)

### 4. Batas Wilayah
- Sumber: GADM 4.1 (level 1 provinsi dan level 2 kabupaten/kota)
- Peran: peta. Pasar dicocokkan ke poligon lewat koordinat (point-in-polygon, dengan cadangan poligon terdekat maksimal 10 km; kenyataannya jarak terjauh 0,66 km)

---

## Pemodelan

### Prediksi harga (regresi, per komoditas dan wilayah)
Empat kandidat model: harga tetap, tren teredam, linear 36 bulan, dan polinomial derajat 2 36 bulan. Model dipilih otomatis lewat uji mundur (rolling backtest) 24 bulan dengan metrik MAPE 6 langkah. Pita ketidakpastian diambil dari persentil ke-90 kesalahan relatif uji mundur per horizon.

### Klasifikasi status inflasi (supervised learning)
- Label: status inflasi tahunan indeks pangan pada bulan berikutnya, yaitu Normal (di bawah 5%), Waspada (5% sampai di bawah 10%), Lonjakan (10% ke atas)
- Pembagian data menurut waktu, data uji mulai November 2022
- Model: Decision Tree (3 fitur), Decision Tree (diperkaya), Random Forest (diperkaya), dan Random Forest dengan data eksternal bila `data/external/` tersedia
- Baseline: tebakan sederhana (status bulan depan sama dengan bulan ini) dan selalu menebak Normal

### Klastering pasar (unsupervised learning)
K-Means pada profil harga dan gejolak tiap pasar, jumlah klaster dipilih dengan silhouette (k = 3 sampai 6). Terpilih k = 4 dengan silhouette sekitar 0,18, yang berarti pemisahan klaster cukup lemah dan dipakai sebagai pengelompokan kasar, bukan batas tegas.

### Skor prioritas pasar
Skor = 0,6 x risiko (0,5 x P(Waspada) + 1,0 x P(Lonjakan)) + 0,2 x momentum inflasi + 0,2 x persentil volatilitas tipe pasar. Prioritas tinggi bila skor di atas 50, pantau ketat bila di atas 25. Bobot dan ambang ditetapkan kelompok sebagai asumsi, bukan hasil estimasi.

---

## Hasil Eksperimen

Klasifikasi status inflasi pada data uji (hanya data RTFP; hasil dengan cuaca dan ENSO muncul setelah `notebooks/9_data_tambahan.ipynb` dijalankan):

| Model atau baseline        | Akurasi | F1 (macro) |
| -------------------------- | ------: | ---------: |
| Decision Tree (3 fitur)    |   0,643 |      0,573 |
| Decision Tree (diperkaya)  |   0,646 |      0,574 |
| Random Forest (diperkaya)  |   0,681 |      0,594 |
| Tebakan sederhana          |   0,707 |      0,603 |
| Selalu tebak Normal        |   0,655 |      0,264 |

Baseline "tebakan sederhana" masih sedikit lebih baik daripada semua model, karena inflasi tahunan sangat persisten dari bulan ke bulan. Nilai tambah model ada pada fungsinya sebagai pemeringkat risiko: lihat uji peringkat di halaman Insight, yaitu berapa persen lonjakan aktual yang tertangkap oleh 10% pasar teratas.

Prediksi harga (MAPE uji mundur 6 langkah) bervariasi per komoditas, mulai sekitar 0,8% (beras) sampai sekitar 10,9% (bawang merah); untuk beberapa komoditas model terpilih adalah harga tetap, artinya tidak ada tren yang dapat diandalkan.

---

## Cara Menjalankan

### 1. Pasang pustaka
```bash
pip install -r requirements.txt
```

### 2. Siapkan data
Taruh data mentah di `data/raw/IDN_RTFP_mkt_2007_2026-08-24.csv`, lalu jalankan secara berurutan:
```text
notebooks/1_cleaning.ipynb          -> data/processed/data_bersih.csv
notebooks/9_data_tambahan.ipynb     -> data/external/  (perlu internet, boleh dilewati)
notebooks/8_peta_wilayah.ipynb      -> data/geo/ dan data/processed/pasar_wilayah.csv
```
Notebook 2 sampai 7 bersifat analisis dan bahan laporan; dashboard melatih modelnya sendiri sehingga tidak harus menunggu notebook itu.

### 3. Jalankan dashboard
```bash
python app.py
```
Buka http://127.0.0.1:5000. Untuk server produksi: `gunicorn app:app`.

Model halaman Insight dilatih di latar belakang saat server menyala (sekitar 10 detik), sehingga tab itu siap saat dibuka.

---

## Halaman Dashboard

- **Beranda** (`/`): ringkasan nasional (jumlah komoditas, berapa yang naik, turun, stabil), kartu sembilan komoditas dengan harga, perubahan bulanan, inflasi tahunan, dan grafik mini 12 bulan (bisa diurutkan dan dicari), serta peta harga per wilayah dengan filter komoditas, tahun, provinsi, dan kota/kabupaten, lengkap dengan tabel wilayah di sampingnya.
- **Komoditas** (`/komoditas`): tabel perbandingan harga dan inflasi semua komoditas. Tiap komoditas punya halaman detail (`/komoditas/beras`) berisi pasar termurah dan termahal, grafik candlestick dengan prediksi 6 bulan dan pita ketidakpastian, grafik inflasi y/y, peringkat 10 provinsi dengan inflasi tertinggi, dan tabel harga per provinsi.
- **Insight** (`/insight`): 10 pasar dengan risiko lonjakan tertinggi bulan depan (prediksi, skor, alasan) sebagai peringatan dini agar intervensi seperti operasi pasar dapat diantisipasi lebih awal, dengan filter provinsi dan unduhan CSV; di bawahnya faktor eksternal yang dipakai model: inflasi pangan dengan penanda Ramadan, curah hujan dan suhu NASA POWER, serta indeks ENSO NOAA.

---

## Keterbatasan

- Model status inflasi belum mengungguli baseline sederhana pada metrik akurasi dan F1.
- Hanya 22% poligon kabupaten/kota memiliki pasar, sehingga sebagian besar peta tingkat kabupaten berwarna abu-abu.
- Survei harga langsung tidak tersedia di semua tahun (0% pada 2007 sampai 2015 dan 2018 sampai 2019); pasar tanpa survei langsung dalam 12 bulan diberi tanda perlu verifikasi.
- Pengolahan memakai pandas dan scikit-learn pada satu mesin; data berukuran puluhan ribu baris dari tiga sumber, bukan skala terdistribusi.

---

## Teknologi yang Digunakan

- Python, Flask
- pandas, NumPy, scikit-learn, matplotlib
- Plotly.js (grafik dan peta di browser)
- Jupyter Notebook
- requests (pengambilan data NASA POWER dan NOAA)

---

## Sumber dan Lisensi Data

- World Bank, Real-Time Food Prices (RTFP) Indonesia
- NASA POWER (https://power.larc.nasa.gov)
- NOAA Climate Prediction Center, Oceanic Nino Index
- GADM versi 4.1 (https://gadm.org), untuk penggunaan akademik non-komersial dengan menyebut sumbernya