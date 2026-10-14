import secrets
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

print("--- SEUS NOVOS SEGREDOS ---")
print(f"FLASK_SECRET_KEY={secrets.token_hex(32)}")
print(f"SENHA_CIFRA_KEY={Fernet.generate_key().decode()}")

senha_adm = input("\nDigite a senha forte que deseja usar para o admin: ").strip()
hash_senha = generate_password_hash(senha_adm)
print(f"ADMIN_PASSWORD_HASH={hash_senha}")
print("---------------------------")