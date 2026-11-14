"""Remote play video (Phase 2): the shared encoder and the WebRTC answer, without FM27 or a phone."""
import asyncio
import time

import pytest

pytest.importorskip("aiortc")
from remote import video  # noqa: E402


class FakeFrame:
    def __init__(self, w=320, h=200, seq=1):
        self.width, self.height, self.seq = w, h, seq
        self.bgra = bytes([40, 80, 160, 255]) * (w * h)


class FakeCapturer:
    def __init__(self):
        self.frame = FakeFrame()

    def wait_newer(self, seq, timeout):
        if self.frame.seq > seq:
            return self.frame
        time.sleep(min(timeout, 0.05))
        return None


def nal_types(data: bytes) -> set[int]:
    return {data[i + 3] & 0x1F for i in range(len(data) - 3) if data[i:i + 3] == b"\x00\x00\x01"}


def test_shared_encoder_feeds_every_viewer_and_stops_when_they_leave():
    async def run():
        enc = video.Encoder(FakeCapturer(), bitrate=1_000_000)
        a, b = video.ScreenTrack(enc), video.ScreenTrack(enc)
        pa = await asyncio.wait_for(a.recv(), 10)
        pb = await asyncio.wait_for(b.recv(), 10)
        thread = enc.thread
        a.stop()
        b.stop()
        for _ in range(100):                       # the thread notices nobody's watching and frees the encoder
            if enc.thread is None:
                break
            await asyncio.sleep(0.05)
        return pa, pb, thread, enc

    pa, pb, thread, enc = asyncio.run(run())
    first = bytes(pa)
    assert first.startswith(b"\x00\x00\x00\x01") or first.startswith(b"\x00\x00\x01")   # Annex B, as aiortc expects
    assert {7, 5} <= nal_types(first)                                                  # SPS + IDR picture
    assert 5 in nal_types(bytes(pb)) and pa.time_base == video.CLOCK                   # a late joiner starts on a full picture
    assert enc.thread is None and not thread.is_alive()
    assert enc.name in {name for name, _, _ in video.ENCODERS}


def test_answer_offers_only_h264():
    async def run():
        offer_pc = video.RTCPeerConnection()
        offer_pc.addTransceiver("video", direction="recvonly")
        await offer_pc.setLocalDescription(await offer_pc.createOffer())
        session = video.VideoSession(video.Encoder(FakeCapturer()))
        answer = await session.answer(offer_pc.localDescription.sdp, "offer")
        await session.close()
        await offer_pc.close()
        return answer

    answer = asyncio.run(run())
    assert answer["type"] == "answer"
    rtpmaps = [l for l in answer["sdp"].splitlines() if l.startswith("a=rtpmap:")]
    assert rtpmaps and all("H264" in l or "rtx" in l for l in rtpmaps)
    assert "a=sendonly" in answer["sdp"]
