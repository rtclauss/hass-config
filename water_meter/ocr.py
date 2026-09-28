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


DEFAULT_VLM_MODEL = "qwen2.5vl:7b"
"""Switched from qwen3-vl:4b 2026-09-20 after a head-to-head comparison
against real captures (see the "Reading Through Glare" report and
[[vlm_ocr_experiment]] project memory): with the 6-shot prompt below,
qwen2.5vl:7b held 100% exact-match across two independent held-out sets
(6, then 12 real captures never used as examples) and got faster, not
slower, as more examples were added. qwen3-vl:4b topped out at 40% on the
same captures; minicpm-v:8b (the next-best alternative) improved with 4
examples but regressed with 6, producing answers that looked like blends
of the few-shot examples rather than genuine reads of the query image.
"""

VLM_EXAMPLES_DIR = Path(__file__).parent / "vlm_examples"

VLM_FEWSHOT_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("example_1_02138978.jpg", "02138978"),
    ("example_2_02139768.jpg", "02139768"),
    ("example_3_02140095.jpg", "02140095"),
    ("example_4_02140333.jpg", "02140333"),
    ("example_5_02147134.jpg", "02147134"),
    ("example_6_02140226.jpg", "02140226"),
)
"""Real captures of this exact meter, each with its true reading confirmed
by direct visual inspection (not by any model's output). Sent as in-context
examples on every VLM call, ahead of the actual query image, since the
glare pattern is fixed - same light, same angle, same meter every time -
so showing the model real examples of how this specific display's glare
looks worked far better than just wording the zero-shot prompt more
strictly (which was tried first and made accuracy *worse*, not better -
see the report). Anchored to the meter's current 02141xxx.x value range;
will need refreshing once the leading digits roll over past "021".

example_5 was originally a second 02138978 photo - byte-different from
example_1 but the same digit string, adding real-world photo variety but
teaching the model nothing about any digit it hadn't already seen. A
2026-09-28 golden-set regression run (water_meter/eval.py,
water_meter/golden_set/ - 16 diverse real captures, visually verified)
found the production model scored only 2/16 (12%) exact-match, with 12 of
the 14 misses sharing one specific error: digit position 3 read as "1" or
"0" whenever its true value was "7" (the same position correctly reads "6"
and "8" without issue) - and a second, differently-trained model
(qwen3-vl:30b-a3b-instruct) hit the identical failure, which rules out
"this model is just bad at this" and points at a real few-shot coverage
gap instead: none of the 6 original examples happen to contain a "7" at
that position. Swapping the redundant example_5 for a real "7134" capture
took the same qwen2.5vl:7b model from 2/16 to 7/16 in isolation, and to
12/16 (75%) when tested with three diverse "7"-position examples via the
dynamic-few-shot mechanism (see load_dynamic_examples) - strong evidence
this is a coverage problem, not a model-quality one. Only one slot was
swapped here (not three) to keep this static set's context-budget cost
unchanged; the dynamic mechanism is the intended path for feeding in
further real corrected examples over time without bloating every call.
"""

DEFAULT_VLM_TIMEOUT = 480.0
"""Originally set against truenas.local:30068's qwen3-vl:4b running
CPU-only, where latency was highly variable, not just slow: one measured
call took 123.9s total_duration with only 48.4s of that in eval_duration
(token generation) plus 0.27s prompt_eval - Ollama's own accounting didn't
explain the remaining ~75s gap. A 240s timeout was tried and confirmed too
short in production: a live run hit that cutoff, then /api/ps showed the
same generation had kept running server-side and completed anyway past the
client's cutoff. An RTX 2000 Ada was later added to that box, and calls
dropped to single-digit seconds through ~30s in the common case - but 480s
is kept as the timeout regardless, both as a margin for occasional slow
calls and because the box has had repeated unrelated Ollama outages
(service restarts, updates) that make "it's GPU-backed now" not a safe
excuse to shrink the safety margin. See the service's TimeoutStartSec,
which must stay above this.
"""

DEFAULT_DYNAMIC_FEWSHOT_LIMIT = 3
"""Cap on how many human-corrected examples get appended to the static
6-shot prompt (see load_dynamic_examples). Each image costs real context
budget - 6 static examples + 1 query already run ~7-8k tokens against the
16384 num_ctx (see DEFAULT_VLM_NUM_CTX), so this stays small enough to
leave headroom rather than chasing every available correction.
"""


def load_dynamic_examples(
    directory: Path | None, limit: int = DEFAULT_DYNAMIC_FEWSHOT_LIMIT
) -> tuple[tuple[Path, str], ...]:
    """Load the most recent human-corrected (image, digits) pairs, if any.

    directory is correction_listener.py's rolling human_corrections folder -
    every time a person approves/modifies a reading via the actionable
    notification, that crop and its confirmed-correct digit string get
    saved there. Feeding a handful of these back into the prompt as
    additional few-shot examples is the mechanism for "learning" from a
    correction without retraining anything: they're real captures of this
    display, at its current value range, confirmed correct by a human who
    looked at the actual crop - a stronger signal than any of this
    project's other feedback loops.

    Missing directory/index (no corrections yet, or the feature unused)
    returns an empty tuple - dynamic examples are additive, never required.
    """
    if directory is None:
        return ()
    index_path = directory / "index.json"
    if not index_path.exists():
        return ()
    try:
        import json as json_module

        entries = json_module.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(entries, list):
        return ()

    examples = []
    for entry in entries[-limit:]:
        try:
            file_name = str(entry["file"])
            digits = str(entry["digits"])
        except (KeyError, TypeError):
            continue
        path = directory / file_name
        if path.exists():
            examples.append((path, digits))
    return tuple(examples)


def _build_vlm_fewshot_prompt(
    digit_count: int, dynamic_examples: tuple[tuple[Path, str], ...] = ()
) -> str:
    all_readings = [reading for _, reading in VLM_FEWSHOT_EXAMPLES] + [
        reading for _, reading in dynamic_examples
    ]
    lines = [
        "You are reading a water meter's LCD digit display. The first "
        f"{len(all_readings)} images below are examples from this "
        f"exact same display, each labeled with its correct {digit_count}-digit "
        "reading, including any leading zeros:",
        "",
    ]
    for i, reading in enumerate(all_readings, 1):
        lines.append(f"Example {i} reading: {reading}")
    lines += [
        "",
        "The leftmost 2-3 digits are frequently crossed by a bright glare "
        "band that can distort their shape. Look carefully through the "
        "glare rather than guessing - and note that these leftmost (most "
        "significant) digits change extremely rarely, often staying "
        "identical across many consecutive readings, unlike the digits "
        "further right which change more often.",
        "",
        "The final image is a new reading from the same display. Using the "
        "examples above as a guide to this display's digit shapes and "
        f"lighting, read the {digit_count}-digit number shown in the final "
        f"image. Respond with exactly {digit_count} digits and nothing else "
        "- no spaces, punctuation, or extra text.",
    ]
    return "\n".join(lines)


DEFAULT_VLM_NUM_THREAD = 2
"""Caps the CPU threads Ollama uses per call, even though qwen3-vl:4b now
runs GPU-resident (an RTX 2000 Ada was added to the TrueNAS box). GPU
offload doesn't cover everything - image preprocessing/tokenization still
runs on CPU, and Ollama defaults to using every core for it. That default
was enough to re-trigger the box's CPU thermal alarm (the same alarm that
originally motivated widening the timer's OnUnitActiveSec), even with
inference itself fast and GPU-bound. 2 threads trades a little latency on
the CPU-side portion for not cooking the box.
"""

DEFAULT_VLM_NUM_CTX = 16384
"""Ollama defaults every model's context to 4096 tokens regardless of what
the model itself supports. The 6-shot prompt sends 7 images per call (6
reference examples + the query crop) and blew straight through that
default with a hard 400 "exceed_context_size_error" the first time it was
tried (5 images alone was already 5427 tokens). 16384 gives real headroom
above the ~7-8k tokens 7 small images plus prompt text actually need.
"""


def read_digits_vlm(
    image_path: Path,
    *,
    host: str,
    digit_count: int,
    model: str = DEFAULT_VLM_MODEL,
    timeout: float = DEFAULT_VLM_TIMEOUT,
    num_thread: int = DEFAULT_VLM_NUM_THREAD,
    num_ctx: int = DEFAULT_VLM_NUM_CTX,
    hint: str | None = None,
    dynamic_examples_dir: Path | None = None,
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

    Sends VLM_FEWSHOT_EXAMPLES ahead of image_path itself, in order, so the
    model sees real labeled examples of this exact display before being
    asked to read a new one - see VLM_FEWSHOT_EXAMPLES for why this beats a
    more strictly-worded zero-shot prompt.

    hint appends extra context to the prompt - used by reader.py's requery
    path to tell the model a first read produced an implausible value and
    ask it to look again, rather than re-asking the identical question and
    hoping sampling variance alone fixes it.
    """
    import base64
    import json as json_module
    import urllib.error
    import urllib.request

    dynamic_examples = load_dynamic_examples(dynamic_examples_dir)
    prompt = _build_vlm_fewshot_prompt(digit_count, dynamic_examples)
    if hint:
        prompt = f"{prompt} {hint}"
    example_images = [
        base64.b64encode((VLM_EXAMPLES_DIR / filename).read_bytes()).decode("ascii")
        for filename, _ in VLM_FEWSHOT_EXAMPLES
    ]
    dynamic_images = [
        base64.b64encode(path.read_bytes()).decode("ascii") for path, _ in dynamic_examples
    ]
    query_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [*example_images, *dynamic_images, query_image],
        "stream": False,
        "options": {"num_thread": num_thread, "num_ctx": num_ctx},
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
    dynamic_examples_dir: Path | None = None,
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
                dynamic_examples_dir=dynamic_examples_dir,
            )
            if bootstrap:
                confirmation = read_digits_vlm(
                    image_path,
                    host=vlm_host,
                    digit_count=calibration.digit_count,
                    model=vlm_model,
                    timeout=vlm_timeout,
                    dynamic_examples_dir=dynamic_examples_dir,
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
