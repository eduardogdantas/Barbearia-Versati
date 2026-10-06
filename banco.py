from datetime import datetime
import getpass
import os
import re
import ssl
import sys
from urllib.parse import urlparse, parse_qs

import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

def _obter_configuracao_conexao():
    """Lê a Service URI do Aiven (DATABASE_URL) ou recorre aos campos individuais se necessário."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        path_parts = parsed.path.lstrip("/").split("?")
        dbname = path_parts[0] if path_parts else "defaultdb"
        
        query_params = parse_qs(parsed.query)
        ssl_mode = query_params.get("ssl-mode", [None])[0]

        return {
            "host": parsed.hostname,
            "user": parsed.username,
            "password": parsed.password,
            "database": dbname,
            "port": parsed.port or 3306,
            "ssl_mode": ssl_mode
        }
    
    # Fallback para variáveis individuais caso a DATABASE_URL não esteja definida
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "defaultdb"),
        "port": int(os.environ.get("DB_PORT", 3306)),
        "ssl_mode": None
    }

_cfg = _obter_configuracao_conexao()
DB_HOST = _cfg["host"]
DB_USER = _cfg["user"]
DB_PASSWORD = _cfg["password"]
DB_NAME = _cfg["database"]
DB_PORT = _cfg["port"]
DB_SSL_CA = os.environ.get("DB_SSL_CA")

if not re.fullmatch(r"[A-Za-z0-9_]+", DB_NAME):
    raise RuntimeError("DB_NAME inválido: use apenas letras, números e underline.")


def _ssl_context():
    """Configuração de SSL compatível com o Aiven."""
    if os.environ.get("DB_SSL_DISABLED", "").lower() == "true":
        return None
    if DB_HOST in ("localhost", "127.0.0.1", "::1") and not DB_SSL_CA:
        return None
    ctx = ssl.create_default_context(cafile=DB_SSL_CA) if DB_SSL_CA else ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _conectar(com_banco=True):
    kwargs = dict(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        ssl=_ssl_context(),
        connect_timeout=15,
        read_timeout=30,
        write_timeout=30,
    )
    if com_banco:
        kwargs["database"] = DB_NAME
    return pymysql.connect(**kwargs)


def get_db_connection():
    """Cria e retorna a conexão com o banco de dados configurado."""
    return _conectar(True)


def coluna_existe(cursor, tabela, coluna):
    """Verifica formalmente se uma coluna existe na tabela usando o Information Schema."""
    cursor.execute("""
        SELECT COUNT(*) AS qtd 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
    """, (DB_NAME, tabela, coluna))
    return cursor.fetchone()["qtd"] > 0


def init_db():
    """Inicializa o banco de dados e cria todas as tabelas necessárias."""
    try:
        try:
            conn = _conectar(com_banco=False)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4"
                    " COLLATE utf8mb4_unicode_ci"
                )
            conn.close()
        except Exception as e:
            print("ℹ️ Não foi possível criar o banco (seguindo com o existente):", e)

        conn = get_db_connection()
        with conn.cursor() as cursor:

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    senha VARCHAR(255) NOT NULL,
                    telefone VARCHAR(20),
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS barbeiros (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL,
                    apelido VARCHAR(100),
                    email VARCHAR(150),
                    cargo VARCHAR(50) DEFAULT 'Barbeiro',
                    nivel_acesso VARCHAR(50) DEFAULT 'Atendente',
                    especialidade VARCHAR(100) DEFAULT 'Cortes em Geral',
                    telefone VARCHAR(20),
                    foto_url MEDIUMTEXT,
                    exibir_agenda TINYINT(1) DEFAULT 1,
                    ver_todas_agendas TINYINT(1) DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS assinaturas (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    cliente_id INT NOT NULL,
                    nome_plano VARCHAR(100) NOT NULL,
                    preco DECIMAL(10, 2) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pendente',
                    data_inicio DATE NOT NULL,
                    data_renovacao DATE NOT NULL,
                    gateway_subscription_id VARCHAR(100) UNIQUE,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (cliente_id) REFERENCES usuarios(id) ON DELETE CASCADE
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS agendamentos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    cliente_id INT NOT NULL,
                    barbeiro_id INT NOT NULL DEFAULT 1,
                    profissional VARCHAR(100),
                    data DATE NOT NULL,
                    horario VARCHAR(10) NOT NULL,
                    servico VARCHAR(100) NOT NULL,
                    tipo_pagamento VARCHAR(50) DEFAULT 'presencial',
                    status_pagamento VARCHAR(50) DEFAULT 'pendente',
                    status VARCHAR(20) DEFAULT 'confirmado',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_horario_barbeiro (barbeiro_id, data, horario),
                    FOREIGN KEY (cliente_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                    FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS produtos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(150) NOT NULL,
                    descricao VARCHAR(255) DEFAULT 'Cuidados profissionais',
                    preco DECIMAL(10, 2) NOT NULL DEFAULT 0,
                    estoque INT NOT NULL DEFAULT 0,
                    ativo TINYINT(1) DEFAULT 1,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS combos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(150) NOT NULL,
                    tipo VARCHAR(20) NOT NULL DEFAULT 'servico',
                    descricao VARCHAR(255),
                    sessoes INT DEFAULT 1,
                    preco DECIMAL(10, 2) NOT NULL DEFAULT 0,
                    desconto_percentual DECIMAL(5, 2) DEFAULT 0,
                    ativo TINYINT(1) DEFAULT 1,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS servicos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(150) NOT NULL UNIQUE,
                    preco DECIMAL(10, 2) NOT NULL DEFAULT 0,
                    categoria VARCHAR(80) NOT NULL DEFAULT 'Geral',
                    foto MEDIUMTEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS planos_assinatura (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(150) NOT NULL,
                    descricao VARCHAR(255) DEFAULT '',
                    preco DECIMAL(10, 2) NOT NULL DEFAULT 0,
                    ordem INT DEFAULT 0,
                    ativo TINYINT(1) DEFAULT 1,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            cursor.execute("SELECT COUNT(*) AS total FROM planos_assinatura;")
            if cursor.fetchone()["total"] == 0:
                planos_padrao = [
                    ("Plano Corte Ilimitado Básico", "Corte quantas vezes quiser de segunda a quarta!", 79.90, 1),
                    ("Plano Corte Ilimitado Premium", "Cortes ilimitados, qualquer dia da semana!", 99.90, 2),
                    ("Plano Barba Ilimitado", "Faça a barba até 1 vez por semana com prioridade.", 99.90, 3),
                    ("Plano Corte + Barba Ilimitado", "Cabelo + barba ilimitado durante o mês inteiro.", 149.90, 4),
                ]
                for nome, descricao, preco, ordem in planos_padrao:
                    cursor.execute(
                        "INSERT INTO planos_assinatura (nome, descricao, preco, ordem) VALUES (%s, %s, %s, %s)",
                        (nome, descricao, preco, ordem)
                    )

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS barbeiro_servicos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    barbeiro_id INT NOT NULL,
                    servico_id INT NOT NULL,
                    realiza TINYINT(1) DEFAULT 1,
                    preco_personalizado DECIMAL(10, 2) DEFAULT 0.00,
                    duracao_minutos INT DEFAULT 30,
                    comissao_percentual DECIMAL(5, 2) DEFAULT 40.00,
                    FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE,
                    FOREIGN KEY (servico_id) REFERENCES servicos(id) ON DELETE CASCADE,
                    UNIQUE KEY uniq_barbeiro_servico (barbeiro_id, servico_id)
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS barbeiro_produtos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    barbeiro_id INT NOT NULL,
                    produto_id INT NOT NULL,
                    comissao_percentual DECIMAL(5, 2) DEFAULT 20.00,
                    FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE,
                    FOREIGN KEY (produto_id) REFERENCES produtos(id) ON DELETE CASCADE,
                    UNIQUE KEY uniq_barbeiro_produto (barbeiro_id, produto_id)
                ) ENGINE=InnoDB;
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS barbeiro_horarios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    barbeiro_id INT NOT NULL,
                    dia_semana TINYINT NOT NULL,
                    trabalha TINYINT(1) DEFAULT 1,
                    hora_inicio VARCHAR(5) DEFAULT '09:00',
                    hora_fim VARCHAR(5) DEFAULT '19:00',
                    almoco_inicio VARCHAR(5) DEFAULT '12:00',
                    almoco_fim VARCHAR(5) DEFAULT '13:00',
                    FOREIGN KEY (barbeiro_id) REFERENCES barbeiros(id) ON DELETE CASCADE,
                    UNIQUE KEY uniq_barbeiro_dia (barbeiro_id, dia_semana)
                ) ENGINE=InnoDB;
            ''')

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pagamentos_processados (
                    pagamento_id VARCHAR(64) PRIMARY KEY,
                    cliente_id INT NOT NULL,
                    processado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            """)

        conn.close()
        print('✅ Banco de dados e tabelas criados/verificados com sucesso!')

    except Exception as e:
        print('❌ Erro ao configurar o MySQL:', e)


if __name__ == '__main__':
    init_db()