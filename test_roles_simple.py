import requests

# Get roles
r = requests.get('http://127.0.0.1:8000/api/roles')
print('Status:', r.status_code)
roles = r.json()
print('Roles:', len(roles))
for role in roles:
    print(role['id'][:8], '-', repr(role['name']), '-', role['is_builtin'])