# LF-S52-001: Inbox status filter silently drops messages without status field

**Severity:** HIGH
**Found by:** Alfred S52 (structured debug session)
**Fixed in:** PR #104
**Date:** 2026-04-01

## Description
RobinMailbox.check_inbox() and AlfredMailbox.check_inbox() in robin_alfred_protocol.py filter messages with:
```python
if msg.get("status") in ("unread", "pending"):
```

Messages from Batman Console, Lucius batch tasks, and older Alfred sessions do NOT include a status field. msg.get("status") returns None, which fails the filter. Every message in both ROBIN_INBOX and ROBIN_INBOX_V2 was silently dropped.

## Impact
- Robin processed zero inbox messages across sessions S47-S52
- Despite PRs #98-103 fixing other pipeline components, the first step (reading messages) was broken
- 28+ Lucius-delegated tasks accumulated without a single completion

## Root Cause
The S50 fix (PR #98) widened the filter from status == unread to status in (unread, pending) but missed the case where status is absent entirely. Classic sentinel value bug.

## Fix (PR #104)
```python
if msg.get("status", "unread") in ("unread", "pending"):
```
Messages without a status field now default to unread.

## Prevention
1. All message senders should include status: unread explicitly
2. Add debug logging when messages are filtered out
3. Integration tests should include messages without optional fields
