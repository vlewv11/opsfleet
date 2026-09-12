import json
import uuid

from google.auth.exceptions import DefaultCredentialsError
from langchain_core.messages import HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from src.agent import memory
from src.agent.agent import build
from src.agent.llm_client import PLATFORM, client as llm_client, get_llm
from src.tools import reports
from src.tools.bigquery import client as bq_client
from src.utils.config import settings
from src.utils.logger import new_trace, read_trace

HELP = """
[bold]Ask anything about sales, customers, products or inventory.[/bold]

  [cyan]/user <id>[/cyan]   switch manager (preferences and reports are per-user)
  [cyan]/reports[/cyan]     list this manager's saved reports
  [cyan]/report <id>[/cyan] print a saved report
  [cyan]/prefs[/cyan]       show learned preferences
  [cyan]/trace[/cyan]       show the execution trace of the last answer
  [cyan]/new[/cyan]         start a fresh conversation thread
  [cyan]/help[/cyan]  [cyan]/quit[/cyan]
"""


def run(user: str = "manager_a") -> None:
    console = Console()
    if problem := preflight():
        console.print(Panel(problem, title="[red]Setup incomplete[/red]", border_style="red"))
        return
    console.print(
        Panel.fit(
            f"[bold]Retail Analytics Assistant[/bold]\n"
            f"dataset [cyan]{settings.bq_dataset}[/cyan]  ·  model "
            f"[cyan]{llm_client(False).config.model}[/cyan] via [cyan]{PLATFORM}[/cyan]\n"
            f"[dim]/help for commands[/dim]",
            border_style="cyan",
        )
    )

    graph = build()
    thread, last_trace = uuid.uuid4().hex[:8], None

    while True:
        try:
            text = console.input(f"\n[bold cyan]{user}[/bold cyan] › ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            return
        if not text:
            continue

        if text.startswith("/"):
            command, _, argument = text[1:].partition(" ")
            if command in ("quit", "exit"):
                return
            if command == "help":
                console.print(HELP)
            elif command == "user":
                user, thread = argument.strip() or user, uuid.uuid4().hex[:8]
                console.print(f"[dim]Now speaking as {user}.[/dim]")
            elif command == "new":
                thread = uuid.uuid4().hex[:8]
                console.print("[dim]Started a new conversation.[/dim]")
            elif command == "prefs":
                console.print(memory.preferences(user))
            elif command == "reports":
                table = Table("id", "created", "title", box=None)
                for record in reports.listing(user):
                    table.add_row(record["id"], record["created_at"][:16], record["title"])
                console.print(table if table.row_count else "[dim]No saved reports yet.[/dim]")
            elif command == "report":
                match = [r for r in reports.listing(user) if r["id"] == argument.strip()]
                console.print(Markdown(match[0]["body"]) if match else "[dim]Not found.[/dim]")
            elif command == "trace":
                for entry in read_trace(last_trace or ""):
                    console.print(f"[dim]{entry['event']}[/dim] {json.dumps(entry, default=str)[:220]}")
            else:
                console.print(f"[dim]Unknown command {text}. /help for the list.[/dim]")
            continue

        last_trace = new_trace()
        memory.active_user.set(user)
        config = {"configurable": {"thread_id": f"{user}:{thread}"}, "recursion_limit": 60}
        state = {
            "messages": [HumanMessage(text)],
            "user_id": user,
            "steps": 0,
            "exhausted": False,
        }

        with console.status("[dim]thinking[/dim]", spinner="dots") as status:
            try:
                for update in graph.stream(state, config, stream_mode="updates"):
                    for node, payload in update.items():
                        for message in (payload or {}).get("messages", []) or []:
                            for call in getattr(message, "tool_calls", None) or []:
                                status.update(f"[dim]{call['name']}[/dim]")
                                console.print(f"[dim]  → {call['name']} {_brief(call['args'])}[/dim]")
                            if message.type == "tool":
                                console.print(f"[dim]  ← {_outcome(str(message.text))}[/dim]")
            except Exception as exc:
                console.print(f"[red]The assistant hit an unrecoverable error:[/red] {exc}")
                console.print(f"[dim]trace {last_trace}[/dim]")
                continue

        final = graph.get_state(config).values["messages"][-1]
        console.print()
        console.print(Markdown(str(final.text)))
        console.print(f"[dim]trace {last_trace}[/dim]")


def preflight() -> str:
    try:
        get_llm()
    except Exception as exc:
        return f"{exc}\n\nCopy [cyan].env.example[/cyan] to [cyan].env[/cyan] and set your key."
    try:
        bq_client()
    except DefaultCredentialsError:
        return (
            "No Google Cloud credentials found, so BigQuery is unreachable.\n\n"
            "Run [cyan]gcloud auth application-default login[/cyan], or set "
            "[cyan]GOOGLE_APPLICATION_CREDENTIALS[/cyan] to a service-account key file.\n"
            "Set [cyan]GCP_PROJECT[/cyan] in .env to the project that should be billed for queries."
        )
    except Exception as exc:
        return f"BigQuery client could not be created: {exc}"
    return ""


def _brief(args: dict) -> str:
    return json.dumps(args, default=str)[:110].replace("\n", " ")


def _outcome(payload: str) -> str:
    try:
        parsed = json.loads(payload)
    except ValueError:
        return payload[:110].replace("\n", " ")
    if parsed.get("status") == "ok":
        return f"{parsed['row_count']} rows, {parsed['repairs']} repair(s)"
    return f"{parsed.get('status', 'done')}: {str(parsed.get('last_error') or parsed.get('guidance', ''))[:90]}"
