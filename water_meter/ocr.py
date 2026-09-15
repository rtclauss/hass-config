from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Sequence

from .config import CalibrationConfig

if TYPE_CHECKING:
    import numpy as np

LOG = logging.getLogger(__name__)

DIGIT_LABELS = "0123456789"


class OcrError(RuntimeError):
    """Raised when neither ssocr nor the template-match fallback can read a value."""


def run_ssocr(image_path: Path, *, ssocr_args: Sequence[str], timeout: float = 10.0) -> str:
    """Run the seven-segment OCR tool against a saved image.

    ssocr is deterministic and offline-debuggable (re-run it by hand against
    any saved image in images/history/ or images/rejects/), unlike a trained
    model - the reliability property this project is built around.
    """
    cmd = ["ssocr", *ssocr_args, str(image_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error:
        raise OcrError(
            "ssocr binary not found on PATH; see docs/water_meter.md for install steps"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise OcrError(f"ssocr timed out after {timeout}s") from error

    if result.returncode != 0:
        raise OcrError(f"ssocr exited {result.returncode}: {result.stderr.strip()}")

    digits = result.stdout.strip()
    if not digits:
        raise OcrError("ssocr returned an empty result")
    return digits


DEFAULT_VLM_MODEL = "qwen3-vl:4b"

DEFAULT_VLM_TIMEOUT = 480.0
"""Latency against truenas.local:30068's qwen3-vl:4b (CPU-only) is highly
variable, not just slow: one measured call took 123.9s total_duration with
only 48.4s of that in eval_duration (token generation) plus 0.27s
prompt_eval - Ollama's own accounting doesn't explain the remaining ~75s gap
(likely CPU contention on that box, not model-inherent). A 240s timeout was
tried and confirmed too short in production: a live run hit that cutoff,
then /api/ps showed the same generation had kept running server-side and
completed anyway past the client's cutoff - the call would have succeeded
if given more time. 480s trades a slower worst case for actually getting an
answer back instead of truncating a call that was going to work; see the
service's TimeoutStartSec, which must stay above this.
"""

DEFAULT_VLM_PROMPT = (
    "What {digit_count}-digit number is shown on this water meter LCD? "
    "Answer with just the digits, nothing else."
)


def read_digits_vlm(
    image_path: Path,
    *,
    host: str,
    digit_count: int,
    model: str = DEFAULT_VLM_MODEL,
    timeout: float = DEFAULT_VLM_TIMEOUT,
    hint: str | None = None,
) -> str:
    """Ask a vision LLM (via an Ollama /api/generate endpoint) to read the
    digits directly off the crop image.

    The only method that has ever correctly read this meter's glare-
    obscured digits - classical thresholding/morphology/template-matching
    never recovered them because the glare genuinely destroys the pixel
    data there, but a VLM reads the display holistically rather than
    per-segment. Deliberately does not cap `num_predict`: an earlier attempt
    at capping generation length (~30-40 tokens) to bound latency risked
    truncating the answer before the model's "thinking" trace finished and
    it emitted the final digit string - a generous timeout on the whole
    call is the safer knob than a token budget that can cut off the answer
    itself. See DEFAULT_VLM_TIMEOUT for why 240s and not something shorter.

    hint appends extra context to the prompt - used by reader.py's requery
    path to tell the model a first read produced an implausible value and
    ask it to look again, rather than re-asking the identical question and
    hoping sampling variance alone fixes it.
    """
    import base64
    import json as json_module
    import urllib.error
    import urllib.request

    image_bytes = image_path.read_bytes()
    prompt = DEFAULT_VLM_PROMPT.format(digit_count=digit_count)
    if hint:
        prompt = f"{prompt} {hint}"
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
    }
    request = urllib.request.Request(
        f"http://{host}/api/generate",
        data=json_module.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json_module.loads(response.read())
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise OcrError(f"vision-LLM request to {host} failed: {error}") from error
    except json_module.JSONDecodeError as error:
        raise OcrError(f"vision-LLM at {host} returned unparseable JSON: {error}") from error

    digits = str(body.get("response", "")).strip()
    if not digits.isdigit() or len(digits) != digit_count:
        raise OcrError(
            f"vision-LLM at {host} returned an unusable response {digits!r} "
            f"(expected {digit_count} digits)"
        )
    return digits


def load_digit_templates(directory: Path) -> dict[str, list["np.ndarray"]]:
    """Load every reference sample for each digit, not just one.

    A single hand-picked template per digit turned out too fragile in
    practice: the same '9' template that correctly won against one live crop
    lost to '6'/'7'/'4' against a different (equally genuine) crop of a '9'
    minutes later - frame-to-frame glare/contrast/focus variation shifts
    correlation scores enough that no single exemplar generalizes. Keeping a
    growing folder of samples per digit (digit_templates/<label>/*.png - see
    reader.py's per-run digit-slice saving, which is what grows this over
    time) and matching against the *best* of them per label is the standard
    fix: it only takes one good-enough sample to recognize a similar future
    crop, and accuracy improves as more real captures accumulate.

    Falls back to the legacy single-file convention (digit_templates/<label>.png)
    for any label that doesn't have a subdirectory, so existing deployments
    don't lose their templates on upgrade.
    """
    import cv2

    templates: dict[str, list["np.ndarray"]] = {}
    for label in DIGIT_LABELS:
        samples: list["np.ndarray"] = []
        label_dir = directory / label
        if label_dir.is_dir():
            for path in sorted(label_dir.glob("*.png")):
                image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    samples.append(image)
        else:
            legacy_path = directory / f"{label}.png"
            if legacy_path.exists():
                image = cv2.imread(str(legacy_path), cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    samples.append(image)
        if samples:
            templates[label] = samples
    return templates


MIN_TEMPLATE_MATCH_CONFIDENCE = 0.4
"""Normalized cross-correlation (cv2.TM_CCOEFF_NORMED, range -1..1) floor an
ordinary (non-bootstrap) match must clear while the template set is still
incomplete. A crop of a digit that genuinely has no template on file tends
to score lower against every available template than a crop matching its
own template does - this is a heuristic, not a guarantee, which is exactly
why it's allowed to run looser here: on an ordinary run a wrong guess still
has to clear the decrease/implausible-jump sanity checks against the
established baseline before being accepted, so this floor only needs to
catch the worst mismatches, not carry the whole burden. See
MIN_BOOTSTRAP_CONFIDENCE for the reading that has no such backstop.
"""

MIN_BOOTSTRAP_CONFIDENCE = 0.5
"""The stricter floor used instead of MIN_TEMPLATE_MATCH_CONFIDENCE while
bootstrapping (see match_digits' `bootstrap` parameter) - the reading that
seeds last_good has no prior value to sanity-check against, so this is the
only thing standing between a low-confidence wrong guess and a corrupted
baseline that silently blocks every correct reading after it (confirmed
against a real capture: a '1' misread as '4' at ~0.46-0.5 confidence became
the accepted seed value once already, before this distinction existed).
Real correctly-matched sparse glyphs (e.g. '1') have scored as low as 0.46,
so this can still reject a good bootstrap reading and force a retry later -
an acceptable tradeoff, since a delayed baseline is far cheaper than a wrong
one.
"""


def match_digit(crop: "np.ndarray", templates: dict[str, list["np.ndarray"]]) -> tuple[str, float]:
    """Nearest-neighbor match for one digit crop against every sample on file.

    Fallback path for meters whose lowest digit(s) aren't clean static
    7-segment glyphs (ssocr's assumption) - e.g. a partially-visible
    mechanical sweep wheel. No training involved: normalized cross-
    correlation against every reference sample for every label, keeping the
    single best score - see load_digit_templates for why multiple samples
    per label matter. Returns the winning label and its score so callers can
    gate on confidence.
    """
    import cv2

    if not templates:
        raise OcrError("No digit templates loaded for template-match fallback")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    best_label, best_score = "?", float("-inf")
    for label, samples in templates.items():
        for template in samples:
            resized = cv2.resize(template, (gray.shape[1], gray.shape[0]))
            score = float(cv2.matchTemplate(gray, resized, cv2.TM_CCOEFF_NORMED)[0][0])
            if score > best_score:
                best_label, best_score = label, score
    return best_label, best_score


def match_digits(
    crops: Sequence["np.ndarray"],
    templates: dict[str, list["np.ndarray"]],
    *,
    excluded_indexes: Sequence[int] = (),
    low_confidence_ok_indexes: Sequence[int] = (),
    min_confidence: float = MIN_TEMPLATE_MATCH_CONFIDENCE,
    bootstrap: bool = False,
) -> str:
    """Match each digit crop, rounding excluded (e.g. sweep-dial) positions down to 0.

    match_digit only ever returns its best-scoring template, so a missing
    template for the true digit (e.g. no real photo of a '5' yet) could
    silently misclassify it as whichever digit *is* on file - worse than
    failing the run, since a wrong-but-plausible reading can slip past the
    sanity checks. Once the full 0-9 set is on file this can't happen (every
    real digit has its own template), so matches are trusted outright. While
    it's incomplete, only trust a match that clears min_confidence - low
    confidence against every available template is the signature of a crop
    that doesn't belong to any of them, i.e. probably one of the missing
    digits, and rejects the run rather than guessing.

    low_confidence_ok_indexes skips this gate for specific positions (see
    CalibrationConfig) where it protects nothing on an ordinary run - a
    glare-affected position whose *correct* template never scores much
    higher than a wrong one anyway - PROVIDED a verified baseline reading
    already exists to catch a bad guess via the decrease/implausible-jump
    sanity checks. bootstrap=True (no last_good reading yet - this run would
    become the seed every future reading is compared against) disables every
    exemption and enforces min_confidence everywhere: confirmed against a
    real capture, a low-confidence wrong match (a '1' misread as '4') slipped
    through as a bootstrap reading once already, corrupting the baseline and
    silently blocking every subsequent correct reading as an "implausible
    jump" against it - there is no sanity check protecting this one read, so
    it must clear full confidence on every position instead.

    The confidence gate itself must stay active for a bootstrap read even
    once every label 0-9 has a template on file. `complete` only says a
    *correctly-scoring* match won't be misclassified as some other digit for
    lack of an alternative - it says nothing about whether an unrelated or
    blurred crop can still score arbitrarily low against every template.
    Skipping the gate once complete is a fine trade for an ordinary run (the
    sanity checks are the backstop there), but a bootstrap run has no such
    backstop: gating only `not complete and ...` here (an earlier version of
    this function) let a bootstrap run seed a wrong baseline from a
    low-confidence match the instant the template set became complete,
    silently reopening the exact corruption this whole bootstrap/exempt
    scheme exists to prevent.
    """
    excluded = set(excluded_indexes)
    exempt = set() if bootstrap else set(low_confidence_ok_indexes)
    effective_min_confidence = MIN_BOOTSTRAP_CONFIDENCE if bootstrap else min_confidence
    complete = all(label in templates for label in DIGIT_LABELS)
    gate_active = bootstrap or not complete
    digits = []
    for index, crop in enumerate(crops):
        if index in excluded:
            digits.append("0")
            continue
        label, score = match_digit(crop, templates)
        if gate_active and index not in exempt and score < effective_min_confidence:
            reason = (
                f"digit at position {index} best-matched {label!r} with low confidence "
                f"({score:.2f} < {effective_min_confidence})"
            )
            if not complete:
                missing = [label for label in DIGIT_LABELS if label not in templates]
                reason += (
                    f" while the template set is still missing {''.join(missing)} - "
                    f"likely one of those digits, not {label!r}"
                )
            raise OcrError(reason)
        digits.append(label)
    return "".join(digits)


def read_digits(
    image_path: Path,
    digit_crops: Sequence["np.ndarray"],
    calibration: CalibrationConfig,
    *,
    templates_dir: Path | None = None,
    bootstrap: bool = False,
    vlm_host: str | None = None,
    vlm_model: str = DEFAULT_VLM_MODEL,
    vlm_timeout: float = DEFAULT_VLM_TIMEOUT,
) -> str:
    """ssocr (cheap, fast when it works) -> vision LLM (slow, ~2min, but the
    only method that has ever correctly read the glare-obscured digits) ->
    template match (fast, fully offline - last resort if the LLM host is
    unreachable, times out, or vlm_host isn't configured).

    Templates are only loaded from disk if both of the above fail, since the
    common case never needs them. bootstrap is forwarded to match_digits -
    see there for why the reading that establishes the baseline can't use
    the same confidence exemptions as every reading after it.

    The VLM path has no numeric confidence signal to gate on the way
    match_digits does, and it has been confirmed (live) to occasionally
    misread the same glare-affected digit a template-match confidence floor
    would have caught. A single VLM read is fine for an ordinary run - the
    decrease/implausible-jump sanity checks are the backstop - but bootstrap
    has no such backstop, so a bootstrap read requires a second, independent
    VLM call on the same image to agree exactly before it's trusted;
    disagreement falls through to template match (which does enforce full
    confidence on bootstrap - see match_digits) rather than guessing between
    the two answers.
    """
    try:
        digits = run_ssocr(image_path, ssocr_args=calibration.ssocr_args)
        if not digits.isdigit() or len(digits) != calibration.digit_count:
            # ssocr exited 0 but produced something unusable (a partial
            # read, stray characters) - sanity.validate_reading would reject
            # this anyway, but only *after* it's already been given the
            # final answer. Treating it as a failure here instead gives the
            # VLM/template-match tiers below a chance to actually read the
            # crop correctly, rather than every malformed-but-nonempty ssocr
            # hiccup permanently skipping straight to a rejected run.
            raise OcrError(
                f"ssocr returned unusable output {digits!r} "
                f"(expected {calibration.digit_count} numeric digits)"
            )
        return digits
    except OcrError as ssocr_error:
        LOG.warning("ssocr failed (%s)", ssocr_error)

    if vlm_host:
        try:
            digits = read_digits_vlm(
                image_path,
                host=vlm_host,
                digit_count=calibration.digit_count,
                model=vlm_model,
                timeout=vlm_timeout,
            )
            if bootstrap:
                confirmation = read_digits_vlm(
                    image_path,
                    host=vlm_host,
                    digit_count=calibration.digit_count,
                    model=vlm_model,
                    timeout=vlm_timeout,
                )
                if confirmation != digits:
                    raise OcrError(
                        f"vision-LLM bootstrap read is unconfirmed: first call got "
                        f"{digits!r}, a second independent call on the same image got "
                        f"{confirmation!r} - refusing to seed a baseline from a single "
                        f"unconfirmed VLM read"
                    )
            return digits
        except OcrError as vlm_error:
            LOG.warning("vision-LLM fallback failed (%s); falling back to template match", vlm_error)

    if not templates_dir:
        raise OcrError("ssocr failed and no vision-LLM/templates fallback is configured")

    templates = load_digit_templates(templates_dir)
    return match_digits(
        digit_crops,
        templates,
        excluded_indexes=calibration.excluded_digit_indexes,
        low_confidence_ok_indexes=calibration.low_confidence_ok_indexes,
        bootstrap=bootstrap,
    )
