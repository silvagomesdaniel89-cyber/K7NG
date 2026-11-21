import os
import re
import json
import html
import time
import random
import asyncio
import logging
import datetime
import unicodedata
import warnings
from collections import defaultdict, deque
from io import BytesIO
from threading import Thread
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
import imagehash
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
from PIL import Image, ImageFile, ImageDraw, ImageFont

if (discord.version_info.major, discord.version_info.minor) < (2, 4):
    raise SystemExit(f"❌ discord.py {discord.__version__} é antigo demais. Rode: pip install -U discord.py (precisa da 2.4 ou mais nova).")

# Aceita imagens "cortadas"/levemente corrompidas (o Discord ainda exibe, então o bot também precisa analisar)
ImageFile.LOAD_TRUNCATED_IMAGES = True
# Imagem gigante demais vira erro (e é ignorada) em vez de estourar a memória da hospedagem
Image.MAX_IMAGE_PIXELS = 60_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

# ==================== SERVIDOR WEB PARA MANTER ONLINE ====================
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

@app.route("/")
def home():
    return "K7NG Security online e operando com perfeição!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ======================================================================
# 1) CONFIGURAÇÃO DO K7NG  (é só aqui que você mexe)
# ======================================================================
GUILD_ID = 1372306050018971849  # ID do servidor K7NG
NOME_SERVIDOR = "K7NG"
COR = 0x950606
COR_VERDE = 0x2ECC71
COR_AMARELA = 0xF1C40F

# ======================================================================
# 📌 2) IDs DOS SEUS CANAIS, CATEGORIAS E CARGOS  (cole os IDs aqui!)
# ======================================================================
# Como pegar um ID: Discord > Configurações > Avançado > ligue o "Modo desenvolvedor".
# Depois clique com o botão direito no canal / categoria / cargo > "Copiar ID".
# 0 = o bot tenta achar sozinho pelo nome (aceita nome decorado, tipo 💬〢geral). Se não achar, ignora aquele item.

# ---------- 📢 Canais que aparecem nas mensagens do bot ----------
CANAL_BOAS_VINDAS = 1467561655771861250        # onde sai a mensagem de boas-vindas
CANAL_SAIDAS = 0             # onde sai o aviso de quem saiu
CANAL_GERAL = 1372306050820083857              # vira o {geral} na mensagem de boas-vindas
CANAL_REGRAS = 1372306050627403779             # vira o {regras}
CANAL_VIDEOS = 1372306052363849843             # vira o {videos}
CANAL_TICKETS = 1529658109654470676            # vira o {tickets}: canal onde fica o painel para abrir ticket
CANAL_BOOSTER = 1493668348440088596            # vira o {booster}: canal do painel "Seja Booster" e dos agradecimentos de impulso
CANAL_SUGESTOES = 0          # canal das sugestões (/sugestao)
CANAL_SORTEIOS = 1375133597027012658           # canal padrão dos sorteios (0 = o canal onde você usar /sorteio criar)
CANAL_NIVEIS = 0             # canal do aviso "subiu de nível" (0 = no próprio canal da conversa)

# ---------- 🎫 Área de tickets ----------
CATEGORIA_TICKETS = 1500672099226746890        # "ÁREA DE TICKET ABERTO": categoria onde os tickets nascem. Cada setor pode ter a sua (veja TICKET_SETORES).
                             # 0 = o bot acha/cria uma categoria chamada "TICKETS"

# ---------- 📜 Canais de punição ----------
CANAL_BAN = 1555001131892211773     # ban, unban, kick + alertas de segurança (raid, nuke, bot barrado, lockdown...)
CANAL_MUTE = 1566956599141204228    # mute, unmute e warn

# ---------- 🏷️ Cargos ----------
CARGO_STAFF = 1419480774964674660                 # cargo da staff. 0 = só conta como staff quem tem permissão de moderação
CARGOS_STAFF_EXTRA = []         # outros cargos de staff. Ex.: [123, 456]
CARGO_VERIFICADO = 0            # cargo dado no botão "Verificar". 0 = verificação desligada
CARGO_AUTOMATICO = 0            # cargo dado a todo membro que entra (0 = nenhum)
CARGO_AUTOMATICO_BOT = 0        # cargo dado a todo bot que entra (0 = nenhum)
CARGO_BOOSTER = 0               # cargo Booster (aparece no painel). 0 = o bot usa o cargo "Server Booster" do próprio Discord
CARGO_BOOSTER_RESGATE = 0       # cargo entregue no botão "Resgatar cargo" do painel Booster (0 = o botão abre um ticket em vez disso)
CARGOS_TRAVAR = []              # cargos de membro que o /lockdown também trava (além do @everyone). Ex.: [123, 456]

# ---------- 📜 LOGS SEPARADOS (igual ao print: AUTOMOD / LOGS / TICKETS) ----------
# Cada tipo de log vai para um canal diferente. Se você já tem o canal, coloque o ID no lugar do 0.
# Com 0, o bot procura um canal com aquele nome (aceita nome decorado tipo 〖📄〗「logs-geral」) e, se não achar, CRIA um privado.
# Para criar tudo de uma vez, use o comando /setup.
LOGS_AUTO_CRIAR = True
# tipo: (ID do canal, nome do canal, categoria, descrição)
CANAIS_LOG = {
    "ban":             (CANAL_BAN,  "logs-ban",        "LOGS",    "Ban, unban, kick e alertas de segurança (raid, nuke, bot barrado, lockdown...)."),
    "mute":            (CANAL_MUTE, "logs-mute",       "LOGS",    "Mute, unmute e warn."),
    "geral":           (1492280267526897734,          "logs-geral",      "LOGS",    "Entradas, saídas, convites, comandos da staff e eventos gerais."),
    "mensagens":       (1492280267526897734,          "logs-mensagem",   "LOGS",    "Mensagens apagadas, editadas e limpezas em massa."),
    "membros":         (1492280267526897734,          "logs-membros",    "LOGS",    "Apelidos, cargos, nome e avatar dos membros."),
    "voz":             (1492280267526897734,          "logs-voz",        "LOGS",    "Entradas, saídas e trocas nos canais de voz."),
    "servidor":        (1573516963999785020,          "logs-servidor",   "LOGS",    "Canais, cargos, emojis, webhooks e configurações do servidor."),
    "ticket":          (1475144659058688151,          "logs-ticket",     "TICKETS", "Tickets abertos e fechados (com transcrição)."),
    "automod_all":     (0,          "automod-all",     "AUTOMOD", "TUDO que o automod fez."),
    "automod_spam":    (0,          "automod-spam",    "AUTOMOD", "Spam, flood e mensagens repetidas."),
    "automod_links":   (0,          "automod-links",   "AUTOMOD", "Links, convites, golpes e imagens proibidas."),
    "automod_profile": (0,          "automod-profile", "AUTOMOD", "Nomes e apelidos impróprios."),
}

# ======================================================================
# 3) OUTROS AJUSTES (opcional)
# ======================================================================
# Pessoas de confiança total (além do dono do servidor): o anti-nuke nunca pune essas contas.
# Dica: coloque aqui os IDs dos staffs de confiança (se um staff banir/expulsar vários de uma vez, o anti-nuke pode agir).
WHITELIST_IDS = set()           # exemplo: {123456789012345678, 987654321098765432}
BOTS_PERMITIDOS = set()         # ids de bots que podem entrar mesmo adicionados por quem não é de confiança

SAIR_DE_OUTROS_SERVIDORES = True   # bot privado: sai sozinho de qualquer servidor que não seja o K7NG
STAFF_ISENTA_DO_AUTOMOD = True     # staff não leva punição de spam/link/palavrão
STAFF_ISENTA_DE_TUDO = True        # staff também NÃO é punida por golpe nem por imagem bloqueada (no golpe, só apago a mensagem e aviso no log)

# Canais privados do bot (só o bot escreve). O bot cria sozinho se não existirem.
NOME_CANAL_REGISTRO = "imagens-bloqueadas"   # guarda a lista do /bloquear_imagem
NOME_CANAL_WARNS = "warns-registro"          # guarda os warns
NOME_CANAL_DADOS = "bot-dados"               # guarda o banco de dados (XP, sorteios, AFK) num arquivo anexado
NOME_ARQUIVO_DADOS = "dados_k7ng.json"
ARQUIVO_LOCAL = "dados_k7ng.json"            # cópia de reserva no disco da hospedagem (se ela deixar gravar)
TOPICO_REGISTRO = "Lista de imagens bloqueadas do bot. NÃO apague as mensagens daqui (para desbloquear use /desbloquear_imagem)."
TOPICO_WARNS = "Registro de warns do bot. NÃO apague as mensagens daqui (para remover use /limpar_warns)."
TOPICO_DADOS = "Banco de dados do bot (XP, sorteios, AFK). NÃO apague a mensagem com o arquivo daqui."
TOPICO_TICKET = "K7NG-ticket:"

# ==================== AJUSTES DO ANTI-RAID ====================
RAID_ENTRADAS = 6               # quantas entradas...
RAID_JANELA_SEG = 10            # ...em quantos segundos ligam o modo raid
RAID_DURACAO_MIN = 10           # quanto tempo o modo raid fica ligado (use /raid desligar para encerrar antes)
RAID_ACAO = "kick"              # o que fazer com quem entra durante a raid: "kick" (expulsa) ou "ban" (bane)
IDADE_MINIMA_CONTA_DIAS = 0     # expulsa contas criadas há menos de X dias (0 = desligado)

# ==================== AJUSTES DO ANTI-SPAM / AUTOMOD ====================
SPAM_MENSAGENS = 6              # X mensagens...
SPAM_JANELA_SEG = 5             # ...em Y segundos = flood
SPAM_DUPLICADAS = 4             # mesma mensagem X vezes...
SPAM_DUP_JANELA_SEG = 20        # ...em Y segundos
SPAM_CANAIS = 3                 # mesma mensagem em X canais diferentes (nessa mesma janela)
SPAM_JANELA_MAX = max(SPAM_JANELA_SEG, SPAM_DUP_JANELA_SEG) + 5
MUTE_SPAM_MIN = 240             # 🔇 quem faz SPAM (flood / repetida / vários canais) leva mute de 240 min = 4 HORAS direto
MAX_MENCOES = 5                 # menções (pessoas + cargos) numa mensagem só
MAX_EMOJIS = 15
MAX_LINHAS = 15
MAX_CAPS_PCT = 0.75             # % de letras MAIÚSCULAS (só vale a partir de MIN_LETRAS_CAPS letras)
MIN_LETRAS_CAPS = 20
NOVATO_SEM_LINKS_MIN = 10       # quem entrou há menos de X minutos não pode mandar links (0 = desligado)
DOMINIOS_PERMITIDOS = (         # links liberados até para novatos
    "discord.com", "discordapp.com", "discordapp.net", "tenor.com", "giphy.com",
    "imgur.com", "youtube.com", "youtu.be", "twitch.tv",
)
CONVITES_PERMITIDOS = set()     # códigos de convite liberados. Ex.: {"k7ng"}  (staff já é isenta)
NICK_PADRAO = "Nick Moderado"   # apelido que o bot coloca em quem entra/troca para um nome impróprio (ver #automod-profile)

# Cada infração soma pontos. Os pontos valem por JANELA_REINCIDENCIA_MIN minutos.
PONTOS = {
    "convite": 5, "mencoes": 5, "multicanal": 5,
    "flood": 3, "repetida": 3,
    "palavrao": 1, "link_novato": 1, "formatacao": 1,
}
JANELA_REINCIDENCIA_MIN = 30
# (pontos acumulados, minutos de mute). 1-2 pontos = só aviso no canal. (Spam ignora isso e leva MUTE_SPAM_MIN.)
ESCADA_PONTOS = sorted([(3, 10), (5, 60), (8, 1440)], reverse=True)
AVISAR_NO_CANAL = True          # manda um aviso rápido (some em 10s) quando alguém é advertido/silenciado

# ==================== AJUSTES DO ANTI-NUKE ====================
NUKE_ACAO = "ban"               # "ban", "kick" ou "remover_cargos" (para quem estourar o limite)
# chave da ação do Registro de Auditoria: (nome, quantidade, em quantos segundos)
NUKE_REGRAS = {
    "channel_delete": ("exclusões de canais", 3, 30),
    "channel_create": ("criações de canais", 6, 30),
    "role_delete": ("exclusões de cargos", 3, 30),
    "role_create": ("criações de cargos", 6, 30),
    "emoji_delete": ("exclusões de emojis", 5, 60),
    "webhook_delete": ("exclusões de webhooks", 3, 60),
    "ban": ("banimentos", 5, 60),
    "kick": ("expulsões", 5, 60),
    "webhook_create": ("criações de webhooks", 3, 60),
    "member_prune": ("limpezas (prune) de membros", 1, 60),
    "perm_perigosa": ("permissões perigosas concedidas", 3, 60),
}
PROTEGER_CARGOS_PERIGOSOS = True        # desfaz permissões perigosas dadas por quem não é de confiança
BLOQUEAR_BOTS_NAO_AUTORIZADOS = True    # expulsa bots adicionados por quem não é de confiança
PERMS_PERIGOSAS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members",
)

# ==================== AJUSTES DOS WARNS ====================
WARN_VALIDADE_DIAS = 30         # warn mais velho que isso não conta mais para o escalonamento
# quando a pessoa chega em X warns: (ação, minutos)  — ação: "mute", "kick" ou "ban"
WARN_ESCADA = {3: ("mute", 60), 5: ("mute", 1440), 7: ("ban", 0)}

# ======================================================================
# 🎫 4) TICKETS (painel estilo Ticket King / BobsBot)
# ======================================================================
TICKET_ESTILO_PADRAO = "botoes"     # "botoes" = botões (print do Ticket King) | "menu" = menu de seleção (print do BobsBot)
                                    # (no /painel_tickets você escolhe o estilo na hora)
TICKET_PAINEL_AUTOR = "Ajuda & Suporte"
TICKET_PAINEL_TITULO = "Tickets Tropa do K7NG"
TICKET_PAINEL_TEXTO = "Denúncias:
↳ Denúncias, ajuda técnica e revisão de punições.

Sorteios:
↳ Resgate premios dos sorteios.

Dúvidas:
↳ Tire dúvidas sobre a comunidade ou regras do servidor.

Patrocionio:
↳ Patrocine alguma fruta ou skin para sorteios.

Lembre-se: Nossa equipe está pronta para investigar e resolver qualquer situação de forma rápida e justa. Sua privacidade será respeitada durante todo o processo!"
TICKET_PAINEL_RODAPE = "Atendimento Oficial K7NG"
IMAGEM_PAINEL_TICKETS = "https://cdn.discordapp.com/attachments/1519742551488467184/1573518663296880792/file_000000002904820e87bbd755ad1aec09.png?ex=6b024cf3&is=6b00fb73&hm=070e56fafc298f96384f399be9f4577cdb63bf8d04089f04531a97515987616f"          # 🖼️ ESPAÇO PARA IMAGEM: banner grande embaixo do texto do painel (cole o link da imagem)
MINIATURA_PAINEL_TICKETS = ""       # 🖼️ imagem pequena no canto do painel (opcional)
IMAGEM_TICKET_ABERTO = ""           # 🖼️ imagem dentro do ticket, na mensagem de abertura (opcional)
TICKET_MENU_PLACEHOLDER = "Selecione o setor do suporte..."
TICKET_MENU_AVISO = ("**Lembre-se:** nossa equipe está pronta para investigar e resolver qualquer situação "
                     "de forma rápida e justa. Sua privacidade será respeitada durante todo o processo!")
TICKET_PEDIR_MOTIVO = True          # abre uma janelinha pedindo o motivo antes de criar o ticket
TICKET_MAX_POR_USUARIO = 1          # quantos tickets abertos cada pessoa pode ter
TICKET_TRANSCRICAO_MAX = 2000       # máximo de mensagens salvas na transcrição
# Mensagem de abertura padrão (cada setor pode ter a sua em "mensagem"). Variável: {mention}
TICKET_MENSAGEM_PADRAO = ("Olá {mention}, seu ticket foi aberto com sucesso!\n\n"
                          "A equipe já foi avisada e vai te atender em breve. "
                          "Enquanto isso, explique tudo com detalhes e envie provas (prints/vídeos) se tiver.")
# Cada setor vira um botão (ou uma opção do menu). Pode apagar, renomear ou adicionar blocos.
#   chave     = nome interno (sem espaço/acento/dois-pontos, NÃO repita)
#   nome      = texto do botão   |   emoji = emoji do botão   |   desc = descrição (aparece no estilo "menu")
#   pergunta  = dica dentro da janelinha que pede o motivo
#   categoria = ID da categoria ("área de ticket aberto") onde ESSE tipo de ticket nasce (0 = usa CATEGORIA_TICKETS)
#   cargo     = ID do cargo que atende ESSE setor (0 = só a staff geral)
#   canal_log = ID do canal onde a transcrição desse setor vai (0 = #logs-ticket)
#   mensagem  = mensagem de abertura só desse setor (vazio = TICKET_MENSAGEM_PADRAO)
#   no_painel = False esconde o setor do painel de tickets (ele abre por outro botão, como o do Booster)
TICKET_SETORES = [
    {"chave": "denuncias", "nome": "Ticket Denúncias", "emoji": "📢",
     "desc": "Denunciar um membro ou situação (leve as provas).",
     "pergunta": "Quem você quer denunciar e o que aconteceu?",
     "categoria": 0, "cargo": 0, "canal_log": 0, "mensagem": "", "no_painel": True},
    {"chave": "duvidas", "nome": "Dúvidas sobre o Servidor", "emoji": "⁉️",
     "desc": "Tire dúvidas sobre o servidor ou as regras.",
     "pergunta": "Qual é a sua dúvida?",
     "categoria": 0, "cargo": 0, "canal_log": 0, "mensagem": "", "no_painel": True},
    {"chave": "sorteios", "nome": "Resgatar Sorteios", "emoji": "🍎",
     "desc": "Ganhou um sorteio? Abra aqui para resgatar o prêmio.",
     "pergunta": "Qual sorteio você ganhou e qual era o prêmio?",
     "categoria": 0, "cargo": 0, "canal_log": 0, "mensagem": "", "no_painel": True},
    {"chave": "patrocinios", "nome": "Patrocínios", "emoji": "💸",
     "desc": "Parcerias e patrocínios com o servidor.",
     "pergunta": "Fale sobre a sua proposta de parceria/patrocínio.",
     "categoria": 0, "cargo": 0, "canal_log": 0, "mensagem": "", "no_painel": True},
    # Setor do painel Booster: NÃO aparece no painel de tickets, abre pelo botão do /painel_booster
    {"chave": "booster", "nome": "Cargo Booster", "emoji": "💎",
     "desc": "Benefícios de booster (cargo personalizado e mais).",
     "pergunta": "Qual nome e cor você quer no seu cargo personalizado?",
     "categoria": 0, "cargo": 0, "canal_log": 0,
     "mensagem": ("Olá {mention}, obrigado por impulsionar o servidor! 💎\n\n"
                  "Nossa equipe vai criar o seu **cargo personalizado** e te dizer como adicionar até 5 amigos nele."),
     "no_painel": False},
    # Exemplo de setor extra (tire o # das linhas para ativar):
    # {"chave": "exposed", "nome": "Exposed", "emoji": "🕵️",
    #  "desc": "Falar sobre algum membro que está expondo outro membro.",
    #  "pergunta": "Conte o que está acontecendo e anexe as provas depois.",
    #  "categoria": 0, "cargo": 0, "canal_log": 0, "mensagem": "", "no_painel": True},
]

# ======================================================================
# 💎 5) PAINEL BOOSTER (estilo Sapphire) — /painel_booster
# ======================================================================
BOOSTER_TITULO = "✦  SEJA BOOSTER !"
BOOSTER_SUBTITULO = "★ Vantagens de ser um {cargo_booster}:"       # {cargo_booster} vira a menção do cargo
BOOSTER_VANTAGENS = [                                              # uma vantagem por linha (apague/edite à vontade)
    "Sorteios em Dobro: Suas chances de ganhar são multiplicadas por 3x.",
    "Acesso VIP: Canais de texto e calls privadas totalmente exclusivas.",
    "Servidores Privados: Entrada garantida em nossos servidores de jogos.",
    "Identidade Única: Cargo destacado na lista de membros e ícone de booster.",
    "Qualidade Superior: Melhores taxas de bits de áudio e transmissão.",
    "Um cargo personalizado SEU que você pode adicionar em até 5 membros.",
    "Permissões Extras: Mais liberdade nos chats (emojis, figurinhas e links).",
]
BOOSTER_COR = 0xE91EC8              # cor da barra do painel (rosa/magenta)
IMAGEM_PAINEL_BOOSTER = "https://cdn.discordapp.com/attachments/1519742551488467184/1573519202159951992/file_00000000e0f0820e8101682a83fed156.png?ex=6b024d74&is=6b00fbf4&hm=40dab6f302b7fec18e3f4702933826d3fb1b406e5e141bd40661634a72083b3f"          # 🖼️ ESPAÇO PARA IMAGEM: banner grande embaixo das vantagens (cole o link da imagem)
MINIATURA_PAINEL_BOOSTER = ""       # 🖼️ imagem pequena no canto do painel (opcional)
SORTEIO_PESO_BOOSTER = 3            # nos sorteios, booster tem X vezes mais chance (1 = igual aos outros). Combine com o texto acima!

# ======================================================================
# 👋 6) BOAS-VINDAS / DESPEDIDA (estilo Loritta)
# ======================================================================
BOAS_VINDAS_ATIVADO = True
BOAS_VINDAS_MARCAR = True       # True = marca o membro fora do embed (ele recebe a notificação), igual a Loritta
BOAS_VINDAS_CONTEUDO = "👋 {mention}"
BOAS_VINDAS_TITULO = "Bem-vindo(a) à tropa do {servidor}! 🔥"
# Cada linha abaixo é um pedaço separado da mensagem (apague uma, troque o texto, ou deixe "" para pular).
# Variáveis: {mention} {nome} {usuario} {servidor} {membros} {id} {conta_criada} {convidado_por}
# Canais (usam os IDs lá de cima): {geral} {regras} {videos} {tickets} {booster}
BOAS_VINDAS_LINHAS = [
    "E aí, {mention}! Seja muito bem-vindo(a) ao **{servidor}**! 🎉",
    "💬 Pode chegar chegando e trocar uma ideia no {geral}.",
    "📕 Antes de tudo, dá uma lida nas {regras} pra manter a convivência tranquila pra todo mundo. 😉",
    "🎥 Fica ligado(a): os vídeos novos são avisados no {videos}!",
    "🎫 Precisando de ajuda? Abre um ticket em {tickets}.",
    "💎 Quer vantagens exclusivas? Vire booster e confira em {booster}!",
    "Aproveita e se diverte! Você é o membro nº **{membros}**. 🚀",
]
BOAS_VINDAS_BANNER = "https://cdn.discordapp.com/attachments/1519742551488467184/1573519623738097704/file_000000003d98820eace23d2a69fcfbc9.png?ex=6b024dd8&is=6b00fc58&hm=ba873abec4a7ef56d4486004664576b4b6c0e4261d546c7d2d93970d872d356d"         # 🖼️ ESPAÇO PARA IMAGEM: link de um banner fixo. Se vazio e BOAS_VINDAS_CARTAO=True, o bot desenha um cartão com a foto do membro
BOAS_VINDAS_CARTAO = True
BOAS_VINDAS_DM = ""             # (opcional) mensagem enviada no privado do membro. Vazio = não envia. Aceita as mesmas variáveis
BOAS_VINDAS_APAGAR_SEG = 0      # apagar a mensagem de boas-vindas depois de X segundos (0 = nunca)
SAIDA_TEXTO = "😢 **{nome}** saiu do servidor. Agora somos **{membros}** membros."
BOOST_AGRADECER = True          # agradece quando alguém impulsiona o servidor (no CANAL_BOOSTER; se vazio, no canal da mensagem de impulso)

# ==================== NÍVEIS / XP (estilo Loritta/MEE6) ====================
XP_ATIVADO = True
XP_POR_MENSAGEM = (15, 25)      # ganha um valor aleatório nesse intervalo...
XP_COOLDOWN_SEG = 60            # ...no máximo 1 vez a cada X segundos
CANAIS_SEM_XP = set()           # ids de canais onde não se ganha XP
RECOMPENSAS_NIVEL = {}          # cargos por nível. Ex.: {5: 111111111111111111, 10: 222222222222222222}
SO_MAIOR_CARGO_NIVEL = True     # True = o membro fica só com o cargo do maior nível alcançado

# ==================== SORTEIOS / EXTRAS ====================
EMOJI_SORTEIO = "🎉"
SALA_TEMP_CRIADOR = 0           # ID de um canal de VOZ "➕ Criar sala": quem entra ganha uma sala própria (0 = desligado)
SALA_TEMP_PREFIXO = "🔊 Sala de "
COMANDOS_SEM_LOG = {"avatar", "userinfo", "serverinfo", "rank", "top", "afk", "sugestao"}   # comandos que não aparecem no #logs-geral

# ==================== LISTAS E AJUSTES DOS FILTROS ====================
# COMO ESCREVER AS LISTAS DE TEXTO (TERMOS_BAN e PALAVROES):
#   - Palavra solta ("rola"): só pega a palavra INTEIRA (rola, rolas, r0la, r o l a, p.o.r.r.a)
#     e NUNCA um pedaço de outra palavra (enrolando, desenrolado, computador, picanha...).
#   - Expressão ("tomar no cu"): escreva COM ESPAÇOS. Pega com espaço, hífen ou tudo junto ("tomarnocu").
#   - Não precisa se preocupar com acento, maiúscula, número no lugar de letra (p0rr4)
#     nem letra repetida (porrrra). O plural com "s" também já é pego sozinho.

TERMOS_BAN = [
    "check my bio", "check my profile", "look my bio", "look at my bio",
    "check bio", "olhar a biografia", "olhe minha bio", "free nitro",
    "nitro gratis", "onlyfans free"
]

# Pedaços de endereço (site) típicos de golpe de Nitro/Steam. Link com isso = punição de golpe (GOLPE_ACAO).
LINKS_GOLPE_PARTES = (
    "discord-nitro", "discordnitro", "nitro-discord", "nitrodiscord", "discord-gift", "discordgift",
    "discorcl", "dlscord", "disc0rd", "steamcommunlty", "steamcornmunity", "steancommunity",
)

PALAVROES = [
    "fdp", "filho da puta", "filha da puta", "caralho", "krl", "bosta",
    "escroto", "escrota", "merda", "arrombado", "arrombada", "viado",
    "corno", "corna", "desgracado", "desgracada", "vagabundo", "vagabunda",
    "porra", "buceta", "cacete", "puta", "puto", "putaria", "putinha",
    "cuzao", "cuzoes", "pica", "rola", "xoxota", "vadia", "foder",
    "foda se", "tnc", "tomar no cu", "vsf", "vtnc", "pqp"
]

# ---------- Imagens proibidas e golpes: o que o bot faz ----------
# SÓ VALE O QUE VOCÊ ESCOLHER, E SÓ IMAGEM IDÊNTICA. Não existe mais "imagem parecida" (era isso que punia gente por engano).
#   - imagens do /bloquear_imagem: só vale se a imagem enviada for IGUAL (os 3 hashes idênticos);
#   - hashes soltos de IMAGENS_BLOQUEADAS (abaixo): só vale se algum hash da imagem enviada for IGUAL ao da lista.
# Use /testar_imagem para conferir uma imagem sem punir ninguém.
IMAGEM_ACAO = "kick"                 # quem manda imagem bloqueada: "kick" (expulsa) | "ban" (bane) | "apagar" (só apaga a mensagem e avisa no log)
GOLPE_ACAO = "ban"                   # quem manda golpe (TERMOS_BAN ou link falso de Nitro/Steam): "ban" ou "kick"
LIMITE_IMAGENS_REGISTRADAS = 150     # máximo de imagens bloqueadas por comando

# ⚠️ A LISTA FICA VAZIA DE PROPÓSITO. O código antigo vinha com 9 hashes que podem não ser escolhas suas, e junto com a
# comparação "parecida" eles podiam punir imagem inocente. Agora só vale o que VOCÊ bloquear com /bloquear_imagem.
# Se algum dos hashes antigos era seu, é só colocar de volta aqui dentro (entre aspas, separados por vírgula):
#   '9977339a644d9a62', '936c6c4e946cd966', '9748a8dcbd4a2579', 'c48ff019712fe2c6', '91ac6db293ab09a6',
#   'c1e1eb965c5e5cd0', 'f5de4a08bdbd5aa5', '956a6e944ac9a6c9', '931e6ae394d3486f'
IMAGENS_BLOQUEADAS = []

LIMITE_DOWNLOAD = 25 * 1024 * 1024   # ignora arquivos maiores que isso
EXT_IMAGEM = (".png", ".apng", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff")
URL_REGEX = re.compile(r'https?://[^\s<>|"\']+', re.IGNORECASE)
HEADERS_NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
CONVITE_RE = re.compile(
    r'(?:discord(?:app)?\s*\.\s*gg|discord(?:app)?\s*\.\s*com\s*/\s*invite|dsc\s*\.\s*gg|invite\s*\.\s*gg|discord\s*\.\s*me)'
    r'\s*/\s*(?P<codigo>[a-z0-9-]+)',
    re.IGNORECASE
)
EMOJI_CUSTOM_RE = re.compile(r'<a?:\w+:\d+>')
EMOJI_UNICODE_RE = re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF]')
REPETICAO_RE = re.compile(r'(.)\1{24,}', re.DOTALL)

# ==================== FILTRO DE TEXTO (PALAVRA INTEIRA) ====================
# Por que existe: o filtro antigo juntava a frase inteira sem espaços ("fiqueienrolandoumpouco") e procurava
# o palavrão DENTRO do texto, então "enrolando" e "desenrolado" (que têm "rola") eram apagados.
# Agora o texto é separado em palavras e só vale quando a palavra INTEIRA é o palavrão.
LEET = str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '$': 's', '@': 'a'})
LEET_ARROBA_PREFIXO = str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '$': 's', '@': ' '})

def limpar_texto(texto, arroba_e_letra=True):
    """Minúsculo, sem acento, sem caracteres invisíveis e com número/símbolo trocado por letra (p0rr4 -> porra)."""
    texto = re.sub(r'<a?:\w+:\d+>|<(?:@[!&]?|#)\d+>', ' ', texto)  # emojis customizados e menções não contam
    texto = unicodedata.normalize('NFKD', texto.lower())
    texto = ''.join(c for c in texto if unicodedata.category(c) not in ('Mn', 'Cf'))
    return texto.translate(LEET if arroba_e_letra else LEET_ARROBA_PREFIXO)

def reduzir(texto):
    """Junta letras repetidas: porrrra -> pora (a lista também é reduzida, então 'porra' continua casando)."""
    return re.sub(r'(.)\1+', r'\1', texto)

def tokenizar(texto, arroba_e_letra=True):
    """Quebra o texto em palavras (só letras). 'pica-pau' vira uma palavra só, e 'p-o-r-r-a' também."""
    limpo = re.sub(r'(?<=[a-z])-(?=[a-z])', '', limpar_texto(texto, arroba_e_letra))
    return re.findall(r'[a-z]+', limpo)

def compilar_lista(entradas):
    """Separa a lista em palavras soltas e expressões (as com espaço)."""
    palavras, frases = {}, []
    for entrada in entradas:
        partes = re.findall(r'[a-z]+', limpar_texto(entrada))
        if not partes:
            continue
        junto = reduzir(''.join(partes))
        if len(partes) == 1:
            palavras[junto] = entrada
        else:
            frases.append((junto, entrada))
    return palavras, frases

def achar_na_lista(texto, lista):
    """Devolve o item da lista que aparece no texto (ou None). Só vale palavra INTEIRA, nunca pedaço de outra palavra."""
    achado = _achar(tokenizar(texto), lista)
    if achado is None and '@' in texto:
        # "@rola": aqui o @ é só um prefixo (tipo menção), não a letra "a"
        achado = _achar(tokenizar(texto, arroba_e_letra=False), lista)
    return achado

def _achar(tokens, lista):
    palavras, frases = lista
    if not tokens:
        return None
    reduzidos = [reduzir(t) for t in tokens]

    # 1) Palavra solta inteira (aceita plural com "s": putas, rolas...)
    for r in reduzidos:
        if r in palavras:
            return palavras[r]
        if len(r) > 1 and r.endswith('s') and r[:-1] in palavras:
            return palavras[r[:-1]]

    # 2) Expressões com várias palavras (separadas, coladas, com hífen, letra por letra...)
    for junto, entrada in frases:
        limite = len(junto) + 3
        for i, r in enumerate(reduzidos):
            if not junto.startswith(r):
                continue
            atual = ""
            for j in range(i, min(len(tokens), i + limite)):
                for ch in tokens[j]:
                    if not atual or atual[-1] != ch:
                        atual += ch
                if atual == junto:
                    return entrada
                if not junto.startswith(atual):
                    break

    # 3) Letras soltas ("p o r r a", "f.d.p", "k_r_l"): junta SÓ as letras que estão sozinhas
    corrida = []
    for t in tokens + ['']:
        if len(t) == 1:
            corrida.append(t)
            continue
        if len(corrida) >= 3:
            junta = reduzir(''.join(corrida))
            for forma, entrada in palavras.items():
                if forma in junta:
                    return entrada
        corrida = []
    return None

TERMOS_BAN_C = compilar_lista(TERMOS_BAN)
PALAVROES_C = compilar_lista(PALAVROES)

def achar_convite(texto):
    """Devolve o convite de OUTRO servidor que aparece no texto (ou None). Pega 'discord . gg / abc', caractere invisível e até letras espaçadas."""
    limpo = ''.join(c for c in texto if unicodedata.category(c) != 'Cf')
    achou_normal = False
    for m in CONVITE_RE.finditer(limpo):
        achou_normal = True
        if m.group("codigo").lower() not in CONVITES_PERMITIDOS:
            return m.group(0)
    if achou_normal:
        return None   # só tinha convite liberado (CONVITES_PERMITIDOS)
    # 2ª tentativa sem espaços nenhum: "d i s c o r d . g g / a b c"
    for m in CONVITE_RE.finditer(re.sub(r'\s+', '', limpo)):
        if m.group("codigo").lower() not in CONVITES_PERMITIDOS:
            return m.group(0)
    return None

def dominio_permitido(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in DOMINIOS_PERMITIDOS)

def achar_link_golpe(texto):
    """Devolve o link de golpe (site falso de Nitro/Steam) que aparece no texto, ou None."""
    for url in URL_REGEX.findall(texto or ""):
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            continue
        if any(parte in host for parte in LINKS_GOLPE_PARTES):
            return url[:100]
    return None

def achar_formatacao_abusiva(texto):
    """Linhas demais, emoji demais, caractere repetido, GRITARIA e texto 'zalgo'. Devolve o motivo ou None."""
    if not texto:
        return None
    if texto.count("\n") >= MAX_LINHAS:
        return "mensagem com linhas demais"
    emojis = len(EMOJI_CUSTOM_RE.findall(texto)) + len(EMOJI_UNICODE_RE.findall(texto))
    if emojis >= MAX_EMOJIS:
        return "excesso de emojis"
    if REPETICAO_RE.search(texto):
        return "caracteres repetidos demais"
    base = re.sub(r'<[^>]+>|https?://\S+', '', texto)
    letras = [c for c in base if c.isalpha()]
    if len(letras) >= MIN_LETRAS_CAPS and sum(1 for c in letras if c.isupper()) / len(letras) >= MAX_CAPS_PCT:
        return "excesso de letras maiúsculas"
    # Acento normal vira 1 caractere só no NFC; o que sobra de "marca combinada" é texto zalgo (Z̷̡a̶l̴g̸o̵)
    if sum(1 for c in unicodedata.normalize('NFC', texto) if unicodedata.category(c) == 'Mn') >= 10:
        return "texto com símbolos abusivos"
    return None

def cortar(texto, limite=1000):
    """Corta o texto no limite (com …) para caber nos campos do embed."""
    texto = str(texto if texto is not None else "")
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"

def bloco(texto, limite=900):
    """Texto dentro de um bloco de código (sem deixar o texto quebrar o bloco)."""
    return "```" + cortar(texto, limite).replace("```", "'''") + "```"

def parse_duracao(texto):
    """'30m', '2h', '1d12h', '1w' -> segundos (ou None se não entendeu)."""
    texto = (texto or "").lower().strip()
    partes = re.findall(r'(\d+)\s*([smhdw])', texto)
    if not partes or re.sub(r'(\d+)\s*([smhdw])|\s', '', texto):
        return None
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return sum(int(n) * mult[u] for n, u in partes)

# ==================== ANÁLISE DE IMAGENS (HASH) ====================
# SÓ IMAGEM IDÊNTICA É PEGA (não existe "imagem parecida"):
#   - Imagem do /bloquear_imagem: o bot guarda 3 hashes dela (average, phash e dhash). Só vale se os TRÊS forem iguais.
#   - Hash solto do código (IMAGENS_BLOQUEADAS): não dá pra saber de qual tipo ele é, então vale se algum dos 3 hashes
#     da imagem enviada for IGUAL ao da lista.
ALGORITMOS = ("average", "phash", "dhash")

HASHES_FIXOS = []   # (hash_em_texto, ImageHash)
for _hex in IMAGENS_BLOQUEADAS:
    try:
        _h = imagehash.hex_to_hash(_hex)
        if _h.hash.shape != (8, 8):
            raise ValueError("o hash precisa ter 16 caracteres (tamanho padrão 8x8)")
        if not 4 <= bin(int(_hex, 16)).count("1") <= 60:
            raise ValueError("hash 'liso' demais (imagem quase sem detalhe): pegaria imagem inocente")
        HASHES_FIXOS.append((_hex, _h))
    except Exception as _erro:
        print(f"[Aviso] Hash ignorado ({_hex}): {_erro}")

HASHES_REGISTRADOS = []   # (nome, {algoritmo: ImageHash}) das imagens do /bloquear_imagem

def reconstruir_hashes(registradas):
    """Recarrega a lista das imagens bloqueadas por comando. Troca a lista de uma vez (seguro com threads)."""
    global HASHES_REGISTRADOS
    HASHES_REGISTRADOS = [
        (e["nome"], {alg: imagehash.hex_to_hash(e["hashes"][alg]) for alg in ALGORITMOS})
        for e in registradas
    ]

def avaliar_imagem(dados):
    """
    Roda em OUTRA THREAD (não trava o bot). Calcula os hashes da imagem (e de alguns frames, se for GIF/WEBP animado)
    e confere se ela é IDÊNTICA a alguma imagem bloqueada.
    Retorna (frames, achado, menor):
      achado = (origem, detalhe) da imagem bloqueada que ela repete (ou None se não repete nenhuma)
      menor  = (distância, origem) da imagem bloqueada mais próxima. Serve só para o /testar_imagem mostrar: NÃO pune ninguém.
    """
    frames = []
    with Image.open(BytesIO(dados)) as img:
        total = max(1, getattr(img, "n_frames", 1))
        for i in sorted({0, total // 3, (total * 2) // 3, total - 1}):
            try:
                img.seek(i)
            except EOFError:
                break
            rgb = img.convert("RGB")
            frames.append({
                "average": imagehash.average_hash(rgb),
                "phash": imagehash.phash(rgb),
                "dhash": imagehash.dhash(rgb),
            })

    registradas = HASHES_REGISTRADOS   # "foto" da lista neste momento
    menor = None
    for hashes in frames:
        candidatos = []
        for nome, alvo in registradas:
            candidatos.append((max(int(hashes[a] - alvo[a]) for a in ALGORITMOS), nome, "average + phash + dhash"))
        for _, alvo in HASHES_FIXOS:
            dist, alg = min((int(hashes[a] - alvo), a) for a in ALGORITMOS)
            candidatos.append((dist, "lista", alg))
        for dist, origem, detalhe in candidatos:
            if dist == 0:
                return frames, (origem, detalhe), (0, origem)
            if menor is None or dist < menor[0]:
                menor = (dist, origem)
    return frames, None, menor

def eh_hash_liso(hashes):
    """True se a imagem tem quase nenhum detalhe (uma cor só, degradê...): o hash dela bateria com muita imagem inocente."""
    def bits(alg):
        return bin(int(str(hashes[alg]), 16)).count("1")
    return not (4 <= bits("average") <= 60 and 4 <= bits("dhash") <= 60 and bits("phash") >= 16)

def limpar_nome(nome):
    """Nome simples (letras, números, espaço, - . ( )), numa linha só e com no máximo 50 caracteres."""
    nome = re.sub(r'[^\w\s\-.()]', '', nome or '')
    return re.sub(r'\s+', ' ', nome).strip()[:50]

def proximo_nome_livre(usados):
    n = 1
    while f"imagem-{n}" in usados:
        n += 1
    return f"imagem-{n}"

# Formato da mensagem que guarda cada imagem bloqueada no canal de registro (só os hashes, NUNCA a imagem)
REGISTRO_RE = re.compile(
    r"Imagem bloqueada\*\* — (?P<nome>[^\n]*)\n"
    r"`average` `(?P<average>[0-9a-f]{16})`\n"
    r"`phash` `(?P<phash>[0-9a-f]{16})`\n"
    r"`dhash` `(?P<dhash>[0-9a-f]{16})`\n"
    r"👤 Por: <@(?P<por>\d+)> • <t:(?P<quando>\d+):f>"
)

def montar_registro(nome, hashes_hex, user_id, quando):
    return (
        f"🚫 **Imagem bloqueada** — {nome}\n"
        f"`average` `{hashes_hex['average']}`\n"
        f"`phash` `{hashes_hex['phash']}`\n"
        f"`dhash` `{hashes_hex['dhash']}`\n"
        f"👤 Por: <@{user_id}> • <t:{int(quando)}:f>\n"
        f"-# Não apague esta mensagem: é ela que guarda a lista. Para desbloquear, use /desbloquear_imagem."
    )

def ler_registro(texto):
    m = REGISTRO_RE.search(texto or "")
    if not m:
        return None
    return {
        "nome": m.group("nome").strip(),
        "hashes": {alg: m.group(alg) for alg in ALGORITMOS},
        "por": int(m.group("por")),
        "quando": int(m.group("quando")),
    }

# Formato da mensagem que guarda cada warn no canal de registro
WARN_RE = re.compile(
    r"Warn\*\* — <@(?P<alvo>\d+)> • por <@(?P<staff>\d+)> • <t:(?P<quando>\d+):f>\n"
    r"Motivo: (?P<motivo>.*)",
    re.DOTALL
)

def montar_warn(alvo_id, staff_id, quando, motivo):
    return f"⚠️ **Warn** — <@{alvo_id}> • por <@{staff_id}> • <t:{int(quando)}:f>\nMotivo: {motivo}"

def ler_warn(texto):
    m = WARN_RE.search(texto or "")
    if not m:
        return None
    return {
        "alvo": int(m.group("alvo")), "staff": int(m.group("staff")),
        "quando": int(m.group("quando")), "motivo": m.group("motivo").strip(),
    }

def nome_seguro(nome):
    """Nome de arquivo seguro para anexar no Discord (só letras/números + extensão de imagem)."""
    base, ext = os.path.splitext(nome or "")
    ext = ext.lower() if ext.lower() in EXT_IMAGEM else ".png"
    base = re.sub(r'[^A-Za-z0-9_-]', '_', base)[:40] or "imagem"
    return base + ext

def coletar_fontes_imagem(message, so_embeds=False):
    """Lista (url, nome, anexo) de tudo que parece imagem na mensagem: anexos, encaminhadas, links e prévias."""
    fontes = []

    if not so_embeds:
        anexos = list(message.attachments)
        # Mensagem ENCAMINHADA: os anexos ficam dentro do "snapshot" da mensagem original
        for snap in (getattr(message, "message_snapshots", None) or []):
            anexos.extend(getattr(snap, "attachments", None) or [])
        for a in anexos:
            tipo = (a.content_type or "").lower()
            if tipo.startswith("image/") or a.filename.lower().endswith(EXT_IMAGEM):
                fontes.append((a.url, a.filename, a))

        # Links diretos para imagem escritos no texto
        for url in URL_REGEX.findall(message.content or ""):
            url = url.rstrip(".,;:!?)]}")
            try:
                caminho = urlparse(url).path
            except ValueError:
                continue
            if caminho.lower().endswith(EXT_IMAGEM):
                fontes.append((url, os.path.basename(caminho), None))

    # Prévias de link (embeds): o Discord gera depois, e avisa editando a mensagem
    for emb in message.embeds:
        for midia in (emb.image, emb.thumbnail):
            url = getattr(midia, "proxy_url", None) or getattr(midia, "url", None)
            if url:
                fontes.append((url, "previa.png", None))

    unicas, vistas = [], set()
    for fonte in fontes:
        if fonte[0] not in vistas:
            vistas.add(fonte[0])
            unicas.append(fonte)
    return unicas[:10]

# ==================== BANCO DE DADOS (XP, sorteios, AFK) ====================
class Banco:
    """
    Guarda XP, sorteios, AFK e o contador de tickets. Fica na memória (rápido) e é salvo a cada 2 minutos:
      1) como ARQUIVO ANEXADO numa mensagem do canal privado #bot-dados (sobrevive mesmo se a hospedagem apagar arquivos)
      2) numa cópia local de reserva (dados_k7ng.json), se a hospedagem deixar gravar
    """
    def __init__(self):
        self.dados = self.vazio()
        self.sujo = False        # True = tem coisa nova para salvar
        self.msg_id = None       # mensagem do #bot-dados que guarda o arquivo
        self.trava = None

    @staticmethod
    def vazio():
        return {"xp": {}, "sorteios": {}, "afk": {}, "tickets": 0}

    def _completar(self):
        if not isinstance(self.dados, dict):
            self.dados = self.vazio()
        for chave, valor in self.vazio().items():
            self.dados.setdefault(chave, valor)

    async def carregar(self, guild):
        """
        Lê o banco do Discord (ou do arquivo local de reserva). Devolve False se NÃO conseguiu ler: nesse caso o bot
        não salva nada por cima (para nunca apagar os seus dados por causa de um erro passageiro).
        """
        self.trava = asyncio.Lock()
        canal = await obter_canal_privado(guild, NOME_CANAL_DADOS, TOPICO_DADOS)
        lido = False
        if canal:
            for tentativa in range(3):
                try:
                    async for msg in canal.history(limit=100):
                        if msg.author.id != bot.user.id:
                            continue
                        anexo = next((a for a in msg.attachments if a.filename == NOME_ARQUIVO_DADOS), None)
                        if anexo is None:
                            continue
                        self.dados = json.loads((await anexo.read()).decode("utf-8"))
                        self.msg_id = msg.id
                        lido = True
                        break
                    break   # leu o canal inteiro sem erro (achando o arquivo ou não)
                except ValueError as e:   # JSON corrompido
                    print(f"[ERRO] O arquivo do banco no canal #{NOME_CANAL_DADOS} está corrompido: {e!r}")
                    return False
                except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError) as e:
                    print(f"[Aviso] Falha ao ler o banco (tentativa {tentativa + 1}/3): {e!r}")
                    await asyncio.sleep(3)
            else:
                return False   # 3 falhas seguidas
        if not lido and os.path.exists(ARQUIVO_LOCAL):
            try:
                with open(ARQUIVO_LOCAL, "r", encoding="utf-8") as f:
                    self.dados = json.load(f)
                lido = True
                self.sujo = True   # manda a cópia local para o Discord no próximo salvamento
            except Exception as e:
                print(f"[Aviso] Não consegui ler {ARQUIVO_LOCAL}: {e!r}")
        self._completar()
        print(f"[Banco] {'Carregado' if lido else 'Começando vazio'}: {len(self.dados['xp'])} membro(s) com XP, "
              f"{len(self.dados['sorteios'])} sorteio(s), {len(self.dados['afk'])} AFK.")
        return True

    async def salvar(self, guild=None):
        if self.trava is None:
            self.trava = asyncio.Lock()
        async with self.trava:
            self.sujo = False
            texto = json.dumps(self.dados, ensure_ascii=False, separators=(",", ":"))
            try:
                with open(ARQUIVO_LOCAL, "w", encoding="utf-8") as f:
                    f.write(texto)
            except OSError:
                pass   # hospedagem sem permissão de gravar: tudo bem, o Discord é a cópia principal
            guild = guild or bot.get_guild(GUILD_ID)
            if guild is None:
                return

            def novo_arquivo():
                return discord.File(BytesIO(texto.encode("utf-8")), filename=NOME_ARQUIVO_DADOS)

            try:
                canal = await obter_canal_privado(guild, NOME_CANAL_DADOS, TOPICO_DADOS, criar=True)
                if self.msg_id:
                    try:
                        await canal.get_partial_message(self.msg_id).edit(attachments=[novo_arquivo()])
                        return
                    except discord.NotFound:
                        self.msg_id = None   # apagaram a mensagem: cria outra
                msg = await canal.send(
                    "💾 **Banco de dados do bot** — NÃO apague esta mensagem (é ela que guarda XP, sorteios e AFK).",
                    file=novo_arquivo()
                )
                self.msg_id = msg.id
            except Exception as e:
                self.sujo = True
                print(f"[Aviso] Não consegui salvar o banco no Discord (tento de novo em 2 min): {e!r}")

# ==================== ESTRUTURA DO BOT ====================
class MeuBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True            # precisa estar ligado no Portal do Desenvolvedor
        intents.message_content = True    # idem
        super().__init__(command_prefix="!", intents=intents, help_command=None, max_messages=5000)

        self.sessao_http = None           # sessão para baixar imagens SEM travar o bot
        self.trava_registro = None        # evita dois comandos mexendo na lista ao mesmo tempo (criada no setup_hook)
        self.imagens_registradas = {}     # imagens do /bloquear_imagem (id da mensagem do registro -> dados)
        self.warns = defaultdict(list)    # id do usuário -> lista de warns
        self.registros_carregados = False
        self.banco = Banco()              # XP, sorteios, AFK...
        self.banco_carregado = False

        # logs
        self.canais_log = {}              # tipo de log -> id do canal em uso
        self.travas_log = {}              # tipo de log -> Lock (evita criar o mesmo canal duas vezes)
        self.falha_log = {}               # tipo de log -> quando falhou criar o canal (não insiste por 5 min)
        self.ignorar_delete = set()       # mensagens que o próprio bot apagou (não repetir no #logs-mensagem)
        self.silenciar_saida = set()      # membros que o bot expulsou/baniu (sem aviso de "saiu")

        # automod
        self.hist_msgs = defaultdict(deque)   # id -> (quando, canal, mensagem, conteúdo)
        self.pontos = defaultdict(deque)      # id -> (quando, pontos)
        self.punindo = set()                  # quem está sendo punido agora (evita punição dupla)
        self.banindo = set()                  # quem está sendo banido agora (evita ban duplicado)

        # anti-raid
        self.entradas_recentes = deque()      # (quando, id)
        self.raid_ate = 0.0                   # time.monotonic() até quando o modo raid dura (0 = desligado)
        self.raid_expulsos = 0

        # anti-nuke
        self.nuke_hist = defaultdict(deque)   # (id, ação) -> (quando, alvo)
        self.nuke_punidos = {}                # id -> quando foi punido (evita reagir duas vezes)

        # lockdown
        self.lock_estado = {}                 # (canal, cargo) -> permissões que o canal tinha antes de travar

        # extras
        self.convites = {}                    # código do convite -> usos (para descobrir quem convidou)
        self.xp_cooldown = {}                 # id -> time.monotonic() da última mensagem que deu XP
        self.tickets_fechando = set()         # canais de ticket que estão sendo fechados agora
        self.criando_ticket = set()           # quem está criando ticket agora (evita clique duplo)

    async def setup_hook(self):
        self.sessao_http = aiohttp.ClientSession()
        self.trava_registro = asyncio.Lock()
        self.add_view(ViewTicketsBotoes())
        self.add_view(ViewTicketsMenu())
        self.add_view(ViewTicketControle())
        self.add_view(ViewVerificar())
        self.add_view(ViewBooster())
        self.add_dynamic_items(BotaoCargo)
        manutencao.start()
        salvar_banco.start()
        loop_sorteios.start()
        try:
            await self.tree.sync(guild=GUILD_OBJ)   # comandos SÓ no K7NG
            await self.tree.sync()                  # limpa os comandos globais da versão antiga (nada vaza para outros servidores)
        except discord.HTTPException as e:
            print(f"[ERRO] Não consegui sincronizar os comandos (o bot foi convidado com o escopo 'applications.commands'?): {e}")

    async def close(self):
        try:
            if self.banco_carregado and self.banco.sujo:
                await self.banco.salvar()   # último salvamento antes de desligar
        except Exception as e:
            print(f"[Aviso] Não consegui salvar o banco ao desligar: {e!r}")
        if self.sessao_http:
            await self.sessao_http.close()
        await super().close()

bot = MeuBot()
GUILD_OBJ = discord.Object(id=GUILD_ID)

def comando(**kwargs):
    """Registra o comando de barra SÓ no K7NG."""
    return bot.tree.command(guild=GUILD_OBJ, **kwargs)

def exige(**perms):
    """Exige a permissão de verdade na hora de usar (o default_permissions sozinho o servidor pode mudar)."""
    def deco(func):
        func = app_commands.checks.has_permissions(**perms)(func)
        func = app_commands.default_permissions(**perms)(func)
        return func
    return deco

def exige_exec(**perms):
    """Para subcomandos de grupo: só a checagem na hora de usar (a permissão padrão fica no grupo)."""
    def deco(func):
        return app_commands.checks.has_permissions(**perms)(func)
    return deco

# Grupos de comandos (/sorteio ... e /ticket ...)
sorteio_grupo = app_commands.Group(
    name="sorteio", description="Sorteios com reação 🎉", guild_only=True,
    default_permissions=discord.Permissions(manage_guild=True)
)
ticket_grupo = app_commands.Group(name="ticket", description="Comandos para usar dentro de um ticket", guild_only=True)
bot.tree.add_command(sorteio_grupo, guild=GUILD_OBJ)
bot.tree.add_command(ticket_grupo, guild=GUILD_OBJ)

# ==================== FUNÇÕES AUXILIARES ====================
class Anonimo:
    """Representa alguém que não deu para buscar no Discord (só temos o ID)."""
    display_avatar = None

    def __init__(self, uid):
        self.id = int(uid)
        self.name = str(uid)
        self.mention = f"<@{uid}>"

def eh_confiavel(guild, uid):
    """Dono do servidor, o próprio bot e a WHITELIST_IDS: nunca são punidos pelo anti-nuke."""
    return uid == bot.user.id or uid == guild.owner_id or uid in WHITELIST_IDS

def eh_staff(membro):
    if not isinstance(membro, discord.Member):
        return False
    if eh_confiavel(membro.guild, membro.id):
        return True
    p = membro.guild_permissions
    if p.administrator or p.manage_guild or p.manage_messages or p.moderate_members or p.kick_members or p.ban_members:
        return True
    if CARGO_STAFF and membro.get_role(CARGO_STAFF):
        return True
    return any(membro.get_role(i) for i in CARGOS_STAFF_EXTRA)

def eh_novato(membro):
    entrou = getattr(membro, "joined_at", None)
    if not entrou:
        return False
    return (discord.utils.utcnow() - entrou).total_seconds() < NOVATO_SEM_LINKS_MIN * 60

def formatar_duracao(minutos):
    minutos = int(minutos)
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 1440:
        h, m = divmod(minutos, 60)
        return f"{h}h" + (f"{m}min" if m else "")
    d, resto = divmod(minutos, 1440)
    h = resto // 60
    return f"{d} dia(s)" + (f" e {h}h" if h else "")

def rodape(embed, guild):
    embed.set_footer(text=f"Segurança Ativa {NOME_SERVIDOR}", icon_url=guild.icon.url if guild.icon else None)
    return embed

def avatar_de(usuario):
    asset = getattr(usuario, "display_avatar", None)
    return asset.url if asset else None

def raid_ativo():
    return time.monotonic() < bot.raid_ate

def cargo_seguro(guild, cargo):
    """O bot consegue dar esse cargo? E ele é inofensivo (sem nenhuma permissão perigosa)?"""
    if cargo is None or cargo.is_default() or cargo.managed:
        return False
    if cargo >= guild.me.top_role:
        return False
    return not any(getattr(cargo.permissions, p, False) for p in PERMS_PERIGOSAS)

async def buscar_usuario(uid):
    if not uid:
        return None
    usuario = bot.get_user(uid)
    if usuario:
        return usuario
    try:
        return await bot.fetch_user(uid)
    except discord.HTTPException:
        return Anonimo(uid)

def marcar_ignorar(msg_id):
    """Avisa o log de mensagens que fomos NÓS que apagamos essa mensagem (o automod já registra o motivo)."""
    if len(bot.ignorar_delete) > 5000:
        bot.ignorar_delete.clear()
    bot.ignorar_delete.add(msg_id)

async def apagar_mensagens(guild, refs):
    """Apaga uma lista de (id_do_canal, id_da_mensagem), em lote quando dá."""
    por_canal = defaultdict(list)
    for canal_id, msg_id in refs:
        por_canal[canal_id].append(msg_id)
        marcar_ignorar(msg_id)
    for canal_id, ids in por_canal.items():
        canal = guild.get_channel_or_thread(canal_id)
        if canal is None:
            continue
        try:
            if len(ids) == 1:
                await canal.get_partial_message(ids[0]).delete()
            else:
                await canal.delete_messages([discord.Object(id=i) for i in ids])
        except discord.HTTPException:
            for i in ids:   # lote falhou (mensagem velha/já apagada): tenta uma por uma
                try:
                    await canal.get_partial_message(i).delete()
                except discord.HTTPException:
                    pass

async def avisar_canal(canal, texto):
    if not AVISAR_NO_CANAL:
        return
    try:
        await canal.send(texto, delete_after=10, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass

# ==================== ACHAR CANAIS E CATEGORIAS ====================
def achar_canal_por_nome(guild, nomes, publico=False):
    """
    Acha um canal de texto pelo nome. Aceita nome decorado, tipo 〖📄〗「logs-geral」 (basta conter o nome).
    publico=True só considera canais que o @everyone enxerga (para não marcar um canal de log por engano).
    """
    if isinstance(nomes, str):
        nomes = (nomes,)
    candidatos = guild.text_channels
    if publico:
        escondidos = ids_canais_log()
        candidatos = [c for c in candidatos
                      if c.id not in escondidos and c.permissions_for(guild.default_role).view_channel]
    for nome in nomes:
        for canal in candidatos:
            if canal.name == nome:
                return canal
    for nome in nomes:
        for canal in candidatos:
            if nome in canal.name.lower():
                return canal
    return None

def achar_canal_texto(guild, id_config, nomes=(), publico=False):
    """Canal pelo ID da configuração; se for 0 (ou sumiu), procura pelo nome."""
    canal = guild.get_channel(id_config) if id_config else None
    if canal is None and nomes:
        canal = achar_canal_por_nome(guild, nomes, publico)
    return canal if isinstance(canal, discord.TextChannel) else None

def achar_categoria(guild, nome):
    nome = nome.lower()
    for c in guild.categories:
        if c.name.lower() == nome:
            return c
    for c in guild.categories:
        if nome in c.name.lower():
            return c
    return None

def cargos_staff_config(guild):
    """Cargos de staff que VOCÊ configurou (CARGO_STAFF + CARGOS_STAFF_EXTRA)."""
    ids = set(CARGOS_STAFF_EXTRA)
    if CARGO_STAFF:
        ids.add(CARGO_STAFF)
    return [r for r in (guild.get_role(i) for i in ids) if r]

async def obter_categoria(guild, nome):
    """Acha (ou cria) uma categoria privada: só a staff vê."""
    categoria = achar_categoria(guild, nome)
    if categoria:
        return categoria
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True,
                                              embed_links=True, attach_files=True, read_message_history=True),
    }
    for cargo in cargos_staff_config(guild):
        overwrites[cargo] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
    return await guild.create_category(nome, overwrites=overwrites, reason="Categoria criada pelo bot de segurança")

# ==================== CANAIS PRIVADOS DO BOT ====================
async def obter_canal_privado(guild, nome, topico, criar=False, categoria=None):
    """Acha (ou cria, se criar=True) um canal privado: só a staff lê, só o bot escreve."""
    canal = discord.utils.get(guild.text_channels, name=nome)
    if canal or not criar:
        return canal

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True
        ),
    }
    for cargo in cargos_staff_config(guild):
        overwrites[cargo] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
    if categoria is None:
        ref = guild.get_channel(CANAL_BAN) if CANAL_BAN else None
        categoria = getattr(ref, "category", None)
    return await guild.create_text_channel(
        nome,
        overwrites=overwrites,
        category=categoria,
        topic=topico[:1000],
        reason="Canal privado do bot de segurança"
    )

# ==================== CANAIS DE LOG (UM PARA CADA ASSUNTO) ====================
def achar_canal_log(guild, tipo):
    """Procura (sem criar) o canal desse tipo de log: primeiro pelo ID da configuração, depois pelo nome."""
    id_config, nome, _, _ = CANAIS_LOG[tipo]
    canal = guild.get_channel(id_config) if id_config else None
    if canal is None:
        canal = achar_canal_por_nome(guild, nome)
    return canal

async def criar_canal_log(guild, tipo):
    id_config, nome, categoria_nome, descricao = CANAIS_LOG[tipo]
    if id_config:
        print(f"[Aviso] Não achei o canal de log '{tipo}' (ID {id_config}). O bot não enxerga esse canal? Vou usar/criar #{nome}.")
    try:
        categoria = await obter_categoria(guild, categoria_nome)
        return await obter_canal_privado(guild, nome, descricao, criar=True, categoria=categoria)
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui achar/criar o canal de log '{tipo}': {e}")
        return None

async def obter_canal_log(guild, tipo, criar=None):
    """Devolve o canal do tipo de log pedido (chaves de CANAIS_LOG). Cria sozinho se faltar e LOGS_AUTO_CRIAR estiver ligado."""
    em_uso = bot.canais_log.get(tipo)
    if em_uso:
        canal = guild.get_channel(em_uso)
        if canal:
            return canal
    canal = achar_canal_log(guild, tipo)
    if canal is None:
        criar = LOGS_AUTO_CRIAR if criar is None else criar
        if not criar:
            return None
        if time.monotonic() - bot.falha_log.get(tipo, -10000.0) < 300:
            return None   # falhou há pouco tempo: não fica insistindo
        async with bot.travas_log.setdefault(tipo, asyncio.Lock()):
            canal = achar_canal_log(guild, tipo)   # outra tarefa pode ter criado enquanto esperávamos
            if canal is None:
                canal = await criar_canal_log(guild, tipo)
        if canal is None:
            bot.falha_log[tipo] = time.monotonic()
            return None
    bot.canais_log[tipo] = canal.id
    return canal

# ==================== ENVIO DE LOGS ====================
async def enviar_log(guild, tipo, titulo, descricao="", campos=None, cor=COR, usuario=None, arquivo=None, canal=None):
    """Manda um embed para o canal do tipo de log pedido (ou para `canal`, se for passado). Se falhar, só avisa no console."""
    canal = canal or await obter_canal_log(guild, tipo)
    if canal is None:
        return None
    embed = discord.Embed(
        title=cortar(titulo, 250), description=cortar(descricao, 4000) or None,
        color=cor, timestamp=discord.utils.utcnow()
    )
    if usuario is not None:
        nome_exibido = getattr(usuario, "display_name", None) or usuario.name
        embed.set_author(name=f"{nome_exibido} ({usuario.id})", icon_url=avatar_de(usuario))
    for nome, valor, inline in (campos or []):
        embed.add_field(name=cortar(nome, 250), value=cortar(valor, 1000) or "—", inline=inline)
    rodape(embed, guild)
    try:
        return await canal.send(embed=embed, file=arquivo, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui enviar o log '{tipo}': {e}")
        return None

# ==================== LOGS DE PUNIÇÃO (#logs-ban e #logs-mute) ====================
async def log_punicao(guild, user, staff, acao, motivo, prova_url=None, prova_arquivo=None, prova_texto=None, tipo="ban"):
    canal = await obter_canal_log(guild, tipo)
    if not canal:
        return

    icone = "🔨" if tipo == "ban" else "🔇"
    embed = discord.Embed(title=f"{icone} {NOME_SERVIDOR} - Punição Aplicada", color=COR, timestamp=discord.utils.utcnow())
    if getattr(user, "display_avatar", None):
        embed.set_thumbnail(url=user.display_avatar.url)

    descricao = (
        f"👤 **Usuário:** {user.mention}\n"
        f"📛 **Nick:** `{user.name}`\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"🛡️ **Staff:** {staff.mention}\n"
        f"🚨 **Ação:** `{acao}`\n"
        f"📄 **Motivo:** {str(motivo)[:900]}\n"
    )
    if prova_texto:
        descricao += f"\n**Mensagem:**\n```{prova_texto[:500].replace('```', '')}```"
    embed.description = descricao

    arquivo = None
    if prova_arquivo:
        # A imagem vai ANEXADA no log: o link do Discord morre quando a mensagem é apagada
        dados, nome = prova_arquivo
        arquivo = discord.File(BytesIO(dados), filename=nome)
        embed.set_image(url=f"attachment://{nome}")
    elif prova_url:
        embed.set_image(url=prova_url)
    rodape(embed, guild)

    try:
        if arquivo:
            await canal.send(embed=embed, file=arquivo)
        else:
            await canal.send(embed=embed)
    except discord.HTTPException as e:
        if not arquivo:
            print(f"[Aviso] Não consegui enviar o log de punição: {e}")
            return
        # Arquivo grande demais para o canal: manda o log sem anexar
        if prova_url:
            embed.set_image(url=prova_url)
        else:
            embed.remove_image()
        try:
            await canal.send(embed=embed)
        except discord.HTTPException as e2:
            print(f"[Aviso] Não consegui enviar o log de punição: {e2}")

async def enviar_alerta(guild, titulo, descricao):
    """Alerta de segurança (raid, nuke, bot barrado, lockdown...) no canal de logs de ban."""
    await enviar_log(guild, "ban", titulo, descricao[:4000])

async def alertar_dono(guild, titulo, texto):
    """Avisa o dono por DM (caso o canal de alertas esteja escondido/apagado por um invasor)."""
    try:
        dono = guild.owner or await guild.fetch_member(guild.owner_id)
        await dono.send(f"**{titulo}**\n{texto}"[:1900])
    except Exception:
        pass

async def log_falha_punicao(guild, alvo, motivo, erro, verbo="banir"):
    """Avisa quando o bot NÃO conseguiu banir/expulsar (antes só aparecia no console)."""
    await enviar_alerta(
        guild,
        f"⚠️ {NOME_SERVIDOR} - Falha ao {verbo.capitalize()}",
        f"👤 **Usuário:** {alvo.mention} (`{alvo.id}`)\n"
        f"📄 **Motivo:** {motivo}\n"
        f"❌ **Erro:** `{type(erro).__name__}`\n\n"
        f"Confira se o cargo do bot está **acima** do cargo dessa pessoa e se ele tem a permissão para {verbo}. "
        f"Ninguém consegue {verbo} o dono do servidor."
    )

# ==================== LOGS DO AUTOMOD (#automod-all, -spam, -links, -profile) ====================
async def log_automod(guild, membro, motivo, canal=None, texto=None, acao="Mensagem apagada", categoria="geral"):
    """Tudo vai para #automod-all; spam, links e perfil também vão para o canal específico deles."""
    local = canal.mention if canal else "—"
    descricao = (
        f"👤 **Usuário:** {membro.mention} (`{membro.id}`)\n"
        f"📍 **Canal:** {local}\n"
        f"🚨 **Motivo:** {motivo}\n"
        f"🛡️ **Ação:** {acao}"
    )
    if texto:
        descricao += "\n\n**Mensagem:**\n" + bloco(texto, 800)
    destinos = ["automod_all"]
    especifico = {"spam": "automod_spam", "links": "automod_links", "perfil": "automod_profile"}.get(categoria)
    if especifico:
        destinos.append(especifico)
    for tipo in destinos:
        await enviar_log(guild, tipo, f"🤖 Automod — {motivo}", descricao, usuario=membro)

# ==================== LOGS DE MENSAGENS (#logs-mensagem) ====================
def ids_canais_log():
    return set(bot.canais_log.values())

async def log_mensagem_apagada(guild, msg):
    if msg is None or msg.author.bot:
        return
    if msg.id in bot.ignorar_delete:   # fomos nós que apagamos (o automod já registrou o motivo)
        bot.ignorar_delete.discard(msg.id)
        return
    if msg.channel.id in ids_canais_log():
        return
    campos = [("📍 Canal", msg.channel.mention, True), ("👤 Autor", msg.author.mention, True)]
    if msg.attachments:
        campos.append(("📎 Anexos", "\n".join(a.filename for a in msg.attachments[:10]), False))
    descricao = bloco(msg.content, 1500) if msg.content else "_(mensagem sem texto)_"
    await enviar_log(guild, "mensagens", "🗑️ Mensagem apagada", descricao, campos, cor=COR, usuario=msg.author)

async def log_mensagem_editada(antes, depois):
    if depois.author.bot or not antes.content or antes.content == depois.content:
        return
    if depois.channel.id in ids_canais_log():
        return
    campos = [
        ("📍 Canal", depois.channel.mention, True),
        ("👤 Autor", depois.author.mention, True),
        ("🔗 Ir para a mensagem", f"[clique aqui]({depois.jump_url})", True),
    ]
    descricao = f"**Antes:**\n{bloco(antes.content, 900)}\n**Depois:**\n{bloco(depois.content, 900)}"
    await enviar_log(depois.guild, "mensagens", "✏️ Mensagem editada", descricao, campos, cor=COR_AMARELA, usuario=depois.author)

async def log_apagadas_em_massa(guild, canal_id, mensagens_cache, total):
    if canal_id in ids_canais_log():
        return
    linhas = [
        f"[{m.created_at:%d/%m/%Y %H:%M:%S}] {m.author} ({m.author.id}): {m.content}"
        for m in sorted(mensagens_cache, key=lambda m: m.created_at)
    ]
    arquivo = None
    if linhas:
        arquivo = discord.File(BytesIO("\n".join(linhas).encode("utf-8")), filename="mensagens_apagadas.txt")
    descricao = f"📍 **Canal:** <#{canal_id}>\n🗑️ **Mensagens apagadas:** {total}\n💾 **Guardadas no arquivo:** {len(linhas)}"
    await enviar_log(guild, "mensagens", "🧹 Mensagens apagadas em massa", descricao, cor=COR, arquivo=arquivo)

# ==================== LOGS DE MEMBROS (#logs-geral e #logs-membros) ====================
async def log_entrada(membro, convite=None):
    guild = membro.guild
    idade = (discord.utils.utcnow() - membro.created_at).days
    descricao = (
        f"👤 {membro.mention} (`{membro.id}`)\n"
        f"📅 Conta criada {discord.utils.format_dt(membro.created_at, 'R')} ({idade} dia(s))\n"
        f"👥 Membro nº **{guild.member_count}**"
    )
    if convite:
        autor = convite.get("autor")
        quem = f" de {autor.mention}" if autor else ""
        usos = convite.get("usos")
        usos_txt = f" ({usos} uso(s))" if usos is not None else ""
        descricao += f"\n📩 Convite `{convite['codigo']}`{quem}{usos_txt}"
    if idade < 7:
        descricao += "\n⚠️ **Conta muito nova!**"
    await enviar_log(guild, "geral", "📥 Membro entrou", descricao, cor=COR_VERDE, usuario=membro)

async def log_saida(membro):
    guild = membro.guild
    cargos = [r.mention for r in membro.roles if not r.is_default()][:15]
    descricao = f"👤 {membro.mention} (`{membro.id}`)"
    if membro.joined_at:
        descricao += f"\n📅 Entrou {discord.utils.format_dt(membro.joined_at, 'R')}"
    descricao += f"\n👥 Agora são **{guild.member_count}** membros"
    if cargos:
        descricao += "\n🏷️ Cargos: " + ", ".join(cargos)
    await enviar_log(guild, "geral", "📤 Membro saiu", descricao, cor=COR, usuario=membro)

async def log_apelido(antes, depois):
    if antes.nick == depois.nick:
        return
    campos = [
        ("Antes", antes.nick or "_(sem apelido)_", True),
        ("Depois", depois.nick or "_(sem apelido)_", True),
    ]
    await enviar_log(depois.guild, "membros", "📝 Apelido alterado", f"👤 {depois.mention}", campos, cor=COR_AMARELA, usuario=depois)

async def log_usuario(antes, depois):
    """Mudou nome de usuário, nome de exibição ou foto de perfil (vale em todos os servidores, então só logamos quem está no K7NG)."""
    guild = bot.get_guild(GUILD_ID)
    membro = guild.get_member(depois.id) if guild else None
    if membro is None:
        return
    campos = []
    if antes.name != depois.name:
        campos.append(("Nome de usuário", f"`{antes.name}` ➜ `{depois.name}`", False))
    if getattr(antes, "global_name", None) != getattr(depois, "global_name", None):
        campos.append(("Nome de exibição", f"`{antes.global_name}` ➜ `{depois.global_name}`", False))
    if antes.avatar != depois.avatar:
        campos.append(("Foto de perfil", "Trocou a foto de perfil.", False))
    if campos:
        await enviar_log(guild, "membros", "👤 Perfil alterado", membro.mention, campos, cor=COR_AMARELA, usuario=membro)

# ==================== LOGS DE VOZ (#logs-voz) ====================
async def log_voz(membro, antes, depois):
    if antes.channel == depois.channel:
        return   # só mudou mute/deaf/câmera/transmissão
    if antes.channel is None:
        titulo, cor = "🔊 Entrou em canal de voz", COR_VERDE
        descricao = f"{membro.mention} entrou em {depois.channel.mention}"
    elif depois.channel is None:
        titulo, cor = "🔇 Saiu do canal de voz", COR
        descricao = f"{membro.mention} saiu de {antes.channel.mention}"
    else:
        titulo, cor = "🔀 Trocou de canal de voz", COR_AMARELA
        descricao = f"{membro.mention}: {antes.channel.mention} ➜ {depois.channel.mention}"
    await enviar_log(membro.guild, "voz", titulo, descricao, cor=cor, usuario=membro)

# ==================== LOGS DO SERVIDOR (#logs-servidor): canais, cargos, emojis... com QUEM fez ====================
CHAVES_RUIDO = {"position", "id", "type"}

def descrever_mudancas(entry, limite=10):
    """Resume o que mudou numa entrada do Registro de Auditoria (antes ➜ depois)."""
    try:
        antes, depois = dict(entry.before), dict(entry.after)
    except Exception:
        return ""
    linhas = []
    for chave in list(dict.fromkeys(list(depois) + list(antes))):
        if chave in CHAVES_RUIDO:
            continue
        a, d = antes.get(chave), depois.get(chave)
        if a == d:
            continue
        if isinstance(a, discord.Permissions) or isinstance(d, discord.Permissions):
            pa = dict(a) if a is not None else {}
            pd = dict(d) if d is not None else {}
            ganhou = [p for p, v in pd.items() if v and not pa.get(p)]
            perdeu = [p for p, v in pa.items() if v and not pd.get(p)]
            if ganhou:
                linhas.append("➕ Permissões: " + ", ".join(ganhou))
            if perdeu:
                linhas.append("➖ Permissões: " + ", ".join(perdeu))
            continue
        if chave == "overwrites":
            linhas.append("🔐 Permissões do canal alteradas")
            continue
        linhas.append(f"**{chave}:** `{cortar(a, 60)}` ➜ `{cortar(d, 60)}`")
    return "\n".join(linhas[:limite])

def nome_do_alvo(entry):
    for lado in (entry.after, entry.before):
        nome = getattr(lado, "name", None)
        if nome:
            return nome
    return "?"

async def log_auditoria(entry):
    """Registra mudanças no servidor e cargos dados/tirados de membros, sempre dizendo QUEM fez."""
    guild = entry.guild
    if entry.user_id == bot.user.id:
        return   # o que o próprio bot faz já tem log próprio
    A = discord.AuditLogAction
    acao = entry.action
    quem = f"<@{entry.user_id}>" if entry.user_id else "desconhecido"
    nome = nome_do_alvo(entry)
    tipo, cor = "servidor", COR_AMARELA

    if acao is A.channel_create:
        titulo, cor, descricao = "📁 Canal criado", COR_VERDE, f"Canal: <#{entry.target_id}> (`{nome}`)"
    elif acao is A.channel_delete:
        titulo, cor, descricao = "🗑️ Canal apagado", COR, f"Canal: `{nome}` (`{entry.target_id}`)"
    elif acao is A.channel_update:
        titulo, descricao = "🛠️ Canal editado", f"Canal: <#{entry.target_id}>\n{descrever_mudancas(entry)}"
    elif acao is A.role_create:
        titulo, cor, descricao = "🏷️ Cargo criado", COR_VERDE, f"Cargo: <@&{entry.target_id}> (`{nome}`)"
    elif acao is A.role_delete:
        titulo, cor, descricao = "🗑️ Cargo apagado", COR, f"Cargo: `{nome}` (`{entry.target_id}`)"
    elif acao is A.role_update:
        titulo, descricao = "🛠️ Cargo editado", f"Cargo: <@&{entry.target_id}>\n{descrever_mudancas(entry)}"
    elif acao in (A.emoji_create, A.emoji_delete, A.emoji_update):
        rotulo = {A.emoji_create: "criado", A.emoji_delete: "apagado", A.emoji_update: "editado"}[acao]
        titulo, descricao = f"😀 Emoji {rotulo}", f"Emoji: `{nome}`"
        cor = COR_VERDE if acao is A.emoji_create else (COR if acao is A.emoji_delete else COR_AMARELA)
    elif acao in (A.webhook_create, A.webhook_delete):
        criado = acao is A.webhook_create
        titulo, cor = ("🪝 Webhook criado" if criado else "🪝 Webhook apagado"), (COR_VERDE if criado else COR)
        descricao = f"Webhook: `{nome}`"
    elif acao in (A.invite_create, A.invite_delete):
        codigo = getattr(entry.after, "code", None) or getattr(entry.before, "code", None) or "?"
        criado = acao is A.invite_create
        titulo, cor = ("🔗 Convite criado" if criado else "🔗 Convite apagado"), (COR_VERDE if criado else COR)
        descricao = f"Convite: `{codigo}`"
    elif acao is A.guild_update:
        titulo, descricao = "⚙️ Servidor editado", descrever_mudancas(entry)
    elif acao is A.member_role_update:
        tipo = "membros"
        titulo = "🏷️ Cargos de membro alterados"
        descricao = f"Membro: <@{entry.target_id}>"
        adicionados = [f"<@&{r.id}>" for r in (getattr(entry.after, "roles", None) or [])]
        removidos = [f"<@&{r.id}>" for r in (getattr(entry.before, "roles", None) or [])]
        if adicionados:
            descricao += "\n➕ Adicionou: " + ", ".join(adicionados)
        if removidos:
            descricao += "\n➖ Removeu: " + ", ".join(removidos)
    else:
        return

    descricao += f"\n👮 **Por:** {quem}"
    if entry.reason:
        descricao += f"\n📄 **Motivo:** {entry.reason}"
    await enviar_log(guild, tipo, titulo, descricao, cor=cor)

# ==================== LOG DE COMANDOS DA STAFF (#logs-geral) ====================
async def log_comando(interaction, command):
    if interaction.guild is None or interaction.guild.id != GUILD_ID:
        return
    raiz = command.qualified_name.split()[0]
    if raiz in COMANDOS_SEM_LOG:
        return
    try:
        params = ", ".join(f"{k}={cortar(v, 40)}" for k, v in list(vars(interaction.namespace).items())[:6])
    except Exception:
        params = ""
    descricao = f"👤 {interaction.user.mention} usou `/{command.qualified_name}`"
    if interaction.channel is not None:
        descricao += f"\n📍 {interaction.channel.mention}"
    if params:
        descricao += f"\n⚙️ `{cortar(params, 300)}`"
    await enviar_log(interaction.guild, "geral", "⌨️ Comando usado", descricao, usuario=interaction.user)

# ==================== PUNIÇÕES ====================
def bot_pode_punir(guild, alvo):
    """False se o bot com certeza NÃO consegue banir/expulsar essa pessoa (dono do servidor ou cargo igual/maior que o do bot)."""
    if alvo.id == guild.owner_id:
        return False
    if isinstance(alvo, discord.Member) and alvo.top_role >= guild.me.top_role:
        return False
    return True

async def executar_banimento(guild, alvo, staff, motivo, acao_log, prova_url=None, prova_arquivo=None,
                             apagar_segundos=0, prova_texto=None):
    if alvo.id in bot.banindo:
        return True  # já tem um ban em andamento para essa pessoa (ex.: várias imagens de uma vez)
    bot.banindo.add(alvo.id)

    try:
        if not bot_pode_punir(guild, alvo):
            print(f"[ERRO PERMISSÃO] Não dá para banir {alvo.name} ({alvo.id}): dono do servidor ou cargo acima do bot.")
            try:
                await log_falha_punicao(guild, alvo, motivo, PermissionError("hierarquia de cargos"), "banir")
            except Exception:
                pass
            return False

        carta_dm = (
            f"**{NOME_SERVIDOR} | Aviso de Banimento**\n\n"
            f"Caro(a) {alvo.mention},\n\n"
            f"Você foi banido(a) por violar as nossas regras.\n\n"
            f"**Motivo:** {motivo}\n\n"
            f"A decisão de banir permanece final e não será revertida sem uma consideração significativa da nossa equipe.\n\n"
            f"*Atenciosamente,*\n"
            f"**Equipe de Moderação - {NOME_SERVIDOR}**"
        )
        try:
            await alvo.send(carta_dm)
        except Exception:
            pass

        try:
            kwargs = {"reason": f"{staff.name} | {motivo}"[:480]}
            if apagar_segundos:
                kwargs["delete_message_seconds"] = min(int(apagar_segundos), 604800)
            bot.silenciar_saida.add(alvo.id)
            try:
                await guild.ban(alvo, **kwargs)
            except TypeError:   # discord.py antigo (< 2.1) não conhece delete_message_seconds
                kwargs.pop("delete_message_seconds", None)
                await guild.ban(alvo, **kwargs)
        except Exception as e:
            bot.silenciar_saida.discard(alvo.id)
            print(f"[ERRO PERMISSÃO] Não foi possível banir o usuário {alvo.name} ({alvo.id}). Detalhe: {e}")
            try:
                await log_falha_punicao(guild, alvo, motivo, e, "banir")
            except Exception:
                pass
            return False

        try:
            await log_punicao(guild, alvo, staff, acao_log, motivo, prova_url, prova_arquivo, prova_texto)
        except Exception as e:
            print(f"[Aviso] {alvo.name} foi banido, mas o log da punição falhou: {e}")
        return True
    finally:
        bot.banindo.discard(alvo.id)

async def executar_expulsao(guild, alvo, staff, motivo, acao_log, dm=True,
                            prova_url=None, prova_arquivo=None, prova_texto=None):
    if alvo.id in bot.banindo:
        return True   # já tem uma punição em andamento para essa pessoa (ex.: várias imagens de uma vez)
    bot.banindo.add(alvo.id)
    try:
        if not bot_pode_punir(guild, alvo):
            print(f"[ERRO PERMISSÃO] Não dá para expulsar {alvo.name} ({alvo.id}): dono do servidor ou cargo acima do bot.")
            try:
                await log_falha_punicao(guild, alvo, motivo, PermissionError("hierarquia de cargos"), "expulsar")
            except Exception:
                pass
            return False
        if dm:
            try:
                await alvo.send(f"**{NOME_SERVIDOR}** — você foi expulso(a).\n**Motivo:** {motivo}")
            except Exception:
                pass
        bot.silenciar_saida.add(alvo.id)
        try:
            await guild.kick(alvo, reason=f"{staff.name} | {motivo}"[:480])
        except discord.NotFound:
            bot.silenciar_saida.discard(alvo.id)
            return True   # a pessoa já tinha saído do servidor
        except Exception as e:
            bot.silenciar_saida.discard(alvo.id)
            print(f"[ERRO PERMISSÃO] Não foi possível expulsar {alvo.name} ({alvo.id}). Detalhe: {e}")
            try:
                await log_falha_punicao(guild, alvo, motivo, e, "expulsar")
            except Exception:
                pass
            return False
        try:
            await log_punicao(guild, alvo, staff, acao_log, motivo, prova_url, prova_arquivo, prova_texto)
        except Exception as e:
            print(f"[Aviso] {alvo.name} foi expulso, mas o log da punição falhou: {e}")
        return True
    finally:
        bot.banindo.discard(alvo.id)

async def aplicar_mute(guild, membro, staff, minutos, motivo, acao_log):
    minutos = max(1, min(int(minutos), 40320))   # o Discord aceita no máximo 28 dias
    try:
        await membro.timeout(datetime.timedelta(minutes=minutos), reason=f"{staff.name} | {motivo}"[:480])
    except Exception as e:
        print(f"[ERRO PERMISSÃO] Não foi possível silenciar {getattr(membro, 'name', membro.id)}. Detalhe: {e}")
        return False
    try:
        await log_punicao(guild, membro, staff, f"{acao_log} ({formatar_duracao(minutos)})", motivo, tipo="mute")
    except Exception as e:
        print(f"[Aviso] Mute aplicado, mas o log da punição falhou: {e}")
    return True

async def remover_cargos(membro, motivo):
    """Tira todos os cargos que o bot consegue tirar (usado quando não dá para banir quem fez nuke)."""
    guild = membro.guild
    alvos = [r for r in membro.roles if not r.is_default() and not r.managed and r < guild.me.top_role]
    if not alvos:
        return []
    try:
        await membro.remove_roles(*alvos, reason=motivo[:480])
        return alvos
    except discord.HTTPException:
        return []

# ==================== REGISTROS GUARDADOS NO DISCORD (IMAGENS E WARNS) ====================
# Cada /bloquear_imagem vira UMA mensagem (só com os códigos/hashes, sem a imagem) no canal privado #imagens-bloqueadas.
# Cada /warn vira UMA mensagem no canal privado #warns-registro.
# Quando o bot liga, ele lê esses canais e recarrega tudo. Assim nada se perde se a hospedagem apagar arquivos.
async def carregar_registros(guild):
    carregadas = {}
    canal = await obter_canal_privado(guild, NOME_CANAL_REGISTRO, TOPICO_REGISTRO)
    if canal:
        try:
            async for msg in canal.history(limit=None, oldest_first=True):
                if msg.author.id != bot.user.id:
                    continue
                dados = ler_registro(msg.content)
                if dados:
                    dados.update(msg_id=msg.id, canal_id=canal.id)
                    carregadas[msg.id] = dados
        except Exception as e:
            print(f"[Aviso] Não consegui ler o canal #{NOME_CANAL_REGISTRO}: {e}")
    bot.imagens_registradas = carregadas
    reconstruir_hashes(carregadas.values())
    print(f"[Imagens] {len(carregadas)} imagem(ns) bloqueada(s) por comando carregada(s).")

    warns = defaultdict(list)
    canal = await obter_canal_privado(guild, NOME_CANAL_WARNS, TOPICO_WARNS)
    if canal:
        try:
            async for msg in canal.history(limit=None, oldest_first=True):
                if msg.author.id != bot.user.id:
                    continue
                dados = ler_warn(msg.content)
                if dados:
                    dados.update(msg_id=msg.id, canal_id=canal.id)
                    warns[dados["alvo"]].append(dados)
        except Exception as e:
            print(f"[Aviso] Não consegui ler o canal #{NOME_CANAL_WARNS}: {e}")
    bot.warns = warns
    print(f"[Warns] {sum(len(v) for v in warns.values())} warn(s) carregado(s).")

def texto_acao_imagem():
    return {
        "kick": "será **expulso(a)** automaticamente",
        "ban": "será **banido(a)** automaticamente",
        "apagar": "terá a mensagem **apagada** (sem punição)",
    }.get(IMAGEM_ACAO, "será punido(a)")

async def registrar_imagem(guild, user, dados, nome=None):
    """Bloqueia uma imagem (usado pelo /bloquear_imagem). Retorna (ok, texto_para_o_admin)."""
    loop = asyncio.get_running_loop()
    try:
        frames, achado, _ = await loop.run_in_executor(None, avaliar_imagem, dados)
    except Exception as e:
        return False, f"❌ Não consegui ler essa imagem: `{e}`"
    if not frames:
        return False, "❌ Não consegui calcular os hashes dessa imagem."

    if achado:
        origem, detalhe = achado
        quem = "uma imagem da lista fixa do código" if origem == "lista" else f"`{origem}`"
        return False, f"ℹ️ Essa imagem **já é bloqueada**: é idêntica a {quem} (`{detalhe}`). Não precisei adicionar."

    # Em GIF animado, usa o primeiro frame que tenha detalhe (o 1º às vezes é só uma tela preta)
    escolhido = next((f for f in frames if not eh_hash_liso(f)), None)
    if escolhido is None:
        return False, "❌ Essa imagem tem quase nenhum detalhe (uma cor só, degradê...). Bloquear ela puniria muita gente inocente."

    async with bot.trava_registro:
        if len(bot.imagens_registradas) >= LIMITE_IMAGENS_REGISTRADAS:
            return False, f"❌ Limite de {LIMITE_IMAGENS_REGISTRADAS} imagens atingido. Remova alguma com `/desbloquear_imagem`."
        usados = {e["nome"].lower() for e in bot.imagens_registradas.values()}
        nome = limpar_nome(nome) or proximo_nome_livre(usados)
        if nome.lower() in usados:
            return False, f"❌ Já existe uma imagem chamada `{nome}`. Escolha outro nome."

        canal_ja_existia = await obter_canal_privado(guild, NOME_CANAL_REGISTRO, TOPICO_REGISTRO) is not None
        try:
            canal = await obter_canal_privado(guild, NOME_CANAL_REGISTRO, TOPICO_REGISTRO, criar=True)
            hashes_hex = {alg: str(escolhido[alg]) for alg in ALGORITMOS}
            quando = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            msg = await canal.send(
                montar_registro(nome, hashes_hex, user.id, quando),
                allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as e:  # inclui Forbidden (sem permissão)
            return False, (
                f"❌ Não consegui guardar a lista no canal `#{NOME_CANAL_REGISTRO}` ({type(e).__name__}). "
                f"Crie um canal com esse nome (só para staff), dê ao bot permissão de ver e enviar mensagens nele e tente de novo."
            )
        bot.imagens_registradas[msg.id] = {
            "nome": nome, "hashes": hashes_hex, "por": user.id, "quando": quando,
            "msg_id": msg.id, "canal_id": canal.id
        }
        reconstruir_hashes(bot.imagens_registradas.values())

    texto = (
        f"✅ **Imagem bloqueada** como `{nome}`.\n"
        f"Quem enviar **essa mesma imagem** (idêntica, não parecida) no {NOME_SERVIDOR} {texto_acao_imagem()}."
    )
    if not canal_ja_existia:
        texto += (
            f"\n\n📁 Criei o canal privado `#{NOME_CANAL_REGISTRO}` para guardar a lista "
            f"(só os códigos, não a imagem). **Não apague as mensagens dele.**"
        )
    return True, texto

async def remover_imagem(nome):
    """Desbloqueia pelo nome (usado pelo /desbloquear_imagem). Retorna (ok, texto_para_o_admin)."""
    async with bot.trava_registro:
        chave = (nome or "").strip().lower()
        alvos = [e for e in bot.imagens_registradas.values() if e["nome"].lower() == chave]
        if not alvos:
            return False, f"❌ Não achei nenhuma imagem bloqueada chamada `{nome}`. Veja os nomes com `/listar_imagens`."
        falhas = 0
        for e in alvos:
            bot.imagens_registradas.pop(e["msg_id"], None)
            try:
                canal = bot.get_channel(e["canal_id"]) or await bot.fetch_channel(e["canal_id"])
                await canal.get_partial_message(e["msg_id"]).delete()
            except discord.NotFound:
                pass  # a mensagem já tinha sido apagada
            except Exception as ex:
                falhas += 1
                print(f"[Aviso] Não consegui apagar a mensagem de registro de '{e['nome']}': {ex}")
        reconstruir_hashes(bot.imagens_registradas.values())

    texto = f"✅ A imagem `{alvos[0]['nome']}` foi desbloqueada."
    if falhas:
        texto += (
            f"\n⚠️ Não consegui apagar a mensagem dela no canal `#{NOME_CANAL_REGISTRO}`. "
            f"Apague manualmente, senão ela volta a ser bloqueada quando o bot reiniciar."
        )
    return True, texto

def esquecer_registros_apagados(ids):
    """Se alguém apagar a mensagem de registro direto no canal, a imagem/warn deixa de valer."""
    ids = set(ids)
    mudou = False
    for mid in ids:
        if bot.imagens_registradas.pop(mid, None) is not None:
            mudou = True
    if mudou:
        reconstruir_hashes(bot.imagens_registradas.values())
    for uid in list(bot.warns):
        bot.warns[uid] = [w for w in bot.warns[uid] if w.get("msg_id") not in ids]
        if not bot.warns[uid]:
            del bot.warns[uid]
    if bot.banco.msg_id in ids:   # apagaram a mensagem do banco de dados: ele recria no próximo salvamento
        bot.banco.msg_id = None
        bot.banco.sujo = True

def warns_ativos(uid):
    limite = time.time() - WARN_VALIDADE_DIAS * 86400
    return [w for w in bot.warns.get(uid, []) if w["quando"] >= limite]

async def registrar_warn(guild, alvo_id, staff_id, motivo):
    quando = int(time.time())
    motivo = (motivo or "").strip()[:300] or "Sem motivo especificado"
    msg_id = canal_id = None
    try:
        canal = await obter_canal_privado(guild, NOME_CANAL_WARNS, TOPICO_WARNS, criar=True)
        msg = await canal.send(montar_warn(alvo_id, staff_id, quando, motivo), allowed_mentions=discord.AllowedMentions.none())
        msg_id, canal_id = msg.id, canal.id
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui guardar o warn no canal #{NOME_CANAL_WARNS} (ele vale só até o bot reiniciar): {e}")
    warn = {"alvo": alvo_id, "staff": staff_id, "quando": quando, "motivo": motivo, "msg_id": msg_id, "canal_id": canal_id}
    bot.warns[alvo_id].append(warn)
    return warn

async def limpar_warns(uid):
    removidos = bot.warns.pop(uid, [])
    for w in removidos:
        if not w.get("msg_id"):
            continue
        try:
            canal = bot.get_channel(w["canal_id"]) or await bot.fetch_channel(w["canal_id"])
            await canal.get_partial_message(w["msg_id"]).delete()
        except Exception:
            pass
    return len(removidos)

async def escalar_warn(guild, membro, total):
    """Aplica a punição automática quando a pessoa chega em certa quantidade de warns. Retorna um texto (ou '')."""
    acao = WARN_ESCADA.get(total)
    if not acao:
        return ""
    tipo, minutos = acao
    motivo = f"Escalonamento automático: {total} warns"
    if tipo == "mute":
        ok = await aplicar_mute(guild, membro, bot.user, minutos, motivo, "Mute (Automático - Warns)")
        return f"\n🔇 Silenciado por {formatar_duracao(minutos)} automaticamente." if ok else "\n⚠️ Não consegui aplicar o mute automático."
    if tipo == "kick":
        ok = await executar_expulsao(guild, membro, bot.user, motivo, "Expulsão (Automático - Warns)")
        return "\n👢 Expulso automaticamente." if ok else "\n⚠️ Não consegui expulsar automaticamente."
    if tipo == "ban":
        ok = await executar_banimento(guild, membro, bot.user, motivo, "Ban (Automático - Warns)")
        return "\n🔨 Banido automaticamente." if ok else "\n⚠️ Não consegui banir automaticamente."
    return ""

# ==================== ANTI-NUKE / ANTI-BOT / ANTI-ESCALADA ====================
async def contar_nuke(guild, autor_id, chave, rotulo, limite, janela, alvo_id=None):
    """Conta ações perigosas de uma pessoa. Se passar do limite, reage (ban/kick/remover cargos)."""
    agora = time.monotonic()
    fila = bot.nuke_hist[(autor_id, chave)]
    fila.append((agora, alvo_id))
    while fila and agora - fila[0][0] > janela:
        fila.popleft()
    if len(fila) < limite:
        return

    ultimo = bot.nuke_punidos.get(autor_id)
    if ultimo is not None and agora - ultimo < 120:
        return   # já reagi a essa pessoa agora há pouco
    bot.nuke_punidos[autor_id] = agora
    alvos = [a for _, a in fila if a]
    fila.clear()
    await reagir_nuke(guild, autor_id, f"{limite}+ {rotulo} em {janela}s", alvos if chave == "ban" else [])

async def contar_acao_staff(guild, staff, chave, alvo_id=None):
    """Ban/kick feitos PELOS COMANDOS do bot também contam (senão uma conta invadida burlava o anti-nuke usando o /ban)."""
    if eh_confiavel(guild, staff.id):
        return
    regra = NUKE_REGRAS.get(chave)
    if regra:
        await contar_nuke(guild, staff.id, chave, regra[0], regra[1], regra[2], alvo_id)

async def reagir_nuke(guild, autor_id, motivo, desbanir=()):
    membro = guild.get_member(autor_id)
    if membro is None:
        try:
            membro = await guild.fetch_member(autor_id)
        except discord.HTTPException:
            membro = None

    resultado = "o autor não está mais no servidor"
    if membro is not None:
        razao = f"Anti-Nuke: {motivo}"
        punido = False
        if NUKE_ACAO == "ban":
            punido = await executar_banimento(guild, membro, bot.user, razao, "Ban (Anti-Nuke)")
            resultado = "banido" if punido else "⚠️ NÃO consegui banir"
        elif NUKE_ACAO == "kick":
            punido = await executar_expulsao(guild, membro, bot.user, razao, "Expulsão (Anti-Nuke)", dm=False)
            resultado = "expulso" if punido else "⚠️ NÃO consegui expulsar"
        if NUKE_ACAO == "remover_cargos" or not punido:
            removidos = await remover_cargos(membro, razao)
            nomes = ", ".join(r.name for r in removidos) or "nenhum"
            resultado = f"cargos removidos: {nomes}" if NUKE_ACAO == "remover_cargos" else f"{resultado} • cargos removidos: {nomes}"

    desfeitos = 0
    for uid in set(desbanir):
        try:
            await guild.unban(discord.Object(id=uid), reason="Anti-Nuke: banimento em massa revertido")
            desfeitos += 1
        except discord.HTTPException:
            pass

    texto = (
        f"👤 **Autor:** <@{autor_id}> (`{autor_id}`)\n"
        f"📄 **O que ele fez:** {motivo}\n"
        f"🛡️ **Resposta:** {resultado}\n"
        + (f"♻️ **Banimentos desfeitos:** {desfeitos}\n" if desbanir else "")
        + "\nConfira o Registro de Auditoria e reveja canais/cargos/webhooks."
    )
    await enviar_alerta(guild, f"🚨 {NOME_SERVIDOR} - ANTI-NUKE ACIONADO", texto)
    await alertar_dono(guild, f"🚨 {NOME_SERVIDOR}: Anti-Nuke acionado", texto)

async def barrar_bot(entry):
    guild = entry.guild
    bot_id = entry.target_id
    if not bot_id or bot_id in BOTS_PERMITIDOS:
        return
    try:
        await guild.kick(discord.Object(id=bot_id), reason="Anti-Bot: adicionado por quem não é de confiança")
        resultado = "expulso"
    except discord.HTTPException:
        resultado = "⚠️ NÃO consegui expulsar (confira as permissões do bot)"
    texto = (
        f"🤖 **Bot:** <@{bot_id}> (`{bot_id}`)\n"
        f"👤 **Adicionado por:** <@{entry.user_id}>\n"
        f"🛡️ **Resposta:** {resultado}\n\n"
        f"Para liberar um bot, coloque o ID dele em BOTS_PERMITIDOS (ou peça ao dono/whitelist para adicionar)."
    )
    await enviar_alerta(guild, f"🤖 {NOME_SERVIDOR} - Bot Barrado", texto)

async def reverter_permissoes_cargo(entry):
    """Alguém deu administrador/banir/etc. para um cargo? Desfaz."""
    antes = getattr(entry.before, "permissions", None)
    depois = getattr(entry.after, "permissions", None)
    if antes is None or depois is None:
        return False
    ganhou = [p for p in PERMS_PERIGOSAS if getattr(depois, p, False) and not getattr(antes, p, False)]
    if not ganhou:
        return False
    guild = entry.guild
    cargo = guild.get_role(entry.target_id)
    if cargo is None:
        return False
    try:
        await cargo.edit(permissions=antes, reason="Anti-Escalada: permissão perigosa dada por quem não é de confiança")
        resultado = "desfeito"
    except discord.HTTPException:
        resultado = "⚠️ NÃO consegui desfazer"
    await enviar_alerta(
        guild, f"🛑 {NOME_SERVIDOR} - Permissão Perigosa Bloqueada",
        f"🏷️ **Cargo:** {cargo.mention}\n👤 **Por:** <@{entry.user_id}>\n"
        f"🔑 **Permissões:** {', '.join(ganhou)}\n🛡️ **Resposta:** {resultado}"
    )
    return True

async def reverter_cargo_dado(entry):
    """Alguém deu um cargo com permissão perigosa a um membro? Tira de volta."""
    adicionados = [r for r in (getattr(entry.after, "roles", None) or []) if isinstance(r, discord.Role)]
    perigosos = [r for r in adicionados if any(getattr(r.permissions, p, False) for p in PERMS_PERIGOSAS)]
    if not perigosos:
        return False
    guild = entry.guild
    alvo = guild.get_member(entry.target_id)
    if alvo is None:
        return False
    try:
        await alvo.remove_roles(*perigosos, reason="Anti-Escalada: cargo perigoso dado por quem não é de confiança")
        resultado = "removido"
    except discord.HTTPException:
        resultado = "⚠️ NÃO consegui remover"
    await enviar_alerta(
        guild, f"🛑 {NOME_SERVIDOR} - Cargo Perigoso Bloqueado",
        f"🎯 **Membro:** {alvo.mention}\n🏷️ **Cargo(s):** {', '.join(r.mention for r in perigosos)}\n"
        f"👤 **Dado por:** <@{entry.user_id}>\n🛡️ **Resposta:** {resultado}\n\n"
        f"Se isso era legítimo, o dono ou alguém da whitelist precisa dar o cargo."
    )
    return True

async def antinuke(entry):
    guild = entry.guild
    autor_id = entry.user_id
    if not autor_id or eh_confiavel(guild, autor_id):
        return
    acao = entry.action
    chave = acao.name

    if acao is discord.AuditLogAction.bot_add:
        if BLOQUEAR_BOTS_NAO_AUTORIZADOS:
            await barrar_bot(entry)
        return

    if PROTEGER_CARGOS_PERIGOSOS and acao in (discord.AuditLogAction.role_update, discord.AuditLogAction.member_role_update):
        if acao is discord.AuditLogAction.role_update:
            revertido = await reverter_permissoes_cargo(entry)
        else:
            revertido = await reverter_cargo_dado(entry)
        if revertido:
            regra = NUKE_REGRAS["perm_perigosa"]
            await contar_nuke(guild, autor_id, "perm_perigosa", regra[0], regra[1], regra[2])
        return

    regra = NUKE_REGRAS.get(chave)
    if regra:
        await contar_nuke(guild, autor_id, chave, regra[0], regra[1], regra[2], entry.target_id)

# Punições feitas à mão pela staff (botão direito/painel do Discord) também entram no log de punições
async def log_manual(entry):
    if entry.user_id is None or entry.user_id == bot.user.id:
        return   # as punições do próprio bot já são logadas na hora
    acao = entry.action
    motivo = entry.reason or "Nenhum motivo inserido."
    tipo = "ban"

    if acao is discord.AuditLogAction.ban:
        titulo = "Banimento (Painel/Botão Direito)"
    elif acao is discord.AuditLogAction.unban:
        titulo = "Desbanimento (Painel/Botão Direito)"
    elif acao is discord.AuditLogAction.kick:
        titulo = "Expulsão (Painel/Botão Direito)"
    elif acao is discord.AuditLogAction.member_update:
        depois = getattr(entry.after, "timed_out_until", None)
        antes = getattr(entry.before, "timed_out_until", None)
        agora = discord.utils.utcnow()
        if depois is not None and depois > agora:
            minutos = max(1, round((depois - agora).total_seconds() / 60))
            titulo = f"Mute ({formatar_duracao(minutos)} - Discord)"
            tipo = "mute"
            if not entry.reason:
                motivo = "Aplicado via painel/botão direito."
        elif antes is not None and antes > agora and depois is None:
            titulo = "Desmutado (Discord)"
            tipo = "mute"
            if not entry.reason:
                motivo = "Removido via painel/botão direito."
        else:
            return
    else:
        return

    staff = entry.user or await buscar_usuario(entry.user_id)
    alvo = entry.target if isinstance(entry.target, (discord.Member, discord.User)) else await buscar_usuario(entry.target_id)
    if alvo is None or staff is None:
        return
    await log_punicao(entry.guild, alvo, staff, titulo, motivo, tipo=tipo)

# ==================== ANTI-RAID ====================
async def barrar_entrada(membro, motivo):
    bot.silenciar_saida.add(membro.id)
    try:
        if RAID_ACAO == "ban":
            await membro.guild.ban(membro, reason=motivo)
        else:
            await membro.kick(reason=motivo)
        return True
    except discord.HTTPException:
        bot.silenciar_saida.discard(membro.id)
        return False

async def ativar_raid(guild, motivo, por=None):
    """Liga o modo raid: barra quem entrou na rajada e barra tudo que entrar durante a duração."""
    fim = time.monotonic() + RAID_DURACAO_MIN * 60
    if raid_ativo():
        bot.raid_ate = fim   # já estava ligado: só renova o tempo
        return False
    bot.raid_ate = fim
    bot.raid_expulsos = 0

    ids = [uid for _, uid in bot.entradas_recentes]
    bot.entradas_recentes.clear()
    alvos = [guild.get_member(uid) for uid in ids]
    alvos = [m for m in alvos if m is not None and not eh_staff(m)]
    resultados = await asyncio.gather(*(barrar_entrada(m, "Anti-Raid: rajada de entradas") for m in alvos))
    barrados = sum(1 for r in resultados if r)
    bot.raid_expulsos += barrados

    texto = (
        f"📄 **Motivo:** {motivo}\n"
        f"👮 **Ativado por:** {por.mention if por else 'detecção automática'}\n"
        f"🧹 **Contas barradas agora:** {barrados}\n"
        f"⏱️ **Duração:** {RAID_DURACAO_MIN} min\n"
        f"⚙️ **Ação:** {'banimento' if RAID_ACAO == 'ban' else 'expulsão'} de quem tentar entrar\n\n"
        f"Para encerrar antes, use `/raid desligar`."
    )
    await enviar_alerta(guild, f"🚨 {NOME_SERVIDOR} - MODO ANTI-RAID ATIVADO", texto)
    await alertar_dono(guild, f"🚨 {NOME_SERVIDOR}: modo anti-raid ativado", texto)
    return True

async def desativar_raid(guild, por=None):
    if not bot.raid_ate:
        return False
    bot.raid_ate = 0.0
    total = bot.raid_expulsos
    await enviar_alerta(
        guild, f"✅ {NOME_SERVIDOR} - Modo Anti-Raid Encerrado",
        f"👮 **Encerrado por:** {por.mention if por else 'tempo esgotado'}\n"
        f"🧹 **Contas barradas durante o modo:** {total}"
    )
    return True

async def tratar_entrada(membro):
    """Confere quem entrou. Devolve True se o membro foi barrado (raid ou conta nova demais), para pular as boas-vindas."""
    guild = membro.guild
    if membro.bot or eh_confiavel(guild, membro.id):
        return False
    agora = time.monotonic()

    # 1) Modo raid ligado: ninguém novo entra
    if raid_ativo():
        if await barrar_entrada(membro, "Anti-Raid: servidor em modo de proteção"):
            bot.raid_expulsos += 1
            return True
        return False

    # 2) Rajada de entradas?
    bot.entradas_recentes.append((agora, membro.id))
    while bot.entradas_recentes and agora - bot.entradas_recentes[0][0] > RAID_JANELA_SEG:
        bot.entradas_recentes.popleft()
    if len(bot.entradas_recentes) >= RAID_ENTRADAS:
        await ativar_raid(guild, f"{len(bot.entradas_recentes)} entradas em {RAID_JANELA_SEG}s")
        return True

    # 3) Conta nova demais
    if IDADE_MINIMA_CONTA_DIAS:
        idade = (discord.utils.utcnow() - membro.created_at).days
        if idade < IDADE_MINIMA_CONTA_DIAS:
            try:
                await membro.send(
                    f"**{NOME_SERVIDOR}** — sua conta é muito nova para entrar agora. "
                    f"Volte quando ela tiver pelo menos {IDADE_MINIMA_CONTA_DIAS} dia(s)."
                )
            except Exception:
                pass
            bot.silenciar_saida.add(membro.id)
            try:
                await membro.kick(reason=f"Anti-Raid: conta com menos de {IDADE_MINIMA_CONTA_DIAS} dia(s)")
                return True
            except discord.HTTPException:
                bot.silenciar_saida.discard(membro.id)
    return False

# ==================== LOCKDOWN ====================
LOCK_PERMS = ("send_messages", "send_messages_in_threads", "create_public_threads")

async def travar_canais(guild, canais, motivo):
    cargos = [guild.default_role] + [r for r in (guild.get_role(i) for i in CARGOS_TRAVAR) if r]
    travados = set()
    for canal in canais:
        for cargo in cargos:
            try:
                ow = canal.overwrites_for(cargo)
                chave = (canal.id, cargo.id)
                if chave not in bot.lock_estado:
                    bot.lock_estado[chave] = {p: getattr(ow, p) for p in LOCK_PERMS}
                for p in LOCK_PERMS:
                    setattr(ow, p, False)
                await canal.set_permissions(cargo, overwrite=ow, reason=motivo[:480])
                travados.add(canal.id)
            except discord.HTTPException as e:
                print(f"[Aviso] Não consegui travar #{getattr(canal, 'name', canal.id)}: {e}")
    return len(travados)

async def destravar_canais(guild, canais=None):
    so_estes = {c.id for c in canais} if canais else None
    destravados = set()
    for (canal_id, cargo_id), antes in list(bot.lock_estado.items()):
        if so_estes is not None and canal_id not in so_estes:
            continue
        canal = guild.get_channel(canal_id)
        cargo = guild.get_role(cargo_id)
        if canal is None or cargo is None:
            bot.lock_estado.pop((canal_id, cargo_id), None)
            continue
        try:
            ow = canal.overwrites_for(cargo)
            for p, valor in antes.items():
                setattr(ow, p, valor)
            if ow.is_empty():
                await canal.set_permissions(cargo, overwrite=None, reason="Fim do lockdown")
            else:
                await canal.set_permissions(cargo, overwrite=ow, reason="Fim do lockdown")
            bot.lock_estado.pop((canal_id, cargo_id), None)
            destravados.add(canal_id)
        except discord.HTTPException as e:
            print(f"[Aviso] Não consegui destravar #{getattr(canal, 'name', canal_id)}: {e}")
    return len(destravados)

# ==================== AUTOMOD / ANTI-SPAM ====================
def somar_pontos(uid, pontos):
    agora = time.monotonic()
    fila = bot.pontos[uid]
    fila.append((agora, pontos))
    while fila and agora - fila[0][0] > JANELA_REINCIDENCIA_MIN * 60:
        fila.popleft()
    return sum(p for _, p in fila)

async def tratar_infracao(message, motivo, pontos, refs=None, categoria="geral", mute_minutos=0):
    """
    Apaga o que for preciso, soma pontos e pune: aviso -> mute 10min -> 1h -> 1 dia (escada de pontos).
    Spam passa mute_minutos=MUTE_SPAM_MIN e leva o mute direto (4 horas), sem esperar acumular pontos.
    categoria ("geral", "spam", "links") diz em quais canais #automod-* o caso aparece.
    """
    guild, membro = message.guild, message.author
    refs = refs or [(message.channel.id, message.id)]

    if membro.id in bot.punindo:   # outra mensagem dele já está sendo tratada: só apaga essa
        await apagar_mensagens(guild, refs)
        return
    bot.punindo.add(membro.id)
    try:
        await apagar_mensagens(guild, refs)
        total = somar_pontos(membro.id, pontos)
        minutos = max(mute_minutos, next((m for limite, m in ESCADA_PONTOS if total >= limite), 0))
        if minutos:
            ok = await aplicar_mute(guild, membro, bot.user, minutos, f"Automod: {motivo}", "Mute (Automático)")
            if ok:
                acao = f"Mute de {formatar_duracao(minutos)}"
                await avisar_canal(message.channel, f"🔇 {membro.mention} foi silenciado por {formatar_duracao(minutos)}: {motivo}.")
            else:
                acao = "Mensagem apagada (⚠️ não consegui silenciar)"
        else:
            acao = f"Aviso ({total} ponto(s) de infração)"
            await avisar_canal(message.channel, f"⚠️ {membro.mention}, {motivo}. ({total} ponto(s) de infração)")
        await log_automod(guild, membro, motivo, message.channel, message.content, acao, categoria)
    finally:
        bot.punindo.discard(membro.id)

def conteudo_para_duplicata(message):
    texto = re.sub(r'\s+', ' ', (message.content or '').lower()).strip()
    if len(texto) >= 4:
        return texto
    if not texto and message.attachments:
        return "anexo:" + ",".join(str(a.size) for a in message.attachments)
    return ""

def checar_spam(message):
    """Registra a mensagem no histórico da pessoa e diz se virou spam. Retorna (motivo, pontos, mensagens_para_apagar) ou None."""
    uid = message.author.id
    agora = time.monotonic()
    chave = conteudo_para_duplicata(message)
    fila = bot.hist_msgs[uid]
    fila.append((agora, message.channel.id, message.id, chave))
    while fila and agora - fila[0][0] > SPAM_JANELA_MAX:
        fila.popleft()

    def refs(itens):
        return [(c, m) for _, c, m, _ in itens]

    if chave:
        iguais = [x for x in fila if x[3] == chave and agora - x[0] <= SPAM_DUP_JANELA_SEG]
        if len({x[1] for x in iguais}) >= SPAM_CANAIS:
            fila.clear()
            return "mesma mensagem enviada em vários canais", PONTOS["multicanal"], refs(iguais)
        if len(iguais) >= SPAM_DUPLICADAS:
            fila.clear()
            return "mensagens repetidas", PONTOS["repetida"], refs(iguais)

    recentes = [x for x in fila if agora - x[0] <= SPAM_JANELA_SEG]
    if len(recentes) >= SPAM_MENSAGENS:
        fila.clear()
        return "flood de mensagens", PONTOS["flood"], refs(recentes)
    return None

async def filtro_golpes(message):
    """Mensagem de golpe/fake ou link falso = ban (ou kick, se GOLPE_ACAO = "kick"). Staff não é punida: só tem a mensagem apagada."""
    texto = message.content or ""
    termo = achar_na_lista(texto, TERMOS_BAN_C)
    link = None if termo else achar_link_golpe(texto)
    if not termo and not link:
        return False
    marcar_ignorar(message.id)
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    if termo:
        motivo = f"Tentativa de golpe (Mensagem Fake): `{termo}`"
    else:
        motivo = f"Tentativa de golpe (link falso): `{link}`"
    if STAFF_ISENTA_DE_TUDO and eh_staff(message.author):
        # Staff NÃO é punida. Mas se a conta foi invadida, o golpe não pode ficar no chat: só apaga e avisa no log.
        await log_automod(message.guild, message.author, motivo, message.channel, texto,
                          "Só apaguei a mensagem (staff não é punida) — confira se a conta foi invadida", "links")
        return True
    if GOLPE_ACAO == "kick":
        await executar_expulsao(message.guild, message.author, bot.user, motivo, "Expulsão (Automático)", prova_texto=texto)
        acao = "Expulso"
    else:
        await executar_banimento(
            message.guild, message.author, bot.user, motivo, "Ban (Automático)",
            apagar_segundos=3600, prova_texto=texto
        )
        acao = "Banido"
    await log_automod(message.guild, message.author, motivo, message.channel, texto, acao, "links")
    return True

async def automod(message, editada=False):
    """Convites, menção em massa, palavrões, links de novatos, spam e formatação abusiva. True = mensagem tratada."""
    membro = message.author
    if STAFF_ISENTA_DO_AUTOMOD and eh_staff(membro):
        return False
    texto = message.content or ""

    # 1) Convites de outros servidores
    if texto and achar_convite(texto):
        await tratar_infracao(message, "divulgação de convite de servidor", PONTOS["convite"], categoria="links")
        return True

    # 2) Menção em massa
    mencoes = len({u.id for u in message.mentions}) + len(message.role_mentions)
    if mencoes >= MAX_MENCOES:
        await tratar_infracao(message, f"menção em massa ({mencoes} menções)", PONTOS["mencoes"], categoria="spam")
        return True

    # 3) Palavrões / xingamentos (só palavra INTEIRA)
    if texto and achar_na_lista(texto, PALAVROES_C):
        await tratar_infracao(message, "linguagem imprópria", PONTOS["palavrao"])
        return True

    # 4) Links para quem acabou de entrar
    if texto and NOVATO_SEM_LINKS_MIN and eh_novato(membro):
        if any(not dominio_permitido(u) for u in URL_REGEX.findall(texto)):
            await tratar_infracao(message, "links bloqueados para quem acabou de entrar", PONTOS["link_novato"], categoria="links")
            return True

    # 5) Spam (só em mensagem nova, não em edição) -> mute direto de MUTE_SPAM_MIN (4 horas)
    if not editada:
        achado = checar_spam(message)
        if achado:
            motivo, pontos, refs = achado
            await tratar_infracao(message, motivo, pontos, refs, categoria="spam", mute_minutos=MUTE_SPAM_MIN)
            return True

    # 6) Formatação abusiva
    motivo = achar_formatacao_abusiva(texto)
    if motivo:
        await tratar_infracao(message, motivo, PONTOS["formatacao"])
        return True
    return False

# ==================== VERIFICAÇÃO DE IMAGENS NO CHAT (SÓ IMAGEM IDÊNTICA) ====================
async def baixar_imagem(url, anexo=None):
    """Baixa a imagem SEM travar o bot (o requests.get antigo congelava o bot inteiro durante o download)."""
    if anexo is not None:
        if anexo.size and anexo.size > LIMITE_DOWNLOAD:
            return None
        try:
            return await anexo.read()
        except Exception:
            pass  # se falhar, tenta pelo link abaixo
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with bot.sessao_http.get(url, headers=HEADERS_NAVEGADOR, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            if resp.content_length and resp.content_length > LIMITE_DOWNLOAD:
                return None
            dados = bytearray()
            async for pedaco in resp.content.iter_chunked(65536):
                dados.extend(pedaco)
                if len(dados) > LIMITE_DOWNLOAD:
                    return None
            return bytes(dados)
    except Exception:
        return None

async def checar_imagens_proibidas(message, so_embeds=False):
    """
    Confere as imagens da mensagem. Se alguma for IDÊNTICA a uma imagem bloqueada, apaga a mensagem e pune
    conforme IMAGEM_ACAO ("kick" por padrão). Imagem apenas parecida NÃO conta. Retorna True se tratou.
    """
    if not HASHES_REGISTRADOS and not HASHES_FIXOS:
        return False   # nenhuma imagem bloqueada ainda: nem precisa baixar as imagens do chat
    if STAFF_ISENTA_DE_TUDO and eh_staff(message.author):
        return False   # staff não é punida (nem tem imagem conferida)
    fontes = coletar_fontes_imagem(message, so_embeds)
    if not fontes:
        return False

    baixados = await asyncio.gather(*(baixar_imagem(url, anexo) for url, _, anexo in fontes))
    loop = asyncio.get_running_loop()

    for (url, nome, _), dados in zip(fontes, baixados):
        if not dados:
            continue
        try:
            # Cálculo pesado numa thread separada: o bot continua respondendo normalmente
            _, achado, _ = await loop.run_in_executor(None, avaliar_imagem, dados)
        except Exception as e:
            print(f"[Aviso Automod] Erro ao analisar a imagem {url}: {e}")
            continue
        if not achado:
            continue

        origem, detalhe = achado
        marcar_ignorar(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        guild, autor = message.guild, message.author
        motivo = "Envio de imagem proibida."
        prova = (dados, nome_seguro(nome))   # a imagem vai anexada no log (o link morre ao apagar a mensagem)
        detalhe_log = f"imagem idêntica • {origem} ({detalhe})"
        if IMAGEM_ACAO == "ban":
            await executar_banimento(guild, autor, bot.user, motivo, f"Ban (Automático) • {detalhe_log}",
                                     prova_url=url, prova_arquivo=prova, apagar_segundos=3600)
            acao = "Banido"
        elif IMAGEM_ACAO == "kick":
            await executar_expulsao(guild, autor, bot.user, motivo, f"Expulsão (Automático) • {detalhe_log}",
                                    prova_url=url, prova_arquivo=prova)
            acao = "Expulso"
        else:
            await log_punicao(guild, autor, bot.user, f"Imagem apagada (sem punição) • {detalhe_log}", motivo,
                              prova_url=url, prova_arquivo=prova)
            acao = "Mensagem apagada (sem punição)"
        await log_automod(guild, autor, f"imagem proibida ({origem})", message.channel, None, acao, "links")
        return True
    return False

# ==================== QUEM CONVIDOU (rastreio de convites) ====================
async def atualizar_cache_convites(guild):
    try:
        convites = await guild.invites()
    except discord.HTTPException:
        return   # sem a permissão "Gerenciar Servidor": o bot só não mostra quem convidou
    bot.convites = {c.code: (c.uses or 0) for c in convites}

async def descobrir_convite(guild):
    """Descobre qual convite foi usado comparando os usos de antes e de depois. Devolve um dict ou None."""
    antigo = dict(bot.convites)
    try:
        atuais = await guild.invites()
    except discord.HTTPException:
        return None
    bot.convites = {c.code: (c.uses or 0) for c in atuais}
    for c in atuais:
        if (c.uses or 0) > antigo.get(c.code, 0):
            return {"codigo": c.code, "autor": c.inviter, "usos": c.uses}
    sumidos = [codigo for codigo in antigo if codigo not in bot.convites]
    if len(sumidos) == 1:   # convite de uso único que se apagou sozinho
        return {"codigo": sumidos[0], "autor": None, "usos": None}
    return None

# ==================== BOAS-VINDAS (estilo Loritta) ====================
def mencao_canal(guild, id_config, nomes):
    """Menção do canal (pelo ID da config ou pelo nome). Devolve None se não achar."""
    canal = achar_canal_texto(guild, id_config, nomes, publico=True)
    return canal.mention if canal else None

def aplicar_modelo(modelo, membro, extra=None, pular_se_faltar_canal=False):
    """
    Troca {mention}, {nome}, {servidor}, {membros}, {geral}, {regras}, {videos}, {tickets}, {booster}... pelos valores de verdade.
    Se o canal de um {placeholder} não for encontrado: com pular_se_faltar_canal=True devolve None (a linha some);
    senão escreve o nome simples (#regras).
    """
    guild = membro.guild
    canais = {
        "{geral}": (CANAL_GERAL, ("geral",), "#geral"),
        "{regras}": (CANAL_REGRAS, ("regras",), "#regras"),
        "{videos}": (CANAL_VIDEOS, ("videos", "vídeos"), "#videos"),
        "{tickets}": (CANAL_TICKETS, ("ticket", "atendimento", "suporte"), "#tickets"),
        "{booster}": (CANAL_BOOSTER, ("booster", "boost"), "#booster"),
    }
    for chave, (id_config, nomes, padrao) in canais.items():
        if chave in modelo:
            mencao = mencao_canal(guild, id_config, nomes)
            if mencao is None and pular_se_faltar_canal:
                return None
            modelo = modelo.replace(chave, mencao or padrao)
    valores = {
        "{mention}": membro.mention,
        "{nome}": discord.utils.escape_markdown(membro.display_name),
        "{usuario}": discord.utils.escape_markdown(membro.name),
        "{servidor}": guild.name,
        "{membros}": str(guild.member_count or len(guild.members)),
        "{id}": str(membro.id),
        "{conta_criada}": discord.utils.format_dt(membro.created_at, "R"),
        "{convidado_por}": "alguém",
    }
    if extra:
        valores.update(extra)
    for chave, valor in valores.items():
        modelo = modelo.replace(chave, valor)
    return modelo

def montar_texto_boas_vindas(membro, extra=None):
    """Junta as linhas de BOAS_VINDAS_LINHAS (uma linha em branco entre elas). Linha cujo canal não existe é pulada."""
    linhas = []
    for linha in BOAS_VINDAS_LINHAS:
        if linha and linha.strip():
            pronta = aplicar_modelo(linha, membro, extra, pular_se_faltar_canal=True)
            if pronta:
                linhas.append(pronta)
    return "\n\n".join(linhas)

def _fonte(tamanho):
    for nome in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except Exception:
            continue
    try:
        return ImageFont.load_default(tamanho)   # Pillow 10.1+
    except Exception:
        return ImageFont.load_default()

def _caber(draw, texto, fonte, largura_max):
    """Corta o texto (com …) até caber na largura."""
    if draw.textlength(texto, font=fonte) <= largura_max:
        return texto
    while len(texto) > 1 and draw.textlength(texto + "…", font=fonte) > largura_max:
        texto = texto[:-1]
    return texto + "…"

def desenhar_cartao(avatar_bytes, titulo, nome, linha_final):
    """Desenha o cartão de boas-vindas (PNG 900x300) com a foto do membro. Roda numa thread separada."""
    largura, altura, tam = 900, 300, 200
    r0, g0, b0 = (COR >> 16) & 255, (COR >> 8) & 255, COR & 255
    degrade = Image.new("RGB", (largura, 1))
    for x in range(largura):
        k = max(0.0, 1.0 - (x / largura) * 1.3)   # vermelho forte na esquerda, escurecendo para a direita
        degrade.putpixel((x, 0), (int(16 + (r0 - 16) * k), int(16 + (g0 - 16) * k), int(20 + (b0 - 20) * k)))
    fundo = degrade.resize((largura, altura))

    x0, y0 = 50, (altura - tam) // 2
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((tam, tam))
    mascara = Image.new("L", (tam, tam), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, tam - 1, tam - 1), fill=255)
    anel = Image.new("L", (tam + 16, tam + 16), 0)
    ImageDraw.Draw(anel).ellipse((0, 0, tam + 15, tam + 15), fill=255)
    fundo.paste((255, 255, 255), (x0 - 8, y0 - 8), anel)   # borda branca redonda
    fundo.paste(avatar, (x0, y0), mascara)

    draw = ImageDraw.Draw(fundo)
    tx = x0 + tam + 50
    maxw = largura - tx - 30
    grande, media, pequena = _fonte(52), _fonte(36), _fonte(24)
    draw.text((tx, 60), _caber(draw, titulo, grande, maxw), font=grande, fill=(255, 255, 255))
    draw.text((tx, 135), _caber(draw, nome, media, maxw), font=media, fill=(255, 255, 255))
    draw.text((tx, 200), _caber(draw, linha_final, pequena, maxw), font=pequena, fill=(215, 215, 215))
    saida = BytesIO()
    fundo.save(saida, format="PNG")
    return saida.getvalue()

async def boas_vindas(membro, convite=None):
    """Mensagem de boas-vindas que MARCA o membro, com embed, cartão com a foto e quem convidou."""
    if not BOAS_VINDAS_ATIVADO or membro.bot:
        return
    guild = membro.guild
    extra = {}
    if convite and convite.get("autor"):
        extra["{convidado_por}"] = convite["autor"].mention

    if BOAS_VINDAS_DM:
        try:
            await membro.send(cortar(aplicar_modelo(BOAS_VINDAS_DM, membro, extra), 1900))
        except Exception:
            pass

    canal = achar_canal_texto(guild, CANAL_BOAS_VINDAS, ("boas-vindas", "bem-vindo", "welcome"), publico=True) or guild.system_channel
    if canal is None:
        return
    numero = guild.member_count or len(guild.members)
    embed = discord.Embed(
        title=cortar(aplicar_modelo(BOAS_VINDAS_TITULO, membro, extra), 250),
        description=cortar(montar_texto_boas_vindas(membro, extra), 4000),
        color=COR, timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=membro.display_avatar.url)
    embed.add_field(name="📅 Conta criada", value=discord.utils.format_dt(membro.created_at, "R"), inline=True)
    embed.add_field(name="👥 Membro nº", value=f"**{numero}**", inline=True)
    if convite and convite.get("autor"):
        embed.add_field(name="📩 Convidado por", value=convite["autor"].mention, inline=True)
    embed.set_footer(text=f"{guild.name} • {NOME_SERVIDOR}", icon_url=guild.icon.url if guild.icon else None)

    arquivo = None
    if BOAS_VINDAS_BANNER:
        embed.set_image(url=BOAS_VINDAS_BANNER)
    elif BOAS_VINDAS_CARTAO:
        try:
            avatar = await membro.display_avatar.replace(size=256, format="png").read()
            nome_cartao = re.sub(r'[^\w\s\-.!@#&()\[\]]', '', membro.display_name).strip() or "Novo membro"
            png = await asyncio.get_running_loop().run_in_executor(
                None, desenhar_cartao, avatar, "BEM-VINDO(A)", nome_cartao, f"Você é o membro nº {numero}"
            )
            arquivo = discord.File(BytesIO(png), filename="boas-vindas.png")
            embed.set_image(url="attachment://boas-vindas.png")
        except Exception as e:
            print(f"[Aviso] Não consegui desenhar o cartão de boas-vindas (mando só o embed): {e!r}")
            arquivo = None

    conteudo = aplicar_modelo(BOAS_VINDAS_CONTEUDO, membro, extra) if BOAS_VINDAS_MARCAR else None
    try:
        msg = await canal.send(content=conteudo, embed=embed, file=arquivo,
                               allowed_mentions=discord.AllowedMentions(users=[membro]))
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui enviar a mensagem de boas-vindas em #{canal.name}: {e}")
        return
    if BOAS_VINDAS_APAGAR_SEG:
        try:
            await msg.delete(delay=BOAS_VINDAS_APAGAR_SEG)
        except discord.HTTPException:
            pass

async def despedida(membro):
    """Aviso de que alguém saiu (não avisa se a pessoa foi banida/expulsa pelo bot)."""
    if not BOAS_VINDAS_ATIVADO or membro.bot:
        return
    if membro.id in bot.silenciar_saida:
        bot.silenciar_saida.discard(membro.id)
        return
    guild = membro.guild
    canal = achar_canal_texto(guild, CANAL_SAIDAS, ("saidas", "saída", "saida", "despedida"), publico=True)
    if canal is None:
        return
    await asyncio.sleep(2)
    try:
        await guild.fetch_ban(membro)   # foi banido? então não manda "saiu"
        return
    except discord.HTTPException:
        pass                            # NotFound = não está banido (saiu mesmo)
    try:
        await canal.send(aplicar_modelo(SAIDA_TEXTO, membro), allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass

async def dar_cargo_automatico(membro):
    cargo_id = CARGO_AUTOMATICO_BOT if membro.bot else CARGO_AUTOMATICO
    if not cargo_id:
        return
    cargo = membro.guild.get_role(cargo_id)
    if cargo is None or not cargo_seguro(membro.guild, cargo):
        print("[Aviso] Cargo automático ignorado: ele não existe, está acima do cargo do bot ou tem permissão perigosa.")
        return
    try:
        await membro.add_roles(cargo, reason="Cargo automático de entrada")
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui dar o cargo automático a {membro}: {e}")

# ==================== PERFIL (nome/apelido impróprio -> #automod-profile) ====================
PERFIL_CD = {}   # id -> quando foi checado (evita checar/logar duas vezes seguidas)

def problema_no_nome(nome):
    """Devolve o motivo se o nome tem convite, golpe ou palavrão (senão None)."""
    if not nome:
        return None
    if achar_convite(nome):
        return "convite de servidor no nome"
    if achar_na_lista(nome, TERMOS_BAN_C):
        return "termo de golpe no nome"
    if achar_na_lista(nome, PALAVROES_C):
        return "palavrão no nome"
    return None

async def checar_perfil(membro):
    """Nome/apelido impróprio? Troca o apelido por NICK_PADRAO e registra no #automod-profile. True = mexeu."""
    if membro.bot or membro.id == membro.guild.owner_id or (STAFF_ISENTA_DO_AUTOMOD and eh_staff(membro)):
        return False
    agora = time.monotonic()
    if agora - PERFIL_CD.get(membro.id, -1000.0) < 10:
        return False
    if len(PERFIL_CD) > 2000:
        PERFIL_CD.clear()
    PERFIL_CD[membro.id] = agora

    guild = membro.guild
    motivo = problema_no_nome(membro.display_name)
    if motivo:
        acao = f"Apelido trocado para \"{NICK_PADRAO}\""
        try:
            await membro.edit(nick=NICK_PADRAO, reason=f"Automod: {motivo}")
        except discord.HTTPException:
            acao = "Só registrei (não consegui trocar o apelido: cargo acima do bot?)"
        await log_automod(guild, membro, motivo, None, f"Nome: {membro.display_name}", acao, "perfil")
        return True
    outro = problema_no_nome(membro.name) or problema_no_nome(getattr(membro, "global_name", None))
    if outro:
        await log_automod(guild, membro, f"{outro} (nome de usuário)", None, f"Usuário: {membro.name}",
                          "Só registrei (o apelido no servidor está ok)", "perfil")
    return False

# ==================== BOOST (agradecimento) ====================
TIPOS_BOOST = (
    discord.MessageType.premium_guild_subscription,
    discord.MessageType.premium_guild_tier_1,
    discord.MessageType.premium_guild_tier_2,
    discord.MessageType.premium_guild_tier_3,
)

async def agradecer_boost(message):
    if not BOOST_AGRADECER:
        return
    guild, membro = message.guild, message.author
    canal = achar_canal_texto(guild, CANAL_BOOSTER) or message.channel
    embed = discord.Embed(
        title="💎 Novo impulso no servidor!",
        description=f"{membro.mention} impulsionou o **{NOME_SERVIDOR}**! Muito obrigado pelo apoio! 💜",
        color=0xF47FFF, timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=membro.display_avatar.url)
    embed.set_footer(text=f"Agora temos {guild.premium_subscription_count} impulso(s)")
    await canal.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[membro]))

# ==================== SALAS DE VOZ TEMPORÁRIAS ====================
async def salas_temporarias(membro, antes, depois):
    """Entrou no canal "➕ Criar sala" (SALA_TEMP_CRIADOR)? Ganha uma sala só dele, que some quando esvazia."""
    if not SALA_TEMP_CRIADOR:
        return
    guild = membro.guild
    if depois.channel and depois.channel.id == SALA_TEMP_CRIADOR:
        criador = depois.channel
        permissoes = dict(criador.overwrites)
        permissoes[membro] = discord.PermissionOverwrite(
            view_channel=True, connect=True, manage_channels=True, move_members=True, mute_members=True
        )
        try:
            sala = await guild.create_voice_channel(
                f"{SALA_TEMP_PREFIXO}{membro.display_name}"[:100],
                category=criador.category, overwrites=permissoes, reason="Sala de voz temporária"
            )
            await membro.move_to(sala)
        except discord.HTTPException as e:
            print(f"[Aviso] Não consegui criar a sala temporária de {membro}: {e}")

    canal = antes.channel
    if canal and canal.id != SALA_TEMP_CRIADOR and canal.name.startswith(SALA_TEMP_PREFIXO) and not canal.members:
        try:
            await canal.delete(reason="Sala temporária vazia")
        except discord.HTTPException:
            pass

# ==================== TICKETS (estilo Ticket King / BobsBot) ====================
def setor_por_chave(chave):
    return next((s for s in TICKET_SETORES if s["chave"] == chave), None)

def setores_do_painel():
    """Setores que aparecem no painel de tickets (os com no_painel = False abrem por outro botão, tipo o do Booster)."""
    return [s for s in TICKET_SETORES if s.get("no_painel", True)]

async def canal_log_do_setor(guild, setor):
    """Canal da transcrição desse setor (canal_log) ou o #logs-ticket padrão."""
    id_canal = setor.get("canal_log", 0) if setor else 0
    canal = guild.get_channel(id_canal) if id_canal else None
    if isinstance(canal, discord.TextChannel):
        return canal
    return await obter_canal_log(guild, "ticket")

def ler_ticket(canal):
    """Lê o tópico do canal (K7NG-ticket:dono:setor:numero:assumido). Devolve um dict, ou None se o canal não for um ticket."""
    topico = getattr(canal, "topic", None) or ""
    if not topico.startswith(TOPICO_TICKET):
        return None
    partes = topico[len(TOPICO_TICKET):].split(":")
    try:
        dono = int(partes[0])
    except ValueError:
        return None

    def numero_em(i):
        return int(partes[i]) if len(partes) > i and partes[i].isdigit() else 0

    return {"dono": dono, "setor": partes[1] if len(partes) > 1 else "", "numero": numero_em(2), "assumido": numero_em(3)}

def tickets_do_usuario(guild, uid):
    achados = []
    for canal in guild.text_channels:
        info = ler_ticket(canal)
        if info and info["dono"] == uid:
            achados.append(canal)
    return achados

def cargos_atendimento(guild, setor=None):
    """Devolve (cargos que enxergam o ticket, cargos que levam ping). Sem nenhum cargo configurado, quem tem permissão de moderação enxerga."""
    ids = set(CARGOS_STAFF_EXTRA)
    if CARGO_STAFF:
        ids.add(CARGO_STAFF)
    if setor and setor.get("cargo"):
        ids.add(setor["cargo"])
    explicitos = [r for r in (guild.get_role(i) for i in ids) if r]
    if explicitos:
        return explicitos, explicitos
    por_permissao = [
        r for r in guild.roles
        if not r.is_default() and not r.managed and not r.permissions.administrator and (
            r.permissions.manage_messages or r.permissions.kick_members
            or r.permissions.ban_members or r.permissions.moderate_members
        )
    ]
    return por_permissao, []

def eh_atendente(membro, chave_setor=""):
    """Staff geral ou cargo do setor daquele ticket."""
    if eh_staff(membro):
        return True
    setor = setor_por_chave(chave_setor)
    cargo_id = setor.get("cargo") if setor else 0
    return bool(cargo_id and isinstance(membro, discord.Member) and membro.get_role(cargo_id))

def proximo_numero_ticket():
    bot.banco.dados["tickets"] = int(bot.banco.dados.get("tickets", 0)) + 1
    bot.banco.sujo = True
    return bot.banco.dados["tickets"]

# ---------- Botões e menu do painel ----------
class BotaoSetor(discord.ui.Button):
    def __init__(self, setor):
        super().__init__(
            label=setor["nome"][:80], emoji=setor.get("emoji") or None,
            style=discord.ButtonStyle.secondary, custom_id=f"k7ng_tk:{setor['chave']}"
        )
        self.chave = setor["chave"]

    async def callback(self, interaction: discord.Interaction):
        await iniciar_ticket(interaction, self.chave)

class ViewTicketsBotoes(discord.ui.View):
    """Painel com botões (estilo Ticket King)."""
    def __init__(self):
        super().__init__(timeout=None)
        for setor in setores_do_painel():
            self.add_item(BotaoSetor(setor))

class SelectTicket(discord.ui.Select):
    def __init__(self):
        opcoes = [
            discord.SelectOption(label=s["nome"][:100], value=s["chave"], description=s["desc"][:100], emoji=s.get("emoji") or None)
            for s in setores_do_painel()
        ]
        super().__init__(placeholder=TICKET_MENU_PLACEHOLDER, min_values=1, max_values=1,
                         options=opcoes, custom_id="k7ng_sel_ticket")

    async def callback(self, interaction: discord.Interaction):
        await iniciar_ticket(interaction, self.values[0], recarregar_menu=True)

class ViewTicketsMenu(discord.ui.View):
    """Painel com menu de seleção (estilo BobsBot)."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelectTicket())

# ---------- Janelinhas (modais) ----------
class ModalTicket(discord.ui.Modal):
    def __init__(self, setor):
        super().__init__(title=setor["nome"][:45], timeout=900)
        self.setor = setor
        self.motivo = discord.ui.TextInput(
            label="Explique o motivo do ticket", style=discord.TextStyle.paragraph,
            placeholder=(setor.get("pergunta") or "Conte com detalhes o que você precisa...")[:100],
            min_length=5, max_length=900, required=True
        )
        self.add_item(self.motivo)

    async def on_submit(self, interaction: discord.Interaction):
        await criar_ticket(interaction, self.setor["chave"], self.motivo.value)

class ModalFecharTicket(discord.ui.Modal, title="Fechar ticket"):
    motivo = discord.ui.TextInput(
        label="Motivo do fechamento (opcional)", style=discord.TextStyle.paragraph,
        placeholder="Ex.: problema resolvido", required=False, max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await fechar_ticket(interaction, self.motivo.value or "")

# ---------- Botões dentro do ticket ----------
class ViewTicketControle(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="k7ng_fechar_ticket")
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        info = ler_ticket(interaction.channel)
        if info is None:
            await interaction.response.send_message("❌ Isso não parece ser um ticket.", ephemeral=True)
            return
        if not (eh_atendente(interaction.user, info["setor"]) or interaction.user.id == info["dono"]):
            await interaction.response.send_message("❌ Só a staff ou quem abriu o ticket pode fechá-lo.", ephemeral=True)
            return
        await interaction.response.send_modal(ModalFecharTicket())

    @discord.ui.button(label="Assumir", style=discord.ButtonStyle.success, emoji="🙋", custom_id="k7ng_assumir_ticket")
    async def assumir(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        info = ler_ticket(canal)
        if info is None:
            await interaction.response.send_message("❌ Isso não parece ser um ticket.", ephemeral=True)
            return
        if not eh_atendente(interaction.user, info["setor"]):
            await interaction.response.send_message("❌ Só a staff pode assumir o ticket.", ephemeral=True)
            return
        if info["assumido"]:
            await interaction.response.send_message(f"ℹ️ Este ticket já foi assumido por <@{info['assumido']}>.", ephemeral=True)
            return
        novo_topico = f"{TOPICO_TICKET}{info['dono']}:{info['setor']}:{info['numero']}:{interaction.user.id}"
        try:
            await canal.edit(topic=novo_topico, reason=f"Ticket assumido por {interaction.user.name}")
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            f"🙋 {interaction.user.mention} assumiu este ticket! <@{info['dono']}>, é com ele(a) que você vai falar.",
            allowed_mentions=discord.AllowedMentions(users=True)
        )
        button.disabled = True
        button.label = "Assumido"
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass
        await enviar_log(interaction.guild, "ticket", "🙋 Ticket assumido",
                         f"🎫 {canal.mention}\n👮 **Staff:** {interaction.user.mention}", cor=COR_VERDE,
                         canal=await canal_log_do_setor(interaction.guild, setor_por_chave(info["setor"])))

async def iniciar_ticket(interaction, chave, recarregar_menu=False):
    """Primeiro passo: confere tudo e abre a janelinha do motivo (ou cria direto, se TICKET_PEDIR_MOTIVO = False)."""
    guild = interaction.guild
    if guild is None or guild.id != GUILD_ID:
        return
    setor = setor_por_chave(chave)
    if setor is None:
        await interaction.response.send_message(
            "❌ Esse setor não existe mais. Peça para a staff reenviar o painel de tickets.", ephemeral=True)
    else:
        abertos = tickets_do_usuario(guild, interaction.user.id)
        if len(abertos) >= TICKET_MAX_POR_USUARIO:
            await interaction.response.send_message(f"❌ Você já tem um ticket aberto: {abertos[0].mention}", ephemeral=True)
        elif TICKET_PEDIR_MOTIVO:
            await interaction.response.send_modal(ModalTicket(setor))
        else:
            await criar_ticket(interaction, chave, "")
    if recarregar_menu:   # tira a opção que ficou "marcada" no menu
        try:
            await interaction.message.edit(view=ViewTicketsMenu())
        except discord.HTTPException:
            pass

async def criar_ticket(interaction, chave, motivo=""):
    guild, membro = interaction.guild, interaction.user
    if guild is None or guild.id != GUILD_ID:
        return
    setor = setor_por_chave(chave)
    if setor is None:
        await interaction.response.send_message("❌ Esse setor não existe mais.", ephemeral=True)
        return
    if membro.id in bot.criando_ticket:
        await interaction.response.send_message("⏳ Seu ticket já está sendo criado...", ephemeral=True)
        return
    bot.criando_ticket.add(membro.id)
    try:
        await interaction.response.defer(ephemeral=True)
        abertos = tickets_do_usuario(guild, membro.id)
        if len(abertos) >= TICKET_MAX_POR_USUARIO:
            await interaction.followup.send(f"❌ Você já tem um ticket aberto: {abertos[0].mention}", ephemeral=True)
            return

        categoria = None
        for id_categoria in (setor.get("categoria", 0), CATEGORIA_TICKETS):   # 1º a do setor, 2º a geral
            candidata = guild.get_channel(id_categoria) if id_categoria else None
            if isinstance(candidata, discord.CategoryChannel):
                categoria = candidata
                break
        if categoria is None:
            try:
                categoria = await obter_categoria(guild, "TICKETS")
            except discord.HTTPException:
                categoria = None

        visiveis, ping = cargos_atendimento(guild, setor)
        permissoes = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            membro: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                                embed_links=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True,
                                                  embed_links=True, attach_files=True, read_message_history=True),
        }
        for cargo in visiveis:
            permissoes[cargo] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                                            embed_links=True, read_message_history=True)

        numero = proximo_numero_ticket()
        nome_limpo = re.sub(r"[^a-z0-9-]", "", membro.name.lower())[:20] or str(membro.id)[-6:]
        try:
            canal = await guild.create_text_channel(
                name=f"{setor['chave']}-{nome_limpo}"[:90], category=categoria, overwrites=permissoes,
                topic=f"{TOPICO_TICKET}{membro.id}:{setor['chave']}:{numero}",
                reason=f"Ticket #{numero} de {membro.name} ({setor['nome']})"
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Não consegui criar o ticket ({type(e).__name__}). Avise a staff.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{setor.get('emoji') or '🎫'} {NOME_SERVIDOR} - {setor['nome']}",
            description=(setor.get("mensagem") or TICKET_MENSAGEM_PADRAO).replace("{mention}", membro.mention),
            color=COR, timestamp=discord.utils.utcnow()
        )
        if IMAGEM_TICKET_ABERTO:
            embed.set_image(url=IMAGEM_TICKET_ABERTO)
        if motivo:
            embed.add_field(name="📝 Motivo informado", value=cortar(motivo, 1000), inline=False)
        embed.add_field(name="🎫 Ticket", value=f"#{numero:04d}", inline=True)
        embed.add_field(name="📂 Setor", value=setor["nome"], inline=True)
        embed.add_field(name="🕒 Aberto", value=discord.utils.format_dt(discord.utils.utcnow(), "R"), inline=True)
        embed.set_thumbnail(url=membro.display_avatar.url)
        rodape(embed, guild)

        conteudo = f"{membro.mention} {' '.join(r.mention for r in ping)}".strip()
        try:
            await canal.send(content=conteudo, embed=embed, view=ViewTicketControle(),
                             allowed_mentions=discord.AllowedMentions(users=[membro], roles=True))
        except discord.HTTPException as e:
            print(f"[Aviso] Não consegui enviar a mensagem inicial do ticket: {e}")

        descricao = (
            f"🎫 **Ticket #{numero:04d}** — {canal.mention}\n"
            f"📂 **Setor:** {setor['nome']}\n"
            f"👤 **Aberto por:** {membro.mention}"
        )
        if motivo:
            descricao += f"\n📝 **Motivo:** {cortar(motivo, 300)}"
        await enviar_log(guild, "ticket", "🎫 Ticket aberto", descricao, cor=COR_VERDE, usuario=membro,
                         canal=await canal_log_do_setor(guild, setor))
        await interaction.followup.send(f"✅ Ticket criado em {canal.mention}!", ephemeral=True)
    finally:
        bot.criando_ticket.discard(membro.id)

# ---------- Transcrição (arquivo .html com toda a conversa) ----------
CSS_TRANSCRICAO = """
body{background:#1e1f22;color:#dbdee1;font-family:Arial,Helvetica,sans-serif;margin:0;padding:24px}
h1{color:#fff;font-size:22px;margin:0 0 6px} .info{color:#949ba4;font-size:13px;margin-bottom:20px;line-height:1.6}
.msg{display:flex;gap:12px;padding:8px 0;border-top:1px solid #2b2d31}
.av{width:40px;height:40px;border-radius:50%;background:#2b2d31;flex:none}
.nome{font-weight:bold;color:#fff} .hora{color:#949ba4;font-size:12px;margin-left:8px}
.tag{background:#5865f2;color:#fff;font-size:10px;padding:1px 5px;border-radius:4px;margin-left:6px}
.extra{margin-top:4px;font-size:13px;color:#b5bac1} a{color:#00a8fc}
"""

def montar_transcricao(canal, mensagens, nome_setor, numero_txt, dono, fechador, motivo):
    esc = html.escape
    linhas = []
    for m in mensagens:
        quando = m.created_at.strftime("%d/%m/%Y %H:%M:%S")
        texto = esc(m.content or "").replace("\n", "<br>")
        extras = []
        for a in m.attachments:
            extras.append(f'<div class="extra">📎 <a href="{esc(a.url)}">{esc(a.filename)}</a></div>')
        for e in m.embeds:
            resumo = " — ".join(p for p in (e.title, e.description) if p)
            if resumo:
                extras.append(f'<div class="extra">🧩 {esc(cortar(resumo, 400))}</div>')
        tag_bot = '<span class="tag">BOT</span>' if m.author.bot else ""
        avatar = esc(avatar_de(m.author) or "")
        linhas.append(
            f'<div class="msg"><img class="av" src="{avatar}" alt="">'
            f'<div><span class="nome">{esc(m.author.display_name)}</span>{tag_bot}<span class="hora">{quando}</span>'
            f'<div>{texto}</div>{"".join(extras)}</div></div>'
        )
    nome_dono = esc(str(getattr(dono, "name", dono)))
    cabecalho = (
        f"<h1>Transcrição do ticket #{esc(numero_txt)} — {esc(nome_setor)}</h1>"
        f'<div class="info">Servidor: {esc(canal.guild.name)} • Canal: #{esc(canal.name)}<br>'
        f"Aberto por: {nome_dono} • Fechado por: {esc(fechador.name)}<br>"
        f"Motivo do fechamento: {esc(motivo or 'não informado')}<br>"
        f"Mensagens salvas: {len(mensagens)}</div>"
    )
    documento = (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        f"<title>Ticket #{esc(numero_txt)}</title><style>{CSS_TRANSCRICAO}</style></head><body>"
        f"{cabecalho}{''.join(linhas)}</body></html>"
    )
    return documento.encode("utf-8")

async def fechar_ticket(interaction, motivo=""):
    """Salva a transcrição no #logs-ticket (e no privado de quem abriu) e apaga o canal."""
    canal, guild = interaction.channel, interaction.guild
    info = ler_ticket(canal)
    if info is None:
        await interaction.response.send_message("❌ Isso não parece ser um ticket.", ephemeral=True)
        return
    if canal.id in bot.tickets_fechando:
        await interaction.response.send_message("⏳ Esse ticket já está sendo fechado.", ephemeral=True)
        return
    bot.tickets_fechando.add(canal.id)
    await interaction.response.send_message("🔒 Fechando o ticket e salvando a transcrição... o canal some em 5 segundos.")
    try:
        mensagens = [m async for m in canal.history(limit=TICKET_TRANSCRICAO_MAX, oldest_first=True)]
        setor = setor_por_chave(info["setor"])
        nome_setor = setor["nome"] if setor else (info["setor"] or "Ticket")
        numero_txt = f"{info['numero']:04d}" if info["numero"] else canal.name
        dono = guild.get_member(info["dono"]) or await buscar_usuario(info["dono"])
        fechador = interaction.user
        conteudo_html = montar_transcricao(canal, mensagens, nome_setor, numero_txt, dono, fechador, motivo)
        nome_arquivo = f"transcricao-ticket-{numero_txt}.html"

        def novo_arquivo():
            return discord.File(BytesIO(conteudo_html), filename=nome_arquivo)

        embed = discord.Embed(title=f"🔒 Ticket #{numero_txt} fechado", color=COR, timestamp=discord.utils.utcnow())
        embed.add_field(name="📂 Setor", value=nome_setor, inline=True)
        embed.add_field(name="👤 Aberto por", value=dono.mention if dono else f"<@{info['dono']}>", inline=True)
        embed.add_field(name="🔒 Fechado por", value=fechador.mention, inline=True)
        embed.add_field(name="🙋 Assumido por", value=f"<@{info['assumido']}>" if info["assumido"] else "ninguém", inline=True)
        embed.add_field(name="💬 Mensagens", value=str(len(mensagens)), inline=True)
        embed.add_field(name="📝 Motivo", value=cortar(motivo, 500) or "não informado", inline=False)
        rodape(embed, guild)

        canal_log = await canal_log_do_setor(guild, setor)
        if canal_log:
            try:
                await canal_log.send(embed=embed, file=novo_arquivo(), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as e:
                print(f"[Aviso] Não consegui enviar a transcrição para o #{canal_log.name}: {e}")

        if isinstance(dono, (discord.Member, discord.User)):   # cópia no privado de quem abriu
            try:
                await dono.send(f"Seu ticket no **{NOME_SERVIDOR}** foi fechado. Segue a transcrição:", embed=embed, file=novo_arquivo())
            except Exception:
                pass

        await asyncio.sleep(5)
        await canal.delete(reason=f"Ticket #{numero_txt} fechado por {fechador.name}")
    except Exception as e:
        print(f"[ERRO] Ao fechar o ticket {canal.name}: {e!r}")
        try:
            await canal.send("❌ Deu erro ao fechar o ticket. Um membro da staff pode apagar este canal manualmente.")
        except Exception:
            pass
    finally:
        bot.tickets_fechando.discard(canal.id)

# ---------- Painel ----------
def montar_painel_tickets(guild, estilo):
    """Monta (embed, view) do painel. estilo = "botoes" (Ticket King) ou "menu" (BobsBot)."""
    icone = guild.icon.url if guild.icon else None
    if estilo == "menu":
        blocos = [f"**{s['nome']}:**\n↳ {s['desc']}" for s in setores_do_painel()]
        descricao = "\n\n".join(blocos) + "\n\n" + TICKET_MENU_AVISO
        embed = discord.Embed(title=TICKET_PAINEL_TITULO, description=descricao, color=COR)
        view = ViewTicketsMenu()
    else:
        embed = discord.Embed(title=TICKET_PAINEL_TITULO, description=TICKET_PAINEL_TEXTO, color=COR)
        embed.set_author(name=TICKET_PAINEL_AUTOR, icon_url=icone)
        view = ViewTicketsBotoes()
    if IMAGEM_PAINEL_TICKETS:
        embed.set_image(url=IMAGEM_PAINEL_TICKETS)
    if MINIATURA_PAINEL_TICKETS:
        embed.set_thumbnail(url=MINIATURA_PAINEL_TICKETS)
    embed.set_footer(text=TICKET_PAINEL_RODAPE, icon_url=icone)
    return embed, view

@comando(name="painel_tickets", description="Envia o painel de tickets neste canal (botões ou menu).")
@app_commands.describe(estilo="Botões (igual Ticket King) ou menu de seleção (igual BobsBot)")
@app_commands.choices(estilo=[
    app_commands.Choice(name="Botões (estilo Ticket King)", value="botoes"),
    app_commands.Choice(name="Menu de seleção (estilo BobsBot)", value="menu"),
])
@exige(administrator=True)
async def painel_tickets_slash(interaction: discord.Interaction, estilo: Optional[str] = None):
    modo = estilo if estilo in ("botoes", "menu") else TICKET_ESTILO_PADRAO
    embed, view = montar_painel_tickets(interaction.guild, modo)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Painel de tickets enviado com sucesso!", ephemeral=True)

# ---------- Comandos /ticket (usar DENTRO de um ticket) ----------
def ticket_do_canal(interaction):
    """Confere se o comando foi usado dentro de um ticket por alguém da staff. Devolve (info, erro)."""
    info = ler_ticket(interaction.channel)
    if info is None:
        return None, "❌ Use esse comando dentro de um ticket."
    if not eh_atendente(interaction.user, info["setor"]):
        return None, "❌ Só a staff pode usar esse comando."
    return info, None

@ticket_grupo.command(name="adicionar", description="Adiciona um membro ao ticket atual.")
@app_commands.describe(membro="Quem vai entrar no ticket")
async def ticket_adicionar(interaction: discord.Interaction, membro: discord.Member):
    info, erro = ticket_do_canal(interaction)
    if erro:
        await interaction.response.send_message(erro, ephemeral=True)
        return
    try:
        await interaction.channel.set_permissions(
            membro, view_channel=True, send_messages=True, attach_files=True, read_message_history=True,
            reason=f"{interaction.user.name} adicionou ao ticket"
        )
    except discord.HTTPException:
        await interaction.response.send_message("❌ Não consegui adicionar essa pessoa.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ {membro.mention} foi adicionado ao ticket.")

@ticket_grupo.command(name="remover", description="Tira um membro do ticket atual.")
@app_commands.describe(membro="Quem vai sair do ticket")
async def ticket_remover(interaction: discord.Interaction, membro: discord.Member):
    info, erro = ticket_do_canal(interaction)
    if erro:
        await interaction.response.send_message(erro, ephemeral=True)
        return
    if membro.id == info["dono"]:
        await interaction.response.send_message("❌ Não dá para tirar quem abriu o ticket. Feche o ticket se já resolveu.", ephemeral=True)
        return
    try:
        await interaction.channel.set_permissions(membro, overwrite=None, reason=f"{interaction.user.name} removeu do ticket")
    except discord.HTTPException:
        await interaction.response.send_message("❌ Não consegui remover essa pessoa.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ {membro.mention} foi removido do ticket.")

@ticket_grupo.command(name="renomear", description="Muda o nome do canal do ticket.")
@app_commands.describe(nome="Novo nome do canal")
async def ticket_renomear(interaction: discord.Interaction, nome: app_commands.Range[str, 1, 50]):
    info, erro = ticket_do_canal(interaction)
    if erro:
        await interaction.response.send_message(erro, ephemeral=True)
        return
    novo = re.sub(r"[^a-z0-9-]", "-", nome.lower()).strip("-") or "ticket"
    try:
        await interaction.channel.edit(name=novo, reason=f"{interaction.user.name} renomeou o ticket")
    except discord.HTTPException:
        await interaction.response.send_message("❌ Não consegui renomear (o Discord limita a 2 trocas de nome a cada 10 minutos).", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Canal renomeado para `{novo}`.")

@ticket_grupo.command(name="fechar", description="Fecha o ticket atual (salva a transcrição no #logs-ticket).")
@app_commands.describe(motivo="Motivo do fechamento (opcional)")
async def ticket_fechar(interaction: discord.Interaction, motivo: Optional[str] = None):
    info = ler_ticket(interaction.channel)
    if info is None:
        await interaction.response.send_message("❌ Use esse comando dentro de um ticket.", ephemeral=True)
        return
    if not (eh_atendente(interaction.user, info["setor"]) or interaction.user.id == info["dono"]):
        await interaction.response.send_message("❌ Só a staff ou quem abriu o ticket pode fechá-lo.", ephemeral=True)
        return
    await fechar_ticket(interaction, motivo or "")

# ==================== PAINEL BOOSTER (estilo Sapphire) ====================
def cargo_do_booster(guild):
    """Cargo Booster: o do CARGO_BOOSTER ou o "Server Booster" que o próprio Discord cria."""
    return (guild.get_role(CARGO_BOOSTER) if CARGO_BOOSTER else None) or guild.premium_subscriber_role

def montar_painel_booster(guild):
    cargo = cargo_do_booster(guild)
    subtitulo = BOOSTER_SUBTITULO.replace("{cargo_booster}", cargo.mention if cargo else "**Booster**").replace("{servidor}", guild.name)
    vantagens = "\n\n".join(f" · {v}" for v in BOOSTER_VANTAGENS)
    descricao = f"```{BOOSTER_TITULO}```\n> {subtitulo}\n```\n{vantagens}\n```"
    embed = discord.Embed(description=descricao, color=BOOSTER_COR)
    if IMAGEM_PAINEL_BOOSTER:
        embed.set_image(url=IMAGEM_PAINEL_BOOSTER)
    if MINIATURA_PAINEL_BOOSTER:
        embed.set_thumbnail(url=MINIATURA_PAINEL_BOOSTER)
    return embed, ViewBooster()

async def conferir_booster(interaction):
    """True se quem clicou está impulsionando o servidor (staff passa, para poder testar). Senão avisa e devolve False."""
    guild, membro = interaction.guild, interaction.user
    if guild is None or guild.id != GUILD_ID:
        return False
    if getattr(membro, "premium_since", None) or eh_staff(membro):
        return True
    await interaction.response.send_message(
        "💎 Você ainda não está impulsionando o servidor, então não dá para resgatar. "
        "Clique em **Como virar booster** para ver como! 😉", ephemeral=True)
    return False

async def resgatar_booster(interaction):
    """Botão "Resgatar cargo": entrega o CARGO_BOOSTER_RESGATE (ou, se ele não estiver configurado, abre um ticket do setor booster)."""
    if not await conferir_booster(interaction):
        return
    guild, membro = interaction.guild, interaction.user
    cargo = guild.get_role(CARGO_BOOSTER_RESGATE) if CARGO_BOOSTER_RESGATE else None
    if cargo is None:
        await iniciar_ticket(interaction, "booster")
        return
    sem_mencoes = discord.AllowedMentions.none()
    if cargo in membro.roles:
        await interaction.response.send_message(f"✅ Você já tem o cargo {cargo.mention}!", ephemeral=True, allowed_mentions=sem_mencoes)
        return
    if not cargo_seguro(guild, cargo):
        await interaction.response.send_message("❌ Não consigo entregar esse cargo (ele está acima do meu cargo ou tem permissão perigosa). Avise a staff.", ephemeral=True)
        return
    try:
        await membro.add_roles(cargo, reason="Booster: cargo resgatado")
    except discord.HTTPException:
        await interaction.response.send_message("❌ Não consegui te dar o cargo. Avise a staff.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"🎁 Cargo {cargo.mention} resgatado! Quer um cargo só seu? Clique em **Cargo personalizado**.",
        ephemeral=True, allowed_mentions=sem_mencoes)
    await enviar_log(guild, "geral", "💎 Cargo de booster resgatado", f"{membro.mention} resgatou {cargo.mention}.",
                     cor=0xF47FFF, usuario=membro)

async def retirar_cargo_booster(membro):
    """Parou de impulsionar? Tira o cargo de resgate e avisa no log."""
    cargo = membro.guild.get_role(CARGO_BOOSTER_RESGATE) if CARGO_BOOSTER_RESGATE else None
    if cargo is None or cargo not in membro.roles:
        return
    try:
        await membro.remove_roles(cargo, reason="Booster: parou de impulsionar")
    except discord.HTTPException:
        return
    await enviar_log(membro.guild, "geral", "💎 Booster perdeu o cargo",
                     f"{membro.mention} parou de impulsionar e perdeu {cargo.mention}.", cor=COR, usuario=membro)

class ViewBooster(discord.ui.View):
    """Botões do painel Booster (continuam funcionando depois que o bot reinicia)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Resgatar cargo", style=discord.ButtonStyle.success, emoji="🎁", custom_id="k7ng_booster_resgatar")
    async def resgatar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await resgatar_booster(interaction)

    @discord.ui.button(label="Cargo personalizado", style=discord.ButtonStyle.primary, emoji="🎨", custom_id="k7ng_booster_personalizado")
    async def personalizado(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await conferir_booster(interaction):
            await iniciar_ticket(interaction, "booster")

    @discord.ui.button(label="Como virar booster", style=discord.ButtonStyle.secondary, emoji="💎", custom_id="k7ng_booster_info")
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "💎 **Como virar booster:** clique no nome do servidor (lá em cima) e escolha **Impulsionar servidor**. "
            "Depois é só voltar aqui e clicar em **Resgatar cargo**!", ephemeral=True)

@comando(name="painel_booster", description="Envia o painel \"Seja Booster\" (vantagens + botão para resgatar o cargo).")
@exige(administrator=True)
async def painel_booster_slash(interaction: discord.Interaction):
    embed, view = montar_painel_booster(interaction.guild)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Painel de booster enviado!", ephemeral=True)

# ==================== NÍVEIS / XP (estilo Loritta/MEE6) ====================
def xp_necessario(nivel):
    """XP para sair do nível `nivel` e ir para o próximo (mesma conta do MEE6)."""
    return 5 * nivel * nivel + 50 * nivel + 100

def calcular_nivel(xp_total):
    """Devolve (nível, XP dentro do nível, XP que o nível pede para ir ao próximo)."""
    nivel, resto = 0, int(xp_total)
    while resto >= xp_necessario(nivel):
        resto -= xp_necessario(nivel)
        nivel += 1
    return nivel, resto, xp_necessario(nivel)

def barra_progresso(atual, total, tamanho=12):
    cheio = int(tamanho * atual / total) if total else 0
    return "▰" * cheio + "▱" * (tamanho - cheio)

def ranking_xp():
    return sorted(bot.banco.dados["xp"].items(), key=lambda kv: kv[1][0], reverse=True)

def posicao_ranking(uid):
    ordenado = ranking_xp()
    for i, (chave, _) in enumerate(ordenado, 1):
        if chave == str(uid):
            return i, len(ordenado)
    return None, len(ordenado)

async def aplicar_recompensas_nivel(membro, nivel):
    """Dá os cargos configurados em RECOMPENSAS_NIVEL para quem chegou nesse nível."""
    if not RECOMPENSAS_NIVEL:
        return
    guild = membro.guild
    alcancados = sorted(((n, guild.get_role(rid)) for n, rid in RECOMPENSAS_NIVEL.items() if n <= nivel), key=lambda x: x[0])
    cargos = [(n, r) for n, r in alcancados if r is not None and cargo_seguro(guild, r)]
    if not cargos:
        return
    if SO_MAIOR_CARGO_NIVEL:
        maior = cargos[-1][1]
        dar = [maior] if maior not in membro.roles else []
        tirar = [r for _, r in cargos[:-1] if r in membro.roles]
    else:
        dar = [r for _, r in cargos if r not in membro.roles]
        tirar = []
    try:
        if dar:
            await membro.add_roles(*dar, reason=f"Recompensa do nível {nivel}")
        if tirar:
            await membro.remove_roles(*tirar, reason="Cargo de nível anterior")
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui dar o cargo de nível a {membro}: {e}")

async def subiu_de_nivel(message, nivel):
    membro = message.author
    canal = achar_canal_texto(message.guild, CANAL_NIVEIS) or message.channel
    embed = discord.Embed(description=f"🎉 {membro.mention} subiu para o **nível {nivel}**!", color=COR)
    embed.set_author(name=membro.display_name, icon_url=membro.display_avatar.url)
    try:
        await canal.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[membro]))
    except discord.HTTPException:
        pass
    await aplicar_recompensas_nivel(membro, nivel)

async def dar_xp(message):
    """Cada mensagem (1x por XP_COOLDOWN_SEG) rende um XP aleatório."""
    if not XP_ATIVADO or not bot.banco_carregado or message.channel.id in CANAIS_SEM_XP:
        return
    if len((message.content or "").strip()) < 3 and not message.attachments:
        return
    uid = message.author.id
    agora = time.monotonic()
    if agora - bot.xp_cooldown.get(uid, -10000.0) < XP_COOLDOWN_SEG:
        return
    bot.xp_cooldown[uid] = agora
    registro = bot.banco.dados["xp"].setdefault(str(uid), [0, 0])
    nivel_antes = calcular_nivel(registro[0])[0]
    registro[0] += random.randint(*XP_POR_MENSAGEM)
    registro[1] += 1
    bot.banco.sujo = True
    nivel_depois = calcular_nivel(registro[0])[0]
    if nivel_depois > nivel_antes:
        await subiu_de_nivel(message, nivel_depois)

@comando(name="rank", description="Mostra o nível e o XP de alguém (ou o seu).")
@app_commands.describe(membro="De quem você quer ver o nível (vazio = você)")
async def rank_slash(interaction: discord.Interaction, membro: Optional[discord.Member] = None):
    alvo = membro or interaction.user
    registro = bot.banco.dados["xp"].get(str(alvo.id))
    if not registro:
        await interaction.response.send_message(f"ℹ️ {alvo.mention} ainda não tem XP. É só conversar no servidor para ganhar!",
                                                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return
    nivel, atual, falta = calcular_nivel(registro[0])
    pos, total = posicao_ranking(alvo.id)
    embed = discord.Embed(title=f"⭐ Nível de {alvo.display_name}", color=COR)
    embed.set_thumbnail(url=alvo.display_avatar.url)
    embed.add_field(name="🏆 Posição", value=f"#{pos} de {total}", inline=True)
    embed.add_field(name="📈 Nível", value=str(nivel), inline=True)
    embed.add_field(name="✨ XP total", value=str(registro[0]), inline=True)
    embed.add_field(name="➡️ Próximo nível", value=f"{barra_progresso(atual, falta)}\n{atual}/{falta} XP", inline=False)
    embed.set_footer(text=f"{registro[1]} mensagens contadas")
    await interaction.response.send_message(embed=embed)

@comando(name="top", description="Ranking de XP do servidor (top 10).")
async def top_slash(interaction: discord.Interaction):
    ordenado = ranking_xp()[:10]
    if not ordenado:
        await interaction.response.send_message("ℹ️ Ninguém tem XP ainda.", ephemeral=True)
        return
    medalhas = {1: "🥇", 2: "🥈", 3: "🥉"}
    linhas = []
    for i, (uid, registro) in enumerate(ordenado, 1):
        nivel = calcular_nivel(registro[0])[0]
        linhas.append(f"{medalhas.get(i, f'**{i}.**')} <@{uid}> — nível **{nivel}** • {registro[0]} XP")
    embed = discord.Embed(title=f"🏆 Ranking de XP — {NOME_SERVIDOR}", description="\n".join(linhas), color=COR)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

@comando(name="xp_dar", description="Dá (ou tira, com número negativo) XP de um membro.")
@app_commands.describe(membro="Quem recebe o XP", quantidade="Quantidade de XP (pode ser negativa)")
@exige(administrator=True)
async def xp_dar_slash(interaction: discord.Interaction, membro: discord.Member, quantidade: int):
    registro = bot.banco.dados["xp"].setdefault(str(membro.id), [0, 0])
    registro[0] = max(0, registro[0] + quantidade)
    bot.banco.sujo = True
    nivel = calcular_nivel(registro[0])[0]
    await interaction.response.send_message(f"✅ {membro.mention} agora tem **{registro[0]} XP** (nível {nivel}).",
                                            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await aplicar_recompensas_nivel(membro, nivel)

@comando(name="xp_resetar", description="Zera o XP de um membro.")
@app_commands.describe(membro="Quem terá o XP zerado")
@exige(administrator=True)
async def xp_resetar_slash(interaction: discord.Interaction, membro: discord.Member):
    if bot.banco.dados["xp"].pop(str(membro.id), None) is not None:
        bot.banco.sujo = True
    await interaction.response.send_message(f"🧹 XP de {membro.mention} zerado.", ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())

# ==================== SORTEIOS ====================
def montar_embed_sorteio(premio, fim, ganhadores, host_id, cargo_id=0):
    embed = discord.Embed(
        title="🎉 SORTEIO",
        description=f"🎁 **Prêmio:** {premio}\n\nReaja com {EMOJI_SORTEIO} para participar!",
        color=COR
    )
    embed.add_field(name="⏰ Termina", value=f"<t:{fim}:R> (<t:{fim}:f>)", inline=False)
    embed.add_field(name="🏆 Ganhadores", value=str(ganhadores), inline=True)
    embed.add_field(name="👑 Criado por", value=f"<@{host_id}>", inline=True)
    if cargo_id:
        embed.add_field(name="🎭 Requisito", value=f"Ter o cargo <@&{cargo_id}>", inline=True)
    embed.set_footer(text=f"{NOME_SERVIDOR} • Sorteios")
    return embed

def sortear_com_peso(participantes, quantidade):
    """Sorteia sem repetir. Booster (quem impulsiona o servidor) tem SORTEIO_PESO_BOOSTER vezes mais chance."""
    pool, escolhidos = list(participantes), []
    while pool and len(escolhidos) < quantidade:
        pesos = [SORTEIO_PESO_BOOSTER if getattr(m, "premium_since", None) else 1 for m in pool]
        sorteado = random.choices(pool, weights=pesos, k=1)[0]
        escolhidos.append(sorteado)
        pool.remove(sorteado)
    return escolhidos

async def sortear_vencedores(guild, mensagem, sorteio, quantidade, excluir=()):
    """Lê quem reagiu, tira bots/quem saiu/quem não tem o cargo exigido e sorteia. Devolve (vencedores, total_de_participantes)."""
    reacao = discord.utils.get(mensagem.reactions, emoji=EMOJI_SORTEIO)
    participantes = []
    if reacao:
        cargo_id = sorteio.get("cargo", 0)
        async for usuario in reacao.users():
            if usuario.bot or usuario.id in excluir:
                continue
            membro = guild.get_member(usuario.id)
            if membro is None:
                continue
            if cargo_id and membro.get_role(cargo_id) is None:
                continue
            participantes.append(membro)
    return sortear_com_peso(participantes, quantidade), len(participantes)

async def finalizar_sorteio(guild, msg_id, rerolar=False, quantidade=None):
    """Sorteia, edita a mensagem e anuncia os ganhadores. Devolve (texto_para_o_admin, deu_certo)."""
    sorteio = bot.banco.dados["sorteios"].get(str(msg_id))
    if sorteio is None:
        return "❌ Não achei esse sorteio.", False

    def marcar_encerrado():
        sorteio["encerrado"] = True
        sorteio["encerrado_em"] = int(time.time())
        bot.banco.sujo = True

    canal = guild.get_channel_or_thread(sorteio["canal"])
    if canal is None:
        try:
            canal = await bot.fetch_channel(sorteio["canal"])
        except discord.HTTPException:
            canal = None
    if canal is None:
        marcar_encerrado()
        return "❌ O canal desse sorteio não existe mais.", False
    try:
        mensagem = await canal.fetch_message(int(msg_id))
    except discord.NotFound:
        marcar_encerrado()
        return "❌ A mensagem desse sorteio foi apagada.", False
    except discord.HTTPException:
        return "❌ Não consegui ler a mensagem do sorteio agora (tento de novo em instantes).", False

    quantidade = quantidade or sorteio["ganhadores"]
    excluir = set(sorteio.get("vencedores", [])) if rerolar else set()
    escolhidos, total = await sortear_vencedores(guild, mensagem, sorteio, quantidade, excluir)
    marcar_encerrado()
    sorteio["vencedores"] = [m.id for m in escolhidos]
    mencoes = ", ".join(m.mention for m in escolhidos)

    embed = discord.Embed(title="🎉 SORTEIO ENCERRADO", description=f"🎁 **Prêmio:** {sorteio['premio']}", color=0x2B2D31)
    embed.add_field(name="🏆 Ganhador(es)", value=mencoes or "Ninguém participou 😢", inline=False)
    embed.add_field(name="👥 Participantes", value=str(total), inline=True)
    embed.add_field(name="👑 Criado por", value=f"<@{sorteio['host']}>", inline=True)
    embed.set_footer(text=f"{NOME_SERVIDOR} • Sorteios")
    try:
        await mensagem.edit(embed=embed)
    except discord.HTTPException:
        pass

    if escolhidos:
        resgate = achar_canal_texto(guild, CANAL_TICKETS, ("ticket", "atendimento", "suporte"))
        onde = f"em {resgate.mention}" if resgate else "no canal de tickets"
        anuncio = (f"🎉 Parabéns {mencoes}! Você ganhou **{sorteio['premio']}**!\n"
                   f"🎫 Para resgatar, abra um ticket {onde} (setor **Resgatar Sorteios**).")
    else:
        anuncio = f"😢 O sorteio de **{sorteio['premio']}** terminou sem nenhum participante válido."
    try:
        await canal.send(anuncio, reference=mensagem, allowed_mentions=discord.AllowedMentions(users=True))
    except discord.HTTPException:
        pass
    for membro in escolhidos:   # aviso no privado (se a pessoa deixar)
        try:
            await membro.send(f"🎉 Você ganhou **{sorteio['premio']}** no sorteio do **{NOME_SERVIDOR}**! "
                              f"Abra um ticket no servidor para resgatar.")
        except Exception:
            pass
    return f"✅ Sorteio finalizado! Ganhador(es): {mencoes or 'ninguém'}", True

@sorteio_grupo.command(name="criar", description="Cria um sorteio (os membros participam reagindo).")
@app_commands.describe(
    premio="O que será sorteado", duracao="Quanto tempo dura. Ex.: 30m, 2h, 1d, 1d12h",
    ganhadores="Quantos ganhadores (1 a 20)", canal="Canal do sorteio (vazio = este canal)",
    cargo_exigido="Só quem tem esse cargo pode ganhar (opcional)"
)
@exige_exec(manage_guild=True)
async def sorteio_criar(interaction: discord.Interaction, premio: app_commands.Range[str, 1, 200], duracao: str,
                        ganhadores: app_commands.Range[int, 1, 20] = 1, canal: Optional[discord.TextChannel] = None,
                        cargo_exigido: Optional[discord.Role] = None):
    segundos = parse_duracao(duracao)
    if segundos is None or not 10 <= segundos <= 30 * 86400:
        await interaction.response.send_message(
            "❌ Duração inválida. Use algo como `30m`, `2h`, `1d` ou `1d12h` (de 10 segundos até 30 dias).", ephemeral=True)
        return
    if not bot.banco_carregado:
        await interaction.response.send_message("⏳ O bot ainda está ligando. Tente de novo em alguns segundos.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    destino = canal or achar_canal_texto(interaction.guild, CANAL_SORTEIOS) or interaction.channel
    fim = int(time.time()) + segundos
    try:
        mensagem = await destino.send(embed=montar_embed_sorteio(premio, fim, ganhadores, interaction.user.id,
                                                                  cargo_exigido.id if cargo_exigido else 0))
        await mensagem.add_reaction(EMOJI_SORTEIO)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Não consegui criar o sorteio em {destino.mention} ({type(e).__name__}). "
                                        f"Confira se o bot pode enviar mensagens e reagir nesse canal.")
        return
    bot.banco.dados["sorteios"][str(mensagem.id)] = {
        "canal": destino.id, "premio": premio, "fim": fim, "ganhadores": ganhadores, "host": interaction.user.id,
        "cargo": cargo_exigido.id if cargo_exigido else 0, "encerrado": False, "vencedores": [],
    }
    bot.banco.sujo = True
    await interaction.followup.send(f"✅ Sorteio criado em {destino.mention}! Termina <t:{fim}:R>.")

@sorteio_grupo.command(name="encerrar", description="Encerra um sorteio agora e sorteia os ganhadores.")
@app_commands.describe(mensagem_id="ID da mensagem do sorteio (clique com o botão direito > Copiar ID)")
@exige_exec(manage_guild=True)
async def sorteio_encerrar(interaction: discord.Interaction, mensagem_id: str):
    await interaction.response.defer(ephemeral=True)
    sorteio = bot.banco.dados["sorteios"].get(mensagem_id.strip())
    if sorteio is None or sorteio.get("encerrado"):
        await interaction.followup.send("❌ Não achei um sorteio **em andamento** com esse ID. (Para sortear de novo, use `/sorteio rerolar`.)")
        return
    texto, _ = await finalizar_sorteio(interaction.guild, int(mensagem_id.strip()))
    await interaction.followup.send(texto, allowed_mentions=discord.AllowedMentions.none())

@sorteio_grupo.command(name="rerolar", description="Sorteia de novo (novos ganhadores) um sorteio que já acabou.")
@app_commands.describe(mensagem_id="ID da mensagem do sorteio", ganhadores="Quantos ganhadores novos (vazio = o mesmo número de antes)")
@exige_exec(manage_guild=True)
async def sorteio_rerolar(interaction: discord.Interaction, mensagem_id: str,
                          ganhadores: Optional[app_commands.Range[int, 1, 20]] = None):
    await interaction.response.defer(ephemeral=True)
    sorteio = bot.banco.dados["sorteios"].get(mensagem_id.strip())
    if sorteio is None or not sorteio.get("encerrado"):
        await interaction.followup.send("❌ Não achei um sorteio **já encerrado** com esse ID.")
        return
    texto, _ = await finalizar_sorteio(interaction.guild, int(mensagem_id.strip()), rerolar=True, quantidade=ganhadores)
    await interaction.followup.send(texto, allowed_mentions=discord.AllowedMentions.none())

@sorteio_grupo.command(name="listar", description="Mostra os sorteios em andamento.")
@exige_exec(manage_guild=True)
async def sorteio_listar(interaction: discord.Interaction):
    ativos = [(mid, s) for mid, s in bot.banco.dados["sorteios"].items() if not s.get("encerrado")]
    if not ativos:
        await interaction.response.send_message("ℹ️ Nenhum sorteio em andamento.", ephemeral=True)
        return
    linhas = [f"• **{s['premio']}** — <#{s['canal']}> — termina <t:{s['fim']}:R> — ID `{mid}`" for mid, s in ativos[:15]]
    await interaction.response.send_message("🎉 **Sorteios em andamento:**\n" + "\n".join(linhas), ephemeral=True)

# ==================== AFK ====================
@comando(name="afk", description="Avisa que você está ausente (quem te marcar vê o motivo).")
@app_commands.describe(motivo="Motivo (opcional)")
async def afk_slash(interaction: discord.Interaction, motivo: str = "AFK"):
    if not bot.banco_carregado:
        await interaction.response.send_message("⏳ O bot ainda está ligando. Tente de novo em alguns segundos.", ephemeral=True)
        return
    motivo = cortar(motivo.strip() or "AFK", 100)
    bot.banco.dados["afk"][str(interaction.user.id)] = {"motivo": motivo, "quando": int(time.time())}
    bot.banco.sujo = True
    await interaction.response.send_message(f"💤 {interaction.user.mention} agora está AFK: **{discord.utils.escape_markdown(motivo)}**",
                                            allowed_mentions=discord.AllowedMentions.none())

async def tratar_afk(message):
    """Tira o AFK de quem voltou a falar e avisa quando alguém marca uma pessoa AFK."""
    if not bot.banco_carregado:
        return
    afk = bot.banco.dados["afk"]
    if not afk:
        return
    autor = message.author
    if str(autor.id) in afk:
        del afk[str(autor.id)]
        bot.banco.sujo = True
        try:
            await message.channel.send(f"👋 Bem-vindo(a) de volta, {autor.mention}! Tirei o seu AFK.", delete_after=8,
                                       allowed_mentions=discord.AllowedMentions(users=[autor]))
        except discord.HTTPException:
            pass
    avisos = []
    for usuario in message.mentions[:5]:
        dados = afk.get(str(usuario.id))
        if dados and usuario.id != autor.id:
            nome = discord.utils.escape_markdown(usuario.display_name)
            avisos.append(f"💤 **{nome}** está AFK: {discord.utils.escape_markdown(dados['motivo'])} (desde <t:{dados['quando']}:R>)")
    if avisos:
        try:
            await message.channel.send("\n".join(avisos)[:1900], reference=message, delete_after=15,
                                       allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

# ==================== SUGESTÕES ====================
@comando(name="sugestao", description="Envia uma sugestão para o servidor (a galera vota com ✅ ou ❌).")
@app_commands.describe(texto="Sua sugestão")
async def sugestao_slash(interaction: discord.Interaction, texto: app_commands.Range[str, 5, 1500]):
    canal = achar_canal_texto(interaction.guild, CANAL_SUGESTOES, ("sugest",))
    if canal is None:
        await interaction.response.send_message(
            "❌ A staff ainda não configurou o canal de sugestões (crie um canal com \"sugestoes\" no nome).", ephemeral=True)
        return
    embed = discord.Embed(title="💡 Nova sugestão", description=texto, color=COR, timestamp=discord.utils.utcnow())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text=f"ID: {interaction.user.id}")
    try:
        mensagem = await canal.send(embed=embed)
        for emoji in ("✅", "❌"):
            await mensagem.add_reaction(emoji)
    except discord.HTTPException:
        await interaction.response.send_message(f"❌ Não consegui enviar em {canal.mention}. Confira as permissões do bot.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Sugestão enviada em {canal.mention}! Obrigado.", ephemeral=True)

# ==================== PAINEL DE CARGOS (botões) ====================
class BotaoCargo(discord.ui.DynamicItem[discord.ui.Button], template=r"k7ng:cargo:(?P<id>[0-9]+)"):
    """Botão que dá/tira um cargo. O ID do cargo fica no custom_id, então continua funcionando depois que o bot reinicia."""
    def __init__(self, cargo_id, rotulo="Cargo"):
        super().__init__(discord.ui.Button(
            label=rotulo[:80], style=discord.ButtonStyle.secondary, custom_id=f"k7ng:cargo:{cargo_id}"
        ))
        self.cargo_id = cargo_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match, /):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction):
        guild, membro = interaction.guild, interaction.user
        cargo = guild.get_role(self.cargo_id) if guild else None
        if cargo is None:
            await interaction.response.send_message("❌ Esse cargo não existe mais.", ephemeral=True)
            return
        if not cargo_seguro(guild, cargo):
            await interaction.response.send_message(
                "❌ Não posso dar esse cargo (ele está acima do meu cargo ou tem permissão perigosa).", ephemeral=True)
            return
        try:
            if cargo in membro.roles:
                await membro.remove_roles(cargo, reason="Painel de cargos")
                await interaction.response.send_message(f"➖ Cargo **{cargo.name}** removido.", ephemeral=True)
            else:
                await membro.add_roles(cargo, reason="Painel de cargos")
                await interaction.response.send_message(f"➕ Cargo **{cargo.name}** adicionado!", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("❌ Não consegui mexer nesse cargo.", ephemeral=True)

@comando(name="painel_cargos", description="Envia um painel de botões para os membros pegarem/tirarem cargos.")
@app_commands.describe(
    titulo="Título do painel", descricao="Texto do painel (use \\n para pular linha)",
    cargo1="Cargo do botão 1", cargo2="Cargo do botão 2", cargo3="Cargo do botão 3", cargo4="Cargo do botão 4",
    cargo5="Cargo do botão 5", cargo6="Cargo do botão 6", cargo7="Cargo do botão 7", cargo8="Cargo do botão 8"
)
@exige(manage_roles=True)
async def painel_cargos_slash(interaction: discord.Interaction, titulo: str, descricao: str, cargo1: discord.Role,
                              cargo2: Optional[discord.Role] = None, cargo3: Optional[discord.Role] = None,
                              cargo4: Optional[discord.Role] = None, cargo5: Optional[discord.Role] = None,
                              cargo6: Optional[discord.Role] = None, cargo7: Optional[discord.Role] = None,
                              cargo8: Optional[discord.Role] = None):
    cargos = [c for c in (cargo1, cargo2, cargo3, cargo4, cargo5, cargo6, cargo7, cargo8) if c]
    invalidos = [c for c in cargos if not cargo_seguro(interaction.guild, c)]
    if invalidos:
        await interaction.response.send_message(
            "❌ Não posso usar estes cargos (estão acima do meu cargo, são de bot/integração ou têm permissão perigosa): "
            + ", ".join(c.mention for c in invalidos), ephemeral=True)
        return
    embed = discord.Embed(title=cortar(titulo, 250), description=cortar(descricao.replace("\\n", "\n"), 3000), color=COR)
    embed.set_footer(text="Clique no botão para pegar ou tirar o cargo.")
    view = discord.ui.View(timeout=None)
    for cargo in cargos:
        view.add_item(BotaoCargo(cargo.id, cargo.name))
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Painel de cargos enviado!", ephemeral=True)

# ==================== VERIFICAÇÃO POR BOTÃO ====================
class ViewVerificar(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verificar", style=discord.ButtonStyle.success, emoji="✅", custom_id="k7ng_verificar")
    async def verificar(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        cargo = guild.get_role(CARGO_VERIFICADO) if (guild and CARGO_VERIFICADO) else None
        if cargo is None:
            await interaction.response.send_message("❌ A verificação não está configurada. Avise a staff.", ephemeral=True)
            return
        if cargo in interaction.user.roles:
            await interaction.response.send_message("✅ Você já está verificado!", ephemeral=True)
            return
        if raid_ativo():
            await interaction.response.send_message("🛡️ Verificação pausada por segurança. Tente de novo em alguns minutos.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(cargo, reason="Verificação por botão")
        except discord.HTTPException:
            await interaction.response.send_message("❌ Não consegui te verificar. Avise a staff (o cargo do bot precisa estar acima do cargo de verificado).", ephemeral=True)
            return
        await interaction.response.send_message("✅ Verificado com sucesso! Bem-vindo(a)!", ephemeral=True)

# ==================== ROTINAS DE FUNDO ====================
@tasks.loop(seconds=30)
async def manutencao():
    """Limpeza de memória e fim do modo raid."""
    try:
        agora = time.monotonic()
        for uid in list(bot.hist_msgs):
            fila = bot.hist_msgs[uid]
            while fila and agora - fila[0][0] > SPAM_JANELA_MAX:
                fila.popleft()
            if not fila:
                del bot.hist_msgs[uid]
        for uid in list(bot.pontos):
            fila = bot.pontos[uid]
            while fila and agora - fila[0][0] > JANELA_REINCIDENCIA_MIN * 60:
                fila.popleft()
            if not fila:
                del bot.pontos[uid]
        for chave in list(bot.nuke_hist):
            fila = bot.nuke_hist[chave]
            if not fila or agora - fila[-1][0] > 120:
                del bot.nuke_hist[chave]
        for uid, quando in list(bot.nuke_punidos.items()):
            if agora - quando > 300:
                del bot.nuke_punidos[uid]
        for uid, quando in list(bot.xp_cooldown.items()):
            if agora - quando > max(XP_COOLDOWN_SEG, 60) * 2:
                del bot.xp_cooldown[uid]
        while bot.entradas_recentes and agora - bot.entradas_recentes[0][0] > RAID_JANELA_SEG:
            bot.entradas_recentes.popleft()

        if bot.raid_ate and agora >= bot.raid_ate:   # tempo do modo raid acabou
            guild = bot.get_guild(GUILD_ID)
            if guild:
                await desativar_raid(guild)
            else:
                bot.raid_ate = 0.0
    except Exception as e:   # sem isso, um erro derrubaria a rotina para sempre
        print(f"[Aviso] Erro na manutenção: {e!r}")

@manutencao.before_loop
async def antes_da_manutencao():
    await bot.wait_until_ready()

@tasks.loop(seconds=120)
async def salvar_banco():
    """A cada 2 minutos salva o XP/sorteios/AFK no Discord (só se mudou alguma coisa)."""
    if bot.banco_carregado and bot.banco.sujo:
        try:
            await bot.banco.salvar()
        except Exception as e:
            bot.banco.sujo = True
            print(f"[Aviso] Erro ao salvar o banco: {e!r}")

@salvar_banco.before_loop
async def antes_de_salvar_banco():
    await bot.wait_until_ready()

@tasks.loop(seconds=15)
async def loop_sorteios():
    """Encerra sozinho os sorteios que chegaram na hora e apaga os antigos da memória."""
    if not bot.banco_carregado:
        return
    try:
        agora = int(time.time())
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            return
        for mid, sorteio in list(bot.banco.dados["sorteios"].items()):
            if not sorteio.get("encerrado") and sorteio["fim"] <= agora:
                await finalizar_sorteio(guild, int(mid))
            elif sorteio.get("encerrado") and agora - sorteio.get("encerrado_em", agora) > 14 * 86400:
                bot.banco.dados["sorteios"].pop(mid, None)
                bot.banco.sujo = True
    except Exception as e:
        print(f"[Aviso] Erro na rotina de sorteios: {e!r}")

@loop_sorteios.before_loop
async def antes_dos_sorteios():
    await bot.wait_until_ready()

# ==================== EVENTOS ====================
PERMS_NECESSARIAS = {
    "ban_members": "Banir Membros", "kick_members": "Expulsar Membros", "moderate_members": "Silenciar Membros",
    "manage_roles": "Gerenciar Cargos", "manage_channels": "Gerenciar Canais", "manage_nicknames": "Gerenciar Apelidos",
    "manage_messages": "Gerenciar Mensagens", "view_audit_log": "Ver Registro de Auditoria",
    "manage_guild": "Gerenciar Servidor (para saber quem convidou)",
}

async def verificar_permissoes(guild):
    p = guild.me.guild_permissions
    if p.administrator:
        return
    faltando = [nome for attr, nome in PERMS_NECESSARIAS.items() if not getattr(p, attr)]
    if faltando:
        aviso = ", ".join(faltando)
        print(f"[Aviso] Faltam permissões para o bot: {aviso}")
        await enviar_alerta(
            guild, f"⚠️ {NOME_SERVIDOR} - Permissões Faltando",
            f"O bot precisa destas permissões para proteger o servidor direito:\n**{aviso}**\n\n"
            f"Dê **Administrador** ao cargo do bot (ou essas permissões) e deixe o cargo dele no topo da lista."
        )

async def sair_de_outros_servidores():
    """Bot privado: só sai se tiver certeza de que está no K7NG (para um GUILD_ID digitado errado não expulsar o bot de tudo)."""
    if not SAIR_DE_OUTROS_SERVIDORES or bot.get_guild(GUILD_ID) is None:
        return
    for g in list(bot.guilds):
        if g.id != GUILD_ID:
            print(f"[Privado] Saindo do servidor não autorizado: {g.name} ({g.id})")
            try:
                await g.leave()
            except discord.HTTPException:
                pass

@bot.event
async def on_ready():
    if not bot.registros_carregados:
        bot.registros_carregados = True
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            print(f"[ERRO] O bot não está no servidor GUILD_ID={GUILD_ID}. Confira o ID e se o bot foi convidado para o K7NG.")
        else:
            try:
                await obter_canal_log(guild, "ban")
                await obter_canal_log(guild, "mute")
                await carregar_registros(guild)
                bot.banco_carregado = await bot.banco.carregar(guild)
                if not bot.banco_carregado:
                    await enviar_alerta(
                        guild, f"⚠️ {NOME_SERVIDOR} - Banco de dados não carregou",
                        f"Não consegui ler o arquivo do canal `#{NOME_CANAL_DADOS}`. Níveis (XP), sorteios e AFK ficam desligados "
                        f"até o bot reiniciar. **Nada foi apagado.** Se o erro continuar, veja o console da hospedagem."
                    )
                await atualizar_cache_convites(guild)
                await verificar_permissoes(guild)
            except Exception as e:
                print(f"[Aviso] Erro ao preparar o servidor: {e!r}")
            await sair_de_outros_servidores()
            try:
                await enviar_log(guild, "geral", "🟢 Bot online", f"O **{bot.user.name}** ligou e está protegendo o {NOME_SERVIDOR}.", cor=COR_VERDE)
            except Exception:
                pass
    print(f"✅ Sistema perfeito! {bot.user.name} está online, protegendo o {NOME_SERVIDOR} (cor #{COR:06x}).")

@bot.event
async def on_guild_join(guild):
    await sair_de_outros_servidores()

@bot.event
async def on_member_join(membro):
    if membro.guild.id != GUILD_ID:
        return
    try:
        if await tratar_entrada(membro):
            return   # foi barrado pelo anti-raid: sem boas-vindas
    except Exception as e:
        print(f"[Aviso Anti-Raid] Erro ao tratar a entrada de {membro}: {e!r}")
    convite = None
    try:
        convite = await descobrir_convite(membro.guild)
    except Exception as e:
        print(f"[Aviso] Erro ao descobrir o convite: {e!r}")
    for rotina in (dar_cargo_automatico, checar_perfil):
        try:
            await rotina(membro)
        except Exception as e:
            print(f"[Aviso] {rotina.__name__} falhou: {e!r}")
    try:
        await boas_vindas(membro, convite)
    except Exception as e:
        print(f"[Aviso] Erro nas boas-vindas de {membro}: {e!r}")
    try:
        await log_entrada(membro, convite)
    except Exception as e:
        print(f"[Aviso] Erro no log de entrada: {e!r}")

@bot.event
async def on_member_remove(membro):
    if membro.guild.id != GUILD_ID:
        return
    try:
        await log_saida(membro)
    except Exception as e:
        print(f"[Aviso] Erro no log de saída: {e!r}")
    try:
        await despedida(membro)
    except Exception as e:
        print(f"[Aviso] Erro na despedida: {e!r}")

@bot.event
async def on_member_update(antes, depois):
    if depois.guild.id != GUILD_ID:
        return
    if antes.nick != depois.nick:
        try:
            await log_apelido(antes, depois)
            await checar_perfil(depois)
        except Exception as e:
            print(f"[Aviso] Erro ao tratar a troca de apelido: {e!r}")
    if antes.premium_since and not depois.premium_since:   # parou de impulsionar
        try:
            await retirar_cargo_booster(depois)
        except Exception as e:
            print(f"[Aviso] Erro ao tratar o fim do impulso: {e!r}")

@bot.event
async def on_user_update(antes, depois):
    try:
        await log_usuario(antes, depois)
        if antes.name != depois.name or getattr(antes, "global_name", None) != getattr(depois, "global_name", None):
            guild = bot.get_guild(GUILD_ID)
            membro = guild.get_member(depois.id) if guild else None
            if membro:
                await checar_perfil(membro)
    except Exception as e:
        print(f"[Aviso] Erro ao tratar a troca de nome: {e!r}")

@bot.event
async def on_voice_state_update(membro, antes, depois):
    if membro.guild.id != GUILD_ID or membro.bot:
        return
    for rotina in (log_voz, salas_temporarias):
        try:
            await rotina(membro, antes, depois)
        except Exception as e:
            print(f"[Aviso] {rotina.__name__} falhou: {e!r}")

@bot.event
async def on_invite_create(convite):
    if convite.guild and convite.guild.id == GUILD_ID:
        bot.convites[convite.code] = convite.uses or 0

@bot.event
async def on_audit_log_entry_create(entry):
    if entry.guild.id != GUILD_ID:
        return
    for rotina in (antinuke, log_manual, log_auditoria):
        try:
            await rotina(entry)
        except Exception as e:
            print(f"[Aviso] {rotina.__name__} falhou: {e!r}")

@bot.event
async def on_app_command_completion(interaction, command):
    try:
        await log_comando(interaction, command)
    except Exception as e:
        print(f"[Aviso] Erro no log de comando: {e!r}")

@bot.event
async def on_raw_message_delete(payload):
    esquecer_registros_apagados([payload.message_id])
    if payload.guild_id != GUILD_ID or payload.cached_message is None:
        return
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await log_mensagem_apagada(guild, payload.cached_message)
        except Exception as e:
            print(f"[Aviso] Erro no log de mensagem apagada: {e!r}")

@bot.event
async def on_raw_bulk_message_delete(payload):
    esquecer_registros_apagados(payload.message_ids)
    if payload.guild_id != GUILD_ID:
        return
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await log_apagadas_em_massa(guild, payload.channel_id, payload.cached_messages, len(payload.message_ids))
        except Exception as e:
            print(f"[Aviso] Erro no log de limpeza em massa: {e!r}")

@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None or message.guild.id != GUILD_ID:
        return

    # Mensagens do sistema (impulso, entrada...) não passam pelos filtros
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        if message.type in TIPOS_BOOST:
            try:
                await agradecer_boost(message)
            except Exception as e:
                print(f"[Aviso] Erro ao agradecer o impulso: {e!r}")
        return

    # 1. Golpes / mensagens fake / links falsos (ban ou kick automático, sem exceção de staff)
    try:
        if await filtro_golpes(message):
            return
    except Exception as e:
        print(f"[Aviso Automod] Erro no filtro de golpes: {e!r}")

    # 2. Imagens proibidas (só IDÊNTICAS). Vem ANTES dos filtros abaixo para uma mensagem com palavrão + imagem proibida
    #    não ter só o texto apagado com a imagem nunca conferida.
    try:
        if await checar_imagens_proibidas(message):
            return
    except Exception as e:
        print(f"[Aviso Automod] Erro na checagem de imagens: {e!r}")

    # 3. Convites, menções, palavrões, links de novatos, spam e formatação abusiva
    try:
        if await automod(message):
            return
    except Exception as e:
        print(f"[Aviso Automod] Erro no automod: {e!r}")

    # 4. Mensagem limpa: AFK e XP
    try:
        await tratar_afk(message)
        await dar_xp(message)
    except Exception as e:
        print(f"[Aviso] Erro no AFK/XP: {e!r}")

@bot.event
async def on_message_edit(antes, depois):
    if depois.author.bot or depois.guild is None or depois.guild.id != GUILD_ID:
        return

    try:
        await log_mensagem_editada(antes, depois)
    except Exception as e:
        print(f"[Aviso] Erro no log de edição: {e!r}")

    # O Discord "edita" a mensagem quando termina de gerar a prévia de um link (embed): confere as imagens da prévia
    if len(depois.embeds) > len(antes.embeds):
        try:
            if await checar_imagens_proibidas(depois, so_embeds=True):
                return
        except Exception as e:
            print(f"[Aviso Automod] Erro ao checar a prévia do link: {e!r}")

    # Editar a mensagem depois de enviar não burla os filtros de texto
    if antes.content == depois.content:
        return
    try:
        if await filtro_golpes(depois):
            return
        await automod(depois, editada=True)
    except Exception as e:
        print(f"[Aviso Automod] Erro ao checar a edição: {e!r}")

# ==================== TRATAMENTO DE ERROS DOS COMANDOS ====================
@bot.tree.error
async def erro_comando(interaction: discord.Interaction, erro: app_commands.AppCommandError):
    erro = getattr(erro, "original", erro)
    if isinstance(erro, app_commands.MissingPermissions):
        texto = "❌ Você não tem permissão para usar esse comando."
    elif isinstance(erro, app_commands.CheckFailure):
        texto = "❌ Você não pode usar esse comando aqui."
    else:
        nome = interaction.command.name if interaction.command else "?"
        print(f"[ERRO] /{nome}: {erro!r}")
        texto = f"❌ Deu um erro inesperado (`{type(erro).__name__}`). Tente de novo; se repetir, veja o console do bot."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(texto, ephemeral=True)
        else:
            await interaction.response.send_message(texto, ephemeral=True)
    except Exception:
        pass

def checar_hierarquia(interaction, alvo):
    """Devolve o texto do erro se NÃO puder punir esse alvo (ou None se puder)."""
    guild, autor = interaction.guild, interaction.user
    if alvo.id == autor.id:
        return "Você não pode punir a si mesmo."
    if alvo.id == bot.user.id:
        return "Eu não vou me punir. 😅"
    if alvo.id == guild.owner_id:
        return "Ninguém pode punir o dono do servidor."
    if isinstance(alvo, discord.Member):
        if autor.id != guild.owner_id and alvo.top_role >= autor.top_role:
            return "Esse membro tem cargo igual ou maior que o seu."
        if alvo.top_role >= guild.me.top_role:
            return "O cargo desse membro é igual ou maior que o do bot. Suba o cargo do bot na lista de cargos."
    return None

# ==================== COMANDOS DE PUNIÇÃO ====================
@comando(name="mute", description="Silencia um membro (timeout) por alguns minutos.")
@app_commands.describe(membro="Quem será silenciado", tempo_minutos="Duração em minutos (máximo 40320 = 28 dias)", motivo="Motivo da punição")
@exige(moderate_members=True)
async def mute_slash(interaction: discord.Interaction, membro: discord.Member,
                     tempo_minutos: app_commands.Range[int, 1, 40320], motivo: str = "Sem motivo especificado"):
    await interaction.response.defer(ephemeral=True)
    erro = checar_hierarquia(interaction, membro)
    if erro:
        await interaction.followup.send(f"❌ {erro}")
        return
    ok = await aplicar_mute(interaction.guild, membro, interaction.user, tempo_minutos, motivo, "Mute (Comando)")
    if ok:
        await interaction.followup.send(f"✅ {membro.mention} foi silenciado por {formatar_duracao(tempo_minutos)}.")
    else:
        await interaction.followup.send("❌ Não foi possível silenciar. Verifique se o meu cargo está acima do cargo desse usuário.")

@comando(name="unmute", description="Remove o silenciamento de um membro.")
@app_commands.describe(membro="Quem terá o silenciamento removido")
@exige(moderate_members=True)
async def unmute_slash(interaction: discord.Interaction, membro: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not membro.is_timed_out():
        await interaction.followup.send("ℹ️ Esse membro não está silenciado.")
        return
    try:
        await membro.timeout(None, reason=f"{interaction.user.name} | Unmute")
    except discord.HTTPException:
        await interaction.followup.send("❌ Não foi possível remover o silenciamento.")
        return
    await log_punicao(interaction.guild, membro, interaction.user, "Desmutado (Comando)", "Silenciamento removido por comando.", tipo="mute")
    await interaction.followup.send(f"✅ {membro.mention} não está mais silenciado.")

@comando(name="kick", description="Expulsa um membro do servidor.")
@app_commands.describe(membro="Quem será expulso", motivo="Motivo da punição")
@exige(kick_members=True)
async def kick_slash(interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo especificado"):
    await interaction.response.defer(ephemeral=True)
    erro = checar_hierarquia(interaction, membro)
    if erro:
        await interaction.followup.send(f"❌ {erro}")
        return
    ok = await executar_expulsao(interaction.guild, membro, interaction.user, motivo, "Expulsão (Comando)")
    if ok:
        await interaction.followup.send(f"👢 {membro.mention} foi expulso.")
        await contar_acao_staff(interaction.guild, interaction.user, "kick", membro.id)
    else:
        await interaction.followup.send("❌ Erro ao expulsar. Verifique se o meu cargo é superior ao da pessoa.")

@comando(name="ban", description="Bane um usuário do servidor permanentemente.")
@app_commands.describe(usuario="Quem será banido", motivo="Motivo da punição", apagar_horas="Apagar as mensagens das últimas X horas (0 a 168)")
@exige(ban_members=True)
async def ban_slash(interaction: discord.Interaction, usuario: discord.User, motivo: str = "Sem motivo especificado",
                    apagar_horas: app_commands.Range[int, 0, 168] = 0):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    alvo = guild.get_member(usuario.id) or usuario
    erro = checar_hierarquia(interaction, alvo)
    if erro:
        await interaction.followup.send(f"❌ {erro}")
        return
    ok = await executar_banimento(guild, alvo, interaction.user, motivo, "Banimento (Comando)", apagar_segundos=apagar_horas * 3600)
    if ok:
        await interaction.followup.send(f"🔨 {usuario.mention} foi banido com sucesso.")
        await contar_acao_staff(guild, interaction.user, "ban", usuario.id)
    else:
        await interaction.followup.send("❌ Erro ao banir. Verifique se o meu cargo é superior ao da pessoa que você está tentando banir.")

@comando(name="unban", description="Remove o banimento de um usuário pelo ID.")
@app_commands.describe(usuario_id="ID do usuário banido", motivo="Motivo do desbanimento")
@exige(ban_members=True)
async def unban_slash(interaction: discord.Interaction, usuario_id: str, motivo: str = "Sem motivo especificado"):
    await interaction.response.defer(ephemeral=True)
    try:
        uid = int(usuario_id.strip().strip("<@!>"))
    except ValueError:
        await interaction.followup.send("❌ ID inválido. Cole só os números do ID do usuário.")
        return
    try:
        await interaction.guild.unban(discord.Object(id=uid), reason=f"{interaction.user.name} | {motivo}"[:480])
    except discord.NotFound:
        await interaction.followup.send("ℹ️ Esse usuário não está banido.")
        return
    except discord.HTTPException:
        await interaction.followup.send("❌ Não consegui desbanir. Confira se o bot tem a permissão Banir Membros.")
        return
    alvo = await buscar_usuario(uid)
    await log_punicao(interaction.guild, alvo, interaction.user, "Desbanimento (Comando)", motivo)
    await interaction.followup.send(f"✅ O usuário `{uid}` foi desbanido.")

@comando(name="warn", description="Dá um aviso (warn) a um membro. Acumulou warns, o bot pune sozinho.")
@app_commands.describe(membro="Quem recebe o warn", motivo="Motivo do warn")
@exige(moderate_members=True)
async def warn_slash(interaction: discord.Interaction, membro: discord.Member, motivo: str):
    await interaction.response.defer(ephemeral=True)
    erro = checar_hierarquia(interaction, membro)
    if erro:
        await interaction.followup.send(f"❌ {erro}")
        return
    guild = interaction.guild
    await registrar_warn(guild, membro.id, interaction.user.id, motivo)
    total = len(warns_ativos(membro.id))
    try:
        await membro.send(f"⚠️ **{NOME_SERVIDOR}** — você recebeu um aviso (warn #{total}).\n**Motivo:** {motivo}")
    except Exception:
        pass
    await log_punicao(guild, membro, interaction.user, f"Warn #{total}", motivo, tipo="mute")
    extra = await escalar_warn(guild, membro, total)
    await interaction.followup.send(f"⚠️ {membro.mention} recebeu o warn **#{total}**.{extra}")

@comando(name="warns", description="Mostra os warns ativos de um membro.")
@app_commands.describe(membro="De quem você quer ver os warns")
@exige(moderate_members=True)
async def warns_slash(interaction: discord.Interaction, membro: discord.Member):
    lista = warns_ativos(membro.id)
    if not lista:
        await interaction.response.send_message(f"✅ {membro.mention} não tem warns ativos.", ephemeral=True)
        return
    linhas = [f"**#{i}** — <t:{w['quando']}:d> por <@{w['staff']}>: {w['motivo'][:100]}" for i, w in enumerate(lista[:15], 1)]
    await interaction.response.send_message(
        f"⚠️ **{len(lista)} warn(s) ativo(s)** de {membro.mention} (valem {WARN_VALIDADE_DIAS} dias):\n" + "\n".join(linhas),
        ephemeral=True
    )

@comando(name="limpar_warns", description="Apaga todos os warns de um membro.")
@app_commands.describe(membro="Quem terá os warns apagados")
@exige(administrator=True)
async def limpar_warns_slash(interaction: discord.Interaction, membro: discord.Member):
    await interaction.response.defer(ephemeral=True)
    n = await limpar_warns(membro.id)
    await interaction.followup.send(f"🧹 {n} warn(s) de {membro.mention} apagado(s).")

# ==================== COMANDOS DE SEGURANÇA / MODERAÇÃO ====================
@comando(name="raid", description="Liga, desliga ou consulta o modo anti-raid (barra novas entradas).")
@app_commands.describe(acao="O que fazer com o modo anti-raid")
@app_commands.choices(acao=[
    app_commands.Choice(name="Ligar", value="ligar"),
    app_commands.Choice(name="Desligar", value="desligar"),
    app_commands.Choice(name="Status", value="status"),
])
@exige(administrator=True)
async def raid_slash(interaction: discord.Interaction, acao: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if acao.value == "ligar":
        if await ativar_raid(guild, "Ligado manualmente", por=interaction.user):
            await interaction.followup.send(f"🚨 Modo anti-raid **ligado** por {RAID_DURACAO_MIN} min. Quem tentar entrar será barrado.")
        else:
            await interaction.followup.send(f"🚨 O modo já estava ligado; renovei por mais {RAID_DURACAO_MIN} min.")
    elif acao.value == "desligar":
        if raid_ativo() and await desativar_raid(guild, por=interaction.user):
            await interaction.followup.send("✅ Modo anti-raid **desligado**.")
        else:
            await interaction.followup.send("ℹ️ O modo anti-raid não estava ligado.")
    else:
        if raid_ativo():
            restam = int((bot.raid_ate - time.monotonic()) // 60) + 1
            await interaction.followup.send(f"🔴 Modo anti-raid **ATIVO** — restam ~{restam} min • {bot.raid_expulsos} conta(s) barrada(s).")
        else:
            await interaction.followup.send(f"🟢 Modo anti-raid desligado. O bot liga sozinho com {RAID_ENTRADAS} entradas em {RAID_JANELA_SEG}s.")

@comando(name="lockdown", description="Trava o chat (um canal ou o servidor inteiro) para os membros.")
@app_commands.describe(canal="Canal para travar (vazio = todos os canais de texto)", motivo="Motivo do lockdown")
@exige(administrator=True)
async def lockdown_slash(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None, motivo: str = "Lockdown manual"):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    canais = [canal] if canal else list(guild.text_channels)
    n = await travar_canais(guild, canais, f"{interaction.user.name} | {motivo}")
    await interaction.followup.send(
        f"🔒 {n} canal(is) travado(s). Use `/unlock` para liberar.\n"
        f"-# O bot guarda o estado anterior na memória: se ele reiniciar durante o lockdown, destrave manualmente."
    )
    await enviar_alerta(guild, f"🔒 {NOME_SERVIDOR} - Lockdown Ativado",
                        f"👮 **Por:** {interaction.user.mention}\n📄 **Motivo:** {motivo}\n📍 **Alcance:** {canal.mention if canal else 'servidor inteiro'}")

@comando(name="unlock", description="Libera o chat travado pelo /lockdown.")
@app_commands.describe(canal="Canal para liberar (vazio = todos os travados)")
@exige(administrator=True)
async def unlock_slash(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not bot.lock_estado:
        await interaction.followup.send("ℹ️ Não há nenhum lockdown registrado na memória do bot.")
        return
    n = await destravar_canais(guild, [canal] if canal else None)
    await interaction.followup.send(f"🔓 {n} canal(is) liberado(s).")
    await enviar_alerta(guild, f"🔓 {NOME_SERVIDOR} - Lockdown Encerrado", f"👮 **Por:** {interaction.user.mention}\n📍 **Alcance:** {canal.mention if canal else 'tudo que estava travado'}")

@comando(name="limpar", description="Apaga mensagens do canal atual (opcionalmente só de um membro).")
@app_commands.describe(quantidade="Quantas mensagens verificar (1 a 100)", membro="Apagar só as mensagens deste membro (opcional)")
@exige(manage_messages=True)
async def limpar_slash(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100], membro: Optional[discord.Member] = None):
    await interaction.response.defer(ephemeral=True)
    kwargs = {"limit": quantidade}
    if membro:
        kwargs["check"] = lambda m: m.author.id == membro.id
    try:
        apagadas = await interaction.channel.purge(**kwargs)
    except discord.HTTPException:
        await interaction.followup.send("❌ Não consegui apagar. Confira se o bot tem Gerenciar Mensagens neste canal.")
        return
    await interaction.followup.send(f"🧹 {len(apagadas)} mensagem(ns) apagada(s).")

@comando(name="slowmode", description="Define o modo lento de um canal (0 desliga).")
@app_commands.describe(segundos="Segundos entre mensagens (0 a 21600)", canal="Canal (vazio = o atual)")
@exige(manage_channels=True)
async def slowmode_slash(interaction: discord.Interaction, segundos: app_commands.Range[int, 0, 21600], canal: Optional[discord.TextChannel] = None):
    await interaction.response.defer(ephemeral=True)
    alvo = canal or interaction.channel
    try:
        await alvo.edit(slowmode_delay=segundos, reason=f"{interaction.user.name} | /slowmode")
    except discord.HTTPException:
        await interaction.followup.send("❌ Não consegui mudar o modo lento desse canal.")
        return
    await interaction.followup.send(f"🐢 Modo lento de {alvo.mention}: **{segundos}s**." if segundos else f"✅ Modo lento de {alvo.mention} desligado.")

@comando(name="status", description="Mostra o estado de todas as proteções e módulos do bot.")
@exige(moderate_members=True)
async def status_slash(interaction: discord.Interaction):
    guild = interaction.guild
    if raid_ativo():
        raid = f"🔴 ATIVO — restam ~{int((bot.raid_ate - time.monotonic()) // 60) + 1} min • {bot.raid_expulsos} barrada(s)"
    else:
        raid = f"🟢 Desligado • liga sozinho com {RAID_ENTRADAS} entradas em {RAID_JANELA_SEG}s"
    travados = len({c for c, _ in bot.lock_estado})
    abertos = sum(1 for c in guild.text_channels if ler_ticket(c))
    logs_ok = sum(1 for tipo in CANAIS_LOG if achar_canal_log(guild, tipo))
    sorteios_ativos = sum(1 for s in bot.banco.dados["sorteios"].values() if not s.get("encerrado"))
    xp_estado = "ligado" if XP_ATIVADO else "desligado"
    banco_estado = "✅ carregado" if bot.banco_carregado else "⚠️ NÃO carregou"
    staff_automod = "sim" if STAFF_ISENTA_DO_AUTOMOD else "não"
    staff_tudo = "sim" if STAFF_ISENTA_DE_TUDO else "não"

    embed = discord.Embed(title=f"🛡️ {NOME_SERVIDOR} - Status", color=COR, timestamp=discord.utils.utcnow())
    embed.add_field(name="Anti-Raid", value=f"{raid}\nAção: {RAID_ACAO} • conta mínima: {IDADE_MINIMA_CONTA_DIAS or 'sem limite'} dia(s)", inline=False)
    embed.add_field(
        name="Anti-Spam",
        value=(f"{SPAM_MENSAGENS} msgs/{SPAM_JANELA_SEG}s • {SPAM_DUPLICADAS} repetidas • {SPAM_CANAIS} canais • "
               f"{MAX_MENCOES} menções\n🔇 Mute por spam: **{formatar_duracao(MUTE_SPAM_MIN)}** • "
               f"outros: mute a partir de {ESCADA_PONTOS[-1][0]} ponto(s)"),
        inline=False
    )
    embed.add_field(
        name="Anti-Nuke",
        value=(f"Ação: {NUKE_ACAO} • {len(NUKE_REGRAS)} regras\nBots barrados: {'sim' if BLOQUEAR_BOTS_NAO_AUTORIZADOS else 'não'} • "
               f"Anti-escalada: {'sim' if PROTEGER_CARGOS_PERIGOSOS else 'não'} • Whitelist: {len(WHITELIST_IDS)}"),
        inline=False
    )
    embed.add_field(
        name="Filtros",
        value=(f"Golpes: {len(TERMOS_BAN)} termos + links falsos → {GOLPE_ACAO} • Palavrões: {len(PALAVROES)}\n"
               f"Imagens: {len(HASHES_FIXOS)} fixas + {len(bot.imagens_registradas)} por comando • "
               f"só IDÊNTICAS → **{IMAGEM_ACAO}**"),
        inline=False
    )
    embed.add_field(name="Staff", value=f"Isenta do automod: {staff_automod} • isenta de golpe/imagem: {staff_tudo}", inline=False)
    embed.add_field(name="Logs", value=f"{logs_ok}/{len(CANAIS_LOG)} canais encontrados (`/setup` cria os que faltam)", inline=False)
    embed.add_field(name="Tickets", value=f"{len(setores_do_painel())} setor(es) no painel • {abertos} aberto(s)", inline=True)
    embed.add_field(name="Níveis", value=f"{xp_estado} • {len(bot.banco.dados['xp'])} membro(s)", inline=True)
    embed.add_field(name="Sorteios", value=f"{sorteios_ativos} em andamento", inline=True)
    embed.add_field(name="Banco de dados", value=banco_estado, inline=True)
    embed.add_field(name="Lockdown", value=f"🔒 {travados} canal(is) travado(s)" if travados else "🔓 Nenhum", inline=True)
    embed.add_field(name="Warns", value=f"{sum(len(warns_ativos(u)) for u in list(bot.warns))} ativo(s)", inline=True)
    embed.add_field(name="Ping", value=f"{round(bot.latency * 1000)} ms", inline=True)
    rodape(embed, guild)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== COMANDOS DE IMAGENS BLOQUEADAS (só imagem IDÊNTICA) ====================
@comando(name="bloquear_imagem", description="Bloqueia uma imagem: quem enviar ESSA mesma imagem será punido (idêntica).")
@app_commands.describe(imagem="A imagem que deve ser bloqueada", nome="Um nome para você identificar depois (opcional)")
@exige(administrator=True)
async def bloquear_imagem_slash(interaction: discord.Interaction, imagem: discord.Attachment, nome: Optional[str] = None):
    await interaction.response.defer(ephemeral=True)
    tipo = (imagem.content_type or "").lower()
    if not (tipo.startswith("image/") or imagem.filename.lower().endswith(EXT_IMAGEM)):
        await interaction.followup.send("❌ Esse arquivo não parece ser uma imagem.")
        return
    if imagem.size > LIMITE_DOWNLOAD:
        await interaction.followup.send("❌ Essa imagem é grande demais.")
        return
    dados = await imagem.read()
    _, texto = await registrar_imagem(interaction.guild, interaction.user, dados, nome)
    await interaction.followup.send(texto)

@comando(name="desbloquear_imagem", description="Tira uma imagem da lista de bloqueadas.")
@app_commands.describe(nome="Escolha a imagem na lista")
@exige(administrator=True)
async def desbloquear_imagem_slash(interaction: discord.Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    _, texto = await remover_imagem(nome)
    await interaction.followup.send(texto)

@desbloquear_imagem_slash.autocomplete("nome")
async def autocompletar_imagens(interaction: discord.Interaction, atual: str):
    if not interaction.permissions.administrator:
        return []
    atual = atual.lower()
    nomes = sorted({e["nome"] for e in bot.imagens_registradas.values() if atual in e["nome"].lower()})
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in nomes[:25]]

@comando(name="listar_imagens", description="Mostra as imagens bloqueadas pelo comando /bloquear_imagem.")
@exige(administrator=True)
async def listar_imagens_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    entradas = sorted(bot.imagens_registradas.values(), key=lambda e: e["quando"])
    linhas = [f"• **{e['nome']}** — <@{e['por']}> — <t:{e['quando']}:d>" for e in entradas]
    texto = (
        f"🚫 **Imagens bloqueadas por comando:** {len(entradas)}/{LIMITE_IMAGENS_REGISTRADAS}\n"
        f"📌 **Hashes fixos no código:** {len(HASHES_FIXOS)}\n"
        f"⚙️ **Só imagem IDÊNTICA é punida** → {IMAGEM_ACAO}\n\n"
        + ("\n".join(linhas) if linhas else "_Nenhuma ainda. Use /bloquear_imagem._")
    )
    if len(texto) > 1900:
        arquivo = discord.File(BytesIO(texto.encode("utf-8")), filename="imagens_bloqueadas.txt")
        await interaction.followup.send("A lista é grande, segue em arquivo:", file=arquivo)
    else:
        await interaction.followup.send(texto)

@comando(name="testar_imagem", description="Mostra os hashes de uma imagem e se o bot a puniria (não bloqueia nada).")
@app_commands.describe(imagem="A imagem que você quer testar")
@exige(administrator=True)
async def testar_imagem_slash(interaction: discord.Interaction, imagem: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    dados = await imagem.read()
    try:
        frames, achado, menor = await asyncio.get_running_loop().run_in_executor(None, avaliar_imagem, dados)
    except Exception as e:
        await interaction.followup.send(f"❌ Não consegui ler essa imagem: `{type(e).__name__}`")
        return
    if not frames:
        await interaction.followup.send("❌ Não consegui calcular os hashes dessa imagem.")
        return

    h = frames[0]
    texto = (
        "**Hashes desta imagem** (para bloquear ela, use `/bloquear_imagem`):\n"
        f"```\naverage: {h['average']}\nphash:   {h['phash']}\ndhash:   {h['dhash']}\n```"
    )
    if achado:
        origem, detalhe = achado
        texto += f"\n🚫 **É IDÊNTICA a uma imagem bloqueada** — `{origem}` (`{detalhe}`). Quem enviar isso {texto_acao_imagem()}."
    else:
        texto += "\n✅ **Não é igual a nenhuma imagem bloqueada** — o bot não faria nada."
        if menor:
            texto += f"\n-# A mais próxima ficou a {menor[0]} de distância de `{menor[1]}`, mas só imagem IDÊNTICA (distância 0) conta."
        elif not (HASHES_FIXOS or HASHES_REGISTRADOS):
            texto += "\n-# Ainda não há nenhuma imagem bloqueada."
    await interaction.followup.send(texto)

# ==================== PAINEL DE VERIFICAÇÃO ====================
@comando(name="painel_verificacao", description="Envia o painel com o botão de verificação neste canal.")
@exige(administrator=True)
async def painel_verificacao_slash(interaction: discord.Interaction):
    if not CARGO_VERIFICADO or interaction.guild.get_role(CARGO_VERIFICADO) is None:
        await interaction.response.send_message("❌ Preencha CARGO_VERIFICADO no topo do arquivo com o ID do cargo de verificado.", ephemeral=True)
        return
    embed = discord.Embed(
        title=f"✅ VERIFICAÇÃO - {NOME_SERVIDOR}",
        description="Clique no botão abaixo para se verificar e liberar o acesso ao servidor.",
        color=COR
    )
    await interaction.channel.send(embed=embed, view=ViewVerificar())
    await interaction.response.send_message("✅ Painel de verificação enviado!", ephemeral=True)

# ==================== /SETUP (cria os canais de logs, automod e tickets) ====================
async def criar_canal_publico(guild, nome, topico):
    """Canal que todo mundo lê, mas só o bot escreve (boas-vindas, sugestões)."""
    permissoes = {
        guild.default_role: discord.PermissionOverwrite(send_messages=False, create_public_threads=False),
        guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True, attach_files=True, add_reactions=True),
    }
    return await guild.create_text_channel(nome, overwrites=permissoes, topic=topico, reason="Canal criado pelo /setup")

@comando(name="setup", description="Cria os canais de logs, automod e tickets do bot (privados, só a staff vê).")
@app_commands.describe(publicos="Também cria #boas-vindas e #sugestoes (públicos, só leitura)")
@exige(administrator=True)
async def setup_slash(interaction: discord.Interaction, publicos: bool = False):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    criados, achados, falhas = [], [], []
    for tipo, (_, nome, _, _) in CANAIS_LOG.items():
        bot.falha_log.pop(tipo, None)   # no /setup sempre tenta de novo
        antes = achar_canal_log(guild, tipo)
        canal = await obter_canal_log(guild, tipo, criar=True)
        if canal is None:
            falhas.append(f"`{nome}`")
        elif antes is None:
            criados.append(canal.mention)
        else:
            achados.append(canal.mention)
    if publicos:
        extras = (
            ("boas-vindas", "Mensagens de boas-vindas aos novos membros.", ("boas-vindas", "bem-vindo")),
            ("sugestoes", "Sugestões dos membros (use /sugestao).", ("sugest",)),
        )
        for nome, topico, busca in extras:
            existente = achar_canal_por_nome(guild, busca, publico=True)
            if existente:
                achados.append(existente.mention)
                continue
            try:
                criados.append((await criar_canal_publico(guild, nome, topico)).mention)
            except discord.HTTPException:
                falhas.append(f"`{nome}`")
    partes = []
    if criados:
        partes.append("✅ **Criei:** " + ", ".join(criados))
    if achados:
        partes.append("📌 **Já existiam (vou usar esses):** " + ", ".join(achados))
    if falhas:
        partes.append("⚠️ **Não consegui criar:** " + ", ".join(falhas) + " — confira se o bot tem a permissão Gerenciar Canais.")
    partes.append("🎫 Os tickets nascem na categoria **TICKETS** (ou na que você colocou nos IDs do topo do arquivo).")
    await interaction.followup.send("\n".join(partes))

# ==================== INFORMAÇÕES ====================
@comando(name="avatar", description="Mostra a foto de perfil de alguém.")
@app_commands.describe(membro="De quem (vazio = você)")
async def avatar_slash(interaction: discord.Interaction, membro: Optional[discord.Member] = None):
    alvo = membro or interaction.user
    embed = discord.Embed(title=f"🖼️ Avatar de {alvo.display_name}", color=COR)
    embed.set_image(url=alvo.display_avatar.replace(size=1024).url)
    await interaction.response.send_message(embed=embed)

@comando(name="userinfo", description="Mostra informações de um membro.")
@app_commands.describe(membro="De quem (vazio = você)")
async def userinfo_slash(interaction: discord.Interaction, membro: Optional[discord.Member] = None):
    alvo = membro or interaction.user
    cor = alvo.color if alvo.color.value else discord.Colour(COR)
    embed = discord.Embed(title=f"👤 {alvo.display_name}", color=cor)
    embed.set_thumbnail(url=alvo.display_avatar.url)
    embed.add_field(name="🆔 ID", value=f"`{alvo.id}`", inline=True)
    embed.add_field(name="📅 Conta criada", value=discord.utils.format_dt(alvo.created_at, "R"), inline=True)
    if alvo.joined_at:
        embed.add_field(name="📥 Entrou", value=discord.utils.format_dt(alvo.joined_at, "R"), inline=True)
    cargos = [r.mention for r in reversed(alvo.roles) if not r.is_default()][:15]
    embed.add_field(name="🏷️ Cargos", value=" ".join(cargos) or "nenhum", inline=False)
    if alvo.premium_since:
        embed.add_field(name="💎 Booster desde", value=discord.utils.format_dt(alvo.premium_since, "R"), inline=True)
    if alvo.is_timed_out():
        embed.add_field(name="🔇 Silenciado até", value=discord.utils.format_dt(alvo.timed_out_until, "f"), inline=True)
    registro = bot.banco.dados["xp"].get(str(alvo.id))
    if registro:
        embed.add_field(name="⭐ Nível", value=f"{calcular_nivel(registro[0])[0]} ({registro[0]} XP)", inline=True)
    if eh_staff(interaction.user):
        embed.add_field(name="⚠️ Warns ativos", value=str(len(warns_ativos(alvo.id))), inline=True)
    await interaction.response.send_message(embed=embed)

@comando(name="serverinfo", description="Mostra informações do servidor.")
async def serverinfo_slash(interaction: discord.Interaction):
    g = interaction.guild
    humanos = sum(1 for m in g.members if not m.bot)
    embed = discord.Embed(title=f"🏰 {g.name}", color=COR)
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="👑 Dono", value=f"<@{g.owner_id}>", inline=True)
    embed.add_field(name="📅 Criado", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
    embed.add_field(name="👥 Membros", value=f"{g.member_count} ({humanos} pessoas • {len(g.members) - humanos} bots)", inline=True)
    embed.add_field(name="💬 Canais", value=f"{len(g.text_channels)} de texto • {len(g.voice_channels)} de voz • {len(g.categories)} categorias", inline=False)
    embed.add_field(name="🏷️ Cargos", value=str(len(g.roles)), inline=True)
    embed.add_field(name="😀 Emojis", value=str(len(g.emojis)), inline=True)
    embed.add_field(name="💎 Impulsos", value=f"{g.premium_subscription_count} (nível {g.premium_tier})", inline=True)
    await interaction.response.send_message(embed=embed)

# ==================== MENSAGENS DO BOT (STAFF) ====================
@comando(name="say", description="Faz o bot enviar uma mensagem em um canal.")
@app_commands.describe(mensagem="Texto (use \\n para pular linha)", canal="Canal (vazio = este)")
@exige(manage_messages=True)
async def say_slash(interaction: discord.Interaction, mensagem: app_commands.Range[str, 1, 1900], canal: Optional[discord.TextChannel] = None):
    destino = canal or interaction.channel
    try:
        await destino.send(mensagem.replace("\\n", "\n"), allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        await interaction.response.send_message(f"❌ Não consegui enviar em {destino.mention}. Confira as permissões do bot.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Mensagem enviada em {destino.mention}.", ephemeral=True)

@comando(name="embed", description="Envia um embed personalizado em um canal.")
@app_commands.describe(
    titulo="Título", descricao="Texto (use \\n para pular linha)",
    cor="Cor em hexadecimal, ex.: #950606 (vazio = cor padrão)", imagem="Link de uma imagem grande (opcional)",
    canal="Canal (vazio = este)"
)
@exige(manage_messages=True)
async def embed_slash(interaction: discord.Interaction, titulo: app_commands.Range[str, 1, 250],
                      descricao: app_commands.Range[str, 1, 3500], cor: Optional[str] = None,
                      imagem: Optional[str] = None, canal: Optional[discord.TextChannel] = None):
    valor_cor = COR
    if cor:
        try:
            valor_cor = int(cor.strip().lstrip("#"), 16)
        except ValueError:
            valor_cor = -1
        if not 0 <= valor_cor <= 0xFFFFFF:
            await interaction.response.send_message("❌ Cor inválida. Use hexadecimal, tipo `#950606`.", ephemeral=True)
            return
    embed = discord.Embed(title=titulo, description=descricao.replace("\\n", "\n"), color=valor_cor)
    if imagem and imagem.lower().startswith(("http://", "https://")):
        embed.set_image(url=imagem)
    destino = canal or interaction.channel
    try:
        await destino.send(embed=embed)
    except discord.HTTPException:
        await interaction.response.send_message(f"❌ Não consegui enviar em {destino.mention}. Confira as permissões do bot.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Embed enviado em {destino.mention}.", ephemeral=True)

# ==================== INÍCIO ====================
if __name__ == "__main__":
    if not GUILD_ID:
        raise SystemExit("❌ Preencha o GUILD_ID (ID do servidor K7NG) no topo do arquivo antes de ligar o bot.")
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise SystemExit("❌ Variável de ambiente TOKEN não encontrada (coloque o token do bot nela).")
    Thread(target=run_server, daemon=True).start()
    bot.run(TOKEN)
