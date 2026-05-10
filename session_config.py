TOOLS = [
    # ==================== TASK TOOLS ====================
    {
        "type": "function",
        "name": "get_all_tasks",
        "description": "Get all active loops/tasks for the current user. Optionally filter by view_tab (sprint/this week vs backlog).",
        "parameters": {
            "type": "object",
            "properties": {
                "view_tab": {
                    "type": "string",
                    "description": "Filter by view tab: 'sprint' (this week), 'backlog', or omit for all active tasks."
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_sprint_tasks",
        "description": "Get all tasks scheduled for this week (sprint view).",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "get_backlog_tasks",
        "description": "Get all tasks in the backlog (not scheduled for this week).",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "get_tasks_by_bucket",
        "description": "Get all tasks in a specific bucket/initiative.",
        "parameters": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string", "description": "Name of the bucket to filter by."}
            },
            "required": ["bucket_name"]
        }
    },
    {
        "type": "function",
        "name": "get_high_priority_tasks",
        "description": "Get all high priority tasks.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "get_tasks_by_status",
        "description": "Get tasks filtered by status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Status to filter by: open, in_progress, or done."}
            },
            "required": ["status"]
        }
    },
    {
        "type": "function",
        "name": "get_upcoming_deadlines",
        "description": "Get tasks with upcoming due dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Number of days to look ahead. Default is 7."}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "search_tasks",
        "description": "Search for tasks by title or description.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Text to search for in task titles or descriptions."}
            },
            "required": ["search_term"]
        }
    },
    {
        "type": "function",
        "name": "create_task",
        "description": "Create a new task/loop in a bucket. Use intelligent inference to determine the right bucket based on task content.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title of the task."},
                "bucket_name": {"type": "string", "description": "The bucket/initiative name where this task belongs. Infer intelligently from context if not explicitly stated."},
                "priority": {"type": "string", "description": "Priority level: low, medium, or high. Default is medium."},
                "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format. Omit if not specified."}
            },
            "required": ["title", "bucket_name"]
        }
    },
    {
        "type": "function",
        "name": "complete_task",
        "description": "Mark a task as completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "The title of the task to complete."}
            },
            "required": ["task_title"]
        }
    },
    {
        "type": "function",
        "name": "update_task_priority",
        "description": "Update the priority of a task.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "The title of the task."},
                "new_priority": {"type": "string", "description": "New priority: low, medium, or high."}
            },
            "required": ["task_title", "new_priority"]
        }
    },
    {
        "type": "function",
        "name": "reschedule_task",
        "description": "Reschedule a task to a new due date or time.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "The title of the task to reschedule."},
                "new_due_date": {"type": "string", "description": "New due date in YYYY-MM-DD format or time like '3:00 PM' for today."}
            },
            "required": ["task_title", "new_due_date"]
        }
    },
    {
        "type": "function",
        "name": "add_task_note",
        "description": "Add a note to an existing task. Use this to record progress updates, blockers, or any details the user shares.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "The title of the task to add a note to."},
                "note": {"type": "string", "description": "The note to add — progress update, blocker, or any detail worth remembering."}
            },
            "required": ["task_title", "note"]
        }
    },
    {
        "type": "function",
        "name": "update_loop",
        "description": "Update a task's status, description, weekly focus flag, or estimated duration.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "The title of the task to update."},
                "status": {"type": "string", "description": "New status: open, in_progress, or done."},
                "description": {"type": "string", "description": "New description for the task."},
                "is_this_week": {"type": "boolean", "description": "Whether to include this task in this week's focus."},
                "estimated_duration_minutes": {"type": "integer", "description": "Estimated time to complete in minutes."}
            },
            "required": ["task_title"]
        }
    },
    {
        "type": "function",
        "name": "rename_task",
        "description": "Rename a task's title.",
        "parameters": {
            "type": "object",
            "properties": {
                "current_title": {"type": "string", "description": "The current task title to find (partial match)."},
                "new_title": {"type": "string", "description": "The new title for the task."}
            },
            "required": ["current_title", "new_title"]
        }
    },
    {
        "type": "function",
        "name": "schedule_loop",
        "description": "Schedule a task for a specific date and time. Only call after you have a real day and time from the user. If they said 'schedule it' without a time, ask first.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "The title of the task to schedule."},
                "scheduled_time": {"type": "string", "description": "ISO 8601 datetime in the user's local timezone, e.g. '2026-04-15T14:00:00'."}
            },
            "required": ["task_title", "scheduled_time"]
        }
    },

    # ==================== BUCKET TOOLS ====================
    {
        "type": "function",
        "name": "get_all_buckets",
        "description": "Get all buckets/initiatives. Use this to intelligently infer which bucket a task belongs to.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "get_bucket_goal",
        "description": "Get the goal for a specific bucket.",
        "parameters": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string", "description": "Name of the bucket."}
            },
            "required": ["bucket_name"]
        }
    },
    {
        "type": "function",
        "name": "create_bucket",
        "description": "Create a new bucket/initiative. Icon and accent color are chosen automatically from the name and goal.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the new bucket."},
                "description": {"type": "string", "description": "Description of the bucket."},
                "goal": {"type": "string", "description": "Goal for this bucket."}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "update_bucket",
        "description": "Update a bucket/initiative's goal or description. Use when the user wants to change or refine what they're working toward.",
        "parameters": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string", "description": "The name of the bucket/initiative to update."},
                "goal": {"type": "string", "description": "New goal statement for this initiative."},
                "description": {"type": "string", "description": "New description for this initiative."}
            },
            "required": ["bucket_name"]
        }
    },
    {
        "type": "function",
        "name": "rename_bucket",
        "description": "Rename an initiative (bucket / category). Use when the user renames a bucket or initiative — not a task.",
        "parameters": {
            "type": "object",
            "properties": {
                "current_name": {"type": "string", "description": "Current initiative/bucket name (partial match)."},
                "new_name": {"type": "string", "description": "New name for the initiative/bucket."}
            },
            "required": ["current_name", "new_name"]
        }
    },
    {
        "type": "function",
        "name": "archive_bucket",
        "description": "Archive or restore an initiative bucket.",
        "parameters": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string", "description": "Name of the initiative/bucket to archive or restore."},
                "archived": {"type": "boolean", "description": "True to archive, False to unarchive."}
            },
            "required": ["bucket_name", "archived"]
        }
    },

    # ==================== CALENDAR TOOLS ====================
    {
        "type": "function",
        "name": "get_upcoming_events",
        "description": "Get upcoming calendar events for the next N days.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Number of days to look ahead from now. Default is 30."}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "find_calendar_event",
        "description": "Find a specific calendar event by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_name": {"type": "string", "description": "Name or keywords to search for in event titles."}
            },
            "required": ["event_name"]
        }
    },
    {
        "type": "function",
        "name": "get_todays_events",
        "description": "Get today's calendar events.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "get_events_for_day",
        "description": "Get calendar events for one specific day. Accepts natural language like 'tomorrow', 'Friday', 'April 19', or ISO dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Day to check: today/tomorrow/yesterday, weekday (Friday), or a date (April 19, 4/19/2026, 2026-04-19). Only dates within about one month (plus yesterday) are supported."}
            },
            "required": ["day"]
        }
    },
    {
        "type": "function",
        "name": "reschedule_calendar_event",
        "description": "Reschedule/move a calendar event to a new date and time.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_name": {"type": "string", "description": "Name or keywords to identify the calendar event to reschedule."},
                "new_date_time": {"type": "string", "description": "New date and time in ISO format (YYYY-MM-DDTHH:MM:SS) or natural language like 'tomorrow at 2pm', 'Friday at 10am'."}
            },
            "required": ["event_name", "new_date_time"]
        }
    },
    {
        "type": "function",
        "name": "check_free_time",
        "description": "Check for free time slots on a specific day.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date to check for free time in YYYY-MM-DD format or natural language like 'tomorrow', 'Friday'."}
            },
            "required": ["date"]
        }
    },

    # ==================== EMAIL TOOLS ====================
    {
        "type": "function",
        "name": "get_recent_emails",
        "description": "Get recent emails worth the user's attention — direct correspondence, not newsletters, digests, or institutional blasts.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent emails to fetch. Default is 5."}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_emails_needing_response",
        "description": "Get unread mail that may need a reply — real threads and asks, not campus/career roundups, newsletters, or bulk announcements.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "get_unread_emails",
        "description": "Get unread messages worth attention — excludes newsletters, marketing, and broadcast/announcement-style mail.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "type": "function",
        "name": "search_emails",
        "description": "Search emails by sender name, email address, or subject. Searches both sender name and email address fields.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {"type": "string", "description": "Search for emails by sender name, email address, or subject. Can be a person's name like 'John' or 'Sarah'."}
            },
            "required": ["search_term"]
        }
    },
    {
        "type": "function",
        "name": "get_email_body",
        "description": "Read the FULL content of a specific email. Use this whenever the user asks what an email says, wants to hear an email, or before replying. Pass '1', '2', etc. to refer to emails by number from the most recent listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_ref": {"type": "string", "description": "Which email to read: use the number shown in the list ('1', '2', '3'), a keyword from the subject, the sender's name, or the raw email ID."}
            },
            "required": ["email_ref"]
        }
    },
    {
        "type": "function",
        "name": "reply_to_email",
        "description": "Send a reply to a specific email. Always read the email body first with get_email_body before replying so you have the full context. Confirm the reply text with the user before sending.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "The email ID to reply to (from a previous email listing)."},
                "reply_body": {"type": "string", "description": "The text of the reply to send."}
            },
            "required": ["email_id", "reply_body"]
        }
    },
]
