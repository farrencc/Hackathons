"""Launch a full ensemble run - the one to quote, not the smoke test.

    python scripts/run_ensemble.py --n 1000 --workers 4
    python scripts/run_ensemble.py --n 2000 --workers 8 --seed 7

The default in-session ensemble is 50 scenarios, which is enough to run the
pipeline end to end and nothing more.  This is the 500-2,000 scenario run.
At about 8 s per scenario per core, 1,000 scenarios on four cores is roughly
35 minutes.  Output goes to ``data/ensemble/<vintage>_seed<seed>_n<n>/`` one
parquet part per scenario, so it can be stopped and resumed with the same
arguments, and a partial run is still a usable ensemble.  Then:

    python compare.py --ensemble data/ensemble/2024_seed42_n1000
    python validate.py --ensemble data/ensemble/2024_seed42_n1000
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import ensemble  # noqa: E402
import frequency  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=ensemble.SEED)
    parser.add_argument("--vintage", default=ensemble.DEFAULT_VINTAGE,
                        choices=ensemble.VINTAGES)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    directory = ensemble.run(args.n, args.seed, args.vintage, args.out,
                             args.workers)
    frequency.run(directory)
    print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
