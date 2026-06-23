import requests

r = requests.get('http://127.0.0.1:8000/api/roles')
roles = r.json()
for role in roles:
    print(f'{role["id"]} - {role["name"]} - builtin={role["is_builtin"]}')

# Delete empty name roles
for role in roles:
    if not role["name"].strip() and not role["is_builtin"]:
        print(f'Deleting empty name role: {role["id"]}')
        requests.delete(f'http://127.0.0.1:8000/api/roles/{role["id"]}')

# Test empty name creation
r = requests.post('http://127.0.0.1:8000/api/roles', json={'name':'', 'system_prompt':'test'})
print(f'\nEmpty name test: {r.status_code} - {r.text}')

# Test duplicate name
r = requests.post('http://127.0.0.1:8000/api/roles', json={'name':'知识馆长', 'system_prompt':'test'})
print(f'Duplicate name test: {r.status_code} - {r.text}')