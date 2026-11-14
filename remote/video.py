"""Phase 2: the FM27 window as WebRTC video, H.264 from the graphics card (NVENC, else QuickSync, else x264).

The phone sends an offer over the remote-play WebSocket; we answer with one receive-only video track. Frames come
from the same Windows Graphics Capture as the JPEG stream. They're encoded here and handed to aiortc as finished
packets, so aiortc only packetises them (its own encoder is software x264 at 720p-ish levels).

No STUN/TURN: it's for the home network or Tailscale, so the PC's own addresses are all the phone needs, and
nothing is sent to outside servers.
"""
from __future__ import annotations

import asyncio
import fractions
import threading
import time

import av
from aiortc.mediastreams import MediaStreamError
from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCRtpSender, RTCSessionDescription

from .capture import Capturer

FPS = 60
REFRESH_S = 1.0                 # resend the picture at least this often when nothing moves (keeps quality settling)
KEYFRAME_S = 4.0                # a full picture this often anyway, so a lost packet never freezes the view for long
CLOCK = fractions.Fraction(1, 90000)
BITRATES = {"high": 16_000_000, "normal": 10_000_000, "low": 5_000_000}

# Low-latency settings per encoder. Baseline profile: that's what phones' WebRTC H.264 offers (42e01f).
ENCODERS = [
    ("h264_nvenc", "bgra", {"preset": "p2", "tune": "ull", "rc": "cbr", "zerolatency": "1", "delay": "0",
                            "bf": "0", "profile": "baseline", "forced-idr": "1"}),
    ("h264_qsv", "nv12", {"preset": "veryfast", "look_ahead": "0", "async_depth": "1", "profile": "baseline"}),
    ("libx264", "yuv420p", {"preset": "ultrafast", "tune": "zerolatency", "profile": "baseline"}),
]


def open_encoder(width: int, height: int, bitrate: int) -> tuple[av.CodecContext, str]:
    """The first H.264 encoder that opens at this size: NVENC (RTX), QuickSync (Intel), then software."""
    errors = []
    for name, pix, opts in ENCODERS:
        try:
            c = av.CodecContext.create(name, "w")
            c.width, c.height, c.pix_fmt = width, height, pix
            c.time_base, c.framerate = CLOCK, fractions.Fraction(FPS, 1)
            c.bit_rate = bitrate
            c.options = {**opts, "maxrate": str(bitrate), "bufsize": str(bitrate // 2), "g": str(int(FPS * KEYFRAME_S))}
            c.open()
            return c, name
        except Exception as e:  # noqa: BLE001  (missing driver/GPU, odd size …)
            errors.append(f"{name}: {e}")
    raise RuntimeError("No H.264 encoder opened: " + "; ".join(errors))


class Encoder:
    """One H.264 encoder for every phone watching (a GPU only allows a few NVENC sessions at once).

    A thread starts with the first viewer and stops, freeing the encoder, when the last one leaves. Each viewer's
    track gets every packet; if one falls behind, its backlog is dropped and everyone gets a keyframe.
    """

    def __init__(self, capturer: Capturer, bitrate: int = BITRATES["normal"]):
        self.cap = capturer
        self.bitrate = bitrate
        self.lock = threading.Lock()
        self.tracks: set[ScreenTrack] = set()
        self.thread: threading.Thread | None = None
        self.keyframe = True
        self.name = ""
        self.sent = self.bytes = 0
        self.encode_s = 0.0

    def subscribe(self, track: "ScreenTrack") -> None:
        with self.lock:
            self.tracks.add(track)
            self.keyframe = True
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name="remote-video")
                self.thread.start()

    def unsubscribe(self, track: "ScreenTrack") -> None:
        with self.lock:
            self.tracks.discard(track)

    def request_keyframe(self) -> None:
        self.keyframe = True

    def stats(self) -> dict:
        n = max(1, self.sent)
        return {"encoder": self.name, "frames": self.sent, "kb_per_frame": round(self.bytes / n / 1024, 1),
                "encode_ms": round(self.encode_s / n * 1000, 1)}

    def _run(self) -> None:
        codec, size, seq, last, t0 = None, (0, 0), 0, 0.0, time.monotonic()
        try:
            while True:
                with self.lock:
                    if not self.tracks:
                        self.thread = None              # under the lock, so a new viewer starts a fresh thread
                        return
                    tracks = list(self.tracks)
                    key, self.keyframe = self.keyframe, False   # a viewer joining after this gets the next one
                wait = last + 1 / FPS - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                frame = self.cap.wait_newer(seq, REFRESH_S) or self.cap.frame   # resend now and then when still
                if frame is None:                       # FM27 isn't running
                    time.sleep(0.25)
                    continue
                seq = frame.seq
                t1 = time.perf_counter()
                if codec is None or (frame.width, frame.height) != size:
                    codec = None                        # PyAV frees an encoder when it's no longer referenced
                    codec, self.name = open_encoder(frame.width, frame.height, self.bitrate)
                    size, key = (frame.width, frame.height), True
                    print(f"[remote] video: {self.name} {frame.width}x{frame.height} "
                          f"at {self.bitrate // 1_000_000} Mbit/s")
                vf = to_video_frame(frame)
                if codec.pix_fmt != "bgra":
                    vf = vf.reformat(format=codec.pix_fmt)
                vf.pts, vf.time_base = int((time.monotonic() - t0) * 90000), CLOCK
                vf.pict_type = av.video.frame.PictureType.I if key else av.video.frame.PictureType.NONE
                data = b"".join(bytes(p) for p in codec.encode(vf))
                last = time.monotonic()
                self.encode_s += time.perf_counter() - t1
                if not data:
                    continue
                self.sent += 1
                self.bytes += len(data)
                for t in tracks:
                    if not t.push(data, vf.pts):
                        self.keyframe = True            # that phone lost frames: a full picture puts it right
        except Exception as e:  # noqa: BLE001
            print(f"[remote] video encoder stopped: {e}")
            with self.lock:
                self.thread = None
                dead = list(self.tracks)
            for t in dead:
                t.push(None, 0)                         # ends their tracks; the phones fall back to pictures
        finally:
            codec = None


def to_video_frame(frame) -> av.VideoFrame:
    vf = av.VideoFrame(frame.width, frame.height, "bgra")
    plane = vf.planes[0]
    if plane.line_size == frame.width * 4:
        plane.update(frame.bgra)
    else:                                            # padded rows: copy row by row
        import numpy as np
        src = np.frombuffer(frame.bgra, np.uint8).reshape(frame.height, frame.width * 4)
        dst = np.frombuffer(plane, np.uint8).reshape(frame.height, plane.line_size)
        dst[:, : frame.width * 4] = src
    return vf


class ScreenTrack(MediaStreamTrack):
    """One phone's view of the shared encoder: already-encoded H.264 packets."""
    kind = "video"
    BACKLOG = 20

    def __init__(self, encoder: Encoder):
        super().__init__()
        self.encoder = encoder
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue = asyncio.Queue()
        encoder.subscribe(self)

    def push(self, data: bytes | None, pts: int) -> bool:
        """From the encoder thread. False when this phone was too far behind and its backlog was dropped."""
        if self.readyState != "live":
            return True
        behind = self.queue.qsize() >= self.BACKLOG
        self.loop.call_soon_threadsafe(self._put, data, pts, behind)
        return not behind

    def _put(self, data, pts, behind) -> None:
        if behind:
            while not self.queue.empty():
                self.queue.get_nowait()
        self.queue.put_nowait((data, pts))

    async def recv(self) -> av.Packet:
        if self.readyState != "live":
            raise MediaStreamError
        data, pts = await self.queue.get()
        if data is None:
            self.stop()
            raise MediaStreamError
        packet = av.Packet(data)
        packet.pts, packet.time_base = pts, CLOCK
        return packet

    def stop(self) -> None:
        self.encoder.unsubscribe(self)
        super().stop()


class VideoSession:
    """One phone's WebRTC connection."""

    def __init__(self, encoder: Encoder):
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.track = ScreenTrack(encoder)

    async def answer(self, sdp: str, kind: str) -> dict:
        # The transceiver must exist, H.264 only, before the offer is applied: aiortc settles the codecs then, and
        # would otherwise pick VP8 first and wrap our H.264 packets as VP8 (which the phone can't decode).
        transceiver = self.pc.addTransceiver(self.track, direction="sendonly")
        caps = RTCRtpSender.getCapabilities("video").codecs
        transceiver.setCodecPreferences([c for c in caps if c.mimeType.lower() in ("video/h264", "video/rtx")])
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
        if not any(c.mimeType.lower() == "video/h264" for c in transceiver._codecs):
            raise ValueError("This phone's browser didn't offer H.264 video.")
        sender = transceiver.sender
        plain = sender._send_keyframe                      # the phone asks for a full picture (PLI/FIR) …

        def keyframe():
            plain()
            self.track.encoder.request_keyframe()          # … which our encoder makes, not aiortc's

        sender._send_keyframe = keyframe
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        return {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}

    async def close(self) -> None:
        self.track.stop()
        await self.pc.close()
