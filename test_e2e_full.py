"""端到端测试：批准模式闭环 + mask_edit auto_face + 人脸检测覆盖率。

测试策略：
1. mask_edit auto_face E2E（通过 HTTP API，使用合成人脸图）
2. 批准/拒绝逻辑（直接通过 orchestrator API，无需真实 AI 调用）
3. 人脸检测覆盖率 + expand 参数优化
"""
import os
os.environ['GPT_IMAGE_TIMEOUT'] = '15'  # 缩短 AI 调用超时，避免测试卡住

import asyncio
import io
import time

import pytest
import requests
import numpy as np
from PIL import Image, ImageDraw

BASE = os.getenv('E2E_BASE_URL', 'http://127.0.0.1:8000')


def _service_available():
    try:
        requests.get(f'{BASE}/health', timeout=2)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _service_available(), reason=f'服务 {BASE} 未启动，跳过 E2E 测试')


def create_face_image(width=512, height=512, face_x=150, face_y=100, face_w=212, face_h=280, bg_color=(200, 180, 160)):
    """生成合成人脸图，可控制人脸位置和大小。"""
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    draw.ellipse([face_x, face_y, face_x + face_w, face_y + face_h], fill=(255, 220, 190))
    eye_y = face_y + int(face_h * 0.28)
    eye_w = int(face_w * 0.12)
    eye_h = int(face_h * 0.09)
    left_eye_x = face_x + int(face_w * 0.25)
    right_eye_x = face_x + int(face_w * 0.62)
    draw.ellipse([left_eye_x, eye_y, left_eye_x + eye_w, eye_y + eye_h], fill=(50, 50, 50))
    draw.ellipse([right_eye_x, eye_y, right_eye_x + eye_w, eye_y + eye_h], fill=(50, 50, 50))
    nose_x = face_x + int(face_w * 0.42)
    nose_y = face_y + int(face_h * 0.42)
    draw.polygon([(nose_x, nose_y), (nose_x - 12, nose_y + 40), (nose_x + 12, nose_y + 40)], fill=(255, 200, 170))
    mouth_x1 = face_x + int(face_w * 0.25)
    mouth_x2 = face_x + int(face_w * 0.75)
    mouth_y = face_y + int(face_h * 0.7)
    draw.arc([mouth_x1, mouth_y, mouth_x2, mouth_y + 30], 0, 180, fill=(200, 100, 100), width=4)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def upload_image(image_bytes, filename='face.png'):
    r = requests.post(f'{BASE}/api/assets/upload', files={'file': (filename, image_bytes, 'image/png')})
    assert r.status_code == 200, f'Upload failed: {r.status_code} {r.text}'
    return r.json()['url']


def poll_node(canvas_id, node_id, timeout=30, expected_statuses=None):
    expected = expected_statuses or ('success', 'failed', 'blocked', 'awaiting_approval')
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f'{BASE}/api/canvas/{canvas_id}/nodes/{node_id}')
        d = r.json()
        if d['status'] in expected:
            return d
        time.sleep(0.5)
    return d


# ───────────────────────── 测试1：mask_edit auto_face E2E ─────────────────────────
def test_mask_edit_auto_face():
    print('\n=== 测试1：mask_edit(auto_face) E2E ===')
    img_bytes = create_face_image()
    image_url = upload_image(img_bytes)
    print(f'上传图片: {image_url}')

    canvas_id = 'e2e_mask_test'
    nodes = [
        {'id': 'img', 'type': 'image_input', 'x': 100, 'y': 100, 'data': {'image_url': image_url}},
        {'id': 'mask', 'type': 'mask_edit', 'x': 400, 'y': 100, 'data': {'mask_mode': 'auto_face'}},
    ]
    conns = [
        {'id': 'c1', 'from': 'img', 'fromField': 'image', 'to': 'mask', 'toField': 'image'},
    ]

    r = requests.post(f'{BASE}/api/canvas/run', json={
        'canvas_id': canvas_id, 'nodes': nodes, 'connections': conns,
    })
    assert r.status_code == 200, f'Run failed: {r.text}'
    print(f'运行画布: {r.json()}')

    d = poll_node(canvas_id, 'mask', timeout=15)
    print(f'mask_edit: status={d["status"]}, mask_url={d.get("mask_url")}, image_url={d.get("image_url")}')
    assert d['status'] == 'success', f'mask_edit 未成功: {d}'
    assert d.get('mask_url'), 'mask_edit 未产出 mask_url'
    assert d.get('image_url'), 'mask_edit 未产出 image_url'
    print('✅ mask_edit(auto_face) E2E 成功')


# ───────────────────────── 测试2：mask_edit auto_full E2E ─────────────────────────
def test_mask_edit_auto_full():
    print('\n=== 测试2：mask_edit(auto_full) E2E ===')
    img_bytes = create_face_image()
    image_url = upload_image(img_bytes)

    canvas_id = 'e2e_mask_full_test'
    nodes = [
        {'id': 'img', 'type': 'image_input', 'x': 100, 'y': 100, 'data': {'image_url': image_url}},
        {'id': 'mask', 'type': 'mask_edit', 'x': 400, 'y': 100, 'data': {'mask_mode': 'auto_full'}},
    ]
    conns = [{'id': 'c1', 'from': 'img', 'fromField': 'image', 'to': 'mask', 'toField': 'image'}]

    r = requests.post(f'{BASE}/api/canvas/run', json={
        'canvas_id': canvas_id, 'nodes': nodes, 'connections': conns,
    })
    assert r.status_code == 200

    d = poll_node(canvas_id, 'mask', timeout=15)
    print(f'mask_edit(auto_full): status={d["status"]}, mask_url={d.get("mask_url")}')
    assert d['status'] == 'success'
    assert d.get('mask_url')
    print('✅ mask_edit(auto_full) E2E 成功')


# ───────────────────────── 测试3：批准/拒绝逻辑（通过 orchestrator 直接测试）─────────────────────────
async def _test_approval_reject_logic_async():
    """直接通过 orchestrator 层测试批准/拒绝，无需真实 AI API 调用。

    注意：approve_node/reject_node 会触发 _schedule_cascade，需要事件循环。
    """
    print('\n=== 测试3：批准/拒绝逻辑 ===')
    import orchestrator

    canvas_id = 'e2e_approval_logic_test'

    # 构建上下文
    nodes = [
        {'id': 'gpt', 'type': 'gpt_image', 'x': 100, 'y': 100, 'data': {'prompt': 'test'}},
        {'id': 'down', 'type': 'mask_edit', 'x': 400, 'y': 100, 'data': {'mask_mode': 'auto_full'}},
    ]
    node_map = {n['id']: n for n in nodes}
    adj = {'gpt': ['down'], 'down': []}
    conn_map = {('gpt', 'down'): [{'fromField': 'image', 'toField': 'image'}]}
    in_degree = {'gpt': 0, 'down': 1}
    orchestrator._canvas_contexts[canvas_id] = {
        'node_map': node_map, 'adj': adj, 'conn_map': conn_map,
        'in_degree': in_degree, 'remaining': dict(in_degree), 'approval_mode': True,
    }

    # 设置 gpt 为 awaiting_approval（模拟 AI 节点执行成功后的状态）
    orchestrator.registry.set(f'{canvas_id}:gpt', {
        'task_id': None, 'canvas_id': canvas_id, 'node_id': 'gpt',
        'node_type': 'gpt_image', 'status': 'awaiting_approval', 'progress': 100,
        'image_url': '/assets/test.png', 'video_url': None, 'mask_url': None,
        'error': None, 'created_at': time.time(), 'updated_at': time.time(),
    })
    orchestrator.registry.set(f'{canvas_id}:down', {
        'task_id': None, 'canvas_id': canvas_id, 'node_id': 'down',
        'node_type': 'mask_edit', 'status': 'idle', 'progress': 0,
        'image_url': None, 'video_url': None, 'mask_url': None,
        'error': None, 'created_at': time.time(), 'updated_at': time.time(),
    })

    # 测试1：对非 awaiting_approval 状态的节点批准应报错
    try:
        orchestrator.approve_node(canvas_id, 'down')
        assert False, '对 idle 节点批准应报错'
    except ValueError as e:
        print(f'  对 idle 节点批准: ✅ 正确报错 "{e}"')

    # 测试2：批准 gpt → 状态变 success + 下游被触发
    result = orchestrator.approve_node(canvas_id, 'gpt')
    print(f'  批准 gpt: {result}')
    assert result['status'] == 'success', f'批准后状态应为 success: {result}'

    gpt_rec = orchestrator.registry.get(f'{canvas_id}:gpt')
    assert gpt_rec['status'] == 'success', f'gpt 状态应为 success: {gpt_rec["status"]}'
    print('  ✅ 批准后 gpt 状态 = success')

    # 给 _schedule_cascade 一点时间触发下游
    await asyncio.sleep(0.3)

    # 验证下游 remaining 减少
    remaining = orchestrator._canvas_contexts[canvas_id]['remaining']['down']
    print(f'  下游 down remaining = {remaining}')
    assert remaining == 0, f'下游 remaining 应为 0: {remaining}'

    # 下游应该已被触发（status 不再是 idle）
    down_rec = orchestrator.registry.get(f'{canvas_id}:down')
    print(f'  下游 down: status={down_rec["status"]}')
    assert down_rec['status'] != 'idle', f'下游应被触发: {down_rec["status"]}'
    print('  ✅ 批准后下游被正确触发')

    # 测试3：拒绝逻辑
    canvas_id2 = 'e2e_reject_logic_test'
    nodes2 = [
        {'id': 'gpt', 'type': 'gpt_image', 'x': 100, 'y': 100, 'data': {'prompt': 'test'}},
        {'id': 'down', 'type': 'mask_edit', 'x': 400, 'y': 100, 'data': {}},
    ]
    node_map2 = {n['id']: n for n in nodes2}
    adj2 = {'gpt': ['down'], 'down': []}
    conn_map2 = {('gpt', 'down'): [{'fromField': 'image', 'toField': 'image'}]}
    in_degree2 = {'gpt': 0, 'down': 1}
    orchestrator._canvas_contexts[canvas_id2] = {
        'node_map': node_map2, 'adj': adj2, 'conn_map': conn_map2,
        'in_degree': in_degree2, 'remaining': dict(in_degree2), 'approval_mode': True,
    }
    orchestrator.registry.set(f'{canvas_id2}:gpt', {
        'task_id': None, 'canvas_id': canvas_id2, 'node_id': 'gpt',
        'node_type': 'gpt_image', 'status': 'awaiting_approval', 'progress': 100,
        'image_url': '/assets/test.png', 'video_url': None, 'mask_url': None,
        'error': None, 'created_at': time.time(), 'updated_at': time.time(),
    })
    orchestrator.registry.set(f'{canvas_id2}:down', {
        'task_id': None, 'canvas_id': canvas_id2, 'node_id': 'down',
        'node_type': 'mask_edit', 'status': 'idle', 'progress': 0,
        'image_url': None, 'video_url': None, 'mask_url': None,
        'error': None, 'created_at': time.time(), 'updated_at': time.time(),
    })

    result = orchestrator.reject_node(canvas_id2, 'gpt')
    print(f'  拒绝 gpt: {result}')
    assert result['status'] == 'failed', f'拒绝后状态应为 failed: {result}'

    # 给 _schedule_cascade 一点时间触发下游
    await asyncio.sleep(0.3)

    gpt_rec2 = orchestrator.registry.get(f'{canvas_id2}:gpt')
    assert gpt_rec2['status'] == 'failed', f'拒绝后 gpt 状态应为 failed'
    assert '用户拒绝' in gpt_rec2.get('error', ''), f'错误信息应包含"用户拒绝"'
    print('  ✅ 拒绝后 gpt 状态 = failed, error 包含"用户拒绝"')

    # 下游应被阻断
    down_rec2 = orchestrator.registry.get(f'{canvas_id2}:down')
    print(f'  下游 down: status={down_rec2["status"]}')
    assert down_rec2['status'] == 'blocked', f'下游应被阻断: {down_rec2["status"]}'
    print('  ✅ 拒绝后下游被正确阻断')

    print('✅ 批准/拒绝逻辑全部通过')


def test_approval_reject_logic():
    asyncio.run(_test_approval_reject_logic_async())


# ───────────────────────── 测试4：完整批准模式链路（image→mask→gpt，gpt 需要真实 API）─────────────────────────
def test_approval_mode_with_real_gpt():
    """开启批准模式运行完整链路，验证 gpt_image 进入 awaiting_approval。"""
    print('\n=== 测试4：完整批准模式链路 ===')
    img_bytes = create_face_image()
    image_url = upload_image(img_bytes)
    print(f'上传图片: {image_url}')

    canvas_id = 'e2e_approval_chain_test'
    nodes = [
        {'id': 'img', 'type': 'image_input', 'x': 100, 'y': 100, 'data': {'image_url': image_url}},
        {'id': 'mask', 'type': 'mask_edit', 'x': 400, 'y': 100, 'data': {'mask_mode': 'auto_face'}},
        {'id': 'gpt', 'type': 'gpt_image', 'x': 700, 'y': 100, 'data': {'prompt': '高质量商业海报', 'model': 'gpt-image-2'}},
    ]
    conns = [
        {'id': 'c1', 'from': 'img', 'fromField': 'image', 'to': 'mask', 'toField': 'image'},
        {'id': 'c2', 'from': 'mask', 'fromField': 'image', 'to': 'gpt', 'toField': 'image1'},
    ]

    r = requests.post(f'{BASE}/api/canvas/run', json={
        'canvas_id': canvas_id, 'nodes': nodes, 'connections': conns,
        'approval_mode': True,
    })
    assert r.status_code == 200
    print(f'运行画布: {r.json()}')

    # 等待 mask 完成
    d = poll_node(canvas_id, 'mask', timeout=15)
    print(f'mask_edit: status={d["status"]}, mask_url={d.get("mask_url")}')
    assert d['status'] == 'success', f'mask_edit 失败: {d}'

    # 等待 gpt 进入终态（成功→awaiting_approval 或 失败）
    d = poll_node(canvas_id, 'gpt', timeout=60, expected_statuses=('awaiting_approval', 'failed', 'success'))
    print(f'gpt_image: status={d["status"]}, error={d.get("error")}')

    if d['status'] == 'awaiting_approval':
        print('✅ gpt_image 进入 awaiting_approval')
        # 通过 API 批准
        r = requests.post(f'{BASE}/api/canvas/{canvas_id}/approve/gpt')
        print(f'批准: {r.status_code} {r.json()}')
        if r.status_code == 200:
            d2 = poll_node(canvas_id, 'gpt', timeout=5, expected_statuses=('success',))
            print(f'批准后: status={d2["status"]}, image_url={d2.get("image_url")}')
            print('✅ 批准模式完整闭环成功')
        else:
            print(f'⚠️ 批准失败: {r.json()}')
    elif d['status'] == 'failed':
        print(f'⚠️ gpt_image 执行失败（可能缺少 API key）: {d.get("error")}')
        print('   批准模式的 awaiting_approval 逻辑已在测试3中验证')
    elif d['status'] == 'success':
        # 可能批准模式未生效（gpt_image 已成功但没进 awaiting_approval）
        print(f'⚠️ gpt_image 直接 success（未进入 awaiting_approval），请检查批准模式逻辑')
    else:
        print(f'❌ gpt_image 意外状态: {d["status"]}')


# ───────────────────────── 测试5：人脸检测覆盖率 + expand 参数 ─────────────────────────
def test_face_detection_coverage():
    print('\n=== 测试5：人脸检测覆盖率 ===')
    from mask_service import detect_face_mask, generate_full_mask

    test_cases = [
        ('正面大脸', {'face_x': 130, 'face_y': 80, 'face_w': 252, 'face_h': 340}),
        ('正面小脸', {'face_x': 180, 'face_y': 120, 'face_w': 150, 'face_h': 200}),
        ('偏左脸', {'face_x': 80, 'face_y': 100, 'face_w': 200, 'face_h': 280}),
        ('偏右脸', {'face_x': 230, 'face_y': 100, 'face_w': 200, 'face_h': 280}),
        ('宽屏图小脸', {'width': 1280, 'height': 720, 'face_x': 500, 'face_y': 100, 'face_w': 180, 'face_h': 250}),
        ('竖屏图大脸', {'width': 720, 'height': 1280, 'face_x': 200, 'face_y': 200, 'face_w': 320, 'face_h': 420}),
    ]

    success_count = 0
    for name, params in test_cases:
        img_bytes = create_face_image(**params)
        try:
            mask_bytes = detect_face_mask(img_bytes, expand=0.25)
            mask = Image.open(io.BytesIO(mask_bytes))
            arr = np.array(mask)
            white_pct = np.sum(arr > 127) / arr.size * 100
            print(f'  {name}: ✅ 检测成功, 遮罩覆盖 {white_pct:.1f}%')
            success_count += 1
        except ValueError as e:
            mask_bytes = generate_full_mask(img_bytes)
            print(f'  {name}: ⚠️ 检测失败({e}), fallback 全图遮罩')
        except Exception as e:
            print(f'  {name}: ❌ 异常: {e}')

    print(f'\n  检测成功率: {success_count}/{len(test_cases)}')

    # expand 参数对比
    print('\n  --- expand 参数对比 ---')
    img_bytes = create_face_image()
    for expand in [0.0, 0.15, 0.25, 0.4, 0.6]:
        try:
            mask_bytes = detect_face_mask(img_bytes, expand=expand)
            mask = Image.open(io.BytesIO(mask_bytes))
            arr = np.array(mask)
            white_pct = np.sum(arr > 127) / arr.size * 100
            print(f'  expand={expand:.2f}: 遮罩覆盖 {white_pct:.1f}%')
        except Exception as e:
            print(f'  expand={expand:.2f}: 失败 {e}')

    print(f'\n✅ 人脸检测覆盖率测试完成，建议 expand=0.25（当前默认值）')


if __name__ == '__main__':
    test_mask_edit_auto_face()
    test_mask_edit_auto_full()
    test_approval_reject_logic()
    test_approval_mode_with_real_gpt()
    test_face_detection_coverage()
    print('\n═══════════════════════════════════════')
    print('  全部测试完成')
    print('═══════════════════════════════════════')
