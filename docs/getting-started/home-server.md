---
title: Home server (Pironman / Raspberry Pi 5)
description: Run Grandpa headless on a Raspberry Pi 5, with the model on the Windows PC
---

# Home server (Pironman / Raspberry Pi 5)

The Pironman case holds a Raspberry Pi 5. It is too small to run the model,
but it is always on, so it is a good home for the parts of Grandpa that should
never sleep:

| Runs on the home server | Stays on the Windows PC |
| --- | --- |
| API, memory, reminders and the scheduler | the model (Ollama) |
| workflows and their triggers | desktop, browser, files, screen |
| phone pairing and notifications | voice, avatar |

`grandpa server --headless` starts only the left column. Every other API
route answers `404` on the node. Each chat goes over your home network to the
PC's model. The PC sends back text only. It runs no tools and no actions for
the node.

## 1. On the PC: allow it once

```powershell
cd D:\Grandpa
uv run python -m grandpa config set server.device_llm true
uv run python -m grandpa serve --host 0.0.0.0
```

`server.device_llm` is off by default. While it is off, the PC refuses the
node's model requests with `403`.

In a second terminal, open a pairing window (a 6-digit code, good for 5
minutes and one use):

```powershell
uv run python -m grandpa devices pair
```

## 2. On the Pi: pair

```bash
grandpa server pair --pc http://192.168.1.20:8000 --code 123456
```

Use your PC's real address (`ipconfig` on the PC shows it). The node gets a
device token, the same kind a phone gets. If the Pi has an encrypted secret
store, the token is saved there (`headless.pc_token`). If not, it is printed
once and you put it in the environment as `GRANDPA_PC_TOKEN`. You can stop the
token at any time on the PC with `grandpa devices revoke <id>`.

## 3. On the Pi: run

```bash
export GRANDPA_PC_URL=http://192.168.1.20:8000
grandpa server status          # PC address, paired, reachable
grandpa server --headless --host 0.0.0.0
```

The API is always authenticated. The API key is created on first start, or you
can set `GRANDPA_API_KEY`. If the PC is asleep, the node keeps running:
`/health` answers `{"status": "ok", "pc": false}` and chat answers `503` until
the PC is back.

## Docker (arm64)

```bash
docker build -f docker/headless.Dockerfile -t grandpa-headless .
echo "GRANDPA_PC_TOKEN=gp_dev_..." > grandpa.env    # from step 2
docker run -d --name grandpa --restart unless-stopped -p 8000:8000 \
  -v grandpa-data:/data -e GRANDPA_PC_URL=http://192.168.1.20:8000 \
  --env-file grandpa.env grandpa-headless
```

Memory, reminders and workflows live in the `grandpa-data` volume
(`GRANDPA_HOME=/data`). The image has no secrets in it. CI builds it for
`linux/arm64` and starts it once on every change to the server.

## Security notes

* The device token only opens the `/v1/devices/...` routes (D1). The model
  route `/v1/devices/llm` is text only and needs `server.device_llm = true`.
* On your home network the traffic is plain HTTP, the same as for the phone.
  Do not expose port 8000 to the internet.
* Workflows on the node keep their confirmations. Steps that need the
  Windows desktop cannot work on the Pi and report a failure.
