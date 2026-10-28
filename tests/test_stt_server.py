from m8py.stt_server import keep_hotword


def test_keep_hotword_takes_only_one_word_swaps():
    assert keep_hotword("Hey Jebby.", "Hey Kevin.", "Kevin") == "Hey Kevin."
    assert keep_hotword("Devin, you see that?", "Kevin, you see that?", "Kevin") == (
        "Kevin, you see that?"
    )
    # beam search changed a different word: keep the plain transcript
    assert keep_hotword("Cover.", "Okay.", "Kevin") == "Cover."
    # inserted names are hotword artifacts, not swaps
    assert keep_hotword("growing longer.", "Kevin Kevin growing longer.", "Kevin") == (
        "growing longer."
    )
    assert keep_hotword("Yeah, I'm careful.", "Kevin Kevin.", "Kevin") == "Yeah, I'm careful."
