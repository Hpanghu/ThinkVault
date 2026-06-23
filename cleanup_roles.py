import requests

r = requests.get('http://127.0.0.1:8000/api/roles')
roles = r.json()

for role in roles:
    if not role['is_builtin']:
        print(f'Deleting: {role["id"]} - {repr(role["name"])}')
        r_del = requests.delete(f'http://127.0.0.1:8000/api/roles/{role["id"]}')
        print(f'  Status: {r_del.status_code}')

# Verify
r = requests.get('http://127.0.0.1:8000/api/roles')
roles = r.json()
print(f'\nRemaining roles: {len(roles)}')
for role in roles:
    print(f'  {role["id"][:8]} - {repr(role["name"])} - builtin={role["is_builtin"]}')

# Test empty name
r = requests.post('http://127.0.0.1:8000/api/roles', json={'name':'', 'system_prompt':'test'})
print(f'\nEmpty name test: {r.status_code} - {r.text}')

# Test duplicate name
r = requests.post('http://127.0.0.1:8000/api/roles', json={'name':'知识馆长', 'system_prompt':'test'})
print(f'Duplicate name test: {r.status_code} - {r.text}')