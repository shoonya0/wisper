"""capture.list_sources: the Windows default device comes first (no audio device needed)."""

import capture

CABLE    = {"index": 22, "name": "CABLE Input (VB-Audio Virtual Cable) [Loopback]"}
SPEAKERS = {"index": 24, "name": "Speakers (4- High Definition Audio Device) [Loopback]"}


class FakePa:
    """Loopback devices as pyaudiowpatch reports them on this PC (2026-10-11)."""

    def __init__(self, default_loopback):
        self.default_loopback = default_loopback

    def get_loopback_device_info_generator(self):
        return iter([dict(CABLE), dict(SPEAKERS)])

    def get_default_wasapi_loopback(self):
        if self.default_loopback is None:
            raise LookupError("no default loopback")
        return dict(self.default_loopback)

    def get_host_api_info_by_type(self, _type):
        # The default *output* index (here 5) is the speaker endpoint, not its loopback twin
        # (24): matching on it never moved the default to the top.
        return {"defaultOutputDevice": 5, "defaultInputDevice": 1}


def test_loopback_puts_the_windows_default_speakers_first():
    labels = [d["label"] for d in capture.list_sources(FakePa(SPEAKERS), "loopback")]
    assert labels == ["Speakers (4- High Definition Audio Device)", "CABLE Input (VB-Audio Virtual Cable)"]


def test_loopback_without_a_default_keeps_device_order():
    labels = [d["label"] for d in capture.list_sources(FakePa(None), "loopback")]
    assert labels == ["CABLE Input (VB-Audio Virtual Cable)", "Speakers (4- High Definition Audio Device)"]
