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
    args = parser.parse_args()

    # Imports live inside each branch so a command only loads what it needs.
    if args.command == "fetch-commodities":
        from quote_desk.generate.fetch_commodities import fetch

        fetch()
        return

    from quote_desk import config

    seed = config.SEED if args.seed is None else args.seed
    if args.command == "generate":
        from quote_desk.generate.synth_erp import generate

        generate(seed=seed, n_jobs=args.jobs)
    elif args.command == "check-generator":
        from quote_desk.generate.learnability import check

        check(seed=seed, n_jobs=args.jobs)
