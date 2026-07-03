"""节点执行器包。

每个执行器是纯函数：`async def execute(input, on_progress, on_submitted=None) -> NodeOutput`
- input: 类型化 NodeInput（PortResolver 归一化后）
- on_progress: 进度回调 Callable[[int], None]
- on_submitted: 可选，RH 任务提交后记录 external_task_id
- 返回 NodeOutput（image_url/video_url/mask_url）

执行器不碰 registry、不碰 _canvas_contexts。引擎 _run_node 负责写 registry。
I/O 依赖（storage/clients）全局 import，测试时 mock.patch。
"""
from . import image_input, gpt_image, remove_bg, mask_edit, seedance_video

# node_type → 执行器函数注册表
NODE_EXECUTORS = {
    "image_input": image_input.execute,
    "gpt_image": gpt_image.execute,
    "remove_bg": remove_bg.execute,
    "mask_edit": mask_edit.execute,
    "seedance_video": seedance_video.execute,
}
