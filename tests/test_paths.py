"""
Tests for rudy.paths module — path construction, environment handling, and portability.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPathsBasics:
    """Test that all path variables are Path objects."""

    def test_desktop_is_path_object(self):
        """DESKTOP must be a Path object."""
        from rudy import paths
        assert isinstance(paths.DESKTOP, Path)

    def test_rudy_is_path_object(self):
        """RUDY must be a Path object."""
        from rudy import paths
        assert isinstance(paths.RUDY, Path)

    def test_logs_is_path_object(self):
        """LOGS must be a Path object."""
        from rudy import paths
        assert isinstance(paths.LOGS, Path)

    def test_commands_is_path_object(self):
        """COMMANDS must be a Path object."""
        from rudy import paths
        assert isinstance(paths.COMMANDS, Path)

    def test_sessions_is_path_object(self):
        """SESSIONS must be a Path object."""
        from rudy import paths
        assert isinstance(paths.SESSIONS, Path)


class TestPathsConstruction:
    """Test that paths are constructed correctly."""

    def test_rudy_is_child_of_desktop(self):
        """RUDY must be a child directory of DESKTOP."""
        from rudy import paths
        assert paths.RUDY.parent == paths.DESKTOP
        assert paths.RUDY.name == "rudy"

    def test_logs_is_child_of_desktop(self):
        """LOGS must be a child directory of DESKTOP."""
        from rudy import paths
        assert paths.LOGS.parent == paths.DESKTOP
        assert paths.LOGS.name == "rudy-logs"

    def test_commands_is_child_of_desktop(self):
        """COMMANDS must be a child directory of DESKTOP."""
        from rudy import paths
        assert paths.COMMANDS.parent == paths.DESKTOP
        assert paths.COMMANDS.name == "rudy-commands"

    def test_sessions_is_child_of_desktop(self):
        """SESSIONS must be a child directory of DESKTOP."""
        from rudy import paths
        assert paths.SESSIONS.parent == paths.DESKTOP
        assert paths.SESSIONS.name == "rudy-sessions"

    def test_all_subdirs_are_under_desktop(self):
        """All subdirectories must be under DESKTOP."""
        from rudy import paths
        assert str(paths.RUDY).startswith(str(paths.DESKTOP))
        assert str(paths.LOGS).startswith(str(paths.DESKTOP))
        assert str(paths.COMMANDS).startswith(str(paths.DESKTOP))
        assert str(paths.SESSIONS).startswith(str(paths.DESKTOP))


class TestUserprofileEnvVar:
    """Test USERPROFILE environment variable handling."""

    def test_paths_constructed_correctly(self):
        """Paths should be constructed correctly from env var or expanduser."""
        from rudy import paths

        # DESKTOP should end with Desktop folder
        assert paths.DESKTOP.name == "Desktop"

    def test_userprofile_logic_in_source(self):
        """Verify that paths.py uses USERPROFILE env var in construction."""
        # Read the source to verify the pattern
        import rudy.paths as paths_module
        source = paths_module.__file__
        with open(source, 'r') as f:
            content = f.read()
            # Should use USERPROFILE
            assert 'USERPROFILE' in content
            # Should have fallback to expanduser
            assert 'expanduser' in content


class TestPathsNoHardcodedUsernames:
    """Test that paths use environment variables, not hardcoded usernames."""

    def test_paths_source_no_hardcoded_usernames(self):
        """Source code should not contain hardcoded usernames in path definitions."""
        import rudy.paths as paths_module
        source_file = paths_module.__file__
        with open(source_file, 'r') as f:
            content = f.read()

            # Check for specific hardcoded usernames in the source
            suspicious_patterns = [
                "/home/ccimino",
                "C:\\\\Users\\\\ccimino",
                "/Users/ccimino",
                "/home/admin",
                "C:\\\\Users\\\\admin",
            ]
            for pattern in suspicious_patterns:
                assert pattern not in content, \
                    f"Found hardcoded path pattern '{pattern}' in paths.py source"

    def test_desktop_path_constructed_from_env(self):
        """DESKTOP path should be constructed dynamically from env."""
        from rudy import paths

        # Should have a Desktop component
        assert "Desktop" in str(paths.DESKTOP)
        # Should not have obvious hardcoded names
        assert "ccimino" not in str(paths.DESKTOP).lower()


class TestPathsHierarchy:
    """Test the directory hierarchy relationships."""

    def test_paths_are_different(self):
        """All paths should be distinct."""
        from rudy import paths
        paths_set = {
            paths.DESKTOP,
            paths.RUDY,
            paths.LOGS,
            paths.COMMANDS,
            paths.SESSIONS,
        }
        assert len(paths_set) == 5, "All paths should be unique"

    def test_subdirs_are_siblings(self):
        """All subdirectories should share the same parent (DESKTOP)."""
        from rudy import paths
        assert paths.RUDY.parent == paths.DESKTOP
        assert paths.LOGS.parent == paths.DESKTOP
        assert paths.COMMANDS.parent == paths.DESKTOP
        assert paths.SESSIONS.parent == paths.DESKTOP

    def test_subdirs_are_not_parents_of_each_other(self):
        """Subdirectories should not be parent/child of each other."""
        from rudy import paths
        subdirs = [paths.RUDY, paths.LOGS, paths.COMMANDS, paths.SESSIONS]

        for i, subdir in enumerate(subdirs):
            for j, other in enumerate(subdirs):
                if i != j:
                    # Compare using parent relationships
                    # subdir should not be a parent of other
                    try:
                        other.relative_to(subdir)
                        # If no exception, subdir is parent of other - fail
                        assert False, f"{subdir.name} is parent of {other.name}"
                    except ValueError:
                        # Expected - not a parent relationship
                        pass


class TestPathsResolving:
    """Test that paths resolve correctly."""

    def test_paths_resolve_to_absolute(self):
        """All paths should be absolute."""
        from rudy import paths
        assert paths.DESKTOP.is_absolute()
        assert paths.RUDY.is_absolute()
        assert paths.LOGS.is_absolute()
        assert paths.COMMANDS.is_absolute()
        assert paths.SESSIONS.is_absolute()

    def test_paths_normalize(self):
        """Paths should normalize correctly (no duplicate separators)."""
        from rudy import paths

        for path in [paths.DESKTOP, paths.RUDY, paths.LOGS, paths.COMMANDS, paths.SESSIONS]:
            path_str = str(path)
            # Should not have double separators
            assert "//" not in path_str
            assert "\\\\" not in path_str
