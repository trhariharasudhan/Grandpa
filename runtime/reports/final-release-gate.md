# Grandpa Final Release Gate

- Status: **READY**
- Started: `2026-06-06T16:37:08.408145+00:00`
- Finished: `2026-06-06T16:42:03.716618+00:00`
- Recommendation: Ready after reviewing and committing intentional working-tree changes.

## Summary

- Passed: 9
- Warnings: 4
- Blockers: 0
- Optional skipped: 1

## Validation Matrix

| Check | Status | Required | Summary |
| --- | --- | --- | --- |
| git status summary | warn | False | Working tree has 91 changed/untracked item(s). Commit before pushing a release. |
| ignored/generated artifact check | pass | True | No tracked generated artifacts found. |
| dependency sanity | pass | True | Resolved 409 packages in 11ms<br>Uninstalled 18 packages in 543ms<br> - cfgv==3.5.0<br> - coverage==7.13.4<br> - distlib==0.4.0<br> - identify==2.6.18<br> - iniconfig==2.3.0<br> - nodeenv==1.10.0<br> - platformdirs==4.9.2<br> - pluggy==1.6.0<br> - polars==1.40.1<br> - polars-runtime-32==1.40.1<br> - pre-commit==4.5.1<br> - pytest==9.0.2<br> - pytest-asyncio==1.3.0<br> - pytest-cov==7.0.0<br> - python-discovery==1.2.0<br> - respx==0.22.0<br> - ruff==0.15.1<br> - virtualenv==21.2.0 |
| doctor dashboard | pass | True | ...──────────┤<br>│ System Integration │  ✓  │ Docker command          │ Ready                  │<br>│                    │     │ available               │   C:\Program           │<br>│                    │     │                         │ Files\Docker\Docker\r… │<br>│                    │  !  │ Docker daemon reachable │ Missing/optional       │<br>│                    │     │                         │   Install Docker       │<br>│                    │     │                         │ Desktop and wait until │<br>│                    │     │                         │ the engine is running. │<br>│                    │  ✓  │ Notifications           │ Ready                  │<br>│                    │     │                         │   Routine and reminder │<br>│                    │     │                         │ notifications can be   │<br>│                    │     │                         │ stored locally.        │<br>│                    │  ✓  │ Background scheduler    │ Ready                  │<br>│                    │     │                         │   Backend startup can  │<br>│                    │     │                         │ register the routine   │<br>│                    │     │                         │ scheduler daemon.      │<br>│                    │  ✓  │ Frontend readiness      │ Ready                  │<br>│                    │     │                         │   D:\Grandpa\src\gran… │<br>│                    │  ✓  │ Final release gate      │ Running now            │<br>│                    │     │                         │   The active final     │<br>│                    │     │                         │ release gate is        │<br>│                    │     │                         │ executing doctor as    │<br>│                    │     │                         │ one of its checks.     │<br>│                    │  !  │ Rust extension          │ Missing/optional       │<br>│                    │     │ background task         │   Rust extension is    │<br>│                    │     │                         │ building in the        │<br>│                    │     │                         │ background.            │<br>│                    │  ✓  │ Background model        │ Ready                  │<br>│                    │     │ downloads               │   No model downloads   │<br>│                    │     │                         │ are currently tracked. │<br>└────────────────────┴─────┴─────────────────────────┴────────────────────────┘<br><br>Final Summary<br>  34 passed, 15 warnings, 0 failures<br>  Overall readiness: PARTIALLY READY |
| daily-use validator | pass | True | RUN doctor dashboard: uv run grandpa doctor<br>PASS doctor dashboard: ok<br>RUN normal AI question: uv run grandpa ask --engine ollama --model qwen2.5:3b What is Python?<br>PASS normal AI question: ok<br>RUN memory remember: uv run grandpa ask remember my project is Grandpa<br>PASS memory remember: ok<br>RUN memory recall: uv run grandpa ask what is my project?<br>PASS memory recall: ok<br>RUN file assistant: uv run grandpa ask show recent files<br>PASS file assistant: ok<br>RUN capability foundations: uv run python -c from grandpa import communication_integration, future_features, iot_smart_home, mobile_integration, real_world_tasks; checks=[mobile_integration.diagnostics()['status'], communication_integration.diagnostics()['status'], real_world_tasks.diagnostics()['status'], iot_smart_home.diagnostics()['status'], future_features.diagnostics()['status']]; assert all(item == 'ready' for item in checks), checks; print('capabilities ok')<br>PASS capability foundations: ok<br>RUN routine reminder: uv run grandpa ask remind me every hour to drink water<br>PASS routine reminder: ok<br>RUN blocked dangerous command: uv run grandpa ask delete all files<br>PASS blocked dangerous command: ok<br>RUN safe app command parser: uv run python -c from grandpa.local_actions import handle_local_action; result = handle_local_action('open notepad', execute=False); print(result.status)<br>PASS safe app command parser: ok<br>RUN frontend build: C:\Program Files\nodejs\npm.cmd run build<br>PASS frontend build: ok<br><br>Daily-use validation: 10 passed, 0 warnings, 0 failures |
| release-grade pytest | pass | True | Test suite report: pass<br>JSON: D:\Grandpa\runtime\reports\test-suite-release-report.json<br>Markdown: D:\Grandpa\runtime\reports\test-suite-release-report.md |
| frontend build | pass | True | ...[1m[2m 13.68 kB[22m[1m[22m[2m │ gzip:   3.88 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/GetStartedPage-BlWa2aL5.js                [39m[1m[2m 14.17 kB[22m[1m[22m[2m │ gzip:   3.70 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/SafetyPage-Dj0PvGWW.js                    [39m[1m[2m 16.50 kB[22m[1m[22m[2m │ gzip:   4.26 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/DashboardPage-DClclAOj.js                 [39m[1m[2m 18.61 kB[22m[1m[22m[2m │ gzip:   5.09 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/SettingsPage-BXb-mMzV.js                  [39m[1m[2m 23.16 kB[22m[1m[22m[2m │ gzip:   5.69 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/router-DS8tesSE.js                        [39m[1m[2m 44.59 kB[22m[1m[22m[2m │ gzip:  16.01 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/AgentsPage-DtSGA2ll.js                    [39m[1m[2m 96.82 kB[22m[1m[22m[2m │ gzip:  22.74 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/DataSourcesPage-DHb5Ny5x.js               [39m[1m[2m167.91 kB[22m[1m[22m[2m │ gzip:  51.71 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/markdown-8lJBaJcI.js                      [39m[1m[2m335.57 kB[22m[1m[22m[2m │ gzip: 101.91 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/charts-BFGfIsz7.js                        [39m[1m[2m358.80 kB[22m[1m[22m[2m │ gzip: 107.19 kB[22m<br>[2m../src/grandpa/server/static/[22m[36massets/index-CvnNqX-3.js                         [39m[1m[33m859.09 kB[39m[22m[2m │ gzip: 258.09 kB[22m<br>[32m✓ built in 22.53s[39m<br><br>PWA v1.2.0<br>mode      generateSW<br>precache  42 entries (2109.70 KiB)<br>files generated<br>  ../src/grandpa/server/static/sw.js<br>  ../src/grandpa/server/static/workbox-8c29f6e4.js<br>[33mGenerated an empty chunk: "react".[39m<br>[33m[plugin vite:reporter] <br>(!) D:/Grandpa/frontend/src/lib/analytics.ts is dynamically imported by D:/Grandpa/frontend/src/lib/store.ts but also statically imported by D:/Grandpa/frontend/src/App.tsx, D:/Grandpa/frontend/src/main.tsx, dynamic import will not move module into another chunk.<br>[39m<br>[33m<br>(!) Some chunks are larger than 500 kB after minification. Consider:<br>- Using dynamic import() to code-split the application<br>- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks<br>- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.[39m |
| tauri frontend build | pass | True | ...                  [39m[1m[2m 10.93 kB[22m[1m[22m[2m │ gzip:   2.69 kB[22m<br>[2mdist/[22m[36massets/CapabilitiesPage-CP_dee21.js              [39m[1m[2m 11.07 kB[22m[1m[22m[2m │ gzip:   3.59 kB[22m<br>[2mdist/[22m[36massets/connectors-CzBred3u.js                    [39m[1m[2m 13.68 kB[22m[1m[22m[2m │ gzip:   3.88 kB[22m<br>[2mdist/[22m[36massets/GetStartedPage-BlWa2aL5.js                [39m[1m[2m 14.17 kB[22m[1m[22m[2m │ gzip:   3.70 kB[22m<br>[2mdist/[22m[36massets/SafetyPage-Dj0PvGWW.js                    [39m[1m[2m 16.50 kB[22m[1m[22m[2m │ gzip:   4.26 kB[22m<br>[2mdist/[22m[36massets/DashboardPage-DClclAOj.js                 [39m[1m[2m 18.61 kB[22m[1m[22m[2m │ gzip:   5.09 kB[22m<br>[2mdist/[22m[36massets/SettingsPage-BXb-mMzV.js                  [39m[1m[2m 23.16 kB[22m[1m[22m[2m │ gzip:   5.69 kB[22m<br>[2mdist/[22m[36massets/router-DS8tesSE.js                        [39m[1m[2m 44.59 kB[22m[1m[22m[2m │ gzip:  16.01 kB[22m<br>[2mdist/[22m[36massets/AgentsPage-DtSGA2ll.js                    [39m[1m[2m 96.82 kB[22m[1m[22m[2m │ gzip:  22.74 kB[22m<br>[2mdist/[22m[36massets/DataSourcesPage-DHb5Ny5x.js               [39m[1m[2m167.91 kB[22m[1m[22m[2m │ gzip:  51.71 kB[22m<br>[2mdist/[22m[36massets/markdown-8lJBaJcI.js                      [39m[1m[2m335.57 kB[22m[1m[22m[2m │ gzip: 101.91 kB[22m<br>[2mdist/[22m[36massets/charts-BFGfIsz7.js                        [39m[1m[2m358.80 kB[22m[1m[22m[2m │ gzip: 107.19 kB[22m<br>[2mdist/[22m[36massets/index-CvnNqX-3.js                         [39m[1m[33m859.09 kB[39m[22m[2m │ gzip: 258.09 kB[22m<br>[32m✓ built in 20.02s[39m<br><br>PWA v1.2.0<br>mode      generateSW<br>precache  42 entries (2109.70 KiB)<br>files generated<br>  dist/sw.js<br>  dist/workbox-8c29f6e4.js<br>[33mGenerated an empty chunk: "react".[39m<br>[33m[plugin vite:reporter] <br>(!) D:/Grandpa/frontend/src/lib/analytics.ts is dynamically imported by D:/Grandpa/frontend/src/lib/store.ts but also statically imported by D:/Grandpa/frontend/src/App.tsx, D:/Grandpa/frontend/src/main.tsx, dynamic import will not move module into another chunk.<br>[39m<br>[33m<br>(!) Some chunks are larger than 500 kB after minification. Consider:<br>- Using dynamic import() to code-split the application<br>- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks<br>- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.[39m |
| release manifest sanity | pass | False | Valid manifest: D:\Grandpa\dist\releases\grandpa-v1.0.1\release-manifest.json |
| full pytest suite status | pass | False | Latest full-suite report status: pass; suites recorded: 1. |
| android apk build | skipped | False | Skipped by gate option. |

## Warnings

- **git status summary**: Working tree has 91 changed/untracked item(s). Commit before pushing a release.
- **doctor dashboard**: ...──────────┤
│ System Integration │  ✓  │ Docker command          │ Ready                  │
│                    │     │ available               │   C:\Program           │
│                    │     │                         │ Files\Docker\Docker\r… │
│                    │  !  │ Docker daemon reachable │ Missing/optional       │
│                    │     │                         │   Install Docker       │
│                    │     │                         │ Desktop and wait until │
│                    │     │                         │ the engine is running. │
│                    │  ✓  │ Notifications           │ Ready                  │
│                    │     │                         │   Routine and reminder │
│                    │     │                         │ notifications can be   │
│                    │     │                         │ stored locally.        │
│                    │  ✓  │ Background scheduler    │ Ready                  │
│                    │     │                         │   Backend startup can  │
│                    │     │                         │ register the routine   │
│                    │     │                         │ scheduler daemon.      │
│                    │  ✓  │ Frontend readiness      │ Ready                  │
│                    │     │                         │   D:\Grandpa\src\gran… │
│                    │  ✓  │ Final release gate      │ Running now            │
│                    │     │                         │   The active final     │
│                    │     │                         │ release gate is        │
│                    │     │                         │ executing doctor as    │
│                    │     │                         │ one of its checks.     │
│                    │  !  │ Rust extension          │ Missing/optional       │
│                    │     │ background task         │   Rust extension is    │
│                    │     │                         │ building in the        │
│                    │     │                         │ background.            │
│                    │  ✓  │ Background model        │ Ready                  │
│                    │     │ downloads               │   No model downloads   │
│                    │     │                         │ are currently tracked. │
└────────────────────┴─────┴─────────────────────────┴────────────────────────┘

Final Summary
  34 passed, 15 warnings, 0 failures
  Overall readiness: PARTIALLY READY (Docker daemon off is optional unless you are publishing container images.)
- **frontend build**: ...[1m[2m 13.68 kB[22m[1m[22m[2m │ gzip:   3.88 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/GetStartedPage-BlWa2aL5.js                [39m[1m[2m 14.17 kB[22m[1m[22m[2m │ gzip:   3.70 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/SafetyPage-Dj0PvGWW.js                    [39m[1m[2m 16.50 kB[22m[1m[22m[2m │ gzip:   4.26 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/DashboardPage-DClclAOj.js                 [39m[1m[2m 18.61 kB[22m[1m[22m[2m │ gzip:   5.09 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/SettingsPage-BXb-mMzV.js                  [39m[1m[2m 23.16 kB[22m[1m[22m[2m │ gzip:   5.69 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/router-DS8tesSE.js                        [39m[1m[2m 44.59 kB[22m[1m[22m[2m │ gzip:  16.01 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/AgentsPage-DtSGA2ll.js                    [39m[1m[2m 96.82 kB[22m[1m[22m[2m │ gzip:  22.74 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/DataSourcesPage-DHb5Ny5x.js               [39m[1m[2m167.91 kB[22m[1m[22m[2m │ gzip:  51.71 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/markdown-8lJBaJcI.js                      [39m[1m[2m335.57 kB[22m[1m[22m[2m │ gzip: 101.91 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/charts-BFGfIsz7.js                        [39m[1m[2m358.80 kB[22m[1m[22m[2m │ gzip: 107.19 kB[22m
[2m../src/grandpa/server/static/[22m[36massets/index-CvnNqX-3.js                         [39m[1m[33m859.09 kB[39m[22m[2m │ gzip: 258.09 kB[22m
[32m✓ built in 22.53s[39m

PWA v1.2.0
mode      generateSW
precache  42 entries (2109.70 KiB)
files generated
  ../src/grandpa/server/static/sw.js
  ../src/grandpa/server/static/workbox-8c29f6e4.js
[33mGenerated an empty chunk: "react".[39m
[33m[plugin vite:reporter] 
(!) D:/Grandpa/frontend/src/lib/analytics.ts is dynamically imported by D:/Grandpa/frontend/src/lib/store.ts but also statically imported by D:/Grandpa/frontend/src/App.tsx, D:/Grandpa/frontend/src/main.tsx, dynamic import will not move module into another chunk.
[39m
[33m
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.[39m (Vite chunk warnings are size/performance guidance, not release blockers.)
- **tauri frontend build**: ...                  [39m[1m[2m 10.93 kB[22m[1m[22m[2m │ gzip:   2.69 kB[22m
[2mdist/[22m[36massets/CapabilitiesPage-CP_dee21.js              [39m[1m[2m 11.07 kB[22m[1m[22m[2m │ gzip:   3.59 kB[22m
[2mdist/[22m[36massets/connectors-CzBred3u.js                    [39m[1m[2m 13.68 kB[22m[1m[22m[2m │ gzip:   3.88 kB[22m
[2mdist/[22m[36massets/GetStartedPage-BlWa2aL5.js                [39m[1m[2m 14.17 kB[22m[1m[22m[2m │ gzip:   3.70 kB[22m
[2mdist/[22m[36massets/SafetyPage-Dj0PvGWW.js                    [39m[1m[2m 16.50 kB[22m[1m[22m[2m │ gzip:   4.26 kB[22m
[2mdist/[22m[36massets/DashboardPage-DClclAOj.js                 [39m[1m[2m 18.61 kB[22m[1m[22m[2m │ gzip:   5.09 kB[22m
[2mdist/[22m[36massets/SettingsPage-BXb-mMzV.js                  [39m[1m[2m 23.16 kB[22m[1m[22m[2m │ gzip:   5.69 kB[22m
[2mdist/[22m[36massets/router-DS8tesSE.js                        [39m[1m[2m 44.59 kB[22m[1m[22m[2m │ gzip:  16.01 kB[22m
[2mdist/[22m[36massets/AgentsPage-DtSGA2ll.js                    [39m[1m[2m 96.82 kB[22m[1m[22m[2m │ gzip:  22.74 kB[22m
[2mdist/[22m[36massets/DataSourcesPage-DHb5Ny5x.js               [39m[1m[2m167.91 kB[22m[1m[22m[2m │ gzip:  51.71 kB[22m
[2mdist/[22m[36massets/markdown-8lJBaJcI.js                      [39m[1m[2m335.57 kB[22m[1m[22m[2m │ gzip: 101.91 kB[22m
[2mdist/[22m[36massets/charts-BFGfIsz7.js                        [39m[1m[2m358.80 kB[22m[1m[22m[2m │ gzip: 107.19 kB[22m
[2mdist/[22m[36massets/index-CvnNqX-3.js                         [39m[1m[33m859.09 kB[39m[22m[2m │ gzip: 258.09 kB[22m
[32m✓ built in 20.02s[39m

PWA v1.2.0
mode      generateSW
precache  42 entries (2109.70 KiB)
files generated
  dist/sw.js
  dist/workbox-8c29f6e4.js
[33mGenerated an empty chunk: "react".[39m
[33m[plugin vite:reporter] 
(!) D:/Grandpa/frontend/src/lib/analytics.ts is dynamically imported by D:/Grandpa/frontend/src/lib/store.ts but also statically imported by D:/Grandpa/frontend/src/App.tsx, D:/Grandpa/frontend/src/main.tsx, dynamic import will not move module into another chunk.
[39m
[33m
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.[39m (Vite chunk warnings are size/performance guidance, not release blockers.)
