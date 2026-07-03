"""端口解析器：统一上游注入 + 字段归一化。

深化目标：把原 orchestrator.py 里分散的端口注入逻辑
（_get_output_value / _resolve_to_field / _inject_upstream_to_downstreams /
_schedule_cascade 的注入段）集中到一个纯函数模块。

PortResolver.resolve 接收上游记录 + 连线，按 NODE_PORTS 把上游产物注入到
规范字段名，与 node.data 用户配置合并，产出类型化 NodeInput。

纯函数：不碰 registry、不碰 _canvas_contexts。_run_node 负责准备
upstream_recs 和 conns 后传入。可独立单测。
"""
from node_types import (
    NODE_PORTS, _OUTPUT_FIELD_MAP, _PORT_TO_ASSET,
    build_input, is_overridable,
)


def _get_output_value(upstream_rec: dict, from_field: str | None) -> tuple[str, str] | None:
    """根据上游记录和 from_field 获取要注入的产物。

    返回 (产物键, 值) 或 None。
    """
    if from_field:
        # from_field 是输出端口名，映射回产物键
        asset_key = _PORT_TO_ASSET.get(from_field)
        if asset_key and upstream_rec.get(asset_key):
            return asset_key, upstream_rec[asset_key]
        return None

    # 无 from_field：按优先级取第一个可用产物
    for asset_key in ("image_url", "video_url", "mask_url"):
        if upstream_rec.get(asset_key):
            return asset_key, upstream_rec[asset_key]
    return None


def _resolve_to_field(downstream_type: str, asset_key: str, to_field: str | None) -> str | None:
    """根据下游节点类型、产物键和 to_field 确定最终注入字段名。"""
    if to_field:
        return to_field

    ports = NODE_PORTS.get(downstream_type, {})
    inputs = ports.get("inputs", [])

    # 优先按产物类型找同名输入端口
    port_name = _OUTPUT_FIELD_MAP.get(asset_key)
    if port_name:
        for inp in inputs:
            if inp["name"] == port_name:
                return port_name
        # 找不到同名端口：按类型找第一个匹配的输入端口
        asset_type = "IMAGE" if asset_key == "image_url" else ("VIDEO" if asset_key == "video_url" else "MASK")
        for inp in inputs:
            if inp["type"] == asset_type:
                return inp["name"]

    return None


class PortResolver:
    """端口解析器：上游记录 + 连线 → 类型化 NodeInput。"""

    @staticmethod
    def resolve(node: dict, upstream_recs: list[dict], conns: list[dict]) -> object:
        """从上游记录 + 连线 + NODE_PORTS，产出类型化 NodeInput。

        Args:
            node: 节点 dict（含 id, type, data）
            upstream_recs: 上游节点的 registry 记录列表（_run_node 负责读出）
            conns: 画布所有连线（PortResolver 自行过滤 to==node.id 的）

        Returns:
            类型化 NodeInput（GptImageInput / SeedanceInput / ...）

        覆盖规则（保持原 _schedule_cascade 语义）：
        - overridable 节点（gpt_image/remove_bg/mask_edit/seedance_video）：
          上游产物总是覆盖已有字段（链路型节点允许新上游覆盖）
        - 非 overridable 节点（image_input）：已有值优先，上游仅填充空字段
        """
        node_type = node.get("type", "")
        node_id = node.get("id")
        merged = dict(node.get("data", {}))

        for conn in conns:
            if conn.get("to") != node_id:
                continue
            upstream = next(
                (r for r in upstream_recs if r and r.get("node_id") == conn.get("from")),
                None,
            )
            if not upstream:
                continue
            asset = _get_output_value(upstream, conn.get("fromField"))
            if asset is None:
                continue
            asset_key, value = asset
            to_field = _resolve_to_field(node_type, asset_key, conn.get("toField"))
            if to_field is None:
                continue
            # 覆盖规则
            if to_field not in merged or not merged.get(to_field) or is_overridable(node_type):
                merged[to_field] = value

        return build_input(node_type, merged)
