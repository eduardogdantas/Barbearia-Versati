from datetime import datetime
import os
import pymysql
from dotenv import load_dotenv

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
                    foto VARCHAR(255) DEFAULT '',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

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
                ("servicos", "foto", "ALTER TABLE servicos ADD COLUMN foto VARCHAR(255) DEFAULT '';"),
            ]

            for tabela, coluna, comando_sql in migracoes:
                if not coluna_existe(cursor, tabela, coluna):
                    cursor.execute(comando_sql)
                    print(f"🔧 Migração aplicada: coluna '{coluna}' adicionada na tabela '{tabela}'.")

            # Popular dados iniciais
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

        conn.close()
        print('✅ Banco de dados e tabelas criados/verificados com sucesso!')

    except Exception as e:
        print('❌ Erro ao configurar o MySQL:', e)


if __name__ == '__main__':
    init_db()