# QUALIAR-UFAM · Qualidade do ar em Manaus, agora e nas próximas 24 horas

Site estático (GitHub Pages) do CCA UFAM. Mostra a qualidade do ar medida pelas estações PurpleAir de Manaus, em quatro classes alinhadas ao IQAr/CONAMA 506/2024, e a previsão hora a hora para as próximas 24 horas. Os focos de calor vêm do [MonitorBETA](https://ufamcca.github.io/MonitorBETA/), lidos do JSON que ele já publica.

## Fontes e custo

| Dado | Fonte | Custo de acesso |
|---|---|---|
| PM2,5, umidade e temperatura dos sensores | API da PurpleAir, uma chamada por hora para todos os sensores da área urbana | Chave gratuita; a leitura consome "pontos" da conta. Uma chamada horária com 9 campos é o modo mais barato. O histórico horário (`--semear`) faz uma chamada por sensor e deve ser usado só na primeira vez |
| Temperatura, umidade, chuva e vento observados e previstos | [Open-Meteo](https://open-meteo.com), no ponto da estação NAMA | Gratuito, sem chave, para uso não comercial |
| Chuva observada | METAR dos aeroportos SBEG e SBMN ([aviationweather.gov](https://aviationweather.gov/data/api/)) e assinatura de chuva nos sensores PurpleAir; pluviômetro do INMET opcional | METAR e sensores: gratuito, sem chave. INMET: token pedido ao INMET, cadastrado como `INMET_TOKEN` (leitor não testado aqui) |
| Focos ativos, recém-extintos e limites municipais | MonitorBETA (INPE BDQueimadas e NASA FIRMS) | Gratuito; já é coletado pelo grupo |

## Publicar (uma vez)

1. Crie um repositório e envie o conteúdo desta pasta para a branch `main`, incluindo a pasta oculta `.github`.
2. Em **Settings → Secrets and variables → Actions**, cadastre a chave de leitura da PurpleAir como `PURPLEAIR_API_KEY`.Caso haja token do INMET, cadastre-o como `INMET_TOKEN`; sem ele, a coleta funciona e só pula o pluviômetro.
3. Em **Settings → Actions → General → Workflow permissions**, marque *Read and write permissions* (a coleta grava os dados no próprio repositório).
4. Em **Settings → Pages**, escolha *Deploy from a branch*, `main`, pasta `/docs`. O site fica em `https://ufamcca.github.io/QUALIAR_BETA/`.
5. Em **Actions → QUALIAR-UFAM (a cada hora) → Run workflow**, marque *semear* na primeira execução. Ela baixa as últimas 24 h de médias horárias de cada sensor, para o site já abrir com tendência e média de 24 h. Depois a coleta roda sozinha no minuto 12 de cada hora.
6. Confira o resultado: o topo do site mostra o estado de cada fonte (PurpleAir, Open-Meteo, METAR, MonitorBETA, INMET). Até a primeira coleta, a página avisa que ainda não há dados.

## Estação MIT_NAMA_UFAM

A estação PurpleAir MIT_NAMA_UFAM é o centro para distâncias e direções até os focos, os anéis de 50, 150 e 300 km e o ponto da meteorologia. O mapa da PurpleAir não mostra o número do sensor, mas a API devolve nome, número e posição de cada sensor na mesma resposta. O coletor procura o nome exato `MIT_NAMA_UFAM` (definido em `NAMA_NOME`, `scripts/config.py`) e guarda o número e a posição em `docs/data/historico.json`. Se numa hora o sensor não enviar dados, usa a última posição conhecida; só sem nenhum registro usa as coordenadas aproximadas do campus (`NAMA_LAT_PADRAO`, `NAMA_LON_PADRAO`). O site mostra um aviso nos dois casos. O número encontrado aparece no topo do método, no site, e em `docs/data/qualiar.json` (campo `nama.id`).

Se o sensor for privado na PurpleAir, a chave de leitura não o enxerga; nesse caso é preciso que o dono o torne público ou compartilhe a chave de leitura dele.

## O que roda a cada hora

1. **PM2,5.** Lê os canais A e B (cf_1) de cada sensor externo, descarta os que divergem mais de 5 µg/m³ e 70% (critério EPA) e aplica a correção da EPA com a extensão para fumaça extrema (Barkjohn et al., 2021 e 2022). O valor da cidade é a mediana das estações válidas. A tendência é a variação média por hora nas últimas 3 h.
2. **Tempo.** Temperatura, umidade, chuva, chance de chuva e vento para as próximas 72 h; dias sem chuva (dias locais com menos de 1 mm) e chuva acumulada em 7 e 30 dias.
3. **Focos.** Por município: ativos, recém-extintos (extinção estimada há até 12 h) e prováveis incêndios (foco ativo há 24 h ou mais, ou com 10 pixels ou mais, ou com FRP de 100 MW ou mais). Distância e rumo de cada foco medidos a partir da NAMA.
4. **Índice de fogo a barlavento (IFB).** Para cada foco e cada hora-alvo:
   - **Vento de transporte**: média vetorial de 30% do vento a 10 m e 70% do vento a 925 hPa (~800 m), porque a fumaça amazônica viaja sobretudo entre 600 e 1100 m.
   - **Tempo de viagem**: distância ÷ velocidade média do vento no trajeto. A fumaça que chega em t+h saiu do foco em t+h−T; o foco só conta se estava queimando nesse instante (focos já apagados ainda contam se a fumaça deles está a caminho; emissão futura decai em 8 h, ou 24 h para prováveis incêndios).
   - **Direção**: núcleo gaussiano no ângulo entre o rumo do foco (visto da NAMA) e a direção de onde vem o vento médio do trajeto. A largura vai de ±40° (vento de 1 m/s) a ±15° (5 m/s ou mais) e alarga quando o vento muda de direção no trajeto.
   - **Calmaria** (vento médio resultante < 1 m/s): sem direção; só focos a até ~20 km pesam.
   - **Intensidade**: FRP (ou número de pixels), descontada a fração injetada acima da camada limite (5% a 35%, crescendo com o FRP).
   - **Diluição e remoção**: `exp(−d/75 km)`, fator 1/U limitado a 0,5–2 e remoção pela chuva caída durante o trajeto.
   - `python scripts/cenarios.py` mostra o peso de cada município sob vento de N, NE, L, SE, S e calmaria, com os focos de uma rodada real do MonitorBETA.
5. **Chuva observada.** A "chuva passada" do Open-Meteo é saída de modelo, não medição, e pancadas de bairro escapam dos modelos globais. A cada hora o coletor registra a chuva que de fato caiu:
   - **Assinatura nos sensores:** temperatura 1,5 °C abaixo e umidade 7 pontos acima do que o ciclo diário previsto explica, em relação à hora anterior (provável), ou um desses sinais com queda de 20% do PM2,5 (possível).
   - **METAR:** chuva fraca, moderada, forte, pancada, trovoada, chuva recente (RE) e pancada nas proximidades (VCSH).
   - Uma hora tem chuva quando 15% dos pontos têm sinal ou o equivalente passa de 0,3 mm; é "não prevista" quando a previsão feita uma hora antes era menor que 0,2 mm.
   - No modelo: por 3 h após a chuva, o peso do fogo não é recalibrado, a queda não vira tendência e a fumaça removida volta com escala de 3 h; a chuva observada entra no trajeto da fumaça e uma pancada em curso continua um pouco nas 2 horas seguintes.
   - A validação separa as previsões com chuva não prevista no intervalo.
5b. **Fumaça distante e madrugada (variante F24R, em teste).** Focos fora dos 13 municípios (Pará, sul do Amazonas, Rondônia, Roraima...) vêm direto dos arquivos públicos do INPE (`focos/csv/10min` e `diario/Brasil`, os mesmos que o MonitorBETA baixa), agregados por célula de 0,25° e por hora em `docs/data/fogo_regional.json`. Para cada hora-alvo, uma retrotrajetória de 60 h parte da NAMA seguindo o vento a 925 hPa numa grade de 24 pontos do Open-Meteo; soma-se o que queimava perto do caminho (núcleo gaussiano de 30 km + 2,5 km por hora de viagem), com perda por diluição (36 h) e chuva no caminho. O índice (IFR) vira µg/m³ por um peso calibrado nas últimas 72 h. Um fator de madrugada (até 2,5×, entre 03h e 10h) multiplica a fumaça quando a noite anterior teve camada de mistura abaixo de 300 m e vento a 925 hPa forte. Para recalcular as últimas 60 h de uma vez: **Run workflow** com *diagnostico* marcado (grava `docs/data/diagnostico_regional.json`).
6. **Previsão (modelo v0).** `PM(t+h) = [PM_base + E(h) · R(h)] · D(h)/D(0)`, com
   - `E(h) = E0 · e^(−h/τ) + K · IFB(h) · (1 − e^(−h/τ)) + tendência amortecida`: a anomalia atual decai e é substituída pelo que o vento traz dos focos;
   - `R(h) = e^(−λ · chuva acumulada até h)`: remoção pela chuva prevista;
   - `D(h)`: camada de mistura (altura da camada limite prevista, ou curva diurna típica).
   - `K` é recalibrado a cada hora pela razão entre a anomalia observada e o IFB atual.
   - A faixa "provável entre" e a chance de cada classe vêm de um erro log-normal que cresce com o horizonte.
7. **Classes.** Valor horário (indicativo) e média móvel de 24 h combinando horas observadas e previstas (classe oficial do IQAr).
8. **Validação.** As previsões de +1, +3, +6, +12 e +24 h ficam em `docs/data/validacao_log.json`. Quando a hora chega, são comparadas com a mediana observada nos próprios PurpleAir: erro médio, viés, acerto de classe e erro da persistência.

## Calibração (próximo passo)

Os coeficientes do modelo v0 (`PM_BASE`, `TAU_PERSIST_H`, `K_FOGO`, `IFB_L_KM`, `IFB_TAU_H`, `LAMBDA_CHUVA`) são valores iniciais de bom senso físico, todos em `scripts/config.py`. Com algumas semanas de `historico.json` e `validacao_log.json`, eles devem ser ajustados pelo erro contra a persistência. Com uma estação seca inteira, o modelo v0 é substituído pelo LightGBM multi-horizonte descrito no artigo, mantendo o mesmo arquivo de saída.

## Rodar localmente

```bash
python scripts/qualiar.py --teste      # PM2,5 e tempo sintéticos + cópia real dos focos em scripts/amostra
cd docs && python -m http.server 8000  # abrir http://localhost:8000
```

Com `PURPLEAIR_API_KEY` no ambiente, `python scripts/qualiar.py` faz a coleta real. Só usa a biblioteca padrão do Python 3.10+.

## Arquivos de dados (`docs/data`)

| Arquivo | Conteúdo |
|---|---|
| `qualiar.json` | tudo o que o site mostra: estações, mediana, tendência, tempo, focos por município, IFB, previsão, validação |
| `focos_pontos.geojson` | focos ativos e recém-extintos com distância e rumo a partir da NAMA |
| `limites.geojson` | limites municipais (cópia do MonitorBETA) |
| `historico.json` | mediana horária das últimas 96 h, valores por estação (PM2,5, umidade, temperatura), registro horário de chuva prevista e observada (31 dias) e o último estado seco do modelo |
| `fogo_regional.json` | focos do INPE fora dos 13 municípios, por célula de 0,25° e hora (72 h) |
| `diagnostico_regional.json` | IFR, fator de madrugada, mediana observada e origem por estado, hora a hora (só com *diagnostico*) |
| `validacao_log.json` | previsões emitidas e observações correspondentes (60 dias) |
