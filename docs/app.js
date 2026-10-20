/* QUALIAR-UFAM: painel de qualidade do ar observada e prevista em Manaus e nas cidades com campus da UFAM. */
const REGIOES_PADRAO = [
  { id: "manaus", nome: "Manaus", pasta: "data/" }, { id: "itacoatiara", nome: "Itacoatiara", pasta: "data/regioes/itacoatiara/" },
  { id: "parintins", nome: "Parintins", pasta: "data/regioes/parintins/" }, { id: "humaita", nome: "Humaitá", pasta: "data/regioes/humaita/" },
  { id: "coari", nome: "Coari", pasta: "data/regioes/coari/" }, { id: "benjamin", nome: "Benjamin Constant", pasta: "data/regioes/benjamin/" },
];
(async function () {
  let d, focos, limites = null, regioes = REGIOES_PADRAO;
  try { const lst = (await carregarJSON("data/regioes.json")).regioes.filter(r => r.pasta); if (lst.length) regioes = lst; } catch (e) { /* índice ainda não existe */ }
  const pedida = new URLSearchParams(location.search).get("r") || "manaus";
  const reg = regioes.find(r => r.id === pedida) || regioes[0];
  const sel = document.getElementById("sel-regiao");
  if (sel) {
    sel.innerHTML = regioes.map(r => `<option value="${esc(r.id)}"${r.id === reg.id ? " selected" : ""}>${esc(r.nome)}${r.classe24 ? "" : ""}</option>`).join("");
    sel.addEventListener("change", () => { const u = new URL(location.href); u.searchParams.set("r", sel.value); location.href = u.toString(); });
  }
  const base = reg.pasta;
  try {
    [d, focos] = await Promise.all([carregarJSON(base + "qualiar.json"), carregarJSON(base + "focos_pontos.geojson")]);
  } catch (e) {
    document.getElementById("atualiz").textContent = `Ainda não há dados de ${reg.nome}. A primeira coleta desta cidade aparece aqui na próxima hora.`;
    console.error(e); return;
  }
  try { limites = await carregarJSON(base + "limites.geojson"); } catch (e) { limites = null; }
  CLASSES = d.classes;
  const cidade = (d.regiao && d.regiao.nome) || reg.nome, centro = d.nama.nome;
  document.querySelectorAll("[data-cidade]").forEach(el => { el.textContent = el.dataset.cidade.replace("{cidade}", cidade); });
  document.title = `QUALIAR-UFAM · Qualidade do ar em ${cidade}`;
  window.__centro = centro; window.__cidade = cidade;
  const h0 = new Date(d.hora_base);
  const at = d.atual;

  /* ---------- cabeçalho e avisos ---------- */
  const st = d.fontes_status || {};
  document.getElementById("atualiz").innerHTML =
    `<span>Atualizado em <b>${horaLocal(d.gerado_em)}</b> · a cada hora</span>` +
    Object.entries(st).map(([f, s]) => `<span class="chip ${/^ok/.test(s) ? "ok" : (/^erro|^sem /.test(s) ? "erro" : "")}" title="${esc(s)}">${esc(f)}</span>`).join("");
  const avisos = [];
  if (d.dados_de_teste) avisos.push("Demonstração: PM2,5 e meteorologia são sintéticos. Nada aqui deve ser usado para decisão.");
  for (const [f, s] of Object.entries(st)) if (/^erro|^sem /.test(s)) avisos.push(`${f}: ${s}`);
  if (d.nama && /padrão|aproximadas/.test(d.nama.origem || "")) avisos.push(`Estação ${d.nama.nome} não encontrada na PurpleAir: o centro do método usa coordenadas aproximadas de ${cidade}.`);
  else if (d.nama && /última posição/.test(d.nama.origem || "")) avisos.push(`A estação ${d.nama.nome} não enviou dados nesta hora: o centro do método usa a última posição conhecida.`);
  if (avisos.length) { const av = document.getElementById("aviso"); av.textContent = avisos.join(" · "); av.hidden = false; }

  /* ---------- agora ---------- */
  const card = document.getElementById("agora-card");
  document.getElementById("ag-valor").textContent = num(at.mediana, 0);
  document.getElementById("ag-classe").innerHTML = seloClasse(at.classe).replace('class="selo"', 'class="selo grande"');
  if (at.classe) card.style.borderLeftColor = corClasse(at.classe);
  const seta = at.tendencia === "subindo" ? "↑" : at.tendencia === "caindo" ? "↓" : "→";
  document.getElementById("ag-detalhe").innerHTML =
    `Mediana de <b>${at.n_sensores}</b> de ${at.n_total} estações às ${hh(d.hora_base)}.<br>` +
    `Tendência: <b>${seta} ${at.tendencia}</b> (${num(at.tendencia_h, 1)} µg/m³ por hora, últimas 3 h).<br>` +
    `Média das últimas 24 h: <b>${num(at.media24, 0)} µg/m³</b> ${at.classe24 ? "· " + esc(classe(at.classe24).nome) : ""}` +
    (at.horas_media24 < 24 ? ` <span title="horas com dado">(${at.horas_media24} h)</span>` : "") +
    (at.iqar24 != null ? ` · <b>IQAr ${at.iqar24 > 400 ? "acima de 400" : num(at.iqar24, 0)}</b>` : "") + ".";

  /* ---------- cartões de previsão ---------- */
  document.getElementById("prev-cartoes").innerHTML = d.destaques.length ? d.destaques.map(p => {
    const c = classe(p.classe);
    const pc = Math.round(p.prob[p.classe - 1] * 100);
    return `<article class="prev-c" aria-label="Previsão para daqui a ${p.h} horas">
      <div class="faixa" style="background:${c.cor};color:${tintaSobre(p.classe)}"><span>+${p.h} h · ${hh(p.t)}</span><span>${esc(c.nome)}</span></div>
      <div class="corpo">
        <span class="val">${num(p.pm, 0)}<small>µg/m³</small></span>
        <span class="linha">provável entre ${num(p.lo, 0)} e ${num(p.hi, 0)}</span>
        <span class="linha">chance desta classe: <b>${pc}%</b></span>
        <span class="linha">média 24 h: <b>${num(p.media24, 0)}</b> · ${esc(classe(p.classe24).nome)}${p.iqar24 != null ? ` · IQAr ${p.iqar24 > 400 ? "&gt;400" : num(p.iqar24, 0)}` : ""}</span>
        <span class="linha fogo">${fogoLinha(p)}</span>
      </div></article>`;
  }).join("") : `<p class="nota">Sem previsão: faltam dados de PM2,5 das estações nesta hora.</p>`;
  const pior = d.previsao.reduce((a, p) => (!a || p.pm > a.pm ? p : a), null);
  const lav = (d.chuva_obs || {}).lavagem || {};
  const notaChuva = lav.recente
    ? `<b>Chuva recente${lav.nao_prevista_recente ? " não prevista" : ""}</b> (há ${lav.horas_desde ? lav.horas_desde + " h" : "menos de 1 h"}): a previsão considera que a fumaça removida volta em cerca de ${d.chuva_obs.criterios.tau_recuperacao_h} h e não usa esta hora para recalibrar o peso do fogo. `
    : "";
  const rm = d.modelo.risco_matinal;
  const notaMatinal = rm
    ? `<b>Risco de fumaça matinal</b>: a variante em teste F24R, que soma a fumaça de focos distantes e a descida da fumaça no começo da manhã, indica ${num(rm.pm, 0)} µg/m³ às ${hh(rm.t)}${Object.keys(rm.origem || {}).length ? ` (origem provável: ${Object.entries(rm.origem).map(([u, f]) => `${esc(u)} ${Math.round(f * 100)}%`).join(", ")})` : ""}. Os cartões seguem a versão publicada, ${esc(d.modelo.modelo_publicado)}. `
    : "";
  const pubG = d.modelo.modelo_publicado;
  const testesG = (d.modelo.variantes_no_site || []).filter(n => n !== pubG && n !== "CAMS");
  const notaLinhas = `No gráfico, a linha preta tracejada é a previsão publicada (${esc(pubG)}), a mesma dos cartões` +
    (testesG.length ? `; a linha cinza${testesG.length > 1 ? "s" : ""} (${testesG.map(esc).join(", ")}) ${testesG.length > 1 ? "são versões" : "é a versão"} em teste com maior acerto de classe nas previsões de 6 a 24 h, mostrada${testesG.length > 1 ? "s" : ""} só para comparação` : "") +
    ((d.modelo.variantes_no_site || []).includes("CAMS") ? "; a linha azul é o CAMS (Copernicus) ajustado ao medido" : "") + ". ";
  document.getElementById("prev-nota").innerHTML = pior
    ? notaMatinal + notaChuva + `Pior hora prevista nas próximas 24 h: <b>${hh(pior.t)}</b>, com ${num(pior.pm, 0)} µg/m³ (${esc(classe(pior.classe).nome)}). ` +
      notaLinhas +
      `As classes dos cartões usam o valor horário (indicativo); a classe oficial do IQAr usa a média de 24 h, mostrada abaixo do valor. Modelo ${esc(d.modelo.versao)}.`
    : "";

  /* ---------- gráfico 24 h observadas + 24 h previstas ---------- */
  desenharGrafico(document.getElementById("grafico-prev"), d, h0);

  /* ---------- estações ---------- */
  const sens = [...d.sensores].sort((a, b) => (b.nama - a.nama) || (!!a.entorno - !!b.entorno) || (b.valido - a.valido) || ((b.pm ?? -1) - (a.pm ?? -1)));
  document.querySelector("#tab-sensores tbody").innerHTML = sens.map(s => `<tr class="${s.valido ? "" : "inval"} ${s.nama ? "nama" : ""}">
      <td>${esc(s.nome)}${s.nama ? " ★" : ""}${s.entorno ? ` <span class="nota" title="${esc(s.entorno)}">(entorno)</span>` : ""}${s.sinal_chuva ? `<span class="gota" title="sinal de chuva na última hora (${s.sinal_chuva.nivel === "provavel" ? "provável" : "possível"})"></span>` : ""}</td>
      <td class="n">${s.valido ? num(s.pm, 0) : "—"}</td>
      <td>${s.valido ? seloClasse(s.classe) : `<span class="nota" title="${esc(s.motivo)}">descartado</span>`}</td>
      <td class="n">${num(s.dist_nama_km, 1, " km")}</td></tr>`).join("");
  document.getElementById("ar-contadores").innerHTML =
    `<div class="contador"><b>${num(at.mediana, 0)}</b><small>mediana agora (µg/m³)</small></div>` +
    `<div class="contador"><b>${seta} ${num(Math.abs(at.tendencia_h), 1)}</b><small>µg/m³ por hora (${at.tendencia})</small></div>` +
    `<div class="contador"><b>${num(at.media24, 0)}</b><small>média 24 h (µg/m³)</small></div>`;

  /* ---------- meteorologia ---------- */
  const mt = d.meteo, ma = mt.agora || {}, mp = mt.previsao || [];
  const metHTML = [
    { nome: "Temperatura", un: "°C", campo: "temp", casas: 0, tipo: "linha" },
    { nome: "Umidade", un: "%", campo: "ur", casas: 0, tipo: "linha" },
    { nome: "Chuva", un: "mm/h", campo: "chuva", casas: 1, tipo: "barra" },
  ].map(v => {
    const ehChuva = v.campo === "chuva", ag = d.chuva_obs?.agora || {};
    const extra = ehChuva ? `<small>${num(mp.slice(1).reduce((a, l) => a + (l.chuva || 0), 0), 1)} mm previstos em 24 h</small>` +
      `<small style="color:var(--chuva);font-weight:600">${ag.evento ? `observada: chovendo em ${ag.n_sinais} de ${ag.n_sensores} estações` : "observada: sem chuva"}</small>` : "";
    return `<div class="met"><div class="cab"><small>${ehChuva ? "Chuva prevista agora" : v.nome + " agora"}</small><b>${num(ma[v.campo], v.casas)}<small> ${v.un}</small></b>${extra}</div>${spark(mp, v)}</div>`;
  }).join("");
  document.getElementById("met-grade").innerHTML = metHTML;
  desenharPerfilVento(document.getElementById("vento-perfil"), d);
  const chuva24 = mp.slice(1).reduce((s, l) => s + (l.chuva || 0), 0);
  const probMax = Math.max(0, ...mp.slice(1).map(l => l.prob || 0));
  desenharChuvaObs(d, h0);
  const ultChuva = lav.ultima ? (lav.horas_desde === 0 ? "nesta hora" : `há ${lav.horas_desde} h (${hh(lav.ultima)})`) : "nenhuma nos registros recentes";
  document.getElementById("met-ficha").innerHTML = `
    <dt>Última chuva observada</dt><dd>${ultChuva}</dd>
    <dt>Dias sem chuva</dt><dd><b>${num(mt.dias_sem_chuva, 0)}</b> (dias com menos de 1 mm) · ${esc(mt.dias_sem_chuva_fonte || "modelo")}</dd>
    <dt>Chuva prevista 24 h</dt><dd>${num(chuva24, 1)} mm · chance máxima ${num(probMax, 0)}%</dd>
    <dt>Chuva acumulada</dt><dd>${num(mt.chuva_7d_mm, 0)} mm em 7 dias · ${num(mt.chuva_30d_mm, 0)} mm em 30 dias</dd>
    <dt>Vento agora</dt><dd>${num(ma.vento, 1)} m/s, vindo de ${cardeal(ma.dir)} (${num(ma.dir, 0)}°)</dd>
    <dt>Fonte</dt><dd>${esc(mt.fonte)}. Chuva observada: assinatura nos sensores PurpleAir e boletins METAR dos aeroportos${d.chuva_obs?.inmet_ativo ? " e pluviômetro do INMET" : ""}.</dd>`;

  /* ---------- focos ---------- */
  const tf = d.focos.totais, cr = d.focos.criterios;
  document.getElementById("fogo-contadores").innerHTML =
    `<div class="contador"><b style="color:var(--f0)">${tf.ativos}</b><small>focos ativos</small></div>` +
    `<div class="contador"><b>${tf.recem_extintos}</b><small>recém-extintos (até ${cr.recem_extinto_h} h)</small></div>` +
    `<div class="contador"><b style="color:var(--f1)">${tf.provaveis_incendios}</b><small>prováveis incêndios</small></div>`;
  const z = v => v ? v : `<span class="zero">0</span>`;
  const HZ = [{ h: 0, rotulo: "Agora", municipios: d.modelo.municipios_agora || {}, setor: d.modelo.setor_agora, fogo_ug: null }]
    .concat(d.destaques.map(p => ({ h: p.h, rotulo: `+${p.h} h`, municipios: p.municipios || {}, setor: p.setor, fogo_ug: p.fogo_ug, t: p.t })));
  const hSel = document.getElementById("h-sel");
  hSel.innerHTML = HZ.map((x, i) => `<button type="button" data-i="${i}" aria-pressed="${i === 0}">${x.rotulo}</button>`).join("");
  function desenharMunis(i) {
    const x = HZ[i];
    const linhas = [...d.focos.municipios].sort((a, b) => ((x.municipios[b.municipio] || 0) - (x.municipios[a.municipio] || 0)) || (b.ativos - a.ativos));
    document.querySelector("#tab-munis tbody").innerHTML = linhas.map(m => {
      const w = x.municipios[m.municipio] || 0;
      return `<tr>
      <td>${esc(m.municipio)}</td><td class="n">${z(m.ativos)}</td><td class="n">${z(m.recem_extintos)}</td>
      <td class="n">${z(m.provaveis_incendios)}</td><td class="n">${m.dist_min_km == null ? "—" : num(m.dist_min_km, 0, " km")}</td>
      <td><span class="peso"><span class="barra"><i style="width:${w * 100}%"></i></span><span class="${w >= 0.005 ? "" : "zero"}">${w >= 0.005 ? num(w * 100, 0) + "%" : "0"}</span></span></td></tr>`;
    }).join("");
    const st = x.setor;
    document.getElementById("vento-trajeto").innerHTML = !st ? "Sem vento previsto para este horizonte." : st.calmaria
      ? `<b>${x.rotulo}:</b> calmaria (vento médio abaixo de 1 m/s). Sem direção definida, só os focos a até ~20 km pesam.`
      : `<b>${x.rotulo}:</b> vento de transporte vindo de <b>${cardeal(st.dir)}</b> (${st.dir}°) a ${num(st.vel, 1)} m/s. A pluma abre cerca de ±${st.sigma}°. ` +
        `Fumaça de um foco a 50 km leva ~${num(50 / (st.vel * 3.6), 0)} h para chegar; a 100 km, ~${num(100 / (st.vel * 3.6), 0)} h.` +
        (x.fogo_ug != null ? ` Contribuição prevista do fogo: <b>${num(x.fogo_ug, 0)} µg/m³</b>.` : "");
    hSel.querySelectorAll("button").forEach(bt => bt.setAttribute("aria-pressed", String(+bt.dataset.i === i)));
    document.dispatchEvent(new CustomEvent("horizonte", { detail: x }));
  }
  hSel.addEventListener("click", ev => { const bt = ev.target.closest("button"); if (bt) desenharMunis(+bt.dataset.i); });
  window.__desenharMunis = () => desenharMunis(0);
  const ff = d.focos.fonte || { nome: "MonitorBETA", url: "https://ufamcca.github.io/MonitorBETA/", gerado_em: d.focos.monitorbeta_gerado_em };
  document.getElementById("fogo-nota").innerHTML =
    `Focos do <a href="${esc(ff.url)}" target="_blank" rel="noopener">${esc(ff.nome)}</a>, atualizados em ${horaLocal(ff.gerado_em)}` +
    (ff.nome === "MonitorBETA" ? "" : " (cada quadrado de 0,25° com detecção de satélite nas últimas 48 h conta como um foco; ativo = detectado nas últimas 3 h)") + `. ` +
    `Distâncias medidas a partir da estação ${esc(centro)}. <b>Peso na fumaça</b>: fração do índice de fogo a barlavento que vem de cada município no horizonte escolhido; depende do vento no trajeto, da distância, do tempo de viagem da fumaça e de o foco estar queimando quando ela partiu. <b>Provável incêndio</b>: foco ativo há ${cr.incendio_duracao_h} h ou mais, com ${cr.incendio_pixels} pixels ou mais, ou com potência radiativa de ${cr.incendio_frp_mw} MW ou mais.`;

  /* ---------- método e validação ---------- */
  const mo = d.modelo, an = d.focos.aneis_km;
  document.getElementById("mod-ficha").innerHTML = `
    <dt>Versão</dt><dd>${esc(mo.versao)}</dd>
    ${mo.cams_fator != null ? `<dt>CAMS</dt><dd>${num(mo.cams_agora, 0)} µg/m³ agora no modelo; ajuste ao nível medido: ×${num(mo.cams_fator, 2)}</dd>` : ""}
    ${mo.perfil_horario ? `<dt>Perfil horário</dt><dd>pico em ${Object.entries(mo.perfil_horario).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([h]) => h + "h").join(", ")} (aprendido dos últimos dias)</dd>` : ""}
    ${mo.regional ? `<dt>Fumaça distante</dt><dd>índice ${num(mo.regional.ifr_agora, 1)} agora, ${num(mo.regional.fumaca_agora_ug, 0)} µg/m³ com o peso ${num(mo.regional.k_reg, 3)} (${mo.regional.k_reg_horas >= 12 ? `calibrado em ${mo.regional.k_reg_horas} h` : `ainda calibrando: ${mo.regional.k_reg_horas} de 12 h`})${Object.keys(mo.regional.uf_agora || {}).length ? ` · origem: ${Object.entries(mo.regional.uf_agora).map(([u, f]) => `${esc(u)} ${Math.round(f * 100)}%`).join(", ")}` : ""} · ${mo.regional.celulas} células com foco nas últimas 72 h (INPE)</dd>` : ""}
    ${(() => { const pn = d.previsao.filter(p => p.noite > 1.05); if (!pn.length) return ""; const mx = pn.reduce((a, p) => p.noite > a.noite ? p : a); return `<dt>Madrugada</dt><dd>fumaça ×${num(mx.noite, 2)} às ${hh(mx.t)} (noite estável em ${Math.round((mx.noite_det?.estavel ?? 0) * 100)}% das horas, vento a 925 hPa de ${num(mx.noite_det?.v925_ms, 1)} m/s)</dd>`; })()}
    ${mo.fundo_regional_ug ? `<dt>Fundo regional</dt><dd>${Object.entries(mo.fundo_regional_ug).map(([w, v]) => `${num(v, 0)} µg/m³ (média de ${w}, ${mo.fundo_medicoes?.[w] ?? "—"} medições)`).join(" · ")}</dd>` : ""}
    <dt>Fogo a barlavento</dt><dd><b>${num(mo.ifb_agora, 1)}</b> agora · ${an.map((a, i) => `${a[0]}–${a[1]} km: ${num(mo.ifb_aneis?.[i], 1)}`).join(" · ")}</dd>
    <dt>Peso do fogo</dt><dd>${num(mo.k_usado, 2)} µg/m³ por unidade (calibrado na hora)</dd>
    <dt>Vento de transporte</dt><dd>${mo.tem_925 ? `média vetorial: ${Math.round((1 - mo.parametros.peso_925) * 100)}% do vento a 10 m e ${Math.round(mo.parametros.peso_925 * 100)}% a 925 hPa (~800 m)` : "só vento a 10 m (925 hPa indisponível nesta rodada)"}</dd>
    <dt>Camada de mistura</dt><dd>fator ${num(mo.fator_diurno_agora, 2)} agora${mo.ventilacao_agora != null ? ` · ventilação ${num(mo.ventilacao_agora, 0)} m²/s (${esc(mo.ventilacao_classe)})` : ""}</dd>
    ${mo.camada ? `<dt>Camada corrigida (F24L)</dt><dd>${num(mo.camada.agora_m, 0)} m agora${mo.camada.modelo_agora_m != null ? ` (modelo: ${num(mo.camada.modelo_agora_m, 0)} m)` : ""} · fator de correção desta cidade α = ${mo.camada.alfa >= 0 ? "+" : ""}${num(mo.camada.alfa, 2)} (${mo.camada.k_l_horas >= 12 ? `calibrado em ${mo.camada.k_l_horas} h` : `ainda calibrando: ${mo.camada.k_l_horas ?? 0} de 12 h`}) · 150 m fixos das 20h às 07h (Dias-Júnior et al., 2022)</dd>` : ""}
    ${mo.ilha_calor && mo.ilha_calor.anomalia_c != null ? `<dt>Ilha de calor</dt><dd>${mo.ilha_calor.anomalia_c >= 0 ? "+" : ""}${num(mo.ilha_calor.anomalia_c, 1)} °C em relação ao normal da hora (${mo.ilha_calor.dias} dias de referência)</dd>` : ""}
    ${ff.painel_fogo ? `<dt>Painel do Fogo</dt><dd>eventos do Censipam de ${horaLocal(ff.painel_fogo)}: área e persistência aumentam o peso dos focos</dd>` : ""}
    <dt>Centro</dt><dd>${esc(d.nama.nome)} · ${num(d.nama.lat, 4)}, ${num(d.nama.lon, 4)}</dd>`;
  document.querySelector("#tab-val tbody").innerHTML = d.validacao.map(v => v.n ? `<tr>
      <td>+${v.h} h</td><td class="n">${v.n}</td><td class="n">${num(v.mae, 1)}</td><td class="n">${num(v.mae_persistencia, 1)}</td>
      <td class="n">${num(v.acerto_classe * 100, 0, "%")}</td></tr>` : `<tr><td>+${v.h} h</td><td colspan="4" class="nota">aguardando a hora prevista chegar</td></tr>`).join("");
  const comp = d.validacao.filter(v => v.variantes);
  const elv = document.getElementById("val-variantes");
  if (comp.length && elv) {
    const noSite = d.modelo.variantes_no_site || Object.keys(comp[0].variantes);
    const nomes = Object.keys(comp[0].variantes).filter(n => noSite.includes(n));
    const pub = d.modelo.modelo_publicado;
    elv.innerHTML = `<table class="tabela-s"><thead><tr><th>Horizonte</th>${nomes.map(n => `<th class="n">${esc(n)}${n === pub ? " ★" : ""}</th>`).join("")}</tr></thead><tbody>` +
      comp.map(v => `<tr><td>+${v.h} h <span class="nota">(${v.variantes[nomes[0]].n})</span></td>${nomes.map(n => {
        const x = v.variantes[n]; if (!x) return `<td class="n">—</td>`;
        const melhor = Math.min(...nomes.map(m => v.variantes[m]?.mae ?? Infinity)) === x.mae;
        return `<td class="n">${melhor ? "<b>" : ""}${num(x.mae, 0)}${melhor ? "</b>" : ""} <span class="nota">${num(x.acerto_classe * 100, 0)}%</span></td>`;
      }).join("")}</tr>`).join("") + `</tbody></table>`;
    elv.hidden = false; document.getElementById("t-variantes").hidden = false;
  }
  const vnp = d.validacao.filter(v => v.n_chuva_np);
  if (vnp.length) {
    const el = document.getElementById("val-chuva");
    el.innerHTML = `<b>Com chuva não prevista no intervalo:</b> ` + vnp.map(v => `+${v.h} h: erro médio ${num(v.mae_chuva_np, 1)} e viés ${v.vies_chuva_np > 0 ? "+" : ""}${num(v.vies_chuva_np, 1)} µg/m³ (${v.n_chuva_np})`).join(" · ") +
      `. Viés positivo = o modelo previu ar pior do que o observado, porque não sabia da chuva.`;
    el.hidden = false;
  }

  /* ---------- classes ---------- */
  document.getElementById("classes-lista").innerHTML = CLASSES.map((c, i) => {
    const de = i ? CLASSES[i - 1].ate : 0;
    const faixa = c.ate == null ? `acima de ${de}` : `${i ? "acima de " + de + " até " : "0 a "}${c.ate}`;
    return `<div class="classe-linha"><span>${seloClasse(c.id)}<br><small class="nota">${faixa} µg/m³ · IQAr ${c.iqar ? c.iqar[0] + "–" + c.iqar[1] : ""}</small></span><span>${esc(c.msg)}</span></div>`;
  }).join("");

  /* ---------- mapa ---------- */
  montarMapa(d, focos, limites);
  window.__desenharMunis();
})();

function fogoLinha(p) {
  const top = Object.entries(p.municipios || {})[0];
  if (!p.fogo_ug || p.fogo_ug < 1 || !top) return "queimadas próximas: pouca ou nenhuma fumaça";
  return `queimadas próximas: <b>~${num(p.fogo_ug, 0)}</b> µg/m³<br>principal origem: ${esc(top[0])} (${num(top[1] * 100, 0)}%)`;
}

/* Chuva prevista x observada: alerta, faixa horária e boletins dos aeroportos */
function desenharChuvaObs(d, h0) {
  const el = document.getElementById("chuva-obs"), co = d.chuva_obs;
  if (!co) { el.innerHTML = ""; return; }
  const ag = co.agora || {}, lav = co.lavagem || {};
  const nomes = d.sensores.filter(s => s.sinal_chuva).map(s => s.nome);
  let alerta = "";
  if (ag.evento) {
    alerta = `<div class="chuva-alerta" role="status"><b>${ag.nao_prevista ? "Chuva não prevista" : "Chuva"} às ${hh(ag.t)}</b>: ` +
      (nomes.length ? `sinal em ${nomes.length} de ${ag.n_sensores} estações (${nomes.map(esc).join(", ")}). ` : "") +
      Object.entries(ag.metar || {}).map(([k, v]) => `${k}: ${esc(v.texto)}`).join(" · ") +
      (ag.nao_prevista ? `. A previsão para esta hora era de ${num(ag.prevista_mm || 0, 1)} mm.` : ".");
    if (co.efeito) alerta += ` Antes da chuva (às ${hh(co.efeito.emitida)}) o modelo previa <b>${num(co.efeito.previsto, 0)} µg/m³</b> para agora; a mediana observada é <b>${num(co.efeito.observado, 0)}</b> (diferença ${co.efeito.dif > 0 ? "+" : ""}${num(co.efeito.dif, 0)}, que inclui o erro normal do modelo).`;
    alerta += `</div>`;
  } else if (lav.recente) {
    alerta = `<div class="chuva-alerta" role="status"><b>Choveu há ${lav.horas_desde} h</b>${lav.nao_prevista_recente ? " (não prevista)" : ""}. O ar pode piorar de novo à medida que a fumaça regional volta.</div>`;
  }
  // faixa: 24 h passadas (prevista na época x observada) e 24 h futuras (prevista)
  const W = 360, H = 64, mL = 62, cel = (W - mL) / 48;
  const reg = Object.fromEntries((co.registro || []).map(r => [new Date(r.t).getTime(), r]));
  const prev = Object.fromEntries((d.meteo.previsao || []).map(l => [new Date(l.t).getTime(), l.chuva || 0]));
  const mx = Math.max(2, ...Object.values(prev), ...(co.registro || []).map(r => r.prevista_mm || 0));
  let g = "";
  for (let i = 0; i < 48; i++) {
    const t = +h0 + (i - 23) * 3.6e6, x = mL + i * cel;
    const r = reg[t];
    const pmm = t <= +h0 ? (r ? r.prevista_mm || 0 : null) : prev[t] ?? 0;
    if (pmm != null && pmm > 0.05) {
      const hb = Math.max(2, 16 * Math.min(1, pmm / mx));
      g += `<rect x="${x + 0.5}" y="${24 - hb}" width="${cel - 1}" height="${hb}" rx="1" fill="var(--tinta-3)"><title>${hh(new Date(t).toISOString())}: ${num(pmm, 1)} mm previstos</title></rect>`;
    }
    if (t <= +h0) {
      const ev = r && r.evento;
      g += `<rect x="${x + 0.5}" y="32" width="${cel - 1}" height="12" rx="2" fill="${ev ? "var(--chuva)" : "var(--papel-2)"}" ${r ? "" : 'opacity=".5"'} stroke="${r && r.nao_prevista ? "var(--tinta)" : "none"}" stroke-width="1.2"><title>${hh(new Date(t).toISOString())}: ${!r ? "sem registro" : ev ? `chuva observada (${Math.round(r.frac * 100)}% dos pontos${r.nao_prevista ? ", não prevista" : ""})` : "sem chuva observada"}</title></rect>`;
    }
  }
  const xa = mL + 23.5 * cel;
  g += `<line x1="${xa}" x2="${xa}" y1="4" y2="48" stroke="var(--acento)" stroke-width="1.2"/>` +
    `<text x="0" y="22">prevista</text><text x="0" y="42">observada</text>` +
    `<text x="${mL}" y="${H - 4}">−24 h</text><text x="${xa}" y="${H - 4}" text-anchor="middle">agora</text><text x="${W}" y="${H - 4}" text-anchor="end">+24 h</text>`;
  const metar = (co.metar || []).map(m => `<dt>${esc(m.estacao)} ${hh(m.hora)}</dt><dd>${esc(m.texto)}${m.fumaca ? " · fumaça (FU)" : ""}</dd>`).join("");
  el.innerHTML = alerta +
    `<div class="chuva-faixa"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Chuva prevista e observada nas últimas 24 horas e prevista nas próximas 24">${g}</svg></div>` +
    `<p class="nota">Barras cinza: chuva prevista pelo modelo (no passado, a previsão feita uma hora antes). Azul: chuva registrada; contorno escuro = não prevista. Registro horário começa com a coleta.</p>` +
    (metar ? `<dl class="metar-lista">${metar}</dl>` : "");
}

/* Vento em três alturas (agora, +6 h, +12 h), ventilação e ilha de calor */
function desenharPerfilVento(el, d) {
  if (!el) return;
  const pv = d.modelo.perfil_vento || [];
  if (!pv.length) { el.innerHTML = ""; return; }
  const niveis = [
    { rot: "~1.500 m", sub: "850 hPa", v: "v850", d: "d850" },
    { rot: "~800 m", sub: "925 hPa", v: "v925", d: "d925" },
    { rot: "10 m", sub: "superfície", v: "vento", d: "dir" },
  ];
  const seta = (vel, dir) => {
    if (vel == null || dir == null) return `<span class="nota">—</span>`;
    const comp = 10 + Math.min(14, vel * 1.4);
    return `<svg width="34" height="34" viewBox="-17 -17 34 34" aria-hidden="true"><circle r="15" fill="none" stroke="var(--linha)"/>` +
      `<g transform="rotate(${(dir + 180) % 360})"><line x1="0" y1="${comp / 2}" x2="0" y2="${-comp / 2 + 4}" stroke="var(--acento)" stroke-width="2.4"/>` +
      `<path d="M0 ${-comp / 2} L4.5 ${-comp / 2 + 6} L-4.5 ${-comp / 2 + 6} Z" fill="var(--acento)"/></g></svg>` +
      `<span><b>${num(vel, 1)}</b> m/s<br><small>de ${cardeal(dir)}</small></span>`;
  };
  const cab = pv.map((p, i) => `<th>${i === 0 ? "agora" : "+" + (i * 6) + " h"} <small class="nota">${hh(p.t)}</small></th>`).join("");
  const linhas = niveis.map(n => `<tr><th scope="row">${n.rot}<br><small class="nota">${n.sub}</small></th>` +
    pv.map(p => `<td><span class="seta-vento">${seta(p[n.v], p[n.d])}</span></td>`).join("") + `</tr>`).join("");
  const mx = pv.map(p => `<td class="n">${p.blh == null ? "—" : num(p.blh, 0) + " m"}</td>`).join("");
  const mo = d.modelo, il = mo.ilha_calor;
  const vc = mo.ventilacao_agora;
  el.innerHTML = `<h3 class="rotulo">Vento em três alturas</h3>
    <div class="tabela-rolagem"><table class="tabela-s perfil"><thead><tr><th></th>${cab}</tr></thead><tbody>${linhas}
    <tr><th scope="row">camada de mistura</th>${mx}</tr></tbody></table></div>
    <p class="nota">A fumaça de queimadas viaja sobretudo entre 500 e 2.000 m, onde o vento costuma ser mais forte e às vezes vem de outra direção que o da superfície. A fumaça distante é calculada seguindo o vento a ~800 m e, na versão em teste F24U, também a ~1.500 m.` +
    (vc != null ? ` <b>Ventilação agora: ${num(vc, 0)} m²/s (${esc(mo.ventilacao_classe)})</b>, a altura da camada de mistura vezes o vento médio dentro dela; abaixo de ~2.000 m²/s a fumaça que já está na cidade demora a sair.` : "") +
    (il && il.anomalia_c != null ? ` <b>Ilha de calor:</b> os sensores estão ${num(Math.abs(il.anomalia_c), 1)} °C ${il.anomalia_c >= 0 ? "acima" : "abaixo"} do normal desta hora em relação ao modelo; à noite, uma ilha de calor mais forte forma uma cúpula que retém a fumaça sobre a cidade.` : "") + `</p>`;
}

/* Sparkline das próximas 24 h */
function spark(serie, v) {
  const pts = serie.filter(l => l[v.campo] != null);
  if (pts.length < 2) return `<span class="nota">sem previsão</span>`;
  const W = 260, H = 54, padT = 12, padB = 12;
  const vals = pts.map(l => l[v.campo]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (v.tipo === "barra") { lo = 0; hi = Math.max(hi, 2); }
  if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
  const x = i => (i / (pts.length - 1)) * W;
  const y = val => padT + (1 - (val - lo) / (hi - lo)) * (H - padT - padB);
  let marcas;
  if (v.tipo === "barra") {
    const bw = Math.max(2, W / pts.length - 2);
    marcas = pts.map((l, i) => l.chuva > 0 ? `<rect x="${x(i) - bw / 2}" y="${y(l.chuva)}" width="${bw}" height="${Math.max(1, y(0) - y(l.chuva))}" rx="1.5" fill="var(--acento)"><title>${hh(l.t)}: ${num(l.chuva, 1)} mm (${num(l.prob, 0)}%)</title></rect>` : "").join("") +
      `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="var(--linha)"/>`;
  } else {
    const dd = pts.map((l, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(l[v.campo]).toFixed(1)}`).join("");
    marcas = `<path d="${dd}" fill="none" stroke="var(--tinta-2)" stroke-width="2" stroke-linejoin="round"/>` +
      pts.map((l, i) => `<circle cx="${x(i)}" cy="${y(l[v.campo])}" r="6" fill="transparent"><title>${hh(l.t)}: ${num(l[v.campo], v.casas)} ${v.un}</title></circle>`).join("");
  }
  const iMax = vals.indexOf(Math.max(...vals)), iMin = vals.indexOf(Math.min(...vals));
  const cx = i => Math.min(W - 40, Math.max(14, x(i)));
  const rot = v.tipo === "barra" ? ""
    : `<text x="${cx(iMax)}" y="${y(vals[iMax]) - 4}" text-anchor="middle">${num(vals[iMax], v.casas)}</text><text x="${cx(iMin)}" y="${y(vals[iMin]) + 12}" text-anchor="middle">${num(vals[iMin], v.casas)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${v.nome} nas próximas 24 horas">${marcas}${rot}
    <text x="0" y="${H}" >agora</text><text x="${W}" y="${H}" text-anchor="end">+24 h</text></svg>`;
}

/* Gráfico principal: observado (24 h) + previsto (24 h) sobre as faixas de classe */
function desenharGrafico(el, d, h0) {
  const obs = d.historico.map(h => ({ t: new Date(h.t), v: h.mediana }));
  const prv = d.previsao.map(p => ({ t: new Date(p.t), v: p.pm, lo: p.lo, hi: p.hi, c: p.classe, m24: p.media24, c24: p.classe24, var: p.variantes }));
  if (!obs.length && !prv.length) { el.innerHTML = ""; return; }
  const W = Math.max(320, Math.round(el.clientWidth || 900)), estreito = W < 600, H = estreito ? 200 : 230, mL = 30, mR = estreito ? 84 : 120, mT = 10, mB = 24;
  const t0 = +h0 - 24 * 3.6e6, t1 = +h0 + 24 * 3.6e6;
  // escala logarítmica: 5 µg/m³ no pé, topo pelo maior valor (no mínimo a classe Péssima)
  const vSite = (d.modelo.variantes_no_site || []).filter(n => n !== d.modelo.modelo_publicado);
  const ymin = 5, ymax = Math.max(200, ...obs.map(o => o.v), ...prv.map(p => p.hi),
    ...prv.flatMap(p => vSite.map(n => (p.var || {})[n] || 0))) * 1.15;
  const X = t => mL + (t - t0) / (t1 - t0) * (W - mL - mR);
  const lg = v => Math.log(Math.max(ymin, Math.min(v, ymax)));
  const Y = v => mT + (1 - (lg(v) - Math.log(ymin)) / (Math.log(ymax) - Math.log(ymin))) * (H - mT - mB);
  let s = "";
  // faixas de classe (tinta clara) com nome à direita
  let ant = ymin;
  CLASSES.forEach(c => {
    const topo = c.ate == null ? ymax : Math.min(c.ate, ymax);
    if (ant >= ymax) return;
    s += `<rect x="${mL}" y="${Y(topo)}" width="${W - mL - mR}" height="${Y(ant) - Y(topo)}" fill="${c.cor}" opacity=".13"/>`;
    s += `<rect x="${W - mR + 6}" y="${Y(topo) + 1}" width="4" height="${Math.max(2, Y(ant) - Y(topo) - 2)}" rx="2" fill="${c.cor}"/>`;
    if (Y(ant) - Y(topo) >= 9) s += `<text x="${W - mR + 14}" y="${(Y(topo) + Y(ant)) / 2 + 4}">${esc(estreito ? c.nome.replace("Muito Ruim", "M. Ruim") : c.nome)}</text>`;
    ant = topo;
  });
  // grade horizontal nos limites
  CLASSES.slice(0, -1).forEach(c => { if (c.ate < ymax) s += `<line x1="${mL}" x2="${W - mR}" y1="${Y(c.ate)}" y2="${Y(c.ate)}" stroke="var(--linha)"/><text x="${mL - 5}" y="${Y(c.ate) + 4}" text-anchor="end">${c.ate}</text>`; });
  [300, 500, 1000].filter(v => v < ymax * 0.9).forEach(v => { s += `<line x1="${mL}" x2="${W - mR}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--linha)" stroke-dasharray="2 4"/><text x="${mL - 5}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`; });
  s += `<text x="${mL - 5}" y="${Y(ymin) + 4}" text-anchor="end">${ymin}</text>`;
  s += `<text x="${mL + 4}" y="${mT + 10}" style="fill:var(--tinta-3);font-size:10px">escala logarítmica</text>`;
  // eixo de tempo a cada 6 h
  for (let t = t0; t <= t1; t += (estreito ? 12 : 6) * 3.6e6) {
    s += `<text x="${X(t)}" y="${H - 6}" text-anchor="middle">${hh(new Date(t).toISOString())}</text>`;
  }
  // faixa de incerteza e linhas
  if (prv.length) {
    const banda = prv.map(p => `${X(+p.t)},${Y(p.hi)}`).join(" ") + " " + [...prv].reverse().map(p => `${X(+p.t)},${Y(p.lo)}`).join(" ");
    s += `<polygon points="${X(+h0)},${Y(prv[0].v)} ${banda}" fill="var(--tinta)" opacity=".10"/>`;
  }
  const o = obs.filter(p => +p.t >= t0);
  if (o.length) s += `<path d="${o.map((p, i) => `${i ? "L" : "M"}${X(+p.t).toFixed(1)} ${Y(p.v).toFixed(1)}`).join("")}" fill="none" stroke="var(--tinta)" stroke-width="2" stroke-linejoin="round"/>`;
  const ultimoObs = o.length ? o[o.length - 1] : null;
  const pp = (ultimoObs ? [ultimoObs] : []).concat(prv);
  if (pp.length > 1) s += `<path d="${pp.map((p, i) => `${i ? "L" : "M"}${X(+p.t).toFixed(1)} ${Y(p.v).toFixed(1)}`).join("")}" fill="none" stroke="var(--tinta)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>`;
  // chuva: observada (horas passadas) e prevista (próximas horas), marcas no pé do gráfico
  const reg = ((d.chuva_obs || {}).registro || []).filter(r => r.evento);
  const largura = (W - mL - mR) / 48;
  reg.forEach(r => {
    const x = X(+new Date(r.t)) - largura / 2;
    s += `<rect x="${x}" y="${Y(ymin) - 7}" width="${Math.max(2, largura - 1)}" height="7" rx="1.5" fill="var(--chuva)"><title>${hh(r.t)}: chuva observada${r.nao_prevista ? " (não prevista)" : ""}</title></rect>`;
  });
  d.previsao.forEach(p => {
    const mm = p.chuva_acum_mm - (d.previsao.find(q => q.h === p.h - 1)?.chuva_acum_mm || 0);
    if (mm >= 0.2) s += `<rect x="${X(+new Date(p.t)) - largura / 2}" y="${Y(ymin) - 7}" width="${Math.max(2, largura - 1)}" height="7" rx="1.5" fill="var(--chuva)" opacity=".4"><title>${hh(p.t)}: ${num(mm, 1)} mm previstos</title></rect>`;
  });
  if (reg.length || d.previsao.some(p => p.chuva_acum_mm > 0)) s += `<text x="${mL + 4}" y="${Y(ymin) - 10}" style="fill:var(--chuva)">chuva</text>`;
  // variantes em teste (linhas finas, rótulo no fim)
  const pub = d.modelo.modelo_publicado;
  const disp = d.previsao.length && d.previsao[0].variantes ? Object.keys(d.previsao[0].variantes) : [];
  const nomesV = (d.modelo.variantes_no_site || d.modelo.variantes_no_grafico || disp).filter(n => n !== pub && disp.includes(n));
  const rotulos = [];
  nomesV.forEach((n, k) => {
    const pts = (ultimoObs ? [{ t: ultimoObs.t, v: ultimoObs.v }] : []).concat(d.previsao.map(p => ({ t: new Date(p.t), v: p.variantes[n] })));
    const cams = n === "CAMS", cor = cams ? "#4f6fb8" : "var(--tinta-3)";
    s += `<path d="${pts.map((p, i) => `${i ? "L" : "M"}${X(+p.t).toFixed(1)} ${Y(p.v).toFixed(1)}`).join("")}" fill="none" stroke="${cor}" stroke-width="${cams ? 1.8 : 1.2}" stroke-dasharray="${cams ? "6 3" : ["3 3", "1 3", "7 3"][k % 3]}"><title>${cams ? "CAMS (Copernicus) ajustado ao medido" : "variante em teste: " + esc(n)}</title></path>`;
    const ult = pts[pts.length - 1];
    rotulos.push({ n: cams ? n : `${n} (teste)`, x: X(+ult.t) - 4, y: Y(ult.v) - 5, cor });
  });
  // rótulo da linha publicada, para não confundir com as variantes em teste
  if (prv.length) { const u = prv[prv.length - 1]; rotulos.push({ n: `${pub} (publicada)`, x: X(+u.t) - 4, y: Y(u.v) - 5, cor: "var(--tinta)" }); }
  // rótulos no fim das linhas, afastados para não se sobreporem
  rotulos.sort((a, b) => a.y - b.y);
  rotulos.forEach((r, i) => { if (i && r.y - rotulos[i - 1].y < 11) r.y = rotulos[i - 1].y + 11; r.y = Math.max(mT + 22, r.y); });
  rotulos.forEach(r => { s += `<text x="${r.x}" y="${r.y}" text-anchor="end" style="fill:${r.cor || "var(--tinta-3)"};font-size:10px;font-weight:600">${esc(r.n)}</text>`; });
  // agora
  s += `<line x1="${X(+h0)}" x2="${X(+h0)}" y1="${mT}" y2="${H - mB}" stroke="var(--acento)" stroke-width="1.5"/>`;
  s += `<text x="${X(+h0) - 6}" y="${mT + 10}" text-anchor="end">observado</text><text x="${X(+h0) + 6}" y="${mT + 10}">previsto</text>`;
  if (ultimoObs) s += `<circle cx="${X(+ultimoObs.t)}" cy="${Y(ultimoObs.v)}" r="5" fill="${corClasse(d.atual.classe)}" stroke="var(--papel)" stroke-width="2"/>`;
  s += `<line id="gx" y1="${mT}" y2="${H - mB}" stroke="var(--tinta-3)" stroke-width="1" opacity="0"/><circle id="gp" r="5" fill="var(--papel)" stroke="var(--tinta)" stroke-width="2" opacity="0"/>`;
  s += `<rect id="gh" x="${mL}" y="${mT}" width="${W - mL - mR}" height="${H - mT - mB}" fill="transparent"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${s}</svg><div class="dica" hidden></div>`;

  // camada de interação: cruzeta + dica
  const svg = el.querySelector("svg"), dica = el.querySelector(".dica"), gx = svg.querySelector("#gx"), gp = svg.querySelector("#gp");
  const todos = obs.filter(p => +p.t >= t0).map(p => ({ ...p, tipo: "obs" })).concat(prv.map(p => ({ ...p, tipo: "prev" })));
  const mover = ev => {
    const r = svg.getBoundingClientRect();
    const xv = (ev.clientX - r.left) / r.width * W;
    const alvo = todos.reduce((a, p) => Math.abs(X(+p.t) - xv) < Math.abs(X(+a.t) - xv) ? p : a, todos[0]);
    gx.setAttribute("x1", X(+alvo.t)); gx.setAttribute("x2", X(+alvo.t)); gx.setAttribute("opacity", 1);
    gp.setAttribute("cx", X(+alvo.t)); gp.setAttribute("cy", Y(alvo.v)); gp.setAttribute("opacity", 1);
    const c = classe(alvo.tipo === "prev" ? alvo.c : null) || CLASSES.find(k => k.ate == null || alvo.v <= k.ate);
    dica.innerHTML = `<b>${horaLocal(alvo.t.toISOString())}</b> · ${alvo.tipo === "prev" ? "previsto" : "observado"}<br>` +
      `${num(alvo.v, 0)} µg/m³ · ${esc(c.nome)}` + (alvo.tipo === "prev" ? `<br>faixa ${num(alvo.lo, 0)}–${num(alvo.hi, 0)} · média 24 h ${num(alvo.m24, 0)}` +
      (alvo.var ? `<br><span style="color:var(--tinta-3)">em teste: ${Object.entries(alvo.var).filter(([n]) => n !== d.modelo.modelo_publicado && (d.modelo.variantes_no_site || []).includes(n)).map(([n, v]) => `${esc(n)} ${num(v, 0)}`).join(" · ")}</span>` : "") : "");
    dica.style.left = (X(+alvo.t) / W * r.width) + "px"; dica.style.top = (Y(alvo.v) / H * r.height - 10) + "px"; dica.hidden = false;
  };
  const sair = () => { dica.hidden = true; gx.setAttribute("opacity", 0); gp.setAttribute("opacity", 0); };
  svg.querySelector("#gh").addEventListener("pointermove", mover);
  svg.querySelector("#gh").addEventListener("pointerleave", sair);
}

/* Mapa: buffers coloridos pela classe em cada estação, NAMA como centro, anéis e focos do entorno */
function montarMapa(d, focos, limites) {
  const mapa = L.map("mapa", { zoomControl: true, minZoom: 5 });
  const ruas = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(mapa);
  const img = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 18, attribution: "Imagem © Esri" });

  const gSens = L.layerGroup().addTo(mapa), gReg = L.layerGroup().addTo(mapa), gFocos = L.layerGroup().addTo(mapa);
  const nama = d.nama;

  // buffers: três anéis (500 m, 1 km, 1,5 km) com opacidade decrescente
  const RAIOS = [1500, 1000, 500], OPAC = [0.16, 0.2, 0.32];
  const lim = [];
  d.sensores.forEach(s => {
    if (s.lat == null) return;
    if (!s.entorno) lim.push([s.lat, s.lon]);
    const cor = s.valido ? corClasse(s.classe) : "#8d968f";
    if (s.sinal_chuva) L.circle([s.lat, s.lon], { radius: 2200, color: "var(--chuva)", weight: 2, dashArray: "3 5", fill: false, interactive: false }).addTo(gSens);
    RAIOS.forEach((r, i) => L.circle([s.lat, s.lon], {
      radius: r, stroke: i === 0, color: cor, weight: s.nama ? 2.5 : 1.2, opacity: .9, dashArray: s.valido && !s.entorno ? null : "4 4",
      fillColor: cor, fillOpacity: s.valido ? OPAC[i] : 0.06, interactive: i === 2,
    }).addTo(gSens));
    const popup = `<div class="pop"><h3>${esc(s.nome)}${s.nama ? " ★" : ""}</h3>${s.valido ? seloClasse(s.classe) : `<span class="selo vazio">descartado</span>`}
      <dl><dt>PM2,5 corrigido</dt><dd>${s.valido ? num(s.pm, 1, " µg/m³") : "—"}</dd>
      <dt>Canais A / B (cf_1)</dt><dd>${num(s.a, 1)} / ${num(s.b, 1)}</dd>
      <dt>Umidade (sensor)</dt><dd>${num(s.ur, 0, "%")}</dd>
      <dt>Dist. de ${esc(window.__centro || "centro")}</dt><dd>${num(s.dist_nama_km, 1, " km")}</dd>
      ${s.entorno ? `<dt>Estação do entorno</dt><dd>${esc(s.entorno)} · fora da mediana da cidade</dd>` : ""}
      <dt>Última leitura</dt><dd>${horaLocal(s.visto)}</dd>
      ${s.motivo ? `<dt>Observação</dt><dd>${esc(s.motivo)}</dd>` : ""}
      ${s.sinal_chuva ? `<dt>Sinal de chuva</dt><dd>${s.sinal_chuva.nivel === "provavel" ? "provável" : "possível"} na última hora: ${num(s.sinal_chuva.dT, 1)} °C e ${s.sinal_chuva.dUR > 0 ? "+" : ""}${num(s.sinal_chuva.dUR, 0)} pontos de umidade além do esperado${s.sinal_chuva.dPM != null ? `, PM2,5 ${num(s.sinal_chuva.dPM, 0)}%` : ""}</dd>` : ""}</dl></div>`;
    L.marker([s.lat, s.lon], {
      icon: L.divIcon({ className: "rotulo-sensor" + (s.nama ? " rotulo-nama" : "") + (s.sinal_chuva ? " chuva" : ""), html: `<span>${s.nama ? "★ " : ""}${s.valido ? num(s.pm, 0) : "×"}</span>`, iconSize: null }),
      title: s.nome,
    }).bindPopup(popup).addTo(gSens);
  });
  if (!d.sensores.some(s => s.nama)) {
    L.marker([nama.lat, nama.lon], { icon: L.divIcon({ className: "rotulo-sensor rotulo-nama", html: `<span>${esc(nama.nome)} (${/última/.test(nama.origem || "") ? "sem dados" : "posição aproximada"})</span>`, iconSize: null }) }).addTo(gSens);
  }

  // aeroportos (METAR)
  ((d.chuva_obs || {}).metar || []).forEach(m => {
    L.marker([m.lat, m.lon], { icon: L.divIcon({ className: "rotulo-metar", html: `<span>${esc(m.estacao)}${m.mm > 0 ? " · chuva" : m.classe === "vizinhanca" ? " · VCSH" : ""}</span>`, iconSize: null }) })
      .bindPopup(`<div class="pop"><h3>${esc(m.nome)} (${esc(m.estacao)})</h3><dl><dt>Boletim</dt><dd>${horaLocal(m.hora)}</dd><dt>Tempo presente</dt><dd>${esc(m.texto)}${m.fumaca ? " · fumaça (FU)" : ""}</dd><dt>Visibilidade</dt><dd>${esc(m.visibilidade ?? "—")}</dd><dt>METAR</dt><dd class="mono">${esc(m.bruto)}</dd></dl></div>`)
      .addTo(gSens);
  });

  // anéis de distância do IFB, centrados na NAMA
  d.focos.aneis_km.forEach(([, b]) => {
    L.circle([nama.lat, nama.lon], { radius: b * 1000, color: "#ffffff", weight: 1.5, dashArray: "6 6", fill: false, interactive: false }).addTo(gReg);
    L.marker([nama.lat + b / 111.2, nama.lon], { interactive: false, icon: L.divIcon({ className: "rotulo-anel", html: `<span>${b} km de ${esc(nama.nome)}</span>`, iconSize: null }) }).addTo(gReg);
  });
  if (limites) {
    L.geoJSON(limites, { style: { color: "#ffffff", weight: 1.2, opacity: .8, fill: false }, interactive: false }).addTo(gReg);
    limites.features.forEach(f => {
      if (!f.properties.rotulo) return;
      L.marker([f.properties.rotulo[1], f.properties.rotulo[0]], { interactive: false, icon: L.divIcon({ className: "nome-municipio", html: `<span>${esc(f.properties.nome)}</span>`, iconSize: null }) }).addTo(gReg);
    });
  }

  // vento na NAMA: rosa simples num controle fixo (seta aponta para onde o vento vai)
  const v = d.meteo.agora;
  if (v && v.dir != null) {
    const ctl = L.control({ position: "topleft" });
    ctl.onAdd = () => {
      const div = L.DomUtil.create("div", "legenda vento");
      div.innerHTML = `<svg width="56" height="56" viewBox="-28 -28 56 56" aria-hidden="true"><circle r="25" fill="none" stroke="var(--linha)"/><text y="-17" text-anchor="middle" font-size="9" fill="var(--tinta-3)">N</text><g transform="rotate(${(v.dir + 180) % 360})"><path d="M0 -19 L7 -5 L2 -5 L2 17 L-2 17 L-2 -5 L-7 -5 Z" fill="var(--acento)"/></g></svg><span>Vento a 10 m: ${num(v.vento, 1)} m/s, de ${cardeal(v.dir)}${d.modelo.setor_agora ? `<br>Transporte da fumaça: de ${cardeal(d.modelo.setor_agora.dir)}` : ""}</span>`;
      return div;
    };
    ctl.addTo(mapa);
  }

  // setor de onde vem a fumaça no horizonte escolhido
  const gSetor = L.layerGroup().addTo(mapa);
  // retrotrajetória: caminho do ar que chega agora à NAMA (vento a 925 hPa)
  const gTraj = L.layerGroup();
  const traj = d.modelo.regional?.trajetoria || [];
  if (traj.length > 1) {
    L.polyline(traj.map(p => [p[0], p[1]]), { color: "#f2b35e", weight: 2.5, opacity: .9, interactive: false }).addTo(gTraj);
    traj.filter(p => p[2] > 0 && p[2] % 12 === 0).forEach(p =>
      L.marker([p[0], p[1]], { interactive: false, icon: L.divIcon({ className: "rotulo-anel", html: `<span>há ${p[2]} h</span>`, iconSize: null }) }).addTo(gTraj));
  }
  function destino(lat, lon, rumo, km) {
    const R = 6371, d_ = km / R, b = rumo * Math.PI / 180, p1 = lat * Math.PI / 180, l1 = lon * Math.PI / 180;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(d_) + Math.cos(p1) * Math.sin(d_) * Math.cos(b));
    const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d_) * Math.cos(p1), Math.cos(d_) - Math.sin(p1) * Math.sin(p2));
    return [p2 * 180 / Math.PI, l2 * 180 / Math.PI];
  }
  function desenharSetor(st) {
    gSetor.clearLayers();
    if (!st) return;
    if (st.calmaria) {
      L.circle([nama.lat, nama.lon], { radius: 20000, color: "#7fd3dc", weight: 2, dashArray: "4 4", fillColor: "#7fd3dc", fillOpacity: .12, interactive: false }).addTo(gSetor);
      return;
    }
    const pts = [[nama.lat, nama.lon]];
    for (let a = st.dir - st.sigma; a <= st.dir + st.sigma + 0.1; a += 4) pts.push(destino(nama.lat, nama.lon, a, 300));
    L.polygon(pts, { color: "#7fd3dc", weight: 2, fillColor: "#7fd3dc", fillOpacity: .14, interactive: false }).addTo(gSetor);
    L.polyline([[nama.lat, nama.lon], destino(nama.lat, nama.lon, st.dir, 300)], { color: "#7fd3dc", weight: 1.5, dashArray: "2 6", interactive: false }).addTo(gSetor);
    L.marker(destino(nama.lat, nama.lon, st.dir, 255), { interactive: false, icon: L.divIcon({ className: "rotulo-setor", iconSize: null,
      html: `<span>a fumaça vem daqui<br>vento de ${cardeal(st.dir)} · ±${st.sigma}°</span>` }) }).addTo(gSetor);
  }

  // focos
  const marcadoresFoco = [];
  focos.features.forEach(f => {
    const p = f.properties, [lon, lat] = f.geometry.coordinates;
    const ativo = p.categoria === "ativo";
    const cor = ativo ? "#e2361f" : "#9b8f86";
    const m = L.circleMarker([lat, lon], {
      radius: p.provavel_incendio ? 7 : 4, color: p.provavel_incendio ? "#ffd166" : "#1a1a1a", weight: p.provavel_incendio ? 2.5 : 1,
      fillColor: cor, fillOpacity: .9,
    });
    m.bindPopup(`<div class="pop"><h3>${esc(p.municipio)}</h3><dl>
      <dt>Situação</dt><dd>${ativo ? "ativo" : "recém-extinto (estimado)"}${p.provavel_incendio ? " · provável incêndio" : ""}</dd>
      <dt>Distância de ${esc(nama.nome)}</dt><dd>${num(p.dist_km, 0, " km")} a ${cardeal(p.rumo)}</dd>
      <dt>Última detecção</dt><dd>${horaLocal(p.ultima_deteccao)}</dd>
      <dt>Duração</dt><dd>${num(p.duracao_h, 0, " h")}</dd>
      <dt>Pixels · FRP máx.</dt><dd>${num(p.n_pixels, 0)} · ${num(p.frp_max, 0, " MW")}</dd>
      ${p.painel_fogo ? `<dt>Painel do Fogo</dt><dd>evento ${esc(p.painel_fogo.id_evento)}: ${num(p.painel_fogo.area_km2, 1, " km²")}, ativo há ${num(p.painel_fogo.persistencia_dias, 0)} dia(s), ${num(p.painel_fogo.deteccoes, 0)} detecções · peso ×${num(p.mult_painel, 1)}</dd>` : ""}
      ${p.goes_painel ? `<dt>Alerta GOES</dt><dd>${num(p.goes_painel.potencia_mw, 0)} MW até ${horaLocal(p.goes_painel.ate)}</dd>` : ""}
      <dt>Peso no índice</dt><dd>${Object.keys(p.influencia || {}).length ? Object.entries(p.influencia).map(([h, c]) => `${h === "0" ? "agora" : "+" + h + " h"}: ${num(c, 2)}`).join(" · ") : "fora do vento em todos os horizontes"}</dd></dl></div>`);
    m.addTo(gFocos);
    marcadoresFoco.push([m, p]);
  });
  document.addEventListener("horizonte", ev => {
    const x = ev.detail;
    desenharSetor(x.setor);
    const mx = Math.max(1e-9, ...marcadoresFoco.map(([, p]) => (p.influencia || {})[String(x.h)] || 0));
    marcadoresFoco.forEach(([m, p]) => {
      const c = (p.influencia || {})[String(x.h)] || 0;
      m.setStyle({ fillOpacity: c > 0 ? 0.45 + 0.5 * Math.sqrt(c / mx) : 0.18, opacity: c > 0 ? 1 : 0.35 });
      m.setRadius((p.provavel_incendio ? 7 : 4) + (c > 0 ? 4 * Math.sqrt(c / mx) : 0));
    });
  });

  L.control.layers({ "Mapa de ruas": ruas, "Imagem de satélite": img },
    { "Estações (buffers)": gSens, "Anéis e limites": gReg, "Focos do entorno": gFocos, "Setor do vento": gSetor }, { collapsed: true }).addTo(mapa);

  const leg = L.control({ position: "bottomright" });
  leg.onAdd = () => {
    const div = L.DomUtil.create("div", "legenda");
    const aberta = !window.matchMedia("(max-width: 900px)").matches;
    div.innerHTML = `<details${aberta ? " open" : ""}><summary>Legenda</summary>
      <div class="rotulo">Buffer de 1,5 km em cada estação</div>
      ${CLASSES.map(c => `<div class="linha"><i style="background:${c.cor}"></i>${esc(c.nome)}</div>`).join("")}
      <div class="linha"><i style="background:#8d968f;opacity:.5"></i>descartada no controle de qualidade</div>
      <div class="rotulo">Focos (${esc((d.focos.fonte || {}).nome || "MonitorBETA")})</div>
      <div class="linha"><i style="background:#e2361f;width:10px;height:10px"></i>ativo</div>
      <div class="linha"><i style="background:#9b8f86;width:10px;height:10px"></i>recém-extinto</div>
      <div class="linha"><i style="background:#e2361f;box-shadow:0 0 0 2.5px #ffd166"></i>provável incêndio</div>
      <div class="linha"><i style="background:transparent;border:2px dashed var(--chuva)"></i>sinal de chuva na última hora</div>
      <div class="linha"><i style="background:var(--tinta);border-radius:2px;width:22px;height:10px"></i>aeroporto (boletim METAR)</div>
      <div class="linha"><i style="background:#7fd3dc;opacity:.6;border-radius:2px"></i>setor de onde vem a fumaça</div>
      ${traj.length > 1 ? `<div class="linha"><i style="background:#f2b35e;height:3px;border-radius:2px"></i>caminho do ar que chega agora (60 h, vento a 925 hPa)</div>` : ""}
      <div class="linha">foco apagado = fora do vento no horizonte escolhido</div>
      <div class="linha">— — anéis de 50, 150 e 300 km de ${esc(nama.nome)}</div></details>`;
    L.DomEvent.disableClickPropagation(div);
    return div;
  };
  leg.addTo(mapa);

  const bCid = document.getElementById("ver-cidade"), bReg = document.getElementById("ver-regiao");
  const verCidade = () => {
    if (lim.length > 1) mapa.fitBounds(L.latLngBounds(lim).pad(0.12)); else mapa.setView([nama.lat, nama.lon], 11);
    if (mapa.hasLayer(img)) { mapa.removeLayer(img); ruas.addTo(mapa); }
    if (mapa.hasLayer(gSetor)) mapa.removeLayer(gSetor);
    if (mapa.hasLayer(gTraj)) mapa.removeLayer(gTraj);
    bCid.setAttribute("aria-pressed", "true"); bReg.setAttribute("aria-pressed", "false");
  };
  const verRegiao = () => {
    const b = L.latLng(nama.lat, nama.lon).toBounds(330000);
    traj.filter(p => p[2] <= 24).forEach(p => b.extend([p[0], p[1]]));
    mapa.fitBounds(b);
    if (mapa.hasLayer(ruas)) { mapa.removeLayer(ruas); img.addTo(mapa); }
    if (!mapa.hasLayer(gSetor)) gSetor.addTo(mapa);
    if (!mapa.hasLayer(gTraj)) gTraj.addTo(mapa);
    bCid.setAttribute("aria-pressed", "false"); bReg.setAttribute("aria-pressed", "true");
  };
  bCid.addEventListener("click", verCidade); bReg.addEventListener("click", verRegiao);
  verCidade();
}
