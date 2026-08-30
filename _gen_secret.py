import secrets

secret = secrets.token_hex(32)  # 32 bytes = 64 hex chars

env_path = r'c:\Users\MaheenShahid\OneDrive\Desktop\studylens.ai\.env'

content = (
    "JWT_SECRET=" + secret + "\n"
    "OPENAI_API_KEY=CHANGE_ME\n"
    "UPLOAD_ROOT=uploads\n"
    "DATABASE_URL=studylens.db\n"
    "FLASK_ENV=development\n"
)

with open(env_path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verification output — never print the secret itself
with open(env_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.rstrip()
        if not line:
            continue
        key, _, val = line.partition('=')
        if key == 'JWT_SECRET':
            print(key + '=[set, ' + str(len(val)) + ' chars, not shown]')
        elif key == 'OPENAI_API_KEY':
            print(key + '=[not shown]')
        else:
            print(line)
