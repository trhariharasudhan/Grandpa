//! OjAgent trait — interface for all agent implementations.

use grandpa_core::{AgentContext, AgentResult, GrandpaError};

/// Core agent trait for all Grandpa agents.
///
/// Renamed from `Agent` to `OjAgent` to avoid collision with `rig::agent::Agent`.
/// Async to support rig-core's async model.
// Same macro-generated `#[must_use]` as grandpa-engine's InferenceEngine, for
// `async fn run`; see the longer note there. This crate depends on
// grandpa-engine, so it never got as far as being compiled while that one was
// failing -- this lint was queued behind it, not absent.
#[allow(clippy::double_must_use)]
#[async_trait::async_trait]
pub trait OjAgent: Send + Sync {
    fn agent_id(&self) -> &str;
    fn accepts_tools(&self) -> bool {
        false
    }
    async fn run(
        &self,
        input: &str,
        context: Option<&AgentContext>,
    ) -> Result<AgentResult, GrandpaError>;
}
