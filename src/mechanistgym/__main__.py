"""Run the MechanistGym M0 analytic fixture."""

from __future__ import annotations

import json

from .demo import run_decay_demo


def main() -> None:
    """Print a complete verified episode as a structured trace."""

    print(json.dumps(run_decay_demo(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
