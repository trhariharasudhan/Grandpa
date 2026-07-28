"""Runtime query routing primitives.

Training, optimization, and experiment frameworks intentionally live outside
the focused local-assistant runtime.
"""

from __future__ import annotations

from grandpa.learning._stubs import (
    QueryAnalyzer,
    RewardFunction,
    RouterPolicy,
    RoutingContext,
)
from grandpa.learning.routing.complexity import (
    ComplexityQueryAnalyzer,
    score_complexity,
)
from grandpa.learning.routing.heuristic_reward import HeuristicRewardFunction
from grandpa.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)


def ensure_registered() -> None:
    """Register the local runtime routing policies."""
    from grandpa.learning.routing.heuristic_policy import (
        ensure_registered as _reg_heuristic,
    )

    _reg_heuristic()

    from grandpa.learning.routing.learned_router import (
        ensure_registered as _reg_learned,
    )

    _reg_learned()


__all__ = [
    "ComplexityQueryAnalyzer",
    "HeuristicRewardFunction",
    "HeuristicRouter",
    "QueryAnalyzer",
    "RewardFunction",
    "RouterPolicy",
    "RoutingContext",
    "build_routing_context",
    "ensure_registered",
    "score_complexity",
]
