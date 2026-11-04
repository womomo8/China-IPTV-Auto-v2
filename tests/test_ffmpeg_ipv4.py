
import json
import shutil
import subprocess

import pytest

from iptv_auto import content_check, deep_probe
from iptv_auto.ffmpeg_ipv4 import ffmpeg_ipv4_input_options


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/live.ts",
        "https://example.com/live.m3u8",
        "rtmp://example.com/live/stream",
    ],
)
def test_supported_tcp_protocols_use_ipv4_binding(url):
    assert ffmpeg_ipv4_input_options(url) == [
        "-local_addr",
        "0.0.0.0",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "rtsp://example.com/live",
        "udp://example.com:5004",
        "rtp://example.com:5004",
        "file:///tmp/video.ts",
    ],
)
def test_unsupported_protocols_are_not_claimed_as_ipv4(url):
    assert ffmpeg_ipv4_input_options(url) is None


def test_deep_probe_uses_ipv4_for_both_ffmpeg_tools(monkeypatch):
    commands = []

    probe_data = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "25/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
        "format": {
            "duration": "10",
        },
    }

    def fake_run_command(command, *, timeout_seconds):
        commands.append(command)
        return (
            0,
            json.dumps(probe_data),
            "",
            "completed",
        )

    def fake_bounded_decode(command, *, timeout_seconds):
        commands.append(command)
        return (
            0,
            deep_probe.MIN_DECODED_BYTES,
            "byte_limit_reached",
        )

    monkeypatch.setattr(
        deep_probe,
        "_run_command",
        fake_run_command,
    )
    monkeypatch.setattr(
        deep_probe,
        "_run_bounded_decode",
        fake_bounded_decode,
    )

    result = deep_probe._probe_one(
        channel_id="channel-a",
        line_id="line-a",
        url="https://example.com/live.m3u8",
        headers={},
        ffprobe_binary="ffprobe",
        ffmpeg_binary="ffmpeg",
        timeout_seconds=5,
    )

    assert result.status == "passed"
    assert len(commands) == 2

    for command in commands:
        index = command.index("-local_addr")
        assert command[index + 1] == "0.0.0.0"
        assert command.index("-local_addr") < command.index("-i")


def test_rtsp_deep_probe_is_unknown_without_running_tools(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail("RTSP 不应该启动未经IPv4保证的检测")

    monkeypatch.setattr(
        deep_probe,
        "_run_command",
        unexpected_call,
    )
    monkeypatch.setattr(
        deep_probe,
        "_run_bounded_decode",
        unexpected_call,
    )

    result = deep_probe._probe_one(
        channel_id="channel-a",
        line_id="line-a",
        url="rtsp://example.com/live",
        headers={},
        ffprobe_binary="ffprobe",
        ffmpeg_binary="ffmpeg",
        timeout_seconds=5,
    )

    assert result.status == "unknown"
    assert (
        result.evidence["result_reason"]
        == "ipv4_transport_not_enforceable_for_protocol"
    )


def test_content_frame_extraction_uses_ipv4(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"fake-png",
            stderr=b"",
        )

    monkeypatch.setattr(
        content_check.subprocess,
        "run",
        fake_run,
    )

    frame, state = content_check._extract_frame(
        "ffmpeg",
        "https://example.com/live.ts",
        {},
        1,
    )

    assert frame == b"fake-png"
    assert state == "ok"

    command = captured["command"]
    index = command.index("-local_addr")

    assert command[index + 1] == "0.0.0.0"
    assert index < command.index("-i")


def test_content_frame_refuses_rtsp_without_ipv4_guarantee(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail("RTSP 不应该启动OCR抽帧")

    monkeypatch.setattr(
        content_check.subprocess,
        "run",
        unexpected_call,
    )

    frame, state = content_check._extract_frame(
        "ffmpeg",
        "rtsp://example.com/live",
        {},
        1,
    )

    assert frame is None
    assert state == "ipv4_transport_not_enforceable"


def test_installed_ffmpeg_supports_tcp_local_addr():
    binary = shutil.which("ffmpeg")

    if not binary:
        pytest.skip("当前环境没有安装 ffmpeg")

    result = subprocess.run(
        [
            binary,
            "-hide_banner",
            "-h",
            "protocol=tcp",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert "-local_addr" in (
        result.stdout + result.stderr
    )
