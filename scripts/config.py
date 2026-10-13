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
             "humidity", "temperature", "last_seen", "location_type"]
# Sensores internos (location_type = 1) vêm na consulta para que a NAMA seja
# achada mesmo se estiver cadastrada como interna, mas ficam fora da mediana.
# Controle de qualidade A/B (critério EPA): descarta se a diferença
# passar de 5 µg/m³ E de 70%.
QC_DIF_ABS = 5.0
QC_DIF_REL = 0.70
SENSORES_MIN = 2                    # mínimo de sensores válidos para a mediana

# ---------------------------------------------------------------- classes
# Quatro classes derivadas do IQAr (MMA 2025) / CONAMA 506/2024, PM2,5 em µg/m³.
CLASSES = [
    {"id": 1, "nome": "Boa", "ate": 15, "cor": "#2f9e57",
     "msg": "Sem restrições."},
    {"id": 2, "nome": "Moderada", "ate": 50, "cor": "#e3b81f",
     "msg": "Grupos sensíveis devem reduzir esforço prolongado ao ar livre."},
    {"id": 3, "nome": "Ruim", "ate": 75, "cor": "#e9732a",
     "msg": "Grupos sensíveis evitam atividade ao ar livre; demais pessoas reduzem."},
    {"id": 4, "nome": "Muito Ruim/Péssima", "ate": math.inf, "cor": "#b01f3c",
     "msg": "Todos evitam atividade ao ar livre. Use PFF2 e procure ambientes com ar filtrado."},
]


def classe_de(pm):
    if pm is None:
        return None
    for c in CLASSES:
        if pm <= c["ate"]:
            return c["id"]
    return CLASSES[-1]["id"]


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
MODELO_PUBLICADO = "F24"
VARIANTES = ("F24", "F48", "v0.3")
HORIZONTES = list(range(1, 25))
DESTAQUES_H = [1, 3, 6, 12, 24]

# ---------------------------------------------------------------- arquivos
HISTORICO_H = 96           # horas de mediana guardadas
VALIDACAO_DIAS = 60
