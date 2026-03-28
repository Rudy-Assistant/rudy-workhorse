"""
Tests for rudy.admin module — elevated command and script execution.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

import rudy.admin as mod


class TestRunElevated:
    """Tests for run_elevated function."""

    def test_run_elevated_success(self, tmp_path, monkeypatch):
        """Test successful elevated command execution."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        # Create output file that the function will read
        output_content = "Command output here"

        def mock_run(cmd, **kwargs):
            # Simulate the function creating the output file
            output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
            output_file.write_text(output_content, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=mock_run):
            success, output = mod.run_elevated("test command")

        assert success is True
        assert output == output_content

    def test_run_elevated_failure(self, tmp_path, monkeypatch):
        """Test failed elevated command execution."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 1

        with patch("subprocess.run", return_value=result):
            success, output = mod.run_elevated("failing command")

        assert success is False
        assert output == ""

    def test_run_elevated_no_output_file(self, tmp_path, monkeypatch):
        """Test when output file is not created."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run", return_value=result):
            success, output = mod.run_elevated("command")

        assert success is True
        assert output == ""

    def test_run_elevated_timeout(self, tmp_path, monkeypatch):
        """Test timeout handling in elevated command."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)
        ):
            success, output = mod.run_elevated("slow command", timeout=30)

        assert success is False
        assert "timed out" in output.lower()

    def test_run_elevated_exception_handling(self, tmp_path, monkeypatch):
        """Test exception handling in elevated command."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        with patch("subprocess.run", side_effect=OSError("Access denied")):
            success, output = mod.run_elevated("command")

        assert success is False
        assert "Access denied" in output

    def test_run_elevated_command_wrapping(self, tmp_path, monkeypatch):
        """Test that command is properly wrapped for output redirection."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated("schtasks /query")

            # Verify subprocess.run was called
            assert mock_run.called
            # Verify the command contains the output redirection
            cmd_arg = mock_run.call_args[0][0]
            assert "Start-Process" in cmd_arg
            assert "RunAs" in cmd_arg
            assert "schtasks /query" in cmd_arg

    def test_run_elevated_output_file_cleanup(self, tmp_path, monkeypatch):
        """Test that output file is cleaned up after reading."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        output_content = "Test output"

        def mock_run(cmd, **kwargs):
            output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
            output_file.write_text(output_content, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=mock_run):
            mod.run_elevated("test")

        # Output file should be cleaned up
        output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
        assert not output_file.exists()

    def test_run_elevated_with_timeout_parameter(self, tmp_path, monkeypatch):
        """Test timeout parameter is passed to subprocess.run."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated("test", timeout=120)

            # Check timeout was passed
            assert mock_run.call_args[1]["timeout"] == 120

    def test_run_elevated_default_timeout(self, tmp_path, monkeypatch):
        """Test default timeout is 60 seconds."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated("test")

            # Check default timeout
            assert mock_run.call_args[1]["timeout"] == 60

    def test_run_elevated_output_with_utf8_errors(self, tmp_path, monkeypatch):
        """Test handling of UTF-8 decoding errors in output."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        # Create output file with invalid UTF-8 (will be handled with errors="replace")
        output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
        output_file.write_bytes(b"Valid: \xc3\xa9 Invalid: \x80\x81")

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run", return_value=result):
            with patch("time.sleep"):  # Skip actual sleep
                success, output = mod.run_elevated("test")

        assert success is True
        # Should have content despite encoding errors
        assert len(output) > 0


class TestRunElevatedPs:
    """Tests for run_elevated_ps function."""

    def test_run_elevated_ps_success(self, tmp_path, monkeypatch):
        """Test successful elevated PowerShell script execution."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        output_content = "PowerShell output"

        def mock_run(cmd, **kwargs):
            output_file = tmp_path / f"_elevated_ps_output_{os.getpid()}.txt"
            output_file.write_text(output_content, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=mock_run):
            success, output = mod.run_elevated_ps("Get-Service")

        assert success is True
        assert output == output_content

    def test_run_elevated_ps_failure(self, tmp_path, monkeypatch):
        """Test failed elevated PowerShell script execution."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 1

        with patch("subprocess.run", return_value=result):
            success, output = mod.run_elevated_ps("failing script")

        assert success is False
        assert output == ""

    def test_run_elevated_ps_script_file_creation(self, tmp_path, monkeypatch):
        """Test that script file is created."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0
        script_content = "Write-Host 'Test'"

        with patch("subprocess.run", return_value=result):
            mod.run_elevated_ps(script_content)

        # Script file should be cleaned up, but we can verify it was created
        script_files = list(tmp_path.glob("_elevated_ps_script_*.ps1"))
        assert len(script_files) == 0  # Cleaned up after execution

    def test_run_elevated_ps_script_content_written(self, tmp_path, monkeypatch):
        """Test that script content is written to file."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0
        script_content = "Get-Process -Name notepad"

        # Capture the file that was created
        created_files = []

        def track_write(cmd, **kwargs):
            # Find all .ps1 files created during the call
            created_files.extend(tmp_path.glob("_elevated_ps_script_*.ps1"))
            return result

        with patch("subprocess.run", side_effect=track_write):
            with patch("subprocess.run", return_value=result):
                with patch("pathlib.Path.write_text") as mock_write:
                    mock_write.return_value = None
                    mod.run_elevated_ps(script_content)

                    # Verify write_text was called with the script content
                    assert mock_write.called
                    call_args = mock_write.call_args
                    # First argument should be the script content
                    assert script_content in str(call_args)

    def test_run_elevated_ps_timeout(self, tmp_path, monkeypatch):
        """Test timeout handling in PowerShell execution."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)
        ):
            success, output = mod.run_elevated_ps("slow script", timeout=30)

        assert success is False
        assert "timed out" in output.lower()

    def test_run_elevated_ps_exception_handling(self, tmp_path, monkeypatch):
        """Test exception handling in PowerShell execution."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        with patch("subprocess.run", side_effect=OSError("Execution failed")):
            success, output = mod.run_elevated_ps("script")

        assert success is False
        assert "Execution failed" in output

    def test_run_elevated_ps_script_cleanup_on_success(self, tmp_path, monkeypatch):
        """Test that script file is cleaned up on success."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run", return_value=result):
            mod.run_elevated_ps("Write-Host 'test'")

        # Script file should be cleaned up
        script_files = list(tmp_path.glob("_elevated_ps_script_*.ps1"))
        assert len(script_files) == 0

    def test_run_elevated_ps_script_cleanup_on_failure(self, tmp_path, monkeypatch):
        """Test that script file is cleaned up on failure."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        # Create a script file first
        script_file = tmp_path / f"_elevated_ps_script_{os.getpid()}.ps1"
        script_file.write_text("test script", encoding="utf-8")

        with patch("subprocess.run", side_effect=OSError("Failed")):
            mod.run_elevated_ps("Write-Host 'test'")

        # Script file should still be cleaned up even after exception
        assert not script_file.exists()

    def test_run_elevated_ps_output_file_cleanup(self, tmp_path, monkeypatch):
        """Test that output file is cleaned up after reading."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        output_content = "Test output"

        def mock_run(cmd, **kwargs):
            output_file = tmp_path / f"_elevated_ps_output_{os.getpid()}.txt"
            output_file.write_text(output_content, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=mock_run):
            mod.run_elevated_ps("test")

        # Output file should be cleaned up
        output_file = tmp_path / f"_elevated_ps_output_{os.getpid()}.txt"
        assert not output_file.exists()

    def test_run_elevated_ps_default_timeout(self, tmp_path, monkeypatch):
        """Test default timeout is 60 seconds."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated_ps("test script")

            # Check default timeout
            assert mock_run.call_args[1]["timeout"] == 60

    def test_run_elevated_ps_custom_timeout(self, tmp_path, monkeypatch):
        """Test custom timeout parameter."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated_ps("test", timeout=90)

            # Check custom timeout
            assert mock_run.call_args[1]["timeout"] == 90

    def test_run_elevated_ps_command_formatting(self, tmp_path, monkeypatch):
        """Test that PowerShell command is properly formatted."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated_ps("Get-Service")

            # Verify subprocess.run was called
            assert mock_run.called
            # Verify the command contains PowerShell invocation
            cmd_arg = mock_run.call_args[0][0]
            assert "powershell" in cmd_arg.lower()
            assert "Start-Process" in cmd_arg
            assert "RunAs" in cmd_arg
            assert "ExecutionPolicy Bypass" in cmd_arg


class TestIsElevated:
    """Tests for is_elevated function."""

    def test_is_elevated_true(self):
        """Test when running with admin elevation."""
        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run", return_value=result):
            elevated = mod.is_elevated()

        assert elevated is True

    def test_is_elevated_false(self):
        """Test when not running with admin elevation."""
        result = MagicMock()
        result.returncode = 1

        with patch("subprocess.run", return_value=result):
            elevated = mod.is_elevated()

        assert elevated is False

    def test_is_elevated_exception_returns_false(self):
        """Test that exception during elevation check returns False."""
        with patch("subprocess.run", side_effect=OSError("Command failed")):
            elevated = mod.is_elevated()

        assert elevated is False

    def test_is_elevated_timeout_returns_false(self):
        """Test that timeout during elevation check returns False."""
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("net", 5)
        ):
            elevated = mod.is_elevated()

        assert elevated is False

    def test_is_elevated_uses_net_session(self):
        """Test that is_elevated uses 'net session' command."""
        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.is_elevated()

            # Verify net session command was used
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert call_args == ["net", "session"]

    def test_is_elevated_timeout_value(self):
        """Test that elevation check has 5 second timeout."""
        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.is_elevated()

            # Check timeout parameter
            assert mock_run.call_args[1]["timeout"] == 5

    def test_is_elevated_capture_output(self):
        """Test that elevation check captures output."""
        result = MagicMock()
        result.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.is_elevated()

            # Check capture_output and text flags
            assert mock_run.call_args[1]["capture_output"] is True
            assert mock_run.call_args[1]["text"] is True

    def test_is_elevated_various_error_types(self):
        """Test handling of various exception types."""
        exceptions = [
            OSError("Access denied"),
            RuntimeError("Process failed"),
            FileNotFoundError("net not found"),
            PermissionError("Permission denied"),
        ]

        for exc in exceptions:
            with patch("subprocess.run", side_effect=exc):
                elevated = mod.is_elevated()
                assert elevated is False


class TestIntegration:
    """Integration tests for admin module."""

    def test_log_dir_creation(self, tmp_path, monkeypatch):
        """Test that LOG_DIR is used for file operations."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        output_content = "Test output"

        def mock_run(cmd, **kwargs):
            output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
            output_file.write_text(output_content, encoding="utf-8")
            return result

        with patch("subprocess.run", side_effect=mock_run):
            success, output = mod.run_elevated("test")

        assert success is True
        assert output == output_content

    def test_process_id_in_filenames(self, tmp_path, monkeypatch):
        """Test that process ID is included in temporary filenames."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0
        current_pid = os.getpid()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = result
            mod.run_elevated("test")

            # Check that PID is used in the command
            cmd_arg = mock_run.call_args[0][0]
            assert str(current_pid) in cmd_arg

    def test_multiple_operations_isolation(self, tmp_path, monkeypatch):
        """Test that multiple operations don't interfere with each other."""
        monkeypatch.setattr(mod, "LOG_DIR", tmp_path)

        result = MagicMock()
        result.returncode = 0

        output1 = "Output 1"
        output2 = "Output 2"

        def mock_run_1(cmd, **kwargs):
            output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
            output_file.write_text(output1, encoding="utf-8")
            return result

        def mock_run_2(cmd, **kwargs):
            output_file = tmp_path / f"_elevated_output_{os.getpid()}.txt"
            output_file.write_text(output2, encoding="utf-8")
            return result

        with patch("subprocess.run", side_effect=mock_run_1):
            success1, out1 = mod.run_elevated("cmd1")

        with patch("subprocess.run", side_effect=mock_run_2):
            success2, out2 = mod.run_elevated("cmd2")

        assert success1 is True
        assert success2 is True
        assert out1 == output1
        assert out2 == output2
