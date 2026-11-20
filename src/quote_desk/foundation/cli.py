"""Foundation commands: profile, draft a contract, and clean any source.

New data goes through three steps, the way a real customer's data would:
  1. `quote-desk profile --source PATH`         look at it (profile.md)
  2. `quote-desk draft-contract --source PATH`  guess a contract to review
  3. `quote-desk clean --source PATH [--contract FILE]`  clean and report
Step 3 alone also works: without --contract it drafts one automatically.
"""

import re
from pathlib import Path

from quote_desk import config
from quote_desk.foundation.draft_contract import draft_contract, load_contract_file
from quote_desk.foundation.load import load_csv_folder, load_source, load_sqlite
from quote_desk.foundation.profile import profile
from quote_desk.foundation.quality_report import build_foundation, render_profile


def source_name(source: Path) -> str:
    """A safe short name for a source: its folder or file name without extension."""
    return re.sub(r"\W+", "_", Path(source).stem).strip("_") or "source"


def output_dir(source: Path, out: str | None) -> Path:
    """Where outputs go: --out if given, else data/generated/<source name>/."""
    return Path(out) if out else config.DATA_DIR / source_name(source)


def profile_command(source: str, out: str | None) -> Path:
    """Profile a source, print the overview, and write profile.md."""
    raw = load_source(source)
    raw_profile = profile(raw)
    folder = output_dir(Path(source), out)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "profile.md"
    path.write_text(render_profile(source_name(Path(source)), raw_profile), encoding="utf-8")
    print(raw_profile["summary"].to_string(index=False))
    print()
    print(raw_profile["relationships"].to_string(index=False))
    print(f"\nWrote {path}")
    return path


def draft_command(source: str, out: str | None) -> Path:
    """Write a draft contract guessed from the data."""
    raw = load_source(source)
    path = Path(out) if out else output_dir(Path(source), None) / "contract_draft.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft_contract(raw, source_name(Path(source))), encoding="utf-8")
    print(f"Wrote {path}")
    print("Review it (every guess and TODO), then run:")
    print(f"  uv run quote-desk clean --source {source} --contract {path}")
    return path


def clean_command(
    source: str | None, contract: str | None, out: str | None, demo: bool = False
) -> Path:
    """Clean a source and write foundation.sqlite + quality_report.md.

    Without --source, cleans the Lakeshore ERP (or the field-service sample
    with --demo). Without --contract, drafts one first and says so.
    """
    if demo:
        from quote_desk.foundation.contracts.field_service_demo import CONTRACT

        raw, contract_obj = (
            load_csv_folder(config.ROOT / "data" / "samples" / "field_service"),
            CONTRACT,
        )
        folder = Path(out) if out else config.DATA_DIR / "demo"
    elif source is None:
        from quote_desk.foundation.contracts.lakeshore_erp import CONTRACT

        raw, contract_obj = load_sqlite(config.ERP_DB), CONTRACT
        folder = Path(out) if out else config.DATA_DIR
    else:
        raw = load_source(source)
        folder = output_dir(Path(source), out)
        if contract:
            contract_obj = load_contract_file(contract)
        else:
            draft_path = folder / "contract_draft.py"
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(draft_contract(raw, source_name(Path(source))), encoding="utf-8")
            contract_obj = load_contract_file(draft_path)
            print(f"No --contract given: used an automatic draft, saved to {draft_path}")
            print("It only knows keys, types and links guessed from the data. Review it, add")
            print("business rules (datasets, filters, identity, units), and rerun with --contract.")

    db = folder / ("foundation.sqlite" if folder != config.DATA_DIR else config.FOUNDATION_DB.name)
    report = folder / "quality_report.md"
    result = build_foundation(raw, contract_obj, db, report)
    print(f"Wrote {db}")
    print(f"Wrote {report}")
    print(f"Review queue: {len(result.review_queue)} cases")
    return report
