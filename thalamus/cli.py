"""thalamus CLI: ask, show-record, eval, export."""
from __future__ import annotations

from pathlib import Path

import typer

from .adapters.base import load_configs
from .evaluate import load_questions, new_eval_dir, run_eval
from .pipeline import DEFAULT_PATIENT, ask as ask_pipeline
from .pipeline import fmt_cost, load_serialized, render_text
from .store import Store, data_dir

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Thalamus CDSS phase 1 test harness")
ROOT = Path(__file__).resolve().parent.parent
PATIENT_OPT = typer.Option(DEFAULT_PATIENT, "--patient", help="Patient export text file")


@app.command()
def ask(question: str = typer.Argument(...), patient: Path = PATIENT_OPT,
        config: str = typer.Option(None, "--config", help="Config id (default: models.yaml default)")):
    """Ask one question about the patient and print the verified answer."""
    cfgs, default = load_configs()
    cfg = cfgs.get(config or default)
    if cfg is None:
        raise typer.BadParameter(f"unknown config {config!r}; choose from {', '.join(cfgs)}")
    r = ask_pipeline(question, cfg, source="cli", patient_path=patient)
    if r.status == "error":
        typer.echo(f"ERROR: {r.error}", err=True)
    typer.echo(render_text(r))
    for f in r.verification.get("failures", []):
        typer.echo(f"  unverified: claim {f['claim_index'] + 1}: {f['problem']}")
    for c in r.format_checks:
        if not c["passed"]:
            typer.echo(f"  format check failed: {c['check']} ({c['detail']})")
    typer.echo(f"\nconfig={r.config_id} model={r.model_returned} run_id={r.run_id}\n"
               f"tokens in={r.input_tokens} (cached {r.cached_input_tokens}) out={r.output_tokens} "
               f"cost={fmt_cost(r.cost_usd)} latency={r.latency_ms} ms retries={r.retries}")
    raise typer.Exit(1 if r.status == "error" else 0)


@app.command("show-record")
def show_record(patient: Path = PATIENT_OPT):
    """Print the serialized record and its hash."""
    s = load_serialized(patient)
    typer.echo(s.text)
    typer.echo(f"record_hash: {s.record_hash}")


@app.command("eval")
def eval_(patient: Path = PATIENT_OPT,
          questions: Path = typer.Option(ROOT / "data" / "questions_2744.yaml", "--questions"),
          configs: str = typer.Option(None, "--configs", help="all | id1,id2 (default: models.yaml default)"),
          repeats: int = typer.Option(1, "--repeats", min=1),
          concurrency: int = typer.Option(4, "--concurrency", min=1, help="Concurrent calls per provider"),
          out: Path = typer.Option(None, "--out", help="Eval directory; pass an existing one to resume")):
    """Run every phrasing of every question against every config."""
    all_cfgs, default = load_configs()
    ids = list(all_cfgs) if configs == "all" else [c.strip() for c in (configs or default).split(",") if c.strip()]
    bad = [i for i in ids if i not in all_cfgs]
    if bad:
        raise typer.BadParameter(f"unknown configs: {', '.join(bad)}")
    out_dir = out or new_eval_dir()
    typer.echo(f"eval dir: {out_dir}")
    run_eval(patient, load_questions(questions), [all_cfgs[i] for i in ids], repeats=repeats,
             concurrency=concurrency, out_dir=out_dir)
    typer.echo(f"wrote {out_dir}/metrics.csv, grading.csv, key.csv, runs.jsonl")


@app.command()
def export(fmt: str = typer.Option("jsonl", "--format", help="jsonl or csv"),
           out: Path = typer.Option(None, "--out", help="Output directory (default $DATA_DIR/export)")):
    """Dump all logged runs."""
    if fmt not in ("jsonl", "csv"):
        raise typer.BadParameter("format must be jsonl or csv")
    for p in Store().export(fmt, out or data_dir() / "export"):
        typer.echo(f"wrote {p}")


if __name__ == "__main__":
    app()
