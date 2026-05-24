"""Learning primitive -- router policies, reward functions, learning."""

from __future__ import annotations

from grandpa.learning._stubs import (
    QueryAnalyzer,
    RewardFunction,
    RouterPolicy,
    RoutingContext,
)
from grandpa.learning.agents.agent_evolver import AgentConfigEvolver
from grandpa.learning.learning_orchestrator import LearningOrchestrator
from grandpa.learning.optimize.llm_optimizer import LLMOptimizer
from grandpa.learning.optimize.optimizer import OptimizationEngine
from grandpa.learning.optimize.store import OptimizationStore
from grandpa.learning.routing.complexity import (
    ComplexityQueryAnalyzer,
    score_complexity,
)
from grandpa.learning.routing.heuristic_reward import HeuristicRewardFunction
from grandpa.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)
from grandpa.learning.training.data import TrainingDataMiner
from grandpa.learning.training.lora import HAS_TORCH, LoRATrainer, LoRATrainingConfig


def ensure_registered() -> None:
    """Ensure all learning policies are registered in RouterPolicyRegistry."""
    from grandpa.learning.routing.heuristic_policy import (
        ensure_registered as _reg_heuristic,
    )

    _reg_heuristic()

    from grandpa.learning.routing.learned_router import (
        ensure_registered as _reg_learned,
    )

    _reg_learned()

    # Intelligence training (optional deps)
    try:
        import grandpa.learning.intelligence  # noqa: F401
    except ImportError:
        pass

    # Orchestrator-specific training (optional deps)
    try:
        import grandpa.learning.intelligence.orchestrator  # noqa: F401
    except ImportError:
        pass

    # Agent optimizers (optional deps)
    try:
        import grandpa.learning.agents.dspy_optimizer  # noqa: F401
    except ImportError:
        pass
    try:
        import grandpa.learning.agents.gepa_optimizer  # noqa: F401
    except ImportError:
        pass
    try:
        import grandpa.learning.agents.ace_optimizer  # noqa: F401
    except ImportError:
        pass


__all__ = [
    "AgentConfigEvolver",
    "ComplexityQueryAnalyzer",
    "HAS_TORCH",
    "HeuristicRewardFunction",
    "HeuristicRouter",
    "LLMOptimizer",
    "LearningOrchestrator",
    "LoRATrainer",
    "LoRATrainingConfig",
    "OptimizationEngine",
    "OptimizationStore",
    "QueryAnalyzer",
    "RewardFunction",
    "RouterPolicy",
    "RoutingContext",
    "TrainingDataMiner",
    "build_routing_context",
    "ensure_registered",
    "score_complexity",
]
