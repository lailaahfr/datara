function itemTerpilih() { return $("h-item").value; }

async function muatPeta() {
  const params = {item: itemTerpilih(), tahun: $("h-tahun").value, prov: $("h-prov").value, kab: $("h-kab").value,
                  lapisan: document.querySelector("input[name=lapisan]:checked").value};
  memuat("h-peta", true);
  let d;
  try { d = await ambil("/api/peta", params); } catch (e) { memuat("h-peta", false); pesan("h-pesan", e.message); return; }
  memuat("h-peta", false);
  if (d.kosong) {
    pesan("h-pesan", d.kosong);
    Plotly.purge("h-peta");
    $("h-legenda").innerHTML = "";
    $("h-tabel").querySelector("tbody").innerHTML = "";
    return;
  }
  pesan("h-pesan", "");
  const p = d.peta;
  p.data[0].geojson = await geoUntuk(p.geo);
  $("peta-sub").textContent = `${d.komoditas}, ${d.wilayah}, rata-rata tahun ${params.tahun}`;
  $("h-legenda").innerHTML = p.legenda.map((l) => `<span><i style="background:${esc(l.warna)}"></i>${esc(l.teks)}</span>`).join("");
  gambar("h-peta", p);
  $("h-catatan").textContent = p.catatan;
  $("h-kolom").textContent = p.kolom_nilai;
  const harga = params.lapisan === "Tingkat harga";
  const urut = p.tabel.slice();
  $("h-tabel").querySelector("tbody").innerHTML = urut.length ? urut.map((t, i) => {
    const nilai = (harga && t.nilai > 0 ? "+" : "") + angka(t.nilai, 1) + "%";
    const cls = harga ? (t.nilai > 2 ? "naik" : t.nilai < -2 ? "turun" : "stabil") : "stabil";
    const tanda = i === 0 && urut.length > 1 ? ' <span class="lencana turun">Termurah</span>' : i === urut.length - 1 && urut.length > 1 ? ' <span class="lencana naik">Termahal</span>' : "";
    return `<tr><td class="nama">${esc(t.nama)}${tanda}<span class="prov">${esc(t.kelas)}, ${t.n} pasar</span></td><td class="kanan tab-num"><b>${angka(t.harga)}</b></td><td class="kanan tab-num ${cls}">${nilai}</td></tr>`;
  }).join("") : '<tr><td colspan="3" class="sub">Belum ada data pasar.</td></tr>';
}

async function muatRisiko() {
  const kotak = $("risiko");
  try {
    const d = await ambil("/api/keputusan", {prov: SEMUA_PROV});
    if (d.kosong || !d.tabel.length) { kotak.innerHTML = '<p class="sub" style="padding:.7rem 0">Data belum cukup untuk daftar pasar.</p>'; return; }
    kotak.innerHTML = d.tabel.slice(0, 3).map((r) =>
      `<a href="/insight"><span>${esc(r.pasar)}<small>${esc(r.provinsi)}</small></span><b>${r.skor.toFixed(0)}/100</b></a>`).join("");
  } catch (e) {
    kotak.innerHTML = '<p class="sub" style="padding:.7rem 0">Daftar pasar belum bisa dimuat.</p>';
  }
}

document.querySelectorAll("#chips-kom .chip-kom").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#chips-kom .chip-kom").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
  $("h-item").value = b.dataset.item;
  muatPeta();
}));
["h-tahun", "h-kab"].forEach((id) => $(id).addEventListener("change", muatPeta));
document.querySelectorAll("input[name=lapisan]").forEach((r) => r.addEventListener("change", muatPeta));
$("h-prov").addEventListener("change", async () => { await isiKab("h-prov", "h-kab"); muatPeta(); });
muatPeta();
muatRisiko();