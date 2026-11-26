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


def test_line_overrides_carve_section_spans():
    spans = [{"index": 0, "start": 0.0, "end": 20.0}, {"index": 1, "start": 20.0, "end": 40.0}]
    timed = [{"start": 5.0, "end": 8.0}, {"start": 10.0, "end": 13.0}, {"start": 25.0, "end": 28.0}]
    pieces, parts = arrangement.apply_line_parts(spans, {0: "A", 1: "AB"}, timed, {1: "B"})
    assert [(p["start"], p["end"], parts[p["index"]]) for p in pieces] == [(0.0, 9.8, "A"), (9.8, 13.2, "B"), (13.2, 20.0, "A"), (20.0, 40.0, "AB")]


def test_key_parsing_and_diatonic_thirds_stay_in_key():
    tonic, scale = arrangement.parse_key("D minor")
    assert tonic == 2 and scale == [2, 4, 5, 7, 9, 10, 0]
    # D->F, E->G, F->A, G->Bb, A->C, Bb->D, C->E in D minor
    assert [arrangement.diatonic_shift(m, scale, 2) for m in (62, 64, 65, 67, 69, 70, 72)] == [3, 3, 4, 3, 3, 4, 4]
    assert arrangement.parse_key("F# major")[0] == 6 and arrangement.parse_key("Bbm")[1][2] == 1 and arrangement.parse_key("") is None


def test_harmony_segments_group_by_shift_and_intersect():
    key = arrangement.parse_key("C major")
    groups = arrangement.harmony_segments([[0.0, 1.0, 60], [1.02, 2.0, 64], [2.5, 3.0, 62]], key, "third")
    assert groups == {4: [(0.0, 1.0)], 3: [(1.02, 2.0), (2.5, 3.0)]}  # C->E major third, E->G and D->F minor thirds
    assert arrangement.intersect([(1.02, 2.0), (2.5, 3.0)], [(1.5, 2.7)]) == [(1.5, 2.0), (2.5, 2.7)]
