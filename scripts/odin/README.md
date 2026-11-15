# Training Odin-1 (grandpa-brain-odin1)

Odin is Grandpa's model family. Odin-1 is **grandpa-brain** (Qwen3 8B)
fine-tuned with LoRA on Grandpa's own tools, so it picks the right action more
often and follows the confirm/refuse rules. You train it once on a free cloud
GPU; it then runs locally in Ollama like every other Grandpa model.

Nothing here changes Grandpa's default model. Compare first (step 5), then
decide.

## 1. Make the dataset (on your PC, 1 minute)

```powershell
cd D:\Grandpa
git pull
uv run python scripts/odin/make_dataset.py
```

You should see `"actions_covered": 167`. The files are now in
`D:\Grandpa\runtime\odin\`: **train.jsonl** and **eval.jsonl** (and
`stats.json`). They contain no personal data.

## 2. Train on a free GPU (about 1–1.5 hours, mostly waiting)

**Google Colab**

1. Go to <https://colab.research.google.com> → **File → Upload notebook** →
   choose `D:\Grandpa\notebooks\odin_brain_lora.ipynb`.
2. **Runtime → Change runtime type → T4 GPU → Save.**
3. **Runtime → Run all.**
4. At step 3 a file picker appears: select **both** `train.jsonl` and
   `eval.jsonl` from `D:\Grandpa\runtime\odin\`.
5. At step 9 Colab asks to connect Google Drive: allow it. The finished model
   is saved as **MyDrive/grandpa/grandpa-brain-odin1.Q4_K_M.gguf** (~5 GB).

**Kaggle** (if Colab disconnects you)

1. <https://www.kaggle.com> → **Datasets → New dataset** → upload
   `train.jsonl` and `eval.jsonl`.
2. **Code → New notebook → File → Import notebook** → the `.ipynb`.
3. Right panel: **Add input** → your dataset; **Settings → Accelerator → GPU
   T4 x2**; **Internet → on**.
4. **Run all.** Download the `.gguf` from the **Output** tab when it finishes.

Step 7 of the notebook prints `tool chosen correctly: N/20` as a first sanity
check.

## 3. Put the file in place

Download `grandpa-brain-odin1.Q4_K_M.gguf` from Drive (or Kaggle) to:

```
D:\Grandpa\models\odin\grandpa-brain-odin1.Q4_K_M.gguf
```

(create the `odin` folder if needed). Git ignores `*.gguf`, so it is never
committed.

## 4. Create the Ollama model

```powershell
cd D:\Grandpa
ollama pull qwen3:8b        # only if you do not have it
powershell -ExecutionPolicy Bypass -File scripts\odin\create_odin1.ps1
ollama run grandpa-brain-odin1 "lock the screen"
```

`create_odin1.ps1` builds from `models/Modelfile.brain-odin1` and adds the
official Qwen3 chat template from your `qwen3:8b`, which is what makes tool
calls work.

## 5. Compare before switching

```powershell
uv run grandpa models eval grandpa-brain
uv run grandpa models eval grandpa-brain-odin1
```

(`grandpa models eval` arrives with O4.) It prints tool-call accuracy,
argument accuracy, refusal correctness and latency for each, and a
recommendation. Grandpa never switches by itself. To try Odin-1 in a session:
`uv run grandpa chat --model grandpa-brain-odin1`.

## Troubleshooting

- **"CUDA out of memory"** in step 6: in the settings cell set
  `MAX_SEQ_LENGTH = 2048`, then **Runtime → Restart and run all**.
- **Colab disconnected during training**: use Kaggle (sessions last longer), or
  set `EPOCHS = 1`.
- **`ollama create` says the template is missing**: run `ollama pull qwen3:8b`
  and run the script again.
