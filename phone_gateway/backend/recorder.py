import os
from pathlib import Path


class AudioRecorder:
    def __init__(self, session_id: str):
        self.session_id = session_id

        recordings_base = os.getenv("RECORDINGS_DIR", "recordings")
        self.recordings_dir = Path(recordings_base) / "audio"
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        self.file_path = self.recordings_dir / f"{session_id}.pcm"
        self.file = open(self.file_path, "ab")

    def write_chunk(self, chunk: bytes):
        if chunk:
            self.file.write(chunk)
            self.file.flush()

    def close(self) -> str:
        if not self.file.closed:
            self.file.close()

        return str(self.file_path)