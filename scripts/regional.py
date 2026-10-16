"""QUALIAR-UFAM: fumaça distante e fator de madrugada.

Fumaça distante (IFR, índice de fogo regional)
  Os focos do MonitorBETA cobrem 13 municípios em torno de Manaus. A fumaça de
  queimadas do Pará, do sul do Amazonas ou de Rondônia chega depois de 1 a 3 dias
  de viagem e não aparece nesse recorte. Aqui os focos vêm direto dos arquivos
  públicos do INPE (os mesmos que o MonitorBETA baixa para o Brasil inteiro),
  agregados por célula de 0,25 grau e por hora.

  Para cada hora-alvo, uma retrotrajetória parte da NAMA e volta 60 h no tempo
  seguindo o vento a 925 hPa (cerca de 800 m) numa grade de 24 pontos do
  Open-Meteo. Em cada hora do caminho, soma-se o que queimava perto do ponto
  (núcleo gaussiano que alarga com o tempo de viagem), descontando diluição,
  deposição e a chuva do caminho. O resultado é o IFR e a parte de cada estado.

Fator de madrugada
  Com camada de mistura rasa e vento forte em altitude, a fumaça viaja acima da
  inversão noturna e desce de uma vez no começo da manhã. O fator multiplica o
  termo de fumaça entre 03h e 10h quando a noite anterior foi estável e o vento
  a 925 hPa foi forte.

Diagnóstico (uma vez, no GitHub Actions):
  python scripts/regional.py --diagnostico
  recalcula o IFR das últimas 60 h e grava docs/data/diagnostico_regional.json
  com IFR, fator de madrugada, mediana observada e origem por estado, hora a hora.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import config as C  # noqa: E402

UTC = timezone.utc
TZ = ZoneInfo(C.FUSO)
UF_SIGLA = {"AMAZONAS": "AM", "PARÁ": "PA", "PARA": "PA", "RONDÔNIA": "RO", "RONDONIA": "RO", "RORAIMA": "RR",
            "AMAPÁ": "AP", "AMAPA": "AP", "MATO GROSSO": "MT", "ACRE": "AC", "TOCANTINS": "TO", "MARANHÃO": "MA",
            "MARANHAO": "MA"}


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def hora_cheia(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def http_text(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "qualiar-ufam/1.0 (UFAM)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def dist_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, a)))


def _num(x):
    try:
        v = float(str(x).replace(",", "."))
        return None if math.isnan(v) or v <= -999 else v
    except (TypeError, ValueError):
        return None


def _dt(s):
    s = str(s or "").strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


# ================================================================ limites dos 13 municípios
def poligonos(limites_gj):
    """Anéis externos dos municípios do MonitorBETA, com caixa envolvente, para excluir o fogo local."""
    out = []
    for f in (limites_gj or {}).get("features", []):
        g = f.get("geometry") or {}
        polys = g.get("coordinates", []) if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
        for p in polys:
            if not p:
                continue
            anel = p[0]
            xs, ys = [c[0] for c in anel], [c[1] for c in anel]
            out.append(((min(xs), min(ys), max(xs), max(ys)), anel))
    return out


def dentro(lat, lon, polys):
    for (x0, y0, x1, y1), anel in polys:
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        ins, j = False, len(anel) - 1
        for i in range(len(anel)):
            xi, yi = anel[i][0], anel[i][1]
            xj, yj = anel[j][0], anel[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
                ins = not ins
            j = i
        if ins:
            return True
    return False


# ================================================================ focos do INPE
def ler_csv_inpe(texto):
    for row in csv.DictReader(io.StringIO(texto)):
        r = {(k or "").strip().lower(): v for k, v in row.items()}
        lat, lon = _num(r.get("lat") or r.get("latitude")), _num(r.get("lon") or r.get("longitude"))
        t = _dt(r.get("data_hora_gmt") or r.get("datahora") or r.get("data"))
        if lat is None or lon is None or t is None:
            continue
        uf = (r.get("estado") or "").strip().upper()
        yield t, lat, lon, _num(r.get("frp")), UF_SIGLA.get(uf, uf[:2] if uf else "?")


def _agregar(cache, linhas, nama, polys):
    o, s, l, n = C.REG_CAIXA
    cel = cache.setdefault("celulas", {})
    g = C.REG_CELULA_GRAUS
    novos = 0
    for t, lat, lon, frp, uf in linhas:
        if not (o <= lon <= l and s <= lat <= n):
            continue
        if dist_km(nama["lat"], nama["lon"], lat, lon) < C.REG_DIST_MIN_KM or dentro(lat, lon, polys):
            continue                      # fogo local: já está no IFB do MonitorBETA
        la, lo = (math.floor(lat / g) + 0.5) * g, (math.floor(lon / g) + 0.5) * g
        k = f"{iso(hora_cheia(t))}|{la:.3f}|{lo:.3f}"
        w = min(5.0, max(1.0, (frp or 0) / C.REG_FRP_REF_MW))
        if k not in cel:
            novos += 1
            cel[k] = [w, uf]
        elif w > cel[k][0]:
            cel[k][0] = w
    return novos


def atualizar_focos(cache, agora, nama, polys, status, baixar=http_text):
    """Atualiza o cache {celulas: {"hora|lat|lon": [peso, UF]}, ultimo_10min: nome}."""
    inicio = agora - timedelta(hours=C.REG_GUARDA_H)
    total = 0
    # primeira vez (ou cache vazio): arquivos diários dos últimos dias cobrem o passado
    if not cache.get("celulas"):
        n = 0
        for dias in range(0, 4):
            d = (agora - timedelta(days=dias)).strftime("%Y%m%d")
            try:
                total += _agregar(cache, ler_csv_inpe(baixar(f"{C.INPE_FOCOS_URL}/diario/Brasil/focos_diario_br_{d}.csv")),
                                  nama, polys)
                n += 1
            except Exception:
                pass
        status["INPE diário"] = f"ok ({n} arquivos)" if n else "sem arquivos diários"
    try:
        idx = baixar(f"{C.INPE_FOCOS_URL}/10min/")
        nomes = sorted(set(re.findall(r'href="(focos_10min_(\d{8})_(\d{4})\.csv)"', idx)))
        ult = cache.get("ultimo_10min", "")
        pend = []
        for nome, d, hm in nomes:
            t = datetime.strptime(d + hm, "%Y%m%d%H%M").replace(tzinfo=UTC)
            if nome > ult and inicio <= t <= agora + timedelta(minutes=10):
                pend.append(nome)
        pend = pend[-C.REG_ARQUIVOS_MAX:]
        erros = 0
        for nome in pend:
            try:
                total += _agregar(cache, ler_csv_inpe(baixar(f"{C.INPE_FOCOS_URL}/10min/{nome}")), nama, polys)
                cache["ultimo_10min"] = nome
            except Exception:
                erros += 1
        status["INPE 10 min"] = f"ok ({len(pend)} arquivos novos{f', {erros} com erro' if erros else ''})"
    except Exception as e:
        status["INPE 10 min"] = f"erro: {e}"
    corte = iso(inicio)
    cache["celulas"] = {k: v for k, v in cache.get("celulas", {}).items() if k[:20] >= corte}
    return total


def gravar_cache(caminho, cache):
    """Uma célula por linha, em ordem: o git guarda só as linhas que mudam a cada hora."""
    linhas = [f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False)}" for k, v in sorted(cache.get("celulas", {}).items())]
    texto = ('{"ultimo_10min":' + json.dumps(cache.get("ultimo_10min", "")) + ',"celulas":{\n'
             + ",\n".join(linhas) + "\n}}\n")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def indexar(cache):
    """{hora (datetime): [(lat, lon, peso, UF), ...]}"""
    idx = {}
    for k, (w, uf) in cache.get("celulas", {}).items():
        t, la, lo = k.split("|")
        idx.setdefault(parse_iso(t), []).append((float(la), float(lo), w, uf))
    return idx


# ================================================================ vento a 925 hPa na região
class Campo:
    """Vento a 925 hPa e chuva numa grade de pontos, hora a hora."""

    def __init__(self, pontos):
        self.pontos = pontos      # [(lat, lon, {t: (u, v, mm)})]

    @classmethod
    def coletar(cls, http_json):
        lats = [la for la in C.REG_GRADE_LAT for _ in C.REG_GRADE_LON]
        lons = [lo for _ in C.REG_GRADE_LAT for lo in C.REG_GRADE_LON]
        q = {"latitude": ",".join(str(x) for x in lats), "longitude": ",".join(str(x) for x in lons),
             "hourly": "wind_speed_925hPa,wind_direction_925hPa,precipitation", "wind_speed_unit": "ms",
             "timezone": "GMT", "timeformat": "unixtime", "past_days": 3, "forecast_days": 2}
        d = http_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q))
        if isinstance(d, dict):
            d = [d]
        pontos = []
        for la, lo, p in zip(lats, lons, d):
            h = p["hourly"]
            s = {}
            for ts, vel, dire, mm in zip(h["time"], h["wind_speed_925hPa"], h["wind_direction_925hPa"], h["precipitation"]):
                if vel is None or dire is None:
                    continue
                r = math.radians(dire)
                s[datetime.fromtimestamp(ts, UTC)] = (-vel * math.sin(r), -vel * math.cos(r), mm or 0.0)
            pontos.append((la, lo, s))
        return cls(pontos)

    def em(self, lat, lon, t):
        """Vento (u, v) em m/s e chuva em mm no ponto e hora, por inverso do quadrado da distância."""
        su = sv = sm = sw = 0.0
        for la, lo, s in self.pontos:
            x = s.get(t)
            if x is None:
                continue
            d2 = (la - lat) ** 2 + ((lo - lon) * math.cos(math.radians(lat))) ** 2
            w = 1.0 / max(d2, 0.05)
            su += w * x[0]; sv += w * x[1]; sm += w * x[2]; sw += w
        return None if sw == 0 else (su / sw, sv / sw, sm / sw)


def trajetoria(campo, t_chegada, lat0, lon0, horas=None):
    """Retrotrajetória: [(k, tempo, lat, lon, chuva_mm)] de k = 0 (chegada) até k = horas."""
    horas = horas or C.REG_TRAJ_H
    pts = [(0, t_chegada, lat0, lon0, 0.0)]
    lat, lon, t = lat0, lon0, t_chegada
    for k in range(1, horas + 1):
        x = campo.em(lat, lon, t)
        if x is None:
            break
        u, v, mm = x
        # meio passo (ponto médio) para curvas mais fiéis
        la_m = lat - v * 1800 / 111320.0
        lo_m = lon - u * 1800 / (111320.0 * math.cos(math.radians(lat)))
        x2 = campo.em(la_m, lo_m, t - timedelta(minutes=30)) or campo.em(la_m, lo_m, t) or x
        u, v = x2[0], x2[1]
        lat -= v * 3600 / 111320.0
        lon -= u * 3600 / (111320.0 * math.cos(math.radians(lat)))
        t -= timedelta(hours=1)
        pts.append((k, t, lat, lon, mm))
    return pts


def ifr(traj, idx, agora):
    """Índice de fogo regional para uma trajetória: total e parte de cada estado."""
    agora_h = hora_cheia(agora)
    recentes = {}
    for hh in range(0, 25):
        for c in idx.get(agora_h - timedelta(hours=hh), []):
            kk = (c[0], c[1])
            if kk not in recentes or c[2] > recentes[kk][2]:
                recentes[kk] = c
    tot, por_uf, chuva_cum = 0.0, {}, 0.0
    for k, tau, lat, lon, mm in traj:
        chuva_cum += mm
        if k == 0:
            continue
        if tau <= agora_h:
            ativos = {}
            for hh in range(-1, C.REG_ATIVO_H + 1):
                for c in idx.get(tau - timedelta(hours=hh), []):
                    kk = (c[0], c[1])
                    if kk not in ativos or c[2] > ativos[kk][2]:
                        ativos[kk] = c
            fator = 1.0
        else:
            ativos, fator = recentes, C.REG_PERSISTENCIA
        if not ativos:
            continue
        sig = C.REG_SIGMA0_KM + C.REG_SIGMA_KMH * k
        jan = 3 * sig / 111.0
        perda = math.exp(-k / C.REG_TAU_H) * math.exp(-C.LAMBDA_ROTA * chuva_cum) * fator
        for la, lo, w, uf in ativos.values():
            if abs(la - lat) > jan or abs(lo - lon) > jan * 1.1:
                continue
            d = dist_km(lat, lon, la, lo)
            c = w * math.exp(-0.5 * (d / sig) ** 2) * perda
            if c > 1e-4:
                tot += c
                por_uf[uf] = por_uf.get(uf, 0.0) + c
    return tot, por_uf


# ================================================================ madrugada
def fator_noite(met, t):
    """Fator (>= 1) sobre o termo de fumaça na hora t, a partir da noite anterior.
    met = {iso: linha Open-Meteo da NAMA com blh e v925}."""
    w_hora = C.NOITE_HORAS.get(t.astimezone(TZ).hour, 0.0)
    if w_hora == 0:
        return 1.0, None
    estaveis, v925, n = 0, [], 0
    for k in range(1, 9):
        l = met.get(iso(t - timedelta(hours=k)))
        if not l:
            continue
        n += 1
        if l.get("blh") is not None:
            estaveis += l["blh"] < C.NOITE_BLH_M
        else:  # sem camada limite: madrugada local conta como estável
            estaveis += (t - timedelta(hours=k)).astimezone(TZ).hour in (20, 21, 22, 23, 0, 1, 2, 3, 4, 5)
        if l.get("v925") is not None:
            v925.append(l["v925"])
    if n < 4 or not v925:
        return 1.0, None
    f_est = estaveis / n
    vm = sum(v925) / len(v925)
    f_jato = min(1.0, max(0.0, (vm - C.NOITE_V925_MIN) / (C.NOITE_V925_PLENO - C.NOITE_V925_MIN)))
    f = 1.0 + C.NOITE_A * w_hora * f_est * f_jato
    return f, {"estavel": round(f_est, 2), "v925_ms": round(vm, 1), "peso_hora": w_hora}


# ================================================================ calibração
def calibrar_k(hist, serie, h0, pm_base):
    """K_reg por mínimos quadrados sem intercepto: anomalia ~ K x IFR x fator.
    Usa as últimas 72 h com IFR relevante; antes disso, puxa para o valor inicial."""
    pares = []
    for r in hist:
        t = parse_iso(r["t"])
        if not (h0 - timedelta(hours=72) < t <= h0):
            continue
        x = r["ifr"] * r.get("noite", 1.0)
        obs = serie.get(r["t"])
        if obs is None or x < C.IFR_MIN:
            continue
        pares.append((max(0.0, obs - pm_base), x))
    if not pares:
        return C.K_REG_INICIAL, 0
    est = sum(a * x for a, x in pares) / sum(x * x for _, x in pares)
    est = min(C.K_REG_MAX, max(C.K_REG_MIN, est))
    if len(pares) < C.K_REG_MIN_HORAS:     # poucas horas: média geométrica com o valor inicial
        frac = len(pares) / C.K_REG_MIN_HORAS
        est = math.exp((1 - frac) * math.log(C.K_REG_INICIAL) + frac * math.log(est))
    return est, len(pares)


def calcular(campo, idx, agora, nama, horas_alvo):
    """IFR por hora-alvo: {t: (ifr, por_uf)} e a trajetória que chega agora (para o mapa)."""
    out, traj0 = {}, None
    for t in horas_alvo:
        tr = trajetoria(campo, t, nama["lat"], nama["lon"])
        out[t] = ifr(tr, idx, agora)
        if t == hora_cheia(agora):
            traj0 = [[round(p[2], 3), round(p[3], 3), p[0]] for p in tr if p[0] % 3 == 0]
    return out, traj0


def preencher_historico(hist, campo, idx, agora, nama, met):
    """Completa o IFR das horas passadas que ainda não têm (primeira rodada, ou lacunas),
    com os focos e ventos de então, para calibrar K_reg sem esperar dias."""
    h0 = hora_cheia(agora)
    tem = {r["t"] for r in hist}
    for k in range(0, C.REG_TRAJ_H + 1):
        t = h0 - timedelta(hours=k)
        if iso(t) in tem:
            continue
        v, uf = ifr(trajetoria(campo, t, nama["lat"], nama["lon"]), idx, t)
        if campo.em(nama["lat"], nama["lon"], t) is None:
            continue
        f, _ = fator_noite(met, t)
        hist.append({"t": iso(t), "ifr": round(v, 2), "noite": round(f, 2),
                     "uf": {u: round(x / v, 2) for u, x in sorted(uf.items(), key=lambda z: -z[1])[:4]} if v > 0 else {}})
    corte = iso(h0 - timedelta(hours=C.REG_GUARDA_H * 2))
    hist[:] = sorted((r for r in hist if r["t"] >= corte), key=lambda r: r["t"])


# ================================================================ diagnóstico
def main():
    import argparse
    import qualiar as Q
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostico", action="store_true")
    a = ap.parse_args()
    if not a.diagnostico:
        ap.print_help(); return
    agora = datetime.now(UTC)
    hist = Q.ler_json("historico.json", {"horas": []})
    conhecida = hist.get("estado", {}).get("nama") or {}
    nama = {"lat": conhecida.get("lat", C.NAMA_LAT_PADRAO), "lon": conhecida.get("lon", C.NAMA_LON_PADRAO)}
    status = {}
    cache = Q.ler_json("fogo_regional.json", {})
    lim = Q.ler_json("limites.geojson", None)
    atualizar_focos(cache, agora, nama, poligonos(lim), status)
    gravar_cache(C.DATA_DIR / "fogo_regional.json", cache)
    campo = Campo.coletar(Q.http_json)
    meteo = Q.coletar_meteo(nama["lat"], nama["lon"])
    met = {l["t"]: l for l in meteo}
    serie = {h["t"]: h["mediana"] for h in hist["horas"]}
    idx = indexar(cache)
    linhas = []
    for k in range(C.REG_TRAJ_H, -1, -1):
        t = hora_cheia(agora) - timedelta(hours=k)
        v, uf = ifr(trajetoria(campo, t, nama["lat"], nama["lon"]), idx, t)
        f, det = fator_noite(met, t)
        linhas.append({"t": iso(t), "local": t.astimezone(TZ).strftime("%d/%m %Hh"), "obs": serie.get(iso(t)),
                       "ifr": round(v, 2), "noite": round(f, 2), "noite_det": det,
                       "uf": {u: round(x / v, 2) for u, x in sorted(uf.items(), key=lambda z: -z[1])[:4]} if v > 0 else {}})
    hreg = []
    preencher_historico(hreg, campo, idx, agora, nama, met)
    kreg, n = calibrar_k(hreg, serie, hora_cheia(agora), C.PM_BASE)
    saida = {"gerado_em": iso(agora), "status": status, "celulas": len(cache.get("celulas", {})),
             "k_reg": round(kreg, 3), "horas_calibracao": n, "horas": linhas}
    Q.gravar_json("diagnostico_regional.json", saida)
    for l in linhas:
        print(l["local"], l["obs"], l["ifr"], l["noite"], l["uf"])
    print("status", status, "K_reg", round(kreg, 3), "horas", n)


if __name__ == "__main__":
    main()
