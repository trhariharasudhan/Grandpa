# systemd Service (Linux)

grandpa includes a systemd unit file for running the API server as a managed background service on Linux. This provides automatic startup on boot, crash recovery, and integration with standard Linux service management tools.

## Prerequisites

Before installing the service, ensure that:

1. grandpa is installed in a virtual environment at `/opt/grandpa/.venv` (or adjust paths accordingly).
2. A dedicated `grandpa` system user exists (recommended for security).
3. An inference engine (such as Ollama) is running and accessible.

Create the user and installation directory:

```bash
sudo useradd --system --create-home --home-dir /opt/grandpa grandpa
sudo -u grandpa python3 -m venv /opt/grandpa/.venv
sudo -u grandpa git clone https://github.com/grandpa/grandpa.git /opt/grandpa/grandpa
cd /opt/grandpa/grandpa && sudo -u grandpa uv sync --extra server
```

## Installing the Service

Copy the unit file to the systemd directory, reload the daemon, and enable the service:

```bash
sudo cp deploy/systemd/grandpa.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable grandpa
sudo systemctl start grandpa
```

Verify it is running:

```bash
sudo systemctl status grandpa
```

## Service File Reference

The provided unit file at `deploy/systemd/grandpa.service`:

```ini
[Unit]
Description=grandpa API Server
After=network.target

[Service]
Type=simple
User=grandpa
WorkingDirectory=/opt/grandpa
ExecStart=/opt/grandpa/.venv/bin/Grandpa serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/grandpa

[Install]
WantedBy=multi-user.target
```

### `[Unit]` Section

| Directive     | Value              | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `grandpa API Server` | Human-readable name shown in `systemctl status` and logs.              |
| `After`       | `network.target`   | Delays startup until the network stack is available, since the server binds to a network socket and may need to reach a remote engine. |

### `[Service]` Section

| Directive          | Value                                                              | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | The process started by `ExecStart` is the main service process. systemd considers the service started immediately. |
| `User`             | `grandpa`                                                       | Runs the server as the `grandpa` user rather than root, limiting the blast radius of any security issue. |
| `WorkingDirectory` | `/opt/grandpa`                                                  | Sets the working directory for the process. This is where grandpa looks for local files and writes data. |
| `ExecStart`        | `/opt/grandpa/.venv/bin/Grandpa serve --host 0.0.0.0 --port 8000` | The command to start the server. Uses the full path to the `Grandpa` binary inside the virtual environment. |
| `Restart`          | `on-failure`                                                       | Automatically restarts the service if it exits with a non-zero exit code. Does not restart on clean shutdown (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Waits 5 seconds before attempting a restart, preventing rapid restart loops if the service crashes immediately on startup. |
| `Environment`      | `HOME=/opt/grandpa`                                             | Sets the `HOME` environment variable so grandpa finds its configuration at `~/.grandpa/config.toml` (resolving to `/opt/grandpa/.grandpa/config.toml`). |

### `[Install]` Section

| Directive    | Value               | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | The service starts when the system reaches multi-user mode (standard boot target for servers). `systemctl enable` creates a symlink under this target. |

## Configuration Options

### Changing the Bind Address and Port

Edit the `ExecStart` line to change the host or port:

```ini
ExecStart=/opt/grandpa/.venv/bin/Grandpa serve --host 127.0.0.1 --port 9000
```

!!! tip
    Binding to `127.0.0.1` restricts access to localhost only. Use this when running behind a reverse proxy like Nginx or Caddy.

### Setting the Engine and Model

Pass additional flags to `Grandpa serve`:

```ini
ExecStart=/opt/grandpa/.venv/bin/Grandpa serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Adding Environment Variables

Add multiple `Environment` directives or use `EnvironmentFile` for complex configurations:

```ini
[Service]
Environment=HOME=/opt/grandpa
Environment=grandpa_ENGINE_DEFAULT=vllm
Environment=grandpa_OLLAMA_HOST=http://localhost:11434
```

Or load from a file:

```ini
[Service]
EnvironmentFile=/opt/grandpa/.env
```

### Changing the User

If you prefer a different service user, update both the `User` directive and the paths:

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/grandpa
ExecStart=/home/myuser/grandpa/.venv/bin/Grandpa serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/grandpa
```

### Using a Configuration File

Ensure the configuration file exists at the path where `HOME` points:

```bash
sudo -u grandpa mkdir -p /opt/grandpa/.grandpa
sudo -u grandpa cp config.toml /opt/grandpa/.grandpa/config.toml
```

The server reads `~/.grandpa/config.toml` on startup, where `~` resolves from the `HOME` environment variable.

## Viewing Logs

grandpa logs are captured by journald. View them with `journalctl`:

```bash
# View all logs for the service
sudo journalctl -u grandpa

# Follow logs in real time
sudo journalctl -u grandpa -f

# View logs since the last boot
sudo journalctl -u grandpa -b

# View logs from the last hour
sudo journalctl -u grandpa --since "1 hour ago"

# View only error-level messages
sudo journalctl -u grandpa -p err
```

## Managing the Service

### Start, Stop, and Restart

```bash
# Start the service
sudo systemctl start grandpa

# Stop the service
sudo systemctl stop grandpa

# Restart the service (stop + start)
sudo systemctl restart grandpa

# Reload configuration without full restart (sends SIGHUP)
sudo systemctl reload-or-restart grandpa
```

### Check Status

```bash
sudo systemctl status grandpa
```

Example output:

```
● grandpa.service - grandpa API Server
     Loaded: loaded (/etc/systemd/system/grandpa.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (Grandpa)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/grandpa.service
             └─12345 /opt/grandpa/.venv/bin/python /opt/grandpa/.venv/bin/Grandpa serve --host 0.0.0.0 --port 8000
```

### Enable and Disable on Boot

```bash
# Enable automatic start on boot
sudo systemctl enable grandpa

# Disable automatic start on boot
sudo systemctl disable grandpa
```

### Apply Changes After Editing the Unit File

After modifying `/etc/systemd/system/grandpa.service`, reload the systemd daemon and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart grandpa
```

## Running Alongside Ollama

If Ollama is also managed via systemd, you can add an ordering dependency so the grandpa service waits for Ollama to start:

```ini
[Unit]
Description=grandpa API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Ensures grandpa starts after Ollama.                                  |
| `Requires` | If Ollama fails to start, grandpa will not start either.              |

!!! note
    Use `Wants` instead of `Requires` if you want grandpa to start even when Ollama is unavailable (for example, if you plan to start Ollama manually later).
