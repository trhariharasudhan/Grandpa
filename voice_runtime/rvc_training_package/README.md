# Hari RVC v2 pilot training package

This package contains only original Hari microphone recordings prepared for a
single-speaker RVC v2 pilot. It does not contain F5 output, synthetic clone
output, Grandpa source code, credentials, or runtime configuration.

## Dataset

- 12 accepted original-microphone recordings
- 260.940 seconds (4 minutes 20.940 seconds)
- Mono, 40 kHz, PCM16 WAV
- Edge silence only was trimmed at -45 dBFS with 100 ms retained padding
- No denoising, normalization, pitch shifting, or speed modification
- `manifest.csv` records provenance, quality metrics, and SHA-256 hashes

The ten files from `raw/original` had MP3 payloads despite `.wav` names. They
were decoded once into genuine PCM WAV training copies. The two `original_v2`
files were genuine PCM WAV sources. RVC does not require transcripts.

## Pinned upstream

Repository: `https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI`

Revision: `81eed5e8f68b6bed1789f682fe78cdd324495afc`

## Preferred GPU

An NVIDIA T4 16 GB is sufficient for this pilot. An RTX 3090 24 GB, RTX 4090,
L4, or A4000 is faster and gives more margin. Use batch size 4; reduce it to 2
only if the training process reports CUDA out-of-memory.

## Google Colab procedure

Colab is sufficient when a T4-or-better GPU is actually allocated and the
session remains connected. Free GPU availability and runtime duration are not
guaranteed, so RunPod is the more predictable fallback.

1. Zip this directory locally and upload it to Colab as
   `/content/rvc_training_package.zip`.
2. Select **Runtime > Change runtime type > T4 GPU**.
3. Run these cells exactly:

```bash
!nvidia-smi
!python --version
!sudo apt-get update -qq
!sudo apt-get install -y -qq ffmpeg unzip
!git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git /content/rvc
%cd /content/rvc
!git checkout 81eed5e8f68b6bed1789f682fe78cdd324495afc
!python -m pip install --upgrade pip "setuptools<81" wheel
!python -m pip install torch==2.7.1+cu118 torchaudio==2.7.1+cu118 --index-url https://download.pytorch.org/whl/cu118 --extra-index-url https://pypi.org/simple
!sed -i 's#https://mirrors.pku.edu.cn/pypi/simple#https://pypi.org/simple#' requirments_cu118_py312.txt
!python -m pip install -r requirments_cu118_py312.txt
!python -m pip install --upgrade huggingface_hub
!hf download lj1995/VoiceConversionWebUI --revision main --include "hubert_base/*" --local-dir assets
!hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision main --local-dir assets/rmvpe
!hf download lj1995/VoiceConversionWebUI --revision main --include "pretrained/*" "pretrained_v2/*" --local-dir assets
!unzip -q /content/rvc_training_package.zip -d /content/rvc_training_package
!chmod +x /content/rvc_training_package/train_hari_pilot.sh
!bash /content/rvc_training_package/train_hari_pilot.sh /content/rvc_training_package/dataset
```

4. Download only:

```text
/content/rvc/artifacts/hari_rvc.pth
/content/rvc/artifacts/hari_rvc.index
/content/rvc/artifacts/training_run.txt
/content/rvc/artifacts/SHA256SUMS
```

Do not download the virtual environment, checkpoints under `logs`, model
caches, or extracted feature directories.

## RunPod procedure

1. Start a secure PyTorch pod with an NVIDIA T4 16 GB or better, at least 25 GB
   container disk, and no public network ports. Stop the pod after downloading
   the artifacts.
2. Upload the package zip to `/workspace/rvc_training_package.zip`.
3. Run:

```bash
cd /workspace
apt-get update -qq && apt-get install -y -qq ffmpeg unzip git
git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git rvc
cd rvc
git checkout 81eed5e8f68b6bed1789f682fe78cdd324495afc
python -m pip install --upgrade pip "setuptools<81" wheel
python -m pip install torch==2.7.1+cu118 torchaudio==2.7.1+cu118 --index-url https://download.pytorch.org/whl/cu118 --extra-index-url https://pypi.org/simple
sed -i 's#https://mirrors.pku.edu.cn/pypi/simple#https://pypi.org/simple#' requirments_cu118_py312.txt
python -m pip install -r requirments_cu118_py312.txt
python -m pip install --upgrade huggingface_hub
hf download lj1995/VoiceConversionWebUI --revision main --include "hubert_base/*" --local-dir assets
hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision main --local-dir assets/rmvpe
hf download lj1995/VoiceConversionWebUI --revision main --include "pretrained/*" "pretrained_v2/*" --local-dir assets
unzip -q /workspace/rvc_training_package.zip -d /workspace/rvc_training_package
chmod +x /workspace/rvc_training_package/train_hari_pilot.sh
bash /workspace/rvc_training_package/train_hari_pilot.sh /workspace/rvc_training_package/dataset
```

4. Copy only the two model artifacts and the two provenance files from
   `/workspace/rvc/artifacts/` back to the laptop.

## Pilot settings

| Setting | Value |
| --- | --- |
| RVC version | v2 |
| Sample rate | 40 kHz |
| Pitch guidance | Enabled |
| F0 extraction | RMVPE on CUDA |
| Epochs | 120 |
| Batch size | 4 |
| Save interval | 20 epochs |
| GPU dataset cache | Disabled |
| Speaker ID | 0 |

Expected wall time is approximately 30-90 minutes on a T4, including setup,
downloads, preprocessing, feature extraction, training, and index creation.
Actual time depends on GPU allocation, storage, network throughput, and Colab
session stability.

## Return destination

After training, copy and verify only:

```text
D:\Grandpa\voice_runtime\models_or_cache\rvc_hari\hari_rvc.pth
D:\Grandpa\voice_runtime\models_or_cache\rvc_hari\hari_rvc.index
```

Do not integrate the model into Grandpa until local conversion of "Hello Hari,
Grandpa is ready." completes in under 10 seconds.
