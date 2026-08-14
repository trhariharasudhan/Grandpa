#!/usr/bin/env bash
set -euo pipefail

# Run from the pinned RVC repository root after dependencies and official model
# assets are installed. The first argument is the prepared dataset directory.
DATASET_DIR="${1:?usage: train_hari_pilot.sh /path/to/dataset}"
EXPERIMENT="hari_rvc"
REVISION="81eed5e8f68b6bed1789f682fe78cdd324495afc"
STARTED_AT="$(date --iso-8601=seconds)"

test "$(git rev-parse HEAD)" = "$REVISION"
test -d "$DATASET_DIR"
nvidia-smi
python -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"

rm -rf "logs/$EXPERIMENT"
python train/preprocess.py "$DATASET_DIR" 40000 4 "logs/$EXPERIMENT" False 3.7
python train/dataset/extract_f0.py cuda 1 0 0 "logs/$EXPERIMENT" true
python train/dataset/extract_hubert_feature.py cuda:0 1 0 0 "logs/$EXPERIMENT" v2 true

python - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
exp = root / "logs" / "hari_rvc"
config = json.loads((root / "configs" / "v1" / "40k.json").read_text(encoding="utf-8"))
(exp / "config.json").write_text(
    json.dumps(config, indent=4, sort_keys=True) + "\n", encoding="utf-8"
)

rows = []
for wav in sorted((exp / "0_gt_wavs").glob("*.wav")):
    feature = exp / "3_feature768" / f"{wav.stem}.npy"
    coarse_f0 = exp / "2a_f0" / f"{wav.name}.npy"
    continuous_f0 = exp / "2b-f0nsf" / f"{wav.name}.npy"
    missing = [path for path in (feature, coarse_f0, continuous_f0) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing extracted files for {wav.name}: {missing}")
    rows.append("|".join(map(str, (wav, feature, coarse_f0, continuous_f0, 0))))
if not rows:
    raise RuntimeError("preprocessing produced no training segments")
(exp / "filelist.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
print(f"Prepared {len(rows)} RVC training segments")
PY

# Conservative pilot: RVC v2, 40 kHz, RMVPE/F0, batch 4, no GPU data cache.
python train/train.py \
  -e "$EXPERIMENT" -sr 40k -f0 1 -bs 4 -g 0 \
  -te 120 -se 20 \
  -pg assets/pretrained_v2/f0G40k.pth \
  -pd assets/pretrained_v2/f0D40k.pth \
  -l 1 -c 0 -sw 1 -v v2

python train/train_index.py "$EXPERIMENT" v2 assets/indices 4 single

mkdir -p artifacts
cp "assets/weights/$EXPERIMENT.pth" artifacts/hari_rvc.pth
INDEX_PATH="$(find "logs/$EXPERIMENT" -maxdepth 1 -name 'added_*.index' -type f -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
test -n "$INDEX_PATH"
cp "$INDEX_PATH" artifacts/hari_rvc.index

FINISHED_AT="$(date --iso-8601=seconds)"
GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
cat > artifacts/training_run.txt <<EOF
rvc_revision=$REVISION
started_at=$STARTED_AT
finished_at=$FINISHED_AT
gpu=$GPU_NAME
version=v2
sample_rate=40000
f0_method=rmvpe
epochs=120
batch_size=4
cache_dataset_in_gpu=false
dataset=$DATASET_DIR
EOF

sha256sum artifacts/hari_rvc.pth artifacts/hari_rvc.index > artifacts/SHA256SUMS
ls -lh artifacts
