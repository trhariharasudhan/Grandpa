//! MemoryBackend trait for all storage backends.

use grandpa_core::{GrandpaError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, GrandpaError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, GrandpaError>;
    fn delete(&self, doc_id: &str) -> Result<bool, GrandpaError>;
    fn clear(&self) -> Result<(), GrandpaError>;
    fn count(&self) -> Result<usize, GrandpaError>;
}
