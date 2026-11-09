import json
import math
import os
import threading

import numpy as np
import pandas as pd
from flask import Flask, Response, abort, redirect, render_template, request

import inti
from inti import (BATAS_HARGA_PERSEN, BATAS_LONJAKAN, BATAS_PANTAU, BATAS_PRIORITAS, BATAS_WASPADA, BOBOT_MOMENTUM, BOBOT_RISIKO,
                  BOBOT_VOLATILITAS, KOL_PASAR, KOL_TANGGAL, KOMODITAS, NAMA_KELAS, NAMA_KOMODITAS, batas_geometri, prediksi_harga,
                  status_inflasi, tabel_peta, zoom_dari_batas)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "processed", "data_bersih.csv")
PASAR_WILAYAH_PATH = os.path.join(BASE_DIR, "data", "processed", "pasar_wilayah.csv")
GEO_PROVINSI_PATH = os.path.join(BASE_DIR, "data", "geo", "provinsi.geojson")
GEO_KAB_PATH = os.path.join(BASE_DIR, "data", "geo", "kabkota.geojson")
CUACA_PATH = os.path.join(BASE_DIR, "data", "external", "cuaca_bulanan.csv")
ONI_PATH = os.path.join(BASE_DIR, "data", "external", "oni.csv")

KOL_PROVINSI = "adm1_name"
KOL_KABUPATEN = "adm2_name"
SEMUA_PROV = "Semua Provinsi"
SEMUA_KAB = "Semua Kota/Kabupaten"

WARNA_HARGA = {"Murah": "#8fc4ee", "Sedang": "#f6e7b4", "Mahal": "#ee8a78"}
WARNA_VOLATILITAS = {"Stabil": "#e3f3ea", "Sedang": "#9fd4b8", "Bergejolak": "#2b7f5e"}
WARNA_TANPA_DATA = "#dcdcdc"
WARNA_STATUS = {"Normal": "#8fc4ee", "Waspada": "#f6c85f", "Lonjakan": "#ee7f6b"}
JUMLAH_PRODUK_UJI = 24
BULAN_PREDIKSI = 6
NAMA_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


def label(item):
    return NAMA_KOMODITAS.get(item, item.replace("_", " ").title())


def bulan_id(tanggal, singkat=False):
    nama = NAMA_BULAN[tanggal.month - 1]
    return f"{nama[:3] if singkat else nama} {tanggal.year}"


def dec(nilai, desimal=1, tanda=False):
    return f"{nilai:{'+' if tanda else ''}.{desimal}f}".replace(".", ",")


def rupiah(nilai):
    return "Rp " + f"{nilai:,.0f}".replace(",", ".")


def tgl(t):
    return pd.Timestamp(t).strftime("%Y-%m-%d")


def bersih(obj):
    if isinstance(obj, dict):
        return {str(k): bersih(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [bersih(v) for v in obj]
    if isinstance(obj, (pd.Series, pd.Index)):
        return bersih(obj.tolist())
    if isinstance(obj, np.ndarray):
        return bersih(obj.tolist())
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return tgl(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if math.isnan(obj) or math.isinf(obj) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def balas(isi, status=200):
    return Response(json.dumps(bersih(isi), ensure_ascii=False), status=status, mimetype="application/json")


def modus(s):
    s = s.dropna()
    return s.mode().iat[0] if len(s) else None


class Data:
    def __init__(self):
        self.galat = None
        self.df = None
        self.kunci_analisis = threading.Lock()
        self.analisis_cache = None
        self.sudah_hitung = False
        self.muat()

    def muat(self):
        if not os.path.exists(DATA_PATH):
            self.galat = "File data/processed/data_bersih.csv belum ada. Jalankan notebooks/1_cleaning.ipynb dulu."
            return
        if not all(os.path.exists(p) for p in (PASAR_WILAYAH_PATH, GEO_PROVINSI_PATH, GEO_KAB_PATH)):
            self.galat = "Data peta belum ada. Jalankan notebooks/7_peta_wilayah.ipynb dulu."
            return
        df = pd.read_csv(DATA_PATH)
        df.columns = [c.strip().lstrip("﻿") for c in df.columns]
        if KOL_TANGGAL not in df.columns and "price_date" in df.columns:
            df = df.rename(columns={"price_date": KOL_TANGGAL})
        if KOL_TANGGAL not in df.columns:
            self.galat = "Kolom 'date' tidak ditemukan. Jalankan notebooks/1_cleaning.ipynb lebih dulu."
            return
        df[KOL_TANGGAL] = pd.to_datetime(df[KOL_TANGGAL], errors="coerce")
        df = df.dropna(subset=[KOL_TANGGAL])
        df["bulan"] = df[KOL_TANGGAL].dt.to_period("M").dt.to_timestamp()
        self.df = df
        with open(GEO_PROVINSI_PATH) as berkas:
            self.geo_prov = json.load(berkas)
        with open(GEO_KAB_PATH) as berkas:
            self.geo_kab = json.load(berkas)
        self.batas = {f["id"]: batas_geometri(f["geometry"]) for f in self.geo_prov["features"] + self.geo_kab["features"]}
        pasar_wilayah = pd.read_csv(PASAR_WILAYAH_PATH).set_index(KOL_PASAR)
        self.info_pasar = (df.drop_duplicates(KOL_PASAR).set_index(KOL_PASAR)[[KOL_PROVINSI, KOL_KABUPATEN, "lat", "lon"]]
                           .join(pasar_wilayah[["gid_1", "gid_2", "nama_provinsi", "nama_kab_kota"]]))
        self.gid_provinsi = self.info_pasar.groupby(KOL_PROVINSI)["gid_1"].agg(modus)
        self.nama_prov = self.info_pasar.groupby(KOL_PROVINSI)["nama_provinsi"].agg(modus)
        self.ada_item = [k for k in KOMODITAS if f"c_{k}" in df.columns]
        self.item_inflasi = [k for k in KOMODITAS if f"inflation_{k}" in df.columns]
        self.tahun = sorted(df[KOL_TANGGAL].dt.year.unique().tolist(), reverse=True)
        self.cuaca = pd.read_csv(CUACA_PATH, parse_dates=["bulan"]) if os.path.exists(CUACA_PATH) else None
        self.oni = pd.read_csv(ONI_PATH, parse_dates=["bulan"]) if os.path.exists(ONI_PATH) else None
        sumber = ["World Bank RTFP"] + (["NASA POWER"] if self.cuaca is not None else []) + (["NOAA ONI"] if self.oni is not None else [])
        self.hero_sumber = ", ".join(sumber[:-1]) + " dan " + sumber[-1] if len(sumber) > 1 else sumber[0]

    def nama_provinsi(self, p):
        return self.nama_prov.get(p, p)

    def saring(self, prov, kab):
        d = self.df
        if prov != SEMUA_PROV:
            d = d[d[KOL_PROVINSI] == prov]
        if kab != SEMUA_KAB:
            d = d[d[KOL_KABUPATEN] == kab]
        return d

    def nama_wilayah(self, prov, kab):
        if kab != SEMUA_KAB:
            return kab.title()
        if prov != SEMUA_PROV:
            return self.nama_provinsi(prov)
        return "Seluruh Indonesia"

    def analisis(self):
        with self.kunci_analisis:
            if not self.sudah_hitung:
                self.analisis_cache = self.hitung_analisis()
                self.sudah_hitung = True
            return self.analisis_cache

    def hitung_analisis(self):
        df = self.df
        if f"inflation_{inti.KOL_INDEKS}" not in df.columns:
            return None
        out = inti.siapkan_fitur(df)
        fitur_kaya = inti.daftar_fitur_kaya(out)
        fitur_eksternal = None
        if self.cuaca is not None or self.oni is not None:
            out = inti.tambah_fitur_eksternal(out, self.cuaca, self.oni)
            fitur_eksternal = inti.daftar_fitur_eksternal(out)
        dm = inti.siapkan_data_model(out)
        if len(dm) < 200:
            return None
        is_train, tgl_potong = inti.pisah_waktu(dm)
        hasil = inti.bandingkan_model(dm, is_train, fitur_kaya, fitur_eksternal)
        terbaru, _, _ = inti.prediksi_terbaru(out, dm, hasil, fitur_kaya)
        klaster = inti.klaster_pasar(df)
        rek = inti.skor_rekomendasi(terbaru, klaster[0]).join(self.info_pasar[[KOL_PROVINSI]], on=KOL_PASAR)
        return {"hasil": hasil, "rek": rek, "bulan_akhir": terbaru[KOL_TANGGAL].max(), "tgl_potong": tgl_potong,
                "peringkat": inti.uji_peringkat(dm, is_train, hasil, 0.1)}


D = Data()
if D.df is not None:
    threading.Thread(target=D.analisis, daemon=True).start()


def baca_wilayah():
    prov = request.args.get("prov", SEMUA_PROV)
    kab = request.args.get("kab", SEMUA_KAB)
    if prov != SEMUA_PROV and prov not in D.gid_provinsi.index:
        prov = SEMUA_PROV
    return prov, kab


def titik_pusat(prov, kab, wilayah_data):
    gid_kab = None
    if kab != SEMUA_KAB:
        gid_kab = modus(wilayah_data.loc[wilayah_data[KOL_KABUPATEN] == kab, "gid_2"])
    if gid_kab in D.batas:
        batas = D.batas[gid_kab]
    elif prov != SEMUA_PROV and D.gid_provinsi.get(prov) in D.batas:
        batas = D.batas[D.gid_provinsi.get(prov)]
    else:
        batas = (95.0, -11.0, 141.0, 6.0)
    pusat = {"lat": (batas[1] + batas[3]) / 2, "lon": (batas[0] + batas[2]) / 2}
    return pusat, zoom_dari_batas(*batas)


def susun_peta(item, tahun, lapisan, prov, kab):
    wilayah_data = D.info_pasar[D.info_pasar[KOL_PROVINSI] == prov] if prov != SEMUA_PROV else D.info_pasar
    if prov == SEMUA_PROV:
        fitur, kolom_gid, tingkat = D.geo_prov["features"], "gid_1", "provinsi"
        geo = "provinsi"
    else:
        gid_pilih = D.gid_provinsi.get(prov)
        fitur = [f for f in D.geo_kab["features"] if f["properties"]["gid_1"] == gid_pilih]
        kolom_gid, tingkat = "gid_2", "kab/kota"
        geo = gid_pilih
    wil, pm = tabel_peta(D.df, D.info_pasar, item, tahun, lapisan, kolom_gid)
    peta_warna = WARNA_HARGA if lapisan == "Tingkat harga" else WARNA_VOLATILITAS
    urutan = list(peta_warna) + ["Tanpa data"]
    warna_urut = list(peta_warna.values()) + [WARNA_TANPA_DATA]
    ids, z, teks = [], [], []
    for f in fitur:
        gid = f["id"]
        nama = f["properties"]["nama"]
        ids.append(gid)
        if gid in wil.index:
            b = wil.loc[gid]
            z.append(urutan.index(b["kelas"]))
            if lapisan == "Tingkat harga":
                teks.append(f"<b>{nama}</b><br>Rata-rata: {rupiah(b['harga'])}/kg<br>Selisih dari median nasional: {dec(b['nilai'], 1, True)}%"
                            f"<br>Kelas: {b['kelas']}<br>Jumlah pasar: {int(b['n'])}")
            else:
                teks.append(f"<b>{nama}</b><br>Rentang harga bulanan: {dec(b['nilai'])}%<br>Rata-rata: {rupiah(b['harga'])}/kg"
                            f"<br>Kelas: {b['kelas']}<br>Jumlah pasar: {int(b['n'])}")
        else:
            z.append(len(urutan) - 1)
            teks.append(f"<b>{nama}</b><br>Tidak ada data pasar")
    skala = [[i / (len(urutan) - 1), w] for i, w in enumerate(warna_urut)]
    trace = [{"type": "choroplethmap", "locations": ids, "z": z, "zmin": 0, "zmax": len(urutan) - 1, "featureidkey": "id", "colorscale": skala,
              "showscale": False, "marker": {"opacity": 0.85, "line": {"width": 0.6, "color": "#ffffff"}}, "hovertext": teks, "hoverinfo": "text"}]
    titik = pm.join(D.info_pasar[["lat", "lon"]])
    if prov != SEMUA_PROV:
        titik = titik[titik.index.isin(wilayah_data.index)]
    if len(titik):
        trace.append({"type": "scattermap", "lat": titik["lat"], "lon": titik["lon"], "mode": "markers", "hoverinfo": "text",
                      "text": [f"<b>{n}</b><br>{rupiah(r['harga'])}/kg" for n, r in titik.iterrows()],
                      "marker": {"size": 5 if prov == SEMUA_PROV else 9, "color": "#1a1a1a"}})
    pusat, zoom = titik_pusat(prov, kab, wilayah_data)
    tata = {"map": {"style": "carto-positron", "center": pusat, "zoom": zoom}, "margin": {"l": 0, "r": 0, "t": 0, "b": 0}, "height": 600,
            "showlegend": False, "separators": ",."}
    hitung = pd.Series(z).map(dict(enumerate(urutan))).value_counts()
    if lapisan == "Tingkat harga":
        ket = {"Murah": "Murah", "Sedang": "Sedang", "Mahal": "Mahal"}
    else:
        ket = {"Stabil": "Stabil", "Sedang": "Sedang", "Bergejolak": "Bergejolak"}
    ket["Tanpa data"] = "Tanpa data"
    legenda = [{"teks": f"{ket[n]} ({int(hitung.get(n, 0))})", "warna": w} for n, w in zip(urutan, warna_urut)]
    if lapisan == "Tingkat harga":
        arti = f"Murah dan Mahal berarti harga lebih dari {BATAS_HARGA_PERSEN}% di bawah atau di atas median nasional."
    else:
        arti = "Gejolak harga adalah selisih harga tertinggi dan terendah dalam sebulan. Stabil adalah sepertiga terendah, Bergejolak sepertiga tertinggi."
    nama_gid = {f["id"]: f["properties"]["nama"] for f in fitur}
    tabel = [{"nama": nama_gid.get(g, g), "harga": float(r["harga"]), "nilai": float(r["nilai"]), "kelas": r["kelas"], "n": int(r["n"])}
             for g, r in wil.iterrows() if g in nama_gid]
    tabel.sort(key=lambda t: t["harga"])
    return {"data": trace, "layout": tata, "geo": geo, "legenda": legenda, "tabel": tabel, "kolom_nilai": "Selisih" if lapisan == "Tingkat harga" else "Gejolak",
            "tingkat": tingkat,
            "catatan": f"Rata-rata tahun {tahun}, per {tingkat}. {arti} Pilih provinsi untuk memperbesar peta."}


def ringkasan_harga(fw, item, prov, kab):
    c = fw.groupby("bulan")[f"c_{item}"].mean().dropna()
    if len(c) < 2:
        return None
    akhir = c.index[-1]
    tahun_lalu = c.get(akhir - pd.DateOffset(years=1), np.nan)
    inf = fw.groupby("bulan")[f"inflation_{item}"].mean().dropna() if f"inflation_{item}" in fw.columns else pd.Series(dtype=float)
    hasil = {"komoditas": label(item), "wilayah": D.nama_wilayah(prov, kab), "bulan": bulan_id(akhir), "harga": float(c.iloc[-1]),
             "mom": float(c.iloc[-1] / c.iloc[-2] - 1) * 100, "yoy": None if pd.isna(tahun_lalu) else float(c.iloc[-1] / tahun_lalu - 1) * 100,
             "inflasi": None, "status": None, "warna": None}
    if len(inf):
        nilai = float(inf.iloc[-1])
        status = NAMA_KELAS[int(status_inflasi(np.array([nilai]))[0])]
        hasil.update({"inflasi": nilai, "inflasi_teks": dec(nilai) + "%", "status": status, "warna": WARNA_STATUS[status], "inflasi_bulan": bulan_id(inf.index[-1], True)})
    hasil["harga_teks"] = rupiah(hasil["harga"])
    hasil["mom_teks"] = dec(hasil["mom"], 1, True) + "%"
    hasil["yoy_teks"] = None if hasil["yoy"] is None else dec(hasil["yoy"], 1, True) + "%"
    return hasil


def susun_candlestick(fw, item, tahun, judul):
    o, h, l, c = (fw.groupby("bulan")[f"{p}_{item}"].mean() for p in "ohlc")
    hasil = prediksi_harga(c, BULAN_PREDIKSI, JUMLAH_PRODUK_UJI)
    trace = [{"type": "candlestick", "x": c.index, "open": o.reindex(c.index), "high": h.reindex(c.index), "low": l.reindex(c.index), "close": c,
              "increasing": {"line": {"color": "#e8707a"}, "fillcolor": "#ffd0d0"}, "decreasing": {"line": {"color": "#5b9bd5"}, "fillcolor": "#cfe3f8"}, "name": "Harga bulanan"}]
    akhir = c.index[-1]
    akhir_tampil = hasil["prediksi"].index[-1] if hasil else akhir
    bentuk = []
    if hasil:
        x = [akhir] + list(hasil["prediksi"].index)
        awal = float(c.iloc[-1])
        trace.append({"type": "scatter", "x": x, "y": [awal] + list(hasil["atas"]), "mode": "lines", "line": {"width": 0}, "hoverinfo": "skip", "showlegend": False})
        trace.append({"type": "scatter", "x": x, "y": [awal] + list(hasil["bawah"]), "mode": "lines", "line": {"width": 0}, "fill": "tonexty",
                      "fillcolor": "rgba(43,127,94,0.16)", "name": "Rentang ketidakpastian", "hoverinfo": "skip"})
        trace.append({"type": "scatter", "x": x, "y": [awal] + list(hasil["prediksi"]), "mode": "lines+markers", "line": {"color": "#2b7f5e", "dash": "dash"},
                      "name": f"Prediksi ({hasil['model']})", "hovertemplate": "%{x|%b %Y}<br>Rp %{y:,.0f}<extra></extra>"})
        bentuk.append({"type": "line", "x0": tgl(akhir), "x1": tgl(akhir), "y0": 0, "y1": 1, "yref": "paper", "line": {"color": "#888888", "dash": "dot", "width": 1}})
    if tahun:
        bentuk.append({"type": "rect", "x0": f"{tahun}-01-01", "x1": f"{tahun}-12-31", "y0": 0, "y1": 1, "yref": "paper", "fillcolor": "rgba(43,127,94,0.07)",
                       "line": {"width": 0}, "layer": "below"})
    awal_tampil = tgl(akhir - pd.DateOffset(months=60))
    tata = {"height": 520, "xaxis": {"rangeslider": {"visible": False}, "range": [awal_tampil, tgl(akhir_tampil + pd.DateOffset(months=1))]},
            "yaxis": {"title": {"text": "Harga (IDR/kg)"}}, "margin": {"l": 70, "r": 10, "t": 50, "b": 30}, "separators": ",.",
            "legend": {"orientation": "h", "x": 0, "xanchor": "left", "y": 1.02, "yanchor": "bottom"}, "shapes": bentuk}
    return {"data": trace, "layout": tata}, hasil, c


@app.route("/api/kab")
def api_kab():
    prov = request.args.get("prov", SEMUA_PROV)
    d = D.df if prov == SEMUA_PROV else D.df[D.df[KOL_PROVINSI] == prov]
    return balas(sorted(d[KOL_KABUPATEN].dropna().unique().tolist()))


@app.route("/api/geo/<gid>")
def api_geo(gid):
    if gid == "provinsi":
        return balas(D.geo_prov)
    fitur = [f for f in D.geo_kab["features"] if f["properties"]["gid_1"] == gid]
    if not fitur:
        abort(404)
    return balas({"type": "FeatureCollection", "features": fitur})


@app.route("/api/prediksi")
def api_prediksi():
    prov, kab = baca_wilayah()
    item = request.args.get("item", "rice")
    if item not in D.ada_item:
        abort(400)
    tahun = int(request.args["tahun"]) if request.args.get("tahun") else None
    fw = D.saring(prov, kab)
    isi = {"komoditas": label(item), "wilayah": D.nama_wilayah(prov, kab), "ringkasan": ringkasan_harga(fw, item, prov, kab)}
    if {f"o_{item}", f"h_{item}", f"l_{item}", f"c_{item}"}.issubset(D.df.columns):
        fig, hasil, seri = susun_candlestick(fw, item, tahun, f"{label(item)} - {D.nama_wilayah(prov, kab)}")
        isi["candle"] = fig
        if hasil is None:
            isi["candle_info"] = "Data wilayah ini terlalu pendek untuk prediksi (minimal 42 bulan)."
        else:
            terakhir = float(seri.iloc[-1])
            tujuan = float(hasil["prediksi"].iloc[-1])
            isi["candle_ringkas"] = {"tujuan": rupiah(tujuan) + "/kg", "bulan": bulan_id(hasil["prediksi"].index[-1], True),
                                     "perubahan": dec((tujuan - terakhir) / terakhir * 100, 1, True) + "%", "bulan_awal": bulan_id(seri.index[-1], True),
                                     "model": hasil["model"], "mape": dec(hasil["mape"]) + "%"}
            isi["candle_catatan"] = (f"Setiap batang adalah satu bulan: hijau bila harga akhir lebih tinggi dari harga awal, merah bila lebih rendah. "
                                     f"Model dipilih otomatis lewat uji mundur {JUMLAH_PRODUK_UJI} bulan: {hasil['model']} "
                                     f"(rata-rata kesalahan {dec(hasil['mape'])}%). Pita oranye adalah rentang ketidakpastian dari 90% kesalahan uji mundur. "
                                     "Prediksi menunjukkan arah tren dan tidak menangkap lonjakan mendadak; lonjakan dipantau lewat grafik inflasi di halaman ini dan halaman Insight.")
    else:
        isi["candle_info"] = "Kolom open, high, low, dan close untuk komoditas ini tidak tersedia."
    return balas(isi)




SLUG = {k: label(k).lower().replace(" ", "-") for k in KOMODITAS}
KATEGORI = {"eggs": "Protein", "garlic": "Bumbu", "onions": "Bumbu", "meat_beef": "Daging", "meat_chicken": "Daging",
            "meat_chicken_broiler": "Daging", "oil": "Minyak", "rice": "Makanan pokok", "sugar": "Gula"}
BATAS_STABIL = 0.5
WARNA_ARAH = {"naik": "#d4553c", "turun": "#3f84c8", "stabil": "#70877c"}
app.jinja_env.globals.update(rupiah=rupiah, dec=dec, label=label, slug_dari=lambda k: SLUG.get(k, k), warna_status=WARNA_STATUS)
_cache = {}


def item_dari_slug(slug):
    for k, v in SLUG.items():
        if v == slug and k in D.ada_item:
            return k
    return None


def spark_svg(nilai, warna):
    v = [float(x) for x in nilai if not pd.isna(x)]
    if len(v) < 2:
        return ""
    lo, hi = min(v), max(v)
    rentang = (hi - lo) or 1
    lebar, tinggi = 100, 34
    titik = " ".join(f"{i * lebar / (len(v) - 1):.1f},{tinggi - 3 - (x - lo) / rentang * (tinggi - 6):.1f}" for i, x in enumerate(v))
    return (f'<svg viewBox="0 0 {lebar} {tinggi}" width="100%" height="34" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{titik}" fill="none" stroke="{warna}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>')


def ringkasan_komoditas():
    if "rk" in _cache:
        return _cache["rk"]
    hasil = []
    for k in D.ada_item:
        c = D.df.groupby("bulan")[f"c_{k}"].mean().dropna()
        if len(c) < 2:
            continue
        akhir = c.index[-1]
        mom = float(c.iloc[-1] / c.iloc[-2] - 1) * 100
        lalu = c.get(akhir - pd.DateOffset(years=1), np.nan)
        yoy = None if pd.isna(lalu) else float(c.iloc[-1] / lalu - 1) * 100
        arah = "naik" if mom > BATAS_STABIL else "turun" if mom < -BATAS_STABIL else "stabil"
        inf, status = None, None
        if f"inflation_{k}" in D.df.columns:
            s = D.df.groupby("bulan")[f"inflation_{k}"].mean().dropna()
            if len(s):
                inf = float(s.iloc[-1])
                status = NAMA_KELAS[int(status_inflasi(np.array([inf]))[0])]
        hasil.append({"kunci": k, "slug": SLUG[k], "nama": label(k), "kategori": KATEGORI.get(k, "Pangan"), "harga": float(c.iloc[-1]), "mom": mom, "yoy": yoy,
                      "arah": arah, "inflasi": inf, "status": status, "bulan": akhir, "spark": spark_svg(c.tail(12).values, WARNA_ARAH[arah])})
    _cache["rk"] = hasil
    return hasil


def opsi_form():
    provinsi = [{"nilai": p, "nama": D.nama_provinsi(p)} for p in sorted(D.df[KOL_PROVINSI].dropna().unique())]
    return {"provinsi": provinsi, "tahun": D.tahun, "hero": D.hero_sumber}


def halaman(nama, **konteks):
    if D.galat:
        return render_template("galat.html", galat=D.galat, aktif=nama)
    return render_template(nama + ".html", aktif=nama, **konteks)


def kabar_bulan(rk, hitung):
    atas = max(rk, key=lambda r: r["mom"])
    bawah = min(rk, key=lambda r: r["mom"])
    if atas["arah"] == "naik":
        judul = f"Harga {atas['nama']} naik paling tinggi bulan ini, {dec(atas['mom'])}%."
    elif bawah["arah"] == "turun":
        judul = f"Tidak ada komoditas yang naik berarti bulan ini. {bawah['nama']} turun paling banyak, {dec(abs(bawah['mom']))}%."
    else:
        judul = "Harga pangan relatif tenang bulan ini."
    rinci = f"{hitung['naik']} dari {len(rk)} komoditas naik dibanding bulan lalu."
    if bawah["arah"] == "turun" and atas["arah"] == "naik":
        rinci += f" {bawah['nama']} turun paling banyak, {dec(abs(bawah['mom']))}%."
    return {"judul": judul, "rinci": rinci}


@app.route("/")
def beranda():
    if D.galat:
        return halaman("beranda")
    rk = ringkasan_komoditas()
    hitung = {a: sum(1 for r in rk if r["arah"] == a) for a in ("naik", "turun", "stabil")}
    perhatian = sorted([r for r in rk if r["status"] in ("Lonjakan", "Waspada")], key=lambda r: -r["inflasi"])[:3]
    return halaman("beranda", rk=rk, hitung=hitung, kabar=kabar_bulan(rk, hitung), perhatian=perhatian, bulan=bulan_id(rk[0]["bulan"]) if rk else "-", n_pasar=D.df[KOL_PASAR].nunique(),
                   n_prov=D.df[KOL_PROVINSI].nunique(), komoditas=[{"nilai": r["kunci"], "nama": r["nama"]} for r in rk],
                   item_awal="rice" if "rice" in D.ada_item else D.ada_item[0], **opsi_form())


@app.route("/komoditas")
def daftar_komoditas():
    if D.galat:
        return halaman("komoditas")
    rk = sorted(ringkasan_komoditas(), key=lambda r: -(r["inflasi"] if r["inflasi"] is not None else -999))
    return halaman("komoditas", rk=rk, bulan=bulan_id(rk[0]["bulan"]) if rk else "-")


@app.route("/komoditas/<slug>")
def detail_komoditas(slug):
    if D.galat:
        return halaman("komoditas")
    item = item_dari_slug(slug)
    if item is None:
        abort(404)
    r = next(x for x in ringkasan_komoditas() if x["kunci"] == item)
    kol = f"c_{item}"
    akhir = r["bulan"]
    sekarang = D.df[D.df["bulan"] == akhir]
    pasar = sekarang.groupby(KOL_PASAR)[kol].mean().dropna().sort_values()
    stat = None
    if len(pasar) >= 2:
        murah, mahal = pasar.index[0], pasar.index[-1]
        stat = {"murah": murah, "harga_murah": float(pasar.iloc[0]), "prov_murah": D.nama_provinsi(D.info_pasar.loc[murah, KOL_PROVINSI]),
                "mahal": mahal, "harga_mahal": float(pasar.iloc[-1]), "prov_mahal": D.nama_provinsi(D.info_pasar.loc[mahal, KOL_PROVINSI]),
                "selisih": float(pasar.iloc[-1] - pasar.iloc[0]), "selisih_pct": float(pasar.iloc[-1] / pasar.iloc[0] - 1) * 100, "n": len(pasar)}
    nasional = float(pasar.mean()) if len(pasar) else None
    tabel_prov = []
    if nasional:
        pp = sekarang.groupby(KOL_PROVINSI)[kol].agg(["mean", "count"]).dropna().sort_values("mean")
        tabel_prov = [{"nama": D.nama_provinsi(p), "harga": float(v["mean"]), "vs": (float(v["mean"]) / nasional - 1) * 100} for p, v in pp.iterrows()]
    return halaman("komoditas_detail", r=r, stat=stat, tabel_prov=tabel_prov, nasional=nasional, bulan=bulan_id(akhir), **opsi_form())


@app.route("/insight")
def insight():
    if D.galat:
        return halaman("insight")
    return halaman("insight", ada_faktor=faktor_tersedia(), item_inflasi=[{"nilai": k, "nama": label(k)} for k in D.item_inflasi], **opsi_form())


@app.route("/peringatan-dini")
def peringatan_lama():
    return redirect("/insight", code=301)


NAMA_FAKTOR = {"hujan": "Anomali curah hujan", "suhu": "Anomali suhu", "oni": "Indeks ENSO (ONI)"}
MAKS_JEDA = 6


def faktor_tersedia():
    ada = []
    if D.cuaca is not None:
        ada += ["hujan", "suhu"]
    if D.oni is not None:
        ada.append("oni")
    return ada


def seri_faktor(faktor, pasar=None):
    if faktor in ("hujan", "suhu"):
        if D.cuaca is None:
            return None
        c = D.cuaca if pasar is None else D.cuaca[D.cuaca[KOL_PASAR].isin(pasar)]
        m = c.groupby("bulan")[faktor].mean().dropna()
        if m.empty:
            return None
        normal = m[m.index.year <= inti.TAHUN_ACUAN_AKHIR].groupby(m[m.index.year <= inti.TAHUN_ACUAN_AKHIR].index.month).mean()
        return m - pd.Series(m.index.month, index=m.index).map(normal)
    if faktor == "oni" and D.oni is not None:
        return D.oni.assign(bulan=pd.to_datetime(D.oni["bulan"])).set_index("bulan")["oni"].dropna()
    return None


def geser(seri, jeda):
    out = seri.copy()
    out.index = out.index + pd.DateOffset(months=jeda)
    return out


def korelasi(inflasi, faktor, jeda):
    gabung = pd.concat([inflasi.rename("i"), geser(faktor, jeda).rename("f")], axis=1).dropna()
    if len(gabung) < 24:
        return None, len(gabung)
    return float(gabung["i"].corr(gabung["f"])), len(gabung)


@app.route("/api/hubungan")
def api_hubungan():
    prov, kab = baca_wilayah()
    item = request.args.get("item", "rice")
    faktor = request.args.get("faktor", "hujan")
    jeda = max(0, min(MAKS_JEDA, int(request.args.get("jeda", 0))))
    kol = f"inflation_{item}"
    if kol not in D.df.columns:
        abort(400)
    if faktor not in faktor_tersedia():
        return balas({"kosong": "Data faktor ini belum diambil. Jalankan notebooks/8_data_tambahan.ipynb lalu restart server."})
    fw = D.saring(prov, kab)
    pasar = None if (prov == SEMUA_PROV and kab == SEMUA_KAB) else fw[KOL_PASAR].unique()
    f = seri_faktor(faktor, pasar)
    s = fw.groupby("bulan")[kol].mean().dropna()
    if f is None or s.empty:
        return balas({"kosong": "Data wilayah ini belum cukup."})
    fg = geser(f, jeda)
    r, n = korelasi(s, f, jeda)
    satuan = {"hujan": "mm/hari", "suhu": "C", "oni": ""}[faktor]
    data = [{"type": "scatter", "x": s.index, "y": s.values, "mode": "lines", "name": f"Inflasi {label(item)} (y/y, %)", "line": {"color": "#2b7f5e", "width": 2.5},
             "hovertemplate": "%{x|%b %Y}: %{y:.1f}%<extra></extra>"},
            {"type": "scatter", "x": fg.index, "y": fg.values, "mode": "lines", "yaxis": "y2", "line": {"color": "#5b9bd5", "width": 2},
             "name": NAMA_FAKTOR[faktor] + (f", digeser {jeda} bulan" if jeda else ""), "hovertemplate": "%{x|%b %Y}: %{y:.2f} " + satuan + "<extra></extra>"}]
    tata = {"height": 380, "separators": ",.", "margin": {"l": 55, "r": 55, "t": 10, "b": 30}, "legend": {"orientation": "h", "x": 0, "y": 1.12},
            "yaxis": {"title": {"text": "Inflasi (%)"}}, "yaxis2": {"title": {"text": NAMA_FAKTOR[faktor]}, "overlaying": "y", "side": "right", "showgrid": False},
            "xaxis": {"range": [tgl(max(s.index.min(), fg.index.min())), tgl(s.index.max())]}}
    kekuatan = None
    if r is not None:
        a = abs(r)
        kekuatan = "sangat lemah" if a < 0.2 else "lemah" if a < 0.4 else "sedang" if a < 0.6 else "kuat"
    return balas({"grafik": {"data": data, "layout": tata}, "r": r, "r_teks": None if r is None else dec(r, 2, True), "n": n, "kekuatan": kekuatan,
                  "wilayah": D.nama_wilayah(prov, kab)})


@app.route("/api/korelasi")
def api_korelasi():
    prov, kab = baca_wilayah()
    ada = faktor_tersedia()
    if not ada:
        return balas({"kosong": "Data cuaca dan ENSO belum diambil. Jalankan notebooks/8_data_tambahan.ipynb lalu restart server."})
    fw = D.saring(prov, kab)
    pasar = None if (prov == SEMUA_PROV and kab == SEMUA_KAB) else fw[KOL_PASAR].unique()
    seri = {f: seri_faktor(f, pasar) for f in ada}
    baris = []
    for k in D.item_inflasi:
        s = fw.groupby("bulan")[f"inflation_{k}"].mean().dropna()
        sel = {}
        for f, fs in seri.items():
            if fs is None:
                continue
            terbaik = None
            for j in range(MAKS_JEDA + 1):
                r, n = korelasi(s, fs, j)
                if r is not None and (terbaik is None or abs(r) > abs(terbaik["r"])):
                    terbaik = {"r": r, "jeda": j, "n": n, "teks": dec(r, 2, True)}
            sel[f] = terbaik
        baris.append({"nama": label(k), "slug": SLUG.get(k, k), "sel": sel})
    return balas({"faktor": [{"kunci": f, "nama": NAMA_FAKTOR[f]} for f in ada], "baris": baris, "wilayah": D.nama_wilayah(prov, kab)})


@app.route("/api/peta")
def api_peta():
    prov, kab = baca_wilayah()
    item = request.args.get("item", "rice")
    if item not in D.ada_item:
        abort(400)
    tahun = int(request.args.get("tahun", D.tahun[0]))
    lapisan = request.args.get("lapisan", "Tingkat harga")
    fw = D.saring(prov, kab)
    if fw[fw[KOL_TANGGAL].dt.year == tahun].empty:
        return balas({"kosong": "Tidak ada data untuk filter yang dipilih."})
    if f"h_{item}" not in D.df.columns and lapisan == "Volatilitas":
        return balas({"kosong": "Kolom high dan low untuk komoditas ini tidak tersedia."})
    isi = {"peta": susun_peta(item, tahun, lapisan, prov, kab), "komoditas": label(item), "wilayah": D.nama_wilayah(prov, kab)}
    return balas(isi)


@app.route("/api/inflasi")
def api_inflasi():
    prov, kab = baca_wilayah()
    item = request.args.get("item", "rice")
    kolom_i = f"inflation_{item}"
    if kolom_i not in D.df.columns:
        return balas({"kosong": "Data inflasi komoditas ini tidak tersedia."})
    fw = D.saring(prov, kab)
    s = fw.groupby("bulan")[kolom_i].mean().dropna()
    if s.empty:
        return balas({"kosong": "Tidak ada data inflasi untuk wilayah ini."})
    garis = lambda y, w: {"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": y, "y1": y, "line": {"color": WARNA_STATUS[w], "dash": "dash", "width": 1.5}}
    grafik = {"data": [{"type": "scatter", "x": s.index, "y": s.values, "mode": "lines", "line": {"color": "#2b7f5e", "width": 2.5}, "name": "Inflasi y/y",
                        "hovertemplate": "%{x|%b %Y}: %{y:.1f}%<extra></extra>"}],
              "layout": {"height": 340, "separators": ",.", "yaxis": {"title": {"text": "Inflasi (%)"}}, "margin": {"l": 55, "r": 10, "t": 10, "b": 30},
                         "shapes": [garis(BATAS_WASPADA, "Waspada"), garis(BATAS_LONJAKAN, "Lonjakan")]}}
    bulan_pr = D.df.dropna(subset=[kolom_i])["bulan"].max()
    pr = (D.df[D.df["bulan"] == bulan_pr].groupby(KOL_PROVINSI).agg(inflasi=(kolom_i, "mean"), pasar=(KOL_PASAR, "nunique"))
          .sort_values("inflasi", ascending=False).head(10))
    warna_bar = [WARNA_STATUS[NAMA_KELAS[int(status_inflasi(np.array([v]))[0])]] for v in pr["inflasi"]]
    ranking = {"data": [{"type": "bar", "orientation": "h", "x": pr["inflasi"], "y": [D.nama_provinsi(p) for p in pr.index], "marker": {"color": warna_bar},
                         "text": [f"{dec(v)}%" for v in pr["inflasi"]], "textposition": "outside", "cliponaxis": False, "customdata": pr["pasar"],
                         "hovertemplate": "%{y}: %{x:.1f}% (%{customdata} pasar)<extra></extra>"}],
               "layout": {"height": 340, "separators": ",.", "margin": {"l": 150, "r": 50, "t": 10, "b": 40}, "xaxis": {"title": {"text": "Inflasi (%)"}},
                          "yaxis": {"autorange": "reversed"}}}
    return balas({"grafik": grafik, "ranking": ranking, "bulan_ranking": bulan_id(bulan_pr), "wilayah": D.nama_wilayah(prov, kab)})


@app.errorhandler(404)
def tidak_ada(e):
    return render_template("galat.html", galat="Halaman tidak ditemukan.", aktif=""), 404



@app.route("/api/eksternal")
def api_eksternal():
    prov, kab = baca_wilayah()
    fw = D.saring(prov, kab)
    kol_inf = f"inflation_{inti.KOL_INDEKS}"
    kal = inti.kalender_ramadan(2006, 2028)
    akhir = D.df["bulan"].max()
    awal = akhir - pd.DateOffset(years=8)
    kal_tampil = kal[(kal["bulan"] >= awal) & (kal["bulan"] <= akhir + pd.DateOffset(months=1))]
    bentuk_ramadan = [{"type": "rect", "x0": tgl(b), "x1": tgl(b + pd.DateOffset(months=1)), "y0": 0, "y1": 1, "yref": "paper", "fillcolor": "rgba(43,127,94,0.14)",
                       "line": {"width": 0}, "layer": "below"} for b in kal_tampil.loc[kal_tampil["ramadan_ada"] == 1, "bulan"]]
    bentuk_ied = [{"type": "line", "x0": tgl(b), "x1": tgl(b), "y0": 0, "y1": 1, "yref": "paper", "line": {"color": "#2b7f5e", "width": 1, "dash": "dot"}}
                  for b in kal_tampil.loc[kal_tampil["idulfitri_ada"] == 1, "bulan"]]
    depan = kal[(kal["bulan"] > akhir) & (kal["ramadan_ada"] == 1)]
    isi = {"wilayah": D.nama_wilayah(prov, kab), "sumber": {"cuaca": D.cuaca is not None, "oni": D.oni is not None}}
    isi["ramadan_berikut"] = bulan_id(depan["bulan"].iloc[0]) if len(depan) else None
    if kol_inf in fw.columns:
        s = fw.groupby("bulan")[kol_inf].mean().dropna()
        s = s[s.index >= awal]
        kal_i = kal.set_index("bulan")["ramadan_ada"].reindex(s.index)
        saat, lain = s[kal_i == 1], s[kal_i == 0]
        isi["ramadan_stat"] = {"saat": float(saat.mean()) if len(saat) else None, "lain": float(lain.mean()) if len(lain) else None}
        isi["grafik_ramadan"] = {"data": [{"type": "scatter", "x": s.index, "y": s.values, "mode": "lines", "line": {"color": "#243a32", "width": 2},
                                           "name": "Inflasi indeks pangan (y/y)", "hovertemplate": "%{x|%b %Y}: %{y:.1f}%<extra></extra>"}],
                                 "layout": {"height": 340, "separators": ",.", "margin": {"l": 55, "r": 10, "t": 10, "b": 30}, "yaxis": {"title": {"text": "Inflasi (%)"}},
                                            "shapes": bentuk_ramadan + bentuk_ied}}
    if D.cuaca is not None:
        c = D.cuaca
        if prov != SEMUA_PROV or kab != SEMUA_KAB:
            c = c[c[KOL_PASAR].isin(fw[KOL_PASAR].unique())]
        m = c.groupby("bulan")[["hujan", "suhu"]].mean().dropna(how="all")
        m = m[m.index >= awal]
        if len(m):
            normal = D.cuaca[D.cuaca["bulan"].dt.year <= inti.TAHUN_ACUAN_AKHIR]
            if len(c):
                normal = normal[normal[KOL_PASAR].isin(c[KOL_PASAR].unique())]
            nb = normal.groupby(normal["bulan"].dt.month)["hujan"].mean()
            terakhir = m.index[-1]
            isi["cuaca_kartu"] = {"bulan": bulan_id(terakhir), "hujan": float(m["hujan"].iloc[-1]), "suhu": float(m["suhu"].iloc[-1]),
                                  "hujan_normal": float(nb.get(terakhir.month, np.nan))}
            isi["grafik_cuaca"] = {"data": [{"type": "bar", "x": m.index, "y": m["hujan"], "name": "Curah hujan (mm/hari)", "marker": {"color": "#a9cdf2"},
                                             "hovertemplate": "%{x|%b %Y}: %{y:.1f} mm/hari<extra></extra>"},
                                            {"type": "scatter", "x": m.index, "y": m["suhu"], "mode": "lines", "name": "Suhu (C)", "yaxis": "y2",
                                             "line": {"color": "#ee7f6b", "width": 2}, "hovertemplate": "%{x|%b %Y}: %{y:.1f} C<extra></extra>"}],
                                   "layout": {"height": 340, "separators": ",.", "margin": {"l": 55, "r": 55, "t": 10, "b": 30}, "legend": {"orientation": "h", "y": 1.12},
                                              "yaxis": {"title": {"text": "Hujan (mm/hari)"}}, "yaxis2": {"title": {"text": "Suhu (C)"}, "overlaying": "y", "side": "right",
                                                                                                          "showgrid": False}}}
    if D.oni is not None:
        o = D.oni.sort_values("bulan")
        o = o[o["bulan"] >= awal]
        if len(o):
            nilai = float(o["oni"].iloc[-1])
            fase = "El Nino" if nilai >= 0.5 else "La Nina" if nilai <= -0.5 else "Netral"
            isi["oni_kartu"] = {"bulan": bulan_id(o["bulan"].iloc[-1]), "nilai": nilai, "teks": dec(nilai, 1, True), "fase": fase}
            isi["grafik_oni"] = {"data": [{"type": "bar", "x": o["bulan"], "y": o["oni"], "marker": {"color": ["#ee8a78" if v >= 0.5 else "#8fc4ee" if v <= -0.5 else "#9aa5b1" for v in o["oni"]]},
                                           "name": "ONI", "hovertemplate": "%{x|%b %Y}: %{y:.1f}<extra></extra>"}],
                                 "layout": {"height": 300, "separators": ",.", "margin": {"l": 55, "r": 10, "t": 10, "b": 30}, "yaxis": {"title": {"text": "ONI"}},
                                            "shapes": [{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 0.5, "y1": 0.5, "line": {"color": "#ee8a78", "dash": "dash", "width": 1}},
                                                       {"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": -0.5, "y1": -0.5, "line": {"color": "#8fc4ee", "dash": "dash", "width": 1}}]}}
    return balas(isi)


def rekomendasi_wilayah(prov):
    a = D.analisis()
    if a is None:
        return None, None
    rek = a["rek"]
    if prov != SEMUA_PROV:
        rek = rek[rek[KOL_PROVINSI] == prov]
    return a, rek


@app.route("/api/keputusan")
def api_keputusan():
    prov, _ = baca_wilayah()
    a, rek = rekomendasi_wilayah(prov)
    if a is None:
        return balas({"kosong": "Data inflasi belum cukup untuk menyusun rekomendasi."})
    hitung = rek["tingkat"].value_counts()
    top = rek.head(10).copy()
    baris = []
    tipe = top["label_klaster"].str.replace(r"^Klaster \d+: ", "", regex=True).str.capitalize()
    for i, (_, r) in enumerate(top.iterrows()):
        baris.append({"pasar": r[KOL_PASAR], "provinsi": D.nama_provinsi(r[KOL_PROVINSI]), "tipe": tipe.iloc[i], "prediksi": r["status_prediksi_bulan_depan"],
                      "skor": float(r["skor_prioritas"]), "tingkat": r["tingkat"], "alasan": r["alasan"]})
    metrik = a["hasil"]["metrik"]
    terbaik = a["hasil"]["terbaik"]
    f1_model, f1_dasar = metrik.loc[terbaik, "F1 (macro)"], metrik.loc["Tebakan sederhana", "F1 (macro)"]
    pr = a["peringkat"]
    banding = "lebih baik dari" if f1_model > f1_dasar else "belum mengungguli"
    catatan = (f"Model: {terbaik}, dilatih sampai {bulan_id(a['tgl_potong'] - pd.DateOffset(months=1), True)} dan diuji sesudahnya. Akurasi kelasnya {banding} tebakan sederhana "
               f"\"status bulan depan sama dengan bulan ini\" (F1 {dec(f1_model, 2)} dibanding {dec(f1_dasar, 2)}). Sebagai pemeringkat risiko, "
               f"{pr['persen']:.0%} pasar teratas menangkap {pr['tertangkap']:.0%} lonjakan aktual di data uji (lonjakan hanya {dec(pr['dasar'] * 100)}% dari seluruh data uji). "
               f"Skor = {dec(BOBOT_RISIKO)} x risiko + {dec(BOBOT_MOMENTUM)} x momentum inflasi + {dec(BOBOT_VOLATILITAS)} x volatilitas tipe pasar; bobot ditetapkan kelompok. "
               f"Prioritas tinggi bila skor di atas {BATAS_PRIORITAS}, pantau ketat bila di atas {BATAS_PANTAU}.")
    sumber = ["World Bank Real-Time Food Prices (RTFP): harga, inflasi, dan skor kepercayaan 9 komoditas di 222 pasar", "GADM 4.1: batas provinsi dan kab/kota untuk peta"]
    ada_eks = D.cuaca is not None or D.oni is not None
    if D.cuaca is not None:
        sumber.append("NASA POWER: curah hujan dan suhu bulanan di koordinat tiap pasar")
    if D.oni is not None:
        sumber.append("NOAA CPC: indeks ENSO (ONI)")
    if ada_eks:
        sumber.append("Kalender Ramadan dan Idulfitri dari kalender Hijriah tabular")
    tabel_metrik = [{"model": str(m), "akurasi": float(r["Akurasi"]), "f1": float(r["F1 (macro)"])} for m, r in metrik.iterrows()]
    return balas({"judul": f"Pasar dengan risiko lonjakan tertinggi pada bulan setelah {bulan_id(a['bulan_akhir'])}",
                  "ringkas": f"Dari {len(rek)} pasar: {int(hitung.get('Prioritas tinggi', 0))} prioritas tinggi, {int(hitung.get('Pantau ketat', 0))} pantau ketat, "
                             f"{int(hitung.get('Aman', 0))} aman. Berikut 10 pasar dengan skor risiko tertinggi.",
                  "jumlah": {"tinggi": int(hitung.get("Prioritas tinggi", 0)), "pantau": int(hitung.get("Pantau ketat", 0)), "aman": int(hitung.get("Aman", 0)), "total": len(rek)},
                  "terbaik": str(terbaik), "tabel": baris, "catatan": catatan, "sumber": sumber, "metrik": tabel_metrik,
                  "info_eksternal": None if ada_eks else "Data tambahan (cuaca, ENSO, Ramadan) belum diambil. Jalankan notebooks/8_data_tambahan.ipynb lalu muat ulang dashboard.",
                  "catatan_metrik": "Klasifikasi ini adalah supervised learning: label berasal dari status inflasi aktual bulan depan. "
                                    "Dua baseline dipakai sebagai pembanding: tebakan sederhana dan selalu menebak Normal."})


@app.route("/unduh/rekomendasi.csv")
def unduh_rekomendasi():
    prov, _ = baca_wilayah()
    a, rek = rekomendasi_wilayah(prov)
    if a is None:
        abort(404)
    kolom = [KOL_PASAR, KOL_PROVINSI, "skor_prioritas", "tingkat", "status_prediksi_bulan_depan", "label_klaster", "alasan", "rekomendasi"]
    isi = rek[kolom].to_csv(index=False)
    return Response(isi, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=rekomendasi_keputusan.csv"})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)