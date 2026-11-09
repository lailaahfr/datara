const grid = $("grid-kom");
let urutan = "naik";

function terapkanUrutan() {
  const kartu = Array.from(grid.children);
  const kunci = {
    naik: (a, b) => b.dataset.mom - a.dataset.mom,
    turun: (a, b) => a.dataset.mom - b.dataset.mom,
    mahal: (a, b) => b.dataset.harga - a.dataset.harga,
    murah: (a, b) => a.dataset.harga - b.dataset.harga,
    az: (a, b) => a.dataset.nama.localeCompare(b.dataset.nama),
  }[urutan];
  kartu.sort(kunci).forEach((k) => grid.appendChild(k));
}

function terapkanCari() {
  const q = $("cari").value.trim().toLowerCase();
  let ada = 0;
  Array.from(grid.children).forEach((k) => {
    const cocok = !q || k.dataset.nama.includes(q);
    k.style.display = cocok ? "" : "none";
    if (cocok) ada++;
  });
  $("kosong-cari").hidden = ada > 0;
}

document.querySelectorAll("#urutan .pil").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#urutan .pil").forEach((x) => x.classList.toggle("aktif", x === b));
  urutan = b.dataset.urut;
  terapkanUrutan();
}));
$("cari").addEventListener("input", terapkanCari);
terapkanUrutan();

async function muatPeta() {
  const params = {item: $("h-item").value, tahun: $("h-tahun").value, prov: $("h-prov").value, kab: $("h-kab").value,
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

["h-item", "h-tahun", "h-kab"].forEach((id) => $(id).addEventListener("change", muatPeta));
document.querySelectorAll("input[name=lapisan]").forEach((r) => r.addEventListener("change", muatPeta));
$("h-prov").addEventListener("change", async () => { await isiKab("h-prov", "h-kab"); muatPeta(); });
muatPeta();
