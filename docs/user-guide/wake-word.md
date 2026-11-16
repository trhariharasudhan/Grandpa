# "Hey Grandpa" wake word

Grandpa listens for **"Hey Grandpa"** with [openWakeWord](https://github.com/dscripka/openWakeWord):
a small model that runs on the CPU (ONNX), on your PC, with no speech-to-text
and no audio saved anywhere. On a 2-core cloud CPU it used about 4-5% of one
core; expect similar on the Ryzen 5 7520U.

openWakeWord has no "Hey Grandpa" model of its own, so you train one once
(free, about an hour, mostly waiting). Until then you can check the microphone
path with the built-in `hey_mycroft` model.

## 1. Install

```powershell
cd D:\Grandpa
uv sync --extra wake --extra voice
uv run grandpa wake setup     # ~4 MB of shared feature models, once
uv run grandpa wake status
```

## 2. Check the microphone path (before training)

```powershell
uv run grandpa wake listen --model hey_mycroft --minutes 2
# say "Hey Mycroft" a few times -> one line per detection
```

## 3. Train "Hey Grandpa" (once, on a free Colab GPU)

1. Open openWakeWord's simple training notebook:
   <https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb>
2. Sign in with Google. **Runtime > Change runtime type > T4 GPU > Save.**
3. In the first form, set the target word to `hey grand pa` (spelling it this
   way helps the synthetic voices say it right). Leave the other settings.
4. **Runtime > Run all.** Accept the "not authored by Google" warning. It
   generates synthetic "Hey Grandpa" clips, trains, and takes about an hour.
5. When it finishes, open the **Files** panel (folder icon, left) and download
   the `.onnx` file it produced (e.g. `my_custom_model/hey_grand_pa.onnx`).
6. Save it as `C:\Users\<you>\.Grandpa\wakeword\hey_grandpa.onnx`
   (make the `wakeword` folder if needed).
7. Check: `uv run grandpa wake status` shows the file.

The trained model is yours; it is not committed to the repo.

## 4. Test it

```powershell
# Say "Hey Grandpa" 20 times from your usual seat; count the lines.
uv run grandpa wake listen --minutes 3

# False triggers: leave it running for an hour with TV / talk / music,
# without saying it. Target: fewer than 1 per hour.
uv run grandpa wake listen --minutes 60

# Or a recording (16-bit WAV, any rate) of an hour with no wake phrase:
uv run grandpa wake test D:\recordings\evening.wav --negative
```

Too many false triggers: raise `--threshold` (0.6, 0.7) or `--patience 3`.
Missed "Hey Grandpa": lower `--threshold` (0.4). Once you like a value, set it
for good with the environment variables below.

| Setting | Default | Env var |
| --- | --- | --- |
| model | `~/.Grandpa/wakeword/hey_grandpa.onnx` | `GRANDPA_WAKE_MODEL` |
| threshold | 0.5 | `GRANDPA_WAKE_THRESHOLD` |
| frames in a row (80 ms each) | 2 | `GRANDPA_WAKE_PATIENCE` |
| quiet time after a detection | 2.0 s | `GRANDPA_WAKE_COOLDOWN` |
| speech filter (Silero VAD) | 0.3 | `GRANDPA_WAKE_VAD_THRESHOLD` |

Licence note: openWakeWord's code is Apache-2.0; its *built-in* models
(`hey_mycroft` etc.) are CC-BY-NC-SA 4.0. Your own trained model is not one of
those built-ins.

Next (B2): the voice loop listens for the wake word all the time and starts a
command after it; push-to-talk stays.
