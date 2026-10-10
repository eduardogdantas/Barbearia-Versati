from datetime import datetime, timedelta
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import logging
import os
import re
import time
from urllib.parse import urlparse

import pymysql

from banco import get_db_connection
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
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

sdk = mercadopago.SDK(os.environ.get("MERCADO_PAGO_ACCESS_TOKEN"))

ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")
MERCADO_PAGO_WEBHOOK_SECRET = os.environ.get("MERCADO_PAGO_WEBHOOK_SECRET")
DEBUG_MODE = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

if not ADMIN_API_TOKEN or len(ADMIN_API_TOKEN) < 24:
    logging.warning("ADMIN_API_TOKEN ausente ou curto (<24): rotas /api/admin ficam bloqueadas ou fracas.")
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
def _token_admin_valido():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not ADMIN_API_TOKEN:
        return False
    token = auth[7:].strip()
    return bool(token) and hmac.compare_digest(token.encode("utf-8"), ADMIN_API_TOKEN.encode("utf-8"))


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


garantir_coluna_concluido_em()
garantir_tabela_pagamentos()
app.json_provider_class = CustomJSONProvider

_secret = os.environ.get("FLASK_SECRET_KEY")
if not _secret or len(_secret) < 32:
    raise RuntimeError(
        "FLASK_SECRET_KEY ausente ou curta (mínimo 32 caracteres). Gere uma com: "
        "python -c \"import secrets; print(secrets.token_hex(32))\""
    )
app.secret_key = _secret

if os.environ.get("TRUST_PROXY", "").lower() == "true":
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
        if request.headers.get("Authorization"):
            return None  # chamadas com token (app) não dependem de cookie
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


@app.route('/api/servicos', methods=['GET'])
def listar_servicos_site():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    "SELECT id, nome, preco, categoria, IFNULL(foto, '') AS foto "
                    "FROM servicos ORDER BY categoria ASC, nome ASC"
                )
                servicos = cursor.fetchall()
            except Exception:
                cursor.execute("SELECT id, nome, preco, categoria FROM servicos ORDER BY categoria ASC, nome ASC")
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
            cursor.execute("SELECT id, nome, cargo, especialidade, telefone, IFNULL(foto_url, '') AS foto_url FROM barbeiros ORDER BY id ASC")
            barbeiros = cursor.fetchall()

            cursor.execute("""
                SELECT DISTINCT a.id, a.barbeiro_id, 
                        IFNULL(a.profissional, '') AS profissional, 
                        a.data, a.horario, a.servico, 
                        IFNULL(a.tipo_pagamento, 'presencial') AS tipo_pagamento, 
                        IFNULL(a.status, 'Confirmado') AS status, 
                        IFNULL(u.nome, 'Cliente') AS cliente_nome, 
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
                       IFNULL(u.nome, 'Cliente') AS cliente_nome, 
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
                       u.nome AS cliente_nome, u.telefone AS cliente_telefone
                FROM agendamentos a
                JOIN usuarios u ON a.cliente_id = u.id
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

            cursor.execute("""
                SELECT id, nome, apelido, cargo, especialidade, nivel_acesso, telefone, email,
                       IFNULL(foto_url, '') AS foto_url, exibir_agenda, ver_todas_agendas
                FROM barbeiros ORDER BY id ASC
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
            # Pega o nome do barbeiro antes de deletar para limpar agendamentos pendentes/concluídos se necessário
            cursor.execute("SELECT nome FROM barbeiros WHERE id = %s", (barbeiro_id,))
            barb = cursor.fetchone()

            # Deleta o barbeiro
            cursor.execute("DELETE FROM barbeiros WHERE id = %s", (barbeiro_id,))

            # Opcional: Se quiser limpar os agendamentos órfãos automaticamente ao deletar o barbeiro:
            if barb:
                cursor.execute("DELETE FROM agendamentos WHERE barbeiro_id = %s OR profissional = %s", (barbeiro_id, barb['nome']))

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
            cursor.execute("SELECT id, nome, email, senha FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
    finally:
        conn.close()

    if _verificar_senha(usuario, senha):
        return jsonify({
            "sucesso": True,
            "mensagem": "Login realizado com sucesso!",
            "usuario": {"id": usuario["id"], "nome": usuario["nome"], "email": usuario["email"]},
        }), 200

    return jsonify({"sucesso": False, "mensagem": "E-mail ou senha incorretos!"}), 401


@app.route("/api/cadastro", methods=["POST"])
@rate_limit(10, 3600, "cadastro-api")
def api_cadastro():
    dados = request.get_json(silent=True) or {}
    nome = str(dados.get("nome") or "").strip()
    email = str(dados.get("email") or "").strip()
    senha = str(dados.get("senha") or "")
    telefone = str(dados.get("telefone") or "").strip()

    erro = validar_cadastro(nome, email, senha, telefone)
    if erro:
        return jsonify({"sucesso": False, "mensagem": erro}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO usuarios (nome, email, senha, telefone) VALUES (%s, %s, %s, %s)",
                (nome, email, generate_password_hash(senha), telefone)
            )
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Cadastro realizado com sucesso!"}), 201
    except pymysql.err.IntegrityError:
        return jsonify({"sucesso": False, "mensagem": "E-mail já cadastrado!"}), 400
    except Exception as e:
        app.logger.error("Erro em api_cadastro: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()


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
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({'sucesso': False, 'mensagem': 'Usuário não encontrado.'}), 404
        return jsonify({'sucesso': True, 'mensagem': 'Senha alterada com sucesso!'}), 200
    except Exception as e:
        app.logger.error("Erro em api_admin_resetar_senha: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro ao alterar senha.'}), 500
    finally:
        conn.close()

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
            # 1. Agendamentos gerais do dia selecionado
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, 
                       a.tipo_pagamento, u.nome as cliente_nome, u.email as cliente_email
                FROM agendamentos a
                JOIN usuarios u ON a.cliente_id = u.id
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

            # 2. Cortes Finalizados do DIA selecionado
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, a.preco, 
                       u.nome AS cliente_nome, 
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

            # 2.1 Cortes Finalizados da SEMANA ATUAL (Reais do sistema)
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, a.preco, 
                       u.nome AS cliente_nome, 
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

            # 2.2 Cortes Finalizados do MÊS ATUAL (Reais do sistema)
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, a.preco, 
                       u.nome AS cliente_nome, 
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

            # 3. Contadores corrigidos com base em CURDATE()
            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos 
                WHERE DATE(data) = %s AND LOWER(status) IN ('concluido', 'finalizado')
            """, (data_filtro,))
            cortes_diario = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos 
                WHERE YEARWEEK(data, 1) = YEARWEEK(%s, 1) AND LOWER(status) IN ('concluido', 'finalizado')
            """, (semana_ref,))
            cortes_semanal = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos 
                WHERE MONTH(data) = MONTH(%s) AND YEAR(data) = YEAR(%s) AND LOWER(status) IN ('concluido', 'finalizado')
            """, (mes_ref, mes_ref,))
            cortes_mensal = cursor.fetchone()["total"]

            # 4. Valor total calculado para a data filtrada
            valor_total_finalizados = sum(
                float(f.get("preco") or precos_por_servico.get(str(f.get("servico")).strip().lower(), 0.0))
                for f in finalizados_raw
            )

            # 5. Serviços mais solicitados filtrados estritamente pela data selecionada
            cursor.execute("""
                SELECT servico, COUNT(*) AS quantidade
                FROM agendamentos
                WHERE DATE(data) = %s AND LOWER(status) IN ('concluido', 'finalizado')
                GROUP BY servico
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

            # 6. Receitas de assinaturas
            cursor.execute("""
                SELECT COALESCE(SUM(preco), 0) AS total
                FROM assinaturas
                WHERE LOWER(status) = 'ativo' AND data_renovacao >= CURDATE()
            """)
            receita_assinaturas_ativas = float(cursor.fetchone()["total"])

            cursor.execute("""
                SELECT COALESCE(SUM(preco), 0) AS total
                FROM assinaturas
                WHERE LOWER(status) = 'ativo' AND DATE(data_inicio) = CURDATE()
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
    
    return render_template("checkout_plano.html", plano=nome_plano, preco=preco)


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
                    a.gateway_subscription_id
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
            session.clear()  # evita fixação de sessão
            session.permanent = True
            session["cliente_id"] = usuario["id"]
            session["cliente_nome"] = usuario["nome"]
            return redirect(url_for("home"))
        erro = "E-mail ou senha incorretos!"

    return render_template("login.html", erro=erro)


@app.route("/cadastro", methods=["GET", "POST"])
@rate_limit(10, 3600, "cadastro-web")
def cadastro():
    erro = None
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")
        telefone = request.form.get("telefone", "").strip()

        erro = validar_cadastro(nome, email, senha, telefone)
        if erro:
            return render_template("cadastro.html", erro=erro)

        senha_hash = generate_password_hash(senha)
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO usuarios (nome, email, senha, telefone) VALUES (%s, %s, %s, %s)",
                    (nome, email, senha_hash, telefone)
                )
                conn.commit()
            return redirect(url_for("login"))
        except Exception as e:
            app.logger.error("Erro no cadastro: %s", e)
            erro = "E-mail já cadastrado ou erro ao processar."
        finally:
            conn.close()

    return render_template("cadastro.html", erro=erro)


@app.route("/agendar", methods=["GET", "POST"])
def agendar():
    if "cliente_id" not in session:
        return redirect(url_for("login"))

    cliente_id = session["cliente_id"]
    tem_assinatura = cliente_tem_assinatura_ativa(cliente_id)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, cargo FROM barbeiros")
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
                    cursor.execute("SELECT nome FROM barbeiros WHERE id = %s", (barbeiro_id,))
                    barb = cursor.fetchone()
                    cursor.execute("SELECT preco FROM servicos WHERE LOWER(TRIM(nome)) = LOWER(TRIM(%s))", (servico,))
                    serv_db = cursor.fetchone()

                    if not barb or not serv_db:
                        erro = "Profissional ou serviço não encontrado."
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