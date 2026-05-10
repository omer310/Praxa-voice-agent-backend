import json
import logging
import os
import re
import asyncio
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from dateutil import parser as date_parser
from supabase import Client

logger = logging.getLogger(__name__)

EMAIL_CACHE_TTL = 300
CALENDAR_DAY_LOOKBACK_DAYS = 1
CALENDAR_DAY_LOOKAHEAD_DAYS = 30

TOOL_LABELS: dict[str, str] = {
    "get_all_tasks": "Looking at your tasks...",
    "get_sprint_tasks": "Checking this week's tasks...",
    "get_backlog_tasks": "Checking your backlog...",
    "get_tasks_by_bucket": "Looking at your tasks...",
    "get_high_priority_tasks": "Finding your priority tasks...",
    "get_tasks_by_status": "Filtering your tasks...",
    "get_upcoming_deadlines": "Checking your deadlines...",
    "search_tasks": "Searching your tasks...",
    "create_task": "Creating a new task...",
    "complete_task": "Completing the task...",
    "update_task_priority": "Updating task priority...",
    "reschedule_task": "Rescheduling the task...",
    "add_task_note": "Adding a note to that task...",
    "update_loop": "Updating the task...",
    "rename_task": "Renaming the task...",
    "schedule_loop": "Scheduling the task...",
    "get_all_buckets": "Looking at your initiatives...",
    "get_bucket_goal": "Checking initiative goal...",
    "create_bucket": "Creating a new initiative...",
    "update_bucket": "Updating initiative...",
    "rename_bucket": "Renaming your initiative...",
    "archive_bucket": "Updating initiative...",
    "get_upcoming_events": "Checking your calendar...",
    "find_calendar_event": "Looking for that event...",
    "get_todays_events": "Looking at today's schedule...",
    "get_events_for_day": "Checking that day's schedule...",
    "reschedule_calendar_event": "Rescheduling your event...",
    "check_free_time": "Checking your availability...",
    "get_recent_emails": "Reading your recent emails...",
    "get_emails_needing_response": "Reviewing emails needing attention...",
    "get_unread_emails": "Checking your unread emails...",
    "search_emails": "Searching your emails...",
    "get_email_body": "Opening that email...",
    "reply_to_email": "Sending your reply...",
}

_PRAXA_SENDER_EMAIL: str = os.getenv("SENDGRID_FROM_EMAIL", "").lower().strip()


@dataclass
class UserData:
    user_id: str = ""
    email_grant_id: str | None = None
    calendar_grant_id: str | None = None
    supabase: Client | None = None
    last_fetched_emails: list = field(default_factory=list)
    timezone: str = "UTC"
    email_classification_cache: list = field(default_factory=list)
    email_classification_cache_ids: tuple[str, ...] | None = None
    email_classification_cache_at: float = 0.0


def _now(tz: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def _format_event_time(start_time, tz: str, fmt: str = "%A, %B %d at %I:%M %p") -> str:
    try:
        zone = ZoneInfo(tz)
        if isinstance(start_time, (int, float)):
            dt = datetime.fromtimestamp(start_time, tz=zone)
        else:
            dt = datetime.fromisoformat(str(start_time).replace("Z", "+00:00")).astimezone(zone)
        return dt.strftime(fmt).lstrip("0")
    except Exception:
        return str(start_time)


def _pick_primary_calendar(calendars: list) -> str | None:
    for cal in calendars:
        if cal.get("is_primary"):
            return cal.get("id")
    for cal in calendars:
        if not cal.get("read_only", False):
            return cal.get("id")
    return calendars[0].get("id") if calendars else None


def _auto_update_tz(calendars: list, primary_id: str | None, ud: UserData) -> None:
    candidates = []
    if primary_id:
        candidates += [c for c in calendars if c.get("id") == primary_id]
    candidates += [c for c in calendars if not c.get("read_only", False)]
    for cal in candidates:
        tz_str = cal.get("timezone")
        if tz_str:
            try:
                ZoneInfo(tz_str)
                if ud.timezone != tz_str:
                    logger.info(f"Timezone auto-detected from Google Calendar '{cal.get('name', '')}': {tz_str}")
                    ud.timezone = tz_str
                return
            except Exception:
                logger.warning(f"Ignoring invalid timezone from calendar: {tz_str}")


def _calendar_single_day_window(now_dt: datetime) -> tuple[date, date]:
    today = now_dt.date()
    lo = today - timedelta(days=CALENDAR_DAY_LOOKBACK_DAYS)
    hi = today + timedelta(days=CALENDAR_DAY_LOOKAHEAD_DAYS)
    return lo, hi


def _calendar_outside_window_message(lo: date, hi: date) -> str:
    return (
        f"I can only check specific days between {lo.strftime('%B %d, %Y')} and {hi.strftime('%B %d, %Y')} "
        f"(about one month from now). Ask again for a date in that range, or say what's coming up for a broader summary."
    )


def _resolve_calendar_target_day(day_raw: str, now_dt: datetime) -> tuple[date | None, str | None, str | None]:
    s = day_raw.strip()
    if not s:
        return None, None, "Say which day you want — for example tomorrow, Monday, or April 19."

    today = now_dt.date()
    tz = now_dt.tzinfo
    lo, hi = _calendar_single_day_window(now_dt)
    sl = s.lower()

    if sl in ("today", "now", "tonight"):
        target = today
    elif sl in ("tomorrow", "tmr", "tmrw"):
        target = today + timedelta(days=1)
    elif sl == "yesterday":
        target = today - timedelta(days=1)
    else:
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target = None
        for i, name in enumerate(day_names):
            if name in sl:
                days_ahead_delta = i - today.weekday()
                if days_ahead_delta <= 0:
                    days_ahead_delta += 7
                target = today + timedelta(days=days_ahead_delta)
                break
        if target is None:
            iso_m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s.strip())
            if iso_m:
                try:
                    y, mo, d = int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3))
                    target = date(y, mo, d)
                except ValueError:
                    return None, None, f"I couldn't parse '{s}' as a calendar date. Try a format like 2026-04-19 or April 19."
            else:
                try:
                    dt_parsed = date_parser.parse(s, default=now_dt, fuzzy=False)
                    target = dt_parsed.date()
                except (ValueError, TypeError, OverflowError):
                    try:
                        dt_parsed = date_parser.parse(s, default=now_dt, fuzzy=True)
                        target = dt_parsed.date()
                    except (ValueError, TypeError, OverflowError):
                        return None, None, (
                            f"I couldn't understand '{s}'. Try a specific date (April 19, 4/19/2026), "
                            f"tomorrow, or a weekday like Friday."
                        )

    if target is None:
        return None, None, "I couldn't work out which day you meant. Try a specific date like April 19 or 2026-04-19."

    if target < lo or target > hi:
        return None, None, _calendar_outside_window_message(lo, hi)

    day_label = datetime(target.year, target.month, target.day, tzinfo=tz).strftime("%A, %B %d, %Y")
    return target, day_label, None


def _calendar_no_events_for_day_message(day_label: str) -> str:
    return (
        f"I checked your connected primary calendar for {day_label} and didn't find any events in that day's window. "
        f"If something should appear, it may be on another calendar in your account or still syncing — double-check the app."
    )


def _calendar_no_events_upcoming_message() -> str:
    return (
        "I queried your connected primary calendar for roughly the next 30 days and don't see events in that range. "
        "If you're expecting meetings, confirm they're on the calendar account you linked, or try again after sync catches up."
    )


def _is_obviously_automated(from_email: str, snippet: str) -> bool:
    from_email = from_email.lower()
    snippet = snippet.lower() if snippet else ""

    if _PRAXA_SENDER_EMAIL and _PRAXA_SENDER_EMAIL in from_email:
        return True

    if any(kw in from_email for kw in ["noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster"]):
        return True

    local = from_email.split("@", 1)[0] if "@" in from_email else from_email
    if any(
        local.startswith(p)
        for p in (
            "newsletter", "notifications", "notification", "marketing",
            "promo", "bounce", "mailing", "digest", "mailer",
        )
    ):
        return True

    if any(kw in snippet for kw in ["unsubscribe", "opt out", "manage your email preferences", "view in browser", "list-unsubscribe"]):
        return True

    return False


async def _filter_reply_worthy_emails(emails: list, ud: UserData) -> list:
    if not emails:
        return []

    incoming_ids = tuple(str(m.get("id") or "") for m in emails)

    if (
        ud.email_classification_cache
        and ud.email_classification_cache_ids == incoming_ids
        and (time.time() - ud.email_classification_cache_at) < EMAIL_CACHE_TTL
    ):
        logger.info("Returning cached email classification")
        return ud.email_classification_cache

    candidates = [
        msg for msg in emails
        if not _is_obviously_automated(
            msg.get("from", [{}])[0].get("email", ""),
            msg.get("snippet", "") or "",
        )
    ]
    if not candidates:
        return []

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        return candidates

    lines = []
    for i, msg in enumerate(candidates, 1):
        from_name = msg.get("from", [{}])[0].get("name", "") or ""
        from_addr = msg.get("from", [{}])[0].get("email", "") or ""
        subject = (msg.get("subject", "") or "")[:140]
        snippet = (msg.get("snippet", "") or "")[:260]
        lines.append(f"{i}. From: {from_name} <{from_addr}> | Subject: {subject} | Preview: {snippet}")

    prompt = (
        "You filter inbox messages for a voice assistant. The user only wants to hear about mail "
        "where a real person would reasonably need to read or reply — not broadcast noise.\n\n"
        "For each line, output P (PASS — include) or A (SKIP — exclude).\n\n"
        "PASS (P) only when:\n"
        "- Someone is writing to the user in a way that expects a reply, decision, or personal follow-up.\n"
        "- Direct 1:1 or small-group thread, real meeting coordination, or a question clearly aimed at the user.\n\n"
        "SKIP (A) for:\n"
        "- Newsletters, digests, marketing, promos, event announcements, workshop invites, or program roundups "
        "sent to many people (including from .edu or trusted orgs).\n"
        "- Career office / campus / institutional announcements, career exploration mailings, or subject lines "
        "that read like a program name, newsletter title, or generic event (e.g. broad topics with no personal ask).\n"
        "- Automated transactional mail: receipts, alerts, shipping, password resets, billing, \"no-reply\" flows.\n"
        "- Anything that feels like a mailing list or campus blast rather than a message to the user personally.\n\n"
        "If unsure: if it sounds like a newsletter or mass announcement, choose A. If it sounds like a person wrote "
        "the user to continue a conversation, choose P.\n\n"
        + "\n".join(lines)
        + f"\n\nReply with exactly {len(candidates)} lines. Format: '1. P' or '1. A'. Nothing else."
    )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": len(candidates) * 8,
                    "temperature": 0,
                }
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                passed = []
                for line in content.splitlines():
                    line = line.strip()
                    parts = line.replace(".", " ").split()
                    if len(parts) >= 2 and parts[0].isdigit():
                        idx = int(parts[0]) - 1
                        if parts[-1].upper() == "P" and 0 <= idx < len(candidates):
                            passed.append(candidates[idx])

                ud.email_classification_cache = passed
                ud.email_classification_cache_ids = incoming_ids
                ud.email_classification_cache_at = time.time()
                return passed
    except Exception as e:
        logger.warning(f"AI email classification failed, using pre-filtered results: {e}")

    return candidates


def _resolve_email_id(ref: str, ud: UserData) -> str | None:
    if not ref:
        return None

    emails = ud.last_fetched_emails
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    ref_lower = ref.strip().lower()

    if ref_lower in ordinals:
        idx = ordinals[ref_lower] - 1
        if 0 <= idx < len(emails):
            return emails[idx].get("id")

    try:
        idx = int(ref_lower) - 1
        if 0 <= idx < len(emails):
            return emails[idx].get("id")
    except ValueError:
        pass

    for msg in emails:
        subject = (msg.get("subject") or "").lower()
        sender_name = (msg.get("from", [{}])[0].get("name") or "").lower()
        sender_email = (msg.get("from", [{}])[0].get("email") or "").lower()
        if ref_lower in subject or ref_lower in sender_name or ref_lower in sender_email:
            return msg.get("id")

    return ref


def sanitize_sql_like_pattern(user_input: str) -> str:
    if not user_input:
        return ""
    return user_input.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _infer_bucket_style(name: str, goal: str | None, description: str | None) -> tuple[str, str]:
    text = f"{name} {goal or ''} {description or ''}".lower()
    rules: list[tuple[tuple[str, ...], str, str]] = [
        (("work", "job", "career", "office", "business", "client", "startup", "company", "slack"), "briefcase.fill", "#6AACD8"),
        (("health", "fitness", "gym", "workout", "run", "doctor", "medical", "wellness", "sleep", "diet"), "dumbbell.fill", "#88C840"),
        (("money", "finance", "invest", "budget", "bank", "tax", "savings", "debt", "crypto"), "dollarsign.circle.fill", "#F2D060"),
        (("family", "kids", "parent", "spouse", "relationship", "wedding"), "person.2.fill", "#F5BC88"),
        (("home", "house", "renovat", "moving", "lease", "rent"), "house.fill", "#C8DC80"),
        (("learn", "study", "course", "school", "degree", "read", "book"), "graduationcap.fill", "#9E98D8"),
        (("creative", "design", "art", "music", "photo", "film", "write"), "paintbrush.fill", "#F5AACF"),
        (("code", "dev", "software", "app", "engineering", "ship"), "hammer.fill", "#3488C0"),
        (("travel", "trip", "flight", "vacation", "hotel"), "airplane", "#70C890"),
        (("side project", "hobby", "game", "fun"), "gamecontroller.fill", "#BDA8D4"),
        (("personal", "growth", "mind", "habit", "journal"), "leaf.fill", "#3A9490"),
        (("spiritual", "faith", "church", "meditat"), "moon.fill", "#7060C0"),
        (("volunteer", "community", "nonprofit", "charity"), "heart.fill", "#E05656"),
        (("legal", "contract", "law"), "building.columns.fill", "#4030A0"),
        (("car", "vehicle", "commute", "driving"), "car.fill", "#6CB8B4"),
        (("pet", "dog", "cat"), "pawprint.fill", "#F5C4A8"),
        (("food", "cook", "meal", "recipe", "grocery", "restaurant"), "fork.knife", "#E8793A"),
        (("email", "inbox", "message", "chat"), "envelope.fill", "#8DCADE"),
        (("calendar", "plan", "schedule", "event"), "calendar", "#3488C0"),
    ]
    for keywords, icon, color in rules:
        if any(k in text for k in keywords):
            return icon, color
    return "sparkles", "#3488C0"


def _sync_praxa_loop_after_event_reschedule(
    event_id: str,
    event_title: str,
    new_start_iso: str,
    due_date_str: str,
    ud: UserData,
) -> None:
    sb = ud.supabase
    uid = ud.user_id
    if not sb or not uid:
        return
    try:
        from datetime import timezone as dt_tz
        now_iso = datetime.now(dt_tz.utc).isoformat()
        payload = {
            "scheduled_time": new_start_iso,
            "due_date": due_date_str,
            "updated_at": now_iso,
        }
        res = (
            sb.table("loops")
            .update(payload)
            .eq("user_id", uid)
            .eq("calendar_event_id", event_id)
            .execute()
        )
        if getattr(res, "data", None):
            logger.info("[reschedule_calendar_event] Synced loop(s) with calendar_event_id=%s", event_id)
            return

        et = (event_title or "").strip()
        if not et:
            return
        r2 = (
            sb.table("loops")
            .select("id, calendar_event_id, title")
            .eq("user_id", uid)
            .eq("title", et)
            .limit(8)
            .execute()
        )
        for row in r2.data or []:
            cid = row.get("calendar_event_id")
            if cid and cid != event_id:
                continue
            extra = {}
            if not cid:
                extra["calendar_event_id"] = event_id
            sb.table("loops").update({**payload, **extra}).eq("id", row["id"]).execute()
            logger.info("[reschedule_calendar_event] Synced loop %s by title match", row.get("id"))
            return
    except Exception as e:
        logger.warning("[reschedule_calendar_event] Praxa task sync skipped: %s", e)


# ==================== TASK/LOOP TOOLS ====================

async def get_all_tasks(ud: UserData, view_tab: str | None = None) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        query = ud.supabase.table("loops").select(
            "id, title, status, priority, due_date, view_tab, buckets(name)"
        ).eq("user_id", ud.user_id).neq("status", "done")

        if view_tab:
            query = query.eq("view_tab", view_tab)

        response = query.eq("archived", False).execute()

        if not response.data:
            if view_tab == "sprint":
                return "No tasks scheduled for this week. Your sprint is clear!"
            elif view_tab == "backlog":
                return "No tasks in your backlog."
            return "No active tasks found."

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            priority = loop.get("priority", "medium")
            status = loop.get("status", "open")
            due = f", due {loop['due_date']}" if loop.get("due_date") else ""
            tasks.append(f"{loop['title']} ({priority} priority, {bucket} bucket, {status}{due})")

        context_str = ""
        if view_tab == "sprint":
            context_str = " for this week (sprint)"
        elif view_tab == "backlog":
            context_str = " in your backlog"

        return f"Found {len(tasks)} active tasks{context_str}: " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error getting tasks: {e}")
        return "Sorry, I couldn't fetch your tasks."


async def get_sprint_tasks(ud: UserData) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        response = ud.supabase.table("loops").select(
            "id, title, status, priority, due_date, scheduled_time, buckets(name)"
        ).eq("user_id", ud.user_id).eq("view_tab", "sprint").neq("status", "done").eq("archived", False).execute()

        if not response.data:
            return "No tasks scheduled for this week. Your sprint is clear!"

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            priority = loop.get("priority", "medium")
            status = loop.get("status", "open")
            scheduled = f", scheduled {loop['scheduled_time']}" if loop.get("scheduled_time") else ""
            due = f", due {loop['due_date']}" if loop.get("due_date") else ""
            tasks.append(f"{loop['title']} ({priority} priority, {bucket}, {status}{scheduled}{due})")

        return f"Found {len(tasks)} tasks scheduled for this week: " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error getting sprint tasks: {e}")
        return "Sorry, I couldn't fetch your sprint tasks."


async def get_backlog_tasks(ud: UserData) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        response = ud.supabase.table("loops").select(
            "id, title, status, priority, due_date, buckets(name)"
        ).eq("user_id", ud.user_id).eq("view_tab", "backlog").neq("status", "done").eq("archived", False).execute()

        if not response.data:
            return "No tasks in your backlog. All caught up!"

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            priority = loop.get("priority", "medium")
            status = loop.get("status", "open")
            due = f", due {loop['due_date']}" if loop.get("due_date") else ""
            tasks.append(f"{loop['title']} ({priority} priority, {bucket}, {status}{due})")

        return f"Found {len(tasks)} tasks in your backlog: " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error getting backlog tasks: {e}")
        return "Sorry, I couldn't fetch your backlog tasks."


async def get_tasks_by_bucket(ud: UserData, bucket_name: str) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_bucket_name = sanitize_sql_like_pattern(bucket_name)
        bucket_response = ud.supabase.table("buckets").select("id").eq(
            "user_id", ud.user_id
        ).ilike("name", safe_bucket_name).eq("archived", False).execute()

        if not bucket_response.data:
            return f"I couldn't find a bucket named '{bucket_name}'"

        bucket_id = bucket_response.data[0]["id"]
        response = ud.supabase.table("loops").select(
            "title, status, priority, due_date"
        ).eq("user_id", ud.user_id).eq("bucket_id", bucket_id).eq("archived", False).execute()

        if not response.data:
            return f"No tasks found in {bucket_name}"

        tasks = []
        for loop in response.data:
            due = f", Due: {loop['due_date']}" if loop.get("due_date") else ""
            tasks.append(f"- {loop['title']} ({loop['status']}, {loop['priority']} priority{due})")

        return f"Tasks in {bucket_name}:\n" + "\n".join(tasks)
    except Exception as e:
        logger.error(f"Error getting tasks by bucket: {e}")
        return f"Sorry, I couldn't fetch tasks for {bucket_name}"


async def get_high_priority_tasks(ud: UserData) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        response = ud.supabase.table("loops").select(
            "title, status, due_date, buckets(name)"
        ).eq("user_id", ud.user_id).eq("priority", "high").eq("archived", False).execute()

        if not response.data:
            return "No high priority tasks found."

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            status = loop.get("status", "open")
            due = f", due {loop['due_date']}" if loop.get("due_date") else ""
            tasks.append(f"{loop['title']} ({bucket}, {status}{due})")

        return f"Found {len(tasks)} high priority tasks: " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error getting high priority tasks: {e}")
        return "Sorry, I couldn't fetch high priority tasks"


async def get_tasks_by_status(ud: UserData, status: str) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        response = ud.supabase.table("loops").select(
            "title, priority, due_date, buckets(name)"
        ).eq("user_id", ud.user_id).eq("status", status).eq("archived", False).execute()

        if not response.data:
            return f"No {status} tasks found."

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            priority = loop.get("priority", "medium")
            due = f", due {loop['due_date']}" if loop.get("due_date") else ""
            tasks.append(f"{loop['title']} ({priority} priority, {bucket}{due})")

        return f"Found {len(tasks)} {status} tasks: " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error getting tasks by status: {e}")
        return f"Sorry, I couldn't fetch {status} tasks"


async def get_upcoming_deadlines(ud: UserData, days_ahead: int = 7) -> str:
    try:
        if not ud.user_id:
            return "I can't access your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        now_dt = _now(ud.timezone)
        end_date = (now_dt + timedelta(days=days_ahead)).date().isoformat()

        response = ud.supabase.table("loops").select(
            "title, due_date, priority, buckets(name)"
        ).eq("user_id", ud.user_id).lte("due_date", end_date).eq("archived", False).neq("status", "done").execute()

        if not response.data:
            return f"No upcoming deadlines in the next {days_ahead} days."

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            priority = loop.get("priority", "medium")
            tasks.append(f"{loop['title']} (due {loop['due_date']}, {priority} priority, {bucket})")

        return f"Found {len(tasks)} upcoming deadlines in the next {days_ahead} days: " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error getting upcoming deadlines: {e}")
        return "Sorry, I couldn't fetch upcoming deadlines"


async def search_tasks(ud: UserData, search_term: str) -> str:
    try:
        if not ud.user_id:
            return "I can't search your tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_search_term = sanitize_sql_like_pattern(search_term)
        response = ud.supabase.table("loops").select(
            "title, status, priority, buckets(name)"
        ).eq("user_id", ud.user_id).ilike("title", f"%{safe_search_term}%").eq("archived", False).execute()

        if not response.data:
            return f"No tasks found matching '{search_term}'."

        tasks = []
        for loop in response.data:
            bucket = loop.get("buckets", {}).get("name", "No bucket") if loop.get("buckets") else "No bucket"
            status = loop.get("status", "open")
            priority = loop.get("priority", "medium")
            tasks.append(f"{loop['title']} ({status}, {priority} priority, {bucket})")

        return f"Found {len(tasks)} tasks matching '{search_term}': " + "; ".join(tasks)
    except Exception as e:
        logger.error(f"Error searching tasks: {e}")
        return "Sorry, I couldn't search for tasks"


async def create_task(
    ud: UserData,
    title: str,
    bucket_name: str,
    priority: str = "medium",
    due_date: str | None = None,
) -> str:
    try:
        if not ud.user_id:
            return "I can't create tasks right now — it looks like you're not signed in. Please open the app and sign in first."
        sb = ud.supabase
        if not sb:
            return "Sorry, I couldn't create the task — the assistant isn't fully connected to your data yet."

        all_buckets_response = sb.table("buckets").select("id, name").eq(
            "user_id", ud.user_id
        ).eq("archived", False).execute()

        if not all_buckets_response.data:
            return "You don't have any buckets yet. Please create a bucket first before adding tasks."

        available_buckets = {b["name"].lower(): b for b in all_buckets_response.data}
        bucket_data = None

        if bucket_name.lower() in available_buckets:
            bucket_data = available_buckets[bucket_name.lower()]
        else:
            for bucket_key, bucket_val in available_buckets.items():
                if bucket_name.lower() in bucket_key or bucket_key in bucket_name.lower():
                    bucket_data = bucket_val
                    break

        if not bucket_data:
            bucket_names = ", ".join([b["name"] for b in all_buckets_response.data])
            return f"I couldn't find a bucket named '{bucket_name}'. Your available buckets are: {bucket_names}. Which one should I use?"

        bucket_id = bucket_data["id"]
        actual_bucket_name = bucket_data["name"]

        new_loop: dict = {
            "user_id": ud.user_id,
            "title": title,
            "status": "open",
            "priority": priority,
            "bucket_id": bucket_id,
        }

        if due_date:
            new_loop["due_date"] = due_date

        response = sb.table("loops").insert(new_loop).execute()
        if not response.data:
            return "Sorry, I couldn't create the task."

        if due_date:
            return f"Got it, added '{title}' to {actual_bucket_name}, due {due_date}"
        return f"Done, added '{title}' to {actual_bucket_name}"
    except Exception as e:
        logger.error(f"Error creating task: {e}", exc_info=True)
        err_s = str(e).lower()
        if "row-level security" in err_s or "42501" in str(e):
            return "Sorry, I couldn't save that task due to a permissions issue."
        return "Sorry, I couldn't create the task"


async def complete_task(ud: UserData, task_title: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_task_title = sanitize_sql_like_pattern(task_title)
        response = ud.supabase.table("loops").update(
            {"status": "done", "completed_at": datetime.now().isoformat()}
        ).eq("user_id", ud.user_id).ilike("title", f"%{safe_task_title}%").execute()

        if response.data:
            return f"Done! Marked '{task_title}' as complete"
        return f"I couldn't find a task matching '{task_title}'"
    except Exception as e:
        logger.error(f"Error completing task: {e}")
        return "Sorry, I couldn't complete the task"


async def update_task_priority(ud: UserData, task_title: str, new_priority: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_task_title = sanitize_sql_like_pattern(task_title)
        response = ud.supabase.table("loops").update(
            {"priority": new_priority}
        ).eq("user_id", ud.user_id).ilike("title", f"%{safe_task_title}%").execute()

        if response.data:
            return f"Updated '{task_title}' priority to {new_priority}"
        return f"Couldn't find task '{task_title}'"
    except Exception as e:
        logger.error(f"Error updating task priority: {e}")
        return "Sorry, I couldn't update the task priority"


async def reschedule_task(ud: UserData, task_title: str, new_due_date: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        due_date_str = new_due_date
        if ":" in new_due_date or "pm" in new_due_date.lower() or "am" in new_due_date.lower():
            due_date_str = datetime.now().date().isoformat()

        safe_task_title = sanitize_sql_like_pattern(task_title)
        response = ud.supabase.table("loops").update(
            {"due_date": due_date_str}
        ).eq("user_id", ud.user_id).ilike("title", f"%{safe_task_title}%").execute()

        if response.data:
            return f"Got it, rescheduled '{task_title}' to {new_due_date}"
        return f"I couldn't find a task called '{task_title}'"
    except Exception as e:
        logger.error(f"Error rescheduling task: {e}")
        return "Sorry, I couldn't reschedule the task"


async def add_task_note(ud: UserData, task_title: str, note: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_task_title = sanitize_sql_like_pattern(task_title)
        existing = ud.supabase.table("loops").select("id, notes").eq(
            "user_id", ud.user_id
        ).ilike("title", f"%{safe_task_title}%").limit(1).execute()

        if not existing.data:
            return f"I couldn't find a task matching '{task_title}'"

        task_id = existing.data[0]["id"]
        existing_notes = existing.data[0].get("notes", "") or ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_notes = f"{existing_notes}\n\n[{timestamp}] {note}".strip()

        ud.supabase.table("loops").update({
            "notes": new_notes,
            "updated_at": datetime.now().isoformat()
        }).eq("id", task_id).execute()

        return f"Got it, noted that down on '{task_title}'."
    except Exception as e:
        logger.error(f"Error adding task note: {e}")
        return "Sorry, I couldn't add that note"


async def update_loop(
    ud: UserData,
    task_title: str,
    status: str | None = None,
    description: str | None = None,
    is_this_week: bool | None = None,
    estimated_duration_minutes: int | None = None,
) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_task_title = sanitize_sql_like_pattern(task_title)
        updates: dict = {}
        changes: list[str] = []

        if status and status in ("open", "in_progress", "done"):
            updates["status"] = status
            changes.append(f"status → {status}")
        if description is not None:
            updates["description"] = description
            changes.append("description updated")
        if is_this_week is not None:
            updates["is_this_week"] = is_this_week
            changes.append("added to this week's focus" if is_this_week else "removed from this week's focus")
        if estimated_duration_minutes is not None and estimated_duration_minutes > 0:
            updates["estimated_duration_minutes"] = estimated_duration_minutes
            changes.append(f"estimated time → {estimated_duration_minutes} min")

        if not updates:
            return "Nothing to update — tell me what you'd like to change."

        updates["updated_at"] = datetime.now().isoformat()
        response = ud.supabase.table("loops").update(updates).eq(
            "user_id", ud.user_id
        ).ilike("title", f"%{safe_task_title}%").execute()

        if response.data:
            return f"Updated '{task_title}': {', '.join(changes)}."
        return f"I couldn't find a task matching '{task_title}'"
    except Exception as e:
        logger.error(f"Error updating loop: {e}", exc_info=True)
        return "Sorry, I couldn't update that task"


async def rename_task(ud: UserData, current_title: str, new_title: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."
        sb = ud.supabase
        if not sb:
            return "Sorry, I couldn't rename the task right now."
        safe_old = sanitize_sql_like_pattern(current_title)
        response = sb.table("loops").update({
            "title": new_title,
            "updated_at": datetime.now().isoformat(),
        }).eq("user_id", ud.user_id).ilike("title", f"%{safe_old}%").execute()
        if response.data:
            return f"Renamed that to '{new_title}'."
        return f"I couldn't find a task matching '{current_title}'."
    except Exception as e:
        logger.error(f"Error renaming task: {e}", exc_info=True)
        err_s = str(e).lower()
        if "row-level security" in err_s or "42501" in str(e):
            return "Sorry, I couldn't save that rename due to a permissions issue."
        return "Sorry, I couldn't rename the task"


async def schedule_loop(ud: UserData, task_title: str, scheduled_time: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update tasks right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_task_title = sanitize_sql_like_pattern(task_title)
        try:
            parsed = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
            display = parsed.strftime("%A, %B %d at %I:%M %p")
        except ValueError:
            display = scheduled_time

        response = ud.supabase.table("loops").update({
            "scheduled_time": scheduled_time,
            "is_this_week": True,
            "updated_at": datetime.now().isoformat()
        }).eq("user_id", ud.user_id).ilike("title", f"%{safe_task_title}%").execute()

        if response.data:
            return f"Got it! '{task_title}' is scheduled for {display} and added to this week's focus."
        return f"I couldn't find a task matching '{task_title}'"
    except Exception as e:
        logger.error(f"Error scheduling loop: {e}")
        return "Sorry, I couldn't schedule that task"


# ==================== BUCKET TOOLS ====================

async def get_all_buckets(ud: UserData) -> str:
    try:
        if not ud.user_id:
            return "I can't access your buckets right now — sign in to the app first."

        response = ud.supabase.table("buckets").select("name, description, goal").eq(
            "user_id", ud.user_id
        ).eq("archived", False).execute()

        if not response.data:
            return "No buckets found."

        bucket_names = [b["name"] for b in response.data]
        result = f"Available buckets: {', '.join(bucket_names)}"

        details = []
        for b in response.data:
            if b.get("description") or b.get("goal"):
                desc = b.get("description", "")
                goal = b.get("goal", "")
                context_info = f" ({desc or goal})" if (desc or goal) else ""
                details.append(f"{b['name']}{context_info}")

        if details:
            result += ". Details: " + "; ".join(details)

        return result
    except Exception as e:
        logger.error(f"Error getting buckets: {e}")
        return "Sorry, I couldn't fetch your buckets"


async def get_bucket_goal(ud: UserData, bucket_name: str) -> str:
    try:
        if not ud.user_id:
            return "I can't access your buckets right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_bucket_name = sanitize_sql_like_pattern(bucket_name)
        response = ud.supabase.table("buckets").select("goal, description").eq(
            "user_id", ud.user_id
        ).ilike("name", safe_bucket_name).eq("archived", False).execute()

        if not response.data:
            return f"Couldn't find bucket '{bucket_name}'"

        bucket = response.data[0]
        goal = bucket.get("goal", "No goal set")
        desc = bucket.get("description", "")

        result = f"Goal for {bucket_name}: {goal}"
        if desc:
            result += f"\nDescription: {desc}"
        return result
    except Exception as e:
        logger.error(f"Error getting bucket goal: {e}")
        return f"Sorry, I couldn't get the goal for {bucket_name}"


async def create_bucket(
    ud: UserData,
    name: str,
    description: str | None = None,
    goal: str | None = None,
) -> str:
    try:
        if not ud.user_id:
            return "I can't create buckets right now — it looks like you're not signed in. Please open the app and sign in first."
        sb = ud.supabase
        if not sb:
            return "Sorry, I couldn't create that initiative — the assistant isn't fully connected to your data yet."

        icon, color = _infer_bucket_style(name, goal, description)
        new_bucket = {
            "user_id": ud.user_id,
            "name": name,
            "description": description,
            "goal": goal,
            "color": color,
            "icon": icon,
        }

        response = sb.table("buckets").insert(new_bucket).execute()
        if not response.data:
            return "Sorry, I couldn't create the bucket."

        return f"Created bucket: {name}" + (f" with goal: {goal}" if goal else "")
    except Exception as e:
        logger.error(f"Error creating bucket: {e}", exc_info=True)
        err_s = str(e).lower()
        if "row-level security" in err_s or "42501" in str(e):
            return "Sorry, I couldn't save that initiative due to a permissions issue."
        return "Sorry, I couldn't create the bucket"


async def update_bucket(
    ud: UserData,
    bucket_name: str,
    goal: str | None = None,
    description: str | None = None,
) -> str:
    try:
        if not ud.user_id:
            return "I can't update initiatives right now — it looks like you're not signed in. Please open the app and sign in first."

        safe_bucket_name = sanitize_sql_like_pattern(bucket_name)
        updates: dict = {}
        changes: list[str] = []
        if goal is not None:
            updates["goal"] = goal
            changes.append("goal updated")
        if description is not None:
            updates["description"] = description
            changes.append("description updated")

        if not updates:
            return "Nothing to update — tell me what you'd like to change."

        updates["updated_at"] = datetime.now().isoformat()
        response = ud.supabase.table("buckets").update(updates).eq(
            "user_id", ud.user_id
        ).ilike("name", f"%{safe_bucket_name}%").execute()

        if response.data:
            return f"Updated '{bucket_name}': {', '.join(changes)}."
        return f"I couldn't find an initiative matching '{bucket_name}'"
    except Exception as e:
        logger.error(f"Error updating bucket: {e}", exc_info=True)
        return "Sorry, I couldn't update that initiative"


async def rename_bucket(ud: UserData, current_name: str, new_name: str) -> str:
    try:
        if not ud.user_id:
            return "I can't update initiatives right now — it looks like you're not signed in. Please open the app and sign in first."
        sb = ud.supabase
        if not sb:
            return "Sorry, I couldn't rename that initiative right now."
        safe_old = sanitize_sql_like_pattern(current_name)
        response = sb.table("buckets").update({
            "name": new_name,
            "updated_at": datetime.now().isoformat(),
        }).eq("user_id", ud.user_id).ilike("name", f"%{safe_old}%").eq("archived", False).execute()
        if response.data:
            return f"Renamed that initiative to '{new_name}'."
        return f"I couldn't find an initiative matching '{current_name}'."
    except Exception as e:
        logger.error(f"Error renaming bucket: {e}", exc_info=True)
        err_s = str(e).lower()
        if "row-level security" in err_s or "42501" in str(e):
            return "Sorry, I couldn't save that rename due to a permissions issue."
        if "unique" in err_s or "23505" in str(e) or "duplicate" in err_s:
            return "That name is already used. Try a different name."
        return "Sorry, I couldn't rename the initiative"


async def archive_bucket(ud: UserData, bucket_name: str, archived: bool) -> str:
    try:
        if not ud.user_id:
            return "I can't update initiatives right now — it looks like you're not signed in. Please open the app and sign in first."
        sb = ud.supabase
        if not sb:
            return "Sorry, I couldn't update that initiative right now."
        safe_name = sanitize_sql_like_pattern(bucket_name)
        response = sb.table("buckets").update({
            "archived": archived,
            "updated_at": datetime.now().isoformat(),
        }).eq("user_id", ud.user_id).ilike("name", f"%{safe_name}%").execute()
        if response.data:
            return f"{'Archived' if archived else 'Restored'} '{bucket_name}'."
        return f"I couldn't find an initiative matching '{bucket_name}'."
    except Exception as e:
        logger.error(f"Error archiving bucket: {e}", exc_info=True)
        err_s = str(e).lower()
        if "row-level security" in err_s or "42501" in str(e):
            return "Sorry, I couldn't update that initiative due to a permissions issue."
        return "Sorry, I couldn't update that initiative"


# ==================== CALENDAR TOOLS ====================

async def get_upcoming_events(ud: UserData, days_ahead: int = 30) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your calendar right now — it looks like you're not signed in. Please open the app and sign in first."

        calendar_grant_id = ud.calendar_grant_id
        if not calendar_grant_id and ud.supabase and ud.user_id:
            try:
                calendar_response = ud.supabase.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", ud.user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
                if calendar_response.data and calendar_response.data.get("grant_id"):
                    calendar_grant_id = calendar_response.data.get("grant_id")
                    ud.calendar_grant_id = calendar_grant_id
            except Exception as e:
                logger.error(f"Error fetching calendar grant ID: {e}")

        if not calendar_grant_id:
            return "I don't have access to your calendar yet. Please connect your calendar in the app settings."

        if not nylas_api_key:
            return "Calendar service is not configured. Please contact support."

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}
            cal_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/calendars",
                headers=headers
            )
            if cal_response.status_code != 200:
                if cal_response.status_code == 401:
                    return "I'm having trouble accessing your calendar. The connection may have expired. Please try reconnecting your calendar."
                if cal_response.status_code == 404:
                    return "Your calendar connection is no longer valid. Please reconnect your calendar in the app."
                return "I couldn't access your calendar. Please reconnect your calendar in the app."

            calendars = cal_response.json().get("data", [])
            if not calendars:
                return "No calendars found in your account."

            calendar_id = _pick_primary_calendar(calendars)
            _auto_update_tz(calendars, calendar_id, ud)

            _n = _now(ud.timezone)
            now_ts = int(_n.timestamp())
            end_ts = int((_n + timedelta(days=days_ahead)).timestamp())

            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events",
                headers=headers,
                params={"calendar_id": calendar_id, "limit": 50, "start": now_ts, "end": end_ts}
            )

            if response.status_code == 401:
                return "I'm having trouble accessing your calendar. The connection may have expired. Please try reconnecting your calendar."
            if response.status_code == 404:
                return "Your calendar connection is no longer valid. Please reconnect your calendar in the app."

            if response.status_code == 200:
                events = response.json().get("data", [])
                if not events:
                    return _calendar_no_events_upcoming_message()

                user_events = []
                holiday_events = []
                for event in events:
                    when = event.get("when", {})
                    title = event.get("title", "").lower()
                    is_holiday = any(keyword in title for keyword in [
                        "holiday", "observance", "public holiday", "national holiday",
                        "federal holiday", "bank holiday", "religious holiday"
                    ])
                    is_all_day = when.get("date") and not when.get("start_time")
                    if when.get("start_time") and not is_holiday:
                        user_events.append(event)
                    elif is_holiday or is_all_day:
                        holiday_events.append(event)

                all_events = user_events + holiday_events
                if not all_events:
                    return _calendar_no_events_upcoming_message()

                event_list = []
                for event in all_events[:20]:
                    title = event.get("title", "Untitled")
                    when = event.get("when", {})
                    start_time = when.get("start_time")
                    if start_time:
                        time_str = _format_event_time(start_time, ud.timezone, "%A, %B %d at %I:%M %p")
                        event_list.append(f"{title} ({time_str})")
                    else:
                        date_str = when.get("date", "")
                        if date_str:
                            try:
                                dt = datetime.fromisoformat(date_str)
                                event_list.append(f"{title} ({dt.strftime('%A, %B %d')})")
                            except Exception:
                                event_list.append(f"{title} ({date_str})")
                        else:
                            event_list.append(title)

                user_count = len(user_events)
                total_count = len(event_list)
                if user_count > 0:
                    return f"Found {total_count} upcoming events ({user_count} scheduled): " + "; ".join(event_list)
                return f"Found {total_count} upcoming events: " + "; ".join(event_list)

            return "I'm having trouble accessing your calendar right now. Please try again."
    except httpx.TimeoutException:
        return "The calendar service is taking too long to respond. Please try again."
    except Exception as e:
        logger.error(f"Error getting calendar events: {type(e).__name__}: {str(e)}")
        return "Sorry, I couldn't access your calendar"


async def find_calendar_event(ud: UserData, event_name: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your calendar right now — it looks like you're not signed in. Please open the app and sign in first."

        calendar_grant_id = ud.calendar_grant_id
        if not calendar_grant_id and ud.supabase and ud.user_id:
            try:
                cal_resp = ud.supabase.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", ud.user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
                if cal_resp.data and cal_resp.data.get("grant_id"):
                    calendar_grant_id = cal_resp.data.get("grant_id")
                    ud.calendar_grant_id = calendar_grant_id
            except Exception as e:
                logger.error(f"Error fetching calendar grant ID: {e}")

        if not calendar_grant_id:
            return "Calendar access isn't configured yet. Please connect your calendar in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}
            cal_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/calendars",
                headers=headers
            )
            if cal_response.status_code != 200:
                return "Couldn't access calendar"

            calendars = cal_response.json().get("data", [])
            if not calendars:
                return "No calendars found"

            calendar_id = _pick_primary_calendar(calendars)
            _auto_update_tz(calendars, calendar_id, ud)

            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events",
                headers=headers,
                params={"calendar_id": calendar_id, "limit": 50}
            )

            if response.status_code == 200:
                events = response.json().get("data", [])
                matching_events = [e for e in events if event_name.lower() in e.get("title", "").lower()]

                if not matching_events:
                    return f"No events found matching '{event_name}'"

                event_list = []
                for event in matching_events[:5]:
                    title = event.get("title", "Untitled")
                    when = event.get("when", {})
                    start_time = when.get("start_time") or when.get("date")
                    event_list.append(f"- {title}" + (f" ({start_time})" if start_time else ""))

                return f"Events matching '{event_name}':\n" + "\n".join(event_list)

            return "Couldn't search calendar events"
    except Exception as e:
        logger.error(f"Error finding calendar event: {type(e).__name__}: {str(e)}")
        return f"Sorry, I couldn't search for '{event_name}'"


async def get_todays_events(ud: UserData) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your calendar right now — it looks like you're not signed in. Please open the app and sign in first."

        calendar_grant_id = ud.calendar_grant_id
        if not calendar_grant_id and ud.supabase and ud.user_id:
            try:
                cal_resp = ud.supabase.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", ud.user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
                if cal_resp.data and cal_resp.data.get("grant_id"):
                    calendar_grant_id = cal_resp.data.get("grant_id")
                    ud.calendar_grant_id = calendar_grant_id
            except Exception as e:
                logger.error(f"Error fetching calendar grant ID: {e}")

        if not calendar_grant_id:
            return "Calendar access isn't configured yet. Please connect your calendar in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}
            cal_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/calendars",
                headers=headers
            )
            if cal_response.status_code != 200:
                return "Couldn't access calendar"

            calendars = cal_response.json().get("data", [])
            if not calendars:
                return "No calendars found"

            calendar_id = _pick_primary_calendar(calendars)
            _auto_update_tz(calendars, calendar_id, ud)

            now_dt = _now(ud.timezone)
            tz = now_dt.tzinfo
            today_start = int(datetime(now_dt.year, now_dt.month, now_dt.day, 0, 0, 0, tzinfo=tz).timestamp())
            today_end = int(datetime(now_dt.year, now_dt.month, now_dt.day, 23, 59, 59, tzinfo=tz).timestamp())

            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events",
                headers=headers,
                params={"calendar_id": calendar_id, "start": today_start, "end": today_end, "limit": 20}
            )

            if response.status_code == 200:
                events = response.json().get("data", [])
                if not events:
                    return _calendar_no_events_for_day_message(now_dt.strftime("%A, %B %d, %Y"))

                event_list = []
                for event in events:
                    title = event.get("title", "Untitled")
                    when = event.get("when", {})
                    start_time = when.get("start_time", "")
                    if start_time:
                        time_str = _format_event_time(start_time, ud.timezone, "%I:%M %p")
                        event_list.append(f"{title} at {time_str}")
                    else:
                        event_list.append(title)

                return "Today's schedule: " + "; ".join(event_list)

            return "I couldn't load today's events from the calendar service. Try again shortly."
    except Exception as e:
        logger.error(f"Error getting today's events: {type(e).__name__}: {str(e)}")
        return "Something went wrong checking today — try again in a moment."


async def get_events_for_day(ud: UserData, day: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your calendar right now — it looks like you're not signed in."

        calendar_grant_id = ud.calendar_grant_id
        if not calendar_grant_id and ud.supabase and ud.user_id:
            try:
                cal_resp = ud.supabase.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", ud.user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
                if cal_resp.data and cal_resp.data.get("grant_id"):
                    calendar_grant_id = cal_resp.data.get("grant_id")
                    ud.calendar_grant_id = calendar_grant_id
            except Exception as e:
                logger.error(f"Error fetching calendar grant ID: {e}")

        if not calendar_grant_id:
            return "Calendar access isn't configured yet. Please connect your calendar in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}
            cal_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/calendars",
                headers=headers
            )
            if cal_response.status_code != 200:
                return "I couldn't open your calendar list. Try again shortly."

            calendars = cal_response.json().get("data", [])
            if not calendars:
                return "No calendars were returned for your account."

            calendar_id = _pick_primary_calendar(calendars)
            _auto_update_tz(calendars, calendar_id, ud)

            now_dt = _now(ud.timezone)
            target_date, day_label, day_err = _resolve_calendar_target_day(day, now_dt)
            if day_err:
                return day_err

            tz = now_dt.tzinfo
            day_start = int(datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz).timestamp())
            day_end = int(datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=tz).timestamp())

            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events",
                headers=headers,
                params={"calendar_id": calendar_id, "start": day_start, "end": day_end, "limit": 50}
            )

            if response.status_code != 200:
                return f"I couldn't load events for {day_label} right now. Try again in a moment."

            events = response.json().get("data", [])
            if not events:
                return _calendar_no_events_for_day_message(day_label)

            event_list = []
            for event in events:
                title = event.get("title", "Untitled")
                when = event.get("when", {})
                start_time = when.get("start_time", "")
                if start_time:
                    time_str = _format_event_time(start_time, ud.timezone, "%I:%M %p")
                    event_list.append(f"{title} at {time_str}")
                else:
                    event_list.append(f"{title} (all day)")

            return f"{day_label}: " + "; ".join(event_list)
    except Exception as e:
        logger.error(f"Error getting events for day: {type(e).__name__}: {str(e)}")
        return "Something went wrong while checking that day — try again in a moment."


async def reschedule_calendar_event(ud: UserData, event_name: str, new_date_time: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your calendar right now — it looks like you're not signed in. Please open the app and sign in first."

        calendar_grant_id = ud.calendar_grant_id
        if not calendar_grant_id and ud.supabase and ud.user_id:
            try:
                calendar_response = ud.supabase.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", ud.user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
                if calendar_response.data and calendar_response.data.get("grant_id"):
                    calendar_grant_id = calendar_response.data.get("grant_id")
                    ud.calendar_grant_id = calendar_grant_id
            except Exception as e:
                logger.error(f"Error fetching calendar grant ID: {e}")

        if not calendar_grant_id:
            return "Calendar access isn't configured yet. Please connect your calendar in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {
                "Authorization": f"Bearer {nylas_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            cal_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/calendars",
                headers=headers
            )
            if cal_response.status_code != 200:
                return "Couldn't access calendar"

            calendars = cal_response.json().get("data", [])
            if not calendars:
                return "No calendars found"

            calendar_id = _pick_primary_calendar(calendars)
            events_url = f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events"
            events_response = await client.get(
                events_url, headers=headers,
                params={"calendar_id": calendar_id, "limit": 50}
            )

            if events_response.status_code != 200:
                return "Couldn't fetch events"

            events = events_response.json().get("data", [])
            matching_event = None
            event_name_lower = event_name.lower()
            for event in events:
                title = event.get("title", "").lower()
                if event_name_lower in title or title in event_name_lower:
                    matching_event = event
                    break

            if not matching_event:
                return f"Couldn't find an event matching '{event_name}'. Please check the exact name."

            event_id = matching_event.get("id")
            event_title = matching_event.get("title", "Untitled")

            try:
                if "T" in new_date_time:
                    new_dt = datetime.fromisoformat(new_date_time.replace("Z", "+00:00"))
                else:
                    new_dt = date_parser.parse(new_date_time)

                new_start_time = new_dt.isoformat()
                original_when = matching_event.get("when", {})
                original_start = original_when.get("start_time")
                original_end = original_when.get("end_time")
                duration_minutes = 60

                if original_start and original_end:
                    try:
                        start_dt = datetime.fromisoformat(original_start.replace("Z", "+00:00"))
                        end_dt = datetime.fromisoformat(original_end.replace("Z", "+00:00"))
                        duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
                    except Exception:
                        pass

                new_end_dt = new_dt + timedelta(minutes=duration_minutes)
                new_end_time = new_end_dt.isoformat()

                check_date = new_dt.date()
                start_of_day = datetime.combine(check_date, datetime.min.time()).isoformat()
                end_of_day = datetime.combine(check_date, datetime.max.time()).isoformat()

                day_events_response = await client.get(
                    events_url, headers=headers,
                    params={"calendar_id": calendar_id, "start": start_of_day, "end": end_of_day, "limit": 50}
                )

                conflicts = []
                if day_events_response.status_code == 200:
                    day_events = [e for e in day_events_response.json().get("data", []) if e.get("id") != event_id]
                    for existing_event in day_events:
                        existing_when = existing_event.get("when", {})
                        existing_start = existing_when.get("start_time")
                        existing_end = existing_when.get("end_time")
                        if existing_start and existing_end:
                            try:
                                es_dt = datetime.fromisoformat(existing_start.replace("Z", "+00:00"))
                                ee_dt = datetime.fromisoformat(existing_end.replace("Z", "+00:00"))
                                if not (new_end_dt <= es_dt or new_dt >= ee_dt):
                                    conflicts.append({"title": existing_event.get("title", "Untitled"), "start": es_dt, "end": ee_dt})
                            except Exception:
                                pass

                if conflicts:
                    conflict_titles = [c["title"] for c in conflicts]
                    conflict_str = ", ".join(conflict_titles[:2])
                    if len(conflicts) > 2:
                        conflict_str += f" and {len(conflicts) - 2} more"

                    timed_events = []
                    for existing_event in day_events_response.json().get("data", []):
                        if existing_event.get("id") == event_id:
                            continue
                        ew = existing_event.get("when", {})
                        es = ew.get("start_time")
                        ee = ew.get("end_time")
                        if es and ee:
                            try:
                                timed_events.append((
                                    datetime.fromisoformat(es.replace("Z", "+00:00")),
                                    datetime.fromisoformat(ee.replace("Z", "+00:00"))
                                ))
                            except Exception:
                                pass

                    timed_events.sort(key=lambda x: x[0])
                    day_start_dt = datetime.combine(check_date, datetime.min.time().replace(hour=8))
                    day_end_dt = datetime.combine(check_date, datetime.min.time().replace(hour=20))
                    free_slots = []
                    current_time = day_start_dt

                    for ev_start, ev_end in timed_events:
                        if ev_start < day_start_dt:
                            current_time = max(current_time, ev_end)
                            continue
                        if ev_start > day_end_dt:
                            break
                        if current_time < ev_start:
                            if (ev_start - current_time).total_seconds() / 60 >= duration_minutes:
                                free_slots.append((current_time, ev_start))
                        current_time = max(current_time, ev_end)

                    if current_time < day_end_dt and (day_end_dt - current_time).total_seconds() / 60 >= duration_minutes:
                        free_slots.append((current_time, day_end_dt))

                    suggestions = [slot_start.strftime("%I:%M %p") for slot_start, _ in free_slots[:5]]
                    date_str = new_dt.strftime("%A %B %d")

                    if suggestions:
                        return f"That time conflicts with {conflict_str} on {date_str}. Here are some free slots that work: {', '.join(suggestions)}. Would you like me to move it to one of these times?"
                    return f"That time conflicts with {conflict_str} on {date_str}. I couldn't find any free slots long enough on that day. Would you like to try a different day?"

                update_response = await client.put(
                    f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events/{event_id}",
                    headers=headers,
                    json={"when": {"start_time": new_start_time, "end_time": new_end_time}}
                )

                if update_response.status_code in [200, 201]:
                    _sync_praxa_loop_after_event_reschedule(
                        event_id, event_title, new_start_time, new_dt.date().isoformat(), ud
                    )
                    return f"Done! Moved '{event_title}' to {new_dt.strftime('%A %B %d at %I:%M %p')}"

                return "Couldn't reschedule the event. Please try again."

            except Exception as parse_error:
                logger.error(f"Error parsing date/time: {parse_error}")
                return f"Couldn't understand the date/time '{new_date_time}'. Please use a format like 'tomorrow at 2pm' or '2024-01-15T14:00:00'"
    except Exception as e:
        logger.error(f"Error rescheduling calendar event: {type(e).__name__}: {str(e)}")
        return "Sorry, I couldn't reschedule that event"


async def check_free_time(ud: UserData, date: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your calendar right now — it looks like you're not signed in. Please open the app and sign in first."

        calendar_grant_id = ud.calendar_grant_id
        if not calendar_grant_id and ud.supabase and ud.user_id:
            try:
                calendar_response = ud.supabase.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", ud.user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
                if calendar_response.data and calendar_response.data.get("grant_id"):
                    calendar_grant_id = calendar_response.data.get("grant_id")
                    ud.calendar_grant_id = calendar_grant_id
            except Exception as e:
                logger.error(f"Error fetching calendar grant ID: {e}")

        if not calendar_grant_id:
            return "Calendar access isn't configured yet. Please connect your calendar in the app settings."

        try:
            check_date = date_parser.parse(date).date()
        except Exception:
            try:
                check_date = datetime.fromisoformat(date).date()
            except Exception:
                return f"Couldn't understand the date '{date}'. Please use YYYY-MM-DD format or natural language like 'tomorrow'."

        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}

            cal_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/calendars",
                headers=headers
            )
            if cal_response.status_code != 200:
                return "Couldn't access calendar"

            calendars = cal_response.json().get("data", [])
            if not calendars:
                return "No calendars found"

            calendar_id = _pick_primary_calendar(calendars)
            start_of_day = datetime.combine(check_date, datetime.min.time()).isoformat()
            end_of_day = datetime.combine(check_date, datetime.max.time()).isoformat()

            events_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{calendar_grant_id}/events",
                headers=headers,
                params={"calendar_id": calendar_id, "start": start_of_day, "end": end_of_day, "limit": 50}
            )

            if events_response.status_code != 200:
                return "Couldn't fetch events for that day"

            events = events_response.json().get("data", [])
            timed_events = []
            for event in events:
                when = event.get("when", {})
                if when.get("start_time") and when.get("end_time"):
                    try:
                        start_dt = datetime.fromisoformat(when["start_time"].replace("Z", "+00:00"))
                        end_dt = datetime.fromisoformat(when["end_time"].replace("Z", "+00:00"))
                        timed_events.append((start_dt, end_dt))
                    except Exception:
                        pass

            timed_events.sort(key=lambda x: x[0])
            day_start = datetime.combine(check_date, datetime.min.time().replace(hour=8))
            day_end = datetime.combine(check_date, datetime.min.time().replace(hour=20))
            free_slots = []
            current_time = day_start

            for event_start, event_end in timed_events:
                if event_start < day_start:
                    current_time = max(current_time, event_end)
                    continue
                if event_start > day_end:
                    break
                if current_time < event_start:
                    free_slots.append((current_time, event_start))
                current_time = max(current_time, event_end)

            if current_time < day_end:
                free_slots.append((current_time, day_end))

            if not free_slots:
                return f"On {check_date.strftime('%A %B %d')}, you're fully booked from 8am to 8pm."

            slot_strings = []
            for start, end in free_slots:
                duration = int((end - start).total_seconds() / 60)
                slot_strings.append(f"{start.strftime('%I:%M %p')}-{end.strftime('%I:%M %p')} ({duration} minutes)")

            return f"On {check_date.strftime('%A %B %d')}, you have free time: " + "; ".join(slot_strings)
    except Exception as e:
        logger.error(f"Error checking free time: {type(e).__name__}: {str(e)}")
        return "Sorry, I couldn't check your free time"


# ==================== EMAIL TOOLS ====================

async def get_recent_emails(ud: UserData, limit: int = 5) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your emails right now — it looks like you're not signed in. Please open the app and sign in first."
        if not ud.email_grant_id:
            return "Email access isn't configured yet. Please connect your email in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages",
                headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"},
                params={"limit": limit * 3, "in": "INBOX"}
            )

            if response.status_code == 200:
                messages = response.json().get("data", [])
                important_emails = await _filter_reply_worthy_emails(messages, ud)
                important_emails = important_emails[:limit]

                if not important_emails:
                    return "No recent important emails that need your attention."

                ud.last_fetched_emails = important_emails
                email_list = []
                for i, msg in enumerate(important_emails, 1):
                    msg_id = msg.get("id", "")
                    sender_name = msg.get("from", [{}])[0].get("name") or msg.get("from", [{}])[0].get("email", "Unknown")
                    sender_email_addr = msg.get("from", [{}])[0].get("email", "")
                    subject = msg.get("subject", "No subject")
                    snippet = (msg.get("snippet", "") or "")[:150]
                    entry = f"[{i}] ID:{msg_id} | From: {sender_name} <{sender_email_addr}> | Subject: {subject}"
                    if snippet:
                        entry += f" | Preview: {snippet}"
                    email_list.append(entry)

                return (
                    f"Found {len(email_list)} recent important emails. "
                    "Call get_email_body with the number (e.g. '1') or subject to read any email in full.\n\n"
                    + "\n".join(email_list)
                )

            logger.error(f"Nylas email API error: {response.status_code}")
            return "Couldn't fetch emails"
    except Exception as e:
        logger.error(f"Error getting emails: {e}")
        return "Sorry, I couldn't access your emails"


async def get_emails_needing_response(ud: UserData) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your emails right now — it looks like you're not signed in. Please open the app and sign in first."
        if not ud.email_grant_id:
            return "Email access isn't configured yet. Please connect your email in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages",
                headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"},
                params={"limit": 20, "unread": "true", "in": "INBOX"}
            )

            if response.status_code == 200:
                messages = response.json().get("data", [])
                needs_response = await _filter_reply_worthy_emails(messages, ud)

                if not needs_response:
                    return "No unread emails from real people right now. Your inbox looks clear."

                ud.last_fetched_emails = needs_response[:7]
                email_list = []
                for i, msg in enumerate(needs_response[:7], 1):
                    msg_id = msg.get("id", "")
                    sender_name = msg.get("from", [{}])[0].get("name") or msg.get("from", [{}])[0].get("email", "Unknown")
                    sender_email_addr = msg.get("from", [{}])[0].get("email", "")
                    subject = msg.get("subject", "No subject")
                    snippet = (msg.get("snippet", "") or "")[:150]
                    entry = f"[{i}] ID:{msg_id} | From: {sender_name} <{sender_email_addr}> | Subject: {subject}"
                    if snippet:
                        entry += f" | Preview: {snippet}"
                    email_list.append(entry)

                return (
                    f"Here are {len(email_list)} emails that may need a response. "
                    "Call get_email_body with the number (e.g. '1') or subject to read the full email.\n\n"
                    + "\n".join(email_list)
                )

            logger.error(f"Nylas email API error: {response.status_code}")
            return "Couldn't fetch emails"
    except Exception as e:
        logger.error(f"Error checking emails: {e}")
        return "Sorry, I couldn't check for emails needing response"


async def get_unread_emails(ud: UserData) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your emails right now — it looks like you're not signed in. Please open the app and sign in first."
        if not ud.email_grant_id:
            return "Email access isn't configured yet. Please connect your email in the app settings."

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages",
                headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"},
                params={"unread": "true", "limit": 20, "in": "INBOX"}
            )

            if response.status_code == 200:
                messages = response.json().get("data", [])
                important_unread = await _filter_reply_worthy_emails(messages, ud)
                count = len(important_unread)

                if count == 0:
                    return "No unread important emails that need your attention."

                ud.last_fetched_emails = important_unread[:5]
                email_list = []
                for i, msg in enumerate(important_unread[:5], 1):
                    msg_id = msg.get("id", "")
                    sender = msg.get("from", [{}])[0].get("name") or msg.get("from", [{}])[0].get("email", "Unknown")
                    subject = msg.get("subject", "No subject")
                    preview = (msg.get("snippet", "") or "")[:120]
                    entry = f"[{i}] ID:{msg_id} | From: {sender} | Subject: {subject}"
                    if preview:
                        entry += f" | Preview: {preview}"
                    email_list.append(entry)

                result = (
                    f"Found {count} unread important email{'s' if count > 1 else ''} that may need your attention. "
                    "Call get_email_body with the number (e.g. '1') to read the full email.\n\n"
                    + "\n".join(email_list)
                )
                if count > 5:
                    result += f"\n(and {count - 5} more)"
                return result

            logger.error(f"Nylas email API error: {response.status_code}")
            return "Couldn't fetch unread emails"
    except Exception as e:
        logger.error(f"Error getting unread emails: {e}")
        return "Sorry, I couldn't get unread emails"


async def search_emails(ud: UserData, search_term: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your emails right now — it looks like you're not signed in. Please open the app and sign in first."
        if not ud.email_grant_id:
            return "Email access isn't configured yet. Please connect your email in the app settings."

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages",
                headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"},
                params={"limit": 50}
            )

            if response.status_code == 200:
                all_messages = response.json().get("data", [])
                search_term_lower = search_term.lower()
                matching_messages = []

                for msg in all_messages:
                    from_info = msg.get("from", [{}])[0] if msg.get("from") else {}
                    sender_name = (from_info.get("name") or "").lower()
                    sender_email = (from_info.get("email") or "").lower()
                    subject = (msg.get("subject") or "").lower()

                    if search_term_lower in sender_name or search_term_lower in sender_email or search_term_lower in subject:
                        matching_messages.append(msg)

                if not matching_messages:
                    search_response = await client.get(
                        f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages",
                        headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"},
                        params={"search": search_term, "limit": 20}
                    )
                    if search_response.status_code == 200:
                        search_results = search_response.json().get("data", [])
                        if search_results:
                            matching_messages = search_results

                if not matching_messages:
                    return f"I couldn't find any emails from or about '{search_term}'. They might be in an older conversation."

                email_list = []
                for msg in matching_messages[:10]:
                    from_info = msg.get("from", [{}])[0] if msg.get("from") else {}
                    sender_name = from_info.get("name") or from_info.get("email", "Unknown")
                    sender_email = from_info.get("email", "")
                    subject = msg.get("subject", "No subject")
                    date_val = msg.get("date", "")

                    if sender_email and sender_name != sender_email:
                        sender_display = f"{sender_name} ({sender_email})"
                    else:
                        sender_display = sender_name or sender_email

                    date_str = f" ({date_val})" if date_val else ""
                    email_list.append(f"{sender_display}: {subject}{date_str}")

                result = f"Found {len(matching_messages)} email" + ("s" if len(matching_messages) > 1 else "")
                if len(matching_messages) > 10:
                    result += f" (showing 10): " + "; ".join(email_list)
                else:
                    result += ": " + "; ".join(email_list)
                return result

            return f"Couldn't search for emails matching '{search_term}'"
    except Exception as e:
        logger.error(f"Error searching emails: {type(e).__name__}: {e}")
        return f"Sorry, I couldn't search for '{search_term}'"


async def get_email_body(ud: UserData, email_ref: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't access your emails right now — it looks like you're not signed in."
        if not ud.email_grant_id:
            return "Email access isn't configured yet. Please connect your email in the app settings."

        email_id = _resolve_email_id(email_ref, ud)
        if not email_id:
            return (
                "I couldn't identify which email you mean. "
                "Ask me to list your emails first, then say 'read email 1' or mention the sender's name."
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages/{email_id}",
                headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}
            )

            if response.status_code == 200:
                msg = response.json().get("data", {})
                sender_info = msg.get("from", [{}])[0]
                sender_name = sender_info.get("name") or sender_info.get("email", "Unknown")
                sender_email_addr = sender_info.get("email", "")
                subject = msg.get("subject", "No subject")
                date_val = msg.get("date", "")

                body = msg.get("body", "") or ""
                if body:
                    body = re.sub(r"<[^>]+>", " ", body)
                    body = re.sub(r"[ \t]+", " ", body)
                    body = re.sub(r"\n{3,}", "\n\n", body).strip()
                else:
                    body = msg.get("snippet", "") or "No content available."

                result = f"Email from {sender_name} <{sender_email_addr}>\nSubject: {subject}\n"
                if date_val:
                    result += f"Date: {date_val}\n"
                result += f"\n{body}"
                return result

            if response.status_code == 404:
                return f"Couldn't find an email with ID {email_id}. It may have been deleted."

            return "Couldn't retrieve the email content."
    except Exception as e:
        logger.error(f"Error getting email body: {e}")
        return "Sorry, I couldn't load that email."


async def reply_to_email(ud: UserData, email_id: str, reply_body: str) -> str:
    try:
        nylas_api_key = os.getenv("NYLAS_API_KEY")
        if not ud.user_id:
            return "I can't send emails right now — it looks like you're not signed in."
        if not ud.email_grant_id:
            return "Email access isn't configured yet. Please connect your email in the app settings."

        async with httpx.AsyncClient(timeout=15.0) as client:
            orig_response = await client.get(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages/{email_id}",
                headers={"Authorization": f"Bearer {nylas_api_key}", "Accept": "application/json"}
            )

            if orig_response.status_code != 200:
                return "Couldn't find the original email to reply to."

            orig = orig_response.json().get("data", {})
            orig_from = orig.get("from", [{}])[0]
            orig_subject = orig.get("subject", "")
            reply_to = orig.get("reply_to") or [orig_from]
            subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"

            send_response = await client.post(
                f"https://api.us.nylas.com/v3/grants/{ud.email_grant_id}/messages/send",
                headers={
                    "Authorization": f"Bearer {nylas_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={
                    "subject": subject,
                    "to": reply_to,
                    "reply_to_message_id": email_id,
                    "body": reply_body,
                }
            )

            if send_response.status_code in (200, 201):
                recipient_name = reply_to[0].get("name") or reply_to[0].get("email", "them")
                return f"Reply sent to {recipient_name}."

            logger.error(f"Nylas send reply error: {send_response.status_code} - {send_response.text[:300]}")
            return "Couldn't send the reply. The email service returned an error."
    except Exception as e:
        logger.error(f"Error sending reply: {e}")
        return "Sorry, I couldn't send that reply."


# ==================== TOOL DISPATCH ====================

TOOL_DISPATCH: dict[str, any] = {
    "get_all_tasks": get_all_tasks,
    "get_sprint_tasks": get_sprint_tasks,
    "get_backlog_tasks": get_backlog_tasks,
    "get_tasks_by_bucket": get_tasks_by_bucket,
    "get_high_priority_tasks": get_high_priority_tasks,
    "get_tasks_by_status": get_tasks_by_status,
    "get_upcoming_deadlines": get_upcoming_deadlines,
    "search_tasks": search_tasks,
    "create_task": create_task,
    "complete_task": complete_task,
    "update_task_priority": update_task_priority,
    "reschedule_task": reschedule_task,
    "add_task_note": add_task_note,
    "update_loop": update_loop,
    "rename_task": rename_task,
    "schedule_loop": schedule_loop,
    "get_all_buckets": get_all_buckets,
    "get_bucket_goal": get_bucket_goal,
    "create_bucket": create_bucket,
    "update_bucket": update_bucket,
    "rename_bucket": rename_bucket,
    "archive_bucket": archive_bucket,
    "get_upcoming_events": get_upcoming_events,
    "find_calendar_event": find_calendar_event,
    "get_todays_events": get_todays_events,
    "get_events_for_day": get_events_for_day,
    "reschedule_calendar_event": reschedule_calendar_event,
    "check_free_time": check_free_time,
    "get_recent_emails": get_recent_emails,
    "get_emails_needing_response": get_emails_needing_response,
    "get_unread_emails": get_unread_emails,
    "search_emails": search_emails,
    "get_email_body": get_email_body,
    "reply_to_email": reply_to_email,
}


async def dispatch_tool(name: str, args: dict, ud: UserData) -> str:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        logger.warning(f"Unknown tool called: {name}")
        return f"Unknown tool: {name}"
    try:
        return await fn(ud, **args)
    except Exception as e:
        logger.error(f"Tool {name} raised: {type(e).__name__}: {e}", exc_info=True)
        return f"Sorry, something went wrong while running {name}."
