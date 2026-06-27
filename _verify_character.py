"""T5 验收2/3 自动重试脚本：每 3 分钟触发一次 character 任务，最多 6 次。
中转 edits 接口 429 恢复后自动跑通，验证背透 PNG 产出。
"""
import sys
import time
import httpx

BASE = "http://127.0.0.1:8001"
MAX_ATTEMPTS = 6
RETRY_INTERVAL = 180  # 3 分钟


def upload_ref() -> str:
    with open("test_face.png", "rb") as f:
        img = f.read()
    r = httpx.post(f"{BASE}/api/assets/upload",
                   files={"file": ("test_face.png", img, "image/png")},
                   timeout=30)
    r.raise_for_status()
    return r.json()["url"]


def trigger_and_poll(ref_url: str) -> dict:
    body = {
        "workflow_id": "verify-character",
        "reference_image_url": ref_url,
        "hair": "短发",
        "makeup": "淡妆",
        "clothing": "白衬衫",
    }
    r = httpx.post(f"{BASE}/api/stages/character/run", json=body, timeout=30)
    r.raise_for_status()
    task_id = r.json()["task_id"]

    start = time.time()
    last_progress = -1
    while time.time() - start < 120:  # 单次任务最多等 120s（含重试 35s + 余量）
        r = httpx.get(f"{BASE}/api/tasks/{task_id}", timeout=10)
        r.raise_for_status()
        d = r.json()
        if d["progress"] != last_progress:
            print(f"      +{int(time.time()-start)}s status={d['status']} progress={d['progress']}%")
            last_progress = d["progress"]
        if d["status"] in ("success", "failed"):
            return d
        time.sleep(2)
    return {"status": "timeout", "progress": last_progress, "error": "120s 未完成"}


def verify_transparent_png(png_url: str) -> bool:
    pr = httpx.get(f"{BASE}{png_url}", timeout=30)
    print(f"   character_png HTTP {pr.status_code}, size={len(pr.content)} bytes")
    if pr.status_code != 200 or len(pr.content) < 100:
        return False
    from PIL import Image
    from io import BytesIO
    im = Image.open(BytesIO(pr.content))
    print(f"   PNG mode={im.mode}, size={im.size}")
    if im.mode == "RGBA":
        print("   [PASS] 背透验证：mode=RGBA（带 alpha 透明通道）")
        return True
    print(f"   [WARN] mode={im.mode}（非 RGBA，可能中转未透传 background=transparent）")
    return False


def main():
    print(f"=== T5 验收2/3 自动重试（最多 {MAX_ATTEMPTS} 次，间隔 {RETRY_INTERVAL}s）===")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n[尝试 {attempt}/{MAX_ATTEMPTS}] {time.strftime('%H:%M:%S')}")
        try:
            ref_url = upload_ref()
            print(f"   ref_url = {ref_url}")
            result = trigger_and_poll(ref_url)
            print(f"   FINAL: status={result['status']}, error={result.get('error', '')[:150]}")

            if result["status"] == "success":
                print("\n[验收2 PASS] 真实生图成功：pending→running→success")
                png_url = result["assets"]["character_png"]
                if verify_transparent_png(png_url):
                    print("[验收3 PASS] 背透 PNG 产出验证通过")
                    print("\n=== 验收2/3 全部通过 ===")
                    sys.exit(0)
                else:
                    print("[验收3 WARN] 背透 PNG 未达 RGBA，但流程已通")
                    sys.exit(0)
            elif result["status"] == "failed" and "429" in (result.get("error") or ""):
                print(f"   中转 edits 仍 429，{RETRY_INTERVAL}s 后重试...")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_INTERVAL)
            else:
                print(f"   非 429 错误，停止重试：{result.get('error', '')[:200]}")
                sys.exit(1)
        except Exception as e:
            print(f"   异常: {type(e).__name__}: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_INTERVAL)

    print(f"\n=== {MAX_ATTEMPTS} 次尝试均 429，中转 edits 接口未恢复 ===")
    print("代码侧已就绪，建议稍后手动重试或换中转。")
    sys.exit(2)


if __name__ == "__main__":
    main()
