/**
 * QUALIAR-UFAM · disparo horário da coleta pelo Google Apps Script
 *
 * O agendamento do próprio GitHub atrasa ou pula execuções em repositórios
 * com pouca atividade. Este script pede ao GitHub, a cada hora, que rode o
 * workflow da coleta (evento workflow_dispatch). Se a hora já tiver sido
 * coletada, o coletor percebe e não gasta pontos da PurpleAir.
 *
 * Também confere a idade dos dados publicados no site e manda um e-mail
 * para a conta dona do script se eles ficarem mais de 3 horas sem atualizar.
 *
 * Instalação (passo a passo no README do repositório):
 *   1. Cole este código em script.google.com (novo projeto).
 *   2. Em Configurações do projeto > Propriedades do script, crie a
 *      propriedade GITHUB_TOKEN com o token de acesso do GitHub.
 *   3. Rode a função instalar() uma vez e autorize.
 */

const CONFIG = {
  repositorio: 'UFAMCCA/qualiar_BETA',
  workflow: 'qualiar.yml',
  branch: 'main',
  dadosDoSite: 'https://ufamcca.github.io/qualiar_BETA/data/qualiar.json',
  horasParaAlerta: 3,
  intervaloEntreAlertasHoras: 6,
};

/** Rode uma vez: cria o gatilho de hora em hora e já dispara a primeira coleta. */
function instalar() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'dispararColeta')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('dispararColeta').timeBased().everyHours(1).create();
  dispararColeta();
  console.log('Gatilho criado: dispararColeta roda a cada hora.');
}

/** Chamada pelo gatilho a cada hora. */
function dispararColeta() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    throw new Error('Falta a propriedade GITHUB_TOKEN (Configurações do projeto > Propriedades do script).');
  }
  const url = `https://api.github.com/repos/${CONFIG.repositorio}/actions/workflows/${CONFIG.workflow}/dispatches`;
  const resposta = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ ref: CONFIG.branch }),
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    muteHttpExceptions: true,
  });
  const codigo = resposta.getResponseCode();
  if (codigo === 204) {
    console.log('Coleta disparada às ' + new Date().toLocaleString('pt-BR', { timeZone: 'America/Manaus' }));
  } else {
    // 401: token inválido ou vencido. 403: token sem permissão "Actions: read and write"
    // ou não aprovado pela organização. 404: repositório ou workflow com nome errado.
    console.error(`GitHub respondeu ${codigo}: ${resposta.getContentText()}`);
    alertar(`O GitHub recusou o disparo da coleta (código ${codigo}).\n\n${resposta.getContentText()}\n\n` +
            'Confira o token em Propriedades do script (GITHUB_TOKEN) e as permissões dele.');
  }
  conferirIdadeDosDados();
}

/** Avisa por e-mail se o site está há mais de N horas sem dados novos. */
function conferirIdadeDosDados() {
  try {
    const r = UrlFetchApp.fetch(CONFIG.dadosDoSite + '?t=' + Date.now(), { muteHttpExceptions: true });
    if (r.getResponseCode() !== 200) return;
    const dados = JSON.parse(r.getContentText());
    const horas = (Date.now() - new Date(dados.gerado_em).getTime()) / 3.6e6;
    console.log(`Dados do site gerados há ${horas.toFixed(1)} h.`);
    if (horas > CONFIG.horasParaAlerta) {
      alertar(`Os dados do QUALIAR-UFAM estão há ${horas.toFixed(1)} horas sem atualizar ` +
              `(última coleta: ${dados.gerado_em}).\n\nVeja a aba Actions do repositório ${CONFIG.repositorio}.`);
    }
  } catch (e) {
    console.error('Não foi possível conferir os dados do site: ' + e);
  }
}

function alertar(texto) {
  const props = PropertiesService.getScriptProperties();
  const ultimo = Number(props.getProperty('ULTIMO_ALERTA') || 0);
  if (Date.now() - ultimo < CONFIG.intervaloEntreAlertasHoras * 3.6e6) return;
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), 'QUALIAR-UFAM: coleta com problema', texto);
  props.setProperty('ULTIMO_ALERTA', String(Date.now()));
}


// ================================================================ boletim da Comissão
/*
 * Boletins às 20h30, 02h30, 08h30 e 14h30 (hora de Manaus). O agendamento do GitHub
 * pode atrasar; este gatilho confere a cada 10 minutos e, entre hh:30 e hh:59 de um
 * desses horários, pede ao GitHub que rode o workflow do boletim (uma vez por horário).
 * Rode instalarBoletim() uma vez (o mesmo token GITHUB_TOKEN serve).
 */
const BOLETIM = {
  workflow: 'boletim.yml',
  horas: [20, 2, 8, 14],
  ate: '2026-11-30',          // último dia de boletins
  pagina: 'https://ufamcca.github.io/qualiar_BETA/boletim/',
  // E-mail: destinatários na propriedade do script EMAIL_BOLETIM (separados por vírgula).
  // Sem ela, vai só para a conta dona do script.
  cidadesNoEmail: 'todas',    // ou, por exemplo, 'manaus,itacoatiara'
  idadeMaximaHoras: 3,        // edição mais velha que isto não é enviada
};

function instalarBoletim() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'verificarBoletim')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('verificarBoletim').timeBased().everyMinutes(10).create();
  console.log('Gatilho criado: verificarBoletim roda a cada 10 minutos.');
}

function verificarBoletim() {
  try { enviarBoletimPorEmail(); } catch (e) { console.error('E-mail do boletim: ' + e); }
  // Horário de boletim em andamento: de hh:30 de um horário até hh+1:50 (a coleta da hora
  // cheia pode atrasar; o boletim espera por ela). Dispara a cada 10 min até a edição aparecer.
  const agora = new Date();
  let alvo = null;
  for (const atraso of [0, 60]) {
    const t = new Date(agora.getTime() - atraso * 60000);
    const hora = Number(Utilities.formatDate(t, 'America/Manaus', 'H'));
    const minuto = Number(Utilities.formatDate(agora, 'America/Manaus', 'm'));
    if (BOLETIM.horas.indexOf(hora) < 0) continue;
    if ((atraso === 0 && minuto >= 30) || (atraso === 60 && minuto < 50)) {
      alvo = Utilities.formatDate(t, 'America/Manaus', 'yyyy-MM-dd') + '_' + ('0' + hora).slice(-2) + '30';
      break;
    }
  }
  if (!alvo || alvo.slice(0, 10) > BOLETIM.ate) return;
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty('ULTIMO_BOLETIM') === alvo) return;
  // já publicado? então não dispara mais
  try {
    const p = UrlFetchApp.fetch(BOLETIM.pagina + 'boletins.json?t=' + Date.now(), { muteHttpExceptions: true });
    if (p.getResponseCode() === 200 && JSON.parse(p.getContentText()).edicao === alvo) {
      props.setProperty('ULTIMO_BOLETIM', alvo);
      return;
    }
  } catch (e) { /* segue e dispara */ }
  const token = props.getProperty('GITHUB_TOKEN');
  const url = `https://api.github.com/repos/${CONFIG.repositorio}/actions/workflows/${BOLETIM.workflow}/dispatches`;
  const r = UrlFetchApp.fetch(url, {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify({ ref: CONFIG.branch }),
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
    muteHttpExceptions: true,
  });
  if (r.getResponseCode() === 204) {
    console.log('Boletim disparado (aguardando publicação): ' + alvo);
  } else {
    console.error(`GitHub respondeu ${r.getResponseCode()}: ${r.getContentText()}`);
    alertar(`O GitHub recusou o disparo do boletim (código ${r.getResponseCode()}).\n\n${r.getContentText()}`);
  }
}


/** Manda por e-mail a edição mais recente do boletim, uma vez por edição (chamada por verificarBoletim). */
function enviarBoletimPorEmail(forcar) {
  const r = UrlFetchApp.fetch(BOLETIM.pagina + 'boletins.json?t=' + Date.now(), { muteHttpExceptions: true });
  if (r.getResponseCode() !== 200) return;
  const b = JSON.parse(r.getContentText());
  if (!b.edicao) return;
  const props = PropertiesService.getScriptProperties();
  if (!forcar && props.getProperty('ULTIMO_EMAIL_BOLETIM') === b.edicao) return;
  const idade = (Date.now() - new Date(b.emitido_em).getTime()) / 3.6e6;
  if (!forcar && idade > BOLETIM.idadeMaximaHoras) { props.setProperty('ULTIMO_EMAIL_BOLETIM', b.edicao); return; }

  const escolha = BOLETIM.cidadesNoEmail;
  const cartoes = (b.cartoes || []).filter(c => b.imagens && b.imagens[c.id] && (escolha === 'todas' || escolha.split(',').indexOf(c.id) >= 0));
  const inline = {};
  cartoes.forEach(c => {
    const img = UrlFetchApp.fetch(BOLETIM.pagina + b.imagens[c.id], { muteHttpExceptions: true });
    if (img.getResponseCode() === 200) inline['c_' + c.id] = img.getBlob().setName(c.id + '.png');
  });
  const notas = (b.notas || []).filter(n => n.imagem);
  notas.forEach(n => {
    const img = UrlFetchApp.fetch(BOLETIM.pagina + n.imagem, { muteHttpExceptions: true });
    if (img.getResponseCode() === 200) inline['n_' + n.cidade] = img.getBlob().setName('nota-' + n.cidade + '.png');
  });
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const linhas = esc(b.whatsapp).replace(/\*(.+?)\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
  const imgs = cartoes.filter(c => inline['c_' + c.id])
    .map(c => `<p><img src="cid:c_${c.id}" alt="${esc(c.nome)}" style="width:100%;max-width:540px;border-radius:8px"></p>`).join('');
  const blocoNotas = notas.length ? '<h3 style="margin:18px 0 6px">Notas técnicas da Comissão</h3>' + notas.map(n =>
      (inline['n_' + n.cidade] ? `<p><img src="cid:n_${n.cidade}" alt="Nota técnica ${n.numero}/${n.ano}: ${esc(n.nome)}" style="width:100%;max-width:540px;border-radius:8px"></p>` : '') +
      `<p style="white-space:pre-line">${esc(n.texto).replace(/\*(.+?)\*/g, '<b>$1</b>')}</p>`).join('') : '';
  const html = `<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.45;color:#1d2430">${linhas}${blocoNotas}${imgs}` +
    `<p style="color:#5b6473;font-size:13px">Página pública: <a href="${BOLETIM.pagina}">${BOLETIM.pagina}</a></p></div>`;
  const para = props.getProperty('EMAIL_BOLETIM') || Session.getEffectiveUser().getEmail();
  const assunto = (notas.length ? 'NOTA TÉCNICA + ' : '') + 'Boletim da qualidade do ar · ' + (b.arquivo && b.arquivo[0] ? b.arquivo[0].data : b.edicao);
  MailApp.sendEmail({ to: para, subject: assunto, body: b.whatsapp, htmlBody: html, inlineImages: inline, name: 'Comissão de Qualidade do Ar da UFAM' });
  props.setProperty('ULTIMO_EMAIL_BOLETIM', b.edicao);
  console.log('Boletim ' + b.edicao + ' enviado por e-mail para ' + para);
}

/** Para testar: manda a última edição por e-mail agora, mesmo que já tenha sido enviada. */
function testarEmailBoletim() { enviarBoletimPorEmail(true); }
