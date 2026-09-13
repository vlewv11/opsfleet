import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retail analytics chat assistant")
    parser.add_argument("--user", default="manager_a", help="manager identity for preferences and reports")
    parser.add_argument("--web", action="store_true", help="serve the browser chat instead of the CLI")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    from src.cli.chat import preflight, run

    if problem := preflight():
        from rich.console import Console
        from rich.panel import Panel

        Console().print(Panel(problem, title="[red]Setup incomplete[/red]", border_style="red"))
    elif args.web:
        import uvicorn

        uvicorn.run("src.web.app:app", host="127.0.0.1", port=args.port)
    else:
        run(args.user)
