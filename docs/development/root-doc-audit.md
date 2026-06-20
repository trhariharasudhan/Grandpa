# Root Documentation Audit

This audit covers tracked Markdown files at the repository root.

| Filename | Purpose | Recommendation | Risk |
| --- | --- | --- | --- |
| `README.md` | Primary repository landing page, quick start, and documentation entry point. | Keep at root. | Low |
| `CHANGELOG.md` | Release history and user-facing change summary. | Keep at root unless release docs become fully centralized. | Low |
| `CODE_OF_CONDUCT.md` | Community conduct policy. | Keep at root. | Low |
| `CONTRIBUTING.md` | Contributor onboarding and contribution policy. | Keep at root. | Low |
| `MODEL_NAMES.md` | Redirect stub to `docs/development/model-names.md`. | Keep temporarily as a compatibility stub; archive later if no external links depend on it. | Low |
| `REVIEW.md` | Redirect stub to `docs/development/pr-review-guidelines.md`. | Keep temporarily as a compatibility stub; archive later if old design references are updated. | Medium |
| `LICENSE` | Project license. | Keep at root. | Low |
| `SECURITY.md` | Security policy. | Not found. Consider adding one in a later security documentation task. | Low |

## Archive Candidates

- `MODEL_NAMES.md`: root stub can be removed later after external references are considered.
- `REVIEW.md`: root stub can be removed later after historical design docs and contributor guidance are updated.

## Notes

Root files should stay limited to common repository entry points: README,
license, contribution policy, code of conduct, security policy, changelog, and
short compatibility stubs.
