from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
import os

@dataclass
class Signature:
    name: str
    magic: bytes
    extension: str
    offset: int = 0

@dataclass
class CarveHit:
    offset: int
    signature: Signature
    size: int = 0
    path: Optional[Path] = None
    valid: Optional[bool] = None

SIGNATURES = [
    Signature("Imou/Dahua DHAV", b"DHAV", ".dav"),
    Signature("MP4", b"ftyp", ".mp4", -4),
    Signature("AVI", b"RIFF", ".avi"),
    Signature("MPEG transport stream", b"\x47\x40\x00", ".ts"),
    Signature("Matroska", b"\x1a\x45\xdf\xa3", ".mkv"),
]

class DeepCarver:
    """Read-only signature scanner for a disk image or block device."""
    def __init__(self, source: str, chunk_size: int = 4 * 1024 * 1024,
                 max_clip_mb: int = 512):
        self.source = source
        self.chunk_size = max(256 * 1024, chunk_size)
        self.max_clip_bytes = max(1, max_clip_mb) * 1024 * 1024
        self.cancelled = False

    def stop(self):
        self.cancelled = True

    def source_size(self) -> int:
        return os.path.getsize(self.source)

    def scan(self, output_dir: str, progress: Optional[Callable] = None,
             validate: bool = False, export_playable_only: bool = False):
        total = self.source_size()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        hits = []
        overlap = max(len(s.magic) for s in SIGNATURES) + 8
        carry = b""
        pos = 0
        seen = set()

        with open(self.source, "rb", buffering=0) as fh:
            while pos < total and not self.cancelled:
                block = fh.read(min(self.chunk_size, total - pos))
                if not block:
                    break
                window = carry + block
                base = pos - len(carry)

                for sig in SIGNATURES:
                    start = 0
                    while True:
                        idx = window.find(sig.magic, start)
                        if idx < 0:
                            break
                        absolute = base + idx + sig.offset
                        if absolute >= 0 and absolute not in seen:
                            seen.add(absolute)
                            hits.append(CarveHit(absolute, sig))
                        start = idx + 1

                pos += len(block)
                carry = window[-overlap:]
                if progress:
                    progress(pos, total, len(hits))

        # Sort by byte offset and carve each candidate up to the next
        # recognized header or the configured safety cap.
        hits.sort(key=lambda h: h.offset)
        for i, hit in enumerate(hits):
            if self.cancelled:
                break
            next_offset = hits[i + 1].offset if i + 1 < len(hits) else total
            end = min(next_offset, hit.offset + self.max_clip_bytes, total)
            length = max(0, end - hit.offset)
            if length < 4096:
                continue
            safe_name = f"recovered_{len([x for x in hits[:i] if x.path]) + 1:04d}_{hit.offset:012x}{hit.signature.extension}"
            target = out / safe_name
            with open(self.source, "rb") as src, open(target, "wb") as dst:
                src.seek(hit.offset)
                remaining = length
                while remaining and not self.cancelled:
                    data = src.read(min(1024 * 1024, remaining))
                    if not data:
                        break
                    dst.write(data)
                    remaining -= len(data)
            if self.cancelled:
                target.unlink(missing_ok=True)
                break
            hit.size = target.stat().st_size
            hit.path = target
            if validate:
                hit.valid = self._ffprobe_ok(target)
                if export_playable_only and not hit.valid:
                    target.unlink(missing_ok=True)
                    hit.path = None
            if progress:
                progress(total, total, len([h for h in hits if h.path]))
        return hits

    @staticmethod
    def _ffprobe_ok(path: Path) -> bool:
        import shutil, subprocess
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return False
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=20
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            return False
