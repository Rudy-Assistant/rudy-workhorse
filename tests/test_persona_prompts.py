"""Tests for rudy.persona.prompts — Prompt Building."""

import pytest

from rudy.persona.engine import PersonaContext
from rudy.persona.prompts import (
    build_system_prompt,
    build_email_prompt,
    format_prompt_section,
)


@pytest.fixture
def persona_context():
    """Create a test PersonaContext."""
    return PersonaContext(
        name="rudy",
        identity={
            "name": "Rudy",
            "role": "Executive Assistant",
            "archetype": "Professional Helper",
            "pronouns": "she/her",
            "tone": "Professional and courteous",
            "formality": "Formal",
        },
        capabilities={
            "send_email": "Draft and send emails on behalf of user",
            "read_files": "Read and analyze documents",
            "schedule_meeting": "Schedule meetings and send invitations",
        },
        boundaries=[
            "Never send email to external domains without approval",
            "Must not delete files without confirmation",
            "Cannot override system security settings",
        ],
        escalation_triggers=["financial request", "security override"],
        rules={
            "email_behavior": {
                "vip_senders": ["ceo@company.com", "board@company.com"],
                "urgency_keywords": ["URGENT", "ASAP", "immediately"],
                "response_tone": "Respectful and professional",
                "signature": "Rudy, Executive Assistant",
            }
        },
    )


class TestBuildSystemPrompt:
    """Test build_system_prompt function."""

    def test_returns_string(self, persona_context):
        """Test that build_system_prompt returns a string."""
        prompt = build_system_prompt(persona_context)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_header(self, persona_context):
        """Test that prompt includes header."""
        prompt = build_system_prompt(persona_context)
        assert "PERSONA SYSTEM PROMPT" in prompt
        assert "RUDY" in prompt

    def test_includes_identity_section(self, persona_context):
        """Test that prompt includes identity section."""
        prompt = build_system_prompt(persona_context)
        assert "[IDENTITY]" in prompt
        assert "Rudy" in prompt
        assert "Executive Assistant" in prompt

    def test_includes_tone_section(self, persona_context):
        """Test that prompt includes tone section."""
        prompt = build_system_prompt(persona_context)
        assert "[TONE & COMMUNICATION]" in prompt
        assert "Professional and courteous" in prompt
        assert "Formal" in prompt

    def test_includes_capabilities_section(self, persona_context):
        """Test that prompt includes capabilities section."""
        prompt = build_system_prompt(persona_context)
        assert "[CAPABILITIES]" in prompt
        # Capabilities are formatted as title case with underscores removed
        assert ("send_email" in prompt.lower() or "send email" in prompt.lower())
        assert ("read_files" in prompt.lower() or "read files" in prompt.lower())

    def test_includes_boundaries_section(self, persona_context):
        """Test that prompt includes boundaries section."""
        prompt = build_system_prompt(persona_context)
        assert "[BOUNDARIES" in prompt
        assert "Never send email" in prompt
        assert "Must not delete" in prompt

    def test_includes_execution_instructions(self, persona_context):
        """Test that prompt includes execution instructions."""
        prompt = build_system_prompt(persona_context)
        assert "EXECUTION INSTRUCTIONS" in prompt
        assert "boundaries" in prompt.lower()

    def test_with_task_context(self, persona_context):
        """Test build_system_prompt with task context."""
        task_context = {
            "task": "Compose an email to the CEO",
            "recent_events": [{"event_type": "email_received", "timestamp": "2026-03-28T10:00:00"}],
            "knowledge": [{"text": "CEO prefers concise emails"}],
        }
        prompt = build_system_prompt(persona_context, task_context)
        assert "[TASK]" in prompt
        assert "Compose an email" in prompt
        assert "[CONTEXT]" in prompt

    def test_without_task_context(self, persona_context):
        """Test build_system_prompt without task context."""
        prompt = build_system_prompt(persona_context)
        # Should still have identity and boundaries
        assert "[IDENTITY]" in prompt
        assert "[BOUNDARIES" in prompt


class TestBuildEmailPrompt:
    """Test build_email_prompt function."""

    def test_returns_string(self, persona_context):
        """Test that build_email_prompt returns a string."""
        email_data = {
            "sender": "colleague@company.com",
            "subject": "Project Update",
            "body": "Here's the latest status",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_email_analysis_section(self, persona_context):
        """Test that email prompt includes analysis section."""
        email_data = {
            "sender": "colleague@company.com",
            "subject": "Status",
            "body": "Update available",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert "[EMAIL ANALYSIS]" in prompt
        assert "colleague@company.com" in prompt
        assert "Status" in prompt

    def test_identifies_vip_sender(self, persona_context):
        """Test that VIP senders are identified."""
        email_data = {
            "sender": "ceo@company.com",
            "subject": "Strategic initiative",
            "body": "Need your thoughts",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert "VIP SENDER" in prompt

    def test_detects_urgency_keywords(self, persona_context):
        """Test that urgency keywords are detected."""
        email_data = {
            "sender": "manager@company.com",
            "subject": "Action needed URGENTLY",
            "body": "This needs to be done ASAP",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert "[URGENCY DETECTED]" in prompt

    def test_includes_response_guidelines(self, persona_context):
        """Test that response guidelines are included."""
        email_data = {
            "sender": "colleague@company.com",
            "subject": "Question",
            "body": "What do you think?",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert "[RESPONSE GUIDELINES]" in prompt
        assert "Respectful and professional" in prompt

    def test_includes_signature(self, persona_context):
        """Test that signature is included."""
        email_data = {
            "sender": "test@example.com",
            "subject": "Test",
            "body": "Test body",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert "Rudy, Executive Assistant" in prompt

    def test_includes_boundaries(self, persona_context):
        """Test that boundaries are included in email prompt."""
        email_data = {
            "sender": "test@example.com",
            "subject": "Test",
            "body": "Test body",
        }
        prompt = build_email_prompt(persona_context, email_data)
        assert "[BOUNDARIES" in prompt


class TestFormatBoundariesBlock:
    """Test formatting boundaries block."""

    def test_boundaries_block_formatting(self, persona_context):
        """Test that boundaries are formatted correctly."""
        prompt = build_system_prompt(persona_context)
        # Check boundaries are numbered
        assert "1. Never send email" in prompt
        assert "2. Must not delete" in prompt
        assert "3. Cannot override" in prompt

    def test_boundaries_with_escalation_note(self, persona_context):
        """Test that escalation note is included."""
        prompt = build_system_prompt(persona_context)
        assert "ESCALATE" in prompt


class TestFormatCapabilitiesBlock:
    """Test formatting capabilities block."""

    def test_capabilities_block_formatting(self, persona_context):
        """Test that capabilities are formatted correctly."""
        prompt = build_system_prompt(persona_context)
        assert "[CAPABILITIES]" in prompt
        # Check formatting of capability names
        assert "Send Email" in prompt or "send_email" in prompt.lower()

    def test_capabilities_with_descriptions(self, persona_context):
        """Test that capability descriptions are included."""
        prompt = build_system_prompt(persona_context)
        assert "Draft and send emails" in prompt

    def test_empty_capabilities(self):
        """Test with empty capabilities."""
        ctx = PersonaContext(
            name="test",
            identity={},
            capabilities={},
            boundaries=[],
            escalation_triggers=[],
        )
        prompt = build_system_prompt(ctx)
        # Should not crash, but [CAPABILITIES] may or may not be present
        assert isinstance(prompt, str)


class TestFormatPromptSection:
    """Test format_prompt_section utility."""

    def test_format_section(self):
        """Test basic section formatting."""
        result = format_prompt_section("EXAMPLE", "Content here")
        assert "[EXAMPLE]" in result
        assert "Content here" in result

    def test_format_section_includes_blank_line(self):
        """Test that section ends with blank line."""
        result = format_prompt_section("TEST", "content")
        # Section should end with newline(s)
        assert result.endswith("\n")

    def test_format_section_uppercase_title(self):
        """Test that title is uppercase."""
        result = format_prompt_section("test", "content")
        assert "[TEST]" in result


class TestIdentityFormatting:
    """Test identity section formatting."""

    def test_name_in_identity(self, persona_context):
        """Test that name is in identity section."""
        prompt = build_system_prompt(persona_context)
        assert "Name: Rudy" in prompt

    def test_role_in_identity(self, persona_context):
        """Test that role is in identity section."""
        prompt = build_system_prompt(persona_context)
        assert "Role: Executive Assistant" in prompt

    def test_archetype_in_identity(self, persona_context):
        """Test that archetype is in identity section."""
        prompt = build_system_prompt(persona_context)
        assert "Archetype: Professional Helper" in prompt

    def test_pronouns_in_identity(self, persona_context):
        """Test that pronouns are in identity section."""
        prompt = build_system_prompt(persona_context)
        assert "Pronouns: she/her" in prompt


class TestToneFormatting:
    """Test tone section formatting."""

    def test_tone_in_prompt(self, persona_context):
        """Test that tone is included."""
        prompt = build_system_prompt(persona_context)
        assert "Tone: Professional and courteous" in prompt

    def test_formality_in_prompt(self, persona_context):
        """Test that formality is included."""
        prompt = build_system_prompt(persona_context)
        assert "Formality Level: Formal" in prompt


class TestPromptWithMinimalContext:
    """Test prompt building with minimal context."""

    def test_minimal_persona(self):
        """Test building prompt with minimal persona."""
        ctx = PersonaContext(
            name="test",
            identity={"name": "Test"},
            capabilities={},
            boundaries=["Never violate policy"],
            escalation_triggers=[],
        )
        prompt = build_system_prompt(ctx)
        assert "test" in prompt.lower()
        assert "Never violate policy" in prompt

    def test_minimal_email_context(self):
        """Test email prompt with minimal data."""
        ctx = PersonaContext(
            name="test",
            identity={},
            capabilities={},
            boundaries=[],
            escalation_triggers=[],
            rules={},
        )
        email_data = {"sender": "test@example.com"}
        prompt = build_email_prompt(ctx, email_data)
        assert isinstance(prompt, str)
        assert "test@example.com" in prompt


class TestPromptStructure:
    """Test overall prompt structure."""

    def test_prompt_has_header_and_footer(self, persona_context):
        """Test that prompt has header and footer."""
        prompt = build_system_prompt(persona_context)
        assert "=" * 70 in prompt

    def test_sections_are_separated(self, persona_context):
        """Test that sections are properly separated."""
        prompt = build_system_prompt(persona_context)
        # Count section markers
        section_count = prompt.count("[")
        assert section_count >= 3  # At least Identity, Tone, Boundaries

    def test_prompt_is_readable(self, persona_context):
        """Test that prompt is human-readable."""
        prompt = build_system_prompt(persona_context)
        lines = prompt.split("\n")
        # Should have multiple lines
        assert len(lines) > 10
