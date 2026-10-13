"""QUALIAR-UFAM: coleta, modelo v0 e validação. Roda de hora em hora.

Fontes:
  - PurpleAir (PM2,5 dos sensores de Manaus) .... chave em PURPLEAIR_API_KEY
  - Open-Meteo (meteorologia observada/prevista) . sem chave
  - MonitorBETA (focos de calor e limites) ....... JSON público do site

Uso:
  python scripts/qualiar.py                 # coleta real
  python scripts/qualiar.py --semear        # também baixa 24 h de histórico horário da PurpleAir
  python scripts/qualiar.py --teste         # dados sintéticos de PM2,5/meteorologia + focos da amostra local
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import config as C  # noqa: E402
import chuva as R  # noqa: E402

TZ = ZoneInfo(C.FUSO)
UTC = timezone.utc


# ================================================================ utilidades
def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hora_cheia(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def http_json(url: str, headers: dict | None = None, tentativas: int = 3, timeout: int = 40):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "QUALIAR-UFAM/1.0", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                raise
            erro = e
        except Exception as e:  # rede instável
            erro = e
        time.sleep(2 * (i + 1))
    raise erro


def ler_json(nome, padrao):
    p = C.DATA_DIR / nome
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return padrao


def gravar_json(nome, obj):
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (C.DATA_DIR / nome).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def dist_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rumo_graus(lat1, lon1, lat2, lon2):
    """Direção (0 = norte, sentido horário) do ponto 1 para o ponto 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def ponto_cardeal(g):
    nomes = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]
    return nomes[int((g + 22.5) // 45) % 8]


# ================================================================ PM2,5
def correcao_epa(cf1: float, ur: float | None) -> float:
    """Correção EPA para PurpleAir (Barkjohn et al. 2021) com a extensão para
    fumaça extrema (Barkjohn et al. 2022). cf1 = média dos canais A e B (cf_1)."""
    ur = 50.0 if ur is None else max(0.0, min(100.0, ur))
    pa = max(0.0, cf1)
    if pa < 30:
        v = 0.524 * pa - 0.0862 * ur + 5.75
    elif pa < 50:
        f = pa / 20 - 3 / 2
        v = (0.786 * f + 0.524 * (1 - f)) * pa - 0.0862 * ur + 5.75
    elif pa < 210:
        v = 0.786 * pa - 0.0862 * ur + 5.75
    elif pa < 260:
        f = pa / 50 - 21 / 5
        v = ((0.69 * f + 0.786 * (1 - f)) * pa - 0.0862 * ur * (1 - f)
             + 2.966 * f + 5.75 * (1 - f) + 8.84e-4 * pa ** 2 * f)
    else:
        v = 2.966 + 0.69 * pa + 8.84e-4 * pa ** 2
    return max(0.0, v)


def qc_ab(a, b):
    if a is None or b is None:
        return (a is not None or b is not None), "um canal só"
    dif = abs(a - b)
    rel = dif / max((a + b) / 2, 1e-6)
    if dif > C.QC_DIF_ABS and rel > C.QC_DIF_REL:
        return False, f"canais A/B divergentes ({a:.0f} e {b:.0f})"
    return True, "ok"


def processar_sensor(s):
    a, b = s.get("a"), s.get("b")
    ok, motivo = qc_ab(a, b)
    vals = [v for v in (a, b) if v is not None]
    s["valido"] = bool(ok and vals)
    s["motivo"] = motivo if not s["valido"] or motivo != "ok" else None
    s["pm_bruto"] = round(sum(vals) / len(vals), 1) if vals else None
    s["pm"] = round(correcao_epa(s["pm_bruto"], s.get("ur")), 1) if s["valido"] else None
    s["classe"] = C.classe_de(s["pm"])
    return s


def coletar_purpleair(chave: str, agora: datetime):
    q = {
        "fields": ",".join(C.PA_CAMPOS),
        "max_age": C.PA_MAX_IDADE_S,
        "nwlng": C.PA_NW[0], "nwlat": C.PA_NW[1], "selng": C.PA_SE[0], "selat": C.PA_SE[1],
    }
    url = "https://api.purpleair.com/v1/sensors?" + urllib.parse.urlencode(q)
    d = http_json(url, {"X-API-Key": chave})
    campos = d["fields"]
    sensores = []
    for linha in d.get("data", []):
        r = dict(zip(campos, linha))
        sensores.append({
            "id": r.get("sensor_index"), "nome": r.get("name") or f"PA {r.get('sensor_index')}",
            "lat": r.get("latitude"), "lon": r.get("longitude"),
            "a": r.get("pm2.5_cf_1_a"), "b": r.get("pm2.5_cf_1_b"),
            "ur": r.get("humidity"), "t_f": r.get("temperature"),
            "visto": iso(datetime.fromtimestamp(r["last_seen"], UTC)) if r.get("last_seen") else None,
            "interno": r.get("location_type") == 1,
        })
    for s in sensores:
        # PurpleAir informa temperatura em °F, medida dentro da caixa (alguns °C acima do ar)
        s["t"] = round((s.pop("t_f") - 32) * 5 / 9, 1) if s.get("t_f") is not None else None
        processar_sensor(s)
        if s["interno"] and s["valido"]:
            s["valido"], s["motivo"], s["pm"], s["classe"] = False, "sensor interno (fora da mediana)", None, None
    return sensores


def semear_historico_pa(chave, sensores, agora, historico):
    """Baixa médias horárias das últimas 24 h de cada sensor (custa mais pontos; usar uma vez)."""
    ini = int((agora - timedelta(hours=26)).timestamp())
    por_hora: dict[str, dict] = {}
    for s in sensores:
        q = {"start_timestamp": ini, "average": 60, "fields": "pm2.5_cf_1_a,pm2.5_cf_1_b,humidity"}
        try:
            d = http_json(f"https://api.purpleair.com/v1/sensors/{s['id']}/history?" + urllib.parse.urlencode(q),
                          {"X-API-Key": chave})
        except Exception as e:
            print(f"  histórico de {s['id']} falhou: {e}")
            continue
        campos = d["fields"]
        for linha in d.get("data", []):
            r = dict(zip(campos, linha))
            t = iso(hora_cheia(datetime.fromtimestamp(r["time_stamp"], UTC)))
            tmp = processar_sensor({"a": r.get("pm2.5_cf_1_a"), "b": r.get("pm2.5_cf_1_b"), "ur": r.get("humidity")})
            if tmp["valido"]:
                por_hora.setdefault(t, {})[str(s["id"])] = tmp["pm"]
    for t, vals in por_hora.items():
        registrar_hora(historico, t, vals)


def registrar_hora(historico, t_iso, valores: dict, met_sens: dict | None = None):
    vals = [v for v in valores.values() if v is not None]
    if len(vals) < C.SENSORES_MIN:
        return
    item = {"t": t_iso, "mediana": round(median(vals), 1), "n": len(vals), "sensores": valores}
    if met_sens:
        item["met"] = met_sens   # {id: [pm, ur, t]} para a assinatura de chuva da hora seguinte
    historico["horas"] = [h for h in historico["horas"] if h["t"] != t_iso] + [item]
    historico["horas"].sort(key=lambda h: h["t"])
    historico["horas"] = historico["horas"][-C.HISTORICO_H:]


def achar_nama(sensores, estado: dict):
    """Acha a estação central. Retorna (sensor ou posição guardada, origem)."""
    conhecida = estado.get("nama") or {}
    alvo_id = C.NAMA_SENSOR_INDEX or conhecida.get("id")
    nome = C.NAMA_NOME.strip().lower()
    achado, origem = None, None
    for s in sensores:
        if alvo_id is not None and s["id"] == alvo_id:
            achado, origem = s, f"sensor {s['id']} ({s['nome']})"; break
    if not achado:
        for s in sensores:
            if str(s["nome"]).strip().lower() == nome:
                achado, origem = s, f"nome exato na PurpleAir (sensor {s['id']})"; break
    if not achado:
        for s in sensores:
            if "nama" in str(s["nome"]).lower():
                achado, origem = s, f"nome parecido na PurpleAir: {s['nome']} (sensor {s['id']})"; break
    if achado:
        estado["nama"] = {"id": achado["id"], "nome": achado["nome"], "lat": achado["lat"], "lon": achado["lon"]}
        return achado, origem
    if conhecida.get("lat") is not None:
        return {"id": conhecida.get("id"), "nome": conhecida.get("nome"), "lat": conhecida["lat"], "lon": conhecida["lon"],
                "pm": None, "classe": None, "_offline": True}, "última posição conhecida (sensor sem dados nesta hora)"
    return None, "coordenadas padrão do campus (config.py)"


# ================================================================ meteorologia
def coletar_meteo(lat, lon):
    base = "https://api.open-meteo.com/v1/forecast?"
    q = {
        "latitude": lat, "longitude": lon, "timezone": "GMT", "timeformat": "unixtime",
        "past_days": 31, "forecast_days": 3, "wind_speed_unit": "ms",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,precipitation_probability,"
                  "wind_speed_10m,wind_direction_10m",
    }
    d = http_json(base + urllib.parse.urlencode(q))
    h = d["hourly"]
    linhas = []
    for i, ts in enumerate(h["time"]):
        linhas.append({
            "t": iso(datetime.fromtimestamp(ts, UTC)),
            "temp": h["temperature_2m"][i], "ur": h["relative_humidity_2m"][i],
            "chuva": h["precipitation"][i], "prob": h["precipitation_probability"][i],
            "vento": h["wind_speed_10m"][i], "dir": h["wind_direction_10m"][i], "blh": None, "v925": None, "d925": None,
        })
    opcionais = [("boundary_layer_height", ["blh"]),
                 ("wind_speed_925hPa,wind_direction_925hPa", ["v925", "d925"])]
    for campos, chaves in opcionais:  # nem todo modelo fornece; opcional
        try:
            q2 = {k: v for k, v in q.items() if k != "hourly"}
            q2["hourly"] = campos
            d2 = http_json(base + urllib.parse.urlencode(q2), tentativas=1)
            hh_ = d2["hourly"]
            idx = {iso(datetime.fromtimestamp(ts, UTC)): i for i, ts in enumerate(hh_["time"])}
            for l in linhas:
                i = idx.get(l["t"])
                for ch, cp in zip(chaves, campos.split(",")):
                    l[ch] = hh_[cp][i] if i is not None else None
        except Exception as e:
            print(f"  {campos} indisponível: {e}")
    return linhas


def resumo_chuva(linhas, agora):
    """Dias consecutivos sem chuva (< 1 mm/dia, dias locais completos até ontem) e acumulados."""
    por_dia: dict[str, float] = {}
    for l in linhas:
        t = parse_iso(l["t"])
        if t > agora:
            continue
        dia = t.astimezone(TZ).date().isoformat()
        por_dia[dia] = por_dia.get(dia, 0.0) + (l["chuva"] or 0.0)
    hoje = agora.astimezone(TZ).date()
    dias = 0
    for k in range(1, 32):
        d = (hoje - timedelta(days=k)).isoformat()
        if d not in por_dia:
            break
        if por_dia[d] < 1.0:
            dias += 1
        else:
            break
    def acum(n):
        return round(sum(v for d, v in por_dia.items() if (hoje - datetime.fromisoformat(d).date()).days <= n), 1)
    return {"dias_sem_chuva": dias, "chuva_hoje_mm": round(por_dia.get(hoje.isoformat(), 0.0), 1),
            "chuva_7d_mm": acum(7), "chuva_30d_mm": acum(30)}


# ================================================================ focos
def baixar_monitorbeta():
    return (http_json(C.MONITORBETA_URL + "focos.geojson"),
            http_json(C.MONITORBETA_URL + "resumo.json"),
            http_json(C.MONITORBETA_URL + "limites.geojson"))


def preparar_focos(focos_gj, nama, agora):
    out = []
    for f in focos_gj.get("features", []):
        p = f["properties"]
        d = dist_km(nama["lat"], nama["lon"], p["lat"], p["lon"])
        ult = parse_iso(p["ultima_deteccao"])
        idade = max(0.0, (agora - ult).total_seconds() / 3600)
        if p["status"] == "ativo":
            cat = "ativo"
            incendio = ((p.get("duracao_h") or 0) >= C.INCENDIO_DURACAO_H
                        or (p.get("n_pixels") or 0) >= C.INCENDIO_PIXELS
                        or (p.get("frp_max") or 0) >= C.INCENDIO_FRP_MW)
        else:
            fim = parse_iso(p["extincao_ate"]) if p.get("extincao_ate") else ult
            cat = "recem_extinto" if (agora - fim).total_seconds() / 3600 <= C.RECEM_EXTINTO_H else "extinto"
            incendio = False
        out.append({
            "id": p["id"], "municipio": p.get("municipio") or "—", "lat": p["lat"], "lon": p["lon"],
            "categoria": cat, "provavel_incendio": incendio, "dist_km": round(d, 1),
            "rumo": round(rumo_graus(nama["lat"], nama["lon"], p["lat"], p["lon"]), 0),
            "idade_h": round(idade, 1), "frp_max": p.get("frp_max"), "n_pixels": p.get("n_pixels"),
            "duracao_h": p.get("duracao_h"), "ultima_deteccao": p["ultima_deteccao"],
            "primeira_deteccao": p.get("primeira_deteccao") or p["ultima_deteccao"],
            "fim_emissao": (p.get("extincao_ate") or p["ultima_deteccao"]) if p["status"] != "ativo" else None,
        })
    return out


def resumo_municipios(focos):
    tab = {m: {"municipio": m, "ativos": 0, "recem_extintos": 0, "provaveis_incendios": 0, "dist_min_km": None}
           for m in C.MUNICIPIOS}
    for f in focos:
        if f["categoria"] == "extinto":
            continue
        r = tab.setdefault(f["municipio"], {"municipio": f["municipio"], "ativos": 0, "recem_extintos": 0,
                                             "provaveis_incendios": 0, "dist_min_km": None})
        if f["categoria"] == "ativo":
            r["ativos"] += 1
        else:
            r["recem_extintos"] += 1
        if f["provavel_incendio"]:
            r["provaveis_incendios"] += 1
        if r["dist_min_km"] is None or f["dist_km"] < r["dist_min_km"]:
            r["dist_min_km"] = f["dist_km"]
    return sorted(tab.values(), key=lambda r: (-(r["ativos"] + r["recem_extintos"]), r["municipio"]))


def _vec(vel, dire):
    """Vetor (u, v) para onde o vento sopra; dire = de onde vem (graus)."""
    r = math.radians(dire)
    return -vel * math.sin(r), -vel * math.cos(r)


def vento_transporte(linha):
    """Média vetorial do vento a 10 m e a 925 hPa (camada onde a fumaça viaja)."""
    if not linha or linha.get("vento") is None or linha.get("dir") is None:
        return None
    u, v = _vec(linha["vento"], linha["dir"])
    if linha.get("v925") is not None and linha.get("d925") is not None:
        u2, v2 = _vec(linha["v925"], linha["d925"])  # wind_speed_unit=ms vale para todos os níveis
        p = C.VT_PESO_925
        u, v = (1 - p) * u + p * u2, (1 - p) * v + p * v2
    return u, v


class Ventos:
    """Série horária do vento de transporte e da chuva no ponto da NAMA."""

    def __init__(self, meteo, chuva_obs: dict | None = None):
        self.uv, self.chuva = {}, {}
        for l in meteo:
            t = parse_iso(l["t"])
            uv = vento_transporte(l)
            if uv:
                self.uv[t] = uv
            self.chuva[t] = l.get("chuva") or 0.0
        # horas passadas: a chuva observada prevalece quando o modelo não a viu
        for t, mm in (chuva_obs or {}).items():
            self.chuva[t] = max(self.chuva.get(t, 0.0), mm)

    def media(self, t_ini, t_fim):
        """Vento médio no intervalo: velocidade escalar média, direção do vetor
        médio e desvio angular circular (variação da direção no trajeto)."""
        t = hora_cheia(t_ini)
        us, vs, vel = [], [], []
        while t <= t_fim:
            if t in self.uv:
                u, v = self.uv[t]; us.append(u); vs.append(v); vel.append(math.hypot(u, v))
            t += timedelta(hours=1)
        if not us:
            return None
        um, vm = sum(us) / len(us), sum(vs) / len(vs)
        vmed = sum(vel) / len(vel)
        r = min(1.0, math.hypot(um, vm) / max(vmed, 1e-6))   # 1 = direção constante
        desvio = math.degrees(math.sqrt(-2 * math.log(max(r, 1e-6))))
        de_onde = (math.degrees(math.atan2(-um, -vm)) + 360) % 360
        return {"vel": vmed, "vel_resultante": math.hypot(um, vm), "dir": de_onde, "desvio": min(desvio, 90.0)}

    def chuva_entre(self, t_ini, t_fim):
        t, s = hora_cheia(t_ini), 0.0
        while t <= t_fim:
            s += self.chuva.get(t, 0.0); t += timedelta(hours=1)
        return s


def sigma_angular(vel, desvio):
    f = min(1.0, max(0.0, (vel - 1.0) / 4.0))
    s_estab = C.SIGMA_ANG_MAX - f * (C.SIGMA_ANG_MAX - C.SIGMA_ANG_MIN)
    return min(C.SIGMA_ANG_TOTAL_MAX, math.hypot(s_estab, desvio))


def emissao(f, t_e, agora):
    """1 se o foco estava queimando em t_e; decai para emissões futuras."""
    ini = parse_iso(f["primeira_deteccao"]) - timedelta(hours=C.MARGEM_DETECCAO_H)
    if t_e < ini:
        return 0.0
    if f["fim_emissao"]:                       # extinto (estimado)
        return 1.0 if t_e <= parse_iso(f["fim_emissao"]) else 0.0
    if t_e <= agora:
        return 1.0
    tau = C.PERSIST_INCENDIO_H if f["provavel_incendio"] else C.PERSIST_FOGO_H
    return math.exp(-(t_e - agora).total_seconds() / 3600 / tau)


def peso_foco(f):
    frp = f.get("frp_max")
    if frp:
        w = min(10.0, max(1.0, frp / C.IFB_FRP_REF_MW))
    else:
        w = min(5.0, max(1.0, math.sqrt(f.get("n_pixels") or 1)))
    frac_ft = C.INJ_FT_MIN + (C.INJ_FT_MAX - C.INJ_FT_MIN) * min(1.0, max(0.0, ((frp or 0) - C.INJ_FRP_INI) / (C.INJ_FRP_FIM - C.INJ_FRP_INI)))
    return w * (1 - frac_ft)


def ifb(focos, ventos: Ventos, t_alvo: datetime, agora: datetime, detalhar=False):
    """Índice de fogo a barlavento para a hora t_alvo.
    Retorna total, por anel, por município e o vento do trajeto curto (para o mapa)."""
    tot, aneis, por_mun = 0.0, [0.0] * len(C.IFB_ANEIS_KM), {}
    cache = {}
    for f in focos:
        d = f["dist_km"]
        # tempo de viagem, com uma iteração: vento no alvo -> vento médio no trajeto
        m = ventos.media(t_alvo, t_alvo)
        if not m:
            continue
        for _ in range(2):
            vel = max(m["vel"], C.IFB_VEL_DERIVA_MS)
            T = min(C.IFB_JANELA_H, d / (vel * 3.6))
            chave = (round(T), )
            if chave not in cache:
                cache[chave] = ventos.media(t_alvo - timedelta(hours=round(T)), t_alvo) or m
            m = cache[chave]
        vel = m["vel"]
        T = d / (max(vel, C.IFB_VEL_DERIVA_MS) * 3.6)
        if T > C.IFB_JANELA_H:
            continue
        t_e = t_alvo - timedelta(hours=T)
        e = emissao(f, t_e, agora)
        if e <= 0:
            continue
        if m["vel_resultante"] < C.IFB_CALMARIA_MS:
            ang, dil, fU = 1.0, math.exp(-d / C.IFB_L_CALMA_KM), 1.0   # sem direção: só a distância importa
        else:
            sig = sigma_angular(vel, m["desvio"])
            dth = (f["rumo"] - m["dir"] + 180) % 360 - 180
            ang = math.exp(-0.5 * (dth / sig) ** 2)
            dil = math.exp(-d / C.IFB_L_KM)
            fU = min(C.IFB_FU_MAX, max(C.IFB_FU_MIN, C.IFB_U_REF_MS / max(vel, 0.1)))
        chuva = ventos.chuva_entre(t_e, t_alvo)
        c = peso_foco(f) * e * dil * ang * fU * math.exp(-C.LAMBDA_ROTA * chuva)
        if c <= 0:
            continue
        tot += c
        for i, (a_, b_) in enumerate(C.IFB_ANEIS_KM):
            if a_ <= d < b_:
                aneis[i] += c
        por_mun[f["municipio"]] = por_mun.get(f["municipio"], 0.0) + c
        if detalhar:
            f.setdefault("_contrib", {})[iso(t_alvo)] = c
    # vento do trajeto típico de 50 km, para desenhar o setor no mapa
    m50 = ventos.media(t_alvo - timedelta(hours=6), t_alvo)
    setor = None
    if m50:
        setor = {"dir": round(m50["dir"]), "vel": round(m50["vel"], 1),
                 "sigma": round(sigma_angular(m50["vel"], m50["desvio"])),
                 "calmaria": m50["vel_resultante"] < C.IFB_CALMARIA_MS}
    return tot, aneis, por_mun, setor


# ================================================================ modelo v0
def fator_diurno(linha_meteo, t: datetime):
    if linha_meteo and linha_meteo.get("blh"):
        f = math.sqrt(C.BLH_REF_M / max(50.0, linha_meteo["blh"]))
    else:  # curva típica: camada rasa de madrugada, profunda à tarde
        hl = t.astimezone(TZ).hour
        f = 1 + 0.35 * math.cos(2 * math.pi * (hl - 6) / 24)
    return min(C.FATOR_DIURNO_MAX, max(C.FATOR_DIURNO_MIN, f))


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_classes(pm, sigma):
    """Probabilidade de cada classe supondo erro log-normal em torno da previsão."""
    lim = [c["ate"] for c in C.CLASSES[:-1]]
    acum, ps, ant = [], [], 0.0
    for b in lim:
        acum.append(norm_cdf((math.log(b) - math.log(max(pm, 0.1))) / sigma))
    for a in acum:
        ps.append(a - ant); ant = a
    ps.append(1 - ant)
    return [round(p, 3) for p in ps]


def prever(agora, p0, historico, meteo, focos, lavagem=None, chuva_obs=None):
    h0 = hora_cheia(agora)
    met = {l["t"]: l for l in meteo}
    m_agora = met.get(iso(h0))
    # tendência das últimas 3 h (µg/m³ por hora)
    serie = {h["t"]: h["mediana"] for h in historico["horas"]}
    p3 = serie.get(iso(h0 - timedelta(hours=3)))
    tend = (p0 - p3) / 3 if p3 is not None else 0.0
    ventos = Ventos(meteo, chuva_obs)
    ifb0, aneis0, mun0, setor0 = ifb(focos, ventos, h0, agora, detalhar=True)
    e0 = max(0.0, p0 - C.PM_BASE)
    lav = lavagem or {}
    estado = historico.setdefault("estado", {})
    lacuna = 0.0
    if lav.get("recente"):
        # Ar lavado pela chuva: a anomalia de agora não representa a fumaça regional.
        # Não recalibra K, não projeta a queda como tendência e prevê a volta da fumaça.
        k = estado.get("k_seco") or C.K_FOGO
        tend = max(0.0, tend)
        t_seco = estado.get("t_seco")
        if t_seco and (h0 - parse_iso(t_seco)).total_seconds() / 3600 <= C.ANOMALIA_SECA_MAX_H:
            lacuna = max(0.0, estado.get("anomalia_seca", 0.0) - e0)
    else:
        # calibração online de K: média geométrica entre o valor inicial e o observado agora
        if ifb0 > 0.5 and e0 > 0:
            k = math.sqrt(C.K_FOGO * min(C.K_MAX, max(C.K_MIN, e0 / ifb0)))
        else:
            k = C.K_FOGO
        estado.update({"k_seco": round(k, 3), "anomalia_seca": round(e0, 1), "t_seco": iso(h0)})
    d0 = fator_diurno(m_agora, h0)
    chuva_acum = 0.0
    prev = []
    for h in C.HORIZONTES:
        t = h0 + timedelta(hours=h)
        m = met.get(iso(t))
        chuva_h = (m["chuva"] or 0.0) if m else 0.0
        # pancada em curso que o modelo não previu: continua um pouco nas próximas horas
        chuva_h = max(chuva_h, lav.get("mm_agora", 0.0) * C.NOWCAST_FRAC.get(h, 0.0))
        chuva_acum += chuva_h
        ifb_h, aneis_h, mun_h, setor_h = ifb(focos, ventos, t, agora, detalhar=h in C.DESTAQUES_H)
        dec = math.exp(-h / C.TAU_PERSIST_H)
        exc = e0 * dec + k * ifb_h * (1 - dec)
        exc += tend * C.TAU_TENDENCIA_H * (1 - math.exp(-h / C.TAU_TENDENCIA_H))
        # volta da fumaça que a pancada removeu (o ar de fora da área molhada chega)
        recup = lacuna * (1 - math.exp(-h / C.TAU_RECUPERACAO_H)) * dec
        exc += recup
        exc = max(0.0, exc) * math.exp(-C.LAMBDA_CHUVA * chuva_acum)
        # fator diurno relativo ao agora; p0 já contém a condição atual
        pm = max(1.0, (C.PM_BASE + exc) * fator_diurno(m, t) / d0)
        sig = C.SIGMA_BASE + C.SIGMA_POR_RAIZ_H * math.sqrt(h)
        prev.append({
            "h": h, "t": iso(t), "pm": round(pm, 1),
            "lo": round(pm * math.exp(-1.28 * sig), 1), "hi": round(pm * math.exp(1.28 * sig), 1),
            "classe": C.classe_de(pm), "prob": prob_classes(pm, sig),
            "ifb": round(ifb_h, 2), "chuva_acum_mm": round(chuva_acum, 1),
            "ifb_aneis": [round(x, 2) for x in aneis_h], "setor": setor_h,
            "fogo_ug": round(k * ifb_h * (1 - dec), 1), "recuperacao_ug": round(recup, 1),
            "municipios": {mu: round(v / ifb_h, 3) for mu, v in sorted(mun_h.items(), key=lambda x: -x[1])} if ifb_h > 0 else {},
        })
    # média móvel de 24 h (observado + previsto) para a classe regulatória
    for p in prev:
        t = parse_iso(p["t"])
        vals, nobs = [], 0
        for k_ in range(24):
            tt = iso(t - timedelta(hours=k_))
            if tt in serie:
                vals.append(serie[tt]); nobs += 1
            else:
                pp = next((x for x in prev if x["t"] == tt), None)
                if pp:
                    vals.append(pp["pm"])
                elif tt == iso(h0):
                    vals.append(p0); nobs += 1
        p["media24"] = round(sum(vals) / len(vals), 1) if vals else None
        p["horas_media24"] = len(vals)
        p["horas_obs_media24"] = nobs
        p["classe24"] = C.classe_de(p["media24"])
    info = {"ifb_agora": round(ifb0, 2), "ifb_aneis": [round(x, 2) for x in aneis0], "setor_agora": setor0,
            "municipios_agora": {mu: round(v / ifb0, 3) for mu, v in sorted(mun0.items(), key=lambda x: -x[1])} if ifb0 > 0 else {},
            "k_usado": round(k, 2), "k_congelado_por_chuva": bool(lav.get("recente")),
            "lacuna_chuva_ug": round(lacuna, 1),
            "tendencia_h": round(tend, 2), "fator_diurno_agora": round(d0, 2)}
    return prev, info


# ================================================================ validação
def validar(log, historico, agora):
    serie = {h["t"]: h["mediana"] for h in historico["horas"]}
    np_horas = {r["t"] for r in historico.get("chuva", []) if r.get("nao_prevista")}
    for e in log["previsoes"]:
        if e.get("obs") is None and e["alvo"] in serie:
            e["obs"] = serie[e["alvo"]]
            e["chuva_np"] = any(e["emitida"] < t <= e["alvo"] for t in np_horas)
    corte = iso(agora - timedelta(days=C.VALIDACAO_DIAS))
    log["previsoes"] = [e for e in log["previsoes"] if e["alvo"] >= corte]
    resumo = []
    for h in C.DESTAQUES_H:
        es = [e for e in log["previsoes"] if e["h"] == h and e.get("obs") is not None]
        if not es:
            resumo.append({"h": h, "n": 0}); continue
        mae = sum(abs(e["prev"] - e["obs"]) for e in es) / len(es)
        mae_p = sum(abs(e["p0"] - e["obs"]) for e in es) / len(es)
        resumo.append({
            "h": h, "n": len(es), "mae": round(mae, 1), "vies": round(sum(e["prev"] - e["obs"] for e in es) / len(es), 1),
            "mae_persistencia": round(mae_p, 1),
            "ganho_sobre_persistencia": round(1 - mae / mae_p, 2) if mae_p > 0 else None,
            "acerto_classe": round(sum(C.classe_de(e["prev"]) == C.classe_de(e["obs"]) for e in es) / len(es), 2),
        })
        cnp = [e for e in es if e.get("chuva_np")]
        if cnp:
            resumo[-1].update({"n_chuva_np": len(cnp),
                               "mae_chuva_np": round(sum(abs(e["prev"] - e["obs"]) for e in cnp) / len(cnp), 1),
                               "vies_chuva_np": round(sum(e["prev"] - e["obs"] for e in cnp) / len(cnp), 1)})
    return resumo


# ================================================================ dados de teste
def sinteticos(agora):
    rnd = random.Random(int(agora.timestamp() // 3600))
    pontos = [("MIT_NAMA_UFAM", C.NAMA_LAT_PADRAO, C.NAMA_LON_PADRAO), ("Centro", -3.130, -60.023),
              ("Adrianópolis", -3.102, -60.010), ("Cidade Nova", -3.035, -59.990), ("Distrito Industrial", -3.125, -59.950),
              ("Ponta Negra", -3.075, -60.095), ("Compensa", -3.105, -60.055), ("Japiim", -3.120, -59.990),
              ("Tarumã", -3.010, -60.050), ("Zona Leste", -3.060, -59.930), ("Educandos", -3.140, -60.010),
              ("Flores", -3.065, -60.020)]
    sens, anterior = [], {}
    # pancada não prevista na última hora sobre quatro bairros do sul e do centro
    molhados = {"Japiim", "Educandos", "Centro", "Distrito Industrial"}
    for i, (n, la, lo) in enumerate(pontos):
        base = 34 + 10 * (la + 3.08) * -10 + rnd.gauss(0, 4)   # mais fumaça ao sul
        ur0, t0 = round(72 + rnd.gauss(0, 4)), round(31 + rnd.gauss(0, 1), 1)
        pm_antes = round(correcao_epa(base / 0.6 * 1.04, ur0 - 2), 1)
        anterior[str(90000 + i)] = [pm_antes, ur0 - 2, round(t0 + 0.6, 1)]
        if n in molhados:
            base *= 0.5; ur0 += 16; t0 -= 3.2
        cf = base / 0.6
        a, b = cf * (1 + rnd.gauss(0, .03)), cf * (1 + rnd.gauss(0, .03))
        if i == 9:
            b = a * 2.6  # um sensor com canal defeituoso, para mostrar o controle de qualidade
        sens.append(processar_sensor({"id": 90000 + i, "nome": n, "lat": la, "lon": lo, "a": round(a, 1), "b": round(b, 1),
                                      "ur": ur0, "t": round(t0, 1), "visto": iso(agora)}))
    meteo = []
    for k in range(-31 * 24, 72):
        t = hora_cheia(agora) + timedelta(hours=k)
        hl = t.astimezone(TZ).hour
        chuva = 0.0
        if k < -20 * 24 and rnd.random() < 0.05:
            chuva = round(rnd.uniform(1, 12), 1)
        if 15 <= k <= 18:
            chuva = [0.6, 3.2, 5.0, 1.1][k - 15]
        meteo.append({"t": iso(t), "temp": round(26 + 7 * math.sin(math.pi * (hl - 7) / 14) if 7 <= hl <= 21 else 26 - 0.3 * ((hl - 21) % 24), 1),
                      "ur": round(min(98, 85 - 30 * max(0, math.sin(math.pi * (hl - 7) / 14)))),
                      "chuva": chuva, "prob": 70 if 13 <= k <= 19 else 10,
                      "vento": round(2.2 + 1.2 * math.sin(k / 5), 1), "dir": (170 + 20 * math.sin(k / 7)) % 360, "blh": None,
                      "v925": round(4.0 + 1.5 * math.sin(k / 6), 1), "d925": (95 + 70 * math.tanh((k - 6) / 8)) % 360})
    return sens, meteo, anterior


def sint_metar(h0):
    """Boletins sintéticos: como na noite de 9/10/2026, os aeroportos não registram a pancada dos bairros."""
    return [
        {"estacao": "SBEG", **C.METAR_ESTACOES["SBEG"], "hora": iso(h0), "classe": "vizinhanca", "mm": 0.0,
         "texto": "pancada nas proximidades", "bruto": "METAR SBEG ...Z 19003KT 8000 VCSH FEW035TCU SCT100 31/22", "fumaca": False, "visibilidade": "8000"},
        {"estacao": "SBMN", **C.METAR_ESTACOES["SBMN"], "hora": iso(h0), "classe": None, "mm": 0.0,
         "texto": "sem chuva", "bruto": "METAR SBMN ...Z 34009KT 5000 FU FEW030 SCT100 32/21", "fumaca": True, "visibilidade": "5000"},
    ]


# ================================================================ principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", action="store_true")
    ap.add_argument("--semear", action="store_true")
    ap.add_argument("--agora")
    ap.add_argument("--focos-local", help="pasta com focos.geojson, resumo.json e limites.geojson")
    ap.add_argument("--forcar", action="store_true", help="coleta mesmo que esta hora já tenha sido coletada")
    a = ap.parse_args()

    status = {}
    teste = a.teste
    focos_dir = a.focos_local or (os.path.join(os.path.dirname(__file__), "amostra") if teste else None)

    # focos primeiro: no teste, o "agora" é o da amostra do MonitorBETA
    try:
        if focos_dir:
            ler = lambda n: json.load(open(os.path.join(focos_dir, n), encoding="utf-8"))
            focos_gj, mb_resumo, limites = ler("focos.geojson"), ler("resumo.json"), ler("limites.geojson")
        else:
            focos_gj, mb_resumo, limites = baixar_monitorbeta()
        status["MonitorBETA"] = "ok"
    except Exception as e:
        focos_gj, mb_resumo, limites = {"features": []}, {}, None
        status["MonitorBETA"] = f"erro: {e}"

    if a.agora:
        agora = parse_iso(a.agora)
    elif teste and mb_resumo.get("gerado_em"):
        agora = parse_iso(mb_resumo["gerado_em"])
    else:
        agora = datetime.now(UTC)
    h0 = hora_cheia(agora)

    # Trava: a coleta pode ser disparada por mais de um agendador (GitHub e Google).
    # Se esta hora já foi coletada com sucesso, não gasta pontos da PurpleAir de novo.
    if not teste and not a.forcar and not a.semear:
        ult = ler_json("qualiar.json", {})
        if ult.get("hora_base") == iso(h0) and str(ult.get("fontes_status", {}).get("PurpleAir", "")).startswith("ok"):
            print(f"Hora {iso(h0)} já coletada em {ult.get('gerado_em')}; nada a fazer (use --forcar para repetir).")
            return

    historico = ler_json("historico.json", {"horas": []}) if not teste else {"horas": []}
    log = ler_json("validacao_log.json", {"previsoes": []}) if not teste else {"previsoes": []}

    # PM2,5
    sensores, meteo = [], []
    if teste:
        sensores, meteo, anterior_sint = sinteticos(agora)
        status["PurpleAir"] = "dados sintéticos (teste)"
        status["Open-Meteo"] = "dados sintéticos (teste)"
    else:
        chave = os.environ.get("PURPLEAIR_API_KEY", "").strip()
        if not chave:
            status["PurpleAir"] = "sem chave: cadastre o segredo PURPLEAIR_API_KEY"
        else:
            try:
                sensores = coletar_purpleair(chave, agora)
                status["PurpleAir"] = f"ok ({len(sensores)} sensores)"
                if a.semear:
                    semear_historico_pa(chave, sensores, agora, historico)
            except Exception as e:
                status["PurpleAir"] = f"erro: {e}"

    nama_s, nama_origem = achar_nama(sensores, historico.setdefault("estado", {}))
    nama = {"nome": nama_s["nome"] if nama_s else C.NAMA_NOME, "id": nama_s["id"] if nama_s else None,
            "lat": nama_s["lat"] if nama_s else C.NAMA_LAT_PADRAO, "lon": nama_s["lon"] if nama_s else C.NAMA_LON_PADRAO,
            "pm": nama_s["pm"] if nama_s else None, "classe": nama_s["classe"] if nama_s else None, "origem": nama_origem}
    for s in sensores:
        s["nama"] = bool(nama_s and not nama_s.get("_offline") and s["id"] == nama_s["id"])
        s["dist_nama_km"] = round(dist_km(nama["lat"], nama["lon"], s["lat"], s["lon"]), 1)

    if not teste:
        try:
            meteo = coletar_meteo(nama["lat"], nama["lon"])
            status["Open-Meteo"] = "ok"
        except Exception as e:
            status["Open-Meteo"] = f"erro: {e}"

    validos = [s for s in sensores if s["valido"]]
    p0 = round(median([s["pm"] for s in validos]), 1) if len(validos) >= C.SENSORES_MIN else None
    if teste and p0 is not None:  # hora anterior (antes da pancada) com leituras por sensor
        registrar_hora(historico, iso(h0 - timedelta(hours=1)),
                       {k: v[0] for k, v in anterior_sint.items() if k != "90009"},
                       {k: v for k, v in anterior_sint.items() if k != "90009"})
    if p0 is not None:
        registrar_hora(historico, iso(h0), {str(s["id"]): s["pm"] for s in validos},
                       {str(s["id"]): [s["pm"], s.get("ur"), s.get("t")] for s in validos})
    if teste and p0 is not None:  # histórico sintético para tendência e média de 24 h
        rnd = random.Random(7)
        p1 = next(h["mediana"] for h in historico["horas"] if h["t"] == iso(h0 - timedelta(hours=1)))
        for k in range(2, 30):
            v = max(5, p1 - 1.8 * (k - 1) + 10 * math.sin(k / 4) + rnd.gauss(0, 2))
            historico["horas"].append({"t": iso(h0 - timedelta(hours=k)), "mediana": round(v, 1), "n": 11, "sensores": {}})
        historico["horas"].sort(key=lambda h: h["t"])
        # estado seco antes da pancada e uma previsão emitida 3 h antes para esta hora
        historico["estado"] = {"k_seco": 4.4, "anomalia_seca": round(p1 - C.PM_BASE, 1), "t_seco": iso(h0 - timedelta(hours=1))}
        log["previsoes"].append({"emitida": iso(h0 - timedelta(hours=3)), "alvo": iso(h0), "h": 3,
                                 "prev": round(p1 * 1.08, 1), "p0": round(p1 * 0.95, 1), "chuva_prev_mm": 0.0})

    # meteorologia: agora e próximas 24 h
    met = {l["t"]: l for l in meteo}
    m_agora = met.get(iso(h0))
    met_prev = [met[iso(h0 + timedelta(hours=h))] for h in range(0, 25) if iso(h0 + timedelta(hours=h)) in met]
    chuva = resumo_chuva(meteo, agora) if meteo else {}

    # chuva observada
    metar, inmet = [], {}
    if teste:
        metar = sint_metar(h0)
        status["METAR"] = "dados sintéticos (teste)"
    else:
        try:
            metar = R.coletar_metar(http_json, iso, h0)
            status["METAR"] = f"ok ({len(metar)} aeroportos)"
        except Exception as e:
            status["METAR"] = f"erro: {e}"
        tok = os.environ.get("INMET_TOKEN", "").strip()
        if tok:
            try:
                inmet = R.coletar_inmet(http_json, tok, h0)
                status["INMET"] = "ok"
            except Exception as e:
                status["INMET"] = f"erro: {e}"
    ant_item = next((h for h in historico["horas"] if h["t"] == iso(h0 - timedelta(hours=1))), None)
    sinais = R.assinatura_sensores(sensores, (ant_item or {}).get("met", {}), m_agora,
                                   met.get(iso(h0 - timedelta(hours=1))))
    ant_chuva = next((r for r in historico.get("chuva", []) if r["t"] == iso(h0 - timedelta(hours=1))), None)
    prevista_mm = (ant_chuva or {}).get("prox_prevista", {}).get(iso(h0))
    if prevista_mm is None and m_agora:
        prevista_mm = m_agora.get("chuva") or 0.0
    prox = {iso(h0 + timedelta(hours=h)): (met.get(iso(h0 + timedelta(hours=h))) or {}).get("chuva") or 0.0 for h in (1, 2, 3)}
    reg_chuva = R.registrar(historico, h0, iso, sensores, sinais, metar,
                            inmet.get(h0) if inmet else None, prevista_mm, prox)
    for s in sensores:
        s["sinal_chuva"] = sinais.get(str(s["id"]))
    lavagem = R.estado_lavagem(historico, h0, iso, parse_iso)
    chuva_obs = R.serie_observada(historico, parse_iso)
    for t, mm in (inmet or {}).items():
        chuva_obs[t] = max(chuva_obs.get(t, 0.0), mm)
    if chuva:
        chuva = R.corrigir_dias_sem_chuva(chuva, historico, h0, TZ, parse_iso)

    # focos
    focos = preparar_focos(focos_gj, nama, agora)
    munis = resumo_municipios(focos)

    # previsão
    previsao, info = ([], {})
    if p0 is not None:
        previsao, info = prever(agora, p0, historico, meteo, focos, lavagem, chuva_obs)
        for p in previsao:
            if p["h"] in C.DESTAQUES_H:
                log["previsoes"].append({"emitida": iso(h0), "alvo": p["t"], "h": p["h"], "prev": p["pm"], "p0": p0,
                                         "chuva_prev_mm": p["chuva_acum_mm"]})
    # efeito da chuva não prevista: o que se previa para agora antes da chuva x o observado
    efeito = None
    if lavagem["nao_prevista_recente"] and p0 is not None:
        inicio = min((r["t"] for r in historico.get("chuva", [])
                      if r["evento"] and parse_iso(r["t"]) > h0 - timedelta(hours=C.LAVAGEM_JANELA_H)), default=iso(h0))
        antes = [e for e in log["previsoes"] if e["alvo"] == iso(h0) and e["emitida"] < inicio]
        if antes:
            e = max(antes, key=lambda x: x["emitida"])
            efeito = {"emitida": e["emitida"], "previsto": e["prev"], "observado": p0, "dif": round(p0 - e["prev"], 1)}
    validacao = validar(log, historico, agora)

    # tendência e média 24 h observadas
    serie = [h for h in historico["horas"] if parse_iso(h["t"]) <= h0]
    ult24 = [h for h in serie if parse_iso(h["t"]) > h0 - timedelta(hours=24)]
    media24 = round(sum(h["mediana"] for h in ult24) / len(ult24), 1) if ult24 else None
    tend = info.get("tendencia_h", 0.0)
    tend_txt = "estável" if abs(tend) < 1 else ("subindo" if tend > 0 else "caindo")

    saida = {
        "gerado_em": iso(agora), "hora_base": iso(h0), "dados_de_teste": teste, "fontes_status": status,
        "classes": [{k: (None if v == math.inf else v) for k, v in c.items()} for c in C.CLASSES],
        "nama": nama,
        "sensores": [{k: s.get(k) for k in ("id", "nome", "lat", "lon", "pm", "pm_bruto", "a", "b", "ur", "t", "classe",
                                            "valido", "motivo", "visto", "nama", "dist_nama_km", "sinal_chuva")} for s in sensores],
        "atual": {"mediana": p0, "classe": C.classe_de(p0), "n_sensores": len(validos), "n_total": len(sensores),
                  "tendencia_h": tend, "tendencia": tend_txt,
                  "media24": media24, "classe24": C.classe_de(media24), "horas_media24": len(ult24)},
        "historico": [{"t": h["t"], "mediana": h["mediana"], "n": h["n"]} for h in serie[-48:]],
        "meteo": {"agora": m_agora, "previsao": met_prev, **chuva,
                  "fonte": "Open-Meteo (modelos globais), no ponto da estação NAMA"},
        "chuva_obs": {"agora": {k: v for k, v in reg_chuva.items() if k != "prox_prevista"},
                      "lavagem": lavagem, "efeito": efeito,
                      "metar": metar, "inmet_ativo": bool(inmet),
                      "registro": [{k: r[k] for k in ("t", "mm_eq", "frac", "evento", "n_sinais", "prevista_mm", "nao_prevista")}
                                   for r in historico.get("chuva", []) if parse_iso(r["t"]) > h0 - timedelta(hours=24)],
                      "criterios": {"dT": C.SINAL_DT_C, "dUR": C.SINAL_DUR_PTS, "dPM": C.SINAL_DPM,
                                    "janela_h": C.LAVAGEM_JANELA_H, "tau_recuperacao_h": C.TAU_RECUPERACAO_H}},
        "focos": {"municipios": munis,
                  "totais": {k: sum(m[k] for m in munis) for k in ("ativos", "recem_extintos", "provaveis_incendios")},
                  "monitorbeta_gerado_em": mb_resumo.get("gerado_em"),
                  "criterios": {"recem_extinto_h": C.RECEM_EXTINTO_H, "incendio_duracao_h": C.INCENDIO_DURACAO_H,
                                "incendio_pixels": C.INCENDIO_PIXELS, "incendio_frp_mw": C.INCENDIO_FRP_MW},
                  "aneis_km": C.IFB_ANEIS_KM},
        "modelo": {"versao": "v0.3 heurística (persistência + fogo a barlavento + chuva prevista e observada + camada limite)", **info,
                   "tem_925": any(l.get("v925") is not None for l in meteo),
                   "parametros": {"pm_base": C.PM_BASE, "tau_persist_h": C.TAU_PERSIST_H, "k_fogo_inicial": C.K_FOGO,
                                  "ifb_L_km": C.IFB_L_KM, "peso_925": C.VT_PESO_925, "sigma_ang": [C.SIGMA_ANG_MIN, C.SIGMA_ANG_MAX],
                                  "calmaria_ms": C.IFB_CALMARIA_MS, "L_calma_km": C.IFB_L_CALMA_KM,
                                  "lambda_chuva": C.LAMBDA_CHUVA, "lambda_rota": C.LAMBDA_ROTA}},
        "previsao": previsao,
        "destaques": [p for p in previsao if p["h"] in C.DESTAQUES_H],
        "validacao": validacao,
    }
    gravar_json("qualiar.json", saida)
    pontos = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [f["lon"], f["lat"]]},
         "properties": {**{k: v for k, v in f.items() if k not in ("lat", "lon", "_contrib")},
                        "influencia": {str(int((parse_iso(t) - h0).total_seconds() // 3600)): round(c, 3)
                                       for t, c in f.get("_contrib", {}).items()}}}
        for f in focos if f["categoria"] != "extinto" or f.get("_contrib")]}
    gravar_json("focos_pontos.geojson", pontos)
    if limites:
        gravar_json("limites.geojson", limites)
    if not teste:
        gravar_json("historico.json", historico)
        gravar_json("validacao_log.json", log)
    print(json.dumps({"status": status, "mediana": p0, "nama": nama["origem"],
                      "destaques": [(p["h"], p["pm"], p["classe"]) for p in saida["destaques"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
