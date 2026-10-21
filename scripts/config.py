"""Configuração central do QUALIAR-UFAM (previsão de qualidade do ar em Manaus).

Todos os limiares e coeficientes do modelo ficam aqui. Os coeficientes do
modelo v0 são valores iniciais de bom senso físico: devem ser recalibrados
com a série histórica (ver README, seção "Calibração").
"""
from pathlib import Path
import math

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "docs" / "data"
FUSO = "America/Manaus"  # UTC-4, sem horário de verão

# ---------------------------------------------------------------- centro
# Estação PurpleAir da UFAM usada como centro do método (distâncias e
# direções até os focos). O coletor procura o nome exato entre os sensores
# devolvidos pela API (que traz nome, número e posição de cada um), guarda o
# número e a posição encontrados e, se o sensor ficar sem dados numa hora,
# usa a última posição conhecida. Só sem nenhum registro usa as coordenadas
# aproximadas do campus abaixo.
NAMA_NOME = "MIT_NAMA_UFAM"
NAMA_SENSOR_INDEX = None          # opcional: o coletor descobre e guarda sozinho
NAMA_LAT_PADRAO = -3.0960
NAMA_LON_PADRAO = -59.9660

# ---------------------------------------------------------------- PurpleAir
# Retângulo da área urbana de Manaus (noroeste e sudeste).
PA_NW = (-60.15, -2.93)   # (lon, lat)
PA_SE = (-59.83, -3.18)
PA_MAX_IDADE_S = 2 * 3600          # ignora sensores sem dados há mais de 2 h
PA_CAMPOS = ["name", "latitude", "longitude", "pm2.5_cf_1_a", "pm2.5_cf_1_b",
             "pm2.5_10minute_a", "pm2.5_10minute_b",
             "humidity", "temperature", "last_seen", "location_type"]
# pm2.5_10minute_a/b: média de 10 min de cada canal, sem correção, como no mapa da PurpleAir.
# Só para mostrar no cartão a "leitura do sensor" (IQAr da média de 10 min), que é o número
# que a pessoa vê no mapa da PurpleAir na escala brasileira; a previsão usa o valor corrigido.
# Sensores internos (location_type = 1) vêm na consulta para que a NAMA seja
# achada mesmo se estiver cadastrada como interna, mas ficam fora da mediana.
# Controle de qualidade A/B (critério EPA): descarta se a diferença
# passar de 5 µg/m³ E de 70%.
QC_DIF_ABS = 5.0
QC_DIF_REL = 0.70
SENSORES_MIN = 2                    # mínimo de sensores válidos para a mediana
# Sensores com um canal (A ou B) com defeito conhecido: usa só o canal bom, em vez de descartar
# o sensor pela divergência entre canais. Conferir de tempos em tempos e tirar daqui quando o
# dono fizer a manutenção.
#   206677 SEMA_DCAM_27 (Coari): canal A marca ~1/7 do B, de forma constante, desde pelo menos 20/10/2026.
#   165023 UEA_EducAIR_19 (Parintins): canal B travado perto de 5.000 µg/m³ desde pelo menos 20/10/2026;
#          o canal A acompanha as duas estações da SEMA.
CANAL_UNICO = {206677: "b", 165023: "a"}

# ---------------------------------------------------------------- regiões
# Manaus é a região original (focos do MonitorBETA, NAMA como centro). As
# demais usam os focos do INPE dos municípios listados e a estação indicada
# como centro. "caixa" = retângulo dos sensores que entram na mediana da
# cidade (oeste, sul, leste, norte); "entorno" = retângulos de estações de
# referência mostradas no mapa e na tabela, fora da mediana (ex.: torre ATTO).
# Municípios em "Nome/UF"; fora do Brasil, "Nome/país".
ATTO = {"nome": "Torre ATTO (São Sebastião do Uatumã)", "caixa": (-59.15, -2.30, -58.85, -2.00)}
REGIOES = [
    {"id": "manaus", "monitorbeta": "manaus", "nome": "Manaus", "centro": "MIT_NAMA_UFAM", "lat": -3.0960, "lon": -59.9660,
     "caixa": (-60.15, -3.18, -59.83, -2.93), "entorno": [], "focos": "monitorbeta",
     "metar": ["SBEG", "SBMN"], "municipios": []},
    {"id": "itacoatiara", "monitorbeta": "itacoatiara", "nome": "Itacoatiara", "centro": "SEMA_DCAM_36", "lat": -3.1430, "lon": -58.4440,
     "caixa": (-58.60, -3.28, -58.30, -3.00), "entorno": [ATTO], "focos": "inpe", "metar": [],
     "municipios": ["Itacoatiara/AM", "Autazes/AM", "Nova Olinda do Norte/AM", "Silves/AM", "Urucará/AM",
                    "Barreirinha/AM", "Parintins/AM", "Urucurituba/AM", "Maués/AM", "Itapiranga/AM",
                    "São Sebastião do Uatumã/AM", "Boa Vista do Ramos/AM", "Presidente Figueiredo/AM",
                    "Rio Preto da Eva/AM"]},
    {"id": "parintins", "monitorbeta": "parintins", "nome": "Parintins", "centro": "SEMA_DCAM_47", "lat": -2.6280, "lon": -56.7360,
     "caixa": (-56.85, -2.75, -56.62, -2.53), "entorno": [ATTO], "focos": "inpe", "metar": ["SWPI"],
     "municipios": ["Parintins/AM", "Nhamundá/AM", "Oriximiná/PA", "Boa Vista do Ramos/AM", "Maués/AM",
                    "Urucurituba/AM", "Barreirinha/AM", "Urucará/AM", "Itaituba/PA", "Santarém/PA",
                    "Itapiranga/AM", "Presidente Figueiredo/AM", "Rio Preto da Eva/AM",
                    "São Sebastião do Uatumã/AM", "Itacoatiara/AM"]},
    {"id": "humaita", "monitorbeta": "humaita", "nome": "Humaitá", "centro": "SEMA_DCAM_65", "lat": -7.5060, "lon": -63.0210,
     "caixa": (-63.18, -7.65, -62.88, -7.38), "entorno": [], "focos": "inpe", "metar": ["SWHT"],
     "municipios": ["Humaitá/AM", "Lábrea/AM", "Porto Velho/RO", "Apuí/AM", "Canutama/AM", "Cruzeiro do Sul/AC",
                    "Manicoré/AM", "Novo Aripuanã/AM", "Tapauá/AM", "Autazes/AM", "Manaquiri/AM"]},
    {"id": "coari", "monitorbeta": "coari", "nome": "Coari", "centro": "SEMA_DCAM_27", "lat": -4.0850, "lon": -63.1410,
     "caixa": (-63.28, -4.20, -63.00, -3.97), "entorno": [], "focos": "inpe", "metar": ["SWKO"],
     "municipios": ["Coari/AM", "Tefé/AM", "Canutama/AM", "Lábrea/AM", "Tapauá/AM", "Beruri/AM", "Anori/AM",
                    "Manacapuru/AM", "Manaus/AM", "Novo Airão/AM", "Anamã/AM", "Barcelos/AM", "Manicoré/AM"]},
    {"id": "benjamin", "monitorbeta": "benjamin-constant", "nome": "Benjamin Constant", "centro": "SEMA_DCAM_19", "lat": -4.3830, "lon": -70.0310,
     # a caixa cobre Benjamin Constant, Tabatinga (SEMA_DCAM_57), Letícia e Atalaia do Norte
     # (SEMA_DCAM_16 e Vale do Javari): uma mediana da tríplice fronteira
     "caixa": (-70.35, -4.55, -69.85, -4.12), "entorno": [], "focos": "inpe", "metar": ["SBTT"],
     # fora dos limites brasileiros, a oeste da fronteira e a até 400 km: Letícia (Colômbia) e Iquitos (Peru)
     "estrangeiro": {"rotulo": "Colômbia e Peru", "lon_max": -69.6, "raio_km": 400.0},
     "municipios": ["Benjamin Constant/AM", "Atalaia do Norte/AM", "Tabatinga/AM", "Eirunepé/AM", "Carauari/AM",
                    "Envira/AM", "Cruzeiro do Sul/AC", "Mâncio Lima/AC", "Letícia/Colômbia", "Iquitos/Peru"]},
]
# Os arquivos de 10 minutos do INPE não trazem município: cada foco é atribuído
# pelo limite municipal do IBGE. Sem os limites (falha no download), conta como
# local tudo até esta distância do centro.
REG_LOCAL_SEM_LIMITES_KM = 150.0
METAR_EXTRA = {
    "SBTT": {"nome": "Aeroporto de Tabatinga", "lat": -4.2557, "lon": -69.9358},
    "SWPI": {"nome": "Aeroporto de Parintins", "lat": -2.6739, "lon": -56.7778},
    "SWKO": {"nome": "Aeroporto de Coari", "lat": -4.1342, "lon": -63.1326},
    "SWHT": {"nome": "Aeroporto de Humaitá", "lat": -7.5321, "lon": -63.0720},
}
# Variantes mostradas no site (gráfico e tabela). As outras continuam no JSON
# e na validação, para a publicação científica.
VARIANTES_NO_SITE = ("F24", "F24R")
# Sempre mostradas no site, além da publicada e da melhor em teste: o CAMS
# (Copernicus) antecipa os picos de fumaça regional, mesmo errando o valor.
VARIANTES_FIXAS_NO_SITE = ("CAMS",)

# ---------------------------------------------------------------- classes
# Cores do quadro oficial do IQAr: verde, amarelo, laranja, vermelho e roxo.
# Cinco classes do IQAr (Resolução CONAMA 506/2024 e guia do MMA), PM2,5 em
# µg/m³ na média de 24 h. Cada faixa de concentração corresponde a uma faixa
# do índice IQAr; dentro dela o índice é interpolado linearmente.
CLASSES = [
    {"id": 1, "nome": "Boa", "de": 0, "ate": 15, "iqar": (0, 40), "cor": "#4f9d3a",
     "msg": "Sem restrições."},
    {"id": 2, "nome": "Moderada", "de": 15, "ate": 50, "iqar": (41, 80), "cor": "#f0d03f",
     "msg": "Grupos sensíveis podem ter sintomas: reduzir esforço prolongado ao ar livre."},
    {"id": 3, "nome": "Ruim", "de": 50, "ate": 75, "iqar": (81, 120), "cor": "#e0812f",
     "msg": "Grupos sensíveis evitam atividade ao ar livre; demais pessoas reduzem esforço."},
    {"id": 4, "nome": "Muito Ruim", "de": 75, "ate": 125, "iqar": (121, 200), "cor": "#b3221c",
     "msg": "Todos evitam atividade ao ar livre. Grupos sensíveis permanecem em ambiente fechado."},
    {"id": 5, "nome": "Péssima", "de": 125, "ate": math.inf, "iqar": (201, 400), "cor": "#7b2d8e",
     "msg": "Risco para toda a população: permanecer em ambiente fechado, usar PFF2 se precisar sair."},
]
PESSIMA_TOPO = 300.0   # fim da faixa de Péssima na tabela (IQAr 400); acima disso o índice é extrapolado


def classe_de(pm):
    if pm is None:
        return None
    for c in CLASSES:
        if pm <= c["ate"]:
            return c["id"]
    return CLASSES[-1]["id"]


def iqar(pm):
    """Índice IQAr para uma concentração de PM2,5 (interpolação dentro da faixa)."""
    if pm is None:
        return None
    for c in CLASSES:
        topo = PESSIMA_TOPO if c["ate"] == math.inf else c["ate"]
        if pm <= topo or c["ate"] == math.inf:
            i0, i1 = c["iqar"]
            return round(i0 + (i1 - i0) / (topo - c["de"]) * (max(pm, c["de"]) - c["de"]))
    return None


# ---------------------------------------------------------------- focos
MONITORBETA_URL = "https://ufamcca.github.io/MonitorBETA/data/"
MUNICIPIOS = [
    "Manaus", "Iranduba", "Careiro", "Careiro da Várzea", "Manacapuru",
    "Novo Airão", "Anori", "Beruri", "Rio Preto da Eva",
    "Presidente Figueiredo", "Itacoatiara", "Manaquiri", "Autazes",
]
RECEM_EXTINTO_H = 12      # extinto (estimado) há no máximo isto = "recém-extinto"
# "Provável incêndio": foco ativo persistente ou grande, compatível com
# incêndio florestal e não com queima pontual de roçado.
INCENDIO_DURACAO_H = 24
INCENDIO_PIXELS = 10
INCENDIO_FRP_MW = 100

# ---------------------------------------------------------------- IFB
# Índice de fogo a barlavento v1 (artigo, seção 8.4). Para cada foco i e
# hora-alvo t (agora + h):
#
#   c_i = w_i * f_sup_i * E_i(t - T_i) * exp(-d_i/L) * G(theta_i; sigma) * f_U * exp(-lambda_rota * chuva_rota)
#
#   T_i      tempo de viagem da fumaça = d_i / velocidade média do vento de transporte
#   E_i      1 se o foco estava queimando no instante em que essa fumaça partiu
#   G        núcleo gaussiano no ângulo entre o rumo do foco (visto da NAMA)
#            e a direção de onde vem o vento médio do trajeto
#   sigma    espalhamento lateral (estabilidade) + variação da direção do vento no trajeto
#
# Vento de transporte: a fumaça viaja sobretudo entre 600 e 1100 m de altura
# (Gonzalez-Alonso et al., 2019), acima do anemômetro de 10 m. Usa-se a
# média vetorial do vento a 10 m e a 925 hPa (~800 m).
VT_PESO_925 = 0.7            # peso do vento a 925 hPa (o resto vem do de 10 m)
IFB_L_KM = 75.0              # diluição com a distância
IFB_JANELA_H = 48            # fumaça mais velha que isto é ignorada (= janela do MonitorBETA)
IFB_ANEIS_KM = [(0, 50), (50, 150), (150, 300)]

# Espalhamento angular da pluma (graus). Vento fraco = atmosfera mais
# turbulenta/variável = pluma larga; vento firme = pluma estreita.
SIGMA_ANG_MAX = 40.0         # com vento de 1 m/s
SIGMA_ANG_MIN = 15.0         # com vento de 5 m/s ou mais
SIGMA_ANG_TOTAL_MAX = 80.0

# Calmaria: sem direção definida, a fumaça se espalha devagar em todas as
# direções; só focos próximos contam.
IFB_CALMARIA_MS = 1.0
IFB_L_CALMA_KM = 20.0
IFB_VEL_DERIVA_MS = 0.5      # velocidade de deriva usada no tempo de viagem

# Diluição pela velocidade do vento: pluma estacionária ~ 1/U.
IFB_U_REF_MS = 2.0
IFB_FU_MIN, IFB_FU_MAX = 0.5, 2.0

# Remoção pela chuva no trajeto (chuva no ponto da NAMA como aproximação).
LAMBDA_ROTA = 0.20           # por mm acumulado no intervalo de transporte

# Intensidade do foco: FRP (MW) quando houver; senão, número de pixels.
IFB_FRP_REF_MW = 50.0        # w = clamp(FRP/ref, 1, 10)
# Fração da fumaça injetada acima da camada limite (não chega ao solo perto).
# 3 a 20% dos focos amazônicos injetam na troposfera livre, até 40% no fim
# da estação (Gonzalez-Alonso et al., 2019); cresce com o FRP.
INJ_FT_MIN, INJ_FT_MAX = 0.05, 0.35
INJ_FRP_INI, INJ_FRP_FIM = 100.0, 500.0

# Persistência de um foco ativo nas próximas horas (emissão futura).
PERSIST_FOGO_H = 8.0         # queima pontual
PERSIST_INCENDIO_H = 24.0    # provável incêndio
MARGEM_DETECCAO_H = 1.0      # a queima começa um pouco antes da 1ª detecção

# ---------------------------------------------------------------- chuva observada
# A "chuva passada" do Open-Meteo é saída de modelo, não medição. Pancadas
# convectivas de bairro escapam dos modelos globais (grade de ~10-25 km,
# convecção parametrizada), por isso a chuva que de fato caiu vem de:
#   1. METAR dos aeroportos (aviationweather.gov, grátis, sem chave);
#   2. assinatura de chuva nos próprios sensores PurpleAir;
#   3. pluviômetro do INMET (opcional, precisa de token: INMET_TOKEN).
METAR_URL = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json&hours=3"
METAR_ESTACOES = {
    "SBEG": {"nome": "Aeroporto Eduardo Gomes", "lat": -3.0386, "lon": -60.0497},
    "SBMN": {"nome": "Ponta Pelada", "lat": -3.1461, "lon": -59.9863},
}
# mm/h equivalentes à intensidade informada no METAR
METAR_MM = {"leve": 1.0, "moderada": 4.0, "forte": 10.0, "chuvisco": 0.3, "recente": 1.0}

INMET_URL = "https://apitempo.inmet.gov.br/token/estacao/{ini}/{fim}/{cod}/{token}"
INMET_ESTACAO = "A101"        # Manaus (estação automática); confirme no portal do INMET

# Assinatura de chuva num sensor PurpleAir, comparando com a hora anterior.
# A variação esperada (ciclo diário) vem do modelo meteorológico e é descontada.
SINAL_DT_C = -1.5             # queda de temperatura além da esperada
SINAL_DUR_PTS = 7.0           # alta de umidade além da esperada (pontos de %)
SINAL_UR_MIN = 70.0           # o sensor mede dentro da caixa, abaixo da UR do ar
SINAL_DPM = -0.20             # queda relativa do PM2,5 (evidência de apoio)
SINAL_MM = {"provavel": 2.0, "possivel": 0.7}   # mm equivalentes para remoção
CHUVA_EVENTO_FRAC = 0.15      # fração da cidade com sinal para contar como chuva
CHUVA_EVENTO_MM = 0.3
CHUVA_NAO_PREVISTA_MM = 0.2   # previsão abaixo disto = "não prevista"
CHUVA_HIST_H = 31 * 24        # horas de registro de chuva guardadas

# Efeito da chuva no modelo
LAVAGEM_JANELA_H = 3          # chuva nas últimas 3 h = ar "lavado"
TAU_RECUPERACAO_H = 3.0       # tempo para a fumaça regional voltar após a pancada
ANOMALIA_SECA_MAX_H = 12      # anomalia pré-chuva mais velha que isto não serve
NOWCAST_FRAC = {1: 0.4, 2: 0.15}   # pancada em curso continua um pouco nas próximas horas

# ---------------------------------------------------------------- modelo v0
PM_BASE = 8.0          # nível urbano de fundo sem fumaça (µg/m³)
TAU_PERSIST_H = 10.0   # escala de decaimento da anomalia atual
TAU_TENDENCIA_H = 2.0  # quanto da tendência das últimas 3 h se projeta
K_FOGO = 3.0           # µg/m³ por unidade de IFB (valor inicial)
K_MIN, K_MAX = 0.5, 20.0
LAMBDA_CHUVA = 0.30    # remoção por chuva, por mm acumulado
BLH_REF_M = 800.0      # altura da camada limite de referência
FATOR_DIURNO_MIN, FATOR_DIURNO_MAX = 0.6, 2.0
SIGMA_BASE, SIGMA_POR_RAIZ_H = 0.15, 0.05   # incerteza log-normal
# Modelo v0.4: nível de fundo regional (teste iniciado em 12/10/2026)
# A fumaça de queimadas em Manaus costuma ser regional: a anomalia de agora não
# decai para o "fogo local", e sim para o nível médio das últimas horas. O
# alvo de longo prazo passa a ser max(fundo regional, K x IFB).
JANELAS_FUNDO_H = (24, 48)
FUNDO_MIN_MEDICOES = 3        # menos que isto na janela: usa a anomalia de agora
TAU_CHUVA_H = 3.0             # o efeito de uma chuva prevista passa em ~3 h (não acumula para sempre)
# Variante publicada no site; as outras rodam em paralelo e são validadas igual.
#   "F24"  = fundo das últimas 24 h, sem ciclo da camada de mistura, chuva passageira
#   "F48"  = idem, fundo das últimas 48 h
#   "v0.3" = modelo anterior (decai para o fogo local; chuva acumulada; ciclo pela camada limite)
#   "F24P" = F24 + perfil horário aprendido com os últimos dias (metade da amplitude)
#   "CAMS" = previsão de PM2,5 do CAMS (Copernicus) ajustada ao nível medido pela PurpleAir
#   "F24N" = F24 + fator de madrugada sobre o fogo local (sem fumaça distante)
#   "F24R" = F24 + fumaça distante (trajetória de 60 h sobre os focos do INPE) + fator de madrugada
#   "F24U" = F24R + trajetórias em 925 e 850 hPa + ventilação + ilha de calor
#   "F24L" = F24U com a camada limite corrigida (Dias-Júnior et al., 2022): diluição da
#            fumaça distante e ventilação pela camada corrigida, alfa calibrado
MODELO_PUBLICADO = "F24"
VARIANTES = ("F24", "F48", "F24P", "CAMS", "F24N", "F24R", "F24U", "F24L", "v0.3")
VARIANTES_NO_GRAFICO = ("F24R",)

# Perfil horário (F24P): razão entre a mediana de cada hora e a média das 24 h
# em torno dela, por hora local, mediana entre os dias disponíveis.
PERFIL_AMPLITUDE = 0.5        # usa metade da amplitude aprendida (poucos dias = perfil ruidoso)
PERFIL_MIN_HORAS = 18         # janelas de 24 h com menos medições que isto são ignoradas
PERFIL_DIAS = 7               # usa no máximo os últimos 7 dias

# CAMS (variante "CAMS"): previsão global de aerossóis do Copernicus, via Open-Meteo
# (gratuito, sem chave). Enxerga o transporte regional de fumaça de focos fora da
# área do MonitorBETA. Ajuste de nível: razão entre o medido e o CAMS nas últimas 24 h.
CAMS_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?"
CAMS_FATOR_MIN, CAMS_FATOR_MAX = 0.2, 5.0
CAMS_MIN_PARES = 12
CAMS_TAU_H = 4.0              # peso do valor medido agora decai com esta escala
# ---------------------------------------------------------------- fumaça distante (F24R)
# Focos fora dos 13 municípios do MonitorBETA (Pará, sul do Amazonas, Rondônia...),
# lidos direto dos mesmos arquivos públicos do INPE que o MonitorBETA usa. A 500 km,
# o núcleo local exp(-d/75 km) daria peso ~0; por isso a fumaça distante é calculada
# por uma retrotrajetória: de Manaus, volta-se no tempo seguindo o vento a 925 hPa
# e soma-se o que queimava perto do caminho quando o ar passou por lá.
INPE_FOCOS_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv"
REG_CAIXA = (-76.0, -14.0, -45.0, 6.0)      # oeste, sul, leste, norte (graus)
REG_CELULA_GRAUS = 0.25                     # focos agregados por célula e por hora
REG_GUARDA_H = 72                           # horas de focos guardadas
REG_ARQUIVOS_MAX = 200                      # arquivos de 10 min baixados por rodada, no máximo
REG_DIST_MIN_KM = 40.0                      # mais perto que isto é sempre fogo local
REG_GRADE_LAT = (-12.0, -8.0, -4.0, 0.0, 4.0)    # pontos de vento a 925 hPa (Open-Meteo, uma chamada)
REG_GRADE_LON = (-74.0, -70.0, -66.0, -62.0, -58.0, -54.0, -50.0, -46.0)
REG_TRAJ_H = 60                             # horas de retrotrajetória
REG_SIGMA0_KM, REG_SIGMA_KMH = 30.0, 2.5    # largura da pluma: 30 km + 2,5 km por hora de viagem
REG_TAU_H = 36.0                            # perda por diluição e deposição ao longo da viagem
REG_ATIVO_H = 6                             # célula detectada há até 6 h conta como queimando
REG_PERSISTENCIA = 0.6                      # emissão futura = focos das últimas 24 h x 0,6
REG_FRP_REF_MW = 50.0
K_REG_INICIAL = 1.0                         # µg/m³ por unidade de IFR, até calibrar
K_REG_MIN, K_REG_MAX = 0.02, 50.0
K_REG_MIN_HORAS = 12                        # horas com IFR relevante para calibrar
IFR_MIN = 2.0

# Madrugada (F24N e F24R): com ar parado junto ao chão e vento forte a ~800 m, a
# fumaça viaja por cima da inversão noturna e desce de uma vez no começo da manhã
# (16/10/2026: 30 -> 123 µg/m³ entre 04h e 05h). Multiplica o termo de fumaça.
NOITE_A = 1.5                 # fator máximo = 1 + NOITE_A
NOITE_BLH_M = 300.0           # camada de mistura abaixo disto = noite estável
NOITE_V925_MIN, NOITE_V925_PLENO = 3.0, 8.0
NOITE_HORAS = {3: 0.5, 4: 1.0, 5: 1.0, 6: 1.0, 7: 1.0, 8: 1.0, 9: 0.5, 10: 0.25}  # hora local -> peso
RISCO_MATINAL_H = 24          # olha a próxima manhã inteira, mesmo numa rodada de 09h
RISCO_MATINAL_UG = 75.0       # aviso no site se F24R passar disto numa manhã com fator > 1,5

# ---------------------------------------------------------------- Painel do Fogo
# Eventos do Painel do Fogo (Censipam), copiados pelo MonitorBETA: um foco dentro de
# um evento grande ou persistente emite mais fumaça. Multiplicador do peso do foco:
# 1 + 0,5 x log2(1 + área em km²), até 3 (evento de 3 km² = 2x; 15 km² = 3x).
PAINEL_MULT_POR_LOG = 0.5
PAINEL_MULT_MAX = 3.0
PAINEL_PERSIST_INCENDIO_D = 3     # evento ativo há 3 dias ou mais = provável incêndio
PAINEL_AREA_INCENDIO_KM2 = 5.0

# ---------------------------------------------------------------- F24U (em teste desde 20/10/2026)
# F24R + três ajustes sugeridos pelo episódio de 14 a 19/10:
# 1) Vento em duas alturas de transporte: a fumaça de queimadas sobe a 500-2000 m.
#    A fumaça distante é a média das trajetórias a 925 hPa (~800 m) e 850 hPa (~1.500 m).
PESO_NIVEL_925 = 0.6
# 2) Ventilação: coeficiente de ventilação = altura da camada de mistura x vento
#    médio dentro dela (vetor de 10 m, 925 e, se a camada passa de 1.000 m, 850 hPa).
#    Ventilação baixa = a fumaça que já está na cidade demora mais a sair.
VENT_REF_M2S = 2000.0          # valor de referência (a calibrar com os dados de Manaus)
VENT_EXPOENTE = 0.3            # tau efetivo = tau x (VENT_REF / ventilação) ^ expoente
VENT_FATOR_MIN, VENT_FATOR_MAX = 0.6, 2.5
# 3) Ilha de calor: à noite, a cidade fica mais quente que o entorno e forma uma
#    cúpula de ar misturado que retém a fumaça sob a inversão. A intensidade vem dos
#    próprios sensores PurpleAir: temperatura medida menos a do modelo (Open-Meteo),
#    comparada com o normal daquela hora nos últimos 14 dias (a diferença fixa do
#    aquecimento da caixa do sensor se cancela).
ILHA_DIAS = 14
ILHA_FATOR_POR_GRAU = 0.15     # cada 1 °C de ilha de calor acima do normal alonga tau em 15%, à noite
ILHA_FATOR_MAX = 1.6
ILHA_HORAS_NOITE = (19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7)

# ---------------------------------------------------------------- F24L (em teste desde 20/10/2026)
# Camada limite corrigida pelas medidas da Amazônia Central:
#   Dias-Júnior et al. (2022, Remote Sensing 14, 4561): o reanálise erra a altura de dia
#     por um fator constante e desaba cedo demais no fim da tarde; correção (eq. 2):
#       12-17 UTC (08h-13h): (1 + alfa) x altura do modelo
#       18-23 UTC (14h-19h): (1 + alfa) x máximo do dia x sen[pi (t - 12) / 12]
#     alfa = -0,12 na floresta (ATTO) e +0,15 a +0,30 no pasto (T3). À noite o modelo não
#     acompanha a medida hora a hora; a camada noturna estável tem ~250 m e o que o
#     ceilômetro vê a 400-500 m é a camada residual.
#   Souza et al. (2023, Ciência e Natura 45, e80266): ciclo médio na ATTO; mínimo às
#     10-11 UTC, máximo de 1.600-1.700 m na seca às 19-20 UTC.
# Fator de correção por município: alfa é calibrado em cada cidade com os seus próprios
# sensores e guardado no historico.json dela (estado.alfa_camada). Parte de 0, ou do valor
# "alfa_camada" da cidade em REGIOES, se houver (região diferente da ATTO e do T3).
CAMADA_ALFA_INICIAL = 0.0
CAMADA_ALFA_MIN, CAMADA_ALFA_MAX, CAMADA_ALFA_PASSO = -0.30, 0.50, 0.05
CAMADA_ALFA_PENALIDADE = 0.10      # o erro precisa cair mais que 10% x alfa² para se afastar de 0
CAMADA_ALFA_SUAVE = 0.3            # alfa novo = 70% do anterior + 30% do melhor desta rodada
CAMADA_NOITE_M = 150.0             # camada noturna estável fixa, 00-11 UTC = 20h-07h (especialista, 20/10/2026)
# Curva da ATTO na seca (Souza et al., 2023), usada só se o Open-Meteo não der a altura de dia.
CAMADA_CLIMA_UTC = {12: 550, 13: 750, 14: 1000, 15: 1200, 16: 1400, 17: 1550}
# Alturas (m acima do solo) usadas para decidir que ventos estão dentro da camada na ventilação.
NIVEIS_ALTURA_M = {"950": 500.0, "925": 800.0, "850": 1500.0}
# Fumaça distante no chão: IFR em duas alturas (como a F24U) x fator de madrugada x diluição
# pela camada corrigida, (DILUICAO_REF_M / camada) ^ DILUICAO_EXPOENTE. Na série de 14 a 20/10
# a anomalia de PM2,5 é máxima às 05-08h e mínima à tarde, quando a camada é funda: a
# fumaça já está na camada rasa da madrugada e se dilui quando ela cresce. A hipótese de que
# a fumaça só chega ao chão quando a camada alcança a altura de transporte não se sustentou
# (correlação ~0 com a anomalia, contra 0,80 desta forma; 145 h, dentro da amostra).
DILUICAO_REF_M = 800.0
DILUICAO_EXPOENTE = 0.25
# À noite a camada é fixa (150 m) e portanto sempre estável: o fator de madrugada da F24L
# depende só da hora e do vento a ~800 m (o critério "camada do modelo < 300 m" da F24R era
# verdadeiro em quase todas as noites e saiu). Diferença de temperatura potencial e número de
# Richardson entre 10 m e 950 hPa ficam registrados no JSON para testar depois.
P_SUPERFICIE_HPA = 1008.0          # pressão típica em Manaus, para a temperatura potencial

HORIZONTES = list(range(1, 25))
DESTAQUES_H = [1, 3, 6, 12, 24]

# ---------------------------------------------------------------- arquivos
HISTORICO_H = 24 * 14      # horas de mediana guardadas (14 dias, para o perfil horário)
VALIDACAO_DIAS = 60
