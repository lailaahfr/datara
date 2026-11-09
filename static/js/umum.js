const SEMUA_PROV = "Semua Provinsi";
const SEMUA_KAB = "Semua Kota/Kabupaten";
const aturPlot = {responsive: true, displaylogo: false};
const fontPlot = {family: "Figtree, system-ui, sans-serif", color: "#243a32", size: 12};
const $ = (id) => document.getElementById(id);

function esc(t) {
  const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t);
  return d.innerHTML;
}

function angka(n, desimal) {
  return Number(n).toLocaleString("id-ID", {minimumFractionDigits: desimal || 0, maximumFractionDigits: desimal || 0});
}

function judulKab(k) {
  return k === SEMUA_KAB ? k : k.toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase());
}

async function ambil(url, params) {
  const q = new URLSearchParams(params || {}).toString();
  const r = await fetch(q ? url + "?" + q : url);
  if (!r.ok) throw new Error("Gagal memuat data (" + r.status + ")");
  return r.json();
}

function pesan(id, teks) {
  const el = $(id);
  if (!el) return;
  el.hidden = !teks;
  el.textContent = teks || "";
}

function gambar(id, fig) {
  fig.layout.font = fontPlot;
  fig.layout.paper_bgcolor = "rgba(0,0,0,0)";
  fig.layout.plot_bgcolor = "rgba(0,0,0,0)";
  ["xaxis", "yaxis"].forEach((a) => { fig.layout[a] = Object.assign({gridcolor: "#e1efe6", zerolinecolor: "#cfe3d7"}, fig.layout[a]); });
  return Plotly.react(id, fig.data, fig.layout, aturPlot);
}

function memuat(id, nyala) {
  const el = $(id);
  if (el) el.classList.toggle("memuat", nyala);
}

async function isiKab(selProv, selKab) {
  const daftar = await ambil("/api/kab", {prov: $(selProv).value});
  const sel = $(selKab);
  sel.innerHTML = "";
  [SEMUA_KAB].concat(daftar).forEach((k) => {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = k === SEMUA_KAB ? (selKab.startsWith("h-") ? k : "Semua") : judulKab(k);
    sel.appendChild(o);
  });
}

const geoCache = {};
async function geoUntuk(kunci) {
  if (!geoCache[kunci]) geoCache[kunci] = await ambil("/api/geo/" + kunci);
  return geoCache[kunci];
}

const hamburger = $("hamburger");
if (hamburger) {
  hamburger.addEventListener("click", () => {
    const buka = $("menu").classList.toggle("buka");
    hamburger.setAttribute("aria-expanded", buka);
  });
}