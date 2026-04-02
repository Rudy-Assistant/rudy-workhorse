"""MVT (Mobile Verification Toolkit) integration for phone forensics.

Extracted from phone_check.py during ADR-005 Phase 2a.
Wraps Amnesty International MVT CLI for iOS/Android backup scanning.
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class MVTIntegration:
    """Integration with Mobile Verification Toolkit (Amnesty International)."""

    def __init__(self):
        self.mvt_available = self._check_mvt()
        self.ioc_dir = IOC_DIR

    def _check_mvt(self) -> bool:
        _, _, rc = _run("mvt-android version")
        if rc == 0:
            return True
        _, _, rc = _run("mvt-ios version")
        return rc == 0

    def update_iocs(self) -> dict:
        """Download latest IOCs from Amnesty International."""
        IOC_DIR.mkdir(parents=True, exist_ok=True)
        ioc_url = "https://raw.githubusercontent.com/AmnestyTech/investigations/master/2021-07-18_nso/pegasus.stix2"

        try:
            import requests
            # Pegasus IOCs
            resp = requests.get(ioc_url, timeout=30)
            if resp.status_code == 200:
                ioc_file = IOC_DIR / "pegasus.stix2"
                with open(ioc_file, "w") as f:
                    f.write(resp.text)
                return {"success": True, "iocs_updated": True, "source": "amnesty_tech"}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

        return {"success": False, "error": "Could not download IOCs"}

    def scan_android_backup(self, backup_path: str) -> dict:
        """Run MVT against an Android backup."""
        if not self.mvt_available:
            return {"error": "MVT not installed. Run: pip install mvt"}

        output_dir = REPORTS_DIR / f"mvt-android-{int(time.time())}"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = f'mvt-android check-backup --output "{output_dir}"'
        if self.ioc_dir.exists():
            stix_files = list(self.ioc_dir.glob("*.stix2"))
            if stix_files:
                cmd += f' --iocs "{stix_files[0]}"'
        cmd += f' "{backup_path}"'

        stdout, stderr, rc = _run(cmd, timeout=300)
        return {
            "success": rc == 0,
            "output_dir": str(output_dir),
            "stdout": stdout[:2000],
            "stderr": stderr[:500],
        }

    def scan_ios_backup(self, backup_path: str) -> dict:
        """Run MVT against an iOS backup."""
        if not self.mvt_available:
            return {"error": "MVT not installed. Run: pip install mvt"}

        output_dir = REPORTS_DIR / f"mvt-ios-{int(time.time())}"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = f'mvt-ios check-backup --output "{output_dir}"'
        if self.ioc_dir.exists():
            stix_files = list(self.ioc_dir.glob("*.stix2"))
            if stix_files:
                cmd += f' --iocs "{stix_files[0]}"'
        cmd += f' "{backup_path}"'

        stdout, stderr, rc = _run(cmd, timeout=600)
        return {
            "success": rc == 0,
            "output_dir": str(output_dir),
            "stdout": stdout[:2000],
            "stderr": stderr[:500],
        }

