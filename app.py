from datetime import datetime, timedelta
from decimal import Decimal
import os
import re
import uuid
import hmac
import hashlib

import requests

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
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps

sdk = mercadopago.SDK(os.environ.get("MERCADO_PAGO_ACCESS_TOKEN"))

ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Permite que os pedidos de pré-voo do CORS passem sem exigir o token
        if request.method == "OPTIONS":
            return "", 200
            
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        
        if not ADMIN_API_TOKEN or token != ADMIN_API_TOKEN:
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
app.json_provider_class = CustomJSONProvider
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "barbearia_versati_secret_key_prod"
)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True, allow_headers=["Content-Type", "Authorization", "X-Requested-With"], methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

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

@app.route("/api/pagamento/cartao", methods=["POST"])
def processar_pagamento_cartao():
    dados = request.get_json() or {}

    valor = float(dados.get("valor", 0.00))
    nome_plano = dados.get("nome_plano", "Plano Barbearia")
    cliente_id = dados.get("cliente_id") or session.get("cliente_id")
    
    token_cartao = dados.get("token")
    payment_method_id = dados.get("payment_method_id")
    email = dados.get("email")
    cpf_raw = dados.get("cpf")

    if not token_cartao or not email or not cpf_raw:
        return jsonify({
            "sucesso": False, 
            "mensagem": "Dados de pagamento incompletos. Informe o cartão, e-mail e CPF."
        }), 400

    if valor <= 0:
        return jsonify({
            "sucesso": False, 
            "mensagem": "Valor do pagamento inválido."
        }), 400

    cpf = re.sub(r"\D", "", str(cpf_raw))
    if len(cpf) != 11:
        return jsonify({
            "sucesso": False, 
            "mensagem": "CPF inválido."
        }), 400

    # Payload de Assinatura Recorrente Mensal (Ciclos de 30 dias no Mercado Pago)
    preapproval_data = {
        "payer_email": email,
        "back_url": "http://127.0.0.1:5000/minha-assinatura",
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
        # Cria a assinatura recorrente no gateway
        preapproval_response = sdk.preapproval().create(preapproval_data)
        response_data = preapproval_response.get("response", {})
        status_sub = response_data.get("status")

        # Status 'authorized' confirma o primeiro desconto no cartão
        if preapproval_response.get("status") in [200, 201] and status_sub == "authorized":
            subscription_id = response_data.get("id")
            data_inicio = datetime.now().date()
            data_renovacao = data_inicio + timedelta(days=30)

            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
                    # Se já existia registro, atualiza com o novo subscription_id
                    cursor.execute("SELECT id FROM assinaturas WHERE cliente_id = %s", (cliente_id,))
                    existente = cursor.fetchone()

                    if existente:
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
        else:
            return jsonify({
                "sucesso": False, 
                "mensagem": "Pagamento recusado pela operadora do cartão.",
                "detalhes": response_data
            }), 400

    except Exception as e:
        app.logger.error("Erro em processar_pagamento_cartao: %s", e)
        return jsonify({"sucesso": False, "mensagem": f"Erro interno: {str(e)}"}), 500
    
@app.route('/api/admin/cancelar-assinatura', methods=['POST'])
@admin_required
def admin_cancelar_assinatura():
    dados = request.get_json()
    assinatura_id = dados.get('assinatura_id')
    
    if not assinatura_id:
        return jsonify({'sucesso': False, 'mensagem': 'ID não informado.'}), 400
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE assinaturas 
                SET status = 'cancelado' 
                WHERE id = %s
            """, (assinatura_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Assinatura cancelada com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em admin_cancelar_assinatura: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()

def processar_renovacao_assinatura(cliente_id, cartao_token, valor):
    url_gateway = "https://api.seugateway.com/v1/cobrancas"
    payload = {
        "token_cartao": cartao_token,
        "valor": valor
    }
    
    try:
        response = requests.post(url_gateway, json=payload, timeout=10)
        dados_resposta = response.json()
        pagamento_aprovado = response.status_code == 200 and dados_resposta.get('status') == 'aprovado'
    except Exception as e:
        app.logger.error("Erro de conexão com o gateway: %s", e)
        pagamento_aprovado = False

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if pagamento_aprovado:
            cursor.execute("""
                UPDATE assinaturas 
                SET status = 'ativo', data_renovacao = DATE_ADD(CURDATE(), INTERVAL 30 DAY) 
                WHERE cliente_id = %s
            """, (cliente_id,))
        else:
            cursor.execute("""
                UPDATE assinaturas 
                SET status = 'inativo' 
                WHERE cliente_id = %s
            """, (cliente_id,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro ao atualizar banco: %s", e)
    finally:
        cursor.close()
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
        return jsonify({"sucesso": False, "tem_assinatura": False, "mensagem": f"Erro interno: {str(e)}"}), 500
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
                preco = data.get('preco', 0)
                ordem = data.get('ordem', 0)

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

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
            campos = []
            valores = []
            for campo in ('nome', 'descricao', 'preco', 'ordem', 'ativo'):
                if campo in data:
                    campos.append(f"{campo} = %s")
                    valores.append(data[campo])
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
            cursor.execute("UPDATE agendamentos SET status = 'concluido' WHERE id = %s", (id,))
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
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, cargo, especialidade, telefone FROM barbeiros ORDER BY id ASC")
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


@app.route('/api/admin/barbeiros', methods=['GET', 'POST'])
@admin_required
def gerenciar_barbeiros():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = data.get('nome')
                cargo = data.get('cargo', 'Barbeiro')
                especialidade = data.get('especialidade', 'Cortes em Geral')
                telefone = data.get('telefone', '')

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

                cursor.execute(
                    "INSERT INTO barbeiros (nome, cargo, especialidade, telefone) VALUES (%s, %s, %s, %s)",
                    (nome, cargo, especialidade, telefone)
                )
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Barbeiro cadastrado!'}), 201

            cursor.execute("SELECT id, nome, cargo, especialidade, telefone FROM barbeiros ORDER BY id ASC")
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


@app.route('/api/admin/barbeiros/<int:barbeiro_id>', methods=['DELETE'])
@admin_required
def deletar_barbeiro(barbeiro_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM barbeiros WHERE id = %s", (barbeiro_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Removido com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em deletar_barbeiro: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
    finally:
        conn.close()


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
                nome = data.get('nome')
                descricao = data.get('descricao') or 'Cuidados profissionais'
                preco = data.get('preco', 0)
                estoque = data.get('estoque', 0)
                foto = (data.get('foto') or '').strip() # Captura a foto enviada

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

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
            campos = []
            valores = []
            for campo in ('nome', 'categoria', 'preco', 'estoque'):
                if campo in data:
                    campos.append(f"{campo} = %s")
                    valores.append(data[campo])
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
                nome = data.get('nome')
                tipo = data.get('tipo', 'servico')
                descricao = data.get('descricao', '')
                sessoes = data.get('sessoes', 1)
                preco = data.get('preco', 0)
                desconto_percentual = data.get('desconto_percentual', 0)

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

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
def processar_pagamento_pix():
    dados = request.get_json() or {}

    valor = float(dados.get("valor", 0.00))
    nome_plano = dados.get("nome_plano", "Plano Barbearia")
    cliente_id = dados.get("cliente_id") or session.get("cliente_id")
    
    # Dados obrigatórios vindos do frontend (sem valores fake hardcoded)
    email = dados.get("email")
    cpf_raw = dados.get("cpf")
    nome = dados.get("nome", "Cliente")

    if not email or not cpf_raw:
        return jsonify({
            "sucesso": False,
            "mensagem": "E-mail e CPF são obrigatórios para gerar o PIX."
        }), 400

    if valor <= 0:
        return jsonify({
            "sucesso": False,
            "mensagem": "Valor do pagamento inválido."
        }), 400

    cpf = re.sub(r"\D", "", str(cpf_raw))
    if len(cpf) != 11:
        return jsonify({
            "sucesso": False,
            "mensagem": "CPF inválido."
        }), 400

    payment_data = {
        "transaction_amount": valor,
        "description": f"Assinatura {nome_plano} - Barbearia Versati",
        "payment_method_id": "pix",
        "payer": {
            "email": email,
            "first_name": nome,
            "identification": {"type": "CPF", "number": cpf},
        },
        "metadata": {
            "cliente_id": cliente_id,
            "nome_plano": nome_plano,
            "preco": valor,
        },
    }

    try:
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response.get("response", {})

        if payment_response.get("status") not in [200, 201]:
            return jsonify({"sucesso": False, "mensagem": "Erro Mercado Pago", "detalhes": payment}), 400

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
    try:
        payment_response = sdk.payment().get(pagamento_id)
        payment = payment_response.get("response", {})
        status_atual = payment.get("status")
        
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
    dados = request.get_json() or {}
    tipo_evento = request.args.get("type") or request.args.get("topic") or dados.get("type")
    data_id = request.args.get("data.id") or dados.get("data", {}).get("id")

    try:
        # Quando uma mensalidade de recorrência é cobrada com sucesso
        if tipo_evento in ["subscription_authorized_payment", "payment"] and data_id:
            info = sdk.payment().get(data_id).get("response", {})
            if info.get("status") == "approved":
                # Verifica se é cobrança de assinatura pelo preapproval_id
                preapproval_id = info.get("order", {}).get("id") or info.get("subscription_id")
                
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

        # Quando a assinatura é pausada, cancelada ou falha por falta de limite
        elif tipo_evento in ["subscription_preapproval", "preapproval"] and data_id:
            sub_info = sdk.preapproval().get(data_id).get("response", {})
            sub_status = sub_info.get("status")

            if sub_status in ["cancelled", "paused"]:
                conn = get_db_connection()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            UPDATE assinaturas 
                            SET status = 'cancelado' 
                            WHERE gateway_subscription_id = %s
                        """, (data_id,))
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
def api_login():
    dados = request.get_json() or {}
    email = dados.get("email")
    senha = dados.get("senha")

    if not email or not senha:
        return jsonify({"sucesso": False, "mensagem": "E-mail e senha obrigatórios!"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, email, senha FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
    finally:
        conn.close()

    # Compara a senha digitada com o hash salvo no banco (nunca em texto plano)
    if usuario and check_password_hash(usuario["senha"], senha):
        return jsonify({
            "sucesso": True,
            "mensagem": "Login realizado com sucesso!",
            "usuario": {"id": usuario["id"], "nome": usuario["nome"], "email": usuario["email"]},
        }), 200

    return jsonify({"sucesso": False, "mensagem": "E-mail ou senha incorretos!"}), 401


@app.route("/api/cadastro", methods=["POST"])
def api_cadastro():
    dados = request.get_json() or {}
    nome = dados.get("nome", "").strip()
    email = dados.get("email", "").strip()
    senha = dados.get("senha", "")
    telefone = dados.get("telefone", "").strip()

    if not nome or not email or not senha:
        return jsonify({"sucesso": False, "mensagem": "Preencha todos os campos obrigatórios!"}), 400

    senha_hash = generate_password_hash(senha)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO usuarios (nome, email, senha, telefone) VALUES (%s, %s, %s, %s)",
                (nome, email, senha_hash, telefone)
            )
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Cadastro realizado com sucesso!"}), 201
    except Exception:
        return jsonify({"sucesso": False, "mensagem": "E-mail já cadastrado!"}), 400
    finally:
        conn.close()
@app.route('/api/admin/usuario/<int:usuario_id>/senha', methods=['GET'])
def ver_senha_usuario(usuario_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, senha FROM usuarios WHERE id = %s", (usuario_id,))
            usuario = cursor.fetchone()
            
            if not usuario:
                return jsonify({'sucesso': False, 'mensagem': 'Usuário não encontrado'}), 404
            
            # Retorna a senha legível em texto plano
            return jsonify({'sucesso': True, 'senha': usuario['senha']})
    except Exception as e:
        app.logger.error("Erro em ver_senha_usuario: %s", e)
        return jsonify({'sucesso': False, 'mensagem': 'Erro interno. Tente novamente.'}), 500
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
    dados = request.get_json() or {}
    usuario_id = dados.get("usuario_id")
    nova_senha = dados.get("nova_senha")

    if not usuario_id or not nova_senha:
        return jsonify({"sucesso": False, "mensagem": "Dados obrigatórios!"}), 400

    senha_hash = generate_password_hash(nova_senha)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE usuarios SET senha = %s WHERE id = %s", (senha_hash, usuario_id))
            conn.commit()
            if cursor.rowcount > 0:
                return jsonify({"sucesso": True, "mensagem": "Senha atualizada!"}), 200
        return jsonify({"sucesso": False, "mensagem": "Usuário não encontrado."}), 404
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em api_admin_resetar_senha: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno. Tente novamente."}), 500
    finally:
        conn.close()



@app.route("/api/admin/dados")
@admin_required
def api_admin_dados():
    data_filtro = request.args.get("data", datetime.now().strftime("%Y-%m-%d"))
    
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

            # 2. Cortes Finalizados filtrados estritamente pela data selecionada
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

            finalizados = []
            for f in finalizados_raw:
                preco_servico = float(f.get("preco") or 0)
                if preco_servico <= 0:
                    nome_servico_chave = str(f.get("servico", "")).strip().lower()
                    preco_servico = precos_por_servico.get(nome_servico_chave, 0.0)

                f["valor"] = f"R$ {preco_servico:.2f}".replace(".", ",")
                finalizados.append(f)

            # 3. Contador Diário estritamente sincronizado com a data selecionada
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
            """, (data_filtro,))
            cortes_semanal = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM agendamentos 
                WHERE MONTH(data) = MONTH(%s) AND YEAR(data) = YEAR(%s) AND LOWER(status) IN ('concluido', 'finalizado')
            """, (data_filtro, data_filtro))
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

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE agendamentos SET status = %s WHERE id = %s", (novo_status, id))
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
    
    nome_plano = request.args.get("plano", "Plano Barbearia")
    preco = request.args.get("preco", "0.00")
    
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

                # Normalização rigorosa do status
                st = str(p.get("status") or "").strip().lower()
                if st in ["ativo", "active", "authorized", "approved", "confirmado"]:
                    p["status"] = "ativo"
                else:
                    p["status"] = "cancelado"

                planos.append(p)

            return jsonify({'sucesso': True, 'planos': planos}), 200
    except Exception as e:
        app.logger.error("Erro crítico em admin_planos_ativos: %s", str(e))
        return jsonify({'sucesso': False, 'planos': [], 'mensagem': f'Erro interno: {str(e)}'}), 500
    finally:
        conn.close()

@app.route("/api/assinaturas/assinar", methods=["POST"])
def assinar_plano():
    """Ativa ou renova a assinatura com validade de 30 dias."""
    data = request.get_json() or {}
    cliente_id = data.get("cliente_id") or session.get("cliente_id")
    nome_plano = data.get("nome_plano")
    preco = data.get("preco", 0.00)

    if not cliente_id or not nome_plano:
        return jsonify({"sucesso": False, "mensagem": "Dados incompletos."}), 400

    data_inicio = datetime.now().date()
    data_renovacao = data_inicio + timedelta(days=30)
    data_renovacao_fmt = data_renovacao.strftime("%d/%m/%Y")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM assinaturas WHERE cliente_id = %s", (cliente_id,))
            existente = cursor.fetchone()

            if existente:
                cursor.execute("""
                    UPDATE assinaturas 
                    SET nome_plano = %s, preco = %s, status = 'ativo', 
                        data_inicio = %s, data_renovacao = %s 
                    WHERE cliente_id = %s
                """, (nome_plano, preco, data_inicio, data_renovacao, cliente_id))
            else:
                cursor.execute("""
                    INSERT INTO assinaturas (cliente_id, nome_plano, preco, status, data_inicio, data_renovacao) 
                    VALUES (%s, %s, %s, 'ativo', %s, %s)
                """, (cliente_id, nome_plano, preco, data_inicio, data_renovacao))
            
            conn.commit()

        return jsonify({
            "sucesso": True, 
            "mensagem": "Assinatura ativada com sucesso!",
            "renovacao": data_renovacao_fmt
        }), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("Erro em assinar_plano: %s", e)
        return jsonify({"sucesso": False, "mensagem": "Erro interno ao processar assinatura."}), 500
    finally:
        conn.close()


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

        if usuario and check_password_hash(usuario["senha"], senha):
            session["cliente_id"] = usuario["id"]
            session["cliente_nome"] = usuario["nome"]
            return redirect(url_for("home"))
        erro = "E-mail ou senha incorretos!"

    return render_template("login.html", erro=erro)


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    erro = None
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")
        telefone = request.form.get("telefone", "").strip()

        if not nome or not email or not senha:
            erro = "Preencha todos os campos obrigatórios."
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
        cliente_telefone = request.form.get("cliente_telefone", "").strip()
        barbeiro_id_str = request.form.get("barbeiro_id")
        data = request.form.get("data")
        horario = request.form.get("horario")
        servico = request.form.get("servico")
        tipo_pagamento = request.form.get("tipo_pagamento", "presencial")

        try:
            barbeiro_id = int(barbeiro_id_str)
        except (TypeError, ValueError):
            barbeiro_id = 1

        tem_assinatura_atual = cliente_tem_assinatura_ativa(cliente_id)

        if tipo_pagamento in ["plano", "vip"] and not tem_assinatura_atual:
            erro = "Você não possui uma assinatura ativa para usar esta opção de pagamento."
        else:
            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT nome FROM barbeiros WHERE id = %s", (barbeiro_id,))
                    barb = cursor.fetchone()
                    profissional_nome = barb['nome'] if barb else "Willian Bruno"

                    cursor.execute("SELECT preco FROM servicos WHERE LOWER(TRIM(nome)) = LOWER(TRIM(%s))", (servico,))
                    serv_db = cursor.fetchone()
                    preco_servico = float(serv_db['preco']) if serv_db else 35.00

                    if tipo_pagamento in ["plano", "vip"]:
                        preco_servico = 0.00

                    cursor.execute(
                        "SELECT id FROM agendamentos WHERE barbeiro_id = %s AND data = %s AND horario = %s AND status != 'cancelado'",
                        (barbeiro_id, data, horario)
                    )
                    if cursor.fetchone():
                        erro = "Este horário já está ocupado com este profissional!"
                    else:
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
    barbeiro_id = request.args.get("barbeiro_id", "1")
    data = request.args.get("data")

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

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({
        "sucesso": False,
        "mensagem": "Recurso ou rota não encontrada."
    }), 404


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", debug=debug_mode, port=port)