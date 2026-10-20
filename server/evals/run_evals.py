"""Manual comparison of the AI agent and the rule-based planner on fixed trips, with real services.

This spends money (about 10 cents per scenario: two Places searches and a few thousand model tokens) and needs
ANTHROPIC_API_KEY, GOOGLE_MAPS_API_KEY and ORS_API_KEY in server/.env or the environment. It only runs with --yes and
stops at --max-usd (default 0.30). The report is printed and saved as .md and .json in server/evals/results
(or --out, or EVAL_RESULTS_DIR). The same comparison can run on the deployed server; see the README.

    cd server
    .venv\\Scripts\\python.exe evals\\run_evals.py --yes
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import comparison
import reportstore
from comparison import SCENARIOS, Scenario, check  # noqa: F401  (also used by the tests)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm that real, paid API calls are intended")
    parser.add_argument("--only", help="run only scenarios whose name contains this text")
    parser.add_argument("--max-usd", type=float, default=comparison.DEFAULT_MAX_USD, help="spending cap, an estimate")
    parser.add_argument("--out", help="directory for the saved report")
    args = parser.parse_args()
    if not args.yes:
        sys.exit("This calls paid APIs. Re-run with --yes to continue.")

    report = comparison.run_comparison(only=args.only, max_usd=args.max_usd, progress=print)
    markdown = comparison.render_markdown(report)
    print()
    print(markdown)

    store = reportstore.FileReportStore(args.out)
    name = datetime.now(timezone.utc).strftime("eval-%Y%m%d-%H%M%S")
    for suffix, text in ((".md", markdown), (".json", json.dumps(report, indent=2, ensure_ascii=False))):
        print("Saved", store.save(name + suffix, text))

    failed = any(
        "error" in r or (r["agent"]["source"] == "agent" and r["agent"]["problems"]) for r in report["results"]
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
