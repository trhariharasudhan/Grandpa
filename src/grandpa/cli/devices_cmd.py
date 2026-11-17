"""``grandpa devices``: pair a phone over the LAN, list and revoke (D1).

* ``pair``   -- open a 5-minute, one-use pairing code and print the address
  the phone should send it to. Waits until the phone pairs (``--no-wait``
  returns at once).
* ``list``   -- paired devices and when each was last seen.
* ``revoke`` -- stop a device's token at once.
* ``notify`` -- send a notification to every paired phone (D3).
* ``log``    -- the pairing log (who paired, refused codes, revocations).
"""

from __future__ import annotations

import ipaddress
import socket
import time
from datetime import datetime

import click

from grandpa.devices import DeviceStore


def _lan_address() -> str | None:
    """This PC's address on the LAN, from the route the OS would pick.

    A UDP ``connect`` sends nothing; it only asks the OS which interface it
    would use.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if ipaddress.ip_address(address).is_loopback else address


def _when(ts: float | None) -> str:
    if not ts:
        return "never"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@click.group()
def devices() -> None:
    """Pair phones on your Wi-Fi with Grandpa, and manage them."""


@devices.command()
@click.option("--no-wait", is_flag=True, help="Print the code and return.")
def pair(no_wait: bool) -> None:
    """Make a one-time pairing code for a phone on the same Wi-Fi."""
    from grandpa.core.config import load_config

    server = load_config().server
    store = DeviceStore()
    before = {d.device_id for d in store.list_devices()}
    code = store.start_pairing()

    click.echo(f"Pairing code: {code.code}")
    click.echo("It works once and expires in 5 minutes.")
    address = _lan_address()
    if address:
        click.echo(f"Phone sends it to: http://{address}:{server.port}/v1/devices/pair")
    else:
        click.echo("Could not find this PC's LAN address (is Wi-Fi connected?).")
    try:
        loopback = ipaddress.ip_address(server.host).is_loopback
    except ValueError:
        loopback = server.host in ("localhost", "")
    if loopback:
        click.echo(
            "The server only listens on this PC. Start it for the phone with:\n"
            f"  grandpa serve --host 0.0.0.0 --port {server.port}"
        )
    if no_wait:
        return

    click.echo("Waiting for the phone... (Ctrl+C to cancel)")
    try:
        while store.pairing_open():
            time.sleep(1)
    except KeyboardInterrupt:
        store.cancel_pairing()
        click.echo("Cancelled. The code no longer works.")
        return
    new = [d for d in store.list_devices() if d.device_id not in before]
    if new:
        click.echo(f"Paired: {new[-1].name} ({new[-1].device_id})")
    else:
        click.echo("Not paired: the code expired or too many wrong codes were tried.")
        raise SystemExit(1)


@devices.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include revoked devices.")
def list_cmd(show_all: bool) -> None:
    """Show paired devices."""
    rows = DeviceStore().list_devices(include_revoked=show_all)
    if not rows:
        click.echo("No paired devices. Pair one with: grandpa devices pair")
        return
    for d in rows:
        state = "revoked" if d.revoked else "active"
        click.echo(
            f"{d.device_id}  {d.name:<20}  {state:<7}  "
            f"paired {_when(d.created_at)}  last seen {_when(d.last_seen_at)}"
        )


@devices.command()
@click.argument("device_id")
def revoke(device_id: str) -> None:
    """Stop a paired device's access at once."""
    if DeviceStore().revoke(device_id):
        click.echo(f"Revoked {device_id}. Its token no longer works.")
    else:
        raise click.ClickException(f"No active device with id {device_id}.")


@devices.command()
@click.argument("message")
@click.option("--title", default="Grandpa", show_default=True)
def notify(message: str, title: str) -> None:
    """Send a notification to every paired phone (they pick it up next poll)."""
    new_id = DeviceStore().push_notification(title, message, kind="manual")
    if new_id is None:
        raise click.ClickException(
            "No paired phone to notify. Pair one with: grandpa devices pair"
        )
    click.echo(f"Queued notification {new_id} for paired phones.")


@devices.command("log")
@click.option("--limit", default=20, show_default=True)
def log_cmd(limit: int) -> None:
    """Show the pairing log, newest first."""
    for e in DeviceStore().events(limit):
        who = f" {e['device_id']}" if e["device_id"] else ""
        detail = f" ({e['detail']})" if e["detail"] else ""
        click.echo(f"{_when(e['at'])}  {e['event']}{who}{detail}")
