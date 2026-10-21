#!/usr/bin/env python3
"""Boletim da Comissão de Qualidade do Ar da UFAM: um cartão por cidade, quatro vezes ao dia
(20h30, 02h30, 08h30 e 14h30, hora de Manaus), com a condição medida na última hora cheia e
a previsão para o período seguinte. Publica em docs/boletim/ (GitHub Pages) e, com --enviar,
manda os cartões pelo Telegram. O e-mail sai pelo Google Apps Script (verificarBoletim).

  python scripts/boletim.py                 # gera o boletim do horário atual (se ainda não saiu)
  python scripts/boletim.py --forcar        # gera de novo o do último horário
  python scripts/boletim.py --verificar     # só diz se há boletim a gerar agora (para o workflow)
  python scripts/boletim.py --enviar        # depois de gerado: manda o último boletim pelo Telegram
  python scripts/boletim.py --sem-imagem    # só a página e o texto (sem Playwright)

Os números vêm dos mesmos qualiar.json do site (versão publicada do modelo). O boletim não
traz recomendação de suspensão: ela continua saindo da nota técnica do plantonista.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import config as C  # noqa: E402

TZ = ZoneInfo(C.FUSO)
UTC = timezone.utc
RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
SAIDA = DOCS / "boletim"
SITE = "https://ufamcca.github.io/qualiar_BETA/"
COMISSAO = "Comissão de Qualidade do Ar da UFAM"
FIM_DA_SERIE = "2026-11-30"          # boletins diários até o fim de novembro (ajuste se precisar)
PNG_DIAS = 3                         # imagens antigas apagadas depois disto (o texto fica no arquivo)

# horário de emissão (hora local) -> janela da previsão: (rótulo, dia relativo, hora inicial, hora final)
# a hora final é inclusiva; dia relativo conta a partir da data de emissão
HORARIOS = {
    20: ("AMANHÃ DE MANHÃ · 05h ÀS 10h", 1, 5, 10),
    2: ("ESTA MANHÃ · 05h ÀS 10h", 0, 5, 10),
    8: ("ESTA TARDE · 12h ÀS 18h", 0, 12, 18),
    14: ("ESTA NOITE E MADRUGADA · 19h ÀS 06h", 0, 19, 30),   # 30 = 06h do dia seguinte
}
MINUTO_EMISSAO = 30
TOLERANCIA_H = 2.0                   # até 2 h depois do horário ainda sai (atrasos do GitHub)
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def ler(p, padrao=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return padrao


def classe(cid):
    return next((c for c in C.CLASSES if c["id"] == cid), None)


def classe_de(pm):
    return classe(C.classe_de(pm)) if pm is not None else None


def tinta(c):
    """Cor do texto sobre a cor da classe (contraste)."""
    return "#1d2430" if c and c["id"] in (2, 3) else "#ffffff"


# ---------------------------------------------------------------- horário
def horario_da_vez(agora_local, forcar=False):
    """(hora de emissão, datetime da emissão) do horário cuja janela de envio contém agora;
    com forcar, o último horário já passado."""
    cands = []
    for d in (0, -1):
        dia = (agora_local + timedelta(days=d)).date()
        for h in HORARIOS:
            em = datetime(dia.year, dia.month, dia.day, h, MINUTO_EMISSAO, tzinfo=TZ)
            if em <= agora_local + timedelta(minutes=10):
                cands.append((em, h))
    if not cands:
        return None
    em, h = max(cands)
    if not forcar and (agora_local - em).total_seconds() / 3600 > TOLERANCIA_H:
        return None
    return h, em


def proximo_horario(em):
    for k in range(1, 30):
        t = em + timedelta(hours=k)
        if t.hour in HORARIOS:
            return t
    return None


# ---------------------------------------------------------------- dados de uma cidade
def cartao(reg, dados, h, em):
    rotulo, ddia, hi, hf = HORARIOS[h]
    out = {"id": reg["id"], "nome": reg["nome"], "janela": rotulo}
    if not dados or not dados.get("atual") or dados["atual"].get("mediana") is None:
        out["sem_dados"] = "Sem medição dos sensores nesta hora."
        return out
    hb = parse_iso(dados["hora_base"])
    idade = (em - hb).total_seconds() / 3600
    a = dados["atual"]
    ca = classe(a.get("classe"))
    out.update({
        "hora": hb.astimezone(TZ).strftime("%Hh"), "pm": round(a["mediana"]), "classe": ca["nome"], "cor": ca["cor"],
        "iqar": a.get("iqar"), "tendencia": a.get("tendencia"),
        "media24": None if a.get("media24") is None else round(a["media24"]),
        "classe24": None if a.get("classe24") is None else classe(a["classe24"])["nome"],
        "n_sensores": a.get("n_sensores"), "idade_h": round(idade, 1)})
    if idade > 3:
        out["aviso"] = f"Última medição às {out['hora']} (dados atrasados)."
    base = em.replace(hour=0, minute=0)
    ini = base + timedelta(days=ddia, hours=hi)
    fim = base + timedelta(days=ddia, hours=hf)
    jan = [p for p in dados.get("previsao", []) if ini <= parse_iso(p["t"]).astimezone(TZ) <= fim]
    if not jan:
        out["sem_previsao"] = "Previsão indisponível para este período."
        return out
    vals = [p["pm"] for p in jan]
    pior = max(jan, key=lambda p: p["pm"])
    mediana = sorted(vals)[len(vals) // 2]
    cm, cp = classe_de(mediana), classe_de(pior["pm"])
    chuva = max(0.0, jan[-1].get("chuva_acum_mm", 0) - (jan[0].get("chuva_acum_mm", 0) if len(jan) > 1 else 0))
    lo, hi_ = round(min(vals)), round(max(vals))
    if hi_ > 1.3 * out["pm"] + 5:
        tend = "deve piorar em relação a agora"
    elif hi_ < 0.7 * out["pm"]:
        tend = "deve melhorar em relação a agora"
    else:
        tend = "parecida com a de agora"
    out.update({
        "prev_faixa": f"{lo}" if lo == hi_ else f"{lo}–{hi_}", "prev_classe": cm["nome"], "prev_cor": cm["cor"],
        "prev_tinta": tinta(cm),
        "pior_hora": parse_iso(pior["t"]).astimezone(TZ).strftime("%Hh"), "pior_pm": round(pior["pm"]),
        "pior_classe": cp["nome"], "pior_id": cp["id"],
        "nota": "Chuva prevista no período pode limpar o ar." if chuva >= 1.0 else f"Qualidade do ar {tend}.",
        "orientacao": cp["msg"], "orientacao_classe": cp["nome"]})
    return out


# ---------------------------------------------------------------- HTML
FONTES = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
          '<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&amp;'
          'family=Barlow+Condensed:wght@600;700&amp;display=swap" rel="stylesheet">')


def escala_html():
    barras = "".join(f'<div style="height:18px;border-radius:4px;background:{c["cor"]}"></div>' for c in C.CLASSES)
    nomes = ["Boa ≤ 15", "Moderada 15–50", "Ruim 50–75", "Muito Ruim 75–125", "Péssima > 125"]
    rot = "".join(f"<div>{n}</div>" for n in nomes)
    return (f'<div class="grade5">{barras}</div><div class="grade5 rot">{rot}</div>')


def cartao_html(c, em, logo_src):
    e = html.escape
    data = f"{DIAS_SEMANA[em.weekday()]}, {em.strftime('%d/%m/%Y')} · {em.strftime('%Hh%M')}"
    logo = f'<img class="logo" src="{e(logo_src)}" alt="UFAM">' if logo_src else ""
    prox = proximo_horario(em)
    prox_txt = f"Próximo boletim às {prox.strftime('%Hh%M')}." if prox else ""
    if c.get("sem_dados"):
        corpo = f'<div class="vazio">{e(c["sem_dados"])}<br>Acompanhe em {e(SITE.replace("https://", ""))}</div>'
    else:
        ca = classe(next(k["id"] for k in C.CLASSES if k["nome"] == c["classe"]))
        m24 = f'Média das últimas 24 h: {c["media24"]} µg/m³ ({e(c["classe24"])})' if c.get("media24") is not None else "Média de 24 h ainda incompleta"
        agora = f'''
  <div class="bloco"><div class="rotulo">AGORA · {e(c["hora"])}</div>
    <div class="caixa"><div class="num" style="background:{ca["cor"]};color:{tinta(ca)}"><div class="n1">{c["pm"]}</div><div class="u">µg/m³ de MP<sub>2,5</sub></div></div>
      <div class="txt"><div class="cl">{e(c["classe"])}</div><div class="l1">IQAr {c.get("iqar") or "—"} · {e(c.get("tendencia") or "")}</div><div class="l2">{m24}</div>
      {f'<div class="l2 aviso">{e(c["aviso"])}</div>' if c.get("aviso") else ""}</div></div></div>'''
        if c.get("sem_previsao"):
            prev = f'<div class="bloco"><div class="rotulo">{e(c["janela"])}</div><div class="vazio">{e(c["sem_previsao"])}</div></div>'
            orient = ""
        else:
            prev = f'''
  <div class="bloco"><div class="rotulo">{e(c["janela"])}</div>
    <div class="caixa"><div class="num" style="background:{c["prev_cor"]};color:{c["prev_tinta"]}"><div class="n2">{e(c["prev_faixa"])}</div><div class="u">µg/m³ previstos</div></div>
      <div class="txt"><div class="cl">{e(c["prev_classe"])}</div><div class="l1">Pior hora prevista: {e(c["pior_hora"])}, {c["pior_pm"]} µg/m³ ({e(c["pior_classe"])})</div><div class="l2">{e(c["nota"])}</div></div></div></div>'''
            orient = f'''
  <div class="orient"><div class="ot">QUALIDADE DO AR {e(c["orientacao_classe"]).upper()}</div><div class="od">Orientação do IQAr: {e(c["orientacao"])} {e(prox_txt)}</div></div>'''
        corpo = agora + prev + orient
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{e(c["nome"])}</title>{FONTES}
<style>
*{{box-sizing:border-box}}body{{margin:0}}
.card{{width:1080px;height:1350px;padding:48px 72px 52px;display:flex;flex-direction:column;gap:22px;background:#f6f5f1;color:#1d2430;font-family:'Barlow',system-ui,sans-serif}}
.topo{{display:flex;flex-direction:column;align-items:center;text-align:center;gap:16px}}.logo{{height:150px;width:auto;display:block}}
sub{{font-size:.62em;vertical-align:baseline;position:relative;top:.3em;line-height:0}}
.org{{font-size:40px;font-weight:700;line-height:1.05;color:#1f3a5f}}.sub{{font-size:26px;font-weight:500;color:#4a5361;margin-top:6px}}
.cidade{{font-size:58px;font-weight:700;line-height:1;margin:-8px 0 -8px}}
.bloco{{display:flex;flex-direction:column;gap:14px}}.rotulo{{font-size:24px;font-weight:700;letter-spacing:.12em;color:#4a5361}}
.caixa{{display:flex;border-radius:20px;overflow:hidden;background:#fff;border:1px solid #dedbd2}}
.num{{width:300px;flex-shrink:0;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:22px 0;gap:4px}}
.n1{{font-family:'Barlow Condensed',sans-serif;font-size:132px;font-weight:700;line-height:.9}}.n2{{font-family:'Barlow Condensed',sans-serif;font-size:92px;font-weight:700;line-height:.9}}
.u{{font-size:26px;font-weight:600}}.txt{{display:flex;flex-direction:column;justify-content:center;gap:8px;padding:22px 36px}}
.cl{{font-size:64px;font-weight:700;line-height:1}}.l1{{font-size:28px;color:#3a4350}}.l2{{font-size:26px;color:#4a5361}}.aviso{{color:#9a3a12;font-weight:600}}
.orient{{padding:26px 36px;border-radius:20px;background:#1f3a5f;color:#fff;display:flex;flex-direction:column;gap:8px}}
.ot{{font-size:34px;font-weight:700;line-height:1.1}}.od{{font-size:26px;line-height:1.3;color:#d9e2ee}}
.vazio{{padding:48px 36px;border-radius:20px;background:#fff;border:1px solid #dedbd2;font-size:32px;color:#4a5361;line-height:1.4}}
.pe{{display:flex;flex-direction:column;gap:14px;margin-top:auto}}.grade5{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}}
.rot{{font-size:20px;color:#3a4350;white-space:nowrap}}.fonte{{display:flex;justify-content:space-between;align-items:baseline;gap:24px;font-size:21px;color:#5b6473;padding-top:6px;border-top:1px solid #dedbd2}}
.fonte b{{color:#1f3a5f;white-space:nowrap}}
</style></head><body><div class="card">
  <div class="topo">{logo}<div><div class="org">{COMISSAO.replace(" da UFAM", "") if logo else COMISSAO}</div><div class="sub">Boletim · {e(data)}</div></div></div>
  <div class="cidade">{e(c["nome"])}</div>
  {corpo}
  <div class="pe">{escala_html()}
    <div class="fonte"><div>MP<sub>2,5</sub> em µg/m³ · classes CONAMA 506/2024 · sensores PurpleAir e previsão QUALIAR-UFAM</div><b>{e(SITE.replace("https://", ""))}boletim</b></div></div>
</div></body></html>'''


def pagina_html(edicao, cards, em, imagens, arquivo):
    e = html.escape
    data = f"{DIAS_SEMANA[em.weekday()]}, {em.strftime('%d/%m/%Y')}, {em.strftime('%Hh%M')}"
    og = f"{SITE}boletim/atual/manaus.png?v={edicao}"
    figs = "".join(
        f'<figure><a href="{e(imagens[c["id"]])}"><img src="{e(imagens[c["id"]])}" alt="Boletim de {e(c["nome"])}: {e(resumo_linha(c))}" loading="lazy"></a>'
        f'<figcaption>{e(c["nome"])}: {e(resumo_linha(c))}</figcaption></figure>'
        if c["id"] in imagens else f'<div class="sem-img"><b>{e(c["nome"])}</b><br>{e(resumo_linha(c))}</div>'
        for c in cards)
    linhas = "".join(f'<li><b>{e(x["data"])}</b> · ' + " · ".join(e(t) for t in x["linhas"]) + "</li>" for x in arquivo[:60])
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Boletim da qualidade do ar · {COMISSAO}</title>
<meta property="og:title" content="Boletim da qualidade do ar · {e(data)}">
<meta property="og:description" content="{e(" · ".join(resumo_linha(c, curto=True) for c in cards))}">
<meta property="og:image" content="{e(og)}"><meta property="og:image:width" content="1080"><meta property="og:image:height" content="1350">
<meta property="og:type" content="website"><meta property="og:url" content="{SITE}boletim/">
<style>
:root{{--papel:#f6f5f1;--tinta:#1d2430;--t2:#4a5361;--linha:#dedbd2;--azul:#1f3a5f}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--papel:#15181d;--tinta:#eceae4;--t2:#b3b8c1;--linha:#2c313a;--azul:#9db8dc}}}}
body{{margin:0;background:var(--papel);color:var(--tinta);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45}}
main{{max-width:1120px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:1.6rem;margin:0 0 4px;color:var(--azul)}}.sub{{color:var(--t2);margin:0 0 20px}}
.grade{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}}
figure{{margin:0}}figure img{{width:100%;height:auto;border-radius:10px;border:1px solid var(--linha);display:block}}
figcaption{{font-size:.9rem;color:var(--t2);margin-top:6px}}.sem-img{{padding:16px;border:1px solid var(--linha);border-radius:10px}}
h2{{font-size:1.15rem;margin:32px 0 8px}}ul{{padding-left:18px;font-size:.92rem}}li{{margin:4px 0}}a{{color:var(--azul)}}
.nota{{font-size:.85rem;color:var(--t2)}}
</style></head><body><main>
<h1>Boletim da qualidade do ar</h1>
<p class="sub">{COMISSAO} · edição de {e(data)} · <a href="../">previsão hora a hora no QUALIAR-UFAM</a></p>
<div class="grade">{figs}</div>
<p class="nota">Valores de material particulado fino (MP<sub>2,5</sub>) em µg/m³, mediana dos sensores PurpleAir de cada cidade (correção EPA), classes da Resolução CONAMA nº 506/2024. A previsão é a versão publicada do modelo QUALIAR-UFAM. Boletins às 20h30, 02h30, 08h30 e 14h30. Toque na imagem para abrir em tamanho cheio e compartilhar.</p>
<h2>Boletins anteriores</h2><ul>{linhas}</ul>
</main></body></html>'''


def resumo_linha(c, curto=False):
    if c.get("sem_dados"):
        return "sem medição"
    s = f'agora {c["pm"]} ({c["classe"]})'
    if c.get("prev_faixa"):
        jan = c["janela"].split("·")[0].strip().lower()
        s += f'; {jan}: {c["prev_faixa"]} ({c["prev_classe"]})' if not curto else f' → {c["prev_faixa"]} ({c["prev_classe"]})'
    return (f'{c["nome"]}: ' + s) if curto else s


def texto_whatsapp(edicao, cards, em):
    data = f"{em.strftime('%d/%m')} {em.strftime('%Hh%M')}"
    jan = cards[0]["janela"].title().replace("Às", "às") if cards else ""
    linhas = [f"*Boletim da qualidade do ar · {data}*", COMISSAO, "", f"MP₂,₅ (µg/m³) agora → {jan.lower()}:"]
    for c in cards:
        if c.get("sem_dados"):
            linhas.append(f"• {c['nome']}: sem medição")
        elif c.get("prev_faixa"):
            linhas.append(f"• {c['nome']}: {c['pm']} {c['classe']} → {c['prev_faixa']} {c['prev_classe']}")
        else:
            linhas.append(f"• {c['nome']}: {c['pm']} {c['classe']}")
    piores = [c for c in cards if c.get("pior_id", 0) >= 3]
    if piores:
        linhas += ["", "Atenção: " + "; ".join(f"{c['nome']} pode chegar a {c['pior_classe']} às {c['pior_hora']}" for c in piores) + "."]
    linhas += ["", f"Cartões: {SITE}boletim/?e={edicao}"]
    return "\n".join(linhas)


# ---------------------------------------------------------------- imagem
def renderizar(htmls, destino):
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        kw = {}
        if os.path.exists("/opt/pw-browsers/chromium") and not os.environ.get("GITHUB_ACTIONS"):
            kw["executable_path"] = "/opt/pw-browsers/chromium"
        nav = p.chromium.launch(**kw)
        pg = nav.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for cid, arq in htmls.items():
            pg.goto(Path(arq).resolve().as_uri(), wait_until="networkidle", timeout=30000)
            pg.wait_for_timeout(300)
            png = destino / f"{cid}.png"
            pg.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
            out[cid] = png
        nav.close()
    return out


# ---------------------------------------------------------------- Telegram
def _multipart(campos, arquivos):
    """Corpo multipart/form-data: campos {nome: texto}, arquivos [(nome, caminho)]."""
    fronteira = "----qualiar" + str(int(time.time() * 1000))
    partes = []
    for k, v in campos.items():
        partes.append(f'--{fronteira}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for nome, caminho in arquivos:
        partes.append(f'--{fronteira}\r\nContent-Disposition: form-data; name="{nome}"; filename="{Path(caminho).name}"\r\n'
                      f'Content-Type: image/png\r\n\r\n'.encode() + Path(caminho).read_bytes() + b"\r\n")
    partes.append(f"--{fronteira}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={fronteira}"


def enviar_telegram(hist):
    """Bot do Telegram: segredos TELEGRAM_TOKEN (do @BotFather) e TELEGRAM_CHAT (um ou mais ids de
    conversa, grupo ou canal, separados por vírgula). Manda os cartões como álbum, com o resumo
    na legenda da primeira imagem. TELEGRAM_CIDADES (opcional): ids separados por vírgula ou "todas"."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT", "").split(",") if c.strip()]
    if not token or not chats:
        print("Telegram não configurado: nada enviado.")
        return 0
    escolha = os.environ.get("TELEGRAM_CIDADES", "todas").strip() or "todas"
    imgs = hist.get("imagens") or {}
    ids = [c["id"] for c in hist.get("cartoes", []) if c["id"] in imgs and (escolha == "todas" or c["id"] in escolha.split(","))]
    arquivos = [(f"f{k}", SAIDA / imgs[cid]) for k, cid in enumerate(ids) if (SAIDA / imgs[cid]).exists()]
    import re
    texto = re.sub(r"\*(.+?)\*", r"<b>\1</b>", html.escape(hist["whatsapp"], quote=False))[:1000]
    base = f"https://api.telegram.org/bot{token}/"
    ok = 0
    for chat in chats:
        try:
            if not arquivos:
                corpo = urllib.parse.urlencode({"chat_id": chat, "text": texto, "parse_mode": "HTML"}).encode()
                req = urllib.request.Request(base + "sendMessage", data=corpo)
            else:
                media = [{"type": "photo", "media": f"attach://{n}"} for n, _ in arquivos]
                media[0].update({"caption": texto, "parse_mode": "HTML"})
                corpo, tipo = _multipart({"chat_id": chat, "media": json.dumps(media, ensure_ascii=False)}, arquivos)
                req = urllib.request.Request(base + "sendMediaGroup", data=corpo, headers={"Content-Type": tipo})
            with urllib.request.urlopen(req, timeout=90) as r:
                sucesso = json.loads(r.read().decode()).get("ok")
            print(f"Telegram {chat}: {'ok' if sucesso else 'falhou'}")
            ok += bool(sucesso)
        except Exception as e:
            print(f"Telegram {chat}: erro {e}")
    return ok


# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--enviar", action="store_true")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--sem-imagem", action="store_true")
    ap.add_argument("--agora", help="hora local para teste, ex.: 2026-10-20T20:31")
    a = ap.parse_args()
    agora = datetime.fromisoformat(a.agora).replace(tzinfo=TZ) if a.agora else datetime.now(TZ)
    SAIDA.mkdir(parents=True, exist_ok=True)
    reg_json = SAIDA / "boletins.json"
    hist = ler(reg_json, {"edicao": None, "arquivo": []})

    if a.enviar:
        if not hist.get("edicao"):
            print("Nada a enviar.")
            return
        enviar_telegram(hist)
        return

    if agora.date().isoformat() > FIM_DA_SERIE and not a.forcar:
        print(f"Série de boletins encerrada em {FIM_DA_SERIE}.")
        return
    hv = horario_da_vez(agora, a.forcar)
    if not hv:
        print("Fora do horário de boletim.")
        return
    h, em = hv
    edicao = em.strftime("%Y-%m-%d_%H%M")
    if hist.get("edicao") == edicao and not a.forcar:
        print(f"Boletim {edicao} já publicado.")
        return
    if a.verificar:
        print(f"Boletim {edicao} a gerar.")
        saida = os.environ.get("GITHUB_OUTPUT")
        if saida:
            with open(saida, "a") as f:
                f.write("novo=1\n")
        return

    regioes = (ler(DOCS / "data" / "regioes.json", {}) or {}).get("regioes") or [{"id": "manaus", "nome": "Manaus", "pasta": "data/"}]
    cards = [cartao(r, ler(DOCS / r["pasta"] / "qualiar.json"), h, em) for r in regioes]

    logo = next((DOCS / "img" / n for n in ("logo-ufam.png", "logo-ufam.svg", "logo-ufam.jpg") if (DOCS / "img" / n).exists()), None)
    tmp = SAIDA / "_cartoes"
    shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
    htmls = {}
    for c in cards:
        arq = tmp / f"{c['id']}.html"
        arq.write_text(cartao_html(c, em, logo.resolve().as_uri() if logo else None), encoding="utf-8")
        htmls[c["id"]] = arq

    imagens = {}
    if not a.sem_imagem:
        pasta = SAIDA / edicao
        pasta.mkdir(exist_ok=True)
        try:
            pngs = renderizar(htmls, pasta)
            atual = SAIDA / "atual"
            atual.mkdir(exist_ok=True)
            for cid, png in pngs.items():
                shutil.copy(png, atual / f"{cid}.png")
                imagens[cid] = f"{edicao}/{cid}.png"
        except Exception as e:
            print(f"Imagens não geradas: {e}")
    shutil.rmtree(tmp, ignore_errors=True)

    # apaga imagens antigas (o texto de cada edição fica em boletins.json)
    limite = (em - timedelta(days=PNG_DIAS)).strftime("%Y-%m-%d_%H%M")
    for d in SAIDA.iterdir():
        if d.is_dir() and d.name[:4].isdigit() and d.name < limite:
            shutil.rmtree(d, ignore_errors=True)

    texto = texto_whatsapp(edicao, cards, em)
    data_txt = f"{em.strftime('%d/%m/%Y %Hh%M')}"
    registro = {"edicao": edicao, "data": data_txt, "linhas": [resumo_linha(c, curto=True) for c in cards]}
    arquivo = [registro] + [x for x in hist.get("arquivo", []) if x.get("edicao") != edicao]
    hist.update({"edicao": edicao, "emitido_em": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "cartoes": cards, "whatsapp": texto, "imagens": imagens, "arquivo": arquivo})
    reg_json.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    (SAIDA / "index.html").write_text(pagina_html(edicao, cards, em, imagens, arquivo), encoding="utf-8")
    print(f"Boletim {edicao} gerado ({len(cards)} cidades, {len(imagens)} imagens).")
    print(texto)


if __name__ == "__main__":
    main()
