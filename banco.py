from datetime import datetime
import pymysql


def get_db_connection():
    """Cria e retorna a conexão com o banco de dados 'barbearia'."""
    connection = pymysql.connect(
        host='localhost',
        user='root',
        password='',  # Adicione sua senha do MySQL se houver
        database='barbearia',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    return connection


def init_db():
    """Inicializa o banco de dados e cria todas as tabelas necessárias."""
    try:
        # 1. Conecta ao MySQL sem especificar o banco para criá-lo se não existir
        conn = pymysql.connect(host='localhost', user='root', password='')
        with conn.cursor() as cursor:
            cursor.execute(
                'CREATE DATABASE IF NOT EXISTS barbearia CHARACTER SET utf8mb4'
                ' COLLATE utf8mb4_unicode_ci'
            )
        conn.close()

        # 2. Conecta diretamente no banco 'barbearia' para criar as tabelas
        conn = get_db_connection()
        with conn.cursor() as cursor:

            # TABELA 1: Usuários (Clientes do aplicativo/web)
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

            # TABELA 2: Barbeiros da Barbearia
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

            # TABELA 3: Assinaturas / Planos Ativos (Gateway de Pagamento)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS assinaturas (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    cliente_id INT NOT NULL,
                    nome_plano VARCHAR(100) NOT NULL,
                    preco DECIMAL(10, 2) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    data_inicio DATE NOT NULL,
                    data_renovacao DATE NOT NULL,
                    gateway_subscription_id VARCHAR(100) UNIQUE,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (cliente_id) REFERENCES usuarios(id) ON DELETE CASCADE
                ) ENGINE=InnoDB;
            ''')

            # --- LIMPEZA PRÉVIA DE DUPLICATAS CASO EXISTAM ---
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

            # TABELA 4: Agendamentos (Com Unique Key para bloquear duplicações)
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

            # TABELA 5: Produtos (vendidos na barbearia, gerenciados pelo app e exibidos no site)
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

            # TABELA 6: Combos/Pacotes (de serviços ou de produtos, com desconto)
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

            # TABELA 7: Preço de cada tipo de serviço
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS servicos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(150) NOT NULL UNIQUE,
                    preco DECIMAL(10, 2) NOT NULL DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            ''')

            # SEGURANÇA: Garante colunas essenciais caso a tabela seja antiga
            colunas_para_verificar = [
                "ALTER TABLE agendamentos ADD COLUMN barbeiro_id INT NOT NULL DEFAULT 1;",
                "ALTER TABLE agendamentos ADD COLUMN profissional VARCHAR(100);",
                "ALTER TABLE agendamentos ADD COLUMN status VARCHAR(20) DEFAULT 'confirmado';",
                "ALTER TABLE agendamentos ADD COLUMN tipo_pagamento VARCHAR(50) DEFAULT 'presencial';",
                "ALTER TABLE agendamentos ADD COLUMN status_pagamento VARCHAR(50) DEFAULT 'pendente';",
                "ALTER TABLE agendamentos ADD COLUMN cliente_telefone VARCHAR(30);",  # <-- Adicionado aqui
                "ALTER TABLE usuarios ADD COLUMN telefone VARCHAR(20);"
            ]
            colunas_para_verificar = [
                "ALTER TABLE agendamentos ADD COLUMN barbeiro_id INT NOT NULL DEFAULT 1;",
                "ALTER TABLE agendamentos ADD COLUMN profissional VARCHAR(100);",
                "ALTER TABLE agendamentos ADD COLUMN status VARCHAR(20) DEFAULT 'confirmado';",
                "ALTER TABLE agendamentos ADD COLUMN tipo_pagamento VARCHAR(50) DEFAULT 'presencial';",
                "ALTER TABLE agendamentos ADD COLUMN status_pagamento VARCHAR(50) DEFAULT 'pendente';",
                "ALTER TABLE agendamentos ADD COLUMN cliente_telefone VARCHAR(30);",
                "ALTER TABLE agendamentos ADD COLUMN preco DECIMAL(10, 2) DEFAULT 0;",
                "ALTER TABLE usuarios ADD COLUMN telefone VARCHAR(20);"
            ]
            for comando_sql in colunas_para_verificar:
                try:
                    cursor.execute(comando_sql)
                except Exception:
                    pass  # Ignora caso a coluna já exista

            # --- POPULAR DADOS INICIAIS ---
            barbeiros_padrao = [
                ('Willian Bruno', 'Barbeiro Master', 'Cortes Clássicos e Barba', '(83) 98642-9833'),
                ('Luan', 'Barbeiro', 'Cortes em Geral', ''),
            ]
            for nome, cargo, especialidade, telefone in barbeiros_padrao:
                cursor.execute("SELECT id FROM barbeiros WHERE nome = %s", (nome,))
                if not cursor.fetchone():
                    cursor.execute(
                        '''
                            INSERT INTO barbeiros (nome, cargo, especialidade, telefone)
                            VALUES (%s, %s, %s, %s)
                        ''',
                        (nome, cargo, especialidade, telefone),
                    )
                    print(f"💈 Barbeiro '{nome}' cadastrado com sucesso!")

        conn.close()
        print('✅ Banco de dados e tabelas criados/verificados com sucesso!')

    except Exception as e:
        print('❌ Erro ao configurar o MySQL:', e)


if __name__ == '__main__':
    init_db()