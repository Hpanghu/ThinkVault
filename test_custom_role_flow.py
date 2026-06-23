import requests

BASE_URL = 'http://127.0.0.1:8000'

def test_custom_role_flow():
    print("=" * 60)
    print("测试自定义角色完整流程")
    print("=" * 60)

    # 1. 获取角色列表
    print("\n1. 获取角色列表...")
    r = requests.get(f'{BASE_URL}/api/roles')
    assert r.status_code == 200, f"获取角色列表失败: {r.status_code}"
    roles_before = r.json()
    print(f"   当前角色数: {len(roles_before)}")
    for role in roles_before:
        print(f"   - {role['name']} (builtin={role['is_builtin']})")

    # 2. 创建自定义角色
    print("\n2. 创建自定义角色...")
    new_role = {
        'name': '测试自定义角色',
        'description': '用于测试的自定义角色',
        'system_prompt': '你是一位专业的测试助手，帮助用户验证系统功能。',
        'welcome_message': '欢迎使用测试角色！'
    }
    r = requests.post(f'{BASE_URL}/api/roles', json=new_role)
    assert r.status_code == 201, f"创建角色失败: {r.status_code} - {r.text}"
    created_role = r.json()
    print(f"   创建成功: {created_role['name']} (id={created_role['id']})")
    assert created_role['is_builtin'] == False, "新建角色不应是内置角色"
    assert created_role['system_prompt'] == new_role['system_prompt']
    assert created_role['welcome_message'] == new_role['welcome_message']

    # 3. 获取单个角色
    print("\n3. 获取单个角色...")
    r = requests.get(f'{BASE_URL}/api/roles/{created_role["id"]}')
    assert r.status_code == 200, f"获取角色失败: {r.status_code}"
    fetched_role = r.json()
    assert fetched_role['id'] == created_role['id']
    assert fetched_role['name'] == created_role['name']
    print(f"   获取成功: {fetched_role['name']}")

    # 4. 更新角色
    print("\n4. 更新角色...")
    update_data = {
        'name': '测试自定义角色(已更新)',
        'description': '更新后的描述'
    }
    r = requests.put(f'{BASE_URL}/api/roles/{created_role["id"]}', json=update_data)
    assert r.status_code == 200, f"更新角色失败: {r.status_code} - {r.text}"
    updated_role = r.json()
    assert updated_role['name'] == update_data['name']
    assert updated_role['description'] == update_data['description']
    print(f"   更新成功: {updated_role['name']}")

    # 5. 创建对话并关联角色
    print("\n5. 创建对话并关联角色...")
    r = requests.post(f'{BASE_URL}/api/conversations', json={
        'title': '测试对话',
        'role_id': created_role['id']
    })
    assert r.status_code == 200, f"创建对话失败: {r.status_code}"
    conversation = r.json()
    print(f"   创建成功: {conversation['title']} (role_id={conversation.get('role_id')})")

    # 6. 验证对话关联的角色
    print("\n6. 验证对话关联的角色...")
    r = requests.get(f'{BASE_URL}/api/conversations/{conversation["id"]}')
    assert r.status_code == 200, f"获取对话失败: {r.status_code}"
    conv_detail = r.json()
    assert conv_detail.get('role_id') == created_role['id'], "对话未正确关联角色"
    print(f"   验证成功: 对话角色ID = {conv_detail.get('role_id')}")

    # 7. 删除角色（需要先删除对话或强制删除）
    print("\n7. 删除角色...")
    r = requests.delete(f'{BASE_URL}/api/conversations/{conversation["id"]}')
    assert r.status_code == 200, f"删除对话失败: {r.status_code}"

    r = requests.delete(f'{BASE_URL}/api/roles/{created_role["id"]}')
    assert r.status_code == 200, f"删除角色失败: {r.status_code} - {r.text}"
    print(f"   删除成功")

    # 8. 验证角色已删除
    print("\n8. 验证角色已删除...")
    r = requests.get(f'{BASE_URL}/api/roles/{created_role["id"]}')
    assert r.status_code == 404, f"角色仍存在: {r.status_code}"
    print(f"   验证成功: 角色不存在 (404)")

    # 9. 验证内置角色不可删除
    print("\n9. 验证内置角色不可删除...")
    builtin_role_id = roles_before[0]['id']
    r = requests.delete(f'{BASE_URL}/api/roles/{builtin_role_id}')
    assert r.status_code == 400, f"内置角色不应被删除: {r.status_code}"
    print(f"   验证成功: 内置角色不可删除 (400)")

    print("\n" + "=" * 60)
    print("所有测试通过！")
    print("=" * 60)

if __name__ == '__main__':
    test_custom_role_flow()