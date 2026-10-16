from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import html as _html
import logging
import os
import re
import secrets
import time
from urllib.parse import urlparse

import pymysql
import requests

from banco import get_db_connection
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
import mercadopago
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps

from itsdangerous import BadSignature, URLSafeTimedSerializer

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # sem a biblioteca, "ver senha" fica desligado
    Fernet = None
    InvalidToken = Exception

sdk = mercadopago.SDK(os.environ.get("MERCADO_PAGO_ACCESS_TOKEN"))
MERCADO_PAGO_PUBLIC_KEY = os.environ.get("MERCADO_PAGO_PUBLIC_KEY", "")

# Login do administrador: e-mail + HASH da senha (nunca a senha) ficam nas variáveis de ambiente.
ADMIN_EMAIL = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
ADMIN_PASSWORD_HASH = (os.environ.get("ADMIN_PASSWORD_HASH") or "").strip()
ADMIN_TOKEN_DIAS = int(os.environ.get("ADMIN_TOKEN_DIAS", "30") or 30)
MERCADO_PAGO_WEBHOOK_SECRET = os.environ.get("MERCADO_PAGO_WEBHOOK_SECRET")
DEBUG_MODE = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

if not ADMIN_EMAIL or not ADMIN_PASSWORD_HASH:
    logging.warning("ADMIN_EMAIL / ADMIN_PASSWORD_HASH ausentes: ninguém consegue entrar nas rotas /api/admin.")
if not MERCADO_PAGO_WEBHOOK_SECRET:
    logging.warning("MERCADO_PAGO_WEBHOOK_SECRET ausente: o webhook rejeitará todas as chamadas.")

# ==============================================================================
# VALIDAÇÃO DE ENTRADA
# ==============================================================================
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TELEFONE_RE = re.compile(r"^[\d\s()+-]{0,20}$")
STATUS_RE = re.compile(r"^[A-Za-zÀ-ÿ _-]{3,20}$")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
TIPOS_PAGAMENTO = {"presencial", "plano", "vip", "pix", "cartao", "dinheiro", "debito", "credito", "saldo"}
HORARIOS_VALIDOS = []
for _h in range(9, 20):
    HORARIOS_VALIDOS.append(f"{_h:02d}:00")
    if _h < 19:
        HORARIOS_VALIDOS.append(f"{_h:02d}:30")
_INVALIDO = object()


def parse_decimal(valor, minimo=0, maximo=100000):
    """Converte para Decimal com 2 casas; devolve None se inválido ou fora do intervalo."""
    try:
        d = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d < minimo or d > maximo:
        return None
    return d.quantize(Decimal("0.01"))


def parse_int(valor, minimo=0, maximo=1000000):
    try:
        if isinstance(valor, bool):
            return None
        n = int(str(valor).strip())
    except (ValueError, TypeError):
        return None
    return n if minimo <= n <= maximo else None


def validar_foto(foto):
    """Aceita vazio, URL http(s), data URI de imagem ou base64 puro; limita o tamanho."""
    if not foto:
        return True
    if len(foto) > 3_000_000:
        return False
    prefixos = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/jpg;base64,",
                "data:image/webp;base64,", "data:image/gif;base64,", "https://", "http://")
    return foto.startswith(prefixos) or bool(BASE64_RE.match(foto))


def cpf_valido(cpf):
    if len(cpf) != 11 or not cpf.isdigit() or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(cpf[n]) * (i + 1 - n) for n in range(i))
        if (soma * 10 % 11) % 10 != int(cpf[i]):
            return False
    return True


def validar_cadastro(nome, email, senha, telefone):
    if not nome or not email or not senha:
        return "Preencha todos os campos obrigatórios!"
    if len(nome) > 100 or len(email) > 100 or not EMAIL_RE.match(email):
        return "Nome ou e-mail inválido."
    if not (8 <= len(senha) <= 128):
        return "A senha deve ter entre 8 e 128 caracteres."
    if not TELEFONE_RE.match(telefone or ""):
        return "Telefone inválido."
    return None


def conv_texto(maximo, obrigatorio=False):
    def conv(v):
        s = ("" if v is None else str(v)).strip()
        if (obrigatorio and not s) or len(s) > maximo:
            return _INVALIDO
        return s
    return conv


def conv_decimal(minimo=0, maximo=100000):
    def conv(v):
        d = parse_decimal(v, minimo, maximo)
        return _INVALIDO if d is None else d
    return conv


def conv_inteiro(minimo=0, maximo=1000000):
    def conv(v):
        n = parse_int(v, minimo, maximo)
        return _INVALIDO if n is None else n
    return conv


def conv_bool(v):
    return 1 if v in (True, 1, "1", "true", "True") else 0


def conv_foto(v):
    s = ("" if v is None else str(v)).strip()
    return s if validar_foto(s) else _INVALIDO


def montar_update(data, permitidos):
    """Monta o SET de um UPDATE usando só campos permitidos (nomes vêm do dict, nunca do usuário)."""
    campos, valores = [], []
    for campo, conv in permitidos.items():
        if campo in data:
            valor = conv(data[campo])
            if valor is _INVALIDO:
                return None, None, campo
            campos.append(f"{campo} = %s")
            valores.append(valor)
    return campos, valores, None


# ==============================================================================
# LIMITE DE TENTATIVAS (em memória, por processo; use Redis se rodar vários workers)
# ==============================================================================
_tentativas = defaultdict(deque)


def _ip_cliente():
    return request.remote_addr or "desconhecido"


def _limite_excedido(chave, maximo, janela):
    agora = time.time()
    fila = _tentativas[chave]
    while fila and agora - fila[0] > janela:
        fila.popleft()
    if len(_tentativas) > 5000:
        for k in [k for k, v in _tentativas.items() if not v]:
            del _tentativas[k]
    return len(fila) >= maximo


def _registrar_tentativa(chave):
    _tentativas[chave].append(time.time())


def rate_limit(maximo, janela, nome):
    """Limita requisições POST por IP."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if request.method == "POST":
                chave = f"{nome}:{_ip_cliente()}"
                if _limite_excedido(chave, maximo, janela):
                    return jsonify({"sucesso": False, "mensagem": "Muitas tentativas. Aguarde alguns minutos."}), 429
                _registrar_tentativa(chave)
            return f(*args, **kwargs)
        return wrapper
    return deco


# ==============================================================================
# AUTENTICAÇÃO ADMIN
# ==============================================================================
def _serializador_admin():
    return URLSafeTimedSerializer(app.secret_key, salt="versati-admin-token")


def _versao_credencial_admin():
    """Muda quando a senha do admin muda: tokens antigos deixam de valer."""
    return hashlib.sha256((ADMIN_EMAIL + ADMIN_PASSWORD_HASH).encode("utf-8")).hexdigest()[:16]


def _token_admin_valido():
    """Aceita só o token assinado emitido por /api/admin/login (com prazo de validade)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not ADMIN_EMAIL or not ADMIN_PASSWORD_HASH:
        return False
    token = auth[7:].strip()
    if not token:
        return False
    try:
        dados = _serializador_admin().loads(token, max_age=ADMIN_TOKEN_DIAS * 86400)
    except BadSignature:  # inclui SignatureExpired
        return False
    return isinstance(dados, dict) and hmac.compare_digest(
        str(dados.get("v", "")), _versao_credencial_admin()
    )


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Pré-voo CORS não carrega credenciais; as respostas CORS ficam por conta do Flask-CORS
        if request.method == "OPTIONS":
            return "", 204

        chave = f"admin-falha:{_ip_cliente()}"
        if _limite_excedido(chave, 10, 300):
            return jsonify({"sucesso": False, "mensagem": "Muitas tentativas. Aguarde alguns minutos."}), 429

        if not _token_admin_valido():
            _registrar_tentativa(chave)
            return jsonify({"sucesso": False, "mensagem": "Não autorizado"}), 401

        return f(*args, **kwargs)
    return wrapper


class CustomJSONProvider(DefaultJSONProvider):
    """Converte objetos Decimal em float para não quebrar a serialização JSON."""
    ensure_ascii = False

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


app = Flask(__name__)


def garantir_coluna_concluido_em():
    """Cria a coluna agendamentos.concluido_em (data/hora em que o atendimento foi concluído)."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW COLUMNS FROM agendamentos LIKE 'concluido_em'")
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE agendamentos ADD COLUMN concluido_em DATETIME NULL")
                    conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível garantir a coluna concluido_em:", e)


def garantir_agendamento_sem_cadastro():
    """Permite agendar cliente sem cadastro: cliente_id aceita NULL e guarda o nome em cliente_nome."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW COLUMNS FROM agendamentos LIKE 'cliente_nome'")
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE agendamentos ADD COLUMN cliente_nome VARCHAR(100) NULL")
                cursor.execute("SHOW COLUMNS FROM agendamentos LIKE 'cliente_id'")
                col = cursor.fetchone()
                if col and str(col.get("Null", "")).upper() == "NO":
                    cursor.execute("ALTER TABLE agendamentos MODIFY cliente_id INT NULL")
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível preparar agendamento sem cadastro:", e)


def garantir_coluna_ativo_barbeiros():
    """Cria barbeiros.ativo (0 = removido da equipe, mas mantém o histórico financeiro)."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW COLUMNS FROM barbeiros LIKE 'ativo'")
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE barbeiros ADD COLUMN ativo TINYINT(1) NOT NULL DEFAULT 1")
                    conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível garantir a coluna barbeiros.ativo:", e)


def garantir_tabela_cadastros_pendentes():
    """Cadastros aguardando a confirmação do código enviado por e-mail."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS cadastros_pendentes ("
                    "email VARCHAR(100) PRIMARY KEY, "
                    "nome VARCHAR(100) NOT NULL, "
                    "telefone VARCHAR(20), "
                    "senha_hash VARCHAR(255) NOT NULL, "
                    "codigo_hash VARCHAR(64) NOT NULL, "
                    "expira_em DATETIME NOT NULL, "
                    "tentativas INT NOT NULL DEFAULT 0, "
                    "ultimo_envio DATETIME NOT NULL"
                    ") ENGINE=InnoDB"
                )
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível garantir a tabela cadastros_pendentes:", e)


_SENHA_COL_OK = False  # vira True se SENHA_CIFRA_KEY estiver válida e as colunas existirem


def _fernet():
    chave = os.environ.get("SENHA_CIFRA_KEY", "").strip()
    if not chave or Fernet is None:
        return None
    try:
        return Fernet(chave.encode("utf-8"))
    except Exception:
        logging.error("SENHA_CIFRA_KEY inválida: gere uma nova com Fernet.generate_key().")
        return None


def _cifrar_senha(senha):
    f = _fernet()
    return f.encrypt(senha.encode("utf-8")).decode("utf-8") if f else None


def _decifrar_senha(token):
    f = _fernet()
    if not f or not token:
        return None
    try:
        return f.decrypt(str(token).encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def garantir_tabela_redefinicoes_senha():
    """Códigos de 'esqueci minha senha' (guardamos só o HMAC do código, nunca o código)."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS redefinicoes_senha ("
                    "email VARCHAR(100) PRIMARY KEY, "
                    "codigo_hash VARCHAR(64) NOT NULL, "
                    "expira_em DATETIME NOT NULL, "
                    "tentativas INT NOT NULL DEFAULT 0, "
                    "ultimo_envio DATETIME NOT NULL"
                    ") ENGINE=InnoDB"
                )
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível garantir a tabela redefinicoes_senha:", e)


def garantir_colunas_senha_cifrada():
    """Opt-in: só mexe no banco se SENHA_CIFRA_KEY estiver configurada."""
    global _SENHA_COL_OK
    if _fernet() is None:
        return
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                for tabela in ("usuarios", "cadastros_pendentes"):
                    cursor.execute(f"SHOW COLUMNS FROM {tabela} LIKE 'senha_cifrada'")
                    if not cursor.fetchone():
                        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN senha_cifrada TEXT NULL")
                conn.commit()
            _SENHA_COL_OK = True
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível preparar as colunas senha_cifrada:", e)


def garantir_tabela_pagamentos():
    """Tabela de pagamentos já processados (idempotência da ativação de planos)."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS pagamentos_processados ("
                    "pagamento_id VARCHAR(64) PRIMARY KEY, cliente_id INT NOT NULL, "
                    "processado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB"
                )
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível garantir a tabela pagamentos_processados:", e)


def garantir_tabela_comissoes_pagas():
    """Controle de baixa das comissões: um registro por atendimento com a comissão já paga."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS comissoes_pagas (
                        agendamento_id INT PRIMARY KEY,
                        barbeiro_id INT NOT NULL,
                        valor DECIMAL(10, 2) NOT NULL DEFAULT 0,
                        percentual DECIMAL(5, 2) NOT NULL DEFAULT 0,
                        pago_em DATETIME NOT NULL,
                        INDEX idx_comissoes_barbeiro (barbeiro_id)
                    ) ENGINE=InnoDB
                """)
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print("Aviso: não foi possível garantir a tabela comissoes_pagas:", e)


garantir_coluna_concluido_em()
garantir_agendamento_sem_cadastro()
garantir_tabela_comissoes_pagas()
garantir_coluna_ativo_barbeiros()
garantir_tabela_cadastros_pendentes()
garantir_colunas_senha_cifrada()
garantir_tabela_redefinicoes_senha()
garantir_tabela_pagamentos()
app.json_provider_class = CustomJSONProvider

_secret = os.environ.get("FLASK_SECRET_KEY")
if not _secret or len(_secret) < 32:
    raise RuntimeError(
        "FLASK_SECRET_KEY ausente ou curta (mínimo 32 caracteres). Gere uma com: "
        "python -c \"import secrets; print(secrets.token_hex(32))\""
    )
app.secret_key = _secret

if os.environ.get("TRUST_PROXY", "").lower() == "true" or os.environ.get("RENDER"):
    # Atrás de Nginx/Render/Heroku: usa X-Forwarded-* para IP, host e esquema reais
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_cookie_seguro_env = os.environ.get("SESSION_COOKIE_SECURE")
SESSION_COOKIE_SEGURO = (_cookie_seguro_env.lower() == "true") if _cookie_seguro_env else (not DEBUG_MODE)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SEGURO,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)
# O app Flutter não usa CORS. Só habilite se o site/painel web ficar em OUTRO domínio.
if CORS_ORIGINS:
    CORS(
        app,
        resources={r"/api/*": {"origins": CORS_ORIGINS}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        max_age=3600,
    )


@app.before_request
def protecao_csrf_por_origem():
    """Bloqueia requisições que alteram dados vindas de outra origem (CSRF), sem exigir mudança nos templates."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path != "/api/webhook":
        if request.headers.get("Authorization") and _token_admin_valido():
            return None  # chamadas com token admin válido (app) não dependem de cookie
        origem = request.headers.get("Origin")
        if origem:
            origem = origem.rstrip("/")
            if urlparse(origem).netloc != request.host and origem not in CORS_ORIGINS:
                return jsonify({"sucesso": False, "mensagem": "Origem não permitida."}), 403
    return None


@app.after_request
def cabecalhos_de_seguranca(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if SESSION_COOKIE_SEGURO:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route('/api/admin/servicos/<int:servico_id>', methods=['PUT', 'DELETE'])
@admin_required
def editar_ou_remover_servico(servico_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'DELETE':
                cursor.execute("DELETE FROM servicos WHERE id = %s", (servico_id,))
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Serviço removido!'}), 200

            data = request.get_json() or {}
            nome = (data.get('nome') or '').strip()
            preco = data.get('preco', 0)
            categoria = (data.get('categoria') or 'Geral').strip()
            foto = (data.get('foto') or '').strip()

            if not nome:
                return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400
            preco = parse_decimal(preco)
            if preco is None or len(nome) > 150 or len(categoria) > 80 or not validar_foto(foto):
                return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos (preço, nome ou foto).'}), 400

            cursor.execute(
                """UPDATE servicos 
                   SET nome = %s, preco = %s, categoria = %s, foto = %s 
                   WHERE id = %s""",
                (nome, preco, categoria, foto, servico_id)
            )
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Serviço atualizado com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em editar_ou_remover_servico: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()
@app.route('/api/admin/barbeiro/<int:barbeiro_id>/comissoes', methods=['GET', 'POST', 'OPTIONS'])
@admin_required
def gerenciar_comissoes_barbeiro(barbeiro_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                dados = request.get_json() or {}
                tipo = dados.get('tipo') 
                item_id = dados.get('item_id') 
                
                if tipo not in ('servico', 'produto') or parse_int(item_id, 1) is None:
                    return jsonify({'sucesso': False, 'mensagem': 'Tipo ou item inválido.'}), 400

                if tipo == 'servico':
                    realiza = 1 if dados.get('realiza', True) else 0
                    preco = parse_decimal(dados.get('preco_personalizado', 0))
                    duracao = parse_int(dados.get('duracao_minutos', 30), 5, 600)
                    comissao = parse_decimal(dados.get('comissao_percentual', 40), 0, 100)
                    if preco is None or duracao is None or comissao is None:
                        return jsonify({'sucesso': False, 'mensagem': 'Valores inválidos.'}), 400

                    cursor.execute("""
                        INSERT INTO barbeiro_servicos (barbeiro_id, servico_id, realiza, preco_personalizado, duracao_minutos, comissao_percentual)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                            realiza = VALUES(realiza),
                            preco_personalizado = VALUES(preco_personalizado),
                            duracao_minutos = VALUES(duracao_minutos),
                            comissao_percentual = VALUES(comissao_percentual)
                    """, (barbeiro_id, item_id, realiza, preco, duracao, comissao))
                
                elif tipo == 'produto':
                    comissao = parse_decimal(dados.get('comissao_percentual', 20), 0, 100)
                    if comissao is None:
                        return jsonify({'sucesso': False, 'mensagem': 'Comissão inválida.'}), 400
                    cursor.execute("""
                        INSERT INTO barbeiro_produtos (barbeiro_id, produto_id, comissao_percentual)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE comissao_percentual = VALUES(comissao_percentual)
                    """, (barbeiro_id, item_id, comissao))

                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Comissão atualizada com sucesso!'}), 200

            cursor.execute("SELECT id, nome, preco, categoria FROM servicos")
            servicos_base = cursor.fetchall()

            cursor.execute("SELECT bs.*, s.nome, s.preco AS preco_padrao FROM servicos s LEFT JOIN barbeiro_servicos bs ON s.id = bs.servico_id AND bs.barbeiro_id = %s", (barbeiro_id,))
            servicos_config = {item['servico_id']: item for item in cursor.fetchall() if item['servico_id']}

            servicos_resultado = []
            for s in servicos_base:
                cfg = servicos_config.get(s['id'], {})
                servicos_resultado.append({
                    'id': s['id'],
                    'nome': s['nome'],
                    'preco_padrao': float(s['preco']),
                    'realiza': int(cfg.get('realiza', 1)),
                    'preco_personalizado': float(cfg.get('preco_personalizado') if cfg.get('preco_personalizado') is not None else s['preco']),
                    'duracao_minutos': int(cfg.get('duracao_minutos', 30)),
                    'comissao_percentual': float(cfg.get('comissao_percentual', 40.00))
                })

            cursor.execute("SELECT p.id, p.nome, p.preco, bp.comissao_percentual FROM produtos p LEFT JOIN barbeiro_produtos bp ON p.id = bp.produto_id AND bp.barbeiro_id = %s", (barbeiro_id,))
            produtos_resultado = cursor.fetchall()

            return jsonify({
                'sucesso': True,
                'servicos': servicos_resultado,
                'produtos': produtos_resultado
            }), 200

    except Exception as e:
        app.logger.error("Erro em gerenciar_comissoes_barbeiro: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno.'}), 500
    finally:
        conn.close()


@app.route('/api/admin/barbeiro/<int:barbeiro_id>/horarios', methods=['GET', 'POST', 'OPTIONS'])
@admin_required
def gerenciar_horarios_barbeiro(barbeiro_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                dados = request.get_json() or {}
                dias = dados.get('dias', [])
                if not isinstance(dias, list) or len(dias) > 7:
                    return jsonify({'sucesso': False, 'mensagem': 'Lista de dias inválida.'}), 400
                padroes = {'hora_inicio': '09:00', 'hora_fim': '19:00', 'almoco_inicio': '12:00', 'almoco_fim': '13:00'}
                for d in dias:
                    if (not isinstance(d, dict) or parse_int(d.get('dia_semana'), 0, 6) is None
                            or not all(HORA_RE.match(str(d.get(k, v))) for k, v in padroes.items())):
                        return jsonify({'sucesso': False, 'mensagem': 'Horário ou dia inválido.'}), 400
                for d in dias:
                    cursor.execute("""
                        INSERT INTO barbeiro_horarios
                            (barbeiro_id, dia_semana, trabalha, hora_inicio, hora_fim, almoco_inicio, almoco_fim)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            trabalha = VALUES(trabalha),
                            hora_inicio = VALUES(hora_inicio),
                            hora_fim = VALUES(hora_fim),
                            almoco_inicio = VALUES(almoco_inicio),
                            almoco_fim = VALUES(almoco_fim)
                    """, (
                        barbeiro_id,
                        d.get('dia_semana'),
                        1 if d.get('trabalha', True) else 0,
                        d.get('hora_inicio', '09:00'),
                        d.get('hora_fim', '19:00'),
                        d.get('almoco_inicio', '12:00'),
                        d.get('almoco_fim', '13:00'),
                    ))
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Horários atualizados com sucesso!'}), 200

            cursor.execute(
                "SELECT dia_semana, trabalha, hora_inicio, hora_fim, almoco_inicio, almoco_fim "
                "FROM barbeiro_horarios WHERE barbeiro_id = %s",
                (barbeiro_id,)
            )
            existentes = {row['dia_semana']: row for row in cursor.fetchall()}

            dias_semana_nomes = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado']
            resultado = []
            for i, nome_dia in enumerate(dias_semana_nomes):
                cfg = existentes.get(i)
                trabalha_padrao = 0 if i == 0 else 1
                resultado.append({
                    'dia_semana': i,
                    'nome_dia': nome_dia,
                    'trabalha': int(cfg['trabalha']) if cfg else trabalha_padrao,
                    'hora_inicio': cfg['hora_inicio'] if cfg else '09:00',
                    'hora_fim': cfg['hora_fim'] if cfg else '19:00',
                    'almoco_inicio': cfg['almoco_inicio'] if cfg else '12:00',
                    'almoco_fim': cfg['almoco_fim'] if cfg else '13:00',
                })
            return jsonify({'sucesso': True, 'horarios': resultado}), 200
    except Exception as e:
        app.logger.error("Erro em gerenciar_horarios_barbeiro: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno.'}), 500
    finally:
        conn.close()
# ==============================================================================
# PAGAMENTOS — o preço SEMPRE vem do banco; o cliente SEMPRE vem da sessão
# ==============================================================================
HASH_FALSO = generate_password_hash("senha-inexistente-para-igualar-o-tempo")


def _verificar_senha(usuario, senha):
    """Confere a senha com hash; gasta o mesmo tempo mesmo se o usuário não existir."""
    try:
        if not usuario:
            check_password_hash(HASH_FALSO, senha)
            return False
        return check_password_hash(usuario["senha"], senha)
    except ValueError:
        return False


def _guardar_senha_cifrada_no_login(usuario, senha):
    """No login a senha é conhecida: guarda/atualiza a cópia cifrada (só se o recurso estiver ativo)."""
    if not _SENHA_COL_OK or _fernet() is None or not usuario:
        return
    try:
        if _decifrar_senha(usuario.get("senha_cifrada")) == senha:
            return
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE usuarios SET senha_cifrada = %s WHERE id = %s", (_cifrar_senha(senha), usuario["id"]))
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        app.logger.error("Erro ao guardar senha cifrada no login: %s", e)


def buscar_plano(plano_id=None, nome=None):
    """Busca um plano ativo do catálogo (fonte única de preço)."""
    pid = parse_int(plano_id, 1)
    nome = str(nome).strip() if nome else ""
    if pid is None and not nome:
        return None
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if pid is not None:
                cursor.execute(
                    "SELECT id, nome, preco FROM planos_assinatura WHERE id = %s AND (ativo = 1 OR ativo IS NULL)",
                    (pid,))
            else:
                cursor.execute(
                    "SELECT id, nome, preco FROM planos_assinatura "
                    "WHERE LOWER(TRIM(nome)) = LOWER(%s) AND (ativo = 1 OR ativo IS NULL)",
                    (nome,))
            return cursor.fetchone()
    finally:
        conn.close()


def cancelar_no_gateway(gw_id):
    """Cancela a cobrança recorrente no Mercado Pago (melhor esforço)."""
    if not gw_id:
        return True
    try:
        resp = sdk.preapproval().update(gw_id, {"status": "cancelled"})
        return resp.get("status") in (200, 201)
    except Exception as e:
        app.logger.warning("Falha ao cancelar assinatura %s no gateway: %s", gw_id, e)
        return False


def ativar_por_pagamento(info):
    """
    Ativa o plano a partir de um pagamento APROVADO no Mercado Pago.
    Confere valor pago >= preço do plano e é idempotente (cada pagamento vale uma única vez).
    """
    if not info or info.get("status") != "approved":
        return False
    meta = info.get("metadata") or {}
    cliente_id = parse_int(meta.get("cliente_id"), 1)
    pagamento_id = str(info.get("id") or "")
    if cliente_id is None or not pagamento_id:
        return False

    plano = buscar_plano(nome=meta.get("nome_plano"))
    if not plano:
        app.logger.warning("Pagamento %s: plano não encontrado", pagamento_id)
        return False
    pago = parse_decimal(info.get("transaction_amount"))
    if pago is None or pago < plano["preco"]:
        app.logger.warning("Pagamento %s: valor pago (%s) menor que o plano (%s)", pagamento_id, pago, plano["preco"])
        return False

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO pagamentos_processados (pagamento_id, cliente_id) VALUES (%s, %s)",
                    (pagamento_id, cliente_id))
            except pymysql.err.IntegrityError:
                return True  # já processado antes
        try:
            ativar_assinatura_banco(cliente_id, plano["nome"], plano["preco"])
        except Exception as e:
            app.logger.error("Falha ao ativar assinatura do pagamento %s: %s", pagamento_id, e)
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM pagamentos_processados WHERE pagamento_id = %s", (pagamento_id,))
            return False
        return True
    finally:
        conn.close()


def validar_assinatura_webhook():
    """Valida o cabeçalho x-signature enviado pelo Mercado Pago (HMAC-SHA256)."""
    if not MERCADO_PAGO_WEBHOOK_SECRET:
        return False
    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")
    partes = dict(p.strip().split("=", 1) for p in x_signature.split(",") if "=" in p)
    ts, v1 = partes.get("ts"), partes.get("v1")
    if not ts or not v1:
        return False
    corpo = request.get_json(silent=True) or {}
    data_id = request.args.get("data.id") or (corpo.get("data") or {}).get("id") or ""
    manifesto = f"id:{str(data_id).lower()};request-id:{x_request_id};ts:{ts};"
    esperado = hmac.new(MERCADO_PAGO_WEBHOOK_SECRET.encode("utf-8"), manifesto.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, v1)


@app.route("/api/pagamento/cartao", methods=["POST"])
@rate_limit(10, 300, "pagamento")
def processar_pagamento_cartao():
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "mensagem": "Faça login para assinar um plano."}), 401

    dados = request.get_json(silent=True) or {}
    token_cartao = dados.get("token")
    email = str(dados.get("email") or "").strip()
    cpf = re.sub(r"\D", "", str(dados.get("cpf") or ""))

    if not token_cartao or not email or not cpf:
        return jsonify({"sucesso": False, "mensagem": "Dados de pagamento incompletos. Informe o cartão, e-mail e CPF."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"sucesso": False, "mensagem": "E-mail inválido."}), 400
    if not cpf_valido(cpf):
        return jsonify({"sucesso": False, "mensagem": "CPF inválido."}), 400

    # O preço vem do catálogo no servidor; qualquer 'valor' enviado pelo navegador é ignorado
    plano = buscar_plano(plano_id=dados.get("plano_id"), nome=dados.get("nome_plano"))
    if not plano:
        return jsonify({"sucesso": False, "mensagem": "Plano não encontrado."}), 400
    nome_plano = plano["nome"]
    valor = float(plano["preco"])

    preapproval_data = {
        "payer_email": email,
        "back_url": f"{PUBLIC_BASE_URL}/minha-assinatura",
        "reason": f"Assinatura {nome_plano} - Barbearia Versati",
        "external_reference": str(cliente_id),
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": valor,
            "currency_id": "BRL"
        },
        "card_token_id": token_cartao,
        "status": "authorized"
    }

    try:
        preapproval_response = sdk.preapproval().create(preapproval_data)
        response_data = preapproval_response.get("response", {})
        status_sub = response_data.get("status")

        if preapproval_response.get("status") in [200, 201] and status_sub == "authorized":
            subscription_id = response_data.get("id")
            data_inicio = datetime.now().date()
            data_renovacao = data_inicio + timedelta(days=30)

            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT id, gateway_subscription_id FROM assinaturas WHERE cliente_id = %s", (cliente_id,))
                    existente = cursor.fetchone()

                    if existente:
                        antigo = existente.get("gateway_subscription_id")
                        if antigo and antigo != subscription_id:
                            cancelar_no_gateway(antigo)  # evita cobrança dupla
                        cursor.execute("""
                            UPDATE assinaturas
                            SET nome_plano = %s, preco = %s, status = 'ativo',
                                data_inicio = %s, data_renovacao = %s,
                                gateway_subscription_id = %s
                            WHERE cliente_id = %s
                        """, (nome_plano, valor, data_inicio, data_renovacao, subscription_id, cliente_id))
                    else:
                        cursor.execute("""
                            INSERT INTO assinaturas
                            (cliente_id, nome_plano, preco, status, data_inicio, data_renovacao, gateway_subscription_id)
                            VALUES (%s, %s, %s, 'ativo', %s, %s, %s)
                        """, (cliente_id, nome_plano, valor, data_inicio, data_renovacao, subscription_id))
                    conn.commit()
            finally:
                conn.close()

            return jsonify({
                "sucesso": True,
                "mensagem": "Assinatura contratada com sucesso!",
                "subscription_id": subscription_id,
                "renovacao": data_renovacao.strftime("%d/%m/%Y")
            }), 200

        app.logger.warning("Cartão recusado (cliente %s): %s", cliente_id, response_data.get("status_detail") or response_data.get("message"))
        return jsonify({"sucesso": False, "mensagem": "Pagamento recusado pela operadora do cartão."}), 400

    except Exception as e:
        app.logger.error("Erro em processar_pagamento_cartao: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500


@app.route('/api/admin/cancelar-assinatura', methods=['POST'])
@admin_required
def admin_cancelar_assinatura():
    dados = request.get_json(silent=True) or {}
    assinatura_id = parse_int(dados.get('assinatura_id'), 1)

    if not assinatura_id:
        return jsonify({'sucesso': False, 'mensagem': 'ID não informado.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT gateway_subscription_id FROM assinaturas WHERE id = %s", (assinatura_id,))
            sub = cursor.fetchone()
            if not sub:
                return jsonify({'sucesso': False, 'mensagem': 'Assinatura não encontrada.'}), 404

            # Cancela também a cobrança recorrente, senão o cliente continua sendo cobrado
            gateway_ok = cancelar_no_gateway(sub.get('gateway_subscription_id'))
            cursor.execute("UPDATE assinaturas SET status = 'cancelado' WHERE id = %s", (assinatura_id,))
            conn.commit()

            msg = 'Assinatura cancelada com sucesso!'
            if not gateway_ok:
                msg += ' Atenção: não foi possível cancelar a cobrança no Mercado Pago; confira no painel deles.'
            return jsonify({'sucesso': True, 'mensagem': msg}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em admin_cancelar_assinatura: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


# ==============================================================================
# ROTAS DE PLANOS DE ASSINATURA (CATÁLOGO — NOME/PREÇO/DESCRIÇÃO)
# ==============================================================================
# ==============================================================================
# ROTAS DE PLANOS DE ASSINATURA (CATÁLOGO — NOME/PREÇO/DESCRIÇÃO)
# ==============================================================================

# ==============================================================================
# ROTAS DE PLANOS DE ASSINATURA (CATÁLOGO — NOME/PREÇO/DESCRIÇÃO)
# ==============================================================================

@app.route('/api/planos', methods=['GET'])
def listar_planos_site():
    """Rota consumida pelo frontend web para obter todos os planos ativos."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Aceita ativo = 1 ou NULL para garantir que novos planos criados apareçam
            cursor.execute(
                "SELECT id, nome, descricao, preco, ordem FROM planos_assinatura "
                "WHERE ativo = 1 OR ativo IS NULL "
                "ORDER BY ordem ASC, preco ASC"
            )
            planos = cursor.fetchall()
            return jsonify({'sucesso': True, 'planos': planos}), 200
    except Exception as e:
        app.logger.error("Erro em listar_planos_site: %s", e)
        return jsonify({'sucesso': False, 'planos': [], 'mensagem': 'Erro interno.'}), 500
    finally:
        conn.close()
# ==============================================================================
# CONSULTA DE ASSINATURA E CARTÕES DO CLIENTE (PARA O MODAL DO SITE)
# ==============================================================================

@app.route("/api/minha-assinatura", methods=["GET"])
def api_minha_assinatura():
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "tem_assinatura": False, "mensagem": "Não autenticado"}), 401

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id, 
                    nome_plano, 
                    preco, 
                    status,
                    data_inicio,
                    data_renovacao
                FROM assinaturas 
                WHERE cliente_id = %s AND LOWER(status) = 'ativo'
                ORDER BY id DESC LIMIT 1
            """, (int(cliente_id),))
            assinatura = cursor.fetchone()

        if assinatura:
            # Formata o preço de forma segura
            val_preco = float(assinatura.get("preco") or 0.0)
            preco_fmt = f"R$ {val_preco:.2f}".replace('.', ',')

            # Formata as datas directamente no Python sem conflito com o PyMySQL
            dt_inicio = assinatura.get("data_inicio")
            inicio_fmt = dt_inicio.strftime("%d/%m/%Y") if hasattr(dt_inicio, "strftime") else str(dt_inicio or "--/--/----")

            dt_renovacao = assinatura.get("data_renovacao")
            renovacao_fmt = dt_renovacao.strftime("%d/%m/%Y") if hasattr(dt_renovacao, "strftime") else str(dt_renovacao or "--/--/----")

            return jsonify({
                "sucesso": True,
                "tem_assinatura": True,
                "assinatura": {
                    "id": assinatura.get("id"),
                    "plano": str(assinatura.get("nome_plano") or "Plano"),
                    "preco": preco_fmt,
                    "inicio": inicio_fmt,
                    "renovacao": renovacao_fmt
                }
            }), 200
        else:
            return jsonify({
                "sucesso": True,
                "tem_assinatura": False
            }), 200
    except Exception as e:
        app.logger.error("Erro detalhado em api_minha_assinatura: %s", str(e))
        return jsonify({"sucesso": False, "tem_assinatura": False, "mensagem": "Erro interno."}), 500
    finally:
        conn.close()


@app.route("/api/meus-cartoes", methods=["GET"])
def api_meus_cartoes():
    """Rota consumida pelo modal para listar os cartões guardados."""
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "cartoes": []}), 401

    # Devolve lista vazia caso ainda não tenha tabela de cartões guardados, evitando erro 404
    return jsonify({"sucesso": True, "cartoes": []}), 200
@app.route("/minha-assinatura", methods=["GET"])
def pagina_minha_assinatura():
    if "cliente_id" not in session:
        return redirect(url_for("login"))

    cliente_id = session["cliente_id"]
    conn = get_db_connection()
    assinaturas = []
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    a.id,
                    a.nome_plano,
                    a.preco,
                    a.status,
                    DATE_FORMAT(a.data_inicio, '%d/%m/%Y') AS data_inicio,
                    DATE_FORMAT(a.data_renovacao, '%d/%m/%Y') AS validade
                FROM assinaturas a
                WHERE a.cliente_id = %s
                ORDER BY a.id DESC
            """, (cliente_id,))
            assinaturas = cursor.fetchall()
    except Exception as e:
        app.logger.error("Erro em pagina_minha_assinatura: %s", e)
    finally:
        conn.close()

    return render_template(
        "gerenciar_assinaturas.html",
        assinaturas=assinaturas,
        cliente_nome=session.get("cliente_nome")
    )

@app.route('/api/admin/planos', methods=['GET', 'POST'])
@admin_required
def gerenciar_planos_catalogo():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = (data.get('nome') or '').strip()
                descricao = (data.get('descricao') or '').strip()
                preco = parse_decimal(data.get('preco', 0))
                ordem = parse_int(data.get('ordem', 0), 0, 10000)

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400
                if preco is None or ordem is None or len(nome) > 150 or len(descricao) > 255:
                    return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos (nome, descrição, preço ou ordem).'}), 400

                # Força explicitamente ativo = 1 na inserção
                cursor.execute(
                    "INSERT INTO planos_assinatura (nome, descricao, preco, ordem, ativo) VALUES (%s, %s, %s, %s, 1)",
                    (nome, descricao, preco, ordem)
                )
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Plano cadastrado!', 'id': cursor.lastrowid}), 201

            cursor.execute(
                "SELECT id, nome, descricao, preco, ordem, ativo FROM planos_assinatura ORDER BY ordem ASC, preco ASC"
            )
            planos = cursor.fetchall()
            return jsonify({'sucesso': True, 'planos': planos}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em gerenciar_planos_catalogo: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


@app.route('/api/admin/planos/<int:plano_id>', methods=['PUT', 'DELETE'])
@admin_required
def editar_ou_remover_plano_catalogo(plano_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'DELETE':
                cursor.execute("DELETE FROM planos_assinatura WHERE id = %s", (plano_id,))
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Plano removido!'}), 200

            data = request.get_json() or {}
            campos, valores, invalido = montar_update(data, {
                'nome': conv_texto(150, obrigatorio=True), 'descricao': conv_texto(255),
                'preco': conv_decimal(), 'ordem': conv_inteiro(0, 10000), 'ativo': conv_bool,
            })
            if invalido:
                return jsonify({'sucesso': False, 'mensagem': f"Valor inválido para '{invalido}'."}), 400
            if not campos:
                return jsonify({'sucesso': False, 'mensagem': 'Nada para atualizar.'}), 400

            valores.append(plano_id)
            cursor.execute(f"UPDATE planos_assinatura SET {', '.join(campos)} WHERE id = %s", valores)
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Plano atualizado!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em editar_ou_remover_plano_catalogo: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


def barbeiro_realiza_servico(cursor, barbeiro_id, servico_nome):
    """False só quando o admin desmarcou "Realiza" desse serviço para o barbeiro (sem configuração = realiza)."""
    cursor.execute(
        """
        SELECT bs.realiza
        FROM servicos s
        LEFT JOIN barbeiro_servicos bs ON bs.servico_id = s.id AND bs.barbeiro_id = %s
        WHERE LOWER(TRIM(s.nome)) = LOWER(TRIM(%s))
        """,
        (barbeiro_id, servico_nome),
    )
    linha = cursor.fetchone()
    return not (linha and linha["realiza"] is not None and int(linha["realiza"]) == 0)


@app.route('/api/servicos', methods=['GET'])
def listar_servicos_site():
    """Serviços do site. Com ?barbeiro_id=N lista só o que esse barbeiro realiza."""
    bruto = (request.args.get("barbeiro_id") or "").strip()
    barbeiro_id = None
    if bruto:
        barbeiro_id = parse_int(bruto, 1)
        if barbeiro_id is None:
            return jsonify({'sucesso': False, 'servicos': [], 'mensagem': 'Profissional inválido.'}), 400

    juncao = ""
    filtro = ""
    params = ()
    if barbeiro_id is not None:
        juncao = "LEFT JOIN barbeiro_servicos bs ON bs.servico_id = s.id AND bs.barbeiro_id = %s"
        filtro = "WHERE bs.realiza IS NULL OR bs.realiza = 1"
        params = (barbeiro_id,)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    f"SELECT s.id, s.nome, s.preco, s.categoria, IFNULL(s.foto, '') AS foto "
                    f"FROM servicos s {juncao} {filtro} ORDER BY s.categoria ASC, s.nome ASC",
                    params,
                )
                servicos = cursor.fetchall()
            except Exception:
                cursor.execute(
                    f"SELECT s.id, s.nome, s.preco, s.categoria "
                    f"FROM servicos s {juncao} {filtro} ORDER BY s.categoria ASC, s.nome ASC",
                    params,
                )
                servicos = cursor.fetchall()
                for s in servicos:
                    s['foto'] = ''

            return jsonify({'sucesso': True, 'servicos': servicos}), 200
    except Exception as e:
        app.logger.error("Erro em listar_servicos_site: %s", e)
        return jsonify({'sucesso': False, 'servicos': [], 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()

@app.route("/api/admin/agendamento/<int:id>/concluir", methods=["POST"])
@admin_required
def api_concluir_agendamento(id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE agendamentos SET status = 'concluido', concluido_em = %s WHERE id = %s",
                (datetime.now(), id),
            )
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Atendimento concluído com sucesso!"}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_concluir_agendamento: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()

@app.route("/api/admin/financeiro", methods=["GET"])
@admin_required
def api_admin_financeiro():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS total_cortes, 
                       IFNULL(SUM(preco), 0) AS valor_total 
                FROM agendamentos 
                WHERE LOWER(status) = 'concluido'
            """)
            resultado = cursor.fetchone()

        return jsonify({
            "sucesso": True,
            "total_cortes": resultado['total_cortes'],
            "valor_total": float(resultado['valor_total'])
        }), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_financeiro: %s", e)
        return jsonify({"sucesso": False, "total_cortes": 0, "valor_total": 0.0, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()

@app.route("/api/admin/agenda-equipe", methods=["GET"])
@admin_required
def api_admin_agenda_equipe():
    if request.method == 'OPTIONS':
        return "", 200
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Adicionado IFNULL(foto_url, '') AS foto_url
            cursor.execute("SELECT id, nome, cargo, especialidade, telefone, IFNULL(foto_url, '') AS foto_url FROM barbeiros WHERE ativo = 1 ORDER BY id ASC")
            barbeiros = cursor.fetchall()

            cursor.execute("""
                SELECT DISTINCT a.id, a.barbeiro_id, 
                        IFNULL(a.profissional, '') AS profissional, 
                        a.data, a.horario, a.servico, 
                        IFNULL(a.tipo_pagamento, 'presencial') AS tipo_pagamento, 
                        IFNULL(a.status, 'Confirmado') AS status, 
                        COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome, 
                        IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE (a.status IS NULL OR (LOWER(a.status) != 'cancelado' AND LOWER(a.status) != 'concluido'))
                ORDER BY a.data ASC, a.horario ASC
            """)
            agendamentos_totais = cursor.fetchall()

            agora = datetime.now()
            hoje_str = agora.strftime("%Y-%m-%d")
            hora_atual_str = agora.strftime("%H:%M")

            agendamentos_filtrados = []
            for item in agendamentos_totais:
                data_val = item.get("data")
                if data_val:
                    if hasattr(data_val, "strftime"):
                        item["data"] = data_val.strftime("%Y-%m-%d")
                    else:
                        item["data"] = str(data_val)
                else:
                    item["data"] = ""

                data_ag = item["data"]
                hora_ag = str(item.get("horario", "00:00"))

                if data_ag > hoje_str or (data_ag == hoje_str and hora_ag >= hora_atual_str):
                    agendamentos_filtrados.append(item)

            resultado = []
            for b in barbeiros:
                b_id = b["id"]
                b_nome = str(b["nome"]).strip().lower()

                agendamentos_barbeiro = []
                ids_adicionados = set()

                for ag in agendamentos_filtrados:
                    ag_id = ag.get("id")
                    ag_b_id = ag.get("barbeiro_id")
                    ag_prof = str(ag.get("profissional", "")).strip().lower()

                    if ag_id not in ids_adicionados:
                        if (ag_b_id is not None and int(ag_b_id) == int(b_id)) or (b_nome in ag_prof):
                            agendamentos_barbeiro.append(ag)
                            ids_adicionados.add(ag_id)

                resultado.append({
                    "barbeiro": b,
                    "agendamentos": agendamentos_barbeiro
                })

            return jsonify({"sucesso": True, "equipe_agenda": resultado}), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_agenda_equipe: %s", e)
        return jsonify({"sucesso": False, "equipe_agenda": [], "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


@app.route("/api/admin/historico", methods=["GET"])
@admin_required
def api_admin_historico():
    data_filtro = request.args.get("data", datetime.now().strftime("%Y-%m-%d"))
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, 
                       a.tipo_pagamento, a.preco, a.status,
                       COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome, 
                       IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE DATE(a.data) = %s AND LOWER(a.status) = 'concluido'
                ORDER BY a.horario ASC
            """, (data_filtro,))
            historico = cursor.fetchall()

            for item in historico:
                if item.get("data") and hasattr(item["data"], "strftime"):
                    item["data"] = item["data"].strftime("%Y-%m-%d")
                else:
                    item["data"] = str(item.get("data", ""))[:10]

        return jsonify({"sucesso": True, "historico": historico}), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_historico: %s", e)
        return jsonify({"sucesso": False, "historico": [], "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()

@app.route('/api/barbeiros/<int:barbeiro_id>/agendamentos', methods=['GET'])
def api_agendamentos_por_barbeiro(barbeiro_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.id, a.data, a.horario, a.servico, a.status, a.tipo_pagamento,
                       COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome, IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE a.barbeiro_id = %s 
                  AND (a.status IS NULL OR LOWER(a.status) != 'cancelado')
                ORDER BY a.data ASC, a.horario ASC
                """,
                (barbeiro_id,)
            )
            agendamentos = cursor.fetchall()
            
            for item in agendamentos:
                if hasattr(item["data"], 'strftime'):
                    item["data"] = item["data"].strftime("%Y-%m-%d")
                else:
                    item["data"] = str(item["data"])
                
            if not _token_admin_valido():
                # Público: apenas os horários ocupados, sem nome/telefone/serviço do cliente
                agendamentos = [
                    {"id": a["id"], "data": a["data"], "horario": a["horario"], "status": a["status"]}
                    for a in agendamentos
                ]
            return jsonify({"sucesso": True, "agendamentos": agendamentos}), 200
    except Exception as e:
        app.logger.error("Erro em api_agendamentos_por_barbeiro: %s", e)
        return jsonify({"sucesso": False, "agendamentos": [], "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


def cliente_tem_assinatura_ativa(cliente_id):
    """Verifica no MySQL se o cliente possui uma assinatura ativa e no prazo."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT id FROM assinaturas 
                WHERE cliente_id = %s 
                  AND LOWER(status) = 'ativo' 
                  AND data_renovacao >= CURDATE()
                LIMIT 1
            """
            cursor.execute(sql, (cliente_id,))
            return cursor.fetchone() is not None
    finally:
        conn.close()


def ativar_assinatura_banco(cliente_id, nome_plano, preco=0.0):
    """Ativa ou renova a assinatura do cliente diretamente no banco de dados MySQL."""
    data_inicio = datetime.now().date()
    data_renovacao = data_inicio + timedelta(days=30)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM assinaturas WHERE cliente_id = %s", (cliente_id,)
            )
            existente = cursor.fetchone()

            if existente:
                sql = """
                    UPDATE assinaturas 
                    SET nome_plano = %s, preco = %s, status = 'ativo', data_inicio = %s, data_renovacao = %s
                    WHERE cliente_id = %s
                """
                cursor.execute(
                    sql, (nome_plano, preco, data_inicio, data_renovacao, cliente_id)
                )
            else:
                sql = """
                    INSERT INTO assinaturas (cliente_id, nome_plano, preco, status, data_inicio, data_renovacao)
                    VALUES (%s, %s, %s, 'ativo', %s, %s)
                """
                cursor.execute(
                    sql, (cliente_id, nome_plano, preco, data_inicio, data_renovacao)
                )

            conn.commit()
    finally:
        conn.close()


@app.route('/api/admin/barbeiros', methods=['GET', 'POST', 'OPTIONS'])
@admin_required
def gerenciar_barbeiros():
    if request.method == 'OPTIONS':
        return "", 200
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = data.get('nome')
                cargo = data.get('cargo', 'Barbeiro')
                especialidade = data.get('especialidade', 'Cortes em Geral')
                telefone = data.get('telefone', '')
                apelido = data.get('apelido', '')
                email = data.get('email', '')
                nivel_acesso = data.get('nivel_acesso', 'Atendente')
                foto_url = (data.get('foto_url') or '').strip()
                exibir_agenda = 1 if data.get('exibir_agenda', True) else 0
                ver_todas_agendas = 1 if data.get('ver_todas_agendas', False) else 0

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400
                if not isinstance(nome, str) or len(nome) > 100 or not validar_foto(foto_url):
                    return jsonify({'sucesso': False, 'mensagem': 'Nome ou foto inválidos.'}), 400

                cursor.execute(
                    """INSERT INTO barbeiros
                       (nome, cargo, especialidade, telefone, apelido, email, nivel_acesso, foto_url, exibir_agenda, ver_todas_agendas)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (nome, cargo, especialidade, telefone, apelido, email, nivel_acesso, foto_url, exibir_agenda, ver_todas_agendas)
                )
                novo_id = cursor.lastrowid
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Barbeiro cadastrado!', 'id': novo_id}), 201

            incluir_inativos = request.args.get('incluir_inativos') == '1'
            filtro_ativo = "" if incluir_inativos else "WHERE ativo = 1"
            cursor.execute(f"""
                SELECT id, nome, apelido, cargo, especialidade, nivel_acesso, telefone, email,
                       IFNULL(foto_url, '') AS foto_url, exibir_agenda, ver_todas_agendas, ativo
                FROM barbeiros {filtro_ativo} ORDER BY id ASC
            """)
            barbeiros = cursor.fetchall()
            return jsonify({'sucesso': True, 'barbeiros': barbeiros}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em gerenciar_barbeiros: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()

def barbearia_compativel(lista):
    return lista


@app.route('/api/admin/barbeiros/<int:barbeiro_id>', methods=['PUT', 'OPTIONS'])
@admin_required
def editar_barbeiro(barbeiro_id):
    if request.method == 'OPTIONS':
        return "", 200
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            data = request.get_json() or {}
            nome = data.get('nome')
            if not nome:
                return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

            cargo = data.get('cargo', 'Barbeiro')
            especialidade = data.get('especialidade', 'Cortes em Geral')
            telefone = data.get('telefone', '')
            apelido = data.get('apelido', '')
            email = data.get('email', '')
            nivel_acesso = data.get('nivel_acesso', 'Atendente')
            foto_url = (data.get('foto_url') or '').strip()
            exibir_agenda = 1 if data.get('exibir_agenda', True) else 0
            ver_todas_agendas = 1 if data.get('ver_todas_agendas', False) else 0

            if not isinstance(nome, str) or len(nome) > 100 or not validar_foto(foto_url):
                return jsonify({'sucesso': False, 'mensagem': 'Nome ou foto inválidos.'}), 400

            cursor.execute(
                """UPDATE barbeiros SET
                       nome = %s, cargo = %s, especialidade = %s, telefone = %s,
                       apelido = %s, email = %s, nivel_acesso = %s, foto_url = %s,
                       exibir_agenda = %s, ver_todas_agendas = %s
                   WHERE id = %s""",
                (nome, cargo, especialidade, telefone, apelido, email, nivel_acesso,
                 foto_url, exibir_agenda, ver_todas_agendas, barbeiro_id)
            )
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Colaborador atualizado com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em editar_barbeiro: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


@app.route('/api/admin/barbeiros/<int:barbeiro_id>', methods=['DELETE', 'OPTIONS'])
@admin_required
def deletar_barbeiro(barbeiro_id):
    if request.method == 'OPTIONS':
        return "", 200
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM barbeiros WHERE id = %s", (barbeiro_id,))
            if not cursor.fetchone():
                return jsonify({'sucesso': False, 'mensagem': 'Barbeiro não encontrado.'}), 404

            # Exclusão "suave": o barbeiro sai da equipe, mas os atendimentos já feitos
            # (e o financeiro/comissões) continuam no banco.
            cursor.execute("UPDATE barbeiros SET ativo = 0 WHERE id = %s", (barbeiro_id,))

            # Cancela só o que ainda não aconteceu (pendente/confirmado de hoje em diante).
            # Concluídos e cancelados antigos não são tocados.
            cursor.execute(
                """UPDATE agendamentos SET status = 'cancelado'
                   WHERE barbeiro_id = %s
                     AND data >= CURDATE()
                     AND (status IS NULL OR LOWER(status) NOT IN ('concluido', 'finalizado', 'cancelado'))""",
                (barbeiro_id,)
            )

            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Removido com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em deletar_barbeiro: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


DIAS_SEMANA_NOMES = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado']




@app.route('/api/produtos', methods=['GET'])
def listar_produtos_site():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    "SELECT id, nome, descricao, preco, estoque FROM produtos WHERE ativo = 1 ORDER BY nome ASC"
                )
            except Exception:
                cursor.execute(
                    "SELECT id, nome, categoria AS descricao, preco, estoque FROM produtos WHERE ativo = 1 ORDER BY nome ASC"
                )
            produtos = cursor.fetchall()
            return jsonify({'sucesso': True, 'produtos': produtos}), 200
    finally:
        conn.close()

@app.route('/api/admin/produtos', methods=['GET', 'POST'])
@admin_required
def gerenciar_produtos():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = str(data.get('nome') or '').strip()
                descricao = str(data.get('descricao') or 'Cuidados profissionais').strip()
                preco = parse_decimal(data.get('preco', 0))
                estoque = parse_int(data.get('estoque', 0), 0, 100000)
                foto = str(data.get('foto') or '').strip()

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400
                if (preco is None or estoque is None or len(nome) > 150 or len(descricao) > 255
                        or not validar_foto(foto)):
                    return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos (preço, estoque, nome ou foto).'}), 400

                cursor.execute(
                    "INSERT INTO produtos (nome, descricao, preco, estoque, foto) VALUES (%s, %s, %s, %s, %s)",
                    (nome, descricao, preco, estoque, foto)
                )
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Produto cadastrado!', 'id': cursor.lastrowid}), 201

            cursor.execute(
                "SELECT id, nome, descricao, preco, estoque, IFNULL(foto, '') AS foto FROM produtos WHERE ativo = 1 ORDER BY nome ASC"
            )
            produtos = cursor.fetchall()
            return jsonify({'sucesso': True, 'produtos': produtos}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em gerenciar_produtos: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


@app.route('/api/admin/produtos/<int:produto_id>', methods=['PUT', 'DELETE'])
@admin_required
def editar_ou_remover_produto(produto_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'DELETE':
                cursor.execute("DELETE FROM produtos WHERE id = %s", (produto_id,))
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Produto removido!'}), 200

            data = request.get_json() or {}
            campos, valores, invalido = montar_update(data, {
                'nome': conv_texto(150, obrigatorio=True), 'descricao': conv_texto(255),
                'preco': conv_decimal(), 'estoque': conv_inteiro(0, 100000),
                'foto': conv_foto, 'ativo': conv_bool,
            })
            if invalido:
                return jsonify({'sucesso': False, 'mensagem': f"Valor inválido para '{invalido}'."}), 400
            if not campos:
                return jsonify({'sucesso': False, 'mensagem': 'Nada para atualizar.'}), 400

            valores.append(produto_id)
            cursor.execute(f"UPDATE produtos SET {', '.join(campos)} WHERE id = %s", valores)
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Produto atualizado!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em editar_ou_remover_produto: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


@app.route('/api/combos', methods=['GET'])
def listar_combos_site():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id, nome, tipo, descricao, sessoes, preco, desconto_percentual
                   FROM combos WHERE ativo = 1 ORDER BY id DESC"""
            )
            combos = cursor.fetchall()
            return jsonify({'sucesso': True, 'combos': combos}), 200
    finally:
        conn.close()

@app.route('/api/admin/combos', methods=['GET', 'POST'])
@admin_required
def gerenciar_combos():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = str(data.get('nome') or '').strip()
                tipo = str(data.get('tipo') or 'servico').strip()
                descricao = str(data.get('descricao') or '').strip()
                sessoes = parse_int(data.get('sessoes', 1), 1, 1000)
                preco = parse_decimal(data.get('preco', 0))
                desconto_percentual = parse_decimal(data.get('desconto_percentual', 0), 0, 100)

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400
                if (sessoes is None or preco is None or desconto_percentual is None or len(nome) > 150
                        or len(tipo) > 20 or len(descricao) > 255):
                    return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos do combo.'}), 400

                cursor.execute(
                    """INSERT INTO combos (nome, tipo, descricao, sessoes, preco, desconto_percentual)
                        VALUES (%s, %s, %s, %s, %s, %s)""",
                    (nome, tipo, descricao, sessoes, preco, desconto_percentual)
                )
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Combo cadastrado!', 'id': cursor.lastrowid}), 201

            cursor.execute(
                """SELECT id, nome, tipo, descricao, sessoes, preco, desconto_percentual
                   FROM combos WHERE ativo = 1 ORDER BY id DESC"""
            )
            combos = cursor.fetchall()
            return jsonify({'sucesso': True, 'combos': combos}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em gerenciar_combos: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()





@app.route('/api/admin/combos/<int:combo_id>', methods=['DELETE'])
@admin_required
def remover_combo(combo_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM combos WHERE id = %s", (combo_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Combo removido!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em remover_combo: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


@app.route('/api/admin/servicos', methods=['GET', 'POST'])
@admin_required
def gerenciar_servicos():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = (data.get('nome') or '').strip()
                preco = data.get('preco', 0)
                categoria = (data.get('categoria') or 'Geral').strip()
                foto = (data.get('foto') or '').strip()

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400
                preco = parse_decimal(preco)
                if preco is None or len(nome) > 150 or len(categoria) > 80 or not validar_foto(foto):
                    return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos (preço, nome ou foto).'}), 400

                cursor.execute(
                    """INSERT INTO servicos (nome, preco, categoria, foto) VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE preco = VALUES(preco), categoria = VALUES(categoria), foto = VALUES(foto)""",
                    (nome, preco, categoria, foto)
                )
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Serviço salvo com sucesso!'}), 201

            cursor.execute("SELECT id, nome, preco, categoria, foto FROM servicos ORDER BY categoria ASC, nome ASC")
            servicos = cursor.fetchall()
            return jsonify({'sucesso': True, 'servicos': servicos}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em gerenciar_servicos: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()

@app.route("/api/pagamento/pix", methods=["POST"])
@rate_limit(10, 300, "pagamento")
def processar_pagamento_pix():
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "mensagem": "Faça login para assinar um plano."}), 401

    dados = request.get_json(silent=True) or {}
    email = str(dados.get("email") or "").strip()
    cpf = re.sub(r"\D", "", str(dados.get("cpf") or ""))
    nome = str(dados.get("nome") or "Cliente").strip()[:60]

    if not email or not cpf:
        return jsonify({"sucesso": False, "mensagem": "E-mail e CPF são obrigatórios para gerar o PIX."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"sucesso": False, "mensagem": "E-mail inválido."}), 400
    if not cpf_valido(cpf):
        return jsonify({"sucesso": False, "mensagem": "CPF inválido."}), 400

    # O preço vem do catálogo no servidor; qualquer 'valor' enviado pelo navegador é ignorado
    plano = buscar_plano(plano_id=dados.get("plano_id"), nome=dados.get("nome_plano"))
    if not plano:
        return jsonify({"sucesso": False, "mensagem": "Plano não encontrado."}), 400
    nome_plano = plano["nome"]
    valor = float(plano["preco"])

    payment_data = {
        "transaction_amount": valor,
        "description": f"Assinatura {nome_plano} - Barbearia Versati",
        "payment_method_id": "pix",
        "external_reference": str(cliente_id),
        "payer": {
            "email": email,
            "first_name": nome,
            "identification": {"type": "CPF", "number": cpf},
        },
        "metadata": {
            "cliente_id": int(cliente_id),
            "nome_plano": nome_plano,
            "preco": valor,
        },
    }
    if PUBLIC_BASE_URL.startswith("https://"):
        payment_data["notification_url"] = f"{PUBLIC_BASE_URL}/api/webhook"

    try:
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response.get("response", {})

        if payment_response.get("status") not in [200, 201]:
            app.logger.warning("Mercado Pago recusou a criação do PIX: %s", payment.get("message"))
            return jsonify({"sucesso": False, "mensagem": "Não foi possível gerar o PIX. Tente novamente."}), 400

        poi = payment.get("point_of_interaction", {}) or {}
        trans_data = poi.get("transaction_data", {}) or {}

        return jsonify({
            "sucesso": True,
            "pagamento_id": payment.get("id"),
            "qr_code_copia_e_cola": trans_data.get("qr_code"),
            "qr_code_imagem_base64": f"data:image/jpeg;base64,{trans_data.get('qr_code_base64')}" if trans_data.get("qr_code_base64") else None,
        }), 200

    except Exception as e:
        app.logger.error("Erro em processar_pagamento_pix: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500


@app.route("/api/pagamento/status/<int:pagamento_id>", methods=["GET"])
def verificar_status_pagamento(pagamento_id):
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "mensagem": "Não autenticado"}), 401
    try:
        payment = sdk.payment().get(pagamento_id).get("response", {}) or {}
        # Só o dono do pagamento pode consultá-lo
        if str((payment.get("metadata") or {}).get("cliente_id")) != str(cliente_id):
            return jsonify({"sucesso": False, "mensagem": "Pagamento não encontrado."}), 404

        status_atual = payment.get("status")
        if status_atual == "approved":
            ativar_por_pagamento(payment)  # idempotente: ativa o plano uma única vez

        return jsonify({
            "sucesso": True,
            "status": status_atual,
            "aprovado": status_atual == "approved",
            "detalhe": payment.get("status_detail"),
        }), 200
    except Exception as e:
        app.logger.error("Erro em verificar_status_pagamento: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500


@app.route("/api/webhook", methods=["POST"])
def webhook_mercadopago():
    if not validar_assinatura_webhook():
        app.logger.warning("Webhook rejeitado: assinatura inválida (ip=%s)", request.remote_addr)
        return jsonify({"status": "unauthorized"}), 401

    dados = request.get_json(silent=True) or {}
    tipo_evento = request.args.get("type") or request.args.get("topic") or dados.get("type")
    data_id = request.args.get("data.id") or (dados.get("data") or {}).get("id")

    try:
        # Mensalidade recorrente cobrada ou pagamento avulso (Pix) aprovado
        if tipo_evento in ["subscription_authorized_payment", "payment"] and data_id and str(data_id).isdigit():
            info = sdk.payment().get(data_id).get("response", {}) or {}
            if info.get("status") == "approved":
                preapproval_id = (info.get("order") or {}).get("id") or info.get("subscription_id")

                if preapproval_id:
                    conn = get_db_connection()
                    try:
                        with conn.cursor() as cursor:
                            cursor.execute("""
                                UPDATE assinaturas
                                SET status = 'ativo',
                                    data_renovacao = DATE_ADD(CURDATE(), INTERVAL 30 DAY)
                                WHERE gateway_subscription_id = %s
                            """, (preapproval_id,))
                            conn.commit()
                    finally:
                        conn.close()
                else:
                    ativar_por_pagamento(info)

        # Assinatura pausada ou cancelada
        elif tipo_evento in ["subscription_preapproval", "preapproval"] and data_id:
            sub_info = sdk.preapproval().get(data_id).get("response", {}) or {}
            if sub_info.get("status") in ["cancelled", "paused"]:
                conn = get_db_connection()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            UPDATE assinaturas
                            SET status = 'cancelado'
                            WHERE gateway_subscription_id = %s
                        """, (str(data_id),))
                        conn.commit()
                finally:
                    conn.close()

    except Exception as e:
        app.logger.error("Erro no processamento do webhook: %s", e)

    return jsonify({"status": "ok"}), 200

@app.route("/api/assinaturas/cancelar/<int:assinatura_id>", methods=["POST"])
def cancelar_assinatura_cliente(assinatura_id):
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "mensagem": "Não autenticado"}), 401

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT gateway_subscription_id FROM assinaturas WHERE id = %s AND cliente_id = %s",
                (assinatura_id, cliente_id)
            )
            sub = cursor.fetchone()

            if not sub:
                return jsonify({"sucesso": False, "mensagem": "Assinatura não encontrada."}), 404

            gw_id = sub.get("gateway_subscription_id")
            # Cancela a cobrança recorrente no Mercado Pago
            if gw_id:
                try:
                    sdk.preapproval().update(gw_id, {"status": "cancelled"})
                except Exception as mp_err:
                    app.logger.warning("Falha ao cancelar no gateway: %s", mp_err)

            cursor.execute("UPDATE assinaturas SET status = 'cancelado' WHERE id = %s", (assinatura_id,))
            conn.commit()

        return jsonify({"sucesso": True, "mensagem": "Assinatura cancelada com sucesso!"}), 200
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
@rate_limit(10, 300, "login-api")
def api_login():
    dados = request.get_json(silent=True) or {}
    email = str(dados.get("email") or "").strip()
    senha = str(dados.get("senha") or "")

    if not email or not senha:
        return jsonify({"sucesso": False, "mensagem": "E-mail e senha obrigatórios!"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            colunas = "id, nome, email, senha, senha_cifrada" if _SENHA_COL_OK else "id, nome, email, senha"
            cursor.execute(f"SELECT {colunas} FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
    finally:
        conn.close()

    if _verificar_senha(usuario, senha):
        _guardar_senha_cifrada_no_login(usuario, senha)
        return jsonify({
            "sucesso": True,
            "mensagem": "Login realizado com sucesso!",
            "usuario": {"id": usuario["id"], "nome": usuario["nome"], "email": usuario["email"]},
        }), 200

    return jsonify({"sucesso": False, "mensagem": "E-mail ou senha incorretos!"}), 401


# ==============================================================================
# CADASTRO COM CONFIRMAÇÃO DE E-MAIL (código de 6 dígitos)
# ==============================================================================
CODIGO_VALIDADE_MIN = 10      # minutos até o código expirar
CODIGO_MAX_TENTATIVAS = 5     # erros permitidos por código
CODIGO_REENVIO_SEG = 60       # intervalo mínimo entre envios para o mesmo e-mail


def _agora_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_codigo(email, codigo):
    """O código nunca fica salvo em texto puro: guardamos só um HMAC dele."""
    chave = str(app.secret_key or "").encode("utf-8")
    msg = f"{email.strip().lower()}:{codigo}".encode("utf-8")
    return hmac.new(chave, msg, hashlib.sha256).hexdigest()


def _mascarar_email(email):
    usuario, _, dominio = email.partition("@")
    if len(usuario) <= 2:
        return f"{usuario[:1]}***@{dominio}"
    return f"{usuario[:2]}{'*' * min(len(usuario) - 2, 6)}@{dominio}"


def _enviar_email_codigo(email, nome, codigo, finalidade="cadastro"):
    """Envia o código via API HTTPS da Brevo (o Render grátis bloqueia SMTP)."""
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    remetente = os.environ.get("EMAIL_REMETENTE", "").strip()

    if not api_key or not remetente:
        if os.environ.get("EMAIL_CODIGO_NO_LOG", "").lower() == "true":
            # Só para testes locais: nunca ligue isso em produção.
            app.logger.warning("[TESTE] Código de verificação de %s: %s", email, codigo)
            return True
        app.logger.error("Envio de e-mail não configurado (BREVO_API_KEY / EMAIL_REMETENTE).")
        return False

    nome_remetente = os.environ.get("EMAIL_REMETENTE_NOME", "Barbearia Versati").strip() or "Barbearia Versati"
    nome_seguro = _html.escape(nome.split(" ")[0] if nome else "cliente")
    if finalidade == "redefinir":
        frase = "Use o código abaixo para redefinir a sua senha:"
        ignorar = "Se você não pediu para redefinir a senha, ignore este e-mail."
        assunto = f"{codigo} é seu código para redefinir a senha"
    else:
        frase = "Use o código abaixo para confirmar seu e-mail:"
        ignorar = "Se você não pediu este cadastro, ignore este e-mail."
        assunto = f"{codigo} é seu código de confirmação"
    html_corpo = (
        '<div style="font-family:Arial,sans-serif;max-width:420px;margin:auto;background:#111;'
        'color:#fff;padding:28px;border-radius:12px">'
        f'<h2 style="margin:0 0 12px;color:#e5243b">{_html.escape(nome_remetente)}</h2>'
        f'<p>Olá, {nome_seguro}! {frase}</p>'
        f'<p style="font-size:34px;font-weight:bold;letter-spacing:8px;margin:20px 0">{codigo}</p>'
        f'<p style="color:#aaa;font-size:13px">O código vale por {CODIGO_VALIDADE_MIN} minutos. '
        f'{ignorar}</p></div>'
    )
    texto = (
        f"Seu código é {codigo}. Ele vale por {CODIGO_VALIDADE_MIN} minutos. "
        f"{ignorar}"
    )

    for tentativa in (1, 2):
        try:
            resp = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": api_key, "accept": "application/json", "content-type": "application/json"},
                json={
                    "sender": {"name": nome_remetente, "email": remetente},
                    "to": [{"email": email, "name": nome or email}],
                    "subject": assunto,
                    "htmlContent": html_corpo,
                    "textContent": texto,
                },
                timeout=20,
            )
            if resp.status_code in (200, 201, 202):
                return True
            app.logger.error("Brevo recusou o envio (%s): %s", resp.status_code, resp.text[:300])
            if resp.status_code < 500:  # erro de configuração/credencial: repetir não adianta
                break
        except requests.RequestException as e:
            app.logger.error("Falha ao chamar a API de e-mail (tentativa %s): %s", tentativa, e)
    return False


def _segundos_de_espera(ultimo_envio, agora):
    return CODIGO_REENVIO_SEG - int((agora - ultimo_envio).total_seconds())


def _iniciar_verificacao_cadastro(nome, email, senha, telefone):
    """Valida o e-mail, guarda o cadastro como pendente e envia o código. Retorna (ok, mensagem, status)."""
    email = email.strip().lower()
    agora = _agora_utc()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
            if cursor.fetchone():
                return False, "E-mail já cadastrado!", 400

            cursor.execute("DELETE FROM cadastros_pendentes WHERE expira_em < %s", (agora - timedelta(days=1),))
            cursor.execute("SELECT ultimo_envio FROM cadastros_pendentes WHERE email = %s", (email,))
            pend = cursor.fetchone()
            if pend:
                espera = _segundos_de_espera(pend["ultimo_envio"], agora)
                if espera > 0:
                    return False, f"Aguarde {espera}s para pedir um novo código.", 429

            codigo = f"{secrets.randbelow(1_000_000):06d}"
            if not _enviar_email_codigo(email, nome, codigo):
                return False, "Não foi possível enviar o e-mail agora. Tente novamente em instantes.", 503

            cursor.execute(
                """INSERT INTO cadastros_pendentes
                       (email, nome, telefone, senha_hash, codigo_hash, expira_em, tentativas, ultimo_envio)
                   VALUES (%s, %s, %s, %s, %s, %s, 0, %s)
                   ON DUPLICATE KEY UPDATE
                       nome = VALUES(nome), telefone = VALUES(telefone), senha_hash = VALUES(senha_hash),
                       codigo_hash = VALUES(codigo_hash), expira_em = VALUES(expira_em),
                       tentativas = 0, ultimo_envio = VALUES(ultimo_envio)""",
                (email, nome, telefone, generate_password_hash(senha), _hash_codigo(email, codigo),
                 agora + timedelta(minutes=CODIGO_VALIDADE_MIN), agora),
            )
            if _SENHA_COL_OK:
                cursor.execute(
                    "UPDATE cadastros_pendentes SET senha_cifrada = %s WHERE email = %s",
                    (_cifrar_senha(senha), email),
                )
            conn.commit()
        return True, "Enviamos um código de 6 dígitos para o seu e-mail.", 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro ao iniciar verificação de cadastro: %s", e)
        return False, "Erro interno. Tente novamente.", 500
    finally:
        conn.close()


def _reenviar_codigo_cadastro(email):
    """Gera e envia um novo código para um cadastro pendente. Retorna (ok, mensagem, status)."""
    email = email.strip().lower()
    agora = _agora_utc()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT nome, ultimo_envio FROM cadastros_pendentes WHERE email = %s", (email,))
            pend = cursor.fetchone()
            if not pend:
                return False, "Cadastro não encontrado ou expirado. Faça o cadastro novamente.", 404
            espera = _segundos_de_espera(pend["ultimo_envio"], agora)
            if espera > 0:
                return False, f"Aguarde {espera}s para pedir um novo código.", 429

            codigo = f"{secrets.randbelow(1_000_000):06d}"
            if not _enviar_email_codigo(email, pend["nome"], codigo):
                return False, "Não foi possível enviar o e-mail agora. Tente novamente em instantes.", 503

            cursor.execute(
                """UPDATE cadastros_pendentes
                   SET codigo_hash = %s, expira_em = %s, tentativas = 0, ultimo_envio = %s
                   WHERE email = %s""",
                (_hash_codigo(email, codigo), agora + timedelta(minutes=CODIGO_VALIDADE_MIN), agora, email),
            )
            conn.commit()
        return True, "Enviamos um novo código para o seu e-mail.", 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro ao reenviar código: %s", e)
        return False, "Erro interno. Tente novamente.", 500
    finally:
        conn.close()


def _confirmar_cadastro(email, codigo):
    """Confere o código e, se estiver certo, cria o usuário. Retorna (ok, mensagem, status)."""
    email = email.strip().lower()
    codigo = re.sub(r"\D", "", str(codigo or ""))
    if len(codigo) != 6:
        return False, "Digite o código de 6 dígitos.", 400

    agora = _agora_utc()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM cadastros_pendentes WHERE email = %s FOR UPDATE", (email,))
            pend = cursor.fetchone()
            if not pend:
                return False, "Cadastro não encontrado ou expirado. Faça o cadastro novamente.", 404
            if pend["expira_em"] < agora:
                return False, "Código expirado. Peça um novo código.", 400
            if pend["tentativas"] >= CODIGO_MAX_TENTATIVAS:
                return False, "Muitas tentativas incorretas. Peça um novo código.", 429

            if not hmac.compare_digest(str(pend["codigo_hash"]), _hash_codigo(email, codigo)):
                cursor.execute(
                    "UPDATE cadastros_pendentes SET tentativas = tentativas + 1 WHERE email = %s", (email,)
                )
                conn.commit()
                restantes = CODIGO_MAX_TENTATIVAS - (pend["tentativas"] + 1)
                if restantes <= 0:
                    return False, "Muitas tentativas incorretas. Peça um novo código.", 429
                return False, f"Código incorreto. Você ainda tem {restantes} tentativa(s).", 400

            try:
                cursor.execute(
                    "INSERT INTO usuarios (nome, email, senha, telefone) VALUES (%s, %s, %s, %s)",
                    (pend["nome"], pend["email"], pend["senha_hash"], pend["telefone"]),
                )
            except pymysql.err.IntegrityError:
                cursor.execute("DELETE FROM cadastros_pendentes WHERE email = %s", (email,))
                conn.commit()
                return False, "E-mail já cadastrado!", 400
            if _SENHA_COL_OK and pend.get("senha_cifrada"):
                cursor.execute(
                    "UPDATE usuarios SET senha_cifrada = %s WHERE id = %s",
                    (pend["senha_cifrada"], cursor.lastrowid),
                )
            cursor.execute("DELETE FROM cadastros_pendentes WHERE email = %s", (email,))
            conn.commit()
        return True, "E-mail confirmado! Cadastro concluído.", 201
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro ao confirmar cadastro: %s", e)
        return False, "Erro interno. Tente novamente.", 500
    finally:
        conn.close()


@app.route("/api/cadastro", methods=["POST"])
@rate_limit(10, 3600, "cadastro-api")
def api_cadastro():
    """Passo 1: valida os dados e envia o código por e-mail (o usuário só é criado no passo 2)."""
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("nome") or "").strip()
    email = str(dados.get("email") or "").strip()
    senha = str(dados.get("senha") or "")
    telefone = str(dados.get("telefone") or "").strip()

    erro = validar_cadastro(nome, email, senha, telefone)
    if erro:
        return jsonify({"sucesso": False, "mensagem": erro}), 400

    ok, msg, status = _iniciar_verificacao_cadastro(nome, email, senha, telefone)
    if ok:
        return jsonify({"sucesso": True, "pendente": True, "mensagem": msg}), 200
    return jsonify({"sucesso": False, "mensagem": msg}), status


@app.route("/api/cadastro/verificar", methods=["POST"])
@rate_limit(15, 600, "verificar-api")
def api_cadastro_verificar():
    """Passo 2: confere o código e cria o usuário."""
    dados = request.get_json(silent=True) or {}
    email = str(dados.get("email") or "").strip()
    if not email or not EMAIL_RE.match(email):
        return jsonify({"sucesso": False, "mensagem": "E-mail inválido."}), 400
    ok, msg, status = _confirmar_cadastro(email, dados.get("codigo"))
    return jsonify({"sucesso": ok, "mensagem": msg}), status


@app.route("/api/cadastro/reenviar", methods=["POST"])
@rate_limit(5, 3600, "reenviar-api")
def api_cadastro_reenviar():
    dados = request.get_json(silent=True) or {}
    email = str(dados.get("email") or "").strip()
    if not email or not EMAIL_RE.match(email):
        return jsonify({"sucesso": False, "mensagem": "E-mail inválido."}), 400
    ok, msg, status = _reenviar_codigo_cadastro(email)
    return jsonify({"sucesso": ok, "mensagem": msg}), status


@app.route("/api/admin/usuarios", methods=["GET", "OPTIONS"])
@admin_required
def api_admin_usuarios():
    if request.method == "OPTIONS":
        return "", 200

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, email FROM usuarios ORDER BY id DESC")
            usuarios = cursor.fetchall()

        for u in usuarios:
            if not u.get("nome"):
                u["nome"] = "Cliente sem nome"

        return jsonify({"sucesso": True, "usuarios": usuarios}), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_usuarios: %s", e)
        return jsonify({"sucesso": False, "usuarios": [], "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()
        
@app.route("/api/admin/usuarios", methods=["POST"])
@admin_required
def api_admin_criar_usuario():
    """O administrador cadastra um cliente direto, sem o código de confirmação por e-mail."""
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("nome") or "").strip()
    email = str(dados.get("email") or "").strip().lower()
    senha = str(dados.get("senha") or "")
    telefone = str(dados.get("telefone") or "").strip()

    erro = validar_cadastro(nome, email, senha, telefone)
    if erro:
        return jsonify({"sucesso": False, "mensagem": erro}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
            if cursor.fetchone():
                return jsonify({"sucesso": False, "mensagem": "E-mail já cadastrado!"}), 400
            try:
                cursor.execute(
                    "INSERT INTO usuarios (nome, email, senha, telefone) VALUES (%s, %s, %s, %s)",
                    (nome, email, generate_password_hash(senha), telefone),
                )
            except pymysql.err.IntegrityError:
                conn.rollback()
                return jsonify({"sucesso": False, "mensagem": "E-mail já cadastrado!"}), 400
            novo_id = cursor.lastrowid
            if _SENHA_COL_OK:
                cursor.execute("UPDATE usuarios SET senha_cifrada = %s WHERE id = %s", (_cifrar_senha(senha), novo_id))
            cursor.execute("DELETE FROM cadastros_pendentes WHERE email = %s", (email,))
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Usuário cadastrado com sucesso!", "id": novo_id}), 201
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_criar_usuario: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


@app.route("/api/admin/usuarios/<int:usuario_id>", methods=["DELETE", "OPTIONS"])
@admin_required
def api_admin_deletar_usuario(usuario_id):
    if request.method == "OPTIONS":
        return "", 200

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT gateway_subscription_id FROM assinaturas "
                "WHERE cliente_id = %s AND gateway_subscription_id IS NOT NULL", (usuario_id,))
            for sub in cursor.fetchall():
                cancelar_no_gateway(sub["gateway_subscription_id"])
            cursor.execute("DELETE FROM agendamentos WHERE cliente_id = %s", (usuario_id,))
            try:
                cursor.execute("DELETE FROM assinaturas WHERE cliente_id = %s", (usuario_id,))
            except Exception:
                pass 

            cursor.execute("DELETE FROM usuarios WHERE id = %s", (usuario_id,))
            conn.commit()
            
            if cursor.rowcount > 0:
                return jsonify({"sucesso": True, "mensagem": "Usuário e registros vinculados removidos com sucesso!"}), 200
                
        return jsonify({"sucesso": False, "mensagem": "Usuário não encontrado."}), 404
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_deletar_usuario: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()      


@app.route("/api/admin/resetar-senha", methods=["POST"])
@admin_required
def api_admin_resetar_senha():
    dados = request.get_json(silent=True) or {}
    usuario_id = parse_int(dados.get('usuario_id'), 1)
    nova_senha = str(dados.get('nova_senha') or "")

    if not usuario_id or not nova_senha:
        return jsonify({'sucesso': False, 'mensagem': 'Dados incompletos.'}), 400
    if not (8 <= len(nova_senha) <= 128):
        return jsonify({'sucesso': False, 'mensagem': 'A senha deve ter entre 8 e 128 caracteres.'}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE usuarios SET senha = %s WHERE id = %s", (generate_password_hash(nova_senha), usuario_id))
            encontrado = cursor.rowcount > 0
            if encontrado and _SENHA_COL_OK:
                # atualiza (ou limpa, se não houver chave) para a cópia nunca ficar desatualizada
                cursor.execute("UPDATE usuarios SET senha_cifrada = %s WHERE id = %s", (_cifrar_senha(nova_senha), usuario_id))
            conn.commit()
            if not encontrado:
                return jsonify({'sucesso': False, 'mensagem': 'Usuário não encontrado.'}), 404
        return jsonify({'sucesso': True, 'mensagem': 'Senha alterada com sucesso!'}), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_resetar_senha: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro ao alterar senha.'}), 500
    finally:
        conn.close()

@app.route("/api/admin/login", methods=["POST"])
@rate_limit(5, 300, "admin-login")
def api_admin_login():
    """Login do administrador do app. Devolve um token assinado com validade (não existe token fixo)."""
    dados = request.get_json(silent=True) or {}
    email = str(dados.get("email") or "").strip().lower()
    senha = str(dados.get("senha") or "")

    configurado = bool(ADMIN_EMAIL and ADMIN_PASSWORD_HASH)
    email_ok = configurado and hmac.compare_digest(email.encode("utf-8"), ADMIN_EMAIL.encode("utf-8"))
    try:
        # sempre confere um hash, para o tempo de resposta não revelar se o e-mail existe
        senha_ok = check_password_hash(ADMIN_PASSWORD_HASH or HASH_FALSO, senha)
    except ValueError:
        senha_ok = False

    if not (configurado and email_ok and senha_ok):
        app.logger.warning("Tentativa de login admin recusada (ip %s)", _ip_cliente())
        return jsonify({"sucesso": False, "mensagem": "E-mail ou senha incorretos!"}), 401

    token = _serializador_admin().dumps({"adm": 1, "v": _versao_credencial_admin()})
    return jsonify({"sucesso": True, "token": token, "expira_em_dias": ADMIN_TOKEN_DIAS}), 200


@app.route("/api/admin/sessao", methods=["GET"])
@admin_required
def api_admin_sessao():
    """O app chama ao abrir para saber se o token salvo ainda vale."""
    return jsonify({"sucesso": True}), 200


@app.route("/api/admin/usuario/<int:usuario_id>/senha", methods=["POST", "OPTIONS"])
@rate_limit(8, 300, "admin-ver-senha")
@admin_required
def api_admin_ver_senha(usuario_id):
    """Mostra a senha ao administrador (cópia cifrada com SENHA_CIFRA_KEY; confere com o hash antes de exibir).
    Exige a senha do próprio administrador no corpo da requisição (senha_admin)."""
    dados = request.get_json(silent=True) or {}
    senha_admin = str(dados.get("senha_admin") or "")
    try:
        admin_ok = bool(ADMIN_PASSWORD_HASH) and check_password_hash(ADMIN_PASSWORD_HASH, senha_admin)
    except ValueError:
        admin_ok = False
    if not admin_ok:
        app.logger.warning("Ver senha: confirmação do admin incorreta (usuário %s, ip %s)", usuario_id, _ip_cliente())
        return jsonify({'sucesso': False, 'mensagem': 'Senha do administrador incorreta.'}), 403

    if not _SENHA_COL_OK or _fernet() is None:
        return jsonify({'sucesso': False, 'mensagem': 'Ver senha não está ativado no servidor (falta SENHA_CIFRA_KEY).'}), 503

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT senha, senha_cifrada FROM usuarios WHERE id = %s", (usuario_id,))
            usuario = cursor.fetchone()
    except Exception as e:
        app.logger.error("Erro em api_admin_ver_senha: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro ao buscar senha.'}), 500
    finally:
        conn.close()

    if not usuario:
        return jsonify({'sucesso': False, 'mensagem': 'Usuário não encontrado.'}), 404

    senha = _decifrar_senha(usuario.get("senha_cifrada"))
    try:
        confere = bool(senha) and check_password_hash(usuario["senha"], senha)
    except ValueError:
        confere = False
    if not confere:
        return jsonify({
            'sucesso': False,
            'mensagem': 'Senha ainda não disponível: ela aparece depois do próximo login deste usuário. Ou use ALTERAR para definir uma nova.',
        }), 404

    app.logger.info("Admin visualizou a senha do usuário %s (ip %s)", usuario_id, _ip_cliente())
    resp = jsonify({'sucesso': True, 'senha': senha})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/admin/dados")
@admin_required
def api_admin_dados():
    data_filtro = request.args.get("data", datetime.now().strftime("%Y-%m-%d"))

    def _data_valida(valor, padrao):
        try:
            return datetime.strptime(str(valor)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return padrao

    # Semana e mês podem ter data própria (cards SEMANA e MÊS); sem ela, seguem o dia selecionado
    semana_ref = _data_valida(request.args.get("semana", data_filtro), data_filtro)
    mes_ref = _data_valida(request.args.get("mes", data_filtro), data_filtro)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Agendamentos gerais do dia selecionado (utiliza JOIN para exigir usuário existente)
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, 
                       a.tipo_pagamento, COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') as cliente_nome, IFNULL(u.email, '') as cliente_email
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE DATE(a.data) = %s
                ORDER BY a.horario ASC
            """, (data_filtro,))
            agendamentos_raw = cursor.fetchall()

            agendamentos = []
            for row in agendamentos_raw:
                data_val = row["data"]
                if hasattr(data_val, "strftime"):
                    data_val = data_val.strftime("%Y-%m-%d")
                else:
                    data_val = str(data_val)[:10]

                agendamentos.append({
                    "id": row["id"],
                    "profissional": row["profissional"],
                    "data": data_val,
                    "horario": str(row["horario"]),
                    "servico": row["servico"],
                    "tipo_pagamento": row.get("tipo_pagamento", "presencial"),
                    "cliente_nome": row["cliente_nome"],
                    "cliente_email": row["cliente_email"],
                })

            # 2. Cortes Finalizados do DIA selecionado (com JOIN para ocultar usuários excluídos)
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, a.preco, 
                       COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome, 
                       IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE DATE(a.data) = %s AND LOWER(a.status) IN ('concluido', 'finalizado')
                ORDER BY a.id DESC
            """, (data_filtro,))
            finalizados_raw = cursor.fetchall()

            cursor.execute("SELECT nome, preco FROM servicos")
            precos_por_servico = {str(s["nome"]).strip().lower(): float(s["preco"]) for s in cursor.fetchall()}

            # Comissões por barbeiro/serviço (padrão 40% quando o serviço não foi configurado para o barbeiro)
            cursor.execute("SELECT id, nome FROM barbeiros")
            barbeiros_nomes = {b["id"]: str(b["nome"]).strip().lower() for b in cursor.fetchall()}
            cursor.execute("""
                SELECT bs.barbeiro_id, LOWER(TRIM(s.nome)) AS servico, bs.comissao_percentual
                FROM barbeiro_servicos bs
                JOIN servicos s ON s.id = bs.servico_id
            """)
            comissoes_cfg = {
                (r["barbeiro_id"], r["servico"]): float(r["comissao_percentual"] if r["comissao_percentual"] is not None else 40.0)
                for r in cursor.fetchall()
            }

            def _pct_comissao(profissional, servico):
                prof = str(profissional or "").strip().lower()
                serv = str(servico or "").strip().lower()
                if not prof:
                    return 0.0
                bid = next((i for i, n in barbeiros_nomes.items() if n == prof), None)
                if bid is None:
                    bid = next((i for i, n in barbeiros_nomes.items() if n and (n in prof or prof in n)), None)
                if bid is None:
                    return 0.0
                return comissoes_cfg.get((bid, serv), 40.0)

            def _aplicar_comissao(item, preco):
                pct = _pct_comissao(item.get("profissional"), item.get("servico"))
                item["valor_num"] = round(float(preco), 2)
                item["comissao_percentual"] = pct
                item["comissao_valor"] = round(float(preco) * pct / 100.0, 2)

            finalizados = []
            for f in finalizados_raw:
                preco_servico = float(f.get("preco") or 0)
                if preco_servico <= 0:
                    nome_servico_chave = str(f.get("servico", "")).strip().lower()
                    preco_servico = precos_por_servico.get(nome_servico_chave, 0.0)

                f["valor"] = f"R$ {preco_servico:.2f}".replace(".", ",")
                _aplicar_comissao(f, preco_servico)
                if hasattr(f.get("data"), "strftime"):
                    f["data"] = f["data"].strftime("%Y-%m-%d")
                else:
                    f["data"] = str(f.get("data", ""))[:10]
                finalizados.append(f)

            # 2.1 Cortes Finalizados da SEMANA ATUAL (Com JOIN)
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, a.preco, 
                       COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome, 
                       IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE YEARWEEK(a.data, 1) = YEARWEEK(%s, 1) AND LOWER(a.status) IN ('concluido', 'finalizado')
                ORDER BY a.data DESC, a.horario ASC
            """, (semana_ref,))
            semanal_raw = cursor.fetchall()
            finalizados_semanal = []
            for f in semanal_raw:
                ps = float(f.get("preco") or 0)
                if ps <= 0:
                    ps = precos_por_servico.get(str(f.get("servico", "")).strip().lower(), 0.0)
                f["valor"] = f"R$ {ps:.2f}".replace(".", ",")
                _aplicar_comissao(f, ps)
                if hasattr(f.get("data"), "strftime"):
                    f["data"] = f["data"].strftime("%Y-%m-%d")
                else:
                    f["data"] = str(f.get("data", ""))[:10]
                finalizados_semanal.append(f)

            # 2.2 Cortes Finalizados do MÊS ATUAL (Com JOIN)
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, a.preco, 
                       COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome, 
                       IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE MONTH(a.data) = MONTH(%s) AND YEAR(a.data) = YEAR(%s) AND LOWER(a.status) IN ('concluido', 'finalizado')
                ORDER BY a.data DESC, a.horario ASC
            """, (mes_ref, mes_ref,))
            mensal_raw = cursor.fetchall()
            finalizados_mensal = []
            for f in mensal_raw:
                ps = float(f.get("preco") or 0)
                if ps <= 0:
                    ps = precos_por_servico.get(str(f.get("servico", "")).strip().lower(), 0.0)
                f["valor"] = f"R$ {ps:.2f}".replace(".", ",")
                _aplicar_comissao(f, ps)
                if hasattr(f.get("data"), "strftime"):
                    f["data"] = f["data"].strftime("%Y-%m-%d")
                else:
                    f["data"] = str(f.get("data", ""))[:10]
                finalizados_mensal.append(f)

            # 3. Contadores filtrados com JOIN nas tabelas correspondentes
            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE DATE(a.data) = %s AND LOWER(a.status) IN ('concluido', 'finalizado')
            """, (data_filtro,))
            cortes_diario = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE YEARWEEK(a.data, 1) = YEARWEEK(%s, 1) AND LOWER(a.status) IN ('concluido', 'finalizado')
            """, (semana_ref,))
            cortes_semanal = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE MONTH(a.data) = MONTH(%s) AND YEAR(a.data) = YEAR(%s) AND LOWER(a.status) IN ('concluido', 'finalizado')
            """, (mes_ref, mes_ref,))
            cortes_mensal = cursor.fetchone()["total"]

            # 4. Valor total calculado para a data filtrada
            valor_total_finalizados = sum(
                float(f.get("preco") or precos_por_servico.get(str(f.get("servico")).strip().lower(), 0.0))
                for f in finalizados_raw
            )

            # 5. Serviços mais solicitados filtrados com JOIN
            cursor.execute("""
                SELECT a.servico, COUNT(*) AS quantidade
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE DATE(a.data) = %s AND LOWER(a.status) IN ('concluido', 'finalizado')
                GROUP BY a.servico
                ORDER BY quantidade DESC
                LIMIT 5
            """, (data_filtro,))
            servicos_raw = cursor.fetchall()
            total_servicos_concluidos = sum(s["quantidade"] for s in servicos_raw)
            servicos_mais_solicitados = []

            if total_servicos_concluidos > 0:
                servicos_mais_solicitados = [
                    {
                        "nome": s["servico"],
                        "quantidade": s["quantidade"],
                        "porcentagem": round(s["quantidade"] / total_servicos_concluidos, 2),
                    }
                    for s in servicos_raw
                ]

            # 6. Receitas de assinaturas ativas com JOIN
            cursor.execute("""
                SELECT COALESCE(SUM(a.preco), 0) AS total
                FROM assinaturas a
                JOIN usuarios u ON a.cliente_id = u.id
                WHERE LOWER(a.status) = 'ativo' AND a.data_renovacao >= CURDATE()
            """)
            receita_assinaturas_ativas = float(cursor.fetchone()["total"])

            cursor.execute("""
                SELECT COALESCE(SUM(a.preco), 0) AS total
                FROM assinaturas a
                JOIN usuarios u ON a.cliente_id = u.id
                WHERE LOWER(a.status) = 'ativo' AND DATE(a.data_inicio) = CURDATE()
            """)
            receita_assinaturas_hoje = float(cursor.fetchone()["total"])

        return jsonify({
            "agendamentos": agendamentos,
            "finalizados": finalizados,
            "finalizados_semanal": finalizados_semanal,
            "finalizados_mensal": finalizados_mensal,
            "dashboard": {"diario": cortes_diario, "semanal": cortes_semanal, "mensal": cortes_mensal},
            "servicos_mais_solicitados": servicos_mais_solicitados,
            "receita_assinaturas_ativas": receita_assinaturas_ativas,
            "receita_assinaturas_hoje": receita_assinaturas_hoje,
            "valor_total_finalizados": valor_total_finalizados,
        })
    finally:
        conn.close()


@app.route("/api/admin/agendamentos/<int:id>/status", methods=["PUT"])
@admin_required
def atualizar_status_agendamento(id):
    data = request.get_json() or {}
    novo_status = data.get("status")
    if not novo_status:
        return jsonify({"sucesso": False, "mensagem": "Status obrigatório."}), 400
    novo_status = str(novo_status).strip()
    if not STATUS_RE.match(novo_status):
        return jsonify({"sucesso": False, "mensagem": "Status inválido."}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if str(novo_status).strip().lower() in ('concluido', 'finalizado'):
                cursor.execute(
                    "UPDATE agendamentos SET status = %s, concluido_em = COALESCE(concluido_em, %s) WHERE id = %s",
                    (novo_status, datetime.now(), id),
                )
            else:
                cursor.execute(
                    "UPDATE agendamentos SET status = %s, concluido_em = NULL WHERE id = %s",
                    (novo_status, id),
                )
            conn.commit()
            if cursor.rowcount > 0:
                return jsonify({"sucesso": True, "mensagem": "Status atualizado!"}), 200
        return jsonify({"sucesso": False, "mensagem": "Agendamento não encontrado."}), 404
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em atualizar_status_agendamento: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


# ==============================================================================
# PAINEL DE COMISSÕES (intervalo de datas + colaborador + baixa de pagamento)
# ==============================================================================
def _contexto_comissoes(cursor):
    """Barbeiros ativos, preços dos serviços e percentuais configurados."""
    cursor.execute("SELECT id, nome FROM barbeiros WHERE ativo = 1")
    barbeiros = {b["id"]: str(b["nome"]).strip() for b in cursor.fetchall()}

    cursor.execute("SELECT nome, preco FROM servicos")
    precos = {str(s["nome"]).strip().lower(): float(s["preco"]) for s in cursor.fetchall()}

    cursor.execute("""
        SELECT bs.barbeiro_id, LOWER(TRIM(s.nome)) AS servico, bs.comissao_percentual
        FROM barbeiro_servicos bs
        JOIN servicos s ON s.id = bs.servico_id
    """)
    cfg = {
        (r["barbeiro_id"], r["servico"]): float(r["comissao_percentual"] if r["comissao_percentual"] is not None else 40.0)
        for r in cursor.fetchall()
    }
    return barbeiros, precos, cfg


def _calcular_comissao_linha(linha, barbeiros, precos, cfg):
    """Devolve (barbeiro_id, valor, percentual, comissao) ou None se o barbeiro não está ativo."""
    bid = linha.get("barbeiro_id")
    if bid not in barbeiros:
        bid = None
        prof = str(linha.get("profissional") or "").strip().lower()
        if prof:
            for i, n in barbeiros.items():
                if n.lower() == prof:
                    bid = i
                    break
            if bid is None:
                for i, n in barbeiros.items():
                    nl = n.lower()
                    if nl and (nl in prof or prof in nl):
                        bid = i
                        break
    if bid is None:
        return None

    serv_chave = str(linha.get("servico") or "").strip().lower()
    valor = float(linha.get("preco") or 0)
    if valor <= 0:
        valor = precos.get(serv_chave, 0.0)
    pct = cfg.get((bid, serv_chave), 40.0)
    return bid, valor, pct, round(valor * pct / 100.0, 2)


def _fmt_data_br(valor, com_hora=False):
    if not valor:
        return ""
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")
    return str(valor)[:16 if com_hora else 10]


@app.route("/api/admin/comissoes", methods=["GET", "OPTIONS"])
@admin_required
def api_admin_comissoes():
    """Comissões por colaborador num intervalo de datas (conta pelo dia do agendamento)."""
    hoje = datetime.now().strftime("%Y-%m-%d")

    def _data_valida(valor, padrao):
        try:
            return datetime.strptime(str(valor)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return padrao

    inicio = _data_valida(request.args.get("inicio"), hoje)
    fim = _data_valida(request.args.get("fim"), hoje)
    if inicio > fim:
        inicio, fim = fim, inicio
    dias = (datetime.strptime(fim, "%Y-%m-%d") - datetime.strptime(inicio, "%Y-%m-%d")).days
    if dias > 366:
        return jsonify({"sucesso": False, "mensagem": "Intervalo máximo de 1 ano."}), 400

    filtro_barbeiro = None
    bruto = (request.args.get("barbeiro_id") or "").strip()
    if bruto:
        filtro_barbeiro = parse_int(bruto, 1)
        if filtro_barbeiro is None:
            return jsonify({"sucesso": False, "mensagem": "Colaborador inválido."}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            barbeiros, precos, cfg = _contexto_comissoes(cursor)

            cursor.execute("""
                SELECT a.id, a.barbeiro_id, a.profissional, a.data, a.horario, a.servico, a.preco,
                       COALESCE(u.nome, NULLIF(a.cliente_nome, ''), 'Cliente sem cadastro') AS cliente_nome
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE DATE(a.data) BETWEEN %s AND %s
                  AND LOWER(a.status) IN ('concluido', 'finalizado')
                ORDER BY a.data ASC, a.horario ASC
            """, (inicio, fim))
            linhas = cursor.fetchall()

            cursor.execute("""
                SELECT cp.agendamento_id, cp.valor, cp.percentual, cp.pago_em
                FROM comissoes_pagas cp
                JOIN agendamentos a ON a.id = cp.agendamento_id
                WHERE DATE(a.data) BETWEEN %s AND %s
            """, (inicio, fim))
            pagas = {r["agendamento_id"]: r for r in cursor.fetchall()}

        grupos = {}
        for l in linhas:
            calc = _calcular_comissao_linha(l, barbeiros, precos, cfg)
            if calc is None:  # barbeiro excluído/inativo não aparece
                continue
            bid, valor, pct, comissao = calc
            if filtro_barbeiro is not None and bid != filtro_barbeiro:
                continue

            baixa = pagas.get(l["id"])
            if baixa:  # comissão já paga: mantém o valor e o percentual da hora do pagamento
                comissao = float(baixa["valor"])
                pct = float(baixa["percentual"])

            g = grupos.setdefault(bid, {
                "barbeiro_id": bid, "nome": barbeiros[bid],
                "qtd": 0, "faturamento": 0.0, "comissao": 0.0,
                "comissao_paga": 0.0, "comissao_pendente": 0.0,
                "servicos": {}, "atendimentos": [],
            })
            g["qtd"] += 1
            g["faturamento"] += valor
            g["comissao"] += comissao
            if baixa:
                g["comissao_paga"] += comissao
            else:
                g["comissao_pendente"] += comissao

            nome_serv = str(l.get("servico") or "Serviço").strip()
            sv = g["servicos"].setdefault(nome_serv, {
                "servico": nome_serv, "qtd": 0, "faturamento": 0.0, "percentual": pct, "comissao": 0.0,
            })
            sv["qtd"] += 1
            sv["faturamento"] += valor
            sv["comissao"] += comissao

            g["atendimentos"].append({
                "id": l["id"], "data": l["data"].strftime("%Y-%m-%d") if hasattr(l["data"], "strftime") else str(l["data"])[:10],
                "horario": str(l.get("horario") or ""),
                "servico": nome_serv, "cliente_nome": l.get("cliente_nome") or "Cliente",
                "valor": round(valor, 2), "percentual": pct, "comissao": comissao,
                "pago": bool(baixa),
                "pago_em": _fmt_data_br(baixa["pago_em"], True) if baixa else "",
            })

        if filtro_barbeiro is not None and filtro_barbeiro in barbeiros and filtro_barbeiro not in grupos:
            grupos[filtro_barbeiro] = {
                "barbeiro_id": filtro_barbeiro, "nome": barbeiros[filtro_barbeiro],
                "qtd": 0, "faturamento": 0.0, "comissao": 0.0,
                "comissao_paga": 0.0, "comissao_pendente": 0.0,
                "servicos": {}, "atendimentos": [],
            }

        resultado = []
        for g in grupos.values():
            for campo in ("faturamento", "comissao", "comissao_paga", "comissao_pendente"):
                g[campo] = round(g[campo], 2)
            g["servicos"] = [
                {**s, "faturamento": round(s["faturamento"], 2), "comissao": round(s["comissao"], 2)}
                for s in g["servicos"].values()
            ]
            resultado.append(g)
        resultado.sort(key=lambda x: x["comissao_pendente"], reverse=True)

        return jsonify({
            "sucesso": True,
            "inicio": inicio,
            "fim": fim,
            "total_cortes": sum(g["qtd"] for g in resultado),
            "total_faturamento": round(sum(g["faturamento"] for g in resultado), 2),
            "total_comissao": round(sum(g["comissao"] for g in resultado), 2),
            "total_paga": round(sum(g["comissao_paga"] for g in resultado), 2),
            "total_pendente": round(sum(g["comissao_pendente"] for g in resultado), 2),
            "barbeiros": resultado,
        }), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_comissoes: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


def _ids_agendamentos(dados):
    """Lê e valida a lista agendamento_ids do corpo da requisição (até 500 ids)."""
    bruto = dados.get("agendamento_ids")
    if not isinstance(bruto, list) or not bruto or len(bruto) > 500:
        return None
    ids = []
    for item in bruto:
        n = parse_int(item, 1)
        if n is None:
            return None
        ids.append(n)
    return sorted(set(ids))


@app.route("/api/admin/comissoes/baixa", methods=["POST", "OPTIONS"])
@admin_required
def api_admin_comissoes_baixa():
    """Dá baixa (marca como paga) nas comissões dos atendimentos escolhidos."""
    dados = request.get_json(silent=True) or {}
    ids = _ids_agendamentos(dados)
    if ids is None:
        return jsonify({"sucesso": False, "mensagem": "Escolha ao menos uma comissão."}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            barbeiros, precos, cfg = _contexto_comissoes(cursor)
            marcadores = ",".join(["%s"] * len(ids))
            cursor.execute(f"""
                SELECT a.id, a.barbeiro_id, a.profissional, a.servico, a.preco
                FROM agendamentos a
                WHERE a.id IN ({marcadores}) AND LOWER(a.status) IN ('concluido', 'finalizado')
            """, ids)
            linhas = cursor.fetchall()

            agora = datetime.now()
            baixados, total = 0, 0.0
            for l in linhas:
                calc = _calcular_comissao_linha(l, barbeiros, precos, cfg)
                if calc is None:
                    continue
                bid, _valor, pct, comissao = calc
                cursor.execute(
                    "INSERT IGNORE INTO comissoes_pagas (agendamento_id, barbeiro_id, valor, percentual, pago_em) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (l["id"], bid, comissao, pct, agora),
                )
                if cursor.rowcount > 0:
                    baixados += 1
                    total += comissao
            conn.commit()

        if baixados == 0:
            return jsonify({"sucesso": False, "mensagem": "Nenhuma comissão pendente encontrada para dar baixa."}), 400
        return jsonify({
            "sucesso": True,
            "mensagem": f"Baixa feita em {baixados} comissão(ões).",
            "baixados": baixados,
            "total": round(total, 2),
        }), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_comissoes_baixa: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


@app.route("/api/admin/comissoes/estornar", methods=["POST", "OPTIONS"])
@admin_required
def api_admin_comissoes_estornar():
    """Desfaz a baixa: as comissões voltam para pendentes."""
    dados = request.get_json(silent=True) or {}
    ids = _ids_agendamentos(dados)
    if ids is None:
        return jsonify({"sucesso": False, "mensagem": "Escolha ao menos uma comissão."}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            marcadores = ",".join(["%s"] * len(ids))
            cursor.execute(f"DELETE FROM comissoes_pagas WHERE agendamento_id IN ({marcadores})", ids)
            desfeitos = cursor.rowcount
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"{desfeitos} baixa(s) desfeita(s).", "desfeitos": desfeitos}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_comissoes_estornar: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


# ==============================================================================
# ADMIN AGENDA UM CLIENTE
# ==============================================================================
@app.route("/api/admin/agendamentos", methods=["POST", "OPTIONS"])
@admin_required
def api_admin_criar_agendamento():
    dados = request.get_json(silent=True) or {}

    cliente_id = parse_int(dados.get("cliente_id"), 1)
    # Cliente sem cadastro no site: sem cliente_id, só o nome digitado pelo administrador
    sem_cadastro = bool(dados.get("sem_cadastro")) or cliente_id is None
    cliente_nome = " ".join(str(dados.get("cliente_nome") or "").split())
    if sem_cadastro:
        cliente_id = None
    barbeiro_id = parse_int(dados.get("barbeiro_id"), 1)
    data = str(dados.get("data") or "").strip()
    horario = str(dados.get("horario") or "").strip()
    servico = str(dados.get("servico") or "").strip()
    telefone = str(dados.get("cliente_telefone") or "").strip()
    tipo_pagamento = str(dados.get("tipo_pagamento") or "presencial").strip().lower()
    if tipo_pagamento not in TIPOS_PAGAMENTO:
        tipo_pagamento = "presencial"

    try:
        momento = datetime.strptime(f"{data} {horario}", "%Y-%m-%d %H:%M")
    except ValueError:
        momento = None

    if sem_cadastro:
        if len(cliente_nome) < 2 or len(cliente_nome) > 100:
            return jsonify({"sucesso": False, "mensagem": "Informe o nome do cliente."}), 400
        if tipo_pagamento in ("plano", "vip"):
            return jsonify({"sucesso": False, "mensagem": "Cliente sem cadastro não tem plano. Escolha outra forma de pagamento."}), 400
    if barbeiro_id is None or not servico or len(servico) > 100:
        return jsonify({"sucesso": False, "mensagem": "Escolha o profissional e o serviço."}), 400
    if momento is None or horario not in HORARIOS_VALIDOS:
        return jsonify({"sucesso": False, "mensagem": "Data ou horário inválido."}), 400
    if momento < datetime.now():
        return jsonify({"sucesso": False, "mensagem": "Esse horário já passou."}), 400
    if not TELEFONE_RE.match(telefone):
        return jsonify({"sucesso": False, "mensagem": "Telefone inválido."}), 400
    if not sem_cadastro and tipo_pagamento in ("plano", "vip") and not cliente_tem_assinatura_ativa(cliente_id):
        return jsonify({"sucesso": False, "mensagem": "Este cliente não possui assinatura ativa."}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not sem_cadastro:
                cursor.execute("SELECT id FROM usuarios WHERE id = %s", (cliente_id,))
                if not cursor.fetchone():
                    return jsonify({"sucesso": False, "mensagem": "Cliente não encontrado."}), 404

            cursor.execute("SELECT nome FROM barbeiros WHERE id = %s AND ativo = 1", (barbeiro_id,))
            barb = cursor.fetchone()
            cursor.execute("SELECT preco FROM servicos WHERE LOWER(TRIM(nome)) = LOWER(TRIM(%s))", (servico,))
            serv_db = cursor.fetchone()
            if not barb or not serv_db:
                return jsonify({"sucesso": False, "mensagem": "Profissional ou serviço não encontrado."}), 404
            if not barbeiro_realiza_servico(cursor, barbeiro_id, servico):
                return jsonify({"sucesso": False, "mensagem": "Este profissional não realiza o serviço escolhido."}), 400

            preco = 0.00 if tipo_pagamento in ("plano", "vip") else float(serv_db["preco"])

            # Libera o horário de um agendamento cancelado (a UNIQUE KEY o manteria bloqueado)
            cursor.execute(
                "DELETE FROM agendamentos WHERE barbeiro_id = %s AND data = %s AND horario = %s "
                "AND LOWER(status) = 'cancelado'",
                (barbeiro_id, data, horario),
            )
            cursor.execute(
                "SELECT id FROM agendamentos WHERE barbeiro_id = %s AND data = %s AND horario = %s AND status != 'cancelado'",
                (barbeiro_id, data, horario),
            )
            if cursor.fetchone():
                conn.rollback()
                return jsonify({"sucesso": False, "mensagem": "Este horário já está ocupado com este profissional."}), 409

            try:
                cursor.execute(
                    """
                    INSERT INTO agendamentos
                    (cliente_id, cliente_nome, barbeiro_id, profissional, data, horario, servico, tipo_pagamento, cliente_telefone, preco)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (cliente_id, (cliente_nome if sem_cadastro else None), barbeiro_id, barb["nome"], data, horario, servico, tipo_pagamento, telefone, preco),
                )
            except pymysql.err.IntegrityError:
                conn.rollback()
                return jsonify({"sucesso": False, "mensagem": "Este horário já está ocupado com este profissional."}), 409
            novo_id = cursor.lastrowid
            conn.commit()

        return jsonify({"sucesso": True, "mensagem": "Cliente agendado com sucesso!", "id": novo_id}), 201
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_criar_agendamento: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


@app.route("/api/admin/cancelar-agendamento/<int:id>", methods=["DELETE"])
@admin_required
def api_admin_cancelar_agendamento(id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM agendamentos WHERE id = %s", (id,))
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Cancelado!"}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_cancelar_agendamento: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()

@app.route("/checkout-plano", methods=["GET"])
def checkout_plano():
    if "cliente_id" not in session:
        return redirect(url_for("login"))
    
    plano = buscar_plano(plano_id=request.args.get("plano_id"), nome=request.args.get("plano"))
    if not plano:
        return redirect(url_for("pagina_planos"))
    nome_plano = plano["nome"]
    preco = f"{plano['preco']:.2f}"  # o preço do navegador (?preco=) é ignorado
    
    return render_template("checkout_plano.html", plano=nome_plano, preco=preco,
                           mp_public_key=MERCADO_PAGO_PUBLIC_KEY)


@app.route("/planos", methods=["GET"])
def pagina_planos():
    """Renderiza a página planos.html injetando a lista do banco de dados."""
    conn = get_db_connection()
    planos = []
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, nome, descricao, preco, ordem FROM planos_assinatura "
                "WHERE ativo = 1 OR ativo IS NULL "
                "ORDER BY ordem ASC, preco ASC"
            )
            planos = cursor.fetchall()
    except Exception as e:
        app.logger.error("Erro ao carregar pagina_planos: %s", e)
    finally:
        conn.close()

    return render_template(
        "planos.html",
        planos=planos,
        cliente_id=session.get("cliente_id"),
        cliente_nome=session.get("cliente_nome")
    )
@app.route('/api/admin/planos-ativos', methods=['GET'])
@admin_required
def admin_planos_ativos():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    a.id, 
                    COALESCE(u.nome, 'Cliente') AS cliente_nome, 
                    COALESCE(u.email, 'Não informado') AS cliente_email, 
                    COALESCE(u.telefone, 'Não informado') AS cliente_telefone,
                    u.criado_em AS cliente_desde,
                    COALESCE(a.nome_plano, 'Plano Mensal') AS nome_plano,
                    COALESCE(a.nome_plano, 'Plano Mensal') AS nome,
                    COALESCE(a.preco, 0.00) AS preco,
                    a.data_inicio AS inicio,
                    a.data_renovacao AS validade,
                    a.status,
                    a.gateway_subscription_id,
                    a.cliente_id,
                    a.criado_em AS assinada_em,
                    (SELECT COUNT(*) FROM agendamentos ag
                      WHERE ag.cliente_id = a.cliente_id
                        AND LOWER(ag.tipo_pagamento) IN ('plano', 'vip')
                        AND LOWER(ag.status) != 'cancelado'
                        AND ag.data BETWEEN a.data_inicio AND a.data_renovacao) AS usos_plano
                FROM assinaturas AS a
                LEFT JOIN usuarios AS u ON a.cliente_id = u.id
                ORDER BY a.id DESC
            """)
            planos_raw = cursor.fetchall()

            planos = []
            for p in planos_raw:
                # Tratamento e conversão ultra-segura de datas para string
                for campo in ["inicio", "validade", "cliente_desde"]:
                    val = p.get(campo)
                    if val:
                        if hasattr(val, "strftime"):
                            p[campo] = val.strftime("%d/%m/%Y")
                        else:
                            p[campo] = str(val)[:10]
                    else:
                        p[campo] = "--/--/----"

                if p.get("assinada_em"):
                    p["assinada_em"] = _fmt_data_br(p["assinada_em"], True)
                else:
                    p["assinada_em"] = "--/--/----"
                p["usos_plano"] = int(p.get("usos_plano") or 0)

                # Conversão segura do preço
                try:
                    p["preco"] = float(p.get("preco") or 0.0)
                except Exception:
                    p["preco"] = 0.0

                # Normalização flexível do status para o painel admin
                st = str(p.get("status") or "").strip().lower()
                if st in ["ativo", "active", "authorized", "approved", "confirmado"]:
                    p["status"] = "ativo"
                elif st in ["vencido", "expired"]:
                    p["status"] = "vencido"
                else:
                    p["status"] = "cancelado"

                planos.append(p)

            return jsonify({'sucesso': True, 'planos': planos}), 200
    except Exception as e:
        app.logger.error("Erro crítico em admin_planos_ativos: %s", str(e))
        return jsonify({'sucesso': False, 'planos': [], 'mensagem': 'Erro interno.'}), 500
    finally:
        conn.close()
@app.route('/api/admin/cobrar-assinatura', methods=['POST'])
@admin_required
def admin_cobrar_assinatura():
    dados = request.get_json() or {}
    assinatura_id = dados.get('assinatura_id')
    
    if not assinatura_id:
        return jsonify({'sucesso': False, 'mensagem': 'ID da assinatura não informado.'}), 400
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Busca os dados da assinatura e do cliente
            cursor.execute("""
                SELECT a.id, a.cliente_id, a.nome_plano, a.preco, a.gateway_subscription_id, u.email, u.nome
                FROM assinaturas a
                JOIN usuarios u ON a.cliente_id = u.id
                WHERE a.id = %s
            """, (assinatura_id,))
            sub = cursor.fetchone()

            if not sub:
                return jsonify({'sucesso': False, 'mensagem': 'Assinatura não encontrada.'}), 404

            gw_id = sub.get("gateway_subscription_id")
            
            # Se houver uma assinatura recorrente no Mercado Pago, tentamos verificar ou criar uma ordem de pagamento avulsa
            if gw_id:
                try:
                    mp_res = sdk.preapproval().get(gw_id)
                    status_mp = mp_res.get("response", {}).get("status")
                    
                    if status_mp == "authorized":
                        cursor.execute("""
                            UPDATE assinaturas 
                            SET status = 'ativo', data_renovacao = DATE_ADD(CURDATE(), INTERVAL 30 DAY) 
                            WHERE id = %s
                        """, (assinatura_id,))
                        conn.commit()
                        return jsonify({'sucesso': True, 'mensagem': 'Cobrança verificada e plano renovado com sucesso!'}), 200
                except Exception as mp_err:
                    app.logger.warning("Falha ao consultar gateway: %s", mp_err)

            # Renovação e cobrança manual direta pelo painel admin
            cursor.execute("""
                UPDATE assinaturas 
                SET status = 'ativo', data_renovacao = DATE_ADD(CURDATE(), INTERVAL 30 DAY) 
                WHERE id = %s
            """, (assinatura_id,))
            conn.commit()

            return jsonify({'sucesso': True, 'mensagem': 'Cobrança solicitada e plano renovado com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em admin_cobrar_assinatura: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()

@app.route("/api/assinaturas/assinar", methods=["POST"])
@rate_limit(20, 300, "assinar")
def assinar_plano():
    """Confirma a assinatura SOMENTE depois de um pagamento aprovado e pertencente ao cliente logado."""
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({"sucesso": False, "mensagem": "Não autenticado"}), 401

    dados = request.get_json(silent=True) or {}
    pagamento_id = parse_int(dados.get("pagamento_id"), 1, 10**15)
    if not pagamento_id:
        return jsonify({"sucesso": False, "mensagem": "Pagamento não informado."}), 400

    try:
        info = sdk.payment().get(pagamento_id).get("response", {}) or {}
        if str((info.get("metadata") or {}).get("cliente_id")) != str(cliente_id):
            return jsonify({"sucesso": False, "mensagem": "Pagamento não encontrado."}), 404
        if not ativar_por_pagamento(info):
            return jsonify({"sucesso": False, "mensagem": "Pagamento ainda não aprovado."}), 402
    except Exception as e:
        app.logger.error("Erro em assinar_plano: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno ao processar assinatura."}), 500

    renovacao = (datetime.now().date() + timedelta(days=30)).strftime("%d/%m/%Y")
    return jsonify({"sucesso": True, "mensagem": "Assinatura ativada com sucesso!", "renovacao": renovacao}), 200


@app.route("/cancelar-agendamento/<int:id>", methods=["POST"])
def cancelar_agendamento(id):
    if "cliente_id" not in session:
        return redirect(url_for("login"))

    cliente_id = session["cliente_id"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM agendamentos WHERE id = %s AND cliente_id = %s", (id, cliente_id))
            conn.commit()
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em cancelar_agendamento: %s", e)
    finally:
        conn.close()

    return redirect(url_for("meus_agendamentos"))


@app.route("/")
def home():
    return render_template("site.html", cliente_id=session.get("cliente_id"), cliente_nome=session.get("cliente_nome"))


@app.route("/login", methods=["GET", "POST"])
@rate_limit(10, 300, "login-web")
def login():
    erro = None
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
                usuario = cursor.fetchone()
        finally:
            conn.close()

        if _verificar_senha(usuario, senha or ""):
            _guardar_senha_cifrada_no_login(usuario, senha or "")
            session.clear()  # evita fixação de sessão
            session.permanent = True
            session["cliente_id"] = usuario["id"]
            session["cliente_nome"] = usuario["nome"]
            return redirect(url_for("home"))
        erro = "E-mail ou senha incorretos!"

    return render_template("login.html", erro=erro)


@app.route('/cadastro', methods=['GET', 'POST'])
@rate_limit(10, 3600, "cadastro-web")
def cadastro():
    erro = None
    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        email = (request.form.get('email') or '').strip()
        telefone = (request.form.get('telefone') or '').strip()
        senha = request.form.get('senha') or ''

        # 1. Valida os dados
        erro = validar_cadastro(nome, email, senha, telefone)
        if not erro:
            # 2. Guarda o cadastro como pendente e envia o código de 6 dígitos por e-mail.
            #    O usuário só é criado depois de confirmar o código em /verificar-email.
            ok, msg, _status = _iniciar_verificacao_cadastro(nome, email, senha, telefone)
            if ok:
                session['cadastro_email'] = email.lower()
                session['verif_aviso'] = msg
                return redirect(url_for('verificar_email'))
            erro = msg

    return render_template('cadastro.html', erro=erro)

@app.route("/verificar-email", methods=["GET", "POST"])
@rate_limit(15, 600, "verificar-web")
def verificar_email():
    email = session.get("cadastro_email")
    if not email:
        return redirect(url_for("cadastro"))

    erro = session.pop("verif_erro", None)
    aviso = session.pop("verif_aviso", None)

    if request.method == "POST":
        ok, msg, _status = _confirmar_cadastro(email, request.form.get("codigo"))
        if ok:
            session.pop("cadastro_email", None)
            return redirect(url_for("login"))
        erro = msg
        aviso = None

    return render_template("verificar_email.html", email_mascarado=_mascarar_email(email), erro=erro, aviso=aviso)


@app.route("/reenviar-codigo", methods=["POST"])
@rate_limit(5, 3600, "reenviar-web")
def reenviar_codigo():
    email = session.get("cadastro_email")
    if not email:
        return redirect(url_for("cadastro"))
    ok, msg, _status = _reenviar_codigo_cadastro(email)
    session["verif_aviso" if ok else "verif_erro"] = msg
    return redirect(url_for("verificar_email"))


# ==============================================================================
# ESQUECI MINHA SENHA (cliente): código de 6 dígitos por e-mail
# ==============================================================================
MSG_CODIGO_ENVIADO = "Se este e-mail estiver cadastrado, enviamos um código de 6 dígitos. Ele vale por 10 minutos."
MSG_CODIGO_INVALIDO = "Código incorreto ou expirado. Confira o código ou peça um novo."


def _enviar_codigo_em_segundo_plano(email, nome, codigo):
    """Envia em segundo plano: o tempo de resposta não revela se o e-mail está cadastrado."""
    from threading import Thread

    def _tarefa():
        try:
            _enviar_email_codigo(email, nome, codigo, finalidade="redefinir")
        except Exception as e:
            app.logger.error("Erro ao enviar código de redefinição: %s", e)

    Thread(target=_tarefa, daemon=True).start()


def _iniciar_redefinicao_senha(email):
    """Gera e envia o código. Não devolve nada de propósito: a resposta é sempre a mesma,
    exista o e-mail ou não (evita descobrir quem é cliente)."""
    email = email.strip().lower()
    agora = _agora_utc()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM redefinicoes_senha WHERE expira_em < %s", (agora - timedelta(days=1),))
            cursor.execute("SELECT id, nome FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
            if not usuario:
                conn.commit()
                return
            cursor.execute("SELECT ultimo_envio FROM redefinicoes_senha WHERE email = %s", (email,))
            pend = cursor.fetchone()
            if pend and _segundos_de_espera(pend["ultimo_envio"], agora) > 0:
                conn.commit()
                return
            codigo = f"{secrets.randbelow(1_000_000):06d}"
            cursor.execute(
                """INSERT INTO redefinicoes_senha (email, codigo_hash, expira_em, tentativas, ultimo_envio)
                   VALUES (%s, %s, %s, 0, %s)
                   ON DUPLICATE KEY UPDATE
                       codigo_hash = VALUES(codigo_hash), expira_em = VALUES(expira_em),
                       tentativas = 0, ultimo_envio = VALUES(ultimo_envio)""",
                (email, _hash_codigo(email, codigo), agora + timedelta(minutes=CODIGO_VALIDADE_MIN), agora),
            )
            conn.commit()
        _enviar_codigo_em_segundo_plano(email, usuario["nome"], codigo)
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro ao iniciar redefinição de senha: %s", e)
    finally:
        conn.close()


def _confirmar_redefinicao_senha(email, codigo, nova_senha):
    """Confere o código e troca a senha. Retorna (ok, mensagem, status)."""
    email = email.strip().lower()
    codigo = re.sub(r"\D", "", str(codigo or ""))
    if not (8 <= len(nova_senha) <= 128):
        return False, "A nova senha deve ter entre 8 e 128 caracteres.", 400
    if len(codigo) != 6:
        return False, "Digite o código de 6 dígitos.", 400

    agora = _agora_utc()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM redefinicoes_senha WHERE email = %s FOR UPDATE", (email,))
            pend = cursor.fetchone()
            if not pend or pend["expira_em"] < agora or pend["tentativas"] >= CODIGO_MAX_TENTATIVAS:
                return False, MSG_CODIGO_INVALIDO, 400

            if not hmac.compare_digest(str(pend["codigo_hash"]), _hash_codigo(email, codigo)):
                cursor.execute("UPDATE redefinicoes_senha SET tentativas = tentativas + 1 WHERE email = %s", (email,))
                conn.commit()
                return False, MSG_CODIGO_INVALIDO, 400

            cursor.execute("UPDATE usuarios SET senha = %s WHERE email = %s", (generate_password_hash(nova_senha), email))
            if _SENHA_COL_OK:
                cursor.execute("UPDATE usuarios SET senha_cifrada = %s WHERE email = %s", (_cifrar_senha(nova_senha), email))
            cursor.execute("DELETE FROM redefinicoes_senha WHERE email = %s", (email,))
            conn.commit()
        app.logger.info("Senha redefinida por código de e-mail")
        return True, "Senha alterada com sucesso!", 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro ao redefinir senha: %s", e)
        return False, "Erro interno. Tente novamente.", 500
    finally:
        conn.close()


PAGINA_RECUPERACAO = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ titulo }} - Barbearia Versati</title>
<style>
  *{box-sizing:border-box} body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:#000;color:#fff;font-family:Arial,Helvetica,sans-serif;padding:20px}
  .card{width:100%;max-width:420px;background:#121212;border-radius:14px;padding:28px}
  h1{margin:0 0 6px;font-size:22px;color:#e5243b} p{color:#bbb;line-height:1.5;font-size:14px}
  label{display:block;margin:14px 0 6px;font-size:13px;color:#8e8e93}
  input{width:100%;padding:13px;border-radius:10px;border:1px solid #2a2a2a;background:#000;color:#fff;font-size:15px}
  input:focus{outline:none;border-color:#e5243b}
  button{width:100%;margin-top:18px;padding:14px;border:0;border-radius:10px;background:#e5243b;color:#fff;
  font-weight:bold;font-size:15px;letter-spacing:1px;cursor:pointer}
  button.sec{background:transparent;border:1px solid #333;color:#ccc;font-weight:normal;letter-spacing:0;margin-top:10px}
  .erro{background:#3a0f14;color:#ff8c98;padding:10px 12px;border-radius:8px}
  .aviso{background:#10301a;color:#8be0a4;padding:10px 12px;border-radius:8px}
  a{color:#e5243b} .rodape{text-align:center;margin-top:18px}
</style></head><body><main class="card">
<h1>{{ titulo }}</h1>
{% if erro %}<p class="erro">{{ erro }}</p>{% endif %}
{% if aviso %}<p class="aviso">{{ aviso }}</p>{% endif %}

{% if modo == "esqueci" %}
  <p>Informe o e-mail da sua conta. Vamos enviar um código para você criar uma nova senha.</p>
  <form method="post" action="{{ url_for('esqueci_senha') }}">
    <label for="email">E-mail</label>
    <input id="email" name="email" type="email" maxlength="100" autocomplete="email" required autofocus>
    <button type="submit">ENVIAR CÓDIGO</button>
  </form>
{% elif modo == "redefinir" %}
  <p>Digite o código enviado para <strong>{{ email_mascarado }}</strong> e escolha a nova senha.</p>
  <form method="post" action="{{ url_for('redefinir_senha') }}">
    <label for="codigo">Código de 6 dígitos</label>
    <input id="codigo" name="codigo" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required autofocus>
    <label for="nova_senha">Nova senha (mínimo 8 caracteres)</label>
    <input id="nova_senha" name="nova_senha" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
    <label for="confirmar_senha">Repita a nova senha</label>
    <input id="confirmar_senha" name="confirmar_senha" type="password" minlength="8" maxlength="128" autocomplete="new-password" required>
    <button type="submit">ALTERAR SENHA</button>
  </form>
  <form method="post" action="{{ url_for('reenviar_codigo_senha') }}">
    <button class="sec" type="submit">Reenviar código</button>
  </form>
{% else %}
  <p>Sua senha foi alterada. Já pode entrar com a nova senha.</p>
  <a href="{{ url_for('login') }}"><button type="button">IR PARA O LOGIN</button></a>
{% endif %}
{% if modo != "sucesso" %}<p class="rodape"><a href="{{ url_for('login') }}">Voltar para o login</a></p>{% endif %}
</main></body></html>"""


@app.route("/esqueci-senha", methods=["GET", "POST"])
@rate_limit(5, 3600, "esqueci-web")
def esqueci_senha():
    erro = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if len(email) > 100 or not EMAIL_RE.match(email):
            erro = "Informe um e-mail válido."
        else:
            _iniciar_redefinicao_senha(email)
            session["reset_email"] = email
            session["reset_aviso"] = MSG_CODIGO_ENVIADO
            return redirect(url_for("redefinir_senha"))
    return render_template("esqueci_senha.html", erro=erro)


@app.route("/redefinir-senha", methods=["GET", "POST"])
@rate_limit(15, 600, "redefinir-web")
def redefinir_senha():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("esqueci_senha"))

    erro = session.pop("reset_erro", None)
    aviso = session.pop("reset_aviso", None)

    if request.method == "POST":
        nova = request.form.get("nova_senha") or ""
        if nova != (request.form.get("confirmar_senha") or ""):
            erro = "As senhas não conferem."
        else:
            ok, msg, _status = _confirmar_redefinicao_senha(email, request.form.get("codigo"), nova)
            if ok:
                session.pop("reset_email", None)
                return render_template("login.html", erro=None) # ou redirecionar com mensagem de sucesso
            erro = msg
        aviso = None

    return render_template(
        "redefinir_senha.html", 
        email_mascarado=_mascarar_email(email), 
        erro=erro, 
        aviso=aviso
    )


@app.route("/redefinir-senha/reenviar", methods=["POST"])
@rate_limit(5, 3600, "reenviar-senha-web")
def reenviar_codigo_senha():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("esqueci_senha"))
    _iniciar_redefinicao_senha(email)
    session["reset_aviso"] = MSG_CODIGO_ENVIADO
    return redirect(url_for("redefinir_senha"))


@app.route("/agendar", methods=["GET", "POST"])
def agendar():
    if "cliente_id" not in session:
        return redirect(url_for("login"))

    cliente_id = session["cliente_id"]
    tem_assinatura = cliente_tem_assinatura_ativa(cliente_id)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, cargo FROM barbeiros WHERE ativo = 1")
            barbeiros = cursor.fetchall()
    finally:
        conn.close()

    erro = None
    if request.method == "POST":
        cliente_telefone = (request.form.get("cliente_telefone") or "").strip()
        barbeiro_id = parse_int(request.form.get("barbeiro_id"), 1)
        data = (request.form.get("data") or "").strip()
        horario = (request.form.get("horario") or "").strip()
        servico = (request.form.get("servico") or "").strip()
        tipo_pagamento = (request.form.get("tipo_pagamento") or "presencial").strip().lower()
        if tipo_pagamento not in TIPOS_PAGAMENTO:
            tipo_pagamento = "presencial"

        try:
            momento = datetime.strptime(f"{data} {horario}", "%Y-%m-%d %H:%M")
        except ValueError:
            momento = None

        if not TELEFONE_RE.match(cliente_telefone):
            erro = "Telefone inválido."
        elif barbeiro_id is None or not servico or len(servico) > 100:
            erro = "Escolha o profissional e o serviço."
        elif momento is None or horario not in HORARIOS_VALIDOS or momento < datetime.now():
            erro = "Data ou horário inválido."
        elif tipo_pagamento in ["plano", "vip"] and not cliente_tem_assinatura_ativa(cliente_id):
            erro = "Você não possui uma assinatura ativa para usar esta opção de pagamento."
        else:
            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT nome FROM barbeiros WHERE id = %s AND ativo = 1", (barbeiro_id,))
                    barb = cursor.fetchone()
                    cursor.execute("SELECT preco FROM servicos WHERE LOWER(TRIM(nome)) = LOWER(TRIM(%s))", (servico,))
                    serv_db = cursor.fetchone()

                    if not barb or not serv_db:
                        erro = "Profissional ou serviço não encontrado."
                    elif not barbeiro_realiza_servico(cursor, barbeiro_id, servico):
                        erro = "Este profissional não realiza o serviço escolhido."
                    else:
                        profissional_nome = barb['nome']
                        preco_servico = 0.00 if tipo_pagamento in ["plano", "vip"] else float(serv_db['preco'])

                        # Libera o horário de um agendamento cancelado (a UNIQUE KEY o manteria bloqueado)
                        cursor.execute(
                            "DELETE FROM agendamentos WHERE barbeiro_id = %s AND data = %s AND horario = %s "
                            "AND LOWER(status) = 'cancelado'",
                            (barbeiro_id, data, horario)
                        )
                        cursor.execute(
                            "SELECT id FROM agendamentos WHERE barbeiro_id = %s AND data = %s AND horario = %s AND status != 'cancelado'",
                            (barbeiro_id, data, horario)
                        )
                        if cursor.fetchone():
                            erro = "Este horário já está ocupado com este profissional!"
                        else:
                            try:
                                cursor.execute(
                                    """
                                    INSERT INTO agendamentos
                                    (cliente_id, barbeiro_id, profissional, data, horario, servico, tipo_pagamento, cliente_telefone, preco)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """,
                                    (cliente_id, barbeiro_id, profissional_nome, data, horario, servico, tipo_pagamento, cliente_telefone, preco_servico)
                                )
                                conn.commit()
                                return redirect(url_for("meus_agendamentos"))
                            except pymysql.err.IntegrityError:
                                erro = "Este horário já está ocupado com este profissional!"
            finally:
                conn.close()

    return render_template("agendar.html", erro=erro, tem_assinatura=tem_assinatura, barbeiros=barbeiros)

@app.route('/api/admin/agendamento/<int:agendamento_id>/concluir', methods=['POST'])
@admin_required
def concluir_agendamento(agendamento_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Atualiza o status para concluido
            cursor.execute(
                "UPDATE agendamentos SET status = 'concluido' WHERE id = %s",
                (agendamento_id,)
            )
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Atendimento concluído com sucesso!'}), 200
    except Exception as e:
        app.logger.error("Erro ao concluir agendamento: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro ao atualizar status.'}), 500
    finally:
        conn.close()
@app.route("/meus-agendamentos")
def meus_agendamentos():
    if "cliente_id" not in session:
        return redirect(url_for("login"))

    cliente_id = session["cliente_id"]
    agora = datetime.now()

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, cliente_id, barbeiro_id, profissional, data, horario, 
                       servico, tipo_pagamento, status_pagamento, status, preco 
                FROM agendamentos 
                WHERE cliente_id = %s 
                  AND LOWER(status) != 'concluido' 
                  AND LOWER(status) != 'cancelado'
                  AND (data > %s OR (data = %s AND horario >= %s))
                ORDER BY data ASC, horario ASC
                """,
                (cliente_id, agora.strftime("%Y-%m-%d"), agora.strftime("%Y-%m-%d"), agora.strftime("%H:%M"))
            )
            agendamentos = cursor.fetchall()
    finally:
        conn.close()

    return render_template("meus_agendamentos.html", agendamentos=agendamentos)


@app.route('/api/cliente/agendamentos', methods=['GET'])
def api_cliente_agendamentos():
    cliente_id = session.get('cliente_id')
    if not cliente_id:
        return jsonify({'sucesso': False, 'agendamentos': []}), 401
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, profissional, data, horario, servico, status
                FROM agendamentos
                WHERE cliente_id = %s
                ORDER BY data DESC, horario DESC
            """, (cliente_id,))
            agendamentos = cursor.fetchall()
            
            # Formata as datas para o padrão de exibição
            for ag in agendamentos:
                if hasattr(ag["data"], "strftime"):
                    ag["data"] = ag["data"].strftime("%d/%m/%Y")
                ag["horario"] = str(ag["horario"])

            return jsonify({'sucesso': True, 'agendamentos': agendamentos}), 200
    finally:
        conn.close()
@app.route("/api/admin/agendamentos/<int:id>/cancelar", methods=["POST", "PUT", "OPTIONS"])
@admin_required
def api_admin_cancelar_agendamento_status(id):
    if request.method == "OPTIONS":
        return "", 200
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE agendamentos SET status = 'cancelado', concluido_em = NULL WHERE id = %s",
                (id,)
            )
            conn.commit()
            if cursor.rowcount > 0:
                return jsonify({"sucesso": True, "mensagem": "Agendamento cancelado com sucesso!"}), 200
        return jsonify({"sucesso": False, "mensagem": "Agendamento não encontrado."}), 404
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_cancelar_agendamento_status: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()  
@app.route("/api/horarios-disponiveis")
def horarios_disponiveis():
    barbeiro_id = parse_int(request.args.get("barbeiro_id", "1"), 1)
    data = request.args.get("data", "")
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        return jsonify([])
    if barbeiro_id is None:
        return jsonify([])

    todos_horarios = []
    for hora in range(9, 20):
        todos_horarios.append(f"{hora:02d}:00")
        if hora < 19:
            todos_horarios.append(f"{hora:02d}:30")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT horario FROM agendamentos WHERE barbeiro_id = %s AND data = %s AND status != 'cancelado'",
                (barbeiro_id, data),
            )
            agendados = [r["horario"] for r in cursor.fetchall()]
    finally:
        conn.close()

    livres = [h for h in todos_horarios if h not in agendados]

    data_atual_str = datetime.now().strftime("%Y-%m-%d")
    if data == data_atual_str:
        hora_atual_str = datetime.now().strftime("%H:%M")
        livres = [h for h in livres if h >= hora_atual_str]

    return jsonify(livres)




@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("home"))


@app.errorhandler(500)
def internal_error(error):
    app.logger.error("Erro 500 Interno: %s", error)
    return jsonify({
        "sucesso": False,
        "mensagem": "Erro interno no servidor. Tente novamente mais tarde."
    }), 500

@app.errorhandler(413)
def payload_grande(error):
    return jsonify({"sucesso": False, "mensagem": "Arquivo ou requisição grande demais."}), 413


@app.errorhandler(405)
def metodo_nao_permitido(error):
    return jsonify({"sucesso": False, "mensagem": "Método não permitido."}), 405


@app.errorhandler(404)
def not_found_error(error):
    return jsonify({
        "sucesso": False,
        "mensagem": "Recurso ou rota não encontrada."
    }), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Em produção use Gunicorn/Waitress atrás de HTTPS; aqui só escuta em 127.0.0.1 por padrão
    app.run(host=os.environ.get("HOST", "127.0.0.1"), debug=DEBUG_MODE, port=port)