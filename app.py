from datetime import datetime, timedelta
from decimal import Decimal
import os
import re
import uuid

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

# ==============================================================================
# CONFIGURAÇÃO DO MERCADO PAGO
# ==============================================================================
SDK_ACCESS_TOKEN = (
    "APP_USR-1433568876847921-082910-4bb2fa84bf01678baf504026003cf1fb-3391694524"
)
sdk = mercadopago.SDK(SDK_ACCESS_TOKEN)


# ==============================================================================
# CONFIGURAÇÃO DA APLICAÇÃO FLASK
# ==============================================================================
class CustomJSONProvider(DefaultJSONProvider):
    """Converte objetos Decimal em float para não quebrar a serialização JSON."""
    ensure_ascii = False

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.json_provider_class = CustomJSONProvider
app.json = CustomJSONProvider(app)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "barbearia_versati_secret_key_prod"
)
CORS(app)

@app.route('/api/admin/cancelar-assinatura', methods=['POST'])
def admin_cancelar_assinatura():
    dados = request.get_json()
    assinatura_id = dados.get('assinatura_id')
    
    if not assinatura_id:
        return jsonify({'sucesso': False, 'mensagem': 'ID não informado.'}), 400
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Apaga o registro da tabela de assinaturas definitivamente
            cursor.execute("""
                DELETE FROM assinaturas 
                WHERE id = %s
            """, (assinatura_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Assinatura cancelada e removida com sucesso!'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500
    finally:
        conn.close()

def processar_renovacao_assinatura(usuario_id, cartao_token, valor):
    url_gateway = "https://api.seugateway.com/v1/cobrancas"
    payload = {
        "token_cartao": cartao_token,
        "valor": valor
    }
    
    try:
        # Faz a chamada para a API do seu gateway de pagamento
        response = requests.post(url_gateway, json=payload, timeout=10)
        dados_resposta = response.json()
        
        # Verifica se o pagamento foi aprovado
        pagamento_aprovado = response.status_code == 200 and dados_resposta.get('status') == 'aprovado'
        
    except Exception as e:
        print(f"Erro de conexão com o gateway: {e}")
        pagamento_aprovado = False

    # Atualiza o banco de dados com base no resultado
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if pagamento_aprovado:
            cursor.execute("""
                UPDATE assinaturas_clientes 
                SET status = 'ativo', validade = DATE_ADD(NOW(), INTERVAL 30 DAY) 
                WHERE usuario_id = %s
            """, (usuario_id,))
        else:
            # Se deu saldo insuficiente ou recusado, altera para inativo
            cursor.execute("""
                UPDATE assinaturas_clientes 
                SET status = 'inativo' 
                WHERE usuario_id = %s
            """, (usuario_id,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Erro ao atualizar banco: {e}")
    finally:
        cursor.close()
        conn.close()

@app.route('/api/servicos', methods=['GET'])
def listar_servicos_site():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, preco FROM servicos ORDER BY nome ASC")
            servicos = cursor.fetchall()
            return jsonify({'sucesso': True, 'servicos': servicos}), 200
    except Exception as e:
        return jsonify({'sucesso': False, 'servicos': [], 'erro': str(e)}), 500
    finally:
        conn.close()

@app.route("/api/admin/agendamento/<int:id>/concluir", methods=["POST"])
def api_concluir_agendamento(id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE agendamentos SET status = 'concluido' WHERE id = %s", (id,))
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Atendimento concluído com sucesso!"}), 200
    except Exception as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        conn.close()
@app.route("/api/admin/financeiro", methods=["GET"])
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
        return jsonify({"sucesso": False, "total_cortes": 0, "valor_total": 0.0, "erro": str(e)}), 500
    finally:
        conn.close()
@app.route("/api/admin/agenda-equipe", methods=["GET"])
def api_admin_agenda_equipe():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, cargo, especialidade, telefone FROM barbeiros ORDER BY id ASC")
            barbeiros = cursor.fetchall()

            # Adicionado o filtro AND LOWER(a.status) != 'concluido' para sumir da agenda ativa
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
        return jsonify({"sucesso": False, "equipe_agenda": [], "erro": str(e)}), 500
    finally:
        conn.close()


# Rota para buscar o histórico de atendimentos concluídos por data
@app.route("/api/admin/historico", methods=["GET"])
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
                WHERE a.data = %s AND LOWER(a.status) = 'concluido'
                ORDER BY a.horario ASC
            """, (data_filtro,))
            historico = cursor.fetchall()

            for item in historico:
                if item.get("data") and hasattr(item["data"], "strftime"):
                    item["data"] = item["data"].strftime("%Y-%m-%d")

        return jsonify({"sucesso": True, "historico": historico}), 200
    except Exception as e:
        return jsonify({"sucesso": False, "historico": [], "erro": str(e)}), 500
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
        return jsonify({"sucesso": False, "agendamentos": [], "erro": str(e)}), 500
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
                  AND status = 'Ativo' 
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
                    SET nome_plano = %s, preco = %s, status = 'Ativo', data_inicio = %s, data_renovacao = %s
                    WHERE cliente_id = %s
                """
                cursor.execute(
                    sql, (nome_plano, preco, data_inicio, data_renovacao, cliente_id)
                )
            else:
                sql = """
                    INSERT INTO assinaturas (cliente_id, nome_plano, preco, status, data_inicio, data_renovacao)
                    VALUES (%s, %s, %s, 'Ativo', %s, %s)
                """
                cursor.execute(
                    sql, (cliente_id, nome_plano, preco, data_inicio, data_renovacao)
                )

            conn.commit()
    finally:
        conn.close()


# ==============================================================================
# ROTAS DA EQUIPE DE BARBEIROS (INTEGRAÇÃO WEB E APP)
# ==============================================================================
@app.route('/api/admin/barbeiros', methods=['GET', 'POST'])
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
            return jsonify({'sucesso': True, 'barbeiros': barbearia_compativel(barbeiros)}), 200
    finally:
        conn.close()

def barbearia_compativel(lista):
    return lista


@app.route('/api/admin/barbeiros/<int:barbeiro_id>', methods=['DELETE'])
def deletar_barbeiro(barbeiro_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM barbeiros WHERE id = %s", (barbeiro_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Removido com sucesso!'}), 200
    finally:
        conn.close()


# ==============================================================================
# ROTAS DE PRODUTOS (INTEGRAÇÃO WEB E APP)
# ==============================================================================
@app.route('/api/produtos', methods=['GET'])
@app.route('/api/admin/produtos', methods=['GET', 'POST'])
def gerenciar_produtos():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = data.get('nome')
                # Pega a descrição enviada pelo app, ou usa 'categoria', ou um texto padrão
                descricao = data.get('descricao') or data.get('categoria') or 'Cuidados profissionais para cabelo e barba.'
                preco = data.get('preco', 0)
                estoque = data.get('estoque', 0)

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

                # Insere o produto com a descrição no banco MySQL
                try:
                    cursor.execute(
                        "INSERT INTO produtos (nome, descricao, preco, estoque) VALUES (%s, %s, %s, %s)",
                        (nome, descricao, preco, estoque)
                    )
                except Exception:
                    # Fallback caso a coluna ainda se chame categoria no banco antigo
                    cursor.execute(
                        "INSERT INTO produtos (nome, categoria, preco, estoque) VALUES (%s, %s, %s, %s)",
                        (nome, descricao, preco, estoque)
                    )

                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Produto cadastrado!', 'id': cursor.lastrowid}), 201

            # Busca os produtos para exibir na web e no app
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


@app.route('/api/admin/produtos/<int:produto_id>', methods=['PUT', 'DELETE'])
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
    finally:
        conn.close()


# ==============================================================================
# ROTAS DE COMBOS / PACOTES (INTEGRAÇÃO WEB E APP)
# ==============================================================================
@app.route('/api/combos', methods=['GET'])
@app.route('/api/admin/combos', methods=['GET', 'POST'])
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
    finally:
        conn.close()


@app.route('/api/admin/combos/<int:combo_id>', methods=['DELETE'])
def remover_combo(combo_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM combos WHERE id = %s", (combo_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Combo removido!'}), 200
    finally:
        conn.close()


# ==============================================================================
# ROTAS DE PREÇOS DE SERVIÇOS (USADO PELO FINANCEIRO)
# ==============================================================================
@app.route('/api/admin/servicos', methods=['GET', 'POST'])
def gerenciar_servicos():
    """GET: lista os preços cadastrados. POST: cadastra ou atualiza o preço de um serviço
    (usa o nome do serviço como chave, pois é o que já vem do formulário de agendamento)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                nome = (data.get('nome') or '').strip()
                preco = data.get('preco', 0)

                if not nome:
                    return jsonify({'sucesso': False, 'mensagem': 'Nome obrigatório'}), 400

                cursor.execute(
                    """INSERT INTO servicos (nome, preco) VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE preco = VALUES(preco)""",
                    (nome, preco)
                )
                conn.commit()
                return jsonify({'sucesso': True, 'mensagem': 'Preço salvo!'}), 201

            cursor.execute("SELECT id, nome, preco FROM servicos ORDER BY nome ASC")
            servicos = cursor.fetchall()
            return jsonify({'sucesso': True, 'servicos': servicos}), 200
    finally:
        conn.close()


@app.route('/api/admin/servicos/<int:servico_id>', methods=['DELETE'])
def remover_servico(servico_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM servicos WHERE id = %s", (servico_id,))
            conn.commit()
            return jsonify({'sucesso': True, 'mensagem': 'Preço removido!'}), 200
    finally:
        conn.close()


# ==============================================================================
# ROTAS DE PAGAMENTO E WEBHOOK (MERCADO PAGO)
# ==============================================================================
@app.route("/api/pagamento/pix", methods=["POST"])
def processar_pagamento_pix():
    dados = request.get_json() or {}

    valor = float(dados.get("valor", 1.00))
    nome = dados.get("nome", "Cliente Teste")
    cliente_id = dados.get("cliente_id") or session.get("cliente_id")
    nome_plano = dados.get("nome_plano", "Plano Barbearia")

    cpf = re.sub(r"\D", "", str(dados.get("cpf", "70069889422")))
    email = f"comprador_teste_{uuid.uuid4().hex[:6]}@gmail.com"

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
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500


@app.route("/api/pagamento/status/<int:pagamento_id>", methods=["GET"])
def verificar_status_pagamento(pagamento_id):
    try:
        payment_response = sdk.payment().get(pagamento_id)
        payment = payment_response.get("response", {})
        return jsonify({
            "status": payment.get("status"),
            "detalhe": payment.get("status_detail"),
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/webhook", methods=["POST"])
def webhook_mercadopago():
    dados = request.get_json() or {}
    tipo_evento = request.args.get("type") or request.args.get("topic") or dados.get("type")
    pagamento_id = request.args.get("data.id") or request.args.get("id") or dados.get("data", {}).get("id")

    if tipo_evento in ["payment", "order"] and pagamento_id:
        try:
            info = sdk.payment().get(pagamento_id).get("response", {})
            if info.get("status") == "approved":
                metadata = info.get("metadata", {})
                cliente_id = metadata.get("cliente_id")
                nome_plano = metadata.get("nome_plano")
                preco = metadata.get("preco", 0.0)

                if cliente_id and nome_plano:
                    ativar_assinatura_banco(cliente_id, nome_plano, preco)
        except Exception as e:
            print(f"Erro no Webhook: {e}")

    return jsonify({"status": "ok"}), 200


# ==============================================================================
# ROTAS DE AUTENTICAÇÃO (API & SESSION)
# ==============================================================================
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
    nome = dados.get("nome")
    email = dados.get("email")
    senha = dados.get("senha")

    if not nome or not email or not senha:
        return jsonify({"sucesso": False, "mensagem": "Preencha todos os campos!"}), 400

    senha_hash = generate_password_hash(senha)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s)", (nome, email, senha_hash))
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Cadastro realizado!"}), 201
    except Exception:
        return jsonify({"sucesso": False, "mensagem": "E-mail já cadastrado!"}), 400
    finally:
        conn.close()


# ==============================================================================
# ROTAS DO PAINEL ADMIN (APP FLUTTER)
# ==============================================================================
@app.route("/api/admin/usuarios", methods=["GET"])
def api_admin_usuarios():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, nome, email FROM usuarios ORDER BY id DESC")
            usuarios = cursor.fetchall()
            for u in usuarios:
                if not u.get("nome"):
                    u["nome"] = "Cliente sem nome"
                u["senha"] = "••••••••"
        return jsonify({"sucesso": True, "usuarios": usuarios}), 200
    finally:
        conn.close()


@app.route("/api/admin/resetar-senha", methods=["POST"])
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
    finally:
        conn.close()


@app.route("/api/admin/dados")
def api_admin_dados():
    data_filtro = request.args.get("data", datetime.now().strftime("%Y-%m-%d"))
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT a.id, a.profissional, a.data, a.horario, a.servico, 
                       a.tipo_pagamento, u.nome as cliente_nome, u.email as cliente_email
                FROM agendamentos a
                JOIN usuarios u ON a.cliente_id = u.id
                WHERE a.data = %s
                ORDER BY a.horario ASC
            """, (data_filtro,))
            agendamentos_raw = cursor.fetchall()

            agendamentos = []
            for row in agendamentos_raw:
                data_val = row["data"]
                if hasattr(data_val, "strftime"):
                    data_val = data_val.strftime("%Y-%m-%d")
                else:
                    data_val = str(data_val)

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

            cursor.execute("SELECT COUNT(*) as total FROM agendamentos WHERE DATE(data) = CURDATE()")
            cortes_diario = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as total FROM agendamentos WHERE YEARWEEK(data, 1) = YEARWEEK(CURDATE(), 1)")
            cortes_semanal = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as total FROM agendamentos WHERE MONTH(data) = MONTH(CURDATE()) AND YEAR(data) = YEAR(CURDATE())")
            cortes_mensal = cursor.fetchone()["total"]

            # ATUALIZADO: Traz o telefone do agendamento ou do cadastro do usuário
            cursor.execute("""
                SELECT a.id, a.profissional, a.horario, a.servico, a.preco, 
                       u.nome AS cliente_nome, 
                       IFNULL(NULLIF(a.cliente_telefone, ''), IFNULL(u.telefone, 'Não informado')) AS cliente_telefone
                FROM agendamentos a
                LEFT JOIN usuarios u ON a.cliente_id = u.id
                WHERE a.data = %s AND LOWER(a.status) IN ('concluido', 'finalizado')
                ORDER BY a.horario ASC
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

                # Se ainda continuar zero, definimos 0.00 para você notar se o serviço não foi cadastrado nos preços
                if preco_servico <= 0:
                    preco_servico = 0.00

                f["valor"] = f"R$ {preco_servico:.2f}".replace(".", ",")
                finalizados.append(f)

            cursor.execute("""
                SELECT a.servico, a.preco, COUNT(*) AS qtd
                FROM agendamentos a
                WHERE LOWER(a.status) IN ('concluido', 'finalizado')
                GROUP BY a.servico, a.preco
            """)
            valor_total_finalizados = 0.0
            for row in cursor.fetchall():
                p = float(row.get("preco") or 0)
                if p <= 0:
                    p = precos_por_servico.get(str(row["servico"]).strip().lower(), 0.0)
                valor_total_finalizados += p * row["qtd"]

            cursor.execute("""
                SELECT servico, COUNT(*) AS quantidade
                FROM agendamentos
                WHERE LOWER(status) != 'cancelado'
                GROUP BY servico
                ORDER BY quantidade DESC
                LIMIT 5
            """)
            servicos_raw = cursor.fetchall()
            total_servicos = sum(s["quantidade"] for s in servicos_raw) or 1
            servicos_mais_solicitados = [
                {
                    "nome": s["servico"],
                    "quantidade": s["quantidade"],
                    "porcentagem": round(s["quantidade"] / total_servicos, 2),
                }
                for s in servicos_raw
            ]

            cursor.execute("""
                SELECT COALESCE(SUM(preco), 0) AS total
                FROM assinaturas
                WHERE status = 'Ativo' AND data_renovacao >= CURDATE()
            """)
            receita_assinaturas_ativas = float(cursor.fetchone()["total"])

            cursor.execute("""
                SELECT COALESCE(SUM(preco), 0) AS total
                FROM assinaturas
                WHERE status = 'Ativo' AND DATE(data_inicio) = CURDATE()
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
    finally:
        conn.close()


@app.route("/api/admin/cancelar-agendamento/<int:id>", methods=["DELETE"])
def api_admin_cancelar_agendamento(id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM agendamentos WHERE id = %s", (id,))
            conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Cancelado!"}), 200
    finally:
        conn.close()

@app.route("/checkout-plano", methods=["GET"])
def checkout_plano():
    if "cliente_id" not in session:
        return redirect(url_for("login"))
    
    # Pega os parâmetros passados pela URL (nome do plano e preço)
    nome_plano = request.args.get("plano", "Plano Barbearia")
    preco = request.args.get("preco", "0.00")
    
    # Você pode renderizar uma página de checkout ou reutilizar uma existente
    return render_template("checkout_plano.html", plano=nome_plano, preco=preco)


# 1. Rota que renderiza o visual com HTML e CSS (o layout bonito)
# Rota que entrega o arquivo HTML estilizado para o navegador
@app.route("/planos", methods=["GET"])
def pagina_planos():
    return render_template("planos.html", cliente_id=session.get("cliente_id"), cliente_nome=session.get("cliente_nome"))

# Rota de API separada para fornecer os dados JSON (se o seu front-end precisar consumir via fetch)
@app.route('/api/admin/planos-ativos', methods=['GET'])
def admin_planos_ativos():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Adicionamos o filtro WHERE status = 'ativo' para sumir os inativos/cancelados
            cursor.execute("""
                SELECT 
                    a.id, 
                    u.nome AS cliente_nome, 
                    u.email AS cliente_email, 
                    COALESCE(a.nome_plano, 'Plano Mensal') AS nome,
                    COALESCE(a.preco, 99.90) AS preco,
                    DATE_FORMAT(a.data_renovacao, '%d/%m/%Y') AS validade,
                    a.status
                FROM assinaturas AS a
                JOIN usuarios AS u ON a.cliente_id = u.id
                WHERE a.status = 'ativo' OR a.status = 'active'
                ORDER BY a.id DESC
            """)
            planos = cursor.fetchall()
            return jsonify({'sucesso': True, 'planos': planos}), 200
    except Exception as e:
        return jsonify({'sucesso': False, 'planos': [], 'erro': str(e)}), 500
    finally:
        conn.close()

@app.route("/api/assinaturas/assinar", methods=["POST"])
def assinar_plano():
    data = request.get_json() or {}
    cliente_id = data.get("cliente_id")
    nome_plano = data.get("nome_plano")
    preco = data.get("preco")

    if not cliente_id or not nome_plano:
        return jsonify({"sucesso": False, "mensagem": "Dados incompletos."}), 400

    data_inicio = datetime.now().date()
    data_renovacao = data_inicio + timedelta(days=30)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM assinaturas WHERE cliente_id = %s AND status = 'Ativo'", (cliente_id,))
            if cursor.fetchone():
                return jsonify({"sucesso": False, "mensagem": "Você já possui um plano ativo."}), 400

            cursor.execute(
                "INSERT INTO assinaturas (cliente_id, nome_plano, preco, status, data_inicio, data_renovacao) VALUES (%s, %s, %s, 'Ativo', %s, %s)",
                (cliente_id, nome_plano, preco, data_inicio, data_renovacao)
            )
            conn.commit()

        return jsonify({"sucesso": True, "mensagem": "Assinatura realizada com sucesso!"})
    finally:
        conn.close()


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
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")

        senha_hash = generate_password_hash(senha)
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s)", (nome, email, senha_hash))
                conn.commit()
            return redirect(url_for("login"))
        except Exception as e:
            erro = f"Erro no cadastro: {str(e)}"
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

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Busca o nome do barbeiro
                cursor.execute("SELECT nome FROM barbeiros WHERE id = %s", (barbeiro_id,))
                barb = cursor.fetchone()
                profissional_nome = barb['nome'] if barb else "Willian Bruno"

                # Busca o preço correto na tabela de serviços
                cursor.execute("SELECT preco FROM servicos WHERE LOWER(TRIM(nome)) = LOWER(TRIM(%s))", (servico,))
                serv_db = cursor.fetchone()
                preco_servico = float(serv_db['preco']) if serv_db else 35.00
        finally:
            conn.close()

        if tipo_pagamento == "plano" and not tem_assinatura:
            erro = "Você não possui uma assinatura ativa para usar esta opção."
        else:
            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
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

    # GARANTIA: Se houver algum erro (como horário ocupado ou falta de plano), a página é renderizada novamente exibindo o erro
    return render_template("agendar.html", erro=erro, tem_assinatura=tem_assinatura, barbeiros=barbeiros)


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
                SELECT * FROM agendamentos 
                WHERE cliente_id = %s AND (data > %s OR (data = %s AND horario >= %s))
                ORDER BY data ASC, horario ASC
                """,
                (cliente_id, agora.strftime("%Y-%m-%d"), agora.strftime("%Y-%m-%d"), agora.strftime("%H:%M"))
            )
            agendamentos = cursor.fetchall()
    finally:
        conn.close()

    return render_template("meus_agendamentos.html", agendamentos=agendamentos)


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
    return jsonify(livres)


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
    finally:
        conn.close()

    return redirect(url_for("meus_agendamentos"))


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)