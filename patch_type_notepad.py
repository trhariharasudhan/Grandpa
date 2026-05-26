from pathlib import Path

p = Path("src/grandpa/local_actions.py")
s = p.read_text(encoding="utf-8")

old = '''    match = re.fullmatch(r"type (.+)", command)
    if match:
        text = match.group(1).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"type|{text}",
            message=f'Typing "{text}".',
            tts_text="Typing that.",
        )
'''

new = '''    match = re.fullmatch(r"type (.+?) in (notepad)", command)
    if match:
        text = match.group(1).strip()
        app = match.group(2).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"focus|{app}||type|{text}",
            message=f'Typing "{text}" in {app.title()}.',
            tts_text=f"Typing that in {app.title()}.",
        )

    match = re.fullmatch(r"type (.+)", command)
    if match:
        text = match.group(1).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"type|{text}",
            message=f'Typing "{text}".',
            tts_text="Typing that.",
        )
'''

if old not in s:
    raise SystemExit("target block not found")

p.write_text(s.replace(old, new), encoding="utf-8")
print("patched local_actions.py")