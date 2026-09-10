import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("CocosScriptGenerator")


class CocosScriptGenerator:
    """
    Tạo nhanh mã nguồn TypeScript mẫu chuẩn cho Cocos Creator 2.x và 3.x,
    đồng thời tự động tạo tệp .meta có UUID hợp lệ để không bị lỗi reference trong Engine.
    """

    TEMPLATES = {
        "component": {
            "name": "🎮 Base Component",
            "desc": "Component cơ bản với đầy đủ vòng đời onLoad, start, update, onDestroy.",
        },
        "game_manager": {
            "name": "👑 Singleton GameManager",
            "desc": "Quản lý luồng Game State, điểm số, và tồn tại xuyên Scene (Persist Root).",
        },
        "audio_manager": {
            "name": "🔊 Audio Manager",
            "desc": "Quản lý BGM/SFX, lưu âm lượng vào localStorage, chống trùng lặp âm thanh.",
        },
        "object_pool": {
            "name": "🏊 Object Pool Manager",
            "desc": "Tái sử dụng Prefab (đạn, quái) bằng NodePool, tránh giật lag khi chơi game.",
        },
        "joystick": {
            "name": "🕹️ Virtual Joystick",
            "desc": "Cần gạt cảm ứng trên màn hình điện thoại phát sự kiện di chuyển nhân vật.",
        },
        "ui_popup": {
            "name": "🪟 UI Popup Base",
            "desc": "Hộp thoại Popup với hiệu ứng mở/đóng Scale & Fade mượt mà.",
        },
    }

    @classmethod
    def generate_uuid(cls) -> str:
        """Tạo UUID v4 ngẫu nhiên cho tệp .meta của Cocos Creator."""
        return str(uuid.uuid4())

    @classmethod
    def create_meta_file(cls, script_path: Path, major_version: int = 2) -> bool:
        """Tạo tệp .meta đồng hành cho script TypeScript."""
        meta_path = script_path.with_name(script_path.name + ".meta")
        if meta_path.exists():
            return True

        uuid_str = cls.generate_uuid()

        if major_version == 3:
            meta_content = {
                "ver": "1.0.1",
                "importer": "typescript",
                "imported": True,
                "uuid": uuid_str,
                "files": [],
                "subMetas": {},
                "userData": {},
            }
        else:
            meta_content = {
                "ver": "1.0.0",
                "uuid": uuid_str,
                "isPlugin": False,
                "loadPluginInWeb": True,
                "loadPluginInNative": True,
                "loadPluginInEditor": False,
                "subMetas": {},
            }

        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta_content, f, indent=2)
            return True
        except Exception as e:
            logger.exception(f"Lỗi khi tạo file .meta: {e}")
            return False

    @classmethod
    def get_template_code(cls, template_key: str, class_name: str, major_version: int = 2) -> str:
        """Tạo nội dung mã nguồn TypeScript theo từng mẫu thiết kế."""
        if major_version == 3:
            return cls._get_v3_template(template_key, class_name)
        else:
            return cls._get_v2_template(template_key, class_name)

    @classmethod
    def _get_v2_template(cls, template_key: str, class_name: str) -> str:
        """Mẫu mã nguồn Cocos Creator 2.x (cc.Component)."""
        if template_key == "game_manager":
            return f"""const {{ ccclass, property }} = cc._decorator;

export enum GameState {{
    INIT,
    PLAYING,
    PAUSED,
    GAME_OVER,
    VICTORY
}}

@ccclass
export default class {class_name} extends cc.Component {{

    public static instance: {class_name} = null;

    @property({{ type: cc.Enum(GameState) }})
    public currentState: GameState = GameState.INIT;

    @property
    public score: number = 0;

    @property
    public highScore: number = 0;

    onLoad() {{
        if ({class_name}.instance === null) {{
            {class_name}.instance = this;
            cc.game.addPersistRootNode(this.node);
        }} else {{
            this.node.destroy();
            return;
        }}

        this.highScore = parseInt(cc.sys.localStorage.getItem("HIGH_SCORE") || "0");
    }}

    public setGameState(state: GameState) {{
        this.currentState = state;
        cc.systemEvent.emit("GAME_STATE_CHANGED", state);
    }}

    public addScore(points: number) {{
        this.score += points;
        if (this.score > this.highScore) {{
            this.highScore = this.score;
            cc.sys.localStorage.setItem("HIGH_SCORE", this.highScore.toString());
        }}
        cc.systemEvent.emit("SCORE_UPDATED", this.score);
    }}

    public restartGame() {{
        this.score = 0;
        this.setGameState(GameState.PLAYING);
        cc.director.loadScene(cc.director.getScene().name);
    }}
}}
"""

        elif template_key == "audio_manager":
            return f"""const {{ ccclass, property }} = cc._decorator;

@ccclass
export default class {class_name} extends cc.Component {{

    public static instance: {class_name} = null;

    @property(cc.AudioSource)
    public bgmSource: cc.AudioSource = null;

    @property([cc.AudioClip])
    public sfxClips: cc.AudioClip[] = [];

    private isMuted: boolean = false;

    onLoad() {{
        if ({class_name}.instance === null) {{
            {class_name}.instance = this;
            cc.game.addPersistRootNode(this.node);
        }} else {{
            this.node.destroy();
            return;
        }}

        this.isMuted = cc.sys.localStorage.getItem("AUDIO_MUTED") === "true";
    }}

    public playBGM(clip: cc.AudioClip, loop: boolean = true) {{
        if (this.isMuted || !clip) return;
        cc.audioEngine.playMusic(clip, loop);
    }}

    public playSFX(clipNameOrIndex: string | number) {{
        if (this.isMuted) return;
        let clip: cc.AudioClip = null;
        if (typeof clipNameOrIndex === "number") {{
            clip = this.sfxClips[clipNameOrIndex];
        }} else {{
            clip = this.sfxClips.find(c => c.name === clipNameOrIndex);
        }}

        if (clip) {{
            cc.audioEngine.playEffect(clip, false);
        }}
    }}

    public toggleMute(): boolean {{
        this.isMuted = !this.isMuted;
        cc.sys.localStorage.setItem("AUDIO_MUTED", this.isMuted.toString());
        if (this.isMuted) {{
            cc.audioEngine.pauseMusic();
        }} else {{
            cc.audioEngine.resumeMusic();
        }}
        return this.isMuted;
    }}
}}
"""

        elif template_key == "object_pool":
            return f"""const {{ ccclass, property }} = cc._decorator;

@ccclass
export default class {class_name} extends cc.Component {{

    public static instance: {class_name} = null;

    @property(cc.Prefab)
    public itemPrefab: cc.Prefab = null;

    @property
    public initPoolSize: number = 20;

    private pool: cc.NodePool = new cc.NodePool();

    onLoad() {{
        {class_name}.instance = this;
        for (let i = 0; i < this.initPoolSize; ++i) {{
            let node = cc.instantiate(this.itemPrefab);
            this.pool.put(node);
        }}
    }}

    public spawn(parent: cc.Node, position?: cc.Vec2): cc.Node {{
        let node: cc.Node = null;
        if (this.pool.size() > 0) {{
            node = this.pool.get();
        }} else {{
            node = cc.instantiate(this.itemPrefab);
        }}

        node.parent = parent;
        if (position) {{
            node.setPosition(position);
        }}
        return node;
    }}

    public recycle(node: cc.Node) {{
        this.pool.put(node);
    }}

    onDestroy() {{
        this.pool.clear();
    }}
}}
"""

        elif template_key == "joystick":
            return f"""const {{ ccclass, property }} = cc._decorator;

@ccclass
export default class {class_name} extends cc.Component {{

    @property(cc.Node)
    public stick: cc.Node = null;

    @property
    public maxRadius: number = 100;

    public direction: cc.Vec2 = cc.v2(0, 0);

    onLoad() {{
        this.node.on(cc.Node.EventType.TOUCH_START, this.onTouchMove, this);
        this.node.on(cc.Node.EventType.TOUCH_MOVE, this.onTouchMove, this);
        this.node.on(cc.Node.EventType.TOUCH_END, this.onTouchEnd, this);
        this.node.on(cc.Node.EventType.TOUCH_CANCEL, this.onTouchEnd, this);
    }}

    private onTouchMove(event: cc.Event.EventTouch) {{
        let touchPos = event.getLocation();
        let localPos = this.node.convertToNodeSpaceAR(touchPos);
        let len = localPos.mag();

        if (len > this.maxRadius) {{
            localPos = localPos.normalize().mul(this.maxRadius);
        }}

        this.stick.setPosition(localPos);
        this.direction = localPos.normalize();
        cc.systemEvent.emit("JOYSTICK_MOVE", this.direction);
    }}

    private onTouchEnd() {{
        this.stick.setPosition(cc.Vec2.ZERO);
        this.direction = cc.Vec2.ZERO;
        cc.systemEvent.emit("JOYSTICK_END");
    }}
}}
"""

        elif template_key == "ui_popup":
            return f"""const {{ ccclass, property }} = cc._decorator;

@ccclass
export default class {class_name} extends cc.Component {{

    @property(cc.Node)
    public panel: cc.Node = null;

    @property(cc.Button)
    public closeBtn: cc.Button = null;

    onLoad() {{
        if (this.closeBtn) {{
            this.closeBtn.node.on("click", this.close, this);
        }}
    }}

    public show() {{
        this.node.active = true;
        if (this.panel) {{
            this.panel.setScale(0.3);
            this.panel.opacity = 0;
            cc.tween(this.panel)
                .to(0.2, {{ scale: 1.05, opacity: 255 }})
                .to(0.1, {{ scale: 1.0 }})
                .start();
        }}
    }}

    public close() {{
        if (this.panel) {{
            cc.tween(this.panel)
                .to(0.15, {{ scale: 0.3, opacity: 0 }})
                .call(() => {{
                    this.node.active = false;
                }})
                .start();
        }} else {{
            this.node.active = false;
        }}
    }}
}}
"""

        else:
            # Component mặc định
            return f"""const {{ ccclass, property }} = cc._decorator;

@ccclass
export default class {class_name} extends cc.Component {{

    @property(cc.Label)
    public label: cc.Label = null;

    @property
    public speed: number = 100;

    onLoad() {{
        // Khởi tạo trạng thái ban đầu
    }}

    start() {{
        // Bắt đầu logic game
    }}

    update(dt: number) {{
        // Cập nhật mỗi khung hình
    }}

    onDestroy() {{
        // Hủy lắng nghe sự kiện
    }}
}}
"""

    @classmethod
    def _get_v3_template(cls, template_key: str, class_name: str) -> str:
        """Mẫu mã nguồn Cocos Creator 3.x."""
        return f"""import {{ _decorator, Component, Node, Vec3 }} from 'cc';
const {{ ccclass, property }} = _decorator;

@ccclass('{class_name}')
export class {class_name} extends Component {{

    @property
    public speed: number = 10;

    start() {{
        // Khởi tạo logic khi game bắt đầu
    }}

    update(deltaTime: number) {{
        // Logic cập nhật theo thời gian thực
    }}
}}
"""

    @classmethod
    def generate_script(
        cls,
        workspace_path: str,
        template_key: str,
        class_name: str,
        target_dir: str = "assets/scripts",
        major_version: int = 2,
    ) -> tuple[bool, str, str]:
        """Tạo file mã nguồn TypeScript và companion .meta vào dự án."""
        clean_name = "".join(w.capitalize() for w in class_name.replace(" ", "_").split("_") if w)
        if not clean_name:
            clean_name = "NewScript"

        ws = Path(workspace_path)
        out_dir = ws / target_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        script_file = out_dir / f"{clean_name}.ts"
        if script_file.exists():
            return False, f"⚠️ Tệp tin `{clean_name}.ts` đã tồn tại trong `{target_dir}`!", str(script_file)

        content = cls.get_template_code(template_key, clean_name, major_version)

        try:
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(content)

            # Tạo file .meta
            cls.create_meta_file(script_file, major_version)

            return True, f"✅ Đã tạo Script `{clean_name}.ts` kèm `.meta` trong `{target_dir}`!", str(script_file)
        except Exception as e:
            logger.exception("Error generating script")
            return False, f"❌ Lỗi khi ghi tệp: {e}", str(script_file)


# Singleton instance
cocos_script_generator = CocosScriptGenerator()
