import os
import re
import time
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
from PIL import Image, ImageFile

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

# Canais de log (o bot só registra punições e alertas de segurança, mais nada)
CANAL_BAN = 1555001131892211773     # ban, unban, kick + alertas de segurança (raid, nuke, bot barrado, lockdown...)
CANAL_MUTE = 1566956599141204228    # mute, unmute e warn

# Tudo abaixo é OPCIONAL (0 = o bot se vira sozinho)
CARGO_STAFF = 0                 # cargo da staff. 0 = só conta como staff quem tem permissão de moderação
CATEGORIA_TICKETS = 0           # categoria onde os tickets nascem. 0 = sem categoria
CARGO_VERIFICADO = 0            # cargo dado no botão "Verificar". 0 = verificação desligada
CARGOS_TRAVAR = []              # cargos de membro que o /lockdown também trava (além do @everyone). Ex.: [123, 456]

# Pessoas de confiança total (além do dono do servidor): o anti-nuke nunca pune essas contas.
WHITELIST_IDS = set()           # exemplo: {123456789012345678, 987654321098765432}
BOTS_PERMITIDOS = set()         # ids de bots que podem entrar mesmo adicionados por quem não é de confiança

SAIR_DE_OUTROS_SERVIDORES = True   # bot privado: sai sozinho de qualquer servidor que não seja o K7NG
STAFF_ISENTA_DO_AUTOMOD = True     # staff não leva punição de spam/link/palavrão (golpe e imagem proibida valem para todos)
IMAGEM_PAINEL_TICKETS = ""         # (opcional) link de um banner para o painel de tickets

NOME_CANAL_BAN = "logs-ban"                  # só usado se o CANAL_BAN acima não for encontrado (o bot cria um canal privado)
NOME_CANAL_MUTE = "logs-mute"                # idem para o CANAL_MUTE
NOME_CANAL_REGISTRO = "imagens-bloqueadas"   # canal privado onde o bot guarda a lista do /bloquear_imagem
NOME_CANAL_WARNS = "warns-registro"          # canal privado onde o bot guarda os warns
TOPICO_REGISTRO = "Lista de imagens bloqueadas do bot. NÃO apague as mensagens daqui (para desbloquear use /desbloquear_imagem)."
TOPICO_WARNS = "Registro de warns do bot. NÃO apague as mensagens daqui (para remover use /limpar_warns)."
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

# Cada infração soma pontos. Os pontos valem por JANELA_REINCIDENCIA_MIN minutos.
PONTOS = {
    "convite": 5, "mencoes": 5, "multicanal": 5,
    "flood": 3, "repetida": 3,
    "palavrao": 1, "link_novato": 1, "formatacao": 1,
}
JANELA_REINCIDENCIA_MIN = 30
# (pontos acumulados, minutos de mute). 1-2 pontos = só aviso no canal.
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

PALAVROES = [
    "fdp", "filho da puta", "filha da puta", "caralho", "krl", "bosta",
    "escroto", "escrota", "merda", "arrombado", "arrombada", "viado",
    "corno", "corna", "desgracado", "desgracada", "vagabundo", "vagabunda",
    "porra", "buceta", "cacete", "puta", "puto", "putaria", "putinha",
    "cuzao", "cuzoes", "pica", "rola", "xoxota", "vadia", "foder",
    "foda se", "tnc", "tomar no cu", "vsf", "vtnc", "pqp"
]

IMAGENS_BLOQUEADAS = [
    '9977339a644d9a62', '936c6c4e946cd966', '9748a8dcbd4a2579',
    'c48ff019712fe2c6', '91ac6db293ab09a6', 'c1e1eb965c5e5cd0', 'f5de4a08bdbd5aa5', '956a6e944ac9a6c9', '931e6ae394d3486f'
]

# Quão "parecida" a imagem precisa ser para levar ban. É a distância entre os hashes (0 a 64):
#   0 = idêntica | menor = mais rígido | maior = pega mais variações (recorte, compressão, redimensionada),
#   mas aumenta o risco de banir imagem inocente.
# Use o comando /testar_imagem para ver a distância real de uma imagem antes de mexer nisso.
LIMITE_HASH = 8
LIMITE_IMAGENS_REGISTRADAS = 150     # máximo de imagens bloqueadas por comando

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

# ==================== ANÁLISE DE IMAGENS (HASH) ====================
# Cada item da lista: (hash_em_texto, ImageHash, algoritmo_exigido, origem)
#   - Hashes do código (IMAGENS_BLOQUEADAS): não dá pra saber de qual tipo cada um é, então são comparados
#     com os 3 tipos (algoritmo_exigido = None).
#   - Imagens bloqueadas pelo /bloquear_imagem: o tipo de cada hash é conhecido, então só comparam com o MESMO tipo.
ALGORITMOS = ("average", "phash", "dhash")

HASHES_FIXOS = []
for _hex in IMAGENS_BLOQUEADAS:
    try:
        _h = imagehash.hex_to_hash(_hex)
        if _h.hash.shape != (8, 8):
            raise ValueError("o hash precisa ter 16 caracteres (tamanho padrão 8x8)")
        HASHES_FIXOS.append((_hex, _h, None, "lista"))
    except Exception as _erro:
        print(f"[Aviso] Hash ignorado ({_hex}): {_erro}")

HASHES_BLOQUEADOS = list(HASHES_FIXOS)   # lista em uso: fixos + os do /bloquear_imagem

def reconstruir_hashes(registradas):
    """Junta a lista do código com as imagens bloqueadas por comando. Troca a lista de uma vez (seguro com threads)."""
    global HASHES_BLOQUEADOS
    novos = list(HASHES_FIXOS)
    for e in registradas:
        for alg in ALGORITMOS:
            novos.append((e["hashes"][alg], imagehash.hex_to_hash(e["hashes"][alg]), alg, e["nome"]))
    HASHES_BLOQUEADOS = novos

def avaliar_imagem(dados):
    """
    Roda em OUTRA THREAD (não trava o bot). Calcula os hashes da imagem (e de alguns frames, se for
    GIF/WEBP animado) e compara com a lista bloqueada.
    Retorna (frames, melhor, menores):
      melhor  = (distancia, algoritmo, hash_bloqueado, origem) da imagem bloqueada mais próxima
      menores = menor distância encontrada em cada algoritmo
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

    alvos = HASHES_BLOQUEADOS   # "foto" da lista neste momento
    melhor = None
    menores = {alg: None for alg in ALGORITMOS}
    for hashes in frames:
        for algoritmo, h in hashes.items():
            for hex_alvo, alvo, alg_exigido, origem in alvos:
                if alg_exigido and alg_exigido != algoritmo:
                    continue
                dist = int(h - alvo)
                if menores[algoritmo] is None or dist < menores[algoritmo]:
                    menores[algoritmo] = dist
                if melhor is None or dist < melhor[0]:
                    melhor = (dist, algoritmo, hex_alvo, origem)
    return frames, melhor, menores

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
        self.canais_log = {}              # "ban"/"mute" -> id do canal de log em uso

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

    async def setup_hook(self):
        self.sessao_http = aiohttp.ClientSession()
        self.trava_registro = asyncio.Lock()
        self.add_view(ViewTickets())
        self.add_view(ViewFechar())
        self.add_view(ViewVerificar())
        manutencao.start()
        try:
            await self.tree.sync(guild=GUILD_OBJ)   # comandos SÓ no K7NG
            await self.tree.sync()                  # limpa os comandos globais da versão antiga (nada vaza para outros servidores)
        except discord.HTTPException as e:
            print(f"[ERRO] Não consegui sincronizar os comandos (o bot foi convidado com o escopo 'applications.commands'?): {e}")

    async def close(self):
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
    return bool(CARGO_STAFF and membro.get_role(CARGO_STAFF))

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

def raid_ativo():
    return time.monotonic() < bot.raid_ate

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

async def apagar_mensagens(guild, refs):
    """Apaga uma lista de (id_do_canal, id_da_mensagem), em lote quando dá."""
    por_canal = defaultdict(list)
    for canal_id, msg_id in refs:
        por_canal[canal_id].append(msg_id)
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

# ==================== CANAIS PRIVADOS DO BOT ====================
async def obter_canal_privado(guild, nome, topico, criar=False):
    """Acha (ou cria, se criar=True) um canal privado: só a staff lê, só o bot escreve."""
    canal = discord.utils.get(guild.text_channels, name=nome)
    if canal or not criar:
        return canal

    cargo_staff = guild.get_role(CARGO_STAFF) if CARGO_STAFF else None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True
        ),
    }
    if cargo_staff:
        overwrites[cargo_staff] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
    ref = guild.get_channel(CANAL_BAN) if CANAL_BAN else None
    return await guild.create_text_channel(
        nome,
        overwrites=overwrites,
        category=getattr(ref, "category", None),
        topic=topico,
        reason="Canal privado do bot de segurança"
    )

async def obter_canal_log(guild, tipo):
    """tipo "ban" = ban, unban, kick e alertas de segurança | tipo "mute" = mute, unmute e warn."""
    em_uso = bot.canais_log.get(tipo)
    if em_uso:
        canal = guild.get_channel(em_uso)
        if canal:
            return canal
    id_config, nome = (CANAL_BAN, NOME_CANAL_BAN) if tipo == "ban" else (CANAL_MUTE, NOME_CANAL_MUTE)
    canal = guild.get_channel(id_config) if id_config else None
    if canal is None:
        if id_config:
            print(f"[Aviso] Não achei o canal de log '{tipo}' (ID {id_config}). O bot não enxerga esse canal? Vou usar/criar #{nome}.")
        try:
            canal = await obter_canal_privado(
                guild, nome, f"Logs de {'ban/kick e alertas de segurança' if tipo == 'ban' else 'mute e warn'} do bot.", criar=True
            )
        except discord.HTTPException as e:
            print(f"[Aviso] Não consegui achar/criar o canal de log '{tipo}': {e}")
            return None
    bot.canais_log[tipo] = canal.id
    return canal

# ==================== LOGS (SÓ PUNIÇÕES E ALERTAS DE SEGURANÇA) ====================
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
    canal = await obter_canal_log(guild, "ban")
    if not canal:
        return
    embed = discord.Embed(title=titulo, description=descricao[:4000], color=COR, timestamp=discord.utils.utcnow())
    rodape(embed, guild)
    try:
        await canal.send(embed=embed)
    except discord.HTTPException as e:
        print(f"[Aviso] Não consegui enviar o alerta: {e}")

async def alertar_dono(guild, titulo, texto):
    """Avisa o dono por DM (caso o canal de alertas esteja escondido/apagado por um invasor)."""
    try:
        dono = guild.owner or await guild.fetch_member(guild.owner_id)
        await dono.send(f"**{titulo}**\n{texto}"[:1900])
    except Exception:
        pass

async def log_falha_ban(guild, alvo, motivo, erro):
    """Avisa quando o bot NÃO conseguiu banir (antes só aparecia no console)."""
    await enviar_alerta(
        guild,
        f"⚠️ {NOME_SERVIDOR} - Falha ao Banir",
        f"👤 **Usuário:** {alvo.mention} (`{alvo.id}`)\n"
        f"📄 **Motivo do ban:** {motivo}\n"
        f"❌ **Erro:** `{type(erro).__name__}`\n\n"
        f"Confira se o cargo do bot está **acima** do cargo dessa pessoa e se ele tem a permissão **Banir Membros**. "
        f"Ninguém consegue banir o dono do servidor."
    )

# ==================== PUNIÇÕES ====================
async def executar_banimento(guild, alvo, staff, motivo, acao_log, prova_url=None, prova_arquivo=None,
                             apagar_segundos=0, prova_texto=None):
    if alvo.id in bot.banindo:
        return True  # já tem um ban em andamento para essa pessoa (ex.: várias imagens de uma vez)
    bot.banindo.add(alvo.id)

    try:
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
            try:
                await guild.ban(alvo, **kwargs)
            except TypeError:   # discord.py antigo (< 2.1) não conhece delete_message_seconds
                kwargs.pop("delete_message_seconds", None)
                await guild.ban(alvo, **kwargs)
        except Exception as e:
            print(f"[ERRO PERMISSÃO] Não foi possível banir o usuário {alvo.name} ({alvo.id}). Detalhe: {e}")
            try:
                await log_falha_ban(guild, alvo, motivo, e)
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

async def executar_expulsao(guild, alvo, staff, motivo, acao_log, dm=True):
    if dm:
        try:
            await alvo.send(f"**{NOME_SERVIDOR}** — você foi expulso(a).\n**Motivo:** {motivo}")
        except Exception:
            pass
    try:
        await guild.kick(alvo, reason=f"{staff.name} | {motivo}"[:480])
    except Exception as e:
        print(f"[ERRO PERMISSÃO] Não foi possível expulsar {alvo.name} ({alvo.id}). Detalhe: {e}")
        return False
    try:
        await log_punicao(guild, alvo, staff, acao_log, motivo)
    except Exception as e:
        print(f"[Aviso] {alvo.name} foi expulso, mas o log da punição falhou: {e}")
    return True

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

async def registrar_imagem(guild, user, dados, nome=None):
    """Bloqueia uma imagem (usado pelo /bloquear_imagem). Retorna (ok, texto_para_o_admin)."""
    loop = asyncio.get_running_loop()
    try:
        frames, melhor, _ = await loop.run_in_executor(None, avaliar_imagem, dados)
    except Exception as e:
        return False, f"❌ Não consegui ler essa imagem: `{e}`"
    if not frames:
        return False, "❌ Não consegui calcular os hashes dessa imagem."

    if melhor and melhor[0] <= LIMITE_HASH:
        dist, alg, _, origem = melhor
        quem = "uma imagem da lista fixa do código" if origem == "lista" else f"`{origem}`"
        return False, f"ℹ️ Essa imagem **já é bloqueada**: é parecida com {quem} (`{alg}`, distância {dist}). Não precisei adicionar."

    # Em GIF animado, usa o primeiro frame que tenha detalhe (o 1º às vezes é só uma tela preta)
    escolhido = next((f for f in frames if not eh_hash_liso(f)), None)
    if escolhido is None:
        return False, "❌ Essa imagem tem quase nenhum detalhe (uma cor só, degradê...). Bloquear ela baniria muita gente inocente."

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
        f"Quem enviar essa imagem (ou uma parecida) no {NOME_SERVIDOR} leva ban automático."
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
    try:
        if RAID_ACAO == "ban":
            await membro.guild.ban(membro, reason=motivo)
        else:
            await membro.kick(reason=motivo)
        return True
    except discord.HTTPException:
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
    guild = membro.guild
    if membro.bot or eh_confiavel(guild, membro.id):
        return
    agora = time.monotonic()

    # 1) Modo raid ligado: ninguém novo entra
    if raid_ativo():
        if await barrar_entrada(membro, "Anti-Raid: servidor em modo de proteção"):
            bot.raid_expulsos += 1
        return

    # 2) Rajada de entradas?
    bot.entradas_recentes.append((agora, membro.id))
    while bot.entradas_recentes and agora - bot.entradas_recentes[0][0] > RAID_JANELA_SEG:
        bot.entradas_recentes.popleft()
    if len(bot.entradas_recentes) >= RAID_ENTRADAS:
        await ativar_raid(guild, f"{len(bot.entradas_recentes)} entradas em {RAID_JANELA_SEG}s")
        return

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
            try:
                await membro.kick(reason=f"Anti-Raid: conta com menos de {IDADE_MINIMA_CONTA_DIAS} dia(s)")
            except discord.HTTPException:
                pass

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

async def tratar_infracao(message, motivo, pontos, refs=None):
    """Apaga o que for preciso, soma pontos e aplica a escada (aviso -> mute 10min -> 1h -> 1 dia)."""
    guild, membro = message.guild, message.author
    refs = refs or [(message.channel.id, message.id)]

    if membro.id in bot.punindo:   # outra mensagem dele já está sendo tratada: só apaga essa
        await apagar_mensagens(guild, refs)
        return
    bot.punindo.add(membro.id)
    try:
        await apagar_mensagens(guild, refs)
        total = somar_pontos(membro.id, pontos)
        minutos = next((m for limite, m in ESCADA_PONTOS if total >= limite), 0)
        if minutos:
            ok = await aplicar_mute(guild, membro, bot.user, minutos, f"Automod: {motivo}", "Mute (Automático)")
            if ok:
                await avisar_canal(message.channel, f"🔇 {membro.mention} foi silenciado por {formatar_duracao(minutos)}: {motivo}.")
        else:
            await avisar_canal(message.channel, f"⚠️ {membro.mention}, {motivo}. ({total} ponto(s) de infração)")
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
    """Mensagem de golpe/fake = ban. Sem exceção de staff (conta de staff invadida também posta golpe)."""
    termo = achar_na_lista(message.content, TERMOS_BAN_C)
    if not termo:
        return False
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    await executar_banimento(
        message.guild, message.author, bot.user,
        f"Tentativa de golpe (Mensagem Fake): `{termo}`", "Ban (Automático)",
        apagar_segundos=3600, prova_texto=message.content
    )
    return True

async def automod(message, editada=False):
    """Convites, menção em massa, palavrões, links de novatos, spam e formatação abusiva. True = mensagem tratada."""
    membro = message.author
    if STAFF_ISENTA_DO_AUTOMOD and eh_staff(membro):
        return False
    texto = message.content or ""

    # 1) Convites de outros servidores
    if texto and achar_convite(texto):
        await tratar_infracao(message, "divulgação de convite de servidor", PONTOS["convite"])
        return True

    # 2) Menção em massa
    mencoes = len({u.id for u in message.mentions}) + len(message.role_mentions)
    if mencoes >= MAX_MENCOES:
        await tratar_infracao(message, f"menção em massa ({mencoes} menções)", PONTOS["mencoes"])
        return True

    # 3) Palavrões / xingamentos (só palavra INTEIRA)
    if texto and achar_na_lista(texto, PALAVROES_C):
        await tratar_infracao(message, "linguagem imprópria", PONTOS["palavrao"])
        return True

    # 4) Links para quem acabou de entrar
    if texto and NOVATO_SEM_LINKS_MIN and eh_novato(membro):
        if any(not dominio_permitido(u) for u in URL_REGEX.findall(texto)):
            await tratar_infracao(message, "links bloqueados para quem acabou de entrar", PONTOS["link_novato"])
            return True

    # 5) Spam (só em mensagem nova, não em edição)
    if not editada:
        achado = checar_spam(message)
        if achado:
            motivo, pontos, refs = achado
            await tratar_infracao(message, motivo, pontos, refs)
            return True

    # 6) Formatação abusiva
    motivo = achar_formatacao_abusiva(texto)
    if motivo:
        await tratar_infracao(message, motivo, PONTOS["formatacao"])
        return True
    return False

# ==================== VERIFICAÇÃO DE IMAGENS NO CHAT ====================
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
    """Confere as imagens da mensagem. Se alguma for parecida com a lista, apaga e bane. Retorna True se baniu."""
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
            _, melhor, _ = await loop.run_in_executor(None, avaliar_imagem, dados)
        except Exception as e:
            print(f"[Aviso Automod] Erro ao analisar a imagem {url}: {e}")
            continue

        if melhor and melhor[0] <= LIMITE_HASH:
            dist, algoritmo, _, origem = melhor
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            # Banimento + imagem anexada como prova no log (não depende do link, que morre ao apagar)
            await executar_banimento(
                message.guild, message.author, bot.user,
                "Envio de imagem proibida.",
                f"Ban (Automático) • {algoritmo} dist. {dist} • {origem}",
                prova_url=url,
                prova_arquivo=(dados, nome_seguro(nome)),
                apagar_segundos=3600
            )
            return True
    return False

# ==================== TICKETS (GENÉRICOS DO K7NG) ====================
def ler_dono_ticket(canal):
    topico = getattr(canal, "topic", None) or ""
    if topico.startswith(TOPICO_TICKET):
        try:
            return int(topico[len(TOPICO_TICKET):])
        except ValueError:
            return None
    return None

class SelectTicket(discord.ui.Select):
    def __init__(self):
        opcoes = [
            discord.SelectOption(label="Suporte", value="suporte", description="Ajuda geral e recurso de punição.", emoji="🛠️"),
            discord.SelectOption(label="Denúncia", value="denuncia", description="Denunciar um membro ou situação.", emoji="🚨"),
            discord.SelectOption(label="Dúvidas", value="duvidas", description="Tire dúvidas sobre o servidor ou as regras.", emoji="❓"),
        ]
        super().__init__(placeholder="Selecione o motivo do atendimento...", min_values=1, max_values=1,
                         options=opcoes, custom_id="k7ng_sel_ticket")

    async def callback(self, interaction: discord.Interaction):
        await criar_ticket(interaction, self.values[0])

class ViewTickets(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelectTicket())

class ViewFechar(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="k7ng_fechar_ticket")
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        if not (eh_staff(interaction.user) or interaction.user.id == ler_dono_ticket(canal)):
            await interaction.response.send_message("❌ Só a staff ou quem abriu o ticket pode fechá-lo.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Fechando canal em 5 segundos...", ephemeral=True)
        await asyncio.sleep(5)
        try:
            await canal.delete(reason=f"Ticket fechado por {interaction.user.name}")
        except discord.HTTPException:
            pass

async def criar_ticket(interaction, setor):
    guild = interaction.guild
    if guild is None or guild.id != GUILD_ID:
        return
    await interaction.response.defer(ephemeral=True)
    membro = interaction.user

    topico = f"{TOPICO_TICKET}{membro.id}"
    existente = discord.utils.find(lambda c: c.topic == topico, guild.text_channels)
    if existente:
        await interaction.followup.send(f"❌ Você já tem um ticket aberto: {existente.mention}", ephemeral=True)
        return

    categoria = guild.get_channel(CATEGORIA_TICKETS) if CATEGORIA_TICKETS else None
    if not isinstance(categoria, discord.CategoryChannel):
        categoria = None
    cargo_staff = guild.get_role(CARGO_STAFF) if CARGO_STAFF else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        membro: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, embed_links=True),
    }
    if cargo_staff:
        overwrites[cargo_staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    nome_limpo = re.sub(r'[^a-z0-9-]', '', membro.name.lower())[:20] or str(membro.id)
    try:
        canal = await guild.create_text_channel(
            name=f"ticket-{nome_limpo}-{setor}", category=categoria, overwrites=overwrites,
            topic=topico, reason=f"Ticket de {membro.name} ({setor})"
        )
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Não consegui criar o ticket ({type(e).__name__}). Avise a staff.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"🚨 {NOME_SERVIDOR} - Atendimento",
        description=(
            f"Olá {membro.mention},\n\n"
            f"Seu ticket para **{setor.upper()}** foi aberto com sucesso!\n"
            f"Descreva detalhadamente o que precisa abaixo para que a equipe possa te responder."
        ),
        color=COR
    )
    await canal.send(content=f"{membro.mention} {cargo_staff.mention if cargo_staff else ''}", embed=embed, view=ViewFechar())
    await interaction.followup.send(f"✅ Ticket criado em {canal.mention}!", ephemeral=True)

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

# ==================== MANUTENÇÃO (limpeza de memória e fim do modo raid) ====================
@tasks.loop(seconds=30)
async def manutencao():
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

# ==================== EVENTOS ====================
PERMS_NECESSARIAS = {
    "ban_members": "Banir Membros", "kick_members": "Expulsar Membros", "moderate_members": "Silenciar Membros",
    "manage_roles": "Gerenciar Cargos", "manage_channels": "Gerenciar Canais",
    "manage_messages": "Gerenciar Mensagens", "view_audit_log": "Ver Registro de Auditoria",
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
        if (discord.version_info.major, discord.version_info.minor) < (2, 4):
            print(f"[AVISO] discord.py {discord.__version__} é antigo: anti-nuke e logs de punição manual precisam da 2.4+ (pip install -U discord.py).")
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            print(f"[ERRO] O bot não está no servidor GUILD_ID={GUILD_ID}. Confira o ID e se o bot foi convidado para o K7NG.")
        else:
            try:
                await obter_canal_log(guild, "ban")
                await obter_canal_log(guild, "mute")
                await carregar_registros(guild)
                await verificar_permissoes(guild)
            except Exception as e:
                print(f"[Aviso] Erro ao preparar o servidor: {e!r}")
            await sair_de_outros_servidores()
    print(f"✅ Sistema perfeito! {bot.user.name} está online, protegendo o {NOME_SERVIDOR} (cor #{COR:06x}).")

@bot.event
async def on_guild_join(guild):
    await sair_de_outros_servidores()

@bot.event
async def on_member_join(membro):
    if membro.guild.id != GUILD_ID:
        return
    try:
        await tratar_entrada(membro)
    except Exception as e:
        print(f"[Aviso Anti-Raid] Erro ao tratar a entrada de {membro}: {e!r}")

@bot.event
async def on_audit_log_entry_create(entry):
    if entry.guild.id != GUILD_ID:
        return
    for rotina in (antinuke, log_manual):
        try:
            await rotina(entry)
        except Exception as e:
            print(f"[Aviso] {rotina.__name__} falhou: {e!r}")

@bot.event
async def on_raw_message_delete(payload):
    esquecer_registros_apagados([payload.message_id])

@bot.event
async def on_raw_bulk_message_delete(payload):
    esquecer_registros_apagados(payload.message_ids)

@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None or message.guild.id != GUILD_ID:
        return

    # 1. Golpes / mensagens fake (ban automático, sem exceção de staff)
    try:
        if await filtro_golpes(message):
            return
    except Exception as e:
        print(f"[Aviso Automod] Erro no filtro de golpes: {e!r}")

    # 2. Imagens proibidas (hash). Vem ANTES dos filtros abaixo para uma mensagem com palavrão + imagem proibida
    #    não ter só o texto apagado com a imagem nunca conferida.
    try:
        if await checar_imagens_proibidas(message):
            return
    except Exception as e:
        print(f"[Aviso Automod] Erro na checagem de imagens: {e!r}")

    # 3. Convites, menções, palavrões, links de novatos, spam e formatação abusiva
    try:
        await automod(message)
    except Exception as e:
        print(f"[Aviso Automod] Erro no automod: {e!r}")

@bot.event
async def on_message_edit(antes, depois):
    if depois.author.bot or depois.guild is None or depois.guild.id != GUILD_ID:
        return

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

@comando(name="status", description="Mostra o estado de todas as proteções do bot.")
@exige(moderate_members=True)
async def status_slash(interaction: discord.Interaction):
    guild = interaction.guild
    if raid_ativo():
        raid = f"🔴 ATIVO — restam ~{int((bot.raid_ate - time.monotonic()) // 60) + 1} min • {bot.raid_expulsos} barrada(s)"
    else:
        raid = f"🟢 Desligado • liga sozinho com {RAID_ENTRADAS} entradas em {RAID_JANELA_SEG}s"
    travados = len({c for c, _ in bot.lock_estado})
    embed = discord.Embed(title=f"🛡️ {NOME_SERVIDOR} - Status da Segurança", color=COR, timestamp=discord.utils.utcnow())
    embed.add_field(name="Anti-Raid", value=f"{raid}\nAção: {RAID_ACAO} • conta mínima: {IDADE_MINIMA_CONTA_DIAS or 'sem limite'} dia(s)", inline=False)
    embed.add_field(
        name="Anti-Spam",
        value=(f"{SPAM_MENSAGENS} msgs/{SPAM_JANELA_SEG}s • {SPAM_DUPLICADAS} repetidas • {SPAM_CANAIS} canais • "
               f"{MAX_MENCOES} menções\nMute automático a partir de {ESCADA_PONTOS[-1][0]} ponto(s)"),
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
        value=(f"Golpes: {len(TERMOS_BAN)} termos • Palavrões: {len(PALAVROES)} • "
               f"Imagens: {len(HASHES_FIXOS)} fixas + {len(bot.imagens_registradas)} por comando"),
        inline=False
    )
    embed.add_field(name="Lockdown", value=f"🔒 {travados} canal(is) travado(s)" if travados else "🔓 Nenhum", inline=True)
    embed.add_field(name="Warns", value=f"{sum(len(warns_ativos(u)) for u in list(bot.warns))} ativo(s)", inline=True)
    embed.add_field(name="Ping", value=f"{round(bot.latency * 1000)} ms", inline=True)
    rodape(embed, guild)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== COMANDOS DE IMAGENS BLOQUEADAS ====================
@comando(name="bloquear_imagem", description="Bloqueia uma imagem: quem enviar ela (ou uma parecida) leva ban.")
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
        f"📌 **Hashes fixos no código:** {len(HASHES_FIXOS)}\n\n"
        + ("\n".join(linhas) if linhas else "_Nenhuma ainda. Use /bloquear_imagem._")
    )
    if len(texto) > 1900:
        arquivo = discord.File(BytesIO(texto.encode("utf-8")), filename="imagens_bloqueadas.txt")
        await interaction.followup.send("A lista é grande, segue em arquivo:", file=arquivo)
    else:
        await interaction.followup.send(texto)

@comando(name="testar_imagem", description="Mostra os hashes de uma imagem e se o bot a baniria (não bloqueia nada).")
@app_commands.describe(imagem="A imagem que você quer testar")
@exige(administrator=True)
async def testar_imagem_slash(interaction: discord.Interaction, imagem: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    dados = await imagem.read()
    try:
        frames, melhor, menores = await asyncio.get_running_loop().run_in_executor(None, avaliar_imagem, dados)
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
    if melhor is None:
        texto += "\nNão há nenhuma imagem na lista de bloqueadas, então nada seria banido."
    else:
        dist, alg, _, origem = melhor
        texto += (
            f"\n**Menor distância até a lista** (0 = igual, limite atual = {LIMITE_HASH}):\n"
            f"```\naverage: {menores['average']}\nphash:   {menores['phash']}\ndhash:   {menores['dhash']}\n```"
        )
        if dist <= LIMITE_HASH:
            texto += f"\n🚫 **Seria BANIDA** — `{alg}`, distância {dist}, parecida com `{origem}`."
        else:
            texto += f"\n✅ **Não seria banida** — a mais próxima ficou a {dist} de distância (`{alg}`, `{origem}`)."
    await interaction.followup.send(texto)

# ==================== PAINÉIS (TICKETS E VERIFICAÇÃO) ====================
@comando(name="painel_tickets", description="Envia o painel de atendimento de tickets neste canal.")
@exige(administrator=True)
async def painel_tickets_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"🛡️ CENTRAL DE ATENDIMENTO - {NOME_SERVIDOR}",
        description=(
            "**Suporte:**\n"
            "↳ Ajuda geral e recurso de punição.\n\n"
            "**Denúncia:**\n"
            "↳ Denunciar um membro ou situação (leve as provas).\n\n"
            "**Dúvidas:**\n"
            "↳ Tire dúvidas sobre o servidor ou as regras.\n\n"
            "**Lembre-se:** nossa equipe está pronta para resolver tudo de forma rápida e justa. "
            "Sua privacidade será respeitada durante todo o processo!"
        ),
        color=COR
    )
    if IMAGEM_PAINEL_TICKETS:
        embed.set_image(url=IMAGEM_PAINEL_TICKETS)
    await interaction.channel.send(embed=embed, view=ViewTickets())
    await interaction.response.send_message("✅ Painel de tickets enviado com sucesso!", ephemeral=True)

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

# ==================== INÍCIO ====================
if __name__ == "__main__":
    if not GUILD_ID:
        raise SystemExit("❌ Preencha o GUILD_ID (ID do servidor K7NG) no topo do arquivo antes de ligar o bot.")
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise SystemExit("❌ Variável de ambiente TOKEN não encontrada (coloque o token do bot nela).")
    Thread(target=run_server, daemon=True).start()
    bot.run(TOKEN)
