# Creative Content Capabilities

## Services

| Service | Access Method | Status | Use Case |
|---------|--------------|--------|----------|
| **Canva** | MCP connector (Cowork) | Connected ✅ | Design, graphics, social media, presentations |
| **Hugging Face** | MCP connector (Cowork) | Suggested — click Connect | Image generation (Stable Diffusion, FLUX), text-to-image |
| **MidJourney** | Playwright via The Workhorse (web UI) | Chris has subscription | High-quality art (use stealth browser on midjourney.com, NOT Discord) |
| **Suno** | rudy-suno.py on The Workhorse | Chris has subscription — needs cookie/key setup | AI music generation (songs for niece/nephew) |
| **Replicate** | MCP server (Claude Code CLI) | Needs API token | Run any open-source AI model (SDXL, FLUX, etc.) |
| **Local generation** | Python on The Workhorse | Ready now | SVG art, matplotlib charts, Pillow image manipulation |

## Creative Workflow for Kids Content

1. **Stories**: Claude writes them natively → export as illustrated .docx or .pptx
2. **Art**: Hugging Face MCP or Replicate for image generation, Canva for polished designs
3. **Music**: Suno API for custom songs (birthday songs, lullabies, fun tunes)
4. **Coloring pages**: SVG generation via Python (svgwrite) on The Workhorse
5. **Videos/animations**: MoviePy compositing (stitch art + music → MP4), Canva templates, Manim for educational animations
6. **Video generation**: No local GPU — use Replicate/Hugging Face APIs for AI video (Wan 2.2, CogVideoX, AnimateDiff), MoviePy for compositing locally

## Voice & Avatar

- **Voice Clone** (`rudy/voice_clone.py`): Pocket TTS (primary)/OpenVoice/Bark, custom character voices, memorial voice recreation, batch script generation. Coqui TTS retired.
- **Avatar** (`rudy/avatar.py`): SadTalker talking-head, InsightFace face swap, Wav2Lip lip sync, MoviePy compositing, presenter videos
