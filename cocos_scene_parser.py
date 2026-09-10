import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("CocosSceneParser")


class CocosSceneParser:
    """
    Phân tích và trích xuất cấu trúc cây Node (Hierarchy Tree) từ các tệp .scene, .fire và .prefab của Cocos Creator.
    Hỗ trợ sinh mã nguồn liên kết thuộc tính TypeScript (@property) tự động.
    """

    COMPONENT_EMOJIS = {
        "Sprite": "🖼️",
        "Label": "🔤",
        "Button": "🔘",
        "RigidBody": "⚙️",
        "RigidBody2D": "⚙️",
        "Collider": "🛡️",
        "BoxCollider": "🛡️",
        "CircleCollider": "🛡️",
        "AudioSource": "🔊",
        "Animation": "🎬",
        "Widget": "📐",
        "Layout": "📑",
        "ScrollView": "📜",
        "ProgressBar": "📊",
        "ParticleSystem": "✨",
        "Camera": "📷",
        "Canvas": "🎨",
    }

    @classmethod
    def get_scene_and_prefab_files(cls, workspace_path: str) -> list[str]:
        """Tìm tất cả các tệp .scene, .fire và .prefab trong thư mục assets của workspace."""
        ws = Path(workspace_path)
        assets_dir = ws / "assets"
        if not assets_dir.exists():
            assets_dir = ws

        files = []
        for ext in ("*.scene", "*.fire", "*.prefab"):
            for f in assets_dir.rglob(ext):
                # Bỏ qua các tệp trong node_modules, temp, build, library
                if any(part in f.parts for part in ("temp", "build", "library", "node_modules", "local")):
                    continue
                try:
                    rel = str(f.relative_to(ws)).replace("\\", "/")
                    files.append(rel)
                except Exception:
                    files.append(str(f))

        return sorted(files)

    @classmethod
    def parse_file(cls, full_path: str) -> tuple[bool, str, dict]:
        """Đọc và parse tệp scene/prefab JSON thành danh sách Node."""
        p = Path(full_path)
        if not p.exists():
            return False, f"Tệp không tồn tại: `{full_path}`", {}

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, list):
                return False, "Định dạng tệp Cocos không phải là JSON Array chuẩn.", {}

            nodes = {}
            root_ids = []

            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                type_name = item.get("__type__", "")

                # Nhận diện Node
                if type_name == "cc.Node":
                    name = item.get("_name", f"Node_{idx}")
                    active = item.get("_active", True)
                    parent_ref = item.get("_parent")
                    parent_id = parent_ref.get("__id__") if isinstance(parent_ref, dict) else None
                    children_refs = item.get("_children", [])
                    children_ids = [c.get("__id__") for c in children_refs if isinstance(c, dict) and "__id__" in c]
                    components_refs = item.get("_components", [])
                    components_ids = [c.get("__id__") for c in components_refs if isinstance(c, dict) and "__id__" in c]

                    nodes[idx] = {
                        "id": idx,
                        "name": name,
                        "active": active,
                        "parent_id": parent_id,
                        "children_ids": children_ids,
                        "components_ids": components_ids,
                        "components": [],
                    }
                    if parent_id is None:
                        root_ids.append(idx)

            # Thu thập thông tin Component
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                type_name = item.get("__type__", "")
                if type_name and type_name != "cc.Node":
                    # Rút gọn tên component: cc.Sprite -> Sprite, cc.Button -> Button
                    clean_type = type_name.replace("cc.", "")
                    # Gán vào node sở hữu
                    node_ref = item.get("node")
                    if isinstance(node_ref, dict) and "__id__" in node_ref:
                        nid = node_ref["__id__"]
                        if nid in nodes:
                            nodes[nid]["components"].append(clean_type)

            return True, f"Tìm thấy {len(nodes)} Node.", {"nodes": nodes, "root_ids": root_ids, "file_name": p.name}

        except Exception as e:
            logger.exception("Error parsing Cocos scene/prefab")
            return False, f"Lỗi đọc file: {e}", {}

    @classmethod
    def generate_hierarchy_text(cls, workspace_path: str, rel_file_path: str, max_depth: int = 5) -> str:
        """Tạo chuỗi sơ đồ cây Node phân cấp trực quan cho Telegram."""
        full_path = Path(workspace_path) / rel_file_path
        ok, msg, result = cls.parse_file(str(full_path))
        if not ok:
            return f"❌ {msg}"

        nodes = result.get("nodes", {})
        root_ids = result.get("root_ids", [])
        file_name = result.get("file_name", rel_file_path)

        if not nodes:
            return f"ℹ️ Tệp `{file_name}` không chứa Node nào."

        lines = [
            f"🌳 **CẤU TRÚC HIERARCHY:** `{file_name}`",
            f"📊 Tổng số Node: `{len(nodes)}`",
            "━━━━━━━━━━━━━━━━━━",
        ]

        def render_node(node_id: int, prefix: str = "", is_last: bool = True, depth: int = 0):
            if depth > max_depth or node_id not in nodes:
                return

            node = nodes[node_id]
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")

            # Components badge
            comp_badges = []
            for comp in node["components"]:
                emoji = cls.COMPONENT_EMOJIS.get(comp, "🧩")
                comp_badges.append(f"{emoji}{comp}")
            comp_str = f" `[{', '.join(comp_badges)}]`" if comp_badges else ""
            status_icon = "" if node["active"] else " ⚪*(Tắt)*"

            lines.append(f"{prefix}{connector}📁 **{node['name']}**{comp_str}{status_icon}")

            children = node["children_ids"]
            for i, cid in enumerate(children):
                is_child_last = (i == len(children) - 1)
                render_node(cid, child_prefix, is_child_last, depth + 1)

        # Render các root node
        for i, rid in enumerate(root_ids):
            render_node(rid, "", i == len(root_ids) - 1, 0)

        return "\n".join(lines)

    @classmethod
    def generate_ts_bindings(cls, workspace_path: str, rel_file_path: str) -> str:
        """Tự động sinh mã nguồn TypeScript khai báo @property binding cho các Node và Component chính."""
        full_path = Path(workspace_path) / rel_file_path
        ok, msg, result = cls.parse_file(str(full_path))
        if not ok:
            return f"❌ {msg}"

        nodes = result.get("nodes", {})
        file_name = result.get("file_name", rel_file_path)
        class_name = Path(file_name).stem.capitalize() + "Controller"

        properties: list[str] = []
        inits: list[str] = []

        for nid, node in nodes.items():
            name = node["name"]
            # Bỏ qua Canvas hoặc Main Camera mặc định
            if name.lower() in ("canvas", "main camera", "background", "bg"):
                continue

            # Chuẩn hóa tên biến: ScoreLabel -> scoreLabel, Player_Node -> playerNode
            var_name = "".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())
            if var_name:
                var_name = var_name[0].lower() + var_name[1:]

            comps = node["components"]

            # Ưu tiên các component phổ biến
            bound = False
            for target_comp in ("Button", "Label", "Sprite", "ProgressBar", "ScrollView", "AudioSource", "RigidBody", "RigidBody2D", "Animation"):
                if target_comp in comps:
                    comp_var = f"{var_name}{target_comp}" if not var_name.lower().endswith(target_comp.lower()) else var_name
                    properties.append(f"    @property(cc.{target_comp})\n    {comp_var}: cc.{target_comp} = null;")
                    bound = True
                    break

            if not bound and comps:
                # Gán Node thông thường
                node_var = f"{var_name}Node" if not var_name.lower().endswith("node") else var_name
                properties.append(f"    @property(cc.Node)\n    {node_var}: cc.Node = null;")

        ts_code = (
            f"// 🤖 Tự động sinh bởi CocosDevBot từ {file_name}\n"
            f"const {{ ccclass, property }} = cc._decorator;\n\n"
            f"@ccclass\n"
            f"export default class {class_name} extends cc.Component {{\n\n"
            f"    // ==========================================\n"
            f"    // UI & NODE BINDINGS\n"
            f"    // ==========================================\n"
            + "\n\n".join(properties[:15])  # Giới hạn 15 properties phổ biến nhất
            + "\n\n"
            f"    onLoad() {{\n"
            f"        // Khởi tạo các sự kiện\n"
            f"    }}\n\n"
            f"    start() {{\n"
            f"        // Bắt đầu logic trò chơi\n"
            f"    }}\n"
            f"}}"
        )
        return ts_code


# Singleton instance
cocos_scene_parser = CocosSceneParser()
