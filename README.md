# 💈 Barbearia Versati — Sistema de Gestão e Agendamento

> Sistema completo para barbearia composto por uma aplicação Web (Frontend para clientes e site institucional) e um Aplicativo Mobile (Painel administrativo em Flutter).

---

## 🚀 Tecnologias Utilizadas

* **Backend:** Python (Flask)
* **Banco de Dados:** MySQL
* **Frontend Web:** HTML5, CSS3, JavaScript (Jinja2 Templates)
* **Mobile (Admin):** Flutter (Dart)

---

## 📋 Funcionalidades do Sistema

### 🌐 Painel do Cliente (Site)
* **Agendamento Online:** Escolha de barbeiro, data, horário e tipo de serviço em tempo real.
* **Catálogo de Serviços e Produtos:** Visualização dinâmica dos serviços disponíveis com preços atualizados direto do banco de dados.
* **Assinatura VIP:** Opção de utilizar o plano mensal ativo diretamente na hora de agendar.
* **Histórico:** Acompanhamento de agendamentos realizados.

### 📱 Painel Administrativo (App Flutter)
* **Gerenciamento de Assinaturas:** Visualização de clientes ativos, status de pagamento e planos vigentes.
* **Cancelamento de Assinaturas:** Botão interativo para cancelar assinaturas diretamente pelo app, removendo-as automaticamente da lista de ativos.
* **Gestão de Preços:** Cadastro e alteração de valores de serviços refletindo instantaneamente no site.

---

## ⚙️ Como Executar o Projeto

### 1. Configurar o Banco de Dados
Certifique-se de ter o **MySQL** rodando localmente. O sistema cria o banco e as tabelas automaticamente ao iniciar o backend pela primeira vez.

### 2. Rodar o Backend (Flask)
```bash
# Clone o repositório
git clone (https://github.com/eduardogdantas/Barbearia-Versati)

# Acesse a pasta do projeto
cd https://github.com/eduardogdantas/Barbearia-Versati

# Instale as dependências do Python
pip install flask pymysql requests

# Execute o servidor Flask
python app.py

# Acesse a pasta do app Flutter
cd pasta_do_flutter

# Instale as dependências
flutter pub get

# Execute o aplicativo
flutter run
