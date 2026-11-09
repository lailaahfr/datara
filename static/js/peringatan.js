const WARNA_TINGKAT = {"Prioritas tinggi": "#ee7f6b", "Pantau ketat": "#f6c85f", "Aman": "#8fc4ee"};

function sel(teks) {
  return `<span class="status ${esc(teks.replace(" ", "-"))}">${esc(teks)}</span>`;
}

async function muatPeringatan() {
  pesan("k-pesan", "Menyiapkan model, tunggu sebentar...");
  $("k-isi").hidden = true;
  let d;
  try { d = await ambil("/api/keputusan", {prov: $("k-prov").value}); } catch (e) { pesan("k-pesan", e.message); return; }
  if (d.kosong) { pesan("k-pesan", d.kosong); return; }
  pesan("k-pesan", "");
  $("k-isi").hidden = false;
  $("k-judul").textContent = d.judul;
  $("k-ringkas").textContent = d.ringkas;
  const j = d.jumlah;
  const tile = (nama, n, nada, ket) => `<div class="kartu stat ${nada}"><div class="lbl">${nama}</div><div class="angka">${n}</div><div class="ket">${ket}</div></div>`;
  $("k-tiles").innerHTML = tile("Prioritas tinggi", j.tinggi, "nada-naik", `pasar, skor di atas 50, dari ${j.total} pasar`) +
    tile("Pantau ketat", j.pantau, "nada-waspada", "pasar, skor 25 sampai 50") + tile("Aman", j.aman, "nada-biru", "pasar, skor di bawah 25");
  $("k-tabel").querySelector("tbody").innerHTML = d.tabel.map((r, i) =>
    `<tr><td><span class="nama">${i + 1}. ${esc(r.pasar)}</span><span class="prov">${esc(r.provinsi)}</span></td><td>${sel(r.prediksi)}</td>` +
    `<td>${sel(r.tingkat)}<br><span class="bar" style="margin-top:.4rem"><b style="width:${Math.min(100, r.skor)}%;background:${WARNA_TINGKAT[r.tingkat]}"></b></span>${r.skor.toFixed(0)}/100</td>` +
    `<td>${esc(r.alasan)}</td></tr>`).join("");
  $("k-unduh").href = "/unduh/rekomendasi.csv?" + new URLSearchParams({prov: $("k-prov").value});
}

$("k-prov").addEventListener("change", muatPeringatan);
muatPeringatan();