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
