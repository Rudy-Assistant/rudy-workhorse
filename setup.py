"""Rudy Workhorse — Autonomous Family Assistant & Command Center."""
from setuptools import setup, find_packages

setup(
    name="rudy-workhorse",
    version="0.1.0",
    description="Autonomous family assistant & home command center",
    author="Christopher M. Cimino",
    author_email="ccimino2@gmail.com",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "requests>=2.31",
        "beautifulsoup4>=4.12",
        "pyyaml>=6.0",
        "pydantic>=2.0",
        "httpx>=0.25",
        "psutil>=5.9",
        "rich>=13.0",
        "structlog>=23.0",
        "python-dotenv>=1.0",
        "humanize>=4.0",
        "tqdm>=4.65",
        "schedule>=1.2",
        "watchdog>=3.0",
        "tenacity>=8.2",
        "cryptography>=41.0",
        "pandas>=2.0",
        "fastapi>=0.100",
        "uvicorn>=0.23",
    ],
    extras_require={
        "ai": ["sentence-transformers", "chromadb", "langchain", "torch"],
        "voice": ["gTTS", "pydub", "soundfile", "yt-dlp", "openai-whisper"],
        "security": ["scapy", "python-nmap"],
        "creative": ["Pillow", "python-docx", "python-pptx", "svgwrite", "moviepy"],
        "dev": ["ruff", "black", "pytest"],
    },
    entry_points={
        "console_scripts": [
            "rudy-api=rudy.api_server:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows :: Windows 11",
    ],
)
