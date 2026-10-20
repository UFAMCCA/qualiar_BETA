"""Camada limite corrigida e mistura da fumaça distante até o chão (variante F24L).

Base:
  Dias-Júnior et al. (2022), Remote Sensing 14, 4561 — correção da altura da camada
    limite do reanálise na Amazônia Central (eq. 2) e camada noturna de ~250 m.
  Souza et al. (2023), Ciência e Natura 45, e80266 — ciclo médio da camada na ATTO.

A fumaça distante (trajetórias a 925 e 850 hPa) entra no chão diluída pela camada de
mistura corrigida: concentrada na camada rasa da madrugada, diluída à tarde. A camada
corrigida também define a ventilação (quanto tempo a fumaça leva para sair da cidade).
"""
from __future__ import annotations

import math
from datetime import timedelta, timezone

import config as C

UTC = timezone.utc
G = 9.81


def _iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")


# ---------------------------------------------------------------- altura da camada
def maximo_do_dia(met, t):
    """Maior altura do modelo entre 12 e 17 UTC do mesmo dia UTC de t (ziM da eq. 2)."""
    d0 = t.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    vals = [(met.get(_iso(d0 + timedelta(hours=h))) or {}).get("blh") for h in range(12, 18)]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else max(C.CAMADA_CLIMA_UTC.values())


def camada_corrigida(met, t, alfa):
    """Altura da camada de mistura (m) na hora t pela eq. 2 de Dias-Júnior et al. (2022):
    12-17 UTC (08h-13h em Manaus): (1 + alfa) x modelo;
    18-23 UTC (14h-19h): (1 + alfa) x máximo do dia x sen[pi (t - 12) / 12];
    00-11 UTC (20h-07h): camada noturna fixa (150 m)."""
    hu = t.astimezone(UTC).hour
    if hu < 12:
        return C.CAMADA_NOITE_M
    if hu <= 17:
        b = (met.get(_iso(t)) or {}).get("blh")
        if b is None:
            b = C.CAMADA_CLIMA_UTC.get(hu, 1000.0)
        return max(C.CAMADA_NOITE_M, (1 + alfa) * b)
    zim = maximo_do_dia(met, t)
    return max(C.CAMADA_NOITE_M, (1 + alfa) * zim * math.sin(math.pi * (hu - 12) / 12.0))


def diluicao(zc):
    """Fator de concentração da fumaça distante no chão pela altura da camada."""
    return (C.DILUICAO_REF_M / max(zc, 50.0)) ** C.DILUICAO_EXPOENTE


# ---------------------------------------------------------------- estabilidade noturna
def _theta(temp_c, p_hpa):
    return (temp_c + 273.15) * (1000.0 / p_hpa) ** 0.2857


def _uv(vel, dire):
    if vel is None or dire is None:
        return None
    r = math.radians(dire)
    return -vel * math.sin(r), -vel * math.cos(r)


def dtheta(l):
    """Diferença de temperatura potencial entre ~500 m (950 hPa) e 2 m, em K (>0 = estável).
    Sem 950 hPa, usa 925 hPa."""
    if not l or l.get("temp") is None:
        return None, None
    for nv, p, z in (("t950", 950.0, 500.0), ("t925", 925.0, 800.0)):
        if l.get(nv) is not None:
            return _theta(l[nv], p) - _theta(l["temp"], C.P_SUPERFICIE_HPA), z
    return None, None


def richardson(l):
    """Número de Richardson global entre 10 m e 950 hPa (ou 925 hPa)."""
    dt, z = dtheta(l)
    if dt is None:
        return None
    alto = _uv(l.get("v950"), l.get("d950")) if z == 500.0 else _uv(l.get("v925"), l.get("d925"))
    baixo = _uv(l.get("vento"), l.get("dir"))
    if alto is None or baixo is None:
        return None
    du2 = max(0.25, (alto[0] - baixo[0]) ** 2 + (alto[1] - baixo[1]) ** 2)
    return G * dt * (z - 10.0) / (300.0 * du2)


def fator_noite(met, t):
    """Fator de madrugada (>= 1): peso da hora x vento médio a ~800 m nas 8 h anteriores.
    Com a camada noturna fixa (150 m) toda noite é estável; o que varia é o vento que traz
    a fumaça por cima dela."""
    w = C.NOITE_HORAS.get(t.astimezone(timezone(timedelta(hours=-4))).hour, 0.0)
    if w == 0:
        return 1.0
    v925 = [l["v925"] for k in range(1, 9) for l in [met.get(_iso(t - timedelta(hours=k)))] if l and l.get("v925") is not None]
    if len(v925) < 4:
        return 1.0
    vm = sum(v925) / len(v925)
    f_jato = min(1.0, max(0.0, (vm - C.NOITE_V925_MIN) / (C.NOITE_V925_PLENO - C.NOITE_V925_MIN)))
    return 1.0 + C.NOITE_A * w * f_jato


# ---------------------------------------------------------------- fumaça distante no chão
def ifr_duas_alturas(ifr925, ifr850):
    if ifr925 is None:
        return None
    return ifr925 if ifr850 is None else C.PESO_NIVEL_925 * ifr925 + (1 - C.PESO_NIVEL_925) * ifr850


def termo_distante(ifr_u, noite, zc):
    """Índice de fumaça distante no chão: IFR (duas alturas) x madrugada x diluição."""
    return (ifr_u or 0.0) * noite * diluicao(zc)


def ventilacao(l, zc):
    """Coeficiente de ventilação (m²/s) com a camada corrigida: vento médio vetorial das
    alturas que estão dentro da camada (10 m sempre)."""
    if not l:
        return None
    vs = [_uv(l.get("vento"), l.get("dir"))]
    for nv, z in C.NIVEIS_ALTURA_M.items():
        if zc >= z:
            vs.append(_uv(l.get(f"v{nv}"), l.get(f"d{nv}")))
    vs = [v for v in vs if v]
    if not vs:
        return None
    u, v = sum(x[0] for x in vs) / len(vs), sum(x[1] for x in vs) / len(vs)
    return zc * max(0.3, math.hypot(u, v))


def fator_ventilacao(l, zc):
    vc = ventilacao(l, zc)
    if vc is None:
        return 1.0
    return min(C.VENT_FATOR_MAX, max(C.VENT_FATOR_MIN, (C.VENT_REF_M2S / max(vc, 100.0)) ** C.VENT_EXPOENTE))


# ---------------------------------------------------------------- calibração de alfa e K
def calibrar(hist, met, serie, h0, pm_base, alfa_ant):
    """Escolhe alfa (e o K correspondente) que melhor explica a anomalia de PM2,5 das últimas
    72 h pela fumaça distante diluída na camada corrigida. Retorna
    (alfa, k, n_horas, alfa_melhor_da_rodada)."""
    linhas = []
    for r in hist:
        t = _parse(r["t"])
        if not (h0 - timedelta(hours=72) < t <= h0):
            continue
        obs = serie.get(r["t"])
        iu = ifr_duas_alturas(r.get("ifr"), r.get("ifr850"))
        if obs is None or iu is None or iu < C.IFR_MIN:
            continue
        linhas.append((t, max(0.0, obs - pm_base), iu * fator_noite(met, t)))
    if len(linhas) < C.K_REG_MIN_HORAS:
        return alfa_ant, C.K_REG_INICIAL, len(linhas), None

    def ajuste(alfa):
        pares = [(a, x * diluicao(camada_corrigida(met, t, alfa))) for t, a, x in linhas]
        sxx = sum(x * x for _, x in pares)
        if sxx <= 0:
            return None
        k = min(C.K_REG_MAX, max(C.K_REG_MIN, sum(a * x for a, x in pares) / sxx))
        return sum((a - k * x) ** 2 for a, x in pares), k

    n_passos = int(round((C.CAMADA_ALFA_MAX - C.CAMADA_ALFA_MIN) / C.CAMADA_ALFA_PASSO))
    melhor = None
    for i in range(n_passos + 1):
        alfa = round(C.CAMADA_ALFA_MIN + i * C.CAMADA_ALFA_PASSO, 3)
        r_ = ajuste(alfa)
        if r_ is None:
            continue
        sse = r_[0] * (1 + C.CAMADA_ALFA_PENALIDADE * alfa * alfa)
        if melhor is None or sse < melhor[0]:
            melhor = (sse, alfa)
    if melhor is None:
        return alfa_ant, C.K_REG_INICIAL, len(linhas), None
    alfa = (1 - C.CAMADA_ALFA_SUAVE) * alfa_ant + C.CAMADA_ALFA_SUAVE * melhor[1]
    alfa = round(min(C.CAMADA_ALFA_MAX, max(C.CAMADA_ALFA_MIN, alfa)), 3)
    k = ajuste(alfa)[1]
    if len(linhas) < 2 * C.K_REG_MIN_HORAS:     # poucas horas: puxa K para o valor inicial
        frac = len(linhas) / (2 * C.K_REG_MIN_HORAS)
        k = math.exp((1 - frac) * math.log(C.K_REG_INICIAL) + frac * math.log(k))
    return alfa, k, len(linhas), melhor[1]


def _parse(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
