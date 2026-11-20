import argparse


def main() -> None:
    """Command-line entry point: `uv run quote-desk <command>`."""
    parser = argparse.ArgumentParser(prog="quote-desk")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch-commodities", help="download real metal prices (one-time)")
    gen = commands.add_parser("generate", help="build data/generated/erp.sqlite")
    chk = commands.add_parser("check-generator", help="eval: how learnable is the cost data")
    for sub in (gen, chk):
        sub.add_argument(
            "--seed", type=int, default=None, help="random seed (default: config.SEED)"
        )
        sub.add_argument("--jobs", type=int, default=3000, help="number of historical quotes")
    cln = commands.add_parser("clean", help="Foundation: profile, clean and report on the ERP")
    cln.add_argument(
        "--demo", action="store_true", help="clean the unrelated field-service sample instead"
    )
    args = parser.parse_args()

    # Imports live inside each branch so a command only loads what it needs.
    if args.command == "fetch-commodities":
        from quote_desk.generate.fetch_commodities import fetch

        fetch()
        return

    from quote_desk import config

    if args.command == "generate":
        from quote_desk.generate.synth_erp import generate

        generate(seed=config.SEED if args.seed is None else args.seed, n_jobs=args.jobs)
    elif args.command == "check-generator":
        from quote_desk.generate.learnability import check

        check(seed=config.SEED if args.seed is None else args.seed, n_jobs=args.jobs)
    elif args.command == "clean":
        from quote_desk.foundation.load import load_csv_folder, load_sqlite
        from quote_desk.foundation.quality_report import build_foundation

        if args.demo:
            from quote_desk.foundation.contracts.field_service_demo import CONTRACT

            raw = load_csv_folder(config.ROOT / "data" / "samples" / "field_service")
            db, report = (
                config.DATA_DIR / "demo" / "foundation.sqlite",
                config.DATA_DIR / "demo" / "quality_report.md",
            )
        else:
            from quote_desk.foundation.contracts.lakeshore_erp import CONTRACT

            raw = load_sqlite(config.ERP_DB)
            db, report = config.FOUNDATION_DB, config.QUALITY_REPORT
        result = build_foundation(raw, CONTRACT, db, report)
        print(f"Wrote {db}")
        print(f"Wrote {report}")
        print(f"Review queue: {len(result.review_queue)} cases")
