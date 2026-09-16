"""Redeem an approval code from the terminal.

``pc_control`` stages a high-risk action and prints an approval code to the
console. Until now the only way to spend one was an HTTP POST to
``/api/local-action/{id}/approve`` -- so a terminal user was handed a code that
nothing they could run would accept (audit finding 3). The action layer does not
need this: it asks inline through a callback, and every interactive caller has
one. What needs it is a caller that cannot block on a human, which is why the
staging exists at all -- and the codes it prints should be spendable by the
person reading them.

The code is required. An action id is not an authorisation: it appears in the
HTTP response, and the whole point of the out-of-band code is that seeing the
staged action is not the same as approving it.
"""

from __future__ import annotations

import click


@click.command("approve")
@click.argument("action_id", required=False)
@click.option("--code", default="", help="The approval code printed when staged.")
@click.option("--deny", is_flag=True, help="Refuse the action instead.")
@click.option("--list", "list_pending", is_flag=True, help="Show what is waiting.")
def approve(action_id: str | None, code: str, deny: bool, list_pending: bool) -> None:
    """Approve, deny, or list pending local actions."""
    # Through the kernel's approval facade, not pc_control: a CLI module that
    # imports the executor directly is a new route around the kernel, and the
    # direct-executor baseline exists to stop exactly that.
    from grandpa.desktop.kernel import approvals

    if list_pending or not action_id:
        pending = approvals.pending()
        if not pending:
            click.echo("Nothing is waiting for approval.")
            return
        click.echo(f"{len(pending)} action(s) waiting:")
        for item in pending:
            click.echo(
                f"  {item.get('action_id')}  {item.get('action_type')} "
                f"on {item.get('target') or '-'}  ({item.get('risk_level')})"
            )
        click.echo("\nApprove with: grandpa approve <action-id> --code <code>")
        return

    if deny:
        response = approvals.reject(action_id)
    elif not code:
        raise click.UsageError(
            "An approval code is required. It was printed when the action was "
            "staged: grandpa approve <action-id> --code <code>"
        )
    else:
        response = approvals.approve(action_id, code)

    click.echo(response.message)
    if not getattr(response, "ok", False):
        raise SystemExit(1)


__all__ = ["approve"]
