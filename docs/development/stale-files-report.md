# Stale Files Report

This report checks tracked files only.

## Extensions Checked

- `*.log`
- `*.tmp`
- `*.bak`
- `*.old`
- `*.orig`

## Result

No tracked files matched those stale-file patterns.

## Nearby Candidates Outside the Requested Patterns

| Path | Reason to Review | Recommendation |
| --- | --- | --- |
| `configs/grandpa/config.backup.toml` | Filename suggests a backup, but extension is `.toml`, not `.bak`. | Review intent before changing. It may be a useful sample or a stale backup. |

No files were deleted or modified as part of this report.
