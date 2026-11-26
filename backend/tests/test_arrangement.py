from app.services import arrangement

LYRICS = "[Intro]\n\n[Verse 1]\nедно две три\nчетири пет\n\n[Chorus]\nой ракийо люта\n\n[Verse 2]\nшест седем\n\n[Chorus]\nой ракийо люта\n\n[Outro]\nкрай"


def _words(text_times):
    out = []
    for text, start in text_times:
        for i, word in enumerate(text.split()):
            out.append({"start": start + i * 0.4, "end": start + i * 0.4 + 0.35, "word": word})
    return out


def test_parse_lyrics_sections_and_lines():
    sections, lines = arrangement.parse_lyrics(LYRICS)
    assert [s["label"] for s in sections] == ["Intro", "Verse 1", "Chorus", "Verse 2", "Chorus", "Outro"]
    assert [line["section"] for line in lines] == [1, 1, 2, 3, 4, 5]


def test_alignment_keeps_order_when_first_chorus_is_missed():
    # The singer skips the first chorus; the second must not be stolen by line 3.
    words = _words([("едно две три", 10), ("четири пет", 12), ("шест седем", 30), ("ой ракийо люта", 40), ("край", 50)])
    timed = arrangement.align_lyrics(LYRICS, words, 60)
    by_text = [(line["text"], line["heard"], line["start"]) for line in timed]
    assert by_text[0] == ("едно две три", True, 10)
    assert by_text[2][1] is False and 12 < by_text[2][2] < 30  # interpolated between verse 1 and verse 2
    assert by_text[3] == ("шест седем", True, 30)
    assert by_text[4] == ("ой ракийо люта", True, 40)


def test_spans_tile_the_song_and_duet_defaults():
    words = _words([("едно две три", 10), ("четири пет", 12), ("ой ракийо люта", 20), ("шест седем", 30), ("ой ракийо люта", 40), ("край", 50)])
    timed = arrangement.align_lyrics(LYRICS, words, 60)
    spans = arrangement.section_spans(LYRICS, timed, 60)
    assert spans[0]["start"] == 0.0 and spans[-1]["end"] == 60
    assert all(a["end"] == b["start"] for a, b in zip(spans, spans[1:]))
    parts = arrangement.default_parts(spans, duet=True)
    assert parts == {1: "A", 2: "AB", 3: "B", 4: "AB", 5: "AB"}


def test_plan_layers_for_duet_and_choir(tmp_path):
    spans = [{"index": 0, "start": 0.0, "end": 10.0}, {"index": 1, "start": 10.0, "end": 20.0}, {"index": 2, "start": 20.0, "end": 30.0}]
    converted = {"A": tmp_path / "a.wav", "B": tmp_path / "b.wav"}
    layers = arrangement.plan_layers(spans=spans, parts={0: "A", 1: "AB", 2: "choir"}, converted=converted, original=tmp_path / "o.wav")
    solo = [layer for layer in layers if layer["path"].endswith("a.wav") and layer["gain_db"] == 0.0 and "delay_ms" not in layer]
    assert solo[0]["segments"] == [(0.0, 10.0)]
    together = [layer for layer in layers if layer["gain_db"] == -3.0]
    assert {layer["path"][-5:] for layer in together} == {"a.wav", "b.wav"}
    choir = [layer for layer in layers if "delay_ms" in layer]
    assert len(choir) == 6 and all(layer["segments"] == [(20.0, 30.0)] for layer in choir)
    assert {layer["path"][-5:] for layer in choir} == {"a.wav", "b.wav", "o.wav"}


def test_is_chorus_skips_pre_and_post_chorus():
    assert arrangement.is_chorus("Chorus") and arrangement.is_chorus("Chorus 2") and arrangement.is_chorus("Припев")
    assert not arrangement.is_chorus("Pre-Chorus") and not arrangement.is_chorus("Post-Chorus") and not arrangement.is_chorus("Verse 1")
