async function muatPrediksi() {
  memuat("d-candle", true);
  let d;
  try { d = await ambil("/api/prediksi", {item: window.ITEM, prov: $("d-prov").value, kab: $("d-kab").value}); } catch (e) { memuat("d-candle", false); $("d-catatan").textContent = e.message; return; }
  memuat("d-candle", false);
  $("d-sub").textContent = `${d.wilayah}. Setiap batang adalah satu bulan harga.`;
  if (d.candle) gambar("d-candle", d.candle); else Plotly.purge("d-candle");
  const r = d.ringkasan, c = d.candle_ringkas;
  $("d-chip").innerHTML = (r ? `<div class="chip"><b>Rp ${angka(r.harga)}/kg</b>harga rata-rata ${esc(r.bulan)}</div>` : "") +
    (c ? `<div class="chip"><b>${esc(c.tujuan)}</b>prediksi ${esc(c.bulan)} (${esc(c.perubahan)})</div><div class="chip"><b>${esc(c.model)}</b>model terpilih</div>` : "");
  $("d-catatan").textContent = d.candle_catatan || d.candle_info || "";
}

async function muatInflasi() {
  memuat("d-inflasi", true);
  let d;
  try { d = await ambil("/api/inflasi", {item: window.ITEM, prov: $("d-prov").value, kab: $("d-kab").value}); } catch (e) { memuat("d-inflasi", false); return; }
  memuat("d-inflasi", false);
  if (d.kosong) {
    Plotly.purge("d-inflasi");
    $("d-inflasi").textContent = d.kosong;
    return;
  }
  $("d-inflasi").textContent = "";
  gambar("d-inflasi", d.grafik);
  gambar("d-ranking", d.ranking);
  $("d-bulan-rank").textContent = "Bulan " + d.bulan_ranking + ", rata-rata semua pasar per provinsi";
}

function muatSemua() { muatPrediksi(); muatInflasi(); }
$("d-kab").addEventListener("change", muatSemua);
$("d-prov").addEventListener("change", async () => { await isiKab("d-prov", "d-kab"); muatSemua(); });
muatSemua();
