"""配置中心：从环境变量读取，python-dotenv 加载 .env。"""
import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# 第三方中转地址（llm-api.net），OpenAI 兼容
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://llm-api.net/v1")
# 编辑接口模型名：中转 default 分组下 gpt-image-2 有通道（-all 后缀无通道会 503）
GPT_IMAGE_MODEL = os.getenv("GPT_IMAGE_MODEL", "gpt-image-2")
GPT_IMAGE_QUALITY = os.getenv("GPT_IMAGE_QUALITY", "medium")  # low/medium/high/auto
# 中转文档未列 thinking 参数，默认空（不传）；如确认支持可在 .env 开启
GPT_IMAGE_THINKING = os.getenv("GPT_IMAGE_THINKING", "")
GPT_IMAGE_SIZE = os.getenv("GPT_IMAGE_SIZE", "1024x1024")
# thinking + high 会很久，HTTP timeout 必须 ≥ 360s
GPT_IMAGE_TIMEOUT = float(os.getenv("GPT_IMAGE_TIMEOUT", "360"))

# ── RunningHub（seedance 图生视频）──
RUNNINGHUB_API_KEY = os.getenv("RUNNINGHUB_API_KEY", "")
RUNNINGHUB_BASE_URL = os.getenv("RUNNINGHUB_BASE_URL", "https://www.runninghub.cn/openapi/v2")
RUNNINGHUB_TIMEOUT = float(os.getenv("RUNNINGHUB_TIMEOUT", "30"))
# 视频生成轮询间隔（秒）
SEEDANCE_POLL_INTERVAL = float(os.getenv("SEEDANCE_POLL_INTERVAL", "5"))
SEEDANCE_POLL_TIMEOUT = float(os.getenv("SEEDANCE_POLL_TIMEOUT", "600"))  # 10 分钟超时
