from datetime import datetime
import os
import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "barbearia")


def get_db_connection():
    """Cria e retorna a conexão com o banco de dados configurado."""
    connection = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    return connection


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
        # 1. Conecta ao MySQL sem especificar o banco para criá-lo se não existir
        conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
        with conn.cursor() as cursor:
            cursor.execute(
                f'CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4'
                ' COLLATE utf8mb4_unicode_ci'
            )
        conn.close()

        # 2. Conecta diretamente no banco para criar as tabelas
        conn = get_db_connection()
        with conn.cursor() as cursor:

            # TABELA 1: Usuários
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

            # TABELA 2: Barbeiros
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS barbeiros (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL,
                    cargo VARCHAR(50) DEFAULT 'Barbeiro',
                    especialidade VARCHAR(100) DEFAULT 'Cortes em Geral',
                    telefone VARCHAR(20),
                    foto_url VARCHAR(255),
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            # TABELA 3: Assinaturas
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

            # Limpeza prévia de duplicatas em agendamentos
            try:
                cursor.execute('''
                    DELETE a1 FROM agendamentos a1
                    JOIN agendamentos a2 
                      ON a1.barbeiro_id = a2.barbeiro_id 
                      AND a1.data = a2.data 
                      AND a1.horario = a2.horario 
                      AND a1.id > a2.id;
                ''')
            except Exception:
                pass

            # TABELA 4: Agendamentos
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

            # TABELA 5: Produtos
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

            # TABELA 6: Combos
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

            # TABELA 7: Serviços
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

            # TABELA 8: Catálogo de Planos de Assinatura (nome/preço/descrição exibidos
            # na página "Planos de Assinatura" do site e editáveis pelo app admin)
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

            # Popular o catálogo de planos com os que já existem hoje fixos no site,
            # só na primeira vez (assim você não perde os que já tem cadastrado).
            cursor.execute("SELECT COUNT(*) AS total FROM planos_assinatura;")
            if cursor.fetchone()["total"] == 0:
                planos_padrao = [
                    ("Plano Corte Ilimitado Básico", "Corte quantas vezes quiser de segunda a quarta!", 79.90, 1),
                    ("Plano Corte Ilimitado Premium", "Cortes ilimitados, qualquer dia da semana!", 99.90, 2),
                    ("Plano Corte + Barba Ilimitado", "Cabelo + barba ilimitado durante o mês inteiro.", 149.90, 3),
                ]
                for nome, descricao, preco, ordem in planos_padrao:
                    cursor.execute(
                        "INSERT INTO planos_assinatura (nome, descricao, preco, ordem) VALUES (%s, %s, %s, %s)",
                        (nome, descricao, preco, ordem)
                    )
                print("💳 Catálogo de planos de assinatura populado com os planos padrão!")

            # Migrações formais e seguras por Schema Check
            migracoes = [
                ("agendamentos", "barbeiro_id", "ALTER TABLE agendamentos ADD COLUMN barbeiro_id INT NOT NULL DEFAULT 1;"),
                ("agendamentos", "profissional", "ALTER TABLE agendamentos ADD COLUMN profissional VARCHAR(100);"),
                ("agendamentos", "status", "ALTER TABLE agendamentos ADD COLUMN status VARCHAR(20) DEFAULT 'confirmado';"),
                ("agendamentos", "tipo_pagamento", "ALTER TABLE agendamentos ADD COLUMN tipo_pagamento VARCHAR(50) DEFAULT 'presencial';"),
                ("agendamentos", "status_pagamento", "ALTER TABLE agendamentos ADD COLUMN status_pagamento VARCHAR(50) DEFAULT 'pendente';"),
                ("agendamentos", "cliente_telefone", "ALTER TABLE agendamentos ADD COLUMN cliente_telefone VARCHAR(30);"),
                ("agendamentos", "preco", "ALTER TABLE agendamentos ADD COLUMN preco DECIMAL(10, 2) DEFAULT 0;"),
                ("usuarios", "telefone", "ALTER TABLE usuarios ADD COLUMN telefone VARCHAR(20);"),
                ("servicos", "categoria", "ALTER TABLE servicos ADD COLUMN categoria VARCHAR(80) NOT NULL DEFAULT 'Geral';"),
                ("servicos", "foto", "ALTER TABLE servicos ADD COLUMN foto MEDIUMTEXT;"),
                ("produtos", "foto", "ALTER TABLE produtos ADD COLUMN foto MEDIUMTEXT;"),
            ]

            for tabela, coluna, comando_sql in migracoes:
                if not coluna_existe(cursor, tabela, coluna):
                    cursor.execute(comando_sql)
                    print(f"🔧 Migração aplicada: coluna '{coluna}' adicionada na tabela '{tabela}'.")

            # Corrige o tamanho da coluna 'foto' caso já exista pequena demais
            # (imagens em base64 não cabem em VARCHAR(255)).
            for tabela in ("servicos", "produtos"):
                try:
                    cursor.execute(f"ALTER TABLE {tabela} MODIFY COLUMN foto MEDIUMTEXT;")
                except Exception:
                    pass

            # Popular dados iniciais de barbeiros
            barbeiros_padrao = [
                ('Willian Bruno', 'Barbeiro Master', 'Cortes Clássicos e Barba', '(83) 98642-9833'),
                ('Luan', 'Barbeiro', 'Cortes em Geral', ''),
            ]
            for nome, cargo, especialidade, telefone in barbeiros_padrao:
                cursor.execute("SELECT id FROM barbeiros WHERE nome = %s", (nome,))
                if not cursor.fetchone():
                    cursor.execute(
                        'INSERT INTO barbeiros (nome, cargo, especialidade, telefone) VALUES (%s, %s, %s, %s)',
                        (nome, cargo, especialidade, telefone),
                    )
                    print(f"💈 Barbeiro '{nome}' cadastrado com sucesso!")

            # Garantir o utilizador Administrador padrão (senha SEMPRE com hash, nunca em texto plano)
            senha_admin_hash = generate_password_hash('La20072016')
            cursor.execute("SELECT id FROM usuarios WHERE email = %s", ('eduardogdantasjp@gmail.com',))
            if not cursor.fetchone():
                cursor.execute(
                    'INSERT INTO usuarios (nome, email, senha, telefone) VALUES (%s, %s, %s, %s)',
                    ('Eduardo Admin', 'eduardogdantasjp@gmail.com', senha_admin_hash, '(83) 98813-9461')
                )
                print("👑 Utilizador Administrador padrão criado com sucesso!")
            else:
                # Atualiza a senha caso já exista, sempre com hash
                cursor.execute(
                    "UPDATE usuarios SET senha = %s WHERE email = %s",
                    (senha_admin_hash, 'eduardogdantasjp@gmail.com')
                )

        conn.close()
        print('✅ Banco de dados e tabelas criados/verificados com sucesso!')

    except Exception as e:
        print('❌ Erro ao configurar o MySQL:', e)


if __name__ == '__main__':
    init_db()