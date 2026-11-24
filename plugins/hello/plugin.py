"""The sample plugin. Every function gets ``ctx`` first.

``ctx.config``      the [config] values (defaults, or ~/.grandpa/plugins.toml)
``ctx.run_action``  run a Grandpa action listed in permissions as actions:<name>
``ctx.log``         write a line to Grandpa's log
"""

from grandpa.plugins import ActionResult


def greet(ctx, name):
    return f"{ctx.config['greeting']}, {name}!"


def greet_with_time(ctx, name="Captain"):
    clock = ctx.run_action("datetime_now", kind="time")
    if not clock.success:
        return ActionResult.failed("no_clock", message=clock.message)
    return f"{ctx.config['greeting']}, {name}! {clock.message}"


def on_workflow_end(ctx, data):
    ctx.log(f"workflow finished: {data.get('workflow')}")
