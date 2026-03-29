"""
Prompt Builder — Generate persona-aware system prompts.

Constructs structured prompts that embed persona identity directly in
agent instructions, ensuring agents stay aligned with their role while
executing tasks.
"""

import logging
from typing import Dict, List, Optional, Any

from rudy.persona.engine import PersonaContext

log = logging.getLogger(__name__)


def build_system_prompt(
    persona_context: PersonaContext,
    task_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a complete system prompt embedding persona identity.

    Structure:
        [IDENTITY] — name, role, archetype, tone
        [TONE] — communication style and formality
        [CAPABILITIES] — what this persona can do
        [BOUNDARIES] — hard constraints
        [TASK] — specific task to execute
        [CONTEXT] — recent events and knowledge

    Args:
        persona_context: PersonaContext with loaded persona state
        task_context: Optional dict with task, recent_events, knowledge, etc.

    Returns:
        Formatted system prompt string
    """
    task_context = task_context or {}
    lines = []

    # Header
    lines.append("=" * 70)
    lines.append(f"PERSONA SYSTEM PROMPT — {persona_context.name.upper()}")
    lines.append("=" * 70)
    lines.append("")

    # [IDENTITY] Section
    lines.extend(_format_identity_block(persona_context.identity))
    lines.append("")

    # [TONE] Section
    lines.extend(_format_tone_block(persona_context.identity))
    lines.append("")

    # [CAPABILITIES] Section
    if persona_context.capabilities:
        lines.extend(_format_capabilities_block(persona_context.capabilities))
        lines.append("")

    # [BOUNDARIES] Section
    lines.extend(_format_boundaries_block(persona_context.boundaries))
    lines.append("")

    # [TASK] Section
    if task_context.get("task"):
        lines.append("[TASK]")
        lines.append(task_context["task"])
        lines.append("")

    # [CONTEXT] Section
    if task_context.get("recent_events") or task_context.get("knowledge"):
        lines.extend(_format_context_block(task_context))
        lines.append("")

    # Instructions
    lines.append("=" * 70)
    lines.append("EXECUTION INSTRUCTIONS:")
    lines.append("- Adhere strictly to all boundaries listed above")
    lines.append("- Use only capabilities within your persona scope")
    lines.append("- Log your actions and decisions")
    lines.append("- Escalate if a task conflicts with your boundaries")
    lines.append("=" * 70)

    return "\n".join(lines)


def _format_identity_block(identity: Dict[str, str]) -> List[str]:
    """Format the [IDENTITY] section of a system prompt.

    Args:
        identity: Identity dict from persona

    Returns:
        List of formatted lines
    """
    lines = ["[IDENTITY]"]

    name = identity.get("name", "Unnamed")
    lines.append(f"Name: {name}")

    if role := identity.get("role"):
        lines.append(f"Role: {role}")

    if archetype := identity.get("archetype"):
        lines.append(f"Archetype: {archetype}")

    if pronouns := identity.get("pronouns"):
        lines.append(f"Pronouns: {pronouns}")

    return lines


def _format_tone_block(identity: Dict[str, str]) -> List[str]:
    """Format the [TONE] section of a system prompt.

    Args:
        identity: Identity dict from persona

    Returns:
        List of formatted lines
    """
    lines = ["[TONE & COMMUNICATION]"]

    if tone := identity.get("tone"):
        lines.append(f"Tone: {tone}")

    if formality := identity.get("formality"):
        lines.append(f"Formality Level: {formality}")

    return lines


def _format_capabilities_block(capabilities: Dict[str, str]) -> List[str]:
    """Format the [CAPABILITIES] section of a system prompt.

    Args:
        capabilities: Capabilities dict from persona

    Returns:
        List of formatted lines
    """
    lines = ["[CAPABILITIES]"]
    lines.append("You can perform the following actions:")
    lines.append("")

    for capability_name, description in capabilities.items():
        # Format as readable bullet points
        pretty_name = capability_name.replace("_", " ").title()
        lines.append(f"• {pretty_name}")
        if description:
            lines.append(f"  {description}")

    return lines


def _format_boundaries_block(boundaries: List[str]) -> List[str]:
    """Format the [BOUNDARIES] section of a system prompt.

    Args:
        boundaries: List of boundary rules

    Returns:
        List of formatted lines
    """
    lines = ["[BOUNDARIES — STRICT CONSTRAINTS]"]
    lines.append("You MUST NOT violate these boundaries under any circumstances:")
    lines.append("")

    for i, boundary in enumerate(boundaries, 1):
        lines.append(f"{i}. {boundary}")

    lines.append("")
    lines.append("→ If a task conflicts with these boundaries, ESCALATE immediately.")

    return lines


def _format_context_block(task_context: Dict[str, Any]) -> List[str]:
    """Format the [CONTEXT] section of a system prompt.

    Args:
        task_context: Context dict with events, knowledge, etc.

    Returns:
        List of formatted lines
    """
    lines = ["[CONTEXT]"]

    # Recent events
    if events := task_context.get("recent_events"):
        lines.append("Recent Activity:")
        for event in events[:5]:  # Limit to 5
            if isinstance(event, dict):
                event_type = event.get("event_type", "event")
                timestamp = event.get("timestamp", "")
                payload = event.get("payload", {})
                lines.append(f"  • [{event_type}] {timestamp}: {payload}")
            else:
                lines.append(f"  • {event}")
        lines.append("")

    # Relevant knowledge
    if knowledge := task_context.get("knowledge"):
        lines.append("Relevant Knowledge:")
        for item in knowledge[:3]:  # Limit to 3
            if isinstance(item, dict):
                text = item.get("text", str(item))
                lines.append(f"  • {text}")
            else:
                lines.append(f"  • {item}")
        lines.append("")

    return lines


def build_email_prompt(
    persona_context: PersonaContext,
    email_data: Dict[str, Any],
) -> str:
    """Build a specialized prompt for email composition/triage.

    Email-specific rules from persona YAML are embedded.

    Args:
        persona_context: PersonaContext with loaded persona
        email_data: Dict with sender, subject, body, etc.

    Returns:
        Formatted email prompt string
    """
    task_context = {
        "task": f"Process email: {email_data.get('subject', '(no subject)')}",
        "email": email_data,
    }

    lines = []
    lines.append("=" * 70)
    lines.append("EMAIL HANDLING PROMPT")
    lines.append("=" * 70)
    lines.append("")

    # Load email behavior rules if available
    email_behavior = persona_context.rules.get("email_behavior", {})

    # Sender analysis
    sender = email_data.get("sender", "unknown")
    vip_senders = email_behavior.get("vip_senders", [])
    is_vip = sender in vip_senders

    lines.append("[EMAIL ANALYSIS]")
    lines.append(f"From: {sender}")
    if is_vip:
        lines.append("Status: VIP SENDER — prioritize this email")
    lines.append(f"Subject: {email_data.get('subject', '(no subject)')}")
    lines.append("")

    # Urgency check
    body = email_data.get("body", "")
    urgency_keywords = email_behavior.get("urgency_keywords", [])
    is_urgent = any(kw.lower() in body.lower() for kw in urgency_keywords)

    if is_urgent:
        lines.append("[URGENCY DETECTED]")
        lines.append("This email contains urgent language. Handle promptly.")
        lines.append("")

    # Response instructions
    lines.append("[RESPONSE GUIDELINES]")
    response_tone = email_behavior.get("response_tone", "Match sender's formality")
    lines.append(f"Tone: {response_tone}")
    lines.append("")

    # Task
    lines.append("[TASK]")
    lines.append("1. Analyze the email and extract key requests")
    lines.append("2. Determine appropriate response or action")
    lines.append("3. Draft a reply following the guidelines above")
    if signature := email_behavior.get("signature"):
        lines.append(f"4. Sign with: {signature}")
    lines.append("")

    # Boundaries
    lines.extend(_format_boundaries_block(persona_context.boundaries))
    lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)


def format_prompt_section(title: str, content: str) -> str:
    """Format a generic prompt section.

    Args:
        title: Section title
        content: Section content

    Returns:
        Formatted section string
    """
    lines = [
        f"[{title.upper()}]",
        content,
        "",
    ]
    return "\n".join(lines)
