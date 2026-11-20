import argparse


def main() -> None:
    """Command-line entry point: `uv run quote-desk <command>`."""
    parser = argparse.ArgumentParser(prog="quote-desk")
    commands = parser.add_subparsers(dest="command", required=True)

    # Generate
    commands.add_parser("fetch-commodities", help="download real metal prices (one-time)")
    gen = commands.add_parser("generate", help="build data/generated/erp.sqlite")
    chk = commands.add_parser("check-generator", help="eval: how learnable is the cost data")
    for sub in (gen, chk):
        sub.add_argument(
            "--seed", type=int, default=None, help="random seed (default: config.SEED)"
        )
        sub.add_argument("--jobs", type=int, default=3000, help="number of historical quotes")

    # Foundation
    source_help = "folder of CSVs, a .csv file, or a SQLite file"
    prof = commands.add_parser("profile", help="profile any data source (no contract needed)")
    prof.add_argument("--source", required=True, help=source_help)
    prof.add_argument("--out", help="output folder (default: data/generated/<source name>)")
    draft = commands.add_parser("draft-contract", help="guess a contract from the data")
    draft.add_argument("--source", required=True, help=source_help)
    draft.add_argument("--out", help="output .py file")
    cln = commands.add_parser(
        "clean", help="Foundation: clean and report (default: the Lakeshore ERP)"
    )
    cln.add_argument("--source", help=source_help + " (default: the Lakeshore ERP)")
    cln.add_argument("--contract", help="reviewed contract .py file (it is run as Python)")
    cln.add_argument("--out", help="output folder")
    cln.add_argument("--demo", action="store_true", help="clean the field-service sample")
    args = parser.parse_args()

    # Imports live inside each branch so a command only loads what it needs.
    if args.command == "fetch-commodities":
        from quote_desk.generate.fetch_commodities import fetch

        fetch()
    elif args.command in ("generate", "check-generator"):
        from quote_desk import config

        seed = config.SEED if args.seed is None else args.seed
        if args.command == "generate":
            from quote_desk.generate.synth_erp import generate

            generate(seed=seed, n_jobs=args.jobs)
        else:
            from quote_desk.generate.learnability import check

            check(seed=seed, n_jobs=args.jobs)
    elif args.command == "profile":
        from quote_desk.foundation.cli import profile_command

        profile_command(args.source, args.out)
    elif args.command == "draft-contract":
        from quote_desk.foundation.cli import draft_command

        draft_command(args.source, args.out)
    elif args.command == "clean":
        from quote_desk.foundation.cli import clean_command

        clean_command(args.source, args.contract, args.out, args.demo)
