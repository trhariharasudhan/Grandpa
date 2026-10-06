"""The decoding options are what measurement left them, not what sounds right.

Four hypotheses were tested against 120 degraded clips of synthesised speech,
504 reference words, four signal-to-noise ratios and three noise realisations
each. Three were refuted:

    base.en beam=1 (shipped)   WER 0.133   --
    base.en beam=5             WER 0.123   z +0.47  not significant
    base.en beam=3             WER 0.121   z +0.57  not significant
    base.en, no initial_prompt WER 0.317   z -7.01  significantly WORSE
    small.en beam=1            WER 0.087   z +2.32  significant

``beam_size=5`` looked like a win on a 42-word sample -- 4 errors against 3 --
and evaporated at 504 words. That near-miss is why these are pinned: the next
person to read "greedy decoding for latency" will have the same idea, and the
number to beat should be in the repository rather than in a chat log.

Gain normalisation, trailing-silence trimming, ``condition_on_previous_text``,
``temperature`` fallback, ``vad_filter`` and the two-channel downmix were each
measured at no significant effect. The only significant lever is the model.
"""

from __future__ import annotations

import pytest

from grandpa.speech.faster_whisper import build_transcription_options
from grandpa.speech.vocabulary import build_initial_prompt

pytestmark = pytest.mark.core


def test_greedy_decoding_stays_greedy() -> None:
    """beam_size=5 measured z = +0.47. Not a win, and it is not adopted.

    If this is ever raised, the commit should carry a WER measurement beating
    0.133 on a corpus of at least 500 reference words -- not a transcript or two
    that read better.
    """
    assert build_transcription_options("en")["beam_size"] == 1


def test_a_single_temperature_with_no_fallback_ladder() -> None:
    """A temperature ladder changed nothing and multiplies worst-case latency."""
    options = build_transcription_options("en")

    assert options["temperature"] == 0.0
    assert not isinstance(options["temperature"], (list, tuple))


def test_the_decoder_is_not_conditioned_on_previous_text() -> None:
    """Measured at no effect, and it couples one utterance to the last."""
    assert build_transcription_options("en")["condition_on_previous_text"] is False


def test_whispers_internal_vad_stays_off() -> None:
    """vad_filter=True measured at no effect, and Grandpa already has a VAD."""
    assert build_transcription_options("en")["vad_filter"] is False


def test_the_initial_prompt_is_not_empty_because_removing_it_measurably_hurts() -> None:
    """The one change with a large, significant effect -- in the wrong direction.

    Removing the prompt took WER from 0.133 to 0.317, z = -7.01. It is the
    cheapest thing in the pipeline that works, so it must not be dropped as
    cosmetic.
    """
    options = build_transcription_options("en")

    assert options["initial_prompt"], "the prompt is load-bearing, not decoration"
    assert options["initial_prompt"] == build_initial_prompt()


def test_trusted_audio_still_disables_every_threshold() -> None:
    """Unchanged by this round: push-to-talk refuses nothing."""
    options = build_transcription_options("en", trust_audio=True)

    assert options["no_speech_threshold"] is None
    assert options["log_prob_threshold"] is None
    assert options["compression_ratio_threshold"] is None
    # And the prompt still applies -- it helps, and it refuses nothing.
    assert options["initial_prompt"]


def test_the_default_model_is_base_en_not_the_multilingual_base() -> None:
    """It was ``base``, and the ``base.en`` fallback beside it was unreachable.

    ``SpeechConfig.model`` defaulted to "base", which always won the
    ``_first_non_empty`` chain, so voice mode's own "base.en" tail was dead code
    and every user ran the multilingual model however the docs read.

    Measured over 504 reference words::

        base.en   WER 0.133   1.00x latency
        base      WER 0.177   2.36x latency

    Worse on both axes at once, so this change costs nothing. It is the only
    default moved in this round, precisely because it is free; ``small.en`` is
    better still (0.087) but costs 2.85x latency and is recommended in the
    documentation rather than imposed.
    """
    from grandpa.core.config import SpeechConfig
    from grandpa.voice.config import load_voice_assistant_config

    assert SpeechConfig().model == "base.en"
    assert load_voice_assistant_config().stt_model == "base.en"


def test_small_en_is_not_imposed_as_the_default() -> None:
    """Better, but it costs 2.85x latency and was measured on synthetic speech.

    The failure being chased is on a particular voice and microphone that no
    synthetic corpus reproduced, so recommending it with the numbers is
    supportable and changing what everyone loads is not.
    """
    from grandpa.voice.config import load_voice_assistant_config

    assert load_voice_assistant_config().stt_model != "small.en"


def test_a_non_english_language_does_not_get_an_english_only_model() -> None:
    """An .en model cannot transcribe French at all, whatever was configured."""
    from grandpa.voice.config import load_voice_assistant_config

    assert load_voice_assistant_config(language="fr").stt_model == "base"
    assert (
        load_voice_assistant_config(model="small.en", language="fr").stt_model
        == "small"
    )


def test_english_variants_keep_the_english_only_model() -> None:
    from grandpa.voice.config import load_voice_assistant_config

    for code in ("en", "en-GB", "EN", "en-US"):
        assert load_voice_assistant_config(language=code).stt_model == "base.en", code


def test_an_explicit_multilingual_model_is_left_alone() -> None:
    from grandpa.voice.config import load_voice_assistant_config

    assert load_voice_assistant_config(model="base").stt_model == "base"
    assert load_voice_assistant_config(model="small").stt_model == "small"


def test_the_model_can_be_changed_without_editing_code() -> None:
    """Three routes, because the measured fix is a model choice."""
    import inspect

    from grandpa.voice import config as voice_config

    source = inspect.getsource(voice_config.load_voice_assistant_config)
    assert "GRANDPA_VOICE_STT_MODEL" in source
    # The --model flag, on the commands where accuracy is judged.
    from grandpa.cli.voice_cmd import voice

    for command in ("accuracy-test", "push-to-talk"):
        names = {
            name
            for parameter in voice.commands[command].params
            for name in parameter.opts
        }
        assert "--model" in names, command
