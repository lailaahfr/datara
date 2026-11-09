const LATAR_STATUS = {Normal: "#dbeafe", Waspada: "#fef0c7", Lonjakan: "#fde1d3"};
const LATAR_TINGKAT = {"Prioritas tinggi": "#fde1d3", "Pantau ketat": "#fef0c7", "Aman": "#dbeafe"};
const WARNA_TINGKAT = {"Prioritas tinggi": "#dc2626", "Pantau ketat": "#f2a900", "Aman": "#2b6cb0"};

function sel(teks, latar) {
  return `<span class="status" style="background:${latar || "transparent"}">${esc(teks)}</span>`;
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
  const tile = (nama, n, warna, ket) => `<div class="kartu stat" style="border-top:3px solid ${warna}"><div class="lbl">${nama}</div><div class="angka" style="color:${warna}">${n}</div><div class="ket">${ket}</div></div>`;
  $("k-tiles").innerHTML = tile("Prioritas tinggi", j.tinggi, "#dc2626", `skor di atas 50, dari ${j.total} pasar`) +
    tile("Pantau ketat", j.pantau, "#f2a900", "skor 25 sampai 50") + tile("Aman", j.aman, "#2b6cb0", "skor di bawah 25");
  $("k-tabel").querySelector("tbody").innerHTML = d.tabel.map((r, i) =>
    `<tr><td><span class="nama">${i + 1}. ${esc(r.pasar)}</span><span class="prov">${esc(r.provinsi)}</span></td><td>${sel(r.prediksi, LATAR_STATUS[r.prediksi])}</td>` +
    `<td>${sel(r.tingkat, LATAR_TINGKAT[r.tingkat])}<br><span class="bar" style="margin-top:.4rem"><b style="width:${Math.min(100, r.skor)}%;background:${WARNA_TINGKAT[r.tingkat]}"></b></span>${r.skor.toFixed(0)}/100</td>` +
    `<td>${esc(r.alasan)}</td></tr>`).join("");
  $("k-unduh").href = "/unduh/rekomendasi.csv?" + new URLSearchParams({prov: $("k-prov").value});
}

$("k-prov").addEventListener("change", muatPeringatan);
muatPeringatan();