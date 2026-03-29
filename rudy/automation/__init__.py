"""
Phase 3: Automation Framework

Central automation coordination system for the Rudy Workhorse.
Manages webhooks, cron scheduling, email pipelines, and workflow triggers.

Module exports:
- AutomationEngine: Central coordinator for all automation triggers
- WebhookHandler: Receive and validate webhooks from n8n and external services
- WorkflowTrigger: Dataclass for trigger definitions
- CronScheduler: Schedule recurring tasks with cron expressions
- EmailPipeline: Persona-aware email processing and classification
"""

from rudy.automation.engine import AutomationEngine
from rudy.automation.webhook import WebhookHandler, WebhookEvent, N8nWebhookClient
from rudy.automation.cron import CronScheduler, CronJob
from rudy.automation.email_pipeline import EmailPipeline, EmailMessage

__all__ = [
    "AutomationEngine",
    "WebhookHandler",
    "WebhookEvent",
    "N8nWebhookClient",
    "CronScheduler",
    "CronJob",
    "EmailPipeline",
    "EmailMessage",
]
