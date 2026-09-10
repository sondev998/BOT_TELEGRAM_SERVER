import io
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger("CocosAssetImporter")


class CocosAssetImporter:
    """
    Tối ưu hóa và nhập hình ảnh, âm thanh, phông chữ vào thư mục dự án Cocos Creator,
    đồng thời tự động tạo tệp .meta có cấu hình SpriteFrame / AudioClip chuẩn xác.
    """

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}
    FONT_EXTS = {".ttf", ".otf", ".fnt"}
    SCRIPT_EXTS = {".ts", ".js"}

    @classmethod
    def generate_uuid(cls) -> str:
        return str(uuid.uuid4())

    @classmethod
    def create_texture_meta(cls, image_path: Path, major_version: int = 2) -> bool:
        """Tạo tệp .meta chuẩn cho Texture/Sprite trong Cocos Creator."""
        meta_path = image_path.with_name(image_path.name + ".meta")
        if meta_path.exists():
            return True

        tex_uuid = cls.generate_uuid()
        sprite_uuid = cls.generate_uuid()

        if major_version == 3:
            meta_content = {
                "ver": "1.0.1",
                "importer": "image",
                "imported": True,
                "uuid": tex_uuid,
                "files": [],
                "subMetas": {
                    "6c48a": {
                        "importer": "sprite-frame",
                        "uuid": sprite_uuid,
                        "displayName": image_path.stem,
                        "userData": {
                            "trimType": "auto",
                            "trimThreshold": 1,
                            "rotated": False,
                            "offsetX": 0,
                            "offsetY": 0,
                        },
                    }
                },
                "userData": {
                    "type": "sprite-frame",
                    "wrapModeS": "clamp-to-edge",
                    "wrapModeT": "clamp-to-edge",
                    "filterMode": "bilinear",
                },
            }
        else:
            meta_content = {
                "ver": "1.2.0",
                "uuid": tex_uuid,
                "type": "sprite",
                "wrapMode": "clamp",
                "filterMode": "bilinear",
                "subMetas": {
                    image_path.stem: {
                        "ver": "1.0.4",
                        "uuid": sprite_uuid,
                        "rawTextureUuid": tex_uuid,
                        "trimType": "auto",
                        "trimThreshold": 1,
                        "rotated": False,
                        "offsetX": 0,
                        "offsetY": 0,
                        "trimX": 0,
                        "trimY": 0,
                        "width": 0,
                        "height": 0,
                        "rawWidth": 0,
                        "rawHeight": 0,
                        "borderTop": 0,
                        "borderBottom": 0,
                        "borderLeft": 0,
                        "borderRight": 0,
                        "subMetas": {},
                    }
                },
            }

        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta_content, f, indent=2)
            return True
        except Exception as e:
            logger.exception(f"Error creating texture meta: {e}")
            return False

    @classmethod
    def create_audio_meta(cls, audio_path: Path, major_version: int = 2) -> bool:
        """Tạo tệp .meta cho AudioClip."""
        meta_path = audio_path.with_name(audio_path.name + ".meta")
        if meta_path.exists():
            return True

        uuid_str = cls.generate_uuid()
        meta_content = {
            "ver": "1.0.0",
            "uuid": uuid_str,
            "downloadMode": 0,
            "subMetas": {},
        }
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta_content, f, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def import_and_optimize(
        cls,
        file_bytes: bytes,
        original_filename: str,
        workspace_path: str,
        target_subfolder: Optional[str] = None,
        max_dimension: int = 2048,
        major_version: int = 2,
    ) -> tuple[bool, str, dict]:
        """
        Nhận diện loại tệp, tối ưu hóa (nén ảnh, resize) và lưu vào đúng thư mục assets của Cocos.
        
        Trả về: (thành_công, thông_báo, chi_tiết_asset)
        """
        ws = Path(workspace_path)
        ext = Path(original_filename).suffix.lower()
        base_name = Path(original_filename).name

        # 1. Xử lý Hình ảnh
        if ext in cls.IMAGE_EXTS:
            out_dir = ws / (target_subfolder or "assets/textures")
            out_dir.mkdir(parents=True, exist_ok=True)
            target_path = out_dir / base_name

            orig_size = len(file_bytes)
            orig_w, orig_h = 0, 0
            new_w, new_h = 0, 0

            try:
                img = Image.open(io.BytesIO(file_bytes))
                orig_w, orig_h = img.size

                # Resize nếu vượt quá kích thước tối đa
                if orig_w > max_dimension or orig_h > max_dimension:
                    img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                new_w, new_h = img.size

                # Lưu và tối ưu
                if ext == ".png":
                    img.save(target_path, format="PNG", optimize=True)
                elif ext in (".jpg", ".jpeg"):
                    img.save(target_path, format="JPEG", quality=85, optimize=True)
                elif ext == ".webp":
                    img.save(target_path, format="WEBP", quality=85)
                else:
                    with open(target_path, "wb") as f:
                        f.write(file_bytes)

                new_size = os.path.getsize(target_path)
                saved_percent = max(0, int((1 - (new_size / orig_size)) * 100)) if orig_size > 0 else 0

                # Tạo file .meta SpriteFrame
                cls.create_texture_meta(target_path, major_version)

                msg = (
                    f"🖼️ **ĐÃ NHẬP & TỐI ƯU ẢNH SPRITE THÀNH CÔNG!**\n\n"
                    f"📂 **Tệp:** `{base_name}`\n"
                    f"📁 **Vào thư mục:** `{out_dir.relative_to(ws)}`\n"
                    f"📐 **Kích thước:** `{orig_w}x{orig_h}` ➔ `{new_w}x{new_h}`\n"
                    f"📦 **Dung lượng:** `{orig_size // 1024} KB` ➔ `{new_size // 1024} KB` *(Giảm {saved_percent}%)*\n"
                    f"✨ *Đã tạo file `.meta` SpriteFrame tự động.*"
                )
                return True, msg, {
                    "type": "image",
                    "path": str(target_path),
                    "width": new_w,
                    "height": new_h,
                }

            except Exception as e:
                logger.exception("Error optimizing image")
                # Fallback lưu nguyên bản
                with open(target_path, "wb") as f:
                    f.write(file_bytes)
                cls.create_texture_meta(target_path, major_version)
                return True, f"📥 Đã lưu ảnh nguyên bản: `{base_name}` vào `{out_dir}`", {"type": "image", "path": str(target_path)}

        # 2. Xử lý Âm thanh
        elif ext in cls.AUDIO_EXTS:
            out_dir = ws / (target_subfolder or "assets/audios")
            out_dir.mkdir(parents=True, exist_ok=True)
            target_path = out_dir / base_name

            with open(target_path, "wb") as f:
                f.write(file_bytes)
            cls.create_audio_meta(target_path, major_version)

            msg = (
                f"🔊 **ĐÃ NHẬP FILE ÂM THANH!**\n\n"
                f"📂 **Tệp:** `{base_name}`\n"
                f"📁 **Vào thư mục:** `{out_dir.relative_to(ws)}`\n"
                f"📦 **Dung lượng:** `{len(file_bytes) // 1024} KB`\n"
                f"✨ *Đã tạo file `.meta` AudioClip tự động.*"
            )
            return True, msg, {"type": "audio", "path": str(target_path)}

        # 3. Xử lý Phông chữ
        elif ext in cls.FONT_EXTS:
            out_dir = ws / (target_subfolder or "assets/fonts")
            out_dir.mkdir(parents=True, exist_ok=True)
            target_path = out_dir / base_name
            with open(target_path, "wb") as f:
                f.write(file_bytes)
            return True, f"🔤 Đã lưu phông chữ `{base_name}` vào `{out_dir.relative_to(ws)}`", {"type": "font", "path": str(target_path)}

        # 4. Xử lý Tệp thông thường khác
        else:
            out_dir = ws / (target_subfolder or "assets")
            out_dir.mkdir(parents=True, exist_ok=True)
            target_path = out_dir / base_name
            with open(target_path, "wb") as f:
                f.write(file_bytes)
            return True, f"📥 Đã lưu tệp `{base_name}` vào `{out_dir.relative_to(ws)}`", {"type": "generic", "path": str(target_path)}


# Singleton instance
cocos_asset_importer = CocosAssetImporter()
