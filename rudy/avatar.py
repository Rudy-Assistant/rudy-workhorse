"""
Digital Avatar — Face swap, talking-head video, and digital presenter creation.

Capabilities:
  1. Talking-head video: photo + audio → animated speaking video
  2. Face swap: swap a face in a video/image
  3. Digital avatar generation from text description
  4. Lip sync: match existing video to new audio
  5. Presenter video: create instruction/presentation videos with digital host

Engines (tried in order):
  1. SadTalker — best open-source talking-head (photo + audio → video)
  2. InsightFace/inswapper — state-of-art face swap
  3. Wav2Lip — lip sync (match mouth to audio)
  4. Roop/facefusion — face replacement in video
  5. MoviePy compositing — fallback for basic overlay/effects

All processing is LOCAL — no cloud API needed, full privacy.
"""

import json
import os
import shutil
import subprocess

from datetime import datetime
from pathlib import Path
from typing import List

from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

AVATAR_DIR = RUDY_DATA / "avatar"
MODELS_DIR = AVATAR_DIR / "models"
OUTPUT_DIR = AVATAR_DIR / "output"
TEMP_DIR = AVATAR_DIR / "temp"
LOGS = RUDY_LOGS

def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

def _run(cmd: str, timeout: int = 300):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "Timeout", -1
    except Exception as e:
        return "", str(e), -1

class SadTalkerEngine:
    """
    SadTalker — generate talking-head video from a single image + audio.
    Paper: "SadTalker: Learning Realistic 3D Motion Coefficients for Stylized
    Audio-Driven Single Image Talking Face Animation" (CVPR 2023)

    Requires: pip install sadtalker (or clone from GitHub)
    """

    def __init__(self):
        self.available = self._check()
        self.sadtalker_dir = MODELS_DIR / "SadTalker"

    def _check(self) -> bool:
        try:
            # Check if sadtalker is available as a package or cloned repo
            stdout, _, rc = _run("python -c \"import sadtalker\"")
            if rc == 0:
                return True
            # Check for cloned repo
            if (MODELS_DIR / "SadTalker" / "inference.py").exists():
                return True
            return False
        except Exception:
            return False

    def generate(self, image_path: str, audio_path: str,
                 output_path: str, **kwargs) -> dict:
        """Generate talking-head video."""
        if not self.available:
            return {"error": "SadTalker not installed. Install via: pip install sadtalker"}

        enhancer = kwargs.get("enhancer", "gfpgan")  # Face enhancement
        still_mode = kwargs.get("still", False)  # Minimal head movement
        preprocess = kwargs.get("preprocess", "crop")  # crop, resize, full

        try:
            # Try module import first
            try:
                from sadtalker.api import SadTalker as STApi
                st = STApi()
                result = st.test(
                    source_image=image_path,
                    driven_audio=audio_path,
                    result_dir=str(OUTPUT_DIR),
                    enhancer=enhancer,
                    still=still_mode,
                    preprocess=preprocess,
                )
                if result:
                    shutil.copy2(result, output_path)
                    return {"success": True, "output": output_path, "engine": "sadtalker"}
            except ImportError:
                pass

            # Fallback to CLI
            cmd = (
                f'python "{self.sadtalker_dir}/inference.py" '
                f'--driven_audio "{audio_path}" '
                f'--source_image "{image_path}" '
                f'--result_dir "{OUTPUT_DIR}" '
                f'--enhancer {enhancer} '
                f'--preprocess {preprocess}'
            )
            if still_mode:
                cmd += " --still"

            stdout, stderr, rc = _run(cmd, timeout=600)
            if rc == 0:
                # Find the output video
                recent = max(OUTPUT_DIR.rglob("*.mp4"), key=os.path.getmtime, default=None)
                if recent:
                    shutil.copy2(str(recent), output_path)
                    return {"success": True, "output": output_path, "engine": "sadtalker"}

            return {"success": False, "error": stderr[:300], "engine": "sadtalker"}

        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "sadtalker"}

class Wav2LipEngine:
    """
    Wav2Lip — accurate lip-sync in videos.
    Match mouth movements to any audio on any face video/image.
    """

    def __init__(self):
        self.available = self._check()

    def _check(self) -> bool:
        try:
            stdout, _, rc = _run("python -c \"import wav2lip\"")
            return rc == 0
        except Exception:
            return False

    def lip_sync(self, video_path: str, audio_path: str,
                 output_path: str) -> dict:
        """Lip-sync a video to new audio."""
        if not self.available:
            return {"error": "Wav2Lip not installed"}

        try:
            cmd = (
                f'python -m wav2lip.inference '
                f'--face "{video_path}" '
                f'--audio "{audio_path}" '
                f'--outfile "{output_path}"'
            )
            stdout, stderr, rc = _run(cmd, timeout=600)
            if rc == 0:
                return {"success": True, "output": output_path, "engine": "wav2lip"}
            return {"success": False, "error": stderr[:300], "engine": "wav2lip"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "wav2lip"}

class FaceSwapEngine:
    """
    Face swap using InsightFace/inswapper or roop.
    Swap a face from a source image onto a target image/video.
    """

    def __init__(self):
        self.insightface_available = self._check_insightface()
        self.roop_available = self._check_roop()
        self.available = self.insightface_available or self.roop_available

    def _check_insightface(self) -> bool:
        try:
            import insightface
            return True
        except ImportError:
            return False

    def _check_roop(self) -> bool:
        stdout, _, rc = _run("python -c \"import roop\"")
        return rc == 0

    def swap_face_image(self, source_face: str, target_image: str,
                        output_path: str) -> dict:
        """Swap face in a single image."""
        if self.insightface_available:
            return self._insightface_swap_image(source_face, target_image, output_path)
        if self.roop_available:
            return self._roop_swap(source_face, target_image, output_path)
        return {"error": "No face swap engine available. Install: pip install insightface onnxruntime"}

    def swap_face_video(self, source_face: str, target_video: str,
                        output_path: str) -> dict:
        """Swap face in a video."""
        if self.roop_available:
            return self._roop_swap(source_face, target_video, output_path)
        return {"error": "Roop not installed for video face swap"}

    def _insightface_swap_image(self, source: str, target: str,
                                output: str) -> dict:
        """Face swap via InsightFace."""
        try:
            import cv2
            import insightface
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(name="buffalo_l")
            app.prepare(ctx_id=0, det_size=(640, 640))

            source_img = cv2.imread(source)
            target_img = cv2.imread(target)

            source_faces = app.get(source_img)
            target_faces = app.get(target_img)

            if not source_faces:
                return {"error": "No face detected in source image"}
            if not target_faces:
                return {"error": "No face detected in target image"}

            # Use inswapper model
            model_path = str(MODELS_DIR / "inswapper_128.onnx")
            if not Path(model_path).exists():
                return {
                    "error": "inswapper model not found. Download from InsightFace model zoo.",
                    "model_url": "https://huggingface.co/deepinsight/inswapper/resolve/main/inswapper_128.onnx",
                    "save_to": model_path,
                }

            swapper = insightface.model_zoo.get_model(model_path)
            result = target_img.copy()

            for face in target_faces:
                result = swapper.get(result, face, source_faces[0], paste_back=True)

            cv2.imwrite(output, result)
            return {"success": True, "output": output, "engine": "insightface"}

        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "insightface"}

    def _roop_swap(self, source: str, target: str, output: str) -> dict:
        """Face swap via roop/facefusion."""
        try:
            cmd = (
                f'python -m roop.core '
                f'-s "{source}" -t "{target}" -o "{output}" '
                f'--execution-provider cpu'
            )
            stdout, stderr, rc = _run(cmd, timeout=600)
            if rc == 0:
                return {"success": True, "output": output, "engine": "roop"}
            return {"success": False, "error": stderr[:300], "engine": "roop"}
        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "roop"}

class MoviePyCompositor:
    """
    Fallback video compositing using MoviePy.
    Can create basic presenter videos with image overlay + audio.
    """

    def __init__(self):
        self.available = self._check()

    def _check(self) -> bool:
        try:
            from moviepy.editor import ImageClip
            return True
        except ImportError:
            return False

    def create_presenter_video(self, image_path: str, audio_path: str,
                               output_path: str, background_color: tuple = (30, 30, 40),
                               resolution: tuple = (1920, 1080)) -> dict:
        """Create a simple presenter video: background + face image + audio."""
        if not self.available:
            return {"error": "MoviePy not installed"}

        try:
            from moviepy.editor import (
                ImageClip, AudioFileClip, ColorClip, CompositeVideoClip
            )

            audio = AudioFileClip(audio_path)
            duration = audio.duration

            # Background
            bg = ColorClip(size=resolution, color=background_color, duration=duration)

            # Face/presenter image
            presenter = ImageClip(image_path, duration=duration)
            # Scale to fit nicely
            scale = min(resolution[1] * 0.8 / presenter.h,
                        resolution[0] * 0.5 / presenter.w)
            presenter = presenter.resize(scale)
            presenter = presenter.set_position(("center", "center"))

            # Composite
            video = CompositeVideoClip([bg, presenter])
            video = video.set_audio(audio)
            video.write_videofile(
                output_path,
                fps=24,
                codec="libx264",
                audio_codec="aac",
                logger=None,
            )

            return {"success": True, "output": output_path, "engine": "moviepy_composite"}

        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "moviepy_composite"}

    def create_slideshow_video(self, images: List[str], audio_path: str,
                               output_path: str, duration_per_image: float = 5.0) -> dict:
        """Create a slideshow video from images + audio."""
        if not self.available:
            return {"error": "MoviePy not installed"}

        try:
            from moviepy.editor import (
                ImageClip, AudioFileClip, concatenate_videoclips
            )

            clips = []
            for img_path in images:
                clip = ImageClip(img_path, duration=duration_per_image)
                clip = clip.resize(height=1080)
                clips.append(clip)

            video = concatenate_videoclips(clips, method="compose")

            audio = AudioFileClip(audio_path)
            if audio.duration < video.duration:
                video = video.subclip(0, audio.duration)
            video = video.set_audio(audio)

            video.write_videofile(
                output_path, fps=24, codec="libx264",
                audio_codec="aac", logger=None,
            )

            return {"success": True, "output": output_path, "engine": "moviepy_slideshow"}

        except Exception as e:
            return {"success": False, "error": str(e)[:300], "engine": "moviepy_slideshow"}

class AvatarStudio:
    """
    Unified digital avatar interface.

    Usage:
        studio = AvatarStudio()

        # Create a talking-head video from photo + audio
        studio.talking_head("person.jpg", "speech.wav")

        # Face swap
        studio.face_swap("source_face.jpg", "target_video.mp4")

        # Presenter video (basic: image + audio → video)
        studio.presenter_video("host.jpg", "narration.wav")
    """

    def __init__(self):
        for d in [AVATAR_DIR, MODELS_DIR, OUTPUT_DIR, TEMP_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        self.sadtalker = SadTalkerEngine()
        self.wav2lip = Wav2LipEngine()
        self.face_swap_engine = FaceSwapEngine()
        self.compositor = MoviePyCompositor()

    def talking_head(self, image_path: str, audio_path: str,
                     output_path: str = None, **kwargs) -> dict:
        """
        Generate a talking-head video from a photo and audio.
        Tries SadTalker → Wav2Lip → MoviePy fallback.
        """
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = str(OUTPUT_DIR / f"talking_head_{ts}.mp4")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Try SadTalker (best quality)
        if self.sadtalker.available:
            result = self.sadtalker.generate(image_path, audio_path, output_path, **kwargs)
            if result.get("success"):
                return result

        # Try Wav2Lip
        if self.wav2lip.available:
            result = self.wav2lip.lip_sync(image_path, audio_path, output_path)
            if result.get("success"):
                return result

        # Fallback: static image + audio composited
        if self.compositor.available:
            result = self.compositor.create_presenter_video(
                image_path, audio_path, output_path
            )
            result["note"] = "Basic composite — install SadTalker for animated talking-head"
            return result

        return {
            "error": "No video engine available",
            "install_options": [
                "pip install sadtalker  (best: animated talking-head)",
                "pip install moviepy  (fallback: static image + audio)",
            ],
        }

    def face_swap(self, source_face: str, target: str,
                  output_path: str = None) -> dict:
        """
        Swap a face from source onto target (image or video).
        """
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            ext = Path(target).suffix
            output_path = str(OUTPUT_DIR / f"face_swap_{ts}{ext}")

        target_ext = Path(target).suffix.lower()
        if target_ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            return self.face_swap_engine.swap_face_video(source_face, target, output_path)
        else:
            return self.face_swap_engine.swap_face_image(source_face, target, output_path)

    def presenter_video(self, image_path: str, audio_path: str,
                        output_path: str = None, **kwargs) -> dict:
        """Create a presenter-style video (host image + narration audio)."""
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = str(OUTPUT_DIR / f"presenter_{ts}.mp4")

        # Try animated first, fall back to static composite
        result = self.talking_head(image_path, audio_path, output_path, **kwargs)
        return result

    def slideshow(self, images: List[str], audio_path: str,
                  output_path: str = None, duration_per_image: float = 5.0) -> dict:
        """Create a slideshow video from images + audio narration."""
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = str(OUTPUT_DIR / f"slideshow_{ts}.mp4")

        return self.compositor.create_slideshow_video(
            images, audio_path, output_path, duration_per_image
        )

    def generate_avatar(self, description: str, output_path: str = None) -> dict:
        """
        Generate an avatar image from a text description.
        Uses Stable Diffusion via local model or API.
        """
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = str(OUTPUT_DIR / f"avatar_{ts}.png")

        # Try local Stable Diffusion
        try:
            from diffusers import StableDiffusionPipeline
            import torch

            pipe = StableDiffusionPipeline.from_pretrained(
                "runwayml/stable-diffusion-v1-5",
                torch_dtype=torch.float32,
            )
            pipe = pipe.to("cpu")

            prompt = f"professional headshot portrait, {description}, high quality, photorealistic"
            image = pipe(prompt, num_inference_steps=20).images[0]
            image.save(output_path)
            return {"success": True, "output": output_path, "engine": "stable_diffusion_local"}

        except ImportError:
            pass
        except Exception:
            pass

        # Suggest alternatives
        return {
            "error": "No local image generation available on CPU",
            "alternatives": [
                "Use Canva MCP connector to generate images",
                "Use Hugging Face MCP connector for Stable Diffusion",
                "Use Replicate API for high-quality generation",
                "Provide a photo directly instead of generating one",
            ],
        }

    def check_engines(self) -> dict:
        """Check which engines are available."""
        return {
            "sadtalker": {"available": self.sadtalker.available, "quality": "best", "type": "talking_head"},
            "wav2lip": {"available": self.wav2lip.available, "quality": "good", "type": "lip_sync"},
            "face_swap_insightface": {"available": self.face_swap_engine.insightface_available, "type": "face_swap"},
            "face_swap_roop": {"available": self.face_swap_engine.roop_available, "type": "face_swap"},
            "moviepy_compositor": {"available": self.compositor.available, "quality": "basic", "type": "composite"},
        }

    def install_guide(self) -> str:
        """Print installation guide for all engines."""
        return """
Digital Avatar — Installation Guide
====================================

1. SadTalker (talking-head, BEST):
   pip install sadtalker
   OR: git clone https://github.com/OpenTalker/SadTalker
   Models auto-download on first run (~1.5GB)

2. Wav2Lip (lip sync):
   pip install wav2lip
   OR: git clone https://github.com/Rudrabha/Wav2Lip
   Download: wav2lip_gan.pth from project releases

3. InsightFace (face swap):
   pip install insightface onnxruntime
   Download inswapper_128.onnx from HuggingFace:
   https://huggingface.co/deepinsight/inswapper/resolve/main/inswapper_128.onnx
   Save to: rudy-data/avatar/models/inswapper_128.onnx

4. Roop (face swap, video):
   pip install roop
   OR: git clone https://github.com/s0md3v/roop

5. MoviePy (basic compositing, fallback):
   pip install moviepy
   Already installed on The Workhorse.

NOTE: All engines run on CPU. Quality is good but generation
is slow (1-5 min per video). For faster/better results, use
Replicate or HuggingFace API connectors.
"""

if __name__ == "__main__":
    print("Digital Avatar Studio")
    studio = AvatarStudio()

    print("\n  Available engines:")
    for name, info in studio.check_engines().items():
        status = "OK" if info["available"] else "NOT INSTALLED"
        print(f"    {name}: {status} ({info.get('type', '')})")

    print("\n  Usage:")
    print("    studio = AvatarStudio()")
    print('    studio.talking_head("photo.jpg", "speech.wav")')
    print('    studio.face_swap("face.jpg", "video.mp4")')
    print('    studio.presenter_video("host.jpg", "narration.wav")')
    print(studio.install_guide())
