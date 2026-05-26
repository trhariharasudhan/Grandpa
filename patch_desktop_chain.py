from pathlib import Path

p = Path("src/grandpa/desktop_automation.py")
s = p.read_text(encoding="utf-8")

old = '''    action, value = _split_spec(spec)
'''

new = '''    if "||" in spec:
        messages = []
        for part in spec.split("||"):
            result = _execute_with_pyautogui(pyautogui, part)
            messages.append(result.message)
            if result.status != "handled":
                return result
        return AutomationResult(
            status="handled",
            message=" ".join(messages),
            tts_text="Done.",
        )

    action, value = _split_spec(spec)
'''

if old not in s:
    raise SystemExit("target block not found")

p.write_text(s.replace(old, new), encoding="utf-8")
print("patched desktop_automation.py")