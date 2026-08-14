# Hari Personalized Piper Pilot Plan

Status: dataset and training-plan preparation only. No Piper dependency, model,
training run, or Grandpa runtime integration has been performed.

## 1. Official Piper Requirements

Source of truth: [current Piper training documentation](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md).

| Area | Current official requirement |
| --- | --- |
| Audio input | Any format supported by `librosa`; the documentation says files are usually WAV. |
| Sample rate | Configured with `--model.sample_rate`; 22,050 Hz is the documented usual value. A fine-tuning checkpoint and dataset must use a compatible rate. |
| Channels | The current training document does not state a mono/stereo rule. This pilot deliberately standardizes a single speaker to mono. |
| Transcript | UTF-8 pipe-delimited CSV: `utt1.wav|Exact transcript`. The filename is resolved inside `--data.audio_dir`. |
| Dataset layout | Piper requires an audio directory plus CSV. Grandpa uses additional immutable raw, staging, manifest, and report directories for provenance. |
| Dataset size | The current official documentation gives no minimum or recommended duration. The requested 30-45 minute pilot is an experiment, not an official quality guarantee. |
| Fine-tuning | `python3 -m piper.train fit ... --ckpt_path <medium checkpoint>` is recommended; only medium checkpoints are supported without architecture changes. |
| Export | `python3 -m piper.train.export_onnx --checkpoint <ckpt> --output-file <model.onnx>`, paired with a same-named `.onnx.json` config. |
| Training platform | Official setup uses Linux-style system packages and a compiled monotonic-alignment extension. Windows inference is supported, but native Windows training is not the documented primary path. |
| Hardware | Official voices were trained on a Threadripper with 128 GiB RAM and A6000/RTX 3090 GPUs; successful reports go down to about 8 GiB VRAM. The documentation provides no practical CPU-training estimate. |

Conclusion: do not train on the Ryzen 5 7520U. Use a Linux cloud GPU with at
least 12-16 GiB VRAM for margin, then bring only the ONNX model and JSON config
back to the local offline runtime.

## 2. Dataset Structure

```text
voice_runtime/datasets/hari_piper/
  raw/          # immutable user-owned source clips; ignored
  processed/    # normalized staging copies; ignored
  wavs/         # accepted Piper utterances; ignored
  metadata/     # local source/Piper/extended manifests; ignored
  scripts/      # reviewable preparation tooling
  reports/      # generated validation reports; ignored
```

The personal-data directories are ignored by Git. `prepare_dataset.py` reads
only from `raw/`, refuses path traversal and overwrites, and creates 22,050 Hz
mono PCM16 copies. It trims only leading/trailing silence, applies bounded peak
normalization, never denoises or changes pitch/rate, rejects corrupt/silent,
clipped, extremely noisy, overlong, or transcript-less clips, and emits Piper
metadata plus an extended provenance manifest.

## 3. Existing Audio Inventory

Audited locations: `D:\Grandpa\voice_runtime\references`, outputs migrated into
that runtime, and the still-present `D:\GrandpaVoice` source runtime.

| Asset | Duration | Provenance | Transcript status | Pilot use |
| --- | ---: | --- | --- | --- |
| 7 `ElevenLabs_*.mp3` files | 552.096 s (9:12.096) | C2PA identifies ElevenLabs trained-algorithmic media | No exact sidecars; local Whisper drafts only | Experimental `synthetic_clone` pool after manual segmentation/review |
| `hari_reference.wav` | 7.000 s | Exact excerpt, offset 0, of the 22.829 s ElevenLabs `11_14_30` file | ASR-recovered draft exists; manual exact review required | Duplicate; do not add duration twice |
| 5 unique F5 output WAVs | 23.136 s | F5 generated from the ElevenLabs-derived reference | Local Whisper drafts; prompts are not stored beside every WAV | Exclude from initial training; second-generation synthetic audio |
| Verified original Hari microphone recordings | 0 s | None found in audited locations | N/A | Required for Model B |

The seven ElevenLabs files are mono 44.1 kHz and range from 22.829 to 279.811
seconds. They require sentence-level segmentation before Piper training. The
longest local Whisper draft contains clear recognition errors (`Fast AP`,
`Allama`, and heavily corrupted Tanglish), so none is approved as exact text.

Exact-transcript status:

- Seven candidate ElevenLabs source files: **7 missing exact transcripts**.
- Migrated seven-second reference: **1 uncertain transcript**, not missing but
  not manually verified.
- Five F5 diagnostic outputs: **5 missing exact sidecar transcripts** and not
  proposed as training ground truth.

## 4. Pilot Composition: 30-45 Minutes

Target 36 minutes, approximately 300-450 utterances of 3-10 seconds:

| Content | Target |
| --- | ---: |
| Natural English conversation and assistant replies | 10 min |
| Tanglish conversation | 7 min |
| Tamil-heavy Romanized Tanglish | 5 min |
| Technical explanations and terminology | 5 min |
| Commands, warnings, and status updates | 3 min |
| Numbers, dates, times, paths, filenames, URLs | 3 min |
| Questions, statements, pauses, and longer narration | 3 min |

Include Python, FastAPI, Docker, GitHub, Ollama, localhost, HTTP, API, DNS,
ports, databases, and common Windows paths. Keep one neutral, natural speaking
style and normal microphone position. Avoid emotional extremes and background
music.

Recommended experimental split:

- Model A: up to 9:12 manually corrected ElevenLabs synthetic-clone material
  plus newly prepared synthetic prompts, all tagged `synthetic_clone`.
- Model B: independently recorded 30-45 minutes of real Hari microphone audio,
  all tagged `original`.
- Never mix the two sources for the first comparison. Use the same held-out
  benchmark text and listening rubric for both models.

## 5. Missing Recording Assets

Still required before training:

1. A complete 300-450-line recording script matching the composition above.
2. A verified pronunciation list for Hari, Grandpa, Tamil/Tanglish words,
   product names, acronyms, file paths, dates, and numbers.
3. Thirty to forty-five minutes of original microphone recordings in short,
   individually named clips.
4. Human-reviewed exact transcripts for every accepted clip.
5. A held-out evaluation script that is never included in training.

Local Whisper may create draft transcripts, but every draft must be manually
corrected before `quality_status=accepted`.

## 6. Training and Export Workflow

1. Record/copy clips into ignored `raw/`; never alter them.
2. Copy `scripts/source_manifest.example.csv` to ignored
   `metadata/source_manifest.csv`, then enter exact transcripts and provenance.
3. Run the preparation script with `voice_runtime/.venv` only for audio
   preparation; review every `review`/`rejected` result manually.
4. Transfer accepted `wavs/` and `metadata.csv` to an isolated Linux GPU job.
5. Pin the current Piper source revision and training environment manifest.
6. Fine-tune a compatible medium English checkpoint first. Treat Tanglish as a
   separate pronunciation-risk gate; do not assume English eSpeak phonemes are
   sufficient.
7. Export ONNX and preserve its generated JSON configuration and model card.
8. Copy only final artifacts to
   `voice_runtime/models_or_cache/piper_hari/`.
9. Benchmark locally before any Grandpa engine integration.

CPU-only training on this laptop is rejected for the pilot: the official
workflow is GPU-oriented, the host has no usable CUDA GPU, and there is no
official evidence that CPU training would finish in a practical iteration
cycle.

## 7. Acceptance Benchmark

- English: `Hello Hari. Grandpa is ready.`
- Tanglish: `Vanakkam Hari. Naan Grandpa. Innaiku enna work panna porom?`
- Technical: `Hari, Docker, FastAPI, Ollama and the local voice service are ready.`

Measure cold load, warm synthesis, RTF, first-audio latency, peak RAM/CPU,
speaker similarity, English/Tanglish intelligibility, and Tamil pronunciation.
Accept under 5 seconds TTFA, prefer under 3 seconds, reject above 10 seconds.

## 8. Licensing

Current OHF Piper code is GPL-3.0. The project states that individual voice
models may have their own licenses, so the warm-start checkpoint's model card
must be retained and reviewed. Hari recordings require Hari's explicit consent;
ElevenLabs-generated material also remains subject to ElevenLabs terms and must
stay provenance-tagged. This is a technical inventory, not legal advice.

## 9. Exact Next Action

Record **ten original pilot clips** first: four English, three Tanglish, one
Tamil-heavy Tanglish, one technical sentence, and one numbers/dates sentence.
Place them in `voice_runtime/datasets/hari_piper/raw/`, create the local source
manifest from the example, verify every transcript manually, then run the
preparation script. Review those ten validation results before recording the
remaining 30-45 minutes; this catches microphone, clipping, naming, and
pronunciation problems cheaply.
