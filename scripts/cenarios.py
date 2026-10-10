"""Mostra como o índice de fogo a barlavento redistribui o peso dos municípios
conforme o vento. Usa os focos reais de uma rodada do MonitorBETA e vento
constante em cada cenário.

  python scripts/cenarios.py                   # focos de scripts/amostra
  python scripts/cenarios.py --focos-local pasta --vel 3
"""
import argparse
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
import config as C  # noqa: E402
import qualiar as Q  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--focos-local", default=os.path.join(os.path.dirname(__file__), "amostra"))
ap.add_argument("--vel", type=float, default=3.0, help="velocidade do vento de transporte (m/s)")
ap.add_argument("--json", action="store_true")
a = ap.parse_args()

gj = json.load(open(os.path.join(a.focos_local, "focos.geojson"), encoding="utf-8"))
res = json.load(open(os.path.join(a.focos_local, "resumo.json"), encoding="utf-8"))
agora = Q.parse_iso(res["gerado_em"])
h0 = Q.hora_cheia(agora)
nama = {"lat": C.NAMA_LAT_PADRAO, "lon": C.NAMA_LON_PADRAO}
focos = Q.preparar_focos(gj, nama, agora)

CENARIOS = [("de N", 0, a.vel), ("de NE", 45, a.vel), ("de L (alísio típico)", 90, a.vel),
            ("de SE", 135, a.vel), ("de S", 180, a.vel), ("calmaria", 90, 0.4)]


def meteo_constante(direcao, vel):
    return [{"t": Q.iso(h0 + timedelta(hours=k)), "vento": vel, "dir": direcao, "chuva": 0.0}
            for k in range(-60, 30)]


saida = []
for nome, direcao, vel in CENARIOS:
    v = Q.Ventos(meteo_constante(direcao, vel))
    linha = {"cenario": nome}
    for h in (0, 12):
        tot, aneis, mun, setor = Q.ifb(focos, v, h0 + timedelta(hours=h), agora)
        linha[f"ifb_{h}"] = round(tot, 2)
        linha[f"mun_{h}"] = {m: round(x / tot, 3) for m, x in sorted(mun.items(), key=lambda t: -t[1])} if tot else {}
    saida.append(linha)

if a.json:
    print(json.dumps(saida, ensure_ascii=False, indent=1))
else:
    munis = sorted({f["municipio"] for f in focos if f["categoria"] != "extinto"})
    ativos = {m: sum(1 for f in focos if f["municipio"] == m and f["categoria"] == "ativo") for m in munis}
    dist = {m: min((f["dist_km"] for f in focos if f["municipio"] == m), default=None) for m in munis}
    rumo = {}
    for m in munis:
        fs = [f for f in focos if f["municipio"] == m]
        sx = sum(Q.math.sin(Q.math.radians(f["rumo"])) for f in fs)
        cy = sum(Q.math.cos(Q.math.radians(f["rumo"])) for f in fs)
        rumo[m] = Q.ponto_cardeal((Q.math.degrees(Q.math.atan2(sx, cy)) + 360) % 360) if fs else "—"
    print(f"Vento de transporte {a.vel} m/s · focos de {res['gerado_em']} · peso de cada município no IFB de agora")
    print(f"{'município':24}{'ativos':>7}{'dist':>7}{'rumo':>6}  " + "".join(f"{l['cenario'][:12]:>14}" for l in saida))
    for m in sorted(munis, key=lambda m: -ativos[m]):
        print(f"{m:24}{ativos[m]:>7}{dist[m]:>7.0f}{rumo[m]:>6}  " + "".join(f"{100 * l['mun_0'].get(m, 0):>13.0f}%" for l in saida))
    print(f"{'IFB total agora':45}" + "".join(f"{l['ifb_0']:>14.2f}" for l in saida))
    print(f"{'IFB total +12 h':45}" + "".join(f"{l['ifb_12']:>14.2f}" for l in saida))
