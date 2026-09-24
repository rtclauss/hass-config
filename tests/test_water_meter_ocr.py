from __future__ import annotations

import json
import urllib.error

import pytest

from water_meter import ocr
from water_meter.config import CalibrationConfig


def test_match_digits_rejects_a_low_confidence_match_when_templates_are_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only 0-6 on file; a real '7' or '8' crop scoring low against every
    # available template is the signature of a digit with no template yet.
    templates = {label: object() for label in "0123456"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("0", 0.2))

    with pytest.raises(ocr.OcrError, match="78"):
        ocr.match_digits(["crop"] * 8, templates, min_confidence=0.5)


def test_match_digits_trusts_a_high_confidence_match_even_with_incomplete_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is what lets the reader "go live" before every digit 0-9 has been
    # photographed: a strong match against an on-file template is trusted,
    # and only a weak match (probably one of the still-missing digits) is
    # rejected.
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("3", 0.9))

    result = ocr.match_digits(["crop"] * 4, templates, min_confidence=0.5)

    assert result == "3333"


def test_match_digits_succeeds_with_a_complete_template_set_regardless_of_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    templates = {label: object() for label in ocr.DIGIT_LABELS}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("5", 0.1))

    result = ocr.match_digits(["crop"] * 4, templates, min_confidence=0.5)

    assert result == "5555"


def test_match_digits_skips_matching_entirely_for_excluded_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    templates: dict[str, object] = {}

    def _boom(crop: object, templates: object) -> tuple[str, float]:
        raise AssertionError("match_digit should not be called for excluded positions")

    monkeypatch.setattr(ocr, "match_digit", _boom)

    result = ocr.match_digits(["crop", "crop"], templates, excluded_indexes=(0, 1))

    assert result == "00"


def test_match_digits_trusts_a_low_confidence_match_at_an_exempt_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Position 0 sits under a fixed glare streak where even the *correct*
    # template scores barely higher than a wrong one - no confidence floor
    # can separate them, and a wrong guess there is either right or produces
    # a jump the sanity checks already catch. It should be trusted outright
    # rather than blocking every other, genuinely reliable digit forever.
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("0", 0.2))

    result = ocr.match_digits(
        ["crop"], templates, min_confidence=0.5, low_confidence_ok_indexes=(0,)
    )

    assert result == "0"


def test_match_digits_still_gates_non_exempt_positions_when_others_are_exempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("0", 0.2))

    with pytest.raises(ocr.OcrError, match="position 1"):
        ocr.match_digits(
            ["crop", "crop"], templates, min_confidence=0.5, low_confidence_ok_indexes=(0,)
        )


def test_bootstrap_uses_a_stricter_default_floor_than_an_ordinary_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A score that clears the ordinary-run floor (0.4) but not the bootstrap
    # floor (0.5) must be rejected while bootstrapping and accepted
    # otherwise - callers shouldn't have to pass min_confidence explicitly
    # to get this protection.
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("3", 0.45))

    assert ocr.match_digits(["crop"], templates) == "3"
    with pytest.raises(ocr.OcrError, match="position 0"):
        ocr.match_digits(["crop"], templates, bootstrap=True)


def test_bootstrap_disables_low_confidence_exemptions(monkeypatch: pytest.MonkeyPatch) -> None:
    # A wrong-but-plausible match at an exempt position, on the reading that
    # would become the baseline, has no sanity check to catch it and
    # corrupts every future comparison - confirmed against a real capture.
    # bootstrap=True must enforce min_confidence even at exempt positions.
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("0", 0.2))

    with pytest.raises(ocr.OcrError, match="position 0"):
        ocr.match_digits(
            ["crop"],
            templates,
            min_confidence=0.5,
            low_confidence_ok_indexes=(0,),
            bootstrap=True,
        )


def test_bootstrap_enforces_confidence_even_with_a_complete_template_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression test: a complete 0-9 template set used to disable the
    # confidence gate unconditionally, including for bootstrap reads - a
    # blurred/unrelated crop scoring low against every template could seed
    # last_good_reading.json with a wrong value, with no sanity check able
    # to catch it after the fact. Bootstrap must still gate on confidence
    # even once every label has a template on file.
    templates = {label: object() for label in ocr.DIGIT_LABELS}  # complete
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("4", 0.2))

    with pytest.raises(ocr.OcrError, match="low confidence"):
        ocr.match_digits(["crop"], templates, min_confidence=0.5, bootstrap=True)


def test_bootstrap_still_trusts_a_genuinely_high_confidence_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("0", 0.9))

    result = ocr.match_digits(
        ["crop"], templates, min_confidence=0.5, low_confidence_ok_indexes=(0,), bootstrap=True
    )

    assert result == "0"


def test_match_digits_excluded_position_does_not_need_a_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Position 0 is a sweep-dial that's rounded to 0 regardless - it must not
    # be gated on confidence or force completeness for the other,
    # genuinely-matched positions.
    templates = {label: object() for label in ocr.DIGIT_LABELS if label != "5"}
    monkeypatch.setattr(ocr, "match_digit", lambda crop, templates: ("3", 0.9))

    result = ocr.match_digits(["crop", "crop"], templates, excluded_indexes=(0,))

    assert result == "03"


class _FakeHttpResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_read_digits_vlm_returns_the_digit_string_from_a_successful_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    image_path = tmp_path / "crop.jpg"  # type: ignore[operator]
    image_path.write_bytes(b"fake-jpeg-bytes")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeHttpResponse({"response": "02139879"}),
    )

    result = ocr.read_digits_vlm(image_path, host="truenas.local:30068", digit_count=8)

    assert result == "02139879"


def test_read_digits_vlm_rejects_a_response_with_the_wrong_digit_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    image_path = tmp_path / "crop.jpg"  # type: ignore[operator]
    image_path.write_bytes(b"fake-jpeg-bytes")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: _FakeHttpResponse({"response": "123"})
    )

    with pytest.raises(ocr.OcrError, match="expected 8 digits"):
        ocr.read_digits_vlm(image_path, host="truenas.local:30068", digit_count=8)


def test_read_digits_vlm_rejects_a_non_numeric_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    image_path = tmp_path / "crop.jpg"  # type: ignore[operator]
    image_path.write_bytes(b"fake-jpeg-bytes")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeHttpResponse({"response": "I see 02139879"}),
    )

    with pytest.raises(ocr.OcrError):
        ocr.read_digits_vlm(image_path, host="truenas.local:30068", digit_count=8)


def test_read_digits_vlm_appends_the_hint_to_the_prompt_when_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    image_path = tmp_path / "crop.jpg"  # type: ignore[operator]
    image_path.write_bytes(b"fake-jpeg-bytes")
    captured: dict = {}

    def _fake_urlopen(request: object, timeout: float) -> _FakeHttpResponse:
        captured["body"] = json.loads(request.data)  # type: ignore[attr-defined]
        return _FakeHttpResponse({"response": "02139879"})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ocr.read_digits_vlm(
        image_path,
        host="truenas.local:30068",
        digit_count=8,
        hint="A first read gave 82139879 - look again carefully.",
    )

    assert "look again carefully" in captured["body"]["prompt"]


def test_read_digits_vlm_omits_hint_language_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    image_path = tmp_path / "crop.jpg"  # type: ignore[operator]
    image_path.write_bytes(b"fake-jpeg-bytes")
    captured: dict = {}

    def _fake_urlopen(request: object, timeout: float) -> _FakeHttpResponse:
        captured["body"] = json.loads(request.data)  # type: ignore[attr-defined]
        return _FakeHttpResponse({"response": "02139879"})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ocr.read_digits_vlm(image_path, host="truenas.local:30068", digit_count=8)

    assert captured["body"]["prompt"] == ocr.DEFAULT_VLM_PROMPT.format(digit_count=8)


def test_read_digits_vlm_wraps_a_network_failure_as_ocr_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    image_path = tmp_path / "crop.jpg"  # type: ignore[operator]
    image_path.write_bytes(b"fake-jpeg-bytes")

    def _raise(request: object, timeout: float) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(ocr.OcrError, match="request to truenas.local:30068 failed"):
        ocr.read_digits_vlm(image_path, host="truenas.local:30068", digit_count=8)


def _calibration(**overrides: object) -> CalibrationConfig:
    defaults: dict[str, object] = dict(
        roi=(0, 0, 10, 10),
        digit_boxes=((0, 0, 5, 5),),
        digit_count=1,
        excluded_digit_indexes=(),
        warmup_seconds=0.0,
        frames_to_grab=1,
        frames_to_discard=0,
        max_gallons_per_interval=500.0,
        stuck_after_hours=24.0,
        history_limit=5,
        ssocr_args=(),
    )
    defaults.update(overrides)
    return CalibrationConfig(**defaults)  # type: ignore[arg-type]


def _fail(error: Exception):
    def _raise(*args: object, **kwargs: object) -> None:
        raise error

    return _raise


def test_read_digits_falls_through_when_ssocr_returns_unusable_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    # Regression test: ssocr can exit 0 but still emit something unusable
    # (a partial read, stray characters) - previously read_digits trusted
    # that output outright, so sanity.validate_reading was the only thing
    # that ever caught it, and only after the VLM/template-match tiers had
    # already been skipped entirely.
    monkeypatch.setattr(ocr, "run_ssocr", lambda *a, **k: "1a")  # non-numeric, wrong length too
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda *a, **k: "7")

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(digit_count=1),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
    )

    assert result == "7"


def test_read_digits_trusts_ssocr_output_matching_the_configured_digit_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setattr(ocr, "run_ssocr", lambda *a, **k: "5")
    monkeypatch.setattr(
        ocr, "read_digits_vlm", _fail(AssertionError("should not reach the VLM tier"))
    )

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(digit_count=1),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
    )

    assert result == "5"


def test_read_digits_tries_the_vision_llm_after_ssocr_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setattr(ocr, "run_ssocr", _fail(ocr.OcrError("boom")))
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda *a, **k: "7")
    monkeypatch.setattr(ocr, "match_digits", _fail(AssertionError("should not reach template match")))

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
    )

    assert result == "7"


def test_read_digits_calls_the_vision_llm_only_once_on_an_ordinary_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    # An ordinary (non-bootstrap) run is protected by the decrease/
    # implausible-jump sanity checks downstream, so it must not pay the cost
    # of a second VLM call - only bootstrap needs corroboration.
    monkeypatch.setattr(ocr, "run_ssocr", _fail(ocr.OcrError("boom")))
    calls = []
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda *a, **k: calls.append(1) or "7")

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
        bootstrap=False,
    )

    assert result == "7"
    assert len(calls) == 1


def test_read_digits_bootstrap_trusts_the_vision_llm_when_two_calls_agree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setattr(ocr, "run_ssocr", _fail(ocr.OcrError("boom")))
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda *a, **k: "02139879")
    monkeypatch.setattr(ocr, "match_digits", _fail(AssertionError("should not reach template match")))

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(digit_count=8),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
        bootstrap=True,
    )

    assert result == "02139879"


def test_read_digits_bootstrap_falls_back_to_template_match_when_vision_llm_calls_disagree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    # Regression test: the VLM has no numeric confidence signal to gate on,
    # and has been confirmed live to occasionally misread the same
    # glare-affected digit. A single unconfirmed VLM read must never be
    # allowed to seed last_good_reading.json.
    monkeypatch.setattr(ocr, "run_ssocr", _fail(ocr.OcrError("boom")))
    responses = iter(["02139879", "82139879"])  # disagree on the leading digit
    monkeypatch.setattr(ocr, "read_digits_vlm", lambda *a, **k: next(responses))
    monkeypatch.setattr(ocr, "load_digit_templates", lambda directory: {"9": [object()]})
    monkeypatch.setattr(ocr, "match_digits", lambda *a, **k: "00000000")

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(digit_count=8),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
        bootstrap=True,
    )

    assert result == "00000000"  # fell through to template match, not either VLM answer


def test_read_digits_falls_back_to_template_match_when_the_vision_llm_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setattr(ocr, "run_ssocr", _fail(ocr.OcrError("boom")))
    monkeypatch.setattr(ocr, "read_digits_vlm", _fail(ocr.OcrError("timed out")))
    monkeypatch.setattr(ocr, "load_digit_templates", lambda directory: {"3": [object()]})
    monkeypatch.setattr(ocr, "match_digits", lambda *a, **k: "3")

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
        vlm_host="truenas.local:30068",
    )

    assert result == "3"


def test_read_digits_skips_the_vision_llm_when_no_host_is_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setattr(ocr, "run_ssocr", _fail(ocr.OcrError("boom")))
    monkeypatch.setattr(ocr, "read_digits_vlm", _fail(AssertionError("should not be called")))
    monkeypatch.setattr(ocr, "load_digit_templates", lambda directory: {"3": [object()]})
    monkeypatch.setattr(ocr, "match_digits", lambda *a, **k: "3")

    result = ocr.read_digits(
        tmp_path / "crop.jpg",  # type: ignore[operator]
        ["crop"],
        _calibration(),
        templates_dir=tmp_path / "templates",  # type: ignore[operator]
    )

    assert result == "3"
