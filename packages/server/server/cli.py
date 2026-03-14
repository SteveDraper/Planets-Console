"""Typer CLI to run the server locally."""
import typer
import uvicorn

app = typer.Typer()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable reload"),
):
    """Run the Planets Console server (API + BFF)."""
    if ctx.invoked_subcommand is not None:
        return
    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
