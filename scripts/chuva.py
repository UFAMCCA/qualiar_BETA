"""Chuva observada para o QUALIAR-UFAM.

Junta três fontes de chuva que de fato caiu em Manaus e registra, hora a hora,
se ela tinha sido prevista:
  - METAR dos aeroportos SBEG e SBMN (tempo presente: RA, SHRA, TSRA, VCSH, RE..)
  - assinatura de chuva em cada sensor PurpleAir (queda de temperatura e alta de
    umidade além do ciclo diário esperado, com queda do PM2,5 como apoio)
  - pluviômetro do INMET, se houver token

As funções recebem `http_json`, `iso` e `parse_iso` de qualiar.py para que os
testes possam substituir a rede.
"""
from __future__ import annotations

import math
import re
from datetime import timedelta

import config as C

# ---------------------------------------------------------------- METAR
_RE_TEMPO = re.compile(r"^(?P<int>[-+]|VC)?(?P<desc>SH|TS)?(?P<prec>(?:RA|DZ|GR|GS)+)?$")


def interpretar_metar(wx: str | None, raw: str | None):
    """Classifica o tempo presente de um METAR. Retorna (classe, mm, texto)."""
    tokens = (wx or "").split()
    recente = any(t.startswith("RE") and ("RA" in t or "SH" in t or "TS" in t) for t in (raw or "").split())
    classe, mm, desc = None, 0.0, []
    for tk in tokens:
        if tk in ("VCSH", "VCTS"):
            desc.append("pancada nas proximidades" if tk == "VCSH" else "trovoada nas proximidades")
            classe = classe or "vizinhanca"
            continue
        m = _RE_TEMPO.match(tk)
        if not m or not m.group("prec"):
            if tk.endswith("TS") or tk == "TS":
                desc.append("trovoada"); classe = classe or "vizinhanca"
            continue
        prec = m.group("prec")
        if prec.startswith("DZ"):
            nivel = "chuvisco"
        else:
            nivel = {"-": "leve", "+": "forte"}.get(m.group("int"), "moderada")
        if C.METAR_MM[nivel] > mm:
            mm, classe = C.METAR_MM[nivel], nivel
        desc.append({"leve": "chuva fraca", "moderada": "chuva moderada", "forte": "chuva forte",
                     "chuvisco": "chuvisco"}[nivel] + (" (pancada)" if m.group("desc") == "SH" else "")
                    + (" com trovoada" if m.group("desc") == "TS" else ""))
    if recente and mm == 0:
        classe, mm = "recente", C.METAR_MM["recente"]
        desc.append("choveu desde o último boletim")
    if raw and "TCU" in raw and not desc:
        desc.append("nuvens convectivas (TCU)")
    if raw and " CB" in raw and not desc:
        desc.append("cumulonimbus (CB)")
    return classe, mm, "; ".join(desc) or "sem chuva"


def coletar_metar(http_json, iso, h0):
    ids = ",".join(C.METAR_ESTACOES)
    dados = http_json(C.METAR_URL.format(ids=ids), tentativas=2)
    por_est = {}
    for r in dados:
        est = r.get("icaoId")
        if est not in C.METAR_ESTACOES or r.get("obsTime") is None:
            continue
        if est in por_est and por_est[est]["_ts"] >= r["obsTime"]:
            continue
        classe, mm, texto = interpretar_metar(r.get("wxString"), r.get("rawOb"))
        por_est[est] = {"_ts": r["obsTime"], "estacao": est, **C.METAR_ESTACOES[est], "classe": classe, "mm": mm,
                        "texto": texto, "bruto": r.get("rawOb"), "fumaca": "FU" in (r.get("wxString") or "").split(),
                        "visibilidade": r.get("visib")}
    from datetime import datetime, timezone
    out = []
    for v in por_est.values():
        v["hora"] = iso(datetime.fromtimestamp(v.pop("_ts"), timezone.utc))
        out.append(v)
    return out


# ---------------------------------------------------------------- INMET (opcional)
def coletar_inmet(http_json, token, h0):
    """Chuva horária (mm) da estação automática do INMET. Formato não testado
    neste ambiente: o leitor aceita as variações de nome conhecidas."""
    dia = h0.strftime("%Y-%m-%d")
    ontem = (h0 - timedelta(days=1)).strftime("%Y-%m-%d")
    dados = http_json(C.INMET_URL.format(ini=ontem, fim=dia, cod=C.INMET_ESTACAO, token=token), tentativas=2)
    out = {}
    from datetime import datetime, timezone
    for r in dados or []:
        d = r.get("DT_MEDICAO") or r.get("dt_medicao")
        h = str(r.get("HR_MEDICAO") or r.get("hr_medicao") or "").zfill(4)
        v = r.get("CHUVA") if "CHUVA" in r else r.get("chuva")
        if not d or v in (None, ""):
            continue
        t = datetime.strptime(f"{d} {h[:2]}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        out[t] = float(v)   # INMET registra em UTC a chuva da hora que termina em t
    return out


# ---------------------------------------------------------------- sensores
def assinatura_sensores(sensores, anterior: dict, meteo_agora, meteo_antes):
    """Sinal de chuva por sensor. `anterior` = {id: [pm, ur, t]} da hora anterior."""
    if not anterior:
        return {}
    dt_mod = (meteo_agora["temp"] - meteo_antes["temp"]) if (meteo_agora and meteo_antes) else 0.0
    dur_mod = (meteo_agora["ur"] - meteo_antes["ur"]) if (meteo_agora and meteo_antes) else 0.0
    sinais = {}
    for s in sensores:
        ant = anterior.get(str(s["id"]))
        if not ant or s.get("t") is None or s.get("ur") is None or ant[1] is None or ant[2] is None:
            continue
        dt = (s["t"] - ant[2]) - dt_mod
        dur = (s["ur"] - ant[1]) - dur_mod
        dpm = None
        if s.get("pm") is not None and ant[0]:
            dpm = (s["pm"] - ant[0]) / max(ant[0], 1.0)
        frio = dt <= C.SINAL_DT_C
        umido = dur >= C.SINAL_DUR_PTS and s["ur"] >= C.SINAL_UR_MIN
        limpou = dpm is not None and dpm <= C.SINAL_DPM
        if frio and umido:
            nivel = "provavel"
        elif (frio or umido) and limpou:
            nivel = "possivel"
        else:
            continue
        sinais[str(s["id"])] = {"nivel": nivel, "dT": round(dt, 1), "dUR": round(dur, 0),
                                "dPM": None if dpm is None else round(100 * dpm)}
    return sinais


# ---------------------------------------------------------------- registro horário
def registrar(historico, h0, iso, sensores, sinais, metar, inmet_mm, prevista_mm, prox_prevista):
    validos = [s for s in sensores if s.get("valido")]
    n = len(validos)
    mm_sens = sum(C.SINAL_MM[v["nivel"]] for k, v in sinais.items()) / n if n else 0.0
    metar_atual = [m for m in metar if m.get("hora") and m["hora"] >= iso(h0 - timedelta(minutes=90))]
    mm_metar = sum(m["mm"] for m in metar_atual) / len(metar_atual) if metar_atual else 0.0
    pontos = n + len(metar_atual)
    com_chuva = len(sinais) + sum(1 for m in metar_atual if m["mm"] > 0)
    frac = com_chuva / pontos if pontos else 0.0
    mm_eq = max(mm_sens, mm_metar, inmet_mm or 0.0)
    evento = frac >= C.CHUVA_EVENTO_FRAC or mm_eq >= C.CHUVA_EVENTO_MM
    reg = {
        "t": iso(h0), "mm_eq": round(mm_eq, 2), "frac": round(frac, 2), "evento": evento,
        "n_sinais": len(sinais), "n_sensores": n, "sinais": sinais,
        "metar": {m["estacao"]: {"classe": m["classe"], "texto": m["texto"]} for m in metar_atual},
        "inmet_mm": inmet_mm, "prevista_mm": None if prevista_mm is None else round(prevista_mm, 2),
        "nao_prevista": bool(evento and (prevista_mm or 0.0) < C.CHUVA_NAO_PREVISTA_MM),
        "prox_prevista": {k: round(v, 2) for k, v in prox_prevista.items()},
    }
    lst = [r for r in historico.setdefault("chuva", []) if r["t"] != reg["t"]] + [reg]
    lst.sort(key=lambda r: r["t"])
    historico["chuva"] = lst[-C.CHUVA_HIST_H:]
    return reg


def serie_observada(historico, parse_iso):
    """{datetime: mm equivalentes observados} para usar como chuva passada."""
    return {parse_iso(r["t"]): r["mm_eq"] for r in historico.get("chuva", []) if r.get("mm_eq")}


def estado_lavagem(historico, h0, iso, parse_iso):
    """Resumo da chuva recente para o modelo."""
    janela = [r for r in historico.get("chuva", [])
              if parse_iso(r["t"]) > h0 - timedelta(hours=C.LAVAGEM_JANELA_H) and r["evento"]]
    ultimo = None
    for r in reversed(historico.get("chuva", [])):
        if r["evento"]:
            ultimo = r; break
    agora = next((r for r in historico.get("chuva", []) if r["t"] == iso(h0)), None)
    return {
        "recente": bool(janela),
        "horas_desde": None if not ultimo else round((h0 - parse_iso(ultimo["t"])).total_seconds() / 3600),
        "ultima": None if not ultimo else ultimo["t"],
        "nao_prevista_recente": any(r["nao_prevista"] for r in janela),
        "mm_agora": agora["mm_eq"] if agora and agora["evento"] else 0.0,
        "frac_max": max((r["frac"] for r in janela), default=0.0),
    }


def corrigir_dias_sem_chuva(resumo_modelo: dict, historico, h0, tz, parse_iso):
    """Um dia com chuva observada (>= 1 mm equivalente somado) interrompe a sequência seca do modelo."""
    por_dia = {}
    for r in historico.get("chuva", []):
        d = parse_iso(r["t"]).astimezone(tz).date()
        por_dia[d] = por_dia.get(d, 0.0) + (r["mm_eq"] or 0.0)
    hoje = h0.astimezone(tz).date()
    dias = resumo_modelo.get("dias_sem_chuva")
    if dias is None:
        return resumo_modelo
    if por_dia.get(hoje, 0.0) >= 1.0:
        return {**resumo_modelo, "dias_sem_chuva": 0, "dias_sem_chuva_fonte": "choveu hoje (observado)"}
    for k in range(1, dias + 1):
        if por_dia.get(hoje - timedelta(days=k), 0.0) >= 1.0:
            resumo_modelo = {**resumo_modelo, "dias_sem_chuva": k - 1,
                             "dias_sem_chuva_fonte": "modelo corrigido por chuva observada"}
            break
    else:
        resumo_modelo = {**resumo_modelo, "dias_sem_chuva_fonte": "modelo (Open-Meteo, horas passadas)"}
    return resumo_modelo
