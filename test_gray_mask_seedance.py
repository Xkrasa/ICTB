"""灰色遮罩 + 真实 Seedance 视频生成测试。

验证：image_input → mask_edit(auto_face, mask_value=128) → gpt_image → seedance_video
看灰色遮罩是否能通过 Seedance 内容安全审查。
"""
import os
os.environ['GPT_IMAGE_TIMEOUT'] = '120'

import time
import requests
from PIL import Image, ImageDraw
import io

BASE = 'http://127.0.0.1:8000'


def create_face_image(width=512, height=512, face_x=130, face_y=80, face_w=252, face_h=340):
    img = Image.new('RGB', (width, height), (200, 180, 160))
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


def poll_node(canvas_id, node_id, timeout=300, expected_statuses=None):
    expected = expected_statuses or ('success', 'failed', 'blocked', 'awaiting_approval')
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f'{BASE}/api/canvas/{canvas_id}/nodes/{node_id}')
        d = r.json()
        if d['status'] in expected:
            return d
        time.sleep(1.0)
    return d


def main():
    print('=== 灰色遮罩 + Seedance 测试 ===')
    print(f'服务地址: {BASE}')
    print('注意：会调用真实 GPT 和 Seedance API，产生费用。')

    img_bytes = create_face_image()
    image_url = upload_image(img_bytes)
    print(f'上传图片: {image_url}')

    canvas_id = 'e2e_gray_mask_test'
    nodes = [
        {'id': 'img', 'type': 'image_input', 'x': 100, 'y': 100, 'data': {'image_url': image_url}},
        {'id': 'mask', 'type': 'mask_edit', 'x': 400, 'y': 100, 'data': {
            'mask_mode': 'auto_face',
            'expand': 0.6,
            'mask_value': 128,  # 灰色遮罩
        }},
        {'id': 'gpt', 'type': 'gpt_image', 'x': 700, 'y': 100, 'data': {'prompt': '高质量商业海报，时尚人物', 'model': 'gpt-image-2'}},
        {'id': 'vid', 'type': 'seedance_video', 'x': 1000, 'y': 100, 'data': {'prompt': '人物轻微摆动，商业广告风格', 'mode': 'reference'}},
    ]
    conns = [
        {'id': 'c1', 'from': 'img', 'fromField': 'image', 'to': 'mask', 'toField': 'image'},
        {'id': 'c2', 'from': 'mask', 'fromField': 'image', 'to': 'gpt', 'toField': 'image1'},
        {'id': 'c3', 'from': 'gpt', 'fromField': 'image', 'to': 'vid', 'toField': 'first_frame'},
    ]

    r = requests.post(f'{BASE}/api/canvas/run', json={
        'canvas_id': canvas_id, 'nodes': nodes, 'connections': conns,
        'approval_mode': True,
    })
    assert r.status_code == 200, f'Run failed: {r.text}'
    print(f'运行画布: {r.json()}')

    # 等待 mask 完成
    d = poll_node(canvas_id, 'mask', timeout=30)
    print(f'mask_edit: status={d["status"]}, mask_url={d.get("mask_url")}')
    if d['status'] != 'success':
        print(f'⚠️ mask_edit 失败: {d.get("error")}')
        return

    # 等待 gpt 进入 awaiting_approval
    d = poll_node(canvas_id, 'gpt', timeout=180, expected_statuses=('awaiting_approval', 'failed'))
    print(f'gpt_image: status={d["status"]}, error={d.get("error")}')
    if d['status'] != 'awaiting_approval':
        print(f'⚠️ gpt_image 未进入 awaiting_approval，测试终止')
        return

    print('✅ gpt_image 进入 awaiting_approval，调用批准 API')
    r = requests.post(f'{BASE}/api/canvas/{canvas_id}/approve/gpt')
    print(f'批准 gpt: {r.status_code} {r.json()}')
    if r.status_code != 200:
        print('⚠️ 批准 gpt 失败')
        return

    # 等待 gpt success
    d = poll_node(canvas_id, 'gpt', timeout=30, expected_statuses=('success', 'failed'))
    print(f'gpt_image 批准后: status={d["status"]}, image_url={d.get("image_url")}')
    if d['status'] != 'success':
        print(f'⚠️ gpt_image 批准后未成功: {d.get("error")}')
        return

    # 等待 vid 进入 awaiting_approval
    d = poll_node(canvas_id, 'vid', timeout=300, expected_statuses=('awaiting_approval', 'failed'))
    print(f'seedance_video: status={d["status"]}, error={d.get("error")}')
    if d['status'] != 'awaiting_approval':
        print(f'⚠️ seedance_video 未进入 awaiting_approval，测试终止')
        return

    print('✅ seedance_video 进入 awaiting_approval，调用批准 API')
    r = requests.post(f'{BASE}/api/canvas/{canvas_id}/approve/vid')
    print(f'批准 vid: {r.status_code} {r.json()}')
    if r.status_code != 200:
        print('⚠️ 批准 vid 失败')
        return

    # 等待 vid success
    d = poll_node(canvas_id, 'vid', timeout=60, expected_statuses=('success', 'failed'))
    print(f'seedance_video 批准后: status={d["status"]}, video_url={d.get("video_url")}')
    if d['status'] == 'success':
        print('✅ 灰色遮罩 Seedance 完整闭环成功')
    else:
        print(f'⚠️ seedance_video 批准后未成功: {d.get("error")}')


if __name__ == '__main__':
    main()
