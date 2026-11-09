function kartuSumber(judul, nilai, sub, ada) {
  return `<div class="kartu sumber kartu-pad"><div class="lbl">${esc(judul)}</div><div class="nilai">${esc(nilai)}</div><div class="ket">${esc(sub)}</div>` +
    `<div class="st"><i class="${ada ? "ada" : ""}"></i>${ada ? "Data tersedia" : "Belum diambil"}</div></div>`;
}

function kosongEks(id, teks) {
  const el = $(id);
  el.hidden = false;
  el.innerHTML = teks;
}

async function muatEksternal() {
  memuat("e-ramadan", true);
  let d;
  try { d = await ambil("/api/eksternal", {prov: $("e-prov").value, kab: $("e-kab").value}); } catch (e) { memuat("e-ramadan", false); return; }
  memuat("e-ramadan", false);
  const perintah = 'Jalankan <code>notebooks/9_data_tambahan.ipynb</code> lalu restart server.';
  const rs = d.ramadan_stat;
  $("e-kartu").innerHTML =
    kartuSumber("Kalender Ramadan", d.ramadan_berikut || "-", "Ramadan berikutnya", true) +
    (d.cuaca_kartu ? kartuSumber("Curah hujan " + d.cuaca_kartu.bulan, angka(d.cuaca_kartu.hujan, 1) + " mm/hari",
        `Normal bulan ini ${angka(d.cuaca_kartu.hujan_normal, 1)} mm/hari, suhu ${angka(d.cuaca_kartu.suhu, 1)} C`, true)
      : kartuSumber("Cuaca (NASA POWER)", "-", "Curah hujan dan suhu bulanan", false)) +
    (d.oni_kartu ? kartuSumber("ENSO " + d.oni_kartu.bulan, d.oni_kartu.teks, "Fase: " + d.oni_kartu.fase, true)
      : kartuSumber("ENSO (NOAA ONI)", "-", "Indeks El Nino dan La Nina", false));
  if (d.grafik_ramadan) {
    gambar("e-ramadan", d.grafik_ramadan);
    $("e-ramadan-cat").textContent = rs && rs.saat !== null && rs.lain !== null
      ? `Rata-rata inflasi y/y indeks pangan: ${angka(rs.saat, 1)}% pada bulan Ramadan dibanding ${angka(rs.lain, 1)}% pada bulan lain (8 tahun terakhir). Ini deskripsi, bukan bukti sebab-akibat.` : "";
  } else {
    Plotly.purge("e-ramadan");
  }
  if (d.grafik_cuaca) { $("e-cuaca-kosong").hidden = true; gambar("e-cuaca", d.grafik_cuaca); }
  else { Plotly.purge("e-cuaca"); kosongEks("e-cuaca-kosong", "Data cuaca NASA POWER belum diambil. " + perintah); }
  if (d.grafik_oni) { $("e-oni-kosong").hidden = true; gambar("e-oni", d.grafik_oni); }
  else { Plotly.purge("e-oni"); kosongEks("e-oni-kosong", "Data ONI NOAA belum diambil. " + perintah); }
}

const wilayahE = () => ({prov: $("e-prov").value, kab: $("e-kab").value});
const KATA_R = {"sangat lemah": "hampir tidak ada hubungan", "lemah": "hubungan lemah", "sedang": "hubungan sedang", "kuat": "hubungan kuat"};

async function muatHubungan() {
  if (!$("x-grafik")) return;
  memuat("x-grafik", true);
  let d;
  try { d = await ambil("/api/hubungan", Object.assign({item: $("x-item").value, faktor: $("x-faktor").value, jeda: $("x-jeda").value}, wilayahE())); } catch (e) { memuat("x-grafik", false); $("x-catatan").textContent = e.message; return; }
  memuat("x-grafik", false);
  if (d.kosong) { Plotly.purge("x-grafik"); $("x-catatan").textContent = d.kosong; $("x-chip").innerHTML = ""; return; }
  gambar("x-grafik", d.grafik);
  $("x-chip").innerHTML = d.r === null ? '<div class="chip"><b>-</b>data belum cukup untuk korelasi</div>'
    : `<div class="chip"><b>r = ${esc(d.r_teks)}</b>${esc(KATA_R[d.kekuatan])}</div><div class="chip"><b>${d.n} bulan</b>data yang dipakai</div>`;
  $("x-catatan").textContent = d.r === null ? "" : "Korelasi hanya menunjukkan kedua garis bergerak searah atau berlawanan, bukan bahwa satu menyebabkan yang lain.";
}

async function muatKorelasi() {
  if (!$("x-tabel")) return;
  const d = await ambil("/api/korelasi", wilayahE());
  if (d.kosong) return;
  $("x-kepala").innerHTML = "<th>Komoditas</th>" + d.faktor.map((f) => `<th class="kanan">${esc(f.nama)}</th>`).join("");
  $("x-tabel").querySelector("tbody").innerHTML = d.baris.map((b) =>
    `<tr><td><a class="nama" href="/komoditas/${esc(b.slug)}">${esc(b.nama)}</a></td>` + d.faktor.map((f) => {
      const c = b.sel[f.kunci];
      if (!c) return '<td class="kanan sub">-</td>';
      const a = Math.min(1, Math.abs(c.r) / 0.6);
      const warna = c.r >= 0 ? `rgba(238,127,107,${(a * 0.45).toFixed(2)})` : `rgba(143,196,238,${(a * 0.55).toFixed(2)})`;
      return `<td class="kanan tab-num" style="background:${warna}"><b>${esc(c.teks)}</b><span class="prov">jeda ${c.jeda} bulan</span></td>`;
    }).join("") + "</tr>").join("");
}

function muatSemuaEks() { muatEksternal(); muatHubungan(); muatKorelasi(); }
["x-item", "x-faktor", "x-jeda"].forEach((id) => { if ($(id)) $(id).addEventListener("change", muatHubungan); });
$("e-kab").addEventListener("change", muatSemuaEks);
$("e-prov").addEventListener("change", async () => { await isiKab("e-prov", "e-kab"); muatSemuaEks(); });
muatSemuaEks();