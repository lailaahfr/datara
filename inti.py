import re

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import accuracy_score, f1_score, silhouette_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.tree import DecisionTreeClassifier


KOL_PASAR = 'mkt_name'
KOL_TANGGAL = 'date'
KOL_INDEKS = 'food_price_index'
KOMODITAS = ['eggs', 'garlic', 'meat_beef', 'meat_chicken', 'meat_chicken_broiler', 'oil', 'onions', 'rice', 'sugar']

BATAS_WASPADA = 5
BATAS_LONJAKAN = 10
NAMA_KELAS = ['Normal', 'Waspada', 'Lonjakan']
FITUR_DASAR = ['inflasi_ini', 'inflasi_lalu', 'bulan']
PERSEN_TEST = 0.2
TAHUN_ACUAN_AKHIR = 2019

BOBOT_RISIKO = 0.6
BOBOT_MOMENTUM = 0.2
BOBOT_VOLATILITAS = 0.2
BATAS_PRIORITAS = 50
BATAS_PANTAU = 25
BATAS_HARGA_PERSEN = 5

NAMA_KOMODITAS = {
    'eggs': 'Telur', 'garlic': 'Bawang Putih', 'meat_beef': 'Daging Sapi', 'meat_chicken': 'Daging Ayam',
    'meat_chicken_broiler': 'Daging Ayam Broiler', 'oil': 'Minyak Goreng', 'onions': 'Bawang Merah',
    'rice': 'Beras', 'sugar': 'Gula', 'food_price_index': 'Indeks Pangan',
}
MUSIM_ONI = ['DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ', 'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ']


def status_inflasi(inflasi):
    return np.select([inflasi < BATAS_WASPADA, inflasi < BATAS_LONJAKAN], [0, 1], default=2)


def tambah_rentang(d):
    h, l, c = f'h_{KOL_INDEKS}', f'l_{KOL_INDEKS}', f'c_{KOL_INDEKS}'
    if {h, l, c}.issubset(d.columns):
        return (d[h] - d[l]) / d[c] * 100
    return pd.Series(np.nan, index=d.index)


def siapkan_fitur(df):
    kol_inf = f'inflation_{KOL_INDEKS}'
    d = df.sort_values([KOL_PASAR, KOL_TANGGAL]).reset_index(drop=True)
    g = d.groupby(KOL_PASAR)
    out = pd.DataFrame({KOL_PASAR: d[KOL_PASAR], KOL_TANGGAL: d[KOL_TANGGAL]})
    out['inflasi_ini'] = d[kol_inf]
    out['inflasi_lalu'] = g[kol_inf].shift(1)
    out['inflasi_depan'] = g[kol_inf].shift(-1)
    out['bulan'] = d[KOL_TANGGAL].dt.month
    for k in KOMODITAS:
        if f'inflation_{k}' in d.columns:
            out[f'inf_{k}'] = d[f'inflation_{k}']
    if f'trust_{KOL_INDEKS}' in d.columns:
        out['trust_indeks'] = d[f'trust_{KOL_INDEKS}']
    for k in KOMODITAS:
        if f'trust_{k}' in d.columns:
            out[f'trust_{k}'] = d[f'trust_{k}']
    rentang = tambah_rentang(d)
    if rentang.notna().any():
        out['rentang_harga'] = rentang
    if 'spatially_interpolated' in d.columns:
        out['interpolasi'] = pd.to_numeric(d['spatially_interpolated'], errors='coerce')
    mentah = [k for k in KOMODITAS if k in d.columns]
    if mentah:
        ada_survei = (d[mentah].notna().sum(axis=1) > 0).astype(float)
        out['obs_12b'] = ada_survei.groupby(d[KOL_PASAR]).transform(lambda x: x.rolling(12, min_periods=1).sum())
    periode = d[KOL_TANGGAL].dt.to_period('M')
    out['lalu_ok'] = g[KOL_TANGGAL].shift(1).dt.to_period('M') == periode - 1
    out['depan_ok'] = g[KOL_TANGGAL].shift(-1).dt.to_period('M') == periode + 1
    return out


def daftar_fitur_kaya(out):
    tambahan = [c for c in out.columns if c.startswith(('inf_', 'trust_')) or c in ('rentang_harga', 'interpolasi')]
    return FITUR_DASAR + tambahan


def siapkan_data_model(out):
    dm = out[out['lalu_ok'] & out['depan_ok']].dropna(subset=['inflasi_ini', 'inflasi_lalu', 'inflasi_depan']).copy()
    dm['kelas_depan'] = status_inflasi(dm['inflasi_depan'].values)
    return dm


def pisah_waktu(dm, persen_test=PERSEN_TEST):
    bulan_unik = np.sort(dm[KOL_TANGGAL].unique())
    tgl_potong = pd.Timestamp(bulan_unik[int(len(bulan_unik) * (1 - persen_test))])
    return dm[KOL_TANGGAL] < tgl_potong, tgl_potong


def buat_model(jenis):
    if jenis == 'tree':
        est = DecisionTreeClassifier(max_depth=4, class_weight='balanced', random_state=42)
    else:
        est = RandomForestClassifier(n_estimators=150, max_depth=8, min_samples_leaf=20,
                                     class_weight='balanced_subsample', n_jobs=-1, random_state=42)
    return make_pipeline(SimpleImputer(strategy='median'), est)


def bandingkan_model(dm, is_train, fitur_kaya, fitur_eksternal=None):
    y_train, y_test = dm.loc[is_train, 'kelas_depan'], dm.loc[~is_train, 'kelas_depan']
    skenario = {
        'Decision Tree (3 fitur)': ('tree', FITUR_DASAR),
        'Decision Tree (diperkaya)': ('tree', fitur_kaya),
        'Random Forest (diperkaya)': ('forest', fitur_kaya),
    }
    if fitur_eksternal:
        skenario['Random Forest + data eksternal'] = ('forest', fitur_kaya + fitur_eksternal)
    model, pred, baris = {}, {}, []
    for nama, (jenis, fitur) in skenario.items():
        model[nama] = buat_model(jenis).fit(dm.loc[is_train, fitur], y_train)
        pred[nama] = model[nama].predict(dm.loc[~is_train, fitur])
        baris.append((nama, accuracy_score(y_test, pred[nama]), f1_score(y_test, pred[nama], average='macro', zero_division=0)))
    pred_base = status_inflasi(dm.loc[~is_train, 'inflasi_ini'].values)
    baris.append(('Tebakan sederhana', accuracy_score(y_test, pred_base), f1_score(y_test, pred_base, average='macro', zero_division=0)))
    pred_normal = np.zeros(len(y_test), dtype=int)
    baris.append(('Selalu tebak Normal', accuracy_score(y_test, pred_normal), f1_score(y_test, pred_normal, average='macro', zero_division=0)))
    metrik = pd.DataFrame(baris, columns=['Model', 'Akurasi', 'F1 (macro)']).set_index('Model')
    terbaik = metrik.drop(index=['Tebakan sederhana', 'Selalu tebak Normal'])['F1 (macro)'].idxmax()
    return {'model': model, 'pred': pred, 'metrik': metrik, 'terbaik': terbaik, 'skenario': skenario, 'y_test': y_test}


def prediksi_terbaru(out, dm, hasil, fitur_kaya):
    jenis, fitur = hasil['skenario'][hasil['terbaik']]
    final = buat_model(jenis).fit(dm[fitur], dm['kelas_depan'])
    terbaru = out[(out[KOL_TANGGAL] == out[KOL_TANGGAL].max()) & out['lalu_ok']].dropna(subset=['inflasi_ini', 'inflasi_lalu']).copy()
    proba = pd.DataFrame(final.predict_proba(terbaru[fitur]), index=terbaru.index, columns=final.classes_)
    for k in range(3):
        terbaru[f'p_{NAMA_KELAS[k].lower()}'] = proba[k] if k in proba.columns else 0.0
    terbaru['status_bulan_ini'] = [NAMA_KELAS[i] for i in status_inflasi(terbaru['inflasi_ini'].values)]
    terbaru['status_prediksi_bulan_depan'] = [NAMA_KELAS[i] for i in final.predict(terbaru[fitur])]
    return terbaru, final, fitur


def klaster_pasar(df, bulan_terakhir=12, k_min=3, k_max=6):
    harga = [f'c_{k}' for k in KOMODITAS if f'c_{k}' in df.columns]
    kol_inf = f'inflation_{KOL_INDEKS}'
    akhir = df[KOL_TANGGAL].max()
    r = df[df[KOL_TANGGAL] > akhir - pd.DateOffset(months=bulan_terakhir)].copy()
    median_bulan = r.groupby(KOL_TANGGAL)[harga].transform('median')
    prof = (r[harga] / median_bulan).groupby(r[KOL_PASAR]).mean()
    prof.columns = [f'rasio_{c[2:]}' for c in prof.columns]
    prof['inflasi_rata'] = r.groupby(KOL_PASAR)[kol_inf].mean()
    prof['volatilitas_inflasi'] = r.groupby(KOL_PASAR)[kol_inf].std()
    r['rentang_harga'] = tambah_rentang(r)
    if r['rentang_harga'].notna().any():
        prof['rentang_harga'] = r.groupby(KOL_PASAR)['rentang_harga'].mean()
    prof = prof.fillna(prof.median())
    X = StandardScaler().fit_transform(prof)
    skor = {}
    for k in range(k_min, min(k_max, len(prof) - 1) + 1):
        skor[k] = silhouette_score(X, KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X))
    k_terbaik = max(skor, key=skor.get)
    prof['klaster'] = KMeans(n_clusters=k_terbaik, n_init=10, random_state=42).fit_predict(X) + 1
    rasio_cols = [c for c in prof.columns if c.startswith('rasio_')]
    prof['komposit_harga'] = prof[rasio_cols].mean(axis=1)
    ringkas = prof.groupby('klaster').agg(jumlah_pasar=('klaster', 'size'), komposit_harga=('komposit_harga', 'mean'),
                                          inflasi_rata=('inflasi_rata', 'mean'), volatilitas_inflasi=('volatilitas_inflasi', 'mean'))
    vol_tengah = prof['volatilitas_inflasi'].median()
    nama = {}
    for i, baris in ringkas.iterrows():
        harga_txt = ('harga jauh di atas median' if baris['komposit_harga'] > 1.10 else 'harga sedikit di atas median' if baris['komposit_harga'] > 1.03
                     else 'harga di bawah median' if baris['komposit_harga'] < 0.97 else 'harga sekitar median')
        vol_txt = 'volatil' if baris['volatilitas_inflasi'] >= vol_tengah else 'stabil'
        nama[i] = f'Klaster {i}: {harga_txt}, {vol_txt}'
    prof['label_klaster'] = prof['klaster'].map(nama)
    ringkas['label_klaster'] = ringkas.index.map(nama)
    return prof, ringkas, pd.Series(skor, name='silhouette')


def alasan_pasar(r):
    bagian = []
    peluang = r['p_waspada'] + r['p_lonjakan']
    if r['p_lonjakan'] >= 0.5:
        bagian.append(f"peluang lonjakan {r['p_lonjakan']:.0%}")
    elif peluang >= 0.5:
        bagian.append(f"peluang naik ke Waspada atau lebih {peluang:.0%}")
    if r['inflasi_ini'] - r['inflasi_lalu'] >= 1:
        bagian.append(f"inflasi naik dari {r['inflasi_lalu']:.1f}% ke {r['inflasi_ini']:.1f}%".replace('.', ','))
    if pd.notna(r['nilai_pemicu']) and r['nilai_pemicu'] >= BATAS_LONJAKAN:
        bagian.append(f"inflasi {r['komoditas_pemicu'].lower()} {r['nilai_pemicu']:.0f}%")
    if r['volatilitas_pct'] >= 67:
        bagian.append('harga sering bergejolak')
    teks = '; '.join(bagian[:3]) if bagian else 'kondisi stabil'
    if r['perlu_verifikasi']:
        teks += ' (perlu verifikasi data)'
    return teks[0].upper() + teks[1:]


def skor_rekomendasi(terbaru, prof):
    t = terbaru.copy()
    risiko = (t['p_waspada'] * 0.5 + t['p_lonjakan'] * 1.0) * 100
    momentum = ((t['inflasi_ini'] - t['inflasi_lalu']) / 10).clip(0, 1) * 100
    vol_pct = prof['volatilitas_inflasi'].rank(pct=True) * 100
    t['label_klaster'] = t[KOL_PASAR].map(prof['label_klaster'])
    t['volatilitas_pct'] = t[KOL_PASAR].map(vol_pct).fillna(vol_pct.median())
    t['skor_prioritas'] = (BOBOT_RISIKO * risiko + BOBOT_MOMENTUM * momentum + BOBOT_VOLATILITAS * t['volatilitas_pct']).round(1)
    t['tingkat'] = np.select([t['skor_prioritas'] >= BATAS_PRIORITAS, t['skor_prioritas'] >= BATAS_PANTAU],
                             ['Prioritas tinggi', 'Pantau ketat'], default='Aman')
    kol_inf = [c for c in t.columns if c.startswith('inf_')]
    if kol_inf:
        t['komoditas_pemicu'] = t[kol_inf].idxmax(axis=1).str.replace('inf_', '', regex=False).map(NAMA_KOMODITAS)
        t['nilai_pemicu'] = t[kol_inf].max(axis=1)
    else:
        t['komoditas_pemicu'] = 'Indeks Pangan'
        t['nilai_pemicu'] = t['inflasi_ini']
    aksi = {'Prioritas tinggi': 'Siapkan operasi pasar dan cek pasokan', 'Pantau ketat': 'Pantau harga mingguan', 'Aman': 'Pemantauan rutin bulanan'}
    t['rekomendasi'] = t['tingkat'].map(aksi)
    t.loc[t['tingkat'] != 'Aman', 'rekomendasi'] += ' (pemicu: ' + t.loc[t['tingkat'] != 'Aman', 'komoditas_pemicu'] + ')'
    tanpa_survei = t['obs_12b'] == 0 if 'obs_12b' in t.columns else pd.Series(False, index=t.index)
    rentang_lebar = t['rentang_harga'] >= t['rentang_harga'].quantile(0.9) if 'rentang_harga' in t.columns else pd.Series(False, index=t.index)
    t['perlu_verifikasi'] = tanpa_survei | rentang_lebar
    t['alasan'] = t.apply(alasan_pasar, axis=1)
    return t.sort_values('skor_prioritas', ascending=False)



def model_datar(y, h):
    return np.repeat(y[-1], h)


def model_teredam(y, h, k=6, phi=0.8):
    kemiringan = np.mean(np.diff(y[-(k + 1):]))
    return y[-1] + kemiringan * np.cumsum(phi ** np.arange(1, h + 1))


def model_regresi(y, h, derajat, jendela=36):
    y = y[-jendela:]
    X = np.arange(len(y)).reshape(-1, 1)
    model = make_pipeline(PolynomialFeatures(degree=derajat), LinearRegression()).fit(X, y)
    return model.predict(np.arange(len(y), len(y) + h).reshape(-1, 1))


def kandidat_prediksi():
    return {
        'Harga tetap': model_datar,
        'Tren teredam': model_teredam,
        'Linear (36 bulan)': lambda y, h: model_regresi(y, h, 1),
        'Polinomial derajat 2 (36 bulan)': lambda y, h: model_regresi(y, h, 2),
    }


def prediksi_harga(seri, bulan_depan=6, uji_bulan=24):
    s = seri.dropna().sort_index().asfreq('MS').interpolate(limit_direction='both')
    y = s.values.astype(float)
    if len(y) < uji_bulan + bulan_depan + 12:
        return None
    kandidat = kandidat_prediksi()
    galat = {nama: [] for nama in kandidat}
    for o in range(len(y) - uji_bulan - bulan_depan + 1, len(y) - bulan_depan + 1):
        aktual = y[o:o + bulan_depan]
        for nama, f in kandidat.items():
            galat[nama].append(np.abs((aktual - f(y[:o], bulan_depan)) / aktual))
    galat = {nama: np.array(v) for nama, v in galat.items()}
    tabel = pd.DataFrame({'MAPE (%)': {nama: v.mean() * 100 for nama, v in galat.items()}})
    terbaik = tabel['MAPE (%)'].idxmin()
    lebar = np.maximum.accumulate(np.quantile(galat[terbaik], 0.9, axis=0))
    tanggal = pd.date_range(s.index[-1] + pd.offsets.MonthBegin(1), periods=bulan_depan, freq='MS')
    pred = kandidat[terbaik](y, bulan_depan)
    return {'model': terbaik, 'mape': float(tabel.loc[terbaik, 'MAPE (%)']), 'tabel': tabel.round(2),
            'prediksi': pd.Series(pred, index=tanggal), 'bawah': pd.Series(pred * (1 - lebar), index=tanggal),
            'atas': pd.Series(pred * (1 + lebar), index=tanggal)}


def titik_di_cincin(x, y, cincin):
    c = np.asarray(cincin)
    x1, y1, x2, y2 = c[:-1, 0], c[:-1, 1], c[1:, 0], c[1:, 1]
    silang = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
    return int(silang.sum()) % 2 == 1


def daftar_poligon(geometri):
    return [geometri['coordinates']] if geometri['type'] == 'Polygon' else geometri['coordinates']


def cari_poligon(fitur, x, y):
    for i, f in enumerate(fitur):
        for poligon in daftar_poligon(f['geometry']):
            luar = np.asarray(poligon[0])
            if x < luar[:, 0].min() or x > luar[:, 0].max() or y < luar[:, 1].min() or y > luar[:, 1].max():
                continue
            if titik_di_cincin(x, y, poligon[0]) and not any(titik_di_cincin(x, y, lubang) for lubang in poligon[1:]):
                return i
    return -1


def poligon_terdekat(fitur, x, y):
    terbaik = (-1, np.inf)
    for i, f in enumerate(fitur):
        for poligon in daftar_poligon(f['geometry']):
            luar = np.asarray(poligon[0])
            if x < luar[:, 0].min() - 0.5 or x > luar[:, 0].max() + 0.5 or y < luar[:, 1].min() - 0.5 or y > luar[:, 1].max() + 0.5:
                continue
            jarak = np.hypot((luar[:, 0] - x) * np.cos(np.radians(y)), luar[:, 1] - y).min() * 111.0
            if jarak < terbaik[1]:
                terbaik = (i, jarak)
    return terbaik


def petakan_pasar(pasar, fitur_kab, jarak_maks_km=10):
    baris = []
    for nama, lat, lon in zip(pasar[KOL_PASAR], pasar['lat'], pasar['lon']):
        i = cari_poligon(fitur_kab, lon, lat)
        metode, jarak = 'di dalam poligon', 0.0
        if i < 0:
            i, jarak = poligon_terdekat(fitur_kab, lon, lat)
            metode = 'poligon terdekat' if jarak <= jarak_maks_km else 'tidak terpetakan'
        ada = i >= 0 and metode != 'tidak terpetakan'
        prop = fitur_kab[i]['properties'] if ada else {}
        baris.append({KOL_PASAR: nama, 'gid_1': prop.get('GID_1'), 'gid_2': prop.get('GID_2'),
                      'metode_pemetaan': metode, 'jarak_km': round(jarak, 2) if ada else np.nan})
    return pd.DataFrame(baris)


def rapikan_nama(nama):
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', str(nama))


def nama_kab_kota(prop):
    nama = rapikan_nama(prop['NAME_2'])
    if prop.get('TYPE_2') == 'Kota':
        return nama if nama.startswith('Kota ') else 'Kota ' + nama
    if prop.get('TYPE_2') == 'Kabupaten':
        return 'Kab. ' + nama
    return nama


def sederhanakan_cincin(cincin, toleransi):
    hasil = [cincin[0]]
    for titik in cincin[1:-1]:
        if abs(titik[0] - hasil[-1][0]) >= toleransi or abs(titik[1] - hasil[-1][1]) >= toleransi:
            hasil.append(titik)
    hasil.append(cincin[0])
    return hasil


def sederhanakan_geometri(geometri, toleransi):
    poligon_baru = []
    for poligon in daftar_poligon(geometri):
        cincin_baru = [sederhanakan_cincin(c, toleransi) for c in poligon]
        if len(cincin_baru[0]) >= 4:
            poligon_baru.append([c for c in cincin_baru if len(c) >= 4])
    return {'type': 'MultiPolygon', 'coordinates': poligon_baru}


def rasio_harga_pasar(df, kolom, tahun):
    d = df[[KOL_PASAR, KOL_TANGGAL, kolom]].dropna().copy()
    d['rasio'] = d[kolom] / d.groupby(KOL_TANGGAL)[kolom].transform('median')
    d = d[d[KOL_TANGGAL].dt.year == tahun]
    return d.groupby(KOL_PASAR).agg(harga=(kolom, 'mean'), rasio=('rasio', 'mean'))


def volatilitas_pasar(df, item, tahun):
    d = df[df[KOL_TANGGAL].dt.year == tahun]
    rentang = (d[f'h_{item}'] - d[f'l_{item}']) / d[f'c_{item}'] * 100
    return rentang.groupby(d[KOL_PASAR]).mean()


def kelas_harga(selisih_persen):
    return np.select([selisih_persen < -BATAS_HARGA_PERSEN, selisih_persen > BATAS_HARGA_PERSEN], ['Murah', 'Mahal'], default='Sedang')


def kelas_volatilitas(nilai, nilai_pasar):
    b1, b2 = np.quantile(nilai_pasar.dropna(), [1 / 3, 2 / 3])
    return np.select([nilai <= b1, nilai <= b2], ['Stabil', 'Sedang'], default='Bergejolak')


def batas_geometri(geometri):
    titik = np.concatenate([np.asarray(p[0]) for p in daftar_poligon(geometri)])
    return titik[:, 0].min(), titik[:, 1].min(), titik[:, 0].max(), titik[:, 1].max()


def zoom_dari_batas(x_min, y_min, x_maks, y_maks, lebar_px=1100, tinggi_px=560):
    z_x = np.log2(lebar_px * 360 / (512 * max(x_maks - x_min, 1e-6)))
    z_y = np.log2(tinggi_px * 360 / (512 * max((y_maks - y_min) * 1.15, 1e-6)))
    return float(min(z_x, z_y, 10) - 0.3)


def uji_peringkat(dm, is_train, hasil, persen=0.1):
    jenis, fitur = hasil['skenario'][hasil['terbaik']]
    proba = hasil['model'][hasil['terbaik']].predict_proba(dm.loc[~is_train, fitur])
    kelas = list(hasil['model'][hasil['terbaik']].classes_)
    risiko = proba[:, kelas.index(1)] * 0.5 + proba[:, kelas.index(2)] if 2 in kelas else proba[:, kelas.index(1)] * 0.5
    lonjakan = (hasil['y_test'].values == 2)
    n_teratas = max(int(len(risiko) * persen), 1)
    teratas = np.argsort(-risiko)[:n_teratas]
    return {'persen': persen, 'tertangkap': float(lonjakan[teratas].sum() / max(lonjakan.sum(), 1)),
            'presisi': float(lonjakan[teratas].mean()), 'dasar': float(lonjakan.mean())}


def nama_provinsi(prop):
    khusus = {'JakartaRaya': 'DKI Jakarta', 'Yogyakarta': 'DI Yogyakarta', 'BangkaBelitung': 'Kepulauan Bangka Belitung'}
    return khusus.get(prop['NAME_1'], rapikan_nama(prop['NAME_1']))


def tabel_peta(df, info_pasar, item, tahun, lapisan, kolom_gid):
    pm = rasio_harga_pasar(df, f'c_{item}', tahun)
    if lapisan == 'Volatilitas':
        pm['nilai'] = volatilitas_pasar(df, item, tahun)
    else:
        pm['nilai'] = (pm['rasio'] - 1) * 100
    pm = pm.join(info_pasar[[kolom_gid]]).dropna(subset=[kolom_gid, 'nilai'])
    wil = pm.groupby(kolom_gid).agg(nilai=('nilai', 'mean'), harga=('harga', 'mean'), n=('nilai', 'size'))
    if lapisan == 'Volatilitas':
        wil['kelas'] = kelas_volatilitas(wil['nilai'], pm['nilai'])
    else:
        wil['kelas'] = kelas_harga(wil['nilai'])
    return wil, pm



def parse_cuaca_nasa(data, nama_pasar):
    p = data['properties']['parameter']
    baris = []
    for kunci, hujan in p['PRECTOTCORR'].items():
        if kunci.endswith('13'):
            continue
        suhu = p['T2M'].get(kunci)
        baris.append({KOL_PASAR: nama_pasar, 'bulan': pd.Timestamp(int(kunci[:4]), int(kunci[4:]), 1),
                      'hujan': np.nan if hujan <= -990 else hujan, 'suhu': np.nan if suhu is None or suhu <= -990 else suhu})
    return pd.DataFrame(baris)


def parse_oni(teks):
    baris = []
    for garis in teks.splitlines():
        bagian = garis.split()
        if len(bagian) >= 4 and bagian[0] in MUSIM_ONI and bagian[1].isdigit():
            baris.append({'bulan': pd.Timestamp(int(bagian[1]), MUSIM_ONI.index(bagian[0]) + 1, 1), 'oni': float(bagian[-1])})
    return pd.DataFrame(baris)


def hijriah_ke_masehi(tahun, bulan, hari):
    jd = hari + np.ceil(29.5 * (bulan - 1)) + (tahun - 1) * 354 + (3 + 11 * tahun) // 30 + 1948439.5 - 1
    return pd.Timestamp.fromordinal(int(jd - 2451544.5 + 730120))


def kalender_ramadan(tahun_awal=2006, tahun_akhir=2028):
    bulan_ramadan, bulan_idulfitri = set(), set()
    for th in range(1420, 1455):
        awal, akhir = hijriah_ke_masehi(th, 9, 1), hijriah_ke_masehi(th, 10, 1)
        for hari in pd.date_range(awal, akhir - pd.Timedelta(days=1)):
            bulan_ramadan.add((hari.year, hari.month))
        bulan_idulfitri.add((akhir.year, akhir.month))
    bulan = pd.date_range(f'{tahun_awal}-01-01', f'{tahun_akhir}-12-01', freq='MS')
    return pd.DataFrame({'bulan': bulan,
                         'ramadan_ada': [int((b.year, b.month) in bulan_ramadan) for b in bulan],
                         'idulfitri_ada': [int((b.year, b.month) in bulan_idulfitri) for b in bulan]})


def tambah_fitur_eksternal(out, cuaca=None, oni=None):
    out = out.copy()
    out['_bulan'] = out[KOL_TANGGAL].dt.to_period('M').dt.to_timestamp()
    if cuaca is not None and len(cuaca):
        c = cuaca.copy()
        c['bulan'] = pd.to_datetime(c['bulan'])
        c = c.sort_values([KOL_PASAR, 'bulan']).reset_index(drop=True)
        c['bln'] = c['bulan'].dt.month
        acuan = c[c['bulan'].dt.year <= TAHUN_ACUAN_AKHIR]
        normal = acuan.groupby([KOL_PASAR, 'bln'])[['hujan', 'suhu']].mean().rename(columns={'hujan': 'hujan_normal', 'suhu': 'suhu_normal'})
        c = c.join(normal, on=[KOL_PASAR, 'bln'])
        c['anom_hujan_ini'] = c['hujan'] - c['hujan_normal']
        c['anom_suhu_ini'] = c['suhu'] - c['suhu_normal']
        g = c.groupby(KOL_PASAR)
        c['anom_hujan_lag1'] = g['anom_hujan_ini'].shift(1)
        c['anom_hujan_lag2'] = g['anom_hujan_ini'].shift(2)
        c['anom_suhu_lag1'] = g['anom_suhu_ini'].shift(1)
        c = c.rename(columns={'hujan': 'hujan_ini', 'suhu': 'suhu_ini', 'bulan': '_bulan'})
        kolom = [KOL_PASAR, '_bulan', 'hujan_ini', 'suhu_ini', 'anom_hujan_ini', 'anom_hujan_lag1', 'anom_hujan_lag2', 'anom_suhu_ini', 'anom_suhu_lag1']
        out = out.merge(c[kolom], on=[KOL_PASAR, '_bulan'], how='left')
    if oni is not None and len(oni):
        o = oni.copy()
        o['_bulan'] = pd.to_datetime(o['bulan'])
        o = o.sort_values('_bulan').reset_index(drop=True)
        o['oni_ini'] = o['oni']
        o['oni_lag3'] = o['oni'].shift(3)
        out = out.merge(o[['_bulan', 'oni_ini', 'oni_lag3']], on='_bulan', how='left')
    kal = kalender_ramadan(out['_bulan'].dt.year.min() - 1, out['_bulan'].dt.year.max() + 1).set_index('bulan')
    depan = out['_bulan'] + pd.offsets.MonthBegin(1)
    out['ramadan_ini'] = out['_bulan'].map(kal['ramadan_ada']).values
    out['ramadan_depan'] = depan.map(kal['ramadan_ada']).values
    out['idulfitri_ini'] = out['_bulan'].map(kal['idulfitri_ada']).values
    out['idulfitri_depan'] = depan.map(kal['idulfitri_ada']).values
    return out.drop(columns='_bulan')


def daftar_fitur_eksternal(out):
    return [c for c in out.columns if c.startswith(('hujan_', 'suhu_', 'anom_', 'oni_', 'ramadan_', 'idulfitri_'))]
