# Avatar voices

`grandpa avatar` picks a voice for each sentence of a reply. It prints the voices it chose when it starts.

| Order | Voice | Where it runs | When it's used |
|---|---|---|---|
| 1 | **ElevenLabs**, your cloned voice | Cloud (opt-in) | When `ELEVENLABS_API_KEY` is set |
| 2 | **Piper** (`en_GB-alan-medium`) | This PC | English / Thanglish, when installed |
| 2 | **MMS Tamil** (sherpa-onnx) | This PC | Replies written mostly in Tamil script |
| 3 | pyttsx3 (Windows SAPI) | This PC | Used when nothing else is installed |

If ElevenLabs fails (no internet, no credits, a bad key), that sentence is spoken
with the local voice. Grandpa then stays local for 60 seconds, so it doesn't wait on a timeout for every sentence.

**Privacy:** with the ElevenLabs key set, the text of every spoken reply is sent to
ElevenLabs. To keep everything on this PC, leave the key unset or set
`GRANDPA_AVATAR_VOICE=piper`.

## Set up your ElevenLabs voice

1. Go to elevenlabs.io → **Developers → API Keys** and create a key. Give it the
   *Text to Speech* permission only, and set a monthly credit limit.
2. In PowerShell (the key is saved for your Windows user, not in the repo):

   ```powershell
   setx ELEVENLABS_API_KEY "<your key>"
   ```

   Then open a **new** terminal.
3. Test it:

   ```powershell
   uv run python -m grandpa.speech.elevenlabs_tts "Hello Captain, this is Grandpa."
   ```

4. Start the avatar: `uv run --extra avatar --extra piper --extra tamil-voice python -m grandpa avatar`.

| Variable | Default | Meaning |
|---|---|---|
| `GRANDPA_ELEVENLABS_VOICE` | `iJwttXBNy3RzWJrkRD97` (Achchuu) | Voice for English / Thanglish |
| `GRANDPA_ELEVENLABS_TAMIL_VOICE` | same as above | A separate Tamil clone, if you make one |
| `GRANDPA_ELEVENLABS_MODEL` | `eleven_flash_v2_5` | `eleven_multilingual_v2` sounds richer but is slower and costs 2x |
| `GRANDPA_AVATAR_VOICE` | — | `piper`/`local` = stay offline, `pyttsx3` = old Windows voice |

Never paste the API key into chat, code, `config.yaml` or a commit.

## Your own voice, fully offline (no ElevenLabs)

The ElevenLabs clone lives on ElevenLabs' servers, so it stops working when the subscription ends. To keep Captain's voice for good, Grandpa gets a **local Piper voice** trained on recordings of that voice:

1. Record the training set while credits last (about 36 minutes of audio, roughly 20k credits on Flash):
   ```powershell
   $env:ELEVENLABS_API_KEY = [Environment]::GetEnvironmentVariable('ELEVENLABS_API_KEY','User')
   uv run python scripts/odin/voice/make_voice_dataset.py --out D:\GrandpaVoice\achchuu --credits-left <left>
   ```
   You can run it again safely: lines that are already recorded are skipped.
2. Train it on Colab with `notebooks/grandpa_voice_piper.ipynb` (T4 GPU, 5–7 hours; it resumes after a disconnect).
3. Copy `grandpa-achchuu.onnx` and `.onnx.json` to `~\.Grandpa\voices`, then set `GRANDPA_PIPER_VOICE=grandpa-achchuu`.

The local voice runs on the CPU at about 0.13× real time on the Vivobook, and it needs no internet.
