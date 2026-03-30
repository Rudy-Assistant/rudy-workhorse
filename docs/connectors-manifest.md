<!-- Migrated from alfred-skills/connectors/MANIFEST.md (Session 11) -->

# Connected Services — Connector Manifest

Alfred works with external services through MCP (Model Context Protocol) connectors. Each connector gives Alfred the ability to read from and act on a specific service.

## How Connectors Work

Connectors are configured in Claude Desktop (or Cowork) and linked to Alfred through the MCP protocol. Once connected, Alfred can use the service's tools autonomously — reading emails, checking calendars, creating documents, etc.

## Available Connectors

### Gmail
- **What it does**: Read, search, and draft emails
- **Tools**: gmail_search_messages, gmail_read_message, gmail_read_thread, gmail_create_draft, gmail_get_profile, gmail_list_labels, gmail_list_drafts
- **Setup**: Connect via Zapier MCP or Google MCP server
- **Common uses**: Draft replies, search for specific emails, summarize threads, compose new messages with tone control

### Google Calendar
- **What it does**: View, create, and manage calendar events
- **Tools**: gcal_list_events, gcal_create_event, gcal_update_event, gcal_delete_event, gcal_find_meeting_times, gcal_find_my_free_time, gcal_list_calendars, gcal_get_event, gcal_respond_to_event
- **Setup**: Connect via Zapier MCP or Google MCP server
- **Common uses**: Check schedule, find free time, create meetings, send calendar invites

### Google Drive
- **What it does**: Search and read documents stored in Google Drive
- **Tools**: google_drive_search, google_drive_fetch
- **Setup**: Connect via Zapier MCP or Google MCP server
- **Common uses**: Find documents by name or content, read shared files, pull reference material

### GitHub
- **What it does**: Manage repositories, files, issues, and pull requests
- **Tools**: create_repository, push_files, create_or_update_file, get_file_contents, search_repositories, create_issue, create_pull_request, create_branch, fork_repository
- **Setup**: Connect via Zapier MCP or native GitHub MCP server
- **Common uses**: Push code, create repos, manage issues, review PRs

### Notion
- **What it does**: Read and manage Notion pages, databases, and views
- **Tools**: notion-search, notion-fetch, notion-create-pages, notion-update-page, notion-create-database, notion-create-view, notion-update-view, notion-get-users, notion-get-teams, notion-create-comment, notion-get-comments, notion-move-pages, notion-duplicate-page
- **Setup**: Connect via Notion MCP server (requires Notion integration token)
- **Common uses**: Update project databases, create pages, search knowledge base, manage tasks
